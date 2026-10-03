---
load: referenced
---

# Review Contract

This contract is what every review lens shares: how a review finds its inputs and runs the
pipeline, the one severity and confidence scale, what counts as evidence, the refutation step
for serious findings, and which lens owns each check family. Each lens's rulebook adds its
own checks; where the two disagree, this file wins for the topics it covers. The review
workflows (`review-code`, `review-methodology`, `review-numbers`, `review-consistency`,
`review-ai`, `full-review`) and their agents cite it instead of restating it.

## 1. Target and inputs

- The target is the project directory named by the workflow's argument. A workflow that runs
  interactively and got no argument asks for one; a delegated run reports the missing
  argument to its caller.
- Discovery is done by a script, not by hand, so every lens sees the same file set:

  ```
  python3 Infrastructure/scripts/review_manifest.py discover <target> [--include ROOT]...
  ```

  It prints a JSON manifest: the resolved pipeline, `code_files`, `document_files`,
  `unsupported_files`, and the exclude list it applied. The include roots default to `code/`
  and `drafts/`; pass `--include` for each root when a project keeps code or drafts
  elsewhere (for example `paper/`), and say which roots were used. The exclude list lives in
  the script (`review_manifest.py excludes` prints it) and applies at any depth.
- A file in `unsupported_files` (a `.docx`, for example) is reported to the user with its
  reason and is not reviewed. Ask for an exported `.md`, `.tex`, or `.pdf` instead of
  guessing at its content.
- When the manifest lists no file a lens needs (no code for the code lens, no document for
  the document lenses), report that and skip the lens rather than widening the search.
- When several documents are found, an interactive run asks which to review; a delegated run
  reviews all of them and says so.

## 2. Pipeline

The code, methodology, numbers, and consistency lenses review a project whose pipeline has
just run, because their findings compare code with the outputs it writes. The provenance
lens (`review-ai`) reads files statically and does not need the run.

- Entry point, first match wins: a `pipeline:` line in the target's `PROJECT.md` (for
  example `- pipeline: code/run_all.R` under Working agreements), then a run-all script at the
  top level, then one in `code/`. The script owns the file names and interpreters: `bash`,
  `stata-mp` or `stata-se` (or `stata`) in batch mode, `Rscript`, and `python3`.
- Run it through the script, which runs from the project root under a timeout and states the
  job tier (`Infrastructure/rules/performance-cost-governance.md`):

  ```
  python3 Infrastructure/scripts/review_manifest.py run <target> [--timeout SECONDS]
  ```

  The default timeout is 900 seconds (Tier 2). For a pipeline known to take longer, pass a
  longer timeout; over 60 minutes (Tier 4) the script refuses without `--confirm-tier4`,
  which needs a human's confirmation, so a delegated run stops and reports instead.
- The script records the run in `<target>/review-reports/pipeline-run.json` (exit code,
  tier, timeout, duration, input hash, output fingerprint, log tail) and reuses a successful
  run while both hold, so `full-review` and a series of single reviews run the pipeline once.
  The hashed inputs are the pipeline script; every code file (`.py`, `.R`, `.Rmd`, `.qmd`,
  `.do`, `.ado`, `.sh`) anywhere in the target outside the exclude list, `output/`, and
  `data/processed/`; `PROJECT.md` and `renv.lock`; every file under `data/` except
  `data/processed/`, following symlinked folders; and every file under
  `Infrastructure/style/themes/`, which the code sources for figures. The fingerprint covers `output/` without its run logs, so deleted or
  edited outputs rerun the pipeline. Pass `--force` only when something outside these
  changed, such as a system package or an external data source.
- Exit 0: continue. Exit 1 (failed or timed out): show the printed log tail, tell the user to
  fix the pipeline, and stop before spawning any reviewer. Exit 2 (no pipeline, missing
  interpreter, Tier 4): report the message and stop.

## 3. Severity and confidence

Severity is the impact if the finding is true. Confidence is how likely it is to be true.
Rate them separately: a serious but unconfirmed concern is HIGH with medium confidence, not
MEDIUM.

| Severity | Meaning |
|---|---|
| CRITICAL | A headline result is wrong in a way that changes its conclusion, or the pipeline cannot produce it |
| HIGH | A result, estimate, or claim is materially misstated, biased, or unsupported |
| MEDIUM | A result could change, or a reader could be misled, under plausible conditions |
| LOW | A limitation worth recording that does not change a result |
| SUGGESTION | Code lens only: efficiency or readability, no correctness impact |
| QUESTION | No severity: something the reviewer could not determine; see §5 |

| Confidence | Meaning |
|---|---|
| high | Shown by command output, package documentation, or quoted code or text that exhibits the problem |
| medium | Strong reading of the code or text, not confirmed by running or by a source |
| low | Plausible only; report it as a QUESTION, not a finding |

- Overall risk for a report is the highest severity among its high-confidence findings,
  alongside the count of HIGH and CRITICAL findings that are not high confidence
  ("unconfirmed"). One unconfirmed finding never turns a whole report red.
- No "when in doubt, flag" and no "choose the higher severity" defaults: when unsure, lower
  the confidence, not the bar.

