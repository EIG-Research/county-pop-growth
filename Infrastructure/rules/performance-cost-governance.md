---
load: referenced
---

# Performance and Cost Governance

Keep expensive work predictable: state what a run will cost before starting it, stop runaway
jobs, and never hide instability behind silent retries.

## Job tiers

| Tier | Expected runtime | Examples | Controls |
|---|---|---|---|
| 1 | Under 2 minutes | Lint and check scripts, small transforms | None |
| 2 | 2–15 minutes | Medium analysis runs, document renders | State expected runtime and output path first |
| 3 | 15–60 minutes | Full rebuilds, heavy joins, large regressions | Also: an explicit timeout, checkpoints (intermediate outputs or logs), and a resume strategy |
| 4 | Over 60 minutes | Multi-stage pipelines on large data | Also: explicit human confirmation before starting |

## Retries and caching

1. Retry at most twice, and only for clearly transient failures; record each retry's reason.
2. Do not retry a deterministic error (syntax, missing file, failed assertion) without a code
   or configuration change.
3. Prefer incremental runs and validated intermediates while inputs and assumptions hold;
   force a clean rerun when inputs, versions, or core assumptions change.
4. When caching affects correctness, document the cache keys and what invalidates them.

## Escalate

Pause and ask for direction when estimated runtime exceeds 60 minutes, estimated output
exceeds 1 GB, the same step fails twice in a row, resource use grows unexpectedly, or the run
would block other critical work for long.

## Report

For a Tier 3 or 4 run, report estimated versus actual runtime, retries and why, the outputs
produced (paths, and sizes when relevant), and whether to keep the approach.
