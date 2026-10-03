#!/usr/bin/env python3
"""Local war-room review app.

Serves a single-page block-by-block review UI on localhost and writes answers straight
back into `ledger.yaml`. The agent is deliberately absent while this runs: it wrote the
predictions during prep, and it reads the completed ledger afterwards in the reconcile
pass. Nothing here talks to a model.

That absence is the point. A rule telling an agent not to soften its reading when the
author pushes back is weaker than an architecture where the agent is not present to
soften anything. The prediction is rendered read-only; the author's fields start empty.

Every mutating request runs load -> mutate -> recompute drift -> lint -> save while
holding one lock, so two answers saved at the same moment cannot read the same ledger and
write back over each other (F12), and nothing reaches disk that
`Infrastructure/scripts/war_room_lint.py` rejects (D7). A lint failure is returned to the
browser with its `WL-` codes and persists nothing.

The server -- not the client -- is authoritative on endorsement (WR-Q7): it clears
`endorsed_prediction` when the author typed anything, and refuses an endorsement paired
with any disposition other than `confirmed`.

The loopback bind, the `Origin`/`Host` check on the bound port, the security headers and
CSP (no inline script: the app's behavior lives in `war_room_app/app.js`), the body cap,
and the port-in-use message come from the shared kit (`localapp.server`).

Usage:
    python Infrastructure/scripts/war_room_server.py --ledger <path-to-ledger.yaml> \
        [--project-root <dir>] [--port 8765] [--no-browser]

A browser opens unless `--no-browser` is passed, as for the review board, once the server is
serving; not under CI or on Linux with no display. `--open` is still accepted and changes
nothing. `--port 0` asks the OS for a free port.

The reviewed source is resolved against the *reviewed project* -- `--project-root`, or the
nearest `PROJECT.md` root whose basename matches the ledger's `project.id` -- never against
the working directory. The project root is never stored in the ledger (WR-A5, D2), and a
root whose basename does not match the ledger's `project.id` is a startup error rather than
a session recorded against the wrong project.

Dependencies: Python 3.11+ and PyYAML. Both are already required by this repository's
validators; nothing new is introduced.
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import war_room_lib as wr  # noqa: E402
import war_room_lint as wl  # noqa: E402
from localapp.server import LoopbackHandler, LoopbackServer, PortInUseError  # noqa: E402

APP_DIR = Path(__file__).resolve().parent / "war_room_app"
APP_FILES = {"/": (APP_DIR / "index.html", "text/html; charset=utf-8"),
             "/index.html": (APP_DIR / "index.html", "text/html; charset=utf-8"),
             "/app.js": (APP_DIR / "app.js", "text/javascript; charset=utf-8")}
DISPOSITIONS = wr.DISPOSITIONS
REVIEWER_ROLES = wr.REVIEWER_ROLES

# One lock for the whole request, not just the write. The old version locked the save
# alone, which still let two requests load the same ledger and discard one another's
# answer between load and save (F12).
_lock = threading.RLock()


# --------------------------------------------------------------------------- ledger io
class Ledger:
    """One request's view of the ledger: loaded fresh, mutated, linted, then saved."""

    def __init__(self, path: Path, project_root: Path):
        self.path = Path(path)
        self.project_root = Path(project_root)
        self.data = wr.load_ledger(self.path)

    # -- source ------------------------------------------------------------------
    def source_lines(self) -> list[str] | None:
        try:
            return wr.wr_a1_lines(wr.resolve_script(self.project_root, self.data))
        except (wr.WarRoomError, OSError, UnicodeDecodeError):
            return None

    # -- persistence -------------------------------------------------------------
    def commit(self) -> dict:
        """D11 then D7: persist drift for every block, lint, and only then write."""
        lines = self.source_lines()
        if lines is not None:
            wr.recompute_drift(self.data, lines)
        result = wl.lint(self.data, self.project_root)
        if not result.ok:
            return {
                "ok": False,
                "error": "lint refused this write; nothing was saved",
                "lint_failures": [f.as_dict() for f in result.failures],
                "lint_lines": [f.line() for f in result.failures],
            }
        wr.save_ledger(self.path, self.data)
        return {"ok": True}

    def block(self, block_id: str) -> dict | None:
        return wr.find_block(self.data, block_id)

    # -- session bookkeeping -----------------------------------------------------
    def register_reviewer(self, reviewer: str, role: str) -> None:
        """D12: `session.reviewers[]` keeps `{id, role}`; an unknown id is appended."""
        session = self.data.setdefault("session", {})
        reviewers = session.setdefault("reviewers", [])
        for item in reviewers:
            if isinstance(item, dict) and str(item.get("id")) == reviewer:
                return
        reviewers.append({"id": reviewer, "role": role})

    def note_walkthrough(self, reviewer: str, at: str) -> None:
        """D10/WR-O7: one `walkthrough` entry per reviewer per UTC date, no more."""
        session = self.data.setdefault("session", {})
        history = session.setdefault("history", [])
        day = at[:10]
        for item in history:
            if (isinstance(item, dict) and item.get("event") == "walkthrough"
                    and str(item.get("by")) == reviewer
                    and str(item.get("at", ""))[:10] == day):
                return
        history.append({"event": "walkthrough", "at": at, "by": reviewer})


