"""Post-GREEN diagnostic fanout hook behavior."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.diagnostic_execution import (  # noqa: E402
    DiagnosticExecutionEngine,
    DiagnosticExecutionSettings,
    ProviderObservation,
)
from omh.coding.diagnostic_providers import DiagnosticProviderConfig, ProviderCapability  # noqa: E402
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import unit_result_path, write_fanout_contract  # noqa: E402
from omh.coding.fanout_diagnostics_hook import run_post_green_diagnostics  # noqa: E402
from omh.coding.fanout_dispatch import dispatch_fanout  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402


class _Resolver:
    def resolve(self, workspace_id: str, baseline: str, end: str) -> tuple[str, ...]:
        return ("src/a.py",)


class _Revisions:
    def read(self, workspace_id: str, revision: str) -> str:
        return revision


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def run(
        self,
        provider_id: str,
        workspace_id: str,
        revision: str,
        files: tuple[str, ...],
        timeout_ms: int,
        cancelled: object,
    ) -> ProviderObservation:
        self.calls.append((provider_id, revision, files))
        return ProviderObservation.completed(files, ())


def _engine(runner: _Runner, *, enabled: bool = True) -> DiagnosticExecutionEngine:
    config = DiagnosticProviderConfig(
        (ProviderCapability("pyright", ("python",), (".py",), 1_000, 10, 10, True),)
    )
    return DiagnosticExecutionEngine(
        config=config,
        resolver=_Resolver(),
        revisions=_Revisions(),
        runner=runner,
        settings=DiagnosticExecutionSettings(enabled=enabled),
    )


class FanoutDiagnosticsHookTests(unittest.TestCase):
    def test_runs_only_after_fixed_green_evidence_and_reuses_engine_identity(self) -> None:
        runner = _Runner()
        engine = _engine(runner)
        revision = "a" * 40
        kwargs = {
            "owner": "codex",
            "workspace_id": "workspace-1",
            "baseline_revision": "b" * 40,
            "end_revision": revision,
            "verification_passed": True,
            "producer_evidence": True,
        }

        first = run_post_green_diagnostics(engine, **kwargs)
        second = run_post_green_diagnostics(engine, **kwargs)

        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(first, second)
        self.assertEqual(first["diagnostic_status"], "observed")
        self.assertEqual(first["diagnostic_execution_status"], "ok")
        self.assertEqual(len(first["diagnostic_evidence_refs"]), 1)
        self.assertNotIn("verification_status", first)
        self.assertNotIn("integration_ready", first)

    def test_provider_failure_is_diagnostic_hold_metadata_only(self) -> None:
        class UnavailableRunner(_Runner):
            def run(
                self,
                provider_id: str,
                workspace_id: str,
                revision: str,
                files: tuple[str, ...],
                timeout_ms: int,
                cancelled: object,
            ) -> ProviderObservation:
                self.calls.append((provider_id, revision, files))
                return ProviderObservation.unavailable()

        result = run_post_green_diagnostics(
            _engine(UnavailableRunner()),
            owner="codex",
            workspace_id="workspace-1",
            baseline_revision="b" * 40,
            end_revision="a" * 40,
            verification_passed=True,
            producer_evidence=True,
        )

        self.assertEqual(result["diagnostic_status"], "held")
        self.assertEqual(result["diagnostic_execution_status"], "unavailable")
        self.assertNotIn("process_succeeded", result)
        self.assertNotIn("integration_ready", result)

    def test_refuses_missing_moving_or_non_green_inputs_without_executing(self) -> None:
        for values in (
            {"verification_passed": False, "producer_evidence": True, "end_revision": "a" * 40},
            {"verification_passed": True, "producer_evidence": False, "end_revision": "a" * 40},
            {"verification_passed": True, "producer_evidence": True, "end_revision": ""},
            {"verification_passed": True, "producer_evidence": True, "end_revision": "HEAD"},
        ):
            with self.subTest(values=values):
                runner = _Runner()
                result = run_post_green_diagnostics(
                    _engine(runner),
                    owner="codex",
                    workspace_id="workspace-1",
                    baseline_revision="b" * 40,
                    **values,
                )
                self.assertIsNone(result)
                self.assertEqual(runner.calls, [])

    def test_dispatch_attaches_diagnostics_without_promoting_verification(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "seed.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "seed.py"], cwd=repo, check=True)
            subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-qm", "seed"],
                cwd=repo,
                check=True,
            )
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
            ).stdout.strip()
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            contract = write_fanout_contract(
                paths,
                build_fanout_contract(
                    "run diagnostics after green",
                    [{
                        "unit_id": "core",
                        "title": "Core",
                        "owner": "codex",
                        "file_scope": ["src/"],
                        "verification_commands": ["python -c pass"],
                    }],
                ),
            )
            sidecar = unit_result_path(paths, contract["fanout_id"], "core")

            class Completed:
                returncode = 0
                stdout = "done"
                stderr = ""

            def runner(argv: list[str], **kwargs: object) -> object:
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                sidecar.parent.mkdir(parents=True, exist_ok=True)
                sidecar.write_text(
                    json.dumps(
                        {
                            "schema_version": "fanout_unit_result/v1",
                            "unit_id": "core",
                            "run_id": contract["units"][0]["run_ref"],
                            "fanout_id": contract["fanout_id"],
                            "base_sha": sha,
                            "head_sha": sha,
                            "process_status": "process_succeeded",
                            "changed_paths": [],
                            "checks": [],
                            "findings": [],
                        }
                    ),
                    encoding="utf-8",
                )
                return Completed()

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text="run diagnostics after green",
                repo_root=repo,
                base_sha=sha,
                only_units=["core"],
                run_verification=True,
                runner=runner,
                readiness=lambda _paths, profile: {"status": "ready", "profile": profile},
                diagnostic_engine=_engine(_Runner()),
            )

            entry = summary["units"][0]
            self.assertEqual(entry["verification_status"], "passed")
            self.assertTrue(entry["unit_verification_observed"])
            self.assertTrue(entry["integration_ready"])
            self.assertEqual(entry["diagnostic_status"], "observed")
            self.assertEqual(entry["diagnostic_execution_status"], "ok")
            self.assertEqual(len(entry["diagnostic_evidence_refs"]), 1)

    def test_disabled_engine_preserves_the_dispatch_result_shape(self) -> None:
        runner = _Runner()

        result = run_post_green_diagnostics(
            _engine(runner, enabled=False),
            owner="codex",
            workspace_id="workspace-1",
            baseline_revision="b" * 40,
            end_revision="a" * 40,
            verification_passed=True,
            producer_evidence=True,
        )

        self.assertIsNone(result)
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
