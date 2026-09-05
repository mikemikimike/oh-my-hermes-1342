"""Named integration suite for the isolated paired evaluation runner."""

from __future__ import annotations

import unittest

from _local_package import load_local_package
from _platform_support import requires_posix

load_local_package()

from tools.qa.orchestration_smoke_paired import adversarial_paired, happy_paired  # noqa: E402


@requires_posix
class EvaluationMatrixRunnerTests(unittest.TestCase):
    def _assert_cleanup(self, cleanup: dict[str, object]) -> None:
        self.assertEqual(
            cleanup,
            {
                "live_workspaces": 0,
                "unreaped_child_groups": 0,
                "port_cleanup": "not_applicable_no_ports_created",
                "live_temp_paths": 0,
            },
        )

    def test_serial_and_parallel_runs_preserve_scope_receipts_and_bounds(self) -> None:
        payload = happy_paired()

        self.assertEqual(payload["cell_count"], 8)
        self.assertEqual(payload["receipt_count"], 8)
        self.assertEqual(len(set(payload["receipt_refs"])), 8)
        self.assertEqual(payload["serial_peaks"]["global"], 1)
        self.assertEqual(payload["parallel_peaks"]["global"], 2)
        self.assertEqual(payload["parallel_peaks"]["provider"], 2)
        self.assertEqual(payload["parallel_peaks"]["local-baseline"], 1)
        self.assertEqual(payload["parallel_peaks"]["local-variant"], 1)
        self.assertTrue(payload["serial_parallel_scope_equivalent"])
        self.assertEqual(payload["decision"], "baseline_dominates")
        self._assert_cleanup(payload["cleanup"])
        for privacy in payload["filesystem_privacy"].values():
            self.assertTrue(privacy["persisted_prompt_absent"])
            self.assertTrue(privacy["persisted_secret_absent"])
            self.assertTrue(privacy["diagnostic_payload_absent"])

    def test_every_invalid_terminal_or_identity_class_blocks_fan_in(self) -> None:
        payload = adversarial_paired()
        required = {
            "missing",
            "stale",
            "mismatched",
            "unauthenticated",
            "partial",
            "timeout",
            "cancel",
            "crash",
            "rate_limit",
            "cleanup_failure",
        }

        self.assertTrue(required <= set(payload))
        self.assertTrue(all(str(payload[key]).startswith("BLOCK:") for key in required))
        self.assertEqual(payload["shared_resource_serialization"], "HOLD:serialized")
        self._assert_cleanup(payload["cleanup"])


if __name__ == "__main__":
    unittest.main()
