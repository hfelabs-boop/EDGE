/* EDGE builder — single-page app, no build step, no dependencies.
 * State is the experiment document itself (same structure as the YAML file).
 */
"use strict";

const S = {
  schema: null, exp: null, path: null, dirty: false,
  routine: null,                 // routine id shown in the timeline
  sel: null,                     // {kind: component|routine|loop|branch|device|settings, ...}
  history: [], future: [],
  previewT: 0, issues: [], sampleRow: {},
  mode: (() => { try { return localStorage.getItem("edge.mode") || "simple"; } catch { return "simple"; } })(),
  view: "story",                 // story (storyboard of all screens) | screen (one screen's timeline)
};

/* Human names for component types, the groups they appear in, and the properties shown before "More options". */
const FRIENDLY = {
  text: ["Text", "Show"], image: ["Picture", "Show"], shape: ["Shape", "Show"], fixation: ["Fixation cross", "Show"],
  sound: ["Sound", "Show"], html: ["Web page / form", "Show"], survey: ["Survey / questionnaire", "Show"],
  keyboard: ["Key press", "Responses"], mouse: ["Mouse click", "Responses"], slider: ["Rating scale", "Responses"],
  gaze_roi: ["Where they look", "Eye tracking"], gaze_follow: ["Follow the gaze", "Eye tracking"], calibrate: ["Calibrate eye tracker", "Eye tracking"],
  marker: ["Event marker", "Hardware"], variable: ["Set a variable", "Logic"], code: ["Python code", "Logic"], wait: ["Pause / blank", "Logic"],
};
const GROUP_ORDER = ["Show", "Responses", "Eye tracking", "Hardware", "Logic", "Other"];
const SIMPLE_HIDDEN = new Set(["code", "marker", "gaze_follow", "calibrate"]);
const BASIC_PROPS = {
  text: ["text", "color", "height", "pos"], image: ["image", "size", "pos"], shape: ["shape", "size", "fill", "pos"],
  fixation: ["size", "fill"], sound: ["sound", "volume"], html: ["file", "html"], survey: ["questions", "title"], keyboard: ["keys", "correct"],
  mouse: ["clickable", "correct"], slider: ["ticks", "labels"], gaze_roi: ["target", "pos", "radius", "dwell"],
  gaze_follow: ["target"], calibrate: ["device"], marker: ["label"], variable: ["set", "when"], wait: [],
};
const BASIC_TIMING = ["start", "duration", "end_routine"];
const FIELD_LABELS = {start: "starts at (s)", duration: "lasts (s)", end_routine: "ends the screen", if: "only if",
  start_after: "starts after", start_if: "starts when", stop_if: "stops when"};
const friendlyName = (type) => (FRIENDLY[type] || [type])[0];
const isSimple = () => S.mode === "simple";

const SCHED_FIELDS = {
  start: {type: "float", default: 0, help: "seconds after the screen appears"},
  duration: {type: "float", default: null, help: "seconds; empty = until the screen ends"},
  start_after: {type: "component", default: null, help: "start when this component stops"},
  start_if: {type: "expr", default: null, help: "start when this expression becomes true"},
  stop_if: {type: "expr", default: null, help: "stop when this expression becomes true"},
  start_frame: {type: "int", default: null, help: "start on frame N (overrides start)"},
  duration_frames: {type: "int", default: null, help: "duration in frames (overrides duration)"},
  end_routine: {type: "bool", default: false, help: "move on to the next screen when this gets a response (or times out)"},
  if: {type: "expr", default: null, help: "include it only when true, e.g. $trials.n < 5"},
  disabled: {type: "bool", default: false},
  save: {type: "bool", default: true, help: "save results in the data file"},
};
const SCHED_KEYS = new Set(["id", "type", ...Object.keys(SCHED_FIELDS)]);

/* ------------------------------------------------------------------ utils */
const $ = (sel, el = document) => el.querySelector(sel);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false)
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
};
const clone = (o) => JSON.parse(JSON.stringify(o));
const isExpr = (v) => typeof v === "string" && v.startsWith("$") && !v.startsWith("$$");
const toast = (msg, ms = 2200) => { const t = $("#toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("on"), ms); };

async function api(path, body) {
  const opt = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  const r = await fetch(path, opt);
  const j = await r.json();
  if (!r.ok || j.error) { const e = new Error(j.error || r.statusText); e.status = r.status; e.data = j; throw e; }
  return j;
}

function uniqueId(base, taken) {
  base = base.replace(/[^A-Za-z0-9_]/g, "_").replace(/^(\d)/, "_$1") || "item";
  if (!taken.has(base)) return base;
  let i = 2; while (taken.has(base + i)) i++;
  return base + i;
}

/* ------------------------------------------------------------------ history */
function commit(render = true) {
  S.history.push(S._snapshot);
  if (S.history.length > 200) S.history.shift();
  S.future = [];
  S._snapshot = JSON.stringify(S.exp);
  setDirty(true);
  saveDraft();
  if (render) renderAll();
  scheduleValidate();
}
const draftKey = () => "edge.draft." + (S.path || "untitled");
function saveDraft() {
  try { localStorage.setItem(draftKey(), JSON.stringify({doc: S.exp, base: S.fingerprint || "", time: new Date().toISOString()})); } catch {}
}
function clearDraft() { try { localStorage.removeItem(draftKey()); } catch {} }
function undo() { if (!S.history.length) return; S.future.push(S._snapshot); S._snapshot = S.history.pop();
  S.exp = JSON.parse(S._snapshot); fixSelection(); setDirty(true); renderAll(); }
function redo() { if (!S.future.length) return; S.history.push(S._snapshot); S._snapshot = S.future.pop();
  S.exp = JSON.parse(S._snapshot); fixSelection(); setDirty(true); renderAll(); }
function setDirty(d) { S.dirty = d; $("#dirty").classList.toggle("on", d); }
function fixSelection() {
  if (!S.exp.routines[S.routine]) S.routine = Object.keys(S.exp.routines)[0] || null;
  if (S.sel?.kind === "component" && !findComp(S.sel.routine, S.sel.id)) S.sel = null;
}

/* ------------------------------------------------------------------ document helpers */
function normalize(exp) {
  exp.name ??= "experiment"; exp.settings ??= {}; exp.devices ??= []; exp.variables ??= {};
  exp.routines ??= {}; exp.flow ??= [];
  for (const r of Object.values(exp.routines)) r.components ??= [];
  return exp;
}
const comps = (rid) => (S.exp.routines[rid]?.components) || [];
const findComp = (rid, id) => comps(rid).find((c) => c.id === id);
const catOf = (type) => S.schema.components[type]?.category || "other";
const allCompIds = () => new Set(Object.values(S.exp.routines).flatMap((r) => r.components.map((c) => c.id)));

function getNode(path) { let cur = S.exp.flow; for (const p of path) cur = cur[p]; return cur; }
function parentOf(path) { return {list: getNode(path.slice(0, -1)), index: path[path.length - 1]}; }
function routineOfNode(n) { return typeof n === "string" ? n : n.routine; }
function walkFlow(fn, nodes = S.exp.flow, path = []) {
  nodes.forEach((n, i) => {
    const p = [...path, i];
    fn(n, p);
    if (n && typeof n === "object") {
      if (n.loop !== undefined) walkFlow(fn, n.children ||= [], [...p, "children"]);
      if (n.if !== undefined && n.then !== undefined) { walkFlow(fn, n.then ||= [], [...p, "then"]); walkFlow(fn, n.else ||= [], [...p, "else"]); }
      if (n.statemachine !== undefined) for (const [name, st] of Object.entries(n.states ||= {}))
        walkFlow(fn, st.run ||= [], [...p, "states", name, "run"]);
    }
  });
}
function loopIds() { const s = new Set(); walkFlow((n) => { if (n?.loop) s.add(n.loop); if (n?.statemachine) s.add(n.statemachine); }); return s; }
function enclosing(rid) {
  // loops and state machines that contain routine `rid` (for variable suggestions)
  const loops = new Set(), machines = new Set();
  walkFlow((n, path) => {
    if (routineOfNode(n) !== rid) return;
    let cur = S.exp.flow;
    for (const k of path) { if (cur && cur.loop !== undefined) loops.add(cur); if (cur && cur.statemachine !== undefined) machines.add(cur); cur = cur[k]; }
  });
  return {loops: [...loops], machines: [...machines]};
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  S.schema = await api("/api/schema");
  try { S.tutorials = (await api("/api/help/tutorials")).tutorials; } catch { S.tutorials = []; }
  const files = (await api("/api/files")).files;
  const last = localStorage.getItem("edge.last");
  if (last && files.some((f) => f.path === last)) await openFile(last);
  else if (files.length === 1) await openFile(files[0].path);
  else { loadDoc(clone(await api("/api/template?name=blank")), null); welcome(files); }
  wire();
  setInterval(pollExternalChanges, 1500);
  const params = new URLSearchParams(location.search);
  if (params.get("tutorial")) { closeModal(); startTutorial(params.get("tutorial")); }
  else if (params.get("help")) { closeModal(); openHelp(params.get("help")); }
}

function loadDoc(exp, path, fp = null, opts = {}) {
  S.fingerprint = fp; S.path = path;
  if (!opts.silent) {
    let draft = null; try { draft = JSON.parse(localStorage.getItem(draftKey()) || "null"); } catch {}
    if (draft && draft.base === (fp || "") && JSON.stringify(draft.doc) !== JSON.stringify(exp)
        && confirm(`Restore unsaved changes from ${draft.time.replace("T", " ").slice(0, 19)}?`)) {
      exp = draft.doc; setTimeout(() => setDirty(true), 0);
    } else if (draft) clearDraft();
  }
  S.exp = normalize(exp); S.history = []; S.future = []; S._snapshot = JSON.stringify(S.exp);
  if (opts.keepSelection && S.exp.routines[S.routine]) fixSelection();
  else {
    S.view = S.mode === "simple" ? "story" : "screen";
    S.routine = routineInFlowOrder()[0] || Object.keys(S.exp.routines)[0] || null;
    S.sel = S.routine ? {kind: "routine", routine: S.routine} : {kind: "settings"};
  }
  $("#filename").textContent = path || "untitled (not saved)";
  setDirty(false); renderAll(); validate();
}
function routineInFlowOrder() { const out = []; walkFlow((n) => { const r = routineOfNode(n); if (typeof r === "string" && !out.includes(r)) out.push(r); }); return out; }

async function openFile(path, opts = {}) {
  const j = await api(`/api/experiment?path=${encodeURIComponent(path)}`);
  loadDoc(j.experiment, path, j.fingerprint, opts);
  if (j.migrations && j.migrations.length) toast("Upgraded from an older format: " + j.migrations.join("; "), 5000);
  localStorage.setItem("edge.last", path);
}

async function save(asNew = false) {
  let path = S.path;
  if (!path || asNew) {
    path = prompt("Save as (path relative to the builder folder):", `${S.exp.name || "experiment"}.yaml`);
    if (!path) return;
  }
  const newPath = path !== S.path;
  const fp = newPath ? "" : (S.fingerprint || "");
  let r;
  try {
    r = await api(`/api/experiment?path=${encodeURIComponent(path)}&fingerprint=${fp}`, S.exp);
  } catch (e) {
    if (e.status !== 409) throw e;
    if (!confirm("This file was changed outside the builder (another window, your editor, or Claude via MCP).\n\n" +
                 "OK = overwrite with my version (theirs is kept as a backup)\nCancel = keep theirs")) {
      await openFile(path, {silent: true, keepSelection: true}); hideBanner(); toast("Loaded the other version"); return;
    }
    r = await api(`/api/experiment?path=${encodeURIComponent(path)}&force=1`, S.exp);
  }
  clearDraft();
  S.path = path; S.fingerprint = r.fingerprint; localStorage.setItem("edge.last", path);
  $("#filename").textContent = path; setDirty(false); hideBanner(); toast("Saved " + path + " (previous version backed up)");
  S.savedAt = Date.now(); checkTutorial();
}

/* ---------------- live sync with edits made elsewhere (MCP, editor, another window) */
let _bannerFor = null;
function hideBanner() { $("#banner").classList.add("hidden"); _bannerFor = null; }
async function pollExternalChanges() {
  if (!S.path || document.hidden) return;
  let fp;
  try { fp = (await api(`/api/fingerprint?path=${encodeURIComponent(S.path)}`)).fingerprint; } catch { return; }
  if (!fp || fp === S.fingerprint) return;
  if (!S.dirty) {
    await openFile(S.path, {silent: true, keepSelection: true});
    validate(); toast("Updated: the file was changed outside the builder (e.g. by Claude)", 3500);
  } else if (_bannerFor !== fp) {
    _bannerFor = fp;
    const b = $("#banner"); b.innerHTML = "";
    b.append("This experiment was changed outside the builder.",
      h("button", {onclick: async () => { clearDraft(); await openFile(S.path, {silent: true, keepSelection: true}); hideBanner(); }}, "Load their version"),
      h("button", {onclick: hideBanner}, "Keep mine"));
    b.classList.remove("hidden");
  }
}

async function versionsDialog() {
  if (!S.path) return toast("Save the experiment first");
  const {backups} = await api(`/api/backups?path=${encodeURIComponent(S.path)}`);
  const body = $("#modal-body"); body.innerHTML = "";
  body.append(h("h3", {}, `Saved versions of ${S.path}`));
  body.append(h("div", {class: "help", style: "color:var(--muted);margin-bottom:8px"},
    "Every save keeps the previous version. Restoring also backs up the current one, so nothing is lost."));
  if (!backups.length) body.append(h("div", {}, "No earlier versions yet."));
  for (const b of backups) body.append(h("div", {class: "choice", onclick: async () => {
    if (S.dirty && !confirm("Discard unsaved changes and restore this version?")) return;
    await api(`/api/restore?path=${encodeURIComponent(S.path)}&id=${encodeURIComponent(b.id)}`, {});
    closeModal(); clearDraft(); await openFile(S.path, {silent: true, keepSelection: true}); toast("Restored " + b.time);
  }}, h("b", {}, b.time.replace("T", " ")), h("small", {}, b.label || b.id)));
  openModal();
}

/* ---------------- data tab: sessions, intelligent tables, exports */
const D = {sessions: [], sel: null, sub: "trials", tables: null, dry: false};
async function renderData() {
  const el = $("#tab-data"); el.innerHTML = "Loading sessions…";
  try { D.sessions = (await api(`/api/sessions?dry_runs=${D.dry ? 1 : 0}`)).sessions; }
  catch (e) { el.textContent = e.message; return; }
  el.innerHTML = "";
  const left = h("div", {});
  const dry = h("input", {type: "checkbox", onchange: (e) => { D.dry = e.target.checked; renderData(); }}); dry.checked = D.dry;
  left.append(h("label", {style: "display:flex;gap:6px;align-items:center;margin-bottom:6px;font-size:12px"}, dry, "include test runs"));
  left.append(h("div", {class: "subtabs"},
    h("button", {onclick: () => exportData(".", ["csv", "xlsx"])}, "Export all → CSV + Excel"),
    h("button", {onclick: () => exportData(".", ["bids"])}, "All → BIDS")));
  if (!D.sessions.length) left.append(h("div", {class: "help", style: "color:var(--muted)"}, "No sessions yet. Run the experiment (or a ▶ Test run, with “include test runs” ticked)."));
  for (const ss of D.sessions) left.append(h("div", {class: "sess" + (D.sel === ss.path ? " sel" : ""), onclick: () => { D.sel = ss.path; renderData(); }},
    h("b", {}, `${ss.participant ?? "?"} · ${ss.experiment ?? ""}`), h("small", {}, `${(ss.started || "").replace("T", " ")}${ss.dry_run ? " · dry run" : ""}${ss.aborted ? " · aborted" : ""}`)));
  const right = h("div", {style: "overflow:auto"});
  el.append(h("div", {class: "data-layout"}, h("div", {style: "overflow:auto"}, left), right));
  if (!D.sel) { right.append(h("div", {class: "help", style: "color:var(--muted)"}, "Select a session to see its trial table, summary and data dictionary.")); return; }
  right.append("Loading tables…");
  const t = await api(`/api/session_tables?path=${encodeURIComponent(D.sel)}`);
  right.innerHTML = "";
  right.append(h("div", {}, t.report.verdict.map((v) => h("div", {class: v.startsWith("OK") ? "ok" : "issue warning"}, v))));
  const subs = [["trials", `Trials (${t.trials.total})`], ["summary", "Summary"], ["dictionary", "Data dictionary"]];
  right.append(h("div", {class: "subtabs"}, subs.map(([k, label]) => h("button", {class: D.sub === k ? "active" : "", onclick: () => { D.sub = k; renderData(); }}, label)),
    h("span", {style: "flex:1"}),
    ...[["csv", "CSV"], ["xlsx", "Excel"], ["tsv", "TSV"], ["json", "JSON"], ["bids", "BIDS"]].map(([f, label]) => h("button", {onclick: () => exportData(D.sel, [f])}, "↓ " + label))));
  const tb = t[D.sub];
  right.append(rowsTable(tb.rows.map((r) => Object.fromEntries(tb.columns.map((c) => [c, r[c]])))));
}
async function exportData(path, formats) {
  try {
    const {files} = await api("/api/export", {path, formats, dry_runs: D.dry});
    const body = $("#modal-body"); body.innerHTML = "";
    body.append(h("h3", {}, `Exported ${files.length} file(s)`));
    for (const f of files.slice(0, 60)) body.append(h("div", {}, h("a", {href: `/api/file?download=1&path=${encodeURIComponent(f)}`}, f)));
    openModal();
  } catch (e) { toast("Export failed: " + e.message, 5000); }
}

/* ------------------------------------------------------------------ render */
function setMode(m) {
  S.mode = m; try { localStorage.setItem("edge.mode", m); } catch {}
  applyMode(); renderAll(); renderIssues(); toast(m === "simple" ? "Simple mode: just the essentials" : "Expert mode: every option is visible");
}
function applyMode() {
  document.body.classList.toggle("mode-simple", S.mode === "simple");
  const b = $("#btn-mode"); if (b) { b.textContent = S.mode === "simple" ? "Simple" : "Expert"; b.classList.toggle("on", S.mode === "expert"); }
  if (S.mode === "simple" && ["source", "hardware"].includes(S.tab)) showTab("issues");
}
function renderAll() {
  renderPalette(); renderDevices(); renderRoutineTabs(); renderTimeline(); renderFlow(); renderProps(); renderPreview();
  if ($("#tab-source").classList.contains("active")) renderSource();
  if (typeof checkTutorial === "function") checkTutorial();
}

function renderPalette() {
  const f = $("#palette-filter").value.toLowerCase();
  const el = $("#palette"); el.innerHTML = "";
  const hasGaze = S.exp.devices.some((d) => (S.schema.devices[d.type]?.capabilities || []).includes("gaze"));
  const groups = {};
  for (const [type, d] of Object.entries(S.schema.components)) {
    if (f && !(type + friendlyName(type) + d.description).toLowerCase().includes(f)) continue;
    if (isSimple() && !f && (SIMPLE_HIDDEN.has(type) || (type === "gaze_roi" && !hasGaze))) continue;
    (groups[(FRIENDLY[type] || [])[1] || "Other"] ||= []).push([type, d]);
  }
  for (const g of GROUP_ORDER) {
    if (!groups[g]) continue;
    el.append(h("div", {class: "pal-cat"}, g));
    for (const [type, d] of groups[g]) {
      el.append(h("div", {class: "pal-item", "data-type": type, title: d.description, draggable: "true",
        ondragstart: (e) => e.dataTransfer.setData("edge/component", type),
        onclick: () => addComponent(type)}, h("span", {class: `dot cat-${d.category}`}), friendlyName(type),
        S.mode === "expert" ? h("span", {class: "pal-type"}, type) : null));
    }
  }
  if (isSimple() && !f) el.append(h("div", {class: "help pal-more"}, "More (code, markers, eye tracking): switch to ",
    h("a", {href: "#", onclick: (e) => { e.preventDefault(); setMode("expert"); }}, "Expert"), " or search."));
}

function renderDevices() {
  const el = $("#devices"); el.innerHTML = "";
  if (!S.exp.devices.length) el.append(h("div", {class: "help", style: "color:var(--muted);font-size:12px"}, "No devices. Add eye trackers, EEG, physiology, LSL or TTL outputs."));
  S.exp.devices.forEach((d, i) => {
    const caps = S.schema.devices[d.type]?.capabilities || [];
    el.append(h("div", {class: "dev-item" + (S.sel?.kind === "device" && S.sel.index === i ? " sel" : ""),
      onclick: () => { S.sel = {kind: "device", index: i}; renderAll(); }},
      h("div", {}, h("b", {}, d.id), " ", h("span", {class: "t"}, d.type), d.required === false ? h("span", {class: "t"}, " (optional)") : null),
      h("div", {class: "caps"}, caps.map((c) => h("span", {class: "cap"}, c)))));
  });
}

function renderRoutineTabs() {
  const el = $("#routine-tabs"); el.innerHTML = "";
  el.append(h("div", {class: "rtab story" + (S.view === "story" ? " active" : ""), title: "See all screens in order",
    onclick: () => { S.view = "story"; if (S.sel && ["machine", "state"].includes(S.sel.kind)) S.sel = null; renderAll(); }}, "▦ Storyboard"));
  for (const rid of Object.keys(S.exp.routines)) {
    el.append(h("div", {class: "rtab" + (rid === S.routine && S.view === "screen" ? " active" : ""), title: "Screen (routine) · double-click to rename",
      onclick: () => openScreen(rid), ondblclick: () => renameRoutine(rid)}, rid));
  }
  el.append(h("div", {class: "rtab add", title: "New screen (a routine: one trial, an instruction page, feedback …)", onclick: () => newRoutine()}, "+ screen"));
}
function openScreen(rid) { S.routine = rid; S.view = "screen"; S.sel = {kind: "routine", routine: rid}; S.previewT = 0; renderAll(); }

function numOr(v, d) { return typeof v === "number" ? v : d; }

function routineSpan(rid) {
  const r = S.exp.routines[rid];
  let max = numOr(r?.duration, 0);
  for (const c of comps(rid)) max = Math.max(max, numOr(c.start, 0) + numOr(c.duration, 0.5));
  return Math.max(2, Math.ceil(max * 1.15 * 2) / 2);
}

function renderTimeline() {
  const el = $("#timeline"); el.innerHTML = "";
  const wf = S.sel && (S.sel.kind === "machine" || S.sel.kind === "state");
  $("#preview-wrap").style.display = wf ? "none" : "";
  $("#routine-body").classList.toggle("wide", !!wf);
  $("#center").classList.remove("story-view");
  if (wf) return renderDiagram(el);
  const story = S.view === "story" && typeof renderStoryboard === "function";
  $("#preview-wrap").style.display = story ? "none" : "";
  $("#routine-body").classList.toggle("wide", story);
  $("#center").classList.toggle("story-view", story);
  if (story) return renderStoryboard(el);
  const rid = S.routine;
  if (!rid) { el.append(h("div", {class: "tl-empty"}, "No screens yet. Click “+ screen”.")); return; }
  const r = S.exp.routines[rid];
  const span = routineSpan(rid);
  $("#preview-t").max = span;
  el.append(h("div", {class: "tl-routine-info"},
    h("button", {class: "mini back", title: "Back to the storyboard", onclick: () => { S.view = "story"; renderAll(); }}, "← Storyboard"), " ",
    h("span", {onclick: () => { S.sel = {kind: "routine", routine: rid}; renderProps(); }}, `Screen “${rid}”`),
    r.duration != null ? ` · lasts ${r.duration}s` : "", r.end_if ? ` · ends if ${r.end_if}` : "",
    " · drag bars to move, drag the right edge to resize"));
  el.append(h("div", {class: "tl-summary"}, describeRoutine(rid)));
  const ruler = h("div", {class: "tl-ruler"});
  const step = span > 10 ? 2 : span > 4 ? 1 : 0.5;
  for (let t = 0; t <= span + 1e-9; t += step) ruler.append(h("span", {style: `left:${(t / span) * 100}%`}, t + "s"));
  el.append(ruler);
  if (!comps(rid).length) el.append(h("div", {class: "tl-empty"}, "Empty screen: click something on the left (Text, Picture, Key press …) to add it."));
  comps(rid).forEach((c, idx) => {
    const cat = catOf(c.type);
    const sel = S.sel?.kind === "component" && S.sel.routine === rid && S.sel.id === c.id;
    const track = h("div", {class: "tl-track"});
    const start = numOr(c.start, 0);
    const conditional = isExpr(c.start) || c.start_after || c.start_if || c.start_frame != null;
    const open = c.duration == null && c.duration_frames == null;
    const dur = open ? (numOr(r.duration, span) - start) : numOr(c.duration, (c.duration_frames || 30) / 60);
    const bar = h("div", {class: `tl-bar cat-${cat}` + (open ? " open" : "") + (conditional ? " cond" : "") + (c.end_routine ? " end" : ""),
      style: `left:${(start / span) * 100}%;width:${Math.max(0.5, (dur / span) * 100)}%`,
      title: `${c.id}: start ${c.start ?? 0}${c.duration != null ? ", duration " + c.duration : ""}`});
    const handle = h("div", {class: "h"});
    bar.append(handle);
    bar.addEventListener("mousedown", (e) => dragBar(e, c, track, span, e.target === handle ? "resize" : "move"));
    track.append(bar);
    const row = h("div", {class: "tl-row" + (sel ? " sel" : ""), "data-idx": idx},
      h("div", {class: "tl-label", onclick: () => selectComp(rid, c.id)},
        h("span", {class: `dot cat-${cat}`}), h("b", {}, c.id), h("span", {class: "ty"}, friendlyName(c.type))), track);
    el.append(row);
  });
  const cursor = h("div", {class: "tl-cursor", style: `left:calc(170px + 10px + (100% - 190px) * ${S.previewT / span})`});
  el.append(cursor);
}

function dragBar(e, c, track, span, mode) {
  e.preventDefault(); e.stopPropagation();
  selectComp(S.routine, c.id, false);
  const rect = track.getBoundingClientRect();
  const x0 = e.clientX;
  const s0 = numOr(c.start, 0), d0 = numOr(c.duration, null);
  const snap = (v) => Math.max(0, Math.round(v * 20) / 20);
  let moved = false;
  const onMove = (ev) => {
    const dt = ((ev.clientX - x0) / rect.width) * span;
    if (Math.abs(ev.clientX - x0) > 2) moved = true;
    if (!moved) return;
    if (mode === "move") { if (!isExpr(c.start)) c.start = snap(s0 + dt); }
    else c.duration = Math.max(0.05, snap((d0 ?? (span - s0)) + dt));
    renderTimeline(); renderPreview();
  };
  const onUp = () => { document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp);
    if (moved) commit(); else renderAll(); };
  document.addEventListener("mousemove", onMove); document.addEventListener("mouseup", onUp);
}

/* ---------------- flow */
function renderFlow() {
  const el = $("#flow"); el.innerHTML = "";
  el.append(renderSeq(S.exp.flow, []));
}

function renderSeq(nodes, path) {
  const seq = h("div", {class: "fl-seq"});
  seq.append(addBtn(path, 0));
  nodes.forEach((n, i) => {
    seq.append(renderNode(n, [...path, i]));
    seq.append(h("span", {class: "fl-arrow"}, "→"), addBtn(path, i + 1));
  });
  return seq;
}

function addBtn(listPath, index) {
  const el = h("span", {class: "fl-add", title: "Insert here (or drop a flow item here)", onclick: (e) => flowInsertMenu(e, listPath, index)}, "+");
  el.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("edge/flowpath")) { e.preventDefault(); el.classList.add("drop"); } });
  el.addEventListener("dragleave", () => el.classList.remove("drop"));
  el.addEventListener("drop", (e) => { e.preventDefault(); el.classList.remove("drop");
    moveFlowNode(JSON.parse(e.dataTransfer.getData("edge/flowpath")), listPath, index); });
  return el;
}
function draggableNode(el, path) {
  el.draggable = true;
  el.addEventListener("dragstart", (e) => { e.stopPropagation(); e.dataTransfer.setData("edge/flowpath", JSON.stringify(path)); el.classList.add("dragging"); });
  el.addEventListener("dragend", () => el.classList.remove("dragging"));
  return el;
}
function moveFlowNode(from, toList, toIndex) {
  // refuse to drop an item inside itself
  if (toList.length >= from.length && from.every((x, i) => toList[i] === x)) return toast("Can't move an item into itself");
  const {list: srcList, index: srcIdx} = parentOf(from);
  const node = srcList[srcIdx];
  const dst = getNode(toList);
  srcList.splice(srcIdx, 1);
  let idx = toIndex;
  if (dst === srcList && srcIdx < toIndex) idx -= 1;
  dst.splice(idx, 0, node);
  S.sel = null; commit();
}

