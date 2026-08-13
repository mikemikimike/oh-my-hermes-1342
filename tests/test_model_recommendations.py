from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.model_recommendations import (  # noqa: E402
    MODEL_RECOMMENDATION_CATALOG_SCHEMA_VERSION,
    MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
    MODEL_RECOMMENDATION_RESOLUTION_SCHEMA_VERSION,
    MODEL_RECOMMENDATION_STATUSES,
    SHIPPED_MODEL_RECOMMENDATIONS,
    load_recommendation_overrides,
    merge_recommendation_catalog,
    resolve_model_recommendation,
    serialize_recommendation_payload,
)
from omh.coding.model_routing import MODEL_CATEGORIES, MODEL_ROLES  # noqa: E402


def _active(
    model_alias: str,
    *,
    provider: str,
    model_id: str | None = None,
    family: str = "",
    owners: tuple[str, ...] = ("hermes", "maestro"),
    status: str = "confirmed_active",
) -> dict[str, object]:
    return {
        "model_alias": model_alias,
        "model_id": model_id or model_alias,
        "provider": provider,
        "provider_family": provider,
        "model_family": family,
        "compatible_owners": owners,
        "status": status,
    }


_ALL_ACTIVE = (
    _active("kimi-k3", provider="apitopia", family="kimi"),
    _active("claude-opus-5", provider="ccapi", family="claude"),
    _active("claude-fable-5", provider="ccapi", family="claude"),
    _active("gpt-5.6-sol", provider="openai-codex", family="gpt"),
    _active("gpt-5.6-terra", provider="openai-codex", family="gpt"),
    _active("glm-5.2", provider="zai", family="glm"),
    _active("glm-5.2-ultrafast", provider="zai", family="glm"),
    _active("grok-code-fast", provider="xai", family="grok"),
    _active("gemini-3.1-pro", provider="google", family="gemini"),
)


