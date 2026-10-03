---
name: idea-refine
description: >-
  Explore and stress-test materially different directions for a rough but understood research,
  communications, analytical-tool, or process idea, then produce a confirmed concept brief without
  repeating intent discovery or starting a plan. Use when the intended outcome is clear but the
  direction to reach it is not.
argument-hint: "<rough-idea-or-confirmed-intent>"
allowed-tools: [Read, Grep, Glob]
---

# Workflow: idea-refine

Turn a rough but understood idea into a defensible concept by expanding the option set,
comparing materially different directions, and confirming what should move downstream.

## Input

Use the request that invoked this workflow together with any confirmed intent brief and
relevant context in `PROJECT.md`, plans, specifications, session logs, literature
catalog entries, dataset registry entries, and files the user placed in scope.

If no idea or confirmed intended outcome is available, route to `interview-me`. Return
to this workflow only after the intended outcome is clear enough to hold fixed while
directions are compared.

## Purpose and Boundary

Own **direction discovery**. Answer: "Which direction best serves the confirmed
outcome, and what must be true for it to work?"

Do not:

- rediscover intent already confirmed upstream;
- convert a rough idea directly into requirements or an implementation plan;
- conduct substantive literature review, data acquisition, analysis, drafting, or
  coding as a substitute for comparing directions;
- present exploratory alternatives as user-approved decisions;
- claim novelty, feasibility, policy relevance, legal permissibility, data
  availability, or current practice without evidence; or
- treat confirmation of a concept as authorization to write files.

Route the confirmed concept downstream:

- use a requirements specification when material requirements remain complex or
  ambiguous;
- use plan-first when the direction and requirements are already clear; or
- stop without persistence when the user does not want to pursue the concept.

## Trigger Test

Run this workflow when the user explicitly asks to ideate, refine an idea, compare
directions, or stress-test a concept.

Otherwise, run it only when all three conditions hold:

1. the intended outcome is sufficiently understood;
2. two or more materially different directions remain plausible; and
3. choosing silently among them could change the research question, estimand,
   audience strategy, analytical architecture, workflow design, cost, risk, or scope.

Do not run it for:

- materially unclear intent — route to `interview-me`;
- approved requirements that only need a plan;
- a clear mechanical edit, diagnosis, factual answer, or narrowly specified task;
- ordinary implementation choices with low reversal cost; or
- a request to execute a direction the user has already selected unless the user
  explicitly asks to reopen or stress-test that choice.

## Prepare

1. Read relevant repository context before questioning or proposing directions.
2. Separate fixed inputs from open choices. Treat user-confirmed and authoritative
   repository values as fixed unless a contradiction or feasibility problem emerges.
3. State the fixed inputs and open directional question concisely.
4. Select exactly one primary mode:
   - research question;
   - policy or communications product;
   - analytical tool or code feature; or
   - workflow or process.
5. Read the matching sections of:
   - `Infrastructure/skills/idea-refine/references/ideation-frameworks.md`; and
   - `Infrastructure/skills/idea-refine/references/refinement-criteria.md`.
6. Read `Infrastructure/skills/idea-refine/references/examples.md` only when an example
   is needed to resolve mode, granularity, or handoff ambiguity.

When an idea crosses modes, choose the mode that defines success and note the secondary
mode. Do not blend all rubrics into a generic checklist.

## Phase 1 — Understand and Expand

### 1. Frame without reopening intent

Restate the directional problem in one or two sentences:

```text
FIXED INPUTS: [confirmed outcome, audience/user, success, constraints, and exclusions]
OPEN DIRECTIONAL QUESTION: [the choice this refinement must resolve]
MODE: [one primary mode]
```

Do not ask again for an audience, success condition, constraint, or exclusion already
confirmed by the user or recorded authoritatively in context.

### 2. Ask only decision-changing sharpening questions

Ask a sharpening question only when its answer would materially change the direction
set or evaluation. Prefer one focused question per turn. Ask no more than three before
expanding; if foundational intent is still missing, stop and route to `interview-me`.

