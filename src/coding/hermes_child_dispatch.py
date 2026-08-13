"""Explicit, bounded local Hermes ``--oneshot`` child dispatch.

This is an operator-command integration seam. Importing or constructing a
request never starts work: callers must supply the fixed ask-before-dispatch
policy and an explicit confirmation for every invocation. OMH itself makes no
provider call; the spawned local Hermes CLI owns that call.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import tempfile
from threading import Event, Lock, Thread
import time
from typing import Final

from ._hermes_child_process import (
    BoundedStreamCapture,
    PipeDrainer,
    await_pipe_threads as _await_pipe_threads,
    block_relay_signals as _block_relay_signals,
    bounded_redacted_output as _bounded_redacted_output,
    install_signal_relays as _install_signal_relays,
    merge_signals as _merge_signals,
    read_usage as _read_usage,
    restore_signal_handlers as _restore_signal_handlers,
    restore_signal_mask as _restore_signal_mask,
    start_pipe_drainers as _start_pipe_drainers,
    terminate_process_group as _terminate_process_group,
    write_stdin_and_close as _write_stdin_and_close,
)

MAX_CHILD_DEPTH: Final = 1
_PARENT_MARKER_ENV: Final = "OMH_ISOLATED_HERMES_PARENT"
_DEPTH_ENV: Final = "OMH_ISOLATED_HERMES_DEPTH"
_MARKER_KEY: Final = secrets.token_bytes(32)
_DISPATCH_GUARD = Lock()
_DISPATCH_ACTIVE = False
_SAFE_ENV_NAMES: Final = frozenset(
    {
        "PATH", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TERM",
        "TMPDIR", "TMP", "TEMP", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    }
)
_PROVIDER_ENV: Final = {
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "ANTHROPIC_BASE_URL"),
    "azure": ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION"),
    "bedrock": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "google": ("GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"),
    "nous": ("NOUS_API_KEY",),
    "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"),
    "vertex": ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"),
    "openai-codex": ("OPENAI_API_KEY", "OPENAI_BASE_URL"),
    "claude-sdk-oauth": ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"),
    "opengateway": ("OPENGATEWAY_API_KEY", "OPENGATEWAY_BASE_URL"),
    "qwen": ("QWEN_API_KEY", "QWEN_BASE_URL"),
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"),
    "zai": ("ZAI_API_KEY", "ZAI_BASE_URL"),
}
_CREDENTIAL_NAME = re.compile(r"(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTHORIZATION)", re.IGNORECASE)


class HermesChildDispatchError(RuntimeError):
    """Base error for a refused Hermes child dispatch."""


class DispatchConfirmationError(HermesChildDispatchError):
    """Raised unless the invocation is explicitly confirmed."""


class DispatchRecursionError(HermesChildDispatchError):
    """Raised when an isolated Hermes child attempts another dispatch."""


@dataclass(frozen=True, slots=True)
class HermesChildRequest:
    prompt: str
    model: str
    provider: str
    reasoning: str
    parent_run_id: str
    run_id: str
    timeout_seconds: float = 900.0
    termination_grace_seconds: float = 2.0
    hermes: str = "hermes"
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    depth: int = 0


@dataclass(frozen=True, slots=True)
class HermesChildObservation:
    status: str
    parent_run_id: str
    run_id: str
    depth: int
    model: str
    pid: int | None = None


@dataclass(frozen=True, slots=True)
class HermesChildResult:
    status: str
    parent_run_id: str
    run_id: str
    depth: int
    model: str
    exit_code: int | None
    stdout: str
    stderr: str
    usage: Mapping[str, object]
    cleanup_verified: bool
    usage_file_exists: bool
    termination_signals: tuple[int, ...]
    stdout_truncated: bool
    stderr_truncated: bool


class CancellationToken:
    """Thread-safe explicit cancellation source without polling delays."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._cancelled = False
        self._callbacks: set[Callable[[], None]] = set()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            callbacks = tuple(self._callbacks)
        for callback in callbacks:
            callback()

    def _register(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if not self._cancelled:
                self._callbacks.add(callback)
                return
        callback()

    def _remove(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks.discard(callback)


def dispatch_hermes_child(
    request: HermesChildRequest,
    *,
    dispatch_policy: str,
    confirmed: bool,
    cancellation: CancellationToken | None = None,
    observe: Callable[[HermesChildObservation], None] | None = None,
) -> HermesChildResult:
    """Run one explicitly confirmed local Hermes child and observe its state."""
    if dispatch_policy != "ask_before_dispatch" or not confirmed:
        raise DispatchConfirmationError(
            "isolated Hermes dispatch requires ask_before_dispatch and explicit confirmation"
        )
    if request.depth >= MAX_CHILD_DEPTH or _environment_is_child():
        raise DispatchRecursionError("isolated Hermes child dispatch depth is limited to one")
    if not request.prompt or not request.model or request.timeout_seconds <= 0:
        raise ValueError("prompt, model, and a positive timeout are required")
    _enter_dispatch_guard()
    try:
        return _dispatch_guarded(request, cancellation=cancellation, observe=observe)
    finally:
        _leave_dispatch_guard()


def _dispatch_guarded(
    request: HermesChildRequest,
    *,
    cancellation: CancellationToken | None,
    observe: Callable[[HermesChildObservation], None] | None,
) -> HermesChildResult:
    depth = request.depth + 1
    notify = observe or (lambda _item: None)
    observer_error: BaseException | None = None

    def emit(status: str, pid: int | None = None) -> None:
        nonlocal observer_error
        try:
            notify(HermesChildObservation(
                status, request.parent_run_id, request.run_id, depth, request.model, pid
            ))
        except RuntimeError as exc:
            if status == "prepared":
                raise
            observer_error = exc

    emit("prepared")
    if cancellation is not None and cancellation.cancelled:
        emit("cancelled")
        return _result(request, depth, "cancelled", None, "", "", {}, True, ())

    scratch = tempfile.TemporaryDirectory(prefix="omh-hermes-child-")
    scratch_path = Path(scratch.name)
    hermes_home = scratch_path / "hermes"
    home = scratch_path / "home"
    hermes_home.mkdir(mode=0o700)
    home.mkdir(mode=0o700)
    usage_path = scratch_path / "usage.json"
    usage_path.touch(mode=0o600)
    marker = _parent_marker(request)
    child_env = _child_env(request, depth, hermes_home, home, marker)
    redaction_values = _redaction_values(request, child_env)
    process: subprocess.Popen[bytes] | None = None
    signals: tuple[int, ...] = ()
    cleanup = True
    status, stdout, stderr = "failed", "", ""
    stdout_capture = BoundedStreamCapture(b"", False)
    stderr_capture = BoundedStreamCapture(b"", False)
    drainers: tuple[PipeDrainer, PipeDrainer] | None = None
    stdin_thread: tuple[Thread, Event] | None = None
    usage: Mapping[str, object] = {}
    usage_file_exists = False
    interrupted: BaseException | None = None
    handlers: dict[int, object] = {}
    old_mask: object | None = None
    spawn_lock = Lock()
    termination_lock = Lock()
    cancelled = Event()

    def terminate(first_signal: int) -> None:
        nonlocal signals, cleanup
        with termination_lock:
            if process is None:
                return
            sent, complete = _terminate_process_group(
                process, request.termination_grace_seconds, first_signal
            )
            signals = _merge_signals(signals, sent)
            cleanup = complete

    def cancel_child() -> None:
        cancelled.set()
        with spawn_lock:
            spawned = process is not None
        if spawned:
            terminate(signal.SIGTERM)

    if cancellation is not None:
        cancellation._register(cancel_child)
    try:
        try:
            old_mask = _block_relay_signals()
            with spawn_lock:
                if cancelled.is_set():
                    status = "cancelled"
                else:
                    process = subprocess.Popen(
                        _argv(request, usage_path), cwd=request.cwd, env=child_env,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=False, close_fds=True, **_process_group_options(),
                    )
                    drainers = _start_pipe_drainers(process)
                    stdin_thread = _write_stdin_and_close(process, request.prompt)
            if process is None:
                emit("cancelled")
            else:
                handlers = _install_signal_relays(process)
        except OSError as exc:
            diagnostic = f"Hermes child process could not be started ({type(exc).__name__})"
            stderr_capture = BoundedStreamCapture(diagnostic.encode("utf-8"), False)
            emit("failed")
        finally:
            _restore_signal_mask(old_mask)
            old_mask = None

        if process is not None:
            emit("running", process.pid)
            if observer_error is not None:
                status = "cancelled"
                terminate(signal.SIGTERM)
            deadline = time.monotonic() + request.timeout_seconds
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
                status = "cancelled" if cancelled.is_set() else (
                    "completed" if process.returncode == 0 else "failed"
                )
            except subprocess.TimeoutExpired:
                status = "cancelled" if cancelled.is_set() else "timed_out"
                terminate(signal.SIGTERM)
            except (KeyboardInterrupt, SystemExit) as exc:
                status, interrupted = "cancelled", exc
                first = signal.SIGINT if isinstance(exc, KeyboardInterrupt) else signal.SIGTERM
                terminate(first)
            finally:
                terminate(signal.SIGTERM)
                if drainers is not None and stdin_thread is not None:
                    pipes_complete = _await_pipe_threads(
                        drainers,
                        stdin_thread,
                        timeout=max(0.25, request.termination_grace_seconds),
                    )
                    cleanup = cleanup and pipes_complete
                    stdout_capture = drainers[0].capture()
                    stderr_capture = drainers[1].capture()
            usage = _read_usage(usage_path)
            usage_file_exists = usage_path.exists()
    finally:
        if cancellation is not None:
            cancellation._remove(cancel_child)
        _restore_signal_mask(old_mask)
        _restore_signal_handlers(handlers)
        stdout = _bounded_redacted_output(stdout_capture, secrets=redaction_values)
        stderr = _bounded_redacted_output(stderr_capture, secrets=redaction_values)
        try:
            scratch.cleanup()
        except OSError:
            cleanup = False
        cleanup = cleanup and not scratch_path.exists()
    if interrupted is not None:
        emit(status)
        raise interrupted
    if observer_error is not None:
        raise observer_error
    if not cleanup and status == "completed":
        status = "failed"
    emit(status)
    return _result(
        request, depth, status, process.returncode if process is not None else None,
        stdout, stderr, usage, cleanup, signals,
        stdout_capture.truncated, stderr_capture.truncated, usage_file_exists,
    )


def _argv(request: HermesChildRequest, usage_path: Path) -> tuple[str, ...]:
    # "-" is the stdin sentinel; prompt text must never enter argv. Safe mode
    # is the strongest customization boundary in the installed Hermes CLI;
    # explicit ignore flags keep the contract visible and compatible.
    command = (
        request.hermes, "--oneshot", "-", "--provider", request.provider,
        "--model", request.model, "--reasoning", request.reasoning,
        "--safe-mode", "--ignore-user-config", "--ignore-rules",
        "--toolsets", "file", "--usage-file", str(usage_path),
    )
    if os.name == "nt" and Path(request.hermes).suffix.casefold() == ".py":
        return (sys.executable, *command)
    return command


def _process_group_options() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _child_env(
    request: HermesChildRequest,
    depth: int,
    hermes_home: Path,
    home: Path,
    marker: str,
) -> dict[str, str]:
    source = os.environ if request.env is None else request.env
    child = {name: source[name] for name in _SAFE_ENV_NAMES if source.get(name)}
    child.setdefault("PATH", os.defpath)
    # Authentication is copied only from the caller-selected provider's
    # documented variables. Hermes' auth.json and .env remain unreachable in
    # the disposable homes, and credentials for every other provider stay out.
    provider_names = set(_PROVIDER_ENV.get(request.provider.lower(), ()))
    for name in provider_names:
        value = source.get(name)
        if value:
            child[name] = value
    child.update(
        {
            "HOME": str(home),
            "HERMES_HOME": str(hermes_home),
            "HERMES_SAFE_MODE": "1",
            "HERMES_IGNORE_USER_CONFIG": "1",
            "HERMES_IGNORE_RULES": "1",
            "OMH_ISOLATED_HERMES_ROUTING": "disabled",
            "OMH_ISOLATED_HERMES_MAX_DEPTH": str(MAX_CHILD_DEPTH),
            _DEPTH_ENV: str(depth),
            _PARENT_MARKER_ENV: marker,
        }
    )
    return child


def _environment_is_child() -> bool:
    # Request.env is deliberately irrelevant: a child cannot bypass recursion
    # by passing env={} or deleting keys from a proposed subprocess mapping.
    if os.environ.get(_PARENT_MARKER_ENV):
        return True
    try:
        return int(os.environ.get(_DEPTH_ENV, "0")) >= MAX_CHILD_DEPTH
    except ValueError:
        return True


def _parent_marker(request: HermesChildRequest) -> str:
    nonce = secrets.token_urlsafe(18)
    identity = f"{nonce}\0{request.parent_run_id}\0{request.run_id}".encode()
    signature = hmac.new(_MARKER_KEY, identity, hashlib.sha256).hexdigest()
    return f"v1.{nonce}.{signature}"


def _redaction_values(request: HermesChildRequest, child_env: Mapping[str, str]) -> set[str]:
    source = os.environ if request.env is None else request.env
    values = {request.prompt}
    values.update(
        value for name, value in source.items()
        if value and _CREDENTIAL_NAME.search(name)
    )
    values.update(
        value for name, value in child_env.items()
        if value and _CREDENTIAL_NAME.search(name)
    )
    return values


def _enter_dispatch_guard() -> None:
    global _DISPATCH_ACTIVE
    with _DISPATCH_GUARD:
        if _DISPATCH_ACTIVE:
            raise DispatchRecursionError("an isolated Hermes child dispatch is already active")
        _DISPATCH_ACTIVE = True


def _leave_dispatch_guard() -> None:
    global _DISPATCH_ACTIVE
    with _DISPATCH_GUARD:
        _DISPATCH_ACTIVE = False


def _result(
    request: HermesChildRequest, depth: int, status: str, exit_code: int | None,
    stdout: str, stderr: str, usage: Mapping[str, object], cleanup: bool,
    signals: tuple[int, ...], stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    usage_file_exists: bool = False,
) -> HermesChildResult:
    return HermesChildResult(
        status, request.parent_run_id, request.run_id, depth, request.model, exit_code,
        stdout, stderr, usage, cleanup, usage_file_exists, signals,
        stdout_truncated, stderr_truncated,
    )
