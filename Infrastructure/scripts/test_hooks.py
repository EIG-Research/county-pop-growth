#!/usr/bin/env python3
"""Fixture suite for the dual-adapter lifecycle hooks.

The three hooks under `Infrastructure/scripts/hooks/` are wired into *both*
`claude.settings.json` and `codex.hooks.json`. That makes every edit a
cross-adapter change: a fix motivated by Codex can silently regress Claude, and
neither failure shows up in `brain-check`, which only compares file contents.

This suite pins the behavior that matters, per adapter:

* the guard blocks generated paths, patch bodies, and shell mutations;
* the guard protects exactly the paths `.brain-manifest` lists, so a user's own
  agent, skill, or `.claude/settings.local.json` stays editable, and it falls back
  to the old prefix rules, saying so, when a checkout has no readable manifest;
* the guard leaves canonical files, project files, and read-only inspection alone;
* the guard judges shell paths by where they resolve: paths outside the project
  (`~/.claude/...`, other repositories, scratch copies) pass, and an agent
  worktree under `.claude/worktrees/` is judged against its own root;
* each adapter gets its own signalling contract (permission decision vs exit 2);
* the reminder fires for canonical edits, stays quiet elsewhere, dedupes, and
  reaches the model through `additionalContext`;
* the session-start hook reports the template-marker branch correctly, in both
  directions;
* the canonical Codex config and hooks definitions parse and stay wired;
* the Claude allowlist enumerates scripts, and the Codex execpolicy holds only
  prompt and forbidden rules whose examples agree with their patterns and with
  the Claude deny list.

Run directly, via `make maintenance-check` (registered as `hook-tests`), or via
`brain.py check`, which runs it as a named step.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS = REPO_ROOT / "Infrastructure" / "scripts" / "hooks"
ADAPTER_CONFIGS = REPO_ROOT / "Infrastructure" / "adapter_configs"

GUARD = HOOKS / "guard_generated_tree.py"
REMINDER = HOOKS / "remind_brain_sync.py"
SESSION = HOOKS / "session_context.py"

PATCH_HEADER = "*** " + "Update File:"

failures: list[str] = []
checks_run = 0

# The reminder dedupes via a per-session marker in the temp directory. Fixture
# sessions use synthetic ids, so without cleanup every run of this suite (including
# every CI run) leaves a fresh pile of marker files behind.
MARKER_PREFIX = "eig_template_brain_sync_reminder_"
fixture_sessions: set[str] = set()


def note_fixture_session(session_id: str) -> str:
    fixture_sessions.add(session_id)
    return session_id


def cleanup_fixture_markers() -> None:
    tmp = tempfile.gettempdir()
    for session_id in fixture_sessions:
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
        for path in glob.glob(os.path.join(tmp, f"{MARKER_PREFIX}{digest}")):
            try:
                os.unlink(path)
            except OSError:
                pass


def run_hook(
    script: Path, payload: dict, *, claude: bool, root: Path = REPO_ROOT
) -> tuple[int, str, str]:
    """Invoke a hook the way its adapter does.

    Claude sets CLAUDE_PROJECT_DIR and includes `hook_event_name`. Codex sets
    neither, so the hook must resolve the root by walking up to the git
    directory -- which is why cwd is the project root here.
    """
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.pop("CODEX_PROJECT_DIR", None)
    if claude:
        env["CLAUDE_PROJECT_DIR"] = str(root)
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(root),
        env=env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def expect(condition: bool, label: str, detail: str = "") -> None:
    global checks_run
    checks_run += 1
    if not condition:
        failures.append(f"{label}{': ' + detail if detail else ''}")


def edit_payload(path: str, *, claude: bool, session: str = "s1") -> dict:
    payload: dict[str, Any] = {
        "session_id": session,
        "cwd": str(REPO_ROOT),
        "tool_name": "Edit",
        "tool_input": {"file_path": path},
    }
    if claude:
        payload["hook_event_name"] = "PreToolUse"
    return payload


def bash_payload(command: str, *, claude: bool, session: str = "s1") -> dict:
    payload: dict[str, Any] = {
        "session_id": session,
        "cwd": str(REPO_ROOT),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    if claude:
        payload["hook_event_name"] = "PreToolUse"
    return payload


def patch_payload(target: str, *, claude: bool, session: str = "s1") -> dict:
    """A Codex apply_patch body, whose target appears only in the header."""
    payload: dict[str, Any] = {
        "session_id": session,
        "cwd": str(REPO_ROOT),
        "tool_name": "apply_patch",
        "tool_input": {
            "patch": (
                "*** Begin Patch\n"
                f"{PATCH_HEADER} {target}\n"
                "@@\n-old line\n+new line\n"
                "*** End Patch\n"
            )
        },
    }
    if claude:
        payload["hook_event_name"] = "PreToolUse"
    return payload


def write_payload(path: str, content: str, *, claude: bool) -> dict:
    """A Write whose *content* quotes commands and patch headers.

    This is the regression fixture for a false positive found while building this
    suite: scanning Write content as if it were a shell command line blocked any
    file that merely mentioned a generated path.
    """
    payload: dict[str, Any] = {
        "session_id": "write-content",
        "cwd": str(REPO_ROOT),
        "tool_name": "Write",
        "tool_input": {"file_path": path, "content": content},
    }
    if claude:
        payload["hook_event_name"] = "PreToolUse"
    return payload


def guard_blocked(
    payload: dict, *, claude: bool, root: Path = REPO_ROOT
) -> tuple[bool, str]:
    """True when the guard blocked, using each adapter's own contract."""
    code, out, err = run_hook(GUARD, payload, claude=claude, root=root)
    if claude:
        if code != 0:
            return False, f"Claude path must exit 0, got {code}"
        if not out.strip():
            return False, "no decision emitted"
        try:
            decision = json.loads(out)
        except json.JSONDecodeError:
            return False, f"stdout is not JSON: {out[:120]}"
        specific = decision.get("hookSpecificOutput", {})
        return specific.get("permissionDecision") == "deny", json.dumps(specific)[:200]
    return code == 2 and "BLOCKED" in err, f"exit={code} stderr={err[:120]}"


# --------------------------------------------------------------------------
# 1. The guard blocks generated surfaces, in both adapters.
# --------------------------------------------------------------------------
GENERATED_TARGETS = [
    ".claude/settings.json",
    ".claude/rules/r-coding-style-rules.md",
    ".claude/agents/code-reviewer.md",
    ".codex/config.toml",
    ".codex/agents/code-reviewer.toml",
    ".agents/skills/review-code/SKILL.md",
    ".claude/README.md",
    ".brain-manifest",
    # Case variants resolve to the generated file on macOS's case-insensitive disk.
    ".claude/agents/CODE-REVIEWER.md",
    ".claude/Agents/code-reviewer.md",
    ".claude/SETTINGS.json",
    ".codex/Config.toml",
]
for claude_mode in (True, False):
    adapter = "claude" if claude_mode else "codex"
    for target in GENERATED_TARGETS:
        ok, detail = guard_blocked(edit_payload(target, claude=claude_mode), claude=claude_mode)
        expect(ok, f"guard[{adapter}] must block generated path {target}", detail)

# --------------------------------------------------------------------------
# 2. The guard leaves everything else alone.
# --------------------------------------------------------------------------
ALLOWED_TARGETS = [
    "Infrastructure/agents/code-reviewer.md",
    "Infrastructure/adapter_configs/codex.config.toml",
    "Infrastructure/scripts/test_hooks.py",
    "README.md",
    "code/run_all.R",
    # The root instruction files are written by hand (Phase 2 Stage C3).
    "CLAUDE.md",
    "AGENTS.md",
    ".claude/settings.local.json",  # documented personal override
    # Files the manifest does not list are the user's, even inside the adapter trees.
    ".claude/agents/local.md",
    ".claude/skills/mine/SKILL.md",
    ".claude/rules/local-note.md",
    ".agents/skills/mine/SKILL.md",
    ".codex/agents/local.toml",
]
for claude_mode in (True, False):
    adapter = "claude" if claude_mode else "codex"
    for target in ALLOWED_TARGETS:
        ok, detail = guard_blocked(edit_payload(target, claude=claude_mode), claude=claude_mode)
        expect(not ok, f"guard[{adapter}] must allow {target}", detail)

# --------------------------------------------------------------------------
# 3. Codex patch bodies: the target exists only in a patch header. Earlier hook
#    logic could not see this payload shape at all.
# --------------------------------------------------------------------------
ok, detail = guard_blocked(patch_payload(".claude/settings.json", claude=False), claude=False)
expect(ok, "guard[codex] must block a patch header naming a generated file", detail)

ok, detail = guard_blocked(
    patch_payload("Infrastructure/agents/code-reviewer.md", claude=False), claude=False
)
expect(not ok, "guard[codex] must allow a patch header naming a canonical file", detail)

# W3 review: `*** Move to:` renames the updated file, so its destination is a target too.
move_payload = patch_payload("Infrastructure/agents/code-reviewer.md", claude=False)
move_payload["tool_input"]["patch"] = move_payload["tool_input"]["patch"].replace(
    "@@\n", "*** " + "Move to: .claude/agents/code-reviewer.md\n@@\n", 1
)
ok, detail = guard_blocked(move_payload, claude=False)
expect(ok, "guard[codex] must block a patch that moves a file onto a generated path", detail)
move_payload["tool_input"]["patch"] = move_payload["tool_input"]["patch"].replace(
    ".claude/agents/code-reviewer.md", "Infrastructure/agents/renamed.md"
)
ok, detail = guard_blocked(move_payload, claude=False)
expect(not ok, "guard[codex] must allow a patch that moves a canonical file", detail)

