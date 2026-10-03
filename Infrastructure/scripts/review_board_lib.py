#!/usr/bin/env python3
"""Shared library for the review board.

Every review-board script imports this module, so the things the rules pin down exist
exactly once:

- the closed vocabularies (event kinds, statuses, triage decisions, response states);
- the board directory's file names and the snapshot and round-plan paths;
- project-root resolution and the project-id check (RB-L1, spec M6);
- loading and saving `feedback.yaml` and `ledger.yaml` in canonical order, through the
  shared kit (`localapp.yamlio`), with timestamps kept as strings;
- `append_event`, the only function that adds to the reviewer lane (RB-L2, RB-L6);
- `fold_status`, a reviewer's current status computed from events (RB-L4);
- `owner_approval`, whether the owner's approval matches the current render (RB-L5);
- `content_hash`, the pinned PNG image-data hash (RB-R5).

The binding text for each is `Infrastructure/rules/review-board-rules.md`. If this module
and that file ever disagree, the repository has a defect.

Nothing here writes `board.yaml`: the owner writes it (RB-L2).

Dependencies: Python 3.11+ and PyYAML.
"""

from __future__ import annotations

import hashlib
import re
import struct
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localapp import projroot  # noqa: E402
from localapp.yamlio import (FlowList, FlowMap, Loader, atomic_write_text,  # noqa: E402,F401
                             dump_yaml as _dump, reorder as _reorder)

# --------------------------------------------------------------------------- vocabularies
SCHEMA_VERSION = 1

EVENT_KINDS = ("status", "change-request", "comment")
NOTE_KINDS = ("change-request", "comment")
STATUSES = ("unreviewed", "approved", "needs-changes")
ROLES = ("owner", "reviewer")
DECISIONS = ("do", "do-with-change", "question", "decline", "surface")
ACTING_DECISIONS = ("do", "do-with-change")
OPEN_DECISIONS = ("question", "surface")
RESPONSE_STATES = ("changed", "still-open", "answered", "declined")
CLASSIFICATIONS = ("new", "changed", "unchanged")
MEASURE_RESULTS = ("pass", "fail", "not-measured")
MEASURE_CHECKS = ("text_floor", "palette", "contrast")
MEDIA = ("print", "screen")
STOP_VERDICTS = ("stop", "proceed")
EVENT_SOURCES = ("local",)          # the board is local only (RB-H1)

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REVIEWER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

BOARD_FILE = "board.yaml"
FEEDBACK_FILE = "feedback.yaml"
LEDGER_FILE = "ledger.yaml"
ROUNDS_DIR = "rounds"
RENDERS_DIR = "renders"
SUMMARY_FILE = "board.md"


class ReviewBoardError(Exception):
    """A refusal the caller should report to the person running the command."""


# --------------------------------------------------------------------------- names
def utc_now() -> str:
    """UTC ISO 8601 with microseconds (RB-L7)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def slug_for(project_id: str, board_id: str) -> str:
    """The board directory name: `<project id>--<board id>` (RB-L1)."""
    return f"{project_id}--{board_id}"


def event_id(seq: int) -> str:
    return f"ev-{seq:05d}"


def round_tag(n: int) -> str:
    return f"r{n:02d}"


def snapshot_rel(n: int, item_id: str, ext: str) -> str:
    """A snapshot path relative to the board directory (RB-R6)."""
    return f"{RENDERS_DIR}/{round_tag(n)}/{item_id}.{ext}"


def round_plan_rel(n: int) -> str:
    return f"{ROUNDS_DIR}/round-{n:02d}.md"


def board_file(board_dir: Path, name: str) -> Path:
    return Path(board_dir) / name


# --------------------------------------------------------------------------- project root
def board_project_id(board: dict) -> str:
    pid = str(((board.get("project") or {}).get("id") or "")).strip()
    if not pid:
        raise ReviewBoardError("board.yaml has no project.id")
    return pid


def resolve_project_root(explicit: str | Path | None, board: dict) -> Path:
    """The flag wins; otherwise walk up from the working directory (spec M6). The root is
    never stored, and it must be named for the board's project.id either way."""
    try:
        return projroot.resolve_project_root(explicit, board_project_id(board),
                                             record="board.yaml")
    except projroot.ProjectRootError as exc:
        raise ReviewBoardError(str(exc)) from None


