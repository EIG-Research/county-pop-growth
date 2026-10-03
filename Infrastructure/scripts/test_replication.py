#!/usr/bin/env python3
"""Test suite for the replication-package builder.

Drives the real `build_replication_package.py` (and, through it,
`validate_replication_manifest.py`) against synthetic source projects built at test time,
with no model in the loop and no network.
`python3 Infrastructure/scripts/test_replication.py` from anywhere.

Cases, one `PASS` line each. Finding ids (`D-1`) refer to the template's modernization
census of its tooling, a template-development record that `make template-reset` removes from
a project.

     1  Clean build                 finalize: fresh repo, one commit, scaffolding, no shell
     2  Secret detection            D-1: R `<-`, uppercase, single quotes, Sys.setenv, and more
     3  Secret false positives      D-1: env-var reads, short values, and prose are not flagged
     4  Symlinks refused            D-2: file and directory links block the build, never copy
     5  Non-interactive confirm     D-3: no TTY and no --yes fails loudly; the skill passes --yes
     6  Project title               D-4: a plain-text title builds; an unset title is refused
     7  Failure after staging       D-4: a late failure leaves no half-built export
     8  Empty include set           D-5: nothing to publish fails loudly, dry run and finalize
     9  Output path aliases         RP-1: an --out path through a symlink into the repo is refused
    10  Output path case alias      RP-1: an --out path differing only in letter case is refused
                                    (skipped, with the reason, on a case-sensitive filesystem)
    11  Exit codes                  0 built or declined, 1 blocked, 2 usage, 3 manifest seeded
    12  Census snapshot             the dry-run census, byte for byte
    13  Scanner precision           R2: user paths, shell references, case-insensitive denylist
    14  Product alignment           D-7: README, DATA.md from the overlay, CITATION.cff from
                                    the manifest, LICENSE placeholder, dotfile include
    15  Scan families               RP-4c "EIG template", RP-4d phones, RP-4e binary and size
    16  Opted-in data tracked       D-8: the export's .gitignore never untracks opted-in data
    17  Generated secrets           a key in PROJECT.md or the overlay blocks the build
    18  Tabular binaries            binary data under output/tables/ is HIGH; figures are not
    19  Dot-segment includes        `./records/x`, `data/./raw/x`, `./.git/config` are refused,
                                    and the resolver and stager recheck every final path

What the suite guarantees about itself:

  - **It writes nothing it does not own.** Every project, every export, and the throwaway
    git config live in one temporary directory that is removed at the end.
  - **It touches no network.** The builder runs only local commands, and git runs with a
    throwaway global config and no system config.
  - **It is fast.** Wall-clock time is printed, and anything over 60 seconds fails.

Exit codes: 0 every case passed; 1 a case failed; 2 the environment is unusable.

Dependencies: Python 3.11+ with PyYAML (the validator needs it), and git.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent.parent
BUILDER = SCRIPTS / "build_replication_package.py"
SKILL = REPO_ROOT / "Infrastructure" / "skills" / "build-replication-package" / "SKILL.md"
TIME_LIMIT_SECONDS = 60
RUN_TIMEOUT_SECONDS = 30
TITLE = "Synthetic Replication Study"

try:
    import yaml
except ImportError:  # pragma: no cover - environment check
    print("PyYAML is required: python3 -m pip install pyyaml", file=sys.stderr)
    raise SystemExit(2)


# The builder runs under this interpreter, which has PyYAML. The builder finds git on PATH,
# so case 7's fake git still fires.
PYTHON = sys.executable


# --------------------------------------------------------------------------- assertions
class CaseFailure(AssertionError):
    """A failed expectation inside a case."""


def check(condition: Any, message: str) -> None:
    if not condition:
        raise CaseFailure(message)


def check_eq(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise CaseFailure(f"{message}: expected {expected!r}, got {actual!r}")


# --------------------------------------------------------------------------- fixtures
class Result:
    def __init__(self, proc: subprocess.CompletedProcess[str]) -> None:
        self.rc = proc.returncode
        self.out = proc.stdout
        self.err = proc.stderr
        self.both = proc.stdout + proc.stderr

    def findings(self) -> list[tuple[str, str, str]]:
        """(severity, family, file) for every scan finding the census printed."""
        rows = []
        for line in self.out.splitlines():
            if line.startswith("  ! "):
                parts = line[4:].split("\t")
                if len(parts) >= 3:
                    rows.append((parts[0], parts[1], parts[2]))
        return rows

    def describe(self) -> str:
        tail = self.both.strip().splitlines()[-6:]
        return f"rc={self.rc}; output tail: {' | '.join(tail) or '(none)'}"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def make_project(work: Path, name: str = "proj", title_block: str = f"- `{TITLE}`",
                 files: dict[str, str] | None = None, manifest: dict | None = None,
                 default_files: bool = True) -> Path:
    """A minimal source project: PROJECT.md, a manifest, public files, and private files."""
    root = work / name
    write(root / "PROJECT.md",
          "# Project Profile\n\n## Research Project Title\n"
          f"{title_block}\n\n## Research Question\n- A synthetic question.\n\n"
          "## Data in Scope\n| Data Source | Type |\n|---|---|\n| Synthetic | CSV |\n")
    spec = {"output_dir": "", "include": [], "exclude": [], "include_raw_data": False,
            "include_processed_data": False, "license": "", "citation": None}
    spec.update(manifest or {})
    write(root / "replication.manifest.yaml", yaml.safe_dump(spec, sort_keys=False))
    # Private material that must never ship, present in every project.
    write(root / "Infrastructure" / "rules" / "private.md", "Proprietary shell file.\n")
    write(root / "data" / "raw" / "input.csv", "id,value\n1,2\n")
    write(root / "drafts" / "draft.md", "Internal draft.\n")
    write(root / "CLAUDE.md", "Proprietary adapter file.\n")
    if default_files:
        write(root / "code" / "run_all.R", "set.seed(1)\nx <- c(1, 2, 3)\nprint(mean(x))\n")
        write(root / "output" / "figures" / "fig1.svg", "<svg/>\n")
        write(root / "output" / "tables" / "table1.csv", "a,b\n1,2\n")
    for rel, text in (files or {}).items():
        write(root / rel, text)
    return root


def environment(work: Path, extra_path: Path | None = None) -> dict[str, str]:
    """A throwaway git identity and config, so git never reads the real ones.

    HOME is left alone: PyYAML may live in the user site-packages under it.
    """
    gitconfig = work.parent / "gitconfig"  # the suite's temp root, outside every case dir
    if not gitconfig.exists():
        gitconfig.write_text("[user]\n\tname = Replication Test\n\temail = test@example.invalid\n"
                             "[init]\n\tdefaultBranch = main\n", encoding="utf-8", newline="\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": str(gitconfig), "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"})
    path = [str(Path(sys.executable).parent), env.get("PATH", "")]
    if extra_path is not None:
        path.insert(0, str(extra_path))
    env["PATH"] = os.pathsep.join(path)
    return env


def build(work: Path, project: Path, *args: str, out: Path | None = None,
          stdin: str | None = None,
          extra_path: Path | None = None) -> Result:
    """Run the real builder. stdin=None gives it no input at all (and no terminal)."""
    out = out if out is not None else work / "export"
    cmd = [PYTHON, str(BUILDER), str(project), "--out", str(out), *args]
    kwargs: dict[str, Any] = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
    proc = subprocess.run(cmd, cwd=work, env=environment(work, extra_path), text=True,
                          capture_output=True, timeout=RUN_TIMEOUT_SECONDS, **kwargs)
    return Result(proc)


def listing(directory: Path) -> set[str]:
    return set(os.listdir(directory)) if directory.is_dir() else set()


def tree_text(directory: Path) -> str:
    """All text under a directory except .git/, for leak checks."""
    chunks = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and ".git" not in path.relative_to(directory).parts:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


# --------------------------------------------------------------------------- cases
def case_1_clean_build(work: Path) -> str:
    project = make_project(work)
    before = listing(work)
    res = build(work, project, "--yes")
    check_eq(res.rc, 0, f"a clean finalize succeeds ({res.describe()})")
    out = work / "export"
    check("SAFETY SCAN: CRITICAL=0  HIGH=0" in res.out, "the clean project scans clean")
    for rel in ("code/run_all.R", "output/figures/fig1.svg", "output/tables/table1.csv",
                "README.md", "DATA.md", "CITATION.cff", ".gitignore", "REPLICATION_MANIFEST.md"):
        check((out / rel).is_file(), f"the export contains {rel}")
    for rel in ("Infrastructure", "data", "drafts", "CLAUDE.md", "replication.manifest.yaml"):
        check(not (out / rel).exists(), f"the export excludes {rel}")
    check((out / ".git").is_dir(), "the export is a git repository")
    log = subprocess.run(["git", "-C", str(out), "log", "--oneline"], env=environment(work),
                         text=True, capture_output=True, timeout=RUN_TIMEOUT_SECONDS)
    check_eq(len(log.stdout.strip().splitlines()), 1, "the export has exactly one commit")
    check(TITLE in (out / "README.md").read_text(encoding="utf-8"), "README carries the title")
    check_eq(listing(work) - before, {"export"}, "nothing but the export is left beside it")
    # The export has the permissions a plain mkdir gives, not mktemp's 0700.
    umask = os.umask(0)
    os.umask(umask)
    check_eq(oct(out.stat().st_mode & 0o777), oct(0o777 & ~umask),
             "the export directory has umask-default permissions")
    # An empty, pre-existing output directory is accepted.
    project2 = make_project(work, "proj2")
    empty = work / "empty-export"
    empty.mkdir()
    res = build(work, project2, "--yes", out=empty)
    check_eq(res.rc, 0, f"an empty existing output directory is accepted ({res.describe()})")
    check((empty / "code" / "run_all.R").is_file(), "the export fills the empty directory")
    return f"builder run by {Path(PYTHON).name}"


# Each positive fixture is one line in its own file, so a miss names the exact form.
# Credential-shaped strings are split so this file is not itself a secret-scanner hit.
SECRET_POSITIVES = {
    # D-1: the four forms the census demonstrated were missed.
    "code/r_arrow.R": 'api_key <- "sk-abcdef1234567890"\n',
    "code/uppercase.py": 'API_KEY = "abcdefghijk"\n',
    "code/setenv.R": 'Sys.setenv(CENSUS_KEY = "abcdef123456")\n',
    "code/single_quote.R": "token = 'abcdefghij'\n",
    # D-1: the other forms named in the fix.
    "code/census_fn.R": 'census_api_key("0123456789abcdef")\n',
    "code/keys.env": "CENSUS_API_KEY=abcdef0123456789\n",
    "code/connect.R": 'con <- DBI::dbConnect(url = "postgres://analyst:hunter22@db.example.org/eig")\n',
    "code/config.json": '{"Secret": "abcdefghijkl"}\n',
    # D-1, round 2: forms a reviewer found missed.
    "code/os_environ.py": 'os.environ["CENSUS_API_KEY"] = "abcdef123456"\n',
    "code/os_putenv.py": 'os.putenv("FRED_API_KEY", "abcdef123456")\n',
    "code/fredr.R": 'fredr_set_key("abcdef0123456789")\n',
    "code/census_name.R": 'census_api_key <- "abcdef0123456789"\n',
    "code/fred_key.R": 'fred_key = "abcdef0123456789"\n',
    "code/bls_key.R": 'bls_key <- "abcdef0123456789"\n',
    "code/bea_key.py": 'bea_key = "ABCDEF01-2345-6789"\n',
    "code/ipums_key.R": "ipums_key <- 'abcdef0123456789'\n",
    "code/pwd.R": 'pwd = "hunter2hunter2"\n',
    "code/bearer.py": 'headers = {"Authorization": "Bearer abcdef0123456789xyz"}\n',
    "code/c_vector.R": 'API_KEY <- c("abcdef0123456789")\n',
    "code/my_token.R": 'my_token <- "abcdef0123456789"\n',
    # A URL-query key ended by `;`, `)`, or `,` rather than `&` or a quote.
    "code/url_semicolon.R": 'u <- "https://x.org/a?key=0123456789abcdef0123456789abcdef01234567;"\n',
    "code/url_paren.py": 'get(base + "?key=0123456789abcdef0123456789abcdef01234567)")\n',
    # Round 3: unquoted YAML values.
    "code/creds.yml": "api_key: abc123def456\n",
    "code/nested.yaml": "database:\n  password: hunter2hunter2\n",
    "code/headers.yml": "x-api-key: abcdef0123456789  # rotate monthly\n",
    # R2 (O7): a harmless suffix counts only after an underscore, and `_id` never excuses
    # a token, secret, or password stem.
    "code/secret_valid.R": 'client_secret_valid <- "abcdef123456"\n',
    "code/token_profile.py": 'auth_token_profile = "abcdef123456"\n',
    "code/token_id.R": 'token_id <- "literal"\n',
    "code/secret_id.py": 'client_secret_id = "abcdef123456"\n',
    "code/password_id.R": 'db_password_id <- "hunter2hunter2"\n',
    # Detections that already worked must keep working.
    "code/aws.R": 'aws <- "AKIA' + 'IOSFODNN7EXAMPLE"\n',
    "code/github.R": 'pat <- "gh' + 'p_EXAMPLEonlyNotARealToken0000"\n',
    "code/slack.R": 'hook <- "xo' + 'xb-000000000000-EXAMPLE"\n',
    "code/key.txt": "-----BEGIN RSA PRI" + "VATE KEY-----\nMIIEexample\n",
    "code/double_quote.R": 'password = "correcthorse"\n',
    # W3 review: keys in URLs, BLS payloads, and OpenAI and Google formats.
    "code/census_url.R": 'u <- "https://api.census.gov/data/2022/acs/acs5?get=NAME&for=state:*'
                         '&ke' + 'y=0123456789abcdef0123456789abcdef01234567"\n',
    "code/token_url.py": 'u = "https://example.org/api?tok' + 'en=abcdef0123456789&x=1"\n',
    "code/bls_list.R": 'payload <- list(registration' + 'key = "0123456789abcdef0123456789abcdef")\n',
    "code/bls_json.py": 'data = json.dumps({"seriesid": s, "registration'
                        + 'key": "0123456789abcdef"})\n',
    "code/openai_proj.py": 'k = "sk-' + 'proj-abcdefghijklmnopqrstuvwxyz0123456789ABCD"\n',
    "code/openai.R": 'k <- "sk-' + 'abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH"\n',
    "code/google.py": 'g = "AI' + 'zaSyA-abcdefghijklmnopqrstuvwxyz012345"\n',
    # W3 round 2: a Census key split from its URL, passed as a bare `key`, or on the next line.
    "code/census_paste.R": 'u <- paste0("https://api.census.gov/data/2022/acs/acs5?get=NAME&ke'
                           + 'y=", "0123456789abcdef0123456789abcdef01234567")\n',
    "code/census_query.R": 'resp <- httr::GET(url, query = list(ke' + 'y = "0123456789abcdef0123456789abcdef01234567"))\n',
    "code/census_params.py": 'r = requests.get(url, params={"ke' + 'y": "0123456789abcdef0123456789abcdef01234567"})\n',
    "code/bls_next_line.R": 'payload <- list(registration' + 'key =\n  "0123456789abcdef0123456789abcdef")\n',
}

SECRET_NEGATIVES = (
    'api_key <- Sys.getenv("CENSUS_API_KEY")\n'
    "token <- Sys.getenv('GITHUB_PAT')\n"
    'secret = ""\n'
    "n_tokens <- 12\n"
    "password_prompt <- getPass::getPass()\n"
    "# Store the API key in .Renviron, never in code; the token is read at run time.\n"
    'tokenize <- function(x) strsplit(x, " ")\n'
    'keyring::key_get("census")\n'
    'Sys.setenv(TZ = "America/New_York")\n'
    "tokens <- tokens[1:3]\n"
    'url <- "https://api.census.gov/data/2022/acs/acs5"\n'
    # Quoted names outside JSON/YAML are join keys and column names, not assignments.
    'joined <- dplyr::left_join(a, b, by = c("token_id" = "token_id"))\n'
    'renamed <- c("secret_id" = "respondent_secret_id")\n'
    # tidytext tokenizer names and an env-var NAME are not credentials.
    'bigrams <- tidytext::unnest_tokens(df, word, text, token = "ngrams", n = 2)\n'
    'api_key_env = "CENSUS_API_KEY"\n'
    # data.table's setkey, and a variable that merely ends in _key.
    'data.table::setkey(dt, "state_fips")\n'
    'merge_key <- "household_id"\n'
    'os.environ["CUDA_VISIBLE_DEVICES"] = "0,1,2,3"\n'
    'old_pwd <- getwd()\n'
    # Names that point at a credential (or describe one) rather than hold it.
    'api_key_file <- "~/.census_key"\n'
    'tokens_file <- "data/tokens.csv"\n'
    'secrets_dir <- "config/secrets"\n'
    'token_pattern <- "[A-Za-z]+"\n'
    'tokenizer_name = "wordpiece"\n'
    'password_prompt <- "Enter password: "\n'
    'secret_col <- "respondent_secret"\n'
    'token_col = "token_text"\n'
    # R2 (O7): `_id` still excuses a key stem; it is an identifier, not the key.
    'api_key_id <- "acs5_2022"\n'
    # A key read at run time, a placeholder, or a template slot in a URL is not a key.
    'u <- paste0(base, "?get=NAME&key=", Sys.getenv("CENSUS_API_KEY"))\n'
    'u = f"{base}?get=NAME&key={api_key}"\n'
    'u <- glue::glue("{base}&key={census_key}&for=state:*")\n'
    '# Append &key=YOUR_CENSUS_KEY to the query; see https://api.census.gov/data/key_signup.html\n'
    'u <- "https://example.org/search?token=${TOKEN}"\n'
    'payload <- list(registrationkey = Sys.getenv("BLS_KEY"))\n'
    'df <- dplyr::mutate(df, task_label = "risk-adjusted-compensation-for-workers")\n'
    'refs <- "https://doi.org/10.1257/aer?key=abc"\n'
    # W3 round 2: identifiers, join keys, and table names are not credentials.
    'u <- "https://example.org/api?key=2022_acs5_table"\n'
    'm <- merge(a, b, by = c(key = "state_fips"))\n'
    'data.table::setkey(dt, key = "household_id")\n'
    'd = dict(key="value", other="x")\n'
    'cfg = {"key": "state_fips_2022"}\n'
    'cache_key <- "0123456789abcdef0123456789abcdef"\n'
    'if (key == "0123456789abcdef0123456789abcdef") stop()\n'
    'x <-\n  Sys.getenv("CENSUS_API_KEY")\n'
    'token =\n  "ngrams"\n'
)

YAML_NEGATIVES = (
    "password_hint: see the docs\n"
    "token_file: path/to/file\n"
    "api_key: ${CENSUS_API_KEY}\n"
    "secret: ''\n"
    "api_key_env: CENSUS_API_KEY\n"
    "token: short\n"
)


def case_2_secret_detection(work: Path) -> str:
    project = make_project(work, files=SECRET_POSITIVES)
    res = build(work, project, "--dry-run")
    check_eq(res.rc, 0, f"a dry run reports rather than fails ({res.describe()})")
    flagged = {f for sev, fam, f in res.findings() if sev == "CRITICAL" and "secret" in fam}
    missed = sorted(set(SECRET_POSITIVES) - flagged)
    check(not missed, f"every credential form is flagged CRITICAL; missed: {missed}")
    res = build(work, project, "--yes")
    check(res.rc != 0 and "BLOCKED" in res.err, f"secrets block finalize ({res.describe()})")
    check(not (work / "export").exists(), "a blocked build writes no export")
    return f"{len(SECRET_POSITIVES)} forms flagged"


def case_3_secret_false_positives(work: Path) -> None:
    project = make_project(work, files={"code/negatives.R": SECRET_NEGATIVES,
                                        "code/negatives.yml": YAML_NEGATIVES})
    res = build(work, project, "--dry-run")
    check_eq(res.rc, 0, f"dry run ({res.describe()})")
    flagged = [ln for ln in res.out.splitlines() if ln.startswith("  ! ") and "secret" in ln]
    check(not flagged, "reading a credential from the environment, short values, and prose "
                       f"are not flagged as secrets; got {flagged}")
    check("CRITICAL=0" in res.out, "the census reports CRITICAL=0")


SYMLINK_SKIP = ("skipped: this account cannot create symlinks (Windows needs Developer Mode "
                "or an administrator); CI's Windows runner exercises the refusal")


def can_symlink(work: Path) -> bool:
    """True when this process may create a symlink: always on POSIX, and on Windows only with
    Developer Mode or elevation."""
    work.mkdir(parents=True, exist_ok=True)
    probe = work / ".symlink-probe"
    try:
        probe.symlink_to(work, target_is_directory=True)
    except OSError:
        return False
    probe.unlink()
    return True


def case_4_symlinks_refused(work: Path) -> str | None:
    if not can_symlink(work):
        return SYMLINK_SKIP
    outside = work / "outside"
    marker = "OUTSIDE-CONTENT-MARKER-D2"
    write(outside / "hosts.txt", f"{marker}\n")
    write(outside / "dir" / "notes.txt", f"{marker}\n")

    # (a) A file symlink inside code/ that points outside the project.
    project = make_project(work, "proj-file")
    (project / "code" / "link.txt").symlink_to(outside / "hosts.txt")
    res = build(work, project, "--dry-run")
    check(res.rc != 0, f"a dry run with a symlink in scope fails ({res.describe()})")
    check("symlink" in res.err and "code/link.txt" in res.err,
          f"the refusal names the symlink ({res.describe()})")
    for extra in ((), ("--allow-unsafe",)):
        res = build(work, project, "--yes", *extra)
        check(res.rc != 0, f"finalize {' '.join(extra)} refuses the symlink ({res.describe()})")
        check(not (work / "export").exists(), "no export is written")

    # (b) A directory symlink inside code/.
    project = make_project(work, "proj-dir")
    (project / "code" / "linked").symlink_to(outside / "dir", target_is_directory=True)
    res = build(work, project, "--yes")
    check(res.rc != 0 and "code/linked" in res.err,
          f"a directory symlink in scope is refused ({res.describe()})")
    check(not (work / "export").exists(), "no export is written")

    # (c) Excluding the link in the manifest is the way past the refusal.
    project = make_project(work, "proj-excluded", manifest={"exclude": ["code/link.txt"]})
    (project / "code" / "link.txt").symlink_to(outside / "hosts.txt")
    res = build(work, project, "--yes")
    check_eq(res.rc, 0, f"an excluded symlink does not block ({res.describe()})")
    check(not (work / "export" / "code" / "link.txt").exists(), "the excluded link is not copied")
    check(marker not in tree_text(work / "export"), "no outside content reached the export")


def case_5_non_interactive_confirm(work: Path) -> None:
    project = make_project(work)
    for label, stdin in (("no stdin", None), ("piped stdin", "y\n")):
        res = build(work, project, stdin=stdin)
        check_eq(res.rc, 2, f"finalize without --yes and without a terminal ({label}) exits 2 "
                            f"({res.describe()})")
        check("--yes" in res.err, f"the message tells the caller to pass --yes ({label})")
        check(not (work / "export").exists(), f"nothing is written ({label})")
    res = build(work, project, "--yes")
    check_eq(res.rc, 0, f"--yes finalizes non-interactively ({res.describe()})")

    # The skill's documented finalize command must be one an agent can run.
    text = SKILL.read_text(encoding="utf-8")
    step8 = text[text.index("### Step 8"):]
    step8 = step8[:step8.index("### Step 9")]
    commands = [ln for ln in step8.splitlines() if "build_replication_package.py" in ln]
    check(commands, "skill Step 8 documents the finalize command")
    check(all("--yes" in ln for ln in commands), f"skill Step 8 passes --yes: {commands}")
    check("--dry-run" not in " ".join(commands), "skill Step 8 is not a dry run")


def case_6_project_title(work: Path) -> None:
    for i, (block, expected) in enumerate((("- Plain Title Study", "Plain Title Study"),
                                           ("Bare Line Title", "Bare Line Title"))):
        project = make_project(work, f"proj{i}", title_block=block)
        out = work / f"export{i}"
        res = build(work, project, "--yes", out=out)
        check_eq(res.rc, 0, f"a plain-text title ({block!r}) builds ({res.describe()})")
        check(expected in (out / "README.md").read_text(encoding="utf-8"), "README has the title")
        check(expected in (out / "CITATION.cff").read_text(encoding="utf-8"), "CITATION has it")

    # An unset title: the skill says stop, and so must the script.
    project = make_project(work, "proj-tbd", title_block="- `TBD`")
    res = build(work, project, "--dry-run")
    check_eq(res.rc, 0, f"a dry run still reports an untitled project ({res.describe()})")
    res = build(work, project, "--yes", out=work / "export-tbd")
    check(res.rc != 0 and "title" in res.err.lower(),
          f"finalize refuses an untitled project ({res.describe()})")
    check(not (work / "export-tbd").exists(), "no export is written for an untitled project")


def case_7_failure_after_staging(work: Path) -> None:
    # A git that always fails makes the build fail after every file has been staged.
    fakebin = work / "fakebin"
    if sys.platform == "win32":  # no shebangs on Windows; a .cmd is found through PATHEXT
        (fakebin).mkdir(parents=True, exist_ok=True)
        (fakebin / "git.cmd").write_text("@echo fake git failure 1>&2\r\n@exit /b 7\r\n",
                                         encoding="utf-8", newline="")
    else:
        write(fakebin / "git", "#!/bin/sh\necho 'fake git failure' >&2\nexit 7\n").chmod(0o755)
    project = make_project(work)
    before = listing(work)
    res = build(work, project, "--yes", extra_path=fakebin)
    check(res.rc != 0, f"a late failure exits non-zero ({res.describe()})")
    check(not (work / "export").exists(), "no half-built export is left at the output path")
    check_eq(listing(work) - before, set(), "no staging directory is left behind")
    check("partial" in res.err.lower(),
          f"the failure says what happened to the partial export ({res.describe()})")

    # A non-empty output directory is refused before anything is written into it.
    write(work / "busy" / "notes.txt", "someone else's file\n")
    res = build(work, project, "--yes", out=work / "busy")
    check(res.rc != 0 and "not empty" in res.err,
          f"a non-empty output directory is refused ({res.describe()})")
    check_eq(listing(work / "busy"), {"notes.txt"}, "the existing directory is untouched")


def case_8_empty_include(work: Path) -> None:
    project = make_project(work, default_files=False)
    for args in (("--dry-run",), ("--yes",)):
        out = work / "export"
        res = build(work, project, *args, out=out)
        check(res.rc != 0, f"{args[0]}: an empty include set fails ({res.describe()})")
        check("nothing to publish" in res.err.lower(),
              f"{args[0]}: the message says nothing would be published ({res.describe()})")
        check(not out.exists(), f"{args[0]}: no export is written")


def case_9_output_alias(work: Path) -> str | None:
    # RP-1: an --out path through a symlink that points into the source repo is still
    # inside the source repo.
    if not can_symlink(work):
        return SYMLINK_SKIP
    project = make_project(work)
    alias = work / "alias"
    alias.symlink_to(project, target_is_directory=True)
    for args in (("--dry-run",), ("--yes",)):
        res = build(work, project, *args, out=alias / "pkg")
        check(res.rc != 0 and "RP-1" in res.err,
              f"{args[0]}: an output path aliased into the repo is refused ({res.describe()})")
        check(not (project / "pkg").exists(), f"{args[0]}: nothing is written inside the repo")
    # The output directory itself as a symlink into the repo is refused too.
    (project / "inside").mkdir()
    (work / "outlink").symlink_to(project / "inside", target_is_directory=True)
    res = build(work, project, "--yes", out=work / "outlink")
    check(res.rc != 0 and "RP-1" in res.err,
          f"a symlinked output directory is refused ({res.describe()})")
    check_eq(listing(project / "inside"), set(), "nothing is written through the symlink")


def case_10_output_case_alias(work: Path) -> str | None:
    # RP-1 on a case-insensitive filesystem: <parent>/PROJ/pkg is inside <parent>/proj.
    probe = work / "caseprobe"
    probe.mkdir()
    if not (work / "CASEPROBE").exists():
        return "skipped: the temporary filesystem is case-sensitive"
    project = make_project(work, "proj")
    for args in (("--dry-run",), ("--yes",)):
        res = build(work, project, *args, out=work / "PROJ" / "pkg")
        check(res.rc != 0 and "RP-1" in res.err,
              f"{args[0]}: an output path that differs from the repo only by case is refused "
              f"({res.describe()})")
        check(not (project / "pkg").exists(), f"{args[0]}: nothing is written inside the repo")
    return None


def build_tty(work: Path, project: Path, answer: str, out: Path) -> Result:
    """Run the builder with a terminal on stdin, answering its prompt with `answer`."""
    import pty  # POSIX only; the caller skips when it is missing

    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen([PYTHON, str(BUILDER), str(project), "--out", str(out)],
                                cwd=work, env=environment(work), stdin=slave, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(slave)
        slave = -1
        os.write(master, answer.encode("utf-8"))
        stdout, stderr = proc.communicate(timeout=RUN_TIMEOUT_SECONDS)
    finally:
        os.close(master)
        if slave != -1:
            os.close(slave)
    return Result(subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr))


def case_11_exit_codes(work: Path) -> str:
    """The documented exit-code table: 0 built or declined, 1 blocked, 2 usage, 3 seeded."""
    project = make_project(work)
    env = environment(work)

    def raw(*args: str) -> Result:
        proc = subprocess.run([PYTHON, str(BUILDER), *args], cwd=work, env=env, text=True,
                              capture_output=True, timeout=RUN_TIMEOUT_SECONDS,
                              stdin=subprocess.DEVNULL)
        return Result(proc)

    write(work / "no-profile" / "code" / "a.R", "x <- 1\n")
    for args, why in (((), "no target"), ((str(project), "--bogus"), "an unknown flag"),
                      ((str(project), str(project)), "a second target"),
                      ((str(work / "missing"),), "a target that does not exist"),
                      ((str(work / "no-profile"),), "a target without PROJECT.md"),
                      ((str(project), "--dry-run", "--out", str(work / "nope" / "pkg")),
                       "an output parent that does not exist")):
        res = raw(*args)
        check_eq(res.rc, 2, f"{why} is a usage error ({res.describe()})")
    seeded = make_project(work, "seeded")
    (seeded / "replication.manifest.yaml").unlink()
    res = raw(str(seeded), "--dry-run")
    check_eq(res.rc, 3, f"a missing manifest is seeded ({res.describe()})")
    check((seeded / "replication.manifest.yaml").is_file(), "the seeded manifest exists")
    bad = make_project(work, "bad", manifest={"surprise": True})
    check_eq(build(work, bad, "--dry-run").rc, 1, "an invalid manifest is a failure")
    check_eq(build(work, project, "--dry-run").rc, 0, "a dry run succeeds")
    leaky = make_project(work, "leaky", files={"code/path.R": 'p <- "/home/analyst/x.csv"\n'})
    res = build(work, leaky, "--yes", out=work / "leaky-export")
    check_eq(res.rc, 1, f"a HIGH finding blocks finalize ({res.describe()})")
    try:
        import pty  # noqa: F401
    except ImportError:
        return "no pty module: the prompt answers were not exercised"
    res = build_tty(work, project, "n\n", work / "declined")
    check_eq(res.rc, 0, f"declining at the prompt exits 0 ({res.describe()})")
    check("Aborted" in res.out and not (work / "declined").exists(), "and writes nothing")
    res = build_tty(work, project, "y\n", work / "accepted")
    check_eq(res.rc, 0, f"accepting at the prompt builds ({res.describe()})")
    check((work / "accepted" / "code" / "run_all.R").is_file(), "the accepted export exists")
    return "0, 1, 2, and 3 each observed"


CENSUS_FILES = {
    "code/leak.R": 'api_key <- "abcdef0123456789"\npath <- "/Users/analyst/data.csv"\n',
    "code/notes.py": "# See Infrastructure/rules/x.md; ask someone@example.org\nx = 1\n",
    "output/tables/t.csv": "a,b\n1,2\n",
}
CENSUS_SNAPSHOT = """\
==============================================================
Replication package — staging census
  Source : <WORK>/proj
  Output : <WORK>/export
  Manifest: <WORK>/proj/replication.manifest.yaml
  Title  : Synthetic Replication Study
  License: (no license named; no LICENSE is written; choose one before publishing)
