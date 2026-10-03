# EIG Brand Guidelines

Logo, typography, color, photography, and illustration rules for EIG materials, taken from the 2022 guide (`Infrastructure/style/sources/2022 Style Guide.pdf`, last updated June 10, 2022). A rule the guide does not state is labeled "template practice". Figures and tables follow `Infrastructure/style/docs/eig-figure-style.md`.

---

## 1. Logo

### Versions

The guide approves three versions. The files are in `Infrastructure/style/assets/logo/eig/`, inventoried in `Infrastructure/style/assets/logo/README.md`.

| Version (2022 guide) | Files | Use |
|---|---|---|
| Full Color | `EIG_fullcolor.*` | Most uses, across digital, print, and video. |
| One-Color Reversed | `EIG_reverse.*` | Only when one-color printing needs a solid white logo against a darker, contrasting color. |
| One-Color Black | `EIG_blackandwhite.*` | Only when one-color printing is required, for specialty items such as T-shirts or mugs. |

- In the full-color logo the icon is `eig_tan_500` and the wordmark is the near-black of the vector masters, which is not a palette token. Use the files; do not rebuild the logo from type or recolor it.
- Do not place the logo in front of colors or photos that make the mark or type hard to read.
- Formats (template practice): SVG for the web, PNG (the `@2x` files on high-DPI screens) for slides, documents, and email, and EPS or the CMYK JPG for print. The Illustrator masters in `ai/` are for the brand designer only.

### Incorrect usage

The guide lists these as incorrect. Never:

1. rotate the logo;
2. distort or warp it in any way;
3. change its colors;
4. change its typeface;
5. move the position of its parts;
6. add special effects;
7. display it with limited legibility;
8. display it as an outline;
9. rearrange its elements.

The guide sets no clear-space or minimum-size rule.

---

## 2. Typography

| Family | Role in the 2022 guide | Weights shown |
|---|---|---|
| Source Serif Pro | Primary font for headlines | Bold, Semibold |
| Open Sans | Body copy (the page's text calls it the primary font "for headlines and subheads") | Bold, Regular, Semibold, Condensed Light |

- Title case is encouraged for headlines in print, video, and social content. All caps may be used for stylized treatments in unique cases, such as infographics or annual reports.
- Source Serif 4 is the current release of Source Serif Pro, and the tokens accept it as primary (`typography.headline.accept_as_primary`). Fallback stacks and figure type sizes are tokens: [font families](_generated/tokens.md#font-families) and [type roles](_generated/tokens.md#type-roles).
- Install the families with `Infrastructure/style/scripts/fonts/README.md`.

### The 2020 lineage

The 2020 guide specified Galaxie Polaris (charts/tables) and Tiempos Text (report body). For figures and tables the 2022 lineage supersedes it (D3). Whether it still governs other EIG materials awaits the owner.

D3 is the owner decision recorded in the 2026-09-29 Phase 3C style plan (a project record under records/plans in the template repository; `make template-reset` removes it from derived projects). The 2020 families stay in the tokens as `typography.legacy_families`, with their 2020 scope, and the themes never select them. Their licensed font files and the rules for using them are in `Infrastructure/style/assets/fonts/INSTALL.md`.

---

## 3. Color

The palette is the 2022 guide's eleven colors plus black and white. The hex, RGB, CMYK, and PMS values are tokens, listed in [brand palette](_generated/tokens.md#brand-palette); cite a color by its token ID, never by a typed value.

- The guide lists no neutrals besides black and white. The grays the themes use are `provisional` tokens ([neutrals](_generated/tokens.md#neutrals)).
- Order, highlighting, and accessibility rules for charts are in `Infrastructure/style/docs/eig-figure-style.md` §1.
- Text meets WCAG AA contrast against its background: 4.5:1 for normal text, 3:1 for large text (template practice).

---

## 4. Photography

The 2022 guide asks for photography that is:

- authentic and natural, and that evokes emotion;
- set in natural environments with warm colors, for friendliness and approachability;
- a captured moment rather than an overly staged or set-up scene;
- diverse in ethnicity, gender, and age.

Template practice: license every image for EIG's use, record the license in the project files, and credit the photographer where the license requires it.

---

## 5. Illustration

The 2022 guide allows custom illustration in modern styles for analysis and other materials. Illustrations help express complex topics, reinforce key messages, and show diversity in ways photography and iconography cannot.

Template practice:

- Use palette colors only, by token ID.
- Do not convey information by color alone; add labels, patterns, or annotations.
- An infographic follows the figure rules in `Infrastructure/style/docs/eig-figure-style.md`: a sentence-case title and a source line.
- Export as SVG where possible.

The guide's overview also lists "Icons & Elements" but gives no rules for them.

---

## 6. Sub-brand: Agglomerations

Agglomerations is an EIG sub-brand with its own logo files in `Infrastructure/style/assets/logo/agglomerations/`, listed in `Infrastructure/style/assets/logo/README.md`. The 2022 guide does not cover it.

- Use its logo only on Agglomerations materials. Do not substitute it for the EIG logo, or combine the two, without design approval (template practice).
- The EIG logo's incorrect-usage list (§1) applies to it too (template practice).
