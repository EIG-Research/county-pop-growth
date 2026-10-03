#!/usr/bin/env python3
"""Generate every style output derived from the canonical EIG token JSON.

The outputs are listed once, in `OUTPUTS`: the Python, R, and Stata token files, the
Stata graph scheme (`themes/stata/scheme-eig.scheme`), and the token tables doc
(`docs/_generated/tokens.md`).

Every output is written with LF line endings on every platform (`newline="\n"`), so
a regeneration is byte-identical to a clean checkout and the drift check
(`Infrastructure/scripts/check_style_token_drift.py`) means the same thing on Windows as
on Linux. Without it, Windows text mode writes CRLF.

Writing requires an explicit `--write`. A bare call (or `--check`) only compares the
fresh rendering with the files on disk and writes nothing, so running the script to see
what it does, or with `--help`, can never rewrite the tracked theme files.

    python3 Infrastructure/style/scripts/sync_tokens.py --write   # regenerate
    python3 Infrastructure/style/scripts/sync_tokens.py --check   # compare only

The token file is validated before anything is rendered: hex is authoritative, so a
color whose `rgb` differs from its hex is an error. An invalid token file writes nothing
in any mode.

Exit codes: 0 = files written (`--write`) or already in sync, 1 = out of sync (check
mode) or an invalid token file, 2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import pprint
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATH = ROOT / "tokens" / "eig-style-tokens.v1.json"
OUT_PY = ROOT / "themes" / "python" / "eig_tokens.py"
OUT_R = ROOT / "themes" / "r" / "eig_tokens.R"
OUT_DO = ROOT / "themes" / "stata" / "eig_tokens.do"
OUT_SCHEME = ROOT / "themes" / "stata" / "scheme-eig.scheme"
OUT_TOKENS_DOC = ROOT / "docs" / "_generated" / "tokens.md"

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _load_tokens() -> dict[str, Any]:
    return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))


def hex_to_rgb(value: str) -> list[int]:
    digits = value.lstrip("#")
    return [int(digits[i : i + 2], 16) for i in (0, 2, 4)]


def _color_entries(tokens: dict[str, Any]) -> list[dict[str, Any]]:
    """Every single-color token (id, hex, rgb) in the file: brand colors, then neutrals."""
    return list(tokens["colors"]["brand"]) + list(tokens["colors"].get("neutrals", []))


def _validate_tables(tokens: dict[str, Any], hex_by_id: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for part, spec in tokens["tables"].items():
        for key, value in spec.items():
            if key.endswith("_token") and value not in hex_by_id:
                errors.append(f"tables.{part}.{key}: unknown color token {value!r}")
    body = tokens["tables"]["body"]
    rule_token = body.get("rule_color_token")
    if rule_token in hex_by_id and body.get("rule_color_hex", "").upper() != hex_by_id[rule_token].upper():
        errors.append(
            f"tables.body.rule_color_hex {body.get('rule_color_hex')!r} does not match "
            f"{rule_token} ({hex_by_id[rule_token]})"
        )
    return errors


def validate_tokens(tokens: dict[str, Any]) -> list[str]:
    """Contradictions inside the token file, one message each; empty when valid."""
    errors: list[str] = []
    entries = _color_entries(tokens)
    ids = [c.get("id") for c in entries]
    errors += [f"{cid}: color id used more than once" for cid in sorted({i for i in ids if ids.count(i) > 1})]
    for color in entries:
        cid, hex_value = color.get("id", "?"), color.get("hex", "")
        if not HEX_RE.match(hex_value):
            errors.append(f"{cid}: hex {hex_value!r} is not #RRGGBB")
            continue
        rgb = color.get("rgb")
        if rgb is not None and list(rgb) != hex_to_rgb(hex_value):
            errors.append(
                f"{cid}: rgb {list(rgb)} does not match hex {hex_value} "
                f"({hex_to_rgb(hex_value)}); hex is authoritative"
            )
        cmyk = color.get("cmyk")
        if cmyk is not None and not (
            isinstance(cmyk, list)
            and len(cmyk) == 4
            and all(isinstance(v, int) and 0 <= v <= 100 for v in cmyk)
        ):
            errors.append(f"{cid}: cmyk {cmyk!r} is not four integers from 0 to 100")
        pms = color.get("pms")
        if pms is not None and not isinstance(pms, str):
            errors.append(f"{cid}: pms {pms!r} must be a string or null")
    hex_by_id = {c["id"]: c["hex"] for c in entries if "id" in c and "hex" in c}
    errors += _validate_tables(tokens, hex_by_id)
    brand_ids = {c.get("id") for c in tokens["colors"]["brand"]}
    order = tokens["colors"].get("discrete_order", {}).get("token_ids", [])
    if not order:
        errors.append("colors.discrete_order.token_ids is missing or empty")
    errors += [f"colors.discrete_order: {i!r} is not a brand token" for i in order if i not in brand_ids]
    if len(set(order)) != len(order):
        errors.append("colors.discrete_order lists a token more than once")
    for role in ("headline", "body"):
        spec = tokens["typography"][role]
        chain = [spec["primary_family"], *spec.get("accept_as_primary", []), *spec["fallback_stack"]]
        if len(chain) != len(set(chain)):
            errors.append(f"typography.{role}: a family appears more than once in its resolution chain")
    errors += _validate_roles(tokens)
    return errors


def _validate_roles(tokens: dict[str, Any]) -> list[str]:
    """Role sizes are points (token version 2.0.0 renamed `size_px*` to `size_pt*`)."""
    errors: list[str] = []
    floor = tokens["sizing"].get("text_floor_pt", {}).get("print", 0)
    for name, role in tokens["typography"]["roles"].items():
        legacy = sorted(k for k in role if k.startswith("size_px"))
        if legacy:
            errors.append(
                f"typography.roles.{name}: {', '.join(legacy)} was renamed to size_pt* in "
                "token version 2.0.0; sizes are points"
            )
        size = role.get("size_pt")
        if not isinstance(size, (int, float)) or isinstance(size, bool):
            errors.append(f"typography.roles.{name}: size_pt must be a number of points")
            continue
        low, high = role.get("size_pt_range", [size, size])
        if not low <= size <= high:
            errors.append(f"typography.roles.{name}: size_pt {size} is outside size_pt_range")
        if size < floor:
            errors.append(f"typography.roles.{name}: size_pt {size} is below the {floor}pt print floor")
    return errors


def _brand(tokens: dict[str, Any]) -> list[dict[str, Any]]:
    return tokens["colors"]["brand"]


def _neutrals(tokens: dict[str, Any]) -> list[dict[str, Any]]:
    return tokens["colors"].get("neutrals", [])


def _discrete_ids(tokens: dict[str, Any]) -> list[str]:
    """The default categorical series order, as brand token IDs."""
    return list(tokens["colors"]["discrete_order"]["token_ids"])


def _sequential(tokens: dict[str, Any]) -> list[dict[str, Any]]:
    return tokens["colors"]["sequential"]


def _legacy_sets(tokens: dict[str, Any]) -> list[dict[str, Any]]:
    return tokens["colors"]["legacy_semantic_sets"]


# Generic CSS family names in the fallback stacks; Stata has no equivalent.
STATA_GENERIC_FAMILIES = ("serif", "sans-serif", "monospace")


def _safe_key(key: str) -> str:
    chars = []
    for ch in key:
        if ch.isalnum():
            chars.append(ch.upper())
        else:
            chars.append("_")
    return "".join(chars)


def _python_literal(value: Any) -> str:
    """A Python literal for any JSON value: `True`/`None`, never JSON's `true`/`null`."""
    return pprint.pformat(value, indent=1, width=88, sort_dicts=False)


