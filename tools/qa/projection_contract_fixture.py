#!/usr/bin/env python3
"""Create deterministic, isolated projection-contract fixtures for CLI QA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _projection_fixture_data import ARTIFACT_ID, EXPECTED_METRICS, build_adversarial, build_happy, fixture_paths
from _projection_fixture_privacy import fixture_digest, frozen_tree_stamp, prepare_empty_root, privacy_scan


def build_fixture(root: Path, scenario: str) -> dict[str, object]:
    paths = fixture_paths(root)
    if scenario == "happy":
        fanout_id, session_id = build_happy(paths)
        payload = _happy_metadata(root, fanout_id, session_id)
    elif scenario == "adversarial":
        fanout_id, session_id = build_adversarial(paths)
        payload = _adversarial_metadata(root, fanout_id, session_id)
    else:
        raise ValueError("--scenario must be happy or adversarial")
    payload["privacy_scan"] = privacy_scan(root)
    return payload


def _happy_metadata(root: Path, fanout_id: str, session_id: str) -> dict[str, object]:
    return {"schema_version": "projection_contract_fixture/v1", "scenario": "happy", "omh_home": str(root), "fanout_id": fanout_id, "artifact_id": ARTIFACT_ID, "expected_metrics": EXPECTED_METRICS, "shape_expectation": {"availability": "available", "format": "ascii", "evidence_state": "prepared_not_observed"}, "selected_session_id": session_id, "frozen_tree_stamp": frozen_tree_stamp(), "fixture_digest": fixture_digest(fanout_id=fanout_id, session_id=session_id), "commands": {"health": _command(root, "runtime", "health-summary", "--run-id", fanout_id, "--json"), "shape": _command(root, "runtime", "artifacts", "show-shape", "--artifact-id", ARTIFACT_ID, "--lens", "flow", "--json")}}


def _adversarial_metadata(root: Path, fanout_id: str, session_id: str) -> dict[str, object]:
    return {"schema_version": "projection_contract_fixture/v1", "scenario": "adversarial", "omh_home": str(root), "fanout_id": fanout_id, "selected_session_id": session_id, "frozen_tree_stamp": frozen_tree_stamp(), "fixture_digest": fixture_digest(fanout_id=fanout_id, session_id=session_id), "cases": {
        "cyclic_lifecycle": {"command": _command(root, "runtime", "health-summary", "--run-id", fanout_id, "--json"), "expect": "metrics_null_with_gap"},
        "unknown_artifact": {"command": _command(root, "runtime", "artifacts", "show-shape", "--session-id", session_id, "--artifact-id", "unknown-artifact", "--lens", "flow", "--json"), "expect": "unknown_artifact_id"},
        "unsupported_lens": {"command": _command(root, "runtime", "artifacts", "show-shape", "--artifact-id", ARTIFACT_ID, "--lens", "invented", "--json"), "expect": "argparse_refusal"},
        "unsafe_source_content": {"command": _command(root, "runtime", "artifacts", "show-shape", "--artifact-id", "acceptance_and_verification", "--lens", "flow", "--json"), "expect": "unsafe_source_content"},
        "mermaid_unavailable": {"command": _command(root, "runtime", "artifacts", "show-shape", "--artifact-id", ARTIFACT_ID, "--lens", "structure", "--format", "mermaid", "--json"), "expect": "mermaid_capability_not_observed"},
        "invented_edge_refusal": {"command": _command(root, "runtime", "artifacts", "show-shape", "--artifact-id", ARTIFACT_ID, "--lens", "flow", "--json"), "expect": "recorded_edges_only"},
    }}


def _command(root: Path, *args: str) -> list[str]:
    return ["uv", "run", "omh", "--omh-home", str(root), *args]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--omh-home", required=True, help="Empty directory to become the isolated OMH home.")
    parser.add_argument("--scenario", required=True, choices=("happy", "adversarial"))
    parser.add_argument("--json", action="store_true", help="Emit bounded fixture metadata as JSON.")
    args = parser.parse_args()
    try:
        root = prepare_empty_root(args.omh_home)
        payload = build_fixture(root, args.scenario)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"{payload['scenario']} fixture: {payload['omh_home']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
