---
name: interview-me
description: "Run a restrained one-question-at-a-time intent interview, then produce a confirmed intent brief; in non-interactive contexts, stop on missing material intent instead of guessing. Use when the desired outcome is materially underspecified."
argument-hint: "[topic-or-request]"
allowed-tools: ["Read", "Grep", "Glob"]
---

# Workflow: interview-me

Establish what outcome the user actually wants before specification, planning, or
implementation locks in the wrong problem.

## Input

Invoke as `/interview-me [topic-or-request]`.

Arguments: $ARGUMENTS

Use the request that invoked this workflow together with relevant context already
available in `PROJECT.md`, recent plans, specifications, session logs, and the files the
user placed in scope.

If no request or topic was provided, ask one question to establish it and wait.

## Purpose and Boundary

This workflow owns **intent discovery**. It answers: "What outcome does the user
actually want?"

It does not:

- generate a broad set of solution directions;
- write requirements;
- create an implementation plan;
- begin substantive research or code work; or
- treat confirmation of meaning as permission to write files.

Downstream stages consume its confirmed intent brief:

- use `idea-refine` if materially different directions remain open;
- use a requirements specification if the direction is selected but requirements are
  complex or ambiguous; or
- proceed to plan-first when the outcome, direction, and requirements are clear.

## Trigger Test

Run the full interview when the user explicitly asks to be interviewed or grilled about
what they want and the context is interactive.

Otherwise, run it automatically only when all three conditions hold:

1. at least one essential intent field is unresolved — outcome, audience/user, success
   criterion, binding constraint, or material exclusion;
2. silently assuming the answer could change the artifact, research question, estimand,
   audience, or implementation class; and
3. the answer is not already available in repository context.

Do not run the full interview for:

- clear and self-contained requests;
- mechanical edits or file operations;
- pure information or explanation requests;
- diagnosis requests whose requested output is already clear;
- ordinary implementation details that can be handled through the existing concise
  clarification protocol; or
- non-interactive automation, scheduled runs, or autonomous loops.

In a non-interactive context, identify the missing material intent as a blocker rather
than guessing. The response must be a compact blocker containing:

- the material intent fields that are missing;
- why those fields could change the class of work; and
- the single user decision or confirmed brief needed before a later interactive run.

Stop there. Do not propose a project title, research question, product, audience,
requirements, data architecture, or implementation plan as a substitute for the
missing user response.

## Pre-Question Context Check

Before asking the user:

1. Read `PROJECT.md` when working in a project repository.
2. Review relevant recent plans, specifications, session logs, and files in scope.
3. Separate facts observed in those sources from your interpretation.
4. Do not ask for information already recorded or directly inferable with high
   confidence from the sources.
5. If the title is missing because the user is forming a new project, stay inside the
   bounded project-framing exception in `AGENTS.md` (Guardrails).

## Alignment Readiness

Use a categorical status, not a numerical percentage:

- **NOT READY:** The desired outcome or intended audience/user is still unclear, or a
  material assumption could change the class of work.
- **NEARLY READY:** The outcome is clear, but one or more material success, constraint,
  scope, or delegation questions remain.
- **READY:** The full intent brief can be stated, no unresolved assumption is likely to
  change the class of work, and you can anticipate the likely reaction to the next
  material questions you might ask.

Whenever the status is NOT READY or NEARLY READY, name the unresolved fields in one
line. Alignment readiness measures shared understanding, not the evidentiary confidence
of a factual claim. Never substitute it for the High/Medium/Low confidence ratings
required by the EIG Evidence standard.

## Interview Process

### Step 1: State the working hypothesis

Start with one concise sentence describing your current best interpretation, followed
by alignment readiness:

```text
WORKING HYPOTHESIS: [one-sentence account of the outcome the user wants]
ALIGNMENT READINESS: NOT READY — unresolved: [material fields]
```

The hypothesis must be defensible from the user's words or repository context. State
uncertainty plainly.

### Step 2: Ask one question with a working guess

Ask exactly one focused question per turn:

```text
QUESTION: [one material question]
CURRENT GUESS: [your best answer and the context or reasoning supporting it]
```

Then wait for the user's response. Do not include a second question disguised after a
semicolon, parenthesis, or list. The next question should depend on the answer just
received.

Attaching a guess exposes assumptions and makes correction easier. It must not be used
to manipulate the user:

- welcome correction explicitly;
- do not intentionally make a false or provocative guess;
- do not imply that agreement is the sophisticated or preferred answer; and
- watch for anchoring when the user simply echoes the guess.

After each answer, update the working hypothesis or readiness only when the new
information warrants it. If readiness has not increased after three consecutive
questions, stop and reframe the missing foundational issue instead of continuing
mechanically.

Keep intent discovery at the outcome boundary. Ask only about an uncertainty that
could still change the desired outcome, audience/user, success condition, binding
constraint, exclusion, or delegated authority. Once those fields are materially clear,
present the proposed restatement immediately. Do not keep interviewing to settle an
operational definition, dataset, geography, measurement rule, research design, or
implementation choice that can be recorded as an open downstream decision without
changing the class of work.

