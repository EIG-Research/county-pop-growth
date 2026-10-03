#!/usr/bin/env python3
"""EIG-styled Python example outputs: matplotlib, seaborn, plotly, and a styled table.

    python3 Infrastructure/style/examples/python/generate_examples.py [out_dir]

Outputs go to out_dir, or to a new temporary directory when it is omitted, so a run
leaves nothing in the repository. Every color, font, and size comes from the tokens.
Exit codes: 0 written, 2 a plotting package is missing.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

STYLE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(STYLE_ROOT / "themes" / "python"))

# Figure text follows Infrastructure/style/docs/eig-figure-style.md: a sentence-case
# title in the image, then a note line above the source line.
TITLE = "Heavier cars get fewer miles per gallon"
NOTE = "Note: Simulated data for illustration."
SOURCE = "Source: Synthetic example data."


def add_note_and_source(fig) -> None:
    """Note and source lines, flush left under the plot, in the caption role's size."""
    import eig_theme

    size = eig_theme.TYPOGRAPHY["roles"]["notes_caption"]["size_pt"]
    color = eig_theme.NEUTRALS["eig_neutral_caption"]
    fig.text(0.01, 0.01, f"{NOTE}\n{SOURCE}", ha="left", va="bottom", fontsize=size, color=color)


def make_data(n: int = 140):
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(42)
    weight = rng.normal(3.1, 0.65, n).clip(1.5, 5.7)
    cyl = rng.choice([4, 6, 8], n, p=[0.4, 0.35, 0.25])
    origin = rng.choice(["Domestic", "Foreign"], n, p=[0.58, 0.42])
    mpg = 41.5 - 5.0 * weight - 0.75 * (cyl - 4) + rng.normal(0, 2.1, n)
    return pd.DataFrame(
        {"weight": weight.round(3), "mpg": mpg.round(2), "cyl": cyl, "origin": origin}
    )


def main(argv: list[str]) -> int:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import jinja2  # noqa: F401 - pandas needs it for the styled table
        import matplotlib.pyplot as plt
        import plotly.express as px
        import seaborn as sns
    except ImportError as exc:
        print(f"ERROR: Missing dependency: {exc}", file=sys.stderr)
        print(f"Install with: pip install -r {STYLE_ROOT / 'requirements.txt'}", file=sys.stderr)
        return 2

    import eig_theme

    out_dir = Path(argv[0]) if argv else Path(tempfile.mkdtemp(prefix="eig-examples-py-"))
    out_dir.mkdir(parents=True, exist_ok=True)

    eig_theme.assert_eig_fonts(allow_fallback=True)
    eig_theme.set_eig_theme()
    df = make_data()
    palette = eig_theme.eig_palette("discrete")

    fig, ax = plt.subplots()
    sns.scatterplot(data=df, x="weight", y="mpg", hue="cyl", palette=palette[:3], ax=ax, alpha=0.9)
    eig_theme.eig_title(ax, TITLE)
    ax.set_xlabel("Weight (thousands of pounds)")
    ax.set_ylabel("Miles per gallon")
    ax.legend(title="Cylinders", frameon=False)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    add_note_and_source(fig)
    fig.savefig(out_dir / "matplotlib_scatter.png", dpi=220)
    plt.close(fig)

    summary = (
        df.groupby("origin", as_index=False)
        .agg(mean_mpg=("mpg", "mean"), mean_weight=("weight", "mean"))
        .round(1)
    )
    fig2, ax2 = plt.subplots()
    sns.barplot(data=summary, x="origin", y="mean_mpg", hue="origin", palette=palette[:2],
                legend=False, ax=ax2)
    eig_theme.eig_title(ax2, "Foreign cars average more miles per gallon")
    ax2.set_xlabel("")
    ax2.set_ylabel("Mean miles per gallon")
    fig2.tight_layout(rect=(0, 0.08, 1, 1))
    add_note_and_source(fig2)
    fig2.savefig(out_dir / "seaborn_bar.png", dpi=220)
    plt.close(fig2)

    fig_plotly = px.scatter(
        df,
        x="weight",
        y="mpg",
        color=df["cyl"].astype(str),
        title=TITLE,
        labels={"weight": "Weight (thousands of pounds)", "mpg": "Miles per gallon",
                "color": "Cylinders"},
        color_discrete_sequence=palette,
    )
    fig_plotly.update_layout(template=eig_theme.eig_plotly_template())
    fig_plotly.add_annotation(
        text=f"{NOTE}<br>{SOURCE}", x=0, y=-0.2, xref="paper", yref="paper",
        xanchor="left", yanchor="top", showarrow=False, align="left",
    )
    fig_plotly.write_html(out_dir / "plotly_scatter.html", include_plotlyjs="cdn")

    table_df = (
        df.groupby("cyl", as_index=False)
        .agg(avg_mpg=("mpg", "mean"), avg_weight=("weight", "mean"))
        .round(1)
        .rename(columns={"cyl": "Cylinders", "avg_mpg": "Mean miles per gallon",
                         "avg_weight": "Mean weight"})
    )
    styled = eig_theme.style_table(table_df).hide(axis="index").set_caption(SOURCE)
    (out_dir / "styled_table.html").write_text(styled.to_html(), encoding="utf-8", newline="\n")

    print(f"Wrote Python example outputs to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
