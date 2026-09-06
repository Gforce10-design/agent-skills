#!/usr/bin/env python3
"""Tests for trigger_check raw-evidence preservation and replay.

stdlib unittest only (no external dependency; also collectable by pytest), matching
tests/test_router.py. Every test drives a **fake CLI** that emits a canned stream-json
transcript: no provider is contacted, no credential is used, and nothing is paid for. The
property under test is that saved bytes reproduce the verdict — that does not need a real
model, and using one would make the test non-deterministic as well as expensive.

Evidence goes to a temporary root; ~/.local/state/awo-c8 is never touched.

Run:  python3 -m unittest discover -s tests -v      (from the skill directory)
"""
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import trigger_check  # noqa: E402

LIVE_EVIDENCE_ROOT = Path.home() / ".local" / "state" / "awo-c8" / "raw"


def fake_cli(tmp: Path, events, stderr_text="fake cli warning\n", exit_code=0) -> Path:
    """A stand-in for `claude` that prints a fixed transcript and some stderr."""
    payload = json.dumps([json.dumps(event) for event in events])
    script = tmp / "fake-claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"for line in json.loads({payload!r}):\n"
        "    sys.stdout.write(line + '\\n')\n"
        "    sys.stdout.flush()\n"
        f"sys.stderr.write({stderr_text!r})\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    return script


def skill_event(name):
    return {"type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Skill",
                                     "input": {"skill": name}}]}}


class EvidencePreservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.evidence = self.root / "evidence"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def probe(self, events, **kwargs):
        cli = fake_cli(self.root, events, **kwargs)
        return trigger_check.run_once(
            "fixture probe", "fixture", cwd=str(self.root), timeout=30,
            cli=str(cli), evidence_root=self.evidence,
        )

    def test_a_run_preserves_stdout_and_stderr_as_bytes(self):
        outcome = self.probe([skill_event(trigger_check.TARGET),
                              {"type": "result"}])
        run_dir = Path(outcome["run_dir"])
        self.assertEqual(outcome["verdict"], "router")
        self.assertTrue((run_dir / "stdout.raw").is_file())
        stderr_raw = run_dir / "stderr.raw"
        self.assertTrue(stderr_raw.is_file())
        # The control: before this change stderr went to DEVNULL, so a probe that failed
        # for an environmental reason left no trace of why. Non-empty here is the fix.
        self.assertIn("fake cli warning", stderr_raw.read_text(encoding="utf-8"))

    def test_metadata_records_what_is_needed_to_reproduce_and_nothing_more(self):
        outcome = self.probe([skill_event(trigger_check.TARGET), {"type": "result"}])
        metadata = json.loads(
            (Path(outcome["run_dir"]) / "metadata.json").read_text(encoding="utf-8"))
        for key in ("argv_redacted", "cwd", "started_utc", "ended_utc", "exit_code",
                    "cli_sha256", "script_sha256", "stdout_sha256", "stderr_sha256"):
            self.assertIn(key, metadata)
        self.assertNotIn("environment", metadata)
        self.assertNotIn("env", metadata)

    def test_replay_reproduces_the_first_pass_exactly(self):
        outcome = self.probe([skill_event(trigger_check.TARGET), {"type": "result"}])
        report = trigger_check.replay(outcome["run_dir"])
        self.assertTrue(report["parity"])
        self.assertEqual(report["replay"]["verdict"], report["first_pass"]["verdict"])
        self.assertEqual(report["replay"]["event_count"], report["first_pass"]["event_count"])
        self.assertEqual(report["replay"]["tool_use_count"],
                         report["first_pass"]["tool_use_count"])

    def test_each_verdict_class_replays_to_itself(self):
        for events, expected in (
            ([skill_event(trigger_check.TARGET), {"type": "result"}], "router"),
            ([skill_event(trigger_check.LEGACY), {"type": "result"}], "legacy"),
            ([skill_event("some-other-skill"), {"type": "result"}], "other"),
            ([{"type": "result"}], "miss"),
        ):
            with self.subTest(expected=expected):
                outcome = self.probe(events)
                self.assertEqual(outcome["verdict"], expected)
                self.assertEqual(
                    trigger_check.replay(outcome["run_dir"])["replay"]["verdict"], expected)

    def test_a_tampered_raw_file_is_refused_not_reinterpreted(self):
        outcome = self.probe([skill_event(trigger_check.TARGET), {"type": "result"}])
        raw = Path(outcome["run_dir"]) / "stdout.raw"
        raw.write_text(json.dumps(skill_event(trigger_check.LEGACY)) + "\n", encoding="utf-8")
        with self.assertRaises(trigger_check.RawEvidenceError) as caught:
            trigger_check.replay(outcome["run_dir"])
        self.assertIn("RAW_DIGEST_MISMATCH", str(caught.exception))

    def test_truncated_raw_from_a_completed_stream_is_refused(self):
        outcome = self.probe([{"type": "result"}])
        run_dir = Path(outcome["run_dir"])
        raw = run_dir / "stdout.raw"
        raw.write_text('{"type": "resu', encoding="utf-8")
        metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        metadata["stdout_sha256"] = trigger_check.sha256_file(raw)
        metadata["stream_complete"] = True
        (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaises(trigger_check.RawEvidenceError) as caught:
            trigger_check.replay(run_dir)
        self.assertIn("INVALID_JSON_LINE", str(caught.exception))

    def test_missing_evidence_is_refused(self):
        outcome = self.probe([{"type": "result"}])
        run_dir = Path(outcome["run_dir"])
        (run_dir / "stdout.raw").unlink()
        with self.assertRaises(trigger_check.RawEvidenceError) as caught:
            trigger_check.replay(run_dir)
        self.assertIn("RAW_MISSING", str(caught.exception))

        (run_dir / "metadata.json").unlink()
        with self.assertRaises(trigger_check.RawEvidenceError) as caught:
            trigger_check.replay(run_dir)
        self.assertIn("METADATA_MISSING", str(caught.exception))

    def test_evidence_is_written_with_owner_only_permissions(self):
        outcome = self.probe([{"type": "result"}])
        run_dir = Path(outcome["run_dir"])
        self.assertEqual(stat.S_IMODE(run_dir.stat().st_mode), 0o700)
        for name in ("stdout.raw", "stderr.raw", "metadata.json"):
            with self.subTest(name=name):
                self.assertEqual(stat.S_IMODE((run_dir / name).stat().st_mode), 0o600)

    def test_the_live_evidence_root_is_untouched_by_tests(self):
        before = sorted(p.name for p in LIVE_EVIDENCE_ROOT.glob("*")) \
            if LIVE_EVIDENCE_ROOT.is_dir() else []
        self.probe([{"type": "result"}])
        after = sorted(p.name for p in LIVE_EVIDENCE_ROOT.glob("*")) \
            if LIVE_EVIDENCE_ROOT.is_dir() else []
        self.assertEqual(before, after)


class RedactionTests(unittest.TestCase):
    def test_credential_shaped_values_are_masked_in_recorded_argv(self):
        secret = "sk" + "-" + "A" * 32
        argv = ["claude", "-p", f"use {secret} now", "--api-key", secret, "--verbose"]
        redacted = trigger_check.redact_argv(argv)
        joined = " ".join(redacted)
        self.assertNotIn(secret, joined)
        self.assertIn("<REDACTED>", joined)
        # Flags themselves stay, so the command shape is still reproducible.
        self.assertIn("--api-key", redacted)
        self.assertIn("--verbose", redacted)

    def test_ordinary_arguments_survive_redaction(self):
        argv = ["claude", "-p", "refactor 8 files", "--permission-mode", "plan"]
        self.assertEqual(trigger_check.redact_argv(argv), argv)


if __name__ == "__main__":
    unittest.main()
