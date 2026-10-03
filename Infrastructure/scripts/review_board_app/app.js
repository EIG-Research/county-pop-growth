"use strict";
// Review board client, served by review_board_server.py.
//
// Every element is built with createElement and textContent. Note text is untrusted
// (RB-S3), so nothing in this file turns a string into markup. The server assigns each
// event's id, seq, time, and approved hash (RB-L6); this client sends only what the reviewer
// chose.

// ------------------------------------------------------------------ storage backend (P10)
// One interface between the page and its storage, so the rendering code never calls fetch.
const localBackend = {
  async state() {
    const res = await fetch("/api/state", { cache: "no-store" });
    if (!res.ok) throw new Error(`the board server answered HTTP ${res.status}`);
    return res.json();
  },
  async post(event) {
    const res = await fetch("/api/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    });
    return res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  },
};
const backend = localBackend;

// Per-viewer conveniences only; the page works without them.
const prefs = {
  get(key) { try { return window.localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { window.localStorage.setItem(key, value); } catch { /* optional */ } },
};

let state = null;
let reviewer = null;
let group = "all";
let signature = "";
const drafts = new Map();          // item id -> unsent note text, kept across refreshes
const views = new Map();           // item id -> "current" | "previous" | "diff"

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
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

let toastTimer = null;
function toast(message) {
  const box = document.getElementById("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 4000);
}

function when(ts) {
  return typeof ts === "string" && ts.length >= 16 ? `${ts.slice(0, 10)} ${ts.slice(11, 16)}Z` : "";
}

function statusLabel(status) {
  return { unreviewed: "Unreviewed", approved: "Approved", "needs-changes": "Needs changes" }[status]
    || status;
}

function nameOf(id) {
  const r = (state.reviewers || []).find((x) => x.id === id);
  return r && r.name ? `${r.name} (${id})` : id;
}

// ------------------------------------------------------------------ header and groups
function renderHeader() {
  document.getElementById("board-title").textContent = state.board.title || state.board.slug;
  document.title = `${state.board.title || state.board.slug} · Review board`;
  const closed = state.round.latest_closed;
  const open = state.round.open;
  let line = closed ? `Showing round ${closed}.` : "No round has closed yet, so there is nothing to review.";
  if (open) line += ` Round ${open} is in progress: notes you add now go to round ${open + 1}.`;
  document.getElementById("round-line").textContent = line;

  const banner = document.getElementById("banner");
  clear(banner);
  banner.hidden = state.writable;
  if (!state.writable) {
    banner.append(el("strong", { text: "Read-only. " }),
      "The server will not save statuses or notes until this is fixed:");
    const list = el("ul");
    for (const reason of state.read_only_reasons || []) list.append(el("li", { text: reason }));
    banner.append(list);
  }

  const picker = document.getElementById("reviewer");
  if (!picker.options.length) {
    for (const r of state.reviewers) {
      const label = `${r.name || r.id}${r.role === "owner" ? " (owner)" : ""}`;
      picker.append(el("option", { value: r.id, text: label }));
    }
    const saved = prefs.get(`review-board:${state.board.slug}:reviewer`);
    reviewer = state.reviewers.some((r) => r.id === saved) ? saved : state.owner;
    picker.value = reviewer;
    picker.addEventListener("change", () => {
      reviewer = picker.value;
      prefs.set(`review-board:${state.board.slug}:reviewer`, reviewer);
      render();
    });
  }
}

function reviewedCount(items) {
  return items.filter((i) => ((i.reviewers[reviewer] || {}).status || "unreviewed") !== "unreviewed").length;
}

function renderGroups() {
  const nav = document.getElementById("groups");
  clear(nav);
  const choices = [["all", "All", state.items]].concat(
    state.groups.map((g) => [g, g, state.items.filter((i) => i.group === g)]));
  if (!choices.some(([key]) => key === group)) group = "all";
  for (const [key, label, items] of choices) {
    nav.append(el("button", {
      type: "button", "aria-pressed": String(key === group),
      text: `${label} (${reviewedCount(items)}/${items.length} reviewed)`,
      onclick: () => { group = key; render(); },
    }));
  }
}

// ------------------------------------------------------------------ one card
function renderFigure(item) {
  const box = el("div", { class: "figure" });
  if (!item.render) {
    box.append(el("div", { class: "empty", text: "No render from a closed round yet." }));
    return box;
  }
  const view = item.previous ? (views.get(item.id) || "current") : "current";
  const holder = el("div");
  if (view === "diff") {
    holder.append(el("p", { class: "muted", text: "Building the difference image…" }));
    drawDiff(item, holder);
  } else {
    const source = view === "previous" ? item.previous : item.render;
    // The measured size is set on the element so the page reserves the image's box before it
    // loads; without it every redraw collapses the page and the reader loses their place (RB-S6).
    const m = item.measurements || {};
    const size = m.width_px && m.height_px ? { width: m.width_px, height: m.height_px } : {};
    holder.append(el("img", {
      src: source.url, alt: `${item.id}, round ${source.round}`, loading: "lazy", ...size,
    }));
  }
  box.append(holder);
  if (item.previous) {
    const compare = el("div", { class: "compare", role: "group", "aria-label": "Compare rounds" });
    for (const [key, label] of [["current", `Round ${item.render.round}`],
      ["previous", `Round ${item.previous.round}`], ["diff", "Differences"]]) {
      compare.append(el("button", {
        type: "button", "aria-pressed": String(view === key), text: label,
        onclick: () => { views.set(item.id, key); render(); },
      }));
    }
    box.append(compare);
  }
  return box;
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`could not load ${url}`));
    img.src = url;
  });
}

