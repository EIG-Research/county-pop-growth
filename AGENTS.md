# Repository Instructions

> New to this repo? Start with `README.md` (Getting Started).

## Delegated and Non-Interactive Runs

If another agent spawned you, or no user can answer, skip startup reads beyond `PROJECT.md`,
user questions, plan approval, and session logging: your caller owns them. Still apply
Guardrails, Change Control, task-triggered reads (the routing table below), and the
canonical-source and commit rules. Wherever a rule says to ask the user or await approval, including a missing `PROJECT.md`
title, stop and report a blocker to your caller instead of guessing.

## Start

1. Read `PROJECT.md`. If the title is missing, stop and ask for it before substantive work
   unless either (a) the user is using the bounded project-framing exception in
   Guardrails (Scope and alignment) below to determine the title and research question, or
   (b) `Infrastructure/.template-identity` exists, which means this is the source
   template and template maintenance may proceed with the title intentionally unset.
2. For a non-trivial task, read `Infrastructure/AI_WORKFLOW.md`; it owns framing and discovery routing.
3. When resuming work, read the newest plan in `records/plans/` and the newest log in
   `records/session_logs/` (the session-start hook names both), check `git status`, and
   state the current task before continuing.
4. Before a task in the routing table below, read its files.

## Working Rules

- **Plans.** A task needs a saved plan when it changes more than two files, touches
  `Infrastructure/` outside the literature store, or is hard to reverse; single-file fixes, diagnostics, and questions do
  not. Save the plan to `records/plans/` and get approval before implementing
  (`Infrastructure/rules/plan-first-workflow.md`).
- **Verification.** Verify before claiming done (`Infrastructure/rules/verification-protocol.md`);
  after changing `Infrastructure/`, run `make brain-sync` and `make maintenance-check` (the
  literature store alone needs only the checks that protocol names).
- **Logging.** Before ending or handing off, log decisions, corrections, and blockers
  (`Infrastructure/rules/session-logging.md`; cadence in `PROJECT.md`).
- **Long runs.** Before a run over 2 minutes, or a retry, read
  `Infrastructure/rules/performance-cost-governance.md`; a run over 60 minutes needs human
  confirmation.

## Guardrails

### Scope and alignment

1. Start by reading `PROJECT.md` before proposing work.
2. Do not begin substantive project work until `PROJECT.md` contains a project title.
3. A bounded project-framing exception may run before a title exists when the user is
   still determining the project title, research question, audience, success criteria,
   constraints, or scope. Under this exception:
   - inspect only the repository context needed for framing;
   - do not acquire literature or data, run analysis, draft deliverables, or implement
     code; and
   - update `PROJECT.md` only after the user confirms the framing and separately
     authorizes the write.
4. Ask for a missing optional `PROJECT.md` section only when the current task needs it.
5. Keep all work tied to the research question and in-scope data when available.
6. If project goals are unclear, flag uncertainty explicitly and use the discovery
   routing in `Infrastructure/AI_WORKFLOW.md` before specification or planning.
7. In a non-interactive context, unresolved material intent is a blocker. Report the
   missing decision and stop; do not invent a project, product, audience, research
   question, specification, or plan as a substitute for user confirmation.

### Data and evidence

1. Do not fabricate data, citations, or results.
2. Add an `Evidence` section whenever an output states a fact, number, conclusion, or
   recommendation about the research (its data, results, methods, or literature), whether a
   deliverable, a review output, or a chat answer.
3. The `Evidence` section must include: `Sources`, `Confidence`, and `Assumptions`.
4. `Sources` must point to concrete origins (for example: repo file paths, dataset names, or URLs).
5. `Confidence` must rate major claims as `High`, `Medium`, or `Low`.
6. If no verifiable source exists, state: `No verifiable source available`.
7. The `Evidence` section is optional for replies whose claims concern only code or repo
   mechanics and are verified by a command shown in the reply. When unsure, include it.
8. Label assumptions clearly.
9. Separate observed facts from interpretations.

### AI use in work product (EIG policy)

1. Never draft any part of an EIG work product's prose (report, brief, blog post, analysis),
   because the author answers for every word. Give feedback: name the problem and rule, suggest
   at most a word or short-phrase swap. Code, analysis, logs, and summaries stay in scope.
2. Log AI use for work product in `records/ai-use-log.md` for disclosure
   (`Infrastructure/rules/ai-use-disclosure-rules.md`).

### Reproducibility

