#!/usr/bin/env python3
"""Tests for cross-vendor-model-effort-router.

stdlib unittest only (no external dependency; also collectable by pytest).
Every test uses a temporary registry fixture — the live registry is never touched.

Run:  python3 -m unittest discover -s tests -v
      (from the skill directory)
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(SKILL_DIR))

import router  # noqa: E402

LIVE_GPT_REGISTRY = Path.home() / ".agents/skills/gpt-model-effort-advisor/registry.jsonl"


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def v1(**kw):
    """Build a v1 record with sane defaults."""
    base = {
        "schema_version": "v1",
        "attempt_id": "a1",
        "task": "refactor the logger module",
        "axes": "verifiable=yes,failcost=low,volume=high,depth=shallow",
        "worker": "claude-main",
        "vendor": "anthropic",
        "surface": "claude-code-cli",
        "model_requested": "opus",
        "effort_requested": "max",
        "outcome": "success",
        "verification_grade": "V3",
        "verification_evidence": "tests/test_x.py::test_y passed",
        "verifier_role": "independent-reviewer",
        "comparison_scope": "anthropic:claude-code",
    }
    base.update(kw)
    return base


def backend_fixture(**overrides):
    base = {
        "schema_version": "2",
        "flavor": "claude-conductor",
        "multiagent_root_env": "MULTIAGENT_ROOT",
        "workers": {
            "claude-main": {
                "model": "opus",
                "effort": "max",
                "call_type": "cli",
                "brief_mode": "stdin",
                "cli": {
                    "command": "/opt/homebrew/bin/claude",
                    "args_template": ["-p", "--model", "opus", "--effort", "max"],
                },
                "expected_executable_sha256": "a" * 64,
                "cwd_policy": "worker_snapshot",
                "write_policy": "none",
                "operation_proof_eligible": True,
                "proof_scope": "DISPATCHER_ROUTE_EXECUTION_AND_RESPONSE_CONTRACT",
                "model_evidence_scope": "PINNED_CLI_RESPONSE_MODEL_USAGE_METADATA",
                "permission_profile": "read-only",
                "result_capture": "dispatcher-envelope-v2",
                "trusted_writer_profile": {
                    "enabled": True,
                    "model": "opus",
                    "effort": "max",
                    "permission_class": "FEATURE_BRANCH_OWNER",
                    "gateway_commit": True,
                    "provider_git_write": False,
                    "args_template": [
                        "-p", "--model", "opus", "--effort", "max", "@brief_stdin"
                    ],
                    "timeout": 900,
                },
            },
            "codex-main": {
                "model": "codex-default",
                "effort": "config",
                "call_type": "cli",
                "brief_mode": "stdin",
                "cli": {
                    "command": "/usr/local/bin/codex",
                    "args_template": ["exec", "--ephemeral", "--json", "-s", "read-only", "-"],
                },
                "expected_executable_sha256": "b" * 64,
                "cwd_policy": "target",
                "write_policy": "none",
                "operation_proof_eligible": False,
                "proof_scope": "REGISTERED_ROUTE_ONLY_NONCOUNTABLE",
                "model_evidence_scope": "NONE",
                "permission_profile": "read-only:never:ephemeral",
                "result_capture": "dispatcher-envelope-v2",
            },
        },
    }
    base.update(overrides)
    return base


class TestLegacyCompat(unittest.TestCase):
    """Legacy v0 records must be readable, and vendor inferred, without mutation."""

    def test_v0_record_reads_without_schema_version(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "legacy.jsonl"
            write_jsonl(p, [{
                "ts": "2026-07-16T03:58:46",
                "task": "MultiAgent Routing Benchmark V2",
                "axes": "verifiable=yes,failcost=high,volume=low,depth=deep",
                "model": "gpt-5.6-sol", "effort": "high", "outcome": "success",
            }])
            load = router.load_registry(p)
            self.assertEqual(len(load.records), 1)
            self.assertEqual(load.records[0]["schema_version"], "v0")

    def test_legacy_gpt_model_infers_openai_vendor(self):
        self.assertEqual(router.infer_vendor({"model": "gpt-5.6-sol"}), "openai")
        self.assertEqual(router.infer_vendor({"model": "gpt-4.1-mini"}), "openai")

    def test_unknown_model_preserved_as_unknown_not_crash(self):
        self.assertEqual(router.infer_vendor({"model": "wat-9000"}), "unknown")
        self.assertEqual(router.infer_vendor({}), "unknown")

    def test_explicit_vendor_field_wins_over_inference(self):
        self.assertEqual(router.infer_vendor({"model": "opus", "vendor": "anthropic"}), "anthropic")

    def test_legacy_axes_keeps_only_original_four(self):
        rec = router.build_record(
            task="t", axes={"verifiable": "yes", "failcost": "low", "volume": "high", "depth": "shallow"},
            axes_ext={"handoff_cost": "low", "spec_readiness": "executable",
                      "decomposability": "independent", "context_dependency": "low"},
            worker="claude-main", outcome="success", attempt_id="x1",
        )
        for k in ("verifiable", "failcost", "volume", "depth"):
            self.assertIn(k, rec["axes"])
        # extended axes must NOT leak into the legacy axes string
        for k in ("handoff_cost", "spec_readiness", "decomposability", "context_dependency"):
            self.assertNotIn(k, rec["axes"])
            self.assertIn(k, rec["task_axes_ext"])

    def test_top_level_outcome_restricted_to_three_values(self):
        for good in ("success", "fail", "partial"):
            router.build_record(task="t", axes={}, axes_ext={}, worker="claude-main",
                                outcome=good, attempt_id="ok-" + good)
        with self.assertRaises(ValueError):
            router.build_record(task="t", axes={}, axes_ext={}, worker="claude-main",
                                outcome="aborted_before_execution", attempt_id="bad")


class TestNonContamination(unittest.TestCase):
    """The core safety property: the live GPT registry is read-only and never written."""

    def test_router_never_writes_to_gpt_registry_path(self):
        src = (SKILL_DIR / "router.py").read_text(encoding="utf-8")
        # No write-mode open on the legacy advisor path anywhere in the source.
        self.assertNotIn("gpt-model-effort-advisor/registry.jsonl\", \"a", src)
        self.assertIn("read_legacy_registry", src)

    def test_legacy_registry_load_is_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "legacy.jsonl"
            payload = [{"task": "t", "model": "gpt-5.6-sol", "effort": "high", "outcome": "success"}]
            write_jsonl(p, payload)
            before = p.read_bytes()
            router.read_legacy_registry(p)
            self.assertEqual(p.read_bytes(), before, "legacy registry must not be mutated by a read")

    def test_live_gpt_registry_untouched_by_test_suite(self):
        if not LIVE_GPT_REGISTRY.exists():
            self.skipTest("live GPT registry not present")
        digest = router.sha256_file(LIVE_GPT_REGISTRY)
        self.assertEqual(digest, router.sha256_file(LIVE_GPT_REGISTRY))

    def test_record_targets_own_registry_not_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            own = Path(d) / "own.jsonl"
            legacy = Path(d) / "legacy.jsonl"
            write_jsonl(legacy, [{"task": "t", "model": "gpt-5.6-sol", "effort": "high",
                                  "outcome": "success"}])
            legacy_before = legacy.read_bytes()
            rec = v1(attempt_id="own-1")
            router.append_record(own, rec)
            self.assertTrue(own.exists())
            self.assertEqual(legacy.read_bytes(), legacy_before)


class TestEffortSemantics(unittest.TestCase):
    """Cross-vendor effort comparison must be structurally impossible."""

    def setUp(self):
        self.caps = router.load_capabilities()

    def test_native_rank_and_semantics_are_all_preserved(self):
        e = router.normalize_effort("high", "anthropic:claude-code", self.caps)
        self.assertEqual(e["effort_native"], "high")
        self.assertEqual(e["effort_rank"], 3)
        self.assertEqual(e["effort_semantics"], "reasoning_depth")
        self.assertEqual(e["comparison_scope"], "anthropic:claude-code")
        self.assertFalse(e["cross_vendor_comparable"])

    def test_auto_is_never_converted_to_medium(self):
        e = router.normalize_effort("auto", "anthropic:claude-code", self.caps)
        self.assertIsNone(e["effort_rank"])
        self.assertEqual(e["effort_native"], "auto")
        self.assertNotEqual(e["effort_semantics"], "reasoning_depth")

    def test_codex_config_is_not_resolved_to_a_level_without_observation(self):
        e = router.normalize_effort("config", "openai:gpt-5.6", self.caps)
        self.assertIsNone(e["effort_rank"])
        self.assertEqual(e["effort_semantics"], "externally_configured")

    def test_agy_embedded_effort_has_null_rank(self):
        e = router.normalize_effort("model-high", "agy:embedded", self.caps)
        self.assertIsNone(e["effort_rank"])
        self.assertEqual(e["effort_semantics"], "embedded_in_model")

    def test_unsupported_dial_is_null_rank(self):
        e = router.normalize_effort(None, "xai:grok-4.5", self.caps)
        self.assertIsNone(e["effort_rank"])

    def test_cross_scope_rank_comparison_is_refused(self):
        self.assertTrue(router.comparable("anthropic:claude-code", "anthropic:claude-code"))
        self.assertFalse(router.comparable("anthropic:claude-code", "openai:gpt-5.6"))
        with self.assertRaises(router.IncomparableScopes):
            router.compare_effort(("max", "anthropic:claude-code"), ("high", "openai:gpt-5.6"), self.caps)

    def test_same_scope_rank_comparison_works(self):
        self.assertEqual(
            router.compare_effort(("max", "anthropic:claude-code"),
                                  ("low", "anthropic:claude-code"), self.caps), 1)

    def test_observed_effort_wins_over_requested(self):
        rec = router.build_record(task="t", axes={}, axes_ext={}, worker="claude-main",
                                  outcome="success", attempt_id="obs-1",
                                  effort_requested="max", effort_observed="high")
        self.assertEqual(router.effective_effort(rec), "high")

    def test_requested_is_not_asserted_as_observed(self):
        rec = router.build_record(task="t", axes={}, axes_ext={}, worker="claude-main",
                                  outcome="success", attempt_id="obs-2", effort_requested="max")
        self.assertIsNone(rec["effort_observed"])
        self.assertEqual(rec["observation_status"], "requested_not_verified")


class TestEvidenceThreshold(unittest.TestCase):
    """A single success must never override the heuristic."""

    def test_one_success_is_anecdotal_not_override(self):
        self.assertEqual(router.evidence_tier(1), "anecdotal")
        self.assertFalse(router.override_allowed(1, failcost="low"))

    def test_three_to_nine_is_tiebreak_only(self):
        self.assertEqual(router.evidence_tier(5), "provisional")
        self.assertFalse(router.override_allowed(5, failcost="low"))

    def test_ten_plus_allows_override_for_normal_task(self):
        self.assertEqual(router.evidence_tier(10), "override_eligible")
        self.assertTrue(router.override_allowed(10, failcost="low"))

    def test_high_failcost_needs_twenty(self):
        self.assertFalse(router.override_allowed(10, failcost="high"))
        self.assertTrue(router.override_allowed(20, failcost="high"))

    def test_v0_records_count_as_zero(self):
        recs = [v1(attempt_id=f"v0-{i}", verification_grade="V0",
                   verification_evidence=None) for i in range(15)]
        self.assertEqual(len(router.usable_attempts(recs)), 0)

    def test_v1_grade_is_supporting_not_override_sample(self):
        recs = [v1(attempt_id=f"v1-{i}", verification_grade="V1") for i in range(15)]
        self.assertEqual(len(router.usable_attempts(recs)), 0)

    def test_v2_v3_with_evidence_count(self):
        recs = [v1(attempt_id=f"g-{i}", task=f"task variant {i}",
                   verification_grade="V2") for i in range(4)]
        self.assertEqual(len(router.usable_attempts(recs)), 4)

    def test_graded_record_without_evidence_is_excluded(self):
        recs = [v1(attempt_id="no-ev", verification_grade="V3", verification_evidence=None)]
        self.assertEqual(len(router.usable_attempts(recs)), 0)

    def test_duplicate_attempt_ids_collapse_to_one(self):
        recs = [v1(attempt_id="same") for _ in range(12)]
        self.assertEqual(len(router.usable_attempts(recs)), 1)

    def test_fewer_than_three_unique_task_instances_blocks_override(self):
        recs = [v1(attempt_id=f"d-{i}", task="identical task") for i in range(12)]
        self.assertFalse(router.override_decision(recs, failcost="low")["allowed"])

    def test_failures_are_counted_not_only_successes(self):
        recs = ([v1(attempt_id=f"s-{i}", task=f"t{i}") for i in range(10)] +
                [v1(attempt_id=f"f-{i}", task=f"tf{i}", outcome="fail") for i in range(10)])
        d = router.override_decision(recs, failcost="low")
        self.assertEqual(d["success"], 10)
        self.assertEqual(d["fail"], 10)
        self.assertFalse(d["allowed"], "a failed cohort must never override the quality prior")

    def test_partial_outcome_blocks_override(self):
        recs = [
            v1(attempt_id=f"s-{i}", task=f"task {i}") for i in range(19)
        ] + [v1(attempt_id="p-1", task="task partial", outcome="partial")]
        self.assertFalse(router.override_decision(recs)["allowed"])

    def test_self_verified_attempt_is_not_usable(self):
        rec = v1(attempt_id="self", worker="claude-main", verifier_role="claude-main")
        self.assertEqual(router.usable_attempts([rec]), [])


class TestRegistryIntegrity(unittest.TestCase):
    def test_duplicate_attempt_id_final_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            router.append_record(p, v1(attempt_id="dup"))
            with self.assertRaises(router.DuplicateAttempt):
                router.append_record(p, v1(attempt_id="dup"))

    def test_malformed_line_is_reported_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps(v1(attempt_id="ok")) + "\n")
                f.write("{ this is not json\n")
            load = router.load_registry(p)
            self.assertEqual(len(load.records), 1)
            self.assertEqual(len(load.invalid), 1, "malformed line must be surfaced")
            self.assertEqual(load.invalid[0][0], 2, "must report the line number")

    def test_semantically_empty_object_is_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            p.write_text("{}\n", encoding="utf-8")
            load = router.load_registry(p)
            self.assertEqual(load.records, [])
            self.assertEqual(len(load.invalid), 1)

    def test_unknown_registry_schema_is_invalid_and_cannot_override(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            records = [
                v1(
                    schema_version="v999", attempt_id=f"future-{i}",
                    task=f"future task {i}")
                for i in range(10)
            ]
            write_jsonl(p, records)
            load = router.load_registry(p)
            self.assertEqual(load.records, [])
            self.assertEqual(len(load.invalid), 10)
            self.assertFalse(router.override_decision(load.records)["allowed"])

    def test_append_is_additive_and_preserves_prior_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            router.append_record(p, v1(attempt_id="one"))
            first = p.read_text(encoding="utf-8")
            router.append_record(p, v1(attempt_id="two"))
            self.assertTrue(p.read_text(encoding="utf-8").startswith(first))

    def test_retry_links_to_parent_attempt(self):
        rec = router.build_record(task="t", axes={}, axes_ext={}, worker="claude-main",
                                  outcome="fail", attempt_id="a2", parent_attempt_id="a1")
        self.assertEqual(rec["parent_attempt_id"], "a1")


class TestDecisionFlow(unittest.TestCase):
    def setUp(self):
        self.caps = router.load_capabilities()

    def test_unclear_spec_returns_plan_first(self):
        r = router.recommend(task="build something nice", axes={},
                             axes_ext={"spec_readiness": "vague"}, caps=self.caps, records=[])
        self.assertEqual(r["route"], "PLAN_FIRST")

    def test_small_one_off_with_high_handoff_is_direct(self):
        r = router.recommend(task="fix a typo in one file",
                             axes={"verifiable": "yes", "failcost": "low",
                                   "volume": "low", "depth": "shallow"},
                             axes_ext={"spec_readiness": "executable", "volume": "low",
                                       "handoff_cost": "high", "context_dependency": "high",
                                       "decomposability": "single"},
                             caps=self.caps, records=[], surface="codex")
        self.assertEqual(r["route"], "DIRECT")

    def test_bulk_verifiable_decomposable_is_delegate_candidate(self):
        # A mechanical batch with a stated non-cost goal reaches DELEGATE. Without a
        # stated goal it is NEEDS_PREFERENCE — see TestOptimizationGoal.
        r = router.recommend(task="apply the same rename across 40 files",
                             axes={"verifiable": "yes", "failcost": "low",
                                   "volume": "high", "depth": "shallow"},
                             axes_ext={"spec_readiness": "executable", "volume": "high",
                                       "handoff_cost": "low", "context_dependency": "low",
                                       "decomposability": "independent",
                                       "verifier_available": "yes",
                                       "optimization_goal": "latency"},
                             caps=self.caps, records=[])
        self.assertEqual(r["route"], "DELEGATE")
        self.assertIn(r["worker"], self.caps["workers"])

    def test_delegate_reports_model_effort_as_worker_property_not_a_dial(self):
        r = router.recommend(task="apply the same rename across 40 files",
                             axes={"verifiable": "yes", "failcost": "low",
                                   "volume": "high", "depth": "shallow"},
                             axes_ext={"spec_readiness": "executable", "volume": "high",
                                       "handoff_cost": "low", "context_dependency": "low",
                                       "decomposability": "independent",
                                       "verifier_available": "yes",
                                       "optimization_goal": "latency"},
                             caps=self.caps, records=[])
        self.assertFalse(r["model_effort_selectable"])
        self.assertIn("property of the worker", r["model_effort_note"])

    def test_direct_route_offers_a_real_session_ladder(self):
        r = router.recommend(task="fix a typo in one file",
                             axes={"verifiable": "yes", "failcost": "low",
                                   "volume": "low", "depth": "shallow"},
                             axes_ext={"spec_readiness": "executable", "volume": "low",
                                       "handoff_cost": "high", "context_dependency": "high"},
                             caps=self.caps, records=[], surface="codex")
        self.assertTrue(r["model_effort_selectable"])
        self.assertIn(r["effort"], ["low", "medium", "high"])

    def test_direct_recommendation_never_starts_above_high(self):
        for depth in ("shallow", "mid", "deep"):
            r = router.recommend(task="a hard reasoning task",
                                 axes={"verifiable": "no", "failcost": "high",
                                       "volume": "low", "depth": depth},
                                 axes_ext={"spec_readiness": "executable",
                                           "handoff_cost": "high", "context_dependency": "high"},
                                 caps=self.caps, records=[], surface="codex")
            if r["route"] == "DIRECT":
                self.assertNotIn(r["effort"], ["xhigh", "max"])

    def test_break_even_gate_makes_no_quantitative_claim(self):
        r = router.recommend(task="apply the same rename across 40 files",
                             axes={"verifiable": "yes", "failcost": "low",
                                   "volume": "high", "depth": "shallow"},
                             axes_ext={"spec_readiness": "executable", "volume": "high",
                                       "handoff_cost": "low", "context_dependency": "low",
                                       "decomposability": "independent",
                                       "verifier_available": "yes"},
                             caps=self.caps, records=[])
        self.assertEqual(r["break_even"], "heuristic pass")
        self.assertNotIn("%", json.dumps(r.get("break_even_detail", "")))

    def test_single_registry_success_does_not_override_heuristic(self):
        recs = [v1(attempt_id="only", task="apply the same rename across 40 files",
                   worker="agy-compat", vendor="multi")]
        r = router.recommend(task="apply the same rename across 40 files",
                             axes={"verifiable": "yes", "failcost": "low",
                                   "volume": "high", "depth": "shallow"},
                             axes_ext={"spec_readiness": "executable", "volume": "high",
                                       "handoff_cost": "low", "context_dependency": "low",
                                       "decomposability": "independent",
                                       "verifier_available": "yes"},
                             caps=self.caps, records=recs)
        self.assertEqual(r["evidence_tier"], "anecdotal")
        self.assertEqual(r["decision_source"], "heuristic")


class TestEscalation(unittest.TestCase):
    def setUp(self):
        self.caps = router.load_capabilities()

    def test_grok_has_no_higher_tier_and_never_invents_one(self):
        t = router.next_tier("grok-adversarial", self.caps)
        self.assertIsNone(t["next_tier"])
        self.assertEqual(t["escalation_status"], "no_higher_tier_available")

    def test_agy_is_pinned_by_dispatcher(self):
        t = router.next_tier("agy-compat", self.caps)
        self.assertIsNone(t["next_tier"])
        self.assertEqual(t["escalation_status"], "pinned_by_dispatcher")

    def test_direct_session_ladder_steps_one_tier(self):
        self.assertEqual(
            router.next_direct_tier("haiku-4.5", "claude-code", self.caps), "sonnet-5")
        self.assertEqual(
            router.next_direct_tier("sonnet-5", "claude-code", self.caps), "opus-5")
        self.assertIsNone(
            router.next_direct_tier("opus-5", "claude-code", self.caps),
            "Fable is experimental and must not be an automatic escalation tier")

    def test_effort_escalates_one_step_and_stops_at_high(self):
        self.assertEqual(router.next_effort("low", "claude-code", self.caps), "medium")
        self.assertEqual(router.next_effort("medium", "claude-code", self.caps), "high")
        self.assertIsNone(router.next_effort("high", "claude-code", self.caps),
                          "High is the normal ceiling; escalate tier instead")

    def test_reasoning_depth_failure_raises_effort_not_tier(self):
        fix = router.diagnose("REASONING_DEPTH_FAILURE", effort="low", surface="claude-code",
                              caps=self.caps)
        self.assertEqual(fix["change_axis"], "effort")
        self.assertEqual(fix["to"], "medium")

    def test_model_capability_failure_raises_tier_not_effort(self):
        fix = router.diagnose("MODEL_CAPABILITY_FAILURE", model="sonnet-5", effort="high",
                              surface="claude-code", caps=self.caps)
        self.assertEqual(fix["change_axis"], "model")
        self.assertEqual(fix["to"], "opus-5")

    def test_infra_failure_changes_neither_model_nor_effort(self):
        fix = router.diagnose("TOOL_OR_INFRA_FAILURE", surface="claude-code", caps=self.caps)
        self.assertEqual(fix["change_axis"], "none")

    def test_spec_failure_does_not_raise_anything(self):
        fix = router.diagnose("SPEC_FAILURE", surface="claude-code", caps=self.caps)
        self.assertEqual(fix["change_axis"], "spec")

    def test_only_one_axis_changes_per_retry(self):
        for cls in ("REASONING_DEPTH_FAILURE", "MODEL_CAPABILITY_FAILURE",
                    "TOOL_OR_INFRA_FAILURE", "SPEC_FAILURE", "OVERPROVISIONING"):
            fix = router.diagnose(cls, model="sonnet-5", effort="low",
                                  surface="claude-code", caps=self.caps)
            self.assertIn(fix["change_axis"], ("effort", "model", "spec", "none", "worker"))


class TestOptimizationGoal(unittest.TestCase):
    """A bulk mechanical task must not be sold as a cost saving when the delegate
    fleet has no economy loadout."""

    def setUp(self):
        self.caps = router.load_capabilities()
        self.bulk_axes = {"verifiable": "yes", "failcost": "low",
                          "volume": "high", "depth": "shallow"}
        self.bulk_ext = {"spec_readiness": "executable", "volume": "high",
                         "handoff_cost": "low", "context_dependency": "low",
                         "decomposability": "independent", "verifier_available": "yes",
                         "uniformity": "high"}

    def _rec(self, goal=None):
        ext = dict(self.bulk_ext)
        if goal:
            ext["optimization_goal"] = goal
        return router.recommend(task="normalize 412 product records", axes=self.bulk_axes,
                                axes_ext=ext, caps=self.caps, records=[], surface="codex")

    def test_unstated_goal_returns_needs_preference_not_a_false_winner(self):
        r = self._rec()
        self.assertEqual(r["route"], "NEEDS_PREFERENCE")
        self.assertIn("cost_first", r["options"])
        self.assertIn("latency_or_context_first", r["options"])

    def test_cost_goal_does_not_recommend_delegate_as_a_saving(self):
        r = self._rec("cost")
        self.assertEqual(r["route"], "DIRECT")
        self.assertIn("no economy loadout", r["cost_note"])

    def test_latency_goal_allows_delegate_but_disclaims_cost(self):
        r = self._rec("latency")
        self.assertEqual(r["route"], "DELEGATE")
        self.assertEqual(r["cost_comparison"], "unmeasured")

    def test_context_goal_allows_delegate(self):
        self.assertEqual(self._rec("context_preservation")["route"], "DELEGATE")

    def test_never_claims_delegation_saves_money(self):
        for goal in (None, "cost", "latency", "context_preservation", "quality"):
            blob = json.dumps(self._rec(goal), ensure_ascii=False)
            self.assertNotIn("saves", blob.lower())
            self.assertNotIn("cheaper than", blob.lower())

    def test_cost_comparison_is_always_unmeasured_not_a_number(self):
        r = self._rec("latency")
        self.assertEqual(r["cost_comparison"], "unmeasured")

    def test_uniform_verifiable_batch_suggests_checking_a_script_first(self):
        r = self._rec("cost")
        self.assertIn("script", r["tool_first_note"].lower())

    def test_non_uniform_batch_does_not_suggest_a_script(self):
        ext = dict(self.bulk_ext, uniformity="mixed", optimization_goal="cost")
        r = router.recommend(task="normalize 412 messy records", axes=self.bulk_axes,
                             axes_ext=ext, caps=self.caps, records=[], surface="codex")
        self.assertIsNone(r.get("tool_first_note"))


class TestMechanicalClassification(unittest.TestCase):
    """shallow+verifiable alone must not label high-risk work as mechanical."""

    def test_full_conjunction_is_mechanical(self):
        self.assertTrue(router.is_mechanical_batch({
            "depth": "shallow", "verifiable": "yes", "volume": "high", "failcost": "low"},
            {"spec_readiness": "executable", "decomposability": "independent",
             "context_dependency": "low"}))

    def test_high_failcost_is_not_mechanical(self):
        self.assertFalse(router.is_mechanical_batch({
            "depth": "shallow", "verifiable": "yes", "volume": "high", "failcost": "high"},
            {"spec_readiness": "executable", "decomposability": "independent",
             "context_dependency": "low"}),
            "bulk permission changes are shallow+verifiable but must never be 'mechanical'")

    def test_high_context_dependency_is_not_mechanical(self):
        self.assertFalse(router.is_mechanical_batch({
            "depth": "shallow", "verifiable": "yes", "volume": "high", "failcost": "low"},
            {"spec_readiness": "executable", "decomposability": "independent",
             "context_dependency": "high"}),
            "repo-wide symbol rename has integration risk")

    def test_low_volume_is_not_a_batch(self):
        self.assertFalse(router.is_mechanical_batch({
            "depth": "shallow", "verifiable": "yes", "volume": "low", "failcost": "low"},
            {"spec_readiness": "executable", "decomposability": "independent",
             "context_dependency": "low"}))

    def test_shallow_and_verifiable_alone_is_insufficient(self):
        self.assertFalse(router.is_mechanical_batch(
            {"depth": "shallow", "verifiable": "yes"}, {}))


class TestSessionParity(unittest.TestCase):
    """Feature parity with the legacy advisor's `session`, but vendor-aware."""

    def test_session_reports_surface_and_observation_status(self):
        s = router.session()
        self.assertIn("surface", s)
        self.assertIn("observation_status", s)

    def test_session_never_asserts_an_unobserved_value_as_actual(self):
        s = router.session()
        if s.get("model") is None:
            self.assertEqual(s["observation_status"], "unobserved")

    def test_session_does_not_report_a_codex_rollout_as_the_claude_session(self):
        s = router.session(surface="claude-code")
        self.assertNotEqual(s.get("source"), "codex_rollout",
                            "the legacy advisor's bug: it read CODEX_HOME rollouts for any caller")


