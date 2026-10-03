#!/usr/bin/env python3
"""Command-line tool for the review board.

    init          validate board.yaml; create an empty feedback.yaml and ledger.yaml
    round open    record the read cursor, list the round's events, write the plan skeleton
    render        run the render command; hash, snapshot, classify, and measure every item
    record        merge the agent's triage, changes, responses, waivers, and stop gate
    round close   lint at close, record files changed outside the sources, close the round
    status        done or not done, with the reasons; exit 0 only when done
    lint          the lint for any stage
    summary       regenerate board.md and every round plan's generated blocks

Every subcommand takes `--board <board dir>` and `--project-root <dir>`. The project root is
never stored. Without the flag, the nearest `PROJECT.md` above the working directory is used,
and only when its basename matches the board's `project.id` (spec M6).

`record` exists so the agent's writes to `ledger.yaml` go through one validated, atomic path
instead of hand-edited YAML. It never touches `feedback.yaml`: this tool has no code path
that writes the reviewer lane (RB-L2).

The binding rules are in `Infrastructure/rules/review-board-rules.md`, and the file shapes
are in `Infrastructure/templates/review-board-ledger.md`.

Exit codes: 0 success (and, for `status`, done); 1 a refusal, a failed check, or not done;
2 the board could not be read or the invocation is wrong.

Dependencies: Python 3.11+ and PyYAML. Git is optional; without it, the check for files
changed outside the sources reports `available: false`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_board_lib as rb  # noqa: E402
import review_board_lint as rl  # noqa: E402
import review_board_measure as rm  # noqa: E402

PLAN_TEMPLATE = (Path(__file__).resolve().parents[1] / "templates"
                 / "review-board-round-plan.md")
SNAPSHOT_FILE = "file-snapshot.json"
_MARKER_RE = re.compile(
    r"(<!-- generated:([a-z-]+):begin -->)(.*?)(<!-- generated:\2:end -->)", re.S)


@dataclass
class Ctx:
    board_dir: Path
    root: Path
    board: dict
    feedback: dict
    ledger: dict

    @property
    def slug(self) -> str:
        return self.board_dir.name


def load_ctx(args: argparse.Namespace, state: bool = True) -> Ctx:
    board_dir = Path(args.board).expanduser().resolve()
    board = rb.load_board(board_dir)
    rb.check_board_dir(board_dir, board)
    root = rb.resolve_project_root(args.project_root, board)
    feedback = rb.load_feedback(board_dir) if state else {}
    ledger = rb.load_ledger(board_dir) if state else {}
    return Ctx(board_dir, root, board, feedback, ledger)


def report(result: rl.LintResult, header: str | None = None) -> bool:
    for warning in result.warnings:
        print(f"warning: {warning.line()}", file=sys.stderr)
    if result.failures and header:
        print(header)
    for failure in result.failures:
        print(f"  {failure.line()}")
    return result.ok


def _when(ts: Any) -> str:
    """A timestamp shortened for reading: `2026-09-24 14:02Z`."""
    s = str(ts or "")
    return f"{s[:10]} {s[11:16]}Z" if len(s) >= 16 else (s or "—")


def _cell(text: Any) -> str:
    """Verbatim text made safe for one Markdown table cell."""
    s = "" if text is None else str(text)
    s = s.replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
    return s.replace("\r\n", "\n").replace("\n", "<br>") or "—"


# --------------------------------------------------------------------------- file snapshot
def _git(cwd: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=str(cwd), input=stdin, capture_output=True,
                              text=True, encoding="utf-8", timeout=120)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def file_snapshot(root: Path) -> dict:
    """Modified and untracked files with their blob ids, plus HEAD (plan P11).

    Uses `git hash-object` without `-w`, so nothing is written to the repository, and
    `git status`, so ignored files (raw data, rendered output) cost nothing.
    """
    top = _git(root, "rev-parse", "--show-toplevel")
    if top is None or top.returncode != 0:
        return {"available": False, "reason": "the project root is not in a git repository"}
    toplevel = Path(top.stdout.strip()).resolve()
    head = _git(root, "rev-parse", "--verify", "-q", "HEAD")
    status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if status is None or status.returncode != 0:
        return {"available": False, "reason": "git status failed"}
    tokens = status.stdout.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":                  # a rename or copy carries its old path next
            if i < len(tokens) and tokens[i]:
                paths.append(tokens[i])
            i += 1
    existing = [p for p in paths if (toplevel / p).is_file()]
    blobs: dict[str, str | None] = {p: None for p in paths}
    if existing:
        hashed = _git(toplevel, "hash-object", "--stdin-paths", stdin="\n".join(existing))
        if hashed is None or hashed.returncode != 0:
            return {"available": False, "reason": "git hash-object failed"}
        for path, blob in zip(existing, hashed.stdout.split()):
            blobs[path] = blob
    return {"available": True, "toplevel": str(toplevel),
            "head": head.stdout.strip() if head and head.returncode == 0 else None,
            "files": blobs}


def changed_files(before: dict, after: dict) -> list[str] | None:
    """Repository-relative paths changed between two snapshots, or None if unknowable."""
    if not (before.get("available") and after.get("available")):
        return None
    if before.get("toplevel") != after.get("toplevel"):
        return None
    a, b = before.get("files") or {}, after.get("files") or {}
    changed = {p for p in set(a) | set(b) if a.get(p) != b.get(p)}
    if before.get("head") and after.get("head") and before["head"] != after["head"]:
        diff = _git(Path(after["toplevel"]), "diff", "--name-only", before["head"],
                    after["head"])
        if diff is None or diff.returncode != 0:
            return None
        changed.update(line for line in diff.stdout.splitlines() if line.strip())
    return sorted(changed)


def outside_sources(ctx: Ctx, changed: list[str], toplevel: Path) -> list[str]:
    """Changed files that no active item declares, excluding the board's own files."""
    declared: set[str] = set()
    for item in rb.items(ctx.board):
        declared.update(item.get("sources") or [])
        declared.add(item.get("render"))
        if item.get("svg"):
            declared.add(item["svg"])
    board_dir = ctx.board_dir.resolve()
    root = ctx.root.resolve()
    out = []
    for rel in changed:
        path = (toplevel / rel).resolve()
        if path.is_relative_to(board_dir):
            continue
        shown = path.relative_to(root).as_posix() if path.is_relative_to(root) else rel
        if shown not in declared:
            out.append(shown)
    return sorted(out)


