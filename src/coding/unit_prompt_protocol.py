"""Verification discipline for prepared fanout unit prompts.

Six deterministic text blocks ride every dispatched unit prompt:

1. **Goal echo-back** — before any tool use the subagent restates the goal,
   its own deliverable, and the completion criteria, and stops to report (not
   guess) if its reading conflicts with the declared boundary.
2. **Pre-declared completion criteria** — "done" is defined BEFORE work
   starts, as a numbered list derived from the unit contract, so completion
   is a check against stated criteria rather than a feeling.
3. **Verification stop conditions** — verification is mandatory (exactly one
   full pass is the floor, never skipped) and bounded (after the criteria
   pass, re-verifying is forbidden; on failure, at most two fix-and-verify
   cycles before reporting the failing criterion instead of looping).
4. **Failure-kind discipline** — a permission, sandbox, or policy denial is
   a boundary, not a bug (never retried through another route), and
   "blocked" requires a named concrete condition that survives the bounded
   fix cycles — difficulty, uncertainty, or remaining work is not blocked.
5. **Structured return** — the unit's final report ends with one fenced
   JSON object in the `fanout_unit_result/v1` expected-evidence shape. The
   sidecar file is the primary machine-read return; when a contracted
   sidecar is missing the collector parses this block from captured stdout
   and validates it the same way, so collection is parse-then-validate on
   either path and never prose-scraping.
6. **Capped structural search** — code exploration is bounded the same way
   verification is: a few targeted structural-search-or-grep passes before a
   full-file read, escalating only when a bounded pass finds nothing or stays
   ambiguous, and stopping the moment the target is found. Shared verbatim
   with the `executor_prompting_contract/v1` payload's
   `structural_search_discipline` field (`.coding_contracts.
   STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE`) so the two cannot drift.

The blocks split across two placement zones for prompt-cache hygiene: the
goal echo-back, verification-stop, failure-kind, structured-return, and
capped-search blocks are unit-invariant,
so `shared_unit_preamble_lines()` places them (with the overall goal) at the
byte-identical head every sibling prompt of one fanout shares, and
`unit_protocol_lines()` carries only the unit-varying remainder — numbered
criteria, role protocol, calibration, and the domain bundle. Every major
serving stack caches prompt prefixes by exact bytes, so sibling prompts that
share their head let the first dispatch write the cache the rest read; the
rule itself ships as `PROMPT_CACHE_COMPOSITION_PROTOCOL`.

High-effort routes additionally get a per-family calibration block that
counters the known over-verification inertia of strong reasoning models.
Calibration is keyed by model family and selected only when the routed
reasoning effort is in the high tier; families the table has not met get the
generic block — no family carries richer guidance than another without a
stated reason, and no vendor is privileged.

Everything here is pure data and pure functions: the blocks land in prepared
prompts (subprocess argv), so the total prompt size is policy-gated by
`UNIT_PROMPT_MAX_BYTES` in tests rather than trimmed at runtime.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

from .coding_contracts import STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE
from .model_contracts import contract_model_id

# Policy ceiling for a fully-assembled unit prompt (bytes of UTF-8). The
# worst-case combination across roles, owners, and calibration blocks is
# asserted under this in tests; runtime never truncates.
UNIT_PROMPT_MAX_BYTES: Final[int] = 8000

# Reasoning efforts that mark a route as high-effort for calibration purposes.
HIGH_EFFORT_TIER: Final[frozenset[str]] = frozenset({"high", "xhigh", "max"})

GOAL_ECHO_PROTOCOL: Final[str] = (
    "Before your first tool use, restate in your own words: (1) the overall goal in one sentence, "
    "(2) this unit's deliverable, and (3) the numbered completion criteria below. If your restatement "
    "conflicts with the declared boundary or criteria, stop and report the conflict instead of guessing."
)

VERIFICATION_STOP_PROTOCOL: Final[str] = (
    "Verification discipline: run exactly ONE full verification pass against the numbered criteria after "
    "finishing the work — verification is never skipped. A check failure blocks completion only when it "
    "violates a stated criterion; note anything else as an observation and move on. Once every criterion "
    "has passed, STOP: do not re-verify, do not add a just-to-be-sure pass, and do not restart verification "
    "after edits that no criterion covers. If a criterion still fails after two fix-and-verify cycles, "
    "commit what passes and report the failing criterion with its output instead of looping."
)

FAILURE_KIND_PROTOCOL: Final[str] = (
    "Failure-kind discipline: a permission, sandbox, or policy denial is a boundary, not a bug — do "
    "not retry it through another tool or route; record the denial and continue with what the boundary "
    "allows, or report it. Report blocked only when the same concrete condition still holds after the "
    "bounded fix-and-verify cycles, and name that condition; difficulty, uncertainty, or useful "
    "remaining work is not blocked. When the unit's whole objective is unreachable for a reason a retry "
    "cannot change — the target does not exist, the request is refused by policy, or the acceptance "
    "criteria are infeasible as specified — report process_status process_declined with a decline_reason "
    "instead of process_failed: a decline is a conclusive negative answer, never a bug to retry."
)

# The sidecar file is the primary machine-read return
# (`fanout_dispatch._intake_unit_result`). The block restates the sidecar
# object when a sidecar path was given, so the two returns cannot disagree,
# and when the contracted sidecar file is missing the collector falls back
# to parsing this block out of captured stdout and validating it against the
# same `fanout_unit_result/v1` schema (`fanout_unit_results.
# validate_unit_result`) plus the dispatch identity check; nothing scrapes
# the surrounding prose for results. Executor-neutral: every owner emits the
# same shape.
UNIT_RESULT_RETURN_PROTOCOL: Final[str] = (
    "Structured return: end your final report with exactly one fenced ```json code block containing "
    "a single JSON object in the fanout_unit_result/v1 shape — schema_version, unit_id, run_id, "
    "fanout_id, base_sha, head_sha, process_status, changed_paths, checks, findings — reusing any "
    "dispatch-bound identity values given in this prompt verbatim, and restating the sidecar object "
    "when a sidecar path was given. The sidecar file is the machine-read return; when it is missing "
    "the collector parses this block instead and validates it against the same schema. Prose "
    "outside the block is context for people and is never scraped for results."
)

PROMPT_CACHE_COMPOSITION_PROTOCOL: Final[str] = (
    "Prompt-cache discipline: every major serving stack caches prompt prefixes by exact bytes "
    "(Anthropic prefix caching, OpenAI automatic prefix caching, Gemini implicit caching, DeepSeek "
    "context caching), and one changed byte invalidates everything after it. Keep the shared preamble "
    "byte-identical across sibling unit prompts — stable ordering, no timestamps, counts, or other "
    "volatile status — append unit-specific content after the shared preamble, and stagger a fan-out "
    "so the first dispatch writes the cache its siblings read."
)

REVIEW_ROLE_PROTOCOL: Final[str] = (
    "Review discipline: a finding blocks only when it violates a stated success criterion of the reviewed "
    "work; list every other finding as non-blocking. Cap re-review at two rounds — after that, report the "
    "remaining criterion-cited blockers rather than starting another round."
)

# Per-family counters to the over-verification inertia of high-effort routes.
# Keyed by `model_family()` output; "generic" is the mandatory fallback so an
# unknown family never gets weaker discipline than a known one.
HIGH_EFFORT_CALIBRATIONS: Final[dict[str, str]] = {
    "gpt": (
        "High-effort calibration: your reasoning depth is for the hard parts of THIS unit, not for "
        "re-deriving settled facts. Once the decisive fact is in view, act on it; once a criterion has "
        "passed, it is settled evidence — reopen it only when new output contradicts it, never to "
        "reassure yourself."
    ),
    "claude": (
        "High-effort calibration: follow the numbered criteria as the complete checklist — do not grow "
        "the checklist mid-run, and once you have enough to act, act instead of gathering more context. "
        "Deliberate deeply only where correctness is genuinely at risk; mechanical steps run directly and "
        "the single verification pass proves them. Edit surgically rather than rewriting a file; fix "
        "only what the criteria name and report adjacent findings instead of changing them; keep scratch "
        "checks out of the repository, and commit tests only where a criterion asks for them or the repo "
        "already keeps tests for this kind of change, sized like their neighbors. Add no helpers, "
        "fallbacks, validation, flags, or shims beyond what the criteria name; when you can just change "
        "the code, change it. Before each tool turn, privately list what you need next and request every "
        "independent item in that one response. No one is watching this unit in real time: proceed on "
        "every reversible action inside the boundary without asking, and if your last paragraph is a "
        "plan, a question, or a promise, do that work now. Every progress claim points at a tool result "
        "from this run — a failed check is reported with its output, a skipped step as skipped."
    ),
    "gemini": (
        "High-effort calibration: a claim without the tool output that proves it is not evidence — "
        "run the actual check and report from its output, never from memory. Done-sounding language "
        "before the single mandatory verification pass is a failure, not optimism, and creative "
        "expansion outside the declared boundary is a defect here, not an improvement."
    ),
    "grok": (
        "High-effort calibration: speed is your default; the numbered criteria are the brake. A fast "
        "first answer never skips the single mandatory verification pass, and a quicker path never "
        "trades away the declared boundary. When search surfaces many candidates, pick by the stated "
        "criteria once and act instead of re-querying for reassurance."
    ),
    "kimi": (
        "High-effort calibration: reserve the decompose-compare-verify loop for the genuinely hard "
        "parts; mechanical steps are low-entropy — execute them directly without enumerating "
        "alternatives. Decide each approach once and reopen it only when new output contradicts it. "
        "If you catch yourself listing options for a step no criterion distinguishes, stop analyzing "
        "and act."
    ),
    "glm": (
        "High-effort calibration: use interleaved reasoning only where it improves a tool decision: "
        "interpret each result, choose the next bounded action, and preserve prior reasoning context "
        "when the runtime exposes it — returned complete and unmodified, in its original order, as "
        "this family's preserved-thinking contract expects. The 5.3 generation cannot disable "
        "thinking, so reasoning depth is the routed effort level, never a request for no thinking. "
        "Mechanical steps need no extended plan. Keep the change goal-shaped, and let the single "
        "verification pass prove it."
    ),
    "qwen": (
        "High-effort calibration: current Qwen3-Coder is a non-thinking coding-agent model, so do not "
        "ask it to emit reasoning or thinking tags. Give the exact goal, repository state, allowed "
        "boundaries, tool schemas, and completion criteria, then follow one explicit plan. Recover "
        "from failures using observed tool output and stop after one passing verification run."
    ),
    "deepseek": (
        "High-effort calibration: treat the model version and declared thinking mode as contract "
        "fields; never apply legacy R1 prompting to every DeepSeek model. Preserve runtime-provided "
        "reasoning context across tool results only on a reasoning-capable route; otherwise use the "
        "same explicit goal, boundaries, and completion criteria without thinking tags. Edit by exact "
        "literal strings — a unique match with exact whitespace — as this family's edit training "
        "expects. Make the smallest correct change, verify once, and stop."
    ),
    "mistral": (
        "High-effort calibration: instructions are followed literally here, so the stated criteria "
        "are the whole contract — check every one even when the change looks obviously right. "
        "Concision is for the output, never for the evidence: the single mandatory verification "
        "pass runs regardless of how small the diff is."
    ),
    "llama": (
        "High-effort calibration: the serving deployment is part of the contract — tool-calling "
        "support, context limits, and output limits come from the host, not the model name. Prove a "
        "capability with a real call before depending on it, fall back to explicit step-by-step "
        "tool use when structured calling is unreliable, and stop after one passing verification run."
    ),
    "codestral": (
        "High-effort calibration: this is a code-completion specialist — work in file-scoped, "
        "concrete edits rather than open-ended investigation, keep each step's expected output "
        "small and explicit, and prove the change with the repository's own check commands instead "
        "of prose explanation."
    ),
    "solar": (
        "High-effort calibration: an efficient instruction-follower, not a long-horizon reasoner — "
        "follow the one explicit plan you were given in bounded steps instead of deriving a new "
        "one, report a missing constraint rather than inferring it, and verify once against the "
        "stated criteria before stopping."
    ),
    "generic": (
        "High-effort calibration: reserve extended reasoning for genuine ambiguity with materially "
        "different outcomes. Decide once, act, verify once against the criteria, and stop — speed is "
        "never a reason to skip the verification pass, and thoroughness is never a reason to repeat it."
    ),
}


# Calibration for the MAIN agent — the one COMPOSING the split, the unit
# prompts, and the briefings — keyed by ITS OWN model family. The user picks
# what Hermes runs on (a claude-family fable/opus, a gpt-family sol/terra, a
# gemini, a kimi, a qwen, ...), and each family fails composition differently: the
# guidance counters the composer's own defaults, never the subagents'.
# Same key set as HIGH_EFFORT_CALIBRATIONS (parity-tested) so no family gets
# subagent discipline without composer discipline, and "generic" stays the
# mandatory fallback for families the table has not met.
MAIN_AGENT_COMPOSITION_CALIBRATIONS: Final[dict[str, str]] = {
    "gpt": (
        "Composition calibration: compose outcome-first, but never compress the contract away — "
        "every unit prompt keeps its declared boundary, dependencies, numbered criteria, and the "
        "one-pass verification floor spelled out. A tighter prompt that drops a stated invariant is "
        "a worse prompt."
    ),
    "claude": (
        "Composition calibration: split only what the goal requires — no speculative units, and no unit "
        "whose only job is re-checking the split itself; a fresh-context review of a unit's deliverable "
        "against its criteria is a legitimate unit. Delegate a unit when it is independent of the work "
        "you keep and its completion can be judged from the evidence it returns; keep in line anything "
        "that finishes in a handful of tool calls, and keep working while delegated units run. The "
        "criteria you write are a closed checklist: state them once, completely, and freeze. If your "
        "closing paragraph is a dispatch you could run, run it before closing. Your closing report is "
        "the reader's first look at the run — lead with the outcome in plain sentences, drop the "
        "working shorthand, and give the one or two things you need from them."
    ),
    "gemini": (
        "Composition calibration: compose from tool-verified facts, not recall — run the inventory "
        "and readiness commands before naming owners or models, and never describe a unit as "
        "prepared until the actual prepare command produced its artifact. A split narrated without "
        "the commands behind it is not a split."
    ),
    "kimi": (
        "Composition calibration: partitioning work is mostly low-entropy — decide the split once, "
        "freeze it, and reserve deep reasoning for boundary overlaps and dependency cycles. Do not "
        "enumerate alternative splits nobody asked for; if two partitions both satisfy the "
        "boundaries, take the first and move."
    ),
    "glm": (
        "Composition calibration: use interleaved reasoning only to interpret evidence between "
        "contract-building tools; mechanical field assembly needs no extra planning. This family "
        "rewards lean, mechanically explicit unit prompts — exact schemas and invocation rules over "
        "narrative instruction — and its tool-call formatting decays in very long contexts, so keep "
        "each unit's scope bounded rather than letting one unit sprawl. Z.ai prices cached input "
        "separately, so the shared prompt-cache discipline is billing-visible on this family. Every "
        "unit carries its owner, boundary, and known route fields. Once boundaries are clean and "
        "dependencies acyclic, freeze the smallest split that covers the goal."
    ),
    "grok": (
        "Composition calibration: speed never skips freeze-time validation — run the overlap and "
        "cycle checks before recording the contract, not after dispatch fails. Pick the partition "
        "once by the stated boundaries and dispatch; re-querying for a better split is re-verifying "
        "a settled decision."
    ),
    "qwen": (
        "Composition calibration: current Qwen3-Coder is non-thinking; freeze one ordered split with "
        "exact owners, boundaries, tool contracts, dependencies, roles, and verification commands "
        "instead of requesting reasoning tags. Validate once and move to dispatch."
    ),
    "deepseek": (
        "Composition calibration: keep the DeepSeek model version and thinking mode explicit in the "
        "prepared route. Preserve runtime reasoning context only when the selected model and executor "
        "support it; otherwise compose exact owners, scopes, dependencies, and verification commands "
        "without synthetic thinking instructions. DeepSeek serving prices cached prefixes, so the "
        "shared prompt-cache discipline is billing-visible on this family, not merely latency. "
        "Validate once and stop."
    ),
    "mistral": (
        "Composition calibration: write unit prompts literally and completely — a Mistral-family "
        "executor follows what is written, not what was implied, so every boundary, dependency, "
        "criterion, and verification command must be stated; never rely on the unit inferring an "
        "unstated invariant."
    ),
    "llama": (
        "Composition calibration: compose for the deployment, not the brand — confirm the served "
        "variant's tool contract and context budget before assigning units, and keep each unit "
        "prompt self-contained so a host with a smaller context window still receives the full "
        "contract."
    ),
    "codestral": (
        "Composition calibration: route codestral units as narrow, file-scoped implementation "
        "slices with exact verification commands; investigation, review, and synthesis belong on a "
        "generalist lane, and a unit that mixes them belongs split."
    ),
    "solar": (
        "Composition calibration: put the depth in the composition, not the unit — give each solar "
        "unit one explicit plan with short bounded steps, exact criteria, and its verification "
        "command, because the unit will execute the plan it is given rather than derive a better one."
    ),
    "generic": (
        "Composition calibration: compose the contract fields exactly, validate the split once with "
        "the validation command, and stop — composing is preparing evidence, and a prepared "
        "contract is the only proof a split exists."
    ),
}


# Exact-model overrides, resolved BEFORE the family tables. A generation whose
# documented traits differ from its family's (GPT-6 Astra against the GPT-5.6
# guidance) gets its own counter here without touching the family block, so
# the older generation's prompts stay byte-stable. Keyed by the exact model
# id after the provider prefix is stripped (`contract_model_id`); the two
# tables share one key set (parity-tested) for the same reason the family
# tables do. Resolution order everywhere: exact model -> family -> generic.
MODEL_HIGH_EFFORT_CALIBRATIONS: Final[dict[str, str]] = {
    # GPT-6 Astra, per OpenAI's latest-model guide (2026-09): asks more
    # readily, follows instructions more strictly and pauses on conflicting
    # skill text, delegates less than a harness expects, and tests more
    # broadly than a change needs. Each sentence counters one of those; the
    # universal echo-back, criteria, one-pass verification, and repair caps
    # are not restated. No monitoring language, no chain-of-thought requests.
    "gpt-6-astra": (
        "High-effort calibration: the user's instructions outrank any skill or guideline text, and "
        "the numbered criteria are the complete task — carry them to completion instead of pausing "
        "for sign-off on work the boundary already authorizes. Ask one focused question only when a "
        "missing input would materially change the result; otherwise state the assumption and "
        "proceed. Size tests to the change: a reversible, low-impact edit that mirrors its "
        "implementation needs no new test, and a green check is re-run only when its inputs changed."
    ),
}
MODEL_COMPOSITION_CALIBRATIONS: Final[dict[str, str]] = {
    "gpt-6-astra": (
        "Composition calibration: write the user's intent into each unit prompt above any skill "
        "text, so a delegate that meets conflicting guidance follows the unit contract rather than "
        "pausing. Delegate every unit that is independent of the work you keep — this model "
        "delegates less than a fanout expects, and an undelegated independent unit is latency you "
        "chose. Set each unit's effort from its task state: the documented floor for routine "
        "follow-ups, deeper only while a criterion holds unresolved hard reasoning or contradictory "
        "evidence, and a change of effort lands on the next prepared unit rather than on a claimed "
        "mid-conversation switch."
    ),
}


def composition_calibration_for_model(model_id: str) -> str:
    """Return the main-agent composition calibration for the composer's own model.

    Exact-model overrides win, then family from `model_family()`
    (provider-prefixed ids welcome); unknown or blank families get the
    generic block — a composer never goes without discipline just because
    the table has not met its model.
    """
    from .model_routing import model_family

    override = MODEL_COMPOSITION_CALIBRATIONS.get(contract_model_id(str(model_id or "")))
    if override:
        return override
    family = model_family(str(model_id or ""))
    return MAIN_AGENT_COMPOSITION_CALIBRATIONS.get(
        family, MAIN_AGENT_COMPOSITION_CALIBRATIONS["generic"]
    )


# Work-domain skill bundles: when a unit DECLARES a work domain, the
# delegate prompt carries the matching OMH skill's distilled discipline and
# a pointer to the full generated guidance. Deterministic data — the domain
# is explicit unit data, never inferred from text — and executor-neutral:
# the delegate follows the discipline inline; it does not need omh
# installed.
DOMAIN_SKILL_GUIDANCE: Final[dict[str, tuple[str, str]]] = {
    "devops": (
        "omh-build-failure-triage",
        "Classify the failure (build/typecheck/lint/test/CI) before fixing; ship the minimal safe fix "
        "and re-run exactly the failed gate as proof.",
    ),
    "app_development": (
        "omh-frontend",
        "Ship user-visible increments with evidence: after each feature slice, run the app-level check "
        "that proves the screen/flow works, not just unit tests.",
    ),
    "research": (
        "omh-research-brief",
        "Every claim carries its source; mark anything not actually fetched as not observed instead of "
        "guessing, and separate evidence from inference in the summary.",
    ),
    "x_platform_data": (
        "omh-live-info-operator",
        "Treat platform data as time-stamped observations: record when and where each datum was read, "
        "and never extrapolate silently past the observation window.",
    ),
}


def domain_skill_guidance_line(unit: Mapping[str, Any]) -> str:
    """Return the OMH skill-bundle line for a unit's declared work domain, or ''."""
    domain = str(unit.get("domain", "") or "").strip().casefold().replace("-", "_")
    if not domain:
        handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), Mapping) else {}
        route = handoff.get("model_route") if isinstance(handoff.get("model_route"), Mapping) else None
        domain = str(route.get("domain", "") or "") if route else ""
    if not domain:
        return ""
    entry = DOMAIN_SKILL_GUIDANCE.get(domain)
    if entry is None:
        return ""
    label, discipline = entry
    return (
        f"OMH skill bundle ({domain}): follow the `{label}` discipline — {discipline} "
        f"(full guidance ships as skills/{label}/SKILL.md in the oh-my-hermes install)."
    )


