# EIG Font Installation Guide

EIG's **primary** typefaces are **Open Sans** (body / UI text) and **Source Serif Pro** (headlines and serif display). These are open-source families, installed by the install scripts (Source Serif 4 for the headline family) — they are *not* in this directory. Use them for all new EIG-branded figures and documents.

The font files bundled in this directory (`Infrastructure/style/assets/fonts/`) are the **legacy / comparability** families — **Galaxie Polaris** and **Tiempos** — the proprietary typefaces used in EIG outputs through 2020. They are bundled here precisely because they are proprietary and cannot be auto-downloaded by the install scripts. Load them only when you need to reproduce or visually compare against legacy EIG material, and only under the documented exception policy.

The token source of truth for all of this is `Infrastructure/style/tokens/eig-style-tokens.v1.json` (`typography.headline.primary_family` = Source Serif Pro, `typography.body.primary_family` = Open Sans, `typography.legacy_families` = Galaxie Polaris + Tiempos Text). The legacy-palette / legacy-typeface exception policy is in `Infrastructure/style/docs/eig-legacy-palette-policy.md`.

---

## Primary families — install these first

The scripts in `Infrastructure/style/scripts/fonts/` install Open Sans and Source Serif 4, the current release of Source Serif Pro, which the tokens accept as primary (`typography.headline.accept_as_primary`). `Infrastructure/style/scripts/fonts/README.md` gives the commands for each platform and the checks to run afterwards; the download URLs and checksums for all three installers are in `Infrastructure/style/scripts/fonts/font-sources.tsv`.

The token file owns the fallback order for each role (`typography.headline.fallback_stack` and `typography.body.fallback_stack`); `Infrastructure/style/docs/_generated/tokens.md` lists it.

The rest of this document covers the **legacy** families bundled in this directory.

---

## Legacy font inventory (bundled here)

| File | Family | Weight / Style | Legacy use |
|------|--------|----------------|------------|
| `TiemposText-Regular.otf` | Tiempos Text | Regular | Body text, report prose |
| `TiemposText-RegularItalic.otf` | Tiempos Text | Regular Italic | Emphasis, source lines |
| `TiemposText-Semibold.otf` | Tiempos Text | Semibold | Subheadings, chart titles |
| `TiemposHeadline-RegularItalic.otf` | Tiempos Headline | Regular Italic | Large display headlines |
| `TiemposHeadline-LightItalic.otf` | Tiempos Headline | Light Italic | Large display headlines (light variant) |
| `GalaxiePolaris-Bold.otf` | Galaxie Polaris | Bold | Strong callouts, labels |
| `GalaxiePolaris-Book.otf` | Galaxie Polaris | Book | Axis labels, captions, UI text |
| `GalaxiePolaris-Light.otf` | Galaxie Polaris | Light | Source lines, footnotes, secondary text |

**Font suppliers:**
- Tiempos — Klim Type Foundry (klim.co.nz)
- Galaxie Polaris — Chester Jenkins / Village Type Foundry (vllg.com)

These are licensed, proprietary fonts. Do not redistribute outside EIG.

---

## Loading the bundled legacy fonts by tool

> Use these only when a task requires the legacy families. New EIG outputs default to Open Sans + Source Serif Pro (see above).

### Windows OS (Required for Stata and some R/Python workflows)

1. Select all `.otf` files in this directory.
2. Right-click → **Install for all users** (preferred) or **Install** (current user only).
3. Fonts will be available by their internal names:
   - `Tiempos Text` (Regular, Italic, Semibold)
   - `Tiempos Headline` (variants appear as separate style entries)
   - `Galaxie Polaris` (Bold, Book, Light appear as separate weights)

---

### R — systemfonts (Recommended)

The `systemfonts` package allows loading fonts from a path without OS installation. This is the preferred method for reproducibly loading the bundled legacy families in R projects.

