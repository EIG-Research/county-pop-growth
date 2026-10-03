# Idea-Refine Evaluation Criteria

Use the rubric matching the selected primary mode. Evaluate only criteria that can
change the recommendation. Use qualitative comparison unless the user supplies or
approves numerical weights.

For every direction, record:

- the decisive strengths and weaknesses;
- the most fragile assumption;
- the failure condition;
- the evidence gap;
- the smallest uncertainty-reducing check; and
- the evidence that would reverse the recommendation.

## Evidence Status

Label material premises as one of:

- **Observed:** directly supported by cited repository or external evidence.
- **User-confirmed:** supplied or explicitly confirmed by the user.
- **Agent interpretation:** a reasoned reading that remains open to correction.
- **Assumption:** provisionally accepted for comparison.
- **Unknown:** not established and requiring validation.

Do not use the High/Medium/Low Evidence confidence labels as idea scores. Apply them only
to major claims and recommendations in the final Evidence section.

## Research-Question Mode

Evaluate:

1. **Research and policy importance:** Would the answer change understanding or a
   relevant decision? Distinguish importance from topicality.
2. **Estimand clarity:** Is the descriptive quantity, causal effect, mechanism, or
   forecast target explicit and interpretable?
3. **Population, geography, and time fit:** Do these choices serve the question and
   preserve sufficient support and relevance?
4. **Data and measurement:** Are constructs measurable with plausible sources? What
   measurement error, linkage, missingness, comparability, or sample constraints could
   dominate the result?
5. **Identification and inference:** Can the design support the intended claim? What
   counterfactual, variation, interference, anticipation, selection, or power problem
   could invalidate it?
6. **Literature position:** What is documented, and what remains unverified? Never
   score novelty positively without reviewed sources.
7. **Publication relevance and timing:** Is the contribution likely to matter when the
   analysis can be completed? Treat this as provisional without current evidence.
8. **Smallest informative analysis:** Which early result best tests the weakest premise?

Disqualify or reframe a causal direction when no credible path connects the proposed
variation to the estimand. A transparent descriptive direction may dominate a weak
causal one.

## Policy or Communications Product Mode

Evaluate:

1. **Audience need and intended use:** Who will use the product, for what decision or
   understanding, and under what time constraint?
2. **Evidentiary support:** Can the available evidence sustain the intended claim and
   level of specificity?
3. **Accessibility with fidelity:** Can the product reduce complexity without erasing
   uncertainty, definitions, or caveats that change interpretation?
4. **Distinctive contribution:** Does it provide a new result, synthesis, frame, tool,
   or timely application? Mark the claim provisional until sources establish it.
5. **Production feasibility:** What research, writing, design, review, and maintenance
   burden does the direction impose?
6. **Timing and shelf life:** Will the product remain useful at release, and does it
   require a recurring update commitment?
7. **Smallest useful deliverable:** What is the least costly artifact that serves the
   audience's actual use case?

Reject a polished format whose evidence cannot support its implied claim.

## Analytical Tool or Code-Feature Mode

Evaluate:

1. **User value:** Which concrete error, delay, or repeated burden does the tool reduce?
2. **Technical and data feasibility:** Are required inputs, interfaces, and execution
   environments available and stable?
3. **Integration fit:** Does the direction extend the repository's canonical source of
   truth or create a competing path?
4. **Maintenance burden:** Who owns dependencies, generated copies, documentation,
   tests, and failures over time?
5. **Reversibility and failure safety:** Can the change be piloted or removed cleanly,
   and does failure block, warn, or silently mislead?
6. **Existing capability:** Does current repository functionality already solve enough
   of the problem that extension dominates a new subsystem?
7. **Smallest useful test:** What narrow slice proves value and integration fit before
   broad automation?

Penalize convenience that creates false assurance or a second source of truth.

## Workflow or Process Mode

Evaluate:

1. **Friction reduced:** Which observed bottleneck or failure does the change address?
2. **Adoption burden:** What new work, training, or coordination does it impose, and on
   whom?
3. **Reversibility:** Can the team pilot, compare, and withdraw the change safely?
4. **Governance implications:** Does the direction alter authority, approval,
   accountability, or records of decision?
5. **Observable success:** What behavior or outcome will show improvement rather than
   superficial compliance?
6. **Failure and gaming risk:** How could the process become theater, encourage box
   checking, or shift burden without solving the bottleneck?
7. **Smallest testable process change:** What bounded trial can reveal behavioral
   response before a permanent rule is adopted?

Prefer a smaller control-point change when a larger process redesign does not address a
different root cause.

## Convergence Rule

Recommend a direction only when:

- it serves the fixed outcome better on the decisive criteria;
- its failure condition is acceptable or testable;
- the central evidence gap has a plausible validation path; and
- the first step is proportionate and reversible where possible.

When evidence is insufficient to choose, recommend the smallest discriminating test.
When the initially proposed direction remains best, state which alternatives were ruled
out and why.
