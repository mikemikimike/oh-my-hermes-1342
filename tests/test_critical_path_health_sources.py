"""Read-only source projection tests for critical-path health."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import (  # noqa: E402
    fanout_run_journal_path,
    write_fanout_contract,
)
from omh.coding.fanout_journal import (  # noqa: E402
    FANOUT_RUN_JOURNAL_SCHEMA_VERSION,
    write_fanout_run_journal,
)
from omh.runtime.critical_path_health_sources import project_fanout_critical_path_health  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402
from omh.workflows.observation_journal import append_observation_event  # noqa: E402


_BASE_SHA = "revision-0123456789"


def _paths(root: Path) -> OmhPaths:
    return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")


def _contract(paths: OmhPaths) -> dict[str, object]:
    return write_fanout_contract(
        paths,
        build_fanout_contract(
            "project exact health from journals",
            [
                {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]},
                {
                    "unit_id": "tests",
                    "title": "Tests",
                    "owner": "codex",
                    "file_scope": ["tests/"],
                    "depends_on": ["core"],
                },
            ],
        ),
    )


def _objects(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise AssertionError(f"{label} must be a list")
    objects = [item for item in value if isinstance(item, dict)]
    if len(objects) != len(value):
        raise AssertionError(f"{label} must contain objects")
    return objects


def _contract_units(contract: dict[str, object]) -> list[dict[str, object]]:
    return _objects(contract.get("units"), "contract units")


def _refs(contract: dict[str, object]) -> dict[str, str]:
    return {str(unit["unit_id"]): str(unit["run_ref"]) for unit in _contract_units(contract)}


def _unit_ref(contract: dict[str, object], index: int) -> str:
    units = _contract_units(contract)
    if index >= len(units):
        raise AssertionError("fixture contract unit is missing")
    return str(units[index]["run_ref"])


def _journal(contract: dict[str, object], *, states: dict[str, str] | None = None) -> dict[str, object]:
    states = states or {"core": "succeeded", "tests": "succeeded"}
    units = []
    for unit in _contract_units(contract):
        unit_id = str(unit["unit_id"])
        terminal_state = states[unit_id]
        units.append(
            {
                "unit_id": unit_id,
                "run_ref": str(unit["run_ref"]),
                "owner": "codex",
                "terminal_state": terminal_state,
                "status": "completed" if terminal_state == "succeeded" else "failed",
                "failure_class": "",
                "failure_label": "",
                "decline_reason": "",
                "replay_safe": terminal_state != "succeeded",
                "replay_verdict": "replay_safe" if terminal_state != "succeeded" else "unsafe_side_effects",
                "side_effect": "no_spawn_observed",
                "blocked_on": [],
            }
        )
    return {
        "schema_version": FANOUT_RUN_JOURNAL_SCHEMA_VERSION,
        "fanout_id": str(contract["fanout_id"]),
        "observed_at": "2026-01-02T03:04:08Z",
        "base_sha": _BASE_SHA,
        "merge_order": ["core", "tests"],
        "units": units,
        "privacy": "metadata_only",
        "claim_boundary": "terminal process state only",
    }


def _observe(paths: OmhPaths, run_ref: str, event: str, observed_at: str, *, status: str = "observed", worker_ref: str) -> None:
    append_observation_event(
        paths,
        {
            "event_id": f"{run_ref}-{event}-{observed_at}",
            "target_type": "run",
            "target_id": run_ref,
            "run_id": run_ref,
            "event": event,
            "status": status,
            "observed_at": observed_at,
            "runtime_profile": "codex",
            "worker_ref": worker_ref,
            "summary": "metadata-only fixture",
        },
    )


class CriticalPathHealthSourceTests(unittest.TestCase):
    def test_legacy_dispatch_events_do_not_invent_zero_queue_time(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            contract = _contract(paths)
            write_fanout_run_journal(
                fanout_run_journal_path(paths, str(contract["fanout_id"])),
                _journal(contract),
            )
            for unit_id, run_ref in _refs(contract).items():
                dispatched_at, finished_at = (
                    ("2026-01-02T03:04:05Z", "2026-01-02T03:04:06Z")
                    if unit_id == "core"
                    else ("2026-01-02T03:04:06Z", "2026-01-02T03:04:07Z")
                )
                _observe(
                    paths,
                    run_ref,
                    "worker_dispatch",
                    dispatched_at,
                    worker_ref=unit_id,
                )
                _observe(
                    paths,
                    run_ref,
                    "worker_result",
                    finished_at,
                    worker_ref=unit_id,
                )

            result = project_fanout_critical_path_health(paths, str(contract["fanout_id"]))

            self.assertIsNone(result.record.metrics)
            self.assertIn(("core", "queue_evidence_unavailable"), result.evidence_gaps)
            self.assertIn(("tests", "queue_evidence_unavailable"), result.evidence_gaps)

    def test_projects_only_observed_started_and_finished_events_from_legacy_journals(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            contract = _contract(paths)
            write_fanout_run_journal(fanout_run_journal_path(paths, str(contract["fanout_id"])), _journal(contract))
            refs = _refs(contract)
            _observe(paths, refs["core"], "worker_dispatch", "2026-01-02T03:04:05Z", worker_ref="core")
            _observe(paths, refs["core"], "worker_result", "2026-01-02T03:04:06Z", worker_ref="core")
            _observe(paths, refs["tests"], "worker_dispatch", "2026-01-02T03:04:06Z", worker_ref="tests")
            _observe(paths, refs["tests"], "worker_result", "2026-01-02T03:04:08Z", worker_ref="tests")

            result = project_fanout_critical_path_health(paths, str(contract["fanout_id"]))

            self.assertEqual(
                [(event.task_id, event.event) for event in result.events],
                [("core", "started"), ("core", "finished"), ("tests", "started"), ("tests", "finished")],
            )
            self.assertEqual(result.record.schema_version, "critical_path_health/v1")
            self.assertIsNone(result.record.metrics)
            self.assertIn(("core", "queue_evidence_unavailable"), result.evidence_gaps)
            self.assertIn(("tests", "queue_evidence_unavailable"), result.evidence_gaps)

    def test_never_turns_incomplete_or_out_of_scope_evidence_into_health(self) -> None:
        cases = {
            "missing": ((), "missing_worker_dispatch"),
            "retry": ((("worker_dispatch", "2026-01-02T03:04:05Z", "observed"), ("worker_result", "2026-01-02T03:04:06Z", "failed"), ("worker_dispatch", "2026-01-02T03:04:07Z", "observed")), "retry_evidence_incomplete"),
            "cleanup": ((("worker_dispatch", "2026-01-02T03:04:05Z", "observed"), ("worker_result", "2026-01-02T03:04:06Z", "observed"), ("worktree_cleanup", "2026-01-02T03:04:07Z", "observed")), "cleanup_evidence_unavailable"),
        }
        for name, (observations, expected_gap) in cases.items():
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                paths = _paths(Path(tmp))
                contract = _contract(paths)
                write_fanout_run_journal(fanout_run_journal_path(paths, str(contract["fanout_id"])), _journal(contract))
                core_ref = _unit_ref(contract, 0)
                for event, timestamp, status in observations:
                    _observe(paths, core_ref, event, timestamp, status=status, worker_ref="core")
                result = project_fanout_critical_path_health(paths, str(contract["fanout_id"]))
                self.assertIsNone(result.record.metrics)
                self.assertIn(("core", expected_gap), result.evidence_gaps)
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            contract = _contract(paths)
            journal = _journal(contract)
            journal_units = _objects(journal.get("units"), "journal units")
            journal_units[0]["status"] = "already_completed"
            write_fanout_run_journal(fanout_run_journal_path(paths, str(contract["fanout_id"])), journal)

            result = project_fanout_critical_path_health(paths, str(contract["fanout_id"]))

            self.assertIn(("core", "reuse_evidence_unavailable"), result.evidence_gaps)

    def test_names_unreadable_and_mismatched_journal_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            contract = _contract(paths)
            journal_path = fanout_run_journal_path(paths, str(contract["fanout_id"]))
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            journal_path.write_text("{", encoding="utf-8")

            result = project_fanout_critical_path_health(paths, str(contract["fanout_id"]))

            self.assertIsNone(result.record.metrics)
            self.assertIn(("", "fanout_journal_journal_corrupt"), result.evidence_gaps)
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            contract = _contract(paths)
            write_fanout_run_journal(fanout_run_journal_path(paths, str(contract["fanout_id"])), _journal(contract))
            refs = _refs(contract)
            for unit_id, run_ref in refs.items():
                _observe(paths, run_ref, "worker_dispatch", "2026-01-02T03:04:05Z", worker_ref=unit_id)
                _observe(paths, run_ref, "worker_result", "2026-01-02T03:04:06Z", status="failed" if unit_id == "core" else "observed", worker_ref=unit_id)

            result = project_fanout_critical_path_health(paths, str(contract["fanout_id"]))

            self.assertIsNone(result.record.metrics)
            self.assertIn(("core", "terminal_mismatch"), result.evidence_gaps)
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            contract = _contract(paths)
            write_fanout_run_journal(fanout_run_journal_path(paths, str(contract["fanout_id"])), _journal(contract))
            paths.runtime_journal_events_path.parent.mkdir(parents=True)
            paths.runtime_journal_events_path.write_text(json.dumps({"schema_version": "invalid"}) + "\n", encoding="utf-8")

            result = project_fanout_critical_path_health(paths, str(contract["fanout_id"]))

            self.assertIsNone(result.record.metrics)
            self.assertIn(("", "observation_journal_invalid"), result.evidence_gaps)

    def test_verification_and_review_receipts_do_not_substitute_for_worker_results(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            contract = _contract(paths)
            write_fanout_run_journal(fanout_run_journal_path(paths, str(contract["fanout_id"])), _journal(contract))
            core_ref = _unit_ref(contract, 0)
            _observe(paths, core_ref, "worker_dispatch", "2026-01-02T03:04:05Z", worker_ref="core")
            _observe(paths, core_ref, "worker_result", "2026-01-02T03:04:06Z", worker_ref="core")
            _observe(paths, core_ref, "verification_result_observed", "2026-01-02T03:04:07Z", worker_ref="core")
            _observe(paths, core_ref, "review_result_observed", "2026-01-02T03:04:08Z", worker_ref="core")

            result = project_fanout_critical_path_health(paths, str(contract["fanout_id"]))

            self.assertEqual(
                [event.event for event in result.events if event.task_id == "core"],
                ["started", "finished"],
            )
            self.assertIn(("core", "queue_evidence_unavailable"), result.evidence_gaps)
            self.assertNotIn(("core", "missing_worker_result"), result.evidence_gaps)


if __name__ == "__main__":
    unittest.main()
