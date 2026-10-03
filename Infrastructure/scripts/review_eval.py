#!/usr/bin/env python3
"""Score the review lenses against the planted-defect fixture, and run the live evaluation.

    score --build DIR --runs DIR [--control-runs DIR] [--match family|lens] [--out FILE]
        Score every run under `--runs` (one subdirectory per run, holding `*.findings.json`
        files or the older HTML reports) against DIR/anchors.json, which
        `Infrastructure/evals/review-fleet/build_fixture.py build DIR` writes. `--control-runs`
        holds runs on the unpatched example. Prints the JSON summary.
    import-html REPORT [--lens LENS]
        Print the findings an older HTML report holds (the report templates before the
        findings schema), in the scorer's normalized form, so a baseline can be scored.
    run [--out DIR] [--runs N] [--control-runs N] [--lenses CE,MR,...] [--agent-cmd CMD]
        [--match family|lens] [--confirm]
        The live evaluation: build the projects, run each lens's workflow N times on the
        patched one (and on the control), then score. It spawns reviewer agents repeatedly, so
        without `--confirm` it prints the plan and exits 3, and it refuses to run when `CI` is
        set. `make review-eval` calls it; `make review-eval CONFIRM=1` confirms. The default
        output directory is under the system temporary directory, outside the repository.

Matching. A finding is at a location when its file is the location's file and either the
location's anchor text appears in the finding's quote, claim, found, or title (whitespace
collapsed), which is the strong match, or its line matches, which is the weak one: within
LINE_TOLERANCE lines for code, the exact line for prose (PROSE_SUFFIXES), where one line holds
several sentences. Strength is ranked first across every defect and decoy, so an anchor quoted
anywhere beats a nearby line. Among the entries at the best strength: a hit (the defect's
family), then a consequence (one of its `also` families; neither credit nor false positive),
then a decoy, then a wrong family. With `--match lens` check ids are ignored and the finding's
lens stands in for its family, which is how an older HTML report (no check id) is always
matched; a baseline comparison uses lens-level matching on both sides. A finding that cites
the evaluation's key (CONTAMINATION_MARKERS) is `contaminated`: never credited, and flagged.

Metrics, per lens and run, then the minimum and mean across runs:
  recall                   mechanical defects of the lens hit at least once / defects
  owner_recall             the same for owner-judgment defects, scored apart
  severity_agreement       hit defects whose first hit has the expected severity / hits
  high_conf_fp             high-confidence findings (or findings with no stated confidence)
                           that match nothing or match a defect under a wrong family
  decoy_high_conf          high-confidence findings at a decoy location, any severity
  duplicate_rate           hits beyond the first per defect / all hits
  questions                QUESTION items
  contaminated             findings that cite the key
A lens expected in a run that wrote nothing scores recall 0 with `missing_output: true`.
Per control run, `control_high` counts high-confidence HIGH or CRITICAL findings and
`control_over_max` findings at a control location above its `max_severity`.
Targets (companion plan O12) are reported beside the numbers; duplicates are informational
until full-review consolidates.

Exit codes: 0 done; 1 a scoring input is unusable; 2 usage error or refused under CI;
3 the live run was not confirmed. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from statistics import mean

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[1]
EVAL_DIR = REPO / "Infrastructure" / "evals" / "review-fleet"
LINE_TOLERANCE = 3
PROSE_SUFFIXES = (".md", ".qmd", ".rmd", ".tex")
CONTAMINATION_MARKERS = ("defects.yaml", "anchors.json", "evals/review-fleet", "scaffold.patch",
                         "decoys/", "defects/")
SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "SUGGESTION": 0, "QUESTION": -1}
LENS_OF_REPORT = {
    "code-error-report.html": "CE", "methodology-report.html": "MR",
    "doc-number-report.html": "DN", "doc-consistency-report.html": "CC",
    "ai-skeptic-report.html": "AS",
}
WORKFLOW_OF_LENS = {"CE": "review-code", "MR": "review-methodology", "DN": "review-numbers",
                    "CC": "review-consistency", "AS": "review-ai"}
LENSES = tuple(WORKFLOW_OF_LENS)
TARGETS = {"recall_min": 0.8, "decoy_high_conf_max": 0, "control_high_max": 0,
           "duplicate_rate_max": 0.10}
DEFAULT_AGENT_CMD = "claude -p {prompt} --add-dir {target}"
PROMPT = ("Run the {workflow} workflow on {target}. Run it non-interactively: review every "
          "discovered document, skip the optional context questions, do not wait for input, and "
          "write the report to {target}/review-reports/.")
RUN_TIMEOUT = 1800  # seconds per agent run


class ScoreError(Exception):
    pass


def norm(text: str) -> str:
    return " ".join(str(text).split())


def norm_path(path: str) -> str:
    return str(path).strip().removeprefix("./")


# --------------------------------------------------------------------------- findings in
def from_json(doc: dict) -> list[dict]:
    """Normalized findings from one findings file."""
    out = []
    for f in doc.get("findings", []):
        ev = f.get("evidence", {})
        text = " ".join(str(ev.get(k, "")) for k in ("quote", "claim", "found")) + " " + f.get("title", "")
        out.append({"lens": doc["lens"], "check_id": f.get("check_id"), "severity": f.get("severity"),
                    "confidence": f.get("confidence", "unstated"), "file": norm_path(f.get("file", "")),
                    "line": f.get("line"), "locations": [(norm_path(f.get("file", "")), f.get("line"))],
                    "text": norm(text), "all_text": json.dumps(f), "title": f.get("title", "")})
    return out


class _Tree(HTMLParser):
    """A minimal element tree: (tag, classes, children, text parts)."""

    VOID = {"br", "hr", "img", "input", "meta", "link", "col", "area", "base", "wbr", "source"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "root", "cls": [], "kids": [], "text": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "cls": (dict(attrs).get("class") or "").split(), "kids": [], "text": []}
        self.stack[-1]["kids"].append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth]["tag"] == tag:
                del self.stack[depth:]
                return

    def handle_data(self, data):
        self.stack[-1]["kids"].append(data)


def _text(node) -> str:
    return node if isinstance(node, str) else " ".join(_text(k) for k in node["kids"])


def _all(node, pred):
    if isinstance(node, str):
        return
    if pred(node):
        yield node
    for kid in node["kids"]:
        yield from _all(kid, pred)


LOC_RE = re.compile(r"([\w./-]+\.(?:R|r|py|do|ado|qmd|Rmd|md|tex|csv)):(\d+)")


def from_html(path: Path, lens: str | None = None) -> list[dict]:
    """Normalized findings from an older template-based report (no check id, no confidence)."""
    lens = lens or LENS_OF_REPORT.get(path.name)
    if lens is None:
        raise ScoreError(f"{path.name}: cannot tell its lens; pass --lens")
    tree = _Tree()
    tree.feed(path.read_text(encoding="utf-8", errors="replace"))
    out = []
    for card in _all(tree.root, lambda n: n["tag"] in ("div", "article") and "finding" in n["cls"]):
        def first(cls: str) -> str:
            hit = next(_all(card, lambda n: cls in n["cls"]), None)
            return norm(_text(hit)) if hit else ""
        badge = first("severity-badge").upper()
        severity = next((s for s in SEVERITY_RANK if s in badge), "MEDIUM")
        file = norm_path(first("file"))
        whole = norm(_text(card))
        locations = [(norm_path(m.group(1)), int(m.group(2))) for m in LOC_RE.finditer(whole)]
        line_match = re.search(r"Line (\d+)", whole)
        line = int(line_match.group(1)) if line_match else None
        if file:
            locations.insert(0, (file, line))
        out.append({"lens": lens, "check_id": None, "severity": severity, "confidence": "unstated",
                    "file": file, "line": line, "locations": locations, "text": whole,
                    "title": first("finding-title")})
    return out


def load_run(folder: Path) -> dict[str, list[dict]]:
    """Findings per lens in one run directory: findings JSON wins over an HTML report."""
    by_lens: dict[str, list[dict]] = {}
    for path in sorted(folder.glob("*.findings.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        by_lens[doc["lens"]] = from_json(doc)
    for path in sorted(folder.glob("*.html")):
        lens = LENS_OF_REPORT.get(path.name)
        if lens and lens not in by_lens:
            by_lens[lens] = from_html(path, lens)
    return by_lens


# --------------------------------------------------------------------------- matching
def line_close(path: str, line: int, anchor_line: int) -> bool:
    """Code tolerates a nearby line; prose needs the exact line, since its lines are sentences."""
    if Path(path).suffix.lower() in PROSE_SUFFIXES:
        return line == anchor_line
    return abs(line - anchor_line) <= LINE_TOLERANCE


def match_strength(finding: dict, entry: dict) -> int:
    """2 when a location's anchor text is in the finding, 1 when only its line matches, else 0."""
    best = 0
    for loc in entry["locations"]:
        target = loc["file"]
        for file, line in finding["locations"]:
            if not file or not (file == target or file.endswith("/" + target)):
                continue
            if norm(loc["anchor"]) in finding["text"]:
                return 2
            if line is not None and line_close(target, int(line), loc["line"]):
                best = 1
    return best


