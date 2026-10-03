#!/usr/bin/env python3
"""Validate required metadata for outputs using legacy EIG palettes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_FIELDS = [
    "legacy_palette_used",
    "legacy_set_id",
    "legacy_palette_justification",
    "approver",
    "approval_date",
]

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_metadata(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def validate(meta: dict) -> list[str]:
    errors: list[str] = []

    if "legacy_palette_used" not in meta:
        errors.append("Missing required field: legacy_palette_used")
        return errors

    if not isinstance(meta["legacy_palette_used"], bool):
        errors.append("legacy_palette_used must be true/false")
        return errors

    if meta["legacy_palette_used"] is False:
        return errors

    for field in REQUIRED_FIELDS[1:]:
        if field not in meta:
            errors.append(f"Missing required field when legacy_palette_used=true: {field}")
        elif isinstance(meta[field], str) and not meta[field].strip():
            errors.append(f"Field must be non-empty: {field}")

    approval_date = meta.get("approval_date")
    if isinstance(approval_date, str) and not DATE_PATTERN.match(approval_date):
        errors.append("approval_date must match YYYY-MM-DD")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata_json", help="Path to metadata JSON sidecar.")
    args = parser.parse_args()

    path = Path(args.metadata_json)
    if not path.exists():
        print(f"ERROR: Metadata file not found: {path}", file=sys.stderr)
        return 2

    try:
        meta = load_metadata(path)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    errors = validate(meta)
    if errors:
        print("FAIL: Legacy metadata validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("PASS: Legacy metadata validation successful.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
