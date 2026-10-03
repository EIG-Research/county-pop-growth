#!/usr/bin/env python3
"""Shared library for the code war room: hashing, segmentation, resolution, ledger IO.

Every war-room script (`war_room_prep.py`, `war_room_server.py`,
`war_room_lint.py`, `war_room_render.py`, `war_room_reconcile.py`) calls into this
module rather than reimplementing any of it, because the guarantees the rules file
makes -- reproducible hashes, deterministic block boundaries, honest drift -- hold
only if there is exactly one implementation of each.

Dependencies: Python 3.11+ and PyYAML. Nothing else.


Segmentation algorithm
======================

`segment(lines, dialect)` returns the block line ranges for a script. It is a pure
function of the file's text and its dialect: the same bytes always produce the same
ranges, on any platform, for any agent. A human can predict every boundary by running
these steps by hand. `Infrastructure/rules/code-war-room-segmentation.md` states the same
steps word for word (WR-S2, and AC-A7 of the hardening plan), and `test_war_room.py` fails
on any divergence between the two.

1. Read the file as UTF-8 and split it into lines, discarding the line terminators (both
   CRLF and LF), exactly as WR-A1 step 2 does. Lines are numbered from 1.

2. Detect the dialect from the file extension: `.R` -> R, `.Rmd` -> Rmd, `.qmd` -> qmd,
   `.py` -> Python, `.do` and `.ado` -> Stata. The ledger's `script.language` records `R`
   for all three R dialects, and `Python` or `Stata` for the others.

3. Classify every line as BLANK, COMMENT, FENCE, or CODE. Read the file top to bottom,
   carrying an open string literal from one line to the next: in R, Rmd and qmd a string
   opened by `"`, `'` or a backtick stays open until the same unescaped character closes
   it, even on a later line; in Python only a triple-quoted string (`\"\"\"` or `'''`) stays
   open past the end of its line; in Stata no string does, but a `/* */` block comment
   stays open until its first `*/`, and a `*` or `//` comment line opens none.
   - BLANK: the line contains only whitespace.
   - FENCE: Rmd and qmd only -- the first non-whitespace characters are three backticks.
     A fence toggles chunk state; the first one encountered opens a chunk, the next
     closes it. A fence also closes any open string.
   - COMMENT: R, Rmd, qmd and Python -- the first non-whitespace character is `#`.
     Stata -- the first non-whitespace characters are `*` or `//`, or nothing but
     whitespace is left once `/* */` comment text and a trailing `//` comment are
     removed. In Rmd and qmd, only lines inside a chunk can be comments; outside a chunk
     every non-blank, non-fence line is Markdown prose, counts as CODE, and carries no
     bracket, string, or continuation.
   - CODE: everything else, including a line that begins inside an open string.

4. PARAGRAPHS (WR-S7). Cut the file into paragraphs at every run of blank lines, except
   a run inside an OPEN CONSTRUCT, which stays inside its paragraph. The run is inside an
   open construct when, after the last non-blank line above it:
   a. the bracket depth of step 7 is greater than zero, or a string is open;
   b. Python -- the first non-blank line below the run is indented, because an indented
      line continues the compound statement above it;
   c. Stata -- a `/* */` comment is open; or a `preserve` has not been closed by a
      `restore` (one whose options include `preserve` keeps it open) or by a program's
      `end`; or a `#delimit ;` has not been followed by `#delimit cr`. The prefixes
      `capture`, `quietly` and `noisily` (`cap`, `qui`, `noi`) are skipped, and
      `#delimit` may be abbreviated down to `#d`.
   Blank lines between paragraphs belong to no block, every block lies inside one
   paragraph, and the bracket depth restarts at zero at the start of every paragraph and
   at every fence.

5. FILE HEADER, the WR-S6 exception. If the first paragraph starts at line 1 and every one
   of its non-blank lines is a COMMENT, that paragraph is a block on its own: a header
   documents the whole script, not the code under it. Any other paragraph made only of
   comments -- a trailing note with no code below it, for example -- is also a block of
   its own, because there is nothing for it to attach to.

6. Inside a paragraph, a CUT POINT opens a new block immediately before a non-blank line
   i, never before the paragraph's first line, when step 7 permits a cut there and line i
   opens a new unit. Here and in step 7, line i-1 is the nearest non-blank line above
   line i. Line i opens a new unit when one of the following holds, tested in this order:
   a. SECTION HEADER -- line i is a COMMENT whose text, after the comment token is
      removed, contains three or more consecutive `-` or `=` characters; or it is a Python
      cell marker (`#`, then optional spaces, then `%%`); or it is an opening FENCE in Rmd
      or qmd.
   b. DEFINITION START -- R, Rmd, qmd: `name <- function(` or `name = function(`, or a
      bare `function(`. Python: the first non-whitespace text is `def`, `class`, or `@`.
      A Python `def` or `class` whose immediately preceding line in the same paragraph is
      a decorator line (first non-whitespace character `@`) does not open a unit, so a
      decorator run and the definition it decorates are never split (WR-S3).
      Stata: `program define`, `program drop`, or `program` followed by a name.
   c. DEFINITION END -- the current block's first CODE line was a DEFINITION START and
      that definition closed on line i-1. A definition closed when the bracket depth,
      having risen above zero since the definition opened, returned to zero; or, in Stata,
      when line i-1's first token is `end`; or, in Python, when the definition started at
      indentation zero and line i is itself at indentation zero.
   This ordering is WR-S2's priority list -- section header, definition, complete chain,
   statement run -- with "complete chain" and "statement run" expressed by step 7 instead
   of by a cut of their own: a chain is never cut because step 7 forbids it, and a run of
   plain statements yields no cut at all, so the run is one block.

7. NO CUT is permitted before line i when any of these holds. This is WR-S3: an atomic
   operation is never split.
   - The running bracket depth after line i-1 is not zero. Depth counts `(`, `[` and `{`
     as +1 and `)`, `]` and `}` as -1, ignoring anything inside a string literal or after
     a comment token. Stata's single quote is a macro delimiter, not a string delimiter,
     and is ignored.
   - A string, or a construct of step 4c, is still open after line i-1: a Stata
     `preserve`/`restore` pair, block comment, or `#delimit ;` region is never cut.
   - Line i-1, with any trailing comment removed, ends with a continuation token: `%>%`,
     `|>`, `+`, `,`, a backslash, `&`, `&&`, `|`, `||`, `~`, `=`, `<-`, or Stata's `///`.
   - Line i is inside an Rmd or qmd chunk, or is a chunk's closing fence.

8. ANCHOR (WR-S6). Once the cut points are chosen, every cut opened by rule 6b or 6c is
   moved UP past the maximal run of COMMENT lines immediately preceding it within the same
   paragraph and, in Python, past the maximal run of decorator lines (first non-whitespace
   character `@`) immediately preceding the definition, then past any comment run above
   those, so a leading comment and a decorator run attach to the code below them rather
   than forming a block of their own. A blank line ends each run. A cut opened by rule 6a
   is not moved, because it already sits on the comment that introduces its block. A cut
   is never moved above the paragraph's first line; if it would be, it is dropped. Cuts
   that coincide after anchoring collapse into one.

9. Blocks are emitted in file order and numbered `b001`, `b002`, ... Ids are assigned once
   and are never renumbered, including after a later merge or split. A block's range ends
   on its last non-blank line. Every non-blank line lies in exactly one block, and a blank
   line lies in a block only when it is inside one (WR-S7).
"""

