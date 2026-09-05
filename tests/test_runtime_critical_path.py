"""Named real-surface suite for recorded critical-path health."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _projection_cli_support import create_projection_fixture, run_omh  # noqa: E402


class RuntimeCriticalPathTests(unittest.TestCase):
    def test_recorded_diamond_reconciles_every_metric_exactly(self) -> None:
        with TemporaryDirectory(prefix="omh-runtime-critical-path-") as raw:
            root = Path(raw) / "fixture"
            metadata = create_projection_fixture(root, "happy")
            summary = run_omh(
                root,
                "runtime",
                "health-summary",
                "--run-id",
                str(metadata["fanout_id"]),
                "--json",
            )

            self.assertEqual(summary["schema_version"], "run_health_summary/v2")
            section = summary["critical_path_health"]
            self.assertEqual(section["metrics"], metadata["expected_metrics"])
            self.assertEqual(section["evidence_gaps"], [])
            self.assertEqual(section["privacy"], "metadata_only")
            self.assertEqual(metadata["privacy_scan"]["leak_count"], 0)

        self.assertFalse(root.exists())

    def test_cyclic_recorded_lifecycle_is_an_explicit_gap(self) -> None:
        with TemporaryDirectory(prefix="omh-runtime-critical-path-bad-") as raw:
            root = Path(raw) / "fixture"
            metadata = create_projection_fixture(root, "adversarial")
            summary = run_omh(
                root,
                "runtime",
                "health-summary",
                "--run-id",
                str(metadata["fanout_id"]),
                "--json",
            )

            section = summary["critical_path_health"]
            self.assertIsNone(section["metrics"])
            gaps = {(item["task_id"], item["code"]) for item in section["evidence_gaps"]}
            self.assertIn(("", "cycle"), gaps)
            self.assertIn(("a", "dependency_order"), gaps)


if __name__ == "__main__":
    unittest.main()
