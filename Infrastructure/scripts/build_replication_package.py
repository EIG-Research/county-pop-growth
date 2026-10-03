#!/usr/bin/env python3
"""Export a public-safe replication package from a research project.

The export is a fresh git repository outside the source repository. It never receives the
source `.git/` or the proprietary shell (`Infrastructure/`, `.claude/`, `.codex/`,
`.agents/`), and no remote is added and nothing is pushed. The allowlist and denylist
live in `validate_replication_manifest.py`; the binding rules are
`Infrastructure/rules/replication-publishing-rules.md`.

Usage:
    python3 Infrastructure/scripts/build_replication_package.py <target-dir> \
        [--dry-run] [--out <path>] [--allow-unsafe] [--yes]

    --dry-run       Print the include/exclude census and scan summary; change nothing.
    --out <path>    Output directory (overrides the manifest's output_dir and the default).
    --allow-unsafe  Finalize despite HIGH or CRITICAL findings (a human-authorized
                    override, recorded in the export's manifest summary). It never admits
                    a symlink: those are refused outright.
    --yes           Skip the confirmation prompt. Required when stdin is not a terminal
                    (an agent confirms with the user in chat, then passes it).

Binary files: a file with a NUL byte in its first 8 KB is treated as binary and skipped by
every text family. It is a finding of its own (RP-4e, owner default O8): MEDIUM when the
manifest opted into it (a data flag or an exact `include`), none for an image or PDF under
`output/figures/` or `output/tables/`, and HIGH anywhere else. A file over 50 MB is MEDIUM, and one of 100 MB or
more is HIGH, because GitHub refuses it.

The generated README.md, DATA.md, and CITATION.cff are scanned too: they carry text from
PROJECT.md, the project's dataset overlay, and the manifest. The overlay itself is scanned as
the source of DATA.md, though it does not ship unless the manifest includes it.

Exit codes: 0 built, dry run done, or declined at the prompt; 1 blocked or failed;
2 usage error, or no terminal to confirm on and no --yes; 3 manifest seeded, review it.

Finalize stages the export in a 0700 temporary sibling of the output directory and moves
it into place only once everything succeeded, so a failure leaves no half-built export.
`git` is run from PATH.

Dependencies: Python 3.11+, PyYAML, and git.
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = SCRIPT_DIR / "replication_assets"
sys.path.insert(0, str(SCRIPT_DIR))

import validate_replication_manifest as vrm  # noqa: E402  (exits 2 without PyYAML)

import yaml  # noqa: E402

RULE = "=" * 62
SEP = "-" * 62
BINARY_PROBE_BYTES = 8192
MB = 1024 * 1024
PUBLICATION_DIRS = ("output/figures", "output/tables")
# Binary files expected there: images and PDFs. Binary data (.dta, .parquet, .rds) under
# output/tables/ is still a finding, since a "table" can be microdata.
FIGURE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".eps", ".pdf",
                   ".svg")
REGISTRY = Path("Infrastructure/references/datasets/registry.yaml")
# The project's own dataset documentation (data-documentation-rules.md DD-4); DATA.md's rows.
OVERLAY = Path("data/docs/dataset-registry.yaml")
TO_CONFIRM = "`[to confirm]`"

# RP-4 grep families: (severity, family, pattern). The credential assignments that need
# lookarounds and value checks come from the validator's scan_secrets, also CRITICAL.
SCAN_FAMILIES = (
    ("CRITICAL", "secret/credential",
     re.compile(r"AKIA[0-9A-Z]{16}|(ghp_|github_pat_)[A-Za-z0-9_]+|xox[baprs]-[A-Za-z0-9-]+"
                r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
                # OpenAI (sk-, sk-proj-) and Google API keys. The lookbehind keeps words
                # that end in "sk" (risk-, task-) out.
                r"|(?<![\w-])sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"
                r"|AIza[0-9A-Za-z_-]{35}")),
    # A home directory, any drive letter (`D:/`, `E:\`), `~/`, or a UNC share. The
    # lookbehinds keep `https://` and `a:b` out. A UNC share is `\\host\share\` as written,
    # or `\\\\host\\share` escaped in a string, so `"\\hline\n"` and `"\\bword\\b"` are not.
    ("HIGH", "absolute/user path",
     re.compile(r"/Users/[A-Za-z]|/home/[A-Za-z]|(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
                # `~/.Renviron` and `~/.Rprofile` are exempt (owner default): they are
                # where R keeps API keys, so naming them is advice, not a leaked path.
                r"|(?<![\w~])~[\\/](?!\.R(?:environ|profile)\b)"
                r"|(?:^|[\s\"'(=,])(?:\\{4}[A-Za-z0-9][\w.$-]+\\{2}[\w.$-]+"
                r"|\\{2}[A-Za-z0-9][\w.$-]+\\(?!\\)[\w.$-]+\\(?!\\))")),
    # A dot directory counts only where a path can start, so `df.agents` and
    # `obj.claude_model` are attribute access, while `../.agents/` and `".claude"` are not.
    # Case is ignored, as in the denylist: `.Claude/` is `.claude/` on a case-insensitive disk.
    ("HIGH", "shell reference",
     re.compile(r"Infrastructure/|(?<![\w.])\.(?:claude|codex|agents)(?![\w-])"
                r"|CLAUDE\.md|AGENTS\.md|\bEIG template\b", re.I)),
    ("MEDIUM", "email/PII", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    # A North American number: (202) 555-0142, 202-555-0142, +1 202.555.0142. Bare digit
    # runs and dates are not phones.
    ("MEDIUM", "phone/PII",
     re.compile(r"(?<![\w.+-])(?:\+?1[ .-]?)?(?:\(\d{3}\)\s?|\d{3}[-.])\d{3}[-.]\d{4}(?![\w.])")),
)
CENSUS_DENY_DIRS = ("Infrastructure", "records", ".claude", ".codex", ".agents", ".git", "drafts",
                    "output/logs", "review-reports", "data/raw", "data/processed")
CENSUS_DENY_FILES = ("CLAUDE.md", "AGENTS.md", "Makefile")


class Stop(Exception):
    """End the run: print `message` to stderr (when given) and exit with `code`."""

    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(message)
        self.code = code


def err(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- inputs
def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="build_replication_package.py", allow_abbrev=False,
                                 description="Export a public-safe replication package.")
    ap.add_argument("target")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--allow-unsafe", action="store_true")
    ap.add_argument("--yes", "-y", action="store_true")
    return ap.parse_args(argv)  # a usage error exits 2


def load_manifest(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise Stop(1, f"ERROR: Manifest is not valid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise Stop(1, "ERROR: Manifest top level must be a mapping of keys to values.")
    errors = vrm.validate(data)
    if errors:
        raise Stop(1, "\n".join(f"ERROR: {e}" for e in errors))
    return data


def output_path(requested: str, target: Path) -> tuple[Path, Path]:
    """(parent, output) as physical paths. The parent must exist; the output need not."""
    raw = requested.rstrip("/") or requested
    parent_text = os.path.dirname(raw) or "."
    if not os.path.isdir(parent_text):
        raise Stop(2, f"Output parent directory does not exist: {parent_text}")
    parent = Path(os.path.realpath(parent_text))
    return parent, parent / os.path.basename(raw)


def check_history_safety(out: Path, parent: Path, target: Path) -> None:
    """RP-1: the export is a fresh directory outside the source repo, by identity."""
    if out.is_symlink():
        raise Stop(1, f"RP-1 violation: output directory is a symlink ({out}); pass the real path.")
    if f"{out}/".startswith(f"{target}/"):
        raise Stop(1, f"RP-1 violation: output directory is inside the source repo ({out}).")
    if out.exists() and os.path.samefile(out, target):
        raise Stop(1, f"RP-1 violation: output directory is the source repo ({out}).")
    # Identity, not strings: on a case-insensitive filesystem .../PROJ/pkg is inside .../proj.
    here = parent
    while True:
        if os.path.samefile(here, target):
            raise Stop(1, f"RP-1 violation: output directory is inside the source repo ({out} "
                          f"is under {here}, which is {target}).")
        if here == here.parent:
            break
        here = here.parent
    if (out / ".git").is_dir():
        raise Stop(1, f"RP-1 violation: output directory already contains a .git/ ({out}).")
    if out.exists() and not out.is_dir():
        raise Stop(1, f"ERROR: output path exists and is not a directory ({out}).")
    if out.is_dir() and any(out.iterdir()):
        raise Stop(1, f"ERROR: output directory already exists and is not empty ({out}). Choose "
                      f"a new --out path or remove it; the export must be a fresh directory.")


# --------------------------------------------------------------------------- scan
def is_binary(path: Path) -> bool:
    with path.open("rb") as fh:
        return b"\0" in fh.read(BINARY_PROBE_BYTES)


def text_rows(name: str, text: str) -> set[str]:
    """The grep families over one text, split on LF only, as grep reads it."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return {f"{sev}\t{family}\t{name}\t{n}:{line}" for sev, family, pattern in SCAN_FAMILIES
            for n, line in enumerate(lines, 1) if pattern.search(line)}


