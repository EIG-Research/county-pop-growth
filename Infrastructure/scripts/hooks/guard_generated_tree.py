#!/usr/bin/env python3
"""PreToolUse hook: refuse edits to generated adapter files.

The repository's first governance rule is "never hand-edit generated copies".
`make brain-sync` produces them from canonical sources under `Infrastructure/`
and records each one in the committed manifest `.brain-manifest` at the checkout
root. Until this hook existed that rule was enforced only by prose and by a
post-hoc `make brain-check`, which catches the violation after the fact and only
if someone runs it.

This hook enforces it at the moment of the edit, and -- more usefully -- names the
canonical file the author actually wanted.

What it protects is exactly the manifest: every listed file, the manifest itself,
and each directory holding a listed file (so `rm -rf .claude/agents` is blocked).
Anything else under `.claude/`, `.codex/`, or `.agents/` -- a user's own agent or
skill, or `.claude/settings.local.json` -- is theirs, sync never touches it, and
this hook allows it. Each checkout is judged by its own manifest, so a real agent
worktree under `.claude/worktrees/<name>/` uses the worktree's copy. When a
checkout's manifest is missing, unreadable, or not a manifest, the hook fails safe
to the rules it used before the manifest existed -- everything under the three
adapter trees plus the manifest itself, except settings.local.json -- and says so
in the block message. The root `CLAUDE.md` and `AGENTS.md` are written by hand
(Phase 2 Stage C3), so they are not protected in either mode. A manifest that does not
list itself was not written by brain-sync and counts as not a manifest.

Dual-adapter. It is wired into both `claude.settings.json` and
`codex.hooks.json`, and covers three ways an edit can arrive:

1. A direct path (`tool_input.file_path` / `notebook_path`) -- Claude's
   Edit/Write/NotebookEdit.
2. An `apply_patch` body, where targets appear only as `*** Update File:` headers
   -- Codex's primary edit tool.
3. A shell mutation naming a generated surface (`sed -i .claude/...`,
   `cat > .codex/config.toml`). Neither adapter reports a path for these, so the command
   text is inspected. Read-only inspection of a generated tree is never blocked.

Limits: this is accident prevention, not a sandbox. The shell scan knows the
ordinary edit idioms -- mutating utilities in any command position (after `;`,
`)`, `do`, `then`, `{`, `!`, `xargs`, or a wrapper with its options such as
`env -i`, `sudo -u x`, `nice`, `timeout 5`; quoted or escaped, as `\rm`; or with a
directory, as `/bin/rm`), in-place `sed` and `perl` flag clusters, `find -delete`,
`rsync`, `patch`, working-tree git commands after git's global options, and the
target of `--output`, `>`, `>>`, `&>`, and `>|`. It does not see a write made by an interpreter (`python3 -c
"open(...,'w')"`), a glob that hides the protected name (`.cl*/agents`), or a
path built at run time; `make brain-check` catches whatever gets through.

Blocking convention differs by adapter: Claude reads a `permissionDecision`
object on stdout, Codex reads exit code 2 plus stderr. Both are emitted, and if
adapter detection is ever wrong the fallback still blocks.
"""

from __future__ import annotations

import functools
import json
import posixpath
import re
import sys
from pathlib import Path

from hook_common import (
    Protection,
    candidate_paths,
    checkout_of,
    is_claude,
    is_shell_tool,
    project_and_cwd,
    shell_mutates,
    tool_command,
)

# The ownership record written by `brain.py sync`. Both values repeat
# `MANIFEST` and `MANIFEST_HEADER` in Infrastructure/scripts/brain.py, and
# test_hooks.py fails if they differ.
MANIFEST = ".brain-manifest"
MANIFEST_HEADER = "# brain-manifest v1"

# The fail-safe rules for a checkout without a readable manifest: the prefix rules
# the guard used before the manifest existed. Every path in these trees is blocked.
FALLBACK_DIRS = (".claude/", ".codex/", ".agents/")
# The manifest is among them: without it, deleting and rewriting it would reopen every file.
# The root CLAUDE.md and AGENTS.md are hand-written, so they are not.
FALLBACK_FILES = (MANIFEST,)

# Paths that are never generated and stay editable even under the fallback rules.
# settings.local.json is the documented place for personal, uncommitted overrides.
EXEMPT = (
    ".claude/settings.local.json",
    ".claude/settings.local.json.bak",
)


@functools.lru_cache(maxsize=None)
def protection_for(root: Path) -> Protection:
    """What is protected in the checkout at `root`: its manifest, or the fallback."""
    path = root / MANIFEST
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        problem = f"`{MANIFEST}` is missing"
    except (OSError, UnicodeDecodeError) as exc:
        problem = f"`{MANIFEST}` could not be read ({exc.__class__.__name__})"
    else:
        paths = {line for line in lines[1:] if line and not line.startswith("#")}
        # brain-sync always lists the manifest itself; one that does not was not written
        # by it (`# brain-manifest v1` plus one stray line would otherwise unprotect all).
        if lines and lines[0] == MANIFEST_HEADER and MANIFEST in paths:
            return Protection.from_manifest(paths)
        problem = f"`{MANIFEST}` is not a brain-sync manifest"
    note = (
        f"{problem} in {root}, so the guard fell back to protecting everything under "
        f".claude/, .codex/, and .agents/, plus {MANIFEST}. Run "
        f"`make brain-sync` to write the manifest; the guard then protects exactly "
        f"the generated files."
    )
    return Protection.from_rules(FALLBACK_DIRS, FALLBACK_FILES, note)


