#!/usr/bin/env python3
"""Schema and integrity lint for a war-room `ledger.yaml`.

One script holds every check, and it gates every write (WR-Q10 in
`Infrastructure/rules/code-war-room-design.md`): the app server runs it after each
mutation and before persisting, reconcile runs it before `--write`, and the renderers run it
before rendering. A check that lived in three places would drift in two of them.

Each check has a stable code, `WL-01` .. `WL-14`, and every failure line is prefixed by it:

    WL-05: b003 endorsed_prediction is true but disposition is 'needs-change'

| Code  | Check |
|-------|-------|
| WL-01 | `schema_version` is 2 and the required top-level keys are present |
| WL-02 | `block_id` unique and of the form `b001`, `b003a`; `lines` ascending; `sha256` is 64 lowercase hex |
| WL-03 | Blocks cover every non-blank line exactly once and do not overlap (WR-S7) |
| WL-04 | Closed-set fields hold closed-set values |
| WL-05 | Endorsement integrity (WR-Q7) |
| WL-06 | Every dispositioned block has `reviewer` and `answered_at` |
| WL-07 | Every `answered_at` is later than `session.prep_completed` |
| WL-08 | No absolute path in a structural field (WR-A5, WR-Q6) |
| WL-09 | After `session.reconciled`, every discussed block carries a `divergence.match` |
| WL-10 | Every reviewer id used on a block or a dissent item is in `session.reviewers[]` |
| WL-11 | `assumption_export[]` and `open_questions[]` name blocks that exist |
| WL-12 | `session.history[]` is non-empty once `prep_completed` is set (WR-O7) |
| WL-13 | Every block hash recomputes from the source, unless the block carries `drift` |
| WL-14 | `dissent[]` items are complete (WR-O6) |

WL-03 and WL-13 read the reviewed source, so they run only when `script.path` resolves under
the project root (resolution per WR-A5 / D2, via the shared library). When it does not
resolve, they are **skipped with a warning** rather than failed: a lint pass that cannot see
the file has learned nothing about the hashes, and reporting that as a hash failure would
send a reader looking for a defect in the ledger instead of in the invocation.

Drift is a recorded fact, not a lint failure. A block whose source changed after prep carries
`drift: true` (set by `war_room_prep.py verify --write` or by the app server on save, D11),
and WL-13 accepts a mismatch there; otherwise a file edited mid-session would make every
later save fail. For the same reason WL-03 and the whole-file hash comparison drop to
warnings in either of two conditions: a block carries `drift: true`, or `script.sha256`
no longer matches the current file. The second covers a relocated block, and it matters
on its own because an append-only edit -- a line added below the last block -- leaves
every block hash reproducing, so nothing is flagged, while coverage and the whole-file
hash both break. `war_room_prep.py verify --accept-relocations` re-stamps the file hash. After a real edit the recorded ranges describe the file as
it was, which is the point of the flags. A per-block hash mismatch is never degraded: it
fails WL-13 unless that block itself carries `drift`.

Usage:
    python3 Infrastructure/scripts/war_room_lint.py <ledger.yaml> [--project-root <dir>] [--json]

Exit 0 and print nothing on success; exit 1 with one line per failure otherwise. Warnings go
to stderr and never change the exit code. `--json` emits
`{"ok": bool, "failures": [{"code", "block_id", "message"}], "warnings": [...]}` for the
app server, which returns the failure list to the browser instead of persisting.

Dependencies: Python 3.11+ and PyYAML. Nothing else.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import war_room_lib as wr  # noqa: E402

SCHEMA_DOC = "Infrastructure/templates/war-room-ledger.md"

_HEX64 = re.compile(r"[0-9a-f]{64}")  # used with fullmatch: `$` would allow a final "\n"
# Prep numbers blocks `b001`, `b002`, ...; a split appends `a` or `b`, so `b003ab` is valid.
_BLOCK_ID = re.compile(r"b[0-9]{3,}[a-z]*")
# `/x`, `~/x`, `C:\x`, `C:/x`, and a UNC share are all absolute for WL-08's purposes.
_ABSOLUTE = re.compile(r"^(?:/|~/|\\\\|[A-Za-z]:[\\/])")

REQUIRED_TOP_KEYS = ("schema_version", "script", "project", "session", "blocks")


@dataclass(frozen=True)
class Finding:
    code: str
    block_id: str | None
    message: str

    def line(self) -> str:
        where = f"{self.block_id} " if self.block_id else ""
        return f"{self.code}: {where}{self.message}"

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "block_id": self.block_id, "message": self.message}


@dataclass
class LintResult:
    failures: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def codes(self) -> set[str]:
        return {f.code for f in self.failures}

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failures": [f.as_dict() for f in self.failures],
            "warnings": [w.as_dict() for w in self.warnings],
        }


class _Ctx:
    """One lint run's accumulating state."""

    def __init__(self, ledger: dict) -> None:
        self.ledger = ledger if isinstance(ledger, dict) else {}
        self.result = LintResult()
        self.session = self.ledger.get("session") or {}
        self.script = self.ledger.get("script") or {}
        blocks = self.ledger.get("blocks")
        self.blocks: list[dict] = [b for b in (blocks or []) if isinstance(b, dict)]

    def fail(self, code: str, message: str, block_id: str | None = None) -> None:
        self.result.failures.append(Finding(code, block_id, message))

    def warn(self, code: str, message: str, block_id: str | None = None) -> None:
        self.result.warnings.append(Finding(code, block_id, message))


