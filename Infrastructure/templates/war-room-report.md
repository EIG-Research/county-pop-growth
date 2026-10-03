# War Room Report — HTML Template

Defines the HTML report rendered from a war-room ledger. Replace all `{{PLACEHOLDER}}`
tokens with actual content and escape user-derived strings for HTML.

**Location:** `<target-dir>/review-reports/war-room/<script-slug>-war-room.html`

**This report is disposable.** `records/war_rooms/<slug>/ledger.yaml` is the source of
truth (WR-O1); this file is regenerated from it and is gitignored along with the rest of
`review-reports/`. The ledger directory is undated and namespaced by project (WR-X2). Never
edit the HTML to correct a finding — correct the ledger and re-render.

---

## Pre-Write Checklist

- [ ] All `{{PLACEHOLDER}}` tokens replaced (grep for `{{` — none should remain)
- [ ] User-supplied strings HTML-escaped (`<` → `&lt;`, `>` → `&gt;`, `&` → `&amp;`, `"` → `&quot;`)
- [ ] Every block in the ledger appears, in file order, discussed and fast-forwarded alike
- [ ] Disposition counts in the stat grid match the block entries below
- [ ] Each discussed block shows the agent prediction **above** the author account, preserving the protocol order
- [ ] Predictions render exactly as recorded in the ledger — never re-worded at render time (WR-P3)
- [ ] Code blocks use `<pre><code>` tags
- [ ] Report is self-contained (no external CSS/JS)

---

