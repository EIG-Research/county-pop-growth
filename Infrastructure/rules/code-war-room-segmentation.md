---
load: referenced
---

# Code War Room Segmentation Algorithm

The block boundaries `Infrastructure/scripts/war_room_prep.py` produces (WR-S2), stated so a
human can predict where they fall without running anything. It is maintainer reference: a
war-room session does not read it, because the script segments and an agent never does. The
shared war-room library (`Infrastructure/scripts/war_room_lib.py`) states the same steps in its
module docstring, and `Infrastructure/scripts/test_war_room.py` fails if the two differ.

```
1. Read the file as UTF-8 and split it into lines, discarding the line terminators (both
   CRLF and LF), exactly as WR-A1 step 2 does. Lines are numbered from 1.

2. Detect the dialect from the file extension: `.R` -> R, `.Rmd` -> Rmd, `.qmd` -> qmd,
   `.py` -> Python, `.do` and `.ado` -> Stata. The ledger's `script.language` records `R`
   for all three R dialects, and `Python` or `Stata` for the others.

3. Classify every line as BLANK, COMMENT, FENCE, or CODE. Read the file top to bottom,
   carrying an open string literal from one line to the next: in R, Rmd and qmd a string
   opened by `"`, `'` or a backtick stays open until the same unescaped character closes
   it, even on a later line; in Python only a triple-quoted string (`"""` or `'''`) stays
   open past the end of its line; in Stata no string does, but a `/* */` block comment
   stays open until its first `*/`, and a `*` or `//` comment line opens none.
   - BLANK: the line contains only whitespace.
   - FENCE: Rmd and qmd only -- the first non-whitespace characters are three backticks.
     A fence toggles chunk state; the first one encountered opens a chunk, the next
     closes it. A fence also closes any open string.
   - COMMENT: R, Rmd, qmd and Python -- the first non-whitespace character is `#`.
     Stata -- the first non-whitespace characters are `*` or `//`, or nothing but
     whitespace is left once `/* */` comment text and a trailing `//` comment are
     removed. In Rmd and qmd, only lines inside a chunk can be comments; outside a chunk
     every non-blank, non-fence line is Markdown prose, counts as CODE, and carries no
     bracket, string, or continuation.
   - CODE: everything else, including a line that begins inside an open string.

4. PARAGRAPHS (WR-S7). Cut the file into paragraphs at every run of blank lines, except
   a run inside an OPEN CONSTRUCT, which stays inside its paragraph. The run is inside an
   open construct when, after the last non-blank line above it:
   a. the bracket depth of step 7 is greater than zero, or a string is open;
   b. Python -- the first non-blank line below the run is indented, because an indented
      line continues the compound statement above it;
   c. Stata -- a `/* */` comment is open; or a `preserve` has not been closed by a
      `restore` (one whose options include `preserve` keeps it open) or by a program's
      `end`; or a `#delimit ;` has not been followed by `#delimit cr`. The prefixes
      `capture`, `quietly` and `noisily` (`cap`, `qui`, `noi`) are skipped, and
      `#delimit` may be abbreviated down to `#d`.
   Blank lines between paragraphs belong to no block, every block lies inside one
   paragraph, and the bracket depth restarts at zero at the start of every paragraph and
   at every fence.

5. FILE HEADER, the WR-S6 exception. If the first paragraph starts at line 1 and every one
   of its non-blank lines is a COMMENT, that paragraph is a block on its own: a header
   documents the whole script, not the code under it. Any other paragraph made only of
   comments -- a trailing note with no code below it, for example -- is also a block of
   its own, because there is nothing for it to attach to.

6. Inside a paragraph, a CUT POINT opens a new block immediately before a non-blank line
   i, never before the paragraph's first line, when step 7 permits a cut there and line i
   opens a new unit. Here and in step 7, line i-1 is the nearest non-blank line above
   line i. Line i opens a new unit when one of the following holds, tested in this order:
   a. SECTION HEADER -- line i is a COMMENT whose text, after the comment token is
      removed, contains three or more consecutive `-` or `=` characters; or it is a Python
      cell marker (`#`, then optional spaces, then `%%`); or it is an opening FENCE in Rmd
      or qmd.
   b. DEFINITION START -- R, Rmd, qmd: `name <- function(` or `name = function(`, or a
      bare `function(`. Python: the first non-whitespace text is `def`, `class`, or `@`.
      A Python `def` or `class` whose immediately preceding line in the same paragraph is
      a decorator line (first non-whitespace character `@`) does not open a unit, so a
      decorator run and the definition it decorates are never split (WR-S3).
      Stata: `program define`, `program drop`, or `program` followed by a name.
   c. DEFINITION END -- the current block's first CODE line was a DEFINITION START and
      that definition closed on line i-1. A definition closed when the bracket depth,
      having risen above zero since the definition opened, returned to zero; or, in Stata,
      when line i-1's first token is `end`; or, in Python, when the definition started at
      indentation zero and line i is itself at indentation zero.
   This ordering is WR-S2's priority list -- section header, definition, complete chain,
   statement run -- with "complete chain" and "statement run" expressed by step 7 instead
   of by a cut of their own: a chain is never cut because step 7 forbids it, and a run of
   plain statements yields no cut at all, so the run is one block.

7. NO CUT is permitted before line i when any of these holds. This is WR-S3: an atomic
   operation is never split.
   - The running bracket depth after line i-1 is not zero. Depth counts `(`, `[` and `{`
     as +1 and `)`, `]` and `}` as -1, ignoring anything inside a string literal or after
     a comment token. Stata's single quote is a macro delimiter, not a string delimiter,
     and is ignored.
   - A string, or a construct of step 4c, is still open after line i-1: a Stata
     `preserve`/`restore` pair, block comment, or `#delimit ;` region is never cut.
   - Line i-1, with any trailing comment removed, ends with a continuation token: `%>%`,
     `|>`, `+`, `,`, a backslash, `&`, `&&`, `|`, `||`, `~`, `=`, `<-`, or Stata's `///`.
   - Line i is inside an Rmd or qmd chunk, or is a chunk's closing fence.

8. ANCHOR (WR-S6). Once the cut points are chosen, every cut opened by rule 6b or 6c is
   moved UP past the maximal run of COMMENT lines immediately preceding it within the same
   paragraph and, in Python, past the maximal run of decorator lines (first non-whitespace
   character `@`) immediately preceding the definition, then past any comment run above
   those, so a leading comment and a decorator run attach to the code below them rather
   than forming a block of their own. A blank line ends each run. A cut opened by rule 6a
   is not moved, because it already sits on the comment that introduces its block. A cut
   is never moved above the paragraph's first line; if it would be, it is dropped. Cuts
   that coincide after anchoring collapse into one.

9. Blocks are emitted in file order and numbered `b001`, `b002`, ... Ids are assigned once
   and are never renumbered, including after a later merge or split. A block's range ends
   on its last non-blank line. Every non-blank line lies in exactly one block, and a blank
   line lies in a block only when it is inside one (WR-S7).
```

The result is a function of the file's bytes alone: the same file segments the same way on
every run, on every platform, and for every reviewer. That is the property the multi-reviewer
model in WR-O6 depends on — two reviewers who segment differently produce two disjoint block
sets instead of the intended conflict on one `block_id`.
