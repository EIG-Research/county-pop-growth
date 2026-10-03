#!/usr/bin/env python3
"""Bring this template's machinery into an existing private research repository.

    port_template.py TARGET [--mode auto|adopt|upgrade] [--ref REF] [--dry-run]
                     [--skip-checks | --full-checks]

`make port TARGET=<folder>` runs it. The mode comes from the target unless `--mode` sets it:

- **adopt**: the target has no copy of this template (no tracked file under `Infrastructure/`
  that this template ever committed at that path). Every tracked file of an earlier AI setup
  (LEGACY_AI: `CLAUDE.md`, `AGENTS.md`, `.claude/`, `.codex/`, `.agents/`, another
  `Infrastructure/` or `INFRA/`, and similar) moves to `legacy-ai/`, keeping its path, and the
  template's machinery is installed fresh.
- **upgrade**: the target carries an earlier copy, however old. A file the template owns is
  replaced only when the target's committed (path, blob) pair is one this template's history at
  `--ref` holds, which shows the template wrote it; other content is a project edit, kept and
  reported.
  A file the template no longer ships is deleted under the same test, except under
  `Infrastructure/references/`, where the project's catalog entries live and nothing is deleted.

In both modes the project's `code/`, `data/`, `drafts/`, `output/`, `README.md`, and records are
never touched, the template's worked example is never copied, and `make template-reset` is
never run, because it would delete an existing project's plans and logs. The template's CI
workflow is not shipped. Machinery comes from the template's committed tree at `--ref`
(default `main`), never from its working tree.

Guards, all checked before anything is written. There is no flag that skips them:

  G0  the script runs from the source template checkout (it carries the template marker), never
      from a ported project's copy, which would ship that project's own machinery;

  G1  every fetch and push URL of `origin` names one github.com repository, which
      `gh repo view` reports PRIVATE and not archived, asked at run time rather than read from
      any list;
  G2  its owner is EIG-Research or an owner named in the operator-local config;
  G3  the target is the top of a git work tree with a commit and no uncommitted change to a
      tracked file, is not this template or an unreset copy of it, and has no port branch
      yet; no untracked file sits where the port would write;
  G4  the repository is not on the config's skip list and is not a `*-replication` repository,
      which exists to be published.

The operator-local config (`Infrastructure/local/port_config.txt`, gitignored) holds lines
`owner: <github owner>` and `skip: <owner>/<name>`; `#` starts a comment.

The work lands as one local commit on branch `chore/eig-template-v2`, authored by the
configured git user; nothing is pushed. The root marker `.eig-port` records the template
version and commit shipped and the project lane: `legacy` when the project keeps its own layout
(no `code/run_all.R`), which `check_internal_path_references.py` reads to treat the template's
project-lane paths as optional. Managed blocks in `.gitattributes` (LF for the machinery paths
only, so the project's files keep their line endings) and `.gitignore` (secrets, review
reports, personal settings) sit between marker comments and are replaced on each port; the
`.gitignore` block goes first, so the project's own rules and negations still win. On any
failure before the commit, the target is restored to its starting branch and state.

After the commit, the maintenance checks whose verdict depends on the target (TARGET_CHECKS)
run there, or the whole suite with `--full-checks`, or none with `--skip-checks`; the verdict
is reported, and a failure leaves the branch in place for inspection. Every run except a dry run appends a row to the operator-local ledger
`Infrastructure/local/port_ledger.tsv`.

Exit codes: 0 ported (or, with --dry-run, planned); 1 refused or failed; 2 usage.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

TEMPLATE_ROOT = Path(__file__).resolve().parents[2]
BRANCH = "chore/eig-template-v2"
DEFAULT_OWNERS = ("EIG-Research",)
CONFIG = TEMPLATE_ROOT / "Infrastructure" / "local" / "port_config.txt"
LEDGER = TEMPLATE_ROOT / "Infrastructure" / "local" / "port_ledger.tsv"
LEDGER_HEADER = "date\trepository\tmode\tresult\tchecks\tcommit\tflags\tnote\n"

MANIFEST = ".brain-manifest"
PORT_MARKER = ".eig-port"
TEMPLATE_MARKER = "Infrastructure/.template-identity"
LOCAL_DIR = "Infrastructure/local/"
REFERENCES_DIR = "Infrastructure/references/"
ROOT_FILES = ("AGENTS.md", "CLAUDE.md", "Makefile", "CHANGELOG.md", "NOTICE", ".lintr", ".renvignore")
SIDE_BY_SIDE = ("Makefile",)  # a project's own copy stays; the template's lands beside it
LEGACY_DIR = "legacy-ai"
# INFRA/ and AI_AGENT_ROUTING.md are the AI setup of EIG's earlier baseline shell.
LEGACY_AI = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".claude", ".codex", ".agents", ".cursor",
             ".cursorrules", ".windsurfrules", ".github/copilot-instructions.md", "Infrastructure", MANIFEST,
             "INFRA", "AI_AGENT_ROUTING.md")
KEEP_IN_PLACE = (".claude/settings.local.json", ".claude/settings.local.json.bak")  # personal settings
ADAPTER_ROOTS = (".claude", ".codex", ".agents")
RETIRED_SURFACES = (".codex/commands/", ".codex/templates/", ".codex/skills/")  # brain.py RETIRED_DIRS
# Older template versions kept project records under Infrastructure/; they now live in records/.
OLD_RECORDS = {"Infrastructure/plans/": "records/plans/", "Infrastructure/specs/": "records/specs/",
               "Infrastructure/session_logs/": "records/session_logs/"}
SIZE_LIMIT = 50 * 1024 * 1024  # GitHub warns at 50 MB and refuses at 100 MB
# The registered checks whose verdict depends on the target rather than on the template's own
# code, which every target shares; the rest of the suite reruns the template's tests (`--full-checks`).
TARGET_CHECKS = ("brain-check", "brain-lints", "brain-load", "internal-paths", "literature-catalog",
                 "dataset-registry")
LEGACY_NOTE = ("- Instructions from the AI setup this project had before the template port are in "
               "`legacy-ai/`; fold what still applies into this file.")
CONTEXT_PLACEHOLDER = "Add any context that would help an AI agent work correctly over time.\n\n`TBD`"

BLOCK_START = "# >>> eig-template: managed by port_template.py; edit outside this block >>>"
BLOCK_END = "# <<< eig-template <<<"
GITATTRIBUTES_BLOCK = (
    "# The template's checks compare its files byte for byte, so its paths are LF on every",
    "# platform. The project's own files keep the line endings they had.",
    "Infrastructure/** text=auto eol=lf",
    ".claude/** text=auto eol=lf",
    ".codex/** text=auto eol=lf",
    ".agents/** text=auto eol=lf",
    "records/** text=auto eol=lf",
    *(f"{name} text=auto eol=lf" for name in (MANIFEST, PORT_MARKER, "PROJECT.md", *ROOT_FILES)),
    "*.patch -text",
    *(f"*.{ext} binary" for ext in ("pdf", "png", "jpg", "eps", "ai", "ttf", "otf", "woff", "woff2",
                                     "parquet", "rds", "dta")),
)
GITIGNORE_BLOCK = (
    "# Secrets: .Renviron and .env files hold API keys and credentials.",
    ".Renviron",
    ".env",
    ".env.*",
    "!.env.example",
    "# Bytecode from the template's scripts.",
    "__pycache__/",
    "*.py[cod]",
    "# Review reports and board renders: regenerated on every run, never published.",
    "review-reports/",
    "**/review-reports/",
    "records/review_boards/*/renders/",
    "records/war_rooms/**/*.lock",
    "# Personal Claude settings, agent worktrees, and operator-local notes.",
    ".claude/settings.local.json",
    ".claude/worktrees/",
    "Infrastructure/local/",
)

# The three URL forms GitHub hands out, host anchored: https://github.com/o/n(.git),
# git@github.com:o/n(.git), and ssh://git@github.com/o/n(.git).
GITHUB_RE = re.compile(r"^(?:https://(?:[^@/\s]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
                       r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", re.IGNORECASE)
EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


class PortRefused(Exception):
    """A guard failed; nothing was written."""


class PortError(Exception):
    """The port failed after it started; the target has been restored."""


Lookup = Callable[[str], dict]


# --------------------------------------------------------------------------- git helpers
def git(cwd: Path, *args: str, stdin: bytes | None = None, check: bool = True) -> bytes:
    proc = subprocess.run(["git", *args], cwd=cwd, input=stdin, capture_output=True)
    if check and proc.returncode:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise PortError(f"`git {' '.join(args[:3])}` failed in {cwd}: {detail}")
    return proc.stdout


def tree(repo: Path, ref: str) -> dict[str, tuple[str, str]]:
    """{path: (mode, blob sha)} for every blob committed at `ref`."""
    entries: dict[str, tuple[str, str]] = {}
    for record in git(repo, "ls-tree", "-r", "-z", "--full-tree", ref).split(b"\0"):
        if record:
            meta, path = record.decode("utf-8").split("\t", 1)
            mode, kind, sha = meta.split()
            if kind == "blob":
                entries[path] = (mode, sha)
    return entries


def index(repo: Path) -> dict[str, tuple[str, str]]:
    """{path: (mode, blob sha)} for every tracked file; on a clean tree this is HEAD."""
    entries: dict[str, tuple[str, str]] = {}
    for record in git(repo, "ls-files", "-s", "-z").split(b"\0"):
        if record:
            meta, path = record.decode("utf-8").split("\t", 1)
            mode, sha, _stage = meta.split()
            entries[path] = (mode, sha)
    return entries


def read_blobs(repo: Path, shas: list[str]) -> dict[str, bytes]:
    """Blob contents by sha, read through one `git cat-file --batch`."""
    unique = list(dict.fromkeys(shas))
    if not unique:
        return {}
    out = git(repo, "cat-file", "--batch", stdin=("\n".join(unique) + "\n").encode())
    blobs, pos = {}, 0
    for sha in unique:
        end = out.index(b"\n", pos)
        header = out[pos:end].decode().split()
        if len(header) < 3 or header[1] != "blob":
            raise PortError(f"template object {sha} is not a readable blob")
        start = end + 1
        blobs[sha] = out[start:start + int(header[2])]
        pos = start + int(header[2]) + 1
    return blobs


def history_blobs(repo: Path, ref: str) -> set[tuple[str, str]]:
    """Every (path, blob sha) the template has committed on the history of `ref`: what it shipped
    at that path. The empty blob never counts, since an empty project file is not the template's."""
    raw = git(repo, "log", ref, "--format=", "--raw", "--no-abbrev", "--no-renames", "--diff-merges=first-parent",
              "-z").split(b"\0")
    pairs: set[tuple[str, str]] = set()
    i = 0
    while i < len(raw) - 1:
        meta = raw[i].decode("utf-8", "replace").strip()
        if not meta.startswith(":"):
            i += 1
            continue
        path = raw[i + 1].decode("utf-8")
        _old_mode, _new_mode, old, new, _status = meta[1:].split()
        pairs |= {(path, sha) for sha in (old, new) if set(sha) != {"0"} and sha != EMPTY_BLOB}
        i += 2
    return pairs


