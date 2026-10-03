#!/usr/bin/env python3
"""Tests for the EIG style layer: tokens, generated outputs, and the language themes.

`python3 Infrastructure/scripts/test_style.py` from anywhere (stdlib `unittest`; pass
`-v` for one line per case).

The suite is hermetic: it writes only inside temporary directories, touches no network
(unless `--network` is passed, which checks the font download URLs and checksums), and gives
every subprocess a timeout. A case that needs a tool this machine lacks (R with
its packages, matplotlib and seaborn, `pdftotext`, a Stata binary) is skipped with the
reason printed; it never passes without running. With `REQUIRE_R=1`, a missing R or R package
fails the R cases instead; with `REQUIRE_PLOTTING=1`, missing matplotlib, seaborn, or the other
example modules fail the Python render cases. CI sets both.

Exit codes: 0 every case passed or skipped; 1 a case failed.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[1]
STYLE_ROOT = REPO_ROOT / "Infrastructure" / "style"
TOKEN_PATH = STYLE_ROOT / "tokens" / "eig-style-tokens.v1.json"
SYNC_SCRIPT = STYLE_ROOT / "scripts" / "sync_tokens.py"
SUBPROCESS_TIMEOUT = 60

# Style subtrees a scratch copy needs; the fonts, logos, and source guides are large
# and nothing under test reads them.
SCRATCH_SUBDIRS = ("tokens", "scripts", "themes", "docs")


def skip_unless_required(case: unittest.TestCase, reason: str, switch: str) -> None:
    """Skip a case whose tool is missing, unless `switch`=1 makes that tool required.

    CI installs R and the plotting packages and sets REQUIRE_R=1 and REQUIRE_PLOTTING=1, so a
    failed install fails the suite instead of turning every render case into a quiet skip.
    """
    if os.environ.get(switch) == "1":
        case.fail(f"{reason} ({switch}=1 requires it)")
    case.skipTest(reason)


def load_tokens(path: Path = TOKEN_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def hex_to_rgb(value: str) -> list[int]:
    digits = value.lstrip("#")
    return [int(digits[i : i + 2], 16) for i in (0, 2, 4)]


def color_entries(tokens: dict[str, Any]) -> list[dict[str, Any]]:
    """Every single-color token: brand colors, then neutrals."""
    return list(tokens["colors"]["brand"]) + list(tokens["colors"].get("neutrals", []))


def load_module(path: Path, name: str) -> ModuleType:
    # An in-process import would otherwise write __pycache__ into the repo.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    # No __pycache__ from a subprocess: the suite writes nothing into the repo.
    kwargs["env"] = dict(kwargs.get("env") or os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT, **kwargs
    )


class ScratchStyleMixin:
    """Gives a case its own copy of the style tree in a temporary directory."""

    def make_scratch_style(self) -> Path:
        tmp = tempfile.TemporaryDirectory(prefix="eig-style-test-")
        self.addCleanup(tmp.cleanup)  # type: ignore[attr-defined]
        style = Path(tmp.name) / "Infrastructure" / "style"
        for sub in SCRATCH_SUBDIRS:
            shutil.copytree(STYLE_ROOT / sub, style / sub, symlinks=True)
        return style

    @staticmethod
    def write_tokens(style: Path, tokens: dict[str, Any]) -> None:
        path = style / "tokens" / "eig-style-tokens.v1.json"
        path.write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8", newline="\n")

    @staticmethod
    def run_sync(style: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return run([sys.executable, str(style / "scripts" / "sync_tokens.py"), *args])


class TokenFileTests(unittest.TestCase):
    """The canonical token JSON is internally consistent."""

    def test_rgb_matches_hex(self) -> None:
        tokens = load_tokens()
        mismatches = [
            f"{c['id']}: hex {c['hex']} is {hex_to_rgb(c['hex'])}, rgb says {c['rgb']}"
            for c in color_entries(tokens)
            if c.get("rgb") is not None and list(c["rgb"]) != hex_to_rgb(c["hex"])
        ]
        self.assertEqual(mismatches, [], "hex is authoritative; rgb must be derived from it")

    def test_neutrals_are_provisional_template_values(self) -> None:
        neutrals = load_tokens()["colors"]["neutrals"]
        self.assertTrue(neutrals, "the themes' grays live in colors.neutrals")
        for n in neutrals:
            self.assertEqual((n["status"], n["source"]), ("provisional", "template"), n["id"])

    def test_font_families_are_ordered_once(self) -> None:
        typography = load_tokens()["typography"]
        for role in ("headline", "body"):
            spec = typography[role]
            chain = [spec["primary_family"], *spec["accept_as_primary"], *spec["fallback_stack"]]
            self.assertEqual(len(chain), len(set(chain)), f"{role}: a family is listed twice")
        self.assertIn("Source Serif 4", typography["headline"]["accept_as_primary"])

    def test_role_sizes_are_points(self) -> None:
        tokens = load_tokens()
        self.assertEqual(tokens["meta"]["version"].split(".")[0], "2", "size_pt* is 2.0.0")
        for name, role in tokens["typography"]["roles"].items():
            self.assertFalse([k for k in role if k.startswith("size_px")], name)
            self.assertIsInstance(role["size_pt"], (int, float), name)
            self.assertEqual(role["source"], "template", name)

    def test_text_floor(self) -> None:
        floor = load_tokens()["sizing"]["text_floor_pt"]
        self.assertEqual((floor["print"], floor["screen"]), (7, 7.5))

    def test_table_tokens_resolve(self) -> None:
        tokens = load_tokens()
        hex_by_id = {c["id"]: c["hex"] for c in color_entries(tokens)}
        for part, spec in tokens["tables"].items():
            for key, value in spec.items():
                if key.endswith("_token"):
                    self.assertIn(value, hex_by_id, f"tables.{part}.{key}")
        body = tokens["tables"]["body"]
        self.assertEqual(body["rule_color_hex"], hex_by_id[body["rule_color_token"]])


PDF_2022 = STYLE_ROOT / "sources" / "2022 Style Guide.pdf"
PDF_PALETTE_PAGE = 7  # printed folio 06


def parse_pdf_palette(text: str) -> list[dict[str, Any]]:
    """Swatches from `pdftotext -layout` output of the palette page, in reading order.

    Each swatch row starts with a line of `Hex:` labels; the RGB, CMYK, and PMS lines
    below it list values in the same column order, and a swatch without print values
    (black, white) simply has no entry on those lines.
    """
    rows: list[list[dict[str, Any]]] = []
    for line in text.splitlines():
        hexes = re.findall(r"(?i)hex:\s*(#[0-9a-f]{5,6})\b", line)
        if hexes:
            rows.append([{"hex": h.upper(), "rgb": None, "cmyk": None, "pms": None} for h in hexes])
            continue
        if not rows:
            continue
        fields = {
            "rgb": [list(map(int, m)) for m in re.findall(r"RGB:\s*(\d+),\s*(\d+),\s*(\d+)", line)],
            "cmyk": [
                list(map(int, m))
                for m in re.findall(r"CMYK:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)", line)
            ],
            "pms": re.findall(r"PMS:\s*(\S+)", line),
        }
        for key, values in fields.items():
            for index, value in enumerate(values):
                rows[-1][index][key] = value
    return [swatch for row in rows for swatch in row]


class PdfPaletteTests(unittest.TestCase):
    """The brand tokens match the 2022 guide's palette page (p.7, folio 06)."""

    def test_tokens_match_pdf_palette(self) -> None:
        if shutil.which("pdftotext") is None:
            self.skipTest("pdftotext not found; the 2022 palette page was not parsed")
        if not PDF_2022.is_file():
            self.skipTest(f"source guide absent: {PDF_2022.relative_to(REPO_ROOT)}")
        proc = run(
            ["pdftotext", "-layout", "-f", str(PDF_PALETTE_PAGE), "-l", str(PDF_PALETTE_PAGE),
             str(PDF_2022), "-"]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        swatches = parse_pdf_palette(proc.stdout)
        tokens = load_tokens()
        brand = tokens["colors"]["brand"]
        self.assertEqual(len(swatches), len(brand), "one PDF swatch per brand token")

        by_hex = {c["hex"].upper(): c for c in brand}
        recorded_rgb = {
            a["source_value"]["hex"].upper(): a["source_value"]["rgb"]
            for a in tokens["ambiguities"]
            if "rgb" in a.get("source_value", {})
        }
        for swatch in swatches:
            # The PDF prints black as "#00000"; ambiguity a-2022-black-swatch resolves it.
            hex_value = "#000000" if swatch["hex"] == "#00000" else swatch["hex"]
            with self.subTest(hex=hex_value):
                self.assertIn(hex_value, by_hex)
                token = by_hex[hex_value]
                if swatch["rgb"] is not None and swatch["rgb"] != token["rgb"]:
                    self.assertEqual(
                        recorded_rgb.get(hex_value), swatch["rgb"],
                        "a PDF rgb that differs from the hex must be recorded under ambiguities",
                    )
                self.assertEqual(token.get("cmyk", "absent"), swatch["cmyk"])
                self.assertEqual(token.get("pms", "absent"), swatch["pms"])


# Machado, Oliveira, and Fernandes (2009) simulation matrices at severity 1.0, applied
# to linear RGB. Used only to warn; they approximate, not certify, what a viewer sees.
CVD_MATRICES = {
    "protan": ((0.152286, 1.052583, -0.204868),
               (0.114503, 0.786281, 0.099216),
               (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968),
               (0.280085, 0.672501, 0.047413),
               (-0.011820, 0.042940, 0.968881)),
    "tritan": ((1.255528, -0.076749, -0.178779),
               (-0.078411, 0.930809, 0.147602),
               (0.004733, 0.691367, 0.303900)),
}
# Warning thresholds for the series-order report (owner-judgment item 5).
ADJACENT_CONTRAST_MIN = 1.5   # luminance ratio between neighboring series
ON_WHITE_CONTRAST_MIN = 3.0   # WCAG 2.1 SC 1.4.11, graphical objects
CVD_DELTA_E_MIN = 15.0        # CIE76 distance between neighbors under simulation


def _linear(rgb: list[int]) -> list[float]:
    out = []
    for channel in rgb:
        c = channel / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def _luminance(lin: list[float]) -> float:
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: list[float], b: list[float]) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _lab(lin: list[float]) -> tuple[float, float, float]:
    r, g, b = (min(max(v, 0.0), 1.0) for v in lin)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _simulate(lin: list[float], matrix: tuple[tuple[float, ...], ...]) -> list[float]:
    return [sum(m * v for m, v in zip(row, lin)) for row in matrix]


