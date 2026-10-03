# Replication Package

The replication-package subsystem exports the publishable part of a research project (code,
figures, tables, and data documentation) into a brand-new git repository outside the source
repository, after a safety scan. The export shares no history with the source, never contains
the proprietary shell (`Infrastructure/`, `.claude/`, `.codex/`, `.agents/`), and is never
given a remote or pushed: a person does that after review.

This README is the one map of the subsystem; other indexes link here rather than list its
parts. Nothing is stored in this folder: the manifest lives in the project, and the export is
written outside the repository.

## How the subsystem fits together

| Part | What it does |
|---|---|
| `Infrastructure/skills/build-replication-package/SKILL.md` | The workflow: dry run, safety review, the gate, confirmation in chat, finalize, verify. Starts only when the user asks. |
| `Infrastructure/rules/replication-publishing-rules.md` | The binding contract (`RP-1` to `RP-8`): history safety, allowlist and denylist, scan families and severities, scaffolding, license. |
| `Infrastructure/scripts/build_replication_package.py` | The builder: census, scan, staging in a private temporary directory, scaffolding, `git init` and one commit, then an atomic move into place. Its docstring lists the flags and exit codes. |
| `Infrastructure/scripts/validate_replication_manifest.py` | Validates the manifest, resolves the include set against the immovable denylist, and holds the credential forms that need more than a pattern. |
| `Infrastructure/scripts/replication_assets/` | Templates the builder reads: `manifest.yaml` (seeded into a project that has none), and the export's `README.md`, `DATA.md`, and `gitignore`. |
| `Infrastructure/agents/replication-safety-reviewer.md` | Reviews the staged set and writes `review-reports/replication-safety-report.html` from `Infrastructure/templates/replication-safety-report.md`. |

## Where things go

- `replication.manifest.yaml` at the project root: what the project publishes, the data
  flags, the license, the citation, and optionally the output directory.
- `<project>/review-reports/replication-safety-report.html`: the safety report.
- The export: `--out`, else the manifest's `output_dir`, else `../<project>-replication`.
  The builder refuses any path inside the project, a symlink, a non-empty directory, or one
  that already holds a `.git/`.

## The gate

The builder's scan is authoritative: a HIGH or CRITICAL finding blocks finalization, and only
`--allow-unsafe`, passed after the owner approves it in chat, overrides it. The safety report
can add a block but never clears a builder finding. With no terminal, the builder finalizes
only with `--yes`, which the workflow passes after the user confirms in chat.

## Tests

`make replication-test` runs `Infrastructure/scripts/test_replication.py`, which drives the real
builder against synthetic projects in a temporary directory, with no model and no network.
