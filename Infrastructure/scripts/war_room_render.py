#!/usr/bin/env python3
"""Render a war-room ledger: `ledger.md` and the HTML report.

`ledger.yaml` is the source of truth (WR-O1). This script is the only writer of the two
rendered artifacts (WR-O5), and it writes nothing else:

    md    <ledger.yaml> --out <ledger.md>
    html  <ledger.yaml> --project-root <dir> --out <report.html>

Both subcommands refuse to run when `war_room_lint.py` reports a failure (D7). Rendering a
ledger that does not lint would publish a broken record in a format that looks finished, so
nothing is written and the failures are printed instead.

Both are deterministic: the output is a pure function of the ledger (and, for `html`, of the
reviewed source and the report template). No timestamp, no path from the running machine,
and no ordering that depends on a dict's insertion history reaches the output, so rendering
the same ledger twice produces the same bytes.

Three properties the rules file depends on, and how they are kept here:

  - **Predictions render verbatim** (WR-P2, WR-P3, WRR-3). Prediction text is copied out of
    the ledger and HTML-escaped; it is never re-worded, truncated, or re-wrapped.
  - **Drift is read, never recomputed** (WR-A3/A4, D11). The drift banner comes from the
    persisted `drift` and `drift_after_disposition` flags, so the console note, the ledger,
    and the report cannot disagree.
  - **Fast-forwarded blocks render with the prediction only** (WRR-2). No author pane is
    emitted for a block nobody discussed, because there is no author account to render.

The HTML is not embedded in this file. It is read at run time out of the fenced `html` block
in `Infrastructure/templates/war-room-report.md`, which keeps the binding template and the
renderer from drifting apart (WR-O5). The template marks its repeated parts with comment
markers, which the renderer repeats and then strips:

    <!-- BEGIN BLOCK_CARD -->        one per block, in file order
      <!-- BEGIN DRIFT_FLAG -->      emitted only when the block carries `drift: true`
      <!-- BEGIN AUTHOR_PANE -->     omitted for a fast-forwarded block (WRR-2)
    <!-- BEGIN ASSUMPTION_ROW -->    one per `assumption_export` item
    <!-- BEGIN OPEN_QUESTION_ROW --> one per `open_questions` item

Every `{{PLACEHOLDER}}` in the template body must be one this renderer knows how to fill; an
unknown one is an error rather than a silently empty cell, and the finished document is
checked for a surviving `{{` before it is written.

Dependencies: Python 3.11+ and PyYAML. Nothing else.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import war_room_lib as wr  # noqa: E402
import war_room_lint as wl  # noqa: E402

DEFAULT_TEMPLATE = (Path(__file__).resolve().parent.parent
                    / "templates" / "war-room-report.md")

NONE_RECORDED = "None recorded"
NONE_DETECTED = "None detected"
EM_DASH = "—"

_DISPOSITION_CLASS = {
    "needs-change": "needs-change",
    "unresolved": "unresolved",
    "misread-by-agent": "misread",
    "confirmed": "confirmed",
}


# --------------------------------------------------------------------------- shared facts
class View:
    """Everything both renderers need, read once out of the ledger."""

    def __init__(self, ledger: dict, ledger_path: Path) -> None:
        self.ledger = ledger
        self.path = Path(ledger_path)
        self.script = ledger.get("script") or {}
        self.project = ledger.get("project") or {}
        self.session = ledger.get("session") or {}
        self.blocks = [b for b in (ledger.get("blocks") or []) if isinstance(b, dict)]
        self.export = [a for a in (ledger.get("assumption_export") or [])
                       if isinstance(a, dict)]
        self.opens = [q for q in (ledger.get("open_questions") or [])
                      if isinstance(q, dict)]

    # -- counts ----------------------------------------------------------------
    @property
    def n(self) -> int:
        return len(self.blocks)

    @property
    def discussed(self) -> list[dict]:
        return [b for b in self.blocks if b.get("discussed")]

    @property
    def fast_forwarded(self) -> list[dict]:
        """Recorded without discussion (WR-C3). A block nobody answered is not one."""
        return [b for b in self.blocks
                if not b.get("discussed") and b.get("disposition")]

    @property
    def unanswered(self) -> list[dict]:
        return [b for b in self.blocks
                if not b.get("discussed") and not b.get("disposition")]

    def by_disposition(self, disposition: str) -> list[dict]:
        return [b for b in self.blocks if b.get("disposition") == disposition]

    @property
    def reviewers(self) -> list[str]:
        ids = [str(r.get("id")) for r in (self.session.get("reviewers") or [])
               if isinstance(r, dict) and r.get("id")]
        return ids or sorted({str(b.get("reviewer")) for b in self.blocks
                              if b.get("reviewer")})

    @property
    def drifted(self) -> list[dict]:
        return [b for b in self.blocks if b.get("drift")]

    def summary(self) -> str:
        """Two to four sentences, computed from the ledger. Nothing here is written prose.

        A rendered summary that a model wrote would be a second reading of the script,
        competing with the recorded predictions; these sentences only count what is there.
        """
        script = self.script.get("path", "the script")
        language = self.script.get("language", "")
        lang = f" ({language})" if language else ""
        tail = (f", and {len(self.unanswered)} not answered"
                if self.unanswered else "")
        parts = [
            f"{script}{lang} was walked in {self.n} block"
            f"{'' if self.n == 1 else 's'}: {len(self.discussed)} discussed, "
            f"{len(self.fast_forwarded)} fast-forwarded{tail}."
        ]
        counts = ", ".join(
            f"{len(self.by_disposition(d))} {d}" for d in
            ("confirmed", "misread-by-agent", "needs-change", "unresolved"))
        parts.append(f"Dispositions: {counts}.")
        diverged = [b for b in self.blocks
                    if (b.get("divergence") or {}).get("match") is False]
        unreconciled = [b for b in self.blocks
                        if b.get("disposition") and b.get("discussed")
                        and (b.get("divergence") or {}).get("match") is None]
        if self.session.get("reconciled"):
            parts.append(f"Reconcile recorded a divergence on {len(diverged)} block"
                         f"{'' if len(diverged) == 1 else 's'} and agreement on the rest.")
        else:
            parts.append(f"This ledger is not reconciled yet: {len(unreconciled)} "
                         f"discussed block"
                         f"{'' if len(unreconciled) == 1 else 's'} still carry no "
                         f"divergence classification.")
        drifted = self.drifted
        if drifted:
            regressed = [b for b in drifted if b.get("drift_after_disposition")]
            parts.append(f"{len(drifted)} block"
                         f"{'' if len(drifted) == 1 else 's'} drifted from the source, "
                         f"{len(regressed)} of them after a disposition was recorded "
                         f"(WR-A4).")
        return " ".join(parts)


def repo_relative(path: Path) -> str:
    """A relative path a reader can paste; never a machine-specific absolute one."""
    resolved = Path(path).expanduser().resolve()
    for parent in resolved.parents:
        if (parent / ".git").exists():
            return resolved.relative_to(parent).as_posix()
    parts = resolved.parts
    if "war_rooms" in parts:
        i = parts.index("war_rooms")
        start = i - 1 if i > 0 and parts[i - 1] == "records" else i
        return Path(*parts[start:]).as_posix()
    return Path(resolved.parent.name, resolved.name).as_posix()


def lint_gate(ledger: dict, ledger_path: Path, project_root: Path | None) -> None:
    """D7: a ledger that does not lint is not rendered, and nothing is written."""
    result = wl.lint(ledger, project_root)
    for warning in result.warnings:
        print(f"warning: {warning.line()}", file=sys.stderr)
    if not result.ok:
        print(f"LINT REFUSED {ledger_path}: {len(result.failures)} failure(s); "
              f"nothing was rendered.")
        for failure in result.failures:
            print(f"  {failure.line()}")
        raise SystemExit(1)


def line_range(block: dict) -> str:
    lines_ = block.get("lines") or [0, 0]
    return f"{lines_[0]}-{lines_[1]}"


# --------------------------------------------------------------------------- markdown
def render_md(view: View) -> str:
    out: list[str] = []
    script = view.script.get("path", "(unknown script)")
    out += [
        f"# War Room — {script}",
        "",
        f"**Reviewed:** {view.session.get('created', '')}  ·  "
        f"**Reviewers:** {', '.join(view.reviewers) or NONE_RECORDED}  ·  "
        f"**Mode:** {view.session.get('mode', 'ordered')}",
        f"**Coverage:** {view.n} blocks — {len(view.discussed)} discussed, "
        f"{len(view.fast_forwarded)} fast-forwarded"
        + (f", {len(view.unanswered)} not answered" if view.unanswered else ""),
        "",
        "## Summary",
        "",
        view.summary(),
        "",
        "| Disposition | Count |",
        "|---|---|",
    ]
    for disposition in ("confirmed", "misread-by-agent", "needs-change", "unresolved"):
        out.append(f"| {disposition} | {len(view.by_disposition(disposition))} |")
    out += ["", "## Blocks", ""]

    if not view.blocks:
        out += [NONE_RECORDED + ".", ""]
    for b in view.blocks:
        pred = b.get("prediction") or {}
        acct = b.get("author_account") or {}
        coverage = ("discussed" if b.get("discussed")
                    else "fast-forwarded" if b.get("disposition") else "not answered")
        disposition = b.get("disposition") or "not answered"
        out += [
            f"### {b.get('block_id')} — {b.get('title', '')}",
            f"`{script}:{line_range(b)}` · density: {b.get('density', '')} · "
            f"{coverage} · **{disposition}**",
            "",
            # WRR-3 / WR-P3: the prediction is copied, never re-worded.
            f"> Agent read (confidence: {pred.get('confidence', '')}): "
            f"{pred.get('what_it_does', '')}",
            f"> Agent inferred intent: {pred.get('inferred_intent', '')}",
        ]
        if acct.get("meant_to_do"):
            out.append(f"> Author intent: {acct.get('meant_to_do')}")
        elif b.get("discussed") and b.get("endorsed_prediction"):
            # WR-Q7: an endorsement is an answer, and it renders as one. A discussed
            # block that showed nothing here would be indistinguishable from an unread one.
            out.append("> Author: endorsed the recorded prediction without amendment "
                       "(WR-Q7).")
        div = b.get("divergence") or {}
        if div.get("match") is False:
            out.append(f"> **Divergence — {div.get('type') or 'unclassified'}:** "
                       f"{div.get('detail') or NONE_RECORDED.lower()}")
        elif div.get("match") is True:
            out.append(f"> **Match:** {div.get('detail') or 'Readings agreed.'}")
        out.append("")
        if b.get("drift"):
            marker = (" It already carried a disposition when it changed (WR-A4)."
                      if b.get("drift_after_disposition") else "")
            out += [f"**Drift:** the source at lines {line_range(b)} no longer matches "
                    f"this block's recorded hash.{marker}", ""]
        if acct.get("why_this_way"):
            out += [f"**Why this way:** {acct.get('why_this_way')}", ""]
        if not b.get("discussed") and b.get("disposition"):
            out += ["Confirmed in a batch without discussion, which endorses the recorded "
                    "prediction and its assumptions (WR-C3, WR-Q8). No author account is "
                    "rendered for a fast-forwarded block.", ""]
        carried = [a for a in (acct.get("assumptions_carried") or []) if str(a).strip()]
        if carried:
            out.append("**Assumptions carried forward:**")
            out += [f"- {a}" for a in carried]
            out.append("")
        for item in (b.get("dissent") or []):
            if not isinstance(item, dict):
                continue
            detail = ((item.get("author_account") or {}).get("meant_to_do")
                      or "no account recorded")
            out += [f"**Dissent — {item.get('reviewer', '')} "
                    f"({item.get('disposition', '')}):** {detail}", ""]
        out += ["---", ""]

    out += ["## Assumptions Carried Forward", ""]
    if view.export:
        for bid in _ordered_block_ids(view, [a.get("block_id") for a in view.export]):
            out.append(f"**{bid}**")
            for a in view.export:
                if a.get("block_id") != bid:
                    continue
                out.append(f"- {a.get('assumption', '')} "
                           f"(stated by {a.get('stated_by', '')}; "
                           f"confirmed: {'yes' if a.get('confirmed') else 'no'})")
            out.append("")
    else:
        out += [NONE_RECORDED + ".", ""]

    out += ["## Open Questions", ""]
    if view.opens:
        for q in view.opens:
            out += [f"- **{q.get('block_id')}** — {q.get('question', '')} "
                    f"(blocked on: {q.get('blocked_on', '')})"]
        out.append("")
    else:
        out += [NONE_RECORDED + ".", ""]

    out += ["## Drift", ""]
    if view.drifted:
        for b in view.drifted:
            marker = ("  **Changed after its disposition (WR-A4).**"
                      if b.get("drift_after_disposition") else "")
            out.append(f"- **{b.get('block_id')}** — recorded lines {line_range(b)}; the "
                       f"source at those lines no longer matches the recorded hash."
                       f"{marker}")
        out.append("")
    else:
        out += [NONE_DETECTED + ".", ""]
    return "\n".join(out).rstrip("\n") + "\n"


def _ordered_block_ids(view: View, ids: Iterable[Any]) -> list[str]:
    """Block ids in file order, then any id the ledger's block list does not carry."""
    order = [str(b.get("block_id")) for b in view.blocks]
    seen = [str(i) for i in ids]
    known = [b for b in order if b in seen]
    extra = sorted({b for b in seen if b not in order})
    return known + extra


