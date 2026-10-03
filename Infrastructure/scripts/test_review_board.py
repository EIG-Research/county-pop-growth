#!/usr/bin/env python3
"""Test suite for the review board.

Runs the review-board tooling (`review_board_lib.py`, `review_board_lint.py`,
`review_board_measure.py`, and, as later phases land, the CLI and the board server) against
synthetic PNG and SVG files generated at test time, with no model in the loop and no network.
`python3 Infrastructure/scripts/test_review_board.py` from anywhere.

Cases, one `PASS` line each. The numbers are fixed; cases not yet built are absent.

     1  Full path                   init -> three rounds -> done, notes posted to the server
     2  Concurrency                 sixty simultaneous notes all persist, seq 1..60
     3  Fold, events, and config    RB-L4/L5 fold and approval currency; RL-01..04, 13..15
     4  Stale approval              RB-L5 through the API: stale after a change, then renewed
     5  Content hash stability      RB-R5: metadata, compression, and IDAT splits ignored
     6  Close refusals              RL-06..13 one at a time; changed files; waivers
     7  Append-only against HEAD    RL-05 against git HEAD and against the loaded version
     8  Server security             RB-S1..S4: paths, origins, server fields, read-only
     9  Measurement                 RB-M2/M3: text floor, palette, contrast, not-measured
    10  Roots and render failures   M6 root checks; RB-R4 missing PNG; failing commands
    11  Retirement and display      retired items and reviewers; the app's display rules
    12  Shared local-app kit        `test_localapp.py`, the suite of the kit the board uses

Case 6 posts reviewer events through `review_board_lib.append_event`, the function the
server calls, because it tests the ledger lane rather than HTTP. Every server is started on
an ephemeral port (`--port 0`, read back from its startup line) and stopped in a `finally`.

What the suite guarantees about itself:

  - **It writes nothing it does not own.** Every file goes to one temporary directory that
    is removed at the end. The fixtures directory is read-only: its digest is printed
    before and after, and the two must match.
  - **It touches no network.** `socket.socket.connect` refuses any address that is not
    loopback while the suite runs. The guard is self-tested.
  - **It is fast.** Wall-clock time is printed, and anything over 120 seconds fails.

Exit codes: 0 every case passed; 1 a case failed; 2 the environment is unusable.

Dependencies: Python 3.11+ and PyYAML. Git is needed for case 7, which is skipped with a
reason when git is absent.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import copy
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zlib
from pathlib import Path
from typing import Any, Callable

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

try:
    import yaml  # noqa: F401
except ImportError:  # pragma: no cover - environment check
    print("PyYAML is required: python3 -m pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)

import review_board_lib as rb  # noqa: E402
import review_board_lint as rl  # noqa: E402
import review_board_measure as rm  # noqa: E402
from localapp import testkit  # noqa: E402
from localapp.testkit import (CaseFailure, check, check_eq, install_network_guard,  # noqa: E402
                              self_test_network_guard, tree_digest)

TIME_LIMIT_SECONDS = 120
FIXTURES = SCRIPTS / "review_board_fixtures"
CLI = SCRIPTS / "review_board.py"
SERVER = SCRIPTS / "review_board_server.py"
APP_DIR = SCRIPTS / "review_board_app"
FIXTURE_SLUG = "proj-fig--demo"
_READY_RE = re.compile(r"ready: http://127\.0\.0\.1:(\d+)/")


# --------------------------------------------------------------------------- assertions
def expect_error(fn: Callable[[], Any], fragment: str, message: str) -> None:
    try:
        fn()
    except rb.ReviewBoardError as exc:
        check(fragment in str(exc), f"{message}: error {str(exc)!r} lacks {fragment!r}")
        return
    raise CaseFailure(f"{message}: no ReviewBoardError raised")


# --------------------------------------------------------------------------- files
def _rmtree(path: Path) -> None:
    def onexc(func, target, _exc):  # read-only git objects on Windows
        os.chmod(target, stat.S_IWRITE)
        func(target)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=onexc)
    else:  # pragma: no cover - 3.11
        shutil.rmtree(path, onerror=lambda f, p, e: onexc(f, p, e))


def _chunk(ctype: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + ctype + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))


def png_bytes(width: int = 12, height: int = 8, *,
              pixel: Callable[[int, int], tuple[int, int, int]] | None = None,
              level: int = 6, dpi: int | None = None, extra: tuple = (),
              split_idat: bool = False) -> bytes:
    """An 8-bit RGB PNG built with the standard library."""
    pixel = pixel or (lambda x, y: (x * 20 % 256, y * 30 % 256, 128))
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width))
                   for y in range(height))
    parts = [rb.PNG_SIGNATURE,
             _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))]
    if dpi:
        ppm = int(round(dpi / 0.0254))
        parts.append(_chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1)))
    for ctype, data in extra:
        parts.append(_chunk(ctype, data))
    compressed = zlib.compress(raw, level)
    if split_idat:
        mid = len(compressed) // 2
        parts += [_chunk(b"IDAT", compressed[:mid]), _chunk(b"IDAT", compressed[mid:])]
    else:
        parts.append(_chunk(b"IDAT", compressed))
    parts.append(_chunk(b"IEND", b""))
    return b"".join(parts)


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                    encoding="utf-8", newline="\n")


def make_project(parent: Path, name: str) -> Path:
    root = parent / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "PROJECT.md").write_text(
        "# Project Profile\n\nSynthetic project for the review-board test suite.\n",
        encoding="utf-8", newline="\n")
    return root


def board_dict(project_id: str, board_id: str = "demo", *,
               item_ids: tuple[str, ...] = ("fig-a", "fig-b"),
               frozen: tuple[str, ...] = ()) -> dict:
    return {
        "schema_version": 1,
        "project": {"id": project_id},
        "board": {"id": board_id, "title": "Demo board", "medium": "print",
                  "fixture": True},
        "reviewers": [
            {"id": "owner1", "role": "owner", "name": "Owner One"},
            {"id": "rev1", "role": "reviewer", "name": "Reviewer One"},
        ],
        "render": {"argv": ["{python}", "code/make_figs.py"],
                   "expected_runtime": "under a second", "timeout_seconds": 60},
        "items": [
            {"id": iid, "title": f"Figure {iid}", "group": "main",
             "sources": [f"code/{iid}.py"], "render": f"output/figures/{iid}.png",
             "svg": None, "frozen": iid in frozen}
            for iid in item_ids
        ],
    }


def make_board_dir(runner: Path, board: dict) -> Path:
    slug = rb.slug_for(board["project"]["id"], board["board"]["id"])
    board_dir = runner / "records" / "review_boards" / slug
    write_yaml(board_dir / rb.BOARD_FILE, board)
    rb.save_feedback(board_dir, rb.new_feedback(board))
    rb.save_ledger(board_dir, rb.new_ledger(board))
    return board_dir


def fake_hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def add_closed_round(ledger: dict, feedback: dict, hashes: dict[str, str]) -> int:
    """A closed round with a render per item, as `render` and `round close` will write it."""
    n = len(rb.rounds(ledger)) + 1
    now = rb.utc_now()
    ledger["rounds"].append({
        "n": n, "opened_at": now, "cursor_seq": rb.max_seq(feedback), "cursor_at": now,
        "listed": [], "carried": [], "stop_gate": {"verdict": "proceed",
                                                    "reason": "test", "approved_on": None},
        "triage": [], "changes": [], "responses": [], "waivers": [],
        "changed_files": {"available": False, "outside_sources": []}, "closed_at": now,
    })
    for iid, h in hashes.items():
        entry = rb.ledger_item(ledger, iid)
        if entry is None:
            entry = {"id": iid, "renders": []}
            ledger["items"].append(entry)
        prev = rb.render_for(ledger, iid, n - 1)
        entry["renders"].append({
            "round": n, "hash": h, "snapshot": rb.snapshot_rel(n, iid, "png"),
            "svg_snapshot": None,
            "classification": "new" if prev is None else (
                "unchanged" if prev["hash"] == h else "changed"),
            "measurements": {},
        })
    return n


def codes_of(board: Any, feedback: dict | None, ledger: dict | None,
             root: Path | None = None, **kw: Any) -> set[str]:
    return rl.lint(board, feedback, ledger, project_root=root, **kw).codes


# --------------------------------------------------------------------------- CLI helpers
def setup_fixture(work: Path, git: bool = False) -> tuple[Path, Path]:
    """A writable copy of the fixture project and board. The fixtures are never touched."""
    root = work / "proj-fig"
    shutil.copytree(FIXTURES / "proj-fig", root,
                    ignore=shutil.ignore_patterns("__pycache__", "output"))
    board_dir = work / "runner" / "records" / "review_boards" / FIXTURE_SLUG
    shutil.copytree(FIXTURES / "boards" / FIXTURE_SLUG, board_dir)
    if git:
        _git(root, "init", "-q")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "fixture project")
    return root, board_dir


class Run:
    def __init__(self, code: int, out: str):
        self.code, self.out = code, out


def cli(board_dir: Path, root: Path | None, *args: Any, expect: int | None = 0,
        cwd: Path | None = None) -> Run:
    """Run `review_board.py` as a subprocess, exactly as the workflow does."""
    argv = [sys.executable, str(CLI), *map(str, args), "--board", str(board_dir)]
    if root is not None:
        argv += ["--project-root", str(root)]
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    out = proc.stdout + proc.stderr
    if expect is not None and proc.returncode != expect:
        raise CaseFailure(f"`{' '.join(map(str, args))}` exited {proc.returncode}, "
                          f"expected {expect}:\n{out}")
    return Run(proc.returncode, out)


def record(work: Path, board_dir: Path, root: Path, data: dict, expect: int = 0) -> Run:
    path = work / f"record-{time.monotonic_ns()}.yaml"
    write_yaml(path, data)
    return cli(board_dir, root, "record", "--from", path, expect=expect)


def post(board_dir: Path, **kw: Any) -> dict:
    """Append one reviewer event through the library function the board server calls."""
    board = rb.load_board(board_dir)
    feedback, ledger = rb.load_feedback(board_dir), rb.load_ledger(board_dir)
    event = rb.append_event(feedback, board, ledger, **kw)
    rb.save_feedback(board_dir, feedback)
    return event


def edit_json(path: Path, mutate: Callable[[dict], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def set_figure(root: Path, fig: str, **kw: Any) -> None:
    edit_json(root / "code" / "params.json", lambda d: d["figures"][fig].update(kw))


def set_params(root: Path, **kw: Any) -> None:
    edit_json(root / "code" / "params.json", lambda d: d.update(kw))


def set_theme(root: Path, **kw: Any) -> None:
    edit_json(root / "code" / "theme.json", lambda d: d.update(kw))


GATE = {"stop_gate": {"verdict": "proceed",
                      "reason": "All changes are inside the declared item sources."}}


def first_round(work: Path, board_dir: Path, root: Path) -> None:
    cli(board_dir, root, "init")
    cli(board_dir, root, "round", "open")
    cli(board_dir, root, "render")
    record(work, board_dir, root, {"stop_gate": {"verdict": "proceed",
                                                 "reason": "Round 1 is the initial render."}})
    cli(board_dir, root, "round", "close")


def round_of(board_dir: Path, n: int) -> dict:
    found = rb.find_round(rb.load_ledger(board_dir), n)
    check(found is not None, f"round {n} exists")
    return found  # type: ignore[return-value]


def classification(board_dir: Path, item: str, n: int) -> str | None:
    return (rb.render_for(rb.load_ledger(board_dir), item, n) or {}).get("classification")


# --------------------------------------------------------------------------- server helpers
class Client(testkit.Client):
    """The kit's loopback client, plus the board's own requests."""

    def __init__(self, port: int):
        super().__init__(port)
        self.output: list[str] = []          # the server's stdout and stderr, drained

    def state(self) -> dict:
        status, _, body = self.request("GET", "/api/state")
        check_eq(status, 200, "GET /api/state")
        return json.loads(body)

    def post(self, payload: Any, origin: str | None = "default",
             headers: dict | None = None) -> tuple[int, dict]:
        sent = {"Content-Type": "application/json"}
        if origin == "default":
            sent["Origin"] = self.origin
        elif origin is not None:
            sent["Origin"] = origin
        sent.update(headers or {})
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        status, _, data = self.request("POST", "/api/event", body, sent)
        return status, json.loads(data or b"{}")

    def event(self, **payload: Any) -> dict:
        status, reply = self.post(payload)
        check(status == 200 and reply.get("ok"), f"server accepted {payload}: {status} {reply}")
        return reply["event"]

    def item(self, item_id: str) -> dict:
        return next(i for i in self.state()["items"] if i["id"] == item_id)


@contextlib.contextmanager
def server(board_dir: Path, root: Path):
    """Start the board server on a free port; always stop it."""
    proc = subprocess.Popen(
        [sys.executable, str(SERVER), "--board", str(board_dir), "--project-root", str(root),
         "--port", "0", "--no-browser"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        lines: list[str] = []
        port = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = proc.stdout.readline() if proc.stdout else ""
            if not line:
                if proc.poll() is not None:
                    break
                continue
            lines.append(line)
            m = _READY_RE.search(line)
            if m:
                port = int(m.group(1))
                break
        if port is None:
            raise CaseFailure("the board server did not start:\n" + "".join(lines))
        # Keep draining the server's output. Without this, a server that prints (a
        # traceback, say) fills the pipe and blocks, and every client then times out.
        def drain() -> None:
            for line in proc.stdout or ():
                lines.append(line)
        threading.Thread(target=drain, daemon=True).start()
        client = Client(port)
        client.output = lines
        yield client
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        if proc.stdout:
            proc.stdout.close()


# --------------------------------------------------------------------------- case 1
def case_1_full_path(work: Path) -> str | None:
    git = shutil.which("git") is not None
    root, bd = setup_fixture(work, git=git)
    out = cli(bd, root, "init").out
    check("Initialized board proj-fig--demo" in out, "init reports the board")

    cli(bd, root, "round", "open")
    out = cli(bd, root, "render").out
    check("expected runtime: under a second" in out and "timeout 60s" in out,
          "render states its cost before running (RB-R3)")
    check("3 new" in out, "round 1 renders three new items")
    led = rb.load_ledger(bd)
    for item in ("fig-bars", "fig-shares", "fig-table"):
        r1 = rb.render_for(led, item, 1)
        check(r1 is not None and rb.HASH_RE.match(r1["hash"]), f"{item} has a round-1 hash")
        check((bd / r1["snapshot"]).is_file(), f"{item} snapshot copied (RB-R6)")
    bars = rb.render_for(led, "fig-bars", 1)["measurements"]
    check_eq((bars["text_floor"]["result"], bars["palette"]["result"], bars["dpi"]),
             ("pass", "pass", 300), "fig-bars measured from its SVG")
    table = rb.render_for(led, "fig-table", 1)["measurements"]
    check_eq(table["text_floor"]["result"], "not-measured", "fig-table has no SVG (RB-M3)")
    cli(bd, root, "round", "close", expect=1)                       # no stop gate yet
    record(work, bd, root, {"stop_gate": {"verdict": "proceed",
                                          "reason": "Round 1 is the initial render."}})
    check("Closed round 1" in cli(bd, root, "round", "close").out, "round 1 closes")
    check("no round has closed" not in cli(bd, root, "status", expect=1).out,
          "status after round 1 is not done, for approvals only")

    with server(bd, root) as client:
        return _case_1_rounds(work, root, bd, git, client)


def _case_1_rounds(work: Path, root: Path, bd: Path, git: bool, client: Client) -> str | None:
    """Rounds 2 and 3, with every reviewer event posted to the board server."""
    state = client.state()
    check_eq((state["round"], state["writable"], state["owner"]),
             ({"latest_closed": 1, "open": None}, True, "owner1"), "server state after round 1")
    ap = client.event(item="fig-shares", by="owner1", kind="status", status="approved")
    cr = client.event(item="fig-bars", by="owner1", kind="change-request",
              text="Use the brand teal for these bars.")
    fr = client.event(item="fig-table", by="owner1", kind="change-request",
              text="Make the table bars taller.")
    nr = client.event(item="fig-shares", by="rev1", kind="change-request",
              text="Could these be sorted | largest first?")
    check_eq(ap["approved_hash"],
             rb.render_for(rb.load_ledger(bd), "fig-shares", 1)["hash"],
             "an approval carries the hash of the closed round's render")

    out = cli(bd, root, "round", "open").out
    check("3 new events, 0 carried" in out, "round 2 lists the three notes, not the status")
    check("not owner: surface" in out, "a non-owner note is marked for surfacing")
    r2 = round_of(bd, 2)
    check_eq((r2["listed"], r2["carried"], r2["cursor_seq"]),
             ([cr["id"], fr["id"], nr["id"]], [], 4), "round 2 cursor and listing")
    plan = (bd / "rounds" / "round-02.md").read_text(encoding="utf-8")
    check(cr["id"] in plan and "rev1 (not owner)" in plan and "sorted \\| largest" in plan,
          "the round plan's triage block lists the events, escaped for Markdown")
    check("### fig-bars" in plan and "{{" not in plan, "the approach section is seeded")

    set_figure(root, "fig-bars", color=[2, 65, 64])
    out = cli(bd, root, "render").out
    check("fig-bars: changed" in out and "fig-shares: unchanged" in out
          and "fig-table: unchanged" in out,
          "only fig-bars changed, although every PNG was rewritten with a new timestamp")
    out = cli(bd, root, "round", "close", expect=1).out
    check("RL-06" in out and "stays open" in out, "close refuses untriaged events")
    check(round_of(bd, 2)["closed_at"] is None, "a refused close saves nothing")

    record(work, bd, root, {
        **GATE,
        "triage": [
            {"event": cr["id"], "decision": "do"},
            {"event": fr["id"], "decision": "decline",
             "reason": "fig-table is frozen (RB-R7); the recommendation is in its response."},
            {"event": nr["id"], "decision": "surface",
             "reason": "From rev1, not the owner; shown to the owner (RB-T5)."},
        ],
        "changes": [{"item": "fig-bars", "what_changed": "Bars recolored to brand teal."}],
        "responses": [
            {"item": "fig-bars", "state": "changed", "text": "Recolored to eig_teal_900."},
            {"item": "fig-table", "state": "declined",
             "text": "Frozen; recommended taller bars for the next edition."},
            {"item": "fig-shares", "state": "still-open",
             "text": "rev1 asked for sorting; waiting on the owner."},
        ],
    })
    out = cli(bd, root, "round", "close").out
    check("Closed round 2" in out and "1 changed this round" in out, "round 2 closes")
    bars, table = client.item("fig-bars"), client.item("fig-table")
    check_eq((bars["tags"], bars["render"]["round"], bars["previous"]["round"]),
             (["changed"], 2, 1), "the API shows round 2 with round 1 to compare")
    check_eq((bars["what_changed"], bars["response"]["state"], table["response"]["state"]),
             ("Bars recolored to brand teal.", "changed", "declined"),
             "what changed and the responses reach the board")
    check_eq(table["tags"], ["frozen"], "fig-table is tagged frozen and unchanged")
    check(any(e["text"] == "Could these be sorted | largest first?"
              for e in client.item("fig-shares")["events"]), "note text reaches the board verbatim")
    check(rb.owner_approval(rb.load_board(bd), rb.load_feedback(bd), rb.load_ledger(bd),
                            "fig-shares")["current"],
          "fig-shares' approval stays current: its render did not change")

    client.event(item="fig-bars", by="owner1", kind="status", status="approved")
    client.event(item="fig-table", by="owner1", kind="status", status="approved")
    out = cli(bd, root, "status", expect=1).out
    check(f"{nr['id']} is still surface" in out, "a surfaced note keeps the board open")

    out = cli(bd, root, "round", "open").out
    check("0 new events, 1 carried" in out, "the surfaced note carries into round 3 (RB-T8)")
    check_eq(round_of(bd, 3)["carried"], [nr["id"]], "round 3 carries the surfaced note")
    record(work, bd, root, {
        **GATE,
        "triage": [{"event": nr["id"], "decision": "decline",
                    "reason": "The owner declined in chat: the order follows the brief.",
                    "owner_confirmed_on": "2026-09-24"}],
        "responses": [{"item": "fig-shares", "state": "answered",
                       "text": "Kept the brief's order, per the owner."}],
    })
    check("3 unchanged" in cli(bd, root, "render").out, "round 3 changes nothing")
    cli(bd, root, "round", "close")

    out = cli(bd, root, "status").out
    check("DONE" in out and "NOT DONE" not in out, "all approvals current: done (RB-D1)")
    status = json.loads(cli(bd, root, "status", "--json").out)
    check(status["done"] and not status["reasons"], "status --json agrees")
    cli(bd, root, "summary")
    summary = (bd / rb.SUMMARY_FILE).read_text(encoding="utf-8")
    check("**Done**" in summary and "Do not edit by hand" in summary, "board.md written")
    plan3 = (bd / "rounds" / "round-03.md").read_text(encoding="utf-8")
    check("| decline |" in plan3, "round plans show decisions from the ledger")
    check("PASS" in cli(bd, root, "lint").out, "the finished board lints clean")
    check_eq(len(rb.events(rb.load_feedback(bd))), 6,
             "the CLI never wrote to feedback.yaml (RB-L2)")
    if git:
        for n in (2, 3):
            check_eq(round_of(bd, n)["changed_files"],
                     {"available": True, "outside_sources": []},
                     f"round {n}: params.json is a declared source (P11)")
        return None
    return "git not found: changed-files checks skipped"


# --------------------------------------------------------------------------- case 6
def case_6_close_refusals(work: Path) -> str | None:
    git = shutil.which("git") is not None
    root, bd = setup_fixture(work, git=git)
    first_round(work, bd, root)
    e1 = post(bd, item="fig-bars", by="owner1", kind="change-request", text="Brighter bars.")
    e2 = post(bd, item="fig-table", by="owner1", kind="comment", text="Fine as is.")
    e3 = post(bd, item="fig-shares", by="rev1", kind="change-request", text="Thicker bars.")
    cli(bd, root, "round", "open")
    set_figure(root, "fig-bars", color=[23, 111, 150])
    set_theme(root, title_px=6.0)
    out = cli(bd, root, "render").out
    check("fig-bars: changed (fails text_floor)" in out, "render reports failing checks")

    baseline = {
        **GATE,
        "triage": [
            {"event": e1["id"], "decision": "do"},
            {"event": e2["id"], "decision": "do"},
            {"event": e3["id"], "decision": "surface", "reason": "Not from the owner."},
        ],
        "changes": [{"item": "fig-bars", "what_changed": "Bars recolored to eig_cyan_700."}],
        "responses": [
            {"item": "fig-bars", "state": "changed", "text": "Brighter brand cyan."},
            {"item": "fig-table", "state": "answered", "text": "Thanks; no change."},
            {"item": "fig-shares", "state": "still-open", "text": "Waiting on the owner."},
        ],
    }
    bad = record(work, bd, root, {"triage": [{"event": e1["id"], "decision": "maybe"}]},
                 expect=1)
    check("Nothing was recorded" in bad.out, "record refuses a decision outside the set")
    out = record(work, bd, root, baseline).out
    check("Still needed" not in out, "the baseline record is complete")
    board, fb, led = rb.load_board(bd), rb.load_feedback(bd), rb.load_ledger(bd)
    check(rl.lint(board, fb, led, project_root=root, at="close").ok,
          "the baseline passes the close lint")

    def close_codes(mutate: Callable[[dict], None]) -> set[str]:
        copy_led = copy.deepcopy(led)
        mutate(copy_led["rounds"][1])
        return rl.lint(board, fb, copy_led, project_root=root, at="close").codes

    def triage_of(r: dict, eid: str) -> dict:
        return next(t for t in r["triage"] if t["event"] == eid)

    matrix: list[tuple[set[str], str, Callable[[dict], None]]] = [
        ({"RL-06"}, "untriaged event",
         lambda r: r["triage"].pop(1)),
        ({"RL-06"}, "duplicate triage",
         lambda r: r["triage"].append(dict(r["triage"][0]))),
        ({"RL-06"}, "decision outside the set",
         lambda r: triage_of(r, e2["id"]).update(decision="maybe")),
        ({"RL-06", "RL-09"}, "an invalid decision does not cover a changed item",
         lambda r: triage_of(r, e1["id"]).update(decision="maybe")),
        ({"RL-06"}, "listed differs from feedback.yaml",
         lambda r: r["listed"].remove(e1["id"])),
        ({"RL-06"}, "triage for an event not in the round",
         lambda r: r["triage"].append({"event": "ev-00099", "decision": "do"})),
        ({"RL-07"}, "non-owner note acted on without confirmation",
         lambda r: triage_of(r, e3["id"]).update(decision="do")),
        (set(), "non-owner note acted on with confirmation",
         lambda r: triage_of(r, e3["id"]).update(decision="do", owner_confirmed_on="2026-09-24")),
        ({"RL-08"}, "surface without a reason",
         lambda r: triage_of(r, e3["id"]).update(reason=None)),
        ({"RL-09"}, "changed item with no covering decision",
         lambda r: triage_of(r, e1["id"]).update(decision="question", reason="Which blue?")),
        (set(), "the same change, explained",
         lambda r: (triage_of(r, e1["id"]).update(decision="question", reason="Which blue?"),
                    r["changes"][0].update(explanation="Shared palette fix, approved."))),
        ({"RL-11"}, "changed item without what_changed",
         lambda r: r["changes"].clear()),
        ({"RL-11"}, "item with events but no response",
         lambda r: r["responses"].pop(1)),
        ({"RL-11"}, "response state outside the set",
         lambda r: r["responses"][0].update(state="done")),
        ({"RL-11"}, "response without text",
         lambda r: r["responses"][0].update(text="")),
        ({"RL-12"}, "stop verdict without approval",
         lambda r: r["stop_gate"].update(verdict="stop")),
        (set(), "stop verdict with approval",
         lambda r: r["stop_gate"].update(verdict="stop", approved_on="2026-09-24")),
        ({"RL-12"}, "no stop gate",
         lambda r: r.update(stop_gate=None)),
    ]
    for expected, label, mutate in matrix:
        check_eq(close_codes(mutate), expected, f"close lint: {label}")

    frozen_led = copy.deepcopy(led)
    rb.render_for(frozen_led, "fig-table", 2)["classification"] = "changed"
    frozen_led["rounds"][1]["changes"].append({"item": "fig-table", "what_changed": "x",
                                               "explanation": None})
    check_eq(rl.lint(board, fb, frozen_led, project_root=root, at="close").codes, {"RL-10"},
             "close lint: frozen item changed")
    missing_led = copy.deepcopy(led)
    entry = rb.ledger_item(missing_led, "fig-shares")
    entry["renders"] = [x for x in entry["renders"] if x["round"] != 2]
    check_eq(rl.lint(board, fb, missing_led, project_root=root, at="close").codes, {"RL-13"},
             "close lint: an item without a render this round")

    set_figure(root, "fig-table", values=[9, 9, 9])
    cli(bd, root, "render")
    out = cli(bd, root, "round", "close", expect=1).out
    check("RL-10" in out and round_of(bd, 2)["closed_at"] is None,
          "a changed frozen item keeps the round open, end to end")
    set_figure(root, "fig-table", values=[6, 6, 6])
    check("fig-table: unchanged" in cli(bd, root, "render").out, "reverting the cause")

    out = cli(bd, root, "round", "close").out
    check("Closed round 2" in out, "the round closes once the cause is reverted")
    status = cli(bd, root, "status", expect=1).out
    check("fig-bars: text_floor fails and is not waived" in status
          and "fig-shares: text_floor fails" in status, "status names unwaived failures")
    if git:
        check("code/theme.json" in out, "close names the shared file it changed (RB-C4)")
        check_eq(round_of(bd, 2)["changed_files"],
                 {"available": True, "outside_sources": ["code/theme.json"]},
                 "changed_files records it")
        plan = (bd / "rounds" / "round-02.md").read_text(encoding="utf-8")
        check("- `code/theme.json`" in plan, "the round plan lists it")

    cli(bd, root, "round", "open")
    record(work, bd, root, {
        **GATE,
        "triage": [{"event": e3["id"], "decision": "surface",
                    "reason": "Still waiting on the owner."}],
        "responses": [{"item": "fig-shares", "state": "still-open",
                       "text": "Waiting on the owner."}],
        "waivers": [{"item": i, "check": "text_floor",
                     "reason": "Owner decision 2026-09-24: small titles are a test value."}
                    for i in ("fig-bars", "fig-shares")],
    })
    cli(bd, root, "render")
    cli(bd, root, "round", "close")
    status = cli(bd, root, "status", expect=1).out
    check("text_floor fails" not in status, "waived failures stop blocking (RB-M4)")
    check(f"{e3['id']} is still surface" in status, "the surfaced note still blocks")
    return None if git else "git not found: changed-files checks skipped"


# --------------------------------------------------------------------------- case 10
def case_10_roots_and_failures(work: Path) -> None:
    root, bd = setup_fixture(work)
    other = make_project(work, "other-proj")
    out = cli(bd, other, "init", expect=2).out
    check("does not match" in out, "a root whose basename is not project.id is refused (M6)")
    out = cli(bd, work / "runner", "init", expect=2).out
    check("does not contain PROJECT.md" in out, "a root without PROJECT.md is refused")

    bad_paths = work / "bad" / "runner" / FIXTURE_SLUG
    shutil.copytree(bd, bad_paths)
    board = rb.load_yaml(bad_paths / rb.BOARD_FILE)
    board["items"][0]["sources"] = ["../elsewhere.py"]
    write_yaml(bad_paths / rb.BOARD_FILE, board)
    check("RL-14" in cli(bad_paths, root, "init", expect=1).out,
          "init refuses a path that escapes the project")
    misnamed = work / "misnamed" / "wrong-name"
    shutil.copytree(bd, misnamed)
    check("should be 'proj-fig--demo'" in cli(misnamed, root, "init", expect=2).out,
          "a board directory not named <project id>--<board id> is refused (M1)")

    cli(bd, root, "init")
    check("already exist" in cli(bd, root, "init", expect=1).out, "init runs once")
    check("No round is open" in cli(bd, root, "render", expect=1).out,
          "render belongs to a round")
    check("no round has closed yet" in cli(bd, root, "status", expect=1).out,
          "status before any round")
    cli(bd, root, "round", "open")
    check("still open" in cli(bd, root, "round", "open", expect=1).out,
          "one open round at a time (RL-13)")

    set_params(root, fail=True)
    out = cli(bd, root, "render", expect=1).out
    check("exited 3" in out and "Nothing was recorded" in out
          and "synthetic render failure" in out, "a failing command records nothing")
    check_eq(rb.load_ledger(bd)["items"], [], "no render entries after the failure")
    set_params(root, fail=False)
    set_figure(root, "fig-shares", skip=True)
    out = cli(bd, root, "render", expect=1).out
    check("wrote no PNG for: fig-shares" in out, "a missing PNG fails the render (RB-R4)")
    check_eq(rb.load_ledger(bd)["items"], [], "no render entries after a missing PNG")
    set_figure(root, "fig-shares", skip=False)
    check("3 new" in cli(bd, root, "render").out, "render succeeds once fixed")

    run = cli(bd, None, "status", expect=1, cwd=root)
    check("ERROR" not in run.out, "without --project-root, the matching cwd root is used")
    nested = root / "code"
    check("ERROR" not in cli(bd, None, "status", expect=1, cwd=nested).out,
          "the root is found by walking up from a subdirectory")
    elsewhere = make_project(work, "unrelated")
    check("records project.id 'proj-fig'" in
          cli(bd, None, "status", expect=2, cwd=elsewhere).out,
          "a cwd inside another project is refused")


# --------------------------------------------------------------------------- case 3
def case_3_fold_events_config(work: Path) -> None:
    root = make_project(work, "proj-x")
    board = board_dict("proj-x")
    feedback, ledger = rb.new_feedback(board), rb.new_ledger(board)
    ha, hb, ha2 = fake_hash("a1"), fake_hash("b1"), fake_hash("a2")

    expect_error(lambda: rb.append_event(feedback, board, ledger, item="fig-a", by="owner1",
                                         kind="status", status="approved"),
                 "nothing to approve", "approval before any closed round")
    add_closed_round(ledger, feedback, {"fig-a": ha, "fig-b": hb})

    e1 = rb.append_event(feedback, board, ledger, item="fig-a", by="owner1",
                         kind="status", status="approved")
    check_eq((e1["id"], e1["seq"], e1["approved_hash"]), ("ev-00001", 1, ha),
             "server-assigned id, seq, and approved_hash (RB-L6)")
    evs = rb.events(feedback)
    check_eq(rb.fold_status(evs, "fig-a", "owner1"), "approved", "approval folds")
    check(rb.owner_approval(board, feedback, ledger, "fig-a")["current"],
          "a fresh approval is current")

    rb.append_event(feedback, board, ledger, item="fig-a", by="owner1", kind="comment",
                    text="This works.")
    check_eq(rb.fold_status(rb.events(feedback), "fig-a", "owner1"), "approved",
             "a comment does not change status")
    rb.append_event(feedback, board, ledger, item="fig-a", by="owner1",
                    kind="change-request", text="Move the 2019 label above the line.")
    check_eq(rb.fold_status(rb.events(feedback), "fig-a", "owner1"), "needs-changes",
             "a change-request after approval demotes it")
    check(not rb.owner_approval(board, feedback, ledger, "fig-a")["current"],
          "a demoted approval is not current")

    rb.append_event(feedback, board, ledger, item="fig-b", by="rev1", kind="status",
                    status="approved")
    b_status = rb.statuses(board, feedback, "fig-b")
    check_eq((b_status["rev1"], b_status["owner1"]), ("approved", "unreviewed"),
             "statuses are per reviewer")
    check_eq(rb.owner_approval(board, feedback, ledger, "fig-b")["status"], "unreviewed",
             "a non-owner approval does not count as the owner's (D3)")

    rb.append_event(feedback, board, ledger, item="fig-a", by="owner1", kind="status",
                    status="approved")
    check(rb.owner_approval(board, feedback, ledger, "fig-a")["current"], "re-approval")
    add_closed_round(ledger, feedback, {"fig-a": ha2, "fig-b": hb})
    stale = rb.owner_approval(board, feedback, ledger, "fig-a")
    check_eq((stale["status"], stale["current"]), ("approved", False),
             "a changed render leaves the approval stale, not reset (RB-L5)")
    check(rb.owner_approval(board, feedback, ledger, "fig-b")["status"] == "unreviewed",
          "fig-b unchanged by the new round")

    add = lambda **kw: rb.append_event(feedback, board, ledger, **kw)  # noqa: E731
    expect_error(lambda: add(item="fig-z", by="owner1", kind="comment", text="x"),
                 "unknown item", "unknown item refused")
    expect_error(lambda: add(item="fig-a", by="nobody", kind="comment", text="x"),
                 "unknown reviewer", "unknown reviewer refused")
    expect_error(lambda: add(item="fig-a", by="guest:abc", kind="comment", text="x"),
                 "unknown reviewer", "an id not listed in board.yaml is refused")
    expect_error(lambda: add(item="fig-a", by="owner1", kind="vote", text="x"),
                 "kind must be", "unknown kind refused")
    expect_error(lambda: add(item="fig-a", by="owner1", kind="status", status="approved",
                             text="x"), "carries no text", "status with text refused")
    expect_error(lambda: add(item="fig-a", by="owner1", kind="change-request", text=" "),
                 "needs text", "empty change-request refused")
    retired = copy.deepcopy(board)
    retired["reviewers"].append({"id": "old", "role": "reviewer", "retired": True})
    expect_error(lambda: rb.append_event(feedback, retired, ledger, item="fig-a", by="old",
                                         kind="comment", text="x"),
                 "retired", "a retired reviewer cannot post")

    # Notes are stored verbatim (RB-T2): strings YAML would otherwise reinterpret survive a
    # save and a load unchanged.
    awkward = ["Line one\nLine two", "  leading spaces", "trailing space ", "yes", "null",
               "2026-09-24", "#not a comment", "key: value", "unicode – é ✓", "a\n\nb\n",
               "tab\tinside", "'quoted' \"both\""]
    trip = rb.new_feedback(board)
    for text in awkward:
        rb.append_event(trip, board, ledger, item="fig-b", by="rev1", kind="comment",
                        text=text)
    trip_dir = work / "roundtrip"
    trip_dir.mkdir()
    rb.save_feedback(trip_dir, trip)
    check_eq([e["text"] for e in rb.events(rb.load_feedback(trip_dir))], awkward,
             "note text survives a save and load verbatim")
    check("|" in (trip_dir / rb.FEEDBACK_FILE).read_text(encoding="utf-8"),
          "multi-line notes are written as literal blocks")

    clean = codes_of(board, feedback, ledger, root)
    check_eq(clean, set(), "the constructed board lints clean")

    retire = copy.deepcopy(board)
    retire["items"][1]["retired"] = True
    check_eq(codes_of(retire, feedback, ledger, root), set(),
             "retiring an item that has events stays valid (RB-L3)")
    expect_error(lambda: rb.append_event(feedback, retire, ledger, item="fig-b",
                                         by="owner1", kind="comment", text="x"),
                 "unknown item", "a retired item takes no new events")
    deleted = copy.deepcopy(board)
    deleted["items"] = deleted["items"][:1]
    check("RL-02" in codes_of(deleted, feedback, ledger, root),
          "deleting an item that has events fails RL-02")
    before = copy.deepcopy(feedback["events"])
    check_eq(before, feedback["events"], "lint does not mutate the events")

    def with_event(mutate: Callable[[dict], None], index: int = 0) -> set[str]:
        fb = copy.deepcopy(feedback)
        mutate(fb["events"][index])
        return codes_of(board, fb, ledger, root)

    event_cases = [
        ("RL-02", lambda e: e.update(item="fig-zzz")),
        ("RL-02", lambda e: e.update(by="nobody")),
        ("RL-03", lambda e: e.update(kind="vote")),
        ("RL-03", lambda e: e.update(text="an approval with text")),
        ("RL-03", lambda e: e.update(approved_hash=None)),
        ("RL-03", lambda e: e.update(source="email")),
        ("RL-03", lambda e: e.update(source="artifact")),
        ("RL-03", lambda e: e.update(source_id="db-doc-1")),
        ("RL-04", lambda e: e.update(id="ev-00099")),
    ]
    for code, mutate in event_cases:
        check_eq(with_event(mutate), {code}, f"event mutation for {code}")
    check_eq(with_event(lambda e: e.update(approved_hash=fake_hash("x")), index=1),
             {"RL-03"}, "approved_hash on a comment")
    check_eq(with_event(lambda e: e.update(text=None), index=2), {"RL-03"},
             "change-request without text")
    fb = copy.deepcopy(feedback)
    fb["events"][1]["seq"] = 1
    check("RL-04" in codes_of(board, fb, ledger, root), "duplicate seq")
    fb = copy.deepcopy(feedback)
    fb["board"]["id"] = "other"
    check_eq(codes_of(board, fb, ledger, root), {"RL-01"}, "feedback names another board")

    def with_board(mutate: Callable[[dict], None]) -> set[str]:
        b = copy.deepcopy(board)
        mutate(b)
        return codes_of(b, feedback, ledger, root)

    board_cases = [
        ("RL-01", lambda b: b["reviewers"][1].update(role="owner")),
        ("RL-01", lambda b: b["reviewers"][0].update(role="reviewer")),
        ("RL-01", lambda b: b["reviewers"][0].update(retired=True)),
        ("RL-01", lambda b: b["board"].update(medium="web")),
        ("RL-01", lambda b: b["render"].pop("expected_runtime")),
        ("RL-01", lambda b: b["render"].update(timeout_seconds=0)),
        ("RL-01", lambda b: b["items"][0].update(frozen="no")),
        ("RL-01", lambda b: b["items"][0].update(render="output/figures/fig-a.jpg")),
        ("RL-14", lambda b: b["items"][0].update(sources=["/abs/fig-a.py"])),
        ("RL-14", lambda b: b["items"][0].update(sources=["../elsewhere/fig-a.py"])),
        ("RL-14", lambda b: b["items"][0].update(sources=["C:/fig-a.py"])),
        ("RL-14", lambda b: b["items"][0].update(sources=["code\\fig-a.py"])),
        ("RL-15", lambda b: b.update(hosting={"cleared": True, "cleared_by": "owner1",
                                              "cleared_on": "2026-09-24", "basis": "public",
                                              "cleared_items": ["fig-a"]})),
        ("RL-15", lambda b: b.update(hosting="yes")),
    ]
    for code, mutate in board_cases:
        check_eq(with_board(mutate), {code}, f"board mutation for {code}")
    check_eq(with_board(lambda b: b.update(hosting={"cleared": False})), set(),
             "a hosting block that stays uncleared is accepted; the board is local only")
    bad_id = copy.deepcopy(board)
    bad_id["board"]["id"] = "Bad_ID"
    check("RL-01" in rl.lint(bad_id, None, None).codes, "a bad board id")

    def with_ledger(mutate: Callable[[dict], None]) -> set[str]:
        led = copy.deepcopy(ledger)
        mutate(led)
        return codes_of(board, feedback, led, root)

    ledger_cases = [
        ("RL-13", lambda led: (led["rounds"][0].update(cursor_seq=3),
                               led["rounds"][1].update(cursor_seq=1))),
        ("RL-13", lambda led: led["rounds"][1].update(cursor_seq=99)),
        ("RL-13", lambda led: led["rounds"][0].update(closed_at=None)),
        ("RL-13", lambda led: led["rounds"][1].update(n=5)),
        ("RL-13", lambda led: led["items"][0]["renders"][0].update(round=9)),
        ("RL-13", lambda led: led["items"][0]["renders"][0].update(hash="abc")),
        ("RL-13", lambda led: led["rounds"][1]["waivers"].append(
            {"item": "fig-a", "check": "palette", "reason": ""})),
        ("RL-01", lambda led: led.update(schema_version=2)),
    ]
    for code, mutate in ledger_cases:
        check_eq(with_ledger(mutate), {code}, f"ledger mutation for {code}")


# --------------------------------------------------------------------------- case 5
def _independent_hash(width: int, height: int, raw: bytes) -> str:
    """RB-R5 recomputed here without the library, so the algorithm itself is pinned."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return hashlib.sha256(b"IHDR" + ihdr + b"IDAT" + raw).hexdigest()


