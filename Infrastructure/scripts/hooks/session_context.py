#!/usr/bin/env python3
"""SessionStart hook: inject project state so session recovery is mechanical.

`AGENTS.md` (Start) says to read PROJECT.md and, when resuming work, the newest plan
and the newest session log, then state your understanding. That sequence previously
depended on the model remembering to follow it. This hook front-loads the three facts it
needs.

It also enforces the repository's one hard precondition: AGENTS.md requires a PROJECT.md
title before substantive work. If the title is missing, the injected context says so
loudly rather than leaving it to be noticed later.

Dual-adapter. Claude reads an `additionalContext` object on stdout; Codex takes the
hook's stdout directly. Exits 0 always -- a failure here must not block the session
from starting.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from hook_common import is_claude, project_and_cwd

MAX_EXCERPT_LINES = 12


# Placeholder values that mean "not filled in yet". `# Project Profile` is the
# template's own permanent heading, not a project title -- the real title lives in
# the `## Research Project Title` section below it.
UNFILLED = {"tbd", "todo", "n/a", "none", "", "project profile"}

NO_TITLE = (
    "PROJECT.md has NO RESEARCH PROJECT TITLE (still the `TBD` placeholder). Per "
    "AGENTS.md (Start), ask for the project title and pause other substantive work until "
    "it is provided, unless the user is still framing the project under the bounded "
    "project-framing exception in AGENTS.md (Guardrails)."
)

# In the template repository itself, a `TBD` title is the correct shipped state, so the
# blocking warning above is noise on every maintenance session. `Infrastructure/.template-identity`
# distinguishes the two cases, and `make template-reset` -- step 1 of porting into a new
# project -- deletes it, which re-arms the warning exactly when it starts mattering.
TEMPLATE_MARKER_REL = "Infrastructure/.template-identity"

TEMPLATE_NO_TITLE = (
    "Template repository (`Infrastructure/.template-identity` present). The PROJECT.md "
    "title is intentionally `TBD` here — do NOT ask for a project title, and do not treat "
    "it as blocking; template maintenance is the expected work. When porting into a real "
    "project, `make template-reset` removes the marker and re-enables the title requirement."
)


def is_template_repo(root: Path) -> bool:
    """True when this checkout is the template itself, not a project derived from it."""
    return (root / TEMPLATE_MARKER_REL).is_file()


def project_title(root: Path) -> tuple[str | None, str]:
    """Return (title, status_line) for PROJECT.md.

    The title is the body of the `## Research Project Title` section -- the one hard
    precondition in AGENTS.md. The file's `# Project Profile` heading is template
    furniture and is never the title.

    An unset title reports as blocking in a real project and as an expected, non-blocking
    condition in the template repository.
    """
    unset_message = TEMPLATE_NO_TITLE if is_template_repo(root) else NO_TITLE

    path = root / "PROJECT.md"
    if not path.is_file():
        return None, "PROJECT.md is missing."

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, "PROJECT.md could not be read."

    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            in_section = heading == "research project title"
            continue
        if not in_section or not stripped:
            continue
        # Section body is a bullet, often wrapped in backticks: - `TBD`
        candidate = stripped.lstrip("-*").strip().strip("`").strip()
        if candidate.lower() in UNFILLED or candidate.startswith("["):
            return None, unset_message
        return candidate, f"PROJECT.md research title: {candidate}"

    return None, unset_message


def newest(directory: Path) -> Path | None:
    """Newest dated Markdown file in a directory, by filename then mtime."""
    if not directory.is_dir():
        return None
    candidates = [
        p
        for p in directory.glob("*.md")
        if p.is_file() and p.name.upper() not in {"README.MD"}
    ]
    if not candidates:
        return None
    dated = [p for p in candidates if re.match(r"^\d{4}-\d{2}-\d{2}", p.name)]
    pool = dated or candidates
    return max(pool, key=lambda p: (p.name, p.stat().st_mtime))


def excerpt(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "    (unreadable)"
    head = [ln for ln in lines[:40] if ln.strip()][:MAX_EXCERPT_LINES]
    return "\n".join(f"    {ln}" for ln in head)


def main() -> int:
    # Codex pipes a payload; Claude pipes a payload and also sets
    # CLAUDE_PROJECT_DIR. Read tolerantly -- an empty or malformed payload still
    # resolves the root by walking up to the git directory.
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    root, _ = project_and_cwd(payload)

    sections: list[str] = []
    _, status = project_title(root)
    sections.append(status)

    plan = newest(root / "records" / "plans")
    if plan is not None:
        rel = plan.relative_to(root).as_posix()
        sections.append(f"Most recent plan: {rel}\n{excerpt(plan)}")
    else:
        sections.append("No plans on disk under records/plans/.")

    log = newest(root / "records" / "session_logs")
    if log is not None:
        rel = log.relative_to(root).as_posix()
        sections.append(f"Most recent session log: {rel}")
    else:
        sections.append("No session logs on disk under records/session_logs/.")

    context = (
        "Repository state at session start (injected by the SessionStart hook; see "
        "AGENTS.md, Start):\n\n"
        + "\n\n".join(sections)
    )

    if is_claude(payload):
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                },
                "suppressOutput": True,
            },
            sys.stdout,
        )
    else:
        # Codex adds the hook's stdout to the session context directly.
        sys.stdout.write(context + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