# Exact generated path -> canonical source. Checked before the directory rules.
EXACT_CANONICAL = {
    ".claude/README.md": "Infrastructure/adapter_configs/claude.README.md",
    ".codex/README.md": "Infrastructure/adapter_configs/codex.README.md",
    ".claude/settings.json": (
        "Infrastructure/adapter_configs/claude.settings.json (permissions: "
        "Infrastructure/adapter_configs/permissions.yaml)"
    ),
    ".codex/config.toml": "Infrastructure/adapter_configs/codex.config.toml",
    ".codex/hooks.json": "Infrastructure/adapter_configs/codex.hooks.json",
    ".codex/rules/template.rules": "Infrastructure/adapter_configs/permissions.yaml",
    MANIFEST: (
        "none -- `make brain-sync` writes it from the generated set; edit the "
        "canonical sources that decide what is generated"
    ),
}

# Direct Markdown mirrors. Claude-only: Codex reads native surfaces plus the
# canonical Infrastructure files on demand, so `.codex/` has no Markdown mirror.
MIRRORED_PARTS = ("agents", "rules")


def canonical_for(rel: str, root: Path) -> str:
    """Best-effort canonical source path for a generated path of the checkout at `root`.

    Candidates are looked up under `root`, not the hook's working directory, which is
    wherever the session started.
    """
    if rel in EXACT_CANONICAL:
        return EXACT_CANONICAL[rel]

    parts = rel.split("/")

    # .codex/agents/<name>.toml is generated from the agent file's frontmatter.
    if len(parts) == 3 and parts[0] == ".codex" and parts[1] == "agents" and parts[2].endswith(".toml"):
        name = parts[2][: -len(".toml")]
        return f"Infrastructure/agents/{name}.md (its `codex:` frontmatter)"

    # .codex/rules/<name>.rules is generated from the canonical command policy.
    if len(parts) == 3 and parts[0] == ".codex" and parts[1] == "rules" and parts[2].endswith(".rules"):
        return "Infrastructure/adapter_configs/permissions.yaml"

    # <adapter>/<part>/<name>.md -- Claude mirrors only.
    if len(parts) == 3 and parts[0] == ".claude" and parts[1] in MIRRORED_PARTS:
        return f"Infrastructure/{parts[1]}/{parts[2]}"

    # <adapter>/skills/<name>/... -- canonical lives in one of two skill roots. A file
    # beside SKILL.md (a workflow's references/, say) is copied from the same place.
    if len(parts) >= 3 and parts[1] == "skills":
        name = parts[2]
        beside = "/".join(parts[3:])
        if beside and beside != "SKILL.md" and (root / "Infrastructure/skills" / name / beside).is_file():
            return f"Infrastructure/skills/{name}/{beside}"
        for base in ("Infrastructure/skills", "Infrastructure/style/skills"):
            structured = f"{base}/{name}/SKILL.md"
            flat = f"{base}/{name}.md"
            if (root / structured).is_file():
                return structured
            if (root / flat).is_file():
                return flat
        return (
            f"Infrastructure/skills/{name}/SKILL.md or "
            f"Infrastructure/style/skills/{name}.md"
        )

    return "the matching file under Infrastructure/"


def blocked_target(payload: dict) -> tuple[str, Protection, Path] | None:
    """Return (the generated path this event would modify, the protection that says so,
    the root of the checkout it belongs to)."""
    project, cwd = project_and_cwd(payload)

    for target in candidate_paths(payload):
        owner = checkout_of(target, project)
        if owner is None:
            continue
        root, rel = owner[0], posixpath.normpath(owner[1])
        if rel.casefold() in {e.casefold() for e in EXEMPT}:
            continue
        protection = protection_for(root)
        if protection.covers(rel):
            return rel, protection, root

    # Shell mutations report no path, so inspect the command text -- but only for
    # tools that actually run a command line. Scanning a Write payload's content
    # would block any file that merely quotes `rm -rf .codex/...`, including this
    # repo's own hook fixtures.
    if is_shell_tool(payload):
        command = tool_command(payload)
        for exempt in EXEMPT:
            command = re.sub(re.escape(exempt), "", command, flags=re.IGNORECASE)
        if shell_mutates(command, project=project, cwd=cwd, protection_for=protection_for):
            owner = checkout_of(cwd, project)
            root = owner[0] if owner else project
            return (
                "a generated adapter surface named by this shell command",
                protection_for(root),
                root,
            )

    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        # Malformed input is hook infrastructure failure, not a policy violation, so the
        # event is allowed; say so, because an allow here is otherwise invisible (a Windows
        # path with unescaped backslashes is invalid JSON).
        sys.stderr.write("guard_generated_tree: the hook payload is not valid JSON; this "
                         "event was not checked\n")
        return 0
    if not isinstance(payload, dict):
        return 0

    blocked = blocked_target(payload)
    if blocked is None:
        return 0
    rel, protection, root = blocked

    reason = (
        f"`{rel}` is a generated file and must not be hand-edited.\n\n"
        f"Edit the canonical source instead:\n    {canonical_for(rel, root)}\n\n"
        f"Then regenerate:\n    make brain-sync\n\n"
        f"Verify:\n    make brain-check\n\n"
        f"(Hand-editing a generated copy is reverted by the next brain-sync and is "
        f"reported as drift by brain-check. See AGENTS.md, "
        f"'Canonical Sources'. Files `{MANIFEST}` does not list, such as your own "
        f"agents and skills, are not blocked.)"
    )
    if protection.note:
        reason += f"\n\nNote: {protection.note}"

    if is_claude(payload):
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            },
            sys.stdout,
        )
        return 0

    # Codex (and any adapter this does not recognize) blocks on exit code 2 with
    # the explanation on stderr.
    sys.stderr.write(f"BLOCKED: {reason}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
