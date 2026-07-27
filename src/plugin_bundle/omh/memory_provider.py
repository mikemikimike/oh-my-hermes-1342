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

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """None. The on-demand block read lives on the existing `omh_memory` tool."""
        return []

    def prefetch(self, query: str = "", *, session_id: str = "") -> str:
        return self._pack

    def queue_prefetch(self, query: str = "", *, session_id: str = "") -> None:
        """Re-render for the next turn, which is where the base class puts this work."""
        self._pack = self.render_pack()

    def shutdown(self) -> None:
        self._pack = ""

    # -- Optional hooks -----------------------------------------------------

    def on_turn_start(self, turn_number: int, message: str = "", **kwargs: Any) -> None:
        if not self._writes_enabled:
            return
        self._mutate_state(record_turn)

    def on_pre_compress(self, messages: list[dict[str, Any]] | None = None) -> str:
        """Hand the compressor what must survive it, and note that it happened.

        Compaction is one of the two triggers Letta uses for dreaming, and it is
        the more informative one: the session just proved it outgrew its context.
        """
        if self._writes_enabled:
            self._mutate_state(record_compaction)
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

    def on_session_end(self, messages: list[dict[str, Any]] | None = None) -> None:
        if not self._writes_enabled:
            return
        self.consolidation_due()

    # -- Deterministic work, exposed for the CLI and for tests --------------

    def render_pack(self) -> str:
        """System blocks in full, reference blocks by label only."""
        system = render_memory_blocks(
            read_memory_blocks(self._omh_home, tier=SYSTEM_TIER),
            budget_chars=DEFAULT_SYSTEM_RENDER_BUDGET_CHARS,
        )
        index = render_block_index(read_memory_blocks(self._omh_home, tier=REFERENCE_TIER))
        return "\n".join(part for part in (system, index) if part)

    def consolidation_due(self) -> dict[str, object]:
        """Decide whether dreaming is due; write the brief when it is.

        Returns the handoff either way so a caller can see the reasons that were
        weighed, not only the ones that fired.
        """
        state = read_dreaming_state(self._omh_home)
        reading = self._memory_reading()
        headroom = reading.headroom_chars if reading is not None else None
        plan = (
            build_eviction_plan(reading.entries, cap=reading.cap, cap_source=reading.cap_source)
            if reading is not None
            else {}
        )
        reasons = consolidation_reasons(
            state,
            headroom_chars=headroom,
            duplicate_count=len(plan.get("duplicate_clusters", []) or []),
        )
        handoff = build_consolidation_handoff(
            reasons,
            block_summaries=[block.to_summary() for block in read_memory_blocks(self._omh_home)],
            eviction_plan=plan,
        )
        if reasons:
            self._write_handoff(handoff)
            write_dreaming_state(
                self._omh_home,
                clear_after_consolidation(state, at=_utc_now(), reasons=reasons),
            )
        return handoff

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
        path = self._omh_home / "memory" / "consolidation.json"
        self._safely(
            lambda: _write_text(path, json.dumps(handoff, ensure_ascii=False, sort_keys=True))
        )

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
