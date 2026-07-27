"""Assembles the OMH skill catalog and serves it.

The catalog is built by ordered mutation, and that order is the point: the
hand-written definitions come first, then the standalone quality-evidence skill,
then the feature-surface skills, then the native-capability skills. Consumers see
that order in `builtin_definitions()`, and the generated docs and skill files are
byte-compared against it, so reordering this file changes committed artifacts.

The data itself lives next door - `catalog_types` (what a skill is),
`catalog_definitions` (the hand-written skills), `catalog_feature_surfaces`
(template-built skills), and `catalog_harnesses` (runtime contracts). This module
is the assembly and the public surface: every accessor other code imports.
"""

from __future__ import annotations

from ..harness_quality import (
    build_harness_quality_contract,
    unknown_harness_quality_contract,
)

from functools import lru_cache

from .native_capability_surfaces import (
    native_capability_harnesses,
    native_capability_skill_definitions,
    native_capability_surface_exposures,
)
from .catalog_definitions import _DEFINITIONS
from .catalog_feature_surfaces import _FEATURE_SURFACE_SKILLS
from .catalog_harnesses import (
    _FEATURE_SURFACE_HARNESSES,
    _HARNESSES,
    _PRIMARY_HARNESSES,
    _feature_surface_harness,
)
# Re-exported for import compatibility: 30 modules and the test suite import
# these straight from `catalog`, so the split must not move where they are
# reachable from. They are unused inside this file by design.
from ..paper_learning import (
    PAPER_LEARNING_ACTIONS,
    PAPER_LEARNING_CARD_SCHEMA_VERSION,
    PAPER_LEARNING_COVERAGE_POLICY,
    PAPER_LEARNING_LEVELS,
    PAPER_LEARNING_NOT_OBSERVED,
    PAPER_LEARNING_SOURCE_STATES,
)
from ..routing.materials_cues import OFFICE_FILE_MATERIAL_CATALOG_TRIGGERS
from ..source_finder import (
    SOURCE_ACQUISITION_STATUS_SCHEMA_VERSION,
    SOURCE_CANDIDATE_SCHEMA_VERSION,
    SOURCE_CANDIDATE_SET_SCHEMA_VERSION,
    SOURCE_FINDER_ACQUISITION_STATES,
    SOURCE_FINDER_ACTIONS,
    SOURCE_FINDER_PLAN_SCHEMA_VERSION,
    SOURCE_FINDER_SOURCE_KINDS,
)
from .catalog_types import (
    _CATEGORY_FINAL_CHECKLISTS,
    _CATEGORY_RECOVERY_NOTES,
    _DEFAULT_GOOD_EXAMPLES,
    _GENERAL_FINAL_CHECKLIST,
    _GENERAL_RECOVERY_NOTES,
    _HANDOFF_FINAL_CHECKLIST,
    _HANDOFF_RECOVERY_NOTES,
    _HERMES_CODING_HARNESS_FINAL_CHECKLIST,
    _HERMES_SETUP_FIVE_STEP_BAR,
    _HERMES_SETUP_SKIP_SEMANTICS,
    _HERMES_SETUP_WRITE_BOUNDARY,
    _ROLE_ALIASES,
    _ROLE_BY_CATEGORY,
    _default_final_checklist,
    _default_recovery_notes,
)
from .catalog_types import (
    CODING_INTENTS,
    CODING_INTENT_PRIORITY,
    CODING_INTENT_TERMS,
    CODING_REVIEW_TERMS,
    DEEP_INTERVIEW_CLARITY_DIMENSIONS,
    DEEP_INTERVIEW_MAX_ROUNDS,
    DEEP_INTERVIEW_SOFT_CHECK_ROUND,
    HarnessDefinition,
    OMH_DESCRIPTION_PREFIX,
    OMH_SKILL_DISPLAY_NAME_OVERRIDES,
    OMH_SKILL_NAME_PREFIX,
    SkillDefinition,
    SkillExample,
    SurfaceExposure,
    ULW_ENGINE_SKILL_NAMES,
    ULW_SKILL_NAME_PREFIX,
    _CODING_INTENT_BY_SKILL,
    _feature_surface_skill,
    canonical_hermes_role,
    historical_skill_display_names,
    omh_description,
    omh_skill_display_name,
)

_DEFINITIONS.extend(_FEATURE_SURFACE_SKILLS)


