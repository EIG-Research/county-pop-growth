#!/usr/bin/env python3
"""Fixture suite for brain.py: sync, check, manifest ownership, metadata errors, and the lints.

Every case runs against a throwaway copy of this repository's tracked and unignored files in a
temporary directory, committed to a fresh git repository there, so the real checkout is never touched.
It needs git and PyYAML, makes no network calls, and finishes in well under a minute. Run it
directly, through `make maintenance-check` (`brain-tests`), or through `brain.py check`.
The cases never run the real suites through `brain.py check`, which would recurse into this
file; the suites case swaps in stubs.

    test_brain.py --parity [BASE [HEAD]]   (default: main HEAD)

is a separate zero-diff proof, not part of the suite: it exports both commits with git archive,
generates each from scratch with its own brain.py, and diffs the full generated sets. The
manifest is left out of the byte diff, because it is a function of the file set the diff
already compares (and a commit from before Stage C1 has none); instead each side's manifest,
when it has one, must list exactly that side's generated files.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "Infrastructure" / "scripts"))
import brain  # noqa: E402  -- the unit cases call its lints on crafted output
import yaml  # noqa: E402  -- PyYAML, a declared dependency; the cases rewrite frontmatter
BRAIN = [sys.executable, "Infrastructure/scripts/brain.py"]
CHECK = [*BRAIN, "check", "--only", "drift", "--only", "lints"]

failures: list[str] = []
checks_run = 0


def expect(condition: bool, label: str, detail: str = "") -> None:
    global checks_run
    checks_run += 1
    if not condition:
        failures.append(f"{label}{': ' + detail[:400] if detail else ''}")


def isolated_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The caller's environment minus every GIT_* variable, with no global or system config.

    An inherited GIT_DIR or GIT_WORK_TREE would point the fixture's git commands at another
    repository, and a user config could sign or hook the fixture's commits. Automatic gc and
    maintenance are off: a background pack after a commit removes loose-object folders while
    the suite copies the fixture repository, which fails the copy intermittently.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "gc.auto", "GIT_CONFIG_VALUE_0": "0",
                "GIT_CONFIG_KEY_1": "maintenance.auto", "GIT_CONFIG_VALUE_1": "false"})
    env.update(extra or {})
    return env


def run(cwd: Path, *cmd: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True,
                          env=isolated_env(env), timeout=120, check=False)


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(cwd, "git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
               "-c", "commit.gpgsign=false", *args)


def status(repo: Path) -> str:
    return git(repo, "status", "--porcelain", "--untracked-files=all").stdout.strip()


def make_copy(dest: Path) -> Path:
    """Copy the tracked and untracked-but-unignored files (and this suite's own scripts) into a
    new committed repository.

    Untracked files count because a new project runs the checks before its first commit; a copy
    of the tracked files alone would then hold almost nothing.
    """
    listed = run(REPO_ROOT, "git", "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if listed.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {listed.stderr}")
    rels = set(filter(None, listed.stdout.split("\0")))
    rels |= {"Infrastructure/scripts/brain.py", "Infrastructure/scripts/test_brain.py"}
    for rel in sorted(rels):
        source = REPO_ROOT / rel
        if source.is_file() and not source.is_symlink():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest / rel)
    for step in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "fixture")):
        result = git(dest, *step)
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(step)} failed: {result.stderr}")
    return dest


AGENT, WORKFLOW, SKILL = ("Infrastructure/agents/{}.md", "Infrastructure/skills/{}/SKILL.md",
                          "Infrastructure/style/skills/{}.md")


def edit_meta(repo: Path, rel: str, changes: dict[str, object]) -> None:
    """Set frontmatter keys of one canonical file; a value of None deletes the key.

    A dotted key (`codex.sandbox_mode`) reaches into a nested mapping.
    """
    path = repo / rel
    meta, body = brain.split_frontmatter(path.read_bytes(), rel)
    for dotted, value in changes.items():
        *parents, key = dotted.split(".")
        target = meta
        for parent in parents:
            target = target[parent]
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value
    head = yaml.safe_dump(meta, sort_keys=False, width=10_000).encode()
    path.write_bytes(b"---\n" + head + b"---\n\n" + body)


def replace_frontmatter(repo: Path, rel: str, head: str) -> None:
    """Swap the whole frontmatter block (delimiters included) for raw text."""
    path = repo / rel
    body = brain.split_frontmatter(path.read_bytes(), rel)[1]
    path.write_bytes(head.encode() + body)


def plant(repo: Path, rel: str, text: str = "hand-added\n") -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text, encoding="utf-8", newline="\n")


def case_sync_is_idempotent(repo: Path) -> None:
    for attempt in ("first", "second"):
        result = run(repo, *BRAIN, "sync")
        expect(result.returncode == 0, f"{attempt} clean sync must succeed", result.stderr)
        expect(status(repo) == "", f"{attempt} clean sync must change nothing", status(repo))
    listed = (repo / brain.MANIFEST).read_text(encoding="utf-8").splitlines()
    expect("AGENTS.md" not in listed and "CLAUDE.md" not in listed,
           "the hand-written root files are not generated, so the manifest does not list them")
    for rel in ("AGENTS.md", "CLAUDE.md"):
        (repo / rel).write_text((repo / rel).read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8", newline="\n")
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 0 and all("hand edit" in (repo / rel).read_text(encoding="utf-8")
                                          for rel in ("AGENTS.md", "CLAUDE.md")),
           "sync must leave a hand edit of a root instruction file in place", result.stderr[-400:])
    git(repo, "checkout", "-q", "--", ".")
    result = run(repo, *CHECK)
    expect(result.returncode == 0, "check must pass on a clean tree", result.stderr)
    expect("[drift] PASS" in result.stdout and "[lints] PASS" in result.stdout,
           "check must report its drift and lints parts by name", result.stdout)


def case_check_reports_drift_missing_and_unowned(repo: Path) -> None:
    """Drift, missing, and retired-surface failures; unowned paths are listed, never failed."""
    unowned = [".claude/agents/zz.md", ".codex/agents/zz.toml", ".claude/commands/zz.md",
               ".claude/skills/zz-mine/SKILL.md", ".claude/rules/zz.md", ".claude/templates/zz.md",
               ".codex/rules/zz.md", ".codex/agents/zz.md", ".agents/skills/zz-orphan/SKILL.md",
               ".claude/settings.local.json"]
    for rel in unowned:
        plant(repo, rel)
    (repo / ".claude" / "rules" / "zz-empty").mkdir()
    plant(repo, ".claude/worktrees/agent-x/.claude/agents/nested.md")
    result = run(repo, *CHECK)
    expect(result.returncode == 0, "unowned paths alone must not fail check", result.stderr[-400:])
    for rel in [*unowned, ".claude/rules/zz-empty/"]:
        expect(f"  {rel}\n" in result.stdout, f"check must list unowned `{rel}` as information",
               result.stdout[-400:])
    expect(f"[drift] INFO: {len(unowned) + 1} unowned path(s)" in result.stdout and "worktrees" not in result.stdout,
           "check must count the unowned paths and skip nested agent worktrees", result.stdout[-400:])

    rule = sorted((repo / ".claude" / "rules").glob("*.md"))[0]
    rule.write_text(rule.read_text(encoding="utf-8") + "hand edit\n", encoding="utf-8", newline="\n")
    missing = [".claude/agents/ai-skeptic.md", ".codex/agents/ai-skeptic.toml", ".claude/skills/cite/SKILL.md",
               ".agents/skills/cite/SKILL.md", ".claude/skills/eig-style-review/SKILL.md",
               ".agents/skills/eig-style-review/SKILL.md", ".claude/rules/r-coding-style-rules.md",
               ".claude/skills/idea-refine/references/examples.md", ".claude/README.md", ".codex/hooks.json"]
    for rel in missing:
        (repo / rel).unlink()
    for rel in (".codex/commands/x.md", ".codex/templates/x.md", ".codex/skills/x/SKILL.md"):
        plant(repo, rel)
    result = run(repo, *CHECK)
    expect(result.returncode == 1, "check must fail on drift", f"exit={result.returncode}")
    needles = [f"Drift detected in .claude/rules/{rule.name}", "+hand edit"]
    needles += [f"Missing file: {rel}" for rel in missing]
    needles += [f"Obsolete Codex surface still exists: .codex/{d}/" for d in ("commands", "templates", "skills")]
    for needle in needles:
        expect(needle in result.stderr, f"check must report `{needle}`", result.stderr[-400:])
    expect("zz.md" not in result.stderr, "an unowned path must never be reported as a problem",
           result.stderr[-400:])

    shutil.rmtree(repo / ".claude" / "agents")
    result = run(repo, *BRAIN, "check", "--only", "drift")
    expect("Missing directory: .claude/agents" in result.stderr, "check must report a missing generated tree",
           result.stderr[-400:])


SYMLINK_SKIP = ("symlink case skipped: this account cannot create symlinks (Windows needs "
                "Developer Mode or an administrator); CI's Windows runner exercises it")


def can_symlink(where: Path) -> bool:
    """True when this process may create a symlink: always on POSIX, and on Windows only with
    Developer Mode or elevation."""
    probe = where / ".symlink-probe"
    try:
        probe.symlink_to(where, target_is_directory=True)
    except OSError:
        return False
    probe.unlink()
    return True


def case_manifest_ownership(repo: Path) -> None:
    """Sync writes and deletes only manifest paths; every other adapter-tree file survives."""
    manifest = repo / brain.MANIFEST
    user = {".claude/agents/local.md": "my agent\n", ".claude/skills/mine/SKILL.md": "my skill\n",
            ".agents/skills/my-codex-skill/SKILL.md": "my Codex skill\n", ".codex/agents/zz-local.toml": "x\n",
            ".claude/settings.local.json": "{}\n", ".agents/skills/cite/notes.md": "beside a generated skill\n"}
    for rel, text in user.items():
        plant(repo, rel, text)

    def user_files_intact() -> bool:
        return all((repo / rel).is_file() and (repo / rel).read_text(encoding="utf-8") == text
                   for rel, text in user.items())
    for attempt in ("first", "second"):
        result = run(repo, *BRAIN, "sync")
        expect(result.returncode == 0, f"{attempt} sync beside user-added files must succeed", result.stderr)
        expect(user_files_intact(), f"{attempt} sync must leave every user-added file untouched")
        expect(sorted(status(repo).splitlines()) == sorted(f"?? {rel}" for rel in user  # the last is gitignored
                                                           if rel != ".claude/settings.local.json"),
               f"{attempt} sync must change no generated file", status(repo))
    result = run(repo, *CHECK)
    expect(result.returncode == 0 and all(f"  {rel}\n" in result.stdout for rel in user),
           "check must pass and list the user-added files as unowned", result.stdout[-400:] + result.stderr[-400:])

    (repo / AGENT.format("ai-skeptic")).unlink()
    result = run(repo, *BRAIN, "check", "--only", "drift")
    expect(result.returncode == 1 and f"Manifest drift: {brain.MANIFEST}" in result.stderr,
           "a manifest that lists a path no longer generated must fail check", result.stderr[-400:])
    result = run(repo, *BRAIN, "sync")
    gone = [".claude/agents/ai-skeptic.md", ".codex/agents/ai-skeptic.toml"]
    expect(result.returncode == 0 and not any((repo / rel).exists() for rel in gone),
           "sync must delete a removed agent's generated files through the manifest", result.stderr[-400:])
    expect(all(f"  {rel}\n" in result.stdout for rel in gone), "sync must list what it deleted", result.stdout)
    listed = manifest.read_text(encoding="utf-8").splitlines()
    expect(not set(gone) & set(listed), "the manifest must drop the deleted paths")

    shutil.rmtree(repo / "Infrastructure" / "skills" / "cite")
    (repo / SKILL.format("eig-style-review")).unlink()
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 0, "sync after removing a workflow and a skill must succeed", result.stderr[-400:])
    for rel in (".claude/skills/cite", ".agents/skills/cite/SKILL.md", ".claude/skills/eig-style-review",
                ".agents/skills/eig-style-review"):
        expect(not (repo / rel).exists(), f"sync must remove `{rel}` (an emptied directory is pruned)")
    expect(user_files_intact(), "a user file beside a deleted generated file must survive, with its directory")
    result = run(repo, *BRAIN, "check", "--only", "drift")
    expect(result.returncode == 0, "check must pass once sync has caught up", result.stderr[-400:])

    agent = repo / ".claude" / "agents" / "code-reviewer.md"
    original = agent.read_bytes()
    agent.write_bytes(original + b"hand edit\n")
    result = run(repo, *BRAIN, "check", "--only", "drift")
    expect(result.returncode == 1 and "Drift detected in .claude/agents/code-reviewer.md" in result.stderr,
           "a hand-edited generated file must be reported as drift", result.stderr[-400:])
    run(repo, *BRAIN, "sync")
    expect(agent.read_bytes() == original, "sync must overwrite a hand-edited generated file")

    text = manifest.read_text(encoding="utf-8")
    kept = ["Infrastructure/agents/code-reviewer.md", "README.md", ".claude/worktrees/agent-x/keep.md",
            ".claude/../README.md"]
    plant(repo, ".claude/worktrees/agent-x/keep.md")
    manifest.write_text(text + "".join(f"{rel}\n" for rel in kept), encoding="utf-8", newline="\n")
    result = run(repo, *BRAIN, "check", "--only", "drift")
    expect(result.returncode == 1 and "Manifest drift" in result.stderr, "a hand-edited manifest must fail check",
           result.stderr[-400:])
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 0 and all((repo / rel).exists() for rel in kept),
           "sync must delete nothing outside the adapter trees or inside a worktree, whatever the manifest says",
           result.stderr[-400:])
    expect(all(f"  {rel}\n" in result.stderr for rel in kept), "sync must name the paths it left in place",
           result.stderr[-400:])
    expect(manifest.read_text(encoding="utf-8") == text, "sync must rewrite the manifest")

    # A symlinked directory must not carry a deletion out of the adapter tree: a committed
    # `.claude/linkdir -> ../data/raw`, or an alias that dodges the worktree exclusion.
    if can_symlink(repo):
        plant(repo, "data/raw/secret.csv", "id,value\n")
        plant(repo, ".claude/worktrees/agent-y/keep.md")
        (repo / ".claude" / "linkdir").symlink_to(Path("..") / "data" / "raw", target_is_directory=True)
        (repo / ".claude" / "wtalias").symlink_to("worktrees", target_is_directory=True)
        plant(repo, ".claude/settings.local.json", "{}\n")
        through = [".claude/linkdir/secret.csv", ".claude/wtalias/agent-y/keep.md", ".claude/settings.local.json"]
        manifest.write_text(text + "".join(f"{rel}\n" for rel in through), encoding="utf-8", newline="\n")
        result = run(repo, *BRAIN, "sync")
        expect(result.returncode == 0 and (repo / "data/raw/secret.csv").is_file()
               and (repo / ".claude/worktrees/agent-y/keep.md").is_file()
               and (repo / ".claude/settings.local.json").is_file(),
               "sync must not delete through a symlinked directory, into a worktree, or settings.local.json",
               result.stderr[-400:])
        expect(all(f"  {rel}\n" in result.stderr for rel in through), "sync must name each path it kept",
               result.stderr[-400:])
        for link in ("linkdir", "wtalias"):
            (repo / ".claude" / link).unlink()
    else:
        print(f"note: {SYMLINK_SKIP} (sync through a symlinked directory)")

    manifest.unlink()
    (repo / AGENT.format("orchestrator")).unlink()
    result = run(repo, *BRAIN, "sync")
    leftover = ".claude/agents/orchestrator.md"
    expect(result.returncode == 0 and (repo / leftover).is_file() and manifest.is_file()
           and f"No previous {brain.MANIFEST}" in result.stdout,
           "without a previous manifest, sync must delete nothing and write a new one", result.stdout[-400:])
    result = run(repo, *BRAIN, "check", "--only", "drift")
    expect(result.returncode == 0 and f"  {leftover}\n" in result.stdout,
           "a leftover from before the manifest must be listed as unowned", result.stdout[-400:])

    plant(repo, ".codex/skills/mine/SKILL.md")
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 0 and (repo / ".codex/skills/mine/SKILL.md").is_file()
           and "Retired Codex surfaces remain" in result.stderr,
           "sync must keep, and name, a retired surface it did not record", result.stderr[-400:])
    shutil.rmtree(repo / ".codex" / "skills")

    if can_symlink(repo):
        outside = repo.parent / f"{repo.name}-outside"
        skills = repo / ".claude" / "skills"
        shutil.move(str(skills), str(outside))
        skills.symlink_to(outside, target_is_directory=True)
        before = sorted(p.name for p in outside.iterdir())
        result = run(repo, *BRAIN, "sync")
        expect(result.returncode == 1 and ".claude/skills is a symbolic link" in result.stderr,
               "sync must refuse to write through a symlinked directory", result.stderr[-400:])
        expect(skills.is_symlink() and sorted(p.name for p in outside.iterdir()) == before,
               "the refusal must keep the link and change nothing behind it")
    else:
        print(f"note: {SYMLINK_SKIP} (sync refuses a symlinked skills dir)")

    for args in (["sync", "--force"], ["sync", "--frce"], ["check", "--force"], ["bogus"], []):
        result = run(repo, *BRAIN, *args)
        expect(result.returncode == 2, f"usage error for `{' '.join(args)}`", f"exit={result.returncode}")


def case_missing_metadata_is_an_error(repo: Path) -> None:
    edit_meta(repo, WORKFLOW.format("cite"), {"allowed-tools": None})
    before = status(repo)
    result = run(repo, *BRAIN, "sync")
    needle = "Infrastructure/skills/cite/SKILL.md: required key `allowed-tools` is missing; there are no defaults."
    expect(result.returncode == 1, "sync must fail on a missing frontmatter key", f"exit={result.returncode}")
    expect(needle in result.stderr, "the error must name the file and the missing key", result.stderr)
    expect(status(repo) == before, "a metadata error must change nothing", status(repo))
    result = run(repo, *CHECK)
    expect(result.returncode == 1 and "Generation failed" in result.stderr and needle in result.stderr,
           "check must report the missing key", result.stderr)
    git(repo, "checkout", "-q", "--", ".")

    for rel, changes, message in (
            (AGENT.format("code-reviewer"), {"description": " "}, "`description` must be a non-empty single-line"),
            (AGENT.format("code-reviewer"), {"codex.sandbox_mode": None}, "`codex.sandbox_mode` is missing"),
            (SKILL.format("eig-style-review"), {"argument-hint": None}, "`argument-hint` is missing")):
        edit_meta(repo, rel, changes)
        result = run(repo, *BRAIN, "sync")
        expect(result.returncode == 1 and f"{rel}: " in result.stderr and message in result.stderr,
               f"sync must fail on {changes} (no silent default)", result.stderr)
        git(repo, "checkout", "-q", "--", ".")
    replace_frontmatter(repo, AGENT.format("code-reviewer"), "")
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 1 and "code-reviewer.md: no YAML frontmatter" in result.stderr,
           "sync must fail on a canonical agent without frontmatter", result.stderr)
    git(repo, "checkout", "-q", "--", ".")


def case_lints(repo: Path) -> None:
    infra = repo / "Infrastructure"
    edit_meta(repo, AGENT.format("code-reviewer"), {"tools": ["[Read"]})  # renders unparseable YAML
    skill = infra / "skills" / "smart-brevity" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nRun `/cite` with $ARGUMENTS.\n", encoding="utf-8", newline="\n")
    shutil.copy(infra / "rules" / "maintenance-rules.md", infra / "templates" / "maintenance-rules.md")
    for rel, name in (("Infrastructure/rules/verification-protocol.md", "cite"),
                      ("Infrastructure/templates/plan.md", "review-code"), ("PROJECT.md", "document-data"),
                      ("AGENTS.md", "eig-style-review"),
                      ("Infrastructure/AI_WORKFLOW.md", "eig-tufte-critique")):
        target = repo / rel  # U10: rules, templates, and PROJECT.md are read by both adapters
        target.write_text(target.read_text(encoding="utf-8") + f"\nRun `/{name}` first; `/api/{name}` is a path.\n",
                          encoding="utf-8", newline="\n")
    (repo / "CLAUDE.md").write_text("Codex notes\n", encoding="utf-8", newline="\n")
    result = run(repo, *BRAIN, "check", "--only", "lints")
    expect(result.returncode == 1, "lints must fail", f"exit={result.returncode}")
    for needle in (".claude/agents/code-reviewer.md: frontmatter is not valid YAML",
                   "Infrastructure/skills/smart-brevity/SKILL.md contains the Claude-only `$ARGUMENTS`",
                   "uses Claude slash syntax `/cite`",
                   "Codex skill .agents/skills/smart-brevity/SKILL.md contains the Claude-only `$ARGUMENTS`",
                   "Codex skill .agents/skills/smart-brevity/SKILL.md uses Claude slash syntax `/cite`",
                   "Unapproved canonical duplication: 'maintenance-rules' appears in rules, templates",
                   "Canonical file Infrastructure/rules/verification-protocol.md uses Claude slash syntax `/cite`",
                   "Canonical file Infrastructure/templates/plan.md uses Claude slash syntax `/review-code`",
                   "Canonical file PROJECT.md uses Claude slash syntax `/document-data`",
                   "Canonical file AGENTS.md uses Claude slash syntax `/eig-style-review`",
                   "Canonical file Infrastructure/AI_WORKFLOW.md uses Claude slash syntax `/eig-tufte-critique`",
                   "CLAUDE.md must import the shared instructions with an `@AGENTS.md` line",
                   "CLAUDE.md mentions Codex"):
        expect(needle in result.stderr, f"lints must report `{needle}`", result.stderr)
    expect("/api/" not in result.stderr, "a path such as `/api/cite` is not workflow syntax", result.stderr)
    git(repo, "checkout", "-q", "--", ".")
    git(repo, "clean", "-fdq")


def case_metadata_lints(repo: Path) -> None:
    """Frontmatter lints, each on its own mutation, with generation failing too."""
    review_code = repo / WORKFLOW.format("review-code")
    mutations = {  # rel -> (frontmatter changes, the reported problem)
        AGENT.format("ai-skeptic"): ({"codex": None}, "required key `codex` is missing; there are no defaults"),
        AGENT.format("code-reviewer"): ({"tools": None}, "required key `tools` is missing"),
        WORKFLOW.format("cite"): ({"description": None}, "required key `description` is missing"),
        SKILL.format("eig-style-review"): ({"argument-hint": None}, "required key `argument-hint` is missing"),
        AGENT.format("orchestrator"): ({"description": "", "codex.sandbox_mode": "sandboxed"},
                                       "`codex.sandbox_mode` has invalid value 'sandboxed'"),
        AGENT.format("eig-writer"): ({"codex.reasoning_effort": "extreme"},
                                     "`codex.reasoning_effort` has invalid value 'extreme'"),
        AGENT.format("eig-reviewer"): ({"effort": "huge"}, "`effort` has invalid value 'huge'"),
        AGENT.format("maintenance-agent"): ({"model": "gpt-9"}, "`model` has invalid value 'gpt-9'"),
        AGENT.format("literature-scout"): ({"tools": "Read,Write"}, "`tools` must be a non-empty list"),
        AGENT.format("code-interlocutor"): ({"codex": "workspace-write"}, "`codex` must be a mapping"),
        WORKFLOW.format("review-style"): ({"name": "review-styles"},
                                          "name 'review-styles' does not match the file or directory name"),
        SKILL.format("eig-tufte-critique"): ({"alowed-tools": ["Read"]}, "unknown key `alowed-tools`"),
        WORKFLOW.format("document-data"): ({"description": "x" * 1025},
                                           "a description is 1025 characters; the limit is 1024"),
        WORKFLOW.format("review-code"): ({"description": brain.first_body_line(review_code)},
                                         "a description is byte-identical to the first body line"),
        WORKFLOW.format("full-review"): ({"disable-model-invocation": "yes"},
                                         "`disable-model-invocation` must be true or false"),
    }
    for rel, (changes, _) in mutations.items():
        edit_meta(repo, rel, changes)
    raw = {  # rel -> (frontmatter block, the reported problem)
        WORKFLOW.format("smart-brevity"): ("---\nname: [smart-brevity\n---\n", "frontmatter is not valid YAML"),
        WORKFLOW.format("interview-me"): ("", "no YAML frontmatter"),
        WORKFLOW.format("cover-sheet"): ("---\n- a\n---\n", "frontmatter is not a YAML mapping"),
        # safe_load would keep the last of a repeated key, silently widening a grant.
        WORKFLOW.format("review-methodology"): (
            "---\nname: review-methodology\ndescription: D.\nallowed-tools: [Read]\n"
            "allowed-tools: [Read, Bash]\n---\n", "duplicate key `allowed-tools`"),
        SKILL.format("eig-style-apply"): (
            "---\nname: eig-style-apply\ndescription: A.\ndescription: B.\nargument-hint: x\n"
            "allowed-tools: [Read]\n---\n", "duplicate key `description`"),
        AGENT.format("data-consistency-reviewer"): (
            "---\nname: data-consistency-reviewer\ndescription: D.\ntools: [Read]\ncodex:\n"
            "  sandbox_mode: read-only\n  sandbox_mode: danger-full-access\n---\n",
            "duplicate key `sandbox_mode`"),
    }
    for rel, (head, _) in raw.items():
        replace_frontmatter(repo, rel, head)
    agent = repo / AGENT.format("data-dictionary-agent")
    agent.write_bytes(agent.read_bytes() + b"\ncaf\xe9 latin-1\n")

    result = run(repo, *BRAIN, "check", "--only", "lints")
    expect(result.returncode == 1, "metadata lints must fail", f"exit={result.returncode}")
    needles = ["Generation failed", "data-dictionary-agent.md is not valid UTF-8",
               f"{AGENT.format('orchestrator')}: `description` must be a non-empty single-line string"]
    needles += [f"{rel}: {problem}" for rel, (_, problem) in (*mutations.items(), *raw.items())]
    for needle in needles:
        expect(needle in result.stderr, f"lints must report `{needle}`", result.stderr[-400:])
    expect("Traceback" not in result.stderr, "a non-UTF-8 body must not crash check", result.stderr[-400:])
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 1 and "there are no defaults" in result.stderr,
           "sync must refuse incomplete metadata", result.stderr[-400:])


def case_generation_errors(repo: Path) -> None:
    """Missing sources and structural conflicts fail sync and are named by the lints."""
    infra = repo / "Infrastructure"
    (repo / "AGENTS.md").write_text("@Infrastructure/AI_WORKFLOW.md\n" + "x" * (32 * 1024), encoding="utf-8", newline="\n")
    (repo / "CLAUDE.md").unlink()
    plant(repo, "Infrastructure/root_instructions/shared_body.md")
    (infra / "style" / "skills" / "cite.md").write_text("# Style skill cite\n", encoding="utf-8", newline="\n")
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 1 and "Duplicate generated skill names detected: cite" in result.stderr,
           "sync must fail when a workflow and a dedicated skill share a name", result.stderr[-400:])
    result = run(repo, *BRAIN, "check", "--only", "lints")
    for needle in ("Missing root instruction file: CLAUDE.md", "Infrastructure/root_instructions/ is retired",
                   "AGENTS.md has an `@path` import line", "Codex truncates past 32768",
                   "'cite' is both a workflow and a dedicated skill",
                   "Unapproved canonical duplication: 'cite' appears in skills, style/skills"):
        expect(needle in result.stderr, f"lints must report `{needle}`", result.stderr[-400:])
    (infra / "style" / "skills" / "cite.md").unlink()
    (repo / "AGENTS.md").unlink()
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 0 and not (repo / "AGENTS.md").exists() and not (repo / "CLAUDE.md").exists(),
           "sync must neither need nor write the hand-written root files", result.stderr[-400:])
    result = run(repo, *BRAIN, "check", "--only", "lints")
    for name in ("AGENTS.md", "CLAUDE.md"):
        needle = f"Missing root instruction file: {name}"
        expect(needle in result.stderr, f"lints must report `{needle}`", result.stderr[-400:])


def lint_output(repo: Path, edit) -> tuple[list[str], list[str]]:
    """Render `repo`, apply `edit` to the rendered files, and run the output lints."""
    expected = brain.render(repo)
    edit(expected.files)
    infra = repo / "Infrastructure"
    return (brain.lint_codex_agents(expected) + brain.lint_frontmatter(infra, expected),
            brain.lint_invocation(repo, expected))


def case_output_lints(repo: Path) -> None:
    """Lints on generated content that a correct generator cannot produce, fed crafted output."""
    toml_tail = "developer_instructions = '''\nx\n'''\n"
    tomls = {"bad-parse": 'name = "bad-parse\n',
             "no-desc": f'name = "no-desc"\nsandbox_mode = "read-only"\n{toml_tail}',
             "renamed": f'name = "other"\ndescription = "d"\nsandbox_mode = "read-only"\n{toml_tail}',
             "sandbox": f'name = "sandbox"\ndescription = "d"\nsandbox_mode = "open"\n{toml_tail}',
             "effort": f'name = "effort"\ndescription = "d"\nmodel_reasoning_effort = "huge"\nsandbox_mode = "read-only"\n{toml_tail}',
             "model": f'name = "model"\ndescription = "d"\nmodel = ""\nsandbox_mode = "read-only"\n{toml_tail}'}

    def edit(files: dict) -> None:
        for name, text in tomls.items():
            files[f".codex/agents/{name}.toml"] = brain.Out(text.encode())
        files[".claude/agents/zz-none.md"] = brain.Out(b"# no frontmatter\n")
        files[".claude/agents/zz-open.md"] = brain.Out(b"---\nname: zz-open\n")
        files[".claude/agents/zz-list.md"] = brain.Out(b"---\n- a\n---\n")
        agent = files[".claude/agents/ai-skeptic.md"].data
        files[".claude/agents/ai-skeptic.md"] = brain.Out(agent.replace(b"name: ai-skeptic", b"name: ai-sceptic", 1))
        agent = files[".claude/agents/code-reviewer.md"].data
        files[".claude/agents/code-reviewer.md"] = brain.Out(agent.replace(b'description: "', b'description: "X', 1))
        skill = files[".claude/skills/cite/SKILL.md"].data
        files[".claude/skills/cite/SKILL.md"] = brain.Out(
            skill.replace(b'argument-hint: "', b'argument-hint: "X', 1).replace(b"Arguments: $ARGUMENTS", b""))
        skill = files[".claude/skills/review-code/SKILL.md"].data
        files[".claude/skills/review-code/SKILL.md"] = brain.Out(
            skill.replace(b"allowed-tools:", b"disable-model-invocation: false\nallowed-tools:", 1)
            + b"\nArguments: $ARGUMENTS\n")
        skill = files[".claude/skills/build-replication-package/SKILL.md"].data
        files[".claude/skills/build-replication-package/SKILL.md"] = brain.Out(
            skill.replace(b"disable-model-invocation: true\n", b"", 1))

    edit_meta(repo, WORKFLOW.format("review-code"), {"argument-hint": None})
    output, invocation = lint_output(repo, edit)
    text = "\n".join(output + invocation)
    for needle in (".codex/agents/bad-parse.toml: generated Codex agent TOML does not parse",
                   ".codex/agents/no-desc.toml: `description` must be a non-empty string",
                   ".codex/agents/renamed.toml: name 'other' does not match the filename",
                   ".codex/agents/sandbox.toml: invalid or missing sandbox_mode 'open'",
                   ".codex/agents/effort.toml: invalid model_reasoning_effort",
                   ".codex/agents/model.toml: `model` is present but empty",
                   ".claude/agents/zz-none.md: frontmatter is missing, unterminated, or not a YAML mapping",
                   ".claude/agents/zz-open.md: frontmatter is missing, unterminated",
                   ".claude/agents/zz-list.md: frontmatter is missing, unterminated, or not a YAML mapping",
                   ".claude/agents/ai-skeptic.md: frontmatter name 'ai-sceptic' does not match `ai-skeptic`",
                   ".claude/agents/code-reviewer.md: frontmatter description does not round-trip",
                   ".claude/skills/cite/SKILL.md: argument-hint",
                   ".claude/skills/cite/SKILL.md: the `Arguments: $ARGUMENTS` bridge must be present",
                   ".claude/skills/review-code/SKILL.md: the `Arguments: $ARGUMENTS` bridge must be present",
                   ".claude/skills/review-code/SKILL.md: disable-model-invocation does not round-trip",
                   ".claude/skills/build-replication-package/SKILL.md: disable-model-invocation does not"):
        expect(needle in text, f"output lints must report `{needle}`", text[-400:])

    expected = brain.render(repo)
    saved = sys.modules.get("yaml")
    sys.modules["yaml"] = None  # type: ignore[assignment]  # makes `import yaml` raise ImportError
    try:
        missing = brain.lint_frontmatter(repo / "Infrastructure", expected)
        try:
            brain.render(repo)
            generation = "rendered without PyYAML"
        except brain.BrainError as exc:
            generation = str(exc)
    finally:
        if saved is None:
            sys.modules.pop("yaml", None)
        else:
            sys.modules["yaml"] = saved
    expect(missing == ["PyYAML is required to parse generated frontmatter: pip install pyyaml"],
           "a missing PyYAML must be reported, not crash", repr(missing))
    expect("PyYAML is required to parse frontmatter" in generation,
           "generation must fail with a message, not crash, without PyYAML", generation[:400])


def case_absent_hint_is_no_hint(repo: Path) -> None:
    edit_meta(repo, WORKFLOW.format("cite"), {"argument-hint": None})
    result = run(repo, *BRAIN, "sync")
    command = (repo / ".claude" / "skills" / "cite" / "SKILL.md").read_text(encoding="utf-8")
    expect(result.returncode == 0 and "$ARGUMENTS" not in command and "argument-hint" not in command
           and "It takes no arguments." in command, "an absent hint must produce no bridge", command[:400])
    result = run(repo, *CHECK)
    expect(result.returncode == 0, "check must agree with sync about an absent hint", result.stderr[-400:])
    edit_meta(repo, WORKFLOW.format("cite"), {"argument-hint": "  "})
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 1 and "`argument-hint` must be a non-empty single-line string" in result.stderr,
           "a whitespace-only hint must be an error, not a silent no-hint", result.stderr[-400:])


def case_claude_surface(repo: Path) -> None:
    """Stage C2: every workflow is a Claude skill with its whole canonical subtree; no commands or
    templates mirror; agent-only rules stay canonical; bodies keep their Infrastructure/ paths."""
    files = brain.render(repo).files
    infra = repo / "Infrastructure"
    workflows = brain.skill_names(infra / "skills")
    for name in workflows:
        skill = files.get(f".claude/skills/{name}/SKILL.md")
        head = yaml.safe_load(skill.data.decode().split("---\n")[1]) if skill else {}
        expect(skill is not None and head.get("name") == name and f"Invoke as `/{name}".encode() in skill.data,
               f"workflow `{name}` must be a Claude skill named for its `/{name}` surface")
        for source in (infra / "skills" / name).rglob("*"):
            rel = source.relative_to(infra / "skills").as_posix()
            expect(not source.is_file() or f".claude/skills/{rel}" in files,
                   f"the Claude skill must carry the canonical file `{rel}`")
    expect(not [rel for rel in files if rel.startswith((".claude/commands/", ".claude/templates/"))],
           "no Claude command or template mirror is generated")
    loads = {name: e.meta["load"] for (kind, name), e in brain.load_entities(infra)[0].items() if kind == "rule"}
    expect(len(loads) == len(brain.md_names(infra / "rules")), "every canonical rule is loaded as a `rule` entity")
    for name, load in sorted(loads.items()):
        expect((f".claude/rules/{name}.md" in files) == (load in ("always", "paths")),
               f"the rule `{name}` (load: {load}) is mirrored exactly when it loads in the main session")
    expect(loads.get("code-quality-rules") == "referenced" and loads.get("r-coding-style-rules") == "paths",
           "a reviewer rulebook is referenced and the R standard is path-scoped", repr(loads)[:300])
    claude = {rel: out.data for rel, out in files.items() if rel.startswith(".claude/")}
    expect(not [rel for rel, data in claude.items() if b".claude/templates/" in data],
           "no generated Claude file cites the retired templates mirror")
    agent = files[".claude/agents/code-reviewer.md"].data
    expect(b"Infrastructure/rules/code-quality-rules.md" in agent, "an agent must cite its rulebook canonically")
    heads = {name: yaml.safe_load(files[f".claude/skills/{name}/SKILL.md"].data.decode().split("---\n")[1])
             for name in workflows}
    no_model = sorted(name for name, head in heads.items() if head.get("disable-model-invocation") is True)
    expect(no_model == ["build-replication-package", "orchestrate"],
           "only build-replication-package and orchestrate are user-invoked only", repr(no_model))
    expect(all("disable-model-invocation" not in (brain.split_frontmatter(
        (repo / f".agents/skills/{name}/SKILL.md").read_bytes(), name)[0]) for name in workflows),
        "the Codex skills carry no Claude-only invocation key")

    edit_meta(repo, WORKFLOW.format("cite"), {"disable-model-invocation": False})
    result = run(repo, *BRAIN, "sync")
    skill = (repo / ".claude/skills/cite/SKILL.md").read_text(encoding="utf-8")
    expect(result.returncode == 0 and "disable-model-invocation: false\n" in skill,
           "an explicit false renders as written", skill[:400])


def case_rule_load_tiers(repo: Path) -> None:
    """Stage D: every rule declares `load:`; the mirror keeps only `paths:`; tiers are validated."""
    rule = "Infrastructure/rules/{}.md"
    edit_meta(repo, rule.format("session-logging"), {"load": "always"})  # no rule ships `always` after 3A
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 0 and (repo / ".claude/rules/session-logging.md").exists(),
           "a rule moved to `load: always` is mirrored on the next sync", result.stderr[-400:])
    files = brain.render(repo).files
    for name, head in (("session-logging", b"# Session Logging"),
                       ("r-coding-style-rules", b'---\npaths:\n  - "code/*.R"')):
        mirror = files[f".claude/rules/{name}.md"].data
        expect(mirror.startswith(head) and b"load:" not in mirror.split(b"\n---\n")[0],
               f"the `{name}` mirror drops `load:` and keeps any `paths:`", mirror[:120].decode())
    edit_meta(repo, rule.format("session-logging"), {"load": "referenced"})
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 0 and not (repo / ".claude/rules/session-logging.md").exists(),
           "a rule moved to `load: referenced` leaves .claude/rules/ on the next sync", result.stderr[-400:])
    edit_meta(repo, rule.format("verification-protocol"), {"load": None})
    edit_meta(repo, rule.format("performance-cost-governance"), {"load": "sometimes"})
    edit_meta(repo, rule.format("code-quality-rules"), {"paths": ["review-reports/**"]})
    edit_meta(repo, rule.format("style-writing-rules"), {"paths": None})
    edit_meta(repo, rule.format("plan-first-workflow"), {"owner": "x"})
    result = run(repo, *BRAIN, "check", "--only", "lints")
    for needle in ("verification-protocol.md: required key `load` is missing",
                   "performance-cost-governance.md: `load` has invalid value 'sometimes'",
                   "code-quality-rules.md: `paths:` goes with `load: paths`",
                   "style-writing-rules.md: `paths:` goes with `load: paths`",
                   "plan-first-workflow.md: unknown key `owner`"):
        expect(result.returncode == 1 and needle in result.stderr, f"lints must report `{needle}`",
               result.stderr[-600:])
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 1 and "required key `load` is missing" in result.stderr,
           "sync refuses a rule without `load:`", result.stderr[-400:])


def case_load_budget_anchors_and_map(repo: Path) -> None:
    """Stage D: the always-loaded ceiling, the required AGENTS.md anchors, and the loading map."""
    load = [*BRAIN, "check", "--only", "load"]
    result = run(repo, *load)
    expect(result.returncode == 0 and "[load] PASS" in result.stdout, "the committed tree passes the load check",
           result.stdout + result.stderr[-400:])
    logging = "Infrastructure/rules/session-logging.md"
    edit_meta(repo, logging, {"load": "always"})  # no rule ships `always` after 3A; plant one to count
    counted = dict(brain.always_loaded(repo, brain.render(repo)))
    edit_meta(repo, logging, {"load": "referenced"})
    expected = brain.render(repo)
    claude = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    expect(counted.get("AGENTS.md") == brain.words((repo / "AGENTS.md").read_text(encoding="utf-8"))
           and counted.get("CLAUDE.md") == brain.words(claude) - 1
           and "Infrastructure/rules/session-logging.md" in counted
           and not any("code-quality-rules" in rel or "r-coding-style" in rel for rel in counted),
           "the budget counts CLAUDE.md minus its import line, the imported AGENTS.md, and only always rules",
           repr(counted))
    total = sum(dict(brain.always_loaded(repo, expected)).values())

    agents = repo / "AGENTS.md"
    original = agents.read_text(encoding="utf-8")
    agents.write_text(original + "\n" + "word " * (brain.ALWAYS_LOADED_CEILING - total + 1), encoding="utf-8", newline="\n")
    result = run(repo, *load)
    expect(result.returncode == 1 and "above the ceiling" in result.stderr and "[load] INFO:" in result.stderr,
           "one word over the ceiling fails and still reports the count", result.stderr[-400:])
    for name, phrases in brain.REQUIRED_ANCHORS.items():
        for phrase in phrases:
            flat = " ".join(original.split())  # every occurrence goes: a phrase may appear more than once
            agents.write_text(re.sub(re.escape(phrase), "", flat, flags=re.IGNORECASE), encoding="utf-8", newline="\n")
            result = run(repo, *load)
            expect(result.returncode == 1 and f"no longer states the {name} guardrail" in result.stderr,
                   f"deleting \"{phrase}\" from AGENTS.md fails the {name} anchor", result.stderr[-400:])
    rewrapped = original.replace("Do not fabricate data, citations, or results", "Do NOT fabricate\ndata, "
                                 "citations,   or results")
    agents.write_text(rewrapped, encoding="utf-8", newline="\n")
    result = run(repo, *load)
    expect(rewrapped != original and result.returncode == 0,
           "an anchor matches across a line break, extra spaces, and case", result.stderr[-400:])
    agents.write_text(original, encoding="utf-8", newline="\n")

    edit_meta(repo, "Infrastructure/rules/verification-protocol.md", {"load": "paths", "paths": ["code/**"]})
    result = run(repo, *load)
    expect(result.returncode == 1 and "loading map in Infrastructure/TEMPLATE_CENSUS.md is out of date"
           in result.stderr, "a changed tier fails until the loading map is refreshed", result.stderr[-400:])
    result = run(repo, *BRAIN, "loading-map", "--write")
    census = (repo / brain.LOADING_MAP[0]).read_text(encoding="utf-8")
    expect(result.returncode == 0 and "| `Infrastructure/rules/verification-protocol.md` | paths |" in census,
           "loading-map --write refreshes the census table in place", result.stderr[-400:])
    result = run(repo, *load)
    expect(result.returncode == 0, "the refreshed map passes, at the same word count", result.stderr[-400:])
    (repo / brain.LOADING_MAP[0]).write_text(census.replace(brain.LOADING_MAP[1], ""), encoding="utf-8", newline="\n")
    result = run(repo, *load)
    expect(result.returncode == 1 and "is missing" in result.stderr, "a census without the map markers fails",
           result.stderr[-400:])


def case_permission_policy(repo: Path) -> None:
    """Stage E: permissions.yaml renders both adapters' command policy; drift and bad entries fail."""
    policy_path = repo / "Infrastructure/adapter_configs" / brain.POLICY
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    settings = json.loads((repo / ".claude/settings.json").read_text(encoding="utf-8"))
    rules = (repo / ".codex/rules/template.rules").read_text(encoding="utf-8")
    claude = [r for e in data["policy"] for r in e.get("claude", [])]
    expect(sorted(sum((settings["permissions"].get(k, []) for k in ("allow", "ask", "deny")), [])) == sorted(claude)
           and "hooks" in settings and 'decision = "allow"' not in rules
           and rules.count("prefix_rule(") == sum(len(e.get("codex", [])) for e in data["policy"]),
           "the committed settings and execpolicy are exactly the rendered policy")

    def write(policy: dict) -> None:
        policy_path.write_text(yaml.safe_dump(policy, sort_keys=False, width=10_000), encoding="utf-8", newline="\n")

    grown = json.loads(json.dumps(data))
    grown["policy"].append({"decision": "prompt", "reason": "Publishing a release is outward-facing.",
                            "claude": ["Bash(gh release create *)"],
                            "codex": [{"pattern": ["gh", "release", "create"], "match": ["gh release create v1"],
                                       "not_match": ["gh release list"]}]})
    write(grown)
    result = run(repo, *CHECK)
    expect(result.returncode == 1 and "Drift detected in .claude/settings.json" in result.stderr
           and "Drift detected in .codex/rules/template.rules" in result.stderr,
           "a policy edit without a sync is drift in both rendered files", result.stderr[-600:])
    result = run(repo, *BRAIN, "sync")
    settings = json.loads((repo / ".claude/settings.json").read_text(encoding="utf-8"))
    rules = (repo / ".codex/rules/template.rules").read_text(encoding="utf-8")
    expect(result.returncode == 0 and (settings["permissions"].get("ask") or [None])[-1] == "Bash(gh release create *)"
           and 'pattern = ["gh", "release", "create"],\n    decision = "prompt",' in rules,
           "one prompt entry renders to Claude `ask` and a Codex prompt rule", result.stderr[-400:])
    (repo / ".claude/settings.json").write_text(json.dumps(settings).replace("git status *", "git *"), encoding="utf-8", newline="\n")
    result = run(repo, *CHECK)
    expect(result.returncode == 1 and "Drift detected in .claude/settings.json" in result.stderr,
           "a hand-widened Claude allow list is drift", result.stderr[-400:])

    bad = [({"decision": "allow", "claude": ["Bash(ls)"], "codex": grown["policy"][-1]["codex"]},
            "Codex takes no `allow` rule"),
           ({"decision": "forbidden", "reason": "x", "codex": [{"pattern": ["rm"], "match": ["rm x"]}]},
            "each `codex` rule needs exactly"),
           ({"decision": "prompt", "codex": grown["policy"][-1]["codex"]}, "needs a one-line `reason`"),
           ({"decision": "deny", "claude": ["Bash(ls)"]}, "`decision` must be one of"),
           ({"decision": "allow", "claude": ["Bash(ls)"], "owner": "x"}, "unknown key `owner`"),
           ({"decision": "allow"}, "lists no `claude` or `codex` rule")]
    for entry, needle in bad:
        write({**data, "policy": [*data["policy"], entry]})
        result = run(repo, *BRAIN, "sync")
        expect(result.returncode == 1 and needle in result.stderr, f"sync must refuse a policy entry: {needle}",
               result.stderr[-400:])
    # W3 review: a repeated key in one entry silently replaced the first (safe_load keeps
    # the last), so a second `claude:` dropped deny rules without an error.
    write(data)
    text = policy_path.read_text(encoding="utf-8")
    policy_path.write_text(text.replace("  claude:\n", "  claude:\n  - Bash(true)\n  claude:\n", 1),
                           encoding="utf-8", newline="\n")
    for command in ([*BRAIN, "sync"], CHECK):
        result = run(repo, *command)
        expect(result.returncode == 1 and "duplicate key `claude`" in result.stderr,
               f"{'sync' if 'sync' in command else 'check'} must refuse a repeated key in a policy entry", result.stderr[-400:])
    write(data)
    base = repo / "Infrastructure/adapter_configs/claude.settings.json"
    # W3 round 2: json.loads keeps the last of a repeated key, so a second "hooks" object
    # would silently replace the guard hooks.
    original = base.read_text(encoding="utf-8")
    base.write_text('{"hooks": {"PreToolUse": []}, "hooks": {}}', encoding="utf-8", newline="\n")
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 1 and "duplicate key `hooks`" in result.stderr,
           "sync must refuse a repeated key in claude.settings.json", result.stderr[-400:])
    base.write_text(original, encoding="utf-8", newline="\n")
    base.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "hooks": {}}), encoding="utf-8", newline="\n")
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 1 and "without `permissions`" in result.stderr,
           "claude.settings.json may not carry its own permissions", result.stderr[-400:])


