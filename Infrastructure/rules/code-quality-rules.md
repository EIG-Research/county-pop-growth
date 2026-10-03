---
load: referenced
---

# Code Quality Rules

The code lens (`code-reviewer`, check ids `CE-*`) finds definitive bugs in research code and
material efficiency or readability improvements. Severity, confidence, evidence, refutation,
and lens ownership follow `Infrastructure/rules/review-contract.md`; this file adds the code
lens's failure classes, what not to flag, and a per-language appendix.

## 1. Goal and scope

A **bug** produces wrong values, data, or estimates; silently loses or corrupts data; stops the
pipeline; or makes results irreproducible. A **suggestion** makes the pipeline materially
faster, lighter on memory, or clearer, and never changes a result.

Do not flag:

- Style preferences (naming, indentation, comment density), except the binding R standard below.
- Research design, inference, weights, or deflators: the methodology lens owns them.
- Bugs that need inputs the project never has, and deprecation warnings that change nothing yet.
- Micro-optimizations with no measurable effect.

**Binding R standard.** When the files include project-authored R (`.R`, `.Rmd`, `.qmd`), read
`Infrastructure/rules/r-coding-style-rules.md`. Report material deviations as `CE-EFFICIENCY`
suggestions unless they affect correctness or reproducibility, then use the matching bug class.
Group repeats by rule rather than one finding per line. If human approval for a
project-defined function cannot be confirmed from repository records, ask a Question; do not
assert that approval was absent.

## 2. Verification

The pipeline has just run successfully (contract §2), so code on its main path does not crash
and every output exists. Use that:

- A bug is reported only with the quoted lines and a check: a scratch script in
  `review-reports/_scratch/` on the project's data or a two-line synthetic case, the package
  documentation, or the pipeline log (`review-reports/pipeline-run.json`).
- Before a HIGH or CRITICAL finding, look for code that handles the case elsewhere (an earlier
  filter, an `assert`, a `distinct()`, a checked `_merge`) and record it in `refutation`.
- A behavior that depends on a package version is checked against the installed version.
- What you cannot confirm lowers the confidence or becomes a Question; it is not a bug.
- Every discovered code file appears in `files_reviewed`; an unreadable one gets a Question.

## 3. Failure classes

Severity is the worst realistic outcome if the bug is real: a wrong number that reaches a
reported result is HIGH (CRITICAL only when it changes the conclusion); a wrong secondary
statistic or a warning users may ignore is MEDIUM; a break that is unlikely with the project's
data, such as an absolute path, is LOW.

**CE-RUNTIME: code that errors.** A branch the pipeline did not run (a flag, a loop that ran
zero times, an `.Rmd` chunk with `eval = FALSE` that the text relies on). MEDIUM, since the run
skipped it; HIGH when a reported result depends on that branch. Don't flag when the pipeline
log shows the code ran.

**CE-LOGIC: wrong logic.** Wrong conditions or operators, overwritten objects, `I()` missing in
an R formula, grouping left on after `group_by()`, `as.numeric()` on a factor (returns level
codes), a result assigned back after `groupby().agg()` on a misaligned index, a Stata local
referenced from a different do-file or from a do-file run in pieces. Don't flag when the code's
output shows the intended result.

**CE-JOIN: join cardinality and unmatched keys.** A join that multiplies rows or drops them
unexpectedly: many-to-many keys (dplyr 1.1.1 or later warns on a many-to-many match, and
`relationship = "many-to-many"` silences it; 1.1.0 warned on any multiple match; Stata
`merge m:m`), a base R `merge()` or pandas `merge()` that
is inner by default, keys of different types. Don't flag when uniqueness is enforced or checked
(`validate=` in pandas, `relationship = "one-to-one"` or `"many-to-one"` in dplyr, `merge 1:1`
or `m:1` with `assert()`, `isid`, a `distinct()` or row-count check before and after).

**CE-MISSING: missing values.** `na.rm = TRUE` or pandas `skipna` (the default) hiding missing
data behind a statistic reported as covering everyone; Stata missing values compared as larger
than any number (`if x > 0` keeps missings); `egen total()` and `rowtotal()` treating missing as
zero; a filter after a left join dropping unmatched rows silently; fixest dropping observations
with missing values, and from 0.13 (default `fixef.rm = "perfect_fit"`) observations perfectly
fit by the fixed effects, singletons included, with only a printed note (before 0.13 singletons
stayed in). Don't flag when the
missing rows are counted and reported, or when the statistic is described as covering
non-missing values.

**CE-TYPE: type coercion.** Leading zeros lost when FIPS, ZIP, or NAICS codes are read or cast
as numbers (base `read.csv()`, pandas `read_csv()`, an explicit `col_integer()`, Stata `import
delimited` without `stringcols()`); `destring, force` turning nonnumeric strings into missing;
`haven` labelled columns used as numbers; `ifelse()` dropping date or factor attributes. Don't
flag when the codes are read as strings or padded back (`str_pad`, `zfill`, `%05.0f`).

**CE-SEED: randomness.** Sampling, bootstrap, simulation, or train/test splits with no seed, or a
seed set after the random call. Don't flag deterministic code or a seed set once upstream of
every random call in the same process.

**CE-PATH: reproducibility breaks.** Absolute or user-specific paths, `setwd()`, reads from
outside the project, dependence on objects left in the session. Don't flag paths built from the
project root (`here::here()`, a root variable).