def _reviewer_of(payload: dict) -> tuple[str, str, str | None]:
    reviewer = str(payload.get("reviewer") or "").strip()
    role = str(payload.get("reviewer_role") or "").strip()
    if not reviewer:
        return "", "", "reviewer is required on every answer (WR-Q9)"
    if role not in REVIEWER_ROLES:
        return reviewer, role, (f"reviewer_role must be one of "
                                f"{', '.join(REVIEWER_ROLES)}")
    return reviewer, role, None


# --------------------------------------------------------------------------- payloads
def build_state(led: Ledger) -> dict:
    """Everything the UI needs: the block map, the walkthrough, and the drift banner."""
    blocks = []
    all_lines = led.source_lines()
    for b in led.data.get("blocks", []):
        lines_ = b.get("lines") or [1, 1]
        start, end = int(lines_[0]), int(lines_[1])
        text = "\n".join(all_lines[start - 1:end]) if all_lines else ""
        pred = b.get("prediction") or {}
        acct = b.get("author_account") or {}
        blocks.append({
            "block_id": b.get("block_id"),
            "lines": [start, end],
            "title": b.get("title", ""),
            "density": b.get("density", ""),
            "discussed": bool(b.get("discussed")),
            "disposition": b.get("disposition") or "",
            "flagged": bool(b.get("flag_for_followup")),
            # WR-A3/A4: the banner reads the persisted flags, so the console, the ledger,
            # and the rendered report cannot say three different things.
            "drift": bool(b.get("drift")),
            "drift_after_disposition": bool(b.get("drift_after_disposition")),
            "relocated_from": b.get("relocated_from"),
            "endorsed_prediction": bool(b.get("endorsed_prediction")),
            "answered_at": b.get("answered_at") or "",
            "reviewer": b.get("reviewer") or "",
            "dissent": b.get("dissent") or [],
            "source": text,
            "prediction": {
                "what_it_does": pred.get("what_it_does", ""),
                "inferred_intent": pred.get("inferred_intent", ""),
                "assumptions": pred.get("assumptions") or [],
                "confidence": pred.get("confidence", ""),
                "inherited_from": pred.get("inherited_from"),
                "merged_from": pred.get("merged_from"),
            },
            "author": {
                "meant_to_do": (acct or {}).get("meant_to_do", "") or "",
                "why_this_way": (acct or {}).get("why_this_way", "") or "",
                "assumptions_carried": (acct or {}).get("assumptions_carried") or [],
            },
        })
    sess = led.data.get("session") or {}
    script = led.data.get("script") or {}
    return {
        "script": {
            "path": script.get("path", ""),
            "language": script.get("language", ""),
            "line_count": script.get("line_count"),
        },
        "project": {"id": (led.data.get("project") or {}).get("id", "")},
        "session": {
            "created": str(sess.get("created", "")),
            "mode": sess.get("mode", "ordered"),
            "prep_completed": str(sess.get("prep_completed", "")),
            "reviewers": sess.get("reviewers") or [],
        },
        "dispositions": list(DISPOSITIONS),
        "reviewer_roles": list(REVIEWER_ROLES),
        # Spec M27 / D5: the block map is shown before the first unanswered block, in
        # every mode, for as long as any block still lacks a disposition.
        "needs_block_map": any(not b.get("disposition") for b in led.data.get("blocks", [])),
        "blocks": blocks,
    }


