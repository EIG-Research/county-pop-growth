#!/usr/bin/env python3
"""Build the review-fleet evaluation fixture: the worked example with planted defects.

    build_fixture.py build <out_dir> [--force]
        Write <out_dir>/wages-a (the worked example with scaffold.patch, decoys/*.patch, and
        defects/*.patch applied, in that order), <out_dir>/wages-b (the unpatched example,
        the control), and <out_dir>/anchors.json (each location, with its line). The copies
        carry neutral names and a neutral PROJECT.md, so a reviewer is not told it is tested.
    build_fixture.py check
        Build into a temporary directory and report; nothing is kept. The review-eval test
        suite runs this, so a patch that no longer applies fails the maintenance check. In a
        project that replaced the worked example it prints "not applicable" and exits 0.
    build_fixture.py diff <before_dir> <after_dir>
        Print a patch, in the format this script applies, that turns one tree into the other.
        Use it to write or refresh a patch after the worked example changes.

The worked example (`code/`, `drafts/`, `data/example/`, and the R theme the figure script
sources) is copied from this repository and never edited here. Patches are applied by content,
not by line number: each hunk's old lines must appear in the file, and the occurrence nearest
the stated line is used, so an unrelated edit above a hunk shifts it harmlessly. A hunk whose
old lines are gone means the example changed under the patch; the build stops and names the
patch, which is the signal to refresh it with `diff`.

The fixture applies only while the worked example is intact: the copied trees exist and each
file in `MARKED` still carries its `EXAMPLE: replace` header. In the template (where
`Infrastructure/.template-identity` exists) it always applies, and a missing example or
header fails the build. In a project, replacing any marked file drops its header, and from
then on `check` reports "not applicable" and exits 0; `not_applicable()` is the one test every
caller uses.

Every patch, scaffold included, starts with `#` comment lines saying what it plants. Each
defect and decoy is keyed in `defects.yaml` by its patch file's stem. The fixture lives under
`Infrastructure/`, which review discovery excludes, so the patches and the key are never
reviewed as project files.

Exit codes: 0 built, checked, or not applicable; 1 a patch is stale, a key entry is
inconsistent, an anchor is missing, or there is no worked example to build; 2 usage error.
"""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import sys
import tempfile
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parents[2]
sys.path.insert(0, str(REPO / "Infrastructure" / "scripts"))

from localapp.yamlio import Loader, yaml  # noqa: E402

KEY = EVAL_DIR / "defects.yaml"
SCAFFOLD = EVAL_DIR / "scaffold.patch"
COPIED = ("code", "drafts", "data/example", "Infrastructure/style/themes/r")
# The example files the patches edit that carry a header marker; a project replacing one drops it.
MARKED = ("code/01_build_dataset.R", "code/02_analysis.R", "code/03_make_figures.R",
          "drafts/example_note.md")
EXAMPLE_MARKER = "EXAMPLE: replace"
MARKER_LINES = 5
TEMPLATE_IDENTITY = "Infrastructure/.template-identity"
SKIPPED_NAMES = {"__pycache__", ".DS_Store", ".Rhistory"}
SKIPPED_SUFFIXES = {".html", ".pyc"}
# Neutral names, so nothing a reviewer reads says which copy carries planted defects.
PATCHED_DIR = "wages-a"
CONTROL_DIR = "wages-b"
PROJECT_MD = """# Project Profile

## Research Project Title
- Wages in a synthetic sample

## Research Question
- How do hourly wages vary by region, sex, and year in the synthetic example sample?

## Working agreements
- Session log cadence: `milestone`.
"""


class FixtureError(Exception):
    """A stale patch, an inconsistent key, a missing anchor, or no worked example to patch."""


# --------------------------------------------------------------------------- applicability
def is_template(root: Path = REPO) -> bool:
    return (root / TEMPLATE_IDENTITY).is_file()


def example_gone(root: Path = REPO) -> str | None:
    """Why the worked example the patches apply to is gone from root; None when it is intact."""
    for rel in COPIED:
        if not (root / rel).is_dir():
            return f"{rel}/ is missing"
    for rel in MARKED:
        path = root / rel
        if not path.is_file():
            return f"{rel} is missing"
        head = path.read_text(encoding="utf-8", errors="replace").splitlines()[:MARKER_LINES]
        if not any(EXAMPLE_MARKER in line for line in head):
            return f"{rel} no longer carries its `{EXAMPLE_MARKER}` header"
    return None


def not_applicable(root: Path = REPO) -> str | None:
    """Why the fixture does not apply here, or None when it does (always, in the template)."""
    if is_template(root):
        return None
    gone = example_gone(root)
    return None if gone is None else f"the project replaced the worked example ({gone})"