function samePath(a, b) { return a && b && a.length === b.length && a.every((x, i) => x === b[i]); }

function renderNode(n, path) {
  return draggableNode(renderNodeInner(n, path), path);
}
function renderNodeInner(n, path) {
  const selected = S.sel && ["loop", "branch", "flowref", "machine"].includes(S.sel.kind) && samePath(S.sel.path, path);
  if (typeof n === "string" || (n && n.routine !== undefined)) {
    const rid = routineOfNode(n);
    return h("div", {class: "fl-routine" + (rid === S.routine && S.sel?.kind !== "machine" && S.sel?.kind !== "state" ? " active" : "") + (selected ? " sel" : ""),
      title: (n.if ? `runs only if ${n.if} · ` : "") + "click: edit · drag: move · right-click: options",
      onclick: (e) => { e.stopPropagation(); S.routine = rid; S.view = "screen"; S.sel = {kind: "routine", routine: rid, path}; S.previewT = 0; renderAll(); },
      oncontextmenu: (e) => { e.preventDefault(); e.stopPropagation(); nodeMenu(e, path); }}, rid, n.if ? h("span", {class: "cond-badge", title: n.if}, "if") : "");
  }
  if (n.statemachine !== undefined) return renderMachine(n, path, selected);
  if (n.loop !== undefined) {
    const desc = n.staircase ? `staircase on ${n.staircase.variable || "level"}` :
      `${loopRowsLabel(n)}${n.repeats && n.repeats !== 1 ? " × " + n.repeats : ""}, ${n.order || "sequential"}`;
    return h("div", {class: "fl-box" + (selected ? " sel" : "")},
      h("div", {class: "fl-head", onclick: () => { S.sel = {kind: "loop", path}; renderAll(); },
        oncontextmenu: (e) => { e.preventDefault(); nodeMenu(e, path); }}, `⟳ ${n.loop} · ${desc}`),
      renderSeq(n.children ||= [], [...path, "children"]));
  }
  if (n.if !== undefined) {
    return h("div", {class: "fl-box branch" + (selected ? " sel" : "")},
      h("div", {class: "fl-head", onclick: () => { S.sel = {kind: "branch", path}; renderAll(); },
        oncontextmenu: (e) => { e.preventDefault(); nodeMenu(e, path); }}, `◇ if ${n.if}`),
      h("div", {style: "display:flex;align-items:center"}, renderSeq(n.then ||= [], [...path, "then"]),
        h("span", {class: "fl-else"}, "else"), renderSeq(n.else ||= [], [...path, "else"])));
  }
  return h("span", {}, "?");
}

function menu(e, items) {
  document.querySelectorAll(".menu").forEach((m) => m.remove());
  const m = h("div", {class: "menu", style: `left:${e.clientX}px;top:${e.clientY}px`});
  for (const it of items) m.append(it === "-" ? h("hr") : h("div", {onclick: () => { m.remove(); it[1](); }}, it[0]));
  document.body.append(m);
  // keep long menus inside the window: shift up / left and scroll
  const r = m.getBoundingClientRect();
  if (r.bottom > innerHeight - 8) m.style.top = Math.max(8, innerHeight - 8 - r.height) + "px";
  if (r.right > innerWidth - 8) m.style.left = Math.max(8, innerWidth - 8 - r.width) + "px";
  setTimeout(() => document.addEventListener("click", () => m.remove(), {once: true}), 0);
}

function flowInsertMenu(e, listPath, index) {
  const list = getNode(listPath);
  const items = Object.keys(S.exp.routines).map((rid) => [`Screen: ${rid}`, () => { list.splice(index, 0, rid); commit(); }]);
  items.push("-",
    ["New screen…", () => { const rid = newRoutine(false); if (rid) { list.splice(index, 0, rid); commit(); } }],
    ["Repeat with a trial list (loop)", () => { const id = uniqueId("trials", loopIds()); list.splice(index, 0, {loop: id, order: "random", repeats: 1, conditions: [{condition: "A"}, {condition: "B"}], children: []});
      S.sel = {kind: "loop", path: [...listPath, index]}; commit(); }],
    ["If / else (branch)", () => { list.splice(index, 0, {if: "$True", then: [], else: []}); S.sel = {kind: "branch", path: [...listPath, index]}; commit(); }],
    ["Workflow (state machine): practice until …, screening", () => { const id = uniqueId("workflow", loopIds());
      list.splice(index, 0, {statemachine: id, start: "start", states: {start: {run: [], next: [{goto: "end"}]}}});
      S.sel = {kind: "machine", path: [...listPath, index]}; commit(); }]);
  menu(e, items);
}

function nodeMenu(e, path) {
  const {list, index} = parentOf(path);
  menu(e, [
    ["Move left", () => { if (index > 0) { [list[index - 1], list[index]] = [list[index], list[index - 1]]; commit(); } }],
    ["Move right", () => { if (index < list.length - 1) { [list[index + 1], list[index]] = [list[index], list[index + 1]]; commit(); } }],
    ["Repeat it (wrap in a loop)", () => { list[index] = {loop: uniqueId("block", loopIds()), order: "sequential", repeats: 2, children: [list[index]]}; commit(); }],
    ["Run only if…", () => { const c = prompt("Expression (e.g. $score > 5):", "$True"); if (!c) return;
      const n = list[index]; if (typeof n === "string" || n.routine) list[index] = {routine: routineOfNode(n), if: c};
      else list[index] = {if: c, then: [n], else: []}; commit(); }],
    "-",
    ["Remove from flow", () => { list.splice(index, 1); S.sel = null; commit(); }],
  ]);
}

