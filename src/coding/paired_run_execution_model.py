"""Typed metadata-only execution records for committed paired-run plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from .hermes_child_receipts import VerifiedHermesChildReceipt
from .paired_run_dispatch_model import PairedRunDispatchCell, PairedRunDispatchPlan


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class PairedRunExecutionError(RuntimeError):
    """An expected external-boundary execution failure."""


class PairedRunWorkspaceFailure(PairedRunExecutionError):
    """The injected workspace factory could not prepare a workspace."""

    def __init__(
        self,
        message: str,
        *,
        cleanup_succeeded: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.cleanup_succeeded = cleanup_succeeded


class PairedRunRunnerFailure(PairedRunExecutionError):
    """The injected runner reported an expected execution failure."""


class PairedRunCleanupFailure(PairedRunExecutionError):
    """The injected cleaner reported an expected cleanup failure."""


@dataclass(frozen=True, slots=True)
class PairedRunWorkspace:
    """Opaque workspace handle passed unchanged between injected boundaries."""

    workspace_id: str


class ExecutionState(StrEnum):
    """Closed terminal outcomes reported by the paired-run execution boundary."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    RATE_LIMITED = "rate_limited"
    CRASHED = "crashed"
    PARTIAL = "partial"
    CLEANUP_FAILED = "cleanup_failed"
    UNAUTHENTICATED = "unauthenticated"


@dataclass(frozen=True, slots=True)
class PairedRunExecutionLimits:
    """Explicit runner limits; omitted limits are inferred from the frozen waves."""

    global_concurrency: int
    executor_concurrency: dict[str, int]
    provider_concurrency: dict[str, int]


@dataclass(frozen=True, slots=True)
class PairedRunExecutionOutcome:
    """A runner result or persisted metadata-only terminal execution record."""

    state: ExecutionState
    receipt: VerifiedHermesChildReceipt | None
    cell: PairedRunDispatchCell | None = None
    cleanup_succeeded: bool | None = None
    authenticated: bool = False
    reused: bool = False


@dataclass(frozen=True, slots=True)
class PairedRunExecutionReport:
    """The completed plan projection. It carries no merge or content payload."""

    plan: PairedRunDispatchPlan
    receipts: tuple[PairedRunExecutionOutcome, ...]

    @property
    def fan_in_ready(self) -> bool:
        return self.plan.decision_ready and all(
            receipt.state is not ExecutionState.UNAUTHENTICATED
            for receipt in self.receipts
        )

    def metadata(self) -> dict[str, JsonValue]:
        """Return only stable execution metadata suitable for caller persistence."""
        return {
            "decision_id": self.plan.decision_id,
            "fan_in_ready": self.fan_in_ready,
            "cells": [
                {
                    "workspace_id": item.cell.workspace_id if item.cell else "",
                    "state": item.state.value,
                    "authenticated": item.authenticated,
                    "cleanup_succeeded": item.cleanup_succeeded,
                    "reused": item.reused,
                    "receipt_ref": item.receipt.receipt_ref if item.receipt else "",
                }
                for item in self.receipts
            ],
        }
