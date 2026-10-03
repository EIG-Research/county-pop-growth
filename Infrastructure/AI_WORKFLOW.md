# AI Workflow

Use this workflow for a non-trivial task, after the startup reads in `AGENTS.md`. It is the one
home of discovery routing.

## 1) Frame the task
- Select the earliest unresolved stage:
  - **Intent discovery:** the intended outcome itself is materially unclear, and
    assuming it could change the artifact, research question, estimand, audience, or
    implementation class.
  - **Idea refinement:** the outcome is understood, but materially different directions
    remain open.
  - **Requirements specification:** the direction is selected, but requirements remain
    complex or ambiguous.
  - **Direct planning:** the outcome, direction, and material requirements are clear.
- Use a full discovery workflow automatically only when ambiguity is material and the
  session is interactive. Clear, mechanical, diagnostic, and purely informational
  requests bypass discovery.
- When ambiguity is material but a full workflow is not warranted, ask the fewest direct
  questions needed to proceed safely.
- If material intent is unresolved in a non-interactive context, report the missing
  decision as a blocker and stop. Do not select or elaborate a project, product,
  audience, research question, specification, or plan on the user's behalf.
- Consume confirmed upstream answers. Do not re-ask resolved questions when moving
  from intent to refinement, specification, or planning.
- Carry confirmed or authoritative repository values forward as fixed inputs unless a
  contradiction or material feasibility problem emerges. A downstream checklist may
  verify those values, but must not present them as unresolved decisions.
- Once the relevant discovery stages are complete, state the task in one sentence and
  propose a short plan.
- Confirm assumptions if risk is high.
- When the task meets the plan threshold in `AGENTS.md`, follow
  `Infrastructure/rules/plan-first-workflow.md`: save the plan to `records/plans/` and
  get approval before implementing.

## 2) Execute
- Make the smallest change that moves the task forward.
- Reuse `Infrastructure/` guidance instead of duplicating rules.
- For expensive or long-running jobs, apply `Infrastructure/rules/performance-cost-governance.md` before execution.

## 3) Validate
- Run the verification steps in `Infrastructure/rules/verification-protocol.md` for the
  output type at hand. Do not report completion without them.
- Check that output answers the task and aligns with `PROJECT.md`.
- Verify no guardrail violations.
- Apply the evidence standard in `AGENTS.md` (Guardrails, Data and evidence), which
  says when an output needs an `Evidence` section.
- Note any limitations.

## 4) Handoff
- Summarize: what changed, why, and what remains.
- Confirm whether evidence standard was applied and why.
- Log decisions, corrections, and blockers per `Infrastructure/rules/session-logging.md`, and
  add a full session log from `Infrastructure/templates/session_log.md` when the cadence in
  `PROJECT.md` calls for one.
- Save recorded logs in `records/session_logs/`.
