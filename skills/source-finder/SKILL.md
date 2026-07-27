---
name: omh-source-finder
description: [omh] Hermes Source Finder workflow: prepare typed source candidates and acquisition status before downstream work.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: source-acquisition
    role: researcher
    quality_tier: source-acquisition-gated
---

# Source Finder

This is a Hermes-native `source-finder` workflow skill.

## Why This Exists

`source-finder` exists so Hermes can turn vague source discovery requests into typed candidates, acquisition status, and downstream workflow choice without pretending OMH searched, downloaded, or verified the material.

## Do Not Use When

- The user asks for current citations, fact-finding, or source-backed synthesis; use `web-research`.
- The user supplies a paper/PDF/arXiv/DOI/excerpt and wants explanation; use `paper-learning`.
- The user asks for recurring monitoring, source inbox, or Scout/Analyst/Briefer operations; use `research-department`.
- The user asks to export, convert, render, package, or attach a file; use `materials-package` or `deliverable-package`.
- The user asks for an image card or visual summary; use `img-summary`.

## Examples

Good example:

- Prompt: source-finder find papers, datasets, and GitHub repos for evaluating browser agent benchmarks.
- Expected behavior: Prepare source_finder_plan/v1 with typed candidates, acquisition states, missing observed evidence, and downstream choices.
- Why: The user needs source candidates before deciding whether to learn, research, package, or implement.

Bad example:

- Prompt: source-finder find current citations and summarize what the sources say.
- Expected behavior: Route to `web-research` because the user asks for current evidence and synthesis, not candidate acquisition status.
- Why: Source-finder prepares acquisition lifecycle metadata; web-research owns current evidence synthesis.

## Completion Checklist

- Source kinds, source boundaries, and downstream intent are named.
- Each candidate has a source_candidate/v1 shape and acquisition state.
- Observed states include provenance before being treated as evidence.
- The next downstream workflow is recommended without claiming it ran.
- Search, download, clone, extraction, hash, license, verification, and downstream processing gaps are explicit.

## Recovery Notes

- If the user asks for facts or citations, route to `web-research`.
- If a candidate lacks a link or file reference, keep it candidate_prepared and ask for the next observable source step.
- If the user wants to process a selected source, route to the downstream workflow instead of continuing source acquisition.

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

Use when Hermes should prepare a typed source candidate set across papers, web links, datasets, GitHub repositories, public presentations, docs/specs, or unknown source material before choosing paper-learning, web-research, research-brief, research-department, materials-package, or ultraprocess.

    Strong routing signals: `source-finder`, `source finder`, `source acquisition`, `source intake`, `find papers and datasets`, `find datasets and repos`, `find papers`, `find arxiv link`, `find arxiv paper`, `find datasets`, `find github repos`, `find oss repos`, `find presentations`, `find public slides`, `find docs and specs`, `find source candidates`, `download candidate`, `source candidate`, `acquisition status`, `자료 후보`, `출처 후보`, `arxiv 링크`, `arxiv 링크 찾아`, `논문 데이터셋 찾아`, `깃허브 저장소 찾아`, `공개 발표자료 찾아`, `문서 스펙 찾아`

## Catalog Metadata

Category: `research`
Phase: `source-acquisition`
Hermes role: `researcher`
Quality tier: `source-acquisition-gated`

Quality bar:

- Name source kinds from: paper, web_link, dataset, github_repo, presentation, docs_spec, unknown.
- Record acquisition state from: candidate_prepared, link_observed, download_link_prepared, download_observed, file_hash_recorded, text_extraction_observed, license_checked, verification_observed, downstream_selected.
- Separate candidate preparation, observed link, observed download, file hash, text extraction, license check, verification, and downstream selection.
- Attach observation provenance before treating any acquisition state as evidence.
- Vary search angles across official docs, academic work, implementations, datasets, and criticism until each requested source kind has candidates or another angle change adds nothing new.
- Recommend the next downstream workflow without pretending that downstream work already ran.

Handoff policy:

Keep source acquisition planning in Hermes. Do not claim search, download, clone, extraction, license check, verification, or downstream processing unless a wrapper or user records observed evidence.

Required inputs:

- source target or topic
- desired source kinds
- source boundaries or exclusion criteria
- downstream intent when known

Expected outputs:

- source_finder_plan/v1
- source_candidate/v1
- source_candidate_set/v1
- source_acquisition_status/v1
- downstream workflow recommendation
- not-evidence boundary

Artifact expectations:

- source_finder_plan/v1 under .omh/source-finder when a wrapper or CLI records it

Safety rules:

- Do not claim web search, download, repository clone, file extraction, file hash verification, license verification, or source correctness from a prepared candidate.
- Do not redefine research-department's source_inbox/v1; source-finder owns source_candidate_set/v1 and source_acquisition_status/v1 only.
- Route current citations and source-backed synthesis to `web-research`, supplied-paper explanation to `paper-learning`, recurring monitoring to `research-department`, file export to `materials-package`, and image cards to `img-summary`.

## Runtime Evidence

Preferred harness for this skill: `source-finder`.

```sh
omh runtime record --skill source-finder --harness source-finder --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve workflow intent and stop conditions; verify before claiming completion.
- Use Hermes-native tools, file operations, and subagent/delegation features when available; do not require unavailable runtime tools, role prompts, or overlays. If a capability is unavailable: native subagents -> Hermes delegation when available, otherwise sequential lanes.
- Respect `omh_target_topology/v1`: bind state to the current target/thread, use single-target behavior when `active_agent_count` is one, and name a one-to-many or many-to-one change before treating it as persistent.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
- Shared rail: `oh-my-hermes/references/skill-common-rail.md` has harness discipline, runtime translations, the delegation command, and execution checklist. Load it when applicable; otherwise name an unavailable capability.
