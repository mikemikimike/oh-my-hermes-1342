from __future__ import annotations

from typing import Final, Mapping

CODING_MODEL_ROUTE_SCHEMA_VERSION: Final[str] = "coding_model_route/v1"

# Roles are the subagent shapes a fanout/handoff unit can declare. They name the
# kind of work, never a vendor, so per-role defaults stay executor-neutral.
MODEL_ROLES: Final[tuple[str, ...]] = (
    "brain",
    "implementation",
    "design_visual",
    "review",
    "docs",
)

MODEL_ROUTE_STATUSES: Final[tuple[str, ...]] = (
    "routed",
    "choice_required",
    "model_unrouted",
    "no_model_catalog",
)

MODEL_ROUTE_SOURCES: Final[tuple[str, ...]] = (
    "request_named_model",
    "role_catalog_default",
    "role_catalog_candidates",
    "executor_default",
    "no_catalog",
)

CODING_MODEL_ROUTE_CLAIM_BOUNDARY: Final[str] = (
    "A model route is prepared metadata for a coding handoff or dispatch argv. Model availability, "
    "entitlement, pricing, and quota are provider truth omh does not observe, and a routed model is "
    "not execution, verification, review, CI, or merge evidence."
)

# Built-in default candidates per dispatchable/prompt-handoff executor profile.
# Claude Code accepts stable tier aliases that track the newest model in each
# tier; Codex takes vendor model ids. Both CLIs also accept ids this catalog
# has never heard of, so requested models always pass through unvalidated —
# the catalog is a default candidate list, not an allowlist.
MODEL_CATALOG_KIND: Final[str] = "built_in_defaults"

EXECUTOR_MODEL_OPTIONS: Final[dict[str, tuple[dict[str, object], ...]]] = {
    "codex": (
        {
            "model_id": "gpt-5-codex",
            "label": "Codex frontier coding model",
            "tier": "frontier",
            "recommended_roles": ("brain", "review", "design_visual"),
            "reasoning_efforts": ("low", "medium", "high", "xhigh"),
        },
        {
            "model_id": "gpt-5",
            "label": "General frontier model",
            "tier": "standard",
            "recommended_roles": ("implementation", "docs"),
            "reasoning_efforts": ("low", "medium", "high", "xhigh"),
        },
    ),
    "claude-code": (
        {
            "model_id": "opus",
            "label": "Claude frontier tier alias",
            "tier": "frontier",
            "recommended_roles": ("brain", "review", "design_visual"),
            "reasoning_efforts": ("low", "medium", "high"),
        },
        {
            "model_id": "sonnet",
            "label": "Claude standard tier alias",
            "tier": "standard",
            "recommended_roles": ("implementation",),
            "reasoning_efforts": ("low", "medium", "high"),
        },
        {
            "model_id": "haiku",
            "label": "Claude fast tier alias",
            "tier": "fast",
            "recommended_roles": ("docs",),
            "reasoning_efforts": ("low", "medium", "high"),
        },
    ),
}

# Model-family prefixes mirror the dynamic-workflow target classifier so both
# surfaces name families the same way; bare Claude tier aliases fold into the
# claude family because the claude CLI resolves them to concrete claude models.
_MODEL_FAMILY_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("gpt-", "gpt"),
    ("glm-", "glm"),
    ("claude-", "claude"),
    ("openai-", "openai"),
    ("anthropic-", "anthropic"),
    ("gemini-", "gemini"),
    ("qwen-", "qwen"),
    ("kimi-", "kimi"),
    ("mistral-", "mistral"),
    ("llama-", "llama"),
    ("deepseek-", "deepseek"),
    ("codestral-", "codestral"),
)
_CLAUDE_TIER_ALIASES: Final[frozenset[str]] = frozenset({"opus", "sonnet", "haiku"})

# Role-based reasoning-effort default: deep planning/architecture units get a
# high-effort default when the profile supports efforts and no effort was
# requested; every other role leaves the executor CLI default in place.
_HIGH_EFFORT_ROLES: Final[frozenset[str]] = frozenset({"brain"})
_HIGH_EFFORT_DEFAULT: Final[str] = "high"


def model_family(model_id: str) -> str:
    normalized = str(model_id or "").strip().casefold()
    if not normalized:
        return ""
    if normalized in _CLAUDE_TIER_ALIASES:
        return "claude"
    for prefix, family in _MODEL_FAMILY_PREFIXES:
        if normalized.startswith(prefix):
            return family
    return "unknown"


