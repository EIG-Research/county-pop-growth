#!/usr/bin/env python3
"""Schema, lane, and round-close lint for a review board.

One script holds every check, and every write goes through it: the board server runs it on
each save, `review_board.py` runs it at `round open` and `round close`, and it runs on demand
from `review_board.py lint` or directly from here. A check that lived in several places would
drift in some of them.

Each check has a stable code. Every failure line starts with that code and the thing it is
about:

    RL-05: ev-00003 altered since git HEAD

| Code  | Checked at | Failure |
|-------|------------|---------|
| RL-01 | all   | `board.yaml` invalid, or `feedback.yaml`/`ledger.yaml` name another board |
| RL-02 | all   | An event names an item or reviewer `board.yaml` does not list |
| RL-03 | all   | A malformed event |
| RL-04 | all   | A duplicate event id, a non-increasing `seq`, or an id that does not match its `seq` |
| RL-05 | write, open, close, lint | An append-only violation against the previous version or `git HEAD` |
| RL-06 | close | Triage missing, duplicated, or outside the closed set; `listed`/`carried` wrong |
| RL-07 | close | A non-owner event acted on without `owner_confirmed_on` |
| RL-08 | close | A decision other than `do` without a reason |
| RL-09 | close | A changed item with no covering decision and no explanation |
| RL-10 | close | A frozen item changed |
| RL-11 | close | A missing `what_changed` or response, or a response state outside the closed set |
| RL-12 | close | A missing stop gate, or a `stop` verdict without `approved_on` |
| RL-13 | all   | Rounds, renders, or waivers malformed or out of order; a round closing without renders |
| RL-14 | all   | A config path that is absolute, contains `..`, or resolves outside the project root |
| RL-15 | all   | A `hosting` block that marks the board for hosting; the board is local only |

The binding definitions are in `Infrastructure/templates/review-board-ledger.md`, and the
rules they enforce are in `Infrastructure/rules/review-board-rules.md`.

Usage:
    python Infrastructure/scripts/review_board_lint.py --board <board dir> \
        [--project-root <dir>] [--at lint|open|close|write] [--json]

Exit codes: 0 no failures; 1 failures; 2 the board could not be read or the project root
could not be resolved.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_board_lib as rb  # noqa: E402
from localapp.lint import Finding, LintResult  # noqa: E402,F401  (callers use rl.LintResult)

STAGES = ("lint", "open", "close", "write")


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------- board.yaml
def check_board(res: LintResult, board: Any, project_root: Path | None) -> bool:
    """RL-01, RL-14, RL-15. Returns False when the board is too broken to go on."""
    if not isinstance(board, dict):
        res.fail("RL-01", "board.yaml", "is not a mapping")
        return False
    if board.get("schema_version") != rb.SCHEMA_VERSION:
        res.fail("RL-01", "board.yaml", f"schema_version must be {rb.SCHEMA_VERSION}")
    if not _nonempty_str((board.get("project") or {}).get("id")):
        res.fail("RL-01", "board.yaml", "project.id is missing")
    meta = board.get("board") or {}
    if not isinstance(meta, dict) or not rb.ID_RE.match(str(meta.get("id") or "")):
        res.fail("RL-01", "board.yaml", "board.id must match [a-z0-9][a-z0-9-]*")
        meta = meta if isinstance(meta, dict) else {}
    if not _nonempty_str(meta.get("title")):
        res.fail("RL-01", "board.yaml", "board.title is missing")
    if meta.get("medium") not in rb.MEDIA:
        res.fail("RL-01", "board.yaml", f"board.medium must be one of {', '.join(rb.MEDIA)}")
    if "fixture" in meta and not isinstance(meta["fixture"], bool):
        res.fail("RL-01", "board.yaml", "board.fixture must be true or false")

    people = board.get("reviewers")
    if not isinstance(people, list) or not people:
        res.fail("RL-01", "board.yaml", "reviewers must be a non-empty list")
        people = []
    seen: set[str] = set()
    owners = []
    for r in people:
        rid = r.get("id") if isinstance(r, dict) else None
        if not isinstance(r, dict) or not rb.REVIEWER_ID_RE.match(str(rid or "")):
            res.fail("RL-01", "board.yaml", f"reviewer id {rid!r} must match "
                     "[a-z0-9][a-z0-9._-]*")
            continue
        if rid in seen:
            res.fail("RL-01", rid, "is listed twice under reviewers")
        seen.add(rid)
        if r.get("role") not in rb.ROLES:
            res.fail("RL-01", rid, f"role must be one of {', '.join(rb.ROLES)}")
        if r.get("role") == "owner":
            owners.append(r)
        if "retired" in r and not isinstance(r["retired"], bool):
            res.fail("RL-01", rid, "retired must be true or false")
    if len(owners) != 1:
        res.fail("RL-01", "board.yaml",
                 f"exactly one reviewer must have role: owner (found {len(owners)})")
    elif owners[0].get("retired"):
        res.fail("RL-01", owners[0].get("id"), "the owner cannot be retired")

    render = board.get("render")
    if not isinstance(render, dict):
        res.fail("RL-01", "board.yaml", "render is missing")
        render = {}
    argv = render.get("argv")
    if not isinstance(argv, list) or not argv or not all(_nonempty_str(a) for a in argv):
        res.fail("RL-01", "board.yaml", "render.argv must be a non-empty list of strings")
    if not _nonempty_str(render.get("expected_runtime")):
        res.fail("RL-01", "board.yaml", "render.expected_runtime is missing (RB-R3)")
    timeout = render.get("timeout_seconds")
    if not _is_int(timeout) or timeout <= 0:
        res.fail("RL-01", "board.yaml", "render.timeout_seconds must be a positive integer")

    entries = board.get("items")
    if not isinstance(entries, list) or not entries:
        res.fail("RL-01", "board.yaml", "items must be a non-empty list")
        entries = []
    ids: set[str] = set()
    for item in entries:
        iid = item.get("id") if isinstance(item, dict) else None
        if not isinstance(item, dict) or not rb.ID_RE.match(str(iid or "")):
            res.fail("RL-01", "board.yaml", f"item id {iid!r} must match [a-z0-9][a-z0-9-]*")
            continue
        if iid in ids:
            res.fail("RL-01", iid, "is listed twice under items")
        ids.add(iid)
        for key in ("title", "group"):
            if not _nonempty_str(item.get(key)):
                res.fail("RL-01", iid, f"{key} is missing")
        sources = item.get("sources")
        if not isinstance(sources, list) or not sources:
            res.fail("RL-01", iid, "sources must be a non-empty list of paths")
            sources = []
        if not isinstance(item.get("render"), str) or not item["render"].endswith(".png"):
            res.fail("RL-01", iid, "render must be a path ending in .png")
        svg = item.get("svg")
        if svg is not None and (not isinstance(svg, str) or not svg.endswith(".svg")):
            res.fail("RL-01", iid, "svg must be null or a path ending in .svg")
        if not isinstance(item.get("frozen"), bool):
            res.fail("RL-01", iid, "frozen must be true or false")
        if "retired" in item and not isinstance(item["retired"], bool):
            res.fail("RL-01", iid, "retired must be true or false")
        paths = [("sources", s) for s in sources] + [("render", item.get("render"))]
        if svg is not None:
            paths.append(("svg", svg))
        for key, rel in paths:
            problem = rb.path_problem(rel)
            if problem:
                res.fail("RL-14", iid, f"{key} path {rel!r} {problem}")
            elif project_root is not None:
                try:
                    rb.resolve_under(project_root, rel)
                except rb.ReviewBoardError as exc:
                    res.fail("RL-14", iid, str(exc))

    _check_hosting(res, board, ids)
    return True


def _check_hosting(res: LintResult, board: dict, ids: set[str]) -> None:
    """RL-15. The board is local only (RB-H1, RB-H2): nothing may be marked for hosting."""
    raw = board.get("hosting")
    if raw is None:
        return
    if not isinstance(raw, dict) or raw.get("cleared") not in (None, False):
        res.fail("RL-15", "board.yaml", "hosting.cleared must be false: the review board is "
                 "local only and has no hosted mode (RB-H2)")


def _check_identity(res: LintResult, board: dict, other: dict, name: str) -> None:
    if other.get("schema_version") != rb.SCHEMA_VERSION:
        res.fail("RL-01", name, f"schema_version must be {rb.SCHEMA_VERSION}")
    want_project = (board.get("project") or {}).get("id")
    want_board = (board.get("board") or {}).get("id")
    got_project = (other.get("project") or {}).get("id")
    got_board = (other.get("board") or {}).get("id")
    if (got_project, got_board) != (want_project, want_board):
        res.fail("RL-01", name, f"names {got_project}/{got_board} but board.yaml is "
                 f"{want_project}/{want_board}")


# --------------------------------------------------------------------------- feedback.yaml
def check_events(res: LintResult, board: dict, feedback: dict) -> None:
    """RL-02, RL-03, RL-04."""
    raw = feedback.get("events")
    if not isinstance(raw, list):
        res.fail("RL-03", "feedback.yaml", "events must be a list")
        return
    item_ids = set(rb.item_ids(board, include_retired=True))
    reviewer_ids = {str(r.get("id")) for r in rb.reviewers(board)}
    seen: set[str] = set()
    last_seq = 0
    for index, e in enumerate(raw):
        if not isinstance(e, dict):
            res.fail("RL-03", f"events[{index}]", "is not a mapping")
            continue
        eid = str(e.get("id"))
        seq = e.get("seq")
        if not _is_int(seq) or seq <= last_seq:
            res.fail("RL-04", eid, f"seq {seq!r} does not strictly increase")
        else:
            last_seq = seq
            if eid != rb.event_id(seq):
                res.fail("RL-04", eid, f"id does not match seq {seq}")
        if eid in seen:
            res.fail("RL-04", eid, "appears twice")
        seen.add(eid)

        if e.get("item") not in item_ids:
            res.fail("RL-02", eid, f"names unknown item {e.get('item')!r}")
        if str(e.get("by")) not in reviewer_ids:
            res.fail("RL-02", eid, f"names unknown reviewer {e.get('by')!r}")

        kind = e.get("kind")
        if kind not in rb.EVENT_KINDS:
            res.fail("RL-03", eid, f"kind {kind!r} is not one of {', '.join(rb.EVENT_KINDS)}")
        if not _nonempty_str(e.get("at")):
            res.fail("RL-03", eid, "at is missing")
        status = e.get("status")
        if kind == "status":
            if status not in rb.STATUSES:
                res.fail("RL-03", eid, f"status {status!r} is not one of "
                         f"{', '.join(rb.STATUSES)}")
            if e.get("text") not in (None, ""):
                res.fail("RL-03", eid, "a status event carries text")
        elif status is not None:
            res.fail("RL-03", eid, "only a status event carries a status")
        if kind in rb.NOTE_KINDS and not _nonempty_str(e.get("text")):
            res.fail("RL-03", eid, f"a {kind} has no text")
        ah = e.get("approved_hash")
        if kind == "status" and status == "approved":
            if not isinstance(ah, str) or not rb.HASH_RE.match(ah):
                res.fail("RL-03", eid, "an approval needs a 64-character approved_hash")
        elif ah is not None:
            res.fail("RL-03", eid, "approved_hash is set on an event that is not an approval")
        source = e.get("source")
        if source not in rb.EVENT_SOURCES:
            res.fail("RL-03", eid, f"source {source!r} is not one of "
                     f"{', '.join(rb.EVENT_SOURCES)}")
        if e.get("source_id") is not None:
            res.fail("RL-03", eid, "source_id is set; every event comes from the local board")


def check_append_only(res: LintResult, old_events: list, new_events: list,
                      against: str) -> None:
    """RL-05. Every earlier event is still present, unchanged, at the same position."""
    for index, old in enumerate(old_events):
        eid = old.get("id") if isinstance(old, dict) else f"events[{index}]"
        if index >= len(new_events):
            res.fail("RL-05", str(eid), f"is missing (present in {against})")
        elif new_events[index] != old:
            res.fail("RL-05", str(eid), f"was altered, removed, or reordered since {against}")


def head_events(board_dir: Path) -> list | None:
    """`feedback.yaml` as committed at git HEAD, or None when git, a repository, or a
    committed copy is absent. An untracked file passes the HEAD comparison (RB-L3)."""
    try:
        proc = subprocess.run(["git", "show", f"HEAD:./{rb.FEEDBACK_FILE}"],
                              cwd=str(board_dir), capture_output=True, text=True,
                              encoding="utf-8", timeout=30)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    data = rb.load_yaml_text(proc.stdout) or {}
    return data.get("events") if isinstance(data, dict) and isinstance(
        data.get("events"), list) else []


# --------------------------------------------------------------------------- ledger.yaml
def check_ledger(res: LintResult, board: dict, feedback: dict, ledger: dict) -> None:
    """RL-13: the shape and order of rounds, renders, and waivers."""
    rs = ledger.get("rounds")
    if not isinstance(rs, list):
        res.fail("RL-13", "ledger.yaml", "rounds must be a list")
        rs = []
    last_seq = rb.max_seq(feedback)
    prev_cursor = 0
    numbers = []
    for index, r in enumerate(rs):
        if not isinstance(r, dict):
            res.fail("RL-13", f"rounds[{index}]", "is not a mapping")
            continue
        n = r.get("n")
        tag = f"round {n}"
        numbers.append(n)
        if n != index + 1:
            res.fail("RL-13", tag, f"is at position {index + 1}; rounds are numbered 1..N")
        if not _nonempty_str(r.get("opened_at")):
            res.fail("RL-13", tag, "opened_at is missing")
        cursor = r.get("cursor_seq")
        if not _is_int(cursor) or cursor < prev_cursor:
            res.fail("RL-13", tag, f"cursor_seq {cursor!r} decreases or is not an integer")
        else:
            if cursor > last_seq:
                res.fail("RL-13", tag, f"cursor_seq {cursor} is beyond the last event "
                         f"({last_seq})")
            prev_cursor = cursor
        if not r.get("closed_at") and index != len(rs) - 1:
            res.fail("RL-13", tag, "is open but is not the last round")
        for key in ("listed", "carried"):
            if not isinstance(r.get(key, []), list):
                res.fail("RL-13", tag, f"{key} must be a list")
        for w in r.get("waivers") or []:
            if (not isinstance(w, dict) or w.get("check") not in rb.MEASURE_CHECKS
                    or not _nonempty_str(w.get("reason"))
                    or rb.find_item(board, str(w.get("item"))) is None):
                res.fail("RL-13", tag, f"malformed waiver {w!r}; needs a known item, a "
                         f"check from {', '.join(rb.MEASURE_CHECKS)}, and a reason")

    items = ledger.get("items")
    if not isinstance(items, list):
        res.fail("RL-13", "ledger.yaml", "items must be a list")
        items = []
    known_rounds = set(n for n in numbers if _is_int(n))
    for item in items:
        iid = item.get("id") if isinstance(item, dict) else None
        if not isinstance(item, dict) or rb.find_item(board, str(iid)) is None:
            res.fail("RL-13", str(iid), "is in ledger.yaml but not in board.yaml")
            continue
        seen_rounds: set[int] = set()
        for r in item.get("renders") or []:
            rn = r.get("round") if isinstance(r, dict) else None
            if rn not in known_rounds:
                res.fail("RL-13", iid, f"has a render for unknown round {rn!r}")
                continue
            if rn in seen_rounds:
                res.fail("RL-13", iid, f"has two renders for round {rn}")
            seen_rounds.add(rn)
            if not isinstance(r.get("hash"), str) or not rb.HASH_RE.match(r["hash"]):
                res.fail("RL-13", iid, f"round {rn} render hash is not 64 hex characters")
            if r.get("classification") not in rb.CLASSIFICATIONS:
                res.fail("RL-13", iid, f"round {rn} classification "
                         f"{r.get('classification')!r} is not one of "
                         f"{', '.join(rb.CLASSIFICATIONS)}")


def check_close(res: LintResult, board: dict, feedback: dict, ledger: dict) -> None:
    """RL-06 to RL-12, and RL-13 for renders, for the open round about to close."""
    r = rb.open_round(ledger)
    if r is None:
        res.fail("RL-13", "ledger.yaml", "there is no open round to close")
        return
    n = r.get("n")
    tag = f"round {n}"
    by_id = rb.events_by_id(feedback)
    owner = rb.owner_id(board)

    expected_listed = rb.round_event_ids(feedback, rb.previous_cursor(ledger, n),
                                         int(r.get("cursor_seq") or 0))
    expected_carried = rb.carried_event_ids(ledger, n)
    if list(r.get("listed") or []) != expected_listed:
        res.fail("RL-06", tag, f"listed {r.get('listed')} does not match feedback.yaml "
                 f"({expected_listed})")
    if list(r.get("carried") or []) != expected_carried:
        res.fail("RL-06", tag, f"carried {r.get('carried')} does not match earlier rounds "
                 f"({expected_carried})")
    expected = expected_listed + [e for e in expected_carried if e not in expected_listed]

    triage = [t for t in (r.get("triage") or []) if isinstance(t, dict)]
    counts: dict[str, int] = {}
    for t in triage:
        counts[str(t.get("event"))] = counts.get(str(t.get("event")), 0) + 1
    for eid in expected:
        if counts.get(eid, 0) == 0:
            res.fail("RL-06", eid, "has no triage entry")
        elif counts[eid] > 1:
            res.fail("RL-06", eid, "has more than one triage entry")
    for t in triage:
        eid = str(t.get("event"))
        if eid not in expected:
            res.fail("RL-06", eid, f"is triaged in {tag} but is not listed or carried there")
            continue
        decision = t.get("decision")
        if decision not in rb.DECISIONS:
            res.fail("RL-06", eid, f"decision {decision!r} is not one of "
                     f"{', '.join(rb.DECISIONS)}")
            continue
        event = by_id.get(eid, {})
        if (event.get("by") != owner and decision != "surface"
                and not _nonempty_str(t.get("owner_confirmed_on"))):
            res.fail("RL-07", eid, f"is from {event.get('by')}, not the owner, and is "
                     f"triaged {decision} without owner_confirmed_on (RB-T5)")
        if decision != "do" and not _nonempty_str(t.get("reason")):
            res.fail("RL-08", eid, f"is triaged {decision} with no reason (RB-T4)")

    active = rb.items(board)
    covered = {by_id.get(str(t.get("event")), {}).get("item") for t in triage
               if t.get("decision") in rb.ACTING_DECISIONS}
    changes = {}
    for c in r.get("changes") or []:
        if isinstance(c, dict):
            changes[str(c.get("item"))] = c
    for item in active:
        iid = item["id"]
        render = rb.render_for(ledger, iid, n)
        if render is None:
            res.fail("RL-13", iid, f"has no render in {tag}; run render before closing")
            continue
        if render.get("classification") != "changed":
            continue
        if item.get("frozen"):
            res.fail("RL-10", iid, "is frozen but its render changed (RB-R7)")
        change = changes.get(iid)
        if change is None or not _nonempty_str(change.get("what_changed")):
            res.fail("RL-11", iid, "changed but has no what_changed text")
        if iid not in covered and not _nonempty_str((change or {}).get("explanation")):
            res.fail("RL-09", iid, "changed with no do/do-with-change decision and no "
                     "explanation (RB-C2)")

    responses: dict[str, int] = {}
    for resp in r.get("responses") or []:
        if not isinstance(resp, dict):
            res.fail("RL-11", tag, f"malformed response {resp!r}")
            continue
        iid = str(resp.get("item"))
        responses[iid] = responses.get(iid, 0) + 1
        if resp.get("state") not in rb.RESPONSE_STATES:
            res.fail("RL-11", iid, f"response state {resp.get('state')!r} is not one of "
                     f"{', '.join(rb.RESPONSE_STATES)}")
        if not _nonempty_str(resp.get("text")):
            res.fail("RL-11", iid, "response has no text")
    needing = sorted({str(by_id.get(eid, {}).get("item")) for eid in expected})
    for iid in needing:
        if responses.get(iid, 0) == 0:
            res.fail("RL-11", iid, f"had events triaged in {tag} but has no response")
        elif responses[iid] > 1:
            res.fail("RL-11", iid, f"has more than one response in {tag}")

    gate = r.get("stop_gate")
    if not isinstance(gate, dict) or gate.get("verdict") not in rb.STOP_VERDICTS:
        res.fail("RL-12", tag, "stop_gate.verdict must be stop or proceed (RB-P2)")
    else:
        if not _nonempty_str(gate.get("reason")):
            res.fail("RL-12", tag, "stop_gate.reason is missing")
        if gate["verdict"] == "stop" and not _nonempty_str(gate.get("approved_on")):
            res.fail("RL-12", tag, "stop_gate.verdict is stop but approved_on is empty")


# --------------------------------------------------------------------------- entry points
def lint(board: Any, feedback: dict | None, ledger: dict | None, *,
         project_root: Path | None = None, at: str = "lint",
         prev_events: list | None = None, head: list | None = None) -> LintResult:
    """Every check that applies at `at`.

    `prev_events` is the event list loaded before a server save; `head` is the list
    committed at git HEAD, or None when there is none to compare against.
    """
    if at not in STAGES:
        raise ValueError(f"at must be one of {STAGES}")
    res = LintResult()
    if not check_board(res, board, project_root):
        return res
    if feedback is not None:
        _check_identity(res, board, feedback, rb.FEEDBACK_FILE)
        check_events(res, board, feedback)
    if ledger is not None:
        _check_identity(res, board, ledger, rb.LEDGER_FILE)
        check_ledger(res, board, feedback or {}, ledger)
    current = rb.events(feedback or {})
    if prev_events is not None:
        check_append_only(res, prev_events, current, "the version loaded before this save")
    if head is not None:
        check_append_only(res, head, current, "git HEAD")
    if at == "close" and feedback is not None and ledger is not None:
        check_close(res, board, feedback, ledger)
    return res


def lint_board_dir(board_dir: Path, project_root: Path | None = None,
                   at: str = "lint") -> LintResult:
    """Load the three files, compare against git HEAD where it applies, and lint."""
    board_dir = Path(board_dir)
    board = rb.load_board(board_dir)
    feedback = rb.load_feedback(board_dir)
    ledger = rb.load_ledger(board_dir)
    head = head_events(board_dir) if at in ("lint", "open", "close") else None
    return lint(board, feedback, ledger, project_root=project_root, at=at, head=head)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="review_board_lint.py",
                                 description="Lint a review board (RL-01..RL-15).")
    ap.add_argument("--board", required=True, help="The board directory")
    ap.add_argument("--project-root", default=None,
                    help="Root of the reviewed project (the directory holding PROJECT.md)")
    ap.add_argument("--at", choices=STAGES, default="lint",
                    help="Which stage's checks to run (default: lint)")
    ap.add_argument("--json", action="store_true", help="Emit a JSON result")
    args = ap.parse_args(argv)

    board_dir = Path(args.board).expanduser()
    try:
        board = rb.load_board(board_dir)
        root = rb.resolve_project_root(args.project_root, board)
        result = lint_board_dir(board_dir, root, args.at)
    except rb.ReviewBoardError as exc:
        if args.json:
            print(json.dumps({"ok": False, "warnings": [], "failures": [
                {"code": "ERROR", "subject": None, "message": str(exc)}]}))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.as_dict()))
        return 0 if result.ok else 1
    for warning in result.warnings:
        print(f"warning: {warning.line()}", file=sys.stderr)
    for failure in result.failures:
        print(failure.line())
    if result.ok:
        print("PASS")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