/* ---------------- components & routines */
function addComponent(type, at, opts = {}) {
  if (!S.routine) newRoutine(false);
  let rid = S.routine;
  if ((type === "survey" || type === "html") && comps(rid).length) {
    // a page needs the whole screen: give it its own, right after this one in the flow
    const nid = uniqueId(type === "survey" ? "questionnaire" : "page", new Set(Object.keys(S.exp.routines)));
    S.exp.routines[nid] = {components: []};
    let placed = false;
    walkFlow((n, path) => { if (placed || routineOfNode(n) !== rid) return; const {list, index} = parentOf(path); list.splice(index + 1, 0, nid); placed = true; });
    if (!placed) S.exp.flow.push(nid);
    S.routine = rid = nid; at = undefined;
    setTimeout(() => toast(`Pages fill the whole screen, so this one got its own screen “${nid}” in the flow`, 4500), 50);
  }
  const d = S.schema.components[type];
  const base = {keyboard: "resp", mouse: "click", slider: "rating", image: "picture", fixation: "fixation", html: "page"}[type] || type;
  const c = {id: uniqueId(base, new Set(comps(rid).map((x) => x.id))), type};
  for (const [k, p] of Object.entries(d.props)) if (p.required) c[k] = p.default ?? (p.type === "text" || p.type === "str" ? "" : null);
  if (type === "text") c.text = "Hello";
  if (type === "keyboard") { c.keys = ["space"]; c.end_routine = true; }
  if (type === "marker") c.label = "event";
  if (type === "survey") { c.title = "A few questions"; c.questions = [{id: "q1", type: "likert", scale: "agree5", required: true, text: "I enjoyed the task."}]; c.end_routine = true; }
  if (type === "html") c.end_routine = true;
  S.autoDur ||= new Set();
  if (d.visual && !["slider"].includes(type) && !comps(rid).some((x) => x.end_routine) && S.exp.routines[rid].duration == null) {
    c.duration = 1.0; S.autoDur.add(rid + "." + c.id);   // a placeholder so the screen can end; see below
  }
  if (c.end_routine) {   // a response now ends the screen: placeholder durations would hide stimuli too early
    const freed = comps(rid).filter((x) => x.duration === 1 && S.autoDur.has(rid + "." + x.id));
    freed.forEach((x) => { delete x.duration; S.autoDur.delete(rid + "." + x.id); });
    if (freed.length) setTimeout(() => toast(`${freed.map((x) => x.id).join(", ")} now stay${freed.length === 1 ? "s" : ""} on screen until the response`, 3500), 50);
  }
  Object.assign(c, opts.props || {});
  if (at != null) comps(rid).splice(at, 0, c); else comps(rid).push(c);
  S.sel = {kind: "component", routine: rid, id: c.id}; S.view = "screen";
  commit();
  if ((opts.picker || !opts.props) && (type === "image" || type === "sound") && typeof openAssetPicker === "function")
    setTimeout(() => openAssetPicker(type === "image" ? "image" : "audio", (v) => { const cc = findComp(rid, c.id); if (cc) setProp(cc, type, v); }), 80);
}

function selectComp(rid, id, render = true) { S.routine = rid; S.sel = {kind: "component", routine: rid, id}; if (render) renderAll(); }

function newRoutine(render = true) {
  const rid = prompt("Name of the new screen (e.g. trial, instructions, feedback):", uniqueId(Object.keys(S.exp.routines).length ? "screen" : "trial", new Set(Object.keys(S.exp.routines))));
  if (!rid) return null;
  const id = uniqueId(rid, new Set(Object.keys(S.exp.routines)));
  S.exp.routines[id] = {components: []};
  S.routine = id; S.view = "screen"; S.sel = {kind: "routine", routine: id};
  if (render) commit(); return id;
}

function renameRoutine(rid) {
  const nid = prompt("Rename screen:", rid);
  if (!nid || nid === rid) return;
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(nid)) return toast("Use letters, digits and _ only (no spaces)");
  if (S.exp.routines[nid]) return toast("A screen with that name exists");
  const r = {}; for (const [k, v] of Object.entries(S.exp.routines)) r[k === rid ? nid : k] = v;
  S.exp.routines = r;
  walkFlow((n, path) => {
    const {list, index} = parentOf(path);
    if (n === rid) list[index] = nid; else if (n && n.routine === rid) n.routine = nid;
  });
  S.routine = nid; S.sel = {kind: "routine", routine: nid}; commit();
}

/* ---------------- properties */
function renderProps() {
  updateExprVars();
  const el = $("#props"); el.innerHTML = "";
  const sel = S.sel || {kind: "settings"};
  const title = $("#props-title");
  if (sel.kind === "component") {
    const c = findComp(sel.routine, sel.id); if (!c) return;
    const d = S.schema.components[c.type];
    title.textContent = `${friendlyName(c.type)} · ${c.id}`;
    el.append(h("div", {class: "desc"}, d?.description || "Unknown component type", " ", helpLink("reference/components", c.type)));
    el.append(field("name", {type: "str", help: "used to refer to it, e.g. $" + c.id + (S.schema.components[c.type]?.category === "response" ? ".rt" : "")}, c.id, (v) => renameComp(c, v), {noExpr: true}));
    const basic = new Set(BASIC_PROPS[c.type] || Object.keys(d?.props || {}));
    const shapeExtra = {circle: ["radius"], line: ["start", "end", "line_width"], polygon: ["vertices"], cross: ["line_width"]}[c.shape || (c.type === "fixation" ? "cross" : "")];
    if (shapeExtra && (c.type === "shape" || c.type === "fixation")) { if (c.shape === "circle" || c.shape === "line" || c.shape === "polygon") basic.delete("size"); shapeExtra.forEach((k) => basic.add(k)); }
    const isSet = (k, p) => c[k] !== undefined && c[k] !== null && JSON.stringify(c[k]) !== JSON.stringify(p?.default ?? null);
    const more = [];
    el.append(h("div", {class: "group"}, "What"));
    for (const [k, p] of Object.entries(d?.props || {})) {
      const f = field(k, p, c[k], (v) => setProp(c, k, v), {comp: c, live: (v) => { if (v === null || v === undefined) delete c[k]; else c[k] = v; renderPreview(); }});
      if (S.mode === "expert" || basic.has(k) || p.required) el.append(f); else more.push([f, isSet(k, p)]);
    }
    el.append(h("div", {class: "group"}, "When"));
    for (const [k, p] of Object.entries(SCHED_FIELDS)) {
      const f = field(k, p, c[k], (v) => setProp(c, k, v), {label: FIELD_LABELS[k]});
      if (S.mode === "expert" || BASIC_TIMING.includes(k)) el.append(f); else more.push([f, isSet(k, p)]);
    }
    const custom = Object.keys(c).filter((k) => !SCHED_KEYS.has(k) && !(d?.props || {})[k]);
    for (const k of custom) { const f = field(k, {type: "json"}, c[k], (v) => setProp(c, k, v)); if (S.mode === "expert") el.append(f); else more.push([f, true]); }
    if (more.length) el.append(moreOptions(more, "comp"));
    const list = comps(sel.routine); const i = list.indexOf(c);
    el.append(h("div", {class: "btns"},
      h("button", {onclick: () => { if (i > 0) { [list[i - 1], list[i]] = [list[i], list[i - 1]]; commit(); } }, title: "Draw earlier (behind)"}, "↑"),
      h("button", {onclick: () => { if (i < list.length - 1) { [list[i + 1], list[i]] = [list[i], list[i + 1]]; commit(); } }, title: "Draw later (on top)"}, "↓"),
      h("button", {onclick: () => { const cp = clone(c); cp.id = uniqueId(c.id, new Set(list.map((x) => x.id))); list.splice(i + 1, 0, cp); S.sel.id = cp.id; commit(); }}, "Duplicate"),
      h("button", {class: "danger", onclick: () => { list.splice(i, 1); S.sel = {kind: "routine", routine: sel.routine}; commit(); }}, "Delete")));
  } else if (sel.kind === "routine") {
    const r = S.exp.routines[sel.routine]; if (!r) return;
    title.textContent = `Screen · ${sel.routine}`;
    el.append(h("div", {class: "desc"}, "A screen (a “routine” in the file) is one step: a trial, an instruction page, feedback. Add things to it from the left. ", helpLink("EXPERIMENT_FORMAT", "routines-and-components")));
    el.append(field("name", {type: "str"}, sel.routine, (v) => renameRoutine(sel.routine), {noExpr: true, readonlyClick: () => renameRoutine(sel.routine)}));
    el.append(field("duration", {type: "float", help: "maximum length in seconds (empty = until a response or everything has finished)"}, r.duration, (v) => setProp(r, "duration", v), {label: "lasts at most (s)"}));
    el.append(field("description", {type: "text"}, r.description, (v) => setProp(r, "description", v), {noExpr: true, label: "notes"}));
    const ruleBox = h("div", {});
    ruleBox.append(field("end_if", {type: "expr", help: "end when this expression becomes true"}, r.end_if, (v) => setProp(r, "end_if", v), {label: "ends when"}));
    renderRulesEditor(ruleBox, r);
    if (S.mode === "expert" || (r.rules || []).length || r.end_if) el.append(ruleBox);
    else el.append(moreOptions([[ruleBox, false]], "screen", "Rules: react while the screen runs"));
    el.append(h("div", {class: "btns"},
      h("button", {onclick: () => { const nid = uniqueId(sel.routine, new Set(Object.keys(S.exp.routines))); S.exp.routines[nid] = clone(r); S.routine = nid; S.sel = {kind: "routine", routine: nid}; commit(); }}, "Duplicate"),
      h("button", {class: "danger", onclick: () => deleteRoutine(sel.routine)}, "Delete screen")));
  } else if (sel.kind === "machine") {
    renderMachineProps(el, title);
  } else if (sel.kind === "state") {
    renderStateProps(el, title);
  } else if (sel.kind === "loop") {
    renderLoopProps(el, getNode(sel.path), title);
  } else if (sel.kind === "branch") {
    const n = getNode(sel.path);
    title.textContent = "Branch";
    el.append(h("div", {class: "desc"}, "Runs the top sequence if the condition is true, otherwise the “else” sequence."));
    el.append(field("if", {type: "expr", help: "e.g. $score >= 8 or $practice.n_correct > 4"}, n.if, (v) => setProp(n, "if", v || "$True")));
  } else if (sel.kind === "device") {
    renderDeviceProps(el, S.exp.devices[sel.index], sel.index, title);
  } else {
    renderSettings(el, title);
  }
}

function renameComp(c, v) {
  if (!v || v === c.id) return;
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(v)) return toast("Use letters, digits and _ only");
  if (findComp(S.sel.routine, v)) return toast("Another component has that id");
  c.id = v; S.sel.id = v; commit();
}

function setProp(obj, k, v) {
  if (v === null || v === undefined || v === "") delete obj[k]; else obj[k] = v;
  commit();
}

function deleteRoutine(rid) {
  if (!confirm(`Delete the screen “${rid}” and remove it from the flow?`)) return;
  delete S.exp.routines[rid];
  const prune = (list) => { for (let i = list.length - 1; i >= 0; i--) { const n = list[i];
    if (routineOfNode(n) === rid) list.splice(i, 1);
    else if (n && typeof n === "object") { if (n.children) prune(n.children); if (n.then) prune(n.then); if (n.else) prune(n.else); } } };
  prune(S.exp.flow);
  S.routine = Object.keys(S.exp.routines)[0] || null; S.sel = S.routine ? {kind: "routine", routine: S.routine} : null; commit();
}

function parseVal(type, raw) {
  if (raw === "" || raw === null || raw === undefined) return null;
  if (typeof raw === "string" && isExpr(raw)) return raw;
  switch (type) {
    case "float": { const n = Number(raw); return isNaN(n) ? raw : n; }
    case "int": { const n = parseInt(raw, 10); return isNaN(n) ? raw : n; }
    case "list": {
      const s = String(raw).trim();
      if (s.startsWith("[")) { try { return JSON.parse(s); } catch { return s; } }
      return s.split(",").map((x) => x.trim()).filter(Boolean).map((x) => (x !== "" && !isNaN(Number(x)) ? Number(x) : x));
    }
    case "vec2": case "json": case "dict": case "marker":
      try { return JSON.parse(raw); } catch { return raw; }
    default: return raw;
  }
}
const showVal = (type, v) => {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (type === "list" && Array.isArray(v) && v.every((x) => typeof x !== "object")) return v.join(", ");
  return typeof v === "object" ? JSON.stringify(v) : String(v);
};

function field(name, p, value, onChange, opts = {}) {
  const type = p.type || "str";
  const wrap = h("div", {class: "field"});
  const picker = !(opts.noExpr || type === "expr" || type === "code" || type === "bool" || type === "survey");
  const cols = picker ? columnsForScreen(S.routine) : [];
  const colOf = (v) => (isExpr(v) && /^\$[A-Za-z_]\w*$/.test(v.trim()) && cols.includes(v.trim().slice(1))) ? v.trim().slice(1) : null;
  let source = !isExpr(value) ? "fixed" : colOf(value) ? "column" : "formula";
  if (type === "expr") source = "formula";
  const label = opts.label || name;
  let src = null;
  if (picker) {
    src = h("select", {class: "vsrc " + source, title: "Where the value comes from", onchange: (e) => {
      const v = e.target.value;
      if (v === "fixed") onChange(isExpr(value) ? (p.default ?? null) : value);
      else if (v === "formula") onChange("$" + (value === null || value === undefined ? "" : showVal(type, value).replace(/^\$/, "")));
      else if (v === "new") { const col = addTrialColumn(name, isExpr(value) ? "" : value); if (col) onChange("$" + col); else e.target.value = source; }
      else if (v.startsWith("col:")) onChange("$" + v.slice(4));
    }});
    const opt = (val, text, sel) => { const o = h("option", {value: val}, text); if (sel) o.selected = true; return o; };
    src.append(opt("fixed", "Fixed", source === "fixed"));
    if (cols.length) src.append(h("optgroup", {label: "From the trial list"}, cols.map((c) => opt("col:" + c, "⟳ " + c, colOf(value) === c))));
    src.append(opt("new", "+ New trial-list column…", false), opt("formula", "Formula ($…)", source === "formula"));
  }
  wrap.append(h("label", {}, h("span", {}, label + (p.required ? " *" : "")), src));
  let input;
  const commitText = (e) => {
    let raw = e.target.value;
    if (type === "expr" && raw && !raw.startsWith("$")) raw = "$" + raw;
    const v = source === "formula" && type !== "expr" ? (raw.startsWith("$") ? raw : "$" + raw) : parseVal(type, raw);
    if (JSON.stringify(v) !== JSON.stringify(value ?? null)) onChange(v);
  };
  if (type === "survey") {
    input = surveySummary(value, onChange);
  } else if (source === "column") {
    const col = colOf(value), ex = sampleRowFor(S.routine)[col];
    input = h("div", {class: "colchip", title: "Each trial uses this column's value. Edit the values in the trial list (click the loop in the Flow).",
      onclick: () => selectLoopWithColumn(col)}, "⟳ ", h("b", {}, col), ex !== undefined && ex !== "" ? h("span", {}, ` e.g. ${short(showVal("", ex), 24)}`) : null);
  } else if (source === "formula" && type !== "code") {
    input = h("input", {class: "expr", list: "expr-vars", value: value ?? "", placeholder: "$expression (type $ for suggestions)", onchange: commitText});
  } else if (!opts.readonlyClick && typeof stageInput === "function" && (input = stageInput(name, p, value, onChange, opts))) {
    // picker, slider, swatches or position editor from stage.js
  } else if (type === "bool") {
    input = h("input", {type: "checkbox", onchange: (e) => onChange(e.target.checked)});
    input.checked = value ?? p.default ?? false;
  } else if (type === "choice") {
    input = h("select", {onchange: (e) => onChange(e.target.value === "" ? null : e.target.value)},
      (p.choices || []).map((c) => { const o = h("option", {value: c}, c === "" ? "(default)" : c); if ((value ?? p.default) === c) o.selected = true; return o; }));
  } else if (type === "text" || type === "code" || type === "dict" || type === "json") {
    input = h("textarea", {rows: type === "code" ? 6 : 3, dir: type === "code" ? null : "auto", onchange: commitText}, showVal(type, value));
  } else if (type === "color") {
    const txt = h("input", {value: showVal(type, value), placeholder: String(p.default ?? ""), onchange: commitText});
    const col = h("input", {type: "color", style: "width:36px;padding:0", onchange: (e) => onChange(e.target.value)});
    if (typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value)) col.value = value;
    input = h("div", {class: "row2"}, col, txt);
  } else if (type === "device" || type === "component") {
    const opts2 = type === "device" ? S.exp.devices.map((d) => d.id) : comps(S.routine).map((c) => c.id);
    input = h("select", {onchange: (e) => onChange(e.target.value || null)},
      h("option", {value: ""}, "(none / default)"),
      opts2.map((o) => { const op = h("option", {value: o}, o); if (value === o) op.selected = true; return op; }));
  } else if (opts.readonlyClick) {
    input = h("input", {value: value ?? "", readonly: true, onclick: opts.readonlyClick});
  } else {
    input = h("input", {value: showVal(type, value), dir: "auto", placeholder: p.default != null ? showVal(type, p.default) : "", onchange: commitText});
  }
  wrap.append(input);
  if (p.help) wrap.append(h("div", {class: "help"}, p.help));
  return wrap;
}

/* "More options": properties most people never need, folded away (remembered while the builder is open). */
const _openMore = new Set();
function moreOptions(items, key, label) {
  const n = items.filter(([, set]) => set).length;
  const box = h("div", {class: "more" + (_openMore.has(key) ? " open" : "")});
  const head = h("div", {class: "more-head", onclick: () => { box.classList.toggle("open");
    box.classList.contains("open") ? _openMore.add(key) : _openMore.delete(key); }},
    h("span", {class: "chev"}, "▸"), " ", label || "More options", n ? h("span", {class: "more-n"}, ` (${n} set)`) : "");
  box.append(head, h("div", {class: "more-body"}, items.map(([f]) => f)));
  return box;
}

