from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

from ..coding.hermes_model_config import (
    AliasCollisionError,
    HermesModelConfigError,
)
from ..coding.model_recommendations import (
    SHIPPED_MODEL_RECOMMENDATIONS,
    merge_recommendation_catalog,
)
from ..installer import OmhError
from .language import tr
from .model_setup_inputs import (
    classified_model_candidates,
    confirmed_model_ids,
    model_alias_changes,
)
from .model_setup_overrides import load_omo_category_overrides
from .model_setup_projections import provider_next_actions, recommendation_projections


@dataclass(frozen=True, slots=True)
class ModelSetupFlowDependencies:
    discover_local_models: Callable
    inspect_hermes_model_config: Callable
    preview_hermes_model_config: Callable
    apply_hermes_model_config: Callable
    resolve_model_recommendation: Callable
    ask_yes_no: Callable
    ask: Callable
    use_color: Callable
    print_model_preview_review: Callable


def model_activation_result(
    args: argparse.Namespace,
    *,
    language: str,
    dependencies: ModelSetupFlowDependencies,
) -> dict[str, object]:
    discovery = dependencies.discover_local_models(Path.home())
    inspection = dependencies.inspect_hermes_model_config()
    confirmed = confirmed_model_ids(getattr(args, "confirm_model", []))
    candidates = classified_model_candidates(discovery, confirmed)
    aliases = model_alias_changes(getattr(args, "model_alias", []))

    if getattr(args, "interactive", False):
        confirmed = _confirm_discovered_models(
            candidates,
            confirmed,
            language=language,
            dependencies=dependencies,
        )
        candidates = classified_model_candidates(discovery, confirmed)
        aliases = _edit_model_aliases(aliases, confirmed, dependencies=dependencies)

    active_models = [
        {
            "status": "confirmed_active",
            "model_alias": model_id.rsplit("/", 1)[-1],
            "model_id": model_id.rsplit("/", 1)[-1],
            "provider": model_id.partition("/")[0] if "/" in model_id else "",
            "provider_family": model_id.partition("/")[0] if "/" in model_id else "",
        }
        for model_id in sorted(confirmed)
    ]
    omo_overrides = None
    omo_override_source = ""
    if getattr(args, "import_omo_category_overrides", False):
        try:
            omo_overrides, omo_override_source = load_omo_category_overrides(Path.home())
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise OmhError(f"cannot import OMO category overrides: {exc}") from exc
    recommendation_catalog = merge_recommendation_catalog(
        SHIPPED_MODEL_RECOMMENDATIONS,
        omo_overrides,
    )
    explicit_main = aliases.get("main") or ""
    recommendation = dependencies.resolve_model_recommendation(
        owner="hermes",
        active_models=active_models,
        role_slot="main",
        explicit_model=explicit_main,
        catalog=recommendation_catalog,
    )
    recommendations = recommendation_projections(
        active_models=active_models,
        catalog=recommendation_catalog,
        main=recommendation,
        resolve_model_recommendation=dependencies.resolve_model_recommendation,
        omo_overrides=omo_overrides,
        omo_override_source=omo_override_source,
    )
    next_actions = provider_next_actions(confirmed, inspection)

    preview = None
    apply_status: dict[str, object] = {
        "status": "declined" if aliases else "not_requested",
        "commands": [],
    }
    verification: dict[str, object] = {"status": "not_run", "verified": False}
    status = "unconfigured"
    next_action = "confirm_active_model"

    if recommendation["status"] == "choice_required":
        status = "choice_required"
    elif aliases:
        try:
            model_preview = dependencies.preview_hermes_model_config(
                inspection,
                aliases,
                allow_collisions=bool(getattr(args, "allow_model_alias_collision", False)),
            )
        except AliasCollisionError as exc:
            if not getattr(args, "interactive", False):
                raise OmhError(str(exc)) from exc
            if not dependencies.ask_yes_no(
                tr(language, "model_setup_collision_prompt", collision=str(exc)),
                default=False,
                use_color=dependencies.use_color(),
                language=language,
            ):
                raise OmhError(str(exc)) from exc
            model_preview = dependencies.preview_hermes_model_config(
                inspection,
                aliases,
                allow_collisions=True,
            )
        except HermesModelConfigError as exc:
            raise OmhError(str(exc)) from exc
        preview = _model_preview_payload(model_preview)
        status = "preview_ready"
        next_action = "apply_model_config"
        if getattr(args, "interactive", False):
            dependencies.print_model_preview_review(preview, language=language)
            args.apply_model_config = dependencies.ask_yes_no(
                tr(language, "model_setup_apply_prompt"),
                default=False,
                use_color=dependencies.use_color(),
                language=language,
            )
        if getattr(args, "apply_model_config", False):
            expected_digest = str(getattr(args, "model_config_digest", "") or "")
            if getattr(args, "interactive", False) and not expected_digest:
                expected_digest = model_preview.config_digest
            if not expected_digest:
                raise OmhError("--apply-model-config requires --model-config-digest from this preview.")
            try:
                receipt = dependencies.apply_hermes_model_config(
                    model_preview,
                    confirmed=True,
                    expected_config_digest=expected_digest,
                )
            except HermesModelConfigError as exc:
                raise OmhError(str(exc)) from exc
            apply_status = {
                "status": "applied",
                "commands": [list(command) for command in receipt.commands],
                "before_digest": receipt.before_digest,
                "after_digest": receipt.after_digest,
            }
            verification = {
                "status": "verified" if receipt.verified else "failed",
                "verified": receipt.verified,
                "config_digest": receipt.after_digest,
            }
            status = "verified" if receipt.verified else "verification_failed"
            next_action = "model_setup_complete" if receipt.verified else "inspect_model_config"
    elif confirmed:
        next_action = "edit_model_recommendations"
    else:
        next_action = "confirm_active_model"

    return {
        "schema_version": "omh_model_activation/v1",
        "status": status,
        "stages": ["inspect", "confirm_active", "preview", "apply", "verify"],
        "discovery": discovery,
        "inspection": _model_inspection_payload(inspection),
        "candidates": candidates,
        "recommendations": recommendations,
        "provider_next_actions": next_actions,
        "preview": preview,
        "apply": apply_status,
        "verification": verification,
        "next_action": next_action,
        "claim_boundary": (
            "Model activation uses local metadata and explicit confirmation only. "
            "Observed-before records are not active-model confirmation, and preview is not apply."
        ),
    }