# --------------------------------------------------------------------------
# 4. Regression: file *content* is not a command. A canonical file whose text
#    quotes `rm -rf .codex/...` or a patch header must still be writable.
# --------------------------------------------------------------------------
DANGEROUS_LOOKING_CONTENT = (
    "Examples that must not trip the guard:\n"
    "    rm -rf .codex/agents\n"
    "    sed -i '' 's/a/b/' .claude/settings.json\n"
    "    cat > AGENTS.md\n"
    f"    {PATCH_HEADER} .claude/settings.json\n"
)
for claude_mode in (True, False):
    adapter = "claude" if claude_mode else "codex"
    ok, detail = guard_blocked(
        write_payload(
            "Infrastructure/scripts/test_hooks.py", DANGEROUS_LOOKING_CONTENT, claude=claude_mode
        ),
        claude=claude_mode,
    )
    expect(
        not ok,
        f"guard[{adapter}] must not read Write content as a shell command",
        detail,
    )
    # ...but the same content written *to* a generated path is still blocked,
    # because the decision comes from the target path.
    ok, detail = guard_blocked(
        write_payload(".claude/settings.json", DANGEROUS_LOOKING_CONTENT, claude=claude_mode),
        claude=claude_mode,
    )
    expect(ok, f"guard[{adapter}] must still block a Write to a generated path", detail)
    ok, detail = guard_blocked(
        write_payload(".claude/agents/CODE-REVIEWER.md", "x\n", claude=claude_mode), claude=claude_mode
    )
    expect(ok, f"guard[{adapter}] must block a Write to a case variant of a generated path", detail)

# --------------------------------------------------------------------------
# 5. Shell mutations. Neither adapter reports a path for these, so the guard must
#    derive the target from the command text; Bash must remain in the Claude matcher.
# --------------------------------------------------------------------------
MUTATING_COMMANDS = [
    "sed -i '' 's/a/b/' .claude/settings.json",
    "cat > .codex/hooks.json",
    "rm -rf .codex/agents",
    "printf 'x' >> .agents/skills/review-code/SKILL.md",
    "mv .claude/README.md .claude/README.md.bak",
    "touch .codex/config.toml",
    # A redirect target inside a generated tree, with output discarding elsewhere
    # in the same command -- the discard must not launder the real write.
    "echo x > .codex/config.toml 2>/dev/null",
    "cp Infrastructure/adapter_configs/codex.config.toml .codex/config.toml",
    "git checkout -- .claude/settings.json",
    # A quoted *path* must still be caught. This is why only message-flag
    # arguments are stripped, not every quoted string.
    'rm -rf ".codex/agents"',
    "sed -i '' 's/a/b/' '.claude/settings.json'",
    # A real mutation alongside a message flag elsewhere in the command.
    'git commit -m "wip" && rm -rf .codex/agents',
    # A mutating verb reached through a command-invoking token.
    "find . -name '*.toml' -exec rm {} \\; # .codex/agents",
    # `bash -c '<script>'` is a command line in one quoted word. Message stripping
    # once removed any quoted `-c` argument, which hid the whole script.
    "bash -c 'echo x > .claude/agents/code-reviewer.md'",
    'sh -c "rm -rf .codex/agents"',
    "bash -lc \"sed -i '' 's/a/b/' .claude/settings.json\"",
    "/bin/zsh -c 'cp x .codex/README.md'",
    # Options before `-c` must not hide the script.
    "bash -e -c 'rm .claude/agents/code-reviewer.md'",
    "bash --norc -c 'echo x > .claude/agents/code-reviewer.md'",
    "bash -euo pipefail -c 'rm -rf .codex/agents'",
    "bash --rcfile /dev/null -O extglob -c 'cp x .brain-manifest'",
    # A real mutation after a git message is still a mutation.
    "git commit -m x; echo x > .claude/settings.json",
    # The manifest itself, and the directories that hold generated files.
    "echo x > .brain-manifest",
    "git checkout HEAD~1 -- .brain-manifest",
    "cp mine.md .claude/agents/",
    "rm -rf .agents/skills/cite",
    # A glob or brace word that can reach a generated file.
    "rm .claude/agents/*.md",
    "rm -f .codex/agents/code-rev?ewer.toml",
    "rm .claude/agents/{code-reviewer,local}.md",
    # Case variants of generated paths (the same file on macOS).
    "rm .claude/Agents/code-reviewer.md",
    "echo x > .CODEX/config.toml",
    "rm .claude/agents/CODE-*.md",
    # W3 review: ordinary bulk-edit idioms the command-position and flag patterns missed.
    "sed -Ei 's/a/b/' .claude/agents/code-reviewer.md",
    "sed -ri 's/a/b/' .claude/agents/code-reviewer.md",
    "sed --in-place 's/a/b/' .claude/agents/code-reviewer.md",
    "perl -lpi -e 's/a/b/' .claude/agents/code-reviewer.md",
    "perl -0pi -e 's/a/b/' .claude/agents/code-reviewer.md",
    "echo x &> .claude/agents/code-reviewer.md",
    "echo x &>> .claude/agents/code-reviewer.md",
    "echo x >| .claude/agents/code-reviewer.md",
    "for f in .claude/agents/*.md; do sed -i 's/a/b/' \"$f\"; done",
    "if true; then rm .claude/agents/code-reviewer.md; fi",
    "{ rm .claude/agents/code-reviewer.md; }",
    "! rm .claude/agents/code-reviewer.md",
    "nohup rm .claude/agents/code-reviewer.md",
    "command rm .claude/agents/code-reviewer.md",
    "exec rm .claude/agents/code-reviewer.md",
    "/bin/rm .claude/agents/code-reviewer.md",
    "/usr/bin/sed -i '' 's/a/b/' .claude/settings.json",
    "find .claude -name '*.md' -delete",
    "find .claude/agents -name '*.md' -print0 | xargs -0 rm",
    "find .claude/agents -name '*.md' | xargs -I {} rm {}",
    "rsync -a /tmp/x/ .claude/agents/",
    "patch .claude/settings.json < fix.diff",
    "git mv .claude/agents/code-reviewer.md /tmp/x.md",
    "git apply --include=.claude/settings.json fix.diff",
    "git stash push -- .claude/settings.json",
    "git diff --output=.claude/settings.json HEAD",
    "git log -1 --output=.claude/agents/code-reviewer.md",
    # W3 round 2: quoted or escaped verbs, wrappers with options, git global options, and a
    # `case` arm.
    "\\rm .claude/agents/code-reviewer.md",
    "'rm' .claude/agents/code-reviewer.md",
    "\"sed\" -i '' 's/a/b/' .claude/settings.json",
    "sed \"-i\" 's/a/b/' .claude/settings.json",
    "env -i rm .claude/agents/code-reviewer.md",
    "sudo -u x rm .claude/agents/code-reviewer.md",
    "nice rm .claude/agents/code-reviewer.md",
    "nice -n 5 rm .claude/agents/code-reviewer.md",
    "timeout 5 rm .claude/agents/code-reviewer.md",
    "timeout -s KILL 5 rm .claude/agents/code-reviewer.md",
    "time rm .claude/agents/code-reviewer.md",
    "git -C . mv .claude/agents/code-reviewer.md /tmp/x.md",
    "git --no-pager mv .claude/agents/code-reviewer.md /tmp/x.md",
    "git -c core.autocrlf=false checkout -- .claude/settings.json",
    "case x in x) rm .claude/agents/code-reviewer.md;; esac",
    "curl -s --output .claude/settings.json https://example.org/x",
    # P4 walkthrough: a verb is judged by its own simple command, so these keep the wider
    # scope where the operands come from elsewhere: a subshell, a substitution, a variable,
    # a `cd`, a pipe, a loop over a read, or a file of names or a patch.
    "(rm .claude/agents/code-reviewer.md)",
    "echo $(rm .claude/agents/code-reviewer.md)",
    "f=.claude/agents/code-reviewer.md; rm \"$f\"",
    "cd .claude/agents && rm code-reviewer.md",
    "for f in .claude/agents/*.md\ndo\n  rm \"$f\"\ndone",
    "find .claude/agents -name '*.md' | while read f; do rm \"$f\"; done",
    "find .claude/agents -name '*.md' > /tmp/list; xargs rm < /tmp/list",
    "git diff .claude/settings.json > /tmp/d; git apply -R /tmp/d",
    "git diff .claude/settings.json | patch -R -p1",
    "ls .claude/agents > /tmp/l && rsync -a --files-from=/tmp/l /tmp/src/ .",
    # A verb at the start of a later line; the whole-line pattern has no newline anchor.
    "echo ok\nrm .claude/agents/code-reviewer.md",
    "echo 'a && b'; rm .claude/agents/code-reviewer.md",
    # W1-fix round 2: names read from a file an earlier command wrote, a tilde after `HOME=`,
    # and a git work tree set by an earlier command.
    "echo .claude/agents/code-reviewer.md > l; git checkout --pathspec-from-file=l",
    "echo .claude/agents/code-reviewer.md > l; git rm --pathspec-from-file=l",
    "echo .claude/agents/code-reviewer.md > l; git restore --pathspec-from-file=l",
    "echo .claude/agents/code-reviewer.md > l; git checkout-index -f --stdin < l",
    "HOME=.claude; rm ~/agents/code-reviewer.md",
    "export GIT_WORK_TREE=.claude/agents; git checkout -- code-reviewer.md",
    "GIT_WORK_TREE=.claude/agents; git checkout -- code-reviewer.md",
    "git config core.worktree .claude/agents; git checkout -- code-reviewer.md",
    # A verb after variable assignments is still in a command position.
    "GIT_WORK_TREE=.claude/agents git checkout -- code-reviewer.md",
    "true; x=1 rm .claude/agents/code-reviewer.md",
]
# The user's own files in the adapter trees: not in the manifest, so not blocked.
USER_OWNED_COMMANDS = [
    # The hand-written root instructions (Phase 2 Stage C3).
    "cat > AGENTS.md",
    "sed -i '' 's/a/b/' CLAUDE.md",
    "echo x > .claude/agents/local.md",
    "mkdir -p .claude/skills/mine && printf x > .claude/skills/mine/SKILL.md",
    "cp mine.md .claude/agents/local.md",
    "rm -f .claude/agents/local.md",
    "rm -rf .claude/skills/mine",
    "sed -i '' 's/a/b/' .codex/agents/local.toml",
    "bash -c 'echo x > .claude/agents/local.md'",
    "echo '{}' > .claude/settings.local.json",
]
READ_ONLY_COMMANDS = [
    "cat .claude/settings.json",
    "grep -rn 'review' .agents/skills",
    "ls -la .codex/agents",
    "diff .claude/rules/maintenance-rules.md Infrastructure/rules/maintenance-rules.md",
    "make brain-check",
    # Real-world shapes that an over-eager redirect signal blocked. Found by
    # running an ordinary read in a live session, not by the first fixture pass:
    # `2>` parsed as a mutating redirect, and the protected path elsewhere in the
    # command completed a false two-signal match.
    "ls .codex/agents 2>/dev/null",
    "ls /tmp/marker_* 2>/dev/null && echo found .codex/agents",
    "find .codex -type f 2>/dev/null | sort",
    "python3 -c \"import json; print(json.load(open('.codex/hooks.json'))['description'])\"",
    "wc -l .claude/rules/*.md 2>/dev/null",
    "make brain-check > /tmp/brain-check.log 2>&1",
    "git diff -- .codex/agents",
    "git log --oneline -3 -- .claude/settings.json",
    # A commit message that *describes* a mutation is not a mutation. Without the
    # message-argument strip, committing the fix for a guard bug is blocked by the
    # guard -- which is exactly how this case was found.
    'git commit -m "stop sed -i .claude/settings.json from bypassing the guard"',
    'git commit -q -m "fix: cat > AGENTS.md and rm -rf .codex/agents now blocked"',
    "git commit --message='describe rm -rf .codex/templates removal'",
    'git tag -m "notes about .claude/settings.json" v1',
    # Message stripping is limited to git, but still covers every message in it.
    "git commit -m \"guard: block bash -c 'echo x > .claude/agents/code-reviewer.md'\"",
    'git commit -q -m "first" -m "then rm -rf .codex/agents; done"',
    "bash -c 'ls .claude/agents'",
    "bash -euo pipefail -c 'ls .claude/agents'",
    # Every message body is stripped, not only the first. A quoted placeholder
    # once stopped the stripping after the first `-m`, so this was blocked.
    "git commit -m 'subj' -m 'body: echo > .claude/a' -m \"and: rm -rf .codex/agents\"",
    # W3: the wider in-place, redirect, and command-position patterns keep reads allowed.
    "sed -n '/-in/p' .claude/settings.json",
    "sed -n 's/-ri/x/p' .claude/settings.json",
    "perl -ne 'print if /x/' .claude/settings.json",
    "find .claude -name '*.md' -print",
    "ls .claude/agents &>/dev/null",
    "ls .claude/agents >/dev/null 2>&1",
    "for f in .claude/agents/*.md; do wc -l \"$f\"; done",
    "if [ -f .claude/settings.json ]; then cat .claude/settings.json; fi",
    "git stash list && git status --short .claude",
    "git log --oneline -- .claude/settings.json | head -3",
    'git commit -m "guard: block perl -0pi, echo &> and find -delete on .claude/agents"',
    # W3 round 2: an in-place flag after a pipe belongs to another command, and --output
    # writes only its own argument.
    "sed -n 1p .claude/settings.json | grep -i x",
    "perl -ne 'print' .claude/settings.json | sort -i",
    "sed -n 1p .claude/settings.json; ls -i .claude",
    "pandoc --output /tmp/x.html .claude/README.md",
    "pandoc --output=/tmp/x.html .claude/README.md",
    "git diff --output=/tmp/x.diff -- .claude/settings.json",
    "timeout 5 cat .claude/settings.json",
    "env -i ls .claude/agents",
    "git -C . log --oneline -- .claude/settings.json",
    # P4 walkthrough: a mutating verb in one simple command does not make a protected path
    # read by another its target.
    "mkdir -p review-reports && grep -n foo .claude/agents/code-reviewer.md",
    "mkdir -p /tmp/x; sed -n 1p .claude/settings.json",
    "touch /tmp/x || ls .codex/agents",
    "rm -f /tmp/a.txt\ncat .claude/settings.json",
]
for claude_mode in (True, False):
    adapter = "claude" if claude_mode else "codex"
    for command in MUTATING_COMMANDS:
        ok, detail = guard_blocked(bash_payload(command, claude=claude_mode), claude=claude_mode)
        expect(ok, f"guard[{adapter}] must block shell mutation: {command[:48]}", detail)
    for command in READ_ONLY_COMMANDS:
        ok, detail = guard_blocked(bash_payload(command, claude=claude_mode), claude=claude_mode)
        expect(
            not ok, f"guard[{adapter}] must allow read-only command: {command[:48]}", detail
        )
    for command in USER_OWNED_COMMANDS:
        ok, detail = guard_blocked(bash_payload(command, claude=claude_mode), claude=claude_mode)
        expect(not ok, f"guard[{adapter}] must allow a user-owned adapter file: {command[:48]}", detail)