def case_codex_description_fallback(repo: Path) -> None:
    """Without `codex.description`, the Codex wrapper uses the shared `description`."""
    rel = AGENT.format("code-reviewer")
    edit_meta(repo, rel, {"codex.description": None})
    shared = brain.split_frontmatter((repo / rel).read_bytes(), rel)[0]["description"]
    toml = brain.tomllib.loads(brain.render(repo).files[".codex/agents/code-reviewer.toml"].data.decode())
    expect(toml.get("description") == shared, "an absent codex.description must fall back to description",
           repr(toml.get("description"))[:200])
    result = run(repo, *BRAIN, "sync")
    expect(result.returncode == 0, "sync must accept an agent without codex.description", result.stderr[-400:])
    for effort in ("none", "minimal", "persistent"):  # the verified Codex enum, beyond Claude's `effort`
        edit_meta(repo, rel, {"codex.reasoning_effort": effort})
        toml = brain.tomllib.loads(brain.render(repo).files[".codex/agents/code-reviewer.toml"].data.decode())
        expect(toml.get("model_reasoning_effort") == effort and not brain.lint_codex_agents(brain.render(repo)),
               f"codex.reasoning_effort `{effort}` must render and pass the lints")


def case_agent_hooks(repo: Path) -> None:
    """An agent's `hooks:` renders into its Claude frontmatter in Claude's nested form, round-trips
    through the lints, stays out of the Codex wrapper, and is validated like every other key."""
    rel = AGENT.format("eig-writer")
    guard = 'python3 "$CLAUDE_PROJECT_DIR/Infrastructure/scripts/hooks/guard_review_write.py"'
    edit_meta(repo, rel, {"hooks": {"PreToolUse": [{"matcher": "Write|Edit|NotebookEdit", "command": guard,
                                                    "timeout": 10}],
                                    "Stop": [{"command": "python3 stop.py"}]}})
    result = run(repo, *BRAIN, "sync")
    text = (repo / ".claude/agents/eig-writer.md").read_text(encoding="utf-8")
    head = yaml.safe_load(text.split("---\n")[1])
    expect(result.returncode == 0 and head.get("hooks") == {
        "PreToolUse": [{"matcher": "Write|Edit|NotebookEdit",
                        "hooks": [{"type": "command", "command": guard, "timeout": 10}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "python3 stop.py"}]}]},
        "an agent's hooks must render in Claude's nested form", result.stderr[-400:] + text[:600])
    toml = (repo / ".codex/agents/eig-writer.toml").read_text(encoding="utf-8")
    expect("hook" not in toml, "Codex has no per-agent hooks, so the wrapper carries none", toml[:400])
    result = run(repo, *CHECK)
    expect(result.returncode == 0, "check must agree with sync about an agent's hooks", result.stderr[-400:])
    expect(not brain.lint_frontmatter(repo / "Infrastructure", brain.render(repo)),
           "rendered hooks must round-trip through the frontmatter lint")
    drifted = brain.render(repo)
    path = ".claude/agents/eig-writer.md"
    drifted.files[path] = brain.Out(drifted.files[path].data.replace(b"timeout: 10", b"timeout: 11"))
    expect(any("hooks do not round-trip" in p for p in brain.lint_frontmatter(repo / "Infrastructure", drifted)),
           "a generated hook that differs from its canonical one must fail the lint")
    for bad, message in (({"PreToolUse": [{"command": guard}]}, "PreToolUse[0].matcher must be"),
                         ({"OnWrite": [{"matcher": "Write", "command": guard}]}, "unknown event `OnWrite`"),
                         ({"PreToolUse": [{"matcher": "Write", "command": guard, "type": "x"}]},
                          "unknown key `type`"),
                         ({"PreToolUse": [{"matcher": "Write", "command": guard, "timeout": 0}]},
                          "timeout must be a positive whole number"),
                         ({"PreToolUse": []}, "must be a non-empty list of hooks"),
                         ("guard", "must be a mapping of hook events")):
        edit_meta(repo, rel, {"hooks": bad})
        result = run(repo, *BRAIN, "sync")
        expect(result.returncode == 1 and message in result.stderr,
               f"an invalid agent hook must be an error: {message}", result.stderr[-400:])