## 4. Evidence

Every finding carries evidence, because a finding the author cannot check costs more trust
than it earns:

- **Claim:** what is wrong, in one sentence.
- **Found:** what the reviewer saw, with file and line, and the exact code or text quoted.
- **Verified by:** how it was checked: a command and its output, a documentation page, or the
  quoted lines themselves when they show the problem.
- A finding about something missing (no weight, no deflator, no disclosure) says where the
  reviewer looked, by file and section, since absence is only as good as the search.

Quote, do not paraphrase: the quoted text is also what gives a finding a stable identity
across runs once the renderer assigns IDs.

## 5. Verify HIGH, and Questions

- Before reporting any HIGH or CRITICAL finding, try to refute it: look for the code that
  handles the case elsewhere, the documentation of the default in question, or the text that
  discloses the choice. Record what was tried. A refuted finding is dropped; one that cannot
  be settled either way becomes a QUESTION with the reason.
- `full-review` adds an independent refutation pass by the owning lens for every HIGH and
  CRITICAL finding after the lenses finish: `Infrastructure/scripts/review_consolidate.py`
  merges duplicates across lenses, queues each HIGH and CRITICAL finding for its agent, and
  turns a refuted one into a QUESTION with the reason.
- Questions for the author hold what the reviewer could not determine (an unknown cluster
  count, an undocumented variable, a design it cannot infer) and every low-confidence
  concern. A question has no severity and does not count toward risk. Not knowing is not a
  finding.

## 6. Lens ownership

Each check family has one owning lens. The others defer: they do not report it, and when they
notice it they add at most a cross-reference to the owner's check family. This keeps one
issue from arriving three times.

| Lens (prefix) | Workflow | Owns |
|---|---|---|
| Code (CE) | `review-code` | Code correctness: crashes, wrong logic, joins and their cardinality, missing-value handling, type coercion (leading zeros), randomness and seeds, efficiency suggestions |
| Methodology (MR) | `review-methodology` | Research design and identification, inference and clustering, specification, survey weights, deflators and seasonal adjustment, survey and sampling error, multiple testing |
| Numbers (DN) | `review-numbers` | Each number in a document against the output that produced it, arithmetic and transformations (log points to percent), rounding, internal consistency between text and tables |
| Consistency (CC) | `review-consistency` | Claims against what the code means: sample and universe descriptions, causal wording, variable definitions, percent vs. percentage points, and undisclosed choices, kept as one assumption ledger merged with any war-room `assumption_export` |
| Provenance (AS) | `review-ai` | Citations and the findings attributed to them, external figures (for example a BLS number) against their source, whether functions and dataset variables exist, comment-code fidelity, and edge-case tests that show an operation feeding a reported result fails (the same bug found by reading the code is CE's) |

Examples of deferral: an undocumented sample filter is CC's undisclosed choice, not a
separate MR or AS finding; a weight that is missing is MR's, while a comment that says the
data are weighted when the code is not is AS's; a significance claim that misreads the table
is DN's arithmetic when the number is wrong and CC's when the wording is.

## 7. Scratch and output

- Reviewers are read-only on the target: they never modify code, data, or documents. The only
  place they write is `<target>/review-reports/`, and scratch scripts, test data, and their
  outputs go in `<target>/review-reports/_scratch/`, which git ignores along with the reports.
- On Claude, each review agent's frontmatter declares a `PreToolUse` hook on
  `Write|Edit|NotebookEdit` that denies any path outside a `review-reports/` directory
  (`Infrastructure/scripts/hooks/guard_review_write.py`, tested by `test_hooks.py`). It allows
  any directory named `review-reports`, at any depth, so a write to a `review-reports` folder inside `code` in
  the project passes; and like every command hook it fails open: if `python3` is missing or
  the script cannot import its helper, Claude runs the tool. Two further gaps remain: a
  `Bash` command can still write elsewhere, so the agents that hold Bash keep their
  scratch work in `_scratch/` by instruction; and Codex has no per-agent hook, so a Codex
  reviewer relies on this rule and its sandbox.
- Each lens's report file and format are named by its workflow and agent.
- Structured findings follow `Infrastructure/templates/review-findings.schema.json`, one
  file per lens (`<target>/review-reports/<lens>.findings.json`), and
  `Infrastructure/scripts/render_review_report.py` renders them: it validates each file,
  assigns stable IDs, computes counts and overall risk, and writes the lens report and
  `index.html`. IDs, counts, and risk are never written by hand; a file the renderer
  rejects is fixed and rendered again.
- **A second round after fixes.** A single-lens workflow writes over its lens's earlier files,
  and the index keeps rendering every other lens file it finds. Before re-reviewing, move the
  earlier round's files into `<target>/review-reports/round<N>/`; the renderer reads only the
  top folder, so the archive stays out of the new index. Give the fresh reviewer the earlier
  findings file and ask it to report each earlier finding as fixed, partly fixed, or not
  fixed, re-raising an unfixed one with the same check id, file, and quote so its ID carries over. `full-review`
  sets earlier findings aside itself (`review_consolidate.py start`).
