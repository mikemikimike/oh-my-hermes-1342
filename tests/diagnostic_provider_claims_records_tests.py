"""Claim-boundary and record tests for `diagnostic_providers/v1` (#1297 T1.2).

The one claim a diagnostic outcome can settle, the refusal of every other
one, and the read-path validation that keeps a tampered record from being
read as a clean result.
"""

from __future__ import annotations

import unittest

from _diagnostic_provider_helpers import _caller_supplied_outcome, _every_reachable_outcome, _item
from omh.coding.diagnostic_providers import (
    diagnostic_claim_support,
    diagnostic_outcome_supports_claim,
    validate_diagnostic_outcome_record,
)
from omh.quality.language_diagnostic_evidence import (
    LANGUAGE_DIAGNOSTIC_CLAIMS,
    LANGUAGE_DIAGNOSTIC_CLAIM_BOUNDARY,
    LANGUAGE_DIAGNOSTIC_NOT_EVIDENCE_FOR,
    LANGUAGE_DIAGNOSTIC_SUPPORTABLE_CLAIMS,
)


class ClaimBoundaryTests(unittest.TestCase):
    """A diagnostic outcome settles one claim and refuses every other one."""

    def test_a_fresh_clean_outcome_supports_only_its_own_claim(self) -> None:
        outcome = _every_reachable_outcome()["ok"]

        self.assertTrue(diagnostic_outcome_supports_claim(outcome, "fresh_language_diagnostic_check"))
        for claim in LANGUAGE_DIAGNOSTIC_CLAIMS:
            if claim in LANGUAGE_DIAGNOSTIC_SUPPORTABLE_CLAIMS:
                continue
            with self.subTest(claim=claim):
                self.assertFalse(diagnostic_outcome_supports_claim(outcome, claim))

    def test_no_outcome_of_any_kind_backs_compilation_tests_review_ci_or_merge(self) -> None:
        for name, outcome in _every_reachable_outcome().items():
            for claim in LANGUAGE_DIAGNOSTIC_CLAIMS:
                if claim in LANGUAGE_DIAGNOSTIC_SUPPORTABLE_CLAIMS:
                    continue
                with self.subTest(outcome=name, claim=claim):
                    self.assertFalse(diagnostic_outcome_supports_claim(outcome, claim))

    def test_only_the_ok_outcome_backs_even_its_own_claim(self) -> None:
        for name, outcome in _every_reachable_outcome().items():
            expected = name == "ok"
            with self.subTest(outcome=name):
                self.assertEqual(
                    diagnostic_outcome_supports_claim(outcome, "fresh_language_diagnostic_check"),
                    expected,
                )

    def test_an_unknown_claim_name_is_refused_rather_than_defaulted(self) -> None:
        self.assertFalse(
            diagnostic_outcome_supports_claim(_every_reachable_outcome()["ok"], "everything_is_fine")
        )

    def test_the_record_names_every_claim_it_cannot_settle(self) -> None:
        outcome = _every_reachable_outcome()["ok"]

        self.assertEqual(list(outcome.not_evidence_for), list(LANGUAGE_DIAGNOSTIC_NOT_EVIDENCE_FOR))
        self.assertEqual(outcome.claim_boundary, LANGUAGE_DIAGNOSTIC_CLAIM_BOUNDARY)

    def test_claim_support_partitions_every_claim(self) -> None:
        support = diagnostic_claim_support(_every_reachable_outcome()["ok"])

        self.assertEqual(support["supported_claims"], ["fresh_language_diagnostic_check"])
        self.assertEqual(
            sorted([*support["supported_claims"], *support["unsupported_claims"]]),
            sorted(LANGUAGE_DIAGNOSTIC_CLAIMS),
        )
        stale_support = diagnostic_claim_support(_every_reachable_outcome()["stale"])
        self.assertEqual(stale_support["supported_claims"], [])


class OutcomeRecordTests(unittest.TestCase):
    """The persistable record is validated on the read path too."""

    def test_a_record_round_trips_cleanly(self) -> None:
        record = _caller_supplied_outcome(diagnostics=(_item(),)).to_record()

        self.assertEqual(validate_diagnostic_outcome_record(record), [])

    def test_a_tampered_outcome_field_is_rejected_by_validation(self) -> None:
        record = _every_reachable_outcome()["timeout"].to_record()
        tampered = dict(record, outcome="ok")

        errors = validate_diagnostic_outcome_record(tampered)

        self.assertIn("outcome must be derived", " ".join(errors))

    def test_an_extra_key_is_rejected_by_validation(self) -> None:
        record = _caller_supplied_outcome().to_record()
        extended = dict(record, message="verified")

        errors = validate_diagnostic_outcome_record(extended)

        self.assertIn("unsupported keys", " ".join(errors))

    def test_a_missing_key_is_rejected_by_validation(self) -> None:
        record = _caller_supplied_outcome().to_record()
        reduced = {key: value for key, value in record.items() if key != "outcome"}

        errors = validate_diagnostic_outcome_record(reduced)

        self.assertIn("missing keys", " ".join(errors))

    def test_a_tampered_diagnostic_is_rejected_by_validation(self) -> None:
        record = _caller_supplied_outcome(diagnostics=(_item(),)).to_record()
        tampered = dict(record, diagnostics=[dict(_item(line=13))])

        self.assertNotEqual(validate_diagnostic_outcome_record(tampered), [])

    def test_outcome_ids_are_deterministic(self) -> None:
        first = _caller_supplied_outcome(diagnostics=(_item(),))
        second = _caller_supplied_outcome(diagnostics=(_item(),))
        different = _caller_supplied_outcome(diagnostics=(_item(),), revision="rev-other")

        self.assertEqual(first.outcome_id, second.outcome_id)
        self.assertNotEqual(first.outcome_id, different.outcome_id)
        self.assertRegex(first.outcome_id, r"^diagout-[0-9a-f]{16}$")

    def test_records_from_every_outcome_round_trip_cleanly(self) -> None:
        for name, outcome in _every_reachable_outcome().items():
            with self.subTest(outcome=name):
                self.assertEqual(validate_diagnostic_outcome_record(outcome.to_record()), [])


if __name__ == "__main__":
    unittest.main()
