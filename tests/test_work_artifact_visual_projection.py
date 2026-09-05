"""Named real-surface suite for selected work-artifact visual projections."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _projection_cli_support import create_projection_fixture, run_omh  # noqa: E402


class WorkArtifactVisualProjectionTests(unittest.TestCase):
    def test_selected_handoff_flow_is_traceable_bounded_and_read_only(self) -> None:
        with TemporaryDirectory(prefix="omh-work-shape-") as raw:
            root = Path(raw) / "fixture"
            metadata = create_projection_fixture(root, "happy")
            payload = run_omh(
                root,
                "runtime",
                "artifacts",
                "show-shape",
                "--artifact-id",
                str(metadata["artifact_id"]),
                "--lens",
                "flow",
                "--json",
            )

            shape = payload["shape"]
            self.assertEqual(shape["availability"], "available")
            self.assertEqual(shape["format"], "ascii")
            self.assertEqual(shape["evidence_state"], "prepared_not_observed")
            self.assertLessEqual(len(shape["bullets"]), 3)
            self.assertTrue(all(node["source_refs"] for node in shape["nodes"]))
            self.assertTrue(all(edge["source_refs"] for edge in shape["edges"]))
            self.assertEqual(payload["next_action"], "show_status")
            self.assertIn("does not advance the session", payload["claim_boundary"])
            self.assertEqual(metadata["privacy_scan"]["leak_count"], 0)

        self.assertFalse(root.exists())

    def test_unknown_schema_and_mermaid_capability_remain_unavailable(self) -> None:
        with TemporaryDirectory(prefix="omh-work-shape-bad-") as raw:
            root = Path(raw) / "fixture"
            metadata = create_projection_fixture(root, "adversarial")
            unknown = run_omh(
                root,
                "runtime",
                "artifacts",
                "show-shape",
                "--session-id",
                str(metadata["selected_session_id"]),
                "--artifact-id",
                "unknown-artifact",
                "--lens",
                "flow",
                "--json",
            )
            mermaid = run_omh(
                root,
                "runtime",
                "artifacts",
                "show-shape",
                "--artifact-id",
                "handoff_prompt",
                "--lens",
                "structure",
                "--format",
                "mermaid",
                "--json",
            )

            self.assertEqual(unknown["shape"]["reason"], "unknown_artifact_id")
            self.assertEqual(unknown["shape"]["availability"], "unavailable")
            self.assertEqual(mermaid["shape"]["reason"], "mermaid_capability_not_observed")
            self.assertEqual(mermaid["shape"]["availability"], "unavailable")
            self.assertEqual(mermaid["shape"]["evidence_state"], "prepared_not_observed")


if __name__ == "__main__":
    unittest.main()
