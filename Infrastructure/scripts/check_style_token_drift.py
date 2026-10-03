#!/usr/bin/env python3
"""Detect drift between canonical style tokens and the files generated from them.

`Infrastructure/style/scripts/sync_tokens.py` generates tracked files from
`Infrastructure/style/tokens/eig-style-tokens.v1.json` (the language token files, the
Stata scheme, and the token tables doc). Its `OUTPUTS` tuple is the one list of them;
this check imports it, so an output added there is drift-checked with no change here.

Every output carries an "Auto-generated ... Do not edit manually" banner, which is the
invariant `brain-check` enforces for the adapter trees. A hand-edit to a generated file,
or a token JSON change without a re-sync, fails this check.

This check regenerates the outputs into a scratch copy of the style tree and compares
them with the working copy, byte for byte after normalizing line endings (CRLF to LF).
That normalization is what git itself stores for text files, so the check compares
content, not how a particular checkout happened to write the line endings: a Windows
working copy with CRLF and a Linux one with LF give the same answer, and a real edit
(a changed value, a hand-edit, trailing whitespace) is still drift. It never writes to the
real outputs, so it is safe to run in CI and safe to run repeatedly.

It also runs a hex lint, because a color literal outside the tokens drifts the same way a
hand-edited output does. Any `#RGB`, `#RRGGBB`, or `#RRGGBBAA` in the style docs, the
hand-written themes and examples, the style skills, `Infrastructure/agents/eig-*.md`, or
`Infrastructure/rules/style-*.md` fails. `Infrastructure/templates` and the review-board
app's CSS are out of scope by design: their colors style report and app chrome, not
figures, and the app belongs to Phase 3D. Exempt within the scope:
- the generated outputs (their colors come from the tokens);
- SVG files and anything under a `fixtures` directory;
- a line that carries `hex-ok: <reason>`, for a color quoted on purpose;
- a file in `HEX_ALLOWLIST`, each naming the unit that removes it. An entry whose file is
  gone or has no hex left fails too, so the list only shrinks.

Exit codes: 0 = no drift and no stray hex, 1 = drift, stray hex, or a generation failure.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STYLE_ROOT = REPO_ROOT / "Infrastructure" / "style"
SYNC_SCRIPT_REL = Path("scripts") / "sync_tokens.py"
TOKEN_REL = Path("tokens") / "eig-style-tokens.v1.json"


# Where the hex lint looks: (directory relative to the repo root, glob).
HEX_LINT_SCOPE = (
    ("Infrastructure/style/docs", "**/*"),
    ("Infrastructure/style/themes", "**/*"),
    ("Infrastructure/style/examples", "**/*"),
    ("Infrastructure/style/skills", "**/*"),
    ("Infrastructure/agents", "eig-*.md"),
    ("Infrastructure/rules", "style-*.md"),
)
# #RGB, #RRGGBB, and #RRGGBBAA; not an HTML entity (&#123;) or an anchor (#top-10).
HEX_RE = re.compile(r"(?<![&\w])#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![\w-])")
HEX_OK_RE = re.compile(r"hex-ok:\s*\S")
HEX_SKIP_SUFFIXES = (".svg",)
# Files that still restate token hex, each mapped to the unit that removes it. It is empty,
# and test_style.py keeps it empty, so a quoted color takes a `hex-ok: <reason>` marker instead.
HEX_ALLOWLIST: dict[str, str] = {}


def hex_hits(path: Path) -> list[tuple[int, str]]:
    """(line number, line) for each unmarked hex color in a text file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # binary files (fonts, images) hold no hex literals to lint
    return [
        (n, line.strip())
        for n, line in enumerate(text.splitlines(), start=1)
        if HEX_RE.search(line) and not HEX_OK_RE.search(line)
    ]


def hex_lint(repo_root: Path, generated: set[Path]) -> tuple[list[str], int]:
    """Problems found by the hex lint, and the number of files it read."""
    problems = []
    checked = 0
    for rel_dir, pattern in HEX_LINT_SCOPE:
        base = repo_root / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.glob(pattern)):
            rel = path.relative_to(repo_root).as_posix()
            if (
                not path.is_file()
                or path.resolve() in generated
                or path.suffix.lower() in HEX_SKIP_SUFFIXES
                or "fixtures" in path.relative_to(base).parts
                or rel in HEX_ALLOWLIST
            ):
                continue
            checked += 1
            problems.extend(f"{rel}:{n}: {line}" for n, line in hex_hits(path))
    for rel, unit in HEX_ALLOWLIST.items():
        path = repo_root / rel
        if not path.is_file():
            problems.append(f"{rel}: allowlisted for {unit}, but the file is gone; remove the entry")
        elif not hex_hits(path):
            problems.append(f"{rel}: allowlisted for {unit}, but has no hex left; remove the entry")
    return problems, checked