_DEFAULT_SURFACE_PROJECTIONS = ("routable", "installable", "workflow_reference", "capability")
_SURFACE_EXPOSURES = (
    SurfaceExposure(
        "design-orchestration",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill for broad design ownership before handing a narrowed concern to design-quality-gate, frontend, accessibility-audit, or visual-qa.",
    ),
    SurfaceExposure(
        "quality-evidence-loop",
        "workflow_reference",
        ("workflow_reference",),
        False,
        "operator_reference",
        "Use as agent-facing catalog guidance for QA scenarios, independent review, and source-bound assessment; invoke the quality-evidence CLI only as a backend/operator control plane.",
    ),
    SurfaceExposure(
        "source-finder",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks to find or classify source candidates before learning, research, materials, or coding work.",
    ),
    SurfaceExposure(
        "paper-learning",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks to understand a supplied paper or paper PDF by level without dropping section coverage.",
    ),
    SurfaceExposure(
        "automation-blueprint",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks for recurring automation or scheduled ops planning.",
    ),
    SurfaceExposure(
        "github-event-ops",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask how to triage GitHub PR, issue, review, webhook, or CI events into label, review, or fix-handoff actions without claiming GitHub mutation.",
    ),
    SurfaceExposure(
        "agent-board",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to coordinate multiple Hermes agents, subagents, roles, handoffs, blockers, heartbeats, or board-shaped collaboration without claiming other agents accepted or completed work.",
    ),
    SurfaceExposure(
        "memory-new",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user wants to add new project, product, or durable context memory through capture, review, and approval.",
    ),
    SurfaceExposure(
        "memory-sync",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks to review stale, duplicate, or conflicting memory and skill context.",
    ),
    SurfaceExposure(
        "gateway-intent-card",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to route, notify, post, or package Discord, Slack, Telegram, webhook, thread, attachment, or silent/status-update gateway intent without claiming delivery.",
    ),
    SurfaceExposure(
        "executor-runtime-readiness",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask whether Codex, Claude Code, Hermes coding, or another runtime has the tools, credentials, worktree posture, and handoff mode needed before dispatch.",
    ),
    SurfaceExposure(
        "deliverable-package",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks for file deliverable packaging and attachment lifecycle status.",
    ),
    SurfaceExposure(
        "design-quality-gate",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a visual, web, frontend, deck, PDF, poster, or publishing deliverable must meet a superior design/content/layout QA bar.",
    ),
    SurfaceExposure(
        "frontend",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a web UI or frontend surface needs design-system, layout, responsive, accessibility, performance, and visual-QA handoff preparation.",
    ),
    SurfaceExposure(
        "accessibility-audit",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a UI surface needs WCAG, keyboard, focus, screen-reader, target-size, contrast, and reflow audit gates.",
    ),
    SurfaceExposure(
        "visual-qa",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a rendered web, image, document, or TUI surface needs fresh visual evidence, diff review, and PASS/REVISE/BLOCK gating.",
    ),
    SurfaceExposure(
        "browser-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to open URLs, click pages, log in, fill forms, capture blockers, or supervise browser interactions without claiming browser execution.",
    ),
    SurfaceExposure(
        "workspace-file-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to list, search, organize, copy, move, rename, archive, or delete local files and folders without claiming filesystem mutation.",
    ),
    SurfaceExposure(
        "command-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to prepare or supervise terminal, shell, CLI, package-manager, or test commands without claiming command execution.",
    ),
    SurfaceExposure(
        "connector-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to prepare or supervise external app, SaaS, email, ticket, calendar, CRM, or connector actions without claiming provider execution.",
    ),
    SurfaceExposure(
        "live-info-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to prepare or supervise read-only weather, finance, sports, map, place, exchange-rate, or time-zone lookups without claiming live data retrieval.",
    ),
    SurfaceExposure(
        "external-connector-readiness",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask whether an external plugin, connector, API, multimodal route, or live-data tool is ready enough to adopt, route, or trial without claiming provider execution.",
    ),
    SurfaceExposure(
        "prompt-import-readiness",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask whether external CLI-agent prompt files can be safely reviewed, normalized, and exposed as Hermes slash-command candidates without claiming prompt mutation.",
    ),
    SurfaceExposure(
        "physical-device-readiness",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use when physical device workflows need a safety envelope, gates, approval, dry-run, and observed-only trial boundary.",
    ),
    SurfaceExposure(
        "content-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask for publish-ready writing, rewriting, summarization, translation, release notes, newsletter, customer copy, or email-draft work with audience, tone, source, and review gates.",
    ),
    SurfaceExposure(
        "media-input-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to prepare or supervise audio/video transcription, YouTube/video summaries, OCR, screenshot text extraction, receipt image parsing, meeting recordings, timestamps, or clip summaries without claiming media access, transcript, OCR, or parsed-field evidence.",
    ),
    SurfaceExposure(
        "data-analysis",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to analyze supplied CSV, JSON, logs, tables, or metric-like data with schema, method, and hallucination guards.",
    ),
    SurfaceExposure(
        "build-failure-triage",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when failing build, lint, typecheck, test, CI, or DCO evidence needs minimal-fix triage.",
    ),
    SurfaceExposure(
        "voice-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when voice, mobile, dictated, or short commands need normalization, ambiguity checks, and safe confirmation before selecting a concrete workflow.",
    ),
    SurfaceExposure(
        "toolbelt-readiness",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask which plugins, MCP servers, CLIs, APIs, credentials, or external connectors a workflow needs before it can run.",
    ),
    SurfaceExposure(
        "harness-session-inventory",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when operators need a cross-harness session, MCP config, connector, wrapper, and worktree inventory with drift boundaries.",
    ),
    SurfaceExposure(
        "ops-observability-card",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when operators need an evidence-bounded command-board for telemetry, supplied metric-provider payloads, and service-quality gaps.",
    ),
    SurfaceExposure(
        "achievements",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks about unlocked hermes-achievements badges, tiers, recent unlocks, or badge progress.",
    ),
    SurfaceExposure(
        "agent-ops-review",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a manager wants quality, blockers, next actions, and throughput guidance for AI-agent work.",
    ),
    SurfaceExposure(
        "agent-debug",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when an agent run is stuck, looping, drifting, or failing repeatedly and needs evidence-bounded diagnosis plus contained recovery guidance.",
    ),
    SurfaceExposure(
        "failure-signal-audit",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when operators need to find swallowed errors, dangerous fallbacks, propagation gaps, and false-green claims before routing remediation.",
    ),
    SurfaceExposure(
        "instinct-ledger",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when repeated lessons should become reviewed, confidence-scored project or global instinct candidates without automatic hook-based learning or mutation.",
    ),
    SurfaceExposure(
        "skill-scout",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill before creating, forking, installing, or adapting a skill so operators can compare candidates and risks first.",
    ),
    SurfaceExposure(
        "skill-health",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when operators need a portfolio health dashboard for skills, generated surfaces, failure-pattern signals, pending amendments, and safe improvement actions.",
    ),
    SurfaceExposure(
        "workflow-learning",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user wants to learn from a workflow run, review an improvement candidate, create a regression case, or export a redacted review bundle.",
    ),
)


