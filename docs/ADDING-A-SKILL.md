# Adding a New Installable Skill

Checklist for adding a skill to the OMH catalog. Every surface below is
enforced by a test; skipping one fails CI with an actionable message naming
the file and structure to edit.

## 1. Define the skill (single registration point)

- Add the `SkillDefinition` to `src/skills/catalog.py`.
- Set `capability_family` **only** when the skill's user-facing family differs
  from its awareness-lane default (rare — 5 of 88 skills today). Leave it
  empty otherwise; the lane default governs.
- If the skill needs a recommendation policy, add its `_SKILL_POLICIES` entry
  in `src/routing/recommend.py`.
- The `SkillDefinition.name` you pick is the canonical identifier (tap
  directory, install manifest, routing key, CLI arguments); the generated
  frontmatter `name` is a separate rendered display identifier that
  `omh_skill_display_name()` prefixes with `omh-` for the host status line, so
  never treat the two as interchangeable.
- The display form also reaches messenger-visible prose: skill-picker bodies,
  capability-family lines, route-hint copy, and `workflow_explanation` copy call
  `display_workflow_name()` in `src/wrapper/contract.py` at render time. Never
  store the `omh-` form in catalog data, routing fixtures, or state, and keep
  `./<name>` invocation strings, `--skill <name>` recipes, and
  `definition.triggers` canonical. Routing accepts the display form back through
  `canonical_display_mentions()` in `src/routing/display_names.py`, so a new
  skill gets echo-back for free; `tests/test_display_names.py` locks all three.

## 2. Hand-authored surfaces (curated order and UX copy)

These cannot be derived from the catalog; each has a gate that fails with
paste-ready guidance:

| Surface | File / structure | Gate |
| --- | --- | --- |
| Awareness lane membership | `awareness_primer_payload()` lane `skills` lists in `src/plugin_bundle/omh/awareness.py` | `tests/test_capabilities.py` (lane coverage) |
| Workflow context card lane | `_WORKFLOW_CONTEXT_CARD_BY_WORKFLOW` in the same file | `tests/test_capabilities.py` (context-card coverage) |
| Visible/ack wrapper actions | `VISIBLE_ACTIONS` + `_ACK_PRIMARY_ACTIONS_BY_NEXT_ACTION` in `src/wrapper/contract.py` | `tests/test_wrapper_contract.py` (visible-ack) |
| Next-action label | `NEXT_ACTION_LABELS` in `src/routing/action_copy.py` | `tests/test_wrapper_contract.py` (curated-label gate) |
| Dedicated non-ack chat card | a `*_CHAT_CARDS` entry or bespoke renderer in `src/wrapper/contract.py` | intervention harness + coverage-case gate |
| Coverage case | `ChatCardCoverageCase` in `src/quality/chat_card_coverage.py` or `RoutingInterventionCase` in `src/quality/routing_precision.py` | `tests/test_wrapper_contract.py` (coverage-case gate) |

The curated-label and coverage-case gates carry frozen legacy allowlists; do
not extend the allowlists for a new skill — register the skill instead.

## 3. Exact-count fixtures (contracts, updated in the same commit)

Adding a routing/intervention case moves exact-count assertions in
`tests/test_routing_precision.py`, `tests/test_cli.py`,
`tests/test_hermes_ux_quality.py`, and `tests/test_release_smoke.py`. Grep
those four for the old count.

## 4. Regenerate every generated artifact family

```sh
# skills/*/SKILL.md + references (short template-write loop; see CLAUDE.md)
uv run python -m omh.cli docs workflows --output docs/WORKFLOWS.md
uv run python -m omh.cli docs roles --output docs/ROLES.md
uv run python -m omh.cli docs capability-families
uv run python -m omh.cli cases demo --all --json > examples/use-cases/g1-g10-demo-cards.json
```

## 5. Verify

Every added skill grows the always-loaded prompt body of a `full` install.
Check what it cost, and keep shared policy in
`skills/omh-routing/references/skill-common-rail.md` instead of a new
repeated section in `workflow_skill`:

```sh
uv run python -m omh.cli docs skill-context-cost
```

```sh
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
uv run python -m omh.cli docs roles --check
uv run python -m omh.cli docs capability-families --check
git diff --check
PYTHONPATH=tests uv run python -m unittest discover -s tests
```