from __future__ import annotations

import copy
import hashlib
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from localapp import filelock, projroot, yamlio  # noqa: E402  (exits without PyYAML)
import yaml  # noqa: E402


# --------------------------------------------------------------------------- vocabularies
SCHEMA_VERSION = 2

DISPOSITIONS = ("confirmed", "misread-by-agent", "needs-change", "unresolved")
DENSITIES = ("high", "medium", "low")
CONFIDENCES = ("high", "medium", "low")
DIVERGENCE_TYPES = (
    "none",
    "wrong-mechanics",
    "wrong-intent",
    "incomplete-intent",
    "undisclosed-assumption",
    "author-uncertain",
)
STATED_BY = ("author", "agent", "existing-report")
REVIEWER_ROLES = ("author", "fresh-eyes")
HISTORY_EVENTS = ("prep", "walkthrough", "reconcile")
SESSION_MODES = ("ordered", "fast-forward")
WRITEBACK_STATUSES = ("pending-confirmation", "written", "declined")

LANGUAGES = ("R", "Python", "Stata")
DIALECTS = ("R", "Rmd", "qmd", "Python", "Stata")

_EXT_DIALECT = {
    ".r": "R",
    ".rmd": "Rmd",
    ".qmd": "qmd",
    ".py": "Python",
    ".do": "Stata",
    ".ado": "Stata",
}
_DIALECT_LANGUAGE = {
    "R": "R",
    "Rmd": "R",
    "qmd": "R",
    "Python": "Python",
    "Stata": "Stata",
}

# Canonical key order, so two ledgers with the same content serialise to the same bytes.
_TOP_ORDER = ("schema_version", "script", "project", "session", "blocks",
              "assumption_export", "open_questions")
_SCRIPT_ORDER = ("path", "language", "sha256", "line_count")
_PROJECT_ORDER = ("id",)
_SESSION_ORDER = ("created", "mode", "prep_completed", "reconciled", "fixture",
                  "history", "reviewers", "segmentation_edits", "source_reports")
_BLOCK_ORDER = ("block_id", "lines", "sha256", "title", "density", "discussed",
                "drift", "drift_after_disposition", "relocated_from",
                "reviewer", "answered_at", "endorsed_prediction", "flag_for_followup",
                "prediction", "author_account", "divergence", "disposition",
                "dissent", "evidence", "registry_writeback")
_PREDICTION_ORDER = ("what_it_does", "inferred_intent", "assumptions", "confidence",
                     "inherited_from", "merged_from")


class WarRoomError(Exception):
    """Any refusal a war-room script must report and exit 1 on."""


