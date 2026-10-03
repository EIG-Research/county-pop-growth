#!/usr/bin/env python3
"""Validate review findings and render them as HTML: one report per lens plus `index.html`.

    render_review_report.py <input>... [--out DIR] [--check]

Each input is a findings file (`<lens>.findings.json`) or a directory, which stands for every
`*.findings.json` in it. `--out` defaults to the first input's directory (normally
`<target>/review-reports/`). `--check` validates and prints the summary without writing.

What the script owns, so that no prompt restates or recomputes it:

  - **Validation** against `Infrastructure/templates/review-findings.schema.json`, read at run
    time. A file that fails (no evidence, an unknown `check_id` for its lens, a HIGH without a
    refutation) is reported and nothing is written.
  - **Stable IDs.** `<lens>-<6 hex>`: the start of a SHA-256 over the check id, the file, and
    the quoted evidence with runs of whitespace collapsed (the claim and the places looked,
    for a finding about something missing). Line numbers are not hashed, so an ID survives
    edits above the quoted code. Findings that hash alike get `-2`, `-3`, ... in line order.
  - **Counts and risk** (review-contract.md section 3): counts by severity and confidence;
    overall risk is the highest severity among high-confidence findings, reported with the
    number of HIGH and CRITICAL findings that are not high confidence.
  - **Rendering.** Colors and fonts come from the EIG token file. Pages are self-contained,
    run no script, carry a Content-Security-Policy that admits only their own hashed style
    block, escape every value, filter by severity, confidence, and lens with CSS alone, and
    have print and dark styles. The output is a pure function of the inputs, the schema, and
    the tokens: rendering twice gives the same bytes.

Exit codes: 0 rendered (or valid under --check); 1 validation failed; 2 usage error.
Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
INFRA = SCRIPTS.parent
SCHEMA_PATH = INFRA / "templates" / "review-findings.schema.json"
TOKENS_PATH = INFRA / "style" / "tokens" / "eig-style-tokens.v1.json"

LENSES = {  # prefix: (title, report file)
    "CE": ("Code errors", "code-error-report.html"),
    "MR": ("Methodology", "methodology-report.html"),
    "DN": ("Document numbers", "doc-number-report.html"),
    "CC": ("Document-code consistency", "doc-consistency-report.html"),
    "AS": ("Provenance (AI skeptic)", "ai-skeptic-report.html"),
}
LENS_ORDER = tuple(LENSES)
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "SUGGESTION", "QUESTION")
RISK_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
CONFIDENCES = ("high", "medium", "low")

# Token ids for each role; a missing id is an error, never a silent fallback.
COLOR_ROLES = {
    "ink": "eig_black", "paper": "eig_white", "brand": "eig_teal_900", "accent": "eig_blue_800",
    "wash": "eig_cream_100", "rule": "eig_neutral_rule_light", "grid": "eig_neutral_grid",
    "muted": "eig_neutral_caption",
    "sev-CRITICAL": "eig_purple_800", "sev-HIGH": "eig_tan_500", "sev-MEDIUM": "eig_gold_600",
    "sev-LOW": "eig_green_500", "sev-SUGGESTION": "eig_blue_200", "sev-QUESTION": "eig_neutral_grid",
}
LIGHT_TEXT_ON = {"sev-CRITICAL"}


class ValidationFailed(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


# --------------------------------------------------------------------------- validation
def _type_ok(value: Any, kind: str) -> bool:
    return {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "null": value is None,
    }[kind]


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref is supported: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(value: Any, schema: dict, root: dict, where: str = "$") -> list[str]:
    """Problems with `value` under the JSON Schema subset the findings schema uses."""
    if "$ref" in schema:
        return validate(value, _resolve(schema["$ref"], root), root, where)
    problems: list[str] = []
    if "type" in schema and not _type_ok(value, schema["type"]):
        return [f"{where}: expected {schema['type']}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        problems.append(f"{where}: must be {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{where}: {value!r} is not one of {', '.join(map(str, schema['enum']))}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            problems.append(f"{where}: must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            problems.append(f"{where}: {value!r} does not match {schema['pattern']}")
    if _type_ok(value, "number") and "minimum" in schema and value < schema["minimum"]:
        problems.append(f"{where}: {value} is below {schema['minimum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{where}: missing required field `{key}`")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                problems += validate(item, props[key], root, f"{where}.{key}")
            elif schema.get("additionalProperties") is False:
                problems.append(f"{where}: unknown field `{key}`")
            elif isinstance(schema.get("additionalProperties"), dict):
                problems += validate(item, schema["additionalProperties"], root, f"{where}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            problems.append(f"{where}: needs at least {schema['minItems']} item(s)")
        if "items" in schema:
            for index, item in enumerate(value):
                problems += validate(item, schema["items"], root, f"{where}[{index}]")
    for sub in schema.get("allOf", []):
        problems += validate(value, sub, root, where)
    if "anyOf" in schema:
        results = [validate(value, sub, root, where) for sub in schema["anyOf"]]
        if all(results):
            problems.append(f"{where}: matches none of the allowed shapes: "
                            + " | ".join("; ".join(r) for r in results))
    if "oneOf" in schema:
        branches = schema["oneOf"]
        passing = [b for b in branches if not validate(value, b, root, where)]
        if len(passing) != 1:
            consts = [b["const"] for b in branches if "const" in b]
            if len(consts) == len(branches):
                problems.append(f"{where}: {value!r} is not one of {', '.join(consts)}")
            else:
                problems.append(f"{where}: must match exactly one allowed shape")
    if "not" in schema and not validate(value, schema["not"], root, where):
        problems.append(f"{where}: {value!r} is not allowed here "
                        f"({schema.get('description', 'excluded by the schema')})")
    if "if" in schema and not validate(value, schema["if"], root, where):
        if "then" in schema:
            problems += validate(value, schema["then"], root, where)
    elif "if" in schema and "else" in schema:
        problems += validate(value, schema["else"], root, where)
    return problems


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_findings(path: Path, schema: dict) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationFailed([f"{path.name}: cannot read JSON ({exc})"]) from None
    problems = validate(doc, schema, schema)
    if problems:
        raise ValidationFailed([f"{path.name}: {p}" for p in problems])
    return doc


# --------------------------------------------------------------------------- ids, counts, risk
def normalize(text: str) -> str:
    return " ".join(text.split())


def identity_text(finding: dict) -> str:
    evidence = finding["evidence"]
    if "quote" in evidence:
        return normalize(evidence["quote"])
    return normalize(evidence["claim"]) + "\0" + "\0".join(normalize(p) for p in evidence["looked_in"])


def assign_ids(lens: str, findings: list[dict]) -> list[str]:
    """Stable IDs in input order; collisions are ordered by line, then title, then input order."""
    bases = []
    for finding in findings:
        key = "\0".join((finding["check_id"], finding["file"], identity_text(finding)))
        bases.append(f"{lens}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:6]}")
    ids = list(bases)
    groups: dict[str, list[int]] = {}
    for index, base in enumerate(bases):
        groups.setdefault(base, []).append(index)
    for base, members in groups.items():
        members.sort(key=lambda i: (findings[i].get("line", 0), findings[i]["title"], i))
        for ordinal, index in enumerate(members[1:], start=2):
            ids[index] = f"{base}-{ordinal}"
    return ids


def tally(findings: list[dict]) -> dict:
    counts = {s: 0 for s in SEVERITIES}
    high_conf = {s: 0 for s in SEVERITIES}
    for f in findings:
        counts[f["severity"]] += 1
        if f["confidence"] == "high":
            high_conf[f["severity"]] += 1
    risk = next((s for s in RISK_SEVERITIES if high_conf[s]), "NONE")
    unconfirmed = sum(1 for f in findings
                      if f["severity"] in ("CRITICAL", "HIGH") and f["confidence"] != "high")
    return {"counts": counts, "high_confidence": high_conf, "risk": risk,
            "unconfirmed_high": unconfirmed, "questions": counts["QUESTION"],
            "findings": sum(counts[s] for s in SEVERITIES if s != "QUESTION")}


def prepare(doc: dict) -> dict:
    ids = assign_ids(doc["lens"], doc["findings"])
    items = [dict(f, id=i) for f, i in zip(doc["findings"], ids)]
    rank = {s: n for n, s in enumerate(SEVERITIES)}
    items.sort(key=lambda f: (rank[f["severity"]], f["file"], f.get("line", 0), f["id"]))
    return dict(doc, findings=items, tally=tally(items))


def summary_line(doc: dict) -> str:
    t = doc["tally"]
    parts = [f"{t['counts'][s]} {s}" for s in SEVERITIES[:-1] if t["counts"][s]]
    return (f"{doc['lens']} {LENSES[doc['lens']][0]}: {t['findings']} finding(s)"
            + (f" ({', '.join(parts)})" if parts else "")
            + f", {t['questions']} question(s); overall risk {t['risk']}"
            + f"; {t['unconfirmed_high']} unconfirmed HIGH/CRITICAL")


# --------------------------------------------------------------------------- HTML
def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def load_tokens() -> tuple[dict[str, str], str, str]:
    tokens = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    by_id = {c["id"]: c["hex"] for group in ("brand", "neutrals") for c in tokens["colors"][group]}
    colors = {}
    for role, token in COLOR_ROLES.items():
        if token not in by_id:
            raise SystemExit(f"render_review_report.py: token `{token}` is missing from {TOKENS_PATH.name}")
        colors[role] = by_id[token]
    typo = tokens["typography"]

    def stack(entry: dict) -> str:
        names = [entry["primary_family"], *entry.get("accept_as_primary", []), *entry["fallback_stack"]]
        return ", ".join(n if n in ("serif", "sans-serif") else f'"{n}"' for n in names)
    return colors, stack(typo["body"]), stack(typo["headline"])


def stylesheet() -> str:
    colors, body_font, head_font = load_tokens()
    var = lambda role: colors[role]  # noqa: E731
    sev_rules = "\n".join(
        f".badge.sev-{s} {{ background: {var('sev-' + s)}; color: "
        f"{var('paper') if 'sev-' + s in LIGHT_TEXT_ON else var('ink')}; }}\n"
        f".finding.sev-{s} {{ border-left-color: {var('sev-' + s)}; }}"
        for s in SEVERITIES)
    filters = "\n".join(
        [f"body:has(#show-sev-{s}:not(:checked)) .sev-{s}.filterable {{ display: none; }}" for s in SEVERITIES]
        + [f"body:has(#show-conf-{c}:not(:checked)) .conf-{c}.filterable {{ display: none; }}" for c in CONFIDENCES]
        + [f"body:has(#show-lens-{l}:not(:checked)) .lens-{l}.filterable {{ display: none; }}" for l in LENS_ORDER])
    return f"""
