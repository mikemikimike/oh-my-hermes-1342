"""Shared fixtures for the diagnostic-provider contract tests (issue #1297 T1.2).

One place for the builders every contract-test module needs: a capability,
a check request, a diagnostic item, a completed scheduler round-trip, a
caller-supplied outcome, and one reachable outcome per vocabulary member.
"""

from __future__ import annotations

from omh.coding.diagnostic_providers import (
    DIAGNOSTIC_OUTCOMES,
    DiagnosticCheckOutcome,
    DiagnosticCheckRequest,
    DiagnosticProviderScheduler,
    ProviderCapability,
    build_diagnostic_check_outcome,
)


def _capability(
    provider_id: str = "pyright",
    *,
    enabled: bool = True,
    file_suffixes: tuple[str, ...] = (".py", ".pyi"),
    languages: tuple[str, ...] = ("python",),
    max_diagnostics_per_check: int = 100,
    max_files_per_check: int = 100,
    max_timeout_ms: int = 60_000,
) -> ProviderCapability:
    return ProviderCapability(
        provider_id=provider_id,
        languages=languages,
        file_suffixes=file_suffixes,
        max_timeout_ms=max_timeout_ms,
        max_diagnostics_per_check=max_diagnostics_per_check,
        max_files_per_check=max_files_per_check,
        enabled=enabled,
    )


def _request(
    *changed_files: str,
    revision: str = "rev-end",
    workspace_id: str = "local/omh",
) -> DiagnosticCheckRequest:
    return DiagnosticCheckRequest(
        workspace_id=workspace_id,
        revision=revision,
        changed_files=changed_files,
    )


def _item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "severity": "error",
        "code": "reportUndefinedVariable",
        "path": "src/a.py",
        "line": 12,
        "character": 4,
        "source": "pyright",
    }
    item.update(overrides)
    return item


def _run_check(
    scheduler: DiagnosticProviderScheduler,
    request: DiagnosticCheckRequest,
    *,
    terminal_state: str = "completed",
    diagnostics_revision: str = "rev-end",
    diagnosed_files: tuple[str, ...] = (),
    diagnostics: tuple[dict[str, object], ...] = (),
) -> DiagnosticCheckOutcome:
    ticket = scheduler.begin_check(request)
    return scheduler.end_check(
        ticket,
        terminal_state=terminal_state,
        diagnostics_revision=diagnostics_revision,
        diagnosed_files=diagnosed_files,
        diagnostics=diagnostics,
    )


_CALLER_SUPPLIED_DEFAULTS: dict[str, object] = {
    "workspace_id": "local/omh",
    "revision": "rev-end",
    "diagnostics_revision": "rev-end",
    "provider_id": "pyright",
    "compatibility": "caller_supplied",
    "terminal_state": "completed",
    "in_scope_files": ("src/a.py",),
    "out_of_scope_files": (),
    "diagnosed_files": ("src/a.py",),
    "diagnostics": (),
    "config_identity": "",
}


def _caller_supplied_outcome(**overrides: object) -> DiagnosticCheckOutcome:
    fields = _CALLER_SUPPLIED_DEFAULTS.copy()
    fields.update(overrides)
    return build_diagnostic_check_outcome(
        workspace_id=str(fields["workspace_id"]),
        revision=str(fields["revision"]),
        diagnostics_revision=str(fields["diagnostics_revision"]),
        provider_id=str(fields["provider_id"]),
        compatibility=str(fields["compatibility"]),
        terminal_state=str(fields["terminal_state"]),
        in_scope_files=fields["in_scope_files"],
        out_of_scope_files=fields["out_of_scope_files"],
        diagnosed_files=fields["diagnosed_files"],
        diagnostics=fields["diagnostics"],
        config_identity=str(fields["config_identity"]),
    )


def _every_reachable_outcome() -> dict[str, DiagnosticCheckOutcome]:
    """One outcome per vocabulary member, so invariants run over all of them."""
    scheduler = DiagnosticProviderScheduler()
    outcomes = {
        "ok": _run_check(scheduler, _request("src/coding/a.py"), diagnosed_files=("src/coding/a.py",)),
        "partial": _run_check(
            scheduler,
            _request("src/coding/b.py", "src/coding/c.py"),
            diagnosed_files=("src/coding/b.py",),
        ),
        "timeout": _run_check(scheduler, _request("src/coding/d.py"), terminal_state="timeout"),
        "cancelled": _run_check(scheduler, _request("src/coding/e.py"), terminal_state="cancelled"),
        "crashed": _run_check(scheduler, _request("src/coding/f.py"), terminal_state="crashed"),
        "stale": _run_check(scheduler, _request("src/coding/g.py"), diagnostics_revision="rev-old"),
        "unsupported": _run_check(scheduler, _request("src/coding/h.ts")),
    }
    assert sorted(outcomes) == sorted(DIAGNOSTIC_OUTCOMES), "an outcome has no reachable record"
    return outcomes
