"""Global language policy for routing.

OMH targets a global audience with English as the primary language, but its
deterministic trigger tables only ever grew in Latin and Hangul. These tests
make that state explicit and hold it still: they re-derive the distribution
from the catalog so it cannot drift silently, and they freeze each skill's
Hangul table so growing one becomes a deliberate act with a visible number to
change rather than an incremental habit. The freeze is per skill rather than a
global sum because a new skill carrying its own Korean triggers and an existing
skill's table being padded are different events, and a total cannot tell them
apart.

The policy being enforced: per-language trigger tables do not scale to a global
product, so non-English intent resolution belongs to model selection over
supplied candidates, not to more tokens. See `src/routing/input_language.py`.
"""

from __future__ import annotations

import collections
import unittest

from omh.routing.input_language import (
    SCRIPT_HAN,
    SCRIPT_HANGUL,
    SCRIPT_KANA,
    SCRIPT_LATIN,
    SUPPORT_MODEL_SELECTION_REQUIRED,
    SUPPORT_TRIGGER_BACKED,
    TRIGGER_BACKED_SCRIPTS,
    detect_input_script,
    routing_input_language,
    routing_language_support,
)
from omh.skills.catalog import routable_definitions


# Frozen per skill on 2026-07-27, not as a global total.
#
# The first version of this gate froze the sum, and it fired on the very next
# merge: three new skills arrived carrying their own Korean triggers and the
# total moved 766 -> 774. That is not the habit worth stopping. A new skill
# paying for its own triggers is proportional work; padding an existing skill's
# Korean table to paper over a routing miss is the unbounded one, and a sum
# cannot tell the two apart.
#
# So the freeze is per skill, and only for skills that existed at freeze time.
# A new skill is exempt here and constrained instead by
# `test_every_routable_skill_is_reachable_in_english`. Raising an entry below
# means an existing Korean table grew: do it only with a stated reason, and
# never to make a routing miss go away -- the fix for that is model selection,
# not more tokens. See `src/routing/input_language.py`.
FROZEN_HANGUL_TRIGGERS_BY_SKILL: dict[str, int] = {
    "accessibility-audit": 11,
    "achievements": 5,
    "agent-board": 13,
    "agent-debug": 7,
    "agent-evaluation": 4,
    "agent-ops-review": 18,
    "ai-slop-cleaner": 5,
    "ask": 2,
    "automation-blueprint": 15,
    "browser-operator": 15,
    "build-failure-triage": 8,
    "code-review": 7,
    "codebase-onboarding": 5,
    "codegraph-refresh": 6,
    "command-operator": 10,
    "connector-operator": 14,
    "content-operator": 12,
    "context-budget-review": 4,
    "cto-loop": 6,
    "data-analysis": 13,
    "deep-interview": 5,
    # 2026-07-27: bare "자료" removed - a generic research-shaded noun that stole
    # reference/data-finding prompts from the research lane via substring phrase
    # match; "첨부"/"전달" phrases still cover the deliverables intent.
    "deliverable-package": 3,
    "deploy-and-monitor": 9,
    "design-orchestration": 4,
    "design-quality-gate": 5,
    "executor-runtime-readiness": 16,
    "external-connector-readiness": 24,
    "failure-signal-audit": 10,
    "feedback-triage": 12,
    "frontend": 16,
    "gateway-intent-card": 10,
    "github-event-ops": 9,
    "harness-session-inventory": 10,
    "idea-to-deploy": 8,
    "img-summary": 55,
    "instinct-ledger": 6,
    "live-info-operator": 13,
    "loop": 8,
    "materials-package": 27,
    "media-input-operator": 19,
    "meeting-brief": 7,
    "memory-new": 7,
    "memory-sync": 25,
    "model-setup": 5,
    "morning-brief": 4,
    "oh-my-hermes": 2,
    "operating-rhythm": 7,
    "ops-observability-card": 9,
    "ops-review": 7,
    "paper-learning": 10,
    "parallel-tools": 4,
    "physical-device-readiness": 7,
    "plan": 8,
    "production-audit": 5,
    "prompt-import-readiness": 6,
    "ralplan": 11,
    "reliability-review": 9,
    "report-package": 9,
    "research-brief": 5,
    "research-department": 7,
    "rules-distill": 4,
    "security-safety-review": 5,
    "skill-health": 6,
    "skill-scout": 13,
    "source-finder": 8,
    "strategy-brief": 6,
    "toolbelt-readiness": 5,
    "ultragoal": 4,
    "ultraprocess": 19,
    "ultraqa": 5,
    "verification-gate": 5,
    "visual-qa": 17,
    "voice-operator": 12,
    "web-research": 15,
    "websearch-setup": 4,
    "wiki": 7,
    "workflow-learning": 11,
    "workspace-audit": 4,
    "workspace-file-operator": 12,
}


