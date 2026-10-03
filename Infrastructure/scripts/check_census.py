#!/usr/bin/env python3
"""Check that TEMPLATE_CENSUS.md inventories every part it claims to, and nothing that is gone.

    check_census.py [--root DIR]

The census stays hand-written prose; this script keeps its inventory tables complete. In any
Markdown table in `Infrastructure/TEMPLATE_CENSUS.md` whose header cell is one of the KINDS
below, every backticked token in that column names one part of that kind; tables inside code
fences or HTML comments do not count. The check fails when a part on disk has no such mention,
and when a mention names a part that does not exist.

What counts as a part, per kind:

- Agent: `Infrastructure/agents/<name>.md`.
- Skill: `Infrastructure/skills/<name>/SKILL.md` and `Infrastructure/style/skills/<name>.md`.
  A directory under `Infrastructure/skills/` without a `SKILL.md` fails outright.
- Rule: `Infrastructure/rules/<name>.md`.
- Template: each entry in `Infrastructure/templates/`; a subdirectory is one part, written
  with a trailing `/`.
- Script: each entry directly in `Infrastructure/scripts/`, and each file in its `hooks/`;
  any other directory (`localapp/`, an app, fixtures) is one part, written with a trailing `/`.
- Check: each name in `CHECKS`, read by importing `Infrastructure/scripts/run_maintenance_checks.py`
  from the checked tree (so `--root` executes that tree's registry module).
- Target: each explicit rule target in the root `Makefile` (every name on a multi-target
  line), written bare or as `make <target>`. Special targets such as `.PHONY`, pattern rules,
  and variable assignments are not targets.

A token may be the bare name or the path under its home directory. Out of scope: the files
inside a grouped directory, the style scripts, the evaluation fixture, and the generated
adapter trees (`.brain-manifest`, checked by `brain.py check`). Rule load tiers are in the
census loading map, which `brain.py check --only load` compares with the rule frontmatter.

Exit codes: 0 complete, 1 incomplete or unreadable.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS = "Infrastructure/TEMPLATE_CENSUS.md"
KINDS = ("Agent", "Skill", "Rule", "Template", "Script", "Check", "Target")
PREFIXES = ("Infrastructure/agents/", "Infrastructure/skills/", "Infrastructure/style/skills/",
            "Infrastructure/rules/", "Infrastructure/templates/", "Infrastructure/scripts/")
DIRECTIVES = {"ifeq", "ifneq", "ifdef", "ifndef", "else", "endif", "include", "-include", "sinclude",
              "define", "endef", "export", "unexport", "override", "vpath"}
FENCE_RE = re.compile(r"^\s*(```|~~~)")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def visible(directory: Path) -> list[Path]:
    """Entries of a directory, without dotfiles and bytecode caches."""
    return sorted(p for p in directory.iterdir() if not p.name.startswith(".") and p.name != "__pycache__")


def make_targets(makefile: str) -> set[str]:
    """Explicit rule targets: every name before a rule's colon, outside recipes and define blocks."""
    targets: set[str] = set()
    in_define = False
    for line in makefile.splitlines():
        words = line.split()
        if in_define or (words and words[0] == "define"):
            in_define = not (words and words[0] == "endef")
            continue
        if not line or line[0] in "\t #" or words[0] in DIRECTIVES or ":" not in line:
            continue
        head, rest = line.split(":", 1)
        if "=" in head or rest.startswith(("=", ":=")):  # a variable assignment, not a rule
            continue
        targets |= {name for name in head.split() if not name.startswith(".") and not set("%$") & set(name)}
    return targets


