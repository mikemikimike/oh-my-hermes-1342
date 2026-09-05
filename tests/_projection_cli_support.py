"""Shared real-CLI helpers for the named projection integration suites."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
QA_ROOT = ROOT / "tools/qa"
if str(QA_ROOT) not in sys.path:
    sys.path.insert(0, str(QA_ROOT))

from _projection_fixture_privacy import prepare_empty_root  # noqa: E402
from projection_contract_fixture import build_fixture  # noqa: E402


def create_projection_fixture(root: Path, scenario: str) -> dict[str, object]:
    return build_fixture(prepare_empty_root(str(root)), scenario)


def run_omh(root: Path, *args: str) -> dict[str, object]:
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    completed = subprocess.run(
        [sys.executable, "-m", "omh.cli", "--omh-home", str(root), *args],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise AssertionError("OMH CLI did not return a JSON object")
    return payload
