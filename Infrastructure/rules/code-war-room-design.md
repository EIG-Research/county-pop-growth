---
load: referenced
---

# Code War Room Design Reference

The mechanics behind `Infrastructure/rules/code-war-room-rules.md`, for whoever changes the
war-room scripts, app, templates, or tests. A war-room session does not read this file: the
scripts in `Infrastructure/scripts/war_room_*.py` enforce everything here, and
`Infrastructure/scripts/test_war_room.py` checks it. Each rule keeps the id the scripts and
tests cite. The segmentation algorithm itself is `Infrastructure/rules/code-war-room-segmentation.md`.

## Block Segmentation

**WR-S1 — A block is a unit of intent, not a fixed line count.** Segment where the purpose
changes, not every N lines.

**WR-S2 — Language-specific boundaries.** Prefer, in order: an explicit section comment
header; a function or macro definition; a complete pipe or chain expression; a contiguous
run of statements separated from neighbours by blank lines.

| Language | Primary boundary signals |
|---|---|
| R (`.R`, `.Rmd`, `.qmd`) | `# ---` / `# ===` section headers, `function(...)` definitions, complete `%>%` or `\|>` chains, `{...}` blocks |
| Python (`.py`) | `def` / `class`, decorator groups, top-level statement runs, cell markers (`# %%`) |
| Stata (`.do`, `.ado`) | `program define`, `*` comment headers, `preserve`/`restore` pairs, a complete estimation command with its options |

These signals are not applied by judgment at prep time. The prep script
(`Infrastructure/scripts/war_room_prep.py`) implements them as the deterministic procedure in
`code-war-room-segmentation.md`, and the language is detected from the file extension. An
agent does not propose boundaries; it reads the ones the script produced, and they may be
merged or split under WR-S5. Some signals in the table are protective rather than generative:
a `preserve`/`restore` pair and a complete chain do not open a block, they forbid a cut inside
one (segmentation step 7).

**WR-S6 — A leading comment attaches to the code below it.** A section comment documents what
follows, so it belongs to that block rather than forming a comment-only block. The exception
is a file header that documents the whole script, which stands alone. Without this rule,
three prep runs over the same 105-line file produced 27, 29, and 30 blocks, mostly from comment
attachment. Determinism matters because the multi-reviewer merge (WR-O6) assumes two
reviewers produce comparable `block_id`s; divergent segmentation yields two disjoint block sets
instead of the intended conflict. Comment attachment is a step of the algorithm (step 8), so
it is a property of the prep script rather than of the reader.

**WR-S7 — Blank separator lines belong to no block.** Do not pad a block's range to make
coverage contiguous. Every non-blank line must sit in exactly one block; blank lines between
blocks sit in none. A blank line inside an open construct is not a separator and stays in its
block: an open bracket, a string or docstring, an indented Python body, and in Stata a
`preserve`/`restore` pair, a `/* */` block comment, or a `#delimit ;` region (segmentation
step 4). Splitting there would cut an atomic operation (WR-S3). The lint pass checks the
coverage property directly whenever the source file resolves under the project root, so a
hand-edited range that double-counts or drops a line fails a gate rather than surviving into
the ledger. Lint counts only non-blank lines, so a ledger segmented before this amendment
stays valid.

## Block Anchoring

**WR-A1 — Every block carries a SHA-256 of its source text**, plus file path and the line
range captured at prep time. The hash must reproduce exactly across agents, platforms, and
checkouts with different line endings, or resume and drift detection silently fail, so "the
exact source text" is this algorithm and no other:

```
1. Read the file as UTF-8.
2. Split into lines, discarding the line terminators (\r\n and \n both).
3. Take lines[start-1 : end] for the block's recorded 1-indexed inclusive range.
4. Join them with "\n". Do not append a trailing newline.
5. Encode UTF-8, SHA-256, lowercase hex, all 64 characters.
```

