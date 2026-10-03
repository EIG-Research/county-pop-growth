# Changelog

Changes to the EIG AI-Assisted Research Template. A project created from the template keeps
this file as the record of the template version it started from; the project's own history
belongs in its session logs.

## 2.0.0 (unreleased)

One Python generator for both adapters, far fewer always-loaded words, a rebuilt review fleet,
the 2022 brand lineage, and a runnable example.

### For research assistants

- **Start from `README.md`.** It takes a new RA from a clean clone to a first pipeline run and
  a first review, and states that every project stays internal to EIG (see `NOTICE`). It
  covers git identity and GitHub CLI sign-in, and says to trust `output/` only after a run
  that ends with its success line.
- **Project records live in `records/`** (plans, specs, session logs, war rooms, review
  boards), outside `Infrastructure/`; `make template-reset` clears them in a new project.
- **A worked example runs on day one.** `make pipeline` runs `code/run_all.R`, which runs each
  script set to `TRUE` in `run_script_flag` in its own R process from the project root, stops at the
  first failure, and writes one log to `output/logs/`. The example uses synthetic data in
  `data/example/`; each file to replace is marked `EXAMPLE: replace`. A project deletes the
  example's data and drafts when it replaces it (README, step 5); once `make template-reset`
  has run, the path check treats those paths as optional, and `make render QMD=...` renders
  another Quarto document.
- **New make targets:** `make check-project` (parse, lint, run), `make render` for the optional
  Quarto brief (skips without Quarto), and `make renv-bootstrap` to opt in to pinned R packages.
- **Safer `.gitignore`:** `data/processed/` contents, Stata and SPSS files, output `.tex`,
  `.xlsx`, and `.html` files, and `.Renviron` and `.env` files are ignored.
- **Shorter instructions.** `AGENTS.md` holds every guardrail. A saved plan is needed only when
  a task changes more than two files, touches `Infrastructure/` outside the literature store,
  or is hard to reverse. The
  Evidence section is optional for replies about code or repository mechanics verified by a
  shown command. `PROJECT.md` has working agreements, including the session-log cadence.
- **Reviews** write validated JSON findings rendered to `review-reports/index.html`, and
  reviewers may write only there. `/full-review` runs the lenses in parallel, merges
  duplicates, and re-checks each HIGH or CRITICAL finding. `/orchestrate` starts the
  orchestrator for multi-specialist work.
- **Methodology rules** gain owner-signed econometrics sections:
  - DiD, IV, clustering, RD, and logs with zeros, with checks for staggered adoption, weak and
    many instruments, judge and formula instruments, short panels, multi-way and spatial
    clustering, fuzzy and spatial RD, and outcomes with zeros;
  - survey weights, ACS (including the IPUMS dollar conventions), CPS, and deflators.
- **Dataset registry:** template entries stay `unverified` until a person signs them against a
  source; a project's own entries go in `data/docs/dataset-registry.yaml`.
- **Style follows the 2022 brand guide** (Source Serif and Open Sans). Figure titles sit inside
  the image with no "Figure N." prefix; font installers check pinned SHA-256 sums.
- **Replication packages** come from a Python builder that scans for secrets and never pushes.
- **Windows is supported alongside macOS.** The README gives the Windows setup (Git for
  Windows and Git Bash, make, R, and a Python 3.12 environment named `python3`). Every check
  suite passes natively on a default-settings Windows clone; the repository checks out with LF
  line endings, and the make targets and hooks fall back to `python` or `py -3` when
  `python3` is missing. On Windows, `R_ENVIRON_USER` points RStudio and the agent's `Rscript`
  at one `.Renviron`, so an API key that works in RStudio also works for the agent.
- **Copying the template by hand** works if every file comes along, `.gitattributes` above
  all; `make template-reset` warns when that file lacks `eol=lf`.
- **Existing projects come in with `make port TARGET=<folder>`.** It installs the template's
  machinery on a local branch of an existing private repository and never pushes. In a repository
  without the template, it moves any earlier AI setup to `legacy-ai/` (adopt). In one with an
  older copy, it replaces only the files the template wrote and keeps the project's edits
  (upgrade). It never touches the project's code, data, drafts, output, or records. It refuses
  any repository GitHub does not report as private, and any `*-replication` repository. The
  `.eig-port` marker it writes records the template version shipped, and with
  `project_lane: legacy` it tells the path check that the project keeps its own layout.

### For maintainers

- **`Infrastructure/scripts/brain.py`** generates `.claude/`, `.codex/`, and `.agents/` from
  `Infrastructure/` and lists every generated file in `.brain-manifest`; sync writes and deletes
  only listed files, and the guard hook protects exactly those. Metadata lives in frontmatter.
  `AGENTS.md` and `CLAUDE.md` are hand-written, and `CLAUDE.md` imports `AGENTS.md`.
- **Workflows are skills** in both adapters. Rules declare a `load:` tier;
  `brain.py check --only load` enforces the always-loaded word ceiling, the required
  `AGENTS.md` anchors, and the loading map in `Infrastructure/TEMPLATE_CENSUS.md`.
- **One command policy,** `Infrastructure/adapter_configs/permissions.yaml`, renders the Claude
  permissions and the Codex rules (no Codex `allow` rules). `Infrastructure/AUTHORING.md` sets
  how agents, skills, rules, and templates are written, with a pre-merge checklist.
