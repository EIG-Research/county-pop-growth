#!/usr/bin/env python3
"""Test suite for the review-fleet evaluation: the planted-defect fixture and the scorer.

`python3 Infrastructure/scripts/test_review_eval.py` from anywhere. One `PASS` line per case:

     1  Fixture builds              every patch applies to the current worked example, each
                                    lens has at least three mechanical defects, each family is
                                    in the findings schema for its lens, and every anchor occurs
                                    exactly once; the control is the unpatched example
     2  Stale patch fails           a changed line under a defect patch stops the build and
                                    names the patch (how drift in the worked example shows)
     3  Perfect run scores          canned, schema-valid findings that hit every defect score
                                    recall 1, severity agreement 1, no false positives
     4  Imperfect runs score        misses, a duplicate, a false positive, a decoy hit, a
                                    consequence, a line-only match, and a Question are counted,
                                    and min and mean are taken across runs
     5  Matching is strict          the reviewer's repro: a DN-VALUE finding quoting another
                                    note line earns no credit; anchor text outranks line
                                    proximity, prose needs the exact line, a decoy outranks a
                                    wrong family, wrong families and key-citing findings are
                                    counted, a missing lens scores 0, and lens-level matching
     6  Older HTML reports import   a template-style report is read into findings and scored
                                    by location, its lens standing in for the family
     7  Live run is gated           without --confirm the plan prints and nothing is built;
                                    under CI it refuses even with --confirm
     8  Fixture numbers trace       the fixture's pipeline reproduces every number its note
                                    traces (needs R; SKIP without it, a failure under REQUIRE_R=1)
     9  Collect clears the reports  each run's reports move out and review-reports/ is emptied
                                    except pipeline-run.json, so no scratch reaches the next run
    10  Example gate                on synthetic trees: the template always builds the fixture;
                                    a project does only while its worked example is intact

Cases 1-6 and 8 need the worked example. In the template (`Infrastructure/.template-identity`
present) they always run, so drift in a patch fails here. In a project they pass as
"not applicable" once it replaces the worked example (`build_fixture.not_applicable`).

Every case works in its own temporary directory, with no network and no model.
Exit codes: 0 pass, 1 fail.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent.parent
EVAL_DIR = REPO / "Infrastructure" / "evals" / "review-fleet"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(EVAL_DIR))

import build_fixture as bf  # noqa: E402
import render_review_report as rr  # noqa: E402
import review_eval as ev  # noqa: E402
from localapp.testkit import CaseFailure, check, check_eq  # noqa: E402

R_PACKAGES = ("dplyr", "readr", "here", "arrow", "fixest", "ggplot2", "systemfonts", "ragg")


class Skip(Exception):
    pass


_BUILT: dict[str, Path] = {}


def built(work: Path) -> Path:
    """Build once per suite run into the first case's directory, and reuse it."""
    if "dir" not in _BUILT:
        out = work / "build"
        bf.build(out)
        _BUILT["dir"] = out
    return _BUILT["dir"]


def anchors(build: Path) -> dict:
    return json.loads((build / "anchors.json").read_text(encoding="utf-8"))


def perfect_doc(lens: str, entries: dict) -> dict:
    findings = []
    for d in entries.values():
        if d["lens"] != lens:
            continue
        loc = d["locations"][0]
        finding = {
            "check_id": d["family"], "title": d["summary"][:80], "severity": d["severity"],
            "confidence": "high", "file": loc["file"], "line": loc["line"],
            "evidence": {"claim": d["summary"], "found": "Canned finding.",
                         "quote": loc["anchor"], "verified_by": "the quoted lines"},
        }
        if d["severity"] in ("HIGH", "CRITICAL"):
            finding["refutation"] = "Canned refutation."
        findings.append(finding)
    return {"schema_version": 1, "lens": lens, "target": "fixture", "review_date": "2026-09-29",
            "files_reviewed": sorted({f["file"] for f in findings}), "findings": findings}