class RecommendationCatalogTests(unittest.TestCase):
    def test_catalog_is_schema_versioned_and_preserves_closed_vocabularies(self) -> None:
        catalog = SHIPPED_MODEL_RECOMMENDATIONS
        self.assertEqual(catalog["schema_version"], MODEL_RECOMMENDATION_CATALOG_SCHEMA_VERSION)
        self.assertEqual(set(catalog["categories"]), set(MODEL_CATEGORIES))
        self.assertEqual(MODEL_CATEGORIES, (
            "ultrabrain", "deep", "unspecified-high", "unspecified-low",
            "quick", "writing", "visual-engineering", "artistry",
        ))
        self.assertEqual(MODEL_ROLES, (
            "brain", "implementation", "design_visual", "review", "docs", "research",
        ))
        self.assertNotIn("main", catalog["categories"])
        self.assertNotIn("x_platform_data", catalog["categories"])
        self.assertEqual(set(catalog["role_suggestions"]), {"main"})
        self.assertEqual(set(catalog["domain_affinities"]), {"x_platform_data"})

    def test_shipped_editorial_chains_are_pinned(self) -> None:
        catalog = SHIPPED_MODEL_RECOMMENDATIONS

        def aliases(section: str, name: str) -> list[str]:
            return [entry["model_alias"] for entry in catalog[section][name]]

        self.assertEqual(aliases("role_suggestions", "main"), [
            "kimi-k3", "claude-opus-5", "claude-fable-5", "gpt-5.6-sol", "gpt-5.6-terra",
        ])
        self.assertEqual(aliases("categories", "unspecified-low"), ["glm-5.2", "glm-5.2-ultrafast"])
        self.assertEqual(aliases("categories", "unspecified-high"), ["kimi-k3", "claude-opus-5"])
        self.assertEqual(aliases("categories", "ultrabrain"), ["gpt-5.6-sol"])
        self.assertEqual(aliases("categories", "deep"), ["gpt-5.6-terra"])
        self.assertEqual(aliases("categories", "visual-engineering"), ["claude-fable-5", "kimi-k3"])
        self.assertEqual(aliases("categories", "quick"), ["glm-5.2-ultrafast", "kimi-k3"])
        self.assertEqual(aliases("categories", "writing"), ["kimi-k3", "qwen3-coder", "gemini-3.1-pro"])
        self.assertEqual(aliases("categories", "artistry"), ["gemini-3.1-pro", "claude-fable-5", "kimi-k3"])
        self.assertEqual(aliases("domain_affinities", "x_platform_data"), [
            "grok-code-fast", "kimi-k3", "gemini-3.1-pro",
        ])
        main = catalog["role_suggestions"]["main"]
        self.assertEqual([entry["reasoning_effort"] for entry in main[-2:]], ["medium", "high"])
        self.assertEqual(catalog["categories"]["ultrabrain"][0]["reasoning_effort"], "xhigh")
        self.assertEqual(catalog["categories"]["deep"][0]["reasoning_effort"], "high")
        for section in ("categories", "role_suggestions", "domain_affinities"):
            for chain in catalog[section].values():
                for candidate in chain:
                    self.assertTrue(candidate["model_family"])
                    self.assertTrue(candidate["preferred_provider_families"])
                    self.assertTrue(candidate["reasoning"])
                    self.assertEqual(candidate["recommendation_source"], "shipped_editorial")

    def test_override_loader_and_merge_are_deterministic_and_secret_free(self) -> None:
        override = {
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {
                "deep": [{
                    "model_alias": "qwen3-coder",
                    "model_family": "qwen",
                    "preferred_provider_families": ["qwen-oauth"],
                    "reasoning_effort": "high",
                    "reasoning": "Operator-selected deep coding route.",
                }],
            },
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "recommendations.json"
            path.write_text(json.dumps(override), encoding="utf-8")
            loaded = load_recommendation_overrides(path)
        self.assertEqual(loaded["categories"]["deep"][0]["recommendation_source"], "user_override")
        first = merge_recommendation_catalog(SHIPPED_MODEL_RECOMMENDATIONS, loaded)
        second = merge_recommendation_catalog(SHIPPED_MODEL_RECOMMENDATIONS, loaded)
        self.assertEqual(serialize_recommendation_payload(first), serialize_recommendation_payload(second))
        self.assertEqual(first["categories"]["deep"][0]["model_alias"], "qwen3-coder")
        self.assertEqual(first["categories"]["quick"], SHIPPED_MODEL_RECOMMENDATIONS["categories"]["quick"])
        serialized = serialize_recommendation_payload(first)
        self.assertNotIn("api_key", serialized.casefold())
        self.assertNotIn("token", serialized.casefold())

    def test_override_rejects_categories_role_slots_domains_and_secret_fields_at_wrong_surfaces(self) -> None:
        bad_payloads = (
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "categories": {"main": []}},
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "categories": {"x_platform_data": []}},
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "role_suggestions": {"brain": []}},
            {"schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION, "domain_affinities": {"main": []}},
            {
                "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
                "categories": {"deep": [{
                    "model_alias": "qwen3-coder", "model_family": "qwen",
                    "preferred_provider_families": ["qwen-oauth"],
                    "reasoning": "x", "api_key": "must-not-be-stored",
                }]},
            },
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    load_recommendation_overrides(payload)


class RecommendationResolverTests(unittest.TestCase):
    def test_recommended_head_and_missing_head_resolution_are_deterministic(self) -> None:
        all_active = resolve_model_recommendation(
            owner="maestro", category="unspecified-high", active_models=reversed(_ALL_ACTIVE)
        )
        self.assertEqual(all_active["status"], "resolved")
        self.assertEqual(all_active["selected"]["model_alias"], "kimi-k3")
        self.assertEqual(
            [entry["model_alias"] for entry in all_active["projection"]["chain"]],
            ["kimi-k3", "claude-opus-5"],
        )

        only_next = resolve_model_recommendation(
            owner="maestro",
            category="unspecified-high",
            active_models=[_active("claude-opus-5", provider="ccapi", family="claude")],
        )
        self.assertEqual(only_next["selected"]["model_alias"], "claude-opus-5")
        self.assertEqual([entry["model_alias"] for entry in only_next["projection"]["chain"]], ["claude-opus-5"])
        self.assertEqual(only_next["inactive_candidates"], ["kimi-k3"])

    def test_explicit_unavailable_freezes_as_choice_required_without_substitution(self) -> None:
        route = resolve_model_recommendation(
            owner="maestro",
            category="unspecified-high",
            explicit_model="grok-code-fast",
            active_models=_ALL_ACTIVE[:-2],
        )
        self.assertEqual(route["status"], "choice_required")
        self.assertEqual(route["requested_model"], "grok-code-fast")
        self.assertIsNone(route["selected"])
        self.assertIsNone(route["projection"])
        self.assertEqual(route["available_chain"], ["kimi-k3", "claude-opus-5"])

    def test_explicit_active_model_wins_over_editorial_chain(self) -> None:
        route = resolve_model_recommendation(
            owner="maestro",
            category="unspecified-high",
            explicit_model="grok-code-fast",
            active_models=_ALL_ACTIVE,
        )
        self.assertEqual(route["status"], "resolved")
        self.assertEqual(route["selected"]["model_alias"], "grok-code-fast")
        self.assertEqual(route["source"], "explicit_model")
        self.assertEqual([entry["model_alias"] for entry in route["projection"]["chain"]], ["grok-code-fast"])

    def test_no_active_candidate_is_unconfigured_and_setup_can_continue(self) -> None:
        route = resolve_model_recommendation(owner="hermes", category="deep", active_models=[])
        self.assertEqual(route["schema_version"], MODEL_RECOMMENDATION_RESOLUTION_SCHEMA_VERSION)
        self.assertEqual(route["status"], "unconfigured")
        self.assertIn(route["status"], MODEL_RECOMMENDATION_STATUSES)
        self.assertIsNone(route["selected"])
        self.assertIsNone(route["projection"])
        self.assertTrue(route["setup_can_continue"])
        self.assertEqual(route["inactive_candidates"], ["gpt-5.6-terra"])

    def test_only_confirmed_active_owner_compatible_models_are_eligible(self) -> None:
        models = (
            _active("gpt-5.6-terra", provider="openai-codex", status="observed_before"),
            _active("gpt-5.6-terra", provider="openai-codex", owners=("maestro",)),
        )
        route = resolve_model_recommendation(owner="hermes", category="deep", active_models=models)
        self.assertEqual(route["status"], "unconfigured")

    def test_hermes_projection_is_one_native_binding_not_a_provider_registry(self) -> None:
        route = resolve_model_recommendation(
            owner="hermes", role_slot="main", active_models=reversed(_ALL_ACTIVE)
        )
        projection = route["projection"]
        self.assertEqual(projection["kind"], "hermes_native_binding")
        self.assertEqual(projection["alias"], "main")
        self.assertEqual(projection["provider"], "apitopia")
        self.assertEqual(projection["model_id"], "kimi-k3")
        self.assertEqual(projection["binding"], "apitopia/kimi-k3")
        self.assertEqual(projection["apply_state"], "approval_required")
        self.assertNotIn("providers", projection)
        self.assertNotIn("credentials", serialize_recommendation_payload(route).casefold())

    def test_maestro_projection_keeps_ordered_external_chain_and_owner_compatibility(self) -> None:
        active = (
            _active("grok-code-fast", provider="xai", family="grok", owners=("hermes",)),
            _active("kimi-k3", provider="apitopia", family="kimi"),
            _active("gemini-3.1-pro", provider="google", family="gemini"),
        )
        route = resolve_model_recommendation(
            owner="maestro", domain="x_platform_data", active_models=active
        )
        self.assertEqual(route["selected"]["model_alias"], "kimi-k3")
        self.assertEqual(route["projection"]["kind"], "maestro_ordered_chain")
        self.assertEqual(
            [entry["model_alias"] for entry in route["projection"]["chain"]],
            ["kimi-k3", "gemini-3.1-pro"],
        )
        self.assertEqual(route["inactive_candidates"], ["grok-code-fast"])

    def test_selector_surfaces_are_mutually_exclusive_and_closed(self) -> None:
        invalid = (
            {"category": "main"},
            {"category": "x_platform_data"},
            {"role_slot": "brain"},
            {"domain": "main"},
            {"category": "deep", "domain": "x_platform_data"},
        )
        for selector in invalid:
            with self.subTest(selector=selector):
                with self.assertRaises(ValueError):
                    resolve_model_recommendation(owner="hermes", active_models=(), **selector)

    def test_user_override_drives_resolution_without_mutating_shipped_catalog(self) -> None:
        override = load_recommendation_overrides({
            "schema_version": MODEL_RECOMMENDATION_OVERRIDE_SCHEMA_VERSION,
            "categories": {"deep": [{
                "model_alias": "qwen3-coder", "model_family": "qwen",
                "preferred_provider_families": ["qwen-oauth"],
                "reasoning_effort": "high", "reasoning": "User deep route.",
            }]},
        })
        route = resolve_model_recommendation(
            owner="hermes",
            category="deep",
            active_models=[_active("qwen3-coder", provider="qwen-oauth", family="qwen")],
            overrides=override,
        )
        self.assertEqual(route["selected"]["model_alias"], "qwen3-coder")
        self.assertEqual(route["selected"]["recommendation_source"], "user_override")
        self.assertEqual(SHIPPED_MODEL_RECOMMENDATIONS["categories"]["deep"][0]["model_alias"], "gpt-5.6-terra")

    def test_resolution_serialization_is_stable_across_active_input_order(self) -> None:
        first = resolve_model_recommendation(
            owner="maestro", role_slot="main", active_models=_ALL_ACTIVE
        )
        second = resolve_model_recommendation(
            owner="maestro", role_slot="main", active_models=reversed(_ALL_ACTIVE)
        )
        self.assertEqual(serialize_recommendation_payload(first), serialize_recommendation_payload(second))


if __name__ == "__main__":
    unittest.main()