def _hangul_triggers_by_skill() -> dict[str, int]:
    return {
        definition.name: sum(1 for trigger in definition.triggers if detect_input_script(trigger) == SCRIPT_HANGUL)
        for definition in routable_definitions()
        if any(detect_input_script(trigger) == SCRIPT_HANGUL for trigger in definition.triggers)
    }


def _trigger_script_counts() -> collections.Counter[str]:
    counts: collections.Counter[str] = collections.Counter()
    for definition in routable_definitions():
        for trigger in definition.triggers:
            counts[detect_input_script(trigger)] += 1
    return counts


class RoutingLanguagePolicyTests(unittest.TestCase):
    def test_no_existing_korean_trigger_table_grows(self) -> None:
        observed = _hangul_triggers_by_skill()

        for skill, frozen in sorted(FROZEN_HANGUL_TRIGGERS_BY_SKILL.items()):
            with self.subTest(skill=skill):
                self.assertLessEqual(observed.get(skill, 0), frozen)

    def test_a_new_skill_may_carry_its_own_korean_triggers(self) -> None:
        # The exemption is deliberate and bounded: a skill absent from the freeze
        # is new, and its Korean triggers are its own cost rather than growth of
        # an existing table. It still has to be reachable in English.
        observed = _hangul_triggers_by_skill()
        new_skills = set(observed) - set(FROZEN_HANGUL_TRIGGERS_BY_SKILL)

        for skill in sorted(new_skills):
            with self.subTest(skill=skill):
                self.assertGreater(observed[skill], 0)

    def test_only_latin_and_hangul_carry_a_real_trigger_table(self) -> None:
        counts = _trigger_script_counts()

        # Han and Kana entries exist but are incidental (single-digit), which is
        # exactly why they are not claimed as trigger-backed: a handful of tokens
        # cannot resolve ordinary Japanese or Chinese requests.
        self.assertGreater(counts[SCRIPT_LATIN], 1000)
        self.assertGreater(counts[SCRIPT_HANGUL], 100)
        self.assertLess(counts[SCRIPT_HAN], 20)
        self.assertLess(counts[SCRIPT_KANA], 20)
        self.assertEqual(set(TRIGGER_BACKED_SCRIPTS), {SCRIPT_LATIN, SCRIPT_HANGUL})

    def test_every_routable_skill_is_reachable_in_english(self) -> None:
        missing = [
            definition.name
            for definition in routable_definitions()
            if not any(detect_input_script(trigger) == SCRIPT_LATIN for trigger in definition.triggers)
        ]

        self.assertEqual(missing, [])

    def test_a_latin_sentence_is_latin(self) -> None:
        self.assertEqual(detect_input_script("why is the build failing on main?"), SCRIPT_LATIN)

    def test_a_product_name_does_not_make_a_korean_request_latin(self) -> None:
        # Product names, commands, and identifiers stay Latin inside otherwise
        # non-Latin sentences, so a Latin majority must not win the vote.
        self.assertEqual(detect_input_script("Claude Code로 바로 열어줘"), SCRIPT_HANGUL)

    def test_scripts_without_a_trigger_table_are_marked_model_selection(self) -> None:
        for message, expected_script in (
            ("ビルドが失敗した理由を教えて", SCRIPT_KANA),
            ("为什么构建失败了", SCRIPT_HAN),
        ):
            with self.subTest(message=message):
                script = detect_input_script(message)
                self.assertEqual(script, expected_script)
                self.assertEqual(routing_language_support(script), SUPPORT_MODEL_SELECTION_REQUIRED)

    def test_trigger_backed_scripts_report_trigger_support(self) -> None:
        for message in ("refactor this module", "빌드 실패 원인 봐줘"):
            with self.subTest(message=message):
                self.assertEqual(routing_language_support(detect_input_script(message)), SUPPORT_TRIGGER_BACKED)

    def test_routing_input_language_states_the_boundary(self) -> None:
        payload = routing_input_language("ビルドが失敗した理由を教えて")

        self.assertEqual(payload["schema_version"], "routing_input_language/v1")
        self.assertEqual(payload["script"], SCRIPT_KANA)
        self.assertEqual(payload["trigger_support"], SUPPORT_MODEL_SELECTION_REQUIRED)
        self.assertIn("not evidence of intent", str(payload["boundary"]))


if __name__ == "__main__":
    unittest.main()
