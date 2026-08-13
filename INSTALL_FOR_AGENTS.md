# OMH Agent Install Protocol

Canonical install reference for AI agents and operators. Execute top to bottom,
then report the observed result. Normal users should use Hermes chat and
installed skills; `omh` is bootstrap, repair, doctor, and backend verifier
infrastructure.

## Prerequisites

```sh
command -v python3 >/dev/null || echo "MISSING: python3 is required"
command -v git >/dev/null || echo "MISSING: git is required for source installs"
command -v hermes >/dev/null || echo "NOTE: Hermes Agent command not found in PATH"
```

On native Windows, run the PowerShell equivalent instead:

```powershell
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { "MISSING: Python 3.11+ is required" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { "MISSING: git is required for source installs" }
if (-not (Get-Command hermes -ErrorAction SilentlyContinue)) { "NOTE: Hermes Agent command not found in PATH" }
```

If Hermes is not available, continue only when the target environment uses a
hosted wrapper that manages Hermes separately. Do not claim Hermes-visible
readiness until the target Hermes runtime or wrapper has been checked.

## Step 1: Install OMH

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
```

On native Windows:

```powershell
irm https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1 | iex
```

Both installers accept the same `OMH_*` environment contract and leave the same
local result. Report which one was used, because the exposed command differs: a
symlink at `~/.local/bin/omh` on POSIX, an `omh.cmd` shim in
`%LOCALAPPDATA%\omh\bin` on Windows.

The installer prepares the local `omh` command only. It does not run setup,
register Hermes skill directories, install profile packs, or run doctor by
default. Run setup explicitly because it is the repairable, repeatable step:

```sh
omh setup
```

If `command -v omh` is still empty after install, use the absolute command path
printed by the installer or add that directory to `PATH`, then continue with
doctor. Treat this as a command availability warning, not proof that Hermes
registration failed.

Expected local result:

- generated skills are installed under `~/.omh/skills`;
- Hermes config includes that directory in `skills.external_dirs`;
- the managed plugin bridge is installed under `~/.hermes/plugins/omh`;
- normal users can talk to Hermes instead of running backend commands.

## Step 2: Verify

```sh
omh doctor
```

Report:

- `ok`;
- top-level `recommended_next_action`;
- whether the `command_path` check found `omh` on PATH or only an absolute path
  is available;
- any check with `severity: blocking`;
- any check with `severity: warning`;
- whether the target Hermes runtime still needs restart/reload.

Install success means a Hermes-usable skill path is configured and doctor has no
blocking checks. It does not mean Hermes has already reloaded the skills,
loaded the plugin bridge, executed code, reviewed a PR, passed CI, or merged.

For release-candidate verification, add the Hermes CLI smoke. Plan mode is safe
and non-mutating:

```sh
omh release hermes-smoke
```

When the operator explicitly wants to prove the current Hermes profile can
install, list, check, and inspect OMH, run one live smoke:

```sh
omh release hermes-smoke --live --install-path tap --target-confirmed
```

Use `--install-path setup` instead when the release must prove the `omh setup`
bootstrap path. Passing either live smoke still does not prove a later Hermes
chat session selected OMH unless that chat response is observed separately.

## Optional Hermes Skill Tap

If the target Hermes environment supports skill taps, this is the native front
door:

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes
```

Install direct workflow skills only when the user wants them exposed as explicit
Hermes skill choices:

```sh
hermes skills install deep-interview
hermes skills install ralplan
hermes skills install research
hermes skills install feedback-triage
hermes skills install ops-review
hermes skills install code-review
```

The tap path and `omh setup` path should converge on the same user experience:
Hermes can see OMH guidance and the user talks to Hermes.

## Plugin Bridge And Profile Packs

`omh setup` installs `~/.hermes/plugins/omh` and lets doctor verify local
manifest, import, and register smoke checks. It does not patch Hermes core,
implement Discord or Slack transports, start a network service, or prove Hermes
loaded the plugin. Runtime plugin use must be observed separately.

Profile packs are setup choices, not curl-download choices. Add them when setup
runs:

```sh
omh setup --profile-pack cto-loop
```

## Optional Guided Model Configuration

Run this only when the user asks to configure models. Model configuration is
not required for OMH installation, and a missing shipped recommendation must
not turn install or doctor into a failure.

Use this exact agent-facing prompt:

```text
Inspect my bounded local model metadata and help me configure OMH model routing. Ask me to confirm which models are still active. Keep Hermes-native aliases separate from Maestro external handoffs, show the exact alias preview and config digest before any write, and apply only after I approve it. Keep recommendation categories editable; if Kimi, GPT, or Claude is missing, continue with a confirmed compatible model such as Qwen or Gemini. Explain Grok's editorial X-platform affinity without presenting it as measured performance. Treat CCAPI and Apitopia as user-declared editorial provider preferences only. Do not read, copy, request, or echo credentials.
```

Agent/maintainer procedure:

1. Preview bounded local observations and confirm active models with the user.
   A session-history observation is `observed_before`, not active confirmation.
2. Build a Hermes-native alias preview without applying it. Repeat
   `--confirm-model` and `--model-alias` as needed:

   ```sh
   omh setup --model-setup \
     --confirm-model google/gemini-3.1-pro \
     --model-alias main=google/gemini-3.1-pro \
     --no-interactive --json
   ```

3. Show the user `steps.model_activation.preview.changes` and
   `config_digest`. After explicit approval, repeat the command with
   `--apply-model-config --model-config-digest <preview-digest>`. A collision
   requires a separate explicit `--allow-model-alias-collision` choice.
4. Verify `steps.model_activation.verification.status == "verified"`, then run
   the offline agent/maintainer report:

   ```sh
   omh coding model-routing status --json
   ```

Hermes aliases are written through Hermes' native `config` commands. Maestro is
an OMH-local coordinator for prepared external Codex, Claude Code, OMO, OMC,
OMX, and generic handoffs; it is not an executor and does not own Hermes-native
work. `pi` and `senpi` are OMO runtime-family hosts. Recommendations are
editable editorial metadata, not provider availability or benchmark evidence.
Qwen, Gemini, or another confirmed compatible model can be selected when a
shipped recommendation is absent. Grok's `x_platform_data` position is an
editable X-platform affinity only. CCAPI and Apitopia are never probed; their
entries remain user-declared provider-family preferences, and credentials stay
in their native owner.

## First Hermes Prompt

After install and any required Hermes restart/reload, try:

```text
Use OMH request-to-handoff for: I want to safely add a feature to this repo.
```

Expected behavior:

- Hermes explains why `request-to-handoff` is the right first workflow;
- Hermes names the responsible role such as `planner` or
  `handoff-guide`;
- Hermes gives the next action, such as clarify, accept plan, choose executor,
  or show status;
- Hermes keeps prepared handoff separate from observed execution evidence.

## Failure Report Template

```text
OMH install result:
- install command:
- omh setup output summary:
- omh doctor ok:
- recommended_next_action:
- blocking checks:
- warning checks:
- Hermes restart/reload performed:
- first Hermes prompt tried:
- observed Hermes response:
```

Do not ask the user for Discord, Slack, GitHub, Vercel, Supabase, or deploy
credentials for the normal OMH install path.