def check_project_id(root: Path, board: dict) -> None:
    try:
        projroot.check_project_id(root, board_project_id(board), record="board.yaml")
    except projroot.ProjectRootError as exc:
        raise ReviewBoardError(str(exc)) from None


def check_board_dir(board_dir: Path, board: dict) -> None:
    """The directory must be named `<project id>--<board id>` (RB-L1, spec M1)."""
    expected = slug_for(board_project_id(board), str((board.get("board") or {}).get("id")))
    if Path(board_dir).name != expected:
        raise ReviewBoardError(
            f"board directory is named {Path(board_dir).name!r}, but board.yaml says it "
            f"should be {expected!r} (<project id>--<board id>)"
        )


def path_problem(rel: Any) -> str | None:
    """Why a config path is unacceptable before any root is known (RL-14), or None."""
    if not isinstance(rel, str) or not rel.strip():
        return "is empty"
    if "\\" in rel:
        return "uses a backslash; write project-relative paths with forward slashes"
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        return "is absolute"
    if ".." in rel.split("/"):
        return "contains '..'"
    return None


def resolve_under(root: Path, rel: str) -> Path:
    """`rel` under `root`, refusing anything that escapes it (RL-14)."""
    problem = path_problem(rel)
    if problem:
        raise ReviewBoardError(f"path {rel!r} {problem}")
    root = Path(root).resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise ReviewBoardError(f"path {rel!r} resolves outside the project root")
    return path


# --------------------------------------------------------------------------- YAML IO
# Multi-line note text is written as literal blocks, so feedback.yaml reads verbatim.
_FEEDBACK_ORDER = ("schema_version", "project", "board", "fixture", "events")
_EVENT_ORDER = ("id", "seq", "item", "by", "at", "kind", "status", "approved_hash", "text",
                "source", "source_id")
_LEDGER_ORDER = ("schema_version", "project", "board", "fixture", "items", "rounds")
_ITEM_ORDER = ("id", "renders")
_RENDER_ORDER = ("round", "hash", "snapshot", "svg_snapshot", "classification",
                 "measurements")
_MEASURE_ORDER = ("width_px", "height_px", "dpi", "dpi_changed", "text_floor", "palette",
                  "contrast")
_ROUND_ORDER = ("n", "opened_at", "cursor_seq", "cursor_at", "listed", "carried",
                "stop_gate", "triage", "changes", "responses", "waivers", "changed_files",
                "closed_at")
_STOP_ORDER = ("verdict", "reason", "approved_on")
_TRIAGE_ORDER = ("event", "decision", "reason", "owner_confirmed_on")
_CHANGE_ORDER = ("item", "what_changed", "explanation")
_RESPONSE_ORDER = ("item", "state", "text")
_WAIVER_ORDER = ("item", "check", "reason")
_CHANGED_FILES_ORDER = ("available", "outside_sources")


def _flow_list(value: Any) -> Any:
    return FlowList(value) if isinstance(value, list) else value


def _each(items: Any, fn) -> Any:
    return [fn(x) for x in items] if isinstance(items, list) else items


def order_feedback(data: dict) -> dict:
    out = _reorder(data, _FEEDBACK_ORDER)
    out["events"] = _each(out.get("events"), lambda e: _reorder(e, _EVENT_ORDER))
    return out


def _order_measurements(m: Any) -> Any:
    m = _reorder(m, _MEASURE_ORDER)
    if isinstance(m, dict):
        for key in MEASURE_CHECKS:
            if isinstance(m.get(key), dict):
                check = dict(m[key])
                for k, v in check.items():
                    check[k] = _flow_list(v)
                m[key] = FlowMap(check)
    return m