def opted_in(rel: str, data: dict) -> bool:
    """The manifest asked for this file: a data flag covers it, or `include` names it."""
    return (bool(data.get("include_raw_data")) and vrm._denied(rel, "data/raw")) \
        or (bool(data.get("include_processed_data")) and vrm._denied(rel, "data/processed")) \
        or rel in {vrm._norm(x) for x in data.get("include") or []}


def file_rows(target: Path, rel: str, data: dict) -> set[str]:
    """RP-4e, owner default O8: size, then binary content."""
    rows = set()
    size = (target / rel).stat().st_size
    if size >= 100 * MB:
        rows.add(f"HIGH\toversized file\t{rel}\t0:{size} bytes; GitHub refuses a file of 100 MB "
                 f"or more")
    elif size > 50 * MB:
        rows.add(f"MEDIUM\toversized file\t{rel}\t0:{size} bytes; consider Git LFS or excluding it")
    if not is_binary(target / rel):
        text = (target / rel).read_bytes().decode("utf-8", errors="replace")
        return rows | text_rows(rel, text)
    if any(vrm._under(rel, d) for d in PUBLICATION_DIRS) and rel.lower().endswith(FIGURE_SUFFIXES):
        return rows
    sev, why = ("MEDIUM", "the manifest opted into it") if opted_in(rel, data) \
        else ("HIGH", "nothing in the manifest asked for it")
    rows.add(f"{sev}\tbinary file\t{rel}\t0:binary content (a NUL byte in the first 8 KB); {why}")
    return rows