# --------------------------------------------------------------------------
# 5b. Shell paths are judged by where they resolve, not by their spelling. The
#     guard once blocked `rm ~/.claude/...` and a `mkdir` in a scratch copy under
#     /tmp, because it substring-matched `.claude/` anywhere in the command.
# --------------------------------------------------------------------------
# Commands spell paths as a shell user would: forward slashes (on Windows `C:/...`, since an
# unquoted backslash is an escape in bash), plus, on Windows, the Git Bash `/c/...` form.
SCRATCH = (Path(tempfile.gettempdir()) / "eig-hook-fixture-scratch").as_posix()
ROOT = REPO_ROOT.as_posix()


def msys(path: str) -> str:
    """`C:/Users/x` as Git Bash spells it: `/c/Users/x`."""
    return f"/{path[0].lower()}{path[2:]}" if re.match(r"[A-Za-z]:/", path) else path


OUTSIDE_PROJECT_COMMANDS = [
    "rm -rf ~/.claude/cache-probe",
    "cp notes.txt ~/.codex/config.toml",
    f"mkdir -p {SCRATCH}/.claude/skills/probe",
    f"sed -i '' 's/a/b/' {SCRATCH}/other-repo/AGENTS.md",
    "rm -rf ../some-other-repo/.claude/agents",
    f"echo x > {SCRATCH}/.codex/config.toml",
    # Absolute operands still resolve after a `cd`.
    f"cd {SCRATCH} && rm -rf {SCRATCH}/.claude/agents",
]
IN_PROJECT_COMMANDS = [
    f"rm -rf {ROOT}/.codex/agents",
    f"cp notes.txt {ROOT}/.claude/settings.json",
    f"echo x >> {ROOT}/.claude/rules/r-coding-style-rules.md",
    "rm -rf .claude",
    "cp x --target-directory=.claude/agents",
    # A shell variable or a `cd` makes a relative operand unresolvable here, so
    # these keep the conservative substring behavior and stay blocked.
    'rm -rf "$PWD/.codex/agents"',
    f"cd {SCRATCH} && rm -rf .claude/agents",
]
if sys.platform == "win32":
    OUTSIDE_PROJECT_COMMANDS.append(f"rm -rf {msys(SCRATCH)}/.claude/agents")
    IN_PROJECT_COMMANDS += [f"rm -rf {msys(ROOT)}/.codex/agents",
                            f"cp notes.txt /cygdrive{msys(ROOT)}/.claude/settings.json"]
for claude_mode in (True, False):
    adapter = "claude" if claude_mode else "codex"
    for command in OUTSIDE_PROJECT_COMMANDS:
        ok, detail = guard_blocked(bash_payload(command, claude=claude_mode), claude=claude_mode)
        expect(
            not ok, f"guard[{adapter}] must allow a path outside the project: {command[:60]}", detail
        )
    for command in IN_PROJECT_COMMANDS:
        ok, detail = guard_blocked(bash_payload(command, claude=claude_mode), claude=claude_mode)
        expect(ok, f"guard[{adapter}] must block an in-project generated path: {command[:60]}", detail)

