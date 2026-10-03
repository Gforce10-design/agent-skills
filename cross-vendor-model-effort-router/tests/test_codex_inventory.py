import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import codex_inventory as inventory
import router


def write_cache(home, models, fetched_at=None, version="0.159.2", identity="account-a"):
    home.mkdir(parents=True, exist_ok=True)
    (home / "models_cache.json").write_text(json.dumps({
        "fetched_at": (fetched_at or datetime.now(timezone.utc)).isoformat(),
        "client_version": version,
        "identity": {"private": identity},
        "models": [{"slug": model, "visibility": "list",
                    "supported_reasoning_levels": [{"effort": effort} for effort in efforts]}
                   for model, efforts in models.items()],
    }), encoding="utf-8")


FULL = {"gpt-6-luna": ["low", "medium", "high"],
        "gpt-6.1-sol": ["low", "medium", "high"],
        "gpt-6-sol": ["low", "medium", "high"],
        "gpt-6-astra": ["low", "medium", "high"]}
AXES = {"verifiable": "yes", "failcost": "mid", "volume": "low", "depth": "mid"}


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "account-a"
        self.binary = Path(self.tmp.name) / "releases/0.159.2-arm64/bin/codex"
        self.caps = router.load_capabilities()

    def apply(self, **kwargs):
        return inventory.apply_inventory(self.caps, home=self.home,
                                         executable=self.binary, refresh=False, **kwargs)

    def test_ancestor_home_beats_conflicting_env_and_explicit_home_overrides(self):
        native = Path(self.tmp.name) / ".codex"
        listing = (f"n{self.binary}\n"
                   f"n{native}/state_5.sqlite-shm\n")
        with patch.dict(os.environ, {"CODEX_HOME": str(self.home)}), \
             patch.object(inventory, "_run", side_effect=["1 codex", listing]):
            home, binary, scope = inventory.active_codex_runtime()
        self.assertEqual((home, binary, scope),
                         (native.resolve(), self.binary.resolve(), "ancestor_codex_open_files"))
        with patch.dict(os.environ, {"CODEX_HOME": str(self.home)}), \
             patch.object(inventory, "_run", side_effect=["1 codex", listing]):
            home, binary, scope = inventory.active_codex_runtime(explicit=self.home)
        self.assertEqual((home, binary, scope),
                         (self.home.resolve(), self.binary.resolve(), "explicit"))
        with patch.dict(os.environ, {"CODEX_HOME": ""}), \
             patch.object(inventory, "_run", side_effect=["1 codex", listing]):
            home, binary, scope = inventory.active_codex_runtime()
        self.assertEqual((home, binary, scope),
                         (native.resolve(), self.binary.resolve(), "ancestor_codex_open_files"))

    def test_foreign_session_files_do_not_change_runtime_home(self):
        active = Path(self.tmp.name) / "codex-accounts/active/home"
        foreign = Path(self.tmp.name) / "codex-accounts/foreign/home"
        listing = (f"n{self.binary}\n"
                   f"n{active}/state_5.sqlite-wal\n"
                   f"n{foreign}/sessions/2026/10/03/history.jsonl\n")
        with patch.dict(os.environ, {"CODEX_HOME": ""}), \
             patch.object(inventory, "_run", side_effect=["1 codex", listing]):
            result = inventory.active_codex_runtime()
        self.assertEqual(result, (active.resolve(), self.binary.resolve(),
                                  "ancestor_codex_open_files"))

    def test_multiple_runtime_homes_fail_closed_and_explicit_home_overrides(self):
        first = Path(self.tmp.name) / "codex-accounts/first/home"
        second = Path(self.tmp.name) / "codex-accounts/second/home"
        listing = (f"n{self.binary}\n"
                   f"n{first}/state_5.sqlite\n"
                   f"n{second}/state_5.sqlite-shm\n")
        with patch.dict(os.environ, {"CODEX_HOME": ""}), \
             patch.object(inventory, "_run", side_effect=["1 codex", listing]):
            self.assertEqual(inventory.active_codex_runtime(),
                             (None, None, "unresolved"))
        with patch.dict(os.environ, {"CODEX_HOME": ""}), \
             patch.object(inventory, "_run", side_effect=["1 codex", listing]):
            result = inventory.active_codex_runtime(explicit=second,
                                                   executable=self.binary)
        self.assertEqual(result, (second.resolve(), self.binary.resolve(), "explicit"))

    def test_all_runtime_db_suffixes_and_incidental_lookalikes(self):
        active = Path(self.tmp.name) / "codex-accounts/active/home"
        foreign = Path(self.tmp.name) / "codex-accounts/foreign/home"
        for suffix in ("", "-wal", "-shm"):
            with self.subTest(suffix=suffix):
                listing = (f"n{self.binary}\n"
                           f"n{active}/state_5.sqlite{suffix}\n"
                           f"n{foreign}/state_5.sqlite.backup\n"
                           f"n{foreign}/sessions/state_5.sqlite\n")
                with patch.dict(os.environ, {"CODEX_HOME": ""}), \
                     patch.object(inventory, "_run", side_effect=["1 codex", listing]):
                    result = inventory.active_codex_runtime()
                self.assertEqual(result, (active.resolve(), self.binary.resolve(),
                                          "ancestor_codex_open_files"))

    def test_native_and_account_runtime_homes_are_genuinely_ambiguous(self):
        active = Path(self.tmp.name) / "codex-accounts/active/home"
        native = Path(self.tmp.name) / ".codex"
        listing = (f"n{self.binary}\n"
                   f"n{active}/state_5.sqlite\n"
                   f"n{native}/state_5.sqlite-shm\n")
        with patch.dict(os.environ, {"CODEX_HOME": ""}), \
             patch.object(inventory, "_run", side_effect=["1 codex", listing]):
            self.assertEqual(inventory.active_codex_runtime(),
                             (None, None, "unresolved"))

    def test_account_session_only_cannot_establish_runtime_home(self):
        foreign = Path(self.tmp.name) / "codex-accounts/foreign/home"
        listing = (f"n{self.binary}\n"
                   f"n{foreign}/sessions/2026/10/03/history.jsonl\n")
        with patch.dict(os.environ, {"CODEX_HOME": ""}), \
             patch.object(inventory, "_run", side_effect=["1 codex", listing]):
            self.assertEqual(inventory.active_codex_runtime(),
                             (None, None, "unresolved"))

    def test_new_sol_without_new_luna_and_explicit_unavailable(self):
        write_cache(self.home, FULL)
        receipt = self.apply()
        self.assertEqual(receipt["recommendation_models"],
                         ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"])
        self.assertNotIn("gpt-6.1-luna", receipt["recommendation_models"])
        selected = router.select_direct_model("codex", AXES, self.caps)
        self.assertEqual((selected["model"], selected["effort"]),
                         ("gpt-6.1-sol", "medium"))
        blocked = router.select_direct_model("codex", AXES, self.caps,
                         model_availability={"gpt-6.1-sol": "unavailable"})
        self.assertEqual(blocked["route"], "BLOCKED_MODEL_AVAILABILITY")

    def test_numeric_version_order_and_cohort(self):
        write_cache(self.home, dict(FULL, **{
            "gpt-6.9-sol": ["low", "medium", "high"],
            "gpt-6.10-sol": ["low", "medium", "high"]}))
        self.apply()
        self.assertEqual(self.caps["direct_execution"]["codex-cli"]["recommendation_models"][1],
                         "gpt-6.10-sol")
        self.assertEqual(router.model_family("gpt-6.10-sol"), "gpt-6.10")
        record = router.build_record(task="test", axes=AXES, axes_ext={},
            worker="codex", outcome="success",
            attempt_id="inventory-test", model_requested="gpt-6.10-sol")
        self.assertEqual(record["model_family"], "gpt-6.10")

    def test_account_isolation_and_refresh_failure_keeps_recent_verified_cache(self):
        write_cache(self.home, FULL)
        self.assertEqual(self.apply()["status"], "RECENT_ACCOUNT_CACHE")
        other = Path(self.tmp.name) / "account-b"
        other_models = {k: v for k, v in FULL.items() if k != "gpt-6.1-sol"}
        write_cache(other, other_models)
        other_caps = router.load_capabilities()
        receipt = inventory.apply_inventory(other_caps, home=other,
                                            executable=self.binary, refresh=False)
        self.assertEqual(receipt["recommendation_models"][1], "gpt-6-sol")
        self.assertEqual(self.caps["direct_execution"]["codex-cli"]["recommendation_models"][1],
                         "gpt-6.1-sol")
        old_identity = self.apply()["identity_hash"]
        write_cache(self.home, other_models, identity="account-b")
        self.assertNotEqual(old_identity, self.apply()["identity_hash"])
        self.assertEqual(self.caps["direct_execution"]["codex-cli"]["recommendation_models"][1],
                         "gpt-6-sol")
        with patch.object(inventory, "probe_model_list", side_effect=TimeoutError):
            receipt = inventory.apply_inventory(other_caps, home=other, executable=self.binary)
        self.assertEqual(receipt["status"], "RECENT_ACCOUNT_CACHE")
        self.assertNotIn("private", json.dumps(receipt))

    def test_stale_cache_and_unsupported_effort_falls_back_to_compatible_version(self):
        old = datetime.now(timezone.utc) - timedelta(days=3)
        write_cache(self.home, FULL, fetched_at=old)
        before = copy.deepcopy(self.caps["direct_execution"]["codex-cli"])
        with patch.object(inventory, "probe_model_list", side_effect=TimeoutError):
            receipt = inventory.apply_inventory(self.caps, home=self.home, executable=self.binary)
        self.assertEqual(receipt["status"], "STALE_UNUSABLE")
        self.assertEqual(self.caps["direct_execution"]["codex-cli"], before)
        limited = dict(FULL, **{"gpt-6.1-sol": ["low"]})
        write_cache(self.home, limited)
        receipt = self.apply()
        self.assertEqual(receipt["status"], "RECENT_ACCOUNT_CACHE")
        self.assertEqual(receipt["recommendation_models"][1], "gpt-6-sol")

    def test_missing_tier_is_explicitly_unavailable(self):
        write_cache(self.home, {"gpt-6-luna": FULL["gpt-6-luna"],
                                "gpt-6.1-sol": FULL["gpt-6.1-sol"]})
        receipt = self.apply()
        self.assertEqual(receipt["status"], "RECENT_ACCOUNT_CACHE_PARTIAL")
        blocked = router.select_direct_model("codex", dict(AXES, failcost="high"), self.caps)
        self.assertEqual(blocked["route"], "BLOCKED_MODEL_AVAILABILITY")

    def test_cache_fallback_requires_matching_runtime_version(self):
        write_cache(self.home, FULL)
        with patch.object(inventory, "probe_model_list", side_effect=TimeoutError):
            with patch.object(inventory, "active_codex_runtime",
                              return_value=(self.home, None, "explicit")):
                missing_binary = inventory.apply_inventory(self.caps, home=self.home)
            different_binary = inventory.apply_inventory(self.caps, home=self.home,
                executable=Path(self.tmp.name) / "releases/0.154.0-arm64/bin/codex")
        self.assertEqual(missing_binary["status"], "RUNTIME_VERSION_MISMATCH")
        self.assertEqual(different_binary["status"], "RUNTIME_VERSION_MISMATCH")

    def test_malformed_live_response_falls_back_and_malformed_cache_is_typed_failure(self):
        write_cache(self.home, FULL)
        with patch.object(inventory, "probe_model_list", side_effect=AttributeError("bad row")):
            receipt = inventory.apply_inventory(self.caps, home=self.home,
                                                executable=self.binary)
        self.assertEqual(receipt["status"], "RECENT_ACCOUNT_CACHE")
        (self.home / "models_cache.json").write_text('{"fetched_at": 42, "models": {}}')
        with patch.object(inventory, "probe_model_list", side_effect=TypeError("bad data")):
            receipt = inventory.apply_inventory(self.caps, home=self.home,
                                                executable=self.binary)
        self.assertEqual(receipt["status"], "REFRESH_FAILED")

    def test_native_auth_metadata_newer_than_cache_rejects_fallback(self):
        native = Path(self.tmp.name) / ".codex"
        write_cache(native, FULL, fetched_at=datetime.now(timezone.utc) - timedelta(hours=1))
        (native / "auth.json").write_text("fixture")
        receipt = inventory.apply_inventory(self.caps, home=native,
                                            executable=self.binary, refresh=False)
        self.assertEqual(receipt["status"], "ACCOUNT_CHANGED_SINCE_CACHE")

    def test_native_cache_without_auth_metadata_is_unverified(self):
        native = Path(self.tmp.name) / ".codex"
        write_cache(native, FULL)
        receipt = inventory.apply_inventory(self.caps, home=native,
                                            executable=self.binary, refresh=False)
        self.assertEqual(receipt["status"], "ACCOUNT_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
