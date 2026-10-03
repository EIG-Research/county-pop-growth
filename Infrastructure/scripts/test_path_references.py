#!/usr/bin/env python3
"""Tests for the internal path checker, `check_internal_path_references.py`.

`python3 Infrastructure/scripts/test_path_references.py` from anywhere. Each case builds a
small repository in a temporary directory, runs the real checker on it with `--repo-root`,
and checks the verdict, so a checker that stops catching a planted broken reference fails
here. One `PASS` line per case:

    1  Root-relative references      `Infrastructure/x.md` that is missing fails; present passes
    2  Relative references           `../x.md` and `./x.md` resolve from the referencing file,
                                     so a broken one fails (the checker once skipped them all)
    3  Outside the repository        a relative reference that leaves the repository is skipped
    4  Rendered sources              an adapter README source resolves `../AGENTS.md` from the
                                     place `brain.py sync` renders it, not from its own folder,
                                     and RENDERED_AT matches brain.py's render pairs
    5  Relative optional paths       `../local/x.md` is optional like `Infrastructure/local/x.md`
    6  Dated records in non-Markdown  a script or config citing a dated plan fails even while
                                     the plan exists, since a reset deletes it; a Markdown
                                     citation of an existing plan and a personal file pass
    7  Dated records, git-listed     in a git work tree a gitignored file is not read, while
                                     the Makefile and `.github/` are (skipped without git)
    8  Worked example optional       missing `data/example/` and example drafts pass in a
       downstream                    project (no template marker) and fail in the template;
                                     another missing `drafts/` file fails in both
    9  Ported legacy layout          with `.eig-port` saying `project_lane: legacy`, missing
                                     `code/`, `data/`, `drafts/`, `output/`, and README paths pass;
                                     with `project_lane: template` they fail, and a missing
                                     `Infrastructure/` path fails either way

No network. Exit codes: 0 pass, 1 fail.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable

SCRIPTS = Path(__file__).resolve().parent
CHECKER = SCRIPTS / "check_internal_path_references.py"


class CaseFailure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CaseFailure(message)


def repo(work: Path, files: dict[str, str]) -> Path:
    root = work / "repo"
    for rel, text in {"AGENTS.md": "# Agents\n", **files}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    return root


def run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHECKER), "--repo-root", str(root)],
                          capture_output=True, text=True, timeout=60)


def case_root_relative(work: Path) -> str:
    root = repo(work, {"Infrastructure/docs/guide.md": "See `Infrastructure/docs/missing.md`.\n"})
    result = run(root)
    check(result.returncode == 1 and "guide.md:1 -> Infrastructure/docs/missing.md" in result.stderr,
          f"a missing root-relative reference fails: {result.stderr}")
    (root / "Infrastructure/docs/missing.md").write_text("here\n", encoding="utf-8", newline="\n")
    check(run(root).returncode == 0, "the same reference passes once the file exists")
    return "missing fails, present passes"


def case_relative(work: Path) -> str:
    root = repo(work, {"Infrastructure/docs/guide.md":
                       "[up](../other.md), [here](./sibling.md), and `../../AGENTS.md`.\n"})
    result = run(root)
    check(result.returncode == 1 and "guide.md:1 -> ../other.md" in result.stderr
          and "guide.md:1 -> ./sibling.md" in result.stderr,
          f"broken ../ and ./ references fail: {result.stderr}")
    check("../../AGENTS.md" not in result.stderr, "a relative reference that resolves passes")
    (root / "Infrastructure/other.md").write_text("x\n", encoding="utf-8", newline="\n")
    (root / "Infrastructure/docs/sibling.md").write_text("x\n", encoding="utf-8", newline="\n")
    check(run(root).returncode == 0, "both pass once their files exist beside the referencing file")
    return "../ and ./ resolved from the referencing file"


def case_outside(work: Path) -> str:
    root = repo(work, {"Infrastructure/guide.md": "[elsewhere](../../outside-the-repo/notes.md)\n"})
    result = run(root)
    check(result.returncode == 0, f"a reference that leaves the repository is not checked: {result.stderr}")
    return "skipped"


def case_rendered_source(work: Path) -> str:
    text = "Read `../AGENTS.md` and [the rules](../Infrastructure/rules/).\n"
    root = repo(work, {"Infrastructure/adapter_configs/claude.README.md": text,
                       ".claude/README.md": text, "Infrastructure/rules/r.md": "x\n"})
    result = run(root)
    check(result.returncode == 0, f"the README source resolves from .claude/: {result.stderr}")
    (root / "Infrastructure/rules/r.md").unlink()
    (root / "Infrastructure/rules").rmdir()
    result = run(root)
    check(result.returncode == 1 and "claude.README.md:1 -> ../Infrastructure/rules/" in result.stderr,
          f"and a broken reference in it still fails: {result.stderr}")
    # RENDERED_AT repeats brain.py's README render pairs; they must agree.
    sys.path.insert(0, str(SCRIPTS))
    import check_internal_path_references as checker
    brain = (SCRIPTS / "brain.py").read_text(encoding="utf-8")
    pairs = {f"Infrastructure/adapter_configs/{src}": dest for dest, src in
             re.findall(r'\("(\.\w+/README\.md)", configs / "(\w+\.README\.md)"\)', brain)}
    check(pairs and pairs == checker.RENDERED_AT, f"RENDERED_AT matches brain.py: {pairs}")
    return "resolved from the rendered location; RENDERED_AT matches brain.py"


def case_relative_optional(work: Path) -> str:
    """A relative link into an optional path is optional too, judged by where it resolves."""
    root = repo(work, {"Infrastructure/docs/guide.md":
                       "[roster](../local/models.md) and [marker](../.template-identity)\n"})
    result = run(root)
    check(result.returncode == 0, f"relative links to optional paths are optional: {result.stderr}")
    return "Infrastructure/local/ and the template marker, reached by ../"


def case_dated_record(work: Path) -> str:
    """Non-Markdown files may not cite a dated record, which `make template-reset` deletes."""
    plan = "records/plans/" + "2026-01-01_plan.md"  # joined so this file cites no record
    root = repo(work, {plan: "# Plan\n", "Infrastructure/guide.md": f"See `{plan}`.\n",
                       ".claude/settings.local.json": f'{{"allow": ["Read({plan})"]}}\n'})
    check(run(root).returncode == 0, "a Markdown citation of an existing plan and a personal file pass")
    for rel, text in (("Infrastructure/scripts/tool.py", f'"""Background: {plan}."""\n'),
                      (".codex/config.toml", f"# ({plan})\n")):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
        result = run(root)
        check(result.returncode == 1 and f"{rel}:1 -> {plan}" in result.stderr,
              f"a dated record cited in {rel} fails: {result.stderr}")
        (root / rel).unlink()
    return "a script docstring and a config comment fail; Markdown and personal files do not"


def case_dated_record_git(work: Path) -> str:
    """In a git work tree the dated-record pass reads what git tracks or would track, so a
    gitignored file is never read; the Makefile and `.github/` are read."""
    if shutil.which("git") is None:
        return "skipped: git is not installed"
    plan = "records/plans/" + "2026-01-01_plan.md"  # joined so this file cites no record
    root = repo(work, {".gitignore": "Infrastructure/.Rhistory\n",
                       "Infrastructure/.Rhistory": f'source("{plan}")\n'})
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True, timeout=60)
    result = run(root)
    check(result.returncode == 0, f"a gitignored file is not read: {result.stderr}")
    for rel in ("Makefile", ".github/workflows/ci.yml"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(f"# {plan}\n", encoding="utf-8", newline="\n")
        result = run(root)
        check(result.returncode == 1 and f"{rel}:1 -> {plan}" in result.stderr,
              f"a dated record cited in {rel} fails: {result.stderr}")
        (root / rel).unlink()
    (root / ".gitignore").write_text("", encoding="utf-8", newline="\n")
    result = run(root)
    check(result.returncode == 1 and f"Infrastructure/.Rhistory:1 -> {plan}" in result.stderr,
          f"the same file fails once git no longer ignores it: {result.stderr}")
    return "ignored file skipped; Makefile, .github/, and an unignored file read"


def case_example_optional(work: Path) -> str:
    """The worked example's paths are optional only outside the template (EXAMPLE_PATHS)."""
    refs = ("`data/example/`, `data/example/wages.csv`, `drafts/example_note.md`, and "
            "[brief](../drafts/example_brief.qmd)\n")
    root = repo(work, {"Infrastructure/guide.md": refs})
    result = run(root)
    check(result.returncode == 0 and "removed worked example" in result.stdout,
          f"downstream, the removed example is optional: {result.stdout}{result.stderr}")
    marker = root / "Infrastructure" / ".template-identity"
    marker.write_text("marker\n", encoding="utf-8", newline="\n")
    result = run(root)
    check(result.returncode == 1 and all(
        f"-> {ref}" in result.stderr for ref in ("data/example/", "data/example/wages.csv",
                                                 "drafts/example_note.md",
                                                 "../drafts/example_brief.qmd")),
          f"in the template, every example path is required: {result.stderr}")
    marker.unlink()
    (root / "Infrastructure/guide.md").write_text(refs + "`drafts/brief.md`\n",
                                                   encoding="utf-8", newline="\n")
    result = run(root)
    check(result.returncode == 1 and "-> drafts/brief.md" in result.stderr
          and "example" not in result.stderr,
          f"downstream, a missing non-example draft still fails: {result.stderr}")
    return "optional downstream, required in the template; other drafts always checked"


