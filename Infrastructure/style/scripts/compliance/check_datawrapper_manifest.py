#!/usr/bin/env python3
"""Validate a Datawrapper publish manifest against the EIG governance contract.

    python3 Infrastructure/style/scripts/compliance/check_datawrapper_manifest.py <manifest> [--tokens PATH]

The contract is `Infrastructure/style/docs/datawrapper-integration.md` §5. Each manifest
row (a CSV row, or a JSON object, list of objects, or {"rows": [...]}) must have:

- every required field, non-empty except `legacy_metadata_path`;
- a valid `palette_mode`, with `legacy_metadata_path` set exactly when it is `legacy`;
- `token_version` equal to the token file's `meta.version`, read at run time, so a
  published chart built from stale tokens fails;
- if `colors_sent` is present (the hex values the pipeline sent to Datawrapper), only
  non-legacy token colors, plus legacy token colors when `palette_mode` is `legacy`.
  This is the "no net-new hex" rule. In CSV, separate the values with `;`, `,`, `|`, or
  spaces; in JSON, give a list or such a string.

The token file defaults to `Infrastructure/style/tokens/eig-style-tokens.v1.json`, found
from this script's location; `--tokens` overrides it.

Exit codes: 0 valid; 1 validation errors; 2 the manifest or token file is missing or
unreadable.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = [
    "run_timestamp_utc",
    "figure_key",
    "chart_id",
    "chart_url",
    "rows_uploaded",
    "palette_mode",
    "token_source_path",
    "token_version",
    "legacy_metadata_path",
]

VALID_PALETTE_MODES = {"primary_2022", "legacy"}
DEFAULT_TOKENS = Path(__file__).resolve().parents[2] / "tokens" / "eig-style-tokens.v1.json"
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
COLOR_SPLIT_RE = re.compile(r"[;,|\s]+")
REGENERATE_HINT = (
    "reload the colors from the current token file "
    "(Infrastructure/style/tokens/eig-style-tokens.v1.json), republish, and rewrite the manifest"
)


class TokenPalette:
    """The token file's version and its non-legacy and legacy hex values (uppercase)."""

    def __init__(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self.version = str(data["meta"]["version"])
        colors = data.get("colors") or {}
        self.primary: set[str] = set()
        self.legacy: set[str] = set()
        for entry in [*(colors.get("brand") or []), *(colors.get("neutrals") or [])]:
            self._add(entry.get("hex"), entry.get("status"))
        for group in [*(colors.get("sequential") or []), *(colors.get("legacy_semantic_sets") or [])]:
            values = group.get("entries") or []
            for value in values.values() if isinstance(values, dict) else values:
                self._add(value, group.get("status"))
        for part in (data.get("tables") or {}).values():
            if isinstance(part, dict):
                for key, value in part.items():
                    if key.endswith("_hex"):
                        self._add(value, "primary")

    def _add(self, value: Any, status: Any) -> None:
        if isinstance(value, str) and HEX_RE.match(value):
            (self.legacy if status == "legacy" else self.primary).add(value.upper())


def _load_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            if "rows" in data and isinstance(data["rows"], list):
                return [dict(r) for r in data["rows"] if isinstance(r, dict)]
            return [dict(data)]
        if isinstance(data, list):
            return [dict(r) for r in data if isinstance(r, dict)]
        raise ValueError("JSON manifest must be an object or list of objects.")

    raise ValueError("Unsupported manifest format. Use .csv or .json.")


def _is_blank(value: object) -> bool:
    return value is None or str(value).strip() == ""


def _version_key(value: str) -> tuple[int, ...] | None:
    parts = value.strip().split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) else None


def _colors_sent(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v for v in COLOR_SPLIT_RE.split(str(value).strip()) if v]


