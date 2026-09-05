"""Contract tests for the metadata-only critical-path health projection."""

from __future__ import annotations

from dataclasses import replace
import unittest

from _local_package import load_local_package

load_local_package()

from omh.runtime.critical_path_health import (  # noqa: E402
    CRITICAL_PATH_HEALTH_SCHEMA_VERSION,
    CriticalPathHealthEvent,
    compare_critical_path_health,
    project_critical_path_health,
)


def _event(
    task_id: str,
    event: str,
    at_ms: int,
    *,
    revision: str = "rev-1",
    dependencies: tuple[str, ...] = (),
    resource_class: str = "cpu",
    phase: str = "execution",
    retry: int = 0,
    terminal_status: str = "",
    reused: bool = False,
    executor: str = "codex",
    model: str = "model-1",
    environment: str = "env-1",
) -> CriticalPathHealthEvent:
    return CriticalPathHealthEvent(
        task_id=task_id,
        event=event,
        at_ms=at_ms,
        revision=revision,
        executor=executor,
        model=model,
        environment=environment,
        dependencies=dependencies,
        resource_class=resource_class,
        phase=phase,
        retry=retry,
        terminal_status=terminal_status,
        reused=reused,
    )


def _span(
    task_id: str,
    queued_at_ms: int,
    started_at_ms: int,
    finished_at_ms: int,
    terminal_status: str = "succeeded",
    **kwargs: object,
) -> tuple[CriticalPathHealthEvent, ...]:
    return (
        _event(task_id, "queued", queued_at_ms, **kwargs),
        _event(task_id, "started", started_at_ms, **kwargs),
        _event(task_id, "finished", finished_at_ms, terminal_status=terminal_status, **kwargs),
    )


class CriticalPathMetricTests(unittest.TestCase):
    def test_diamond_counts_shared_work_once_and_attributes_phase_and_resource(self) -> None:
        events = (
            *_span("a", 0, 0, 100, phase="plan", resource_class="io"),
            *_span("b", 100, 100, 300, dependencies=("a",), resource_class="cpu"),
            *_span("c", 100, 100, 400, dependencies=("a",), resource_class="gpu"),
            *_span("d", 400, 400, 500, dependencies=("b", "c"), phase="cleanup", resource_class="io"),
        )

        projection = project_critical_path_health(events)

        self.assertEqual(projection.schema_version, CRITICAL_PATH_HEALTH_SCHEMA_VERSION)
        self.assertEqual(projection.evidence_gaps, ())
        self.assertEqual(
            projection.metrics.to_dict(),
            {
                "wall_clock_ms": 500,
                "active_ms": 700,
                "queue_ms": 0,
                "critical_path_ms": 500,
                "peak_concurrency": 2,
                "overlap_savings_ms": 200,
                "repeated_cost_ms": 0,
                "stale_count": 0,
                "cleanup_tail_ms": 100,
                "reused_task_count": 0,
            },
        )
        self.assertEqual(projection.phase_attribution[0].to_dict(), {"name": "cleanup", "active_ms": 100, "queue_ms": 0, "repeated_cost_ms": 0, "task_count": 1})
        self.assertEqual(projection.resource_attribution[1].to_dict(), {"name": "gpu", "active_ms": 300, "queue_ms": 0, "repeated_cost_ms": 0, "task_count": 1})

    def test_serial_work_has_zero_overlap_and_retries_and_reuse_are_counted(self) -> None:
        events = (
            *_span("a", 0, 0, 100),
            *_span("b", 100, 100, 300, dependencies=("a",)),
            *_span("b", 300, 300, 350, dependencies=("a",), retry=1),
            *_span("c", 350, 350, 350, dependencies=("b",), reused=True),
            *_span("d", 350, 350, 400, dependencies=("c",), terminal_status="stale"),
        )

        projection = project_critical_path_health(events)

        self.assertEqual(projection.evidence_gaps, ())
        self.assertEqual(projection.metrics.to_dict()["overlap_savings_ms"], 0)
        self.assertEqual(projection.metrics.to_dict()["repeated_cost_ms"], 50)
        self.assertEqual(projection.metrics.to_dict()["reused_task_count"], 1)
        self.assertEqual(projection.metrics.to_dict()["stale_count"], 1)


class CriticalPathEvidenceGapTests(unittest.TestCase):
    def test_adversarial_lifecycles_are_gaps_not_normalized_metrics(self) -> None:
        cases = {
            "cycle": (*_span("a", 0, 0, 1, dependencies=("b",)), *_span("b", 1, 1, 2, dependencies=("a",))),
            "invalid_event_order": (_event("a", "started", 0), _event("a", "queued", 1), _event("a", "finished", 2, terminal_status="succeeded")),
            "missing_terminal": (_event("a", "queued", 0), _event("a", "started", 1)),
            "duplicate_terminal": (*_span("a", 0, 0, 1), _event("a", "finished", 2, terminal_status="succeeded")),
            "revision_mismatch": (_event("a", "queued", 0, revision="rev-1"), _event("a", "started", 1, revision="rev-2"), _event("a", "finished", 2, revision="rev-2", terminal_status="succeeded")),
        }
        for expected_gap, events in cases.items():
            with self.subTest(expected_gap=expected_gap):
                projection = project_critical_path_health(events)
                self.assertIsNone(projection.metrics)
                self.assertIn(expected_gap, tuple(gap.code for gap in projection.evidence_gaps))


class CriticalPathComparisonAndPrivacyTests(unittest.TestCase):
    def test_comparison_requires_the_same_task_revision_and_execution_identity(self) -> None:
        baseline = project_critical_path_health(_span("a", 0, 0, 10))
        candidate = project_critical_path_health(_span("a", 0, 0, 11))
        comparison = compare_critical_path_health(baseline, candidate)
        self.assertEqual(comparison["wall_clock_delta_ms"], 1)

        for replacement in (
            _span("b", 0, 0, 11),
            _span("a", 0, 0, 11, revision="rev-2"),
            _span("a", 0, 0, 11, executor="claude-code"),
            _span("a", 0, 0, 11, model="model-2"),
            _span("a", 0, 0, 11, environment="env-2"),
        ):
            with self.subTest(replacement=replacement[0].task_id):
                with self.assertRaisesRegex(ValueError, "incompatible"):
                    compare_critical_path_health(baseline, project_critical_path_health(replacement))

    def test_events_reject_private_or_payload_shaped_metadata(self) -> None:
        aws_access_key = "AKIA" + "IOSFODNN7EXAMPLE"
        for forbidden in (
            "command",
            "output",
            "source",
            "prompt",
            "credential",
            "private",
            "payload",
            aws_access_key,
        ):
            with self.subTest(forbidden=forbidden):
                with self.assertRaisesRegex(ValueError, "metadata"):
                    _event(f"task-{forbidden}", "queued", 0)

        safe = _event("task-a", "queued", 0)
        with self.assertRaisesRegex(ValueError, "privacy"):
            replace(safe, privacy="raw_payload")


if __name__ == "__main__":
    unittest.main()
