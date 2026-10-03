"""Shared payload parsing for Claude Code and Codex lifecycle hooks.

The three hooks in this directory are wired into *both* adapters:
`Infrastructure/adapter_configs/claude.settings.json` and
`Infrastructure/adapter_configs/codex.hooks.json`. The adapters describe the
same events differently, so all of that variation is isolated here rather than
repeated in each hook.

What differs between adapters:

* **Where the target path lives.** Claude passes `tool_input.file_path` (or
  `notebook_path`) for Edit/Write/NotebookEdit. Codex's `apply_patch` passes a
  patch body whose targets appear only as `*** Add|Update|Delete File:` and
  `*** Move to:` headers.
* **Bash / shell writes.** Neither adapter reports a `file_path` for a shell
  redirect or an in-place `sed`, so a mutation has to be recognized from the
  command text. This is the hole that let `sed -i .claude/settings.json` past the
  guard even in Claude, since the Claude matcher previously excluded Bash.
* **How to signal a block.** Claude reads a `permissionDecision` JSON object on
  stdout; Codex reads exit code 2 plus stderr. `is_claude()` picks the branch,
  and it fails toward *still blocking* if detection is ever wrong.

Every helper is deliberately conservative: a hook that crashes or guesses wrong
must never break legitimate work, so ambiguity resolves to "no opinion" —
except in the guard, where ambiguity resolves to "block", because a wrongly
blocked edit costs one retry and a wrongly allowed edit is silently reverted by
the next `make brain-sync`.
"""

from __future__ import annotations

import fnmatch
import os
import posixpath
import re
import shlex
from pathlib import Path
from typing import Callable, Iterable, Iterator, Tuple

# `*** Add File: path`, `*** Update File: path`, `*** Delete File: path`, and
# `*** Move to: path`, which renames the updated file onto that path.
PATCH_PATH_RE = re.compile(
    r"^\*\*\*\s+(?:(?:Add|Update|Delete)\s+File|Move\s+to):\s*(.+?)\s*$",
    flags=re.MULTILINE,
)

# A mutating *verb*: something that can create, overwrite, move, or delete files.
# When one of these appears, any protected path in the same simple command is
# treated as its target, because `rm -rf build .codex/agents` mutates both operands
# (`_mutation_scopes` says when a wider part of the command line counts).
#
# Every alternative is anchored to a command position -- start of line, after a
# separator, or after a command-invoking token like `-exec`/`xargs`. Unanchored
# `\bsed\b` matched the *word* "sed" wherever it appeared, including inside a
# commit message describing a fix.
# `\b` cannot precede `-exec`: a space and a hyphen are both non-word characters,
# so there is no boundary between them. Match the whitespace explicitly instead.
#
# A command position is also the word after a shell keyword or a command-running
# prefix (`do sed -i`, `then rm`, `{ rm`, `! rm`, `nohup rm`, `command rm`,
# `xargs -0 rm`), and the verb may carry a directory (`/bin/rm`).
# Wrappers that run a later word as the command, after options of their own
# (`env -i rm`, `sudo -u x rm`, `nice -n 5 rm`, `timeout -s KILL 5 rm`).
_WRAPPER = (
    r"(?:env|sudo|nice|timeout|time|nohup|command|builtin|exec)"
    r"(?:\s+(?:-\S+(?:\s+[^\s-]\S*)?|\d\S*|\w+=\S*))*"
)
# The verb may be quoted or escaped (`\rm`, `'rm'`, `"sed"`), which the shell removes.
# Variable assignments may precede the command (`x=1 rm`, `GIT_WORK_TREE=d git checkout`).
_COMMAND_POSITION = (
    r"(?:(?:^|[;&|()`{!]\s*)(?:[A-Za-z_]\w*=\S*\s+)*"
    r"|(?:^|\s)(?:-exec|-execdir|xargs(?:\s+(?:-\S+|\{\}))*|" + _WRAPPER
    + r"|do|then|else|elif)\s+)"
    r"[\\'\"]*(?:[\w.~-]*/)*"
)
# Git's global options before the subcommand (`git -C . mv`, `git --no-pager mv`).
_GIT = r"git[\"']?(?:\s+(?:-[Cc]\s+\S+|--?[\w-]+(?:=\S+)?))*\s+"
# An in-place flag, possibly quoted, after whitespace and within one command: `-i`, `-Ei`,
# `-ri`, `--in-place`, `-pi`, `-lpi`, `-0pi`. Whitespace keeps a `-i` inside a sed script
# (`'s/-ri/x/'`) out, and the bound keeps a flag after `|` or `;` (`| grep -i`) out.
_IN_PLACE = r"[^\n;|&]*?(?<=\s)[\"']?(?:--in-place|-[a-z0-9]*i)(?![a-z0-9])"
VERB_MUTATION_RE = re.compile(
    # Mutating utilities.
    _COMMAND_POSITION
    + r"(?:rm|unlink|mv|cp|touch|mkdir|rmdir|chmod|chown|ln|tee|truncate|install|dd|rsync"
    r"|patch)\b"
    # In-place editors.
    r"|" + _COMMAND_POSITION + r"sed[\"']?\s+" + _IN_PLACE
    + r"|" + _COMMAND_POSITION + r"perl[\"']?\s+" + _IN_PLACE
    # find's own deleter.
    + r"|" + _COMMAND_POSITION + r"find[\"']?\s+[^\n;|&]*?\s-delete\b"
    # Git commands that rewrite the working tree.
    r"|" + _COMMAND_POSITION + _GIT + r"(?:checkout|restore|clean|reset|rm|mv|apply"
    r"|stash(?!\s+(?:list|show)\b))\b",
    flags=re.IGNORECASE,
)

