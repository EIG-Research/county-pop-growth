---
load: referenced
---

# Replication Publishing Rules

These are binding rules for the `replication-safety-reviewer` sub-agent, the
`build-replication-package` workflow, and the builder script
(`Infrastructure/scripts/build_replication_package.py`). Follow them exactly. They govern any
process that produces a public-facing replication package from a private research project
built on this template.

---

## Operating Philosophy

Default stance: nothing is publishable until proven safe.

The private project repository contains a proprietary AI template shell, raw data,
internal drafts, and a full git history. The public replication package must contain
only what the research team has deliberately chosen to release. The cost of a false
exclusion is a follow-up commit; the cost of a false inclusion is a permanent public
leak of proprietary infrastructure or confidential data. Exclude when uncertain.

**Guiding principles:**

1. **History is the trap.** A `.gitignore` does not remove already-committed files; it
   only stops future tracking. Because the proprietary shell is already committed, the
   existing repository can never be safely made public. Publication MUST go through a
   fresh export, never by flipping an existing private repo to public.
2. **Allowlist, not denylist, decides inclusion.** A file is published only if it
   matches the resolved allowlist. The denylist is a second, independent backstop that
   can only ever *remove*, never add.
3. **Extract, do not copy, anything that lives inside the shell.** Data documentation,
   citations, and figures may be publishable even though their canonical form lives in
   `Infrastructure/`. Synthesize a standalone artifact; never ship the shell file.
4. **The scan gate is not advisory.** A HIGH or CRITICAL safety finding blocks
   finalization. Overrides must be explicit, logged, and human-authorized.

---

## RP-1: History Safety (highest priority)

1. The export must be a newly initialized git repository (`git init`) created in a
   directory outside the source repository tree.
2. The source `.git/` directory MUST NOT be copied, referenced, or used as the base of
   the export. The public repo carries no commits from the private repo.
3. The export tool refuses to run when the resolved output directory is inside the
   source repository, is the source repository, or already contains a `.git/`.
4. The tool adds no git remote and MUST NOT push, because publishing is a human decision. It
   prints next steps; a human creates the remote and pushes after review.

**Severity:** any violation of RP-1 is **CRITICAL** and blocks finalization.

---

## RP-2: Default Allowlist and Denylist

The script seeds these defaults; the per-project manifest (RP-5) may narrow or extend
the allowlist but may never override the denylist.

### Default allowlist (published)

- `code/` — all analysis scripts, after the safety scan (RP-4).
- `output/figures/` and `output/tables/` — finished publication artifacts.
- A generated public `README.md` (RP-6).
- A generated `DATA.md` (RP-3).
- `LICENSE` (only when a license is chosen — RP-7), `CITATION.cff`, and `.gitignore`.
- A `REPLICATION_MANIFEST.md` summary of what was and was not included.

### Default denylist (never published — backstop)

`Infrastructure/`, `records/`, `.claude/`, `.codex/`, `.agents/`, `CLAUDE.md`, `AGENTS.md`,
`Makefile`, `.gitattributes`, the source `.gitignore`, `.git/`, `drafts/`, `output/logs/`,
`review-reports/`, `data/raw/`, `data/processed/`, `renv/library/` (installed packages;
`renv.lock` rebuilds them), and any path the manifest marks excluded. Dotfiles and
dot-directories at any level are excluded unless the manifest's `include` names the file's
exact path, such as `.Rprofile`; an included dotfile is scanned like any other file.
Environment files such as `.Renviron` and `.env` are therefore never shipped by default.

### Conditional (opt-in via manifest)

