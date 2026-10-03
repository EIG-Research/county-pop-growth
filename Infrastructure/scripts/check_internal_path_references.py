#!/usr/bin/env python3
"""Validate internal markdown path references used by template docs.

Walks every Markdown file in the canonical and adapter trees plus the
root-level adapter instructions, and the project records under `records/`. Any
code-span or link target that points inside the repo (Infrastructure/, records/,
.claude/, .codex/, .agents/, code/, data/, drafts/, output/, or one of the named
root files) is resolved and verified
to exist on disk. A `./` or `../` target is resolved from the referencing file (or, for a
source `brain.py sync` renders elsewhere, from its rendered location; RENDERED_AT) and
checked when it lands inside the repository. Four kinds of internal path are optional: the source-template
identity marker, which `make template-reset` intentionally removes in derived
research projects; anything under the gitignored `Infrastructure/local/`,
which holds operator-local machine notes that exist only on the operator's own
machine; a project's dataset overlay (`data/docs/` and
`data/docs/dataset-registry.yaml`), which the first documentation pass creates; and, only
outside the template (no identity marker), the worked example's data and drafts, which a
project deletes when it replaces the example (EXAMPLE_PATHS). In a repository the port script
brought the template into with its own layout kept (`.eig-port` says `project_lane: legacy`),
every project-lane path is optional too (PROJECT_LANE_PREFIXES), and so is a root `README.md`,
which an older project may never have had. Targets outside the allow-list
are skipped silently.

`records/plans/`, `records/specs/`, the subdirectories of
`records/war_rooms/` and `records/review_boards/`, and the fixture
directories `Infrastructure/scripts/war_room_fixtures/` and
`Infrastructure/scripts/review_board_fixtures/` are excluded from the walk: they describe work that has not been done yet, or
code that lives somewhere other than this repository, so their references are
correct-by-design rather than broken. See FORWARD_LOOKING_INFRA_PATHS.

A second pass reads the non-Markdown files git tracks, or would track, under
`Infrastructure/`, the adapter trees, `.github/`, and the `Makefile` (scripts, configs,
templates in other formats), which the Markdown walk never opens, and
fails on any citation of a dated plan, spec, or session log under `records/`: `make
template-reset` deletes those, so the citation dangles in every project. See
DATED_RECORD_RE.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
LINE_SUFFIX_RE = re.compile(r":\d+(?::\d+)?$")

# Anything that begins with one of these prefixes is in scope for validation.
# Adapter trees (.claude/, .codex/, .agents/) and the root-level adapter
# instruction files (CLAUDE.md, AGENTS.md) are included so broken references
# inside the generated mirrors do not silently ship.
ALLOWED_INTERNAL_PREFIXES = (
    "Infrastructure/",
    "records/",
    ".codex/",
    ".claude/",
    ".agents/",
    "code/",
    "data/",
    "drafts/",
    "output/",
    "PROJECT.md",
    "README.md",
    "Makefile",
    "CLAUDE.md",
    "AGENTS.md",
    "CHANGELOG.md",
    "NOTICE",
)

# Top-level Markdown files we treat as in-scope alongside Infrastructure/.
ROOT_MARKDOWN_FILES = (
    "README.md",
    "PROJECT.md",
    "CLAUDE.md",
    "AGENTS.md",
    "CHANGELOG.md",
)

# Top-level directories walked in full, before the adapter trees. `records/` holds the
# project records (plans, specs, session logs, war rooms, review boards); the
# forward-looking parts of it are exempt through FORWARD_LOOKING_INFRA_PATHS.
WALKED_DIRS = (
    "Infrastructure",
    "records",
)

# Adapter directories that the validator also walks for internal references.
ADAPTER_DIRS = (
    ".claude",
    ".codex",
    ".agents",
)

# Claude Code creates isolated agent worktrees under `.claude/worktrees/`. Each is a
# full checkout of this repository, so scanning it would validate another checkout's
# references against this one and report its relative paths as broken. The directory
# is gitignored for the same reason.
NESTED_WORKTREE_PARTS = (".claude", "worktrees")

# This marker exists only in the source template. `make template-reset` deletes
# it when creating a research project, while documentation continues to explain
# both sides of that lifecycle. Every other in-scope internal path must exist.
#
# A project's dataset overlay (Infrastructure/rules/data-documentation-rules.md DD-4) is
# created by the first documentation pass, so the template and a new project lack it. Only
# the directory and the overlay file are exempt; a named doc under data/docs/ must exist.
#
# The AI-use ledger (Infrastructure/rules/ai-use-disclosure-rules.md) is created from its
# template the first time a session uses AI for work product, and `make template-reset`
# removes it, so the template and a new project lack it.
OPTIONAL_INTERNAL_PATHS = {
    "Infrastructure/.template-identity",
    "data/docs/",
    "data/docs/dataset-registry.yaml",
    "records/ai-use-log.md",
}

# Operator-local context (AGENTS.md, Change Control): gitignored,
# never committed, and present only on the machine it describes -- for example
# the local model roster the delegate-to-local-model workflow points to. Docs may cite
# it, but a clean checkout or CI never has it, so its absence is not a defect.
OPTIONAL_INTERNAL_PREFIXES = (
    "Infrastructure/local/",
)

# The worked example's synthetic data and drafts. The template must ship them, so there they
# stay required; a project deletes them when it replaces the example (README, "Run the example
# pipeline"), so once `make template-reset` has removed the identity marker they are optional.
# An entry ending in "/" exempts everything under it. The example's `code/` scripts are not
# listed: a project replaces them in place under the same numbered names.
TEMPLATE_MARKER = "Infrastructure/.template-identity"
EXAMPLE_PATHS = (
    "data/example/",
    "drafts/example_note.md",
    "drafts/example_brief.qmd",
)


# A repository `port_template.py` brought the template into keeps its own layout: its code and
# data stay where they always were, so the template's project-lane paths may not exist there.
# The port marker says so with `project_lane: legacy`; a ported project that adopts the
# template's layout says `project_lane: template`, and its lane stays checked.
PORT_MARKER = ".eig-port"
PROJECT_LANE_PREFIXES = ("code/", "data/", "drafts/", "output/")


def legacy_lane(repo_root: Path) -> bool:
    """True when the port marker records that the project keeps its own layout."""
    try:
        text = (repo_root / PORT_MARKER).read_text(encoding="utf-8")
    except OSError:
        return False
    return any(line.strip() == "project_lane: legacy" for line in text.splitlines())


def is_lane_path(name: str) -> bool:
    """True when `name` is, or lies under, one of the template's project-lane directories, or is
    the root README.md, which the template's docs cite and an older project may not have."""
    return name.startswith(PROJECT_LANE_PREFIXES) or name + "/" in PROJECT_LANE_PREFIXES or name == "README.md"


