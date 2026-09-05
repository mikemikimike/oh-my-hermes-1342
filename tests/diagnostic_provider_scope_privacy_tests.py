"""Scope and privacy contract tests for `diagnostic_providers/v1` (#1297 T1.2).

The changed-file scope (including files no provider supports and paths that
escape the workspace), the moving-HEAD equality predicate, and the
metadata-only shape of everything persistable.
"""

from __future__ import annotations

import unittest

import omh.coding.diagnostic_providers as module
from _diagnostic_provider_helpers import (
    _caller_supplied_outcome,
    _every_reachable_outcome,
    _item,
    _request,
    _run_check,
)
from omh.coding.diagnostic_providers import (
    DIAGNOSTIC_OUTCOME_RECORD_KEYS,
    DIAGNOSTIC_PROVIDER_IDS,
    MOVING_REVISION_REFS,
    RAW_PAYLOAD_FIELD_NAMES,
    DiagnosticProviderError,
    DiagnosticProviderScheduler,
    diagnostic_outcome_supports_claim,
    is_moving_revision,
    normalize_diagnostic_item,
    revisions_identical,
)
from omh.quality.language_diagnostic_evidence import LANGUAGE_DIAGNOSTIC_ITEM_KEYS


class MovingRevisionEqualityTests(unittest.TestCase):
    """A moving HEAD is identical to nothing, not even itself."""

    def test_identical_pinned_revisions_are_identical(self) -> None:
        self.assertTrue(revisions_identical("rev-a", "rev-a"))
        self.assertTrue(is_moving_revision("HEAD"))
        self.assertFalse(is_moving_revision("rev-a"))

    def test_different_or_empty_revisions_are_not_identical(self) -> None:
        self.assertFalse(revisions_identical("rev-a", "rev-b"))
        self.assertFalse(revisions_identical("", "rev-a"))
        self.assertFalse(revisions_identical("rev-a", ""))

    def test_a_moving_head_is_identical_to_nothing_not_even_itself(self) -> None:
        for ref in MOVING_REVISION_REFS:
            with self.subTest(ref=ref):
                self.assertFalse(revisions_identical(ref, ref))
                self.assertFalse(revisions_identical(ref, "rev-a"))
                self.assertFalse(revisions_identical("rev-a", ref))

    def test_a_check_observed_at_head_is_stale_even_when_the_request_was_head(self) -> None:
        scheduler = DiagnosticProviderScheduler()

        outcome = _run_check(scheduler, _request("src/a.py", revision="HEAD"), diagnostics_revision="HEAD")

        self.assertEqual(outcome.outcome, "stale")
        self.assertFalse(diagnostic_outcome_supports_claim(outcome, "fresh_language_diagnostic_check"))

    def test_a_check_observed_at_a_different_revision_is_stale(self) -> None:
        scheduler = DiagnosticProviderScheduler()

        outcome = _run_check(scheduler, _request("src/a.py"), diagnostics_revision="rev-old")

        self.assertEqual(outcome.outcome, "stale")


class ChangedFileScopeTests(unittest.TestCase):
    """A check covers the changed files its provider can actually read."""

    def test_the_scope_partitions_into_provider_files_and_out_of_scope_files(self) -> None:
        scheduler = DiagnosticProviderScheduler()

        ticket = scheduler.begin_check(_request("src/a.py", "src/b.ts"))

        self.assertEqual(ticket.in_scope_files, ("src/a.py",))
        self.assertEqual(ticket.out_of_scope_files, ("src/b.ts",))

    def test_the_record_names_every_file_in_the_requested_scope(self) -> None:
        scheduler = DiagnosticProviderScheduler()

        outcome = _run_check(
            scheduler,
            _request("src/a.py", "src/b.ts"),
            diagnosed_files=("src/a.py",),
        )

        self.assertEqual(outcome.outcome, "ok")
        record = outcome.to_record()
        self.assertEqual(record["changed_files"], ["src/a.py", "src/b.ts"])

    def test_a_file_no_provider_supports_yields_an_unsupported_outcome(self) -> None:
        scheduler = DiagnosticProviderScheduler()

        outcome = _run_check(scheduler, _request("src/only.ts"))

        self.assertEqual(outcome.outcome, "unsupported")
        self.assertEqual(outcome.compatibility, "provider_disabled")
        self.assertEqual(outcome.provider_id, "")

    def test_an_absolute_path_is_refused(self) -> None:
        with self.assertRaises(DiagnosticProviderError) as caught:
            _request("/etc/passwd")
        self.assertIn("workspace-relative", str(caught.exception))

    def test_an_escaping_path_is_refused(self) -> None:
        with self.assertRaises(DiagnosticProviderError):
            _request("../outside.py")

    def test_a_windows_absolute_path_is_refused(self) -> None:
        with self.assertRaises(DiagnosticProviderError):
            _request("C:/Users/dev/a.py")


class MetadataOnlyShapeTests(unittest.TestCase):
    """Everything persistable is metadata; a body has nowhere to ride in."""

    def test_a_diagnostic_carrying_a_message_is_refused_by_key_name(self) -> None:
        with self.assertRaises(DiagnosticProviderError) as caught:
            normalize_diagnostic_item(_item(message="undefined name 'x'"))
        self.assertIn("metadata only", str(caught.exception))

    def test_every_raw_payload_field_name_is_refused(self) -> None:
        for field in RAW_PAYLOAD_FIELD_NAMES:
            with self.subTest(field=field):
                with self.assertRaises(DiagnosticProviderError):
                    normalize_diagnostic_item(_item(**{field: "raw body"}))

    def test_the_persistable_record_carries_no_raw_payload_field(self) -> None:
        outcome = _caller_supplied_outcome(diagnostics=(_item(),))

        record = outcome.to_record()

        self.assertEqual(sorted(record), sorted(DIAGNOSTIC_OUTCOME_RECORD_KEYS))
        self.assertFalse(set(record) & set(RAW_PAYLOAD_FIELD_NAMES))
        self.assertNotIn("message", record)
        self.assertNotIn("prompt", record)

    def test_the_persisted_diagnostic_reuses_the_v1_item_vocabulary(self) -> None:
        record = _caller_supplied_outcome(diagnostics=(_item(),)).to_record()

        items = record["diagnostics"]
        assert isinstance(items, list) and items
        item = items[0]
        assert isinstance(item, dict)
        self.assertEqual(sorted(item), sorted(LANGUAGE_DIAGNOSTIC_ITEM_KEYS))
        # The one `source` field is a provider name, never file content.
        self.assertIn(item["source"], DIAGNOSTIC_PROVIDER_IDS)

    def test_a_diagnostic_outside_the_checked_scope_is_refused(self) -> None:
        with self.assertRaises(DiagnosticProviderError) as caught:
            _caller_supplied_outcome(diagnostics=(_item(path="src/elsewhere.py"),))
        self.assertIn("in_scope_files", str(caught.exception))

    def test_privacy_is_metadata_only(self) -> None:
        self.assertEqual(module.DIAGNOSTIC_PROVIDERS_PRIVACY, "metadata_only")
        for outcome in _every_reachable_outcome().values():
            self.assertEqual(outcome.privacy, "metadata_only")


if __name__ == "__main__":
    unittest.main()
