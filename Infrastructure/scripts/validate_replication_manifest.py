#!/usr/bin/env python3
"""Validate and resolve a replication publishing manifest.

The manifest (`replication.manifest.yaml` at a project root) declares the scope of
a public replication package. This script is consumed by
`build_replication_package.py`:

  validate <manifest>            -> schema check; exit 0 if valid, 1 otherwise.
  resolve  <manifest> <target>   -> print included source file paths (relative to
                                    <target>), one per line, after applying defaults,
                                    the immovable denylist, and the raw/processed flags.
                                    Exit 1, printing nothing to stdout, if any path in
                                    scope is a symlink: symlinks are never published,
                                    because one can pull in content from outside the
                                    project (a home directory, data/raw/, /etc).
  title    <PROJECT.md>          -> print the Research Project Title (the first non-blank
                                    line under that heading, list marker and backticks
                                    removed), or an empty line if there is none.
  scan-secrets <target>          -> read file paths (relative to <target>) on stdin and
                                    print `path<TAB>lineno:text` for each line that
                                    assigns a credential literal (RP-4a forms that need
                                    more than grep -E can express).

Binding rules: Infrastructure/rules/replication-publishing-rules.md (RP-2, RP-5).
The denylist is immovable: the manifest may add to it but may never allowlist a
denied path. It is compared without regard to case, because on a case-insensitive
filesystem `Data/Raw` is `data/raw`. Loader uses PyYAML.
"""

from __future__ import annotations

import argparse
import os
import posixpath
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write(
        "PyYAML is required (pip install pyyaml). "
        "It backs the dataset-registry and literature validators too.\n"
    )
    sys.exit(2)

# --- Canonical defaults (RP-2) ------------------------------------------------

DEFAULT_ALLOW = ["code", "output/figures", "output/tables"]

# Path prefixes that are NEVER published. The manifest may extend this list but
# may never remove an entry or allowlist a path that falls under one of these.
DENY_PREFIXES = [
    "Infrastructure",
    "records",         # project records: plans, specs, session logs, ledgers, boards
    ".claude",
    ".codex",
    ".agents",
    ".git",
    "drafts",
    "output/logs",
    "review-reports",
    "data/raw",        # conditionally re-enabled by include_raw_data
    "data/processed",  # conditionally re-enabled by include_processed_data
    "renv/library",    # installed packages: renv.lock rebuilds them (owner default O5)
]

DENY_FILES = ["CLAUDE.md", "AGENTS.md", "Makefile", ".gitattributes", ".gitignore"]

CITATION_KEYS = {"authors", "title", "year", "url"}

RECOGNIZED_KEYS = {
    "output_dir",
    "include",
    "exclude",
    "include_raw_data",
    "include_processed_data",
    "license",
    "citation",
}


def _load(manifest_path: Path) -> dict:
    if not manifest_path.is_file():
        _fail(f"Manifest not found: {manifest_path}")
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        _fail(f"Manifest is not valid YAML: {exc}")
    if not isinstance(data, dict):
        _fail("Manifest top level must be a mapping of keys to values.")
    return data


def _fail(msg: str) -> None:
    sys.stderr.write(f"ERROR: {msg}\n")
    sys.exit(1)


def _norm(p: str) -> str:
    return p.strip().strip("/").replace("\\", "/")


def _segments_ok(p: str) -> bool:
    """No empty, `.`, or `..` segment: `./records/x` would dodge the prefix denylist."""
    return all(part not in ("", ".", "..") for part in _norm(p).split("/"))


def _active_deny(data: dict) -> list[str]:
    """The denylist in force for this manifest: defaults less opted-in data, plus excludes."""
    raw_ok = bool(data.get("include_raw_data", False))
    proc_ok = bool(data.get("include_processed_data", False))
    deny = [d for d in DENY_PREFIXES
            if not (d == "data/raw" and raw_ok) and not (d == "data/processed" and proc_ok)]
    return deny + [posixpath.normpath(_norm(x)) for x in (data.get("exclude") or [])
                   if isinstance(x, str) and _norm(x)]


def staged_path_problem(rel: str, data: dict) -> str | None:
    """Why a final path must not be staged, or None. Checked on every path the resolver
    returns and again before the builder copies it, whatever produced the path."""
    if rel != posixpath.normpath(rel) or not _segments_ok(rel) or rel.startswith("/"):
        return "not a normalized relative path"
    parts = rel.split("/")
    if any(part.casefold() == ".git" for part in parts):
        return "inside a .git directory"
    if _denied_file(parts[-1]):
        return "a denylisted file"
    for deny in _active_deny(data):
        if _denied(rel, deny):
            return f"under denylisted path '{deny}'"
    return None


