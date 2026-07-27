"""Undecidable routes hand their shortlist to model selection.

The deterministic router keeps every confident route. These tests pin the other
half: a tie, a near-tie, a low-confidence score, or a script the trigger tables
do not cover must produce candidates for the model to choose from instead of a
picker or a bare fallback.
"""

from __future__ import annotations

import unittest

from omh.routing.candidate_handoff import (
    CANDIDATE_HANDOFF_SCHEMA_VERSION,
    MAX_CANDIDATES,
    REASON_LOW_CONFIDENCE,
    REASON_NARROW_SCORE_GAP,
    REASON_NO_TRIGGER_COVERAGE,
    build_candidate_handoff,
    candidate_handoff_digest,
)
from omh.routing.chat import route_chat_message


class CandidateHandoffTests(unittest.TestCase):
    def test_a_confident_route_carries_no_handoff(self) -> None:
        route = route_chat_message("why is the build failing on main?", source="generic", limit=3)

        self.assertEqual(route["action"], "dispatch")
        self.assertIsNone(route.get("candidate_handoff"))

    def test_a_scoring_tie_hands_the_shortlist_over(self) -> None:
        # Two skills scored 9 apiece here, so the picker was standing in for a
        # decision the scorer could not make.
        route = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=3)
        handoff = route["candidate_handoff"]

        self.assertEqual(route["action"], "clarify")
        self.assertEqual(handoff["schema_version"], CANDIDATE_HANDOFF_SCHEMA_VERSION)
        self.assertIn(REASON_NARROW_SCORE_GAP, handoff["reasons"])
        self.assertIn("code-review", [candidate["skill"] for candidate in handoff["candidates"]])
        self.assertEqual(handoff["selector"], "hermes")

    def test_a_script_without_trigger_coverage_hands_over(self) -> None:
        route = route_chat_message("ビルドが失敗した理由を教えて", source="generic", limit=3)
        handoff = route["candidate_handoff"]

        self.assertIn(REASON_NO_TRIGGER_COVERAGE, handoff["reasons"])
        self.assertIn(REASON_LOW_CONFIDENCE, handoff["reasons"])

    def test_every_candidate_carries_its_reason_and_evidence_boundary(self) -> None:
        route = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=3)

        for candidate in route["candidate_handoff"]["candidates"]:
            with self.subTest(skill=candidate["skill"]):
                self.assertTrue(candidate["skill"])
                self.assertTrue(candidate["why_it_matched"])
                self.assertTrue(candidate["next_action"])
                self.assertTrue(candidate["evidence_boundary"])

    def test_the_candidate_set_is_bounded(self) -> None:
        route = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=8)

        self.assertLessEqual(route["candidate_handoff"]["candidate_count"], MAX_CANDIDATES)

    def test_the_handoff_is_reproducible(self) -> None:
        first = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=3)["candidate_handoff"]
        second = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=3)["candidate_handoff"]

        self.assertEqual(first["digest"], second["digest"])

    def test_the_digest_tracks_the_shortlist_not_the_scores(self) -> None:
        reasons = (REASON_NARROW_SCORE_GAP,)
        low = candidate_handoff_digest([{"skill": "code-review", "score": 9}], reasons)
        high = candidate_handoff_digest([{"skill": "code-review", "score": 41}], reasons)
        other = candidate_handoff_digest([{"skill": "verification-gate", "score": 9}], reasons)

        self.assertEqual(low, high)
        self.assertNotEqual(low, other)

    def test_an_empty_shortlist_points_at_the_catalog_index(self) -> None:
        route = {
            "action": "fallback",
            "confidence": "low",
            "recommendations": [],
            "input_language": {"trigger_support": "model_selection_required"},
        }
        handoff = build_candidate_handoff(route)

        self.assertEqual(handoff["candidate_count"], 0)
        self.assertEqual(handoff["catalog_reference"], "references/catalog-index.md")
        self.assertIn("catalog-index", str(handoff["question"]))

    def test_the_handoff_never_claims_a_decision(self) -> None:
        route = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=3)

        self.assertIn("not a routing decision", route["candidate_handoff"]["claim_boundary"])


