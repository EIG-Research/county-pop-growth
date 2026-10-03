# Review Board Ledger — Template

Defines the two machine-written files of a review board: `feedback.yaml`, the reviewer lane,
and `ledger.yaml`, the agent lane. The third file, `board.yaml`, is defined in
`Infrastructure/templates/review-board-config.md`. All three are governed by
`Infrastructure/rules/review-board-rules.md`.

**Location:** `records/review_boards/<project id>--<board id>/`: one directory per
board, undated and namespaced by project.

| File | Writer | Role |
|---|---|---|
| `feedback.yaml` | Board server | Every reviewer event, append-only (RB-L3) |
| `ledger.yaml` | `review_board.py`; the agent through `review_board.py record` | Renders, measurements, rounds, triage, responses |

The agent writes its round entries (the stop gate, triage, changes, responses, and waivers)
as a small YAML file with any of those five keys, shaped as in the round entry below, and
merges it with `review_board.py record --from <file>`. Entries are matched and replaced by
event for triage, by item for changes and responses, and by item and check for waivers.
`record` refuses unknown keys, events outside the open round, and values outside the closed
sets, and then lists whatever `round close` would still refuse.

Do not hand-serialize either file in a different key order. The library writes keys in the
order shown below, and a reordered file produces a large, meaningless diff.

---

## `feedback.yaml` Schema

```yaml
schema_version: 1
project:
  id: my-project                  # must equal board.yaml project.id
board:
  id: brief-figures               # must equal board.yaml board.id
fixture: false                    # true on every test file
events:                           # append-only (RB-L3); ordered by seq
  - id: ev-00001                  # server-assigned: "ev-" + seq, zero-padded to 5 digits
    seq: 1                        # server-assigned; strictly increasing, starts at 1
    item: fig-wages-by-sex        # a board.yaml item id (RL-02)
    by: bglasner                  # a board.yaml reviewer id (RL-02)
    at: '2026-09-24T14:02:11.418201Z'   # server-assigned UTC, microseconds, quoted
    kind: status                  # status | change-request | comment
    status: approved              # status events only: unreviewed | approved | needs-changes
    approved_hash: 3f9a…          # approvals only; server-assigned from the ledger (RB-L6)
    text: null                    # change-request and comment only: required, verbatim
    source: local                 # always local: the board is local only (RB-H1)
    source_id: null               # always null; reserved
  - id: ev-00002
    seq: 2
    item: fig-wages-by-sex
    by: bglasner
    at: '2026-09-24T14:03:40.002117Z'
    kind: change-request
    status: null
    approved_hash: null
    text: >-
      The 2019 label overlaps the line. Move it above.
    source: local
    source_id: null
```

Rules the lint enforces on every event:

- `kind` is from the closed set. `status` is present exactly when `kind: status`.
  `approved_hash` is present exactly when `status: approved`. `text` is non-empty exactly
  when `kind` is `change-request` or `comment` (RL-03).
- `id` values are unique, `seq` strictly increases, and `id` equals `ev-` plus the
  zero-padded `seq` (RL-04).
- Nothing committed at `git HEAD` is missing or altered (RL-05).

### Fold rules (RB-L4, RB-L5)

A reviewer's status on an item is folded from their events in `seq` order, starting at
`unreviewed`:

| Event | Effect |
|---|---|
| `status` | status becomes the event's value |
| `change-request` | `approved` becomes `needs-changes`; other statuses unchanged |
| `comment` | none |

The owner's approval is **current** when the folded status is `approved` and the
`approved_hash` of the owner's latest approval event equals the item's render hash in the
latest closed round.

---

## `ledger.yaml` Schema

