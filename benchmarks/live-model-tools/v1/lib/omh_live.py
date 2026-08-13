from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

from omh.coding.routing_observation import validate_routing_observation
from omh.coding.unit_prompt_protocol import calibration_for_route


_TASK_START = "OMH benchmark task:\n"
_TASK_END = "\n\nOMH benchmark protocol:"
MAX_PROMPT_BYTES = 131_072


def route_argv(
    executable: str,
    *,
    model: str,
    effort: str,
    role: str = "implementation",
) -> list[str]:
    return [
        executable,
        "coding",
        "model-route",
        "--executor",
        "hermes",
        "--model",
        model,
        "--effort",
        effort,
        "--role",
        role,
        "--json",
    ]


def dispatch_argv(
    executable: str,
    *,
    hermes_executable: str,
    workspace: Path,
    route: Mapping[str, Any],
    provider: str,
    parent_run_id: str,
    run_id: str,
    timeout: int,
) -> list[str]:
    return [
        executable,
        "coding",
        "hermes-child",
        "dispatch",
        "--confirm-dispatch",
        "--model",
        str(route["selected_model"]),
        "--provider",
        provider,
        "--reasoning",
        str(route["selected_reasoning_effort"]),
        "--parent-run-id",
        parent_run_id,
        "--run-id",
        run_id,
        "--hermes",
        hermes_executable,
        "--cwd",
        str(workspace),
        "--timeout",
        str(timeout),
        "--json",
    ]


def prompt_pair(task: str, route: Mapping[str, Any]) -> tuple[str, str]:
    common = (
        f"{_TASK_START}{task.strip()}{_TASK_END}\n"
        "Use the available file tools. Respect the working directory boundary. "
        "Return the requested answer or smallest correct edit, then stop."
    )
    calibration = calibration_for_route(route)
    optimized = common if not calibration else f"{calibration}\n\n{common}"
    return common, optimized


def task_digest(prompt: str) -> str:
    try:
        task = prompt.split(_TASK_START, 1)[1].split(_TASK_END, 1)[0]
    except IndexError as exc:
        raise ValueError("prompt does not contain the OMH benchmark task boundary") from exc
    return hashlib.sha256(task.encode("utf-8")).hexdigest()


def observation_metrics(observation: Mapping[str, Any]) -> dict[str, object]:
    errors = validate_routing_observation(observation)
    if errors:
        raise ValueError("invalid routing observation: " + "; ".join(errors))
    return {
        "status": observation.get("status"),
        "tools": observation.get("tools"),
        "tokens": observation.get("tokens"),
        "cost_usd": observation.get("cost_usd"),
    }


def run_trial(
    *,
    omh_executable: str,
    hermes_executable: str,
    workspace: Path,
    omh_home: Path,
    task: str,
    model: str,
    provider: str,
    effort: str,
    condition: str,
    parent_run_id: str,
    run_id: str,
    timeout: int,
    confirmed: bool = False,
) -> dict[str, object]:
    if not confirmed:
        raise ValueError("explicit paid-live confirmation is required at the effect boundary")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 3600:
        raise ValueError("timeout must be an integer from 1 to 3600 seconds")
    if len(task.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError(f"prompt exceeds {MAX_PROMPT_BYTES} bytes")
    route_completed = subprocess.run(
        _platform_argv(route_argv(omh_executable, model=model, effort=effort)),
        check=False,
        capture_output=True,
        text=True,
        env=_environment(omh_home),
        timeout=60,
    )
    if route_completed.returncode:
        raise RuntimeError(f"OMH model route failed with exit {route_completed.returncode}")
    route = json.loads(route_completed.stdout)
    baseline, optimized = prompt_pair(task, route)
    prompt = optimized if condition == "optimized" else baseline
    completed = subprocess.run(
        _platform_argv(dispatch_argv(
            omh_executable,
            hermes_executable=hermes_executable,
            workspace=workspace,
            route=route,
            provider=provider,
            parent_run_id=parent_run_id,
            run_id=run_id,
            timeout=timeout,
        )),
        input=prompt,
        check=False,
        capture_output=True,
        text=True,
        env=_environment(omh_home),
        timeout=timeout + 30,
    )
    if completed.returncode:
        detail = completed.stderr.strip()
        raise RuntimeError(
            f"OMH Hermes child dispatch failed with exit {completed.returncode}: {detail}"
        )
    observation = json.loads(completed.stdout)
    metrics = observation_metrics(observation)
    return {
        "schema_version": "omh_live_model_trial/v1",
        "condition": condition,
        "task_digest": task_digest(prompt),
        "route": {
            "selected_model": route["selected_model"],
            "selected_reasoning_effort": route["selected_reasoning_effort"],
            "model_family": route["model_family"],
        },
        "observation": metrics,
    }


def _platform_argv(argv: list[str]) -> list[str]:
    if sys.platform == "win32" and Path(argv[0]).suffix.casefold() == ".py":
        return [sys.executable, *argv]
    return argv


def _environment(omh_home: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["OMH_HOME"] = str(omh_home)
    return environment
