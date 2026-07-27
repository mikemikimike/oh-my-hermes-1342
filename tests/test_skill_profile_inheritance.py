"""An update carries the installed skill profile forward instead of resetting it.

The profile was chosen as `"full" if --full else "core"` on every run, so a
plain `omh update` rewrote the manifest to `core` regardless of what was
installed. Installs never delete skills, so the full-only skills stayed on
disk, and the summary then reported the gap it had just created:

    Skill profile: core requested, but 83 full-only skill(s) are still
    installed and still cost per-turn context. Installs never delete skills;
    run `omh skill-profile reconcile --to core` to shrink explicitly.

Nobody had asked for core. The operator installed the full catalog, ran the
command whose job is to keep it current, and was handed a reconcile chore for a
divergence the update invented.

`reconcile` is deliberately the only path that deletes managed skill
directories, and it stays that way. Nothing here removes anything; the fix is
that an update stops changing the recorded profile on its own.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.skill_pack import CORE_PROFILE_SKILLS


class SkillProfileInheritanceTests(unittest.TestCase):
    def _base(self, root: Path) -> list[str]:
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

    def _profile(self, root: Path) -> str:
        return str(json.loads((root / ".omh" / "manifest.json").read_text(encoding="utf-8"))["skill_profile"])

    def _installed(self, root: Path) -> int:
        return len([child for child in (root / ".omh" / "skills").iterdir() if child.is_dir()])

    def test_update_keeps_a_full_install_full(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["install", "--full"])
            installed = self._installed(root)
            self.assertEqual(self._profile(root), "full")

            status, _, stderr = run_cli(self._base(root) + ["update"])
            self.assertEqual(status, 0, stderr)
            self.assertEqual(self._profile(root), "full")
            self.assertEqual(self._installed(root), installed)

    def test_repeated_updates_do_not_drift(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["install", "--full"])
            for _ in range(3):
                run_cli(self._base(root) + ["update"])
            self.assertEqual(self._profile(root), "full")

    def test_a_core_install_stays_core(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["install"])
            self.assertEqual(self._profile(root), "core")
            self.assertEqual(self._installed(root), len(CORE_PROFILE_SKILLS))

            run_cli(self._base(root) + ["update"])
            self.assertEqual(self._profile(root), "core")
            self.assertEqual(self._installed(root), len(CORE_PROFILE_SKILLS))

    def test_a_first_install_with_no_flag_is_core(self) -> None:
        # Inheritance must not turn the default into "whatever was there", and
        # there is nothing to inherit on a fresh machine.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["update"])
            self.assertEqual(self._profile(root), "core")

    def test_the_full_flag_still_widens_a_core_install(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["install"])
            self.assertEqual(self._profile(root), "core")

            run_cli(self._base(root) + ["update", "--full"])
            self.assertEqual(self._profile(root), "full")
            self.assertGreater(self._installed(root), len(CORE_PROFILE_SKILLS))

    def test_update_no_longer_reports_a_divergence_it_created(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["install", "--full"])
            _, stdout, _ = run_cli(self._base(root) + ["update"], output_json=False)
            self.assertNotIn("skill-profile reconcile", stdout)
            self.assertNotIn("full-only skill", stdout)

    def test_narrowing_is_still_reconcile_only(self) -> None:
        # Update carries the profile forward; it never shrinks one. Deleting
        # managed skill directories stays the one thing only reconcile does.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(self._base(root) + ["install", "--full"])
            installed = self._installed(root)
            run_cli(self._base(root) + ["update"])
            self.assertEqual(self._installed(root), installed)


if __name__ == "__main__":
    unittest.main()
