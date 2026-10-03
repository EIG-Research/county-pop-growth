---
load: referenced
---

# Plan-First Workflow

How to specify, plan, and execute a task that meets the plan threshold in `AGENTS.md` (Working
Rules), which is the only definition of when a plan is needed. Choosing between intent
discovery, idea refinement, a requirements spec, and direct planning is owned by
`Infrastructure/AI_WORKFLOW.md`; this rule starts once that choice is made.

## Protocol

1. **Specify if needed.** Write a requirements spec first when the task is ambiguous or large
   (see below); otherwise plan directly.
2. **Draft the plan** from `Infrastructure/templates/plan.md`: goal and boundaries, files,
   order, and a proof for each piece.
3. **Save it** to `records/plans/YYYY-MM-DD_short-description.md` with Status DRAFT, so
   the plan survives the session.
4. **Get approval**, then record it in the plan's Status line before implementing, because the
   next session reads the file, not the chat.
5. **Implement and verify** following `Infrastructure/AI_WORKFLOW.md`; log decisions per
   `Infrastructure/rules/session-logging.md`.
6. **Close it.** Set Status to COMPLETED only when every verification check passes; otherwise
   PARTIAL, with the open checks listed.

## Requirements Specification

Write a spec when the task is high-level or vague ("improve this analysis"), has several valid
interpretations, or is large (more than an hour, or more than three files). Skip it for a
clear, specific task, a single-file edit, or when the user already gave detailed requirements.

1. Take any confirmed intent or concept brief as fixed input and ask only about unresolved
   requirements, in at most five short questions. Unselected concept alternatives are context,
   not requirements, unless the user selects one.
2. Create `records/specs/YYYY-MM-DD_description.md` from
   `Infrastructure/templates/requirements-spec.md`.
3. Mark each requirement **MUST** (non-negotiable), **SHOULD** (preferred), or **MAY**
   (optional), and each major aspect **CLEAR**, **ASSUMED** (the user can override), or
   **BLOCKED** (cannot proceed until answered).
4. Get the user's approval, then record it in the spec before drafting a plan: change Status
   from DRAFT to APPROVED, date the approval, and keep each unresolved BLOCKED item as an
   explicit preimplementation gate. A plan never calls requirements approved while its source
   still says DRAFT.
5. A plan may sequence work around an open gate, but implementation does not cross it until
   the requirement is confirmed and recorded.

## Executing a Large Plan

For a plan with several units or more than one agent:

- The implementer and the reviewer are different agents, and each review round uses a fresh
  reviewer, because an agent reviewing its own work misses what it assumed.
- Each unit's proof is either a command whose output shows it passed or a named reviewer
  check; "reviewed" alone is not a proof.
- Before implementing, confirm the approval is on disk (the plan's Status line), not only in
  the chat.
- Owner-judgment items take the most reversible default, land in their own commit, and are
  listed in the plan so the owner can accept or revert each one.