def is_example_path(name: str) -> bool:
    """True when `name` is, or lies under, one of the worked example's paths."""
    return any(name == entry or name == entry.rstrip("/") or
               (entry.endswith("/") and name.startswith(entry))
               for entry in EXAMPLE_PATHS)

# Forward-looking workspace records, excluded from validation entirely.
# `records/plans/` and `records/specs/` exist to describe work that
# has not been done yet, so they legitimately name paths that do not exist: a
# spec that could only cite files already on disk could not specify anything new.
# Validating them made `Infrastructure/rules/plan-first-workflow.md` a process
# that fails its own maintenance suite the moment it is followed.
#
# The exclusion is deliberately narrow. Runtime references -- the ones that break
# an agent mid-session -- live in the canonical and adapter trees, which stay
# fully validated. A stale path inside an approved spec costs a reader one failed
# lookup; a stale path inside a rules file costs every session that reads it.
#
# Two further paths join the exemption for a related reason: their Markdown
# describes code that is not in this repository at all.
#
# `records/war_rooms/*/` holds rendered war-room ledgers and work orders.
# Those cite paths inside the *reviewed* project -- `code/02_build_sample.R`,
# `review-reports/methodology-report.html` -- which may be a different checkout
# entirely, and which change as that project changes. Only the slug
# subdirectories are exempt; `records/war_rooms/README.md` documents this
# repository and stays fully checked.
#
# `Infrastructure/scripts/war_room_fixtures/` holds synthetic fixture projects
# for the war-room test suite. Each carries its own `PROJECT.md` describing a
# project that exists only inside that directory, so its paths resolve relative
# to the fixture rather than to this repository.
#
# `records/review_boards/*/` holds review-board round plans and the
# generated `board.md`. Like war-room ledgers, they cite paths inside the
# reviewed project (`code/04_figures.R`), which may be another checkout. Only the
# board subdirectories are exempt; `records/review_boards/README.md` stays
# checked. `Infrastructure/scripts/review_board_fixtures/` holds a synthetic
# fixture project whose paths resolve relative to the fixture, not this repo.
#
# The cost calculus is the same as for plans and specs: a stale path in a
# rendered ledger or a fixture costs one reader one failed lookup, while the
# runtime references that break a session live in the canonical and adapter
# trees, which stay fully validated.
#
# Each entry is a repository-relative path. A trailing "/*" exempts the
# directory's subdirectories while leaving files directly inside it checked;
# without it, the directory and everything under it is exempt.
FORWARD_LOOKING_INFRA_PATHS = (
    "records/plans",
    "records/specs",
    "records/war_rooms/*",
    "Infrastructure/scripts/war_room_fixtures",
    "records/review_boards/*",
    "Infrastructure/scripts/review_board_fixtures",
)