# RB-R5 golden digests, pinned before the board moved onto the shared kit (I8). A change
# here re-stales every recorded approval, so it is a defect, not an update.
GOLDEN_IMAGE_HASHES = {
    "base": "e7bd28bee23283a4a0c467027815d622243b96d424d452b75335335ddc86e6f8",
    "one pixel": "1c65bdc20c3d82765669abe79292ca898d78295f19c7abd3dbd8e2d0cb33662a",
    "width 13": "a6296c53491681d68fa5f0d2c82a5ed6c49efffe7becb0e418231b7c909095e9",
}


def case_5_hash_stability(work: Path) -> None:
    base = png_bytes()
    base_hash = rb.content_hash_bytes(base)
    golden = {"base": base, "width 13": png_bytes(width=13),
              "one pixel": png_bytes(pixel=lambda x, y: (1, 2, 3) if (x, y) == (5, 5) else
                                     (x * 20 % 256, y * 30 % 256, 128))}
    for label, data in golden.items():
        check_eq(rb.content_hash_bytes(data), GOLDEN_IMAGE_HASHES[label], f"golden: {label}")
    raw = b"".join(b"\x00" + b"".join(bytes((x * 20 % 256, y * 30 % 256, 128))
                                      for x in range(12)) for y in range(8))
    check_eq(base_hash, _independent_hash(12, 8, raw), "RB-R5 known answer")

    same_pixels = {
        "tEXt and tIME metadata": png_bytes(extra=((b"tEXt", b"Software\x00test-suite"),
                                                   (b"tIME", bytes(7)))),
        "compression level 1": png_bytes(level=1),
        "compression level 9": png_bytes(level=9),
        "IDAT split in two": png_bytes(split_idat=True),
        "pHYs 72 dpi": png_bytes(dpi=72),
        "pHYs 300 dpi": png_bytes(dpi=300),
    }
    for label, data in same_pixels.items():
        check_eq(rb.content_hash_bytes(data), base_hash, f"unchanged under {label}")

    one_pixel = png_bytes(pixel=lambda x, y: (1, 2, 3) if (x, y) == (5, 5) else
                          (x * 20 % 256, y * 30 % 256, 128))
    check(rb.content_hash_bytes(one_pixel) != base_hash, "a one-pixel edit changes the hash")
    check(rb.content_hash_bytes(png_bytes(width=13)) != base_hash,
          "a size change changes the hash")

    check_eq(rb.png_info_bytes(png_bytes(dpi=300)),
             {"width_px": 12, "height_px": 8, "dpi": 300}, "pHYs 300 dpi read back")
    check_eq(rb.png_info_bytes(base)["dpi"], None, "no pHYs means dpi is null")

    corrupt = bytearray(base)
    corrupt[-20] ^= 0xFF
    expect_error(lambda: rb.content_hash_bytes(bytes(corrupt)), "PNG",
                 "a corrupted chunk is refused")
    expect_error(lambda: rb.content_hash_bytes(b"GIF89a" + base[6:]), "signature",
                 "a non-PNG is refused")
    expect_error(lambda: rb.content_hash_bytes(base[:40]), "truncated",
                 "a truncated PNG is refused")

    path = work / "a.png"
    path.write_bytes(base)
    check_eq(rb.content_hash(path), base_hash, "file and bytes hash the same")


