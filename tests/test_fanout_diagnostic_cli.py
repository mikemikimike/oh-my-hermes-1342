"""Operator CLI coverage for fanout diagnostics and health events."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.commands.coding import cmd_coding_fanout_dispatch  # noqa: E402
from omh.commands.main import build_parser  # noqa: E402
from omh.coding.diagnostic_execution import DiagnosticExecutionEngine  # noqa: E402
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402


class FanoutDiagnosticsCliTests(unittest.TestCase):
    def test_optional_diagnostics_hook_is_disabled_unless_the_operator_enables_it(self) -> None:
        base = ["coding", "fanout", "dispatch", "fanout-1", "--goal-file", "goal.txt"]

        self.assertFalse(build_parser().parse_args(base).diagnostics)
        self.assertTrue(build_parser().parse_args([*base, "--diagnostics"]).diagnostics)
        self.assertFalse(build_parser().parse_args([*base, "--no-diagnostics"]).diagnostics)

    def test_enabled_diagnostics_builds_the_default_local_engine(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            repo.mkdir()
            (repo / "seed.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "add", "seed.py"], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-qm", "seed"],
                cwd=repo,
                check=True,
            )
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            contract = write_fanout_contract(
                paths,
                build_fanout_contract(
                    "run local diagnostics",
                    [{
                        "unit_id": "core",
                        "title": "Core",
                        "owner": "codex",
                        "file_scope": ["src/"],
                        "verification_commands": ["python -c pass"],
                    }],
                ),
            )
            goal = root / "goal.txt"
            goal.write_text("run local diagnostics", encoding="utf-8")
            args = build_parser().parse_args([
                "coding",
                "fanout",
                "dispatch",
                str(contract["fanout_id"]),
                "--goal-file",
                str(goal),
                "--repo-root",
                str(repo),
                "--base-ref",
                "HEAD",
                "--dry-run",
                "--diagnostics",
            ])
            captured: list[DiagnosticExecutionEngine] = []

            def dispatch(*args: object, **kwargs: object) -> dict[str, object]:
                engine = kwargs.get("diagnostic_engine")
                if isinstance(engine, DiagnosticExecutionEngine):
                    captured.append(engine)
                return {"dry_run": True, "units": []}

            stdout = StringIO()
            with (
                patch("omh.commands.coding._paths", return_value=paths),
                patch("omh.coding.fanout_dispatch.dispatch_fanout", side_effect=dispatch),
                redirect_stdout(stdout),
            ):
                status = cmd_coding_fanout_dispatch(args)

        self.assertEqual(status, 0)
        self.assertTrue(json.loads(stdout.getvalue())["dry_run"])
        self.assertEqual(len(captured), 1)

    def test_health_events_are_explicitly_opt_in_and_can_be_disabled(self) -> None:
        base = ["coding", "fanout", "dispatch", "fanout-1", "--goal-file", "goal.txt"]

        self.assertFalse(build_parser().parse_args(base).health_events)
        self.assertTrue(build_parser().parse_args([*base, "--health-events"]).health_events)
        self.assertFalse(build_parser().parse_args([*base, "--no-health-events"]).health_events)


if __name__ == "__main__":
    unittest.main()
