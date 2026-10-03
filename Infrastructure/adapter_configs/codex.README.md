# Codex Adapter

Codex-facing adapter to the shared AI brain.

The startup sequence, the working rules, and the task routing table live in `../AGENTS.md`;
this file only describes the adapter.

## What Codex actually loads

This adapter is deliberately thin. Codex reads native surfaces plus the canonical Markdown on demand — it does not read Markdown mirrors of agents, commands, rules, or templates, so this repo no longer generates them.

| Surface | Location | Generated from |
|---|---|---|
| Project instructions | `../AGENTS.md` | written by hand; not generated |
| Repo-local skills (the only skill discovery tree) | `../.agents/skills/<name>/SKILL.md` | `../Infrastructure/skills/`, `../Infrastructure/style/skills/` |
| Native subagents | `agents/<name>.toml` | `../Infrastructure/agents/` (body and `codex:` frontmatter) |
| Project configuration | `config.toml` | `../Infrastructure/adapter_configs/codex.config.toml` |
| Lifecycle hooks | `hooks.json` | `../Infrastructure/adapter_configs/codex.hooks.json` |
| Execution policy | `rules/template.rules` | `../Infrastructure/adapter_configs/permissions.yaml` (shared with the Claude permissions) |

Each `agents/<name>.toml` wrapper carries only metadata plus instructions to read the canonical body at `../Infrastructure/agents/<name>.md` in full. The behavior lives in the canonical file, never in the wrapper.

## Trust and hook review (read this first if something seems inactive)

Codex loads project-scoped `config.toml`, `hooks.json`, and `rules/*.rules` **only for a trusted project**. If a session behaves as though none of them exist, check the project's trust level before debugging anything else.

Hooks additionally require interactive review: run `/hooks`, read the three handlers, and approve their hashes. Until you do, they are discovered but inactive — and the hash changes whenever the scripts change, so a re-review is expected after `make brain-sync` touches them. The three handlers are:

| Event | Script | Effect |
|---|---|---|
| PreToolUse | `hooks/guard_generated_tree.py` | Blocks edits to generated adapter files and names the canonical source to edit instead. |
| PostToolUse | `hooks/remind_brain_sync.py` | Reminds once per session that a canonical edit needs `make brain-sync`. |
| SessionStart | `hooks/session_context.py` | Injects PROJECT.md title status, newest plan, and newest session log. |

All three live under `../Infrastructure/scripts/hooks/` and are shared with Claude Code. `python3 Infrastructure/scripts/test_hooks.py` exercises both adapters' contracts and runs inside `make maintenance-check`.

A fourth script there, `hooks/guard_review_write.py`, limits the review agents' writes to `review-reports/`. Claude runs it from each review agent's own frontmatter; Codex has no per-agent hooks, so a Codex reviewer relies on its instructions and the workspace-write sandbox (`Infrastructure/rules/review-contract.md` §7).

The execution policy in `rules/template.rules` (experimental in Codex) only adds prompts and prohibitions; the workspace-write sandbox in `config.toml` stays the execution boundary. It prompts on `git push`, `latexmk`, and `sync_tokens.py --write`, and forbids force-push, hard reset, forced clean, working-tree discard, and `rm -rf`. It has no `allow` rule, because an allowed command runs outside the sandbox without a prompt. Every rule's `match` / `not_match` examples must agree with its pattern: Codex drops all project and user rules when one fails, and `test_hooks.py` checks them.

## Reading the rules

There is no auto-loaded rules directory on the Codex side, and Codex reads no Markdown mirror of agents, rules, or templates. Read the relevant rulebook from `../Infrastructure/rules/` on demand — `../AGENTS.md` carries the task routing table. Canonical review content lives in `../Infrastructure/agents/`, `../Infrastructure/rules/`, and `../Infrastructure/templates/`; canonical style assets live in `../Infrastructure/style/`.

## Adapter rules
- Treat `../Infrastructure/` as source of truth for core workflow and guardrails.
- Use canonical review files in `../Infrastructure/` as source of truth for review workflows.
- Evidence standard is enforced through `../AGENTS.md` (Guardrails, Data and evidence) (no separate command or agent needed).
- Do not fork review logic in `.codex/`; update canonical files in `../Infrastructure/` and regenerate with `make brain-sync`. Verify with `make brain-check`.
- `make brain-check` actively rejects the retired Markdown mirror directories, so they cannot drift back into the runtime.
