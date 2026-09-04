"""Real CLI coverage for the isolated projection-contract fixture builder."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools" / "qa" / "projection_contract_fixture.py"
SUPPLIED_SENTINEL = "fixture-private-message-1290"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


def _tree_stamp() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD^{tree}"),
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _json(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise AssertionError("CLI did not return a JSON object")
    return payload


class ProjectionContractFixtureTests(unittest.TestCase):
    def test_happy_fixture_uses_the_real_health_and_shape_surfaces(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "fixture"
            metadata = _json(_run("uv", "run", "python", str(BUILDER), "--omh-home", str(root), "--scenario", "happy", "--json"))
            health = _json(_run("uv", "run", "omh", "--omh-home", str(root), "runtime", "health-summary", "--run-id", str(metadata["fanout_id"]), "--json"))
            shape = _json(_run("uv", "run", "omh", "--omh-home", str(root), "runtime", "artifacts", "show-shape", "--artifact-id", str(metadata["artifact_id"]), "--lens", "flow", "--json"))

            section = health["critical_path_health"]
            self.assertIsInstance(section, dict)
            assert isinstance(section, dict)
            self.assertEqual(health["schema_version"], "run_health_summary/v2")
            self.assertEqual(section["metrics"], metadata["expected_metrics"])
            self.assertEqual(section["evidence_gaps"], [])
            self.assertEqual(shape["selected_session_id"], metadata["selected_session_id"])
            rendered = shape["shape"]
            self.assertIsInstance(rendered, dict)
            assert isinstance(rendered, dict)
            self.assertEqual(rendered["availability"], "available")
            self.assertEqual(rendered["format"], "ascii")
            self.assertEqual(rendered["evidence_state"], "prepared_not_observed")
            self.assertEqual(rendered["reason"], "")
            self.assertTrue(rendered["body"])
            self.assertLessEqual(len(rendered["bullets"]), 3)
            self.assertTrue(all(node["source_refs"] for node in rendered["nodes"]))
            self.assertTrue(all(edge["source_refs"] for edge in rendered["edges"]))
            self.assertEqual([(edge["source_id"], edge["target_id"]) for edge in rendered["edges"]], [("handoff", "executor"), ("executor", "observation")])
            self.assertIn("unchanged marker", str(rendered["claim_boundary"]))
            self.assertNotIn(SUPPLIED_SENTINEL, json.dumps(rendered))
            self.assertEqual(metadata["frozen_tree_stamp"], _tree_stamp())
            self.assertTrue(str(metadata["fixture_digest"]).startswith("fixture-"))
            self.assertEqual(metadata["shape_expectation"], {"availability": "available", "format": "ascii", "evidence_state": "prepared_not_observed"})
            self.assertEqual(metadata["privacy_scan"], {"supplied_sentinel_kind": "wrapper_message", "files_scanned": 8, "leak_count": 0, "leaks": []})
            for path in root.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    self.assertNotIn(SUPPLIED_SENTINEL.encode(), path.read_bytes())

        self.assertFalse(root.exists())

    def test_adversarial_fixture_is_explicitly_gappy_or_unavailable(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "fixture"
            metadata = _json(_run("uv", "run", "python", str(BUILDER), "--omh-home", str(root), "--scenario", "adversarial", "--json"))
            self.assertEqual(metadata["frozen_tree_stamp"], _tree_stamp())
            cases = metadata["cases"]
            self.assertIsInstance(cases, dict)
            assert isinstance(cases, dict)
            health = _json(_run("uv", "run", "omh", "--omh-home", str(root), "runtime", "health-summary", "--run-id", str(metadata["fanout_id"]), "--json"))
            section = health["critical_path_health"]
            self.assertIsInstance(section, dict)
            assert isinstance(section, dict)
            self.assertIsNone(section["metrics"])
            self.assertIn({"task_id": "", "code": "cycle"}, section["evidence_gaps"])
            for name, expected in (("unknown_artifact", "unknown_artifact_id"), ("unsupported_schema", "unsupported_source_schema"), ("mermaid_unavailable", "mermaid_capability_not_observed")):
                case = cases[name]
                self.assertIsInstance(case, dict)
                assert isinstance(case, dict)
                command = case["command"]
                self.assertIsInstance(command, list)
                assert isinstance(command, list)
                result = _json(_run(*[str(item) for item in command]))
                shape = result["shape"]
                self.assertIsInstance(shape, dict)
                assert isinstance(shape, dict)
                self.assertEqual(shape["availability"], "unavailable")
                self.assertEqual(shape["reason"], expected)
            lens_case = cases["unsupported_lens"]
            self.assertIsInstance(lens_case, dict)
            assert isinstance(lens_case, dict)
            lens_command = lens_case["command"]
            self.assertIsInstance(lens_command, list)
            assert isinstance(lens_command, list)
            lens_result = _run(*[str(item) for item in lens_command])
            self.assertEqual(lens_result.returncode, 2)
            self.assertIn("invalid choice", lens_result.stderr)
            edge_case = cases["invented_edge_refusal"]
            self.assertIsInstance(edge_case, dict)
            assert isinstance(edge_case, dict)
            edge_command = edge_case["command"]
            self.assertIsInstance(edge_command, list)
            assert isinstance(edge_command, list)
            edge_payload = _json(_run(*[str(item) for item in edge_command]))
            edge_shape = edge_payload["shape"]
            self.assertIsInstance(edge_shape, dict)
            assert isinstance(edge_shape, dict)
            self.assertEqual(edge_shape["availability"], "available")
            self.assertEqual([(edge["source_id"], edge["target_id"]) for edge in edge_shape["edges"]], [("handoff", "executor"), ("executor", "observation")])

        self.assertFalse(root.exists())

    def test_refuses_nonempty_target(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "fixture"
            root.mkdir()
            (root / "keep").write_text("keep", encoding="utf-8")
            result = _run("uv", "run", "python", str(BUILDER), "--omh-home", str(root), "--scenario", "happy", "--json")

            self.assertEqual(result.returncode, 2)
            self.assertIn("must be an empty directory", result.stderr)
            self.assertTrue((root / "keep").exists())


if __name__ == "__main__":
    unittest.main()