def at_location(finding: dict, loc: dict) -> bool:
    return match_strength(finding, {"locations": [loc]}) > 0


def contaminated(finding: dict) -> bool:
    """A finding that cites the evaluation's own key saw the answers."""
    where = " ".join([finding.get("all_text", finding["text"]), *(str(f) for f, _ in finding["locations"])])
    return any(marker in where for marker in CONTAMINATION_MARKERS)


def classify(finding: dict, anchors: dict) -> tuple[str, str | None]:
    """('contaminated' | 'hit' | 'consequence' | 'decoy' | 'wrong_family' | 'unmatched', entry id).

    Location strength is ranked first, across every defect and decoy: an anchor-text match
    anywhere beats a line-only match anywhere. Among the entries at the best strength, a hit
    (the defect's family, or its lens when the finding has no family) beats a consequence (an
    `also` family), which beats a decoy, which beats a wrong family.
    """
    if contaminated(finding):
        return "contaminated", None
    family, lens = finding["check_id"], finding["lens"]
    scored = [("defect", did, d, match_strength(finding, d)) for did, d in anchors["defects"].items()]
    scored += [("decoy", did, d, match_strength(finding, d)) for did, d in anchors["decoys"].items()]
    best = max((s for *_, s in scored), default=0)
    if not best:
        return "unmatched", None
    top = [(group, did, d) for group, did, d, s in scored if s == best]

    def kind_of(group: str, d: dict) -> str:
        if group == "decoy":
            return "decoy"
        also = d.get("also") or []
        if family is None:  # lens-level matching: the finding's lens stands in for its family
            if lens == d["lens"]:
                return "hit"
            return "consequence" if any(a.startswith(lens + "-") for a in also) else "wrong_family"
        if family == d["family"]:
            return "hit"
        return "consequence" if family in also else "wrong_family"

    kinds = [(kind_of(group, d), did) for group, did, d in top]
    for wanted in ("hit", "consequence", "decoy", "wrong_family"):
        for kind, did in kinds:
            if kind == wanted:
                return kind, did
    return "unmatched", None


