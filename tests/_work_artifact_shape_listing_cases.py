"""Listing-side cases: shape advertisement, legacy copy compat, immutability.

Not a discovery module: collected only through
``tests/test_work_artifact_show_shape_action.py`` so each case runs exactly
once under both unittest discovery and pytest.
"""

from __future__ import annotations

import copy

from _local_package import load_local_package

load_local_package()

from _work_artifact_shape_payloads import WorkArtifactShapeSessionPayloads
from omh.surfaces.work_artifact_copy import (
    WORK_ARTIFACT_COPY_MANIFEST_SCHEMA_VERSION,
    build_work_artifact_copy_manifest,
)
from omh.wrapper.work_artifact_actions import (
    build_work_artifact_copy_action,
    build_work_artifact_show_shape_action,
)


class WorkArtifactShapeListingTests(WorkArtifactShapeSessionPayloads):
    """The copy action's listing advertises shapes without changing its contract."""

    def test_listing_advertises_shape_availability_per_artifact(self) -> None:
        # Given a prepared runtime handoff session status payload.
        status = self._status_payload(runtime_handoff=self._runtime_handoff_status())

        # When the copy action lists the work artifacts.
        listing = build_work_artifact_copy_action(status)

        # Then every entry advertises its shape, and only the handoff artifact
        # carries a facade-supported source schema.
        self.assertEqual(listing["action"], "list_work_artifacts")
        self.assertEqual(listing["next_action"], "show_status")
        by_id = {str(entry["artifact_id"]): entry for entry in listing["artifacts"]}
        handoff_shape = by_id["handoff_prompt"]["shape"]
        self.assertEqual(handoff_shape["availability"], "available")
        self.assertEqual(handoff_shape["reason"], "")
        self.assertEqual(
            handoff_shape["lenses"],
            ["flow", "structure", "state", "ownership"],
        )
        for artifact_id in (
            "acceptance_and_verification",
            "status_brief",
            "evidence_gaps",
            "next_action",
            "issue_pr_followup",
        ):
            self.assertEqual(
                (
                    by_id[artifact_id]["shape"]["availability"],
                    by_id[artifact_id]["shape"]["reason"],
                ),
                ("unavailable", "unsupported_source_schema"),
            )
            self.assertEqual(by_id[artifact_id]["shape"]["lenses"], [])
        # Copy availability stays independent of shape availability: the
        # prompt-only copy text is absent while the runtime shape is present.
        self.assertEqual(by_id["handoff_prompt"]["availability"], "unavailable")

    def test_listing_without_any_prepared_source_advertises_every_shape_unavailable(
        self,
    ) -> None:
        # Given a session payload with no briefing and no prepared handoffs.
        empty = {
            "schema_version": "wrapper_session_result/v1",
            "session_id": "wsession-empty",
        }

        # When the copy action lists the artifacts.
        listing = build_work_artifact_copy_action(empty)

        # Then every shape is advertised unavailable with the copy reason.
        for entry in listing["artifacts"]:
            self.assertEqual(
                (entry["shape"]["availability"], entry["shape"]["reason"]),
                ("unavailable", "source_not_recorded"),
            )
            self.assertEqual(entry["shape"]["lenses"], [])

    def test_actions_never_mutate_the_payload_and_copy_stays_legacy(self) -> None:
        # Given a prepared runtime handoff session payload.
        status = self._status_payload(runtime_handoff=self._runtime_handoff_status())
        before = copy.deepcopy(status)

        # When every action runs against it.
        build_work_artifact_copy_action(status)
        build_work_artifact_copy_action(status, artifact_id="status_brief")
        shape = build_work_artifact_show_shape_action(
            status, artifact_id="handoff_prompt", lens="ownership"
        )
        listing = build_work_artifact_copy_action(status)

        # Then the payload is byte-identical and the legacy copy outputs keep
        # their exact manifest v1 shape: no shape keys, no new fields.
        self.assertEqual(status, before)
        self.assertEqual(shape["next_action"], "show_status")
        selection = build_work_artifact_copy_action(status, artifact_id="status_brief")
        self.assertEqual(
            set(selection),
            {
                "schema_version",
                "session_id",
                "next_action",
                "claim_boundary",
                "action",
                "artifact",
            },
        )
        self.assertEqual(selection["action"], "select_work_artifact")
        self.assertTrue(str(selection["artifact"]["text"]))
        self.assertNotIn("shape", selection["artifact"])
        # When the payloads are narrowed to the mappings the legacy builder takes.
        briefing = status["coding_briefing"]
        prompt_handoff = status["prompt_handoff"]
        self.assertIsInstance(briefing, dict)
        self.assertIsInstance(prompt_handoff, dict)
        manifest = build_work_artifact_copy_manifest(
            briefing, prompt_handoff=prompt_handoff
        )
        self.assertEqual(
            manifest["schema_version"], WORK_ARTIFACT_COPY_MANIFEST_SCHEMA_VERSION
        )
        for entry in manifest["artifacts"]:
            self.assertEqual(
                set(entry),
                {
                    "artifact_id",
                    "label",
                    "artifact_type",
                    "source_schema",
                    "availability",
                    "reason",
                    "boundary",
                    "text",
                },
            )
        listed_ids = [str(entry["artifact_id"]) for entry in listing["artifacts"]]
        self.assertEqual(
            listed_ids,
            [
                "handoff_prompt",
                "acceptance_and_verification",
                "status_brief",
                "evidence_gaps",
                "next_action",
                "issue_pr_followup",
            ],
        )
        for entry in listing["artifacts"]:
            self.assertNotIn("text", entry)
