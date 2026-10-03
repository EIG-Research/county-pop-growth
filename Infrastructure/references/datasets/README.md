# Datasets

This category is the machine-readable store of **dataset and variable knowledge** for recognized public datasets: weights, pitfalls, identification signals, and the variable names each codebook uses. Where [`literature/`](../literature/) catalogs source artifacts (papers, codebooks), `datasets/` holds the structured knowledge extracted from them.

The [`data-dictionary-agent`](../../agents/data-dictionary-agent.md) extends it; the review agents read it.

## Contents

| Path | Purpose |
|---|---|
| [`registry.yaml`](registry.yaml) | Recognized-dataset knowledge shipped with the template. Validated by `validate_dataset_registry.py`. |
| [`docs/`](docs/) | Human-readable Markdown for template entries. |

## Who reads `registry.yaml`

- `methodology-reviewer` — `weights` and `pitfalls` (MR-WEIGHTS, MR-SURVEY).
- the `document-data` workflow — `identification` signals and `currency` queries for its currency check.
- `ai-skeptic` — `known_variables` (AS-VARIABLE: does a variable name exist?).

Each consumer reads this file instead of carrying its own copy, so a correction here reaches every reviewer.

## Verification and provenance

`verification` says how far an entry has been checked. It is independent of `layer`, which only says where the entry lives.

| `verification` | Meaning | How a reviewer treats it |
|---|---|---|
| `unverified` | Nobody has signed it against a source. Every template entry starts here. | A lead: confirm against the codebook before it drives a HIGH finding. |
| `parsed` | An agent extracted it from a cited source for the vintage in use. | A lead, as above. |
| `verified` | A person checked it against `sources` and signed it. | Authoritative. |

A `verified` entry needs all three provenance fields: `sources` (each `{title, url}`), `verified_by`, and `verified_on`. `sources` may also appear on an unverified entry to record where its facts came from; a signature may not. Agents never write `verified`: signing is a person's step, because a signature is a claim that someone read the source. Nothing is invented: an unconfirmed field is written as `[unverified: ...]`.

## Schema (summary)

```yaml
version: 2
last_updated: YYYY-MM-DD
datasets:
  - id: <slug>                      # unique
    name: <full name>
    layer: template | project
    verification: unverified | parsed | verified
    sources: [{title: <document>, url: <https://...>}]  # provenance
    verified_by: <person>             # only with verification: verified
    verified_on: YYYY-MM-DD           # only with verification: verified
    kind: survey | administrative | aggregate
    agency: <publishing organization>
    identification:                   # signals that the dataset is in use
      file_patterns: [<glob>, ...]
      loaders: [<loader call>, ...]
      comments: [<string>, ...]
      signal_variables: [<name>, ...] # distinctive names only; each also in known_variables
    known_variables: [<name>, ...]    # names as the codebook spells them; `*` = wave/replicate
    weights:                          # list, or the string `not_applicable`
      - context: <analysis context>
        source_name: <publisher's public-use name>
        ipums_name: <IPUMS name>      # at least one of the two names
        notes: <string>
    pitfalls:
      - id: <slug>
        description: <string>
        severity: HIGH | MEDIUM | LOW
        why: <string>                 # optional
        what_to_check: <string>       # optional
    currency:
      search_strategy: <web-search query>
    vintages: []
    variables:                        # per-variable docs
      - name: <variable>
        vintage: <year/release>       # required (or [unverified: ...])
        source: <authority + doc>     # required (or [unverified: ...])
        definition: <string>
        universe: <string>
        question: <question wording>
        topcoding: <string|false>
        verification: unverified | parsed | verified
    docs: []                          # repository-relative Markdown paths
```

Variable names are listed as the publisher spells them; match them case-insensitively, since Stata, SAS, and IPUMS extracts differ in case. A name too common to identify a dataset (`emp`, `year`) stays out of `signal_variables`. The validator enforces these rules.

## Project overlay

A project's own documentation lives in the project, not here: `data/docs/dataset-registry.yaml`
(same schema, every entry `layer: project`) plus its Markdown under `data/docs/`. Template
updates then never collide with project edits, and a review of an external project reads that
project's overlay. An overlay entry whose `id` names a template dataset adds `variables`,
`vintages`, and `docs` only; the curated metadata stays here. The validator checks the overlay
when it exists (`--project-root` points it at another project).

## Validation

```bash
python3 Infrastructure/scripts/validate_dataset_registry.py
```

`make maintenance-check` runs it; `Infrastructure/scripts/test_knowledge_stores.py` tests it with planted bad entries.

## Adding to the registry

Use the [`document-data` workflow](../../skills/document-data/SKILL.md).
