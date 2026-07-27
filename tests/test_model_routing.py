from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_dispatch import build_dispatch_argv  # noqa: E402
from omh.coding.model_routing import (  # noqa: E402
    CODING_MODEL_ROUTE_SCHEMA_VERSION,
    MODEL_ROLES,
    model_family,
    model_route_for_unit,
    resolve_model_route,
)


class ModelRouteResolverTests(unittest.TestCase):
    def test_requested_model_always_wins_and_passes_through_unvalidated(self) -> None:
        route = resolve_model_route("codex", requested_model="gpt-6-terra", requested_effort="xhigh", role="brain")
        self.assertEqual(route["schema_version"], CODING_MODEL_ROUTE_SCHEMA_VERSION)
        self.assertEqual(route["status"], "routed")
        self.assertEqual(route["source"], "request_named_model")
        self.assertEqual(route["selected_model"], "gpt-6-terra")
        self.assertEqual(route["selected_reasoning_effort"], "xhigh")
        self.assertEqual(route["model_family"], "gpt")

    def test_unknown_family_is_named_not_rejected(self) -> None:
        route = resolve_model_route("claude-code", requested_model="luna-5.5")
        self.assertEqual(route["status"], "routed")
        self.assertEqual(route["model_family"], "unknown")

    def test_claude_tier_aliases_fold_into_claude_family(self) -> None:
        self.assertEqual(model_family("opus"), "claude")
        self.assertEqual(model_family("claude-opus-5"), "claude")

    def test_role_with_single_candidate_routes_deterministically(self) -> None:
        route = resolve_model_route("claude-code", role="implementation")
        self.assertEqual(route["status"], "routed")
        self.assertEqual(route["source"], "role_catalog_default")
        self.assertEqual(route["selected_model"], "sonnet")

    def test_review_role_on_codex_requires_an_explicit_choice(self) -> None:
        # `review` is recommended on both codex options by design, so the role
        # resolves to a choice instead of a silent default.
        route = resolve_model_route("codex", role="review")
        self.assertEqual(route["status"], "choice_required")
        self.assertEqual(route["source"], "role_catalog_candidates")
        self.assertEqual(len(route["candidates"]), 2)
        self.assertEqual(route["selected_model"], "")

    def test_unknown_role_is_named_in_reasons_not_erased(self) -> None:
        route = resolve_model_route("codex", role="tester")
        self.assertEqual(route["status"], "model_unrouted")
        self.assertTrue(any("tester" in reason for reason in route["reasons"]))
        self.assertFalse(any("No model or role was requested" in reason for reason in route["reasons"]))

    def test_effort_survives_profiles_without_catalog(self) -> None:
        route = resolve_model_route("gemini-runtime", requested_effort="high")
        self.assertEqual(route["status"], "no_model_catalog")
        self.assertEqual(route["selected_reasoning_effort"], "high")

    def test_unsafe_effort_shape_falls_back_to_cli_default(self) -> None:
        route = resolve_model_route("codex", requested_model="gpt-5", requested_effort='high\nsandbox_mode = "danger"')
        self.assertEqual(route["selected_reasoning_effort"], "")

    def test_brain_role_gets_high_effort_default(self) -> None:
        route = resolve_model_route("codex", role="brain")
        self.assertEqual(route["selected_reasoning_effort"], "high")

    def test_no_request_is_an_explicit_executor_default_outcome(self) -> None:
        route = resolve_model_route("codex")
        self.assertEqual(route["status"], "model_unrouted")
        self.assertEqual(route["source"], "executor_default")
        self.assertEqual(route["selected_model"], "")

    def test_profile_without_catalog_is_named(self) -> None:
        route = resolve_model_route("hermes")
        self.assertEqual(route["status"], "no_model_catalog")

    def test_claim_boundary_disclaims_provider_truth(self) -> None:
        route = resolve_model_route("codex", requested_model="gpt-5")
        self.assertIn("provider truth", route["claim_boundary"])

    def test_model_roles_vocabulary_is_stable(self) -> None:
        self.assertEqual(MODEL_ROLES, ("brain", "implementation", "design_visual", "review", "docs"))


class DispatchArgvTests(unittest.TestCase):
    def test_no_route_keeps_argv_byte_identical(self) -> None:
        argv = build_dispatch_argv("codex", "do the work")
        self.assertEqual(argv, ["codex", "exec", "do the work"])
        claude = build_dispatch_argv("claude-code", "do the work")
        self.assertEqual(claude[0:3], ["claude", "-p", "do the work"])
        self.assertNotIn("--model", claude)

    def test_codex_model_and_effort_insert_before_prompt(self) -> None:
        route = resolve_model_route("codex", requested_model="gpt-5-codex", requested_effort="xhigh")
        argv = build_dispatch_argv("codex", "do the work", route)
        self.assertEqual(
            argv,
            [
                "codex",
                "exec",
                "--model",
                "gpt-5-codex",
                "--config",
                "model_reasoning_effort=xhigh",
                "do the work",
            ],
        )

    def test_claude_model_options_append_after_base_argv(self) -> None:
        route = resolve_model_route("claude-code", requested_model="opus", requested_effort="high")
        argv = build_dispatch_argv("claude-code", "do the work", route)
        self.assertEqual(argv[-4:], ["--model", "opus", "--effort", "high"])
        self.assertEqual(argv[1], "-p")

    def test_unknown_owner_has_no_argv(self) -> None:
        self.assertIsNone(build_dispatch_argv("hermes", "do the work"))


class UnitModelRouteTests(unittest.TestCase):
    def test_unit_without_model_fields_stays_unrouted(self) -> None:
        self.assertIsNone(model_route_for_unit({"unit_id": "core"}, "codex"))

    def test_contract_embeds_model_route_when_unit_names_one(self) -> None:
        contract = build_fanout_contract(
            "split the sample feature across agents",
            [
                {"unit_id": "brain", "owner": "codex", "file_scope": ["src/a/"], "role": "brain"},
                {"unit_id": "ui", "owner": "claude-code", "file_scope": ["src/b/"], "model": "opus"},
                {"unit_id": "plain", "owner": "codex", "file_scope": ["src/c/"]},
            ],
        )
        units = {unit["unit_id"]: unit for unit in contract["units"]}
        brain_route = units["brain"]["handoff"]["model_route"]
        self.assertEqual(brain_route["selected_reasoning_effort"], "high")
        ui_route = units["ui"]["handoff"]["model_route"]
        self.assertEqual(ui_route["selected_model"], "opus")
        self.assertNotIn("model_route", units["plain"]["handoff"])


class ModelRouteCliTests(unittest.TestCase):
    def test_cli_resolves_route_json(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, stdout, stderr = run_cli(
                base + ["coding", "model-route", "--executor", "codex", "--role", "brain"]
            )
            self.assertEqual(status, 0, stderr)
            route = json.loads(stdout)
            self.assertEqual(route["schema_version"], CODING_MODEL_ROUTE_SCHEMA_VERSION)
            self.assertEqual(route["selected_reasoning_effort"], "high")


if __name__ == "__main__":
    unittest.main()