def apply_answer(led: Ledger, payload: dict) -> dict:
    """`POST /api/answer` (D13). The server decides endorsement; the client only asks."""
    b = led.block(payload.get("block_id", ""))
    if b is None:
        return {"ok": False, "error": "unknown block_id"}

    disp = payload.get("disposition") or ""
    if disp and disp not in DISPOSITIONS:
        return {"ok": False, "error": f"disposition must be one of {DISPOSITIONS}"}

    reviewer, role, problem = _reviewer_of(payload)
    if problem:
        return {"ok": False, "error": problem}

    author = payload.get("author") or {}
    meant = (author.get("meant_to_do") or "").strip()
    why = (author.get("why_this_way") or "").strip()
    carried = [a.strip() for a in (author.get("assumptions_carried") or []) if a.strip()]
    has_text = bool(meant or why or carried)

    endorsed = bool(payload.get("endorsed_prediction"))
    # The client clears this too, but only cosmetically: an endorsement means the author
    # wrote nothing to compare the prediction against, so text wins and the endorsement
    # goes (WR-Q7). A stale checkbox must never turn an author's account into an
    # endorsement that reconcile then reads as agreement.
    if has_text:
        endorsed = False
    if endorsed and disp != "confirmed":
        return {"ok": False,
                "error": f"an endorsement is a confirmation: disposition must be "
                         f"'confirmed', not {disp or 'unset'!r} (WR-Q7). Nothing was saved."}

    if has_text:
        b["author_account"] = {
            "meant_to_do": meant,
            "why_this_way": why,
            "assumptions_carried": carried,
        }
    elif endorsed:
        # WR-Q7: "the prediction is correct and I have nothing to add" is a legitimate
        # outcome -- making the author retype an accurate reading is bad design. But it
        # is recorded as a deliberate act, so a careful confirmation and an unread block
        # are not identical in the ledger.
        b["author_account"] = None
    # Every answer that arrives here was given on the block's own screen, so the block
    # was discussed (WR-C3) -- whether the author typed an account, endorsed the
    # prediction, or simply marked it `misread-by-agent` and moved on. `discussed: false`
    # means one thing only: batch-confirmed without being opened, which
    # `/api/fast-forward` and nothing else writes. Leaving a silent `needs-change` at
    # `false` made reconcile skip it, kept WL-09 quiet, and had the renderer label it
    # fast-forwarded -- three artifacts agreeing on a state that never happened.
    b["discussed"] = True

    now = wr.utc_now()
    b["endorsed_prediction"] = endorsed
    b["disposition"] = disp or None
    # WR-Q9: the reviewer is whoever answered here, never the id prep happened to write.
    b["reviewer"] = reviewer
    b["answered_at"] = now
    b["flag_for_followup"] = bool(payload.get("flagged"))

    # Divergence is NOT set here. A batch reconcile pass compares the recorded prediction
    # against the recorded account after the walkthrough (spec M25) so that nothing
    # classifies a disagreement while the author is still in the room.
    b.setdefault("divergence", {"match": None, "type": None, "detail": None})

    led.register_reviewer(reviewer, role)
    led.note_walkthrough(reviewer, now)
    return led.commit()