- **Checks:** `make maintenance-check` runs one Python registry
  (`run_maintenance_checks.py --list`); `check_census.py` keeps the census complete. The review
  fleet has a review contract, a discovery manifest, consolidation, and an owner-gated
  planted-defect evaluation (`make review-eval CONFIRM=1`).
- **CI** runs on pushes to `main` and pull requests, with R and the plotting packages required,
  a Python 3.11 job, a brain-sync idempotency check, and a derived-project start (reset, path
  check, brain check).
- **Hardening from the final adversarial review:** the replication export refuses dot-segment
  include and exclude paths and rechecks every staged path; the secret scan catches Census and
  BLS keys (in a URL, as a bare `key`, or on the next line) and OpenAI and Google key formats;
  the generated-tree guard covers more shell edit idioms and Codex `Move to:` patches; Claude
  denies force-push after any remote or ref; pre-approved commands ask first before writing
  through `--output`, running `git difftool`, or leaving `code/` through `..`; relative
  Markdown links are checked; `brain.py` refuses repeated keys in its adapter sources.
- **Fixes from the new-RA walkthrough:** the generated-tree guard judges a mutating verb by
  its own simple command, so `mkdir -p x && grep ...` on a generated file is no longer denied,
  and it now catches a verb that starts a later line; the internal path check also fails a
  tracked non-Markdown file under `Infrastructure/`, an adapter tree, `.github/`, or the
  `Makefile` that cites a dated plan, spec, or session log, which `make template-reset` deletes.
- **Raw-data protection** is one Claude deny rule, `Edit(data/raw/**)`, which covers every
  file-editing tool; the `Write` form Claude Code ignores (and warned about at launch) is gone.
- **Development records removed from the tree.** The plans, specs, and session logs written
  while building 2.0.0 are in git history (before the commit that removed them); `records/`
  ships with only its folder READMEs, as a new project gets it.
- **Fixes from the first project pilot** (2026-09-30):
  - the brain fixture copies untracked, unignored files as well as tracked ones, and the war
    room suite compares its ledgers and `code/` status with their state before the run, so
    both pass in a new project before its first commit and in one with its own war rooms;
  - the orchestrator waits for each wave to finish before returning, and never runs two
    workstreams that write the same file in one wave;
  - data documentation rule DD-8: the claims a documentation pass makes are checked against
    the data at first read, and constructed estimates are benchmarked against published ones
    overall and for a subgroup, since one aggregate can match while two errors cancel;
  - the verification protocol warns that piping a check into `tail` hides its exit status;
  - the review contract says how to run a second review round after fixes;
  - the maintenance rules say how to fix the template from a downstream project;
  - a change confined to the literature store needs neither a saved plan nor the full
    maintenance check, only the literature checks the verification protocol names (the
    always-loaded ceiling rose from 1,246 to 1,261 words, owner-approved, to say so).
- **EIG AI-use policy:** AI never drafts any part of a work product's prose; it gives feedback
  (comments, rule citations, word or short-phrase swaps) and the author makes every change.
  AI may write code, analysis, figure code with its titles and slide text, logs, and summaries.
  Every AI use is logged in `records/ai-use-log.md` and disclosed in the product, with the
  supervisor informed (`Infrastructure/rules/ai-use-disclosure-rules.md`). `eig-writer` is now
  a read-only writing coach, `smart-brevity` returns a critique rather than a rewrite, and the
  cover sheet and final handoff checklist carry the disclosure (the always-loaded ceiling rose
  from 1,261 to 1,339 words, owner-approved, for the `AGENTS.md` guardrail).
- **CI on three platforms:** the full check suite also runs on Windows and macOS runners.
- **Shared local-app kit** (`Infrastructure/scripts/localapp/`) for the war room and review
  board. Its loopback server binds without a hostname lookup, which had stalled startup for
  about 35 seconds on macOS runners.
- **Style tokens** are version 2.0.0, with type sizes in points (`size_pt`); the Stata scheme is
  generated from them.

### Removed, and what replaces it

- `GUARDRAILS.md` and the root-instruction sources: the hand-written `AGENTS.md`.
- The Bash generator and maintenance runner, their checkers, the metadata TSVs, and
  `make brain-sync FORCE=1`: `brain.py`, `run_maintenance_checks.py`, frontmatter, and
  `.brain-manifest`. The hand-written Codex execpolicy file: `permissions.yaml`, which renders
  `.codex/rules/template.rules`.
- Governance rules: meta-governance folded into `AGENTS.md` (Change Control); the empty
  constitutional-governance rule and the exploration protocol retired; local-model delegation
  moved into the `delegate-to-local-model` skill; the review pipeline runner replaced by
  `Infrastructure/rules/review-contract.md`; replication-protocol renamed
  `Infrastructure/rules/reproduce-published-results.md`.
- The orchestration-plan template: the slimmed `orchestrator` agent and `/orchestrate` skill.
- Per-lens Markdown report templates: `Infrastructure/templates/review-findings.schema.json`
  and `Infrastructure/scripts/render_review_report.py`.
- The templates mirror in the adapter trees: templates are read from `Infrastructure/templates/`.
- Superseded style docs: the topic docs indexed in `Infrastructure/style/docs/README.md`.
- The replication shell shim and CPS review smoke test: the Python builder and review-fleet tests.