def scan(target: Path, included: list[str], data: dict, generated: dict[str, str]) -> list[str]:
    """RP-4 findings as sorted, unique `severity<TAB>family<TAB>file<TAB>line:text` rows."""
    rows = set()
    for rel in included:
        try:
            rows |= file_rows(target, rel, data)
        except OSError as exc:
            rows.add(f"HIGH\tunreadable file\t{rel}\t0:{exc}")
    # The overlay is DATA.md's source, so a key anywhere in it blocks even when the field
    # holding it never reaches the table.
    try:
        overlay = (target / OVERLAY).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        overlay = ""
    if overlay:
        label = f"{OVERLAY.as_posix()} (DATA.md source)"
        rows |= text_rows(label, overlay)
        for hit in vrm.scan_secret_text(OVERLAY.as_posix(), overlay):
            rows.add(f"CRITICAL\tsecret/credential\t{label}\t{hit.split(chr(9), 1)[1]}")
    # The generated files carry text from PROJECT.md, the overlay, and the manifest, so
    # they get every family, credentials included, before anything is committed.
    for name in ("README.md", "DATA.md", "CITATION.cff"):
        label = f"{name} (generated)"
        rows |= text_rows(label, generated[name])
        for hit in vrm.scan_secret_text(name, generated[name]):
            rows.add(f"CRITICAL\tsecret/credential\t{label}\t{hit.split(chr(9), 1)[1]}")
    for hit in vrm.scan_secrets(target, included):
        rows.add(f"CRITICAL\tsecret/credential\t{hit}")
    return sorted(rows)


