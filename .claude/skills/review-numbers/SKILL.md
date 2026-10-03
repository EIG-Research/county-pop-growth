---
name: review-numbers
description: "Run the document number verification review on a target project: runs the pipeline, spawns the data-consistency-reviewer agent, and renders its validated findings as doc-number-report.html and index.html in <target-dir>/review-reports/. Use when checking a draft's numbers against the analysis."
argument-hint: "<target-dir> [document-path]"
allowed-tools: ["Read", "Grep", "Glob", "Agent", "Bash(mkdir -p *)", "Bash(python3 Infrastructure/scripts/review_manifest.py discover *)", "Bash(python3 Infrastructure/scripts/render_review_report.py *)"]
---

# Workflow: review-numbers

Runs the numbers lens on one project. It is done when
`<target>/review-reports/doc-number-report.html` and `index.html` are rendered from a findings
file the renderer accepted, and the summary below is reported. Discovery, the pipeline run,
severity, and where files go follow `Infrastructure/rules/review-contract.md`.

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
4. **Review.** Create `<target>/review-reports/` and spawn `data-consistency-reviewer` with the
   target, the documents, and the code files.
5. **Render.** Run `python3 Infrastructure/scripts/render_review_report.py
   <target>/review-reports`, which renders every findings file there and the index. If it
   rejects a file, send the owning agent the renderer's message to fix and render again; after
   a second rejection, report the message and stop.
6. **Report.** Give the report path, the renderer's summary line for the lens, the extraction
   counts from the findings file's `context`, and one line per HIGH or CRITICAL finding.

## Input

Invoke as `/review-numbers <target-dir> [document-path]`.

Arguments: $ARGUMENTS