Hash the whole file for `script.sha256` the same way: every line of the file joined with
`\n`, no trailing newline. Do not preserve CRLF, include a trailing newline, hash raw bytes as
read, or truncate the digest: each is a defensible reading of "exact source text" and each
produces a different hash, which is why the algorithm is pinned. Record the full 64-character
digest; abbreviations belong in rendered output, never in `ledger.yaml`.

The algorithm is implemented once, in `Infrastructure/scripts/war_room_lib.py`: `wr_a1_hash`,
fed by `wr_a1_lines`, and `wr_a1_file_hash` for `script.sha256`. The prep script, the app
server, the lint pass, reconcile, and the renderers all call it. The library's docstring
states the same steps, and a divergence between the two is a defect in this repository.

**WR-A2 — Re-anchor by hash on resume, never by line number.** Line ranges shift whenever
the file is edited. Locate a block by its content hash first; use the stored line range only
as a search hint.

**WR-A3 — Report drift; never silently remap, and persist what you found.** Drift is a
recorded field, not a message on a console. Exactly two writers set it: the prep script's
`verify --write` command, and the app server on every save. Both call `recompute_drift` in the
shared library, with these semantics, and no other code decides drift:

```
If the block's recorded range still hashes to its `sha256`:
    `drift` is false, and the block owns that range.
Otherwise, if an identical hash is found at exactly one contiguous range in the same
file that overlaps no range another block owns:
    update `lines` to that range, record `relocated_from: [old start, old end]`,
    and leave `drift` false — re-anchoring under WR-A2 is not drift. The block now
    owns that range. Grant every such match in one pass against the same ownership,
    except matches that overlap each other in that pass, and repeat until no match
    is granted.
Otherwise (no free match, more than one, or an overlapping match in the same pass):
    set `drift: true`, leave `lines` untouched, and surface the block to the human
    with both the recorded and the current line ranges.
```

Choosing between two identical ranges would be a silent remap, so an ambiguous match is
drift. `relocated_from` stays until the human runs `verify --accept-relocations`, which
clears it and re-stamps `script.sha256` once no block drifts and lint passes.

Attaching a prior discussion to changed code is worse than losing it. The server recomputes
drift for every block on every save, so a file edited mid-session produces a flagged block
rather than a failed save. An edit that touches no block, such as lines appended after the
last block, changes only `script.sha256`; lint then reports coverage and the whole-file hash
as warnings rather than failures, so the save succeeds and the next `verify --write` or
re-segmentation can account for the new lines.

**WR-A4 — Changed-after-disposition is a regression signal.** When a block that already
carried a disposition drifts, the same two writers also set `drift_after_disposition: true`:
the decision reached in the room no longer describes the code. Neither writer ever clears
that flag — only a human editing the ledger does — so the signal survives every later save.
Reconcile and the renderers read the persisted flags and never recompute drift, which keeps
the console note, the rendered banner, and the ledger saying the same thing.

**WR-A5 — The project root is resolved at run time and never stored.** The ledger records
`script.path`, project-relative, and `project.id`, the basename of the reviewed project's
root at prep time. It never records an absolute `project_root`. Every script that reads the
source resolves the root in this order and no other:

```
1. The explicit `--project-root <dir>`, when it is given; it must contain `PROJECT.md`
   and its basename must equal the ledger's `project.id`.
2. Otherwise, walk upward from the CURRENT WORKING DIRECTORY -- never from the ledger's own
   directory, which lives in the runner's repository rather than in the reviewed project --
   to the nearest directory containing `PROJECT.md`, and accept that directory only if its
   basename equals the ledger's `project.id`.
3. Otherwise, exit with an error naming the `--project-root` flag.
```

`script.path` must then resolve under that root, and nothing else is tried. A same-named file
found elsewhere is never used: a basename search can hash a decoy and record the digest as if
it were the reviewed script, which makes every later drift check meaningless.

## Coverage Mechanics