/* ---------------- trial-list columns available to a screen */
function loopColumns(lp) {
  if (!lp) return [];
  if (lp.staircase) return [lp.staircase.variable || "level"];
  const c = lp.conditions;
  if (Array.isArray(c)) return [...new Set(c.flatMap((r) => Object.keys(r || {})))];
  if (c && c.factorial) return Object.keys(c.factorial);
  if (c) return Object.keys(firstRow(c) || {});
  return [];
}
function columnsForScreen(rid) {
  if (!rid) return [];
  const out = [];
  for (const lp of enclosing(rid).loops) for (const c of loopColumns(lp)) if (!out.includes(c)) out.push(c);
  return out;
}
function loopRowsLabel(n) {
  const c = n.conditions;
  const rows = Array.isArray(c) ? c.length : c && c.factorial ? Object.values(c.factorial).reduce((a, v) => a * (Array.isArray(v) ? v.length : 1), 1) : null;
  return rows == null ? (typeof c === "string" ? c : "repeat") : `${rows} row${rows === 1 ? "" : "s"}`;
}
function innermostLoopPath(rid) {
  let best = null;
  walkFlow((n, path) => {
    if (routineOfNode(n) !== rid) return;
    let cur = S.exp.flow, lpPath = null;
    for (let i = 0; i < path.length; i++) { if (cur && cur.loop !== undefined) lpPath = path.slice(0, i); cur = cur[path[i]]; }
    if (lpPath && (!best || lpPath.length > best.length)) best = lpPath;
  });
  return best;
}
function selectLoopWithColumn(col) {
  const path = innermostLoopPath(S.routine);
  if (path) { S.sel = {kind: "loop", path}; renderAll(); }
}
/* Add a column to the trial list around the current screen, creating the trial list if there is none. */
function addTrialColumn(suggest, fill) {
  const rid = S.routine;
  const name = (prompt("Name of the new trial-list column (each trial can have a different value):",
    uniqueId(suggest === "text" ? "word" : suggest === "image" ? "picture" : suggest, new Set(columnsForScreen(rid)))) || "").trim();
  if (!name) return null;
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) { toast("Use letters, digits and _ only (no spaces)"); return null; }
  const v = fill === null || fill === undefined ? "" : fill;
  let path = innermostLoopPath(rid);
  if (path) {
    const lp = getNode(path);
    if (typeof lp.conditions === "string") { toast(`The trial list comes from ${lp.conditions}: add the column in that file`, 5000); return null; }
    if (lp.staircase) { toast("This loop is a staircase; add a column to an outer trial list instead"); return null; }
    if (lp.conditions && lp.conditions.factorial) { lp.conditions.factorial[name] = [v]; }
    else { lp.conditions = Array.isArray(lp.conditions) && lp.conditions.length ? lp.conditions : [{}]; lp.conditions.forEach((r) => { if (!(name in r)) r[name] = v; }); }
    toast(`Added “${name}” to the trial list of “${lp.loop}”. Click the loop in the Flow to fill in each trial.`, 5000);
  } else {
    // no loop yet: wrap every top-level use of this screen in a new trial list
    const id = uniqueId("trials", loopIds());
    let wrapped = false;
    walkFlow((n, p) => { if (wrapped || routineOfNode(n) !== rid) return; const {list, index} = parentOf(p);
      list[index] = {loop: id, order: "random", repeats: 1, conditions: [{[name]: v}, {[name]: v}], children: [n]}; wrapped = true; });
    if (!wrapped) S.exp.flow.push({loop: id, order: "random", repeats: 1, conditions: [{[name]: v}, {[name]: v}], children: [rid]});
    toast(`Made a trial list “${id}” around this screen with a column “${name}”. Fill in one row per trial.`, 6000);
  }
  return name;
}

function renderLoopProps(el, n, title) {
  title.textContent = `Trial list · ${n.loop}`;
  el.append(h("div", {class: "desc"}, "Repeats the screens inside it once per row. Each column can be picked as a value in any property (the ⟳ entries in its value menu). ", helpLink("COOKBOOK", "trial-lists-and-randomization")));
  el.append(field("id", {type: "str", help: "used in formulas, e.g. $" + n.loop + ".accuracy"}, n.loop, (v) => { if (v) { n.loop = v; commit(); } }, {noExpr: true, label: "name"}));
  const mode = n.staircase ? "staircase" : typeof n.conditions === "string" ? "file" :
    (n.conditions && n.conditions.factorial) ? "factorial" : n.conditions ? "table" : "none";
  el.append(field("conditions source", {type: "choice", choices: ["none", "table", "file", "factorial", "staircase"], help: "table: type it here · file: a CSV/Excel file · factorial: all combinations · staircase: adaptive"}, mode, (v) => {
    delete n.staircase;
    if (v === "none") delete n.conditions;
    else if (v === "table") n.conditions = Array.isArray(n.conditions) ? n.conditions : [{condition: "A"}, {condition: "B"}];
    else if (v === "file") n.conditions = "conditions.csv";
    else if (v === "factorial") n.conditions = {factorial: {factor_a: ["a1", "a2"], factor_b: ["b1", "b2"]}};
    else if (v === "staircase") { delete n.conditions; n.staircase = {variable: "level", start: 0.5, step: [0.1, 0.05], down: 3, up: 1, min: 0, max: 1, reversals: 8, max_trials: 60, correct: "resp.corr"}; }
    commit();
  }, {noExpr: true, label: "trial list from"}));
  if (mode === "table") el.append(condTable(n));
  if (mode === "file") {
    el.append(field("file", {type: "str", help: "CSV / TSV / XLSX / JSON, relative to the experiment file"}, n.conditions, (v) => { n.conditions = v; commit(); }, {noExpr: true}));
    const pv = h("div", {class: "help"}, "loading preview…"); el.append(pv);
    api(`/api/conditions?spec=${encodeURIComponent(JSON.stringify(n.conditions))}&exp=${encodeURIComponent(S.path || "")}`)
      .then((j) => { pv.replaceWith(rowsTable(j.rows.slice(0, 12))); }).catch((e) => pv.textContent = e.message);
  }
  if (mode === "factorial") el.append(field("factors", {type: "dict", help: '{"color": ["red","green"], "size": [1,2]} → all combinations'}, n.conditions.factorial, (v) => { n.conditions.factorial = v; commit(); }, {noExpr: true}));
  if (mode === "staircase") el.append(field("staircase", {type: "dict", help: "variable, start, step, down, up, min, max, reversals, max_trials, correct (expression), log"}, n.staircase, (v) => { n.staircase = v; commit(); }, {noExpr: true}));
  const more = [];
  const put = (f, adv, set) => { if (adv && isSimple()) more.push([f, set]); else el.append(f); };
  if (mode !== "staircase") {
    put(field("order", {type: "choice", choices: S.schema.loop_orders, help: "random: shuffled each repeat · latin_square/counterbalance use the participant number"}, n.order || "sequential", (v) => setProp(n, "order", v), {noExpr: true}), false);
    put(field("repeats", {type: "int", help: "how many times the whole list is run"}, n.repeats ?? 1, (v) => setProp(n, "repeats", v)), false);
    put(field("max_repeat", {type: "dict", help: '{"color": 2} or {"kind": {"deviant": 1}}: limit identical values in a row'}, n.max_repeat, (v) => setProp(n, "max_repeat", v), {noExpr: true, label: "no more than N in a row"}), true, n.max_repeat != null);
    put(field("select", {type: "str", help: 'subset of rows: "0:10" or [0, 3, 5]'}, n.select, (v) => setProp(n, "select", parseVal("json", v)), {noExpr: true, label: "use only rows"}), true, n.select != null);
  }
  put(field("stop_if", {type: "expr", help: "checked after each iteration, e.g. $resp.corr == 0"}, n.stop_if, (v) => setProp(n, "stop_if", v), {label: "stop early when"}), true, !!n.stop_if);
  if (more.length) el.append(moreOptions(more, "loop"));
  const est = h("div", {class: "help loop-est"}); el.append(est);
  if (Array.isArray(n.conditions) || (n.conditions && n.conditions.factorial)) {
    const rows = Array.isArray(n.conditions) ? n.conditions.length : Object.values(n.conditions.factorial).reduce((a, v) => a * (Array.isArray(v) ? v.length : 1), 1);
    est.textContent = `${rows} row${rows === 1 ? "" : "s"} × ${n.repeats ?? 1} = ${rows * (+n.repeats || 1)} runs of the screens inside.`;
  }
  el.append(h("div", {class: "btns"}, h("button", {class: "danger", onclick: () => { const {list, index} = parentOf(S.sel.path);
    if (confirm("Remove the loop but keep its children?")) { list.splice(index, 1, ...(n.children || [])); S.sel = null; commit(); } }}, "Unwrap loop")));
}

function rowsTable(rows) {
  if (!rows.length) return h("div", {class: "help"}, "(no rows)");
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  return h("div", {style: "overflow:auto;max-height:220px"}, h("table", {class: "grid"},
    h("tr", {}, cols.map((c) => h("th", {}, c))), rows.map((r) => h("tr", {}, cols.map((c) => h("td", {}, showVal("", r[c])))))));
}

function condTable(n) {
  const rows = n.conditions;
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const tbl = h("table", {class: "grid cond-table"});
  tbl.append(h("tr", {}, cols.map((c) => h("th", {}, h("input", {value: c, onchange: (e) => {
    const nc = e.target.value.trim();
    if (nc && nc !== c && cols.includes(nc)) { toast(`There is already a column “${nc}”`); e.target.value = c; return; }
    rows.forEach((r, i) => {   // rebuild each row so the renamed column keeps its position
      const out = {};
      for (const [k, v] of Object.entries(r)) { if (k === c) { if (nc) out[nc] = v; } else out[k] = v; }
      rows[i] = out;
    });
    commit(); }}))), h("th", {}, h("button", {class: "mini", title: "add column", onclick: () => { const nc = uniqueId("column", new Set(cols)); rows.forEach((r) => r[nc] = ""); if (!rows.length) rows.push({[nc]: ""}); commit(); }}, "+"))));
  rows.forEach((r, i) => tbl.append(h("tr", {}, cols.map((c) => h("td", {}, h("input", {value: showVal("", r[c]), onchange: (e) => {
    const raw = e.target.value; r[c] = raw !== "" && !isNaN(Number(raw)) ? Number(raw) : raw; commit(); }}))),
    h("td", {}, h("button", {class: "mini danger", onclick: () => { rows.splice(i, 1); commit(); }}, "×")))));
  return h("div", {class: "field"}, h("label", {}, "trial list: one row per trial, one column per thing that changes"),
    cols.length ? null : h("div", {class: "help"}, "Empty table: click + to add a column, then + row."),
    h("div", {style: "overflow:auto"}, tbl),
    h("button", {class: "mini", style: "margin-top:4px", onclick: () => { rows.push(Object.fromEntries(cols.map((c) => [c, ""]))); commit(); }}, "+ row"));
}

function renderDeviceProps(el, d, index, title) {
  const info = S.schema.devices[d.type] || {options: {}, capabilities: []};
  title.textContent = `Device · ${d.id}`;
  el.append(h("div", {class: "desc"}, info.description || d.type, " ", helpLink("reference/devices", d.type),
    info.available === false ? h("div", {style: "color:var(--warn);margin-top:4px"}, "⚠ " + info.unavailable_reason) : null));
  el.append(field("id", {type: "str"}, d.id, (v) => { if (v) { d.id = v; commit(); } }, {noExpr: true}));
  el.append(field("type", {type: "choice", choices: Object.keys(S.schema.devices)}, d.type, (v) => { d.type = v; d.options = {}; commit(); }, {noExpr: true}));
  for (const [k, help] of [["required", "abort if it can't connect"], ["record", "save its data streams"], ["markers", "receive event markers"], ["calibrate", "calibrate at session start"]])
    el.append(field(k, {type: "bool", help}, d[k] ?? (k !== "calibrate"), (v) => { d[k] = v; commit(); }, {noExpr: true}));
  el.append(h("div", {class: "group"}, "Options"));
  d.options ||= {};
  for (const [k, p] of Object.entries(info.options || {})) el.append(field(k, p, d.options[k], (v) => { if (v === null) delete d.options[k]; else d.options[k] = v; commit(); }, {noExpr: true}));
  el.append(h("div", {class: "btns"}, h("button", {class: "danger", onclick: () => { S.exp.devices.splice(index, 1); S.sel = null; commit(); }}, "Remove device")));
}

function renderSettings(el, title) {
  title.textContent = "Experiment settings";
  const st = S.exp.settings; st.window ||= {}; st.data ||= {}; st.participant ||= {};
  const def = S.schema.default_settings;
  el.append(field("name", {type: "str"}, S.exp.name, (v) => { S.exp.name = v || "experiment"; commit(); }, {noExpr: true}));
  el.append(field("description", {type: "text"}, S.exp.description, (v) => setProp(S.exp, "description", v), {noExpr: true}));
  el.append(h("div", {class: "group"}, "Window"));
  const w = st.window, dw = def.window;
  el.append(field("size", {type: "vec2", default: dw.size}, w.size, (v) => setProp(w, "size", v), {noExpr: true}));
  el.append(field("fullscreen", {type: "bool"}, w.fullscreen ?? dw.fullscreen, (v) => setProp(w, "fullscreen", v), {noExpr: true}));
  el.append(field("screen", {type: "int", default: 0}, w.screen, (v) => setProp(w, "screen", v), {noExpr: true}));
  el.append(field("background", {type: "color", default: dw.background}, w.background, (v) => setProp(w, "background", v), {noExpr: true}));
  el.append(field("units", {type: "choice", choices: ["px", "norm", "height", "deg"]}, w.units ?? dw.units, (v) => setProp(w, "units", v), {noExpr: true}));
  el.append(field("monitor", {type: "dict", help: "width_cm, distance_cm (for deg units)", default: dw.monitor}, w.monitor, (v) => setProp(w, "monitor", v), {noExpr: true}));
  el.append(h("div", {class: "group"}, "Participant & data"));
  el.append(field("participant fields", {type: "dict", help: "default values; override with edge run -p / -s / -f key=value"}, st.participant, (v) => setProp(st, "participant", v), {noExpr: true}));
  el.append(field("data folder", {type: "str", default: def.data.dir}, st.data.dir, (v) => setProp(st.data, "dir", v), {noExpr: true}));
  el.append(field("file name pattern", {type: "str", default: def.data.filename}, st.data.filename, (v) => setProp(st.data, "filename", v), {noExpr: true}));
  el.append(field("seed", {type: "int", help: "fix randomization (empty = new random seed per session, saved in session.json)"}, st.seed, (v) => setProp(st, "seed", v), {noExpr: true}));
  el.append(h("div", {class: "group"}, "Markers & variables"));
  st.markers ||= {};
  el.append(field("marker codes", {type: "dict", help: '{"stim_on": 10, "response": 20}; unlisted labels get codes automatically'}, st.markers.codes, (v) => setProp(st.markers, "codes", v), {noExpr: true}));
  el.append(field("variables", {type: "dict", help: "initial values of experiment variables, e.g. {\"score\": 0}"}, S.exp.variables, (v) => { S.exp.variables = v || {}; commit(); }, {noExpr: true}));
}

/* ---------------- preview */
function sampleRowFor(rid) {
  // first condition row of the innermost inline/factorial loop containing this routine
  let row = {};
  walkFlow((n, path) => {
    if (routineOfNode(n) !== rid) return;
    let cur = S.exp.flow;
    for (const p of path) { if (cur && cur.loop !== undefined) row = {...row, ...firstRow(cur.conditions)};
      if (cur && cur.loop !== undefined && cur.staircase) row[cur.staircase.variable || "level"] = cur.staircase.start;
      cur = cur[p]; }
  });
  return {...S.exp.variables, ...row};
}

const _condCache = {};
function firstRow(spec) {
  if (!spec) return {};
  if (Array.isArray(spec)) return spec[0] || {};
  const key = JSON.stringify(spec) + "|" + (S.path || "");
  if (key in _condCache) return _condCache[key];
  _condCache[key] = {};
  api(`/api/conditions?spec=${encodeURIComponent(JSON.stringify(spec))}&exp=${encodeURIComponent(S.path || "")}`)
    .then((j) => { _condCache[key] = j.rows[0] || {}; renderPreview(); }).catch(() => {});
  return {};
}

