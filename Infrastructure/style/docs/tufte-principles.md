# Tufte's Principles for Data Visualization

> **EIG use note.** This is the graphical-quality layer of the EIG style system, applied
> by the `eig-tufte-critique` skill and the second pass of `eig-style-review`. It
> complements, and does not replace, the brand rules in
> `Infrastructure/style/docs/eig-figure-style.md`. §1–§8 cover every figure; §9–§16 add
> analytical design for dashboards, dense displays, sparklines, small multiples, and
> results graphics (event-study plots, coefficient plots, panel data).
>
> **Where EIG and Tufte interact (binding):**
> - **Color.** EIG's brand palette governs *which* colors are allowed (see
>   `eig-figure-style.md` §1). Tufte governs *how many*: prefer one or two series colors
>   plus neutral gray; do not spend six brand colors where two plus gray carry the
>   comparison. "Grayscale by default" here means *minimize the number of encoded hues*,
>   not abandon the brand palette.
> - **Data density and sizing.** EIG's standard static figure is `sizing.figure_default`
>   (6.5 × 3.5 in; `eig-figure-style.md` §6). Small-multiple arrays and high-density
>   displays may exceed it; treat it as a default, not a ceiling, and note the exception.
>
> Adapted from Edward Tufte, *The Visual Display of Quantitative Information*,
> *Envisioning Information* (1990), *Visual Explanations* (1997), and *Beautiful Evidence*
> (2006), via the `tufte-viz-claude-code` skill (Ben Glasner Style Guide).

## 1. Graphical Excellence

Excellence in statistical graphics consists of complex ideas communicated with clarity, precision, and efficiency.

**Core qualities:**
- Show the data
- Induce the viewer to think about substance, not methodology or design
- Avoid distorting what the data have to say
- Present many numbers in a small space
- Make large datasets coherent
- Encourage eye comparison of different pieces of data
- Reveal data at several levels of detail (broad overview to fine structure)
- Serve a reasonably clear purpose
- Integrate closely with statistical and verbal descriptions

**Questions to ask:** Does the graphic show the data clearly? Does it encourage thinking about content over decoration? Can the viewer compare data elements easily?

## 2. Graphical Integrity

Graphics must tell the truth about the data.

**The Lie Factor:**
```
Lie Factor = Size of effect shown in graphic / Size of effect in data
```
- Lie Factor = 1.0: Truthful
- Lie Factor > 1.05 or < 0.95: Distortion

**Six principles of graphical integrity:**
1. Representation of numbers should be directly proportional to quantities represented
2. Clear, detailed, thorough labeling defeats distortion
3. Show data variation, not design variation
4. In time-series displays, standardize money (deflate) and use consistent baselines
5. Dimensions of graphics should not exceed dimensions of data
6. Graphics must not quote data out of context

**Common violations:** 3D effects on 2D data (a fake dimension); truncated axes that exaggerate change; inconsistent intervals; area or volume encoding of linear data; missing context or baselines.

## 3. Data-Ink Ratio

The data-ink ratio is the proportion of a graphic's ink devoted to the non-redundant display of data-information.

```
Data-Ink Ratio = Data-ink / Total ink used in graphic
```

**Maximize the data-ink ratio within reason:**
1. Erase non-data-ink (decoration, heavy grids, boxes)
2. Erase redundant data-ink (3D when 2D suffices)
3. Revise and edit

**Non-data-ink to eliminate:** heavy gridlines; unnecessary borders and boxes; redundant labels; decorative elements; excessive tick marks; 3D effects that add no information.

**The eraser test:** If you can erase something without losing data information, erase it.

## 4. Chartjunk

Chartjunk is the interior decoration of graphics that does not convey information. It comes in three kinds:

- **Unintentional optical art (moiré vibration):** busy patterns, cross-hatching that vibrates, competing visual frequencies.
- **The grid:** heavy grids compete with data. Mute or eliminate them; if needed, use light gray or dotted lines.
- **The duck (self-promoting graphics):** graphics that draw attention to their own design; decoration masquerading as information; style over substance.

**Chartjunk indicators:** the viewer notices the design before the data; colors or patterns decorate rather than encode; 3D effects, shadows, or gradients without purpose; clip art, icons, or illustrations that carry no data.

## 5. Small Multiples

Small multiples are series of graphics showing the same combination of variables, indexed by changes in another variable.