def write_run(folder: Path, docs: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (folder / f"{doc['lens'].lower()}.findings.json").write_text(json.dumps(doc), encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------- cases
def case_fixture_builds(work: Path) -> str:
    build = built(work)
    key = anchors(build)
    schema = rr.load_schema()
    per_lens: dict[str, int] = {}
    for did, d in key["defects"].items():
        allowed = [b["const"] for b in schema["$defs"][f"check_ids_{d['lens']}"]["oneOf"]]
        check(d["family"] in allowed, f"{did}: family {d['family']} is not a {d['lens']} check id")
        for other in d.get("also") or []:
            check(any(other in [b["const"] for b in schema["$defs"][f"check_ids_{l}"]["oneOf"]]
                      for l in ev.LENSES), f"{did}: `also` family {other} is not in the schema")
        check(d["locations"] and all(loc["line"] >= 1 for loc in d["locations"]), f"{did}: located")
        if not d["owner_judgment"]:
            per_lens[d["lens"]] = per_lens.get(d["lens"], 0) + 1
    check_eq(sorted(per_lens), sorted(ev.LENSES), "every lens has planted defects")
    check(min(per_lens.values()) >= 3, f"at least three mechanical defects per lens: {per_lens}")
    check(key["decoys"] and key["control"], "decoys and the control are keyed")
    example = build / bf.PATCHED_DIR / "data" / "example"
    check('"S20"' in (example / "state_fips.csv").read_text(encoding="utf-8")
          and '"20",' not in (example / "min_wage.csv").read_text(encoding="utf-8"),
          "ce-04 bites on its own: state 20 has workers but no minimum wage, whatever ce-02 does")
    widths = [len(l) for l in (build / bf.PATCHED_DIR / "drafts" / "example_note.md")
              .read_text(encoding="utf-8").splitlines() if not l.startswith("|")]
    check(max(widths) <= 92, f"the planted note keeps the note's wrap (widest line {max(widths)})")
    for rel in ("code/02_analysis.R", "drafts/example_note.md"):
        check((build / bf.CONTROL_DIR / rel).read_bytes() == (REPO / rel).read_bytes(),
              f"the control's {rel} is the unpatched example")
    result = subprocess.run([sys.executable, str(EVAL_DIR / "build_fixture.py"), "check"],
                            capture_output=True, text=True, timeout=120)
    check(result.returncode == 0, f"build_fixture.py check passes: {result.stderr}")
    return ", ".join(f"{k} {v}" for k, v in sorted(per_lens.items())) + " mechanical"


def case_stale_patch(work: Path) -> str:
    patches = bf.patches()
    victim = EVAL_DIR / "defects" / "ce-03-many-to-many-join.patch"
    before = patches[:patches.index(victim)]
    for label, drift in (("unchanged", False), ("drifted", True)):
        tree = work / label
        bf.copy_example(tree)
        for patch in before:
            bf.apply_patch(tree, patch)
        target = tree / "code" / "04_min_wage.R"
        text = target.read_text(encoding="utf-8")
        old = 'relationship = "many-to-one"\n  )'
        check_eq(text.count(old), 1, "the line the drift changes is present")
        if drift:
            target.write_text(text.replace(old, 'relationship = "one-to-one"\n  )'), encoding="utf-8", newline="\n")
        try:
            bf.apply_patch(tree, victim)
        except bf.FixtureError as exc:
            check(drift, f"the patch applies to the unchanged example: {exc}")
            check(victim.name in str(exc) and "refresh" in str(exc), f"the error names the patch: {exc}")
            continue
        check(not drift, "a patch applied over a changed line")
    # A line added above a hunk only shifts it.
    tree = work / "shifted"
    bf.copy_example(tree)
    target = tree / "code" / "02_analysis.R"
    target.write_text("# an unrelated first line\n" + target.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    for patch in patches:
        bf.apply_patch(tree, patch)
    return "a changed line fails and names the patch; a shifted one applies"


def case_perfect_run(work: Path) -> str:
    build = built(work)
    key = anchors(build)
    schema = rr.load_schema()
    docs = [perfect_doc(lens, key["defects"]) for lens in ev.LENSES]
    for doc in docs:
        check_eq(rr.validate(doc, schema, schema), [], f"canned {doc['lens']} findings are schema-valid")
    write_run(work / "runs" / "run-1", docs)
    result = ev.score(build, work / "runs")
    for lens, m in result["per_lens"].items():
        check_eq((m["recall"]["min"], m["severity_agreement"]["min"], m["high_conf_fp"]["mean"],
                  m["decoy_high_conf"]["mean"], m["duplicate_rate"]["mean"]), (1.0, 1.0, 0, 0, 0.0),
                 f"{lens}: a perfect run")
    check_eq(result["per_lens"]["MR"]["owner_recall"]["min"], 1.0, "owner-judgment defects scored apart")
    return "recall 1.0 in every lens"


def case_imperfect_runs(work: Path) -> str:
    build = built(work)
    key = anchors(build)
    ce = perfect_doc("CE", key["defects"])
    run1 = copy.deepcopy(ce)
    missed = run1["findings"].pop(0)                       # one miss
    dup = copy.deepcopy(run1["findings"][0])
    dup["title"] = "Same defect again"
    run1["findings"].append(dup)                           # one duplicate
    run1["findings"][1]["severity"] = "LOW"                 # one severity disagreement
    run1["findings"][1].pop("refutation", None)
    run1["findings"].append({                              # one high-confidence false positive
        "check_id": "CE-LOGIC", "title": "Invented", "severity": "MEDIUM", "confidence": "high",
        "file": "code/03_make_figures.R", "line": 12,
        "evidence": {"claim": "x", "found": "y", "quote": "library(ggplot2)", "verified_by": "z"}})
    run1["findings"].append({                              # medium confidence: not counted as FP
        "check_id": "CE-LOGIC", "title": "Unsure", "severity": "MEDIUM", "confidence": "medium",
        "file": "code/03_make_figures.R", "line": 20,
        "evidence": {"claim": "x", "found": "y", "quote": "library(readr)", "verified_by": "z"}})
    decoy = key["decoys"]["03-explicit-vcov"]["locations"][0]
    run1["findings"].append({                              # decoy hit, high confidence
        "check_id": "CE-LOGIC", "title": "Not clustered", "severity": "LOW", "confidence": "high",
        "file": decoy["file"], "line": decoy["line"],
        "evidence": {"claim": "x", "found": "y", "quote": decoy["anchor"], "verified_by": "z"}})
    other = key["defects"]["dn-01-note-vs-table"]["locations"][0]
    run1["findings"].append({                              # another lens's defect, wrong family
        "check_id": "CE-LOGIC", "title": "Other lens", "severity": "LOW", "confidence": "high",
        "file": other["file"], "line": other["line"],
        "evidence": {"claim": "x", "found": "y", "quote": other["anchor"], "verified_by": "z"}})
    conseq = key["defects"]["ce-01-na-rm-missing-ages"]["locations"][1]
    cc_doc = {"schema_version": 1, "lens": "CC", "target": "fixture", "review_date": "2026-09-29",
              "files_reviewed": [conseq["file"]], "findings": [{   # a consequence via `also`
                  "check_id": "CC-SAMPLE", "title": "Not all 500 have an age", "severity": "MEDIUM",
                  "confidence": "high", "file": conseq["file"], "line": conseq["line"],
                  "evidence": {"claim": "x", "found": "y", "quote": conseq["anchor"], "verified_by": "z"}}]}
    run1["findings"].append({                              # a Question
        "check_id": "CE-SEED", "title": "Seed?", "severity": "QUESTION", "confidence": "low",
        "file": "code/02_analysis.R",
        "evidence": {"claim": "x", "found": "y", "verified_by": "z", "looked_in": ["code/02_analysis.R"]}})
    line_only = copy.deepcopy(missed)                      # run 2 finds the miss by line only
    line_only["line"] += 2
    line_only["evidence"]["quote"] = "a paraphrase, not the anchor"
    run2 = copy.deepcopy(ce)
    run2["findings"][0] = line_only
    schema = rr.load_schema()
    for doc in (run1, run2, cc_doc):
        check_eq(rr.validate(doc, schema, schema), [], "canned findings are schema-valid")
    write_run(work / "runs" / "run-1", [run1, cc_doc])
    write_run(work / "runs" / "run-2", [run2])
    result = ev.score(build, work / "runs")
    m = result["per_lens"]["CE"]
    per = result["per_run"]
    check_eq((per["run-1"]["CC"]["high_conf_fp"], per["run-1"]["CC"]["findings"][0]["kind"]),
             (0, "consequence"), "an `also` family at a defect's spot is a consequence, not a false positive")
    check_eq([f["kind"] for f in per["run-1"]["CE"]["findings"] if f["title"] == "Other lens"],
             ["wrong_family"], "another lens's defect under the wrong family is classed wrong_family")
    check_eq(per["run-1"]["CE"]["recall"], 0.75, "run 1 misses one of four")
    check_eq(per["run-2"]["CE"]["recall"], 1.0, "run 2 finds it by line within tolerance")
    check_eq((m["recall"]["min"], m["recall"]["mean"]), (0.75, 0.875), "min and mean across runs")
    check_eq(per["run-1"]["CE"]["high_conf_fp"], 2,
             "an invented finding and a confident wrong-family one are false positives; medium is not")
    check_eq(per["run-1"]["CE"]["decoy_high_conf"], 1, "the decoy hit is counted apart")
    check_eq(per["run-1"]["CE"]["duplicate_rate"], 0.25, "one duplicate among four hits")
    check_eq(per["run-1"]["CE"]["questions"], 1, "the Question is counted, not scored")
    check_eq(per["run-1"]["CE"]["severity_agreement"], round(2 / 3, 4), "one of three hit severities disagrees")
    check_eq(per["run-1"]["CE"]["missed"], [missed_id(key, missed)], "the miss is named")
    check_eq(m["targets"]["recall_min"], False, "recall below 0.8 in one run fails the target")
    check_eq(m["targets"]["decoys"], False, "a decoy hit fails its target")

    control = work / "control-runs" / "run-1"
    control.mkdir(parents=True)
    cloc = key["control"]["control-disclosed-small-clusters"]["locations"][0]
    (control / "mr.findings.json").write_text(json.dumps({
        "schema_version": 1, "lens": "MR", "target": "control", "review_date": "2026-09-29",
        "files_reviewed": [cloc["file"]], "findings": [{
            "check_id": "MR-INFERENCE", "title": "Few clusters", "severity": "HIGH", "confidence": "high",
            "file": cloc["file"], "line": cloc["line"], "refutation": "r",
            "evidence": {"claim": "x", "found": "y", "quote": cloc["anchor"], "verified_by": "z"}}]}),
        encoding="utf-8", newline="\n")
    scored = ev.score(build, work / "runs", work / "control-runs")
    check_eq(scored["control"]["run-1"]["MR"], {"control_high": 1, "control_over_max": 1},
             "a HIGH on the disclosed clusters in the control breaks both control targets")
    return "recall min 0.75, mean 0.875; FP, decoy, duplicate, question, control"


def missed_id(key: dict, finding: dict) -> str:
    return next(i for i, d in key["defects"].items()
                if d["lens"] == "CE" and d["locations"][0]["anchor"] == finding["evidence"]["quote"])


OLD_REPORT = """<!DOCTYPE html><html><body>
<div class="finding high"><div class="finding-header"><div class="finding-id">CE-001</div>
<div class="finding-title-block"><div class="finding-title">Many-to-many join duplicates workers</div>
<div class="finding-meta"><span class="file">code/04_min_wage.R</span><span> · Line {line} · R</span></div></div>
<span class="severity-badge badge-high">HIGH</span></div>
<div class="finding-body"><div class="code-label">code/04_min_wage.R:{line}</div>
<pre><code>    by = &quot;state_fips&quot;,
    relationship = &quot;many-to-many&quot;</code></pre></div></div>
<div class="finding medium"><div class="finding-header"><div class="finding-id">CE-002</div>
<div class="finding-title-block"><div class="finding-title">Unrelated</div>
<div class="finding-meta"><span class="file">code/03_make_figures.R</span><span> · Line 5 · R</span></div></div>
<span class="severity-badge badge-medium">MEDIUM</span></div></div>
</body></html>
"""


def finding(check_id: str, file: str, line: int, quote: str, severity: str = "MEDIUM",
            confidence: str = "high") -> dict:
    return {"check_id": check_id, "title": f"{check_id} at {file}:{line}", "severity": severity,
            "confidence": confidence, "file": file, "line": line,
            "evidence": {"claim": "x", "found": "y", "quote": quote, "verified_by": "z"}}


def doc(lens: str, findings: list[dict]) -> dict:
    return {"schema_version": 1, "lens": lens, "target": "wages", "review_date": "2026-09-29",
            "files_reviewed": sorted({f["file"] for f in findings}), "findings": findings}


def case_strict_matching(work: Path) -> str:
    build = built(work)
    key = anchors(build)
    note = "drafts/example_note.md"
    dn01 = key["defects"]["dn-01-note-vs-table"]["locations"][0]
    dn02 = key["defects"]["dn-02-nobs-after-singletons"]["locations"][0]
    dn04 = key["defects"]["dn-04-log-points-as-percent"]["locations"][0]
    note_lines = (build / bf.PATCHED_DIR / note).read_text(encoding="utf-8").splitlines()
    all_anchors = [loc["anchor"] for group in ("defects", "decoys") for e in key[group].values()
                   for loc in e["locations"]]
    innocent = next(dn02["line"] + k for k in (2, -2, 3, -3, 1, -1)
                    if note_lines[dn02["line"] + k - 1].strip()
                    and not any(a in note_lines[dn02["line"] + k - 1] for a in all_anchors))
    # The reviewer's repro: DN-VALUE findings quoting the wrong note line took dn-01 and dn-02.
    wrong_quote = finding("DN-VALUE", note, dn01["line"] + 1, dn04["anchor"])
    near_line = finding("DN-VALUE", note, innocent, note_lines[innocent - 1].strip())
    # A wrong family at a decoy's anchor, also quoting a defect's anchor: the decoy wins.
    decoy = key["decoys"]["03-explicit-vcov"]["locations"][0]
    mr01 = key["defects"]["mr-01-unweighted-population-mean"]["locations"][0]
    both = finding("MR-INFERENCE", decoy["file"], decoy["line"], decoy["anchor"] + " " + mr01["anchor"])
    # A finding that cites the evaluation key is contaminated, even at the right spot.
    leaked = finding("DN-VALUE", note, dn01["line"], dn01["anchor"])
    leaked["evidence"]["verified_by"] = "matches Infrastructure/evals/review-fleet/defects.yaml"
    schema = rr.load_schema()
    dn_doc, mr_doc = doc("DN", [wrong_quote, near_line, leaked]), doc("MR", [both])
    for d in (dn_doc, mr_doc):
        check_eq(rr.validate(d, schema, schema), [], "canned findings are schema-valid")
    write_run(work / "runs" / "run-1", [dn_doc, mr_doc])
    write_run(work / "runs" / "run-2", [doc("MR", [])])
    result = ev.score(build, work / "runs")
    dn = result["per_run"]["run-1"]["DN"]
    check_eq(dn["recall"], 0.0, "no DN defect is credited to a finding quoting the wrong line")
    check_eq([(f["kind"], f["defect"]) for f in dn["findings"]],
             [("wrong_family", "dn-04-log-points-as-percent"), ("unmatched", None), ("contaminated", None)],
             "an anchor match outranks a line-only match; prose needs the exact line; the key taints")
    check_eq((dn["high_conf_fp"], dn["contaminated"]), (2, 1), "both misplaced findings are false positives")
    mr = result["per_run"]["run-1"]["MR"]
    check_eq((mr["findings"][0]["kind"], mr["decoy_high_conf"], mr["high_conf_fp"]), ("decoy", 1, 0),
             "a decoy outranks a wrong family at the same strength")
    missing = result["per_run"]["run-2"]["DN"]
    check_eq((missing["recall"], missing["missing_output"]), (0.0, True),
             "a lens with no output in a run scores recall 0 and is flagged")
    check_eq(result["per_lens"]["DN"]["missing_output_runs"], 1, "the summary counts missing runs")
    check_eq(result["per_lens"]["DN"]["targets"]["no contaminated findings"], False,
             "a contaminated finding fails its target")
    expected = ev.score(build, work / "runs", expected=["CE"])
    check(expected["per_run"]["run-1"]["CE"]["missing_output"], "an expected lens with no file is missing")

    loose = doc("CE", [finding("CE-LOGIC", mr01["file"], mr01["line"], mr01["anchor"])])
    write_run(work / "lens" / "run-1", [loose])
    family = ev.score(build, work / "lens")["per_run"]["run-1"]["CE"]
    lens = ev.score(build, work / "lens", match="lens")["per_run"]["run-1"]["CE"]
    check_eq((family["findings"][0]["kind"], lens["findings"][0]["kind"]), ("wrong_family", "wrong_family"),
             "a CE finding at an MR defect is wrong in both modes")
    own = key["defects"]["ce-03-many-to-many-join"]["locations"][0]
    write_run(work / "lens2" / "run-1", [dict(doc("CE", []), findings=[dict(
        finding("CE-LOGIC", own["file"], own["line"], own["anchor"], "HIGH"), refutation="r")])])
    strict = ev.score(build, work / "lens2")["per_run"]["run-1"]["CE"]["recall"]
    loose_recall = ev.score(build, work / "lens2", match="lens")["per_run"]["run-1"]["CE"]["recall"]
    check_eq((strict, loose_recall), (0.0, 0.25), "lens-level matching credits any family of the lens")
    return "anchor beats line; exact prose lines; decoy over wrong family; missing output; lens mode"


def case_import_html(work: Path) -> str:
    build = built(work)
    key = anchors(build)
    line = key["defects"]["ce-03-many-to-many-join"]["locations"][0]["line"]
    run = work / "runs" / "run-1"
    run.mkdir(parents=True)
    report = run / "code-error-report.html"
    report.write_text(OLD_REPORT.replace("{line}", str(line)), encoding="utf-8", newline="\n")
    found = ev.from_html(report)
    check_eq([(f["severity"], f["file"], f["line"], f["check_id"]) for f in found],
             [("HIGH", "code/04_min_wage.R", line, None), ("MEDIUM", "code/03_make_figures.R", 5, None)],
             "the older report's cards become findings")
    check('relationship = "many-to-many"' in found[0]["text"], "the quoted code survives unescaping")
    result = ev.score(build, work / "runs")
    row = result["per_run"]["run-1"]["CE"]
    check_eq((row["recall"], row["high_conf_fp"]), (0.25, 1),
             "matched by location with the lens as family; an unstated confidence counts as high")
    cli = subprocess.run([sys.executable, str(SCRIPTS / "review_eval.py"), "import-html", str(report)],
                         capture_output=True, text=True, timeout=60)
    check(cli.returncode == 0 and json.loads(cli.stdout)[0]["severity"] == "HIGH", "the CLI prints them")
    return "2 cards imported, 1 hit"


def case_gated(work: Path) -> str:
    out = work / "eval"
    env = {k: v for k, v in os.environ.items() if k != "CI"}
    result = subprocess.run([sys.executable, str(SCRIPTS / "review_eval.py"), "run", "--out", str(out)],
                            capture_output=True, text=True, timeout=60, env=env)
    check_eq(result.returncode, 3, f"unconfirmed exits 3: {result.stderr}")
    check("agent runs    20" in result.stdout and "CONFIRM=1" in result.stdout, "the plan is printed")
    check(not out.exists(), "nothing is built without confirmation")
    result = subprocess.run([sys.executable, str(SCRIPTS / "review_eval.py"), "run", "--out", str(out),
                             "--confirm"], capture_output=True, text=True, timeout=60,
                            env={**env, "CI": "true"})
    check(result.returncode == 2 and "never runs in CI" in result.stderr, "CI refuses even with --confirm")
    check(not out.exists(), "nothing is built under CI")
    default = subprocess.run([sys.executable, str(SCRIPTS / "review_eval.py"), "run"],
                             capture_output=True, text=True, timeout=60, env=env).stdout
    out_line = next(l for l in default.splitlines() if l.strip().startswith("output"))
    check(str(REPO) not in out_line and tempfile.gettempdir() in out_line,
          f"the default output is outside the repository: {out_line}")
    check("evaluation" not in ev.PROMPT.lower() and "evaluation" not in bf.PROJECT_MD.lower(),
          "neither the prompt nor the project's PROJECT.md says it is an evaluation")
    if shutil.which("make"):
        for value, wanted in (("0", False), ("yes", False), ("", False), ("1", True)):
            dry = subprocess.run(["make", "-n", "review-eval", f"CONFIRM={value}"], cwd=REPO,
                                 capture_output=True, text=True, timeout=60).stdout
            check(("--confirm" in dry) == wanted, f"make review-eval CONFIRM={value!r}: {dry.strip()}")
    runner = (SCRIPTS / "run_maintenance_checks.py").read_text(encoding="utf-8")
    check("review_eval.py run" not in runner, "the maintenance registry never runs the live evaluation")
    return "plan printed; exit 3 unconfirmed; exit 2 under CI"


NOTE_ROW = re.compile(r"^\| (?P<claim>[^|]+?) \| `(?P<file>output/tables/[^`]+)` \|", re.MULTILINE)
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def case_fixture_numbers(work: Path) -> str:
    rscript = shutil.which("Rscript")
    if rscript is None:
        raise Skip("Rscript not found")
    probe = "cat(all(vapply(c({}), requireNamespace, logical(1L), quietly = TRUE)))".format(
        ", ".join(f'"{p}"' for p in R_PACKAGES))
    ok = subprocess.run([rscript, "-e", probe], capture_output=True, text=True, timeout=120).stdout.strip()
    if ok != "TRUE":
        raise Skip("an R package the example needs is missing")
    fixture = built(work) / bf.PATCHED_DIR
    run = subprocess.run([rscript, "code/run_all.R"], cwd=fixture, capture_output=True, text=True, timeout=300)
    check_eq(run.returncode, 0, f"the fixture pipeline runs: {run.stderr[-2000:]}")
    note = (fixture / "drafts" / "example_note.md").read_text(encoding="utf-8")
    checked = 0
    for match in NOTE_ROW.finditer(note):
        claim = match.group("claim").split(";")[0]
        with open(fixture / match.group("file"), newline="", encoding="utf-8") as handle:
            cells = {float(c) for row in csv.reader(handle) for c in row if NUMBER.fullmatch(c.strip())}
        for token in NUMBER.findall(claim):
            value = float(token.replace(",", ""))
            check(any(abs(value - c) < 1e-9 for c in cells),
                  f"{token} in the trace row {claim!r} is not in {match.group('file')}")
            checked += 1
    check(checked >= 12, f"the trace table was read ({checked} numbers)")
    return f"{checked} traced numbers reproduce"


def case_example_gate(work: Path) -> str:
    def tree(name: str, template: bool) -> Path:
        root = work / name
        for rel in bf.COPIED:
            (root / rel).mkdir(parents=True)
        for rel in bf.MARKED:
            (root / rel).write_text(f"# {rel} -- {bf.EXAMPLE_MARKER}. A worked example\n",
                                    encoding="utf-8", newline="\n")
        if template:
            (root / bf.TEMPLATE_IDENTITY).write_text("marker\n", encoding="utf-8", newline="\n")
        return root

    for template in (True, False):
        root = tree(f"intact-{template}", template)
        check_eq((bf.example_gone(root), bf.not_applicable(root)), (None, None),
                 f"an intact example applies (template={template})")
        replaced = tree(f"replaced-{template}", template)
        (replaced / "code" / "01_build_dataset.R").write_text("# 01_build_dataset -- the project's own\n",
                                                              encoding="utf-8", newline="\n")
        removed = tree(f"removed-{template}", template)
        (removed / "drafts" / "example_note.md").unlink()
        for root, file in ((replaced, "code/01_build_dataset.R"), (removed, "drafts/example_note.md")):
            gone = bf.example_gone(root)
            check(gone is not None and file in gone, f"{file} is named: {gone}")
            reason = bf.not_applicable(root)
            if template:
                check_eq(reason, None, "the template never reports the fixture as not applicable")
            else:
                check(reason is not None and file in reason, f"a project reports why: {reason}")
    check_eq(bf.is_template(), (REPO / bf.TEMPLATE_IDENTITY).is_file(), "this repository is classed")
    return "template always applies; a project, only with its example intact"


def case_collect_clears(work: Path) -> str:
    """W3 review: collect() moved top-level files only, so `_scratch/` (phase-1 copies, the
    refutation queue) from one run was still there for the next."""
    target = work / "project"
    reports = target / "review-reports"

    def plant(tag: str) -> None:
        for rel in ("code.findings.json", "code-error-report.html", "index.html",
                    "_scratch/phase1/code.findings.json", "_scratch/refute-queue.json",
                    "_scratch/ai-skeptic-tests/probe.py", "notes.txt"):
            (reports / rel).parent.mkdir(parents=True, exist_ok=True)
            (reports / rel).write_text(f"{tag}\n", encoding="utf-8", newline="\n")

    (reports).mkdir(parents=True)
    (reports / "pipeline-run.json").write_text('{"exit_code": 0}\n', encoding="utf-8", newline="\n")
    plant("run-1")
    ev.collect(target, work / "runs" / "run-1")
    check_eq(sorted(p.name for p in (work / "runs" / "run-1").iterdir()),
             ["code-error-report.html", "code.findings.json", "index.html"], "the run's reports are collected")
    check_eq(sorted(p.name for p in reports.iterdir()), ["pipeline-run.json"],
             "review-reports/ keeps only the pipeline record after a collect")
    plant("run-2")
    ev.collect(target, work / "runs" / "run-2")
    collected = (work / "runs" / "run-2" / "code.findings.json").read_text(encoding="utf-8")
    check_eq(collected, "run-2\n", "the second run collects its own findings")
    check_eq(sorted(p.name for p in reports.iterdir()), ["pipeline-run.json"], "and is cleared again")
    return "reports collected; _scratch/ and strays cleared; pipeline-run.json kept"


CASES: list[tuple[str, Callable[[Path], str]]] = [
    ("Fixture builds", case_fixture_builds),
    ("Stale patch fails", case_stale_patch),
    ("Perfect run scores", case_perfect_run),
    ("Imperfect runs score", case_imperfect_runs),
    ("Matching is strict", case_strict_matching),
    ("Older HTML reports import", case_import_html),
    ("Live run is gated", case_gated),
    ("Fixture numbers trace", case_fixture_numbers),
    ("Collect clears the reports", case_collect_clears),
    ("Example gate", case_example_gate),
]
NEEDS_EXAMPLE = {case_fixture_builds, case_stale_patch, case_perfect_run, case_imperfect_runs,
                 case_strict_matching, case_import_html, case_fixture_numbers}


def main() -> int:
    started = time.monotonic()
    failures = 0
    not_applicable = bf.not_applicable()
    with tempfile.TemporaryDirectory(prefix="review-eval-test-") as tmp:
        for index, (name, func) in enumerate(CASES, start=1):
            work = Path(tmp) / f"case{index:02d}"
            work.mkdir()
            if not_applicable is not None and func in NEEDS_EXAMPLE:
                print(f"PASS {name}  [not applicable: {not_applicable}]")
                continue
            try:
                note = func(work)
            except Skip as exc:
                if os.environ.get("REQUIRE_R") == "1":
                    failures += 1
                    print(f"FAIL {name}\n  REQUIRE_R=1, but {exc}")
                else:
                    print(f"SKIP {name}  [{exc}]")
                continue
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