function previewVal(v, row) {
  if (!isExpr(v)) return v;
  const src = v.slice(1).trim();
  if (/^[A-Za-z_]\w*$/.test(src)) return src in row ? row[src] : v;
  try {  // best-effort preview of simple expressions; real evaluation happens in Python
    // eslint-disable-next-line no-new-func
    return Function(...Object.keys(row), `"use strict"; return (${src.replace(/^f(['"])/, "`").replace(/(['"])$/, "`").replace(/\{/g, "${")});`)(...Object.values(row));
  } catch { return v; }
}

function renderPreview() {
  const t = S.previewT; $("#preview-label").textContent = `t = ${t.toFixed(2)} s`;
  // HTML pages are previewed live in an iframe on top of the canvas
  const frame = $("#preview-html");
  const page = comps(S.routine).find((c) => (c.type === "html" || c.type === "survey") && numOr(c.start, 0) <= t && (c.duration == null || t < numOr(c.start, 0) + c.duration));
  if (page && page.type === "survey") {
    const html = typeof surveyPreviewHtml === "function" ? surveyPreviewHtml(page, renderPreview) : null;
    if (html && frame.dataset.survey !== html.length + ":" + html.slice(-200)) { frame.removeAttribute("src"); frame.dataset.src = ""; frame.srcdoc = html; frame.dataset.survey = html.length + ":" + html.slice(-200); }
    frame.classList.remove("hidden");
  } else if (page && (page.file || page.html)) {
    frame.dataset.survey = "";
    if (page.file && !isExpr(page.file)) {
      const src = `/api/file?path=${encodeURIComponent((S.path ? S.path.replace(/[^/]*$/, "") : "") + page.file)}`;
      if (frame.dataset.src !== src) { frame.removeAttribute("srcdoc"); frame.src = src; frame.dataset.src = src; }
    } else if (page.html) { frame.dataset.src = ""; frame.srcdoc = page.html; }
    frame.classList.remove("hidden");
  } else frame.classList.add("hidden");
  const cv = $("#preview");
  const want = Math.round((cv.clientWidth || 480) * Math.min(2, window.devicePixelRatio || 1));
  if (cv.width !== want) cv.width = want;
  drawScreen(cv, S.routine, t);
  if (typeof drawStageOverlay === "function") drawStageOverlay(cv);
}

/* Draw one screen (routine) at time t onto a canvas, with values from its trial list's first row. */
function drawScreen(cv, rid, t, row) {
  const ctx = cv.getContext("2d");
  const win = S.exp.settings.window || {};
  const [W, H] = win.size || [1280, 720];
  cv.height = Math.round(cv.width * H / W);
  const k = cv.width / W;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = win.background || "#000"; ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.translate(cv.width / 2, cv.height / 2); ctx.scale(k, -k);
  const winUnits = win.units || "px";
  let units = winUnits;
  const conv = (v, axis) => units === "norm" ? v * (axis === "x" ? W / 2 : H / 2) : units === "height" ? v * H : v;
  const pos = (p) => Array.isArray(p) ? [conv(+p[0] || 0, "x"), conv(+p[1] || 0, "y")] : [0, 0];
  row = row || sampleRowFor(rid);
  cv._boxes = []; cv._k = k; cv._W = W; cv._H = H;
  const box = (c, hw, hh) => cv._boxes.push({id: c.id, type: c.type, x: pos(c.pos || [0, 0])[0], y: pos(c.pos || [0, 0])[1], hw, hh, rot: numOr(c.ori, 0), units});
  for (const c0 of comps(rid)) {
    const c = Object.fromEntries(Object.entries(c0).map(([kk, v]) => [kk, previewVal(v, row)]));
    const st = numOr(c.start, 0), du = numOr(c.duration, Infinity);
    if (c.start_after || c.start_if || t < st || t >= st + du || c.disabled === true) continue;
    units = c.units && ["px", "norm", "height"].includes(c.units) ? c.units : winUnits;
    const [x, y] = pos(c.pos || [0, 0]);
    ctx.save(); ctx.translate(x, y); ctx.globalAlpha = Math.max(0, Math.min(1, typeof c.opacity === "number" ? c.opacity : 1));
    ctx.rotate(-(numOr(c.ori, 0)) * Math.PI / 180);
    const color = (v, d) => (typeof v === "string" && !isExpr(v) ? v : d);
    if (c.type === "text") {
      if (isExpr(c.text)) {   // computed while the experiment runs (e.g. feedback): show a readable stand-in
        const m = c.text.match(/^\$\s*f?(['"])(.*)\1\s*$/) || c.text.match(/^\$\s*(['"])(.*?)\1\s+if\b/);
        c.text = m ? m[2].replace(/\{[^}]*\}/g, "…") : (cv.id === "preview" ? c.text : "(depends on the trial)");
      }
      ctx.scale(1, -1); ctx.fillStyle = color(c.color, "#fff");
      const hgt = conv(numOr(c.height, 40), "y"); ctx.font = `${c.bold ? "bold " : ""}${hgt}px sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.direction = c.direction === "rtl" || (c.direction !== "ltr" && /[\u0590-\u05ff\ufb1d-\ufb4f]/.test(String(c.text ?? ""))) ? "rtl" : "ltr";
      const lines = String(c.text ?? "").split("\n"); lines.forEach((ln, i) => ctx.fillText(ln, 0, (i - (lines.length - 1) / 2) * hgt * 1.25));
      box(c, Math.max(hgt / 2, ...lines.map((ln) => ctx.measureText(ln).width / 2)), lines.length * hgt * 1.25 / 2);
    } else if (c.type === "shape" || c.type === "fixation") {
      const shape = c.shape || (c.type === "fixation" ? "cross" : "rect");
      ctx.fillStyle = color(c.fill, "#fff"); ctx.strokeStyle = color(c.line_color, color(c.fill, "#fff"));
      ctx.lineWidth = numOr(c.line_width, shape === "cross" ? 4 : 2);
      const sz = Array.isArray(c.size) ? [conv(c.size[0], "x"), conv(c.size[1], "y")] : [conv(numOr(c.size, shape === "cross" ? 40 : 100), "y"), conv(numOr(c.size, 100), "y")];
      const r = conv(numOr(c.radius, 50), "y");
      if (shape === "circle") box(c, r, r);
      else if (shape === "polygon" && Array.isArray(c.vertices) && c.vertices.length) { const m = Math.max(10, ...c.vertices.flatMap(([vx, vy]) => [Math.abs(conv(vx, "x")), Math.abs(conv(vy, "y"))])); box(c, m, m); }
      else if (shape === "cross") box(c, sz[0] / 2, sz[0] / 2);
      else if (shape !== "line") box(c, sz[0] / 2, sz[1] / 2);
      if (shape === "rect") { ctx.fillRect(-sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); if (c.line_color) ctx.strokeRect(-sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); }
      else if (shape === "circle") { ctx.beginPath(); ctx.arc(0, 0, r, 0, 2 * Math.PI); ctx.fill(); if (c.line_color) ctx.stroke(); }
      else if (shape === "ellipse") { ctx.beginPath(); ctx.ellipse(0, 0, sz[0] / 2, sz[1] / 2, 0, 0, 2 * Math.PI); ctx.fill(); if (c.line_color) ctx.stroke(); }
      else if (shape === "line") { const a = pos(c.start || [-50, 0]), b = pos(c.end || [50, 0]); ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
        box(c, Math.max(6, Math.abs(a[0]), Math.abs(b[0])), Math.max(6, Math.abs(a[1]), Math.abs(b[1]))); }
      else if (shape === "cross") { const s = sz[0] / 2; ctx.beginPath(); ctx.moveTo(-s, 0); ctx.lineTo(s, 0); ctx.moveTo(0, -s); ctx.lineTo(0, s); ctx.stroke(); }
      else if (shape === "polygon" && Array.isArray(c.vertices) && c.vertices.length) { ctx.beginPath(); c.vertices.forEach(([vx, vy], i) => i ? ctx.lineTo(conv(vx, "x"), conv(vy, "y")) : ctx.moveTo(conv(vx, "x"), conv(vy, "y"))); ctx.closePath(); ctx.fill(); }
    } else if (c.type === "image" && typeof c.image === "string" && c.image && !isExpr(c.image)) {
      const img = imgCache(c.image);
      if (img.complete && img.naturalWidth) { const sz = Array.isArray(c.size) ? [conv(c.size[0], "x"), conv(c.size[1], "y")] : [img.naturalWidth, img.naturalHeight];
        ctx.scale(1, -1); ctx.drawImage(img, -sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); box(c, sz[0] / 2, sz[1] / 2); }
      else { ctx.strokeStyle = "#888"; ctx.strokeRect(-100, -75, 200, 150); box(c, 100, 75); }
    } else if (c.type === "image") {
      ctx.strokeStyle = "#888"; ctx.setLineDash([6, 4]); ctx.strokeRect(-100, -75, 200, 150);
      ctx.scale(1, -1); ctx.fillStyle = "#888"; ctx.font = "22px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(c.image ? "picture from the trial list" : "click “Choose…” to pick a picture", 0, 0); box(c, 100, 75);
    } else if (c.type === "slider") {
      const sz = Array.isArray(c.size) ? c.size : [800, 30]; ctx.fillStyle = color(c.color, "#fff");
      ctx.fillRect(-sz[0] / 2, -2, sz[0], 4); box(c, sz[0] / 2, Math.max(10, sz[1] / 2));
    } else if (c.type === "survey" && cv.id !== "preview") {
      ctx.scale(1, -1); ctx.fillStyle = "#f7f8fa"; ctx.fillRect(-W * 0.32, -H * 0.4, W * 0.64, H * 0.8);
      ctx.fillStyle = "#2f6fde"; ctx.fillRect(-W * 0.28, -H * 0.33, W * 0.3, H * 0.025);
      for (let k = 0; k < 4; k++) { ctx.fillStyle = "#fff"; ctx.fillRect(-W * 0.28, -H * 0.27 + k * H * 0.15, W * 0.56, H * 0.12);
        ctx.fillStyle = "#c5ccd6"; for (let j = 0; j < 5; j++) { ctx.beginPath(); ctx.arc(-W * 0.12 + j * W * 0.08, -H * 0.2 + k * H * 0.15, H * 0.018, 0, 7); ctx.fill(); } }
      ctx.fillStyle = "#333"; ctx.font = `bold ${H * 0.05}px sans-serif`; ctx.textAlign = "center";
      ctx.fillText(`survey · ${(c0.questions || []).filter((q) => q.type !== "page_break").length} question block(s)`, 0, H * 0.36);
    } else if (c.type === "html" && cv.id !== "preview") {
      ctx.scale(1, -1); ctx.fillStyle = "#fff"; ctx.fillRect(-W * 0.3, -H * 0.35, W * 0.6, H * 0.7);
      ctx.fillStyle = "#555"; ctx.font = `${H * 0.06}px sans-serif`; ctx.textAlign = "center"; ctx.fillText("web page", 0, 0);
    } else if (c.type === "sound") {
      ctx.scale(1, -1); ctx.fillStyle = "#9ab"; ctx.font = `${H * 0.12}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("♪", 0, -H * 0.3);
    } else if (c.type === "gaze_roi" && !c.target) {
      ctx.strokeStyle = "#a070ff"; ctx.setLineDash([8, 6]); ctx.lineWidth = 2;
      if ((c.shape || "circle") === "circle") { const r = conv(numOr(c.radius, 100), "y"); ctx.beginPath(); ctx.arc(0, 0, r, 0, 2 * Math.PI); ctx.stroke(); box(c, r, r); }
      else { const sz = Array.isArray(c.size) ? [conv(c.size[0], "x"), conv(c.size[1], "y")] : [200, 200]; ctx.strokeRect(-sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); box(c, sz[0] / 2, sz[1] / 2); }
    }
    ctx.restore();
  }
}
const _imgs = {};
function imgCache(src) { if (!_imgs[src]) { const im = new Image(); im.onload = () => { renderPreview(); if (S.view === "story") renderTimeline(); };
  im.src = `/api/file?path=${encodeURIComponent((S.path ? S.path.replace(/[^/]*$/, "") : "") + src)}`; _imgs[src] = im; } return _imgs[src]; }

/* ---------------- play the preview at real speed */
let _play = null;
function playPreview() {
  const btn = $("#preview-play");
  if (_play) { cancelAnimationFrame(_play.raf); _play = null; btn.textContent = "▶"; return; }
  const span = routineSpan(S.routine);
  const t0 = performance.now() - (S.previewT >= span - 0.02 ? 0 : S.previewT * 1000);
  btn.textContent = "❚❚";
  const step = () => {
    S.previewT = Math.min(span, (performance.now() - t0) / 1000);
    $("#preview-t").value = S.previewT; renderPreview(); renderTimeline();
    if (S.previewT >= span) { _play = null; btn.textContent = "▶"; return; }
    _play.raf = requestAnimationFrame(step);
  };
  _play = {raf: requestAnimationFrame(step)};
}

/* ---------------- console: issues, results, source, hardware */
let _vt = null;
function scheduleValidate() { clearTimeout(_vt); _vt = setTimeout(validate, 400); }
async function validate() {
  try { S.issues = (await api("/api/validate", {experiment: S.exp, path: S.path})).issues; }
  catch (e) { S.issues = [{level: "error", where: "server", message: e.message}]; }
  renderIssues();
}
function renderIssues() {
  const el = $("#tab-issues"); el.innerHTML = "";
  const n = S.issues.filter((i) => i.level === "error").length, w = S.issues.filter((i) => i.level === "warning").length;
  $("#issue-count").textContent = n || w ? `(${n}/${w})` : "✓";
  const shown = S.issues.filter((i) => S.mode === "expert" || i.level !== "info");
  if (!shown.length) { el.append(h("div", {class: "ok"}, "✓ No problems found. Press ▶ Try it to do it yourself, or ▶ Test run for a quick automatic check.")); return; }
  const word = {error: "Must fix", warning: "Check", info: "Note"};
  for (const i of shown) el.append(h("div", {class: `issue ${i.level}`, onclick: () => gotoIssue(i), title: "click to go there"},
    h("span", {class: "lvl"}, word[i.level] || i.level), " ", h("span", {class: "msg"}, cap(i.message)),
    i.hint ? h("span", {class: "hint"}, " · " + i.hint) : null, h("span", {class: "where"}, "  " + friendlyWhere(i.where))));
}
const cap = (t) => String(t).charAt(0).toUpperCase() + String(t).slice(1);
function friendlyWhere(w) {
  const m = String(w).match(/^routines\.([^.]+)(?:\.([^.\[]+))?(?:\.(\w+))?/);
  if (m) return `screen “${m[1]}”` + (m[2] && m[2] !== "rules" ? ` › ${m[2]}` : "") + (m[3] ? ` › ${FIELD_LABELS[m[3]] || m[3]}` : "");
  if (w.startsWith("devices.")) return `device “${w.slice(8)}”`;
  if (w.startsWith("flow")) return "flow";
  return w;
}
function gotoIssue(i) {
  const m = i.where.match(/^routines\.([^.]+)(?:\.([^.]+))?/);
  if (m && S.exp.routines[m[1]]) { S.routine = m[1]; S.view = "screen"; S.sel = m[2] && findComp(m[1], m[2]) ? {kind: "component", routine: m[1], id: m[2]} : {kind: "routine", routine: m[1]}; renderAll(); }
  const d = i.where.match(/^devices\.(.+)/);
  if (d) { const idx = S.exp.devices.findIndex((x) => x.id === d[1]); if (idx >= 0) { S.sel = {kind: "device", index: idx}; renderAll(); } }
}

function showTab(name) {
  S.tab = name; setTimeout(() => checkTutorial(), 0);
  document.querySelectorAll("#console .tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll("#console .tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
  if (name === "source") renderSource();
  if (name === "data") renderData();
}

async function renderSource() { $("#yaml").value = (await api("/api/to_yaml", S.exp)).yaml; }

async function dryRun() {
  showTab("results");
  const el = $("#tab-results"); el.innerHTML = "A virtual participant is doing the whole experiment (a few seconds)…";
  try {
    const r = await api("/api/dryrun", {experiment: S.exp, path: S.path});
    if (!r.ok) { el.innerHTML = ""; el.append(h("div", {class: "issue error"}, "Fix errors first:"), r.issues.map((i) => h("div", {class: "issue error"}, `${i.where}: ${i.message}`))); return; }
    renderResults(r);
  } catch (e) { el.innerHTML = ""; el.append(h("pre", {class: "issue error"}, e.message)); }
}

function renderResults(r) {
  S.lastDryRun = Date.now(); setTimeout(() => checkTutorial(), 0);
  const el = $("#tab-results"); el.innerHTML = "";
  const t = r.summary.timing || {}, rep = r.report;
  const kpi = (v, l) => h("div", {class: "kpi"}, h("b", {}, v), h("span", {}, l));
  const mins = t.frames && t.refresh_rate_hz ? (t.frames / t.refresh_rate_hz / 60).toFixed(1) + " min" : "–";
  const corr = r.trials.flatMap((row) => Object.entries(row).filter(([k, v]) => k.endsWith(".corr") && typeof v === "number").map(([, v]) => v));
  el.append(h("div", {class: "kpis"}, kpi(mins, "session length"), kpi(r.n_trials ?? r.trials.length, r.n_trials != null ? "trials" : "screens shown"),
    corr.length ? kpi(Math.round(100 * corr.reduce((a, b) => a + b, 0) / corr.length) + "%", "correct (virtual participant)") : null,
    S.mode === "expert" ? kpi(Object.keys(r.summary.devices).length, "devices (simulated)") : null,
    S.mode === "expert" ? kpi(Object.keys(r.summary.marker_codebook).length, "marker labels") : null,
    kpi(r.summary.errors.length, "errors")));
  el.append(h("div", {class: "help", style: "margin-bottom:6px"}, "A virtual participant just did the whole experiment with simulated hardware. Want to do it yourself? Press ▶ Try it."));
  el.append(h("div", {}, rep.verdict.map((v) => h("div", {class: v.startsWith("OK") ? "ok" : "issue warning"}, v))));
  const streams = Object.entries(rep.streams);
  if (streams.length) {
    el.append(h("h3", {style: "margin-top:10px"}, "Streams & synchronization"));
    el.append(h("table", {class: "grid"}, h("tr", {}, ["stream", "samples", "rate (Hz)", "gaps", "clock model", "triggers", "alignment (ms)"].map((x) => h("th", {}, x))),
      streams.map(([name, s]) => h("tr", {}, h("td", {}, name), h("td", {}, s.samples), h("td", {}, s.effective_srate ?? "–"), h("td", {}, s.gaps ?? "–"),
        h("td", {}, s.clock_model && s.clock_model.method !== "identity" ? `${s.clock_model.method}, drift ${((s.clock_model.slope - 1) * 1e6).toFixed(1)} ppm` : "master"),
        h("td", {}, s.triggers ? `${s.triggers.matched}/${s.triggers.expected}` : "–"),
        h("td", {}, s.triggers && s.triggers.latency_mean_ms != null ? `${s.triggers.latency_mean_ms} ± ${s.triggers.latency_sd_ms ?? 0} (max ${s.triggers.latency_max_abs_ms})` : "–")))));
  }
  el.append(h("h3", {style: "margin-top:10px"}, `Data preview (${r.summary.data_dir})`));
  el.append(rowsTable(r.trials.slice(0, 60)));
}

async function scanHardware() {
  showTab("hardware");
  const el = $("#tab-hardware"); el.innerHTML = "Scanning LSL network, serial ports, Tobii and Gazepoint…";
  try {
    const r = await api("/api/scan?timeout=1.5"); el.innerHTML = "";
    for (const [sec, items] of Object.entries(r)) {
      el.append(h("h3", {style: "margin-top:8px"}, sec.replace("_", " ")));
      if (!items.length) el.append(h("div", {class: "help", style: "color:var(--muted)"}, "none found"));
      for (const it of items) {
        const {suggested, ...rest} = it;
        el.append(h("div", {style: "display:flex;gap:8px;align-items:center;margin:3px 0"},
          h("code", {}, Object.entries(rest).map(([k, v]) => `${k}=${v}`).join("  ")),
          suggested ? h("button", {class: "mini", onclick: () => addDevice(suggested.type, suggested.options)}, "+ add") : null));
      }
    }
  } catch (e) { el.textContent = e.message; }
}

function addDevice(type, options = {}) {
  const id = uniqueId(type.split("_")[0], new Set(S.exp.devices.map((d) => d.id)));
  S.exp.devices.push({id, type, options});
  S.sel = {kind: "device", index: S.exp.devices.length - 1}; commit(); toast(`Added ${type} as “${id}”`);
}

function deviceMenu(e) {
  const groups = {};
  for (const [type, d] of Object.entries(S.schema.devices)) (groups[d.capabilities.includes("gaze") ? "Eye tracking" : d.capabilities.includes("ttl") ? "Triggers / TTL" : type.startsWith("sim") || type === "mouse_gaze" ? "Simulated" : "Streams / physiology"] ||= []).push([type, d]);
  const items = [];
  for (const [g, list] of Object.entries(groups)) { if (items.length) items.push("-");
    for (const [type, d] of list) items.push([`${type} — ${g}`, () => addDevice(type)]); }
  menu(e, items);
}

async function runReal() {
  if (!S.path || S.dirty) { await save(); if (!S.path) return; }
  const simulate = confirm("Simulate hardware? (OK = simulated devices, Cancel = real hardware)");
  const {run_id} = await api("/api/run", {path: S.path, simulate});
  showTab("results");
  const el = $("#tab-results");
  const poll = async () => { const st = await api(`/api/run_status?id=${run_id}`);
    el.innerHTML = ""; el.append(h("pre", {style: "font-family:var(--mono);font-size:12px"}, st.output.join("\n") || "starting…"));
    if (st.running) setTimeout(poll, 700); else toast(`Run finished (exit ${st.returncode})`); };
  poll();
}

async function newFromTemplate() {
  const body = $("#modal-body"); body.innerHTML = "";
  body.append(h("h3", {}, "New experiment from template"));
  for (const [key, t] of Object.entries(S.schema.templates)) body.append(h("div", {class: "choice", onclick: async () => {
    if (S.dirty && !confirm("Discard unsaved changes?")) return;
    closeModal(); loadDoc(clone(await api(`/api/template?name=${key}`)), null); }}, h("b", {}, key), h("small", {}, t.description || t.name)));
  openModal();
}

async function openDialog() {
  const {files, root} = await api("/api/files");
  const body = $("#modal-body"); body.innerHTML = "";
  body.append(h("h3", {}, `Open experiment (${root})`));
  if (!files.length) body.append(h("div", {class: "help"}, "No experiment files in this folder yet."));
  for (const f of files) body.append(h("div", {class: "choice", onclick: async () => {
    if (S.dirty && !confirm("Discard unsaved changes?")) return; closeModal(); await openFile(f.path); }}, h("b", {}, f.name), h("small", {}, f.path)));
  openModal();
}
function openModal() { $("#modal").classList.remove("hidden"); const box = $(".modal-box"); box.scrollTop = 0; box.scrollLeft = 0; }
function _resetModal() { $("#modal-body").className = ""; }
function closeModal() { $("#modal").classList.add("hidden"); _resetModal(); }

/* ---------------- wiring */
function wire() {
  $("#btn-new").onclick = () => welcome();
  $("#btn-import").onclick = () => { const inp = h("input", {type: "file", multiple: true, onchange: (e) => importFiles([...e.target.files])}); inp.click(); };
  $("#btn-help").onclick = () => openHelp();
  $("#btn-open").onclick = openDialog;
  $("#btn-save").onclick = () => save();
  $("#btn-versions").onclick = versionsDialog;
  $("#btn-bundle").onclick = () => { if (!S.path) return toast("Save the experiment first");
    if (S.dirty) toast("Bundling the saved version (you have unsaved changes)");
    location.href = `/api/bundle?path=${encodeURIComponent(S.path)}`; };
  $("#btn-undo").onclick = undo; $("#btn-redo").onclick = redo;
  $("#btn-settings").onclick = () => { S.sel = {kind: "settings"}; renderAll(); };
  $("#btn-validate").onclick = () => { validate(); showTab("issues"); };
  $("#btn-dryrun").onclick = dryRun;
  $("#btn-run").onclick = () => (typeof runDialog === "function" ? runDialog() : runReal());
  $("#btn-try").onclick = () => tryIt();
  $("#btn-mode").onclick = () => setMode(S.mode === "simple" ? "expert" : "simple");
  $("#preview-play").onclick = () => playPreview();
  applyMode();
  $("#btn-scan").onclick = scanHardware;
  $("#btn-add-device").onclick = deviceMenu;
  $("#palette-filter").oninput = renderPalette;
  $("#btn-apply-yaml").onclick = async () => { try { const {experiment} = await api("/api/from_yaml", {yaml: $("#yaml").value});
    S.exp = normalize(experiment); fixSelection(); commit(); toast("YAML applied"); } catch (e) { toast("YAML error: " + e.message, 4000); } };
  document.querySelectorAll("#console .tabs button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
  $("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };
  $("#preview-t").oninput = (e) => { S.previewT = +e.target.value; renderPreview(); renderTimeline(); };
  const tl = $("#timeline");
  tl.ondragover = (e) => e.preventDefault();
  tl.ondrop = (e) => { const type = e.dataTransfer.getData("edge/component"); if (!type) return; e.preventDefault();
    const row = e.target.closest(".tl-row"); addComponent(type, row ? +row.dataset.idx + 1 : undefined); };
  document.addEventListener("keydown", (e) => {
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !typing) { e.preventDefault(); e.shiftKey ? redo() : undo(); }
    else if ((e.key === "Delete" || e.key === "Backspace") && !typing && S.sel?.kind === "component") {
      const list = comps(S.sel.routine); const i = list.findIndex((c) => c.id === S.sel.id);
      if (i >= 0) { list.splice(i, 1); S.sel = {kind: "routine", routine: S.routine}; commit(); } }
    else if (e.key === "Escape") closeModal();
    else if (e.key === "?" && !typing) openHelp();
  });
  window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
}

window.addEventListener("DOMContentLoaded", () => boot().catch((e) => {
  document.body.innerHTML = `<pre style="padding:20px;color:#d33">Failed to start: ${e.message}</pre>`; }));


/* ================================================================== workflow: state machines */
function renderMachine(n, path, selected) {
  const box = h("div", {class: "fl-box sm" + (selected ? " sel" : "")});
  box.append(h("div", {class: "fl-head", onclick: (e) => { e.stopPropagation(); S.sel = {kind: "machine", path}; renderAll(); },
    oncontextmenu: (e) => { e.preventDefault(); e.stopPropagation(); nodeMenu(e, path); }},
    `⚙ ${n.statemachine} · workflow`, h("span", {class: "sm-hint"}, " click to see the diagram")));
  const row = h("div", {class: "sm-states"});
  for (const [name, st] of Object.entries(n.states || {})) {
    const isSel = S.sel?.kind === "state" && samePath(S.sel.path, path) && S.sel.name === name;
    row.append(h("div", {class: "sm-state" + (n.start === name ? " start" : "") + (isSel ? " sel" : "")},
      h("div", {class: "sm-name", onclick: (e) => { e.stopPropagation(); S.sel = {kind: "state", path, name}; renderAll(); }},
        (n.start === name ? "▶ " : "") + name, st.max_visits ? h("span", {class: "sm-hint"}, ` ≤${st.max_visits}×`) : ""),
      renderSeq(st.run ||= [], [...path, "states", name, "run"]),
      h("div", {class: "sm-next"}, describeTransitions(st))));
  }
  row.append(h("button", {class: "mini", title: "Add a state", onclick: (e) => { e.stopPropagation(); addState(path); }}, "+ state"));
  box.append(row);
  return box;
}
function describeTransitions(st) {
  const nx = st.next || [];
  if (!nx.length) return "→ end";
  return nx.map((t) => typeof t === "string" ? `→ ${t}` : (t.if ? `→ ${t.goto} if ${short(t.if.replace(/^\$/, ""), 28)}` : `→ ${t.goto}`)).join(" · ");
}
function short(s, n = 40) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
function addState(path) {
  const m = getNode(path);
  const name = prompt("Name of the new state (e.g. practice, main, debrief):", uniqueId("state", new Set(Object.keys(m.states))));
  if (!name) return;
  const id = uniqueId(name, new Set(Object.keys(m.states)));
  m.states[id] = {run: [], next: [{goto: "end"}]};
  S.sel = {kind: "state", path, name: id}; commit();
}
function renameState(path, old) {
  const m = getNode(path);
  const nn = prompt("Rename state:", old);
  if (!nn || nn === old) return;
  if (m.states[nn]) return toast("A state with that name exists");
  const states = {};
  for (const [k, v] of Object.entries(m.states)) states[k === old ? nn : k] = v;
  for (const st of Object.values(states)) for (const t of st.next || []) if (typeof t === "object" && t.goto === old) t.goto = nn;
  m.states = states;
  if (m.start === old) m.start = nn;
  S.sel = {kind: "state", path, name: nn}; commit();
}

function layoutMachine(m) {
  const names = Object.keys(m.states || {});
  const col = {}, queue = [m.start];
  if (m.start in m.states) col[m.start] = 0;
  while (queue.length) {
    const cur = queue.shift();
    for (const t of (m.states[cur]?.next || [])) {
      const g = typeof t === "string" ? t : t.goto;
      if (g in m.states && !(g in col)) { col[g] = col[cur] + 1; queue.push(g); }
    }
  }
  let maxc = Math.max(0, ...Object.values(col));
  for (const n of names) if (!(n in col)) col[n] = ++maxc;
  const rows = {}, pos = {};
  const W = 160, H = 64, GX = 150, GY = 56;
  for (const n of names) { const c = col[n]; rows[c] = (rows[c] || 0); pos[n] = {x: 30 + c * (W + GX), y: 40 + rows[c] * (H + GY), w: W, h: H}; rows[c]++; }
  const endCol = Math.max(0, ...Object.values(col)) + 1;
  pos.end = {x: 30 + endCol * (W + GX), y: 70, w: 70, h: H, end: true};
  for (const p of Object.values(pos)) p.y += 30;   // room for routes that arc over the states
  return pos;
}

function renderDiagram(el) {
  const path = S.sel.path;
  let m;
  try { m = getNode(path); } catch { m = null; }
  if (!m || m.statemachine === undefined) { S.sel = null; return renderTimeline(); }
  const pos = layoutMachine(m);
  const W = Math.max(...Object.values(pos).map((p) => p.x + p.w)) + 60;
  const H = Math.max(...Object.values(pos).map((p) => p.y + p.h)) + 90;
  el.append(h("div", {class: "tl-routine-info"}, `Workflow “${m.statemachine}”: after a state finishes, its routes are checked top to bottom and the first true one is taken. Click a state to edit it.`));
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("width", W); svg.setAttribute("class", "wf");
  svg.style.maxWidth = "100%"; svg.style.height = "auto";
  const mk = (tag, attrs, text) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (text != null) e.textContent = text; return e; };
  const defs = mk("defs", {});
  const marker = mk("marker", {id: "arrow", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse"});
  marker.append(mk("path", {d: "M0,0 L10,5 L0,10 z", class: "wf-arrowhead"}));
  defs.append(marker); svg.append(defs);
  // edges
  for (const [name, st] of Object.entries(m.states)) {
    const a = pos[name];
    (st.next?.length ? st.next : [{goto: "end"}]).forEach((t0, i) => {
      const t = typeof t0 === "string" ? {goto: t0} : t0;
      const b = pos[t.goto] || pos.end;
      const label = t.if ? short(t.if.replace(/^\$/, ""), 22) : ((st.next || []).length > 1 ? "otherwise" : "");
      let d, lx, ly;
      if (t.goto === name) {          // self loop
        const x = a.x + a.w * 0.7, y = a.y;
        d = `M${x - 24},${y} C${x - 40},${y - 50} ${x + 30},${y - 50} ${x + 10},${y}`;
        lx = x - 5; ly = y - 46;
      } else if (b.x > a.x && b.x - (a.x + a.w) < 200) {   // forward to the next column
        const y1 = a.y + a.h / 2 + (i - ((st.next || []).length - 1) / 2) * 12;
        d = `M${a.x + a.w},${y1} C${a.x + a.w + 50},${y1} ${b.x - 50},${b.y + b.h / 2} ${b.x},${b.y + b.h / 2}`;
        lx = (a.x + a.w + b.x) / 2; ly = Math.min(y1, b.y + b.h / 2) - 8;
      } else if (b.x > a.x) {          // forward, skipping states: arc over the top
        const y = Math.min(a.y, b.y) - 22 - i * 12;
        d = `M${a.x + a.w / 2},${a.y} C${a.x + a.w / 2},${y - 20} ${b.x + b.w / 2},${y - 20} ${b.x + b.w / 2},${b.y}`;
        lx = (a.x + b.x + b.w) / 2; ly = y - 12;
      } else {                         // backward: arc underneath
        const y = Math.max(a.y + a.h, b.y + b.h) + 30 + i * 14;
        d = `M${a.x + a.w / 2},${a.y + a.h} C${a.x + a.w / 2},${y} ${b.x + b.w / 2},${y} ${b.x + b.w / 2},${b.y + b.h}`;
        lx = (a.x + b.x + b.w) / 2; ly = y - 2;
      }
      svg.append(mk("path", {d, class: "wf-edge" + (t.if ? "" : " default"), "marker-end": "url(#arrow)"}));
      if (label) svg.append(mk("text", {x: lx, y: ly, class: "wf-label", "text-anchor": "middle"}, label));
    });
  }
  // nodes
  for (const [name, p] of Object.entries(pos)) {
    const g = mk("g", {class: "wf-node" + (p.end ? " end" : "") + (name === m.start ? " start" : "") +
      (S.sel.kind === "state" && S.sel.name === name ? " sel" : ""), transform: `translate(${p.x},${p.y})`});
    if (p.end) {
      g.append(mk("rect", {width: p.w, height: p.h, rx: p.h / 2}));
      g.append(mk("text", {x: p.w / 2, y: p.h / 2 + 5, "text-anchor": "middle"}, "end"));
    } else {
      const st = m.states[name];
      g.append(mk("rect", {width: p.w, height: p.h, rx: 10}));
      g.append(mk("text", {x: 12, y: 24, class: "wf-title"}, (name === m.start ? "▶ " : "") + name));
      const contents = (st.run || []).map((x) => typeof x === "string" ? x : (x.loop ? `⟳${x.loop}` : x.routine || (x.statemachine ? `⚙${x.statemachine}` : "if"))).join(" → ");
      g.append(mk("text", {x: 12, y: 44, class: "wf-sub"}, short(contents || "(empty: add routines)", 24)));
      g.addEventListener("click", () => { S.sel = {kind: "state", path, name}; renderAll(); });
    }
    svg.append(g);
  }
  el.append(h("div", {class: "wf-wrap"}, svg));
}

function renderMachineProps(el, title) {
  const m = getNode(S.sel.path);
  title.textContent = `Workflow · ${m.statemachine}`;
  el.append(h("div", {class: "desc"}, "A state machine runs one state at a time. Each state contains routines or loops; when it finishes, its routes decide the next state (or the end). Use it for practice-until-criterion, adaptive blocks, branching studies or consent screening. ", helpLink("EXPERIMENT_FORMAT", "workflows-state-machines")));
  el.append(field("id", {type: "str"}, m.statemachine, (v) => { if (v) { m.statemachine = v; commit(); } }, {noExpr: true}));
  el.append(field("start state", {type: "choice", choices: Object.keys(m.states)}, m.start, (v) => { m.start = v; commit(); }, {noExpr: true}));
  el.append(field("max_steps", {type: "int", help: "safety limit on state changes"}, m.max_steps, (v) => setProp(m, "max_steps", v), {noExpr: true}));
  el.append(h("div", {class: "help"}, "In expressions: ", h("code", {}, `$${m.statemachine}.state`), ", ", h("code", {}, `$${m.statemachine}.visit`), " (visits of the current state), loop results like ", h("code", {}, "$practice.accuracy"), "."));
  el.append(h("div", {class: "btns"}, h("button", {onclick: () => addState(S.sel.path)}, "+ Add state"),
    h("button", {class: "danger", onclick: () => { const {list, index} = parentOf(S.sel.path); if (confirm("Remove this workflow (its routines stay defined)?")) { list.splice(index, 1); S.sel = null; commit(); } }}, "Remove workflow")));
}

function renderStateProps(el, title) {
  const m = getNode(S.sel.path), name = S.sel.name, st = m.states[name];
  if (!st) { S.sel = {kind: "machine", path: S.sel.path}; return renderProps(); }
  title.textContent = `State · ${name}`;
  el.append(h("div", {class: "desc"}, "Add routines or loops to this state in the Flow strip below (use its + buttons). Then define where to go next."));
  el.append(field("name", {type: "str"}, name, () => renameState(S.sel.path, name), {noExpr: true, readonlyClick: () => renameState(S.sel.path, name)}));
  el.append(field("description", {type: "text"}, st.description, (v) => setProp(st, "description", v), {noExpr: true}));
  el.append(field("max_visits", {type: "int", help: "after this many visits, stop repeating this state and take the first route elsewhere"}, st.max_visits, (v) => setProp(st, "max_visits", v), {noExpr: true}));
  el.append(h("div", {class: "group"}, "Routes (checked top to bottom)"));
  st.next = (st.next || []).map((t) => typeof t === "string" ? {goto: t} : t);
  const targets = [...Object.keys(m.states), "end"];
  st.next.forEach((t, i) => {
    const goto = h("select", {onchange: (e) => { t.goto = e.target.value; commit(); }}, targets.map((x) => { const o = h("option", {value: x}, x === "end" ? "⏹ end" : x); if (t.goto === x) o.selected = true; return o; }));
    const cond = h("input", {class: "expr", list: "expr-vars", value: t.if || "", placeholder: "otherwise (always)",
      onchange: (e) => { const v = e.target.value.trim(); if (v) t.if = v.startsWith("$") ? v : "$" + v; else delete t.if; commit(); }});
    const setv = h("input", {value: t.set ? JSON.stringify(t.set) : "", placeholder: 'set variables, e.g. {"block": 2}',
      onchange: (e) => { try { const v = e.target.value.trim(); if (v) t.set = JSON.parse(v); else delete t.set; commit(); } catch { toast("Not valid JSON"); } }});
    el.append(h("div", {class: "route"},
      h("div", {class: "route-head"}, h("b", {}, i === 0 ? "if" : "else if"), h("span", {style: "flex:1"}),
        h("button", {class: "mini", title: "Move up", onclick: () => { if (i > 0) { [st.next[i - 1], st.next[i]] = [st.next[i], st.next[i - 1]]; commit(); } }}, "↑"),
        h("button", {class: "mini danger", title: "Remove route", onclick: () => { st.next.splice(i, 1); commit(); }}, "×")),
      cond, h("div", {class: "route-goto"}, "go to ", goto), setv));
  });
  el.append(h("div", {class: "btns"},
    h("button", {onclick: () => { st.next.push({if: "$True", goto: name}); commit(); }}, "+ Route"),
    m.start !== name ? h("button", {onclick: () => { m.start = name; commit(); }}, "Make start state") : null,
    h("button", {class: "danger", onclick: () => { if (!confirm(`Delete state ${name}?`)) return; delete m.states[name];
      for (const s2 of Object.values(m.states)) s2.next = (s2.next || []).filter((t) => (typeof t === "string" ? t : t.goto) !== name);
      if (m.start === name) m.start = Object.keys(m.states)[0] || ""; S.sel = {kind: "machine", path: S.sel.path}; commit(); }}, "Delete state")));
  el.append(h("div", {class: "help", style: "margin-top:8px"}, "Example: ", h("code", {}, "$practice.accuracy >= 0.8"), " → main; otherwise → practice (with max_visits 3)."));
}

/* ================================================================== routine rules ("when → do") */
const RULE_ACTIONS = {
  end_routine: {label: "end the screen", param: null},
  start: {label: "start component", param: "component"},
  stop: {label: "stop component", param: "component"},
  set: {label: "set variable", param: "set"},
  marker: {label: "send marker", param: "text"},
  goto: {label: "go to workflow state", param: "state"},
  log: {label: "write to the log", param: "text"},
};
function renderRulesEditor(el, r) {
  el.append(h("div", {class: "group"}, "Rules (when → do) ", helpLink("EXPERIMENT_FORMAT", "routine-rules-when-do")));
  el.append(h("div", {class: "help"}, "Rules react while the routine runs, e.g. when ", h("code", {}, "$t > 3"), " start a hint; when ", h("code", {}, "$resp.keys == 'q'"), " go to state 'end'."));
  r.rules ||= [];
  const comps_ = (r.components || []).map((c) => c.id);
  const states = new Set(); walkFlow((n) => { if (n?.statemachine) Object.keys(n.states || {}).forEach((x) => states.add(x)); }); states.add("end");
  r.rules.forEach((rule, i) => {
    rule.do = Array.isArray(rule.do) ? rule.do : (rule.do ? [rule.do] : []);
    const box = h("div", {class: "route"});
    box.append(h("div", {class: "route-head"}, h("b", {}, "When"), h("span", {style: "flex:1"}),
      h("label", {class: "help", title: "fire again each time the condition becomes true"},
        (() => { const cb = h("input", {type: "checkbox", onchange: (e) => { if (e.target.checked) rule.repeat = true; else delete rule.repeat; commit(); }}); cb.checked = !!rule.repeat; return cb; })(), " repeat"),
      h("button", {class: "mini danger", onclick: () => { r.rules.splice(i, 1); if (!r.rules.length) delete r.rules; commit(); }}, "×")));
    box.append(h("input", {class: "expr", list: "expr-vars", value: rule.when || "", placeholder: "$resp.keys == 'space'",
      onchange: (e) => { const v = e.target.value.trim(); rule.when = v.startsWith("$") ? v : "$" + v; commit(); }}));
    box.append(h("div", {class: "route-goto"}, h("b", {}, "do")));
    rule.do.forEach((a0, j) => {
      const a = typeof a0 === "string" ? {[a0]: true} : a0;
      const kind = Object.keys(a)[0] || "end_routine";
      const sel = h("select", {onchange: (e) => { const k = e.target.value; rule.do[j] = {[k]: k === "end_routine" ? true : k === "set" ? {x: 1} : (k === "start" || k === "stop") ? comps_[0] || "" : k === "goto" ? [...states][0] : "event"}; commit(); }},
        Object.entries(RULE_ACTIONS).map(([k, d]) => { const o = h("option", {value: k}, d.label); if (k === kind) o.selected = true; return o; }));
      let param = null;
      const pt = RULE_ACTIONS[kind]?.param;
      if (pt === "component") param = h("select", {onchange: (e) => { rule.do[j] = {[kind]: e.target.value}; commit(); }}, comps_.map((c) => { const o = h("option", {value: c}, c); if (a[kind] === c) o.selected = true; return o; }));
      else if (pt === "state") param = h("select", {onchange: (e) => { rule.do[j] = {goto: e.target.value}; commit(); }}, [...states].map((c) => { const o = h("option", {value: c}, c); if (a.goto === c) o.selected = true; return o; }));
      else if (pt === "set") param = h("input", {value: JSON.stringify(a.set), onchange: (e) => { try { rule.do[j] = {set: JSON.parse(e.target.value)}; commit(); } catch { toast('Use JSON, e.g. {"hits": "$hits + 1"}'); } }});
      else if (pt === "text") param = h("input", {value: a[kind] ?? "", onchange: (e) => { rule.do[j] = {[kind]: e.target.value}; commit(); }});
      box.append(h("div", {class: "row2", style: "margin-top:4px"}, sel, param, h("button", {class: "mini danger", onclick: () => { rule.do.splice(j, 1); commit(); }}, "×")));
    });
    box.append(h("button", {class: "mini", style: "margin-top:4px", onclick: () => { rule.do.push({end_routine: true}); commit(); }}, "+ action"));
    el.append(box);
  });
  el.append(h("div", {class: "btns"}, h("button", {onclick: () => { r.rules.push({when: "$t > 1", do: [{end_routine: true}]}); commit(); }}, "+ Rule")));
}

/* ================================================================== plain-language descriptions */
function describeRoutine(rid) {
  const r = S.exp.routines[rid];
  if (!r || !(r.components || []).length) return "This screen is empty.";
  const fmt = (v) => isExpr(v) ? `“${v}”` : `${v} s`;
  const out = [];
  for (const c of r.components) {
    if (c.disabled === true) continue;
    let when = c.start_after ? `after ${c.start_after} ends` : c.start_if ? `when ${c.start_if}` : c.start_frame != null ? `from frame ${c.start_frame}` :
      (numOr(c.start, 0) === 0 && !isExpr(c.start) ? "from the start" : `at ${fmt(c.start)}`);
    const dur = c.duration != null ? `for ${fmt(c.duration)}` : c.duration_frames != null ? `for ${c.duration_frames} frames` : "until the screen ends";
    const what = {
      text: () => `shows text ${isExpr(c.text) ? c.text : "“" + short(c.text || "", 30) + "”"}`,
      image: () => `shows image ${c.image || ""}`, shape: () => `draws a ${c.shape || "rect"}`, fixation: () => "shows a fixation cross",
      sound: () => `plays ${typeof c.sound === "number" ? c.sound + " Hz tone" : (c.sound || "a sound")}`,
      keyboard: () => `waits for ${c.keys ? (Array.isArray(c.keys) ? c.keys.join("/") : c.keys) : "any key"}${c.correct ? ` (correct: ${c.correct})` : ""}`,
      mouse: () => `waits for a click${c.clickable?.length ? " on " + c.clickable.join("/") : ""}`,
      slider: () => "shows a rating scale", html: () => `shows the page ${c.file || "(inline HTML)"}`,
      survey: () => `shows a survey (${(c.questions || []).map((q) => q.instrument || q.id).filter(Boolean).join(", ") || "no questions"})`,
      gaze_roi: () => `watches gaze in an area${c.dwell ? ` (dwell ${c.dwell} s)` : ""}`, gaze_follow: () => `moves ${c.target} with the gaze`,
      calibrate: () => "calibrates the eye tracker", marker: () => `sends marker “${c.label}”`,
      variable: () => `sets ${Object.keys(c.set || {}).join(", ")}${c.when === "end" ? " at the end" : ""}`,
      code: () => "runs Python code", wait: () => "waits",
    }[c.type];
    let s2 = `${c.id} ${what ? what() : c.type}`;
    if (!["code", "variable", "marker"].includes(c.type)) s2 += ` ${when}, ${["keyboard", "mouse", "slider", "html", "survey", "gaze_roi"].includes(c.type) && c.duration == null ? "until answered" : dur}`;
    if (c.end_routine) s2 += "; this ends the screen";
    if (c.if) s2 += ` (only when ${c.if})`;
    if (c.marker) s2 += `; marks “${typeof c.marker === "object" ? c.marker.onset : c.marker}”`;
    out.push(s2 + ".");
  }
  if (r.duration != null) out.push(`The screen lasts at most ${fmt(r.duration)}.`);
  if (r.end_if) out.push(`It ends early when ${r.end_if}.`);
  for (const rule of r.rules || []) out.push(`When ${rule.when}: ${(Array.isArray(rule.do) ? rule.do : [rule.do]).map((a) => typeof a === "string" ? a.replace("_", " ") : Object.entries(a).map(([k, v]) => k === "end_routine" ? "end the routine" : `${k} ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" ")).join(", ")}.`);
  return out.join(" ");
}

/* ================================================================== variable suggestions */
function updateExprVars() {
  let dl = document.getElementById("expr-vars");
  if (!dl) { dl = h("datalist", {id: "expr-vars"}); document.body.append(dl); }
  const vars = new Set(["$t", "$frame", "$participant", "$session"]);
  const rid = S.routine;
  const {loops, machines} = rid ? enclosing(rid) : {loops: [], machines: []};
  for (const lp of loops) {
    Object.keys(firstRow(lp.conditions) || {}).forEach((k) => vars.add("$" + k));
    if (lp.staircase) vars.add("$" + (lp.staircase.variable || "level"));
    ["n", "total", "accuracy", "n_correct", "mean_rt", "repeat"].forEach((k) => vars.add(`$${lp.loop}.${k}`));
  }
  for (const m of machines) ["state", "visit"].forEach((k) => vars.add(`$${m.statemachine}.${k}`));
  walkFlow((n) => { if (n?.loop) ["accuracy", "n_correct", "mean_rt", "total"].forEach((k) => vars.add(`$${n.loop}.${k}`)); });
  Object.keys(S.exp.variables || {}).forEach((k) => vars.add("$" + k));
  const results = {keyboard: ["keys", "rt", "corr"], mouse: ["clicked", "x", "y", "rt", "corr"], slider: ["rating", "rt"],
    gaze_roi: ["entered", "dwell_time", "completed", "first_entry"], html: ["submitted", "rt"]};
  for (const r of Object.values(S.exp.routines)) for (const c of r.components || [])
    for (const k of results[c.type] || []) vars.add(`$${c.id}.${k}`);
  dl.innerHTML = "";
  for (const v of [...vars].sort()) dl.append(h("option", {value: v}));
}

/* ================================================================== welcome & import */
async function welcome(files) {
  files = files || (await api("/api/files")).files;
  const body = $("#modal-body"); body.innerHTML = "";
  body.classList.add("welcome");
  const tpl = Object.entries(S.schema.templates).map(([key, t]) => h("div", {class: "card", onclick: async () => {
    if (S.dirty && !confirm("Discard unsaved changes?")) return;
    closeModal(); loadDoc(clone(await api(`/api/template?name=${key}`)), null); toast("Template loaded: Save to choose where it lives"); }},
    h("b", {}, key.replace(/_/g, " ")), h("small", {}, t.description || t.name)));
  const recent = files.slice(0, 8).map((f) => h("div", {class: "card", onclick: async () => { closeModal(); await openFile(f.path); }},
    h("b", {}, f.name), h("small", {}, f.path)));
  const drop = h("div", {class: "dropzone"}, h("b", {}, "Import from PsychoPy, E-Prime, OpenSesame or jsPsych"),
    h("small", {}, "Drop the files here (for E-Prime: the generated .ebs3 script plus List .txt exports, images…) or click to choose"));
  const input = h("input", {type: "file", multiple: true, style: "display:none", onchange: (e) => importFiles([...e.target.files])});
  drop.onclick = () => input.click();
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("drop"); };
  drop.ondragleave = () => drop.classList.remove("drop");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("drop"); importFiles([...e.dataTransfer.files]); };
  body.append(h("h2", {}, "Welcome to EDGE"),
    h("p", {class: "lead"}, "An experiment is a series of screens (instructions, trials, feedback) shown in order; a trial list repeats screens with different words or pictures."),
    h("div", {class: "card guided", onclick: () => { closeModal(); if (typeof openWizard === "function") openWizard(); }},
      h("b", {}, "✨ Make a new experiment: answer a few questions"),
      h("small", {}, "What participants see, how they respond, timing, practice, blocks. You get a finished, tested experiment to adjust.")),
    h("div", {class: "welcome-learn"}, h("h3", {}, "New to EDGE? Learn by doing"),
      h("div", {class: "learn-row"}, ...(S.tutorials || []).slice(0, 4).map((t) => h("div", {class: "card learn", onclick: () => { closeModal(); startTutorial(t.id); }},
        h("b", {}, (tutorialDone(t.id) ? "✓ " : "") + t.title), h("small", {}, `${t.minutes} min · ${t.level}`))),
        h("div", {class: "card learn more", onclick: () => { closeModal(); openHelp("TUTORIALS"); }}, h("b", {}, "All tutorials & docs →"), h("small", {}, "guides, cookbook, reference")))),
    h("div", {class: "welcome-grid"},
      h("div", {}, h("h3", {}, "Or start from an example"), ...tpl),
      h("div", {}, h("h3", {}, "Open"), ...(recent.length ? recent : [h("div", {class: "help"}, "No experiments in this folder yet.")]),
        h("h3", {style: "margin-top:16px"}, "Import"), drop, input)),
    h("div", {class: "btns"}, h("button", {onclick: () => { closeModal(); }}, "Start with a blank experiment"),
      h("button", {onclick: () => { closeModal(); openHelp(); }}, "Help & documentation")));
  openModal();
}