--------------------------------------------------------------
INCLUDED (6 files):
  + code/leak.R
  + code/notes.py
  + code/run_all.R
  + output/figures/fig1.svg
  + output/tables/t.csv
  + output/tables/table1.csv
--------------------------------------------------------------
EXCLUDED (denylist — never published):
  - Infrastructure/  (proprietary shell, history, raw/derived data, or internal)
  - drafts/  (proprietary shell, history, raw/derived data, or internal)
  - data/raw/  (proprietary shell, history, raw/derived data, or internal)
  - CLAUDE.md  (proprietary shell)
--------------------------------------------------------------
SAFETY SCAN: CRITICAL=1  HIGH=2  MEDIUM=1
  (details: severity / family / file / match)
  ! CRITICAL\tsecret/credential\tcode/leak.R\t1:api_key <- "abcdef0123456789"
  ! HIGH\tabsolute/user path\tcode/leak.R\t2:path <- "/Users/analyst/data.csv"
  ! HIGH\tshell reference\tcode/notes.py\t1:# See Infrastructure/rules/x.md; ask someone@example.org
  ! MEDIUM\temail/PII\tcode/notes.py\t1:# See Infrastructure/rules/x.md; ask someone@example.org
==============================================================
Dry run complete. No files written.
"""


def case_12_census_snapshot(work: Path) -> None:
    """The dry-run census, byte for byte, with the temporary directory replaced."""
    project = make_project(work, files=CENSUS_FILES)
    res = build(work, project, "--dry-run")
    check_eq(res.rc, 0, f"the dry run succeeds ({res.describe()})")
    text = res.out
    for spelling in (os.path.realpath(work), str(work)):  # the census prints POSIX separators
        text = text.replace(Path(spelling).as_posix(), "<WORK>").replace(spelling, "<WORK>")
    if text != CENSUS_SNAPSHOT:
        import difflib
        diff = "\n".join(difflib.unified_diff(CENSUS_SNAPSHOT.splitlines(), text.splitlines(),
                                              "expected", "actual", lineterm=""))
        raise CaseFailure(f"the census changed:\n{diff}")


# R2 scanner precision. Each positive is one line in its own file, flagged HIGH under the
# named family; the negatives share one file and must raise nothing but MEDIUM.
PATH_POSITIVES = {
    "code/tilde.R": 'df <- read.csv("~/Dropbox/eig/people.csv")\n',
    "code/drive_d.R": 'df <- read.csv("D:/projects/eig/people.csv")\n',
    "code/drive_e.py": 'rows = open(r"E:\\data\\people.csv")\n',
    "code/unc_r.R": 'df <- read.csv("\\\\\\\\fileserver\\\\share\\\\people.csv")\n',
    "code/unc_raw.txt": "Source: \\\\fileserver\\share\\people.csv\n",
    "code/users.R": 'setwd("/Users/analyst/eig")\n',
    "code/tilde_config.R": 'keys <- read.csv("~/.config/eig/keys.csv")\n',
}
SHELL_POSITIVES = {
    "code/agents_dir.R": 'source("../.agents/skills/x.R")\n',
    "code/claude_dir.py": 'CONFIG = ".claude/settings.json"\n',
    "code/infra.R": 'source("Infrastructure/scripts/x.R")\n',
    "code/claude_md.txt": "See CLAUDE.md for the rules.\n",
    # The shell names match in any case, as the denylist does.
    "code/claude_cased.R": 'cfg <- ".Claude/settings.json"\n',
    "code/infra_lower.py": 'SCRIPT = "infrastructure/scripts/x.py"\n',
}
PRECISION_NEGATIVES = (
    "x <- df.agents\n"
    "self.agents = []\n"
    "model <- obj.claude_model\n"
    "n <- nrow(data.codex)\n"
    'url <- "https://example.org/a:b/c"\n'
    'ok <- grepl("\\\\w\\\\s", x)\n'
    'label <- "a:b"\n'
    'path <- file.path("data", "processed", "people.parquet")\n'
    'fit <- lm(y ~ x, data = df)\n'
    # LaTeX table rules and regex word boundaries are escaped backslashes, not UNC shares.
    'cat("\\\\hline\\n")\n'
    'cat("\\\\midrule\\n")\n'
    'hit <- grepl("\\\\bword\\\\b", x)\n'
    # Owner default: the R startup files are where the 3E guidance keeps API keys, so
    # naming them is advice, not a leaked path.
    'readRenviron("~/.Renviron")\n'
    "# Keep the Census key in ~/.Renviron, never in code.\n"
    'source("~/.Rprofile")\n'
)


def case_13_scanner_precision(work: Path) -> str:
    files = {**PATH_POSITIVES, **SHELL_POSITIVES, "code/negatives.R": PRECISION_NEGATIVES}
    project = make_project(work, files=files)
    res = build(work, project, "--dry-run")
    check_eq(res.rc, 0, f"dry run ({res.describe()})")
    found = res.findings()
    paths = {f for sev, fam, f in found if sev == "HIGH" and fam == "absolute/user path"}
    shells = {f for sev, fam, f in found if sev == "HIGH" and fam == "shell reference"}
    missed = sorted((set(PATH_POSITIVES) - paths) | (set(SHELL_POSITIVES) - shells))
    check(not missed, f"every user path and shell reference is flagged HIGH; missed: {missed}")
    noisy = sorted({(sev, fam) for sev, fam, f in found
                    if f == "code/negatives.R" and sev != "MEDIUM"})
    check(not noisy, f"attribute access, URLs, regexes and formulas are not flagged: {noisy}")

    # The denylist compares paths case-insensitively: `include: [Data]` must not ship
    # `Data/Raw/`, whatever the filesystem's case rules.
    cased = make_project(work, "cased", manifest={"include": ["Data"]})
    # Rename through a temporary name, so the capitals stick on a case-insensitive disk.
    (cased / "data").rename(cased / "data-tmp")
    (cased / "data-tmp").rename(cased / "Data")
    (cased / "Data" / "raw").rename(cased / "Data" / "raw-tmp")
    (cased / "Data" / "raw-tmp").rename(cased / "Data" / "Raw")
    write(cased / "Data" / "Raw" / "secret.csv", "id,income\n1,52000\n")
    write(cased / "Data" / "Processed" / "panel.csv", "id,x\n1,2\n")
    write(cased / "Data" / "crosswalk.csv", "fips,name\n01,Alabama\n")
    res = build(work, cased, "--yes", out=work / "cased-export")
    check_eq(res.rc, 0, f"the cased project builds ({res.describe()})")
    shipped = {p.relative_to(work / "cased-export").as_posix()
               for p in (work / "cased-export").rglob("*") if p.is_file()}
    check("Data/crosswalk.csv" in shipped, "an allowlisted Data/ file still ships")
    leaked = sorted(p for p in shipped if p.lower().startswith(("data/raw/", "data/processed/")))
    check(not leaked, f"Data/Raw and Data/Processed never ship under include: [Data]: {leaked}")
    for include in ("Data/Raw", "DRAFTS", "infrastructure/rules"):
        bad = make_project(work, f"bad-{include.replace('/', '-')}",
                           manifest={"include": [include]})
        res = build(work, bad, "--dry-run")
        check(res.rc == 1 and "denylisted path" in res.err,
              f"include: [{include}] is refused as denylisted ({res.describe()})")
    return (f"{len(PATH_POSITIVES)} paths and {len(SHELL_POSITIVES)} shell references flagged; "
            f"case-insensitive denylist")


# R3: the scaffolding is built from what the project states, and nothing more.
PROFILE = """# Project Profile

