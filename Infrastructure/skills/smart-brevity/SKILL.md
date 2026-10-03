---
name: smart-brevity
description: >-
  Critiques a passage against Smart Brevity form (lede, why it matters, bullets, cuts) under EIG
  writing rules, and returns what the author should change, sentence by sentence, without
  rewriting it. Use when an author is tightening their own blog post, newsletter item, social
  post, or press release; for report prose it critiques sentence-level tightening only.
argument-hint: "<text>"
allowed-tools: [Read, Grep, Glob]
---

# Workflow: smart-brevity

Show an author where their passage falls short of Smart Brevity and what each fix must do, so
they can tighten it themselves. The workflow writes no replacement text, because EIG policy
keeps AI from drafting any part of a work product (`Infrastructure/rules/ai-use-disclosure-rules.md`).

Done when the reply holds the critique in the shape of
`Infrastructure/templates/smart-brevity-output.md`, names the document type assumed, and
contains no composed headline, lede, sentence, or bullet.

## Input

The argument is the text to critique, or a path to a file containing it. If none was given, ask
which passage to critique when the session is interactive; otherwise report the missing input to
the caller.

## Scope

Smart Brevity structure is for external communications: blog posts, newsletter items, social
posts, and press releases (`Infrastructure/style/docs/eig-writing-style.md` §7). For a passage
from a research report, policy brief, fact sheet, or data explainer, critique only the cutting
and sentence-level steps, leave out the structure checks, and say so in the reply.

## Steps

1. Identify the document type, and quote the sentence that carries the core finding or news
   angle, or say that no sentence does.
2. For external communications, check the structure: is there a headline, a one-sentence lede,
   an explicit `Why it matters` sentence, and bullets for lists of three or more? For each one
   missing or weak, say what it must do (for example, "the lede should state the finding in
   paragraph 3 in one sentence"); the author writes it.
3. Mark each sentence to cut because it restates another, each passive or weak-verb sentence,
   and each break of `Infrastructure/rules/style-writing-rules.md`. Suggest a word or
   short-phrase swap where one fixes it; otherwise describe the change.
4. Report the word count and the words the marked cuts would remove.
5. Return the critique using `Infrastructure/templates/smart-brevity-output.md`, and remind
   the author to log this editing feedback in `records/ai-use-log.md`.
