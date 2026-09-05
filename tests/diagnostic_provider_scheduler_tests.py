"""Scheduler contract tests for `diagnostic_providers/v1` (issue #1297 T1.2).

The stateful serial scheduler and its fallback past disabled or failed
providers, plus the module-boundary guards that keep the whole contract from
ever being able to start a server or touch disk.
"""

from __future__ import annotations

import ast
import importlib
from dataclasses import replace
from pathlib import Path
import unittest

from _diagnostic_provider_helpers import _capability, _request, _run_check
from omh.coding.diagnostic_providers import (
    DiagnosticProviderConfig,
    DiagnosticProviderError,
    DiagnosticProviderScheduler,
)

# Every module of the contract, facade included. The import-boundary tests
# below walk all of them, so a split can never smuggle a capability in.
CONTRACT_MODULE_NAMES = (
    "diagnostic_providers",
    "diagnostic_provider_models",
    "diagnostic_provider_parse",
    "diagnostic_provider_config",
    "diagnostic_provider_scope",
    "diagnostic_provider_outcomes",
    "diagnostic_provider_claims",
    "diagnostic_provider_validate",
    "diagnostic_provider_scheduler",
)


def _module_source(name: str) -> str:
    contract_module = importlib.import_module(f"omh.coding.{name}")
    return Path(contract_module.__file__ or "").read_text(encoding="utf-8")


class StatefulSerialFallbackTests(unittest.TestCase):
    """One check at a time, past disabled and failed providers."""

    def test_a_second_check_cannot_begin_while_one_is_active(self) -> None:
        scheduler = DiagnosticProviderScheduler()
        scheduler.begin_check(_request("src/a.py"))

        with self.assertRaises(DiagnosticProviderError) as caught:
            scheduler.begin_check(_request("src/b.py"))
        self.assertIn("serial", str(caught.exception))

    def test_a_check_can_begin_again_after_the_active_one_ends(self) -> None:
        scheduler = DiagnosticProviderScheduler()
        ticket = scheduler.begin_check(_request("src/a.py"))
        scheduler.end_check(ticket, diagnostics_revision="rev-end", diagnosed_files=("src/a.py",))

        second = scheduler.begin_check(_request("src/b.py"))

        self.assertEqual(second.check_number, 2)
        self.assertEqual(scheduler.active_provider_id, "pyright")

    def test_end_check_refuses_a_foreign_ticket(self) -> None:
        scheduler = DiagnosticProviderScheduler()
        ticket = scheduler.begin_check(_request("src/a.py"))
        forged = replace(ticket, check_number=99)

        with self.assertRaises(DiagnosticProviderError) as caught:
            scheduler.end_check(forged, diagnostics_revision="rev-end")
        self.assertIn("own active check", str(caught.exception))

    def test_end_check_refuses_when_no_check_is_active(self) -> None:
        scheduler = DiagnosticProviderScheduler()
        ticket = scheduler.begin_check(_request("src/a.py"))
        scheduler.end_check(ticket, diagnostics_revision="rev-end")

        with self.assertRaises(DiagnosticProviderError) as caught:
            scheduler.end_check(ticket, diagnostics_revision="rev-end")
        self.assertIn("no active check", str(caught.exception))

    def test_selection_falls_back_past_a_disabled_provider(self) -> None:
        config = DiagnosticProviderConfig(capabilities=(_capability(enabled=False), _capability("basedpyright")))
        scheduler = DiagnosticProviderScheduler(config)

        ticket = scheduler.begin_check(_request("src/a.py"))

        self.assertEqual(ticket.provider_id, "basedpyright")

    def test_selection_falls_back_past_a_provider_that_timed_out(self) -> None:
        scheduler = DiagnosticProviderScheduler()
        first = _run_check(scheduler, _request("src/a.py"), terminal_state="timeout")

        self.assertEqual(first.outcome, "timeout")
        self.assertEqual(scheduler.last_provider_id, "pyright")
        self.assertEqual(scheduler.last_outcome, "timeout")
        self.assertEqual(scheduler.completed_checks, 1)

        ticket = scheduler.begin_check(_request("src/b.py"))
        self.assertEqual(ticket.provider_id, "basedpyright")

    def test_a_recovered_provider_is_selected_again(self) -> None:
        scheduler = DiagnosticProviderScheduler()
        _run_check(scheduler, _request("src/a.py"), terminal_state="crashed")
        second = scheduler.begin_check(_request("src/b.py"))  # falls back past pyright
        scheduler.end_check(second, diagnostics_revision="rev-end", diagnosed_files=("src/b.py",))

        scheduler.mark_provider_available("pyright")
        ticket = scheduler.begin_check(_request("src/c.py"))

        self.assertEqual(ticket.provider_id, "pyright")

    def test_marking_an_unknown_provider_available_is_refused(self) -> None:
        scheduler = DiagnosticProviderScheduler()

        with self.assertRaises(DiagnosticProviderError):
            scheduler.mark_provider_available("pylsp")

    def test_the_scheduler_is_idle_only_between_checks(self) -> None:
        scheduler = DiagnosticProviderScheduler()

        self.assertEqual(scheduler.active_provider_id, "")

        ticket = scheduler.begin_check(_request("src/a.py"))
        self.assertNotEqual(scheduler.active_provider_id, "")

        scheduler.end_check(ticket, diagnostics_revision="rev-end")
        self.assertEqual(scheduler.active_provider_id, "")


class ModuleBoundaryTests(unittest.TestCase):
    """The contract selects and records; it must never be able to execute."""

    def test_the_contract_imports_nothing_that_could_start_a_server_or_touch_disk(self) -> None:
        imported: set[str] = set()
        for name in CONTRACT_MODULE_NAMES:
            for node in ast.walk(ast.parse(_module_source(name))):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and not node.level:
                    imported.add((node.module or "").split(".")[0])

        self.assertEqual(imported, {"__future__", "collections", "dataclasses", "hashlib"})
        for capability in ("subprocess", "socket", "urllib", "http", "pathlib", "os", "shutil", "time", "datetime"):
            with self.subTest(capability=capability):
                self.assertNotIn(capability, imported)

    def test_relative_imports_reuse_only_the_sanctioned_contracts(self) -> None:
        sanctioned = {"quality.language_diagnostic_evidence", "system.metadata_safety"}
        allowed = sanctioned | set(CONTRACT_MODULE_NAMES)
        relative: set[str] = set()
        for name in CONTRACT_MODULE_NAMES:
            for node in ast.walk(ast.parse(_module_source(name))):
                if isinstance(node, ast.ImportFrom) and node.level:
                    relative.add(node.module or "")

        self.assertTrue(relative <= allowed)
        self.assertIn("quality.language_diagnostic_evidence", relative)
        self.assertIn("system.metadata_safety", relative)


if __name__ == "__main__":
    unittest.main()
