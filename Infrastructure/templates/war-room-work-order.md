# War Room Work Order — Template

The handoff artifact from a war-room session to a coding agent. Rendered by
`Infrastructure/scripts/war_room_reconcile.py` from the `needs-change` and `unresolved`
entries in `ledger.yaml` (WR-O4): `needs-change` blocks become `actionable` items, and
`unresolved` blocks become `blocked` items that a coding agent must not implement.

**Location:** `records/war_rooms/<slug>/work-order.md`, beside the ledger it renders
from. The slug is undated and namespaced by project (WR-X2); session dates live in the
ledger's `session.history[]`.

**Design constraint:** this file must be actionable on its own. A coding agent should be
able to implement every item without opening the ledger. Each item therefore restates the
current behavior and the intended behavior rather than pointing back at a block entry.

---

## Pre-Write Checklist

- [ ] Contains `needs-change` items as `actionable` and `unresolved` items as `blocked` — nothing `confirmed` or `misread-by-agent`
- [ ] Every `blocked` item carries a **Blocked on** row and appears in the Blocked Items table
- [ ] The header's `**Items:**` counts are computed from the ledger, never hard-coded
- [ ] Every item names file, line range, and `block_id`
- [ ] Every item states current behavior and intended behavior as separate fields
- [ ] Every item records who decided and on what date
- [ ] No item says only "fix this" or otherwise assumes ledger context
- [ ] Every path in the file is repository-relative or project-relative — no absolute path
- [ ] Line ranges are flagged as of the recorded `sha256`, so a coding agent can detect drift

---

## Template

```markdown
# Work Order — <script path>

**Source ledger:** `records/war_rooms/<slug>/ledger.yaml`
**Session date:** <YYYY-MM-DD>
**Reviewers:** <ids>
**Items:** <N> actionable, <B> blocked

> Generated from a war-room walkthrough. Every item traces to a recorded decision.
> Do not implement a change that is not listed here; raise it back to the ledger instead.
> A `blocked` item is listed so the open question is visible, not so it can be guessed at.

---

## WO-001 — Apply the upper age bound

| Field | Value |
|---|---|
| **Status** | actionable |
| **File** | `<project>/code/02_build_sample.R` |
| **Lines** | 42-51 |
| **Block** | b007 |
| **Block sha256** | `4b1e...` |
| **Decided by** | bglasner |
| **Decided on** | 2026-09-16 |

**Current behavior**
The filter keeps rows where `age >= 25`. No upper bound is applied, so respondents aged 55
and older remain in the analysis sample.

**Intended behavior**
Restrict to prime-age workers, defined by the project as ages 25 through 54 inclusive.

**Why it is this way**
"We copied the bound from the earlier CPS work and never revisited it."

**Change**
Add the upper bound to the existing filter. Both bounds are inclusive.

**Downstream effects**
Sample size drops. Every age-group tabulation and every model estimated on this sample
changes. Rerun the full pipeline rather than the affected script alone.

**Verification**
Confirm the post-filter age range is 25-54 and that no downstream script assumes the
previous sample size.

---

## WO-002 — <title>

| Field | Value |
|---|---|
| **Status** | blocked |
| **File** | `<project>/code/02_build_sample.R` |
| **Lines** | 88-94 |
| **Block** | b019 |
| **Block sha256** | `c30a...` |
| **Decided by** | — |
| **Decided on** | — |
| **Blocked on** | Confirmation of the correct weight vintage from the data lead |

**Current behavior**
<what the code does today>

**Intended behavior**
<unresolved — do not implement until the blocker clears>

**Blocked on**
Confirmation of the correct weight vintage from the data lead. Until that clears, this item
is a record of an open question, not an instruction.

---

## Blocked Items

| ID | Block | Blocked on |
|---|---|---|
| WO-002 | b019 | Weight vintage confirmation from the data lead |

## Not In Scope

Recorded during the session but deliberately excluded from this work order:

| Block | Disposition | Note |
|---|---|---|
| b012 | misread-by-agent | Code is correct; the agent's reading was wrong. No change needed. |
| b022 | confirmed | Author confirmed intent matches implementation. |
```

How the renderer fills this shape:

- **Block sha256 is the full 64-character digest** recorded for the block (WR-A1). The
  examples above are abbreviated for legibility only; an abbreviated digest in a rendered
  work order is a defect, because a coding agent cannot re-verify against it (WO-R4).
- **File** is the project-relative `script.path` from the ledger, never an absolute path. The
  examples above carry a `<project>/` prefix only so this repository's own internal-path check
  does not read them as local files; the renderer emits no such prefix.
- **Decided by / Decided on** come from the block's `reviewer` and the date part of its
  `answered_at`. Either renders as `—` when the ledger does not record it, which is the normal
  state for an `unresolved` block nobody signed off.
- **Numbering is `WO-001`, `WO-002`, …** assigned in one pass: every actionable item first, in
  file order, then every blocked item, in file order. Numbers are positional and are not
  stable across regenerations; the `block_id` is the stable reference.
- **Change** carries `divergence.detail` once the divergence is classified, so an unreconciled
  ledger produces an item with no change text rather than an invented one.
- **Change**, **Downstream effects**, and **Verification** render `[unverified: not recorded]`
  when the session recorded nothing for them. The renderer never fills them in from inference
  (WO-R3); the marker says plainly that a human has to supply the answer. **Why it is this
  way** and the two behavior fields use the same marker when their source field is empty.
- **Blocked Items** renders only when at least one blocked item exists.
- **Not In Scope** always renders. When nothing was excluded it carries the single row
  `| — | — | None recorded. |`, so an empty table and an unwritten section stay
  distinguishable (WO-R5).

---

## Status Values

| Status | Meaning |
|---|---|
| `actionable` | Decision is recorded and complete. A coding agent may implement it. |
| `blocked` | The change is agreed in principle but depends on an unresolved question. Do not implement. |

---

## Rules

**WO-R1 — `needs-change` blocks produce `actionable` items; `unresolved` blocks produce
`blocked` items.** A `misread-by-agent` disposition records an agent calibration failure, not
a code defect, and a `confirmed` block records agreement; neither generates an item. A
`blocked` item is never implemented — it names what it waits on, and clearing the blocker
means returning to the ledger, not guessing in the code.

**WO-R2 — One item per block.** If a block needs several distinct changes, that is a signal
the block was segmented too coarsely; split it in the ledger and regenerate.

**WO-R3 — Never invent a fix the author did not agree to.** The work order transcribes
decisions. A change the agent thinks is a good idea but that was not decided in the room
belongs in a review report, not here.

**WO-R4 — Record the block hash.** A coding agent that finds the block changed since the
session must stop and flag it rather than applying a decision to different code.

**WO-R5 — Include the "Not In Scope" table.** Showing what was examined and deliberately
left alone prevents a coding agent from re-opening settled questions.
