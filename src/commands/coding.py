from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from ..coding_delegation import CODING_EXECUTOR_TARGETS, build_coding_delegation_payload, coding_delegation_record_payload
from ..coding.executor_capability_snapshots import (
    ExecutorCapabilitySnapshotError,
    build_executor_capability_snapshot,
    read_executor_capability_snapshot,
    validate_executor_capability_snapshot,
    write_executor_capability_snapshot,
)
from ..executor_readiness import EXECUTOR_READINESS_PROFILES, probe_executor_readiness
from ..hermes_planning import (
    build_plan_handoff_context_pack,
    build_plan_handoff_message,
    read_hermes_plan_artifact,
)
from ..ingress import CHAT_SOURCES, extract_message_text, extract_source_metadata
from ..installer import OmhError
from ..local_store import read_json_object
from ..memory import memory_recall_pack_for_handoff, read_handoff_context_pack_file
from ..coding.product_family_templates import PRODUCT_FAMILIES, product_family_template
from ..coding.product_quality_harnesses import product_quality_harness
from ..coding.project_governance import discover_project_governance
from ..routing.intent import META_OR_FEEDBACK_INTENTS, classify_workflow_intent
from ..routing.localization import normalized_phrase, routing_tokens
from ..runtime.artifacts import append_journal_observation, create_prepared_coding_delegation_run, write_coding_delegation
from ..wrapper.lifecycle import (
    CodingLifecycleError,
    record_codex_dispatch,
    record_codex_result,
    record_codex_verification,
    report_codex_delegation_lifecycle,
    start_codex_delegation_lifecycle,
)
from .common import _chat_input_and_metadata, _explicit_source_metadata, _paths, _print_json, _resolved_executor
from .dynamic_workflow import _add_dynamic_workflow_command, cmd_coding_dynamic_workflow


_CAPABILITY_SNAPSHOT_CLAIM_BOUNDARY = (
    "Executor capability snapshots are metadata-only host observations. They are not execution evidence, "
    "verification, review, CI, merge-readiness, or merge evidence."
)
_CAPABILITY_SNAPSHOT_EXECUTOR_TARGETS = tuple(target for target in CODING_EXECUTOR_TARGETS if target != "choose")


def cmd_coding_delegate(args: argparse.Namespace) -> int:
    try:
        paths = _paths(args)
        source_metadata: dict[str, str] = {}
        plan_artifact: dict[str, object] | None = None
        context_pack = _context_pack(args)
        executor_target = _resolved_executor_for_delegate(args)
        if args.from_plan:
            if args.event_json or args.stdin or args.message:
                raise ValueError("coding delegate --from-plan cannot be combined with --stdin, --event-json, or message arguments")
            artifact = read_hermes_plan_artifact(args.from_plan)
            if artifact.get("schema_version") != "hermes_plan/v1":
                raise ValueError("coding delegate --from-plan requires a hermes_plan/v1 artifact")
            plan_status = str(artifact.get("status", ""))
            if plan_status != "accepted" and not args.allow_draft_plan:
                raise ValueError("coding delegate --from-plan requires an accepted plan; use hermes plan-accept or --allow-draft-plan")
            message = build_plan_handoff_message(artifact)
            source_metadata.update(_plan_source_metadata(artifact))
            plan_artifact = _coding_plan_artifact(artifact)
            if context_pack is None:
                context_pack = build_plan_handoff_context_pack(artifact, executor_target=executor_target)
        elif args.event_json:
            raw = (
                sys.stdin.read()
                if args.event_json == "-"
                else Path(args.event_json).expanduser().read_text(encoding="utf-8")
            )
            event = json.loads(raw)
            message = extract_message_text(event)
            source_metadata = extract_source_metadata(event)
        elif args.stdin:
            message = sys.stdin.read().strip()
        else:
            message = " ".join(args.message).strip()
        source_metadata.update(_explicit_source_metadata(args))
        memory_recall_pack = memory_recall_pack_for_handoff(paths, message, executor_target=executor_target)
        payload = build_coding_delegation_payload(
            message,
            source=args.source,
            limit=args.limit,
            include_message=args.include_message or args.include_message_full,
            message_context_mode="full" if args.include_message_full else "bounded",
            source_metadata=source_metadata,
            executor_target=executor_target,
            context_pack=context_pack,
            memory_recall_pack=memory_recall_pack,
            plan_artifact=plan_artifact,
            capability_snapshot_directory=paths.omh_home / "coding" / "executor-capability-snapshots",
            project_root=args.project_root or None,
            governance_default=args.governance_default,
            product_family=args.product_family or None,
        )
        if plan_artifact:
            _apply_plan_handoff_source(payload)
        if payload.get("delegation_policy") or _payload_choice_required(payload):
            from ..executor_readiness import executor_choice_context

            payload["executor_choice_context"] = executor_choice_context(paths)
        runtime_skip_reason = ""
        if args.record:
            runtime_skip_reason = _coding_delegate_record_readiness_skip_reason(
                message,
                force_record=bool(args.force_record or args.from_plan),
            )
            if not runtime_skip_reason:
                runtime_skip_reason = _coding_delegate_runtime_skip_reason(payload)
            if not runtime_skip_reason:
                runtime_skip_reason = _coding_delegate_record_readiness_skip_reason(
                    message,
                    force_record=bool(args.force_record or args.from_plan),
                    require_dispatchable_requirements=True,
                )
        if runtime_skip_reason:
            if runtime_skip_reason == "requirements_or_dispatch_intent_missing":
                payload["status"] = "blocked_requirements_missing"
                payload["recorded"] = False
            payload["runtime"] = {
                "recorded": False,
                "reason": runtime_skip_reason,
                "run_created": False,
                "record_status": _coding_delegate_record_status(runtime_skip_reason),
                "record_notice": _coding_delegate_record_notice(runtime_skip_reason),
                "next_action": _coding_delegate_record_next_action(runtime_skip_reason),
            }
        elif args.record:
            delegation = payload["delegation"]
            if not isinstance(delegation, dict):
                raise OmhError("coding delegation payload is missing delegation")
            run = create_prepared_coding_delegation_run(
                paths,
                {
                    "skill": str(delegation["recommended_workflow"]),
                    "harness": str(delegation["recommended_harness"]),
                    "trigger": f"coding:{args.source}:{delegation['action']}",
                    "privacy": "metadata_only",
                    "inputs_summary": _inputs_summary(args.source, message, plan_artifact=plan_artifact),
                    "outputs_summary": f"prepared {delegation['action']} for {delegation['recommended_workflow']}",
                    "verification_summary": "prepared_not_observed; executor work is not observed by omh",
                },
            )
            record = write_coding_delegation(
                paths.runtime_runs_dir / run["run_id"],
                coding_delegation_record_payload(payload, message, source_metadata=source_metadata),
            )
            if plan_artifact:
                append_journal_observation(
                    paths,
                    {
                        "target_type": "run",
                        "target_id": run["run_id"],
                        "run_id": run["run_id"],
                        "workflow": str(delegation["recommended_workflow"]),
                        "harness": str(delegation["recommended_harness"]),
                        "phase": "prepared",
                        "event": "prepared_handoff_created",
                        "status": "observed",
                        "source": "coding_delegate_from_plan",
                        "plan_artifact": plan_artifact.get("path", ""),
                        "plan_status": plan_artifact.get("status", ""),
                        "summary": "Prepared coding handoff from accepted Hermes plan artifact.",
                    },
                )
            payload["runtime"] = {"run": run, "coding_delegation": record}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def _coding_delegate_runtime_skip_reason(payload: dict[str, object]) -> str:
    selection = payload.get("executor_selection")
    if isinstance(selection, dict) and selection.get("choice_required") is True:
        return "executor_choice_required"
    if payload.get("work_owner_mode") == "prompt_only_handoff":
        return "prompt_only_handoff_is_wrapper_session_only"
    if payload.get("work_owner_mode") == "runtime_handoff":
        return "runtime_handoff_is_wrapper_session_only"
    if payload.get("work_owner_mode") == "retained_hermes":
        return "retained_hermes_has_no_executor_handoff"
    if payload.get("selected_executor_profile") != "codex" or not isinstance(payload.get("executor_handoff"), dict):
        return "codex_executor_handoff_required_for_runtime_record"
    return ""


