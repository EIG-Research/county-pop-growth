# Template Census

The inventory of the EIG AI-Assisted Research Template: what each part is, where it lives, and
how the parts connect. `AGENTS.md` (Repository Layout) is the short orientation; this is the
detail behind it, and `Infrastructure/README.md` is the index of `Infrastructure/`.

How it stays current: every backticked name in a column headed Agent, Skill, Rule, Template,
Script, Check, or Target must name a part that exists, and every such part must be named
(`Infrastructure/scripts/check_census.py`, the `census` maintenance check, which states what
counts as a part). Backticked paths must resolve (`internal-paths`), and the loading map in §5.1
must match the rule frontmatter (`brain-load`). The prose around the tables has no check;
update it in the change that makes it wrong.

## 1. Two lanes

The repository is a research project and a reusable template at once (`AGENTS.md`, Change
Control). Project work lives in `PROJECT.md`, `code/`, `data/`, `drafts/`, `output/`, and
`records/`; the reusable machinery is `Infrastructure/` plus the adapter trees generated from it.
`make template-reset` returns `records/` to its READMEs and removes
`Infrastructure/.template-identity`, which re-arms the `PROJECT.md` title requirement in the
copy. It never touches `code/`, `data/`, `drafts/`, or `output/`: clearing a project's inputs
and results is a human's decision.

## 2. Top-level map

| Path | Role |
|---|---|
| `PROJECT.md` | Project context: title (the one hard requirement), question, data, deliverables, working agreements. |
| `README.md` | Getting started for people; not in the agent's startup reads. |
| `AGENTS.md` | Root instructions for both tools, written by hand. Codex loads it directly. |
| `CLAUDE.md` | `@AGENTS.md` plus Claude runtime notes, written by hand. |
| `Makefile` | The control panel (§7). |
| `CHANGELOG.md` | Release notes, one entry per template version. `make template-reset` keeps it, so a project records the template version it started from. |
| `NOTICE` | The internal-use statement (internal to EIG, never public), matching the README's opening notice; no license grant. `make template-reset` keeps it, because it applies to derived projects too. |
| `.brain-manifest` | Every file `make brain-sync` generates. Sync writes and deletes only listed files; the guard hook blocks edits to them, to the manifest itself, and to each directory holding a listed file. |
| `.claude/`, `.codex/`, `.agents/` | Adapter trees generated from `Infrastructure/` (§5). A file a project adds there itself is not in the manifest, and sync never touches it. |
| `.github/workflows/maintenance-check.yml` | CI on pushes to `main` and pull requests: `make maintenance-check` with R and the plotting packages (`REQUIRE_R=1`, `REQUIRE_PLOTTING=1`), a brain-sync idempotency check, a derived-project start (reset, path check, brain check), and the suite again on Python 3.11, the floor. |
| `code/` | Analysis scripts: the starter pipeline `code/run_all.R`, and a worked example whose numbered scripts are marked `EXAMPLE: replace` (`code/README.md`). |
| `data/` | `data/raw` (as received) and `data/processed` (checkpoints), their contents gitignored; `data/example` holds the example's synthetic data. |
| `drafts/` | Prose in progress; `drafts/example_note.md` traces each number to a table, and `drafts/example_brief.qmd` is the optional Quarto example. |
| `output/` | `output/figures`, `output/tables`, and `output/logs` (one log per pipeline run). |
| `records/` | Plans, specs, session logs, war-room ledgers, and review boards (`records/README.md`). |
| `Infrastructure/` | Canonical sources for every adapter file, and the rules, style system, references, and scripts (§3). |

Review workflows write findings and reports to `review-reports/` inside the reviewed project at
run time; it is gitignored.

## 3. Infrastructure

Subsystems with their own map: the code war room (`Infrastructure/war_room/README.md`), the
review board (`Infrastructure/review_board/README.md`), the replication package
(`Infrastructure/replication/README.md`), the style system (`Infrastructure/style/README.md`;
its topic docs are indexed in `Infrastructure/style/docs/README.md`), and the knowledge stores
(`Infrastructure/references/README.md`: the literature catalog and the dataset registry).

