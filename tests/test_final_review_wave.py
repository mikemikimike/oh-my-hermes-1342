from __future__ import annotations

import itertools
import unittest

from _local_package import load_local_package

load_local_package()
from omh.coding.final_review_wave import (
    LANE_ORDER,
    FinalReviewWave,
    ImmutableRevision,
    IntegrationReceipt,
    LaneBudgetReservationInput,
    LaneObservation,
    LaneState,
    ReviewLens,
    WaveAssessment,
    WaveVerdict,
    prepare_final_review_wave,
    prepare_remediated_wave,
)


def _reservations(*, unavailable: ReviewLens | None = None) -> tuple[LaneBudgetReservationInput, ...]:
    return tuple(
        LaneBudgetReservationInput(lens, limit=1, reserved=1 if lens == unavailable else 0)
        for lens in LANE_ORDER
    )


def _integrated_wave() -> FinalReviewWave:
    return prepare_final_review_wave("wave-1", _reservations()).integrate(
        IntegrationReceipt(ImmutableRevision("a" * 40), completed=True)
    )


class FinalReviewWaveTests(unittest.TestCase):
    def test_at_least_three_read_only_lanes_are_eligible_concurrently_only_after_integration(self) -> None:
        prepared = prepare_final_review_wave("wave-1", _reservations())

        self.assertEqual(prepared.eligible_lanes(), ())

        integrated = prepared.integrate(IntegrationReceipt(ImmutableRevision("a" * 40), completed=True))

        self.assertEqual(integrated.eligible_lanes(), LANE_ORDER)
        self.assertTrue(all(not lane.read_only.allows_mutation for lane in integrated.lanes))
        self.assertTrue(all(lane.bound_revision == ImmutableRevision("a" * 40) for lane in integrated.lanes))

    def test_revision_mismatch_marks_the_exact_lane_stale_and_blocks(self) -> None:
        wave = _integrated_wave().observe(
            LaneObservation(ReviewLens.QUALITY, LaneState.COMPLETED, ImmutableRevision("b" * 40))
        )

        quality = next(lane for lane in wave.lanes if lane.lens == ReviewLens.QUALITY)
        self.assertEqual(quality.state, LaneState.STALE)
        self.assertEqual(wave.assess().verdict, WaveVerdict.BLOCK)
        self.assertEqual(wave.assess().blocking_lens, ReviewLens.QUALITY)

    def test_missing_real_surface_blocks_with_its_exact_lens(self) -> None:
        wave = _integrated_wave().observe(
            LaneObservation(ReviewLens.REAL_SURFACE, LaneState.MISSING, ImmutableRevision("a" * 40))
        )

        self.assertEqual(wave.assess().verdict, WaveVerdict.BLOCK)
        self.assertEqual(wave.assess().blocking_lens, ReviewLens.REAL_SURFACE)

    def test_completion_permutations_have_the_same_pass_assessment(self) -> None:
        observations = tuple(
            LaneObservation(lens, LaneState.COMPLETED, ImmutableRevision("a" * 40))
            for lens in LANE_ORDER
        )

        verdicts = set()
        for order in itertools.permutations(observations):
            wave = _integrated_wave()
            for observation in order:
                wave = wave.observe(observation)
            verdicts.add(wave.assess())

        self.assertEqual(verdicts, {WaveAssessment(WaveVerdict.PASS, None)})

    def test_remediation_invalidates_old_wave_and_requires_a_new_revision_and_wave(self) -> None:
        prior = _integrated_wave().invalidate_for_remediation()
        replacement = prepare_remediated_wave(prior, "wave-2", _reservations()).integrate(
            IntegrationReceipt(ImmutableRevision("b" * 40), completed=True)
        )

        self.assertEqual(prior.assess().verdict, WaveVerdict.BLOCK)
        self.assertNotEqual(prior.wave_id, replacement.wave_id)
        self.assertNotEqual(prior.integration, replacement.integration)

    def test_prepared_lane_status_never_claims_execution(self) -> None:
        projection = _integrated_wave().project_status()

        self.assertEqual(
            [lane.execution_status for lane in projection.lanes],
            ["prepared_not_executed"] * len(LANE_ORDER),
        )

    def test_exhausted_typed_reservation_blocks_its_exact_lane(self) -> None:
        wave = prepare_final_review_wave("wave-1", _reservations(unavailable=ReviewLens.SAFETY)).integrate(
            IntegrationReceipt(ImmutableRevision("a" * 40), completed=True)
        )

        self.assertEqual(wave.assess().verdict, WaveVerdict.BLOCK)
        self.assertEqual(wave.assess().blocking_lens, ReviewLens.SAFETY)