**Characteristics:** the same design structure repeated; changes in data, not design; direct visual comparison; high information density; the eye moves across variations effortlessly.

**When to use:** comparing across categories, time periods, or conditions; showing change or variation; revealing patterns across groups; when animation would work but a static display is needed.

**Design guidelines:**
- Identical scales across all panels
- Consistent visual encoding
- Minimal between-panel decoration
- Clear labeling of what varies
- Tight spacing (data should dominate)

## 6. Data Density and Information Resolution

**Data density = numbers plotted per unit area.** High data density is a sign of graphical quality. Maps and time series can achieve thousands of numbers per square inch.

**Shrink principle:** Graphics can often be reduced significantly while staying readable and gaining impact: sparklines (§10), condensed time series, small-multiple arrays.

**Resolution thinking:** What is the minimum size that remains readable? (Never below the text floor in `eig-figure-style.md` §6.) Can we show more data in the same space? Are we wasting white space?

## 7. Multifunctioning Graphical Elements

Every graphical element should serve multiple purposes when possible. A data measure can also serve as a label, a scale marker, or a grid reference.

**Examples:** data points that also serve as labels (scatter plots with text); an axis that is also a data series; range frames (§14), where the axis shows the data range, not an arbitrary extent.

## 8. Aesthetics and Technique

**Balance complexity and simplicity:** simple design, complex data. Complexity should come from data, not decoration.

**Visual hierarchy:** Data > Labels > Annotations > Grids > Borders. Prominent elements should carry the most information.

**Color use:**
- Use sparingly and purposefully
- Ensure accessibility (colorblind-safe)
- Gray as default, color for emphasis or encoding
- Avoid "rainbow" color maps for sequential data

**Typography:** clear, readable fonts; an appropriate sizing hierarchy; horizontal text when possible; labels close to the data they describe.

## 9. The Six Principles of Analytical Design

From *Beautiful Evidence*. They apply to any analytical presentation, not just charts.

1. **Show comparisons, contrasts, differences.** The fundamental analytical act. Every display should answer "compared to what?"
2. **Show causality, mechanism, structure, explanation.** Move beyond description: what is the *why* behind the pattern? A causal claim must be one the research design supports (§16).
3. **Show multivariate data: more than one or two variables.** Real problems are multivariate. Reducing to a single variable hides interactions.
4. **Completely integrate words, numbers, images, diagrams.** Do not segregate by mode. Put labels next to the data they describe and equations next to the curves they generate.
5. **Thoroughly describe the evidence.** Provenance, authorship, scales, sources, measurements. Documentation enables trust. (EIG note: this is the source and note line requirement in `eig-figure-style.md` §4.)
6. **Analytical presentations ultimately stand or fall depending on the quality, relevance, and integrity of their content.** No amount of design fixes weak evidence.

**Use in critique:** walk through all six. The lowest-scoring principle is usually the biggest improvement opportunity.

## 10. Sparklines

Word-sized, data-intense graphics, from *Beautiful Evidence*.

**Defining properties:** typographic resolution, sized like text and embedded in prose or tables; no axes, labels, or decoration; endpoints often marked (start and end values, or minimum and maximum); shape, trend, and variability readable at a glance.

**Design rules:**
- Height about the x-height of the surrounding text (about 14–20px)
- Length about a word or short phrase
- Flag one key point (the current value or an anomaly) with a single dot in one accent color from the palette
- Pair with the most recent numeric value: `120 ▁▂▃▅▇▇▆▅ 132`
- Stack in tables so the eye can scan vertically

**When to use:** dashboards with many metrics (one row per metric: name, sparkline, current value, change); inline prose ("the share trended up ▁▂▄▆▇ over the decade"); anywhere a full chart would dominate but the trend matters.

**When not to use:** when precise readings matter, because sparklines show shape, not value; for categorical or part-to-whole data.

## 11. Layering and Separation

From *Envisioning Information*. Visually distinct elements can share the same space if they are *layered*: separated by value, weight, hue, or transparency rather than by position.

- **1 + 1 = 3 effect:** two heavy lines next to each other create a phantom third line. Lighten one to suppress it.
- **Hierarchy by weight:** primary data dark and saturated; secondary data light gray; annotations lighter still.
- **Color for separation, not decoration:** distinct hues keep overlapping data readable.
- **Whisper, don't shout:** grids, axes, and reference lines fade into the background.