# --------------------------------------------------------------------------
# 5c. Agent worktrees. Claude Code creates them at `.claude/worktrees/<name>/`
#     inside the project, so measured from the outer root every path in one
#     starts with `.claude/`, and the guard blocked all work there. A nested
#     checkout is judged against its own root instead.
# --------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    outer = Path(tmp).resolve() / "project"
    worktree = outer / ".claude" / "worktrees" / "agent-probe"
    (outer / ".git").mkdir(parents=True)
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: ../../../.git/worktrees/agent-probe\n", encoding="utf-8", newline="\n")
    (outer / ".git" / "worktrees" / "agent-probe").mkdir(parents=True)

    def at(root: Path, rel: str) -> str:
        return str(root / rel)

    def fixture_edit(path: str, *, claude: bool, cwd: Path) -> dict:
        payload = edit_payload(path, claude=claude)
        payload["cwd"] = str(cwd)
        return payload

    def fixture_bash(command: str, *, claude: bool, cwd: Path) -> dict:
        payload = bash_payload(command, claude=claude)
        payload["cwd"] = str(cwd)
        return payload

    worktree_allowed = [
        at(worktree, "Infrastructure/scripts/hooks/hook_common.py"),
        at(worktree, "Infrastructure/adapter_configs/claude.settings.json"),
        at(worktree, "README.md"),
        at(worktree, "CLAUDE.md"),  # hand-written, so allowed even by the fallback rules
    ]
    worktree_blocked = [
        at(worktree, ".claude/agents/code-reviewer.md"),
        at(worktree, ".codex/config.toml"),
        at(worktree, ".brain-manifest"),
        at(outer, ".claude/agents/code-reviewer.md"),
    ]
    for claude_mode in (True, False):
        adapter = "claude" if claude_mode else "codex"
        # Claude may report the outer project in CLAUDE_PROJECT_DIR even for a
        # worktree session; Codex resolves the root from cwd. Exercise each pair.
        for root, cwd in ((outer, worktree), (worktree, worktree), (outer, outer)):
            label = f"root={root.name}, cwd={cwd.name}"
            # The project the hook protects: Claude's reported root, or for Codex
            # the checkout that contains cwd.
            effective = root if claude_mode else cwd
            for path in worktree_allowed:
                ok, detail = guard_blocked(
                    fixture_edit(path, claude=claude_mode, cwd=cwd), claude=claude_mode, root=root
                )
                expect(
                    not ok,
                    f"guard[{adapter}] must allow a canonical edit inside a worktree ({label}): "
                    f"{Path(path).relative_to(outer)}",
                    detail,
                )
            for path in worktree_blocked:
                if not Path(path).is_relative_to(effective):
                    continue  # outside the protected project: not its business
                ok, detail = guard_blocked(
                    fixture_edit(path, claude=claude_mode, cwd=cwd), claude=claude_mode, root=root
                )
                expect(
                    ok,
                    f"guard[{adapter}] must block a generated path ({label}): "
                    f"{Path(path).relative_to(outer)}",
                    detail,
                )

        for command, should_block in (
            (f"sed -i '' 's/a/b/' {worktree.as_posix()}/Infrastructure/scripts/hooks/hook_common.py", False),
            (f"cp a.md {worktree.as_posix()}/Infrastructure/rules/probe.md", False),
            ("sed -i '' 's/a/b/' Infrastructure/rules/probe.md", False),
            (f"rm -rf {worktree.as_posix()}/.codex/agents", True),
            ("rm -rf .claude/agents", True),
            (f"echo x > {worktree.as_posix()}/AGENTS.md", False),
            (f"echo x > {worktree.as_posix()}/.brain-manifest", True),
        ):
            ok, detail = guard_blocked(
                fixture_bash(command, claude=claude_mode, cwd=worktree),
                claude=claude_mode,
                root=outer,
            )
            verb = "block" if should_block else "allow"
            expect(
                ok == should_block,
                f"guard[{adapter}] must {verb} inside a worktree: {command[-60:]}",
                detail,
            )

# --------------------------------------------------------------------------
# 5d. A `.git` marker must not re-root the generated trees. Treating any
#     directory holding `.git` as a nested checkout let `git init .claude` (or a
#     stray `.git` in `.claude/agents/` or `.codex/`) unblock edits to them. Only a
#     worktree directly under `.claude/worktrees/`, whose `.git` file points into
#     this project's `.git/worktrees/`, counts.
# --------------------------------------------------------------------------
def fake_git_marker_cases(outer: Path) -> list[tuple[str, str, str]]:
    """(label, edit target, shell command) cases that must all stay blocked."""
    (outer / ".git").mkdir(parents=True)
    (outer / ".claude" / ".git").mkdir(parents=True)  # git init .claude
    (outer / ".claude" / "agents").mkdir(parents=True)
    (outer / ".claude" / "agents" / ".git").write_text(
        "gitdir: ../../.git/worktrees/agents\n", encoding="utf-8",
        newline="\n",
    )
    (outer / ".codex" / ".git").mkdir(parents=True)
    elsewhere = outer / ".claude" / "worktrees" / "elsewhere"
    elsewhere.mkdir(parents=True)
    (elsewhere / ".git").write_text(f"gitdir: {outer.parent}/other/.git/worktrees/x\n", encoding="utf-8", newline="\n")
    dir_marker = outer / ".claude" / "worktrees" / "dir-marker"
    (dir_marker / ".git").mkdir(parents=True)
    return [
        (".git dir in .claude", ".claude/agents/code-reviewer.md", "sed -i '' 's/a/b/' .claude/settings.json"),
        (".git file in .claude/agents", ".claude/agents/x.md", "rm -f .claude/agents/x.md"),
        (".git dir in .codex", ".codex/config.toml", "echo x > .codex/config.toml"),
        (
            "worktree whose gitdir points elsewhere",
            ".claude/worktrees/elsewhere/.claude/agents/x.md",
            "rm -rf .claude/worktrees/elsewhere/.codex/agents",
        ),
        (
            "worktree whose gitdir points elsewhere (canonical-looking path)",
            ".claude/worktrees/elsewhere/Infrastructure/x.py",
            "cp a .claude/worktrees/elsewhere/Infrastructure/x.py",
        ),
        (
            "worktree with a .git directory instead of a file",
            ".claude/worktrees/dir-marker/.claude/agents/x.md",
            "rm -f .claude/worktrees/dir-marker/.claude/agents/x.md",
        ),
    ]


with tempfile.TemporaryDirectory() as tmp:
    outer = Path(tmp).resolve() / "project"
    for label, target, command in fake_git_marker_cases(outer):
        for claude_mode in (True, False):
            adapter = "claude" if claude_mode else "codex"
            edit = edit_payload(str(outer / target), claude=claude_mode)
            edit["cwd"] = str(outer)
            ok, detail = guard_blocked(edit, claude=claude_mode, root=outer)
            expect(ok, f"guard[{adapter}] must block an edit despite a {label}", detail)
            shell = bash_payload(command, claude=claude_mode)
            shell["cwd"] = str(outer)
            ok, detail = guard_blocked(shell, claude=claude_mode, root=outer)
            expect(ok, f"guard[{adapter}] must block a shell write despite a {label}", detail)

# --------------------------------------------------------------------------
# 5e. The manifest decides. brain-sync records every generated file in
#     `.brain-manifest`, and the guard blocks exactly those paths (plus the
#     directories holding them). Without a readable manifest it falls back to the
#     old prefix rules and says so in the block message.
# --------------------------------------------------------------------------
sys.path.insert(0, str(HOOKS))
sys.path.insert(0, str(REPO_ROOT / "Infrastructure" / "scripts"))
import brain  # noqa: E402
import guard_generated_tree  # noqa: E402

expect(
    (guard_generated_tree.MANIFEST, guard_generated_tree.MANIFEST_HEADER)
    == (brain.MANIFEST, brain.MANIFEST_HEADER),
    "the guard and brain.py must agree on the manifest's name and header",
)
MANIFEST_HEADER = brain.MANIFEST_HEADER


def write_manifest(
    root: Path, paths: list[str], header: str = MANIFEST_HEADER, *, lists_itself: bool = True
) -> None:
    listed = sorted({*paths, ".brain-manifest"} if lists_itself else set(paths))
    (root / ".brain-manifest").write_text(
        header + "\n# fixture\n" + "".join(f"{p}\n" for p in listed), encoding="utf-8",
        newline="\n",
    )


def fixture_guard(root: Path, target: str, *, claude: bool, cwd: Path, shell: bool = False) -> tuple[bool, str]:
    """(blocked, the full block message) for an edit of `cwd/target`, or a shell command."""
    payload = bash_payload(target, claude=claude) if shell else edit_payload(str(cwd / target), claude=claude)
    payload["cwd"] = str(cwd)
    code, out, err = run_hook(GUARD, payload, claude=claude, root=root)
    if not claude:
        return code == 2 and "BLOCKED" in err, f"exit={code} {err}"
    try:
        specific = json.loads(out)["hookSpecificOutput"] if out.strip() else {}
    except (json.JSONDecodeError, KeyError):
        return False, f"stdout is not a decision: {out[:120]}"
    return code == 0 and specific.get("permissionDecision") == "deny", str(
        specific.get("permissionDecisionReason", "")
    )


