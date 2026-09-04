"""Config contract tests for `diagnostic_providers/v1` (issue #1297 T1.2).

The provider allowlist, the global and per-provider bounds, and the config
identity: everything that decides which provider a check may run under.
"""

from __future__ import annotations

import unittest

from _diagnostic_provider_helpers import _caller_supplied_outcome, _capability, _item, _request
from omh.coding.diagnostic_providers import (
    DEFAULT_PROVIDER_CAPABILITIES,
    DIAGNOSTIC_PROVIDER_IDS,
    GLOBAL_MAX_DIAGNOSTICS_PER_CHECK,
    GLOBAL_MAX_FILES_PER_CHECK,
    GLOBAL_MAX_TIMEOUT_MS,
    MIN_TIMEOUT_MS,
    DiagnosticProviderConfig,
    DiagnosticProviderError,
    DiagnosticProviderScheduler,
    normalize_diagnostic_item,
)


class ProviderAllowlistTests(unittest.TestCase):
    """The provider set is an allowlist; nothing outside it can be named."""

    def test_the_allowlist_is_a_unique_closed_tuple(self) -> None:
        self.assertTrue(DIAGNOSTIC_PROVIDER_IDS)
        self.assertEqual(len(set(DIAGNOSTIC_PROVIDER_IDS)), len(DIAGNOSTIC_PROVIDER_IDS))
        for provider_id in DIAGNOSTIC_PROVIDER_IDS:
            with self.subTest(provider_id=provider_id):
                self.assertRegex(provider_id, r"^[a-z][a-z0-9-]*$")

    def test_a_capability_for_an_unknown_provider_is_refused(self) -> None:
        with self.assertRaises(DiagnosticProviderError) as caught:
            _capability("pylsp")
        self.assertIn("not allowlisted", str(caught.exception))

    def test_an_outcome_cannot_name_an_unknown_provider(self) -> None:
        with self.assertRaises(DiagnosticProviderError) as caught:
            _caller_supplied_outcome(provider_id="pylsp")
        self.assertIn("not allowlisted", str(caught.exception))

    def test_a_diagnostic_item_source_must_name_an_allowlisted_provider(self) -> None:
        with self.assertRaises(DiagnosticProviderError) as caught:
            normalize_diagnostic_item(_item(source="flaky-analyzer"))
        self.assertIn("allowlisted provider", str(caught.exception))

    def test_the_item_source_field_cannot_carry_source_code(self) -> None:
        with self.assertRaises(DiagnosticProviderError):
            normalize_diagnostic_item(_item(source="import os\nfrom x import y\n"))