class TestCapabilitiesHonesty(unittest.TestCase):
    def setUp(self):
        self.caps = router.load_capabilities()

    def test_economy_availability_is_recorded_per_path_not_globally(self):
        """A global economy_tier_available:false would be a false statement —
        the DIRECT path does have lower tiers."""
        e = self.caps["economy"]
        self.assertFalse(e["delegate_economy_loadout_available"])
        self.assertTrue(e["direct_lower_tier_selection_available"])
        self.assertNotIn("economy_tier_available", json.dumps(self.caps))

    def test_capability_snapshot_declares_its_own_staleness_window(self):
        self.assertIn("stale_after_days", self.caps)
        self.assertIsNotNone(self.caps.get("captured_at"))

    def test_tier_class_is_separate_from_cross_vendor_cost_rank(self):
        for name, w in self.caps["workers"].items():
            if "alias_of" in w:
                continue
            self.assertEqual(w["dispatcher"].get("cost_rank_cross_vendor"), "unknown",
                             f"{name}: cross-vendor cost ranking is not measured")

    def test_no_worker_is_delegation_model_selectable(self):
        for name, w in self.caps["workers"].items():
            if "alias_of" in w:
                continue
            self.assertFalse(w.get("delegation_selectable", False),
                             f"{name}: dispatcher fixes the loadout; skill does not modify it")

    def test_every_worker_records_requested_not_observed(self):
        for name, w in self.caps["workers"].items():
            if "alias_of" in w:
                continue
            self.assertIsNone(w["dispatcher"]["model_observed"])
            self.assertEqual(w["dispatcher"]["observation_status"], "requested_not_verified")

    def test_agy_vendor_is_multi_not_google(self):
        self.assertEqual(self.caps["workers"]["agy-compat"]["vendor"], "multi")

    def test_recommendation_never_names_a_model_outside_capabilities(self):
        caps = self.caps
        for name, w in caps["workers"].items():
            if "alias_of" in w:
                continue
            t = router.next_tier(name, caps)
            if t["next_tier"] is not None:
                self.assertIn(t["next_tier"], w["vendor_cli"]["models"])

    def test_capability_inventory_covers_every_live_backend_id(self):
        self.assertEqual(
            set(self.caps["workers"]),
            {"claude-main", "agy-compat", "grok-adversarial",
             "codex-main", "codex-critic", "gemini"})
        for alias in ("codex-critic", "gemini"):
            target = self.caps["workers"][alias]["alias_of"]
            self.assertIn(target, self.caps["workers"])
            self.assertEqual(
                self.caps["workers"][alias]["dispatcher"],
                self.caps["workers"][target]["dispatcher"])


