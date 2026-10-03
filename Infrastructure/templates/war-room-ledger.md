# War Room Ledger — Template

Defines the two files that make up a war-room ledger. The war-room scripts write it: the prep
script builds and finalizes the skeleton, the app server records each answer, and reconcile
and the renderers produce the rest. The `code-interlocutor` sub-agent fills only each block's
`title`, `density`, and `prediction`, and never writes a line range or a hash. All of it is
governed by `Infrastructure/rules/code-war-room-rules.md`.

**Location:** `records/war_rooms/<slug>/` — one directory per script, undated and
namespaced by project. The slug is the project id, then a double hyphen, then the script's
project-relative path with every path separator replaced by a double hyphen, keeping the file
extension: `my-project--code--02_build_sample.R`.

| File | Role |
|---|---|
| `ledger.yaml` | Source of truth. Machine-readable. Every other artifact renders from it. |
| `ledger.md` | Human-readable narrative, rendered from `ledger.yaml`. Reads top to bottom as a walkthrough of the script. |

One ledger covers exactly one script. A project accumulates several.

---

## Schema version 2 — field summary

The `ledger.yaml` schema block below is the full definition. This table is the short version:
what version 2 adds relative to version 1. Nothing is removed. A `schema_version: 1` ledger
fails lint rather than being migrated silently; no committed version 1 ledgers exist.

| Field | Meaning |
|---|---|
| `schema_version: 2` | Replaces `1`. A version 1 ledger fails lint with a message naming this template. |
| `project.id` | Basename of the reviewed project's root at prep time. Informational; it is also the value that resume and startup compare against the basename of the resolved project root. `project_root` itself is never stored (D2). |
| `session.mode` | `ordered` or `fast-forward`. Written only by `war_room_prep.py skeleton --mode {ordered,fast-forward}`, and by nothing else (D5). |
| `session.history[]` | Items are `{event, at}`, plus `by` on `prep` and `walkthrough` entries; a `reconcile` entry carries no `by`, because no reviewer is present. `event` is `prep`, `walkthrough`, or `reconcile`. Exactly three writers (D10): prep's `finalize` appends `{event: prep, at, by}`; the app server appends `{event: walkthrough, at, by}` on a reviewer's first saved answer on a given UTC date; reconcile appends `{event: reconcile, at}` on `--write`. Session dates live here, not in the ledger directory name. |
| `session.reconciled` | Set by reconcile `--write`, and only when no block still needs agent judgment. |
| `session.fixture: true` | Carried by every test ledger, so fixture text can never be mistaken for an agent's reading of real code. |
| `answered_at` (per block) | When the answer was saved. Required on every block that carries a disposition. |
| `endorsed_prediction` (per block) | The author endorsed the recorded prediction instead of writing their own account. True requires `disposition: confirmed` and `author_account: null`. |
| `drift` (per block) | True when the block's recorded range no longer hashes to its `sha256` and an identical hash was not found at exactly one range no other block owns (WR-A3). |
| `drift_after_disposition` (per block) | True when that change happened after the block already carried a disposition. This is the WR-A4 regression signal. |
| `relocated_from` (per block) | `[old start, old end]`, recorded when an identical hash was found at exactly one other contiguous range that no other block owns and `lines` was updated to it. Re-anchoring under WR-A2 is not drift, so `drift` stays false (D11). Cleared by `war_room_prep.py verify --accept-relocations`. |
| `dissent[]` (per block) | Items `{reviewer, answered_at, disposition, author_account, endorsed_prediction}`. Holds a second reviewer's answer for a block whose record is kept from the first reviewer (D4, one entry per `block_id`). |
| `flag_for_followup` (per block) | The author marked the block to come back to. Independent of disposition: a `confirmed` block can still be flagged. |
| `prediction.inherited_from`, `prediction.merged_from` (per block) | Which block a split's prediction was inherited from, or which blocks a merge's prediction combined (WR-S5). Absent unless a merge or split set it, so a block whose boundaries were never edited carries neither key. |