def _snapshot_path(ctx: Ctx, n: int) -> Path:
    return ctx.board_dir / rb.RENDERS_DIR / rb.round_tag(n) / SNAPSHOT_FILE


# --------------------------------------------------------------------------- round plans
def plan_skeleton() -> str:
    """The fenced skeleton in the round-plan template, read at run time (RB-P1)."""
    text = PLAN_TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"```markdown\n(.*?)\n```", text, re.S)
    if not m:
        raise rb.ReviewBoardError(f"no ```markdown skeleton in {PLAN_TEMPLATE}")
    return m.group(1) + "\n"


def _round_events(ctx: Ctx, r: dict) -> list[dict]:
    by_id = rb.events_by_id(ctx.feedback)
    ids = list(r.get("listed") or []) + [e for e in r.get("carried") or []
                                         if e not in (r.get("listed") or [])]
    return [by_id[e] for e in ids if e in by_id]


def _approach_seed(ctx: Ctx, r: dict) -> str:
    grouped: dict[str, list[str]] = {}
    for e in _round_events(ctx, r):
        grouped.setdefault(str(e.get("item")), []).append(str(e.get("id")))
    if not grouped:
        return "No events this round."
    return "\n\n".join(f"### {item}\n\n" + "\n".join(f"- {eid}: " for eid in ids)
                       for item, ids in grouped.items())


def _header_block(ctx: Ctx, r: dict) -> str:
    gate = r.get("stop_gate") or {}
    verdict = gate.get("verdict") or "not recorded"
    approved = gate.get("approved_on") or "n/a"
    listed, carried = r.get("listed") or [], r.get("carried") or []
    return "\n".join([
        f"- Board: `{ctx.slug}`",
        f"- Opened: {_when(r.get('opened_at'))}. Cursor: seq {r.get('cursor_seq')} "
        f"({_when(r.get('cursor_at'))})",
        f"- Events: {len(listed)} new, {len(carried)} carried from earlier rounds",
        f"- Stop gate: {verdict}. Approved: {approved}",
        f"- Stop-gate reason: {_cell(gate.get('reason'))}",
        f"- Closed: {_when(r.get('closed_at')) if r.get('closed_at') else 'open'}",
    ])


