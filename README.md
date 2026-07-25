<p align="center">
  <img src="assets/oh-my-hermes-wordmark.png" alt="OH-MY-HERMES" width="100%" style="display:block;max-width:none;height:auto">
</p>

# oh-my-hermes

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.ko.md">한국어</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.zh.md">中文</a>
</p>

<p align="center">
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="GitHub" src="https://img.shields.io/badge/github-rlaope%2Foh--my--hermes-181717?logo=github"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <a href="https://github.com/NousResearch/hermes-agent"><img alt="Hermes Agent" src="https://img.shields.io/badge/Hermes%20Agent-NousResearch-6f42c1?logo=github"></a>
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="OMH stars" src="https://img.shields.io/github/stars/rlaope/oh-my-hermes?style=flat&logo=github"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img alt="Hermes Agent stars" src="https://img.shields.io/github/stars/NousResearch/hermes-agent?style=flat&logo=github"></a>
  <a href="https://github.com/rlaope/oh-my-hermes/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/rlaope/oh-my-hermes/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/rlaope/oh-my-hermes/actions/workflows/pages.yml"><img alt="GitHub Pages" src="https://github.com/rlaope/oh-my-hermes/actions/workflows/pages.yml/badge.svg"></a>
  <a href="https://github.com/rlaope/oh-my-hermes/issues"><img alt="GitHub issues" src="https://img.shields.io/github/issues/rlaope/oh-my-hermes?logo=github"></a>
  <img alt="Status" src="https://img.shields.io/badge/status-1.0.2%20stable-blue">
</p>

<p align="center">
  <img src="assets/hermes-agent-hero.png" alt="Oh My Hermes" width="720">
</p>

<p align="center">
  <strong>Install once. Keep Hermes. Add a stronger operating layer.</strong>
  <br>
  <em>Planning, research, creation, coding handoffs, operations, and project memory with explicit evidence boundaries.</em>
</p>

<p align="center">
  <img src="assets/oh-my-hermes-agent-poster.png" alt="Oh My Hermes Agent poster" width="720">
</p>

<p align="center">
  <strong>oh-my-hermes</strong> (OMH) turns a normal request in
  <a href="https://github.com/NousResearch/hermes-agent">Hermes Agent</a> into
  a clear capability, a useful next step, and an honest statement of what has
  or has not happened. It strengthens the Hermes workflow you already use
  instead of replacing Hermes or hiding a coding executor behind it.
  <br><br>
  OMH is the operating layer above individual Hermes-native skills: it frames
  the problem, selects the workflow and evidence gates, and uses native skills
  as capabilities within that governed path rather than as competing top-level
  owners.
</p>

