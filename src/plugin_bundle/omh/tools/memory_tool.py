"""Let Hermes see how its own memory relates to OMH's approved records.

PR #672 built the comparison but left it CLI-only: `omh memory status` carried
it, and none of the nine registered tools did, so the model could not reach it
from chat. That is the half of the problem #672 did not close -- the store had
governance and no outlet.

The tool later grew a second job. OMH's memory blocks split into a tier that
renders every turn and a tier that is listed by label and read on request, and
the second tier only means anything if something can perform the read. That
something is this tool rather than a memory-provider tool schema: Hermes gates
provider tools behind toolset config (``memory_provider_tools_enabled`` in
``agent/memory_manager.py``), so a tier built on one would disappear for any
operator whose toolsets exclude memory, and ``agent/memory_provider.py`` names
tool-schema bloat as the reason only one external provider may run at all.

Two different redaction rules meet here, and they do not merge. OMH block values
are OMH's own content and are returned in full. Hermes memory entries are not
OMH's, are never returned, and appear only as counts, hashes, and similarity
scores -- the same boundary this file has always held.

Read-only with respect to Hermes: nothing here opens a Hermes file for writing.
Hermes owns ``~/.hermes/memories``, and the `memory` tool Hermes exposes to the
model is what edits it.
"""

from __future__ import annotations

import json
import os

from ..degradation import safe_error_type as _safe_error_type
from ..hermes_memory import build_hermes_memory_bridge
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call
from ..memory_blocks import read_memory_block, read_memory_blocks
from ..memory_dreaming import read_dreaming_state
from ..memory_provider import OmhMemoryProvider

MEMORY_ACTIONS = ("status", "blocks", "read", "consolidation")

OMH_MEMORY_SCHEMA = {
    "name": "omh_memory",
    "description": (
        "Read OMH's durable memory and how it relates to Hermes' own. Actions: 'status' "
        "compares Hermes' built-in memory (MEMORY.md, USER.md) against OMH's approved records "
        "and reports what fits under Hermes' character cap; 'blocks' lists OMH memory blocks by "
        "label without their values; 'read' returns one block's value by label; 'consolidation' "
        "reports whether memory consolidation is due and why. OMH block values are returned in "
        "full; Hermes memory entries are never returned, only counted and hashed. OMH cannot "
        "change Hermes memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(MEMORY_ACTIONS),
                "description": "Which view to return. Defaults to 'status'.",
            },
            "label": {
                "type": "string",
                "description": "Block label, required by the 'read' action.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_memory_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_memory", args, kwargs)
    action = str((args or {}).get("action", "") or "status").strip().lower()
    if action not in MEMORY_ACTIONS:
        payload, backend = _unknown_action(action), "bundle_memory"
    elif action == "blocks":
        payload, backend = _blocks(), "bundle_memory"
    elif action == "read":
        payload, backend = _read_block(str((args or {}).get("label", "") or "")), "bundle_memory"
    elif action == "consolidation":
        payload, backend = _consolidation()
    else:
        payload, backend = _memory_bridge()
    payload["plugin_tool"] = "omh_memory"
    payload["action"] = action
    payload["source_backend"] = backend
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _memory_bridge() -> tuple[dict[str, object], str]:
    """Compare the two stores using the bundle's own reader.

    This used to delegate to `omh.memory` and fall back when the import failed.
    The Hermes process cannot import that package -- it lives in its own
    environment -- so the fallback was the *only* path taken on the host this
    tool exists for, and the tool answered "package_absent" every time. Measured
    live before the fix: the model called it, got nothing, and shelled out to
    `omh memory status` instead. The reader is vendored here now, which is what
    every other working bundle surface already does.
    """
    try:
        return (
            build_hermes_memory_bridge(_home("OMH_HOME", "~/.omh"), _home("HERMES_HOME", "~/.hermes")),
            "bundle_memory",
        )
    except Exception as exc:
        # A read failure must stay distinguishable from an empty comparison, or
        # an unreadable memory file reads as a memory with nothing in it.
        return _unavailable(_safe_error_type(type(exc).__name__)), "bundle_memory_error"


def _blocks() -> dict[str, object]:
    """Every block by label, without values -- the listing the tier split needs."""
    blocks = read_memory_blocks(_home("OMH_HOME", "~/.omh"))
    return {
        "schema_version": "omh_memory_block_listing/v1",
        "blocks": [block.to_summary() for block in blocks],
        "block_count": len(blocks),
        "next_action": "Call this tool again with action='read' and a label to read one block.",
        "claim_boundary": (
            "Block metadata is prepared OMH context. It is not evidence that Hermes read a "
            "block, or that any memory was written or changed."
        ),
    }


def _read_block(label: str) -> dict[str, object]:
    """One block's value, or a stated miss.

    A missing block returns ``found: false`` rather than an empty value, so an
    absent block is never mistaken for a block that has nothing to say.
    """
    if not label:
        return {
            "schema_version": "omh_memory_block_read/v1",
            "found": False,
            "reason": "label_required",
            "next_action": "Call action='blocks' to list available labels.",
        }
    for block in read_memory_blocks(_home("OMH_HOME", "~/.omh")):
        if block.label == label:
            return {
                "schema_version": "omh_memory_block_read/v1",
                "found": True,
                "block": block.to_dict(),
                "claim_boundary": (
                    "A block value is prepared OMH context, not execution, review, CI, merge, "
                    "or Hermes internal-memory evidence."
                ),
            }
    return {
        "schema_version": "omh_memory_block_read/v1",
        "found": False,
        "reason": "unknown_label",
        "label": label,
        "next_action": "Call action='blocks' to list available labels.",
    }


def _consolidation() -> tuple[dict[str, object], str]:
    """Whether dreaming is due, and on what evidence.

    This never runs consolidation. OMH cannot: the work needs a model, and the
    only thing that consolidates Hermes memory is Hermes.
    """
    omh_home = _home("OMH_HOME", "~/.omh")
    try:
        provider = OmhMemoryProvider(omh_home)
        provider.initialize("", hermes_home=_home("HERMES_HOME", "~/.hermes"))
        payload = dict(provider.consolidation_due())
        payload["state"] = read_dreaming_state(omh_home)
        return payload, "bundle_memory"
    except Exception as exc:
        return _unavailable(_safe_error_type(type(exc).__name__)), "bundle_memory_error"


def _unknown_action(action: str) -> dict[str, object]:
    return {
        "schema_version": "omh_memory_unknown_action/v1",
        "status": "unavailable",
        "reason": "unknown_action",
        "requested_action": action,
        "supported_actions": list(MEMORY_ACTIONS),
        "next_action": f"Retry with one of: {', '.join(MEMORY_ACTIONS)}.",
        "claim_boundary": "No memory view was produced. This is not evidence about memory state.",
    }


def _home(variable: str, default: str) -> str:
    return os.path.expandvars(os.environ.get(variable, "") or default)


def _unavailable(reason: str) -> dict[str, object]:
    return {
        "schema_version": "omh_memory_bridge_unavailable/v1",
        "status": "unavailable",
        "reason": reason,
        "next_action": "Run `omh memory status` locally, or `omh doctor` if OMH may not be installed.",
        "claim_boundary": (
            "No memory comparison was produced. This is not evidence that Hermes memory is empty, "
            "in sync, or readable."
        ),
    }


__all__ = ["MEMORY_ACTIONS", "OMH_MEMORY_SCHEMA", "omh_memory_handler", "read_memory_block"]
