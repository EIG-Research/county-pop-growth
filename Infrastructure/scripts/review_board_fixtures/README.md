# Review Board Fixtures

Synthetic inputs for `Infrastructure/scripts/test_review_board.py`. Nothing here describes a
real project, real data, or a real review.

| Path | What it is |
|---|---|
| `proj-fig/` | A fixture project. `code/make_figs.py` draws three small bar charts from `code/params.json`, styled by the shared `code/theme.json`, with the Python standard library only, and writes them to `output/figures/`. |
| `boards/proj-fig--demo/board.yaml` | The fixture board: three items (one frozen, one without an SVG sibling), an owner and one reviewer, and `board.fixture: true`. |

The suite copies both into a temporary directory before running anything, and checks that
this directory's digest is the same before and after. No PNG is committed here; every image
is generated at test time.

`code/theme.json` is deliberately absent from every item's `sources`, so a change to it is a
shared-code change: the round's changed-files report must name it (RB-C4).
