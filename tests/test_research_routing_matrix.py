"""Regression matrix for research-lane routing.

Derived from a 31-prompt bilingual probe audit (2026-07-27) that found nine
misroutes for realistic reference/data-finding, docs-inquiry, and vendor-
comparison requests. These fixtures lock the corrected behavior:

- English research phrasings dispatch to the intended research skill.
- Korean phrasings that previously surfaced FALSE candidates (visual-qa via
  the generic token "문제", deliverable-package via the bare trigger "자료",
  parallel-tools via "확인해줘") no longer do. Per the routing language policy
  (docs/DIRECTION.md), Korean misses are not fixed by growing trigger tables;
  the locked contract here is "no false deterministic candidate", with intent
  resolution left to model selection over supplied candidates.
- Negative controls stay in their non-research lanes.
"""

from __future__ import annotations

import unittest

from omh.routing.chat import route_chat_message


DISPATCH_CASES: tuple[tuple[str, str], ...] = (
    ("이 문제 해결을 위해 참고할만한 데이터 찾아줘", "source-finder"),
    ("자료 찾아줘", "web-research"),
    ("참고자료 찾아줘", "web-research"),
    ("이 논문 PDF를 쉽게 설명해줘", "paper-learning"),
    ("이 주제의 논문과 데이터셋을 찾아줘", "source-finder"),
    ("find datasets for browser agent benchmarks", "source-finder"),
    ("what do the docs say about OAuth PKCE?", "best-practice-research"),
    ("check the official docs for the current API migration", "best-practice-research"),
    ("find best practices for browser performance", "best-practice-research"),
    ("compare onboarding analytics vendors", "research-brief"),
    (
        "compare three onboarding analytics vendors using customer notes and confidence gaps",
        "research-brief",
    ),
    ("what is the current weather in Seoul?", "live-info-operator"),
)

# Prompts that previously surfaced a false deterministic candidate. The locked
# contract is candidate hygiene, not dispatch: no non-research skill may be
# offered for these research-shaped requests.
NO_FALSE_CANDIDATE_CASES: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "문제 해결에 참고할 자료/데이터 찾아줘",
        frozenset({"visual-qa", "deliverable-package", "parallel-tools", "ultraprocess"}),
    ),
    (
        "관련 자료와 데이터를 찾아줘",
        frozenset({"visual-qa", "deliverable-package", "parallel-tools", "ultraprocess"}),
    ),
    (
        "공식 문서에서 OAuth PKCE를 확인해줘",
        frozenset({"visual-qa", "deliverable-package", "parallel-tools", "ultraprocess"}),
    ),
)

# Weak-but-correct: candidate must stay in the research lane even when the
# score stays below the dispatch threshold.
CANDIDATE_CASES: tuple[tuple[str, str], ...] = (
    ("레퍼런스 조사해줘", "web-research"),
)

NEGATIVE_CONTROLS: tuple[tuple[str, str], ...] = (
    ("check this checkout page for visual regressions", "visual-qa"),
    ("fix the checkout bug in our app", "ultraprocess"),
    ("create a slide deck from these meeting notes", "materials-package"),
    ("evaluate agent performance on the benchmark suite", "performance-goal"),
    ("triage this customer feedback backlog", "feedback-triage"),
    ("analyze this CSV and summarize anomalies", "data-analysis"),
    ("발표 자료로 만들어줘", "materials-package"),
)

RESEARCH_SKILLS = frozenset(
    {
        "web-research",
        "source-finder",
        "best-practice-research",
        "research-brief",
        "research-department",
        "paper-learning",
        "autoresearch-goal",
    }
)


class ResearchRoutingMatrixTest(unittest.TestCase):
    def test_research_prompts_dispatch_to_expected_skill(self) -> None:
        for prompt, expected_skill in DISPATCH_CASES:
            with self.subTest(prompt=prompt):
                decision = route_chat_message(prompt)
                self.assertEqual(decision.get("action"), "dispatch", decision)
                self.assertEqual(decision.get("selected_skill"), expected_skill, decision)

    def test_research_shaped_prompts_never_surface_false_candidates(self) -> None:
        for prompt, forbidden in NO_FALSE_CANDIDATE_CASES:
            with self.subTest(prompt=prompt):
                decision = route_chat_message(prompt)
                self.assertNotIn(decision.get("selected_skill"), forbidden, decision)
                self.assertNotIn(decision.get("candidate_skill"), forbidden, decision)
                self.assertNotEqual(decision.get("action"), "dispatch_non_research", decision)

    def test_below_threshold_research_prompts_keep_research_candidates(self) -> None:
        for prompt, expected_candidate in CANDIDATE_CASES:
            with self.subTest(prompt=prompt):
                decision = route_chat_message(prompt)
                self.assertEqual(decision.get("candidate_skill"), expected_candidate, decision)

    def test_negative_controls_stay_out_of_the_research_lane(self) -> None:
        for prompt, expected_skill in NEGATIVE_CONTROLS:
            with self.subTest(prompt=prompt):
                decision = route_chat_message(prompt)
                self.assertEqual(decision.get("selected_skill"), expected_skill, decision)
                self.assertNotIn(decision.get("selected_skill"), RESEARCH_SKILLS, decision)

    def test_deliverables_lane_still_reachable_after_trigger_cleanup(self) -> None:
        decision = route_chat_message("자료 첨부해줘")
        self.assertEqual(decision.get("candidate_skill"), "deliverable-package", decision)


if __name__ == "__main__":
    unittest.main()
