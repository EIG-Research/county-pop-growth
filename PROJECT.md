# Project Profile

Use this file as the single source of project context. Fill this out at project start with an AI agent.
Minimum required to begin work: `Research Project Title` only.
All other sections are optional; an agent asks for one only when the current task needs it.

## Research Project Title
- `TBD`

## Research Question
Optional.
- `TBD`

## Data in Scope
Optional.
List the datasets/sources that can be used to answer the research question.

| Data Source | Type | Owner/Location | Time Coverage | Access Notes |
|---|---|---|---|---|
| `TBD` | `TBD` | `TBD` | `TBD` | `TBD` |

For each in-scope dataset, run the `document-data` workflow to acquire its vintage-correct codebook and document the relevant variables in the dataset registry (`Infrastructure/references/datasets/registry.yaml`). The review agents read that registry for weights, pitfalls, and variable definitions.

## Deliverables
Optional.
- `TBD`

## Constraints
Optional.
- `TBD`

## Additional Context (Open Notes)
Optional.
Add any context that would help an AI agent work correctly over time.

`TBD`

## Working agreements
Agents read these instead of asking about them each session.

- Session log cadence: `milestone`, meaning a full session log at plan approval, plan
  completion, and handoff. Edit the value here to change it; agents raise it only if the user
  asks about logging.
- Project non-negotiables: optional. List any principles that bind every task in this project.