def _resolved_executor_for_delegate(args: argparse.Namespace) -> str:
    if getattr(args, "executor", None):
        return str(args.executor)
    if getattr(args, "from_plan", None):
        return "codex"
    return _resolved_executor(args, default="generic")


def _plan_source_metadata(artifact: dict[str, object]) -> dict[str, str]:
    return {
        "plan_artifact_path": str(artifact.get("path", "")),
        "plan_artifact_sha256": str(artifact.get("sha256", "")),
        "plan_artifact_status": str(artifact.get("status", "")),
        "plan_task_sha256": str(artifact.get("task_statement_sha256", "")),
        "plan_task_length": str(artifact.get("task_statement_length", 0)),
    }


def _coding_plan_artifact(artifact: dict[str, object]) -> dict[str, object]:
    return {
        "path": str(artifact.get("path", "")),
        "kind": "hermes_plan",
        "schema_version": str(artifact.get("schema_version", "hermes_plan/v1")),
        "status": str(artifact.get("status", "")),
        "sha256": str(artifact.get("sha256", "")),
        "task_statement_sha256": str(artifact.get("task_statement_sha256", "")),
        "task_statement_length": int(artifact.get("task_statement_length", 0) or 0),
    }


def _apply_plan_handoff_source(payload: dict[str, object]) -> None:
    for key, brief_key in (
        ("executor_handoff", "execution_brief"),
        ("runtime_handoff", "runtime_brief"),
        ("prompt_handoff", ""),
    ):
        handoff = payload.get(key)
        if not isinstance(handoff, dict):
            continue
        if brief_key and isinstance(handoff.get(brief_key), dict):
            handoff[brief_key]["task_source"] = "accepted_plan_artifact"
        scope = handoff.get("scope")
        if isinstance(scope, list):
            scope.insert(0, "Use the accepted Hermes plan artifact as the executor request.")
        handoff["dispatch_contract"] = str(handoff.get("dispatch_contract", "")) + "; plan_artifact_context_required"


def _inputs_summary(source: str, message: str, *, plan_artifact: dict[str, object] | None) -> str:
    if plan_artifact:
        return (
            f"{source} coding delegation from accepted plan artifact; "
            f"plan_sha256={plan_artifact.get('sha256', '')}; message_length={len(message)}"
        )
    return f"{source} coding delegation request; message_length={len(message)}"


def _coding_delegate_record_readiness_skip_reason(
    message: str,
    *,
    force_record: bool = False,
    require_dispatchable_requirements: bool = False,
) -> str:
    intent = classify_workflow_intent(message)
    if intent.missing_requirements_cues:
        return "requirements_or_dispatch_intent_missing"
    if intent.intent_class in META_OR_FEEDBACK_INTENTS and not intent.explicit_execution:
        return "requirements_or_dispatch_intent_missing"
    if require_dispatchable_requirements and (
        not _coding_delegate_dispatch_intent_present(intent, force_record=force_record)
        or not _coding_delegate_requirements_present(message)
    ):
        return "requirements_or_dispatch_intent_missing"
    return ""


def _coding_delegate_dispatch_intent_present(intent: object, *, force_record: bool = False) -> bool:
    return bool(force_record or getattr(intent, "explicit_execution", False))


_VAGUE_RECORD_TOKENS = frozenset(
    {
        "agent",
        "code",
        "codex",
        "coding",
        "cleanup",
        "delegate",
        "fix",
        "handoff",
        "implement",
        "implementation",
        "improve",
        "maybe",
        "pr",
        "ready",
        "refactor",
        "request",
        "review",
        "risky",
        "task",
        "update",
    }
)


