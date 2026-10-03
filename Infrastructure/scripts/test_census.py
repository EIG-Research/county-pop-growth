#!/usr/bin/env python3
"""Tests for check_census.py, the TEMPLATE_CENSUS.md completeness check.

`python3 Infrastructure/scripts/test_census.py` from anywhere. One `PASS` line per case. Each
case copies the census and the directories it inventories into a scratch directory, plants one
change, and checks the verdict, so a check that stops catching an omission or a stale entry
fails here. The shipped census is checked too. Exit codes: 0 pass, 1 fail, 2 unusable environment.

Dependencies: Python 3.11+.
"""

from __future__ import annotations

import contextlib
import io
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent
sys.path.insert(0, str(SCRIPTS))

try:
    import check_census  # noqa: E402
except (ImportError, SystemExit) as exc:
    print(f"ENVIRONMENT: {exc}")
    raise SystemExit(2)

COPIED = ("Infrastructure/agents", "Infrastructure/skills", "Infrastructure/style/skills", "Infrastructure/rules",
          "Infrastructure/templates", "Infrastructure/scripts")
CASES: list[Callable[[Path], None]] = []


def case(fn: Callable[[Path], None]) -> Callable[[Path], None]:
    CASES.append(fn)
    return fn


def copy_repo(dest: Path) -> Path:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for part in COPIED:
        shutil.copytree(REPO / part, dest / part, ignore=ignore)
    for part in (check_census.CENSUS, "Makefile"):
        shutil.copy2(REPO / part, dest / part)
    return dest


def verdict(root: Path) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = check_census.main(["--root", str(root)])
    return code, out.getvalue()


def expect_fail(root: Path, *fragments: str) -> None:
    code, output = verdict(root)
    if code != 1 or not all(fragment in output for fragment in fragments):
        raise AssertionError(f"expected a failure naming {fragments}, got exit {code}:\n{output}")


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"{old!r} not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


@case
def shipped_census_is_complete(_: Path) -> None:
    code, output = verdict(REPO)
    if code != 0:
        raise AssertionError(output)


@case
def copy_passes_before_any_change(root: Path) -> None:
    code, output = verdict(root)
    if code != 0:
        raise AssertionError(f"the unchanged copy fails:\n{output}")


@case
def census_row_removed_fails(root: Path) -> None:
    census = root / check_census.CENSUS
    lines = census.read_text(encoding="utf-8").splitlines(keepends=True)
    row = next(i for i, line in enumerate(lines) if line.startswith("| `orchestrator` |"))
    census.write_text("".join(lines[:row] + lines[row + 1:]), encoding="utf-8", newline="\n")
    expect_fail(root, "agent `orchestrator` exists but is not in")


@case
def stale_census_row_fails(root: Path) -> None:
    census = root / check_census.CENSUS
    text = census.read_text(encoding="utf-8")
    header = re.search(r"^\| Script \|.*\n\|[-| ]+\|\n", text, re.MULTILINE)
    if header is None:
        raise AssertionError("no Script table in the census")
    census.write_text(text[:header.end()] + "| `retired_tool.py` | Gone. | |\n" + text[header.end():],
                      encoding="utf-8", newline="\n")
    expect_fail(root, "script `retired_tool.py` does not exist")


@case
def new_parts_missing_from_census_fail(root: Path) -> None:
    infra = root / "Infrastructure"
    (infra / "agents/new-agent.md").write_text("x\n", encoding="utf-8", newline="\n")
    (infra / "skills/new-skill").mkdir()
    (infra / "skills/new-skill/SKILL.md").write_text("x\n", encoding="utf-8", newline="\n")
    (infra / "rules/new-rules.md").write_text("x\n", encoding="utf-8", newline="\n")
    (infra / "templates/new-output.md").write_text("x\n", encoding="utf-8", newline="\n")
    (infra / "scripts/hooks/new_hook.py").write_text("x\n", encoding="utf-8", newline="\n")
    (infra / "scripts/newkit").mkdir()
    edit(infra / "scripts/run_maintenance_checks.py", "CHECKS = (\n",
         'CHECKS = (\n    Check("new-check", "python3 x.py", "x"),\n')
    edit(root / "Makefile", "\nbrain-sync:", "\nnew-target:\n\ttrue\n\nbrain-sync:")
    expect_fail(root, "agent `new-agent`", "skill `new-skill`", "rule `new-rules`", "template `new-output.md`",
                "script `hooks/new_hook.py`", "script `newkit/`", "check `new-check`", "target `new-target`")


@case
def removed_parts_named_in_census_fail(root: Path) -> None:
    infra = root / "Infrastructure"
    (infra / "style/skills/eig-tufte-critique.md").unlink()
    (infra / "scripts/review_eval.py").unlink()
    edit(root / "Makefile", "\nrender:", "\nrendered:")
    expect_fail(root, "skill `eig-tufte-critique` does not exist", "script `review_eval.py` does not exist",
                "target `render` does not exist")


@case
def multi_target_make_rules_count(root: Path) -> None:
    edit(root / "Makefile", "\nbrain-sync:",
         "\nextra-one extra-two: brain-sync\n\ttrue\n\n%.out: %.in\n\ttrue\n\nLATE ::= x\n\nbrain-sync:")
    code, output = verdict(root)
    if code != 1 or "target `extra-one`" not in output or "target `extra-two`" not in output:
        raise AssertionError(f"both targets of a multi-target rule must be required, got exit {code}:\n{output}")
    if "`%" in output or "`LATE`" in output:
        raise AssertionError(f"a pattern rule or variable assignment was read as a target:\n{output}")


@case
def tables_in_code_fences_and_comments_do_not_count(root: Path) -> None:
    census = root / check_census.CENSUS
    lines = census.read_text(encoding="utf-8").splitlines(keepends=True)
    row = next(i for i, line in enumerate(lines) if line.startswith("| `orchestrator` |"))
    decoys = ("\n```\n| Agent |\n|---|\n| `orchestrator` |\n| `ghost-in-fence` |\n```\n\n"
              "<!--\n| Agent |\n|---|\n| `orchestrator` |\n| `ghost-in-comment` |\n-->\n")
    census.write_text("".join(lines[:row] + lines[row + 1:]) + decoys, encoding="utf-8", newline="\n")
    expect_fail(root, "agent `orchestrator` exists but is not in")
    _, output = verdict(root)
    if "ghost-in-fence" in output or "ghost-in-comment" in output:
        raise AssertionError(f"a table in a code fence or comment was read as inventory:\n{output}")


@case
def template_subdirectories_and_bare_skill_directories_fail(root: Path) -> None:
    infra = root / "Infrastructure"
    (infra / "templates/report-parts").mkdir()
    (infra / "templates/report-parts/header.md").write_text("x\n", encoding="utf-8", newline="\n")
    (infra / "skills/half-made").mkdir()
    (infra / "skills/half-made/notes.md").write_text("x\n", encoding="utf-8", newline="\n")
    expect_fail(root, "template `report-parts/` exists but is not in", "skill directory `half-made/` has no SKILL.md")


def main() -> int:
    failures = 0
    for fn in CASES:
        with tempfile.TemporaryDirectory(prefix="census-test-") as scratch:
            try:
                fn(copy_repo(Path(scratch)) if fn is not shipped_census_is_complete else REPO)
            except Exception:  # noqa: BLE001 - report every failing case
                failures += 1
                print(f"FAIL {fn.__name__}")
                traceback.print_exc(limit=3)
                continue
        print(f"PASS {fn.__name__}")
    print(f"{len(CASES)} cases, {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