with tempfile.TemporaryDirectory() as tmp:
    project = Path(tmp).resolve() / "project"
    (project / ".git").mkdir(parents=True)
    listed = [".claude/agents/code-reviewer.md", ".claude/settings.json", ".agents/skills/cite/SKILL.md",
              "CLAUDE.md"]
    states = {  # label -> (how to set up the manifest, the note the block message carries)
        "missing": (lambda: None, "is missing"),
        "not a manifest": (lambda: write_manifest(project, listed, header="# something else"),
                           "is not a brain-sync manifest"),
        "unreadable": (lambda: (project / ".brain-manifest").mkdir(), "could not be read"),
        # brain-sync always lists the manifest; a hand-written stub that does not is refused.
        "not listing itself": (lambda: write_manifest(project, ["x"], lists_itself=False),
                               "is not a brain-sync manifest"),
    }
    for label, (setup, note) in states.items():
        manifest = project / ".brain-manifest"
        if manifest.is_dir():
            manifest.rmdir()
        elif manifest.exists():
            manifest.unlink()
        setup()
        for claude_mode in (True, False):
            adapter = "claude" if claude_mode else "codex"
            for target in (".claude/agents/local.md", ".codex/agents/local.toml", ".brain-manifest"):
                ok, detail = fixture_guard(project, target, claude=claude_mode, cwd=project)
                expect(ok, f"guard[{adapter}] must fall back to the prefix rules ({label} manifest): {target}", detail)
                expect(note in detail and "fell back" in detail,
                       f"guard[{adapter}] must say why it fell back ({label})", detail[-300:])
            ok, detail = fixture_guard(project, "echo x > .claude/agents/local.md", claude=claude_mode,
                                       cwd=project, shell=True)
            expect(ok, f"guard[{adapter}] must fall back for a shell write ({label} manifest)", detail)
            ok, detail = fixture_guard(project, ".claude/settings.local.json", claude=claude_mode, cwd=project)
            expect(not ok, f"guard[{adapter}] must keep settings.local.json editable ({label} manifest)", detail)
            for target in ("AGENTS.md", "CLAUDE.md"):  # hand-written since Phase 2 Stage C3
                ok, detail = fixture_guard(project, target, claude=claude_mode, cwd=project)
                expect(not ok, f"guard[{adapter}] must keep {target} editable ({label} manifest)", detail)

    (project / ".brain-manifest").unlink()  # the last state left a stub there
    write_manifest(project, listed)

    # The chain a review found: delete the manifest, then Write a stub listing one stray
    # path, and every generated file becomes editable. Each link is now blocked.
    stub = f"{MANIFEST_HEADER}\nx\n"

    def write_manifest_blocked(*, claude: bool) -> tuple[bool, str]:
        payload = write_payload(str(project / ".brain-manifest"), stub, claude=claude)
        payload["cwd"] = str(project)
        code, out, err = run_hook(GUARD, payload, claude=claude, root=project)
        if not claude:
            return code == 2 and "BLOCKED" in err, f"exit={code} {err}"
        specific = json.loads(out)["hookSpecificOutput"] if out.strip() else {}
        return specific.get("permissionDecision") == "deny", str(specific.get("permissionDecisionReason", ""))

    for claude_mode in (True, False):
        adapter = "claude" if claude_mode else "codex"
        for command in ("unlink .brain-manifest", "git rm .brain-manifest", "git rm -q --cached .brain-manifest",
                        "rm -f .brain-manifest", "unlink .claude/agents/code-reviewer.md"):
            ok, detail = fixture_guard(project, command, claude=claude_mode, cwd=project, shell=True)
            expect(ok, f"guard[{adapter}] must block deleting a manifest path: {command}", detail)
        ok, detail = write_manifest_blocked(claude=claude_mode)
        expect(ok, f"guard[{adapter}] must block a Write over the manifest", detail)
    (project / ".brain-manifest").unlink()  # suppose it is gone anyway
    for claude_mode in (True, False):
        adapter = "claude" if claude_mode else "codex"
        ok, detail = write_manifest_blocked(claude=claude_mode)
        expect(ok and "is missing" in detail,
               f"guard[{adapter}] must block writing a new manifest once the old one is gone", detail[-200:])
    (project / ".brain-manifest").write_text(stub, encoding="utf-8", newline="\n")  # or the stub got written
    for claude_mode in (True, False):
        adapter = "claude" if claude_mode else "codex"
        for target in (".claude/agents/code-reviewer.md", ".claude/settings.json", ".brain-manifest"):
            ok, detail = fixture_guard(project, target, claude=claude_mode, cwd=project)
            expect(ok and "is not a brain-sync manifest" in detail,
                   f"guard[{adapter}] must treat a stub that does not list itself as no manifest: {target}",
                   detail[-200:])
    write_manifest(project, listed)
    for claude_mode in (True, False):
        adapter = "claude" if claude_mode else "codex"
        for target, should_block in (
            (".claude/agents/code-reviewer.md", True),
            (".claude/settings.json", True),
            (".agents/skills/cite/SKILL.md", True),
            ("CLAUDE.md", True),
            (".brain-manifest", True),  # always protected, listed or not
            (".claude/agents/local.md", False),
            (".agents/skills/cite/notes.md", False),
            ("AGENTS.md", False),  # not generated here, so not protected
            (".codex/config.toml", False),
        ):
            ok, detail = fixture_guard(project, target, claude=claude_mode, cwd=project)
            verb = "block" if should_block else "allow"
            expect(ok == should_block, f"guard[{adapter}] must {verb} {target} by the fixture manifest", detail)
            if should_block:
                expect("fell back" not in detail, f"guard[{adapter}] must not claim a fallback with a manifest", detail)

# --------------------------------------------------------------------------
# 5f. A real agent worktree is judged by its *own* manifest, not the outer
#     checkout's, and falls back on its own when it has none.
# --------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    outer = Path(tmp).resolve() / "project"
    (outer / ".git").mkdir(parents=True)
    worktrees = {}
    for name in ("agent-listed", "agent-bare"):
        tree = outer / ".claude" / "worktrees" / name
        tree.mkdir(parents=True)
        (tree / ".git").write_text(f"gitdir: ../../../.git/worktrees/{name}\n", encoding="utf-8", newline="\n")
        (outer / ".git" / "worktrees" / name).mkdir(parents=True)
        worktrees[name] = tree
    write_manifest(outer, [".claude/agents/code-reviewer.md", ".claude/agents/local.md", "CLAUDE.md"])
    write_manifest(worktrees["agent-listed"], [".claude/agents/code-reviewer.md", ".codex/config.toml"])
    listed_tree, bare_tree = worktrees["agent-listed"], worktrees["agent-bare"]
    for claude_mode in (True, False):
        adapter = "claude" if claude_mode else "codex"
        for root in ((outer, listed_tree) if claude_mode else (listed_tree,)):
            label = f"root={root.name}"
            for target, should_block in (
                (".claude/agents/code-reviewer.md", True),
                (".codex/config.toml", True),
                (".claude/agents/local.md", False),  # listed by the outer manifest only
                ("CLAUDE.md", False),
                ("Infrastructure/rules/probe.md", False),
            ):
                ok, detail = fixture_guard(root, target, claude=claude_mode, cwd=listed_tree)
                verb = "block" if should_block else "allow"
                expect(ok == should_block,
                       f"guard[{adapter}] must {verb} worktree {target} by its own manifest ({label})", detail)
            for command, should_block in (
                ("rm .claude/agents/code-reviewer.md", True),
                ("bash -c 'echo x > .codex/config.toml'", True),
                ("echo x > .claude/agents/local.md", False),
                (f"echo x > {listed_tree}/.claude/agents/local.md", False),
            ):
                ok, detail = fixture_guard(root, command, claude=claude_mode, cwd=listed_tree, shell=True)
                verb = "block" if should_block else "allow"
                expect(ok == should_block,
                       f"guard[{adapter}] must {verb} in a worktree by its manifest ({label}): {command[-50:]}", detail)
        if claude_mode:
            for target, should_block in ((".claude/agents/local.md", True), (".claude/agents/mine.md", False)):
                ok, detail = fixture_guard(outer, target, claude=True, cwd=outer)
                verb = "block" if should_block else "allow"
                expect(ok == should_block, f"guard[claude] must {verb} outer {target} by the outer manifest", detail)
            ok, detail = fixture_guard(outer, f"echo x > {outer}/.claude/agents/local.md", claude=True,
                                       cwd=listed_tree, shell=True)
            expect(ok, "guard[claude] must judge an outer path in a worktree command by the outer manifest", detail)
        for root in ((outer, bare_tree) if claude_mode else (bare_tree,)):
            ok, detail = fixture_guard(root, ".claude/agents/local.md", claude=claude_mode, cwd=bare_tree)
            expect(ok and "fell back" in detail,
                   f"guard[{adapter}] must fall back in a worktree without a manifest (root={root.name})", detail)

# --------------------------------------------------------------------------
# 5g. A fake `.git` must not re-root the generated trees under a manifest either:
#     a manifest planted in the fake root is never consulted.
# --------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    outer = Path(tmp).resolve() / "project"
    fake_git_marker_cases(outer)
    write_manifest(outer, [".claude/agents/code-reviewer.md", ".claude/agents/x.md", ".claude/settings.json",
                           ".codex/config.toml"])
    for fake_root in (outer / ".claude", outer / ".claude" / "agents", outer / ".codex"):
        write_manifest(fake_root, ["unrelated.md"])
    for label, target, command in (
        (".git dir in .claude", ".claude/agents/code-reviewer.md", "sed -i '' 's/a/b/' .claude/settings.json"),
        (".git file in .claude/agents", ".claude/agents/x.md", "rm -f .claude/agents/x.md"),
        (".git dir in .codex", ".codex/config.toml", "echo x > .codex/config.toml"),
    ):
        for claude_mode in (True, False):
            adapter = "claude" if claude_mode else "codex"
            ok, detail = fixture_guard(outer, target, claude=claude_mode, cwd=outer)
            expect(ok, f"guard[{adapter}] must block a manifest path despite a {label}", detail)
            ok, detail = fixture_guard(outer, command, claude=claude_mode, cwd=outer, shell=True)
            expect(ok, f"guard[{adapter}] must block a shell write to a manifest path despite a {label}", detail)


# Message stripping replaces every body with an unquoted placeholder.
from hook_common import strip_message_arguments  # noqa: E402

stripped = strip_message_arguments("git commit -m 'a' -m \"b > .claude/x\" -m 'c'")
expect(
    stripped == "git commit -m MSG -m MSG -m MSG",
    "every -m body must be stripped to a placeholder",
    stripped,
)