def _delta_e(a: list[float], b: list[float]) -> float:
    return sum((p - q) ** 2 for p, q in zip(_lab(a), _lab(b))) ** 0.5


def series_order_warnings(tokens: dict[str, Any]) -> list[str]:
    """Adjacent-contrast, on-white, and CVD warnings for colors.discrete_order."""
    hex_by_id = {c["id"]: c["hex"] for c in tokens["colors"]["brand"]}
    ids = tokens["colors"]["discrete_order"]["token_ids"]
    lin = {i: _linear(hex_to_rgb(hex_by_id[i])) for i in ids}
    white = _linear([255, 255, 255])
    warnings = []
    for i in ids:
        ratio = _contrast(lin[i], white)
        if ratio < ON_WHITE_CONTRAST_MIN:
            warnings.append(f"{i} on white: {ratio:.2f}:1 (< {ON_WHITE_CONTRAST_MIN}:1)")
    for a, b in zip(ids, ids[1:]):
        ratio = _contrast(lin[a], lin[b])
        if ratio < ADJACENT_CONTRAST_MIN:
            warnings.append(f"{a} next to {b}: luminance {ratio:.2f}:1 (< {ADJACENT_CONTRAST_MIN}:1)")
        for kind, matrix in CVD_MATRICES.items():
            de = _delta_e(_simulate(lin[a], matrix), _simulate(lin[b], matrix))
            if de < CVD_DELTA_E_MIN:
                warnings.append(f"{a} next to {b}: {kind} delta E {de:.1f} (< {CVD_DELTA_E_MIN})")
    return warnings


class SeriesOrderTests(unittest.TestCase):
    """The series order resolves, and its contrast and CVD warnings are reported."""

    def test_series_order_report(self) -> None:
        tokens = load_tokens()
        brand_ids = {c["id"] for c in tokens["colors"]["brand"]}
        ids = tokens["colors"]["discrete_order"]["token_ids"]
        self.assertTrue(ids)
        self.assertLessEqual(set(ids), brand_ids)
        warnings = series_order_warnings(tokens)
        # Owner-judgment item 5 keeps the order; the warnings are reported, not failed.
        if warnings:
            print("\nSeries-order warnings (reported, not failed; see a-series-order):",
                  file=sys.stderr)
            for warning in warnings:
                print(f"  - {warning}", file=sys.stderr)


class SyncValidationTests(ScratchStyleMixin, unittest.TestCase):
    """sync_tokens.py refuses a token file that contradicts itself."""

    def test_sync_rejects_rgb_mismatch(self) -> None:
        style = self.make_scratch_style()
        tokens = load_tokens()
        tokens["colors"]["brand"][0]["rgb"] = [9, 9, 9]
        self.write_tokens(style, tokens)
        before = {p: p.read_bytes() for p in (style / "themes").rglob("*") if p.is_file()}
        for mode in ((), ("--write",), ("--check",)):
            proc = self.run_sync(style, *mode)
            self.assertEqual(proc.returncode, 1, f"mode {mode}: {proc.stdout}{proc.stderr}")
            self.assertIn("rgb", proc.stderr)
        after = {p: p.read_bytes() for p in (style / "themes").rglob("*") if p.is_file()}
        self.assertEqual(before, after, "an invalid token file must write nothing")

    def test_sync_rejects_pre_2_0_size_keys(self) -> None:
        style = self.make_scratch_style()
        tokens = load_tokens()
        role = tokens["typography"]["roles"]["notes_caption"]
        role["size_px"] = role.pop("size_pt")
        self.write_tokens(style, tokens)
        proc = self.run_sync(style, "--write")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("renamed to size_pt", proc.stderr)


