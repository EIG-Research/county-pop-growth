"use strict";
// Code war room client, served by war_room_server.py.
//
// Every element is built with createElement and textContent, and every handler is attached
// with addEventListener. Ledger text is model-authored from untrusted code comments, and the
// source is untrusted too, so nothing in this file turns a string into markup or script
// (census D-14): a quote, an apostrophe, or a tag in any field renders as the characters it
// is. The server decides endorsement (WR-Q7); this client only asks.

let S = null;
let cur = 0;
let dirty = false;
let screen = "reviewer";
// The disposition and the endorsement the author has picked but not yet saved. They are
// kept apart from S.blocks[cur] on purpose: the sidebar and the block map render the
// ledger as the server holds it, so an unsaved pick never appears anywhere as recorded.
let pendingDisp = "";
let pendingEndorse = false;

// Per-viewer conveniences only; the page works without them.
const prefs = {
  get(key) { try { return window.localStorage.getItem(key) || ""; } catch { return ""; } },
  set(key, value) { try { window.localStorage.setItem(key, value); } catch { /* optional */ } },
};

// WR-Q9: identity carried over from prep is not the reviewer. Without an id *and* a role
// on every answer, two people's entries both claim the same author and the multi-reviewer
// merge story in WR-O6 is fiction.
let REVIEWER = prefs.get("warroom.reviewer");
let ROLE = prefs.get("warroom.role");
let ROLES = ["author", "fresh-eyes"];

// ------------------------------------------------------------------ DOM helpers
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function byId(id) { return document.getElementById(id); }
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function fill(node, ...children) { clear(node); for (const c of children) if (c) node.append(c); }
function range(b) { return `${b.lines[0]}–${b.lines[1]}`; }

