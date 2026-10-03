# Review Board Round Plan — Template

The shell for `rounds/round-NN.md` in a review board directory. `review_board.py round open`
reads the fenced block below at run time and writes it out as the round's skeleton, so this
block is the one source for the file's structure; edit it here, never in the script. The
agent then writes the prose sections before editing any source (RB-P1). Governed by
`Infrastructure/rules/review-board-rules.md`.

Two kinds of content share the file:

- **Generated blocks** sit between `<!-- generated:<name>:begin -->` and
  `<!-- generated:<name>:end -->` markers. `round open`, `record`, `round close`, and
  `summary` rewrite them from `ledger.yaml` and `feedback.yaml`. Never edit inside them.
  Decisions and verdicts live in `ledger.yaml` only, and these blocks display them.
- **Agent prose** is everything else: approach, chat requests, probes, stop-gate reasoning,
  self-check findings, claim checks, and Evidence.

The placeholders `{{round}}`, `{{board_title}}`, and `{{approach}}` are filled once, when
the skeleton is written. `{{approach}}` becomes one subsection per item with events this
round, listing its event ids.

---

```markdown
# Round {{round}} — {{board_title}}

<!-- generated:header:begin -->
<!-- generated:header:end -->

## Events and triage

<!-- generated:triage:begin -->
<!-- generated:triage:end -->

Note text is copied from `feedback.yaml`, which is the record. A decision shows as `—`
until it is recorded in `ledger.yaml`.

## Approach

<!-- For each item: what will change, in which source file, and why that satisfies the
note, or why the note is declined (RB-T6). -->

{{approach}}

## Chat requests

<!-- Owner requests made in conversation (RB-T7): the date, what was asked, and how it is
handled. Write "None." when there were none. -->

## Probes

<!-- Every tool setting a fix relies on, tested alone first (RB-P3). -->

| Setting | Expected effect | Evidence |
|---|---|---|

## Stop gate

<!-- The reasoning behind the verdict in the header (RB-P2): every file outside the items'
declared sources this round will change, any data change, and any board.yaml change. If the
verdict is stop, say what the owner needs to decide. -->

## Self-check

<!-- Style findings on changed items against the figure style rules, failing measurements
(RB-M2), and how each was resolved or waived (RB-M4). -->

## Claim checks

<!-- Every claim a changed item makes, and every item's claims before reporting done
(RB-E1). -->

| Item | Claim | Source | Result |
|---|---|---|---|

## Changed files

<!-- generated:changed-files:begin -->
<!-- generated:changed-files:end -->

<!-- Explain each file listed above (RB-C4). -->

## Evidence

- **Sources:**
- **Confidence:**
- **Assumptions:**
```

---

## Example

What the filled sections look like for one event, after `round open` and the agent's
edits. The generated blocks are abbreviated.

```markdown
## Events and triage

| Event | Item | By | Kind | Note | Decision | Reason |
|---|---|---|---|---|---|---|
| ev-00004 | fig-wages-by-sex | bglasner | change-request | Start the y-axis at 30 so the gap is visible. | do-with-change | A truncated bar axis breaks style-figure-rules.md rule 8; added data labels instead. |

## Approach

### fig-wages-by-sex

- ev-00004: keep the zero baseline in the figure script and add value labels to each bar,
  which makes the gap readable without exaggerating it.

## Probes

| Setting | Expected effect | Evidence |
|---|---|---|
| `geom_text(vjust = -0.4)` | Labels sit above each bar | Hash changed; labels visible above all six bars |

## Claim checks

| Item | Claim | Source | Result |
|---|---|---|---|
| fig-wages-by-sex | "Women's wages grew faster than men's since 2019" | `wages_by_sex.csv` (the table the figure plots), rows 2019–2025 | Supported |
```
