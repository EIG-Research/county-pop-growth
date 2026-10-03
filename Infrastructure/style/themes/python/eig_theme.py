"""EIG plotting and table theme helpers for Python.

Every value comes from the generated `eig_tokens.py`, which
`Infrastructure/style/scripts/sync_tokens.py` writes from the token JSON.

Imports are lazy: importing this module needs only the standard library, and
matplotlib, seaborn, plotly, and pandas are imported by the function that uses them.

Fonts resolve in token order: the primary family, then the families accepted as
primary (Source Serif 4 for Source Serif Pro), then the fallback stack. Using a
fallback raises a warning; the theme never substitutes a font silently. Matplotlib
has no rcParam for a title font family, so draw titles with `eig_title()`.
"""

from __future__ import annotations

import subprocess
import warnings
from typing import TYPE_CHECKING, Any, Iterable

try:
    from .eig_tokens import (
        BRAND_COLORS,
        EIG_DISCRETE,
        LEGACY_SEMANTIC_SETS,
        NEUTRALS,
        SEQUENTIAL,
        SIZING,
        TABLES,
        TYPOGRAPHY,
    )
except ImportError:
    from eig_tokens import (  # type: ignore[no-redef]
        BRAND_COLORS,
        EIG_DISCRETE,
        LEGACY_SEMANTIC_SETS,
        NEUTRALS,
        SEQUENTIAL,
        SIZING,
        TABLES,
        TYPOGRAPHY,
    )

if TYPE_CHECKING:
    import pandas as pd
    import plotly.graph_objects as go
    from matplotlib.axes import Axes
    from pandas.io.formats.style import Styler

# Generic CSS family names; matplotlib accepts the same names.
GENERIC_FAMILIES = ("serif", "sans-serif", "monospace")


def _color(token_id: str) -> str:
    return BRAND_COLORS.get(token_id) or NEUTRALS[token_id]


def _role(name: str) -> dict[str, Any]:
    return TYPOGRAPHY["roles"][name]


def _pt_to_px(pt: float) -> float:
    """Points to CSS pixels at 96 dpi."""
    return pt * 96 / 72


# --------------------------------------------------------------------------- fonts
def _families_via_matplotlib() -> set[str]:
    try:
        import matplotlib.font_manager as fm
    except ImportError:
        return set()
    return {f.name for f in fm.fontManager.ttflist if getattr(f, "name", None)}