def apply_fast_forward(led: Ledger, payload: dict) -> dict:
    """`POST /api/fast-forward` (D13): batch confirmation from the block map (WR-C2..C5).

    A fast-forwarded block is recorded, not skipped (WR-C3), and batch confirmation is an
    endorsement of the recorded prediction and its assumptions (WR-Q8). WR-C4 is enforced
    here and not only in the selector, because a selector is a suggestion and this is the
    gate: high density and low confidence are exactly the blocks that need a human.
    """
    mode = str((led.data.get("session") or {}).get("mode") or "ordered")
    if mode != "fast-forward":
        # WR-C2: fast-forward is opt-in and per-session. `session.mode` is written only by
        # `war_room_prep.py skeleton --mode fast-forward`, so a batch posted against an
        # `ordered` ledger is a request the session never opted into, not a screen action.
        return {"ok": False,
                "error": f"batch confirmation needs session.mode 'fast-forward'; this "
                         f"ledger is mode {mode!r}. Fast-forward is opt-in and per-session "
                         f"(WR-C2), written only by `war_room_prep.py skeleton --mode "
                         f"fast-forward`. Nothing was saved."}

    block_ids = [str(x) for x in (payload.get("block_ids") or [])]
    if not block_ids:
        return {"ok": False, "error": "block_ids is empty; nothing to confirm"}

    reviewer, role, problem = _reviewer_of(payload)
    if problem:
        return {"ok": False, "error": problem}

    targets, refusals = [], []
    for bid in block_ids:
        b = led.block(bid)
        if b is None:
            refusals.append(f"{bid}: unknown block_id")
            continue
        if b.get("disposition"):
            refusals.append(f"{bid}: already carries disposition "
                            f"{b['disposition']!r}; re-open it in the walkthrough instead")
        elif b.get("density") == "high":
            refusals.append(f"{bid}: density is high; a high-assumption-density block is "
                            f"never fast-forwarded (WR-C4)")
        elif (b.get("prediction") or {}).get("confidence") == "low":
            refusals.append(f"{bid}: prediction confidence is low; a low-confidence block "
                            f"is never fast-forwarded (WR-C4)")
        else:
            targets.append(b)
    if refusals:
        # All or nothing: a partial batch would leave the author guessing which of the
        # blocks they selected were actually recorded.
        return {"ok": False, "error": "refused: " + "; ".join(refusals),
                "refusals": refusals}

    now = wr.utc_now()
    for b in targets:
        b["disposition"] = "confirmed"
        b["discussed"] = False
        b["endorsed_prediction"] = True
        b["author_account"] = None
        b["reviewer"] = reviewer
        b["answered_at"] = now
        b.setdefault("divergence", {"match": None, "type": None, "detail": None})

    led.register_reviewer(reviewer, role)
    led.note_walkthrough(reviewer, now)
    out = led.commit()
    if out.get("ok"):
        out["confirmed"] = [b.get("block_id") for b in targets]
    return out


def apply_segmentation(led: Ledger, payload: dict) -> dict:
    """Merge or split blocks (WR-S5), through the shared library and nothing else.

    A range and a hash edited by hand disagree the moment either is wrong, so both
    operations go through `war_room_lib`, which the prep script's `merge` and `split`
    commands call too (D6).
    """
    op = payload.get("op")
    lines = led.source_lines()
    if lines is None:
        return {"ok": False, "error": "cannot re-segment: the reviewed source did not "
                                      "resolve, so the affected blocks cannot be rehashed"}
    by = str(payload.get("reviewer") or "").strip() or None
    try:
        if op == "merge":
            wr.merge_blocks(led.data, str(payload.get("block_id") or ""), lines, by=by)
        elif op == "split":
            wr.split_block(led.data, str(payload.get("block_id") or ""),
                           int(payload.get("at_line") or 0), lines, by=by)
        else:
            return {"ok": False, "error": "op must be merge or split"}
    except wr.WarRoomError as exc:
        return {"ok": False, "error": str(exc)}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": f"bad split line: {exc}"}
    return led.commit()


