from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.paths import resolve_paths
from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.profiles.setup import write_setup_profile
from omh.routing.action_copy import NEXT_ACTION_LABELS
from omh.routing.executor_cues import (
    NAMED_CODING_AGENT_PHRASES,
    OMO_RUNTIME_CODING_AGENT_PHRASES,
    SUBSTRING_NAMED_CODING_AGENT_PHRASES,
)
from omh.routing.coding_route_actions import (
    CODING_ROUTE_LANE_NEXT_ACTION,
    CODING_ROUTE_NEXT_ACTIONS,
    COMPATIBLE_ROUTE_NEXT_ACTION,
    NAMED_EXECUTOR_NEXT_ACTION,
    RECORDED_OWNER_NEXT_ACTION,
    USER_CHOICE_NEXT_ACTION,
    named_coding_agent_phrase_parity,
    resolve_coding_route_decision,
)
from omh.routing.localization import normalized_phrase
from omh.routing.owner_preference import (
    empty_owner_preference_state,
    record_accepted_explicit_choice,
)
from omh.wrapper.contract import build_chat_interaction_payload


# One message per coding-delivery route-hint site. Direct `ultraprocess`, broad
# `coding_delivery`, and `test_until_pass_delivery` have to answer the coding-owner
# question the same way, so they are asserted together rather than one by one.
CODING_DELIVERY_SITE_MESSAGES: tuple[tuple[str, str], ...] = (
    ("direct_workflow_invocation", "Use OMH ultraprocess for: improve README and open PR"),
    ("coding_delivery", "implement the dark mode toggle and open a pr"),
    ("test_until_pass_delivery", "테스트 통과할때까지 고쳐줘"),
)

# Overroute guards: advisor, customer-signal, and executor-comparison requests. None of
# them is an unambiguous delivery request, so none of them may auto-select a coding owner.
NON_CODING_DELIVERY_MESSAGES: tuple[tuple[str, str], ...] = (
    ("advisor", "ask claude for a second opinion on this plan"),
    ("customer_signal", "users report a bug in the checkout page"),
    ("customer_signal_ko", "고객들이 결제 실패 이슈를 계속 제보해요"),
    ("executor_comparison", "should i use codex or claude code for this?"),
)

# Customer-signal work stays on the feedback lane, so it never reaches a coding-owner
# decision at all. Kept separate because awareness has no advisor lane of its own.
CUSTOMER_SIGNAL_MESSAGES: tuple[str, ...] = (
    "users report a bug in the checkout page",
    "고객들이 결제 실패 이슈를 계속 제보해요",
)


def _decision(message: str, **kwargs: str):
    return resolve_coding_route_decision(normalized_phrase(message), **kwargs)


def _learned_owner_state(owner: str = "codex") -> dict[str, object]:
    state = empty_owner_preference_state()
    for index in range(3):
        state = record_accepted_explicit_choice(
            state,
            route_family="ulw-coding-delivery",
            selected_owner=owner,
            occurred_at=f"2026-08-13T00:00:0{index + 1}Z",
        )
    return state


