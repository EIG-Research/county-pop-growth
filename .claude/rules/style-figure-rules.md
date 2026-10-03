---
paths:
  - "code/**"
  - "output/**"
  - "Infrastructure/style/**"
---

# Style Figure Rules

Binding rules for EIG figure and chart styling.

## Canonical Sources

- `Infrastructure/style/docs/eig-figure-style.md`
- `Infrastructure/style/docs/eig-brand-guidelines.md`
- `Infrastructure/style/tokens/eig-style-tokens.v1.json`
- `Infrastructure/style/docs/tufte-principles.md` (graphical-quality layer; §9–§16 for dense and results displays)

## Requirements

### Brand compliance

1. Use token-derived colors only.
2. Keep 2022 primary palette as default for new outputs.
3. Put the title inside the image, top-left, in sentence case, with no `Figure N.` prefix; the document supplies the number (`eig-figure-style.md` §3).
4. Include source line: `Source: [Organization], [Year].`
5. Use horizontal gridlines only where needed; avoid vertical gridlines by default.
6. Avoid boxed plot borders unless explicitly requested.
7. Use approved typography and fallback stacks from style docs/assets.

### Graphical quality

8. Maintain graphical integrity: lie factor ≈ 1 (no truncated/exaggerating axes, no 3D on
   2D data, deflated money and consistent baselines in time series).
9. Maximize data-ink: erase any element that can be removed without losing information
   conveyed elsewhere (eraser test).
10. No chartjunk and no text collisions: decoration-free, and no label crowding data or
    other text (collision test).
11. Minimize encoded colors: prefer one or two series colors plus neutral gray within the
    EIG palette. The palette governs *which* colors; this rule governs *how many*.
12. Where a graphical-quality preference conflicts with a brand non-negotiable (1–7), keep
    the brand rule and flag the conflict as an open decision — do not silently override.

## Legacy Palette

Legacy semantic palettes are allowed only under documented exception policy:
- `Infrastructure/style/docs/eig-legacy-palette-policy.md`
