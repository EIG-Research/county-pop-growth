# Authoring Standard

This guide sets how agents, skills (workflows), rules, and templates are written for current
models, which follow instructions literally, over-apply emphasis, and pay for every
always-loaded word in every session and subagent. A file meets it when it passes the checklist
at the end. A check this guide names enforces its item; every other item is reviewer-applied.

## 1. Load tiers

Put text in the cheapest tier that still reaches the reader who needs it.

| `load:` | Loads when | Who pays | What belongs there |
|---|---|---|---|
| `always` | Session start: root instructions, and rules without `paths:` | Main session and every subagent, every turn | Invariants every agent needs (no fabrication, evidence standard, generated-file rule, attribution, subagent clause) and one-line pointers |
| `paths` | Claude reads a file matching `paths:` | The session that read it | Conventions for editing that file type, such as R style |
| `invoked` | A skill is invoked or an agent spawned | That run | Workflow steps, agent roles |
| `referenced` | Another file names it and the reader opens it | That reader | Rulebooks, templates, style docs, reference tables |

- Every subagent pays the always-loaded set again; its word ceiling is enforced (`brain.py check`).
  Skill and agent descriptions are always loaded too, as the listing the model routes by.
- A `paths:` rule fires when a matching file is read, not written, and not when a task starts.
  It never reaches an agent that only writes there, and a task-triggered rule (replication, for
  example) belongs in that task's workflow instead.
- Codex loads the `AGENTS.md` files from the repo root down to the working directory, plus skill
  names and descriptions: no read-triggered tier, no imports, a 32 KiB cap. A link loads nothing
  there, so a rule that binds everyone lives in `AGENTS.md` itself.
- The tier is fixed by file type: agents and skills are `invoked`; templates and style docs are
  `referenced`. Rules vary, so each declares `load:` (and `paths:` for that tier) in frontmatter;
  a missing or invalid key fails (`brain.py check`).

## 2. One owner per fact

Each fact has one home. Other files link to it by path instead of restating it, because copies
drift: the review output contract sits in every reviewer's files, and the copies disagree.

| Fact | Owner |
|---|---|
| Policy: what must or must not happen, thresholds, severities | rule (`Infrastructure/rules/`) |
| Role, inputs, outputs, which rules and templates to read | agent (`Infrastructure/agents/`) |
| Workflow steps: arguments, order, agents to spawn, what to report | skill (`Infrastructure/skills/`) |
| Output shape: sections, fields, markup, placeholder fill | template (`Infrastructure/templates/`) |
| Tool grants, model, effort, description | the file's frontmatter |
| Project facts and working agreements | `PROJECT.md` |
| Invocation syntax and argument bridges | the generator |
| Anything a script computes or checks: IDs, hashes, formats, rendering, inventories | the script, named in prose |

- Summarize beside a link only when the reader needs it to decide whether to open it. A
  restated fact is a review item with no check: `ALLOWED_DUPLICATIONS` in `brain.py` covers only
  a canonical file name used in two directories, not facts repeated across files.
- No counts, ordinals, or inventories that go stale when an item is added ("the five reviews");
  point to what enumerates them. History ("merges the former X") belongs in version control.

## 3. Write for the reader model

1. Agents and skills open with purpose and "done when" (the observable result that ends the
   job), since the model plans from the opening. Rules and templates open with their purpose.