# --------------------------------------------------------------------------- time
def utc_now() -> str:
    """UTC ISO 8601 with microseconds, so strict ordering holds inside one test run."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------- hashing
def utc_date() -> str:
    """UTC calendar date, for `session.created`."""
    return datetime.now(timezone.utc).date().isoformat()


def split_lines(text: str) -> list[str]:
    """WR-A1 step 2: split on \r\n and \n, and on no other character.

    `str.splitlines()` also breaks on form feed, vertical tab, the file/group/record
    separators, NEL, LINE SEPARATOR, PARAGRAPH SEPARATOR, and a lone carriage return.
    Any of those inside a string literal or a comment would shift every line number and
    every hash below it, which is exactly the silent divergence WR-A1 exists to prevent.
    """
    normalised = text.replace("\r\n", "\n")
    lines = normalised.split("\n")
    if lines and lines[-1] == "" and normalised.endswith("\n"):
        lines.pop()
    return lines


def wr_a1_lines(path: Path) -> list[str]:
    """WR-A1 steps 1-2: read UTF-8, split into lines, discard line terminators.

    The bytes are read raw and decoded here rather than through `read_text`, whose
    universal-newline mode silently rewrites a lone `\r` to `\n` before `split_lines`
    ever sees it. Every war-room read of a reviewed source goes through this function.
    """
    return split_lines(Path(path).read_bytes().decode("utf-8"))


def wr_a1_hash(lines: Sequence[str], start: int, end: int) -> str:
    """WR-A1 steps 3-5 for a 1-indexed inclusive range. Full 64-character lowercase hex."""
    return hashlib.sha256("\n".join(lines[start - 1:end]).encode("utf-8")).hexdigest()


def wr_a1_file_hash(lines: Sequence[str]) -> str:
    """`script.sha256`: every line of the file, same algorithm."""
    return wr_a1_hash(lines, 1, len(lines))


# --------------------------------------------------------------------------- naming
def slug_for(project_id: str, script_path: str) -> str:
    """D1 ledger-directory slug: project id, `--`, script path with `/` -> `--`."""
    rel = str(script_path).replace("\\", "/").strip("/")
    return f"{project_id}--{rel.replace('/', '--')}"


def locate_ledger(war_rooms_dir: Path, project_id: str, script_path: str) -> Path | None:
    """The ledger a downstream reviewer or a resumed session should open (WR-I5)."""
    candidate = Path(war_rooms_dir) / slug_for(project_id, script_path) / "ledger.yaml"
    return candidate if candidate.is_file() else None


# --------------------------------------------------------------------------- language
def detect_dialect(path: Path | str) -> str:
    """Segmentation dialect: R, Rmd, qmd, Python, or Stata."""
    ext = Path(path).suffix.lower()
    if ext not in _EXT_DIALECT:
        raise WarRoomError(
            f"unsupported script extension {ext!r}; expected one of "
            f"{', '.join(sorted(_EXT_DIALECT))}"
        )
    return _EXT_DIALECT[ext]


def detect_language(path: Path | str) -> str:
    """Ledger `script.language`: one of the closed set R, Python, Stata."""
    return _DIALECT_LANGUAGE[detect_dialect(path)]


# --------------------------------------------------------------------------- segmentation
_R_DEF = re.compile(r"^\s*(?:[\w.$\[\]\"']+\s*(?:<-|=)\s*)?function\s*\(")
_PY_DEF = re.compile(r"^\s*(?:def\s|class\s|@)")
_STATA_DEF = re.compile(r"^\s*program\b")
_HEADER_RULE = re.compile(r"-{3,}|={3,}")
_PY_CELL = re.compile(r"^\s*#\s*%%")
_COMMENT_TOKEN = re.compile(r"^\s*(?:#+|\*+|//)\s*")
_CONTINUATIONS = ("%>%", "|>", "///", "<-", "&&", "||", "+", ",", "\\", "&", "|", "~", "=")
_STATA_PRESERVE = re.compile(
    r"^\s*(?:(?:capture|capt|cap|quietly|quiet|qui|noisily|noi)\s*:?\s+)*"
    r"(preserve|restore)\b(.*)$")
_STATA_DELIMIT = re.compile(r"^\s*#(d[a-z]*)\s*(;|cr)\s*;?\s*$")


def _scan(line: str, dialect: str, state: dict[str, Any]) -> tuple[str, int, bool]:
    """Return (code outside comments, bracket-depth delta, Stata `///`), string-aware.

    `state["quote"]` carries an open string across lines (step 3): an R string, or a
    Python triple-quoted one. Python's one-line strings and Stata's strings end at the
    line end. `state["block"]` carries an open Stata `/* */` comment. The third value exists because Stata's line-continuation token `///`
    begins with the comment token `//`: the comment cut happens here, so a later look at
    the code could never see the continuation that step 7 promises to honour.
    """
    python = dialect == "Python"
    quote_chars = '"' if dialect == "Stata" else ("\"'" if python else "\"'`")
    quote: str | None = state["quote"]
    block: bool = state["block"]
    code: list[str] = []
    depth = 0
    continues = False
    i = 0
    while i < len(line):
        c = line[i]
        if block:
            if line.startswith("*/", i):
                block = False
                i += 2
            else:
                i += 1
            continue
        if quote is not None:
            if c == "\\":
                code.append(line[i:i + 2])
                i += 2
                continue
            if line.startswith(quote, i):
                code.append(quote)
                i += len(quote)
                quote = None
                continue
            code.append(c)
            i += 1
            continue
        if python and line.startswith(('"""', "'''"), i):
            quote = line[i:i + 3]
        elif c in quote_chars:
            quote = c
        elif dialect == "Stata":
            if line.startswith("/*", i):
                block = True
                i += 2
                continue
            if line.startswith("///", i):
                continues = True
                break
            if line.startswith("//", i):
                break
        elif c == "#":
            break
        if quote is not None:
            code.append(quote)
            i += len(quote)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        code.append(c)
        i += 1
    if quote is not None and (dialect == "Stata" or (python and len(quote) == 1)):
        quote = None
    state["quote"] = quote
    state["block"] = block
    return "".join(code), depth, continues


