#!/usr/bin/env python3
"""Reconcile a completed war-room ledger and render its work order.

Runs after the walkthrough, never during it. Splits cleanly in two:

  Mechanical (this script, no model)
    - promote assumptions from endorsed blocks into `assumption_export` (WR-Q8)
    - promote the author's own carried assumptions
    - set `divergence.match = true` on endorsed blocks
    - collect `unresolved` blocks into `open_questions`
    - render `work-order.md` from the `needs-change` and `unresolved` blocks (WR-O4)

  Judgment (left for the agent's reconcile phase)
    - classify divergence on every discussed block that is not an endorsement: one whose
      author wrote an account to compare against the recorded prediction, and equally one
      answered with a disposition and nothing else, which is silence rather than agreement

A session where every block was endorsed needs no model at all. This script reports which
blocks -- if any -- still require the agent, so that step is never guessed at.

What this script never does:

  - It never touches a `prediction` mapping. Predictions are immutable once prep has
    persisted them (WR-P3); reconcile records a divergence instead of editing a reading.
  - It never recomputes drift. `drift` and `drift_after_disposition` are written by
    `war_room_prep.py verify --write` and by the app server (WR-A3/A4, D11); this script
    reads the persisted flags so the console note, the ledger, and the rendered report
    cannot say three different things.

Lint gates every write (D7): `war_room_lint.py` runs before `--write` and again on the
bytes that were written. A refused ledger is not written at all, and a written ledger that
does not lint is reported loudly rather than left to be discovered later.

`session.reconciled` and the `{event: reconcile, at}` history entry (WR-O7, D10) are set
only when no block still needs agent judgment, so WL-09 stays quiet until the classification
actually exists. Rerunning `--write` afterwards is idempotent: the timestamp is not
rewritten and a second history entry is never appended.

Usage:
    python3 Infrastructure/scripts/war_room_reconcile.py --ledger <path> \
        [--project-root <dir>] [--write] [--allow-incomplete]

Without --write it reports what it would do and changes nothing.

Exit codes: 0 success; 1 lint refused the write, or the written ledger did not lint;
2 no ledger at that path; 3 the ledger is incomplete and --allow-incomplete was not given.

Dependencies: Python 3.11+ and PyYAML. Nothing else.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import war_room_lib as wr  # noqa: E402
import war_room_lint as wl  # noqa: E402

UNRECORDED = "[unverified: not recorded]"


# --------------------------------------------------------------------------- helpers
def has_author_text(account: Any) -> bool:
    """True when the author wrote anything at all for this block."""
    if not isinstance(account, dict):
        return False
    for key in ("meant_to_do", "why_this_way"):
        if (account.get(key) or "").strip():
            return True
    return any(str(a).strip() for a in (account.get("assumptions_carried") or []))


def repo_relative(path: Path) -> str:
    """A path a reader can paste, never an absolute one (WR-Q6, AC-D2).

    The work order is read inside the repository the war room ran from, so the ledger is
    cited relative to that repository's root. Outside a repository -- a test in a
    temporary directory, say -- the last two components are used, which is still a
    relative string. Nothing here ever emits a machine-specific prefix.
    """
    resolved = Path(path).expanduser().resolve()
    for parent in resolved.parents:
        if (parent / ".git").exists():
            return resolved.relative_to(parent).as_posix()
    parts = resolved.parts
    if "war_rooms" in parts:
        i = parts.index("war_rooms")
        start = i - 1 if i > 0 and parts[i - 1] == "records" else i
        return Path(*parts[start:]).as_posix()
    return Path(resolved.parent.name, resolved.name).as_posix()


def date_of(value: Any) -> str:
    """The calendar date out of an ISO 8601 timestamp, for a human-facing table cell."""
    text = str(value or "").strip()
    return text.split("T", 1)[0] if text else ""


# --------------------------------------------------------------------------- reconcile
def reconcile(data: dict) -> tuple[dict, list[str], list[str]]:
    """Returns (data, needs_agent_block_ids, notes). Predictions are never touched."""
    export: list[dict] = []
    opens: list[dict] = []
    needs_agent: list[str] = []
    notes: list[str] = []

    for b in data.get("blocks", []):
        bid = b.get("block_id")
        disp = b.get("disposition")
        pred = b.get("prediction") or {}
        acct = b.get("author_account") or {}
        wrote = has_author_text(acct)

        # An endorsement only counts when it satisfies WL-05: `endorsed_prediction: true`
        # with `disposition: confirmed` and no author text. Anything else is a lint failure
        # upstream, and reading it as agreement here would convert a broken record into a
        # confirmed one. A `confirmed` block that carries neither the endorsement flag nor
        # an account is not agreement either -- it is an answer nobody explained, and it
        # goes to the agent below rather than being read as a match.
        endorsed_ok = ((disp == "confirmed") and not wrote
                       and bool(b.get("endorsed_prediction")))

        # --- assumption export -------------------------------------------------
        # WR-Q8: confirming a prediction confirms the assumptions inside it, and batch
        # confirmation of a fast-forwarded block is a confirmation. Without this, a
        # fully-endorsed review produces an empty export and the session's primary
        # downstream product is silently lost.
        for a in pred.get("assumptions") or []:
            export.append({
                "block_id": bid,
                "assumption": a,
                "stated_by": "agent",
                "confirmed": bool(endorsed_ok),
            })
        for a in acct.get("assumptions_carried") or []:
            export.append({
                "block_id": bid,
                "assumption": a,
                "stated_by": "author",
                "confirmed": True,
            })

        # --- divergence --------------------------------------------------------
        div = b.get("divergence") or {"match": None, "type": None, "detail": None}
        if endorsed_ok:
            div = {
                "match": True,
                "type": "none",
                "detail": "Author endorsed the recorded prediction without amendment.",
            }
        elif b.get("discussed") and div.get("match") is None:
            # Every discussed block that is not an endorsement needs a classification
            # before the ledger can be called reconciled (WR-P4): an unset divergence is
            # not a match, and WL-09 checks exactly this once `session.reconciled` is set.
            # That covers a block whose author wrote an account -- comparing it to the
            # prediction is judgment, not string handling -- and equally a block answered
            # with a disposition and nothing else, which is silence rather than agreement.
            needs_agent.append(str(bid))
        b["divergence"] = div

        # --- open questions ----------------------------------------------------
        if disp == "unresolved":
            opens.append({
                "block_id": bid,
                "question": acct.get("meant_to_do") or b.get("title", ""),
                "blocked_on": acct.get("why_this_way") or UNRECORDED,
            })

        if b.get("flag_for_followup"):
            notes.append(f"{bid} flagged for follow-up")
        # WR-A3/A4: read the persisted flags; never recompute them here.
        if b.get("drift"):
            note = f"{bid} hash drift - decision may not describe current code"
            if b.get("drift_after_disposition"):
                note += " (changed AFTER its disposition: WR-A4 regression signal)"
            notes.append(note)
        elif b.get("relocated_from"):
            old = b.get("relocated_from")
            notes.append(f"{bid} re-anchored by hash from lines {old[0]}-{old[1]} "
                         f"to {(b.get('lines') or ['?', '?'])[0]}-"
                         f"{(b.get('lines') or ['?', '?'])[1]} (WR-A2, not drift)")

    data["assumption_export"] = export
    data["open_questions"] = opens
    return data, needs_agent, notes


def mark_reconciled(data: dict) -> None:
    """Set `session.reconciled` and append the history entry, at most once (D10)."""
    session = data.setdefault("session", {})
    history = session.setdefault("history", [])
    if not any(isinstance(h, dict) and h.get("event") == "reconcile" for h in history):
        history.append({"event": "reconcile", "at": wr.utc_now()})
    if not session.get("reconciled"):
        session["reconciled"] = history[-1].get("at") if history else wr.utc_now()


# --------------------------------------------------------------------------- work order
def _item_rows(b: dict, script_path: str, status: str, blocked_on: str | None) -> list[str]:
    ln = b.get("lines") or [0, 0]
    rows = [
        "| Field | Value |",
        "|---|---|",
        f"| **Status** | {status} |",
        f"| **File** | `{script_path}` |",
        f"| **Lines** | {ln[0]}-{ln[1]} |",
        f"| **Block** | {b.get('block_id')} |",
        f"| **Block sha256** | `{b.get('sha256', '')}` |",
        f"| **Decided by** | {b.get('reviewer') or '—'} |",
        f"| **Decided on** | {date_of(b.get('answered_at')) or '—'} |",
    ]
    if blocked_on is not None:
        rows.append(f"| **Blocked on** | {blocked_on} |")
    return rows


def render_work_order(data: dict, ledger_path: Path) -> str:
    """The template in `Infrastructure/templates/war-room-work-order.md`, filled (WR-O5)."""
    sess = data.get("session") or {}
    script = data.get("script") or {}
    script_path = script.get("path", "")
    blocks = [b for b in data.get("blocks", []) if isinstance(b, dict)]

    actionable = [b for b in blocks if b.get("disposition") == "needs-change"]
    blocked = [b for b in blocks if b.get("disposition") == "unresolved"]
    skipped = [b for b in blocks
               if b.get("disposition") in ("confirmed", "misread-by-agent")]
    reviewers = sorted({str(b.get("reviewer")) for b in blocks if b.get("reviewer")})
    opens = {str(q.get("block_id")): q for q in (data.get("open_questions") or [])
             if isinstance(q, dict)}

    out = [
        f"# Work Order — {script_path or '(unknown script)'}",
        "",
        f"**Source ledger:** `{repo_relative(ledger_path)}`",
        f"**Session date:** {sess.get('created', '')}",
        f"**Reviewers:** {', '.join(reviewers) or '(none recorded)'}",
        f"**Items:** {len(actionable)} actionable, {len(blocked)} blocked",
        "",
        "> Generated from a war-room walkthrough. Every item traces to a recorded decision.",
        "> Do not implement a change that is not listed here; raise it back to the ledger instead.",
        "> A `blocked` item is listed so the open question is visible, not so it can be guessed at.",
        "",
        "---",
        "",
    ]
    if not actionable and not blocked:
        out += ["No `needs-change` or `unresolved` blocks were recorded. Nothing to "
                "implement and nothing outstanding.", "", "---", ""]

    number = 0
    wo_ids: dict[str, str] = {}

    for b in actionable:
        number += 1
        wo_id = f"WO-{number:03d}"
        wo_ids[str(b.get("block_id"))] = wo_id
        acct = b.get("author_account") or {}
        pred = b.get("prediction") or {}
        out += [
            f"## {wo_id} — {b.get('title', '')}",
            "",
            *_item_rows(b, script_path, "actionable", None),
            "",
            "**Current behavior**",
            pred.get("what_it_does", "") or UNRECORDED,
            "",
            "**Intended behavior**",
            acct.get("meant_to_do", "") or UNRECORDED,
            "",
            "**Why it is this way**",
            acct.get("why_this_way", "") or UNRECORDED,
            "",
            "**Change**",
            (b.get("divergence") or {}).get("detail") or UNRECORDED,
            "",
            "**Downstream effects**",
            UNRECORDED,
            "",
            "**Verification**",
            UNRECORDED,
            "",
            "---",
            "",
        ]

    for b in blocked:
        number += 1
        wo_id = f"WO-{number:03d}"
        bid = str(b.get("block_id"))
        wo_ids[bid] = wo_id
        acct = b.get("author_account") or {}
        pred = b.get("prediction") or {}
        blocked_on = (opens.get(bid) or {}).get("blocked_on") or UNRECORDED
        out += [
            f"## {wo_id} — {b.get('title', '')}",
            "",
            *_item_rows(b, script_path, "blocked", blocked_on),
            "",
            "**Current behavior**",
            pred.get("what_it_does", "") or UNRECORDED,
            "",
            "**Intended behavior**",
            "<unresolved — do not implement until the blocker clears>",
            "",
            "**Why it is this way**",
            acct.get("why_this_way", "") or UNRECORDED,
            "",
            "**Blocked on**",
            blocked_on,
            "",
            "Until that clears, this item is a record of an open question, not an "
            "instruction.",
            "",
            "---",
            "",
        ]

    if blocked:
        out += ["## Blocked Items", "",
                "| ID | Block | Blocked on |", "|---|---|---|"]
        for b in blocked:
            bid = str(b.get("block_id"))
            out.append(f"| {wo_ids[bid]} | {bid} | "
                       f"{(opens.get(bid) or {}).get('blocked_on') or UNRECORDED} |")
        out.append("")

    out += ["## Not In Scope", "",
            "Examined during the session and deliberately left alone:", "",
            "| Block | Disposition | Note |", "|---|---|---|"]
    if skipped:
        for b in skipped:
            if b.get("disposition") != "confirmed":
                note = "Code is correct; the agent's reading was wrong."
            elif b.get("endorsed_prediction"):
                note = "Author endorsed the reading; no change needed."
            else:
                note = "Author confirmed without endorsing or explaining the reading."
            out.append(f"| {b.get('block_id')} | {b.get('disposition')} | {note} |")
    else:
        out.append("| — | — | None recorded. |")
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- lint gate
def _print_lint(result: "wl.LintResult", stream=sys.stderr) -> None:
    for warning in result.warnings:
        print(f"warning: {warning.line()}", file=stream)


def _fail_lint(result: "wl.LintResult", heading: str) -> None:
    print(heading)
    for failure in result.failures:
        print(f"  {failure.line()}")


# --------------------------------------------------------------------------- entry point
def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="war_room_reconcile.py",
        description="Reconcile a war-room ledger and render its work order.",
    )
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--project-root", default=None,
                    help="Root of the reviewed project (the directory holding PROJECT.md). "
                         "Without it, the nearest PROJECT.md root above the working "
                         "directory is used, and only when its basename matches project.id "
                         "(WR-A5). Lint's source-reading checks are skipped with a warning "
                         "when the root cannot be resolved.")
    ap.add_argument("--write", action="store_true",
                    help="Apply changes (default: dry run)")
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="Reconcile a ledger that still has blocks without a disposition")
    args = ap.parse_args(list(argv) if argv is not None else None)

    path = Path(args.ledger).expanduser().resolve()
    if not path.is_file():
        print(f"No ledger at {path}")
        return 2
    # The lock is held from the load to the post-write lint, so the app server or a prep
    # command cannot save in between and have its change overwritten (D-15).
    try:
        with wr.locked_ledger(path):
            return _run(args, path)
    except wr.WarRoomError as exc:
        print(f"ERROR: {exc}")
        return 1


def _run(args: argparse.Namespace, path: Path) -> int:
    root = Path(args.project_root) if args.project_root else None
    data = wr.load_ledger(path)
    if root is not None:
        # D1/WR-A5: prep and the server refuse a root whose basename names a different
        # project; reconcile refuses it too, rather than reconciling against other code.
        try:
            wr.resolve_project_root(root, data)
        except wr.WarRoomError as exc:
            print(f"ERROR: {exc}")
            return 2

    # D7: lint gates the write. A ledger that does not lint is not reconciled at all --
    # promoting assumptions out of a broken record would launder the breakage.
    pre = wl.lint(data, root)
    _print_lint(pre)
    if not pre.ok:
        _fail_lint(pre, f"LINT REFUSED this ledger ({len(pre.failures)} failure(s)); "
                        f"nothing was written:")
        return 1

    blocks = [b for b in data.get("blocks", []) if isinstance(b, dict)]
    undone = [str(b.get("block_id")) for b in blocks if not b.get("disposition")]
    if undone and not args.allow_incomplete:
        print(f"Ledger      : {path}")
        print(f"INCOMPLETE: {len(undone)} blocks without a disposition")
        print("  " + ", ".join(undone[:12]) + (" ..." if len(undone) > 12 else ""))
        print("Reconcile refuses a partial walkthrough. Finish it, or pass "
              "--allow-incomplete to reconcile what is recorded so far.")
        return 3

    data, needs_agent, notes = reconcile(data)
    work_order = render_work_order(data, path)

    print(f"Ledger      : {path}")
    print(f"Blocks      : {len(blocks)}  ({len(undone)} without a disposition)")
    if undone:
        print(f"  incomplete: {', '.join(undone[:12])}"
              f"{' ...' if len(undone) > 12 else ''}")
    print(f"Assumptions : {len(data['assumption_export'])} exported "
          f"({sum(1 for a in data['assumption_export'] if a['confirmed'])} confirmed)")
    print(f"Open qs     : {len(data['open_questions'])}")
    print(f"Work order  : "
          f"{sum(1 for b in blocks if b.get('disposition') == 'needs-change')} actionable, "
          f"{sum(1 for b in blocks if b.get('disposition') == 'unresolved')} blocked")
    for n in notes:
        print(f"  note: {n}")

    if needs_agent:
        print(f"\nNEEDS AGENT JUDGMENT ({len(needs_agent)} discussed blocks without a "
              f"divergence classification):")
        print("  " + ", ".join(needs_agent))
        print("  session.reconciled stays unset until every one of them carries a "
              "divergence classification.")
    elif not undone:
        print("\nNo agent judgment required - every block was endorsed or left "
              "undiscussed.")

    if not args.write:
        print("\n(dry run - pass --write to apply)")
        return 0

    if not needs_agent:
        mark_reconciled(data)

    wr.save_ledger(path, data)
    work_order_path = path.parent / "work-order.md"
    work_order_path.write_bytes(work_order.encode("utf-8"))
    print(f"\nWritten: {path.name}, {work_order_path.name}")

    # The bytes on disk are what everything downstream reads, so lint those, not the
    # in-memory object they came from.
    post = wl.lint(wr.load_ledger(path), root)
    _print_lint(post)
    if not post.ok:
        _fail_lint(post, f"POST-WRITE LINT FAILED ({len(post.failures)} failure(s)): the "
                         f"ledger on disk does not pass lint. Fix it before anything reads "
                         f"it:")
        return 1
    print("Post-write lint: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
