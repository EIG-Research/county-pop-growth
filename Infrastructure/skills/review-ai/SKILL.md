---
name: review-ai
description: >-
  Run the provenance (AI skeptic) review on a target project: spawns the ai-skeptic agent to
  check citations, external figures, functions, dataset variables, and comments, and renders its
  validated findings as ai-skeptic-report.html and index.html in <target-dir>/review-reports/.
  Does not need a pipeline run. Use when checking the sources and references behind
  AI-assisted work.
argument-hint: "<target-dir>"
allowed-tools:
  - Read
  - Grep
  - Glob
  - Agent
  - Bash(mkdir -p *)
  - Bash(python3 Infrastructure/scripts/review_manifest.py discover *)
  - Bash(python3 Infrastructure/scripts/render_review_report.py *)
---

# Workflow: review-ai

Runs the provenance lens on one project. It is done when
`<target>/review-reports/ai-skeptic-report.html` and `index.html` are rendered from a findings
file the renderer accepted, and the summary below is reported. Discovery, severity, and where
files go follow `Infrastructure/rules/review-contract.md`. The lens reads files statically, so
no pipeline run is needed; its edge-case tests use the data when it is present.

1. **Target.** The argument is the project directory; expand `~`. With no argument, ask for one
   in an interactive session; a delegated run reports the missing argument and stops. Stop if
   the path is not a directory.
2. **Discover.** Run `python3 Infrastructure/scripts/review_manifest.py discover <target>`,
   adding `--include <root>` for code or drafts kept elsewhere (contract §1). Report each
   unsupported file with its reason. With neither code nor documents, say so and stop.
3. **Review.** Create `<target>/review-reports/` and spawn `ai-skeptic` with the target and the
   code and document files.
4. **Render.** Run `python3 Infrastructure/scripts/render_review_report.py
   <target>/review-reports`, which renders every findings file there and the index. If it
   rejects a file, send the owning agent the renderer's message to fix and render again; after
   a second rejection, report the message and stop.
5. **Report.** Give the report path, the renderer's summary line for the lens (counts, overall
   risk, unconfirmed HIGH findings), and one line per HIGH or CRITICAL finding.
