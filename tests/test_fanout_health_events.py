"""Typed fanout critical-path health telemetry."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _fanout_health_event_support import (
    Clock as _Clock,
    SHA as _SHA,
    dispatch_fixture as _dispatch_fixture,
    ready as _ready,
    runner as _runner,
)
from _local_package import load_local_package

load_local_package()

from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import fanout_run_journal_path, write_fanout_contract  # noqa: E402
from omh.coding.fanout_dispatch import dispatch_fanout  # noqa: E402
from omh.coding.fanout_health_events import (  # noqa: E402
    FanoutHealthEvents,
    fanout_health_events_path,
    monotonic_milliseconds,
    write_fanout_health_event,
)
from omh.coding.fanout_journal import FANOUT_RUN_JOURNAL_SCHEMA_VERSION, write_fanout_run_journal  # noqa: E402
from omh.runtime.critical_path_health_sources import project_fanout_critical_path_health  # noqa: E402
from omh.system.local_store import read_jsonl_objects  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402


class FanoutHealthEventTests(unittest.TestCase):
    def test_explicit_missing_stage_revision_is_not_replaced_by_the_base(self) -> None:
        recorded = []
        events = FanoutHealthEvents(
            fanout_id="fanout-abcdef123456",
            revision=_SHA,
            emit=recorded.append,
            clock=_Clock(),
        )

        events.queued(
            "core:verification",
            dependencies=("core",),
            resource_class="verification",
            phase="verification",
            revision="",
        )

        self.assertEqual(recorded, [])

    def test_default_monotonic_clock_uses_the_schema_millisecond_unit(self) -> None:
        with patch(
            "omh.coding.fanout_health_events.time.monotonic_ns",
            return_value=12_345_678,
        ):
            self.assertEqual(monotonic_milliseconds(), 12)

    def test_same_millisecond_lifecycle_is_preserved(self) -> None:
        recorded = []
        events = FanoutHealthEvents(
            fanout_id="fanout-abcdef123456",
            revision=_SHA,
            emit=recorded.append,
            clock=lambda: 7,
        )

        events.queued("core", dependencies=(), resource_class="codex")
        events.started("core")
        events.finished("core", terminal_status="succeeded")

        self.assertEqual(
            [(event.event, event.at_ms) for event in recorded],
            [("queued", 7), ("started", 7), ("finished", 7)],
        )

    def test_diamond_events_reconcile_through_the_real_projector(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            contract = write_fanout_contract(
                paths,
                build_fanout_contract(
                    "health diamond",
                    [
                        {"unit_id": "root", "title": "Root", "owner": "codex", "file_scope": ["root/"]},
                        {"unit_id": "left", "title": "Left", "owner": "codex", "file_scope": ["left/"], "depends_on": ["root"]},
                        {"unit_id": "right", "title": "Right", "owner": "codex", "file_scope": ["right/"], "depends_on": ["root"]},
                        {"unit_id": "join", "title": "Join", "owner": "codex", "file_scope": ["join/"], "depends_on": ["left", "right"]},
                    ],
                ),
            )
            units = contract["units"]
            write_fanout_run_journal(
                fanout_run_journal_path(paths, str(contract["fanout_id"])),
                {
                    "schema_version": FANOUT_RUN_JOURNAL_SCHEMA_VERSION,
                    "fanout_id": contract["fanout_id"],
                    "observed_at": "2026-01-01T00:00:00Z",
                    "base_sha": _SHA,
                    "merge_order": [unit["unit_id"] for unit in units],
                    "units": [
                        {
                            "unit_id": unit["unit_id"], "run_ref": unit["run_ref"], "owner": "codex",
                            "terminal_state": "succeeded", "status": "completed", "failure_class": "",
                            "failure_label": "", "decline_reason": "", "replay_safe": False,
                            "replay_verdict": "unsafe_side_effects", "side_effect": "no_spawn_observed", "blocked_on": [],
                        }
                        for unit in units
                    ],
                    "privacy": "metadata_only", "claim_boundary": "terminal process state only",
                },
            )
            events = FanoutHealthEvents(
                fanout_id=str(contract["fanout_id"]), revision=_SHA, emit=lambda event: write_fanout_health_event(paths, str(contract["fanout_id"]), event), clock=_Clock(),
            )
            dependencies = {str(unit["unit_id"]): tuple(str(item) for item in unit.get("depends_on", [])) for unit in units}
            for unit_id in ("root", "left", "right", "join"):
                events.queued(unit_id, dependencies=dependencies[unit_id], resource_class="codex")
                events.started(unit_id)
                events.finished(unit_id, terminal_status="succeeded")

            projected = project_fanout_critical_path_health(paths, str(contract["fanout_id"]))

            self.assertEqual(projected.record.metrics.critical_path_ms, 15)
            self.assertEqual(projected.evidence_gaps, ())

    def test_revision_override_is_preserved_across_a_stage_lifecycle(self) -> None:
        observed = []
        events = FanoutHealthEvents(
            fanout_id="fanout-abcdef123456", revision=_SHA, emit=observed.append, clock=_Clock()
        )
        producer_revision = "b" * 40
        integrated_revision = "c" * 40

        events.queued(
            "core:verification",
            dependencies=("core",),
            resource_class="verification",
            phase="verification",
            revision=producer_revision,
        )
        events.started("core:verification", phase="verification")
        events.finished("core:verification", terminal_status="succeeded", phase="verification")
        events.queued(
            "fanout-abcdef123456:review",
            dependencies=("core",),
            resource_class="final_review",
            phase="review",
            revision=integrated_revision,
        )
        events.started("fanout-abcdef123456:review", phase="review")
        events.finished("fanout-abcdef123456:review", terminal_status="succeeded", phase="review")

        self.assertEqual([event.revision for event in observed[:3]], [producer_revision] * 3)
        self.assertEqual([event.revision for event in observed[3:]], [integrated_revision] * 3)

    def test_enabled_dispatch_writes_private_events_consumed_by_the_projector(self) -> None:
        with TemporaryDirectory() as directory:
            paths, repo, sha, contract = _dispatch_fixture(Path(directory))

            summary = dispatch_fanout(
                paths,
                contract,
                goal_text="health telemetry",
                repo_root=repo,
                base_sha=sha,
                runner=_runner,
                readiness=_ready,
                emit_health_events=True,
                health_clock=_Clock(),
            )

            fanout_id = str(contract["fanout_id"])
            path = fanout_health_events_path(paths, fanout_id)
            records, errors = read_jsonl_objects(path)
            projected = project_fanout_critical_path_health(paths, fanout_id)

            self.assertEqual(summary["units"][0]["status"], "completed")
            self.assertEqual(errors, [])
            self.assertEqual([record["event"] for record in records], ["queued", "started", "finished"])
            self.assertTrue(all(record["privacy"] == "metadata_only" for record in records))
            self.assertTrue(all("output" not in record and "prompt" not in record for record in records))
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            self.assertIsNotNone(projected.record.metrics)
            self.assertEqual(projected.evidence_gaps, ())

    def test_malformed_direct_journal_is_a_gap_not_a_legacy_timing_fallback(self) -> None:
        with TemporaryDirectory() as directory:
            paths, repo, sha, contract = _dispatch_fixture(Path(directory))
            fanout_id = str(contract["fanout_id"])
            dispatch_fanout(
                paths,
                contract,
                goal_text="health telemetry",
                repo_root=repo,
                base_sha=sha,
                runner=_runner,
                readiness=_ready,
                emit_health_events=True,
                health_clock=_Clock(),
            )
            fanout_health_events_path(paths, fanout_id).write_text("{not-json}\n", encoding="utf-8")

            projected = project_fanout_critical_path_health(paths, fanout_id)

            self.assertIsNone(projected.record.metrics)
            self.assertIn(("", "health_event_journal_invalid"), projected.evidence_gaps)

    def test_dispatch_write_failure_preserves_unit_status_and_readiness(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_paths, baseline_repo, baseline_sha, baseline_contract = _dispatch_fixture(root / "baseline")
            failed_paths, failed_repo, failed_sha, failed_contract = _dispatch_fixture(root / "failed")
            baseline = dispatch_fanout(
                baseline_paths,
                baseline_contract,
                goal_text="health telemetry",
                repo_root=baseline_repo,
                base_sha=baseline_sha,
                runner=_runner,
                readiness=_ready,
            )
            with patch(
                "omh.coding.fanout_dispatch.write_fanout_health_event",
                side_effect=OSError("journal unavailable"),
            ):
                failed = dispatch_fanout(
                    failed_paths,
                    failed_contract,
                    goal_text="health telemetry",
                    repo_root=failed_repo,
                    base_sha=failed_sha,
                    runner=_runner,
                    readiness=_ready,
                    emit_health_events=True,
                    health_clock=_Clock(),
                )

            baseline_unit = baseline["units"][0]
            failed_unit = failed["units"][0]
            self.assertEqual(
                {key: baseline_unit.get(key) for key in ("status", "exit_code", "unit_verification_observed", "integration_ready")},
                {key: failed_unit.get(key) for key in ("status", "exit_code", "unit_verification_observed", "integration_ready")},
            )
            self.assertFalse(fanout_health_events_path(failed_paths, str(failed_contract["fanout_id"])).exists())

    def test_writer_failure_is_non_blocking_and_does_not_fabricate_lifecycle_events(self) -> None:
        attempts: list[str] = []
        events = FanoutHealthEvents(
            fanout_id="fanout-abcdef123456", revision=_SHA,
            emit=lambda event: (attempts.append(event.event), (_ for _ in ()).throw(OSError("offline")))[1],
            clock=_Clock(),
        )

        events.queued("core", dependencies=(), resource_class="codex")
        events.started("core")
        events.finished("core", terminal_status="succeeded")

        self.assertEqual(attempts, ["queued", "started", "finished"])


if __name__ == "__main__":
    unittest.main()
