# Rolling back the Phase 3C owner-judgment defaults

Each default from the 2026-09-29 Phase 3C style plan's owner-judgment table (a project record under records/plans in the template repository) landed in its own commit so the owner can reverse it. This file says how, per item. SHAs are the ones merged from `feat/p3c-batch1`; if they differ, find the commit by its subject with `git log --oneline -- Infrastructure/style`.

Every recipe ends the same way:

```bash
python3 Infrastructure/style/scripts/sync_tokens.py --write   # regenerate every output
make style-tokens-check                                        # generated files match
python3 Infrastructure/scripts/test_style.py                   # suite passes
```

## Plain reverts

These revert cleanly on their own.

| Item | Commit | Subject | After `git revert <sha>` |
|---|---|---|---|
| 1 Titles in the image | `138e4ea` | keep R figure titles in the image, flush left with the plot | Nothing more; the revert removes its test too. |
| 3 Legacy font families | `3a5aab7` | scope the 2020 legacy font families | Run `sync_tokens.py --write`: the revert leaves `docs/_generated/tokens.md` stale. |
| 6 Stata scheme | `f42de22` | generate a Stata graph scheme from the tokens | Nothing more; the revert removes the scheme, its output entry, and its test. |

## Data rollbacks

These commits also added code that later commits build on: sync validation, generator output, and theme lookups of `colors.neutrals`, `colors.discrete_order`, and `size_pt`. `git revert <sha>` therefore conflicts, and resolving it as a whole-commit revert breaks sync validation and the themes. Reverse the decision in the token JSON instead, then run the common ending.

| Item | Commit | `git revert` conflicts in | Rollback |
|---|---|---|---|
| 2 CMYK and PMS | `e55bab7` | `test_style.py`, `sync_tokens.py`, the token JSON | Set `cmyk` and `pms` to `null` (or the owner's values) on the brand tokens. Put `@unittest.skip` with the reason on `PdfPaletteTests.test_tokens_match_pdf_palette`, which checks the values against the PDF. |
| 4 Neutrals | `2bd9548` | `test_style.py`, `sync_tokens.py`, `themes/r/eig_tokens.R`, the token JSON | Change the `hex` and `rgb` of the entries in `colors.neutrals`. Keep the IDs, because the themes and the Stata scheme read them. |
| 5 Series order | `094a22f` | `sync_tokens.py`, the token JSON | Edit `colors.discrete_order.token_ids`, for example to the queued reorder. The scheme and theme palettes follow. |
| 8 Type sizes | `f7e330e` | the token JSON | To adopt the 2020 values in ambiguity `a-type-sizes`, set each role's `size_pt` (and `size_pt_range`, or drop it) and `source: "2020"`. Then change `test_role_sizes_are_points` to accept that source. Keep the `size_pt` names: sync rejects `size_px*`. |

Each recipe here was run on the branch tip, and the suite passed afterwards (2026-09-29).