def _render_python(tokens: dict[str, Any]) -> str:
    brand = {c["id"]: c["hex"] for c in _brand(tokens)}
    brand_rgb = {c["id"]: c["rgb"] for c in _brand(tokens)}
    sequential = {s["id"]: s["entries"] for s in _sequential(tokens)}
    legacy = {s["set_id"]: s["entries"] for s in _legacy_sets(tokens)}
    typography = tokens["typography"]
    sizing = tokens["sizing"]
    tables = tokens["tables"]
    policies = tokens["policies"]
    status_by_id = {c["id"]: c["status"] for c in _brand(tokens)}
    neutrals = {c["id"]: c["hex"] for c in _neutrals(tokens)}
    provisional = [c["id"] for c in _color_entries(tokens) if c["status"] == "provisional"]
    discrete = [brand[k] for k in _discrete_ids(tokens)]

    content = f"""# Auto-generated by scripts/sync_tokens.py. Do not edit manually.
# Source: tokens/eig-style-tokens.v1.json

TOKENS_VERSION = {_python_literal(tokens["meta"]["version"])}
TOKENS_GENERATED_ON = {_python_literal(tokens["meta"]["generated_on"])}

BRAND_COLORS = {_python_literal(brand)}
BRAND_RGB = {_python_literal(brand_rgb)}
BRAND_STATUS = {_python_literal(status_by_id)}
NEUTRALS = {_python_literal(neutrals)}
PROVISIONAL_TOKEN_IDS = {_python_literal(provisional)}

EIG_DISCRETE_IDS = {_python_literal(_discrete_ids(tokens))}
EIG_DISCRETE = {_python_literal(discrete)}
SEQUENTIAL = {_python_literal(sequential)}
LEGACY_SEMANTIC_SETS = {_python_literal(legacy)}

TYPOGRAPHY = {_python_literal(typography)}
SIZING = {_python_literal(sizing)}
TABLES = {_python_literal(tables)}
POLICIES = {_python_literal(policies)}
"""
    return content


