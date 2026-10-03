---
name: review-methodology
description: >-
  Run the methodology review on a target project: runs the pipeline, spawns the methodology-reviewer agent, and renders its validated findings as methodology-report.html and index.html in <target-dir>/review-reports/. Use when checking research design and inference.
---

# Workflow: review-methodology

Runs the methodology lens on one project. It is done when
`<target>/review-reports/methodology-report.html` and `index.html` are rendered from a findings
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
4. **Context.** In an interactive session, offer once to take the identification strategy,
   treatment and outcome variables, and clustering level; each may be skipped. A delegated run
   skips this and the agent infers them.
5. **Review.** Create `<target>/review-reports/` and spawn `methodology-reviewer` with the
   target, the code files, and any context.
6. **Render.** Run `python3 Infrastructure/scripts/render_review_report.py
   <target>/review-reports`, which renders every findings file there and the index. If it
   rejects a file, send the owning agent the renderer's message to fix and render again; after
   a second rejection, report the message and stop.
7. **Report.** Give the report path, the renderer's summary line for the lens (counts, overall
   risk, unconfirmed HIGH findings), the inferred design, and one line per HIGH or CRITICAL
   finding.

## Input

Mention `$review-methodology` with the details in the same message, pick the skill by name, or simply describe the task. Treat the invoking message as this workflow input.
