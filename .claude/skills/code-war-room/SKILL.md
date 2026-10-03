---
name: code-war-room
description: "Walk one analysis script block by block with its author: the agent commits its reading of each block before the author explains, and every divergence, assumption, and decision is recorded to a durable ledger plus a coding-agent work order. Use when an author wants to check what a script they wrote actually does against what they meant it to do."
argument-hint: "<script-path> [--fast-forward]"
allowed-tools: ["Read", "Write", "Edit", "Grep", "Glob", "Agent", "Bash(python3 Infrastructure/scripts/war_room_prep.py *)", "Bash(python3 Infrastructure/scripts/war_room_reconcile.py *)", "Bash(python3 Infrastructure/scripts/war_room_render.py *)", "Bash(python3 Infrastructure/scripts/war_room_lint.py *)"]
---

# Workflow: code-war-room

Walk one analysis script block by block with its author. The `code-interlocutor` agent commits
its reading of every block first, the author answers in a local app, and the difference is
recorded: the author's intent and assumptions, a work order for a coding agent, and an
assumption export for `review-ai` and `review-methodology`. It captures what the author
believes; it does not hunt bugs (the review workflows do), judge methodology, or edit code.

**Done when** the ledger passes `war_room_lint.py` (coverage, hashes, closed sets, reviewer
ids, answers after prep), reconcile has set `session.reconciled` or the blocks without a
disposition are named, `ledger.md`, `work-order.md`, and the report exist, the assumption
export is non-empty if answered blocks carry assumptions (WR-Q8), and the script is unchanged.

Read `Infrastructure/rules/code-war-room-rules.md` before Step 2; it is binding, and the steps
below cite its rule ids. WR-A3, A4, A5, and Q8 are enforced by the scripts and defined in the
design reference (`Infrastructure/rules/code-war-room-design.md`); you need not read it.

**The walkthrough needs the author.** In a delegated or non-interactive run, stop after Step 3
and report the ledger path and that the walkthrough is waiting for the author; wherever a step
below asks the author something, report it to the caller instead.

## Step 1 — Parse the target

The argument is one script and an optional `--fast-forward` (batch-confirm mechanical blocks).
With none, reply `code-war-room <script-path> [--fast-forward]` and stop. Expand `~`. The path must be a file ending in `.py`, `.R`, `.Rmd`, `.qmd`, `.do`, or `.ado`;
otherwise say it is not a reviewable script and stop. For a directory, list its scripts and ask
which one: one session covers one script. The project root is the nearest ancestor of the
script that contains `PROJECT.md`; if there is none, ask the author for it. Pass it to every
script below as `--project-root`, because the ledger never stores it (WR-A5).

## Step 2 — Locate the ledger

```
python3 Infrastructure/scripts/war_room_prep.py locate <script> --project-root <root>
```

It prints the ledger path, whose directory name is the `<slug>` (never build it by hand), and
says on stderr whether a ledger exists there. If it refuses (exit 1) because that ledger names
another project or script, report its message and stop: it describes different code (WR-I5).

If the ledger exists, re-anchor it and persist what changed:

```
python3 Infrastructure/scripts/war_room_prep.py verify <ledger> --project-root <root> --write
```

Report every drifted block with its recorded and current lines, and every
`drift_after_disposition` as a regression: the decision recorded for it may no longer describe
the code (WR-A3, WR-A4). If blocks only moved (`relocated_from`) and none drifted, offer
`verify <ledger> --project-root <root> --accept-relocations`. If `session.prep_completed` is
set, report the block and disposition counts and go to Step 4, where the app resumes at the
first unanswered block. If prep never finished, run Step 3 on the ledger without rebuilding it.

## Step 3 — Prep

State the estimated runtime and the ledger path first (a Tier 2 job under
`Infrastructure/rules/performance-cost-governance.md`). List `<root>/review-reports/`; say
which reports exist, since they seed questions, and that none is normal.

Build the skeleton if there is no ledger yet, passing `--mode fast-forward` only when the
invocation carried `--fast-forward`, since this command is the only writer of `session.mode`:

