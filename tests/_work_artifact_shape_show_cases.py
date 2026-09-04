"""Show-action cases: rendering, unavailable paths, Mermaid gating, privacy.

Not a discovery module: collected only through
``tests/test_work_artifact_show_shape_action.py`` so each case runs exactly
once under both unittest discovery and pytest.
"""

from __future__ import annotations

import copy

from _local_package import load_local_package

load_local_package()

from _work_artifact_shape_payloads import (
    PROMPT_HANDOFF,
    WorkArtifactShapeSessionPayloads,
)
from omh.surfaces.show_shape_models import ShowShapeCapabilities
from omh.wrapper.work_artifact_actions import (
    SHOW_SHAPE_ACTION,
    build_work_artifact_copy_action,
    build_work_artifact_show_shape_action,
)


class WorkArtifactShowShapeActionTests(WorkArtifactShapeSessionPayloads):
    """The shape action renders through the committed facade or says why not."""

    def test_show_shape_renders_exact_schema_evidence_and_refs_within_budget(
        self,
    ) -> None:
        # Given the same prepared runtime handoff session.
        status = self._status_payload(runtime_handoff=self._runtime_handoff_status())

        # When the shape action renders the handoff artifact's state shape.
        result = build_work_artifact_show_shape_action(
            status, artifact_id="handoff_prompt", lens="state"
        )

        # Then the committed facade's exact source identity is preserved and
        # the body stays inside the render budget.
        self.assertEqual(result["action"], SHOW_SHAPE_ACTION)
        self.assertEqual(SHOW_SHAPE_ACTION, "show_work_artifact_shape")
        self.assertEqual(result["next_action"], "show_status")
        self.assertEqual(result["schema_version"], "work_artifact_copy_manifest/v1")
        shape = result["shape"]
        self.assertIsInstance(shape, dict)
        self.assertEqual(shape["schema_version"], "work_artifact_show_shape/v1")
        self.assertEqual(shape["availability"], "available")
        self.assertEqual(
            shape["source_artifact_id"], f"{self.SESSION_ID}#runtime_handoff"
        )
        self.assertEqual(shape["source_schema"], "coding_runtime_handoff/v1")
        self.assertEqual(shape["evidence_state"], "prepared_not_observed")
        self.assertEqual(shape["lens"], "state")
        self.assertEqual(shape["format"], "ascii")
        self.assertIn(f"{self.SESSION_ID}#runtime_handoff.status", shape["body"])
        self.assertIn(
            f"{self.SESSION_ID}#runtime_handoff.observation_contract", shape["body"]
        )
        self.assertLessEqual(len(shape["body"]), 4000)
        self.assertLessEqual(len(shape["bullets"]), 3)
        self.assertTrue(
            any(item["reason"] == "bullet_limit" for item in shape["omissions"])
        )
        self.assertTrue(shape["legend"])
        self.assertIn("not", shape["claim_boundary"])

    def test_every_recorded_briefing_artifact_has_a_traceable_shape(self) -> None:
        prompt_status = self._status_payload(prompt_handoff=PROMPT_HANDOFF)
        briefing = copy.deepcopy(prompt_status["coding_briefing"])
        briefing["run_id"] = "run-shape"
        run_status = self._status_payload(
            prompt_handoff=PROMPT_HANDOFF,
            briefing=briefing,
        )
        cases = (
            (prompt_status, "handoff_prompt", "ownership", "coding_prompt_handoff/v1"),
            (prompt_status, "acceptance_and_verification", "flow", "coding_briefing/v1"),
            (prompt_status, "status_brief", "state", "coding_briefing/v1"),
            (prompt_status, "evidence_gaps", "state", "coding_briefing/v1"),
            (prompt_status, "next_action", "ownership", "coding_briefing/v1"),
            (run_status, "issue_pr_followup", "flow", "coding_briefing/v1"),
        )

        for status, artifact_id, lens, source_schema in cases:
            with self.subTest(artifact_id=artifact_id, lens=lens):
                result = build_work_artifact_show_shape_action(
                    status,
                    artifact_id=artifact_id,
                    lens=lens,
                )
                shape = result["shape"]
                self.assertIsInstance(shape, dict)
                self.assertEqual(shape["availability"], "available")
                self.assertEqual(shape["source_schema"], source_schema)
                self.assertEqual(shape["evidence_state"], "prepared_not_observed")
                self.assertTrue(shape["nodes"])
                self.assertTrue(
                    all(node["source_refs"] for node in shape["nodes"])
                )
                self.assertTrue(
                    all(edge["source_refs"] for edge in shape["edges"])
                )

    def test_missing_artifact_lens_format_and_schema_return_unavailable(self) -> None:
        # Given a runtime handoff session, a prompt-only session, and an empty one.
        runtime_status = self._status_payload(
            runtime_handoff=self._runtime_handoff_status()
        )
        empty = {
            "schema_version": "wrapper_session_result/v1",
            "session_id": "wsession-empty",
        }

        # When shapes are requested for unknown ids, missing sources,
        # unsupported lenses and formats, and unsupported source schemas.
        unknown = build_work_artifact_show_shape_action(
            runtime_status, artifact_id="does_not_exist"
        )
        no_source = build_work_artifact_show_shape_action(
            empty, artifact_id="handoff_prompt"
        )
        bad_lens = build_work_artifact_show_shape_action(
            runtime_status, artifact_id="handoff_prompt", lens="causal"
        )
        change_lens = build_work_artifact_show_shape_action(
            runtime_status, artifact_id="handoff_prompt", lens="change"
        )
        bad_format = build_work_artifact_show_shape_action(
            runtime_status, artifact_id="handoff_prompt", format="svg"
        )

        # Then every case is an explicit unavailable shape, never a guess.
        for result, reason in (
            (unknown, "unknown_artifact_id"),
            (no_source, "source_not_recorded"),
            (bad_lens, "unsupported_lens"),
            (change_lens, "lens_not_supported_for_source_schema"),
            (bad_format, "unsupported_format"),
        ):
            self.assertEqual(result["action"], SHOW_SHAPE_ACTION)
            self.assertEqual(result["next_action"], "show_status")
            shape = result["shape"]
            self.assertIsInstance(shape, dict)
            self.assertEqual(shape["availability"], "unavailable")
            self.assertEqual(shape["reason"], reason)
            self.assertEqual(shape["body"], "")
        change_shape = change_lens["shape"]
        self.assertIsInstance(change_shape, dict)
        self.assertEqual(change_shape["evidence_state"], "prepared_not_observed")

    def test_mermaid_requires_observed_capability(self) -> None:
        # Given a prepared runtime handoff session.
        status = self._status_payload(runtime_handoff=self._runtime_handoff_status())

        # When mermaid is requested without and with the observed capability.
        unobserved = build_work_artifact_show_shape_action(
            status, artifact_id="handoff_prompt", lens="structure", format="mermaid"
        )
        observed = build_work_artifact_show_shape_action(
            status,
            artifact_id="handoff_prompt",
            lens="structure",
            format="mermaid",
            capabilities=ShowShapeCapabilities(mermaid_observed=True),
        )

        # Then only the observed capability renders, and it stays bounded.
        unobserved_shape = unobserved["shape"]
        observed_shape = observed["shape"]
        self.assertIsInstance(unobserved_shape, dict)
        self.assertIsInstance(observed_shape, dict)
        self.assertEqual(
            (unobserved_shape["availability"], unobserved_shape["reason"]),
            ("unavailable", "mermaid_capability_not_observed"),
        )
        self.assertEqual(
            (observed_shape["availability"], observed_shape["format"]),
            ("available", "mermaid"),
        )
        self.assertLessEqual(len(observed_shape["body"]), 4000)

    def test_unsafe_source_content_is_unavailable_and_not_leaked(self) -> None:
        # Given a runtime handoff whose profile label carries a secret token.
        handoff = self._runtime_handoff_status()
        handoff["runtime_profile"] = {
            **handoff["runtime_profile"],
            "label": "token=not-for-display",
        }
        status = self._status_payload(runtime_handoff=handoff)

        # When the shape action renders it and the copy action lists it.
        result = build_work_artifact_show_shape_action(
            status, artifact_id="handoff_prompt", lens="structure"
        )
        listing = build_work_artifact_copy_action(status)
        by_id = {str(entry["artifact_id"]): entry for entry in listing["artifacts"]}

        # Then the shape is unavailable, unlisted, and never echoed anywhere.
        result_shape = result["shape"]
        self.assertIsInstance(result_shape, dict)
        self.assertEqual(
            (result_shape["availability"], result_shape["reason"]),
            ("unavailable", "unsafe_source_content"),
        )
        self.assertEqual(
            (
                by_id["handoff_prompt"]["shape"]["availability"],
                by_id["handoff_prompt"]["shape"]["reason"],
            ),
            ("unavailable", "unsafe_source_content"),
        )
        self.assertNotIn("not-for-display", str(result))
        self.assertNotIn("not-for-display", str(listing))