# --------------------------------------------------------------------------- server
ROUTES = {"/api/answer": apply_answer, "/api/fast-forward": apply_fast_forward,
          "/api/segment": apply_segmentation}


def make_handler(ledger_path: Path, project_root: Path):
    class Handler(LoopbackHandler):
        server_version = "WarRoom/1"
        static = APP_FILES

        def handle_get(self, route: str) -> None:
            if route != "/api/state":
                return self.refuse(404, "not found")
            with _lock:
                state = build_state(Ledger(ledger_path, project_root))
            return self.send_json(state)

        def handle_post(self, route: str, body: bytes) -> None:
            handler = ROUTES.get(route)
            if handler is None:
                return self.refuse(404, "not found")
            payload = self.json_object(body)
            if payload is None:
                return None
            try:
                # One lock around load, mutate, drift, lint, and save: two answers saved at
                # the same moment must not read the same ledger and overwrite each other.
                # The file lock also keeps out a prep or reconcile CLI writing this ledger.
                with _lock, wr.locked_ledger(ledger_path):
                    result = handler(Ledger(ledger_path, project_root), payload)
            except Exception as exc:  # surface, never silently lose an answer
                return self.refuse(500, str(exc))
            return self.send_json(result)

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="war_room_server.py",
                                 description="Local war-room review app.")
    ap.add_argument("--ledger", required=True, help="Path to ledger.yaml")
    ap.add_argument("--project-root", default=None,
                    help="Root of the reviewed project (the directory holding PROJECT.md)")
    ap.add_argument("--port", type=int, default=8765, help="Port; 0 picks a free one")
    ap.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    ap.add_argument("--open", action="store_true",
                    help="Accepted for older instructions; a browser opens by default")
    args = ap.parse_args(argv)

    path = Path(args.ledger).expanduser().resolve()
    if not path.is_file():
        return print(f"No ledger at {path}") or 2
    missing = sorted({f.name for f, _ in APP_FILES.values() if not f.is_file()})
    if missing:
        return print(f"Missing app files in {APP_DIR}: {', '.join(missing)}") or 2

    probe = wr.load_ledger(path)
    if not (probe.get("session") or {}).get("prep_completed"):
        # Spec M4 / WR-P1: without prep there are no predictions to commit to, so the
        # walkthrough would be a conversation with nothing recorded before it.
        print(f"ERROR: {path} has no session.prep_completed, so prep is not complete: "
              f"`war_room_prep.py finalize` has not run on this ledger. "
              f"Run it before opening the app.")
        return 2
    try:
        # D1: never record a session against the wrong project; an explicit root is checked.
        root = wr.resolve_project_root(args.project_root, probe)
        source = wr.resolve_script(root, probe)
    except wr.WarRoomError as exc:
        return print(f"ERROR: {exc}") or 2

    blocks = probe.get("blocks") or []
    done = sum(1 for b in blocks if isinstance(b, dict) and b.get("disposition"))
    try:
        # Bind first, then read the port back: `--port 0` asks the OS for a free one, and
        # the origin check compares against the port actually served.
        srv = LoopbackServer(args.port, make_handler(path, root))
    except PortInUseError as exc:
        return print(f"ERROR: {exc.strerror}", flush=True) or 2

    print(f"War room: {path.name}  ({done}/{len(blocks)} blocks dispositioned)", flush=True)
    print(f"Reviewed source: {source}", flush=True)
    # Both spellings are printed because the origin check accepts both and a reader who
    # opens the other one should not have to guess whether it will work.
    print(f"Serving {srv.url}   (Ctrl-C to stop)", flush=True)
    print(f"     or http://localhost:{srv.port}/", flush=True)
    if not args.no_browser:
        note = srv.open_browser_when_serving()  # after serving starts, never blocking it
        if note:
            print(note, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Ledger saved after every answer.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