def _triage_block(ctx: Ctx, r: dict) -> str:
    events = _round_events(ctx, r)
    if not events:
        return "No events this round."
    triage = {str(t.get("event")): t for t in r.get("triage") or [] if isinstance(t, dict)}
    owner = rb.owner_id(ctx.board)
    rows = ["| Event | Item | By | Kind | Note | Decision | Reason |",
            "|---|---|---|---|---|---|---|"]
    for e in events:
        t = triage.get(str(e.get("id")), {})
        by = str(e.get("by"))
        if by != owner:
            by += " (not owner)"
        rows.append(f"| {e.get('id')} | {e.get('item')} | {_cell(by)} | {e.get('kind')} | "
                    f"{_cell(e.get('text'))} | {t.get('decision') or '—'} | "
                    f"{_cell(t.get('reason'))} |")
    return "\n".join(rows)


def _changed_files_block(r: dict) -> str:
    cf = r.get("changed_files")
    if not isinstance(cf, dict):
        return "Written at close."
    if not cf.get("available"):
        return ("Not available: the round was not opened and closed in the same git "
                "checkout, or the project is not in a git repository.")
    outside = cf.get("outside_sources") or []
    if not outside:
        return "None outside the declared sources."
    return "\n".join(f"- `{p}`" for p in outside)


def write_plan(ctx: Ctx, r: dict, create: bool = False) -> Path | None:
    """Create the skeleton when asked, then regenerate every generated block."""
    n = int(r["n"])
    path = ctx.board_dir / rb.round_plan_rel(n)
    if path.exists():
        text = path.read_text(encoding="utf-8")
    elif create:
        title = (ctx.board.get("board") or {}).get("title") or ctx.slug
        text = (plan_skeleton().replace("{{round}}", f"{n:02d}")
                .replace("{{board_title}}", str(title))
                .replace("{{approach}}", _approach_seed(ctx, r)))
    else:
        return None
    blocks = {"header": _header_block(ctx, r), "triage": _triage_block(ctx, r),
              "changed-files": _changed_files_block(r)}
    text = _MARKER_RE.sub(
        lambda m: (f"{m.group(1)}\n{blocks[m.group(2)]}\n{m.group(4)}"
                   if m.group(2) in blocks else m.group(0)), text)
    rb.atomic_write_text(path, text)
    return path


# --------------------------------------------------------------------------- init
def cmd_init(args: argparse.Namespace) -> int:
    ctx = load_ctx(args, state=False)
    result = rl.LintResult()
    rl.check_board(result, ctx.board, ctx.root)
    if not report(result, "board.yaml does not pass lint; nothing was created:"):
        return 1
    existing = [n for n in (rb.FEEDBACK_FILE, rb.LEDGER_FILE)
                if (ctx.board_dir / n).exists()]
    if existing:
        print(f"Refusing to initialize: {', '.join(existing)} already exist in "
              f"{ctx.board_dir}. A board is initialized once.")
        return 1
    rb.save_feedback(ctx.board_dir, rb.new_feedback(ctx.board))
    rb.save_ledger(ctx.board_dir, rb.new_ledger(ctx.board))
    (ctx.board_dir / rb.ROUNDS_DIR).mkdir(exist_ok=True)
    print(f"Initialized board {ctx.slug}: {len(rb.items(ctx.board))} items, "
          f"{len(rb.reviewers(ctx.board, include_retired=False))} reviewers "
          f"(owner: {rb.owner_id(ctx.board)}).")
    print("Next: `round open`, then `render`, then `record` a stop gate and `round close`.")
    return 0


