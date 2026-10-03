# Data Documentation — {{PROJECT_TITLE}}

This file documents the datasets used in the analysis: their sources, vintages, and how
each was used. The table is generated from the project's dataset documentation and lists
only what it states; the raw input data are generally not redistributed here.

> How to extend this file: for each dataset in scope, record the source agency, the exact
> vintage or release, the variables used, the universe, weighting, and any access or
> licensing notes. Pull these from the project's data documentation. Mark anything you
> cannot confirm as `[to confirm]` — do not guess.

## Datasets

| Dataset | Source / agency | Vintage | How it was used | Access notes |
|---|---|---|---|---|
{{DATASET_ROWS}}

## Obtaining the data

Describe here, per dataset, exactly how a replicator obtains the inputs (download URL,
extract specification, API parameters, or application process) and where to place the
files so that `code/run_all.R` finds them.
