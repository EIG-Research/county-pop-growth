---
name: eig-tufte-critique
description: >-
  Ideates and critiques data displays for graphical excellence (data-ink, lie factor, chartjunk, small multiples, analytical design) within EIG brand constraints, with before-and-after recommendations. Use when choosing a chart approach, improving a draft figure, or reviewing a dashboard or results graphic for design quality; brand compliance is eig-style-review's job.
---

# EIG Tufte Critique

Ideate new data displays and critique existing figures, tables, dashboards, and results
graphics for graphical excellence: the design-quality layer on top of EIG brand compliance.
This skill asks "is this a good display of the data?"; the `eig-style-review` skill asks "is it
on-brand?", and a full figure review runs both.

Done when each display in scope has a recommended approach or a critique whose findings follow
the format below, each tied to a principle and checked against the brand non-negotiables.

## Source Priority

1. `Infrastructure/style/docs/tufte-principles.md` (data-ink, lie factor, chartjunk, small multiples, density; §9–§16 for the six analytical-design principles, sparklines, layering, range-frames, and causality)
2. `Infrastructure/style/docs/eig-figure-style.md` (brand standards that constrain the design space)
3. `Infrastructure/style/docs/_generated/tokens.md` (token values: series order, neutrals, type roles)

## EIG Reconciliation (binding)

- **Color.** The EIG brand palette governs *which* hues are allowed; Tufte governs *how
  many*. Prefer one or two series colors plus neutral gray. Do not override brand hues for
  "grayscale" — minimize the *count* of encoded colors instead. Highlight in the first series
  color against gray per `eig-figure-style.md` §1; keep `eig_gold_600` for large fills.
- **Never relax** a brand non-negotiable (source line, in-image title without a figure number,
  token colors, no vertical gridlines, no plot box) to satisfy a Tufte preference. Where they genuinely
  conflict, flag it as an open decision rather than silently choosing.

## Workflow — New Visualizations

1. **Clarify the data story.** What comparison matters? What is the key insight? Who is the audience? Infer these from the request and the draft, or ask if the session is interactive.
2. **Select approach via Tufte principles.**
   - High comparison need → small multiples (identical scales across panels)
   - Dense data → data tables, sparklines, layered display
   - Time series → line chart, minimal grid, range-frame axis
   - Part-to-whole → avoid pie charts; prefer bar or table
   - Results (regression/event study) → coefficient/event-study plot with neutral baseline, one accent color, annotated treatment moment
3. **Design with data-ink in mind.** Start minimal; every element earns its ink; default to the fewest encoded colors.
4. **Eraser test.** For every element (label, tick, gridline, border, annotation): can it be erased without losing information conveyed elsewhere? Drop duplicate encodings (numeric label next to a marked value; legend duplicating direct labels).
5. **Collision test.** For every text element, mentally draw its bounding box. Does anything cross it? Standard fixes: move prose to the figcaption; relocate epoch/band labels to a strip above the plot; push baseline labels to the margin; add leader lines.
6. **Tufte test.** Run the Quick Reference in `Infrastructure/style/docs/tufte-principles.md` and the graphical-quality items of `eig-figure-style.md` §9.
7. **Hand off implementation** to `eig-style-apply` / `eig-style-guide-agent` for token-correct R/Python/Stata code.

## Workflow — Critiquing Visualizations

1. **Graphical integrity.** Estimate the lie factor if proportions look off; verify baselines, consistent intervals, deflated money; check for 3D distortion or truncated axes.
2. **Chartjunk.** Flag decoration, heavy grids, moiré patterns, 3D effects, gratuitous icons.
3. **Data-ink ratio.** What can be erased? What is redundant?
4. **Analytical design.** Walk the six principles (comparison, causality, multivariate, integration, documentation, content). The lowest-scoring principle is the biggest opportunity.
5. **Improvements.** Give specific before/after recommendations, each tied to a principle and respecting EIG brand non-negotiables.

## Required Findings Format

For each finding:

1. Severity (`Critical`, `Medium`, `Optional`)
2. Principle invoked (e.g. data-ink, lie factor, "compared to what?", layering)
3. Evidence (the specific element or code/output location)
4. Before → after recommendation
5. EIG-compliance note (confirm the fix keeps brand non-negotiables, or flag a conflict)
