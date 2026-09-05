"""Target-root and privacy checks for projection contract fixtures."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import subprocess


_SENTINELS = (
    b"fixture-private-message-1290",
    b"fixture-private-secret-1290",
    b"fixture-private-source-1290",
    b"fixture-private-diagnostic-1290",
)


def prepare_empty_root(raw_root: str) -> Path:
    """Accept one empty, non-symlink fixture root without removing anything."""
    root = Path(raw_root).expanduser()
    if not raw_root or root.is_symlink():
        raise ValueError("--omh-home must name a non-symlink fixture directory")
    resolved = root.resolve(strict=False)
    if resolved in {Path("/"), Path.home()}:
        raise ValueError("--omh-home must not be a filesystem or home root")
    if root.exists() and (not root.is_dir() or next(root.iterdir(), None) is not None):
        raise ValueError("--omh-home must be an empty directory")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def privacy_scan(root: Path) -> dict[str, object]:
    """Report every persisted sentinel occurrence without printing its content."""
    leaks: list[str] = []
    files = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        files += 1
        if any(marker in path.read_bytes() for marker in _SENTINELS):
            leaks.append(path.relative_to(root).as_posix())
    return {
        "supplied_sentinel_kind": "wrapper_message",
        "files_scanned": files,
        "leak_count": len(leaks),
        "leaks": leaks,
    }


def frozen_tree_stamp() -> str:
    """Return the repository tree consumed by this builder's process."""
    result = subprocess.run(
        ("git", "rev-parse", "HEAD^{tree}"),
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def fixture_digest(*, fanout_id: str, session_id: str) -> str:
    """Stable fixture identity, deliberately independent of writer timestamps."""
    basis = f"projection_contract_fixture/v1|{fanout_id}|{session_id}"
    return f"fixture-{sha256(basis.encode()).hexdigest()[:16]}"