```r
library(systemfonts)

# Register the bundled legacy EIG fonts from the assets directory
# Run once per R session (or add to .Rprofile for persistence)

eig_font_path <- here::here("Infrastructure/style/assets/fonts")  # adjust path as needed

systemfonts::register_font(
  name   = "Tiempos Text",
  plain  = file.path(eig_font_path, "TiemposText-Regular.otf"),
  italic = file.path(eig_font_path, "TiemposText-RegularItalic.otf"),
  bold   = file.path(eig_font_path, "TiemposText-Semibold.otf")
)

systemfonts::register_font(
  name  = "Tiempos Headline",
  plain = file.path(eig_font_path, "TiemposHeadline-RegularItalic.otf"),
  bold  = file.path(eig_font_path, "TiemposHeadline-LightItalic.otf")
)

systemfonts::register_font(
  name   = "Galaxie Polaris",
  plain  = file.path(eig_font_path, "GalaxiePolaris-Book.otf"),
  bold   = file.path(eig_font_path, "GalaxiePolaris-Bold.otf"),
  italic = file.path(eig_font_path, "GalaxiePolaris-Book.otf")  # no true italic; Book is used
)
```

After registering, pass the name to `theme_eig()`:
```r
theme_eig(base_family = "Galaxie Polaris")
```

**Saving figures with custom fonts:** Use `ragg::agg_png()` or `svglite::svglite()` as the graphics device — both honor systemfonts registrations. The default `png()` device does not.

```r
ragg::agg_png("figure1.png", width = 8, height = 5, units = "in", res = 300)
# ... ggplot code ...
dev.off()
```

---

### R — extrafont (Alternative)

```r
library(extrafont)
font_import(paths = here::here("Infrastructure/style/assets/fonts"), prompt = FALSE)
loadfonts(device = "win")   # Windows; use device = "pdf" for PDF output
```

After import, use family names: `"Tiempos Text"`, `"Galaxie Polaris"`.

---

### Python — Matplotlib

Matplotlib can load fonts directly from a path without OS installation.

```python
import matplotlib.font_manager as fm
from pathlib import Path

# Add the bundled legacy EIG fonts to the Matplotlib font manager
font_dir = Path("Infrastructure/style/assets/fonts")   # adjust path as needed
for f in font_dir.glob("*.otf"):
    fm.fontManager.addfont(str(f))

# Verify they loaded
eig_fonts = [f.name for f in fm.fontManager.ttflist if "Tiempos" in f.name or "Galaxie" in f.name]
print(eig_fonts)

# Then set in rcParams:
import matplotlib as mpl
mpl.rcParams["font.family"] = "Galaxie Polaris"
```

**Note:** After calling `addfont()`, set the family name to exactly what appears in the font's metadata (as shown by the `print(eig_fonts)` step above). Common values: `"Galaxie Polaris"`, `"Tiempos Text"`.

**Clearing the cache:** If fonts do not appear after adding them, delete Matplotlib's font cache:
```python
import matplotlib.font_manager as fm
import os
os.remove(fm.get_cachedir() + "/fontlist-*.json")
# Then restart Python
```

---

### Python — Plotly

Plotly renders fonts in the browser (for HTML) or via Kaleido (for PNG/PDF export). For web output, fonts must be available via CSS or embedded. For static export:

1. Install the fonts at the OS level (see Windows section above), **or**
2. Use a fallback font (Plotly will use whatever is installed):
   ```python
   # If the legacy family is not installed, the configured fallback is used
   # automatically, e.g. "Galaxie Polaris, Arial, sans-serif".
   ```

For Plotly web embeds, add the font via CSS:
```css
@font-face {
  font-family: 'Galaxie Polaris';
  src: url('/Infrastructure/style/assets/fonts/GalaxiePolaris-Book.otf') format('opentype');
  font-weight: normal;
}
```

---

### Stata

Stata requires fonts to be installed at the OS level.

1. Install via Windows font manager (see Windows section above).
2. Set the font with:
   ```stata
   graph set window fontface "Galaxie Polaris Book"
   ```
3. If the legacy family is not installed, Stata falls back to the default sans-serif. Wrap the call in `capture` to handle this gracefully.

---

## Fallback Strategy (legacy families)

When the bundled legacy fonts are unavailable, use these substitutes:

| Legacy font | Best fallback | Second fallback |
|-------------|---------------|-----------------|
| Tiempos Text | Georgia | Times New Roman |
| Tiempos Headline | Georgia Italic | — |
| Galaxie Polaris | Arial | DejaVu Sans (Python) / sans (R) |

For new (non-legacy) outputs, use the primary families and their fallback stacks listed at the top of this document.
