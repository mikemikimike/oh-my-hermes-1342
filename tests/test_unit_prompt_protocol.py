from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_dispatch import build_unit_prompt  # noqa: E402
from omh.coding.model_routing import EXECUTOR_MODEL_OPTIONS, MODEL_ROLES  # noqa: E402
from _cli_harness import run_cli  # noqa: E402
from omh.coding.unit_prompt_protocol import (  # noqa: E402
    GOAL_ECHO_PROTOCOL,
    HIGH_EFFORT_CALIBRATIONS,
    HIGH_EFFORT_TIER,
    MAIN_AGENT_COMPOSITION_CALIBRATIONS,
    REVIEW_ROLE_PROTOCOL,
    UNIT_PROMPT_MAX_BYTES,
    VERIFICATION_STOP_PROTOCOL,
    calibration_for_route,
    completion_criteria_for_unit,
    composition_calibration_for_model,
    unit_protocol_lines,
)

_GOAL = "build the virtual dashboard feature across subagents"


def _contract_unit(units: list[dict], unit_id: str) -> dict:
    contract = build_fanout_contract(_GOAL, units)
    return {unit["unit_id"]: unit for unit in contract["units"]}[unit_id]


class ProtocolContentTests(unittest.TestCase):
    def test_prompt_carries_echo_criteria_and_stop_protocol(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "impl", "title": "Impl", "owner": "codex", "file_scope": ["src/core/"]},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "impl",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        self.assertIn(GOAL_ECHO_PROTOCOL, prompt)
        self.assertIn("Done means, and only means:", prompt)
        self.assertIn(VERIFICATION_STOP_PROTOCOL, prompt)
        # Verification stays mandatory: the discipline bounds it, never skips it.
        self.assertIn("verification is never skipped", prompt)
        self.assertIn("Commit your work; do not merge or push other branches.", prompt)

    def test_integration_checks_become_numbered_criteria(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "impl", "title": "Impl", "owner": "codex", "file_scope": ["src/core/"]},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "impl",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        self.assertNotIn("Before finishing:", prompt)
        criteria = completion_criteria_for_unit(unit)
        self.assertGreaterEqual(len(criteria), 3)
        for index, criterion in enumerate(criteria, start=1):
            self.assertIn(f"{index}. {criterion}", prompt)
        # Boundary confinement and committed work are always declared criteria.
        self.assertTrue(any("src/core/" in criterion for criterion in criteria))
        self.assertTrue(any("committed" in criterion for criterion in criteria))

    def test_review_role_gets_criterion_bound_review_protocol(self) -> None:
        review = _contract_unit(
            [
                {"unit_id": "review", "title": "Review", "owner": "codex", "file_scope": ["src/r/"], "role": "review"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "review",
        )
        self.assertIn(REVIEW_ROLE_PROTOCOL, build_unit_prompt(review, _GOAL))
        aux = _contract_unit(
            [
                {"unit_id": "review", "title": "Review", "owner": "codex", "file_scope": ["src/r/"], "role": "review"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "aux",
        )
        self.assertNotIn(REVIEW_ROLE_PROTOCOL, build_unit_prompt(aux, _GOAL))


class CalibrationSelectionTests(unittest.TestCase):
    def test_high_effort_codex_brain_gets_gpt_calibration(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "brain", "title": "Brain", "owner": "codex", "file_scope": ["src/d/"], "role": "brain"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "brain",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        self.assertIn(HIGH_EFFORT_CALIBRATIONS["gpt"], prompt)

    def test_high_effort_claude_brain_gets_claude_calibration(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "brain", "title": "Brain", "owner": "claude-code", "file_scope": ["src/d/"], "role": "brain"},
                {"unit_id": "aux", "title": "Aux", "owner": "codex", "file_scope": ["docs/"]},
            ],
            "brain",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        self.assertIn(HIGH_EFFORT_CALIBRATIONS["claude"], prompt)

    def test_low_or_absent_effort_gets_no_calibration(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "docs", "title": "Docs", "owner": "codex", "file_scope": ["docs/a/"], "role": "docs"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/b/"]},
            ],
            "docs",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        for block in HIGH_EFFORT_CALIBRATIONS.values():
            self.assertNotIn(block, prompt)

    def test_unknown_family_high_effort_falls_back_to_generic(self) -> None:
        route = {"selected_reasoning_effort": "xhigh", "model_family": "unknown"}
        self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["generic"])
        route = {"selected_reasoning_effort": "xhigh", "model_family": "mistral"}
        self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["generic"])

    def test_each_declared_family_gets_its_own_block(self) -> None:
        # gemini/grok/kimi/glm/qwen/deepseek ride provider-surfaced routes; each family's
        # counter-text is distinct data, selected by the recorded model_family.
        for family in ("gpt", "claude", "gemini", "grok", "kimi", "glm", "qwen", "deepseek"):
            route = {"selected_reasoning_effort": "high", "model_family": family}
            self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS[family], family)

    def test_target_family_calibrations_preserve_documented_agent_behavior(self) -> None:
        self.assertIn("non-thinking", HIGH_EFFORT_CALIBRATIONS["qwen"])
        self.assertNotIn("<think>", HIGH_EFFORT_CALIBRATIONS["qwen"])
        self.assertIn("model version", HIGH_EFFORT_CALIBRATIONS["deepseek"])
        self.assertIn("interleaved", HIGH_EFFORT_CALIBRATIONS["glm"])

    def test_no_route_means_no_calibration(self) -> None:
        self.assertEqual(calibration_for_route(None), "")

    def test_generic_fallback_exists_and_no_family_lacks_discipline(self) -> None:
        # Executor neutrality: the generic block is mandatory so an unknown
        # family never gets weaker discipline than a known one, and every
        # declared block carries the same core stop rule.
        self.assertIn("generic", HIGH_EFFORT_CALIBRATIONS)
        for family, block in HIGH_EFFORT_CALIBRATIONS.items():
            self.assertTrue(block.startswith("High-effort calibration:"), family)


class CompositionCalibrationTests(unittest.TestCase):
    def test_composer_families_mirror_subagent_families(self) -> None:
        """No family gets subagent discipline without composer discipline:
        the two calibration tables share one key set, generic included."""
        self.assertEqual(
            set(MAIN_AGENT_COMPOSITION_CALIBRATIONS), set(HIGH_EFFORT_CALIBRATIONS)
        )
        for family, block in MAIN_AGENT_COMPOSITION_CALIBRATIONS.items():
            self.assertTrue(block.startswith("Composition calibration:"), family)

    def test_selection_follows_the_composers_own_model(self) -> None:
        # The user's own examples: fable5 -> claude family, sol -> gpt,
        # gemini -> gemini, kimi -> kimi, qwen -> qwen; provider prefixes welcome.
        cases = {
            "claude-fable-5": "claude",
            "gpt-5.6-sol": "gpt",
            "gemini-3.1-pro": "gemini",
            "kimi-k3": "kimi",
            "opencode/glm-5": "glm",
            "grok-code-fast-1": "grok",
            "qwen-max-2024-11-26": "qwen",
        }
        for model_id, family in cases.items():
            self.assertEqual(
                composition_calibration_for_model(model_id),
                MAIN_AGENT_COMPOSITION_CALIBRATIONS[family],
                model_id,
            )
        self.assertEqual(
            composition_calibration_for_model("mystery-model-9"),
            MAIN_AGENT_COMPOSITION_CALIBRATIONS["generic"],
        )
        self.assertEqual(
            composition_calibration_for_model(""),
            MAIN_AGENT_COMPOSITION_CALIBRATIONS["generic"],
        )

    def test_cli_guide_plain_default_and_json(self) -> None:
        status, stdout, _stderr = run_cli(
            ["coding", "composition-guide", "--model", "claude-fable-5"], output_json=False
        )
        self.assertEqual(status, 0)
        self.assertIn("claude family", stdout)
        self.assertIn("Composition calibration:", stdout)
        status, stdout, _stderr = run_cli(["coding", "composition-guide", "--json"])
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "composition_guide/v1")
        self.assertEqual(set(payload["calibrations"]), set(MAIN_AGENT_COMPOSITION_CALIBRATIONS))


