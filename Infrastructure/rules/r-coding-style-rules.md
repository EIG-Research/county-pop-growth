---
load: paths
paths:
  - "code/*.R"
  - "code/**/*.R"
  - "**/*.Rmd"
  - "**/*.qmd"
---

# R Coding Style Rules

These rules govern project-authored R: `.R` scripts and the R chunks in `.Rmd` and `.qmd`
files (the opening block and header apply to whole scripts, not chunks). Research
assistants must be able to read, audit, and modify every script, so prefer explicit
intermediate objects, descriptive names, and visible steps over compressed abstractions.
When an approved project requirement conflicts with this rule, follow the requirement and
record the exception next to the code or in the session log.

## 1. Script opening and header

Every `.R` script begins with:

```r
# NN_script_name -- one-line description
# Author - *Insert Human Author Here*
# research title -
# research question -

rm(list = ls())
options(scipen = 999)
set.seed(42)
```

- Prefix analysis scripts with two digits so execution order is visible. `run_all.R` is the
  unnumbered orchestrator and uses its filename in place of `NN_script_name`.
- Replace the author placeholder with the responsible human author before substantive work.
  Do not list an AI system as the author.
- Keep the three statements in this order even when a script uses no randomness, so every
  script runs directly and later stochastic code stays reproducible. `rm(list = ls())`
  clears objects only, not attached packages, options, or the RNG state; running the
  script in a fresh process, as `Rscript` does, is what isolates it.

## 2. Structure and comments

Divide each script with section banners 80 characters wide, the name centered, numbered in
processing order:

```r
################################################################################
###                             1. Load packages                             ###
################################################################################
```

- Number steps within sections as `# 1) Step name`, `# 2) Step name`, to expose the logic,
  not to narrate syntax.
- Break a long chain into named intermediate objects when it would otherwise hide a sample
  restriction, recode, join, or calculation.
- Keep lines within 80 characters; `make check-project` lints `code/` with `.lintr`.

## 3. Packages, pipes, and paths

- Use tidyverse functions by default for data work, and base R for orchestration,
  filesystem work, package checks, or where it is materially clearer.
- Use the base pipe `|>`; do not add `%>%` to new code.
- Qualify functions as `pkg::fn()` when provenance would be ambiguous, and follow one
  package-loading convention within a script.
- Call `here::i_am("code/NN_script_name.R")` near the top of each script and build every
  path with `here::here()`, so a script started outside the project stops instead of
  reading or writing elsewhere. Do not hard-code absolute or user-specific paths.
- Pinning package versions with renv is optional; `make renv-bootstrap` sets it up.

## 4. Progress and diagnostics

- Report progress with `message()`, naming the step, input, output, or count. Do not use
  `cat()` or `print()` as progress reporters; functions that write a file are fine.
- Stop fatal conditions with `stop()`, naming the failed operation and the object, file,
  or condition involved.

## 5. Names and types

- Keep raw variable names exactly as received (for example, IPUMS `AGE` and `EMPSTAT`).
  Use snake_case for derived variables and R objects.
- Add a transformation-state suffix only when it is accurate: `_int` (integer-valued),
  `_num` (numeric conversion), `_flag` (logical or binary indicator), `_valid` (validity
  check or valid universe), `_real` (inflation-adjusted), `_nominal` (current dollars).
- Use typed missing values (`NA_real_`, `NA_integer_`, `NA_character_`) and the `L`
  suffix on intended integers, including comparisons and `logical(1L)`.

## 6. Project-defined functions

Prefer inline code, because reviewers audit what they can see. A named function is allowed
when it is short, defined once (at the script top, or in `00_functions.R` in `code/`, which
each script that uses it sources; it is not a runner stage), and opens with a one-line
purpose comment. A function that encodes a sample restriction, weights, or estimation needs
the human's approval first when the session is interactive, because those choices must stay
visible; otherwise write it inline and report the open question. Record approvals next to
the function or in the session log. Anonymous callbacks a standard API requires, such as
`error = function(e)` in `tryCatch()`, need no approval.

## 7. Data checkpoints

Save tabular data at logical checkpoints in both R-native and interoperable formats,
using the same file stem:

```r
saveRDS(checkpoint_data, file.path(path_processed, "checkpoint_name.rds"))
arrow::write_parquet(
  checkpoint_data,
  file.path(path_processed, "checkpoint_name.parquet")
)
```

- Use `.rds` to preserve R-native types and `.parquet` for interoperable access (arrow
  compresses with Snappy by default). Both files hold the same variables in the same row
  order. Parquet keeps haven labels for R readers, not for Python or Stata.
- Save only at documented boundaries, such as after cleaning, merging, or constructing the
  analytic sample, not after every mutation.
- Save non-tabular objects that Parquet cannot represent as `.rds` only, with the reason
  next to the save call or in the session log.

## 8. Reading, joining, and filtering

- Read raw files with explicit column types, such as `readr::read_csv(col_types = ...)`,
  so a changed file surfaces as parsing problems instead of silently re-guessed types.
- Give every join its expected cardinality with `relationship =` (dplyr 1.1.0 or later),
  add `unmatched = "error"` where a dropped key would be a bug, and check row counts before
  and after with `stopifnot()` or an informative `stop()`.
- For survey weights, use the weight that the dataset's entry in
  `Infrastructure/references/datasets/registry.yaml` documents, and name it in a comment.
- Use `tryCatch()` only for meaningful recovery, context, or cleanup, never to hide an
  error.
- Filter with vectorized masks, not row-index loops. Name the mask when the condition is
  nontrivial, reused, or defines the analytic sample.
- A comparison with `NA` returns `NA`, and base `df[mask, ]` turns each `NA` into an
  all-`NA` row. Guard the mask with `!is.na()` and filter with `dplyr::filter()`, which
  drops `NA`:

```r
prime_age_valid_flag <-
  !is.na(analysis_data$age_num) &
  analysis_data$age_num >= 25L &
  analysis_data$age_num <= 54L &
  !is.na(analysis_data$employment_status_valid)

prime_age_data <- dplyr::filter(analysis_data, prime_age_valid_flag)
```

## 9. Pipeline orchestration

`code/run_all.R` (run by `make pipeline`) stops unless `here::i_am()` finds the project,
toggles scripts with one named logical vector after the opening block, in run order, and
runs each selected script from the project root in a fresh `Rscript` process, so the
project `.Rprofile` (renv) loads and no object, package, or option leaks between scripts.
It appends each script's output and `sessionInfo()` to one log under `output/logs/`,
headed by the R version, git commit, and `renv.lock` hash, and stops at the first missing
or failing script, naming it. Each numbered script therefore keeps the opening block and
loads its own packages and paths, so it also runs directly.