def _validate_row(row: dict[str, Any], index: int, palette: TokenPalette) -> list[str]:
    errors: list[str] = []
    prefix = f"row {index}"

    for field in REQUIRED_FIELDS:
        if field not in row:
            errors.append(f"{prefix}: missing required field '{field}'")
            continue
        if _is_blank(row.get(field)):
            if field == "legacy_metadata_path":
                continue
            errors.append(f"{prefix}: field '{field}' must be non-empty")

    palette_mode = str(row.get("palette_mode", "")).strip()
    if palette_mode and palette_mode not in VALID_PALETTE_MODES:
        errors.append(
            f"{prefix}: field 'palette_mode' must be one of {sorted(VALID_PALETTE_MODES)}"
        )

    rows_uploaded = str(row.get("rows_uploaded", "")).strip()
    if rows_uploaded:
        try:
            val = int(rows_uploaded)
            if val < 0:
                errors.append(f"{prefix}: field 'rows_uploaded' must be >= 0")
        except ValueError:
            errors.append(f"{prefix}: field 'rows_uploaded' must be an integer")

    chart_url = str(row.get("chart_url", "")).strip()
    if chart_url and not (chart_url.startswith("http://") or chart_url.startswith("https://")):
        errors.append(f"{prefix}: field 'chart_url' must start with http:// or https://")

    legacy_path = str(row.get("legacy_metadata_path") or "").strip()
    if palette_mode == "legacy" and not legacy_path:
        errors.append(
            f"{prefix}: field 'legacy_metadata_path' is required when palette_mode=legacy"
        )
    if palette_mode == "primary_2022" and legacy_path:
        errors.append(
            f"{prefix}: field 'legacy_metadata_path' must be empty when palette_mode=primary_2022"
        )

    token_version = str(row.get("token_version") or "").strip()
    if token_version and token_version != palette.version:
        sent, current = _version_key(token_version), _version_key(palette.version)
        if sent is not None and current is not None and sent < current:
            errors.append(
                f"{prefix}: token_version {token_version} is older than the token file's "
                f"{palette.version}; {REGENERATE_HINT}"
            )
        else:
            errors.append(
                f"{prefix}: token_version {token_version} does not match the token file's "
                f"{palette.version}"
            )

    if not _is_blank(row.get("colors_sent")):
        allowed = palette.primary | (palette.legacy if palette_mode == "legacy" else set())
        for color in _colors_sent(row["colors_sent"]):
            if not HEX_RE.match(color):
                errors.append(f"{prefix}: colors_sent value '{color}' is not a #RRGGBB hex color")
            elif color.upper() in palette.legacy and color.upper() not in allowed:
                errors.append(
                    f"{prefix}: colors_sent {color} is a legacy token color; "
                    "legacy colors need palette_mode=legacy and a legacy metadata sidecar"
                )
            elif color.upper() not in allowed:
                errors.append(f"{prefix}: colors_sent {color} is not a token color (net-new hex)")

    return errors


def validate(path: Path, palette: TokenPalette) -> list[str]:
    try:
        rows = _load_rows(path)
    except (json.JSONDecodeError, ValueError) as exc:
        return [f"Invalid manifest: {exc}"]

    if not rows:
        return ["Manifest contains no data rows."]

    errors: list[str] = []
    for idx, row in enumerate(rows, start=1):
        errors.extend(_validate_row(row, idx, palette))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("manifest_path", help="Path to Datawrapper manifest (.csv or .json)")
    parser.add_argument(
        "--tokens",
        type=Path,
        default=DEFAULT_TOKENS,
        help="Token JSON to validate against (default: this repository's token file)",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest_path)
    if not manifest_path.exists():
        print(f"ERROR: Manifest file not found: {manifest_path}", file=sys.stderr)
        return 2
    try:
        palette = TokenPalette(args.tokens)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: cannot read token file {args.tokens}: {exc}", file=sys.stderr)
        return 2

    errors = validate(manifest_path, palette)
    if errors:
        print("FAIL: Datawrapper manifest validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("PASS: Datawrapper manifest validation successful.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
