"""Failure containment for the paired-run local worktree adapter."""

from __future__ import annotations

from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.coding.paired_run_dispatch import (  # noqa: E402
    ApprovalState,
    ArmDispatchTarget,
    CostTimeBound,
    DispatchBudgets,
    NamedConcurrencyBudget,
    PairedRunDispatchConfig,
    SharedResourceMode,
    plan_paired_run_dispatch,
)
from omh.coding.paired_run_local_models import PairedRunLocalRunnerConfig  # noqa: E402
from omh.coding.paired_run_local_worktrees import execute_local_paired_plan  # noqa: E402
from omh.quality.paired_run_decision import build_paired_run_decision  # noqa: E402
from omh.quality.paired_run_model import (  # noqa: E402
    ArmRole,
    ArmSpec,
    BehaviorVerdict,
    InfrastructureStatus,
    PairedRunRequest,
    RunResultInput,
    TaskSpec,
)
from omh.system.paths import OmhPaths  # noqa: E402


def _decision(revision: str):
    task = TaskSpec("task-a", "criteria-a", "a" * 64)
    return build_paired_run_decision(
        PairedRunRequest(
            "decision-timeout",
            None,
            ArmSpec("baseline", "hermes", "model-a", ()),
            ArmSpec("variant", "hermes", "model-b", ()),
            (task,),
            2,
            30,
            revision,
            "2026-09-04T00:00:00Z",
            tuple(
                RunResultInput(
                    task.task_id,
                    arm,
                    InfrastructureStatus.NOT_OBSERVED,
                    BehaviorVerdict.NOT_OBSERVED,
                    None,
                )
                for arm in ArmRole
            ),
        )
    )


def _plan(decision):
    one = CostTimeBound(1, 1)
    targets = tuple(
        ArmDispatchTarget(arm, "hermes", "local", model, one, one)
        for arm, model in (
            (ArmRole.BASELINE, "model-a"),
            (ArmRole.VARIANT, "model-b"),
        )
    )
    return plan_paired_run_dispatch(
        decision.to_json(),
        PairedRunDispatchConfig(
            ApprovalState.APPROVED,
            False,
            SharedResourceMode.SERIALIZE,
            DispatchBudgets(
                1,
                (NamedConcurrencyBudget("hermes", 1),),
                (NamedConcurrencyBudget("local", 1),),
                CostTimeBound(2, 2),
                CostTimeBound(2, 2),
            ),
            targets,
        ),
    )


class PairedRunLocalFailureTests(unittest.TestCase):
    def test_git_timeout_becomes_crashed_with_verified_partial_cleanup(self) -> None:
        with TemporaryDirectory(prefix="omh-paired-timeout-") as raw:
            root = Path(raw)
            repo = root / "repo"
            repo.mkdir()
            revision = "a" * 40
            decision = _decision(revision)
            plan = _plan(decision)
            paths = OmhPaths(root / ".omh", root / ".hermes")

            def time_out(_repo: Path, path: Path, _revision: str) -> int:
                path.mkdir()
                raise subprocess.TimeoutExpired(["git", "worktree", "add"], 1)

            def remove(_repo: Path, path: Path) -> int:
                path.rmdir()
                return 0

            with (
                patch(
                    "omh.coding.paired_run_local_worktrees._add_worktree",
                    side_effect=time_out,
                ),
                patch(
                    "omh.coding.paired_run_local_worktrees._remove_worktree",
                    side_effect=remove,
                ),
            ):
                report = execute_local_paired_plan(
                    plan,
                    decision,
                    {"task-a": "content"},
                    PairedRunLocalRunnerConfig(paths, repo, "provider"),
                )

            self.assertEqual(
                {item.state.value for item in report.receipts},
                {"crashed"},
            )
            self.assertTrue(
                all(item.cleanup_succeeded for item in report.receipts)
            )
            self.assertFalse(any(root.glob("repo-paired-run-*")))


if __name__ == "__main__":
    unittest.main()
