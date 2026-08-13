from __future__ import annotations

import json
import os
from pathlib import Path
import signal
from tempfile import TemporaryDirectory
import textwrap
import unittest
from unittest.mock import patch

from _cli_harness import run_cli


_FAKE_HERMES = r"""
#!/usr/bin/env python3
import json
import os
from pathlib import Path
import signal
import sys
import time

root = Path(sys.argv[0]).resolve().parent
args = sys.argv[1:]
(root / "argv.json").write_text(json.dumps(args), encoding="utf-8")
prompt = sys.stdin.read()
(root / "prompt.txt").write_text(prompt, encoding="utf-8")
usage = Path(args[args.index("--usage-file") + 1])
usage.write_text(json.dumps({
    "provider": "fake-provider", "model": args[args.index("--model") + 1],
    "total_tokens": 19, "estimated_cost_usd": 0.25,
}), encoding="utf-8")
if "hang" in prompt:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(60)
if "fail" in prompt:
    print("fake bad invocation", file=sys.stderr)
    raise SystemExit(7)
print("fake child complete")
"""


class HermesChildCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="omh-hermes-child-cli-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.omh_home = self.root / ".omh"
        self.hermes = self.root / "hermes.py"
        self.hermes.write_text(textwrap.dedent(_FAKE_HERMES).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)

    def base(self, action: str) -> list[str]:
        return [
            "--omh-home", str(self.omh_home), "coding", "hermes-child", action,
            "--model", "fake-model", "--provider", "fake-provider",
            "--reasoning", "high", "--parent-run-id", "parent-123",
            "--run-id", "child-456",
        ]

    def test_prepare_is_default_safe_action_and_writes_no_prompt(self) -> None:
        secret = "SECRET_PREPARE_PROMPT_91"
        status, stdout, stderr = run_cli(self.base("prepare"), stdin_text=secret)
        self.assertEqual(status, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual((payload["schema_version"], payload["claim"], payload["status"]), ("routing_observation/v1", "prepared", "prepared"))
        self.assertEqual(payload["role"], "agent_maintainer")
        self.assertFalse((self.root / "argv.json").exists())
        stored = (self.omh_home / "coding" / "hermes-child" / "child-456" / "observation.json").read_text(encoding="utf-8")
        self.assertNotIn(secret, stored)

    def test_dispatch_requires_confirmation_before_fake_cli_starts(self) -> None:
        status, stdout, stderr = run_cli(self.base("dispatch"), stdin_text="do work")
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("--confirm-dispatch", stderr)
        self.assertFalse((self.root / "argv.json").exists())

    def test_real_fake_cli_happy_bad_timeout_and_secret_free_argv(self) -> None:
        cases = (
            ("SECRET_HAPPY_22", "completed", 0, "2"),
            ("fail SECRET_BAD_73", "failed", 1, "2"),
            ("hang", "timed_out", 1, "0.15"),
        )
        for index, (prompt, expected_status, expected_code, timeout) in enumerate(cases):
            with self.subTest(prompt=prompt):
                run_id = f"child-{index}"
                command = [item if item != "child-456" else run_id for item in self.base("dispatch")]
                command += ["--confirm-dispatch", "--hermes", str(self.hermes), "--timeout", timeout, "--termination-grace", "0.05"]
                status, stdout, stderr = run_cli(command, stdin_text=prompt)
                self.assertEqual(status, expected_code, stderr)
                payload = json.loads(stdout)
                self.assertEqual(payload["status"], expected_status)
                argv = json.loads((self.root / "argv.json").read_text(encoding="utf-8"))
                self.assertNotIn(prompt, json.dumps(argv))
                self.assertEqual(argv[argv.index("--oneshot") + 1], "-")
                stored = (self.omh_home / "coding" / "hermes-child" / run_id / "observation.json").read_text(encoding="utf-8")
                self.assertNotIn(prompt, stored)
                self.assertFalse((self.omh_home / "coding" / "hermes-child" / run_id / "active.json").exists())

    def test_prompt_file_recursion_guard_status_rows_and_help(self) -> None:
        prompt_file = self.root / "prompt.md"
        prompt_file.write_text("file prompt", encoding="utf-8")
        command = self.base("dispatch") + [
            "--confirm-dispatch", "--hermes", str(self.hermes), "--prompt-file", str(prompt_file),
        ]
        previous = os.environ.get("OMH_ISOLATED_HERMES_DEPTH")
        os.environ["OMH_ISOLATED_HERMES_DEPTH"] = "1"
        try:
            status, stdout, stderr = run_cli(command)
        finally:
            if previous is None:
                os.environ.pop("OMH_ISOLATED_HERMES_DEPTH", None)
            else:
                os.environ["OMH_ISOLATED_HERMES_DEPTH"] = previous
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("depth is limited", stderr)
        self.assertFalse((self.root / "argv.json").exists())

        run_cli(self.base("prepare"), stdin_text="status prompt")
        status, stdout, stderr = run_cli([
            "--omh-home", str(self.omh_home), "coding", "hermes-child", "status", "--run-id", "child-456",
        ], output_json=False)
        self.assertEqual(status, 0, stderr)
        self.assertIn("AUDIENCE agent/maintainer", stdout)
        self.assertIn("STATE status prepared", stdout)

        with self.assertRaises(SystemExit) as raised:
            run_cli(["coding", "hermes-child", "--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_traversal_nested_and_symlink_run_ids_are_rejected_before_write(self) -> None:
        child_root = self.omh_home / "coding" / "hermes-child"
        outside = self.root / "outside"
        outside.mkdir()
        child_root.mkdir(parents=True)
        (child_root / "linked").symlink_to(outside, target_is_directory=True)

        for run_id in ("../escape", "nested/run", r"..\\escape", "linked"):
            with self.subTest(run_id=run_id):
                command = [item if item != "child-456" else run_id for item in self.base("prepare")]
                status, stdout, stderr = run_cli(command, stdin_text="safe prompt")
                self.assertEqual((status, stdout), (2, ""))
                self.assertIn("run_id", stderr)
        self.assertFalse((self.omh_home / "coding" / "escape" / "observation.json").exists())
        self.assertFalse((child_root / "nested" / "run" / "observation.json").exists())
        self.assertFalse((outside / "observation.json").exists())

    def test_symlinked_child_root_is_rejected(self) -> None:
        outside = self.root / "outside-root"
        outside.mkdir()
        coding = self.omh_home / "coding"
        coding.mkdir(parents=True, exist_ok=True)
        (coding / "hermes-child").symlink_to(outside, target_is_directory=True)
        status, stdout, stderr = run_cli(
            self.base("prepare"),
            stdin_text="secret prompt",
        )
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("symlink", stderr)
        self.assertFalse((outside / "child-456" / "observation.json").exists())

    def test_duplicate_dispatch_run_id_is_rejected(self) -> None:
        command = [*self.base("dispatch"), "--confirm-dispatch", "--hermes", str(self.hermes)]
        first = run_cli(command, stdin_text="first prompt")
        self.assertEqual(first[0], 0)
        second = run_cli(command, stdin_text="second prompt")
        self.assertEqual(second[0], 2)
        self.assertIn("already exists", second[2])

    def test_status_rejects_unvalidated_persisted_payload_without_echoing_it(self) -> None:
        observation_path = self.omh_home / "coding" / "hermes-child" / "child-456" / "observation.json"
        observation_path.parent.mkdir(parents=True)
        secret = "ULTRA_PRIVATE_PERSISTED_PROSE_791"
        observation_path.write_text(
            json.dumps({"schema_version": "attacker/v1", "status": "completed", "prose": secret}),
            encoding="utf-8",
        )
        status, stdout, stderr = run_cli([
            "--omh-home", str(self.omh_home), "coding", "hermes-child", "status",
            "--run-id", "child-456",
        ])
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("invalid", stderr)
        self.assertNotIn(secret, stdout + stderr)

    def test_status_rejects_shape_valid_tampered_observation(self) -> None:
        run_cli(self.base("prepare"), stdin_text="prepare")
        observation_path = (
            self.omh_home
            / "coding"
            / "hermes-child"
            / "child-456"
            / "observation.json"
        )
        payload = json.loads(observation_path.read_text(encoding="utf-8"))
        payload["status"] = "completed"
        payload["claim"] = "observed"
        payload["tokens"] = 987654
        observation_path.write_text(json.dumps(payload), encoding="utf-8")
        status, stdout, stderr = run_cli(
            [
                "--omh-home",
                str(self.omh_home),
                "coding",
                "hermes-child",
                "status",
                "--run-id",
                "child-456",
            ]
        )
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("invalid", stderr)

    def test_cancel_signals_only_matching_live_process_identity(self) -> None:
        run_cli(self.base("prepare"), stdin_text="cancel target")
        active_path = self.omh_home / "coding" / "hermes-child" / "child-456" / "active.json"
        identity = {"start_time": "123.456", "executable": "/safe/omh"}
        active_path.write_text(
            json.dumps(
                {
                    "schema_version": "hermes_child_active/v2",
                    "run_id": "child-456",
                    "run_nonce": "a" * 64,
                    "dispatcher_pid": 43210,
                    "child_pid": 43211,
                    "process_identity": identity,
                }
            ),
            encoding="utf-8",
        )
        with patch("omh.commands.hermes_child._process_identity", return_value=identity), patch(
            "omh.commands.hermes_child.os.kill"
        ) as kill:
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(self.omh_home), "coding", "hermes-child",
                    "cancel", "--run-id", "child-456",
                ]
            )
        self.assertEqual(status, 0, stderr)
        kill.assert_called_once_with(43210, signal.SIGTERM)
        self.assertEqual(json.loads(stdout)["status"], "cancelled")

    def test_stale_or_forged_process_identity_never_signals_unrelated_pid(self) -> None:
        run_cli(self.base("prepare"), stdin_text="cancel target")
        active_path = self.omh_home / "coding" / "hermes-child" / "child-456" / "active.json"
        active_path.write_text(
            json.dumps(
                {
                    "schema_version": "hermes_child_active/v2",
                    "run_id": "child-456",
                    "run_nonce": "b" * 64,
                    "dispatcher_pid": os.getpid(),
                    "child_pid": os.getpid(),
                    "process_identity": {"start_time": "stale", "executable": "/forged"},
                }
            ),
            encoding="utf-8",
        )
        live_identity = {"start_time": "live", "executable": "/actual"}
        with patch("omh.commands.hermes_child._process_identity", return_value=live_identity), patch(
            "omh.commands.hermes_child.os.kill"
        ) as kill:
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(self.omh_home), "coding", "hermes-child",
                    "cancel", "--run-id", "child-456",
                ]
            )
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("identity", stderr)
        kill.assert_not_called()

    def test_cancel_never_signals_pid_from_forged_or_legacy_active_record(self) -> None:
        run_cli(self.base("prepare"), stdin_text="cancel target")
        active_path = self.omh_home / "coding" / "hermes-child" / "child-456" / "active.json"
        active_path.write_text(
            json.dumps(
                {
                    "schema_version": "hermes_child_active/v1",
                    "run_id": "child-456",
                    "dispatcher_pid": os.getpid(),
                    "child_pid": os.getpid(),
                }
            ),
            encoding="utf-8",
        )
        with patch("omh.commands.hermes_child.os.kill") as kill:
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(self.omh_home), "coding", "hermes-child",
                    "cancel", "--run-id", "child-456",
                ]
            )
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("invalid", stderr)
        kill.assert_not_called()

    def test_empty_prompt_and_argv_prompt_are_rejected(self) -> None:
        status, stdout, stderr = run_cli(self.base("prepare"), stdin_text="")
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("non-empty prompt", stderr)
        with self.assertRaises(SystemExit) as raised:
            run_cli(self.base("prepare") + ["secret-on-argv"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