Every timestamp written by a war-room script — `session.prep_completed`,
`session.reconciled`, each `session.history[].at`, and each block's `answered_at` — is UTC
ISO 8601 with microseconds, and is emitted as a quoted string, as is `session.created`.

---

## Pre-Write Checklist

- [ ] Every block in the source file has an entry — discussed or fast-forwarded, none absent
- [ ] Every entry has a `prediction` block written during prep, before any human input
- [ ] No prediction was edited after its block opened (WR-P3)
- [ ] Every entry has a `disposition` from the closed vocabulary
- [ ] Every entry carries `reviewer` identity (WR-O3)
- [ ] `block_id` values are stable and unique; no shared counters anywhere (WR-O2)
- [ ] Every `needs-change` entry has enough detail to become a work-order item
- [ ] `sha256` recorded for every block — full 64 characters, computed by the exact WR-A1
      algorithm (UTF-8, line terminators discarded, block lines joined with a single
      newline, no trailing newline)
- [ ] Every hash re-verified against the source file after writing
- [ ] `ledger.md` regenerated from the current `ledger.yaml`

---

## `ledger.yaml` Schema

```yaml
# Key order below is the order the war-room scripts emit. Re-serializing a ledger by hand in
# a different order produces a large, meaningless diff; let the library write it.
schema_version: 2                        # a version 1 ledger fails lint; nothing migrates
script:
  path: code/02_build_sample.R           # project-relative path to the reviewed script
  language: R                            # R | Python | Stata (all three R dialects are `R`)
  sha256: 9f2c...                        # hash of the whole file at prep time (WR-A1)
  line_count: 184
project:
  id: my-project                         # basename of the reviewed project root at prep time
                                         # informational, and the value resume and startup
                                         # compare against the resolved root's basename.
                                         # The root itself is never stored (WR-A5).
session:
  created: '2026-09-16'                  # date of the prep pass, emitted as a quoted string
  mode: ordered                          # ordered | fast-forward. Written only by the prep
                                         # script's skeleton command (WR-C2, D5).
  prep_completed: '2026-09-16T09:14:02.118374Z'   # UTC ISO 8601, microseconds, quoted. Set
                                         # only by the prep script's finalize command
                                         # (WR-P1). MUST predate every answered_at.
  reconciled: '2026-09-18T16:40:11.902244Z'       # set by reconcile --write, and only when
                                         # no block still needs agent judgment. Omit until.
  fixture: false                         # true on every test ledger, so fixture text can
                                         # never be read as an agent's reading of real code
  history:                               # exactly three writers (WR-O7)
    - event: prep                        # prep | walkthrough | reconcile
      at: '2026-09-16T09:14:02.118374Z'
      by: bglasner                       # present on prep and walkthrough
    - event: walkthrough
      at: '2026-09-17T10:02:55.410882Z'
      by: bglasner
    - event: reconcile                   # a reconcile entry carries no `by`: nobody is there
      at: '2026-09-18T16:40:11.902244Z'
  reviewers:                             # everyone who has contributed entries (WR-Q9)
    - id: bglasner
      role: author                       # author | fresh-eyes
    - id: jdoe
      role: fresh-eyes
  segmentation_edits:                    # every merge and split, in order (WR-S5)
    - action: split                      # merge | split
      block_id: b011
      at: '2026-09-17T10:05:18.774310Z'
      by: bglasner
      at_line: 63                        # split only: the first line of the second block
      produced: [b011a, b011b]           # split only: the two ids the split created
    - action: merge
      block_id: b002
      at: '2026-09-17T10:06:02.331907Z'
      by: bglasner
      merged_from: [b002, b003]          # merge only: the ids folded into this block
  source_reports:                        # existing review reports read during prep (WR-I1)
    - review-reports/code-error-report.html
    - review-reports/methodology-report.html

blocks:
  - block_id: b007                       # stable, unique, never renumbered (WR-O2)
    lines: [42, 51]                      # flow style; line range at prep time, a hint (WR-A2)
    sha256: 4b1e...                      # hash of this block's exact source text
    title: Age restriction on the analysis sample
    density: high                        # high | medium | low (WR-N1: when unsure, higher)
    discussed: true                      # false for fast-forwarded blocks (WR-C3)
    drift: false                         # true if the hash no longer matches and the content
                                         # was not found at exactly one free range (WR-A3)
    drift_after_disposition: false       # true if that happened after a disposition was
                                         # recorded — the WR-A4 regression signal. Never
                                         # cleared by a script.
    relocated_from: null                 # null when unset. [old start, old end] when an
                                         # identical hash was found at one free range and
                                         # `lines` was updated. Re-anchoring is not drift.
    reviewer: bglasner                   # who recorded this entry (WR-O3)
    answered_at: '2026-09-17T10:11:44.093551Z'    # required on every dispositioned block
    endorsed_prediction: false           # true requires disposition: confirmed and a null
                                         # author_account (WR-Q7)
    flag_for_followup: false             # the author marked this block to come back to

    # Written during prep, before any human input. Immutable once the block opens.
    prediction:
      what_it_does: >-
        Keeps rows where age is 25 or older and drops everyone younger.
      inferred_intent: >-
        Restrict the sample to prime-age adults.
      assumptions:
        - Age is measured in completed years, not months.
        - The lower bound is intended to be inclusive.
      confidence: medium                 # high | medium | low (WR-P6: never revised)
      # Two further prediction keys close the emit order: `inherited_from`, the block id a
      # split inherited this prediction from, and `merged_from`, the block ids a merge
      # combined (WR-S5). Both are absent unless a merge or split set it, so this block —
      # whose boundaries were never edited — carries neither.

    # Captured live, from the author.
    author_account:
      meant_to_do: >-
        Restrict to prime-age workers, which the team defines as 25 to 54.
      why_this_way: >-
        "We copied the bound from the earlier CPS work and never revisited the upper end."
      assumptions_carried:
        - Downstream age-group tabulations assume no one under 25 remains.

    # The finding. Recorded whether or not the readings agreed (WR-P4).
    divergence:
      match: false
      type: incomplete-intent            # see divergence types below
      detail: >-
        The agent read a single lower bound. The author intends a 25-54 window, but no
        upper bound is applied in the code, so 55+ remains in the sample.

    disposition: needs-change            # confirmed | misread-by-agent | needs-change | unresolved

    # A second reviewer's answer for this same block, moved here when git reported a conflict
    # (WR-O6). One entry per block_id always; the disagreement lives in this list.
    dissent:
      - reviewer: jdoe
        answered_at: '2026-09-18T09:22:03.551209Z'
        disposition: confirmed
        author_account:
          meant_to_do: >-
            The missing upper bound is deliberate; 55+ is dropped upstream.
          why_this_way: "Inherited from the pooled-sample build."
          assumptions_carried: []
        endorsed_prediction: false

    evidence:
      sources:
        - code/02_build_sample.R:42-51
        - review-reports/methodology-report.html (MR-SA2)
      confidence: high
      assumptions:
        - Author's 25-54 definition is the project standard, stated in session.

    registry_writeback:                  # omit entirely when not applicable (WR-R1)
      dataset_id: cps
      action: variable-restriction
      status: pending-confirmation       # pending-confirmation | written | declined
      layer: project                     # ALWAYS project (WR-R2)
      verification: parsed               # ALWAYS parsed — never `verified` (WR-R2)

  # A fast-forwarded block still gets a full entry.
  - block_id: b001
    lines: [1, 8]
    sha256: a77d...
    title: Library loads and path setup
    density: low
    discussed: false
    drift: false
    drift_after_disposition: false
    relocated_from: null
    reviewer: bglasner
    answered_at: '2026-09-17T10:03:12.664018Z'
    endorsed_prediction: true            # batch confirmation is an endorsement (WR-Q8)
    flag_for_followup: false
    prediction:
      what_it_does: Loads tidyverse and fixest and resolves the project root.
      inferred_intent: Standard environment setup.
      assumptions: []
      confidence: high                   # `inherited_from` and `merged_from` are absent
                                         # unless a merge or split set them
    author_account: null                 # null when not discussed
    divergence:
      match: null                        # null when not discussed; set by reconcile
      type: null
      detail: null
    disposition: confirmed
    dissent: []
    evidence:
      sources: [code/02_build_sample.R:1-8]
      confidence: high
      assumptions: []

# Rendered on session close for ai-skeptic and methodology-reviewer (WR-I3).
assumption_export:
  - block_id: b007
    assumption: Downstream age-group tabulations assume no one under 25 remains.
    stated_by: author                    # author | agent | existing-report
    confirmed: true                      # author confirmed it in session
  - block_id: b007
    assumption: Age is measured in completed years.
    stated_by: agent
    confirmed: false                     # agent inferred it; author did not address it
  - block_id: b001
    assumption: No path setup depends on the working directory.
    stated_by: agent
    confirmed: true                      # endorsed via batch confirmation (WR-Q8)

open_questions:                          # every `unresolved` block lands here
  - block_id: b019
    question: Whether the 2019 vintage weight is correct for the pooled sample.
    blocked_on: Confirmation from the data lead.
```