## HTML Template

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>War Room — {{SCRIPT_NAME}}</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 15px; line-height: 1.6; color: #1e293b; background: #f8fafc;
    }

    .report-header { background: #1e293b; color: #f1f5f9; padding: 2rem 2.5rem; }
    .report-header h1 { font-size: 1.6rem; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 0.25rem; }
    .report-header .subtitle { font-size: 0.9rem; color: #94a3b8; font-family: monospace; }
    .report-header .meta { margin-top: 1rem; display: flex; flex-wrap: wrap; gap: 2rem; font-size: 0.85rem; color: #cbd5e1; }
    .report-header .meta span strong { color: #f1f5f9; }

    .container { max-width: 960px; margin: 0 auto; padding: 2rem 1.5rem; }

    h2 {
      font-size: 1.15rem; font-weight: 600; color: #1e293b;
      margin: 2rem 0 1rem; padding-bottom: 0.4rem; border-bottom: 2px solid #e2e8f0;
    }

    .summary-box {
      background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
      padding: 1.25rem 1.5rem; margin-bottom: 1.5rem;
      font-size: 0.95rem; color: #334155; line-height: 1.7;
    }

    /* ── Disposition stat grid ── */
    .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; margin-bottom: 2rem; }
    .stat-card {
      background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
      padding: 1rem; text-align: center;
    }
    .stat-card .count { font-size: 2rem; font-weight: 700; line-height: 1; }
    .stat-card .label {
      font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.05em; margin-top: 0.3rem;
    }
    .disp-needs-change .count, .disp-needs-change .label { color: #ea580c; }
    .disp-unresolved   .count, .disp-unresolved   .label { color: #ca8a04; }
    .disp-misread      .count, .disp-misread      .label { color: #7c3aed; }
    .disp-confirmed    .count, .disp-confirmed    .label { color: #16a34a; }

    /* ── Coverage bar ── */
    .coverage { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 2rem; }
    .coverage-label { font-size: 0.8rem; color: #64748b; margin-bottom: 0.5rem; }
    .coverage-track { height: 10px; border-radius: 5px; background: #e2e8f0; overflow: hidden; display: flex; }
    .coverage-discussed { background: #2563eb; }
    .coverage-fastfwd  { background: #cbd5e1; }

    /* ── Block cards ── */
    .block { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 1.25rem; overflow: hidden; }
    .block-header { display: flex; align-items: flex-start; gap: 1rem; padding: 1rem 1.25rem; border-left: 5px solid transparent; }
    .block.needs-change .block-header { border-left-color: #ea580c; }
    .block.unresolved   .block-header { border-left-color: #ca8a04; }
    .block.misread      .block-header { border-left-color: #7c3aed; }
    .block.confirmed    .block-header { border-left-color: #16a34a; }

    .block-id { font-size: 0.75rem; font-weight: 700; font-family: monospace; color: #64748b; min-width: 3.5rem; padding-top: 0.15rem; }
    .block-title-block { flex: 1; }
    .block-title { font-weight: 600; font-size: 1rem; color: #1e293b; }
    .block-meta { font-size: 0.8rem; color: #64748b; margin-top: 0.2rem; }
    .block-meta .file { font-family: monospace; }

    .disp-badge {
      font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.06em; padding: 0.2rem 0.55rem; border-radius: 4px; white-space: nowrap;
    }
    .badge-needs-change { background: #fff7ed; color: #ea580c; }
    .badge-unresolved   { background: #fefce8; color: #ca8a04; }
    .badge-misread      { background: #f5f3ff; color: #7c3aed; }
    .badge-confirmed    { background: #f0fdf4; color: #16a34a; }

    .density-badge { font-size: 0.68rem; font-weight: 600; color: #64748b; background: #f1f5f9; padding: 0.15rem 0.45rem; border-radius: 4px; }

    .block-body { padding: 0 1.25rem 1.25rem 2.75rem; }
    .section-label {
      font-size: 0.75rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.07em; color: #94a3b8; margin: 0.85rem 0 0.35rem;
    }
    .block-text { font-size: 0.9rem; color: #334155; }

    /* ── The prediction/account pair: order is the protocol ── */
    .protocol-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-top: 0.5rem; }
    .pane { border: 1px solid #e2e8f0; border-radius: 6px; padding: 0.85rem 1rem; }
    .pane.prediction { background: #f8fafc; }
    .pane.account { background: #fff; }
    .pane-label { font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: #64748b; margin-bottom: 0.4rem; }
    .pane .conf { font-size: 0.7rem; color: #94a3b8; font-weight: 500; }

    .divergence { border-left: 3px solid #ea580c; background: #fff7ed; padding: 0.75rem 1rem; border-radius: 0 6px 6px 0; margin-top: 0.85rem; }
    .divergence.match { border-left-color: #16a34a; background: #f0fdf4; }
    .divergence-type { font-size: 0.7rem; font-weight: 700; font-family: monospace; color: #9a3412; text-transform: uppercase; }
    .divergence.match .divergence-type { color: #15803d; }

    .verbatim { font-style: italic; color: #475569; border-left: 2px solid #cbd5e1; padding-left: 0.8rem; margin-top: 0.3rem; }

    ul.assumptions { margin: 0.3rem 0 0 1.1rem; font-size: 0.9rem; color: #334155; }
    ul.assumptions li { margin-bottom: 0.25rem; }

    pre { background: #0f172a; color: #e2e8f0; border-radius: 6px; padding: 0.85rem 1rem; overflow-x: auto; margin-top: 0.4rem; }
    pre code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.82rem; line-height: 1.5; }

    table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; font-size: 0.87rem; }
    th { background: #f1f5f9; text-align: left; padding: 0.6rem 0.85rem; font-weight: 600; color: #475569; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }
    td { padding: 0.6rem 0.85rem; border-top: 1px solid #e2e8f0; color: #334155; }
    td.file { font-family: monospace; font-size: 0.82rem; }

    .drift-flag { background: #fef2f2; border: 1px solid #fecaca; color: #b91c1c; border-radius: 6px; padding: 0.6rem 0.9rem; font-size: 0.85rem; margin-top: 0.6rem; }

    .footer { text-align: center; color: #94a3b8; font-size: 0.8rem; padding: 2rem 0 1rem; }

    @media (max-width: 720px) {
      .stat-grid { grid-template-columns: repeat(2, 1fr); }
      .protocol-pair { grid-template-columns: 1fr; }
      .block-body { padding-left: 1.25rem; }
    }
  </style>
</head>
<body>
  <div class="report-header">
    <h1>War Room Walkthrough</h1>
    <div class="subtitle">{{SCRIPT_PATH}}</div>
    <div class="meta">
      <span>project: <strong>{{PROJECT_ID}}</strong></span>
      <span><strong>{{SESSION_DATE}}</strong> session</span>
      <span><strong>{{REVIEWER_LIST}}</strong></span>
      <span><strong>{{LANGUAGE}}</strong></span>
      <span><strong>{{BLOCK_COUNT}}</strong> blocks</span>
      <span>mode: <strong>{{COVERAGE_MODE}}</strong></span>
    </div>
  </div>

  <div class="container">

    <h2>Summary</h2>
    <div class="summary-box">{{EXECUTIVE_SUMMARY_TEXT}}</div>

    <div class="stat-grid">
      <div class="stat-card disp-needs-change"><div class="count">{{COUNT_NEEDS_CHANGE}}</div><div class="label">Needs change</div></div>
      <div class="stat-card disp-unresolved"><div class="count">{{COUNT_UNRESOLVED}}</div><div class="label">Unresolved</div></div>
      <div class="stat-card disp-misread"><div class="count">{{COUNT_MISREAD}}</div><div class="label">Agent misread</div></div>
      <div class="stat-card disp-confirmed"><div class="count">{{COUNT_CONFIRMED}}</div><div class="label">Confirmed</div></div>
    </div>

    <div class="coverage">
      <div class="coverage-label">{{COUNT_DISCUSSED}} discussed &middot; {{COUNT_FASTFWD}} fast-forwarded &middot; {{BLOCK_COUNT}} total</div>
      <div class="coverage-track">
        <div class="coverage-discussed" style="width: {{PCT_DISCUSSED}}%"></div>
        <div class="coverage-fastfwd" style="width: {{PCT_FASTFWD}}%"></div>
      </div>
    </div>

    <!-- ══ Blocks, in file order. The renderer repeats everything between the
         BLOCK_CARD markers once per block and strips the markers. ══ -->
    <h2>Blocks</h2>

    <!-- BEGIN BLOCK_CARD -->
    <div class="block {{DISPOSITION_CLASS}}">
      <div class="block-header">
        <div class="block-id">{{BLOCK_ID}}</div>
        <div class="block-title-block">
          <div class="block-title">{{BLOCK_TITLE}}</div>
          <div class="block-meta">
            <span class="file">{{FILE_PATH}}:{{LINE_RANGE}}</span>
            &middot; <span class="density-badge">density: {{DENSITY}}</span>
            &middot; {{DISCUSSED_LABEL}}
          </div>
        </div>
        <span class="disp-badge badge-{{DISPOSITION_CLASS}}">{{DISPOSITION_LABEL}}</span>
      </div>

      <div class="block-body">
        <pre><code>{{BLOCK_SOURCE}}</code></pre>

        <!-- BEGIN DRIFT_FLAG -->
        <div class="drift-flag"><strong>Drift:</strong> the source at the recorded lines
          {{RECORDED_LINES}} no longer matches the hash recorded for this block.
          {{DRIFT_REGRESSION_NOTE}} The decision below may no longer describe this code.</div>
        <!-- END DRIFT_FLAG -->

        <div class="protocol-pair">
          <div class="pane prediction">
            <div class="pane-label">Agent read it as <span class="conf">({{PREDICTION_CONFIDENCE}} confidence)</span></div>
            <div class="block-text">{{PREDICTION_WHAT_IT_DOES}}</div>
            <div class="section-label">Inferred intent</div>
            <div class="block-text">{{PREDICTION_INFERRED_INTENT}}</div>
          </div>
          <!-- BEGIN AUTHOR_PANE -->
          <div class="pane account">
            <div class="pane-label">Author said</div>
            <div class="block-text">{{AUTHOR_MEANT_TO_DO}}</div>
            <div class="section-label">Why this way</div>
            <div class="verbatim">{{AUTHOR_WHY_THIS_WAY}}</div>
          </div>
          <!-- END AUTHOR_PANE -->
        </div>

        <div class="divergence {{MATCH_CLASS}}">
          <div class="divergence-type">{{DIVERGENCE_TYPE}}</div>
          <div class="block-text">{{DIVERGENCE_DETAIL}}</div>
        </div>

        <div class="section-label">Assumptions carried forward</div>
        <ul class="assumptions">{{ASSUMPTION_ITEMS}}</ul>
      </div>
    </div>
    <!-- END BLOCK_CARD -->

    <h2>Assumptions Carried Forward</h2>
    <table>
      <thead><tr><th>Block</th><th>Assumption</th><th>Stated by</th><th>Confirmed</th></tr></thead>
      <tbody>
        <!-- BEGIN ASSUMPTION_ROW -->
        <tr><td>{{ASSUMPTION_BLOCK}}</td><td>{{ASSUMPTION_TEXT}}</td><td>{{ASSUMPTION_STATED_BY}}</td><td>{{ASSUMPTION_CONFIRMED}}</td></tr>
        <!-- END ASSUMPTION_ROW -->
      </tbody>
    </table>

    <h2>Open Questions</h2>
    <table>
      <thead><tr><th>Block</th><th>Question</th><th>Blocked on</th></tr></thead>
      <tbody>
        <!-- BEGIN OPEN_QUESTION_ROW -->
        <tr><td>{{QUESTION_BLOCK}}</td><td>{{QUESTION_TEXT}}</td><td>{{QUESTION_BLOCKED_ON}}</td></tr>
        <!-- END OPEN_QUESTION_ROW -->
      </tbody>
    </table>

    <h2>Work Order</h2>
    <div class="summary-box">
      {{WORK_ORDER_SUMMARY}}
      Full handoff: <code>{{WORK_ORDER_PATH}}</code>
    </div>

    <div class="footer">
      Rendered from <code>{{LEDGER_PATH}}</code> &middot; regenerate rather than edit this file.
    </div>
  </div>
</body>
</html>
```

---

## Placeholder Reference

| Placeholder | Source in `ledger.yaml` |
|---|---|
| `{{SCRIPT_PATH}}`, `{{SCRIPT_NAME}}`, `{{LANGUAGE}}` | `script.*` |
| `{{PROJECT_ID}}` | `project.id` |
| `{{SESSION_DATE}}`, `{{COVERAGE_MODE}}` | `session.created`, `session.mode` |
| `{{REVIEWER_LIST}}` | `session.reviewers[].id`, comma-joined |
| `{{BLOCK_COUNT}}`, `{{COUNT_DISCUSSED}}`, `{{COUNT_FASTFWD}}` | derived from `blocks` |
| `{{PCT_DISCUSSED}}`, `{{PCT_FASTFWD}}` | integer percentages summing to 100 |
| `{{COUNT_NEEDS_CHANGE}}`, `{{COUNT_UNRESOLVED}}`, `{{COUNT_MISREAD}}`, `{{COUNT_CONFIRMED}}` | disposition tallies |
| `{{BLOCK_ID}}`, `{{BLOCK_TITLE}}`, `{{FILE_PATH}}`, `{{LINE_RANGE}}`, `{{DENSITY}}` | per-block fields |
| `{{DISCUSSED_LABEL}}` | `discussed`, rendered as "discussed" or "fast-forwarded" |
| `{{DISPOSITION_CLASS}}` | `needs-change` \| `unresolved` \| `misread` \| `confirmed` |
| `{{DISPOSITION_LABEL}}` | human-readable disposition |
| `{{BLOCK_SOURCE}}` | the block's source text, HTML-escaped |
| `{{PREDICTION_*}}` | `prediction.*` — rendered verbatim, never re-worded |
| `{{AUTHOR_*}}` | `author_account.*`; the AUTHOR pane is omitted when `discussed: false`, while the prediction pane always renders (WRR-2) |
| `{{MATCH_CLASS}}` | `match` when `divergence.match` is true, otherwise empty |
| `{{DIVERGENCE_TYPE}}`, `{{DIVERGENCE_DETAIL}}` | `divergence.*` |
| `{{ASSUMPTION_ITEMS}}` | `<li>` per entry in `author_account.assumptions_carried` |
| `{{RECORDED_LINES}}`, `{{DRIFT_REGRESSION_NOTE}}` | inside `DRIFT_FLAG`: the block's recorded `lines`, and a sentence naming whether `drift_after_disposition` is set (WR-A4). Both read the persisted flags; drift is never recomputed at render time |
| `{{ASSUMPTION_BLOCK}}`, `{{ASSUMPTION_TEXT}}`, `{{ASSUMPTION_STATED_BY}}`, `{{ASSUMPTION_CONFIRMED}}` | inside `ASSUMPTION_ROW`: one `assumption_export` item |
| `{{QUESTION_BLOCK}}`, `{{QUESTION_TEXT}}`, `{{QUESTION_BLOCKED_ON}}` | inside `OPEN_QUESTION_ROW`: one `open_questions` item |
| `{{WORK_ORDER_SUMMARY}}`, `{{WORK_ORDER_PATH}}`, `{{LEDGER_PATH}}` | counts and paths |

**Repeat markers.** `Infrastructure/scripts/war_room_render.py` reads this fenced block at run time and repeats the region between each `<!-- BEGIN NAME -->` / `<!-- END NAME -->` pair: `BLOCK_CARD` once per block in file order, `ASSUMPTION_ROW` once per `assumption_export` item, `OPEN_QUESTION_ROW` once per `open_questions` item. `DRIFT_FLAG` is emitted only when the block carries `drift: true`, and `AUTHOR_PANE` is dropped for a block that was not discussed (WRR-2). Empty tables render one row with an explicit empty state rather than disappearing (WRR-4). The renderer strips every marker comment from the output, refuses a placeholder it does not fill, and refuses a rendered document that still contains `{{`. The placeholder table above is documentation and is not parsed.

## Rendering Rules

**WRR-1 — Prediction pane renders left, author pane right.** The visual order carries the
protocol: the agent committed first. Do not reorder, and do not collapse the two into one
pane even when they agree.

**WRR-2 — Fast-forwarded blocks render with the prediction pane only**, plus their
disposition. Do not fabricate an author account for a block nobody discussed.

**WRR-3 — Render predictions verbatim from the ledger.** Tidying the wording at render time
re-opens the drift that WR-P2 exists to prevent.

**WRR-4 — Empty sections stay, with an explicit empty state.** A report with no open
questions shows the table with a "None recorded" row rather than dropping the section, so a
reader can tell the difference between "nothing found" and "not checked".
