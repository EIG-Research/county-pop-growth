# War Rooms

Durable ledgers from `code-war-room` sessions — a human and an agent walking one analysis
script block by block, recording what each block does, what it is meant to do, why it is
built that way, and what assumptions it carries forward.

## Layout

```
records/war_rooms/<slug>/
  ledger.yaml      source of truth, machine-readable
  ledger.md        rendered walkthrough, human-readable
  work-order.md    actionable items for a coding agent
```

The slug is the reviewed project's id, then a double hyphen, then the script's
project-relative path with every path separator replaced by a double hyphen, keeping the file
extension:

```
my-project--code--02_build_sample.R
```

It carries no date. Namespacing by project id means two reviewed projects with the same
script path never share a ledger, and one script keeps one directory across every session
that touches it. Session dates live in the ledger's `session.history[]`, which records the
prep pass, each reviewer's walkthrough days, and each reconcile run.

**One ledger covers exactly one script.** A project accumulates several. Two people
reviewing different scripts never touch the same file.

## Why these live here and not in `review-reports/`

The rendered HTML report goes to `<target>/review-reports/war-room/` alongside the five
review reports, and is regenerated on demand. The ledger does not: `review-reports/` is
gitignored and denylisted from replication packages, which would defeat the three things
this ledger exists to provide — durability across sessions, git-mergeable multi-reviewer
review, and hash-based detection of code that changed after a decision was recorded.

## Committed, and scrubbed on distribution

Ledgers are committed. They are project memory: the next person to touch a script can read
why it does what it does, and a changed block can be checked against the decision that was
recorded for it.

`make template-reset` scrubs this directory back to this README, so one project's ledgers
never ship inside a copy of the template.

## Merging two reviewers

Two reviewers walking the same script share one `ledger.yaml` — the one in that script's slug
directory — and edit it on separate branches. There is never a second ledger directory for the
same script, and never a second entry for the same `block_id`.

Ledgers are structured so those parallel edits merge in git: exactly one top-level entry per
block under a stable `block_id`, no shared counters, and `reviewer` recorded per entry.

A merge conflict on one `block_id` means two people recorded different readings of the same
block. **That conflict is the intended signal, and the thing to preserve is the disagreement,
not the duplicate.** Resolve it by keeping one reviewer's entry as the block's record and
moving the other reviewer's answer into a `dissent` list on that same entry:

```yaml
- block_id: b007
  reviewer: bglasner
  disposition: needs-change
  # ... the kept record, unchanged ...
  dissent:
    - reviewer: jdoe
      answered_at: '2026-09-18T14:02:11.418293Z'
      disposition: confirmed
      author_account:
        meant_to_do: >-
          Restrict to prime-age workers; the missing upper bound is deliberate here.
        why_this_way: "The pooled sample already drops 55+ upstream."
        assumptions_carried: []
      endorsed_prediction: false
```

Never resolve it by picking a winner and deleting the other answer, and never by keeping two
entries with the same `block_id`. Two people disagreeing about what a block is meant to do is
a finding worth keeping; a duplicated `block_id` is a lint failure that breaks every count
rendered from the ledger.

## Tooling

The scripts, agent, rules, templates, and tests that write these ledgers are mapped in
`Infrastructure/war_room/README.md`.
