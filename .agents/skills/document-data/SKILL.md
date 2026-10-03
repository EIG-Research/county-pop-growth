---
name: document-data
description: >-
  Acquire and document a project's data source: fetch the vintage-correct codebook, extract the relevant variables, and persist them to the dataset registry and per-variable Markdown. Enforces permission, no-fabrication, and validation.
---

# Workflow: document-data

Document the variables a project uses from one dataset, pinned to the vintage in use. Done when
the variables and their Markdown docs are written and both validators below pass.

The argument is `<dataset>`, optionally followed by `<vintage>`. With no vintage, document the
vintage the analysis code uses and say which one. With no argument, ask which dataset to
document if the session is interactive; otherwise stop and report that none was given.

1. Follow the procedure in `Infrastructure/agents/data-dictionary-agent.md` in this session
   rather than spawning the agent, because its permission gate needs the user before any fetch.
   The policy it applies is `Infrastructure/rules/data-documentation-rules.md`.
2. Run `python3 Infrastructure/scripts/validate_dataset_registry.py`, and
   `python3 Infrastructure/scripts/validate_literature_catalog.py` if a codebook was cataloged.
3. Check currency, which is informational. Include only datasets you can identify with
   confidence; skip proprietary, unrecognized, or project-specific files. Match the code's data
   files and loaders against the registry entry's `identification`, run its `currency` query (`search_strategy`, or the
   `search_strategy_1yr`, `search_strategy_5yr`, or `ipums_search_strategy` variant) with
   WebSearch, and record the version in code, the latest release, and a status: Current, Update
   Available, or Unable to Verify. An older vintage is never an error, because projects pin
   vintages for replication and comparability.
4. Report the datasets and vintages documented, the fields left `[unverified: ...]`, the
   claims to check against the data at first read (rule DD-8), and the currency status.

## Input

Mention `$document-data` with the details in the same message, pick the skill by name, or simply describe the task. Treat the invoking message as this workflow input.
