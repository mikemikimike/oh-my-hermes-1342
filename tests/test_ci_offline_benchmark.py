"""CI integration contract for the offline live-model framework benchmark."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest

from _local_package import load_local_package

load_local_package()

from tools.test_sharding.plan import (  # noqa: E402
    PlanningInputs,
    build_plan,
    load_quarantine,
    load_timings,
)
from tools.test_sharding.static_inventory import discover_inventory  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "benchmarks/live-model-tools/v1/tests/test_framework.py"
WRAPPER_PREFIX = "test_live_model_benchmark_framework."


class CiOfflineBenchmarkTests(unittest.TestCase):
    def test_upstream_framework_runs_all_fifteen_tests_without_live_authority(self) -> None:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"OMH_BENCH_ALLOW_LIVE", "OMH_BENCH_MAX_CALLS"}
        }
        completed = subprocess.run(
            [sys.executable, str(UPSTREAM)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )

        combined = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 0, combined)
        self.assertIn("Ran 15 tests", combined)
        self.assertIn("OK", combined)

    def test_static_ci_plan_assigns_every_wrapper_test_exactly_once(self) -> None:
        inventory = discover_inventory(ROOT / "tests")
        plan = build_plan(
            PlanningInputs(
                inventory,
                load_timings(ROOT / "tools/test_sharding/timings.json"),
                load_quarantine(ROOT / "tools/test_sharding/quarantine.json"),
            ),
            2,
        )
        assigned = [
            test_id
            for shard in plan.shards
            for test_id in shard
            if test_id.startswith(WRAPPER_PREFIX)
        ]
        assigned.extend(
            test_id
            for test_id in plan.quarantine
            if test_id.startswith(WRAPPER_PREFIX)
        )

        self.assertEqual(len(assigned), 16)
        self.assertEqual(len(assigned), len(set(assigned)))
        self.assertTrue(
            all("benchmarks/live-model-tools" not in test_id for test_id in inventory)
        )

    def test_every_main_suite_lane_consumes_the_shared_exact_once_plan(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn('python-version: ["3.11", "3.12"]', workflow)
        self.assertIn("lane: windows-3.12", workflow)
        self.assertIn("python tools/test_sharding/plan.py --shards 2", workflow)
        self.assertEqual(
            workflow.count("python tools/test_sharding/run.py --plan shard-plan/plan.json"),
            3,
        )
        self.assertIn("needs: [test, test-windows, test-quarantine]", workflow)


if __name__ == "__main__":
    unittest.main()