**CE-EFFICIENCY: suggestions (SUGGESTION only).** Row-by-row loops that vectorize, repeated
reads of the same file, growing objects in loops, very large CSVs where Parquet would cut
I/O, opaque one-liners that need named steps. Report only an improvement a reader would
notice: minutes of runtime, gigabytes of memory, or a block that cannot be followed. Never
report a suggestion as a bug.

## 4. Findings

Findings follow `Infrastructure/rules/review-contract.md` and the findings schema (lens `CE`);
the renderer owns IDs, order, counts, risk, and the HTML. Quote the problematic code as it
appears in the file, and put the corrected code in `fix`. Data currency (whether a newer
release of a public dataset exists) is not a code finding; the `document-data` workflow checks
it.

## Appendix A. Per-language checks

Consult the list for the file's language; it is a reference, not a checklist to walk.

**Python (pandas, numpy, statsmodels, linearmodels).**
- Chained assignment: under pandas 3.0 copy-on-write, `df[mask]["col"] = v` never changes `df`
  (it emits a `ChainedAssignmentError` warning, and `SettingWithCopyWarning` no longer exists); use
  `df.loc[mask, "col"] = v`. Before 3.0 it only warned.
- `merge()` defaults to `how="inner"`; `validate=` raises `MergeError` when keys are not unique.
- `read_csv()` infers `01001` as the integer 1001; pass `dtype={"fips": str}`.
- Reductions skip missing values by default (`skipna=True`).
- Masks built before `reset_index()` applied after it; formula strings naming absent columns.
- `DataFrame.append()` was removed in pandas 2.0.

**R (base, tidyverse, fixest, haven).**
- `mean()` without `na.rm` returns `NA`, which is loud; `na.rm = TRUE` is the silent risk.
- dplyr 1.1.1 and later warn on an unexpected many-to-many join (1.1.0 warned on any multiple
  match); `relationship =` states intent.
- base `merge()` is an inner join unless `all`, `all.x`, or `all.y` is set.
- `readr::read_csv()` keeps `01001` as character, but `col_integer()` or `as.numeric()` drops
  the zero; `read.csv()` reads it as 1001.
- fixest drops rows with missing values with a `NOTE`; from 0.13 its default
  `fixef.rm = "perfect_fit"` also drops observations perfectly fit by the fixed effects,
  singletons included, while earlier versions kept singletons. Compare `nobs()` with the
  expected N, and check the installed version.
- `df["col"]` returns a data frame and `df[["col"]]` a vector; short vectors recycle silently.

**Stata.**
- Local macros exist only within the do-file or program that defines them: a do-file run in
  pieces, or a local set in another do-file, reads as empty.
- `merge m:m` pairs observations by order within a key (the manual calls it "a bad idea"); use
  `1:1`, `1:m`, or `m:1` with `assert(match)` or a checked `_merge`.
- Missing (`.`) sorts above every number, so `if x > 0` includes missing values.
- `egen total()` and `rowtotal()` treat missing as zero; `egen mean()` skips missing values.
- `capture` suppresses all output, error messages included, and continues, so an unchecked
  `_rc` hides a failure; `quietly` hides output, but a failing command still stops the do-file.
- `destring, force` converts nonnumeric strings to missing; check what was lost.
- `preserve` without `restore`; panel commands before `xtset`; scalars sharing a variable's name.

## Appendix B. Sources for the examples

Checked 2026-09-29. Local runs used R 4.5.2 with fixest 0.14.2, readr 2.2.0, and dplyr 1.2.1,
and Python with pandas 3.0.5; the commands and outputs are in the template's 2.0.0
development records, in git history.

| Example | Source |
|---|---|
| pandas chained assignment, `ChainedAssignmentError`, no `SettingWithCopyWarning` | local run (pandas 3.0.5); pandas "Copy-on-Write" user guide |
| pandas `merge` inner default, `validate=` raises `MergeError` | local run; `pandas.DataFrame.merge` reference |
| pandas `read_csv` reads `01001` as 1001; `skipna` default | local run |
| R `mean(c(1, NA, 3))` is `NA`; with `na.rm = TRUE` it is 2 | local run |
| dplyr many-to-many warning and `relationship =` | local run (dplyr 1.2.1); dplyr `mutate-joins` reference |
| base `merge()` inner by default; `as.numeric(factor(c("10", "20")))` gives 1, 2 | local run |
| `readr::read_csv` keeps `01001`; `read.csv` gives 1001 | local run |
| fixest NA and singleton removal notes; `fixef.rm` default `"perfect_fit"` | local run (fixest 0.14.2, `formals(feols)$fixef.rm`); fixest news for 0.13.0 |
| dplyr many-to-many-only warning from 1.1.1 | dplyr news for 1.1.1 |
| Stata local macro scope | Stata [P] macro: local macros "exist solely within the program or do-file in which they are defined" |
| Stata `merge m:m` | Stata [D] merge: "m:m specifies a many-to-many merge and is a bad idea" |
| Stata `egen total()`, `rowtotal()` | Stata [D] egen: the sum "treating missing as 0" |
| Stata `capture` | Stata [P] capture: suppresses "all its output (including error messages, if any)" |
| Stata `quietly` | Stata [P] quietly: "suppresses all terminal output for the duration of command" |
| Stata `destring, force` | Stata [D] destring: "convert nonnumeric strings to missing values" |
| Stata `import delimited`, `stringcols()` | Stata [D] import delimited: read columns "as string to preserve leading zeros" |