2. Give the reason with the instruction ("pin the codebook vintage, because codes change between
   releases"), so the model can handle unlisted cases and skip cases where the reason fails.
3. Calibrate emphasis: keep it (the words and bold counted by checklist item 3) for safety and
   integrity (fabrication, data loss, secrets, publishing, attribution), at most three per file,
   each with its reason. On routine steps ("read in full") it is over-applied and drowns the rest.
4. State the role, not a persona. A disposition such as "assume every line is fabricated" is
   followed literally and produces false positives; write a calibration rule instead (§6).
5. Be concrete: name the file, command, threshold, and output path. Say what to do, not only
   what to avoid. Cut lines the model follows anyway ("be concise", "be thorough").
6. Prioritize: keep the key steps in the body and long catalogs in a referenced file, because
   long mandatory lists dilute attention. Make "read first" lists conditional on the task.
7. Add an example only to settle an ambiguity, and check it: models copy examples, mistakes
   included. "Done when" lists name observable results, not self-attestation.
8. Keep one stance per topic; resolve conflicting instructions in the owning file before merge.

## 4. Subagent-safe phrasing

- Every agent, and any skill a subagent or automated run can invoke, may run with no user to
  ask. Write user-dependent steps as conditionals: "If the session is interactive, confirm the
  draft with the owner; otherwise return the draft and the open question to the caller."
- Irreversible or outward-facing steps (publishing, pushing, deleting, writing outside the
  project) wait for the user's approval; a delegated run stops there and reports.
- The root instructions own the general subagent skip rule; files state only their exceptions.

## 5. Guarantees live in scripts

Prose describes; scripts enforce. A claim that a state always holds names its check ("Internal
paths resolve (`make maintenance-check`)"); with no check yet, write expected practice and log
the gap. Emphasis and prose self-checks ("no placeholder left") are not guarantees. Do not
describe an algorithm a script implements (hashing, IDs): the model does it by hand, and drifts.

## 6. Reviewer prompts

Reviewers also follow these, because false positives cost trust; the severity scale is in
`Infrastructure/rules/review-contract.md` §3.

- Scope each lens: its goal, about five to eight high-value failure classes, and a "don't flag
  when" clause for each. Each check family has one owning lens; the others defer.
- Verify before reporting. A finding quotes code or text with file and line and says how it was
  checked; a finding about a missing step says where the reviewer looked.
- Severity (impact if true) and confidence are separate. High confidence means verified by
  command output, documentation, or quoted code that shows the problem. Overall risk counts
  high-confidence findings only and states how many HIGH findings are unconfirmed.
- Not knowing is not a finding: unresolved and low-confidence items go to "Questions for the
  author", without a severity. Try to refute each HIGH or CRITICAL finding before reporting it.
- No "when in doubt, flag" or "choose the higher severity" defaults. The one exception is the
  replication safety gate, fail-closed by design because a false inclusion is a permanent public
  leak (`Infrastructure/rules/replication-publishing-rules.md`, Severity Summary).
- Rulebook examples are checkable against package docs, since a wrong default becomes a false
  finding in every report.

## 7. Frontmatter and length budgets

| File type | Body budget | Frontmatter |
|---|---|---|
| Root instructions | under 200 lines each; always-loaded words ≤ `ALWAYS_LOADED_CEILING` (`brain.py check --only load`) | none |
| Always-loaded rule | 40 lines; prefer a line in `AGENTS.md` | `load: always` |
| Path-scoped rule | 150 lines | `load: paths`, `paths:` |
| Referenced rulebook | 300 lines | `load: referenced` |
| Skill | 150 lines; up to 250 with a recorded reason | `name`, `description`, `allowed-tools`; optional `argument-hint`, `disable-model-invocation` |
| Agent | 60 lines | `name`, `description`, `tools`; optional `model`, `effort`; `codex:` with `sandbox_mode`, optional `reasoning_effort` (set only where reasoning is the deliverable), `model`, `description` |
| Template | 15 lines of instructions | none |

- Budgets count body lines, blank ones included, plus any appendix, but not frontmatter. A skill
  passes 150 lines only when splitting would separate steps that run together, with the reason in
  the approved plan. Template instructions are prose for the model, not markup or placeholders.
- Budgets apply when a file is created or rewritten. No check enforces the line budgets;
  reviewers apply them (checklist item 2). `brain.py check` enforces the always-loaded word
  ceiling, the 1,024-character description limit, and the 32 KiB `AGENTS.md` cap.
- Current exceptions, over budget: `review-board-rules` (400 lines, referenced; to be split into
  operator rules and a design reference);
  `methodology-rules` (365 lines, referenced; the owner kept one rulebook over splitting it when
  signing off the econometrics sections, 2026-09-30); agents `literature-scout` (197), `data-dictionary-agent`
  (141), and `replication-safety-reviewer` (86); skills `idea-refine` (306) and `interview-me`
  (271); and `maintenance-rules` (222, path-scoped). Each stays listed until it is trimmed
  or rewritten.
- `name` matches the file or directory. `description` says what the file does, then "Use
  when…", within 1,024 characters (Codex `MAX_DESCRIPTION_LEN`), ideally 300. Codex reads
  `name`, `description`, and `metadata.short-description`, not `when_to_use`.
- Skill `allowed-tools` "grants permission for the listed tools during the turn that invokes the
  skill… It does not restrict which tools are available" (Claude Code skills docs). List only
  what the skill uses, scope Bash as `Bash(<command> *)`, and leave out what should prompt:
  project code, ports, downloads, publishing, non-localhost network. Agent `tools` takes tool
  names and limits the agent: grant `Bash` only when the procedure runs commands (they still
  meet the session's permission rules), and no `Edit` for read-only reviewers.
- `effort: high` where a miss is costly, as for reviewers; `model` only when a role needs a
  different tier; `disable-model-invocation: true` for workflows the user starts deliberately.

## 8. Adapter neutrality

Canonical bodies (agents, skills, rules, templates) and `PROJECT.md` serve both adapters. They
contain no `/name`, `$name`, `$ARGUMENTS`, or paths into `.claude/`, `.codex/`, or `.agents/`:
write "the `review-code` workflow" and cite `Infrastructure/` paths. `make brain-check` scans
workflow bodies, generated Codex skills, rules, templates, `PROJECT.md`, `AGENTS.md`, and
`AI_WORKFLOW.md` for `$ARGUMENTS` and for a backticked `/name` naming any
workflow or style skill; a bare slash is not checked, since paths contain them. A grep covers
agents and style-skill bodies.

## Pre-merge checklist

1. Frontmatter parses; required keys are present; rules declare `load:` (`brain.py check`).
2. Body within budget, or on the §7 exceptions list; agents and skills open with purpose and
   "done when".
3. At most three case-sensitive `\b(MUST|NEVER|ALWAYS|DO NOT)\b` matches plus bold warnings,
   each on safety or integrity; headings, code spans, and lowercase words do not count.
4. No fact restated from its owner (reviewer-applied; see §2).
5. No stale counts, ordinals, inventories, or history; "read first" lists are conditional.
6. No unconditional "ask the user" or "wait for approval" where the file can run delegated.
7. No adapter syntax or generated-tree paths (`make brain-check`; grep agent and style-skill bodies).
8. Each claim that a state always holds (a guarantee, not an instruction) names its check, and
   `make maintenance-check` passes.
9. Reviewers: evidence per finding, separate severity and confidence, no flag-if-unsure, a
   "don't flag when" per failure class, examples checkable against package docs.