def case_suites_report_by_name(repo: Path) -> None:
    scripts = repo / "Infrastructure" / "scripts"
    (scripts / "test_hooks.py").write_text("raise SystemExit('hook fixture broke')\n", encoding="utf-8", newline="\n")
    (scripts / "test_brain.py").write_text("print('Brain fixture stub passed.')\n", encoding="utf-8", newline="\n")
    result = run(repo, *BRAIN, "check", "--only", "suites")
    expect(result.returncode == 1 and "[hook-tests] FAIL" in result.stderr and "hook fixture broke" in result.stderr
           and "[brain-tests] PASS" in result.stdout, "a failing suite must fail under its own name",
           result.stdout + result.stderr)
    (scripts / "test_brain.py").unlink()
    result = run(repo, *BRAIN, "check", "--only", "suites")
    expect("[brain-tests] FAIL" in result.stderr, "a missing suite must fail under its own name", result.stderr[-400:])

    (scripts / "test_hooks.py").write_text("import time\ntime.sleep(10)\n", encoding="utf-8", newline="\n")
    (scripts / "test_brain.py").write_text("pass\n", encoding="utf-8", newline="\n")
    saved, brain.SUITE_TIMEOUT = brain.SUITE_TIMEOUT, 1
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            code = brain.check(repo, ["suites"])
    finally:
        brain.SUITE_TIMEOUT = saved
    expect(code == 1 and "[hook-tests] FAIL" in stderr.getvalue() and "timed out after 1s" in stderr.getvalue(),
           "a suite timeout must fail under its own name", stderr.getvalue())