**WR-C2 — Fast-forward is opt-in and per-session, and it happens on the block map.**
`session.mode: fast-forward`, written only by `war_room_prep.py skeleton --mode fast-forward`,
turns on the block map's batch-confirm selector. Blocks scored as mechanical are then
confirmed together from that screen, before the walkthrough begins. The selector posts to the
server's `/api/fast-forward` endpoint, the only writer of a batch-confirmed entry.

**WR-C3 — A fast-forwarded block is recorded, not skipped.** It gets a full entry with its
prediction, `discussed: false`, `disposition: confirmed`, `endorsed_prediction: true`, and the
`reviewer` and `answered_at` of whoever confirmed the batch. The ledger accounts for every
block, and a batch confirmation endorses the recorded prediction and its assumptions (WR-Q8).

WR-C4 is enforced twice: the batch selector pre-selects only blocks whose density is `low`
and whose confidence is above `low`, and `/api/fast-forward` refuses a high-density block, a
low-confidence block, a block that already carries a disposition, and any batch on a ledger
whose `session.mode` is not `fast-forward`, saving nothing. The selector is a suggestion; the
endpoint is the gate, so a hand-built request cannot do what the screen will not offer.

**WR-C5 — Surface density scores before fast-forwarding.** The block map lists every block
with its line range, title, density, prediction confidence, and current disposition.
Pre-selection is a proposal: the author deselects any block and walks it instead. A batch is
all-or-nothing — if any selected block is ineligible the whole request is refused and named.

## The Walkthrough App

The walkthrough runs in a local, loopback-bound app (`Infrastructure/scripts/war_room_server.py`
with `war_room_app/`), not in conversation.

**WR-Q1 — One block per screen**, with its source, never a list to react to in bulk.
**WR-Q2 — Show progress**: block N of M, and how many carry a disposition.

**WR-Q3 — Persist on every save.** The ledger is written atomically after each answer, so the
window can be closed at any point; the block on screen is the only unsaved state. Every
timestamp a war-room script writes — `session.prep_completed`, `session.reconciled`, each
`session.history[].at`, and each block's `answered_at` — is UTC ISO 8601 with microseconds,
because ordering is compared strictly and seconds cannot separate two events in one run.

**WR-Q4 — The prediction renders read-only, beside empty author fields.** Never pre-fill or
summarize the prediction into the author's fields, and never place the author's input before
the prediction: reading order carries the protocol.

**WR-Q5 — Ask open questions only.** The field label is "What is it meant to do?", never "Did
you mean X?" or a yes/no confirmation; a leading field manufactures agreement and voids the
divergence record.

**WR-Q6 — Record the author verbatim.** Store exactly what was typed; do not clean up,
summarize, or normalize it, particularly for "why this way".

**WR-Q7 — An endorsement is a deliberate act.** "The prediction is correct and I have nothing
to add" is legitimate and common, and the author need not retype an accurate reading. It is
recorded as an explicit endorsement, never inferred from empty fields, or a careful
confirmation and an unread block would look the same.

**WR-Q8 — Endorsing a prediction endorses its assumptions.** A `confirmed` block with
`endorsed_prediction: true` and no author text means the recorded assumptions are accepted,
and reconcile must promote them into `assumption_export` as `stated_by: agent, confirmed:
true`; skipping that leaves an empty export after a complete review. A `confirmed` block with
neither an endorsement nor an author account is an answer nobody explained: reconcile exports
its assumptions as `confirmed: false`, leaves `divergence.match` null, and lists the block for
agent judgment rather than reading silence as agreement (WR-P4).

**WR-Q9 — Capture reviewer identity in the app.** Every saved entry records who answered;
identity carried over from prep is not the reviewer. The app sends a reviewer id and a role
from the closed set `author` or `fresh-eyes` with every answer. `session.reviewers[]` holds one
`{id, role}` per reviewer, and the server appends one the first time an id appears. Lint
checks every block's `reviewer`, and every `dissent[].reviewer`, against those ids.

