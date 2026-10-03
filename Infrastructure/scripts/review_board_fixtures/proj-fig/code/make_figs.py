#!/usr/bin/env python3
"""Synthetic figure renderer for the review-board test suite. Not a real analysis.

Draws one small bar chart per entry in `code/params.json`, styled by the shared
`code/theme.json`, and writes `output/figures/<id>.png` plus an SVG sibling unless the entry
sets `"svg": false`. Standard library only, so the suite needs no plotting package.

Test hooks in `params.json`:

- `"stamp": true` writes a `tEXt` chunk holding the current time, so every run's bytes
  differ while the pixels do not (RB-R5: the content hash must ignore it).
- `"fail": true` exits non-zero before writing anything.
- a figure's `"skip": true` leaves that figure unwritten (RB-R4: render must refuse).

`theme.json` is deliberately not in any item's `sources`: changing it is a shared-code
change that the round's changed-files check must report (RB-C4).
"""

from __future__ import annotations

import json
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 48, 32


def _chunk(ctype: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + ctype + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))


def _hex(rgb: list[int]) -> str:
    return "#" + "".join(f"{c:02x}" for c in rgb)


def write_png(path: Path, spec: dict, theme: dict, stamp: bool) -> None:
    background = tuple(theme["background"])
    rows = [[background] * WIDTH for _ in range(HEIGHT)]
    for index, value in enumerate(spec["values"]):
        x0 = 4 + index * 14
        for y in range(max(0, HEIGHT - 2 - int(value)), HEIGHT - 2):
            for x in range(x0, min(WIDTH, x0 + 10)):
                rows[y][x] = tuple(spec["color"])
    raw = b"".join(b"\x00" + b"".join(bytes(px) for px in row) for row in rows)
    ppm = int(round(theme["dpi"] / 0.0254))
    chunks = [_chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)),
              _chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))]
    if stamp:
        chunks.append(_chunk(b"tEXt", b"Creation Time\x00" + repr(time.time()).encode()))
    chunks += [_chunk(b"IDAT", zlib.compress(raw, 6)), _chunk(b"IEND", b"")]
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"".join(chunks))


def write_svg(path: Path, fig_id: str, spec: dict, theme: dict) -> None:
    bars = "\n".join(
        f"  <rect x='{40 + i * 100}' y='{220 - v * 6}' width='70' height='{v * 6}' "
        f"style='fill: {_hex(spec['color'])};'/>"
        for i, v in enumerate(spec["values"]))
    path.write_text(f"""<?xml version='1.0' encoding='UTF-8' ?>
<svg xmlns='http://www.w3.org/2000/svg' width='360.00pt' height='240.00pt'
     viewBox='0 0 360.00 240.00'>
  <rect width='100%' height='100%' style='stroke: none; fill: {_hex(theme["background"])};'/>
{bars}
  <text x='10' y='20' style='font-size: {theme["title_px"]}px; fill: {spec.get("title_fill", theme["text_fill"])};'>{fig_id}</text>
  <text x='40' y='236' style='font-size: {theme["label_px"]}px; fill: {theme["text_fill"]};'>2019</text>
</svg>
""", encoding="utf-8", newline="\n")


def main() -> int:
    params = json.loads((ROOT / "code" / "params.json").read_text(encoding="utf-8"))
    theme = json.loads((ROOT / "code" / "theme.json").read_text(encoding="utf-8"))
    if params.get("fail"):
        print("synthetic render failure requested by params.json", file=sys.stderr)
        return 3
    out = ROOT / "output" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for fig_id, spec in params["figures"].items():
        if spec.get("skip"):
            continue
        write_png(out / f"{fig_id}.png", spec, theme, bool(params.get("stamp", True)))
        if spec.get("svg", True):
            write_svg(out / f"{fig_id}.svg", fig_id, spec, theme)
        written += 1
    print(f"wrote {written} synthetic figures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
