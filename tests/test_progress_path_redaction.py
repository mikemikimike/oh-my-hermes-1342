"""Chat-facing progress copy must not carry absolute filesystem paths.

Progress lines reach chat surfaces verbatim. An absolute path in one of them
publishes the operator's home directory — on this project's own machines that
segment is an email-shaped account name — to whatever channel renders the
line, and pads a one-line status with machine layout the reader cannot act on.

The sanitizer already dropped JSONL noise and background-process wrappers but
passed paths through untouched, so a "file was not modified" progress line
arrived in chat as a full `/Users/<account>/work/<repo>/src/...` string. These
tests lock the redaction and, just as importantly, lock what must NOT change:
relative paths are the readable form already, and URLs are not filesystem
paths.
"""

from __future__ import annotations

import unittest

from omh.coding.context_safety import (
    redact_absolute_paths,
    sanitize_user_facing_progress_text,
)


class ProgressPathRedactionTest(unittest.TestCase):
    def test_absolute_home_path_loses_the_account_segment(self) -> None:
        line = (
            "4 file(s) were NOT modified this turn: "
            "/Users/someone@example.com/work/oh-my-hermes/src/skills/render.py"
        )
        cleaned = sanitize_user_facing_progress_text(line)
        self.assertNotIn("someone@example.com", cleaned)
        self.assertNotIn("/Users/", cleaned)
        self.assertIn("src/skills/render.py", cleaned)

    def test_redaction_keeps_a_bounded_identifying_tail(self) -> None:
        redacted = redact_absolute_paths("/Users/a/work/repo/src/skills/render.py")
        self.assertEqual(redacted, ".../src/skills/render.py")

    def test_windows_paths_are_redacted_too(self) -> None:
        redacted = redact_absolute_paths(r"wrote C:\Users\someone\repo\src\main.py")
        self.assertNotIn("someone", redacted)
        self.assertIn(r"src\main.py", redacted)

    def test_relative_paths_are_left_alone(self) -> None:
        # The readable form already; rewriting it would be pure churn.
        for line in ("edited src/skills/render.py", "see tests/test_cli.py hunk 2"):
            with self.subTest(line=line):
                self.assertEqual(sanitize_user_facing_progress_text(line), line)

    def test_short_absolute_paths_keep_their_leading_separator(self) -> None:
        # Nothing to redact, so the string must survive byte-identical rather
        # than silently becoming a relative-looking path.
        self.assertEqual(redact_absolute_paths("see /etc/hosts"), "see /etc/hosts")

    def test_urls_and_ratios_are_not_mistaken_for_paths(self) -> None:
        for line in ("visit https://example.com/a/b/c now", "ratio 3/4 done"):
            with self.subTest(line=line):
                self.assertEqual(redact_absolute_paths(line), line)

    def test_redaction_runs_before_the_existing_noise_filters(self) -> None:
        # A path riding inside a background-process wrapper must be dropped
        # with the wrapper, not resurrected by the redaction pass.
        line = (
            "[Background process abc finished with exit code 0~ Here's the final output:] "
            "/Users/someone/work/repo/src/skills/render.py changed"
        )
        cleaned = sanitize_user_facing_progress_text(line)
        self.assertNotIn("/Users/", cleaned)
        self.assertNotIn("Background process", cleaned)


if __name__ == "__main__":
    unittest.main()