def _coding_delegate_requirements_present(message: str) -> bool:
    normalized = normalized_phrase(message)
    tokens = set(routing_tokens(message, stopwords=set()))
    concrete_tokens = {token for token in tokens if len(token) > 1 and token not in _VAGUE_RECORD_TOKENS}
    if len(concrete_tokens) >= 2:
        return True
    if re.search(r"(?:src|tests|docs|\.github)/|[A-Za-z_][A-Za-z0-9_./-]*\.[A-Za-z0-9]+", message):
        return True
    concrete_phrases = (
        "api",
        "module",
        "repo",
        "auth",
        "router",
        "runtime",
        "workflow",
        "기능",
        "이슈",
        "변경",
        "버그",
        "라우팅",
        "워크플로",
    )
    return any(phrase in normalized for phrase in concrete_phrases) and len(tokens) >= 3


def _coding_delegate_record_status(reason: str) -> str:
    if reason == "requirements_or_dispatch_intent_missing":
        return "blocked_requirements_missing"
    if reason == "executor_choice_required":
        return "record_skipped_until_executor_selected"
    return "record_skipped"


def _coding_delegate_record_notice(reason: str) -> str:
    if reason == "requirements_or_dispatch_intent_missing":
        return "Coding delegate record blocked until concrete requirements and explicit dispatch intent are present; no run was created."
    if reason == "executor_choice_required":
        return "Runtime record skipped until executor selected; no run was created."
    if reason == "prompt_only_handoff_is_wrapper_session_only":
        return "Runtime record skipped because prompt-only handoffs stay in wrapper session state."
    if reason == "runtime_handoff_is_wrapper_session_only":
        return "Runtime record skipped because runtime handoffs stay prepared until runtime evidence is observed."
    if reason == "retained_hermes_has_no_executor_handoff":
        return "Runtime record skipped because retained Hermes guidance has no executor handoff."
    return "Runtime record skipped because a Codex executor handoff is required before creating a run."


def _coding_delegate_record_next_action(reason: str) -> str:
    if reason == "requirements_or_dispatch_intent_missing":
        return "ask_requirements_or_prepare_plan"
    if reason == "executor_choice_required":
        return "select_executor_then_record"
    if reason == "prompt_only_handoff_is_wrapper_session_only":
        return "copy_prompt_or_select_run_backed_executor"
    if reason == "runtime_handoff_is_wrapper_session_only":
        return "observe_runtime_start_before_recording_execution"
    if reason == "retained_hermes_has_no_executor_handoff":
        return "continue_in_hermes_or_select_executor"
    return "select_codex_executor_for_run_backed_record"


def _context_pack(args: argparse.Namespace) -> dict[str, object] | None:
    path = getattr(args, "context_pack", None)
    if not path:
        return None
    return read_handoff_context_pack_file(path)