_HARNESSES.extend(_FEATURE_SURFACE_HARNESSES)


_DEFINITIONS.extend(native_capability_skill_definitions(_feature_surface_skill))
_HARNESSES.extend(native_capability_harnesses(_feature_surface_harness))
_PRIMARY_HARNESSES.update(
    {
        "decision-recall": "decision-recall",
        "run-efficiency": "run-efficiency",
        "provider-profile-posture": "provider-profile-posture",
    }
)
_CODING_INTENT_BY_SKILL.update(
    {
        "decision-recall": "planning",
        "run-efficiency": "planning",
        "provider-profile-posture": "planning",
    }
)
_SURFACE_EXPOSURES = (*_SURFACE_EXPOSURES, *native_capability_surface_exposures(SurfaceExposure))


def builtin_definitions() -> list[SkillDefinition]:
    return list(_builtin_definitions_cached())


def routable_definitions() -> list[SkillDefinition]:
    return _projected_definitions("routable")


def installable_skill_definitions() -> list[SkillDefinition]:
    return [
        definition
        for definition in _builtin_definitions_cached()
        if surface_exposure_for_skill(definition.name).install_visibility
    ]


def capability_definitions() -> list[SkillDefinition]:
    return _projected_definitions("capability")


def workflow_reference_definitions() -> list[SkillDefinition]:
    return _projected_definitions("workflow_reference")


def routable_skill_names() -> tuple[str, ...]:
    return tuple(definition.name for definition in routable_definitions())


def installable_skill_names() -> tuple[str, ...]:
    return tuple(definition.name for definition in installable_skill_definitions())


def surface_exposure_for_skill(name: str) -> SurfaceExposure:
    return _surface_exposure_by_name().get(name, _default_surface_exposure(name))


def skill_exposure_payload(name: str) -> dict[str, object]:
    exposure = surface_exposure_for_skill(name)
    return {
        "exposure": exposure.exposure,
        "projections": list(exposure.projections),
        "install_visibility": exposure.install_visibility,
        "docs_visibility": exposure.docs_visibility,
        "preferred_usage": exposure.preferred_usage,
        "compatibility_alias": exposure.compatibility_alias,
    }


def builtin_harnesses() -> list[HarnessDefinition]:
    return list(_builtin_harnesses_cached())


@lru_cache(maxsize=1)
def _builtin_definitions_cached() -> tuple[SkillDefinition, ...]:
    return tuple(_DEFINITIONS)


@lru_cache(maxsize=1)
def _surface_exposure_by_name() -> dict[str, SurfaceExposure]:
    return {exposure.name: exposure for exposure in _SURFACE_EXPOSURES}


def _default_surface_exposure(name: str) -> SurfaceExposure:
    return SurfaceExposure(
        name,
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle.",
    )


def _projected_definitions(projection: str) -> list[SkillDefinition]:
    return list(_projected_definitions_cached(projection))


