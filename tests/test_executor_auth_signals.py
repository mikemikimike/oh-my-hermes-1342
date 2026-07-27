from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.executor_auth_signals import (  # noqa: E402
    EXECUTOR_AUTH_SIGNALS_SCHEMA_VERSION,
    auth_signal_for_profile,
    executor_auth_signals,
    last_limit_signal_for_profile,
)
from omh.coding.executor_readiness import executor_choice_context, probe_executor_readiness  # noqa: E402
from omh.system.local_store import atomic_write_json  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402


class AuthSignalMarkerTests(unittest.TestCase):
    def test_absent_markers_when_nothing_is_installed(self) -> None:
        with TemporaryDirectory() as tmp:
            signals = executor_auth_signals(home=Path(tmp))
            self.assertEqual(signals["schema_version"], EXECUTOR_AUTH_SIGNALS_SCHEMA_VERSION)
            self.assertEqual(signals["profiles"]["codex"]["login_marker"], "absent")
            self.assertEqual(signals["profiles"]["claude-code"]["login_marker"], "absent")
            self.assertIn("not subscription tier", signals["claim_boundary"])

    def test_present_markers_read_shape_only(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude.json").write_text(json.dumps({"oauthAccount": {"x": 1}}), encoding="utf-8")
            (home / ".codex").mkdir()
            (home / ".codex" / "auth.json").write_text("{\"tokens\": \"sk-SECRET-VALUE-12345\"}", encoding="utf-8")
            signals = executor_auth_signals(home=home)
            self.assertEqual(signals["profiles"]["claude-code"]["login_marker"], "present")
            self.assertEqual(signals["profiles"]["codex"]["login_marker"], "present")
            # No credential value may appear anywhere in the payload.
            self.assertNotIn("sk-SECRET-VALUE-12345", json.dumps(signals))

    def test_unreadable_claude_config_is_unknown(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude.json").write_text("not json at all {", encoding="utf-8")
            signals = executor_auth_signals(home=home)
            self.assertEqual(signals["profiles"]["claude-code"]["login_marker"], "unknown")

    def test_claude_config_without_login_key_is_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude.json").write_text(json.dumps({"projects": {}}), encoding="utf-8")
            signals = executor_auth_signals(home=home)
            self.assertEqual(signals["profiles"]["claude-code"]["login_marker"], "absent")

    def test_non_cli_profile_is_not_applicable(self) -> None:
        entry = auth_signal_for_profile("hermes")
        self.assertEqual(entry["login_marker"], "not_applicable")


class LimitSignalReadTests(unittest.TestCase):
    def test_missing_state_reads_as_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            self.assertEqual(last_limit_signal_for_profile(paths, "codex"), {})

    def test_recorded_signal_round_trips(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            atomic_write_json(
                paths.executor_limit_signals_path,
                {
                    "schema_version": "executor_limit_signals/v1",
                    "profiles": {"codex": {"last_limit_shaped_at": "2026-07-27T00:00:00Z", "pattern_label": "rate_limit"}},
                },
                private=True,
            )
            entry = last_limit_signal_for_profile(paths, "codex")
            self.assertEqual(entry["pattern_label"], "rate_limit")


class ReadinessAdvisoryFreshnessTests(unittest.TestCase):
    def test_advisories_refresh_while_probe_stays_cached(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            # Seed a cached observed_once probe result so no subprocess runs.
            atomic_write_json(
                paths.executor_readiness_path,
                {
                    "schema_version": "executor_readiness_cache/v1",
                    "profiles": {
                        "codex": {
                            "schema_version": "executor_readiness/v1",
                            "profile": "codex",
                            "status": "ready",
                            "observed_once": True,
                        }
                    },
                },
                private=True,
            )
            first = probe_executor_readiness(paths, "codex")
            self.assertEqual(first["cache_status"], "cached")
            self.assertIn("auth_signal", first)
            self.assertEqual(first["last_limit_signal"], {})
            # A limit signal lands later; the cached probe must surface it
            # without --force.
            atomic_write_json(
                paths.executor_limit_signals_path,
                {
                    "schema_version": "executor_limit_signals/v1",
                    "profiles": {"codex": {"pattern_label": "quota"}},
                },
                private=True,
            )
            second = probe_executor_readiness(paths, "codex")
            self.assertEqual(second["cache_status"], "cached")
            self.assertEqual(second["last_limit_signal"]["pattern_label"], "quota")

    def test_advisories_are_not_persisted_into_the_cache(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            probe_executor_readiness(paths, "omx-runtime", force=True)
            stored = json.loads(paths.executor_readiness_path.read_text(encoding="utf-8"))
            profile_entry = stored["profiles"]["omx-runtime"]
            self.assertNotIn("auth_signal", profile_entry)
            self.assertNotIn("last_limit_signal", profile_entry)


class ExecutorChoiceContextTests(unittest.TestCase):
    def test_choice_context_lists_both_cli_candidates_without_probing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            context = executor_choice_context(paths)
            profiles = [entry["profile"] for entry in context["candidates"]]
            self.assertEqual(profiles, ["codex", "claude-code"])
            for entry in context["candidates"]:
                self.assertEqual(entry["readiness_status"], "not_observed")
                self.assertIn("auth_signal", entry)
                self.assertIn("last_limit_signal", entry)
            self.assertIn("never removes a candidate", context["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
