---
load: referenced
---

# Task Completion Verification Protocol

Verify outputs before reporting a task complete, because a claim of success that no command
or inspection backs is the failure this rule prevents. Report what was checked, how, and what
remains unverified.

## Code and analysis scripts
1. Run the relevant script or test command from the project root and confirm it exits 0. Read
   the exit status itself: piping a check into `tail` or `grep` reports the filter's status,
   so a failed check looks passed unless the shell sets `pipefail`.
2. Confirm the expected outputs exist and are non-empty.
3. Spot-check key values for plausible ranges and units.

## Reports, notebooks, and rendered artifacts
1. Rebuild or render with the project's standard command, and read its warnings and errors.
2. Confirm figures and tables render, source paths resolve, and citations resolve.
3. Open the output to confirm it is usable and formatted.

## Data processing
1. Validate row counts, schema, and nulls in key fields.
2. Confirm joins and filters changed the data as expected.
3. Record a short before/after note in the session log.
4. Before analysis relies on a documented definition, check it against the data and against a
   published benchmark, overall and for a subgroup
   (`Infrastructure/rules/data-documentation-rules.md`, DD-8).

## Documentation, configuration, and `Infrastructure/` changes
1. Confirm the paths and commands referenced exist.
2. After changing `Infrastructure/`, run `make brain-sync` and then `make maintenance-check`
   (every registered check, including internal paths); commit the sync output with the change.
   A change confined to the literature store (`Infrastructure/references/literature/`), such
   as a `literature-scout` pass or a codebook intake, changes no generated copy, so it needs
   only `python3 Infrastructure/scripts/run_maintenance_checks.py --only literature-catalog
   --only catalog-staleness --only internal-paths`.
3. When onboarding steps changed, walk them end to end.