def _load_standalone_bundle_awareness():
    """Load the vendored bundle's awareness module outside the omh package.

    Standalone plugin hosts import the bundle without `omh.*` on the path, so
    `from ...routing.executor_cues import ...` raises ImportError there and the
    module runs on its vendored fallback tuples. Loading the bundle the same
    way here makes those fallbacks — not the re-exported source constants —
    the values under test.
    """
    module_name = "_test_omh_standalone_bundle"
    for name in list(sys.modules):
        if name == module_name or name.startswith(f"{module_name}."):
            sys.modules.pop(name, None)
    bundle_dir = Path(__file__).resolve().parents[1] / "src" / "plugin_bundle" / "omh"
    spec = importlib.util.spec_from_file_location(
        module_name,
        bundle_dir / "__init__.py",
        submodule_search_locations=[str(bundle_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load the vendored plugin bundle standalone")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return importlib.import_module(f"{module_name}.awareness")


class CodingRouteActionVocabularyTests(unittest.TestCase):
    def test_four_states_resolve_to_four_distinct_next_actions(self) -> None:
        named = _decision("use codex to fix the login bug")
        recorded = _decision("implement the dark mode toggle and open a pr", recorded_owner="claude-code")
        automatic = _decision("implement the dark mode toggle in a worktree with parallel workers")
        fallback = _decision("implement the dark mode toggle and open a pr")

        self.assertEqual(named.next_action, NAMED_EXECUTOR_NEXT_ACTION)
        self.assertEqual(recorded.next_action, RECORDED_OWNER_NEXT_ACTION)
        self.assertEqual(automatic.next_action, COMPATIBLE_ROUTE_NEXT_ACTION)
        self.assertEqual(fallback.next_action, USER_CHOICE_NEXT_ACTION)

        actions = {named.next_action, recorded.next_action, automatic.next_action, fallback.next_action}
        self.assertEqual(len(actions), 4)
        self.assertEqual(actions, set(CODING_ROUTE_NEXT_ACTIONS))

    def test_every_coding_route_action_has_a_route_label(self) -> None:
        for action in CODING_ROUTE_NEXT_ACTIONS:
            with self.subTest(action=action):
                self.assertIn(action, NEXT_ACTION_LABELS)
                self.assertTrue(NEXT_ACTION_LABELS[action].strip())
        self.assertIn(CODING_ROUTE_LANE_NEXT_ACTION, NEXT_ACTION_LABELS)

    def test_owner_phrase_groups_still_cover_the_policy_executor_names(self) -> None:
        self.assertTrue(named_coding_agent_phrase_parity())

    def test_vendored_awareness_fallback_matches_the_executor_name_policy(self) -> None:
        # The bundle's ImportError fallback is a copy, not a re-export, so it
        # drifts silently when `NAMED_CODING_AGENT_PHRASES` gains a phrase.
        # Tuple equality (order included) keeps the standalone plugin host and
        # the source routing policy recognising exactly the same names.
        awareness = _load_standalone_bundle_awareness()

        self.assertEqual(awareness._NAMED_CODING_AGENT_PHRASES, NAMED_CODING_AGENT_PHRASES)
        self.assertEqual(
            awareness._SUBSTRING_NAMED_CODING_AGENT_PHRASES,
            SUBSTRING_NAMED_CODING_AGENT_PHRASES,
        )
        self.assertEqual(
            awareness._OMO_RUNTIME_CODING_AGENT_PHRASES,
            OMO_RUNTIME_CODING_AGENT_PHRASES,
        )

    def test_vendored_awareness_delivery_signal_applies_the_boundary_rule(self) -> None:
        # The vendored delivery signal must reject the same embedded-substring
        # shapes the source surfaces reject, and keep the pi-family positives,
        # in both the standalone (ImportError fallback) and in-repo modules.
        from omh.plugin_bundle.omh import awareness as bundled

        for awareness in (_load_standalone_bundle_awareness(), bundled):
            signal = awareness._named_coding_agent_delivery_signal
            self.assertTrue(signal("tell pi to fix the flaky test", {"fix"}))
            self.assertTrue(signal("opencode로 이 버그 고쳐줘", set()))
            self.assertFalse(signal("promo runtime 로그 확인하는 코드 짜줘", set()))
            self.assertFalse(signal("api한테 요청 보내는 코드 짜줘", set()))

    def test_automatic_route_carries_source_reason_and_confidence(self) -> None:
        automatic = _decision("implement the dark mode toggle in a worktree with parallel workers")

        self.assertEqual(automatic.source, "request_capability_match")
        self.assertEqual(automatic.confidence, "medium")
        self.assertEqual(automatic.selected_route_family, "runtime_handoff")
        self.assertTrue(automatic.reason.strip())
        self.assertTrue(automatic.matched_cues)
        self.assertFalse(automatic.choice_required)
        # An automatic route names a compatible handoff shape, never a vendor to dispatch.
        self.assertEqual(automatic.selected_owner, "")

    def test_named_and_recorded_states_report_the_owner_and_its_source(self) -> None:
        named = _decision("codex로 이 버그 고쳐줘")
        recorded = _decision("implement the dark mode toggle and open a pr", recorded_owner="omx-runtime")

        self.assertEqual(named.selected_owner, "codex")
        self.assertEqual(named.source, "request_named_executor")
        self.assertEqual(named.confidence, "high")
        self.assertEqual(recorded.selected_owner, "omx-runtime")
        self.assertEqual(recorded.source, "recorded_setup_preference")
        self.assertEqual(recorded.confidence, "high")

    def test_caller_fixed_executor_target_is_a_named_executor_state(self) -> None:
        decision = _decision("implement the dark mode toggle and open a pr", requested_owner="claude-code")

        self.assertEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
        self.assertEqual(decision.selected_owner, "claude-code")
        self.assertFalse(decision.choice_required)

    def test_pi_family_cues_resolve_the_omo_runtime_owner(self) -> None:
        for message in (
            "have pi implement the retry fix",
            "ask pi to fix the login bug",
            "tell pi to fix the flaky test",
            "delegate to pi: fix the login bug",
            "pi한테 이 버그 고치라고 해줘",
            "pi에게 이 이슈 맡겨서 고쳐줘",
            "have senpi fix the login bug",
            "opencode로 이 버그 고쳐줘",
            "omo runtime으로 이 버그 고쳐줘",
        ):
            with self.subTest(message=message):
                decision = _decision(message)

                self.assertEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
                self.assertEqual(decision.selected_owner, "omo-runtime")
                self.assertFalse(decision.choice_required)


class CodingRouteActionGuardTests(unittest.TestCase):
    """Negative guards: the explicit user-choice path must survive every unsafe case."""

    def test_unset_recorded_owner_is_not_a_preference(self) -> None:
        for recorded_owner in ("", "choose", "  ", "CHOOSE"):
            with self.subTest(recorded_owner=recorded_owner):
                decision = _decision("implement the dark mode toggle and open a pr", recorded_owner=recorded_owner)
                self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
                self.assertTrue(decision.choice_required)

    def test_two_named_executors_stay_a_user_choice(self) -> None:
        decision = _decision("use codex or claude code to fix the login bug")

        self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
        self.assertTrue(decision.choice_required)
        self.assertEqual(decision.selected_owner, "")

    def test_two_route_families_stay_a_user_choice(self) -> None:
        decision = _decision("give me the prompt and also run parallel workers in a worktree")

        self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
        self.assertEqual(decision.selected_route_family, "")

    def test_merge_and_production_authority_outranks_a_named_executor(self) -> None:
        for message in (
            "use codex to implement this and merge to main",
            "codex로 고치고 프로덕션에 배포해줘",
            "have claude code fix this and force push the branch",
        ):
            with self.subTest(message=message):
                decision = _decision(message)
                self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
                self.assertTrue(decision.choice_required)

    def test_authority_cue_outranks_a_recorded_preference(self) -> None:
        decision = _decision("implement this and merge to main", recorded_owner="codex")

        self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
        self.assertTrue(decision.choice_required)

    def test_authority_cue_outranks_a_caller_fixed_executor_target(self) -> None:
        decision = _decision("implement this and merge to main", requested_owner="codex")

        self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
        self.assertTrue(decision.choice_required)

    def test_raspberry_pi_and_pip_context_never_name_the_omo_runtime_owner(self) -> None:
        # Bare "pi" belongs to Raspberry-Pi physical-device routing, and "pi"
        # is a substring of "pip"; neither may name the omo-runtime executor.
        for message in (
            "raspberry pi relay",
            "deploy to my pi 5",
            "raspberry pi에 배포",
            "fix the build with pip install",
        ):
            with self.subTest(message=message):
                decision = _decision(message)

                self.assertNotEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
                self.assertEqual(decision.selected_owner, "")

    def test_owner_learning_asks_then_exposes_reversible_fourth_default(self) -> None:
        state = empty_owner_preference_state()

        for index in range(3):
            decision = _decision(
                "implement the dark mode toggle and open a pr",
                owner_preference_state=state,
            )
            self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
            self.assertEqual(decision.owner_preference_action, "ask_explicit_owner")
            self.assertEqual(decision.owner_preference_evidence_count, index)
            state = record_accepted_explicit_choice(
                state,
                route_family="ulw-coding-delivery",
                selected_owner="codex",
                occurred_at=f"2026-08-13T00:00:0{index + 1}Z",
            )

        fourth = _decision(
            "implement the dark mode toggle and open a pr",
            owner_preference_state=state,
        )

        self.assertEqual(fourth.next_action, RECORDED_OWNER_NEXT_ACTION)
        self.assertEqual(fourth.source, "learned_owner_preference")
        self.assertEqual(fourth.selected_owner, "codex")
        self.assertEqual(fourth.owner_preference_route_family, "ulw-coding-delivery")
        self.assertEqual(fourth.owner_preference_evidence_count, 3)
        self.assertTrue(fourth.owner_preference_override_available)
        self.assertTrue(fourth.owner_preference_reset_available)

    def test_explicit_owner_and_safety_gates_outrank_learned_default(self) -> None:
        state = _learned_owner_state()
        named = _decision(
            "have claude code fix the login bug",
            owner_preference_state=state,
        )
        self.assertEqual(named.next_action, NAMED_EXECUTOR_NEXT_ACTION)
        self.assertEqual(named.selected_owner, "claude-code")
        self.assertEqual(named.owner_preference_reason_code, "owner_named_in_request")

        cases = (
            (
                "use codex or claude code to fix the login bug",
                {},
                "multiple_owners_named",
            ),
            (
                "implement this and merge to main",
                {},
                "authority_requires_choice",
            ),
            (
                "implement the dark mode toggle and open a pr",
                {"owner_ready": False},
                "owner_unready",
            ),
            (
                "implement the dark mode toggle and open a pr",
                {"capability_fit": False},
                "capability_gap",
            ),
        )
        for message, flags, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                decision = _decision(
                    message,
                    owner_preference_state=state,
                    **flags,
                )
                self.assertEqual(decision.next_action, USER_CHOICE_NEXT_ACTION)
                self.assertTrue(decision.choice_required)
                self.assertEqual(decision.owner_preference_reason_code, reason_code)

        bypass = _decision(
            "summarize this paragraph",
            owner_preference_state=state,
            coding_delivery=False,
        )
        self.assertEqual(bypass.owner_preference_action, "bypass_owner_learning")
        self.assertEqual(bypass.owner_preference_reason_code, "non_coding_workflow")
        self.assertEqual(bypass.selected_owner, "")

    def test_embedded_pi_family_substrings_never_name_the_omo_runtime_owner(self) -> None:
        # Word-boundary guard: as raw substrings "promo runtime" contains
        # "omo runtime" and "api한테" contains "pi한테", so containment alone
        # named an executor these messages never mention.
        for message in (
            "promo runtime 로그 확인하는 코드 짜줘",
            "api한테 요청 보내는 코드 짜줘",
        ):
            with self.subTest(message=message):
                decision = _decision(message)

                self.assertNotEqual(decision.next_action, NAMED_EXECUTOR_NEXT_ACTION)
                self.assertEqual(decision.selected_owner, "")


class CodingRouteHintTests(unittest.TestCase):
    def test_every_coding_delivery_site_reports_the_same_lane_and_decision_shape(self) -> None:
        for site, message in CODING_DELIVERY_SITE_MESSAGES:
            with self.subTest(site=site, message=message):
                hint = awareness_route_hint(message)
                decision = hint["primary_coding_route_decision"]

                self.assertEqual(hint["primary_workflow"], "ultraprocess")
                self.assertEqual(hint["primary_next_action"], CODING_ROUTE_LANE_NEXT_ACTION)
                self.assertEqual(hint["hints"][0]["coding_route_decision"], decision)
                self.assertEqual(decision["schema_version"], "coding_route_decision/v1")
                self.assertIn(decision["next_action"], CODING_ROUTE_NEXT_ACTIONS)
                self.assertEqual(decision["lane_next_action"], CODING_ROUTE_LANE_NEXT_ACTION)
                self.assertEqual(decision["user_choice_next_action"], USER_CHOICE_NEXT_ACTION)
                self.assertIn("not executor dispatch", decision["claim_boundary"])

    def test_named_executor_request_reports_the_named_executor_state(self) -> None:
        hint = awareness_route_hint("claude code로 이 이슈 해결해줘")
        decision = hint["primary_coding_route_decision"]

        self.assertEqual(hint["primary_next_action"], CODING_ROUTE_LANE_NEXT_ACTION)
        self.assertEqual(decision["next_action"], NAMED_EXECUTOR_NEXT_ACTION)
        self.assertEqual(decision["selected_owner"], "claude-code")
        self.assertFalse(decision["choice_required"])

    def test_unresolved_request_keeps_the_explicit_user_choice_path(self) -> None:
        hint = awareness_route_hint("테스트 통과할때까지 고쳐줘")
        decision = hint["primary_coding_route_decision"]

        self.assertEqual(decision["next_action"], USER_CHOICE_NEXT_ACTION)
        self.assertTrue(decision["choice_required"])
        self.assertEqual(hint["hints"][0]["fallback_action"], "choose_coding_agent_or_runtime")

    def test_route_hints_stay_prepared_and_never_claim_execution(self) -> None:
        for _site, message in CODING_DELIVERY_SITE_MESSAGES:
            with self.subTest(message=message):
                hint = awareness_route_hint(message)

                self.assertTrue(hint["hints"][0]["not_evidence_yet"])
                self.assertIn("not workflow execution", hint["claim_boundary"])

    def test_non_delivery_requests_never_auto_select_a_coding_owner(self) -> None:
        for guard, message in NON_CODING_DELIVERY_MESSAGES:
            with self.subTest(guard=guard, message=message):
                for item in awareness_route_hint(message)["hints"]:
                    decision = item.get("coding_route_decision")
                    if decision is None:
                        continue
                    self.assertEqual(decision["next_action"], USER_CHOICE_NEXT_ACTION)
                    self.assertTrue(decision["choice_required"])
                    self.assertEqual(decision["selected_owner"], "")
                    self.assertEqual(decision["selected_route_family"], "")

    def test_customer_signal_requests_never_reach_a_coding_owner_decision(self) -> None:
        for message in CUSTOMER_SIGNAL_MESSAGES:
            with self.subTest(message=message):
                hint = awareness_route_hint(message)

                self.assertEqual(hint["primary_workflow"], "feedback-triage")
                self.assertIsNone(hint["primary_coding_route_decision"])
                for item in hint["hints"]:
                    self.assertNotIn("coding_route_decision", item)

    def test_coding_status_requests_are_not_coding_delivery_decisions(self) -> None:
        hint = awareness_route_hint("codex 세션 지금 실행 중이야?")

        self.assertEqual(hint["primary_next_action"], "show_coding_handoff_status")
        self.assertIsNone(hint["primary_coding_route_decision"])


class CodingRouteDecisionWrapperTests(unittest.TestCase):
    def test_recorded_setup_preference_is_its_own_wrapper_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, default_executor="codex")

            payload = build_chat_interaction_payload(
                "implement a focused parser fix in src/omh/parser.py and update tests",
                source="discord",
                mode="delegate",
                paths=paths,
            )

        decision = payload["coding_route_decision"]
        self.assertEqual(decision["next_action"], RECORDED_OWNER_NEXT_ACTION)
        self.assertEqual(decision["source"], "recorded_setup_preference")
        self.assertEqual(decision["selected_owner"], "codex")
        self.assertFalse(decision["choice_required"])
        self.assertEqual(payload["delegation"]["coding_route_decision"], decision)
        # The decision explains ownership; it never upgrades the handoff into dispatch.
        self.assertIn(payload["delegation"]["dispatch_policy"], {"prepare_only", "ask_before_dispatch"})

    def test_wrapper_without_a_recorded_owner_keeps_the_user_choice_state(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")

            payload = build_chat_interaction_payload(
                "implement a focused parser fix in src/omh/parser.py and update tests",
                source="discord",
                mode="delegate",
                paths=paths,
            )

        decision = payload["coding_route_decision"]
        self.assertEqual(decision["next_action"], USER_CHOICE_NEXT_ACTION)
        self.assertTrue(decision["choice_required"])


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