class GeneratedLiteralTests(ScratchStyleMixin, unittest.TestCase):
    """Generated token files are valid code for any JSON value, booleans and nulls included."""

    def fixture_tokens(self) -> dict[str, Any]:
        tokens = load_tokens()
        tokens["sizing"]["fixture_flag"] = True
        tokens["sizing"]["fixture_none"] = None
        tokens["sizing"]["fixture_quote"] = 'a "quoted" name'
        return tokens

    def test_python_output_compiles_and_round_trips(self) -> None:
        style = self.make_scratch_style()
        tokens = self.fixture_tokens()
        self.write_tokens(style, tokens)
        proc = self.run_sync(style, "--write")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        source = (style / "themes" / "python" / "eig_tokens.py").read_text(encoding="utf-8")
        namespace: dict[str, Any] = {}
        exec(compile(source, "eig_tokens.py", "exec"), namespace)
        self.assertEqual(namespace["SIZING"], tokens["sizing"])
        self.assertEqual(namespace["TYPOGRAPHY"], tokens["typography"])
        self.assertEqual(namespace["TABLES"], tokens["tables"])

    def test_r_output_parses(self) -> None:
        if shutil.which("Rscript") is None:
            skip_unless_required(self, "Rscript not found; the generated R file was not parsed", "REQUIRE_R")
        style = self.make_scratch_style()
        self.write_tokens(style, self.fixture_tokens())
        proc = self.run_sync(style, "--write")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        r_file = style / "themes" / "r" / "eig_tokens.R"
        expr = (
            "e <- new.env(); sys.source(commandArgs(TRUE)[1], envir = e); "
            "s <- e$EIG_SIZING; "
            "stopifnot(isTRUE(s$fixture_flag), is.null(s$fixture_none), "
            "identical(s$fixture_quote, 'a \"quoted\" name'), "
            "identical(e$EIG_TABLES$header$background_token, 'eig_teal_900')); cat('ok')"
        )
        proc = run(["Rscript", "-e", expr, str(r_file)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ok")


SCHEME_PATH = STYLE_ROOT / "themes" / "stata" / "scheme-eig.scheme"
TOKENS_DOC_PATH = STYLE_ROOT / "docs" / "_generated" / "tokens.md"
DRIFT_SCRIPT = SCRIPTS / "check_style_token_drift.py"


class GeneratedOutputTests(ScratchStyleMixin, unittest.TestCase):
    """The Stata scheme and the token tables are generated, token-exact, and drift-checked."""

    def test_scheme_colors_are_token_rgb(self) -> None:
        tokens = load_tokens()
        token_rgb = {" ".join(map(str, hex_to_rgb(c["hex"]))) for c in color_entries(tokens)}
        lines = SCHEME_PATH.read_text(encoding="utf-8").splitlines()
        colors = {}
        for line in lines:
            parts = line.split(None, 2)
            if len(parts) == 3 and parts[0] == "color":
                colors[parts[1]] = parts[2]
        self.assertTrue(colors, "the scheme sets colors")
        for name, value in colors.items():
            with self.subTest(entry=name):
                self.assertRegex(value, r'^"\d{1,3} \d{1,3} \d{1,3}"$', "an RGB triple, not a name")
                self.assertIn(value.strip('"'), token_rgb, "the triple equals a token")
        hex_by_id = {c["id"]: c["hex"] for c in tokens["colors"]["brand"]}
        order = tokens["colors"]["discrete_order"]["token_ids"]
        for n, token_id in enumerate(order, start=1):
            self.assertEqual(colors.get(f"p{n}"), '"' + " ".join(map(str, hex_to_rgb(hex_by_id[token_id]))) + '"')

    def make_scratch_repo(self) -> Path:
        style = self.make_scratch_style()
        scripts = style.parent / "scripts"
        scripts.mkdir()
        shutil.copy2(DRIFT_SCRIPT, scripts / DRIFT_SCRIPT.name)
        return style.parents[1]

    def run_drift(self, repo: Path) -> subprocess.CompletedProcess[str]:
        return run([sys.executable, str(repo / "Infrastructure" / "scripts" / DRIFT_SCRIPT.name)])

    def test_drift_check_catches_hand_edits(self) -> None:
        for rel in (
            Path("themes") / "stata" / "scheme-eig.scheme",
            Path("docs") / "_generated" / "tokens.md",
        ):
            with self.subTest(output=str(rel)):
                repo = self.make_scratch_repo()
                self.assertEqual(self.run_drift(repo).returncode, 0, "a clean copy passes")
                target = repo / "Infrastructure" / "style" / rel
                target.write_text(target.read_text(encoding="utf-8") + "hand edit\n", encoding="utf-8", newline="\n")
                proc = self.run_drift(repo)
                self.assertEqual(proc.returncode, 1, proc.stdout)
                self.assertIn(rel.name, proc.stderr)

    def test_check_mode_writes_nothing(self) -> None:
        style = self.make_scratch_style()

        def stamps() -> dict[Path, int]:
            return {p: p.stat().st_mtime_ns for p in style.rglob("*") if p.is_file()}

        before = stamps()
        for mode in ((), ("--check",)):
            self.assertEqual(self.run_sync(style, *mode).returncode, 0)
        tokens = load_tokens()
        tokens["meta"]["version"] = "2.99.0"  # printed in every generated output
        self.write_tokens(style, tokens)
        token_file = style / "tokens" / "eig-style-tokens.v1.json"
        before[token_file] = token_file.stat().st_mtime_ns
        for mode in ((), ("--check",)):
            proc = self.run_sync(style, *mode)
            self.assertEqual(proc.returncode, 1, "a stale output is reported")
            self.assertIn("scheme-eig.scheme", proc.stderr)
            self.assertIn("tokens.md", proc.stderr)
        self.assertEqual(stamps(), before, "check mode must not touch any file")


class HexLintTests(ScratchStyleMixin, unittest.TestCase):
    """The drift check fails on a hex color outside the tokens and generated files."""

    make_scratch_repo = GeneratedOutputTests.make_scratch_repo
    run_drift = GeneratedOutputTests.run_drift

    def plant(self, repo: Path, rel: str, text: str) -> None:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def test_real_tree_passes(self) -> None:
        proc = run([sys.executable, str(DRIFT_SCRIPT)])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_planted_hex_fails(self) -> None:
        cases = (
            "Infrastructure/style/docs/planted.md",
            "Infrastructure/style/themes/r/planted.R",
            "Infrastructure/style/examples/python/planted.py",
            "Infrastructure/style/skills/planted.md",
            "Infrastructure/agents/eig-planted.md",
            "Infrastructure/rules/style-planted.md",
        )
        for rel in cases:
            with self.subTest(path=rel):
                repo = self.make_scratch_repo()
                self.plant(repo, rel, "Use teal #024140 for the first series.\n"
                                      "Gray #333 for text.\nTeal #024140CC at 80% opacity.\n")
                proc = self.run_drift(repo)
                self.assertEqual(proc.returncode, 1, proc.stdout)
                for line in (1, 2, 3):  # 6-, 3-, and 8-digit hex
                    self.assertIn(f"{rel}:{line}:", proc.stderr)

    def test_exceptions_pass(self) -> None:
        repo = self.make_scratch_repo()
        # A marked line, a file outside the scope, an SVG, a fixture, a non-color anchor.
        self.plant(repo, "Infrastructure/style/docs/marked.md",
                   "Old default #3366CC. hex-ok: quotes the pre-2022 guide\n")
        self.plant(repo, "Infrastructure/agents/code-reviewer.md", "#024140\n")
        self.plant(repo, "Infrastructure/style/docs/logo.svg", '<path fill="#024140"/>\n')
        self.plant(repo, "Infrastructure/style/docs/fixtures/case.md", "#024140\n")
        self.plant(repo, "Infrastructure/style/docs/links.md", "See [the table](#decade-trends) and &#123456;\n")
        proc = self.run_drift(repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_marker_needs_a_reason(self) -> None:
        repo = self.make_scratch_repo()
        self.plant(repo, "Infrastructure/style/docs/marked.md", "Old default #3366CC. hex-ok:\n")
        self.assertEqual(self.run_drift(repo).returncode, 1)

    def test_allowlist_is_empty(self) -> None:
        drift = load_module(DRIFT_SCRIPT, "eig_drift_check")
        self.assertEqual(drift.HEX_ALLOWLIST, {}, "U12 emptied the allowlist; mark a quoted color hex-ok")

    def test_stale_allowlist_entry_fails(self) -> None:
        # The list is empty, so plant entries in the scratch copy of the script: one whose
        # file is gone, and one whose file has no hex left.
        repo = self.make_scratch_repo()
        script = repo / "Infrastructure" / "scripts" / DRIFT_SCRIPT.name
        text = script.read_text(encoding="utf-8")
        empty = "HEX_ALLOWLIST: dict[str, str] = {}"
        self.assertIn(empty, text)
        gone = "Infrastructure/style/docs/gone.md"
        clean = "Infrastructure/style/docs/clean.md"
        self.plant(repo, clean, "No colors here.\n")
        script.write_text(text.replace(empty, f"HEX_ALLOWLIST = {{{gone!r}: 'U99', {clean!r}: 'U99'}}"),
                          encoding="utf-8", newline="\n")
        proc = self.run_drift(repo)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn(f"{gone}: allowlisted for U99, but the file is gone", proc.stderr)
        self.assertIn(f"{clean}: allowlisted for U99, but has no hex left", proc.stderr)


DOCS_DIR = STYLE_ROOT / "docs"
FIGURE_DOC = DOCS_DIR / "eig-figure-style.md"
BRAND_DOC = DOCS_DIR / "eig-brand-guidelines.md"
THEME_FILES = (
    STYLE_ROOT / "themes" / "r" / "eig_theme.R",
    STYLE_ROOT / "themes" / "python" / "eig_theme.py",
    STYLE_ROOT / "themes" / "stata" / "eig_theme.do",
)
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
TOKEN_PATH_RE = re.compile(r"^(?:colors|typography|sizing|tables)(?:\.[a-z0-9_]+)+$")
FLOOR_RE = re.compile(
    r"`sizing\.text_floor_pt`: \*\*(?P<print>[\d.]+)pt for print\*\* and "
    r"\*\*(?P<screen>[\d.]+)pt for screen, which is (?P<px>[\d.]+)px at 96 dpi\*\*"
)


def resolve_token_path(tokens: dict[str, Any], dotted: str) -> bool:
    """Whether a dotted path such as `tables.header.background_token` exists."""
    node: Any = tokens
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return True


class StyleDocTests(unittest.TestCase):
    """The figure and brand docs cite tokens that exist, and the text floor matches."""

    def setUp(self) -> None:
        self.tokens = load_tokens()
        colors = self.tokens["colors"]
        self.token_ids = {c["id"] for c in color_entries(self.tokens)}
        self.token_ids |= {s["id"] for s in colors["sequential"]}
        self.token_ids |= {s["set_id"] for s in colors["legacy_semantic_sets"]}
        self.theme_text = "".join(p.read_text(encoding="utf-8") for p in THEME_FILES)

    def spans(self, path: Path) -> list[str]:
        return CODE_SPAN_RE.findall(path.read_text(encoding="utf-8"))

    def test_figure_doc_has_one_lineage(self) -> None:
        text = FIGURE_DOC.read_text(encoding="utf-8")
        for name in ("Tiempos", "Galaxie"):
            self.assertNotIn(name, text)

    def test_cited_tokens_exist(self) -> None:
        ambiguity_ids = {a["id"] for a in self.tokens["ambiguities"]}
        for doc in (FIGURE_DOC, BRAND_DOC):
            for span in self.spans(doc):
                with self.subTest(doc=doc.name, span=span):
                    if TOKEN_PATH_RE.match(span):
                        self.assertTrue(resolve_token_path(self.tokens, span), span)
                    elif re.fullmatch(r"eig_[a-z0-9_]+", span):
                        # A token ID, or a theme function or program named without "()".
                        self.assertTrue(span in self.token_ids or span in self.theme_text, span)
                    elif re.fullmatch(r"a-[a-z0-9-]+", span):
                        self.assertIn(span, ambiguity_ids)

    def test_figure_doc_roles_match_tokens(self) -> None:
        text = FIGURE_DOC.read_text(encoding="utf-8")
        cited = set(re.findall(r"^\|[^|\n]+\| `([a-z_]+)` \|$", text, flags=re.M))
        self.assertEqual(cited, set(self.tokens["typography"]["roles"]))

    def test_text_floor_matches_token(self) -> None:
        # review_board_measure.py and review-board-rules.md cite this sentence.
        text = FIGURE_DOC.read_text(encoding="utf-8")
        self.assertIn('<a id="text-floor"></a>', text)
        match = FLOOR_RE.search(text)
        self.assertIsNotNone(match, "the text-floor sentence is missing or reworded")
        floor = self.tokens["sizing"]["text_floor_pt"]
        self.assertEqual(float(match["print"]), floor["print"])
        self.assertEqual(float(match["screen"]), floor["screen"])
        self.assertEqual(float(match["px"]), floor["screen"] * 96 / 72)


R_THEME_REL = "Infrastructure/style/themes/r/eig_theme.R"
R_PACKAGES = ("ggplot2", "ragg", "systemfonts")
_R_SKIP_REASON: list[str | None] = []


def r_skip_reason() -> str | None:
    """Why the R cases cannot run here, or None when Rscript and its packages exist."""
    if not _R_SKIP_REASON:
        reason = None
        if shutil.which("Rscript") is None:
            reason = "Rscript not found"
        else:
            expr = (
                "p <- c(" + ", ".join(f'"{p}"' for p in R_PACKAGES) + "); "
                "cat(p[!vapply(p, requireNamespace, logical(1L), quietly = TRUE)])"
            )
            proc = run(["Rscript", "-e", expr])
            if proc.returncode != 0:
                reason = f"Rscript failed: {proc.stderr.strip()[:200]}"
            elif proc.stdout.strip():
                reason = f"R packages missing: {proc.stdout.strip()}"
        _R_SKIP_REASON.append(reason)
    return _R_SKIP_REASON[0]


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"not a PNG: {path}")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


class RThemeTests(unittest.TestCase):
    """The R theme loads from anywhere in the repo, renders, and reports its fonts."""

    def setUp(self) -> None:
        reason = r_skip_reason()
        if reason:
            skip_unless_required(self, reason, "REQUIRE_R")
        tmp = tempfile.TemporaryDirectory(prefix="eig-style-r-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def run_r(self, body: str, cwd: Path = REPO_ROOT, source: str = R_THEME_REL
              ) -> subprocess.CompletedProcess[str]:
        script = self.tmp / "case.R"
        script.write_text(f'source("{source}")\n{body}\n', encoding="utf-8", newline="\n")
        env = {k: v for k, v in os.environ.items() if k != "EIG_STYLE_DIR"}
        return run(["Rscript", "--vanilla", str(script)], cwd=cwd, env=env)

    def test_sources_from_repo_root_and_code_dir(self) -> None:
        body = 'invisible(suppressWarnings(eig_theme_ggplot())); cat("ok")'
        for cwd, source in ((REPO_ROOT, R_THEME_REL), (REPO_ROOT / "code", "../" + R_THEME_REL)):
            with self.subTest(cwd=str(cwd.relative_to(REPO_ROOT)) or "."):
                proc = self.run_r(body, cwd=cwd, source=source)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout.strip(), "ok")

    def test_ragg_render_has_expected_pixel_size(self) -> None:
        out = self.tmp / "figure.png"
        body = f"""
df <- data.frame(x = 1:6, y = c(2, 3, 5, 4, 6, 7), g = rep(c("A", "B"), 3L))
p <- ggplot2::ggplot(df, ggplot2::aes(x, y, color = g)) +
  ggplot2::geom_line() +
  ggplot2::labs(title = "A sentence-case title", caption = "Source: Synthetic data.") +
  eig_scale_color() +
  suppressWarnings(eig_theme_ggplot())
tokens <- eig_load_tokens()
ggplot2::ggsave("{out.as_posix()}", p, device = ragg::agg_png, dpi = 100,
  width = tokens$EIG_FIGURE_DEFAULT_WIDTH_IN, height = tokens$EIG_FIGURE_DEFAULT_HEIGHT_IN)
"""
        proc = self.run_r(body)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(png_size(out), (650, 350), "6.5 x 3.5 in at 100 dpi")

    def test_headline_is_source_serif_or_warns(self) -> None:
        body = """
warns <- character(0L)
th <- withCallingHandlers(
  eig_theme_ggplot(),
  warning = function(w) {
    warns <<- c(warns, conditionMessage(w))
    invokeRestart("muffleWarning")
  }
)
family <- ggplot2::calc_element("plot.title", th)$family
matched <- systemfonts::match_fonts(family)$path
cat(basename(matched), any(grepl("headline", warns)), sep = "|")
"""
        proc = self.run_r(body)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        font_file, warned = proc.stdout.strip().split("|")
        serif = "sourceserif" in font_file.lower().replace(" ", "")
        self.assertTrue(serif or warned == "TRUE",
                        f"title drew with {font_file} and no headline warning was raised")

    def test_resolver_order_and_warning(self) -> None:
        body = """
tokens <- eig_load_tokens()
ok <- eig_resolve_family("headline", tokens, available = c("Georgia", "Source Serif 4"))
stopifnot(identical(as.vector(ok), "Source Serif 4"), isTRUE(attr(ok, "eig_primary")))
fb <- tryCatch(eig_resolve_family("headline", tokens, available = c("Arial", "Georgia")),
  warning = function(w) conditionMessage(w))
stopifnot(grepl("using fallback 'Georgia'", fb))
generic <- suppressWarnings(eig_resolve_family("body", tokens, available = character(0L)))
stopifnot(identical(as.vector(generic), "sans"))
cat("ok")
"""
        proc = self.run_r(body)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ok")

    def test_title_and_caption_align_to_plot(self) -> None:
        # Owner-judgment item 1: the title stays in the image, flush left with the plot.
        out = self.tmp / "untitled.png"
        body = f"""
th <- suppressWarnings(eig_theme_ggplot())
stopifnot(identical(th$plot.title.position, "plot"), identical(th$plot.caption.position, "plot"))
p <- ggplot2::ggplot(data.frame(x = 1:3, y = 1:3), ggplot2::aes(x, y)) +
  ggplot2::geom_point() + ggplot2::labs(title = NULL) + th
ggplot2::ggsave("{out.as_posix()}", p, device = ragg::agg_png, width = 3, height = 2, dpi = 50)
cat("ok")
"""
        proc = self.run_r(body)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(png_size(out), (150, 100), "a plot without a title renders")

    def test_font_checker_agrees_with_theme(self) -> None:
        body = """
tokens <- eig_load_tokens()
primary <- vapply(c("headline", "body"), function(role) {
  isTRUE(attr(eig_resolve_family(role, tokens, warn = FALSE), "eig_primary"))
}, logical(1L))
cat(all(primary))
"""
        proc = self.run_r(body)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        theme_primary = proc.stdout.strip() == "TRUE"
        checker = run(["Rscript", str(STYLE_ROOT / "scripts" / "fonts" / "check-fonts.R")])
        self.assertIn(checker.returncode, (0, 1), checker.stderr)
        self.assertEqual(checker.returncode == 0, theme_primary, checker.stderr)

    def test_text_sizes_equal_tokens(self) -> None:
        tokens = load_tokens()
        roles = tokens["typography"]["roles"]
        body = """
th <- suppressWarnings(eig_theme_ggplot())
cat(ggplot2::calc_element("plot.title", th)$size,
    ggplot2::calc_element("plot.caption", th)$size,
    ggplot2::calc_element("axis.text.x", th)$size, sep = "|")
"""
        proc = self.run_r(body)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        sizes = [float(v) for v in proc.stdout.strip().split("|")]
        self.assertEqual(sizes, [roles["chart_title"]["size_pt"], roles["notes_caption"]["size_pt"],
                                 roles["axis_legend_table_body"]["size_pt"]])


PY_THEME_DIR = STYLE_ROOT / "themes" / "python"


def python_missing(*modules: str) -> list[str]:
    return [m for m in modules if importlib.util.find_spec(m) is None]


class PythonThemeTests(unittest.TestCase):
    """The Python theme imports lazily, resolves fonts like R, and survives seaborn."""

    def run_py(self, code: str) -> subprocess.CompletedProcess[str]:
        tmp = tempfile.TemporaryDirectory(prefix="eig-style-py-")
        self.addCleanup(tmp.cleanup)
        env = dict(os.environ, MPLCONFIGDIR=tmp.name, MPLBACKEND="Agg")
        prelude = f"import sys\nsys.path.insert(0, {str(PY_THEME_DIR)!r})\n"
        return run([sys.executable, "-c", prelude + code], cwd=tmp.name, env=env)

    def test_imports_without_plotting_packages(self) -> None:
        code = (
            "for name in ('matplotlib', 'seaborn', 'plotly', 'pandas'):\n"
            "    sys.modules[name] = None  # any import of it now fails\n"
            "import eig_theme\n"
            "print(eig_theme.eig_palette()[0])\n"
        )
        proc = self.run_py(code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), load_tokens()["colors"]["brand"][0]["hex"])

    def test_resolver_accepts_source_serif_4_and_warns_on_fallback(self) -> None:
        code = (
            "import warnings\n"
            "import eig_theme as t\n"
            "with warnings.catch_warnings():\n"
            "    warnings.simplefilter('error')\n"
            "    assert t.resolve_font_family('headline', ['Georgia', 'Source Serif 4']) == ('Source Serif 4', True)\n"
            "    assert t.resolve_font_family('body', ['Open Sans']) == ('Open Sans', True)\n"
            "with warnings.catch_warnings(record=True) as caught:\n"
            "    warnings.simplefilter('always')\n"
            "    assert t.resolve_font_family('headline', ['Arial', 'Georgia']) == ('Georgia', False)\n"
            "    assert t.resolve_font_family('body', []) == ('sans-serif', False)\n"
            "assert len(caught) == 2 and 'using fallback' in str(caught[0].message), caught\n"
            "print('ok')\n"
        )
        proc = self.run_py(code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ok")

    def test_font_checker_agrees_with_theme(self) -> None:
        code = (
            "import eig_theme as t\n"
            "fams = t.installed_font_families()\n"
            "print(bool(fams) and all(t.resolve_font_family(r, fams, warn=False)[1]"
            " for r in ('headline', 'body')))\n"
        )
        proc = self.run_py(code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        theme_primary = proc.stdout.strip() == "True"
        checker = run([sys.executable, str(STYLE_ROOT / "scripts" / "fonts" / "check-fonts.py")])
        if checker.returncode == 2:
            self.skipTest(f"no font enumerator on this machine: {checker.stderr.strip()}")
        self.assertEqual(checker.returncode == 0, theme_primary, checker.stdout + checker.stderr)

    def test_seaborn_does_not_override_theme(self) -> None:
        missing = python_missing("matplotlib", "seaborn")
        if missing:
            skip_unless_required(self, f"Python packages missing: {', '.join(missing)}", "REQUIRE_PLOTTING")
        tokens = load_tokens()
        neutrals = {c["id"]: c["hex"] for c in tokens["colors"]["neutrals"]}
        code = (
            "import json, warnings\n"
            "import matplotlib as mpl\n"
            "import eig_theme as t\n"
            "warnings.simplefilter('ignore')\n"
            "t.set_eig_theme()\n"
            "body, _ = t.resolve_font_family('body')\n"
            "rc = mpl.rcParams\n"
            "print(json.dumps({'family0': rc['font.family'][0], 'body': body,\n"
            "  'grid': rc['grid.color'], 'top': rc['axes.spines.top'],\n"
            "  'right': rc['axes.spines.right'], 'title': rc['axes.titlesize'],\n"
            "  'text': rc['text.color']}))\n"
            "import matplotlib.pyplot as plt\n"
            "fig, ax = plt.subplots()\n"
            "t.eig_title(ax, 'A sentence-case title')\n"
            "fig.canvas.draw()\n"
        )
        proc = self.run_py(code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Failed to find font weight", proc.stderr,
                         "the title weight must be one the headline family has")
        got = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(got["family0"], got["body"], "seaborn must not replace the body font")
        self.assertEqual(got["grid"].upper(), neutrals["eig_neutral_grid"])
        self.assertEqual((got["top"], got["right"]), (False, False), "top and right spines off")
        self.assertEqual(got["title"], tokens["typography"]["roles"]["chart_title"]["size_pt"])
        black = next(c["hex"] for c in tokens["colors"]["brand"] if c["id"] == "eig_black")
        self.assertEqual(got["text"].upper(), black)


STATA_BINARIES = ("stata-mp", "stata-se", "stata")
# A quoted 6-digit hex string ("024140" or "#024140") or a quoted RGB triple
# ("2 65 64"): the two ways a color literal reaches a Stata command.
STATA_HEX_RE = re.compile(r'"#?[0-9A-Fa-f]{6}"')
STATA_RGB_RE = re.compile(r'"\d{1,3} \d{1,3} \d{1,3}"')
STATA_DO_RE = re.compile(r'^\s*(?:(capture|cap)\s+)?(?:(?:quietly|qui|noisily|noi)\s+)?(?:do|run)\s')


def handwritten_do_files(style_root: Path = STYLE_ROOT) -> list[Path]:
    """Every .do file under the style tree that sync_tokens.py did not generate."""
    return sorted(
        p for p in style_root.rglob("*.do")
        if "Auto-generated" not in p.read_text(encoding="utf-8").split("\n", 1)[0]
    )


def stata_statements(path: Path) -> list[tuple[int, str]]:
    """(line number, text) for each non-blank, non-comment line of a do-file."""
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith(("*", "//")):
            out.append((n, stripped))
    return out


def stata_color_literals(path: Path) -> list[str]:
    return [
        f"{path.name}:{n}: {text}"
        for n, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if STATA_HEX_RE.search(text) or STATA_RGB_RE.search(text)
    ]


def uncaptured_do_rc(path: Path) -> list[str]:
    """A `do` whose next statement reads `_rc` but that is not run under `capture`."""
    statements = stata_statements(path)
    problems = []
    for (n, text), (_, following) in zip(statements, statements[1:]):
        match = STATA_DO_RE.match(text)
        if match and "_rc" in following and not match.group(1):
            problems.append(f"{path.name}:{n}: {text}")
    return problems


class StataStaticTests(unittest.TestCase):
    """The hand-written Stata files take colors from token globals and capture their `do`s."""

    def test_do_files_exist(self) -> None:
        names = {p.name for p in handwritten_do_files()}
        self.assertLessEqual({"eig_theme.do", "check-fonts.do", "generate_examples.do"}, names)

    def test_no_color_literals_in_handwritten_do_files(self) -> None:
        found = [hit for p in handwritten_do_files() for hit in stata_color_literals(p)]
        self.assertEqual(found, [], "use the $EIG_HEX_* / $EIG_RGB_* / $EIG_TABLE_* globals")

    def test_color_lint_catches_literals(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eig-style-do-") as tmp:
            planted = Path(tmp) / "planted.do"
            planted.write_text(
                'putdocx table t(1,.), shading("024140")\n'
                'twoway scatter y x, mcolor("2 65 64")\n'
                'twoway scatter y x, mcolor("$EIG_RGB_EIG_TEAL_900")\n',
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(len(stata_color_literals(planted)), 2)

    def test_globals_used_are_defined(self) -> None:
        # Without Stata, a misspelled global would expand to "" silently; check the names.
        token_do = STYLE_ROOT / "themes" / "stata" / "eig_tokens.do"
        defined = set(re.findall(r"^global (\w+)", token_do.read_text(encoding="utf-8"), re.M))
        for path in handwritten_do_files():
            text = path.read_text(encoding="utf-8")
            defined |= set(re.findall(r"^\s*global (\w+)", text, re.M))
            # A per-role global built in a loop: global EIG_FONT_`role'_RESOLVED.
            for prefix, suffix in re.findall(r"\bglobal (EIG_\w*)`role'(\w*)", text):
                defined |= {f"{prefix}{role}{suffix}" for role in ("HEADLINE", "BODY")}
        defined.add("EIG_STYLE_DIR")  # set by the user or by eig_load_tokens
        used = {
            f"{p.name}: {name}"
            for p in handwritten_do_files()
            # A name built from a local (${EIG_FONT_`role'}) is checked where it is built.
            for name in re.findall(r"\$\{?(EIG_\w+)(?![\w`])", p.read_text(encoding="utf-8"))
            if name not in defined
        }
        self.assertEqual(sorted(used), [], "every $EIG_* global is set by the tokens or the theme")

    def test_graph_defaults_use_resolved_fonts(self) -> None:
        # The installers install Source Serif 4, so the title font must be the family
        # the check found, not the primary name "Source Serif Pro".
        checker = (FONTS_DIR / "check-fonts.do").read_text(encoding="utf-8")
        self.assertIn("global EIG_FONT_`role'_RESOLVED", checker)
        theme = (STYLE_ROOT / "themes" / "stata" / "eig_theme.do").read_text(encoding="utf-8")
        body = theme[theme.index("program define eig_graph_defaults"):]
        body = body[:body.index("\nend")]
        for role, local in (("HEADLINE", "titlefont"), ("BODY", "bodyfont")):
            resolved = body.find(f'local {local} "$EIG_FONT_{role}_RESOLVED"')
            primary = body.find(f'local {local} "$EIG_FONT_{role}"')
            self.assertNotEqual(resolved, -1, f"{local} reads EIG_FONT_{role}_RESOLVED")
            self.assertLess(resolved, primary, f"{local}: the resolved family comes first")

    def test_style_dir_is_absolute(self) -> None:
        theme = (STYLE_ROOT / "themes" / "stata" / "eig_theme.do").read_text(encoding="utf-8")
        body = theme[theme.index("program define eig_style_dir"):]
        body = body[:body.index("\nend")]
        self.assertRegex(body, r"quietly cd `\"`found'\"'\n\s*local found `\"`c\(pwd\)'\"'")

    def test_theme_uses_generated_scheme(self) -> None:
        theme = (STYLE_ROOT / "themes" / "stata" / "eig_theme.do").read_text(encoding="utf-8")
        self.assertRegex(theme, r"(?m)^\s*set scheme eig\s*$")
        self.assertRegex(theme, r"(?m)^\s*adopath \+ .*themes/stata")
        self.assertTrue(SCHEME_PATH.is_file(), "set scheme eig reads scheme-eig.scheme")
        self.assertNotRegex(theme, r"(?m)^\s*set scheme s2color")

    def test_do_followed_by_rc_is_captured(self) -> None:
        found = [hit for p in handwritten_do_files() for hit in uncaptured_do_rc(p)]
        self.assertEqual(found, [], "an uncaptured `do` aborts before `_rc` is read")

    def test_rc_lint_catches_uncaptured_do(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eig-style-do-") as tmp:
            planted = Path(tmp) / "planted.do"
            planted.write_text(
                'quietly do "a.do"\nif _rc exit 1\n'
                'capture quietly do "b.do"\nif _rc exit 1\n',
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(uncaptured_do_rc(planted), ['planted.do:1: quietly do "a.do"'])


def stata_binary() -> str | None:
    return next((b for b in STATA_BINARIES if shutil.which(b)), None)


class StataRenderTests(unittest.TestCase):
    """The Stata example renders with the EIG scheme (needs a Stata binary)."""

    def test_stata_example_renders(self) -> None:
        binary = stata_binary()
        if binary is None:
            self.skipTest(f"no Stata binary ({', '.join(STATA_BINARIES)}) on PATH; "
                          "the Stata example was not rendered")
        with tempfile.TemporaryDirectory(prefix="eig-style-stata-") as tmp:
            out = Path(tmp) / "out"
            example = STYLE_ROOT / "examples" / "stata" / "generate_examples.do"
            env = dict(os.environ, EIG_STYLE_DIR=str(STYLE_ROOT))
            proc = run([binary, "-b", "do", str(example), str(out)], cwd=tmp, env=env)
            log = Path(tmp) / "generate_examples.log"
            detail = log.read_text(encoding="utf-8", errors="replace")[-2000:] if log.is_file() else ""
            self.assertEqual(proc.returncode, 0, detail)
            self.assertNotRegex(detail, r"\nr\(\d+\);", "the do-file stopped on an error")
            for name in ("twoway_scatter.png", "bar_chart.png", "eig_table_example.docx"):
                self.assertTrue((out / name).is_file(), f"{name} was not written\n{detail}")


EXAMPLES_DIR = STYLE_ROOT / "examples"
PY_EXAMPLE_MODULES = ("matplotlib", "seaborn", "plotly", "pandas", "numpy", "jinja2")


def repo_status() -> str | None:
    """`git status --porcelain` for the repo, or None when git or the repo is absent."""
    if shutil.which("git") is None:
        return None
    proc = run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO_ROOT)
    return proc.stdout if proc.returncode == 0 else None


class ExampleSmokeTests(unittest.TestCase):
    """The example scripts render into a temporary directory and leave the repo clean."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="eig-style-examples-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def assert_outputs(self, out: Path, names: tuple[str, ...], detail: str) -> None:
        for name in names:
            with self.subTest(output=name):
                path = out / name
                self.assertTrue(path.is_file() and path.stat().st_size > 0,
                                f"{name} was not written\n{detail}")

    def test_r_example_renders(self) -> None:
        reason = r_skip_reason()
        if reason:
            skip_unless_required(self, reason, "REQUIRE_R")
        out = self.tmp / "out"
        work = self.tmp / "work"
        work.mkdir()
        proc = run(["Rscript", str(EXAMPLES_DIR / "r" / "generate_examples.R"), str(out)], cwd=work)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_outputs(out, ("base_scatter.png", "ggplot_scatter.png"), proc.stderr)
        self.assertEqual(png_size(out / "ggplot_scatter.png"), (1430, 770), "6.5 x 3.5 in at 220 dpi")
        self.assertEqual(list(work.iterdir()), [], "nothing is written to the working directory")

    def test_r_example_default_leaves_repo_clean(self) -> None:
        reason = r_skip_reason()
        if reason:
            skip_unless_required(self, reason, "REQUIRE_R")
        before = repo_status()
        if before is None:
            self.skipTest("git or the repository is not available; repo cleanliness not checked")
        proc = run(["Rscript", str(EXAMPLES_DIR / "r" / "generate_examples.R")], cwd=REPO_ROOT)
        match = re.search(r"Wrote R example outputs to: (.+?)\s*$", proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNotNone(match, proc.stdout)
        out = Path(match.group(1)).resolve()
        self.assertFalse(out.is_relative_to(REPO_ROOT.resolve()), f"default output inside the repo: {out}")
        self.addCleanup(shutil.rmtree, out, True)  # only ever a directory outside the repo
        self.assertEqual(repo_status(), before, "running the example changed git status")

    def test_python_example_renders(self) -> None:
        missing = python_missing(*PY_EXAMPLE_MODULES)
        if missing:
            skip_unless_required(self, f"Python packages missing: {', '.join(missing)}", "REQUIRE_PLOTTING")
        out = self.tmp / "out"
        env = dict(os.environ, MPLCONFIGDIR=str(self.tmp / "mpl"), MPLBACKEND="Agg")
        proc = run([sys.executable, str(EXAMPLES_DIR / "python" / "generate_examples.py"), str(out)],
                   cwd=self.tmp, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_outputs(out, ("matplotlib_scatter.png", "seaborn_bar.png",
                                  "plotly_scatter.html", "styled_table.html"), proc.stderr)
        self.assertNotIn("Failed to find font weight", proc.stderr)


DW_VALIDATOR = STYLE_ROOT / "scripts" / "compliance" / "check_datawrapper_manifest.py"


class DatawrapperManifestTests(unittest.TestCase):
    """The manifest validator checks the token version and the colors actually sent."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="eig-dw-manifest-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.tokens = load_tokens()
        self.version = self.tokens["meta"]["version"]
        order = self.tokens["colors"]["discrete_order"]["token_ids"]
        hex_by_id = {c["id"]: c["hex"] for c in color_entries(self.tokens)}
        self.primary = [hex_by_id[i] for i in order[:3]]
        self.legacy = list(self.tokens["colors"]["legacy_semantic_sets"][0]["entries"].values())[:2]

    def row(self, **overrides: Any) -> dict[str, Any]:
        base = {
            "run_timestamp_utc": "2026-09-29T12:00:00Z",
            "figure_key": "fig_wages",
            "chart_id": "aBc12",
            "chart_url": "https://datawrapper.dwcdn.net/aBc12/1/",
            "rows_uploaded": 40,
            "palette_mode": "primary_2022",
            "token_source_path": "Infrastructure/style/tokens/eig-style-tokens.v1.json",
            "token_version": self.version,
            "legacy_metadata_path": "",
            "colors_sent": self.primary,
        }
        base.update(overrides)
        return base

    def check(self, rows: list[dict[str, Any]], *extra: str,
              name: str = "manifest.json") -> subprocess.CompletedProcess[str]:
        path = self.tmp / name
        if name.endswith(".csv"):
            import csv

            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        else:
            path.write_text(json.dumps(rows), encoding="utf-8", newline="\n")
        return run([sys.executable, str(DW_VALIDATOR), str(path), *extra])

    def test_compliant_manifest_passes(self) -> None:
        proc = self.check([self.row(), self.row(colors_sent=None)])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_csv_colors_are_split(self) -> None:
        proc = self.check([self.row(colors_sent="; ".join(self.primary))], name="manifest.csv")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.check([self.row(colors_sent=f"{self.primary[0]};#123456")], name="bad.csv")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("#123456 is not a token color", proc.stderr)

    def test_net_new_hex_fails(self) -> None:
        proc = self.check([self.row(colors_sent=[*self.primary, "#FF00FF"])])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("#FF00FF is not a token color (net-new hex)", proc.stderr)
        proc = self.check([self.row(colors_sent=["teal"])])
        self.assertIn("is not a #RRGGBB hex color", proc.stderr)

    def test_legacy_colors_need_legacy_mode(self) -> None:
        proc = self.check([self.row(colors_sent=self.legacy)])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("is a legacy token color", proc.stderr)
        proc = self.check([self.row(colors_sent=self.legacy, palette_mode="legacy",
                                    legacy_metadata_path="meta/legacy.json")])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_stale_token_version_fails(self) -> None:
        proc = self.check([self.row(token_version="1.0.0")])
        self.assertEqual(proc.returncode, 1)
        self.assertIn(f"older than the token file's {self.version}", proc.stderr)
        proc = self.check([self.row(token_version="v2")])
        self.assertIn("does not match", proc.stderr)

    def test_version_is_read_from_the_token_file(self) -> None:
        bumped = dict(self.tokens, meta=dict(self.tokens["meta"], version="9.0.0"))
        token_path = self.tmp / "tokens.json"
        token_path.write_text(json.dumps(bumped), encoding="utf-8", newline="\n")
        proc = self.check([self.row()], "--tokens", str(token_path))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("older than the token file's 9.0.0", proc.stderr)
        proc = self.check([self.row(token_version="9.0.0")], "--tokens", str(token_path))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_missing_token_file_is_exit_2(self) -> None:
        proc = self.check([self.row()], "--tokens", str(self.tmp / "absent.json"))
        self.assertEqual(proc.returncode, 2)

    def test_ci_template_calls_real_validators(self) -> None:
        template = (STYLE_ROOT / "docs" / "ci" /
                    "datawrapper-compliance.workflow.template.yml").read_text(encoding="utf-8")
        scripts = re.findall(r"python3 (\S+\.py)", template)
        self.assertEqual(len(scripts), 2, scripts)
        for rel in scripts:
            self.assertTrue((REPO_ROOT / rel).is_file(), rel)
        manifest_glob = re.search(r'MANIFEST_GLOB: "([^"]+)"', template)
        self.assertIsNotNone(manifest_glob)
        self.assertTrue({".csv", ".json"} <= {Path(g).suffix for g in manifest_glob[1].split()})


FONTS_DIR = STYLE_ROOT / "scripts" / "fonts"
FONT_SOURCES = FONTS_DIR / "font-sources.tsv"
INSTALLERS = ("install-fonts-linux.sh", "install-fonts-windows.ps1", "install-fonts-macos.sh")
URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
# Set by --network on the command line; off in the maintenance sweep.
NETWORK = False


def font_sources() -> list[dict[str, str]]:
    """Rows of font-sources.tsv: family, style, file, sha256, url."""
    lines = [
        line for line in FONT_SOURCES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


class FontInstallerTests(unittest.TestCase):
    """The installers share one URL list and parse; every checker accepts Source Serif 4."""

    def test_font_sources_cover_primary_families(self) -> None:
        rows = font_sources()
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(file=row.get("file")):
                self.assertEqual(set(row), {"family", "style", "file", "sha256", "url"})
                self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(row["url"].startswith("https://"), row["url"])
                self.assertTrue(row["url"].endswith("/" + row["file"]), "the URL names the file")
        typography = load_tokens()["typography"]
        families = {row["family"] for row in rows}
        for role in ("headline", "body"):
            spec = typography[role]
            accepted = {spec["primary_family"], *spec["accept_as_primary"]}
            self.assertTrue(families & accepted, f"{role}: no family the tokens accept as primary")

    def test_installers_use_only_tsv_urls(self) -> None:
        allowed = {row["url"] for row in font_sources()}
        for name in INSTALLERS:
            with self.subTest(installer=name):
                urls = set(URL_RE.findall((FONTS_DIR / name).read_text(encoding="utf-8")))
                self.assertEqual(urls - allowed, set(), "installer URLs live in font-sources.tsv")

    def test_installers_read_tsv_and_verify_checksums(self) -> None:
        for name, verify in (("install-fonts-linux.sh", "sha256_of"),
                             ("install-fonts-windows.ps1", "Get-FileHash")):
            with self.subTest(installer=name):
                text = (FONTS_DIR / name).read_text(encoding="utf-8")
                self.assertIn(FONT_SOURCES.name, text)
                self.assertIn(verify, text)
        # macOS runs the same verified installer with a different font directory.
        mac = (FONTS_DIR / "install-fonts-macos.sh").read_text(encoding="utf-8")
        self.assertRegex(mac, r'exec bash "\$\{SCRIPT_DIR\}/install-fonts-linux\.sh"')
        self.assertNotIn("brew install", mac)

    @unittest.skipIf(sys.platform == "win32", "the macOS and Linux shell installers run on those platforms (CI tests them there); Windows uses install-fonts-windows.ps1")
    def test_shell_installers_parse(self) -> None:
        for name in ("install-fonts-linux.sh", "install-fonts-macos.sh"):
            with self.subTest(installer=name):
                proc = run(["bash", "-n", str(FONTS_DIR / name)])
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def run_installer(self, tmp: Path, curl_body: str, installer: Path | None = None,
                      ) -> tuple[subprocess.CompletedProcess[str], Path]:
        """Run an installer with a fake curl; returns the result and the font directory."""
        bin_dir = tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        fake = bin_dir / "curl"
        fake.write_text("#!/bin/sh\n" + curl_body, encoding="utf-8", newline="\n")
        fake.chmod(0o755)
        font_dir = tmp / "fonts"
        env = dict(os.environ, HOME=str(tmp), EIG_FONT_DIR=str(font_dir), TMPDIR=str(tmp),
                   PATH=f"{bin_dir}{os.pathsep}/usr/bin:/bin")
        script = installer or FONTS_DIR / "install-fonts-linux.sh"
        return run(["bash", str(script)], cwd=tmp, env=env), font_dir

    # A fake curl that writes a fixed body to the -o path.
    WRITE_BODY = (
        'out=""\nwhile [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done\n'
        'echo "fake curl" >&2\nprintf "not a font" > "$out"\n'
    )

    @unittest.skipIf(sys.platform == "win32", "the macOS and Linux shell installers run on those platforms (CI tests them there); Windows uses install-fonts-windows.ps1")
    def test_installer_continues_past_a_failed_download(self) -> None:
        # Every download fails; the installer must try each row and report them all,
        # not stop at the first (the old `set -e` early exit).
        with tempfile.TemporaryDirectory(prefix="eig-style-fonts-") as tmp:
            proc, font_dir = self.run_installer(Path(tmp), 'echo "fake curl: $*" >&2\nexit 22\n')
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertEqual(proc.stderr.count("fake curl:"), len(font_sources()), proc.stderr)
            self.assertEqual(list(font_dir.glob("*")), [], "a failed download installs nothing")

    @unittest.skipIf(sys.platform == "win32", "the macOS and Linux shell installers run on those platforms (CI tests them there); Windows uses install-fonts-windows.ps1")
    def test_installer_refuses_a_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eig-style-fonts-") as tmp:
            proc, font_dir = self.run_installer(Path(tmp), self.WRITE_BODY)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertEqual(proc.stderr.count("checksum mismatch"), len(font_sources()), proc.stderr)
            self.assertEqual(list(font_dir.glob("*")), [], "a mismatched download is not installed")

    @unittest.skipIf(sys.platform == "win32", "the macOS and Linux shell installers run on those platforms (CI tests them there); Windows uses install-fonts-windows.ps1")
    def test_installer_installs_a_matching_download(self) -> None:
        # A copy of the installer beside a TSV whose checksum matches the fake body.
        import hashlib

        with tempfile.TemporaryDirectory(prefix="eig-style-fonts-") as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            for name in ("install-fonts-linux.sh", "install-fonts-macos.sh"):
                shutil.copy2(FONTS_DIR / name, scripts / name)
            digest = hashlib.sha256(b"not a font").hexdigest()
            (scripts / FONT_SOURCES.name).write_text(
                "family\tstyle\tfile\tsha256\turl\n"
                f"Fake Sans\tRegular\tFakeSans-Regular.ttf\t{digest}\t"
                "https://example.org/FakeSans-Regular.ttf\n",
                encoding="utf-8",
                newline="\n",
            )
            for name in ("install-fonts-linux.sh", "install-fonts-macos.sh"):
                with self.subTest(installer=name):
                    proc, font_dir = self.run_installer(Path(tmp), self.WRITE_BODY, scripts / name)
                    # fontconfig, when present, cannot list a fake family: exit 2 after install.
                    self.assertIn(proc.returncode, (0, 2), proc.stdout + proc.stderr)
                    self.assertEqual((font_dir / "FakeSans-Regular.ttf").read_bytes(), b"not a font")
                    shutil.rmtree(font_dir)

    def test_python_checker_accepts_source_serif_4(self) -> None:
        code = (
            "import importlib.util, sys\n"
            f"sys.path.insert(0, {str(PY_THEME_DIR)!r})\n"
            "import eig_theme\n"
            "eig_theme.installed_font_families = lambda: {'Source Serif 4', 'Open Sans'}\n"
            f"spec = importlib.util.spec_from_file_location('chk', {str(FONTS_DIR / 'check-fonts.py')!r})\n"
            "chk = importlib.util.module_from_spec(spec); spec.loader.exec_module(chk)\n"
            "sys.argv = ['check-fonts.py']\n"
            "sys.exit(chk.main())\n"
        )
        proc = run([sys.executable, "-c", code])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("OK headline: Source Serif 4", proc.stdout)

    def test_r_checker_accepts_source_serif_4(self) -> None:
        reason = r_skip_reason()
        if reason:
            skip_unless_required(self, reason, "REQUIRE_R")
        checker = (FONTS_DIR / "check-fonts.R").as_posix()
        with tempfile.TemporaryDirectory(prefix="eig-style-fonts-") as tmp:
            wrapper = Path(tmp) / "wrapper.R"
            # The checker finds itself through --file= and sources the theme; stand in
            # for both, then replace the font enumerator after the theme loads.
            wrapper.write_text(
                f'commandArgs <- function(trailingOnly = FALSE) '
                f'if (trailingOnly) character(0L) else "--file={checker}"\n'
                'source <- function(file, ...) {\n'
                '  base::source(file, ...)\n'
                '  assign("eig_available_fonts", function() c("Source Serif 4", "Open Sans"),\n'
                '         envir = globalenv())\n'
                '}\n'
                f'base::source("{checker}")\n',
                encoding="utf-8",
                newline="\n",
            )
            proc = run(["Rscript", "--vanilla", str(wrapper)], cwd=tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK headline: Source Serif 4", proc.stderr)

    def test_stata_checker_reads_token_font_lists(self) -> None:
        # Static, because Stata is absent: the checker's primary loop covers the
        # accepted families, and the generated globals list Source Serif 4.
        token_do = (STYLE_ROOT / "themes" / "stata" / "eig_tokens.do").read_text(encoding="utf-8")
        accept = re.search(r"^global EIG_FONT_HEADLINE_ACCEPT (.*)$", token_do, re.M)
        self.assertIsNotNone(accept)
        self.assertIn('"Source Serif 4"', accept.group(1))
        checker = (FONTS_DIR / "check-fonts.do").read_text(encoding="utf-8")
        self.assertRegex(checker, r"(?m)^foreach role in HEADLINE BODY \{")
        for suffix in ("ACCEPT", "FALLBACK"):
            self.assertIn(f"${{EIG_FONT_`role'_{suffix}}}", checker)
        families = {f for role in ("headline", "body")
                    for f in (load_tokens()["typography"][role]["primary_family"],
                              *load_tokens()["typography"][role]["fallback_stack"])}
        code_lines = [text for _, text in stata_statements(FONTS_DIR / "check-fonts.do")
                      if not text.startswith("di")]
        hard_coded = [f for f in families if any(f'"{f}"' in line for line in code_lines)]
        self.assertEqual(hard_coded, [], "font names come from the token globals")


class FontSourceNetworkTests(unittest.TestCase):
    """Every URL in font-sources.tsv resolves and matches its checksum (only with --network)."""

    def test_font_source_urls_resolve(self) -> None:
        if not NETWORK:
            self.skipTest("network checks are off; run test_style.py --network")
        import hashlib
        import urllib.request

        for row in font_sources():
            with self.subTest(url=row["url"]):
                request = urllib.request.Request(row["url"], method="HEAD")
                with urllib.request.urlopen(request, timeout=SUBPROCESS_TIMEOUT) as response:
                    self.assertEqual(response.status, 200)
                # Hashed in memory; nothing is written to disk.
                with urllib.request.urlopen(row["url"], timeout=SUBPROCESS_TIMEOUT) as response:
                    digest = hashlib.sha256(response.read()).hexdigest()
                self.assertEqual(digest, row["sha256"], "the pinned file changed")


if __name__ == "__main__":
    if "--network" in sys.argv:
        sys.argv.remove("--network")
        NETWORK = True
    program = unittest.main(exit=False)
    # Print every skip reason at any verbosity, so a skipped case is never silent.
    for case, reason in program.result.skipped:
        print(f"SKIPPED {case.id().removeprefix('__main__.')}: {reason}")
    sys.exit(0 if program.result.wasSuccessful() else 1)
