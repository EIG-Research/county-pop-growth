---
name: eig-style-review
description: "Read-only audit of figures, charts, tables, and the code that draws them: brand compliance against the EIG figure spec and tokens, then graphical quality, with a fix for each finding. Use when checking a figure or table before publication, or when a prose review hands off figure content; to change the code, hand the findings to the eig-style-guide-agent."
argument-hint: "[target files or outputs]"
allowed-tools: ["Read", "Grep", "Glob"]
---

# EIG Style Review

Audit figures and tables, and the code that draws them, for EIG brand compliance and graphical
quality, without editing them.

Done when every figure or table in scope has both passes recorded, and each finding has a
severity, evidence (path plus the element or line), the risk, a fix, and a verification step.

## Sources

1. `Infrastructure/style/docs/eig-figure-style.md`: the spec; its §9 checklist is Pass 1's list.
2. `Infrastructure/style/docs/_generated/tokens.md`: token values.
3. `Infrastructure/style/themes/README.md`: which helper the code should call.
4. `Infrastructure/style/docs/eig-legacy-palette-policy.md`: only when a legacy palette appears.
5. `Infrastructure/style/docs/tufte-principles.md`: Pass 2; §9–§16 for dense and results displays.

## Pass 1: brand compliance

1. Identify each artifact: rendered figure, table, dashboard, or code. From code alone you
   cannot confirm rendered text sizes or collisions, so say which checks need a render.
2. Walk the spec §9 brand checklist. For code, confirm it loads the theme and styles through
   its helpers, and that each color literal matches a token in `_generated/tokens.md`.
3. Confirm a legacy palette carries the metadata the policy requires.

## Pass 2: graphical quality

4. Check lie factor about 1, the eraser and collision tests, "compared to what?", and data
   density.
5. Check for the fewest encoded colors within the palette. Flag a conflict between a Tufte
   preference and a brand rule as an open decision; do not resolve it silently.
6. For ideation or a standalone design critique, hand off to the `eig-tufte-critique` skill.

Do not flag: a figure larger than `sizing.figure_default` when it is a small-multiple or dense
display with the reason noted; a font fallback the theme warned about and the author noted; or
hex values inside the generated theme files, which `make style-tokens-check` already covers.

## Findings format

1. Severity (`Critical`, `Medium`, `Optional`)
2. Evidence (path plus the element or line)
3. Risk
4. Recommended fix
5. Verification step
