#!/usr/bin/env python3
"""Report literature catalog entries not verified recently.

An entry's age runs from `last_verified_on`, or from `added_on` when it was never verified;
both fields belong to the one catalog schema in Infrastructure/references/literature/README.md,
which validate_literature_catalog.py checks. Archived entries are skipped.

Tested by Infrastructure/scripts/test_knowledge_stores.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_literature_catalog import load_catalog, parse_date  # noqa: E402

import yaml  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check staleness of literature catalog entries.")
    parser.add_argument("--catalog", default="Infrastructure/references/literature/catalog.yaml",
                        help="Repository-relative path to catalog YAML.")
    parser.add_argument("--repo-root", default=None,
                        help="Repository root path. Defaults to script-derived root.")
    parser.add_argument("--warning-days", default=180, type=int,
                        help="Warn when an entry has not been verified in this many days.")
    parser.add_argument("--fail-on-warning", action="store_true",
                        help="Exit with status 1 if stale entries are found.")
    return parser.parse_args(argv)


def find_stale(entries: list[Any], today: dt.date, warning_days: int
               ) -> tuple[list[str], list[str], int]:
    """Return (stale warnings, info notes, entries checked)."""
    warnings: list[str] = []
    info: list[str] = []
    checked = 0
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("status") == "archived":
            continue
        entry_id = entry.get("id", "<missing-id>")
        added_on = parse_date(entry.get("added_on"))
        last_verified = parse_date(entry.get("last_verified_on"))
        reference = last_verified or added_on
        if reference is None:
            info.append(f"{entry_id}: neither `last_verified_on` nor `added_on` is a valid date; "
                        "cannot compute staleness.")
            continue
        checked += 1
        age_days = (today - reference).days
        if age_days <= warning_days:
            continue
        if last_verified is None:
            warnings.append(f"{entry_id}: stale ({age_days} days since added_on={reference.isoformat()}); "
                            "set `last_verified_on` after re-checking the source.")
        else:
            warnings.append(f"{entry_id}: stale ({age_days} days since "
                            f"last_verified_on={reference.isoformat()}).")
    return warnings, info, checked


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    catalog_path = (repo_root / args.catalog).resolve()

    if not catalog_path.exists():
        print(f"ERROR: catalog file does not exist: {catalog_path}", file=sys.stderr)
        return 1
    try:
        catalog = load_catalog(catalog_path)
    except yaml.YAMLError as exc:
        print(f"ERROR: unable to load catalog: {exc}", file=sys.stderr)
        return 1

    entries = catalog.get("entries", []) if isinstance(catalog, dict) else []
    if not isinstance(entries, list):
        print("ERROR: catalog `entries` must be a list.", file=sys.stderr)
        return 1

    warnings, info, checked = find_stale(entries, dt.date.today(), args.warning_days)
    if warnings:
        print(f"Catalog staleness check found {len(warnings)} stale entr"
              f"{'y' if len(warnings) == 1 else 'ies'} (threshold: {args.warning_days} days).")
        for item in warnings:
            print(f"- WARNING: {item}")
    else:
        print(f"Catalog staleness check passed: no stale entries above {args.warning_days} days "
              f"across {checked} checked entr{'y' if checked == 1 else 'ies'}.")
    for item in info:
        print(f"- INFO: {item}")
    return 1 if warnings and args.fail_on_warning else 0


if __name__ == "__main__":
    raise SystemExit(main())
