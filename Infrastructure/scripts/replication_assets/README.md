# {{PROJECT_TITLE}} — Replication Package

This repository contains the public replication materials for **{{PROJECT_TITLE}}**:
the analysis code, the data documentation needed to obtain and prepare the inputs, and
the figures and tables the analysis produces. It was generated on {{DATE}}.

## Research question

{{RESEARCH_QUESTION}}

## Deliverables

{{DELIVERABLES}}

## What is here

- `code/` — analysis scripts. The pipeline entry point is `code/run_all.R`, which sets a
  clean environment and seed, resolves paths, and runs the numbered scripts in order.
- `output/figures/` and `output/tables/` — the figures and tables in the publication.
- `DATA.md` — the datasets used, their sources and vintages, and how each was used. Raw
  input data are generally **not** included; `DATA.md` documents how to obtain them.
- `CITATION.cff` — how to cite this work.

## How to replicate

1. Obtain the input data as described in `DATA.md` and place it where the scripts expect.
2. Install the R packages listed at the top of `code/run_all.R`.
3. From the repository root, run `Rscript code/run_all.R` (toggle the script flags at the
   top of `run_all.R` to control which steps run).
4. Outputs are written to `output/`.

## Notes

Raw input data are excluded by default for size, licensing, or confidentiality reasons.
See `DATA.md` for access instructions. Please open an issue if a step does not reproduce.