# --------------------------------------------------------------------------
# 6. The guard names the canonical source, which is the point of the message.
# --------------------------------------------------------------------------
_, out, _ = run_hook(GUARD, edit_payload(".claude/settings.json", claude=True), claude=True)
reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
expect(
    "Infrastructure/adapter_configs/claude.settings.json" in reason,
    "guard must name the canonical source for .claude/settings.json",
    reason[:200],
)
_, out, _ = run_hook(GUARD, edit_payload(".codex/agents/ai-skeptic.toml", claude=True), claude=True)
reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
expect(
    "Infrastructure/agents/ai-skeptic.md" in reason and "`codex:` frontmatter" in reason,
    "guard must name the canonical agent and its Codex frontmatter for a Codex agent wrapper",
    reason[:200],
)
_, out, _ = run_hook(
    GUARD, edit_payload(".claude/skills/review-code/SKILL.md", claude=True), claude=True
)
reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
expect(
    "Infrastructure/skills/review-code/SKILL.md" in reason,
    "guard must map a Claude workflow skill to its canonical workflow body",
    reason[:200],
)
_, out, _ = run_hook(
    GUARD, edit_payload(".claude/skills/idea-refine/references/examples.md", claude=True), claude=True
)
reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
expect(
    "Infrastructure/skills/idea-refine/references/examples.md" in reason,
    "guard must map a file beside a generated SKILL.md to the same canonical file",
    reason[:200],
)
_, out, _ = run_hook(
    GUARD, edit_payload(".agents/skills/eig-style-review/SKILL.md", claude=True), claude=True
)
reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
expect(
    "Infrastructure/style/skills/eig-style-review.md" in reason,
    "guard must map a generated dedicated skill to its canonical style skill",
    reason[:200],
)
# W3 review: the hint looked its candidates up relative to the hook's own working
# directory, so a session started in a subdirectory got the generic fallback text.
for rel_target, canonical in (
    (".claude/skills/idea-refine/references/examples.md",
     "Infrastructure/skills/idea-refine/references/examples.md"),
    (".agents/skills/eig-style-review/SKILL.md", "Infrastructure/style/skills/eig-style-review.md"),
):
    sub_payload = edit_payload(str(REPO_ROOT / rel_target), claude=True)
    sub_payload["cwd"] = str(REPO_ROOT / "Infrastructure")
    sub_env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "CODEX_PROJECT_DIR")}
    sub_env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, str(GUARD)], input=json.dumps(sub_payload), capture_output=True,
        text=True, cwd=str(REPO_ROOT / "Infrastructure"), env=sub_env, timeout=30,
    )
    reason = json.loads(proc.stdout or "{}").get("hookSpecificOutput", {}).get(
        "permissionDecisionReason", "")
    expect(
        f"\n    {canonical}\n" in reason,
        f"guard must name {canonical} when run from a subdirectory",
        reason[:200],
    )

# --------------------------------------------------------------------------
# 7. Malformed input is infrastructure failure, not a policy violation.
# --------------------------------------------------------------------------
for claude_mode in (True, False):
    adapter = "claude" if claude_mode else "codex"
    env = dict(os.environ)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if claude_mode:
        env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input="not json at all",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=30,
    )
    expect(
        proc.returncode == 0,
        f"guard[{adapter}] must not block on a malformed payload",
        f"exit={proc.returncode}",
    )


# --------------------------------------------------------------------------
# 8. The reminder: fires for canonical edits, quiet elsewhere, dedupes.
# --------------------------------------------------------------------------
def reminder_message(payload: dict, *, claude: bool) -> str:
    """Return the model-visible reminder text, checking the output contract.

    Both adapters read model-visible text from `hookSpecificOutput.additionalContext`.
    Claude Code shows `systemMessage` to the user only, so a reminder carried only
    there never reached the agent that needs to run the sync.
    """
    code, out, _ = run_hook(REMINDER, payload, claude=claude)
    if code != 0 or not out.strip():
        return ""
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return ""
    specific = data.get("hookSpecificOutput", {})
    adapter = "claude" if claude else "codex"
    expect(
        specific.get("hookEventName") == "PostToolUse",
        f"reminder[{adapter}] must name the PostToolUse event it is registered on",
        json.dumps(data)[:160],
    )
    return str(specific.get("additionalContext") or "")


for claude_mode in (True, False):
    adapter = "claude" if claude_mode else "codex"
    session = note_fixture_session(f"reminder-{adapter}-{uuid.uuid4().hex}")

    message = reminder_message(
        edit_payload(
            "Infrastructure/agents/code-reviewer.md", claude=claude_mode, session=session
        ),
        claude=claude_mode,
    )
    expect(
        "brain-sync" in message,
        f"reminder[{adapter}] must fire on a canonical agent edit (as additionalContext)",
        message[:120],
    )

    repeat = reminder_message(
        edit_payload(
            "Infrastructure/rules/maintenance-rules.md", claude=claude_mode, session=session
        ),
        claude=claude_mode,
    )
    expect(repeat == "", f"reminder[{adapter}] must fire only once per session", repeat[:120])

    fresh = reminder_message(
        edit_payload(
            "Infrastructure/rules/maintenance-rules.md",
            claude=claude_mode,
            session=note_fixture_session(f"{session}-b"),
        ),
        claude=claude_mode,
    )
    expect(
        "brain-sync" in fresh,
        f"reminder[{adapter}] must fire again in a new session",
        fresh[:120],
    )

    for quiet_target in (
        "records/plans/README.md",
        "records/session_logs/README.md",
        "code/run_all.R",
        "README.md",
    ):
        quiet = reminder_message(
            edit_payload(
                quiet_target,
                claude=claude_mode,
                session=note_fixture_session(f"{session}-{uuid.uuid4().hex}"),
            ),
            claude=claude_mode,
        )
        expect(
            quiet == "",
            f"reminder[{adapter}] must stay quiet for {quiet_target}",
            quiet[:120],
        )

    outside = reminder_message(
        bash_payload(
            "sed -i '' 's/a/b/' ../other-repo/Infrastructure/agents/x.md",
            claude=claude_mode,
            session=note_fixture_session(f"{session}-{uuid.uuid4().hex}"),
        ),
        claude=claude_mode,
    )
    expect(
        outside == "",
        f"reminder[{adapter}] must stay quiet for a canonical-looking path outside the project",
        outside[:120],
    )
    inside = reminder_message(
        bash_payload(
            "sed -i '' 's/a/b/' Infrastructure/agents/code-reviewer.md",
            claude=claude_mode,
            session=note_fixture_session(f"{session}-{uuid.uuid4().hex}"),
        ),
        claude=claude_mode,
    )
    expect(
        "brain-sync" in inside,
        f"reminder[{adapter}] must fire for a shell edit of a canonical file",
        inside[:120],
    )

# --------------------------------------------------------------------------
# 9. Session start, in both adapters.
# --------------------------------------------------------------------------
marker_present = (REPO_ROOT / "Infrastructure" / ".template-identity").is_file()

for claude_mode in (True, False):
    adapter = "claude" if claude_mode else "codex"
    session_payload: dict[str, Any] = {"cwd": str(REPO_ROOT), "source": "startup"}
    if claude_mode:
        session_payload["hook_event_name"] = "SessionStart"
    code, out, err = run_hook(SESSION, session_payload, claude=claude_mode)
    expect(code == 0, f"session[{adapter}] must exit 0", f"exit={code} stderr={err[:120]}")

    context = ""
    if claude_mode:
        try:
            context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        except (json.JSONDecodeError, KeyError) as exc:
            expect(False, f"session[{adapter}] must emit additionalContext", str(exc))
    else:
        expect(
            not out.lstrip().startswith("{"),
            f"session[{adapter}] must emit plain text, not a Claude decision object",
            out[:80],
        )
        context = out

    expect(
        "AGENTS.md, Start" in context,
        f"session[{adapter}] must cite the startup sequence in AGENTS.md",
        context[:120],
    )
    if marker_present:
        expect(
            "do NOT ask for a project title" in context,
            f"session[{adapter}] must suppress the title demand in the template repo",
            context[:200],
        )

# The marker branch is exercised against a synthetic checkout so it is tested in
# both directions, not only in whichever state this repository happens to be in.
with tempfile.TemporaryDirectory() as tmp:
    fake = Path(tmp) / "project"
    (fake / "records" / "plans").mkdir(parents=True)
    (fake / "records" / "session_logs").mkdir(parents=True)
    (fake / "Infrastructure").mkdir()
    (fake / ".git").mkdir()
    (fake / "PROJECT.md").write_text(
        "# Project Profile\n\n## Research Project Title\n\n- `TBD`\n", encoding="utf-8",
        newline="\n",
    )
    fake_env = dict(os.environ)
    fake_env["CLAUDE_PROJECT_DIR"] = str(fake)

    def fake_context() -> str:
        proc = subprocess.run(
            [sys.executable, str(SESSION)],
            input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(fake)}),
            capture_output=True,
            text=True,
            cwd=str(fake),
            env=fake_env,
            timeout=30,
        )
        return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]

    ctx = fake_context()
    expect(
        "NO RESEARCH PROJECT TITLE" in ctx,
        "session must demand a title in a real project (no template marker)",
        ctx[:200],
    )
    expect(
        "AGENTS.md (Start)" in ctx and "project-framing exception" in ctx and "GUARDRAILS" not in ctx,
        "the no-title message must name AGENTS.md and the project-framing exception, not the "
        "retired GUARDRAILS.md",
        ctx[:400],
    )

    (fake / "Infrastructure" / ".template-identity").write_text("marker\n", encoding="utf-8", newline="\n")
    ctx = fake_context()
    expect(
        "do NOT ask for a project title" in ctx,
        "session must suppress the title demand once the template marker exists",
        ctx[:200],
    )
    expect(
        "No plans on disk under records/plans/." in ctx
        and "No session logs on disk under records/session_logs/." in ctx,
        "session must report empty record folders under records/",
        ctx[-300:],
    )

    # The newest plan and log are found in records/ (Phase 2 Stage F), by dated filename,
    # with the folder README ignored and a leftover pre-move folder never consulted.
    for parts in (
        ("records", "plans", "README.md"),
        ("records", "plans", "2026-01-01_older-plan.md"),
        ("records", "plans", "2026-02-01_newer-plan.md"),
        ("records", "session_logs", "2026-01-05_older-log.md"),
        ("records", "session_logs", "2026-03-01_newer-log.md"),
        ("Infrastructure", "plans", "2026-12-31_pre-move-plan.md"),
        ("Infrastructure", "session_logs", "2026-12-31_pre-move-log.md"),
    ):
        target = fake.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {target.stem}\n", encoding="utf-8", newline="\n")
    ctx = fake_context()
    # Joined from parts, like the fixture files above: the internal path checker fails a
    # non-Markdown file that cites a dated record, and these are fixtures, not citations.
    expect(
        "Most recent plan: " + "/".join(("records", "plans", "2026-02-01_newer-plan.md")) in ctx,
        "session must name the newest plan under records/plans/",
        ctx[-400:],
    )
    expect(
        "Most recent session log: "
        + "/".join(("records", "session_logs", "2026-03-01_newer-log.md")) in ctx,
        "session must name the newest session log under records/session_logs/",
        ctx[-400:],
    )
    expect(
        "pre-move" not in ctx,
        "session must not read plans or logs from the retired Infrastructure/ record folders",
        ctx[-400:],
    )

