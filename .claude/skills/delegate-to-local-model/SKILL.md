---
name: delegate-to-local-model
description: "Decide whether a mechanical, low-stakes piece of the current task can go to a local, non-metered model server (such as Ollama); propose it, and on the user's confirmation dispatch it, review the output, and log it. Use when part of the current task is mechanical and low-stakes and a local model server may be running."
argument-hint: "[task-description]"
allowed-tools: ["Read", "Grep", "Glob", "Bash(curl -s http://127.0.0.1:11434/api/tags)"]
---

# Workflow: delegate-to-local-model

Send a mechanical piece of the current task to a local model, to keep low-value-per-token work
off the primary agent's budget without lowering the correctness bar. Done when the user has
confirmed or declined one specific proposal, and any delegated output has been reviewed,
fixed or discarded, and logged.

This workflow owns the local-delegation policy. Delegation is a per-instance choice the user
confirms each time, never a standing default, because the user carries the risk of each one.

## Input

Invoke as `/delegate-to-local-model [task-description]`.

Arguments: $ARGUMENTS

Optional: the task or fragment to consider. Without one, consider the task in progress.

## Eligibility

Small local models (single-digit billions of parameters) are reliable at pattern-following,
restyling, and bulk mechanical transforms, and unreliable at multi-step reasoning, domain
judgment, and exact numbers or citations. Eligibility follows from that split, so it turns on
stakes, not runtime. A task qualifies only when all of these hold:

- a mechanical rule, not judgment, defines "correct";
- it is narrowly scoped, and the result is easy to diff-review;
- nothing in it is evidence, and it is not part of a Tier 3 or 4 job
  (`Infrastructure/rules/performance-cost-governance.md`), where a silent error costs a long
  rerun and the run's reproducibility.

When unsure, it does not qualify. For example, good candidates:

- first-pass relevance triage of a batch of abstracts before the `literature-intake` workflow;
- repetitive stubs (near-identical registry entries or spec sections) that are filled in later;
- converting already-correct text between checkable formats, such as table markup;
- a rough summary of a long codebook, checked against the source by `data-dictionary-agent` or
  a person before anything relies on it;
- bulk renaming to a fixed pattern, or a first-draft commit message or log entry that is
  rewritten before use.

Do not delegate these, because a small model's errors in them are hard to see and costly:

- anything that will appear in an `Evidence` section: facts, citations, confidence;
- methodology, econometric, or research-design reasoning;
- analysis code whose correctness depends on the dataset conventions in
  `Infrastructure/references/datasets/registry.yaml`;
- constructing or verifying a citation (the `cite` workflow owns correctness; restyling
  already-correct citation strings is fine);
- EIG voice and style judgment;
- any review-agent role;
- anything that would be accepted without an independent review.

## Steps

1. Probe the endpoint: `curl -s http://127.0.0.1:11434/api/tags`. A local server is
   operator-specific setup, not a template dependency. If nothing responds and the user invoked
   this workflow directly, tell them no local model server answered; otherwise return to the
   task without mentioning delegation.
2. If the run is not interactive (a subagent or automation), stop here: delegation needs the
   user's per-instance yes. Do the work directly, or return a proposal to the caller.
3. Check the candidate against Eligibility. If it is not eligible, stop without proposing, and
   say why if the user invoked this workflow directly.
4. Pick the model. If `Infrastructure/local/model-routing.md` exists (operator-local, not
   committed), use its fast general-purpose model for ordinary work, and its reasoning model
   only for tasks that need multi-step reasoning, since that model is slower. Without a roster,
   ask the user which model to use. Model names belong in that roster, not in this file.
5. Propose it in one or two sentences: what would be delegated, to which model, and why it is
   eligible. Wait for the user's yes.
6. On confirmation, dispatch over the HTTP API
   (`curl http://127.0.0.1:11434/api/generate -d '{"model": "<model>", "prompt": "<task>", "stream": false}'`)
   or the CLI (`ollama run <model> "<task>"`).
7. Treat the output as an untrusted draft. Review it as you would any tool output, and fix or
   discard anything wrong before it touches `code/`, `data/`, `drafts/`, or `output/`. Never
   cite it as a source in an `Evidence` section, because no one has verified it against one.
8. Record the delegation in the session log (`Infrastructure/rules/session-logging.md`).

## Output

A short note: the task delegated, the model, a summary of what came back, what changed on
review, and a statement that the output was not used as an evidence source.