# --------------------------------------------------------------------------- template snapshot
@dataclass
class Snapshot:
    commit: str
    version: str
    machinery: dict[str, tuple[str, str]]
    records: dict[str, tuple[str, str]]
    project_md: tuple[str, str]
    generated: list[str]
    known: set[tuple[str, str]]


def ships(path: str) -> bool:
    if path.startswith("Infrastructure/"):
        return path != TEMPLATE_MARKER and not path.startswith(LOCAL_DIR)
    return path in ROOT_FILES


def snapshot(template: Path, ref: str, known_extra: set[tuple[str, str]] | None = None) -> Snapshot:
    commit = git(template, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    files = tree(template, commit)
    for required in (MANIFEST, "CHANGELOG.md", "PROJECT.md", "Infrastructure/scripts/brain.py"):
        if required not in files:
            raise PortError(f"template ref {ref} has no {required}")
    meta = read_blobs(template, [files[MANIFEST][1], files["CHANGELOG.md"][1]])
    generated = [line for line in meta[files[MANIFEST][1]].decode("utf-8").splitlines()
                 if line and not line.startswith("#")]
    version = re.search(r"^## (\S+)", meta[files["CHANGELOG.md"][1]].decode("utf-8"), re.MULTILINE)
    return Snapshot(
        commit=commit,
        version=version.group(1) if version else "unknown",
        machinery={p: e for p, e in files.items() if ships(p)},
        records={p: e for p, e in files.items()
                 if p.startswith("records/") and p.rsplit("/", 1)[-1] in ("README.md", ".gitkeep")},
        project_md=files["PROJECT.md"],
        generated=generated,
        known=history_blobs(template, commit) | (known_extra or set()),
    )


# --------------------------------------------------------------------------- guards
def gh_lookup(slug: str) -> dict:
    """Ask GitHub, now, for the repository's visibility; any failure refuses (G1)."""
    try:
        proc = subprocess.run(["gh", "repo", "view", slug, "--json", "visibility,isArchived,nameWithOwner"],
                              capture_output=True, text=True, errors="replace")
    except OSError as exc:
        raise PortRefused(f"G1: the GitHub CLI could not run, so the visibility of {slug} is unknown: {exc}")
    if proc.returncode:
        raise PortRefused(f"G1: `gh repo view {slug}` failed, so its visibility is unknown: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def read_config(path: Path) -> tuple[set[str], set[str]]:
    owners, skip = {o.casefold() for o in DEFAULT_OWNERS}, set()
    if path.is_file():
        for raw in path.read_text(encoding="utf-8-sig").splitlines():  # a PowerShell BOM is not a key
            key, _, value = raw.split("#", 1)[0].partition(":")
            key, value = key.strip().casefold(), value.strip().casefold()
            if key == "owner" and value:
                owners.add(value)
            elif key == "skip" and value:
                skip.add(value)
    return owners, skip


def origin_slug(repo: Path) -> str:
    """`owner/name` of origin, when every fetch and push URL it has names that one GitHub repository."""
    urls = []
    for key in ("url", "pushurl"):
        out = git(repo, "config", "--get-all", f"remote.origin.{key}", check=False).decode().split("\n")
        urls += [url.strip() for url in out if url.strip()]
    if not urls:
        raise PortRefused("G1: the target has no origin remote")
    slugs = set()
    for url in urls:
        match = GITHUB_RE.match(url)
        if not match:
            raise PortRefused(f"G1: an origin URL is not a github.com repository: {url}")
        slugs.add(f"{match.group(1)}/{match.group(2)}".casefold())
    if len(slugs) != 1:
        raise PortRefused(f"G1: origin's fetch and push URLs name different repositories: {', '.join(urls)}")
    match = GITHUB_RE.match(urls[0])
    return f"{match.group(1)}/{match.group(2)}"


def guard(target: Path, lookup: Lookup, config: Path, template: Path) -> str:
    """The repository's `owner/name` once every guard passes; PortRefused otherwise."""
    if not target.is_dir():
        raise PortRefused(f"G3: {target} is not a folder")
    top = git(target, "rev-parse", "--show-toplevel", check=False).decode().strip()
    if not top or Path(top).resolve() != target.resolve():
        raise PortRefused(f"G3: {target} is not the top of a git work tree")
    if target.resolve() == template.resolve() or (target / TEMPLATE_MARKER).exists():
        raise PortRefused("G3: the target is this template, or a copy of it that `make template-reset` "
                          "has not turned into a project")
    if not git(target, "rev-parse", "--verify", "--quiet", "HEAD", check=False).strip():
        raise PortRefused("G3: the target has no commit yet")
    if git(target, "status", "--porcelain", "--untracked-files=no").strip():
        raise PortRefused("G3: the target has uncommitted changes to tracked files; commit or stash them first")
    if git(target, "rev-parse", "--verify", "--quiet", f"refs/heads/{BRANCH}", check=False).strip():
        raise PortRefused(f"G3: branch {BRANCH} already exists in the target; merge or delete it first")
    slug = origin_slug(target)
    try:
        template_slug = origin_slug(template)
    except PortRefused:
        template_slug = ""
    if slug.casefold() == template_slug.casefold():
        raise PortRefused("G3: the target's origin is this template's repository")
    info = lookup(slug)
    real = str(info.get("nameWithOwner") or slug)  # GitHub follows renames and transfers
    if info.get("visibility") != "PRIVATE":
        raise PortRefused(f"G1: GitHub reports {real} as {info.get('visibility')}, not PRIVATE; "
                          "the template is never ported into a repository that is not private")
    if info.get("isArchived"):
        raise PortRefused(f"G1: {real} is archived")
    owners, skip = read_config(config)
    owner, name = real.split("/", 1)
    if owner.casefold() not in owners:
        raise PortRefused(f"G2: owner {owner} is not EIG-Research or an owner in {config.name}")
    if real.casefold() in skip or slug.casefold() in skip:
        raise PortRefused(f"G4: {real} is on the skip list in {config.name}")
    if name.casefold().endswith("-replication") or slug.casefold().endswith("-replication"):
        raise PortRefused(f"G4: {real} is a replication repository, which exists to be published")
    return real


# --------------------------------------------------------------------------- plan
@dataclass
class Plan:
    mode: str
    moves: list[tuple[str, str]] = field(default_factory=list)
    writes: dict[str, tuple[str, str]] = field(default_factory=dict)
    deletes: list[str] = field(default_factory=list)
    project_md: bool = False
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def under(path: str, item: str) -> bool:
    return path == item or path.startswith(item + "/")


def exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def replaceable(path: str, mode: str) -> bool:
    """Template-owned machinery whose project copy is set aside rather than kept when it matches no
    shipped version: anything under Infrastructure/ except the project's reference entries, and in
    an upgrade the root instructions. A project's own root files (its CHANGELOG.md, say) stay."""
    if path.startswith("Infrastructure/"):
        return not path.startswith(REFERENCES_DIR)
    return mode == "upgrade" and path in ("AGENTS.md", "CLAUDE.md")


def detect_mode(tracked: dict[str, tuple[str, str]], known: set[tuple[str, str]]) -> str:
    """Upgrade when any tracked file under Infrastructure/ is one this template committed there,
    which marks a copy of this template however old; otherwise adopt."""
    return "upgrade" if any(path.startswith("Infrastructure/") and (path, sha) in known
                            for path, (_mode, sha) in tracked.items()) else "adopt"


def build_plan(target: Path, snap: Snapshot, mode: str, tracked: dict[str, tuple[str, str]]) -> Plan:
    plan = Plan(mode)
    moved: set[str] = set()
    if mode == "adopt":
        if exists(target / LEGACY_DIR):
            raise PortRefused(f"G3: {LEGACY_DIR}/ already exists in the target")
        for path in sorted(tracked):
            if path not in KEEP_IN_PLACE and any(under(path, item) for item in LEGACY_AI):
                plan.moves.append((path, f"{LEGACY_DIR}/{path}"))
                moved.add(path)
    plan.notes += [f"{path}: personal settings are committed; the new ignore line does not untrack them"
                   for path in KEEP_IN_PLACE if path in tracked]
    blocked: list[str] = []
    for path, entry in sorted(snap.machinery.items()):
        current = None if path in moved else tracked.get(path)
        if current is None:
            if exists(target / path) and path not in moved:
                blocked.append(path)
            else:
                plan.writes[path] = entry
        elif current[1] == entry[1]:
            continue
        elif (path, current[1]) in snap.known:
            plan.writes[path] = entry
        elif path in SIDE_BY_SIDE:
            side = f"{path}.eig-template"
            plan.writes[side] = entry
            plan.flags.append(f"{path}: the project's own; the template's is at {side} for a manual merge")
        elif (replaceable(path, mode) and not exists(target / LEGACY_DIR / path)):
            # Stale machinery breaks the checks, so the template's copy goes in and the project's
            # moves to legacy-ai/ (the moves run before the writes).
            plan.moves.append((path, f"{LEGACY_DIR}/{path}"))
            plan.writes[path] = entry
            plan.flags.append(f"{path}: matches no version this template has shipped; installed the template's, "
                              f"the project's copy is at {LEGACY_DIR}/{path}")
        else:
            plan.flags.append(f"{path}: matches no version this template has shipped; kept the project's copy")
    if mode == "upgrade":
        generated = set(snap.generated)
        old_manifest: set[str] = set()
        if MANIFEST in tracked:
            text = read_blobs(target, [tracked[MANIFEST][1]])[tracked[MANIFEST][1]].decode("utf-8", "replace")
            old_manifest = {line for line in text.splitlines() if line and not line.startswith("#")}
        # Folders under Infrastructure/ that hold the project's own files, other than the old
        # record folders, whose contents move to records/.
        project_dirs = {path.rsplit("/", 1)[0] for path, (_mode, sha) in tracked.items()
                        if path.startswith("Infrastructure/") and "/" in path[len("Infrastructure/"):]
                        and path not in snap.machinery and (path, sha) not in snap.known
                        and not any(path.startswith(old) for old in OLD_RECORDS)}
        for path, (_mode, sha) in sorted(tracked.items()):
            root = path.split("/", 1)[0]
            if root in ADAPTER_ROOTS and path not in generated and path not in KEEP_IN_PLACE:
                # An adapter file sync no longer generates. The template's own output is deleted.
                # Other content stays where it is (sync never touches an unlisted file) unless
                # staying is unsafe: sync deletes a path the old manifest lists, and a retired
                # Codex surface fails brain-check. Those move to legacy-ai/.
                if (path, sha) in snap.known:
                    plan.deletes.append(path)
                elif path not in old_manifest and not path.startswith(RETIRED_SURFACES):
                    plan.notes.append(f"{path}: the project's own adapter file, kept")
                elif exists(target / LEGACY_DIR / path):
                    plan.flags.append(f"{path}: not template-written and {LEGACY_DIR}/{path} exists; "
                                      "move it by hand, or the next sync may delete it")
                else:
                    plan.moves.append((path, f"{LEGACY_DIR}/{path}"))
                    plan.flags.append(f"{path}: not template-written; moved to {LEGACY_DIR}/{path}")
                continue
            if (not path.startswith("Infrastructure/") or path.startswith(LOCAL_DIR)
                    or path in snap.machinery or path == TEMPLATE_MARKER):
                continue
            old_record = next((old for old in OLD_RECORDS if path.startswith(old)), None)
            if (path, sha) in snap.known and not path.startswith(REFERENCES_DIR):
                if path.rsplit("/", 1)[0] in project_dirs:
                    # The project still files its own work in this folder (an explorations
                    # lane, say), so the template's README for it stays.
                    plan.notes.append(f"{path}: retired by the template, kept because its folder holds project files")
                else:
                    plan.deletes.append(path)
            elif old_record:
                dst = OLD_RECORDS[old_record] + path[len(old_record):]
                if dst in tracked or exists(target / dst) or dst in plan.writes:
                    plan.flags.append(f"{path}: an old-layout record, not moved because {dst} exists")
                else:
                    plan.moves.append((path, dst))
            elif path.startswith(REFERENCES_DIR):
                plan.notes.append(f"{path}: the project's reference entry, kept")
            else:
                plan.notes.append(f"{path}: the project's own file under Infrastructure/, kept")
    for path in snap.generated:
        if path not in tracked and exists(target / path):
            blocked.append(path)
    moved_to = {dst for _src, dst in plan.moves}
    for path, entry in sorted(snap.records.items()):
        if path not in tracked and not exists(target / path) and path not in moved_to:
            plan.writes[path] = entry
    for name in (".gitattributes", ".gitignore", PORT_MARKER, *(f"{m}.eig-template" for m in SIDE_BY_SIDE)):
        if name not in tracked and exists(target / name):
            blocked.append(name)
    for name in (".gitattributes", ".gitignore"):
        if (target / name).is_file():
            try:
                (target / name).read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise PortRefused(f"G3: {name} is not UTF-8 text; convert it before porting")
    if "PROJECT.md" not in tracked:
        if exists(target / "PROJECT.md"):
            blocked.append("PROJECT.md")
        else:
            plan.project_md = True
    if blocked:
        raise PortRefused("G3: untracked files sit where the port writes; move them out first:\n"
                          + "".join(f"  {path}\n" for path in sorted(set(blocked))))
    return plan


def describe(plan: Plan) -> str:
    to_legacy = sum(dst.startswith(LEGACY_DIR + "/") for _src, dst in plan.moves)
    lines = [f"Mode: {plan.mode}",
             f"  move to {LEGACY_DIR}/: {to_legacy} tracked file(s)",
             f"  move old-layout records to records/: {len(plan.moves) - to_legacy} file(s)",
             f"  write from the template: {len(plan.writes)} file(s)",
             f"  delete (template-written, no longer shipped): {len(plan.deletes)} file(s)",
             f"  create PROJECT.md: {'yes' if plan.project_md else 'no'}",
             "  update the managed blocks in .gitattributes and .gitignore; write .eig-port; run brain.py sync"]
    lines += [f"  FLAG {flag}" for flag in plan.flags]
    lines += [f"  note {note}" for note in plan.notes[:5]]
    if len(plan.notes) > 5:
        lines.append(f"  note ... and {len(plan.notes) - 5} more project file(s) kept")
    return "\n".join(lines)


# --------------------------------------------------------------------------- apply
def upsert_block(path: Path, body: tuple[str, ...], top: bool) -> None:
    """Write the managed block, replacing an earlier one wherever it sits.

    Later lines win in both files. In .gitignore the block goes first (`top`), so the project's
    own rules and negations override it; in .gitattributes it goes last, so the machinery paths
    are LF whatever the project's earlier lines say."""
    raw = path.read_bytes().decode("utf-8") if path.is_file() else ""
    newline = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    if BLOCK_START in text and BLOCK_END in text:
        head, rest = text.split(BLOCK_START, 1)
        text = head.rstrip("\n") + "\n" + rest.split(BLOCK_END, 1)[1].lstrip("\n")
        text = text.strip("\n") + "\n" if text.strip() else ""
    block = "\n".join((BLOCK_START, *body, BLOCK_END)) + "\n"
    if top:
        text = block + ("\n" + text if text.strip() else "")
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def prune_empty(root: Path, directory: Path) -> None:
    while directory != root and root in directory.parents:
        try:
            directory.rmdir()
        except OSError:
            return
        directory = directory.parent


def project_lane(target: Path) -> str:
    return "template" if (target / "code" / "run_all.R").is_file() else "legacy"


def staged_too_large(target: Path) -> list[str]:
    """Files the commit would add or change (not renames of committed files) over SIZE_LIMIT."""
    found = []
    # -z output is status, path for most entries, and status, old path, new path for R and C.
    fields = git(target, "diff", "--cached", "--name-status", "-M", "-z").decode("utf-8").split("\0")
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status.startswith(("R", "C")):
            i += 3
            continue
        path = fields[i + 1]
        i += 2
        if status in ("A", "M") and (target / path).is_file() and (target / path).stat().st_size > SIZE_LIMIT:
            found.append(path)
    return found


def run_sync(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(target / "Infrastructure" / "scripts" / "brain.py"), "sync"],
                          cwd=target, capture_output=True, text=True, errors="replace")


def apply(target: Path, snap: Snapshot, plan: Plan, tracked: dict[str, tuple[str, str]], template: Path) -> str:
    """Make the port commit on BRANCH and return its sha; on failure restore the target."""
    start = git(target, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).decode().strip() \
        or git(target, "rev-parse", "HEAD").decode().strip()
    git(target, "checkout", "-q", "-b", BRANCH)
    created: list[str] = []
    try:
        for src, dst in plan.moves:
            (target / dst).parent.mkdir(parents=True, exist_ok=True)
            os.replace(target / src, target / dst)
            created.append(dst)
        for src, _dst in plan.moves:
            prune_empty(target, (target / src).parent)
        shas = [sha for _mode, sha in plan.writes.values()] + [snap.project_md[1]]
        blobs = read_blobs(template, shas)
        for path, (mode, sha) in plan.writes.items():
            out = target / path
            if not exists(out):
                created.append(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(blobs[sha])
            if mode == "100755":
                out.chmod(out.stat().st_mode | 0o111)
        for path in plan.deletes:
            (target / path).unlink()
            prune_empty(target, (target / path).parent)
        if plan.project_md:
            text = blobs[snap.project_md[1]].decode("utf-8")
            if any(dst.startswith(LEGACY_DIR + "/") for _src, dst in plan.moves):
                text = text.replace(CONTEXT_PLACEHOLDER, CONTEXT_PLACEHOLDER.replace("`TBD`", LEGACY_NOTE))
            (target / "PROJECT.md").write_bytes(text.encode("utf-8"))
            created.append("PROJECT.md")
        for name, body in ((".gitattributes", GITATTRIBUTES_BLOCK), (".gitignore", GITIGNORE_BLOCK)):
            if not exists(target / name):
                created.append(name)
            upsert_block(target / name, body, top=name == ".gitignore")
        if not exists(target / PORT_MARKER):
            created.append(PORT_MARKER)
        (target / PORT_MARKER).write_bytes((
            "# Written by the EIG template's port_template.py; the next port reads it.\n"
            f"template_version: {snap.version}\n"
            f"template_commit: {snap.commit}\n"
            f"mode: {plan.mode}\n"
            f"ported: {datetime.date.today().isoformat()}\n"
            f"project_lane: {project_lane(target)}\n").encode("utf-8"))
        sync = run_sync(target)
        # An older generation's canonical files the port kept as the project's own (a retired rule
        # in a version this template never shipped, say) can fail the current frontmatter schema.
        # When those are the only files sync rejects, set them aside in legacy-ai/ and sync again.
        rejected = list(dict.fromkeys(re.findall(r"^\s+(Infrastructure/[^:\n]+):", sync.stdout + sync.stderr,
                                                 re.MULTILINE)))
        kept = [p for p in rejected if p in tracked and p not in snap.machinery
                and exists(target / p) and not exists(target / LEGACY_DIR / p)]
        if sync.returncode and rejected and kept == rejected:
            for path in kept:
                dst = f"{LEGACY_DIR}/{path}"
                (target / dst).parent.mkdir(parents=True, exist_ok=True)
                os.replace(target / path, target / dst)
                created.append(dst)
                plan.moves.append((path, dst))
                plan.flags.append(f"{path}: fails the current frontmatter schema, which stops sync; "
                                  f"moved to {dst}")
            sync = run_sync(target)
        if sync.returncode:
            raise PortError(f"brain.py sync failed in the target:\n{sync.stdout}{sync.stderr}")
        generated = [line for line in (target / MANIFEST).read_text(encoding="utf-8").splitlines()
                     if line and not line.startswith("#")]
        paths = {src for src, _ in plan.moves} | {dst for _, dst in plan.moves} | set(plan.writes)
        paths |= set(plan.deletes) | set(generated) | {".gitattributes", ".gitignore", PORT_MARKER}
        paths |= {p for p in tracked if p.split("/", 1)[0] in (".claude", ".codex", ".agents")}
        if plan.project_md:
            paths.add("PROJECT.md")
        stage = sorted(p for p in paths if exists(target / p) or p in tracked)
        with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".pathspec") as handle:
            handle.write(b"\0".join(p.encode("utf-8") for p in stage))
        try:
            git(target, "--literal-pathspecs", "add", "-A", "-f", f"--pathspec-from-file={handle.name}",
                "--pathspec-file-nul")
        finally:
            os.unlink(handle.name)
        executable = [p for p, (mode, _sha) in plan.writes.items() if mode == "100755"]
        if executable:
            git(target, "update-index", "--chmod=+x", "--", *executable)
        large = staged_too_large(target)
        if large:
            raise PortError(f"the commit would add file(s) over {SIZE_LIMIT // (1024 * 1024)} MB: {', '.join(large)}")
        body = [f"Mode: {plan.mode}. Template {snap.version} at {snap.commit[:12]}.",
                f"Moved {sum(d.startswith(LEGACY_DIR + '/') for _s, d in plan.moves)} file(s) to {LEGACY_DIR}/ "
                f"and {sum(not d.startswith(LEGACY_DIR + '/') for _s, d in plan.moves)} old-layout record(s) "
                f"to records/; wrote {len(plan.writes)}; deleted {len(plan.deletes)}."]
        body += [f"Flag: {flag}" for flag in plan.flags[:40]]
        git(target, "commit", "-q", "-m", f"chore: port the EIG research template ({snap.version}, {plan.mode})",
            "-m", "\n".join(body))
        return git(target, "rev-parse", "HEAD").decode().strip()
    except BaseException as exc:
        left = restore(target, start, created, snap.generated)
        if left:
            raise PortError(f"{exc}\nRESTORE INCOMPLETE; left behind: {', '.join(left[:20])}") from exc
        raise


def restore(target: Path, start: str, created: list[str], generated: list[str]) -> list[str]:
    """Put the target back as it was: tracked files from HEAD, created files removed, branch gone.

    Every step runs even when an earlier one fails (a Windows file lock, say); the return value
    lists what could not be restored, empty when the target is exactly as it was."""
    left: list[str] = []
    git(target, "reset", "-q", "--hard", "HEAD", check=False)
    if git(target, "status", "--porcelain", "--untracked-files=no", check=False).strip():
        left.append("tracked files (git reset did not finish)")
    try:
        head = index(target)
    except PortError:
        head = {}
    for path in reversed([*created, *generated]):
        out = target / path
        if path not in head and out.is_file():
            try:
                out.unlink()
                prune_empty(target, out.parent)
            except OSError:
                left.append(path)
    git(target, "checkout", "-q", start, check=False)
    if git(target, "branch", "--show-current", check=False).decode().strip() == BRANCH:
        left.append(f"still on branch {BRANCH}")
    else:
        git(target, "branch", "-q", "-D", BRANCH, check=False)
    return left


def run_checks(target: Path, full: bool) -> str:
    """Run the target's maintenance checks: TARGET_CHECKS, or with `full` the whole suite."""
    runner = target / "Infrastructure" / "scripts" / "run_maintenance_checks.py"
    only = [] if full else [arg for name in TARGET_CHECKS for arg in ("--only", name)]
    proc = subprocess.run([sys.executable, str(runner), *only], cwd=target, capture_output=True, text=True,
                          errors="replace")
    if not proc.returncode:
        return "pass" if full else "pass (target checks)"
    # The runner's summary lists each failed check as `  FAIL  <name>  (<time>, exit=N)`.
    failed = [m.group(1) for m in re.finditer(r"^\s+FAIL\s+([a-z][\w-]*)\s+\(", proc.stdout, re.MULTILINE)]
    tail = (proc.stdout + proc.stderr).splitlines()[-25:]
    print("Checks FAILED in the target; last lines:\n" + "\n".join(f"    {line}" for line in tail))
    return "fail: " + (", ".join(failed) or f"exit {proc.returncode}")


def record(ledger: Path, row: list[str]) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    new = not ledger.is_file()
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
        if new:
            handle.write(LEDGER_HEADER)
        handle.write("\t".join(cell.replace("\t", " ").replace("\n", " ") for cell in row) + "\n")


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None, lookup: Lookup = gh_lookup,
         known_extra: set[tuple[str, str]] | None = None,
         template: Path = TEMPLATE_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    parser.add_argument("target", type=Path, help="the repository folder to port into")
    parser.add_argument("--mode", choices=("auto", "adopt", "upgrade"), default="auto")
    parser.add_argument("--ref", default="main", help="the template ref whose committed tree ships (default main)")
    parser.add_argument("--dry-run", action="store_true", help="check the guards and print the plan; change nothing")
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--skip-checks", action="store_true", help="run no checks in the target afterwards")
    checks.add_argument("--full-checks", action="store_true",
                        help="run the whole maintenance suite in the target, not only TARGET_CHECKS")
    parser.add_argument("--config", type=Path, default=CONFIG, help=argparse.SUPPRESS)
    parser.add_argument("--ledger", type=Path, default=LEDGER, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not (template / TEMPLATE_MARKER).is_file():
        # A ported project carries this script too; run from there it would ship that project's
        # own machinery, edits and all, instead of the template's.
        print("REFUSED: the port runs only from the source template checkout, which carries "
              f"{TEMPLATE_MARKER}; this checkout is a project")
        return 1
    target = args.target.resolve()
    today = datetime.date.today().isoformat()
    slug, mode = str(target), args.mode
    try:
        slug = guard(target, lookup, args.config, template)
        tracked = index(target)
        snap = snapshot(template, args.ref, known_extra)
        mode = detect_mode(tracked, snap.known) if args.mode == "auto" else args.mode
        plan = build_plan(target, snap, mode, tracked)
    except (PortRefused, PortError) as exc:
        print(f"REFUSED {slug}: {exc}")
        if not args.dry_run:
            record(args.ledger, [today, slug, mode, "refused", "-", "-", "0", str(exc).splitlines()[0]])
        return 1
    print(f"{slug}: private on GitHub; template {snap.version} at {snap.commit[:12]} ({args.ref})")
    print(describe(plan))
    if args.dry_run:
        print("Dry run: nothing changed.")
        return 0
    try:
        commit = apply(target, snap, plan, tracked, template)
    except (PortError, OSError) as exc:
        restored = "RESTORE INCOMPLETE" not in str(exc)
        print(f"FAILED {slug}: {exc}" + ("\nThe target was restored to its starting state." if restored else ""))
        result = "failed" if restored else "failed-RESTORE-INCOMPLETE"
        record(args.ledger, [today, slug, mode, result, "-", "-", str(len(plan.flags)), " | ".join(str(exc).splitlines())])
        return 1
    print(f"Committed {commit[:12]} on {BRANCH}; nothing was pushed.")
    checks = "skipped" if args.skip_checks else run_checks(target, args.full_checks)
    print(f"Checks in the target: {checks}")
    record(args.ledger, [today, slug, mode, "ported", checks, commit[:12], str(len(plan.flags)),
                         "; ".join(plan.flags)[:500]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
