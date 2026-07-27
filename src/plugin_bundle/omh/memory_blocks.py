"""Memory blocks: the tier Hermes does not have.

Hermes keeps one flat, character-capped entry list per file (``MEMORY.md``,
``USER.md``). There is no label, no per-topic budget, and no way to say "this
belongs in context every turn but that only when asked" -- so everything
competes for the same 2200 characters and the file fills up.

Letta's answer, which this file borrows, is the memory block: a labelled record
with its own character limit, rendered into the prompt by string templating with
its fill level shown alongside the value. Blocks live in two tiers, after
MemFS: ``system`` renders every turn, ``reference`` is listed by label and read
only when something asks for it. The split is what keeps an always-on budget
small while the store itself stays unbounded.

Everything here is deterministic file work -- no model call decides what a block
says, only what a prepared handoff proposes. Stdlib only, and vendored in the
bundle rather than in ``workflows/`` because this module is imported inside the
Hermes process, where the ``omh`` package does not exist.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MEMORY_BLOCK_SCHEMA_VERSION = "omh_memory_block/v1"

SYSTEM_TIER = "system"
REFERENCE_TIER = "reference"
BLOCK_TIERS = (SYSTEM_TIER, REFERENCE_TIER)

# Per-block ceiling. Letta's documented persona example uses 5000 and its
# framework defaults are larger still, but a block here has to share a Hermes
# turn with the rest of OMH's context, so the default is deliberately smaller
# than anything it renders beside.
DEFAULT_BLOCK_LIMIT_CHARS = 2000

# Ceiling for one rendered system-tier pack. A per-block limit alone cannot
# bound the render: ten blocks under their own limits still overflow a turn.
DEFAULT_SYSTEM_RENDER_BUDGET_CHARS = 6000

# Labels name files, so they are constrained to what is safe as a filename and
# stable as an identifier.
_LABEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class MemoryBlockError(ValueError):
    """A block was rejected before anything was written."""


@dataclass(frozen=True)
class MemoryBlock:
    """One labelled, budgeted piece of durable context."""

    label: str
    description: str
    value: str
    limit: int
    tier: str

    @property
    def chars(self) -> int:
        return len(self.value)

    @property
    def over_limit(self) -> bool:
        return self.chars > self.limit

    @property
    def headroom_chars(self) -> int:
        return max(0, self.limit - self.chars)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MEMORY_BLOCK_SCHEMA_VERSION,
            "label": self.label,
            "description": self.description,
            "value": self.value,
            "limit": self.limit,
            "tier": self.tier,
        }

    def to_summary(self) -> dict[str, object]:
        """Metadata without the value, for listings and status payloads."""
        return {
            "label": self.label,
            "description": self.description,
            "tier": self.tier,
            "chars": self.chars,
            "limit": self.limit,
            "headroom_chars": self.headroom_chars,
            "over_limit": self.over_limit,
        }


def normalize_label(value: str) -> str:
    """A label usable as both an identifier and a filename."""
    label = str(value or "").strip().lower()
    if not _LABEL.match(label):
        raise MemoryBlockError(
            "block label must be 1-63 chars of lowercase letters, digits, '-' or '_', "
            f"starting alphanumeric; got {label!r}"
        )
    return label


def normalize_tier(value: str) -> str:
    tier = str(value or "").strip().lower()
    if tier not in BLOCK_TIERS:
        raise MemoryBlockError(f"block tier must be one of {BLOCK_TIERS}; got {tier!r}")
    return tier


def blocks_dir(omh_home: str | Path) -> Path:
    return Path(omh_home).expanduser() / "memory" / "blocks"


def block_path(omh_home: str | Path, label: str, tier: str) -> Path:
    return blocks_dir(omh_home) / normalize_tier(tier) / f"{normalize_label(label)}.json"


def build_memory_block(
    label: str,
    value: str,
    *,
    description: str = "",
    limit: int = DEFAULT_BLOCK_LIMIT_CHARS,
    tier: str = SYSTEM_TIER,
) -> MemoryBlock:
    """Validate one block. Raises rather than truncating.

    Silent truncation would make the store disagree with what a caller believes
    it wrote, and the disagreement would only surface as a missing sentence in a
    later prompt. An over-limit block is a caller error, so it is one here.
    """
    normalized_label = normalize_label(label)
    normalized_tier = normalize_tier(tier)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise MemoryBlockError(f"block limit must be a positive integer; got {limit!r}")
    text = str(value or "")
    if len(text) > limit:
        raise MemoryBlockError(
            f"block {normalized_label!r} is {len(text)} chars against a {limit}-char limit"
        )
    return MemoryBlock(normalized_label, str(description or ""), text, limit, normalized_tier)


def write_memory_block(omh_home: str | Path, block: MemoryBlock) -> Path:
    """Persist one block, creating its tier directory when needed."""
    path = block_path(omh_home, block.label, block.tier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(block.to_dict(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def read_memory_block(path: str | Path) -> MemoryBlock | None:
    """One block from disk, or None when the file is absent or unusable.

    Never raises: an unreadable block must degrade to "not present" rather than
    take down the turn that was rendering it.
    """
    candidate = Path(path)
    try:
        if candidate.is_symlink() or not candidate.is_file():
            return None
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != MEMORY_BLOCK_SCHEMA_VERSION:
        return None
    try:
        return build_memory_block(
            str(data.get("label", "")),
            str(data.get("value", "")),
            description=str(data.get("description", "")),
            limit=_int_or(data.get("limit"), DEFAULT_BLOCK_LIMIT_CHARS),
            tier=str(data.get("tier", "")),
        )
    except MemoryBlockError:
        return None


def read_memory_blocks(omh_home: str | Path, *, tier: str | None = None) -> tuple[MemoryBlock, ...]:
    """Every readable block, label-ordered so a render is reproducible."""
    tiers = (normalize_tier(tier),) if tier is not None else BLOCK_TIERS
    found: list[MemoryBlock] = []
    for tier_name in tiers:
        directory = blocks_dir(omh_home) / tier_name
        try:
            candidates = sorted(directory.glob("*.json"))
        except OSError:
            continue
        for candidate in candidates:
            block = read_memory_block(candidate)
            if block is not None and block.tier == tier_name:
                found.append(block)
    return tuple(sorted(found, key=lambda item: item.label))


def delete_memory_block(omh_home: str | Path, label: str, tier: str) -> bool:
    """Remove one block. False when it was not there to begin with."""
    path = block_path(omh_home, label, tier)
    try:
        path.unlink()
    except OSError:
        return False
    return True


def render_memory_blocks(
    blocks: tuple[MemoryBlock, ...] | list[MemoryBlock],
    *,
    budget_chars: int = DEFAULT_SYSTEM_RENDER_BUDGET_CHARS,
) -> str:
    """Blocks as prompt text, with each block's fill level beside its value.

    The shape follows Letta's documented rendering: an XML-ish wrapper, one
    element per label, and a metadata line carrying chars_current/chars_limit so
    the model can see how much room a block has before it proposes an edit.
    Pure templating -- no model call is involved in producing this.

    Blocks are emitted in label order until the budget is spent; the first block
    that would exceed it, and every block after, is dropped rather than clipped,
    and the omission is stated in the output. A half-sentence would read as
    something the store actually holds.
    """
    if not blocks:
        return ""
    lines = ["<memory_blocks>"]
    used = 0
    omitted: list[str] = []
    for block in blocks:
        element = _render_block(block)
        if omitted or used + len(element) > max(budget_chars, 0):
            omitted.append(block.label)
            continue
        used += len(element)
        lines.append(element)
    if omitted:
        lines.append(
            f"  <omitted reason=\"render_budget_exhausted\" budget_chars=\"{budget_chars}\">"
            f"{', '.join(omitted)}</omitted>"
        )
    lines.append("</memory_blocks>")
    return "\n".join(lines)


def render_block_index(blocks: tuple[MemoryBlock, ...] | list[MemoryBlock]) -> str:
    """Reference-tier blocks as a label listing, without their values.

    This is the half of the tier split that makes it worth having: the model
    learns a block exists and what it is for, and pays its characters only when
    it asks for the block by label.
    """
    if not blocks:
        return ""
    lines = ["<memory_block_index>"]
    for block in blocks:
        lines.append(
            f'  <block label="{block.label}" chars="{block.chars}" limit="{block.limit}">'
            f"{block.description}</block>"
        )
    lines.append("</memory_block_index>")
    return "\n".join(lines)


def _render_block(block: MemoryBlock) -> str:
    return (
        f"  <{block.label}>\n"
        f"    <description>{block.description}</description>\n"
        f"    <metadata>chars_current={block.chars} chars_limit={block.limit}</metadata>\n"
        f"    <value>{block.value}</value>\n"
        f"  </{block.label}>"
    )


def _int_or(value: Any, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value
