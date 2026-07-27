---
name: omh-autoresearch-goal
description: [omh] Hermes adaptation for durable research-goal execution.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: durable-research
    role: researcher
    quality_tier: validator-gated
---

# Autoresearch Goal

This is a Hermes-native `autoresearch-goal` workflow skill.

## Why This Exists

`autoresearch-goal` exists to keep `research` work explicit, evidence-backed, and inside the Hermes/executor boundary instead of relying on ad hoc chat narration.

## Do Not Use When

- The request is casual chat, a status-only acknowledgement, or another workflow has stronger routing evidence.
- The user needs implementation, review, CI, merge, or external publishing evidence that has not been delegated or observed.

## Examples

Good example:

- Prompt: autoresearch-goal: keep researching AI agent memory practices until the evidence gaps are closed or logged.
- Expected behavior: Run a durable research loop with critic checks, source gaps, and a stop or checkpoint condition.
- Why: The request is research that needs persistence and review, not a one-shot brief.

Bad example:

- Prompt: autoresearch-goal: treat casual chat or unaccepted work as if this workflow already produced verified results.
- Expected behavior: Ask a clarification question or route to a narrower workflow instead of forcing `autoresearch-goal`.
- Why: The request lacks the required inputs or would overclaim work that Hermes did not observe.

## Completion Checklist

- The research question, source boundaries, recency assumptions, and confidence level are named.
- Observed sources, inference, synthesis, and unresolved retrieval gaps are separated.
- Follow-up planning or handoff uses the research summary without calling it execution evidence.

## Recovery Notes

- If sources cannot be accessed, state the retrieval gap and use only observed local context.
- If evidence is thin or one-sided, lower confidence and ask for a narrower source boundary.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Research and company ops** (`source-finder`, `web-research`, `best-practice-research`, `autoresearch-goal`, `research-brief`, `strategy-brief`, `feedback-triage`, `research-department`, `+6 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/a11y/visual-qa; paper->paper-learning; content->content-operator; media->media-input-operator; file->materials-package; search->web-research; live->live-info-operator; audit->workspace/production/security; failures->build-failure; verify->verification-gate; code->codegraph/onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing/cards/handoffs/artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use for validator-gated research that needs durable artifacts.

    Strong routing signals: `autoresearch-goal`, `research goal`, `durable research`, `critic research`

## Catalog Metadata

Category: `research`
Phase: `durable-research`
Hermes role: `researcher`
Quality tier: `validator-gated`

Quality bar:

- Define validator criteria before gathering evidence.
- Run each cycle as evidence-gap closure: name the open gaps the cycle targets, then stop at the validator criteria or the declared iteration budget, whichever comes first.
- Keep durable research artifacts separate from coding execution evidence.
- Stop with next questions or a source-backed synthesis when validation is incomplete.

Handoff policy:

Keep durable research in Hermes-managed artifacts; do not convert to executor handoff unless the research produces an accepted coding task.

Required inputs:

- research objective
- validator criteria
- source boundaries

Expected outputs:

- research artifact
- validator result
- next questions

Artifact expectations:

- durable research ledger or checklist

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Preferred harness for this skill: `research`.

```sh
omh runtime record --skill autoresearch-goal --harness research --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve workflow intent and stop conditions; verify before claiming completion.
- Use Hermes-native tools, file operations, and subagent/delegation features when available; do not require unavailable runtime tools, role prompts, or overlays. If a capability is unavailable: native subagents -> Hermes delegation when available, otherwise sequential lanes.
- Respect `omh_target_topology/v1`: bind state to the current target/thread, use single-target behavior when `active_agent_count` is one, and name a one-to-many or many-to-one change before treating it as persistent.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
- Shared rail: `oh-my-hermes/references/skill-common-rail.md` has harness discipline, runtime translations, the delegation command, and execution checklist. Load it when applicable; otherwise name an unavailable capability.