def _r_literal(value: Any, indent: int = 0) -> str:
    """An R literal for any JSON value.

    Objects become named `list()`s; arrays of strings, of numbers, or of booleans become
    `c()` vectors; other arrays become unnamed `list()`s. JSON `true`/`false`/`null`
    become `TRUE`/`FALSE`/`NULL`, and strings use JSON escaping, which R accepts.
    """
    pad, close = "  " * (indent + 1), "  " * indent
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, dict):
        if not value:
            return "list()"
        items = [f"{pad}{json.dumps(k)} = {_r_literal(v, indent + 1)}" for k, v in value.items()]
        return "list(\n" + ",\n".join(items) + f"\n{close})"
    if isinstance(value, list):
        if not value:
            return "list()"
        if (
            all(isinstance(v, str) for v in value)
            or all(isinstance(v, bool) for v in value)
            or all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
        ):
            return "c(" + ", ".join(_r_literal(v) for v in value) + ")"
        items = [f"{pad}{_r_literal(v, indent + 1)}" for v in value]
        return "list(\n" + ",\n".join(items) + f"\n{close})"
    raise TypeError(f"no R literal for {type(value).__name__}")


def _r_assign(name: str, value: Any) -> str:
    return f"{name} <- {_r_literal(value)}"


def _r_named_vector(name: str, mapping: dict[str, str]) -> str:
    """A named character vector, so `x[["id"]]` and `unname(x)` both work."""
    parts = [f"{json.dumps(k)} = {json.dumps(v)}" for k, v in mapping.items()]
    return f"{name} <- c(\n  " + ",\n  ".join(parts) + "\n)"


def _render_r(tokens: dict[str, Any]) -> str:
    brand = {c["id"]: c["hex"] for c in _brand(tokens)}
    sequential = {s["id"]: s["entries"] for s in _sequential(tokens)}
    legacy = {s["set_id"]: s["entries"] for s in _legacy_sets(tokens)}
    discrete = [brand[k] for k in _discrete_ids(tokens)]
    neutrals = {c["id"]: c["hex"] for c in _neutrals(tokens)}
    provisional = [c["id"] for c in _color_entries(tokens) if c["status"] == "provisional"]
    headline = tokens["typography"]["headline"]["primary_family"]
    body = tokens["typography"]["body"]["primary_family"]
    fig = tokens["sizing"]["figure_default"]
    legacy_rule = tokens["policies"]["legacy_palette_decision_rule"]

    lines = [
        "# Auto-generated by scripts/sync_tokens.py. Do not edit manually.",
        "# Source: tokens/eig-style-tokens.v1.json",
        "",
        f'EIG_TOKENS_VERSION <- "{tokens["meta"]["version"]}"',
        f'EIG_TOKENS_GENERATED_ON <- "{tokens["meta"]["generated_on"]}"',
        "",
        _r_named_vector("EIG_COLORS", brand),
        "",
        _r_named_vector("EIG_NEUTRALS", neutrals),
        "",
        _r_assign("EIG_DISCRETE_IDS", _discrete_ids(tokens)),
        _r_assign("EIG_DISCRETE", discrete),
        "",
        _r_assign("EIG_PROVISIONAL_TOKEN_IDS", provisional),
        "",
        _r_assign("EIG_SEQUENTIAL", sequential),
        "",
        _r_assign("EIG_LEGACY_SEMANTIC_SETS", legacy),
        "",
        _r_assign("EIG_FONT_HEADLINE_PRIMARY", headline),
        _r_assign("EIG_FONT_BODY_PRIMARY", body),
        "",
        _r_assign("EIG_FIGURE_DEFAULT_WIDTH_IN", fig["width_in"]),
        _r_assign("EIG_FIGURE_DEFAULT_HEIGHT_IN", fig["height_in"]),
        "",
        _r_assign("EIG_LEGACY_PALETTE_DECISION_RULE", legacy_rule),
        "",
        _r_assign("EIG_TYPOGRAPHY", tokens["typography"]),
        "",
        _r_assign("EIG_SIZING", tokens["sizing"]),
        "",
        _r_assign("EIG_TABLES", tokens["tables"]),
        "",
    ]
    return "\n".join(lines) + "\n"


