---
name: review-code
description: >-
  Run the code error review on a target project: runs the pipeline, spawns the code-reviewer
  agent, and renders its validated findings as code-error-report.html and index.html in
  <target-dir>/review-reports/. Use when checking analysis scripts for bugs.
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

# Workflow: review-code

Runs the code lens on one project. It is done when
`<target>/review-reports/code-error-report.html` and `index.html` are rendered from a findings
file the renderer accepted, and the summary below is reported. Discovery, the pipeline run,
severity, and where files go follow `Infrastructure/rules/review-contract.md`.

1. **Target.** The argument is the project directory; expand `~`. With no argument, ask for one
   in an interactive session; a delegated run reports the missing argument and stops. Stop if
   the path is not a directory.
2. **Pipeline.** Run `python3 Infrastructure/scripts/review_manifest.py run <target>` (contract
   §2). On a non-zero exit, show its message and stop before spawning the reviewer.
3. **Discover.** Run `python3 Infrastructure/scripts/review_manifest.py discover <target>`,
   adding `--include <root>` for code kept outside `code/` (contract §1). Report each
   unsupported file with its reason. With no code files, say so and stop.
4. **Review.** Create `<target>/review-reports/` and spawn `code-reviewer` with the target and
   the code files.
5. **Render.** Run `python3 Infrastructure/scripts/render_review_report.py
   <target>/review-reports`, which renders every findings file there and the index. If it
   rejects a file, send the owning agent the renderer's message to fix and render again; after
   a second rejection, report the message and stop.
6. **Report.** Give the report path, the renderer's summary line for the lens (counts, overall
   risk, unconfirmed HIGH findings), and one line per HIGH or CRITICAL finding.
