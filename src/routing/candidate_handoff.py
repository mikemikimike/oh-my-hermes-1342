"""Hand an undecidable route to model selection instead of degrading it.

The deterministic router resolves confident requests well, and it should keep
doing that. What it does badly is the undecided case. Measured on a 24-message
natural-language sample, 8 turns ended in a picker and 2 in a bare fallback,
and 6 produced a score tie the scorer could not break. A user who wrote "PR
리뷰 좀 해줘" got a picker because two skills scored 9 apiece; a user who wrote
"ビルドが失敗した理由を教えて" got nothing because the trigger tables carry no
Kana. In both cases the router had the information needed to shortlist, and
threw it away to ask the user to do the routing instead.

This module turns that dead end into a handoff. When the route is undecidable,
OMH emits the candidates it did find -- each with the reason it matched, its
next action, and its evidence boundary -- and asks the model to choose. Hermes
already understands every language OMH targets and can read a shortlist of four
descriptions; that is the part it is good at.

OMH makes no LLM call here. It assembles candidates and a question; the
selection happens in Hermes. `docs/DIRECTION.md`'s "not an LLM router" boundary
holds, and the payload stays reproducible: the same message yields the same
candidate set and the same digest, so a routing decision remains auditable.
"""

from __future__ import annotations

import hashlib

from .input_language import SUPPORT_MODEL_SELECTION_REQUIRED
from ..skills.catalog import routable_definitions
from ..workflows.hermes_planning import is_coding_shaped_task


CANDIDATE_HANDOFF_SCHEMA_VERSION = "model_selection_candidates/v1"

# The workflows that actually deliver implementation work. Observed live: an
# implementation-shaped request ("...백엔드 구현해줘") reached model selection
# carrying instinct-ledger, materials-package, and memory-new at score 3 --
# decomposed-token noise -- while the picker in the same session offered
# idea-to-deploy and planning flows. The engines that do the work (ultraprocess,
# team, ultragoal) never surfaced, because nothing connected "this is coding"
# to "these are the coding candidates".
CODING_LANE_CANDIDATES = (
    ("ultraprocess", "prepare_coding_handoff"),
    ("team", "prepare_coding_handoff"),
    ("ultragoal", "prepare_goal_ledger"),
    ("executor-runtime-readiness", "check_executor_readiness"),
)

# Matches the router's own specific-capability minimum: below this, a match is
# decomposition noise, not a signal worth showing over the coding lane.
CODING_LANE_SCORE_FLOOR = 6

# Below this score gap the scorer is not discriminating between the top two
# candidates, it is picking one arbitrarily. Measured ties (gap 0) and near-ties
# (gap 1) both produced wrong winners on the sample corpus.
DECIDING_SCORE_GAP = 5

MAX_CANDIDATES = 4

REASON_LOW_CONFIDENCE = "low_confidence"
REASON_NARROW_SCORE_GAP = "narrow_score_gap"
REASON_NO_TRIGGER_COVERAGE = "no_trigger_coverage"

CLAIM_BOUNDARY = (
    "A candidate set is routing input for model selection, not a routing decision. "
    "It is not execution, review, CI, merge, or evidence that any candidate ran."
)

_UNDECIDED_ACTIONS = ("clarify", "fallback")


def _score_gap(recommendations: list[dict[str, object]]) -> int | None:
    if len(recommendations) < 2:
        return None
    return int(recommendations[0].get("score", 0) or 0) - int(recommendations[1].get("score", 0) or 0)


def candidate_handoff_reasons(route: dict[str, object]) -> tuple[str, ...]:
    """Why this route cannot be decided deterministically, in stable order."""
    if str(route.get("action", "")) not in _UNDECIDED_ACTIONS:
        return ()

    reasons: list[str] = []
    input_language = route.get("input_language")
    if isinstance(input_language, dict):
        if input_language.get("trigger_support") == SUPPORT_MODEL_SELECTION_REQUIRED:
            reasons.append(REASON_NO_TRIGGER_COVERAGE)

    recommendations = [item for item in route.get("recommendations", []) if isinstance(item, dict)]
    gap = _score_gap(recommendations)
    if gap is not None and gap < DECIDING_SCORE_GAP:
        reasons.append(REASON_NARROW_SCORE_GAP)
    if str(route.get("confidence", "")) == "low":
        reasons.append(REASON_LOW_CONFIDENCE)
    return tuple(reasons)