# --------------------------------------------------------------------------- patches
def parse_patch(text: str, name: str) -> list[tuple[str | None, str, list[tuple[int, list[str]]]]]:
    """[(old path or None for a new file, new path, [(old start, hunk lines)])]."""
    files: list[tuple[str | None, str, list[tuple[int, list[str]]]]] = []
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            old = line[4:].strip()
            if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
                raise FixtureError(f"{name}: `---` without `+++` at line {i + 1}")
            new = lines[i + 1][4:].strip()
            old_path = None if old == "/dev/null" else old.removeprefix("a/")
            files.append((old_path, new.removeprefix("b/"), []))
            i += 2
            continue
        if line.startswith("@@"):
            if not files:
                raise FixtureError(f"{name}: hunk before any file header")
            old_range, new_range = line.split()[1:3]
            start, _, old_count = old_range.lstrip("-").partition(",")
            new_count = new_range.lstrip("+").partition(",")[2]
            remaining_old = int(old_count) if old_count else 1
            remaining_new = int(new_count) if new_count else 1
            body: list[str] = []
            i += 1
            while remaining_old > 0 or remaining_new > 0:
                if i >= len(lines) or lines[i][:1] not in (" ", "+", "-"):
                    raise FixtureError(f"{name}: hunk at line {start} is shorter than its header")
                kind = lines[i][0]
                remaining_old -= kind in (" ", "-")
                remaining_new -= kind in (" ", "+")
                body.append(lines[i])
                i += 1
            files[-1][2].append((int(start), body))
            continue
        i += 1  # comment and blank lines between files
    if not files:
        raise FixtureError(f"{name}: no file headers found")
    return files


def apply_patch(root: Path, patch: Path) -> None:
    for old_path, new_path, hunks in parse_patch(patch.read_text(encoding="utf-8"), patch.name):
        target = root / new_path
        if old_path is None:
            if target.exists():
                raise FixtureError(f"{patch.name}: creates {new_path}, which already exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(l[1:] for _, body in hunks for l in body if l[0] == "+"),
                              encoding="utf-8", newline="\n")
            continue
        if not target.is_file():
            raise FixtureError(f"{patch.name}: {new_path} does not exist in the example; "
                               "the worked example changed, so refresh the patch")
        current = target.read_text(encoding="utf-8").splitlines(keepends=True)
        for start, body in hunks:
            old = [l[1:] for l in body if l[0] in (" ", "-")]
            new = [l[1:] for l in body if l[0] in (" ", "+")]
            spots = [k for k in range(len(current) - len(old) + 1) if current[k:k + len(old)] == old]
            if not spots:
                raise FixtureError(f"{patch.name}: a hunk near line {start} of {new_path} no longer "
                                   "matches; the worked example changed under this patch, so "
                                   "refresh it with `build_fixture.py diff`"
                                   + ("" if is_template() else
                                      f" (in a project that edited the example, remove the "
                                      f"`{EXAMPLE_MARKER}` header of each file it replaced)"))
            at = min(spots, key=lambda k: abs(k + 1 - start))
            current[at:at + len(old)] = new
        target.write_text("".join(current), encoding="utf-8", newline="\n")


def tree_files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(root.rglob("*")) if p.is_file()
            and not SKIPPED_NAMES.intersection(p.parts) and p.suffix not in SKIPPED_SUFFIXES}


def diff_trees(before: Path, after: Path) -> str:
    old, new = tree_files(before), tree_files(after)
    chunks: list[str] = []
    for rel in sorted(set(old) | set(new)):
        if rel not in new:
            raise FixtureError(f"{rel} was deleted; patches here only add and change files")
        a, b = old.get(rel), new[rel]
        if a == b:
            continue
        if not b.endswith("\n") or (a is not None and not a.endswith("\n")):
            raise FixtureError(f"{rel} must end with a newline")
        chunks.extend(difflib.unified_diff(
            [] if a is None else a.splitlines(keepends=True), b.splitlines(keepends=True),
            "/dev/null" if a is None else f"a/{rel}", f"b/{rel}", n=3))
    return "".join(chunks)


# --------------------------------------------------------------------------- key
def load_key() -> dict:
    key = yaml.load(KEY.read_text(encoding="utf-8"), Loader=Loader)
    problems = []
    for group, folder in (("defects", "defects"), ("decoys", "decoys")):
        entries = key.get(group) or []
        ids = [e["id"] for e in entries]
        patches = sorted(p.stem for p in (EVAL_DIR / folder).glob("*.patch"))
        if sorted(ids) != patches:
            problems.append(f"{group} in defects.yaml ({sorted(ids)}) do not match {folder}/*.patch "
                            f"({patches})")
        for entry in entries:
            for field in ("id", "lens", "family", "severity", "locations"):
                if field not in entry:
                    problems.append(f"{entry.get('id', '?')}: missing `{field}`")
            if group == "defects" and "owner_judgment" not in entry:
                problems.append(f"{entry['id']}: missing `owner_judgment`")
    for entry in key.get("control") or []:
        for field in ("id", "lens", "family", "max_severity", "locations"):
            if field not in entry:
                problems.append(f"{entry.get('id', '?')}: missing `{field}`")
    if problems:
        raise FixtureError("defects.yaml: " + "; ".join(problems))
    return key


