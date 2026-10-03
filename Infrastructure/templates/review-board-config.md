# Review Board Config — Template

Defines `board.yaml`, the one file of a review board that a person writes. It says what is
under review, how it is rendered, who reviews it, and whether it may be hosted outside this
machine. The machine-written files are defined in
`Infrastructure/templates/review-board-ledger.md`, and all three are governed by
`Infrastructure/rules/review-board-rules.md`.

**Location:** `records/review_boards/<project id>--<board id>/board.yaml`

**Writer:** the owner. The agent drafts it with the owner at setup, and edits it later only
with the owner's approval, recorded in a round plan (RB-L2).

---

## `board.yaml`

```yaml
schema_version: 1
project:
  id: my-project                  # basename of the reviewed project's root (checked, RB-L1)
board:
  id: brief-figures               # [a-z0-9][a-z0-9-]*; forms the directory slug
  title: Q3 wages brief — figures
  medium: print                   # print | screen; selects the text floor (RB-M2)
  fixture: false                  # true only in test fixtures

reviewers:                        # exactly one owner (RB-T1)
  - id: bglasner                  # [a-z0-9][a-z0-9._-]*; recorded as `by` on events
    role: owner                   # owner | reviewer
    name: Ben Glasner             # display only
  - id: jdoe
    role: reviewer
    name: J. Doe
    retired: false                # optional; true removes a reviewer without deleting
                                  # them, because their events still name them (RB-L3)

render:
  argv: ["Rscript", "code/render_board.R"]   # run in the project root, no shell (RB-R2);
                                             # "{python}" expands to the CLI's interpreter
  expected_runtime: about 2 minutes          # stated before every render (RB-R3)
  timeout_seconds: 900

items:                            # one entry per rendered item, in board order
  - id: fig-wages-by-sex          # [a-z0-9][a-z0-9-]*; used in file names and URLs
    title: Wages by sex, 2015–2025
    group: labor-market           # the board's group selector; use one group if none apply
    sources:                      # the source of truth, one or more project-relative paths
      - code/04_figures.R
    render: output/figures/fig-wages-by-sex.png   # PNG the render command writes
    svg: output/figures/fig-wages-by-sex.svg      # optional sibling for measurement (RB-M2)
    frozen: false                 # true: record recommendations only, change nothing (RB-R7)
    retired: false                # optional; true drops the item from the board without
                                  # deleting it, because its events still name it (RB-L3)
  - id: fig-dci-map
    title: Distressed communities, 2024
    group: geography
    sources:
      - code/05_maps.R
    render: output/figures/fig-dci-map.png
    svg: null
    frozen: true
```

Field rules the lint enforces (RL-01, RL-14, RL-15):

- Every path is project-relative. No absolute paths, no `..`, and nothing that resolves
  outside the project root.
- Item ids and reviewer ids are unique. Exactly one reviewer has `role: owner`, and the
  owner is never retired.
- Never delete an item or a reviewer once the board has events: set `retired: true`.
  Events are permanent, and an event that names a missing entry fails RL-02.
- `render.argv` is a non-empty list of strings. `timeout_seconds` is a positive integer.
- There is no `hosting` block: the board is local only (RB-H1, RB-H2). A block that sets
  `cleared: true` fails RL-15.

---

## Choosing items and sources

- **One item per rendered file the owner approves.** A figure with an inset is one item.
  A slide deck is one item per slide.
- **`sources` lists every file the fix for this item would normally touch.** Anything else
  is shared code, and editing it trips the stop gate (RB-P2). Listing too little makes
  routine fixes stop for approval; listing a shared theme file as a source hides the fact
  that editing it changes other items. List shared files as sources only when this board is
  the only thing that uses them.
- **Freeze items that are already published or signed off.** A frozen item's
  recommendations go in its response only.

## Writing the render command

The command runs once per `render` and must write every item's PNG, and every declared SVG,
at its declared path. For more than one step, write a small script and point `argv` at it,
because `argv` runs a single program without a shell.

Keep renders deterministic: a fixed size, a fixed DPI, fixed fonts, and no timestamp drawn
into the image. Metadata and compression differences are ignored by the hash (RB-R5), but
anything that changes pixels is not.

The recipes below are illustrations, not requirements. The template prescribes no tooling.

**R (ggplot2).** Render the PNG with `ragg` so the EIG fonts work, and the SVG with
`svglite`, which keeps text as text:

```r
ggplot2::ggsave(
  file.path(path_figures, "fig-wages-by-sex.png"),
  plot = figure_wages_by_sex,
  device = ragg::agg_png,
  width = 6.5,
  height = 3.5,
  units = "in",
  dpi = 300
)

ggplot2::ggsave(
  file.path(path_figures, "fig-wages-by-sex.svg"),
  plot = figure_wages_by_sex,
  device = svglite::svglite,
  width = 6.5,
  height = 3.5,
  units = "in"
)
```

**Python (matplotlib).** Set `svg.fonttype` to `none`. The default converts text to paths,
and the text checks then report `not-measured` (RB-M3):

```python
import matplotlib.pyplot as plt
plt.rcParams["svg.fonttype"] = "none"
fig.savefig("output/figures/fig-wages-by-sex.png", dpi=300)
fig.savefig("output/figures/fig-wages-by-sex.svg")
```

**Stata.** Export both formats from the same graph:

```stata
graph export "output/figures/fig-wages-by-sex.png", width(1950) replace
graph export "output/figures/fig-wages-by-sex.svg", replace
```

**Slides.** Export the deck to PDF, then rasterize one PNG per page. For example, with
LibreOffice and Poppler:

```
soffice --headless --convert-to pdf --outdir output/slides drafts/deck.pptx
pdftoppm -png -r 150 output/slides/deck.pdf output/slides/slide
```

Page-numbered file names shift whenever a slide is inserted or deleted, which makes every
later slide look changed. Either keep the deck's length fixed during review or have the
render script rename pages to stable ids.

---

## Nothing leaves this machine

The board server binds to loopback, and no script uploads a render, a note, or a status.
That is why a board needs no data-clearance decision even for figures built from
restricted-use or licensed data, and why it has no hosted mode (RB-H2). To show someone
else where a review stands, share the committed board directory or its `board.md`. Mind
that the committed files include every note verbatim and each round's reasoning.

---

## Setup Checklist

- [ ] `project.id` equals the basename of the project root
- [ ] Exactly one owner; every other reviewer has `role: reviewer`
- [ ] Every item's `render` path is written by `render.argv`
- [ ] Every item's `sources` covers the files a routine fix would touch
- [ ] SVG siblings declared where text size and palette should be measured
- [ ] Published or signed-off items are `frozen: true`