# --------------------------------------------------------------------------- html
class TemplateError(Exception):
    """The report template does not carry what the renderer needs."""


_FENCE = re.compile(r"^```html\n(.*?)^```", re.DOTALL | re.MULTILINE)
_PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def read_template(path: Path) -> str:
    """The fenced `html` block of the report template, which is the binding source."""
    text = Path(path).read_text(encoding="utf-8")
    match = _FENCE.search(text)
    if not match:
        raise TemplateError(f"{path} has no fenced ```html block to render from")
    return match.group(1)


def cut(text: str, name: str) -> tuple[str, str, str]:
    """Split a template on its BEGIN/END markers: (before, inner, after)."""
    begin, end = f"<!-- BEGIN {name} -->", f"<!-- END {name} -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise TemplateError(
            f"the report template must carry exactly one {begin} and one {end}; "
            f"found {text.count(begin)} and {text.count(end)}")
    head, rest = text.split(begin, 1)
    inner, tail = rest.split(end, 1)
    return head, inner, tail


def fill(template: str, values: dict[str, str], where: str) -> str:
    """Substitute every `{{NAME}}`. An unknown name is an error, never an empty cell."""
    def one(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise TemplateError(f"{where}: the template asks for {{{{{name}}}}}, which "
                                f"this renderer does not fill")
        return values[name]
    return _PLACEHOLDER.sub(one, template)


def esc(value: Any) -> str:
    """Every ledger string reaching the report passes through here (AC-C2)."""
    return html.escape("" if value is None else str(value), quote=True)


def block_source(source_lines: Sequence[str], block: dict) -> str:
    lines_ = block.get("lines") or [1, 1]
    try:
        start, end = int(lines_[0]), int(lines_[1])
    except (TypeError, ValueError):
        return ""
    start = max(start, 1)
    end = min(end, len(source_lines))
    if end < start:
        return ""
    return "\n".join(source_lines[start - 1:end])


def render_html(view: View, source_lines: Sequence[str], template_path: Path) -> str:
    template = read_template(template_path)

    shell, card_template, shell_tail = cut(template, "BLOCK_CARD")
    shell = shell + "\x00CARDS\x00" + shell_tail
    shell, assumption_row, shell_tail = cut(shell, "ASSUMPTION_ROW")
    shell = shell + "\x00ASSUMPTIONS\x00" + shell_tail
    shell, question_row, shell_tail = cut(shell, "OPEN_QUESTION_ROW")
    shell = shell + "\x00QUESTIONS\x00" + shell_tail

    cards = [render_card(b, view, source_lines, card_template) for b in view.blocks]

    rows: list[str] = []
    for a in view.export:
        rows.append(fill(assumption_row, {
            "ASSUMPTION_BLOCK": esc(a.get("block_id")),
            "ASSUMPTION_TEXT": esc(a.get("assumption")),
            "ASSUMPTION_STATED_BY": esc(a.get("stated_by")),
            "ASSUMPTION_CONFIRMED": "yes" if a.get("confirmed") else "no",
        }, "ASSUMPTION_ROW"))
    if not rows:  # WRR-4: the section stays, with an explicit empty state.
        rows.append(fill(assumption_row, {
            "ASSUMPTION_BLOCK": EM_DASH,
            "ASSUMPTION_TEXT": NONE_RECORDED,
            "ASSUMPTION_STATED_BY": EM_DASH,
            "ASSUMPTION_CONFIRMED": EM_DASH,
        }, "ASSUMPTION_ROW"))

    questions: list[str] = []
    for q in view.opens:
        questions.append(fill(question_row, {
            "QUESTION_BLOCK": esc(q.get("block_id")),
            "QUESTION_TEXT": esc(q.get("question")),
            "QUESTION_BLOCKED_ON": esc(q.get("blocked_on")),
        }, "OPEN_QUESTION_ROW"))
    if not questions:
        questions.append(fill(question_row, {
            "QUESTION_BLOCK": EM_DASH,
            "QUESTION_TEXT": NONE_RECORDED,
            "QUESTION_BLOCKED_ON": EM_DASH,
        }, "OPEN_QUESTION_ROW"))

    n = view.n or 1
    pct_discussed = round(100 * len(view.discussed) / n)
    pct_fastfwd = (100 - pct_discussed if not view.unanswered
                   else round(100 * len(view.fast_forwarded) / n))
    actionable = len(view.by_disposition("needs-change"))
    blocked = len(view.by_disposition("unresolved"))
    ledger_rel = repo_relative(view.path)
    document = fill(shell, {
        "SCRIPT_NAME": esc(Path(view.script.get("path", "")).name),
        "SCRIPT_PATH": esc(view.script.get("path", "")),
        "PROJECT_ID": esc(view.project.get("id", "")),
        "SESSION_DATE": esc(view.session.get("created", "")),
        "REVIEWER_LIST": esc(", ".join(view.reviewers) or NONE_RECORDED),
        "LANGUAGE": esc(view.script.get("language", "")),
        "BLOCK_COUNT": str(view.n),
        "COVERAGE_MODE": esc(view.session.get("mode", "ordered")),
        "EXECUTIVE_SUMMARY_TEXT": esc(view.summary()),
        "COUNT_NEEDS_CHANGE": str(actionable),
        "COUNT_UNRESOLVED": str(blocked),
        "COUNT_MISREAD": str(len(view.by_disposition("misread-by-agent"))),
        "COUNT_CONFIRMED": str(len(view.by_disposition("confirmed"))),
        "COUNT_DISCUSSED": str(len(view.discussed)),
        "COUNT_FASTFWD": str(len(view.fast_forwarded)),
        "PCT_DISCUSSED": str(pct_discussed),
        "PCT_FASTFWD": str(pct_fastfwd),
        "WORK_ORDER_SUMMARY": f"{actionable} actionable item"
                              f"{'' if actionable == 1 else 's'} and {blocked} blocked "
                              f"item{'' if blocked == 1 else 's'}.",
        "WORK_ORDER_PATH": esc(repo_relative(view.path.parent / "work-order.md")),
        "LEDGER_PATH": esc(ledger_rel),
    }, "report body")

    document = (document
                .replace("\x00CARDS\x00", "".join(cards))
                .replace("\x00ASSUMPTIONS\x00", "".join(rows))
                .replace("\x00QUESTIONS\x00", "".join(questions)))
    return finish(document)


def render_card(block: dict, view: View, source_lines: Sequence[str],
                card_template: str) -> str:
    pred = block.get("prediction") or {}
    acct = block.get("author_account") or {}
    div = block.get("divergence") or {}

    card = card_template
    head, drift_markup, tail = cut(card, "DRIFT_FLAG")
    if block.get("drift"):  # WR-A3/A4: the persisted flag, never a fresh computation.
        note = ("The block already carried a disposition when it changed, which is the "
                "WR-A4 regression signal."
                if block.get("drift_after_disposition")
                else "The block carried no disposition when it changed.")
        drift = fill(drift_markup, {
            "RECORDED_LINES": esc(line_range(block)),
            "DRIFT_REGRESSION_NOTE": note,
        }, f"DRIFT_FLAG ({block.get('block_id')})")
    else:
        drift = ""
    card = head + drift + tail

    head, author_markup, tail = cut(card, "AUTHOR_PANE")
    if block.get("discussed"):
        # Every discussed block gets the pane, endorsement included: an endorsement is an
        # answer (WR-Q7), and dropping the pane would put a discussed block's card in the
        # same shape as a fast-forwarded one.
        endorsed_only = not acct and block.get("endorsed_prediction")
        meant = esc(acct.get("meant_to_do"))
        why = esc(acct.get("why_this_way"))
        if endorsed_only:
            meant = meant or ("Endorsed the recorded prediction without amendment "
                              "(WR-Q7).")
            why = why or EM_DASH
        author = fill(author_markup, {
            "AUTHOR_MEANT_TO_DO": meant or NONE_RECORDED,
            "AUTHOR_WHY_THIS_WAY": why or NONE_RECORDED,
        }, f"AUTHOR_PANE ({block.get('block_id')})")
    else:
        author = ""  # WRR-2: no author pane for a block nobody discussed.
    card = head + author + tail

    carried = [a for a in (acct.get("assumptions_carried") or []) if str(a).strip()]
    if not carried and block.get("endorsed_prediction"):
        # WR-Q8: an endorsement carries the prediction's own assumptions forward.
        carried = [a for a in (pred.get("assumptions") or []) if str(a).strip()]
    items = "".join(f"<li>{esc(a)}</li>" for a in carried) or f"<li>{NONE_RECORDED}</li>"

    disposition = block.get("disposition") or ""
    match = div.get("match")
    return fill(card, {
        "DISPOSITION_CLASS": _DISPOSITION_CLASS.get(disposition, "unanswered"),
        "BLOCK_ID": esc(block.get("block_id")),
        "BLOCK_TITLE": esc(block.get("title")),
        "FILE_PATH": esc(view.script.get("path", "")),
        "LINE_RANGE": esc(line_range(block)),
        "DENSITY": esc(block.get("density")),
        "DISCUSSED_LABEL": ("discussed" if block.get("discussed")
                            else "fast-forwarded" if block.get("disposition")
                            else "not answered"),
        "DISPOSITION_LABEL": esc(disposition or "not answered"),
        "BLOCK_SOURCE": esc(block_source(source_lines, block)),
        "PREDICTION_CONFIDENCE": esc(pred.get("confidence")),
        "PREDICTION_WHAT_IT_DOES": esc(pred.get("what_it_does")),
        "PREDICTION_INFERRED_INTENT": esc(pred.get("inferred_intent")),
        "MATCH_CLASS": "match" if match is True else "",
        "DIVERGENCE_TYPE": esc(div.get("type") or ("match" if match else "not reconciled")),
        "DIVERGENCE_DETAIL": esc(div.get("detail")) or "No divergence recorded yet.",
        "ASSUMPTION_ITEMS": items,
    }, f"BLOCK_CARD ({block.get('block_id')})")


def finish(document: str) -> str:
    """Strip the marker comments and refuse a document with an unfilled placeholder."""
    document = re.sub(r"[ \t]*<!-- (?:BEGIN|END) [A-Z0-9_]+ -->\n?", "", document)
    stripped = _COMMENT.sub("", document)
    leftover = sorted(set(_PLACEHOLDER.findall(stripped)))
    if leftover or "{{" in stripped:
        raise TemplateError(f"unfilled placeholder(s) in the rendered report: "
                            f"{', '.join(leftover) or '{{'}")
    return document


# --------------------------------------------------------------------------- entry point
def write(path: Path, text: str) -> None:
    """LF, UTF-8, no trailing surprise: the same bytes every time (AC-C3)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="war_room_render.py",
        description="Render ledger.md and the HTML report from a war-room ledger.")
    sub = ap.add_subparsers(dest="command", required=True)

    md = sub.add_parser("md", help="Render ledger.md")
    md.add_argument("ledger")
    md.add_argument("--out", required=True)
    md.add_argument("--project-root", default=None,
                    help="Root of the reviewed project. Optional here: only lint's "
                         "source-reading checks use it, and they are skipped with a "
                         "warning when it cannot be resolved.")

    ht = sub.add_parser("html", help="Render the HTML report")
    ht.add_argument("ledger")
    ht.add_argument("--project-root", default=None,
                    help="Root of the reviewed project (the directory holding PROJECT.md). "
                         "Required in practice: the report quotes the reviewed source.")
    ht.add_argument("--out", required=True)
    ht.add_argument("--template", default=str(DEFAULT_TEMPLATE),
                    help="The report template to read the HTML out of. Defaults to "
                         "Infrastructure/templates/war-room-report.md.")

    args = ap.parse_args(list(argv) if argv is not None else None)

    ledger_path = Path(args.ledger).expanduser().resolve()
    if not ledger_path.is_file():
        print(f"No ledger at {ledger_path}")
        return 2
    root = Path(args.project_root) if args.project_root else None
    ledger = wr.load_ledger(ledger_path)
    if root is not None:
        # D1/WR-A5: an explicit root that names a different project describes different
        # code. Prep and the server refuse it; so does every renderer.
        try:
            wr.resolve_project_root(root, ledger)
        except wr.WarRoomError as exc:
            print(f"ERROR: {exc}")
            return 2
    lint_gate(ledger, ledger_path, root)
    view = View(ledger, ledger_path)

    if args.command == "md":
        write(Path(args.out), render_md(view))
        print(f"Wrote {args.out} ({view.n} blocks)")
        return 0

    try:
        source_lines = wr.wr_a1_lines(wr.resolve_script(wr.resolve_project_root(root, ledger),
                                                         ledger))
    except wr.WarRoomError as exc:
        print(f"ERROR: {exc}")
        return 2
    try:
        document = render_html(view, source_lines, Path(args.template))
    except TemplateError as exc:
        print(f"ERROR: {exc}")
        return 1
    write(Path(args.out), document)
    print(f"Wrote {args.out} ({view.n} blocks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
