<p align="center">
  <img src="assets/oh-my-hermes-wordmark.png" alt="OH-MY-HERMES" width="100%" style="display:block;max-width:none;height:auto">
</p>

<table align="center">
  <tr>
    <td width="50%" align="center">
      <img src="assets/hermes-desktop.gif" alt="Hermes Desktop running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes Desktop, with oh-my-hermes.</b><br>Pick a workflow; Hermes clarifies before it builds.</sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/hermes-cli.gif" alt="Hermes CLI running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes CLI, with oh-my-hermes.</b><br>The same workflows, in your terminal.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="assets/hermes-messenger.gif" alt="Hermes messenger app running an OMH workflow" width="380" height="266"><br>
      <sub><b>Hermes messenger app, with oh-my-hermes.</b><br>Ask in a thread; the run reports back there.</sub>
    </td>
    <td width="50%" align="center">
      <img src="assets/omh-setup.gif" alt="omh setup installing the OMH workflows" width="380" height="266"><br>
      <sub><b><code>omh setup</code>, one command.</b><br>Installs the workflows and connects them to Hermes.</sub>
    </td>
  </tr>
</table>

# oh-my-hermes

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.ko.md">한국어</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.zh.md">中文</a>
</p>

<p align="center">
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="GitHub" src="https://img.shields.io/badge/github-rlaope%2Foh--my--hermes-181717?logo=github"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img alt="Hermes Agent" src="https://img.shields.io/badge/Hermes%20Agent-NousResearch-6f42c1?logo=github"></a>
  <a href="https://github.com/rlaope/oh-my-hermes"><img alt="OMH stars" src="https://img.shields.io/github/stars/rlaope/oh-my-hermes?style=flat&logo=github"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img alt="Hermes Agent stars" src="https://img.shields.io/github/stars/NousResearch/hermes-agent?style=flat&logo=github"></a>
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
  <strong>oh-my-hermes</strong> (OMH) turns a normal
  <a href="https://github.com/NousResearch/hermes-agent">Hermes Agent</a>
  request into a clear capability, a useful next step, and an honest record
  of what actually happened — strengthening the workflow you already use,
  never replacing Hermes or hiding a coding executor behind it.
  <br><br>
  OMH is the operating layer above Hermes-native skills: it frames the
  problem, picks the workflow and evidence gates, and runs native skills
  as capabilities inside that governed path.
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
>   <img src="assets/omh-terminal-boot-banner.png" alt="OH-MY-HERMES terminal banner listing available tools, grouped skills, OMH specialists, infrastructure, and the model pool on Hermes Agent" width="1080">
> </p>
>
> <p align="center">
>   <img src="assets/hermes-omh-terminal-orchestration.png" alt="Hermes Agent and OH-MY-HERMES working side by side" width="1080">
> </p>
>
> <p align="center">
>   <img src="assets/friren-agent-omh-callout.png" alt="Friren Agent explaining OMH in Art&Engine" width="720">
> </p>

> [!TIP]
> Be with us!
>
> <table>
>   <tr>
>     <td width="124"><a href="https://x.com/rlaope"><img alt="X link" src="https://img.shields.io/badge/Follow-%40rlaope-00CED1?style=flat-square&logo=x&labelColor=black" width="112" /></a></td>
>     <td>Updates for <code>oh-my-hermes</code> are shared on <a href="https://x.com/rlaope">@rlaope</a> on X, alongside release notes and project news.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope"><img alt="GitHub Follow" src="https://img.shields.io/github/followers/rlaope?style=flat-square&logo=github&labelColor=black&color=24292f" width="112" /></a></td>
>     <td>Follow <a href="https://github.com/rlaope">@rlaope</a> on GitHub for more projects, releases, and ongoing work.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://github.com/rlaope/oh-my-hermes/graphs/contributors"><img alt="AI agent collaborators" src="https://img.shields.io/badge/With-AI%20agents-6f42c1?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Built with AI agents <a href="https://github.com/frirenai"><strong>Friren</strong></a> and <a href="https://github.com/sionic-khope"><strong>Killua</strong></a>, collaborators helping ship <code>oh-my-hermes</code>.</td>
>   </tr>
>   <tr>
>     <td width="124"><a href="https://nousresearch.com/"><img alt="Thanks to Nous Research" src="https://img.shields.io/badge/Thanks-Nous%20Research-4B2E83?style=flat-square&labelColor=black" width="112" /></a></td>
>     <td>Thank you to <a href="https://nousresearch.com/">Nous Research</a> for creating Hermes Agent.</td>
>   </tr>
> </table>

