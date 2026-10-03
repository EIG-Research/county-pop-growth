#!/usr/bin/env python3
"""PostToolUse hook: remind that a canonical edit needs `make brain-sync`.

Editing a canonical file under `Infrastructure/` leaves the generated adapter trees
stale until `make brain-sync` runs. Without this hook, the gap between "edited the
canonical file" and "discovered the drift" is however long it takes someone to run
`make brain-check` -- often not until CI, or not at all.

The reminder fires only for canonical surfaces that actually feed the generators, so
editing (say) a plan or a session log stays quiet. It fires once per session: the
message states a fact about the session ("sync before you commit"), and repeating it
after every file in a 40-file refactor is noise, not signal. CI (`make
maintenance-check`) is the backstop if the reminder is missed.

Dual-adapter, and advisory in both. Exits 0 always -- this hook must never
interfere with a completed edit.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

from hook_common import (
    candidate_paths,
    is_claude,
    is_shell_tool,
    project_and_cwd,
    relative_to_project,
    shell_mutates,
    tool_command,
)

# Canonical directories whose contents are mirrored into the adapter trees.
# Templates are read in place by both adapters, so a template edit needs no sync.
SYNCED_PREFIXES = (
    "Infrastructure/agents/",
    "Infrastructure/rules/",
    "Infrastructure/skills/",
    "Infrastructure/style/skills/",
    "Infrastructure/adapter_configs/",
)

MESSAGE = (
    "Canonical Infrastructure file changed ({paths}). Run `make brain-sync` before "
    "committing, then `make brain-check` to confirm zero drift -- canonical edits and "
    "their regenerated copies travel in the same commit. This reminder fires once per "
    "session."
)


def touched_canonical(payload: dict) -> list[str]:
    """Return the canonical repo-relative paths this event touched."""
    project, cwd = project_and_cwd(payload)
    hits = []
    for target in candidate_paths(payload):
        rel = relative_to_project(target, project)
        if rel is not None and rel.startswith(SYNCED_PREFIXES):
            hits.append(rel)
    if hits:
        return sorted(set(hits))

    # Shell mutations report no path; recognize them from the command text. Gated
    # on shell tools so a Write payload's *content* is never read as a command.
    if is_shell_tool(payload) and shell_mutates(
        tool_command(payload), SYNCED_PREFIXES, (), project, cwd
    ):
        return ["a canonical Infrastructure path named by a shell command"]
    return []


def already_reminded(payload: dict) -> bool:
    """True when this session has already been reminded. Marks it if not."""
    session_id = str(
        payload.get("session_id")
        or payload.get("sessionId")
        or payload.get("thread_id")
        or "unknown"
    )
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    marker = Path(tempfile.gettempdir()) / f"eig_template_brain_sync_reminder_{digest}"
    if marker.exists():
        return True
    try:
        marker.touch()
    except OSError:
        # Cannot dedupe without a marker; reminding twice beats staying silent.
        pass
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    hits = touched_canonical(payload)
    if not hits:
        return 0
    if already_reminded(payload):
        return 0

    message = MESSAGE.format(paths=", ".join(hits[:3]) + (" ..." if len(hits) > 3 else ""))

    # `additionalContext` is what reaches the model, in both adapters. Claude Code
    # shows `systemMessage` to the user only, so emitting just that (as this hook
    # once did) told the human to sync and never told the agent doing the edits.
    # The hook is registered on PostToolUse in both claude.settings.json and
    # codex.hooks.json, and hookEventName must name the event it runs on.
    output: dict = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        }
    }
    if is_claude(payload):
        output["systemMessage"] = message
    json.dump(output, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