def _confirm_discovered_models(
    candidates: list[dict[str, str]],
    confirmed: set[str],
    *,
    language: str,
    dependencies: ModelSetupFlowDependencies,
) -> set[str]:
    selected = set(confirmed)
    for candidate in candidates:
        if candidate["model"] in selected:
            continue
        if dependencies.ask_yes_no(
            tr(language, "model_setup_confirm_prompt", model=candidate["model"]),
            default=False,
            use_color=dependencies.use_color(),
            note=tr(language, "model_setup_observed_note", status=candidate["status"]),
            language=language,
        ):
            selected.add(candidate["model"])
    return selected


def _edit_model_aliases(
    aliases: dict[str, str],
    confirmed: set[str],
    *,
    dependencies: ModelSetupFlowDependencies,
) -> dict[str, str]:
    if aliases or not confirmed:
        return aliases
    default_model = sorted(confirmed)[0]
    raw = dependencies.ask(
        "Hermes main model alias (provider/model, blank to leave unconfigured)",
        default=default_model,
        use_color=dependencies.use_color(),
    ).strip()
    return {"main": raw} if raw else {}


def _model_preview_payload(preview) -> dict[str, object]:
    return {
        "config_path": str(preview.config_path),
        "config_digest": preview.config_digest,
        "changes": dict(preview.changes),
        "commands": [list(command) for command in preview.commands],
    }


def _model_inspection_payload(inspection) -> dict[str, object]:
    return {
        "config_path": str(inspection.config_path),
        "config_digest": inspection.config_digest,
        "config_check_ok": inspection.config_check_ok,
        "aliases": dict(inspection.model_dot_aliases),
        "providers": [
            {
                "provider_id": provider.provider_id,
                "auth_present": provider.auth_present,
                "auth_status_ok": provider.auth_status_ok,
                "plugin_present": provider.plugin_present,
            }
            for provider in inspection.providers
        ],
        "commands": [list(command) for command in inspection.commands],
    }