def confident(f: dict) -> bool:
    return f["confidence"] in ("high", "unstated")


def score_lens(lens: str, findings: list[dict], anchors: dict) -> dict:
    own = {i: d for i, d in anchors["defects"].items() if d["lens"] == lens}
    mechanical = [i for i, d in own.items() if not d["owner_judgment"]]
    owner = [i for i, d in own.items() if d["owner_judgment"]]
    hits: dict[str, list[dict]] = {}
    fp = decoys = questions = tainted = 0
    detail = []
    for f in findings:
        if f["severity"] == "QUESTION":
            questions += 1
            continue
        kind, did = classify(f, anchors)
        detail.append({"title": f["title"], "kind": kind, "defect": did})
        if kind == "contaminated":
            tainted += 1
        elif kind == "hit" and did in own:
            hits.setdefault(did, []).append(f)
        elif kind == "decoy" and confident(f):
            decoys += 1
        elif kind in ("unmatched", "wrong_family") and confident(f):
            fp += 1
    agree = [SEVERITY_RANK[h[0]["severity"]] == SEVERITY_RANK[own[i]["severity"]] for i, h in hits.items()]
    total_hits = sum(len(h) for h in hits.values())
    return {
        "recall": round(sum(i in hits for i in mechanical) / len(mechanical), 4) if mechanical else None,
        "owner_recall": round(sum(i in hits for i in owner) / len(owner), 4) if owner else None,
        "severity_agreement": round(sum(agree) / len(agree), 4) if agree else None,
        "high_conf_fp": fp,
        "decoy_high_conf": decoys,
        "duplicate_rate": round((total_hits - len(hits)) / total_hits, 4) if total_hits else 0.0,
        "questions": questions,
        "contaminated": tainted,
        "missing_output": False,
        "missed": sorted(set(mechanical) - set(hits)),
        "findings": detail,
    }


def score_control(lens: str, findings: list[dict], anchors: dict) -> dict:
    high = over = 0
    for f in findings:
        if f["severity"] in ("HIGH", "CRITICAL") and confident(f):
            high += 1
        for entry in anchors.get("control", {}).values():
            if any(at_location(f, loc) for loc in entry["locations"]) \
                    and SEVERITY_RANK.get(f["severity"], -1) > SEVERITY_RANK[entry["max_severity"]]:
                over += 1
    return {"control_high": high, "control_over_max": over}


def summarize(values: list) -> dict:
    present = [v for v in values if v is not None]
    if not present:
        return {"min": None, "mean": None}
    return {"min": min(present), "mean": round(mean(present), 4)}