async function importFiles(files) {
  if (!files.length) return;
  const exts = S.schema.import_extensions;
  const main = files.find((f) => exts.some((x) => f.name.toLowerCase().endsWith(x)) && !f.name.toLowerCase().endsWith(".js")) ||
    files.find((f) => exts.some((x) => f.name.toLowerCase().endsWith(x)));
  if (!main) return toast("None of these files is a PsychoPy/E-Prime/OpenSesame/jsPsych experiment", 4000);
  const stem = main.name.replace(/\.[^.]+$/, "").replace(/[^\w-]+/g, "_");
  const base = `imports/${stem}`;
  toast(`Importing ${main.name}…`, 6000);
  try {
    for (const f of files) {
      const rel = f.webkitRelativePath || f.name;
      await fetch(`/api/upload?path=${encodeURIComponent(base + "/source/" + rel)}`, {method: "POST", body: await f.arrayBuffer()});
    }
    const r = await api("/api/import", {source: `${base}/source/${main.name}`, out: base});
    const body = $("#modal-body"); body.innerHTML = ""; body.classList.remove("welcome");
    const n = (lvl) => r.notes.filter((x) => x.level === lvl);
    body.append(h("h3", {}, `Imported from ${r.platform}`),
      h("p", {}, "Converted: " + Object.entries(r.stats).map(([k, v]) => `${v} ${k}`).join(", ")),
      h("div", {class: "kpis"}, h("div", {class: "kpi"}, h("b", {}, n("unsupported").length), h("span", {}, "need manual work")),
        h("div", {class: "kpi"}, h("b", {}, n("approx").length), h("span", {}, "approximate, please check")),
        h("div", {class: "kpi"}, h("b", {}, n("info").length), h("span", {}, "notes"))),
      ...["unsupported", "approx"].flatMap((lvl) => n(lvl).map((x) => h("div", {class: "issue " + (lvl === "unsupported" ? "error" : "warning")}, `${x.where}: ${x.message.split("\n")[0]}`))),
      h("p", {class: "help"}, `Saved as ${r.path}, with IMPORT_REPORT.md next to it. Run a dry run before collecting data.`),
      h("div", {class: "btns"}, h("button", {class: "primary", onclick: async () => { closeModal(); await openFile(r.path); dryRun(); }}, "Open and dry-run"),
        h("button", {onclick: async () => { closeModal(); await openFile(r.path); }}, "Open")));
    openModal();
  } catch (e) { toast("Import failed: " + e.message, 6000); }
}

