from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.surfaces.show_shape import (
    HandoffShapeInput,
    PlanShapeInput,
    ReviewShapeInput,
    ShapeEdge,
    ShapeNode,
    ShowShapeCapabilities,
    StatusShapeInput,
    WORK_ARTIFACT_SHOW_SHAPE_SCHEMA_VERSION,
    build_work_artifact_show_shape,
)


class WorkArtifactShowShapeTests(unittest.TestCase):
    def test_plan_flow_defaults_to_text_safe_ascii_and_preserves_sources(self) -> None:
        result = build_work_artifact_show_shape(
            PlanShapeInput(
                source_artifact_id="plan-12",
                source_schema="work_plan/v1",
                evidence_state="prepared_not_observed",
                nodes=(
                    ShapeNode("draft", "Draft plan", ("plan-12#step-1",)),
                    ShapeNode("verify", "Verify plan", ("plan-12#step-2",)),
                ),
                edges=(ShapeEdge("draft", "verify", ("plan-12#dependency-1",), "next"),),
                bullets=("Prepared only", "Verify before execution", "Third detail", "not rendered"),
            ),
        ).to_dict()

        self.assertEqual(result["schema_version"], WORK_ARTIFACT_SHOW_SHAPE_SCHEMA_VERSION)
        self.assertEqual(result["availability"], "available")
        self.assertEqual(result["format"], "ascii")
        self.assertEqual(result["lens"], "flow")
        self.assertEqual(result["evidence_state"], "prepared_not_observed")
        self.assertIn("plan-12#step-1", result["body"])
        self.assertIn("plan-12#dependency-1", result["body"])
        self.assertLessEqual(len(result["bullets"]), 3)
        self.assertTrue(result["legend"])
        self.assertIn("unchanged marker", result["claim_boundary"])

    def test_status_handoff_and_review_use_their_specific_lenses(self) -> None:
        status = build_work_artifact_show_shape(
            StatusShapeInput(
                source_artifact_id="status-7",
                source_schema="work_status/v1",
                evidence_state="prepared_not_observed",
                nodes=(ShapeNode("verify", "Verification", ("status-7#verification",), state="not_observed"),),
            ),
            lens="state",
            format="tree",
        ).to_dict()
        handoff = build_work_artifact_show_shape(
            HandoffShapeInput(
                source_artifact_id="handoff-8",
                source_schema="coding_runtime_handoff/v1",
                evidence_state="prepared_not_observed",
                nodes=(ShapeNode("implementation", "Implementation", ("handoff-8#owner",), owner="selected executor"),),
            ),
            lens="ownership",
        ).to_dict()
        review = build_work_artifact_show_shape(
            ReviewShapeInput(
                source_artifact_id="review-4",
                source_schema="review_change/v1",
                evidence_state="observed",
                nodes=(ShapeNode("show-shape", "show_shape.py", ("review-4#file",), change="modified"),),
            ),
            lens="change",
            format="diff",
        ).to_dict()

        self.assertEqual((status["availability"], status["format"]), ("available", "tree"))
        self.assertIn("not_observed", status["body"])
        self.assertEqual(handoff["availability"], "available")
        self.assertIn("selected executor", handoff["body"])
        self.assertEqual((review["availability"], review["format"]), ("available", "diff"))
        self.assertIn("~ show_shape.py", review["body"])

    def test_handoff_flow_is_available_when_its_contract_records_exact_edges(self) -> None:
        result = build_work_artifact_show_shape(
            HandoffShapeInput(
                source_artifact_id="handoff-flow",
                source_schema="coding_runtime_handoff/v1",
                evidence_state="prepared_not_observed",
                nodes=(
                    ShapeNode("handoff", "Prepared handoff", ("handoff-flow#status",)),
                    ShapeNode("executor", "Selected executor", ("handoff-flow#profile",)),
                ),
                edges=(
                    ShapeEdge(
                        "handoff",
                        "executor",
                        ("handoff-flow#dispatch_contract",),
                        "dispatches",
                    ),
                ),
            ),
            lens="flow",
        ).to_dict()

        self.assertEqual(result["availability"], "available")
        self.assertIn("handoff-flow#dispatch_contract", result["body"])
        self.assertEqual(result["evidence_state"], "prepared_not_observed")

    def test_unavailable_paths_are_explicit_and_do_not_invent_missing_evidence(self) -> None:
        no_refs = build_work_artifact_show_shape(
            PlanShapeInput(
                source_artifact_id="plan-no-ref",
                source_schema="work_plan/v1",
                evidence_state="prepared_not_observed",
                nodes=(ShapeNode("draft", "Draft", ()),),
            )
        ).to_dict()
        unsupported = build_work_artifact_show_shape(
            {"artifact_id": "unknown", "schema_version": "unrecognized/v1"}
        ).to_dict()
        absent_mermaid = build_work_artifact_show_shape(
            PlanShapeInput(
                source_artifact_id="plan-mermaid",
                source_schema="work_plan/v1",
                evidence_state="prepared_not_observed",
                nodes=(ShapeNode("draft", "Draft", ("plan-mermaid#draft",)),),
            ),
            format="mermaid",
        ).to_dict()

        self.assertEqual((no_refs["availability"], no_refs["reason"]), ("unavailable", "missing_node_source_refs"))
        self.assertEqual((unsupported["availability"], unsupported["reason"]), ("unavailable", "unsupported_source_schema"))
        self.assertEqual((absent_mermaid["availability"], absent_mermaid["reason"]), ("unavailable", "mermaid_capability_not_observed"))
        self.assertEqual(absent_mermaid["evidence_state"], "prepared_not_observed")

    def test_mermaid_requires_observed_capability_and_output_is_bounded_and_private(self) -> None:
        private = build_work_artifact_show_shape(
            PlanShapeInput(
                source_artifact_id="plan-private",
                source_schema="work_plan/v1",
                evidence_state="prepared_not_observed",
                nodes=(ShapeNode("draft", "Draft", ("plan-private#draft",)),),
                bullets=tuple(f"detail {index}" for index in range(12)),
            ),
            format="mermaid",
            capabilities=ShowShapeCapabilities(mermaid_observed=True),
        ).to_dict()
        unsafe = build_work_artifact_show_shape(
            PlanShapeInput(
                source_artifact_id="plan-secret",
                source_schema="work_plan/v1",
                evidence_state="prepared_not_observed",
                nodes=(ShapeNode("draft", "token=not-for-display", ("plan-secret#draft",)),),
            )
        ).to_dict()

        self.assertEqual((private["availability"], private["format"]), ("available", "mermaid"))
        self.assertLessEqual(len(private["body"]), 4000)
        self.assertLessEqual(len(private["bullets"]), 3)
        self.assertTrue(any(item["reason"] == "bullet_limit" for item in private["omissions"]))
        self.assertEqual((unsafe["availability"], unsafe["reason"]), ("unavailable", "unsafe_source_content"))
        self.assertNotIn("not-for-display", str(unsafe))

    def test_mapping_source_parses_graph_and_omissions(self) -> None:
        result = build_work_artifact_show_shape(
            {
                "source_artifact_id": "plan-mapping",
                "source_schema": "work_plan/v1",
                "evidence_state": "prepared_not_observed",
                "nodes": [
                    {
                        "node_id": "draft",
                        "label": "Draft",
                        "source_refs": ["plan-mapping#draft"],
                        "change": "unchanged",
                    },
                    {
                        "node_id": "verify",
                        "label": "Verify",
                        "source_refs": ["plan-mapping#verify"],
                        "change": "unchanged",
                    },
                ],
                "edges": [
                    {
                        "source_id": "draft",
                        "target_id": "verify",
                        "source_refs": ["plan-mapping#dependency"],
                        "label": "next",
                    }
                ],
                "omissions": [{"item_id": "detail", "reason": "source_limit"}],
            }
        ).to_dict()

        self.assertEqual(result["availability"], "available")
        self.assertIn("plan-mapping#dependency", result["body"])
        self.assertIn({"item_id": "detail", "reason": "source_limit"}, result["omissions"])


if __name__ == "__main__":
    unittest.main()