:root {{ --ink: {var('ink')}; --paper: {var('paper')}; --brand: {var('brand')}; --accent: {var('accent')};
  --wash: {var('wash')}; --rule: {var('rule')}; --grid: {var('grid')}; --muted: {var('muted')}; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: {body_font}; font-size: 15px; line-height: 1.55; color: var(--ink); background: var(--paper); }}
h1, h2, h3 {{ font-family: {head_font}; line-height: 1.25; }}
header.top {{ background: var(--brand); color: var(--paper); padding: 1.5rem 2rem; }}
header.top h1 {{ margin: 0 0 .25rem; font-size: 1.6rem; }}
header.top p {{ margin: 0; }}
main {{ max-width: 72rem; margin: 0 auto; padding: 1.5rem 2rem 3rem; }}
a {{ color: var(--accent); }}
header.top a {{ color: var(--paper); }}
.stats {{ display: flex; flex-wrap: wrap; gap: .75rem; margin: 1rem 0; }}
.stat {{ border: 1px solid var(--grid); border-radius: 4px; padding: .5rem .9rem; min-width: 7rem; }}
.stat b {{ display: block; font-size: 1.4rem; }}
.stat.risk {{ background: var(--wash); }}
table {{ border-collapse: collapse; width: 100%; margin: .75rem 0; }}
th, td {{ border-bottom: 1px solid var(--rule); padding: .35rem .5rem; text-align: left; vertical-align: top; }}
th {{ border-bottom: 2px solid var(--grid); }}
.badge {{ display: inline-block; padding: 0 .45rem; border-radius: 3px; font-size: .8rem; font-weight: 700; }}
.badge.conf {{ border: 1px solid var(--grid); font-weight: 400; }}
.finding {{ border: 1px solid var(--rule); border-left: 6px solid var(--grid); border-radius: 4px; padding: .75rem 1rem; margin: 1rem 0; }}
.finding h3 {{ margin: .1rem 0 .4rem; font-size: 1.1rem; }}
.meta {{ color: var(--muted); font-size: .85rem; }}
dl {{ margin: .5rem 0 0; }}
dt {{ font-weight: 700; margin-top: .4rem; }}
dd {{ margin: 0 0 0 1rem; }}
pre {{ background: var(--wash); color: var(--ink); padding: .6rem .8rem; overflow-x: auto; border-radius: 3px; white-space: pre-wrap; }}
code {{ font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: .88rem; }}
fieldset.filters {{ border: 1px solid var(--grid); border-radius: 4px; margin: 1rem 0; padding: .4rem .8rem; }}
fieldset.filters label {{ margin-right: .9rem; white-space: nowrap; }}
{sev_rules}
{filters}
@media (prefers-color-scheme: dark) {{
  :root {{ --ink: {var('paper')}; --paper: {var('ink')}; --wash: {var('brand')}; --accent: {var('sev-SUGGESTION')}; --muted: {var('grid')}; --rule: {var('muted')}; }}
  header.top {{ background: {var('brand')}; color: {var('paper')}; }}
  header.top a {{ color: {var('paper')}; }}
}}
@media print {{
  fieldset.filters {{ display: none; }}
  .filterable {{ display: block !important; }}
  tr.filterable {{ display: table-row !important; }}
  .finding {{ break-inside: avoid; }}
  header.top {{ background: none; color: {var('ink')}; border-bottom: 2px solid {var('brand')}; }}
}}
"""


def page(title: str, body: str) -> str:
    style = stylesheet()
    digest = base64.b64encode(hashlib.sha256(style.encode("utf-8")).digest()).decode("ascii")
    csp = (f"default-src 'none'; style-src 'sha256-{digest}'; img-src 'none'; "
           "base-uri 'none'; form-action 'none'")
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            f"<meta http-equiv=\"Content-Security-Policy\" content=\"{csp}\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<meta name=\"referrer\" content=\"no-referrer\">\n"
            f"<title>{esc(title)}</title>\n<style>{style}</style>\n</head>\n<body>\n{body}</body>\n</html>\n")


def filter_controls(lenses: list[str] | None = None) -> str:
    def box(group: str, value: str, label: str) -> str:
        return (f'<label><input type="checkbox" id="show-{group}-{value}" checked> '
                f"{esc(label)}</label>")
    rows = ['<fieldset class="filters"><legend>Show</legend>',
            "<div>" + "".join(box("sev", s, s.title()) for s in SEVERITIES) + "</div>",
            "<div>" + "".join(box("conf", c, f"{c} confidence") for c in CONFIDENCES) + "</div>"]
    if lenses:
        rows.append("<div>" + "".join(box("lens", l, LENSES[l][0]) for l in lenses) + "</div>")
    rows.append("</fieldset>")
    return "\n".join(rows) + "\n"


def location(f: dict) -> str:
    if "line" not in f:
        return f["file"]
    end = f":{f['line']}" + (f"-{f['end_line']}" if f.get("end_line", f["line"]) != f["line"] else "")
    return f["file"] + end


def stats_block(t: dict) -> str:
    cells = [f'<div class="stat risk">Overall risk<b>{esc(t["risk"])}</b>'
             f'<span class="meta">high-confidence findings only</span></div>',
             f'<div class="stat">Unconfirmed HIGH/CRITICAL<b>{t["unconfirmed_high"]}</b></div>']
    for s in SEVERITIES:
        label = "Questions" if s == "QUESTION" else s.title()
        extra = "" if s == "QUESTION" else f'<span class="meta">{t["high_confidence"][s]} high confidence</span>'
        cells.append(f'<div class="stat">{label}<b>{t["counts"][s]}</b>{extra}</div>')
    return '<div class="stats">' + "".join(cells) + "</div>\n"


def finding_card(f: dict, lens: str) -> str:
    ev = f["evidence"]
    rows = [("Claim", esc(ev["claim"])), ("Found", esc(ev["found"]))]
    if "quote" in ev:
        rows.append(("Quoted", f"<pre><code>{esc(ev['quote'])}</code></pre>"))
    if "looked_in" in ev:
        rows.append(("Looked in", "<ul>" + "".join(f"<li>{esc(p)}</li>" for p in ev["looked_in"]) + "</ul>"))
    rows.append(("Verified by", esc(ev["verified_by"])))
    if ev.get("command"):
        rows.append(("Command", f"<pre><code>{esc(ev['command'])}</code></pre>"))
    for key, label in (("refutation", "Refutation tried"), ("explanation", "Why it matters"),
                       ("fix", "Fix")):
        if f.get(key):
            rows.append((label, esc(f[key])))
    if f.get("related"):
        rows.append(("Related", esc(", ".join(f["related"]))))
    detail = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    sev = f["severity"]
    badge = "Question" if sev == "QUESTION" else sev
    return (f'<article class="finding filterable sev-{sev} conf-{f["confidence"]} lens-{lens}" id="{esc(f["id"])}">\n'
            f'<p class="meta"><span class="badge sev-{sev}">{badge}</span> '
            f'<span class="badge conf">{esc(f["confidence"])} confidence</span> '
            f'<a href="#{esc(f["id"])}">{esc(f["id"])}</a> · {esc(f["check_id"])} · '
            f"<code>{esc(location(f))}</code></p>\n"
            f"<h3>{esc(f['title'])}</h3>\n<dl>{detail}</dl>\n</article>\n")


def render_lens(doc: dict) -> str:
    lens = doc["lens"]
    title = f"{LENSES[lens][0]} review: {doc['target']}"
    parts = [f'<header class="top"><h1>{esc(LENSES[lens][0])} review</h1>'
             f"<p>{esc(doc['target'])} · {esc(doc['review_date'])} · "
             f"{len(doc['files_reviewed'])} file(s) reviewed · "
             f'<a href="index.html">all reviews</a></p></header>\n<main>\n']
    parts.append(stats_block(doc["tally"]))
    if doc.get("summary"):
        parts.append(f"<h2>Summary</h2>\n<p>{esc(doc['summary'])}</p>\n")
    if doc.get("context"):
        parts.append("<h2>Context</h2>\n<dl>" + "".join(
            f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in sorted(doc["context"].items())) + "</dl>\n")
    findings = [f for f in doc["findings"] if f["severity"] != "QUESTION"]
    questions = [f for f in doc["findings"] if f["severity"] == "QUESTION"]
    parts.append(filter_controls())
    parts.append(f"<h2>Findings ({len(findings)})</h2>\n")
    parts.extend(finding_card(f, lens) for f in findings)
    if not findings:
        parts.append("<p>No findings.</p>\n")
    parts.append(f"<h2>Questions for the author ({len(questions)})</h2>\n")
    parts.extend(finding_card(f, lens) for f in questions)
    if not questions:
        parts.append("<p>No open questions.</p>\n")
    parts.append("<h2>Files reviewed</h2>\n<ul>" + "".join(
        f"<li><code>{esc(p)}</code></li>" for p in doc["files_reviewed"]) + "</ul>\n")
    parts.append(f'<p class="meta">Rendered by render_review_report.py from '
                 f"{esc(doc['_source'])}; IDs are stable across reruns.</p>\n</main>\n")
    return page(title, "".join(parts))


def render_index(docs: list[dict]) -> str:
    target = docs[0]["target"]
    lenses = [d["lens"] for d in docs]
    parts = [f'<header class="top"><h1>Review index</h1><p>{esc(target)} · '
             f"{esc(max(d['review_date'] for d in docs))}</p></header>\n<main>\n",
             "<h2>Reports</h2>\n<table><thead><tr><th>Lens</th><th>Report</th><th>Findings</th>"
             "<th>Questions</th><th>Overall risk</th><th>Unconfirmed HIGH/CRITICAL</th></tr></thead><tbody>\n"]
    for d in docs:
        t, (name, file) = d["tally"], LENSES[d["lens"]]
        counts = ", ".join(f"{t['counts'][s]} {s}" for s in SEVERITIES[:-1] if t["counts"][s]) or "none"
        parts.append(f"<tr><td>{esc(name)}</td><td><a href=\"{file}\">{file}</a></td>"
                     f"<td>{esc(counts)}</td><td>{t['questions']}</td><td>{esc(t['risk'])}</td>"
                     f"<td>{t['unconfirmed_high']}</td></tr>\n")
    parts.append("</tbody></table>\n")
    parts.append(filter_controls(lenses))
    parts.append("<h2>All findings and questions</h2>\n<table><thead><tr><th>ID</th><th>Severity</th>"
                 "<th>Confidence</th><th>Location</th><th>Title</th></tr></thead><tbody>\n")
    rank = {s: n for n, s in enumerate(SEVERITIES)}
    rows = sorted(((d["lens"], f) for d in docs for f in d["findings"]),
                  key=lambda x: (rank[x[1]["severity"]], LENS_ORDER.index(x[0]), x[1]["id"]))
    for lens, f in rows:
        parts.append(f'<tr class="filterable sev-{f["severity"]} conf-{f["confidence"]} lens-{lens}">'
                     f'<td><a href="{LENSES[lens][1]}#{esc(f["id"])}">{esc(f["id"])}</a></td>'
                     f'<td><span class="badge sev-{f["severity"]}">{f["severity"]}</span></td>'
                     f"<td>{esc(f['confidence'])}</td><td><code>{esc(location(f))}</code></td>"
                     f"<td>{esc(f['title'])}</td></tr>\n")
    if not rows:
        parts.append('<tr><td colspan="5">No findings.</td></tr>\n')
    parts.append("</tbody></table>\n</main>\n")
    return page(f"Review index: {target}", "".join(parts))


# --------------------------------------------------------------------------- CLI
def collect(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            paths.extend(sorted(path.glob("*.findings.json")))
        elif path.is_file():
            paths.append(path)
        else:
            raise SystemExit(f"render_review_report.py: {raw} does not exist")
    if not paths:
        raise SystemExit("render_review_report.py: no *.findings.json files to render")
    return paths


def build(paths: list[Path]) -> list[dict]:
    schema = load_schema()
    docs, problems = [], []
    for path in paths:
        try:
            doc = load_findings(path, schema)
        except ValidationFailed as exc:
            problems.extend(exc.problems)
            continue
        doc["_source"] = path.name
        docs.append(prepare(doc))
    lenses = [d["lens"] for d in docs]
    for lens in sorted({l for l in lenses if lenses.count(l) > 1}):
        problems.append(f"more than one findings file for lens {lens}")
    if len({d["target"] for d in docs}) > 1:
        problems.append("the findings files name different targets: "
                        + ", ".join(sorted({d["target"] for d in docs})))
    if problems:
        raise ValidationFailed(problems)
    return sorted(docs, key=lambda d: LENS_ORDER.index(d["lens"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], allow_abbrev=False)
    parser.add_argument("inputs", nargs="+", help="findings files or directories")
    parser.add_argument("--out", help="output directory (default: the first input's directory)")
    parser.add_argument("--check", action="store_true", help="validate and summarize; write nothing")
    args = parser.parse_args(argv)
    paths = collect(args.inputs)
    try:
        docs = build(paths)
    except ValidationFailed as exc:
        print("Findings failed validation; nothing was written:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    for doc in docs:
        print(summary_line(doc))
    if args.check:
        return 0
    first = Path(args.inputs[0]).expanduser()
    out = Path(args.out).expanduser() if args.out else (first if first.is_dir() else first.parent)
    out.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        (out / LENSES[doc["lens"]][1]).write_text(render_lens(doc), encoding="utf-8", newline="\n")
    (out / "index.html").write_text(render_index(docs), encoding="utf-8", newline="\n")
    print(f"Wrote {', '.join(LENSES[d['lens']][1] for d in docs)} and index.html to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