1. Keep steps operational and repeatable.
2. Record key commands, files changed, and outputs.
3. Note unresolved risks and open decisions.
4. Store all recorded session logs in `records/session_logs/`.

### Communication

1. Be concise and explicit.
2. Surface tradeoffs when choices have non-obvious consequences.
3. End sessions with clear next actions.

## Change Control

- The template is EIG-specific by design; keep machine- and person-specific paths, credentials,
  and private notes out of shared files (operator-local notes go in the gitignored
  `Infrastructure/local/`).
- Anything another agent needs to resume work lives on disk (`PROJECT.md`, plans, specs, session
  logs), not only in chat.
- Scripts enforce; prose describes. A claim that a state always holds names the check that
  enforces it (`Infrastructure/AUTHORING.md` §5).
- Ask before adding new top-level systems or major structure changes.
- Prefer small, reversible edits.
- Document significant decisions in the session log.

## Task Routing

Both adapters read these files by path.

| Task | Read |
|---|---|
| Planning or a requirements spec | `Infrastructure/rules/plan-first-workflow.md` |
| R code creation, editing, or review | `Infrastructure/rules/r-coding-style-rules.md` |
| Code review | `Infrastructure/rules/review-contract.md`, `Infrastructure/rules/code-quality-rules.md` |
| Methodology review | `Infrastructure/rules/review-contract.md`, `Infrastructure/rules/methodology-rules.md` |
| Number or document-consistency review | `Infrastructure/rules/review-contract.md`, `Infrastructure/rules/doc-number-rules.md`, `Infrastructure/rules/doc-consistency-rules.md` |
| AI-skeptic review | `Infrastructure/rules/review-contract.md`, `Infrastructure/rules/ai-skeptic-rules.md` |
| Data documentation | `Infrastructure/rules/data-documentation-rules.md` |
| Reproducing a published result | `Infrastructure/rules/reproduce-published-results.md` |
| Publishing a replication package | `Infrastructure/rules/replication-publishing-rules.md` |
| Writing, citations, figures, tables, or Datawrapper | `Infrastructure/style/docs/README.md` and the matching `Infrastructure/rules/style-*.md` file |
| Feedback on EIG prose, or an AI-use disclosure | `Infrastructure/rules/ai-use-disclosure-rules.md` |
| Writing agents, workflows, rules, or templates | `Infrastructure/AUTHORING.md` |
| Maintenance | `Infrastructure/rules/maintenance-rules.md` |

## Repository Layout

This repo is both an active project workspace and a reusable template. Project work and outputs
live in the project lane:

- `PROJECT.md` — project context.
- `code/` — analysis scripts; the starter pipeline is `code/run_all.R`.
- `data/raw`, `data/processed` — inputs as received, and cleaned checkpoints.
- `drafts/` — prose in progress.
- `output/figures`, `output/tables` — finished figures and tables; `output/logs` — one log per pipeline run.

Shared logic lives in `Infrastructure/`, the source of truth for workflow, review
logic, and style: `Infrastructure/README.md` indexes it, and `Infrastructure/TEMPLATE_CENSUS.md`
inventories every part. Each adapter lists the agents and workflows itself. Project records live
in `records/plans/`, `records/specs/`, and `records/session_logs/`.

## Canonical Sources

The `.claude/`, `.codex/`, and `.agents/` trees are generated from `Infrastructure/` by `make brain-sync`. This `AGENTS.md` and the root `CLAUDE.md` (which imports it) are written by hand and edited in place. Do not hand-edit generated copies; change the canonical file under `Infrastructure/`, run `make brain-sync`, then `make brain-check`. The control panel is the `Makefile` (`make brain-sync`, `make brain-check`, `make parity-check`, `make maintenance-check`, `make template-reset`).

## Git Commit Attribution

- Author commits solely as the repository's configured git user — Ben Glasner. Do not
  add AI co-author trailers (for example `Co-Authored-By: Claude ...`) or any other AI
  attribution to commits.
- Do not include links or references to AI sessions, chats, or generation tools (for
  example "Generated with Claude Code") in commit messages or pull request descriptions.
- Commit or push only when the user asks; use a branch for multi-file work.

## Codex Notes

- Workflow skills live in `.agents/skills/`; subagents in `.codex/agents/*.toml`, each a wrapper whose canonical body under `Infrastructure/agents/` you read in full before acting.
- Codex loads no rule on its own. Project configuration, hooks, and execution policy load only for a trusted project; see `.codex/README.md`.