`Infrastructure/adapter_configs/` holds the per-adapter sources that are not agents, skills, or
rules: `claude.settings.json`, `codex.config.toml`, `codex.hooks.json`, the adapter READMEs,
and `permissions.yaml`, the one command policy rendered into both adapters. Agent and skill
metadata lives in each canonical file's frontmatter (`Infrastructure/AUTHORING.md` §7).

### 3.1 Agents — `Infrastructure/agents/`

| Agent | Role | Launched by |
|---|---|---|
| `code-reviewer` | Code lens: definitive bugs in R, Python, and Stata. | `review-code`, `full-review` |
| `methodology-reviewer` | Methodology lens: identification, inference, weights, samples. | `review-methodology`, `full-review` |
| `data-consistency-reviewer` | Numbers lens: each number in a document traced to code or data. | `review-numbers`, `full-review` |
| `conceptual-consistency-reviewer` | Consistency lens: does the prose describe what the code does. | `review-consistency`, `full-review` |
| `ai-skeptic` | Provenance lens: citations, external figures, functions, variables. | `review-ai`, `full-review` |
| `code-interlocutor` | War room: commits its reading of each block, then reconciles it with the author's account. | `code-war-room` |
| `data-dictionary-agent` | Acquires vintage-pinned codebooks and writes the dataset registry. | `document-data` |
| `literature-scout` | Maps a literature and drafts catalog entries. | direct |
| `eig-writer` | Writing coach: feedback on an author's own EIG prose; never drafts it. | direct |
| `eig-reviewer` | Audits prose and citations against EIG style. | `review-style` |
| `eig-style-guide-agent` | Writes and fixes EIG figure and table code. | direct; style skills hand off to it |
| `maintenance-agent` | Runs the maintenance suite and reports prioritized actions. | direct |
| `orchestrator` | Orders multi-specialist work by dependency and spawns it in waves. | `orchestrate` |
| `replication-safety-reviewer` | Scans a staged public export for secrets, paths, and PII. | `build-replication-package` |

The review lenses share `Infrastructure/rules/review-contract.md`, and each declares the write
guard hook (§3.5) in its frontmatter.

### 3.2 Skills — `Infrastructure/skills/` and `Infrastructure/style/skills/`

Each workflow is `Infrastructure/skills/<name>/SKILL.md`, plus any files beside it; the style
skills are single files under `Infrastructure/style/skills/`. Both render to Claude skills and
Codex repo skills (§5).

| Skill | What it does |
|---|---|
| `review-code`, `review-methodology`, `review-numbers`, `review-consistency`, `review-ai` | One review lens on a target project, rendered to HTML (§6). |
| `full-review` | Every applicable lens, then consolidation and refutation of HIGH and CRITICAL findings (§6). |
| `review-style` | EIG writing and citation audit of a document, section by section. |
| `code-war-room` | Block-by-block walkthrough of one script with its author. |
| `review-board` | Rounds of owner review of rendered figures, tables, or slides. |
| `build-replication-package` | Exports an allowlisted public package, gated by a safety scan. |
| `document-data` | Acquires and documents a data source in the dataset registry. |
| `literature-intake` | Adds a paper or codebook to the literature catalog. |
| `interview-me` | Resolves underspecified intent into a confirmed intent brief. |
| `idea-refine` | Compares directions for an understood idea; returns a concept brief. |
| `orchestrate` | Launches the `orchestrator` agent on a multi-step objective. |
| `maintenance-check` | Runs the maintenance suite and reports prioritized actions. |
| `delegate-to-local-model` | Proposes, dispatches, and reviews mechanical work on a local model server. |
| `cite`, `cover-sheet`, `smart-brevity` | EIG citation, publication cover sheet (factual fields), and Smart Brevity critique. |
| `eig-style-apply`, `eig-style-datawrapper`, `eig-style-review`, `eig-tufte-critique` | Style skills: apply themes, check Datawrapper governance, audit figures, critique chart design. |

`interview-me` and `idea-refine` are adapted from upstream projects (`UPSTREAM.md` beside each).

### 3.3 Rules — `Infrastructure/rules/`

Each rule owns its policy; its load tier is in §5.1.