```yaml
schema_version: 1
project:
  id: my-project
board:
  id: brief-figures
fixture: false

items:                                   # one entry per item ever rendered
  - id: fig-wages-by-sex
    renders:                             # one entry per round in which it was rendered
      - round: 1
        hash: 3f9a…                      # RB-R5, full 64 characters
        snapshot: renders/r01/fig-wages-by-sex.png     # relative to the board directory
        svg_snapshot: renders/r01/fig-wages-by-sex.svg # null when no SVG is declared
        classification: new              # new | changed | unchanged, against the latest
                                         # closed round's render (RB-R6)
        measurements:                    # RB-M2
          width_px: 1950
          height_px: 1050
          dpi: 300                       # null when pHYs is absent
          dpi_changed: false
          text_floor: {result: pass, smallest_pt: 8.0, floor_pt: 7.0, below_floor: 0}
          palette: {result: fail, off_palette: ['#1f77b4']}
          contrast: {result: pass, min_ratio: 12.6, background: '#ffffff',
                     background_source: full-size rect, failing_fills: []}
                                         # result: pass | fail | not-measured (RB-M3).
                                         # A not-measured result carries `reason` instead
                                         # of the other keys. background_source is
                                         # svg background | full-size rect |
                                         # first painted shape | assumed white

rounds:                                  # one entry per round, in order (RL-13)
  - n: 2
    opened_at: '2026-09-24T15:00:02.771450Z'
    cursor_seq: 7                        # events with seq <= this are this round's
    cursor_at: '2026-09-24T14:58:41.090311Z'   # `at` of the event at cursor_seq
    listed: [ev-00004, ev-00005, ev-00007]     # new change-requests and comments
    carried: [ev-00002]                  # latest triage was question or surface (RB-T8)
    stop_gate:                           # RB-P2
      verdict: proceed                   # stop | proceed
      reason: All changes are inside declared item sources.
      approved_on: null                  # required when verdict is stop (RL-12)
    triage:                              # exactly one entry per listed and carried event
      - event: ev-00004
        decision: do-with-change         # do | do-with-change | question | decline | surface
        reason: >-                       # required unless decision is do (RL-08)
          Asked for the y-axis to start at 30; a truncated axis on a bar chart breaks
          style-figure-rules.md rule 8. Kept the zero baseline and added data labels.
        owner_confirmed_on: null         # required for a non-owner event that is not
                                         # triaged surface (RL-07)
    changes:                             # one entry per changed item (RL-11)
      - item: fig-wages-by-sex
        what_changed: Data labels added to each bar; axis unchanged.
        explanation: null                # required when no do/do-with-change on this
                                         # item covers the change (RL-09, RB-C2)
    responses:                           # one per item with an event triaged this round
      - item: fig-wages-by-sex
        state: changed                   # changed | still-open | answered | declined
        text: >-
          Added data labels instead of truncating the axis, which would exaggerate the gap.
    waivers:                             # RB-M4
      - item: fig-dci-map
        check: palette
        reason: DCI quintile legacy palette, per eig-legacy-palette-policy.md.
    changed_files:                       # written at close; paths outside declared sources
      available: true                    # false outside a git repository
      outside_sources: []
    closed_at: '2026-09-24T15:41:19.330871Z'   # null while the round is open
```

Round 1 is the initial render. It has no events, so `listed`, `carried`, and `triage` are
empty, and every item is `new`.

The per-machine file snapshot that `round close` compares against is kept in
`renders/rNN/file-snapshot.json`, which is gitignored. A round opened on one machine and
closed on another reports `changed_files.available: false`.

---

## Lint Codes

`review_board_lint.py` runs at four points: on every server write (`write`), at
`round open` (`open`), at `round close` (`close`), and on demand (`lint`, which runs the
checks that apply to the board's current state). A failure at any point saves nothing.

| Code | Checked at | Failure |
|---|---|---|
| RL-01 | all | `board.yaml` is invalid (required fields, id patterns, not exactly one owner, a retired owner, duplicate ids, or `medium` not `print` or `screen`), or `feedback.yaml` or `ledger.yaml` has another `schema_version` or names another project or board |
| RL-02 | all | An event names an item or reviewer that `board.yaml` does not list. Retired entries still count as listed, which is why nothing is deleted from `board.yaml` (RB-L3) |
| RL-03 | all | A malformed event: kind or status outside the closed set, `status` or `approved_hash` present when it should not be or missing when it should be, or missing text |
| RL-04 | all | A duplicate event id, a `seq` that does not strictly increase, or an `id` that does not match its `seq` |
| RL-05 | write, open, close, lint | An append-only violation: an event present in the previous version or at `git HEAD` is missing or altered |
| RL-06 | close | A listed or carried event has no triage entry, more than one, or a decision outside the closed set; a triage entry names an event the round did not list or carry; or `listed`/`carried` differ from what `feedback.yaml` and earlier rounds imply |
| RL-07 | close | A non-owner event is triaged other than `surface` without `owner_confirmed_on` |
| RL-08 | close | A decision other than `do` has no reason |
| RL-09 | close | A `changed` item has neither a covering `do`/`do-with-change` decision nor an `explanation` |
| RL-10 | close | A frozen item's classification is `changed` |
| RL-11 | close | A changed item has no `what_changed`, an item with an event triaged this round has no response, or a response state is outside the closed set |
| RL-12 | close | `stop_gate.verdict` is `stop` and `approved_on` is empty |
| RL-13 | all | Rounds, renders, or waivers are malformed or out of order: rounds not numbered 1..N, an open round that is not the last, `cursor_seq` decreasing or beyond the last event, a render for an unknown round or with a bad hash or classification, a ledger item missing from `board.yaml`, or a malformed waiver. At close, also a round without a render of every active item |
| RL-14 | all | A path in `board.yaml` is absolute, contains `..`, or resolves outside the project root |
| RL-15 | all | `board.yaml` has a `hosting` block that sets `cleared: true` (or is not a mapping): the board is local only and has no hosted mode (RB-H2) |

---

## Pre-Write Checklist (agent-lane edits)

- [ ] `feedback.yaml` was not opened for writing (RB-L2)
- [ ] Every listed and carried event has exactly one triage entry
- [ ] Every reason names a data source, file, or rule id (RB-T4)
- [ ] Every changed item has `what_changed`, and an `explanation` where no decision covers it
- [ ] Every response is short, specific, and gives the reason for any decline (RB-C3)
- [ ] `stop_gate` reflects the round's actual file changes (RB-P2, RB-C4)
- [ ] `review_board.py lint` passes
