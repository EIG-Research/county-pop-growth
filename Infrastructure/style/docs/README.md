# EIG Style Docs

The index of EIG style guidance for researchers and agents. Open the doc that matches the task; colors, fonts, and sizes are never typed into these docs but cited by token ID from `Infrastructure/style/tokens/eig-style-tokens.v1.json`, whose values are listed in `Infrastructure/style/docs/_generated/tokens.md`.

## Which entry point

Prose and figures have separate reviewers: prose reviews never judge figure content, and figure reviews never judge prose. The agent and workflow bodies live under `Infrastructure/agents/`, `Infrastructure/skills/`, and `Infrastructure/style/skills/`.

| Task | Use | Kind | Edits files |
|---|---|---|---|
| Get feedback on your own draft (structure, argument, clarity); AI never drafts EIG prose (`Infrastructure/rules/ai-use-disclosure-rules.md`) | `eig-writer` (a writing coach) | agent | no |
| Critique a passage against Smart Brevity, for the author to tighten | `smart-brevity` | workflow | no; returns a critique, not a rewrite |
| Format a citation | `cite` | workflow | no |
| Fill a publication cover sheet's factual fields | `cover-sheet` | workflow | no |
| Audit prose, citations, and a document's figure captions | `review-style`, which applies `eig-reviewer` section by section | workflow and agent | no |
| Audit a figure, table, or its plotting code | `eig-style-review` | skill | no |
| Choose or critique a chart design | `eig-tufte-critique` | skill | no |
| Restyle existing plotting code with the themes | `eig-style-apply` | skill | yes |
| Build figure or table code, or fix audit findings | `eig-style-guide-agent` | agent | yes |
| Check a Datawrapper pipeline's manifests and colors | `eig-style-datawrapper` | skill | no |
| Review rendered figures with their owner, round by round | `review-board` | workflow | yes |

## Figures and tables

- `Infrastructure/style/docs/eig-figure-style.md`: the figure and table spec (color, type, titles, source lines, tables, the minimum text size).
- `Infrastructure/style/docs/tufte-principles.md`: graphical quality (data-ink, lie factor, chartjunk, small multiples) and analytical design for dense and results displays. The `eig-tufte-critique` skill applies it.
- `Infrastructure/style/docs/eig-legacy-palette-policy.md`: when the 2020 semantic palettes are allowed.
- `Infrastructure/style/themes/README.md`: R, Python, and Stata quickstarts.

## Brand

- `Infrastructure/style/docs/eig-brand-guidelines.md`: logo, typography, color, photography, and illustration, from the 2022 guide.

## Writing and publication

- `Infrastructure/style/docs/eig-writing-style.md`: writing mechanics and Smart Brevity.
- `Infrastructure/style/docs/eig-citation-style.md`: citation formats.
- `Infrastructure/style/docs/eig-document-process.md`: the publication process and cover sheet.

## Datawrapper

- `Infrastructure/style/docs/datawrapper-integration.md`: the governance contract (token colors, palette mode, publish manifests, CI) and downstream adoption.
- `Infrastructure/style/docs/datawrapper-api-notes.md`: measured API behavior (what the export honors and ignores, merge semantics, data orientation).
- `Infrastructure/style/docs/ci/datawrapper-compliance.workflow.template.yml`: the CI template for downstream repositories.

## Checks

```bash
make style-tokens-check                     # generated files match the tokens; no stray hex
python3 Infrastructure/scripts/test_style.py
python3 Infrastructure/style/scripts/compliance/check_datawrapper_manifest.py <manifest_path>
python3 Infrastructure/style/scripts/compliance/check_legacy_metadata.py <metadata_json_path>
```