def load_outputs(sync_script: Path) -> tuple[Path, ...]:
    """Generated outputs, relative to the style root, from sync_tokens.OUTPUTS."""
    sys.dont_write_bytecode = True  # no __pycache__ beside sync_tokens.py
    spec = importlib.util.spec_from_file_location("eig_sync_tokens", sync_script)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {sync_script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(Path(path).relative_to(module.ROOT) for path, _ in module.OUTPUTS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print a unified diff for each drifted file.",
    )
    return parser.parse_args()


def normalized(path: Path) -> bytes:
    """File content with CRLF line endings folded to LF, as git stores text files."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def fail(message: str) -> int:
    print(f"Style token drift check FAILED: {message}", file=sys.stderr)
    return 1


def main() -> int:
    args = parse_args()

    sync_script = STYLE_ROOT / SYNC_SCRIPT_REL
    token_file = STYLE_ROOT / TOKEN_REL
    for required in (sync_script, token_file):
        if not required.is_file():
            return fail(f"missing required file: {required.relative_to(REPO_ROOT)}")

    try:
        outputs = load_outputs(sync_script)
    except Exception as exc:  # noqa: BLE001 - any import failure is a check failure
        return fail(f"could not read OUTPUTS from {SYNC_SCRIPT_REL}: {exc}")

    missing = [o for o in outputs if not (STYLE_ROOT / o).is_file()]
    if missing:
        names = ", ".join(str(m) for m in missing)
        return fail(f"generated token file(s) absent: {names} (run sync_tokens.py --write)")

    with tempfile.TemporaryDirectory(prefix="eig-style-tokens-") as tmp:
        # sync_tokens.py resolves its paths from its own location (parents[1]), so a
        # faithful dry run means copying the style tree and running the copy. The copy
        # needs --write: without it sync_tokens.py only compares and writes nothing.
        scratch_style = Path(tmp) / "style"
        shutil.copytree(STYLE_ROOT, scratch_style, symlinks=True)

        proc = subprocess.run(
            [sys.executable, str(scratch_style / SYNC_SCRIPT_REL), "--write"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            return fail(f"sync_tokens.py exited {proc.returncode}\n{detail}")

        drifted = []
        for rel in outputs:
            committed = STYLE_ROOT / rel
            regenerated = scratch_style / rel
            if not regenerated.is_file():
                drifted.append((rel, "not produced by sync_tokens.py"))
                continue
            if normalized(committed) != normalized(regenerated):
                drifted.append((rel, "differs from regenerated output"))
                if args.verbose:
                    import difflib

                    diff = difflib.unified_diff(
                        committed.read_text(encoding="utf-8").splitlines(keepends=True),
                        regenerated.read_text(encoding="utf-8").splitlines(keepends=True),
                        fromfile=f"committed/{rel}",
                        tofile=f"regenerated/{rel}",
                    )
                    sys.stderr.writelines(diff)

    hex_problems, hex_checked = hex_lint(
        REPO_ROOT, {(STYLE_ROOT / rel).resolve() for rel in outputs}
    )

    if drifted:
        print("Style token drift check FAILED.", file=sys.stderr)
        for rel, reason in drifted:
            print(f"  - Infrastructure/style/{rel}: {reason}", file=sys.stderr)
        print(
            "\nFix: run `python3 Infrastructure/style/scripts/sync_tokens.py --write` and commit "
            "the regenerated files. Never hand-edit them -- they carry an "
            '"Auto-generated ... Do not edit manually" banner.',
            file=sys.stderr,
        )

    if hex_problems:
        print("Style hex lint FAILED: color literals outside the tokens.", file=sys.stderr)
        for problem in hex_problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nFix: cite the token ID (see Infrastructure/style/docs/_generated/tokens.md) or "
            "read the color from the generated token file. A color quoted on purpose takes "
            "`hex-ok: <reason>` on its line.",
            file=sys.stderr,
        )

    if drifted or hex_problems:
        return 1

    print(
        f"Style token drift check passed: {len(outputs)} generated file(s) match "
        f"{TOKEN_REL.name}; hex lint read {hex_checked} file(s), "
        f"{len(HEX_ALLOWLIST)} allowlisted."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
