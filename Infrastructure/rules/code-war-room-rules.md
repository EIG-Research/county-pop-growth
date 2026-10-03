---
load: referenced
---

# Code War Room Rules

Binding rules for the `code-war-room` workflow and the `code-interlocutor` agent. A war room
walks one script block by block with its author: the agent's reading of each block comes
first, and the difference is recorded as the author's intent and assumptions, a work order,
and an assumption export. The scripts (`Infrastructure/scripts/war_room_*.py`) segment, hash,
re-anchor, record drift, resolve the project root, serve the app, and render; never do those
by hand, edit a range or hash, or store a project root. Their rules (WR-S1, S2, S6, S7, A1 to
A5, C2, C3, C5, Q1 to Q10, O2, O3, O7) are in `Infrastructure/rules/code-war-room-design.md`.

## Prediction First

**WR-P1 — Predictions are written during prep, before any human input**: for every block, a
plain-language reading, the inferred intent, the assumptions carried forward, and a
confidence, persisted to `ledger.yaml` before the walkthrough opens. Only `war_room_prep.py
finalize` sets `session.prep_completed`, once every block has a `title`, a `density`, and a
`prediction` with a confidence from the closed set; the app server refuses a ledger without it.

**WR-P2 — The walkthrough reads predictions; nothing re-derives them.** A prediction
generated at walkthrough time drifts toward what the author just said, which destroys the
only evidence this workflow produces.
**WR-P3 — Predictions are immutable once persisted.** Never edit, soften, or retrofit the
text, in the app, in reconcile, or when rendering; record a divergence. The one exception is
a merge or split under WR-S5, which yields an explicitly inherited, lower-confidence prediction.

**WR-P4 — Agreement is recorded explicitly.** A matched block gets `match: true` and a
one-line justification from reconcile. An unset divergence is not a match; it is unreconciled.
**WR-P5 — The agent is not present during the walkthrough.** The author answers in the local
app, and no agent output is produced between a block opening and its answer being saved.

**WR-P6 — Confidence is stated before the answer, never revised, and honestly distributed.**
It is your certainty, not the code's quality; a `low` stays `low` even if it proves right. A
prep pass with no `low` that admits judgment calls it cannot settle is miscalibrated.

| Situation | Maximum confidence |
|---|---|
| Intent rests on something outside the code (skip logic, an external spec, a data dictionary, a downstream label) | `medium` |
| Two readings are plausible and the code does not distinguish them | `low` |
| Correctness depends on a fact in a file you have not read | `low` |

