---
name: orchestrate
description: >-
  Launch the orchestrator agent on a multi-step objective: it orders the work across specialist agents by dependency, spawns them in waves, and returns one status summary. Use when a task needs several specialists in a set order; for a review pass alone, use full-review.
---

# Workflow: orchestrate

Launch the orchestrator agent and relay its status. Done when the orchestrator has returned and
its summary, open questions, and next action have been reported to the user.

1. The argument is the objective. If none was given, ask for it.
2. Spawn the `orchestrator` agent (`Infrastructure/agents/orchestrator.md`) with the objective,
   the target directory if the user named one, and any constraints the user stated. It plans
   and spawns the specialists itself, so their wave outputs stay out of this session.
3. Relay its summary. Put each question it returns from an approval gate to the user, then
   launch it again with its previous summary and the user's answers, since a new launch starts
   with no memory of the last one, so it resumes the blocked workstreams instead of replanning.
4. If it returns a review pass as the next action, offer to run the `full-review` workflow on
   the target it names.

## Input

Mention `$orchestrate` with the details in the same message, pick the skill by name, or simply describe the task. Treat the invoking message as this workflow input.
