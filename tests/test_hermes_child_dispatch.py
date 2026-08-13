from __future__ import annotations

import io
import json
import os
from pathlib import Path
import signal
import socket
from tempfile import TemporaryDirectory
import textwrap
from threading import Event, Thread
import threading
import tracemalloc
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.coding.hermes_child_dispatch import (  # noqa: E402
    CancellationToken,
    DispatchConfirmationError,
    DispatchRecursionError,
    HermesChildRequest,
    dispatch_hermes_child,
)
from omh.coding._hermes_child_process import (  # noqa: E402
    BoundedStreamCapture,
    bounded_redacted_output,
    process_absent,
)


_FAKE_HERMES = r"""
#!/usr/bin/env python3
import json
import os
from pathlib import Path
import signal
import subprocess
import socket
import sys
import threading
import time

root = Path.cwd()
args = sys.argv[1:]
(root / "argv.json").write_text(json.dumps(args), encoding="utf-8")
(root / "env.json").write_text(json.dumps({
    key: os.environ.get(key) for key in (
        "HOME", "HERMES_HOME", "HERMES_SAFE_MODE", "HERMES_IGNORE_USER_CONFIG",
        "HERMES_IGNORE_RULES", "OMH_ISOLATED_HERMES_ROUTING",
        "OMH_ISOLATED_HERMES_MAX_DEPTH", "OMH_ISOLATED_HERMES_DEPTH",
        "OMH_ISOLATED_HERMES_PARENT", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY",
    )
}), encoding="utf-8")
(root / "isolated-paths.json").write_text(json.dumps({
    "HOME": os.environ["HOME"], "HERMES_HOME": os.environ["HERMES_HOME"],
}), encoding="utf-8")
Path(os.environ["HERMES_HOME"]).joinpath("state.db").write_text("ephemeral", encoding="utf-8")
if args[args.index("--oneshot") + 1] != "-":
    raise SystemExit("oneshot prompt was not supplied through stdin")
prompt = sys.stdin.read()
(root / "prompt-seen").write_text(prompt, encoding="utf-8")
(root / "started").touch()
usage = Path(args[args.index("--usage-file") + 1])
(root / "usage-mode").write_text(oct(usage.stat().st_mode & 0o777), encoding="utf-8")
usage.write_text(json.dumps({
    "estimated_cost_usd": 0.125, "input_tokens": 11, "output_tokens": 7,
    "total_tokens": 18, "api_calls": 1, "model": args[args.index("--model") + 1],
    "provider": "fake-provider", "completed": True, "failed": False,
    "failure": "SECRET_FAILURE_TEXT_MUST_NOT_ESCAPE",
}), encoding="utf-8")
if "spawn-descendant" in prompt:
    child = subprocess.Popen([
        sys.executable, "-c",
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
    ])
    (root / "descendant.pid").write_text(str(child.pid), encoding="utf-8")
    if "notify-port=" in prompt:
        port = int(prompt.split("notify-port=", 1)[1].split()[0])
        with socket.create_connection(("127.0.0.1", port), timeout=2) as ready:
            ready.sendall(b"ready")
if "ignore-term" in prompt:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if "hang" in prompt or "cancel" in prompt:
    while True:
        time.sleep(60)
if "flood-both-100mb" in prompt:
    (root / "flood.pid").write_text(str(os.getpid()), encoding="utf-8")
    chunk = b"z" * (1024 * 1024)
    def flood(fd):
        for _ in range(100):
            view = memoryview(chunk)
            while view:
                written = os.write(fd, view)
                view = view[written:]
    threads = [threading.Thread(target=flood, args=(1,)), threading.Thread(target=flood, args=(2,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    raise SystemExit(9)
if "leak-output" in prompt:
    print(os.environ.get("OPENAI_API_KEY", "missing") + " SECRET_OUTPUT " + "x" * 50000)
    print("authorization bearer must not escape", file=sys.stderr)
    raise SystemExit(9)
if "fail" in prompt:
    print("fake failure", file=sys.stderr)
    raise SystemExit(9)
print("fake Hermes provider response")
"""


