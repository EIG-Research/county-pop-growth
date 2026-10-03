# Claude Adapter

Claude-facing adapter to the shared AI brain.

The startup sequence, the working rules, and the task routing table live in `../AGENTS.md`;
this file only describes the adapter.

## Shared brain links
- Root Claude instructions live in `../CLAUDE.md`, which imports the shared `../AGENTS.md` and adds Claude-only notes; both are written by hand.
- `agents/` and `rules/` are generated copies of canonical files in `../Infrastructure/`. `rules/` holds only the rules that declare `load: always` or `load: paths`; every other rulebook stays in `../Infrastructure/rules/`, where the agent, workflow, or routing-table task that needs one reads it.
- Templates are not mirrored: agents, rules, and workflows cite `../Infrastructure/templates/` directly.
- Canonical review content lives in `../Infrastructure/agents/`, `../Infrastructure/rules/`, and `../Infrastructure/templates/`.
- Canonical style-system assets live in `../Infrastructure/style/`.
- Project-level Claude config lives in `settings.json`.
- Refresh local copies (including skills) with `make brain-sync`; verify drift with `make brain-check`.

## Skills
- Every workflow is a skill at `skills/<name>/`, generated from `../Infrastructure/skills/<name>/` with the files beside its `SKILL.md`, and invoked as `/<name>`.
- The dedicated EIG style skills are generated from `../Infrastructure/style/skills/` into the same tree.
- A workflow whose canonical frontmatter sets `disable-model-invocation: true` (today `build-replication-package`) runs only when you invoke it; Claude does not start it on its own.

## Adapter rules
- Treat `../Infrastructure/` as source of truth for core workflow and guardrails.
- Use canonical review files in `../Infrastructure/` as source of truth for review workflows.
- Evidence standard is enforced through `../AGENTS.md` (Guardrails, Data and evidence) (no separate slash command or agent needed).
- Do not fork review logic in `.claude/`; update canonical files in `../Infrastructure/` and regenerate.