### Divergence types

| Type | Meaning |
|---|---|
| `none` | Readings matched. `match: true`. |
| `wrong-mechanics` | The agent misread what the code does. Usually pairs with `misread-by-agent`. |
| `wrong-intent` | The agent read the mechanics correctly but inferred the wrong purpose. |
| `incomplete-intent` | The author intends more than the code implements. Usually pairs with `needs-change`. |
| `undisclosed-assumption` | The block carries an assumption neither the comments nor the author had stated. |
| `author-uncertain` | The author could not confirm intent. Pairs with `unresolved`. |

---

## `ledger.md` Structure

Rendered from `ledger.yaml` by `Infrastructure/scripts/war_room_render.py md`, which is the
only writer of this file (WR-O5). It must read as a walkthrough someone new to the script can
follow start to finish (S6). The shape below is what the renderer emits; the notes after it
state the parts a reader is most likely to get wrong by hand.

```markdown
# War Room — <script path>

**Reviewed:** <date>  ·  **Reviewers:** <ids>  ·  **Mode:** <ordered | fast-forward>
**Coverage:** <N> blocks — <D> discussed, <F> fast-forwarded

## Summary

<2-4 sentences: what the script does, where agent and author diverged, what needs changing.>

| Disposition | Count |
|---|---|
| confirmed | N |
| misread-by-agent | N |
| needs-change | N |
| unresolved | N |

## Blocks

### b007 — Age restriction on the analysis sample
`<project>/code/02_build_sample.R:42-51` · density: high · discussed · **needs-change**

> Agent read (confidence: medium): Keeps rows where age is 25 or older.
> Agent inferred intent: Restrict the sample to prime-age adults.
> Author intent: Restrict to prime-age workers, defined as 25 to 54.
> **Divergence — incomplete-intent:** no upper bound is applied, so 55+ remains.

**Drift:** the source at lines 42-51 no longer matches this block's recorded hash. It already
carried a disposition when it changed (WR-A4).

**Why this way:** "We copied the bound from the earlier CPS work and never revisited it."

**Assumptions carried forward:**
- Downstream age-group tabulations assume no one under 25 remains.

**Dissent — jdoe (confirmed):** the missing upper bound is deliberate; 55+ is dropped
upstream.

---

### b001 — Library loads and path setup
`<project>/code/02_build_sample.R:1-8` · density: low · fast-forwarded · **confirmed**

> Agent read (confidence: high): Loads tidyverse and fixest and resolves the project root.
> Agent inferred intent: Make the analysis packages and the project paths available.

Confirmed in a batch without discussion, which endorses the recorded prediction and its
assumptions (WR-C3, WR-Q8). No author account is rendered for a fast-forwarded block.

---

<one section per block, in file order. Every block's own section — between its heading and
the next block heading — carries its prediction verbatim, and a fast-forwarded block's
section says `fast-forwarded` so the two coverage states are never confused.>

## Assumptions Carried Forward

**b004**
- Downstream tabulations assume nobody under 25 remains. (stated by author; confirmed: yes)

## Open Questions

- **b006** — Whether dropping missing wages is the intended treatment. (blocked on: the data
  codebook, which is not in the room.)

## Drift

None detected.
```