class HermesChildDispatchTests(unittest.TestCase):
    def test_truncated_complete_secret_prefix_is_redacted(self) -> None:
        output = bounded_redacted_output(
            BoundedStreamCapture(b"prefix-TOPSECRE", True),
            secrets={"TOPSECRET"},
        )
        self.assertNotIn("TOPSECRE", output)
        self.assertIn("[redacted]", output)

    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="omh-hermes-child-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hermes = self.root / "hermes.py"
        self.hermes.write_text(textwrap.dedent(_FAKE_HERMES).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)
        self.omh_home = self.root / ".omh"
        self.omh_home.mkdir()
        self.env = {**os.environ, "OMH_HOME": str(self.omh_home)}

    def request(self, prompt: str = "do focused work", **changes: object) -> HermesChildRequest:
        values: dict[str, object] = {
            "prompt": prompt,
            "model": "fake/model",
            "provider": "fake-provider",
            "reasoning": "low",
            "parent_run_id": "parent-123",
            "run_id": "child-456",
            "timeout_seconds": 2.0,
            "termination_grace_seconds": 0.2,
            "hermes": str(self.hermes),
            "cwd": self.root,
            "env": self.env,
        }
        values.update(changes)
        return HermesChildRequest(**values)  # type: ignore[arg-type]

    def test_hidden_or_unconfirmed_dispatch_never_starts_hermes(self) -> None:
        for policy, confirmed in (("prepare_only", True), ("ask_before_dispatch", False)):
            with self.subTest(policy=policy, confirmed=confirmed):
                with self.assertRaises(DispatchConfirmationError):
                    dispatch_hermes_child(self.request(), dispatch_policy=policy, confirmed=confirmed)
                self.assertFalse((self.root / "started").exists())

    def test_depth_one_child_cannot_recursively_dispatch(self) -> None:
        with self.assertRaises(DispatchRecursionError):
            dispatch_hermes_child(
                self.request(depth=1),
                dispatch_policy="ask_before_dispatch",
                confirmed=True,
            )
        self.assertFalse((self.root / "started").exists())

    def test_real_fake_hermes_uses_secret_free_argv_and_reports_usage(self) -> None:
        secret = "SECRET_PROMPT_84f3c7"
        observed = []
        result = dispatch_hermes_child(
            self.request(f"do work with {secret}"),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
            observe=observed.append,
        )

        argv = json.loads((self.root / "argv.json").read_text(encoding="utf-8"))
        child_env = json.loads((self.root / "env.json").read_text(encoding="utf-8"))
        self.assertEqual(
            argv[:8],
            [
                "--oneshot",
                "-",
                "--provider",
                "fake-provider",
                "--model",
                "fake/model",
                "--reasoning",
                "low",
            ],
        )
        self.assertEqual(
            argv[8:15],
            ["--safe-mode", "--ignore-user-config", "--ignore-rules", "--toolsets", "file", "--usage-file", argv[14]],
        )
        self.assertNotIn(secret, json.dumps(argv))
        self.assertEqual(
            (result.status, result.stdout.replace("\r\n", "\n"), result.exit_code),
            ("completed", "fake Hermes provider response\n", 0),
        )
        self.assertEqual(result.usage["total_tokens"], 18)
        self.assertNotIn("SECRET_FAILURE_TEXT", repr(result.usage))
        self.assertEqual([item.status for item in observed], ["prepared", "running", "completed"])
        self.assertTrue(all(secret not in repr(item) for item in observed))
        self.assertEqual(child_env["OMH_ISOLATED_HERMES_ROUTING"], "disabled")
        self.assertEqual(child_env["OMH_ISOLATED_HERMES_MAX_DEPTH"], "1")
        self.assertEqual(child_env["OMH_ISOLATED_HERMES_DEPTH"], "1")
        self.assertEqual(child_env["HERMES_SAFE_MODE"], "1")
        self.assertEqual(child_env["HERMES_IGNORE_USER_CONFIG"], "1")
        self.assertEqual(child_env["HERMES_IGNORE_RULES"], "1")
        self.assertNotIn("parent-123", child_env["OMH_ISOLATED_HERMES_PARENT"])
        self.assertNotIn("child-456", child_env["OMH_ISOLATED_HERMES_PARENT"])
        self.assertTrue(result.cleanup_verified)
        isolated = json.loads((self.root / "isolated-paths.json").read_text(encoding="utf-8"))
        self.assertFalse(Path(isolated["HOME"]).exists())
        self.assertFalse(Path(isolated["HERMES_HOME"]).exists())
        self.assertTrue(result.usage_file_exists)
        if os.name != "nt":
            self.assertEqual((self.root / "usage-mode").read_text(encoding="utf-8"), "0o600")
        self.assertNotIn(secret, "".join(path.read_text(encoding="utf-8") for path in self.omh_home.rglob("*") if path.is_file()))

    def test_env_override_cannot_remove_parent_recursion_marker(self) -> None:
        with patch.dict(os.environ, {"OMH_ISOLATED_HERMES_PARENT": "v1.opaque.signature"}):
            with self.assertRaises(DispatchRecursionError):
                dispatch_hermes_child(
                    self.request(env={}),
                    dispatch_policy="ask_before_dispatch",
                    confirmed=True,
                )
        self.assertFalse((self.root / "started").exists())

    def test_active_in_process_dispatch_cannot_reenter_from_observer(self) -> None:
        recursion_errors: list[Exception] = []

        def observe(item: object) -> None:
            if getattr(item, "status", "") != "running":
                return
            try:
                dispatch_hermes_child(
                    self.request(env={}),
                    dispatch_policy="ask_before_dispatch",
                    confirmed=True,
                )
            except DispatchRecursionError as exc:
                recursion_errors.append(exc)

        result = dispatch_hermes_child(
            self.request(), dispatch_policy="ask_before_dispatch", confirmed=True, observe=observe
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(recursion_errors), 1)

    def test_environment_allowlists_only_selected_provider_auth(self) -> None:
        openai_key = "opaque-auth-material-7731"
        aws_key = "unrelated-aws-material-9912"
        env = {
            "PATH": os.environ["PATH"],
            "OPENAI_API_KEY": openai_key,
            "AWS_SECRET_ACCESS_KEY": aws_key,
            "UNRELATED_CREDENTIAL": "other-material-5511",
        }
        result = dispatch_hermes_child(
            self.request(provider="openai", env=env),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
        )
        child_env = json.loads((self.root / "env.json").read_text(encoding="utf-8"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(child_env["OPENAI_API_KEY"], openai_key)
        self.assertIsNone(child_env["AWS_SECRET_ACCESS_KEY"])
        self.assertNotIn("UNRELATED_CREDENTIAL", child_env)

    def test_unknown_provider_cannot_project_dynamic_token(self) -> None:
        credential = "github-token-must-not-project"
        result = dispatch_hermes_child(
            self.request(
                provider="github",
                env={"PATH": os.environ["PATH"], "GITHUB_TOKEN": credential},
            ),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
        )
        child_env = json.loads((self.root / "env.json").read_text(encoding="utf-8"))
        self.assertNotIn("GITHUB_TOKEN", child_env)
        self.assertNotIn(credential, result.stdout)

    def test_observer_failure_after_spawn_still_reaps_child(self) -> None:
        observed_pid: list[int] = []

        def observe(item) -> None:
            if item.pid is not None:
                observed_pid.append(item.pid)
                raise RuntimeError("observer failed")

        with self.assertRaisesRegex(RuntimeError, "observer failed"):
            dispatch_hermes_child(
                self.request("hang", timeout_seconds=10),
                dispatch_policy="ask_before_dispatch",
                confirmed=True,
                observe=observe,
            )
        self.assertTrue(observed_pid)
        self.assertTrue(process_absent(observed_pid[0]))

    def test_prepared_observer_failure_never_spawns(self) -> None:
        def observe(item) -> None:
            if item.status == "prepared":
                raise RuntimeError("prepared observer failed")

        with patch("omh.coding.hermes_child_dispatch.subprocess.Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "prepared observer failed"):
                dispatch_hermes_child(
                    self.request(),
                    dispatch_policy="ask_before_dispatch",
                    confirmed=True,
                    observe=observe,
                )
        popen.assert_not_called()

    def test_output_and_spawn_errors_are_bounded_and_redacted(self) -> None:
        credential = "opaque-auth-material-8842"
        result = dispatch_hermes_child(
            self.request(
                "leak-output",
                provider="openai",
                env={"PATH": os.environ["PATH"], "OPENAI_API_KEY": credential},
            ),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
        )
        self.assertLessEqual(len(result.stdout), 16_500)
        self.assertNotIn(credential, result.stdout)
        self.assertNotIn("SECRET_OUTPUT", result.stdout)
        self.assertNotIn("authorization", result.stderr.lower())

        missing = dispatch_hermes_child(
            self.request(hermes="/private/SECRET_EXECUTABLE_991/not-there"),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
        )
        self.assertEqual(missing.status, "failed")
        self.assertNotIn("SECRET_EXECUTABLE", missing.stderr)
        self.assertIn("FileNotFoundError", missing.stderr)

    def test_exact_100mb_on_both_streams_is_hard_capped_without_deadlock_or_leaks(self) -> None:
        prior_drainers = {
            thread.ident for thread in threading.enumerate()
            if thread.name.startswith("hermes-")
        }
        tracemalloc.start()
        try:
            result = dispatch_hermes_child(
                self.request("flood-both-100mb", timeout_seconds=10.0),
                dispatch_policy="ask_before_dispatch",
                confirmed=True,
            )
            _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertLess(peak_bytes, 4 * 1024 * 1024, "stream capture retained hostile output")
        self.assertEqual((result.status, result.exit_code), ("failed", 9))
        self.assertTrue(result.stdout_truncated)
        self.assertTrue(result.stderr_truncated)
        marker = "[output truncated at 16384-byte capture limit]"
        self.assertEqual(result.stdout.count(marker), 1)
        self.assertEqual(result.stderr.count(marker), 1)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 16_500)
        self.assertLessEqual(len(result.stderr.encode("utf-8")), 16_500)
        self.assertTrue(result.cleanup_verified)
        pid = int((self.root / "flood.pid").read_text(encoding="utf-8"))
        self.assertTrue(process_absent(pid))
        remaining = {
            thread.ident for thread in threading.enumerate()
            if thread.name.startswith("hermes-")
        }
        self.assertEqual(remaining, prior_drainers)

    def test_nonzero_exit_is_failed_and_usage_is_still_parsed(self) -> None:
        result = dispatch_hermes_child(
            self.request("fail"), dispatch_policy="ask_before_dispatch", confirmed=True
        )
        self.assertEqual((result.status, result.exit_code, result.usage["api_calls"]), ("failed", 9, 1))
        self.assertTrue(result.cleanup_verified)

    def test_timeout_sends_sigterm_then_sigkill_and_leaves_no_orphan(self) -> None:
        result = dispatch_hermes_child(
            self.request("spawn-descendant ignore-term hang", timeout_seconds=1.0),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
        )
        pid = int((self.root / "descendant.pid").read_text(encoding="utf-8"))
        self.assertTrue(process_absent(pid))
        self.assertEqual(result.status, "timed_out")
        self.assertEqual(
            result.termination_signals,
            (signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)),
        )
        self.assertTrue(result.cleanup_verified)

    def test_explicit_cancellation_terminates_group_without_timing_luck(self) -> None:
        token = CancellationToken()
        outcome: list[object] = []
        finished = Event()
        ready = socket.socket()
        self.addCleanup(ready.close)
        ready.bind(("127.0.0.1", 0))
        ready.listen(1)
        ready.settimeout(2)
        port = ready.getsockname()[1]

        def run() -> None:
            try:
                outcome.append(
                    dispatch_hermes_child(
                        self.request(
                            f"spawn-descendant notify-port={port} cancel",
                            timeout_seconds=10,
                        ),
                        dispatch_policy="ask_before_dispatch",
                        confirmed=True,
                        cancellation=token,
                    )
                )
            finally:
                finished.set()

        thread = Thread(target=run)
        thread.start()
        connection, _ = ready.accept()
        with connection:
            self.assertEqual(connection.recv(5), b"ready")
        token.cancel()
        self.assertTrue(finished.wait(2), "cancelled dispatch did not finish")
        thread.join()
        result = outcome[0]
        self.assertEqual(result.status, "cancelled")
        pid = int((self.root / "descendant.pid").read_text(encoding="utf-8"))
        self.assertTrue(process_absent(pid))
        self.assertTrue(result.cleanup_verified)

    def test_keyboard_interrupt_is_propagated_after_group_cleanup(self) -> None:
        class InterruptingProcess:
            pid = 991199
            returncode = None
            stdin = io.BytesIO()
            stdout = io.BytesIO()
            stderr = io.BytesIO()

            def poll(self) -> int | None:
                return self.returncode

            def wait(self, timeout: float) -> int:
                raise KeyboardInterrupt

        events = []
        with patch("omh.coding.hermes_child_dispatch.subprocess.Popen", return_value=InterruptingProcess()), patch(
            "omh.coding.hermes_child_dispatch._terminate_process_group",
            return_value=(
                (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)),
                True,
            ),
        ):
            with self.assertRaises(KeyboardInterrupt):
                dispatch_hermes_child(
                    self.request(),
                    dispatch_policy="ask_before_dispatch",
                    confirmed=True,
                    observe=events.append,
                )
        self.assertEqual(events[-1].status, "cancelled")


if __name__ == "__main__":
    unittest.main()
