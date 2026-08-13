"""Explicit agent/maintainer CLI for one isolated local Hermes child."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import sys

from ..coding.hermes_child_dispatch import (
    DispatchConfirmationError,
    DispatchRecursionError,
    HermesChildDispatchError,
    HermesChildObservation,
    HermesChildRequest,
    dispatch_hermes_child,
)
from ..coding.routing_observation import (
    authenticate_child_observation,
    authenticate_executor_observation,
    build_routing_observation,
    render_routing_status_rows,
    validate_routing_observation,
)
from ..installer import OmhError
from ..local_store import atomic_write_json, read_json_object
from ..system.metadata_safety import require_opaque_metadata_ref
from .common import _paths, _print_json, _wants_json

_AUDIENCE = "agent/maintainer"
_ACTIVE_SCHEMA_VERSION = "hermes_child_active/v2"


def cmd_hermes_child_prepare(args: argparse.Namespace) -> int:
    _validate_metadata_args(args)
    prompt = _read_prompt(args.prompt_file)
    del prompt  # Deliberately neither persisted nor returned.
    observation = _prepared_observation(args)
    _write_observation(args, observation)
    _emit(args, observation)
    return 0


def cmd_hermes_child_dispatch(args: argparse.Namespace) -> int:
    if not args.confirm_dispatch:
        raise OmhError("Hermes child dispatch requires --confirm-dispatch; prepare is the safe default")
    _validate_metadata_args(args)
    prompt = _read_prompt(args.prompt_file)
    run_dir = _run_dir(args)
    run_dir.mkdir(mode=0o700, exist_ok=True)
    reservation_path = run_dir / "dispatch.reserved"
    try:
        reservation = os.open(
            reservation_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as exc:
        raise OmhError(f"Hermes child run already exists: {args.run_id}") from exc
    os.close(reservation)
    active_path = run_dir / "active.json"
    run_nonce = secrets.token_hex(32)

    def observe(item: HermesChildObservation) -> None:
        observation = _observed_payload(args, item.status)
        _write_observation(args, observation)
        if item.pid is not None:
            atomic_write_json(
                active_path,
                {
                    "schema_version": _ACTIVE_SCHEMA_VERSION,
                    "run_id": args.run_id,
                    "run_nonce": run_nonce,
                    "dispatcher_pid": os.getpid(),
                    "child_pid": item.pid,
                    "process_identity": _process_identity(os.getpid()),
                },
                private=True,
            )

    try:
        result = dispatch_hermes_child(
            HermesChildRequest(
                prompt=prompt,
                model=args.model,
                provider=args.provider,
                reasoning=args.reasoning,
                parent_run_id=args.parent_run_id,
                run_id=args.run_id,
                timeout_seconds=args.timeout,
                termination_grace_seconds=args.termination_grace,
                hermes=args.hermes,
                cwd=Path(args.cwd).expanduser() if args.cwd else None,
            ),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
            observe=observe,
        )
    except (DispatchConfirmationError, DispatchRecursionError, HermesChildDispatchError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    finally:
        active_path.unlink(missing_ok=True)

    observation = _result_payload(args, result.status, result.usage)
    _write_observation(args, observation)
    _emit(args, observation)
    return 0 if result.status == "completed" else 1


def cmd_hermes_child_status(args: argparse.Namespace) -> int:
    _validate_run_id(args.run_id)
    try:
        observation = read_json_object(_run_dir(args) / "observation.json")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(f"Hermes child observation is unreadable: {exc}") from exc
    if observation is None:
        raise OmhError(f"Hermes child run not found: {args.run_id}")
    if (
        validate_routing_observation(observation)
        or observation.get("run_id") != args.run_id
        or not _observation_signature_valid(args, observation)
    ):
        raise OmhError("Hermes child observation is invalid")
    _emit(args, observation)
    return 0


def cmd_hermes_child_cancel(args: argparse.Namespace) -> int:
    _validate_run_id(args.run_id)
    active_path = _run_dir(args) / "active.json"
    try:
        active = read_json_object(active_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(f"Hermes child active record is unreadable: {exc}") from exc
    if active is None:
        raise OmhError(f"Hermes child run is not active: {args.run_id}")
    _validate_active_record(active, args.run_id)
    pid = int(active["dispatcher_pid"])
    try:
        current_identity = _process_identity(pid)
    except (OSError, ValueError) as exc:
        active_path.unlink(missing_ok=True)
        raise OmhError(f"Hermes child run is no longer active: {args.run_id}") from exc
    if current_identity != active["process_identity"]:
        raise OmhError("Hermes child active process identity does not match")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError as exc:
        active_path.unlink(missing_ok=True)
        raise OmhError(f"Hermes child run is no longer active: {args.run_id}") from exc
    observation = _cancelled_from_existing(args)
    _write_observation(args, observation)
    _emit(args, observation)
    return 0


def _prepared_observation(args: argparse.Namespace) -> dict[str, object]:
    _validate_metadata_args(args)
    return build_routing_observation(
        route=_route(args),
        parent_session_id=args.parent_run_id,
        child_session_id=args.run_id,
        run_id=args.run_id,
    )


def _observed_payload(args: argparse.Namespace, status: str) -> dict[str, object]:
    if status == "prepared":
        return _prepared_observation(args)
    return build_routing_observation(
        route=_route(args),
        child_dispatch=authenticate_child_observation(
            {"status": status, "run_id": args.run_id}
        ),
        parent_session_id=args.parent_run_id,
        child_session_id=args.run_id,
        run_id=args.run_id,
    )


def _result_payload(args: argparse.Namespace, status: str, usage: object) -> dict[str, object]:
    session: dict[str, object] = {"status": status}
    if isinstance(usage, dict):
        session.update(
            {
                key: usage[key]
                for key in ("provider", "model", "total_tokens", "estimated_cost_usd")
                if key in usage
            }
        )
        if "total_tokens" in session:
            session["tokens"] = session.pop("total_tokens")
        if "estimated_cost_usd" in session:
            session["cost_usd"] = session.pop("estimated_cost_usd")
        if "tokens" not in session:
            token_parts = [
                usage.get(key)
                for key in ("input_tokens", "output_tokens", "reasoning_tokens")
            ]
            observed_parts = [
                value for value in token_parts if isinstance(value, int) and not isinstance(value, bool)
            ]
            if observed_parts:
                session["tokens"] = sum(observed_parts)
        for source, target in (("turns", "turn"), ("tool_calls", "tools"), ("cost_usd", "cost_usd")):
            value = usage.get(source)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                session[target] = value
    return build_routing_observation(
        route=_route(args),
        child_dispatch=authenticate_child_observation(
            {"status": status, "run_id": args.run_id}
        ),
        session_observation=authenticate_executor_observation(session),
        parent_session_id=args.parent_run_id,
        child_session_id=args.run_id,
        run_id=args.run_id,
    )


def _validate_active_record(active: dict[str, object], run_id: str) -> None:
    expected_fields = {
        "schema_version",
        "run_id",
        "run_nonce",
        "dispatcher_pid",
        "child_pid",
        "process_identity",
    }
    if set(active) != expected_fields or active.get("schema_version") != _ACTIVE_SCHEMA_VERSION:
        raise OmhError("Hermes child active record is invalid")
    if active.get("run_id") != run_id:
        raise OmhError("Hermes child active record is invalid")
    for field in ("dispatcher_pid", "child_pid"):
        value = active.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 1:
            raise OmhError("Hermes child active record is invalid")
    nonce = active.get("run_nonce")
    if not isinstance(nonce, str) or len(nonce) != 64:
        raise OmhError("Hermes child active record is invalid")
    try:
        int(nonce, 16)
    except ValueError as exc:
        raise OmhError("Hermes child active record is invalid") from exc
    identity = active.get("process_identity")
    if not isinstance(identity, dict) or set(identity) != {"start_time", "executable"}:
        raise OmhError("Hermes child active record is invalid")
    if not isinstance(identity.get("start_time"), str) or not identity["start_time"]:
        raise OmhError("Hermes child active record is invalid")
    if not isinstance(identity.get("executable"), str) or not identity["executable"]:
        raise OmhError("Hermes child active record is invalid")


def _process_identity(pid: int) -> dict[str, str]:
    if sys.platform.startswith("linux"):
        stat_fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        if len(stat_fields) < 22:
            raise ValueError("process metadata is incomplete")
        executable = str(Path(f"/proc/{pid}/exe").resolve(strict=True))
        return {"start_time": stat_fields[21], "executable": executable}
    if sys.platform == "darwin":
        return _darwin_process_identity(pid)
    if sys.platform == "win32":
        return _windows_process_identity(pid)
    raise OSError("process identity verification is unavailable on this platform")


def _darwin_process_identity(pid: int) -> dict[str, str]:
    class ProcBsdInfo(ctypes.Structure):
        _fields_ = [
            ("flags", ctypes.c_uint32), ("status", ctypes.c_uint32),
            ("xstatus", ctypes.c_int32), ("pid", ctypes.c_int32),
            ("ppid", ctypes.c_int32), ("uid", ctypes.c_uint32),
            ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32),
            ("rgid", ctypes.c_uint32), ("svuid", ctypes.c_uint32),
            ("svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
            ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
            ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32),
            ("pjobc", ctypes.c_uint32), ("tdev", ctypes.c_int32),
            ("tpgid", ctypes.c_int32), ("nice", ctypes.c_int32),
            ("start_tvsec", ctypes.c_uint64), ("start_tvusec", ctypes.c_uint64),
        ]

    libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    info = ProcBsdInfo()
    if libproc.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info):
        raise ProcessLookupError(pid)
    path_buffer = ctypes.create_string_buffer(4096)
    if libproc.proc_pidpath(pid, path_buffer, len(path_buffer)) <= 0:
        raise ProcessLookupError(pid)
    executable = os.fsdecode(path_buffer.value)
    return {
        "start_time": f"{info.start_tvsec}.{info.start_tvusec}",
        "executable": str(Path(executable).resolve()),
    }


def _windows_process_identity(pid: int) -> dict[str, str]:
    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        raise ProcessLookupError(pid)
    try:
        creation = FileTime()
        exit_time = FileTime()
        kernel = FileTime()
        user = FileTime()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise ProcessLookupError(pid)
        capacity = ctypes.c_uint32(32_768)
        path_buffer = ctypes.create_unicode_buffer(capacity.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, path_buffer, ctypes.byref(capacity)
        ):
            raise ProcessLookupError(pid)
        start_time = (creation.high << 32) | creation.low
        return {
            "start_time": str(start_time),
            "executable": str(Path(path_buffer.value).resolve()),
        }
    finally:
        kernel32.CloseHandle(handle)


def _cancelled_from_existing(args: argparse.Namespace) -> dict[str, object]:
    existing = read_json_object(_run_dir(args) / "observation.json") or {}
    provider = str(existing.get("selected_provider") or "hermes")
    model = str(existing.get("selected_model") or "unknown")
    reasoning = str(existing.get("selected_reasoning") or "unknown")
    route = {
        "selected_model": f"{provider}/{model}",
        "selected_reasoning_effort": reasoning,
        "role": "agent_maintainer",
        "executor_profile": "hermes_child",
        "chain": [{"provider": provider, "model_id": model, "reasoning_effort": reasoning}],
    }
    return build_routing_observation(
        route=route,
        child_dispatch=authenticate_child_observation(
            {"status": "cancelled", "run_id": args.run_id}
        ),
        parent_session_id=str(existing.get("parent_session_id") or ""),
        child_session_id=str(existing.get("child_session_id") or args.run_id),
        run_id=args.run_id,
    )


def _route(args: argparse.Namespace) -> dict[str, object]:
    return {
        "selected_model": f"{args.provider}/{args.model}",
        "selected_reasoning_effort": args.reasoning,
        "role": "agent_maintainer",
        "executor_profile": "hermes_child",
        "chain": [
            {
                "provider": args.provider,
                "model_id": args.model,
                "reasoning_effort": args.reasoning,
            }
        ],
    }


def _validate_metadata_args(args: argparse.Namespace) -> None:
    for field in ("model", "provider", "reasoning", "parent_run_id", "run_id"):
        try:
            require_opaque_metadata_ref(getattr(args, field), field=field)
        except ValueError as exc:
            raise OmhError(str(exc)) from exc
    _validate_run_id(args.run_id)


def _validate_run_id(run_id: str) -> None:
    try:
        safe_run_id = require_opaque_metadata_ref(run_id, field="run_id")
    except ValueError as exc:
        raise OmhError(str(exc)) from exc
    if safe_run_id in {".", ".."} or "/" in safe_run_id or "\\" in safe_run_id:
        raise OmhError("run_id must be a single safe opaque metadata reference")


def _read_prompt(source: str) -> str:
    try:
        prompt = sys.stdin.read() if source == "-" else Path(source).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise OmhError(f"could not read prompt file: {exc}") from exc
    if not prompt.strip():
        raise OmhError("a non-empty prompt is required via stdin or --prompt-file")
    return prompt


def _run_dir(args: argparse.Namespace) -> Path:
    _validate_run_id(args.run_id)
    omh_home = _paths(args).omh_home.expanduser()
    coding = omh_home / "coding"
    root = coding / "hermes-child"
    for component in (omh_home, coding, root):
        if component.is_symlink() or (
            component.exists() and component.resolve(strict=True) != component
        ):
            raise OmhError("Hermes child storage path must not contain a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    candidate = root / args.run_id
    if (
        candidate.is_symlink()
        or (candidate.exists() and candidate.resolve(strict=True) != candidate)
        or candidate.parent != root
    ):
        raise OmhError("run_id resolves outside the Hermes child run directory")
    return candidate


def _write_observation(args: argparse.Namespace, observation: dict[str, object]) -> None:
    run_dir = _run_dir(args)
    atomic_write_json(run_dir / "observation.json", observation, private=True)
    signature = hmac.new(
        _observation_key(args),
        _canonical_observation(observation),
        hashlib.sha256,
    ).hexdigest()
    atomic_write_json(
        run_dir / "observation.signature.json",
        {"schema_version": "hermes_child_observation_signature/v1", "hmac_sha256": signature},
        private=True,
    )


def _observation_signature_valid(
    args: argparse.Namespace,
    observation: dict[str, object],
) -> bool:
    try:
        signature = read_json_object(_run_dir(args) / "observation.signature.json")
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(signature, dict):
        return False
    observed = signature.get("hmac_sha256")
    if not isinstance(observed, str):
        return False
    expected = hmac.new(
        _observation_key(args),
        _canonical_observation(observation),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(observed, expected)


def _observation_key(args: argparse.Namespace) -> bytes:
    root = _run_dir(args).parent
    key_path = root / ".observation-hmac-key"
    try:
        descriptor = os.open(
            key_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError:
        pass
    else:
        try:
            os.write(descriptor, secrets.token_bytes(32))
        finally:
            os.close(descriptor)
    key = key_path.read_bytes()
    if len(key) != 32 or key_path.is_symlink():
        raise OmhError("Hermes child observation integrity key is invalid")
    return key


def _canonical_observation(observation: dict[str, object]) -> bytes:
    return json.dumps(
        observation,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _emit(args: argparse.Namespace, observation: dict[str, object]) -> None:
    if _wants_json(args):
        _print_json(observation)
        return
    print(f"AUDIENCE {_AUDIENCE}")
    print("\n".join(render_routing_status_rows(observation)))


def _add_request_arguments(parser: argparse.ArgumentParser, *, dispatch: bool) -> None:
    parser.add_argument("--prompt-file", default="-", help="Prompt file, or '-' for stdin (default). Prompt text is never accepted on argv.")
    parser.add_argument("--model", required=True, help="Hermes model alias metadata and --model value.")
    parser.add_argument("--provider", required=True, help="Provider alias metadata (not a credential).")
    parser.add_argument("--reasoning", required=True, help="Reasoning alias metadata.")
    parser.add_argument("--parent-run-id", required=True, help="Opaque parent run id.")
    parser.add_argument("--run-id", required=True, help="Opaque isolated child run id.")
    parser.add_argument("--json", action="store_true", help="Emit routing_observation/v1 JSON instead of status rows.")
    if dispatch:
        parser.add_argument("--confirm-dispatch", action="store_true", help="Required explicit approval to start local Hermes.")
        parser.add_argument("--hermes", default="hermes", help="Hermes CLI executable path.")
        parser.add_argument("--cwd", default=None, help="Child working directory.")
        parser.add_argument("--timeout", type=float, default=900.0, help="Hard child timeout in seconds.")
        parser.add_argument("--termination-grace", type=float, default=2.0, help="SIGTERM grace before SIGKILL.")


def add_hermes_child_command(coding_sub: argparse._SubParsersAction) -> None:
    child = coding_sub.add_parser(
        "hermes-child",
        help="Agent/maintainer-only explicit isolated Hermes child control (never automatic).",
        description=(
            "AUDIENCE: agent/maintainer. Prepare is non-executing; dispatch calls only the isolated "
            "Hermes child module and requires --confirm-dispatch. Prompts come only from stdin/files."
        ),
    )
    actions = child.add_subparsers(dest="hermes_child_action", required=True)
    prepare = actions.add_parser("prepare", help="Default-safe metadata-only preparation; starts no process.")
    _add_request_arguments(prepare, dispatch=False)
    prepare.set_defaults(func=cmd_hermes_child_prepare)
    dispatch = actions.add_parser("dispatch", help="Explicitly dispatch one bounded local Hermes --oneshot child.")
    _add_request_arguments(dispatch, dispatch=True)
    dispatch.set_defaults(func=cmd_hermes_child_dispatch)
    status = actions.add_parser("status", help="Read the metadata-only routing observation for one child run.")
    status.add_argument("--run-id", required=True)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_hermes_child_status)
    cancel = actions.add_parser("cancel", help="Signal an active foreground dispatcher and its isolated process group.")
    cancel.add_argument("--run-id", required=True)
    cancel.add_argument("--json", action="store_true")
    cancel.set_defaults(func=cmd_hermes_child_cancel)