def _order_render(r: Any) -> Any:
    r = _reorder(r, _RENDER_ORDER)
    if isinstance(r, dict) and "measurements" in r:
        r["measurements"] = _order_measurements(r["measurements"])
    return r


def _order_round(r: Any) -> Any:
    r = _reorder(r, _ROUND_ORDER)
    if not isinstance(r, dict):
        return r
    for key in ("listed", "carried"):
        r[key] = _flow_list(r.get(key, []))
    if "stop_gate" in r:
        r["stop_gate"] = _reorder(r["stop_gate"], _STOP_ORDER)
    for key, order in (("triage", _TRIAGE_ORDER), ("changes", _CHANGE_ORDER),
                       ("responses", _RESPONSE_ORDER), ("waivers", _WAIVER_ORDER)):
        if key in r:
            r[key] = _each(r[key], lambda x, o=order: _reorder(x, o))
    if isinstance(r.get("changed_files"), dict):
        cf = _reorder(r["changed_files"], _CHANGED_FILES_ORDER)
        cf["outside_sources"] = _flow_list(cf.get("outside_sources", []))
        r["changed_files"] = cf
    return r


def order_ledger(data: dict) -> dict:
    out = _reorder(data, _LEDGER_ORDER)
    out["items"] = _each(out.get("items"), lambda i: _reorder(i, _ITEM_ORDER))
    for item in out["items"] if isinstance(out["items"], list) else []:
        if isinstance(item, dict):
            item["renders"] = _each(item.get("renders"), _order_render)
    out["rounds"] = _each(out.get("rounds"), _order_round)
    return out


def load_yaml(path: Path) -> dict:
    """Read one board file. Timestamps come back as strings, never datetimes."""
    path = Path(path)
    if not path.is_file():
        raise ReviewBoardError(f"no {path.name} at {path}")
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ReviewBoardError(f"{path.name} is not a mapping")
    return data


def load_yaml_text(text: str) -> Any:
    return yaml.load(text, Loader=Loader)


def dump_yaml(data: dict) -> str:
    return _dump(data, literal_multiline=True)


def load_board(board_dir: Path) -> dict:
    return load_yaml(board_file(board_dir, BOARD_FILE))


def load_feedback(board_dir: Path) -> dict:
    return load_yaml(board_file(board_dir, FEEDBACK_FILE))


def load_ledger(board_dir: Path) -> dict:
    return load_yaml(board_file(board_dir, LEDGER_FILE))


def dump_feedback(data: dict) -> str:
    return dump_yaml(order_feedback(data))


def dump_ledger(data: dict) -> str:
    return dump_yaml(order_ledger(data))


def save_feedback(board_dir: Path, data: dict) -> None:
    """Only the board server calls this (RB-L2)."""
    atomic_write_text(board_file(board_dir, FEEDBACK_FILE), dump_feedback(data))


def save_ledger(board_dir: Path, data: dict) -> None:
    atomic_write_text(board_file(board_dir, LEDGER_FILE), dump_ledger(data))


def _header(board: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "project": {"id": board_project_id(board)},
        "board": {"id": (board.get("board") or {}).get("id")},
        "fixture": bool((board.get("board") or {}).get("fixture", False)),
    }


def new_feedback(board: dict) -> dict:
    return {**_header(board), "events": []}


def new_ledger(board: dict) -> dict:
    return {**_header(board), "items": [], "rounds": []}


# --------------------------------------------------------------------------- board model
def items(board: dict, include_retired: bool = False) -> list[dict]:
    out = [i for i in (board.get("items") or []) if isinstance(i, dict)]
    return out if include_retired else [i for i in out if not i.get("retired")]


def item_ids(board: dict, include_retired: bool = True) -> list[str]:
    return [str(i.get("id")) for i in items(board, include_retired)]