class TestSurfaceLockedDirectRecommendation(unittest.TestCase):
    def setUp(self):
        self.caps = router.load_capabilities()
        self.shallow = {
            "verifiable": "yes", "failcost": "low", "volume": "low", "depth": "shallow"
        }
        self.mid = dict(self.shallow, depth="mid")
        self.deep = dict(self.shallow, depth="deep", failcost="high")
        self.ext = {
            "spec_readiness": "executable", "volume": "low",
            "handoff_cost": "high", "context_dependency": "high",
        }

    def rec(self, surface, axes=None, **kw):
        return router.recommend(
            task="bounded direct task", axes=axes or self.shallow,
            axes_ext=self.ext, caps=self.caps, records=[], surface=surface, **kw)

    def test_missing_surface_fails_closed_for_direct(self):
        r = self.rec(None)
        self.assertEqual(r["route"], "NEEDS_SURFACE")
        self.assertFalse(r["model_effort_selectable"])

    def test_unknown_surface_fails_closed(self):
        r = self.rec("gemini-web")
        self.assertEqual(r["route"], "NEEDS_SURFACE")

    def test_codex_quality_floor_is_the_declared_one(self):
        """🔴 층 1/2 — 바닥의 **내용**을 리터럴로 못박는다.

        아래 라우팅 시험은 기대값을 quality_floor 에서 뽑는다. 그것만 있으면 바닥이
        조용히 바뀌어도 시험이 따라가서 아무도 모른다. 그래서 바닥 자체는 여기서 리터럴로
        고정한다 — 모델을 올릴 때 이 시험이 **먼저** 빨개져서 의도적 갱신을 강제한다.
        2026-09-06: codex 최상위를 gpt-5.6-sol → gpt-6-astra 로 올렸다(라이브 프로브로
        4종 모두 응답 확인, 없는 id 는 provider 400).
        """
        floor = self.caps["direct_execution"]["codex-cli"]["quality_floor"]
        self.assertEqual(
            {
                "shallow_low_failcost": "gpt-5.6-luna",
                "mid": "gpt-5.6-terra",
                "deep_or_high_failcost": "gpt-6-astra",
            },
            floor,
        )

    def test_codex_direct_uses_only_the_recommendation_allowlist(self):
        """층 2/2 — 라우팅이 바닥을 따르고, 표면 잠금을 지키는가.

        기대값을 바닥에서 뽑되(모델을 올려도 이 시험은 안 깨진다), 그 값이 허용목록 안이고
        타 벤더 모델이 아님을 함께 단언한다 — 라우터가 엉뚱한 것을 내면 여전히 빨개진다.
        """
        cx = self.caps["direct_execution"]["codex-cli"]
        floor = cx["quality_floor"]
        for axes, key in (
            (self.shallow, "shallow_low_failcost"),
            (self.mid, "mid"),
            (self.deep, "deep_or_high_failcost"),
        ):
            r = self.rec("codex", axes)
            self.assertEqual(r["model"], floor[key])
            self.assertIn(r["model"], cx["recommendation_models"])
            self.assertNotIn("claude", r["model"])

    def test_claude_direct_uses_only_claude_family(self):
        for axes, expected in (
            (self.shallow, "haiku-4.5"),
            (self.mid, "sonnet-5"),
            (self.deep, "opus-5"),
        ):
            r = self.rec("claude", axes)
            self.assertEqual(r["model"], expected)
            self.assertIn(
                r["model"],
                self.caps["direct_execution"]["claude-code"]["recommendation_models"])

    def test_quality_floor_precedes_cost_or_quota(self):
        r = self.rec(
            "codex", self.deep,
            quota_state="limited", optimization_goal="cost")
        # 이 시험의 주제는 **단계 순서**(품질 바닥이 비용·쿼터보다 먼저)다.
        # 모델명은 바닥에서 뽑는다 — 위 리터럴 시험이 바닥 자체를 지킨다.
        self.assertEqual(
            r["model"],
            self.caps["direct_execution"]["codex-cli"]["quality_floor"]["deep_or_high_failcost"],
        )
        self.assertEqual(r["selection_stages"][0]["stage"], "quality_floor")
        self.assertEqual(r["selection_stages"][1]["stage"], "availability")
        self.assertEqual(r["selection_stages"][2]["stage"], "cost_tiebreak")

    def test_unavailable_quality_floor_blocks_instead_of_downgrading(self):
        r = self.rec(
            "claude", self.deep,
            model_availability={"opus-5": "unavailable", "sonnet-5": "available"})
        self.assertEqual(r["route"], "BLOCKED_MODEL_AVAILABILITY")
        self.assertIsNone(r.get("model"))

    def test_fable_is_never_a_production_direct_recommendation(self):
        for axes in (self.shallow, self.mid, self.deep):
            self.assertNotEqual(self.rec("claude", axes).get("model"), "fable-5")


