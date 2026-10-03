---
load: paths
paths:
  - "data/**"
  - "Infrastructure/references/datasets/**"
---

# Data Documentation Rules

These are binding rules for the `data-dictionary-agent` and the `document-data` workflow. Follow them exactly. They also govern any agent that writes to the dataset registry, and DD-8 governs the agent that first builds a dataset from the data.

---

## Canonical Sources

- Template registry: `Infrastructure/references/datasets/registry.yaml`
- Project overlay: `data/docs/dataset-registry.yaml` and its Markdown docs under `data/docs/`, in the project
- Category docs: `Infrastructure/references/datasets/README.md`
- Validator: `Infrastructure/scripts/validate_dataset_registry.py`
- Artifact intake: `Infrastructure/skills/literature-intake/SKILL.md`

---

## Scope

The data-dictionary agent acquires authoritative data dictionaries/codebooks for the datasets a project uses, and converts them into structured variable documentation. It documents the variables that are **used in the analysis code or clearly implied by the research question** — not the entire codebook. The set expands as code evolves.

It does **not**: edit analysis code, drafts, or figures; perform literature mapping (that is `literature-scout`); or assess identification strategy (that is `methodology-reviewer`).

---

## Rule DD-1: No Fabrication (highest priority)

1. Record only what the authoritative source states. Never infer a variable's universe, question wording, definition, or coding from its name or from a related dataset.
2. When a field is not available in the source, write the literal marker `[unverified: <what is missing>]`. A flagged gap is acceptable; a fabricated field is a critical failure.
3. Never invent a variable name. Every variable documented must exist in the codebook for the stated vintage. This is the target of `ai-skeptic` check AS-VARIABLE.
4. Separate observed facts (from the codebook) from any interpretation the agent adds.

---

## Rule DD-2: Vintage Pinning

1. Every documented variable must record the `vintage` (year or release) it describes.
2. Definitions, universes, and question wording change across vintages (ACS year to year, the 2014 CPS ASEC income redesign, the 2019 NHIS questionnaire redesign, IPUMS harmonization). Documenting one vintage's variable against another's data is an error.
3. When the project uses multiple vintages of one dataset, document each vintage whose definitions differ, and note breaks in comparability.

---

## Rule DD-3: Acquisition

1. **Permission first.** Before fetching or downloading any external document, state the dataset, vintage, exact source, and whether it is a download or a read, and wait for approval. Acquire only what was approved.
2. **Authority order.** Prefer, in order: (a) the codebook/DDI shipped with the project's own data extract; (b) official agency technical documentation for the exact vintage; (c) the provider's variable pages. Never use aggregators or secondary summaries for variable semantics.
3. **Pages that fetch empty.** Some portals render with JavaScript, so a plain fetch can return an empty shell. Fall back to the codebook bundled with the extract, or ask the user for a copy, and record what could not be read. Do not retrieve blocked content through alternative scraping.
4. **Save the artifact.** Store the retrieved codebook under `Infrastructure/references/literature/data_dictionaries/` with intake naming (`YYYY_dataset_dictionary.ext`) and add a `parsed` catalog entry recording the vintage in `relevance_note`.

---

## Rule DD-4: Two Layers, Two Files

1. **Template layer** (`layer: template`) — reusable knowledge shipped with the template
   (identification, known variables, weights, pitfalls, currency) in the template registry. The
   agent does not create, edit, or downgrade it; a correction is a template change, because
   upstream updates overwrite that file.
2. **Project layer** (`layer: project`) — one project's variable documentation, written to the
   project overlay `data/docs/dataset-registry.yaml` so template updates never collide with project edits. An
   overlay entry whose `id` names a template dataset extends it with `variables`, `vintages`,
   and `docs` only; an unrecognized dataset gets a full `layer: project` entry.
3. **Verification is independent of layer.** `unverified` (nobody has signed it), `parsed` (an
   agent extracted it from a cited source), or `verified` (a person checked it against
   `sources` and signed `verified_by` and `verified_on`). The agent writes `parsed`, never
   `verified`: signing is a person's claim to have read the source. Each variable carries its
   own `verification`, default `parsed`.
4. A consumer (e.g., `methodology-reviewer`) treats a `verified` entry as authoritative and an
   `unverified` or `parsed` one as a lead to confirm before it drives a HIGH finding.

The validator checks both files, the layer of each entry, and the signature on `verified`.

---

## Rule DD-5: Output

1. **Dual output is mandatory.** Every documentation pass produces both human-readable Markdown under `data/docs/` and structured entries in `data/docs/dataset-registry.yaml`.
2. **Markdown naming:** `<dataset-id>_<vintage>.md`; split per-variable only for large datasets. Lead with dataset, vintage, and source; one section per variable covering definition, universe, question wording, coding/special values, and comparability.
3. **Registry variable entries** require `name`, `vintage`, and `source` (a value or an explicit `[unverified: ...]` marker). Add the doc path (relative to the project root) to the dataset's `docs:` list. Set top-level `last_updated`.

---

## Rule DD-6: Validation Before Handoff

1. Run `python3 Infrastructure/scripts/validate_dataset_registry.py` and fix every error.
2. Run `python3 Infrastructure/scripts/validate_literature_catalog.py` if a codebook artifact was added.
3. Confirm referenced doc paths exist (the validator checks this).
4. Close with an `Evidence` section: `Sources`, `Confidence` (per documented dataset), `Assumptions` (vintages, variables, scope boundary).

---

## Rule DD-7: Consumer Contract

The registry is read by other agents; changes must preserve their contract:

1. `methodology-reviewer` reads `weights` and `pitfalls` for MR-WEIGHTS and MR-SURVEY (`Infrastructure/rules/methodology-rules.md` §6). Do not remove or restructure these fields without updating that agent.
2. The `document-data` workflow reads `identification` (file patterns, loaders, comments, `signal_variables`) and `currency` for its currency check.
3. `ai-skeptic` reads `known_variables` for AS-VARIABLE existence checks. List only names the codebook spells that way; a description is not a variable name.
4. Adding project `variables` and `docs` to the overlay is always safe; it never alters template metadata. Consumers read the template registry and, when present, the overlay.

---

## Rule DD-8: Check the Documentation Against the Data

Documentation describes a variable; only the data show how it behaves in the extract the
project uses. A provider's derived variable can differ from the agency definition it seems to
match (who it counts, which adjustment it already carries, what a special code means), and an
analysis built on the documented reading inherits the error.

1. **Hand off the claims to check.** A documentation pass lists, in its Markdown doc and its
   report, each documented fact that sets a headline definition: the universe, the unit and
   how a measure is constructed, adjustments and their direction, top codes, and special
   values. Each item says what tabulation in the data would confirm or refute it.
2. **Check them at first read.** When the data arrive and before analysis code relies on a
   listed fact, the agent building the dataset tabulates it in the data and records the result
   beside the fact in the Markdown doc: confirmed, contradicted, or not checkable, with the
   command or script. A contradiction corrects the doc and the registry entry, and is raised
   with the owner when it changes a definition the spec or `PROJECT.md` fixed.
3. **Benchmark at more than one level.** When an agency publishes the measure being built (for
   example a median from a published table), compare the constructed estimate against it, both
   overall and for at least one subgroup where the documented choices act differently. A
   single aggregate can match while two errors cancel. Record each comparison, with the
   published margin of error, in the Markdown doc.
4. Until a fact is confirmed this way, label it as documentation-stated, not data-verified,
   wherever a draft or methods note relies on it.
