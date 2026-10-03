#!/usr/bin/env python3
"""Local review board.

Serves the board app on loopback and records each reviewer's statuses and notes in
`feedback.yaml`, the reviewer lane. The agent is not part of this: it reads the recorded
events at `round open`, and it answers through the ledger, which this server only reads.
Nothing here talks to a model.

Every write runs load -> append -> append-only check -> lint -> atomic save while holding
one lock, so two notes saved at the same moment cannot read the same file and overwrite each
other (RB-S4), and nothing reaches disk that `Infrastructure/scripts/review_board_lint.py`
rejects. The server, not the client, assigns each event's `id`, `seq`, `at`, and
`approved_hash` (RB-L6); a request that names any of them is refused.

The board shows each item's snapshot from the latest closed round, never the live file in
`output/`, and serves only snapshots the ledger registers, looked up by item id and round
(RB-S2). The loopback bind, the `Origin`/`Host` check on the bound port (RB-S1), the
security headers and CSP, and the body cap come from the shared kit (`localapp.server`).
When the board fails lint at startup, or `feedback.yaml` cannot be written, it serves
read-only and the app says why.

Usage:
    python Infrastructure/scripts/review_board_server.py --board <board dir> \
        [--project-root <dir>] [--port 8766] [--no-browser]

`--port 0` asks the OS for a free port; the bound address is printed on startup. A port
already in use exits 2 with a message. A browser opens once the server is serving, unless
`--no-browser` is passed, CI is set, or Linux has no display.

Dependencies: Python 3.11+ and PyYAML.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_board_lib as rb  # noqa: E402
import review_board_lint as rl  # noqa: E402
from localapp.server import LoopbackHandler, LoopbackServer, PortInUseError  # noqa: E402

APP_DIR = Path(__file__).resolve().parent / "review_board_app"
APP_FILES = {"/": (APP_DIR / "index.html", "text/html; charset=utf-8"),
             "/index.html": (APP_DIR / "index.html", "text/html; charset=utf-8"),
             "/app.js": (APP_DIR / "app.js", "text/javascript; charset=utf-8")}
CLIENT_FIELDS = frozenset({"item", "by", "kind", "status", "text"})
SERVER_FIELDS = frozenset({"id", "seq", "at", "approved_hash", "source", "source_id"})
MAX_TEXT_CHARS = 8000
IMG_RE = re.compile(r"^/img/([a-z0-9][a-z0-9-]*)/(\d{1,4})$")

# One lock for a whole request, not only the save: two notes posted at the same moment must
# not load the same event list and write back over each other.
_lock = threading.RLock()


class Board:
    """The three files, loaded fresh for each request."""

    def __init__(self, board_dir: Path, root: Path):
        self.dir = board_dir
        self.root = root
        self.board = rb.load_board(board_dir)
        self.feedback = rb.load_feedback(board_dir)
        self.ledger = rb.load_ledger(board_dir)


def _response_for(ledger: dict, item_id: str, n: int | None) -> dict | None:
    r = rb.find_round(ledger, n) if n else None
    for resp in (r or {}).get("responses") or []:
        if isinstance(resp, dict) and resp.get("item") == item_id:
            return {"round": n, "state": resp.get("state"), "text": resp.get("text")}
    return None


def _what_changed(ledger: dict, item_id: str, n: int | None) -> str | None:
    r = rb.find_round(ledger, n) if n else None
    for change in (r or {}).get("changes") or []:
        if isinstance(change, dict) and change.get("item") == item_id:
            return change.get("what_changed")
    return None


def _reviewer_view(b: Board, item_id: str, render: dict | None) -> dict:
    """Each reviewer's folded status, and whether their approval matches the render."""
    evs = rb.events(b.feedback)
    out = {}
    for rid, status in rb.statuses(b.board, b.feedback, item_id).items():
        current = False
        if status == "approved":
            latest = rb.latest_status_event(evs, item_id, rid) or {}
            current = bool(render and latest.get("approved_hash") == render.get("hash"))
        out[rid] = {"status": status, "approval_current": current}
    return out


