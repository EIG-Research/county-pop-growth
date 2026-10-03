#!/usr/bin/env python3
"""Test suite for the researcher lane: the R rule's examples and the pipeline runner.

`python3 Infrastructure/scripts/test_project_lane.py` from anywhere. Finding ids (`P-D13`)
refer to the template's modernization census of the project lane, a template-development
record that `make template-reset` removes from a project.

Cases, one `PASS` line each:

     1  Filtering example drops NA   P-D13: the R rule's masked-filter example, run on a
                                     data frame and a tibble that each hold an NA age, keeps
                                     only the valid rows and adds no all-NA row
     2  Runner refuses outside       P-D5: `code/run_all.R` started from outside the
                                     project exits non-zero and creates nothing
     3  Runner logs its children     P-D4, P-D6: run from the root and from `code/`, the
                                     runner exits 0, writes only under `output/logs/`, and
                                     the log holds each child's message, warning, and
                                     sessionInfo(); children load the root `.Rprofile`
     4  Runner stops on failure      P-D6: a failing script stops the run with a non-zero
                                     exit that names it, and later scripts do not run
     5  Children are isolated        P-D7: a script cannot see the runner's objects
     6  Example data regenerates     P-D10: the seeded generator in `data/example/README.md`
                                     rewrites the committed synthetic CSVs byte for byte
     7  Example pipeline and note    P-D10, P-E.10: the worked example runs end to end in a
                                     copy, writes only under `output/` and `data/processed/`,
                                     and each number `drafts/example_note.md` traces (before
                                     any `;`) appears in its prose and equals the named row
                                     and column of the named table; three planted note
                                     mutations must each fail that check
     8  Runner restores directory    `source("run_all.R")` from `code/` leaves the session
                                     in `code/` after a failing script

Cases 2-5 run a temporary copy of `code/run_all.R` with every flag turned on, over stub
numbered scripts, so they test the runner and not the project's own scripts.

The suite writes only to one temporary directory, removed at the end, and uses no network.

R is optional here. Without `Rscript` or a package a case needs, the suite prints
`SKIPPED: <reason>` (or `SKIP` for one case) and exits 0; with `REQUIRE_R=1` in the
environment, a skip is a failure. Cases 6 and 7 pass as "not applicable" once a project
removes the worked example.

Exit codes: 0 every case passed (or the suite skipped); 1 a case failed, or a skip under
`REQUIRE_R=1`; 2 the environment is unusable.
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parent.parent
R_RULE = REPO_ROOT / "Infrastructure" / "rules" / "r-coding-style-rules.md"
RUN_TIMEOUT_SECONDS = 60
R_PACKAGES = ("dplyr", "tibble", "here")

R_BLOCK_RE = re.compile(r"^```r\n(.*?)^```", re.MULTILINE | re.DOTALL)


class Skip(Exception):
    """Raised when the environment lacks R or a package a case needs."""


def find_rscript() -> str:
    rscript = shutil.which("Rscript")
    if rscript is None:
        raise Skip("Rscript not found on PATH")
    probe = "cat(all(vapply(c({}), requireNamespace, logical(1L), quietly = TRUE)))".format(
        ", ".join(f'"{name}"' for name in R_PACKAGES)
    )
    result = subprocess.run(
        [rscript, "-e", probe],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_SECONDS,
    )
    if result.returncode != 0 or result.stdout.strip() != "TRUE":
        raise Skip("R packages {} not all installed".format(", ".join(R_PACKAGES)))
    return rscript


def filtering_example() -> str:
    """Return the rule's R example that builds `prime_age_data`."""
    text = R_RULE.read_text(encoding="utf-8")
    blocks = [block for block in R_BLOCK_RE.findall(text) if "prime_age_data <-" in block]
    if len(blocks) != 1:
        raise AssertionError(
            f"expected one R example defining prime_age_data in {R_RULE}, found {len(blocks)}"
        )
    return blocks[0]