def _under(path: str, prefix: str) -> bool:
    path = _norm(path)
    prefix = _norm(prefix)
    return path == prefix or path.startswith(prefix + "/")


def _denied(path: str, prefix: str) -> bool:
    """The denylist ignores case: on a case-insensitive disk `Data/Raw` is `data/raw`."""
    return _under(path.casefold(), prefix.casefold())


def _denied_file(name: str) -> bool:
    return _norm(name).casefold() in {f.casefold() for f in DENY_FILES}


def _has_dot_component(path: str) -> bool:
    return any(part.startswith(".") for part in _norm(path).split("/"))


def validate(data: dict) -> list[str]:
    errors: list[str] = []

    unknown = set(data) - RECOGNIZED_KEYS
    if unknown:
        errors.append(f"Unknown manifest key(s): {', '.join(sorted(unknown))}")

    for key in ("include", "exclude"):
        val = data.get(key, [])
        if val is None:
            continue
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            errors.append(f"`{key}` must be a list of strings.")

    for key in ("include_raw_data", "include_processed_data"):
        if key in data and not isinstance(data[key], bool):
            errors.append(f"`{key}` must be true or false.")

    if "license" in data and data["license"] is not None and not isinstance(data["license"], str):
        errors.append("`license` must be a string or null.")

    citation = data.get("citation")
    if citation is not None and not isinstance(citation, dict):
        errors.append("`citation` must be a mapping or null.")
    elif citation:
        unknown_cite = set(citation) - CITATION_KEYS
        if unknown_cite:
            errors.append(f"Unknown `citation` key(s): {', '.join(sorted(unknown_cite))}")
        authors = citation.get("authors")
        if authors is not None and not (isinstance(authors, list)
                                        and all(isinstance(a, str) for a in authors)):
            errors.append("`citation.authors` must be a list of strings, such as "
                          "[\"Family, Given\"].")

    # The denylist is immovable: an `include` entry may not target a denied path.
    raw_ok = bool(data.get("include_raw_data", False))
    proc_ok = bool(data.get("include_processed_data", False))
    # An exclude that is not a plain relative path matches nothing, so what it meant to
    # keep out would ship: `./code/notes.R` is not `code/notes.R` to the prefix match.
    for exc in data.get("exclude") or []:
        if isinstance(exc, str) and (
                exc.strip().startswith(("/", "\\", "~")) or re.match(r"[A-Za-z]:", exc.strip())
                or not _segments_ok(exc)):
            errors.append(f"`exclude` entry '{exc}' must be a normalized relative path inside "
                          "the project, with no empty, `.`, or `..` segment.")
    for inc in data.get("include") or []:
        if not isinstance(inc, str):
            continue
        if inc.strip().startswith(("/", "\\", "~")) or re.match(r"[A-Za-z]:", inc.strip()) \
                or not _segments_ok(inc):
            errors.append(f"`include` entry '{inc}' must be a normalized relative path inside "
                          "the project, with no empty, `.`, or `..` segment.")
            continue
        for deny in DENY_PREFIXES:
            if deny == "data/raw" and raw_ok:
                continue
            if deny == "data/processed" and proc_ok:
                continue
            if _denied(inc, deny):
                errors.append(
                    f"`include` entry '{inc}' targets denylisted path '{deny}'. "
                    "The denylist cannot be overridden."
                )
        if _denied_file(inc):
            errors.append(f"`include` entry '{inc}' targets a denylisted file.")

    return errors