def build_state(b: Board, writable: bool, read_only_reasons: list[str]) -> dict:
    closed = rb.latest_closed_round(b.ledger)
    current = rb.open_round(b.ledger)
    meta = b.board.get("board") or {}
    items = []
    for item in rb.items(b.board):
        iid = item["id"]
        render = rb.current_render(b.ledger, iid)
        previous = rb.previous_render(b.ledger, iid)
        tags = []
        if render and render.get("classification") in ("new", "changed"):
            tags.append(render["classification"])
        if item.get("frozen"):
            tags.append("frozen")
        events = [{k: e.get(k) for k in ("id", "seq", "by", "at", "kind", "status", "text")}
                  for e in rb.events(b.feedback) if e.get("item") == iid]
        items.append({
            "id": iid, "title": item.get("title"), "group": item.get("group"),
            "frozen": bool(item.get("frozen")), "tags": tags,
            "render": ({"round": render["round"], "hash": render.get("hash"),
                        "url": f"/img/{iid}/{render['round']}"} if render else None),
            "previous": ({"round": previous["round"],
                          "url": f"/img/{iid}/{previous['round']}"} if previous else None),
            "measurements": (render or {}).get("measurements") or {},
            "what_changed": _what_changed(b.ledger, iid, closed),
            "response": _response_for(b.ledger, iid, closed),
            "reviewers": _reviewer_view(b, iid, render),
            "owner_approval": rb.owner_approval(b.board, b.feedback, b.ledger, iid),
            "events": events,
        })
    return {
        "board": {"slug": b.dir.name, "title": meta.get("title"), "medium": meta.get("medium"),
                  "project_id": rb.board_project_id(b.board)},
        "writable": writable, "read_only_reasons": read_only_reasons,
        "owner": rb.owner_id(b.board),
        "reviewers": [{"id": r.get("id"), "role": r.get("role"), "name": r.get("name")}
                      for r in rb.reviewers(b.board, include_retired=False)],
        "vocab": {"statuses": list(rb.STATUSES), "note_kinds": list(rb.NOTE_KINDS)},
        "round": {"latest_closed": closed, "open": current["n"] if current else None},
        "groups": sorted({str(i.get("group")) for i in rb.items(b.board)}),
        "items": items,
    }


def apply_event(b: Board, payload: dict) -> tuple[int, dict]:
    """POST /api/event. Returns (HTTP status, body). Saves only when everything passes."""
    supplied = set(payload)
    forbidden = sorted(supplied & SERVER_FIELDS)
    if forbidden:
        return 400, {"ok": False, "error": f"the server assigns {', '.join(forbidden)} "
                                           "(RB-L6); do not send them"}
    unknown = sorted(supplied - CLIENT_FIELDS)
    if unknown:
        return 400, {"ok": False, "error": f"unknown fields {', '.join(unknown)}"}
    text = payload.get("text")
    if text is not None and (not isinstance(text, str) or len(text) > MAX_TEXT_CHARS):
        return 400, {"ok": False, "error": f"text must be a string of at most "
                                           f"{MAX_TEXT_CHARS} characters"}
    before = copy.deepcopy(rb.events(b.feedback))
    try:
        event = rb.append_event(b.feedback, b.board, b.ledger,
                                item=str(payload.get("item") or ""),
                                by=str(payload.get("by") or ""),
                                kind=str(payload.get("kind") or ""),
                                status=payload.get("status"), text=text)
    except rb.ReviewBoardError as exc:
        return 400, {"ok": False, "error": str(exc)}
    result = rl.lint(b.board, b.feedback, b.ledger, project_root=b.root, at="write",
                     prev_events=before)
    if not result.ok:
        return 422, {"ok": False, "error": "the save would fail lint; nothing was saved",
                     "codes": sorted(result.codes),
                     "failures": [f.line() for f in result.failures]}
    rb.save_feedback(b.dir, b.feedback)
    return 200, {"ok": True, "event": event}


