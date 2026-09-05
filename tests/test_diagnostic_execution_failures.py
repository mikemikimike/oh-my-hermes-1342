"""External-failure containment for diagnostic execution."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.coding.diagnostic_execution import (  # noqa: E402
    DiagnosticExecutionEngine,
    DiagnosticExecutionRequest,
    ProviderObservation,
)
from omh.coding.diagnostic_providers import (  # noqa: E402
    DiagnosticProviderConfig,
    ProviderCapability,
)


def _config() -> DiagnosticProviderConfig:
    return DiagnosticProviderConfig(
        (
            ProviderCapability(
                "ruff",
                ("python",),
                (".py",),
                1_000,
                10,
                10,
                True,
            ),
        )
    )


class _Resolver:
    def resolve(
        self,
        workspace_id: str,
        baseline: str,
        end: str,
    ) -> tuple[str, ...]:
        return ("src/a.py",)


class _FixedRevisions:
    def read(self, workspace_id: str, revision: str) -> str:
        return revision


class _Runner:
    def run(
        self,
        provider_id: str,
        workspace_id: str,
        revision: str,
        files: tuple[str, ...],
        timeout_ms: int,
        cancelled: object,
    ) -> ProviderObservation:
        return ProviderObservation.completed(files, ())


class DiagnosticExecutionFailureTests(unittest.TestCase):
    def test_git_boundary_failures_become_crashed_results(self) -> None:
        class BrokenRevisions:
            def read(self, workspace_id: str, revision: str) -> str:
                raise OSError("git revision unavailable")

        class BrokenResolver:
            def resolve(
                self,
                workspace_id: str,
                baseline: str,
                end: str,
            ) -> tuple[str, ...]:
                raise OSError("git diff unavailable")

        request = DiagnosticExecutionRequest(
            "wrapper",
            "local/omh",
            "base",
            "HEAD",
        )
        revision_failure = DiagnosticExecutionEngine(
            config=_config(),
            resolver=_Resolver(),
            revisions=BrokenRevisions(),
            runner=_Runner(),
        ).execute(request)
        resolver_failure = DiagnosticExecutionEngine(
            config=_config(),
            resolver=BrokenResolver(),
            revisions=_FixedRevisions(),
            runner=_Runner(),
        ).execute(request)

        self.assertEqual(revision_failure.status, "crashed")
        self.assertEqual(revision_failure.results, ())
        self.assertEqual(resolver_failure.status, "crashed")
        self.assertEqual(resolver_failure.results, ())

    def test_single_flight_waiters_receive_unexpected_runner_error(self) -> None:
        started = Event()
        release = Event()
        waiter_entered = Event()

        class RaisingRunner:
            def run(
                self,
                provider_id: str,
                workspace_id: str,
                revision: str,
                files: tuple[str, ...],
                timeout_ms: int,
                cancelled: object,
            ) -> ProviderObservation:
                started.set()
                release.wait(timeout=2)
                raise AssertionError("runner contract bug")

        class TrackingFuture(Future[ProviderObservation]):
            def result(
                self,
                timeout: float | None = None,
            ) -> ProviderObservation:
                waiter_entered.set()
                return super().result(
                    timeout=0.2 if timeout is None else timeout
                )

        engine = DiagnosticExecutionEngine(
            config=_config(),
            resolver=_Resolver(),
            revisions=_FixedRevisions(),
            runner=RaisingRunner(),
        )
        request = DiagnosticExecutionRequest(
            "wrapper",
            "local/omh",
            "base",
            "end",
        )

        with (
            patch(
                "omh.coding.diagnostic_execution_engine.Future",
                TrackingFuture,
            ),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            owner = pool.submit(engine.execute, request)
            self.assertTrue(started.wait(timeout=2))
            waiter = pool.submit(engine.execute, request)
            self.assertTrue(waiter_entered.wait(timeout=2))
            release.set()
            with self.assertRaisesRegex(
                AssertionError,
                "runner contract bug",
            ):
                owner.result(timeout=2)
            with self.assertRaisesRegex(
                AssertionError,
                "runner contract bug",
            ):
                waiter.result(timeout=2)

if __name__ == "__main__":
    unittest.main()