# --------------------------------------------------------------------------- case 7
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=review-board-test", "-c",
         "user.email=review-board-test@example.invalid", "-c", "commit.gpgsign=false",
         "-c", "init.defaultBranch=main", *args],
        cwd=str(repo), capture_output=True, text=True, check=True)


def case_7_append_only(work: Path) -> str | None:
    if shutil.which("git") is None:
        return "skipped: git not found"
    repo = make_project(work, "proj-git")
    _git(repo, "init", "-q")
    board = board_dict("proj-git")
    board_dir = make_board_dir(repo, board)
    feedback, ledger = rb.load_feedback(board_dir), rb.load_ledger(board_dir)
    add_closed_round(ledger, feedback, {"fig-a": fake_hash("a"), "fig-b": fake_hash("b")})
    rb.append_event(feedback, board, ledger, item="fig-a", by="owner1", kind="comment",
                    text="First note.")
    rb.append_event(feedback, board, ledger, item="fig-b", by="owner1",
                    kind="change-request", text="Second note.")
    rb.save_feedback(board_dir, feedback)
    rb.save_ledger(board_dir, ledger)

    check_eq(rl.head_events(board_dir), None, "untracked feedback.yaml has no HEAD copy")
    check(rl.lint_board_dir(board_dir, repo, "lint").ok, "untracked board lints clean")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "board")
    check_eq(len(rl.head_events(board_dir) or []), 2, "HEAD copy read back")
    check(rl.lint_board_dir(board_dir, repo, "lint").ok, "committed board lints clean")

    committed = rb.load_feedback(board_dir)
    rb.append_event(committed, board, ledger, item="fig-a", by="rev1", kind="comment",
                    text="Third note, after the commit.")
    rb.save_feedback(board_dir, committed)
    check("RL-05" not in rl.lint_board_dir(board_dir, repo, "lint").codes,
          "appending after the commit passes")

    def tampered(mutate: Callable[[dict], None]) -> set[str]:
        fb = rb.load_feedback(board_dir)
        mutate(fb)
        rb.save_feedback(board_dir, fb)
        try:
            return rl.lint_board_dir(board_dir, repo, "lint").codes
        finally:
            rb.save_feedback(board_dir, committed)

    check("RL-05" in tampered(lambda fb: fb["events"][0].update(text="Edited.")),
          "editing a committed event fails RL-05")
    check("RL-05" in tampered(lambda fb: fb["events"].pop(0)),
          "deleting a committed event fails RL-05")
    check("RL-05" in tampered(lambda fb: fb["events"].reverse()),
          "reordering committed events fails RL-05")
    check("RL-05" not in rl.lint_board_dir(board_dir, repo, "open").codes,
          "the restored file passes at open")

    prev = copy.deepcopy(committed["events"])
    altered = copy.deepcopy(committed)
    altered["events"][2]["text"] = "Rewritten before save."
    at_write = rl.lint(board, altered, ledger, project_root=repo, at="write",
                       prev_events=prev)
    check_eq(at_write.codes, {"RL-05"}, "the server's pre-save check catches an edit")
    check(rl.lint(board, committed, ledger, project_root=repo, at="write",
                  prev_events=prev).ok, "an unchanged save passes the pre-save check")

    outside = work / "not-a-repo"
    outside.mkdir()
    check_eq(rl.head_events(outside), None, "no repository means no HEAD comparison")
    return None


