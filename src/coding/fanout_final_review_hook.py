"""Immutable post-integration fanout final-review hook."""

from __future__ import annotations

import re
from typing import Protocol

from .final_review_wave import (
    LANE_ORDER,
    FinalReviewWave,
    ImmutableRevision,
    LaneState,
    WaveVerdict,
)


_FIXED_REVISION = re.compile(r"[0-9a-f]{40}")


class FinalReviewWaveEngine(Protocol):
    """Caller-owned executor for one already-configured read-only review wave."""

    def execute(self, revision: ImmutableRevision) -> FinalReviewWave: ...


def run_final_review_after_integration(
    engine: FinalReviewWaveEngine | None,
    *,
    integrated_revision: str,
    integration_green: bool,
    producer_evidence: bool,
) -> dict[str, object] | None:
    """Execute one immutable review wave without changing dispatch readiness."""
    if engine is None:
        return None
    if _FIXED_REVISION.fullmatch(integrated_revision) is None:
        return _aggregate(integrated_revision, "BLOCK")
    if not integration_green or not producer_evidence:
        return _aggregate(integrated_revision, "HOLD")
    revision = ImmutableRevision(integrated_revision)
    wave = engine.execute(revision)
    if (
        wave.integration is None
        or not wave.integration.completed
        or wave.integration.revision != revision
        or tuple(lane.lens for lane in wave.lanes) != LANE_ORDER
        or any(lane.read_only.allows_mutation or lane.bound_revision != revision for lane in wave.lanes)
    ):
        return _aggregate(integrated_revision, "BLOCK")
    assessment = wave.assess()
    if any(lane.observed_revision != revision for lane in wave.lanes):
        return _aggregate(integrated_revision, "BLOCK", assessment.blocking_lens.value if assessment.blocking_lens else "")
    if assessment.verdict is WaveVerdict.PASS and any(
        lane.state is not LaneState.COMPLETED for lane in wave.lanes
    ):
        return _aggregate(integrated_revision, "BLOCK")
    records = [
        {
            "lens": lane.lens.value,
            "state": lane.state.value,
            "revision": integrated_revision,
        }
        for lane in wave.lanes
    ]
    result = _aggregate(
        integrated_revision,
        assessment.verdict.value,
        assessment.blocking_lens.value if assessment.blocking_lens else "",
    )
    result["final_review_records"] = records
    return result


def _aggregate(revision: str, verdict: str, blocking_lens: str = "") -> dict[str, object]:
    aggregate: dict[str, str] = {"revision": revision, "verdict": verdict}
    if blocking_lens:
        aggregate["blocking_lens"] = blocking_lens
    return {
        "final_review_status": verdict,
        "final_review_aggregate": aggregate,
    }