def resolve_model_route(
    executor_profile: str,
    *,
    requested_model: str = "",
    requested_effort: str = "",
    role: str = "",
) -> dict[str, object]:
    """Return the deterministic prepared model route for one executor profile.

    Precedence: an explicitly requested model always wins (passthrough, never
    rejected); otherwise a role with exactly one catalog candidate routes to
    it; several candidates become an explicit choice; no data leaves the
    executor CLI default in place as a named outcome rather than a guess.
    """
    profile = str(executor_profile or "").strip().casefold()
    normalized_role = _normalized_role(role)
    model = str(requested_model or "").strip()
    effort = str(requested_effort or "").strip().casefold()
    options = EXECUTOR_MODEL_OPTIONS.get(profile, ())
    candidates = [dict(option) for option in options]

    if not options and not model:
        return _route_payload(
            profile,
            status="no_model_catalog",
            source="no_catalog",
            role=normalized_role,
            candidates=[],
            reasons=[
                f"No built-in model catalog exists for `{profile or 'unknown'}`; the executor CLI default applies.",
            ],
        )

    if model:
        return _route_payload(
            profile,
            status="routed",
            source="request_named_model",
            role=normalized_role,
            selected_model=model,
            selected_reasoning_effort=_selected_effort(profile, effort, normalized_role, model),
            candidates=candidates,
            reasons=[f"The request names `{model}` directly, so the catalog is advisory only."],
        )

    if normalized_role:
        matched = [option for option in candidates if normalized_role in tuple(option.get("recommended_roles", ()))]
        if len(matched) == 1:
            selected = str(matched[0]["model_id"])
            return _route_payload(
                profile,
                status="routed",
                source="role_catalog_default",
                role=normalized_role,
                selected_model=selected,
                selected_reasoning_effort=_selected_effort(profile, effort, normalized_role, selected),
                candidates=candidates,
                reasons=[
                    f"Role `{normalized_role}` has exactly one built-in candidate for `{profile}`.",
                ],
            )
        return _route_payload(
            profile,
            status="choice_required",
            source="role_catalog_candidates",
            role=normalized_role,
            candidates=matched or candidates,
            reasons=[
                f"Role `{normalized_role}` matches {len(matched) or len(candidates)} candidates for `{profile}`; "
                "the caller picks one or names a model.",
            ],
        )

    return _route_payload(
        profile,
        status="model_unrouted",
        source="executor_default",
        role=normalized_role,
        selected_reasoning_effort=_selected_effort(profile, effort, normalized_role, ""),
        candidates=candidates,
        reasons=["No model or role was requested, so the executor CLI default model applies."],
    )


def model_route_for_unit(unit: Mapping[str, object], executor_target: str) -> dict[str, object] | None:
    """Return the prepared model route for a fanout unit, or None when unrouted."""
    model = str(unit.get("model", "") or "").strip()
    effort = str(unit.get("reasoning_effort", "") or "").strip()
    role = str(unit.get("role", "") or "").strip()
    if not model and not effort and not role:
        return None
    return resolve_model_route(
        executor_target,
        requested_model=model,
        requested_effort=effort,
        role=role,
    )


def _normalized_role(role: str) -> str:
    normalized = str(role or "").strip().casefold().replace("-", "_")
    return normalized if normalized in MODEL_ROLES else ""


def _supported_efforts(profile: str, model_id: str) -> tuple[str, ...]:
    for option in EXECUTOR_MODEL_OPTIONS.get(profile, ()):
        if str(option.get("model_id", "")).casefold() == str(model_id or "").casefold():
            return tuple(str(value) for value in option.get("reasoning_efforts", ()))
    # Unknown/passthrough models keep the profile-level union so a requested
    # effort is never silently dropped for a model the catalog has not met.
    union: list[str] = []
    for option in EXECUTOR_MODEL_OPTIONS.get(profile, ()):
        for value in option.get("reasoning_efforts", ()):
            if str(value) not in union:
                union.append(str(value))
    return tuple(union)


def _selected_effort(profile: str, requested_effort: str, role: str, model_id: str) -> str:
    if requested_effort:
        # Requested efforts pass through even off-catalog; the executor CLI is
        # the authority on what it accepts, same rule as requested models.
        return requested_effort
    if role in _HIGH_EFFORT_ROLES and _HIGH_EFFORT_DEFAULT in _supported_efforts(profile, model_id):
        return _HIGH_EFFORT_DEFAULT
    return ""


def _route_payload(
    profile: str,
    *,
    status: str,
    source: str,
    role: str,
    candidates: list[dict[str, object]],
    reasons: list[str],
    selected_model: str = "",
    selected_reasoning_effort: str = "",
) -> dict[str, object]:
    return {
        "schema_version": CODING_MODEL_ROUTE_SCHEMA_VERSION,
        "executor_profile": profile,
        "status": status,
        "source": source,
        "role": role,
        "selected_model": selected_model,
        "selected_reasoning_effort": selected_reasoning_effort,
        "model_family": model_family(selected_model),
        "candidates": [
            {
                "model_id": str(option.get("model_id", "")),
                "label": str(option.get("label", "")),
                "tier": str(option.get("tier", "")),
                "recommended_roles": list(option.get("recommended_roles", ())),
                "reasoning_efforts": list(option.get("reasoning_efforts", ())),
            }
            for option in candidates
        ],
        "catalog_kind": MODEL_CATALOG_KIND,
        "reasons": list(reasons),
        "claim_boundary": CODING_MODEL_ROUTE_CLAIM_BOUNDARY,
    }
