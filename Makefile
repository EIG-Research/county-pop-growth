.PHONY: brain-sync brain-check literature-check dataset-registry-check style-tokens-check maintenance-check parity-check war-room-test review-board-test replication-test style-test localapp-test review-eval template-reset port

# The Python interpreter: python3 where it is a real interpreter (macOS, Linux, or a Windows
# venv that has python3.exe), else python, else the Windows py launcher. On Windows, python3
# is often the Microsoft Store alias stub in WindowsApps, so a name resolving there is skipped.
# Override with `make PYTHON=/path/to/python ...`.
PYTHON ?= $(shell for p in python3 python; do c=$$(command -v $$p 2>/dev/null) || continue; case "$$c" in (*WindowsApps*) continue;; esac; echo $$p; exit 0; done; command -v py >/dev/null 2>&1 && echo "py -3" || echo python3)

# brain-sync regenerates .claude/, .codex/, and .agents/ from Infrastructure/ (the root
# AGENTS.md and CLAUDE.md are written by hand) and records every generated file in .brain-manifest. It writes only
# those files and deletes a file only when the previous manifest listed it and it is no
# longer generated, so a file you add yourself, such as .claude/agents/<name>.md or
# .claude/settings.local.json, is never touched.
brain-sync:
	$(PYTHON) Infrastructure/scripts/brain.py sync

# brain-check runs every generated-copy check in one pass: content drift, missing and
# orphan files, the structural lints (canonical frontmatter, generated TOML and
# frontmatter, invocation hygiene, declared canonical duplication), the load budget (the
# always-loaded word ceiling, the required AGENTS.md anchors, and the loading map), and the
# hook and brain fixture suites, each reported under its own name.
brain-check:
	$(PYTHON) Infrastructure/scripts/brain.py check

literature-check:
	$(PYTHON) Infrastructure/scripts/validate_literature_catalog.py

dataset-registry-check:
	$(PYTHON) Infrastructure/scripts/validate_dataset_registry.py

# style-tokens-check applies the brain-check invariant to the style layer: the
# three generated theme files carry an "Auto-generated / do not edit" banner but
# had no drift detection until this target existed.
style-tokens-check:
	$(PYTHON) Infrastructure/scripts/check_style_token_drift.py

# parity-check is an alias for brain-check, which now also runs the structural
# checks (missing adapter mirrors, orphan adapter files, uncovered metadata, and
# unapproved canonical-source duplications) that parity-check used to run separately.
parity-check: brain-check

# maintenance-check runs every check in the registry at the top of
# Infrastructure/scripts/run_maintenance_checks.py (`--list` prints it), continues past
# failures, prints a summary, and exits non-zero if any check failed. A check that cannot run
# here (R absent) is reported as SKIP; REQUIRE_R=1 turns that into a failure, as in CI.
RUNNER = $(PYTHON) Infrastructure/scripts/run_maintenance_checks.py
maintenance-check:
	$(RUNNER)

# The targets below run one registered check each through the same runner. None needs a
# model or the network; each suite writes only to a temporary directory.
# war-room-test: the code war room's prep, lint, server, reconcile, and render scripts against
# Infrastructure/scripts/war_room_fixtures/ (`war-room-tests`).
war-room-test:
	$(RUNNER) --only war-room-tests

# review-board-test: the review board's CLI, lint, measurement, and server against
# Infrastructure/scripts/review_board_fixtures/ (`review-board-tests`).
review-board-test:
	$(RUNNER) --only review-board-tests

# replication-test: the replication-package builder's safety suite against synthetic
# projects (`replication-tests`).
replication-test:
	$(RUNNER) --only replication-tests

# style-test: the style tokens, generated themes, and the R, Python, and Stata themes and
# examples (`style-tests`); a case whose tool is missing is skipped with the reason printed.
style-test:
	$(RUNNER) --only style-tests

# localapp-test: the shared local-app kit under Infrastructure/scripts/localapp/
# (`localapp-tests`).
localapp-test:
	$(RUNNER) --only localapp-tests