def print_census(target: Path, out: Path, manifest: Path, title: str, title_set: bool,
                 license_name: str, included: list[str], rows: list[str],
                 counts: dict[str, int]) -> None:
    print(RULE)
    print("Replication package — staging census")
    # POSIX separators on every platform, so the census reads the same on Windows.
    print(f"  Source : {Path(target).as_posix()}")
    print(f"  Output : {Path(out).as_posix()}")
    print(f"  Manifest: {Path(manifest).as_posix()}")
    print(f"  Title  : {title if title_set else '(not set in PROJECT.md; finalize will refuse until it is)'}")
    # RP-7 (owner default O6): no legal text is generated, so say so before anyone ships.
    print(f"  License: {license_name} (a placeholder LICENSE is written; add the full text)"
          if license_name else
          "  License: (no license named; no LICENSE is written; choose one before publishing)")
    print(SEP)
    print(f"INCLUDED ({len(included)} files):")
    for rel in included:
        print(f"  + {rel}")
    print(SEP)
    print("EXCLUDED (denylist — never published):")
    for d in CENSUS_DENY_DIRS:
        if (target / d).exists():
            print(f"  - {d}/  (proprietary shell, history, raw/derived data, or internal)")
    for f in CENSUS_DENY_FILES:
        if (target / f).exists():
            print(f"  - {f}  (proprietary shell)")
    print(SEP)
    print(f"SAFETY SCAN: CRITICAL={counts['CRITICAL']}  HIGH={counts['HIGH']}  "
          f"MEDIUM={counts['MEDIUM']}")
    if rows:
        print("  (details: severity / family / file / match)")
        for row in rows:
            print(f"  ! {row}")
    print(RULE, flush=True)


# --------------------------------------------------------------------------- export
def confirm(out: Path) -> bool:
    """Ask on the terminal. Without one there is no one to answer, so the caller must
    confirm with the user in chat and pass --yes instead."""
    no_one = Stop(2, "ERROR: finalize needs confirmation, but stdin is not a terminal. Confirm "
                     "with the user, then re-run with --yes. Nothing was written.")
    if not stdin_is_terminal():
        raise no_one
    print(f"Build replication package at {out} ? [y/N] ", end="", flush=True)
    line = sys.stdin.readline()
    if not line:  # end of input: no one is there to answer
        raise no_one
    return line.strip() in ("y", "Y", "yes", "YES")


def stdin_is_terminal() -> bool:
    """True only for an interactive console. On Windows `isatty()` is also true for NUL and
    other character devices, so a console handle is required as well."""
    if not sys.stdin.isatty():
        return False
    if sys.platform != "win32":
        return True
    import ctypes
    import msvcrt
    mode = ctypes.c_uint32()
    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))


def copy_file(src: Path, dst: Path, umask: int) -> None:
    """Copy content and the source's mode less the umask, as `cp` does."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    os.chmod(dst, stat.S_IMODE(src.stat().st_mode) & ~umask)


def render(template: Path, values: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def section(project_md: Path, heading: str) -> list[str] | None:
    """The lines under `## <heading>` in PROJECT.md, up to the next `## `, or None."""
    lines = project_md.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    body, inside, found = [], False, False
    for line in lines:
        if line.startswith("## "):
            inside = line[3:].strip().lower() == heading.lower()
            found = found or inside
            continue
        if inside:
            body.append(line)
    return body if found else None


def profile_text(project_md: Path, heading: str) -> str:
    """RP-6: a section's content with the template's `Optional.` and `TBD` filler removed."""
    keep = [line for line in section(project_md, heading) or []
            if line.strip() and line.strip() != "Optional."
            and line.strip().lstrip("-*+ ").strip("`").strip().lower() not in ("tbd", "[tbd]")]
    return "\n".join(keep) or TO_CONFIRM


def data_in_scope(project_md: Path) -> str:
    """The PROJECT.md "Data in Scope" section, as DATA.md appends it, or nothing."""
    body = section(project_md, "Data in Scope")
    if body is None:
        return ""
    return "\n## Data in scope (from project profile)\n\n" + "".join(f"{b}\n" for b in body)


def _cell(value: object) -> str:
    text = " ".join(str(value).split()) if value not in (None, "") else ""
    return text.replace("|", "\\|") or TO_CONFIRM


def _datasets(path: Path) -> list[dict]:
    """The `datasets` mappings of one registry file, or none when it is absent or unreadable."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return []
    found = doc.get("datasets") if isinstance(doc, dict) else None
    return [d for d in found or [] if isinstance(d, dict)]


