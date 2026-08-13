from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.routing_observation import (  # noqa: E402
    authenticate_child_observation,
    authenticate_executor_observation,
    build_routing_observation,
    render_routing_code_block_text,
    render_routing_status_rows,
    routing_surface_projection,
)
from omh.coding.status_board import build_status_board, render_status_board_text  # noqa: E402
from omh.paths import resolve_paths  # noqa: E402
from omh.wrapper.contract import build_chat_interaction_payload  # noqa: E402
from omh.wrapper.mission_control import build_mission_control  # noqa: E402
from omh.wrapper.sessions import create_or_resume_wrapper_session  # noqa: E402


_FANOUT_ID = "fanout-0123456789ab"


def _route() -> dict[str, object]:
    return {
        "schema_version": "coding_model_route/v2",
        "executor_profile": "codex",
        "status": "routed",
        "provenance": "recommendation_chain_head",
        "role": "implementation",
        "category": "deep",
        "domain": "coding",
        "selected_model": "openai-codex/gpt-5.6-sol",
        "selected_reasoning_effort": "high",
        "chain": [
            {"model_id": "openai-codex/gpt-5.6-sol", "reasoning_effort": "high"},
            {"model_id": "qwen-oauth/qwen3-coder", "reasoning_effort": "medium"},
        ],
    }


def _write_status_artifacts(root: Path) -> None:
    paths = resolve_paths(root / ".omh", root / ".hermes")
    fanout_dir = paths.fanout_contracts_dir / _FANOUT_ID
    fanout_dir.mkdir(parents=True, exist_ok=True)
    (fanout_dir / "fanout_contract.json").write_text(
        json.dumps(
            {
                "fanout_id": _FANOUT_ID,
                "units": [
                    {
                        "unit_id": "core",
                        "title": "Core work",
                        "handoff": {"model_route": _route()},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (fanout_dir / "dispatch_summary.json").write_text(
        json.dumps(
            {
                "fanout_id": _FANOUT_ID,
                "units": [
                    {
                        "unit_id": "core",
                        "run_ref": "run-core",
                        "owner": "codex",
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "high",
                        "status": "completed",
                        "duration_seconds": 12,
                        "tokens_total": 345,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class RoutingObservationSurfaceParityTests(unittest.TestCase):
    def test_cli_desktop_and_hosted_messages_share_payload_and_bytes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            _write_status_artifacts(root)
            board = build_status_board(paths, now="2026-08-13T00:00:00+00:00")
            observation = board["units"][0]["routing_observation"]
            expected = build_routing_observation(
                route=_route(),
                session_observation=authenticate_executor_observation({
                    "status": "completed",
                    "owner": "codex",
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "high",
                    "elapsed_seconds": 12,
                    "tokens": 345,
                    "run_id": "run-core",
                }),
            )
            self.assertEqual(observation, expected)

            started = create_or_resume_wrapper_session(paths, "inspect routing status", source="discord")
            session_id = str(started["session"]["session_id"])
            mission = build_mission_control(paths, session_id, routing_observation=observation)
            canonical_text = render_routing_code_block_text(observation)

            self.assertEqual(board["units"][0]["routing_status_rows"], list(render_routing_status_rows(observation)))
            self.assertIn(canonical_text, render_status_board_text(board))
            self.assertEqual(mission["routing_observation"], observation)
            self.assertEqual(mission["desktop_routing_code_block_text"], canonical_text)

            for source in ("discord", "slack", "hermes"):
                with self.subTest(source=source):
                    interaction = build_chat_interaction_payload(
                        "show coding route status",
                        source=source,
                        routing_observation=observation,
                    )
                    response = interaction["chat_response"]
                    self.assertEqual(interaction["routing_observation"], observation)
                    self.assertEqual(response["routing_code_block_text"], canonical_text)
                    blocks = response["messenger_rendering"]["body_blocks"]
                    routing_blocks = [
                        block for block in blocks
                        if block.get("type") == "code_block" and block.get("text") == canonical_text
                    ]
                    self.assertEqual(len(routing_blocks), 1)

            serialized = json.dumps({"board": board, "mission": mission}, sort_keys=True)
            self.assertNotIn("inspect routing status", serialized)
            self.assertNotIn("prompt", serialized.casefold())
            self.assertNotIn("turn 0", canonical_text)
            self.assertNotIn("tools 0", canonical_text)
            self.assertNotIn("cost $0", canonical_text)

    def test_genuine_observed_zero_has_byte_parity_on_every_surface(self) -> None:
        observation = build_routing_observation(
            route=_route(),
            session_observation=authenticate_executor_observation({
                "status": "running",
                "turn": 0,
                "tools": 0,
                "elapsed_seconds": 0.0,
                "tokens": 0,
                "cost_usd": 0.0,
                "rate_tokens_per_second": 0.0,
            }),
        )
        canonical_text = render_routing_code_block_text(observation)
        self.assertIn(
            "METRICS turn 0  tools 0  elapsed 0.0s  tokens 0  cost $0.0  rate 0.0 tok/s",
            canonical_text,
        )
        projection = routing_surface_projection(observation)
        self.assertEqual("\n".join(projection["cli_status_rows"]), canonical_text)
        self.assertEqual(projection["desktop_code_block_text"], canonical_text)
        self.assertEqual(projection["messaging_code_block_text"], canonical_text)

        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, "inspect zero metrics", source="discord")
            mission = build_mission_control(
                paths,
                str(started["session"]["session_id"]),
                routing_observation=observation,
            )
            self.assertEqual(mission["desktop_routing_code_block_text"], canonical_text)
            for source in ("discord", "slack", "hermes"):
                with self.subTest(source=source):
                    interaction = build_chat_interaction_payload(
                        "show zero metrics",
                        source=source,
                        routing_observation=observation,
                    )
                    self.assertEqual(interaction["chat_response"]["routing_code_block_text"], canonical_text)

    def test_shared_surface_projection_rejects_claim_status_exploit(self) -> None:
        prepared = build_routing_observation(route=_route())
        with self.assertRaisesRegex(ValueError, "observed claim must not use prepared status"):
            routing_surface_projection({**prepared, "claim": "observed"})

    def test_category_is_canonicalized_in_observation(self) -> None:
        observation = build_routing_observation(
            route={**_route(), "category": "ulw-visual"},
        )
        self.assertEqual(observation["category"], "visual-engineering")
        self.assertIn("category visual-engineering", render_routing_code_block_text(observation))

    def test_hermes_child_record_projects_without_dispatch_module_coupling(self) -> None:
        observation = build_routing_observation(
            route={**_route(), "executor_profile": "hermes"},
            child_dispatch=authenticate_child_observation({
                "status": "running",
                "parent_run_id": "parent-1",
                "run_id": "child-1",
                "model": "qwen3-coder",
                "usage": {
                    "provider": "qwen-oauth",
                    "model": "qwen3-coder",
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                },
                "prompt": "raw secret prompt",
            }),
        )
        self.assertEqual(observation["claim"], "observed")
        self.assertEqual(observation["status"], "running")
        self.assertEqual(observation["selected_owner"], "hermes")
        self.assertEqual(observation["selected_provider"], "qwen-oauth")
        self.assertEqual(observation["selected_model"], "qwen3-coder")
        self.assertEqual(observation["tokens"], 0)
        self.assertEqual(observation["cost_usd"], 0.0)
        self.assertIn("tokens 0", render_routing_code_block_text(observation))
        self.assertNotIn("raw secret prompt", json.dumps(observation))


if __name__ == "__main__":
    unittest.main()
