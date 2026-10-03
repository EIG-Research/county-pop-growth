# Records

The project's recoverable context: what was planned, what was specified, what happened in each
session, and the durable records of the code war room and the review board. Agents write here
so that another agent, or a person, can resume the work from disk rather than from chat.

| Folder | Holds | Written by |
|---|---|---|
| `records/plans/` | Saved plans, DRAFT through COMPLETED (`Infrastructure/rules/plan-first-workflow.md`). | the agent, before non-trivial work |
| `records/specs/` | Requirements specs for ambiguous or high-effort tasks. | the agent, after clarification |
| `records/session_logs/` | Session logs (`Infrastructure/rules/session-logging.md`). | the agent, during and after a session |
| `records/war_rooms/` | Per-script code war-room ledgers and work orders. | the war-room scripts |
| `records/review_boards/` | Review boards: notes, decisions, and render hashes, round by round. | the review-board scripts and server |
| `records/ai-use-log.md` | The AI-use ledger that disclosure statements are built from (`Infrastructure/rules/ai-use-disclosure-rules.md`); created from `Infrastructure/templates/ai-use-disclosure.md` on first use. | the agent, each session that uses AI for work product |

The SessionStart hook names the newest plan and session log here at the start of every session.

`make template-reset` scrubs this directory back to its READMEs before the template is copied
into a new project, so one project's records never ship inside another. The tooling that
writes the war-room and review-board records is mapped in `Infrastructure/war_room/README.md`
and `Infrastructure/review_board/README.md`.
