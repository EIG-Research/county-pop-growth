#!/usr/bin/env python3
"""Discover what a review reads, and run the project's pipeline once per input state.

`Infrastructure/rules/review-contract.md` describes the review workflows; this script owns
the facts they depend on, so no workflow restates them:

    discover <target> [--include ROOT]... [--out FILE]
        Print the JSON discovery manifest: the resolved pipeline entry, the code and
        document files under the include roots, the files listed as unsupported (`.docx`),
        and the exclude list that was applied.
    run <target> [--timeout SECONDS] [--force] [--confirm-tier4]
        Resolve the pipeline, run it from the target root under a timeout, and record the
        run in `<target>/review-reports/pipeline-run.json`. A successful record whose input
        hash matches the current inputs is reused instead of rerunning.
    excludes
        Print the exclude list, one entry per line.

Pipeline entry, first match wins: a `pipeline:` line in the target's `PROJECT.md` (for
example `- pipeline: code/run_all.R`), then a run-all script at the top level, then one in
`code/`. Within a location the names in RUNALL_NAMES are tried in order, case-insensitively.

Exclusions apply at any depth: a file is skipped when any directory above it is named in
EXCLUDE_DIRS, or when its path contains one of EXCLUDE_PATHS as consecutive components.

The input hash covers the pipeline script; every code file (HASHED_CODE_SUFFIXES) anywhere in
the target outside the exclude list, `output/`, and `data/processed/`, whatever the include
roots; `PROJECT.md` and `renv.lock`; every file under `data/` other than `data/processed/`,
following directory symlinks (a directory reached twice is walked once); and every file under
`Infrastructure/style/themes/` (HASHED_THEMES), which the code sources for its figures.
Files up to HASH_CONTENT_LIMIT bytes are hashed by content; larger ones by path, size, and
modification time, so a large raw file does not make every review pay for reading it. After
a run the record also keeps a fingerprint of `output/` (run logs excluded); a run is reused
only while both the input hash and that fingerprint still match, so deleted or edited
outputs rerun the pipeline.

Exit codes: 0 success (or a reused run); 1 the pipeline failed or timed out; 2 usage error,
no pipeline found, missing interpreter, or a Tier 4 timeout without `--confirm-tier4`.
Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_VERSION = 1

EXCLUDE_DIRS = (
    ".git", ".claude", ".codex", ".agents", "Infrastructure", "review-reports", "temp",
    "renv", ".venv", "node_modules", "__pycache__", ".Rproj.user", ".quarto",
)
EXCLUDE_PATHS = (("output", "logs"),)

DEFAULT_INCLUDE_ROOTS = ("code", "drafts")

CODE_SUFFIXES = (".py", ".r", ".rmd", ".qmd", ".do", ".ado")
DOCUMENT_SUFFIXES = (".tex", ".md", ".qmd", ".rmd", ".pdf")
DOCUMENT_SKIP_NAMES = ("readme.md", "changelog.md", "license.md")
UNSUPPORTED_SUFFIXES = {
    ".docx": "Word files are not read; export the draft to .md, .tex, or .pdf",
    ".doc": "Word files are not read; export the draft to .md, .tex, or .pdf",
}

# (file name, interpreter kind), in priority order within one location.
RUNALL_NAMES = (
    ("runall.sh", "bash"), ("run_all.sh", "bash"),
    ("runall.do", "stata"), ("run_all.do", "stata"),
    ("runall.R", "r"), ("run_all.R", "r"),
    ("runall.py", "python"), ("run_all.py", "python"),
)
KIND_BY_SUFFIX = {".sh": "bash", ".do": "stata", ".r": "r", ".py": "python"}
STATA_BINARIES = ("stata-mp", "stata-se", "stata")

PIPELINE_LINE_RE = re.compile(r"^\s*(?:[-*]\s*)?`?pipeline`?\s*:\s*`?([^`\s]+)`?", re.IGNORECASE)

DEFAULT_TIMEOUT = 900  # seconds: the Tier 2 ceiling in performance-cost-governance.md
TIERS = ((120, "Tier 1"), (900, "Tier 2"), (3600, "Tier 3"))
HASH_CONTENT_LIMIT = 16 * 1024 * 1024
HASHED_CODE_SUFFIXES = (*CODE_SUFFIXES, ".sh")
HASHED_ROOT_FILES = ("PROJECT.md", "renv.lock")
HASHED_THEMES = Path("Infrastructure") / "style" / "themes"
LOG_TAIL_LINES = 50
RUN_RECORD = Path("review-reports") / "pipeline-run.json"
RUN_LOG = Path("review-reports") / "_scratch" / "pipeline-run.log"


class UsageError(Exception):
    """A problem the caller must fix; exit status 2."""


# --------------------------------------------------------------------------- discovery
def excluded(rel: Path) -> bool:
    parts = rel.parts[:-1]
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    for seq in EXCLUDE_PATHS:
        for i in range(len(parts) - len(seq) + 1):
            if tuple(parts[i:i + len(seq)]) == seq:
                return True
    return False


def walk(target: Path, root: Path, follow: bool = False) -> list[Path]:
    """Every file under `root`, relative to `target`, skipping excluded directories.

    With `follow`, directory symlinks are followed, and a directory already walked (by its
    real path) is not walked again, so a link cycle ends.
    """
    found: list[Path] = []
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow):
        here = Path(dirpath)
        if follow:
            real = os.path.realpath(dirpath)
            if real in seen:
                dirnames[:] = []
                continue
            seen.add(real)
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for name in sorted(filenames):
            rel = (here / name).relative_to(target)
            if not excluded(rel):
                found.append(rel)
    return found


def project_pipeline_line(target: Path) -> str | None:
    project = target / "PROJECT.md"
    if not project.is_file():
        return None
    for line in project.read_text(encoding="utf-8", errors="replace").splitlines():
        match = PIPELINE_LINE_RE.match(line)
        if match:
            return match.group(1)
    return None


def resolve_pipeline(target: Path) -> dict | None:
    declared = project_pipeline_line(target)
    if declared is not None:
        path = (target / declared).resolve()
        if not path.is_file() or target not in path.parents:
            raise UsageError(f"PROJECT.md names the pipeline `{declared}`, which is not a file "
                             f"inside {target}")
        kind = KIND_BY_SUFFIX.get(path.suffix.lower())
        if kind is None:
            raise UsageError(f"PROJECT.md names `{declared}`; a pipeline must be .sh, .do, .R, or .py")
        return {"path": path.relative_to(target).as_posix(), "kind": kind, "source": "PROJECT.md"}
    for location, source in (("", "top level"), ("code", "code/")):
        folder = target / location if location else target
        if not folder.is_dir():
            continue
        names = {entry.name.lower(): entry.name for entry in folder.iterdir() if entry.is_file()}
        for name, kind in RUNALL_NAMES:
            actual = names.get(name.lower())
            if actual:
                rel = Path(location, actual) if location else Path(actual)
                return {"path": rel.as_posix(), "kind": kind, "source": source}
    return None


def discover(target: Path, include: list[str] | None = None) -> dict:
    target = target.resolve()
    if not target.is_dir():
        raise UsageError(f"{target} does not exist or is not a directory")
    roots = list(include) if include else list(DEFAULT_INCLUDE_ROOTS)
    pipeline = resolve_pipeline(target)
    files: set[Path] = set()
    missing: list[str] = []
    for root in roots:
        folder = (target / root).resolve()
        if folder != target and target not in folder.parents:
            raise UsageError(f"include root `{root}` is outside {target}")
        if not folder.is_dir():
            missing.append(root)
            continue
        files.update(walk(target, folder))
    if pipeline:
        files.add(Path(pipeline["path"]))
    code, documents, unsupported = [], [], []
    for rel in sorted(files, key=lambda p: p.as_posix()):
        suffix = rel.suffix.lower()
        if suffix in UNSUPPORTED_SUFFIXES:
            unsupported.append({"path": rel.as_posix(), "reason": UNSUPPORTED_SUFFIXES[suffix]})
            continue
        if suffix in CODE_SUFFIXES:
            code.append(rel.as_posix())
        if suffix in DOCUMENT_SUFFIXES and rel.name.lower() not in DOCUMENT_SKIP_NAMES:
            documents.append(rel.as_posix())
    return {
        "manifest_version": MANIFEST_VERSION,
        "target": str(target),
        "include_roots": roots,
        "missing_include_roots": missing,
        "exclude_dirs": list(EXCLUDE_DIRS),
        "exclude_paths": ["/".join(seq) for seq in EXCLUDE_PATHS],
        "pipeline": pipeline,
        "code_files": code,
        "document_files": documents,
        "unsupported_files": unsupported,
    }


# --------------------------------------------------------------------------- pipeline run
def tier_for(timeout: int) -> str:
    for ceiling, label in TIERS:
        if timeout <= ceiling:
            return label
    return "Tier 4"


def command_for(pipeline: dict) -> list[str]:
    path, kind = pipeline["path"], pipeline["kind"]
    if kind == "stata":
        for binary in STATA_BINARIES:
            if shutil.which(binary):
                return [shutil.which(binary) or binary, "-b", "do", path]
        raise UsageError(f"`{path}` needs Stata, but none of {', '.join(STATA_BINARIES)} is on PATH")
    if kind == "python":
        return [python_interpreter(), path]
    binary = {"bash": "bash", "r": "Rscript"}[kind]
    if not shutil.which(binary):
        raise UsageError(f"`{path}` needs `{binary}`, which is not on PATH")
    return [shutil.which(binary) or binary, path]  # resolved: CreateProcess finds only .exe


def python_interpreter() -> str:
    """The project's Python: python3 or python on PATH, skipping the Windows Store alias stub
    (in WindowsApps, which only prints an install hint), else the interpreter running this."""
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found and "windowsapps" not in found.lower():
            return found
    return sys.executable


def _digest_file(digest, target: Path, rel: Path) -> None:
    path = target / rel
    digest.update(rel.as_posix().encode("utf-8") + b"\0")
    stat = path.stat()
    if stat.st_size <= HASH_CONTENT_LIMIT:
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    else:
        digest.update(f"size={stat.st_size};mtime_ns={stat.st_mtime_ns}".encode("ascii"))


def hashed_inputs(target: Path, manifest: dict) -> list[Path]:
    """The files whose change reruns the pipeline (see the module docstring)."""
    rels = {Path(manifest["pipeline"]["path"])}
    for rel in walk(target, target):
        top = rel.parts[0]
        if top == "output" or rel.parts[:2] == ("data", "processed"):
            continue
        if (rel.suffix.lower() in HASHED_CODE_SUFFIXES or top == "data"
                or rel.as_posix() in HASHED_ROOT_FILES):
            rels.add(rel)
    # Data is often a link to shared storage (`data/raw -> /Volumes/...`), so follow links.
    if (target / "data").is_dir():
        rels.update(rel for rel in walk(target, target / "data", follow=True)
                    if rel.parts[:2] != ("data", "processed"))
    # The style themes the code sources, which sit under the excluded Infrastructure/.
    themes = target / HASHED_THEMES
    if themes.is_dir():
        for dirpath, _dirnames, filenames in os.walk(themes):
            rels.update((Path(dirpath) / name).relative_to(target) for name in filenames)
    return sorted(rels, key=lambda p: p.as_posix())


def input_hash(target: Path, manifest: dict) -> str:
    digest = hashlib.sha256(f"pipeline={manifest['pipeline']['path']}\0".encode("utf-8"))
    for rel in hashed_inputs(target, manifest):
        _digest_file(digest, target, rel)
    return "sha256:" + digest.hexdigest()


def output_fingerprint(target: Path) -> str:
    """Every file under output/ except the run logs; a missing output/ has its own value."""
    folder = target / "output"
    if not folder.is_dir():
        return "missing"
    digest = hashlib.sha256()
    for rel in walk(target, folder):
        _digest_file(digest, target, rel)
    return "sha256:" + digest.hexdigest()


def read_record(target: Path) -> dict | None:
    path = target / RUN_RECORD
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def run_pipeline(target: Path, timeout: int, force: bool, confirm_tier4: bool,
                 include: list[str] | None = None) -> int:
    target = target.resolve()
    manifest = discover(target, include)
    pipeline = manifest["pipeline"]
    if pipeline is None:
        names = ", ".join(name for name, _ in RUNALL_NAMES)
        raise UsageError(f"No pipeline found: PROJECT.md has no `pipeline:` line, and neither "
                         f"{target} nor {target / 'code'} holds one of {names}.")
    tier = tier_for(timeout)
    if tier == "Tier 4" and not confirm_tier4:
        raise UsageError(f"A {timeout}s timeout is Tier 4 (over 60 minutes) and needs human "
                         "confirmation; rerun with --confirm-tier4 once it is given.")
    current = input_hash(target, manifest)
    previous = read_record(target)
    if (not force and previous and previous.get("exit_code") == 0
            and previous.get("input_hash") == current and previous.get("pipeline") == pipeline["path"]
            and previous.get("output_fingerprint") == output_fingerprint(target)):
        print(f"Reusing the pipeline run of {previous.get('finished_utc', 'an earlier run')}: "
              f"inputs are unchanged ({current[:19]}…). Pipeline completed successfully.")
        return 0
    command = command_for(pipeline)
    print(f"Found `{pipeline['path']}` ({pipeline['source']}). Running pipeline "
          f"({tier}, timeout {timeout}s)…", flush=True)
    log_path = target / RUN_LOG
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    timed_out = False
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(command, cwd=target, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # The whole process group on POSIX, so a pipeline's children stop too; Windows
            # has no process groups here (no os.killpg), so it stops the pipeline itself.
            killpg = getattr(os, "killpg", None)
            try:
                if killpg is None:
                    raise ProcessLookupError
                killpg(proc.pid, 9)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            code = proc.wait()
    seconds = round(time.monotonic() - start, 2)
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-LOG_TAIL_LINES:]
    exit_code = 124 if timed_out else code
    record = {
        "pipeline": pipeline["path"],
        "pipeline_source": pipeline["source"],
        "command": command,
        "tier": tier,
        "timeout_seconds": timeout,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "seconds": seconds,
        "finished_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_hash": current,
        "output_fingerprint": output_fingerprint(target),
        "log": RUN_LOG.as_posix(),
        "log_tail": tail,
    }
    (target / RUN_RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    if exit_code == 0:
        print("Pipeline completed successfully.")
        return 0
    reason = f"timed out after {timeout}s" if timed_out else f"exit code {exit_code}"
    print(f"Pipeline failed ({reason}).\n\n```\n" + "\n".join(tail) + "\n```")
    return 1


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    disc = sub.add_parser("discover", help="print the JSON discovery manifest")
    disc.add_argument("target")
    disc.add_argument("--include", action="append", metavar="ROOT",
                      help="include root relative to the target (repeatable; default code, drafts)")
    disc.add_argument("--out", help="also write the manifest to this file")
    run = sub.add_parser("run", help="run the pipeline, or reuse a run whose inputs are unchanged")
    run.add_argument("target")
    run.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds (default 900)")
    run.add_argument("--force", action="store_true", help="rerun even when the inputs are unchanged")
    run.add_argument("--confirm-tier4", action="store_true",
                     help="a human confirmed a run over 60 minutes")
    run.add_argument("--include", action="append", metavar="ROOT", help=argparse.SUPPRESS)
    sub.add_parser("excludes", help="print the exclude list")
    args = parser.parse_args(argv)
    try:
        if args.command == "excludes":
            print("\n".join([*(f"{d}/" for d in EXCLUDE_DIRS),
                             *("/".join(seq) + "/" for seq in EXCLUDE_PATHS)]))
            return 0
        target = Path(os.path.expanduser(args.target))
        if args.command == "discover":
            text = json.dumps(discover(target, args.include), indent=2) + "\n"
            if args.out:
                Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                Path(args.out).write_text(text, encoding="utf-8", newline="\n")
            sys.stdout.write(text)
            return 0
        if args.timeout <= 0:
            raise UsageError("--timeout must be a positive number of seconds")
        return run_pipeline(target, args.timeout, args.force, args.confirm_tier4, args.include)
    except UsageError as exc:
        print(f"review_manifest.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