<br>

## Quick Start

**Install the local command and managed skills:**

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
omh setup
```

**On Windows (PowerShell 5.1+):**

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
omh setup
```

<br>

**Hermes skill tap path:**

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/omh-routing --yes
```

**or ask Your AI Agent:**

```text
Hey Agent, Install this >> https://github.com/rlaope/oh-my-hermes <<
```

<br>

**Update and health check:**

```sh
omh update
omh doctor
```

Maintenance paths such as reconciling a `--full` install back to core live in
[Installation](docs/INSTALLATION.md#reconciling-an-existing-full-install-back-to-core).

<br>

## Recommended models

OMH ships with these editable category recommendations:

| Category | Recommended models |
| --- | --- |
| `ultrabrain` | GPT-5.6 Sol |
| `deep` | GPT-5.6 Terra |
| `unspecified-high` | Kimi K3, then Claude Opus 5 |
| `unspecified-low` | GLM 5.2, then GLM 5.2 Ultrafast |
| `visual-engineering` | Claude Fable 5, then Kimi K3 |

Ask Hermes to **set up my models** to review or change them. These are editable
preferences, not benchmark results. See
[Guided Model Setup](docs/INSTALLATION.md#guided-model-setup) for the detailed
setup, fallback, provider, and ownership rules.

<br>

## Ultra-Skills

<p align="center">
  <img src="assets/omh-character-badge.png" alt="Oh My Hermes character mark" width="170">
</p>

Twelve `ulw-` workflows. Say the trigger in chat — Hermes routes the
rest. Full catalog: [Workflow Reference](docs/WORKFLOWS.md).

| Workflow&nbsp;command | What it does |
| --- | --- |
| ⚡ `ulw-context` | Aligns reviewed project terms, captures confirmed candidates, and interviews the next decision frontier without giving terminology routing authority. |
| ⚡ `ulw-interview` | Asks one question at a time until it knows exactly what you want. |
| ⚡ `ulw-research` | Digs through real code and the live web, keeps sources, and verifies anything doubtful. |
| ⚡ `ulw-plan` | Builds a reviewed plan: options compared, risks named, done-criteria agreed. |
| ⚡ `ulw-work` | Runs an accepted plan in parallel lanes that never touch the same file. |
| ⚡ `ulw-ralph` | One owner grinds a task to done — build, verify, review, repeat. |
| ⚡ `ulw-team` | Multiple workers, one task list, no collisions. |
| ⚡ `ulw-loop` | Cycles plan → build → review until the goal actually passes. |
| ⚡ `ulw-goal` | Long-running goals with checkpoints — survives lost context, resumes where it stopped. |
| ⚡ `ulw-process` | Takes one task all the way from research to an open PR. |
| ⚡ `ulw-qa` | Attacks the build with hostile scenarios and fixes what breaks. |
| ⚡ `ulw-perf` | Measures where it is actually slow or expensive, then fixes one hot path at a time. |

<br>

## What OMH Adds

<p align="center">
  <img src="assets/hermes-agent-mom-aura.png" alt="Hermes-Agent mixture-of-models orchestration illustration" width="560">
</p>

<p align="center"><strong>Mixture of Models</strong></p>

OMH packages **105 installable workflow skills** behind six human-readable
capability families: 12 workflow engines use `ulw-` labels, including
`ulw-context`, and the remaining 93 skills use `omh-` labels. The family is the
front door; exact skill names remain available when a wrapper or operator needs
precise control.

The full generated catalog, triggers, harnesses, and evidence rules live in
[Workflow Reference](docs/WORKFLOWS.md).

**Highlights**

| Capability | Try it with | What it does |
| --- | --- | --- |
| 🧭 **Clarify and plan** | `omh-plan` · `omh-decide` · `omh-meeting-brief` | Turns an ambiguous request into explicit goals, constraints, tradeoffs, acceptance criteria, and a plan that can be handed off. |
| ⚡ **Build with leverage** | `omh-idea-to-deploy` · `omh-cto-loop` · `omh-running-work-board` | Scales from fast parallel work to durable multi-step execution while keeping ownership, checkpoints, and verification visible. |
| 🔬 **Research and learn** | `omh-best-practice-research` · `omh-research-brief` · `omh-paper-learning` | Finds and synthesizes source-backed evidence with freshness, source-quality, and unresolved-uncertainty boundaries. |
| 🛠️ **Code and ship safely** | `omh-code-review` · `omh-build-failure-triage` · `omh-verification-gate` | Prepares executor-neutral coding work, then makes review, QA, CI, and merge claims depend on observed evidence. |
| 🎨 **Create polished deliverables** | `omh-design-quality-gate` · `omh-materials-package` · `omh-deliverable-package` · `omh-image-cards` | Shapes websites, visuals, reports, decks, documents, PDFs, posters, and packages around content, taste, accessibility, and render-quality gates. |
| 🧠 **Remember and operate** | `omh-memory-new` · `omh-memory-sync` · `omh-ops-observability-card` · `omh-doctor` | Keeps project memory review-first, surfaces operational readiness, and gives the next repair action without inventing provider or system state. |
| 🔌 **Connect without hiding boundaries** | `omh-toolbelt-readiness` · `omh-external-connector-readiness` · `omh-agent-board` | Checks whether a needed tool, connector, or agent surface is really available before work depends on it, and keeps host load, tool use, and external-provider access separately observable. |

<br>

## Built For Real Work

<p align="center">
  <img src="assets/built-for-real-work-orchestration-ai.png" alt="OMH orchestrating coding agents, creative tools, and AI" width="900">
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
Code, Hermes, the OMO runtime (via its `pi`, `senpi`, or `opencode` host CLI),
and generic executors remain explicit owners rather than hidden defaults.

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

**💬 Project-aware clarification, without automatic routing.** In
natural-language Hermes chat, reviewed terminology from the current repository
can improve one ambiguous wrapper question. OMH derives the current project
internally; users do not provide a domain scope, and the context is not
persisted. The clarification does not change the selected route or mean that
planning, execution, review, CI, or merge work happened.

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

<p align="center">
  <img src="assets/omh-goal-post.png" alt="Post from @rlaope: the goal of oh-my-hermes is a single entry point for Hermes Agent that eliminates plugin fatigue and turns anyone into a power user" width="680">
</p>

## Evidence Before Claims

OMH never reports that work happened unless it watched it happen. Every status
you see has two parts: the stage, and how sure OMH is about it.

| You see | It means |
| --- | --- |
| `Plan · not run` | A prompt or plan is ready. **Nothing has run yet.** |
| `Code · running` | An executor is running now, and OMH is watching it. |
| `Code · reported done` | The executor said it finished. Nobody checked the result. |
| `Test · verified` | A test, review, or CI gate actually passed. |

The distinction that matters is the second row from the bottom: an executor
saying it is done is not the same as anything having been checked, and most
tools spell both "complete". Capability impact is reported across separate
dimensions rather than collapsed into one marketing score. See
[Capability Impact](docs/CAPABILITY_IMPACT.md).

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
