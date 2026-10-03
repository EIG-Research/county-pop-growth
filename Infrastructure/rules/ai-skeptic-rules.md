---
load: referenced
---

# AI Skeptic Review Rules

The provenance lens (`ai-skeptic`, check ids `AS-*`) verifies what a project takes from
elsewhere: citations and the findings attributed to them, figures from outside sources,
functions and their arguments, dataset variables, and what comments say the code does.
Severity, confidence, evidence, refutation, and lens ownership follow
`Infrastructure/rules/review-contract.md`; this file adds the check families, how to verify
each, and what not to flag.

## 1. Goal

AI-assisted code and prose fail in characteristic ways: a citation that does not exist or does
not say what it is cited for, an external figure copied wrong, a function or variable that
looks standard but is not, and a comment that describes what the code was meant to do rather
than what it does. This lens verifies those references against their sources. It reviews every
file the same way, whoever wrote it, and treats plausibility as a reason to look something up,
not as evidence either way.

## 2. Scope and deference

The lens owns the families in section 4. It defers everything else (contract §6):

| Concern | Owner |
|---|---|
| A bug, crash, or wrong join in the code | code lens (`CE-*`); report here only when the cause is a function, argument, or variable that does not exist |
| Research design, inference, weights, deflators | methodology lens (`MR-*`) |
| Undisclosed choices, causal wording, a result generalized beyond its sample | consistency lens (`CC-*`), which keeps the assumption ledger |
| A document number against the project's own output | numbers lens (`DN-*`) |
| Hedging, AI-prose tells, uncertainty reporting in prose | `eig-reviewer` against `Infrastructure/style/docs/eig-writing-style.md` (its economic-writing and AI-prose sections) |
| Unused imports, generic names | no lens: code style is not a finding, except the binding R standard the code lens applies (`Infrastructure/rules/code-quality-rules.md`) |

When an issue touches two lenses, report your part and name the other lens's check family in
`related`; do not restate its finding.

## 3. Verification

- Look each reference up; do not judge it by how it reads. Use `WebSearch` to find a source and
  `WebFetch` to read it (the publisher's page, the agency release, the package reference, the
  codebook). Record in `verified_by` what was consulted and what it says.
- Record each citation as one of: *matches its source*, *not found*, *misattributed*, or
  *could not check*. "Not found" needs the searches you ran (author and year, title fragment,
  the journal's index); a source you could not reach is *could not check*, a Question.
- Pin versions: a package behavior is checked against the installed version (`packageVersion()`,
  `pip show`), and an agency figure against the release or vintage the text names, since
  figures are revised.
- Before a HIGH or CRITICAL finding, try another route to the source (a working-paper version,
  a later edition, a different release of the series) and record it in `refutation`.

## 4. Check families

**AS-CITATION: a citation that does not exist, or does not say what it is cited for.** Search
prose and code comments for author-year citations. A source that cannot be found after the
searches above is HIGH; a real source cited for a finding it does not contain (checked against
its abstract, results, or conclusion) is HIGH; a wrong year or misspelled author on a source
that clearly exists is LOW. The same source cited inconsistently is LOW. Don't flag a source
you could not reach: that is a Question.

**AS-EXTERNAL: an outside figure that differs from its source.** A number the document takes
from an agency or another paper (a BLS rate, a Census count, a published estimate). Compare it
with the source under the rounding rule in `Infrastructure/rules/doc-number-rules.md` §4. HIGH
when the figure supports a main claim, MEDIUM when it is context. Don't flag a figure that
matches the release or vintage the text names although the series was revised later; note the
revision in `explanation` only if the text implies it is current.

**AS-API: a function, argument, or default that does not exist or does not behave as used.**
The pipeline ran, so a call on its main path exists; check the calls that feed a key result,
and non-core packages (`fixest`, `lfe`, `survey`, `MatchIt`, `rdrobust`, `haven`, `arrow`,
`statsmodels`, `linearmodels`, Stata user-written commands), where a plausible argument can be
silently ignored or a default can differ from what the code assumes. HIGH when a reported
result depends on it; a call that would error sits on a branch the run skipped and is MEDIUM,
as in the code lens. Defaults that are often misremembered:

- fixest `feols()` without `vcov`: IID errors from fixest 0.13 unless the project calls
  `setFixest_vcov()`; before 0.13, clustered by the first fixed effect when there is one.
  Check the installed version and the setup code before saying which applied.
- `merge()` is an inner join by default in base R (`all = FALSE`) and pandas (`how = "inner"`).

Code written for a different version of a package than the one installed (a removed argument, a
changed default) is MEDIUM. Don't flag a call whose effect the code checks (an
`nobs()` comparison, an explicit `vcov`).