async function drawDiff(item, holder) {
  try {
    const [a, b] = await Promise.all([loadImage(item.render.url), loadImage(item.previous.url)]);
    const w = Math.max(a.naturalWidth, b.naturalWidth);
    const h = Math.max(a.naturalHeight, b.naturalHeight);
    const pixels = (img) => {
      const c = document.createElement("canvas");
      c.width = w; c.height = h;
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0);
      return ctx.getImageData(0, 0, w, h);
    };
    const now = pixels(a);
    const before = pixels(b);
    const out = document.createElement("canvas");
    out.width = w; out.height = h;
    const ctx = out.getContext("2d");
    const result = ctx.createImageData(w, h);
    let changed = 0;
    for (let i = 0; i < now.data.length; i += 4) {
      const differs = now.data[i] !== before.data[i] || now.data[i + 1] !== before.data[i + 1]
        || now.data[i + 2] !== before.data[i + 2];
      if (differs) {
        changed += 1;
        result.data.set([214, 39, 140, 255], i);
      } else {
        const grey = 0.3 * now.data[i] + 0.59 * now.data[i + 1] + 0.11 * now.data[i + 2];
        const faded = 255 - (255 - grey) * 0.35;
        result.data.set([faded, faded, faded, 255], i);
      }
    }
    ctx.putImageData(result, 0, 0);
    out.setAttribute("aria-label", `${changed} pixels differ between rounds`);
    clear(holder);
    holder.append(out, el("p", { class: "muted",
      text: `${changed.toLocaleString()} of ${(w * h).toLocaleString()} pixels differ (shown in magenta).` }));
  } catch (err) {
    clear(holder);
    holder.append(el("p", { class: "muted", text: `Could not compare rounds: ${err.message}` }));
  }
}

function renderChecks(measurements) {
  const list = el("ul", { class: "checks" });
  for (const key of ["text_floor", "palette", "contrast"]) {
    const m = measurements[key];
    if (!m) continue;
    let detail = m.reason || "";
    if (key === "text_floor" && m.smallest_pt !== undefined) detail = `smallest ${m.smallest_pt}pt, floor ${m.floor_pt}pt`;
    if (key === "palette" && m.off_palette && m.off_palette.length) detail = `off palette: ${m.off_palette.join(", ")}`;
    if (key === "contrast" && m.min_ratio !== undefined) detail = `lowest ${m.min_ratio}:1`;
    list.append(el("li", { class: m.result === "fail" ? "fail" : m.result === "pass" ? "pass" : "" },
      `${key.replace("_", " ")}: ${m.result}${detail ? ` (${detail})` : ""}`));
  }
  if (measurements.width_px) {
    list.append(el("li", { text: `${measurements.width_px}×${measurements.height_px}px`
      + (measurements.dpi ? `, ${measurements.dpi} dpi` : "") }));
  }
  return el("details", {}, el("summary", { text: "Measurements" }), list);
}

