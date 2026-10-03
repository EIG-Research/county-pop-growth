---
name: full-review
description: "Run every applicable review lens (code, methodology, numbers, consistency, provenance) on a target project in two phases: the lenses in parallel, then consolidation that merges duplicates, cross-links related findings, and has each HIGH or CRITICAL finding re-checked by its owning agent, rendered as one index in <target-dir>/review-reports/. Use for a complete review before a draft circulates."
argument-hint: "[target-dir] [lenses]"
allowed-tools: ["Read", "Grep", "Glob", "Agent", "Bash(mkdir -p *)", "Bash(python3 Infrastructure/scripts/review_manifest.py discover *)", "Bash(python3 Infrastructure/scripts/review_consolidate.py *)", "Bash(python3 Infrastructure/scripts/render_review_report.py *)"]
---

# Workflow: full-review

Runs the review lenses on one project and consolidates their findings. It is done when
`<target>/review-reports/index.html` and one report per lens that ran are rendered from
consolidated findings, every HIGH or CRITICAL finding has been re-checked by its owning agent
(or is listed as not rechecked), and the summary in step 10 is reported.

`Infrastructure/rules/review-contract.md` owns discovery, the pipeline run, severity and
confidence, evidence, lens ownership, and where files go. Each lens's agent owns its checks.
`Infrastructure/scripts/review_consolidate.py` owns merging, cross-linking, the refutation
queue, and applying verdicts; `Infrastructure/scripts/render_review_report.py` owns the HTML.

| Lens | Agent | Findings file | Runs when |
|---|---|---|---|
| Code (CE) | `code-reviewer` | `code.findings.json` | code files found |
| Methodology (MR) | `methodology-reviewer` | `methodology.findings.json` | code files found |
| Numbers (DN) | `data-consistency-reviewer` | `numbers.findings.json` | documents found |
| Consistency (CC) | `conceptual-consistency-reviewer` | `consistency.findings.json` | documents found |
| Provenance (AS) | `ai-skeptic` | `provenance.findings.json` | code or documents found |

## Setup

1. **Target.** The first argument is the project directory; expand `~`. With no argument, ask
   for one in an interactive session; a delegated run reports the missing argument and stops.
   Stop if the path is not a directory.
2. **Lenses.** A second argument narrows the run to the lenses it names, comma-separated, by
   lens name or prefix (`code,numbers` or `CE,DN`); otherwise every applicable lens runs.
   Name any requested lens that cannot run and why.
3. **Pipeline.** Run `python3 Infrastructure/scripts/review_manifest.py run <target>` (contract
   §2) when any lens other than provenance will run. On a non-zero exit, show its message and
   stop before spawning any reviewer.
4. **Discover.** Run `python3 Infrastructure/scripts/review_manifest.py discover <target>`,
   adding `--include <root>` for code or drafts kept outside `code/` and `drafts/` (contract
   §1). Report each unsupported file with its reason. With neither code nor documents, say so
   and stop.
5. **Context.** In an interactive session, ask once, in one message: which documents to check
   when there are several, and, optionally, the identification strategy, treatment and outcome
   variables, and clustering level. A delegated run checks every document, infers the design,
   and says so.

## Phase 1: the lenses, in parallel

6. Create `<target>/review-reports/` and run `python3
   Infrastructure/scripts/review_consolidate.py start <target>/review-reports`, which moves the
   previous run's findings aside so no stale lens is consolidated. Then spawn every applicable
   agent at once, each with the target, its files from the manifest (code files, the selected
   documents, or both, as its agent file lists), and the research context for the methodology
   and consistency lenses. One agent's failure does not stop the others; record it.
7. When all have returned, run `python3 Infrastructure/scripts/render_review_report.py
   <target>/review-reports --check`. For each file it rejects, send the owning agent the
   renderer's message once to fix the file. If a file is still rejected, go on without that
   lens (step 8 sets it aside) and report it as failed.

## Phase 2: consolidation and refutation

8. Run `python3 Infrastructure/scripts/review_consolidate.py consolidate
   <target>/review-reports --set-aside-invalid`. It merges duplicates (same file, anchor, and
   check family, and within one lens the same title or claim; the owner lens's finding is kept), cross-links related findings in `related`,
   and writes the refutation queue to `review-reports/_scratch/refute-queue.json`: each HIGH
   and CRITICAL finding with its ID and owning agent.
9. For each agent with queued findings, spawn it again, in parallel, with this task instead of
   a review: "Independent refutation pass. For each finding ID listed for your lens in
   `<target>/review-reports/_scratch/refute-queue.json`, read the finding in its findings file
   and try to disprove it from the project itself: code that handles the case elsewhere, the
   documentation of the default in question, or text that discloses the choice. Do not rely on
   the first pass's reasoning. Write
   `<target>/review-reports/_scratch/refutations/<LENS>.json` as `{"verdicts": [{"id": ...,
   "verdict": "refuted" or "upheld", "reason": ...}]}`, one verdict per listed ID, and change no
   other file." Then run `python3 Infrastructure/scripts/review_consolidate.py apply
   <target>/review-reports`: a refuted finding becomes a Question for the author with the
   reason; an upheld one keeps its severity.

## Render and report

10. Run `python3 Infrastructure/scripts/render_review_report.py <target>/review-reports`, then
    report:
    - the index path, and one row per lens: ran, failed, or skipped (with why), and its
      renderer summary line (counts, overall risk, unconfirmed HIGH findings);
    - the consolidation line (duplicates merged, cross-links) and the apply line (refuted,
      upheld, not rechecked);
    - one line per remaining HIGH or CRITICAL finding: ID, title, and file with line.

## Input

Invoke as `/full-review [target-dir] [lenses]`.

Arguments: $ARGUMENTS