# --------------------------------------------------------------------------- round open
def cmd_round_open(args: argparse.Namespace) -> int:
    ctx = load_ctx(args)
    result = rl.lint(ctx.board, ctx.feedback, ctx.ledger, project_root=ctx.root, at="open",
                     head=rl.head_events(ctx.board_dir))
    if not report(result, "The board does not pass lint; no round was opened:"):
        return 1
    current = rb.open_round(ctx.ledger)
    if current is not None:
        print(f"Round {current['n']} is still open. Close it before opening another.")
        return 1
    n = len(rb.rounds(ctx.ledger)) + 1
    now = rb.utc_now()
    cursor = rb.max_seq(ctx.feedback)
    by_id = {e.get("seq"): e for e in rb.events(ctx.feedback)}
    listed = rb.round_event_ids(ctx.feedback, rb.previous_cursor(ctx.ledger, n), cursor)
    carried = [e for e in rb.carried_event_ids(ctx.ledger, n) if e not in listed]
    r = {"n": n, "opened_at": now, "cursor_seq": cursor,
         "cursor_at": (by_id.get(cursor) or {}).get("at") or now,
         "listed": listed, "carried": carried,
         "stop_gate": {"verdict": None, "reason": None, "approved_on": None},
         "triage": [], "changes": [], "responses": [], "waivers": [],
         "changed_files": None, "closed_at": None}
    snapshot = file_snapshot(ctx.root)
    rb.atomic_write_text(_snapshot_path(ctx, n), json.dumps(snapshot, indent=1) + "\n")
    ctx.ledger.setdefault("rounds", []).append(r)
    rb.save_ledger(ctx.board_dir, ctx.ledger)
    plan = write_plan(ctx, r, create=True)

    owner = rb.owner_id(ctx.board)
    print(f"Opened round {n} at cursor seq {cursor}: {len(listed)} new events, "
          f"{len(carried)} carried.")
    for e in _round_events(ctx, r):
        tag = "carried" if e["id"] in carried else "new"
        who = e.get("by") if e.get("by") == owner else f"{e.get('by')} (not owner: surface)"
        text = str(e.get("text") or "").replace("\n", " ")
        print(f"  {e['id']}  {tag:<7} {e.get('item')}  {who}  {e.get('kind')}: {text}")
    print(f"Round plan: {plan}")
    return 0


# --------------------------------------------------------------------------- render
def _argv(ctx: Ctx) -> list[str]:
    return [str(a).replace("{python}", sys.executable)
            for a in (ctx.board.get("render") or {}).get("argv") or []]


def cmd_render(args: argparse.Namespace) -> int:
    ctx = load_ctx(args)
    r = rb.open_round(ctx.ledger)
    if r is None:
        print("No round is open. Run `round open` first; every render belongs to a round.")
        return 1
    result = rl.lint(ctx.board, ctx.feedback, ctx.ledger, project_root=ctx.root)
    if not report(result, "The board does not pass lint; nothing was rendered:"):
        return 1
    n = int(r["n"])
    render = ctx.board.get("render") or {}
    active = rb.items(ctx.board)
    argv = _argv(ctx)
    timeout = int(render.get("timeout_seconds") or 600)
    print(f"Rendering {len(active)} items for round {n} (RB-R3).")
    print(f"  command: {' '.join(argv)}")
    print(f"  in: {ctx.root}")
    print(f"  expected runtime: {render.get('expected_runtime')}; timeout {timeout}s")
    print("  outputs:")
    for item in active:
        print(f"    {item['render']}" + (f", {item['svg']}" if item.get("svg") else ""))
    sys.stdout.flush()

    started = time.time()
    try:
        proc = subprocess.run(argv, cwd=str(ctx.root), capture_output=True, text=True,
                              timeout=timeout)
    except FileNotFoundError as exc:
        print(f"Render command not found: {exc}. Nothing was recorded.")
        return 1
    except subprocess.TimeoutExpired:
        print(f"Render command exceeded {timeout}s. Nothing was recorded.")
        return 1
    elapsed = time.time() - started
    if proc.returncode != 0:
        print(f"Render command exited {proc.returncode} after {elapsed:.1f}s. "
              "Nothing was recorded.")
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-15:]
        for line in tail:
            print(f"  | {line}")
        return 1

    missing = [i["id"] for i in active if not rb.resolve_under(ctx.root, i["render"]).is_file()]
    if missing:
        print(f"Render finished but wrote no PNG for: {', '.join(missing)} (RB-R4). "
              "Nothing was recorded.")
        return 1

    medium = (ctx.board.get("board") or {}).get("medium") or "print"
    palette = rm.load_palette()
    closed = rb.latest_closed_round(ctx.ledger)
    staged = []
    for item in active:
        png = rb.resolve_under(ctx.root, item["render"])
        svg = rb.resolve_under(ctx.root, item["svg"]) if item.get("svg") else None
        try:
            digest = rb.content_hash(png)
            measurements = rm.measure(png, svg, medium, palette)
        except rb.ReviewBoardError as exc:
            print(f"{item['id']}: {exc}. Nothing was recorded.")
            return 1
        prev = rb.render_for(ctx.ledger, item["id"], closed)
        classification = ("new" if prev is None else
                          "unchanged" if prev.get("hash") == digest else "changed")
        prev_dpi = ((prev or {}).get("measurements") or {}).get("dpi")
        measurements["dpi_changed"] = prev is not None and prev_dpi != measurements["dpi"]
        stale = png.stat().st_mtime < started - 1
        staged.append((item, png, svg, digest, classification, measurements, stale))

    for item, png, svg, digest, classification, measurements, stale in staged:
        snap = ctx.board_dir / rb.snapshot_rel(n, item["id"], "png")
        snap.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(png, snap)
        svg_rel = None
        if svg is not None and svg.is_file():
            svg_rel = rb.snapshot_rel(n, item["id"], "svg")
            shutil.copy2(svg, ctx.board_dir / svg_rel)
        entry = rb.ledger_item(ctx.ledger, item["id"])
        if entry is None:
            entry = {"id": item["id"], "renders": []}
            ctx.ledger.setdefault("items", []).append(entry)
        entry["renders"] = [x for x in entry.get("renders") or []
                            if not (isinstance(x, dict) and x.get("round") == n)]
        entry["renders"].append({"round": n, "hash": digest,
                                 "snapshot": rb.snapshot_rel(n, item["id"], "png"),
                                 "svg_snapshot": svg_rel, "classification": classification,
                                 "measurements": measurements})
    rb.save_ledger(ctx.board_dir, ctx.ledger)

    counts = {c: sum(1 for s in staged if s[4] == c) for c in rb.CLASSIFICATIONS}
    print(f"Rendered in {elapsed:.1f}s: {counts['new']} new, {counts['changed']} changed, "
          f"{counts['unchanged']} unchanged.")
    for item, _png, _svg, _d, classification, m, stale in staged:
        fails = [k for k in rb.MEASURE_CHECKS if (m.get(k) or {}).get("result") == "fail"]
        notes = []
        if fails:
            notes.append("fails " + ", ".join(fails))
        if m.get("dpi_changed"):
            notes.append(f"dpi changed to {m.get('dpi')}")
        if stale:
            notes.append("PNG was not rewritten by this render")
        print(f"  {item['id']}: {classification}" + (f" ({'; '.join(notes)})" if notes else ""))
    return 0


