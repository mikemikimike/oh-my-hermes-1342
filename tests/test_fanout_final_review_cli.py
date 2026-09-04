"""Operator-path coverage for fanout final-review execution."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import textwrap
import unittest

from _local_package import load_local_package

load_local_package()

from omh.commands.main import build_parser  # noqa: E402
from omh.coding.fanout_final_review_hook import (  # noqa: E402
    run_final_review_after_integration,
)
from omh.coding.final_review_local_engine import (  # noqa: E402
    FinalReviewLocalEngineConfig,
    FinalReviewLocalEngineError,
    HermesFinalReviewEngine,
)


_REVISION = "a" * 40
_FAKE_HERMES = r"""
#!/usr/bin/env python3
import json
from pathlib import Path
import sys

args = sys.argv[1:]
sys.stdin.read()
usage = Path(args[args.index("--usage-file") + 1])
usage.write_text(json.dumps({
    "provider": "fake-provider",
    "model": args[args.index("--model") + 1],
    "total_tokens": 1,
}), encoding="utf-8")
print("<verdict>PASS</verdict>")
"""


class FanoutFinalReviewCliTests(unittest.TestCase):
    def test_final_review_is_an_explicit_fanout_option(self) -> None:
        base = [
            "coding",
            "fanout",
            "dispatch",
            "fanout-1",
            "--goal-file",
            "goal.txt",
        ]

        self.assertFalse(build_parser().parse_args(base).final_review)
        self.assertTrue(
            build_parser().parse_args([*base, "--final-review"]).final_review
        )

    def test_sanctioned_hermes_engine_produces_four_observed_pass_lanes(
        self,
    ) -> None:
        with TemporaryDirectory(prefix="omh-final-review-") as raw:
            root = Path(raw)
            hermes = root / "hermes.py"
            hermes.write_text(
                textwrap.dedent(_FAKE_HERMES).lstrip(),
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            engine = HermesFinalReviewEngine(
                FinalReviewLocalEngineConfig(
                    worktree=root,
                    goal_text="Review the integrated implementation.",
                    provider="fake-provider",
                    model="fake-model",
                    reasoning="medium",
                    timeout_seconds=5,
                    hermes=str(hermes),
                )
            )

            result = run_final_review_after_integration(
                engine,
                integrated_revision=_REVISION,
                integration_green=True,
                producer_evidence=True,
                workspace_revision=lambda: _REVISION,
            )

        self.assertEqual(result["final_review_status"], "PASS")
        self.assertEqual(len(result["final_review_records"]), 4)
        self.assertTrue(
            all(
                record["execution_observed"]
                for record in result["final_review_records"]
            )
        )

    def test_final_review_configuration_refuses_missing_provider(self) -> None:
        with TemporaryDirectory(prefix="omh-final-review-config-") as raw:
            with self.assertRaisesRegex(
                FinalReviewLocalEngineError,
                "--hermes-provider",
            ):
                FinalReviewLocalEngineConfig(
                    worktree=Path(raw),
                    goal_text="Review.",
                    provider="",
                    model="fake-model",
                    reasoning="medium",
                    timeout_seconds=5,
                )


if __name__ == "__main__":
    unittest.main()
