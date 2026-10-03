---
name: maintenance-check
description: >-
  Run the repository maintenance sweep (generated-copy drift, internal path integrity, literature
  catalog, freshness signals) and report prioritized actions. Use when auditing repository
  hygiene, or after changing Infrastructure/.
argument-hint: "[scope-hint]"
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash(make maintenance-check)
---

# Workflow: maintenance-check

Run the repository maintenance sweep and report prioritized actions. It is done when every
check has run and a report built from `Infrastructure/templates/maintenance-report.md` gives
each check's status, the findings by severity, and a remediation command for each.

## Input

The argument is optional. When present, treat it as a scope hint (for example a check name
such as `style-tokens`, or `deps` to focus on dependency freshness). With no argument, run the
full sweep.

## Steps

1. Run the whole check suite with a single command:

```bash
make maintenance-check
```

`make maintenance-check` delegates to `Infrastructure/scripts/run_maintenance_checks.py`,
which owns the registry (`--list` prints it), runs every check, continues past failures, prints
a per-check PASS/FAIL/SKIP summary with timings, and exits non-zero if any check failed.

2. Run dependency freshness checks for whichever stack files are present:

   - Python (`requirements*.txt` or `pyproject.toml`): `python3 -m pip list --outdated`
   - R (`renv.lock`): `Rscript -e "if (requireNamespace('renv', quietly = TRUE)) renv::status() else cat('renv not installed\n')"`
   - Node (`package.json`): `npm outdated`

   These are not part of the check suite because they depend on the local toolchain and on
   network access. Report `INFO` when a check cannot run in the current environment rather
   than treating it as a failure.

3. If the project has analysis code, perform the dataset coverage review described in MT-6
   of `Infrastructure/rules/maintenance-rules.md` — recognized datasets loaded in code but
   absent from the registry, variable vintages older than the data the code uses, and
   registry variables no longer referenced anywhere.

4. Classify every finding by severity using `Infrastructure/rules/maintenance-rules.md`
   (its MT check families). Report each check that ran, including the ones that passed.

5. Compile the report using `Infrastructure/templates/maintenance-report.md`.

## Output

A maintenance report containing:

1. Every check that ran, with its exact command and PASS/FAIL status — passes included.
2. Findings grouped by severity per `Infrastructure/rules/maintenance-rules.md`.
3. Exact remediation commands for every HIGH and MEDIUM finding.
4. A "do now" versus "do later" action list.
5. A rerun plan that verifies the fixes end to end.