**Test:** squint at the graphic. The most important data should stay visible; chartjunk should disappear first.

## 12. Micro/Macro Design

Distinct from raw data density: a micro/macro graphic tells different stories at different viewing distances. The macro view (zoomed out) shows the overall pattern, shape, and trend; the micro view (close inspection) shows individual points, labels, and exceptions.

**Examples:** the Vietnam Veterans Memorial (macro: the sweep of names; micro: a single name); a table with sparklines (macro: which rows trended up; micro: the values).

**Design implication:** do not choose between overview and detail; show both at once by layering.

## 13. Escaping Flatland

The page and screen are flat; good information design adds dimensions *without* 3D gimmicks. Dimensions available on flat media: color (categorical or sequential), size (continuous), shape (categorical), position (two or three axes via projection), time (small multiples or sparkline-style inline series), and layering (foreground and background via value).

**Anti-pattern:** 3D bar charts, pie charts with depth, and isometric projections that distort proportions add visual dimension without information dimension.

## 14. Range-Frame and Dot-Dash Plot

Redesigns of standard chart elements that apply data-ink maximization.

- **Range-frame:** replace the full axis with a line spanning only the range of the data, so the axis ends at the minimum and maximum values rather than arbitrary round numbers.
- **Dot-dash plot:** a scatter plot whose axes are replaced by marginal rug plots, so each axis shows the distribution of its variable. Same ink, more information.

**Pattern:** every standard chart element (axis, tick, gridline) can be redesigned to carry data.

## 15. Confections, Parallelism, Narrative

From *Visual Explanations*.

- **Confections:** assemblages of disparate elements (images, maps, text, diagrams) into one explanatory composition, such as Minard's map of Napoleon's march or Snow's cholera map. They work when each element serves the argument.
- **Parallelism:** repeated visual structure that enables comparison. Small multiples are one form; side-by-side maps, before-and-after states, and repeated annotation styles are others.
- **Narrative graphics of space and time:** spatial and temporal dimensions in one frame. Minard's graphic encodes troop size, geography, direction, temperature, and time together.

## 16. Cause and Effect

From *Visual Explanations*. Causality is hard to show because it needs both the variables and the mechanism linking them.

**Techniques:**
- Show the intervention and the response in the same frame
- Annotate the causal mechanism directly on the data
- Use sequence (small multiples through time) to show how the effect unfolds
- Pair the data display with a process diagram of the proposed cause

**Worked example:** the Challenger O-ring decision. Plotted against temperature, the available data showed the risk, but the engineers' presentation hid the relationship; Tufte's redesign makes it plain.

**EIG note: causal framing follows the research design.** A chart may present an effect as causal only when the identification strategy supports that reading, and its annotations and title must match the claim the analysis makes. A descriptive or correlational result is shown as an association, with the note line saying so. The methodology review checks the identification strategy; the figure must not claim more than it supports. These techniques map onto EIG's regression and event-study plots (`eig-figure-style.md` §7): range-frames for coefficient axes (§14), a marked treatment moment, and small multiples through time for dynamic effects.

## Quick Reference: The Tufte Test

For any visualization, ask:

1. **Data-ink:** Can I erase any element without losing data? (Erase it)
2. **Integrity:** Does the visual effect match the data effect? (Lie factor about 1)
3. **Chartjunk:** Does any element exist for decoration only? (Remove it)
4. **Excellence:** Does it reveal the data at several levels? (Broad and detailed)
5. **Comparison:** Can the viewer easily compare data elements? (Enable it)
6. **Density:** Could this show more data in the same space? (Condense)
7. **Context:** Is all necessary context provided? (Labels, sources, scales)

For dense, dashboard, or results displays, add:

8. **Compared to what?** Does the graphic answer it?
9. **Causality:** Is the mechanism or explanation visible, not just the pattern, and does the causal reading match the research design?
10. **Multivariate:** Are interactions among variables shown, or has the problem been over-reduced?
11. **Integration:** Are words, numbers, and images interleaved, or segregated?
12. **Documentation:** Can a stranger evaluate the evidence (sources, scales, authorship)?
13. **Layering:** Do important elements dominate while secondary elements recede?
14. **Micro/macro:** Does the display reward both a glance and a close read?