# A dated project record: a plan, spec, or session log named `YYYY-MM-DD_...`. The Markdown
# walk validates such a citation against the disk, and CI repeats that walk after a reset,
# but a script docstring or a config comment is never walked, so the second pass fails on
# any citation of one there, present or not: `make template-reset` always deletes it. Cite
# the owning `Infrastructure/` doc or `CHANGELOG.md` instead.
DATED_RECORD_RE = re.compile(
    r"records/(?:plans|specs|session_logs)/\d{4}-\d{2}-\d{2}[^\s`'\"()\[\],;]*"
)
NON_MARKDOWN_ROOTS = ("Infrastructure", *ADAPTER_DIRS, "Makefile", ".github")
# Personal files the adapter trees may hold beside the generated ones (a user's own
# permission rules can name any path); they never ship.
PERSONAL_FILE_MARKER = ".local."


# Sources that `brain.py sync` copies elsewhere are written for where they are rendered: the
# adapter READMEs link `../AGENTS.md` from `.claude/` and `.codex/`. Their `./` and `../`
# references resolve from the rendered location. The two entries repeat the README pairs in
# `brain.py` (`render`), whose rendered copies this checker also walks.
RENDERED_AT = {
    "Infrastructure/adapter_configs/claude.README.md": ".claude/README.md",
    "Infrastructure/adapter_configs/codex.README.md": ".codex/README.md",
}


def is_forward_looking(repo_root: Path, md_file: Path) -> bool:
    """Return True when this Markdown file sits under an exempt path.

    A pattern ending in "/*" exempts only the subdirectories of the named
    directory: a file directly inside it (such as
    `records/war_rooms/README.md`) is still validated.
    """

    try:
        relative = md_file.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False

    parts = relative.parts
    for pattern in FORWARD_LOOKING_INFRA_PATHS:
        subdirs_only = pattern.endswith("/*")
        base = pattern[:-2] if subdirs_only else pattern
        base_parts = Path(base).parts
        if parts[: len(base_parts)] != base_parts:
            continue
        remainder = parts[len(base_parts) :]
        if subdirs_only:
            # Needs at least one intermediate directory plus the file itself.
            if len(remainder) >= 2:
                return True
            continue
        if remainder:
            return True
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check internal markdown path references.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root path. Defaults to script-derived root.",
    )
    return parser.parse_args()