| Rule | Governs |
|---|---|
| `plan-first-workflow` | Specs, saved plans, approval, and execution for non-trivial tasks. |
| `session-logging` | What a session log records and when. |
| `ai-use-disclosure-rules` | The EIG AI-use policy: AI never drafts work-product prose; the ledger and disclosure statement. |
| `verification-protocol` | Verifying before claiming done. |
| `performance-cost-governance` | Cost statements, runaway limits, and the human gate on long runs. |
| `reproduce-published-results` | Reproducing a published result before extending it. |
| `maintenance-rules` | Severity and rationale for each maintenance check family. |
| `r-coding-style-rules` | Project-authored R. |
| `review-contract` | What every review lens shares: inputs, pipeline, severity, evidence, output. |
| `code-quality-rules`, `methodology-rules`, `doc-number-rules`, `doc-consistency-rules`, `ai-skeptic-rules` | Each review lens's check families. |
| `data-documentation-rules` | The dataset registry and per-variable docs. |
| `code-war-room-rules`, `code-war-room-design`, `code-war-room-segmentation` | The war-room session; its mechanics and block boundaries, for maintainers. |
| `review-board-rules` | The review board's rounds, records, and approvals. |
| `replication-publishing-rules` | The public-export contract. |
| `style-writing-rules`, `style-citation-rules`, `style-figure-rules`, `style-datawrapper-rules` | EIG prose, citations, figures, and Datawrapper publishing. |

### 3.4 Templates — `Infrastructure/templates/`

| Template | Used by |
|---|---|
| `plan.md`, `requirements-spec.md` | `Infrastructure/rules/plan-first-workflow.md` |
| `session_log.md` | `Infrastructure/rules/session-logging.md` |
| `ai-use-disclosure.md` | `Infrastructure/rules/ai-use-disclosure-rules.md` (the `records/ai-use-log.md` ledger) |
| `review-findings.schema.json` | Every review lens writes findings against it; `render_review_report.py` validates and renders them. |
| `war-room-ledger.md`, `war-room-work-order.md`, `war-room-report.md` | The code war room |
| `review-board-config.md`, `review-board-ledger.md`, `review-board-round-plan.md` | The review board (`review_board.py` reads the round-plan skeleton) |
| `replication-safety-report.md` | `replication-safety-reviewer` |
| `maintenance-report.md` | `maintenance-check`, `maintenance-agent` |
| `style-review-report.md`, `style-citation-output.md`, `style-cover-sheet.md`, `smart-brevity-output.md` | `review-style`, `cite`, `cover-sheet`, `smart-brevity` |

### 3.5 Scripts — `Infrastructure/scripts/`

Each registered check runs through `run_maintenance_checks.py` (`--list` prints the registry).