def case_filtering_example_drops_na(rscript: str, workdir: Path) -> None:
    example = filtering_example()
    script = workdir / "filtering_example.R"
    script.write_text(
        "\n".join(
            [
                "base_data <- data.frame(",
                "  age_num = c(30, NA, 60, 40, 45),",
                "  employment_status_valid = c(1L, 1L, 1L, NA_integer_, 2L)",
                ")",
                "for (fixture_kind in c('data.frame', 'tibble')) {",
                "  analysis_data <- base_data",
                "  if (fixture_kind == 'tibble') analysis_data <- tibble::as_tibble(base_data)",
                example,
                "  kept_ages <- prime_age_data$age_num",
                "  if (!identical(kept_ages, c(30, 45))) {",
                "    stop(fixture_kind, ': kept ages ', paste(kept_ages, collapse = ', '),",
                "         '; expected 30, 45')",
                "  }",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    result = subprocess.run(
        [rscript, "--vanilla", str(script)],
        capture_output=True,
        text=True,
        cwd=workdir,
        timeout=RUN_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip() or result.stdout.strip())


RUNNER = REPO_ROOT / "code" / "run_all.R"
FLAG_BLOCK_RE = re.compile(r"^run_script_flag <- c\((.*?)^\)", re.MULTILINE | re.DOTALL)
STUB_NAMES = ("01_build_dataset.R", "02_analysis.R", "03_make_figures.R")


def stub_project(root: Path, stubs: dict[str, str], rprofile: str | None = None) -> Path:
    """Copy the runner into `root/code/` with every flag TRUE, beside stub scripts."""
    runner_text = RUNNER.read_text(encoding="utf-8")
    match = FLAG_BLOCK_RE.search(runner_text)
    if match is None:
        raise AssertionError("code/run_all.R has no `run_script_flag <- c(...)` vector")
    flags = match.group(1)
    for name in STUB_NAMES:
        if f'"{name}"' not in flags:
            raise AssertionError(f"run_script_flag does not list {name}")
    turned_on = re.sub(r"=\s*FALSE", "= TRUE", flags)
    runner_text = runner_text[: match.start(1)] + turned_on + runner_text[match.end(1) :]
    (root / "code").mkdir(parents=True)
    (root / "code" / "run_all.R").write_text(runner_text, encoding="utf-8", newline="\n")
    for name in STUB_NAMES:
        body = stubs.get(name, f'message("stub {name} ran")\n')
        (root / "code" / name).write_text(body, encoding="utf-8", newline="\n")
    if rprofile is not None:
        (root / ".Rprofile").write_text(rprofile, encoding="utf-8", newline="\n")
    return root


def run_runner(rscript: str, runner: Path, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [rscript, str(runner)],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=RUN_TIMEOUT_SECONDS * 3,
    )


def tree(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def only_log(root: Path, result: subprocess.CompletedProcess) -> str:
    """Return the single run log's text, asserting it is the run's only new file."""
    logs = sorted((root / "output" / "logs").glob("run_all_*.log"))
    if len(logs) != 1:
        raise AssertionError(f"expected one run log, found {len(logs)}: {result.stderr}")
    return logs[0].read_text(encoding="utf-8")


def case_runner_refuses_outside(rscript: str, workdir: Path) -> None:
    project = stub_project(workdir / "project", {})
    outside = workdir / "outside"
    outside.mkdir()
    before = tree(project)
    result = run_runner(rscript, project / "code" / "run_all.R", outside)
    if result.returncode == 0:
        raise AssertionError("the runner exited 0 from outside the project")
    if tree(project) != before or any(outside.iterdir()):
        raise AssertionError("the runner created files when started outside the project")


def case_runner_logs_children(rscript: str, workdir: Path) -> None:
    stubs = {
        "01_build_dataset.R": 'message("CHILD_MESSAGE_01")\nwarning("CHILD_WARNING_01")\n',
        "02_analysis.R": 'message("CHILD_MESSAGE_02 in ", basename(getwd()))\n',
    }
    rprofile = 'message("RPROFILE_LOADED")\n'
    for start in ("root", "code"):
        project = stub_project(workdir / start, stubs, rprofile=rprofile)
        before = tree(project)
        cwd = project if start == "root" else project / "code"
        result = run_runner(rscript, Path("code/run_all.R") if start == "root"
                            else Path("run_all.R"), cwd)
        if result.returncode != 0:
            raise AssertionError(f"from {start}: exit {result.returncode}: {result.stderr}")
        new_files = tree(project) - before
        stray = sorted(path for path in new_files if not path.startswith("output/logs/"))
        if stray:
            raise AssertionError(f"from {start}: files written outside output/logs/: {stray}")
        log = only_log(project, result)
        expected = {
            "the first child's message": "CHILD_MESSAGE_01",
            "the first child's warning": "CHILD_WARNING_01",
            "the second child running at the root": f"CHILD_MESSAGE_02 in {project.name}",
            "the third child's message": "stub 03_make_figures.R ran",
        }
        for what, needle in expected.items():
            if needle not in log:
                raise AssertionError(f"from {start}: the log lacks {what} ({needle!r})")
        if log.count("--- sessionInfo() ---") != len(STUB_NAMES):
            raise AssertionError(f"from {start}: the log lacks a sessionInfo() per child")
        if log.count("RPROFILE_LOADED") < len(STUB_NAMES):
            raise AssertionError(f"from {start}: children did not load the root .Rprofile")


def case_runner_stops_on_failure(rscript: str, workdir: Path) -> None:
    stubs = {
        "02_analysis.R": 'stop("PLANTED_FAILURE")\n',
        "03_make_figures.R": 'file.create("output/should_not_exist")\n',
    }
    project = stub_project(workdir / "project", stubs)
    result = run_runner(rscript, Path("code/run_all.R"), project)
    if result.returncode == 0:
        raise AssertionError("the runner exited 0 after a failing script")
    if "code/02_analysis.R failed" not in result.stderr:
        raise AssertionError(f"the error does not name the failing script: {result.stderr}")
    if (project / "output" / "should_not_exist").exists():
        raise AssertionError("a script after the failing one still ran")
    if "PLANTED_FAILURE" not in only_log(project, result):
        raise AssertionError("the log lacks the failing script's error")


def case_runner_restores_directory(rscript: str, workdir: Path) -> None:
    project = stub_project(workdir / "project", {"02_analysis.R": 'stop("PLANTED_FAILURE")\n'})
    probe = (
        'failed <- inherits(try(source("run_all.R"), silent = TRUE), "try-error"); '
        'cat(failed, basename(getwd()))'
    )
    result = subprocess.run(
        [rscript, "-e", probe],
        capture_output=True,
        text=True,
        cwd=project / "code",
        timeout=RUN_TIMEOUT_SECONDS * 3,
    )
    if result.stdout.split() != ["TRUE", "code"]:
        raise AssertionError(
            f"expected a failed run that returns to code/, got {result.stdout.strip()!r}"
        )


def case_children_isolated(rscript: str, workdir: Path) -> None:
    stubs = {
        "01_build_dataset.R": (
            'leaked <- intersect(c("run_script_flag", "log_file", "log_step"), ls(globalenv()))\n'
            'if (length(leaked) > 0L) stop("runner objects visible: ", toString(leaked))\n'
        ),
    }
    project = stub_project(workdir / "project", stubs)
    result = run_runner(rscript, Path("code/run_all.R"), project)
    if result.returncode != 0:
        raise AssertionError(f"exit {result.returncode}: {result.stderr.strip()[-400:]}")


EXAMPLE_DATA = REPO_ROOT / "data" / "example"
EXAMPLE_NOTE = REPO_ROOT / "drafts" / "example_note.md"
EXAMPLE_PACKAGES = ("readr", "arrow", "fixest", "ggplot2", "systemfonts", "ragg")
NOTE_ROW_RE = re.compile(
    r"^\| (?P<claim>[^|]+?) \| `(?P<file>output/tables/[^`]+)` \| (?P<where>[^|]+) \|$",
    re.MULTILINE,
)


def require_packages(rscript: str, packages: tuple[str, ...]) -> None:
    probe = "cat(names(which(!vapply(c({}), requireNamespace, logical(1L), quietly = TRUE))))"
    result = subprocess.run(
        [rscript, "-e", probe.format(", ".join(f'"{name}"' for name in packages))],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_SECONDS,
    )
    missing = result.stdout.split()
    if result.returncode != 0 or missing:
        raise Skip("R packages not installed: " + (" ".join(missing) or "probe failed"))


def case_example_data_regenerates(rscript: str, workdir: Path) -> str | None:
    readme = EXAMPLE_DATA / "README.md"
    if not readme.is_file():
        return "not applicable: data/example/ was removed"
    blocks = R_BLOCK_RE.findall(readme.read_text(encoding="utf-8"))
    if len(blocks) != 1:
        raise AssertionError(f"expected one R generator block in {readme}, found {len(blocks)}")
    (workdir / "data" / "example").mkdir(parents=True)
    (workdir / "generate.R").write_text(blocks[0], encoding="utf-8", newline="\n")
    result = subprocess.run(
        [rscript, "--vanilla", "generate.R"],
        capture_output=True,
        text=True,
        cwd=workdir,
        timeout=RUN_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr.strip())
    csvs = sorted(EXAMPLE_DATA.glob("*.csv"))
    if not csvs:
        raise AssertionError("data/example/ holds no CSV files")
    for csv in csvs:
        regenerated = workdir / "data" / "example" / csv.name
        if not regenerated.is_file() or regenerated.read_bytes() != csv.read_bytes():
            raise AssertionError(f"the README generator does not reproduce {csv.name}")
    return None


def case_example_pipeline(rscript: str, workdir: Path) -> str | None:
    if not (EXAMPLE_DATA.is_dir() and EXAMPLE_NOTE.is_file()):
        return "not applicable: the worked example was removed"
    require_packages(rscript, EXAMPLE_PACKAGES)
    project = workdir / "project"
    shutil.copytree(REPO_ROOT / "code", project / "code")
    shutil.copytree(EXAMPLE_DATA, project / "data" / "example")
    shutil.copytree(
        REPO_ROOT / "Infrastructure" / "style" / "themes" / "r",
        project / "Infrastructure" / "style" / "themes" / "r",
    )
    before = tree(project)
    result = run_runner(rscript, Path("code/run_all.R"), project)
    if result.returncode != 0:
        raise AssertionError(f"exit {result.returncode}: {result.stderr.strip()[-600:]}")
    stray = sorted(
        path
        for path in tree(project) - before
        if not path.startswith(("output/", "data/processed/"))
    )
    if stray:
        raise AssertionError(f"the pipeline wrote outside output/ and data/processed/: {stray}")
    note = EXAMPLE_NOTE.read_text(encoding="utf-8")
    traced = check_note(note, project)

    # The check must catch a changed prose number and a changed trace-table number.
    mutations = {
        "prose wage": ("$18.23.", "$19.99."),
        "prose coefficient": ("coefficient -0.1879", "coefficient -0.2500"),
        "trace-table count": ("| 303 workers |", "| 3 workers |"),
    }
    for label, (old, new) in mutations.items():
        if old not in note:
            raise AssertionError(f"mutation '{label}' no longer applies: {old!r} not in the note")
        try:
            check_note(note.replace(old, new, 1), project)
        except AssertionError:
            continue
        raise AssertionError(f"the note check missed the '{label}' mutation")
    return f"{traced} note rows traced; {len(mutations)} mutations caught"


NOTE_TRACE_HEADING = "## Where each number comes from"
CLAIM_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def note_number_re(number: str) -> re.Pattern[str]:
    """Match `number` as a whole number in prose: no digit or decimal point runs on."""
    return re.compile(r"(?<![\d.])" + re.escape(number) + r"(?!\.?\d)")


def check_note(note: str, project: Path) -> int:
    """Check every trace row: its numbers are in the prose and in the named table cells."""
    if NOTE_TRACE_HEADING not in note:
        raise AssertionError(f"drafts/example_note.md lacks the {NOTE_TRACE_HEADING!r} heading")
    prose, trace = note.split(NOTE_TRACE_HEADING, 1)
    rows = list(NOTE_ROW_RE.finditer(trace))
    if not rows:
        raise AssertionError("drafts/example_note.md has no number-to-table rows")
    for row in rows:
        numbers = CLAIM_NUMBER_RE.findall(row["claim"].split(";")[0])
        names = re.findall(r"`([^`]+)`", row["where"])
        if not numbers or len(names) != len(numbers) + 1:
            raise AssertionError(
                f"trace row {row['claim']!r} must name one row and one column per number"
            )
        for number in numbers:
            if not note_number_re(number).search(prose):
                raise AssertionError(f"the note's {number} does not appear in its prose")
        table = project / row["file"]
        if not table.is_file():
            raise AssertionError(f"the note cites {row['file']}, which the pipeline did not write")
        with table.open(encoding="utf-8", newline="") as handle:
            records = list(csv.reader(handle))
        header, body = records[0], records[1:]
        matches = [record for record in body if record and record[0] == names[0]]
        if len(matches) != 1:
            raise AssertionError(f"{row['file']} has {len(matches)} rows named {names[0]!r}")
        for number, column in zip(numbers, names[1:]):
            if column not in header:
                raise AssertionError(f"{row['file']} has no column {column!r}")
            cell = matches[0][header.index(column)]
            if float(cell) != float(number.replace(",", "")):
                raise AssertionError(
                    f"the note says {number} but {row['file']} {names[0]}/{column} is {cell}"
                )
    return len(rows)


CASES: list[tuple[str, Callable[[str, Path], str | None]]] = [
    ("Filtering example drops NA", case_filtering_example_drops_na),
    ("Runner refuses outside", case_runner_refuses_outside),
    ("Runner logs its children", case_runner_logs_children),
    ("Runner stops on failure", case_runner_stops_on_failure),
    ("Children are isolated", case_children_isolated),
    ("Example data regenerates", case_example_data_regenerates),
    ("Example pipeline and note", case_example_pipeline),
    ("Runner restores directory", case_runner_restores_directory),
]


def main() -> int:
    require_r = os.environ.get("REQUIRE_R") == "1"
    if not R_RULE.is_file():
        print(f"environment unusable: {R_RULE} not found")
        return 2
    try:
        rscript = find_rscript()
    except Skip as reason:
        print(f"SKIPPED: {reason}")
        return 1 if require_r else 0

    failures = 0
    with tempfile.TemporaryDirectory(prefix="project-lane-") as tmp:
        for number, (name, case) in enumerate(CASES, start=1):
            workdir = Path(tmp) / f"case{number:02d}"
            workdir.mkdir()
            try:
                detail = case(rscript, workdir)
            except Skip as reason:
                if require_r:
                    failures += 1
                    print(f"FAIL {number:2d} {name}: skipped under REQUIRE_R=1: {reason}")
                else:
                    print(f"SKIP {number:2d} {name}: {reason}")
            except Exception as error:  # noqa: BLE001 - report every case
                failures += 1
                print(f"FAIL {number:2d} {name}: {error}")
                if not isinstance(error, AssertionError):
                    traceback.print_exc()
            else:
                print(f"PASS {number:2d} {name}" + (f"  [{detail}]" if detail else ""))

    print(f"{len(CASES) - failures}/{len(CASES)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