Attach a concise current interpretation so the user can correct the premise. Do not
use a deliberately false or provocative guess.

If the user delegates the open choice, proceed using stated assumptions and mark the
result as an agent recommendation, not a confirmed preference.

### 3. Generate materially different directions

Generate three to five directions. Use only the lenses that create real distinctions;
do not mechanically exhaust the framework reference.

For each direction, state:

- **Direction:** a concrete framing, not a slogan;
- **Why it exists:** the lens or tension that makes it distinct;
- **Central bet:** what must be true for the direction to create value;
- **Failure condition:** what would make the direction uninformative, infeasible, or
  not worth doing; and
- **Evidence gap:** the specific material fact, relationship, or behavioral response
  that is not known; and
- **First discriminating check:** the distinct action that would most reduce that
  evidence gap.

Never substitute a proposed check for the evidence gap itself. Name both separately for
every direction, even in a compact table.

Directions are not materially different when they only rename the same artifact,
change cosmetic presentation, or vary a minor implementation detail. In research mode,
change a consequential element such as the estimand, inferential goal, population,
geography, period, measurement strategy, identification design, or minimum test.

Invite the user to react to the direction set before converging unless the user has
explicitly delegated convergence or requested a one-pass comparison.

When the user's reaction explicitly selects the preferred direction and identifies any
alternative to retain, consume that decision without asking them to choose among the
directions again. Complete the stress test and present the proposed concept brief in the
same turn. A later statement that confirms "the concept" is valid confirmation only if
the proposed concept brief was already visible to the user; otherwise present the brief
and request confirmation before persisting it.

## Phase 2 — Evaluate and Converge

### 1. Apply the mode-specific rubric

Use the selected rubric from
`Infrastructure/skills/idea-refine/references/refinement-criteria.md`. Explain the
criteria that actually decide among the directions. Do not create a weighted numerical
score unless the user requests one and supplies or approves the weights.

For each surviving direction, distinguish:

- observed facts supported by sources;
- user-confirmed preferences;
- agent interpretations;
- assumptions that must be true; and
- unknowns requiring validation.

### 2. Stress-test before recommending

For each surviving direction:

1. identify the most fragile assumption;
2. describe the credible failure condition;
3. identify the smallest check that would most reduce uncertainty;
4. name the most important tradeoff against the alternatives; and
5. state what should remain out of scope for the first test.

In research mode, explicitly assess measurement and identification. Do not recommend a
causal direction merely because it is more interesting. If the proposed design cannot
support the estimand, say so before comparing novelty or publication value.

### 3. Handle evidence honestly

- Mark an unsupported literature-gap claim as **unverified**, not novel.
- Mark uninspected data as **potentially available**, not available or sufficient.
- Mark external legal, regulatory, institutional, and current-practice claims as
  unknown until verified against an authoritative source.
- Use repository sources first. Browse only when external verification is necessary
  and within scope.
- Never manufacture citations or infer a literature consensus from memory.

### 4. Recommend with reasons

Recommend one direction when the comparison supports it. Explain why it dominates the
alternatives on the decisive criteria and what evidence could reverse the recommendation.

If no direction dominates, recommend the smallest discriminating test rather than
forcing false convergence. If the original direction remains best, explain what the
comparison clarified or ruled out.

## Phase 3 — Sharpen and Hand Off

Present a proposed concept brief:

```markdown
## Concept Brief — Proposed

- **Problem or research question:**
- **Audience/User and why now:**
- **Directions considered:**
- **Recommended direction:**
- **Why it dominates:**
- **Data, evidence, design, or implementation requirements:**
- **Key assumptions and validation strategies:**
- **Smallest informative analysis or useful deliverable:**
- **Not doing:**
- **Open questions:**
- **Decision status:** User-confirmed preference or agent recommendation under delegation.
```

Keep the brief at concept resolution. Name the kind of data, evidence, design,
implementation, validation, or governance requirement that matters and the shape of the
smallest test. Do not fix operative requirements that belong in the next specification,
such as exact cohort size, full artifact fields, status taxonomies, approval authority,
retrigger rules, thresholds, acceptance criteria, file layout, or step-by-step workflow,
unless the user already confirmed or explicitly delegated that exact choice.

