---
name: review-consistency
description: >-
  Run the document-code consistency review on a target project: runs the pipeline, spawns the
  conceptual-consistency-reviewer agent, and renders its validated findings as
  doc-consistency-report.html and index.html in <target-dir>/review-reports/. Use when checking
  that a draft describes what the code does.
argument-hint: "<target-dir> [document-path]"
allowed-tools:
  - Read
  - Grep
  - Glob
  - Agent
  - Bash(mkdir -p *)
  - Bash(python3 Infrastructure/scripts/review_manifest.py discover *)
  - Bash(python3 Infrastructure/scripts/render_review_report.py *)
---

# Workflow: review-consistency

Runs the consistency lens on one project. It is done when
`<target>/review-reports/doc-consistency-report.html` and `index.html` are rendered from a
findings file the renderer accepted, and the summary below is reported. Discovery, the pipeline
run, severity, and where files go follow `Infrastructure/rules/review-contract.md`.

1. **Target.** The first argument is the project directory; expand `~`. An optional second
   argument names the document to check, which must exist. With no argument, ask for the
   directory in an interactive session; a delegated run reports the missing argument and stops.
2. **Pipeline.** Run `python3 Infrastructure/scripts/review_manifest.py run <target>` (contract
   §2). On a non-zero exit, show its message and stop before spawning the reviewer.
3. **Discover.** Run `python3 Infrastructure/scripts/review_manifest.py discover <target>`,
   adding `--include <root>` for code or drafts kept elsewhere (contract §1). Report each
   unsupported file with its reason. Without a named document, use the manifest's
   `document_files`: when there are several, an interactive run asks which to check and a
   delegated run checks all of them and says so. With no document, say so and stop.
4. **Context.** In an interactive session, offer once to take the identification strategy and
   the treatment and outcome variables; each may be skipped. A delegated run skips this.
5. **Review.** Create `<target>/review-reports/` and spawn `conceptual-consistency-reviewer`
   with the target, the documents, the code files, and any context.
6. **Render.** Run `python3 Infrastructure/scripts/render_review_report.py
   <target>/review-reports`, which renders every findings file there and the index. This agent
   has no shell, so this is its validation: if the renderer rejects its file, send the agent
   the message to fix and render again; after a second rejection, report the message and stop.
7. **Report.** Give the report path, the renderer's summary line for the lens, the claim tally
   from the findings file's `context`, and one line per HIGH or CRITICAL finding.
