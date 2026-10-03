# EIG Figure and Table Style

The single specification for charts, maps, and tables in EIG publications, in R, Python, Stata, Datawrapper, and Excel. It follows the 2022 brand lineage: Source Serif Pro headlines, Open Sans text, and the 2022 palette (owner decision D3). Where the 2022 guide (`Infrastructure/style/sources/2022 Style Guide.pdf`) is silent on a data-visualization question, the 2020 guide fills the gap.

Values live in `Infrastructure/style/tokens/eig-style-tokens.v1.json`. This doc names them by token ID; `Infrastructure/style/docs/_generated/tokens.md` lists each value, and the themes read them, so a changed token needs no edit here. Brand-level rules (logo, photography, the 2020 font lineage) are in `Infrastructure/style/docs/eig-brand-guidelines.md`.

---

## 1. Color

- **Series order.** Discrete series take their colors from `colors.discrete_order`, first to last ([series order](_generated/tokens.md#series-order)). The themes apply it: `eig_scale_color()` and `eig_scale_fill()` in R, `eig_palette()` in Python, and the `eig` scheme in Stata. Skip or reorder a color only for a documented reason.
- **One or two series.** A single series uses the first color in the order; two series use the first two.
- **Highlighting.** Draw the element that matters in the first series color and the rest in a `colors.neutrals` gray. `eig_gold_600` has about 2.1:1 contrast on white, below the 3:1 WCAG floor for graphical objects (ambiguity `a-series-order`), so use it for large fills, not thin lines or small marks.
- **How many colors.** The palette governs *which* colors are allowed; graphical-quality discipline governs *how many*. Prefer one or two series colors plus gray, and reserve color for the comparison that matters (`Infrastructure/style/docs/tufte-principles.md` §8).
- **Diverging scales** (maps, heatmaps). No diverging palette is tokenized. Run from `eig_green_700` (high or positive) through `eig_white` to `eig_tan_500` (low or negative). Do not pair red with green.
- **Sequential scales and semantic sets.** The tokenized sequential scales (`eig_seq_blue_5`, `eig_seq_red_5`) and semantic sets (such as `dci_quintile`) come from the 2020 guide and carry status `legacy`, so `Infrastructure/style/docs/eig-legacy-palette-policy.md` governs their use.
- **Neutrals.** Gridlines, rules, axis lines, and caption text use the `colors.neutrals` tokens ([neutrals](_generated/tokens.md#neutrals)). They are `provisional`: the 2022 guide names no neutrals besides black and white.
- **Color vision.** `python3 Infrastructure/scripts/test_style.py` reports adjacent-series contrast and color-vision-deficiency warnings for the default order. For a public-facing figure, check the final chart in a simulator, and label series directly so color is not the only cue.

---

## 2. Fonts and type sizes

- **Families.** Titles use the headline family (`typography.headline`: Source Serif Pro, with Source Serif 4 accepted as primary); all other text uses the body family (`typography.body`: Open Sans). The fallback stacks are in [font families](_generated/tokens.md#font-families).
- **Resolution.** The themes resolve each family in token order (primary, then accepted as primary, then the fallback stack) and warn when they fall back; they never substitute a font silently. Install and check the fonts with `Infrastructure/style/scripts/fonts/README.md`.
- **Sizes.** Each element takes the size of its type role ([type roles](_generated/tokens.md#type-roles)). The role sizes are template values (`source: "template"`); the 2020 guide's smaller sizes are recorded as the alternative in ambiguity `a-type-sizes`.

| Element | Type role |
|---|---|
| Chart title | `chart_title` |
| Subtitle, panel headers, table header | `subtitle` |
| Axis titles, tick labels, legend, data labels, table body | `axis_legend_table_body` |
| Note and source lines | `notes_caption` |

---

## 3. Titles, axes, and labels

### Figure title

- The title sits inside the image, top-left and flush with the plot's left edge, in sentence case, with no "Figure N." prefix. The document supplies the numbering in its own caption ("Figure 1. ...").
- A title that states the finding ("Heavier cars get fewer miles per gallon") serves the reader better than one that names the variables.
- When the layout designer sets the title outside the image, drop it from the figure: the themes accept `title = NULL`.

### Axis titles

- Sentence case, short, with units in parentheses: "Annual earnings (2023 dollars)", "Share of workers (%)".
- A horizontal y-axis title is preferred where space permits.

### Tick labels

- No more decimal places than the data support.
- Commas as thousands separators from 1,000 up.
- The % sign in axis and tick labels; "percent" in words is for body text.
- Year-only date labels ("2000", "2005") unless month-level precision matters.

### Gridlines, axes, and background

- Major horizontal gridlines only, thin, in `eig_neutral_grid`; no vertical or minor gridlines in standard bar and line charts.
- No plot border; remove the top and right axis lines. Axis lines, where drawn, use `eig_neutral_axis`.
- Background `eig_white`.

### Legend and data labels

- Label series directly on the chart where possible. With one series, omit the legend.
- A legend sits right of or below the plot, never over data, and has no border. Its labels match the series names exactly.
- Legend and label text is `eig_black` on light fills and `eig_white` on dark fills.
- Show data labels when they add little clutter. When every mark is labeled, the y-axis and gridlines may be dropped (2020 guide).

---

## 4. Source and note lines

Every figure has a source line:

```
Source: [Full organization name], [year or dataset version].
```

- Place it below the figure, below any note line, flush left, in the `notes_caption` role and `eig_neutral_caption`. Italicize it in the layout where possible.
- Write the source name in full in the source line, even when the text abbreviates it after first use.
- Several sources: "Sources: [Source 1], [year]; [Source 2], [year]."
- Author analysis: "Source: Author's analysis of [dataset], [year]."

### Note line (optional)

- Format: "Note: [Text]." Place it above the source line.
- Use it for methodological caveats, suppressed data, definitions, and rounding notices, in one or two sentences. Longer notes go in a footnote.

---

## 5. Tables

The `tables` tokens set the structure ([tables](_generated/tokens.md#tables)); `eig_style_gt()` in R and `style_table()` in Python apply them.

- Header row: fill `tables.header.background_token`, text `tables.header.text_token`, in the `subtitle` role.
- Body: the `axis_legend_table_body` role, horizontal rules only, no vertical borders and no boxes.
- Right-align numeric columns. The table helpers do not yet do this, so set it per table.
- Use one header family per publication, and keep it consistent.
- Table titles and source and note lines follow §3 and §4.

---

## 6. Size, accessibility, and minimum text size

- **Default size.** A static figure is `sizing.figure_default` (6.5 × 3.5 in). It is a default, not a ceiling: small-multiple arrays and dense displays may exceed it, with the reason noted.
- **Text contrast.** Text meets WCAG AA against its background: 4.5:1, or 3:1 for large text (18pt and above, or 14pt and above in bold).
- **Color independence.** Never encode information by color alone: add direct labels, distinct line styles (solid, dashed, dotted), or pattern fills when color printing is uncertain.
- **Alt text.** A web figure's alt text states its key finding, not its appearance: `alt="Bar chart showing that wage growth in the bottom income quintile lagged the top quintile by 12 percentage points between 2000 and 2022."`

<a id="text-floor"></a>

### Minimum text size

No text in a figure is smaller than the floor in `sizing.text_floor_pt`: **7pt for print** and **7.5pt for screen, which is 10px at 96 dpi** ([sizes](_generated/tokens.md#sizes)). The token is the source; `test_style.py` fails if this sentence and the token disagree.

---

## 7. Graphical quality

Brand compliance (§1–§6) confirms a figure is on-brand. This section confirms it is a good display of the data. `Infrastructure/style/docs/tufte-principles.md` holds the full guidance; the `eig-tufte-critique` skill applies it, and `eig-style-review` runs it as its second pass.

- **Integrity.** The visual effect matches the data effect (lie factor about 1): no truncated axes that exaggerate change, no 3D on 2D data, no area or volume encoding of linear quantities. Deflate money and keep consistent baselines in time series.
- **Eraser test.** Every element earns its ink; this is why EIG drops plot boxes, vertical gridlines, and redundant legends.
- **Collision test.** No text collides with data or other text: move prose to the note line, labels to a margin or strip, and use leader lines.
- **Compared to what?** The display makes its key comparison obvious; prefer small multiples with identical scales for category and time comparisons.
- **Results displays.** Regression and event-study plots use a neutral baseline with one accent color, a light tint for confidence intervals, and a marked treatment moment. A causal reading on a chart must match the identification strategy (`Infrastructure/style/docs/tufte-principles.md` §16).

---

## 8. Tools

Per-language quickstarts that run from the repository root are in `Infrastructure/style/themes/README.md`.

| Tool | File | Entry points |
|---|---|---|
| R: ggplot2, base, plotly, gt | `Infrastructure/style/themes/r/eig_theme.R` | `eig_theme_ggplot()`, `eig_scale_color()`, `eig_scale_fill()`, `eig_scale_fill_seq()`, `eig_base_defaults()`, `eig_plotly_layout()`, `eig_style_gt()` |
| Python: matplotlib, seaborn, plotly, pandas | `Infrastructure/style/themes/python/eig_theme.py` | `set_eig_theme()`, `eig_title()`, `eig_palette()`, `eig_plotly_template()`, `style_table()` |
| Stata | `Infrastructure/style/themes/stata/eig_theme.do` | `eig_graph_defaults` (sets the generated `eig` scheme), `eig_palette_discrete` |
| Datawrapper | `Infrastructure/style/docs/datawrapper-integration.md` | Token-derived colors and publish manifests |
| Excel | none | The manual rules below |

### Excel (manual)

- Prefer line charts for time series and clustered bars for comparisons.
- Remove the chart border; keep only light, thin horizontal gridlines.
- Apply the series order from §1 by hand, reading the hex values from `_generated/tokens.md`.
- Title in the headline family, other text in the body family; if a family is not installed, use the first installed family in its fallback stack.
- Delete the legend for one series; otherwise place it below the chart.
- Put the note and source lines in a text box below the chart, at the `notes_caption` size.

---

## 9. Checklist

**Brand compliance**
- [ ] Title in the image, sentence case, no "Figure N." prefix (or `title = NULL` when the layout sets it)
- [ ] Source line present and formatted; note line, if any, above it
- [ ] Series colors follow `colors.discrete_order`; no color outside the tokens
- [ ] Major horizontal gridlines only, in `eig_neutral_grid`; no plot border
- [ ] Fonts resolve to a primary or accepted family, or the fallback is noted
- [ ] Tick labels: % sign, thousands commas, minimal decimals
- [ ] Direct labels, or a legend placed off the data
- [ ] No text below the §6 floor
- [ ] Color-vision check and alt text for public web figures

**Graphical quality** (§7)
- [ ] Lie factor about 1
- [ ] Eraser and collision tests pass
- [ ] Answers "compared to what?"
- [ ] Fewest encoded colors: one or two plus gray