[Website](https://rlaope.github.io/oh-my-hermes/) ·
[Documentation](docs/README.md) ·
[Installation](docs/INSTALLATION.md) ·
[Capabilities](docs/CAPABILITIES.md) ·
[Capability Impact](docs/CAPABILITY_IMPACT.md) ·
[Agent Install](INSTALL_FOR_AGENTS.md) ·
[GitHub Pages site](site/index.html)

> [!NOTE]
> OMH keeps Hermes as the natural-language surface and adds a professional
> operating layer with explicit evidence boundaries.
>
> <p align="center">
>   <img src="assets/hermes-omh-terminal-orchestration.png" alt="Hermes Agent and OH-MY-HERMES working side by side" width="1080">
> </p>
>
> <p align="center">
>   <img src="assets/friren-agent-omh-callout.png" alt="Friren Agent explaining OMH in Art&Engine" width="720">
> </p>

<br>

## Quick Start

**Install the local command and managed skills:**

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

<br>

**Hermes skill tap path:**

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes
```

<br>

**Then ask Hermes normally:**

```text
I want to safely add a feature to this repo.
```

<br>

**or ask Your AI Agent:**

```text
Hey Agent, Install this >> https://github.com/rlaope/oh-my-hermes <<
```

<br>

## What OMH Adds

OMH packages **88 installable workflow skills** behind six human-readable
capability families. The family is the front door; exact skill names remain
available when a wrapper or operator needs precise control.

| Capability family | What it helps Hermes do |
| --- | --- |
| **Plan and decide** | Clarify ambiguous goals, prepare reviewed plans, and run durable goal loops. |
| **Learn and gather** | Find sources, explain papers, inspect data, and prepare source-backed briefs. |
| **Create materials and visuals** | Prepare websites, visual QA, images, decks, reports, documents, and deliverable packages with format-specific quality gates. |
| **Delegate coding and ship** | Prepare scoped, skill-aware coding handoffs for Codex, Claude Code, Hermes runtime, or another selected executor. |
| **Operate and observe** | Review setup, service quality, releases, incidents, automation, tools, sessions, and workflow learning. |
| **Retain knowledge** | Build reviewed project memory and connect external knowledge systems through provider-neutral boundaries. |

The full generated catalog, triggers, harnesses, and evidence rules live in
[Workflow Reference](docs/WORKFLOWS.md).

**Highlights**

| Capability | Try it with | What it does |
| --- | --- | --- |
| 🧭 **Clarify and plan** | `$deep-interview` · `$ralplan` · `$strategy-brief` | Turns an ambiguous request into explicit goals, constraints, tradeoffs, acceptance criteria, and a plan that can be handed off. |
| ⚡ **Build with leverage** | `$ultrawork` · `$ultragoal` · `$team` · `$loop` | Scales from fast parallel work to durable multi-step execution while keeping ownership, checkpoints, and verification visible. |
| 🔬 **Research and learn** | `$best-practice-research` · `$web-research` · `$research-brief` | Finds and synthesizes source-backed evidence with freshness, source-quality, and unresolved-uncertainty boundaries. |
| 🛠️ **Code and ship safely** | `$request-to-handoff` · `$code-review` · `$ultraqa` | Prepares executor-neutral coding work, then makes review, QA, CI, and merge claims depend on observed evidence. |
| 🎨 **Create polished deliverables** | `$design-quality-gate` · `$materials-package` · `$deliverable-package` · `$img-summary` | Shapes websites, visuals, reports, decks, documents, PDFs, posters, and packages around content, taste, accessibility, and render-quality gates. |
| 🧠 **Remember and operate** | `$memory` · `$ops-observability-card` · `$doctor` | Keeps project memory review-first, surfaces operational readiness, and gives the next repair action without inventing provider or system state. |
| 🔌 **Connect without hiding boundaries** | `omh mcp` · `omh plugin` · `$agent-board` | Exposes local metadata-only contracts for Hermes and compatible hosts while keeping host load, tool use, and external-provider access separately observable. |

<br>

## Built For Real Work

<p align="center">
  <img src="assets/built-for-real-work-orchestration.png" alt="OMH orchestrating coding agents and creative tools" width="900">
</p>

> **OMH (Oh-My-Hermes)** — Anyone can use hermes-agent professionally.<br>
> The powerful intelligence harness for your AI Agent.

**🧭 A stronger router, not a command dump.** English, Korean, Japanese,
Chinese, Spanish, French, German, and Hindi operator requests can be
classified locally without a translation API. OMH returns the recommended
family, skill, owner, next action, and what is still not evidence.

**🤝 Better coding handoffs.** OMH can include repository constraints, accepted
scope, worktree and session-isolation guidance, locally available skills,
acceptance criteria, review expectations, and verification gates. Codex, Claude
Code, Hermes, and generic executors remain explicit owners rather than hidden
defaults.

**🎨 Quality-aware creation.** Frontend, accessibility, image, report, slide,
document, spreadsheet, PDF, poster, and shareable-package requests are routed
through specialized production and QA guidance. A prepared brief is never
presented as a generated or visually verified artifact.

**🔍 Evidence before claims.** OMH separates prepared intent, observed runtime
events, and verified results. A handoff can be ready without claiming that an
executor ran, a review passed, CI succeeded, a deployment completed, or a PR
was merged.

**🧠 Review-first project memory.** OMH keeps project-memory candidates separate
from approved records and recalls only reviewed, prepared context into future
handoffs. It does not pretend to read or mutate opaque Hermes memory.

**🔌 Provider-neutral operations.** Metric, wiki, browser, image, video, and
connector systems sit behind explicit external-provider contracts. OMH can
validate and analyze supplied data without pretending that a provider was
connected or called.

**🏛️ Hermes-native, executor-neutral architecture.** Hermes remains the chat,
clarification, planning, research, and status surface. The selected executor
owns implementation, while OMH supplies the local contracts, routing, memory,
quality gates, and evidence boundaries around that work.

**🧱 Local-first control plane.** Core OMH routing, catalogs, manifests, and
claim rules are deterministic local surfaces. External calls and provider
access stay explicit integrations rather than hidden behavior inside the core.

<br>

## Evidence Before Claims

OMH separates useful preparation from observed results:

| State | Meaning |
| --- | --- |
| Prepared | A route, plan, prompt, artifact contract, or handoff is ready. |
| Observed | A wrapper or runtime recorded that an action or result occurred. |
| Verified | A matching test, review, served-surface check, or other required gate passed. |

`prepared_not_observed` is not execution, provider access, artifact generation,
review, CI, deployment, merge readiness, or a merge. Capability impact is
reported across separate dimensions rather than collapsed into one marketing
score. See [Capability Impact](docs/CAPABILITY_IMPACT.md).

<br>

## Documentation

- [Documentation map](docs/README.md)
- [Installation and updates](docs/INSTALLATION.md)
- [Product direction and boundaries](docs/DIRECTION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Capability manifests](docs/CAPABILITIES.md)
- [Workflow reference](docs/WORKFLOWS.md)
- [Roles](docs/ROLES.md)
- [Application cases](docs/APPLICATION_CASES.md)
- [Release and development](docs/RELEASE.md)

<br>

## Development

For a source checkout:

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
git diff --check
```

OMH is developed in the open as part of
[Team Art & Engineering](https://rlaope.github.io/artengine-lab/). Follow
[@rlaope](https://github.com/rlaope) for project updates.
