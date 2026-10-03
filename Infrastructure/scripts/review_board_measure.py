#!/usr/bin/env python3
"""Deterministic measurements for review-board renders (RB-M1 to RB-M3).

From the PNG: pixel width and height, and DPI from `pHYs`. From the SVG sibling, when an
item declares one:

- **text floor**: the smallest text size in points, against 7pt for print and 7.5pt (10px
  at 96 dpi) for screen, from `Infrastructure/style/docs/eig-figure-style.md`;
- **palette**: every fill, stroke, and stop color, against the non-legacy hex values in
  `Infrastructure/style/tokens/eig-style-tokens.v1.json`. Legacy palettes are flagged
  because the legacy-palette policy requires a documented exception, which a waiver
  records (RB-M4);
- **contrast**: each text fill against the figure background, against WCAG AA (4.5:1, or
  3:1 for text of 18pt and above).

A check that cannot run records `not-measured` with a reason, never `pass` (RB-M3). This
happens when there is no SVG, when the SVG has no `<text>` elements (text converted to
paths), or when the SVG declares entities.

SVG sizes are converted to points through the root element's `width` and `viewBox`, and
through every `transform` on the way down to each text element. Entity declarations are
refused before parsing. A DOCTYPE without entities is allowed, because matplotlib writes
one.

Usage (for inspecting one render):
    python Infrastructure/scripts/review_board_measure.py --png <file> [--svg <file>] \
        [--medium print|screen]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_board_lib as rb  # noqa: E402

TOKENS_PATH = (Path(__file__).resolve().parents[1] / "style" / "tokens"
               / "eig-style-tokens.v1.json")
FLOOR_PT = {"print": 7.0, "screen": 7.5}
AA_NORMAL = 4.5
AA_LARGE = 3.0
LARGE_TEXT_PT = 18.0
DEFAULT_FONT_USER = 16.0          # CSS initial font-size, in user units (px)

_UNIT_PT = {"pt": 1.0, "px": 0.75, "in": 72.0, "mm": 72.0 / 25.4, "cm": 72.0 / 2.54,
            "pc": 12.0, "": 0.75}
_UNIT_USER = {"px": 1.0, "": 1.0, "pt": 4.0 / 3.0, "in": 96.0, "mm": 96.0 / 25.4,
              "cm": 96.0 / 2.54, "pc": 16.0}
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_LENGTH_RE = re.compile(rf"^\s*({_NUMBER})\s*(pt|px|in|mm|cm|pc|%)?\s*$")
_FONT_SIZE_RE = re.compile(rf"^\s*({_NUMBER})\s*(pt|px|in|mm|cm|pc|em|%)?\s*$")
_FONT_SHORTHAND_RE = re.compile(
    rf"(?:^|\s)({_NUMBER})(pt|px|in|mm|cm|pc|em|%)?(?:\s*/\s*\S+)?\s+['\"A-Za-z]")
_TRANSFORM_RE = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
_ENTITY_RE = re.compile(rb"<!ENTITY", re.IGNORECASE)
_NAMED = {"white": "#ffffff", "black": "#000000"}
_SKIP_COLORS = {"none", "transparent", "currentcolor", "inherit", "initial", "unset"}
_SKIP_SUBTREES = {"metadata", "title", "desc", "style", "script"}
_HIDDEN_SUBTREES = {"defs", "clipPath", "mask", "symbol", "marker", "pattern"}
_SHAPES = {"rect", "path", "polygon", "circle", "ellipse"}


# --------------------------------------------------------------------------- palette
def load_palette(path: Path = TOKENS_PATH) -> frozenset[str]:
    """Lowercase `#rrggbb` values from every non-legacy color token."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    colors = data.get("colors") or {}
    out: set[str] = set()
    # Neutrals may be absent, a list of entries like brand, or a mapping of id to entry.
    neutrals = colors.get("neutrals") or []
    if isinstance(neutrals, dict):
        neutrals = [v if isinstance(v, dict) else {"hex": v} for v in neutrals.values()]
    for entry in [*(colors.get("brand") or []), *neutrals]:
        if isinstance(entry, dict) and entry.get("status") != "legacy" \
                and isinstance(entry.get("hex"), str):
            out.add(entry["hex"].lower())
    for entry in colors.get("sequential") or []:
        if entry.get("status") != "legacy":
            values = entry.get("entries") or []
            values = values.values() if isinstance(values, dict) else values
            out.update(str(v).lower() for v in values)
    for group in (data.get("tables") or {}).values():
        if isinstance(group, dict):
            out.update(str(v).lower() for k, v in group.items()
                       if k.endswith("_hex") and isinstance(v, str))
    return frozenset(out)


