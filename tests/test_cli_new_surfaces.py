"""Operator/agent CLI fan-in contracts for #1296, #1290, and #1295."""

from __future__ import annotations

import json
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package
from _work_artifact_shape_payloads import WorkArtifactShapeSessionPayloads

load_local_package()

from omh.commands.main import build_parser  # noqa: E402
from omh.commands.paired_run import cmd_coding_paired_run_dispatch  # noqa: E402
from omh.coding.paired_run_execution import PairedRunExecutionReport  # noqa: E402
from omh.quality.paired_run_decision import build_paired_run_decision  # noqa: E402
from omh.runtime.critical_path_health_models import (  # noqa: E402
    CRITICAL_PATH_HEALTH_SCHEMA_VERSION,
    CriticalPathEvidenceGap,
    CriticalPathHealthProjection,
)
from omh.runtime.critical_path_health_source_models import CriticalPathHealthSourceResult  # noqa: E402
from omh.quality.paired_run_model import (  # noqa: E402
    ArmRole,
    ArmSpec,
    BehaviorVerdict,
    InfrastructureStatus,
    PairedRunRequest,
    RunResultInput,
    TaskSpec,
)


class RuntimeHealthFanInCliTests(unittest.TestCase):
    def test_fanout_health_uses_v2_with_explicit_source_gaps(self) -> None:
        record = CriticalPathHealthProjection(
            CRITICAL_PATH_HEALTH_SCHEMA_VERSION,
            "fanout", "frozen", "omh", (), None, (), (),
            (CriticalPathEvidenceGap("", "missing_worker_result"),),
        )
        source = CriticalPathHealthSourceResult("fanout-missing", (), record, (("", "missing_worker_result"),))
        with patch(
            "omh.commands.run_health.project_fanout_critical_path_health",
            return_value=source,
            create=True,
        ):
            status, stdout, stderr = run_cli(
                ["runtime", "health-summary", "--run-id", "fanout-missing", "--json"], output_json=False
            )

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "run_health_summary/v2")
        section = payload["critical_path_health"]
        self.assertIsNone(section["metrics"])
        self.assertEqual(section["evidence_gaps"], [{"code": "missing_worker_result", "task_id": ""}])

    def test_legacy_input_remains_supported_and_cannot_mix_with_run_id(self) -> None:
        legacy = {
            "schema_version": "run_health_input/v1",
            "run_id": "legacy-run",
            "owner": "codex",
            "observed_at_ms": 1000,
            "events": [],
            "efficiency_claim": {"direction": "unclaimed", "baseline_ref": "", "evaluator_ref": ""},
        }
        with TemporaryDirectory() as raw:
            path = Path(raw) / "health.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            status, stdout, stderr = run_cli(["runtime", "health-summary", "--input", str(path), "--json"])
            with self.assertRaises(SystemExit) as raised:
                run_cli(["runtime", "health-summary", "--input", str(path), "--run-id", "fanout-1"])

        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(stdout)["schema_version"], "run_health_summary/v1")
        self.assertEqual(raised.exception.code, 2)


class RuntimeArtifactShowShapeCliTests(unittest.TestCase):
    def _status_payload(self) -> dict[str, object]:
        fixture = WorkArtifactShapeSessionPayloads()
        return fixture._status_payload(runtime_handoff=fixture._runtime_handoff_status())

    def test_show_shape_without_session_selects_latest_matching_session_and_defaults_ascii(self) -> None:
        statuses = {
            "ws-earlier": self._status_payload(),
            "ws-latest": self._status_payload(),
        }
        with patch(
            "omh.wrapper.sessions.list_wrapper_sessions",
            return_value=[
                {"session_id": "ws-latest", "updated_at": "2026-09-04T12:00:00+00:00"},
                {"session_id": "ws-earlier", "updated_at": "2026-09-04T11:00:00+00:00"},
            ],
        ), patch(
            "omh.wrapper.sessions.build_wrapper_session_status",
            side_effect=lambda _paths, session_id: statuses[session_id],
        ):
            status, stdout, stderr = run_cli(
                ["runtime", "artifacts", "show-shape", "--artifact-id", "handoff_prompt", "--lens", "flow", "--json"],
                output_json=False,
            )

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["selected_session_id"], "ws-latest")
        self.assertEqual(payload["shape"]["format"], "ascii")
        self.assertNotIn("selected_session", payload)

    def test_show_shape_uses_selected_action_and_gates_mermaid(self) -> None:
        with patch(
            "omh.wrapper.sessions.build_wrapper_session_status",
            return_value=self._status_payload(),
        ):
            status, stdout, stderr = run_cli(
                [
                    "runtime", "artifacts", "show-shape", "--session-id", "wsession-shape",
                    "--artifact-id", "handoff_prompt", "--lens", "flow", "--format", "mermaid", "--json",
                ],
                output_json=False,
            )

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["action"], "show_work_artifact_shape")
        self.assertEqual(payload["selected_session_id"], "wsession-shape")
        self.assertEqual(payload["shape"]["availability"], "unavailable")
        self.assertEqual(payload["shape"]["reason"], "mermaid_capability_not_observed")

    def test_show_shape_fails_when_no_current_session_contains_the_artifact(self) -> None:
        with patch("omh.wrapper.sessions.list_wrapper_sessions", return_value=[]):
            status, _stdout, stderr = run_cli(
                ["runtime", "artifacts", "show-shape", "--artifact-id", "handoff_prompt", "--lens", "flow", "--json"],
                output_json=False,
            )

        self.assertEqual(status, 2)
        self.assertIn("no current wrapper session contains artifact", stderr)

    def test_show_shape_returns_explicit_unavailable_for_unknown_artifact(self) -> None:
        with patch(
            "omh.wrapper.sessions.build_wrapper_session_status",
            return_value=self._status_payload(),
        ):
            status, stdout, stderr = run_cli(
                [
                    "runtime", "artifacts", "show-shape", "--session-id", "wsession-shape",
                    "--artifact-id", "missing", "--lens", "flow", "--format", "ascii", "--json",
                ],
                output_json=False,
            )

        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(stdout)["shape"]["reason"], "unknown_artifact_id")