# --------------------------------------------------------------------------- record
_RECORD_KEYS = ("stop_gate", "triage", "changes", "responses", "waivers")


def _upsert(existing: list, entries: list, key) -> list:
    out = [x for x in existing if isinstance(x, dict)]
    for entry in entries:
        out = [x for x in out if key(x) != key(entry)]
        out.append(entry)
    return out


def cmd_record(args: argparse.Namespace) -> int:
    ctx = load_ctx(args)
    r = rb.open_round(ctx.ledger)
    if r is None:
        print("No round is open. `record` writes to the open round only.")
        return 1
    data = rb.load_yaml(Path(args.from_file).expanduser())
    errors: list[str] = []
    unknown = sorted(set(data) - set(_RECORD_KEYS))
    if unknown:
        errors.append(f"unknown keys {unknown}; allowed: {', '.join(_RECORD_KEYS)}")
    in_round = set(r.get("listed") or []) | set(r.get("carried") or [])
    active = {i["id"] for i in rb.items(ctx.board)}
    # An item retired in the round its note asked for that retirement still owes the note a
    # response (RL-11 counts every item with an event triaged this round), so a response may
    # name any item in board.yaml, retired or not.
    declared = {str(i.get("id")) for i in (ctx.board.get("items") or []) if isinstance(i, dict)}

    def entries(name: str) -> list[dict]:
        raw = data.get(name) or []
        if not isinstance(raw, list) or not all(isinstance(x, dict) for x in raw):
            errors.append(f"{name} must be a list of mappings")
            return []
        return [dict(x) for x in raw]

    triage = entries("triage")
    for t in triage:
        if t.get("event") not in in_round:
            errors.append(f"triage: {t.get('event')} is not listed or carried in round {r['n']}")
        if t.get("decision") not in rb.DECISIONS:
            errors.append(f"triage: {t.get('event')} decision {t.get('decision')!r} is not one "
                          f"of {', '.join(rb.DECISIONS)}")
        t.setdefault("reason", None)
        t.setdefault("owner_confirmed_on", None)
    changes = entries("changes")
    for c in changes:
        if c.get("item") not in active:
            errors.append(f"changes: unknown item {c.get('item')!r}")
        c.setdefault("explanation", None)
    responses = entries("responses")
    for resp in responses:
        if resp.get("item") not in declared:
            errors.append(f"responses: unknown item {resp.get('item')!r}")
        if resp.get("state") not in rb.RESPONSE_STATES:
            errors.append(f"responses: {resp.get('item')} state {resp.get('state')!r} is not "
                          f"one of {', '.join(rb.RESPONSE_STATES)}")
    waivers = entries("waivers")
    for w in waivers:
        if w.get("item") not in active or w.get("check") not in rb.MEASURE_CHECKS:
            errors.append(f"waivers: {w!r} needs a known item and a check from "
                          f"{', '.join(rb.MEASURE_CHECKS)}")
    gate = data.get("stop_gate")
    if gate is not None:
        if not isinstance(gate, dict) or not set(gate) <= {"verdict", "reason", "approved_on"}:
            errors.append("stop_gate takes verdict, reason, and approved_on")
        elif "verdict" in gate and gate["verdict"] not in rb.STOP_VERDICTS:
            errors.append(f"stop_gate.verdict must be one of {', '.join(rb.STOP_VERDICTS)}")
    if errors:
        print("Nothing was recorded:")
        for e in errors:
            print(f"  {e}")
        return 1

    if isinstance(gate, dict):
        merged = dict(r.get("stop_gate") or {})
        merged.update(gate)
        r["stop_gate"] = merged
    r["triage"] = _upsert(r.get("triage") or [], triage, lambda x: x.get("event"))
    r["changes"] = _upsert(r.get("changes") or [], changes, lambda x: x.get("item"))
    r["responses"] = _upsert(r.get("responses") or [], responses, lambda x: x.get("item"))
    r["waivers"] = _upsert(r.get("waivers") or [], waivers,
                           lambda x: (x.get("item"), x.get("check")))
    rb.save_ledger(ctx.board_dir, ctx.ledger)
    write_plan(ctx, r)
    print(f"Recorded in round {r['n']}: {len(triage)} triage, {len(changes)} changes, "
          f"{len(responses)} responses, {len(waivers)} waivers"
          + (", stop gate" if isinstance(gate, dict) else "") + ".")
    pending = rl.LintResult()
    rl.check_close(pending, ctx.board, ctx.feedback, ctx.ledger)
    if pending.failures:
        print("Still needed before `round close`:")
        for f in pending.failures:
            print(f"  {f.line()}")
    return 0


