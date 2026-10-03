---
paths:
  - "Infrastructure/scripts/**"
  - "Makefile"
---

# Maintenance Rules

Use these rules for periodic repository hygiene checks.

## Purpose

1. Keep canonical and generated AI files synchronized.
2. Catch broken internal references before they block users.
3. Surface stale dependencies and stale dataset references early.

## Severity Definitions

| Severity | Meaning |
|---|---|
| HIGH | Immediate workflow risk or guaranteed breakage |
| MEDIUM | Staleness or drift that can degrade quality soon |
| LOW | Cleanup/improvement that is not currently blocking |
| INFO | Observations requiring monitoring or human context |

## Required Check Families

The runner's registry (`python3 Infrastructure/scripts/run_maintenance_checks.py --list`) lists
every check that `make maintenance-check` runs; the families below give each its severity and
rationale.

### MT-1 Generated Copy Drift

- Run `make brain-check`.
- HIGH if drift exists between `Infrastructure/` and generated copies in `.claude/`, `.codex/`,
  or `.agents/`,
  or if `.brain-manifest` does not list exactly the files `brain.py sync` generates.
- A hand-edited generated file is drift. `make brain-sync` overwrites it, so move a lasting
  change into its canonical source first.

### MT-2 Internal Path Integrity

- Run `python3 Infrastructure/scripts/check_internal_path_references.py`.
- Four kinds of internal path are optional: `Infrastructure/.template-identity`, because
  `make template-reset` intentionally removes it in derived research projects; anything
  under the gitignored `Infrastructure/local/`, because operator-local notes exist only on
  the operator's machine (`AGENTS.md`, Change Control); `data/docs/` and
  `data/docs/dataset-registry.yaml`, the project dataset overlay the first documentation pass
  creates; and, only once the template marker is gone, the worked example's data and drafts
  (`data/example/` and everything under it, `drafts/example_note.md`,
  `drafts/example_brief.qmd`), which a project deletes when it replaces the example
  (`README.md`, Getting started, step 5). In the template they stay required. A fifth kind
  applies only in a repository `port_template.py` brought the template into with its own
  layout kept (`.eig-port` says `project_lane: legacy`): every path under `code/`, `data/`,
  `drafts/`, and `output/`, and the root `README.md`, because that project's code and data live
  where they always did and it may never have had a README.
- HIGH for missing referenced files that break documented workflows.
- LOW for cosmetic/path wording issues that do not affect execution.
- The same script fails a non-Markdown file (under `Infrastructure/`, an adapter tree,
  `.github/`, or the `Makefile`) that cites a dated plan, spec, or session log, because
  `make template-reset` deletes it; cite the owning `Infrastructure/` doc or `CHANGELOG.md`.

### MT-3 Literature Catalog Integrity

- Run `make literature-check`.
- HIGH for schema or missing-path failures, and when `knowledge-store-tests` fails: the
  catalog, registry, or staleness validator no longer rejects a planted bad entry.

### MT-4 Catalog Staleness

- Run `python3 Infrastructure/scripts/check_catalog_staleness.py`.
- MEDIUM for non-archived entries that have not been verified recently.
- INFO when freshness cannot be determined from available metadata.

### MT-5 Dependency Freshness Signals

- Run applicable checks based on stack files present.
- MEDIUM when critical dependencies are outdated or unsupported.
- INFO when automated freshness checks are unavailable in the current environment.

### MT-6 Dataset Registry Integrity and Coverage

- Run `python3 Infrastructure/scripts/validate_dataset_registry.py`.
- HIGH for schema, enum, or provenance violations (for example a `verified` entry without
  `sources`, `verified_by`, and `verified_on`, or a project variable missing its `vintage` or `source`).
- When a project has analysis code, also check coverage:
  - MEDIUM when a recognized public dataset is loaded in code but absent from `Infrastructure/references/datasets/registry.yaml` and the project overlay `data/docs/dataset-registry.yaml`. Recommend the `document-data` workflow.
  - MEDIUM when a documented variable's `vintage` is older than the dataset vintage the code uses.
  - LOW for registry variables not referenced anywhere in code (possible dead documentation).

### MT-7 Adapter Structural Parity

- Run `python3 Infrastructure/scripts/brain.py check --only drift` (the `brain-check` step of
  `make maintenance-check`).
- HIGH when a canonical agent, workflow, skill, or main-session rule has no generated adapter
  file, or when `.brain-manifest` still lists a generated file whose source was deleted
  (manifest drift; `make brain-sync` deletes the file and updates the manifest).
- HIGH when a retired Codex surface (`.codex/{commands,templates,skills}/`) exists. Codex
  discovers skills at `.agents/skills/`, so a second tree registers every skill name twice.
  Sync deletes only manifest paths, so remove a retired surface by hand.
- INFO for unowned paths: a file in `.claude/`, `.codex/`, or `.agents/` that the manifest
  does not list, such as a project's own agent or skill or a personal settings.local.json.
  Sync never touches it and the guard hook does not block it; confirm each one is intended.
