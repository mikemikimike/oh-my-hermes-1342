from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from typing import Mapping

from _local_package import load_local_package

load_local_package()
from omh.coding_delegation import (  # noqa: E402
    build_coding_delegation_payload,
    coding_delegation_record_payload,
)
from omh.coding.coding_delegation import _build_coding_delegation_payload_native  # noqa: E402
from omh.executors import (  # noqa: E402
    EXECUTOR_HANDOFF_SCHEMA_VERSION,
    PROMPT_HANDOFF_SCHEMA_VERSION,
    RUNTIME_HANDOFF_SCHEMA_VERSION,
)
from omh.coding.maestro import (  # noqa: E402
    ExternalHandoffRequest,
    HermesNativeSelectionError,
    Maestro,
    PreparedExternalHandoff,
    build_external_handoff,
)


MESSAGE = "risky refactor"
EXTERNAL_PROFILE_LANES = {
    "codex": ("external_executor", "executor_handoff", EXECUTOR_HANDOFF_SCHEMA_VERSION, True),
    "claude-code": ("prompt_only_handoff", "prompt_handoff", PROMPT_HANDOFF_SCHEMA_VERSION, False),
    "omx-runtime": ("runtime_handoff", "runtime_handoff", RUNTIME_HANDOFF_SCHEMA_VERSION, False),
    "omo-runtime": ("runtime_handoff", "runtime_handoff", RUNTIME_HANDOFF_SCHEMA_VERSION, False),
    "omc-runtime": ("runtime_handoff", "runtime_handoff", RUNTIME_HANDOFF_SCHEMA_VERSION, False),
    "generic": ("prompt_only_handoff", "prompt_handoff", PROMPT_HANDOFF_SCHEMA_VERSION, False),
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


class CurrentCodingHandoffCharacterizationTests(unittest.TestCase):
    """Characterize coding handoffs, unrelated to the awesome-catalog Maestro."""

    def test_external_profiles_have_one_stable_handoff_lane(self) -> None:
        for profile, (owner_mode, field, schema_version, dispatchable) in EXTERNAL_PROFILE_LANES.items():
            with self.subTest(profile=profile):
                payload = build_coding_delegation_payload(
                    MESSAGE,
                    source="discord",
                    executor_target=profile,
                )

                self.assertEqual(payload["work_owner_mode"], owner_mode)
                self.assertEqual(payload["selected_executor_profile"], profile)
                self.assertIs(payload["dispatchable"], dispatchable)
                self.assertEqual(
                    [key for key in ("executor_handoff", "prompt_handoff", "runtime_handoff") if key in payload],
                    [field],
                )
                self.assertEqual(payload[field]["schema_version"], schema_version)

    def test_record_preserves_handoff_fields_and_canonical_bytes(self) -> None:
        for profile, (_, field, _, _) in EXTERNAL_PROFILE_LANES.items():
            with self.subTest(profile=profile):
                payload = build_coding_delegation_payload(
                    MESSAGE,
                    source="discord",
                    executor_target=profile,
                )
                record = coding_delegation_record_payload(payload, MESSAGE)

                self.assertEqual(record[field], payload[field])
                self.assertEqual(_canonical_bytes(record[field]), _canonical_bytes(payload[field]))


@dataclass
class _StatusAdapter:
    received: PreparedExternalHandoff | None = None

    def status_for(self, handoff: PreparedExternalHandoff) -> Mapping[str, object]:
        self.received = handoff
        return {"status": "prepared_not_observed", "profile": handoff.capability.profile}


@dataclass
class _ObservationAdapter:
    received: PreparedExternalHandoff | None = None

    def observations_for(self, handoff: PreparedExternalHandoff) -> tuple[Mapping[str, object], ...]:
        self.received = handoff
        return ({"event": "prepared", "profile": handoff.capability.profile},)


class MaestroExternalHandoffFacadeTests(unittest.TestCase):
    def test_facade_preserves_builder_payload_bytes_and_handoff_field(self) -> None:
        for profile, (_, field, _, _) in EXTERNAL_PROFILE_LANES.items():
            with self.subTest(profile=profile):
                request = ExternalHandoffRequest(message=MESSAGE, source="discord", profile=profile)
                expected = _build_coding_delegation_payload_native(
                    MESSAGE,
                    source="discord",
                    executor_target=profile,
                )

                prepared = build_external_handoff(request)

                self.assertEqual(prepared.handoff_field, field)
                self.assertEqual(prepared.payload, expected)
                self.assertEqual(_canonical_bytes(prepared.payload), _canonical_bytes(expected))
                self.assertEqual(prepared.handoff, expected[field])

    def test_capability_describes_coordination_without_executor_claim(self) -> None:
        prepared = build_external_handoff(
            ExternalHandoffRequest(message=MESSAGE, source="discord", profile="codex")
        )

        self.assertEqual(prepared.capability.profile, "codex")
        self.assertEqual(prepared.capability.work_owner_mode, "external_executor")
        self.assertTrue(prepared.capability.dispatchable)
        self.assertFalse(prepared.capability.executes_work)
        self.assertEqual(prepared.capability.observation_boundary, "prepared_not_observed")

    def test_hermes_native_selection_is_rejected_before_building(self) -> None:
        with self.assertRaisesRegex(
            HermesNativeSelectionError,
            "Hermes-native selection bypasses maestro",
        ):
            build_external_handoff(
                ExternalHandoffRequest(message=MESSAGE, source="discord", profile="hermes")
            )

    def test_status_and_observation_adapters_receive_prepared_handoff(self) -> None:
        status_adapter = _StatusAdapter()
        observation_adapter = _ObservationAdapter()
        maestro = Maestro(
            status_adapter=status_adapter,
            observation_adapter=observation_adapter,
        )
        prepared = maestro.prepare(
            ExternalHandoffRequest(message=MESSAGE, source="discord", profile="omo-runtime")
        )

        status = maestro.status(prepared)
        observations = maestro.observations(prepared)

        self.assertIs(status_adapter.received, prepared)
        self.assertIs(observation_adapter.received, prepared)
        self.assertEqual(status["status"], "prepared_not_observed")
        self.assertEqual(observations[0]["event"], "prepared")


if __name__ == "__main__":
    unittest.main()