# An output-file option writes only its own argument (`git diff --output=<file>`,
# `curl --output <file>`), so that argument decides, as a redirect target does: pandoc
# with `--output /tmp/x.html` and a generated file as input only reads the generated file.
OUTPUT_TARGET_RE = re.compile(r"(?:^|\s)--output(?:=|\s+)[\"']?([^\s;|&()'\"]+)")

# Quoted arguments to message-carrying flags. A commit or tag message is prose,
# not a target list: `git commit -m "stop sed -i .claude/settings.json"` describes
# a mutation without performing one. Stripped before scanning.
#
# Deliberately narrow -- only the message flags, and only inside a git command.
# Stripping *all* quoted text would let `rm -rf ".codex/agents"` through, because
# the path itself is quoted there; stripping a quoted `-c` argument anywhere let
# `bash -c 'echo x > .claude/agents/a.md'` through, because the whole script is
# that argument.
MESSAGE_ARG_RE = re.compile(
    r"(\bgit\b[^;&|\n]*?(?:^|\s)"
    r"(?:-m|-am|-c|-C|--message|--message=|--squash-message=|--tag-message=)\s*)"
    r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')",
)

# Shells whose `-c <script>` argument is itself a command line to inspect.
INLINE_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}

# Redirection targets, captured so the *target* decides rather than the mere
# presence of a `>`. This precision matters: `ls .codex/agents 2>/dev/null` is a
# read, and an over-eager redirect signal blocked it -- discovered by live use,
# not by the first version of the fixtures. Excludes `>&` (fd duplication such as
# `2>&1`) and `<` (input redirection, which reads). Covers `&>` and `&>>` (stdout
# and stderr together) and `>|` (overwrite despite noclobber).
REDIRECT_TARGET_RE = re.compile(
    r"(?:(?<![<>&\d])\d?|(?<![<>&])&)>{1,2}\|?\s*(?![&(])([^\s;|&()]+)"
)

# Redirect targets that never mutate anything worth guarding.
DISCARD_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}

