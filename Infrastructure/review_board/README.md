# Review Board

The review board takes rendered figures, tables, or slides through rounds of owner review on a
local board: the agent evaluates each note against the data and the style rules, revises the
source, re-renders, and reports what changed until the owner has approved every current render.

This README is the one map of the subsystem; other indexes link here rather than list its
parts. Nothing is stored in this folder: the boards live in `records/review_boards/`, whose
README describes each board's files, their single writers, and what is committed.

## How the subsystem fits together

| Part | What it does |
|---|---|
| `Infrastructure/skills/review-board/SKILL.md` | The workflow: sets up a board, runs rounds, and reports what changed. |
| `Infrastructure/rules/review-board-rules.md` | The binding rules (`RB-` ids) the workflow and scripts cite. |
| `Infrastructure/scripts/review_board.py` | The CLI: `init`, `round open`, `render`, `record`, `round close`, `status`, `lint`, `summary`. The agent's only write path into `ledger.yaml`. |
| `Infrastructure/scripts/review_board_server.py` with `review_board_app/` | The loopback board, and the only writer of `feedback.yaml`. Opens a browser unless `--no-browser`. |
| `Infrastructure/scripts/review_board_lint.py` | The `RL-` checks that gate every server save, `round open`, and `round close`, including the append-only check against `git HEAD`. |
| `Infrastructure/scripts/review_board_measure.py` | Size, DPI, text-size, palette, and contrast measurements for each render. |
| `Infrastructure/scripts/review_board_lib.py` | Vocabularies, the reviewer-event writer, the status fold, and the render hash. |

YAML IO, project-root resolution, lint result types, and the loopback server base are the
shared kit in `Infrastructure/scripts/localapp/`.

- Records: `records/review_boards/<project id>--<board id>/`, one directory per board
  (`records/review_boards/README.md`).
- Tests: `make review-board-test` runs `Infrastructure/scripts/test_review_board.py` against
  `Infrastructure/scripts/review_board_fixtures/`, with no model and no network.