- Rationale: the manifest records ownership, so the check compares the full expected file
  set with the live files and the manifest. A file left behind after its source was deleted
  fails as surely as a content change, while a file the project added itself is not an error.

### MT-8 Adapter Metadata Coverage

- Run `python3 Infrastructure/scripts/brain.py check --only lints` (the `brain-lints` step).
- HIGH when a canonical agent, workflow, dedicated skill, or rule has no YAML frontmatter, or its
  frontmatter does not parse, lacks a required key, has an unknown key or an invalid value,
  or names a different entity than its file; or when a generated Codex TOML or frontmatter
  block does not parse or does not round-trip the canonical frontmatter.
- Rationale: there are no defaults. `brain.py sync` fails on a missing required key, so an
  uncovered entity is a hard error rather than generic metadata. An agent's Codex settings
  sit in its `codex:` frontmatter map.
- HIGH when the `hook-tests` step (`python3 Infrastructure/scripts/test_hooks.py`) or the
  `brain-tests` step (`python3 Infrastructure/scripts/test_brain.py`) fails. The hooks are
  shared by both adapters, so a change made for one can regress the other, and only the
  fixtures exercise their behavior.

### MT-9 Canonical Source Consistency

- Run `python3 Infrastructure/scripts/brain.py check --only lints`.
- HIGH when a canonical name appears in more than one of `agents/`, `rules/`, `templates/`,
  `skills/`, and `style/skills/` without an entry in `ALLOWED_DUPLICATIONS` in
  `Infrastructure/scripts/brain.py`.
- Rationale: undeclared duplicates drift apart silently. A declared pair states its reason
  and who keeps the two in step.

### MT-10 Style Token Drift

- Run `python3 Infrastructure/scripts/check_style_token_drift.py` (or `make style-tokens-check`).
- HIGH when any output of `Infrastructure/style/scripts/sync_tokens.py` (its `OUTPUTS`) does
  not match a fresh regeneration from `Infrastructure/style/tokens/eig-style-tokens.v1.json`,
  or when a hex color literal appears outside the tokens in the scope the check lints
  (`check_style_token_drift.py` names it).
- Fix by running `python3 Infrastructure/style/scripts/sync_tokens.py --write` and committing the
  result. Never hand-edit the generated outputs.
- Rationale: this is the MT-1 invariant applied to the style layer. The generated outputs
  carry an "Auto-generated / do not edit" banner, so a hand-edit or a token change without
  a re-sync is a governance violation of exactly the kind MT-1 exists to catch.

### MT-11 War-Room Test Suite

- Run `python3 Infrastructure/scripts/test_war_room.py`, registered as `war-room-tests` in
  `Infrastructure/scripts/run_maintenance_checks.py`.
- Fixtures live under `Infrastructure/scripts/war_room_fixtures/`; every fixture ledger
  carries `session.fixture: true` so fixture text cannot be mistaken for an agent's
  reading.
- All writes go to a temporary directory; the suite makes no network calls and completes
  in under 120 seconds.
- HIGH when the suite fails; a failure means one of the code war room's mechanically
  enforced guarantees (deterministic blocks, reproducible hashes, lint, drift, or
  rendering) is broken.
- Rationale: the code war room's central guarantee — that every rule the skill promises is
  enforced by a script rather than by model behavior — only holds if the enforcing scripts
  are themselves tested.

### MT-12 Review-Board Test Suite

- Run `python3 Infrastructure/scripts/test_review_board.py`, registered as
  `review-board-tests` in `Infrastructure/scripts/run_maintenance_checks.py`.
- Fixtures live under `Infrastructure/scripts/review_board_fixtures/`. Every fixture board
  sets `board.fixture: true`, and the suite fails if the fixtures directory's digest changes
  during a run.
- All writes go to a temporary directory; the suite makes no network calls and completes in
  under 120 seconds. Case 7 needs git and is skipped, with the reason printed, without it.