def on_disk(root: Path) -> tuple[dict[str, set[str]], list[str]]:
    """(every part of each kind, as the bare name a census token normalizes to; broken parts)."""
    infra = root / "Infrastructure"
    broken = [f"skill directory `{p.name}/` has no SKILL.md" for p in visible(infra / "skills")
              if p.is_dir() and not (p / "SKILL.md").is_file()]
    scripts: set[str] = set()
    for entry in visible(infra / "scripts"):
        if entry.name == "hooks":
            scripts |= {f"hooks/{hook.name}" for hook in visible(entry) if hook.is_file()}
        else:
            scripts.add(entry.name + "/" if entry.is_dir() else entry.name)
    spec = importlib.util.spec_from_file_location("census_registry", infra / "scripts/run_maintenance_checks.py")
    registry = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = registry  # dataclasses look their module up while it loads
    try:
        spec.loader.exec_module(registry)
    finally:
        del sys.modules[spec.name]
    return {
        "Agent": {p.stem for p in visible(infra / "agents") if p.suffix == ".md"},
        "Skill": {p.name for p in visible(infra / "skills") if (p / "SKILL.md").is_file()}
        | {p.stem for p in visible(infra / "style/skills") if p.suffix == ".md"},
        "Rule": {p.stem for p in visible(infra / "rules") if p.suffix == ".md"},
        "Template": {p.name + "/" if p.is_dir() else p.name for p in visible(infra / "templates")},
        "Script": scripts,
        "Check": {check.name for check in registry.CHECKS},
        "Target": make_targets((root / "Makefile").read_text(encoding="utf-8")),
    }, broken


def normalize(kind: str, token: str) -> str:
    token = token.strip()
    if kind == "Target":
        return token.removeprefix("make ").strip()
    for prefix in PREFIXES:
        token = token.removeprefix(prefix)
    if kind in ("Agent", "Skill", "Rule"):
        token = token.removesuffix("/SKILL.md").removesuffix("/").removesuffix(".md")
    return token


def cells(line: str) -> list[str]:
    """Split a table row on the pipes outside code spans."""
    out, cell, in_code = [], "", False
    for char in line.strip().strip("|"):
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code:
            out.append(cell)
            cell = ""
        else:
            cell += char
    return [c.strip() for c in out + [cell]]


def in_census(text: str) -> dict[str, dict[str, int]]:
    """{kind: {normalized token: first line number}} from the columns headed by a kind."""
    named: dict[str, dict[str, int]] = {kind: {} for kind in KINDS}
    text = COMMENT_RE.sub(lambda match: "\n" * match.group().count("\n"), text)  # keeps line numbers
    lines = text.splitlines()
    columns: dict[int, str] = {}
    in_fence = False
    for number, line in enumerate(lines, 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        if in_fence or not line.lstrip().startswith("|"):
            columns = {}
            continue
        row = cells(line)
        following = lines[number] if number < len(lines) else ""
        if not columns and re.fullmatch(r"\|?[\s:|-]+\|?", following.strip()):
            columns = {i: cell for i, cell in enumerate(row) if cell in KINDS}
            continue
        for i, kind in columns.items():
            for token in re.findall(r"`([^`]+)`", row[i] if i < len(row) else ""):
                named[kind].setdefault(normalize(kind, token), number)
    return named


def problems(root: Path) -> list[str]:
    census = root / CENSUS
    named = in_census(census.read_text(encoding="utf-8"))
    found, out = on_disk(root)
    for kind in KINDS:
        out += [f"{kind.lower()} `{name}` exists but is not in a `{kind}` column of {CENSUS}"
                for name in sorted(found[kind] - named[kind].keys())]
        out += [f"{CENSUS}:{line}: {kind.lower()} `{name}` does not exist"
                for name, line in sorted(named[kind].items()) if name not in found[kind]]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    args = parser.parse_args(argv)
    try:
        found = problems(args.root)
    except (OSError, AttributeError, SyntaxError) as exc:
        print(f"check_census: cannot read the census or its sources: {exc}")
        return 1
    for problem in found:
        print(f"FAIL {problem}")
    if found:
        print(f"{len(found)} census problem(s); update {CENSUS} (or the part) and rerun.")
        return 1
    print(f"{CENSUS} names every agent, skill, rule, template, script, check, and make target.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