# --------------------------------------------------------------------------- helpers
def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_absolute(value: Any) -> bool:
    return isinstance(value, str) and bool(_ABSOLUTE.match(value.strip()))


def _walk_strings(node: Any, prefix: str) -> list[tuple[str, str]]:
    """Every string leaf under `node`, with a dotted path for the message."""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out.extend(_walk_strings(v, f"{prefix}.{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_walk_strings(v, f"{prefix}[{i}]"))
    elif isinstance(node, str):
        out.append((prefix, node))
    return out


def _path_keys(node: Any, prefix: str) -> list[tuple[str, str]]:
    """Every string under a key ending `_path`, anywhere in the ledger."""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{prefix}.{k}"
            if isinstance(k, str) and k.endswith("_path"):
                out.extend(_walk_strings(v, here))
            else:
                out.extend(_path_keys(v, here))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_path_keys(v, f"{prefix}[{i}]"))
    return out


def _has_author_text(account: Any) -> bool:
    if not isinstance(account, dict):
        return False
    for key in ("meant_to_do", "why_this_way"):
        if (account.get(key) or "").strip():
            return True
    return bool([a for a in (account.get("assumptions_carried") or []) if str(a).strip()])


# --------------------------------------------------------------------------- checks
def _wl01(ctx: _Ctx) -> bool:
    """Returns False when lint must stop (WL-01 is the gate on every other check)."""
    version = ctx.ledger.get("schema_version")
    if version == 1:
        ctx.fail("WL-01", f"schema_version is 1; schema version 2 is required. "
                          f"Nothing migrates a version 1 ledger -- see {SCHEMA_DOC} "
                          f"(\"Schema version 2\") and rebuild the ledger with "
                          f"war_room_prep.py")
        return False
    if version != wr.SCHEMA_VERSION:
        ctx.fail("WL-01", f"schema_version is {version!r}; expected {wr.SCHEMA_VERSION}")
        return False
    missing = [k for k in REQUIRED_TOP_KEYS if k not in ctx.ledger]
    if missing:
        ctx.fail("WL-01", f"missing required top-level key(s): {', '.join(missing)}")
        return False
    if not isinstance(ctx.ledger.get("blocks"), list):
        ctx.fail("WL-01", "blocks must be a list")
        return False
    return True


def _wl02(ctx: _Ctx) -> None:
    seen: set[str] = set()
    previous_start: int | None = None
    for b in ctx.blocks:
        bid = b.get("block_id")
        if not isinstance(bid, str) or not bid:
            ctx.fail("WL-02", "a block has no block_id")
            continue
        if not _BLOCK_ID.fullmatch(bid):
            # Ids reach the app and the report; only the format prep writes is accepted.
            ctx.fail("WL-02", f"block_id {bid!r} is not of the form b001 or b003a", None)
            continue
        if bid in seen:
            ctx.fail("WL-02", "block_id appears more than once; one entry per block "
                              "(WR-O2) -- a second reviewer's answer belongs in dissent[]",
                     bid)
        seen.add(bid)
        lines_ = b.get("lines")
        if not (isinstance(lines_, list) and len(lines_) == 2
                and all(isinstance(v, int) for v in lines_)):
            ctx.fail("WL-02", f"lines must be [start, end] integers, got {lines_!r}", bid)
        else:
            start, end = int(lines_[0]), int(lines_[1])
            if start < 1 or end < start:
                ctx.fail("WL-02", f"lines {start}-{end} are not ascending", bid)
            elif previous_start is not None and start < previous_start:
                ctx.fail("WL-02", f"block starts at line {start}, before the previous "
                                  f"block's start ({previous_start}); blocks are emitted "
                                  f"in file order", bid)
            previous_start = start
        digest = b.get("sha256")
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            ctx.fail("WL-02", f"sha256 must be 64 lowercase hex characters, got "
                              f"{digest!r}", bid)


def _wl03(ctx: _Ctx, source_lines: Sequence[str], degraded: bool) -> None:
    non_blank = {i for i, line in enumerate(source_lines, start=1) if line.strip()}
    covered: dict[int, list[str]] = {}
    for b in ctx.blocks:
        lines_ = b.get("lines")
        if not (isinstance(lines_, list) and len(lines_) == 2):
            continue
        try:
            start, end = int(lines_[0]), int(lines_[1])
        except (TypeError, ValueError):
            continue
        for i in range(start, end + 1):
            if i in non_blank:
                covered.setdefault(i, []).append(str(b.get("block_id")))
    report = ctx.warn if degraded else ctx.fail
    for line_no in sorted(i for i, owners in covered.items() if len(owners) > 1):
        owners = covered[line_no]
        report("WL-03", f"line {line_no} is covered by {len(owners)} blocks "
                        f"({', '.join(owners)}); every non-blank line sits in exactly one "
                        f"block (WR-S7)")
    missing = sorted(non_blank - set(covered))
    if missing:
        shown = ", ".join(str(i) for i in missing[:12])
        more = "" if len(missing) <= 12 else f" (+{len(missing) - 12} more)"
        report("WL-03", f"non-blank line(s) {shown}{more} are in no block (WR-S7)")


def _wl04(ctx: _Ctx) -> None:
    for b in ctx.blocks:
        bid = b.get("block_id")
        disp = b.get("disposition")
        if disp not in (None, "") and disp not in wr.DISPOSITIONS:
            ctx.fail("WL-04", f"disposition {disp!r} is not one of "
                              f"{', '.join(wr.DISPOSITIONS)}", bid)
        density = b.get("density")
        if density not in (None, "") and density not in wr.DENSITIES:
            ctx.fail("WL-04", f"density {density!r} is not one of "
                              f"{', '.join(wr.DENSITIES)}", bid)
        conf = (b.get("prediction") or {}).get("confidence")
        if conf not in (None, "") and conf not in wr.CONFIDENCES:
            ctx.fail("WL-04", f"prediction.confidence {conf!r} is not one of "
                              f"{', '.join(wr.CONFIDENCES)}", bid)
        dtype = (b.get("divergence") or {}).get("type")
        if dtype not in (None, "") and dtype not in wr.DIVERGENCE_TYPES:
            ctx.fail("WL-04", f"divergence.type {dtype!r} is not one of "
                              f"{', '.join(wr.DIVERGENCE_TYPES)}", bid)
    for i, item in enumerate(ctx.ledger.get("assumption_export") or []):
        if not isinstance(item, dict):
            continue
        stated = item.get("stated_by")
        if stated not in (None, "") and stated not in wr.STATED_BY:
            ctx.fail("WL-04", f"assumption_export[{i}].stated_by {stated!r} is not one of "
                              f"{', '.join(wr.STATED_BY)}", item.get("block_id"))
    for i, rev in enumerate(ctx.session.get("reviewers") or []):
        if not isinstance(rev, dict):
            continue
        role = rev.get("role")
        if role not in (None, "") and role not in wr.REVIEWER_ROLES:
            ctx.fail("WL-04", f"session.reviewers[{i}].role {role!r} is not one of "
                              f"{', '.join(wr.REVIEWER_ROLES)}")
    mode = ctx.session.get("mode")
    if mode not in (None, "") and mode not in wr.SESSION_MODES:
        ctx.fail("WL-04", f"session.mode {mode!r} is not one of "
                          f"{', '.join(wr.SESSION_MODES)}")


def _wl05(ctx: _Ctx) -> None:
    """Endorsement integrity, stated once in both directions (WR-Q7).

    `endorsed_prediction: true` requires `disposition: confirmed` and an empty
    `author_account`; equivalently, any non-empty author field requires
    `endorsed_prediction: false`. The two readings are the same pairing, so a block that
    breaks it is reported once per broken half and never twice for the same half.
    """
    for b in ctx.blocks:
        bid = b.get("block_id")
        endorsed = bool(b.get("endorsed_prediction"))
        if not endorsed:
            continue
        if b.get("disposition") != "confirmed":
            ctx.fail("WL-05", f"endorsed_prediction is true but disposition is "
                              f"{b.get('disposition')!r}; an endorsement is a "
                              f"confirmation (WR-Q7)", bid)
        if _has_author_text(b.get("author_account")):
            ctx.fail("WL-05", "endorsed_prediction is true but author_account carries "
                              "text; an endorsement means the author wrote nothing to "
                              "compare the prediction against (WR-Q7)", bid)


def _wl06(ctx: _Ctx) -> None:
    for b in ctx.blocks:
        if not b.get("disposition"):
            continue
        bid = b.get("block_id")
        reviewer = b.get("reviewer")
        if not (isinstance(reviewer, str) and reviewer.strip()):
            ctx.fail("WL-06", "block carries a disposition but no reviewer (WR-O3)", bid)
        if not b.get("answered_at"):
            ctx.fail("WL-06", "block carries a disposition but no answered_at", bid)


def _wl07(ctx: _Ctx) -> None:
    prep = ctx.session.get("prep_completed")
    dispositioned = [b for b in ctx.blocks if b.get("disposition")]
    if dispositioned and not prep:
        ctx.fail("WL-07", f"{len(dispositioned)} block(s) carry a disposition but "
                          f"session.prep_completed is unset; only war_room_prep.py "
                          f"finalize sets it (WR-P1)")
        return
    if not prep:
        return
    prep_ts = _parse_ts(prep)
    for b in ctx.blocks:
        answered = b.get("answered_at")
        if not answered:
            continue
        bid = b.get("block_id")
        answered_ts = _parse_ts(answered)
        later = (answered_ts > prep_ts) if (prep_ts and answered_ts) \
            else (str(answered) > str(prep))
        if not later:
            ctx.fail("WL-07", f"answered_at {answered} is not later than "
                              f"session.prep_completed {prep}", bid)
        for i, item in enumerate(b.get("dissent") or []):
            if not isinstance(item, dict) or not item.get("answered_at"):
                continue
            d_ts = _parse_ts(item["answered_at"])
            ok = (d_ts > prep_ts) if (prep_ts and d_ts) \
                else (str(item["answered_at"]) > str(prep))
            if not ok:
                ctx.fail("WL-07", f"dissent[{i}].answered_at {item['answered_at']} is not "
                                  f"later than session.prep_completed {prep}", bid)


def _wl08(ctx: _Ctx) -> None:
    """Structural fields only. Free text is never checked (WR-Q6)."""
    candidates: list[tuple[str, str, str | None]] = []
    path = (ctx.script or {}).get("path")
    if isinstance(path, str):
        candidates.append(("script.path", path, None))
    for key, value in _walk_strings(ctx.ledger.get("project") or {}, "project"):
        candidates.append((key, value, None))
    for i, value in enumerate(ctx.session.get("source_reports") or []):
        if isinstance(value, str):
            candidates.append((f"session.source_reports[{i}]", value, None))
    for b in ctx.blocks:
        bid = b.get("block_id")
        for i, value in enumerate((b.get("evidence") or {}).get("sources") or []):
            if isinstance(value, str):
                candidates.append((f"evidence.sources[{i}]", value, bid))
    for key, value in _path_keys(ctx.ledger, "ledger"):
        candidates.append((key, value, None))
    for key, value, bid in candidates:
        if _is_absolute(value):
            ctx.fail("WL-08", f"{key} is an absolute path ({value!r}); structural paths are "
                              f"project-relative and the project root is never stored "
                              f"(WR-A5)", bid)


def _wl09(ctx: _Ctx) -> None:
    if not ctx.session.get("reconciled"):
        return
    for b in ctx.blocks:
        if not b.get("disposition") or not b.get("discussed"):
            continue
        div = b.get("divergence") or {}
        if div.get("match") is None:
            ctx.fail("WL-09", "session.reconciled is set but divergence.match is null on a "
                              "discussed block; an unset divergence is not a match (WR-P4)",
                     b.get("block_id"))


def _wl10(ctx: _Ctx) -> None:
    known = {str(r.get("id")) for r in (ctx.session.get("reviewers") or [])
             if isinstance(r, dict) and r.get("id")}
    for b in ctx.blocks:
        bid = b.get("block_id")
        reviewer = b.get("reviewer")
        if reviewer and str(reviewer) not in known:
            ctx.fail("WL-10", f"reviewer {reviewer!r} is not listed in "
                              f"session.reviewers[] (WR-Q9)", bid)
        for i, item in enumerate(b.get("dissent") or []):
            if not isinstance(item, dict):
                continue
            who = item.get("reviewer")
            if who and str(who) not in known:
                ctx.fail("WL-10", f"dissent[{i}].reviewer {who!r} is not listed in "
                                  f"session.reviewers[] (WR-O3)", bid)


def _wl11(ctx: _Ctx) -> None:
    ids = {b.get("block_id") for b in ctx.blocks}
    unresolved = {b.get("block_id") for b in ctx.blocks
                  if b.get("disposition") == "unresolved"}
    for i, item in enumerate(ctx.ledger.get("assumption_export") or []):
        if not isinstance(item, dict):
            ctx.fail("WL-11", f"assumption_export[{i}] is not a mapping")
            continue
        bid = item.get("block_id")
        if bid not in ids:
            ctx.fail("WL-11", f"assumption_export[{i}] names block {bid!r}, which is not in "
                              f"this ledger", bid)
    for i, item in enumerate(ctx.ledger.get("open_questions") or []):
        if not isinstance(item, dict):
            ctx.fail("WL-11", f"open_questions[{i}] is not a mapping")
            continue
        bid = item.get("block_id")
        if bid not in ids:
            ctx.fail("WL-11", f"open_questions[{i}] names block {bid!r}, which is not in "
                              f"this ledger", bid)
        elif bid not in unresolved:
            ctx.fail("WL-11", f"open_questions[{i}] names block {bid!r}, whose disposition "
                              f"is not 'unresolved'", bid)


def _wl12(ctx: _Ctx) -> None:
    history = ctx.session.get("history")
    if ctx.session.get("prep_completed") and not history:
        ctx.fail("WL-12", "session.prep_completed is set but session.history[] is empty; "
                          "session dates live in the history (WR-O7)")
        return
    for i, item in enumerate(history or []):
        if not isinstance(item, dict):
            ctx.fail("WL-12", f"session.history[{i}] is not a mapping")
            continue
        for key in ("event", "at"):
            if not item.get(key):
                ctx.fail("WL-12", f"session.history[{i}] has no {key}")
        event = item.get("event")
        if event and event not in wr.HISTORY_EVENTS:
            ctx.fail("WL-12", f"session.history[{i}].event {event!r} is not one of "
                              f"{', '.join(wr.HISTORY_EVENTS)}")


def _wl13(ctx: _Ctx, source_lines: Sequence[str], degraded: bool) -> None:
    total = len(source_lines)
    for b in ctx.blocks:
        recorded = b.get("sha256")
        lines_ = b.get("lines")
        if not isinstance(recorded, str) or not (isinstance(lines_, list) and len(lines_) == 2):
            continue
        try:
            start, end = int(lines_[0]), int(lines_[1])
        except (TypeError, ValueError):
            continue
        if not (1 <= start <= end <= total):
            if not b.get("drift"):
                ctx.fail("WL-13", f"lines {start}-{end} are outside the source file "
                                  f"({total} lines) and the block is not marked drift",
                         b.get("block_id"))
            continue
        current = wr.wr_a1_hash(source_lines, start, end)
        if current == recorded:
            continue
        if b.get("drift"):
            continue  # a recorded, honest drift (WR-A3); not a lint failure
        ctx.fail("WL-13", f"sha256 does not match lines {start}-{end} of the source "
                          f"(recorded {recorded[:12]}..., current {current[:12]}...) and "
                          f"the block is not marked drift", b.get("block_id"))
    file_hash = (ctx.script or {}).get("sha256")
    if isinstance(file_hash, str) and file_hash:
        current_file = wr.wr_a1_file_hash(source_lines)
        if current_file != file_hash:
            report = ctx.warn if degraded else ctx.fail
            report("WL-13", f"script.sha256 does not match the whole file "
                            f"(recorded {file_hash[:12]}..., current {current_file[:12]}...)")


def _wl14(ctx: _Ctx) -> None:
    for b in ctx.blocks:
        bid = b.get("block_id")
        for i, item in enumerate(b.get("dissent") or []):
            if not isinstance(item, dict):
                ctx.fail("WL-14", f"dissent[{i}] is not a mapping", bid)
                continue
            for key in ("reviewer", "answered_at", "disposition"):
                if not item.get(key):
                    ctx.fail("WL-14", f"dissent[{i}] has no {key}; a dissent item carries "
                                      f"reviewer, answered_at, disposition, author_account, "
                                      f"and endorsed_prediction (WR-O6)", bid)
            disp = item.get("disposition")
            if disp and disp not in wr.DISPOSITIONS:
                ctx.fail("WL-14", f"dissent[{i}].disposition {disp!r} is not one of "
                                  f"{', '.join(wr.DISPOSITIONS)}", bid)


def _degraded(ctx: _Ctx, source_lines: Sequence[str]) -> bool:
    """True when the file no longer is what prep recorded, so ranges are notes, not law.

    Two conditions, either of which degrades WL-03 and the whole-file half of WL-13
    from failures to warning lines:

    * a block carries `drift: true` -- a recorded, honest mismatch (WR-A3);
    * `script.sha256` does not match the current file, even while every block hash still
      reproduces. This covers a relocation (WR-A2), which only happens after the file
      changed, and the append-only edit: a line added below the last block leaves every
      block intact, so no block is flagged, yet coverage and the whole-file hash both
      fail. Without this condition a mid-session edit made every later save fail lint and
      nothing could clear it, which is the opposite of what D11 asks for -- a source edit
      during a session produces flags, not failed saves.

    `relocated_from` alone does not degrade: `war_room_prep.py verify --accept-relocations`
    re-stamps `script.sha256`, and from then on coverage is judged strictly (D-11).

    Per-block hash mismatches are not degraded by any of this: WL-13 still fails a block
    whose recorded digest does not reproduce unless that block itself carries `drift`.
    """
    if any(b.get("drift") for b in ctx.blocks):
        return True
    recorded = (ctx.script or {}).get("sha256")
    if isinstance(recorded, str) and recorded:
        return wr.wr_a1_file_hash(source_lines) != recorded
    return False


# --------------------------------------------------------------------------- entry point
def lint(ledger: dict, project_root: Path | None = None) -> LintResult:
    """Run every check. `project_root` enables WL-03 and WL-13; None means resolve per D2."""
    ctx = _Ctx(ledger)
    if not _wl01(ctx):
        return ctx.result

    _wl02(ctx)
    _wl04(ctx)
    _wl05(ctx)
    _wl06(ctx)
    _wl07(ctx)
    _wl08(ctx)
    _wl09(ctx)
    _wl10(ctx)
    _wl11(ctx)
    _wl12(ctx)
    _wl14(ctx)

    source_lines: list[str] | None = None
    try:
        root = wr.resolve_project_root(project_root, ctx.ledger)
        source_lines = wr.wr_a1_lines(wr.resolve_script(root, ctx.ledger))
    except (wr.WarRoomError, OSError, UnicodeDecodeError) as exc:
        ctx.warn("WL-03", f"skipped: the reviewed source did not resolve ({exc})")
        ctx.warn("WL-13", f"skipped: the reviewed source did not resolve ({exc})")

    if source_lines is not None:
        # After a real edit the recorded ranges describe the file as it was, so coverage
        # and the whole-file hash become notes rather than failures (D11).
        degraded = _degraded(ctx, source_lines)
        _wl03(ctx, source_lines, degraded)
        _wl13(ctx, source_lines, degraded)
    return ctx.result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="war_room_lint.py",
        description="Lint a war-room ledger.yaml (WL-01..WL-14).",
    )
    ap.add_argument("ledger", help="Path to ledger.yaml")
    ap.add_argument("--project-root", default=None,
                    help="Root of the reviewed project (the directory holding PROJECT.md). "
                         "Without it, the nearest PROJECT.md root above the working "
                         "directory is used, and only when its basename matches project.id.")
    ap.add_argument("--json", action="store_true",
                    help="Emit a JSON result instead of one line per failure")
    args = ap.parse_args(argv)

    path = Path(args.ledger).expanduser()
    if not path.is_file():
        print(f"No ledger at {path}", file=sys.stderr)
        return 2
    try:
        ledger = wr.load_ledger(path)
    except Exception as exc:  # a ledger that will not parse is a failure, not a crash
        if args.json:
            print(json.dumps({"ok": False, "failures": [
                {"code": "WL-01", "block_id": None, "message": f"unreadable ledger: {exc}"}],
                "warnings": []}))
        else:
            print(f"WL-01: unreadable ledger: {exc}")
        return 1

    root: Path | None = None
    if args.project_root:
        # D1/WR-A5: an explicit root whose basename is not the ledger's `project.id`
        # describes different code, and linting hashes against it would compare this
        # ledger to another project's file, so `resolve_project_root` refuses it.
        try:
            resolved = wr.resolve_project_root(args.project_root, ledger)
        except wr.WarRoomError as exc:
            if args.json:
                # Same envelope as every other result, so a machine caller never has to
                # parse an empty stdout. The code is not a WL- code because nothing in
                # the ledger is wrong: the invocation is.
                print(json.dumps({"ok": False, "warnings": [], "failures": [
                    {"code": "PROJECT-ROOT", "block_id": None, "message": str(exc)}]}))
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        root = resolved

    result = lint(ledger, root)
    if args.json:
        print(json.dumps(result.as_dict()))
        return 0 if result.ok else 1
    for warning in result.warnings:
        print(f"warning: {warning.line()}", file=sys.stderr)
    for failure in result.failures:
        print(failure.line())
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