def case_environment_is_isolated(_repo: Path) -> None:
    saved = os.environ.get("GIT_DIR")
    os.environ["GIT_DIR"] = "/elsewhere/.git"
    try:
        env = isolated_env()
    finally:
        if saved is None:
            os.environ.pop("GIT_DIR")
        else:
            os.environ["GIT_DIR"] = saved
    expect("GIT_DIR" not in env and env.get("GIT_CONFIG_GLOBAL") == os.devnull,
           "fixture commands must not inherit GIT_* variables or the global git config", repr(env.get("GIT_DIR")))


ROOT_OUTPUTS = ("AGENTS.md", "CLAUDE.md", ".claude/settings.json", ".claude/README.md",
                ".codex/config.toml", ".codex/hooks.json", ".codex/README.md")
# Trees an earlier generator owned (Stage C2 retired them), so a proof across that change sees them.
LEGACY_OUTPUTS = (".claude/commands", ".claude/templates")


def generate_from_scratch(ref: str, dest: Path) -> Path:
    """Export `ref` with git archive, delete every generated path, sync with that ref's own
    brain.py, and copy the generated set (owned trees plus root outputs) into `dest`/out."""
    tree, out, archive = dest / "tree", dest / "out", dest / "export.tar"
    tree.mkdir(parents=True)
    for cmd in (("git", "archive", "--format=tar", "-o", str(archive), ref),
                ("tar", "-xf", str(archive), "-C", str(tree))):
        result = run(REPO_ROOT, *cmd)
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd[:2])} failed: {result.stderr}")
    generated = [*brain.OWNED_DIRS, *LEGACY_OUTPUTS, *brain.RETIRED_DIRS, *ROOT_OUTPUTS, brain.MANIFEST]
    for rel in generated:
        if (tree / rel).is_dir():
            shutil.rmtree(tree / rel)
        elif (tree / rel).exists():
            (tree / rel).unlink()
    result = run(tree, sys.executable, "Infrastructure/scripts/brain.py", "sync")
    if result.returncode != 0:
        raise RuntimeError(f"brain.py sync failed on {ref}: {result.stderr}")
    for rel in generated:
        if (tree / rel).is_dir():
            shutil.copytree(tree / rel, out / rel, symlinks=True)
        elif (tree / rel).exists():
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(tree / rel, out / rel)
    return out


