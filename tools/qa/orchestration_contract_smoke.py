#!/usr/bin/env python3
"""Bounded real-surface orchestration contract smoke driver."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from orchestration_smoke_paired import adversarial_paired, happy_paired
from orchestration_smoke_quality import adversarial_diagnostic, adversarial_review, happy_diagnostic, happy_review


_EXPECTED_CLEANUP = {
    "live_workspaces": 0,
    "unreaped_child_groups": 0,
    "port_cleanup": "not_applicable_no_ports_created",
    "live_temp_paths": 0,
}


def _tree_stamp() -> str:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True, capture_output=True, check=False, timeout=10)
    return completed.stdout.strip() if completed.returncode == 0 else "unavailable"


def _cleanup(pair: dict[str, object]) -> dict[str, object]:
    value = pair["cleanup"]
    return value if isinstance(value, dict) else {"invalid": True}


def _privacy_scan(pair: dict[str, object], fixture: dict[str, object] | None = None) -> dict[str, bool]:
    filesystem = pair.get("filesystem_privacy")
    rows = (filesystem,) if isinstance(filesystem, dict) and "persisted_prompt_absent" in filesystem else (filesystem.values() if isinstance(filesystem, dict) else ())
    scan = {
        "paired_files_scanned": bool(rows) and all(isinstance(row, dict) and row.get("regular_file_count", 0) > 0 for row in rows),
        "persisted_prompt_absent": bool(rows) and all(isinstance(row, dict) and row.get("persisted_prompt_absent") is True for row in rows),
        "persisted_secret_absent": bool(rows) and all(isinstance(row, dict) and row.get("persisted_secret_absent") is True for row in rows),
        "diagnostic_payload_absent": bool(rows) and all(isinstance(row, dict) and row.get("diagnostic_payload_absent") is True for row in rows),
    }
    if fixture is not None:
        scan.update({
            "diagnostic_fixture_scanned": fixture.get("searched_file_count", 0) > 0,
            "diagnostic_fixture_unpersisted": fixture.get("input_fixture_contains_sentinel") is True and fixture.get("output_store_file_count") == 0 and fixture.get("persisted_secret_absent") is True,
            "sentinel_absent_from_output": fixture.get("sentinel_absent_from_output") is True,
        })
    return scan


def happy_scenario() -> dict[str, object]:
    paired = happy_paired()
    diagnostic = happy_diagnostic()
    review = happy_review()
    payload = {
        "scenario": "happy", "paired": paired, "diagnostic": diagnostic, "final_review": review,
        "cleanup": _cleanup(paired), "frozen_tree_stamp": _tree_stamp(), "privacy_scan": _privacy_scan(paired),
        "claim_boundaries": [paired["claim_boundary"], diagnostic["claim_boundary"]],
    }
    return _audited(payload)


def adversarial_scenario() -> dict[str, object]:
    paired = adversarial_paired()
    diagnostic = adversarial_diagnostic()
    payload = {
        "scenario": "adversarial", "paired": paired, "diagnostic": diagnostic,
        "final_review": adversarial_review(), "cleanup": _cleanup(paired),
        "frozen_tree_stamp": _tree_stamp(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    fixture = diagnostic["fixture_privacy_scan"] if isinstance(diagnostic.get("fixture_privacy_scan"), dict) else {}
    payload["privacy_scan"] = _privacy_scan(paired, fixture)
    payload["privacy_scan"].update({
        "sentinel_absent": "SENTINEL-SECRET-MESSAGE-SOURCE" not in encoded,
        "raw_prompt_absent": "orchestration-qa" not in encoded,
    })
    return _audited(payload)


def _audited(payload: dict[str, object]) -> dict[str, object]:
    errors = _errors(payload)
    payload["ok"] = not errors
    payload["errors"] = errors
    return payload


def _happy_paired_ok(paired: object) -> bool:
    if not isinstance(paired, dict) or paired.get("cell_count") != 8 or paired.get("receipt_count") != 8 or not paired.get("serial_parallel_scope_equivalent"):
        return False
    serial, parallel = paired.get("serial_peaks"), paired.get("parallel_peaks")
    identities, refs = paired.get("identities"), paired.get("receipt_refs")
    if not isinstance(serial, dict) or not isinstance(parallel, dict) or serial.get("global") != 1 or serial.get("provider") != 1 or parallel.get("global") != 2 or parallel.get("provider") != 2:
        return False
    if any(parallel.get(name) != 1 for name in ("local-baseline", "local-variant")) or not isinstance(identities, list) or not isinstance(refs, list) or len(set(refs)) != 8:
        return False
    expected = {(f"cell-{index}", f"{index:064x}", executor, model) for index in range(1, 5) for executor, model in (("local-baseline", "model-baseline"), ("local-variant", "model-variant"))}
    observed = {(item.get("task"), item.get("input"), item.get("executor"), item.get("model")) for item in identities if isinstance(item, dict)}
    workspaces = {item.get("workspace") for item in identities if isinstance(item, dict)}
    return observed == expected and len(identities) == len(workspaces) == 8 and all(item.get("revision") == "orchestration-contract-revision-1" for item in identities if isinstance(item, dict))


def _errors(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    cleanup = payload.get("cleanup")
    if cleanup != _EXPECTED_CLEANUP:
        errors.append("cleanup evidence is incomplete")
    if payload.get("frozen_tree_stamp") == "unavailable":
        errors.append("git tree stamp is unavailable")
    paired, diagnostic, review = payload.get("paired"), payload.get("diagnostic"), payload.get("final_review")
    privacy = payload.get("privacy_scan")
    if not isinstance(privacy, dict) or not privacy or not all(value is True for value in privacy.values()):
        errors.append("privacy scan failed")
    if payload.get("scenario") == "happy":
        if not _happy_paired_ok(paired):
            errors.append("paired serial/parallel evidence is incomplete")
        if not isinstance(diagnostic, dict) or diagnostic.get("status") != "ok" or diagnostic.get("provider_status") != "ok" or diagnostic.get("evidence_verdict") != "no_new_diagnostics_observed" or diagnostic.get("runner_calls") != ["orchestration-baseline", "orchestration-end"] or not diagnostic.get("cache_exact_once") or not diagnostic.get("metadata_only"):
            errors.append("diagnostic engine evidence is incomplete")
        if not isinstance(review, dict) or review.get("aggregate") != "PASS" or not 3 <= review.get("concurrent_peak", 0) <= 4 or set(review.get("lane_states", {}).values()) != {"completed"}:
            errors.append("final review did not pass")
        return errors
    required = {
        "paired": {"missing", "stale", "mismatched", "unauthenticated", "partial", "timeout", "cancel", "crash", "rate_limit", "cleanup_failure", "shared_resource_serialization", "filesystem_privacy"},
        "diagnostic": {"moving_end_revision", "unsupported_suffix", "timeout", "cancel", "crash", "partial_provider", "stateful_serialization", "forbidden_message", "forbidden_source", "fixture_privacy_scan"},
        "final_review": {"missing", "failed", "stale", "timed_out", "cancelled", "crashed", "non_read_only_attempt", "remediation_invalidation"},
    }
    for name, group in (("paired", paired), ("diagnostic", diagnostic), ("final_review", review)):
        if not isinstance(group, dict) or not required[name] <= set(group):
            errors.append(f"{name} adversarial evidence is missing")
            continue
        for value in group.values():
            if isinstance(value, str) and (not value.startswith(("HOLD:", "BLOCK:", "unavailable")) or "PASS" in value or "no_new_diagnostics_observed" in value):
                errors.append("adversarial evidence was incorrectly promoted")
                break
    if not isinstance(diagnostic, dict) or not str(diagnostic.get("stateful_serialization", "")).endswith("max_active=1") or not str(diagnostic.get("partial_provider", "")).startswith("HOLD:partial:"):
        errors.append("diagnostic adversarial execution evidence is incomplete")
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local orchestration contract smoke scenarios.")
    parser.add_argument("--scenario", choices=("happy", "adversarial"), required=True)
    parser.add_argument("--json", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = happy_scenario() if args.scenario == "happy" else adversarial_scenario()
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
