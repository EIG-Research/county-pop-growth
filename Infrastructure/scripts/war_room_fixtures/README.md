# War Room Test Fixtures

Synthetic inputs for the war-room test suite. **Every ledger in this directory carries
`session.fixture: true`**, so fixture text can never be mistaken for an agent's reading of
real code. Nothing here is a real analysis, and no number in it is a real number.

Nothing in this directory is ever written to during a test run. Test cases copy a fixture
project to a temporary directory before touching it, and every ledger a test produces goes
to a temporary directory too.

## Layout

| Path | What it is |
|---|---|
| `Infrastructure/scripts/war_room_fixtures/proj_a` | Fixture project A. Carries its own `PROJECT.md`, so project-root resolution has a root to walk up to and a basename to record as `project.id`. |
| `Infrastructure/scripts/war_room_fixtures/proj_a/code` | One synthetic script per supported language: `sample.R`, `sample.Rmd`, `sample.qmd`, `sample.py`, `sample.do`, `sample.ado`. Each has a file header, comment section headers, a function or program definition, a pipe or chain, a filter with a `>=` boundary, and blank separators. |
| `Infrastructure/scripts/war_room_fixtures/proj_a/a` | A second `clean.R`, at a different path from the one below, so two slugs from one project can be shown to differ. |
| `Infrastructure/scripts/war_room_fixtures/proj_a/b` | The other `clean.R`. |
| `Infrastructure/scripts/war_room_fixtures/proj_b` | Fixture project B. Its `code/sample.R` is byte-identical to project A's, so the same script path under a different `project.id` can be shown to produce a distinct ledger slug. |
| `Infrastructure/scripts/war_room_fixtures/code/run_all_starter.R` | A frozen copy of the template's starter `code/run_all.R`. Case 8 segments it and pins its blocks, so the case never skips when a project rewrites its own pipeline. Do not edit it; add a new fixture instead. |
| `Infrastructure/scripts/war_room_fixtures/predictions` | One prediction set per fixture script: `title`, `density`, and `prediction` per `block_id`. Confidence is distributed honestly under WR-P6 — at least one `low`, and not every block is `high`. |
| `Infrastructure/scripts/war_room_fixtures/ledgers` | Three finished ledgers for `proj_a` `code/sample.R`, described below. |

## Ledgers

| Directory | What it holds |
|---|---|
| `Infrastructure/scripts/war_room_fixtures/ledgers/ordered` | Filled and finalized, `session.mode: ordered`, no dispositions. The block-map screen shows for it, because every block still lacks a disposition. |
| `Infrastructure/scripts/war_room_fixtures/ledgers/fast-forward` | The same, with `session.mode: fast-forward`. Block `b008` has density `low` and confidence `medium`, so batch confirmation may pre-select it; `b004` is `high` density and `b006` is `low` confidence, so neither may ever be fast-forwarded (WR-C4). |
| `Infrastructure/scripts/war_room_fixtures/ledgers/two-reviewer` | Hand-merged. Every block is dispositioned by `bglasner`; `b004` carries one `dissent[]` item from `rlee`; `session.reviewers[]` lists both; `session.history[]` holds one `prep` and two `walkthrough` entries. |

## Rebuilding

The ledgers are generated, not hand-written. Rebuild any of them from its fixture script
and prediction set with `Infrastructure/scripts/war_room_prep.py`: `skeleton --fixture`,
then `fill`, then `finalize`. The two-reviewer ledger adds its answers, dissent, and
history on top of an `ordered` build; its timestamps are pinned so the committed file does
not change from one rebuild to the next.