# --------------------------------------------------------------------------- round close
def _owner_counts(ctx: Ctx) -> tuple[int, int]:
    active = rb.items(ctx.board)
    approved = sum(1 for i in active
                   if rb.owner_approval(ctx.board, ctx.feedback, ctx.ledger, i["id"])["current"])
    return approved, len(active) - approved


def cmd_round_close(args: argparse.Namespace) -> int:
    ctx = load_ctx(args)
    r = rb.open_round(ctx.ledger)
    if r is None:
        print("No round is open.")
        return 1
    n = int(r["n"])
    result = rl.lint(ctx.board, ctx.feedback, ctx.ledger, project_root=ctx.root, at="close",
                     head=rl.head_events(ctx.board_dir))
    if not report(result, f"Round {n} cannot close:"):
        print(f"Round {n} stays open; nothing was saved.")
        return 1

    outside: list[str] = []
    snapshot_file = _snapshot_path(ctx, n)
    before = json.loads(snapshot_file.read_text(encoding="utf-8")) if snapshot_file.is_file() \
        else {"available": False}
    after = file_snapshot(ctx.root)
    changed = changed_files(before, after)
    if changed is None:
        r["changed_files"] = {"available": False, "outside_sources": []}
    else:
        outside = outside_sources(ctx, changed, Path(after["toplevel"]))
        r["changed_files"] = {"available": True, "outside_sources": outside}
    r["closed_at"] = rb.utc_now()
    rb.save_ledger(ctx.board_dir, ctx.ledger)
    write_plan(ctx, r)

    approved, still_open = _owner_counts(ctx)
    changed_items = [i["id"] for i in rb.items(ctx.board)
                     if (rb.render_for(ctx.ledger, i["id"], n) or {}).get("classification")
                     == "changed"]
    print(f"Closed round {n}: {approved} approved, {len(changed_items)} changed this round, "
          f"{still_open} open (RB-C5).")
    if changed is None:
        print("  Files changed outside the sources: not available (no git snapshot pair).")
    elif outside:
        print("  Files changed outside every item's sources; explain each in the round plan "
              "(RB-C4):")
        for path in outside:
            print(f"    {path}")
    return 0


