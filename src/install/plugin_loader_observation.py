from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Any

from ..plugin_bundle.omh.metadata import PROVIDED_HOOKS, PROVIDED_TOOLS
from ..release_smoke_core import CommandResult, Runner, subprocess_runner_exact_env

_OBSERVATION_PREFIX = "OMH_PLUGIN_LOADER_OBSERVATION="
_PROBE_SCRIPT = r"""
import json

from hermes_cli.plugins import PluginManager

manager = PluginManager()
manager.discover_and_load(force=True)
loaded = manager._plugins.get("omh")
payload = {
    "enabled": bool(loaded and loaded.enabled),
    "error": None if loaded is None else loaded.error,
    "tools": [] if loaded is None else sorted(loaded.tools_registered),
    "hooks": [] if loaded is None else sorted(loaded.hooks_registered),
}
print("OMH_PLUGIN_LOADER_OBSERVATION=" + json.dumps(payload, sort_keys=True))
"""


def observe_real_loader_registration(
    plugin_dir: Path,
    *,
    python_executable: Path | None = None,
    runner: Runner | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    hermes_python = python_executable or _find_hermes_python()
    if hermes_python is None or not hermes_python.is_file():
        return _not_observed("hermes_not_installed")
    if not plugin_dir.is_dir():
        return _not_observed("plugin_bundle_not_installed")

    execute = runner or subprocess_runner_exact_env
    with TemporaryDirectory(prefix="omh-hermes-loader-") as tmp:
        hermes_home = Path(tmp)
        isolated_plugin = hermes_home / "plugins" / "omh"
        isolated_plugin.parent.mkdir(parents=True)
        shutil.copytree(plugin_dir, isolated_plugin)
        (hermes_home / "config.yaml").write_text(
            "plugins:\n  enabled:\n    - omh\n  disabled: []\n",
            encoding="utf-8",
        )
        env = {
            "HOME": os.environ.get("HOME", ""),
            "HERMES_HOME": str(hermes_home),
            "PATH": os.environ.get("PATH", ""),
        }
        command = [str(hermes_python), "-c", _PROBE_SCRIPT]
        try:
            result = execute(command, timeout_seconds, env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _not_observed("loader_probe_failed", detail=type(exc).__name__)

    if result.returncode != 0:
        return _not_observed(
            "loader_probe_failed",
            detail=_bounded_detail(result.stderr or result.stdout),
        )
    payload = _parse_observation(result)
    if payload is None:
        return _not_observed("loader_probe_failed", detail="invalid_probe_output")

    tools = _string_list(payload.get("tools"))
    hooks = _string_list(payload.get("hooks"))
    enabled = payload.get("enabled") is True
    ok = enabled and tools == sorted(PROVIDED_TOOLS) and hooks == sorted(PROVIDED_HOOKS)
    error = payload.get("error")
    return {
        "schema_version": "plugin_loader_observation/v1",
        "observed": True,
        "ok": ok,
        "reason": "registration_matches_manifest" if ok else "registration_mismatch",
        "enabled": enabled,
        "error": "" if error is None else _bounded_detail(str(error)),
        "registered_tools": tools,
        "registered_hooks": hooks,
        "expected_tools": sorted(PROVIDED_TOOLS),
        "expected_hooks": sorted(PROVIDED_HOOKS),
    }


def _find_hermes_python() -> Path | None:
    override = " ".join(os.environ.get("HERMES_PYTHON", "").split())
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    candidate = Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python"
    if candidate.is_file():
        return candidate
    executable = shutil.which("hermes")
    if not executable:
        return None
    try:
        first_line = Path(executable).read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeError, IndexError):
        return None
    if first_line.startswith("#!") and "python" in first_line.lower():
        candidate = Path(first_line[2:].strip())
        return candidate if candidate.is_file() else None
    return None


def _parse_observation(result: CommandResult) -> dict[str, Any] | None:
    for line in reversed(result.stdout.splitlines()):
        if not line.startswith(_OBSERVATION_PREFIX):
            continue
        try:
            payload = json.loads(line.removeprefix(_OBSERVATION_PREFIX))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(str(item) for item in value if isinstance(item, str))


def _bounded_detail(value: str) -> str:
    return " ".join(value.split())[:300]


def _not_observed(reason: str, *, detail: str = "") -> dict[str, Any]:
    return {
        "schema_version": "plugin_loader_observation/v1",
        "observed": False,
        "ok": False,
        "reason": reason,
        "detail": detail,
        "registered_tools": [],
        "registered_hooks": [],
        "expected_tools": sorted(PROVIDED_TOOLS),
        "expected_hooks": sorted(PROVIDED_HOOKS),
    }


__all__ = ["observe_real_loader_registration"]