def cmd_coding_lifecycle_start(args: argparse.Namespace) -> int:
    if not args.record:
        raise OmhError("coding lifecycle start requires --record")
    if args.executor != "codex":
        raise OmhError("coding lifecycle is Codex-only for run-backed tracking; use coding delegate for prompt-only or runtime handoffs")
    try:
        event_or_message, source_metadata = _chat_input_and_metadata(args)
        message = extract_message_text(event_or_message)
        payload = start_codex_delegation_lifecycle(
            _paths(args),
            message,
            source=args.source,
            source_metadata=source_metadata,
            limit=args.limit,
            include_message=args.include_message,
            context_pack=_context_pack(args),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(payload)
    return 0


def cmd_coding_lifecycle_dispatch(args: argparse.Namespace) -> int:
    try:
        _print_json(record_codex_dispatch(_paths(args), args.run_id))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    except CodingLifecycleError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_lifecycle_result(args: argparse.Namespace) -> int:
    participants = [item.strip() for item in (args.participants or "").split(",") if item.strip()]
    try:
        _print_json(
            record_codex_result(
                _paths(args),
                args.run_id,
                result=args.result,
                participants=participants or ["codex"],
                evidence_refs=args.evidence_ref or [],
            )
        )
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    except CodingLifecycleError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_lifecycle_verify(args: argparse.Namespace) -> int:
    try:
        _print_json(
            record_codex_verification(
                _paths(args),
                args.run_id,
                completion_status=args.completion_status,
                gaps=args.gap or [],
            )
        )
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    except CodingLifecycleError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_lifecycle_report(args: argparse.Namespace) -> int:
    try:
        _print_json(report_codex_delegation_lifecycle(_paths(args), args.run_id))
    except FileNotFoundError as exc:
        raise OmhError(f"runtime run not found: {args.run_id}") from exc
    return 0


def cmd_coding_executor_readiness(args: argparse.Namespace) -> int:
    try:
        _print_json(
            probe_executor_readiness(
                _paths(args),
                args.executor,
                force=bool(args.force),
                dry_run=bool(args.dry_run),
            )
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_capability_snapshot_prepare(args: argparse.Namespace) -> int:
    try:
        _print_json(_build_capability_snapshot(args))
    except (ExecutorCapabilitySnapshotError, OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_capability_snapshot_record(args: argparse.Namespace) -> int:
    try:
        snapshot = _build_capability_snapshot(args)
        path = _capability_snapshot_path(args)
        persisted = write_executor_capability_snapshot(path, snapshot)
    except (ExecutorCapabilitySnapshotError, OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "snapshot": persisted,
            "snapshot_path": str(path),
            "claim_boundary": _CAPABILITY_SNAPSHOT_CLAIM_BOUNDARY,
        }
    )
    return 0


def cmd_coding_capability_snapshot_inspect(args: argparse.Namespace) -> int:
    try:
        path = _capability_snapshot_path(args)
        snapshot = read_executor_capability_snapshot(path)
        if snapshot is None:
            raise ValueError(f"executor capability snapshot not found: {path}")
        if snapshot.get("executor") != args.executor:
            raise ValueError(f"executor capability snapshot executor does not match --executor {args.executor}")
    except (ExecutorCapabilitySnapshotError, OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "snapshot": snapshot,
            "snapshot_path": str(path),
            "claim_boundary": _CAPABILITY_SNAPSHOT_CLAIM_BOUNDARY,
        }
    )
    return 0


def cmd_coding_capability_snapshot_validate(args: argparse.Namespace) -> int:
    try:
        path = _capability_snapshot_path(args)
        snapshot = read_json_object(path)
        if snapshot is None:
            raise ValueError(f"executor capability snapshot not found: {path}")
        errors = validate_executor_capability_snapshot(snapshot)
        if snapshot.get("executor") != args.executor:
            errors.append(f"snapshot executor does not match --executor {args.executor}")
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_json(
        {
            "valid": not errors,
            "errors": errors,
            "snapshot_path": str(path),
            "claim_boundary": _CAPABILITY_SNAPSHOT_CLAIM_BOUNDARY,
        }
    )
    return 0 if not errors else 1


def _build_capability_snapshot(args: argparse.Namespace) -> dict[str, object]:
    raw = _read_capability_snapshot_json(args.capabilities_json)
    capabilities: dict[str, dict[str, object]] = {}
    for name, value in raw.items():
        if not isinstance(value, dict):
            raise ValueError("--capabilities-json values must be objects")
        capabilities[name] = value
    return build_executor_capability_snapshot(
        executor=args.executor,
        capabilities=capabilities,
        recorded_at=args.recorded_at or None,
    )


def _read_capability_snapshot_json(path_text: str) -> dict[str, object]:
    raw = sys.stdin.read() if path_text == "-" else Path(path_text).expanduser().read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--capabilities-json must contain a JSON object")
    return value


def _capability_snapshot_path(args: argparse.Namespace) -> Path:
    explicit_path = getattr(args, "snapshot_path", "")
    if explicit_path:
        return Path(explicit_path).expanduser()
    return _paths(args).omh_home / "coding" / "executor-capability-snapshots" / f"{args.executor}.json"


def cmd_coding_governance_discover(args: argparse.Namespace) -> int:
    try:
        _print_json(discover_project_governance(args.project_root, decision=args.governance_default))
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_templates_show(args: argparse.Namespace) -> int:
    try:
        _print_json(product_family_template(args.family))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def cmd_coding_quality_harness_show(args: argparse.Namespace) -> int:
    try:
        _print_json(product_quality_harness(args.family))
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    return 0


def _payload_choice_required(payload: dict[str, object]) -> bool:
    selection = payload.get("executor_selection")
    return isinstance(selection, dict) and bool(selection.get("choice_required"))


def cmd_coding_model_route(args: argparse.Namespace) -> int:
    from ..coding.model_routing import resolve_model_route

    _print_json(
        resolve_model_route(
            args.executor,
            requested_model=args.model or "",
            requested_effort=args.effort or "",
            role=args.role or "",
        )
    )
    return 0


def cmd_coding_fanout_prepare(args: argparse.Namespace) -> int:
    from ..coding.fanout import build_fanout_contract, is_degenerate_single_unit, single_unit_redirect
    from ..coding.fanout_artifacts import write_fanout_contract
    from ..coding.fanout_contracts import FanoutContractError

    units = _read_fanout_units(args.units)
    if is_degenerate_single_unit(units):
        _print_json(single_unit_redirect(units))
        return 0
    try:
        contract = build_fanout_contract(
            " ".join(args.goal).strip(),
            units,
            source=args.source,
            source_metadata=_explicit_source_metadata(args),
        )
    except FanoutContractError as exc:
        raise OmhError(str(exc)) from exc
    if args.record:
        contract = write_fanout_contract(_paths(args), contract)
    _print_json(contract)
    return 0


def cmd_coding_fanout_validate(args: argparse.Namespace) -> int:
    from ..coding.fanout import detect_boundary_overlaps, merge_order, validate_fanout_units, _normalized_unit
    from ..coding.fanout_contracts import FanoutContractError

    units = [_normalized_unit(unit, index) for index, unit in enumerate(_read_fanout_units(args.units))]
    try:
        validate_fanout_units(units)
        notes = detect_boundary_overlaps(units)
        order = merge_order(units)
    except FanoutContractError as exc:
        _print_json({"schema_version": "fanout_validation/v1", "ok": False, "error": str(exc)})
        return 1
    _print_json(
        {
            "schema_version": "fanout_validation/v1",
            "ok": True,
            "unit_count": len(units),
            "merge_order": order,
            "conflict_risk_notes": notes,
        }
    )
    return 0


def cmd_coding_fanout_show(args: argparse.Namespace) -> int:
    from ..coding.fanout_artifacts import read_fanout_contract
    from ..runtime.artifacts import show_run
    from ..runtime.context_budget import payload_fingerprint, run_context_budget, smaller_payload

    paths = _paths(args)
    try:
        contract = read_fanout_contract(paths, args.fanout_id)
    except (OSError, ValueError) as exc:
        raise OmhError(f"fanout contract not found: {exc}") from exc

    full = bool(getattr(args, "full", False))
    history_limit = None if full else _fanout_history_limit(args)
    units = contract.get("units", [])
    status_by_unit: dict[str, object] = {}
    watched_runs: list[str] = []
    exhausted_units: list[str] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        run_ref = str(unit.get("run_ref", ""))
        observed = "not_observed"
        latest_event = ""
        history: dict[str, object] = {}
        if run_ref and (paths.runtime_runs_dir / run_ref / "run.json").exists():
            try:
                shown = show_run(paths, run_ref, history_limit=history_limit)
            except (OSError, ValueError, KeyError):
                shown = None
            if isinstance(shown, dict):
                watched_runs.append(run_ref)
                shown_history = shown.get("history")
                if isinstance(shown_history, dict):
                    journal_bounds = shown_history.get("journal_events")
                    history = journal_bounds if isinstance(journal_bounds, dict) else {}
                events = [event for event in shown.get("journal_events", []) or [] if isinstance(event, dict)]
                if events:
                    latest = events[-1]
                    latest_event = str(latest.get("event", ""))
                    observed = str(latest.get("status", "not_observed"))
                else:
                    observed = "run_recorded_no_observations"
                if run_context_budget(paths, run_ref, surface="fanout_show")["exhausted"]:
                    exhausted_units.append(str(unit.get("unit_id")))
        status_by_unit[str(unit.get("unit_id"))] = {
            "prepared_status": unit.get("status", "prepared"),
            "observed_run_status": observed,
            "latest_observed_event": latest_event,
            "run_ref": run_ref,
            "journal_event_counts": history,
        }
    board = {
        "schema_version": "fanout_board/v1",
        "fanout_id": contract.get("fanout_id"),
        "merge_order": contract.get("merge_plan", {}).get("merge_order", []),
        "units": status_by_unit,
    }
    fingerprint = payload_fingerprint(board)
    context_budget = {
        "history_limit": history_limit,
        "watched_run_count": len(watched_runs),
        "budget_exhausted_units": exhausted_units,
        "policy": "timed_polling_rejected; raw_log_dumping_rejected",
        "next_action": (
            "read_full_history_from_artifacts_instead_of_repeating_this_command"
            if exhausted_units
            else "wait_for_executor_evidence"
        ),
    }
    if not full and _fanout_board_unchanged(paths, watched_runs, fingerprint):
        full_board = {**board, "context_budget": context_budget, "claim_boundary": contract.get("claim_boundary", "")}
        payload = smaller_payload(full_board, {
            "schema_version": "fanout_board_unchanged/v1",
            "fanout_id": contract.get("fanout_id"),
            "unchanged_since_last_emission": True,
            "delta": {},
            "context_budget": context_budget,
            "next_action": "wait_for_new_observed_evidence_instead_of_repeating_this_command",
            "full_output_command": f"omh coding fanout show {contract.get('fanout_id')} --full",
            "claim_boundary": contract.get("claim_boundary", ""),
        })
    else:
        payload = {**board, "context_budget": context_budget, "claim_boundary": contract.get("claim_boundary", "")}
    _print_json(payload)
    _record_fanout_board_emission(paths, watched_runs, payload, fingerprint)
    return 0


_FANOUT_BRIEF_SUMMARY_LIMIT = 200
_FANOUT_BRIEF_CLAIM_BOUNDARY = (
    "A fanout briefing joins the frozen contract with observed dispatch and journal metadata only. "
    "It is not verification, review, CI, merge-readiness, or merge evidence; unknown fields stay "
    "unknown rather than being inferred."
)


def cmd_coding_fanout_brief(args: argparse.Namespace) -> int:
    from ..coding.fanout_artifacts import read_fanout_contract
    from ..local_store import read_json_object_result
    from ..runtime.artifacts import show_run

    paths = _paths(args)
    fanout_id = getattr(args, "fanout_id", None)
    if not fanout_id:
        _print_json(_fanout_brief_listing(paths))
        return 0
    try:
        contract = read_fanout_contract(paths, fanout_id)
    except (OSError, ValueError) as exc:
        raise OmhError(f"fanout contract not found: {exc}") from exc
    dispatch_summary, _ = read_json_object_result(paths.fanout_dispatch_summary_path(str(fanout_id)))
    dispatched_units = {
        str(entry.get("unit_id", "")): entry
        for entry in (dispatch_summary or {}).get("units", [])
        if isinstance(entry, dict)
    }
    units = []
    watched_runs: list[str] = []
    for unit in contract.get("units", []):
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("unit_id", ""))
        handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), dict) else {}
        model_route = handoff.get("model_route", {}) if isinstance(handoff.get("model_route"), dict) else {}
        dispatched = dispatched_units.get(unit_id, {})
        run_ref = str(unit.get("run_ref", ""))
        latest_summary = ""
        observed_status = "not_observed"
        if run_ref and (paths.runtime_runs_dir / run_ref / "run.json").exists():
            try:
                shown = show_run(paths, run_ref, history_limit=1)
            except (OSError, ValueError, KeyError):
                shown = None
            if isinstance(shown, dict):
                watched_runs.append(run_ref)
                events = [event for event in shown.get("journal_events", []) or [] if isinstance(event, dict)]
                if events:
                    latest_summary = str(events[-1].get("summary", ""))[:_FANOUT_BRIEF_SUMMARY_LIMIT]
                    observed_status = str(events[-1].get("status", "not_observed"))
                else:
                    observed_status = "run_recorded_no_observations"
        status = str(dispatched.get("status", "") or "") or str(unit.get("status", "prepared"))
        units.append(
            {
                "unit_id": unit_id,
                "owner": str(handoff.get("executor_target", "choose")),
                "model": str(model_route.get("selected_model", "") or "") or "executor_default",
                "session_ref": str(dispatched.get("session_ref", "") or "") or "unknown",
                "status": status,
                "observed_run_status": observed_status,
                "elapsed_seconds": dispatched.get("duration_seconds", "unknown"),
                "tokens_total": dispatched.get("tokens_total", "unknown"),
                "limit_shaped": bool(dispatched.get("limit_shaped", False)),
                "summary": latest_summary,
            }
        )
    payload = {
        "schema_version": "fanout_briefing/v1",
        "fanout_id": contract.get("fanout_id"),
        "merge_order": contract.get("merge_plan", {}).get("merge_order", []),
        "dispatch_observed_at": (dispatch_summary or {}).get("observed_at", ""),
        "units": units,
        "generated_from": ["fanout_contract", "dispatch_summary", "run_journal"],
        "claim_boundary": _FANOUT_BRIEF_CLAIM_BOUNDARY,
    }
    _print_json(payload)
    _record_fanout_brief_emission(paths, watched_runs, payload)
    return 0