class FanoutDiagnosticsCliTests(unittest.TestCase):
    def test_optional_diagnostics_hook_is_disabled_unless_the_operator_enables_it(self) -> None:
        base = ["coding", "fanout", "dispatch", "fanout-1", "--goal-file", "goal.txt"]

        self.assertFalse(build_parser().parse_args(base).diagnostics)
        self.assertTrue(build_parser().parse_args([*base, "--diagnostics"]).diagnostics)
        self.assertFalse(build_parser().parse_args([*base, "--no-diagnostics"]).diagnostics)

    def test_health_events_are_explicitly_opt_in_and_can_be_disabled(self) -> None:
        base = ["coding", "fanout", "dispatch", "fanout-1", "--goal-file", "goal.txt"]

        self.assertFalse(build_parser().parse_args(base).health_events)
        self.assertTrue(build_parser().parse_args([*base, "--health-events"]).health_events)
        self.assertFalse(build_parser().parse_args([*base, "--no-health-events"]).health_events)


class PairedRunDispatchCliTests(unittest.TestCase):
    def _decision_path(self, root: Path) -> Path:
        tasks = (TaskSpec("task-a", "criteria-a", "a" * 64),)
        request = PairedRunRequest(
            "decision-cli", None,
            ArmSpec("baseline", "hermes", "model-base", ()),
            ArmSpec("variant", "hermes", "model-variant", ("skill-a",)),
            tasks, 2, 60, "revision-cli", "2026-09-04T00:00:00Z",
            tuple(
                RunResultInput(task.task_id, arm, InfrastructureStatus.NOT_OBSERVED, BehaviorVerdict.NOT_OBSERVED, None)
                for task in tasks
                for arm in ArmRole
            ),
        )
        path = root / "decision.json"
        path.write_text(build_paired_run_decision(request).to_json(), encoding="utf-8")
        return path

    def test_dry_run_returns_an_inert_operator_plan(self) -> None:
        with TemporaryDirectory() as raw:
            decision = self._decision_path(Path(raw))
            status, stdout, stderr = run_cli(
                ["coding", "paired-run", "dispatch", "--decision", str(decision), "--dry-run", "--json"],
                output_json=False,
            )

        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["launch_authorized"])
        self.assertEqual(payload["approval"], "required")
        self.assertEqual(
            payload["budgets"],
            {
                "global_concurrency": 1,
                "executor_concurrency": {"hermes": 1},
                "provider_concurrency": {"local": 1},
                "local_bound": {"cost_units": 2, "seconds": 60},
                "provider_bound": {"cost_units": 2, "seconds": 60},
            },
        )
        self.assertEqual(
            payload["isolation"],
            {
                "shared_resource_mode": "serialize",
                "shared_resource_keys": ["paired-run-local-boundary"],
                "launch_waves": [0, 1],
            },
        )
        self.assertEqual(len(payload["cells"]), 2)

    def test_confirmed_dispatch_calls_only_the_injected_runner_boundary(self) -> None:
        with TemporaryDirectory() as raw:
            decision = self._decision_path(Path(raw))
            calls = []

            def runner(plan):
                calls.append(plan)
                return PairedRunExecutionReport(plan, ())

            stdout = StringIO()
            with redirect_stdout(stdout):
                status = cmd_coding_paired_run_dispatch(
                    Namespace(decision=str(decision), dry_run=False, confirm_dispatch=True),
                    runner_boundary=runner,
                )

        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 1)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["launch_authorized"])
        self.assertEqual(payload["execution"], {"decision_id": "decision-cli", "fan_in_ready": False, "cells": []})

    def test_real_dispatch_requires_explicit_confirmation(self) -> None:
        with TemporaryDirectory() as raw:
            decision = self._decision_path(Path(raw))
            status, _stdout, stderr = run_cli(
                ["coding", "paired-run", "dispatch", "--decision", str(decision)], output_json=False
            )

        self.assertEqual(status, 2)
        self.assertIn("--confirm-dispatch", stderr)

    def test_confirmed_cli_dispatch_without_runner_boundary_fails_honestly(self) -> None:
        with TemporaryDirectory() as raw:
            decision = self._decision_path(Path(raw))
            status, _stdout, stderr = run_cli(
                ["coding", "paired-run", "dispatch", "--decision", str(decision), "--confirm-dispatch"],
                output_json=False,
            )

        self.assertEqual(status, 2)
        self.assertIn("injected local runner boundary", stderr)


if __name__ == "__main__":
    unittest.main()
