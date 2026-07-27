from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..install.config_adapter import (
    clear_memory_provider,
    memory_provider_selection,
    read_config,
    set_memory_provider,
    write_config,
)
from ..installer import OmhError
from ..plugin_bundle.omh.memory_blocks import (
    MemoryBlockError,
    blocks_dir,
    build_memory_block,
    delete_memory_block,
    read_memory_blocks,
    write_memory_block,
)
from ..plugin_bundle.omh.memory_dreaming import read_dreaming_state
from ..plugin_bundle.omh.memory_provider import OmhMemoryProvider
from ..plugin_bundle.omh.metadata import MEMORY_PROVIDER_NAME
from ..memory import (
    RejectedDecisionRecallRequest,
    apply_memory_update_batch,
    approve_project_memory_candidate,
    build_handoff_context_pack,
    build_memory_inspection,
    build_project_memory_recall_pack,
    build_project_memory_review,
    build_project_memory_status,
    capture_project_memory_candidate,
    read_memory_snapshot_file,
    reject_project_memory_candidate,
    build_rejected_decision_recall,
)
from .common import _paths, _print_json


def cmd_memory_status(args: argparse.Namespace) -> int:
    try:
        payload = build_project_memory_status(_paths(args))
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_capture(args: argparse.Namespace) -> int:
    try:
        summary = " ".join(args.summary).strip()
        content = sys.stdin.read() if args.stdin else str(args.content or "")
        if not summary:
            raise ValueError("memory capture requires a summary")
        payload = capture_project_memory_candidate(
            _paths(args),
            summary,
            content=content,
            record_type=args.type,
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            source=args.source,
            source_ref=args.source_ref,
            tags=args.tag or [],
            ttl_days=args.ttl_days,
            stale_after_days=args.stale_after_days,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_review(args: argparse.Namespace) -> int:
    try:
        payload = build_project_memory_review(
            _paths(args),
            candidate_id=args.candidate,
            limit=_optional_positive_int(args.limit, "--limit") or 20,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_approve(args: argparse.Namespace) -> int:
    try:
        payload = approve_project_memory_candidate(_paths(args), args.candidate_id, approved_by=args.approved_by)
    except FileNotFoundError as exc:
        raise OmhError(f"memory candidate not found: {args.candidate_id}") from exc
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_reject(args: argparse.Namespace) -> int:
    try:
        payload = reject_project_memory_candidate(
            _paths(args),
            args.candidate_id,
            rejected_by=args.rejected_by,
            reason=args.reason,
        )
    except FileNotFoundError as exc:
        raise OmhError(f"memory candidate not found: {args.candidate_id}") from exc
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_recall(args: argparse.Namespace) -> int:
    try:
        query = " ".join(args.query).strip()
        payload = build_project_memory_recall_pack(
            _paths(args),
            query,
            executor_target=args.executor,
            session_id=args.session_id,
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            limit=_optional_positive_int(args.limit, "--limit") or 6,
            include_stale=args.include_stale,
        )
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_rejected_recall(args: argparse.Namespace) -> int:
    try:
        request = RejectedDecisionRecallRequest(
            " ".join(args.query).strip(),
            args.scope_kind,
            args.scope_ref,
            tuple(args.tag or []),
            args.include_stale,
            args.limit,
        )
        payload = build_rejected_decision_recall(_paths(args), request)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_memory_inspect(args: argparse.Namespace) -> int:
    try:
        inspection = build_memory_inspection(
            _paths(args),
            wrapper_snapshot=_read_optional_json(args.fixture),
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            session_limit=_optional_positive_int(args.session_limit, "--session-limit"),
            summary=args.summary,
            review_item_limit=_optional_positive_int(args.review_item_limit, "--review-item-limit"),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(inspection)
    return 0


def cmd_memory_pack(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        inspection = None
        wrapper_snapshot = _read_optional_json(args.fixture)
        if wrapper_snapshot is not None:
            inspection = build_memory_inspection(
                paths,
                wrapper_snapshot=wrapper_snapshot,
                scope_kind=args.scope_kind,
                scope_ref=args.scope_ref,
                session_limit=_optional_positive_int(args.session_limit, "--session-limit"),
                review_item_limit=_optional_positive_int(args.review_item_limit, "--review-item-limit"),
            )
        pack = build_handoff_context_pack(
            paths,
            inspection=inspection,
            executor_target=args.executor,
            session_id=args.session_id,
            scope_kind=args.scope_kind,
            scope_ref=args.scope_ref,
            session_limit=_optional_positive_int(args.session_limit, "--session-limit"),
            context_limit=_optional_positive_int(args.context_limit, "--context-limit") or 12,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(pack)
    return 0


def cmd_memory_apply(args: argparse.Namespace) -> int:
    try:
        batch = _read_required_json(args.batch)
        result = apply_memory_update_batch(_paths(args), batch, dry_run=args.dry_run)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(result)
    return 0


def cmd_memory_blocks(args: argparse.Namespace) -> int:
    paths = _paths(args)
    blocks = read_memory_blocks(paths.omh_home, tier=args.tier)
    _print_json(
        {
            "schema_version": "omh_memory_block_listing/v1",
            "blocks": [block.to_summary() for block in blocks],
            "block_count": len(blocks),
            "store_dir": str(blocks_dir(paths.omh_home)),
            "claim_boundary": (
                "Block listings are prepared OMH context; they are not evidence that Hermes read "
                "a block or that any memory was written."
            ),
        }
    )
    return 0


def cmd_memory_block_set(args: argparse.Namespace) -> int:
    try:
        value = sys.stdin.read() if args.stdin else str(args.value or "")
        block = build_memory_block(
            args.label,
            value,
            description=args.description,
            limit=args.limit,
            tier=args.tier,
        )
        path = write_memory_block(_paths(args).omh_home, block)
    except MemoryBlockError as exc:
        raise OmhError(str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_memory_block_write/v1", "written": True, "path": str(path), "block": block.to_summary()})
    return 0


def cmd_memory_block_remove(args: argparse.Namespace) -> int:
    try:
        removed = delete_memory_block(_paths(args).omh_home, args.label, args.tier)
    except MemoryBlockError as exc:
        raise OmhError(str(exc)) from exc
    _print_json({"schema_version": "omh_memory_block_remove/v1", "removed": removed, "label": args.label, "tier": args.tier})
    return 0


def cmd_memory_dream(args: argparse.Namespace) -> int:
    """Report whether consolidation is due. Never consolidates: that needs a model."""
    paths = _paths(args)
    provider = OmhMemoryProvider(paths.omh_home)
    provider.initialize("", hermes_home=str(paths.hermes_home))
    payload = dict(provider.consolidation_due()) if args.evaluate else {}
    payload["state"] = read_dreaming_state(paths.omh_home)
    payload["evaluated"] = bool(args.evaluate)
    _print_json(payload)
    return 0


def cmd_memory_provider(args: argparse.Namespace) -> int:
    """Show, take, or hand back Hermes' single external memory-provider slot."""
    paths = _paths(args)
    path = paths.hermes_config_path
    text = read_config(path)
    change = None
    if args.enable:
        change = set_memory_provider(text, MEMORY_PROVIDER_NAME)
    elif args.disable:
        change = clear_memory_provider(text, MEMORY_PROVIDER_NAME)
    if change is not None and change.changed and not args.dry_run:
        try:
            write_config(path, change.text)
        except OSError as exc:
            raise OmhError(str(exc)) from exc
    selection = memory_provider_selection(change.text if change is not None else text)
    _print_json(
        {
            "schema_version": "omh_memory_provider_status/v1",
            "provider": selection,
            "is_omh": selection == MEMORY_PROVIDER_NAME,
            "config_path": str(path),
            "config_exists": path.is_file(),
            "changed": bool(change.changed) if change is not None else False,
            "reason": change.message if change is not None else "status only",
            "dry_run": bool(args.dry_run),
            "next_action": (
                "Restart Hermes for a provider change to take effect; run `omh setup` first if the "
                "bundle is not installed."
            ),
            "claim_boundary": (
                "This reports and edits Hermes' config selection only. It is not evidence that "
                "Hermes loaded the provider, ran a hook, or changed any memory."
            ),
        }
    )
    return 0


def _read_optional_json(path: str | None) -> dict[str, object] | None:
    if not path:
        return None
    return read_memory_snapshot_file(path)


def _read_required_json(path: str) -> dict[str, object]:
    raw = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("memory JSON input must be an object")
    return data


def _optional_positive_int(value: int | None, flag: str) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise ValueError(f"{flag} must be at least 1")
    return value


def _add_memory_commands(sub) -> None:
    from .memory_parser import add_memory_commands

    add_memory_commands(sub)
