---
name: build-replication-package
description: >-
  Build a public-safe replication package: export an allowlisted subset (code, figures, tables, data docs) into a fresh git repo outside the source repo, gated by a safety scan. Never copies the proprietary shell, raw data, or git history; never pushes. Use when the user asks to publish or package a project's replication materials.
---

# Workflow: build-replication-package

Export the publishable part of a research project (code, figures, tables, data documentation)
into a brand-new git repository outside the source repository, after a safety scan. The builder,
`Infrastructure/scripts/build_replication_package.py`, enforces the contract in
`Infrastructure/rules/replication-publishing-rules.md`: the allowlist and immovable denylist,
the scan, a fresh repository with no inherited history, no remote, and no push. Read the rules
before Step 5.

**Done when** the export exists at the output path with its scaffolding and one initial
commit (or, where git has no user identity, every file staged and the user told to commit),
the safety report is written, and the user has the census, the report path, and
the next steps; or, on a dry run or a block, when the user has the census and the reason.

**Gate policy.** The builder's scan is authoritative: a HIGH or CRITICAL finding blocks
finalization, and only `--allow-unsafe` overrides it. The safety reviewer's report can add a
block, but it never clears a builder finding. Pass `--allow-unsafe` only when the owner has
approved that override in chat for this run, and record the approval in the final report.

**Publishing needs the user.** Finalizing waits for the user's explicit yes in chat. A
delegated or non-interactive run stops after Step 6 and reports the census, the safety report,
and the open decision to its caller.

## Input

Mention `$build-replication-package` with the details in the same message, pick the skill by name, or simply describe the task. Treat the invoking message as this workflow input.

The argument is a target directory, plus optional `--dry-run` (stop after the census) and
`--out <path>`. If no target is given, reply with the usage line,
`build-replication-package <target-dir> [--dry-run] [--out <path>]`, and stop. Never infer
`--out`: when it is absent, the builder uses the manifest's `output_dir`, then
`../<target-basename>-replication`.

## Execution Steps

### Step 1 — Parse arguments

Expand `~` in the target and in `--out`. The builder refuses (exit 2) a target that is not a
directory or has no `PROJECT.md`; report its message and stop.

### Step 2 — Check the project title

Read `<target>/PROJECT.md`. If the Research Project Title is `TBD` or missing, ask for it and
stop: a public package must be titled, and the builder's finalize refuses an unset title too.
Note the research question and deliverables; the builder writes them into the export's README.

### Step 3 — Resolve the manifest

If `<target>/replication.manifest.yaml` exists, validate it:
`python3 Infrastructure/scripts/validate_replication_manifest.py validate <target>/replication.manifest.yaml`.
On failure, report the errors and stop. If it is absent, Step 5's dry run seeds it from
`Infrastructure/scripts/replication_assets/manifest.yaml` and exits 3: report that the manifest
was created, ask the user to review the include and exclude lists, the raw- and processed-data
flags, the license, and the citation, and stop. Never export on the run that creates it.

### Step 4 — Destination safety

The builder refuses (exit 1, RP-1) an output directory that is inside the target, is the
target, is a symlink, is not empty, or already holds a `.git/`. Nothing to check by hand;
report the refusal if it comes.

### Step 5 — Dry run and census

```
python3 Infrastructure/scripts/build_replication_package.py <target> --dry-run [--out <out>]
```

It prints the census (what will be published, what is excluded and why) and the scan summary,
and writes nothing. Show both to the user. The proprietary shell (`Infrastructure/`,
`.claude/`, `.codex/`, `.agents/`) must be in the excluded list. If the user passed `--dry-run`,
stop here.

### Step 6 — Safety review

Spawn `replication-safety-reviewer`:

```
Agent: replication-safety-reviewer
Target directory: <target>
Staged file list: [from the dry-run census]
Manifest: <target>/replication.manifest.yaml
Rules: Infrastructure/rules/replication-publishing-rules.md
Template: Infrastructure/templates/replication-safety-report.md
Output: <target>/review-reports/replication-safety-report.html
```

### Step 7 — Evaluate the gate

Combine the builder's scan summary with the report's counts. If either has an unresolved HIGH
or CRITICAL finding, stop and report the findings and the report path (Gate policy above). The
next run can proceed with `--allow-unsafe` only after the owner approves the override in chat.
MEDIUM findings do not block, but list them for the user to acknowledge.

### Step 8 — Finalize

Show the user the output path and the census summary and ask for a clear yes. The builder
cannot prompt an agent (with no terminal and no `--yes` it exits 2 and writes nothing), so the
yes given in chat is recorded by passing `--yes`:

```
python3 Infrastructure/scripts/build_replication_package.py <target> --out <out> --yes [--allow-unsafe]
```

The builder stages the export in a private temporary directory, renders the scaffolding
(`README.md`, `DATA.md`, `CITATION.cff`, a `LICENSE` placeholder if a license is named,
`.gitignore`, `REPLICATION_MANIFEST.md`), scans the generated files too, runs `git init`,
commits once when git has a user identity (otherwise it stages every file and prints "No git
identity configured"), and moves the result into place. On any failure it removes the partial export
and says so. It refuses, writing nothing, on an unset title, a symlink in scope, or an empty
include set. Exit codes: 0 built or declined, 1 blocked or failed, 2 usage or no
confirmation, 3 manifest seeded.

### Step 9 — Verify and report

Confirm that `<out>` is outside the target, that `git -C <out> log --oneline` shows one commit,
that the scaffolding files exist, and that
`grep -rIl "Infrastructure/\|\.claude\|C:\\\\Users" <out>` finds nothing. If the builder printed
"No git identity configured", there is no commit yet: skip the log check and tell the user to
run `git -C <out> commit` before pushing. Then report:

> Replication package built at `<out>`.
>
> **Included:** <summary>. **Excluded:** proprietary shell, raw data, history.
> **Safety report:** `<target>/review-reports/replication-safety-report.html`.
> **Overrides:** none, or `--allow-unsafe` approved by <owner> in chat.
>
> Next: review the package, paste the license text into `LICENSE`, create an empty GitHub
> repo, then `git -C <out> remote add origin <url>` and `git -C <out> push -u origin HEAD`.
> The branch takes your `init.defaultBranch`; `git -C <out> branch --show-current` names it,
> and `git -C <out> branch -m main` renames it if the repo expects `main`.

Close with an `Evidence` section (Sources, Confidence, Assumptions) per RP-8.
