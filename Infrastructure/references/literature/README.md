# Literature

This category holds papers, technical notes, codebooks, data dictionaries, and agent-written summaries that inform analysis. It is one category under [`Infrastructure/references/`](../README.md).

## Contents

| Path | Purpose |
|---|---|
| [`catalog.yaml`](catalog.yaml) | Machine-readable index of every literature entry. Agents read it for discovery; entries are added through the intake workflow. |
| [`papers/`](papers/) | Saved research papers and technical notes (PDFs, preprints, working papers). |
| [`data_dictionaries/`](data_dictionaries/) | Schema docs, codebooks, and variable dictionaries for datasets used in analysis. |
| [`summaries/`](summaries/) | Extraction notes and summaries written by agents. |

## Operating Rule

Add literature through the [`literature-intake` workflow](../../skills/literature-intake/SKILL.md), so the catalog stays complete, searchable, and consistent across contributors.

## Catalog Schema

This is the one schema for `catalog.yaml`. [`validate_literature_catalog.py`](../../scripts/validate_literature_catalog.py) checks it, and [`check_catalog_staleness.py`](../../scripts/check_catalog_staleness.py) reads its dates.

```yaml
version: 2
last_updated: YYYY-MM-DD
entries:
  - id: <YYYY-short-title>             # unique, stable slug
    title: <full title>
    authors: [<Last, First>, ...]        # the publishing agency for an official document
    year: <YYYY>                         # publication year, an integer
    type: paper | data_dictionary | codebook | technical_note | other
    topic_tags: [<tag>, ...]             # retrieval tags, e.g. methods, data-cps, tier-1
    path: <repository-relative path>     # e.g. Infrastructure/references/literature/papers/x.pdf
    source_url: <https://...> | null     # null when no URL exists
    doi: <10.xxxx/...>                   # optional; bare DOI, no https://doi.org/ prefix
    added_on: YYYY-MM-DD
    last_verified_on: YYYY-MM-DD         # optional; required when status is verified
    status: raw | parsed | summarized | verified | archived
    relevance_note: <1-2 sentences: why this matters here>
    summary_path: <repository-relative path>  # optional
```

- `path` and `summary_path` resolve from the repository root, not from this folder.
- `status: parsed` marks an agent's draft; `verified` means a person checked the entry against the source on `last_verified_on`. Agents never write `verified`.
- Staleness runs from `last_verified_on`, or from `added_on` for an entry never verified. Archived entries are skipped.
- Unknown keys fail, so a field name cannot drift silently; the earlier `added`, `verified`, and `tags` are rejected with the field that replaced each.

## Validation

Run after every catalog edit:

```bash
python3 Infrastructure/scripts/validate_literature_catalog.py
python3 Infrastructure/scripts/check_catalog_staleness.py
```

`make maintenance-check` runs both; `Infrastructure/scripts/test_knowledge_stores.py` tests them with planted bad entries.