function renderNotes(item) {
  const list = el("ol", { class: "notes", "aria-label": "Notes and statuses" });
  for (const e of item.events) {
    const head = el("div", { class: "note-head",
      text: `${nameOf(e.by)} · ${when(e.at)} · ${e.kind === "status" ? "status" : e.kind}` });
    const body = e.kind === "status"
      ? el("div", { class: "note-text", text: `Set status: ${statusLabel(e.status)}` })
      : el("div", { class: "note-text", text: e.text });
    list.append(el("li", { class: e.kind }, head, body));
  }
  if (!item.events.length) list.append(el("li", { class: "status", text: "No notes yet." }));
  return list;
}

// Posts one event, then redraws. `onSaved` runs between the two, so a saved note's draft is
// cleared before the redraw would put it back in the text box.
async function send(event, onSaved) {
  const reply = await backend.post(event).catch((err) => ({ ok: false, error: err.message }));
  if (!reply.ok) {
    toast(`Not saved: ${reply.error || "unknown error"}`);
    return false;
  }
  if (onSaved) onSaved();
  await refresh(true);
  return true;
}

function renderCard(item) {
  const mine = item.reviewers[reviewer] || { status: "unreviewed", approval_current: false };
  const card = el("article", { class: "card", tabindex: "-1", "data-item": item.id,
    "aria-label": item.title || item.id });

  const left = el("div");
  const meta = el("div", { class: "meta" }, el("span", { class: "id", text: item.id }),
    el("span", { class: "tag", text: item.group }));
  for (const tag of item.tags) meta.append(el("span", { class: `tag ${tag}`, text: tag }));
  left.append(el("h2", { text: item.title || item.id }), meta, renderFigure(item));

  const right = el("div", { class: "block" });
  const stack = [];
  if (mine.status === "approved" && !mine.approval_current) {
    stack.push(el("p", { class: "stale",
      text: "Changed since you approved. Look at the new render and approve it again (RB-L5)." }));
  }
  stack.push(el("div", {}, el("h3", { text: "What changed this round" }),
    el("p", { text: item.what_changed || "No change recorded for this item." })));
  const response = item.response;
  stack.push(el("div", {}, el("h3", { text: "Response to your last notes" }),
    response ? el("p", {}, el("strong", { text: `${response.state}: ` }), response.text || "")
      : el("p", { text: "No response this round." })));
  stack.push(renderChecks(item.measurements || {}));

  const controls = el("div", { class: "status-controls", role: "group", "aria-label": "Your status" });
  for (const status of state.vocab.statuses) {
    const disabled = !state.writable || (status === "approved" && !item.render);
    controls.append(el("button", {
      type: "button", "aria-pressed": String(mine.status === status), disabled,
      text: statusLabel(status),
      onclick: () => send({ item: item.id, by: reviewer, kind: "status", status }),
    }));
  }
  stack.push(el("div", {}, el("h3", { text: "Your status" }), controls));
  if (reviewer !== state.owner) {
    const owner = item.owner_approval;
    stack.push(el("p", { class: "muted", text: `Owner: ${statusLabel(owner.status)}`
      + (owner.status === "approved" && !owner.current ? " (on an earlier render)" : "") }));
  }
  stack.push(el("div", {}, el("h3", { text: "Notes" }), renderNotes(item)));

  const area = el("textarea", { "aria-label": `New note on ${item.id}`,
    placeholder: "One point per note.", disabled: !state.writable });
  area.value = drafts.get(item.id) || "";
  area.addEventListener("input", () => drafts.set(item.id, area.value));
  const kind = el("select", { "aria-label": "Note kind", disabled: !state.writable },
    el("option", { value: "change-request", text: "Change request" }),
    el("option", { value: "comment", text: "Comment" }));
  const add = el("button", { type: "submit", text: "Add note", disabled: !state.writable });
  const form = el("form", { class: "composer" }, area, el("div", { class: "row" }, kind, add),
    el("p", { class: "muted", text: "A change request on an approved item sets it back to Needs changes. A comment does not." }));
  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const text = area.value.trim();
    if (!text) { toast("Write the note first."); return; }
    add.disabled = true;
    const saved = await send({ item: item.id, by: reviewer, kind: kind.value, text },
      () => drafts.delete(item.id));
    if (!saved) add.disabled = !state.writable;
  });
  stack.push(form);
  right.append(...stack);
  card.append(left, right);
  return card;
}

// ------------------------------------------------------------------ whole page
function visibleItems() {
  return group === "all" ? state.items : state.items.filter((i) => i.group === group);
}