def find_item(board: dict, item_id: str) -> dict | None:
    for item in items(board, include_retired=True):
        if item.get("id") == item_id:
            return item
    return None


def reviewers(board: dict, include_retired: bool = True) -> list[dict]:
    out = [r for r in (board.get("reviewers") or []) if isinstance(r, dict)]
    return out if include_retired else [r for r in out if not r.get("retired")]


def find_reviewer(board: dict, reviewer_id: str) -> dict | None:
    for r in reviewers(board):
        if r.get("id") == reviewer_id:
            return r
    return None


def owner_id(board: dict) -> str | None:
    owners = [r.get("id") for r in reviewers(board) if r.get("role") == "owner"]
    return owners[0] if len(owners) == 1 else None


# --------------------------------------------------------------------------- ledger model
def rounds(ledger: dict) -> list[dict]:
    return [r for r in (ledger.get("rounds") or []) if isinstance(r, dict)]


def open_round(ledger: dict) -> dict | None:
    rs = rounds(ledger)
    return rs[-1] if rs and not rs[-1].get("closed_at") else None


def latest_closed_round(ledger: dict) -> int | None:
    closed = [r.get("n") for r in rounds(ledger) if r.get("closed_at")]
    return closed[-1] if closed else None


def find_round(ledger: dict, n: int) -> dict | None:
    for r in rounds(ledger):
        if r.get("n") == n:
            return r
    return None


def ledger_item(ledger: dict, item_id: str) -> dict | None:
    for item in ledger.get("items") or []:
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    return None


def render_for(ledger: dict, item_id: str, n: int | None) -> dict | None:
    if n is None:
        return None
    item = ledger_item(ledger, item_id)
    for r in (item or {}).get("renders") or []:
        if isinstance(r, dict) and r.get("round") == n:
            return r
    return None


def current_render(ledger: dict, item_id: str) -> dict | None:
    """The item's render in the latest closed round: what the board shows (RB-S2)."""
    return render_for(ledger, item_id, latest_closed_round(ledger))


def previous_render(ledger: dict, item_id: str) -> dict | None:
    """The item's render in the closed round before the latest one (spec S1)."""
    closed = [r.get("n") for r in rounds(ledger) if r.get("closed_at")]
    return render_for(ledger, item_id, closed[-2]) if len(closed) >= 2 else None


# --------------------------------------------------------------------------- events
def events(feedback: dict) -> list[dict]:
    return [e for e in (feedback.get("events") or []) if isinstance(e, dict)]


def max_seq(feedback: dict) -> int:
    seqs = [e.get("seq") for e in events(feedback) if isinstance(e.get("seq"), int)]
    return max(seqs) if seqs else 0


def events_by_id(feedback: dict) -> dict[str, dict]:
    return {str(e.get("id")): e for e in events(feedback)}