def dataset_rows(target: Path) -> list[str]:
    """RP-3: one DATA.md row per dataset in the project's overlay.

    The overlay (`data/docs/dataset-registry.yaml`) holds what this project documented; an
    entry that extends a template dataset takes its name and agency from the template entry
    with the same id. The template's catalog of recognized datasets says nothing about what
    this project used, so it adds no rows. Only what the files state is written; everything
    else is `[to confirm]`.
    """
    template = {d.get("id"): d for d in _datasets(target / REGISTRY)}
    rows = []
    for ds in _datasets(target / OVERLAY):
        base = template.get(ds.get("id"), {})
        variables = [v for v in ds.get("variables") or [] if isinstance(v, dict) and v.get("name")]
        vintages = [str(v) for v in ds.get("vintages") or [] if isinstance(v, (str, int, float))]
        vintages += [str(v["vintage"]) for v in variables if v.get("vintage")]
        used = "Variables: " + ", ".join(str(v["name"]) for v in variables) if variables else ""
        cells = (ds.get("name") or base.get("name") or ds.get("id"),
                 ds.get("agency") or base.get("agency"),
                 "; ".join(dict.fromkeys(vintages)), used, "")
        rows.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return rows


def citation_cff(citation: dict | None, title: str, today: str) -> str:
    """RP-6: CITATION.cff from the manifest `citation` block; gaps are `[to confirm]`."""
    cite = citation or {}
    authors = []
    for name in cite.get("authors") or []:
        family, _, given = str(name).partition(",")
        if given.strip():
            authors.append({"family-names": family.strip(), "given-names": given.strip()})
        elif family.strip():
            authors.append({"name": family.strip()})
    doc = {"cff-version": "1.2.0",
           "message": "If you use these materials, please cite the work as below.",
           "title": str(cite.get("title") or "").strip() or title,
           "date-released": today,
           "authors": authors or [{"family-names": "[to confirm]", "given-names": "[to confirm]"}],
           "url": str(cite.get("url") or "").strip() or "[to confirm]"}
    year = str(cite.get("year") or "").strip()
    if year:
        doc["preferred-citation"] = {"type": "generic", "title": doc["title"],
                                     "authors": copy.deepcopy(doc["authors"]),
                                     "year": int(year) if year.isdigit() else year}
    return ("# Generated from the replication manifest's `citation` block. Replace every\n"
            "# [to confirm] before publication; nothing here was guessed.\n"
            + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False))


def gitignore(data: dict) -> str:
    """The public .gitignore. D-8: data the manifest publishes is never ignored by it."""
    lines = (TEMPLATE_DIR / "gitignore").read_text(encoding="utf-8").split("\n")
    if data.get("include_raw_data"):
        lines = [line for line in lines if line.strip() != "data/raw/"]
    kept = [d for flag, d in (("include_raw_data", "data/raw"),
                              ("include_processed_data", "data/processed")) if data.get(flag)]
    text = "\n".join(lines)
    if kept:
        text += ("\n# Data this package publishes (manifest opt-in): never ignored.\n"
                 + "".join(f"!{d}/**\n" for d in kept))
    return text


def scaffolding(target: Path, data: dict, title: str, today: str) -> dict[str, str]:
    """RP-3 and RP-6: the generated public files, built before the scan so it covers them."""
    profile = target / "PROJECT.md"
    rows = dataset_rows(target) or ["| " + " | ".join([TO_CONFIRM] * 5) + " |"]
    base = {"PROJECT_TITLE": title, "DATE": today}
    return {
        "README.md": render(TEMPLATE_DIR / "README.md", {
            **base, "RESEARCH_QUESTION": profile_text(profile, "Research Question"),
            "DELIVERABLES": profile_text(profile, "Deliverables")}),
        "DATA.md": render(TEMPLATE_DIR / "DATA.md", {**base, "DATASET_ROWS": "\n".join(rows)})
        + data_in_scope(profile),
        "CITATION.cff": citation_cff(data.get("citation"), title, today),
        ".gitignore": gitignore(data),
    }