def resolve(data: dict, target: Path) -> tuple[list[str], list[str]]:
    """Return (included files, refused symlinks), both relative to `target` and sorted.

    A symlink is refused, never included, when it is a file in scope or a directory that
    is in scope or contains an allowlisted path. Excluding it in the manifest is the only
    way past the refusal.
    """
    allow = list(DEFAULT_ALLOW) + [posixpath.normpath(_norm(x)) for x in (data.get("include") or [])
                                   if _norm(x)]
    active_deny = _active_deny(data)

    included: list[str] = []
    refused: list[str] = []
    for root, dirs, files in os.walk(target):
        # Prune denied / dot directories early for speed and safety.
        rel_root = _norm(os.path.relpath(root, target))
        pruned = []
        for d in dirs:
            rel = _norm(os.path.join(rel_root, d)) if rel_root != "." else d
            if d.startswith(".") or any(_denied(rel, dp) for dp in active_deny):
                continue
            if os.path.islink(os.path.join(root, d)):
                # os.walk does not descend into it; refuse it if it is in scope.
                if any(_under(rel, a) or _under(a, rel) for a in allow):
                    refused.append(rel)
                continue
            pruned.append(d)
        dirs[:] = pruned

        for f in files:
            rel = _norm(os.path.join(rel_root, f)) if rel_root != "." else f
            if _has_dot_component(rel):
                continue
            if _denied_file(f):
                continue
            if any(_denied(rel, dp) for dp in active_deny):
                continue
            if not any(_under(rel, a) for a in allow):
                continue
            if os.path.islink(os.path.join(root, f)):
                refused.append(rel)
                continue
            included.append(rel)

    # RP-2 (owner default O5): a dotfile ships only when `include` names its exact path,
    # such as `.Rprofile`; it is then scanned like every other file.
    for rel in (x for x in allow if _has_dot_component(x) and x not in included):
        path = target / rel
        if _denied_file(rel.rsplit("/", 1)[-1]) or any(_denied(rel, dp) for dp in active_deny):
            continue
        if not path.exists() and not path.is_symlink():
            continue
        # A link anywhere on the way, not just at the end, could reach outside the project.
        if path.is_symlink() or Path(os.path.realpath(path)) != Path(os.path.realpath(target)) / rel:
            refused.append(rel)
        elif path.is_file():
            included.append(rel)

    # Defense in depth: recheck every final path, however the allowlist produced it.
    included = [rel for rel in included if staged_path_problem(rel, data) is None]
    return sorted(included), sorted(refused)


def project_title(project_md: Path) -> str:
    """The first non-blank line under `## Research Project Title`, unwrapped."""
    lines = project_md.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## research project title"):
            for nxt in lines[i + 1:]:
                s = nxt.strip()
                if s.startswith("#"):
                    return ""
                if s:
                    return re.sub(r"^[-*+]\s+", "", s).strip().strip("`").strip()
            return ""
    return ""


# --- RP-4a credential scan -------------------------------------------------------
# The high-signal token formats (AWS, GitHub, Slack, private keys) stay in the scan table
# of build_replication_package.py. The forms below need lookarounds and value checks, so
# they live here. A match is CRITICAL.

# Words that make an identifier credential-like. Generic `*_key` names are left out on
# purpose: `merge_key <- "household_id"` is not a credential.
_CRED = (
    r"(?:password|passwd|secret|token|api[_-]?key|apikey"
    r"|(?:access|private|auth|client|app|dev|subscription|registration|census|fred|bls|bea"
    r"|ipums|noaa|eia|usda|quandl|nasdaq|openai|google)[_-]?key)"
)
# An environment-variable name that holds a credential.
_ENV_NAME = r"\w*(?:key|token|secret|pass|pwd|auth)\w*"
# A quoted literal of at least six characters, optionally wrapped in R's c().
_VALUE = r"(?:c\(\s*)?(?P<q>[\"'])(?P<val>[^\"'\n]{6,})(?P=q)"
_ASSIGN = r"\s*(?:<<-|<-|=|:)\s*"
# URL query parameters that carry a key, and a value shaped like one: 16 or more letters,
# digits, and hyphens with at least one digit (hex keys, UUIDs), never an underscore.
_QUERY_NAME = r"api[_-]?key|apikey|access_token|token|key"
_KEY_VALUE = r"(?=[A-Za-z0-9-]*\d)[A-Za-z0-9-]{16,}"