def _record_fanout_brief_emission(paths, watched_runs: list[str], payload: dict) -> None:
    from ..runtime.context_budget import record_context_emission

    if not watched_runs:
        return
    per_run = len(json.dumps(payload, sort_keys=True)) // len(watched_runs)
    for run_ref in watched_runs:
        record_context_emission(paths, run_ref, surface="fanout_brief", byte_count=per_run)


def _fanout_brief_listing(paths) -> dict[str, object]:
    from ..local_store import read_json_object_result

    entries = []
    contracts_dir = paths.fanout_contracts_dir
    if contracts_dir.is_dir():
        for child in sorted(contracts_dir.iterdir()):
            contract_path = child / "fanout_contract.json"
            if not contract_path.is_file():
                continue
            contract, _ = read_json_object_result(contract_path)
            summary, _ = read_json_object_result(paths.fanout_dispatch_summary_path(child.name))
            entries.append(
                {
                    "fanout_id": child.name,
                    "unit_count": len((contract or {}).get("units", [])),
                    "last_dispatch_observed_at": (summary or {}).get("observed_at", ""),
                }
            )
    return {
        "schema_version": "fanout_briefing_listing/v1",
        "fanouts": entries,
        "next_action": "run `omh coding fanout brief <fanout-id>` for one fanout's unit briefing",
        "claim_boundary": _FANOUT_BRIEF_CLAIM_BOUNDARY,
    }


