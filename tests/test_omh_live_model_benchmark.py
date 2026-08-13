from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.unit_prompt_protocol import HIGH_EFFORT_CALIBRATIONS  # noqa: E402


BASE = Path(__file__).resolve().parents[1] / "benchmarks" / "live-model-tools" / "v1"


def _load_omh_live():
    path = BASE / "lib" / "omh_live.py"
    spec = importlib.util.spec_from_file_location("omh_live", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OmhLiveAdapterTests(unittest.TestCase):
    def test_route_argv_uses_omh_model_route_surface(self) -> None:
        module = _load_omh_live()
        argv = module.route_argv("omh", model="qwen3-coder-next", effort="high")
        self.assertEqual(
            argv,
            [
                "omh",
                "coding",
                "model-route",
                "--executor",
                "hermes",
                "--model",
                "qwen3-coder-next",
                "--effort",
                "high",
                "--role",
                "implementation",
                "--json",
            ],
        )

    def test_run_trial_requires_effect_boundary_confirmation_and_bounded_input(self) -> None:
        module = _load_omh_live()
        with self.assertRaisesRegex(ValueError, "explicit paid-live confirmation"):
            module.run_trial(
                omh_executable="omh",
                hermes_executable="hermes",
                workspace=Path("/tmp/workspace"),
                omh_home=Path("/tmp/omh-home"),
                task="task",
                model="glm-5",
                provider="zai",
                effort="high",
                condition="baseline",
                parent_run_id="parent",
                run_id="child",
                timeout=30,
                confirmed=False,
            )
        with self.assertRaisesRegex(ValueError, "prompt exceeds"):
            module.run_trial(
                omh_executable="omh",
                hermes_executable="hermes",
                workspace=Path("/tmp/workspace"),
                omh_home=Path("/tmp/omh-home"),
                task="x" * 131_073,
                model="glm-5",
                provider="zai",
                effort="high",
                condition="baseline",
                parent_run_id="parent",
                run_id="child",
                timeout=30,
                confirmed=True,
            )

    def test_dispatch_argv_uses_explicit_omh_hermes_child_surface(self) -> None:
        module = _load_omh_live()
        argv = module.dispatch_argv(
            "omh",
            hermes_executable="/tmp/fake-hermes",
            workspace=Path("/tmp/workspace"),
            route={
                "selected_model": "glm-5",
                "selected_reasoning_effort": "high",
                "model_family": "glm",
            },
            provider="zai",
            parent_run_id="parent",
            run_id="child",
            timeout=30,
        )
        self.assertIn("hermes-child", argv)
        self.assertIn("dispatch", argv)
        self.assertIn("--confirm-dispatch", argv)
        self.assertNotIn("omo", argv)

    def test_prompt_pair_changes_only_omh_calibration(self) -> None:
        module = _load_omh_live()
        task = "Read TARGET.txt and return its exact contents."
        route = {
            "selected_model": "deepseek-v4-pro",
            "selected_reasoning_effort": "high",
            "model_family": "deepseek",
        }
        baseline, optimized = module.prompt_pair(task, route)
        self.assertIn(task, baseline)
        self.assertIn(task, optimized)
        self.assertNotIn(HIGH_EFFORT_CALIBRATIONS["deepseek"], baseline)
        self.assertIn(HIGH_EFFORT_CALIBRATIONS["deepseek"], optimized)
        self.assertEqual(module.task_digest(baseline), module.task_digest(optimized))

    def test_observation_metrics_never_estimate_missing_usage(self) -> None:
        module = _load_omh_live()
        observation = {
            "schema_version": "routing_observation/v1",
            "claim": "observed",
            "status": "completed",
            "category": None,
            "lane": None,
            "role": None,
            "selected_owner": None,
            "selected_provider": None,
            "selected_model": None,
            "selected_reasoning": None,
            "fallback_chain": [],
            "fallback_index": None,
            "reason": "runtime_completed",
            "provenance": "runtime",
            "routing_provenance": None,
            "turn": None,
            "tools": 3,
            "tokens": None,
            "cost_usd": None,
            "rate_tokens_per_second": None,
            "current_action": None,
            "parent_session_id": None,
            "child_session_id": None,
            "run_id": None,
            "dispatch_id": None,
        }
        metrics = module.observation_metrics(observation)
        self.assertEqual(metrics["tools"], 3)
        self.assertIsNone(metrics["tokens"])
        self.assertIsNone(metrics["cost_usd"])

    def test_manifest_declares_omh_harness_without_omo(self) -> None:
        manifest = json.loads((BASE / "manifest.json").read_text())
        self.assertEqual(manifest["live_harness"]["kind"], "omh_hermes_child")
        serialized = json.dumps(manifest).lower()
        self.assertNotIn('"omo"', serialized)

    def test_baseline_and_optimized_run_through_real_omh_observation_surface(self) -> None:
        module = _load_omh_live()
        with TemporaryDirectory() as root_text:
            root = Path(root_text)
            omh = root / "omh.py"
            hermes = root / "hermes.py"
            capture = root / "capture"
            capture.mkdir()
            omh.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'src')!r})\n"
                "from omh.cli import main\n"
                "raise SystemExit(main())\n",
                encoding="utf-8",
            )
            hermes.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "args=sys.argv[1:]\n"
                "prompt=sys.stdin.read()\n"
                "capture=Path(sys.argv[0]).resolve().parent/'capture'\n"
                "index=len(list(capture.glob('prompt-*.txt')))\n"
                "(capture/f'prompt-{index}.txt').write_text(prompt,encoding='utf-8')\n"
                "usage=Path(args[args.index('--usage-file')+1])\n"
                "usage.write_text(json.dumps({'provider':'fake','model':args[args.index('--model')+1],"
                "'tool_calls':2,'total_tokens':37,'estimated_cost_usd':0.125}),encoding='utf-8')\n",
                encoding="utf-8",
            )
            executable = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            omh.chmod(omh.stat().st_mode | executable)
            hermes.chmod(hermes.stat().st_mode | executable)
            trials = []
            for condition in ("baseline", "optimized"):
                workspace = root / condition
                workspace.mkdir()
                trials.append(
                    module.run_trial(
                        omh_executable=str(omh),
                        hermes_executable=str(hermes),
                        workspace=workspace,
                        omh_home=root / f"omh-{condition}",
                        task="Read TARGET.txt and return its exact contents.",
                        model="qwen3-coder-next",
                        provider="qwen",
                        effort="high",
                        condition=condition,
                        parent_run_id=f"parent-{condition}",
                            run_id=f"child-{condition}",
                            timeout=30,
                            confirmed=True,
                        )
                )
            self.assertEqual(trials[0]["task_digest"], trials[1]["task_digest"])
            self.assertEqual(trials[1]["route"]["model_family"], "qwen")
            self.assertEqual(trials[1]["observation"]["tools"], 2)
            self.assertEqual(trials[1]["observation"]["tokens"], 37)
            self.assertEqual(trials[1]["observation"]["cost_usd"], 0.125)
            baseline = (capture / "prompt-0.txt").read_text(encoding="utf-8")
            optimized = (capture / "prompt-1.txt").read_text(encoding="utf-8")
            self.assertNotIn(HIGH_EFFORT_CALIBRATIONS["qwen"], baseline)
            self.assertIn(HIGH_EFFORT_CALIBRATIONS["qwen"], optimized)


if __name__ == "__main__":
    unittest.main()