def case_legacy_lane(work: Path) -> str:
    """A ported project that keeps its own layout makes the project lane optional (PORT_MARKER)."""
    refs = "`code/run_all.R`, `data/raw/`, `drafts/`, `README.md`, and [figures](../output/figures/)\n"
    root = repo(work, {"Infrastructure/guide.md": refs})
    marker = root / ".eig-port"
    marker.write_text("mode: adopt\nproject_lane: legacy\n", encoding="utf-8", newline="\n")
    result = run(root)
    check(result.returncode == 0 and "own layout" in result.stdout,
          f"a legacy-layout port makes the project lane optional: {result.stdout}{result.stderr}")
    marker.write_text("mode: adopt\nproject_lane: template\n", encoding="utf-8", newline="\n")
    result = run(root)
    check(result.returncode == 1 and "-> code/run_all.R" in result.stderr,
          f"a template-layout port keeps the project lane required: {result.stderr}")
    marker.write_text("project_lane: legacy\n", encoding="utf-8", newline="\n")
    (root / "Infrastructure/guide.md").write_text(refs + "`Infrastructure/rules/gone.md`\n",
                                                   encoding="utf-8", newline="\n")
    result = run(root)
    check(result.returncode == 1 and "-> Infrastructure/rules/gone.md" in result.stderr
          and "code/run_all.R" not in result.stderr,
          f"machinery paths stay required in a legacy-layout port: {result.stderr}")
    return "lane optional under project_lane: legacy only; machinery always checked"


CASES: list[tuple[str, Callable[[Path], str]]] = [
    ("Root-relative references", case_root_relative),
    ("Relative references", case_relative),
    ("Outside the repository", case_outside),
    ("Rendered sources", case_rendered_source),
    ("Relative optional paths", case_relative_optional),
    ("Dated records in non-Markdown", case_dated_record),
    ("Dated records, git-listed", case_dated_record_git),
    ("Worked example optional downstream", case_example_optional),
    ("Ported legacy layout", case_legacy_lane),
]


def main() -> int:
    failures = 0
    tmp = Path(tempfile.mkdtemp(prefix="path-refs-test-"))
    try:
        for number, (title, fn) in enumerate(CASES, 1):
            work = tmp / f"case{number}"
            work.mkdir()
            try:
                note = fn(work)
                print(f"PASS  {number}  {title}  ({note})")
            except CaseFailure as exc:
                failures += 1
                print(f"FAIL  {number}  {title}: {exc}")
            except Exception:  # an unexpected error is a failure with its traceback
                failures += 1
                print(f"FAIL  {number}  {title}: unexpected error")
                traceback.print_exc()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{len(CASES) - failures}/{len(CASES)} cases passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