## Research Project Title
- `Synthetic Replication Study`

## Research Question
Optional.
- Do synthetic wages rise with synthetic tenure?

## Data in Scope
| Data Source | Type |
|---|---|
| Synthetic | CSV |

## Deliverables
Optional.
- A research brief with two figures.

## Constraints
Optional.
- PRIVATE-CONSTRAINT: embargoed until the board meets.

## Additional Context (Open Notes)
PRIVATE-NOTE: the AI workflow lives in the shell.
"""
# The template registry lists recognized datasets; the project's overlay holds what it used.
REGISTRY = {"version": 2, "last_updated": "2026-09-29", "datasets": [
    {"id": "cps", "name": "Current Population Survey (CPS)", "layer": "template",
     "verification": "unverified", "agency": "U.S. Census Bureau", "vintages": [],
     "variables": []},
    {"id": "acs", "name": "American Community Survey (ACS)", "layer": "template",
     "verification": "unverified", "agency": "U.S. Census Bureau", "vintages": [],
     "variables": []}]}
OVERLAY = {"version": 2, "last_updated": "2026-09-29", "datasets": [
    {"id": "acs", "layer": "project", "verification": "parsed",
     "variables": [{"name": "PWGTP", "vintage": "2023 1-year", "source": "PUMS data dictionary"}]},
    {"id": "synthetic_panel", "name": "Synthetic Wage Panel", "layer": "project",
     "verification": "parsed", "agency": "Synthetic Statistics Office",
     "vintages": ["2024 release"],
     "variables": [{"name": "wage_hr", "vintage": "2024 release", "source": "Codebook p. 3"},
                   {"name": "tenure_yrs", "vintage": "[unverified: codebook pending]",
                    "source": "Codebook p. 4"}]}]}


def write_registries(project: Path, overlay: dict = OVERLAY) -> None:
    write(project / "Infrastructure/references/datasets/registry.yaml",
          yaml.safe_dump(REGISTRY, sort_keys=False))
    write(project / "data/docs/dataset-registry.yaml", yaml.safe_dump(overlay, sort_keys=False))


def _cff(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _binary(path: Path, size: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n\0" + b"\x01" * size)


def case_14_product_alignment(work: Path) -> str:
    """RP-2, RP-3, RP-6 and RP-7 as the rules now state them (D-7)."""
    project = make_project(work, manifest={
        "license": "MIT", "include": [".Rprofile"],
        "citation": {"authors": ["Glasner, Benjamin", "Synthetic Lab"], "title": "Wages",
                     "year": "2026", "url": "https://example.org/wages"}},
        files={".Rprofile": 'source("renv/activate.R")\n', ".env": "X=1\n",
               "renv/library/pkg/DESCRIPTION": "Package: pkg\n"})
    write(project / "PROJECT.md", PROFILE)
    write_registries(project)
    res = build(work, project, "--yes")
    check_eq(res.rc, 0, f"the aligned project builds ({res.describe()})")
    out = work / "export"
    readme = (out / "README.md").read_text(encoding="utf-8")
    for text in ("Do synthetic wages rise with synthetic tenure?", "A research brief with two figures."):
        check(text in readme, f"RP-6: README carries {text!r}")
    for text in ("PRIVATE-CONSTRAINT", "PRIVATE-NOTE", "Optional."):
        check(text not in readme, f"RP-6: README leaves out {text!r}")
    data_md = (out / "DATA.md").read_text(encoding="utf-8")
    for text in ("Synthetic Wage Panel", "Synthetic Statistics Office", "2024 release",
                 "wage_hr", "tenure_yrs", "[unverified: codebook pending]",
                 "American Community Survey (ACS)", "U.S. Census Bureau", "PWGTP",
                 "Data in scope (from project profile)"):
        check(text in data_md, f"RP-3: DATA.md carries {text!r} from the overlay, template, or profile")
    check("Current Population Survey" not in data_md,
          "RP-3: a template dataset the project never used is not listed")
    check(not any(p.startswith("data/docs/") for p in
                  (q.relative_to(out).as_posix() for q in out.rglob("*") if q.is_file())),
          "RP-3: the overlay and its docs are not on the default allowlist")
    check("Infrastructure" not in tree_text(out), "RP-3: no shell path reaches the export")
    cff = _cff(out / "CITATION.cff")
    check_eq(cff["title"], "Wages", "RP-6: the citation title comes from the manifest")
    check_eq(cff["authors"], [{"family-names": "Glasner", "given-names": "Benjamin"},
                              {"name": "Synthetic Lab"}], "RP-6: the manifest authors")
    check_eq(cff["url"], "https://example.org/wages", "RP-6: the manifest url")
    check_eq(cff["preferred-citation"]["year"], 2026, "RP-6: the manifest year")
    license_text = (out / "LICENSE").read_text(encoding="utf-8")
    check("MIT" in license_text and "full license text" in license_text,
          "RP-7 (O6): a placeholder names the license and asks for the full text")
    check("placeholder" in res.out.split("SAFETY SCAN")[0],
          "RP-7 (O6): the census warns that the LICENSE is a placeholder")
    shipped = {p.relative_to(out).as_posix() for p in out.rglob("*")
               if p.is_file() and ".git" not in p.relative_to(out).parts}
    check(".Rprofile" in shipped, "RP-2 (O5): an exact-path include ships a dotfile")
    check(".env" not in shipped, "RP-2 (O5): an environment file is not shipped by default")
    check(not any(p.startswith("renv/") for p in shipped), "renv/library/ never ships")

    # Nothing named: [to confirm] markers, no LICENSE, and the census says so.
    plain = make_project(work, "plain")
    res = build(work, plain, "--yes", out=work / "plain-export")
    check_eq(res.rc, 0, f"a project with no registry builds ({res.describe()})")
    data_md = (work / "plain-export" / "DATA.md").read_text(encoding="utf-8")
    check("`[to confirm]`" in data_md and "Data in scope (from project profile)" in data_md,
          "RP-3: without a registry, DATA.md keeps the placeholder row and the profile section")
    cff = _cff(work / "plain-export" / "CITATION.cff")
    check_eq((cff["title"], cff["url"], cff["authors"][0]["family-names"]),
             (TITLE, "[to confirm]", "[to confirm]"), "RP-6: unfilled fields are [to confirm]")
    check(not (work / "plain-export" / "LICENSE").exists(), "RP-7: no license, no LICENSE")
    check("no license named" in res.out, "RP-7: the census says no license is named")

    # A dotfile include is scanned like any other file; renv/library and escapes refused.
    leaky = make_project(work, "leaky", manifest={"include": [".Rprofile"]},
                         files={".Rprofile": 'Sys.setenv(CENSUS_KEY = "abcdef123456")\n'})
    res = build(work, leaky, "--dry-run", out=work / "leaky-export")
    check(("CRITICAL", "secret/credential", ".Rprofile") in res.findings(),
          f"RP-2 (O5): an included dotfile is still scanned ({res.describe()})")
    for include, message in (("renv/library", "denylisted path"),
                             ("records/plans", "denylisted path"),
                             ("../outside/.env", "inside the project"),
                             ("/etc/hosts", "inside the project")):
        bad = make_project(work, f"bad{abs(hash(include))}", manifest={"include": [include]})
        res = build(work, bad, "--dry-run")
        check(res.rc == 1 and message in res.err, f"include: [{include}] is refused ({res.describe()})")
    return "README, DATA.md, CITATION.cff, LICENSE placeholder, dotfile include"


PHONE_POSITIVES = {"code/phone_paren.R": "# questions: (202) 555-0142\n",
                   "code/phone_dash.py": 'CONTACT = "202-555-0142"\n',
                   "code/phone_intl.R": "# +1 202.555.0142\n"}
PHONE_NEGATIVES = ('x <- c(202, 555, 142)\nssn_shape <- "123-45-6789"\npi <- 3.14159\n'
                   'd <- as.Date("2024-01-15")\nfips <- "01001"\n')


def case_15_scan_families(work: Path) -> str:
    """RP-4c "EIG template", RP-4d phone numbers, and RP-4e binary and size per O8."""
    files = {**PHONE_POSITIVES, "code/phone_negatives.R": PHONE_NEGATIVES,
             "code/eig.R": "# Built on the EIG template.\n",
             "code/eig_negative.R": "eig_template_version <- 2\nteig template <- 1\n"}
    project = make_project(work, files=files, manifest={
        "include_processed_data": True, "include": ["data/processed", "extras/model.bin"]})
    _binary(project / "code" / "model.rds")                 # unflagged binary: HIGH
    _binary(project / "data" / "processed" / "panel.rds")   # under a data flag: MEDIUM
    _binary(project / "extras" / "model.bin")               # exact include: MEDIUM
    _binary(project / "output" / "figures" / "fig2.png")    # a publication figure: nothing
    with open(project / "output" / "tables" / "big.csv", "wb") as fh:
        fh.truncate(51 * 1024 * 1024)                        # over 50 MB: MEDIUM
    with open(project / "output" / "tables" / "huge.csv", "wb") as fh:
        fh.truncate(100 * 1024 * 1024)                       # 100 MB or more: HIGH
    res = build(work, project, "--dry-run")
    check_eq(res.rc, 0, f"dry run ({res.describe()})")
    found = set(res.findings())
    expected = {("HIGH", "shell reference", "code/eig.R"),
                ("HIGH", "binary file", "code/model.rds"),
                ("MEDIUM", "binary file", "data/processed/panel.rds"),
                ("MEDIUM", "binary file", "extras/model.bin"),
                ("MEDIUM", "oversized file", "output/tables/big.csv"),
                ("HIGH", "oversized file", "output/tables/huge.csv"),
                *(("MEDIUM", "phone/PII", f) for f in PHONE_POSITIVES)}
    missing = sorted(expected - found)
    check(not missing, f"every RP-4c/d/e finding is raised at its severity; missing: {missing}")
    noisy = sorted(r for r in found if r[2] in ("code/phone_negatives.R", "code/eig_negative.R",
                                                "output/figures/fig2.png"))
    check(not noisy, f"numbers, dates, names, and figures are not flagged: {noisy}")
    return f"{len(expected)} findings at their O8 severities"


def case_16_opted_in_data_tracked(work: Path) -> str:
    """D-8: data the manifest opts into is tracked by the export's git, not ignored."""
    # A data flag unlocks the directory; `include` selects what ships from it.
    project = make_project(work, manifest={"include_raw_data": True,
                                           "include_processed_data": True,
                                           "include": ["data/raw", "data/processed"]})
    write(project / "data" / "processed" / "panel.parquet", "not really parquet\n")
    write(project / "data" / "raw" / "extract.dta", "not really stata\n")
    write(project / "code" / "cache.rds", "cached\n")
    res = build(work, project, "--yes")
    check_eq(res.rc, 0, f"the opted-in project builds ({res.describe()})")
    out = work / "export"
    tracked = set(subprocess.run(["git", "-C", str(out), "ls-files"], env=environment(work),
                                 text=True, capture_output=True,
                                 timeout=RUN_TIMEOUT_SECONDS).stdout.split())
    for rel in ("data/raw/input.csv", "data/raw/extract.dta", "data/processed/panel.parquet"):
        check(rel in tracked, f"D-8: the published {rel} is tracked, not ignored")
    # Only opted-in files are forced past the .gitignore; anything else is left to it.
    check("code/cache.rds" not in tracked, "a file nothing opted into stays under .gitignore")
    ignore = (out / ".gitignore").read_text(encoding="utf-8")
    check("data/raw/" not in ignore.split("\n"), "D-8: .gitignore no longer ignores data/raw/")
    return f"{len(tracked)} files tracked"