What the renderer guarantees, and what a hand-written file would get wrong:

1. **Coverage line.** `**Coverage:** <N> blocks — <D> discussed, <F> fast-forwarded`, with
   `, <U> not answered` appended only while some block lacks a disposition. Fast-forwarded
   means `discussed: false` *with* a disposition; `discussed: false` *without* one renders as
   not answered, in the coverage line, in the block's own meta line, and in place of the
   disposition. The two states are never collapsed.
2. **The summary is computed from the ledger**, never written prose: block counts, the
   coverage split, the disposition tallies, and whether the ledger is reconciled.
3. **Per-block quote.** `> Agent read (confidence: <c>): <what_it_does>` then
   `> Agent inferred intent: <inferred_intent>`, both verbatim from `prediction` (WRR-3,
   WR-P3). `> Author intent: <meant_to_do>` follows only when an author account exists, and
   the classification renders as `> **Match:** <detail>` or
   `> **Divergence — <type>:** <detail>`.
4. **The block meta line cites the project-relative `script.path`** exactly as the ledger
   records it, followed by the recorded line range — never an absolute path. The examples
   above carry a `<project>/` prefix only so this repository's own internal-path check does
   not read them as local files; the renderer emits no such prefix.
5. **A drifted block carries a `**Drift:** …` line inside its own section**, naming the
   recorded lines, plus the WR-A4 sentence when `drift_after_disposition` is set. Both read
   the persisted flags; drift is never recomputed at render time (WR-A3).