**WR-Q10 — The lint pass gates every write.** `Infrastructure/scripts/war_room_lint.py` holds
every schema and integrity check (the `WL-` codes), and its callers run it before anything
reaches disk: the app server after each mutation, reconcile before `--write` and again after
writing, and the renderers before rendering. A server-side failure returns its codes and
persists nothing. Because lint recomputes every hash whenever the source resolves, a
hand-written range or digest cannot pass; a block whose source changed after prep passes only
with `drift: true`, and a whole-file hash change with every block intact is a warning, which
is why drift is persisted rather than printed (WR-A3).

**API contract.** The test suite drives three endpoints, so their shapes are fixed.
`POST /api/answer` takes `{block_id, disposition, endorsed_prediction, flagged, reviewer,
reviewer_role, author: {meant_to_do, why_this_way, assumptions_carried[]}}`.
`POST /api/fast-forward` takes `{block_ids[], reviewer, reviewer_role}`. Both require
`reviewer` and a `reviewer_role` from `author | fresh-eyes` (WR-Q9), append the reviewer to
`session.reviewers[]` the first time an id appears, and append one `walkthrough` entry to
`session.history[]` per reviewer per UTC date (WR-O7). `GET /api/state` returns the script and
session header, the closed sets, `needs_block_map` (true while any block lacks a disposition),
and, per block, `block_id`, `lines`, `title`, `density`, `discussed`, `disposition`, `flagged`,
`drift`, `drift_after_disposition`, `relocated_from`, `endorsed_prediction`, `answered_at`,
`reviewer`, `dissent`, the source text, the recorded `prediction`, and the recorded
`author_account`. The server is authoritative on endorsement: it clears `endorsed_prediction`
whenever an author field carries text, and refuses an endorsement paired with any disposition
other than `confirmed`, saving nothing.

## Ledger Mechanics

**WR-O2 — Exactly one top-level list entry per block, keyed by a stable `block_id`.** No
shared counters or running totals inside block entries, so the ledger stays line-local and a
conflict is confined to the one disputed block (WR-O6). A `block_id` never appears twice in
one ledger and is never renumbered; lint rejects a duplicate.

**WR-O3 — Reviewer identity is recorded per entry**, not once per file, so a merged ledger
still attributes each answer. Every id used on a block or in a `dissent[]` item also appears
in `session.reviewers[]` as `{id, role}` (WR-Q9).

**WR-O7 — Session dates live in `session.history[]`.** The ledger directory carries no date
(WR-X2), so the history list records when the work happened. It has exactly three writers:
`war_room_prep.py finalize` appends `{event: prep, at, by}`; the app server appends `{event:
walkthrough, at, by}` the first time a given reviewer saves an answer on a given UTC date;
`war_room_reconcile.py --write` appends `{event: reconcile, at}`, with no `by` because no
reviewer is present. Nothing else appends to it or rewrites an entry, and lint requires a
non-empty history whenever `session.prep_completed` is set.

`war_room_render.py` reads the report's HTML out of the fenced block in
`Infrastructure/templates/war-room-report.md` at run time, so the template and the renderer
cannot drift apart (WR-O5).

## Rationale for the Operator Rules

- WR-P5: An architecture in which the agent is absent, so there is nothing to fold to, is
  stronger than an instruction not to soften a reading under pushback.
- WR-P6: Trial runs recorded no `low` prediction across 29, 30, and 83 blocks while naming
  unresolvable blocks in the same report; the confidence ceiling exists because of that.
- WR-I2: The field `evidence.existing_report_findings` is named in the rules because agents
  left to invent one chose differently, which made ledgers inconsistent.
- WR-I2a: Trial runs found reports reviewing an 87-line version of a now-105-line file:
  their clean findings did not cover the added lines and their line citations were unusable.
- WR-X4: `review-reports/` is where this workflow reads from, which makes it the likeliest
  place to leave something behind, and `review-reports/war-room/` is the one place WR-X3
  permits a write, so a stray file can hide there behind a legitimate one.