def _fanout_board_unchanged(paths, watched_runs: list[str], fingerprint: str) -> bool:
    """True when every watched run already saw exactly this board.

    The ledger is keyed per run while the board spans several, so a board only
    counts as unchanged if no watched run has newer state than the last
    emission. A partially-changed board still prints in full.
    """
    from ..runtime.context_budget import run_context_budget

    if not watched_runs:
        return False
    return all(
        run_context_budget(paths, run_ref, surface="fanout_show")["last_payload_fingerprint"] == fingerprint
        for run_ref in watched_runs
    )


def _fanout_history_limit(args: argparse.Namespace) -> int:
    from ..runtime.artifacts import DEFAULT_RUN_HISTORY_LIMIT

    limit = getattr(args, "history_limit", None)
    if limit is None:
        return DEFAULT_RUN_HISTORY_LIMIT
    if int(limit) < 1:
        raise OmhError("--limit must be at least 1 unless --full is set")
    return int(limit)


def _record_fanout_board_emission(paths, watched_runs: list[str], payload: dict, fingerprint: str = "") -> None:
    from ..runtime.context_budget import record_context_emission

    if not watched_runs:
        return
    per_run = len(json.dumps(payload, sort_keys=True)) // len(watched_runs)
    for run_ref in watched_runs:
        record_context_emission(
            paths,
            run_ref,
            surface="fanout_show",
            byte_count=per_run,
            payload_fingerprint_value=fingerprint,
        )


def cmd_coding_fanout_dispatch(args: argparse.Namespace) -> int:
    import subprocess as _subprocess

    from ..coding.fanout_artifacts import read_fanout_contract
    from ..coding.fanout_dispatch import dispatch_fanout

    paths = _paths(args)
    try:
        contract = read_fanout_contract(paths, args.fanout_id)
    except (OSError, ValueError) as exc:
        raise OmhError(f"fanout contract not found: {exc}") from exc
    goal_text = sys.stdin.read() if args.goal_file == "-" else Path(args.goal_file).expanduser().read_text(encoding="utf-8")
    repo_root = Path(args.repo_root).expanduser().resolve()
    resolved = _subprocess.run(
        ["git", "rev-parse", args.base_ref],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        timeout=30,
    )
    if resolved.returncode != 0:
        raise OmhError(f"could not resolve --base-ref {args.base_ref!r} in {repo_root}: {resolved.stderr.strip()}")
    try:
        summary = dispatch_fanout(
            paths,
            contract,
            goal_text=goal_text,
            repo_root=repo_root,
            base_sha=resolved.stdout.strip(),
            concurrency=args.concurrency,
            timeout=args.timeout,
            only_units=args.unit,
            dry_run=bool(args.dry_run),
        )
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    _print_json(summary)
    return 0


def _read_fanout_units(units_arg: str) -> list[dict[str, object]]:
    raw = sys.stdin.read() if units_arg == "-" else Path(units_arg).expanduser().read_text(encoding="utf-8")
    payload = json.loads(raw)
    units = payload.get("units") if isinstance(payload, dict) else payload
    if not isinstance(units, list):
        raise OmhError("fanout units input must be a JSON list (or an object with a 'units' list)")
    return units