def is_nested_worktree(repo_root: Path, path: Path) -> bool:
    """True when `path` lies inside an agent worktree nested under `.claude/`."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return False
    return rel.parts[: len(NESTED_WORKTREE_PARTS)] == NESTED_WORKTREE_PARTS


def iter_markdown_files(repo_root: Path) -> Iterable[Path]:
    """Yield every Markdown file in scope for reference validation.

    Order: top-level files, then Infrastructure/ and records/ recursively, then
    each adapter tree recursively. Skips dotfiles other than the adapter dirs
    themselves, anything under .git/, and agent worktrees nested under the
    Claude adapter directory (see NESTED_WORKTREE_PARTS).
    """

    seen: set[Path] = set()

    def maybe_yield(path: Path) -> Iterable[Path]:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        yield path

    for name in ROOT_MARKDOWN_FILES:
        path = repo_root / name
        if path.exists():
            yield from maybe_yield(path)

    for walked in WALKED_DIRS:
        walked_root = repo_root / walked
        if not walked_root.exists():
            continue
        for md in sorted(walked_root.rglob("*.md")):
            if is_forward_looking(repo_root, md):
                continue
            yield from maybe_yield(md)

    for adapter in ADAPTER_DIRS:
        adapter_root = repo_root / adapter
        if not adapter_root.exists():
            continue
        for md in sorted(adapter_root.rglob("*.md")):
            if is_nested_worktree(repo_root, md):
                continue
            yield from maybe_yield(md)


def git_listed_files(repo_root: Path, roots: Iterable[str]) -> List[Path] | None:
    """Files under `roots` that git tracks or would track (not ignored), or None.

    None when git is unavailable or `repo_root` is not the top of its own work tree (a
    bare copy, or a directory inside another repository), so the caller walks the disk.
    """
    try:
        top = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=30)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != repo_root.resolve():
            return None
        listed = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard", "--", *roots],
            capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if listed.returncode != 0:
        return None
    names = sorted({name for name in listed.stdout.decode("utf-8", "replace").split("\0") if name})
    return [repo_root / name for name in names]


def iter_non_markdown_files(repo_root: Path) -> Iterable[Path]:
    """Yield every non-Markdown file under NON_MARKDOWN_ROOTS.

    Reads what git tracks or would track, so gitignored files (`.Rhistory`, local caches)
    are never read; without git, walks the disk. Skips the exempt paths of the Markdown
    walk (fixtures), agent worktrees, operator-local notes, personal `*.local.*` files,
    and bytecode caches.
    """
    listed = git_listed_files(repo_root, NON_MARKDOWN_ROOTS)
    if listed is None:
        listed = []
        for top in NON_MARKDOWN_ROOTS:
            base = repo_root / top
            listed.extend(sorted(base.rglob("*")) if base.is_dir() else [base])
    for path in listed:
        if not path.is_file() or path.suffix.lower() == ".md":
            continue
        rel = path.relative_to(repo_root).as_posix()
        if (
            is_nested_worktree(repo_root, path)
            or is_forward_looking(repo_root, path)
            or rel.startswith(OPTIONAL_INTERNAL_PREFIXES)
            or PERSONAL_FILE_MARKER in path.name
            or "__pycache__" in path.parts
        ):
            continue
        yield path


def dated_record_citations(repo_root: Path) -> tuple[List[str], int]:
    """Return (`file:line -> citation` for each dated record cited, files read)."""
    found: List[str] = []
    count = 0
    for path in iter_non_markdown_files(repo_root):
        count += 1
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"records/" not in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), start=1):
            for match in DATED_RECORD_RE.finditer(line):
                found.append(f"{path.relative_to(repo_root).as_posix()}:{idx} -> {match.group(0)}")
    return found, count


def normalize_candidate(raw: str) -> str:
    candidate = raw.strip().strip("<>").strip("\"'").rstrip(".,;:")
    if "#" in candidate:
        candidate = candidate.split("#", 1)[0]
    if "?" in candidate:
        candidate = candidate.split("?", 1)[0]
    candidate = LINE_SUFFIX_RE.sub("", candidate)
    return candidate


def should_check(candidate: str) -> bool:
    if not candidate:
        return False
    if " " in candidate:
        return False
    if any(ch in candidate for ch in ("*", "{", "}", "$", "|")):
        return False
    if any(token in candidate for token in ("YYYY-", "[", "]", "<", ">", "TBD")):
        return False
    if candidate.startswith(("http://", "https://", "mailto:", "tel:", "data:")):
        return False
    return candidate.startswith(ALLOWED_INTERNAL_PREFIXES) or is_relative(candidate)


def is_relative(candidate: str) -> bool:
    """`./x` and `../x` name a path relative to the referencing file."""
    return candidate.startswith(("./", "../"))


def resolve_candidate(repo_root: Path, source_file: Path, candidate: str) -> Path | None:
    """The path a reference names, or None for a relative one that leaves the repository
    (a fixture or an example pointing at another checkout), which is not this repo's to check."""
    if is_relative(candidate):
        try:
            rel_source = source_file.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel_source = ""
        base = repo_root / RENDERED_AT[rel_source] if rel_source in RENDERED_AT else source_file
        resolved = (base.parent / candidate).resolve()
        try:
            resolved.relative_to(repo_root.resolve())
        except ValueError:
            return None
        return resolved
    return (repo_root / candidate).resolve()