def git(stage: Path, *args: str, check: bool = True,
        stdin: str | None = None) -> subprocess.CompletedProcess:
    # Resolve git on PATH as the shell would (on Windows, with PATHEXT) rather than leaving it
    # to CreateProcess, which only looks for git.exe.
    exe = shutil.which("git") or "git"
    proc = subprocess.run([exe, "-C", str(stage), *args], stdout=subprocess.PIPE, text=True,
                          input=stdin)
    if check and proc.returncode != 0:
        raise Stop(1, f"ERROR: git {' '.join(args)} failed (exit {proc.returncode}).")
    return proc


def write_scaffolding(stage: Path, generated: dict[str, str], title: str, today: str,
                      included: list[str], counts: dict[str, int], allow_unsafe: bool,
                      license_name: str, out: Path) -> None:
    for name, text in generated.items():
        (stage / name).write_text(text, encoding="utf-8", newline="\n")
    summary = ["# Replication manifest summary", "", f"- Built: {today}",
               f"- Source project: {title}", f"- Files included: {len(included)}",
               f"- Safety scan: CRITICAL={counts['CRITICAL']} HIGH={counts['HIGH']} "
               f"MEDIUM={counts['MEDIUM']}"]
    if allow_unsafe:
        summary.append("- NOTE: finalized with --allow-unsafe (override).")
    summary += ["", "## Included files", *(f"- {rel}" for rel in included)]
    (stage / "REPLICATION_MANIFEST.md").write_text("\n".join(summary) + "\n", encoding="utf-8",
                                                   newline="\n")
    # RP-7 (owner default O6): a placeholder only; no legal text is generated.
    if license_name:
        (stage / "LICENSE").write_text(
            f"License requested: {license_name} — add the full license text to {out}/LICENSE.\n",
            encoding="utf-8", newline="\n")
        print(f"NOTE: a LICENSE placeholder was written for '{license_name}'. Replace it with "
              f"the full license text.")
    else:
        print("NOTE: no license specified in the manifest; no LICENSE file written. Choose one "
              "before publishing.")


def finalize(target: Path, out: Path, parent: Path, title: str, included: list[str],
             counts: dict[str, int], allow_unsafe: bool, license_name: str,
             generated: dict[str, str], today: str, forced: list[str],
             data: dict) -> None:
    """Stage, scaffold, and commit the export, then move it into place in one rename."""
    # Belt and braces: the resolver already applied the denylist; recheck each final path.
    for rel in included:
        problem = vrm.staged_path_problem(rel, data)
        if problem:
            raise Stop(1, f"BLOCKED: {rel} is {problem}; it is never published. Nothing was "
                          f"written.")
    umask = os.umask(0)
    os.umask(umask)
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.staging.", dir=parent))  # mode 0700
    try:
        for rel in included:
            # Belt and braces: the validator already refused symlinks, and a copy follows one.
            if (target / rel).is_symlink():
                raise Stop(1, f"BLOCKED: {rel} is a symlink; symlinks are never published.")
            copy_file(target / rel, stage / rel, umask)
        write_scaffolding(stage, generated, title, today, included, counts, allow_unsafe,
                          license_name, out)
        git(stage, "init", "-q")
        git(stage, "add", "-A")
        # D-8: a file the manifest opted into (a data flag or an exact include) is tracked
        # whatever a .gitignore pattern says; everything else is left to the .gitignore.
        if forced:
            git(stage, "add", "-f", "--pathspec-from-file=-", "--pathspec-file-nul",
                stdin="".join(f"{rel}\0" for rel in forced))
        committed = git(stage, "config", "user.email", check=False).returncode == 0
        if committed:
            git(stage, "commit", "-q", "-m", f"Initial public replication package: {title}")
        os.chmod(stage, 0o777 & ~umask)  # what a plain mkdir gives, not mkdtemp's 0700
        if out.is_dir():
            out.rmdir()  # absent or empty, checked before staging
        os.rename(stage, out)
    except BaseException as exc:
        shutil.rmtree(stage, ignore_errors=True)
        code = exc.code if isinstance(exc, Stop) else 1
        if isinstance(exc, Stop) and str(exc):
            err(str(exc))
        elif not isinstance(exc, Stop):
            err(f"ERROR: {exc}")
        raise Stop(code, f"ERROR: the build failed after staging began (exit {code}). The "
                         f"partial export was removed; nothing was written to {out}.") from None
    if committed:
        print("Committed initial replication package.")
    else:
        print(f"Staged all files. No git identity configured here — run 'git -C \"{out}\" "
              f"commit' to create the first commit.")