- `data/raw/` — excluded by default. `include_raw_data: true` lifts the denial, and
  `include` then names what ships (a dataset's files, or `data/raw` for all of it),
  subject to the scan and the confirmation prompt.
- `data/processed/` — the same, with `include_processed_data`.

**Conflict rule:** if a path matches both the allowlist and the denylist, the denylist
wins. This is non-negotiable and is the second backstop behind RP-1. A denylisted path in the
staged set that no manifest opt-in (Conditional, above) lifts is HIGH and blocks finalization,
because the backstop failed.

---

## RP-3: Data Documentation Extraction

1. The publishable description of datasets used — names, vintages, sources, how each was
   used, and notes on access — is synthesized into a standalone `DATA.md` in the
   export.
2. Source material is the project overlay `data/docs/dataset-registry.yaml`, joined by `id`
   to the template registry `Infrastructure/references/datasets/registry.yaml` for a
   dataset's name and agency, and `PROJECT.md`'s "Data in Scope". The builder writes one
   table row per overlay dataset with its name, agency, vintages, and the variables used.
   The template's catalog of recognized datasets says nothing about what this project
   used, so a template entry the overlay does not name is not listed. With no overlay
   dataset the table keeps one `[to confirm]` row. The "Data in Scope" section follows the
   table verbatim.
3. Nothing under `Infrastructure/`, the template registry included, is copied into the
   export, because it is part of the proprietary shell. The overlay and the per-variable
   docs under `data/docs/` are not on the default allowlist either, because `DATA.md` is how
   dataset documentation ships; a manifest `include` can still name them, and they are
   scanned like any other file. The builder scans the overlay as `DATA.md`'s source either
   way, so a key in it blocks the build.
4. Record only what the source states. Do not infer or fabricate a dataset's vintage,
   universe, or access terms. Mark unknown fields `[to confirm]`; the builder writes
   access notes as `[to confirm]` because the registry does not record them.

---

## RP-4: Pre-flight Safety Scan (hard gate)

Before finalization, scan every staged file (the export candidate set, not the source
repo) for the following families. Findings carry a severity; HIGH and CRITICAL block. The
generated `README.md`, `DATA.md`, and `CITATION.cff` are scanned with the text families
too, because they carry text from `PROJECT.md`, the registry, and the manifest.

### RP-4a: Secrets and credentials — **CRITICAL**

API keys, tokens, passwords, private keys, connection strings. Detection patterns
include: `AKIA[0-9A-Z]{16}` (AWS), `ghp_`/`github_pat_` (GitHub), `xox[baprs]-` (Slack),
`-----BEGIN [A-Z ]*PRIVATE KEY-----`, `sk-`/`sk-proj-` (OpenAI), `AIza` (Google),
`password\s*=`, `secret\s*=`, `token\s*=`, `api[_-]?key\s*=`, `registrationkey` (BLS), and a
key in a URL query (`&key=`, `?token=`) or a bare `key` given a key-shaped value, with
the value on the same line or the next. Any match blocks finalization; the full pattern set
lives in the scripts and is tested (`test_replication.py` cases 2 and 3).

### RP-4b: Absolute / user-identifying paths — **HIGH**

Machine paths that leak a username or local layout: `/Users/<name>`, `/home/<name>`, any
drive letter (`C:\\`, `D:/`), `~/` (except `~/.Renviron` and `~/.Rprofile`, which name R's
startup files rather than a layout), and UNC paths. These both break replication and expose
identity.

### RP-4c: Proprietary-shell references — **HIGH**

Literal references in staged files to `Infrastructure/`, `.claude`, `.codex`, `.agents`,
`CLAUDE.md`, `AGENTS.md`, or "EIG template" as whole words, in any letter case. A dot
directory counts only where a path can start, so `df.agents` is not a reference. Their
presence means either a shell file was staged (a denylist failure) or code points at
infrastructure that will not exist publicly.

### RP-4d: PII and contact details — **MEDIUM**

Email addresses and phone numbers (North American forms such as `(202) 555-0142`,
`202-555-0142`, `+1 202.555.0142`) in code or comments; the script flags these, and the
safety reviewer also looks for other personal identifiers. Flag for human review; MEDIUM
does not auto-block but must be acknowledged.

### RP-4e: Oversized / binary surprises — **MEDIUM or HIGH**

- A file over 50 MB is MEDIUM (recommend Git LFS or exclusion); one of 100 MB or more is
  HIGH, because GitHub refuses it.
- A binary file (a NUL byte in its first 8 KB) is MEDIUM when the manifest opted into it,
  through a data flag or an exact `include` path, and HIGH anywhere else: nothing asked
  for it. Image and PDF files (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.tif`, `.tiff`,
  `.eps`, `.pdf`, `.svg`) under `output/figures/` and `output/tables/` are the package's
  purpose and raise no binary finding; binary data there, such as `.dta` or `.parquet`, is
  judged like any other binary.

**Gate rule:** finalization proceeds only when there are zero unresolved CRITICAL and
HIGH findings. An override requires an explicit human-authorized flag and is recorded in
the safety report and the `REPLICATION_MANIFEST.md`.

---

## RP-5: Manifest Contract

1. Scope is declared per project in `replication.manifest.yaml` at the project root.
2. If the manifest is absent, the tool creates it from the template
   (`Infrastructure/scripts/replication_assets/manifest.yaml`) and STOPS, instructing the user
   to review it before exporting. The tool never invents scope silently.
3. Recognized fields: `output_dir`, `include` (extra paths), `exclude` (extra paths),
   `include_raw_data`, `include_processed_data`, `license`, and `citation` (keys
   `authors`, `title`, `year`, `url`; `authors` a list of `"Family, Given"` strings or
   single names). Unknown keys at either level are an error (fail loud), and so is an
   `include` or `exclude` entry that is absolute or has an empty, `.`, or `..` segment
   (`include: [./records/x]` would slip past the denylist, and `exclude: [./code/x]` would
   match nothing). The builder rechecks every final path
   against the denylist before copying it (`test_replication.py` case 19).
4. The manifest may extend or narrow the allowlist. It may add to the denylist. It may
   not remove an entry from the RP-2 denylist (the validator rejects attempts to
   allowlist a denied path).

---

## RP-6: Generated Public Scaffolding

1. `README.md` is generated from `PROJECT.md`'s title, "Research Question", and
   "Deliverables" (the template's `Optional.` and `TBD` filler removed; an empty section
   reads `[to confirm]`) plus replication instructions that point at `code/run_all.R`.
   "Data in Scope" goes to `DATA.md` (RP-3). No other section is copied, so the README
   never reproduces constraints, open notes, or the AI workflow.
2. `CITATION.cff` is generated from the manifest `citation` block: `title` (the project
   title when unset), `authors`, `url`, and `year` (as the preferred citation's year);
   `date-released` is the build date. Unfilled fields are marked `[to confirm]`, never
   fabricated.
3. `.gitignore` for the public repo ignores raw data, OS cruft, and common large/derived
   artifacts so they are not accidentally tracked after publication. It never untracks
   data the manifest opted into: an opted-in data directory is un-ignored, and every file
   a data flag or an exact `include` covers is added to the export's git regardless of any
   pattern. Every other file is left to the `.gitignore`.

---

## RP-7: License Handling

1. No `LICENSE` file is written unless the manifest `license` field names a license. The
   tool does not assume a default license, and the census says when none is named.
2. No legal text is generated. When a license is named, `LICENSE` is a placeholder that
   names it and asks for the full text, and the census warns that it is a placeholder. A
   human pastes the license's standard text before publishing.

---

## RP-8: Verification Before Handoff

1. After a finalize run, confirm: the export directory is outside the source repo; it
   contains a fresh repo with no inherited history; `.gitignore` and scaffolding exist;
   and a recursive search for denylisted references returns nothing.
2. The safety report (`replication-safety-report.html`) is written and self-contained, since
   the gate decision rests on it.
3. Close with an `Evidence` section: `Sources` (manifest path, scanned file count, output
   path), `Confidence` per major safety family, and `Assumptions` (defaults applied,
   overrides used).

---

## Severity Summary

| Family | Severity | Blocks finalization |
|--------|----------|---------------------|
| RP-1 history-safety violation | CRITICAL | Yes |
| RP-2 denylisted path staged without an opt-in | HIGH | Yes |
| RP-4a secrets / credentials | CRITICAL | Yes |
| RP-4b absolute / user paths | HIGH | Yes |
| RP-4c proprietary-shell references | HIGH | Yes |
| RP-4d PII / contact details | MEDIUM | No (must acknowledge) |
| RP-4e over 50 MB, or an opted-in binary | MEDIUM | No (must acknowledge) |
| RP-4e 100 MB or more, or a binary nothing asked for | HIGH | Yes |

**Severity bias.** This gate is fail-closed by design, the one exception to the
no-upward-default rule in `Infrastructure/AUTHORING.md` §6: when a finding sits between two
levels, choose the higher one, because a false inclusion is a permanent public leak and a
false exclusion costs a follow-up commit. The author can downgrade.

---

## Output Format Rules (safety report)

1. **File**: write to `{EXPORT_OR_TARGET}/review-reports/replication-safety-report.html`.
   Create the `review-reports/` directory if needed.
2. **Template**: use `Infrastructure/templates/replication-safety-report.md` as the HTML
   structure. Replace all `{{PLACEHOLDER}}` tokens; verify no `{{` remains.
3. **Sort order**: CRITICAL → HIGH → MEDIUM → LOW.
4. **Finding IDs**: sequential, starting at RS-001. No gaps, no duplicates.
5. **HTML escaping**: escape all code snippets, file paths, and excerpts.
6. **Evidence standard**: every finding states what was scanned, what matched, and where
   (file and line). Separate observed matches from interpretation.
7. **Self-contained**: no external dependencies.
