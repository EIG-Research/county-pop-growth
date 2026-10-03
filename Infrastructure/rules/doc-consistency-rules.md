---
load: referenced
---

# Document Consistency Rules

The consistency lens (`conceptual-consistency-reviewer`, check ids `CC-*`) checks that a
document describes what its code does, in both directions: claims the code does not support,
and choices the code makes that the document does not disclose. Severity, confidence,
evidence, refutation, and lens ownership follow `Infrastructure/rules/review-contract.md`;
this file adds the claim classes, the assumption ledger, and what not to flag.

## 1. Scope

An empirical claim describes the sample (who, when, where), a variable (measure,
construction, transformation), the method (estimator, fixed effects, clustering, weights), a
data source (name, vintage, frequency), a result's interpretation (direction, magnitude,
significance, causality), a robustness check, or what a table or figure shows.

**The code is the source of truth.** When the document and the code disagree, the finding
describes the document.

Read every section: abstract, data, methods, results, robustness, conclusion, footnotes,
appendices, table notes, and captions. LaTeX includes are followed; in `.qmd` and `.Rmd`, prose
is the document and chunks are code.

Do not flag:

- Theory, literature review, opinion, or policy recommendations not tied to the analysis.
- Writing style, hedging, and prose quality: `eig-reviewer` audits them against
  `Infrastructure/style/docs/eig-writing-style.md`, including its economic-writing section.
- A wrong number (the numbers lens) or a wrong citation or outside figure (the provenance lens).
- A description that is loose but true of every specification it covers.

## 2. Cross-reference protocol

For each claim: find the code it describes, read the whole block, and check that the claim
holds for every specification it covers ("our regressions" means all of them). Quote the
document text and the code. A claim with no corresponding code is unsupported: say where you
looked. Before a HIGH finding, look for the disclosure elsewhere (another script, a footnote, an
appendix, a table note) and record it in `refutation`.

## 3. Claim classes

Severity: HIGH when the text directly contradicts what the code does in its method, variable
definitions, data source, or a table's content, or when the mismatch changes what the main
result means (a causal claim the design cannot support). A claim with no supporting code is HIGH
for a result or robustness check and MEDIUM for a methods description. MEDIUM when the text
omits or loosely states the sample or universe (the eval key's severity for "all workers" said
of a prime-age sample); LOW when the wording is imprecise but unlikely to mislead a careful
reader.

**CC-SAMPLE: the sample or universe differs.** Age, income, and threshold bounds (off by one:
"20 or older" against `> 20`), geography (DC, territories), years, industries, the unit of
observation, a "balanced" panel that is not. A subsample described as everyone ("all workers"
for a prime-age sample). Don't flag when the text states the restriction anywhere a reader of
the result would see it.

**CC-VARIABLE: a variable is defined differently.** Log against level, weekly against annual,
nominal against real, per capita against total, the treatment's timing or coding, the control
list, winsorizing or other transformations. Don't flag a synonym that names the same measure.

**CC-METHOD: the method differs.** The estimator, fixed effects, standard errors, weights,
bandwidths, or bootstrap settings the text names are not the ones the code runs, or a claimed
robustness check, placebo, or alternative specification has no code. Whether the method is
appropriate belongs to the methodology lens.

**CC-CAUSAL: causal wording the design does not support.** Causal verbs (causes, leads to,
results in, drives, produces, generates, triggers, impacts, raises, the effect of) for a
descriptive or correlational analysis, or a
mechanism asserted from a gap ("because employers..."). Don't flag causal wording backed by an
identification strategy the code implements, or wording the text itself qualifies.

**CC-INTERPRET: interpretation and units.** Percent against percentage points, the sign or
direction of an effect, "larger for women" when the code does not show it, significance
described as importance, a result generalized beyond its sample ("workers", "Americans",
"firms", "households" for a subgroup), and precision theater: more decimal places than the data
support (more than one decimal on a survey percentage, "12.347 percent" beside a 2-point margin
of error). Don't flag when the number itself is wrong; that is the numbers lens.

**CC-UNDISCLOSED: a choice the text does not disclose.** A filter, recode, exclusion, imputation,
top-code treatment, or default the code relies on that could change a reported result and that
no part of the document mentions (see the ledger below). Don't flag a choice that cannot change
a reported result.

**CC-DATA: the data source differs.** The dataset, vintage, wave, frequency, or merge the text
names is not what the code loads.

**CC-TABLE: a table or figure is misdescribed.** A column, note, or caption that states fixed
effects, standard errors, a sample, or content the code that produced it does not have.

## 4. The assumption ledger

Undisclosed choices are kept in one ledger, which this lens owns (contract §6). List each
analytical choice the code makes that a reader would need in order to interpret a result:

- thresholds in filters and recodes (`age >= 25 & age <= 54`, `income > 0`, `year >= 2015`);
- defaults with substantive effect: the join type (base R and pandas merges are inner by
  default), missing-value handling, and standard errors (fixest `feols()` reports IID errors
  by default from version 0.13 unless the project calls `setFixest_vcov()`; check the
  installed version and the project's setup code before saying which default applied);
- variable definitions where alternatives exist (employment by hours, earnings, or status; the
  CPI series used to deflate);
- scope (states and territories, the population's age and institutional bounds, years);
- functional form, and the handling of zeros, negatives, top codes, and imputed values.

Each ledger item that is undisclosed and could change a reported result is one CC-UNDISCLOSED
finding. One finding per choice, not per line: a filter repeated in three scripts is one
finding that lists the three places. The rest of the ledger goes in `context` as a short list.

**War-room export.** If a war-room ledger exists for a reviewed script (located under WR-I5 in
`Infrastructure/rules/code-war-room-rules.md`, confirmed by its `project.id` and
`script.path`), read its `assumption_export` before building the ledger. An exported assumption
is disclosed, so do not report it as undisclosed; check whether the code does what it says,
because a recorded belief is not evidence. `stated_by: agent, confirmed: false` entries were
never reviewed by the author; check those first. Most projects have no war room, and a missing
export is never a finding.

## 5. Findings

Findings follow `Infrastructure/rules/review-contract.md` and the findings schema (lens `CC`);
the renderer owns IDs, order, counts, risk, and the HTML. Quote the exact document text that
makes the claim and the code that contradicts or fails to support it; `explanation` says what
the document says against what the code does, and `fix` names the concrete change. Record the
tally in `context`: `Claims checked`, `Consistent`, and `Flagged`, and keep the claim inventory
at `review-reports/_scratch/claim-inventory.csv`: document location, claim, code location, and
status (consistent, inconsistent, unsupported, ambiguous).

The fixest default was checked by a local run on 2026-09-29 (fixest 0.14.2: `feols(y ~ x | g)`
prints "Standard-errors: IID"; after `setFixest_vcov(one_FE = "cluster")` it prints "Clustered
(g)").