# --------------------------------------------------------------------------- main
def run(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.target):
        raise Stop(2, "Target directory not found.")
    # Physical paths throughout, so a symlinked alias cannot hide that the output
    # directory is inside the source repo (RP-1).
    target = Path(os.path.realpath(args.target))
    if not (target / "PROJECT.md").is_file():
        raise Stop(2, f"No PROJECT.md in {target} — is this a project root?")
    manifest = target / "replication.manifest.yaml"
    if not manifest.is_file():  # RP-5
        shutil.copyfile(TEMPLATE_DIR / "manifest.yaml", manifest)
        print(f"Created {manifest} from template.", flush=True)
        raise Stop(3, "Review the include/exclude lists, raw/processed flags, and license, "
                      "then re-run.")
    data = load_manifest(manifest)

    try:
        title = vrm.project_title(target / "PROJECT.md")
    except (OSError, UnicodeDecodeError):
        raise Stop(1, f"ERROR: could not read the project title from {target}/PROJECT.md.") from None
    title_set = title.lower() not in ("", "tbd", "[tbd]")

    requested = args.out or str(data.get("output_dir") or "").strip() \
        or str(target.parent / f"{target.name}-replication")
    parent, out = output_path(requested, target)
    check_history_safety(out, parent, target)

    included, refused = vrm.resolve(data, target)
    if refused:
        for rel in refused:
            try:
                dest = os.readlink(target / rel)
            except OSError:
                dest = "?"
            err(f"ERROR: symlink refused: {rel} -> {dest}")
        err("ERROR: symlinks are never published, because a symlink can pull in content from "
            "outside the project. Replace each one with a regular file, or add it to `exclude` "
            "in the manifest.")
        raise Stop(1, "BLOCKED: the include set could not be resolved (see the errors above). "
                      "Nothing was written.")
    if not included:
        raise Stop(1, "ERROR: nothing to publish: no file under the allowlist (code/, "
                      "output/figures/, output/tables/, plus the manifest's include) survived "
                      "the denylist and excludes. Check the manifest; nothing was written.")

    today = date.today().isoformat()
    license_name = str(data.get("license") or "").strip()
    generated = scaffolding(target, data, title, today)
    rows = scan(target, included, data, generated)
    counts = {sev: sum(1 for r in rows if r.startswith(sev + "\t"))
              for sev in ("CRITICAL", "HIGH", "MEDIUM")}
    print_census(target, out, manifest, title, title_set, license_name, included, rows, counts)
    if args.dry_run:
        print("Dry run complete. No files written.")
        return 0

    if counts["CRITICAL"] or counts["HIGH"]:
        if not args.allow_unsafe:
            raise Stop(1, f"BLOCKED: {counts['CRITICAL']} CRITICAL and {counts['HIGH']} HIGH "
                          f"safety finding(s). Resolve them or re-run with --allow-unsafe "
                          f"(human-authorized).")
        print(f"WARNING: proceeding despite {counts['CRITICAL']} CRITICAL / {counts['HIGH']} "
              f"HIGH finding(s) due to --allow-unsafe.")
    if not title_set:
        raise Stop(1, f"BLOCKED: PROJECT.md has no Research Project Title (found "
                      f"'{title or 'nothing'}'). A public package must be titled; set it and "
                      f"re-run.")
    if not args.yes and not confirm(out):
        print("Aborted. Nothing was written.")
        return 0

    finalize(target, out, parent, title, included, counts, args.allow_unsafe, license_name,
             generated, today, [rel for rel in included if opted_in(rel, data)], data)
    print(RULE)
    print(f"Replication package built at: {out}")
    print("It shares NO history with the source repo and contains no proprietary shell files.")
    print("Next: review it, confirm the LICENSE, create an empty GitHub repo, then add a "
          "remote and push.")
    print(RULE)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except Stop as stop:
        sys.stdout.flush()
        if str(stop):
            err(str(stop))
        return stop.code
    except Exception as exc:  # an unexpected failure is exit 1, never a silent 0
        sys.stdout.flush()
        err(f"ERROR: the builder stopped unexpectedly: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