async function api(path, body) {
  const res = await fetch(path, body === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
}

function reviewerReady() { return !!REVIEWER && ROLES.includes(ROLE); }

// ------------------------------------------------------------------ reviewer form
// An in-page form, not `prompt()`: a dialog that is suppressed or unsupported returns
// null, and a loop that re-asked on null spun forever with the page frozen. The form stays
// up until both fields are valid, and nothing else in the app runs until it is done.
function renderReviewerForm(message) {
  screen = "reviewer";
  clear(byId("list"));
  byId("hwho").textContent = "";
  const id = el("input", { type: "text", id: "rv-id", autocomplete: "off" });
  id.value = REVIEWER;
  const role = el("select", { id: "rv-role" },
    ...ROLES.map((r) => el("option", { value: r, selected: r === ROLE, text: r })));
  const form = el("form", { id: "reviewer-form", onsubmit: submitReviewer },
    el("h2", { text: "Who is answering?" }),
    el("div", { class: "note", text: "Every saved answer records a reviewer id and a role " +
      "(WR-Q9). Identity carried over from prep is not the reviewer: without this, two " +
      "people's entries both claim the same author." }),
    el("label", { for: "rv-id", text: "Reviewer id" }), id,
    el("label", { for: "rv-role", text: "Role for this session" }), role,
    el("div", { class: "foot" },
      el("button", { class: "btn p", type: "submit", text: "Start" }),
      el("span", { class: "status err", id: "rv-err", text: message || "" })));
  fill(byId("main"), form);
  id.focus();
}

function submitReviewer(ev) {
  ev.preventDefault();
  const id = byId("rv-id").value.trim();
  const role = byId("rv-role").value.trim();
  if (!id) return renderReviewerForm("a reviewer id is required");
  if (!ROLES.includes(role)) return renderReviewerForm(`role must be one of ${ROLES.join(" or ")}`);
  REVIEWER = id;
  ROLE = role;
  prefs.set("warroom.reviewer", REVIEWER);
  prefs.set("warroom.role", ROLE);
  load();
}

// ------------------------------------------------------------------ state
async function load() {
  S = await api("/api/state");
  if (S.reviewer_roles && S.reviewer_roles.length) ROLES = S.reviewer_roles;
  if (!reviewerReady()) return renderReviewerForm();
  byId("hwho").textContent = `${REVIEWER} · ${ROLE}`;
  byId("hpath").textContent = S.script.path || "";
  const first = S.blocks.findIndex((b) => !b.disposition);
  cur = first === -1 ? 0 : first;
  // Spec M27 / D5: the block map comes before the first unanswered block, in every mode.
  screen = S.needs_block_map ? "map" : "block";
  render();
}

function progress() {
  const done = S.blocks.filter((b) => b.disposition).length;
  byId("hprog").textContent =
    `block ${Math.min(cur + 1, S.blocks.length)} of ${S.blocks.length} · ${done} dispositioned`;
  byId("hbar").style.width = `${S.blocks.length ? (100 * done) / S.blocks.length : 0}%`;
}

function densityClass(d) { return ["high", "medium", "low"].includes(d) ? `d-${d}` : ""; }

function renderList() {
  const items = [el("div", { class: `bitem ${screen === "map" ? "on" : ""}`, onclick: showMap },
    el("span", { class: "dot" }), el("span", { class: "id", text: "map" }),
    el("span", { class: "t" }, "Block map",
      el("div", { class: "ln", text: `${S.blocks.length} blocks · ${S.session.mode}` })))];
  S.blocks.forEach((b, i) => {
    const meta = `${range(b)} · ${b.density}${b.flagged ? " · ⚑" : ""}${b.drift ? " · drift" : ""}`;
    items.push(el("div", { class: `bitem ${screen === "block" && i === cur ? "on" : ""}`,
                           onclick: () => go(i) },
      el("span", { class: `dot ${S.dispositions.includes(b.disposition) ? b.disposition : ""}` }),
      el("span", { class: "id", text: b.block_id }),
      el("span", { class: "t" }, b.title, el("div", { class: `ln ${densityClass(b.density)}`, text: meta }))));
  });
  fill(byId("list"), ...items);
}

function numbered(src, start) {
  const code = el("code");
  src.split("\n").forEach((line, i) => {
    if (i) code.append("\n");
    code.append(el("span", { class: "ln-no", text: `${String(start + i).padStart(4)} │ ` }), line);
  });
  return el("pre", {}, code);
}

// ------------------------------------------------------------------ block map
function ffEligible(b) {
  // WR-C4: never a high-density block, never a low-confidence prediction. The server
  // refuses these too; pre-selecting them here would just teach the author to expect it.
  return !b.disposition && b.density === "low" && b.prediction.confidence !== "low";
}

function segControls(b) {
  const at = el("input", { type: "text", placeholder: String(b.lines[0] + 1),
                           "aria-label": `split ${b.block_id} at line` });
  return { at, merge: () => seg("merge", b.block_id), split: () => seg("split", b.block_id, at.value) };
}

function renderMap() {
  progress();
  renderList();
  const ff = S.session.mode === "fast-forward";
  const boxes = [];
  const rows = S.blocks.map((b) => {
    const c = segControls(b);
    const cells = [];
    if (ff) {
      const box = el("input", { type: "checkbox", class: "ffbox", checked: ffEligible(b),
                                disabled: !!b.disposition });
      box.dataset.b = b.block_id;
      boxes.push(box);
      cells.push(el("td", {}, box));
    }
    cells.push(el("td", { class: "id", text: b.block_id }), el("td", { class: "num", text: range(b) }),
      el("td", { text: b.title }), el("td", { class: densityClass(b.density), text: b.density }),
      el("td", { text: b.prediction.confidence }), el("td", { text: b.disposition || "—" }),
      el("td", { class: "mapacts" },
        el("button", { type: "button", onclick: c.merge, text: "merge with next" }), c.at,
        el("button", { type: "button", onclick: c.split, text: "split" })));
    return el("tr", {}, ...cells);
  });
  const heads = [...(ff ? ["ff"] : []), "id", "lines", "title", "density", "confidence",
                 "disposition", "re-segment"];
  const ffStat = el("span", { class: "status", id: "ffstat" });
  const selector = ff ? el("div", { id: "fast-forward-selector" },
    el("div", { class: "ffhead", text: "Fast-forward: batch-confirm mechanical blocks" }),
    el("div", { class: "warn ffwarn", text: "Pre-selected: density low with prediction " +
      "confidence above low (WR-C4, WR-C5). Deselect anything you want to walk through. A " +
      "batch-confirmed block is recorded, not skipped: it keeps its prediction, is marked " +
      "discussed: false, and the confirmation endorses the prediction's assumptions " +
      "(WR-C3, WR-Q8)." }),
    el("button", { class: "btn p", type: "button", text: "Confirm selected blocks",
                   onclick: () => fastForward(boxes, ffStat) }), ffStat) : null;
  fill(byId("main"), el("div", { id: "block-map" },
    el("div", { class: "crumb" }, el("strong", { text: "Block map" }),
      el("span", { class: "tag", text: S.session.mode }),
      el("span", { text: `${S.blocks.length} blocks · ` +
        `${S.blocks.filter((b) => b.disposition).length} dispositioned` })),
    el("h2", { text: "Confirm the segmentation before the walkthrough" }),
    el("div", { class: "note", text: "Segmentation is proposed, not imposed (WR-S5). Merge " +
      "or split anything that is not a unit of intent now — a block that already carries a " +
      "disposition can no longer be re-segmented. A merged or split block's prediction is " +
      "marked inherited and lower-confidence, because the agent committed to the original " +
      "boundaries." }),
    selector,
    el("table", {}, el("thead", {}, el("tr", {}, ...heads.map((h) => el("th", { text: h })))),
      el("tbody", {}, ...rows)),
    el("div", { class: "mapfoot" },
      el("button", { class: "btn p", type: "button", text: "Begin walkthrough",
                     onclick: beginWalkthrough }),
      el("span", { class: "warn", text: "Opens the first block without a disposition." }))));
}

// WR-Q3: the block on screen is the only unsaved state, so every exit from it saves first
// and stays put when the save is refused. Leaving the block with `dirty` set used to drop
// the answer silently while the map and the sidebar drew the disposition as recorded.
async function leaveBlock() {
  if (screen !== "block" || !dirty) return true;
  if (await save()) return true;
  const st = byId("stat");
  if (st) st.textContent += " — staying on this block; nothing was recorded";
  return false;
}

async function showMap() {
  if (!(await leaveBlock())) return;
  screen = "map";
  renderMap();
  window.scrollTo(0, 0);
}

async function beginWalkthrough() {
  if (!(await leaveBlock())) return;
  const first = S.blocks.findIndex((b) => !b.disposition);
  cur = first === -1 ? 0 : first;
  screen = "block";
  render();
  window.scrollTo(0, 0);
}

async function fastForward(boxes, st) {
  const ids = boxes.filter((x) => x.checked && !x.disabled).map((x) => x.dataset.b);
  if (!ids.length) { st.textContent = "nothing selected"; st.className = "status err"; return; }
  st.textContent = "confirming…";
  st.className = "status";
  const r = await api("/api/fast-forward", { block_ids: ids, reviewer: REVIEWER, reviewer_role: ROLE });
  if (!r.ok) { st.textContent = `refused: ${r.error || "?"}`; st.className = "status err"; return; }
  await load();
  showMap();
}

// ------------------------------------------------------------------ one block
function textarea(id, value) {
  const node = el("textarea", { id });
  node.value = value;
  node.addEventListener("input", () => { dirty = true; clearEndorsement(); });
  node.addEventListener("blur", () => { if (dirty) save(); });   // autosave: no silent loss
  return node;
}

function render() {
  if (screen === "map" || !S.blocks.length) return renderMap();
  const b = S.blocks[cur];
  // The screen opens on what the server holds; every later pick edits the pending copy.
  pendingDisp = b.disposition || "";
  pendingEndorse = !!b.endorsed_prediction;
  dirty = false;
  progress();
  renderList();
  const c = segControls(b);
  const pred = b.prediction;
  const drift = b.drift ? el("div", { class: "drift" }, el("strong", { text: "Drift: " }),
    "this block's content no longer matches the hash recorded at prep, and the same content " +
    "was not found elsewhere in the file. The prediction below may describe different code.",
    b.drift_after_disposition ? el("strong", { text: " It changed after this block was " +
      "dispositioned — the decision reached in the room may no longer describe the code (WR-A4)." })
      : null) : null;
  const moved = b.relocated_from ? el("div", { class: "note", text: "Re-anchored by hash: " +
    `this block moved from lines ${b.relocated_from[0]}–${b.relocated_from[1]} to ${range(b)}. ` +
    "Same content, new position (WR-A2)." }) : null;
  const dissent = b.dissent && b.dissent.length ? el("div", { class: "note" },
    el("strong", { text: "Dissent on this block: " }),
    b.dissent.map((d) => `${d.reviewer} (${d.disposition})`).join(", ")) : null;
  const flag = el("input", { type: "checkbox", id: "flag", checked: b.flagged });

  fill(byId("main"),
    el("div", { class: "crumb" }, el("strong", { text: `Block ${cur + 1} of ${S.blocks.length}` }),
      el("span", { class: "tag", text: b.block_id }), el("span", { text: `lines ${range(b)}` }),
      el("span", { class: `tag ${densityClass(b.density)}`, text: `density ${b.density}` }),
      el("button", { class: "btn small", type: "button", text: "block map", onclick: showMap })),
    el("h2", { text: b.title }), drift, moved, numbered(b.source, b.lines[0]),
    // WR-Q4: the prediction is first in reading order, read-only, and the author's fields
    // start empty beside it. Reading order carries the protocol.
    el("div", { class: "cols" },
      el("div", { class: "pane pred" },
        el("div", { class: "plabel" }, el("span", { text: "Agent read it as" }),
          el("span", { class: "conf", text: `${pred.confidence} confidence` })),
        el("div", { class: "ptext", text: pred.what_it_does }),
        el("div", { class: "sub", text: "Inferred intent" }),
        el("div", { class: "ptext", text: pred.inferred_intent }),
        pred.assumptions.length ? el("div", { class: "sub", text: "Assumptions it thinks this carries" }) : null,
        pred.assumptions.length ? el("ul", { class: "as" }, ...pred.assumptions.map((a) => el("li", { text: a }))) : null,
        el("div", { class: "locknote", text: "Recorded before you saw it. Not editable — if " +
          "it is wrong, that is the finding." })),
      el("div", { class: "pane" }, el("div", { class: "plabel" }, el("span", { text: "Your account" })),
        el("label", { for: "meant", text: "What is it meant to do?" }), textarea("meant", b.author.meant_to_do),
        el("label", { for: "why", text: "Why is it done this way?" }), textarea("why", b.author.why_this_way),
        el("label", { for: "carried", text: "What does it assume downstream? (one per line)" }),
        textarea("carried", b.author.assumptions_carried.join("\n")))),
    el("div", { class: "disp" }, ...S.dispositions.map((d, i) => {
      const btn = el("button", { type: "button", class: pendingDisp === d ? "sel" : "",
                                 onclick: () => pick(d) }, d, el("span", { class: "k", text: String(i + 1) }));
      btn.dataset.d = d;
      return btn;
    })),
    el("div", { class: "foot" },
      el("button", { class: "btn", type: "button", disabled: cur === 0, onclick: () => go(cur - 1), text: "← Prev" }),
      el("button", { class: "btn p", type: "button", onclick: saveNext }, "Save & next ",
        el("span", { class: "k", text: "⌘↵" })),
      el("button", { class: "btn", type: "button", disabled: cur === S.blocks.length - 1,
                     onclick: () => go(cur + 1), text: "Skip →" }),
      el("button", { class: "btn", type: "button", onclick: endorse,
                     title: "Record that the prediction is correct and you have nothing to add" },
        "Prediction correct, nothing to add ", el("span", { class: "k", text: "E" })),
      el("span", { class: "endorsed", id: "endorsedflag",
                   text: pendingEndorse ? "endorsed_prediction: true" : "" }),
      el("label", { class: "flagbox" }, flag, " flag for agent follow-up"),
      el("span", { class: "status", id: "stat",
                   text: b.answered_at ? `saved ${b.answered_at} by ${b.reviewer}` : "" })),
    dissent,
    el("details", { class: "seg" }, el("summary", { text: "Adjust segmentation" }),
      el("div", { class: "row" },
        el("button", { class: "btn", type: "button", onclick: c.merge, text: "Merge with next block" }),
        el("span", {}, "or split at line ", c.at),
        el("button", { class: "btn", type: "button", onclick: c.split, text: "Split" })),
      el("div", { class: "warn", text: "Merging or splitting rehashes the affected blocks and " +
        "marks their inherited prediction lower-confidence — the agent committed to the " +
        "original boundaries, not these. Blocks that already have a disposition cannot be " +
        "re-segmented." })),
    el("div", { class: "warn keys", text: "1–4 disposition · ⌘/Ctrl ↵ save & next · " +
      "⌘/Ctrl ←/→ move · E endorse prediction · M block map" }));
}

function clearEndorsement() {
  // Cosmetic only: the server clears it too, and the server is the one that decides
  // (WR-Q7). An endorsement means the author wrote nothing to compare against, so the
  // moment they type, the endorsement is gone.
  if (!pendingEndorse) return;
  pendingEndorse = false;
  const flag = byId("endorsedflag");
  if (flag) flag.textContent = "";
}

function markDisposition() {
  document.querySelectorAll(".disp button").forEach((x) => x.classList.toggle("sel", x.dataset.d === pendingDisp));
}

function pick(d) {
  pendingDisp = pendingDisp === d ? "" : d;
  if (pendingDisp !== "confirmed") clearEndorsement();
  dirty = true;
  markDisposition();
}

async function endorse() {
  // WR-Q7: an endorsement is deliberate. Same cost as clicking confirmed, but the ledger
  // can tell a careful confirmation apart from an unread block.
  pendingDisp = "confirmed";
  pendingEndorse = true;
  dirty = true;
  byId("endorsedflag").textContent = "endorsed_prediction: true";
  markDisposition();
  if (await save()) go(cur + 1);
}

function collect() {
  return {
    block_id: S.blocks[cur].block_id,
    disposition: pendingDisp || "",
    reviewer: REVIEWER,
    reviewer_role: ROLE,
    endorsed_prediction: !!pendingEndorse,
    flagged: byId("flag").checked,
    author: {
      meant_to_do: byId("meant").value,
      why_this_way: byId("why").value,
      assumptions_carried: byId("carried").value.split("\n").filter((s) => s.trim()),
    },
  };
}

async function save() {
  const st = byId("stat");
  st.textContent = "saving…";
  st.className = "status";
  const payload = collect();
  const r = await api("/api/answer", payload);
  if (!r.ok) {
    const detail = r.lint_lines && r.lint_lines.length ? r.lint_lines.join(" | ") : r.error || "?";
    st.textContent = `save failed: ${detail}`;
    st.className = "status err";
    return false;
  }
  // Only now does the client's copy of the ledger change: everything the sidebar and the
  // block map draw is state the server has accepted and written.
  const b = S.blocks[cur];
  const a = payload.author;
  b.author = a;
  b.flagged = payload.flagged;
  b.disposition = payload.disposition;
  b.discussed = !!(a.meant_to_do || a.why_this_way || a.assumptions_carried.length);
  b.endorsed_prediction = b.discussed ? false : payload.endorsed_prediction;  // server-decided
  pendingEndorse = b.endorsed_prediction;
  byId("endorsedflag").textContent = b.endorsed_prediction ? "endorsed_prediction: true" : "";
  st.textContent = "saved";
  st.className = "status ok";
  dirty = false;
  progress();
  renderList();
  return true;
}

async function saveNext() { if (await save()) go(cur + 1); }

async function go(i) {
  if (i < 0 || i >= S.blocks.length) return;
  if (!(await leaveBlock())) return;
  cur = i;
  screen = "block";
  render();
  window.scrollTo(0, 0);
}

async function seg(op, bid, atValue) {
  if (!(await leaveBlock())) return;
  const body = { op, block_id: bid, reviewer: REVIEWER, reviewer_role: ROLE };
  if (op === "split") {
    const v = parseInt(atValue || "", 10);
    if (!v) { window.alert("Enter a line number to split at."); return; }
    body.at_line = v;
  }
  const r = await api("/api/segment", body);
  if (!r.ok) { window.alert(r.lint_lines && r.lint_lines.length ? r.lint_lines.join("\n") : r.error); return; }
  const keep = cur;
  const where = screen;
  await load();
  cur = Math.min(keep, S.blocks.length - 1);
  screen = where;
  render();
}

document.addEventListener("keydown", (e) => {
  // Nothing is navigable until the reviewer form is complete: an answer with no reviewer
  // id is an answer attributed to nobody (WR-Q9).
  if (!S || screen === "reviewer" || !reviewerReady()) return;
  const typing = /^(TEXTAREA|INPUT|SELECT)$/.test(document.activeElement.tagName);
  const mod = e.metaKey || e.ctrlKey;
  const key = e.key.toLowerCase();
  if (screen !== "block") {
    if (!typing && key === "m") { e.preventDefault(); showMap(); }
    return;
  }
  if (mod && e.key === "Enter") { e.preventDefault(); saveNext(); return; }
  if (mod && e.key === "ArrowRight") { e.preventDefault(); go(cur + 1); return; }
  if (mod && e.key === "ArrowLeft") { e.preventDefault(); go(cur - 1); return; }
  if (typing) return;
  if (/^[1-4]$/.test(e.key)) { e.preventDefault(); pick(S.dispositions[Number(e.key) - 1]); }
  if (key === "e") { e.preventDefault(); endorse(); }
  if (key === "m") { e.preventDefault(); showMap(); }
});

window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
load();