# --------------------------------------------------------------------------- status
def board_status(ctx: Ctx) -> dict:
    """RB-D1, computed. Every reason that the board is not done, item by item."""
    reasons: list[str] = []
    lint = rl.lint(ctx.board, ctx.feedback, ctx.ledger, project_root=ctx.root,
                   head=rl.head_events(ctx.board_dir))
    reasons += [f"lint: {f.line()}" for f in lint.failures]
    closed = rb.latest_closed_round(ctx.ledger)
    if closed is None:
        reasons.append("no round has closed yet")
    current = rb.open_round(ctx.ledger)
    if current is not None:
        reasons.append(f"round {current['n']} is open")

    by_id = rb.events_by_id(ctx.feedback)
    latest = rb.latest_triage(ctx.ledger, 10 ** 9)
    open_events = {eid: d for eid, d in latest.items() if d in rb.OPEN_DECISIONS}
    last_cursor = int((rb.find_round(ctx.ledger, closed) or {}).get("cursor_seq") or 0) \
        if closed else 0
    untriaged = rb.round_event_ids(ctx.feedback, last_cursor, rb.max_seq(ctx.feedback))
    if current is None and untriaged:
        reasons.append(f"{len(untriaged)} notes posted since round {closed} closed are not "
                       f"yet triaged ({', '.join(untriaged)})")
    waived = {(w.get("item"), w.get("check")) for r in rb.rounds(ctx.ledger)
              if r.get("closed_at") for w in r.get("waivers") or [] if isinstance(w, dict)}

    rows = []
    for item in rb.items(ctx.board):
        iid = item["id"]
        approval = rb.owner_approval(ctx.board, ctx.feedback, ctx.ledger, iid)
        render = rb.current_render(ctx.ledger, iid) or {}
        failing = [k for k in rb.MEASURE_CHECKS
                   if ((render.get("measurements") or {}).get(k) or {}).get("result") == "fail"
                   and (iid, k) not in waived]
        item_open = sorted(eid for eid in open_events
                           if (by_id.get(eid) or {}).get("item") == iid)
        if not approval["current"]:
            state = ("approved against an earlier render (changed since approval)"
                     if approval["status"] == "approved" else approval["status"])
            reasons.append(f"{iid}: owner status is {state}")
        for eid in item_open:
            reasons.append(f"{iid}: {eid} is still {open_events[eid]}")
        for check in failing:
            reasons.append(f"{iid}: {check} fails and is not waived (RB-M4)")
        rows.append({"item": iid, "owner_status": approval["status"],
                     "approval_current": approval["current"], "open_events": item_open,
                     "failing_checks": failing})
    return {"done": not reasons, "reasons": reasons, "items": rows,
            "latest_closed_round": closed}


def cmd_status(args: argparse.Namespace) -> int:
    ctx = load_ctx(args)
    status = board_status(ctx)
    if args.json:
        print(json.dumps(status, indent=1))
        return 0 if status["done"] else 1
    print(f"Board {ctx.slug}: {'DONE' if status['done'] else 'NOT DONE'} "
          f"(latest closed round: {status['latest_closed_round'] or 'none'})")
    for row in status["items"]:
        mark = "ok " if row["approval_current"] and not row["open_events"] \
            and not row["failing_checks"] else "   "
        print(f"  {mark}{row['item']}: owner {row['owner_status']}"
              + ("" if row["approval_current"] or row["owner_status"] != "approved"
                 else " (stale)"))
    for reason in status["reasons"]:
        print(f"  - {reason}")
    return 0 if status["done"] else 1


# --------------------------------------------------------------------------- lint, summary
def cmd_lint(args: argparse.Namespace) -> int:
    ctx = load_ctx(args)
    result = rl.lint_board_dir(ctx.board_dir, ctx.root, args.at)
    if args.json:
        print(json.dumps(result.as_dict()))
        return 0 if result.ok else 1
    report(result)
    if result.ok:
        print("PASS")
    return 0 if result.ok else 1


