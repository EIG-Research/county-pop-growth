@AGENTS.md

## Claude Runtime Notes

- The `@AGENTS.md` line above imports the shared instructions in place; edit shared text there.
- Subagents live in `.claude/agents/`; skills, every workflow included, in `.claude/skills/`
  (invoke one as `/<name>`); project settings in `.claude/settings.json`.
- `.claude/rules/` holds the path-scoped rules, which load when a matching file is read, such as
  the R coding standard for project-authored R files.