@lru_cache(maxsize=8)
def _projected_definitions_cached(projection: str) -> tuple[SkillDefinition, ...]:
    return tuple(
        definition
        for definition in _builtin_definitions_cached()
        if projection in surface_exposure_for_skill(definition.name).projections
    )


@lru_cache(maxsize=1)
def _builtin_harnesses_cached() -> tuple[HarnessDefinition, ...]:
    return tuple(_HARNESSES)


@lru_cache(maxsize=1)
def _harnesses_by_name() -> dict[str, HarnessDefinition]:
    return {harness.name: harness for harness in _builtin_harnesses_cached()}


def harness_definition(name: str) -> HarnessDefinition:
    return _harnesses_by_name()[name]


def harness_quality_contract(name: str) -> dict[str, object]:
    try:
        harness = harness_definition(name)
    except KeyError:
        return unknown_harness_quality_contract(name)
    return build_harness_quality_contract(
        harness=harness.name,
        quality_tier=harness.quality_tier,
        quality_bar=harness.quality_bar,
        evidence_ladder=harness.evidence_ladder,
        wrapper_actions=harness.wrapper_actions,
        overclaim_guards=harness.overclaim_guards,
    )


def primary_harness_for_skill(name: str) -> str:
    return _PRIMARY_HARNESSES.get(name, "coding-handling")


def coding_intent_for_skill(name: str) -> str:
    return _CODING_INTENT_BY_SKILL.get(name, "coding")


def coding_skills_for_intent(intent: str) -> tuple[str, ...]:
    return _coding_skills_by_intent().get(intent, ())


@lru_cache(maxsize=1)
def _coding_skills_by_intent() -> dict[str, tuple[str, ...]]:
    return {
        intent: tuple(
            name
            for name, mapped_intent in _CODING_INTENT_BY_SKILL.items()
            if mapped_intent == intent
        )
        for intent in CODING_INTENTS
    }


def coding_terms_for_intent(intent: str) -> tuple[str, ...]:
    return CODING_INTENT_TERMS.get(intent, ())


def retained_delegation_skill_names() -> tuple[str, ...]:
    return _retained_delegation_skill_names_cached()


@lru_cache(maxsize=1)
def _retained_delegation_skill_names_cached() -> tuple[str, ...]:
    return tuple(
        definition.name
        for definition in _builtin_definitions_cached()
        if definition.delegation_boundary in {"retained", "retained-catalog-intent"}
    )


def catalog_intent_delegation_skill_names() -> tuple[str, ...]:
    return _catalog_intent_delegation_skill_names_cached()


@lru_cache(maxsize=1)
def _catalog_intent_delegation_skill_names_cached() -> tuple[str, ...]:
    return tuple(
        definition.name
        for definition in _builtin_definitions_cached()
        if definition.delegation_boundary == "retained-catalog-intent"
    )


MEMORY_CONTEXT_POLICIES = ("compact", "explicit")
_EXPLICIT_MEMORY_CONTEXT_SKILLS = (
    "ralph",
    "ultragoal",
    "loop",
    "ultraprocess",
    "team",
    "ultrawork",
    "idea-to-deploy",
    "cto-loop",
    "deploy-and-monitor",
    "ultraqa",
    "plan",
    "ralplan",
    "code-review",
    "ai-slop-cleaner",
    "performance-goal",
    "ask",
)


def memory_context_policy_for_skill(name: str) -> str:
    return "explicit" if name in _EXPLICIT_MEMORY_CONTEXT_SKILLS else "compact"


def explicit_memory_context_skill_names() -> tuple[str, ...]:
    return _EXPLICIT_MEMORY_CONTEXT_SKILLS


# The doctor health floor: skills OMH needs on disk to describe, diagnose, manage,
# and stop itself. This is intentionally small and independent of
# `installable_skill_names()` (the full catalog) so a health check does not force
# every packaged skill onto disk just to pass `omh doctor`.
CORE_SKILLS = (
    "oh-my-hermes",
    "doctor",
    "skill",
    "cancel",
    "agent-ops-review",
)

# The default install profile: the doctor health floor above, plus the workflow
# skills a messenger-first user needs for the chat/plan/status/handoff flows that
# make up a first session (planning with a coding handoff, gateway status-update
# and delivery policy for chat channels, executor runtime readiness before a
# handoff, and an ops observability card for status questions). Everything else
# in the catalog is opt-in via a `full` install so a default install does not add
# every packaged skill's context weight to every turn.
CORE_PROFILE_SKILLS = tuple(
    dict.fromkeys(
        CORE_SKILLS
        + (
            "plan",
            "gateway-intent-card",
            "executor-runtime-readiness",
            "ops-observability-card",
        )
    )
)
DESCRIPTIONS = {definition.name: definition.description for definition in _DEFINITIONS}