6. **Empty states are explicit** (WRR-4): `None recorded.` under Assumptions Carried Forward
   and under Open Questions, `None detected.` under Drift. A section is never dropped.
7. **Assumptions Carried Forward is grouped by block id in file order**: a `**bNNN**` line,
   then one `- <assumption> (stated by <stated_by>; confirmed: yes|no)` per item.
8. **Open Questions is one line per item**:
   `- **<block_id>** — <question> (blocked on: <blocked_on>)`.

---

## Merge Behavior

Two reviewers walking the same script share **one** `ledger.yaml`, in that script's slug
directory, and edit it on separate branches. There is never a second directory for the same
script and never a second entry for the same `block_id`. The file merges in git because:

1. Each block is exactly one top-level list entry under a stable `block_id` (WR-O2).
2. No entry contains a running count, index, or total — aggregates live only in rendered
   output, which is regenerated rather than merged.
3. `reviewer` is recorded per entry (WR-O3), so a merged ledger still attributes each answer.

Where two reviewers recorded different answers for the same `block_id`, git reports a
conflict. **That is the intended behavior** — two people disagreeing about what a block is
meant to do is a finding, not a merge problem.

Resolve it by keeping one reviewer's entry as the block's record and moving the other
reviewer's answer into `dissent[]` on that same entry (WR-O6). Each `dissent` item carries
`reviewer`, `answered_at`, `disposition`, `author_account`, and `endorsed_prediction`, which
is everything needed to reconstruct the second answer without a second entry. Do not pick a
winner and delete the loser, and do not leave two entries sharing a `block_id`: lint rejects
the duplicate, and every count rendered from the ledger would double-count that block.
