"""Metadata-only learning for explicit coding-owner choices.

This module owns the durable preference artifact and its pure transitions.  It
intentionally does not inspect request prose, model selection, executor results,
or timing data.  Integrating the resulting decision with wrapper routing is a
separate concern.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from ..system.local_store import atomic_write_json, read_json_object_result
from ..system.metadata_safety import require_opaque_metadata_ref
from ..system.paths import OmhPaths


OWNER_PREFERENCE_SCHEMA_VERSION: Final = "coding_owner_preference/v1"
OWNER_PREFERENCE_RECORD_TYPE: Final = "coding_owner_preference"
OWNER_PREFERENCE_LEARNING_THRESHOLD: Final = 3
OWNER_PREFERENCE_EXCLUDED_SIGNALS: Final = (
    "performance",
    "failure",
    "benchmark",
    "latency",
    "model_choice",
)
OWNER_PREFERENCE_PATH_SEGMENTS: Final = ("routing", "owner-preference.json")

_STATE_KEYS: Final = {
    "schema_version",
    "record_type",
    "privacy",
    "routes",
    "updated_at",
}
_PRIVACY_KEYS: Final = {"mode", "learning_source", "excluded_signals"}
_ROUTE_KEYS: Final = {
    "route_family",
    "selected_owner",
    "consecutive_accepted_explicit_choices",
    "first_choice_at",
    "last_choice_at",
    "learned_at",
    "reset_at",
    "reset_reason",
}


@dataclass(frozen=True)
class OwnerPreferenceDecision:
    """The safe routing projection of learned owner state."""

    action: str
    reason_code: str
    reason: str
    route_family: str
    selected_owner: str
    evidence_count: int
    override_available: bool


def empty_owner_preference_state(*, updated_at: str = "") -> dict[str, Any]:
    """Return a valid state with no learned routes.

    ``updated_at`` is caller-supplied so construction and every transition stay
    deterministic.  An empty timestamp means no preference event has occurred.
    """
    if updated_at:
        _require_timestamp(updated_at, field="updated_at")
    return {
        "schema_version": OWNER_PREFERENCE_SCHEMA_VERSION,
        "record_type": OWNER_PREFERENCE_RECORD_TYPE,
        "privacy": {
            "mode": "metadata_only",
            "learning_source": "accepted_explicit_owner_choice",
            "excluded_signals": list(OWNER_PREFERENCE_EXCLUDED_SIGNALS),
        },
        "routes": {},
        "updated_at": updated_at,
    }


def owner_preference_decision(
    state: Mapping[str, Any] | None,
    *,
    route_family: str,
    coding_delivery: bool = True,
    ulw: bool = True,
    named_owner: bool = False,
    multiple_owners: bool = False,
    authority_blocked: bool = False,
    owner_ready: bool = True,
    capability_fit: bool = True,
) -> OwnerPreferenceDecision:
    """Decide whether to ask, bypass learning, or expose a learned default.

    Scope and safety gates always outrank learned state.  Missing or malformed
    state is treated exactly like an empty state, so it can only produce an
    explicit choice, never an accidental default.
    """
    family = require_opaque_metadata_ref(route_family, field="route_family")
    safe = _safe_state(state)
    route = safe["routes"].get(family)
    count = int(route["consecutive_accepted_explicit_choices"]) if route else 0

    if not coding_delivery:
        return _decision("bypass_owner_learning", "non_coding_workflow", family, count)
    if not ulw:
        return _decision("bypass_owner_learning", "non_ulw_workflow", family, count)
    if named_owner:
        return _decision("bypass_owner_learning", "owner_named_in_request", family, count)
    if multiple_owners:
        return _decision("ask_explicit_owner", "multiple_owners_named", family, count)
    if authority_blocked:
        return _decision("ask_explicit_owner", "authority_requires_choice", family, count)
    if not owner_ready:
        return _decision("ask_explicit_owner", "owner_unready", family, count)
    if not capability_fit:
        return _decision("ask_explicit_owner", "capability_gap", family, count)

    if route and count >= OWNER_PREFERENCE_LEARNING_THRESHOLD and route["selected_owner"]:
        return OwnerPreferenceDecision(
            action="use_learned_default",
            reason_code="three_consecutive_explicit_choices",
            reason=(
                "three consecutive accepted explicit choices established this visible default; "
                "the user can override or reset it."
            ),
            route_family=family,
            selected_owner=str(route["selected_owner"]),
            evidence_count=count,
            override_available=True,
        )
    return _decision("ask_explicit_owner", "learning_window", family, count)


def record_accepted_explicit_choice(
    state: Mapping[str, Any] | None,
    *,
    route_family: str,
    selected_owner: str,
    occurred_at: str,
    accepted: bool = True,
    explicit: bool = True,
    coding_delivery: bool = True,
    ulw: bool = True,
    named_owner: bool = False,
    multiple_owners: bool = False,
    authority_blocked: bool = False,
    owner_ready: bool = True,
    capability_fit: bool = True,
) -> dict[str, Any]:
    """Record one qualifying accepted explicit handoff without mutating input.

    A changed owner starts a new streak at one and leaves a visible reset
    reason.  Non-qualifying events are exact no-ops; in particular, outcomes,
    model choices, latency, and benchmark data are not parameters and cannot
    influence this transition.
    """
    family = require_opaque_metadata_ref(route_family, field="route_family")
    owner = require_opaque_metadata_ref(selected_owner, field="selected_owner")
    timestamp = _require_timestamp(occurred_at, field="occurred_at")
    safe = _safe_state(state)
    if not _qualifies(
        accepted=accepted,
        explicit=explicit,
        coding_delivery=coding_delivery,
        ulw=ulw,
        named_owner=named_owner,
        multiple_owners=multiple_owners,
        authority_blocked=authority_blocked,
        owner_ready=owner_ready,
        capability_fit=capability_fit,
    ):
        return safe

    updated = deepcopy(safe)
    previous = updated["routes"].get(family)
    changed = previous is not None and previous["selected_owner"] != owner
    if previous is None or changed or not previous["selected_owner"]:
        count = 1
        first_choice_at = timestamp
        learned_at = ""
    else:
        count = int(previous["consecutive_accepted_explicit_choices"]) + 1
        first_choice_at = str(previous["first_choice_at"])
        learned_at = str(previous["learned_at"])
    if count >= OWNER_PREFERENCE_LEARNING_THRESHOLD and not learned_at:
        learned_at = timestamp

    updated["routes"][family] = {
        "route_family": family,
        "selected_owner": owner,
        "consecutive_accepted_explicit_choices": count,
        "first_choice_at": first_choice_at,
        "last_choice_at": timestamp,
        "learned_at": learned_at,
        "reset_at": timestamp if changed else str(previous["reset_at"]) if previous else "",
        "reset_reason": (
            "explicit_owner_changed" if changed else str(previous["reset_reason"]) if previous else ""
        ),
    }
    updated["updated_at"] = timestamp
    _raise_if_invalid(updated)
    return updated


def reset_owner_preference(
    state: Mapping[str, Any] | None,
    *,
    route_family: str,
    reason: str,
    occurred_at: str,
) -> dict[str, Any]:
    """Explicitly clear one route-family preference and retain reset metadata."""
    family = require_opaque_metadata_ref(route_family, field="route_family")
    reset_reason = require_opaque_metadata_ref(reason, field="reset reason")
    timestamp = _require_timestamp(occurred_at, field="occurred_at")
    updated = deepcopy(_safe_state(state))
    updated["routes"][family] = {
        "route_family": family,
        "selected_owner": "",
        "consecutive_accepted_explicit_choices": 0,
        "first_choice_at": "",
        "last_choice_at": "",
        "learned_at": "",
        "reset_at": timestamp,
        "reset_reason": reset_reason,
    }
    updated["updated_at"] = timestamp
    _raise_if_invalid(updated)
    return updated


def owner_preference_path(paths: OmhPaths) -> Path:
    """Return the dedicated artifact path, separate from setup-profile state."""
    return paths.omh_home.joinpath(*OWNER_PREFERENCE_PATH_SEGMENTS)


def read_owner_preference(paths: OmhPaths) -> dict[str, Any]:
    """Read valid learned state; missing, unreadable, or corrupt state is empty."""
    state, error = read_json_object_result(owner_preference_path(paths))
    if error or state is None or validate_owner_preference(state):
        return empty_owner_preference_state()
    return state


def write_owner_preference(paths: OmhPaths, state: Mapping[str, Any]) -> Path:
    """Validate and atomically write the private preference artifact."""
    _raise_if_invalid(state)
    path = owner_preference_path(paths)
    atomic_write_json(path, dict(state), private=True)
    return path


def validate_owner_preference(state: Mapping[str, Any]) -> list[str]:
    """Validate the closed owner-preference schema without raising."""
    errors: list[str] = []
    if set(state) != _STATE_KEYS:
        errors.append("owner preference must contain exactly the schema fields")
    if state.get("schema_version") != OWNER_PREFERENCE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {OWNER_PREFERENCE_SCHEMA_VERSION}")
    if state.get("record_type") != OWNER_PREFERENCE_RECORD_TYPE:
        errors.append(f"record_type must be {OWNER_PREFERENCE_RECORD_TYPE}")

    privacy = state.get("privacy")
    if not isinstance(privacy, Mapping) or set(privacy) != _PRIVACY_KEYS:
        errors.append("privacy must contain exactly mode, learning_source, and excluded_signals")
    elif (
        privacy.get("mode") != "metadata_only"
        or privacy.get("learning_source") != "accepted_explicit_owner_choice"
        or privacy.get("excluded_signals") != list(OWNER_PREFERENCE_EXCLUDED_SIGNALS)
    ):
        errors.append("privacy must preserve the explicit-choice-only metadata boundary")

    updated_at = state.get("updated_at")
    if not isinstance(updated_at, str) or (updated_at and not _valid_timestamp(updated_at)):
        errors.append("updated_at must be empty or an ISO-8601 timestamp")

    routes = state.get("routes")
    if not isinstance(routes, Mapping):
        errors.append("routes must be a route-family mapping")
        return errors
    for key, route in routes.items():
        errors.extend(_route_errors(key, route))
    return errors


def _decision(action: str, reason_code: str, route_family: str, count: int) -> OwnerPreferenceDecision:
    reasons = {
        "non_coding_workflow": "Owner learning does not apply to a non-coding workflow.",
        "non_ulw_workflow": "Owner learning does not apply outside an ULW workflow.",
        "owner_named_in_request": "The request already names an owner, so learned state is bypassed.",
        "multiple_owners_named": "Multiple named owners require a fresh explicit choice.",
        "authority_requires_choice": "The authority boundary requires a fresh explicit choice.",
        "owner_unready": "The learned owner is not ready, so the owner choice is reopened.",
        "capability_gap": "A required capability is not met, so the owner choice is reopened.",
        "learning_window": "Fewer than three consecutive accepted explicit choices exist; ask again.",
    }
    return OwnerPreferenceDecision(
        action=action,
        reason_code=reason_code,
        reason=reasons[reason_code],
        route_family=route_family,
        selected_owner="",
        evidence_count=count,
        override_available=False,
    )


def _qualifies(**flags: bool) -> bool:
    return (
        flags["accepted"]
        and flags["explicit"]
        and flags["coding_delivery"]
        and flags["ulw"]
        and not flags["named_owner"]
        and not flags["multiple_owners"]
        and not flags["authority_blocked"]
        and flags["owner_ready"]
        and flags["capability_fit"]
    )


def _safe_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, Mapping) or validate_owner_preference(state):
        return empty_owner_preference_state()
    return deepcopy(dict(state))


def _route_errors(key: object, route: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(key, str):
        return ["route-family keys must be strings"]
    try:
        family = require_opaque_metadata_ref(key, field="route-family key")
    except ValueError as exc:
        return [str(exc)]
    if not isinstance(route, Mapping) or set(route) != _ROUTE_KEYS:
        return [f"route {family} must contain exactly the route preference fields"]
    if route.get("route_family") != family:
        errors.append(f"route {family} must repeat its route-family key")

    owner = route.get("selected_owner")
    if not isinstance(owner, str):
        errors.append(f"route {family} selected_owner must be a string")
    elif owner:
        try:
            require_opaque_metadata_ref(owner, field=f"route {family} selected_owner")
        except ValueError as exc:
            errors.append(str(exc))
    count = route.get("consecutive_accepted_explicit_choices")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        errors.append(f"route {family} consecutive choice count must be a nonnegative integer")
        count = -1
    if (count == 0) != (owner == ""):
        errors.append(f"route {family} owner must be empty exactly when its count is zero")

    for field in ("first_choice_at", "last_choice_at", "learned_at", "reset_at"):
        value = route.get(field)
        if not isinstance(value, str) or (value and not _valid_timestamp(value)):
            errors.append(f"route {family} {field} must be empty or an ISO-8601 timestamp")
    if count > 0 and (not route.get("first_choice_at") or not route.get("last_choice_at")):
        errors.append(f"route {family} a nonempty streak requires first and last timestamps")
    if count >= OWNER_PREFERENCE_LEARNING_THRESHOLD and not route.get("learned_at"):
        errors.append(f"route {family} a learned streak requires learned_at")
    if 0 <= count < OWNER_PREFERENCE_LEARNING_THRESHOLD and route.get("learned_at"):
        errors.append(f"route {family} an unlearned streak cannot have learned_at")

    reason = route.get("reset_reason")
    if not isinstance(reason, str):
        errors.append(f"route {family} reset_reason must be a string")
    elif reason:
        try:
            require_opaque_metadata_ref(reason, field=f"route {family} reset_reason")
        except ValueError as exc:
            errors.append(str(exc))
    if bool(reason) != bool(route.get("reset_at")):
        errors.append(f"route {family} reset_reason and reset_at must appear together")
    return errors


def _require_timestamp(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _valid_timestamp(value):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    return value


def _valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _raise_if_invalid(state: Mapping[str, Any]) -> None:
    errors = validate_owner_preference(state)
    if errors:
        raise ValueError("; ".join(errors))