def _families_via_command(cmd: list[str], parse: Any) -> set[str]:
    try:
        # UTF-8 with replacement: font names are not in the Windows console code page.
        proc = subprocess.run(cmd, capture_output=True, check=False, text=True, timeout=60,
                              encoding="utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return set()
    return parse(proc.stdout or "") if proc.returncode == 0 else set()


def _parse_fc_list(stdout: str) -> set[str]:
    return {part.strip() for line in stdout.splitlines() for part in line.split(",") if part.strip()}


def _parse_system_profiler(stdout: str) -> set[str]:
    out = set()
    for line in stdout.splitlines():
        line = line.strip()
        if line.endswith(":") and not line.startswith("Fonts:"):
            out.add(line[:-1].strip())
    return out


def installed_font_families() -> set[str]:
    """Installed font family names: matplotlib's list, else fc-list, else system_profiler."""
    return (
        _families_via_matplotlib()
        or _families_via_command(["fc-list", ":", "family"], _parse_fc_list)
        or _families_via_command(["system_profiler", "SPFontsDataType"], _parse_system_profiler)
    )


def resolve_font_family(
    role: str, available: Iterable[str] | None = None, warn: bool = True
) -> tuple[str, bool]:
    """The family to draw `role` ("headline" or "body") with, and whether it is primary.

    Walks the token chain: the primary family, then `accept_as_primary`, then the
    fallback stack, whose last entry is a generic family that always resolves.
    """
    spec = TYPOGRAPHY[role]
    installed = set(installed_font_families() if available is None else available)
    for family in [spec["primary_family"], *spec.get("accept_as_primary", [])]:
        if family in installed:
            return family, True
    for family in spec["fallback_stack"]:
        if family in installed or family in GENERIC_FAMILIES:
            if warn:
                warnings.warn(
                    f"EIG {role} font: {spec['primary_family']!r} is not installed; using "
                    f"fallback {family!r}. Install the EIG fonts "
                    "(Infrastructure/style/scripts/fonts/).",
                    stacklevel=2,
                )
            return family, False
    raise RuntimeError(f"No EIG {role} font is available in the token chain.")


def css_font_family(role: str) -> str:
    """A CSS font-family list for browser renderers: the token chain, in order."""
    spec = TYPOGRAPHY[role]
    chain = [spec["primary_family"], *spec.get("accept_as_primary", []), *spec["fallback_stack"]]
    return ", ".join(f"'{f}'" if " " in f else f for f in chain)


def assert_eig_fonts(allow_fallback: bool = False) -> None:
    """Raise RuntimeError unless both roles resolve to a primary (or accepted) family."""
    available = installed_font_families()
    if not available:
        raise RuntimeError("Unable to enumerate installed fonts (install matplotlib or fontconfig).")
    missing = [
        TYPOGRAPHY[role]["primary_family"]
        for role in ("headline", "body")
        if not resolve_font_family(role, available, warn=False)[1]
    ]
    if missing and not allow_fallback:
        raise RuntimeError(
            "Missing required EIG primary fonts: "
            + ", ".join(missing)
            + ". Run an installer in Infrastructure/style/scripts/fonts/ and restart the session."
        )


# --------------------------------------------------------------------------- palettes
def eig_palette(name: str = "discrete") -> list[str]:
    if name == "discrete":
        return list(EIG_DISCRETE)
    if name in SEQUENTIAL:
        return list(SEQUENTIAL[name])
    if name in LEGACY_SEMANTIC_SETS:
        return list(LEGACY_SEMANTIC_SETS[name].values())
    raise KeyError(f"Unknown EIG palette: {name}")


# --------------------------------------------------------------------------- matplotlib
def _heading_weight(family: str) -> str:
    """"semibold" when `family` has a semibold face installed, else "bold", else "normal".

    Matplotlib cannot select a weight from a variable font's axis, so on such installs
    it has only the 400 face; asking for another weight then logs a findfont warning
    on every draw. Generic families ("serif") resolve to fonts that carry bold.
    """
    import matplotlib.font_manager as fm

    weights = set()
    for entry in fm.fontManager.ttflist:
        if entry.name == family:
            weight = entry.weight
            weights.add(fm.weight_dict.get(weight, 400) if isinstance(weight, str) else weight)
    if not weights:
        return "bold"
    if 600 in weights:
        return "semibold"
    return "bold" if any(w >= 700 for w in weights) else "normal"


def eig_rc(figsize: tuple[float, float] | None = None) -> dict[str, Any]:
    """The matplotlib rcParams the EIG theme sets."""
    try:
        import matplotlib  # noqa: F401 - cycler ships with it; import first for a clear error
        from cycler import cycler
    except ImportError as exc:
        raise ImportError("set_eig_theme() and eig_rc() need matplotlib installed.") from exc

    if figsize is None:
        fig = SIZING["figure_default"]
        figsize = (float(fig["width_in"]), float(fig["height_in"]))
    body, _ = resolve_font_family("body")
    text_pt = _role("axis_legend_table_body")["size_pt"]
    title_pt = _role("chart_title")["size_pt"]
    black, white = _color("eig_black"), _color("eig_white")
    return {
        "figure.figsize": figsize,
        "figure.facecolor": white,
        "savefig.facecolor": white,
        "axes.facecolor": white,
        "axes.edgecolor": _color("eig_neutral_axis"),
        "axes.labelcolor": black,
        "axes.titlecolor": black,
        "axes.titlesize": title_pt,
        "axes.titleweight": _heading_weight(body),
        "axes.titlelocation": "left",
        "axes.labelsize": text_pt,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.prop_cycle": cycler(color=list(EIG_DISCRETE)),
        "grid.color": _color("eig_neutral_grid"),
        "grid.linewidth": 0.6,
        "xtick.color": black,
        "ytick.color": black,
        "xtick.labelsize": text_pt,
        "ytick.labelsize": text_pt,
        "legend.fontsize": text_pt,
        "legend.title_fontsize": text_pt,
        "legend.frameon": False,
        "font.family": [body],
        "font.size": text_pt,
        "text.color": black,
    }


def set_eig_theme(figsize: tuple[float, float] | None = None) -> None:
    """Apply the EIG theme to matplotlib, through seaborn when it is installed.

    seaborn's styles rewrite font, text, and grid rcParams, so the EIG values go in one
    `sns.set_theme(rc=...)` call, which applies them after seaborn's own.
    """
    rc = eig_rc(figsize)
    try:
        import seaborn as sns
    except ImportError:
        import matplotlib as mpl

        mpl.rcParams.update(rc)
        return
    sns.set_theme(style="whitegrid", palette=list(EIG_DISCRETE), rc=rc)


def eig_title(ax: Axes, label: str, **kwargs: Any) -> Any:
    """Set an axes title in the headline family (flush left, token size and weight)."""
    headline, _ = resolve_font_family("headline")
    options = {
        "loc": "left",
        "fontfamily": headline,
        "fontsize": _role("chart_title")["size_pt"],
        "fontweight": _heading_weight(headline),
    }
    options.update(kwargs)
    return ax.set_title(label, **options)


# --------------------------------------------------------------------------- plotly
def eig_plotly_template() -> go.layout.Template:
    import plotly.graph_objects as go

    black, white = _color("eig_black"), _color("eig_white")
    return go.layout.Template(
        layout=dict(
            font=dict(
                family=css_font_family("body"),
                size=_pt_to_px(_role("axis_legend_table_body")["size_pt"]),
                color=black,
            ),
            title=dict(
                font=dict(
                    family=css_font_family("headline"),
                    size=_pt_to_px(_role("chart_title")["size_pt"]),
                    color=black,
                ),
                x=0,
            ),
            colorway=list(EIG_DISCRETE),
            paper_bgcolor=white,
            plot_bgcolor=white,
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=True, gridcolor=_color("eig_neutral_grid"), zeroline=False),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
        )
    )