# Tools whose payload carries a patch body instead of a path. Deliberately does
# NOT include Claude's Edit/Write/MultiEdit: those always supply `file_path`, and
# scanning their *content* for patch headers produced false positives on any file
# that merely quotes a patch (this suite's own fixtures, for one).
PATCH_CAPABLE_TOOLS = {"apply_patch", "applyPatch", "apply-patch"}

# Tools whose payload carries a shell command line. Only these get the
# mutating-command scan; running it over Write/Edit content would block any file
# that happens to contain the text `rm -rf .codex/...`.
SHELL_TOOLS = {"Bash", "bash", "shell", "Shell", "local_shell", "exec", "run_command"}

# Tokens that change what a relative path in the rest of the command refers to
# (`cd elsewhere && rm -rf .claude/agents`, `git -C elsewhere checkout -- ...`).
# When one is present, relative operands cannot be resolved against the event's
# cwd, so they fall back to the conservative substring match.
DIRECTORY_CHANGERS = {"cd", "pushd", "popd", "-C"}
# Settings that move git's work tree or repository for the rest of the line
# (`export GIT_WORK_TREE=.claude/agents; git checkout -- x`), treated like a `cd`.
GIT_LOCATION_ASSIGNMENTS = ("GIT_DIR=", "GIT_WORK_TREE=", "GIT_INDEX_FILE=", "GIT_COMMON_DIR=")
GIT_LOCATION_SETTINGS = {"core.worktree", "core.bare"}


def _changes_directory(token: str) -> bool:
    """True when a shell word changes what later relative paths in the line refer to."""
    return (
        token in DIRECTORY_CHANGERS
        or token.startswith(GIT_LOCATION_ASSIGNMENTS)
        or token.casefold() in GIT_LOCATION_SETTINGS
    )


def find_project_root(start: Path) -> Path:
    """Return the nearest directory at or above `start` containing `.git`."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def project_and_cwd(payload: dict) -> Tuple[Path, Path]:
    """Resolve (repository root, event working directory).

    Claude sets `CLAUDE_PROJECT_DIR`. Codex hooks run from the session working
    directory and may set `CODEX_PROJECT_DIR`. When neither is present, walk up
    to the git root so relative paths in the payload still resolve correctly.
    """
    raw_cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    cwd = Path(raw_cwd).resolve()
    raw_project = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CODEX_PROJECT_DIR")
    project = Path(raw_project).resolve() if raw_project else find_project_root(cwd)
    return project, cwd


def is_claude(payload: dict) -> bool:
    """True when this looks like a Claude Code hook invocation.

    Used only to choose an output contract, never to decide whether to act. If
    this returns a false negative under Claude the guard still blocks — it just
    reports through exit code 2 and stderr instead of a permission decision.
    """
    return bool(payload.get("hook_event_name") or os.environ.get("CLAUDE_PROJECT_DIR"))


def tool_name(payload: dict) -> str:
    """Return the tool name across both adapters' spellings."""
    return str(payload.get("tool_name") or payload.get("toolName") or "")


def tool_command(payload: dict) -> str:
    """Return shell command text or a patch body, across spellings.

    Restricted to fields that genuinely hold a command or patch. `content` and
    `input` are excluded on purpose: those hold *file contents* for Write-style
    tools, and treating them as commands blocks any file that quotes one.
    """
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        return ""
    for field in ("command", "cmd", "patch"):
        value = tool_input.get(field)
        if isinstance(value, str) and value:
            return value
    return ""


def is_shell_tool(payload: dict) -> bool:
    """True when this event runs a shell command line rather than editing a path."""
    return tool_name(payload) in SHELL_TOOLS