# --------------------------------------------------------------------------- case 9
def _svglite(small_px: float = 8.8, line: str = "#024140", title_fill: str = "#000000",
             title_px: float = 11.0) -> str:
    return f"""<?xml version='1.0' encoding='UTF-8' ?>
<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink'
     width='468.00pt' height='252.00pt' viewBox='0 0 468.00 252.00'>
<g class='svglite'>
<defs><style type='text/css'><![CDATA[ .svglite text {{ white-space: pre; }} ]]></style></defs>
<rect width='100%' height='100%' style='stroke: none; fill: #FFFFFF;'/>
<defs><clipPath id='cp1'><rect x='0.00' y='0.00' width='468.00' height='252.00' /></clipPath></defs>
<g clip-path='url(#cp1)'>
<rect x='0.00' y='0.00' width='468.00' height='252.00' style='stroke-width: 1.07; stroke: #FFFFFF; fill: #FFFFFF;' />
<polyline points='40,200 400,40' style='stroke-width: 2.13; stroke: {line};' />
<text x='40' y='230' style='font-size: {small_px}px; fill: #000000; font-family: "Arial";'>2019</text>
<text x='10' y='20' style='font-size: {title_px}px; fill: {title_fill}; font-family: "Arial";'>Title</text>
</g></g></svg>
"""


