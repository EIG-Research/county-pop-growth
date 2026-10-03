---
name: literature-intake
description: "Add a paper, data dictionary, codebook, or technical note to the literature catalog under Infrastructure/references/literature/. Enforces required fields, stores the artifact, and updates the catalog index. Use when a source should be reusable in later sessions, or a task needs a source the project may already hold."
argument-hint: "<paper-or-source>"
allowed-tools: ["Read", "Write", "Edit", "Grep", "Glob", "Bash(python3 Infrastructure/scripts/validate_literature_catalog.py *)"]
---

# Workflow: literature-intake

Find, add, index, and reuse papers, data dictionaries, codebooks, and methodology references
through the literature catalog, so a source found once is reusable in every later session. It
is done when the source is stored under its canonical folder with a catalog entry and
`validate_literature_catalog.py` passes, or an existing entry for it is reported.

## Input

Invoke as `/literature-intake <paper-or-source>`.

Arguments: $ARGUMENTS

The argument identifies the source to ingest — a file path, a URL, a DOI, or a citation. If no
argument was given, ask which source to add in an interactive session; otherwise report the
missing input and stop. Use this workflow whenever a reference is found
that should be reusable later, and whenever a task needs a source the project has already seen.

## Finding an Existing Source First

Before ingesting anything, check whether the repository already has it. Search in this order:

1. `Infrastructure/references/literature/catalog.yaml` — the discovery index. Match on
   `topic_tags`, `title`, and `relevance_note`.
2. The files referenced by matching catalog entries.
3. `Infrastructure/references/literature/summaries/` for prior extraction notes.

Read the underlying source file before producing any claim-level output. Treat `catalog.yaml`
as an index, never as evidence in its own right. If the needed source is missing, ingest it
with the workflow below and update the catalog.

## Canonical Locations

- Catalog: `Infrastructure/references/literature/catalog.yaml`
- Papers: `Infrastructure/references/literature/papers/`
- Data dictionaries and codebooks: `Infrastructure/references/literature/data_dictionaries/`
- Agent-written summaries and extraction notes: `Infrastructure/references/literature/summaries/`

## Catalog Fields

The catalog schema, with its required fields and allowed values, is in
`Infrastructure/references/literature/README.md`; the validator below enforces it. Record
`authors` and `year` from the source itself, and a `doi` only when it resolves to this work.

## Intake Workflow

1. Save the artifact into the correct folder.
2. Use deterministic file naming:
   - Paper: `YYYY_author_short-title.pdf`
   - Data dictionary/codebook: `YYYY_dataset_dictionary.ext`
3. Add or update an entry in `catalog.yaml` (`status: parsed` for an agent's entry; only a person
   sets `verified`, with `last_verified_on`).
4. If text extraction or a summary is created, save it in `summaries/` and add `summary_path` in the catalog entry.
5. If the item supersedes an older version, keep both files and set the older entry `status` to `archived` with a short note.
6. Run `python3 Infrastructure/scripts/validate_literature_catalog.py` and fix any errors.

## Retrieval Rules For Agents

1. Search `catalog.yaml` first before broad repository scans.
2. Filter by `type`, `topic_tags`, and keyword match in `title`/`relevance_note`.
3. Cite exact file paths used in final outputs.
4. Do not make claim-level assertions from catalog metadata alone; read the underlying source file first.

## Guardrails

- Never invent a citation or a finding that is not present in the source material.
- Preserve prior entries. When a newer version arrives, keep both files and archive the older
  entry rather than deleting history.
- In deliverables, cite the exact repository path of every source used.

## Quality Check Before Handoff

- [ ] Artifact path exists and is readable
- [ ] Catalog entry contains all required fields
- [ ] `topic_tags` are specific enough for future retrieval
- [ ] Any summary/extract path resolves correctly
