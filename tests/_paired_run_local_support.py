"""Local executable and Git fixtures for paired-run CLI tests."""

from __future__ import annotations

from pathlib import Path
import subprocess


FAKE_HERMES = r"""
#!/usr/bin/env python3
import json
from pathlib import Path
import sys

root = Path(sys.argv[0]).resolve().parent
args = sys.argv[1:]
with (root / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": args, "prompt": sys.stdin.read()}) + "\n")
usage = Path(args[args.index("--usage-file") + 1])
usage.write_text(json.dumps({
    "provider": "fake-provider",
    "model": args[args.index("--model") + 1],
    "total_tokens": 3,
    "estimated_cost_usd": 0.01,
}), encoding="utf-8")
print("completed")
"""


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", *argv],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