def collect_candidates(line: str) -> List[str]:
    candidates: List[str] = []
    candidates.extend(MD_LINK_RE.findall(line))
    candidates.extend(CODE_SPAN_RE.findall(line))
    return candidates


def main() -> int:
    args = parse_args()
    script_root = Path(__file__).resolve().parents[2]
    repo_root = Path(args.repo_root).resolve() if args.repo_root else script_root

    if not repo_root.exists():
        print(f"ERROR: repo root does not exist: {repo_root}", file=sys.stderr)
        return 1

    missing: List[str] = []
    checked_count = 0
    file_count = 0
    optional_absent_count = 0
    # Outside the template the worked example may be gone (EXAMPLE_PATHS).
    example_optional = not (repo_root / TEMPLATE_MARKER).is_file()
    lane_optional = legacy_lane(repo_root)

    for md_file in iter_markdown_files(repo_root):
        file_count += 1
        try:
            lines = md_file.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            lines = md_file.read_text(encoding="latin-1").splitlines()

        for idx, line in enumerate(lines, start=1):
            for raw in collect_candidates(line):
                candidate = normalize_candidate(raw)
                if not should_check(candidate):
                    continue

                resolved = resolve_candidate(repo_root, md_file, candidate)
                if resolved is None:
                    continue
                checked_count += 1
                if not resolved.exists():
                    # Judged by where it resolves, so `../local/x.md` is as optional as
                    # `Infrastructure/local/x.md`.
                    try:
                        landed = resolved.relative_to(repo_root).as_posix()
                    except ValueError:
                        landed = candidate
                    if any(name in OPTIONAL_INTERNAL_PATHS
                           or name.startswith(OPTIONAL_INTERNAL_PREFIXES)
                           or (example_optional and is_example_path(name))
                           or (lane_optional and is_lane_path(name))
                           for name in (candidate, landed, landed + "/")):
                        optional_absent_count += 1
                        continue
                    relative_md = md_file.relative_to(repo_root)
                    missing.append(f"{relative_md}:{idx} -> {candidate}")

    dated, non_markdown_count = dated_record_citations(repo_root)
    if dated:
        print(
            f"Dated record citation check failed: {len(dated)} citation(s) of a plan, spec, "
            "or session log that `make template-reset` deletes, in non-Markdown files. Cite "
            "the owning Infrastructure/ doc or CHANGELOG.md instead.",
            file=sys.stderr,
        )
        for item in dated:
            print(f"- {item}", file=sys.stderr)

    if missing:
        print(
            f"Internal path reference check failed: {len(missing)} missing reference(s) "
            f"across {checked_count} checked reference(s) in {file_count} file(s).",
            file=sys.stderr,
        )
        for item in missing:
            print(f"- {item}", file=sys.stderr)
    if missing or dated:
        return 1

    optional_note = ""
    if optional_absent_count:
        optional_note = (
            f"; {optional_absent_count} reference(s) point to intentionally absent "
            "optional paths (the source-template marker, operator-local notes, a "
            "project dataset overlay, the removed worked example, or a ported project's own layout)"
        )
    print(
        f"Internal path reference check passed: {checked_count} reference(s) "
        f"validated across {file_count} file(s){optional_note}; no dated record cited in "
        f"{non_markdown_count} non-Markdown file(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