_MATPLOTLIB = """<?xml version="1.0" encoding="utf-8" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
  "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg xmlns:xlink="http://www.w3.org/1999/xlink" width="460.8pt" height="345.6pt"
     viewBox="0 0 460.8 345.6" xmlns="http://www.w3.org/2000/svg" version="1.1">
 <metadata><title>ignored</title></metadata>
 <defs><style type="text/css">*{stroke-linejoin: round; stroke-linecap: butt}</style></defs>
 <g id="figure_1">
  <g id="patch_1"><path d="M 0 345.6 L 460.8 345.6 L 460.8 0 L 0 0 z" style="fill: #ffffff"/></g>
  <g id="axes_1">
   <g id="line2d_1"><path d="M 57 300 L 400 50" style="fill: none; stroke: #1f77b4; stroke-width: 1.5"/></g>
   <g id="text_1"><text style="font: 10px 'DejaVu Sans'; text-anchor: middle" x="200" y="330"
      transform="rotate(-0 200 330)">x label</text></g>
   <g transform="translate(20 20) scale(0.5)"><text style="font: 10px 'DejaVu Sans'">tiny</text></g>
  </g>
 </g>
</svg>
"""

_PATHS_ONLY = """<svg xmlns="http://www.w3.org/2000/svg" width="100pt" height="50pt"
  viewBox="0 0 100 50"><rect width="100%" height="100%" fill="#ffffff"/>
  <path d="M0 0 L10 10" fill="rgb(2, 65, 64)"/></svg>
"""

