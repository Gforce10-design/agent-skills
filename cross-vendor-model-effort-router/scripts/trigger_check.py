#!/usr/bin/env python3
"""Did the Skill tool actually fire for cross-vendor-model-effort-router?

Structural check, not grep: reads `--output-format stream-json --verbose` events and counts
content blocks where type=="tool_use" AND name=="Skill" AND input.skill=="<target>". This
distinguishes a real invocation from the skill merely being listed in the system:init
slash_commands array.

Always runs with --permission-mode plan: the probe queries describe real work ("refactor 8
files"), and without plan mode a fresh agent would carry them out.

Every run preserves its raw evidence (2026-07-26). Before that the verdict was the only thing
that survived: stdout was consumed from a pipe and dropped, stderr went to DEVNULL, and a
probe that produced a surprising answer could not be re-examined — only re-run, at another
turn of the rate-limit window, against a non-deterministic agent. A verdict you cannot replay
is a claim, not a measurement.

    ./trigger_check.py <label> "<query>" [--runs N]
    ./trigger_check.py --replay <run-dir>          # re-derive the verdict from saved bytes

Evidence lives under ~/.local/state/awo-c8/raw (dir 0700, files 0600) and never enters a
repository: it is a transcript of a model session and belongs to this machine.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

TARGET = "cross-vendor-model-effort-router"
LEGACY = "gpt-model-effort-advisor"

EVIDENCE_ROOT = Path.home() / ".local" / "state" / "awo-c8" / "raw"
DIR_MODE = 0o700
FILE_MODE = 0o600

# Argv is recorded so a run can be reproduced, so it must not carry a credential if one is
# ever passed. Shapes, not a wordlist: a wordlist misses the next provider's prefix.
_SECRET_SHAPES = (
    re.compile(r"\b(sk|rk|pk)-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
)
_SECRET_FLAGS = {"--api-key", "--token", "--password", "--secret", "--auth"}


class RawEvidenceError(RuntimeError):
    """Raised instead of returning a verdict derived from evidence we cannot trust."""


def redact_argv(argv):
    """Mask credential-shaped values and anything following a credential flag."""
    out = []
    mask_next = False
    for item in argv:
        if mask_next:
            out.append("<REDACTED>")
            mask_next = False
            continue
        if item in _SECRET_FLAGS:
            out.append(item)
            mask_next = True
            continue
        masked = item
        for shape in _SECRET_SHAPES:
            masked = shape.sub("<REDACTED>", masked)
        out.append(masked)
    return out


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _secure_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, DIR_MODE)
    return path


def classify(events):
    """The verdict, derived only from parsed events.

    Pure on purpose: the first pass and the replay call this same function on the same
    bytes, so a parity mismatch can only mean the bytes changed — never that two code
    paths disagreed about what they mean.
    """
    verdict = None
    other = []
    tool_use_count = 0
    examined = 0
    for event in events:
        examined += 1
        message = event.get("message")
        if isinstance(message, dict):
            for block in message.get("content", []):
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_use_count += 1
                if block.get("name") != "Skill":
                    # A non-Skill tool first means the agent chose to act without routing.
                    verdict = verdict or "miss"
                    continue
                name = (block.get("input") or {}).get("skill")
                if name == TARGET:
                    verdict = "router"
                elif name == LEGACY:
                    verdict = "legacy"
                else:
                    other.append(name)
                    verdict = verdict or "other"
        if verdict:
            break
        if event.get("type") == "result":
            verdict = verdict or "miss"
            break
    return {
        "verdict": verdict or "miss",
        "other": other,
        # Events *examined*, not events supplied. The first pass stops reading at the
        # verdict while a replay is handed the whole saved file, so counting the input
        # made the two disagree by however much the CLI wrote after the decision — a
        # parity failure that meant nothing. The decision prefix is what has to match.
        "event_count": examined,
        "tool_use_count": tool_use_count,
    }


def parse_raw(raw_path, *, complete):
    """Events from saved bytes, refusing rather than guessing at damaged input.

    `complete` says whether the producing run reached a natural end. A run stopped early at
    the verdict legitimately leaves a half-written final line, so a trailing fragment is only
    an error when the stream was supposed to be whole.
    """
    data = Path(raw_path).read_bytes()
    if not data:
        raise RawEvidenceError(f"EMPTY_RAW:{raw_path}")
    text = data.decode("utf-8", errors="strict")
    lines = text.splitlines(keepends=True)
    events = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        last = index == len(lines) - 1
        try:
            events.append(json.loads(stripped))
        except ValueError:
            if last and not line.endswith("\n") and not complete:
                break  # the run was cut at the verdict; the tail is a partial write
            raise RawEvidenceError(f"INVALID_JSON_LINE:{raw_path}:{index + 1}") from None
    if not events:
        raise RawEvidenceError(f"NO_EVENTS:{raw_path}")
    return events


def run_once(query, label, cwd="/tmp", timeout=420, cli="claude", evidence_root=None):
    """Read the event stream and stop the run as soon as the verdict is in.

    The trigger decision is settled at the agent's first tool_use; everything after it is the
    agent doing the actual routing work, which is irrelevant here and can outlast any timeout
    (an observed run was still working past 420s). Killing at the verdict keeps each probe to
    roughly one model turn of the five-hour rate-limit window.

    Both streams go straight to files rather than to pipes. Reading one pipe to EOF while the
    other fills is the classic deadlock, and draining them in turn would mean the run's own
    behaviour depends on which stream the parent happens to read first. Files also give byte
    preservation for free: what the CLI wrote is what is on disk.
    """
    root = _secure_dir(Path(evidence_root or EVIDENCE_ROOT))
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", label)
    run_dir = _secure_dir(root / f"{safe}-{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}")
    out_path, err_path = run_dir / "stdout.raw", run_dir / "stderr.raw"

    cmd = [cli, "-p", query,
           "--permission-mode", "plan",
           "--output-format", "stream-json",
           "--verbose",
           "--no-session-persistence",
           "--disallowedTools", "mcp__*"]

    t0 = time.time()
    started = datetime.now(timezone.utc).isoformat()
    events = []
    verdict_seen = False
    with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
        os.chmod(out_path, FILE_MODE)
        os.chmod(err_path, FILE_MODE)
        process = subprocess.Popen(cmd, cwd=cwd, stdout=out_f, stderr=err_f)
        try:
            with open(out_path, "r", encoding="utf-8") as follow:
                pending = ""
                while True:
                    if process.poll() is not None and not pending:
                        chunk = follow.read()
                        if not chunk:
                            break
                        pending += chunk
                    if time.time() - t0 > timeout:
                        break
                    chunk = follow.read()
                    if chunk:
                        pending += chunk
                    elif process.poll() is None:
                        time.sleep(0.05)
                        continue
                    while "\n" in pending:
                        line, pending = pending.split("\n", 1)
                        if not line.strip():
                            continue
                        try:
                            events.append(json.loads(line))
                        except ValueError:
                            continue
                        decided = classify(events)
                        if decided["verdict"] != "miss" or events[-1].get("type") == "result":
                            verdict_seen = True
                            break
                    if verdict_seen:
                        break
                    if process.poll() is not None and not pending:
                        break
        finally:
            process.terminate()
            try:
                exit_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                exit_code = process.wait()

    result = classify(events)
    complete = not verdict_seen
    metadata = {
        "schema_version": "trigger-check-evidence.v1",
        "label": label,
        "argv_redacted": redact_argv(cmd),
        "cwd": str(cwd),
        "started_utc": started,
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(time.time() - t0, 3),
        "exit_code": exit_code,
        "stopped_at_verdict": verdict_seen,
        "stream_complete": complete,
        "cli_path": shutil.which(cli),
        "cli_sha256": sha256_file(shutil.which(cli)) if shutil.which(cli) else None,
        "script_sha256": sha256_file(__file__),
        "stdout_sha256": sha256_file(out_path),
        "stderr_sha256": sha256_file(err_path),
        "stdout_bytes": out_path.stat().st_size,
        "stderr_bytes": err_path.stat().st_size,
        "first_pass": result,
    }
    metadata_path = run_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
                             encoding="utf-8")
    os.chmod(metadata_path, FILE_MODE)

    dur = metadata["duration_s"]
    print(f"[{label}] {dur:.1f}s verdict={result['verdict']}"
          f"{' ' + str(result['other']) if result['other'] else ''} raw={run_dir}")
    return {"verdict": result["verdict"], "router": 1 if result["verdict"] == "router" else 0,
            "other": result["other"], "dur": dur, "run_dir": str(run_dir),
            "event_count": result["event_count"], "tool_use_count": result["tool_use_count"]}


def replay(run_dir):
    """Re-derive the verdict from saved bytes and prove it matches the first pass.

    Fail-closed at every step: missing metadata, a raw file whose digest no longer matches
    what was recorded, truncated or non-JSON content, and a verdict that differs all raise.
    A replay that silently "fixed" damaged evidence would be worse than no replay, because it
    would look like corroboration.
    """
    run_dir = Path(run_dir)
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.is_file():
        raise RawEvidenceError(f"METADATA_MISSING:{metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    for name, key in (("stdout.raw", "stdout_sha256"), ("stderr.raw", "stderr_sha256")):
        path = run_dir / name
        if not path.is_file():
            raise RawEvidenceError(f"RAW_MISSING:{path}")
        actual = sha256_file(path)
        if actual != metadata.get(key):
            raise RawEvidenceError(f"RAW_DIGEST_MISMATCH:{path}:{actual}")

    events = parse_raw(run_dir / "stdout.raw", complete=metadata.get("stream_complete", True))
    replayed = classify(events)
    first = metadata["first_pass"]
    mismatches = [key for key in ("verdict", "event_count", "tool_use_count", "other")
                  if replayed[key] != first[key]]
    if mismatches:
        raise RawEvidenceError(
            f"REPLAY_DIVERGED:{','.join(mismatches)}:first={first}:replay={replayed}")
    return {"run_dir": str(run_dir), "first_pass": first, "replay": replayed, "parity": True}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label", nargs="?")
    ap.add_argument("query", nargs="?")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--cli", default="claude")
    ap.add_argument("--evidence-root")
    ap.add_argument("--replay", help="re-derive the verdict from a saved run directory")
    args = ap.parse_args()

    if args.replay:
        report = replay(args.replay)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return

    if not args.label or not args.query:
        ap.error("label and query are required unless --replay is given")

    hits = 0
    for index in range(1, args.runs + 1):
        outcome = run_once(args.query, f"{args.label}#{index}",
                           cli=args.cli, evidence_root=args.evidence_root)
        hits += 1 if outcome["router"] else 0
    print(f"[{args.label}] TOTAL {hits}/{args.runs} runs fired the router")


if __name__ == "__main__":
    main()
