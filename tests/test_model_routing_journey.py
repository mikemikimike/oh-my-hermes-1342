from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.maestro import ExternalHandoffRequest, HermesNativeSelectionError, build_external_handoff  # noqa: E402
from omh.coding.model_discovery import discover_local_models  # noqa: E402
from omh.coding.model_recommendations import resolve_model_recommendation  # noqa: E402


class ModelRoutingJourneyTests(unittest.TestCase):
    def test_discovery_to_hermes_and_maestro_keeps_the_owner_boundary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            models = home / ".omo" / "models.json"
            models.parent.mkdir(parents=True)
            models.write_text(
                json.dumps(
                    {
                        "models": [
                            {"provider": "xai", "model_id": "grok-code-fast"},
                            {"provider": "apitopia", "model_id": "kimi-k3"},
                            {"provider": "google", "model_id": "gemini-3.1-pro"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            discovery = discover_local_models(home=home)
            active = [
                {
                    **observation,
                    "status": "confirmed_active",
                }
                for observation in discovery["observations"]
            ]
            hermes = resolve_model_recommendation(
                owner="hermes",
                domain="x_platform_data",
                active_models=active,
            )
            external = resolve_model_recommendation(
                owner="maestro",
                domain="x_platform_data",
                active_models=active,
            )
            handoff = build_external_handoff(
                ExternalHandoffRequest(
                    message="Use Claude Code to implement the X-platform change",
                    profile="claude-code",
                )
            )

        self.assertEqual(hermes["projection"]["kind"], "hermes_native_binding")
        self.assertEqual(hermes["projection"]["binding"], "xai/grok-code-fast")
        self.assertEqual(external["projection"]["kind"], "maestro_ordered_chain")
        self.assertEqual(external["available_chain"][:3], ["grok-code-fast", "kimi-k3", "gemini-3.1-pro"])
        self.assertEqual(handoff.capability.profile, "claude-code")
        self.assertEqual(handoff.capability.observation_boundary, "prepared_not_observed")
        self.assertFalse(handoff.capability.executes_work)

    def test_maestro_rejects_hermes_and_missing_recommendations_stay_flexible(self) -> None:
        missing = resolve_model_recommendation(
            owner="hermes",
            category="ultrabrain",
            active_models=[{"provider": "google", "model_id": "gemini-3.1-pro", "status": "confirmed_active"}],
        )
        unavailable = resolve_model_recommendation(
            owner="hermes",
            category="ultrabrain",
            explicit_model="gpt-5.6-sol",
            active_models=[{"provider": "google", "model_id": "gemini-3.1-pro", "status": "confirmed_active"}],
        )

        self.assertEqual(missing["status"], "unconfigured")
        self.assertTrue(missing["setup_can_continue"])
        self.assertEqual(missing["inactive_candidates"], ["gpt-5.6-sol"])
        self.assertEqual(unavailable["status"], "choice_required")
        self.assertTrue(unavailable["setup_can_continue"])
        self.assertEqual(unavailable["requested_model"], "gpt-5.6-sol")
        with self.assertRaises(HermesNativeSelectionError):
            build_external_handoff(ExternalHandoffRequest(message="fix it", profile="hermes"))