def candidate_paths(payload: dict) -> Iterator[Path]:
    """Yield every filesystem target this event names, resolved absolutely.

    Covers the direct Claude path fields and the apply_patch header form. Shell
    mutations are handled separately by `shell_mutates()`, because a command
    line has no single unambiguous target.
    """
    _, cwd = project_and_cwd(payload)
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    tool_response = payload.get("tool_response") or {}

    raw_values = []
    if isinstance(tool_input, dict):
        raw_values += [tool_input.get("file_path"), tool_input.get("notebook_path")]
    if isinstance(tool_response, dict):
        raw_values.append(tool_response.get("filePath"))

    for raw in raw_values:
        if raw:
            target = Path(os.path.expanduser(str(raw)))
            yield target.resolve() if target.is_absolute() else (cwd / target).resolve()

    if tool_name(payload) in PATCH_CAPABLE_TOOLS:
        for raw in PATCH_PATH_RE.findall(tool_command(payload)):
            target = Path(os.path.expanduser(raw.strip()))
            yield target.resolve() if target.is_absolute() else (cwd / target).resolve()


def checkout_of(path: Path, project: Path) -> Tuple[Path, str] | None:
    """Return (checkout root, POSIX path relative to it) for the checkout that owns `path`.

    That is normally the project root. A nested checkout inside the project -- an
    agent worktree under `.claude/worktrees/<name>/`, which Claude Code creates
    there -- is its own checkout with its own generated trees and its own manifest,
    so a path inside it is judged against *that* root: `<worktree>/Infrastructure/x.py`
    is canonical and editable, while `<worktree>/.claude/agents/x.md` is judged by the
    worktree's manifest. Measured from the outer root, every worktree path started
    with `.claude/`, and the guard blocked all work inside worktrees.

    Returns None when the path is outside the project.
    """
    try:
        resolved = path.resolve()
        root = project.resolve()
        rel = resolved.relative_to(root)
    except (ValueError, OSError):
        return None
    for ancestor in (resolved, *resolved.parents):
        if ancestor == root:
            break
        if _is_agent_worktree(ancestor, root):
            return ancestor, resolved.relative_to(ancestor).as_posix()
    return root, rel.as_posix()


def relative_to_project(path: Path, project: Path) -> str | None:
    """Return `path` relative to the checkout that owns it (see `checkout_of`), or None."""
    owner = checkout_of(path, project)
    return owner[1] if owner else None


def _is_agent_worktree(candidate: Path, root: Path) -> bool:
    """True only for a real git worktree of this project at `.claude/worktrees/<name>/`.

    Any looser test is a bypass: treating every directory that holds a `.git` as a
    nested root let `git init .claude` (or a stray `.git` file in `.claude/agents/`
    or `.codex/`) re-root the generated trees and unblock edits to them. A worktree
    is recognized only when it sits directly under `.claude/worktrees/`, its `.git`
    is a *file*, and that file's `gitdir:` points inside this project's own
    `.git/worktrees/`.
    """
    if candidate.parent != root / ".claude" / "worktrees":
        return False
    marker = candidate / ".git"
    if not marker.is_file():
        return False
    try:
        first_line = marker.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeDecodeError, IndexError):
        return False
    if not first_line.startswith("gitdir:"):
        return False
    gitdir = Path(os.path.expanduser(first_line[len("gitdir:"):].strip()))
    if not gitdir.is_absolute():
        gitdir = candidate / gitdir
    try:
        gitdir.resolve().relative_to((root / ".git" / "worktrees").resolve())
    except (ValueError, OSError):
        return False
    return True


def _parents(rel: str) -> Iterator[str]:
    """Every proper ancestor directory of a relative path, excluding the root."""
    parts = rel.split("/")
    for depth in range(1, len(parts)):
        yield "/".join(parts[:depth])