# --------------------------------------------------------------------------- parsing helpers
def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _style(el: ET.Element) -> dict[str, str]:
    props: dict[str, str] = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            props[key.strip().lower()] = value.strip()
    return props


def _prop(el: ET.Element, style: dict[str, str], name: str) -> str | None:
    """A CSS style property beats the presentation attribute of the same name."""
    if name in style:
        return style[name]
    return el.get(name)


def _length_pt(value: str | None) -> float | None:
    m = _LENGTH_RE.match(value or "")
    if not m or m.group(2) == "%":
        return None
    return float(m.group(1)) * _UNIT_PT[m.group(2) or ""]


def _font_size_user(value: str | None, inherited: float) -> float | None:
    m = _FONT_SIZE_RE.match(value or "")
    if not m:
        return None
    number, unit = float(m.group(1)), (m.group(2) or "")
    if unit == "em":
        return number * inherited
    if unit == "%":
        return number * inherited / 100.0
    return number * _UNIT_USER[unit]


def _shorthand_size(value: str | None, inherited: float) -> float | None:
    m = _FONT_SHORTHAND_RE.search(value or "")
    if not m:
        return None
    return _font_size_user(f"{m.group(1)}{m.group(2) or ''}", inherited)


def _matmul(a: tuple, b: tuple) -> tuple:
    """2x2 linear parts (a, b, c, d) as in SVG matrix(a b c d e f); translation ignored."""
    a1, b1, c1, d1 = a
    a2, b2, c2, d2 = b
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2)


def _transform(value: str | None) -> tuple:
    m = (1.0, 0.0, 0.0, 1.0)
    for name, args in _TRANSFORM_RE.findall(value or ""):
        nums = [float(x) for x in re.findall(_NUMBER, args)]
        if name == "matrix" and len(nums) >= 4:
            local = (nums[0], nums[1], nums[2], nums[3])
        elif name == "scale" and nums:
            local = (nums[0], 0.0, 0.0, nums[1] if len(nums) > 1 else nums[0])
        elif name == "rotate" and nums:
            t = math.radians(nums[0])
            local = (math.cos(t), math.sin(t), -math.sin(t), math.cos(t))
        elif name == "skewX" and nums:
            local = (1.0, 0.0, math.tan(math.radians(nums[0])), 1.0)
        elif name == "skewY" and nums:
            local = (1.0, math.tan(math.radians(nums[0])), 0.0, 1.0)
        else:                                   # translate, or unparseable arguments
            continue
        m = _matmul(m, local)
    return m


def _scale(m: tuple) -> float:
    """The factor a transform applies to a font size: the root of the determinant."""
    a, b, c, d = m
    return math.sqrt(abs(a * d - b * c))


