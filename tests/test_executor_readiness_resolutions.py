"""The readiness probe reports every PATH resolution, pinned to no version.

Users update codex and claude on their own cadence and through more than one
installer, so binaries of different versions routinely coexist on PATH.
Observed live: a stale npm codex 0.144.5 resolved first and probed "ready"
while the standalone 0.145.0 the auth session actually required sat one PATH
entry later -- `shutil.which` answers only "what will run", so the newer
install was invisible and the dispatch failed mid-flight.

The structural rule these pin: OMH never compares an executor version against
an expectation of its own. It observes what each resolution prints and says
when the binary that will run is not the only one installed.
"""

from __future__ import annotations

import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.coding.executor_readiness import (
    EXECUTOR_VERSION_POLICY,
    _run_probe,
    executor_readiness_contract,
)


def _fake_binary(directory: str, name: str, version: str) -> Path:
    path = Path(directory) / name
    path.write_text(f"#!/bin/sh\necho 'codex-cli {version}'\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class PathResolutionReportTests(unittest.TestCase):
    def _probe(self, path_value: str) -> dict:
        with patch.dict(os.environ, {"PATH": path_value}):
            return _run_probe(dict(executor_readiness_contract("codex")))

    def test_a_stale_binary_shadowing_a_newer_one_is_reported(self) -> None:
        # The live failure, reproduced: first-on-PATH is old, newer sits behind.
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            _fake_binary(first, "codex", "0.144.5")
            _fake_binary(second, "codex", "0.145.0")
            result = self._probe(os.pathsep.join([first, second]))

            self.assertTrue(result["shadowed"])
            versions = [row["observed_version"] for row in result["path_resolutions"]]
            self.assertEqual(versions, ["codex-cli 0.144.5", "codex-cli 0.145.0"])
            # The stale one is still what runs, so status stays honest...
            self.assertEqual(result["status"], "ready")
            # ...and the summary names the alternative instead of hiding it.
            self.assertIn("0.145.0", result["summary"])
            self.assertIn("PATH also resolves", result["summary"])

    def test_a_single_binary_reports_no_shadow(self) -> None:
        with TemporaryDirectory() as only:
            _fake_binary(only, "codex", "0.145.0")
            result = self._probe(only)
            self.assertFalse(result["shadowed"])
            self.assertEqual(len(result["path_resolutions"]), 1)
            self.assertNotIn("PATH also resolves", result["summary"])

    def test_a_symlink_to_the_same_binary_is_not_a_conflict(self) -> None:
        # Dedup is by real path: standalone installs symlink through a
        # `current` pointer, and a chain to one binary is one binary.
        with TemporaryDirectory() as real_dir, TemporaryDirectory() as link_dir:
            real = _fake_binary(real_dir, "codex", "0.145.0")
            (Path(link_dir) / "codex").symlink_to(real)
            result = self._probe(os.pathsep.join([link_dir, real_dir]))
            self.assertFalse(result["shadowed"])
            self.assertEqual(len(result["path_resolutions"]), 1)

    def test_same_version_in_two_places_is_not_flagged_as_shadowed(self) -> None:
        # Two distinct binaries printing the same version disagree about
        # nothing a user must resolve; flagging them would train people to
        # ignore the flag.
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            _fake_binary(first, "codex", "0.145.0")
            _fake_binary(second, "codex", "0.145.0")
            result = self._probe(os.pathsep.join([first, second]))
            self.assertFalse(result["shadowed"])

    def test_the_probe_carries_the_no_pinned_version_policy(self) -> None:
        with TemporaryDirectory() as only:
            _fake_binary(only, "codex", "9.9.9")
            result = self._probe(only)
            self.assertEqual(result["version_policy"], EXECUTOR_VERSION_POLICY)
            # A future version OMH has never seen probes ready: nothing in the
            # contract encodes an expected version to fall behind.
            self.assertEqual(result["status"], "ready")

    def test_no_source_line_hardcodes_an_executor_version(self) -> None:
        # The guard for the structural rule itself: the module may print
        # versions it observed, never carry one of its own.
        import inspect

        import omh.coding.executor_readiness as module

        source = inspect.getsource(module)
        for literal in ("0.144", "0.145", "2.1.2"):
            self.assertNotIn(literal, source)


if __name__ == "__main__":
    unittest.main()