def startup_check(board_dir: Path, root: Path) -> list[str]:
    """Reasons to serve read-only; empty when the board may be written."""
    reasons = []
    try:
        result = rl.lint_board_dir(board_dir, root, "lint")
        reasons += [f"lint: {f.line()}" for f in result.failures]
    except rb.ReviewBoardError as exc:
        reasons.append(str(exc))
    feedback = board_dir / rb.FEEDBACK_FILE
    if not os.access(feedback, os.W_OK) or not os.access(board_dir, os.W_OK):
        reasons.append(f"{feedback} is not writable")
    return reasons


def make_handler(board_dir: Path, root: Path, read_only_reasons: list[str]):
    class Handler(LoopbackHandler):
        server_version = "ReviewBoard/1"
        static = APP_FILES

        def handle_get(self, route: str) -> None:
            if route == "/api/state":
                try:
                    with _lock:
                        b = Board(board_dir, root)
                        state = build_state(b, not read_only_reasons, read_only_reasons)
                except rb.ReviewBoardError as exc:
                    return self.refuse(500, str(exc))
                return self.send_json(state)
            m = IMG_RE.match(route)
            if m:
                return self._image(m.group(1), int(m.group(2)))
            return self.refuse(404, "not found")

        def _image(self, item_id: str, n: int) -> None:
            """RB-S2: only a registered snapshot from a closed round, looked up by id."""
            with _lock:
                ledger = rb.load_ledger(board_dir)
            r = rb.find_round(ledger, n)
            render = rb.render_for(ledger, item_id, n)
            if not r or not r.get("closed_at") or not render or not render.get("snapshot"):
                return self.refuse(404, "not found")
            renders_dir = (board_dir / rb.RENDERS_DIR).resolve()
            target = (board_dir / str(render["snapshot"])).resolve()
            if not target.is_relative_to(renders_dir) or target.suffix != ".png" \
                    or not target.is_file():
                return self.refuse(404, "not found")
            return self.send_bytes(200, target.read_bytes(), "image/png")

        def handle_post(self, route: str, body: bytes) -> None:
            if route != "/api/event":
                return self.refuse(404, "not found")
            if read_only_reasons:
                return self.refuse(403, "the board is read-only", reasons=read_only_reasons)
            payload = self.json_object(body)
            if payload is None:
                return None
            try:
                with _lock:
                    code, reply = apply_event(Board(board_dir, root), payload)
            except rb.ReviewBoardError as exc:
                return self.refuse(500, str(exc))
            except OSError as exc:
                # A file another program holds open, a full disk: say so to the reviewer
                # rather than dropping the connection. The atomic save left nothing behind.
                return self.refuse(500, f"could not save: {exc}")
            return self.send_json(reply, code)

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="review_board_server.py",
                                 description="Serve the local review board on loopback.")
    ap.add_argument("--board", required=True, help="The board directory")
    ap.add_argument("--project-root", default=None,
                    help="Root of the reviewed project (the directory holding PROJECT.md)")
    ap.add_argument("--port", type=int, default=8766, help="Port; 0 picks a free one")
    ap.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    args = ap.parse_args(argv)

    board_dir = Path(args.board).expanduser().resolve()
    try:
        board = rb.load_board(board_dir)
        rb.check_board_dir(board_dir, board)
        root = rb.resolve_project_root(args.project_root, board)
        rb.load_feedback(board_dir)
        rb.load_ledger(board_dir)
    except rb.ReviewBoardError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 2
    missing = sorted({f.name for f, _ in APP_FILES.values() if not f.is_file()})
    if missing:
        print(f"ERROR: missing app files in {APP_DIR}: {', '.join(missing)}", flush=True)
        return 2
    reasons = startup_check(board_dir, root)

    try:
        srv = LoopbackServer(args.port, make_handler(board_dir, root, reasons))
    except PortInUseError as exc:
        print(f"ERROR: {exc.strerror}", flush=True)
        return 2
    url = srv.url
    print(f"Review board {board_dir.name} ready: {url}", flush=True)
    if reasons:
        print("Serving READ-ONLY:", flush=True)
        for reason in reasons:
            print(f"  {reason}", flush=True)
    if not args.no_browser:
        note = srv.open_browser_when_serving()  # after serving starts, never blocking it
        if note:
            print(note, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