def _add_coding_commands(sub) -> None:
    coding = sub.add_parser("coding", help="Prepare executor-neutral or tracked coding handoff artifacts.")
    coding_sub = coding.add_subparsers(dest="coding_command", required=True)

    fanout = coding_sub.add_parser(
        "fanout",
        help="Validate and freeze a proposed parallel work split into a fanout contract (agent/backend surface).",
    )
    fanout_sub = fanout.add_subparsers(dest="fanout_command", required=True)

    fanout_prepare = fanout_sub.add_parser("prepare")
    fanout_prepare.add_argument("--goal", nargs="+", required=True, help="Accepted user goal being split.")
    fanout_prepare.add_argument("--units", required=True, help="JSON unit list path, or '-' for stdin.")
    fanout_prepare.add_argument("--source", choices=CHAT_SOURCES, default="generic")
    fanout_prepare.add_argument("--record", action="store_true", help="Persist the contract under ~/.omh/coding/fanout/.")
    fanout_prepare.set_defaults(func=cmd_coding_fanout_prepare)

    fanout_validate = fanout_sub.add_parser("validate")
    fanout_validate.add_argument("--units", required=True, help="JSON unit list path, or '-' for stdin.")
    fanout_validate.set_defaults(func=cmd_coding_fanout_validate)

    fanout_show = fanout_sub.add_parser("show")
    fanout_show.add_argument("fanout_id")
    fanout_show.add_argument(
        "--limit",
        dest="history_limit",
        type=int,
        default=None,
        help="Per-unit run history tail read while projecting the board (default: 20).",
    )
    fanout_show.add_argument(
        "--full",
        action="store_true",
        help="Read each unit's full run history. Expensive for agent context.",
    )
    fanout_show.set_defaults(func=cmd_coding_fanout_show)

    fanout_dispatch = fanout_sub.add_parser(
        "dispatch",
        help="Opt-in local bridge: spawn each unit's local agent CLI in an isolated worktree (never merges).",
    )
    fanout_dispatch.add_argument("fanout_id")
    fanout_dispatch.add_argument("--goal-file", required=True, help="File with the goal text frozen at prepare time ('-' for stdin).")
    fanout_dispatch.add_argument("--repo-root", default=".", help="Repository the unit worktrees branch from.")
    fanout_dispatch.add_argument("--base-ref", default="HEAD", help="Ref resolved once to a SHA all unit branches start from.")
    fanout_dispatch.add_argument("--concurrency", type=int, default=2)
    fanout_dispatch.add_argument("--timeout", type=int, default=1800, help="Per-unit subprocess timeout in seconds.")
    fanout_dispatch.add_argument("--unit", action="append", default=None, help="Dispatch only these unit ids (repeatable).")
    fanout_dispatch.add_argument("--dry-run", action="store_true", help="Resolve readiness, argv, and worktree paths; spawn nothing.")
    fanout_dispatch.set_defaults(func=cmd_coding_fanout_dispatch)

    fanout_brief = fanout_sub.add_parser(
        "brief",
        help="Join the frozen contract with observed dispatch/journal metadata into one per-unit briefing.",
    )
    fanout_brief.add_argument("fanout_id", nargs="?", default=None, help="Fanout id; omit to list known fanouts.")
    fanout_brief.set_defaults(func=cmd_coding_fanout_brief)

    model_route = coding_sub.add_parser(
        "model-route",
        help="Resolve the prepared model route for one executor profile (metadata only, never invocation).",
    )
    model_route.add_argument("--executor", required=True, help="Executor profile, for example codex or claude-code.")
    model_route.add_argument("--model", default=None, help="Explicit model id; always passes through unvalidated.")
    model_route.add_argument("--effort", default=None, help="Reasoning effort for profiles that support one.")
    model_route.add_argument("--role", default=None, help="Subagent role: brain, implementation, design_visual, review, docs.")
    model_route.set_defaults(func=cmd_coding_model_route)

    delegate = coding_sub.add_parser("delegate")
    delegate.add_argument("message", nargs="*", help="Coding task description to prepare for executor delegation.")
    delegate.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the coding request.",
    )
    delegate.add_argument("--limit", type=int, default=3, help="Maximum catalog recommendations to include.")
    delegate.add_argument(
        "--executor",
        choices=CODING_EXECUTOR_TARGETS,
        default=None,
        help="Optional coding executor target for wrapper handoff payloads.",
    )
    delegate.add_argument("--stdin", action="store_true", help="Read the raw coding task from stdin.")
    delegate.add_argument(
        "--event-json",
        default=None,
        help="Read a Slack/Discord/Hermes-like JSON event from this path, or '-' for stdin.",
    )
    delegate.add_argument(
        "--include-message",
        action="store_true",
        help="Include bounded previews and artifact refs for the raw message and expanded delegation prompt.",
    )
    delegate.add_argument(
        "--include-message-full",
        action="store_true",
        help="Include the verbatim raw message and expanded prompts. For wrappers that dispatch the prompt directly.",
    )
    delegate.add_argument("--record", action="store_true", help="Record a metadata-only coding delegation artifact under .omh/runtime.")
    delegate.add_argument(
        "--force-record",
        action="store_true",
        help="Override the meta/test readiness guard when an operator intentionally records a prepared Codex handoff.",
    )
    delegate.add_argument(
        "--context-pack",
        default=None,
        help="Optional handoff_context_pack/v1 JSON to attach to the prepared executor prompt when conflict-free.",
    )
    delegate.add_argument(
        "--from-plan",
        default=None,
        help="Read an accepted hermes_plan/v1 Markdown artifact and use it as executor context.",
    )
    delegate.add_argument(
        "--allow-draft-plan",
        action="store_true",
        help="Allow --from-plan to use a draft plan. Intended only for explicit operator overrides.",
    )
    delegate.add_argument("--source-event-id", default="", help="Optional source message/event id to store as metadata.")
    delegate.add_argument("--channel-ref", default="", help="Optional channel reference to store as metadata.")
    delegate.add_argument("--user-ref", default="", help="Optional user reference to store as metadata.")
    delegate.add_argument("--project-root", default="", help="Explicit project root for read-only governance discovery.")
    delegate.add_argument(
        "--governance-default",
        choices=("not_applicable", "accept", "decline"),
        default="not_applicable",
        help="Explicit advisory-default decision for a project without discovered governance.",
    )
    delegate.add_argument("--product-family", choices=PRODUCT_FAMILIES, default="", help="Optional prepared product-family template.")
    delegate.set_defaults(func=cmd_coding_delegate)

    governance = coding_sub.add_parser("governance", help="Discover explicit-root project governance for prepared handoffs.")
    governance_sub = governance.add_subparsers(dest="governance_command", required=True)
    discover = governance_sub.add_parser("discover")
    discover.add_argument("--project-root", required=True, help="Explicit project root to inspect read-only.")
    discover.add_argument("--governance-default", choices=("not_applicable", "accept", "decline"), default="not_applicable")
    discover.set_defaults(func=cmd_coding_governance_discover)

    templates = coding_sub.add_parser("templates", help="Show prepared product-family coding templates.")
    templates_sub = templates.add_subparsers(dest="templates_command", required=True)
    show_template = templates_sub.add_parser("show")
    show_template.add_argument("--family", choices=PRODUCT_FAMILIES, required=True)
    show_template.set_defaults(func=cmd_coding_templates_show)

    quality_harness = coding_sub.add_parser("quality-harness", help="Show prepared product-family quality harness guidance.")
    quality_harness_sub = quality_harness.add_subparsers(dest="quality_harness_command", required=True)
    show_quality_harness = quality_harness_sub.add_parser("show")
    show_quality_harness.add_argument("--family", choices=PRODUCT_FAMILIES, required=True)
    show_quality_harness.set_defaults(func=cmd_coding_quality_harness_show)

    _add_dynamic_workflow_command(coding_sub)
    _add_capability_snapshot_commands(coding_sub)

    lifecycle = coding_sub.add_parser("lifecycle")
    lifecycle_sub = lifecycle.add_subparsers(dest="lifecycle_command", required=True)

    lifecycle_start = lifecycle_sub.add_parser("start")
    lifecycle_start.add_argument("message", nargs="*", help="Coding task description to prepare for Codex lifecycle tracking.")
    lifecycle_start.add_argument(
        "--source",
        choices=CHAT_SOURCES,
        default="generic",
        help="Source surface that received the coding request.",
    )
    lifecycle_start.add_argument("--limit", type=int, default=3, help="Maximum catalog recommendations to include.")
    lifecycle_start.add_argument("--executor", choices=CODING_EXECUTOR_TARGETS, default="codex", help="Coding executor target.")
    lifecycle_start.add_argument("--record", action="store_true", help="Record a metadata-only prepared lifecycle run.")
    lifecycle_start.add_argument("--stdin", action="store_true", help="Read the raw coding task from stdin.")
    lifecycle_start.add_argument(
        "--event-json",
        default=None,
        help="Read a Slack/Discord/Hermes-like JSON event from this path, or '-' for stdin.",
    )
    lifecycle_start.add_argument(
        "--include-message",
        action="store_true",
        help="Include raw message and expanded executor prompt in stdout for immediate wrapper dispatch.",
    )
    lifecycle_start.add_argument(
        "--context-pack",
        default=None,
        help="Optional handoff_context_pack/v1 JSON to attach to the prepared Codex lifecycle handoff when conflict-free.",
    )
    lifecycle_start.add_argument("--source-event-id", default="", help="Optional source message/event id to store as metadata.")
    lifecycle_start.add_argument("--channel-ref", default="", help="Optional channel reference to store as metadata.")
    lifecycle_start.add_argument("--user-ref", default="", help="Optional user reference to store as metadata.")
    lifecycle_start.set_defaults(func=cmd_coding_lifecycle_start)

    lifecycle_dispatch = lifecycle_sub.add_parser("dispatch")
    lifecycle_dispatch.add_argument("--run", dest="run_id", required=True)
    lifecycle_dispatch.set_defaults(func=cmd_coding_lifecycle_dispatch)

    lifecycle_result = lifecycle_sub.add_parser("result")
    lifecycle_result.add_argument("--run", dest="run_id", required=True)
    lifecycle_result.add_argument("--result", choices=("completed", "blocked", "failed"), required=True)
    lifecycle_result.add_argument("--participants", default="codex")
    lifecycle_result.add_argument("--evidence-ref", action="append")
    lifecycle_result.set_defaults(func=cmd_coding_lifecycle_result)

    lifecycle_verify = lifecycle_sub.add_parser("verify")
    lifecycle_verify.add_argument("--run", dest="run_id", required=True)
    lifecycle_verify.add_argument("--completion-status", choices=("completed", "blocked", "failed", "unknown"), default="completed")
    lifecycle_verify.add_argument("--gap", action="append")
    lifecycle_verify.set_defaults(func=cmd_coding_lifecycle_verify)

    lifecycle_report = lifecycle_sub.add_parser("report")
    lifecycle_report.add_argument("--run", dest="run_id", required=True)
    lifecycle_report.set_defaults(func=cmd_coding_lifecycle_report)

    readiness = coding_sub.add_parser(
        "executor-readiness",
        help="Probe or preview first-use coding agent readiness for wrapper fallback decisions.",
    )
    readiness.add_argument("--executor", choices=EXECUTOR_READINESS_PROFILES, required=True)
    readiness.add_argument("--force", action="store_true", help="Run the probe even if a first-use result is already cached.")
    readiness.add_argument("--dry-run", action="store_true", help="Return the probe contract without running or caching it.")
    readiness.set_defaults(func=cmd_coding_executor_readiness)


