---
name: review-style
description: "Audits a whole document or a passage against EIG writing and citation style, section by section, and returns one merged issue list with a suggested fix for every error (a word swap or a described change; it never rewrites the prose). Use when checking prose, citations, or a draft's figure captions for EIG compliance; for figure and table content or plotting code, use the eig-style-review skill."
argument-hint: "<file-path-or-text>"
allowed-tools: ["Read", "Grep", "Glob", "Agent"]
---

# Workflow: review-style

Audit a document or passage against EIG writing and citation style, covering all of it.

Done when every section of the input has been reviewed at line level and the merged report, in
the shape of `Infrastructure/templates/style-review-report.md`, lists each issue once with all
its locations and gives a suggested fix for every `ERROR`. A fix is a word or short-phrase
swap or a described change, never a composed sentence, because EIG policy keeps AI from
drafting any part of a work product (`Infrastructure/rules/ai-use-disclosure-rules.md`).

## Input

Invoke as `/review-style <file-path-or-text>`.

Arguments: $ARGUMENTS

The argument is a file path or the passage itself. If none was given, ask which document to
review when the session is interactive; otherwise report the missing input to the caller.

## Steps

1. Read the input. Split a file into sections by its headings, or into blocks of about 1,000
   words when it has none.
2. Review every section with the scope and procedure in `Infrastructure/agents/eig-reviewer.md`,
   one section at a time, so long documents get the same line-level review as short ones.
   - For a document over about 3,000 words, you may spawn the `eig-reviewer` agent once per
     section or group of short sections, passing the document type, and merge what it returns.
3. Merge the section lists: report a pattern that recurs across sections once, with all its
   locations, and keep document order.
4. If the document holds figures, tables drawn as images, or plotting code, say so in the
   summary and name the `eig-style-review` skill as the next step, because this workflow does
   not review figure content.
5. Format the result with `Infrastructure/templates/style-review-report.md`, and note that
   the author applies the fixes and logs this editing feedback in `records/ai-use-log.md`.
