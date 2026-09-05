"""Bounded-journal cases collected through the fanout health facade."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _fanout_health_event_support import (
    Clock,
    dispatch_fixture,
    ready,
    runner,
)
from _local_package import load_local_package

load_local_package()

from omh.coding.fanout_dispatch import dispatch_fanout  # noqa: E402
from omh.coding.fanout_health_events import fanout_health_events_path  # noqa: E402
from omh.runtime.critical_path_health_sources import project_fanout_critical_path_health  # noqa: E402


class FanoutHealthJournalBoundsTests(unittest.TestCase):
    def test_oversized_direct_journal_is_rejected_without_partial_metrics(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            paths, repo, sha, contract = dispatch_fixture(Path(directory))
            fanout_id = str(contract["fanout_id"])
            dispatch_fanout(
                paths,
                contract,
                goal_text="health telemetry",
                repo_root=repo,
                base_sha=sha,
                runner=runner,
                readiness=ready,
                emit_health_events=True,
                health_clock=Clock(),
            )
            path = fanout_health_events_path(paths, fanout_id)
            first_record = path.read_text(
                encoding="utf-8"
            ).splitlines(keepends=True)[0]
            path.write_text(first_record * 1_025, encoding="utf-8")

            projected = project_fanout_critical_path_health(paths, fanout_id)

            self.assertIsNone(projected.record.metrics)
            self.assertEqual(projected.events, ())
            self.assertIn(
                ("", "health_event_journal_limit"),
                projected.evidence_gaps,
            )
