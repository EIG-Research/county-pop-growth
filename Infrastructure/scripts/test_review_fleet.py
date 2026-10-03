#!/usr/bin/env python3
"""Test suite for the review fleet's scripts: discovery, the pipeline run, the renderer, and
full-review's consolidation.

`python3 Infrastructure/scripts/test_review_fleet.py` from anywhere. One `PASS` line per case:

     1  Template pipeline found     the template layout resolves `code/run_all.R`, a top-level
                                    run-all script wins over `code/`, and a `pipeline:` line
                                    in PROJECT.md wins over both
     2  Exclusions at any depth     nested `renv/`, `Infrastructure/`, `temp/`, `output/logs/`
                                    and the rest are never listed; only the include roots are
                                    walked; `.docx` is listed as unsupported
     3  Unchanged inputs reuse      a second run with the same input hash does not rerun the
                                    pipeline; a changed code, data, helper (anywhere, `.sh`
                                    included), or PROJECT.md file does, as do deleted or edited
                                    outputs and `--force`
     4  Failure, timeout, Stata     a failing pipeline exits 1 with its log tail; a hung one is
                                    killed at the timeout; `.do` runs under `stata-mp`/`stata-se`;
                                    no pipeline and a Tier 4 timeout exit 2
     5  Invalid findings refused    no evidence, an unknown or other-lens `check_id`, a HIGH
                                    without a refutation, a low-confidence non-Question, and
                                    SUGGESTION outside the code lens are rejected; nothing written
     6  Golden, byte-identical      the fixtures render byte for byte like
                                    `review_fleet_fixtures/golden/`, twice; counts and risk
                                    follow the contract (an unconfirmed HIGH does not set risk)
     7  Values escaped              `<script>`, markup, and quotes in any field are escaped;
                                    the CSP forbids script
     8  IDs survive a line shift    IDs ignore line numbers and whitespace in the quote;
                                    collisions get ordinals in line order
     9  Duplicates consolidate      canned duplicates collapse to the owner lens (a filter to
                                    CC, an external figure to AS, a lens's own repeat); other
                                    families at one anchor cross-link; every HIGH is queued for
                                    its agent; a refuted verdict becomes a Question; `start`
                                    clears a run; an invalid lens file stops the step unless set
                                    aside; both steps repeat to the same bytes

The golden files change only on purpose: rerun with `REVIEW_FLEET_UPDATE_GOLDEN=1` to
rewrite them (a token change in `Infrastructure/style/tokens/` also changes them), and review
the diff. Every case works in its own temporary directory and uses no network or R.
Exit codes: 0 pass, 1 fail.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent
sys.path.insert(0, str(SCRIPTS))

import render_review_report as rr  # noqa: E402
import review_manifest as rm  # noqa: E402
from localapp.testkit import CaseFailure, check, check_eq  # noqa: E402

MANIFEST = SCRIPTS / "review_manifest.py"
RENDERER = SCRIPTS / "render_review_report.py"
FIXTURES = SCRIPTS / "review_fleet_fixtures"
GOLDEN = FIXTURES / "golden"


def touch(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(MANIFEST), *args], capture_output=True, text=True,
                          timeout=120, env=env)


# --------------------------------------------------------------------------- manifest
def case_template_pipeline(work: Path) -> str:
    project = work / "project"
    for name in ("run_all.R", "01_build_dataset.R", "02_analysis.R"):
        touch(project / "code" / name, (REPO / "code" / name).read_text(encoding="utf-8"))
    touch(project / "drafts" / "note.md", "# Note\n")
    result = cli("discover", str(project))
    check_eq(result.returncode, 0, "discover exits 0 on the template layout")
    manifest = json.loads(result.stdout)
    check_eq(manifest["pipeline"], {"path": "code/run_all.R", "kind": "r", "source": "code/"},
             "the template's own pipeline resolves from the project root")
    check("code/run_all.R" in manifest["code_files"], "the pipeline is listed as code")

    touch(project / "run_all.py", "print('top')\n")
    check_eq(rm.discover(project)["pipeline"]["path"], "run_all.py",
             "a top-level run-all script wins over code/")
    check("run_all.py" in rm.discover(project)["code_files"],
          "a top-level pipeline is listed even outside the include roots")

    touch(project / "PROJECT.md", "# Project\n\n## Working agreements\n- pipeline: `code/02_analysis.R`\n")
    check_eq(rm.discover(project)["pipeline"],
             {"path": "code/02_analysis.R", "kind": "r", "source": "PROJECT.md"},
             "a pipeline: line in PROJECT.md wins over both")
    touch(project / "PROJECT.md", "- pipeline: code/missing.R\n")
    result = cli("discover", str(project))
    check(result.returncode == 2 and "code/missing.R" in result.stderr,
          f"a PROJECT.md pipeline that does not exist is refused: {result.stderr}")
    return "code/run_all.R, top level, PROJECT.md"


def case_exclusions(work: Path) -> str:
    project = work / "project"
    touch(project / "code" / "run_all.R")
    touch(project / "code" / "clean.py")
    touch(project / "drafts" / "paper.tex")
    touch(project / "drafts" / "README.md")
    touch(project / "drafts" / "brief.docx", "binary")
    planted = []
    for nested in ("renv", "Infrastructure", "temp", "review-reports", ".venv", "node_modules",
                   ".git", ".claude", ".codex", ".agents", "__pycache__", "output/logs"):
        for base in ("code", "code/sub", "drafts"):
            planted.append(touch(project / base / nested / "planted.R"))
            planted.append(touch(project / base / nested / "planted.md"))
    touch(project / "Infrastructure" / "scripts" / "tool.py")
    touch(project / "notes" / "outside.R")
    manifest = rm.discover(project)
    listed = manifest["code_files"] + manifest["document_files"]
    leaked = [p for p in listed if "planted" in p or "outside" in p or "tool.py" in p]
    check_eq(leaked, [], "no excluded or out-of-root file is listed")
    check_eq(manifest["code_files"], ["code/clean.py", "code/run_all.R"], "code files")
    check_eq(manifest["document_files"], ["drafts/paper.tex"], "documents skip README.md")
    check_eq([u["path"] for u in manifest["unsupported_files"]], ["drafts/brief.docx"],
             ".docx is listed as unsupported")
    check("output/logs" in manifest["exclude_paths"] and "renv" in manifest["exclude_dirs"],
          "the manifest records the exclude list it applied")
    wider = rm.discover(project, ["code", "drafts", "notes"])
    check("notes/outside.R" in wider["code_files"], "an extra include root is walked")
    check_eq(rm.discover(project, ["missing"])["missing_include_roots"], ["missing"],
             "a missing include root is reported, not an error")
    excludes = cli("excludes").stdout.split()
    check("renv/" in excludes and "output/logs/" in excludes, "`excludes` prints the list")
    return f"{len(planted)} planted files excluded"


# --------------------------------------------------------------------------- pipeline run
COUNTER_PIPELINE = """\
from pathlib import Path
counter = Path("data") / "processed" / "runs.txt"
counter.parent.mkdir(parents=True, exist_ok=True)
counter.write_text(str(int(counter.read_text()) + 1 if counter.exists() else 1))
Path("output", "tables").mkdir(parents=True, exist_ok=True)
Path("output", "tables", "result.csv").write_text("a\\n1\\n")
print("pipeline ran from", Path.cwd().name)
"""


def runs(project: Path) -> int:
    counter = project / "data" / "processed" / "runs.txt"
    return int(counter.read_text()) if counter.exists() else 0


def case_reuse(work: Path) -> str:
    project = work / "project"
    touch(project / "code" / "run_all.py", COUNTER_PIPELINE)
    touch(project / "code" / "helper.py", "x = 1\n")
    touch(project / "data" / "raw" / "input.csv", "a\n1\n")
    touch(project / "data" / "processed" / "cache.csv", "a\n1\n")
    first = cli("run", str(project))
    check(first.returncode == 0 and "Pipeline completed successfully." in first.stdout,
          f"first run succeeds: {first.stdout}{first.stderr}")
    check_eq(runs(project), 1, "the pipeline ran once, from the project root")
    record = json.loads((project / "review-reports" / "pipeline-run.json").read_text())
    check_eq((record["exit_code"], record["tier"], record["timeout_seconds"]), (0, "Tier 2", 900),
             "the record states exit code, tier, and timeout")
    check((project / "review-reports" / "_scratch" / "pipeline-run.log").is_file(),
          "the log lands in review-reports/_scratch/")

    second = cli("run", str(project))
    check(second.returncode == 0 and "Reusing" in second.stdout, f"reused: {second.stdout}")
    check_eq(runs(project), 1, "an unchanged input hash skips the run")

    touch(project / "data" / "processed" / "cache.csv", "a\n2\n")
    cli("run", str(project))
    check_eq(runs(project), 1, "data/processed/ is not an input")
    touch(project / "drafts" / "note.md", "# Note\n")
    cli("run", str(project))
    check_eq(runs(project), 1, "a draft is not a pipeline input")

    touch(project / "code" / "helper.py", "x = 2\n")
    cli("run", str(project))
    check_eq(runs(project), 2, "a changed code file reruns")
    touch(project / "data" / "raw" / "input.csv", "a\n2\n")
    cli("run", str(project))
    check_eq(runs(project), 3, "a changed data file reruns")
    cli("run", str(project), "--force")
    check_eq(runs(project), 4, "--force reruns")

    touch(project / "scripts" / "helpers" / "clean.sh", "echo one\n")
    cli("run", str(project))
    check_eq(runs(project), 5, "a new helper outside the include roots reruns")
    touch(project / "scripts" / "helpers" / "clean.sh", "echo two\n")
    cli("run", str(project))
    check_eq(runs(project), 6, "a changed .sh helper outside the include roots reruns")
    touch(project / "PROJECT.md", "# Project\n")
    cli("run", str(project))
    check_eq(runs(project), 7, "a changed PROJECT.md reruns")
    touch(project / "code" / "renv" / "library" / "pkg.R", "x <- 1\n")
    touch(project / "output" / "logs" / "old.log", "log\n")
    cli("run", str(project))
    check_eq(runs(project), 7, "excluded folders and run logs are not inputs")

    # W3 review: a symlinked data folder was not followed, and the style themes the code
    # sources (`Infrastructure/style/themes/r/eig_theme.R`) sat under an excluded folder.
    outside = work / "outside-raw"
    touch(outside / "input.csv", "a\n1\n")
    # Without symlink privilege (Windows without Developer Mode) the two symlink runs are
    # skipped, and the later run counts shift down by two.
    shift = 0
    try:
        (project / "data" / "linked").symlink_to(outside, target_is_directory=True)
        (project / "data" / "loop").symlink_to(project / "data", target_is_directory=True)
    except OSError:
        shift = 2
        print("  (symlinked-data checks skipped: this account cannot create symlinks)")
    if not shift:
        cli("run", str(project))
        check_eq(runs(project), 8, "a symlinked data folder is an input (and a link cycle ends)")
        touch(outside / "input.csv", "a\n2\n")
        cli("run", str(project))
        check_eq(runs(project), 9, "a changed file behind a data symlink reruns")
    theme = project / "Infrastructure" / "style" / "themes" / "r" / "eig_theme.R"
    touch(theme, "theme <- 1\n")
    cli("run", str(project))
    check_eq(runs(project), 10 - shift, "a new style theme reruns")
    touch(theme, "theme <- 2\n")
    cli("run", str(project))
    check_eq(runs(project), 11 - shift, "a changed style theme reruns")
    touch(project / "Infrastructure" / "rules" / "note.md", "rule\n")
    cli("run", str(project))
    check_eq(runs(project), 11 - shift, "the rest of Infrastructure/ is not an input")

    import shutil
    shutil.rmtree(project / "output")
    result = cli("run", str(project))
    check("Reusing" not in result.stdout and runs(project) == 12 - shift,
          f"a deleted output directory reruns: {result.stdout}")
    touch(project / "output" / "tables" / "result.csv", "edited\n")
    cli("run", str(project))
    check_eq(runs(project), 13 - shift, "an edited output reruns")
    record = json.loads((project / "review-reports" / "pipeline-run.json").read_text())
    check(record["output_fingerprint"].startswith("sha256:"), "the record keeps the output fingerprint")
    return "1 run, 1 reuse, 11 reruns (code, data, linked data, helper, PROJECT.md, themes, outputs)"


def case_failure_timeout_stata(work: Path) -> str:
    failing = work / "failing"
    touch(failing / "code" / "run_all.py", "import sys\nprint('bad row')\nsys.exit(3)\n")
    result = cli("run", str(failing))
    check(result.returncode == 1 and "exit code 3" in result.stdout and "bad row" in result.stdout,
          f"a failing pipeline exits 1 with its tail: {result.stdout}")
    again = cli("run", str(failing))
    check("Reusing" not in again.stdout, "a failed run is never reused")

    hung = work / "hung"
    touch(hung / "code" / "run_all.py", "import time\ntime.sleep(30)\n")
    started = time.monotonic()
    result = cli("run", str(hung), "--timeout", "1")
    check(result.returncode == 1 and "timed out after 1s" in result.stdout,
          f"a hung pipeline is stopped: {result.stdout}")
    check(time.monotonic() - started < 20, "the timeout kills the run promptly")
    record = json.loads((hung / "review-reports" / "pipeline-run.json").read_text())
    check_eq((record["timed_out"], record["exit_code"], record["tier"]), (True, 124, "Tier 1"),
             "the timeout is recorded")
    # W3 review: os.killpg does not exist on Windows; the timeout must still stop the run.
    import contextlib
    import io
    killpg = os.__dict__.pop("killpg", None)
    try:
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = rm.run_pipeline(hung, 1, True, False)
    except AttributeError as exc:
        raise CaseFailure(f"a timeout without os.killpg must fall back to kill(): {exc}") from None
    finally:
        if killpg is not None:
            os.killpg = killpg
    check(code == 1 and "timed out after 1s" in printed.getvalue(),
          f"without os.killpg the hung run is still stopped: {printed.getvalue()}")

    stata = work / "stata"
    touch(stata / "run_all.do", "display 1\n")
    fakebin = work / "bin"
    if sys.platform == "win32":  # no shebangs on Windows; a .cmd is found through PATHEXT
        fakebin.mkdir(parents=True, exist_ok=True)
        (fakebin / "stata-se.cmd").write_text("@echo stata-se %*> called.txt\r\n",
                                              encoding="utf-8", newline="")
    else:
        fake = touch(fakebin / "stata-se", '#!/bin/sh\necho "stata-se $*" > called.txt\n')
        fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{fakebin}{os.pathsep}/usr/bin{os.pathsep}/bin"}
    result = cli("run", str(stata), env=env)
    check_eq(result.returncode, 0, f"the .do pipeline ran: {result.stdout}{result.stderr}")
    check_eq((stata / "called.txt").read_text().strip(), "stata-se -b do run_all.do",
             "Stata runs in batch mode under stata-se when stata-mp is absent")
    empty_env = {**os.environ, "PATH": f"/usr/bin{os.pathsep}/bin"}
    result = cli("run", str(stata), "--force", env=empty_env)
    if not any(Path(d, b).exists() for d in ("/usr/bin", "/bin") for b in rm.STATA_BINARIES):
        check(result.returncode == 2 and "stata-mp" in result.stderr,
              f"a missing Stata is a usage error: {result.stderr}")

    nothing = work / "nothing"
    touch(nothing / "code" / "analysis.R")
    result = cli("run", str(nothing))
    check(result.returncode == 2 and "No pipeline found" in result.stderr,
          f"no pipeline exits 2: {result.stderr}")
    result = cli("run", str(failing), "--timeout", "7200")
    check(result.returncode == 2 and "Tier 4" in result.stderr, "a Tier 4 timeout needs confirmation")
    return "exit 1 with tail, killed at 1s, stata-se"


# --------------------------------------------------------------------------- renderer
def render_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RENDERER), *args], capture_output=True, text=True,
                          timeout=120)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def write_json(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8", newline="\n")
    return path


def case_rejects_invalid(work: Path) -> str:
    base = fixture("code.findings.json")

    def broken(label: str, mutate: Callable[[dict], None], expect: str) -> None:
        doc = json.loads(json.dumps(base))
        mutate(doc)
        folder = work / label
        write_json(folder / "code.findings.json", doc)
        result = render_cli(str(folder))
        check(result.returncode == 1 and expect in result.stderr,
              f"{label}: expected exit 1 naming {expect!r}, got {result.returncode}: {result.stderr}")
        check(not any(folder.glob("*.html")), f"{label}: nothing is written when validation fails")

    broken("no-evidence", lambda d: d["findings"][0].pop("evidence"), "missing required field `evidence`")
    broken("no-verification", lambda d: d["findings"][1]["evidence"].pop("verified_by"),
           "missing required field `verified_by`")
    broken("unknown-check", lambda d: d["findings"][0].update(check_id="CE-VIBES"), "'CE-VIBES' is not one of")
    broken("wrong-lens-check", lambda d: d["findings"][0].update(check_id="MR-WEIGHTS"),
           "'MR-WEIGHTS' is not one of")
    broken("high-no-refutation", lambda d: d["findings"][0].pop("refutation"),
           "missing required field `refutation`")
    broken("low-not-question", lambda d: d["findings"][1].update(confidence="low"), "must be 'QUESTION'")
    broken("no-quote-no-looked-in", lambda d: d["findings"][1]["evidence"].pop("quote"),
           "matches none of the allowed shapes")
    broken("unknown-field", lambda d: d["findings"][0].update(id="CE-001"), "unknown field `id`")
    broken("efficiency-not-suggestion", lambda d: d["findings"][2].update(severity="MEDIUM"),
           "'MEDIUM' is not one of SUGGESTION, QUESTION")
    broken("suggestion-not-efficiency", lambda d: d["findings"][1].update(severity="SUGGESTION"),
           "must be 'CE-EFFICIENCY'")

    mr = fixture("methodology.findings.json")
    mr["findings"][0]["severity"] = "SUGGESTION"
    folder = write_json(work / "mr-suggestion" / "methodology.findings.json", mr).parent
    result = render_cli(str(folder))
    check(result.returncode == 1 and "SUGGESTION" in result.stderr,
          f"SUGGESTION outside the code lens is rejected: {result.stderr}")
    return "11 invalid files refused, none written"


def case_golden_and_deterministic(work: Path) -> str:
    out1, out2 = work / "one", work / "two"
    for out in (out1, out2):
        result = render_cli(str(FIXTURES / "code.findings.json"),
                            str(FIXTURES / "methodology.findings.json"), "--out", str(out))
        check_eq(result.returncode, 0, f"render succeeds: {result.stderr}")
    names = sorted(p.name for p in out1.glob("*.html"))
    check_eq(names, ["code-error-report.html", "index.html", "methodology-report.html"], "files written")
    for name in names:
        check((out1 / name).read_bytes() == (out2 / name).read_bytes(), f"{name} re-renders byte-identically")
    if os.environ.get("REVIEW_FLEET_UPDATE_GOLDEN") == "1":
        for name in names:
            (GOLDEN / name).write_bytes((out1 / name).read_bytes())
        return "golden files rewritten"
    for name in names:
        check((out1 / name).read_bytes() == (GOLDEN / name).read_bytes(),
              f"{name} matches the golden render in {GOLDEN.relative_to(REPO)} "
              "(if the change is intended, rerun with REVIEW_FLEET_UPDATE_GOLDEN=1)")
    docs = rr.build([FIXTURES / "code.findings.json", FIXTURES / "methodology.findings.json"])
    ce, mr = docs
    check_eq((ce["tally"]["risk"], ce["tally"]["unconfirmed_high"], ce["tally"]["questions"],
              ce["tally"]["findings"]), ("HIGH", 0, 1, 3), "code lens counts and risk")
    check_eq((mr["tally"]["risk"], mr["tally"]["unconfirmed_high"]), ("LOW", 1),
             "a medium-confidence HIGH is unconfirmed and does not set the risk")
    return "3 files match the golden render"


def case_escaping(work: Path) -> str:
    doc = fixture("code.findings.json")
    doc["target"] = "<b>bold</b> & co"
    doc["findings"][0]["title"] = "<script>alert('title')</script>"
    doc["findings"][0]["evidence"]["quote"] = "</code></pre><script>alert(1)</script><img src=x onerror=alert(2)>"
    doc["findings"][1]["file"] = 'code/"quoted".R'
    folder = write_json(work / "in" / "code.findings.json", doc).parent
    result = render_cli(str(folder), "--out", str(work / "out"))
    check_eq(result.returncode, 0, f"render succeeds: {result.stderr}")
    for name in ("code-error-report.html", "index.html"):
        text = (work / "out" / name).read_text(encoding="utf-8")
        lowered = text.lower()
        check("<script" not in lowered and "<img" not in lowered and "<b>bold" not in lowered,
              f"{name}: no injected markup survives")
        check("&lt;script&gt;" in text, f"{name}: the script tag is escaped, not dropped")
        check("default-src 'none'" in text and "'unsafe-inline'" not in text,
              f"{name}: CSP forbids scripts and inline styles other than the hashed block")
        check('code/&quot;quoted&quot;.R' in text or name == "index.html",
              f"{name}: attribute-significant quotes are escaped")
    return "script, img, and quotes escaped; CSP present"


def case_ids_survive_line_shift(work: Path) -> str:
    doc = fixture("code.findings.json")
    original = rr.prepare(json.loads(json.dumps(doc)))
    shifted_doc = json.loads(json.dumps(doc))
    for finding in shifted_doc["findings"]:
        if "line" in finding:
            finding["line"] += 7
            if "end_line" in finding:
                finding["end_line"] += 7
    shifted_doc["findings"][1]["evidence"]["quote"] = "  mean_age   =  mean(age,\n na.rm = TRUE)  "
    shifted = rr.prepare(shifted_doc)
    ids = lambda d: sorted((f["check_id"], f["id"]) for f in d["findings"])  # noqa: E731
    check_eq(ids(shifted), ids(original), "IDs survive a line shift and whitespace-only quote changes")
    check(all(re.fullmatch(r"CE-[0-9a-f]{6}", f["id"]) for f in original["findings"]),
          "IDs are the lens prefix plus six hex digits")

    twin = json.loads(json.dumps(doc["findings"][1]))
    twin["line"] = 90
    twin["title"] = "Second mean over the same missing ages"
    doc["findings"].append(twin)
    first = {f["line"]: f["id"] for f in rr.prepare(json.loads(json.dumps(doc)))["findings"]
             if f["check_id"] == "CE-MISSING"}
    check_eq(first[90], first[51] + "-2", "a colliding finding gets an ordinal in line order")
    for finding in doc["findings"]:
        if "line" in finding:
            finding["line"] += 3
    doc["findings"].reverse()
    again = {f["line"]: f["id"] for f in rr.prepare(doc)["findings"] if f["check_id"] == "CE-MISSING"}
    check_eq((again[54], again[93]), (first[51], first[90]),
             "collision ordinals hold after a shift and a reordering of the input")
    changed = json.loads(json.dumps(fixture("code.findings.json")))
    changed["findings"][0]["evidence"]["quote"] = "left_join(workers_raw, states_raw)"
    join_id = lambda d: next(f["id"] for f in d["findings"] if f["check_id"] == "CE-JOIN")  # noqa: E731
    check(join_id(rr.prepare(changed)) != join_id(original), "a different quote gives a different ID")
    return "line shift, whitespace, collisions, reordering"


# --------------------------------------------------------------------------- consolidation
CONSOLIDATE = SCRIPTS / "review_consolidate.py"


def consolidate_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CONSOLIDATE), *args], capture_output=True, text=True,
                          timeout=120)


def canned(lens: str, findings: list[dict]) -> dict:
    return {"schema_version": 1, "lens": lens, "target": "wages", "review_date": "2026-09-29",
            "files_reviewed": sorted({f["file"] for f in findings}), "findings": findings}


def finding(check_id: str, severity: str, file: str, line: int | None, quote: str | None,
            title: str, confidence: str = "high", claim: str | None = None) -> dict:
    evidence = {"claim": claim or title, "found": title, "verified_by": "the quoted lines"}
    if quote is None:
        evidence["looked_in"] = [file]
    else:
        evidence["quote"] = quote
    item = {"check_id": check_id, "title": title, "severity": severity, "confidence": confidence,
            "file": file, "evidence": evidence}
    if line is not None:
        item["line"] = line
    if severity in ("HIGH", "CRITICAL"):
        item["refutation"] = "Looked for a disclosure or a handler elsewhere; none found."
    return item


def canned_duplicates(folder: Path) -> None:
    age = "filter(age >= 25, age <= 54)"
    write_json(folder / "code.findings.json", canned("CE", [
        finding("CE-JOIN", "HIGH", "code/01_clean.R", 30, "left_join(workers, states, by = \"state\")",
                "Many-to-many join duplicates workers"),
        finding("CE-JOIN", "HIGH", "code/01_clean.R", 30, "left_join(workers, states, by = \"state\")",
                "The same join, reported twice", confidence="medium",
                claim="Many-to-many  join duplicates workers"),
        # W3 review: two different findings of one lens on one line are not duplicates,
        # even with the same check id and quote; only a matching title or claim merges them.
        finding("CE-LOGIC", "HIGH", "code/02_analysis.R", 40, "wage_gap <- wage_m / wage_f",
                "Gap computed as a ratio, not a difference"),
        finding("CE-LOGIC", "HIGH", "code/02_analysis.R", 40, "wage_gap <- wage_m / wage_f",
                "Numerator and denominator swapped relative to the note"),
        finding("CE-MISSING", "MEDIUM", "code/02_analysis.R", 10, "mean(wage, na.rm = TRUE)",
                "Mean wage drops missing wages"),
        finding("CE-MISSING", "MEDIUM", "code/02_analysis.R", 50, "na.rm = TRUE",
                "A second statistic drops missing values")]))
    write_json(folder / "methodology.findings.json", canned("MR", [
        finding("MR-SAMPLE", "MEDIUM", "code/01_clean.R", 12, age, "Prime-age restriction as a design choice",
                confidence="medium"),
        finding("MR-WEIGHTS", "HIGH", "code/02_analysis.R", None, None, "Population mean without weights")]))
    write_json(folder / "consistency.findings.json", canned("CC", [
        finding("CC-UNDISCLOSED", "HIGH", "code/01_clean.R", 12, f"  {age}  ", "Undisclosed age filter"),
        finding("CC-INTERPRET", "MEDIUM", "drafts/note.md", 9, "about 19% less than", "Log points read as percent")]))
    write_json(folder / "numbers.findings.json", canned("DN", [
        finding("DN-TRACE", "MEDIUM", "drafts/note.md", 5, "4.1 percent", "Unemployment rate not in any output"),
        finding("DN-ARITH", "HIGH", "drafts/note.md", 9, "19% less", "0.19 log points is about 17 percent")]))
    write_json(folder / "provenance.findings.json", canned("AS", [
        finding("AS-EXTERNAL", "HIGH", "drafts/note.md", 5, "BLS reports 4.1 percent unemployment",
                "BLS figure differs from the published rate")]))


def case_consolidation(work: Path) -> str:
    reports = work / "review-reports"
    canned_duplicates(reports)
    originals = {p.name: p.read_bytes() for p in reports.glob("*.findings.json")}
    result = consolidate_cli("consolidate", str(reports))
    check_eq(result.returncode, 0, f"consolidate succeeds: {result.stderr}")
    check("Merged 3 duplicate finding(s); 1 cross-link(s)" in result.stdout, f"summary line: {result.stdout}")
    phase1 = reports / "_scratch" / "phase1"
    check({p.name: p.read_bytes() for p in phase1.glob("*.findings.json")} == originals,
          "the phase-1 lens files are kept unchanged")
    docs = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in reports.glob("*.findings.json")}
    by_check = {f["check_id"]: f for d in docs.values() for f in d["findings"]}
    ids = {f["check_id"]: fid for d in docs.values()
           for f, fid in zip(d["findings"], rr.assign_ids(d["lens"], d["findings"]))}
    check("MR-SAMPLE" not in by_check and "CC-UNDISCLOSED" in by_check,
          "the undisclosed filter collapses to the consistency lens, its owner")
    check("DN-TRACE" not in by_check and "AS-EXTERNAL" in by_check,
          "the untraced external figure collapses to the provenance lens, its owner")
    check_eq(sorted(f["check_id"] for f in docs["code.findings.json"]["findings"]),
             ["CE-JOIN", "CE-LOGIC", "CE-LOGIC", "CE-MISSING", "CE-MISSING"],
             "a lens's own repeat of a finding (same claim) collapses; the same text at another line, "
             "or a different finding on the same line, does not")
    check(any("(merged duplicate)" in r for r in by_check["CC-UNDISCLOSED"]["related"]),
          "the kept finding names the merged one")
    check(ids["CC-INTERPRET"] in by_check["DN-ARITH"]["related"]
          and ids["DN-ARITH"] in by_check["CC-INTERPRET"]["related"],
          "different families at one anchor are cross-linked both ways")
    check("MR-WEIGHTS" in by_check and "related" not in by_check["MR-WEIGHTS"], "an unrelated finding is untouched")
    queue = json.loads((reports / "_scratch" / "refute-queue.json").read_text(encoding="utf-8"))["queue"]
    check_eq(sorted((q["lens"], q["agent"]) for q in queue),
             [("AS", "ai-skeptic"), ("CC", "conceptual-consistency-reviewer"), ("CE", "code-reviewer"),
              ("CE", "code-reviewer"), ("CE", "code-reviewer"), ("DN", "data-consistency-reviewer"),
              ("MR", "methodology-reviewer")],
             "every HIGH or CRITICAL finding is queued for its owning agent")
    check_eq(render_cli(str(reports), "--check").returncode, 0, "the consolidated files render")

    first = {p.name: p.read_bytes() for p in reports.glob("*.findings.json")}
    check_eq(consolidate_cli("consolidate", str(reports)).returncode, 0, "consolidate runs again")
    check({p.name: p.read_bytes() for p in reports.glob("*.findings.json")} == first,
          "consolidate is repeatable: it starts again from phase 1")

    verdicts = reports / "_scratch" / "refutations"
    write_json(verdicts / "AS.json", {"verdicts": [{"id": ids["AS-EXTERNAL"], "verdict": "refuted",
                                                    "reason": "The note cites the seasonally adjusted rate, which is 4.1."}]})
    write_json(verdicts / "CC.json", {"verdicts": [{"id": ids["CC-UNDISCLOSED"], "verdict": "upheld",
                                                    "reason": "No footnote or appendix mentions the age range."}]})
    result = consolidate_cli("apply", str(reports))
    check_eq(result.returncode, 0, f"apply succeeds: {result.stderr}")
    check("Applied 1 refuted (now Questions) and 1 upheld" in result.stdout and "Not rechecked:" in result.stdout,
          f"apply summary: {result.stdout}")
    after = {f["check_id"]: f for p in reports.glob("*.findings.json")
             for f in json.loads(p.read_text(encoding="utf-8"))["findings"]}
    external = after["AS-EXTERNAL"]
    check((external["severity"], external["confidence"]) == ("QUESTION", "low")
          and "seasonally adjusted" in external["refutation"], "a refuted finding becomes a Question with the reason")
    check(after["CC-UNDISCLOSED"]["severity"] == "HIGH" and "Upheld" in after["CC-UNDISCLOSED"]["refutation"],
          "an upheld finding keeps its severity and gains the reason")
    applied = {p.name: p.read_bytes() for p in reports.glob("*.findings.json")}
    check_eq(consolidate_cli("apply", str(reports)).returncode, 0, "apply runs again")
    check({p.name: p.read_bytes() for p in reports.glob("*.findings.json")} == applied,
          "apply is repeatable: it starts again from phase 2")
    check_eq(render_cli(str(reports)).returncode, 0, "the index renders after the refutation pass")
    write_json(verdicts / "bad.json", {"verdicts": [{"id": "CE-000000", "verdict": "maybe", "reason": "x"}]})
    check_eq(consolidate_cli("apply", str(reports)).returncode, 1, "a malformed verdict is refused")

    result = consolidate_cli("start", str(reports))
    check_eq(result.returncode, 0, f"start succeeds: {result.stderr}")
    scratch = reports / "_scratch"
    check(not list(reports.glob("*.findings.json")) and len(list((scratch / "previous").glob("*.json"))) == 5
          and not (scratch / "phase1").exists() and not (scratch / "refutations").exists()
          and not (scratch / "refute-queue.json").exists(), "start clears the previous run")
    canned_duplicates(reports)
    broken = json.loads((reports / "numbers.findings.json").read_text(encoding="utf-8"))
    broken["findings"][0].pop("evidence")
    write_json(reports / "numbers.findings.json", broken)
    check_eq(consolidate_cli("consolidate", str(reports)).returncode, 1, "an invalid lens file stops consolidation")
    result = consolidate_cli("consolidate", str(reports), "--set-aside-invalid")
    check(result.returncode == 0 and "Set aside as invalid: numbers.findings.json" in result.stdout
          and (scratch / "rejected" / "numbers.findings.json").is_file(),
          f"--set-aside-invalid moves the rejected file aside and goes on: {result.stdout} {result.stderr}")
    check("merged duplicate" not in (reports / "provenance.findings.json").read_text(encoding="utf-8"),
          "the set-aside lens takes no part in the merge")
    return "3 duplicates merged, 1 cross-link, 7 queued, refuted -> Question, start and set-aside"


CASES: list[tuple[str, Callable[[Path], str]]] = [
    ("Template pipeline found", case_template_pipeline),
    ("Exclusions at any depth", case_exclusions),
    ("Unchanged inputs reuse", case_reuse),
    ("Failure, timeout, Stata", case_failure_timeout_stata),
    ("Invalid findings refused", case_rejects_invalid),
    ("Golden, byte-identical", case_golden_and_deterministic),
    ("Values escaped", case_escaping),
    ("IDs survive a line shift", case_ids_survive_line_shift),
    ("Duplicates consolidate", case_consolidation),
]


def main() -> int:
    started = time.monotonic()
    failures = 0
    with tempfile.TemporaryDirectory(prefix="review-fleet-test-") as tmp:
        for index, (name, func) in enumerate(CASES, start=1):
            work = Path(tmp) / f"case{index:02d}"
            work.mkdir()
            try:
                note = func(work)
            except Exception as exc:  # one failing case never stops the rest
                failures += 1
                print(f"FAIL {name}\n  " + (str(exc) if isinstance(exc, CaseFailure)
                                            else traceback.format_exc().rstrip()))
                continue
            print(f"PASS {name}" + (f"  [{note}]" if note else ""))
    print(f"{len(CASES)} cases, {failures} failure(s), {time.monotonic() - started:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