def _render_stata(tokens: dict[str, Any]) -> str:
    brand = _brand(tokens)
    sequential = _sequential(tokens)
    legacy = _legacy_sets(tokens)

    lines = [
        "* Auto-generated by scripts/sync_tokens.py. Do not edit manually.",
        "* Source: tokens/eig-style-tokens.v1.json",
        f'* Version: {tokens["meta"]["version"]}',
        "",
    ]

    for c in _color_entries(tokens):
        key = _safe_key(c["id"])
        hex_value = c["hex"]
        rgb_value = " ".join(str(x) for x in c["rgb"])
        lines.append(f'global EIG_HEX_{key} "{hex_value}"')
        lines.append(f'global EIG_RGB_{key} "{rgb_value}"')
        lines.append(f'global EIG_STATUS_{key} "{c["status"]}"')
    lines.append("")

    discrete_hex = []
    brand_by_id = {c["id"]: c for c in brand}
    for token_id in _discrete_ids(tokens):
        if token_id in brand_by_id:
            discrete_hex.append(brand_by_id[token_id]["hex"])
    lines.append(f'global EIG_DISCRETE_HEX "{" ".join(discrete_hex)}"')
    lines.append("")

    for seq in sequential:
        key = _safe_key(seq["id"])
        joined = " ".join(seq["entries"])
        lines.append(f'global EIG_SEQ_{key} "{joined}"')
    lines.append("")

    for set_item in legacy:
        set_key = _safe_key(set_item["set_id"])
        for name, color in set_item["entries"].items():
            entry_key = _safe_key(name)
            lines.append(f'global EIG_LEGACY_{set_key}_{entry_key} "{color}"')
    lines.append("")

    typography = tokens["typography"]
    for role in ("headline", "body"):
        spec = typography[role]
        key = role.upper()
        lines.append(f'global EIG_FONT_{key} "{spec["primary_family"]}"')
        # Font lists are quoted names, read with `foreach f of global ...`. Generic CSS
        # names (serif, sans-serif) mean nothing to Stata and are left out.
        for suffix, families in (
            ("ACCEPT", spec.get("accept_as_primary", [])),
            ("FALLBACK", [f for f in spec["fallback_stack"] if f not in STATA_GENERIC_FAMILIES]),
        ):
            quoted = " ".join(f'"{f}"' for f in families)
            # Compound quotes keep the inner quotes: the global holds "A" "B".
            lines.append(f"global EIG_FONT_{key}_{suffix} `\"{quoted}\"'" if quoted
                         else f'global EIG_FONT_{key}_{suffix} ""')
    lines.append("")

    for name, role in typography["roles"].items():
        lines.append(f'global EIG_SIZE_PT_{_safe_key(name)} {role["size_pt"]}')
    lines.append("")

    fig = tokens["sizing"]["figure_default"]
    lines.append(f'global EIG_FIG_WIDTH_IN {fig["width_in"]}')
    lines.append(f'global EIG_FIG_HEIGHT_IN {fig["height_in"]}')
    lines.append("")

    tables = tokens["tables"]
    table_colors = (
        ("HEADER_BG", brand_by_id[tables["header"]["background_token"]]["hex"]),
        ("HEADER_TEXT", brand_by_id[tables["header"]["text_token"]]["hex"]),
        ("RULE", tables["body"]["rule_color_hex"]),
    )
    for key, hex_value in table_colors:
        rgb_value = " ".join(str(x) for x in hex_to_rgb(hex_value))
        lines.append(f'global EIG_TABLE_{key}_HEX "{hex_value}"')
        lines.append(f'global EIG_TABLE_{key}_RGB "{rgb_value}"')
    lines.append("")

    return "\n".join(lines) + "\n"