# --------------------------------------------------------------------------
# 10. The canonical adapter configurations must parse and stay wired to the
#     scripts this suite exercises.
# --------------------------------------------------------------------------
try:
    with (ADAPTER_CONFIGS / "codex.config.toml").open("rb") as handle:
        codex_config = tomllib.load(handle)
    expect(
        codex_config.get("approval_policy") == "on-request",
        "codex.config.toml must set approval_policy = on-request",
        repr(codex_config.get("approval_policy")),
    )
    expect(
        codex_config.get("sandbox_mode") == "workspace-write",
        "codex.config.toml must set sandbox_mode = workspace-write",
        repr(codex_config.get("sandbox_mode")),
    )
    expect(
        codex_config.get("sandbox_workspace_write", {}).get("network_access") is False,
        "codex.config.toml must disable sandbox network access by default",
    )
    # Only keys verified in phase2-codex-facts.md and needed here. Hooks are on by
    # default, so `[features] hooks = true` was redundant and is gone.
    expect(
        set(codex_config) <= {"approval_policy", "sandbox_mode", "sandbox_workspace_write", "agents"},
        "codex.config.toml may set only its verified, needed keys",
        repr(sorted(codex_config)),
    )
    expect(
        codex_config.get("agents", {}).get("max_concurrent_threads_per_session", 0) >= 1,
        "codex.config.toml must allow concurrent reviewer threads",
    )
except (OSError, tomllib.TOMLDecodeError) as exc:
    expect(False, "codex.config.toml must parse", str(exc))

try:
    codex_hooks = json.loads((ADAPTER_CONFIGS / "codex.hooks.json").read_text(encoding="utf-8"))
    events = codex_hooks.get("hooks", {})
    for event, script in (
        ("PreToolUse", "guard_generated_tree.py"),
        ("PostToolUse", "remind_brain_sync.py"),
        ("SessionStart", "session_context.py"),
    ):
        entries = events.get(event) or []
        expect(script in json.dumps(entries), f"codex.hooks.json {event} must invoke {script}")
        # Windows is a first-class host for this template; a POSIX-only command
        # would silently disable the hook there.
        for matcher_entry in entries:
            for hook in matcher_entry.get("hooks", []):
                expect(
                    bool(hook.get("commandWindows")),
                    f"codex.hooks.json {event} hook must define commandWindows",
                )
except (OSError, json.JSONDecodeError) as exc:
    expect(False, "codex.hooks.json must parse", str(exc))

