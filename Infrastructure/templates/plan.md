# Plan Template

The shell for a saved plan at `records/plans/YYYY-MM-DD_short-description.md`. Copy
everything below the rule, save it with Status DRAFT, and get approval before implementing.

- Status is one word and a date: DRAFT, APPROVED (by whom), PARTIAL (what is open, listed
  under Verification), COMPLETED, or SUPERSEDED (by which plan). Update it on disk when it
  changes, because the next session reads the file, not the chat.
- Requirements source names the approved spec or parent plan, or the session log that
  records the request. A plan never calls requirements approved while its source says DRAFT.
- Boundaries name the files and topics the plan leaves alone, so a reviewer can check scope.
- Use Units only when the plan has more than one separately committable piece; otherwise
  list files and a proof under Approach. A proof is a command with the output that shows it
  passed, or a named reviewer check; "reviewed" alone is not one.
- Owner-judgment items record the default taken; each lands in its own commit so it can be
  reverted. Delete the section when there are none.
- Add sections the work needs (merge order, budgets, risks). Record changes made after
  approval under Amendments with a date and reason instead of rewriting approved text.

---

# Plan: [Title]

**Date:** YYYY-MM-DD
**Status:** DRAFT YYYY-MM-DD
**Requirements source:** [`records/specs/...` (APPROVED YYYY-MM-DD) | parent plan | session log]

## Goal and boundaries

[The observable result when this plan is done.]

**Not changed here:** [files, topics, or workstreams outside scope]

## Approach

[Why this order and design; the constraints that drive it.]

## Units

**U1 — [name]** ([S/M/L]). [What changes.] *Files:* [paths]. *Closes:* [finding or
requirement ids]. *Proof:* [command and expected output, or reviewer check].

## Owner-judgment items

| # | Question | Default taken | Commit |
|---|---|---|---|
| O1 | | | |

## Verification

The plan is COMPLETED only when every check below passes; otherwise it is PARTIAL and each
open check is listed with its reason.

- [ ] [command or reviewer check, and where its result is recorded]

## Amendments

- YYYY-MM-DD: [change and reason]