_SECRET_PATTERNS = [
    # An unquoted credential-named identifier assigned a literal: api_key <- "...",
    # API_KEY = "...", config$token <- "...", self.api_key = "...", fred_key = "...".
    # A name inside quotes is not an assignment here (c("token_id" = "token_id")).
    re.compile(rf"(?<![\w\"'])(?P<name>[\w.$]*{_CRED}\w*){_ASSIGN}{_VALUE}", re.I),
    # pwd as a whole word, optionally prefixed: pwd = "...", db_pwd <- "...".
    re.compile(rf"(?<![\w\"'.$])(?P<name>(?:[A-Za-z0-9]+_)?pwd)(?!\w){_ASSIGN}{_VALUE}", re.I),
    # A quoted name counts only with a colon (JSON, YAML, Python dicts): {"api_key": "..."}.
    re.compile(rf"(?P<nq>[\"'])(?P<name>[\w.-]*{_CRED}[\w.-]*)(?P=nq)\s*:\s*{_VALUE}", re.I),
    # A key passed straight to a setter: census_api_key("..."), fredr_set_key("..."),
    # blsAPI::setkey(key = "...").
    re.compile(rf"(?:api[_-]?key|set_?key)\s*\(\s*(?:\w+\s*=\s*)?{_VALUE}", re.I),
    # Environment setters with a credential-named variable.
    re.compile(rf"Sys\.setenv\([^)]*?\b{_ENV_NAME}\s*=\s*{_VALUE}", re.I),
    re.compile(rf"os\.environ\[\s*[\"']{_ENV_NAME}[\"']\s*\]\s*=\s*{_VALUE}", re.I),
    re.compile(rf"os\.putenv\(\s*[\"']{_ENV_NAME}[\"']\s*,\s*{_VALUE}", re.I),
    # .Renviron / .env style lines: CENSUS_API_KEY=abc123 (unquoted, whole line).
    re.compile(r"^\s*(?:export\s+)?[A-Z0-9_]*(?:PASSWORD|PASSWD|PWD|SECRET|KEY|TOKEN)[A-Z0-9_]*"
               r"=[^\s()]{6,}\s*$"),
    # Credentials in a URL: postgres://user:pass@host.
    re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@\"']+:[^/\s@\"']+@", re.I),
    # An HTTP bearer token: Authorization: Bearer <token>.
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    # A key in a URL query: ...acs5?get=NAME&key=<40 hex>, or split from it by paste0:
    # paste0("...&key=", "<40 hex>"). The value must look like a key (_KEY_VALUE), so a
    # template slot ({key}), a placeholder (YOUR_CENSUS_KEY), or a table name
    # (2022_acs5_table) is not one.
    re.compile(rf"[?&](?P<name>{_QUERY_NAME})=(?P<val>{_KEY_VALUE})(?=[&\s\"'#;),]|$)", re.I),
    re.compile(rf"[?&](?P<name>{_QUERY_NAME})=[\"']\s*,\s*(?P<q>[\"'])(?P<val>{_KEY_VALUE})(?P=q)", re.I),
    # A bare `key` passed a key-like literal: list(key = "<hex>"), params={"key": "<hex>"}.
    # Not part of a longer name (cache_key), and not a comparison (key == "...").
    re.compile(rf"(?<![\w.$-])(?P<nq>[\"']?)(?P<name>key)(?P=nq)\s*(?:<-|=(?!=)|:)\s*"
               rf"(?P<q>[\"'])(?P<val>(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{{20,}})(?P=q)", re.I),
]

# YAML files only: a credential-named key with an unquoted value on its own line
# (api_key: abc123, x-api-key: ...). A value with spaces, quotes, braces, or `$` is prose,
# a quoted value (handled above), or a ${VAR} reference.
_YAML_SECRET = re.compile(
    rf"^\s*(?:-\s+)?(?P<name>[\w.-]*{_CRED}[\w.-]*)\s*:\s*"
    r"(?P<val>[^\s\"'#{}\[\]$]{6,})\s*(?:#.*)?$",
    re.I,
)

# A name that points at or describes a credential rather than holding one:
# api_key_file, secrets_dir, tokenizer_name, password_prompt, token_col. The suffix counts
# only after an underscore, so `client_secret_valid` and `auth_token_profile` are not
# excused by "id" and "file". `_id` names an identifier, except right after a token,
# secret, or password stem: `token_id` and `client_secret_id` are credentials (owner
# default O7, Phase 3D plan).
_HARMLESS_NAME = re.compile(
    r"(?:izer|_(?:file|path|dir|name|pattern|col|column|var|env|prompt|label|field|url|id))$",
    re.I,
)
_CREDENTIAL_ID = re.compile(r"(?:token|secret|password|passwd)_id$", re.I)

# A value that is an environment-variable NAME, not a secret: api_key_env = "CENSUS_API_KEY".
_ENV_NAME_VALUE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")
# tidytext's unnest_tokens(token = ...) tokenizer names.
_TOKENIZERS = {"words", "characters", "character_shingles", "ngrams", "skip_ngrams",
               "sentences", "lines", "paragraphs", "regex", "tweets", "ptb"}


