"""Naming a skill has to work in the language the sentence is written in.

OMH resolves intent two ways. Ordinary prose goes to the router, which scores
candidates and hands ambiguity to model selection -- that is the main path and
this file does not touch it. The other way is naming a skill outright, and on
Slack or Discord there is no slash-command surface, so naming it in a sentence
*is* the explicit path.

That path assumed English word order. `use omh <skill>` needs the name third;
the prefix and bare-first-word forms need it first. Korean puts the verb last,
so `omh wiki 써줘` matched none of them and fell through to trigger scoring,
which is right only when the name happens to be a distinctive token. Measured
across every routable skill before the fix:

    omh <skill> 써줘        81/92
    use the <skill> skill  86/92

The failures were the skills with ordinary names -- the ones a user cannot
rescue by rephrasing.

Three conditions gate the new resolution, and each removed a real overroute
found while building it: a marker word, a run cue, and the name adjacent to the
marker. The guards below are that evidence, not decoration.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.routing.chat import route_chat_message
from omh.routing.policy import explicit_skill_invocation
from omh.skills.catalog import routable_definitions

# `meta-router` is the `/omh` command lane rather than a workflow a user names,
# so it resolves through the prefix path and is excluded from name-form sweeps.
COMMAND_LANE_SKILL = "meta-router"


def _routable_names() -> list[str]:
    return [definition.name for definition in routable_definitions()]


def _named(name: str) -> set[str]:
    return set(_routable_names())


class ExplicitInvocationFormTests(unittest.TestCase):
    """Every naming form resolves every skill, whatever the word order."""

    def _sweep(self, template) -> list[str]:
        return [
            name
            for name in _routable_names()
            if name != COMMAND_LANE_SKILL
            and route_chat_message(template(name)).get("selected_skill") != name
        ]

    def test_korean_verb_final_invocation_resolves_every_skill(self) -> None:
        # The form this was built for: no slash surface, name in a sentence.
        self.assertEqual(self._sweep(lambda name: f"omh {name} 써줘"), [])

    def test_korean_particle_form_resolves_every_skill(self) -> None:
        # Korean attaches particles to the noun: "omh로" rather than "omh".
        self.assertEqual(self._sweep(lambda name: f"omh로 {name} 해줘"), [])

    def test_korean_skill_word_form_resolves_every_skill(self) -> None:
        self.assertEqual(self._sweep(lambda name: f"{name} 스킬 실행해줘"), [])

    def test_english_trailing_skill_word_resolves_every_skill(self) -> None:
        # `use the <skill> skill` puts the name second, not third.
        self.assertEqual(self._sweep(lambda name: f"use the {name} skill"), [])

    def test_the_forms_that_already_worked_still_do(self) -> None:
        self.assertEqual(self._sweep(lambda name: f"use omh {name}"), [])
        self.assertEqual(self._sweep(lambda name: f"/{name}"), [])


class ExplicitInvocationGuardTests(unittest.TestCase):
    """What must never be read as "run this skill"."""

    def test_a_catalog_question_is_not_an_invocation(self) -> None:
        # Marker and skill name both present, and answering it by running the
        # skill is exactly wrong. The missing ingredient is a run cue.
        for message in (
            "does OMH support skill health dashboards?",
            "does OMH support skill candidate scouting?",
            "what is oh-my-hermes?",
        ):
            with self.subTest(message=message):
                self.assertIsNone(explicit_skill_invocation(message, _named(message)))

    def test_an_ordinary_word_that_is_also_a_skill_name_is_not_an_invocation(self) -> None:
        # `loop`, `plan`, `team`, `ask` are ordinary words. A sentence carrying a
        # marker and a cue still does not mean the user named the workflow.
        message = "Run a loop to find and fix OMH router context-loss and coding handoff bugs with progress evidence."
        self.assertIsNone(explicit_skill_invocation(message, _named(message)))

    def test_a_marker_without_a_run_cue_is_not_an_invocation(self) -> None:
        self.assertIsNone(explicit_skill_invocation("omh wiki", _named("omh wiki")))

    def test_a_name_far_from_the_marker_is_not_an_invocation(self) -> None:
        message = "use the tooling we discussed and then think about wiki someday"
        self.assertIsNone(explicit_skill_invocation(message, _named(message)))

    def test_two_names_each_beside_a_marker_are_ambiguity_not_a_choice(self) -> None:
        message = "omh wiki 랑 doctor 스킬 써줘"
        self.assertIsNone(explicit_skill_invocation(message, _named(message)))

    def test_only_the_name_beside_the_marker_is_read_as_the_invocation(self) -> None:
        # Adjacency decides rather than declaring ambiguity here: the user put
        # `wiki` against the marker and `doctor` further along, which is a
        # weaker signal than two names each introduced by their own marker.
        message = "omh wiki doctor 써줘"
        self.assertEqual(explicit_skill_invocation(message, _named(message)), "wiki")

    def test_a_negated_name_is_not_an_invocation(self) -> None:
        for message in ("omh wiki 말고 다른 스킬 써줘", "use the skill instead of wiki"):
            with self.subTest(message=message):
                self.assertIsNone(explicit_skill_invocation(message, _named(message)))

    def test_a_bare_mention_without_a_marker_is_not_an_invocation(self) -> None:
        self.assertIsNone(explicit_skill_invocation("자 이제 실행해줘", _named("자 이제 실행해줘")))


class MaintenanceCommandBoundaryTests(unittest.TestCase):
    """`omh <command>` and `omh <skill>` are different requests.

    The maintenance card matches by alias substring, so it also claimed the four
    skills whose own names contain one: `codegraph-refresh` reads as `refresh`,
    `model-setup` and `websearch-setup` as `setup`, `skill-health` as `health`.
    Naming any of them ran the maintenance path instead of the workflow.
    """

    def _route(self, message: str) -> str:
        return str(route_chat_message(message).get("selected_skill"))

    def test_a_skill_whose_name_contains_a_command_alias_wins(self) -> None:
        for name in ("codegraph-refresh", "model-setup", "websearch-setup", "skill-health"):
            with self.subTest(skill=name):
                self.assertEqual(self._route(f"omh {name} 써줘"), name)

    def test_the_real_maintenance_commands_still_route_to_maintenance(self) -> None:
        for message, expected in (
            ("omh doctor", "doctor"),
            ("omh update", "oh-my-hermes"),
            ("omh setup", "oh-my-hermes"),
            ("omh list", "oh-my-hermes"),
            ("omh 업데이트 해줘", "oh-my-hermes"),
        ):
            with self.subTest(message=message):
                self.assertEqual(self._route(message), expected)

    def test_the_prefixed_command_lane_is_left_alone(self) -> None:
        # `./omh update` resolves through the `/omh` alias to the command lane;
        # that is not a user naming a different workflow to run instead.
        for message in ("./omh update", "/omh update"):
            with self.subTest(message=message):
                self.assertEqual(self._route(message), "oh-my-hermes")


class KoreanCueFoldingTests(unittest.TestCase):
    """Both sides of a Korean comparison must be folded the same way.

    `normalized_phrase` decomposes Hangul to jamo, so a composed literal never
    matches a folded message. This shipped once doing nothing at all for every
    Korean cue, and the symptom was silence rather than an error.
    """

    def test_a_korean_run_cue_is_recognised(self) -> None:
        self.assertEqual(explicit_skill_invocation("omh wiki 써줘", _named("omh wiki 써줘")), "wiki")

    def test_an_english_run_cue_is_recognised(self) -> None:
        self.assertEqual(explicit_skill_invocation("use the wiki skill", _named("x")), "wiki")


if __name__ == "__main__":
    unittest.main()
