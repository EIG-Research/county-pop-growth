#!/usr/bin/env python3
"""Test suite for the template port script, `port_template.py`.

`python3 Infrastructure/scripts/test_port_template.py` from anywhere. Each case builds a
fixture repository in a temporary directory and calls the real script's `main()` with a stub
in place of the GitHub lookup. The stub is passed as an argument, so the command line has no
way to skip the visibility guard. The template source is this checkout's committed HEAD.
One `PASS` line per case:

     1  Public refused            a PUBLIC or INTERNAL repository is refused, dry run included,
                                  and nothing in the target changes
     2  Lookup failure refused    a failed `gh repo view` refuses rather than guessing
     3  Archived refused          an archived private repository is refused
     4  Owner refused             an owner that is not EIG-Research or in the config is refused
     5  Skip list and replication a skip-listed repository and a `*-replication` one are refused
     6  Dirty tree refused        an uncommitted change to a tracked file is refused
     7  Template refused          this template, an unreset copy, no origin, and a run from a
                                  project's copy (not the source template) are refused
     8  Untracked conflict        an untracked file where the port writes (a generated file, or
                                  a root .gitignore) is refused and left untouched
     9  Adopt                     legacy AI files move to legacy-ai/, the project lane and README
                                  are untouched, no worked example is copied, a project Makefile
                                  stays with the template's beside it, PROJECT.md, .eig-port, and
                                  both managed blocks are written, one commit with no AI trailer,
                                  and the ledger gets a row
    10  Upgrade                   a template-written stale file is replaced, a project edit is
                                  saved to legacy-ai/ and flagged as the template copy goes in, a
                                  retired template file is deleted, a project
                                  reference entry and the project's records are kept, an
                                  old-layout plan moves to records/, a stale generated adapter
                                  file goes, unknown old-manifest and retired-surface files move
                                  to legacy-ai/ while an unlisted project agent stays, and the
                                  managed block is replaced rather than duplicated
    11  Rollback                  a failure before the commit (an oversized file) restores the
                                  target's branch, files, and status exactly
    12  Remote URLs               a look-alike host, a github.com path on another host, and a
                                  push URL naming another repository are refused; the ssh form
                                  is accepted

In a project (no template marker) the suite prints SKIPPED and exits 0: the port runs only from
the source template. No network: git runs with a throwaway global config, and GitHub is never
called. Exit codes:
0 every case passed; 1 a case failed.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import port_template as port  # noqa: E402

TIME_LIMIT_SECONDS = 240


class CaseFailure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CaseFailure(message)


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, encoding="utf-8", check=True).stdout


def lookup(visibility: str = "PRIVATE", archived: bool = False) -> Callable[[str], dict]:
    def stub(slug: str) -> dict:
        return {"visibility": visibility, "isArchived": archived, "nameWithOwner": slug}
    return stub


def failing_lookup(slug: str) -> dict:
    raise port.PortRefused(f"G1: `gh repo view {slug}` failed, so its visibility is unknown: offline")


def fixture(work: Path, slug: str = "bnglasner/legacy-study", files: dict[str, str] | None = None) -> Path:
    root = work / slug.split("/")[1]
    defaults = {
        "README.md": "# Legacy study\n",
        "Code/analysis.R": "x <- 1\n",
        "CLAUDE.md": "# Old instructions\nUse Code/analysis.R.\n",
        ".claude/agents/old-helper.md": "---\nname: old-helper\n---\nOld agent.\n",
        ".gitignore": "*.Rhistory\n",
    }
    for rel, text in (defaults if files is None else files).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    root.mkdir(parents=True, exist_ok=True)
    sh(root, "init", "-q", "-b", "main")
    sh(root, "add", "-A")
    sh(root, "commit", "-q", "-m", "legacy history")
    sh(root, "remote", "add", "origin", f"https://github.com/{slug}.git")
    return root


def config(work: Path, *lines: str) -> Path:
    path = work / "port_config.txt"
    path.write_text("owner: bnglasner\n" + "".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def run(target: Path, work: Path, *extra: str, stub=None, known: set[str] | None = None,
        cfg: Path | None = None) -> tuple[int, str]:
    argv = [str(target), "--ref", "HEAD", "--skip-checks", "--config", str(cfg or config(work)),
            "--ledger", str(work / "ledger.tsv"), *extra]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = port.main(argv, lookup=stub or lookup(), known_extra=known)
    return code, out.getvalue()


def state(target: Path) -> tuple[str, str, str, list[str]]:
    """Branch, HEAD, porcelain status (untracked included), and every file on disk."""
    files = sorted(p.relative_to(target).as_posix() for p in target.rglob("*")
                   if p.is_file() and ".git" not in p.relative_to(target).parts[:1])
    return (sh(target, "branch", "--show-current"), sh(target, "rev-parse", "HEAD"),
            sh(target, "status", "--porcelain", "--untracked-files=all"), files)


def blob_sha(text: str) -> str:
    # Bytes in, so Windows text mode cannot turn the newline into CRLF and change the hash.
    return subprocess.run(["git", "hash-object", "--stdin"], input=text.encode("utf-8"), capture_output=True,
                          check=True).stdout.decode().strip()


# --------------------------------------------------------------------------- cases
def case_public(work: Path) -> str:
    target = fixture(work)
    before = state(target)
    for visibility in ("PUBLIC", "INTERNAL"):
        for extra in ((), ("--dry-run",)):
            code, out = run(target, work, *extra, stub=lookup(visibility))
            check(code == 1 and "G1" in out and "not PRIVATE" in out, f"{visibility} {extra}: {out}")
    check(state(target) == before, "a refused port changed the target")
    return "PUBLIC and INTERNAL refused, dry run too; target unchanged"


def case_lookup_failure(work: Path) -> str:
    code, out = run(fixture(work), work, stub=failing_lookup)
    check(code == 1 and "visibility is unknown" in out, out)
    return "an unanswered lookup refuses"


def case_archived(work: Path) -> str:
    code, out = run(fixture(work), work, stub=lookup(archived=True))
    check(code == 1 and "archived" in out, out)
    return "archived refused"


def case_owner(work: Path) -> str:
    code, out = run(fixture(work, "SomeColleague/study"), work)
    check(code == 1 and "G2" in out, out)
    code, out = run(fixture(work / "no-config"), work, cfg=work / "missing.txt")
    check(code == 1 and "G2" in out, f"with no config, only EIG-Research passes: {out}")
    return "colleague's repository refused; with no config, bnglasner is refused too"


def case_skip(work: Path) -> str:
    code, out = run(fixture(work), work, cfg=config(work, "skip: bnglasner/Legacy-Study"))
    check(code == 1 and "G4" in out and "skip list" in out, f"skip list, case-insensitive: {out}")
    bom = work / "bom_config.txt"
    bom.write_bytes("skip: bnglasner/legacy-study\nowner: bnglasner\n".encode("utf-8-sig"))
    code, out = run(work / "legacy-study", work, cfg=bom)
    check(code == 1 and "skip list" in out, f"a BOM before the first skip line hid it: {out}")
    code, out = run(fixture(work, "EIG-Research/some-study-replication"), work)
    check(code == 1 and "replication" in out, out)
    return "skip list (BOM-safe) and replication name refused"


def case_dirty(work: Path) -> str:
    target = fixture(work)
    (target / "Code/analysis.R").write_text("x <- 2\n", encoding="utf-8")
    code, out = run(target, work)
    check(code == 1 and "uncommitted" in out, out)
    return "uncommitted tracked change refused"


def case_template(work: Path) -> str:
    code, out = run(port.TEMPLATE_ROOT, work)
    check(code == 1 and "this template" in out, f"the template itself: {out}")
    target = fixture(work)
    (target / port.TEMPLATE_MARKER).parent.mkdir(parents=True)
    (target / port.TEMPLATE_MARKER).write_text("marker\n", encoding="utf-8")
    code, out = run(target, work)
    check(code == 1 and "template-reset" in out, f"an unreset copy: {out}")
    bare = fixture(work / "bare")
    sh(bare, "remote", "remove", "origin")
    code, out = run(bare, work)
    check(code == 1 and "no origin" in out, f"no origin: {out}")
    project = fixture(work / "source")  # a ported project's copy: no template marker
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = port.main([str(fixture(work / "dest")), "--ref", "HEAD", "--skip-checks", "--dry-run",
                          "--config", str(config(work))], lookup=lookup(), template=project)
    check(code == 1 and "source template checkout" in buffer.getvalue(),
          f"a port run from a project's copy was not refused: {buffer.getvalue()}")
    return "template, unreset copy, and missing origin refused"


def case_untracked_conflict(work: Path) -> str:
    target = fixture(work)
    (target / ".claude/settings.json").write_text("{}\n", encoding="utf-8")
    before = state(target)
    code, out = run(target, work)
    check(code == 1 and ".claude/settings.json" in out and "untracked" in out, out)
    check(state(target) == before, "the untracked file or the target changed")
    files = {"README.md": "# Study\n", "Code/analysis.R": "x <- 1\n"}
    other = fixture(work / "ignore", files=files)
    (other / ".gitignore").write_text("data/\n", encoding="utf-8")
    before = state(other)
    code, out = run(other, work)
    check(code == 1 and ".gitignore" in out, f"an untracked .gitignore was not protected: {out}")
    check(state(other) == before, "the untracked .gitignore changed")
    return "untracked generated file and untracked .gitignore refused and kept"


def case_adopt(work: Path) -> str:
    target = fixture(work, files={
        "README.md": "# Legacy study\n",
        "Code/analysis.R": "x <- 1\n",
        "Data/README.md": "data notes\n",
        "CLAUDE.md": "# Old instructions\n",
        ".claude/agents/old-helper.md": "old agent\n",
        "Makefile": "all:\n\tRscript Code/analysis.R\n",
        ".gitignore": "*.Rhistory\n",
    })
    (target / ".claude/settings.local.json").write_text("{}\n", encoding="utf-8")  # untracked, personal
    head = sh(target, "rev-parse", "HEAD").strip()
    code, out = run(target, work)
    check(code == 0, f"adopt failed: {out}")
    check(sh(target, "branch", "--show-current").strip() == port.BRANCH, "not on the port branch")
    check(sh(target, "rev-parse", "HEAD~1").strip() == head, "the port is not exactly one commit")
    message = sh(target, "log", "-1", "--format=%B")
    check("Co-Authored-By" not in message and "Claude" not in message, f"AI attribution: {message}")
    changed = sh(target, "diff", "--name-only", head, "HEAD").splitlines()
    check(not any(p.startswith(("Code/", "Data/")) or p == "README.md" for p in changed),
          f"the project lane or README changed: {[p for p in changed if not p.startswith(('Infra', '.'))][:10]}")
    for legacy in ("CLAUDE.md", ".claude/agents/old-helper.md"):
        check((target / port.LEGACY_DIR / legacy).is_file(), f"{legacy} was not moved to legacy-ai/")
    check((target / ".claude/settings.local.json").is_file(), "personal settings were moved")
    check(not (target / ".claude/agents/old-helper.md").exists(), "the legacy agent stayed in .claude/")
    check(not any((target / p).exists() for p in ("code/run_all.R", "data/example", "drafts/example_note.md")),
          "the worked example was copied")
    check((target / "Makefile").read_text(encoding="utf-8").startswith("all:"), "the project's Makefile changed")
    check((target / "Makefile.eig-template").is_file() and "Makefile" in out, "no side-by-side Makefile flag")
    for rel in ("AGENTS.md", "CLAUDE.md", "Infrastructure/scripts/brain.py", ".claude/settings.json",
                ".brain-manifest", "records/README.md", "records/plans/README.md"):
        check(rel in sh(target, "ls-files", rel), f"{rel} is not committed")
    check(not (target / port.TEMPLATE_MARKER).exists(), "the template marker shipped")
    check(not (target / "Infrastructure/local").exists() or not sh(target, "ls-files", "Infrastructure/local"),
          "operator-local files shipped")
    check(not (target / ".github/workflows/maintenance-check.yml").exists(), "the template CI shipped")
    project = (target / "PROJECT.md").read_text(encoding="utf-8")
    check("`TBD`" in project and "legacy-ai/" in project, "PROJECT.md lacks the TBD title or the legacy pointer")
    marker = (target / port.PORT_MARKER).read_text(encoding="utf-8")
    check("mode: adopt" in marker and "project_lane: legacy" in marker, f"marker: {marker}")
    for name in (".gitattributes", ".gitignore"):
        text = (target / name).read_text(encoding="utf-8")
        check(text.count(port.BLOCK_START) == 1, f"{name} block missing or doubled")
    check("*.Rhistory" in (target / ".gitignore").read_text(encoding="utf-8"), "the project's ignore lines were lost")
    check("* text=auto eol=lf" not in (target / ".gitattributes").read_text(encoding="utf-8").splitlines(),
          "the whole repository was switched to LF")
    drift = subprocess.run([sys.executable, str(target / "Infrastructure/scripts/brain.py"), "check", "--only", "drift"],
                           cwd=target, capture_output=True, text=True)
    check(drift.returncode == 0, f"brain drift check fails in the target: {drift.stdout[-800:]}{drift.stderr[-800:]}")
    paths = subprocess.run([sys.executable, str(target / "Infrastructure/scripts/check_internal_path_references.py")],
                           cwd=target, capture_output=True, text=True)
    check(paths.returncode == 0, f"path check fails in the target: {paths.stderr[-1200:]}")
    check(not sh(target, "status", "--porcelain", "--untracked-files=no").strip(), "tracked files left uncommitted")
    ledger = (work / "ledger.tsv").read_text(encoding="utf-8").splitlines()
    check(ledger[0].startswith("date\t") and "\tported\t" in ledger[-1], f"ledger: {ledger[-1:]}")
    return "legacy moved, lane untouched, machinery committed, drift and path checks pass"


def case_upgrade(work: Path) -> str:
    target = fixture(work)
    code, out = run(target, work)
    check(code == 0, f"setup adopt failed: {out}")
    sh(target, "checkout", "-q", "main")
    sh(target, "merge", "-q", "--ff-only", port.BRANCH)
    sh(target, "branch", "-q", "-d", port.BRANCH)
    old_text, edit_text, retired_text = "old template wording\n", "a project's own rule edit\n", "retired rule\n"
    stale, edited = "Infrastructure/rules/session-logging.md", "Infrastructure/AUTHORING.md"
    retired, reference = "Infrastructure/rules/retired-rule.md", "Infrastructure/references/literature/summaries/mine.md"
    log = "/".join(("records", "session_logs", "2026-01-01_project.md"))  # joined: the path check flags dated records
    old_plan, old_generated = "Infrastructure/plans/old-plan.md", ".codex/commands/cite.md"
    stale_adapter, own_agent = ".claude/commands/cite.md", ".claude/agents/my-own-helper.md"
    for rel, text in ((stale, old_text), (edited, edit_text), (retired, retired_text),
                      (reference, "project summary\n"), (log, "- Goal: keep me\n"),
                      (old_plan, "# An old-layout plan\n"), (old_generated, "retired surface\n"),
                      (stale_adapter, "old generated command\n"), (own_agent, "the project's agent\n")):
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        (target / rel).write_text(text, encoding="utf-8", newline="\n")
    # An older generator listed a file the current one no longer makes, and the project edited it:
    # sync would delete it, so the port must move it to legacy-ai/ first.
    listed = ".claude/commands/legacy-cmd.md"
    (target / listed).write_text("the project's edit of an old generated command\n", encoding="utf-8", newline="\n")
    manifest = target / port.MANIFEST
    manifest.write_text(manifest.read_text(encoding="utf-8") + listed + "\n", encoding="utf-8", newline="\n")
    # A retired template README in a folder the project still files its own work in stays.
    lane_readme, lane_note = "Infrastructure/explorations/README.md", "Infrastructure/explorations/my-notes.md"
    # An older generation's rule this template never shipped, with no frontmatter: sync rejects
    # it, so the port must set it aside in legacy-ai/ and sync again.
    old_rule = "Infrastructure/rules/old-governance.md"
    for rel, text in ((lane_readme, "explorations lane\n"), (lane_note, "the project's exploration\n"),
                      (old_rule, "# Old governance\n")):
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        (target / rel).write_text(text, encoding="utf-8", newline="\n")
    # A project negation after the managed block must keep winning.
    gitignore = target / ".gitignore"
    gitignore.write_text(gitignore.read_text(encoding="utf-8") + "!review-reports/\n", encoding="utf-8", newline="\n")
    sh(target, "add", "-A")
    sh(target, "commit", "-q", "-m", "project work on an older template")
    known = {(stale, blob_sha(old_text)), (retired, blob_sha(retired_text)),
             (stale_adapter, blob_sha("old generated command\n")), (lane_readme, blob_sha("explorations lane\n"))}
    code, out = run(target, work, known=known)
    check(code == 0 and "Mode: upgrade" in out, f"upgrade failed: {out}")
    check(not (target / old_rule).exists() and (target / port.LEGACY_DIR / old_rule).is_file()
          and old_rule in sh(target, "log", "-1", "--format=%B"),
          "a rule that stops sync was not moved to legacy-ai/ and flagged in the commit")
    check((target / lane_readme).is_file() and (target / lane_note).is_file(),
          "a retired README was deleted from a folder the project still uses")
    ignore_text = (target / ".gitignore").read_text(encoding="utf-8")
    check(ignore_text.startswith(port.BLOCK_START) and ignore_text.rstrip().endswith("!review-reports/"),
          "the managed .gitignore block is not first, so it overrides the project's own rules")
    check((target / "records/plans/old-plan.md").is_file() and not (target / old_plan).exists(),
          "an old-layout plan did not move to records/plans/")
    check(not (target / old_generated).exists() and (target / port.LEGACY_DIR / old_generated).is_file()
          and old_generated in out, "an unknown file on a retired Codex surface was not moved to legacy-ai/ and flagged")
    check(not (target / stale_adapter).exists(), "a stale template-generated adapter file was kept")
    check((target / own_agent).is_file(), "the project's own unlisted adapter file was moved or deleted")
    check((target / port.LEGACY_DIR / listed).is_file() and listed in out,
          "an old-manifest file with project content was not moved to legacy-ai/ and flagged before sync")
    check("legacy-ai/" not in (target / "PROJECT.md").read_text(encoding="utf-8")
          or (target / port.LEGACY_DIR).is_dir(), "PROJECT.md points at a legacy-ai/ that does not exist")
    template_stale = subprocess.run(["git", "show", f"HEAD:{stale}"], cwd=port.TEMPLATE_ROOT,
                                    capture_output=True, encoding="utf-8", check=True).stdout
    check((target / stale).read_text(encoding="utf-8") == template_stale, "a template-written file was not replaced")
    template_edited = subprocess.run(["git", "show", f"HEAD:{edited}"], cwd=port.TEMPLATE_ROOT,
                                     capture_output=True, encoding="utf-8", check=True).stdout
    check((target / edited).read_text(encoding="utf-8") == template_edited,
          "stale machinery matching no shipped version was not replaced")
    check((target / port.LEGACY_DIR / edited).read_text(encoding="utf-8") == edit_text and edited in out,
          "the project's copy of replaced machinery was not saved to legacy-ai/ and flagged")
    check(not (target / retired).exists(), "a retired template file was not deleted")
    check((target / reference).is_file() and (target / log).is_file(), "a reference entry or record was lost")
    check(not (target / port.LEGACY_DIR / "AGENTS.md").exists(), "the upgrade moved files to legacy-ai/")
    text = (target / ".gitignore").read_text(encoding="utf-8")
    check(text.count(port.BLOCK_START) == 1, "the managed block was duplicated")
    return "stale replaced, edit kept and flagged, retired deleted, references and records kept"


def case_rollback(work: Path) -> str:
    target = fixture(work)
    (target / "notes.txt").write_text("an untracked note of the user's\n", encoding="utf-8")
    before = state(target)
    limit = port.SIZE_LIMIT
    port.SIZE_LIMIT = 1024  # the template's own scripts exceed this, so the size guard fires
    try:
        code, out = run(target, work)
    finally:
        port.SIZE_LIMIT = limit
    check(code == 1 and "FAILED" in out and "restored" in out, out)
    after = state(target)
    check(after == before, f"the target was not restored: {set(after[3]) ^ set(before[3])} {after[2]!r}")
    check(port.BRANCH not in sh(target, "branch"), "the port branch was left behind")
    ledger = (work / "ledger.tsv").read_text(encoding="utf-8")
    check("\tfailed\t" in ledger, "the failure was not recorded")
    return "branch, files, and untracked note exactly as before"


def case_remote_urls(work: Path) -> str:
    target = fixture(work)
    for url in ("https://evilgithub.com/bnglasner/legacy-study.git",
                "https://gitlab.com/github.com/bnglasner/legacy-study.git"):
        sh(target, "remote", "set-url", "origin", url)
        code, out = run(target, work, "--dry-run")
        check(code == 1 and "not a github.com repository" in out, f"{url}: {out}")
    sh(target, "remote", "set-url", "origin", "git@github.com:bnglasner/legacy-study.git")
    code, out = run(target, work, "--dry-run")
    check(code == 0 and "bnglasner/legacy-study" in out, f"the ssh form was refused: {out}")
    sh(target, "remote", "set-url", "--push", "origin", "https://github.com/bnglasner/public-copy.git")
    code, out = run(target, work, "--dry-run")
    check(code == 1 and "different repositories" in out, f"a push URL to another repository passed: {out}")
    return "look-alike hosts and a foreign push URL refused; ssh accepted"


CASES: list[tuple[str, Callable[[Path], str]]] = [
    ("Public refused", case_public),
    ("Lookup failure refused", case_lookup_failure),
    ("Archived refused", case_archived),
    ("Owner refused", case_owner),
    ("Skip list and replication", case_skip),
    ("Dirty tree refused", case_dirty),
    ("Template refused", case_template),
    ("Untracked conflict", case_untracked_conflict),
    ("Adopt", case_adopt),
    ("Upgrade", case_upgrade),
    ("Rollback", case_rollback),
    ("Remote URLs", case_remote_urls),
]


def main() -> int:
    if not (port.TEMPLATE_ROOT / port.TEMPLATE_MARKER).is_file():
        # The port ships the source template's committed tree and refuses to run anywhere else, so
        # in a project (where `make template-reset` removed the marker) there is nothing to test.
        print("SKIPPED: the port runs only from the source template checkout; this is a project")
        return 0
    if shutil.which("git") is None:
        print("git is required")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="port-template-test-"))
    gitconfig = tmp / "gitconfig"
    gitconfig.write_text("[user]\n\tname = Port Test\n\temail = port-test@example.invalid\n"
                         "[init]\n\tdefaultBranch = main\n[core]\n\tautocrlf = false\n", encoding="utf-8")
    saved = {k: os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
    os.environ.update(GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1")
    failures, start = 0, time.monotonic()
    try:
        for number, (title, fn) in enumerate(CASES, 1):
            work = tmp / f"case{number}"
            work.mkdir()
            try:
                print(f"PASS  {number:>2}  {title}  ({fn(work)})", flush=True)
            except CaseFailure as exc:
                failures += 1
                print(f"FAIL  {number:>2}  {title}: {exc}", flush=True)
            except Exception:  # an unexpected error is a failure with its traceback
                failures += 1
                print(f"FAIL  {number:>2}  {title}: unexpected error", flush=True)
                traceback.print_exc()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)
    seconds = time.monotonic() - start
    if seconds > TIME_LIMIT_SECONDS:
        failures += 1
        print(f"FAIL  the suite took {seconds:.0f}s, over its {TIME_LIMIT_SECONDS}s limit")
    print(f"{len(CASES) - failures}/{len(CASES)} cases passed in {seconds:.1f}s")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
