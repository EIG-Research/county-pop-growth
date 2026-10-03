---
name: cover-sheet
description: >-
  Generate an EIG publication cover sheet from a project description. Fills known factual fields, leaves the thesis and title to the author, and marks unresolved items as [TO FILL]. Use when starting an EIG publication that needs its cover sheet.
---

# Workflow: cover-sheet

Generate an EIG publication cover sheet from project description text. It is done when the
cover sheet, in the shape of `Infrastructure/templates/style-cover-sheet.md`, is returned with
every unresolved field marked `[TO FILL]` and the open pre-draft questions listed.

## Input

Mention `$cover-sheet` with the details in the same message, pick the skill by name, or simply describe the task. Treat the invoking message as this workflow input.

The argument is the project description to build the cover sheet from. If no argument was
given, use `PROJECT.md` as the description source.

## Steps

1. Extract known fields from the input.
2. Infer defaults only for factual fields (dates, status, data sources, scope, people named in
   the input). Leave the working title and `Core Finding / Thesis` as `[TO FILL]` for the
   author unless the input states them, because the cover sheet goes to internal reviewers and
   EIG policy keeps AI from writing a work product's prose
   (`Infrastructure/rules/ai-use-disclosure-rules.md`).
3. Fill `AI Use Disclosure` from `records/ai-use-log.md` when it exists.
4. Mark unresolved fields as `[TO FILL]`.
5. Use `Infrastructure/templates/style-cover-sheet.md` for output.
6. List unresolved pre-draft questions and immediate next steps.

## Reference

- `Infrastructure/style/docs/eig-document-process.md`