### Step 3: Distinguish preference from convention

Probe when an answer relies on an unspecified convention, buzzword, or obligation —
for example, "standard," "modern," "robust," "scalable," or "I suppose I should."

Use a neutral question such as:

> Putting convention aside, which concrete outcome would make this worth doing for
> you?

Do not assume that conventional practice is wrong. The purpose is to identify whether
it is the user's actual priority or an unexamined proxy.

### Step 4: Handle delegated judgment

"Use your judgment" can be a valid delegation rather than evidence of confusion.
Accept it when the decision is within the agent's authorized scope and you can state:

- the recommended choice;
- the principal alternative;
- the material tradeoff;
- the assumptions supporting the recommendation; and
- which preference remains delegated rather than user-confirmed.

Continue interviewing only if the delegated choice depends on values, authority, risk
tolerance, or external consequences that the agent should not choose for the user.
Delegation never waives evidence, research, safety, or change-control guardrails.

### Step 5: Restate the intent

When alignment readiness is READY, present a concise brief using the user's language
where possible:

```markdown
## Confirmed Intent — Proposed Restatement

- **Outcome:**
- **Audience/User:**
- **Why now:**
- **Success:**
- **Binding constraint:**
- **Out of scope:**
- **Delegated decisions:** None, or list the decision and assumptions.
```

Readiness depends on material intent, not on collecting a separate user statement for
every field. In particular, do not prolong the interview solely because the user has
not named a time-sensitive trigger. If timing is not material to the requested outcome,
record `Why now` as `No separate time-specific trigger identified` and, if useful, add
a clearly labeled agent interpretation of the present value. Never silently convert an
unanswered material field into a confirmed preference.

Ask the user to confirm or correct the restatement. Require a clear affirmative response
that refers to the restatement, but do not require a ritual exact word. If the user
corrects a line, incorporate the correction and restate only what materially changed.
A corrective response is not confirmation unless it also clearly affirms the revised
brief. After a correction, request confirmation again; do not enter `idea-refine` or
another downstream stage merely because the original request anticipated that handoff.

### Step 6: Separate confirmation from persistence

After the content is confirmed:

1. State the correct downstream stage.
2. Ask separately whether the user wants the intent persisted.
3. If authorized:
   - update `PROJECT.md` for durable project framing; or
   - create a DRAFT requirements specification under `records/specs/` for a
     feature, workflow, or substantial project task.
4. Do not create a separate intent or ideas directory.

## High-Stakes, Urgent, and Non-Converging Cases

- **High stakes:** Ask the smallest number of intent questions needed, but do not waive
  evidence, methodology, safety, or legal constraints.
- **Urgency:** Reduce conversational overhead by prioritizing the assumption most likely
  to change the work. Urgency alone is not permission to guess a material objective.
- **Non-convergence:** If several questions do not increase readiness, state the
  foundational uncertainty and ask whether to step back, narrow the task, or stop.
- **Non-interactive context:** Return only the compact blocker defined in the Trigger
  Test. Do not perform speculative framing work merely because no user can respond.
- **User stops the interview:** Respect the stop. Report the unresolved assumptions and
  whether they block further work; do not pretend READY status was reached.

## Output Contract

The deliverable is a user-confirmed intent brief, not a specification or plan. It must
make observed context, user-confirmed preferences, delegated decisions, and agent
interpretations distinguishable.

If the brief only restates user-confirmed intent, do not manufacture an Evidence
section. If it adds factual claims, conclusions, or recommendations — including a
recommended delegated choice — close with the EIG Evidence section required by
`AGENTS.md` (Guardrails, Data and evidence).

## Verification

Before handing off, verify:

- [ ] The trigger test justified a full interview, or the user explicitly invoked it.
- [ ] Relevant repository context was checked before questioning.
- [ ] The initial working hypothesis and alignment readiness were explicit.
- [ ] Every turn asked exactly one material question with a defensible current guess.
- [ ] No deliberately false or manipulative guess was used.
- [ ] Readiness changes were tied to information received.
- [ ] Delegated judgment was accepted or declined using the stated boundary.
- [ ] The restatement covered outcome, audience/user, why now, success, binding
      constraint, out of scope, and delegated decisions.
- [ ] The user clearly confirmed the restatement.
- [ ] Content confirmation and file-write authorization were separate.
- [ ] The downstream stage was selected without repeating resolved questions.
- [ ] Any claim-bearing recommendation included Sources, Confidence, and Assumptions.

## Red Flags

- Asking multiple questions in one turn.
- Interviewing a clear or mechanical request.
- Asking for context already present in the repository.
- Treating a readiness category as factual evidence confidence.
- Refusing a safe, well-specified delegation merely because the user did not express a
  preference.
- Producing a specification, plan, research output, or code before confirming intent.
- Updating `PROJECT.md` immediately after content confirmation without separate write
  authorization.
- Repeating audience, success, or constraint questions in downstream stages.
