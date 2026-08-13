from __future__ import annotations

import json
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.coding.model_recommendations import (  # noqa: E402
    MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
)
from omh.coding.model_routing import resolve_model_route  # noqa: E402


def _active(alias: str, provider: str, family: str) -> dict[str, object]:
    return {
        "model_alias": alias,
        "model_id": alias,
        "provider": provider,
        "provider_family": provider,
        "model_family": family,
        "compatible_owners": ["hermes"],
        "status": "confirmed_active",
    }


_KIMI = _active("kimi-k3", "apitopia", "kimi")
_OPUS = _active("claude-opus-5", "ccapi", "claude")
_GROK = _active("grok-code-fast", "xai", "grok")
_GEMINI = _active("gemini-3.1-pro", "google", "gemini")
_GLM_FAST = _active("glm-5.2-ultrafast", "zai", "glm")
_FABLE = _active("claude-fable-5", "ccapi", "claude")


_CATEGORY_ACTIVE = {
    "quick": _GLM_FAST,
    "writing": _KIMI,
    "artistry": _GEMINI,
    "visual-engineering": _FABLE,
}


class HermesRecommendationRoutingTests(unittest.TestCase):
    def test_every_closed_category_has_an_editable_nonempty_editorial_chain(self) -> None:
        from omh.coding.model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS
        from omh.coding.model_routing import MODEL_CATEGORIES

        categories = SHIPPED_MODEL_RECOMMENDATIONS["categories"]
        self.assertEqual(set(categories), set(MODEL_CATEGORIES))
        for category in MODEL_CATEGORIES:
            with self.subTest(category=category):
                self.assertGreater(len(categories[category]), 0)

    def test_category_is_orthogonal_to_role_and_aliases_are_canonical(self) -> None:
        for requested, canonical in (
            ("quick", "quick"),
            ("ulw-writing", "writing"),
            ("ulw-visual", "visual-engineering"),
            ("ulw-artistry", "artistry"),
        ):
            with self.subTest(requested=requested):
                active = _CATEGORY_ACTIVE[canonical]
                route = resolve_model_route(
                    "hermes",
                    role="implementation",
                    requested_category=requested,
                    active_models=[active, _OPUS],
                )
                self.assertEqual(route["category"], canonical)
                self.assertEqual(route["role"], "implementation")
                self.assertEqual(route["selected_model"], f"{active['provider']}/{active['model_id']}")

    def test_non_category_text_does_not_trigger_a_category(self) -> None:
        from omh.coding.model_routing import category_from_text

        for message in (
            "the visual-engineering docs mention routing",
            "make this quick please",
            "the writer discussed artistry",
            "ulw-visual-engineering-ish is not a route",
        ):
            with self.subTest(message=message):
                self.assertEqual(category_from_text(message), "")

    def test_route_consumes_hermes_native_recommendation_projection(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            active_models=[_KIMI, _OPUS],
        )

        recommendation = route["recommendation"]
        projection = recommendation["projection"]
        self.assertEqual(recommendation["owner"], "hermes")
        self.assertEqual(projection["kind"], "hermes_native_binding")
        self.assertEqual(projection["binding"], route["selected_model"])
        self.assertNotEqual(projection["kind"], "maestro_ordered_chain")

    def test_missing_recommended_head_falls_through_confirmed_active_chain(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            active_models=[_OPUS],
        )

        self.assertEqual(route["status"], "routed")
        self.assertEqual(route["provenance"], "recommendation_chain_head")
        self.assertEqual(route["selected_model"], "ccapi/claude-opus-5")
        self.assertEqual(
            [entry["model_id"] for entry in route["chain"]],
            ["ccapi/claude-opus-5"],
        )
        recommendation = route["recommendation"]
        self.assertEqual(recommendation["inactive_candidates"][0], "kimi-k3")

    def test_x_platform_domain_stably_promotes_grok_kimi_gemini_without_removal(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            requested_domain="x_platform_data",
            active_models=[_OPUS, _GEMINI, _KIMI, _GROK],
        )

        chain = [entry["model_id"] for entry in route["chain"]]
        self.assertEqual(
            chain,
            [
                "xai/grok-code-fast",
                "apitopia/kimi-k3",
                "google/gemini-3.1-pro",
                "ccapi/claude-opus-5",
            ],
        )
        self.assertEqual(route["selected_model"], "xai/grok-code-fast")
        affinity = next(
            entry for entry in route["attempted"] if entry["stage"] == "domain_affinity"
        )
        self.assertEqual(affinity["outcome"], "reordered")
        self.assertIn("no entry removed", affinity["reason"])

    def test_missing_grok_falls_through_to_kimi_then_gemini(self) -> None:
        route = resolve_model_route(
            "hermes",
            role="implementation",
            requested_domain="x_platform_data",
            active_models=[_GEMINI, _KIMI],
        )

        self.assertEqual(route["selected_model"], "apitopia/kimi-k3")
        self.assertEqual(
            [entry["model_id"] for entry in route["chain"]],
            ["apitopia/kimi-k3", "google/gemini-3.1-pro"],
        )

    def test_explicit_active_model_wins_over_domain_and_explicit_missing_freezes(self) -> None:
        active = resolve_model_route(
            "hermes",
            role="implementation",
            requested_domain="x_platform_data",
            requested_model="gemini-3.1-pro",
            active_models=[_GROK, _KIMI, _GEMINI],
        )
        self.assertEqual(active["provenance"], "request_named_model")
        self.assertEqual(active["selected_model"], "google/gemini-3.1-pro")

        missing = resolve_model_route(
            "hermes",
            role="implementation",
            requested_domain="x_platform_data",
            requested_model="qwen3-coder",
            active_models=[_GROK, _KIMI, _GEMINI],
        )
        self.assertEqual(missing["status"], "choice_required")
        self.assertEqual(missing["provenance"], "request_named_model_unavailable")
        self.assertEqual(missing["selected_model"], "")
        self.assertEqual(missing["requested_model"], "qwen3-coder")
        self.assertEqual(missing["chain"], [])

    def test_editable_qwen_recommendation_routes_without_omo_catalog_relabeling(self) -> None:
        overrides = {
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {
                "deep": [
                    {
                        "model_alias": "qwen3-coder",
                        "model_family": "qwen",
                        "preferred_provider_families": ["qwen-oauth"],
                        "reasoning_effort": "high",
                        "reasoning": "Operator-selected deep coding route.",
                    }
                ]
            },
        }
        route = resolve_model_route(
            "hermes",
            role="brain",
            active_models=[_active("qwen3-coder", "qwen-oauth", "qwen")],
            recommendation_overrides=overrides,
            local_catalog={
                "schema_version": "local_model_catalog/v1",
                "executor_profile": "omo-runtime",
                "options": [{"model_id": "must/not-route"}],
            },
        )

        self.assertEqual(route["selected_model"], "qwen-oauth/qwen3-coder")
        self.assertEqual(route["catalog_kind"], "editorial_recommendations")
        self.assertNotIn("catalog_fingerprint", route)
        self.assertEqual(route["recommendation"]["source"], "recommendation_chain")

    def test_cli_category_routes_independently_from_role(self) -> None:
        inventory = {
            "model_discovery": {
                "observations": [
                    {
                        "source": "omo",
                        "provider": "zai",
                        "model_id": "glm-5.2-ultrafast",
                        "variant": "",
                        "timestamp": "",
                        "status": "confirmed_active",
                    }
                ]
            }
        }
        with mock.patch("omh.coding.model_inventory.local_model_inventory", return_value=inventory):
            code, stdout, stderr = run_cli(
                [
                    "coding", "model-route", "--executor", "hermes",
                    "--role", "implementation", "--category", "ulw-quick",
                    "--from-inventory", "--json",
                ]
            )
        self.assertEqual((code, stderr), (0, ""))
        route = json.loads(stdout)
        self.assertEqual(route["category"], "quick")
        self.assertEqual(route["role"], "implementation")
        self.assertEqual(route["selected_model"], "zai/glm-5.2-ultrafast")

    def test_cli_routes_hermes_from_confirmed_discovery_and_freezes_missing_explicit(self) -> None:
        inventory = {
            "model_discovery": {
                "observations": [
                    {
                        "source": "omo",
                        "provider": "xai",
                        "model_id": "grok-code-fast",
                        "variant": "",
                        "timestamp": "",
                        "status": "confirmed_active",
                    },
                    {
                        "source": "omo",
                        "provider": "apitopia",
                        "model_id": "kimi-k3",
                        "variant": "",
                        "timestamp": "",
                        "status": "confirmed_active",
                    },
                    {
                        "source": "omo",
                        "provider": "google",
                        "model_id": "gemini-3.1-pro",
                        "variant": "",
                        "timestamp": "",
                        "status": "confirmed_active",
                    },
                ]
            }
        }
        with mock.patch("omh.coding.model_inventory.local_model_inventory", return_value=inventory):
            code, stdout, _stderr = run_cli(
                [
                    "coding",
                    "model-route",
                    "--executor",
                    "hermes",
                    "--role",
                    "implementation",
                    "--domain",
                    "x_platform_data",
                    "--from-inventory",
                    "--json",
                ]
            )
            missing_code, missing_stdout, _missing_stderr = run_cli(
                [
                    "coding",
                    "model-route",
                    "--executor",
                    "hermes",
                    "--role",
                    "implementation",
                    "--model",
                    "qwen3-coder",
                    "--from-inventory",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(missing_code, 0)
        self.assertEqual(json.loads(stdout)["selected_model"], "xai/grok-code-fast")
        self.assertEqual(json.loads(missing_stdout)["status"], "choice_required")


if __name__ == "__main__":
    unittest.main()
