---
load: referenced
---

# Reproduce Published Results

Use this rule when a task reproduces a published paper's or report's results before extending
them. Reproduce first, because an extension built on a baseline that does not match inherits
an unknown error. Publishing this project's own replication package is a different task:
`Infrastructure/rules/replication-publishing-rules.md`.

## 1. Inventory and targets

- Read the source's replication README and methodology notes.
- Inventory its code, data files, scripts, and expected outputs.
- Record each target value in
  `records/session_logs/YYYY-MM-DD_replication_targets.md`.

## 2. Translate and run

- Translate line by line first; do not optimize before the baseline matches.
- Match the original specification exactly: sample, covariates, clustering, and
  standard-error method.
- Save intermediate outputs so a divergence can be traced to its step.

## 3. Verify the match

A reproduced value matches its target under the one rounding rule in
`Infrastructure/rules/doc-number-rules.md` §4: rounded to the precision the source publishes,
it equals the published number. The rule scales with the number (a coefficient in dollars and
an elasticity of 0.004 are each held to their published digits), counts match exactly, and a
p-value or interval is compared the same way rather than by which side of a threshold it falls.

If a target does not match, do not extend. Find the step where the results first diverge,
record the likely causes, and log the investigation even when it is unresolved.

## 4. Report, then extend

- Save `records/session_logs/YYYY-MM-DD_replication_report.md`: targets checked,
  pass and fail counts, discrepancy notes, and the execution environment.
- Once the baseline passes, commit it, then add each extension as a separate step that traces
  back to the verified baseline.
