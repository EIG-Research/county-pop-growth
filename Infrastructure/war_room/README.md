# Code War Room

The code war room walks one analysis script block by block with its author: the agent commits
its reading of each block before the author explains it, and every divergence, assumption, and
decision is recorded in a durable per-script ledger plus a work order for a coding agent.

This README is the one map of the subsystem; other indexes link here rather than list its
parts. Nothing is stored in this folder: the ledgers live in `records/war_rooms/`, whose README
describes their layout, the slug, and how two reviewers' edits merge.

## How the subsystem fits together

A session runs prep, the walkthrough, reconcile, and render, and each part writes only what its
row says:

| Part | What it does and writes |
|---|---|
| `Infrastructure/skills/code-war-room/SKILL.md` | The workflow: runs the scripts in order and spawns the agent. |
| `Infrastructure/agents/code-interlocutor.md` | Writes the judgment fields only: each block's title, density, and prediction in prep, and divergences in reconcile. |
| `Infrastructure/scripts/war_room_prep.py` | `skeleton` segments and hashes; `merge`, `split`, `verify --write`, and `finalize` update the ledger; `locate` prints a script's ledger path. |
| `Infrastructure/scripts/war_room_server.py` with `war_room_app/` | The loopback walkthrough app; saves each answer, the reviewer list, walkthrough history, and drift. Opens a browser unless `--no-browser`. |
| `Infrastructure/scripts/war_room_reconcile.py` | Writes the assumption export, open questions, endorsed matches, `session.reconciled`, and `work-order.md`. |
| `Infrastructure/scripts/war_room_render.py` | Writes `ledger.md` and the HTML report, and nothing else; it does not write `work-order.md`. |
| `Infrastructure/scripts/war_room_lint.py` | Writes nothing; its `WL-` checks gate every write above. |
| `Infrastructure/scripts/war_room_lib.py` | Shared hashing, segmentation, drift, project-root resolution, and ledger IO. |

The file lock, atomic YAML save, project-root check, and loopback server base are the shared
kit in `Infrastructure/scripts/localapp/`. Every script that writes the ledger holds its lock
(`ledger.yaml.lock`, gitignored) from load to save, so a command-line write and a save from
the app never overwrite each other; the agent's hand edits do not, so the workflow stops the
app before a reconcile agent runs.

- Records: `records/war_rooms/<slug>/`, one directory per script (`records/war_rooms/README.md`).
- Rules: `Infrastructure/rules/code-war-room-rules.md` is what a session follows.
  `Infrastructure/rules/code-war-room-design.md` (hashing, drift, root resolution, the app and
  its API, ledger mechanics) and `Infrastructure/rules/code-war-room-segmentation.md` are
  for maintainers changing the scripts.
- Templates: `Infrastructure/templates/war-room-ledger.md`, `war-room-work-order.md`, and
  `war-room-report.md`.
- Tests: `make war-room-test` runs `Infrastructure/scripts/test_war_room.py` against
  `Infrastructure/scripts/war_room_fixtures/`, with no model and no network.
