# EIG Example Outputs

These scripts draw example figures and tables with the token-driven themes, and they double as render smoke tests (`python3 Infrastructure/scripts/test_style.py`). Each follows `Infrastructure/style/docs/eig-figure-style.md`: a sentence-case title in the image, then a note line above the source line.

Each script takes an optional output directory. Without one it writes to a new temporary directory and prints its path, so a run leaves nothing in the repository.

## Before you run

1. Install the fonts and run a check, as `Infrastructure/style/scripts/fonts/README.md` describes. The examples pass on fallback fonts too, with a warning.
2. After a token change, regenerate the theme files: `python3 Infrastructure/style/scripts/sync_tokens.py --write`.

## R

```bash
Rscript Infrastructure/style/examples/r/generate_examples.R [out_dir]
```

Writes `base_scatter.png`, plus `ggplot_scatter.png` (with ggplot2), `plotly_scatter.html` (with plotly and htmlwidgets), and `gt_table.html` (with gt).

## Python

```bash
pip install -r Infrastructure/style/requirements.txt
python3 Infrastructure/style/examples/python/generate_examples.py [out_dir]
```

Writes `matplotlib_scatter.png`, `seaborn_bar.png`, `plotly_scatter.html`, and `styled_table.html`. It exits 2 when a plotting package is missing.

## Stata

From the repository root, in Stata:

```stata
do Infrastructure/style/examples/stata/generate_examples.do [out_dir]
```

Writes `twoway_scatter.png`, `bar_chart.png`, and `eig_table_example.docx`. Without `out_dir` it writes to `eig-examples-stata` in Stata's temporary directory (`c(tmpdir)`).