class ProviderBoundsTests(unittest.TestCase):
    """Global caps bound every capability; capabilities bound every check."""

    def test_a_timeout_bound_above_the_global_cap_is_refused(self) -> None:
        with self.assertRaises(DiagnosticProviderError) as caught:
            _capability(max_timeout_ms=GLOBAL_MAX_TIMEOUT_MS + 1)
        self.assertIn("max_timeout_ms", str(caught.exception))

    def test_zero_and_negative_bounds_are_refused(self) -> None:
        for overrides in (
            {"max_timeout_ms": 0},
            {"max_timeout_ms": MIN_TIMEOUT_MS - 1},
            {"max_diagnostics_per_check": 0},
            {"max_diagnostics_per_check": -1},
            {"max_files_per_check": 0},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(DiagnosticProviderError):
                    _capability(**overrides)

    def test_a_capability_at_the_global_caps_is_accepted(self) -> None:
        capability = _capability(
            max_timeout_ms=GLOBAL_MAX_TIMEOUT_MS,
            max_diagnostics_per_check=GLOBAL_MAX_DIAGNOSTICS_PER_CHECK,
            max_files_per_check=GLOBAL_MAX_FILES_PER_CHECK,
        )

        self.assertEqual(capability.max_timeout_ms, GLOBAL_MAX_TIMEOUT_MS)
        self.assertEqual(capability.max_diagnostics_per_check, GLOBAL_MAX_DIAGNOSTICS_PER_CHECK)

    def test_a_request_above_the_global_file_bound_is_refused(self) -> None:
        files = tuple(f"src/f{index}.py" for index in range(GLOBAL_MAX_FILES_PER_CHECK + 1))

        with self.assertRaises(DiagnosticProviderError) as caught:
            _request(*files)
        self.assertIn("changed_files", str(caught.exception))

    def test_an_outcome_above_the_global_diagnostics_bound_is_refused(self) -> None:
        items = tuple(_item(line=index) for index in range(GLOBAL_MAX_DIAGNOSTICS_PER_CHECK + 1))

        with self.assertRaises(DiagnosticProviderError) as caught:
            _caller_supplied_outcome(diagnostics=items)
        self.assertIn("diagnostics", str(caught.exception))

    def test_a_provider_diagnostics_bound_is_enforced_by_the_scheduler(self) -> None:
        config = DiagnosticProviderConfig(capabilities=(_capability(max_diagnostics_per_check=1),))
        scheduler = DiagnosticProviderScheduler(config)
        ticket = scheduler.begin_check(_request("src/a.py"))

        with self.assertRaises(DiagnosticProviderError) as caught:
            scheduler.end_check(
                ticket,
                diagnostics_revision="rev-end",
                diagnosed_files=("src/a.py",),
                diagnostics=(_item(), _item(line=13)),
            )
        self.assertIn("at most 1", str(caught.exception))

    def test_selection_skips_a_provider_whose_file_bound_is_too_small(self) -> None:
        config = DiagnosticProviderConfig(
            capabilities=(_capability(max_files_per_check=10), _capability("basedpyright"))
        )
        scheduler = DiagnosticProviderScheduler(config)
        files = tuple(f"src/m{index}.py" for index in range(12))

        ticket = scheduler.begin_check(_request(*files))

        self.assertEqual(ticket.provider_id, "basedpyright")
        self.assertEqual(len(ticket.in_scope_files), 12)


class ConfigIdentityTests(unittest.TestCase):
    """A check names the exact capability set it ran under."""

    def test_the_same_capabilities_in_a_different_order_have_the_same_identity(self) -> None:
        first = DiagnosticProviderConfig(capabilities=(_capability(), _capability("basedpyright")))
        second = DiagnosticProviderConfig(capabilities=(_capability("basedpyright"), _capability()))

        self.assertEqual(first.config_identity(), second.config_identity())

    def test_a_changed_bound_changes_the_identity(self) -> None:
        first = DiagnosticProviderConfig(capabilities=(_capability(),))
        second = DiagnosticProviderConfig(capabilities=(_capability(max_timeout_ms=60_001),))

        self.assertNotEqual(first.config_identity(), second.config_identity())

    def test_a_disabled_provider_changes_the_identity(self) -> None:
        first = DiagnosticProviderConfig(capabilities=(_capability(),))
        second = DiagnosticProviderConfig(capabilities=(_capability(enabled=False),))

        self.assertNotEqual(first.config_identity(), second.config_identity())

    def test_a_removed_provider_changes_the_identity(self) -> None:
        first = DiagnosticProviderConfig(capabilities=(_capability(), _capability("basedpyright")))
        second = DiagnosticProviderConfig(capabilities=(_capability(),))

        self.assertNotEqual(first.config_identity(), second.config_identity())

    def test_the_identity_is_deterministic_and_names_its_schema(self) -> None:
        config = DiagnosticProviderConfig(capabilities=DEFAULT_PROVIDER_CAPABILITIES)

        self.assertEqual(config.config_identity(), config.config_identity())
        self.assertRegex(config.config_identity(), r"^provdiag-[0-9a-f]{16}$")


if __name__ == "__main__":
    unittest.main()