def locate(root: Path, entries: list[dict]) -> dict[str, list[dict]]:
    """Each entry's locations with their lines; an anchor must occur exactly once."""
    found: dict[str, list[dict]] = {}
    problems = []
    for entry in entries:
        spots = []
        for loc in entry["locations"]:
            path = root / loc["file"]
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            count = text.count(loc["anchor"])
            if count != 1:
                problems.append(f"{entry['id']}: anchor {loc['anchor']!r} occurs {count} times in "
                                f"{loc['file']} (needs exactly one)")
                continue
            line = text[:text.index(loc["anchor"])].count("\n") + 1
            spots.append({"file": loc["file"], "anchor": loc["anchor"], "line": line})
        found[entry["id"]] = spots
    if problems:
        raise FixtureError("; ".join(problems))
    return found


# --------------------------------------------------------------------------- build
def copy_example(dest: Path) -> None:
    for rel in COPIED:
        source = REPO / rel
        if not source.is_dir():
            raise FixtureError(f"the worked example is incomplete: {rel}/ is missing")
        shutil.copytree(source, dest / rel, ignore=lambda d, names: [
            n for n in names if n in SKIPPED_NAMES or Path(n).suffix in SKIPPED_SUFFIXES])
    for sub in ("output/tables", "output/figures", "data/processed"):
        (dest / sub).mkdir(parents=True, exist_ok=True)
    (dest / "PROJECT.md").write_text(PROJECT_MD, encoding="utf-8", newline="\n")


def patches() -> list[Path]:
    return [SCAFFOLD, *sorted((EVAL_DIR / "decoys").glob("*.patch")),
            *sorted((EVAL_DIR / "defects").glob("*.patch"))]


def build(out: Path, force: bool = False) -> dict:
    gone = example_gone()
    if gone is not None:
        raise FixtureError(f"no worked example to patch: {gone}"
                           + ("; the template must keep it" if is_template() else
                              "; the fixture does not apply to this project"))
    key = load_key()
    if out.exists() and any(out.iterdir()):
        if not force:
            raise FixtureError(f"{out} is not empty; pass --force to replace it")
        shutil.rmtree(out)
    fixture, control = out / PATCHED_DIR, out / CONTROL_DIR
    copy_example(fixture)
    copy_example(control)
    for patch in patches():
        apply_patch(fixture, patch)
    anchors: dict[str, dict] = {"defects": {}, "decoys": {}, "control": {}}
    for group, tree in (("defects", fixture), ("decoys", fixture), ("control", control)):
        entries = key.get(group) or []
        located = locate(tree, entries)
        for entry in entries:
            anchors[group][entry["id"]] = dict(entry, locations=located[entry["id"]])
    (out / "anchors.json").write_text(json.dumps(anchors, indent=2) + "\n", encoding="utf-8", newline="\n")
    return anchors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build the fixture and the control")
    b.add_argument("out")
    b.add_argument("--force", action="store_true", help="replace a non-empty output directory")
    sub.add_parser("check", help="build into a temporary directory and report")
    d = sub.add_parser("diff", help="print the patch between two trees")
    d.add_argument("before")
    d.add_argument("after")
    args = parser.parse_args(argv)
    try:
        if args.command == "diff":
            sys.stdout.write(diff_trees(Path(args.before), Path(args.after)))
            return 0
        if args.command == "check":
            reason = not_applicable()
            if reason is not None:
                print(f"not applicable: {reason}; the fixture is checked in the template")
                return 0
            with tempfile.TemporaryDirectory(prefix="review-eval-fixture-") as tmp:
                anchors = build(Path(tmp) / "out")
        else:
            anchors = build(Path(args.out).expanduser(), args.force)
    except FixtureError as exc:
        print(f"build_fixture.py: {exc}", file=sys.stderr)
        return 1
    lenses: dict[str, int] = {}
    for entry in anchors["defects"].values():
        lenses[entry["lens"]] = lenses.get(entry["lens"], 0) + 1
    print(f"{len(patches())} patches applied; {len(anchors['defects'])} defects "
          f"({', '.join(f'{k} {v}' for k, v in sorted(lenses.items()))}) and "
          f"{len(anchors['decoys'])} decoys located"
          + ("" if args.command == "check" else f"; fixture and control in {args.out}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
