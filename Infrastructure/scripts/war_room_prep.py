#!/usr/bin/env python3
"""Prep tooling for the code war room: build, check, re-segment, and finalize a ledger.

The prep pass owns the mechanical half of a war room. This script produces the block
boundaries, the hashes, the block ids, the language, the whole-file hash, and the line
count (D6). The agent owns only `title`, `density`, and `prediction` -- the judgment
fields -- and fills them into the skeleton this script emits.

Segmentation is a pure function of the file's bytes; the algorithm is stated in
`war_room_lib`'s module docstring and mirrored in
`Infrastructure/rules/code-war-room-segmentation.md`, so a human can predict every boundary.

Subcommands
    skeleton   Segment a script and emit a schema v2 ledger skeleton. `--fixture` marks
               the result `session.fixture: true`, which every test ledger carries. It
               refuses to overwrite an existing `--out` unless `--force` is passed, so a
               re-run cannot destroy a filled ledger.
    fill       Apply a prediction set (title/density/prediction per block id) to a
               skeleton. A helper for fixtures and tests; an agent may also edit the
               skeleton directly.
    verify     Recompute every hash under WR-A1, re-anchor by hash (WR-A2), and report.
               With --write, persist `drift` and `drift_after_disposition` (WR-A3/A4).
               With --accept-relocations, also clear `relocated_from` and re-stamp
               `script.sha256`; refused while a block drifts or when lint fails.
    merge      Merge a block with the one after it (WR-S5).
    split      Split a block before a line (WR-S5).
    finalize   Check that prep is complete, set `session.prep_completed`, and append the
               `prep` entry to `session.history[]`. The only writer of `prep_completed`.
    locate     Print the ledger path for a script (M1: `<war_rooms>/<project id>--<script
               path, / as -->/ledger.yaml`), say on stderr whether it exists, and refuse a
               ledger there that names another project or script.

Every subcommand holds the ledger's lock (`ledger.yaml.lock`) from load to save, so it
waits while the app server or another CLI is saving; after 10 s it exits 1 naming the
process that holds the lock.

Exit codes: 0 success, 1 a mismatch or a refusal, 2 a usage error.

Usage:
    python3 Infrastructure/scripts/war_room_prep.py skeleton <script> \
        --project-root <dir> --out <ledger.yaml> [--mode ordered|fast-forward] [--fixture] \
        [--force]
    python3 Infrastructure/scripts/war_room_prep.py verify <ledger.yaml> \
        [--project-root <dir>] [--write | --accept-relocations]
    python3 Infrastructure/scripts/war_room_prep.py locate <script> --project-root <dir> \
        [--war-rooms <dir>]

Dependencies: Python 3.11+ and PyYAML.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import war_room_lib as wr  # noqa: E402
import war_room_lint as wl  # noqa: E402

WAR_ROOMS = Path(__file__).resolve().parents[2] / "records" / "war_rooms"


# --------------------------------------------------------------------------- helpers
def _ledger_path(path_str: str) -> Path:
    path = Path(path_str).expanduser().resolve()
    if not path.is_file():
        raise wr.WarRoomError(f"no ledger at {path}")
    return path


def _load(path_str: str) -> tuple[Path, dict]:
    path = _ledger_path(path_str)
    return path, wr.load_ledger(path)


def _source_lines(ledger: dict, explicit_root: str | None) -> tuple[Path, Path, list[str]]:
    # D1: an explicit --project-root is checked against the ledger's project.id too, so a
    # root pointed at the wrong project fails loudly instead of hashing the wrong file.
    root = wr.resolve_project_root(explicit_root, ledger)
    script = wr.resolve_script(root, ledger)
    return root, script, wr.wr_a1_lines(script)


# --------------------------------------------------------------------------- skeleton
def cmd_skeleton(args: argparse.Namespace) -> int:
    root = Path(args.project_root).expanduser().resolve()
    if not (root / "PROJECT.md").is_file():
        raise wr.WarRoomError(f"--project-root {root} does not contain PROJECT.md")
    script = Path(args.script).expanduser().resolve()
    if not script.is_file():
        raise wr.WarRoomError(f"no script at {script}")
    ledger = wr.new_skeleton(script, root, mode=args.mode)
    if args.fixture:
        ledger["session"]["fixture"] = True
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with wr.locked_ledger(out):
        if out.exists() and not args.force:
            # A skeleton has empty predictions: overwriting a filled ledger would destroy
            # the agent's committed readings, which WR-P3 says nothing may rewrite.
            raise wr.WarRoomError(
                f"{out} already exists; refusing to overwrite it. "
                f"Pass --force to replace it, or choose a different --out"
            )
        wr.save_ledger(out, ledger)
    print(f"{ledger['script']['path']}: {len(ledger['blocks'])} blocks, "
          f"{ledger['script']['line_count']} lines, language {ledger['script']['language']}, "
          f"mode {ledger['session']['mode']}")
    print(f"Wrote {out}")
    return 0


# --------------------------------------------------------------------------- fill
def cmd_fill(args: argparse.Namespace) -> int:
    path, ledger = _load(args.ledger)
    preds = wr.load_ledger(Path(args.predictions).expanduser().resolve())
    unknown = sorted(set(preds) - {b["block_id"] for b in ledger.get("blocks") or []})
    if unknown:
        raise wr.WarRoomError(f"prediction set names unknown blocks: {', '.join(unknown)}")
    filled = 0
    for b in ledger.get("blocks") or []:
        entry = preds.get(b["block_id"])
        if not entry:
            continue
        b["title"] = entry.get("title", b.get("title", ""))
        b["density"] = entry.get("density", b.get("density", ""))
        pred = dict(entry.get("prediction") or {})
        b["prediction"] = {
            "what_it_does": pred.get("what_it_does", ""),
            "inferred_intent": pred.get("inferred_intent", ""),
            "assumptions": list(pred.get("assumptions") or []),
            "confidence": pred.get("confidence", ""),
        }
        filled += 1
    wr.save_ledger(path, ledger)
    print(f"Filled {filled}/{len(ledger.get('blocks') or [])} blocks in {path.name}")
    return 0


# --------------------------------------------------------------------------- verify
def cmd_verify(args: argparse.Namespace) -> int:
    path, ledger = _load(args.ledger)
    root, script, lines = _source_lines(ledger, args.project_root)
    report = wr.recompute_drift(ledger, lines)
    file_hash = wr.wr_a1_file_hash(lines)
    recorded_file_hash = (ledger.get("script") or {}).get("sha256")

    bad = [r for r in report if r["status"] == "drift"]
    moved = [r for r in report if r["status"] == "relocated"]
    print(f"Script : {script}")
    print(f"Blocks : {len(report)} checked, {len(bad)} drifted, {len(moved)} re-anchored")
    if recorded_file_hash and recorded_file_hash != file_hash:
        print(f"  note: whole-file hash changed (recorded {recorded_file_hash[:12]}..., "
              f"current {file_hash[:12]}...)")
    for r in moved:
        print(f"  RELOCATED {r['block_id']}: recorded lines "
              f"{r['recorded_lines'][0]}-{r['recorded_lines'][1]} -> current "
              f"{r['current_lines'][0]}-{r['current_lines'][1]}")
    for r in bad:
        print(f"  DRIFT {r['block_id']}: recorded lines "
              f"{r['recorded_lines'][0]}-{r['recorded_lines'][1]}, recorded hash "
              f"{r['recorded_sha256'][:12]}..., current hash "
              f"{(r['current_sha256'] or 'out-of-range')[:12]}..."
              + ("  [after disposition]" if r["drift_after_disposition"] else ""))
        if len(r["ambiguous_starts"]) > 1:
            print(f"    ambiguous: the recorded hash is at {len(r['ambiguous_starts'])} free "
                  f"ranges (starting at lines "
                  f"{', '.join(str(s) for s in r['ambiguous_starts'])}); not moved (WR-A3)")
        elif r["contested"]:
            print("    ambiguous: another block's hash matches the same range; neither "
                  "was moved (WR-A3)")
    if args.accept_relocations:
        return _accept_relocations(path, ledger, root, lines)
    if args.write:
        wr.save_ledger(path, ledger)
        print(f"Wrote drift flags to {path.name}")
    if bad:
        print(f"MISMATCH: {len(bad)} block(s) drifted")
        return 1
    print("OK: every block hash reproduces")
    return 0


def _accept_relocations(path: Path, ledger: dict, root: Path, lines: list[str]) -> int:
    """Adopt the current file as the reference once every block re-anchored cleanly (D-11).

    Clears `relocated_from` and re-stamps `script.sha256` and `line_count`, so lint judges
    coverage strictly again. Refused while any block carries drift, because the human
    resolves drift first (WR-A3), and refused when the result fails lint (I2): new lines
    that no block covers need a fresh prep, not an accept.
    """
    drifted = [b.get("block_id") for b in ledger.get("blocks") or [] if b.get("drift")]
    if drifted:
        print(f"REFUSED: {len(drifted)} block(s) carry drift ({', '.join(drifted)}); "
              f"resolve the drift before accepting relocations")
        return 1
    accepted = [b.get("block_id") for b in ledger.get("blocks") or [] if b.get("relocated_from")]
    for b in ledger.get("blocks") or []:
        if b.get("relocated_from"):
            b["relocated_from"] = None
    script = ledger.setdefault("script", {})
    script["sha256"] = wr.wr_a1_file_hash(lines)
    script["line_count"] = len(lines)
    result = wl.lint(ledger, root)
    if not result.ok:
        print(f"REFUSED: the accepted ledger would fail lint; {path.name} is unchanged")
        for failure in result.failures:
            print(f"  {failure.line()}")
        return 1
    wr.save_ledger(path, ledger)
    print(f"Accepted {len(accepted)} relocation(s) and re-stamped script.sha256 in {path.name}")
    return 0


# --------------------------------------------------------------------------- re-segment
def cmd_merge(args: argparse.Namespace) -> int:
    path, ledger = _load(args.ledger)
    _, _, lines = _source_lines(ledger, args.project_root)
    merged = wr.merge_blocks(ledger, args.block_id, lines, by=args.by)
    wr.save_ledger(path, ledger)
    print(f"Merged into {merged['block_id']} (lines {merged['lines'][0]}-{merged['lines'][1]}, "
          f"confidence {merged['prediction']['confidence']})")
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    path, ledger = _load(args.ledger)
    _, _, lines = _source_lines(ledger, args.project_root)
    parts = wr.split_block(ledger, args.block_id, args.at, lines, by=args.by)
    wr.save_ledger(path, ledger)
    for p in parts:
        print(f"Split produced {p['block_id']} (lines {p['lines'][0]}-{p['lines'][1]}, "
              f"confidence {p['prediction']['confidence']})")
    return 0


# --------------------------------------------------------------------------- finalize
def cmd_finalize(args: argparse.Namespace) -> int:
    path, ledger = _load(args.ledger)
    problems: list[str] = []
    for b in ledger.get("blocks") or []:
        bid = b.get("block_id")
        if not (b.get("title") or "").strip():
            problems.append(f"{bid}: title is empty")
        density = b.get("density")
        if density not in wr.DENSITIES:
            problems.append(f"{bid}: density {density!r} is not one of "
                            f"{', '.join(wr.DENSITIES)}")
        pred = b.get("prediction") or {}
        for field in ("what_it_does", "inferred_intent"):
            if not (pred.get(field) or "").strip():
                problems.append(f"{bid}: prediction.{field} is empty")
        if pred.get("confidence") not in wr.CONFIDENCES:
            problems.append(f"{bid}: prediction.confidence {pred.get('confidence')!r} is not "
                            f"one of {', '.join(wr.CONFIDENCES)}")
    if problems:
        print(f"REFUSED: prep is not complete ({len(problems)} problem(s))")
        for p in problems:
            print(f"  {p}")
        return 1

    session = ledger.setdefault("session", {})
    if session.get("prep_completed"):
        print(f"REFUSED: prep is already finalized "
              f"(session.prep_completed is {session['prep_completed']}); "
              f"finalize never re-stamps it or appends a second prep history entry")
        return 1
    session["prep_completed"] = wr.utc_now()
    session.setdefault("history", []).append(
        {"event": "prep", "at": session["prep_completed"], "by": args.by}
    )
    wr.save_ledger(path, ledger)
    print(f"Finalized {path.name}: prep_completed {session['prep_completed']}, "
          f"{len(ledger.get('blocks') or [])} blocks, "
          f"{len(session['history'])} history entr(y|ies)")
    return 0


# --------------------------------------------------------------------------- locate
def cmd_locate(args: argparse.Namespace) -> int:
    """WR-I5 / D-17: the one way to find a script's ledger, so no one builds a slug by hand."""
    root = Path(args.project_root).expanduser().resolve()
    if not (root / "PROJECT.md").is_file():
        raise wr.WarRoomError(f"--project-root {root} does not contain PROJECT.md")
    script = Path(args.script).expanduser().resolve()
    try:
        rel = script.relative_to(root).as_posix()
    except ValueError:
        raise wr.WarRoomError(f"{script} is not inside --project-root {root}") from None
    war_rooms = Path(args.war_rooms).expanduser().resolve() if args.war_rooms else WAR_ROOMS
    path = war_rooms / wr.slug_for(root.name, rel) / "ledger.yaml"
    if wr.locate_ledger(war_rooms, root.name, rel) is None:
        print(path)
        print("no ledger yet; a new session writes here", file=sys.stderr)
        return 0
    ledger = wr.load_ledger(path)
    wr.check_project_id(root, ledger)  # the directory name is a hint, not proof (WR-I5)
    recorded = (ledger.get("script") or {}).get("path")
    if recorded != rel:
        raise wr.WarRoomError(f"{path} records script.path {recorded!r}, not {rel!r}")
    blocks = ledger.get("blocks") or []
    done = sum(1 for b in blocks if isinstance(b, dict) and b.get("disposition"))
    print(path)  # only a checked ledger's path, so a refusal never hands one out
    print(f"found: {len(blocks)} blocks, {done} dispositioned", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- cli
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="war_room_prep.py",
        description="Deterministic prep tooling for a code war room.")
    sub = ap.add_subparsers(dest="command", required=True)

    sk = sub.add_parser("skeleton", help="Segment a script into a schema v2 ledger skeleton")
    sk.add_argument("script")
    sk.add_argument("--project-root", required=True)
    sk.add_argument("--out", required=True)
    sk.add_argument("--mode", choices=list(wr.SESSION_MODES), default="ordered")
    sk.add_argument("--fixture", action="store_true",
                    help="Mark the ledger session.fixture: true (test ledgers only)")
    sk.add_argument("--force", action="store_true",
                    help="Overwrite --out if it already exists (destroys a filled ledger)")
    sk.set_defaults(func=cmd_skeleton)

    fl = sub.add_parser("fill", help="Apply a prediction set to a skeleton")
    fl.add_argument("ledger")
    fl.add_argument("predictions")
    fl.set_defaults(func=cmd_fill)

    vf = sub.add_parser("verify", help="Recompute hashes; optionally persist drift flags")
    vf.add_argument("ledger")
    vf.add_argument("--project-root", default=None)
    vf.add_argument("--write", action="store_true")
    vf.add_argument("--accept-relocations", action="store_true",
                    help="Clear relocated_from and re-stamp script.sha256 (writes); "
                         "refused while any block drifts or if lint fails")
    vf.set_defaults(func=cmd_verify)

    mg = sub.add_parser("merge", help="Merge a block with the one after it")
    mg.add_argument("ledger")
    mg.add_argument("block_id")
    mg.add_argument("--project-root", default=None)
    mg.add_argument("--by", default=None)
    mg.set_defaults(func=cmd_merge)

    sp = sub.add_parser("split", help="Split a block before a line")
    sp.add_argument("ledger")
    sp.add_argument("block_id")
    sp.add_argument("--at", type=int, required=True)
    sp.add_argument("--project-root", default=None)
    sp.add_argument("--by", default=None)
    sp.set_defaults(func=cmd_split)

    fz = sub.add_parser("finalize", help="Close prep and stamp session.prep_completed")
    fz.add_argument("ledger")
    fz.add_argument("--by", default="code-interlocutor")
    fz.set_defaults(func=cmd_finalize)

    lc = sub.add_parser("locate", help="Print a script's ledger path and whether it exists")
    lc.add_argument("script")
    lc.add_argument("--project-root", required=True)
    lc.add_argument("--war-rooms", default=None,
                    help="The war_rooms directory (default: records/war_rooms in this repository)")
    lc.set_defaults(func=cmd_locate)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in ("skeleton", "locate"):
            return args.func(args)
        # Every other command loads, checks or mutates, and saves one ledger; the lock is
        # held across all of it, so the app server or another CLI cannot save in between
        # and have its change silently dropped (D-15).
        with wr.locked_ledger(_ledger_path(args.ledger)):
            return args.func(args)
    except wr.WarRoomError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