- HIGH when the suite fails; a failure means one of the review board's mechanically enforced
  guarantees (append-only feedback, computed statuses and stale approvals, the content hash,
  the close refusals, or the server's origin and path checks) is broken.
- Rationale: a review board is trustworthy only because its scripts refuse what its rules
  forbid, so those refusals must themselves be tested.

### MT-13 Replication Test Suite

- Run `python3 Infrastructure/scripts/test_replication.py`, registered as
  `replication-tests` in `Infrastructure/scripts/run_maintenance_checks.py`.
- The suite drives the real `build_replication_package.py` against synthetic projects it
  builds in a temporary directory. It makes no network calls and completes in under 60
  seconds. It needs git.
- HIGH when the suite fails. A failure means a replication safety guarantee is broken:
  the secret patterns, the symlink refusal, the non-interactive confirm, the title
  handling, the cleanup of a partial export, or the refusal of an empty include set.
- Rationale: a false negative in the replication builder is an irreversible public leak,
  so its refusals must themselves be tested.

### MT-14 Load Budget and Required Anchors

- Run `python3 Infrastructure/scripts/brain.py check --only load` (the `brain-load` step).
- HIGH when the words every Claude session loads (`CLAUDE.md`, the imported `AGENTS.md`, and
  every `load: always` rule) exceed `ALWAYS_LOADED_CEILING` in `brain.py`, when `AGENTS.md`
  lacks a phrase in `REQUIRED_ANCHORS` (no fabrication, the project-framing exception, the
  non-interactive blocker, the generated-file rule, commit attribution), or when the loading
  map in `Infrastructure/TEMPLATE_CENSUS.md` differs from the rule frontmatter.
- Rationale: every session and subagent pays for the always-loaded words, so the ceiling
  only moves down; the anchors keep a shrinking budget from silently deleting a guardrail.

### MT-15 Style, Local-App, and Project-Lane Suites

- Run `make style-test`, `make localapp-test`, and
  `python3 Infrastructure/scripts/test_project_lane.py` (registered as `style-tests`,
  `localapp-tests`, and `project-lane-tests`).
- HIGH when a suite fails. A case whose tool is missing (R and its packages, matplotlib and
  seaborn, Stata) is skipped with the reason printed. Without R, `project-lane-tests` reports
  SKIP in the runner summary. With `REQUIRE_R=1` a missing R fails the project-lane and R style
  cases, and with `REQUIRE_PLOTTING=1` missing plotting packages fail the Python style cases;
  CI sets both.
- Rationale: the themes, the local-app kit, and the R runner carry guarantees the analysis
  depends on, and only these suites exercise them.

### MT-16 Review-Fleet Suites

- Run `python3 Infrastructure/scripts/test_review_fleet.py` and
  `python3 Infrastructure/scripts/test_review_eval.py` (registered as `review-fleet-tests`
  and `review-eval-tests`).
- HIGH when either fails: the review workflows then discover the wrong files, rerun or skip
  the pipeline wrongly, render findings that were never validated, or merge findings that are
  not duplicates in `full-review`; or the evaluation fixture no longer builds. A stale patch under `Infrastructure/evals/review-fleet/` means
  the worked example changed: refresh the patch with `build_fixture.py diff`.
- The evaluation fixture patches the worked example, so it applies only while that example is
  intact. In the template (`Infrastructure/.template-identity` present) it always applies, and
  a stale patch or a missing example is HIGH. In a project, the fixture cases pass as "not
  applicable" once any file in `build_fixture.MARKED` loses its `EXAMPLE: replace` header; a
  project that keeps the example intact still runs them. `build_fixture.not_applicable()`
  applies this rule, and case 10 of `test_review_eval.py` tests it.

### MT-17 Census Completeness

- Run `python3 Infrastructure/scripts/check_census.py` (`census`; its tests are `census-tests`).
- MEDIUM when `Infrastructure/TEMPLATE_CENSUS.md` omits an agent, skill, rule, template, script,
  registered check, or make target, or names one that is gone: add or remove the table row.
- Rationale: the census is how a person finds a part; one that silently omits parts misleads.

### MT-18 Port Test Suite

- Run `python3 Infrastructure/scripts/test_port_template.py`, registered as `port-tests`.
- The suite drives the real `port_template.py` against fixture repositories it builds in a
  temporary directory, with a stub in place of the GitHub lookup passed as an argument, so the
  command line has no way past the visibility guard. It makes no network calls and needs git.
  In a project (no template marker) it reports SKIP, because the port runs only from the source
  template.
- HIGH when the suite fails. A failure means a port guarantee is broken: a public, archived,
  foreign, skip-listed, replication, dirty, or template target is no longer refused, an adopt
  or upgrade touches the project lane or overwrites a project edit, or a failed port no longer
  restores the target exactly.
- Rationale: porting into a public repository would publish the template's internal
  machinery, and that cannot be undone, so the refusal must itself be tested.

## Fixing the Template From a Project

A check that fails in a downstream project because of the template, not the project, is a
template defect, and the fix belongs upstream so every later project gets it.

1. Reproduce the failure in the template, or in a copy of the project with its own changes
   set aside, before calling it a template defect.
2. Fix the canonical file in a template checkout, one branch per fix. When another fix is
   already open in that checkout, give the new one its own `git worktree`, so two sessions
   never edit one working tree and their changes cannot land in one commit.
3. Copy the change into the project only after it passes in the template, and say in the
   project's commit which template commit it came from.
4. The plan and session log for a template fix go with the template, not into the project's
   `records/`, which hold the project's own decisions.

## Reporting Standard

1. List every check run, even if it passes.
2. Include exact command, pass/fail status, and key output.
3. Provide concrete fix actions for every HIGH or MEDIUM finding.
4. Include a rerun plan that verifies fixes end to end.