def completion_criteria_for_unit(unit: Mapping[str, Any]) -> list[str]:
    """Return the pre-declared, numbered 'done means' criteria for one unit.

    Derived deterministically from the frozen unit contract: boundary
    confinement and committed work are always criteria; the contract's
    integration checks become the unit-specific ones.
    """
    boundary = unit.get("boundary", {}) if isinstance(unit.get("boundary"), Mapping) else {}
    file_scope = ", ".join(str(path) for path in boundary.get("file_scope", []))
    criteria = [f"Every edit stays inside: {file_scope}." if file_scope else "Every edit stays inside the declared file scope."]
    for check in unit.get("integration_checks", []) or []:
        text = str(check).strip()
        if text:
            criteria.append(text[0].upper() + text[1:] if text[0].islower() else text)
    criteria.append("The work is committed on the unit branch; nothing else is merged or pushed.")
    return criteria


def calibration_for_route(model_route: Mapping[str, Any] | None, *, family_only: bool = False) -> str:
    """Return the high-effort calibration block for a routed unit, or ''.

    Selected only when the route's effective reasoning effort is in the high
    tier; an exact-model override on the recorded `selected_model` wins, then
    family comes from the already-recorded `model_family` (falling back to
    generic for unknown/blank families).

    `family_only=True` skips the exact-model override and returns the block
    the model would inherit from its family. That is the measurement arm
    `docs/MODEL-ONBOARDING.md` §8 asks for when an override ships: the
    override is kept only if it measures at least as well as the inherited
    block on the same corpus. Production callers never pass it.
    """
    if not isinstance(model_route, Mapping):
        return ""
    effort = str(model_route.get("selected_reasoning_effort", "") or "").casefold()
    if effort not in HIGH_EFFORT_TIER:
        return ""
    override = None if family_only else MODEL_HIGH_EFFORT_CALIBRATIONS.get(
        contract_model_id(str(model_route.get("selected_model", "") or ""))
    )
    if override:
        return override
    family = str(model_route.get("model_family", "") or "").casefold()
    return HIGH_EFFORT_CALIBRATIONS.get(family, HIGH_EFFORT_CALIBRATIONS["generic"])