def parity(base: str, head: str) -> int:
    """Zero-diff proof: `base` and `head` must generate the same files, bytes, and modes."""
    with tempfile.TemporaryDirectory() as tmp:
        outs = [generate_from_scratch(ref, Path(tmp) / label) for label, ref in (("base", base), ("head", head))]
        files = [{p.relative_to(o).as_posix(): p for p in o.rglob("*") if p.is_file()} for o in outs]
        diff = run(Path(tmp), "diff", "-r", "-x", brain.MANIFEST, "base/out", "head/out")
        modes = [rel for rel in sorted(files[0].keys() & files[1].keys())
                 if brain.mode_of(files[0][rel]) != brain.mode_of(files[1][rel])]
        manifests = []
        for ref, found in ((base, files[0]), (head, files[1])):
            if brain.MANIFEST not in found:
                manifests.append((True, f"{ref}: no {brain.MANIFEST} (a commit from before Stage C1)"))
                continue
            listed = {line for line in found[brain.MANIFEST].read_text(encoding="utf-8").splitlines()
                      if line and not line.startswith("#")}
            generated = set(found)
            manifests.append((listed == generated, f"{ref}: {brain.MANIFEST} lists exactly its {len(generated)} "
                              "generated files" if listed == generated else f"{ref}: {brain.MANIFEST} does not "
                              f"match; unlisted {sorted(generated - listed)}, not generated {sorted(listed - generated)}"))
        print(f"Generated {len(files[0])} file(s) from {base} and {len(files[1])} from {head}, each from scratch.")
        print(f"== diff -r base head, except {brain.MANIFEST} (content and file set)\n{diff.stdout or '0 differences'}")
        print("== permission bits\n" + ("\n".join(modes) or "0 differences"))
        print("== manifests\n" + "\n".join(line for _, line in manifests))
        same = diff.returncode == 0 and not modes and all(ok for ok, _ in manifests)
        print("ZERO DIFF: identical generated output." if same else "PARITY FAILED.")
        return 0 if same else 1