// Every redraw rebuilds the cards, which empties the page for a moment and would otherwise
// scroll the reader back to the top after each status click, note, or round change (RB-S6).
// The anchor is the card being worked in (or the first one on screen) and its offset from the
// top of the window; after the redraw the page is scrolled so that card sits where it was.
function captureAnchor() {
  const active = document.activeElement && document.activeElement.closest
    ? document.activeElement.closest("#cards .card") : null;
  const cards = Array.from(document.querySelectorAll("#cards .card"));
  const card = active || cards.find((c) => c.getBoundingClientRect().bottom > 0) || null;
  return card ? { id: card.dataset.item, top: card.getBoundingClientRect().top } : null;
}

function restoreAnchor(anchor) {
  if (!anchor) return;
  const card = document.querySelector(`#cards [data-item="${CSS.escape(anchor.id)}"]`);
  if (card) window.scrollBy(0, card.getBoundingClientRect().top - anchor.top);
}

function render() {
  const anchor = captureAnchor();
  renderHeader();
  renderGroups();
  const main = document.getElementById("cards");
  const focused = document.activeElement && document.activeElement.closest
    ? (document.activeElement.closest(".card") || {}).dataset : null;
  clear(main);
  const items = visibleItems();
  if (!items.length) main.append(el("p", { class: "empty", text: "No items in this group." }));
  for (const item of items) main.append(renderCard(item));
  if (focused && focused.item) {
    const again = main.querySelector(`[data-item="${CSS.escape(focused.item)}"]`);
    if (again) again.focus({ preventScroll: true });
  }
  restoreAnchor(anchor);
}

function signatureOf(s) {
  return JSON.stringify([s.round, s.writable, s.items.map((i) => [i.id, i.render && i.render.hash,
    i.events.length, i.response && i.response.text])]);
}

async function refresh(force = false) {
  try {
    const next = await backend.state();
    const sig = signatureOf(next);
    state = next;
    if (force || sig !== signature) {
      signature = sig;
      render();
    }
  } catch (err) {
    toast(`Could not reach the board server: ${err.message}`);
  }
}

// ------------------------------------------------------------------ copy all feedback (S5)
function digest() {
  const lines = [`Review board: ${state.board.title || state.board.slug} (${state.board.slug})`,
    `Latest closed round: ${state.round.latest_closed || "none"}`, ""];
  for (const item of state.items) {
    const owner = item.owner_approval;
    lines.push(`== ${item.id}: ${item.title || ""}`);
    lines.push(`Owner: ${statusLabel(owner.status)}${owner.status === "approved" && !owner.current ? " (stale)" : ""}`);
    for (const e of item.events) {
      if (e.kind === "status") lines.push(`- ${e.id} ${e.by} ${when(e.at)} status ${e.status}`);
      else lines.push(`- ${e.id} ${e.by} ${when(e.at)} ${e.kind}: ${e.text}`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

async function copyAll() {
  const text = digest();
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied all feedback.");
  } catch {
    const area = el("textarea", { "aria-hidden": "true" });
    area.value = text;
    document.body.append(area);
    area.select();
    const ok = document.execCommand && document.execCommand("copy");
    area.remove();
    toast(ok ? "Copied all feedback." : "Copy failed: your browser blocked clipboard access.");
  }
}

// ------------------------------------------------------------------ keyboard
document.addEventListener("keydown", (evt) => {
  const target = evt.target;
  if (target && ["TEXTAREA", "INPUT", "SELECT"].includes(target.tagName)) return;
  if (evt.altKey || evt.ctrlKey || evt.metaKey) return;
  const step = { ArrowRight: 1, j: 1, ArrowLeft: -1, k: -1 }[evt.key];
  if (!step) return;
  const cards = Array.from(document.querySelectorAll(".card"));
  if (!cards.length) return;
  const at = cards.indexOf(document.activeElement && document.activeElement.closest
    ? document.activeElement.closest(".card") : null);
  const next = cards[Math.min(cards.length - 1, Math.max(0, at + step))] || cards[0];
  evt.preventDefault();
  next.focus();
  next.scrollIntoView({ block: "start", behavior: "smooth" });
});

document.getElementById("copy").addEventListener("click", () => { if (state) copyAll(); });

refresh(true);
setInterval(() => refresh(false), 15000);
