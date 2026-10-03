---
load: referenced
---

# Document Number Verification Rules

The numbers lens (`data-consistency-reviewer`, check ids `DN-*`) checks each number a document
reports against the output or data that produced it, the arithmetic that transforms it, and
its agreement with the document's other mentions. Severity, confidence, evidence, refutation,
and lens ownership follow `Infrastructure/rules/review-contract.md`; this file adds what to
extract, how to trace, the one rounding tolerance, and the failure classes.

## 1. Scope

A number is in scope when it comes from the analysis: an estimate, test statistic, p-value,
sample size, mean, share, count, date range, a table or figure value, or a figure derived from
these (a difference, ratio, or growth rate).

Out of scope: structural references (Section 3, Table 2, Column 4), citation years, page and
footnote numbers, specification labels ("Model 1"). A figure taken from an outside source (a
BLS rate, another paper's estimate) belongs to the provenance lens; note it in `context` and
leave it.

## 2. Extraction in tiers

A real paper holds more numbers than one pass can check, so extract in this order and record
what was left:

1. **Headline:** title, abstract or summary, key findings, and figure and table titles. Check
   every number.
2. **Body text:** every number in the prose, including footnotes and captions.
3. **Tables and figures:** every cell the text cites (the table-text links), the key estimate
   row of each results table, and a sample of the remaining cells, at least five per table
   spread across rows and columns. Record the unchecked cells as `Not checked` in `context`.

Format notes:

- LaTeX (`.tex`): follow `\input{}` and `\include{}`; numbers in generated table files should
  match exactly, while numbers typed into the source are likelier to be stale. Parse `\num{}`,
  `\SI{}`, `\numprint{}`, `\pgfmathprintnumber{}`, and `\newcommand` macros (such as
  `\newcommand{\nobs}{15234}`), and read `tabular`, `longtable`, and `threeparttable` cell by cell.
- Quarto and R Markdown (`.qmd`, `.Rmd`): prose is the document and chunks are code. An inline
  expression (`` `r round(x, 1)` ``) is checked by its value: read the rendered file when one
  exists, otherwise recompute the expression in `review-reports/_scratch/` from the output it
  reads. Compare its rounding with the table it restates.
- Markdown, HTML, and PDF: read the text; `.docx` is not supported (contract §1).

## 3. Tracing

Trace each number through three levels, and stop at the first that settles it:

1. **Direct output:** print and export statements (`print()`, `display()`, `cat()`, `di`,
   `esttab`, `outreg`, `stargazer`, `modelsummary`, and similar), file-writing operations, and
   generated files (`.csv`, `.tex`, `.log`, `.html`, `.rtf`, `.txt`). Quote the output line.
2. **Computation:** the assignment, summary call, or model object that produces it.
3. **Data:** recompute it from the data with a script in `review-reports/_scratch/`.

## 4. The rounding tolerance

One rule decides whether a number matches its source: **the source, rounded to the precision
the document shows, equals the document's number.** Precision is the last digit shown: 4.2
matches 4.2349 and 0.04217 shown as 4.2 percent; $18.23 does not match 18.32. A number the text
marks as approximate ("about 40,000", "roughly half") is held to its stated precision, so about
40,000 matches 40,321. Counts and sample sizes match exactly unless the text rounds them.
Formatting (40,321 or 40.3 thousand) and unit changes (0.042 as 4.2 percent) are not
differences. `Infrastructure/rules/reproduce-published-results.md` applies the same rule.

## 5. Failure classes

**DN-VALUE: a number differs from its source beyond the tolerance.** HIGH for a reported
result (an estimate, mean, share, or growth rate); MEDIUM for a sample size or other count;
CRITICAL when the corrected number changes a conclusion (sign, significance, or the direction
of a comparison). Don't flag when a later output or a different specification the text names
produces the number; say which.

**DN-ARITH: arithmetic or a transformation is wrong.** A difference, ratio, or growth rate that
does not follow from its inputs; log points read as percent (a coefficient of -0.19 is a
change of exp(-0.19) - 1, about -17 percent, not -19); a proportion written as a percentage
twice. MEDIUM; HIGH when the error is more than a fifth of the reported value. Don't flag the
log-point approximation for coefficients under 0.10 in absolute value when the text calls it
approximate.

**DN-ROUND: rounding inconsistent between mentions.** The same value rounded differently in two
places, or rounded against the tolerance in the last digit only. LOW. Don't flag different
precision in a table and in the text when each rounds correctly.

**DN-INTERNAL: the document disagrees with itself.** Text against its table, abstract against
body, or two tables that should share a sample size. HIGH for a headline number, MEDIUM
otherwise. When one side also differs from the output, report DN-VALUE and relate the two.

**DN-TRACE: a number with no source.** A result the document reports that no output, code, or
recomputation produces. MEDIUM for a headline or key result, because a reader cannot reproduce
it; otherwise a Question. Don't flag a number the text attributes to an outside source.

Significance claims ("significant at 5 percent") are DN-VALUE when the p-value or interval
contradicts them; wording that overstates a correct number belongs to the consistency lens.

## 6. Findings

Findings follow `Infrastructure/rules/review-contract.md` and the findings schema (lens `DN`);
the renderer owns IDs, order, counts, risk, and the HTML. Quote the document sentence or table
cell with the number, and the output line or code it was checked against. Record the tally in
`context`: `Numbers extracted`, `Verified`, `Flagged`, and `Not checked` (with why, such as
table cells outside the sample). A number that matches needs no finding, but every extracted
number gets a row in the inventory at `review-reports/_scratch/number-inventory.csv`: document
location, claimed value, source (file and line, or "not found"), source value, and status
(verified, mismatch, untraced, approximate). The inventory is the audit trail for the tally;
the findings carry only the numbers that fail.

Example arithmetic, checked by a local run (Python `math.exp`): exp(-0.19) - 1 = -0.173;
exp(-0.1879) - 1 = -0.171; exp(0.10) - 1 = 0.105; 0.04217 as a percent to one decimal is 4.2.