class CodingLaneTests(unittest.TestCase):
    """An implementation-shaped request gets the coding lane, not scorer noise.

    Observed live: "...백엔드 구현해줘" reached model selection carrying
    instinct-ledger, materials-package, and memory-new at score 3 -- decomposed
    -token noise -- while the engines that deliver coding work (ultraprocess,
    team, ultragoal) never surfaced. The same session's picker offered
    idea-to-deploy and planning flows for what was an implementation ask.
    """

    LANE = ["ultraprocess", "team", "ultragoal", "executor-runtime-readiness"]

    def _handoff(self, message: str) -> dict:
        from omh.routing.chat import route_chat_message

        return route_chat_message(message, source="slack").get("candidate_handoff") or {}

    def test_the_observed_failure_now_yields_the_coding_lane(self) -> None:
        handoff = self._handoff(
            "document-harness에서 프로젝트 링크만 주면 observer 결과를 자동 조회하게 백엔드 구현해줘"
        )
        self.assertEqual([c["skill"] for c in handoff["candidates"]], self.LANE)
        self.assertIn("implementation_shaped_request", handoff["reasons"])
        self.assertIn("Do not route implementation work to planning-only flows", handoff["question"])

    def test_english_implementation_asks_get_the_same_lane(self) -> None:
        handoff = self._handoff("implement the backend for observer lookup")
        self.assertEqual([c["skill"] for c in handoff["candidates"]], self.LANE)

    def test_a_strong_match_keeps_its_own_shortlist(self) -> None:
        # The lane replaces noise, never signal: a real trigger match must not
        # be displaced by generic coding candidates.
        from omh.routing.chat import route_chat_message

        route = route_chat_message("기억이 잘못 저장된 것 같아 확인해줘", source="slack")
        self.assertEqual(route["action"], "dispatch")
        self.assertNotIn("candidate_handoff", route)

    def test_non_coding_weak_requests_do_not_get_the_lane(self) -> None:
        handoff = self._handoff("점심 뭐 먹을까 추천해줘")
        skills = [c["skill"] for c in handoff.get("candidates", [])]
        self.assertNotEqual(skills, self.LANE)
        self.assertNotIn("implementation_shaped_request", handoff.get("reasons", []))

    def test_lane_candidates_carry_the_routing_only_boundary(self) -> None:
        handoff = self._handoff("implement the backend for observer lookup")
        for candidate in handoff["candidates"]:
            self.assertIn("routing input only", candidate["evidence_boundary"])


class WrapperPathParityTests(unittest.TestCase):
    """The messenger path sees the same enriched route as a direct call.

    Found by a mocked Slack QA pass: `_public_chat_route_payload_cached` called
    the raw cached decision directly, so the wrapper contract -- and therefore
    every messenger behind `omh_interact` -- never received `input_language`,
    the model-selection `candidate_handoff`, or skill governance. The
    candidate-handoff feature was invisible on the one surface it was built
    for.
    """

    MESSAGE = "document-harness에서 프로젝트 링크만 주면 observer 결과를 자동 조회하게 백엔드 구현해줘"

    def test_the_public_payload_carries_the_handoff_and_language(self) -> None:
        from omh.routing.chat import public_chat_route_payload

        route = public_chat_route_payload(self.MESSAGE, source="slack")
        handoff = route.get("candidate_handoff") or {}
        self.assertEqual(
            [candidate["skill"] for candidate in handoff.get("candidates", [])],
            ["ultraprocess", "team", "ultragoal", "executor-runtime-readiness"],
        )
        self.assertIn("input_language", route)

    def test_the_real_plugin_tool_route_matches_the_direct_route(self) -> None:
        import json as jsonlib
        import os
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from omh.plugin_bundle.omh.tools.chat_tool import omh_interact_handler
        from omh.routing.chat import route_chat_message

        direct = route_chat_message(self.MESSAGE, source="slack")
        direct_lane = [c["skill"] for c in (direct.get("candidate_handoff") or {}).get("candidates", [])]
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
                out = jsonlib.loads(
                    omh_interact_handler(
                        {
                            "message": self.MESSAGE,
                            "source": "slack",
                            "record_session": False,
                            "omh_home": str(root / ".omh"),
                            "hermes_home": str(root / ".hermes"),
                        }
                    )
                )
        tool_route = out.get("route") or {}
        tool_lane = [c["skill"] for c in (tool_route.get("candidate_handoff") or {}).get("candidates", [])]
        self.assertEqual(tool_lane, direct_lane)
        self.assertIn("input_language", tool_route)


if __name__ == "__main__":
    unittest.main()
