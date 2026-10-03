# Reference Store

This folder is the canonical store for **reusable knowledge** that should survive across sessions, projects, and contributors. It is organized by **reference category**, with one subdirectory per category.

## Current Categories

| Category | Path | Purpose |
|---|---|---|
| Literature | [`literature/`](literature/) | Papers, technical notes, data dictionaries, codebooks, and agent-generated summaries that inform analysis. |
| Datasets | [`datasets/`](datasets/) | Machine-readable registry of recognized-dataset knowledge — weights, pitfalls, identification signals, and per-variable documentation — consumed by the review fleet and maintained by the `data-dictionary-agent`. |

Additional categories (for example `policies/` or `methodology/`) can be added as siblings under this folder. See **Adding a New Category** below.

## Layout Pattern

Every category folder follows the same shape:

```
references/
└── <category>/
    ├── README.md         # category-specific purpose, conventions, validation
    ├── <index>.yaml      # machine-readable index (literature: catalog.yaml; datasets: registry.yaml)
    └── <subfolders>/     # category-specific content folders (e.g., papers/, summaries/)
```

This shape exists so that:

1. **Agents discover content by category.** The literature workflows read `literature/catalog.yaml`; the review agents and the data-dictionary agent read `datasets/registry.yaml`. No agent needs to scan the whole tree.
2. **Categories evolve independently.** Each category owns its index schema, validator, and subfolder conventions, documented in its README; `datasets/` and `literature/` share neither.
3. **Validators take a path.** `validate_literature_catalog.py` accepts `--catalog`, so it can check another index that uses the literature schema; a category with its own schema gets its own validator, as `datasets/` has `validate_dataset_registry.py`.

## Operating Rule

When adding content, always follow the category's own playbook. For literature, see [`Infrastructure/skills/literature-intake/SKILL.md`](../skills/literature-intake/SKILL.md) and [`literature/README.md`](literature/README.md).

## Validation

Validate a category's index after every edit:

```bash
python3 Infrastructure/scripts/validate_literature_catalog.py
python3 Infrastructure/scripts/check_catalog_staleness.py
python3 Infrastructure/scripts/validate_dataset_registry.py
```

`make maintenance-check` runs all three as part of the routine hygiene pass.

## Adding a New Category

To add a new reference category (for example `policies/`):

1. **Create the folder structure** following the layout pattern above:
   ```bash
   mkdir -p Infrastructure/references/policies/documents
   touch Infrastructure/references/policies/documents/.gitkeep
   ```
2. **Add a category README** at `references/policies/README.md` describing the category's purpose, conventions for what belongs in each subfolder, and its index schema.
3. **Add an index stub** at `references/policies/catalog.yaml`:
   ```yaml
   version: 1
   last_updated: YYYY-MM-DD
   entries: []
   ```
4. **Register the category in this README's table** (above) so future contributors discover it.
5. **Wire validation.** If the new catalog follows the same schema as the literature catalog, point the existing validators at it via `--catalog`. If the schema diverges, add a category-specific validator under `Infrastructure/scripts/` and add a Makefile target so the new check runs as part of `maintenance-check`.
6. **Add an intake playbook** (optional but recommended) at `Infrastructure/skills/<category>-intake/SKILL.md` so agents know how to add new entries to the catalog consistently.

This pattern keeps the reference store extensible without changing how existing categories work or how agents discover content.