def case_17_generated_secrets(work: Path) -> str:
    """Review repro: a key in PROJECT.md or the registry reaches a generated file."""
    project = make_project(work)
    write(project / "PROJECT.md", PROFILE.replace(
        "- Do synthetic wages rise with synthetic tenure?",
        '- census_api_key("abcdef0123456789")\n- API_KEY = "abcdefghijk"'))
    overlay = {**OVERLAY, "datasets": [{**OVERLAY["datasets"][1],
                                        "agency": 'token = "abcdefghij"'}]}
    write_registries(project, overlay)
    res = build(work, project, "--yes")
    check(res.rc == 1 and "BLOCKED" in res.err, f"a key in generated text blocks ({res.describe()})")
    check(not (work / "export").exists(), "and nothing is written")
    hits = {f for sev, fam, f in res.findings() if sev == "CRITICAL" and "secret" in fam}
    for name in ("README.md (generated)", "DATA.md (generated)",
                 "data/docs/dataset-registry.yaml (DATA.md source)"):
        check(name in hits, f"the generated {name.split()[0]} is scanned for secrets: {hits}")
    return "README and DATA.md scanned for secrets; the build blocks"


def case_18_tabular_binaries(work: Path) -> str:
    """Review repro: microdata under output/tables/ shipped with no finding."""
    tables = make_project(work, "tables")
    _binary(tables / "output" / "tables" / "microdata.dta")
    _binary(tables / "output" / "tables" / "cps.parquet")
    _binary(tables / "output" / "figures" / "fig2.png")
    _binary(tables / "output" / "figures" / "fig3.pdf")
    res = build(work, tables, "--dry-run", out=work / "tables-export")
    found = set(res.findings())
    for rel in ("output/tables/microdata.dta", "output/tables/cps.parquet"):
        check(("HIGH", "binary file", rel) in found, f"binary data under output/tables/ is HIGH: {rel}")
    figures = sorted(r for r in found if r[2].startswith("output/figures/"))
    check(not figures, f"image and PDF figures raise nothing: {figures}")
    return "binary data in output/tables/ HIGH; image and PDF figures clean"


