# Datawrapper API Notes

What the Datawrapper API and its PNG/SVG exporter actually do, as measured on real exports, for R pipelines that publish through `DatawRappr`. The governance contract (token colors, palette mode, publish manifests, CI) is `Infrastructure/style/docs/datawrapper-integration.md`; this file holds only API behavior. Its sections are numbered 4 and 4.1, the numbers other files cite.

When a probe (see "Probe before you build") finds new behavior, add it to the matching table with the date measured.

### 4) Datawrapper API behavior guardrails
- Use `DatawRappr::dw_data_to_chart(x = data_frame, chart_id = chart_id)`.
- Do not rely on a fixed return type from `DatawRappr::dw_test_key()`; treat object/list success responses as valid and fail only on explicit errors.
- Keep auth material outside tracked code. DatawRappr reads the token from the `DW_KEY` environment variable (`DatawRappr::datawrapper_auth()` writes it to the user's `.Renviron`); keep that file gitignored and never print the key.
- Pass `type =` on every `dw_edit_chart()` call, so a chart whose spec changes type adopts the new type on update.

### 4.1) Known API behavior (measured on real exports)
The API **accepts and stores** many `metadata.visualize` keys that the PNG/SVG exporter then **ignores**, and a response of `200` does not mean a setting rendered. The findings below were measured on exported PNGs from a downstream R pipeline between July and September 2026; Datawrapper may change them, so treat this as a map of where to look, not a guarantee.

**Probe before you build.** Before building on any visualize key not listed as working below, set it on a scratch chart, export a PNG, compare it with a control export, and delete the scratch chart. Use a fresh scratch chart for each probe (see merge semantics below). Record what you measured, and the date, next to the code that relies on it.

**Merge semantics (PATCH, not replace).**
- `dw_edit_chart()` merges into the stored metadata. Keys a call omits keep their old values, including `lines` entries for series that no longer exist and annotations a spec has dropped.
- To make the spec the whole truth, send `range-annotations` and `text-annotations` on every update, as `list()` when there are none.

**Data orientation.**
- The column-chart family (`column-chart`, `grouped-column-chart`, `stacked-column-chart`) reads the matrix the opposite way from line and bar charts. At the default `metadata.data.transpose = FALSE` a tidy one-row-per-x table comes out transposed. Set `data = list(transpose = TRUE)` on `dw_edit_chart()`.
- The same family treats the first column as bar labels only when it is text. A numeric first column (years, for example) is read as another series and the chart plots column sums. Convert the x column to character before upload.
- A line chart whose x column holds years is read as dates, so annotation `x` positions on it must also be dates.
- Datawrapper joins any two consecutive non-empty rows with a line. A sparse series meant to show as points (for example, decennial observations) needs empty rows between its observations and per-line `symbols`.

**Works.**

| Setting | Effect |
|---|---|
| `custom-colors` | Per-series color by column name |
| `custom-range-y`, `custom-ticks-y` (comma-separated string) | Fixed y range and explicit gridline positions |
| `y-grid-format`, `number-format`, `value-label-format` | Tick and label number formats |
| `custom-area-fills` (top level: `from`, `to`, `color`, `opacity`) | Shades between two lines, the only way to draw a ribbon; per-line `fill` is ignored |
| `range-annotations`, `text-annotations` | Shaded spans, rules, and text; render in exports |
| `lines[s].dash = "style2"` / `"style3"` | Dotted / dashed line |
| `lines[s].width = "style3"` | Thinner line (named style, not a number) |
| `lines[s].symbols = list(enabled = TRUE, on = "every", shape, style, size)` | Marks every observation |
| `lines[s].valueLabels = list(enabled = TRUE, first, last, min, max)` | Values under the direct label; clean with about four labeled lines, collides when many crowd one edge |
| `lines[s].directLabel = FALSE` | Removes that series' direct label |
| `label-colors`, `value-label-colors` | Tints direct and value labels in the series color |
| `connector-lines` | Dotted connectors when labels are pushed apart. Also extends each label to the right edge, which reads as data continuing when series end at different x values; turn it off in that case |
| `label-margin` (positive) | Reserves room on the right for direct labels |
| `d3-bars` `custom-range`; a range annotation with `x0 = x1 = 0`, `display = "line"` | Bar axis range; a zero rule |
| `publish = list(blocks = list(logo = list(enabled = FALSE)))` | Removes the chart's own footer logo |

**Accepted but ignored by the export.**

| Setting | Note |
|---|---|
| Numeric line widths: `line-width`, `lines[s].width = <number>`, and other stroke-width key names (14 tried at chart and series level) | Series render at a fixed stroke; only the named `"style3"` (thinner) changed it. No way to make lines heavier has been found |
| `lines[s].directLabeling` | Use `directLabel` instead |
| Top-level `show-value-labels`, `value-labels`, `valueLabelsPosition` | Use per-line `valueLabels` instead |
| Negative `label-margin` | Clamped to 0 |
| `line-symbols = TRUE` (top level) | Works, but puts symbols on every line; prefer per-line `symbols` |
| `d3-bars-split` `custom-range` | Ignored; no zero line |
| Bar-chart `text-annotations` placed by category | Land on the top row whatever category they name |

**Export geometry.**
- Datawrapper renders type at fixed pixel sizes (measured: 12 px ticks, labels, and notes; 14 px subtitle; 18 px title) whatever the logical width. Strokes are fixed too.
- So in `dw_export_chart()`, the logical `width`/`height` set how large type and lines look relative to the frame, and `scale` sets output resolution only. To make type larger on a slide or page, narrow the logical width; to get more pixels, raise `scale`.
- An SVG export does not reliably carry the chart body; place the PNG.

**Outside the pipeline's reach.** Theme edits (`PATCH /v3/themes/<theme>`) need a team-admin role; a standard pipeline key gets `401 ADMIN_ROLE_REQUIRED`. Fonts and base stroke weight set by the theme therefore cannot be changed from R.
