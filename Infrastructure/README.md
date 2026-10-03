# Infrastructure

The shared brain of this template: the rules, agents, workflows, templates, style system, and
scripts that both adapters read. This file is an index. `Infrastructure/TEMPLATE_CENSUS.md` is the detailed inventory of every part and how
the parts connect, including the generation model and the loading map.

## What lives here

- `AI_WORKFLOW.md`: the session process from intake to handoff.
- `AUTHORING.md`: how agents, workflows, rules, and templates are written, with the pre-merge checklist.
- `TEMPLATE_CENSUS.md`: the inventory of agents, skills, rules, templates, scripts, checks, and make
  targets, kept complete by the `census` maintenance check.
- `rules/`: governance, review, and style rulebooks; each owns its policy.
- `agents/`: specialist agent bodies (role, inputs, outputs, which rules to read).
- `skills/`: workflows, one adapter-neutral `<name>/SKILL.md` each.
- `templates/`: output shells (see the census).
- `style/`: the EIG style system; start at `style/README.md`.
- `references/`: the literature catalog and dataset registry; start at `references/README.md`.
- `adapter_configs/`: canonical Claude and Codex settings, hooks, command policy, and adapter READMEs.
- `scripts/`: the generator (`brain.py`), lifecycle hooks, validators, test suites, the review
  scripts, the shared local-app kit, and the war-room, review-board, and replication tools.
- `evals/review-fleet/`: the planted-defect fixture that `make review-eval` scores the review
  lenses against.
- `war_room/`, `review_board/`, `replication/`: the maps of the code war-room, review-board,
  and replication-package subsystems (`war_room/README.md`, `review_board/README.md`,
  `replication/README.md`).

Project records do not live here: plans, specs, session logs, war-room ledgers, and review
boards are in the top-level `records/` directory, beside the project lane (`records/README.md`).

## Changing things

1. Edit the canonical file here, never a generated copy in `.claude/`, `.codex/`, or
   `.agents/`: the guard hook blocks those edits and `make brain-check` reports drift.
2. Run `make brain-sync`, then `make maintenance-check`, which runs every registered
   maintenance check. Commit the sync output with the change.
3. New files under `agents/`, `rules/`, `templates/`, `skills/`, or `style/skills/` are found
   by `brain.py` without registration; agent and skill frontmatter follows `AUTHORING.md` §7,
   and `make brain-check` rejects missing or unknown keys. An agent that writes files, or spawns
   agents that do, sets Codex `sandbox_mode: workspace-write`, even a read-only reviewer; one
   that only returns text, such as `eig-reviewer`, sets `read-only`.
4. Give each fact one home (`AUTHORING.md` §2). When a part is added, moved, or removed, update
   its row in `TEMPLATE_CENSUS.md` (the `census` check fails until you do) and any subsystem
   README, instead of listing it here.