_ENTITIES = """<?xml version="1.0"?>
<!DOCTYPE svg [<!ENTITY big "aaaaaaaaaa">]>
<svg xmlns="http://www.w3.org/2000/svg" width="10pt" height="10pt" viewBox="0 0 10 10">
<text font-size="8">&big;</text></svg>
"""


def case_9_measurement(work: Path) -> None:
    palette = rm.load_palette()
    check("#024140" in palette and "#ffffff" in palette and "#000000" in palette,
          "brand colors are in the palette")
    check("#d9d9d9" in palette, "the table rule color is in the palette")
    check("#164c87" not in palette, "legacy sequential colors are excluded")

    def svg(name: str, text: str) -> Path:
        p = work / name
        p.write_text(text, encoding="utf-8", newline="\n")
        return p

    # Non-legacy `colors.neutrals` are on the palette; the key may be absent (read defensively).
    # Append to whatever neutrals the real token file defines: replacing them would drop
    # real palette colors and make the subset check below fail for the wrong reason.
    tokens = json.loads(rm.TOKENS_PATH.read_text(encoding="utf-8"))
    tokens.setdefault("colors", {}).setdefault("neutrals", []).extend([
        {"id": "caption", "hex": "#444444", "status": "provisional"},
        {"id": "axis", "hex": "#CFCFCF", "status": "provisional"},
        {"id": "retired", "hex": "#777777", "status": "legacy"}])
    (work / "tokens.json").write_text(json.dumps(tokens), encoding="utf-8", newline="\n")
    neutral = rm.load_palette(work / "tokens.json")
    check("#444444" in neutral and "#cfcfcf" in neutral and "#777777" not in neutral,
          "non-legacy neutrals are in the palette, legacy ones are not")
    check(palette <= neutral, "adding neutrals removes nothing")
    themed = svg("neutral.svg", _svglite(line="#CFCFCF", title_fill="#444444"))
    check_eq(rm.measure_svg(themed, "print", neutral)["palette"],
             {"result": "pass", "off_palette": []}, "theme neutrals are not off-palette")

    good = rm.measure_svg(svg("good.svg", _svglite()), "print", palette)
    check_eq(good["text_floor"]["result"], "pass", "8.8pt text passes the print floor")
    check_eq(good["text_floor"]["smallest_pt"], 8.8, "svglite px are points")
    check_eq(good["palette"], {"result": "pass", "off_palette": []}, "all brand colors")
    check_eq((good["contrast"]["result"], good["contrast"]["background"],
              good["contrast"]["background_source"]),
             ("pass", "#ffffff", "full-size rect"), "black on the white background rect")

    small = rm.measure_svg(svg("small.svg", _svglite(small_px=6.0)), "print", palette)
    check_eq((small["text_floor"]["result"], small["text_floor"]["smallest_pt"],
              small["text_floor"]["below_floor"]), ("fail", 6.0, 1), "6pt fails")
    edge = svg("edge.svg", _svglite(small_px=7.2))
    check_eq(rm.measure_svg(edge, "print", palette)["text_floor"]["result"], "pass",
             "7.2pt passes the 7pt print floor")
    check_eq(rm.measure_svg(edge, "screen", palette)["text_floor"]["result"], "fail",
             "7.2pt fails the 7.5pt screen floor")

    off = rm.measure_svg(svg("off.svg", _svglite(line="#1F77B4")), "print", palette)
    check_eq(off["palette"], {"result": "fail", "off_palette": ["#1f77b4"]},
             "an off-palette stroke is flagged")

    low = rm.measure_svg(svg("low.svg", _svglite(title_fill="#F0B799")), "print", palette)
    check_eq((low["contrast"]["result"], low["contrast"]["failing_fills"]),
             ("fail", ["#f0b799"]), "tan text on white fails AA")
    large = svg("large.svg", _svglite(title_fill="#5E9C86", title_px=20.0))
    check_eq(rm.measure_svg(large, "print", palette)["contrast"]["result"], "pass",
             "3.2:1 passes for 20pt text")
    normal = svg("normal.svg", _svglite(title_fill="#5E9C86", title_px=9.0))
    check_eq(rm.measure_svg(normal, "print", palette)["contrast"]["result"], "fail",
             "3.2:1 fails for 9pt text")

    mpl = rm.measure_svg(svg("mpl.svg", _MATPLOTLIB), "print", palette)
    check_eq((mpl["text_floor"]["result"], mpl["text_floor"]["smallest_pt"]), ("fail", 5.0),
             "font shorthand and a scale(0.5) transform give 5pt")
    check_eq(mpl["palette"]["off_palette"], ["#1f77b4"], "matplotlib's default blue")
    check_eq((mpl["contrast"]["result"], mpl["contrast"]["background_source"]),
             ("pass", "first painted shape"), "background from the first painted path")

    paths = rm.measure_svg(svg("paths.svg", _PATHS_ONLY), "print", palette)
    check_eq((paths["text_floor"]["result"], paths["contrast"]["result"]),
             ("not-measured", "not-measured"), "no text elements is not measured")
    check_eq(paths["palette"]["result"], "pass", "rgb() normalizes into the palette")

    entities = rm.measure_svg(svg("entities.svg", _ENTITIES), "print", palette)
    check(all(entities[k]["result"] == "not-measured" for k in rb.MEASURE_CHECKS),
          "entity declarations are refused")

    png = work / "fig.png"
    png.write_bytes(png_bytes(width=40, height=20, dpi=300))
    full = rm.measure(png, None, "print", palette)
    check_eq((full["width_px"], full["height_px"], full["dpi"]), (40, 20, 300), "PNG facts")
    check(all(full[k]["result"] == "not-measured" for k in rb.MEASURE_CHECKS),
          "no SVG sibling means not measured, never passed (RB-M3)")
    missing = rm.measure(png, work / "absent.svg", "print", palette)
    check_eq(missing["palette"]["result"], "not-measured", "a declared SVG that is missing")
    with_svg = rm.measure(png, work / "good.svg", "print", palette)
    check_eq(with_svg["text_floor"]["result"], "pass", "PNG and SVG together")