# Stata scheme entries and the token each takes its color from. The scheme covers
# colors, the white background, and the default size; a .scheme file cannot set a
# font face, so eig_theme.do sets fonts with `graph set`.
SCHEME_COLORS = (
    ("background", "eig_white"),
    ("foreground", "eig_black"),
    ("graphregion", "eig_white"),
    ("graphregion_line", "eig_white"),
    ("plotregion", "eig_white"),
    ("plotregion_line", "eig_white"),
    ("legend", "eig_white"),
    ("legend_line", "eig_white"),
    ("text", "eig_black"),
    ("body", "eig_black"),
    ("heading", "eig_black"),
    ("subheading", "eig_black"),
    ("axis_title", "eig_black"),
    ("label", "eig_black"),
    ("key_label", "eig_black"),
    ("tick_label", "eig_black"),
    ("small_body", "eig_neutral_caption"),
    ("axisline", "eig_neutral_axis"),
    ("tick", "eig_neutral_axis"),
    ("grid", "eig_neutral_grid"),
    ("major_grid", "eig_neutral_grid"),
    ("minor_grid", "eig_neutral_grid"),
)


def _stata_rgb(hex_value: str) -> str:
    return '"' + " ".join(str(v) for v in hex_to_rgb(hex_value)) + '"'


def _render_scheme(tokens: dict[str, Any]) -> str:
    hex_by_id = {c["id"]: c["hex"] for c in _color_entries(tokens)}
    fig = tokens["sizing"]["figure_default"]
    lines = [
        "*! EIG graph scheme. Auto-generated by scripts/sync_tokens.py. Do not edit manually.",
        "*! Source: tokens/eig-style-tokens.v1.json",
        f'*! Version: {tokens["meta"]["version"]}',
        "*  Colors are RGB triples of token values; fonts are set by eig_theme.do.",
        "",
        "#include s2color",
        "",
        f'graphsize x {fig["width_in"]}',
        f'graphsize y {fig["height_in"]}',
        "",
    ]
    width = max(len(name) for name, _ in SCHEME_COLORS)
    for name, token_id in SCHEME_COLORS:
        lines.append(f"color {name:<{width}} {_stata_rgb(hex_by_id[token_id])}")
    lines.append("")
    lines.append("* Series colors, in colors.discrete_order")
    for n, token_id in enumerate(_discrete_ids(tokens), start=1):
        lines.append(f"color p{n} {_stata_rgb(hex_by_id[token_id])}")
    lines.append("")
    lines.append("* Horizontal gridlines only")
    lines.append("yesno draw_major_hgrid yes")
    lines.append("yesno draw_major_vgrid no")
    lines.append("")
    return "\n".join(lines)


def _md_cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    return str(value).replace("|", "\\|")


def _md_table(header: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(_md_cell(v) for v in row) + " |" for row in rows]
    return out + [""]


