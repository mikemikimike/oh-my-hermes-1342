"""Read the dispatcher's typed critical-path journal conservatively."""

from __future__ import annotations

from ..coding.fanout_health_events import fanout_health_events_path
from ..system.local_store import read_jsonl_objects
from ..system.paths import OmhPaths
from .critical_path_health_models import CriticalPathHealthEvent
from .critical_path_health_source_parsing import ObjectMapping, object_mapping, string_values


def read_direct_health_events(
    paths: OmhPaths,
    fanout_id: str,
    gaps: set[tuple[str, str]],
) -> tuple[CriticalPathHealthEvent, ...] | None:
    """Read explicit lifecycle observations, or select legacy fallback when absent."""
    try:
        path = fanout_health_events_path(paths, fanout_id)
    except ValueError:
        gaps.add(("", "health_event_journal_invalid"))
        return ()
    if not path.exists():
        return None
    records, errors = read_jsonl_objects(path)
    if errors:
        gaps.add(("", "health_event_journal_invalid"))
    events: list[CriticalPathHealthEvent] = []
    for record in records:
        event = _direct_health_event(object_mapping(record))
        if event is None:
            gaps.add(("", "health_event_journal_invalid"))
            continue
        events.append(event)
    return tuple(events)


def _direct_health_event(record: ObjectMapping | None) -> CriticalPathHealthEvent | None:
    if record is None:
        return None
    dependencies = string_values(record.get("dependencies"))
    at_ms = record.get("at_ms")
    if dependencies is None or isinstance(at_ms, bool) or not isinstance(at_ms, int):
        return None
    try:
        return CriticalPathHealthEvent(
            task_id=str(record.get("task_id", "")),
            event=str(record.get("event", "")),
            at_ms=at_ms,
            revision=str(record.get("revision", "")),
            executor=str(record.get("executor", "")),
            model=str(record.get("model", "")),
            environment=str(record.get("environment", "")),
            dependencies=tuple(dependencies),
            resource_class=str(record.get("resource_class", "")),
            phase=str(record.get("phase", "")),
            retry=record.get("retry", 0),
            terminal_status=str(record.get("terminal_status", "")),
            reused=record.get("reused", False),
            schema_version=str(record.get("schema_version", "")),
            privacy=str(record.get("privacy", "")),
        )
    except ValueError:
        return None