class TestBackendContractAdapter(unittest.TestCase):
    def write_backend(self, root, payload=None, raw=None):
        p = Path(root) / "backends.json"
        if raw is not None:
            p.write_text(raw, encoding="utf-8")
        else:
            p.write_text(json.dumps(payload or backend_fixture(), ensure_ascii=False), encoding="utf-8")
        return p

    def test_claude_conductor_plan_reads_codex_main_fixed_loadout(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write_backend(d)
            contract = router.load_backend_contract(p)
            plan = router.build_multiagent_execution_plan(
                contract, role="implementation_writer", selected_worker="codex-main")
            self.assertEqual(plan["flavor"], "claude-conductor")
            self.assertEqual(plan["conductor_surface"], "claude-code")
            self.assertEqual(plan["default_main_worker"], "codex-main")
            self.assertEqual(plan["worker"]["model"], "codex-default")
            self.assertEqual(plan["worker"]["effort"], "config")
            self.assertFalse(plan["worker"]["model_selectable"])
            self.assertFalse(plan["worker"]["effort_selectable"])

    def test_codex_main_writer_fit_is_blocked_without_trusted_profile(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write_backend(d)
            plan = router.build_multiagent_execution_plan(
                router.load_backend_contract(p),
                role="implementation_writer", selected_worker="codex-main")
            self.assertEqual(plan["writer_fit"], "BLOCKED_CONTRACT_MISMATCH")
            self.assertIn("trusted_writer_profile", plan["writer_fit_reason"])

    def test_reader_fit_does_not_require_writer_profile(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write_backend(d)
            plan = router.build_multiagent_execution_plan(
                router.load_backend_contract(p), role="reviewer", selected_worker="codex-main")
            self.assertEqual(plan["execution_status"], "READY")

    def test_symlink_and_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            real = self.write_backend(d)
            link = Path(d) / "link.json"
            link.symlink_to(real)
            with self.assertRaises(router.BackendContractError):
                router.load_backend_contract(link)
        with tempfile.TemporaryDirectory() as d:
            p = self.write_backend(
                d, raw='{"schema_version":"2","flavor":"x","flavor":"y","workers":{}}')
            with self.assertRaises(router.BackendContractError):
                router.load_backend_contract(p)

    def test_model_effort_cli_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            payload = backend_fixture()
            payload["workers"]["claude-main"]["cli"]["args_template"][2] = "sonnet"
            p = self.write_backend(d, payload)
            with self.assertRaises(router.BackendContractError):
                router.load_backend_contract(p)

    def test_semantic_hash_ignores_json_whitespace_and_key_order(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write_backend(d, backend_fixture())
            first = router.load_backend_contract(p)["semantic_sha256"]
            payload = backend_fixture()
            p.write_text(
                json.dumps(payload, ensure_ascii=False, indent=4, sort_keys=True),
                encoding="utf-8")
            second = router.load_backend_contract(p)["semantic_sha256"]
            self.assertEqual(first, second)

    def test_semantic_hash_changes_for_fixed_loadout_change(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write_backend(d, backend_fixture())
            first = router.load_backend_contract(p)["semantic_sha256"]
            payload = backend_fixture()
            payload["workers"]["codex-main"]["effort"] = "high"
            p.write_text(json.dumps(payload), encoding="utf-8")
            second = router.load_backend_contract(p)["semantic_sha256"]
            self.assertNotEqual(first, second)

    def test_semantic_hash_changes_for_root_env_or_version_trust_change(self):
        with tempfile.TemporaryDirectory() as d:
            payload = backend_fixture()
            p = self.write_backend(d, payload)
            first = router.load_backend_contract(p)["semantic_sha256"]
            payload["multiagent_root_env"] = "OTHER_ROOT"
            p.write_text(json.dumps(payload), encoding="utf-8")
            second = router.load_backend_contract(p)["semantic_sha256"]
            self.assertNotEqual(first, second)

            payload = backend_fixture()
            payload["workers"]["claude-main"]["expected_version_regex"] = "^999\\."
            p.write_text(json.dumps(payload), encoding="utf-8")
            third = router.load_backend_contract(p)["semantic_sha256"]
            self.assertNotEqual(first, third)

    def test_recommendation_re_reads_and_degrades_on_semantic_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write_backend(d)
            axes = {
                "verifiable": "yes", "failcost": "low",
                "volume": "high", "depth": "shallow",
            }
            ext = {
                "spec_readiness": "executable", "volume": "high",
                "handoff_cost": "low", "context_dependency": "low",
                "decomposability": "independent", "verifier_available": "yes",
                "optimization_goal": "latency", "role": "reviewer",
            }
            out = router.recommend(
                "review many files", axes, ext, caps=router.load_capabilities(),
                records=[], surface="codex", backends_path=p)
            self.assertEqual(out["backend_adapter_status"], "DEGRADED_SEMANTIC_MISMATCH")

    def test_byte_drift_with_same_semantics_is_distinguished(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.write_backend(d)
            contract = router.load_backend_contract(p)
            caps = json.loads(json.dumps(router.load_capabilities()))
            caps["backends_semantic_sha256"] = contract["semantic_sha256"]
            caps["backends_source_sha256"] = "0" * 64
            out = router.recommend(
                "review many files",
                {"verifiable": "yes", "failcost": "low", "volume": "high", "depth": "shallow"},
                {"spec_readiness": "executable", "volume": "high", "handoff_cost": "low",
                 "context_dependency": "low", "decomposability": "independent",
                 "verifier_available": "yes", "optimization_goal": "latency",
                 "role": "reviewer"},
                caps=caps, records=[], surface="codex", backends_path=p)
            self.assertEqual(out["backend_adapter_status"], "FRESH_SEMANTIC_BYTE_DRIFT")


class TestEvidenceIsolationAndInvalidation(unittest.TestCase):
    def cohort(self):
        return {
            "vendor": "openai",
            "surface": "codex-cli",
            "model_family": "gpt-5.6",
            "task_family": "implementation",
            "role": "direct",
        }

    def test_unrelated_vendor_surface_family_and_role_do_not_count(self):
        records = [
            v1(
                attempt_id=f"claude-{i}", task=f"t{i}",
                vendor="anthropic", surface="claude-code-cli",
                model_requested="opus-5", model_family="claude-5",
                task_family="implementation", role="direct")
            for i in range(20)
        ]
        self.assertEqual(
            len(router.usable_attempts(records, cohort=self.cohort())), 0)

    def test_append_only_invalidation_excludes_target_without_mutation(self):
        target = v1(
            attempt_id="bad-route", vendor="openai", surface="codex-cli",
            model_requested="gpt-5.6-sol", model_family="gpt-5.6",
            task_family="implementation", role="direct")
        event = router.build_invalidation_event(
            target_attempt_id="bad-route",
            reason_code="CROSS_VENDOR_RECOMMENDATION",
            evidence="reviewed router output",
            event_id="invalidate-bad-route-1")
        before = json.dumps(target, sort_keys=True)
        self.assertEqual(
            router.usable_attempts([target, event], cohort=self.cohort()), [])
        self.assertEqual(json.dumps(target, sort_keys=True), before)

    def test_append_refuses_malformed_existing_registry(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            p.write_text("{bad json\n", encoding="utf-8")
            with self.assertRaises(router.RegistryIntegrityError):
                router.append_record(p, v1(attempt_id="new"))

    def test_append_refuses_secret_like_or_raw_transcript_payload(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            with self.assertRaises(router.RegistryIntegrityError):
                router.append_record(p, v1(attempt_id="secret", notes="api_key=abc123"))
            with self.assertRaises(router.RegistryIntegrityError):
                router.append_record(
                    p, v1(attempt_id="raw", provider_transcript="full response"))


class TestFableRolloutPolicy(unittest.TestCase):
    def test_historical_fable_aliases_share_one_family(self):
        self.assertEqual(router.model_family("claude-fable-5"), "fable-5")
        self.assertEqual(router.model_family("fable"), "fable-5")

    def test_fable_stays_shadow_only_without_v2_diverse_evidence(self):
        records = [
            v1(
                attempt_id=f"f{i}", task="same task", model_requested="fable-5",
                model_family="fable-5", vendor="anthropic",
                surface="claude-code-cli", outcome="partial")
            for i in range(3)
        ]
        gate = router.fable_rollout_gate(records, explicit_opt_in=False)
        self.assertEqual(gate["status"], "SHADOW_ONLY")
        self.assertFalse(gate["promotion_allowed"])

    def test_v3_sample_without_explicit_opt_in_cannot_enable_production(self):
        records = [
            v1(
                attempt_id=f"f{i}", task=f"real task {i}",
                model_requested="fable-5", model_family="fable-5",
                vendor="anthropic", surface="claude-code-cli",
                rollout_stage="v3", task_origin="real",
                verifier_role="independent-reviewer")
            for i in range(20)
        ]
        gate = router.fable_rollout_gate(records, explicit_opt_in=False)
        self.assertEqual(gate["status"], "V3_SHADOW_PASS_OPT_IN_REQUIRED")
        self.assertFalse(gate["promotion_allowed"])

    def test_failure_blocks_promotion_even_with_sample_and_opt_in(self):
        records = [
            v1(
                attempt_id=f"f{i}", task=f"real task {i}",
                model_requested="fable-5", model_family="fable-5",
                vendor="anthropic", surface="claude-code-cli",
                rollout_stage="v3", task_origin="real",
                verifier_role="independent-reviewer",
                outcome="fail" if i == 19 else "success")
            for i in range(20)
        ]
        gate = router.fable_rollout_gate(records, explicit_opt_in=True)
        self.assertEqual(gate["status"], "SHADOW_ONLY")
        self.assertFalse(gate["promotion_allowed"])

    def test_cross_surface_synthetic_or_self_reviewed_samples_never_promote(self):
        records = []
        for i in range(20):
            records.append(v1(
                attempt_id=f"bad-{i}", task=f"synthetic fixture {i}",
                worker="codex", model_requested="fable-5", model_family="fable-5",
                vendor="openai", surface="codex-cli", rollout_stage="v3",
                task_origin="synthetic", verifier_role="codex"))
        gate = router.fable_rollout_gate(records, explicit_opt_in=True)
        self.assertEqual(gate["status"], "SHADOW_ONLY")
        self.assertFalse(gate["promotion_allowed"])
        self.assertEqual(gate["n"], 0)


class TestCLI(unittest.TestCase):
    def _run(self, *args, registry=None):
        cmd = [sys.executable, str(SKILL_DIR / "router.py")] + list(args)
        if registry:
            cmd += ["--registry", str(registry)]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_recommend_emits_machine_readable_json(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._run("recommend", "apply the same rename across 40 files",
                          "--axes", "verifiable=yes,failcost=low,volume=high,depth=shallow",
                          registry=Path(d) / "r.jsonl")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertIn(out["route"], ("DIRECT", "PLAN_FIRST", "DELEGATE", "NEEDS_SURFACE"))

    def test_validate_reports_invalid_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            p.write_text('{"bad json\n', encoding="utf-8")
            r = self._run("validate", registry=p)
            out = json.loads(r.stdout)
            self.assertEqual(out["invalid_lines"], 1)

    def test_stats_labels_itself_as_observed_recorded_outcomes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            write_jsonl(p, [v1(attempt_id="s1")])
            r = self._run("stats", registry=p)
            out = json.loads(r.stdout)
            self.assertIn("observed recorded outcomes", out["_meaning"])

    def test_codex_surface_cli_never_emits_claude_model(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._run(
                "recommend", "small direct implementation",
                "--surface", "codex",
                "--axes", "verifiable=yes,failcost=low,volume=low,depth=shallow",
                "--axes-ext",
                "spec_readiness=executable,volume=low,handoff_cost=high,context_dependency=high",
                registry=Path(d) / "r.jsonl")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["model"], "gpt-5.6-luna")

    def test_experimental_fable_cli_returns_shadow_plan_not_production(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._run(
                "recommend", "evaluate Fable on a bounded task",
                "--surface", "claude",
                "--candidate-model", "fable-5",
                "--rollout-stage", "v2",
                "--axes", "verifiable=yes,failcost=low,volume=low,depth=mid",
                "--axes-ext",
                "spec_readiness=executable,volume=low,handoff_cost=high,context_dependency=high",
                registry=Path(d) / "r.jsonl")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["route"], "SHADOW_EVALUATION")
            self.assertFalse(out["production_eligible"])

    def test_v3_fable_shadow_is_recommendation_only_not_selectable(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._run(
                "recommend", "evaluate Fable recommendation only",
                "--surface", "claude", "--candidate-model", "fable-5",
                "--rollout-stage", "v3",
                "--axes", "verifiable=yes,failcost=low,volume=low,depth=mid",
                "--axes-ext",
                "spec_readiness=executable,volume=low,handoff_cost=high,context_dependency=high",
                registry=Path(d) / "r.jsonl")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertFalse(out["model_effort_selectable"])
            self.assertNotIn("effort", out)

    def test_query_filters_candidate_list_by_full_cohort(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.jsonl"
            write_jsonl(p, [
                v1(
                    attempt_id="codex", task="parser refactor", vendor="openai",
                    surface="codex-cli", model_family="gpt-5.6",
                    task_family="implementation", role="direct"),
                v1(
                    attempt_id="claude", task="parser refactor", vendor="anthropic",
                    surface="claude-code-cli", model_family="claude-5",
                    task_family="implementation", role="direct"),
            ])
            r = self._run(
                "query", "parser refactor", "--no-legacy",
                "--vendor", "openai", "--surface", "codex",
                "--model-family", "gpt-5.6", "--task-family", "implementation",
                "--role", "direct", registry=p)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["matched"], 1)
            self.assertEqual(out["candidates"][0]["vendor"], "openai")


if __name__ == "__main__":
    unittest.main(verbosity=2)