**The four questions**, asked of the agent first: what the block does (simplest accurate
language); what it is meant to do (only the author knows); why it is done this way ("I don't
remember" is valid, recorded verbatim); and what it assumes downstream, the highest-value field.

## Blocks

**WR-S3 — Never split an atomic operation**: a filter and its condition, a model call and its
options, a `preserve`/`restore` pair stay in one block even when long.
**WR-S4 — Small blocks are allowed and often the point.** A lone `filter(x >= 5)` is a block;
the `>=`-versus-`>` conversation is what this workflow surfaces. Do not merge to cut the count.
**WR-S5 — Segmentation is proposed, not imposed.** Merge and split happen on the app's block
map, shown before the first unanswered block in every mode, or with `war_room_prep.py merge`
and `split`, never by editing a range. Each edit is recorded in `session.segmentation_edits`,
affected blocks are rehashed, and an inherited prediction is marked lower-confidence, because
the agent committed to the original boundaries. A block with a disposition cannot be re-segmented.

## Dispositions, Coverage, and Density

Every block ends with exactly one disposition from this closed set.

| Disposition | Meaning |
|---|---|
| `confirmed` | The reading matched the author's intent and the code does what it should. |
| `misread-by-agent` | The prediction was wrong and the code is correct: a calibration failure, not a defect. |
| `needs-change` | The code does not do what the author intended, or the author decided to change it. The only source of actionable work-order items. |
| `unresolved` | The author could not say, or the answer needs information not in the room; carried forward as an open question. |

**WR-D1 — `misread-by-agent` is a first-class outcome.** A cluster of misreads marks code a
careful reader misunderstands, a real finding even when every line is correct.
**WR-D2 — `unresolved` means information is missing**, never a way to end a hard exchange.
**WR-C1 — Ordered is the default**: file order, never by severity, interest, or density.
**WR-C4 — Never fast-forward a `high`-density or `low`-confidence block**; those need a human.

Score density in prep; it orders attention and never drops a block. **High:** sample
restrictions and filters, weights, variable construction or recoding, model specification,
joins, missing-data handling, hard-coded constants, thresholds, or cutoffs, and boundary
conditions (`>` versus `>=`). **Medium:** reshapes and aggregations, column selection, type
coercion, result-affecting sort order, formatting that encodes a rounding or unit decision.
**Low:** library loads, path setup, logging, comments, plain I/O.
**WR-N1 — When uncertain, score higher**: a block wrongly scored `low` can be fast-forwarded
past its own defect.

## Review Fleet and Registry

**WR-I1 — Read existing review reports in `<target>/review-reports/` during prep** to seed
questions and raise density. Their absence is normal. **WR-I2 — Findings never become
predictions**: store them in `evidence.existing_report_findings`, attributed to the agent
and finding id. **WR-I2a — Treat reports as possibly stale**: if a report's line count or
file hash differs from the file, cite findings by id only and record the mismatch in
`evidence.assumptions`.
**WR-I3 — Export stated assumptions on close**, each with its block id, text, and whether the
author confirmed it, for `ai-skeptic` and `methodology-reviewer`. **WR-I4 — An exported
assumption is author-stated, not verified**; downstream reviewers test it as a claim.
**WR-I5 — Downstream reviewers locate a ledger by slug, then confirm it.** It lives at
`records/war_rooms/<slug>/ledger.yaml` (WR-X2) in the repository the war room ran
from, which for a project built from this template is its own `records/war_rooms/`.
Confirm `project.id` (the basename of the project under review) and `script.path`; the
directory name is a hint, not proof, and a ledger naming another project is not evidence
about this one. A missing ledger is normal and never a finding.
**WR-R1 — Only variable selection, exclusion, and weight decisions write back**, and only for
a dataset in `Infrastructure/references/datasets/registry.yaml`. **WR-R2 — Writes go to the
project overlay `data/docs/dataset-registry.yaml` as `layer: project`, `verification: parsed`.**
Promotion to `verified` is a human step even if the author agreed live; the validator rejects it.
**WR-R3 — Confirm each write with the human, showing the exact entry**; no batch writeback.
Prep may stage candidates as `status: pending-confirmation` but never writes; a declined one
is kept as `status: declined` so it is not proposed again. **WR-R4 — Re-run the validator
after every write**, and revert and report on failure. **WR-R5 — Never invent a variable,
universe, or weight**; record unconfirmed values as `[unverified: ...]`.

## Read-Only

**WR-X1 — Never edit the code under review.** Changes come later from the work order, so each
traces to a recorded decision.
**WR-X2 — Write only to** `records/war_rooms/<slug>/`, the rendered report under
`<target>/review-reports/war-room/`, and, under WR-R1 to R5, the project's dataset overlay.
The slug is undated and namespaced by project (`my-project--code--02_build_sample.R`); take
it from `war_room_prep.py locate`, never build it by hand. Dates live in `session.history[]`.
**WR-X3 — Create no other file inside the reviewed project, not even a temporary one.**
Intermediates (converted reports, snippets, grep dumps, notes) go in the session scratch
directory outside both repositories; deleting a stray file does not undo the breach.
**WR-X4 — Never use `git status` alone to confirm the project is untouched**: it cannot see
gitignored paths such as `review-reports/`, `output/`, and `data/raw/`. Check a direct
listing of every directory read or written, their mtimes (which reveal a create-and-delete),
and `git status --porcelain`. List `<target>/review-reports/war-room/` before and after: the
report may be its only new entry. Report the filesystem result, and disclose any stray file
even after deleting it, naming the check that found it.

## Evidence and Outputs

Per `AGENTS.md` (Guardrails, Data and evidence), ledger entries carry claims and therefore evidence.
**WR-E1** — every prediction carries its confidence. **WR-E2** — every assumption names its
block id and whether it came from the agent, the author, or a review report. **WR-E3** — keep
observation ("keeps rows with `age >= 25`") and interpretation ("meant to restrict to
prime-age workers") in separate fields. **WR-E4** — mechanical entries may skip evidence.
**WR-O1 — `ledger.yaml` is the source of truth**; `ledger.md` and the HTML report are
rendered from it and may be regenerated at any time.
**WR-O4 — The work order holds actionable `needs-change` items plus `unresolved` items
rendered as `blocked`, which a coding agent must not implement.** It is usable without the
ledger; a `blocked` item names its blocker and is implemented only after that clears.

**WR-O5 — The templates are binding, and scripts write every rendered file**:
`war_room_render.py` writes `ledger.md` and the HTML report, and `war_room_reconcile.py
--write` writes `work-order.md`, from `Infrastructure/templates/war-room-ledger.md`,
`war-room-report.md`, and `war-room-work-order.md`. Never hand-write or patch one; correct
`ledger.yaml` and re-render.
**WR-O6 — Two reviewers share one ledger**, edited on separate branches; a git conflict on a
block is the intended signal that two people read the same code differently. Keep one entry
and move the other answer into its `dissent[]` (`reviewer`, `answered_at`, `disposition`,
`author_account`, `endorsed_prediction`); never discard an answer or add a second entry for
the `block_id`. `records/war_rooms/README.md` shows an example.