def _is_secret_match(m: re.Match) -> bool:
    groups = m.groupdict()
    val = groups.get("val")
    if val is None:
        return True
    if _ENV_NAME_VALUE.fullmatch(val):
        return False
    name = (groups.get("name") or "").lower()
    if name and _HARMLESS_NAME.search(name) and not _CREDENTIAL_ID.search(name):
        return False
    if name == "token" and val in _TOKENIZERS:
        return False
    return True


def scan_secret_text(name: str, text: str, *, yaml_like: bool | None = None) -> list[str]:
    """Return `name<TAB>lineno:text` for every line of `text` holding a credential literal.

    `yaml_like` adds the unquoted-YAML pattern; by default it follows `name`'s extension
    (`.yml`, `.yaml`, and `.cff`, which is YAML).
    """
    if yaml_like is None:
        yaml_like = name.lower().endswith((".yml", ".yaml", ".cff"))
    patterns = [*_SECRET_PATTERNS, *([_YAML_SECRET] if yaml_like else [])]
    def holds(line: str) -> bool:
        return any(_is_secret_match(m) for p in patterns for m in p.finditer(line))

    lines = text.splitlines()
    alone = [holds(line) for line in lines]
    hits = []
    for i, line in enumerate(lines):
        # An assignment whose value is on the next line (`registrationkey =` then the key)
        # is read as one line, and the hit names the line that opens it; a next line that
        # holds a credential on its own is reported by itself.
        split = (i + 1 < len(lines) and not alone[i + 1]
                 and line.rstrip().endswith(("=", ":", "<-"))
                 and holds(f"{line.rstrip()} {lines[i + 1].lstrip()}"))
        if alone[i] or split:
            hits.append(f"{name}\t{i + 1}:{line}")
    return hits


def scan_secrets(target: Path, rel_paths: list[str]) -> list[str]:
    """Return `path<TAB>lineno:text` for every line holding a credential literal."""
    hits: list[str] = []
    for rel in rel_paths:
        try:
            data = (target / rel).read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:  # binary, as grep -I would judge it
            continue
        hits += scan_secret_text(rel, data.decode("utf-8", errors="replace"),
                                 yaml_like=rel.lower().endswith((".yml", ".yaml")))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("scan-secrets", help="Scan files (paths on stdin) for credentials.")
    ps.add_argument("target")

    pt = sub.add_parser("title", help="Print the project title from PROJECT.md.")
    pt.add_argument("project_md")

    pv = sub.add_parser("validate", help="Schema-check the manifest.")
    pv.add_argument("manifest")

    pr = sub.add_parser("resolve", help="Print included source files, one per line.")
    pr.add_argument("manifest")
    pr.add_argument("target")

    args = parser.parse_args()
    if args.cmd == "scan-secrets":
        target = Path(args.target).expanduser()
        rels = [ln.rstrip("\n") for ln in sys.stdin if ln.strip()]
        for hit in scan_secrets(target, rels):
            print(hit)
        return 0

    if args.cmd == "title":
        path = Path(args.project_md).expanduser()
        if not path.is_file():
            _fail(f"PROJECT.md not found: {path}")
        print(project_title(path))
        return 0

    manifest_path = Path(args.manifest).expanduser()
    data = _load(manifest_path)

    if args.cmd == "validate":
        errors = validate(data)
        if errors:
            for e in errors:
                sys.stderr.write(f"ERROR: {e}\n")
            return 1
        print(f"Manifest OK: {manifest_path}")
        return 0

    if args.cmd == "resolve":
        errors = validate(data)
        if errors:
            for e in errors:
                sys.stderr.write(f"ERROR: {e}\n")
            return 1
        target = Path(args.target).expanduser().resolve()
        if not target.is_dir():
            _fail(f"Target directory not found: {target}")
        included, refused = resolve(data, target)
        if refused:
            for rel in refused:
                link = target / rel
                try:
                    dest = os.readlink(link)
                except OSError:
                    dest = "?"
                sys.stderr.write(f"ERROR: symlink refused: {rel} -> {dest}\n")
            sys.stderr.write(
                "ERROR: symlinks are never published, because a symlink can pull in content "
                "from outside the project. Replace each one with a regular file, or add it "
                "to `exclude` in the manifest.\n"
            )
            return 1
        for rel in included:
            print(rel)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