| Script | Job | Check |
|---|---|---|
| `brain.py` | Generates the adapter trees and `.brain-manifest` (`sync`); checks drift, lints, and the load budget (`check`); writes §5.1 (`loading-map --write`). | `brain-check`, `brain-lints`, `brain-load` |
| `test_brain.py` | `brain.py` against a throwaway copy of the repository. | `brain-tests` |
| `hooks/guard_generated_tree.py` | PreToolUse, both adapters: blocks edits to manifest-listed files and names the canonical source. | |
| `hooks/remind_brain_sync.py` | PostToolUse, both adapters: once per session, reminds that a canonical edit needs `make brain-sync`. | |
| `hooks/session_context.py` | SessionStart, both adapters: injects the `PROJECT.md` title state and the newest plan and session log. | |
| `hooks/guard_review_write.py` | Declared by each review agent: allows its file writes only under `review-reports/`. | |
| `hooks/hook_common.py` | Shared payload parsing for both adapters' hook events. | |
| `hooks/run_python.sh` | Launcher every hook command goes through: runs the first real Python (python3, python, then `py -3`), skipping the Windows Store alias stub. | |
| `test_hooks.py` | The hooks under both adapters, and the command policy in `permissions.yaml`. | `hook-tests` |
| `run_maintenance_checks.py` | The check registry and runner behind `make maintenance-check`. | |
| `check_internal_path_references.py`, `test_path_references.py` | Backticked and linked internal paths in Markdown resolve, `./` and `../` from the referencing file; plans, specs, record subdirectories, and fixtures are exempt; tracked non-Markdown files under `Infrastructure/`, the adapter trees, `.github/`, and the `Makefile` cite no dated record; its planted-reference tests. | `internal-paths`, `path-reference-tests` |
| `check_census.py`, `test_census.py` | This census names every part and nothing stale; its planted-omission tests. | `census`, `census-tests` |
| `validate_literature_catalog.py`, `check_catalog_staleness.py` | Literature catalog schema and paths; entries not verified recently. | `literature-catalog`, `catalog-staleness` |
| `validate_dataset_registry.py` | Dataset registry and a project's `data/docs/` overlay. | `dataset-registry` |
| `test_knowledge_stores.py` | The knowledge-store validators against planted bad entries. | `knowledge-store-tests` |
| `check_style_token_drift.py`, `test_style.py` | Generated themes match the tokens; the R, Python, and Stata themes and examples. | `style-tokens`, `style-tests` |
| `test_project_lane.py` | The R rule's examples, `code/run_all.R`, and the worked example. | `project-lane-tests` |
| `review_manifest.py` | Review discovery (the JSON manifest of code and documents) and the pipeline run, reused while its input hash holds. | |
| `render_review_report.py` | Validates findings JSON, assigns IDs, and renders each lens's HTML report and `index.html`. | |
| `review_consolidate.py` | `full-review` phase 2: merges duplicates, cross-links, queues HIGH and CRITICAL findings for refutation, applies verdicts. | |
| `test_review_fleet.py`, `review_fleet_fixtures/` | The review scripts above, on canned findings and a golden render. | `review-fleet-tests` |
| `review_eval.py`, `test_review_eval.py` | Scores the lenses on the planted-defect fixture in `Infrastructure/evals/review-fleet/` (`make review-eval`, human-gated); the scorer's tests. | `review-eval-tests` |
| `localapp/` | Shared kit for the local apps: YAML IO, file lock, project root, loopback server, lint types, test kit. | |
| `test_localapp.py` | The local-app kit. | `localapp-tests` |
| `war_room_lib.py`, `war_room_prep.py`, `war_room_lint.py`, `war_room_server.py`, `war_room_app/`, `war_room_reconcile.py`, `war_room_render.py`, `war_room_fixtures/`, `test_war_room.py` | The code war room (`Infrastructure/war_room/README.md`). | `war-room-tests` |
| `review_board.py`, `review_board_lib.py`, `review_board_lint.py`, `review_board_measure.py`, `review_board_server.py`, `review_board_app/`, `review_board_fixtures/`, `test_review_board.py` | The review board (`Infrastructure/review_board/README.md`). | `review-board-tests` |
| `build_replication_package.py`, `validate_replication_manifest.py`, `replication_assets/`, `test_replication.py` | The replication package (`Infrastructure/replication/README.md`). | `replication-tests` |
| `template_reset.sh` | Scrubs `records/` and removes the template marker (`make template-reset`). | |
| `port_template.py`, `test_port_template.py` | Brings the machinery into an existing private research repository on a local branch, adopting (legacy AI files to `legacy-ai/`) or upgrading (template-written files replaced by blob history, project edits kept), and writes the `.eig-port` marker (`make port`); its refusal, adopt, upgrade, and rollback tests. | `port-tests` |

## 4. Knowledge and style

- **Literature** (`Infrastructure/references/literature/`): `catalog.yaml` indexes the papers,
  summaries, and data dictionaries beside it; the schema is in its README.
- **Datasets** (`Infrastructure/references/datasets/registry.yaml`): recognized datasets'
  weights, pitfalls, identification signals, and variables. A project documents its own
  variables in the overlay `data/docs/dataset-registry.yaml`. The methodology and provenance
  lenses and the `document-data` workflow read it.
- **Style** (`Infrastructure/style/`): the tokens (`Infrastructure/style/tokens/eig-style-tokens.v1.json`)
  are the source of approved colors and type; `Infrastructure/style/scripts/sync_tokens.py` generates
  the token files the R, Python, and Stata themes read, and the token tables doc; examples, compliance scripts, brand
  assets, and source guides sit beside them.

## 5. The generation model

