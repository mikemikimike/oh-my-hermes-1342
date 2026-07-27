# Fanout: Parallel Split, Dispatch Bridge, and Merge Contract

Audience: operators, wrappers, and coding agents. Normal users describe the
goal to Hermes in chat; these commands are the backend surface.

## Lifecycle

1. **Propose** — Hermes (the LLM) proposes the unit split in chat: unit ids,
   titles, owners, file boundaries, dependencies.
2. **Freeze** — `omh coding fanout prepare --goal <words> --units units.json
   --record` validates the split deterministically (boundary overlaps without
   a `depends_on` edge are hard errors; dependency cycles are hard errors) and
   freezes it as `fanout_contract/v1` under `~/.omh/coding/fanout/<id>/`. The
   goal is stored as a digest only.
3. **Dispatch (opt-in bridge)** — `omh coding fanout dispatch <id>
   --goal-file goal.txt` spawns each spawnable unit's local agent CLI in an
   isolated per-unit worktree, dependency-aware, with bounded concurrency.
4. **Observe** — `omh coding fanout show <id>` joins the frozen contract with
   per-unit run records; unit status is `not_observed` until real evidence
   exists. The board reads a bounded tail (last 20 events) of each unit's run
   history, so repeated checks cost the same context instead of growing with
   the run. `--limit N` changes the tail; `--full` reads everything and is
   expensive for agent context.
   For user-facing briefings, `omh coding fanout brief <id>` emits one
   `fanout_briefing/v1` row per unit (owner, routed model, session ref,
   status, elapsed seconds, token count, last observed summary) joined from
   the contract, the persisted dispatch summary, and a one-event journal
   tail; unknown fields stay the literal string `unknown` rather than being
   inferred. Without an id it lists known fanouts. Session refs and token
   counts are `unknown` until a structured-output dispatch contract lands
   (deliberate deferral — the current templates keep executor stdout as
   opaque bounded text).
5. **Merge (human/agent-gated)** — dispatch never merges. The summary lists
   merge-ready units in the contract's `merge_order`; merging and the final
   integration gate remain the operator's or reviewing agent's job.

## Dispatch bridge semantics

- **Spawnability is data.** `DISPATCH_COMMAND_TEMPLATES` in
  `src/coding/fanout_dispatch.py` maps profiles with a local headless CLI to
  fixed argv templates. Profiles without a template (hermes, omx/omo/omc
  runtimes, generic, unassigned) are reported
  `unsupported_for_local_dispatch` with the unit handoff as a prepared-prompt
  fallback — no profile is privileged.
- **Bridge dispatch is a separate axis from chat prompt-handoff.** Chat
  surfaces keep their prompt-only semantics for prompt-only profiles; the
  bridge is an operator-invoked command on a different surface.
- **Goal integrity.** `--goal-file` must hash to the digest frozen in the
  contract; a diverged goal is refused.
- **Worktrees.** One per unit at `<repo>-fanout-<unit>` on branch
  `agent/<unit>`, all branched from one SHA resolved at dispatch start
  (`--base-ref`, default HEAD). Pre-existing paths or branches are errors,
  never silently reused. Worktrees are never auto-deleted; reconcile with
  `git worktree list`.
- **Evidence.** Each dispatched unit gets a run named by its `run_ref`;
  spawn and exit are recorded as journal observations
  (`worker_dispatch`/`worker_result`, canonicalized to
  `executor_dispatch_observed`/`executor_result_observed`).
- **Dependency bar.** A satisfied dependency means only that the owner agent
  process exited 0. It is not verified, reviewed, or correct work. Failed
  units block their dependents, never their independents.
- **Blocked-by-design cascades.** An `unsupported_for_local_dispatch` or
  `executor_not_ready` dependency also blocks its dependents — dependents must
  never build on an unstarted base. Recovery: complete that unit manually (or
  via its owner's own tooling), record its observed result on the unit's
  `run_ref` run, then re-run `dispatch --unit <dependent>`; completed units
  satisfy dependencies even when not re-selected. Blocked entries carry a
  `blocked_on` list naming the offending units.
- **First-use validation note.** `codex exec` has in-repo precedent. The
  claude template was validated in a live dispatch (2026-07): `acceptEdits`
  alone let the agent create files but blocked the requested `git commit`,
  so the template additionally grants `--allowedTools
  "Bash(git add:*),Bash(git commit:*)"` — exactly those two git verbs,
  nothing broader. Template drift in either CLI surfaces as a clean
  readiness or exit-code failure recorded as observed evidence, and the fix
  is a one-line data edit in `DISPATCH_COMMAND_TEMPLATES`.
- **Model routing.** A unit may declare `model`, `reasoning_effort`, and/or
  `role` (brain, implementation, design_visual, review, docs). Prepare embeds
  the resolved `coding_model_route/v1` in the unit handoff, and dispatch
  turns it into argv fragments (`codex --model … --config
  model_reasoning_effort=…`; `claude --model … --effort …`). No route means
  the argv stays byte-identical to the base template and the executor CLI
  default model applies. Model availability and entitlement are provider
  truth; a routed model that the CLI rejects surfaces as a normal observed
  exit failure. `omh coding model-route` previews routes standalone.
- **Telemetry.** Each dispatched unit records `started_at`, `finished_at`,
  and `duration_seconds`, and the full dispatch summary persists to
  `~/.omh/coding/fanout/<id>/dispatch_summary.json` (latest wins,
  metadata only, skipped on `--dry-run`).
- **Limit signals.** A failed spawn whose bounded output matches a fixed
  limit-shape pattern (rate limit, usage limit, quota, 429, credits) is
  flagged `limit_shaped` with a pattern label; the last such failure per
  executor persists to `~/.omh/runtime/executor-limit-signals.json` and
  surfaces as an advisory in `omh coding executor-readiness` and the
  choose-executor context. Only the boolean and label persist — never the
  matched text, and stderr is matched in memory only.
- **Resume.** Re-running dispatch skips units whose runs already carry an
  observed successful result. `--unit <id>` selects subsets.
- **Never**: auto-merge, default-on execution, network calls by omh itself,
  raw-prompt persistence under `.omh`, Hermes-inline coding (coding-shaped
  work that cannot resolve an executor becomes an explicit user choice, not
  retained Hermes implementation).

## Command reference

```sh
omh coding fanout prepare --goal <words...> --units units.json [--record] [--source discord]
omh coding fanout validate --units units.json
omh coding fanout show <fanout-id> [--limit 20] [--full]
omh coding fanout brief [<fanout-id>]
omh coding fanout dispatch <fanout-id> --goal-file goal.txt \
  [--repo-root .] [--base-ref HEAD] [--concurrency 2] [--timeout 1800] \
  [--unit <id> ...] [--dry-run]
omh coding model-route --executor <profile> [--role <role>] [--model <id>] [--effort <level>]
```

`--units` and `--goal-file` accept `-` for stdin. `--dry-run` resolves
readiness, planned argv, and worktree paths without spawning anything or
creating any runs.
