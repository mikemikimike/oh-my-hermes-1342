from __future__ import annotations

from typing import Callable

from .language import tr


def print_model_preview_review(
    payload: dict[str, object],
    *,
    language: str,
    use_color: Callable[[], bool],
    color: Callable[[str, str, bool], str],
) -> None:
    print("")
    print(color(tr(language, "model_setup_preview_title"), "1;32", use_color()))
    print(f"  config: {payload.get('config_path', '')}")
    print(f"  digest: {payload.get('config_digest', '')}")
    changes = payload.get("changes", {})
    if isinstance(changes, dict):
        for alias, model in changes.items():
            print(f"  {alias} -> {model}")


def print_model_activation_summary(
    payload: dict[str, object],
    *,
    language: str,
    use_color: Callable[[], bool],
    color: Callable[[str, str, bool], str],
) -> None:
    print("")
    print(color(tr(language, "model_setup_title"), "1;32", use_color()))
    print(f"  {tr(language, 'model_setup_scan')}")
    discovery = payload.get("discovery", {})
    sources = discovery.get("sources", {}) if isinstance(discovery, dict) else {}
    if isinstance(sources, dict):
        for name, result in sources.items():
            if not isinstance(result, dict):
                continue
            reasons = result.get("truncated_reasons", [])
            suffix = (
                f" ({tr(language, 'model_setup_truncated', reasons=', '.join(str(item) for item in reasons))})"
                if reasons
                else ""
            )
            print(f"  - {name}: {result.get('status', 'unobserved')}{suffix}")
    candidates = payload.get("candidates", [])
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                print(f"  - {candidate.get('model', '')}: {candidate.get('status', 'unobserved')}")
    if not any(
        isinstance(candidate, dict) and candidate.get("status") == "confirmed_active"
        for candidate in candidates if isinstance(candidates, list)
    ):
        print(f"  {tr(language, 'model_setup_no_active')}")
    print(f"  {tr(language, 'model_setup_status', status=payload.get('status', 'unconfigured'))}")
    print(f"  {tr(language, 'model_setup_next', action=payload.get('next_action', ''))}")