def append_event(feedback: dict, board: dict, ledger: dict, *, item: str, by: str,
                 kind: str, status: str | None = None, text: str | None = None,
                 source: str = "local", source_id: str | None = None,
                 at: str | None = None) -> dict:
    """Append one reviewer event and return it. The only writer of the reviewer lane.

    The caller supplies what a reviewer chose: the item, who they are, the kind, and the
    status or the text. `id`, `seq`, `at`, and `approved_hash` are assigned here (RB-L6).
    """
    board_item = find_item(board, item)
    if board_item is None or board_item.get("retired"):
        raise ReviewBoardError(f"unknown item {item!r}")
    reviewer = find_reviewer(board, by)
    if reviewer is None:
        raise ReviewBoardError(f"unknown reviewer {by!r}")
    if reviewer.get("retired"):
        raise ReviewBoardError(f"reviewer {by!r} is retired")
    if kind not in EVENT_KINDS:
        raise ReviewBoardError(f"kind must be one of {', '.join(EVENT_KINDS)}")
    if source not in EVENT_SOURCES or source_id is not None:
        raise ReviewBoardError("every event comes from the local board (RB-H1)")

    approved_hash = None
    if kind == "status":
        if status not in STATUSES:
            raise ReviewBoardError(f"status must be one of {', '.join(STATUSES)}")
        if text not in (None, ""):
            raise ReviewBoardError("a status event carries no text")
        text = None
        if status == "approved":
            render = current_render(ledger, item)
            if render is None or not render.get("hash"):
                raise ReviewBoardError(
                    f"{item} has no render in a closed round, so there is nothing to approve")
            approved_hash = render["hash"]
    else:
        if status is not None:
            raise ReviewBoardError("only a status event carries a status")
        if not isinstance(text, str) or not text.strip():
            raise ReviewBoardError(f"a {kind} needs text")

    seq = max_seq(feedback) + 1
    event = {
        "id": event_id(seq),
        "seq": seq,
        "item": item,
        "by": by,
        "at": at or utc_now(),
        "kind": kind,
        "status": status if kind == "status" else None,
        "approved_hash": approved_hash,
        "text": text,
        "source": source,
        "source_id": source_id,
    }
    feedback.setdefault("events", []).append(event)
    return event


# --------------------------------------------------------------------------- status fold
def fold_status(event_list: Iterable[dict], item_id: str, reviewer_id: str) -> str:
    """RB-L4. Start at `unreviewed`; walk the reviewer's events on the item in seq order."""
    status = "unreviewed"
    mine = [e for e in event_list if e.get("item") == item_id and e.get("by") == reviewer_id]
    for e in sorted(mine, key=lambda e: e.get("seq", 0)):
        kind = e.get("kind")
        if kind == "status" and e.get("status") in STATUSES:
            status = e["status"]
        elif kind == "change-request" and status == "approved":
            status = "needs-changes"
    return status


def statuses(board: dict, feedback: dict, item_id: str) -> dict[str, str]:
    """Every reviewer's folded status on an item (unlisted ids that posted are shown too;
    lint reports them as RL-02)."""
    evs = events(feedback)
    ids = [str(r.get("id")) for r in reviewers(board)]
    ids += sorted({str(e.get("by")) for e in evs
                   if e.get("item") == item_id and str(e.get("by")) not in ids})
    return {rid: fold_status(evs, item_id, rid) for rid in ids}


def latest_status_event(event_list: Iterable[dict], item_id: str,
                        reviewer_id: str) -> dict | None:
    latest = None
    for e in event_list:
        if (e.get("item") == item_id and e.get("by") == reviewer_id
                and e.get("kind") == "status"):
            if latest is None or e.get("seq", 0) > latest.get("seq", 0):
                latest = e
    return latest


def owner_approval(board: dict, feedback: dict, ledger: dict, item_id: str) -> dict:
    """RB-L5. The owner's folded status, and whether an approval matches the current render."""
    owner = owner_id(board)
    evs = events(feedback)
    status = fold_status(evs, item_id, owner) if owner else "unreviewed"
    approved_hash = None
    current = False
    if status == "approved":
        # A folded `approved` means the owner's latest status event is the approval and no
        # change-request followed it, so that event holds the hash they saw.
        approval = latest_status_event(evs, item_id, owner)
        approved_hash = (approval or {}).get("approved_hash")
        render = current_render(ledger, item_id)
        current = bool(render and approved_hash and render.get("hash") == approved_hash)
    return {"status": status, "approved_hash": approved_hash, "current": current}


# --------------------------------------------------------------------------- round listing
def round_event_ids(feedback: dict, after_seq: int, through_seq: int) -> list[str]:
    """Change-requests and comments with after_seq < seq <= through_seq, in seq order."""
    picked = [e for e in events(feedback)
              if e.get("kind") in NOTE_KINDS and isinstance(e.get("seq"), int)
              and after_seq < e["seq"] <= through_seq]
    return [str(e["id"]) for e in sorted(picked, key=lambda e: e["seq"])]