Logic is written once in `Infrastructure/` and generated into each adapter by
`Infrastructure/scripts/brain.py`. Edit the canonical file, run `make brain-sync`, and commit
both; `make brain-check` reports drift, and the guard hook blocks edits to generated files.

| Capability | Claude surface | Codex surface | Canonical source |
|---|---|---|---|
| Root instructions | `CLAUDE.md` (imports `AGENTS.md`) | `AGENTS.md` | the root files, by hand |
| Workflows | `.claude/skills/<name>/` | `.agents/skills/<name>/` | `Infrastructure/skills/<name>/` |
| Style skills | `.claude/skills/<name>/SKILL.md` | `.agents/skills/<name>/SKILL.md` | `Infrastructure/style/skills/` |
| Agents | `.claude/agents/<name>.md` | `.codex/agents/<name>.toml` (a wrapper that reads the canonical body) | `Infrastructure/agents/` |
| Rules | `.claude/rules/` for `always` and `paths` rules; others read in place | read in place | `Infrastructure/rules/` |
| Templates | read in place | read in place | `Infrastructure/templates/` |
| Settings and hooks | `.claude/settings.json` | `.codex/config.toml`, `.codex/hooks.json` | `Infrastructure/adapter_configs/`, `Infrastructure/scripts/hooks/` |
| Command policy | `.claude/settings.json` (`permissions`) | `.codex/rules/template.rules` | `Infrastructure/adapter_configs/permissions.yaml` |
| Adapter README | `.claude/README.md` | `.codex/README.md` | `Infrastructure/adapter_configs/` |

Sync deletes a file only when the previous manifest listed it and it is no longer generated, so
a project's own agents, skills, and local settings survive every sync.

### 5.1 Loading map

When each instruction file reaches the model, by the load tiers in `Infrastructure/AUTHORING.md`
§1. Rules declare their tier in `load:` frontmatter; other files take their type's tier. Every
session and subagent pays for the `always` rows, and `brain-load` holds that word count under a
ceiling that only moves down. The table is generated; refresh it with
`python3 Infrastructure/scripts/brain.py loading-map --write`.

<!-- loading-map:begin -->
| File | `load` | Claude Code | Codex |
|---|---|---|---|
| `CLAUDE.md` | always | every session and subagent | not read |
| `AGENTS.md` | always | every session and subagent (imported by `CLAUDE.md`) | every session |
| `Infrastructure/rules/data-documentation-rules.md` | paths | when a matching file is read: `data/**`, `Infrastructure/references/datasets/**` | read by path |
| `Infrastructure/rules/maintenance-rules.md` | paths | when a matching file is read: `Infrastructure/scripts/**`, `Makefile` | read by path |
| `Infrastructure/rules/r-coding-style-rules.md` | paths | when a matching file is read: `code/*.R`, `code/**/*.R`, `**/*.Rmd`, `**/*.qmd` | read by path |
| `Infrastructure/rules/style-citation-rules.md` | paths | when a matching file is read: `drafts/**` | read by path |
| `Infrastructure/rules/style-datawrapper-rules.md` | paths | when a matching file is read: `code/**`, `output/**`, `Infrastructure/style/**` | read by path |
| `Infrastructure/rules/style-figure-rules.md` | paths | when a matching file is read: `code/**`, `output/**`, `Infrastructure/style/**` | read by path |
| `Infrastructure/rules/style-writing-rules.md` | paths | when a matching file is read: `drafts/**` | read by path |
| `Infrastructure/rules/ai-skeptic-rules.md` | referenced | read by path | read by path |
| `Infrastructure/rules/ai-use-disclosure-rules.md` | referenced | read by path | read by path |
| `Infrastructure/rules/code-quality-rules.md` | referenced | read by path | read by path |
| `Infrastructure/rules/code-war-room-design.md` | referenced | read by path | read by path |
| `Infrastructure/rules/code-war-room-rules.md` | referenced | read by path | read by path |
| `Infrastructure/rules/code-war-room-segmentation.md` | referenced | read by path | read by path |
| `Infrastructure/rules/doc-consistency-rules.md` | referenced | read by path | read by path |
| `Infrastructure/rules/doc-number-rules.md` | referenced | read by path | read by path |
| `Infrastructure/rules/methodology-rules.md` | referenced | read by path | read by path |
| `Infrastructure/rules/performance-cost-governance.md` | referenced | read by path | read by path |
| `Infrastructure/rules/plan-first-workflow.md` | referenced | read by path | read by path |
| `Infrastructure/rules/replication-publishing-rules.md` | referenced | read by path | read by path |
| `Infrastructure/rules/reproduce-published-results.md` | referenced | read by path | read by path |
| `Infrastructure/rules/review-board-rules.md` | referenced | read by path | read by path |
| `Infrastructure/rules/review-contract.md` | referenced | read by path | read by path |
| `Infrastructure/rules/session-logging.md` | referenced | read by path | read by path |
| `Infrastructure/rules/verification-protocol.md` | referenced | read by path | read by path |
| `Infrastructure/agents/<name>.md` | invoked | when spawned (`.claude/agents/`); description always listed | when spawned (`.codex/agents/<name>.toml`) |
| `Infrastructure/skills/<name>/SKILL.md` | invoked | when invoked (`.claude/skills/`); description always listed | when invoked (`.agents/skills/`); description always listed |
| `Infrastructure/style/skills/<name>` | invoked | when invoked (`.claude/skills/`); description always listed | when invoked (`.agents/skills/`); description always listed |
| `PROJECT.md`, `Infrastructure/AI_WORKFLOW.md` | referenced | read by path at startup (`AGENTS.md`) | read by path at startup (`AGENTS.md`) |
| `Infrastructure/templates/<name>`, `Infrastructure/style/docs/<name>` | referenced | read by path | read by path |
<!-- loading-map:end -->

