# EIG Theme Assets

The R, Python, and Stata themes apply the EIG figure and table style (`Infrastructure/style/docs/eig-figure-style.md`). Every color, font, and size they use comes from `Infrastructure/style/tokens/eig-style-tokens.v1.json` through the generated token files beside them; the theme files hold no values of their own.

## Quickstarts

Each runs from the repository root. Once loaded, the themes find the style directory themselves (from the `EIG_STYLE_DIR` environment variable, then by walking up from the working directory), so from another directory, such as `code/`, only the path to the theme file changes. With the fallback option shown, the font check passes on any family in the token fallback stack; drop the option to require a primary or accepted family. Either way, the themes warn when they draw with a fallback.

### R

```r
source("Infrastructure/style/themes/r/eig_theme.R")
tokens <- eig_load_tokens()
eig_assert_fonts(tokens, allow_fallback = TRUE)

ggplot2::ggplot(mtcars, ggplot2::aes(wt, mpg, color = factor(cyl))) +
  ggplot2::geom_point() +
  eig_scale_color(tokens) +
  ggplot2::labs(title = "Heavier cars get fewer miles per gallon",
                caption = "Source: Motor Trend, 1974.") +
  eig_theme_ggplot(tokens)
```

Render with `ragg::agg_png()` (or `ggsave(device = ragg::agg_png)`) so system fonts resolve. Base graphics, plotly, and gt take `eig_base_defaults()`, `eig_plotly_layout()`, and `eig_style_gt()`.

### Python

```python
import sys
sys.path.insert(0, "Infrastructure/style/themes/python")
import eig_theme

eig_theme.assert_eig_fonts(allow_fallback=True)
eig_theme.set_eig_theme()
colors = eig_theme.eig_palette()          # the series order, as hex
# eig_theme.eig_title(ax, "Heavier cars get fewer miles per gallon")
```

Importing `eig_theme` needs only the standard library; matplotlib, seaborn, plotly, and pandas are imported by the function that uses them. Plotly and pandas tables take `eig_plotly_template()` and `style_table()`.

### Stata

```stata
do Infrastructure/style/themes/stata/eig_theme.do
eig_load_tokens
capture noisily eig_assert_fonts, allowfallback
eig_graph_defaults
```

`eig_graph_defaults` adds `themes/stata` to the adopath, sets the generated `eig` scheme, and sets the fonts.

## Generated files

`python3 Infrastructure/style/scripts/sync_tokens.py --write` regenerates, from the token JSON:

- `Infrastructure/style/themes/python/eig_tokens.py`
- `Infrastructure/style/themes/r/eig_tokens.R`
- `Infrastructure/style/themes/stata/eig_tokens.do`
- `Infrastructure/style/themes/stata/scheme-eig.scheme`
- `Infrastructure/style/docs/_generated/tokens.md`

Never edit them by hand; `make style-tokens-check` fails on drift.

## Datawrapper and legacy palettes

- Datawrapper publishing: `Infrastructure/style/docs/datawrapper-integration.md`.
- Legacy palettes are exceptions under [docs/eig-legacy-palette-policy.md](../docs/eig-legacy-palette-policy.md); check a legacy metadata sidecar with `python3 Infrastructure/style/scripts/compliance/check_legacy_metadata.py <metadata_json_path>`.
