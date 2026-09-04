"""Named integration suite for bounded revision-bound diagnostics."""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from tools.qa.orchestration_smoke_quality import (  # noqa: E402
    adversarial_diagnostic,
    happy_diagnostic,
)


class DiagnosticRunnerTests(unittest.TestCase):
    def test_fixed_green_revision_runs_once_per_provider_revision_identity(self) -> None:
        payload = happy_diagnostic()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["provider_status"], "ok")
        self.assertEqual(payload["runner_calls"], [
            "orchestration-baseline",
            "orchestration-end",
        ])
        self.assertTrue(payload["cache_exact_once"])
        self.assertTrue(payload["identical_result"])
        self.assertTrue(payload["metadata_only"])
        self.assertEqual(payload["evidence_verdict"], "no_new_diagnostics_observed")

    def test_every_unattributable_or_failed_provider_state_holds(self) -> None:
        payload = adversarial_diagnostic()
        required = {
            "moving_end_revision",
            "unsupported_suffix",
            "timeout",
            "cancel",
            "crash",
            "partial_provider",
            "forbidden_message",
            "forbidden_source",
        }

        self.assertTrue(required <= set(payload))
        for key in required:
            value = str(payload[key])
            self.assertTrue(value.startswith("HOLD:"), (key, value))
            self.assertNotIn("no_new_diagnostics_observed", value)
        self.assertEqual(payload["stateful_serialization"], "HOLD:serialized:max_active=1")
        self.assertTrue(payload["fixture_privacy_scan"]["persisted_secret_absent"])
        self.assertEqual(payload["fixture_privacy_scan"]["output_store_file_count"], 0)


if __name__ == "__main__":
    unittest.main()