def _render_tokens_doc(tokens: dict[str, Any]) -> str:
    meta = tokens["meta"]
    hex_by_id = {c["id"]: c["hex"] for c in _color_entries(tokens)}
    typography = tokens["typography"]
    lines = [
        "<!-- Auto-generated by scripts/sync_tokens.py. Do not edit manually. -->",
        "",
        "# EIG style tokens",
        "",
        f"Generated from `Infrastructure/style/tokens/eig-style-tokens.v1.json` (version "
        f"{meta['version']}, {meta['generated_on']}) by "
        "`Infrastructure/style/scripts/sync_tokens.py`. Cite colors, fonts, and sizes by "
        "token ID; change them in the JSON and regenerate.",
        "",
        "## Brand palette",
        "",
        "CMYK and PMS are from the 2022 Style Guide, p.7 (folio 06). Hex is authoritative; "
        "RGB is derived from it.",
        "",
    ]
    lines += _md_table(
        ["Token", "Hex", "RGB", "CMYK", "PMS", "Status", "Role"],
        [[f"`{c['id']}`", c["hex"], c["rgb"], c.get("cmyk"), c.get("pms"), c["status"], c["role"]]
         for c in _brand(tokens)],
    )
    lines += ["## Neutrals", ""]
    lines += _md_table(
        ["Token", "Hex", "RGB", "Status", "Role"],
        [[f"`{c['id']}`", c["hex"], c["rgb"], c["status"], c["role"]] for c in _neutrals(tokens)],
    )
    lines += ["## Series order", "", tokens["colors"]["discrete_order"]["role"], ""]
    lines += _md_table(
        ["Series", "Token", "Hex"],
        [[n, f"`{i}`", hex_by_id[i]] for n, i in enumerate(_discrete_ids(tokens), start=1)],
    )
    lines += ["## Sequential and legacy palettes", ""]
    lines += _md_table(
        ["Palette", "Status", "Colors"],
        [[f"`{s['id']}`", s["status"], s["entries"]] for s in _sequential(tokens)]
        + [[f"`{s['set_id']}`", s["status"], [f"{k} {v}" for k, v in s["entries"].items()]]
           for s in _legacy_sets(tokens)],
    )
    lines += ["## Font families", ""]
    lines += _md_table(
        ["Use", "Primary", "Accepted as primary", "Fallback stack"],
        [[use, typography[use]["primary_family"], typography[use].get("accept_as_primary"),
          typography[use]["fallback_stack"]] for use in ("headline", "body")],
    )
    lines += _md_table(
        ["Legacy family", "2020 scope", "Status"],
        [[f["family"], f.get("scope_2020"), f["status"]] for f in typography["legacy_families"]],
    )
    lines += ["## Type roles", ""]
    lines += _md_table(
        ["Role", "Family", "Weight", "Size (pt)", "Range (pt)", "Source"],
        [[f"`{name}`", r["family"], r["weight"], r["size_pt"],
          "–".join(str(v) for v in r["size_pt_range"]) if "size_pt_range" in r else None,
          r["source"]] for name, r in typography["roles"].items()],
    )
    floor = tokens["sizing"]["text_floor_pt"]
    fig = tokens["sizing"]["figure_default"]
    lines += ["## Sizes", ""]
    lines += _md_table(
        ["Token", "Value"],
        [["`sizing.text_floor_pt.print`", f"{floor['print']} pt"],
         ["`sizing.text_floor_pt.screen`", f"{floor['screen']} pt"],
         ["`sizing.figure_default`", f"{fig['width_in']} × {fig['height_in']} in"]],
    )
    lines += ["## Tables", ""]
    lines += _md_table(
        ["Part", "Setting", "Value"],
        [[part, key, value] for part, spec in tokens["tables"].items()
         for key, value in spec.items() if key not in ("source", "status")],
    )
    lines += ["## Ambiguities", "", "Recorded source conflicts and provisional choices; each JSON entry holds its resolution.", ""]
    lines += _md_table(
        ["ID", "Needs sign-off", "Issue"],
        [[f"`{a['id']}`", "yes" if a.get("requires_signoff") else "no", a["issue"]]
         for a in tokens["ambiguities"]],
    )
    return "\n".join(lines).rstrip("\n") + "\n"


# Every generated output and its renderer. check_style_token_drift.py imports this
# tuple, so a new output is drift-checked as soon as it is listed here.
OUTPUTS = (
    (OUT_PY, _render_python),
    (OUT_R, _render_r),
    (OUT_DO, _render_stata),
    (OUT_SCHEME, _render_scheme),
    (OUT_TOKENS_DOC, _render_tokens_doc),
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the Python, R, and Stata token files, the Stata scheme, and the "
            "token tables doc from tokens/eig-style-tokens.v1.json. Without --write, "
            "nothing is written."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="Regenerate and overwrite every generated output.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help=(
            "Compare a fresh rendering with the files on disk without writing "
            "(the default); exit 1 if any file is out of sync."
        ),
    )
    return parser.parse_args(argv)


def _normalized(data: bytes) -> bytes:
    """Content with CRLF folded to LF, as git stores text files."""
    return data.replace(b"\r\n", b"\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tokens = _load_tokens()
    errors = validate_tokens(tokens)
    if errors:
        print(f"Token file is invalid (nothing was written): {TOKEN_PATH.name}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    rendered = [(path, render(tokens)) for path, render in OUTPUTS]

    if args.write:
        for path, content in rendered:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        print("Synced token outputs:")
        for path, _ in rendered:
            print(f"  - {path.relative_to(ROOT)}")
        return 0

    stale = [
        path
        for path, content in rendered
        if not path.is_file()
        or _normalized(path.read_bytes()) != content.encode("utf-8")
    ]
    if stale:
        print("Token outputs are out of sync (nothing was written):", file=sys.stderr)
        for path in stale:
            print(f"  - {path.relative_to(ROOT)}", file=sys.stderr)
        print("Regenerate with --write, then commit the result.", file=sys.stderr)
        return 1

    print("Token outputs are in sync; nothing written. Pass --write to regenerate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
