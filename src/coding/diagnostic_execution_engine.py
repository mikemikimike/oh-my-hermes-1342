"""Bounded post-GREEN execution of allowlisted diagnostic providers."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import nullcontext
from subprocess import SubprocessError, TimeoutExpired
from threading import Lock, Semaphore

from ..quality.language_diagnostic_evidence import build_language_diagnostic_evidence
from .diagnostic_execution_models import (
    CancellationSignal,
    ChangedFileResolver,
    DiagnosticExecutionRequest,
    DiagnosticExecutionResult,
    DiagnosticExecutionSettings,
    ProviderDiagnosticResult,
    ProviderObservation,
    ProviderRunner,
    RevisionReader,
)
from .diagnostic_providers import (
    DIAGNOSTIC_PROVIDER_IDS,
    DiagnosticCheckOutcome,
    DiagnosticProviderConfig,
    DiagnosticProviderError,
    ProviderCapability,
    build_diagnostic_check_outcome,
)


class DiagnosticExecutionEngine:
    """Runs baseline/end observations with caching, bounds, and HEAD revalidation."""

    def __init__(
        self,
        *,
        config: DiagnosticProviderConfig,
        resolver: ChangedFileResolver,
        revisions: RevisionReader,
        runner: ProviderRunner,
        settings: DiagnosticExecutionSettings | None = None,
        cancellation: CancellationSignal | None = None,
    ) -> None:
        self.config = config
        self.resolver = resolver
        self.revisions = revisions
        self.runner = runner
        self.settings = settings or DiagnosticExecutionSettings()
        self.cancellation = cancellation
        self._global_slots = Semaphore(self.settings.max_global_concurrency)
        self._provider_slots = {provider: Semaphore(self.settings.max_provider_concurrency) for provider in DIAGNOSTIC_PROVIDER_IDS}
        self._stateful_locks = {provider: Lock() for provider in self.settings.stateful_providers}
        self._cache: dict[tuple[str, str, str, tuple[str, ...]], ProviderObservation] = {}
        self._inflight: dict[tuple[str, str, str, tuple[str, ...]], Future[ProviderObservation]] = {}
        self._cache_lock = Lock()

    def execute(self, request: DiagnosticExecutionRequest) -> DiagnosticExecutionResult:
        """Observe every applicable provider at both interval endpoints.

        Provider output is handed only to the committed provider facade and the
        evidence builder. Both reject non-metadata diagnostics by key name.
        """
        if not self.settings.enabled:
            return DiagnosticExecutionResult("disabled", ())
        if self._cancelled():
            return DiagnosticExecutionResult("cancelled", ())
        baseline = self.revisions.read(request.workspace_id, request.baseline_revision)
        end = self.revisions.read(request.workspace_id, request.end_revision)
        files = self.resolver.resolve(request.workspace_id, baseline, end)
        selected = self._selected(files)
        if not selected:
            return DiagnosticExecutionResult("unsupported", ())
        with ThreadPoolExecutor(max_workers=min(len(selected), self.settings.max_global_concurrency)) as pool:
            futures = [pool.submit(self._observe_pair, request, capability, files, baseline, end) for capability in selected]
            pairs = [future.result() for future in futures]
        final_end = self.revisions.read(request.workspace_id, request.end_revision)
        results = tuple(
            self._result(request, capability, files, pair, baseline, end, final_end)
            for capability, pair in zip(selected, pairs)
        )
        return DiagnosticExecutionResult(_overall_status(results), results)

    def _selected(self, files: tuple[str, ...]) -> tuple[ProviderCapability, ...]:
        by_id = {capability.provider_id: capability for capability in self.config.capabilities}
        return tuple(
            capability for provider in DIAGNOSTIC_PROVIDER_IDS
            if (capability := by_id.get(provider)) is not None
            and capability.enabled
            and 0 < len(_in_scope(files, capability)) <= capability.max_files_per_check
        )

    def _observe_pair(
        self,
        request: DiagnosticExecutionRequest,
        capability: ProviderCapability,
        files: tuple[str, ...],
        baseline: str,
        end: str,
    ) -> tuple[ProviderObservation, ProviderObservation]:
        scope = _in_scope(files, capability)
        lock = self._stateful_locks.get(capability.provider_id)
        with lock if lock is not None else nullcontext():
            return (
                self._observe(capability, request.workspace_id, baseline, scope),
                self._observe(capability, request.workspace_id, end, scope),
            )

    def _observe(
        self, capability: ProviderCapability, workspace_id: str, revision: str, files: tuple[str, ...]
    ) -> ProviderObservation:
        if self._cancelled():
            return ProviderObservation("cancelled")
        key = (workspace_id, capability.provider_id, revision, files)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            future = self._inflight.get(key)
            if future is None:
                future = Future()
                self._inflight[key] = future
                owner = True
            else:
                owner = False
        if not owner:
            return future.result()
        try:
            with self._global_slots, self._provider_slots[capability.provider_id]:
                observed = self.runner.run(
                    capability.provider_id, workspace_id, revision, files, capability.max_timeout_ms, self.cancellation
                )
            if not isinstance(observed, ProviderObservation):
                observed = ProviderObservation.crashed()
        except TimeoutExpired:
            observed = ProviderObservation("timeout")
        except (OSError, SubprocessError):
            observed = ProviderObservation.crashed()
        with self._cache_lock:
            self._cache[key] = observed
            self._inflight.pop(key).set_result(observed)
        return observed

    def _result(
        self,
        request: DiagnosticExecutionRequest,
        capability: ProviderCapability,
        files: tuple[str, ...],
        pair: tuple[ProviderObservation, ProviderObservation],
        baseline_revision: str,
        observed_end: str,
        final_end: str,
    ) -> ProviderDiagnosticResult:
        baseline_observation, end_observation = pair
        invalid = False
        try:
            baseline = self._outcome(capability, request.workspace_id, baseline_revision, baseline_observation, files)
            end = self._outcome(
                capability, request.workspace_id, final_end, end_observation, files, observed_revision=observed_end
            )
        except DiagnosticProviderError:
            baseline, end, invalid = None, None, True
        status = "crashed" if invalid else _status(baseline, end, baseline_observation, end_observation)
        introduced, resolved = _deltas(baseline, end)
        state = _evidence_state(status)
        evidence = build_language_diagnostic_evidence(
            owner=request.owner,
            provider=capability.provider_id,
            workspace_id=request.workspace_id,
            baseline_revision=baseline_revision,
            end_revision=final_end,
            diagnostics_revision=end.diagnostics_revision if end else "",
            check_state=state,
            config_digest=self.config.config_identity(),
            changed_paths=_in_scope(files, capability),
            introduced=introduced,
            resolved=resolved,
        )
        return ProviderDiagnosticResult(capability.provider_id, status, baseline, end, evidence)

    def _outcome(
        self,
        capability: ProviderCapability,
        workspace_id: str,
        revision: str,
        observation: ProviderObservation,
        files: tuple[str, ...],
        observed_revision: str | None = None,
    ) -> DiagnosticCheckOutcome | None:
        if observation.state == "unavailable":
            return None
        return build_diagnostic_check_outcome(
            workspace_id=workspace_id,
            revision=revision,
            diagnostics_revision=revision if observed_revision is None else observed_revision,
            provider_id=capability.provider_id,
            terminal_state=observation.state,
            compatibility="provider_selected",
            in_scope_files=files,
            diagnosed_files=observation.diagnosed_files,
            diagnostics=observation.diagnostics,
            config_identity=self.config.config_identity(),
        )

    def _cancelled(self) -> bool:
        return self.cancellation.is_set() if self.cancellation is not None else False


def _in_scope(files: tuple[str, ...], capability: ProviderCapability) -> tuple[str, ...]:
    return tuple(path for path in files if path.endswith(capability.file_suffixes))


def _status(
    baseline: DiagnosticCheckOutcome | None,
    end: DiagnosticCheckOutcome | None,
    baseline_observation: ProviderObservation,
    end_observation: ProviderObservation,
) -> str:
    if baseline_observation.state == "unavailable" or end_observation.state == "unavailable":
        return "unavailable"
    if baseline is not None and baseline.outcome != "ok":
        return baseline.outcome
    if end is not None:
        return end.outcome
    return "unavailable"


def _deltas(
    baseline: DiagnosticCheckOutcome | None, end: DiagnosticCheckOutcome | None
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    before = {tuple(item.as_record().items()): item.as_record() for item in baseline.diagnostics} if baseline else {}
    after = {tuple(item.as_record().items()): item.as_record() for item in end.diagnostics} if end else {}
    return tuple(after[key] for key in sorted(set(after) - set(before))), tuple(before[key] for key in sorted(set(before) - set(after)))


def _evidence_state(status: str) -> str:
    if status in ("ok", "stale"):
        return "observed"
    if status in ("timeout", "crashed"):
        return "failed"
    if status == "unsupported":
        return "unsupported"
    return "not_observed"


def _overall_status(results: tuple[ProviderDiagnosticResult, ...]) -> str:
    statuses = {result.status for result in results}
    return statuses.pop() if len(statuses) == 1 else "partial"
