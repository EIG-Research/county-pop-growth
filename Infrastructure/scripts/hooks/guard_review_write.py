#!/usr/bin/env python3
"""PreToolUse hook for the review agents: allow file writes only under `review-reports/`.

The review lenses are read-only on the project they review (review-contract.md section 7):
their findings file, the rendered reports, and scratch work all go under
`<target>/review-reports/`. An agent's `tools:` list cannot express a path rule, and a
path-scoped `disallowedTools` entry removes the whole tool (anthropics/claude-code#97212),
so each review agent declares this hook in its own frontmatter (`hooks:`, rendered into the
Claude agent by `brain.py`) on `Write|Edit|NotebookEdit`. The hook runs only while that
agent runs; it does not touch the main session.

A write is allowed when every path the event names resolves (symlinks and `..` followed)
to a location inside a directory called `review-reports`, at any depth, so a review of an
external project works the same as a review of this repository. Anything else is denied
with the reason, and an event that names no path is denied too, because a guard that
cannot see the target should not wave it through.

Known gaps, recorded rather than hidden: a `Bash` command can still write anywhere the
session's permissions allow (the agents that hold Bash need it to run scratch scripts and
the renderer), and Codex has no per-agent hook, so a Codex reviewer relies on its
instructions and its sandbox.

Output follows the adapter convention in `hook_common.py`: Claude reads a
`permissionDecision` object on stdout; anything else gets exit code 2 and stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from hook_common import candidate_paths, is_claude

ALLOWED_DIR = "review-reports"


def outside_reports(payload: dict) -> list[str] | None:
    """The named paths that fall outside a `review-reports/` directory; None when no path is named."""
    paths = list(candidate_paths(payload))
    if not paths:
        return None
    return [str(p) for p in paths if ALLOWED_DIR not in Path(p).parts[:-1]]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        reason = "the hook received no readable event, so the write target is unknown"
    else:
        outside = outside_reports(payload)
        if outside == []:
            return 0
        reason = ("the event names no file path" if outside is None
                  else "it would write outside a review-reports/ directory: " + ", ".join(outside))
    message = (
        f"Review agents write only under <target>/review-reports/, and {reason}. Put findings "
        "and reports in review-reports/ and scratch scripts in review-reports/_scratch/ "
        "(Infrastructure/rules/review-contract.md section 7); never edit the project under review."
    )
    if isinstance(payload, dict) and is_claude(payload):
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "permissionDecision": "deny",
                                          "permissionDecisionReason": message}}, sys.stdout)
        return 0
    sys.stderr.write(f"BLOCKED: {message}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
