from __future__ import annotations

from dataclasses import replace
import unittest

from omh.coding.paired_run_dispatch import (
    ApprovalState,
    ArmDispatchTarget,
    CostTimeBound,
    DispatchBudgets,
    NamedConcurrencyBudget,
    PairedRunDispatchConfig,
    PairedRunDispatchPlanError,
    SharedResourceMode,
    TerminalState,
    plan_paired_run_dispatch,
    record_terminal_state,
)
from omh.quality.paired_run_decision import build_paired_run_decision
from omh.quality.paired_run_model import (
    ArmRole,
    ArmSpec,
    BehaviorVerdict,
    InfrastructureStatus,
    PairedRunRequest,
    RunResultInput,
    TaskSpec,
)


def _decision_document(*, max_total_runs: int = 4) -> str:
    tasks = (
        TaskSpec("task-a", "criteria-a", "a" * 64),
        TaskSpec("task-b", "criteria-b", "b" * 64),
    )
    results = tuple(
        RunResultInput(
            task.task_id,
            arm,
            InfrastructureStatus.NOT_OBSERVED,
            BehaviorVerdict.NOT_OBSERVED,
            None,
        )
        for task in tasks
        for arm in (ArmRole.BASELINE, ArmRole.VARIANT)
    )
    request = PairedRunRequest(
        "decision-dispatch", None,
        ArmSpec("baseline-arm", "hermes", "model-baseline", ()),
        ArmSpec("variant-arm", "hermes", "model-variant", ("skill-a",)),
        tasks, max_total_runs, 900, "revision-123", "2026-09-04T00:00:00Z", results,
    )
    return build_paired_run_decision(request).to_json()


def _config(
    *,
    approval: ApprovalState = ApprovalState.APPROVED,
    dry_run: bool = False,
    shared_mode: SharedResourceMode = SharedResourceMode.SERIALIZE,
    local_bound: CostTimeBound = CostTimeBound(8, 80),
) -> PairedRunDispatchConfig:
    budgets = DispatchBudgets(
        2,
        (NamedConcurrencyBudget("hermes", 2),),
        (NamedConcurrencyBudget("provider-a", 1),),
        local_bound,
        CostTimeBound(8, 80),
    )
    targets = (
        ArmDispatchTarget(ArmRole.BASELINE, "hermes", "provider-a", "model-baseline", CostTimeBound(1, 10), CostTimeBound(1, 10), "repo-lock"),
        ArmDispatchTarget(ArmRole.VARIANT, "hermes", "provider-a", "model-variant", CostTimeBound(1, 10), CostTimeBound(1, 10), "repo-lock"),
    )
    return PairedRunDispatchConfig(approval, dry_run, shared_mode, budgets, targets)


class PairedRunDispatchPlanTests(unittest.TestCase):
    def test_exact_expansion_preserves_inputs_revisions_and_workspace_identity(self) -> None:
        first = plan_paired_run_dispatch(_decision_document(), _config())
        second = plan_paired_run_dispatch(_decision_document(), _config())
        self.assertEqual(
            [(cell.task_id, cell.arm.value) for cell in first.cells],
            [("task-a", "baseline"), ("task-a", "variant"), ("task-b", "baseline"), ("task-b", "variant")],
        )
        self.assertEqual([cell.input_digest for cell in first.cells], ["a" * 64, "a" * 64, "b" * 64, "b" * 64])
        self.assertEqual({cell.execution_revision for cell in first.cells}, {"revision-123"})
        self.assertEqual(len({cell.workspace_id for cell in first.cells}), 4)
        self.assertEqual([cell.workspace_id for cell in first.cells], [cell.workspace_id for cell in second.cells])

    def test_refuses_unfair_bounds_before_cells_can_exist(self) -> None:
        with self.assertRaisesRegex(PairedRunDispatchPlanError, "local cost bound"):
            plan_paired_run_dispatch(_decision_document(), _config(local_bound=CostTimeBound(3, 80)))
        with self.assertRaisesRegex(PairedRunDispatchPlanError, "max_total_runs"):
            plan_paired_run_dispatch(_decision_document(max_total_runs=3), _config())

    def test_approval_shared_serialization_and_dry_run_have_no_runner(self) -> None:
        pending = plan_paired_run_dispatch(_decision_document(), _config(approval=ApprovalState.REQUIRED))
        dry_run = plan_paired_run_dispatch(_decision_document(), _config(dry_run=True))
        self.assertEqual(pending.launchable_cells, ())
        self.assertEqual(dry_run.launchable_cells, ())
        self.assertFalse(hasattr(dry_run, "runner"))
        waves = [cell.launch_wave for cell in pending.cells if cell.shared_resource_key == "repo-lock"]
        self.assertEqual(len(waves), len(set(waves)))

    def test_no_model_substitution_and_all_terminal_outcomes_gate_decision(self) -> None:
        config = _config()
        invalid = replace(config, targets=(replace(config.targets[0], model="replacement"), config.targets[1]))
        with self.assertRaisesRegex(PairedRunDispatchPlanError, "model"):
            plan_paired_run_dispatch(_decision_document(), invalid)
        plan = plan_paired_run_dispatch(_decision_document(), config)
        for outcome in TerminalState:
            with self.subTest(outcome=outcome):
                updated = record_terminal_state(plan, plan.cells[0].workspace_id, outcome)
                self.assertEqual(updated.cells[0].terminal_state, outcome)
                self.assertFalse(updated.decision_ready)
        for cell, outcome in zip(plan.cells, TerminalState, strict=False):
            plan = record_terminal_state(plan, cell.workspace_id, outcome)
        self.assertTrue(plan.decision_ready)


if __name__ == "__main__":
    unittest.main()