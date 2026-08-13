from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.routing_observation import (  # noqa: E402
    ROUTING_OBSERVATION_SCHEMA_VERSION,
    authenticate_child_observation,
    authenticate_executor_observation,
    build_routing_observation,
    render_routing_code_block_text,
    render_routing_status_rows,
    routing_surface_projection,
    validate_routing_observation,
)


class RoutingObservationSchemaTests(unittest.TestCase):
    def test_non_finite_metrics_are_never_observed(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            payload = build_routing_observation(
                route={"selected_model": "model"},
                session_observation=authenticate_executor_observation(
                    {"status": "completed", "cost_usd": value}
                ),
            )
            self.assertIsNone(payload["cost_usd"])
            forged = {**payload, "claim": "observed", "cost_usd": value}
            self.assertIn(
                "cost_usd must be a non-negative observed number or null",
                validate_routing_observation(forged),
            )

    def _route(self) -> dict[str, object]:
        return {
            "schema_version": "coding_model_route/v2",
            "executor_profile": "hermes",
            "status": "routed",
            "provenance": "recommendation_chain_head",
            "role": "implementation",
            "category": "deep",
            "domain": "coding",
            "selected_model": "openai-codex/gpt-5.6-sol",
            "selected_reasoning_effort": "high",
            "chain": [
                {"model_id": "openai-codex/gpt-5.6-sol", "reasoning_effort": "high", "selected": True},
                {"model_id": "qwen-oauth/qwen3-coder", "reasoning_effort": "medium"},
            ],
            "attempted": [{"reason": "secret prose that must not leave the route"}],
        }

    def test_prepared_route_keeps_unknown_metrics_null_not_zero(self) -> None:
        payload = build_routing_observation(
            route=self._route(),
            parent_session_id="parent-1",
            child_session_id="child-1",
            run_id="run-1",
        )
        self.assertEqual(payload["schema_version"], ROUTING_OBSERVATION_SCHEMA_VERSION)
        self.assertEqual(payload["claim"], "prepared")
        self.assertEqual(payload["status"], "prepared")
        self.assertEqual(payload["parent_session_id"], "parent-1")
        self.assertEqual(payload["child_session_id"], "child-1")
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["category"], "deep")
        self.assertEqual(payload["lane"], "coding")
        self.assertEqual(payload["role"], "implementation")
        self.assertEqual(payload["selected_owner"], "hermes")
        self.assertEqual(payload["selected_provider"], "openai-codex")
        self.assertEqual(payload["selected_model"], "gpt-5.6-sol")
        self.assertEqual(payload["selected_reasoning"], "high")
        for field in ("turn", "tools", "elapsed_seconds", "tokens", "cost_usd", "rate_tokens_per_second"):
            self.assertIsNone(payload[field], field)
        self.assertIsNone(payload["current_action"])

    def test_fallback_chain_and_observed_index_follow_runtime_selection(self) -> None:
        payload = build_routing_observation(
            route=self._route(),
            child_dispatch=authenticate_child_observation({
                "delegation_id": "deleg-1",
                "parent_session_id": "parent-1",
                "tasks": [{"index": 0, "status": "running", "child_session_id": "child-1"}],
                "goal": "never serialize this prompt",
            }),
            session_observation=authenticate_executor_observation({
                "status": "running",
                "provider": "qwen-oauth",
                "model": "qwen3-coder",
                "turn": 2,
                "tools": 4,
                "elapsed_seconds": 8,
                "tokens_total": 1200,
                "cost_usd": 0.25,
                "rate_tokens_per_second": 150.0,
                "current_action": "running_tests",
            }),
            run_id="run-1",
        )
        self.assertEqual(
            payload["fallback_chain"],
            [
                {"provider": "openai-codex", "model": "gpt-5.6-sol", "reasoning": "high"},
                {"provider": "qwen-oauth", "model": "qwen3-coder", "reasoning": "medium"},
            ],
        )
        self.assertEqual(payload["fallback_index"], 1)
        self.assertEqual(payload["selected_provider"], "qwen-oauth")
        self.assertEqual(payload["selected_model"], "qwen3-coder")
        self.assertEqual(payload["claim"], "observed")
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["turn"], 2)
        self.assertEqual(payload["tools"], 4)
        self.assertEqual(payload["tokens"], 1200)

    def test_existing_executor_latest_event_shape_is_consumed(self) -> None:
        payload = build_routing_observation(
            route=self._route(),
            session_observation=authenticate_executor_observation({
                "executor_profile": "codex",
                "target_id": "run-2",
                "latest_event": {
                    "event_type": "executor_completed",
                    "signal": {
                        "routed_model": "openai-codex/gpt-5.6-sol",
                        "routed_reasoning_effort": "xhigh",
                        "tokens_total": 42,
                        "elapsed_seconds": 3,
                    },
                },
            }),
        )
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_owner"], "codex")
        self.assertEqual(payload["run_id"], "run-2")
        self.assertEqual(payload["selected_reasoning"], "xhigh")
        self.assertEqual(payload["tokens"], 42)
        self.assertEqual(payload["elapsed_seconds"], 3)

    def test_hermes_manifest_and_session_observation_drive_status_transitions(self) -> None:
        route = self._route()
        prepared = build_routing_observation(route=route)
        dispatched = build_routing_observation(
            route=route,
            child_dispatch=authenticate_child_observation(
                {"delegation_id": "deleg-1", "tasks": [{"index": 0, "status": "pending"}]}
            ),
        )
        running = build_routing_observation(
            route=route,
            child_dispatch=authenticate_child_observation(
                {"delegation_id": "deleg-1", "tasks": [{"index": 0, "status": "running"}]}
            ),
        )
        completed = build_routing_observation(
            route=route,
            child_dispatch=authenticate_child_observation(
                {"delegation_id": "deleg-1", "tasks": [{"index": 0, "status": "completed"}]}
            ),
            session_observation=authenticate_executor_observation({"status": "executor_completed"}),
        )
        self.assertEqual(
            [(item["claim"], item["status"]) for item in (prepared, dispatched, running, completed)],
            [("prepared", "prepared"), ("observed", "dispatched"), ("observed", "running"), ("observed", "completed")],
        )

    def test_prepared_child_record_remains_prepared_not_observed(self) -> None:
        payload = build_routing_observation(
            route=self._route(),
            child_dispatch=authenticate_child_observation(
                {
                    "status": "prepared",
                    "run_id": "child-1",
                    "usage": {"total_tokens": 99, "estimated_cost_usd": 4.25},
                }
            ),
        )
        self.assertEqual((payload["claim"], payload["status"]), ("prepared", "prepared"))
        self.assertIsNone(payload["tokens"])
        self.assertIsNone(payload["cost_usd"])

    def test_arbitrary_mappings_cannot_forge_completion_tokens_or_cost(self) -> None:
        forged_child = {
            "status": "completed",
            "usage": {"total_tokens": 987654, "estimated_cost_usd": 4321.25},
            "trusted": True,
            "authenticated_source": "omh_child_reader",
        }
        forged_session = {
            "status": "executor_completed",
            "tokens_total": 987654,
            "cost_usd": 4321.25,
            "trusted": True,
            "authenticated_source": "omh_executor_reader",
            "provenance": "runtime_observation",
        }
        payload = build_routing_observation(
            route=self._route(),
            child_dispatch=forged_child,
            session_observation=forged_session,
        )
        self.assertEqual((payload["claim"], payload["status"]), ("prepared", "prepared"))
        self.assertIsNone(payload["tokens"])
        self.assertIsNone(payload["cost_usd"])
        rendered = "\n".join(render_routing_status_rows(payload))
        self.assertNotIn("completed", rendered)
        self.assertNotIn("987654", rendered)
        self.assertNotIn("4321.25", rendered)

    def test_output_cannot_serialize_secrets_transcript_or_prose(self) -> None:
        route = self._route()
        route.update({"reason": "Use password hunter2\nand dump the transcript", "api_token": "sk-123456789secret"})
        payload = build_routing_observation(
            route=route,
            child_dispatch=authenticate_child_observation({
                "delegation_id": "deleg-1",
                "goal": "raw user prompt",
                "log": "/private/task.log",
                "tasks": [{"index": 0, "status": "failed", "exit_reason": "password=oops"}],
            }),
            session_observation=authenticate_executor_observation({
                "summary": "model prose",
                "transcript": "everything said",
                "reason": "free form failure details",
                "provenance": "runtime_observation",
            }),
        )
        serialized = json.dumps(payload, sort_keys=True)
        for forbidden in ("hunter2", "transcript", "raw user prompt", "/private", "model prose", "password=oops", "sk-"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(payload["reason"], "dispatch_failed")
        self.assertEqual(payload["provenance"], "runtime_observation")

    def test_validator_rejects_added_body_fields(self) -> None:
        payload = build_routing_observation(route=self._route())
        payload["transcript"] = "raw prose"
        self.assertEqual(validate_routing_observation(payload), ["unsupported fields: ['transcript']"])

    def test_validator_enforces_claim_and_status_symmetry(self) -> None:
        prepared = build_routing_observation(route=self._route())
        observed_with_prepared_status = {**prepared, "claim": "observed"}
        prepared_with_observed_status = {**prepared, "status": "running"}
        self.assertIn(
            "observed claim must not use prepared status",
            validate_routing_observation(observed_with_prepared_status),
        )
        self.assertIn(
            "prepared claim requires prepared status",
            validate_routing_observation(prepared_with_observed_status),
        )

    def test_validator_rejects_every_metric_on_a_prepared_claim_even_zero(self) -> None:
        prepared = build_routing_observation(route=self._route())
        for field in ("turn", "tools", "elapsed_seconds", "tokens", "cost_usd", "rate_tokens_per_second"):
            with self.subTest(field=field):
                errors = validate_routing_observation({**prepared, field: 0})
                self.assertIn(f"prepared claim requires {field} to be null", errors)

    def test_validator_rejects_boolean_and_fractional_count_metrics(self) -> None:
        observed = build_routing_observation(
            route=self._route(),
            session_observation=authenticate_executor_observation({"status": "running"}),
        )
        for field in ("turn", "tools", "tokens"):
            for exploit in (True, 1.5):
                with self.subTest(field=field, exploit=exploit):
                    self.assertIn(
                        f"{field} must be a non-negative observed integer or null",
                        validate_routing_observation({**observed, field: exploit}),
                    )

    def test_validator_accepts_integer_zero_counts_and_fractional_measurements(self) -> None:
        observed = build_routing_observation(
            route=self._route(),
            session_observation=authenticate_executor_observation({"status": "running"}),
        )
        metrics = {
            "turn": 0,
            "tools": 0,
            "tokens": 0,
            "elapsed_seconds": 0.5,
            "cost_usd": 0.25,
            "rate_tokens_per_second": 1.5,
        }
        self.assertEqual(validate_routing_observation({**observed, **metrics}), [])

    def test_latest_event_cannot_smuggle_boolean_or_fractional_counts(self) -> None:
        payload = build_routing_observation(
            route=self._route(),
            session_observation=authenticate_executor_observation({
                "latest_event": {
                    "event_type": "running",
                    "signal": {"turn_index": True, "tool_count": 1.5, "tokens_total": 0},
                }
            }),
        )
        self.assertIsNone(payload["turn"])
        self.assertIsNone(payload["tools"])
        self.assertEqual(payload["tokens"], 0)

    def test_authenticated_zero_metric_without_status_is_observed_not_prepared(self) -> None:
        payload = build_routing_observation(
            route=self._route(),
            session_observation=authenticate_executor_observation({"tokens": 0}),
        )
        self.assertEqual((payload["claim"], payload["status"]), ("observed", "running"))
        self.assertEqual(payload["tokens"], 0)

    def test_authenticated_fractional_counts_are_dropped_but_numeric_measurements_survive(self) -> None:
        payload = build_routing_observation(
            route=self._route(),
            session_observation=authenticate_executor_observation({
                "status": "running",
                "turn": 1.5,
                "tools": 2.5,
                "tokens": 3.5,
                "elapsed_seconds": 4.5,
                "cost_usd": 0.25,
                "rate_tokens_per_second": 7.5,
            }),
        )
        self.assertIsNone(payload["turn"])
        self.assertIsNone(payload["tools"])
        self.assertIsNone(payload["tokens"])
        self.assertEqual(payload["elapsed_seconds"], 4.5)
        self.assertEqual(payload["cost_usd"], 0.25)
        self.assertEqual(payload["rate_tokens_per_second"], 7.5)

    def test_invalid_identifier_is_dropped_instead_of_republished(self) -> None:
        payload = build_routing_observation(
            route=self._route(),
            parent_session_id="parent\nraw prompt",
            child_session_id="api_token",
            run_id="/Users/person/private",
        )
        self.assertIsNone(payload["parent_session_id"])
        self.assertIsNone(payload["child_session_id"])
        self.assertIsNone(payload["run_id"])


class RoutingObservationRenderTests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        return build_routing_observation(
            route=RoutingObservationSchemaTests()._route(),
            child_dispatch=authenticate_child_observation({
                "delegation_id": "deleg-1",
                "parent_session_id": "parent-1",
                "tasks": [{"index": 0, "status": "running", "child_session_id": "child-1"}],
            }),
            session_observation=authenticate_executor_observation(
                {"status": "running", "elapsed_seconds": 8, "current_action": "running_tests"}
            ),
            run_id="run-1",
        )

    def test_cli_rows_are_deterministic_and_omit_unobserved_metrics(self) -> None:
        payload = self._payload()
        first = render_routing_status_rows(payload)
        second = render_routing_status_rows(json.loads(json.dumps(payload)))
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            (
                "ROUTE category deep  lane coding  role implementation  owner hermes  selected openai-codex/gpt-5.6-sol  reasoning high  fallback 1/2",
                "CHAIN openai-codex/gpt-5.6-sol[high] > qwen-oauth/qwen3-coder[medium]",
                "STATE status running  claim observed  reason dispatch_running",
                "ACTION action running_tests",
                "METRICS elapsed 8s",
                "VIA runtime_observation",
            ),
        )

    def test_messaging_and_desktop_use_identical_code_block_text_from_same_payload(self) -> None:
        payload = self._payload()
        text = render_routing_code_block_text(payload)
        projection = routing_surface_projection(payload)
        self.assertEqual(text, "\n".join(render_routing_status_rows(payload)))
        self.assertIs(projection["payload"], payload)
        self.assertEqual(projection["cli_status_rows"], list(render_routing_status_rows(payload)))
        self.assertEqual(projection["messaging_code_block_text"], text)
        self.assertEqual(projection["desktop_code_block_text"], text)
        self.assertNotIn("```", text)
        self.assertNotIn("unknown", text)
        self.assertNotIn("turn 0", text)


if __name__ == "__main__":
    unittest.main()