**AS-VARIABLE: a dataset variable that does not exist in the named source or vintage.** Trace
each variable used in a filter, formula, or merge key to where it is loaded or created. For a
recognized public dataset, read the registry at `Infrastructure/references/datasets/registry.yaml`
and check the dataset's `known_variables` (a `*` stands for a wave or replicate number; match
case-insensitively) and any `variables` in the project overlay `data/docs/dataset-registry.yaml`.
A listed name confirms the variable exists; a `verified` entry (signed against `sources`) is
authoritative, and an `unverified` or `parsed` one is a lead. Only if the registry does not list
the name, search the codebook for that vintage (for example `"CPS ASEC" codebook "HTOTVAL"`).
HIGH when the variable feeds a reported result and does not exist in that source; MEDIUM when it
exists under a different name or vintage than the text says. Don't flag a variable created
upstream in the project's own code.

**AS-COMMENT: a comment or section header that says something the code does not do.** Treat
each factual comment (`# filter to ages 25-64`, `# cluster at state level`, `# median household
income`) and each banner (`# ==== Data cleaning ====`) as a claim about the code beneath it,
including the variable names it mentions. LOW when the code does what the analysis needs and
only the comment misdescribes it; MEDIUM when the document repeats the comment's version or the
comment hides a material operation (a comment `# clean the data` over a filter that drops 40
percent of rows). Template text left in comments ("# add your cleaning steps here") is LOW.
Don't flag a vague comment that is true.

**AS-EDGE: an edge-case test showing that an operation feeding a key result breaks.** Test only
operations whose output reaches a reported result: division by a possibly-zero denominator,
`log()` of zero or negatives, groups with zero or one row, keys duplicated on both sides of a
join, string and date parsing, and conditions without an `NA` or other-category branch. Record
each result as PASS, FAIL-CRASH, FAIL-SILENT (a wrong result without error), or FAIL-NA.
FAIL-SILENT or FAIL-NA reaching a reported statistic is HIGH (CRITICAL when it changes the
conclusion); FAIL-CRASH on data the project could receive is MEDIUM; a PASS whose handling is
undocumented (an upstream filter nobody comments on) is LOW. Don't flag an edge case
the project's data cannot contain (check the data). The lenses run in parallel, so report a
failing test even when the code lens may find the same bug by reading, and name the `CE-*`
family in `related`; consolidation cross-links findings at the same anchor
(`review_consolidate.py`).

Test-script limits: scripts go in `<target>/review-reports/_scratch/ai-skeptic-tests/`, read the
data only, are self-contained, use a synthetic dataset when the data is too large to load, and
run with a 30-second timeout.

## 5. Findings

Findings follow `Infrastructure/rules/review-contract.md` and the findings schema (lens `AS`);
the renderer owns IDs, order, counts, risk, and the HTML. Each finding states what was claimed
(`evidence.claim`, with the quoted citation, call, or comment), what was found, and how it was
verified (`verified_by`: the search, page, documentation, or test script and its result).

The fixest default was checked by a local run on 2026-09-29 (fixest 0.14.2 prints
"Standard-errors: IID" for `feols(y ~ x | g)` and "Clustered (g)" after
`setFixest_vcov(one_FE = "cluster")`); the merge defaults by local runs of base R `merge()` and
pandas 3.0.5 `merge()`.