def latest_triage(ledger: dict, before_round: int) -> dict[str, str]:
    """Each event's latest triage decision across rounds numbered below `before_round`."""
    latest: dict[str, str] = {}
    for r in rounds(ledger):
        if isinstance(r.get("n"), int) and r["n"] < before_round:
            for t in r.get("triage") or []:
                if isinstance(t, dict) and t.get("event"):
                    latest[str(t["event"])] = str(t.get("decision"))
    return latest


def carried_event_ids(ledger: dict, round_n: int) -> list[str]:
    """RB-T8. Events whose latest triage before `round_n` is `question` or `surface`."""
    latest = latest_triage(ledger, round_n)
    return sorted(eid for eid, decision in latest.items() if decision in OPEN_DECISIONS)


def previous_cursor(ledger: dict, round_n: int) -> int:
    prev = find_round(ledger, round_n - 1)
    return int(prev.get("cursor_seq") or 0) if prev else 0


# --------------------------------------------------------------------------- PNG
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    """Every chunk as (type, data), in file order, through IEND. CRCs are verified."""
    if not data.startswith(PNG_SIGNATURE):
        raise ReviewBoardError("not a PNG: the 8-byte signature is missing")
    chunks: list[tuple[bytes, bytes]] = []
    pos = len(PNG_SIGNATURE)
    while pos < len(data):
        if pos + 8 > len(data):
            raise ReviewBoardError("truncated PNG: incomplete chunk header")
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        start, end = pos + 8, pos + 8 + length
        if end + 4 > len(data):
            raise ReviewBoardError(f"truncated PNG: chunk {ctype!r} runs past the end")
        body = data[start:end]
        (crc,) = struct.unpack(">I", data[end:end + 4])
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise ReviewBoardError(f"corrupt PNG: CRC mismatch in chunk {ctype!r}")
        chunks.append((ctype, body))
        pos = end + 4
        if ctype == b"IEND":
            break
    if not chunks or chunks[0][0] != b"IHDR":
        raise ReviewBoardError("invalid PNG: the first chunk is not IHDR")
    return chunks


def content_hash_bytes(data: bytes) -> str:
    """RB-R5, exactly: IHDR, PLTE, tRNS, then the decompressed IDAT stream."""
    chunks = png_chunks(data)
    kept = {b"IHDR": None, b"PLTE": None, b"tRNS": None}
    idat = bytearray()
    for ctype, body in chunks:
        if ctype in kept and kept[ctype] is None:
            kept[ctype] = body
        elif ctype == b"IDAT":
            idat.extend(body)
    if not idat:
        raise ReviewBoardError("invalid PNG: no IDAT data")
    try:
        pixels = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise ReviewBoardError(f"corrupt PNG: IDAT does not decompress ({exc})") from exc
    h = hashlib.sha256()
    for ctype in (b"IHDR", b"PLTE", b"tRNS"):
        if kept[ctype] is not None:
            h.update(ctype + kept[ctype])
    h.update(b"IDAT" + pixels)
    return h.hexdigest()


def content_hash(path: Path) -> str:
    return content_hash_bytes(Path(path).read_bytes())


def png_info_bytes(data: bytes) -> dict:
    """Pixel width and height from IHDR; DPI from pHYs when its unit is the metre."""
    chunks = png_chunks(data)
    width, height = struct.unpack(">II", chunks[0][1][:8])
    dpi = None
    for ctype, body in chunks:
        if ctype == b"pHYs" and len(body) == 9:
            x_ppu, _y_ppu, unit = struct.unpack(">IIB", body)
            if unit == 1:
                dpi = int(round(x_ppu * 0.0254))
            break
    return {"width_px": width, "height_px": height, "dpi": dpi}


def png_info(path: Path) -> dict:
    return png_info_bytes(Path(path).read_bytes())
