"""Focused public-contract tests for the local orchestration smoke driver."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from _platform_support import requires_posix

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "tools" / "qa"
sys.path.insert(0, str(QA))
from orchestration_contract_smoke import _audited, adversarial_scenario, happy_scenario


@requires_posix
class OrchestrationContractSmokeTests(unittest.TestCase):
    def test_scenario_functions_preserve_required_evidence(self) -> None:
        happy = happy_scenario()
        adversarial = adversarial_scenario()
        paired = happy["paired"]
        diagnostic = happy["diagnostic"]
        self.assertTrue(happy["ok"])
        self.assertEqual(paired["cell_count"], 8)
        self.assertEqual(paired["receipt_count"], 8)
        self.assertEqual(paired["serial_peaks"]["global"], 1)
        self.assertEqual(paired["parallel_peaks"]["global"], 2)
        self.assertTrue(paired["serial_parallel_scope_equivalent"])
        self.assertEqual(diagnostic["status"], "ok")
        self.assertEqual(diagnostic["evidence_verdict"], "no_new_diagnostics_observed")
        self.assertEqual(diagnostic["runner_calls"], ["orchestration-baseline", "orchestration-end"])
        self.assertEqual(happy["final_review"]["aggregate"], "PASS")
        self.assertTrue(adversarial["ok"])
        self.assertTrue(adversarial["privacy_scan"]["sentinel_absent"])
        for group in (adversarial["paired"], adversarial["diagnostic"], adversarial["final_review"]):
            for value in group.values():
                if isinstance(value, str):
                    self.assertNotIn("PASS", value)
                    self.assertNotIn("no_new_diagnostics_observed", value)

    def test_audit_refuses_missing_evidence(self) -> None:
        audited = _audited({"scenario": "happy", "cleanup": {"live_workspaces": 1}})
        self.assertFalse(audited["ok"])
        self.assertIn("cleanup evidence is incomplete", audited["errors"])
        self.assertIn("diagnostic engine evidence is incomplete", audited["errors"])

    def test_audit_rejects_mutated_peaks_privacy_and_partial_evidence(self) -> None:
        happy = happy_scenario()
        broken_happy = deepcopy(happy)
        broken_happy["paired"]["parallel_peaks"]["global"] = 1
        broken_happy.pop("ok")
        broken_happy.pop("errors")
        self.assertIn("paired serial/parallel evidence is incomplete", _audited(broken_happy)["errors"])
        broken_privacy = deepcopy(happy)
        broken_privacy["privacy_scan"]["persisted_prompt_absent"] = False
        broken_privacy.pop("ok")
        broken_privacy.pop("errors")
        self.assertIn("privacy scan failed", _audited(broken_privacy)["errors"])
        adversarial = adversarial_scenario()
        broken_adversarial = deepcopy(adversarial)
        broken_adversarial["diagnostic"].pop("partial_provider")
        broken_adversarial.pop("ok")
        broken_adversarial.pop("errors")
        self.assertIn("diagnostic adversarial evidence is missing", _audited(broken_adversarial)["errors"])

    def test_cli_is_bounded_json_and_rejects_bad_scenario(self) -> None:
        command = [sys.executable, str(QA / "orchestration_contract_smoke.py")]
        for scenario in ("happy", "adversarial"):
            completed = subprocess.run([*command, "--scenario", scenario, "--json"], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, text=True, capture_output=True, check=False, timeout=180)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertLess(len(completed.stdout), 20_000)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["scenario"], scenario)
            self.assertTrue(payload["ok"], payload["errors"])
        bad = subprocess.run([*command, "--scenario", "bad", "--json"], cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, text=True, capture_output=True, check=False, timeout=30)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("invalid choice", bad.stderr)


if __name__ == "__main__":
    unittest.main()
