"""Typed contracts for external coding handoff coordination.

This package is unrelated to the awesome-catalog project named Maestro.
It coordinates prepared OMH handoffs and never acts as a coding executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Protocol, TypeAlias


ExternalProfile: TypeAlias = Literal[
    "codex",
    "claude-code",
    "omx-runtime",
    "omo-runtime",
    "omc-runtime",
    "generic",
]
HandoffField: TypeAlias = Literal["executor_handoff", "prompt_handoff", "runtime_handoff"]


@dataclass(frozen=True)
class ExternalHandoffRequest:
    """Minimal request accepted by the external handoff facade."""

    message: str
    profile: str
    source: str = "generic"
    limit: int = 3
    include_message: bool = False
    source_metadata: Mapping[str, str] | None = None
    main_agent_model: str = ""
    context_pack: dict[str, object] | None = None
    input_manifest: dict[str, object] | None = None
    memory_recall_pack: dict[str, object] | None = None
    plan_artifact: dict[str, object] | None = None
    preferred_workflow: str | None = None
    preferred_workflow_score: int | None = None
    prefer_direct_coding_handoff: bool = True
    preserve_preferred_workflow: bool = False
    force_coding_handoff: bool = False
    capability_snapshot_directory: Path | None = None
    project_root: str | Path | None = None
    governance_default: str = "not_applicable"
    product_family: str | None = None
    message_context_mode: str = "full"
    safety_preflight: dict[str, object] | None = None
    live_safety_profile_revision: str | None = None
    requested_authority_actions: tuple[str, ...] | list[str] | None = None
    model_recommendation: dict[str, object] | None = None


@dataclass(frozen=True)
class ExternalHandoffCapability:
    """Coordination capability derived from an existing prepared payload."""

    profile: ExternalProfile
    work_owner_mode: str
    handoff_field: HandoffField
    schema_version: str
    dispatchable: bool
    executes_work: bool = False
    observation_boundary: str = "prepared_not_observed"


@dataclass(frozen=True)
class PreparedExternalHandoff:
    """Untouched builder payload plus its typed coordination metadata."""

    capability: ExternalHandoffCapability
    payload: dict[str, object]
    handoff: dict[str, object]

    @property
    def handoff_field(self) -> HandoffField:
        return self.capability.handoff_field


class PreparedHandoffStatusAdapter(Protocol):
    """Projects status without granting maestro execution authority."""

    def status_for(self, handoff: PreparedExternalHandoff) -> Mapping[str, object]: ...


class PreparedHandoffObservationAdapter(Protocol):
    """Reads observations recorded by the selected external owner."""

    def observations_for(
        self,
        handoff: PreparedExternalHandoff,
    ) -> tuple[Mapping[str, object], ...]: ...