function showHelp() {
  const body = $("#modal-body"); body.innerHTML = ""; body.classList.remove("welcome");
  const kb = [["Ctrl/⌘ S", "save"], ["Ctrl/⌘ Z / Shift+Z", "undo / redo"], ["Delete", "remove the selected component"], ["?", "this help"], ["Esc", "close dialogs"]];
  body.append(h("h3", {}, "How EDGE works"),
    h("ul", {class: "help-list"},
      h("li", {}, h("b", {}, "Routine"), ": one screen/event sequence (trial, instructions, feedback). Components sit on its timeline; drag bars to change timing."),
      h("li", {}, h("b", {}, "Component"), ": a stimulus, response, eye-tracking element, marker or logic step. Set ", h("code", {}, "if"), " to include it only sometimes."),
      h("li", {}, h("b", {}, "Flow"), ": the order of routines. Drag items to reorder; use + to insert routines, loops, branches or workflows."),
      h("li", {}, h("b", {}, "Loop"), ": repeats routines once per row of a conditions table; columns become ", h("code", {}, "$variables"), ". Loops also track ", h("code", {}, "$loop.accuracy"), " and ", h("code", {}, "$loop.mean_rt"), " live."),
      h("li", {}, h("b", {}, "Workflow (state machine)"), ": states with routes like “if ", h("code", {}, "$practice.accuracy >= 0.8"), " go to main, otherwise repeat practice”."),
      h("li", {}, h("b", {}, "Rules"), ": inside a routine, “when ", h("code", {}, "$t > 3"), " → start hint”, “when ", h("code", {}, "$resp.keys == 'q'"), " → go to state end”."),
      h("li", {}, h("b", {}, "Expressions"), ": any value starting with $ is computed at run time. Type $ in a field to see the variables available there."),
      h("li", {}, h("b", {}, "HTML pages"), ": the html component shows consent forms, questionnaires or custom JS tasks; every form field is saved."),
      h("li", {}, h("b", {}, "Dry run"), ": tests the whole experiment in seconds with simulated hardware and a virtual participant.")),
    h("h3", {}, "Keyboard"), h("table", {class: "grid"}, kb.map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v)))));
  openModal();
}