def cmd_summary(args: argparse.Namespace) -> int:
    ctx = load_ctx(args)
    status = board_status(ctx)
    meta = ctx.board.get("board") or {}
    owner = rb.owner_id(ctx.board)
    others = [r["id"] for r in rb.reviewers(ctx.board, include_retired=False)
              if r.get("id") != owner]
    rs = rb.rounds(ctx.ledger)
    current = rb.open_round(ctx.ledger)
    lines = [
        f"# Review board: {meta.get('title') or ctx.slug}",
        "",
        "<!-- Generated by review_board.py summary from board.yaml, feedback.yaml, and "
        "ledger.yaml. Do not edit by hand. -->",
        "",
        f"- Board: `{ctx.slug}` · Medium: {meta.get('medium')}",
        f"- Owner: {owner} · Reviewers: {', '.join(others) or 'none'}",
        f"- Rounds: {len(rs)} (latest closed: {status['latest_closed_round'] or 'none'}; "
        f"open: {current['n'] if current else 'none'})",
        f"- Status: **{'Done' if status['done'] else 'Not done'}**",
        "",
        "## Items",
        "",
        "| Item | Title | Group | Frozen | Owner status | Approval current | Last changed | "
        "Latest response |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in rb.items(ctx.board):
        iid = item["id"]
        approval = rb.owner_approval(ctx.board, ctx.feedback, ctx.ledger, iid)
        renders = (rb.ledger_item(ctx.ledger, iid) or {}).get("renders") or []
        changed = [x.get("round") for x in renders
                   if x.get("classification") in ("new", "changed")]
        response = None
        for r in rs:
            for resp in r.get("responses") or []:
                if isinstance(resp, dict) and resp.get("item") == iid:
                    response = f"R{r.get('n')} {resp.get('state')}: {resp.get('text')}"
        lines.append(f"| {iid} | {_cell(item.get('title'))} | {_cell(item.get('group'))} | "
                     f"{'yes' if item.get('frozen') else 'no'} | {approval['status']} | "
                     f"{'yes' if approval['current'] else 'no'} | "
                     f"{('R' + str(changed[-1])) if changed else '—'} | {_cell(response)} |")
    lines += ["", "## Open items", ""]
    lines += [f"- {_cell(reason)}" for reason in status["reasons"]] or ["None."]
    lines += ["", "## Rounds", "",
              "| Round | Opened | Closed | New events | Carried | Changed items | Stop gate |",
              "|---|---|---|---|---|---|---|"]
    for r in rs:
        n = r.get("n")
        changed = [i["id"] for i in rb.items(ctx.board)
                   if (rb.render_for(ctx.ledger, i["id"], n) or {}).get("classification")
                   == "changed"]
        gate = (r.get("stop_gate") or {}).get("verdict") or "—"
        lines.append(f"| {n} | {_when(r.get('opened_at'))} | "
                     f"{_when(r.get('closed_at')) if r.get('closed_at') else 'open'} | "
                     f"{len(r.get('listed') or [])} | {len(r.get('carried') or [])} | "
                     f"{', '.join(changed) or '—'} | {gate} |")
    rb.atomic_write_text(ctx.board_dir / rb.SUMMARY_FILE, "\n".join(lines) + "\n")
    refreshed = [p for p in (write_plan(ctx, r) for r in rs) if p is not None]
    print(f"Wrote {ctx.board_dir / rb.SUMMARY_FILE}; refreshed {len(refreshed)} round plans.")
    return 0


# --------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--board", required=True, help="The board directory")
    common.add_argument("--project-root", default=None,
                        help="Root of the reviewed project (the directory holding PROJECT.md)")
    ap = argparse.ArgumentParser(prog="review_board.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("init", parents=[common], help="Create feedback.yaml and ledger.yaml"
                   ).set_defaults(fn=cmd_init)
    rnd = sub.add_parser("round", help="Open or close a round")
    rsub = rnd.add_subparsers(dest="action", required=True)
    rsub.add_parser("open", parents=[common]).set_defaults(fn=cmd_round_open)
    rsub.add_parser("close", parents=[common]).set_defaults(fn=cmd_round_close)
    sub.add_parser("render", parents=[common], help="Render and record every item"
                   ).set_defaults(fn=cmd_render)
    rec = sub.add_parser("record", parents=[common], help="Merge agent-lane entries")
    rec.add_argument("--from", dest="from_file", required=True,
                     help="YAML file with any of: " + ", ".join(_RECORD_KEYS))
    rec.set_defaults(fn=cmd_record)
    st = sub.add_parser("status", parents=[common], help="Done or not done")
    st.add_argument("--json", action="store_true")
    st.set_defaults(fn=cmd_status)
    li = sub.add_parser("lint", parents=[common], help="Run the lint")
    li.add_argument("--at", choices=rl.STAGES, default="lint")
    li.add_argument("--json", action="store_true")
    li.set_defaults(fn=cmd_lint)
    sub.add_parser("summary", parents=[common], help="Regenerate board.md and round plans"
                   ).set_defaults(fn=cmd_summary)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except rb.ReviewBoardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
