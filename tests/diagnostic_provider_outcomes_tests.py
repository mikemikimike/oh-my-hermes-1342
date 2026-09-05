"""Outcome vocabulary and compatibility tests for `diagnostic_providers/v1` (#1297 T1.2).

The seven closed outcomes, their derivation, and the disabled/caller-supplied
compatibility markers that say how a check related to the allowlisted
providers.
"""

from __future__ import annotations

import unittest

from _diagnostic_provider_helpers import (
    _caller_supplied_outcome,
    _every_reachable_outcome,
    _item,
    _request,
    _run_check,
)
from omh.coding.diagnostic_providers import (
    DIAGNOSTIC_COMPATIBILITY_MARKERS,
    DIAGNOSTIC_OUTCOMES,
    DIAGNOSTIC_TERMINAL_STATES,
    DiagnosticProviderError,
    DiagnosticProviderScheduler,
    build_diagnostic_check_outcome,
    diagnostic_outcome_supports_claim,
)
from omh.quality.language_diagnostic_evidence import LANGUAGE_DIAGNOSTIC_CHECK_STATES


class OutcomeVocabularyTests(unittest.TestCase):
    """Seven outcomes, all reachable, none invented by a caller."""

    def test_the_outcome_vocabulary_is_exactly_the_seven_closed_outcomes(self) -> None:
        self.assertEqual(
            sorted(DIAGNOSTIC_OUTCOMES),
            ["cancelled", "crashed", "ok", "partial", "stale", "timeout", "unsupported"],
        )
        self.assertEqual(sorted(DIAGNOSTIC_TERMINAL_STATES), ["cancelled", "completed", "crashed", "timeout"])
        self.assertEqual(
            sorted(DIAGNOSTIC_COMPATIBILITY_MARKERS),
            ["caller_supplied", "provider_disabled", "provider_selected"],
        )

    def test_every_outcome_is_reachable_and_derived(self) -> None:
        for name, outcome in _every_reachable_outcome().items():
            with self.subTest(outcome=name):
                self.assertEqual(outcome.outcome, name)

    def test_partial_means_not_every_in_scope_file_was_diagnosed(self) -> None:
        scheduler = DiagnosticProviderScheduler()

        outcome = _run_check(
            scheduler,
            _request("src/a.py", "src/b.py"),
            diagnosed_files=("src/a.py",),
        )

        self.assertEqual(outcome.outcome, "partial")
        self.assertFalse(diagnostic_outcome_supports_claim(outcome, "fresh_language_diagnostic_check"))

    def test_an_unknown_terminal_state_is_refused(self) -> None:
        with self.assertRaises(DiagnosticProviderError) as caught:
            _caller_supplied_outcome(terminal_state="exploded")
        self.assertIn("terminal_state is unsupported", str(caught.exception))

    def test_an_unknown_compatibility_marker_is_refused(self) -> None:
        with self.assertRaises(DiagnosticProviderError) as caught:
            _caller_supplied_outcome(compatibility="wrapper")
        self.assertIn("compatibility is unsupported", str(caught.exception))

    def test_an_unknown_outcome_cannot_be_supplied(self) -> None:
        # The outcome is derived from the terminal state and the scope, so the
        # only way to ask for one is to build the situation that produces it.
        for outcome in _every_reachable_outcome().values():
            self.assertIn(outcome.outcome, DIAGNOSTIC_OUTCOMES)


class CompatibilityMarkerTests(unittest.TestCase):
    """The marker says how the check relates to the allowlisted providers."""

    def test_provider_disabled_pairs_only_with_unsupported(self) -> None:
        outcome = build_diagnostic_check_outcome(
            workspace_id="local/omh",
            revision="rev-end",
            diagnostics_revision="",
            compatibility="provider_disabled",
        )

        self.assertEqual(outcome.outcome, "unsupported")

    def test_provider_disabled_cannot_name_a_provider(self) -> None:
        with self.assertRaises(DiagnosticProviderError) as caught:
            _caller_supplied_outcome(compatibility="provider_disabled")
        self.assertIn("provider_disabled", str(caught.exception))

    def test_provider_disabled_cannot_carry_a_terminal_state(self) -> None:
        with self.assertRaises(DiagnosticProviderError):
            build_diagnostic_check_outcome(
                workspace_id="local/omh",
                revision="rev-end",
                diagnostics_revision="",
                compatibility="provider_disabled",
                terminal_state="crashed",
            )

    def test_a_selected_or_caller_supplied_marker_requires_a_provider(self) -> None:
        with self.assertRaises(DiagnosticProviderError):
            build_diagnostic_check_outcome(
                workspace_id="local/omh",
                revision="rev-end",
                diagnostics_revision="rev-end",
                compatibility="provider_selected",
            )

    def test_caller_supplied_diagnostics_are_observed_checks_in_the_v1_vocabulary(self) -> None:
        outcome = _caller_supplied_outcome(diagnostics=(_item(),))

        self.assertEqual(outcome.outcome, "ok")
        self.assertEqual(outcome.compatibility, "caller_supplied")
        self.assertEqual(outcome.language_diagnostic_check_state(), "observed")
        self.assertTrue(diagnostic_outcome_supports_claim(outcome, "fresh_language_diagnostic_check"))

    def test_every_outcome_maps_into_the_v1_check_state_vocabulary(self) -> None:
        expected = {
            "ok": "observed",
            "partial": "observed",
            "stale": "observed",
            "timeout": "failed",
            "crashed": "failed",
            "cancelled": "not_observed",
            "unsupported": "unsupported",
        }
        for name, outcome in _every_reachable_outcome().items():
            with self.subTest(outcome=name):
                self.assertIn(outcome.language_diagnostic_check_state(), LANGUAGE_DIAGNOSTIC_CHECK_STATES)
                self.assertEqual(outcome.language_diagnostic_check_state(), expected[name])


if __name__ == "__main__":
    unittest.main()