def _stata_regions(code: str, preserve: bool, delimit: bool) -> tuple[bool, bool]:
    """Step 4c: the Stata `preserve` and `#delimit ;` states after a CODE line."""
    m = _STATA_DELIMIT.match(code)
    if m and "delimit".startswith(m.group(1)):
        return preserve, m.group(2) == ";"
    m = _STATA_PRESERVE.match(code)
    if m:
        return m.group(1) == "preserve" or bool(re.search(r"\bpreserve\b", m.group(2))), delimit
    if code.replace(";", " ").split()[:1] == ["end"]:
        return False, delimit
    return preserve, delimit


def _is_section_header(line: str, dialect: str) -> bool:
    if dialect == "Python" and _PY_CELL.match(line):
        return True
    body = _COMMENT_TOKEN.sub("", line, count=1)
    return bool(_HEADER_RULE.search(body))


def _is_def_start(line: str, dialect: str) -> bool:
    if dialect == "Python":
        return bool(_PY_DEF.match(line))
    if dialect == "Stata":
        return bool(_STATA_DEF.match(line))
    return bool(_R_DEF.match(line))


def _is_continuation(code: str, dialect: str) -> bool:
    stripped = code.rstrip()
    return any(stripped.endswith(tok) for tok in _CONTINUATIONS)


def _joins(above: dict[str, Any], below: str, dialect: str) -> bool:
    """Step 4: is the blank run between line `above` and the line `below` inside a construct?"""
    if above["depth"] > 0 or above["held"]:
        return True
    return dialect == "Python" and below[:1] in (" ", "\t")


def _classify(lines: Sequence[str], dialect: str) -> list[dict[str, Any]]:
    """Per-line facts for steps 3 and 4. Index 0 is line 1.

    One pass top to bottom, because a construct stays open across lines: each line records
    the state after it (`depth`, and `held` for a string, a Stata block comment, a
    `preserve`, or a `#delimit ;` region) and whether it starts a paragraph.
    """
    facts: list[dict[str, Any]] = []
    in_chunk = False
    fenced = dialect in ("Rmd", "qmd")
    state: dict[str, Any] = {"quote": None, "block": False}
    preserve = delimit = False
    depth = 0
    last: int | None = None
    for idx, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        inside = in_chunk
        opening_fence = False
        carried = state["quote"] is not None or state["block"]
        code, delta, stata_cont = "", 0, False
        if not stripped:
            kind = "blank"
        elif fenced and stripped.startswith("```"):
            kind = "fence"
            opening_fence = not in_chunk
            in_chunk = not in_chunk
        elif fenced and not in_chunk:
            kind = "code"  # Markdown prose: no depth, string, or continuation
        elif dialect == "Stata" and not carried and stripped.startswith(("*", "//")):
            kind = "comment"
        elif dialect != "Stata" and not carried and stripped.startswith("#"):
            kind = "comment"
        else:
            code, delta, stata_cont = _scan(raw, dialect, state)
            kind = "code" if code.strip() else "comment"  # a Stata `/* */`-only line
            if dialect == "Stata" and kind == "code":
                preserve, delimit = _stata_regions(code, preserve, delimit)
        starts_paragraph = False
        if kind != "blank":
            if last is None or (idx > last + 1 and not _joins(facts[last - 1], raw, dialect)):
                starts_paragraph = True
                depth = 0
            if kind == "fence":
                state = {"quote": None, "block": False}
                depth = 0
            depth += delta
            last = idx
        facts.append({
            "raw": raw,
            "kind": kind,
            "inside_chunk": inside,
            "opening_fence": opening_fence,
            "starts_paragraph": starts_paragraph,
            "depth": depth,
            "held": state["quote"] is not None or state["block"] or preserve or delimit,
            "carried": carried,
            "cont": bool(code) and (stata_cont or _is_continuation(code, dialect)),
            "decorator": (kind == "code" and dialect == "Python" and not carried
                          and raw.lstrip().startswith("@")),
        })
    return facts


