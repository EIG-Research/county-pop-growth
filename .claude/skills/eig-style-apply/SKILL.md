---
name: eig-style-apply
description: "Applies the EIG themes and token colors to existing figure and table code in R, Python, or Stata once the chart design is settled. Use when adding or updating styling in project plotting code; settle a new design with eig-tufte-critique first, and use the eig-style-guide-agent to build a figure from scratch."
argument-hint: "[target files or output type]"
allowed-tools: ["Read", "Grep", "Glob", "Bash(python3 Infrastructure/style/scripts/fonts/check-fonts.py *)", "Bash(Rscript Infrastructure/style/scripts/fonts/check-fonts.R *)"]
---

# EIG Style Apply

Style existing plotting code with the vendored EIG themes, so colors, fonts, and table rules
come from the tokens rather than from literals in the code.

Done when the target code loads its language's theme, styles through the theme helpers, holds
no color literal outside the tokens, and the reply names the files changed and the command
that renders them.

## Sources

1. `Infrastructure/style/themes/README.md`: per-language quickstarts.
2. `Infrastructure/style/docs/eig-figure-style.md`: the spec; §8 lists each language's helpers.
3. `Infrastructure/style/docs/_generated/tokens.md`: token values.
4. `Infrastructure/style/docs/eig-legacy-palette-policy.md`: only when a legacy palette is in use.

## Workflow

1. If the design is not settled (the approach, how many colors, what comparison), resolve it
   first with the `eig-tufte-critique` skill; this skill styles a chosen design.
2. Detect the language from the files or the request.
3. Load the theme:
   - R: `source("Infrastructure/style/themes/r/eig_theme.R")`
   - Python: import the helpers in `Infrastructure/style/themes/python/eig_theme.py`
   - Stata: `do Infrastructure/style/themes/stata/eig_theme.do`
4. Replace hand-set colors, fonts, and sizes with the theme helpers and token IDs. A needed
   color with no token is an open decision to report, not a new hex value.
5. If fonts may be missing, run the checker for the language:
   - `Rscript Infrastructure/style/scripts/fonts/check-fonts.R`
   - `python3 Infrastructure/style/scripts/fonts/check-fonts.py`
   - `do Infrastructure/style/scripts/fonts/check-fonts.do`

## Constraints

- Leave `Infrastructure/style/tokens/eig-style-tokens.v1.json` unchanged unless the owner asks,
  because the themes are generated from it.
- Default to the 2022 primary palette; a legacy palette needs the policy's metadata.
