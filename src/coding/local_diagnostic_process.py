"""Allowlisted subprocess boundary for local diagnostic providers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
from typing import Iterator

from .diagnostic_execution import CancellationSignal, ProviderObservation
from .diagnostic_providers import GLOBAL_MAX_DIAGNOSTICS_PER_CHECK
from .local_diagnostic_capture import DiagnosticPipeDrainer
from .local_diagnostic_parsing import parse_local_diagnostics
from .local_diagnostic_process_owner import ProcessTreeOwner, start_owned_process


_COMMAND_ARGS: dict[str, tuple[str, ...]] = {
    "pyright": ("--outputjson",),
    "basedpyright": ("--outputjson",),
    "ruff": ("check", "--no-cache", "--isolated", "--output-format=json", "--"),
}
_MAX_OUTPUT_BYTES = 2_000_000
_TERMINATE_GRACE_SECONDS = 1.0


class LocalDiagnosticProviderRunner:
    """Run one closed-set provider against one immutable Git snapshot."""

    def __init__(self, executables: Mapping[str, str]) -> None:
        unknown = set(executables) - set(_COMMAND_ARGS)
        if unknown:
            raise ValueError(
                f"local diagnostic provider is not allowlisted: {sorted(unknown)}"
            )
        checked: dict[str, str] = {}
        for provider_id, executable in executables.items():
            path = Path(executable).expanduser()
            if not path.is_file() or not os.access(path, os.X_OK):
                raise ValueError(
                    f"local diagnostic executable is unavailable for {provider_id}"
                )
            checked[provider_id] = str(path.resolve())
        self.executables = checked
        self._git_lock = Lock()

    def run(
        self,
        provider_id: str,
        workspace_id: str,
        revision: str,
        files: tuple[str, ...],
        timeout_ms: int,
        cancelled: CancellationSignal | None,
    ) -> ProviderObservation:
        executable = self.executables.get(provider_id)
        if executable is None:
            return ProviderObservation.unavailable()
        if cancelled is not None and cancelled.is_set():
            return ProviderObservation("cancelled")
        with _revision_worktree(
            Path(workspace_id),
            revision,
            self._git_lock,
        ) as snapshot:
            existing = tuple(
                path for path in files if (snapshot / path).is_file()
            )
            if not existing:
                return ProviderObservation.completed(files, ())
            argv = [
                executable,
                *_COMMAND_ARGS[provider_id],
                *existing,
            ]
            return self._execute(
                provider_id,
                argv,
                snapshot,
                files,
                timeout_ms,
                cancelled,
            )

    def _execute(
        self,
        provider_id: str,
        argv: Sequence[str],
        snapshot: Path,
        files: tuple[str, ...],
        timeout_ms: int,
        cancelled: CancellationSignal | None,
    ) -> ProviderObservation:
        process, process_owner = start_owned_process(
            argv,
            cwd=snapshot,
            env=_diagnostic_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            raise OSError("local diagnostic subprocess pipes were unavailable")
        stdout = DiagnosticPipeDrainer(
            process.stdout,
            max_bytes=_MAX_OUTPUT_BYTES,
            name=f"diagnostic-stdout-{process.pid}",
        )
        stderr = DiagnosticPipeDrainer(
            process.stderr,
            max_bytes=_MAX_OUTPUT_BYTES,
            name=f"diagnostic-stderr-{process.pid}",
        )
        stdout.start()
        stderr.start()
        stopped = Event()
        cancelled_during_run = Event()
        watcher = Thread(
            target=_watch_cancellation,
            args=(
                cancelled,
                process_owner,
                stopped,
                cancelled_during_run,
            ),
            daemon=True,
        )
        watcher.start()
        cleanup_signal = signal.SIGTERM
        process_group_clean = False
        try:
            try:
                process.wait(timeout=timeout_ms / 1000)
            except subprocess.TimeoutExpired:
                raise
            except KeyboardInterrupt:
                cleanup_signal = signal.SIGINT
                raise
        finally:
            stopped.set()
            watcher.join(timeout=3)
            process_group_clean = process_owner.terminate(cleanup_signal)
            stdout_capture = stdout.finish(1)
            stderr_capture = stderr.finish(1)
        if not process_group_clean:
            return ProviderObservation.crashed()
        if cancelled_during_run.is_set() or (
            cancelled is not None and cancelled.is_set()
        ):
            return ProviderObservation("cancelled")
        if process.returncode not in (0, 1):
            return ProviderObservation.crashed()
        if stdout_capture.truncated or stderr_capture.truncated:
            return ProviderObservation("completed", (), ())
        try:
            diagnostics = parse_local_diagnostics(
                provider_id,
                stdout_capture.data,
                snapshot,
                files,
            )
        except ValueError:
            return ProviderObservation.crashed()
        if len(diagnostics) > GLOBAL_MAX_DIAGNOSTICS_PER_CHECK:
            return ProviderObservation("completed", (), ())
        return ProviderObservation.completed(files, diagnostics)


def _watch_cancellation(
    cancelled: CancellationSignal | None,
    process_owner: ProcessTreeOwner,
    stopped: Event,
    cancelled_during_run: Event,
) -> None:
    if cancelled is None:
        return
    while not stopped.wait(0.05):
        if cancelled.is_set():
            cancelled_during_run.set()
            process_owner.terminate(signal.SIGTERM)
            return


@contextmanager
def _revision_worktree(
    workspace: Path,
    revision: str,
    git_lock: Lock,
) -> Iterator[Path]:
    with TemporaryDirectory(prefix="omh-diagnostics-") as raw:
        snapshot = Path(raw) / "checkout"
        with git_lock:
            added = subprocess.run(
                [
                    "git",
                    "worktree",
                    "add",
                    "--detach",
                    "--quiet",
                    str(snapshot),
                    revision,
                ],
                cwd=workspace,
                capture_output=True,
                timeout=30,
            )
        if added.returncode != 0:
            raise OSError("local diagnostics could not materialize the revision")
        try:
            yield snapshot
        finally:
            with git_lock:
                removed = subprocess.run(
                    [
                        "git",
                        "worktree",
                        "remove",
                        "--force",
                        str(snapshot),
                    ],
                    cwd=workspace,
                    capture_output=True,
                    timeout=30,
                )
            if removed.returncode != 0:
                raise OSError("local diagnostics could not remove its revision worktree")


def _diagnostic_environment() -> dict[str, str]:
    retained = (
        "HOME",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "VIRTUAL_ENV",
        "WINDIR",
    )
    environment = {
        key: os.environ[key]
        for key in retained
        if key in os.environ
    }
    environment.update({"NO_COLOR": "1", "PYTHONUTF8": "1"})
    return environment