def _paragraphs(facts: Sequence[dict[str, Any]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start: int | None = None
    last = 0
    for idx, f in enumerate(facts, start=1):
        if f["kind"] == "blank":
            continue
        if f["starts_paragraph"]:
            if start is not None:
                out.append((start, last))
            start = idx
        last = idx
    if start is not None:
        out.append((start, last))
    return out


def _cuts_for_paragraph(facts: Sequence[dict[str, Any]], pstart: int, pend: int,
                        dialect: str) -> list[int]:
    """Cut points (absolute line numbers) inside one paragraph, anchored per step 8."""
    raw_cuts: list[tuple[int, str]] = []
    seg_is_def = False
    seg_def_indent = 0
    seg_has_code = False
    risen = False
    prev: dict[str, Any] | None = None
    for i in range(pstart, pend + 1):
        f = facts[i - 1]
        if f["kind"] == "blank":
            continue
        if prev is not None and prev["depth"] == 0 and not prev["held"] and not prev["cont"] \
                and not f["inside_chunk"] and not (f["kind"] == "fence" and not f["opening_fence"]):
            reason = None
            if f["opening_fence"]:
                reason = "header"
            elif f["kind"] == "comment" and _is_section_header(f["raw"], dialect):
                reason = "header"
            elif (f["kind"] == "code" and _is_def_start(f["raw"], dialect)
                  and not (dialect == "Python" and not f["decorator"]
                           and prev["decorator"])):
                # Step 6b: a `def`/`class` directly below a decorator run does not open a
                # unit, so the decorators and the definition they carry stay in one block.
                reason = "definition"
            elif seg_is_def and _def_closed(prev, f, risen, dialect, seg_def_indent):
                reason = "definition-end"
            if reason:
                raw_cuts.append((i, reason))
                seg_is_def = False
                seg_def_indent = 0
                seg_has_code = False
                risen = False
        if not seg_has_code and f["kind"] in ("code", "fence"):
            seg_has_code = True
            seg_is_def = f["kind"] == "code" and _is_def_start(f["raw"], dialect)
            # The Python rule in step 6c is keyed to the DEFINITION START's own
            # indentation, not just to line i's, so a nested def never closes on the
            # first zero-indent line below it.
            seg_def_indent = len(f["raw"]) - len(f["raw"].lstrip()) if seg_is_def else 0
        if seg_is_def and f["depth"] > 0:
            risen = True
        prev = f

    anchored: set[int] = set()
    for line_no, reason in raw_cuts:
        target = line_no
        if reason in ("definition", "definition-end"):
            # Step 8: comment run, then (Python) the decorator run above it, then the
            # comment run above those, so `# note` / `@a` / `@b` / `def g` is one block.
            while target - 1 >= pstart and facts[target - 2]["kind"] == "comment":
                target -= 1
            if dialect == "Python":
                moved = False
                while target - 1 >= pstart and facts[target - 2]["decorator"]:
                    target -= 1
                    moved = True
                if moved:
                    while target - 1 >= pstart and facts[target - 2]["kind"] == "comment":
                        target -= 1
        if target > pstart:
            anchored.add(target)
    return sorted(anchored)


def _def_closed(prev: dict[str, Any], f: dict[str, Any], risen: bool, dialect: str,
                def_indent: int) -> bool:
    if risen and prev["depth"] == 0:
        return True
    if dialect == "Stata" and prev["raw"].strip().lower().split(" ")[0] == "end":
        return True
    if (dialect == "Python" and prev["depth"] == 0 and def_indent == 0
            and f["raw"][:1] not in (" ", "\t")):
        return True
    return False


def segment(lines: Sequence[str], dialect: str) -> list[tuple[int, int]]:
    """Deterministic block ranges. See the module docstring for the algorithm."""
    if dialect not in DIALECTS:
        raise WarRoomError(f"unknown dialect {dialect!r}")
    facts = _classify(lines, dialect)
    ranges: list[tuple[int, int]] = []
    for pstart, pend in _paragraphs(facts):
        if all(facts[i - 1]["kind"] in ("comment", "blank") for i in range(pstart, pend + 1)):
            ranges.append((pstart, pend))
            continue
        cuts = _cuts_for_paragraph(facts, pstart, pend, dialect)
        bounds = [pstart, *cuts, pend + 1]
        for a, b in zip(bounds, bounds[1:]):
            end = b - 1
            while facts[end - 1]["kind"] == "blank":  # a block ends on a non-blank line
                end -= 1
            ranges.append((a, end))
    return ranges


def block_id_for(index: int) -> str:
    """`b001`, `b002`, ... from a 0-based position."""
    return f"b{index + 1:03d}"


# --------------------------------------------------------------------------- resolution
def _project_id(ledger: dict) -> str:
    return str((ledger.get("project") or {}).get("id") or "")


def resolve_project_root(explicit: str | Path | None, ledger: dict) -> Path:
    """D2, through the shared kit. The flag wins; otherwise walk up from the CWD to the
    nearest PROJECT.md root. Either way the root's basename must be the ledger's
    `project.id` (D1), so a root that names another project never resolves.

    `project_root` is never read from the ledger, and the working directory is never
    used as a silent fallback.
    """
    try:
        return projroot.resolve_project_root(explicit, _project_id(ledger), record="the ledger")
    except projroot.ProjectRootError as exc:
        raise WarRoomError(str(exc)) from None


def check_project_id(root: Path, ledger: dict) -> None:
    """D1 resume guard: the root's basename must equal the ledger's project.id."""
    try:
        projroot.check_project_id(root, _project_id(ledger), record="the ledger")
    except projroot.ProjectRootError as exc:
        raise WarRoomError(str(exc)) from None


def resolve_script(root: Path, ledger: dict) -> Path:
    """`script.path` under the project root. Nothing else is tried (D2)."""
    rel = ((ledger.get("script") or {}).get("path") or "").strip()
    if not rel:
        raise WarRoomError("ledger has no script.path")
    if Path(rel).is_absolute():
        raise WarRoomError(f"script.path must be project-relative, got {rel!r}")
    path = Path(root) / rel
    if not path.is_file():
        raise WarRoomError(
            f"script.path {rel!r} does not resolve under --project-root {root}"
        )
    return path


# --------------------------------------------------------------------------- ledger IO
def _order_block(block: Any) -> Any:
    """Canonical key order, with the short `[start, end]` pairs rendered inline, as the
    ledger template shows them."""
    if not isinstance(block, dict):
        return block
    out = yamlio.reorder(block, _BLOCK_ORDER)
    if "prediction" in out:
        out["prediction"] = yamlio.reorder(out["prediction"], _PREDICTION_ORDER)
    for key in ("lines", "relocated_from"):
        if isinstance(out.get(key), list) and len(out[key]) == 2:
            out[key] = yamlio.FlowList(out[key])
    return out


def order_ledger(data: dict) -> dict:
    """Canonical key order, so equal content always serialises to equal bytes."""
    out = yamlio.reorder(data, _TOP_ORDER)
    for key, order in (("script", _SCRIPT_ORDER), ("project", _PROJECT_ORDER),
                       ("session", _SESSION_ORDER)):
        if key in out:
            out[key] = yamlio.reorder(out[key], order)
    if isinstance(out.get("blocks"), list):
        out["blocks"] = [_order_block(b) for b in out["blocks"]]
    return out


def load_ledger(path: Path) -> dict:
    """Read `ledger.yaml`. Timestamps come back as strings, never datetimes."""
    return yaml.load(Path(path).read_text(encoding="utf-8"), Loader=yamlio.Loader) or {}


def dump_ledger(data: dict) -> str:
    """The exact text `save_ledger` writes."""
    return yamlio.dump_yaml(order_ledger(data), literal_multiline=False)


def save_ledger(path: Path, data: dict) -> None:
    """Atomic LF write that keeps the file's mode: a half-written ledger would lose the
    session (WR-Q3). Callers that load, mutate, and save hold `locked_ledger` around all
    three."""
    yamlio.atomic_write_text(Path(path), dump_ledger(data))


@contextmanager
def locked_ledger(path: Path, timeout: float = filelock.DEFAULT_TIMEOUT) -> Iterator[None]:
    """Hold the ledger's lock (`ledger.yaml.lock`) around load, mutate, lint, and save.

    The app server and the prep and reconcile CLIs all write one ledger. Without a lock
    across processes each can load the same version, and the second save silently drops
    the first one's change (D-15). A holder that keeps the lock past `timeout` seconds is a
    refusal naming its PID.
    """
    try:
        with filelock.locked(Path(path), timeout):
            yield
    except filelock.LockError as exc:
        raise WarRoomError(str(exc)) from None


def find_block(ledger: dict, block_id: str) -> dict | None:
    for b in ledger.get("blocks") or []:
        if b.get("block_id") == block_id:
            return b
    return None


# --------------------------------------------------------------------------- drift
def recompute_drift(ledger: dict, source_lines: Sequence[str]) -> list[dict[str, Any]]:
    """D11. Re-anchor by hash where the match is unique; otherwise flag drift.

    A block whose recorded range still hashes to `sha256` is unchanged: `drift` is false
    and it owns that range. Every other block is searched for ranges of the same length
    that hash to its `sha256` and overlap no range another block owns. Exactly one such
    range re-anchors it: `lines` moves there, `relocated_from` records the old range,
    `drift` stays false (WR-A2 re-anchoring is not drift), and the block owns the new
    range. Each pass grants every unique match found against the same ownership, and two
    matches that overlap in one pass are contested; passes repeat until nothing is granted,
    so the result does not depend on block order. A block with no free match, with more
    than one, or with a contested one is drift:
    `lines` is left untouched, `drift` becomes true, and when the block already carried a
    disposition `drift_after_disposition` becomes true (the WR-A4 regression signal).
    Choosing between identical ranges would be a silent remap (WR-A3), and duplicated
    lines such as `print(summary(df))` are common in analysis code.

    `drift_after_disposition` is never cleared here; only a human editing the ledger
    clears it. `relocated_from` is cleared only by `war_room_prep.py verify
    --accept-relocations`.
    """
    total = len(source_lines)
    blocks = [b for b in ledger.get("blocks") or []
              if b.get("sha256") and len(b.get("lines") or []) == 2]
    recorded_range = {id(b): (int(b["lines"][0]), int(b["lines"][1])) for b in blocks}
    current_hash: dict[int, str | None] = {}
    owned: set[int] = set()
    pending: dict[int, list[int]] = {}
    for b in blocks:
        start, end = recorded_range[id(b)]
        current = wr_a1_hash(source_lines, start, end) if 1 <= start <= end <= total else None
        current_hash[id(b)] = current
        if current == b["sha256"]:
            owned.update(range(start, end + 1))
        else:
            span = end - start + 1
            pending[id(b)] = [s for s in range(1, total - span + 2)
                              if wr_a1_hash(source_lines, s, s + span - 1) == b["sha256"]]

    def free(b: dict) -> list[int]:
        span = recorded_range[id(b)][1] - recorded_range[id(b)][0] + 1
        return [s for s in pending[id(b)] if owned.isdisjoint(range(s, s + span))]

    # Each pass takes every unique claim against the same `owned`, so block order cannot
    # matter. Claims that overlap each other in one pass are contested: both blocks drift.
    moved_to: dict[int, int] = {}
    contested: set[int] = set()
    while True:
        claims: dict[int, range] = {}
        for b in blocks:
            if id(b) in pending and id(b) not in moved_to and id(b) not in contested:
                options = free(b)
                if len(options) == 1:
                    start, end = recorded_range[id(b)]
                    claims[id(b)] = range(options[0], options[0] + end - start + 1)
        clashing = {k for k in claims for other in claims
                    if other != k and not set(claims[k]).isdisjoint(claims[other])}
        contested |= clashing
        granted = {k: r for k, r in claims.items() if k not in clashing}
        if not granted:
            break
        for k, r in granted.items():
            moved_to[k] = r.start
            owned.update(r)

    report: list[dict[str, Any]] = []
    for b in blocks:
        start, end = recorded_range[id(b)]
        candidates: list[int] = []
        if id(b) not in pending:
            b["drift"] = False
            status = "ok"
        elif id(b) in moved_to:
            found = moved_to[id(b)]
            b["relocated_from"] = [start, end]
            b["lines"] = [found, found + end - start]
            b["drift"] = False
            status = "relocated"
        else:
            candidates = free(b)
            b["drift"] = True
            status = "drift"
            if b.get("disposition"):
                b["drift_after_disposition"] = True
        report.append({
            "block_id": b.get("block_id"),
            "status": status,
            "recorded_lines": [start, end],
            "current_lines": list(b.get("lines") or []),
            "recorded_sha256": b["sha256"],
            "current_sha256": current_hash[id(b)],
            "ambiguous_starts": candidates,
            "contested": id(b) in contested,
            "drift_after_disposition": bool(b.get("drift_after_disposition")),
        })
    return report


# --------------------------------------------------------------------------- re-segmentation
def rehash_block(block: dict, source_lines: Sequence[str]) -> None:
    """Recompute ONE block's hash from its current range under WR-A1.

    Only a block a merge or a split just re-bounded is rehashed. Rehashing the whole
    ledger would rewrite the `sha256` of blocks nobody re-segmented, and a source edit
    recorded as drift on one of them would be silently absorbed into the new hash --
    the next `verify` would then report OK on a block whose source really did change.
    """
    lines_ = block.get("lines") or []
    if len(lines_) == 2:
        block["sha256"] = wr_a1_hash(source_lines, int(lines_[0]), int(lines_[1]))


def _refuse_if_drifted(block: dict) -> None:
    """A drifted block is not re-segmentable: rehashing it would erase the drift.

    The human resolves the drift first (re-read the block, re-run prep, or accept the
    new source), because a merge or split across changed source would silently adopt
    text no one predicted against (WR-A3, WR-S5).
    """
    if block.get("drift"):
        raise WarRoomError(
            f"cannot re-segment {block.get('block_id')}: it carries drift: true; "
            f"resolve the drift first (re-read the block against the current source, "
            f"then clear the flag) -- re-segmenting would rewrite its hash and erase it"
        )


def _refresh_evidence_sources(ledger: dict, block: dict) -> None:
    """Point the block's own `<script.path>:<start>-<end>` source at its current range."""
    rel = ((ledger.get("script") or {}).get("path") or "").strip()
    lines_ = block.get("lines") or []
    if not rel or len(lines_) != 2:
        return
    current = f"{rel}:{int(lines_[0])}-{int(lines_[1])}"
    evidence = block.setdefault("evidence", {"sources": [], "confidence": "", "assumptions": []})
    sources = evidence.setdefault("sources", [])
    pattern = re.compile(rf"^{re.escape(rel)}:\d+-\d+$")
    for i, src in enumerate(sources):
        if pattern.match(str(src)):
            sources[i] = current
            return
    sources.insert(0, current)


def _record_segmentation_edit(ledger: dict, entry: dict) -> None:
    sess = ledger.setdefault("session", {})
    sess.setdefault("segmentation_edits", []).append(entry)


def merge_blocks(ledger: dict, block_id: str, source_lines: Sequence[str],
                 by: str | None = None) -> dict:
    """Merge a block with the one after it (WR-S5). Refuses if either is dispositioned."""
    blocks = ledger.get("blocks") or []
    idx = next((i for i, b in enumerate(blocks) if b.get("block_id") == block_id), None)
    if idx is None:
        raise WarRoomError(f"unknown block_id {block_id!r}")
    if idx + 1 >= len(blocks):
        raise WarRoomError(f"block {block_id} is the last block; nothing to merge into")
    a, nxt = blocks[idx], blocks[idx + 1]
    for b in (a, nxt):
        if b.get("disposition"):
            raise WarRoomError(
                f"cannot re-segment {b.get('block_id')}: it already carries a disposition"
            )
        _refuse_if_drifted(b)
    pa = a.get("prediction") or {}
    pb = nxt.get("prediction") or {}
    a["lines"] = [int(a["lines"][0]), int(nxt["lines"][1])]
    a["title"] = " + ".join(t for t in (a.get("title"), nxt.get("title")) if t)
    order = {"low": 0, "medium": 1, "high": 2}
    a["density"] = max([a.get("density") or "low", nxt.get("density") or "low"],
                       key=lambda d: order.get(d, 0))
    a["prediction"] = {
        "what_it_does": " ".join(x for x in (pa.get("what_it_does"), pb.get("what_it_does")) if x),
        "inferred_intent": " ".join(x for x in (pa.get("inferred_intent"), pb.get("inferred_intent")) if x),
        "assumptions": list(pa.get("assumptions") or []) + list(pb.get("assumptions") or []),
        # WR-S5: the agent committed to the original boundaries, not this one.
        "confidence": _lower_confidence(pa.get("confidence"), pb.get("confidence")),
        "merged_from": [a.get("block_id"), nxt.get("block_id")],
    }
    blocks.pop(idx + 1)
    _refresh_evidence_sources(ledger, a)
    rehash_block(a, source_lines)
    _record_segmentation_edit(ledger, {
        "action": "merge", "block_id": block_id, "at": utc_now(), "by": by,
        "merged_from": a["prediction"]["merged_from"],
    })
    return a


def split_block(ledger: dict, block_id: str, at_line: int,
                source_lines: Sequence[str], by: str | None = None) -> list[dict]:
    """Split a block before `at_line` (WR-S5). Refuses if the block is dispositioned."""
    blocks = ledger.get("blocks") or []
    idx = next((i for i, b in enumerate(blocks) if b.get("block_id") == block_id), None)
    if idx is None:
        raise WarRoomError(f"unknown block_id {block_id!r}")
    b = blocks[idx]
    if b.get("disposition"):
        raise WarRoomError(
            f"cannot re-segment {block_id}: it already carries a disposition"
        )
    _refuse_if_drifted(b)
    start, end = int(b["lines"][0]), int(b["lines"][1])
    if start == end:
        raise WarRoomError(f"block {block_id} is a single line ({start}) and cannot be split")
    if not start < at_line <= end:
        raise WarRoomError(f"--at must be between {start + 1} and {end}, got {at_line}")
    parts = []
    for suffix, rng in (("a", [start, at_line - 1]), ("b", [at_line, end])):
        # Deep copy: a shallow one would leave both halves sharing one `evidence`,
        # `divergence`, and `dissent` object, so an edit to either would alter both.
        part = copy.deepcopy(b)
        part["block_id"] = f"{block_id}{suffix}"
        part["lines"] = rng
        pred = dict(part.get("prediction") or {})
        # WR-S5: an inherited prediction is lower-confidence than the one committed to.
        pred["confidence"] = _demote_confidence(pred.get("confidence"))
        pred["inherited_from"] = block_id
        pred.pop("merged_from", None)
        part["prediction"] = pred
        _refresh_evidence_sources(ledger, part)
        rehash_block(part, source_lines)
        parts.append(part)
    blocks[idx:idx + 1] = parts
    _record_segmentation_edit(ledger, {
        "action": "split", "block_id": block_id, "at_line": at_line, "at": utc_now(),
        "by": by, "produced": [p["block_id"] for p in parts],
    })
    return parts


def _demote_confidence(value: str | None) -> str:
    return {"high": "medium", "medium": "low", "low": "low"}.get(value or "", "low")


def _lower_confidence(a: str | None, b: str | None) -> str:
    """The merged prediction inherits the lower of the two, then one step lower."""
    order = {"high": 2, "medium": 1, "low": 0}
    worst = min((a or "low", b or "low"), key=lambda v: order.get(v, 0))
    return _demote_confidence(worst)


# --------------------------------------------------------------------------- skeleton
def new_skeleton(script_path: Path, project_root: Path, mode: str = "ordered") -> dict:
    """Schema v2 skeleton for one script. `project_root` is used, never stored (D2)."""
    if mode not in SESSION_MODES:
        raise WarRoomError(f"--mode must be one of {', '.join(SESSION_MODES)}")
    script_path = Path(script_path).resolve()
    project_root = Path(project_root).resolve()
    try:
        rel = script_path.relative_to(project_root).as_posix()
    except ValueError:
        raise WarRoomError(
            f"{script_path} is not inside --project-root {project_root}"
        ) from None
    lines = wr_a1_lines(script_path)
    dialect = detect_dialect(script_path)
    ranges = segment(lines, dialect)
    blocks = []
    for i, (start, end) in enumerate(ranges):
        blocks.append({
            "block_id": block_id_for(i),
            "lines": [start, end],
            "sha256": wr_a1_hash(lines, start, end),
            "title": "",
            "density": "",
            "discussed": False,
            "drift": False,
            "drift_after_disposition": False,
            "relocated_from": None,
            "reviewer": None,
            "answered_at": None,
            "endorsed_prediction": False,
            "flag_for_followup": False,
            "prediction": {
                "what_it_does": "",
                "inferred_intent": "",
                "assumptions": [],
                "confidence": "",
            },
            "author_account": None,
            "divergence": {"match": None, "type": None, "detail": None},
            "disposition": None,
            "dissent": [],
            "evidence": {
                "sources": [f"{rel}:{start}-{end}"],
                "confidence": "",
                "assumptions": [],
            },
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "script": {
            "path": rel,
            "language": detect_language(script_path),
            "sha256": wr_a1_file_hash(lines),
            "line_count": len(lines),
        },
        "project": {"id": project_root.name},
        "session": {
            "created": utc_date(),
            "mode": mode,
            "reviewers": [],
            "source_reports": [],
            "history": [],
            "segmentation_edits": [],
        },
        "blocks": blocks,
        "assumption_export": [],
        "open_questions": [],
    }