# review-eval scores the review agents against the planted-defect fixture in
# Infrastructure/evals/review-fleet/ (Infrastructure/scripts/review_eval.py). It spawns every
# reviewer several times, with model cost and a Tier 4 runtime (over 60 minutes), so it is
# human-gated: only CONFIRM=1 runs it; otherwise it prints the plan and exits non-zero. It is
# not a maintenance check and it refuses to run under CI. OUT= sets the output directory
# (default: under the system temporary directory); ARGS= passes other options.
review-eval:
	$(PYTHON) Infrastructure/scripts/review_eval.py run $(if $(OUT),--out $(OUT)) $(if $(filter 1,$(CONFIRM)),--confirm) $(ARGS)

# template-reset scrubs the project-record directories under records/ (plans/, specs/,
# session_logs/, war_rooms/, review_boards/) back to their fresh-template
# baseline (README.md / .gitkeep) before distributing this template into a new
# project. It also removes
# Infrastructure/.template-identity, which re-arms the PROJECT.md title
# requirement in the copy. Pass ARGS="--dry-run" to preview, or ARGS="--yes"
# to skip the confirmation prompt.
template-reset:
	bash Infrastructure/scripts/template_reset.sh $(ARGS)

# port brings this template's machinery into an existing research repository
# (Infrastructure/scripts/port_template.py) on a local branch, and refuses any repository GitHub
# does not report as private. TARGET= the repository folder; MODE=adopt|upgrade overrides the
# detected mode; REF= the template ref to ship (default main); ARGS= other options, such as
# --dry-run or --full-checks.
port:
	$(PYTHON) Infrastructure/scripts/port_template.py "$(TARGET)" $(if $(MODE),--mode $(MODE)) $(if $(REF),--ref $(REF)) $(ARGS)

# --- Researcher lane --------------------------------------------------------------
# These targets exercise the project lane (code/, data/, output/), not the template
# machinery, so maintenance-check does not run them.
.PHONY: pipeline check-project

# pipeline runs the R pipeline from the project root. It never lints.
pipeline:
	Rscript code/run_all.R

# check-project parses every R script under code/, lints code/ with the checked-in
# .lintr (any lint fails; without lintr it prints "SKIPPED: lintr" and continues), and
# then runs the pipeline.
check-project:
	Rscript -e 'r_files <- list.files("code", pattern = "[.][Rr]$$", recursive = TRUE, full.names = TRUE); for (r_file in r_files) invisible(parse(r_file)); message("parse: ", length(r_files), " R file(s) under code/ parse")'
	Rscript -e 'if (!requireNamespace("lintr", quietly = TRUE)) { message("SKIPPED: lintr"); quit(status = 0L) }; lints <- lintr::lint_dir("code"); if (length(lints) > 0L) { print(lints); quit(status = 1L) }; message("lint: no lints under code/")'
	Rscript code/run_all.R

# renv-bootstrap is for teams that opt in to pinned R package versions; the template
# ships no renv.lock or .Rprofile. It runs renv::init(), which scans the project lane
# (.renvignore keeps the template machinery out), builds a project library, reusing
# installed packages where it can, and writes renv.lock, .Rprofile, and renv/. Commit
# those; collaborators then run renv::restore(). It refuses to run when renv.lock
# already exists. lintr is a development tool that renv.lock does not record, so under
# renv run renv::install("lintr") once, or check-project prints "SKIPPED: lintr".
.PHONY: renv-bootstrap
renv-bootstrap:
	Rscript -e 'if (!requireNamespace("renv", quietly = TRUE)) stop("renv is not installed; run install.packages(\"renv\") first", call. = FALSE); if (file.exists("renv.lock")) stop("renv.lock already exists; use renv::restore() or renv::snapshot()", call. = FALSE); renv::init()'

# render builds a Quarto document, by default the optional example drafts/example_brief.qmd,
# whose inline R quotes the pipeline's tables, so run `make pipeline` first. QMD= names
# another document, for a project that replaced the example. Quarto is optional: without it
# the target prints "SKIPPED: quarto not installed" and exits 0. A missing QMD exits 1. The
# rendered HTML sits beside its source and is ignored by git.
QMD ?= drafts/example_brief.qmd
.PHONY: render
render:
	@if ! command -v quarto >/dev/null 2>&1; then \
		echo "SKIPPED: quarto not installed"; \
	elif [ ! -f "$(QMD)" ]; then \
		echo "render: $(QMD) not found; pass QMD=drafts/<file>.qmd" >&2; exit 1; \
	else \
		quarto render "$(QMD)"; \
	fi