class Protection:
    """What a hook protects in one checkout, in one of two shapes.

    * `from_manifest`: exact paths. Each listed file is protected, and so is each
      directory that holds one, because `rm -rf .claude/agents` removes the listed
      files inside it. Anything else -- `.claude/agents/local.md`, a user's own skill,
      `.claude/settings.local.json` -- is not.
    * `from_rules`: whole trees plus exact root files, the prefix rules the guard used
      before the manifest existed and still uses when a checkout has none.

    Three questions are asked of it: `covers` a resolved relative path; `named_in`,
    the conservative substring test for a shell word that cannot be resolved; and
    `mentioned`, a cheap filter before resolving a word at all.

    Every comparison ignores case. On macOS's default case-insensitive file system
    `.claude/Agents/CODE-REVIEWER.md` is the generated file, so matching exact case
    would let it through; the cost is over-blocking a case variant on Linux.
    """

    def __init__(
        self,
        files: Iterable[str],
        trees: Iterable[str],
        patterns: Iterable[str],
        mentions: Iterable[str],
        note: str = "",
    ) -> None:
        self.files = frozenset(posixpath.normpath(f).casefold() for f in files)
        self.trees = tuple(t.rstrip("/").casefold() for t in trees)
        self.dirs = frozenset(d for f in self.files for d in _parents(f))
        self.patterns = tuple(re.compile(p, re.IGNORECASE) for p in patterns)
        self.mentions = tuple(m.casefold() for m in mentions)
        self.note = note  # why this is a fallback; empty for a manifest

    @classmethod
    def from_manifest(cls, paths: Iterable[str]) -> "Protection":
        paths = {posixpath.normpath(p) for p in paths}
        tops = sorted({p.split("/", 1)[0] for p in paths})
        return cls(
            paths,
            (),
            (rf"(?:^|[/\s'\"]){re.escape(top)}(?:$|[/\s'\"])" for top in tops),
            tops,
        )

    @classmethod
    def from_rules(
        cls, prefixes: Iterable[str], files: Iterable[str], note: str = ""
    ) -> "Protection":
        prefixes, files = tuple(prefixes), tuple(files)
        return cls(
            files,
            prefixes,
            (rf"(?:^|[/\s'\"]){re.escape(name)}(?:$|[\s'\"])" for name in files),
            (*(p.rstrip("/") for p in prefixes), *files),
            note,
        )

    def covers(self, rel: str, *, pattern: bool = False) -> bool:
        """True when a checkout-relative path is protected.

        With `pattern`, a shell glob (`.claude/agents/*.md`) is protected when it
        can match a protected file or directory.
        """
        rel = posixpath.normpath(rel).casefold()
        if rel in self.files or rel in self.dirs:
            return True
        if any(rel == tree or rel.startswith(tree + "/") for tree in self.trees):
            return True
        if pattern and GLOB_CHARACTERS & set(rel):
            return any(fnmatch.fnmatchcase(p, rel) for p in (*self.files, *self.dirs))
        return False

    def named_in(self, text: str) -> bool:
        """True when `text` names a protected tree or top-level entry anywhere in it.

        A plain substring match, with no idea where the named path is. Used only as
        the conservative fallback when a path cannot be resolved (see
        `_token_protected`).
        """
        normalized = text.replace("\\", "/").casefold()
        if any(tree + "/" in normalized for tree in self.trees):
            return True
        return any(pattern.search(normalized) for pattern in self.patterns)

    def mentioned(self, text: str) -> bool:
        folded = text.casefold()
        return any(name in folded for name in self.mentions)


# Characters that make a shell word a glob pattern rather than a literal path.
GLOB_CHARACTERS = set("*?[")


