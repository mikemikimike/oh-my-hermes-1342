"""Local dispatch fixtures for fanout health-event tests."""

from __future__ import annotations

from pathlib import Path
import subprocess

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402


SHA = "a" * 40


class Clock:
    def __init__(self) -> None:
        self.value = -5

    def __call__(self) -> int:
        self.value += 5
        return self.value


class Completed:
    returncode = 0
    stdout = "done"
    stderr = ""


def _git(repo: Path, *argv: str) -> None:
    subprocess.run(
        ["git", *argv],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def dispatch_fixture(root: Path) -> tuple[OmhPaths, Path, str, dict[str, object]]:
    paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(
        repo,
        "-c",
        "user.name=tests",
        "-c",
        "user.email=tests@example.com",
        "commit",
        "-qm",
        "init",
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    contract = write_fanout_contract(
        paths,
        build_fanout_contract(
            "health telemetry",
            [{
                "unit_id": "core",
                "title": "Core",
                "owner": "codex",
                "file_scope": ["src/"],
            }],
        ),
    )
    return paths, repo, sha, contract


def runner(argv: list[str], **kwargs: object) -> object:
    if argv[0] == "git":
        return subprocess.run(argv, **kwargs)
    return Completed()


def ready(paths: OmhPaths, profile: str, **kwargs: object) -> dict[str, str]:
    return {"status": "ready", "profile": profile}
