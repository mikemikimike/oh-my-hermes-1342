"""Production-writer fixture data for runtime health and artifact projections."""

from __future__ import annotations

from pathlib import Path

from omh.coding.fanout import build_fanout_contract
from omh.coding.fanout_artifacts import fanout_run_journal_path, write_fanout_contract
from omh.coding.fanout_journal import build_fanout_run_journal, write_fanout_run_journal
from omh.coding.fanout_health_events import write_fanout_health_event
from omh.runtime.critical_path_health_models import CriticalPathHealthEvent
from omh.system.paths import OmhPaths, resolve_paths
from omh.wrapper.sessions import create_or_resume_wrapper_session, prepare_wrapper_session_handoff, record_plan_decision, select_wrapper_session_executor


EXPECTED_METRICS = {"wall_clock_ms": 500, "active_ms": 700, "queue_ms": 0, "critical_path_ms": 500, "peak_concurrency": 2, "overlap_savings_ms": 200, "repeated_cost_ms": 0, "stale_count": 0, "cleanup_tail_ms": 100, "reused_task_count": 0}
ARTIFACT_ID = "handoff_prompt"
_REVISION = "fixture-revision"
_SESSION_MESSAGE = "risky refactor fixture-private-message-1290"
_SPANS = (("a", 0, 100, "plan", ()), ("b", 100, 300, "execution", ("a",)), ("c", 100, 400, "execution", ("a",)), ("d", 400, 500, "cleanup", ("b", "c")))


def fixture_paths(root: Path) -> OmhPaths:
    return resolve_paths(root, root / "hermes")


def build_happy(paths: OmhPaths) -> tuple[str, str]:
    contract = _write_contract(paths, "projection contract happy diamond")
    fanout_id = str(contract["fanout_id"])
    _write_journal(paths, contract)
    for task_id, queued, finished, phase, dependencies in _SPANS:
        _write_attempt(paths, fanout_id, task_id, queued, finished, phase, dependencies)
    return fanout_id, _write_runtime_session(paths)


def build_adversarial(paths: OmhPaths) -> tuple[str, str]:
    contract = _write_contract(paths, "projection contract adversarial cycle")
    fanout_id = str(contract["fanout_id"])
    _write_journal(paths, contract)
    _write_attempt(paths, fanout_id, "a", 0, 100, "execution", ("b",))
    _write_attempt(paths, fanout_id, "b", 100, 200, "execution", ("a",))
    return fanout_id, _write_runtime_session(paths)


def _write_contract(paths: OmhPaths, goal: str) -> dict[str, object]:
    return write_fanout_contract(paths, build_fanout_contract(goal, _units()))


def _units() -> list[dict[str, object]]:
    return [
        {"unit_id": "a", "title": "Plan", "file_scope": ["fixture/a"], "depends_on": []},
        {"unit_id": "b", "title": "Build B", "file_scope": ["fixture/b"], "depends_on": ["a"]},
        {"unit_id": "c", "title": "Build C", "file_scope": ["fixture/c"], "depends_on": ["a"]},
        {"unit_id": "d", "title": "Clean up", "file_scope": ["fixture/d"], "depends_on": ["b", "c"]},
    ]


def _write_journal(paths: OmhPaths, contract: dict[str, object]) -> None:
    units = contract["units"]
    assert isinstance(units, list)
    rows = [{"unit_id": str(unit["unit_id"]), "run_ref": str(unit["run_ref"]), "owner": "choose", "status": "completed", "exit_code": 0} for unit in units if isinstance(unit, dict)]
    journal = build_fanout_run_journal({"fanout_id": contract["fanout_id"], "base_sha": _REVISION, "merge_order": [row["unit_id"] for row in rows], "units": rows})
    write_fanout_run_journal(fanout_run_journal_path(paths, str(contract["fanout_id"])), journal)


def _write_attempt(paths: OmhPaths, fanout_id: str, task_id: str, queued: int, finished: int, phase: str, dependencies: tuple[str, ...]) -> None:
    for event, at_ms in (("queued", queued), ("started", queued), ("finished", finished)):
        write_fanout_health_event(paths, fanout_id, CriticalPathHealthEvent(task_id=task_id, event=event, at_ms=at_ms, revision=_REVISION, executor="fanout_dispatch", model="frozen_contract", environment="omh", dependencies=dependencies, resource_class="worker", phase=phase, terminal_status="succeeded" if event == "finished" else ""))


def _write_runtime_session(paths: OmhPaths) -> str:
    started = create_or_resume_wrapper_session(paths, _SESSION_MESSAGE, source="discord")
    session = started["session"]
    assert isinstance(session, dict)
    session_id = str(session["session_id"])
    record_plan_decision(paths, session_id, "accept")
    select_wrapper_session_executor(paths, session_id, "hermes")
    prepare_wrapper_session_handoff(paths, session_id, _SESSION_MESSAGE)
    return session_id