def main() -> int:
    if shutil.which("git") is None:
        print("Brain fixture suite skipped: git is not available.")
        return 0
    if sys.argv[1:2] == ["--parity"]:  # test_brain.py --parity [BASE [HEAD]], default main HEAD
        return parity(*(sys.argv[2:4] + ["main", "HEAD"][len(sys.argv[2:4]):]))
    cases = (case_sync_is_idempotent, case_check_reports_drift_missing_and_unowned,
             case_manifest_ownership, case_missing_metadata_is_an_error, case_lints,
             case_metadata_lints, case_generation_errors, case_output_lints,
             case_absent_hint_is_no_hint, case_claude_surface, case_rule_load_tiers,
             case_load_budget_anchors_and_map, case_permission_policy,
             case_codex_description_fallback, case_agent_hooks,
             case_suites_report_by_name,
             case_environment_is_isolated)
    with tempfile.TemporaryDirectory() as tmp:
        template = make_copy(Path(tmp) / "template")
        for index, case in enumerate(cases):
            repo = Path(tmp) / f"case{index}"
            shutil.copytree(template, repo, symlinks=True)
            try:
                case(repo)
            except Exception as exc:  # a crash in one case must not hide the others
                expect(False, f"{case.__name__} raised", repr(exc))
    if failures:
        print(f"Brain fixture suite FAILED: {len(failures)} of {checks_run} check(s).", file=sys.stderr)
        print("".join(f"- {item}\n" for item in failures), end="", file=sys.stderr)
        return 1
    print(f"Brain fixture suite passed ({checks_run} checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