def _add_capability_snapshot_commands(coding_sub) -> None:
    snapshots = coding_sub.add_parser(
        "capability-snapshot",
        help="Prepare, persist, inspect, or validate metadata-only executor capability snapshots.",
    )
    snapshot_sub = snapshots.add_subparsers(dest="capability_snapshot_command", required=True)

    prepare = snapshot_sub.add_parser("prepare", help="Build a capability snapshot without writing it.")
    _add_capability_snapshot_build_arguments(prepare)
    prepare.set_defaults(func=cmd_coding_capability_snapshot_prepare)

    record = snapshot_sub.add_parser("record", help="Persist a capability snapshot under .omh or an explicit local path.")
    _add_capability_snapshot_build_arguments(record)
    record.add_argument("--path", dest="snapshot_path", default="", help="Optional local output path for this snapshot.")
    record.set_defaults(func=cmd_coding_capability_snapshot_record)

    inspect = snapshot_sub.add_parser("inspect", help="Read one locally persisted capability snapshot.")
    _add_capability_snapshot_read_arguments(inspect)
    inspect.set_defaults(func=cmd_coding_capability_snapshot_inspect)

    validate = snapshot_sub.add_parser("validate", help="Validate one locally persisted capability snapshot.")
    _add_capability_snapshot_read_arguments(validate)
    validate.set_defaults(func=cmd_coding_capability_snapshot_validate)


def _add_capability_snapshot_build_arguments(parser) -> None:
    parser.add_argument(
        "--executor",
        choices=_CAPABILITY_SNAPSHOT_EXECUTOR_TARGETS,
        required=True,
        help="Selected coding executor profile.",
    )
    parser.add_argument(
        "--capabilities-json",
        required=True,
        help="Path to a metadata-only JSON object keyed by supported capability name, or '-' for stdin.",
    )
    parser.add_argument("--recorded-at", default="", help="Optional ISO-8601 timestamp; defaults to the local record time.")


def _add_capability_snapshot_read_arguments(parser) -> None:
    parser.add_argument(
        "--executor",
        choices=_CAPABILITY_SNAPSHOT_EXECUTOR_TARGETS,
        required=True,
        help="Selected coding executor profile.",
    )
    parser.add_argument("--path", dest="snapshot_path", default="", help="Optional local snapshot path to inspect or validate.")