/* ================================================================== markdown */
function mdInline(t) {
  t = t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const codes = [];
  t = t.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  t = t.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, src) => `<img alt="${alt}" src="${/^https?:/.test(src) ? src : "/api/help/asset?path=" + encodeURIComponent(src.replace(/^\.\.\//, "").replace(/^docs\//, ""))}">`);
  t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, txt, href) => {
    if (/^https?:/.test(href)) return `<a href="${href}" target="_blank" rel="noopener">${txt}</a>`;
    const [file, anchor] = href.split("#");
    const topic = file ? file.replace(/^(\.\.\/|\.\/|docs\/)+/, "").replace(/\.md$/, "") : "";
    return `<a href="#" data-topic="${topic}" data-anchor="${anchor || ""}">${txt}</a>`;
  });
  t = t.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*\w])\*([^*\n]+)\*(?!\*)/g, "$1<i>$2</i>");
  return t.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i].replace(/&/g, "&amp;").replace(/</g, "&lt;")}</code>`);
}
function slugify(s) { return s.toLowerCase().replace(/[`*_]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
function md(src) {
  const lines = String(src).replace(/\r/g, "").split("\n");
  const out = [];
  let i = 0;
  const para = [];
  const flush = () => { if (para.length) { out.push(`<p>${mdInline(para.join(" "))}</p>`); para.length = 0; } };
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith("```")) {
      flush(); const code = []; i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      out.push(`<pre><code>${code.join("\n").replace(/&/g, "&amp;").replace(/</g, "&lt;")}</code></pre>`); i++; continue;
    }
    const hm = l.match(/^(#{1,4})\s+(.*)/);
    if (hm) { flush(); out.push(`<h${hm[1].length} id="${slugify(hm[2])}">${mdInline(hm[2])}</h${hm[1].length}>`); i++; continue; }
    if (/^\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      flush();
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => mdInline(c.trim().replace(/\\\|/g, "|")));
      const head = cells(l); i += 2;
      const rows = [];
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push(`<table class="grid md-table"><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</table>`);
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) {
      flush();
      const ordered = /^\s*\d+\./.test(l);
      const items = [];
      while (i < lines.length && (/^\s*([-*]|\d+\.)\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        if (/^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        else items[items.length - 1] += " " + lines[i].trim();
        i++;
      }
      out.push(`<${ordered ? "ol" : "ul"}>${items.map((x) => `<li>${mdInline(x)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`);
      continue;
    }
    if (l.startsWith(">")) { flush(); out.push(`<blockquote>${mdInline(l.replace(/^>\s?/, ""))}</blockquote>`); i++; continue; }
    if (/^---+\s*$/.test(l)) { flush(); out.push("<hr>"); i++; continue; }
    if (!l.trim()) { flush(); i++; continue; }
    para.push(l.trim()); i++;
  }
  flush();
  return out.join("\n");
}

/* ================================================================== help center */
function helpLink(topic, anchor) {
  return h("a", {href: "#", class: "help-link", title: "Open the documentation", onclick: (e) => { e.preventDefault(); openHelp(topic, anchor); }}, "📖 docs");
}
const HELP = {topics: null};
async function openHelp(topic, anchor) {
  if (!HELP.topics) { try { HELP.topics = (await api("/api/help/topics")).topics; } catch (e) { return toast("Help unavailable: " + e.message); } }
  const body = $("#modal-body"); body.innerHTML = ""; body.className = "helpcenter";
  const nav = h("div", {class: "help-nav"});
  const content = h("div", {class: "help-content"});
  const search = h("input", {type: "search", placeholder: "Search the docs (e.g. jitter, TTL, accuracy)…", class: "help-search"});
  let timer = null;
  search.oninput = () => { clearTimeout(timer); timer = setTimeout(() => helpSearch(search.value, content), 200); };
  nav.append(search, h("div", {class: "help-group"}, "Tutorials (interactive)"));
  for (const t of S.tutorials || []) nav.append(h("div", {class: "help-item", onclick: () => { closeModal(); startTutorial(t.id); }},
    (tutorialDone(t.id) ? "✓ " : "▶ ") + t.title, h("small", {}, ` ${t.minutes} min`)));
  let group = null;
  for (const t of HELP.topics) {
    if (t.group !== group) { group = t.group; nav.append(h("div", {class: "help-group"}, group)); }
    nav.append(h("div", {class: "help-item" + (t.id === topic ? " sel" : ""), "data-id": t.id, title: t.summary, onclick: () => showTopic(t.id, null, content, nav)}, t.title));
  }
  body.append(h("div", {class: "help-layout"}, nav, content), h("button", {class: "help-close", onclick: closeModal, title: "Close (Esc)"}, "×"));
  openModal();
  await showTopic(topic || "README", anchor, content, nav);
  search.focus();
}
async function showTopic(id, anchor, content, nav) {
  content.innerHTML = "Loading…";
  let r;
  try { r = await api(`/api/help/topic?id=${encodeURIComponent(id)}`); } catch (e) { content.textContent = e.message; return; }
  content.innerHTML = md(r.markdown);
  nav && nav.querySelectorAll(".help-item").forEach((x) => x.classList.toggle("sel", x.dataset.id === id));
  content.querySelectorAll("a[data-topic]").forEach((a) => a.onclick = (e) => { e.preventDefault();
    showTopic(a.dataset.topic || id, a.dataset.anchor || null, content, nav); });
  content.scrollTop = 0;
  if (anchor) {
    const target = content.querySelector(`[id="${CSS.escape(anchor)}"]`) || [...content.querySelectorAll("h2,h3,h4")].find((x) => x.id.includes(slugify(anchor)));
    if (target) { content.scrollTop = target.offsetTop - content.offsetTop - 8; target.classList.add("flash"); }
  }
}
async function helpSearch(q, content) {
  if (!q.trim()) return;
  const {results} = await api(`/api/help/search?q=${encodeURIComponent(q)}`);
  content.innerHTML = "";
  content.append(h("h2", {}, `Results for “${q}”`));
  if (!results.length) content.append(h("p", {}, "Nothing found. Try other words, or browse the guides on the left."));
  for (const r of results) content.append(h("div", {class: "search-hit", onclick: () => {
    if (r.topic === "tutorial") { closeModal(); startTutorial(r.anchor); } else showTopic(r.topic, r.anchor, content, document.querySelector(".help-nav")); }},
    h("b", {}, r.section), h("small", {}, r.topic === "tutorial" ? " · interactive tutorial" : ` · ${r.topic}`), h("div", {}, r.snippet)));
}

/* ================================================================== tutorials */
const T = {tut: null, i: 0, passed: false};
function tutorialDone(id) { try { return (JSON.parse(localStorage.getItem("edge.tutorials.done") || "[]")).includes(id); } catch { return false; } }
function markTutorialDone(id) { try { const d = new Set(JSON.parse(localStorage.getItem("edge.tutorials.done") || "[]")); d.add(id); localStorage.setItem("edge.tutorials.done", JSON.stringify([...d])); } catch {} }

async function startTutorial(id) {
  let r;
  try { r = await api(`/api/help/tutorial?id=${encodeURIComponent(id)}`); } catch (e) { return toast(e.message); }
  if (r.start_doc) {
    if (S.dirty && !confirm("Start the tutorial? Your unsaved changes will be discarded (save first if you want to keep them).")) return;
    clearDraft(); loadDoc(clone(r.start_doc), null, null, {silent: true});
  }
  S.lastDryRun = null; S.savedAt = null; S.tab = null;
  if (r.tutorial.mode && r.tutorial.mode !== S.mode) setMode(r.tutorial.mode);
  if (r.start_doc) { S.view = "story"; renderAll(); }
  T.tut = r.tutorial; T.i = 0; T.passed = false; T.startedAt = Date.now();
  renderCoach();
}
function stopTutorial() { T.tut = null; document.querySelectorAll(".coach-target").forEach((x) => x.classList.remove("coach-target")); $("#coach")?.remove(); }

function renderCoach() {
  $("#coach")?.remove();
  document.querySelectorAll(".coach-target").forEach((x) => x.classList.remove("coach-target"));
  if (!T.tut) return;
  const steps = T.tut.steps, st = steps[T.i];
  if (!st) {           // finished
    markTutorialDone(T.tut.id);
    const next = (S.tutorials || []).find((t) => !tutorialDone(t.id));
    const c = h("div", {id: "coach", class: "done"}, h("div", {class: "coach-head"}, "Tutorial complete 🎉"),
      h("h4", {}, T.tut.title), h("p", {}, "Nicely done. Keep experimenting with this file, or continue learning."),
      h("div", {class: "coach-btns"},
        next ? h("button", {class: "primary", onclick: () => startTutorial(next.id)}, `Next: ${next.title}`) : null,
        h("button", {onclick: () => { stopTutorial(); openHelp("TUTORIALS"); }}, "All tutorials"),
        h("button", {onclick: stopTutorial}, "Close")));
    document.body.append(c); return;
  }
  const ok = st.check ? tutorialCheck(st.check) : true;
  const c = h("div", {id: "coach"});
  c.append(h("div", {class: "coach-head"}, h("span", {}, `${T.tut.title}`), h("span", {class: "coach-step"}, `${T.i + 1} / ${steps.length}`),
    h("button", {class: "mini", title: "Exit the tutorial", onclick: () => { if (confirm("Exit the tutorial?")) stopTutorial(); }}, "×")));
  c.append(h("div", {class: "coach-progress"}, h("div", {style: `width:${(T.i / steps.length) * 100}%`})));
  const bodyEl = h("div", {class: "coach-body"}); bodyEl.innerHTML = `<h4>${mdInline(st.title)}</h4>` + md(st.body);
  bodyEl.querySelectorAll("a[data-topic]").forEach((a) => a.onclick = (e) => { e.preventDefault(); openHelp(a.dataset.topic, a.dataset.anchor); });
  c.append(bodyEl);
  const status = st.check ? h("div", {class: "coach-status" + (ok ? " ok" : "")}, ok ? "✓ Done!" : "Waiting for you to do this…") : null;
  c.append(h("div", {class: "coach-btns"},
    h("button", {disabled: T.i === 0 ? true : null, onclick: () => { T.i--; T.passed = false; renderCoach(); }}, "Back"),
    status,
    h("button", {class: "primary", disabled: (st.check && !ok) ? true : null, onclick: () => { T.i++; T.passed = false; renderCoach(); }}, T.i === steps.length - 1 ? "Finish" : "Next"),
    st.check && !ok ? h("button", {class: "mini skip", title: "Skip this step", onclick: () => { T.i++; renderCoach(); }}, "skip") : null));
  document.body.append(c);
  if (st.target) {
    const targets = document.querySelectorAll(st.target);
    targets.forEach((x) => x.classList.add("coach-target"));
    if (targets[0]) targets[0].scrollIntoView({block: "nearest", inline: "nearest"});
  }
}

function checkTutorial() {
  if (!T.tut) return;
  const st = T.tut.steps[T.i];
  if (!st) return;
  // re-apply highlight after re-renders replaced the DOM
  if (st.target) document.querySelectorAll(st.target).forEach((x) => x.classList.add("coach-target"));
  if (!st.check || T.passed) return;
  if (tutorialCheck(st.check)) {
    T.passed = true; renderCoach();
    setTimeout(() => { if (T.tut && T.passed && T.tut.steps[T.i] === st) { T.i++; T.passed = false; renderCoach(); } }, 1100);
  } else {
    const s2 = document.querySelector(".coach-status"); if (s2) s2.textContent = "Waiting for you to do this…";
  }
}
setInterval(() => checkTutorial(), 800);

function _flowItems() { const out = []; walkFlow((n, p) => out.push({n, p})); return out; }
function _machines() { return _flowItems().map((x) => x.n).filter((n) => n && n.statemachine !== undefined); }
function _cmpProp(obj, spec) {
  if (!spec.prop) return true;
  const v = obj[spec.prop];
  if (spec.exists) return v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && !v.length);
  if ("value" in spec) return String(v).trim() === String(spec.value) || (typeof spec.value === "number" && Number(v) === spec.value) || v === spec.value;
  if ("contains" in spec) return JSON.stringify(v ?? "").includes(spec.contains);
  return v !== undefined;
}
const TUTORIAL_CHECKS = {
  routine_exists: (name) => !!S.exp.routines[name],
  component: (c) => Object.entries(S.exp.routines).some(([rid, r]) => (!c.routine || rid === c.routine) &&
    (r.components || []).some((x) => (!c.type || x.type === c.type) && _cmpProp(x, c))),
  routine_prop: (c) => _cmpProp(S.exp.routines[c.routine] || {}, c),
  loop: (c) => _flowItems().some(({n}) => n && n.loop !== undefined && (!c.id || n.loop === c.id) &&
    (!c.children_include || JSON.stringify(n.children || []).includes(`"${c.children_include}"`)) &&
    (!c.order || n.order === c.order) && (!c.has || n[c.has] != null) &&
    (!c.conditions_kind || (c.conditions_kind === "factorial" ? !!(n.conditions && n.conditions.factorial) :
      c.conditions_kind === "file" ? typeof n.conditions === "string" : Array.isArray(n.conditions))) &&
    (!c.conditions_min || (Array.isArray(n.conditions) && n.conditions.filter((r) => Object.values(r).some((v) => v !== "" && v != null)).length >= c.conditions_min)) &&
    (!c.columns || (Array.isArray(n.conditions) && c.columns.every((col) => n.conditions.some((r) => col in r))))),
  flow_has: (rid) => _flowItems().some(({n}) => routineOfNode(n) === rid),
  statemachine: (c) => _machines().some((m) => {
    const states = m.states || {};
    if (c.state && !states[c.state]) return false;
    if (c.states_min && Object.keys(states).length < c.states_min) return false;
    if (c.state_contains) { const st = states[c.state_contains.state]; if (!st) return false;
      const names = (st.run || []).map((x) => typeof x === "string" ? x : (x.loop || x.routine || x.statemachine));
      if (!names.includes(c.state_contains.item)) return false; }
    if (c.route_contains && !Object.values(states).some((st) => (st.next || []).some((t) => typeof t === "object" && (t.if || "").includes(c.route_contains)))) return false;
    if (c.max_visits && !Object.values(states).some((st) => st.max_visits)) return false;
    return true;
  }),
  device: (type) => (S.exp.devices || []).some((d) => d.type === type),
  rule: (c) => Object.entries(S.exp.routines).some(([rid, r]) => (!c.routine || rid === c.routine) &&
    (r.rules || []).some((rule) => (!c.when_contains || (rule.when || "").includes(c.when_contains)) &&
      (!c.action || (Array.isArray(rule.do) ? rule.do : [rule.do]).some((a) => (typeof a === "string" ? a : Object.keys(a || {})[0]) === c.action)))),
  dry_run: () => !!S.lastDryRun && S.lastDryRun >= (T.startedAt || 0),
  tab_open: (name) => S.tab === name,
  saved: () => !!S.savedAt && S.savedAt >= (T.startedAt || 0),
  selected: (kind) => S.sel?.kind === kind,
  variable: (name) => name in (S.exp.variables || {}),
  setting: (c) => { let v = S.exp.settings; for (const k of c.path.split(".")) v = v?.[k];
    return "contains" in c ? JSON.stringify(v ?? "").includes(c.contains) : "value" in c ? v === c.value : v != null; },
};
function tutorialCheck(chk) {
  try { return Object.entries(chk).every(([k, v]) => TUTORIAL_CHECKS[k] ? TUTORIAL_CHECKS[k](v) : false); }
  catch { return false; }
}