# --------------------------------------------------------------------------- case 2
def case_2_concurrency(work: Path) -> None:
    root, bd = setup_fixture(work)
    first_round(work, bd, root)
    with server(bd, root) as client:
        def one(i: int) -> tuple[int, dict]:
            return client.post({"item": "fig-bars", "by": "owner1" if i % 2 else "rev1",
                                "kind": "comment", "text": f"Concurrent note {i:02d}"})
        # Sixty at once, well past the standard library's default listen backlog of 5:
        # on Windows an overflowing backlog resets connections instead of queueing them.
        with concurrent.futures.ThreadPoolExecutor(max_workers=60) as pool:
            try:
                replies = list(pool.map(one, range(60)))
            except (OSError, http.client.HTTPException) as exc:
                raise CaseFailure(f"a concurrent save failed ({exc!r}); server output:\n"
                                  + "".join(client.output[-20:])) from exc
        check(all(code == 200 and body.get("ok") for code, body in replies),
              f"all sixty saves succeed: {[c for c, _ in replies]}")
        check(not any("Traceback" in line for line in client.output),
              "the server raised during concurrent saves:\n" + "".join(client.output[-20:]))
        events = rb.events(rb.load_feedback(bd))
        check_eq([e["seq"] for e in events], list(range(1, 61)),
                 "sixty events with seq 1..60, none overwritten (RB-S4)")
        check_eq(sorted(e["text"] for e in events),
                 sorted(f"Concurrent note {i:02d}" for i in range(60)), "every note kept")
        check_eq(len(client.item("fig-bars")["events"]), 60, "the API shows all sixty")
    check("PASS" in cli(bd, root, "lint").out, "the board lints clean after concurrent saves")


# --------------------------------------------------------------------------- case 4
def case_4_stale_approval(work: Path) -> None:
    root, bd = setup_fixture(work)
    first_round(work, bd, root)
    with server(bd, root) as client:
        r1_hash = rb.render_for(rb.load_ledger(bd), "fig-bars", 1)["hash"]
        approval = client.event(item="fig-bars", by="owner1", kind="status", status="approved")
        check_eq(approval["approved_hash"], r1_hash, "the server sets approved_hash (RB-L6)")
        bars = client.item("fig-bars")
        check(bars["owner_approval"]["current"] and bars["reviewers"]["owner1"]["approval_current"],
              "a fresh approval is current")

        cli(bd, root, "round", "open")
        set_figure(root, "fig-bars", values=[12, 18, 24])
        cli(bd, root, "render")
        mid = client.state()
        check_eq((mid["round"]["open"], client.item("fig-bars")["render"]["round"]), (2, 1),
                 "during an open round the board still shows the closed round (RB-S2)")
        check(client.item("fig-bars")["owner_approval"]["current"],
              "an unclosed render does not make an approval stale yet")
        record(work, bd, root, {**GATE, "changes": [{
            "item": "fig-bars", "what_changed": "First bar raised to 12.",
            "explanation": "Owner chat request 2026-09-24 (RB-T7): correct the first value."}]})
        cli(bd, root, "round", "close")

        bars = client.item("fig-bars")
        check_eq((bars["owner_approval"]["status"], bars["owner_approval"]["current"],
                  bars["reviewers"]["owner1"]["approval_current"]),
                 ("approved", False, False), "the approval is stale, not reset (RB-L5)")
        check_eq((bars["tags"], bars["previous"]["round"]), (["changed"], 1),
                 "the changed item offers the previous round")
        check("approved against an earlier render" in cli(bd, root, "status", expect=1).out,
              "status blocks on the stale approval")
        events_before = len(rb.events(rb.load_feedback(bd)))
        check_eq(events_before, 1, "nothing wrote a status to clear the stale approval")

        again = client.event(item="fig-bars", by="owner1", kind="status", status="approved")
        check_eq(again["approved_hash"], rb.render_for(rb.load_ledger(bd), "fig-bars", 2)["hash"],
                 "a re-approval records the new render's hash")
        check(client.item("fig-bars")["owner_approval"]["current"], "re-approval is current")


# --------------------------------------------------------------------------- case 8
_FORBIDDEN_JS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                 "new Function", "srcdoc")


_BOARD_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'none'; script-src 'self'; connect-src 'self'; "
                                "img-src 'self' blob:; style-src 'unsafe-inline'; "
                                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
}


def case_8_server_security(work: Path) -> None:
    root, bd = setup_fixture(work)
    first_round(work, bd, root)
    snapshot = (bd / rb.snapshot_rel(1, "fig-bars", "png")).read_bytes()
    with server(bd, root) as client:
        status, headers, page = client.request("GET", "/")
        check_eq(status, 200, "GET / serves the app")
        csp = headers.get("content-security-policy", "")
        check("script-src 'self'" in csp and "default-src 'none'" in csp, f"CSP is strict: {csp}")
        check_eq((headers.get("x-content-type-options"), headers.get("x-frame-options")),
                 ("nosniff", "DENY"), "security headers")
        # Pinned before the move onto `localapp.server` (K3): the headers must not change.
        check_eq({k: headers.get(k.lower()) for k in _BOARD_HEADERS}, _BOARD_HEADERS,
                 "every security header and the CSP are exactly as pinned")
        check_eq(client.request("GET", "/app.js")[0], 200, "GET /app.js")
        for method in ("HEAD", "OPTIONS"):
            status, headers, _ = client.request(method, "/")
            check_eq((status, {k: headers.get(k.lower()) for k in _BOARD_HEADERS}),
                     (501, _BOARD_HEADERS), f"{method}: the stdlib 501 carries the headers")
        for path in ("/?v=2", "/app.js?v=2", "/api/state?since=1", "/img/fig-bars/1?x=1"):
            check_eq(client.request("GET", path)[0], 200, f"{path}: a query string routes")

        status, headers, body = client.request("GET", "/img/fig-bars/1")
        check_eq((status, headers.get("content-type"), body), (200, "image/png", snapshot),
                 "a registered closed-round snapshot is served")
        for path in ("/img/fig-bars/2", "/img/fig-zzz/1", "/img/FIG-BARS/1",
                     "/img/../board.yaml", "/img/fig-bars/1/../../../board.yaml",
                     "/renders/r01/fig-bars.png", "/board.yaml", "/feedback.yaml",
                     "/%2e%2e/board.yaml", "/img/fig-bars/01x", "/img/fig-bars/-1"):
            check_eq(client.request("GET", path)[0], 404, f"{path} is refused (RB-S2)")
        cli(bd, root, "round", "open")
        cli(bd, root, "render")
        check_eq(client.request("GET", "/img/fig-bars/2")[0], 404,
                 "an open round's snapshot is not served")

        for host in ("evil.example", f"127.0.0.1:{client.port + 1}", "127.0.0.1:notaport"):
            check_eq(client.request("GET", "/api/state", headers={"Host": host})[0], 403,
                     f"Host {host} is refused (RB-S1)")
        for origin in ("http://evil.example", f"http://127.0.0.1:{client.port + 1}", "null"):
            code, _ = client.post({"item": "fig-bars", "by": "owner1", "kind": "comment",
                                   "text": "x"}, origin=origin)
            check_eq(code, 403, f"Origin {origin} is refused")
        code, _ = client.post({"item": "fig-bars", "by": "owner1", "kind": "comment",
                               "text": "From a command-line client."}, origin=None)
        check_eq(code, 200, "no Origin, loopback Host: a command-line client may post")

        count = len(rb.events(rb.load_feedback(bd)))
        good = {"item": "fig-bars", "by": "owner1", "kind": "comment", "text": "x"}
        refusals = [
            ({**good, "id": "ev-00009"}, 400), ({**good, "seq": 9}, 400),
            ({**good, "at": "2020-01-01T00:00:00.000000Z"}, 400),
            ({**good, "approved_hash": "0" * 64}, 400), ({**good, "source": "artifact"}, 400),
            ({**good, "source_id": "x"}, 400), ({**good, "colour": "red"}, 400),
            ({**good, "item": "fig-zzz"}, 400), ({**good, "by": "nobody"}, 400),
            ({"item": "fig-bars", "by": "owner1", "kind": "status"}, 400),
            ({**good, "text": "x" * 8001}, 400), ([good], 400), (b"{not json", 400),
            (b"x" * (70 * 1024), 413),
        ]
        for payload, expected in refusals:
            code, _ = client.post(payload)
            check_eq(code, expected, f"refused: {str(payload)[:60]}")
        check_eq(len(rb.events(rb.load_feedback(bd))), count, "no refused request saved anything")
        check_eq(client.request("PUT", "/api/event", b"{}", {"Origin": client.origin})[0], 405,
                 "PUT is refused")

        with socket.create_connection(("127.0.0.1", client.port), timeout=10) as raw:
            raw.sendall(f"POST /api/event HTTP/1.1\r\nHost: 127.0.0.1:{client.port}\r\n"
                        "Connection: close\r\n\r\n".encode())
            check(b" 400 " in raw.recv(200), "a POST without Content-Length is refused")
        # The kit's JSON reader also refuses a body that is not UTF-8, which the board's own
        # reader let escape as an unhandled exception and a dropped connection.
        code, reply = client.post(b'{"text": "\xff\xfe"}')
        check_eq((code, reply.get("error")), (400, "bad json"), "a non-UTF-8 body gets 400")
        count = len(rb.events(rb.load_feedback(bd)))
        status, _, _ = client.request("POST", "/api/event?from=cli",
                                      json.dumps({**good, "text": "q"}).encode(),
                                      {"Origin": client.origin,
                                       "Content-Type": "application/json"})
        check_eq((status, len(rb.events(rb.load_feedback(bd)))), (200, count + 1),
                 "POST /api/event?from=cli routes on the path alone")

        # A second server on a port already in use says so, rather than a traceback.
        taken = subprocess.run(
            [sys.executable, str(SERVER), "--board", str(bd), "--project-root", str(root),
             "--port", str(client.port), "--no-browser"],
            capture_output=True, text=True, timeout=30)
        said = taken.stdout + taken.stderr
        check(taken.returncode == 2 and "already in use" in said and "Traceback" not in said,
              f"a port in use exits 2 with a message, not a traceback: "
              f"{taken.returncode} {said[-400:]}")

        hostile = "<img src=x onerror=alert(1)> & </li><script>alert(2)</script>"
        client.event(item="fig-bars", by="owner1", kind="comment", text=hostile)
        check(any(e["text"] == hostile for e in client.item("fig-bars")["events"]),
              "note HTML comes back as literal text (RB-S3)")

    for name in ("index.html", "app.js"):
        text = (APP_DIR / name).read_text(encoding="utf-8")
        for token in _FORBIDDEN_JS:
            check(token not in text, f"{name} must not use {token} (RB-S3)")
    html = (APP_DIR / "index.html").read_text(encoding="utf-8")
    check_eq(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html), [],
             "no inline script: the CSP allows only /app.js")
    check_eq(re.findall(r"<[^>]*\son[a-z]+\s*=", html, flags=re.I), [],
             "no inline event-handler attributes")

    opt = subprocess.run([sys.executable, str(SERVER), "--board", str(bd), "--host", "0.0.0.0"],
                         capture_output=True, text=True)
    check_eq(opt.returncode, 2, "there is no option to bind anything but loopback")

    # A browser that blocks (a BROWSER command, a text browser) must not stop the board
    # serving, and under CI no browser is started (the kit's open_browser_when_serving).
    testkit.probe_browser_open([sys.executable, str(SERVER), "--board", str(bd),
                                "--project-root", str(root), "--port", "0"], _READY_RE, work)

    ledger = rb.load_ledger(bd)
    ledger["items"][0]["renders"][0]["hash"] = "not-a-hash"
    rb.save_ledger(bd, ledger)
    with server(bd, root) as client:
        state = client.state()
        check(not state["writable"] and any("RL-13" in r for r in state["read_only_reasons"]),
              "a board that fails lint is served read-only, with the reason")
        code, reply = client.post({"item": "fig-bars", "by": "owner1", "kind": "comment",
                                   "text": "Should not save."})
        check_eq((code, reply.get("error")), (403, "the board is read-only"), "writes refused")