def _shell_tokens(command: str) -> list[str] | None:
    """Split a command line into words and operators; None if it cannot be parsed."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        # `#` stays part of the scan: a protected path after it is still treated
        # as named, which is the conservative reading.
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def _command_segments(command: str) -> list[tuple[str, int]] | None:
    """Split a command line into simple commands, each tagged with its pipeline number.

    Splits on `&&`, `||`, `;`, `|`, and newlines outside quotes and backslash escapes.
    A `|` keeps the pipeline number, so the commands of one pipeline share it; every
    other separator starts a new one. `>|` is a redirect, not a pipe. Returns None when
    a quote is left open, so the caller falls back to judging the whole command.
    """
    segments: list[tuple[str, int]] = []
    current: list[str] = []
    pipeline = 0
    quote = ""
    index, length = 0, len(command)

    def flush(next_pipeline: int) -> None:
        nonlocal current, pipeline
        segments.append(("".join(current).strip(), pipeline))
        current, pipeline = [], next_pipeline

    while index < length:
        char = command[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < length:
                current.append(command[index : index + 2])
                index += 2
                continue
            current.append(char)
            if char == quote:
                quote = ""
            index += 1
            continue
        if char == "\\" and index + 1 < length:
            current.append(command[index : index + 2])
            index += 2
            continue
        if char in "'\"`":
            quote = char
            current.append(char)
            index += 1
            continue
        pair = command[index : index + 2]
        if pair in ("&&", "||"):
            flush(pipeline + 1)
            index += 2
            continue
        if char in ";\n":
            flush(pipeline + 1)
            index += 1
            continue
        if char == "|" and not (index and command[index - 1] == ">"):
            flush(pipeline)
            index += 2 if pair == "|&" else 1
            continue
        current.append(char)
        index += 1
    if quote:
        return None
    flush(pipeline)
    return [(text, number) for text, number in segments if text]


# Signs that a simple command takes its operands from outside its own words: a shell
# expansion (a loop or other variable, a command substitution, a tilde after `HOME=`), or
# a verb that reads names or a patch from stdin or from a file an earlier command may have
# written (`xargs`, `read`, `patch`, `git apply`, `rsync --files-from`,
# `git checkout --pathspec-from-file`, `git checkout-index --stdin`, an input redirect).
# For such a command the whole command line counts.
_INDIRECT_OPERANDS_RE = re.compile(
    r"[$`~]|--files-from|--pathspec-from-file|--stdin\b|(?:^|\s)\d?<(?![<(])"
    r"|(?:^|[\s;&|(){}!])[\\'\"]*(?:xargs|read|readarray|mapfile|parallel|patch|apply)(?![\w-])",
    flags=re.IGNORECASE,
)


def _mutation_scopes(command: str, tokens: list[str], ambiguous: bool) -> list[list[str]]:
    """Return the words each mutating verb in `command` may act on.

    A verb's targets are the words of its own simple command, so the `mkdir` in
    `mkdir -p out && grep x .claude/agents/a.md` does not make the protected path
    its target. A wider scope applies, conservatively, where a command's operands
    can come from elsewhere in the line:

    * the upstream commands of its pipeline (`find .claude | xargs rm`,
      `git diff .claude/x | patch -R`), because a pipe carries data forward;
    * the whole command line when the command's operands are indirect
      (`_INDIRECT_OPERANDS_RE`, as in the loop body of
      `for f in .claude/agents/*; do rm "$f"; done`), when a `cd` or `-C` makes
      relative paths depend on an earlier command (`ambiguous`), when the line
      cannot be split, or when the verb is seen only in the whole line.

    Each command is also checked on its own, which catches a verb that starts a
    new line (`echo ok` newline `rm .claude/x`); the whole-line pattern has no
    newline anchor.
    """
    segments = _command_segments(command)
    whole_line_verb = bool(VERB_MUTATION_RE.search(command))
    if segments is None:
        return [tokens] if whole_line_verb else []
    if not whole_line_verb and not any(VERB_MUTATION_RE.search(text) for text, _ in segments):
        return []
    if ambiguous:
        return [tokens]
    scopes: list[list[str]] = []
    for position, (text, pipeline) in enumerate(segments):
        if not VERB_MUTATION_RE.search(text):
            continue
        if _INDIRECT_OPERANDS_RE.search(text):
            return [tokens]
        upstream = [part for part, number in segments[: position + 1] if number == pipeline]
        scope = _shell_tokens(" ".join(upstream))
        if scope is None:
            return [tokens]
        scopes.append(scope)
    return scopes or [tokens]


ProtectionFor = Callable[[Path], Protection]


_MSYS_DRIVE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?=/|$)")


def native_drive_path(text: str) -> str:
    """On Windows, turn a Git Bash (MSYS) `/c/...` or Cygwin `/cygdrive/c/...` path into
    `C:/...`. Python would read `/c/Users` as `C:\\c\\Users`, so an operand spelled the way
    Git Bash users type it would otherwise resolve outside the project and be allowed."""
    if os.name != "nt":
        return text
    converted = _MSYS_DRIVE.sub(lambda m: m.group(1).upper() + ":", text)
    return converted + "/" if re.fullmatch(r"[A-Z]:", converted) else converted


def _token_protected(
    token: str,
    event: Protection,
    protection_for: ProtectionFor,
    project: Path,
    cwd: Path,
    *,
    ambiguous: bool,
    cwd_protected: bool,
) -> bool:
    """True when one shell word names a protected path inside the project.

    The word is resolved against the event's cwd and then judged by where it
    lands, against the protection of the checkout it lands in, so `~/.claude/...`,
    another repository's `.codex/`, or a scratch copy under `/tmp` are left alone,
    while `.claude/agents` or an absolute path to a generated file of this project
    (or of a nested agent worktree, by that worktree's own manifest) are caught. A
    word whose meaning depends on the shell -- a variable, a command substitution,
    a brace expansion, or any relative path after a `cd` -- cannot be resolved
    here and falls back to the substring match of the event's checkout (`event`).
    """
    normalized = token.replace("\\", "/")
    if not cwd_protected and not event.mentioned(normalized):
        return False

    candidates = [normalized]
    if "=" in normalized:
        # `--out=.claude/x`, `of=.codex/y`: the operand follows the `=`.
        candidates.append(normalized.split("=", 1)[1])

    for candidate in candidates:
        if not candidate:
            continue
        candidate = native_drive_path(candidate)
        if "$" in candidate or "`" in candidate or "{" in candidate:
            if event.named_in(candidate):
                return True
            continue
        expanded = os.path.expanduser(candidate)
        if os.path.isabs(expanded):
            owner = checkout_of(Path(expanded), project)
        elif ambiguous:
            if event.named_in(candidate):
                return True
            continue
        else:
            owner = checkout_of(cwd / expanded, project)
        if owner is not None and protection_for(owner[0]).covers(owner[1], pattern=True):
            return True
    return False


def strip_message_arguments(command: str) -> str:
    """Remove quoted `-m`/`--message` argument bodies from a command line.

    A commit message that *describes* a mutation is not a mutation. Without this,
    committing the fix for a guard bug is blocked by the guard.
    """
    # One substitution per pass, so a second `-m` in the same git command is
    # found once the first message body has been removed. The placeholder must
    # be unquoted: a quoted `""` is itself a message the pattern matches, so the
    # text stopped changing after the first `-m` and later bodies were never
    # stripped.
    for _ in range(32):
        stripped = MESSAGE_ARG_RE.sub(lambda match: match.group(1) + "MSG", command, count=1)
        if stripped == command:
            break
        command = stripped
    return command


# Shell options that consume the following word, so it is not the script.
SHELL_LONG_OPTIONS_WITH_ARG = {"--rcfile", "--init-file"}
SHELL_SHORT_OPTIONS_WITH_ARG = {"o", "O"}


def _inline_shell_scripts(tokens: list[str]) -> list[str]:
    """Return the script bodies of `bash -c '...'`-style invocations in `tokens`.

    Options may come before `-c` (`bash -e -c`, `bash --norc -c`,
    `bash -euo pipefail -c`), so walk forward over them: short clusters led by
    `-` or `+` (where `o` and `O` take the next word), `--rcfile`/`--init-file`
    and their argument, and any other `--long` flag. When a short cluster holds
    `c`, the first non-option word after the options is the script.
    """
    scripts = []
    for index, token in enumerate(tokens):
        if os.path.basename(token) not in INLINE_SHELLS:
            continue
        position = index + 1
        wants_script = False
        while position < len(tokens):
            option = tokens[position]
            if option == "--":
                position += 1
                break
            if option in SHELL_LONG_OPTIONS_WITH_ARG:
                position += 2
                continue
            if option.startswith("--"):
                position += 1
                continue
            if len(option) > 1 and option[0] in "-+" and option[1:].isalpha():
                letters = option[1:]
                if option[0] == "-" and "c" in letters:
                    wants_script = True
                position += 1 + sum(letter in SHELL_SHORT_OPTIONS_WITH_ARG for letter in letters)
                continue
            break
        if wants_script and position < len(tokens):
            scripts.append(tokens[position])
    return scripts


def shell_mutates(
    command: str,
    prefixes: Iterable[str] = (),
    files: Iterable[str] = (),
    project: Path | None = None,
    cwd: Path | None = None,
    *,
    protection_for: ProtectionFor | None = None,
) -> bool:
    """True when `command` would mutate a protected surface of `project`.

    Two independent signals, both narrow on purpose:

    * a mutating verb (`rm`, `mv`, `sed -i`, `git checkout`, ...) in a command
      position, combined with a protected path in the same simple command, or in
      the wider part of the line its operands can come from (`_mutation_scopes`);
    * a redirection whose *target* is a protected path.

    A verb that names no path (`git checkout .`, `git stash`) is judged by its own
    command, as it would be run alone, so a protected path read elsewhere in the line
    does not make it block.

    Read-only inspection is never blocked, and neither is discarding output:
    `ls .codex/agents 2>/dev/null` names a protected path but redirects only to
    /dev/null and uses no mutating verb. Message arguments are stripped first, so
    prose describing a mutation is not mistaken for one.

    What is protected comes from `protection_for(checkout root)` when given (the
    guard passes its manifest reader), and otherwise from `prefixes` and `files`
    in every checkout. A "protected path" is one that resolves to a protected
    path of the checkout it lands in (see `_token_protected`). Without `project`
    and `cwd`, or when the command cannot be tokenized, this falls back to a
    substring match on the whole command, which also blocked commands on paths
    outside the repository such as `rm ~/.claude/...`.
    """
    if not command:
        return False

    if protection_for is None:
        fixed = Protection.from_rules(prefixes, files)
        protection_for = lambda _root: fixed  # noqa: E731
    command = strip_message_arguments(command)

    tokens = _shell_tokens(command) if project is not None and cwd is not None else None
    if tokens is None:
        words = [command]
        event = protection_for(project) if project is not None else Protection.from_rules(prefixes, files)

        def protected(text: str) -> bool:
            return event.named_in(text)

    else:
        words = tokens
        ambiguous = any(_changes_directory(token) for token in tokens)
        cwd_owner = checkout_of(cwd, project)
        event = protection_for(cwd_owner[0] if cwd_owner else project)
        cwd_protected = cwd_owner is not None and event.covers(cwd_owner[1])

        def protected(text: str) -> bool:
            return _token_protected(
                text,
                event,
                protection_for,
                project,
                cwd,
                ambiguous=ambiguous,
                cwd_protected=cwd_protected,
            )

    if tokens is None:
        scopes = [words] if VERB_MUTATION_RE.search(command) else []
    else:
        scopes = _mutation_scopes(command, tokens, ambiguous)
    if any(protected(word) for scope in scopes for word in scope):
        return True

    # `bash -c '<script>'` runs a command line held in one quoted word; inspect it
    # as a command in its own right.
    if tokens is not None:
        for script in _inline_shell_scripts(tokens):
            if shell_mutates(script, prefixes, files, project, cwd, protection_for=protection_for):
                return True

    for target in [*REDIRECT_TARGET_RE.findall(command), *OUTPUT_TARGET_RE.findall(command)]:
        cleaned = target.strip().strip("'\"")
        if cleaned in DISCARD_TARGETS:
            continue
        if protected(cleaned):
            return True

    return False
