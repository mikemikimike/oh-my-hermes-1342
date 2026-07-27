"""Scheduling for memory consolidation -- the deterministic half of "dreaming".

Letta surfaces sleep-time compute as dreaming: background subagents that review
recent turns, consolidate what was learned, and rewrite memory without blocking
the foreground session. The consolidation is model work. The *trigger* is not --
it fires after a configured number of user messages, or on a context-compaction
event.

That split is the whole reason this file exists. OMH makes no model call, so it
cannot dream. It can decide precisely when dreaming is due, on what evidence,
and hand Hermes a prepared brief -- and Hermes already runs the consolidation
loop itself (``agent/background_review.py`` forks after each turn with the
memory and skill tools). The gap this closes is that the loop runs with no
statement of what is duplicated, expiring, or out of room. It supplies that.

Counting turns is deliberate and unglamorous. The sleep-time compute paper is
explicit that the technique pays off in proportion to how predictable the next
query is, so a scheduler that fires on a fixed interval should not be sold as
one that fires when consolidation would help most.

Stdlib only; vendored in the bundle because it is imported inside the Hermes
process, where the ``omh`` package does not exist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DREAMING_STATE_SCHEMA_VERSION = "omh_memory_dreaming_state/v1"
DREAMING_HANDOFF_SCHEMA_VERSION = "omh_memory_consolidation_handoff/v1"

# Letta's server-side sleeptime default is every 5 steps; matched so the cadence
# has a stated origin rather than being picked here.
DEFAULT_TURN_INTERVAL = 5

# Free characters below which the memory file is treated as under pressure,
# whatever the turn count says. A full file is the failure this is meant to
# reach before it happens, not after.
DEFAULT_HEADROOM_FLOOR_CHARS = 300

# Modes. There is no auto-launch: OMH cannot start Hermes' consolidation, so
# offering the word would claim a capability the wrapper does not have.
DREAMING_MODES = ("off", "reminder")
DEFAULT_DREAMING_MODE = "reminder"


def dreaming_state_path(omh_home: str | Path) -> Path:
    return Path(omh_home).expanduser() / "memory" / "dreaming.json"


def empty_dreaming_state() -> dict[str, object]:
    return {
        "schema_version": DREAMING_STATE_SCHEMA_VERSION,
        "turns_since_consolidation": 0,
        "compaction_pending": False,
        "memory_writes_observed": 0,
        "last_consolidated_at": "",
        "last_reasons": [],
    }


def read_dreaming_state(omh_home: str | Path) -> dict[str, object]:
    """Persisted counters, or a fresh state when absent or unusable.

    Never raises. A corrupt counter file must cost at most one missed
    consolidation, not the turn that read it.
    """
    path = dreaming_state_path(omh_home)
    try:
        if path.is_symlink() or not path.is_file():
            return empty_dreaming_state()
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return empty_dreaming_state()
    if not isinstance(data, dict) or data.get("schema_version") != DREAMING_STATE_SCHEMA_VERSION:
        return empty_dreaming_state()
    state = empty_dreaming_state()
    state["turns_since_consolidation"] = _non_negative_int(data.get("turns_since_consolidation"))
    state["compaction_pending"] = bool(data.get("compaction_pending"))
    state["memory_writes_observed"] = _non_negative_int(data.get("memory_writes_observed"))
    state["last_consolidated_at"] = str(data.get("last_consolidated_at", "") or "")
    state["last_reasons"] = [str(item) for item in data.get("last_reasons", []) if isinstance(item, str)]
    return state


def write_dreaming_state(omh_home: str | Path, state: dict[str, Any]) -> Path:
    path = dreaming_state_path(omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def record_turn(state: dict[str, Any]) -> dict[str, object]:
    """One more user turn since the last consolidation."""
    updated = dict(state)
    updated["turns_since_consolidation"] = _non_negative_int(state.get("turns_since_consolidation")) + 1
    return updated


def record_compaction(state: dict[str, Any]) -> dict[str, object]:
    """Hermes is about to discard messages; consolidation is due next chance."""
    updated = dict(state)
    updated["compaction_pending"] = True
    return updated


def record_memory_write(state: dict[str, Any]) -> dict[str, object]:
    """Hermes wrote its own memory; the two stores may have diverged."""
    updated = dict(state)
    updated["memory_writes_observed"] = _non_negative_int(state.get("memory_writes_observed")) + 1
    return updated


def clear_after_consolidation(state: dict[str, Any], *, at: str, reasons: list[str]) -> dict[str, object]:
    updated = dict(state)
    updated["turns_since_consolidation"] = 0
    updated["compaction_pending"] = False
    updated["memory_writes_observed"] = 0
    updated["last_consolidated_at"] = at
    updated["last_reasons"] = list(reasons)
    return updated


def consolidation_reasons(
    state: dict[str, Any],
    *,
    mode: str = DEFAULT_DREAMING_MODE,
    turn_interval: int = DEFAULT_TURN_INTERVAL,
    headroom_chars: int | None = None,
    headroom_floor_chars: int = DEFAULT_HEADROOM_FLOOR_CHARS,
    duplicate_count: int = 0,
    expiring_count: int = 0,
    session_ending: bool = False,
) -> list[str]:
    """Why consolidation is due now, or an empty list when it is not.

    Reasons are returned rather than a bare boolean so the handoff can state its
    own cause. "It is time" and "the file is nearly full" ask for different work,
    and a brief that cannot tell them apart is a brief that says nothing.

    ``session_ending`` lowers the bar to a single unconsolidated turn, because
    the interval assumes a later turn will come and a closing session is exactly
    where that assumption fails. Three turns and a closed laptop would otherwise
    leave nothing behind.
    """
    if normalize_dreaming_mode(mode) == "off":
        return []
    reasons: list[str] = []
    interval = turn_interval if isinstance(turn_interval, int) and turn_interval > 0 else DEFAULT_TURN_INTERVAL
    turns = _non_negative_int(state.get("turns_since_consolidation"))
    if turns >= interval:
        reasons.append(f"turn_interval_reached:{turns}/{interval}")
    elif session_ending and turns > 0:
        reasons.append(f"session_ending_with_unconsolidated_turns:{turns}")
    if bool(state.get("compaction_pending")):
        reasons.append("context_compaction_observed")
    if headroom_chars is not None and headroom_chars <= max(headroom_floor_chars, 0):
        reasons.append(f"headroom_below_floor:{headroom_chars}<={headroom_floor_chars}")
    if duplicate_count > 0:
        reasons.append(f"duplicate_records:{duplicate_count}")
    if expiring_count > 0:
        reasons.append(f"expiring_records:{expiring_count}")
    return reasons


# What the executor is asked to do differs by which moment woke it. A brief
# written because the context is about to be discarded is asking for something
# a routine interval brief is not.
_TRIGGER_INSTRUCTIONS = {
    "compaction": (
        "Context compression is about to discard messages. Extract anything durable from them "
        "FIRST -- that material does not survive this turn."
    ),
    "shutdown": (
        "Hermes is closing. Save what is worth keeping now; there is no later turn in this session."
    ),
    "session_end": "The session ended. Consolidate what it produced before it is only a transcript.",
    "session_start_recovery": (
        "A previous session ended without consolidating -- a closed laptop, a killed process, a lost "
        "gateway. Its counters are below and its work was never reviewed."
    ),
    "turn": "The turn interval came due. Review recent work and consolidate what proved durable.",
}


def build_consolidation_handoff(
    reasons: list[str],
    *,
    block_summaries: list[dict[str, object]] | None = None,
    eviction_plan: dict[str, object] | None = None,
    mode: str = DEFAULT_DREAMING_MODE,
    trigger: str = "manual",
    messages_at_risk: int = 0,
    session_id: str = "",
) -> dict[str, object]:
    """A prepared brief for whoever actually consolidates.

    OMH never executes this. It states what it observed and what it would like
    decided; Hermes' own memory tool is the only thing that can act on it.
    """
    requested = [_TRIGGER_INSTRUCTIONS.get(trigger, "Review what is below and consolidate what is durable.")]
    if messages_at_risk:
        requested.append(f"{messages_at_risk} message(s) are in the buffer being compressed.")
    requested.extend(
        [
            "Rewrite or merge memory through Hermes' own memory tool, not through OMH.",
            "Leave anything you cannot source; an unsourced entry is not evidence it is wrong.",
        ]
    )
    return {
        "schema_version": DREAMING_HANDOFF_SCHEMA_VERSION,
        "mode": normalize_dreaming_mode(mode),
        "due": bool(reasons),
        "trigger": trigger,
        "session_id": session_id,
        "messages_at_risk": messages_at_risk,
        "reasons": list(reasons),
        "blocks": list(block_summaries or []),
        "eviction_plan": dict(eviction_plan or {}),
        "requested_of_executor": requested,
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "A consolidation handoff is prepared context. It is not evidence that memory was "
            "consolidated, that Hermes read it, or that any entry was written, changed, or removed."
        ),
    }


def normalize_dreaming_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in DREAMING_MODES else DEFAULT_DREAMING_MODE


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