def case_19_dot_segment_includes(work: Path) -> str:
    """Review repro (W3): `_norm` kept `.` segments, so a denied path passed as `./x`."""
    sys.path.insert(0, str(SCRIPTS))
    import validate_replication_manifest as vrm  # the validator, imported for its resolver

    private = {"records/session_logs/x.md": "PRIVATE-LOG\n", "Infrastructure/x.md": "SHELL\n",
               "data/raw/micro.csv": "id,income\n1,52000\n", ".git/config": "[core]\n"}
    bad = ["./records/session_logs/x.md", "data/./raw/micro.csv", "./Infrastructure/x.md",
           "./.git/config", "code//run_all.R", "code/."]
    for n, include in enumerate(bad):
        project = make_project(work, f"dot{n}", files=private, manifest={"include": [include]})
        res = build(work, project, "--yes", out=work / f"dot{n}-export")
        check(res.rc == 1 and "include" in res.err,
              f"include: [{include}] is refused by validation ({res.describe()})")
        check(not (work / f"dot{n}-export").exists(), f"include: [{include}] writes no export")
        # Defense in depth: the resolver rechecks every final path even when a caller skips
        # validation, with the same check the stager applies before copying.
        included, _ = vrm.resolve({"include": [include]}, project)
        leaked = [r for r in included if vrm.staged_path_problem(r, {"include": [include]})]
        check(not leaked, f"the resolver drops denied final paths for [{include}]: {leaked}")
    for rel in ("records/session_logs/x.md", "data/raw/micro.csv", ".git/config",
                "code/.git/config", "./code/run_all.R", "code/../records/x.md", "AGENTS.md"):
        check(vrm.staged_path_problem(rel, {}), f"the stager refuses the final path {rel}")
    check(vrm.staged_path_problem("code/run_all.R", {}) is None, "a clean path stages")
    check(vrm.staged_path_problem("data/raw/micro.csv", {"include_raw_data": True}) is None,
          "opted-in raw data stages")
    # Excludes too: `./code/secret_notes.R` matched nothing, so the file shipped.
    for n, exclude in enumerate(["./code/secret_notes.R", "code//secret_notes.R",
                                 "code/./secret_notes.R", "/code/secret_notes.R", "../code"]):
        project = make_project(work, f"ex{n}", files={"code/secret_notes.R": "# private\n"},
                               manifest={"exclude": [exclude]})
        res = build(work, project, "--yes", out=work / f"ex{n}-export")
        check(res.rc == 1 and "exclude" in res.err,
              f"exclude: [{exclude}] is refused by validation ({res.describe()})")
        check(not (work / f"ex{n}-export").exists(), f"exclude: [{exclude}] writes no export")
    check(vrm.staged_path_problem("code/secret_notes.R", {"exclude": ["code/./secret_notes.R"]}),
          "the stager's denylist normalizes excludes")
    return f"{len(bad)} dot-segment includes and 5 bad excludes refused; final paths rechecked"