For a provisional one-pass brief, place these choices under Open questions or identify
them as categories the requirements stage must settle. A concrete example may illustrate
the direction, but must not silently become the proposed operating specification.

Make the **Not doing** list specific: include attractive adjacent work that is excluded
and give the reason. Generic entries such as "avoid scope creep" do not satisfy the
contract.

Ask the user to confirm, correct, reject, or pause the proposed brief. Do not imply that
the recommendation is approved before a clear response.

After confirmation:

1. state the correct downstream stage;
2. ask separately whether the user wants the concept persisted;
3. if authorized, update `PROJECT.md` for durable project framing or create a DRAFT
   requirements specification under `records/specs/`. In a specification,
   convert only the selected direction and user-confirmed or explicitly delegated
   constraints into `MUST`, `SHOULD`, or `MAY` requirements. An unselected direction
   retained as a principal alternative may appear only as clearly non-operative context,
   a not-doing entry, or a future decision trigger; it must not become an optional
   requirement, pilot task, acceptance criterion, or planned comparison without
   separate user confirmation; and
4. do not create `docs/ideas/` or another concept-specific persistence system.

## One-Pass and Non-Interactive Use

When the user explicitly requests a one-pass comparison or no interactive follow-up is
possible:

- proceed only if the intended outcome and essential constraints are already fixed;
- state assumptions that substitute for missing reactions;
- present the concept brief as **PROVISIONAL — NOT USER-CONFIRMED**;
- do not write a persistent artifact; and
- stop at the handoff boundary.

If material intent is missing, use the `interview-me` non-interactive blocker behavior.
Do not invent the outcome to keep ideation moving.

## Evidence Contract

When the output contains factual claims, conclusions, or recommendations, close with
the EIG Evidence section required by `AGENTS.md` (Guardrails, Data and evidence):

- **Sources:** repository paths, datasets, or verified URLs supporting the claims;
- **Confidence:** High, Medium, or Low for each major claim or recommendation; and
- **Assumptions:** explicit assumptions, including delegated preferences and unverified
  premises.

Evidence confidence describes support for claims. It is not an alignment score and
must not be converted into numerical idea-quality certainty.

## Verification

Before handing off, verify:

- [ ] The intended outcome was clear enough for idea refinement.
- [ ] Fixed inputs were carried forward without duplicate questions.
- [ ] One primary mode and its matching rubric were used.
- [ ] Three to five materially different directions were explored.
- [ ] Every direction separately named a central bet, failure condition, evidence gap,
      and first discriminating check.
- [ ] Research directions addressed measurement and identification when applicable.
- [ ] Unsupported novelty, data, legal, and current-practice claims remained provisional.
- [ ] The recommendation used decisive criteria and named reversal evidence.
- [ ] The smallest informative test targets the riskiest premise.
- [ ] The Not doing list contains real, reasoned exclusions.
- [ ] The brief's decision status is explicit.
- [ ] The brief did not fix unconfirmed operative requirements that belong in the next
      specification or plan.
- [ ] Content confirmation and persistence authorization remained separate.
- [ ] No specification, plan, research output, or implementation began prematurely.
- [ ] Claim-bearing output included Sources, Confidence, and Assumptions.

## Red Flags

- Repeating audience, success, or constraint questions answered upstream.
- Generating many shallow variations or cosmetic alternatives.
- Applying software-product language to research or team-process ideas.
- Treating novelty, data availability, or policy context as known without evidence.
- Ranking a causal idea highly without testing identification credibility.
- Recommending the most ambitious direction because it sounds more consequential.
- Producing a requirements list or implementation plan instead of a concept brief.
- Specifying exact workflow fields, statuses, authority, thresholds, acceptance tests,
  or file layout while simultaneously claiming those choices remain for the next stage.
- Writing an ideas file immediately after content confirmation.
- Calling an agent recommendation user-confirmed.