# --------------------------------------------------------------------------- runner
# --------------------------------------------------------------------------- case 11
# Two defects found in real use (the American Worker Project slim-deck board, round 2,
# 2026-09-28), each guarded here so it cannot return quietly.

# Nearest-neighbour sampling on a downscaled render drops most of its pixels, so slide text
# reads jagged and smeared. Only the difference canvas may ask for hard pixel edges (RB-S5).
_HARD_EDGES = re.compile(r"image-rendering\s*:\s*(pixelated|crisp-edges|-moz-crisp-edges|"
                         r"optimizespeed|-webkit-optimize-contrast)", re.I)
_IMG_SELECTOR = re.compile(r"(^|[\s>+~,(])img(?![\w-])", re.I)


def hard_edged_img_rules(css: str) -> list[str]:
    """Selectors of every CSS rule that draws an <img> with hard pixel edges."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    bad = []
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if _HARD_EDGES.search(body) and any(_IMG_SELECTOR.search(" " + sel.strip())
                                            for sel in selectors.split(",")):
            bad.append(selectors.strip())
    return bad


def case_11_retire_and_display(work: Path) -> None:
    # (a) An item retired in the round its note asked for still owes that note a response
    # (RL-11), so `record` must accept one; an item board.yaml does not declare stays refused.
    root, bd = setup_fixture(work)
    first_round(work, bd, root)
    ev = post(bd, item="fig-shares", by="owner1", kind="change-request", text="Drop this figure.")
    cli(bd, root, "round", "open")
    board = rb.load_yaml(bd / rb.BOARD_FILE)
    next(i for i in board["items"] if i["id"] == "fig-shares")["retired"] = True
    write_yaml(bd / rb.BOARD_FILE, board)
    cli(bd, root, "render")
    check(classification(bd, "fig-shares", 2) is None, "a retired item is not rendered")
    bad = record(work, bd, root, {"responses": [{"item": "fig-zzz", "state": "answered",
                                                 "text": "No such item."}]}, expect=1)
    check("unknown item 'fig-zzz'" in bad.out, "a response for an undeclared item is refused")
    out = record(work, bd, root, {
        **GATE,
        "triage": [{"event": ev["id"], "decision": "do"}],
        "responses": [{"item": "fig-shares", "state": "changed", "text": "Retired from the board."}],
    }).out
    check("Still needed" not in out, "a retired item's response is accepted and completes the round")
    cli(bd, root, "round", "close")

    # (b) The served app never draws a render with hard pixel edges (RB-S5). The detector is
    # checked against the stylesheet that shipped the defect, so the test cannot pass vacuously.
    check(hard_edged_img_rules(".figure img, .figure canvas { max-width: 100%; "
                               "image-rendering: pixelated; }") == [".figure img, .figure canvas"],
          "the detector flags the rule that shipped the defect")
    check(hard_edged_img_rules(".figure canvas { image-rendering: pixelated; }") == [],
          "the detector allows hard edges on the difference canvas")
    with server(bd, root) as client:
        status, _, page = client.request("GET", "/")
        check_eq(status, 200, "GET / serves the app")
        styles = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", page.decode("utf-8"), flags=re.S))
        check(styles.strip(), "the app has a stylesheet to check")
        check_eq(hard_edged_img_rules(styles), [], "no stylesheet rule draws a render with hard pixel edges")
        status, _, script = client.request("GET", "/app.js")
        check_eq(status, 200, "GET /app.js")
        check(not re.search(r"imageRendering|image-rendering", script.decode("utf-8")),
              "app.js sets no image-rendering at run time")
        # A redraw keeps the reader's place (RB-S6): images carry their measured size, and render()
        # captures an anchor before rebuilding the cards and restores it after.
        js = script.decode("utf-8").replace("\r\n", "\n")  # CRLF on a Windows checkout
        body = js[js.index("function render()"):]
        body = body[:body.index("\n}\n") + 2]
        check("captureAnchor()" in body and "restoreAnchor(" in body
              and body.index("captureAnchor()") < body.index("clear(main)") < body.index("restoreAnchor("),
              "render() restores the reader's scroll position around the rebuild")
        check(re.search(r'el\("img", \{[^;]{0,200}\.\.\.size', js) and "m.width_px" in js,
              "render images carry their measured width and height")


def case_12_localapp_kit(work: Path) -> None:
    """The board saves through `localapp`, so the kit's own suite runs here until the
    maintenance registry lists it on its own."""
    proc = subprocess.run([sys.executable, str(SCRIPTS / "test_localapp.py")], text=True,
                          capture_output=True, timeout=120)
    check(proc.returncode == 0, f"test_localapp.py failed:\n{proc.stdout[-1500:]}{proc.stderr[-500:]}")


CASES: list[tuple[int, str, Callable[[Path], Any]]] = [
    (1, "Full path", case_1_full_path),
    (2, "Concurrency", case_2_concurrency),
    (3, "Fold, events, and config", case_3_fold_events_config),
    (4, "Stale approval", case_4_stale_approval),
    (5, "Content hash stability", case_5_hash_stability),
    (6, "Close refusals", case_6_close_refusals),
    (7, "Append-only against HEAD", case_7_append_only),
    (8, "Server security", case_8_server_security),
    (9, "Measurement", case_9_measurement),
    (10, "Roots and render failures", case_10_roots_and_failures),
    (11, "Retirement and display", case_11_retire_and_display),
    (12, "Shared local-app kit", case_12_localapp_kit),
]


def assert_fixture_boards_labelled() -> None:
    """Every fixture board says it is synthetic, so none can be mistaken for a real review."""
    boards = sorted(FIXTURES.rglob(rb.BOARD_FILE))
    check(boards, "the fixtures directory holds at least one board")
    for path in boards:
        board = rb.load_yaml(path)
        check((board.get("board") or {}).get("fixture") is True,
              f"{path.relative_to(FIXTURES)} must set board.fixture: true")


def main() -> int:
    install_network_guard()
    try:
        self_test_network_guard()
        assert_fixture_boards_labelled()
    except CaseFailure as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    started = time.monotonic()
    failures = 0
    digest_before = tree_digest(FIXTURES)
    print(f"Fixtures digest (before): {digest_before}")
    tmp = Path(tempfile.mkdtemp(prefix="review-board-test-"))
    try:
        for number, title, fn in CASES:
            work = tmp / f"case{number:02d}"
            work.mkdir()
            try:
                note = fn(work)
            except CaseFailure as exc:
                failures += 1
                print(f"FAIL  {number:>2}  {title}: {exc}")
                continue
            except Exception:  # an unexpected error is a failure with its traceback
                failures += 1
                print(f"FAIL  {number:>2}  {title}: unexpected error")
                traceback.print_exc()
                continue
            suffix = f"  ({note})" if note else ""
            print(f"PASS  {number:>2}  {title}{suffix}")
    finally:
        _rmtree(tmp)
    digest_after = tree_digest(FIXTURES)
    print(f"Fixtures digest (after):  {digest_after}")
    if digest_after != digest_before:
        failures += 1
        print("FAIL  the fixtures directory changed during the run")
    elapsed = time.monotonic() - started
    print(f"{len(CASES) - failures}/{len(CASES)} cases passed in {elapsed:.1f}s")
    if elapsed > TIME_LIMIT_SECONDS:
        print(f"FAIL  runtime {elapsed:.1f}s exceeds {TIME_LIMIT_SECONDS}s")
        return 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