CASES: list[tuple[int, str, Callable[[Path], Any]]] = [
    (1, "Clean build", case_1_clean_build),
    (2, "Secret detection", case_2_secret_detection),
    (3, "Secret false positives", case_3_secret_false_positives),
    (4, "Symlinks refused", case_4_symlinks_refused),
    (5, "Non-interactive confirm", case_5_non_interactive_confirm),
    (6, "Project title", case_6_project_title),
    (7, "Failure after staging", case_7_failure_after_staging),
    (8, "Empty include set", case_8_empty_include),
    (9, "Output path aliases", case_9_output_alias),
    (10, "Output path case alias", case_10_output_case_alias),
    (11, "Exit codes", case_11_exit_codes),
    (12, "Census snapshot", case_12_census_snapshot),
    (13, "Scanner precision", case_13_scanner_precision),
    (14, "Product alignment", case_14_product_alignment),
    (15, "Scan families", case_15_scan_families),
    (16, "Opted-in data tracked", case_16_opted_in_data_tracked),
    (17, "Generated secrets", case_17_generated_secrets),
    (18, "Tabular binaries", case_18_tabular_binaries),
    (19, "Dot-segment includes", case_19_dot_segment_includes),
]


def main() -> int:
    if shutil.which("git") is None:
        print("ERROR: git is required", file=sys.stderr)
        return 2
    started = time.monotonic()
    failures = 0
    tmp = Path(tempfile.mkdtemp(prefix="replication-test-"))
    try:
        for number, title, fn in CASES:
            work = tmp / f"case{number:02d}"
            work.mkdir()
            try:
                note = fn(work)
            except CaseFailure as exc:
                failures += 1
                print(f"FAIL  {number:>2}  {title}: {exc}")
                continue
            except Exception:  # an unexpected error is a failure with its traceback
                failures += 1
                print(f"FAIL  {number:>2}  {title}: unexpected error")
                traceback.print_exc()
                continue
            suffix = f"  ({note})" if note else ""
            print(f"PASS  {number:>2}  {title}{suffix}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    elapsed = time.monotonic() - started
    print(f"{len(CASES) - failures}/{len(CASES)} cases passed in {elapsed:.1f}s")
    if elapsed > TIME_LIMIT_SECONDS:
        print(f"FAIL  runtime {elapsed:.1f}s exceeds {TIME_LIMIT_SECONDS}s")
        return 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
