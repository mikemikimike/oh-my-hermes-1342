from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..installer import OmhError
from ..runtime.critical_path_health_sources import project_fanout_critical_path_health
from ..runtime.run_health_critical_path import committed_critical_path_health_errors
from ..runtime.run_health import (
    RUN_HEALTH_INPUT_SCHEMA_VERSION,
    RUN_HEALTH_INPUT_V2_SCHEMA_VERSION,
    build_run_health_summary,
    parse_run_health_input,
    render_run_health_summary_text,
    validate_run_health_summary,
)
from ..system.paths import OmhPaths
from .common import _paths, _print_json, _wants_json


def cmd_runtime_health_summary(args: argparse.Namespace) -> int:
    try:
        raw = _health_input(args)
        summary = build_run_health_summary(parse_run_health_input(raw))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    # A projection this surface just built should never fail its own validator.
    # Checking anyway is what keeps the read path and the write path from
    # drifting: the CLI refuses to render a summary it could not read back.
    errors = validate_run_health_summary(summary)
    if errors:
        raise OmhError("; ".join(errors))
    if _wants_json(args):
        _print_json(summary)
        return 0
    print(render_run_health_summary_text(summary))
    return 0


def _health_input(args: argparse.Namespace) -> object:
    if args.input:
        return json.loads(Path(args.input).expanduser().read_text(encoding="utf-8"))
    return _fanout_health_input(args.run_id, _paths(args))


def _fanout_health_input(fanout_id: str, paths: OmhPaths) -> dict[str, object]:
    """Adapt source-owned fanout evidence without manufacturing lifecycle facts."""
    source = project_fanout_critical_path_health(paths, fanout_id)
    section = source.record.to_dict()
    metrics = section.get("metrics")
    gaps = section.get("evidence_gaps")
    has_explicit_gap_section = isinstance(gaps, list) and bool(gaps)
    committed = not committed_critical_path_health_errors(section, "critical_path_health")
    observed_at_ms = max((event.at_ms for event in source.events), default=0)
    raw: dict[str, object] = {
        "schema_version": RUN_HEALTH_INPUT_SCHEMA_VERSION,
        "run_id": fanout_id,
        # This reads an aggregate rather than a named executor stream. The
        # owner stays deliberately unsupported, keeping the source's separate
        # committed section as the sole place timing can be claimed.
        "owner": "fanout",
        "observed_at_ms": observed_at_ms,
        "events": [],
        "efficiency_claim": {"direction": "unclaimed", "baseline_ref": "", "evaluator_ref": ""},
    }
    if committed and (metrics is not None or has_explicit_gap_section):
        raw["schema_version"] = RUN_HEALTH_INPUT_V2_SCHEMA_VERSION
        raw["critical_path_health"] = section
    return raw


def add_runtime_health_summary_command(runtime_sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    health = runtime_sub.add_parser(
        "health-summary",
        help="Agent/operator surface: explain run or fanout health from recorded metadata only.",
    )
    input_source = health.add_mutually_exclusive_group(required=True)
    input_source.add_argument("--input", help="Path to a legacy run_health_input/v1 or v2 JSON file.")
    input_source.add_argument("--run-id", help="Fanout id to project through the committed critical-path source.")
    health.add_argument("--json", action="store_true", help="Emit the machine payload instead of plain text.")
    health.set_defaults(func=cmd_runtime_health_summary)
