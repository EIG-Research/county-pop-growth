#!/usr/bin/env python3
"""Validate the literature catalog against its one schema.

The schema is documented in Infrastructure/references/literature/README.md; this script is
the check, and check_catalog_staleness.py reads the same `added_on` and `last_verified_on`
fields. Paths (`path`, `summary_path`) resolve from the repository root.

Tested by Infrastructure/scripts/test_knowledge_stores.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from localapp.yamlio import Loader  # noqa: E402  (exits with an install hint without PyYAML)

import yaml  # noqa: E402

REQUIRED_FIELDS = {"id", "title", "authors", "year", "type", "topic_tags", "path", "source_url",
                   "added_on", "status", "relevance_note"}
OPTIONAL_FIELDS = {"doi", "last_verified_on", "summary_path"}
# Keys from the retired README schema, with the field that replaced each one.
RETIRED_FIELDS = {"added": "added_on", "verified": "last_verified_on", "tags": "topic_tags"}
ALLOWED_TYPES = {"paper", "data_dictionary", "codebook", "technical_note", "other"}
ALLOWED_STATUS = {"raw", "parsed", "summarized", "verified", "archived"}
# A bare DOI (no https://doi.org/ prefix): "10.", a registrant code, "/", a suffix.
DOI = re.compile(r"^10\.\d{4,9}/\S+$")


def load_catalog(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.load(fh, Loader=Loader)  # noqa: S506 - Loader is a SafeLoader subclass


def parse_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_path(label: str, key: str, value: Any, repo_root: Path, errors: list[str]) -> None:
    if not _text(value):
        errors.append(f"{label}: `{key}` must be a non-empty repository-relative path string.")
    elif value.startswith("/"):
        errors.append(f"{label}: `{key}` must be repository-relative, not absolute.")
    else:
        target = (repo_root / value).resolve()
        if not target.exists():
            errors.append(f"{label}: `{key}` does not exist: `{value}`.")
        elif target.is_dir():
            errors.append(f"{label}: `{key}` points to a directory, expected a file: `{value}`.")


def validate_entry(label: str, entry: dict, repo_root: Path, today: dt.date,
                   errors: list[str]) -> None:
    missing = REQUIRED_FIELDS - set(entry)
    if missing:
        errors.append(f"{label}: missing required keys: {', '.join(sorted(missing))}.")
    for old, new in RETIRED_FIELDS.items():
        if old in entry:
            errors.append(f"{label}: `{old}` is retired; use `{new}`.")
    unknown = set(entry) - REQUIRED_FIELDS - OPTIONAL_FIELDS - set(RETIRED_FIELDS)
    if unknown:
        errors.append(f"{label}: unknown keys {', '.join(sorted(unknown))} (schema: "
                      f"Infrastructure/references/literature/README.md).")

    if "title" in entry and not _text(entry["title"]):
        errors.append(f"{label}: `title` must be a non-empty string.")
    authors = entry.get("authors")
    if "authors" in entry and (not isinstance(authors, list) or not authors
                               or not all(_text(a) for a in authors)):
        errors.append(f"{label}: `authors` must be a non-empty list of names (an agency for "
                      f"an official document).")
    year = entry.get("year")
    if "year" in entry and not (isinstance(year, int) and not isinstance(year, bool)
                                and 1500 <= year <= today.year + 1):
        errors.append(f"{label}: `year` must be a four-digit publication year.")
    if "type" in entry and entry["type"] not in ALLOWED_TYPES:
        errors.append(f"{label}: `type` must be one of: {', '.join(sorted(ALLOWED_TYPES))}.")
    tags = entry.get("topic_tags")
    if "topic_tags" in entry and (not isinstance(tags, list) or not tags
                                  or not all(_text(t) for t in tags)):
        errors.append(f"{label}: `topic_tags` must be a non-empty list of strings.")
    if "path" in entry:
        _check_path(label, "path", entry["path"], repo_root, errors)
    if entry.get("summary_path") is not None:
        _check_path(label, "summary_path", entry["summary_path"], repo_root, errors)
    url = entry.get("source_url")
    if url is not None and not (_text(url) and url.startswith(("http://", "https://"))):
        errors.append(f"{label}: `source_url` must be null or start with `http://` or `https://`.")
    if "doi" in entry and not (_text(entry["doi"]) and DOI.match(entry["doi"])):
        errors.append(f"{label}: `doi` must be a bare DOI such as `10.1257/aer.20190300`.")

    added = parse_date(entry.get("added_on"))
    if "added_on" in entry and added is None:
        errors.append(f"{label}: `added_on` must be an ISO date (`YYYY-MM-DD`).")
    if "last_verified_on" in entry:
        verified = parse_date(entry["last_verified_on"])
        if verified is None:
            errors.append(f"{label}: `last_verified_on` must be an ISO date (`YYYY-MM-DD`).")
        elif verified > today:
            errors.append(f"{label}: `last_verified_on` is in the future.")
    status = entry.get("status")
    if "status" in entry and status not in ALLOWED_STATUS:
        errors.append(f"{label}: `status` must be one of: {', '.join(sorted(ALLOWED_STATUS))}.")
    if status == "verified" and "last_verified_on" not in entry:
        errors.append(f"{label}: a `verified` entry records `last_verified_on`, the date a "
                      f"person checked it against the source.")
    if "relevance_note" in entry and not _text(entry["relevance_note"]):
        errors.append(f"{label}: `relevance_note` must be a non-empty string.")


def validate_catalog(catalog: Any, repo_root: Path, today: dt.date | None = None
                     ) -> tuple[list[str], list[str], int]:
    today = today or dt.date.today()
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(catalog, dict):
        return ["Catalog root must be a YAML mapping."], warnings, 0
    if not isinstance(catalog.get("version"), int):
        errors.append("Top-level `version` must be an integer.")
    if parse_date(catalog.get("last_updated")) is None:
        errors.append("Top-level `last_updated` must be an ISO date (`YYYY-MM-DD`).")
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        errors.append("Top-level `entries` must be a list (use [] if none).")
        return errors, warnings, 0

    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        label = f"entry #{index}"
        if not isinstance(entry, dict):
            errors.append(f"{label}: entry must be a mapping.")
            continue
        entry_id = entry.get("id")
        if not _text(entry_id):
            errors.append(f"{label}: `id` must be a non-empty string.")
        else:
            if entry_id in seen:
                errors.append(f"{label}: duplicate `id` value `{entry_id}`.")
            seen.add(entry_id)
            label = f"entry `{entry_id}`"
        validate_entry(label, entry, repo_root, today, errors)

    if not entries:
        warnings.append("Catalog has no entries yet.")
    return errors, warnings, len(entries)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Infrastructure literature catalog entries.")
    parser.add_argument("--catalog", default="Infrastructure/references/literature/catalog.yaml",
                        help="Repository-relative path to catalog YAML.")
    parser.add_argument("--repo-root", default=None,
                        help="Repository root path. Defaults to script-derived root.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    script_root = Path(__file__).resolve().parents[2]
    repo_root = Path(args.repo_root).resolve() if args.repo_root else script_root
    catalog_path = (repo_root / args.catalog).resolve()

    if not catalog_path.exists():
        print(f"ERROR: catalog file does not exist: {catalog_path}", file=sys.stderr)
        return 1
    try:
        catalog = load_catalog(catalog_path)
    except yaml.YAMLError as exc:
        print(f"ERROR: catalog is not valid YAML: {exc}", file=sys.stderr)
        return 1

    errors, warnings, entry_count = validate_catalog(catalog, repo_root)
    if errors:
        print(f"Literature catalog validation failed with {len(errors)} error(s) "
              f"and {len(warnings)} warning(s).", file=sys.stderr)
        for err in errors:
            print(f"- ERROR: {err}", file=sys.stderr)
        for warn in warnings:
            print(f"- WARNING: {warn}", file=sys.stderr)
        return 1

    print(f"Literature catalog validation passed for {entry_count} entr"
          f"{'y' if entry_count == 1 else 'ies'} with {len(warnings)} warning(s).")
    for warn in warnings:
        print(f"- WARNING: {warn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
