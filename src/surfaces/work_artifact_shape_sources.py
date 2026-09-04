"""Typed projection of persisted wrapper payloads into per-artifact shape sources.

This module owns the parsing half of the shape surface: it reads the same
already-persisted payloads the copy manifest reads (the coding briefing and
the session's prepared handoffs) and narrows them into mapping-typed shape
sources carrying exact source schemas, evidence states, and field-level refs.
It performs no I/O, mutates nothing, and never upgrades a prepared artifact
into observed evidence; rendering and availability decisions stay with the
committed ``show_shape`` facade.
"""

from __future__ import annotations

from collections.abc import Mapping

from .work_artifact_copy import _ARTIFACT_IDS


def work_artifact_shape_sources(
    briefing: Mapping[str, object],
    *,
    prompt_handoff: Mapping[str, object] | None = None,
    runtime_handoff: Mapping[str, object] | None = None,
    session_id: str = "",
) -> dict[str, Mapping[str, object] | None]:
    """Project each copy artifact's shape source from the same persisted payloads.

    Reads only the payloads the copy manifest already reads: the coding
    briefing and the session's prepared handoffs. The handoff artifact prefers
    the runtime handoff, the one prepared handoff whose schema the committed
    shape facade can trace; a prompt handoff beside it is still projected with
    its exact schema so the facade, not this module, reports it unsupported.
    """

    handoff = _first_mapping(runtime_handoff, prompt_handoff)
    prefix_session = session_id or str(briefing.get("session_id", ""))
    sources: dict[str, Mapping[str, object] | None] = {}
    for artifact_id in _ARTIFACT_IDS:
        if artifact_id == "handoff_prompt":
            sources[artifact_id] = (
                _handoff_shape_source(prefix_session, handoff) if handoff else None
            )
        else:
            sources[artifact_id] = (
                _briefing_shape_source(artifact_id, prefix_session, briefing)
                if briefing
                else None
            )
    return sources


def _handoff_shape_source(
    session_id: str, handoff: Mapping[str, object]
) -> dict[str, object]:
    """Project the prepared handoff's own fields into a facade shape source.

    Every node and edge is emitted only when its backing field is recorded, and
    carries a source ref naming that exact field, so nothing structural is
    inferred from an absent contract.
    """

    status = str(handoff.get("status", ""))
    profile = _mapping(handoff.get("runtime_profile"))
    owner = str(
        handoff.get("selected_executor_profile") or profile.get("profile") or ""
    )
    prefix = f"{session_id}#runtime_handoff"
    nodes: list[dict[str, object]] = []
    if status:
        nodes.append(
            _shape_node(
                "handoff",
                "Prepared runtime handoff",
                (f"{prefix}.status",),
                state=status,
                owner=owner,
            )
        )
    if profile:
        nodes.append(
            _shape_node(
                "executor",
                str(profile.get("label") or "Selected runtime"),
                (f"{prefix}.runtime_profile",),
                state=status,
                owner=owner,
            )
        )
    observation = _mapping(handoff.get("observation_contract"))
    if observation:
        nodes.append(
            _shape_node(
                "observation",
                "Runtime observation",
                (f"{prefix}.observation_contract",),
                state="not_observed",
                owner="omh",
            )
        )
    edges: list[dict[str, object]] = []
    if status and profile and handoff.get("dispatch_contract"):
        edges.append(
            _shape_edge(
                "handoff", "executor", (f"{prefix}.dispatch_contract",), "dispatches"
            )
        )
    if profile and observation:
        edges.append(
            _shape_edge(
                "executor",
                "observation",
                (f"{prefix}.observation_contract",),
                "reports",
            )
        )
    return {
        "source_artifact_id": prefix,
        "source_schema": str(handoff.get("schema_version", "")),
        "evidence_state": status,
        "nodes": nodes,
        "edges": edges,
        # The runtime's own ownership list, bounded by the facade's bullet budget.
        "bullets": _string_list(
            _mapping(handoff.get("runtime_brief")).get("runtime_owns")
        ),
    }


def _briefing_shape_source(
    artifact_id: str, session_id: str, briefing: Mapping[str, object]
) -> dict[str, object]:
    """The briefing-backed artifacts carry the briefing's exact schema.

    The committed facade does not support the briefing schema, so these sources
    render unavailable rather than being re-labeled with a schema they do not
    have.
    """

    return {
        "source_artifact_id": f"{session_id}#{artifact_id}",
        "source_schema": str(briefing.get("schema_version", "")),
        "evidence_state": "prepared_not_observed",
        "nodes": [],
    }


def _shape_node(
    node_id: str, label: str, refs: tuple[str, ...], *, state: str = "", owner: str = ""
) -> dict[str, object]:
    return {
        "node_id": node_id,
        "label": label,
        "source_refs": list(refs),
        "state": state,
        "owner": owner,
        "change": "unknown",
    }


def _shape_edge(
    source_id: str, target_id: str, refs: tuple[str, ...], label: str
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "target_id": target_id,
        "source_refs": list(refs),
        "label": label,
    }


def _first_mapping(*values: Mapping[str, object] | None) -> Mapping[str, object]:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]