```
python3 Infrastructure/scripts/war_room_prep.py skeleton <script> --project-root <root> \
    --mode <ordered | fast-forward> --out <ledger>
```

Then spawn `code-interlocutor`:

```
Agent: code-interlocutor
Phase: prep
Script: <absolute script path>
Project root: <absolute project root>
Ledger: <ledger>
Mode: <ordered | fast-forward>
Existing reports: [list, possibly empty]
```

It writes each block's title, density, and prediction, then runs `finalize`. Confirm
`session.prep_completed` is set and `war_room_lint.py <ledger> --project-root <root>` passes
before going on: a prediction written after the walkthrough opens drifts toward what the
author said (WR-P1, WR-P2). Pass any boundary concerns it returns to the author for the block map.

## Step 4 — Launch the app

Start the server as a background process; it serves until stopped:

```
python3 Infrastructure/scripts/war_room_server.py --ledger <ledger> --project-root <root>
```

It opens a browser once it is serving (pass `--no-browser` when this session has no display)
and prints the URL; `--port 0` picks a free port if 8765 is taken. It refuses a ledger without
`prep_completed`; never work around that by setting the field. Report once, then wait:

> War room ready: **N blocks** in `<script>` (H high density, M medium, L low). Open
> `<url>`. The ledger saves after every answer, so you can stop at any point. Tell me when you
> are done and I will reconcile.

Then produce no output about the blocks until the author is done: no summaries,
interpretations, or offers to walk them in conversation (WR-P5). The app opens on the block
map, where the author merges and splits blocks (WR-S5) and, in fast-forward mode,
batch-confirms mechanical ones; then it shows one block per screen.

## Step 5 — Reconcile

```
python3 Infrastructure/scripts/war_room_reconcile.py --ledger <ledger> --project-root <root> --write
```

The server may keep running: every script write holds the ledger's lock, so reconcile waits
for a save in progress (after 10 seconds it stops and names the holder; retry). Exit 3 means
blocks lack a disposition: name them and ask whether to resume in the app or close now with
`--allow-incomplete`. If it lists blocks needing judgment, stop the server, because the agent
edits the ledger without the lock, then spawn `code-interlocutor` with `Phase: reconcile`, the
script, root, and ledger; it records each divergence and reruns `--write`. If it lists none,
every block was endorsed; do not manufacture divergences.

## Step 6 — Render and close

List `<root>/review-reports/war-room/`, then render (both refuse a ledger that fails lint):

```
python3 Infrastructure/scripts/war_room_render.py md <ledger> --project-root <root> \
    --out <ledger dir>/ledger.md
python3 Infrastructure/scripts/war_room_render.py html <ledger> --project-root <root> \
    --out <root>/review-reports/war-room/<slug>-war-room.html
```

List the report directory again and report both listings, plus the WR-X4 filesystem check of
the reviewed project: the report may be the only new file there (WR-X3). Never hand-edit a
rendered file; correct `ledger.yaml` and re-render (WR-O5).

Confirm each staged registry candidate with the author, one at a time, showing the exact entry;
write it to `<root>/data/docs/dataset-registry.yaml`, then run the validator (WR-R1 to R5):
`python3 Infrastructure/scripts/validate_dataset_registry.py --project-root <root>`. Then stop
the server if it is still running, and report:

> War room complete for `<script>`. **Coverage:** N of M blocks (D answered, E endorsed,
> F fast-forwarded). **Dispositions:** X confirmed, Y needs-change, Z agent misreads,
> W unresolved. **Divergences:** N. **Assumptions exported:** N (M author-confirmed).
> Ledger `<ledger dir>/ledger.md`; work order `<ledger dir>/work-order.md` (N actionable,
> M blocked); report `<root>/review-reports/war-room/<slug>-war-room.html`.

Name any blocks still without a disposition; the next run resumes at them. The work order goes
to a coding agent, which implements `needs-change` items and leaves `blocked` ones alone
(WR-O4); `review-ai` and `review-methodology` read the exported assumptions.

## Input

Invoke as `/code-war-room <script-path> [--fast-forward]`.

Arguments: $ARGUMENTS
