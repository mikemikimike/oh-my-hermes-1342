"""Read what Hermes actually remembers, not just how large the file is.

Hermes keeps its built-in memory in ``~/.hermes/memories/MEMORY.md`` and
``USER.md`` as a ``§``-delimited entry list, and enforces a *character* cap per
file on write (``hermes-agent/tools/memory_tool.py``). OMH's advisory lane used
``stat().st_size`` for that comparison, which is a different unit: UTF-8 spends
three bytes on a Hangul syllable, so a Korean MEMORY.md reads about 1.2x its own
length. A 1,933-character file reports as ``2347 bytes (cap ~2200)`` and looks
over budget while Hermes still accepts writes. An ASCII file of the same length
reports correctly, which is why the mismatch went unnoticed.

Counting characters fixes the unit. Splitting the entries is what lets the rest
of OMH say *which* entry is stale or already duplicated in its own store,
instead of only how full the file is.

Read-only by construction: nothing here opens a file for writing. Hermes owns
these files, and the `memory` tool it exposes to the model is the surface that
edits them.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Hermes' own entry separator; see ENTRY_DELIMITER in its memory tool.
HERMES_MEMORY_DELIMITER = "§"

# Hermes memory files and the character caps it enforces on write.
MEMORY_FILE_CAP_CHARS = 2200
USER_FILE_CAP_CHARS = 1375

HERMES_MEMORY_FILES = (
    ("MEMORY.md", MEMORY_FILE_CAP_CHARS),
    ("USER.md", USER_FILE_CAP_CHARS),
)


@dataclass(frozen=True)
class HermesMemoryFile:
    """One Hermes memory file as OMH observed it."""

    label: str
    path: Path
    exists: bool
    chars: int
    cap: int
    entries: tuple[str, ...]
    age_days: float
    error: str = ""

    @property
    def over_cap(self) -> bool:
        return self.exists and self.chars > self.cap

    @property
    def headroom_chars(self) -> int:
        """Characters a new entry may occupy, delimiter included."""
        if not self.exists:
            return self.cap
        return max(0, self.cap - self.chars)

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "path": str(self.path),
            "exists": self.exists,
            "chars": self.chars,
            "cap": self.cap,
            "over_cap": self.over_cap,
            "headroom_chars": self.headroom_chars,
            "entry_count": len(self.entries),
            "age_days": round(self.age_days, 1),
            "error": self.error,
        }


def parse_memory_entries(text: str) -> tuple[str, ...]:
    """Split one Hermes memory file into its entries."""
    return tuple(entry.strip() for entry in text.split(HERMES_MEMORY_DELIMITER) if entry.strip())


def memory_char_count(entries: tuple[str, ...] | list[str]) -> int:
    """Count characters the way Hermes counts them when enforcing the cap."""
    if not entries:
        return 0
    return len(HERMES_MEMORY_DELIMITER.join(entries))


def read_hermes_memory_file(
    path: Path,
    *,
    label: str,
    cap: int,
    now: float | None = None,
) -> HermesMemoryFile:
    """Read one memory file. Never raises: an unreadable file reports its error."""
    moment = time.time() if now is None else now
    if not path.exists():
        return HermesMemoryFile(label, path, False, 0, cap, (), 0.0)
    try:
        text = path.read_text(encoding="utf-8")
        age_days = max(0.0, (moment - path.stat().st_mtime) / 86400.0)
    except (OSError, UnicodeDecodeError) as error:
        return HermesMemoryFile(label, path, True, 0, cap, (), 0.0, error=str(error))
    entries = parse_memory_entries(text)
    return HermesMemoryFile(label, path, True, memory_char_count(entries), cap, entries, age_days)


def read_hermes_memory(
    hermes_home: str | Path,
    *,
    now: float | None = None,
) -> tuple[HermesMemoryFile, ...]:
    """Read every Hermes memory file under one Hermes home."""
    memories_dir = Path(hermes_home).expanduser() / "memories"
    return tuple(
        read_hermes_memory_file(memories_dir / name, label=name, cap=cap, now=now)
        for name, cap in HERMES_MEMORY_FILES
    )


# A fact restated in Hermes' own words shares most of its nouns but almost none
# of its punctuation or particles, so token overlap separates "already known"
# from "new" where exact matching cannot. The threshold is deliberately loose:
# this only decides what to *show* a reviewer, never what to write.
DUPLICATE_SIMILARITY_THRESHOLD = 0.6

_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def text_tokens(text: str) -> frozenset[str]:
    """Comparable tokens for one memory summary or entry."""
    return frozenset(_TOKEN_PATTERN.findall(text.lower()))


def similarity(left: str, right: str) -> float:
    """Jaccard overlap of two memory texts, 0.0 when either side has no tokens."""
    left_tokens = text_tokens(left)
    right_tokens = text_tokens(right)
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def nearest_entry(text: str, entries: tuple[str, ...] | list[str]) -> tuple[int, float]:
    """Index and score of the entry closest to ``text``; ``(-1, 0.0)`` when none."""
    best_index = -1
    best_score = 0.0
    for index, entry in enumerate(entries):
        score = similarity(text, entry)
        if score > best_score:
            best_index, best_score = index, score
    return best_index, best_score


HERMES_MEMORY_BRIDGE_SCHEMA_VERSION = "hermes_memory_bridge/v1"
PROJECT_MEMORY_RECORD_SCHEMA_VERSION = "project_memory_record/v1"


def read_approved_records(omh_home: str | Path) -> list[dict[str, Any]]:
    """Approved OMH project-memory records, read with stdlib only.

    The bundle has to reach these itself. The `omh` package is not importable
    from the Hermes process -- it lives in its own environment -- so a tool that
    delegated the read would answer "package absent" on the one host that
    matters, which is exactly what shipped before this was vendored.
    """
    directory = Path(omh_home).expanduser() / "memory" / "records"
    records: list[dict[str, Any]] = []
    try:
        candidates = sorted(directory.glob("*.json"))
    except OSError:
        return records
    for path in candidates:
        try:
            if path.is_symlink() or not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("schema_version") != PROJECT_MEMORY_RECORD_SCHEMA_VERSION:
            continue
        if data.get("review_status") != "approved":
            continue
        records.append(data)
    return records


def build_hermes_memory_bridge(omh_home: str | Path, hermes_home: str | Path) -> dict[str, object]:
    """Relate OMH's approved records to what Hermes already remembers.

    The two stores share no identifier, so neither could see the other: OMH
    deduplicated against itself, and Hermes' memory tool rejects only exact
    strings. A fact approved in OMH and restated by hand in MEMORY.md lived in
    both, worded differently, with nothing linking them.

    Read-only. Hermes owns these files; its own `memory` tool is what edits them.
    """
    readings = read_hermes_memory(hermes_home)
    records = read_approved_records(omh_home)
    memory_file = next((reading for reading in readings if reading.label == "MEMORY.md"), None)
    entries = memory_file.entries if memory_file else ()
    already_present: list[dict[str, object]] = []
    promotable: list[dict[str, object]] = []
    matched_entries: set[int] = set()
    for record in records:
        summary = str(record.get("summary", "") or "")
        index, score = nearest_entry(summary, entries)
        row: dict[str, object] = {
            "record_id": str(record.get("record_id", "")),
            "summary_length": len(summary),
            "scope": record.get("scope", {}),
            "nearest_entry_index": index,
            "similarity": round(score, 2),
        }
        if score >= DUPLICATE_SIMILARITY_THRESHOLD:
            matched_entries.add(index)
            already_present.append(row)
            continue
        # `+ 1` is the delimiter Hermes inserts before an appended entry.
        row["fits_headroom"] = bool(memory_file) and len(summary) + 1 <= memory_file.headroom_chars
        promotable.append(row)
    return {
        "schema_version": HERMES_MEMORY_BRIDGE_SCHEMA_VERSION,
        "files": [reading.to_dict() for reading in readings],
        "approved_records": len(records),
        "already_in_hermes": already_present,
        "promotable": promotable,
        "hermes_entries_without_omh_record": _unsourced_entry_rows(entries, matched_entries),
        "duplicate_similarity_threshold": DUPLICATE_SIMILARITY_THRESHOLD,
        "redaction_policy": "metadata_only",
        "next_action": (
            "Promote a record by asking Hermes to add it through its own memory tool; free headroom first "
            "when nothing fits."
        ),
        "claim_boundary": (
            "OMH reads Hermes memory and cannot change it. This comparison is prepared review context only; "
            "it is not a Hermes memory write, execution, review, CI, or merge evidence."
        ),
    }


def _unsourced_entry_rows(entries: tuple[str, ...], matched: set[int]) -> list[dict[str, object]]:
    """Hermes entries no approved OMH record explains, as metadata only."""
    return [
        {
            "entry_index": index,
            "chars": len(entry),
            "sha256": hashlib.sha256(entry.encode("utf-8")).hexdigest(),
        }
        for index, entry in enumerate(entries)
        if index not in matched
    ]
