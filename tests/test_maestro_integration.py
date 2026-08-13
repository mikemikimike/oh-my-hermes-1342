from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.coding.maestro import ExternalHandoffRequest, HermesNativeSelectionError  # noqa: E402
from omh.wrapper_contract import build_chat_interaction_payload  # noqa: E402
from omh.paths import resolve_paths  # noqa: E402
from omh.wrapper.executor_sessions import (  # noqa: E402
    maestro_for_executor_session,
    open_executor_session,
    record_executor_session_result,
)
from omh.wrapper_sessions import (  # noqa: E402
    create_or_resume_wrapper_session,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    select_wrapper_session_executor,
)


MESSAGE = "risky refactor"
EXTERNAL_PROFILES = (
    "codex",
    "claude-code",
    "generic",
    "omo-runtime",
    "omx-runtime",
    "omc-runtime",
)
_HANDOFF_FIELD = {
    "codex": "executor_handoff",
    "claude-code": "prompt_handoff",
    "generic": "prompt_handoff",
    "omo-runtime": "runtime_handoff",
    "omx-runtime": "runtime_handoff",
    "omc-runtime": "runtime_handoff",
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


class MaestroProductionPreparationTests(unittest.TestCase):
    def test_maestro_projects_category_and_ordered_recommendation_chain(self) -> None:
        recommendation = {
            "schema_version": "model_recommendation_resolution/v1",
            "owner": "maestro",
            "status": "resolved",
            "selector": {"surface": "categories", "name": "quick"},
            "projection": {
                "kind": "maestro_ordered_chain",
                "chain": [
                    {
                        "model_alias": "glm-5.2-ultrafast",
                        "provider": "zai",
                        "model_id": "glm-5.2-ultrafast",
                    }
                ],
            },
        }
        prepared = __import__(
            "omh.coding.maestro", fromlist=["build_external_handoff"]
        ).build_external_handoff(
            ExternalHandoffRequest(
                message="Use ulw-quick to implement the fix",
                profile="codex",
                model_recommendation=recommendation,
            )
        )

        self.assertEqual(prepared.handoff["model_route_category"], "quick")
        projection = prepared.handoff["maestro_model_projection"]
        self.assertEqual(projection["kind"], "maestro_ordered_chain")
        self.assertEqual(projection["chain"][0]["model_alias"], "glm-5.2-ultrafast")
        self.assertEqual(projection["status"], "prepared_not_observed")

    def test_wrapper_external_preparation_crosses_maestro_without_changing_handoff_or_dispatching(self) -> None:
        from omh.coding.maestro import facade

        for profile in EXTERNAL_PROFILES:
            prepared_handoffs = []
            real_prepare = facade.build_external_handoff

            def capture(request: ExternalHandoffRequest):
                prepared = real_prepare(request)
                prepared_handoffs.append(prepared)
                return prepared

            with self.subTest(profile=profile), mock.patch.object(
                facade,
                "build_external_handoff",
                side_effect=capture,
            ) as prepare:
                interaction = build_chat_interaction_payload(
                    MESSAGE,
                    source="discord",
                    mode="delegate",
                    executor_target=profile,
                )

                prepare.assert_called_once()
                prepared = prepared_handoffs[0]
                field = _HANDOFF_FIELD[profile]
                self.assertEqual(prepare.call_args.args[0].profile, profile)
                self.assertEqual(
                    _canonical_bytes(interaction["delegation"][field]),
                    _canonical_bytes(prepared.handoff),
                )
                self.assertEqual(prepared.handoff["status"], "prepared_not_observed")
                self.assertFalse(prepared.capability.executes_work)
                self.assertNotIn("dispatch_observed", prepared.handoff)

    def test_wrapper_hermes_preparation_stays_native(self) -> None:
        from omh.coding.maestro import facade

        with mock.patch.object(
            facade,
            "build_external_handoff",
            wraps=facade.build_external_handoff,
        ) as prepare:
            interaction = build_chat_interaction_payload(
                MESSAGE,
                source="discord",
                mode="delegate",
                executor_target="hermes",
            )

        prepare.assert_not_called()
        self.assertEqual(interaction["delegation"]["selected_executor_profile"], "hermes")
        self.assertIn("runtime_handoff", interaction["delegation"])
        self.assertNotIn("maestro", str(interaction["delegation"]).casefold())


class MaestroExecutorSessionIntegrationTests(unittest.TestCase):
    def test_external_profiles_share_prepare_status_and_observation_contracts(self) -> None:
        for profile in EXTERNAL_PROFILES:
            with self.subTest(profile=profile), TemporaryDirectory() as tmp:
                paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
                started = create_or_resume_wrapper_session(paths, MESSAGE, source="discord")
                session_id = str(started["session"]["session_id"])
                record_plan_decision(paths, session_id, "accept")
                select_wrapper_session_executor(paths, session_id, profile)
                prepared_session = prepare_wrapper_session_handoff(paths, session_id, MESSAGE)["session"]
                maestro = maestro_for_executor_session(paths, prepared_session)

                prepared = maestro.prepare(
                    ExternalHandoffRequest(
                        message=MESSAGE,
                        source="discord",
                        profile=profile,
                    )
                )
                initial_status = maestro.status(prepared)
                initial_observations = maestro.observations(prepared)

                self.assertEqual(prepared.capability.profile, profile)
                self.assertEqual(initial_status["schema_version"], "executor_session_status/v1")
                self.assertEqual(initial_status["selected_executor_profile"], profile)
                self.assertEqual(initial_status["dispatch"], "not_observed")
                self.assertEqual(initial_observations, ())

                open_executor_session(
                    paths,
                    session_id,
                    observed=True,
                    external_session_ref=f"{profile}-session-1",
                    evidence_refs=[f"session:{profile}-1"],
                )
                record_executor_session_result(
                    paths,
                    session_id,
                    result="completed",
                    evidence_refs=[f"result:{profile}-1"],
                )
                observed_status = maestro.status(prepared)
                observations = maestro.observations(prepared)

                self.assertEqual(observed_status["dispatch"], "observed")
                self.assertEqual(observed_status["result"], "completed")
                self.assertEqual(
                    [(item["event"], item["status"]) for item in observations],
                    [("dispatch", "observed"), ("result", "completed")],
                )
                self.assertNotIn(MESSAGE, str(observations))

    def test_hermes_native_session_never_builds_a_maestro_facade(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            started = create_or_resume_wrapper_session(paths, MESSAGE, source="hermes")
            session_id = str(started["session"]["session_id"])
            record_plan_decision(paths, session_id, "accept")
            select_wrapper_session_executor(paths, session_id, "hermes")
            session = prepare_wrapper_session_handoff(paths, session_id, MESSAGE)["session"]

            with self.assertRaisesRegex(
                HermesNativeSelectionError,
                "Hermes-native selection bypasses maestro",
            ):
                maestro_for_executor_session(paths, session)


if __name__ == "__main__":
    unittest.main()