try:
    claude_settings = json.loads(
        (REPO_ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")  # hooks plus rendered permissions
    )
    pre_entries = claude_settings.get("hooks", {}).get("PreToolUse") or []
    matchers = [entry.get("matcher", "") for entry in pre_entries]
    expect(
        any("Bash" in matcher for matcher in matchers),
        "claude.settings.json PreToolUse must match Bash, or shell writes bypass the guard",
        repr(matchers),
    )
    expect(
        "remind_brain_sync.py"
        in json.dumps(claude_settings.get("hooks", {}).get("PostToolUse") or []),
        "claude.settings.json PostToolUse must invoke remind_brain_sync.py (its "
        "hookEventName depends on it)",
    )
    # The allowlist enumerates scripts. A glob such as
    # `Bash(python3 Infrastructure/scripts/*)` auto-approved template_reset.sh --yes,
    # the replication builder, and the port-opening servers.
    allow_rules = claude_settings.get("permissions", {}).get("allow") or []
    for rule in allow_rules:
        expect(
            not re.search(r"Infrastructure/(?:style/)?scripts/\*", rule),
            "the Claude allow list (permissions.yaml) must enumerate scripts, not glob a scripts directory",
            rule,
        )
        expect(
            not any(
                name in rule
                for name in (
                    "template_reset.sh",
                    "template-reset",  # `make template-reset ARGS=--yes` scrubs the records
                    "make *",  # a make glob would cover template-reset
                    "build_replication_package.sh",
                    "build_replication_package.py",
                    "review_board_server.py",
                    "war_room_server.py",
                    "sync_tokens.py --write",
                )
            ),
            "the Claude allow list (permissions.yaml) must not pre-approve destructive or port-opening scripts",
            rule,
        )

    claude_validators = {
        match.group(1)
        for rule in allow_rules
        if (match := re.fullmatch(r"Bash\(python3 (Infrastructure/\S+\.py) \*\)", rule))
    }
except (OSError, json.JSONDecodeError) as exc:
    expect(False, "claude.settings.json must parse", str(exc))
    claude_validators = set()

# The Codex execpolicy holds only `prompt` and `forbidden` rules: an `allow` rule
# runs its command outside the sandbox with no prompt. Codex validates every rule's
# `match` / `not_match` examples at load time, and one failure drops every project
# and user rule, so the examples are checked here against a prefix matcher that
# follows the execpolicy README (a pattern element may be a list of alternatives).
import ast  # noqa: E402
import shlex  # noqa: E402


def execpolicy_rules(text: str) -> list[dict]:
    """Each `prefix_rule(...)` call's keyword arguments, read as literals (never executed)."""
    rules = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "prefix_rule":
            rules.append({kw.arg: ast.literal_eval(kw.value) for kw in node.keywords})
    return rules


def prefix_matches(pattern: list, command: str) -> bool:
    words = shlex.split(command)
    return len(words) >= len(pattern) and all(
        word in (element if isinstance(element, list) else [element])
        for element, word in zip(pattern, words)
    )


def claude_allows(rule: str, command: str) -> bool:
    """Whether a Claude `Bash(...)` rule matches `command`.

    `*` matches any run of characters, spaces included, wherever it stands; a trailing
    ` *` also admits the bare command (`Bash(ls *)` matches `ls`). Anything else is exact.
    """
    body = rule[len("Bash("):-1] if rule.startswith("Bash(") and rule.endswith(")") else None
    if body is None:
        return False
    tail = ""
    if body.endswith(" *"):
        body, tail = body[:-2], r"(?: .*)?"
    pattern = ".*".join(re.escape(part) for part in body.split("*")) + tail
    return re.fullmatch(pattern, command, flags=re.DOTALL) is not None


try:
    execpolicy = (REPO_ROOT / ".codex" / "rules" / "template.rules").read_text(encoding="utf-8")
    rules = execpolicy_rules(execpolicy)
    expect(bool(rules), "the Codex execpolicy (permissions.yaml) must define rules")
    for rule in rules:
        label = " ".join(p if isinstance(p, str) else "|".join(p) for p in rule.get("pattern", []))
        expect(
            rule.get("decision") in {"prompt", "forbidden"},
            f"the Codex execpolicy (permissions.yaml) must set decision prompt or forbidden (no allow, no default): {label}",
            repr(rule.get("decision")),
        )
        expect(bool(rule.get("pattern")) and bool(rule.get("justification")),
               f"the Codex execpolicy (permissions.yaml) needs a pattern and a justification: {label}")
        expect(bool(rule.get("match")) and bool(rule.get("not_match")),
               f"the Codex execpolicy (permissions.yaml) needs match and not_match examples: {label}")
        for example in rule.get("match", []):
            expect(prefix_matches(rule["pattern"], example),
                   f"execpolicy match example must match its rule ({label}): {example}")
            expect(not any(claude_allows(allowed, example) for allowed in allow_rules),
                   f"the Claude allow list (permissions.yaml) must not pre-approve a command Codex prompts for or forbids: {example}")
        for example in rule.get("not_match", []):
            expect(not prefix_matches(rule["pattern"], example),
                   f"execpolicy not_match example must not match its rule ({label}): {example}")
    decisions = {tuple(map(str, r["pattern"])): r.get("decision") for r in rules if "pattern" in r}
    deny_rules = claude_settings.get("permissions", {}).get("deny") or []
    # One policy: every command Claude denies outright, Codex forbids: its literal prefix
    # is forbidden, or (for a rule such as `git push * --force*`, with no single command
    # to test) it matches a Codex-forbidden example.
    forbidden_examples = [ex for r in rules if r.get("decision") == "forbidden" for ex in r.get("match", [])]
    for denied in deny_rules:
        if not (denied.startswith("Bash(") and denied.endswith(")")):
            continue
        command = denied[len("Bash("):-1].rstrip("*").strip()
        expect(any(r.get("decision") == "forbidden" and prefix_matches(r["pattern"], command) for r in rules)
               or any(claude_allows(denied, ex) for ex in forbidden_examples),
               f"a command Claude denies (permissions.yaml) must be forbidden in the Codex execpolicy: {command}")
    # ...and the reverse for force-push: every form Codex forbids, Claude denies. Claude
    # once denied only `git push --force*` and `git push -f*`, so `git push origin --force`
    # ran with no prompt.
    for rule in rules:
        if rule.get("decision") == "forbidden" and rule.get("pattern", [])[:2] == ["git", "push"]:
            for example in rule.get("match", []):
                expect(any(claude_allows(d, example) for d in deny_rules),
                       f"the Claude deny list (permissions.yaml) must cover every force-push Codex forbids: {example}")
    for command in ("git push origin main", "git push -u origin feature", "git push --follow-tags"):
        expect(not any(claude_allows(d, command) for d in deny_rules),
               f"the Claude deny list (permissions.yaml) must not deny an ordinary push: {command}")

    # W3 review: an allow is only as narrow as what its `*` admits. `git diff*` admitted
    # `--output=<file>`, which overwrites a file, and `python3 code/*` admitted
    # `python3 code/../Infrastructure/...`. An ask or deny rule wins over an allow, so a
    # command is pre-approved only when an allow matches and neither of those does.
    ask_rules = claude_settings.get("permissions", {}).get("ask") or []

    def pre_approved(command: str) -> bool:
        return any(claude_allows(a, command) for a in allow_rules) and not any(
            claude_allows(r, command) for r in (*ask_rules, *deny_rules))

    escapes = []
    for rule in allow_rules:
        body = rule[len("Bash("):-1] if rule.startswith("Bash(") else ""
        if body.endswith("/*"):  # a path glob must not climb out of its directory
            escapes += [body[:-1] + "../Infrastructure/scripts/template_reset.sh --yes",
                        body[:-1] + "sub/../../Infrastructure/scripts/review_board_server.py"]
        if body.startswith("git ") and body.endswith("*"):  # read-only git must not write
            stem = body.rstrip("*").rstrip()
            escapes += [f"{stem} --output=.claude/settings.json", f"{stem} HEAD --output README.md"]
        # A `*` glued to a word admits a longer command: `git diff*` admitted
        # `git difftool -x '<cmd>'`, which runs any command. Write `git diff *` instead.
        expect(not re.search(r"[A-Za-z0-9]\*$", body),
               f"a Claude allow rule (permissions.yaml) must not glue `*` to a word: {rule}")
    escapes += ["git difftool -x 'touch /tmp/pwned' HEAD", "git difftool --extcmd=sh HEAD~1",
                "git showx", "git logx --all"]
    expect(bool(escapes), "the escape probes must find the path-glob and git allow rules")
    for command in escapes:
        expect(not pre_approved(command),
               f"the Claude allow list (permissions.yaml) must not pre-approve an escape (`..`, --output, difftool): {command}")
    for command in ("python3 code/run_all.py", "Rscript code/run_all.R", "git diff HEAD~1 -- code",
                    "git log --oneline -5", "git show HEAD:README.md", "git diff", "git log",
                    "git show", "git status", "git status --short", "git ls-files"):
        expect(pre_approved(command), f"an ordinary project run or read stays pre-approved: {command}")
    sync_write = [r for r in rules if prefix_matches(r["pattern"], "python3 Infrastructure/style/scripts/sync_tokens.py --write")]
    expect(
        [r.get("decision") for r in sync_write] == ["prompt"],
        "the Codex execpolicy (permissions.yaml) must prompt for sync_tokens.py --write",
    )
    expect(
        [r.get("decision") for r in rules if prefix_matches(r["pattern"], "latexmk -pdf main.tex")] == ["prompt"],
        "the Codex execpolicy (permissions.yaml) must prompt for latexmk (-e and -r run arbitrary Perl)",
    )
    # sync_tokens.py writes with --write, so the Claude allowlist may take only its
    # read-only forms.
    expect(
        "Infrastructure/style/scripts/sync_tokens.py" not in claude_validators,
        "the Claude allow list (permissions.yaml) may not allow sync_tokens.py with any arguments",
    )
    # The checker is a regression test of itself: a broken example must fail it.
    broken = execpolicy_rules('prefix_rule(pattern = ["git", "push"], decision = "prompt", match = ["git fetch"])')
    expect(not prefix_matches(broken[0]["pattern"], broken[0]["match"][0]),
           "the execpolicy example check must reject an example its pattern does not match")
except (OSError, SyntaxError, ValueError) as exc:
    expect(False, "the Codex execpolicy (permissions.yaml) must be readable literal Starlark", str(exc))

# --------------------------------------------------------------------------
# 11. The review write guard: a review agent writes only under review-reports/.
# It is declared in each review agent's own frontmatter (`hooks:`), so it runs
# only while that agent runs; the project under review may be any directory.
# --------------------------------------------------------------------------
REVIEW_GUARD = HOOKS / "guard_review_write.py"


def review_write_denied(payload: dict, *, claude: bool, root: Path) -> tuple[bool, str]:
    code, out, err = run_hook(REVIEW_GUARD, payload, claude=claude, root=root)
    if claude:
        try:
            specific = json.loads(out).get("hookSpecificOutput", {}) if out.strip() else {}
        except json.JSONDecodeError:
            return False, f"stdout is not JSON: {out[:120]}"
        return code == 0 and specific.get("permissionDecision") == "deny", f"exit={code} {out[:200]}"
    return code == 2 and "BLOCKED" in err, f"exit={code} stderr={err[:120]}"


with tempfile.TemporaryDirectory(prefix="review-guard-") as review_tmp:
    target = Path(review_tmp).resolve() / "wages-project"
    for sub in ("code", "drafts", "review-reports/_scratch", "data"):
        (target / sub).mkdir(parents=True, exist_ok=True)
    # Creating a symlink needs Developer Mode or elevation on Windows; without it the escape
    # probe is skipped (CI's Windows runner, an administrator, still exercises it).
    try:
        (target / "review-reports" / "escape").symlink_to(target / "code", target_is_directory=True)
        escape_probe = [("Write", "review-reports/escape/01_clean.R")]
    except OSError:
        escape_probe = []
        print("note: review-guard symlink-escape probe skipped: this account cannot create "
              "symlinks (Windows needs Developer Mode or an administrator)")

    def review_payload(tool: str, path: str, *, claude: bool) -> dict:
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        payload: dict[str, Any] = {"session_id": "review-guard", "cwd": str(target), "tool_name": tool,
                                   "tool_input": {key: path, "content": "x"}}
        if claude:
            payload["hook_event_name"] = "PreToolUse"
        return payload

    for claude in (True, False):
        adapter = "Claude" if claude else "Codex"
        for tool, path in (("Write", str(target / "code" / "01_clean.R")),
                           ("Edit", "drafts/note.md"),
                           ("Write", "PROJECT.md"),
                           ("NotebookEdit", str(target / "code" / "explore.ipynb")),
                           ("Write", "review-reports/../code/01_clean.R"),
                           *escape_probe,
                           ("Write", str(Path(review_tmp).resolve() / "elsewhere.json"))):
            denied, detail = review_write_denied(review_payload(tool, path, claude=claude), claude=claude,
                                                 root=target)
            expect(denied, f"[{adapter}] the review guard must deny {tool} outside review-reports/: {path}", detail)
        for tool, path in (("Write", "review-reports/code.findings.json"),
                           ("Write", str(target / "review-reports" / "index.html")),
                           ("Edit", "review-reports/methodology.findings.json"),
                           ("Write", "review-reports/_scratch/check_nobs.R")):
            code, out, err = run_hook(REVIEW_GUARD, review_payload(tool, path, claude=claude), claude=claude,
                                      root=target)
            expect(code == 0 and not out.strip(),
                   f"[{adapter}] the review guard must allow {tool} under review-reports/: {path}",
                   f"exit={code} out={out[:120]} err={err[:120]}")
        no_path = {"session_id": "review-guard", "cwd": str(target), "tool_name": "Write", "tool_input": {}}
        if claude:
            no_path["hook_event_name"] = "PreToolUse"
        denied, detail = review_write_denied(no_path, claude=claude, root=target)
        expect(denied, f"[{adapter}] the review guard must deny a write that names no path", detail)
    _, out, _ = run_hook(REVIEW_GUARD, review_payload("Write", "code/x.R", claude=True), claude=True, root=target)
    expect("review-contract.md" in out and "review-reports/_scratch/" in out,
           "the review guard's denial must say where writes go and cite the contract", out[:300])

# Every review agent declares the guard on Write|Edit|NotebookEdit in its frontmatter.
REVIEW_AGENTS = ("code-reviewer", "methodology-reviewer", "data-consistency-reviewer",
                 "conceptual-consistency-reviewer", "ai-skeptic")
try:
    import yaml  # noqa: E402  -- PyYAML, a declared dependency of brain.py
except ImportError:
    yaml = None
for agent in REVIEW_AGENTS if yaml else ():
    text = (REPO_ROOT / "Infrastructure" / "agents" / f"{agent}.md").read_text(encoding="utf-8")
    head = yaml.safe_load(text.split("---\n")[1]) if text.startswith("---\n") else {}
    pre = (head.get("hooks") or {}).get("PreToolUse") or []
    expect(any(entry.get("matcher") == "Write|Edit|NotebookEdit"
               and "hooks/guard_review_write.py" in str(entry.get("command")) for entry in pre),
           f"the review agent `{agent}` must declare the review write guard on Write|Edit|NotebookEdit",
           repr(head.get("hooks"))[:200])
    expect("Edit" not in (head.get("tools") or []), f"the review agent `{agent}` must not hold Edit",
           repr(head.get("tools")))

# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
cleanup_fixture_markers()

if failures:
    print(
        f"Hook fixture suite FAILED: {len(failures)} of {checks_run} check(s).", file=sys.stderr
    )
    for item in failures:
        print(f"- {item}", file=sys.stderr)
    raise SystemExit(1)

print(f"Hook fixture suite passed ({checks_run} checks across both adapters).")