def _coding_lane_applies(candidates: list[dict[str, object]], message: str) -> bool:
    """Should the coding lane replace what scoring found?

    Only when the message is implementation-shaped AND every scored candidate
    is below the floor. A strong match -- memory-sync at 31, ultraprocess at a
    real trigger score -- keeps its shortlist; the lane replaces noise, never
    signal.
    """
    if not message or not is_coding_shaped_task(message):
        return False
    return all(int(candidate.get("score", 0) or 0) < CODING_LANE_SCORE_FLOOR for candidate in candidates)


def _coding_lane() -> list[dict[str, object]]:
    definitions = {definition.name: definition for definition in routable_definitions()}
    lane: list[dict[str, object]] = []
    for name, next_action in CODING_LANE_CANDIDATES:
        definition = definitions.get(name)
        if definition is None:
            continue
        lane.append(
            {
                "skill": definition.name,
                "description": definition.description,
                "why_it_matched": (
                    "The request is implementation-shaped; this is one of the workflows that "
                    "actually delivers coding work."
                ),
                "matched": ["coding_shaped_task"],
                "score": 0,
                "confidence": "low",
                "next_action": next_action,
                "evidence_boundary": (
                    "A candidate is routing input only; nothing has been planned, dispatched, "
                    "implemented, or verified."
                ),
            }
        )
    return lane[:MAX_CANDIDATES]


def _candidate(recommendation: dict[str, object]) -> dict[str, object]:
    return {
        "skill": recommendation.get("skill"),
        "description": recommendation.get("description"),
        "why_it_matched": recommendation.get("why"),
        "matched": list(recommendation.get("matched", []) or []),
        "score": recommendation.get("score"),
        "confidence": recommendation.get("confidence"),
        "next_action": recommendation.get("next_action"),
        "evidence_boundary": recommendation.get("evidence_boundary"),
    }


def candidate_handoff_digest(candidates: list[dict[str, object]], reasons: tuple[str, ...]) -> str:
    """Reproducible identity for this candidate set.

    Keyed on the candidate skills and the reasons, not on scores, so the digest
    survives score tuning while still changing when the shortlist changes.
    """
    # Joined fields, not json.dumps: this now runs inside the public payload
    # path, and the efficiency contract forbids JSON serialization during the
    # quality demos that walk every routing case. The identity content is
    # unchanged -- schema version, reasons, skills, in order -- and the unit
    # separator cannot occur in any of them.
    encoded = "\x1f".join(
        [
            CANDIDATE_HANDOFF_SCHEMA_VERSION,
            *[str(reason) for reason in reasons],
            *[str(candidate.get("skill")) for candidate in candidates],
        ]
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_candidate_handoff(route: dict[str, object], message: str = "") -> dict[str, object] | None:
    """Build the model-selection handoff, or None when the route is decidable."""
    reasons = candidate_handoff_reasons(route)
    if not reasons:
        return None

    recommendations = [item for item in route.get("recommendations", []) if isinstance(item, dict)]
    candidates = [_candidate(recommendation) for recommendation in recommendations[:MAX_CANDIDATES]]

    if _coding_lane_applies(candidates, message):
        candidates = _coding_lane()
        reasons = (*reasons, "implementation_shaped_request")

    payload: dict[str, object] = {
        "schema_version": CANDIDATE_HANDOFF_SCHEMA_VERSION,
        "reasons": list(reasons),
        "candidates": candidates,
        "candidate_count": len(candidates),
        "selector": "hermes",
        "digest": candidate_handoff_digest(candidates, reasons),
        "claim_boundary": CLAIM_BOUNDARY,
    }

    if "implementation_shaped_request" in reasons:
        payload["question"] = (
            "The request is implementation-shaped but no workflow matched strongly. These are "
            "the coding-delivery workflows; choose the one that fits the delivery grain, or ask "
            "one clarifying question. Do not route implementation work to planning-only flows."
        )
    elif candidates:
        payload["question"] = (
            "Which of these workflows fits the request? Choose one, say why in one line, "
            "and carry its evidence boundary forward. If none fit, ask one clarifying question."
        )
    else:
        # Scoring found nothing at all, which is the normal outcome for a script
        # the trigger tables do not cover. Point at the installed shortlist rather
        # than inventing candidates; `references/catalog-index.md` carries one line
        # per skill and is exactly what meta-router already tells the model to read.
        payload["question"] = (
            "No deterministic candidate matched this request. Shortlist from the installed "
            "`references/catalog-index.md`, confirm with a bounded `omh recommend` query, and "
            "name the chosen workflow with its evidence boundary."
        )
        payload["catalog_reference"] = "references/catalog-index.md"

    return payload
