from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.coding_delegation import (  # noqa: E402
    _coding_status_request_applies,
    build_coding_delegation_payload,
)


class CodingStatusAgentTermTests(unittest.TestCase):
    """pi-family executor names reach the coding status board classification.

    `_CODING_STATUS_AGENT_TERMS` matches by substring on the lowered message,
    and bare "pi" hides inside "api" and "pipeline" while the token itself is
    owned by Raspberry-Pi physical-device routing — so pi only counts through
    right-bounded forms matched at word boundaries ("raspi status" hides
    "pi status"), and never in raspberry/api context.
    """

    POSITIVE = (
        "how far along is senpi?",
        "pi 진행상황?",
        "pi 세션 상태 알려줘",
        "opencode 진행상황 알려줘",
        "omo runtime status?",
        # The incumbent names keep working alongside the pi family.
        "how far along is codex?",
        "claude code 작업 어디까지 됐어?",
    )
    NEGATIVE = (
        "raspberry pi 진행상황?",
        "raspberry pi status check",
        "api 진행상황 알려줘",
        # Word-boundary guard: "raspi status" and "spi status" contain
        # "pi status" as a raw substring without any raspberry/api blocker term.
        "raspi status check",
        "check spi status",
    )

    def test_pi_family_status_questions_apply_on_the_status_workflow(self) -> None:
        for message in self.POSITIVE:
            with self.subTest(message=message):
                self.assertTrue(_coding_status_request_applies(message.lower(), "ultraprocess"))

    def test_raspberry_pi_and_api_context_never_applies(self) -> None:
        for message in self.NEGATIVE:
            with self.subTest(message=message):
                self.assertFalse(_coding_status_request_applies(message.lower(), "ultraprocess"))

    def test_status_terms_only_apply_on_the_status_workflow(self) -> None:
        self.assertFalse(_coding_status_request_applies("how far along is senpi?", "loop"))

    def test_an_agent_name_without_a_status_request_never_applies(self) -> None:
        self.assertFalse(_coding_status_request_applies("senpi is a nice tool", "ultraprocess"))


class CategoryPropagationTests(unittest.TestCase):
    def test_natural_ulw_category_reaches_root_and_hermes_handoff(self) -> None:
        payload = build_coding_delegation_payload(
            "Use ulw-visual-engineering to implement the dashboard",
            executor_target="hermes",
        )

        self.assertEqual(payload["model_route_category"], "visual-engineering")
        self.assertEqual(
            payload["runtime_handoff"]["model_route_category"],
            "visual-engineering",
        )

    def test_natural_alias_reaches_external_handoff_without_becoming_a_role(self) -> None:
        payload = build_coding_delegation_payload(
            "Implement a risky documentation refactor with /ulw-write",
            executor_target="codex",
        )

        self.assertEqual(payload["model_route_category"], "writing")
        self.assertEqual(payload["executor_handoff"]["model_route_category"], "writing")


class HermesNativeModelBindingTests(unittest.TestCase):
    def test_resolved_recommendation_binds_native_alias_kanban_and_delegate_metadata(self) -> None:
        recommendation = {
            "schema_version": "model_recommendation_resolution/v1",
            "owner": "hermes",
            "status": "resolved",
            "source": "recommendation_chain",
            "selected": {
                "model_alias": "qwen3-coder",
                "provider": "qwen-oauth",
                "model_id": "qwen3-coder",
                "recommendation_source": "shipped_catalog",
            },
            "projection": {
                "kind": "hermes_native_binding",
                "alias": "deep",
                "provider": "qwen-oauth",
                "model_id": "qwen3-coder",
                "binding": "qwen-oauth/qwen3-coder",
                "apply_state": "approval_required",
            },
        }

        payload = build_coding_delegation_payload(
            "implement a risky refactor with Hermes",
            executor_target="hermes",
            model_recommendation=recommendation,
        )

        handoff = payload["runtime_handoff"]
        binding = handoff["hermes_native_model_binding"]
        self.assertEqual(binding["status"], "prepared_not_observed")
        self.assertEqual(binding["alias"], "deep")
        self.assertEqual(binding["provider"], "qwen-oauth")
        self.assertEqual(binding["model_id"], "qwen3-coder")
        self.assertEqual(binding["binding"], "qwen-oauth/qwen3-coder")
        self.assertEqual(binding["provenance"], "shipped_catalog")
        self.assertEqual(binding["kanban_task_override"]["command"], "set-model qwen-oauth/qwen3-coder")
        self.assertEqual(
            binding["delegate_task_override"],
            {
                "model": "qwen-oauth/qwen3-coder",
                "status": "prepared_not_observed",
            },
        )
        self.assertNotIn("maestro", str(payload).casefold())
        self.assertIn("runtime observation", binding["claim_boundary"].casefold())

    def test_unconfigured_recommendation_requires_native_setup_without_model_pin(self) -> None:
        recommendation = {
            "schema_version": "model_recommendation_resolution/v1",
            "owner": "hermes",
            "status": "unconfigured",
            "source": "recommendation_chain",
            "selected": None,
            "projection": None,
            "inactive_candidates": ["gemini-3.1-pro"],
        }

        payload = build_coding_delegation_payload(
            "implement a risky refactor with Hermes",
            executor_target="hermes",
            model_recommendation=recommendation,
        )

        binding = payload["runtime_handoff"]["hermes_native_model_binding"]
        self.assertEqual(binding["status"], "choice_required")
        self.assertEqual(binding["next_action"], "configure_hermes_native_alias")
        self.assertEqual(binding["inactive_candidates"], ["gemini-3.1-pro"])
        self.assertNotIn("kanban_task_override", binding)
        self.assertNotIn("delegate_task_override", binding)


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()