## 6. How a review wires together

Using the code lens as the example:

1. The `review-code` workflow (`Infrastructure/skills/review-code/SKILL.md`) runs the pipeline
   and discovers files with `Infrastructure/scripts/review_manifest.py`, under
   `Infrastructure/rules/review-contract.md`; a failed pipeline stops the review.
2. It spawns `code-reviewer`, whose write guard keeps its file writes in `review-reports/`.
3. The agent applies `Infrastructure/rules/code-quality-rules.md` and writes
   `review-reports/code.findings.json` against `Infrastructure/templates/review-findings.schema.json`.
4. `Infrastructure/scripts/render_review_report.py` validates the findings, assigns IDs, and
   renders the lens report and `index.html`.

The other lenses pair the same way (the agent table in §3.1 and the rule table in §3.3).
`full-review` runs every applicable lens, then `Infrastructure/scripts/review_consolidate.py`
merges duplicates and sends each HIGH or CRITICAL finding back to its owning agent to refute
before one index is rendered. The dataset registry feeds the lenses, so documenting data with
`document-data` sharpens reviews.

## 7. Make targets

| Target | Action |
|---|---|
| `make brain-sync` | Regenerate the adapter trees and `.brain-manifest`. |
| `make brain-check` | Every `brain.py check` part: drift, lints, load, and the hook and brain suites. |
| `make parity-check` | Alias for `brain-check`. |
| `make maintenance-check` | Every registered check, continuing past failures, with a summary. |
| `make literature-check`, `make dataset-registry-check`, `make style-tokens-check` | One validator each. |
| `make war-room-test`, `make review-board-test`, `make replication-test`, `make style-test`, `make localapp-test` | One registered suite each, through the runner. |
| `make review-eval` | Prints the evaluation plan; with `CONFIRM=1`, runs every lens on the planted-defect fixture and scores it (model cost, over an hour, never in CI). |
| `make template-reset` | Scrub `records/` and remove the template marker (`ARGS="--dry-run"` to preview). |
| `make port` | Port the machinery into the private repository at `TARGET=` on branch `chore/eig-template-v2` (`ARGS="--dry-run"` to preview); never pushes. |
| `make pipeline` | Run `code/run_all.R`. |
| `make check-project` | Parse and lint the R under `code/`, then run the pipeline. |
| `make renv-bootstrap` | Opt in to pinned R packages with `renv::init()`. |
| `make render` | Render `drafts/example_brief.qmd` (or `QMD=drafts/<file>.qmd`) when Quarto is installed. |

`pipeline`, `check-project`, `renv-bootstrap`, and `render` exercise the project lane, so `maintenance-check` does not run them.