# --------------------------------------------------------------------------- tables
def style_table(df: pd.DataFrame) -> Styler:
    """A pandas Styler with the EIG table tokens: filled header, solid horizontal rules."""
    header, body = TABLES["header"], TABLES["body"]
    header_role, body_role = _role(header["font_role"]), _role(body["font_role"])
    family = css_font_family("body")
    rule = f"1px solid {_color(body['rule_color_token'])}"
    row_rule = f"1px solid {_color(body['row_rule_color_token'])}"
    return df.style.set_table_styles(
        [
            {
                "selector": "th",
                "props": [
                    ("background-color", _color(header["background_token"])),
                    ("color", _color(header["text_token"])),
                    ("font-family", family),
                    ("font-size", f"{header_role['size_pt']}pt"),
                    ("font-weight", "600" if header_role["weight"] == "semibold" else "bold"),
                    ("text-align", "left"),
                    ("border", "0"),
                    ("border-bottom", rule),
                ],
            },
            {
                "selector": "td",
                "props": [
                    ("font-family", family),
                    ("font-size", f"{body_role['size_pt']}pt"),
                    ("color", _color("eig_black")),
                    ("border", "0"),
                    ("border-bottom", row_rule),
                ],
            },
            {"selector": "tbody tr:last-child td", "props": [("border-bottom", rule)]},
            {"selector": "table", "props": [("border-collapse", "collapse")]},
        ]
    )