def shared_unit_preamble_lines(goal_text: str) -> list[str]:
    """Byte-identical head shared by every sibling unit prompt of one fanout.

    Cached prompt prefixes are exact byte matches on every provider, so the
    lines here depend only on the goal text — never on the unit — and callers
    must place them before any unit-specific byte.
    """
    return [
        f"Overall goal: {goal_text.strip()}",
        GOAL_ECHO_PROTOCOL,
        VERIFICATION_STOP_PROTOCOL,
        FAILURE_KIND_PROTOCOL,
        UNIT_RESULT_RETURN_PROTOCOL,
        STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE,
    ]


def unit_protocol_lines(unit: Mapping[str, Any]) -> list[str]:
    """Return the ordered unit-varying protocol lines appended to a unit prompt.

    The unit-invariant blocks (goal echo, verification stop, failure kind)
    live in `shared_unit_preamble_lines()` so sibling prompts keep a
    byte-identical head; only content that genuinely varies per unit belongs
    here.
    """
    criteria = completion_criteria_for_unit(unit)
    lines = ["Done means, and only means:"]
    lines.extend(f"{index}. {criterion}" for index, criterion in enumerate(criteria, start=1))
    handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), Mapping) else {}
    model_route = handoff.get("model_route") if isinstance(handoff.get("model_route"), Mapping) else None
    # Contract units carry the declared role inside the recorded route, not as
    # a top-level key; accept both so pre-contract unit dicts behave the same.
    role = str(unit.get("role", "") or "") or (str(model_route.get("role", "") or "") if model_route else "")
    if role == "review":
        lines.append(REVIEW_ROLE_PROTOCOL)
    calibration = calibration_for_route(model_route)
    if calibration:
        lines.append(calibration)
    bundle = domain_skill_guidance_line(unit)
    if bundle:
        lines.append(bundle)
    return lines