def lens_level(found: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Drop check ids, so a findings file is matched as loosely as an older HTML report."""
    return {lens: [dict(f, check_id=None) for f in items] for lens, items in found.items()}


def score(build: Path, runs: Path, control_runs: Path | None = None, match: str = "family",
          expected: list[str] | None = None) -> dict:
    anchors_path = build / "anchors.json"
    if not anchors_path.is_file():
        raise ScoreError(f"{anchors_path} is missing; run build_fixture.py build {build} first")
    anchors = json.loads(anchors_path.read_text(encoding="utf-8"))
    run_dirs = sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []
    if not run_dirs:
        raise ScoreError(f"no run directories under {runs}")
    loaded = {d.name: load_run(d) for d in run_dirs}
    if match == "lens":
        loaded = {name: lens_level(found) for name, found in loaded.items()}
    wanted = sorted(set(expected or []).union(*(set(f) for f in loaded.values())), key=LENSES.index)
    per_run = {}
    for name, found in loaded.items():
        per_run[name] = {}
        for lens in wanted:
            row = score_lens(lens, found.get(lens, []), anchors)
            if lens not in found:  # the lens wrote nothing in this run: it found nothing
                row["missing_output"] = True
            per_run[name][lens] = row
    control = {}
    if control_runs is not None and control_runs.is_dir():
        control = {d.name: {lens: score_control(lens, found, anchors)
                            for lens, found in load_run(d).items()}
                   for d in sorted(p for p in control_runs.iterdir() if p.is_dir())}
    per_lens = {}
    for lens in LENSES:
        rows = [r[lens] for r in per_run.values() if lens in r]
        crow = [c[lens] for c in control.values() if lens in c]
        if not rows and not crow:
            continue
        metrics = {k: summarize([r[k] for r in rows]) for k in
                   ("recall", "owner_recall", "severity_agreement", "high_conf_fp", "decoy_high_conf",
                    "duplicate_rate", "questions", "contaminated")}
        metrics["runs"] = len(rows)
        metrics["missing_output_runs"] = sum(1 for r in rows if r["missing_output"])
        if crow:
            metrics.update({k: summarize([c[k] for c in crow]) for k in ("control_high", "control_over_max")})
        recall_min = metrics["recall"]["min"]
        decoy_max = max((r["decoy_high_conf"] for r in rows), default=0)
        control_max = max((c["control_high"] for c in crow), default=None)
        metrics["targets"] = {
            "recall_min": None if recall_min is None else recall_min >= TARGETS["recall_min"],
            "decoys": decoy_max <= TARGETS["decoy_high_conf_max"],
            "no contaminated findings": sum(r["contaminated"] for r in rows) == 0,
            "control": None if control_max is None else control_max <= TARGETS["control_high_max"],
            "duplicates (informational until consolidation)":
                max((r["duplicate_rate"] for r in rows), default=0) <= TARGETS["duplicate_rate_max"],
        }
        per_lens[lens] = metrics
    return {"fixture": str(build), "match": match, "runs": [d.name for d in run_dirs],
            "control_runs": sorted(control), "per_lens": per_lens, "per_run": per_run,
            "control": control}


# --------------------------------------------------------------------------- live run
def plan_text(args, lenses: list[str]) -> str:
    agent_runs = len(lenses) * (args.runs + args.control_runs)
    return "\n".join([
        "Review-fleet evaluation plan (human-gated; never run in CI)",
        f"  commit        {git_sha()}",
        f"  output        {args.out}",
        f"  lenses        {', '.join(f'{l} ({WORKFLOW_OF_LENS[l]})' for l in lenses)}",
        f"  runs          {args.runs} on the fixture, {args.control_runs} on the unpatched control",
        f"  agent runs    {agent_runs}, each a full reviewer session with model cost, "
        f"timeout {RUN_TIMEOUT}s each",
        f"  estimate      about {agent_runs * 5} to {agent_runs * 10} minutes; past 60 minutes this is Tier 4, and the confirmation is its human approval",
        f"  agent command {args.agent_cmd}",
        "  steps         build the fixture and control; run each pipeline once (reused by the",
        "                workflows); run each lens's workflow; collect review-reports/ per run; score",
        "Check that the agent command grants the permissions a headless workflow needs.",
        "Confirm with: make review-eval CONFIRM=1  (or: review_eval.py run --confirm)",
    ])


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
                              timeout=30).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def collect(target: Path, dest: Path) -> None:
    """Move one run's reports to `dest`, then empty review-reports/ but for the pipeline
    record, so no findings, scratch (phase-1 copies, the refutation queue), or stray file
    reaches the next run."""
    reports = target / "review-reports"
    dest.mkdir(parents=True, exist_ok=True)
    if reports.is_dir():
        for path in reports.iterdir():
            if path.name == "pipeline-run.json":
                continue
            if path.is_file() and path.suffix in (".html", ".json"):
                shutil.move(str(path), dest / path.name)
            elif path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()


def live_run(args) -> int:
    lenses = [l.strip() for l in args.lenses.split(",") if l.strip()]
    unknown = [l for l in lenses if l not in WORKFLOW_OF_LENS]
    if unknown:
        print(f"review_eval.py: unknown lens {', '.join(unknown)}", file=sys.stderr)
        return 2
    print(plan_text(args, lenses))
    if os.environ.get("CI"):
        print("review_eval.py: refusing to run: CI is set, and this evaluation never runs in CI.",
              file=sys.stderr)
        return 2
    if not args.confirm:
        print("\nNot confirmed; nothing was run.")
        return 3
    sys.path.insert(0, str(EVAL_DIR))
    import build_fixture  # noqa: E402
    import review_manifest  # noqa: E402
    reason = build_fixture.not_applicable()
    if reason is not None:
        print(f"review_eval.py: the fixture does not apply here: {reason}", file=sys.stderr)
        return 1
    out = Path(args.out).resolve()
    build = out / "projects"
    build_fixture.build(build, force=True)
    patched, control = build_fixture.PATCHED_DIR, build_fixture.CONTROL_DIR
    for name in (patched, control):
        if review_manifest.run_pipeline(build / name, 900, False, False) != 0:
            print(f"review_eval.py: the {name} pipeline failed; see its review-reports/", file=sys.stderr)
            return 1
    started = time.monotonic()
    for name, count in ((patched, args.runs), (control, args.control_runs)):
        target = build / name
        for index in range(1, count + 1):
            for lens in lenses:
                prompt = PROMPT.format(workflow=WORKFLOW_OF_LENS[lens], target=target)
                command = args.agent_cmd.format(prompt=shlex.quote(prompt), target=shlex.quote(str(target)),
                                                workflow=WORKFLOW_OF_LENS[lens])
                print(f"[{name} run {index}] {lens}: {command[:120]}", flush=True)
                try:
                    subprocess.run(shlex.split(command), cwd=REPO, timeout=RUN_TIMEOUT)
                except subprocess.TimeoutExpired:
                    print(f"  timed out after {RUN_TIMEOUT}s; scoring what it wrote", flush=True)
                collect(target, out / ("runs" if name == patched else "control-runs") / f"run-{index}")
    result = score(build, out / "runs", out / "control-runs", args.match, lenses)
    result["commit"] = git_sha()
    result["finished_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result["minutes"] = round((time.monotonic() - started) / 60, 1)
    (out / "score.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result["per_lens"], indent=2))
    print(f"Wrote {out / 'score.json'}")
    return 0


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("score", help="score collected runs")
    s.add_argument("--build", required=True, help="the build_fixture.py output directory")
    s.add_argument("--runs", required=True)
    s.add_argument("--control-runs")
    s.add_argument("--out")
    s.add_argument("--match", choices=("family", "lens"), default="family",
                   help="lens: ignore check ids, as for older HTML reports (baseline comparisons)")
    i = sub.add_parser("import-html", help="print an older HTML report's findings")
    i.add_argument("report")
    i.add_argument("--lens", choices=LENSES)
    r = sub.add_parser("run", help="the live, human-gated evaluation")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    r.add_argument("--out", default=str(Path(tempfile.gettempdir()) / f"wages-{stamp}"),
                   help="outside the repository by default, so reviewers never see the key beside the project")
    r.add_argument("--match", choices=("family", "lens"), default="family")
    r.add_argument("--runs", type=int, default=3)
    r.add_argument("--control-runs", type=int, default=1)
    r.add_argument("--lenses", default=",".join(LENSES))
    r.add_argument("--agent-cmd", default=os.environ.get("REVIEW_EVAL_AGENT_CMD", DEFAULT_AGENT_CMD),
                   help="command template with {prompt}, {target}, {workflow}")
    r.add_argument("--confirm", action="store_true", help="a human approved the plan")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return live_run(args)
        if args.command == "import-html":
            print(json.dumps(from_html(Path(args.report), args.lens), indent=2))
            return 0
        result = score(Path(args.build), Path(args.runs),
                       Path(args.control_runs) if args.control_runs else None, args.match)
        text = json.dumps(result, indent=2) + "\n"
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8", newline="\n")
        sys.stdout.write(text)
        return 0
    except ScoreError as exc:
        print(f"review_eval.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