class DomainSkillBundleTests(unittest.TestCase):
    def test_declared_work_domain_bundles_the_matching_skill(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "ops", "title": "Fix CI", "owner": "codex", "file_scope": ["ci/"], "role": "implementation", "domain": "devops"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "ops",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        self.assertIn("OMH skill bundle (devops)", prompt)
        self.assertIn("omh-build-failure-triage", prompt)

    def test_no_domain_or_unknown_domain_means_no_bundle(self) -> None:
        from omh.coding.unit_prompt_protocol import DOMAIN_SKILL_GUIDANCE, domain_skill_guidance_line

        self.assertEqual(domain_skill_guidance_line({"unit_id": "x"}), "")
        self.assertEqual(domain_skill_guidance_line({"domain": "gardening"}), "")
        self.assertEqual(
            set(DOMAIN_SKILL_GUIDANCE), {"devops", "app_development", "research", "x_platform_data"}
        )


class PromptBudgetPolicyTests(unittest.TestCase):
    def test_worst_case_prompt_stays_under_budget(self) -> None:
        """Unit prompts become subprocess argv; the ceiling is policy-gated
        here rather than trimmed at runtime. Exercises every profile x role
        combination plus, per calibration family, a requested model that
        selects that family's block (requested models pass through
        unvalidated, so every declared block is reachable on any profile)."""
        wide_scope = [f"src/area{i}/" for i in range(12)]
        requested_models = [""] + [f"{family}-x" for family in HIGH_EFFORT_CALIBRATIONS]
        worst = 0
        for profile in EXECUTOR_MODEL_OPTIONS:
            for role in MODEL_ROLES:
                for requested_model in requested_models:
                    target: dict[str, object] = {
                        "unit_id": "target",
                        "title": "A deliberately verbose unit title for budget measurement",
                        "owner": profile,
                        "file_scope": ["src/target/"],
                        "role": role,
                        "reasoning_effort": "max",
                        "domain": "x_platform_data",
                    }
                    if requested_model:
                        target["model"] = requested_model
                    units = [
                        target,
                        {"unit_id": "sibling", "title": "Sibling", "owner": profile, "file_scope": wide_scope},
                    ]
                    unit = _contract_unit(units, "target")
                    prompt = build_unit_prompt(unit, _GOAL * 3)
                    worst = max(worst, len(prompt.encode("utf-8")))
        self.assertLess(worst, UNIT_PROMPT_MAX_BYTES, f"worst-case unit prompt {worst}B")

    def test_protocol_lines_are_deterministic(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "brain", "title": "Brain", "owner": "codex", "file_scope": ["src/d/"], "role": "brain"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "brain",
        )
        self.assertEqual(unit_protocol_lines(unit), unit_protocol_lines(unit))
        self.assertEqual(build_unit_prompt(unit, _GOAL), build_unit_prompt(unit, _GOAL))

    def test_high_effort_tier_vocabulary(self) -> None:
        self.assertEqual(HIGH_EFFORT_TIER, frozenset({"high", "xhigh", "max"}))


if __name__ == "__main__":
    unittest.main()
