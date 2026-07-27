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

The cap itself is read rather than assumed. Hermes takes it from
``memory.memory_char_limit`` / ``memory.user_char_limit`` in ``config.yaml`` and
only falls back to 2200/1375, so hardcoding those two numbers reported a raised
limit as exhausted headroom on any host that had changed them. Each reading
carries the cap it was measured against and whether that cap was observed in
config or assumed.

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

# The caps Hermes falls back to, not the caps it necessarily enforces. Hermes
# builds its memory tool with ``mem_config.get("memory_char_limit", 2200)`` and
# ``mem_config.get("user_char_limit", 1375)`` (``agent/agent_init.py``), so a
# user who raises either limit in ``config.yaml`` keeps writing while OMH -- which
# used to hardcode these two numbers -- reported the file over cap and its
# headroom exhausted. Read the config; treat these as the fallback they are.
DEFAULT_MEMORY_FILE_CAP_CHARS = 2200
DEFAULT_USER_FILE_CAP_CHARS = 1375

# Memory file, the ``memory`` config key that overrides its cap, and the default.
HERMES_MEMORY_FILES = (
    ("MEMORY.md", "memory_char_limit", DEFAULT_MEMORY_FILE_CAP_CHARS),
    ("USER.md", "user_char_limit", DEFAULT_USER_FILE_CAP_CHARS),
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
    cap_source: str = "default"

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
            "cap_source": self.cap_source,
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


def resolve_memory_caps(hermes_home: str | Path) -> tuple[tuple[str, int, str], ...]:
    """Per-file ``(label, cap, cap_source)`` for one Hermes home.

    ``cap_source`` is ``"config"`` when ``config.yaml`` overrode the cap and
    ``"default"`` otherwise, so a reader can tell an observed limit from an
    assumed one instead of trusting every cap equally.

    A key that is absent, unparseable, or not a positive integer falls back to
    the default: OMH reports on Hermes memory and must not turn a malformed
    config into a headroom figure that looks measured.
    """
    config_text = _read_hermes_config(hermes_home)
    resolved: list[tuple[str, int, str]] = []
    for label, config_key, default_cap in HERMES_MEMORY_FILES:
        configured = _positive_int(_config_section_scalar(config_text, "memory", config_key))
        if configured is None:
            resolved.append((label, default_cap, "default"))
        else:
            resolved.append((label, configured, "config"))
    return tuple(resolved)


def read_hermes_memory_file(
    path: Path,
    *,
    label: str,
    cap: int,
    now: float | None = None,
    cap_source: str = "default",
) -> HermesMemoryFile:
    """Read one memory file. Never raises: an unreadable file reports its error."""
    moment = time.time() if now is None else now
    if not path.exists():
        return HermesMemoryFile(label, path, False, 0, cap, (), 0.0, cap_source=cap_source)
    try:
        text = path.read_text(encoding="utf-8")
        age_days = max(0.0, (moment - path.stat().st_mtime) / 86400.0)
    except (OSError, UnicodeDecodeError) as error:
        return HermesMemoryFile(label, path, True, 0, cap, (), 0.0, error=str(error), cap_source=cap_source)
    entries = parse_memory_entries(text)
    return HermesMemoryFile(
        label,
        path,
        True,
        memory_char_count(entries),
        cap,
        entries,
        age_days,
        cap_source=cap_source,
    )


def read_hermes_memory(
    hermes_home: str | Path,
    *,
    now: float | None = None,
) -> tuple[HermesMemoryFile, ...]:
    """Read every Hermes memory file under one Hermes home, at its configured cap."""
    memories_dir = Path(hermes_home).expanduser() / "memories"
    return tuple(
        read_hermes_memory_file(memories_dir / label, label=label, cap=cap, now=now, cap_source=cap_source)
        for label, cap, cap_source in resolve_memory_caps(hermes_home)
    )


def _read_hermes_config(hermes_home: str | Path) -> str:
    """Hermes' ``config.yaml`` as text, or empty when it cannot be read."""
    path = Path(hermes_home).expanduser() / "config.yaml"
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _positive_int(value: str) -> int | None:
    """A positive integer scalar, or None when the text is not one."""
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _config_section_scalar(config_text: str, section: str, key: str) -> str:
    """One scalar under one top-level section, in dotted or nested form.

    Vendored rather than imported: this module is loaded inside the Hermes
    process, where the `omh` package is absent, so it cannot reach OMH's own
    reader in `workflows/hermes_retained_context_probes.py`. Same two forms,
    same comment and quote handling.
    """
    dotted = f"{section}.{key}:"
    section_header = f"{section}:"
    in_section = False
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(dotted):
            return _clean_config_scalar(stripped[len(dotted) :])
        if not line.startswith(" "):
            in_section = stripped == section_header
            continue
        if in_section and line.startswith("  ") and not line.startswith("    "):
            prefix = f"{key}:"
            if stripped.startswith(prefix):
                return _clean_config_scalar(stripped[len(prefix) :])
    return ""


def _clean_config_scalar(value: str) -> str:
    stripped = _strip_unquoted_yaml_comment(value).strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _strip_unquoted_yaml_comment(value: str) -> str:
    in_single_quote = False
    in_double_quote = False
    for index, character in enumerate(value):
        if character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            continue
        if character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            continue
        if character == "#" and not in_single_quote and not in_double_quote and _starts_yaml_comment(value, index):
            return value[:index]
    return value


def _starts_yaml_comment(value: str, index: int) -> bool:
    return index == 0 or value[index - 1].isspace()


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
