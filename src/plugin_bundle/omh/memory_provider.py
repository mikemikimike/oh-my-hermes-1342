"""OMH as a Hermes memory provider: the lane that runs without being called.

Everything OMH knew about memory used to require someone to ask. `omh memory
status` had the comparison, the `omh_memory` tool had it after PR #672, and both
waited for a question. Meanwhile Hermes' own memory kept being written by
``agent/background_review.py``, which forks after each turn and decides for
itself what to save -- with nothing telling it what OMH already holds, what is
duplicated, or how little room is left.

Hermes exposes the seam for this and OMH was not standing in it.
``plugins/memory/__init__.py`` scans ``$HERMES_HOME/plugins/<name>/`` as well as
its own bundled directory, which is where the OMH bundle already installs, and
``agent/memory_provider.py`` defines the lifecycle. Four of its hooks are the
ones that matter here:

- ``prefetch``       -- runs before every API call, so recall arrives unasked
- ``on_pre_compress``-- runs before compression discards messages
- ``on_memory_write``-- runs when Hermes writes its own memory, giving provenance
- ``on_session_end`` -- runs at a session boundary, where consolidation belongs

No tool schemas are exposed. ``memory_provider.py`` gives tool-schema bloat as
the reason only one external provider may run at a time, and OMH already
registers ten tools through the plugin path; the on-demand block read belongs on
``omh_memory``, which exists, rather than on a second registration path that
Hermes gates behind toolset config.

OMH still makes no model call and still cannot write Hermes memory. This
provider reads OMH's own store, renders it, and records what it saw.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # Present only inside the Hermes process.
    from agent.memory_provider import MemoryProvider as _MemoryProviderBase
except ImportError:  # pragma: no cover - exercised by the repo's own test run
    _MemoryProviderBase = object

from .hermes_memory import read_hermes_memory
from .memory_blocks import (
    DEFAULT_SYSTEM_RENDER_BUDGET_CHARS,
    REFERENCE_TIER,
    SYSTEM_TIER,
    read_memory_blocks,
    render_block_index,
    render_memory_blocks,
)
from .memory_dreaming import (
    build_consolidation_handoff,
    clear_after_consolidation,
    consolidation_reasons,
    read_dreaming_state,
    read_latest_consolidation,
    record_compaction,
    record_memory_write,
    record_turn,
    write_dreaming_state,
)
from .memory_eviction import build_eviction_plan

PROVIDER_NAME = "omh"
WRITE_JOURNAL_SCHEMA_VERSION = "omh_memory_write_journal_entry/v1"

# Hermes states that only a primary agent should write; a cron or subagent
# context replaying its own system prompt would otherwise move the counters that
# decide when consolidation is due.
_WRITING_CONTEXTS = frozenset({"", "primary"})

# Moments after which this session gets no further turn. The turn interval
# assumes a later turn will come; at these it will not, so a single
# unconsolidated turn is enough. `session_start_recovery` belongs here because
# it is settling the account of a session that already ended without one.
_SESSION_ENDING_TRIGGERS = frozenset({"session_end", "shutdown", "session_start_recovery"})


class OmhMemoryProvider(_MemoryProviderBase):
    """Deterministic, file-backed recall for Hermes. No model call, no network."""

    def __init__(self, omh_home: str | Path | None = None) -> None:
        self._omh_home = Path(omh_home).expanduser() if omh_home else _default_omh_home()
        self._hermes_home: Path | None = None
        self._session_id = ""
        self._writes_enabled = True
        # prefetch() is called before every API call and the base class asks for
        # it to be fast, so the pack is rendered off the hot path and served
        # from here.
        self._pack = ""

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    # -- Core lifecycle -----------------------------------------------------

    def is_available(self) -> bool:
        """True when there is an OMH home to read. Never touches the network."""
        try:
            return self._omh_home.is_dir()
        except OSError:
            return False

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = str(session_id or "")
        hermes_home = kwargs.get("hermes_home")
        self._hermes_home = Path(str(hermes_home)).expanduser() if hermes_home else None
        self._writes_enabled = str(kwargs.get("agent_context", "") or "") in _WRITING_CONTEXTS
        self._pack = self.render_pack()
        # A session that died rather than ended -- a killed process, a closed
        # laptop, a lost gateway -- never reaches on_session_end, so nothing
        # would ever act on the turns it accumulated. The counters survived on
        # disk; this is where they are honoured.
        self._evaluate_if_due("session_start_recovery")

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """None. The on-demand block read lives on the existing `omh_memory` tool."""
        return []

    def prefetch(self, query: str = "", *, session_id: str = "") -> str:
        return self._pack

    def queue_prefetch(self, query: str = "", *, session_id: str = "") -> None:
        """Re-render for the next turn, which is where the base class puts this work."""
        self._pack = self.render_pack()

    def shutdown(self) -> None:
        """Hermes is closing. Last chance to leave a brief behind."""
        self._evaluate_if_due("shutdown")
        self._pack = ""

    # -- Optional hooks -----------------------------------------------------

    def on_turn_start(self, turn_number: int, message: str = "", **kwargs: Any) -> None:
        if not self._writes_enabled:
            return
        self._mutate_state(record_turn)
        self._evaluate_if_due("turn")

    def on_pre_compress(self, messages: list[dict[str, Any]] | None = None) -> str:
        """Hand the compressor what must survive it, and note that it happened.

        Compaction is one of the two triggers Letta uses for dreaming, and it is
        the more informative one: the session just proved it outgrew its context.
        It is also the one place where waiting costs something real -- the brief
        has to exist *before* the messages go, not at whatever later moment the
        session happens to end -- so the evaluation runs here rather than being
        deferred with a flag.
        """
        if self._writes_enabled:
            self._mutate_state(record_compaction)
            self._evaluate_if_due("compaction", messages_at_risk=len(messages or []))
        blocks = read_memory_blocks(self._omh_home, tier=SYSTEM_TIER)
        if not blocks:
            return ""
        return render_memory_blocks(blocks, budget_chars=DEFAULT_SYSTEM_RENDER_BUDGET_CHARS)

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record that Hermes wrote, and what shape the entry was -- never its text.

        This is the hook that closes the provenance gap. Entries written by the
        background review used to appear in MEMORY.md with nothing recording that
        they had been written, by what, or when; OMH could only observe, later,
        that some entry matched no record it held.
        """
        if not self._writes_enabled:
            return
        self._append_write_journal(action, target, content, metadata)
        self._mutate_state(record_memory_write)
        # Retirement only, and only for consolidation-shaped writes. The first
        # version routed this through the full evaluation, which had two
        # measured consequences: every write below the headroom floor re-raised
        # a brief (the embedded value changes, so suppression never held) and
        # reset the turn counter, starving the interval trigger and growing the
        # journal one record per write. And gating on the trigger alone was not
        # enough either -- an interval-raised brief has its counters cleared at
        # birth, so ANY 'add' write one moment later looked like consolidation.
        # Hermes documents the action vocabulary as add/replace/remove:
        # an 'add' appends new material and consolidates nothing; 'replace' and
        # 'remove' are what a merge or prune actually emits.
        if action in ("replace", "remove") and not self._standing_reasons():
            self._retire_stale_brief("memory_write")

    def on_session_end(self, messages: list[dict[str, Any]] | None = None) -> None:
        self._evaluate_if_due("session_end")

    # -- Deterministic work, exposed for the CLI and for tests --------------

    def _evaluate_if_due(self, trigger: str, *, messages_at_risk: int = 0) -> dict[str, object] | None:
        """Weigh the triggers at one of the moments memory can be lost.

        Every trigger point calls this: each turn, compaction, session end,
        shutdown, and the start of the next session. Deferring the decision to
        session end alone -- which is what this did first -- means a laptop that
        closes mid-session writes nothing at all, and a turn interval that comes
        due at turn 5 waits until whenever the session happens to stop.
        """
        if not self._writes_enabled:
            return None
        return self.consolidation_due(trigger=trigger, messages_at_risk=messages_at_risk)

    def render_pack(self) -> str:
        """System blocks in full, reference blocks by label only."""
        system = render_memory_blocks(
            read_memory_blocks(self._omh_home, tier=SYSTEM_TIER),
            budget_chars=DEFAULT_SYSTEM_RENDER_BUDGET_CHARS,
        )
        index = render_block_index(read_memory_blocks(self._omh_home, tier=REFERENCE_TIER))
        return "\n".join(part for part in (system, index) if part)

    def consolidation_due(self, *, trigger: str = "manual", messages_at_risk: int = 0) -> dict[str, object]:
        """Decide whether dreaming is due; write the brief when it is.

        Returns the handoff either way so a caller can see the reasons that were
        weighed, not only the ones that fired.
        """
        state = read_dreaming_state(self._omh_home)
        plan, reason_kwargs = self._evaluation_inputs(trigger)
        reasons = consolidation_reasons(state, **reason_kwargs)
        handoff = build_consolidation_handoff(
            reasons,
            block_summaries=[block.to_summary() for block in read_memory_blocks(self._omh_home)],
            eviction_plan=plan,
            trigger=trigger,
            messages_at_risk=messages_at_risk,
            session_id=self._session_id,
            # Only a brief that actually fires was raised; stamping the not-due
            # inspection object gave it a raise time for a raise that never was.
            raised_at=_utc_now() if reasons else "",
        )
        if reasons:
            self._write_handoff(handoff)
            write_dreaming_state(
                self._omh_home,
                clear_after_consolidation(state, at=_utc_now(), reasons=reasons),
            )
        return handoff

    def _evaluation_inputs(self, trigger: str) -> tuple[dict[str, object], dict[str, object]]:
        """The eviction plan and reason kwargs for one evaluation, no writes."""
        reading = self._memory_reading()
        plan = (
            build_eviction_plan(reading.entries, cap=reading.cap, cap_source=reading.cap_source)
            if reading is not None
            else {}
        )
        return plan, {
            "headroom_chars": reading.headroom_chars if reading is not None else None,
            "duplicate_count": len(plan.get("duplicate_clusters", []) or []),
            "session_ending": trigger in _SESSION_ENDING_TRIGGERS,
        }

    def _standing_reasons(self) -> list[str]:
        """Is anything still true at all? Read-only, suppression bypassed.

        A suppressed standing condition returns [] from the default evaluation
        while remaining true; retirement must see through that, or it would
        clear a notice whose fact had not cleared.
        """
        _, reason_kwargs = self._evaluation_inputs("memory_write")
        return consolidation_reasons(read_dreaming_state(self._omh_home), suppress=False, **reason_kwargs)

    def _retire_stale_brief(self, trigger: str) -> None:
        """Mark the on-disk brief not-due once consolidation was observed.

        Nothing used to clear `consolidation.json`: it was written when
        consolidation came due and never touched again, so the doctor warning
        and every messenger's chat notice repeated forever -- including after
        the user actually consolidated.

        The only caller is the consolidation-shaped branch of
        `on_memory_write`: a 'replace' or 'remove' from Hermes' memory tool is
        what a merge or prune actually emits, and it is the one observable
        signal that consolidation happened. Timers, reads, and other triggers
        never retire -- event reasons clear their own counters by firing, so
        anything looser erases a brief before anyone could act on it.
        """
        brief = read_latest_consolidation(self._omh_home)
        if not brief or not brief.get("due"):
            return
        retired = dict(brief)
        retired["due"] = False
        retired["superseded_at"] = _utc_now()
        retired["superseded_by_trigger"] = trigger
        self._write_handoff(retired)

    # -- Internals ----------------------------------------------------------

    def _memory_reading(self):
        if self._hermes_home is None:
            return None
        try:
            readings = read_hermes_memory(self._hermes_home)
        except OSError:
            return None
        return next((item for item in readings if item.label == "MEMORY.md" and item.exists), None)

    def _mutate_state(self, mutate) -> None:
        state = read_dreaming_state(self._omh_home)
        self._safely(lambda: write_dreaming_state(self._omh_home, mutate(state)))

    def _write_handoff(self, handoff: dict[str, object]) -> None:
        """Latest brief where a reader looks; every brief where none is lost.

        Consolidation can come due more than once before anyone acts on it -- a
        turn interval, then a compaction, then a shutdown. Writing only the
        latest would mean the compaction brief, the one whose material is
        already gone, is the one overwritten.
        """
        directory = self._omh_home / "memory"
        payload = json.dumps(handoff, ensure_ascii=False, sort_keys=True)
        self._safely(lambda: _write_text(directory / "consolidation.json", payload))
        self._safely(lambda: _append_line(directory / "consolidation.jsonl", payload))

    def _append_write_journal(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        text = str(content or "")
        entry = {
            "schema_version": WRITE_JOURNAL_SCHEMA_VERSION,
            "observed_at": _utc_now(),
            "action": str(action or ""),
            "target": str(target or ""),
            "chars": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "session_id": self._session_id,
            "write_origin": str((metadata or {}).get("write_origin", "") or ""),
            "execution_context": str((metadata or {}).get("execution_context", "") or ""),
            "redaction_policy": "metadata_only",
        }
        path = self._omh_home / "memory" / "write_journal.jsonl"
        self._safely(lambda: _append_line(path, json.dumps(entry, ensure_ascii=False, sort_keys=True)))

    @staticmethod
    def _safely(write) -> None:
        """A memory-provider write must never take down the turn that triggered it.

        Hermes calls these hooks inside a live conversation. A read-only home, a
        full disk, or a racing writer is a lost journal line -- not a failed turn
        -- so the failure is swallowed here and nowhere else in this module.
        """
        try:
            write()
        except OSError:
            return


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _default_omh_home() -> Path:
    return Path(os.path.expandvars(os.environ.get("OMH_HOME", "") or "~/.omh")).expanduser()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
