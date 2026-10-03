#!/usr/bin/env python3
"""Run the maintenance checks in CHECKS, continue past failures, and summarize.

    run_maintenance_checks.py                 every registered check (`make maintenance-check`)
    run_maintenance_checks.py --only NAME...  the named checks (`make style-test`, ...)
    run_maintenance_checks.py --list          the registry: name, command, and what it guards

CHECKS below is the one registry. Docs name a check by its registry name and point here (or
at `--list`) instead of restating the set or its size. Adding a check is one entry.

Output contract, which CI and the orchestrator parse: each check streams its own output under
a `==> [i/N] name` header and ends PASS, FAIL, or SKIP; then one line

    Summary  <P> passed, <F> failed[, <S> skipped] in <T> total

and exit status 0 exactly when no check failed. A check that cannot run on this machine (R
absent, say) prints a line starting `SKIPPED:` and exits 0; the runner reports it as SKIP,
visibly, and it does not count as a failure. CI sets `REQUIRE_R=1`, under which such a check
fails instead.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 900  # seconds per check; the slowest suite takes well under a minute


@dataclass(frozen=True)
class Check:
    name: str
    command: str  # run from the repository root; a leading `python3` is this interpreter
    guards: str


CHECKS = (
    Check("brain-check", "python3 Infrastructure/scripts/brain.py check --only drift",
          "generated adapter files and .brain-manifest match their canonical sources"),
    Check("brain-lints", "python3 Infrastructure/scripts/brain.py check --only lints",
          "canonical frontmatter, generated TOML and frontmatter, invocation hygiene, duplication"),
    Check("brain-load", "python3 Infrastructure/scripts/brain.py check --only load",
          "always-loaded word ceiling, required AGENTS.md anchors, loading map"),
    Check("hook-tests", "python3 Infrastructure/scripts/test_hooks.py",
          "the guard, reminder, and session hooks under both adapters; the command policy"),
    Check("brain-tests", "python3 Infrastructure/scripts/test_brain.py",
          "brain.py sync and check against a throwaway copy of the repository"),
    Check("literature-catalog", "python3 Infrastructure/scripts/validate_literature_catalog.py",
          "literature catalog schema and paths"),
    Check("dataset-registry", "python3 Infrastructure/scripts/validate_dataset_registry.py",
          "dataset registry schema and two-layer governance"),
    Check("internal-paths", "python3 Infrastructure/scripts/check_internal_path_references.py",
          "internal path references in Markdown resolve"),
    Check("path-reference-tests", "python3 Infrastructure/scripts/test_path_references.py",
          "the path checker catches broken root-relative, ./, and ../ references"),
    Check("census", "python3 Infrastructure/scripts/check_census.py",
          "TEMPLATE_CENSUS.md names every agent, skill, rule, template, script, check, and make target"),
    Check("census-tests", "python3 Infrastructure/scripts/test_census.py",
          "the census check catches a missing part and a stale entry"),
    Check("catalog-staleness", "python3 Infrastructure/scripts/check_catalog_staleness.py",
          "literature entries verified recently"),
    Check("knowledge-store-tests", "python3 Infrastructure/scripts/test_knowledge_stores.py",
          "the catalog, registry, and staleness validators reject planted bad entries"),
    Check("style-tokens", "python3 Infrastructure/scripts/check_style_token_drift.py",
          "generated style themes match the token file; no stray hex colors"),
    Check("style-tests", "python3 Infrastructure/scripts/test_style.py",
          "style tokens, generated themes, and the R, Python, and Stata themes and examples"),
    Check("war-room-tests", "python3 Infrastructure/scripts/test_war_room.py",
          "code war room prep, lint, server, reconcile, and render"),
    Check("review-board-tests", "python3 Infrastructure/scripts/test_review_board.py",
          "review board CLI, lint, measurement, and server"),
    Check("replication-tests", "python3 Infrastructure/scripts/test_replication.py",
          "replication-package builder refusals and export"),
    Check("port-tests", "python3 Infrastructure/scripts/test_port_template.py",
          "template port: private-only and other refusals, adopt, upgrade, and rollback"),
    Check("localapp-tests", "python3 Infrastructure/scripts/test_localapp.py",
          "the shared local-app kit: YAML IO, file lock, project root, loopback server"),
    Check("review-fleet-tests", "python3 Infrastructure/scripts/test_review_fleet.py",
          "review discovery manifest, pipeline run and reuse, findings schema and renderer, consolidation"),
    Check("review-eval-tests", "python3 Infrastructure/scripts/test_review_eval.py",
          "planted-defect fixture patches still apply; eval scorer on canned findings"),
    Check("project-lane-tests", "python3 Infrastructure/scripts/test_project_lane.py",
          "the R rule's examples, code/run_all.R, and the worked example (skips without R)"),
)

TTY = sys.stdout.isatty()


def paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if TTY else text


def duration(seconds: float) -> str:
    return f"{int(seconds * 1000)}ms" if seconds < 1 else f"{seconds:.1f}s"


def run(check: Check) -> tuple[str, int, float, str]:
    """(PASS | FAIL | SKIP, exit code, seconds, skip reason); the output streams as it arrives."""
    words = check.command.split()
    argv = [sys.executable, *words[1:]] if words[0] == "python3" else words
    start = time.monotonic()
    try:
        proc = subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                errors="replace", bufsize=1)
    except OSError as exc:
        print(f"    could not start: {exc}")
        return "FAIL", 127, time.monotonic() - start, ""
    skips: list[str] = []

    def stream() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            if line.startswith("SKIPPED:"):
                skips.append(line[len("SKIPPED:"):].strip() or "no reason given")

    reader = threading.Thread(target=stream, daemon=True)
    reader.start()
    try:
        code = proc.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = proc.wait()
        print(f"    timed out after {TIMEOUT}s")
        code = code or 124
    reader.join(timeout=10)
    seconds = time.monotonic() - start
    if code:
        return "FAIL", code, seconds, ""
    return ("SKIP" if skips else "PASS"), 0, seconds, skips[0] if skips else ""


def main(argv: list[str] | None = None) -> int:
    names = [check.name for check in CHECKS]
    parser = argparse.ArgumentParser(description="Run the maintenance checks.", allow_abbrev=False)
    parser.add_argument("--only", action="append", choices=names, metavar="NAME",
                        help="run only this check (repeatable); see --list")
    parser.add_argument("--list", action="store_true", help="print the check registry and exit")
    args = parser.parse_args(argv)
    if args.list:
        width = max(map(len, names))
        print("".join(f"{c.name:<{width}}  {c.guards}\n{'':<{width}}  {c.command}\n" for c in CHECKS), end="")
        return 0
    selected = [check for check in CHECKS if not args.only or check.name in args.only]
    results = []
    start = time.monotonic()
    try:
        for index, check in enumerate(selected, 1):
            print(f"\n{paint('1', f'==> [{index}/{len(selected)}] {check.name}')}")
            print(paint("2", f"    {check.command}"), flush=True)
            status, code, seconds, reason = run(check)
            results.append((check.name, status, code, seconds, reason))
            detail = {"PASS": "", "SKIP": f"; {reason}", "FAIL": f", exit={code}"}[status]
            colour = {"PASS": "32", "SKIP": "33", "FAIL": "31"}[status]
            print(f"    {paint(colour, status)}  ({duration(seconds)}{detail})")
    except KeyboardInterrupt:
        print(paint("31", "\nInterrupted; aborting maintenance suite."), file=sys.stderr)
        return 130
    counts = {status: sum(1 for r in results if r[1] == status) for status in ("PASS", "FAIL", "SKIP")}
    rule = "=" * 70
    skipped = f", {counts['SKIP']} skipped" if counts["SKIP"] else ""
    passed = f"{counts['PASS']} passed"
    failed = f"{counts['FAIL']} failed"
    line = (f"{paint('1', 'Summary')}  {passed if counts['FAIL'] else paint('32', passed)}, "
            f"{paint('31', failed) if counts['FAIL'] else failed}{skipped} in {duration(time.monotonic() - start)} total")
    print(f"\n{paint('1', rule)}\n{line}\n{paint('1', rule)}")
    for wanted in ("FAIL", "SKIP", "PASS"):  # failures first, so they sit nearest the summary
        for name, status, code, seconds, reason in results:
            if status == wanted:
                detail = {"PASS": "", "SKIP": f"; {reason}", "FAIL": f", exit={code}"}[status]
                colour = {"PASS": "32", "SKIP": "33", "FAIL": "31"}[status]
                print(f"  {paint(colour, status)}  {name:<26}  ({duration(seconds)}{detail})")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")  # children stream line by line
    raise SystemExit(main())