def normalize_color(value: str | None) -> str | None:
    """`#rrggbb` lowercase, a name we do not know (reported as off-palette), or None."""
    if value is None:
        return None
    v = value.strip().lower().replace("!important", "").strip()
    if not v or v in _SKIP_COLORS or v.startswith("url("):
        return None
    if v in _NAMED:
        return _NAMED[v]
    if re.fullmatch(r"#[0-9a-f]{3}", v):
        return "#" + "".join(ch * 2 for ch in v[1:])
    if re.fullmatch(r"#[0-9a-f]{6}([0-9a-f]{2})?", v):
        return v[:7]
    m = re.fullmatch(r"rgba?\(([^)]*)\)", v)
    if m:
        parts = [p.strip() for p in m.group(1).replace("/", ",").split(",") if p.strip()]
        if len(parts) >= 3:
            rgb = []
            for p in parts[:3]:
                n = float(p[:-1]) * 2.55 if p.endswith("%") else float(p)
                rgb.append(max(0, min(255, int(round(n)))))
            return "#" + "".join(f"{c:02x}" for c in rgb)
    return v


def _luminance(hex_color: str) -> float:
    def channel(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def _is_hex(value: str | None) -> bool:
    return bool(value) and bool(re.fullmatch(r"#[0-9a-f]{6}", value or ""))


# --------------------------------------------------------------------------- SVG walk
class _Walk:
    def __init__(self, pt_per_user: float, view_size: tuple[float, float] | None):
        self.pt_per_user = pt_per_user
        self.view_size = view_size
        self.texts: list[tuple[float, str | None]] = []     # (size in pt, fill)
        self.colors: set[str] = set()
        self.background: str | None = None
        self.background_source: str | None = None
        self.first_shape_fill: str | None = None

    def visit(self, el: ET.Element, font_user: float, fill: str | None, matrix: tuple,
              hidden: bool, depth: int) -> None:
        tag = _local(el.tag)
        if tag in _SKIP_SUBTREES:
            return
        style = _style(el)
        hidden = hidden or tag in _HIDDEN_SUBTREES

        size = _font_size_user(_prop(el, style, "font-size"), font_user)
        if size is None and "font" in style:
            size = _shorthand_size(style["font"], font_user)
        font_user = size if size is not None else font_user

        own_fill = _prop(el, style, "fill")
        if own_fill is not None:
            normalized = normalize_color(own_fill)
            if normalized:
                fill = normalized
            elif own_fill.strip().lower() == "none":
                fill = "none"           # invisible text: not a hex, so contrast skips it
            # currentColor, inherit, and url(...) keep the inherited fill
        for name in ("fill", "stroke", "stop-color"):
            color = normalize_color(_prop(el, style, name))
            if color:
                self.colors.add(color)

        matrix = _matmul(matrix, _transform(el.get("transform")))

        if not hidden:
            if tag == "svg" and depth == 0:
                bg = normalize_color(style.get("background-color") or style.get("background"))
                if _is_hex(bg):
                    self.background, self.background_source = bg, "svg background"
            if tag in _SHAPES:
                shape_fill = normalize_color(_prop(el, style, "fill"))
                if self.first_shape_fill is None and _is_hex(shape_fill):
                    self.first_shape_fill = shape_fill
                if (tag == "rect" and self.background is None and _is_hex(shape_fill)
                        and self._covers(el)):
                    self.background, self.background_source = shape_fill, "full-size rect"
            if tag in ("text", "tspan") and (el.text or "").strip():
                self.texts.append((font_user * _scale(matrix) * self.pt_per_user,
                                   fill if fill is not None else "#000000"))

        for child in el:
            self.visit(child, font_user, fill, matrix, hidden, depth + 1)

    def _covers(self, el: ET.Element) -> bool:
        w, h = el.get("width", ""), el.get("height", "")
        if w.strip() == "100%" and h.strip() == "100%":
            return True
        if self.view_size is None:
            return False
        try:
            return (float(w) >= self.view_size[0] * 0.99
                    and float(h) >= self.view_size[1] * 0.99)
        except ValueError:
            return False


def _not_measured(reason: str) -> dict:
    return {"result": "not-measured", "reason": reason}


def measure_svg(svg_path: Path, medium: str, palette: frozenset[str]) -> dict:
    """text_floor, palette, and contrast results for one SVG."""
    data = Path(svg_path).read_bytes()
    if _ENTITY_RE.search(data):
        reason = "the SVG declares entities, which are refused (RB-M3)"
        return {k: _not_measured(reason) for k in rb.MEASURE_CHECKS}
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        reason = f"the SVG does not parse ({exc})"
        return {k: _not_measured(reason) for k in rb.MEASURE_CHECKS}

    view = [float(x) for x in re.findall(_NUMBER, root.get("viewBox") or "")]
    view_size = (view[2], view[3]) if len(view) == 4 and view[2] > 0 else None
    width_pt = _length_pt(root.get("width"))
    pt_per_user = (width_pt / view_size[0]) if (view_size and width_pt) else 0.75

    walk = _Walk(pt_per_user, view_size)
    walk.visit(root, DEFAULT_FONT_USER, None, (1.0, 0.0, 0.0, 1.0), False, 0)

    off = sorted(c for c in walk.colors if c not in palette)
    palette_result = {"result": "fail" if off else "pass", "off_palette": off}

    floor = FLOOR_PT[medium]
    if not walk.texts:
        reason = "the SVG has no <text> elements; text may have been converted to paths"
        return {"text_floor": _not_measured(reason), "palette": palette_result,
                "contrast": _not_measured(reason)}
    sizes = [size for size, _ in walk.texts]
    smallest = min(sizes)
    text_floor = {"result": "fail" if smallest < floor - 1e-9 else "pass",
                  "smallest_pt": round(smallest, 2), "floor_pt": floor,
                  "below_floor": sum(1 for s in sizes if s < floor - 1e-9)}

    if walk.background is None and walk.first_shape_fill is not None:
        walk.background, walk.background_source = walk.first_shape_fill, "first painted shape"
    if walk.background is None:
        walk.background, walk.background_source = "#ffffff", "assumed white"
    ratios = []
    failing: set[str] = set()
    for size, fg in walk.texts:
        if not _is_hex(fg):
            continue
        ratio = contrast_ratio(fg, walk.background)
        ratios.append(ratio)
        if ratio < (AA_LARGE if size >= LARGE_TEXT_PT else AA_NORMAL):
            failing.add(fg)
    if not ratios:
        contrast = _not_measured("no text fill resolved to a color")
    else:
        contrast = {"result": "fail" if failing else "pass",
                    "min_ratio": round(min(ratios), 2), "background": walk.background,
                    "background_source": walk.background_source,
                    "failing_fills": sorted(failing)}
    return {"text_floor": text_floor, "palette": palette_result, "contrast": contrast}


def measure(png_path: Path, svg_path: Path | None, medium: str,
            palette: frozenset[str] | None = None) -> dict:
    """The full measurement record for one render (RB-M2). `dpi_changed` is set by render."""
    info = rb.png_info(png_path)
    out: dict[str, Any] = {"width_px": info["width_px"], "height_px": info["height_px"],
                           "dpi": info["dpi"]}
    if svg_path is None:
        reason = "no SVG sibling is declared for this item"
        out.update({k: _not_measured(reason) for k in rb.MEASURE_CHECKS})
    elif not Path(svg_path).is_file():
        reason = "the declared SVG sibling was not written by the render command"
        out.update({k: _not_measured(reason) for k in rb.MEASURE_CHECKS})
    else:
        out.update(measure_svg(Path(svg_path), medium,
                               palette if palette is not None else load_palette()))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="review_board_measure.py",
                                 description="Measure one review-board render.")
    ap.add_argument("--png", required=True)
    ap.add_argument("--svg", default=None)
    ap.add_argument("--medium", choices=tuple(FLOOR_PT), default="print")
    args = ap.parse_args(argv)
    try:
        result = measure(Path(args.png), Path(args.svg) if args.svg else None, args.medium)
    except rb.ReviewBoardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
