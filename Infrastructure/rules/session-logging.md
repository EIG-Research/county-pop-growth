---
load: referenced
---

# Session Logging

Keep decisions recoverable by the next session or agent. Logs live at
`records/session_logs/YYYY-MM-DD_description.md`, from
`Infrastructure/templates/session_log.md`.

- **Cadence.** Read `Session log cadence` in `PROJECT.md` (Working agreements); it sets when a
  full log is due. Ask about it only if the user raises logging.
- **Before ending or handing off,** log decisions, user corrections, and blockers, with open
  questions and the next step (the short form). A small task with no decisions needs no entry.
- **After plan approval,** record the goal, approach, and key context.
- **Delegation.** Record work delegated to a local model (the `delegate-to-local-model` workflow).
- **AI use.** When the session used AI for work product (code, analysis, figure code, editing
  feedback), append a row to `records/ai-use-log.md`
  (`Infrastructure/rules/ai-use-disclosure-rules.md`), because disclosure is built from it.
- **Promote durable lessons.** If a finding is reusable beyond this project, move it into the
  canonical doc that owns the topic before closing, because `make template-reset` deletes logs.
