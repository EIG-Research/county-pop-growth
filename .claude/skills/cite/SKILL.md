---
name: cite
description: "Format a citation from natural-language source information using EIG citation rules. Returns the formatted citation, inferred source type, and any missing required fields. Use when a source needs an EIG-format citation."
argument-hint: "<source-description>"
allowed-tools: ["Read", "Grep", "Glob"]
---

# Workflow: cite

Format a citation from natural-language source information using EIG citation rules. It is
done when the formatted citation, its inferred source type, and any missing required fields
are returned.

## Input

Invoke as `/cite <source-description>`.

Arguments: $ARGUMENTS

The argument is the natural-language source information to format. If no argument was given,
ask for the source details in an interactive session; otherwise report the missing input and
stop.

## Steps

1. Parse authors, title, outlet, date, URL, and access date if present.
2. Infer source type (article, report, book, webpage, press release, podcast, law).
3. Apply `Infrastructure/rules/style-citation-rules.md`.
4. Return output using `Infrastructure/templates/style-citation-output.md`.

## Minimum Output

- Formatted citation
- Inferred source type
- Missing required fields (`[MISSING]`)
