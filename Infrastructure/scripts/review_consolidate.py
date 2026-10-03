#!/usr/bin/env python3
"""Phase 2 of `full-review`: merge duplicate findings across lenses, cross-link the rest, queue
every HIGH and CRITICAL finding for an independent refutation pass, and apply its verdicts.

    review_consolidate.py start <reports-dir>
    review_consolidate.py consolidate <reports-dir> [--set-aside-invalid]
    review_consolidate.py apply <reports-dir>

`<reports-dir>` is `<target>/review-reports/`, holding one `*.findings.json` per lens that
`render_review_report.py` accepts.

start
    Clears the previous run before phase 1: moves any `*.findings.json` to
    `_scratch/previous/` and removes the phase copies, the queue, and the verdicts, so a lens
    that does not run this time leaves no stale file behind.
consolidate
    With `--set-aside-invalid`, a lens file the schema rejects is moved to `_scratch/rejected/`
    and named in the summary instead of stopping the step (the workflow uses it only after the
    owning agent has had a chance to fix the file). It copies the lens files to
    `_scratch/phase1/` the first time (later runs start again from that copy, so the step is
    repeatable), then:
      - merges findings that share a file, an anchor, and a check family. Two findings share
        an anchor when their quotes agree (one contains the other) and, where both give lines,
        the lines overlap; without quotes, when the lines overlap; for two findings about
        something missing, the file itself. The same text quoted at two places is two findings. The family is the check id, except
        where review-contract.md section 6 gives one issue to one lens across several ids
        (FAMILIES). Two findings of one lens merge only when they also share a check id and a
        title or claim (whitespace and case aside), since one lens can report two different
        problems on one line. The owner lens's finding is kept, then the more severe, then
        the more confident; the kept finding lists the merged IDs in `related`;
      - cross-links findings of different lenses at the same anchor through `related`;
      - writes the consolidated files over the lens files, a copy to `_scratch/phase2/`, and
        `_scratch/refute-queue.json`: every HIGH and CRITICAL finding with its lens, ID, and the
        agent that owns it.
apply
    Reads the verdicts the owning agents wrote to `_scratch/refutations/*.json`
    (`{"verdicts": [{"id": ..., "verdict": "refuted" | "upheld", "reason": ...}]}`) and applies
    them to the `_scratch/phase2/` copy: a refuted finding becomes a Question for the author
    (severity QUESTION, confidence low) with the reason in `refutation`; an upheld one keeps its
    severity and gains the reason. Queued findings with no verdict are listed as not rechecked.
    Repeatable: it always starts from `_scratch/phase2/`.

Consolidate and apply validate every file they read and write against the findings schema, and IDs are
the renderer's (`render_review_report.assign_ids`), so the `related` links and the queue name
the IDs the rendered reports show. Rendering stays with `render_review_report.py`.
Exit codes: 0 done; 1 a findings or verdict file is invalid; 2 usage error. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_review_report as rr  # noqa: E402

# check id -> cross-lens family, and the lens that owns each family (review-contract.md §6):
# an undocumented filter or a mis-described universe is the consistency lens's undisclosed
# choice, and an external figure is the provenance lens's even when the numbers lens could not
# trace it. Every other check id is its own family.
FAMILIES = {"CC-UNDISCLOSED": "sample-choice", "CC-SAMPLE": "sample-choice", "MR-SAMPLE": "sample-choice",
            "AS-EXTERNAL": "external-figure", "DN-TRACE": "external-figure"}
FAMILY_OWNER = {"sample-choice": "CC", "external-figure": "AS"}
AGENT_OF_LENS = {"CE": "code-reviewer", "MR": "methodology-reviewer", "DN": "data-consistency-reviewer",
                 "CC": "conceptual-consistency-reviewer", "AS": "ai-skeptic"}
SEVERITY_RANK = {s: n for n, s in enumerate(rr.SEVERITIES)}
CONFIDENCE_RANK = {c: n for n, c in enumerate(rr.CONFIDENCES)}
SERIOUS = ("CRITICAL", "HIGH")


class Invalid(Exception):
    pass


def family(finding: dict) -> str:
    return FAMILIES.get(finding["check_id"], finding["check_id"])


def owner(finding: dict) -> str:
    return FAMILY_OWNER.get(family(finding), finding["check_id"].split("-", 1)[0])


def lines_of(finding: dict) -> tuple[int, int] | None:
    if "line" not in finding:
        return None
    return finding["line"], max(finding["line"], finding.get("end_line", finding["line"]))


def same_anchor(a: dict, b: dict) -> bool:
    if rr.normalize(a["file"]).removeprefix("./") != rr.normalize(b["file"]).removeprefix("./"):
        return False
    qa, qb = (rr.normalize(f["evidence"].get("quote", "")) for f in (a, b))
    if qa and qb and not (qa in qb or qb in qa):
        return False
    la, lb = lines_of(a), lines_of(b)
    if la and lb:  # the same text at different places is two findings, not one
        return la[0] <= lb[1] and lb[0] <= la[1]
    return bool(qa and qb) or (la is None and lb is None)


def same_finding(a: dict, b: dict) -> bool:
    """Within one lens, a repeat only: the same check id and the same title or claim.

    Across lenses one anchor in one family is one problem seen twice. One lens can hold
    two different findings on one line (two HIGH CE-LOGIC errors on line 40), and merging
    those would drop one.
    """
    def text(f: dict, key: str) -> str:
        return rr.normalize(f.get(key) or f["evidence"].get(key, "")).casefold()
    return a["check_id"] == b["check_id"] and any(
        text(a, key) and text(a, key) == text(b, key) for key in ("title", "claim"))


def load(paths: list[Path]) -> list[dict]:
    schema, docs, problems = rr.load_schema(), [], []
    for path in paths:
        try:
            doc = rr.load_findings(path, schema)
        except rr.ValidationFailed as exc:
            problems += exc.problems
            continue
        docs.append({"name": path.name, "doc": doc})
    lenses = [d["doc"]["lens"] for d in docs]
    problems += [f"more than one findings file for lens {lens}" for lens in sorted(set(lenses))
                 if lenses.count(lens) > 1]
    if problems:
        raise Invalid("\n".join(problems))
    return docs


def write(folder: Path, docs: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for entry in docs:
        (folder / entry["name"]).write_text(json.dumps(entry["doc"], indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8", newline="\n")
    load([folder / entry["name"] for entry in docs])  # what was written still validates


def add_related(finding: dict, items: list[str]) -> None:
    related = finding.setdefault("related", [])
    related += [item for item in items if item not in related]


def nodes_of(docs: list[dict]) -> list[dict]:
    nodes = []
    for d, entry in enumerate(docs):
        lens, findings = entry["doc"]["lens"], entry["doc"]["findings"]
        for i, (finding, fid) in enumerate(zip(findings, rr.assign_ids(lens, findings))):
            nodes.append({"doc": d, "index": i, "lens": lens, "id": fid, "f": finding})
    return nodes


def start(folder: Path) -> str:
    scratch = folder / "_scratch"
    for name in ("phase1", "phase2", "refutations", "rejected"):
        shutil.rmtree(scratch / name, ignore_errors=True)
    (scratch / "refute-queue.json").unlink(missing_ok=True)
    previous = sorted(folder.glob("*.findings.json"))
    if previous:
        (scratch / "previous").mkdir(parents=True, exist_ok=True)
        for path in previous:
            path.replace(scratch / "previous" / path.name)
    return (f"Ready for phase 1 in {folder}; moved {len(previous)} earlier findings file(s) to "
            f"{scratch / 'previous'}." if previous else f"Ready for phase 1 in {folder}.")


def set_aside_invalid(folder: Path) -> list[str]:
    schema, notes = rr.load_schema(), []
    for path in sorted(folder.glob("*.findings.json")):
        try:
            rr.load_findings(path, schema)
        except rr.ValidationFailed as exc:
            (folder / "_scratch" / "rejected").mkdir(parents=True, exist_ok=True)
            path.replace(folder / "_scratch" / "rejected" / path.name)
            notes.append(f"{path.name} ({exc.problems[0]})")
    return notes


def consolidate(folder: Path, aside: bool = False) -> str:
    phase1 = folder / "_scratch" / "phase1"
    sources = sorted(phase1.glob("*.findings.json"))
    rejected = set_aside_invalid(folder) if aside and not sources else []
    if not sources:
        current = sorted(folder.glob("*.findings.json"))
        if not current:
            raise Invalid(f"no valid *.findings.json in {folder}"
                          + (f"; set aside: {'; '.join(rejected)}" if rejected else ""))
        load(current)
        phase1.mkdir(parents=True, exist_ok=True)
        for path in current:
            shutil.copyfile(path, phase1 / path.name)
        sources = sorted(phase1.glob("*.findings.json"))
    docs = load(sources)
    nodes = nodes_of(docs)

    parent = list(range(len(nodes)))

    def root(n: int) -> int:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    for a in range(len(nodes)):
        for b in range(a + 1, len(nodes)):
            if family(nodes[a]["f"]) == family(nodes[b]["f"]) and same_anchor(nodes[a]["f"], nodes[b]["f"]) \
                    and (nodes[a]["lens"] != nodes[b]["lens"] or same_finding(nodes[a]["f"], nodes[b]["f"])):
                parent[root(b)] = root(a)
    groups: dict[int, list[int]] = {}
    for n in range(len(nodes)):
        groups.setdefault(root(n), []).append(n)

    dropped: set[int] = set()
    merged = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda n: (nodes[n]["lens"] != owner(nodes[n]["f"]),
                                    SEVERITY_RANK[nodes[n]["f"]["severity"]],
                                    CONFIDENCE_RANK[nodes[n]["f"]["confidence"]],
                                    rr.LENS_ORDER.index(nodes[n]["lens"]), nodes[n]["id"]))
        keep, rest = members[0], members[1:]
        add_related(nodes[keep]["f"], [f"{nodes[n]['id']} (merged duplicate)" for n in rest])
        dropped.update(rest)
        merged += len(rest)

    links = 0
    kept = [n for n in range(len(nodes)) if n not in dropped]
    for x, a in enumerate(kept):
        for b in kept[x + 1:]:
            if nodes[a]["lens"] != nodes[b]["lens"] and same_anchor(nodes[a]["f"], nodes[b]["f"]):
                add_related(nodes[a]["f"], [nodes[b]["id"]])
                add_related(nodes[b]["f"], [nodes[a]["id"]])
                links += 1

    for d, entry in enumerate(docs):
        entry["doc"]["findings"] = [n["f"] for i, n in enumerate(nodes) if n["doc"] == d and i not in dropped]
    write(folder, docs)
    write(folder / "_scratch" / "phase2", docs)

    queue = [{"id": n["id"], "lens": n["lens"], "agent": AGENT_OF_LENS[n["lens"]],
              "findings_file": docs[n["doc"]]["name"], "check_id": n["f"]["check_id"],
              "severity": n["f"]["severity"], "confidence": n["f"]["confidence"], "title": n["f"]["title"],
              "file": n["f"]["file"], **({"line": n["f"]["line"]} if "line" in n["f"] else {})}
             for n in nodes_of(docs) if n["f"]["severity"] in SERIOUS]
    queue_path = folder / "_scratch" / "refute-queue.json"
    queue_path.write_text(json.dumps({"queue": queue}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    by_lens = {lens: sum(1 for q in queue if q["lens"] == lens) for lens in rr.LENS_ORDER}
    per = ", ".join(f"{lens} {count} ({AGENT_OF_LENS[lens]})" for lens, count in by_lens.items() if count)
    return (f"Merged {merged} duplicate finding(s); {links} cross-link(s); {len(queue)} HIGH/CRITICAL "
            f"finding(s) queued for refutation{': ' + per if per else ''}. Queue: {queue_path}"
            + (f". Set aside as invalid: {'; '.join(rejected)}" if rejected else ""))


def apply(folder: Path) -> str:
    phase2 = folder / "_scratch" / "phase2"
    sources = sorted(phase2.glob("*.findings.json"))
    queue_path = folder / "_scratch" / "refute-queue.json"
    if not sources or not queue_path.is_file():
        raise Invalid(f"run `consolidate {folder}` first: no phase-2 findings or refutation queue")
    queue = json.loads(queue_path.read_text(encoding="utf-8"))["queue"]
    verdicts: dict[str, dict] = {}
    for path in sorted((folder / "_scratch" / "refutations").glob("*.json")):
        try:
            items = json.loads(path.read_text(encoding="utf-8"))["verdicts"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise Invalid(f"{path.name}: not a verdict file ({exc.__class__.__name__})") from None
        for item in items:
            if not (isinstance(item, dict) and item.get("verdict") in ("refuted", "upheld")
                    and isinstance(item.get("id"), str) and str(item.get("reason", "")).strip()):
                raise Invalid(f"{path.name}: each verdict needs an id, a verdict of refuted or upheld, "
                              f"and a reason: {item!r}")
            verdicts[item["id"]] = item
    docs = load(sources)
    refuted = upheld = 0
    seen: set[str] = set()
    for n in nodes_of(docs):
        verdict = verdicts.get(n["id"])
        if verdict is None or n["f"]["severity"] not in SERIOUS:
            continue
        seen.add(n["id"])
        reason, before = " ".join(verdict["reason"].split()), n["f"].get("refutation", "")
        if verdict["verdict"] == "refuted":
            n["f"].update(severity="QUESTION", confidence="low",
                          refutation=f"Refuted by the independent pass: {reason} The reviewer's own check: {before}")
            refuted += 1
        else:
            n["f"]["refutation"] = f"{before} Upheld by the independent pass: {reason}"
            upheld += 1
    write(folder, docs)
    unchecked = [q["id"] for q in queue if q["id"] not in seen]
    unknown = sorted(set(verdicts) - seen)
    return (f"Applied {refuted} refuted (now Questions) and {upheld} upheld verdict(s)."
            + (f" Not rechecked: {', '.join(unchecked)}." if unchecked else "")
            + (f" Verdicts matching no queued finding: {', '.join(unknown)}." if unknown else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], allow_abbrev=False)
    parser.add_argument("step", choices=("start", "consolidate", "apply"))
    parser.add_argument("reports_dir", help="<target>/review-reports")
    parser.add_argument("--set-aside-invalid", action="store_true",
                        help="consolidate: move a rejected lens file to _scratch/rejected/ instead of stopping")
    args = parser.parse_args(argv)
    folder = Path(args.reports_dir).expanduser()
    if not folder.is_dir():
        print(f"review_consolidate.py: {folder} is not a directory", file=sys.stderr)
        return 2
    steps = {"start": lambda: start(folder), "apply": lambda: apply(folder),
             "consolidate": lambda: consolidate(folder, args.set_aside_invalid)}
    try:
        print(steps[args.step]())
    except Invalid as exc:
        print(f"review_consolidate.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
