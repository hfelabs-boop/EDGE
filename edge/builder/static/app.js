/* app.js: the builder shell (SPEC §7.6 "app.js stays"). Owner: P1.
 * Owns the state S, the document helpers (normalize, walkFlow, getNode, ...), undo history with labelled steps
 * (commit, undo, redo), loading and saving, live sync with edits made elsewhere, the alert strips, workspaces and
 * hash routing, renderAll, the app bar and the status bar, the Problems popover (validate, renderIssues), the Home
 * page, the Test page (dryRun, renderResults), the Data page (renderData, exportData), the companion column with
 * the Help tab and the full reader, the anchored tutorial coach (TUTORIAL_CHECKS, TOUR_REVEAL), Preferences, the
 * command palette, the recording pill and run recovery, the keyboard map, the legacy modal host
 * (openModal/closeModal), and the EDGE namespace (§7.5.1) that the other modules talk to.
 * State is the experiment document itself (same structure as the YAML file). Loaded after icons.js and ui.js;
 * functions of later files (build.js, inspector.js, simple.js, widgets.js, stage.js, measures.js, assistant.js)
 * are only called at run time, and always through a typeof check when the owning package may not have them yet.
 */
"use strict";

const S = {
  schema: null, exp: null, path: null, dirty: false,
  routine: null,                 // routine id shown in the screen view
  sel: null,                     // {kind: component|routine|loop|branch|device|machine|state, ...}; null = overview
  history: [], future: [],       // snapshots (strings); one entry = one undo step
  historyLabels: [], futureLabels: [],
  previewT: 0, issues: [], sampleRow: {},
  mode: (() => { try { return localStorage.getItem("edge.mode") || "simple"; } catch { return "simple"; } })(),
  view: "story",                 // story | screen | list | diagram | source (Build only)
  ws: "build",                   // home | build | measures | test | run | data
  tab: null,                     // compatibility for the tutorial check tab_open (§2.5)
  proposal: null,                // the assistant's preview (EDGE.proposal)
  fresh: null,                   // path of an experiment EDGE.newExperiment made in this page session, until the user saves
  tested: null,                  // {snapshot, at, ok} of the last test run
  strict: false,                 // true after Try it, a test run or Start session: "still to do" items count as problems
  run: null,                     // {id, path, participant, session, startedAt, running} while a session records (P4b, P1)
  noDoc: false,                  // Home without an open experiment (a placeholder document is loaded)
  files: null,                   // experiments in the builder folder (GET /api/files?status=1)
  root: "",
};

/* Theme and density apply before the first paint (Preferences, §W14). */
(function applyEarlyPrefs() {
  try {
    const t = localStorage.getItem("edge.theme");
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
    if (localStorage.getItem("edge.density") === "compact") document.documentElement.dataset.density = "compact";
  } catch { /* private mode */ }
})();

/* Human names for item types, the groups they appear in, and the types Simple mode lists only when searched. */
const FRIENDLY = {
  text: ["Text", "Show"], image: ["Picture", "Show"], shape: ["Shape", "Show"], fixation: ["Fixation cross", "Show"],
  sound: ["Sound", "Show"], html: ["Web page / form", "Show"], survey: ["Survey / questionnaire", "Show"],
  keyboard: ["Key press", "Responses"], device_response: ["Button box / external input", "Responses"], mouse: ["Mouse click", "Responses"], slider: ["Rating scale", "Responses"],
  gaze_roi: ["Where they look", "Eye tracking"], gaze_follow: ["Follow the gaze", "Eye tracking"], calibrate: ["Calibrate eye tracker", "Eye tracking"],
  marker: ["Event marker", "Hardware"], variable: ["Set a variable", "Logic"], code: ["Python code", "Logic"], wait: ["Pause / blank", "Logic"],
};
const GROUP_ORDER = ["Show", "Responses", "Eye tracking", "Hardware", "Logic", "Other"];
const SIMPLE_HIDDEN = new Set(["code", "marker", "gaze_follow", "calibrate"]);

const friendlyName = (type) => (FRIENDLY[type] || [type])[0];
const isSimple = () => S.mode === "simple";
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
const MOD = IS_MAC ? "⌘" : "Ctrl";

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
  for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false)
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
};
/* Element.append() would print "null" for skipped optional parts. */
function put(el, ...kids) { el.append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false)); }
const clone = (o) => JSON.parse(JSON.stringify(o));
const isExpr = (v) => typeof v === "string" && v.startsWith("$") && !v.startsWith("$$");
/* toast(msg, ms) keeps its old signature; it is ui.toast underneath (also accepts ui.toast's options object). */
const toast = (msg, ms) => ui.toast(msg, typeof ms === "number" ? {ms} : (ms || {}));
const countWord = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
const docName = () => (S.path ? S.path.split("/").pop().replace(/\.(ya?ml|json)$/i, "") : (S.exp?.name || "untitled"));

async function api(path, body) {
  const opt = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  const r = await fetch(path, opt);
  let j;
  try { j = await r.json(); } catch { j = {error: r.statusText || "The builder did not answer"}; }
  if (!r.ok || j.error) { const e = new Error(j.error || r.statusText); e.status = r.status; e.data = j; throw e; }
  return j;
}

function uniqueId(base, taken) {
  base = base.replace(/[^A-Za-z0-9_]/g, "_").replace(/^(\d)/, "_$1") || "item";
  if (!taken.has(base)) return base;
  let i = 2; while (taken.has(base + i)) i++;
  return base + i;
}

/* Times in words: "10:42", "12 Oct 10:42", "2 min ago". */
function clock(d) { d = d instanceof Date ? d : new Date(d); return isNaN(d) ? "" : d.toTimeString().slice(0, 5); }
function dayTime(d) {
  d = d instanceof Date ? d : new Date(d);
  if (isNaN(d)) return "";
  const today = new Date().toDateString() === d.toDateString();
  return today ? `today ${clock(d)}` : `${d.getDate()} ${d.toLocaleString("en", {month: "short"})} ${clock(d)}`;
}
function ago(d) {
  d = d instanceof Date ? d : new Date(d);
  if (isNaN(d)) return "";
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 2) return "yesterday";
  if (s < 86400 * 30) return `${Math.round(s / 86400)} days ago`;
  return dayTime(d);
}

/* ------------------------------------------------------------------ history */
/* commit() = one undo step. Old signature commit(render = true) and the new one commit("Add Text"[, render]).
 * The label names the step in the undo tooltip ("Undo: Add Text (Ctrl+Z)"); without one, a label is worked out
 * from the change when the tooltip needs it. */
function commit(labelOrRender = true, render = true) {
  const label = typeof labelOrRender === "string" ? labelOrRender : null;
  if (typeof labelOrRender !== "string") render = labelOrRender !== false;
  if (S.proposal) {          // the assistant's preview is not the document: nothing is recorded until Apply
    S.proposal.edited = true;
    toast("Apply or discard the assistant's changes first");
    if (render) renderAll();
    return;
  }
  S.history.push(S._snapshot);
  S.historyLabels.push(label);
  if (S.history.length > 200) { S.history.shift(); S.historyLabels.shift(); }
  S.future = []; S.futureLabels = [];
  S._snapshot = JSON.stringify(S.exp); S.rev = (S.rev || 0) + 1;
  setDirty(true);
  saveDraft();
  if (render) renderAll();
  scheduleValidate();
  EDGE.emit("doc:changed", {label});
}
const draftKey = () => "edge.draft." + (S.path || "untitled");
function saveDraft() {
  if (S.noDoc) return;
  try { localStorage.setItem(draftKey(), JSON.stringify({doc: S.exp, base: S.fingerprint || "", time: new Date().toISOString()})); } catch {}
}
function clearDraft() { try { localStorage.removeItem(draftKey()); } catch {} }
function undo() {
  if (S.proposal) return EDGE.proposal.discard();
  if (!S.history.length) return;
  const label = stepLabel("undo");
  S.future.push(S._snapshot); S.futureLabels.push(S.historyLabels.pop() ?? null);
  S._snapshot = S.history.pop(); S.rev = (S.rev || 0) + 1;
  S.exp = JSON.parse(S._snapshot); fixSelection(); setDirty(true); renderAll(); scheduleValidate();
  ui.announce(`Undid: ${label}`);
  EDGE.emit("doc:changed", {label: "Undo"});
}
function redo() {
  if (S.proposal || !S.future.length) return;
  const label = stepLabel("redo");
  S.history.push(S._snapshot); S.historyLabels.push(S.futureLabels.pop() ?? null);
  S._snapshot = S.future.pop(); S.rev = (S.rev || 0) + 1;
  S.exp = JSON.parse(S._snapshot); fixSelection(); setDirty(true); renderAll(); scheduleValidate();
  ui.announce(`Redid: ${label}`);
  EDGE.emit("doc:changed", {label: "Redo"});
}
/* The name of the next undo (or redo) step: its label, or a description worked out from the two versions. */
const _labelCache = new Map();
function stepLabel(which = "undo") {
  const undoSide = which === "undo";
  const list = undoSide ? S.history : S.future, labels = undoSide ? S.historyLabels : S.futureLabels;
  if (!list.length) return "";
  const i = list.length - 1;
  if (labels[i]) return labels[i];
  const before = undoSide ? list[i] : S._snapshot, after = undoSide ? S._snapshot : list[i];
  const key = before.length + ":" + after.length + ":" + i + which;
  if (_labelCache.has(key)) return _labelCache.get(key);
  let out = "change";
  try { out = guessLabel(JSON.parse(undoSide ? before : after), JSON.parse(undoSide ? after : before)); } catch { /* keep "change" */ }
  if (_labelCache.size > 50) _labelCache.clear();
  _labelCache.set(key, out);
  return out;
}
function guessLabel(a, b) {
  const ra = a.routines || {}, rb = b.routines || {};
  const added = Object.keys(rb).filter((k) => !(k in ra)), gone = Object.keys(ra).filter((k) => !(k in rb));
  if (added.length === 1 && !gone.length) return `Add screen “${added[0]}”`;
  if (gone.length === 1 && !added.length) return `Delete screen “${gone[0]}”`;
  if (added.length === 1 && gone.length === 1) return `Rename “${gone[0]}”`;
  for (const rid of Object.keys(rb)) {
    if (JSON.stringify(ra[rid]) === JSON.stringify(rb[rid])) continue;
    const ca = (ra[rid]?.components || []), cb = (rb[rid]?.components || []);
    const ida = new Set(ca.map((c) => c.id)), idb = new Set(cb.map((c) => c.id));
    const plus = cb.filter((c) => !ida.has(c.id)), minus = ca.filter((c) => !idb.has(c.id));
    if (plus.length === 1 && !minus.length) return `Add ${friendlyName(plus[0].type)}`;
    if (minus.length === 1 && !plus.length) return `Delete “${minus[0].id}”`;
    if (plus.length === 1 && minus.length === 1) return `Rename “${minus[0].id}”`;
    const changed = cb.find((c) => JSON.stringify(c) !== JSON.stringify(ca.find((x) => x.id === c.id)));
    if (changed && ca.map((c) => c.id).join() === cb.map((c) => c.id).join()) return `Change “${changed.id}”`;
    if (ca.length === cb.length) return `Reorder items in “${rid}”`;
    return `Change screen “${rid}”`;
  }
  if (JSON.stringify(a.flow) !== JSON.stringify(b.flow)) return "Change the order of the experiment";
  if (JSON.stringify(a.devices) !== JSON.stringify(b.devices)) return "Change devices";
  if (JSON.stringify(a.measures) !== JSON.stringify(b.measures)) return "Change measures";
  if (JSON.stringify(a.settings) !== JSON.stringify(b.settings)) return "Change settings";
  if (JSON.stringify(a.variables) !== JSON.stringify(b.variables)) return "Change variables";
  return "change";
}

/* Save state in the app bar: Saved · Unsaved changes · Saving… · Not saved: try again (§2.3). */
function setDirty(d) {
  S.dirty = d;
  if (!d) S.savedTime = new Date();
  setSaveState(S._saveState === "error" && d ? "error" : null);
}
function setSaveState(state = null) {
  S._saveState = state;
  const b = $("#btn-save"); if (!b) return;
  const d = S.dirty, fresh = !d && !S.path;
  const word = state === "saving" ? "Saving…" : state === "error" ? "Not saved: try again" : d ? "Unsaved changes" : fresh ? "Not saved yet" : "Saved";
  $("#dirty").classList.toggle("on", d && state !== "saving");
  b.classList.toggle("dirty", d || state === "error");
  b.classList.toggle("error", state === "error");
  b.classList.toggle("new", fresh);
  b.classList.toggle("saving", state === "saving");
  const blocked = !!S.proposal;
  b.setAttribute("aria-disabled", blocked ? "true" : "false");
  const tip = blocked ? "Apply or discard the assistant's changes first" : d ? `Save your changes (${MOD}+S)` : fresh ? `Save this experiment (${MOD}+S)` : `All changes saved (${MOD}+S saves again)`;
  b.dataset.tip = tip;
  b.setAttribute("aria-label", `${word}. ${tip}`);
  const ic = b.querySelector(":scope > svg.ic");
  if (ic) ic.replaceWith(icon(state === "error" ? "warning" : state === "saving" ? "refresh" : fresh ? "save" : "success"));
  const lbl = $("#save-label"); if (lbl) lbl.textContent = word;
  const sb = $("#sb-saved");
  if (sb) sb.textContent = d ? "Unsaved" : S.path && S.savedTime ? `Saved ${clock(S.savedTime)}` : "";
}
function fixSelection() {
  if (!S.exp.routines[S.routine]) S.routine = Object.keys(S.exp.routines)[0] || null;
  if (S.sel?.kind === "component" && !findComp(S.sel.routine, S.sel.id)) S.sel = null;
  if (S.sel?.kind === "routine" && !S.exp.routines[S.sel.routine]) S.sel = null;
  if (S.sel?.kind === "device" && !S.exp.devices[S.sel.index]) S.sel = null;
  if (S.sel?.path) { try { if (!getNode(S.sel.path)) S.sel = null; } catch { S.sel = null; } }
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
function routineInFlowOrder() { const out = []; walkFlow((n) => { const r = routineOfNode(n); if (typeof r === "string" && !out.includes(r)) out.push(r); }); return out; }
function findFlowPath(pred) { let out = null; walkFlow((n, p) => { if (!out && n && typeof n === "object" && pred(n)) out = p; }); return out; }

/* ------------------------------------------------------------------ boot */
/* Boot rule (§2.5): reopen the last experiment if it still exists, else open the only experiment, else Home.
 * ?tutorial=<id> and ?help=<topic> keep working; a hash route (#/test, #/build/screen/trial …) is honoured. */
async function boot() {
  decorateIcons();
  S.schema = await api("/api/schema");
  try { S.tutorials = (await api("/api/help/tutorials")).tutorials; } catch { S.tutorials = []; }
  await refreshFiles();
  const files = S.files || [];
  const params = new URLSearchParams(location.search);
  const route = parseRoute(location.hash);
  const last = EDGE.prefs.get("last", null);
  const startPref = EDGE.prefs.get("start", "last");
  const wantHome = (route && route.ws === "home") || (startPref === "home" && !route);
  if (!wantHome && last && files.some((f) => f.path === last)) await openFile(last, {quietMigrations: false});
  else if (!wantHome && files.length === 1) await openFile(files[0].path);
  else await loadPlaceholder();
  wire();
  restoreLayout();
  setInterval(pollExternalChanges, 1500);
  setInterval(tick, 1000);
  watchTryIt();
  if (params.get("tutorial")) { closeModal(); await startTutorial(params.get("tutorial")); }
  else if (params.get("help")) { closeModal(); openHelp(params.get("help")); if (S.noDoc) EDGE.go("home"); else routeFromHash(); }
  else if (S.noDoc) EDGE.go("home", {replace: true});
  else routeFromHash(true);
  S.booted = true; syncHash(true);
  recoverRuns();
  EDGE.emit("app:ready", {});
}

/* Home without an open experiment: a blank document stands in so every renderer has something to draw. */
async function loadPlaceholder() {
  let doc;
  try { doc = await api("/api/template?name=blank"); } catch { doc = {name: "experiment", routines: {}, flow: []}; }
  S.ws = "home";
  loadDoc(clone(doc), null, null, {silent: true, placeholder: true});
}

async function refreshFiles() {
  try { const r = await api("/api/files?status=1"); S.files = r.files; S.root = r.root || S.root; }
  catch { try { const r = await api("/api/files"); S.files = r.files; S.root = r.root || S.root; } catch { S.files = S.files || []; } }
  return S.files;
}

function loadDoc(exp, path, fp = null, opts = {}) {
  if (S.proposal) endProposal();   // loading another document discards an assistant preview
  const samePath = path && path === S.path && !S.noDoc;
  S.fingerprint = fp; S.path = path; S.noDoc = !!opts.placeholder;
  clearAlert("draft");
  if (!opts.keepSelection) clearAlert("external");
  let draft = null;
  if (!opts.silent && !opts.placeholder) {
    try { draft = JSON.parse(localStorage.getItem(draftKey()) || "null"); } catch { draft = null; }
    if (draft && !(draft.base === (fp || "") && draft.doc && JSON.stringify(draft.doc) !== JSON.stringify(exp))) { clearDraft(); draft = null; }
  }
  S.exp = normalize(exp); S.history = []; S.future = []; S.historyLabels = []; S.futureLabels = [];
  S._snapshot = JSON.stringify(S.exp); S.rev = (S.rev || 0) + 1;
  if (!samePath) {               // document-scoped state resets when another document loads (§2.9)
    S.tested = null; S.strict = false; S.rowIndex = 0; S.previewT = 0; S.triedAt = null; S.lastResults = null;
    $("#tab-results")?.replaceChildren();
    S.dataSeen = null;
  }
  if (opts.keepSelection && S.exp.routines[S.routine]) fixSelection();
  else {
    S.view = S.mode === "simple" ? "story" : "screen";
    S.routine = routineInFlowOrder()[0] || Object.keys(S.exp.routines)[0] || null;
    S.sel = null;
    const saved = path ? EDGE.prefs.get("view." + path, null) : null;
    if (saved && saved.view && ["story", "screen"].includes(saved.view)) S.view = saved.view;
    if (S.view === "screen" && S.routine) S.sel = {kind: "routine", routine: S.routine};
  }
  renderDocName();
  setDirty(false); renderAll(); validate();
  if (draft) showDraftAlert(draft);
  EDGE.emit("doc:loaded", {path});
}

async function openFile(path, opts = {}) {
  const j = await api(`/api/experiment?path=${encodeURIComponent(path)}`);
  loadDoc(j.experiment, path, j.fingerprint, opts);
  if (j.migrations && j.migrations.length) toast("Upgraded from an older format: " + j.migrations.join("; "), 6000);
  EDGE.prefs.set("last", path);
  rememberRecent(path);
}
function rememberRecent(path) {
  const list = (EDGE.prefs.get("recent", []) || []).filter((p) => p !== path);
  list.unshift(path);
  EDGE.prefs.set("recent", list.slice(0, 12));
}

/* "You have unsaved changes from 18:31 (the browser closed). [Restore them] [Discard]" (§4.4). */
function showDraftAlert(draft) {
  const when = dayTime(draft.time).replace(/^today /, "");
  showAlert("draft", {tone: "info", text: `You have unsaved changes from ${when} (the browser closed).`, actions: [
    {label: "Restore them", kind: "primary", run: () => {
      clearAlert("draft");
      S.history.push(S._snapshot); S.historyLabels.push("Restore unsaved changes"); S.future = []; S.futureLabels = [];
      S.exp = normalize(draft.doc); S._snapshot = JSON.stringify(S.exp); S.rev = (S.rev || 0) + 1; fixSelection();
      setDirty(true); saveDraft(); renderAll(); scheduleValidate();
      toast("Restored your unsaved changes. Save to keep them.");
      EDGE.emit("doc:changed", {label: "Restore unsaved changes"});
    }},
    {label: "Discard", run: () => { clearAlert("draft"); clearDraft(); }},
  ]});
}

/* Name a new experiment: typed freely, saved as <slug>/<slug>.yaml, unique in this folder. → slug or null */
async function askExperimentName({title = "Name this experiment", ok = "Create", suggest = "", help} = {}) {
  let taken = new Set();
  try { taken = new Set((await refreshFiles()).map((f) => f.path)); } catch { /* keep going */ }
  const unique = (v) => { const base = ui.slug(v); if (!base) return ""; let s = base, n = 2; while (taken.has(`${s}/${s}.yaml`)) s = `${base}_${n++}`; return s; };
  const name = await ui.prompt({title, label: "Name", value: suggest || "", placeholder: "e.g. Stroop task",
    help: help || `It gets its own folder${S.root ? ` in ${shortRoot()}` : ""}, with its pictures, sounds and data.`,
    ok, transform: unique, validate: (v) => (v ? null : "Type a name first.")});
  return name || null;
}
function shortRoot() {
  const r = (S.root || "").replace(/^\/home\/[^/]+|^\/Users\/[^/]+|^\/root(?=\/|$)|^[A-Z]:\\Users\\[^\\]+/, "~");
  if (r.length <= 44) return r;
  const parts = r.split(/[\\/]/);
  return "…/" + parts.slice(-2).join("/");
}

async function save(asNew = false, opts = {}) {
  if (S.proposal) { toast("Apply or discard the assistant's changes first"); return false; }
  if (S.noDoc) return false;
  let path = S.path;
  if (!path || asNew) {
    const slug = await askExperimentName({title: asNew ? "Save a copy" : "Name this experiment", ok: asNew ? "Save the copy" : "Save",
      suggest: asNew ? `${docName()} copy` : (["experiment", "my_experiment", "untitled"].includes(S.exp.name) ? "" : S.exp.name)});
    if (!slug) return false;
    path = `${slug}/${slug}.yaml`;
    if (!asNew && (!S.exp.name || ["experiment", "my_experiment", "untitled"].includes(S.exp.name))) S.exp.name = slug;
  }
  const newPath = path !== S.path;
  const fp = newPath ? "" : (S.fingerprint || "");
  const label = encodeURIComponent(opts.label || S.saveLabel || "Saved by you");
  setSaveState("saving");
  let r;
  try {
    r = await api(`/api/experiment?path=${encodeURIComponent(path)}&fingerprint=${fp}&label=${label}`, S.exp);
  } catch (e) {
    if (e.status !== 409) { setSaveState("error"); toast(`Not saved: ${e.message}`, {tone: "danger", ms: 8000}); return false; }
    const choice = await ui.dialog({title: "This experiment was changed elsewhere", icon: "warning", size: "sm",
      body: h("div", {}, h("p", {}, "Someone or something changed it while you worked: another window, your editor, or Claude via MCP."),
        h("p", {class: "t-2"}, "Keeping your version backs up the other one in History.")),
      buttons: [{label: "Cancel", value: null, left: true, kind: "ghost"}, {label: "Load the other version", value: "theirs"}, {label: "Keep my version", value: "mine", kind: "primary"}]});
    if (choice === "theirs") { setSaveState(); await openFile(path, {silent: true, keepSelection: true}); clearAlert("external"); toast("Loaded the other version"); return false; }
    if (choice !== "mine") { setSaveState(); return false; }
    try { r = await api(`/api/experiment?path=${encodeURIComponent(path)}&force=1&label=${label}`, S.exp); }
    catch (e2) { setSaveState("error"); toast(`Not saved: ${e2.message}`, {tone: "danger", ms: 8000}); return false; }
  }
  if (newPath) clearDraft();
  S.path = path; S.fingerprint = r.fingerprint; S.saveLabel = null;
  clearDraft();
  EDGE.prefs.set("last", path); rememberRecent(path);
  renderDocName(); setDirty(false); clearAlert("external");
  toast(opts.toast || (newPath ? `Saved as ${path}` : "Saved. The previous version is in History."), {tone: "success"});
  S.savedAt = Date.now(); if (!opts.keepFresh) S.fresh = null;
  refreshFiles().then(() => { if (S.ws === "home") renderHome(); renderShell(); });
  checkTutorial();
  EDGE.emit("doc:saved", {path});
  return true;
}

/* ---------------- alert strips under the app bar (§W22): changed elsewhere, draft restore, session running */
const ALERTS = new Map();
function showAlert(id, {tone = "info", text, actions = [], icon: ic, ws = null, dismiss = true} = {}) {
  ALERTS.set(id, {tone, text, actions, icon: ic, ws, dismiss});
  renderAlerts();
}
function clearAlert(id) { if (ALERTS.delete(id)) renderAlerts(); }
function hideBanner() { clearAlert("external"); }
function renderAlerts() {
  const b = $("#banner"); if (!b) return;
  const rows = [...ALERTS].filter(([, a]) => !a.ws || a.ws === S.ws);
  b.replaceChildren(...rows.map(([id, a]) => {
    const iconName = a.icon || {info: "info", warning: "warning", danger: "error", success: "success", assistant: "assistant"}[a.tone] || "info";
    const row = h("div", {class: `alert-strip ${a.tone}`, role: a.tone === "danger" || a.tone === "warning" ? "alert" : "status", "data-alert": id});
    row.append(icon(iconName, "m"), h("span", {class: "msg"}, a.text));
    for (const act of a.actions || []) row.append(h("button", {class: "btn sm" + (act.kind ? " " + act.kind : ""), onclick: act.run}, act.label));
    if (a.dismiss) row.append(h("button", {class: "btn ghost icon sm", "aria-label": "Dismiss", "data-tip": "Dismiss", "data-tip-pos": "end", onclick: () => clearAlert(id)}, icon("close")));
    return row;
  }));
  b.hidden = !rows.length;
}

/* ---------------- live sync with edits made elsewhere (MCP, editor, another window) */
let _bannerFor = null;
async function pollExternalChanges() {
  if (!S.path || document.hidden || S.noDoc) return;
  let fp;
  try { fp = (await api(`/api/fingerprint?path=${encodeURIComponent(S.path)}`)).fingerprint; } catch { return; }
  if (!fp || fp === S.fingerprint) return;
  if (S.proposal) {
    EDGE.proposal.discard();
    showAlert("assistant-external", {tone: "warning", text: "The experiment changed elsewhere; ask the assistant again."});
  }
  if (!S.dirty) {
    if (_bannerFor === fp) return;
    try { await openFile(S.path, {silent: true, keepSelection: true}); }
    catch (e) { _bannerFor = fp; return showAlert("external", {tone: "warning", text: `This experiment was changed elsewhere, and the new version can't be read: ${e.message}`, dismiss: true}); }
    validate(); toast("Updated: the experiment was changed elsewhere (another window, your editor or Claude via MCP).", 5000);
  } else if (_bannerFor !== fp) {
    _bannerFor = fp;
    showAlert("external", {tone: "info", text: "This experiment was changed elsewhere (another window, your editor or Claude via MCP).", actions: [
      {label: "Load the new version", kind: "primary", run: async () => {
        try { await openFile(S.path, {silent: true, keepSelection: true}); }
        catch (e) { return toast(`The new version can't be read: ${e.message}`, {tone: "danger", ms: 8000}); }
        clearDraft(); clearAlert("external");
      }},
      {label: "Keep mine", run: () => clearAlert("external")},
    ], dismiss: false});
  }
}

/* ---------------- History (the saved versions) */
const BACKUP_LABEL = {builder: "Saved by you", "saved by you": "Saved by you", "before restore": "Before restore", wizard: "Made by answering questions", mcp: "Changed by Claude via MCP"};
async function versionsDialog() {
  if (!S.path || S.noDoc) return toast("Save the experiment first: History keeps its saved versions.");
  let backups = [];
  try { backups = (await api(`/api/backups?path=${encodeURIComponent(S.path)}`)).backups; } catch (e) { return toast(e.message, {tone: "danger"}); }
  let closeIt = () => {};
  const list = h("ul", {class: "hist-list", "aria-label": "Saved versions"});
  for (const b of backups) {
    const lbl = BACKUP_LABEL[(b.label || "").toLowerCase()] || (b.label ? b.label.charAt(0).toUpperCase() + b.label.slice(1) : "Saved");
    list.append(h("li", {class: "hist-row"},
      h("span", {class: "when"}, h("b", {}, dayTime(b.time)), h("span", {class: "t-caption"}, ago(b.time))),
      h("span", {class: "chip" + (/assistant/i.test(lbl) ? " assistant" : "")}, lbl),
      h("button", {class: "btn sm", onclick: async () => {
        if (S.dirty && !(await ui.confirm({title: "Restore this version?", message: "Your unsaved changes will be lost. The current saved version is kept in History.", ok: "Restore", danger: true}))) return;
        try { await api(`/api/restore?path=${encodeURIComponent(S.path)}&id=${encodeURIComponent(b.id)}`, {}); }
        catch (e) { return toast(e.message, {tone: "danger"}); }
        closeIt(); clearDraft(); await openFile(S.path, {silent: true, keepSelection: true});
        toast(`Restored the version from ${dayTime(b.time)}.`);
      }}, "Restore")));
  }
  const body = h("div", {class: "hist"},
    h("p", {class: "t-2"}, "Every save keeps the previous version. Restoring backs up the current one first, so nothing is lost."),
    backups.length ? list : h("div", {class: "empty"}, h("span", {class: "ic-wrap"}, icon("history")), h("p", {}, "No earlier versions yet. They appear here after you save again.")));
  ui.dialog({title: `History of “${docName()}”`, icon: "history", body, size: "md", buttons: [{label: "Close", value: null}],
    onOpen: (_dlg, close) => { closeIt = close; }});
}

/* ---------------- leaving an experiment with unsaved changes */
async function confirmLeaveDirty() {
  if (!S.dirty || S.noDoc) return true;
  const v = await ui.dialog({title: `Save changes to “${docName()}” first?`, size: "sm",
    body: "If you don't save, the changes since the last save are lost.",
    buttons: [{label: "Cancel", value: null, kind: "ghost", left: true}, {label: "Don't save", value: "discard"}, {label: "Save", value: "save", kind: "primary"}]});
  if (v === "save") return await save();
  if (v === "discard") { clearDraft(); S.dirty = false; return true; }
  return false;
}
async function openExperiment(path, ws = "build") {
  if (path === S.path && !S.noDoc) { EDGE.go(ws); return; }
  if (!(await confirmLeaveDirty())) return;
  try { await openFile(path); } catch (e) { return toast(`Couldn't open ${path}: ${e.message}`, {tone: "danger", ms: 8000}); }
  EDGE.go(ws);
}
async function closeExperiment() {
  if (!(await confirmLeaveDirty())) return;
  clearAlert("draft"); clearAlert("external");
  await loadPlaceholder();
  EDGE.prefs.set("last", null);
  EDGE.go("home");
}

/* ---------------- Open (quick open, §W21) */
async function openDialog() {
  const files = await refreshFiles();
  const search = h("input", {class: "input", type: "search", placeholder: "Search experiments", "aria-label": "Search experiments"});
  const list = h("div", {class: "qo-list", role: "list"});
  let closeIt = () => {};
  const draw = () => {
    const q = search.value.trim().toLowerCase();
    const hits = files.filter((f) => !q || (f.name + " " + f.path).toLowerCase().includes(q));
    list.replaceChildren(...hits.map((f) => h("button", {class: "qo-row", role: "listitem", onclick: () => { closeIt(); openExperiment(f.path); }},
      icon("file"), h("span", {class: "t"}, h("b", {}, f.path.split("/").pop().replace(/\.(ya?ml|json)$/i, "")), h("span", {class: "t-caption"}, f.path)),
      statusChip(f), f.modified ? h("span", {class: "t-caption when"}, ago(f.modified)) : null)));
    if (!hits.length) list.append(h("p", {class: "t-2 qo-none"}, files.length ? `Nothing called “${search.value}”.` : `No experiments in ${shortRoot() || "this folder"} yet.`));
  };
  search.oninput = draw;
  search.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); list.querySelector(".qo-row")?.click(); } if (e.key === "ArrowDown") { e.preventDefault(); list.querySelector(".qo-row")?.focus(); } };
  list.addEventListener("keydown", (e) => {
    const rows = [...list.querySelectorAll(".qo-row")]; const i = rows.indexOf(document.activeElement);
    if (e.key === "ArrowDown" && i >= 0) { e.preventDefault(); rows[Math.min(rows.length - 1, i + 1)].focus(); }
    if (e.key === "ArrowUp" && i >= 0) { e.preventDefault(); (i ? rows[i - 1] : search).focus(); }
  });
  draw();
  ui.dialog({title: "Open an experiment", icon: "folder", size: "md", body: h("div", {class: "qo"}, search, list),
    buttons: [{label: "Import…", value: null, left: true, kind: "ghost"}, {label: "Cancel", value: null}], initialFocus: search,
    onOpen: (dlg, close) => { closeIt = close; dlg.querySelector("footer .btn.left").onclick = () => { close(null); chooseImportFiles(); }; }});
}
function statusChip(f) {
  if (!f || !f.sessions) return null;
  if (f.locked) return h("span", {class: "chip"}, icon("lock"), "Locked");
  if (f.sessions.real) return h("span", {class: "chip success"}, "Has data");
  return h("span", {class: "chip"}, "Draft");
}

/* ---------------- new experiments: examples gallery, blank, wizard */
const TEMPLATE_INFO = {
  blank: ["Blank", "One empty screen.", []],
  freeview_eyetracking: ["Free viewing (eye tracking)", "Pictures shown for 4 s while gaze is recorded. Works without an eye tracker (simulated); choose Tobii or Gazepoint later.", ["eye tracking"]],
  eeg_oddball: ["Auditory oddball (EEG)", "Rare high tones among low tones; press space for the high ones. Sends triggers.", ["EEG"]],
  timing_test: ["Timing test for this computer", "Measures how late screens and sounds really are. Needs a light sensor and a microphone.", ["hardware"]],
  staircase: ["Contrast threshold (staircase)", "Finds the contrast where a person is right about 79 % of the time.", ["adaptive"]],
  online_questionnaire: ["Online questionnaire", "Consent, demographics, three validated scales and attention checks.", ["survey"]],
};
const templateInfo = (key) => TEMPLATE_INFO[key] || [key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()), S.schema.templates[key]?.description || "", []];

/* A thumbnail of an experiment's first screen (P4a's drawThumbnail when it exists, an icon tile until then). */
function thumbTile(doc, {w = 160, h: hh = 90, iconName = "screen"} = {}) {
  const box = h("span", {class: "thumb-tile", "aria-hidden": "true"});
  if (doc && typeof drawThumbnail === "function") {
    const cv = h("canvas", {width: w * 2, height: hh * 2});
    try { drawThumbnail(doc, cv); box.append(cv); box.classList.add("drawn"); return box; } catch { /* fall back to the icon */ }
  }
  box.append(icon(iconName, "l"));
  return box;
}

async function examplesGallery() {
  let closeIt = () => {};
  const grid = h("div", {class: "ex-grid", role: "list"});
  for (const key of Object.keys(S.schema.templates)) {
    const [title, sentence, tags] = templateInfo(key);
    const thumb = thumbTile(null, {iconName: key === "blank" ? "file" : "storyboard"});
    const card = h("button", {class: "ex-card card interactive", role: "listitem", onclick: async () => { closeIt(); await createFromTemplate(key); }},
      thumb, h("span", {class: "meta"}, h("b", {}, title), h("span", {class: "t-small t-2"}, sentence),
        tags.length ? h("span", {class: "tags"}, tags.map((t) => h("span", {class: "chip"}, t))) : null));
    grid.append(card);
    if (key !== "blank" && typeof drawThumbnail === "function") api(`/api/template?name=${encodeURIComponent(key)}`).then((d) => thumb.replaceWith(thumbTile(normalize(d)))).catch(() => {});
  }
  ui.dialog({title: "Start from an example", icon: "storyboard", size: "lg", body: grid, buttons: [{label: "Cancel", value: null}],
    onOpen: (_d, close) => { closeIt = close; }});
}
async function createFromTemplate(key) {
  if (!(await confirmLeaveDirty())) return;
  const [title] = templateInfo(key);
  const suggest = key === "blank" ? "" : (S.schema.templates[key]?.name || title);
  const slug = await askExperimentName({title: key === "blank" ? "New blank experiment" : `New experiment: ${title}`, suggest});
  if (!slug) return;
  try { await EDGE.newExperiment({name: slug, template: key}); }
  catch (e) { toast(`Couldn't create it: ${e.message}`, {tone: "danger", ms: 8000}); }
}
/* Kept names: newFromTemplate() opens the examples gallery; welcome() goes Home; runReal() goes to Run. */
function newFromTemplate() { return examplesGallery(); }
function welcome() { EDGE.go("home"); }
function runReal() { EDGE.go("run"); }
async function startWizard() {
  if (!(await confirmLeaveDirty())) return;
  if (typeof openWizard === "function") openWizard();
}

/* ---------------- Import (PsychoPy, E-Prime, OpenSesame, jsPsych) */
function chooseImportFiles() {
  const inp = h("input", {type: "file", multiple: true, style: "display:none", onchange: (e) => { importFiles([...e.target.files]); inp.remove(); }});
  document.body.append(inp); inp.click();
}
async function importFiles(files) {
  if (!files.length) return;
  const exts = S.schema.import_extensions;
  const main = files.find((f) => exts.some((x) => f.name.toLowerCase().endsWith(x)) && !f.name.toLowerCase().endsWith(".js")) ||
    files.find((f) => exts.some((x) => f.name.toLowerCase().endsWith(x)));
  if (!main) return toast("None of these files is a PsychoPy, E-Prime, OpenSesame or jsPsych experiment.", {tone: "warning", ms: 6000});
  if (!(await confirmLeaveDirty())) return;
  const stem = main.name.replace(/\.[^.]+$/, "").replace(/[^\w-]+/g, "_");
  const base = `imports/${stem}`;
  const busy = toast(`Importing ${main.name}…`, 60000);
  let r;
  try {
    for (const f of files) {
      const rel = f.webkitRelativePath || f.name;
      await fetch(`/api/upload?path=${encodeURIComponent(base + "/source/" + rel)}`, {method: "POST", body: await f.arrayBuffer()});
    }
    r = await api("/api/import", {source: `${base}/source/${main.name}`, out: base});
  } catch (e) { busy.close(); return toast(`Import failed: ${e.message}`, {tone: "danger", ms: 8000}); }
  busy.close();
  const n = (lvl) => r.notes.filter((x) => x.level === lvl);
  const kpi = (v, l) => h("div", {class: "kpi"}, h("b", {}, v), h("span", {}, l));
  const body = h("div", {class: "import-result"},
    h("p", {}, "Converted: " + Object.entries(r.stats).map(([k, v]) => `${v} ${k}`).join(", ") + "."),
    h("div", {class: "kpis"}, kpi(n("unsupported").length, "need work by hand"), kpi(n("approx").length, "approximate: please check"), kpi(n("info").length, "notes")),
    h("ul", {class: "import-notes"}, ...["unsupported", "approx"].flatMap((lvl) => n(lvl).map((x) =>
      h("li", {class: lvl === "unsupported" ? "danger" : "warning"}, icon(lvl === "unsupported" ? "error" : "warning"), h("span", {}, h("b", {}, S.mode === "expert" ? x.where : friendlyWhere(x.where)), " ", x.message.split("\n")[0]))))),
    h("p", {class: "t-2 t-small"}, `Saved as ${r.path}, with IMPORT_REPORT.md next to it. Run a test run before collecting data.`));
  const v = await ui.dialog({title: `Imported from ${r.platform}`, icon: "import", size: "md", body,
    buttons: [{label: "Open", value: "open"}, {label: "Open and test", value: "test", kind: "primary"}]});
  if (!v) { refreshFiles().then(() => { if (S.ws === "home") renderHome(); }); return; }
  try { await openFile(r.path); } catch (e) { return toast(e.message, {tone: "danger"}); }
  EDGE.go(v === "test" ? "test" : "build");
  if (v === "test") dryRun();
}

/* ================================================================== Check and the Problems popover (§W19) */
let _vt = null;
function scheduleValidate() { clearTimeout(_vt); _vt = setTimeout(validate, 400); }
async function validate() {
  if (!S.exp) return;
  try { S.issues = (await api("/api/validate", {experiment: S.exp, path: S.path})).issues; }
  catch (e) { S.issues = [{level: "error", where: "server", message: e.message}]; }
  renderIssues();
  EDGE.emit("validated", {issues: S.issues});
}
const cap = (t) => String(t).charAt(0).toUpperCase() + String(t).slice(1);
const issueRoutine = (i) => (String(i.where || "").match(/^routines\.([^.[]+)/) || [])[1];
/* "Still to do" instead of premature red (§W19): an empty flow, or a screen that has no items yet, until the
 * researcher presses Try it, Test run or Start session. Validation itself does not change. */
function isTodo(i) {
  if (S.strict || (i.level !== "error" && i.level !== "warning")) return false;
  if (/flow is empty/i.test(i.message || "")) return true;
  const rid = issueRoutine(i);
  return !!(rid && S.exp.routines[rid] && !comps(rid).length);
}
function problemGroups(issues = S.issues || []) {
  const g = {error: [], warning: [], todo: [], info: []};
  for (const i of issues) { if (isTodo(i)) g.todo.push(i); else (g[i.level] || g.info).push(i); }
  return g;
}
/* Known validator messages in the researcher's words (§4.4); Expert also shows the original. */
function issueText(i) {
  const msg = String(i.message || ""), rid = issueRoutine(i);
  if (/flow is empty/i.test(msg)) return {text: "Add a screen to the experiment.", rewritten: true,
    action: {label: "Add a screen", run: () => { closeProblems(); EDGE.go("build"); if (typeof newRoutine === "function") newRoutine(); }}};
  if (/nothing ends this routine/i.test(msg) && rid) return {text: `“${rid}” never ends. Add a response that ends it, or give it a length.`, rewritten: true};
  return {text: cap(msg)};
}
function friendlyWhere(w) {
  w = String(w || "");
  const m = w.match(/^routines\.([^.[]+)(?:\.([^.[]+))?(?:\.(\w+))?/);
  const label = (k) => (typeof FIELD_LABELS !== "undefined" && FIELD_LABELS[k]) || k;
  if (m) return `Screen “${m[1]}”` + (m[2] && m[2] !== "rules" ? ` › ${m[2]}` : "") + (m[3] ? ` › ${cap(label(m[3]))}` : "");
  if (w.startsWith("devices")) return `Device “${w.replace(/^devices[.[]?/, "").replace(/[\]].*$/, "").split(".")[0]}”`;
  if (w.startsWith("flow")) return "The order of the experiment";
  if (w.startsWith("settings")) return "Experiment settings";
  if (w.startsWith("measures")) return "Measures";
  if (w === "server") return "";
  return w;
}
function gotoIssue(i) {
  closeProblems();
  const w = String(i.where || "");
  const m = w.match(/^routines\.([^.[]+)(?:\.([^.[]+))?/);
  if (m && S.exp.routines[m[1]]) {
    const cid = m[2] && findComp(m[1], m[2]) ? m[2] : null;
    S.routine = m[1];
    if (S.ws !== "build") EDGE.go("build", {render: false});
    S.view = "screen"; S.sel = cid ? {kind: "component", routine: m[1], id: cid} : {kind: "routine", routine: m[1]};
    renderAll(); syncHash(); EDGE.pulse($("#inspector"));
    return;
  }
  const d = w.match(/^devices(?:\.|\[)([^.\]]+)/);
  if (d) {
    const idx = /^\d+$/.test(d[1]) ? +d[1] : S.exp.devices.findIndex((x) => x.id === d[1]);
    if (idx >= 0 && S.exp.devices[idx]) return EDGE.select({kind: "device", index: idx}, {pulse: true});
  }
  if (w.startsWith("flow")) { EDGE.go("build", {render: false}); return EDGE.setView("story"); }
  if (w.startsWith("settings")) return openExperimentSettings();
  if (w.startsWith("measures")) return EDGE.go("measures");
}
function assistantApi() {
  try { if (window.Assistant) return window.Assistant; if (typeof Assistant !== "undefined") return Assistant; } catch { /* not loaded */ }
  return null;
}
const assistantOn = () => !!assistantApi() && !EDGE.prefs.get("assistant.hidden", false);
const assistantReady = () => { try { return assistantOn() && !!assistantApi().status?.()?.configured; } catch { return false; } };

const LEVELS = {error: ["Must fix", "error", "danger"], warning: ["Worth checking", "warning", "warning"],
  todo: ["Still to do", "checklist", "neutral"], info: ["Notes", "info", "info"]};
/* The grouped list of problems, used by the Problems popover and the Test page's Check card. */
function problemsList({compact = false} = {}) {
  const g = problemGroups();
  const wrap = h("div", {class: "problems" + (compact ? " compact" : "")});
  const order = ["error", "warning", "todo", ...(S.mode === "expert" ? ["info"] : [])];
  let any = false;
  for (const lvl of order) {
    if (!g[lvl].length) continue;
    any = true;
    const [word, ic, tone] = LEVELS[lvl];
    const ul = h("ul", {class: "plist"});
    for (const i of g[lvl]) {
      const t = issueText(i), where = friendlyWhere(i.where);
      const canGo = /^(routines|devices|flow|settings|measures)/.test(String(i.where || ""));
      ul.append(h("li", {class: `prob ${tone}`},
        h("div", {class: "msg"}, t.text),
        i.hint ? h("div", {class: "hint"}, cap(i.hint)) : null,
        t.rewritten && S.mode === "expert" ? h("div", {class: "orig mono"}, i.message) : null,
        h("div", {class: "acts"},
          where ? h("span", {class: "chip loc"}, where) : null, h("span", {class: "grow"}),
          t.action ? h("button", {class: "btn sm", onclick: t.action.run}, t.action.label) : null,
          canGo ? h("button", {class: "btn sm", onclick: () => gotoIssue(i)}, "Go there") : null,
          assistantReady() && lvl !== "todo" ? h("button", {class: "btn sm assistant-outline", onclick: () => { closeProblems(); assistantApi().fixIssue(i); }}, icon("assistant"), "Ask the assistant") : null)));
    }
    wrap.append(h("section", {class: `pgroup ${tone}`}, h("h3", {class: "phead"}, icon(ic), `${word} (${g[lvl].length})`), ul));
  }
  if (!any && compact) wrap.append(h("p", {class: "pnone"}, icon("success", "c-ok"), "No problems found."));
  else if (!any) wrap.append(h("div", {class: "empty pempty"}, h("span", {class: "ic-wrap ok"}, icon("success")), h("p", {}, "No problems found."),
    h("div", {class: "actions"}, h("button", {class: "btn sm", onclick: () => { closeProblems(); tryNow("all"); }}, icon("play"), "Try it yourself"),
      h("button", {class: "btn sm", onclick: () => { closeProblems(); dryRun(); }}, icon("test"), "Start test run"))));
  return wrap;
}
let _problems = null;
function openProblems({reason} = {}) {
  closeProblems();
  const head = h("header", {class: "pop-head"}, h("h2", {class: "t-title-s"}, "Problems"), h("span", {class: "grow"}),
    h("button", {class: "btn ghost icon sm", "aria-label": "Close", onclick: () => closeProblems()}, icon("close")));
  const body = h("div", {class: "pop-body"});
  if (reason) body.append(h("div", {class: "alert danger", role: "alert"}, icon("error"), h("div", {}, h("b", {}, reason), "Fix these first, then try again.")));
  body.append(problemsList());
  const box = h("div", {class: "problems-pop", role: "dialog", "aria-label": "Problems"}, head, body);
  S.tab = "issues";
  const pop = ui.popover($("#btn-validate"), box, {placement: "top-start", onClose: () => { _problems = null; if (S.tab === "issues") S.tab = null; checkTutorial(); }});
  pop.el.classList.add("problems-host");
  _problems = pop;
  checkTutorial();
  return pop;
}
function closeProblems() { if (_problems) { const p = _problems; _problems = null; p.close(); } }
function renderIssues() {
  const g = problemGroups();
  renderProblemsButton(g);
  const el = $("#tab-issues");
  if (el) el.replaceChildren(problemsList({compact: true}));
  const st = $("#test-check-state");
  if (st) {
    st.className = "chip " + (g.error.length ? "danger" : g.warning.length ? "warning" : "success");
    st.replaceChildren(icon(g.error.length ? "error" : g.warning.length ? "warning" : "success"),
      g.error.length ? `${g.error.length} to fix` : g.warning.length ? `${g.warning.length} to check` : "No problems");
  }
  if (_problems) { const body = _problems.el.querySelector(".pop-body"); const alert = body?.querySelector(".alert"); body?.replaceChildren(...(alert ? [alert] : []), problemsList()); }
  renderBadges();
  if (S.ws === "test") renderReadiness();
}
function renderProblemsButton(g = problemGroups()) {
  const b = $("#btn-validate"); if (!b) return;
  const n = g.error.length, w = g.warning.length, t = g.todo.length;
  const empty = S.exp && !S.exp.flow.length && !n;
  const [tone, ic, text] = empty ? ["", "info", "Empty experiment"]
    : n && w ? ["danger", "error", `${n} to fix · ${w} to check`] : n ? ["danger", "error", `${n} to fix`]
    : w ? ["warning", "warning", `${w} to check`] : t ? ["", "checklist", `${t} still to do`] : ["ok", "success", "No problems"];
  b.className = "st" + (tone ? " " + tone : "");
  b.replaceChildren(icon(ic), h("span", {id: "issue-count"}, text));
  b.setAttribute("aria-label", `${text}. Show the problems`);
  if (S._lastProblemText !== undefined && S._lastProblemText !== text) ui.announce(text);
  S._lastProblemText = text;
}

/* ================================================================== Try it, test runs and the Test page (§W10) */
/* Try it from the app bar, Ctrl+Enter, the Test card: refuses with the Problems popover when there is something to fix. */
function tryNow(scope = "all") {
  S.strict = true; renderIssues();
  const n = problemGroups().error.length;
  if (n) { openProblems({reason: `Can't start yet: ${countWord(n, "thing")} to fix.`}); return; }
  if (scope === "screen" && !S.routine) scope = "all";
  if (typeof tryIt === "function") {
    if (scope === "screen") { if (typeof startPlay === "function") return startPlay(S.routine); }
    return tryIt(scope);
  }
}
/* A Try-it session ended (the #play overlay closed): the readiness checklist counts it (shim until P4b reports it). */
function watchTryIt() {
  const el = $("#play"); if (!el) return;
  let wasOpen = !el.classList.contains("hidden");
  new MutationObserver(() => {
    const open = !el.classList.contains("hidden");
    if (wasOpen && !open) { S.triedAt = Date.now(); if (S.ws === "test") renderReadiness(); renderShell(); }
    wasOpen = open;
  }).observe(el, {attributes: true, attributeFilter: ["class"]});
}

function testState() {
  if (S.testing) return "testing";
  if (!S.tested) return "none";
  if (S.tested.rev !== S.rev) {           // edited since: compare the content (undo back to the tested version counts as tested)
    if (S.tested.snapshot !== JSON.stringify(S.exp)) return S.tested.ok ? "changed" : "changed-failed";
    S.tested.rev = S.rev;
  }
  return S.tested.ok ? "passed" : "failed";
}

async function dryRun() {
  S.strict = true; renderIssues();
  if (S.testing) return;
  S.testing = true;
  const btn = $("#btn-dryrun");
  if (btn) { btn.style.minWidth = btn.offsetWidth + "px"; btn.setAttribute("aria-busy", "true"); btn.lastChild.textContent = "Testing…"; btn.prepend(h("span", {class: "spin"})); }
  renderShell(); if (S.ws === "test") renderTestPage();
  const snap = JSON.stringify(S.exp);
  try {
    const r = await api("/api/dryrun", {experiment: S.exp, path: S.path});
    if (!r.ok) {
      S.tested = {snapshot: snap, rev: S.rev, at: Date.now(), ok: false};
      S.lastResults = {failed: r.issues || []};
      renderFailedRun(r.issues || []);
      if (S.ws !== "test") openProblems({reason: `Can't start yet: ${countWord((r.issues || []).length || 1, "thing")} to fix.`});
    } else {
      r._at = Date.now();
      renderResults(r);
      const ok = (r.report?.verdict || []).every((v) => v.startsWith("OK")) && !(r.summary?.errors || []).length;
      S.tested = {snapshot: snap, rev: S.rev, at: Date.now(), ok, trials: r.n_trials ?? r.trials.length};
      if (S.ws !== "test") toast(ok ? `Test run passed: ${countWord(S.tested.trials, "trial")}.` : "The test run finished with something to check.",
        {tone: ok ? "success" : "warning", action: {label: "See results", run: () => EDGE.go("test")}});
      else ui.announce(ok ? "Test run passed." : "The test run finished with something to check.");
    }
  } catch (e) {
    S.lastResults = {error: e.message};
    const el = $("#tab-results");
    if (el) el.replaceChildren(h("div", {class: "alert danger", role: "alert"}, icon("error"), h("div", {}, h("b", {}, "The test run stopped with a problem."), h("pre", {class: "mono errtext"}, e.message))));
    if (S.ws !== "test") toast("The test run stopped with a problem.", {tone: "danger", action: {label: "See why", run: () => EDGE.go("test")}});
  } finally {
    S.testing = false;
    const b = $("#btn-dryrun");
    if (b) { b.removeAttribute("aria-busy"); b.querySelector(".spin")?.remove(); b.lastChild.textContent = "Start test run"; b.style.minWidth = ""; }
    renderShell(); if (S.ws === "test") renderTestPage();
    setTimeout(() => checkTutorial(), 0);
  }
}
function renderFailedRun(issues) {
  const el = $("#tab-results"); if (!el) return;
  el.replaceChildren(h("section", {class: "card pad results"},
    h("div", {class: "alert danger", role: "alert"}, icon("error"), h("div", {}, h("b", {}, `Can't start yet: ${countWord(issues.length || 1, "thing")} to fix.`),
      h("ul", {class: "plain"}, issues.slice(0, 8).map((i) => h("li", {}, issueText(i).text, " ", h("span", {class: "t-caption"}, friendlyWhere(i.where))))),
      h("div", {class: "actions"}, h("button", {class: "btn sm", onclick: () => openProblems()}, "Show the problems"))))));
}

const pct = (x) => `${Math.round(100 * x)} %`;
function renderResults(r) {
  S.lastDryRun = Date.now(); setTimeout(() => checkTutorial(), 0);
  if (S.ws === "test") S.tab = "results";
  S.lastResults = r;
  const el = $("#tab-results"); if (!el) return;
  const t = r.summary.timing || {}, rep = r.report || {verdict: [], streams: {}};
  const kpi = (v, l) => h("div", {class: "kpi"}, h("b", {}, v), h("span", {}, l));
  const mins = t.frames && t.refresh_rate_hz ? (t.frames / t.refresh_rate_hz / 60).toFixed(1) + " min" : "–";
  const corr = r.trials.flatMap((row) => Object.entries(row).filter(([k, v]) => k.endsWith(".corr") && typeof v === "number").map(([, v]) => v));
  const nTrials = r.n_trials ?? r.trials.length;
  const card = h("section", {class: "card pad results", "aria-labelledby": "res-title"});
  card.append(h("header", {class: "res-head"}, h("h2", {class: "t-title-s", id: "res-title"}, "Last test run"),
    h("span", {class: "t-caption"}, `${clock(new Date(r._at || Date.now()))} · virtual participant`), h("span", {class: "grow"}),
    h("button", {class: "btn sm ghost", onclick: () => openRunInData(r)}, "Open in Data", icon("chev-right"))));
  card.append(h("div", {class: "kpis"}, kpi(mins, "session"), kpi(nTrials, r.n_trials != null ? "trials" : "screens shown"),
    corr.length ? kpi(pct(corr.reduce((a, b) => a + b, 0) / corr.length), "correct (virtual participant)") : null,
    S.mode === "expert" ? kpi(Object.keys(r.summary.devices || {}).length, "devices (simulated)") : null,
    S.mode === "expert" ? kpi(Object.keys(r.summary.marker_codebook || {}).length, "marker labels") : null,
    kpi((r.summary.errors || []).length, "errors")));
  for (const v of rep.verdict || []) {
    const ok = v.startsWith("OK");
    card.append(h("div", {class: "alert " + (ok ? "success" : "warning")}, icon(ok ? "success" : "warning"), h("div", {}, cap(v.replace(/^OK:\s*/, "").replace(/synchronization/g, "synchronisation")) + (ok ? "." : ""))));
  }
  const mv = rep.measures?.values || [];
  if (mv.length && typeof fmtMeasure === "function") {
    card.append(h("p", {class: "res-measures"}, h("b", {}, "Measures: "),
      mv.flatMap((v, i) => [i ? " · " : "", `${v.label} ${fmtMeasure(v, v.value)} (${v.summary} of ${v.n})`])));
  } else if (!mv.length) {
    card.append(h("p", {class: "t-2 t-small"}, "Say what this experiment measures to see those results here. ",
      h("a", {href: "#/measures", onclick: (e) => { e.preventDefault(); EDGE.go("measures"); }}, "Measures")));
  }
  const streams = Object.entries(rep.streams || {});
  if (streams.length) {
    const det = h("details", {class: "res-more", open: S.mode === "expert" ? true : null}, h("summary", {}, `Streams & synchronisation (${streams.length})`));
    det.append(h("div", {class: "table-wrap"}, h("table", {class: "grid"}, h("tr", {}, ["stream", "samples", "rate (Hz)", "gaps", "clock model", "triggers", "alignment (ms)"].map((x) => h("th", {}, x))),
      streams.map(([name, s]) => h("tr", {}, h("td", {class: "mono"}, name), h("td", {class: "num"}, s.samples), h("td", {class: "num"}, s.effective_srate ?? "–"), h("td", {class: "num"}, s.gaps ?? "–"),
        h("td", {}, s.clock_model && s.clock_model.method !== "identity" ? `${s.clock_model.method}, drift ${((s.clock_model.slope - 1) * 1e6).toFixed(1)} ppm` : "master"),
        h("td", {class: "num"}, s.triggers ? `${s.triggers.matched}/${s.triggers.expected}` : "–"),
        h("td", {class: "num"}, s.triggers && s.triggers.latency_mean_ms != null ? `${s.triggers.latency_mean_ms} ± ${s.triggers.latency_sd_ms ?? 0} (max ${s.triggers.latency_max_abs_ms})` : "–"))))));
    card.append(det);
  }
  const prev = h("details", {class: "res-more"}, h("summary", {}, `Data preview (${countWord(r.trials.length, "row")})`));
  prev.append(h("p", {class: "t-caption"}, `Saved in ${r.summary.data_dir}`), rowsTable(r.trials.slice(0, 60)));
  card.append(prev);
  el.replaceChildren(card);
}
async function openRunInData(r) {
  D.filter = "tests"; D.sel = null;
  const dir = String(r?.summary?.data_dir || "");
  D.pick = dir ? dir.replace(/\\/g, "/").split("/").slice(-1)[0] : null;
  EDGE.go("data");
}

/* The Test page: readiness, Check, Try it yourself, Test run, results and device tests. */
function renderTestPage() {
  renderIssues();
  renderReadiness();
  const ts = testState(), at = S.tested ? clock(S.tested.at) : "";
  const status = $("#test-status");
  if (status) {
    const [cls, ic, txt] = {none: ["", "info", "Not tested yet"], testing: ["", null, "Testing…"], passed: ["success", "success", `Tested ${at}`],
      failed: ["danger", "error", `The last test run (${at}) found problems`], changed: ["warning", "dot", `Changed since the last test (${at})`],
      "changed-failed": ["warning", "dot", `Changed since the last test (${at})`]}[ts];
    status.className = "chip lg " + cls;
    status.replaceChildren(...(ic ? [icon(ic)] : [h("span", {class: "spin"})]), txt);
  }
  const last = $("#test-run-last");
  if (last) last.replaceChildren(...(S.tested ? [h("span", {class: "t-caption"}, `Last: ${at}`),
    icon(S.tested.ok ? "success" : "warning", S.tested.ok ? "c-ok" : "c-warn")] : [h("span", {class: "t-caption"}, "Not run yet")]));
  const res = $("#tab-results");
  if (res && !res.childElementCount && !S.testing) {
    res.append(h("div", {class: "empty dropzone test-empty"}, h("span", {class: "ic-wrap"}, icon("test")),
      h("p", {}, "Try it yourself to see what participants see. A test run lets a virtual participant do the whole experiment in a few seconds."),
      h("div", {class: "actions"}, h("button", {class: "btn", onclick: () => tryNow("all")}, icon("play"), "Try it"),
        h("button", {class: "btn", onclick: () => dryRun()}, icon("test"), "Start test run"))));
  }
  renderDeviceTests();
}
function renderReadiness() {
  const el = $("#test-ready"); if (!el || !S.exp) return;
  const g = problemGroups(), ts = testState(), at = S.tested ? clock(S.tested.at) : "";
  const nMeasures = Array.isArray(S.exp.measures) ? S.exp.measures.length : Object.keys(S.exp.measures || {}).length;
  const f = (S.files || []).find((x) => x.path === S.path);
  const devs = S.exp.devices || [];
  const row = (state, text, act) => h("li", {class: "ready-row " + state},
    icon(state === "ok" ? "success" : state === "bad" ? "error" : state === "warn" ? "warning" : "dot", "st-ic"), h("span", {class: "txt"}, text),
    act ? h("button", {class: "btn sm ghost", onclick: act[1]}, act[0]) : null);
  const items = [
    g.error.length ? row("bad", `${countWord(g.error.length, "problem")} to fix`, ["Show", () => openProblems()])
      : g.todo.length ? row("todo", `${g.todo.length} still to do`, ["Show", () => openProblems()])
      : row("ok", g.warning.length ? `No problems to fix (${g.warning.length} to check)` : "No problems", g.warning.length ? ["Show", () => openProblems()] : null),
    ts === "passed" ? row("ok", `Test run passed (${at})`, null)
      : ts === "none" ? row("todo", "Test run: not run yet", ["Run it", () => dryRun()])
      : ts === "testing" ? row("todo", "Test run: running…", null)
      : ts === "failed" ? row("bad", `The test run (${at}) found problems`, ["Run it", () => dryRun()])
      : row("warn", `Test run: changed since ${at}`, ["Run it", () => dryRun()]),
    S.triedAt ? row("ok", "You tried it yourself", ["Try again", () => tryNow("all")]) : row("todo", "You tried it yourself", ["Try it", () => tryNow("all")]),
    nMeasures ? row("ok", `Measures declared (${nMeasures})`, ["Review", () => EDGE.go("measures")]) : row("todo", "Say what you measure", ["Add", () => EDGE.go("measures")]),
    devs.length ? row("todo", `Devices to test: ${devs.map((d) => d.id).join(", ")}`, ["Test", () => $("#test-devices")?.scrollIntoView({behavior: "smooth", block: "start"})]) : null,
    row("todo", "This computer's timing", ["Check", () => computerDialog()]),
    f?.locked ? row("ok", "Locked after piloting", null) : row("todo", "Locked after piloting", ["Lock…", () => lockExperiment()]),
  ];
  el.replaceChildren(h("h2", {class: "t-title-s"}, "Ready for participants?"), h("ul", {class: "ready-list"}, items),
    h("p", {class: "t-small t-2 trouble"}, "Having trouble? ", h("button", {class: "linkbtn", onclick: () => supportBundle()}, "Make a support bundle")));
}
function renderDeviceTests() {
  const el = $("#test-devices"); if (!el) return;
  const devs = S.exp?.devices || [];
  if (!devs.length) { el.replaceChildren(); el.hidden = true; return; }
  el.hidden = false;
  const key = devs.map((d) => d.id + d.type).join() + (typeof deviceTestBox === "function");
  if (el.dataset.key === key && el.childElementCount) return;   // keep results that are on screen
  el.dataset.key = key;
  const card = h("section", {class: "card pad", "aria-labelledby": "dev-tests-title"}, h("h2", {class: "t-title-s", id: "dev-tests-title"}, "Device tests"),
    h("p", {class: "t-small t-2"}, "Connect each device and test it here, or use the simulator to check the experiment without the hardware."));
  devs.forEach((d, i) => {
    const kind = S.schema.devices[d.type]?.label || short(S.schema.devices[d.type]?.description?.split(/[.(]/)[0] || d.type, 48);
    card.append(h("div", {class: "dev-test-row"}, h("span", {class: "dt-name"}, h("b", {}, d.id), h("span", {class: "t-caption"}, kind)),
      typeof deviceTestBox === "function" ? deviceTestBox(i)
        : h("button", {class: "btn sm", onclick: () => EDGE.select({kind: "device", index: i}, {pulse: true})}, "Open the device to test it")));
  });
  el.replaceChildren(card);
}
async function computerDialog() {
  const body = typeof computerCheckBox === "function" ? await computerCheckBox() : h("p", {}, "Not available.");
  ui.dialog({title: "Check this computer", icon: "screen", size: "md", body});
}
async function lockExperiment() {
  if (!S.path || S.dirty) { if (!(await save())) return; }
  const ok = await ui.confirm({title: "Lock this version?", ok: "Lock this version",
    message: "Locking records the software versions, the file fingerprints and a golden participant, so you can check later that nothing changed. Do it after piloting, before collecting data."});
  if (!ok) return;
  try { const l = await api("/api/lock", {path: S.path}); toast(`Locked: ${countWord(l.files || 0, "file")}, golden participant ${l.trials ?? "–"} trials.`, {tone: "success"}); }
  catch (e) { return toast(`Couldn't lock it: ${e.message}`, {tone: "danger", ms: 8000}); }
  await refreshFiles(); if (S.ws === "test") renderReadiness();
}
function supportBundle() {
  if (!S.path || S.noDoc) return toast("Save the experiment first: the support bundle is made from the saved file.");
  location.href = `/api/support_bundle?path=${encodeURIComponent(S.path)}`;
  toast("Making the support bundle (no participant data is included)…");
}

/* ================================================================== Data (§W12) */
const D = {sessions: [], sel: null, sub: "trials", tables: null, dry: false, filter: "participants", q: "", allExp: false, pick: null};
const sessionDir = () => (S.path && S.path.includes("/") ? S.path.split("/").slice(0, -1).join("/") + "/" : "");
function sessionBelongs(s) {
  if (D.allExp || !S.path || S.noDoc) return true;
  const dir = sessionDir();
  if (dir && String(s.path || "").startsWith(dir)) return true;
  return s.experiment === S.exp.name && (!dir || !!s.dry_run);     // the builder's test runs live in <folder>/data/dry_runs
}
function sessionStatus(s) {
  if (s.error) return ["danger", "error", "Can't read"];
  if (s.errors) return ["danger", "error", "Errors"];
  if (s.aborted) return ["warning", "warning", "Stopped early"];
  if (s.dry_run) return ["", "test", "Test run"];
  return ["success", "success", "Complete"];
}
const sessionMinutes = (s) => { const a = Date.parse(s.started), b = Date.parse(s.ended); if (!a || !b || b < a) return ""; const m = (b - a) / 60000; return m < 1 ? "under 1 min" : `${Math.round(m)} min`; };
async function renderData() {
  const side = $("#data-sessions"), main = $("#data-detail");
  if (!side || !main) return;
  D.dry = D.filter !== "participants";
  if (!side.childElementCount) side.append(h("div", {class: "t-caption"}, "Loading sessions…"));
  try { D.sessions = (await api("/api/sessions?dry_runs=1")).sessions; }
  catch (e) { side.replaceChildren(h("div", {class: "alert danger"}, icon("error"), h("div", {}, e.message))); return; }
  const mine = D.sessions.filter(sessionBelongs);
  const real = mine.filter((s) => !s.dry_run);
  EDGE.prefs.set("dataSeen." + (S.path || "-"), real.length);
  renderBadges();
  const shown = mine.filter((s) => (D.filter === "all" || (D.filter === "tests" ? s.dry_run : !s.dry_run))
    && (!D.q || `${s.participant ?? ""} ${s.session ?? ""} ${s.path}`.toLowerCase().includes(D.q.toLowerCase())));
  if (D.pick) { const hit = mine.find((s) => s.path.endsWith(D.pick)); if (hit) D.sel = hit.path; D.pick = null; }
  if (!D.sel || !shown.some((s) => s.path === D.sel)) D.sel = shown[0]?.path || null;
  $("#data-count").textContent = (real.length ? `${countWord(real.length, "session")} with participants` : "No sessions with participants yet") + (mine.length > real.length ? ` · ${mine.length - real.length} under Tests & tries` : "");
  // the sessions list
  const search = h("input", {class: "input", type: "search", placeholder: "Search participant…", "aria-label": "Search sessions by participant", value: D.q});
  search.oninput = () => { D.q = search.value; clearTimeout(renderData._t); renderData._t = setTimeout(renderData, 200); };
  const filter = ui.seg([{value: "participants", label: "Participants"}, {value: "tests", label: "Tests & tries"}, {value: "all", label: "All"}],
    D.filter, (v) => { D.filter = v; D.sel = null; renderData(); }, {ariaLabel: "Which sessions", size: "sm"});
  filter.classList.add("full");
  const list = h("div", {class: "sess-list", role: "list", "aria-label": "Sessions"});
  for (const s of shown) {
    const [tone, ic, word] = sessionStatus(s);
    list.append(h("button", {class: "sess-row" + (D.sel === s.path ? " sel" : ""), role: "listitem", "aria-current": D.sel === s.path ? "true" : null,
      "aria-label": `Participant ${s.participant ?? "unknown"}, session ${s.session ?? 1}, ${dayTime(s.started)}, ${word}${sessionMinutes(s) ? ", " + sessionMinutes(s) : ""}`,
      onclick: () => { D.sel = s.path; D.sub = D.sub || "trials"; renderData(); }},
      h("span", {class: "who"}, h("b", {}, `${s.participant ?? "?"}`), h("span", {class: "t-caption"}, ` · ${s.session ?? 1}`)),
      h("span", {class: "when t-caption"}, dayTime(s.started).replace(/^today /, "")),
      h("span", {class: `st ${tone}`, title: word}, icon(ic), h("span", {class: "w"}, word === "Complete" ? sessionMinutes(s) || word : word))));
  }
  const keepFocus = document.activeElement === $("#data-sessions input[type=search]");
  side.replaceChildren(search, filter, list.childElementCount ? list : h("p", {class: "t-small t-2 sess-none"}, D.q ? `No session matches “${D.q}”.` : D.filter === "participants" ? "No participant sessions yet." : "Nothing here yet."),
    h("div", {class: "sess-foot"},
      h("button", {class: "btn sm", onclick: (e) => exportMenu(e.currentTarget, null)}, icon("export"), "Export all sessions", icon("chev-down")),
      S.path ? h("button", {class: "linkbtn t-small", onclick: () => { D.allExp = !D.allExp; D.sel = null; renderData(); }}, D.allExp ? "Only this experiment" : "Every experiment in this folder") : null));
  if (keepFocus) { const s2 = side.querySelector("input[type=search]"); s2.focus(); s2.setSelectionRange(s2.value.length, s2.value.length); }
  // the detail
  if (!D.sel) {
    main.replaceChildren(h("div", {class: "empty data-empty"}, h("span", {class: "ic-wrap"}, icon("results")),
      h("h3", {}, "No sessions yet"),
      h("p", {}, "Run a participant in Run. Your test runs and your own tries are under Tests & tries."),
      h("div", {class: "actions"}, h("button", {class: "btn primary", onclick: () => EDGE.go("run")}, icon("run"), "Go to Run"),
        D.filter !== "tests" ? h("button", {class: "btn", onclick: () => { D.filter = "tests"; renderData(); }}, "Show tests & tries") : null)));
    return;
  }
  const sess = D.sessions.find((s) => s.path === D.sel) || {};
  main.replaceChildren(h("div", {class: "t-caption pad"}, "Loading tables…"));
  let t;
  try { t = await api(`/api/session_tables?path=${encodeURIComponent(D.sel)}`); }
  catch (e) { main.replaceChildren(h("div", {class: "alert danger"}, icon("error"), h("div", {}, h("b", {}, "This session can't be read."), e.message))); return; }
  if (sess.path !== D.sel) return;
  D.tables = t;
  const [tone, ic, word] = sessionStatus(sess);
  const head = h("header", {class: "data-head"},
    h("div", {class: "who"}, h("h2", {class: "t-title-m"}, `${sess.participant ?? "?"} · session ${sess.session ?? 1}`),
      h("span", {class: "t-caption"}, [dayTime(sess.started), sessionMinutes(sess)].filter(Boolean).join(" · ")),
      h("span", {class: `chip ${tone}`}, icon(ic), word)),
    h("span", {class: "grow"}),
    h("button", {class: "btn sm", "aria-haspopup": "menu", onclick: (e) => exportMenu(e.currentTarget, D.sel)}, icon("export"), "Export", icon("chev-down")));
  const alerts = h("div", {class: "data-alerts"});
  for (const v of t.report?.verdict || []) {
    const ok = v.startsWith("OK");
    alerts.append(h("div", {class: "alert " + (ok ? "success" : "warning")}, icon(ok ? "success" : "warning"), h("div", {}, cap(v.replace(/^OK:\s*/, "").replace(/synchronization/g, "synchronisation")) + (ok ? "." : ""))));
  }
  for (const w of t.report?.warnings || []) alerts.append(h("div", {class: "alert warning"}, icon("warning"), h("div", {}, cap(typeof w === "string" ? w : w.message || JSON.stringify(w)))));
  const subs = [["trials", `Trials`, t.trials?.total], ["summary", "Summary"], ...(t.measures ? [["measures", "Measures"]] : []), ["dictionary", "What each column means"]];
  if (!subs.some(([k]) => k === D.sub)) D.sub = "trials";
  const tabs = h("div", {class: "tabs data-tabs", role: "tablist", "aria-label": "Tables"});
  for (const [k, label, count] of subs) {
    const b = h("button", {role: "tab", "aria-selected": D.sub === k ? "true" : "false", tabindex: D.sub === k ? "0" : "-1", "aria-controls": "data-table",
      "aria-label": count != null ? `${label}, ${countWord(count, "row")}` : null,
      onclick: () => { D.sub = k; renderData(); }}, label, count != null ? h("span", {class: "count", "aria-hidden": "true"}, count) : null);
    tabs.append(b);
  }
  tabs.addEventListener("keydown", (e) => {
    const bs = [...tabs.querySelectorAll("[role=tab]")], i = bs.indexOf(document.activeElement);
    if (i < 0 || !["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    e.preventDefault(); const j = (i + (e.key === "ArrowRight" ? 1 : -1) + bs.length) % bs.length; renderData._focusTab = true; bs[j].click();
  });
  const tb = t[D.sub] || {columns: [], rows: []};
  const dict = Object.fromEntries((t.dictionary?.rows || []).map((r) => [r.column, r.description]));
  const panel = h("div", {class: "table-wrap data-table", id: "data-table", role: "tabpanel"}, dataTable(tb.columns, tb.rows, dict));
  const more = tb.total > tb.rows.length ? h("p", {class: "t-caption"}, `Showing the first ${tb.rows.length} of ${tb.total} rows. Export to see them all.`) : null;
  main.replaceChildren(head, alerts, tabs, panel, more || "", h("p", {class: "t-caption data-path"}, "Folder: ", h("span", {class: "mono"}, D.sel)));
  const focusTab = main.querySelector('[role=tab][aria-selected="true"]');
  if (renderData._focusTab && focusTab) focusTab.focus();
  renderData._focusTab = false;
}
function fmtCell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(+v.toFixed(4));
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function dataTable(columns, rows, dict = {}) {
  if (!rows.length) return h("p", {class: "t-2 pad"}, "No rows.");
  const numeric = new Set(columns.filter((c) => rows.slice(0, 20).every((r) => r[c] == null || typeof r[c] === "number") && rows.some((r) => typeof r[c] === "number")));
  return h("table", {class: "grid"},
    h("thead", {}, h("tr", {}, columns.map((c) => h("th", {class: numeric.has(c) ? "num mono" : "mono", title: dict[c] || null, scope: "col"}, c)))),
    h("tbody", {}, rows.map((r) => h("tr", {}, columns.map((c) => h("td", {class: numeric.has(c) ? "num" : null}, fmtCell(r[c])))))));
}
function exportMenu(anchor, path) {
  const run = (p, f) => () => exportData(p, f);
  const items = path ? [{head: "This session"}, {label: "CSV", run: run(path, ["csv"])}, {label: "Excel", run: run(path, ["xlsx"])},
    {label: "TSV", run: run(path, ["tsv"])}, {label: "JSON", run: run(path, ["json"])}, {label: "BIDS", run: run(path, ["bids"])}, {sep: true}] : [];
  items.push({head: "All sessions"}, {label: "CSV + Excel", run: run(".", ["csv", "xlsx"])}, {label: "BIDS", run: run(".", ["bids"])});
  ui.menu(anchor, items, {placement: "bottom-end"});
}
function commonFolder(files) {
  if (!files.length) return "";
  const parts = files.map((f) => f.replace(/\\/g, "/").split("/").slice(0, -1));
  const out = [];
  for (let i = 0; i < parts[0].length; i++) { const p = parts[0][i]; if (parts.every((x) => x[i] === p)) out.push(p); else break; }
  return out.join("/") + "/";
}
async function exportData(path, formats) {
  const busy = toast("Exporting…", 30000);
  let files;
  try { files = (await api("/api/export", {path, formats, dry_runs: D.filter !== "participants"})).files; }
  catch (e) { busy.close(); return toast(`Export failed: ${e.message}`, {tone: "danger", ms: 8000}); }
  busy.close();
  const folder = commonFolder(files);
  toast(`Exported ${countWord(files.length, "file")}${folder ? ` to ${folder}` : ""}.`, {tone: "success", action: {label: "Show the files", run: () => {
    ui.dialog({title: `Exported ${countWord(files.length, "file")}`, icon: "export", size: "md",
      body: h("ul", {class: "export-list"}, files.slice(0, 80).map((f) => h("li", {}, h("a", {href: `/api/file?download=1&path=${encodeURIComponent(f)}`}, f)))),
      buttons: [{label: "Close", value: null}]});
  }}});
}

/* ------------------------------------------------------------------ small shared renderers */
const showVal = (type, v) => {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (type === "list" && Array.isArray(v) && v.every((x) => typeof x !== "object")) return v.join(", ");
  return typeof v === "object" ? JSON.stringify(v) : String(v);
};
function rowsTable(rows) {
  if (!rows.length) return h("div", {class: "help"}, "(no rows)");
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  return h("div", {class: "table-wrap rows-table"}, dataTable(cols, rows));
}
function numOr(v, d) { return typeof v === "number" ? v : d; }
function short(s, n = 40) { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; }

/* menu(e, items): the old item format ([label, run, title], "-", {head}) on top of ui.menu (keyboard, focus, flips). */
function menu(e, items) {
  return ui.menu(e, items.map((it) => it === "-" ? {sep: true} : it.head ? {head: it.head}
    : Array.isArray(it) ? {label: it[0], run: it[1], title: it[2] || ""} : it));
}

/* showTab(name): compatibility shim for the retired console tabs (§2.5).
 * issues -> Problems popover · results -> Test · source -> Build YAML view · hardware -> Build Devices tab · data -> Data. */
function showTab(name) {
  if (name === "source") EDGE.setView("source");
  else if (name === "hardware") { EDGE.go("build"); showSide("devices"); }
  else if (name === "data") EDGE.go("data");
  else if (name === "results") EDGE.go("test");
  else if (name === "issues") { if (S.ws === "home") EDGE.go("build"); openProblems(); }
  S.tab = name; setTimeout(() => checkTutorial(), 0);
  if (name === "results") $("#test-results")?.scrollIntoView({block: "nearest"});
}
async function renderSource() { try { $("#yaml").value = (await api("/api/to_yaml", S.exp)).yaml; } catch (e) { $("#yaml").value = "# " + e.message; } }

/* ---------------- the legacy modal host (#modal); new dialogs use ui.dialog */
let _modalRelease = null, _modalOpener = null;
function openModal() {
  const m = $("#modal");
  if (m.classList.contains("hidden")) _modalOpener = document.activeElement;
  m.classList.remove("hidden");
  const box = $(".modal-box"); box.scrollTop = 0; box.scrollLeft = 0;
  _modalRelease?.(); _modalRelease = ui.trapFocus(box);
  setTimeout(() => { if (!box.contains(document.activeElement)) (box.querySelector("input, select, textarea, button, a[href]") || box).focus?.(); }, 0);
}
function _resetModal() { $("#modal-body").className = ""; }
function closeModal() {
  const m = $("#modal"); if (m.classList.contains("hidden")) return;
  m.classList.add("hidden"); _resetModal();
  _modalRelease?.(); _modalRelease = null;
  if (_modalOpener && _modalOpener.isConnected) _modalOpener.focus?.();
  _modalOpener = null;
}

/* ================================================================== Home (§W1) */
const HOME = {q: "", sort: null, mounted: null, thumbs: new Map()};
function renderHome() {
  const files = S.files || [];
  const returning = files.length > 0;
  const root = $("#home-root"); if (root) root.textContent = shortRoot();
  const A = assistantOn() ? assistantApi() : null;
  const desc = $("#home-describe");
  const variant = returning ? "compact" : "full";
  let mounted = false;
  if (A && typeof A.mountComposer === "function") {
    if (HOME.mounted !== variant || !desc.childElementCount) {
      try { A.mountComposer(desc, {variant: "home", compact: returning}); HOME.mounted = variant; } catch (e) { console.error("EDGE: the Describe card failed", e); }
    }
    mounted = desc.childElementCount > 0;
  }
  desc.hidden = !mounted;
  desc.classList.toggle("compact", returning);
  $("#home-hero").className = "home-hero " + (returning ? "returning" : "first") + (mounted ? "" : " no-assistant");
  renderHomeStart(returning, mounted);
  renderHomeFirst();
  renderHomeList(files);
  renderHomeLearn(returning);
}
function homeImportTarget(el) {
  el.addEventListener("dragover", (e) => { e.preventDefault(); el.classList.add("drop"); });
  el.addEventListener("dragleave", () => el.classList.remove("drop"));
  el.addEventListener("drop", (e) => { e.preventDefault(); el.classList.remove("drop"); importFiles([...e.dataTransfer.files]); });
  return el;
}
function renderHomeStart(returning, withDescribe) {
  const el = $("#home-start");
  const card = (id, ic, tone, title, text, run, big = false) => h("button", {class: `start-card card interactive${big ? " big" : ""}`, id, onclick: run},
    h("span", {class: `tile ${tone}`}, icon(ic, "l")), h("span", {class: "txt"}, h("b", {}, title), h("span", {class: "t-small t-2"}, text)));
  const wizard = () => startWizard(), example = () => examplesGallery(), blank = () => createFromTemplate("blank"), imp = () => chooseImportFiles();
  if (returning) {
    const chip = (id, ic, label, run) => h("button", {class: "btn", id, onclick: run}, icon(ic), label);
    const imb = chip("home-import", "import", "Import", imp);
    el.replaceChildren(h("div", {class: "start-row"}, withDescribe ? h("span", {class: "t-2"}, "or") : h("span", {class: "t-2"}, "Start a new experiment:"),
      chip("home-wizard", "checklist", "Answer a few questions", wizard), chip("home-example", "storyboard", "Start from an example", example),
      chip("home-blank", "file", "Blank experiment", blank), homeImportTarget(imb)));
    return;
  }
  const imp2 = card("home-import", "import", "neutral", "Import", "PsychoPy, E-Prime, OpenSesame, jsPsych. Drop the files here.", imp);
  const wiz = card("home-wizard", "checklist", "accent", "Answer a few questions", "6 short pages, about 2 minutes. No AI needed.", wizard, !withDescribe);
  if (!withDescribe) wiz.querySelector(".txt").append(
    h("span", {class: "t-2 big-more"}, "What participants see, how they respond, the timing, practice and feedback, blocks, and any questionnaires or devices. You get a finished, tested experiment to adjust."),
    h("span", {class: "btn primary big-cta", "aria-hidden": "true"}, icon("checklist"), "Answer a few questions"));
  el.replaceChildren(
    wiz,
    card("home-example", "storyboard", "neutral", "Start from an example", "Stroop, oddball (EEG), free viewing, survey…", example),
    card("home-blank", "file", "neutral", "Blank experiment", "One empty screen.", blank),
    homeImportTarget(imp2));
}
function renderHomeFirst() {
  const el = $("#home-first"); if (!el) return;
  const first = (S.tutorials || [])[0];
  if (!first || tutorialDone(first.id)) { el.replaceChildren(); el.hidden = true; return; }
  el.hidden = false;
  el.replaceChildren(h("span", {class: "t-2"}, "New to EDGE?"),
    h("button", {class: "btn", onclick: () => startTutorial(first.id)}, icon("play"), `Your first experiment, step by step · ${first.minutes} min`),
    h("button", {class: "linkbtn", onclick: () => openHelp()}, "All tutorials", icon("chev-right")));
}
function sortFiles(files) {
  const sort = HOME.sort || EDGE.prefs.get("home.sort", "opened");
  const recent = EDGE.prefs.get("recent", []) || [];
  const r = (p) => { const i = recent.indexOf(p); return i < 0 ? 1e9 : i; };
  const mod = (f) => Date.parse(f.modified || "") || 0;
  return [...files].sort(sort === "name" ? (a, b) => a.path.localeCompare(b.path)
    : sort === "changed" ? (a, b) => mod(b) - mod(a)
    : (a, b) => r(a.path) - r(b.path) || mod(b) - mod(a));
}
const SORT_LABEL = {opened: "Last opened", changed: "Last changed", name: "Name"};
function renderHomeList(files) {
  const el = $("#home-list");
  const head = h("div", {class: "sec-head"}, h("h2", {class: "t-title-s"}, files.length ? `Your experiments (${files.length})` : "Your experiments"));
  if (!files.length) {
    el.replaceChildren(head, h("div", {class: "empty dropzone home-none"}, h("p", {}, `Nothing here yet. Experiments you make are saved in ${shortRoot() || "this folder"} and appear here.`)));
    return;
  }
  const search = h("span", {class: "input-wrap"}, icon("search", "lead"), h("input", {class: "input", type: "search", placeholder: "Search…", "aria-label": "Search your experiments", value: HOME.q,
    oninput: (e) => { HOME.q = e.target.value; drawRows(); }}));
  const sortBtn = h("button", {class: "btn sm ghost", "aria-haspopup": "menu", onclick: (e) => ui.menu(e.currentTarget, Object.entries(SORT_LABEL).map(([k, label]) => ({label, checked: (HOME.sort || EDGE.prefs.get("home.sort", "opened")) === k,
    run: () => { HOME.sort = k; EDGE.prefs.set("home.sort", k); renderHomeList(S.files || []); }})))}, SORT_LABEL[HOME.sort || EDGE.prefs.get("home.sort", "opened")] || "Last opened", icon("chev-down"));
  head.append(h("span", {class: "grow"}), search, sortBtn);
  const hasStatus = files.some((f) => f.sessions);
  const table = h("div", {class: "xlist" + (hasStatus ? "" : " no-status"), role: "list", "aria-label": "Your experiments"});
  const drawRows = () => {
    const q = HOME.q.trim().toLowerCase();
    const shown = sortFiles(files).filter((f) => !q || `${f.name} ${f.path}`.toLowerCase().includes(q));
    table.replaceChildren(...shown.map((f) => homeRow(f, hasStatus)));
    if (!shown.length) table.append(h("p", {class: "t-2 xnone"}, `Nothing called “${HOME.q}”. Try another word.`));
    loadThumbs(shown.slice(0, 8));
  };
  drawRows();
  el.replaceChildren(head, table);
}
function homeRow(f, hasStatus) {
  const nm = f.path.split("/").pop().replace(/\.(ya?ml|json)$/i, "");
  const isOpen = f.path === S.path && !S.noDoc;
  const cached = HOME.thumbs.get(f.path + "|" + f.modified);
  const thumb = h("span", {class: "xthumb", "data-path": f.path}, cached ? copyCanvas(cached) : icon("screen"));
  const real = f.sessions?.real || 0;
  return h("div", {class: "xrow" + (isOpen ? " open" : ""), role: "listitem"},
    thumb,
    h("button", {class: "xname", onclick: () => openExperiment(f.path, "build"), "aria-label": `Open ${nm}`},
      h("b", {}, nm, isOpen ? h("span", {class: "chip accent"}, "Open now") : null), h("span", {class: "t-caption"}, f.path)),
    hasStatus ? h("span", {class: "xstatus"}, statusChip(f)) : null,
    hasStatus ? h("span", {class: "xsess t-small"}, real ? countWord(real, "session") : "–", f.last_session ? h("span", {class: "t-caption"}, `last ${ago(f.last_session)}`) : null) : null,
    hasStatus ? h("span", {class: "xwhen t-small t-2"}, f.modified ? ago(f.modified) : "") : null,
    h("span", {class: "xacts"},
      h("button", {class: "btn sm", onclick: () => openExperiment(f.path, "build")}, "Open"),
      h("button", {class: "btn sm ghost", onclick: () => openExperiment(f.path, "run")}, "Run"),
      real ? h("button", {class: "btn sm ghost", onclick: () => openExperiment(f.path, "data")}, "Data") : h("span", {class: "xgap"}),
      h("button", {class: "btn sm ghost icon", "aria-label": `More for ${nm}`, "aria-haspopup": "menu", onclick: (e) => ui.menu(e.currentTarget, [
        {label: "Open", icon: "design", run: () => openExperiment(f.path, "build")},
        {label: "Run a participant", icon: "run", run: () => openExperiment(f.path, "run")},
        {label: "See the data", icon: "results", run: () => openExperiment(f.path, "data")},
        {label: "History…", icon: "history", run: async () => { await openExperiment(f.path, "build"); if (S.path === f.path) versionsDialog(); }},
        {label: "Share as one file (.edgez)", icon: "package", run: () => { location.href = `/api/bundle?path=${encodeURIComponent(f.path)}`; }},
      ], {placement: "bottom-end"})}, icon("more"))));
}
async function loadTemplateThumbs(keys) {
  if (typeof drawThumbnail !== "function") return;
  HOME.tpl ||= {};
  for (const k of keys) {
    if (k in HOME.tpl) continue;
    HOME.tpl[k] = null;
    try {
      const d = await api(`/api/template?name=${encodeURIComponent(k)}`);
      const cv = h("canvas", {width: 320, height: 180}); drawThumbnail(normalize(d), cv); HOME.tpl[k] = cv;
      const slot = document.querySelector(`.ex-thumb[data-tpl="${CSS.escape(k)}"]`); if (slot) slot.replaceChildren(copyCanvas(cv));
    } catch { /* keep the icon */ }
  }
}
function copyCanvas(cv) { const c = h("canvas", {width: cv.width, height: cv.height}); try { c.getContext("2d").drawImage(cv, 0, 0); } catch { /* blank */ } return c; }
async function loadThumbs(files) {
  if (typeof drawThumbnail !== "function") return;
  for (const f of files) {
    const key = f.path + "|" + f.modified;
    if (HOME.thumbs.has(key)) continue;
    HOME.thumbs.set(key, null);
    try {
      const j = await api(`/api/experiment?path=${encodeURIComponent(f.path)}`);
      const cv = h("canvas", {width: 320, height: 180});
      drawThumbnail(normalize(j.experiment), cv);
      HOME.thumbs.set(key, cv);
      const slot = document.querySelector(`.xthumb[data-path="${CSS.escape(f.path)}"]`);
      if (slot) slot.replaceChildren(copyCanvas(cv));
    } catch { /* keep the icon tile */ }
  }
}
function renderHomeLearn(returning) {
  const el = $("#home-learn");
  const parts = [];
  if (returning) {
    const ex = Object.keys(S.schema.templates).filter((k) => k !== "blank");
    parts.push(h("div", {class: "sec-head"}, h("h2", {class: "t-title-s"}, "Examples"), h("span", {class: "t-caption"}, "Complete, tested experiments to adapt")),
      h("div", {class: "ex-row"}, ex.map((k) => { const [title, sentence] = templateInfo(k);
        const tile = h("span", {class: "ex-thumb", "data-tpl": k}, HOME.tpl?.[k] ? copyCanvas(HOME.tpl[k]) : icon("storyboard"));
        return h("button", {class: "ex-mini card interactive", title: sentence, onclick: () => createFromTemplate(k)}, tile, h("span", {}, title)); })));
    loadTemplateThumbs(ex);
  }
  const tuts = S.tutorials || [];
  if (tuts.length) {
    const pick = [...tuts.filter((t) => !tutorialDone(t.id)).slice(0, 3)];
    if (pick.length < 3) pick.push(...tuts.filter((t) => tutorialDone(t.id)).slice(0, 3 - pick.length));
    parts.push(h("div", {class: "sec-head"}, h("h2", {class: "t-title-s"}, "Learn by doing"), h("span", {class: "t-caption"}, "Short tutorials that guide you step by step, in the builder")),
      h("div", {class: "learn-row"}, pick.map((t) => h("button", {class: "learn-card card interactive", onclick: () => startTutorial(t.id)},
        h("span", {class: "lc-top"}, icon(tutorialDone(t.id) ? "success" : "play", tutorialDone(t.id) ? "c-ok" : ""), h("span", {class: "t-caption"}, `${t.minutes} min · ${t.level}`)),
        h("b", {}, t.title), h("span", {class: "t-small t-2"}, t.learn || ""))),
        h("button", {class: "learn-card card interactive more", onclick: () => openHelp()}, icon("learn", "l"), h("b", {}, "All tutorials and guides"), h("span", {class: "t-small t-2"}, "Builder guide, cookbook, FAQ"))));
  }
  el.replaceChildren(...parts);
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
      out.push(`<div class="table-wrap"><table class="grid md-table"><tr>${head.map((c) => `<th>${c}</th>`).join("")}</tr>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</table></div>`);
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

/* ================================================================== Help: the companion tab and the full reader (§W15) */
/* helpLink(topic, anchor): the [book] icon button next to a field or a title; opens the anchor in the Help tab. */
function helpLink(topic, anchor, about = "") {
  const tip = about ? `Help for ${about}` : "Help on this";
  return h("button", {type: "button", class: "btn ghost icon sm help-link", "aria-label": tip, "data-tip": tip, "data-tip-pos": "end",
    onclick: (e) => { e.preventDefault(); e.stopPropagation(); openHelp(topic, anchor); }}, icon("book"));
}
const HELP = {topics: null, view: "index", topic: null, anchor: null, q: "", hits: null};
const HELP_GROUPS = [
  ["Start here", ["GETTING_STARTED", "BUILDER_GUIDE", "TUTORIALS", "FAQ", "ASSISTANT"]],
  ["Guides", ["COOKBOOK", "EXPERIMENT_FORMAT", "SURVEYS", "DATA", "DEVICES", "IMPORT", "MCP", "README"]],
  ["Reference", ["reference/components", "reference/devices", "reference/questionnaires", "reference/cli"]],
  ["For lab managers", ["SECURITY", "KNOWN_ISSUES", "PAIN_POINTS", "ARCHITECTURE"]],
];
async function loadHelpTopics() {
  if (!HELP.topics) { try { HELP.topics = (await api("/api/help/topics")).topics; } catch { HELP.topics = []; } }
  return HELP.topics;
}
function helpGroups() {
  const byId = Object.fromEntries((HELP.topics || []).map((t) => [t.id, t]));
  const used = new Set();
  const out = HELP_GROUPS.map(([g, ids]) => [g, ids.filter((id) => byId[id]).map((id) => (used.add(id), byId[id]))]);
  const rest = (HELP.topics || []).filter((t) => !used.has(t.id));
  if (rest.length) out[1][1].push(...rest);
  return out.filter(([, list]) => list.length);
}
/* What the researcher is looking at → help that explains it. */
function helpContext() {
  const out = [], add = (label, topic, anchor) => out.push({label, topic, anchor});
  if (S.ws === "home") { add("Getting started", "GETTING_STARTED"); add("Starting a new experiment", "BUILDER_GUIDE", "starting-a-new-experiment"); }
  else if (S.ws === "build") {
    const sel = S.sel;
    if (sel?.kind === "component") { const c = findComp(sel.routine, sel.id); if (c) add(`${friendlyName(c.type)}: every option`, "reference/components", c.type); }
    if (sel?.kind === "loop") add("Trial lists and randomisation", "COOKBOOK", "trial-lists-and-randomization");
    if (sel?.kind === "machine" || sel?.kind === "state") add("Practice until good enough (workflows)", "COOKBOOK", "practice-until-80-correct-at-most-three-times");
    if (sel?.kind === "branch") add("Showing screens only sometimes", "COOKBOOK", "flow-and-logic");
    if (sel?.kind === "device") { const d = S.exp.devices[sel.index]; add("Devices and synchronisation", "DEVICES"); if (d) add(`${d.type}: options`, "reference/devices", d.type); }
    if (S.view === "screen") { add("Screens and the timeline", "BUILDER_GUIDE", "screens-and-the-timeline"); add("Changing a value from trial to trial", "BUILDER_GUIDE", "properties-and-where-values-come-from"); add("Timing recipes", "COOKBOOK", "timing"); }
    else if (S.view === "source") add("The experiment file, key by key", "EXPERIMENT_FORMAT");
    else { add("The storyboard: screens in order", "BUILDER_GUIDE", "the-storyboard"); if (!out.some((x) => x.anchor === "trial-lists-and-randomization")) add("Trial lists: repeat screens for each row", "COOKBOOK", "trial-lists-and-randomization"); }
  } else if (S.ws === "measures") { add("Measures & data", "BUILDER_GUIDE", "measures-data"); add("How the summary is built", "DATA", "how-the-summary-is-built-summary-csv"); }
  else if (S.ws === "test") { add("Checking, testing and trying", "BUILDER_GUIDE", "checking-testing-and-trying"); add("Known issues on lab computers", "KNOWN_ISSUES"); }
  else if (S.ws === "run") { add("Run with a participant", "BUILDER_GUIDE", "run-with-a-participant"); add("Known issues on lab computers", "KNOWN_ISSUES"); }
  else if (S.ws === "data") { add("Saving, loading and data", "DATA"); add("Measures & data", "BUILDER_GUIDE", "measures-data"); }
  return out.slice(0, 4);
}
function helpPane() {
  const pane = $("#help-panel");
  if (!pane.querySelector(".help-pane")) {
    const input = h("input", {class: "input", type: "search", id: "help-search", placeholder: "Search help: jitter, TTL, accuracy…", "aria-label": "Search help"});
    let timer = null;
    input.oninput = () => { clearTimeout(timer); timer = setTimeout(() => { HELP.q = input.value; if (input.value.trim()) helpSearchPanel(input.value); else { HELP.view = "index"; renderHelpPanel(); } }, 220); };
    input.onkeydown = (e) => { if (e.key === "Escape" && input.value) { e.stopPropagation(); input.value = ""; HELP.view = "index"; renderHelpPanel(); } };
    pane.replaceChildren(h("div", {class: "help-pane"},
      h("div", {class: "help-top"}, h("span", {class: "input-wrap"}, icon("search", "lead"), input),
        h("button", {class: "btn ghost icon sm", "aria-label": "Open the full reader", "data-tip": "Open the full reader", "data-tip-pos": "end", onclick: () => openHelpReader(HELP.view === "topic" ? HELP.topic : null, HELP.anchor)}, icon("expand"))),
      h("div", {class: "help-body", id: "help-body", tabindex: "-1"})));
  }
  return pane.querySelector("#help-body");
}
async function openHelp(topic, anchor) {
  EDGE.companion.open("help");
  helpPane();
  if (topic) await showHelpTopic(topic, anchor);
  else { HELP.view = "index"; await renderHelpPanel(); setTimeout(() => $("#help-search")?.focus(), 0); }
}
async function renderHelpPanel() {
  const body = helpPane();
  if (HELP.view === "topic" && HELP.topic) return showHelpTopic(HELP.topic, null, {keepScroll: true});
  if (HELP.view === "search" && HELP.hits) return drawHelpHits(body);
  await loadHelpTopics();
  const row = (ic, label, run, extra) => h("button", {class: "help-row", onclick: run}, ic ? icon(ic) : null, h("span", {class: "lbl"}, label), extra || null, icon("chev-right", "chev"));
  const parts = [];
  const last = EDGE.prefs.get("tutorial.last", null);
  if (last && !T.tut && last.i < last.n) parts.push(h("div", {class: "alert info help-continue"}, icon("learn"), h("div", {},
    h("b", {}, `Continue: ${last.title}`), `Step ${last.i + 1} of ${last.n}.`,
    h("div", {class: "actions"}, h("button", {class: "btn sm primary", onclick: () => startTutorial(last.id, {resumeAt: last.i})}, "Continue"),
      h("button", {class: "btn sm ghost", onclick: () => { EDGE.prefs.set("tutorial.last", null); renderHelpPanel(); }}, "Forget it")))));
  const ctx = helpContext();
  if (ctx.length) parts.push(h("h3", {class: "t-overline"}, "About what you're looking at"), h("div", {class: "help-rows"}, ctx.map((c) => row("book", c.label, () => showHelpTopic(c.topic, c.anchor)))));
  if ((S.tutorials || []).length) parts.push(h("h3", {class: "t-overline"}, "Learn by doing"), h("div", {class: "help-rows"},
    S.tutorials.map((t) => row(tutorialDone(t.id) ? "success" : "play", t.title, () => startTutorial(t.id), h("span", {class: "t-caption"}, `${t.minutes} min`)))));
  for (const [g, list] of helpGroups()) parts.push(h("h3", {class: "t-overline"}, g), h("div", {class: "help-rows"}, list.map((t) => row(null, t.title, () => showHelpTopic(t.id)))));
  parts.push(h("div", {class: "help-foot"},
    assistantOn() ? h("p", {}, "Can't find it? ", h("button", {class: "btn sm assistant-outline", onclick: () => assistantApi().open({text: HELP.q || ""})}, icon("assistant"), "Ask the assistant")) : null,
    h("button", {class: "linkbtn", onclick: () => keyboardDialog()}, icon("command"), "Keyboard shortcuts")));
  body.replaceChildren(...parts);
}
async function showHelpTopic(id, anchor, {keepScroll = false} = {}) {
  const body = helpPane();
  HELP.view = "topic"; HELP.topic = id; HELP.anchor = anchor || null;
  const scroll = keepScroll ? body.scrollTop : 0;
  const back = h("button", {class: "btn sm ghost help-back", onclick: () => { HELP.view = HELP.hits ? "search" : "index"; renderHelpPanel(); }}, icon("chev-left"), HELP.hits ? "Search results" : "All help");
  const content = h("div", {class: "help-content"}, h("p", {class: "t-caption"}, "Loading…"));
  body.replaceChildren(back, content);
  await showTopic(id, anchor, content, null);
  if (keepScroll) body.scrollTop = scroll;
}
async function showTopic(id, anchor, content, nav) {
  content.replaceChildren(h("p", {class: "t-caption"}, "Loading…"));
  let r;
  try { r = await api(`/api/help/topic?id=${encodeURIComponent(id)}`); } catch (e) { content.textContent = e.message; return; }
  content.innerHTML = md(r.markdown);
  nav && nav.querySelectorAll(".help-item").forEach((x) => { const on = x.dataset.id === id; x.classList.toggle("sel", on); if (on) x.setAttribute("aria-current", "page"); else x.removeAttribute("aria-current"); });
  content.querySelectorAll("a[data-topic]").forEach((a) => a.onclick = (e) => { e.preventDefault();
    if (nav) showTopic(a.dataset.topic || id, a.dataset.anchor || null, content, nav);
    else showHelpTopic(a.dataset.topic || id, a.dataset.anchor || null); });
  const scroller = content.closest(".help-body, .reader-content") || content;
  scroller.scrollTop = 0;
  if (anchor) {
    const target = content.querySelector(`[id="${CSS.escape(anchor)}"]`) || [...content.querySelectorAll("h2,h3,h4")].find((x) => x.id.includes(slugify(anchor)));
    if (target) { scroller.scrollTop = target.offsetTop - scroller.offsetTop - 8; target.classList.add("flash"); }
  }
}
async function helpSearchPanel(q) {
  if (!q.trim()) return;
  let results = [];
  try { results = (await api(`/api/help/search?q=${encodeURIComponent(q)}`)).results; } catch { results = []; }
  HELP.view = "search"; HELP.hits = {q, results};
  drawHelpHits(helpPane());
}
function drawHelpHits(body) {
  const {q, results} = HELP.hits;
  body.replaceChildren(h("h3", {class: "t-overline"}, `Results for “${q}”`));
  if (!results.length) body.append(h("div", {class: "empty"}, h("p", {}, `Nothing called “${q}”. Try another word, or ask the assistant.`),
    assistantOn() ? h("button", {class: "btn sm assistant-outline", onclick: () => assistantApi().open({text: q})}, icon("assistant"), "Ask the assistant") : null));
  for (const r of results) body.append(h("button", {class: "search-hit", onclick: () => { if (r.topic === "tutorial") startTutorial(r.anchor); else showHelpTopic(r.topic, r.anchor); }},
    h("b", {}, r.section), h("span", {class: "t-caption"}, r.topic === "tutorial" ? " · interactive tutorial" : ` · ${r.topic}`), h("span", {class: "snip"}, r.snippet)));
}
/* helpSearch(q, content): search into a content element (the full reader). */
async function helpSearch(q, content) {
  if (!q.trim()) return;
  const {results} = await api(`/api/help/search?q=${encodeURIComponent(q)}`);
  content.replaceChildren(h("h2", {}, `Results for “${q}”`));
  if (!results.length) content.append(h("p", {}, "Nothing found. Try other words, or browse the guides on the left."));
  for (const r of results) content.append(h("button", {class: "search-hit", onclick: () => {
    if (r.topic === "tutorial") { HELP.readerClose?.(); startTutorial(r.anchor); }
    else showTopic(r.topic, r.anchor, content, document.querySelector(".reader-nav")); }},
    h("b", {}, r.section), h("span", {class: "t-caption"}, r.topic === "tutorial" ? " · interactive tutorial" : ` · ${r.topic}`), h("span", {class: "snip"}, r.snippet)));
}
/* The full two-column reader (⤢ in the Help tab, deep links). */
async function openHelpReader(topic, anchor) {
  await loadHelpTopics();
  const nav = h("nav", {class: "reader-nav", "aria-label": "Help topics"});
  const content = h("article", {class: "reader-content help-content", tabindex: "-1"});
  const search = h("input", {type: "search", class: "input", placeholder: "Search the help", "aria-label": "Search the help"});
  let timer = null, closeIt = () => {};
  search.oninput = () => { clearTimeout(timer); timer = setTimeout(() => helpSearch(search.value, content), 220); };
  nav.append(search, h("div", {class: "help-group t-overline"}, "Tutorials"));
  for (const t of S.tutorials || []) nav.append(h("button", {class: "help-item", onclick: () => { closeIt(); startTutorial(t.id); }},
    icon(tutorialDone(t.id) ? "success" : "play"), h("span", {}, t.title), h("span", {class: "t-caption"}, ` ${t.minutes} min`)));
  for (const [g, list] of helpGroups()) {
    nav.append(h("div", {class: "help-group t-overline"}, g));
    for (const t of list) nav.append(h("button", {class: "help-item", "data-id": t.id, title: t.summary || "", onclick: () => showTopic(t.id, null, content, nav)}, h("span", {}, t.title)));
  }
  ui.dialog({title: "Help", icon: "book", size: "full", body: h("div", {class: "reader"}, nav, content), buttons: [],
    onOpen: (dlg, close) => { closeIt = close; HELP.readerClose = close; dlg.classList.add("reader-dialog"); }, initialFocus: search});
  await showTopic(topic || "README", anchor, content, nav);
}

/* ================================================================== tutorials: the anchored coach (§W15, §6.1) */
const T = {tut: null, i: 0, passed: false, min: false};
function tutorialDone(id) { try { return (JSON.parse(localStorage.getItem("edge.tutorials.done") || "[]")).includes(id); } catch { return false; } }
function markTutorialDone(id) { try { const d = new Set(JSON.parse(localStorage.getItem("edge.tutorials.done") || "[]")); d.add(id); localStorage.setItem("edge.tutorials.done", JSON.stringify([...d])); } catch {} }

async function startTutorial(id, {resumeAt = null} = {}) {
  let r;
  try { r = await api(`/api/help/tutorial?id=${encodeURIComponent(id)}`); } catch (e) { return toast(e.message, {tone: "danger"}); }
  const resume = resumeAt !== null && resumeAt !== undefined;
  if (r.start_doc && !resume) {
    if (S.dirty && !S.noDoc) {
      const v = await ui.dialog({title: "Start the tutorial?", size: "sm", icon: "learn",
        body: "It opens a practice file. Your unsaved changes would be lost.",
        buttons: [{label: "Cancel", value: null, kind: "ghost", left: true}, {label: "Discard my changes", value: "discard"}, {label: "Save first", value: "save", kind: "primary"}]});
      if (!v) return;
      if (v === "save" && !(await save())) return;
    }
    clearDraft(); loadDoc(clone(r.start_doc), null, null, {silent: true});
  } else if (S.noDoc) S.noDoc = false;
  S.lastDryRun = null; S.savedAt = null; S.tab = null;
  if (r.tutorial.mode && r.tutorial.mode !== S.mode) setMode(r.tutorial.mode, {quiet: true});
  if (r.start_doc && !resume) { S.view = "story"; EDGE.go("build", {render: false}); renderAll(); }
  else if (S.ws === "home") EDGE.go("build");
  T.tut = r.tutorial; T.i = resume ? Math.min(resumeAt, r.tutorial.steps.length - 1) : 0; T.passed = false; T.min = false; T.startedAt = Date.now();
  EDGE.prefs.set("tutorial.last", null);
  renderCoach(true);
}
function stopTutorial() {
  if (T.tut && T.i < T.tut.steps.length) EDGE.prefs.set("tutorial.last", {id: T.tut.id, title: T.tut.title, i: T.i, n: T.tut.steps.length});
  T.tut = null; T.min = false;
  clearCoachMarks();
  $("#coach")?.remove();
  renderTutorialPill();
  if (EDGE.companion.isOpen("help") && HELP.view === "index") renderHelpPanel();
}
function clearCoachMarks() {
  document.querySelectorAll(".coach-target").forEach((x) => x.classList.remove("coach-target"));
  document.querySelectorAll("[data-coach-proxy]").forEach((x) => { x.classList.remove("coach-proxy"); delete x.dataset.coachProxy; });
}
function renderTutorialPill() {
  const p = $("#sb-tutorial"); if (!p) return;
  if (T.tut && T.min) {
    p.hidden = false;
    p.replaceChildren(icon("learn"), `Tutorial ${Math.min(T.i + 1, T.tut.steps.length)}/${T.tut.steps.length}`, icon("chev-right"));
    p.setAttribute("aria-label", `Show the tutorial: ${T.tut.title}, step ${T.i + 1} of ${T.tut.steps.length}`);
  } else p.hidden = true;
}

const WS_LABEL = {home: "Home", build: "Build", measures: "Measures", test: "Test", run: "Run", data: "Data"};
const VIEW_LABEL = {story: "the Storyboard", screen: "the Screen view", list: "the trial list", diagram: "the workflow diagram", source: "the YAML view"};
function needWs(ws) { return S.ws === ws ? null : {place: WS_LABEL[ws], go: () => EDGE.go(ws), proxy: `#ws-nav a[data-ws="${ws}"]`}; }
function viewNeed(view, start) {
  if (S.view === view) return null;
  if (start) { EDGE.setView(view); return null; }
  return {place: VIEW_LABEL[view], go: () => EDGE.setView(view), proxy: `#view-switch [data-view="${view}"]`, same: true};
}
function sideNeed(side, start) {
  const sb = $("#sidebar");
  const hidden = $("#side-" + side)?.hidden || (sb && sb.offsetParent === null);
  if (!hidden) return null;
  if (start) { revealSide(side); return null; }
  const rail = $(`#rail [data-side="${side}"]`);
  return {place: `the ${cap(side)} tab`, go: () => revealSide(side), proxy: rail && rail.offsetParent ? `#rail [data-side="${side}"]` : `#sidebar-tabs [data-side="${side}"]`, same: true};
}
function propsNeed(start) {
  if (!document.body.classList.contains("shared-right") || EDGE.companion.current() === "props") return null;
  if (start) { EDGE.companion.open("props"); return null; }
  return {place: "Properties", go: () => EDGE.companion.open("props"), proxy: "#companion-tab-props", same: true};
}
/* How the coach reveals a target that is not visible (§6.1): [selector pattern, (atStepStart) → need | null]. */
const TOUR_REVEAL = [
  [/rtab\.add|#btn-add-screen/, (start) => needWs("build") || (S.view === "source" ? viewNeed("story", start) : null)],
  [/\.pal-item|#palette/, (start) => needWs("build") || sideNeed("add", start)],
  [/#btn-add-device|#devices|#btn-scan|#side-devices/, (start) => needWs("build") || sideNeed("devices", start)],
  [/#files|#side-files/, (start) => needWs("build") || sideNeed("files", start)],
  [/^#props|#inspector|#props-title/, (start) => needWs("build") || propsNeed(start)],
  [/#flow\b|\.sm-states?|\.fl-box|\.fl-head|\.scard|\.frame/, (start) => needWs("build") || viewNeed("story", start)],
  [/#timeline|#preview|#stage/, (start) => needWs("build") || viewNeed("screen", start)],
  [/data-tab=source|#yaml|#btn-apply-yaml/, (start) => needWs("build") || (S.mode === "expert" ? viewNeed("source", false) : {place: "Expert mode", go: () => setMode("expert"), proxy: "#btn-mode"})],
  [/#btn-dryrun|#test-|#tab-results/, () => needWs("test")],
  [/#ws-measures|#measures/, () => needWs("measures")],
  [/#ws-run/, () => needWs("run")],
  [/data-tab=data|#nav-data|#data-/, () => null],
  [/#btn-import|#btn-versions|#btn-bundle|#btn-new|#btn-open|#menu-/, () => ({place: "the Experiment menu", go: () => ui.menu($("#docname"), $("#menu-experiment")), proxy: "#docname"})],
  [/#assistant-|#companion/, (start) => {
    if (!assistantOn()) return null;
    if (start) { EDGE.companion.open("assistant"); return null; }
    return {place: "the Assistant", go: () => EDGE.companion.open("assistant"), proxy: "#assistant-toggle"};
  }],
];
const isShown = (x) => !!x && x.isConnected && x.offsetParent !== null && x.getClientRects().length > 0 && getComputedStyle(x).visibility !== "hidden";
function coachTargets(selector) { try { return [...document.querySelectorAll(selector)]; } catch { return []; } }
/* Highlight the step's target (or the control that shows it) and return {target, need}. */
function markCoachTargets(selector, atStepStart = false) {
  let targets = coachTargets(selector);
  let target = targets.find(isShown) || null;
  let need = null;
  if (!target) {
    const rule = TOUR_REVEAL.find(([re]) => re.test(selector));
    need = rule ? rule[1](atStepStart) : null;
    if (!need && atStepStart) { targets = coachTargets(selector); target = targets.find(isShown) || null; }
  }
  document.querySelectorAll(".coach-target").forEach((x) => { if (!targets.includes(x)) x.classList.remove("coach-target"); });
  targets.forEach((x) => x.classList.add("coach-target"));
  const proxy = need && need.proxy ? $(need.proxy) : null;
  document.querySelectorAll("[data-coach-proxy]").forEach((x) => { if (x !== proxy) { x.classList.remove("coach-proxy"); delete x.dataset.coachProxy; } });
  if (proxy) { proxy.classList.add("coach-proxy"); proxy.dataset.coachProxy = "1"; }
  T.need = need; T.target = target;
  return targets;
}

function renderCoach(stepStart = true) {
  $("#coach")?.remove();
  clearCoachMarks();
  renderTutorialPill();
  if (!T.tut || T.min) return;
  const steps = T.tut.steps, st = steps[T.i];
  if (!st) {           // finished
    markTutorialDone(T.tut.id);
    EDGE.prefs.set("tutorial.last", null);
    const next = (S.tutorials || []).find((t) => !tutorialDone(t.id));
    const c = h("div", {id: "coach", class: "done", role: "dialog", "aria-label": "Tutorial complete"},
      h("div", {class: "coach-bar"}, h("i", {style: "width:100%"})),
      h("div", {class: "coach-head"}, h("span", {class: "t-overline"}, T.tut.title), h("span", {class: "grow"}),
        h("button", {class: "btn ghost icon sm", "aria-label": "Close", onclick: stopTutorial}, icon("close"))),
      h("h4", {class: "coach-title"}, icon("success", "c-ok"), "Tutorial complete."),
      h("p", {class: "coach-body"}, "Nicely done. Keep experimenting with this file, or continue learning."),
      h("div", {class: "coach-foot"},
        h("button", {class: "btn sm ghost", onclick: () => { stopTutorial(); openHelp(); }}, "All tutorials"), h("span", {class: "grow"}),
        next ? h("button", {class: "btn sm primary", onclick: () => startTutorial(next.id)}, `Next: ${next.title}`) : h("button", {class: "btn sm primary", onclick: stopTutorial}, "Close")));
    document.body.append(c);
    placeCoach(c, null);
    ui.announce("Tutorial complete.");
    return;
  }
  const ok = st.check ? tutorialCheck(st.check) : true;
  const c = h("div", {id: "coach", role: "dialog", "aria-label": `Tutorial: ${T.tut.title}, step ${T.i + 1} of ${steps.length}`});
  c.append(h("div", {class: "coach-bar"}, h("i", {style: `width:${(T.i / steps.length) * 100}%`})),
    h("div", {class: "coach-head"}, h("span", {class: "t-overline coach-name"}, T.tut.title), h("span", {class: "coach-step"}, `${T.i + 1} of ${steps.length}`),
      h("button", {class: "btn ghost icon sm", "aria-label": "Minimise the tutorial", "data-tip": "Minimise", onclick: () => { T.min = true; renderCoach(false); }}, icon("minus")),
      h("button", {class: "btn ghost icon sm", "aria-label": "Exit the tutorial", "data-tip": "Exit the tutorial", "data-tip-pos": "end", onclick: stopTutorial}, icon("close"))));
  const title = h("h4", {class: "coach-title"}); title.innerHTML = mdInline(st.title);
  const bodyEl = h("div", {class: "coach-body"}); bodyEl.innerHTML = md(st.body);
  bodyEl.querySelectorAll("a[data-topic]").forEach((a) => a.onclick = (e) => { e.preventDefault(); openHelp(a.dataset.topic, a.dataset.anchor); });
  c.append(title, bodyEl, h("div", {class: "coach-reveal", hidden: true}));
  const last = T.i === steps.length - 1;
  const next = h("button", {class: "btn sm coach-next" + (ok ? " primary" : ""), onclick: () => { T.i++; T.passed = false; renderCoach(true); }}, last ? "Finish" : "Next");
  if (st.check) c.append(h("div", {class: "coach-status" + (ok ? " ok" : ""), role: "status"}, ok ? [icon("success"), "Done"] : [h("span", {class: "spin"}), "Waiting for you…"]));
  c.append(h("div", {class: "coach-foot"},
    h("button", {class: "btn sm ghost", disabled: T.i === 0 ? true : null, onclick: () => { T.i--; T.passed = false; renderCoach(true); }}, "Back"),
    st.target ? h("button", {class: "btn sm", onclick: () => coachShowMe()}, "Show me") : null,
    st.check && !ok ? h("button", {class: "linkbtn t-small", onclick: () => { T.i++; T.passed = false; renderCoach(true); }}, "Skip step") : null,
    h("span", {class: "grow"}), next));
  c.append(h("span", {class: "coach-arrow", "aria-hidden": "true"}));
  document.body.append(c);
  if (st.target) markCoachTargets(st.target, stepStart);
  updateCoach();
  if (stepStart) for (const ms of [180, 420, 900]) setTimeout(() => { if (T.tut && T.tut.steps[T.i] === st) { if (st.target) markCoachTargets(st.target); updateCoach(); } }, ms);
  if (stepStart) ui.announce(`Step ${T.i + 1} of ${steps.length}: ${st.title.replace(/[*`]/g, "")}`);
  if (stepStart && T.target && !isInView(T.target)) T.target.scrollIntoView({block: "nearest", inline: "nearest"});
}
const isInView = (x) => { const r = x.getBoundingClientRect(); return r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth; };
function coachShowMe() {
  const st = T.tut?.steps[T.i]; if (!st?.target) return;
  markCoachTargets(st.target, true);
  if (T.need && T.need.go) { T.need.go(); setTimeout(() => { markCoachTargets(st.target, true); updateCoach(); if (T.target) { T.target.scrollIntoView({block: "center", inline: "nearest"}); EDGE.pulse(T.target); } }, 120); return; }
  if (T.target) { T.target.scrollIntoView({block: "center", inline: "nearest"}); EDGE.pulse(T.target); }
  updateCoach();
}
/* Refresh the reveal hint ("First open Test") and the position; called on every check and on resize. */
function updateCoach() {
  const c = $("#coach"); if (!c || c.classList.contains("done")) return;
  const rv = c.querySelector(".coach-reveal");
  const need = T.target ? null : T.need;
  if (rv) {
    if (need && !need.same) {
      const key = need.place;
      if (rv.dataset.key !== key) {
        rv.dataset.key = key;
        rv.replaceChildren(icon("info"), h("span", {}, "First open ", h("b", {}, need.place), "."),
          h("button", {class: "btn sm", onclick: () => { need.go(); setTimeout(() => { const st = T.tut?.steps[T.i]; if (st?.target) markCoachTargets(st.target, true); updateCoach(); }, 150); }}, "Take me there"));
      }
      rv.hidden = false;
    } else { rv.hidden = true; rv.dataset.key = ""; }
  }
  placeCoach(c, T.target || (need && need.proxy ? $(need.proxy) : null));
}
function placeCoach(c, target) {
  const vw = innerWidth, vh = innerHeight, m = 8, gap = 14;
  const top0 = 48 + m, bottom0 = vh - 28 - m;
  const cw = c.offsetWidth, ch = Math.min(c.offsetHeight, bottom0 - top0);
  let x, y, side = "none", arrow = 0;
  const visible = target && isShown(target) && isInView(target);
  if (!visible) {
    const right = S.ws === "build" && !document.body.classList.contains("shared-right") ? ($("#inspector")?.offsetWidth || 0) + 16 : 16;
    x = Math.max(m, vw - cw - right); y = bottom0 - ch;
  } else {
    const r = target.getBoundingClientRect();
    const room = {right: vw - m - r.right - gap, left: r.left - m - gap, bottom: bottom0 - r.bottom - gap, top: r.top - top0 - gap};
    const need = {right: cw, left: cw, bottom: ch, top: ch};
    // beside the target when it is in the work area; under it in the app bar; above it in the status bar
    const order = r.top < top0 ? ["bottom", "right", "left", "top"] : r.bottom > bottom0 ? ["top", "right", "left", "bottom"] : ["right", "left", "bottom", "top"];
    side = order.find((s) => room[s] >= need[s]) || order.slice().sort((a, b) => room[b] / need[b] - room[a] / need[a])[0];
    const cy = r.top + r.height / 2, cx = r.left + r.width / 2;
    if (side === "right" || side === "left") {
      x = side === "right" ? r.right + gap : r.left - gap - cw;
      y = Math.min(Math.max(top0, cy - ch / 2), bottom0 - ch);
      arrow = Math.min(Math.max(16, Math.min(Math.max(cy, r.top + 8), r.bottom - 8) - y), ch - 16);
    } else {
      y = side === "bottom" ? r.bottom + gap : r.top - gap - ch;
      x = Math.min(Math.max(m, cx - cw / 2), vw - m - cw);
      arrow = Math.min(Math.max(16, cx - x), cw - 16);
    }
    x = Math.min(Math.max(m, x), vw - m - cw);
    y = Math.min(Math.max(top0, y), Math.max(top0, bottom0 - ch));
  }
  const px = Math.round(x) + "px", py = Math.round(y) + "px";
  if (c.style.left !== px) c.style.left = px;
  if (c.style.top !== py) c.style.top = py;
  c.dataset.side = side;
  c.style.setProperty("--arrow", Math.round(arrow) + "px");
  c.style.maxHeight = (bottom0 - top0) + "px";
}

function checkTutorial() {
  if (!T.tut || T.min) return;
  const st = T.tut.steps[T.i];
  if (!st) return;
  if (st.target) markCoachTargets(st.target);          // re-apply after re-renders replaced the DOM
  updateCoach();
  if (!st.check || T.passed) return;
  if (tutorialCheck(st.check)) {
    T.passed = true; renderCoach(false);
    setTimeout(() => { if (T.tut && T.passed && T.tut.steps[T.i] === st) { T.i++; T.passed = false; renderCoach(true); } }, 1100);
  }
}
setInterval(() => checkTutorial(), 800);
window.addEventListener("resize", () => { if (T.tut) updateCoach(); });

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
  // new in the redesign (§6.2)
  workspace: (name) => S.ws === name,
  view: (name) => S.ws === "build" && S.view === name,
  assistant_open: (v) => EDGE.companion.isOpen("assistant") === (v !== false),
  assistant_applied: () => { const t = assistantApi()?.lastAppliedAt || 0; return t > 0 && t >= (T.startedAt || 0); },
};
function tutorialCheck(chk) {
  try { return Object.entries(chk).every(([k, v]) => TUTORIAL_CHECKS[k] ? TUTORIAL_CHECKS[k](v) : false); }
  catch { return false; }
}

/* ================================================================== the shell: app bar, status bar, columns, routing */
const WORKSPACES = ["home", "build", "measures", "test", "run", "data"];
const VIEWS = ["story", "screen", "list", "diagram", "source"];

/* Icons inside buttons: <button data-ic="undo"> gets icon("undo") prepended once. */
function decorateIcons(root = document) {
  root.querySelectorAll("[data-ic]").forEach((el) => {
    if (!el.querySelector(":scope > svg.ic")) el.prepend(icon(el.dataset.ic));
  });
}

function setMode(m, {quiet = false} = {}) {
  S.mode = m; try { localStorage.setItem("edge.mode", m); } catch {}
  applyMode(); renderAll(); renderIssues();
  if (!quiet) toast(m === "simple" ? "Simple mode: just the essentials" : "Expert mode: every option is visible");
  if (EDGE.companion.isOpen("help") && HELP.view === "index") renderHelpPanel();
  EDGE.emit("mode", {mode: m});
}
function applyMode() {
  document.body.classList.toggle("mode-simple", S.mode === "simple");
  const b = $("#btn-mode"); if (b && b.setValue) b.setValue(S.mode);
  if (S.mode === "simple" && S.view === "source") { S.view = "story"; if (S.tab === "source") S.tab = null; }
}
/* renderAll(): the shell, then the open workspace (§7.5.5). Data renders when it opens, not on every edit. */
function renderAll() {
  renderShell();
  if (S.ws === "build") { if (typeof renderBuild === "function") renderBuild(); if (typeof renderProps === "function") renderProps(); if (S.view === "source") renderSource(); }
  else if (S.ws === "measures") renderMeasuresWorkspace();
  else if (S.ws === "test") renderTestPage();
  else if (S.ws === "run") renderRunWorkspace();
  else if (S.ws === "home") renderHome();
  if (typeof checkTutorial === "function") checkTutorial();
}

function renderDocName() {
  const name = docName();
  $("#filename").replaceChildren(h("span", {class: "nm"}, name), icon("chev-down"));
  $("#filepath").textContent = S.path || "Not saved yet";
  $("#docname").setAttribute("aria-label", `Experiment menu: ${name}${S.path ? ", " + S.path : ", not saved yet"}`);
  document.title = S.noDoc || S.ws === "home" ? "EDGE Builder" : `${name} · EDGE Builder`;
}

function renderStatusEstimate() {
  const el = $("#sb-estimate");
  if (!el || !S.exp || S.noDoc || typeof storyEstimate !== "function") { if (el) el.textContent = ""; return; }
  let est = null;
  try { est = storyEstimate(() => { renderStatusEstimate(); if (S.ws === "build" && S.view === "story" && typeof renderTimeline === "function") renderTimeline(); }); } catch { est = null; }
  el.textContent = est && !est.error ? EDGE.fmt.estimate(est) : "";
}

function renderTestChip() {
  const el = $("#sb-test"); if (!el) return;
  if (S.noDoc || S.ws === "home") { el.replaceChildren(); return; }
  const ts = testState();
  const now = h("button", {class: "st-link sb-test-now", onclick: () => dryRun(), "aria-label": "Test now: start a test run without leaving this page"}, "Test now");
  const open = (kids, tone = "") => h("button", {class: "st-link chipish " + tone, onclick: () => EDGE.go("test"), "aria-label": "Open the Test page"}, ...kids);
  const parts = {
    none: [open(["Not tested yet"]), h("span", {class: "sep"}, "·"), now],
    testing: [h("span", {class: "spin"}), "Testing…"],
    passed: [open([icon("success"), `Tested ${ago(S.tested?.at)}`], "ok")],
    failed: [open([icon("error"), "The last test run found problems"], "danger"), h("span", {class: "sep"}, "·"), now],
    changed: [open([h("span", {class: "dot warn"}), "Changed since the last test"], "warning"), h("span", {class: "sep"}, "·"), now],
    "changed-failed": [open([h("span", {class: "dot warn"}), "Changed since the last test"], "warning"), h("span", {class: "sep"}, "·"), now],
  }[ts];
  el.replaceChildren(...parts);
}

/* Badges on the workspace tabs (§2.3): Test !2 / check / amber dot; Run: the recording pill; Data: real sessions + new dot. */
function renderBadges() {
  const bt = $("#badge-test"), bd = $("#badge-data"), nt = $("#nav-test"), nd = $("#nav-data");
  if (!bt || !S.exp) return;
  const g = problemGroups(), ts = testState();
  bt.className = "badge"; bt.replaceChildren();
  let tWord = "";
  if (g.error.length) { bt.className = "badge danger"; bt.textContent = `!${g.error.length}`; tWord = `, ${countWord(g.error.length, "problem")} to fix`; }
  else if (ts === "passed") { bt.className = "badge success"; bt.append(icon("check")); tWord = ", the last test run passed"; }
  else if (ts === "changed") { bt.className = "badge dot"; tWord = ", changed since the last test"; }
  nt.setAttribute("aria-label", `Test${tWord}`);
  const f = (S.files || []).find((x) => x.path === S.path);
  const real = f?.sessions?.real || 0;
  const seen = EDGE.prefs.get("dataSeen." + (S.path || "-"), null);
  bd.className = "badge" + (real && seen !== null && real > seen ? " new" : "");
  bd.textContent = real && !S.noDoc ? String(real) : "";
  nd.setAttribute("aria-label", `Data${real ? `, ${countWord(real, "session")}` : ""}${bd.classList.contains("new") ? ", new sessions" : ""}`);
}

/* The recording pill on the Run tab and "Recording P014" in the status bar (§2.3, §2.4, §W11). */
const pidLabel = (p) => (p == null ? "" : /^\d+$/.test(String(p)) ? "P" + p : String(p));
function runElapsed() {
  if (!S.run) return "";
  const t0 = typeof S.run.startedAt === "number" ? S.run.startedAt : Date.parse(S.run.startedAt || S.run.started || "") || S.run._seen || (S.run._seen = Date.now());
  const s = Math.max(0, Math.floor((Date.now() - t0) / 1000));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return (hh ? hh + ":" + String(mm).padStart(2, "0") : String(mm).padStart(2, "0")) + ":" + String(ss).padStart(2, "0");
}
function renderRunPill() {
  const b = $("#badge-run"), nr = $("#nav-run"), sr = $("#sb-recording");
  const live = !!(S.run && S.run.running);
  document.body.classList.toggle("recording", live);
  if (b) {
    if (live) { b.className = "badge rec"; b.replaceChildren(h("span", {class: "rec-dot"}), h("span", {class: "rec-txt"}, `${pidLabel(S.run.participant)} ${runElapsed()}`)); }
    else { b.className = "badge"; b.replaceChildren(); }
  }
  if (nr) nr.setAttribute("aria-label", live ? `Run: recording participant ${S.run.participant}, ${runElapsed()} elapsed` : "Run");
  if (sr) {
    const want = live ? `Recording ${pidLabel(S.run.participant)}` : "";
    if (sr.dataset.text !== want) { sr.dataset.text = want; sr.replaceChildren(...(live ? [h("span", {class: "rec-dot"}), want] : [])); }
    sr.hidden = !live;
  }
  if (live) showAlert("session", {tone: "info", ws: "build", icon: "run", text: "A session is running. Saved changes apply to the next participant.",
    actions: [{label: "Open Run", run: () => openRunningSession()}], dismiss: true});
  else clearAlert("session");
}
let _runWatch = null;
function watchRun() {
  if (_runWatch || !S.run?.running || !S.run.id) return;
  _runWatch = setInterval(async () => {
    if (!S.run?.running) { clearInterval(_runWatch); _runWatch = null; return; }
    try {
      const st = await api(`/api/run_status?id=${encodeURIComponent(S.run.id)}`);
      if (!st.running && S.run?.running) {
        S.run.running = false; S.run.returncode = st.returncode; S.run.endedAt = Date.now();
        clearInterval(_runWatch); _runWatch = null;
        ui.announce(`The session of participant ${S.run.participant} ended.`, {assertive: true});
        EDGE.emit("run", S.run);
        refreshFiles().then(() => renderBadges());
      }
    } catch (e) {
      if (/unknown run/i.test(e.message)) { S.run = null; clearInterval(_runWatch); _runWatch = null; EDGE.emit("run", null); }
    }
  }, 2000);
}
/* After a reload: find a session this builder started that is still recording (GET /api/runs) and bring the pill back. */
async function recoverRuns() {
  let runs = [];
  try { runs = (await api("/api/runs")).runs || []; } catch { return; }
  const live = runs.filter((r) => r.running);
  if (!live.length || S.run?.running) return;
  const r = live.find((x) => x.path === S.path) || live[0];
  S.run = {id: r.run_id, path: r.path, participant: r.participant, session: r.session, startedAt: Date.parse(r.started) || Date.now(), running: true, recovered: true};
  EDGE.emit("run", S.run);
  toast(`A session is still recording: participant ${r.participant}.`, {action: {label: "Open Run", run: () => openRunningSession()}});
}
/* The recording pill and the status bar bring you back to the running session (opening its experiment if needed). */
function openRunningSession() {
  if (!S.run) return EDGE.go("run");
  if (S.run.path && (S.noDoc || S.run.path !== S.path)) return openExperiment(S.run.path, "run");
  EDGE.go("run");
}
let _ticks = 0;
function tick() {
  _ticks++;
  if (S.run?.running) { const t = $("#badge-run .rec-txt"); if (t) t.textContent = `${pidLabel(S.run.participant)} ${runElapsed()}`; }
  if (_ticks % 30 === 0 && S.tested && !S.testing) renderTestChip();
}

/* Columns (§2.2): the companion owns a 384-px column; below 1280 px (or without the rail) it shares the right column
 * with Properties (tabs Properties · Assistant · Help) and the inspector moves into it. The sidebar becomes P4a's rail
 * below 1280 px, and between 1280 and 1599 px while the companion is open. */
function layoutColumns() {
  const comp = $("#companion"), insp = $("#inspector"), build = $("#ws-build");
  if (!comp || !insp || !build) return;
  const w = innerWidth, open = !comp.hidden;
  const hasRail = !!$("#rail")?.childElementCount;
  const shared = open && S.ws === "build" && (w < 1280 || (!hasRail && w < 1600));
  const railOn = S.ws === "build" && hasRail && (w < 1280 || (open && w < 1600));
  document.body.classList.toggle("with-companion", open);
  document.body.classList.toggle("shared-right", shared);
  document.body.classList.toggle("rail-mode", railOn);
  build.classList.toggle("rail-on", railOn);
  $("#companion-tab-props").hidden = !shared;
  if (shared && insp.parentElement !== comp) {
    comp.append(insp);
    insp.setAttribute("role", "tabpanel"); insp.setAttribute("aria-labelledby", "companion-tab-props");
  } else if (!shared && insp.parentElement !== build) {
    build.insertBefore(insp, $("#center").nextSibling);
    insp.removeAttribute("role"); insp.removeAttribute("aria-labelledby");
    if (S.companion === "props") EDGE.companion.open(EDGE.prefs.get("layout", {})?.companion || "help", {persist: false});
  }
  comp.classList.toggle("tab-props", shared && S.companion === "props");
}
window.addEventListener("resize", () => { clearTimeout(layoutColumns._t); layoutColumns._t = setTimeout(layoutColumns, 60); });
function restoreLayout() {
  const L = EDGE.prefs.get("layout", {}) || {};
  if (L.sidebarTab && ["add", "files", "devices"].includes(L.sidebarTab)) showSide(L.sidebarTab, {persist: false});
  if (L.companion === "help" || (L.companion === "assistant" && assistantOn())) EDGE.companion.open(L.companion, {persist: false, focus: false});
}
function saveLayout(patch) { const L = EDGE.prefs.get("layout", {}) || {}; EDGE.prefs.set("layout", {...L, ...patch}); }

/* The app bar, the status bar, the alert strips and which workspace is visible; runs first in every renderAll(). */
let _lastSel = "null";
function renderShell() {
  const home = S.ws === "home";
  for (const m of document.querySelectorAll("#body > main.ws")) m.hidden = m.dataset.ws !== S.ws;
  for (const a of document.querySelectorAll("#ws-nav a[data-ws]")) {
    if (a.dataset.ws === S.ws) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  document.body.dataset.ws = S.ws;
  renderDocName();
  const u = $("#btn-undo"), r = $("#btn-redo");
  u.disabled = !S.history.length && !S.proposal; r.disabled = !S.future.length || !!S.proposal;
  const ut = S.proposal ? `Discard the assistant's changes (${MOD}+Z)` : S.history.length ? `Undo: ${stepLabel("undo")} (${MOD}+Z)` : "Nothing to undo";
  const rt = S.future.length && !S.proposal ? `Redo: ${stepLabel("redo")} (${MOD}+Shift+Z)` : "Nothing to redo";
  u.dataset.tip = ut; u.setAttribute("aria-label", ut); r.dataset.tip = rt; r.setAttribute("aria-label", rt);
  $("#try-split").hidden = home || (S.ws === "run" && !!S.run?.running);
  $("#btn-try").dataset.tip = S.proposal ? `Try the proposed version (${MOD}+Enter)` : `Try it yourself, right here (${MOD}+Enter)`;
  $("#assistant-toggle").hidden = !assistantOn();
  $("#companion-tab-assistant").hidden = !assistantOn();
  const devs = S.exp?.devices || [];
  const sd = $("#sb-devices");
  sd.textContent = devs.length && !home ? countWord(devs.length, "device") : "";
  sd.title = devs.map((d) => `${d.id} (${d.type})`).join(", ");
  $("#sb-home").hidden = !home;
  $("#btn-validate").hidden = home;
  renderStatusEstimate();
  if (home) $("#sb-estimate").textContent = "";
  renderTestChip();
  renderBadges();
  renderRunPill();
  renderProposalBar();
  setSaveState(S._saveState);
  layoutColumns();
  renderAlerts();
  if (S.booted) syncHash();
  const sel = JSON.stringify(S.sel ?? null);
  if (sel !== _lastSel) {
    _lastSel = sel; setTimeout(() => EDGE.emit("selection", {sel: S.sel}), 0);
    if (EDGE.companion.isOpen("help") && HELP.view === "index") setTimeout(() => renderHelpPanel(), 0);
  }
}

/* Show a sidebar tab, opening P4a's flyout when the rail is showing. */
function revealSide(side) { if (typeof openFlyout === "function") openFlyout(side, {focus: false}); else showSide(side, {open: true}); }
/* Sidebar tabs of the Build workspace: add | files | devices (remembered in edge.layout). */
function showSide(name, {persist = true, open = false} = {}) {
  for (const s of ["add", "files", "devices"]) $("#side-" + s).hidden = s !== name;
  $("#sidebar-tabs").setValue?.(name);
  S.side = name;
  if (persist) saveLayout({sidebarTab: name});
  if (open && $("#ws-build").classList.contains("rail-on")) $("#sidebar").classList.add("open");
  if (name === "files" && typeof renderFiles === "function") renderFiles();
}

/* Until P4b provides renderMeasuresPage / renderRunPage, these pages open today's dialogs. */
function pageFallback(title, text, label, ic, run) {
  return h("div", {class: "page-fallback"}, h("header", {class: "page-head"}, h("h1", {class: "t-title-l"}, title)),
    h("div", {class: "card pad"}, h("p", {class: "t-2"}, text), h("button", {class: "btn primary", onclick: run}, icon(ic), label)));
}
function renderMeasuresWorkspace() {
  const el = $("#ws-measures");
  if (typeof renderMeasuresPage === "function") return renderMeasuresPage(el);
  if (!el.childElementCount) el.append(pageFallback("Measures",
    "Say what this experiment measures, and see everything it records. After every session EDGE summarises it per participant and condition and checks it against what you expect.",
    "Open measures", "measures", () => openMeasures()));
}
function renderRunWorkspace() {
  const el = $("#ws-run");
  if (typeof renderRunPage === "function") return renderRunPage(el);
  if (!el.childElementCount) el.append(pageFallback("Run with a participant",
    "The experiment opens in its own window on this computer and the data is saved as it runs. Choose the participant and the session, check the computer and the devices, then start.",
    "Run with a participant…", "run", () => { S.strict = true; runDialog(); }));
}
function openExperimentSettings(section) {
  if (typeof openSettings === "function") return openSettings(section);
  EDGE.go("build", {render: false}); S.sel = {kind: "settings"}; renderAll();
}

/* The assistant's preview: the proposal bar under the app bar (§W16). */
function proposalCount(m = {}) {
  return ["routines", "components", "loops", "devices"].reduce((a, k) => a + Object.keys(m[k] || {}).length, 0)
    + (m.settings ? 1 : 0) + (m.measures ? 1 : 0) + (m.removed || []).length;
}
function renderProposalBar() {
  const bar = $("#proposal-bar");
  const p = S.proposal;
  if (!p) { if (!bar.hidden) { bar.hidden = true; bar.replaceChildren(); } return; }
  const n = proposalCount(p.marks || {});
  const key = `${n}|${p.label}|${p.conflict}`;
  if (bar.dataset.key === key && !bar.hidden) return;
  bar.dataset.key = key;
  const what = n ? `Previewing ${countWord(n, "change")} from the assistant.` : "Previewing changes from the assistant.";
  bar.replaceChildren(icon("assistant", "m"),
    h("span", {class: "msg"}, h("b", {}, what), " Nothing is changed until you apply."),
    h("button", {class: "btn sm", onclick: () => EDGE.proposal.discard(), "data-tip": "Esc"}, "Discard"),
    h("button", {class: "btn sm primary", onclick: () => EDGE.proposal.apply(), "data-tip": `${MOD}+Enter`, "data-tip-pos": "end"}, "Apply changes"));
  bar.setAttribute("role", "region"); bar.setAttribute("aria-label", "Assistant preview"); bar.tabIndex = -1;
  bar.hidden = false;
}
function endProposal(emit = true) {
  S.proposal = null;
  document.body.classList.remove("proposal");
  renderProposalBar();
  if (emit) EDGE.emit("proposal", {active: false});
}

/* ---------------- hash routes (§2.5): #/home #/build #/build/screen/<rid> #/build/list/<loopid> #/build/source #/measures … */
function parseRoute(hash) {
  const m = String(hash || "").match(/^#\/([a-z]+)(?:\/([a-z]+)(?:\/(.+))?)?$/);
  return m ? {ws: m[1], view: m[2] || null, arg: m[3] ? decodeURIComponent(m[3]) : null} : null;
}
function selNode() { if (!S.sel?.path) return null; try { return getNode(S.sel.path); } catch { return null; } }
function currentRoute() {
  if (S.ws !== "build") return "#/" + S.ws;
  if (S.view === "screen" && S.routine) return "#/build/screen/" + encodeURIComponent(S.routine);
  if (S.view === "source") return "#/build/source";
  if (S.view === "list" || S.view === "diagram") { const n = selNode(); const id = n?.loop ?? n?.statemachine; if (id) return `#/build/${S.view}/${encodeURIComponent(id)}`; }
  return "#/build";
}
let _routing = false;
function syncHash(replace = false) {
  const want = currentRoute();
  if (location.hash === want) return;
  try { history[replace || _routing ? "replaceState" : "pushState"](null, "", want); } catch { /* sandboxed */ }
}
function routeFromHash(initial = false) {
  const r = parseRoute(location.hash);
  _routing = true;
  try {
    if (!r) return;
    if (r.ws === "help") { openHelp(r.view ? r.view.toUpperCase() : null, r.arg); return; }
    if (!WORKSPACES.includes(r.ws)) return;
    if (S.noDoc && r.ws !== "home") { EDGE.go("home"); return; }
    if (r.ws === "build" && r.view) {
      if (r.view === "screen" && r.arg && S.exp.routines[r.arg]) return EDGE.setView("screen", {routine: r.arg});
      if (r.view === "list" && r.arg) { const p = findFlowPath((n) => n.loop === r.arg); if (p) return EDGE.setView("list", {path: p}); }
      if (r.view === "diagram" && r.arg) { const p = findFlowPath((n) => n.statemachine === r.arg); if (p) return EDGE.setView("diagram", {path: p}); }
      if (r.view === "source") return EDGE.setView(S.mode === "expert" ? "source" : "story");
      return EDGE.setView("story");
    }
    if (r.ws === "build" && !initial && S.ws === "build" && S.view !== "story") return EDGE.setView("story");
    if (r.ws !== S.ws || r.ws === "home" || initial) EDGE.go(r.ws);
  } finally {
    _routing = false;
    if (!S.booted) S.booted = true;
    syncHash(true);
  }
}

/* ================================================================== Preferences (§W14), shortcuts, About */
function setTheme(v) {
  if (v === "light" || v === "dark") document.documentElement.dataset.theme = v; else delete document.documentElement.dataset.theme;
  EDGE.prefs.set("theme", v === "light" || v === "dark" ? v : null);
}
function setDensity(v) {
  if (v === "compact") document.documentElement.dataset.density = "compact"; else delete document.documentElement.dataset.density;
  EDGE.prefs.set("density", v === "compact" ? "compact" : null);
  renderAll();
}
function preferencesDialog() {
  let n = 0;
  const row = (label, control, help) => {
    const id = "pref-" + (++n);
    if (control.setAttribute && control.classList.contains("seg")) control.setAttribute("aria-labelledby", id);
    return h("div", {class: "pref-row"}, h("div", {class: "pref-label", id}, label), h("div", {class: "pref-ctl"}, control, help ? h("p", {class: "t-caption"}, help) : null));
  };
  const theme = document.documentElement.dataset.theme || "system";
  const assistantRow = h("div", {class: "pref-stack"});
  if (assistantApi()) {
    const show = ui.switch(!EDGE.prefs.get("assistant.hidden", false), (v) => { EDGE.prefs.set("assistant.hidden", !v); if (!v) EDGE.companion.close(); renderShell(); if (S.ws === "home") { HOME.mounted = null; renderHome(); } }, {label: "Show the assistant"});
    const auto = ui.switch(!!EDGE.prefs.get("assistant.autoApply", false), (v) => EDGE.prefs.set("assistant.autoApply", v), {label: "Apply its changes right away (you can always undo)",
      caption: "Changes that replace most of the experiment, or that clash with your edits, are always shown first."});
    put(assistantRow, h("div", {class: "pref-inline"}, show, h("button", {class: "btn sm", onclick: () => assistantApi()?.openSettings?.()}, "Assistant settings…")), auto);
  } else assistantRow.append(h("p", {class: "t-small t-2"}, "The assistant isn't available in this version of the builder."));
  const body = h("div", {class: "prefs"},
    row("View", ui.seg([{value: "simple", label: "Simple"}, {value: "expert", label: "Expert"}], S.mode, (v) => setMode(v)), "Simple shows the essentials; Expert shows every option."),
    row("Theme", ui.seg([{value: "system", label: "System"}, {value: "light", label: "Light", icon: "sun"}, {value: "dark", label: "Dark", icon: "moon"}], theme, setTheme)),
    row("Density", ui.seg([{value: "comfortable", label: "Comfortable"}, {value: "compact", label: "Compact"}], document.documentElement.dataset.density === "compact" ? "compact" : "comfortable", setDensity)),
    row("On start", ui.seg([{value: "last", label: "Reopen the last experiment"}, {value: "home", label: "Show Home"}], EDGE.prefs.get("start", "last"), (v) => EDGE.prefs.set("start", v))),
    row("Assistant", assistantRow),
    row("Tutorials", h("div", {}, h("button", {class: "btn sm", onclick: async () => {
      if (!(await ui.confirm({title: "Reset tutorial progress?", message: "Every tutorial shows as not done again. Your experiments are not touched.", ok: "Reset progress"}))) return;
      try { localStorage.removeItem("edge.tutorials.done"); } catch { /* private mode */ }
      EDGE.prefs.set("tutorial.last", null); toast("Tutorial progress reset."); if (S.ws === "home") renderHome();
    }}, "Reset tutorial progress"))),
    row("Keyboard", h("div", {}, h("button", {class: "btn sm", onclick: () => keyboardDialog()}, icon("command"), "Keyboard shortcuts…"))));
  ui.dialog({title: "Preferences", icon: "settings", size: "md", body, buttons: [{label: "Done", value: null, kind: "primary"}]});
}
const SHORTCUTS = [
  [`${MOD} K`, "Search everything (command palette)"], [`${MOD} I`, "Open the assistant (what you selected becomes its context)"],
  [`${MOD} S · ${MOD} Shift S`, "Save · save a copy"], [`${MOD} O`, "Open an experiment"],
  [`${MOD} Z · ${MOD} Shift Z`, "Undo · redo (during an assistant preview: discard)"],
  [`${MOD} Enter`, "Try it (this screen in the Screen view); in an assistant preview: apply"], [`${MOD} Shift Enter`, "Start a test run"],
  [IS_MAC ? "⌃1 … ⌃5" : "Alt 1 … 5", "Build, Measures, Test, Run, Data"], ["Enter · Esc", "Open the selection · go up one level, close, stop Try it"],
  ["[ · ]", "Previous · next screen"], [`${MOD} [ · ${MOD} ]`, "Previous · next trial-list row in the preview"],
  ["/", "Quick add (screen editor)"], ["Space", "Play or pause the preview (stage focused)"],
  [`F2 · ${MOD} D · Delete`, "Rename · duplicate · delete the selection"], ["Alt ↑ ↓ ← →", "Move the selection in the flow or the drawing order"],
  ["Arrows · Shift arrows", "Stage: nudge 1 · 10 px; timeline bar: move 0.05 · 0.5 s"], ["? · F1", "Help · help for the focused field"],
  ["F6 · Shift F6", "Move between regions: app bar, sidebar, canvas, inspector, companion, status bar"], ["Shift F10", "The selection's menu"],
];
function keyboardDialog() {
  const kbd = (s) => s.split(" ").flatMap((p, i) => p === "·" || p === "…" ? [h("span", {class: "t-3"}, ` ${p} `)] : [i ? " " : "", h("kbd", {class: "kbd"}, p)]);
  ui.dialog({title: "Keyboard shortcuts", icon: "command", size: "md", buttons: [{label: "Close", value: null}],
    body: h("table", {class: "grid keys"}, h("tbody", {}, SHORTCUTS.map(([k, v]) => h("tr", {}, h("td", {class: "k"}, kbd(k)), h("td", {}, v))))),
  });
}
/* Kept name: showHelp() shows the keyboard shortcuts. */
function showHelp() { keyboardDialog(); }
function aboutDialog() {
  let closeIt = () => {};
  ui.dialog({title: "About EDGE", size: "sm", buttons: [{label: "Close", value: null}], onOpen: (_d, close) => { closeIt = close; }, body: h("div", {class: "about"},
    h("img", {src: "/assets/edge-128.png", alt: "", width: 56, height: 56}),
    h("div", {}, h("p", {}, h("b", {}, "EDGE experiment builder"), " for behavioural, eye-tracking, EEG and physiology experiments."),
      h("p", {class: "t-small t-2"}, `The builder runs on this computer${S.root ? ` and works in ${shortRoot()}` : ""}. Nothing leaves it unless you use an online assistant.`),
      h("p", {}, h("button", {class: "linkbtn", onclick: () => { closeIt(); openHelp("README"); }}, "Documentation"), " · ", h("button", {class: "linkbtn", onclick: () => { closeIt(); keyboardDialog(); }}, "Keyboard shortcuts"))))});
}
function moreMenu() {
  ui.menu($("#btn-more"), [
    {label: "Preferences…", icon: "settings", run: () => preferencesDialog()},
    {label: "Keyboard shortcuts", icon: "command", shortcut: "?", run: () => keyboardDialog()},
    {sep: true},
    {label: "Find connected devices", icon: "chip", run: () => { if (S.noDoc) return toast("Open an experiment first: found devices are added to it."); showTab("hardware"); if (typeof scanHardware === "function") scanHardware(); }},
    {label: "Check this computer", icon: "screen", run: () => computerDialog()},
    {label: "Make a support bundle", icon: "package", run: () => supportBundle()},
    {sep: true},
    {label: "About EDGE", icon: "info", run: () => aboutDialog()},
  ], {placement: "bottom-end"});
}
function tryMenu() {
  const scr = S.ws === "build" && S.view === "screen" && S.routine;
  ui.menu($("#btn-try-menu"), [
    {label: S.proposal ? "Try the proposed version" : "Try the whole experiment", icon: "play", shortcut: `${MOD} Enter`, run: () => tryNow("all")},
    scr ? {label: `Try only “${S.routine}” (5 trials)`, icon: "screen", run: () => tryNow("screen")} : null,
    {sep: true},
    {label: "Start a test run (virtual participant)", icon: "test", shortcut: `${MOD} Shift Enter`, run: () => dryRun()},
    {label: "Check for problems now", icon: "checklist", run: async () => { await validate(); openProblems(); }},
  ].filter(Boolean), {placement: "bottom-end"});
}
function experimentMenu() {
  const recent = (EDGE.prefs.get("recent", []) || []).filter((p) => p !== S.path && (S.files || []).some((f) => f.path === p)).slice(0, 5);
  const host = $("#menu-recent");
  host.replaceChildren(...(recent.length ? [h("div", {class: "head", role: "presentation"}, "Recent"),
    ...recent.map((p) => h("button", {class: "item", role: "menuitem", onclick: () => openExperiment(p)}, icon("file"), h("span", {class: "lbl"}, p.split("/").pop().replace(/\.(ya?ml|json)$/i, "")), h("span", {class: "sc"}, p.split("/")[0])))] : []));
  ui.menu($("#docname"), $("#menu-experiment"));
}

/* ================================================================== command palette (§W18) */
const PAL = {open: false};
function scoreMatch(text, q) {
  if (!q) return 1;
  text = text.toLowerCase();
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  let score = 0;
  for (const w of words) {
    const i = text.indexOf(w);
    if (i < 0) return 0;
    score += i === 0 ? 3 : /[\s›“"(_./-]/.test(text[i - 1]) ? 2 : 1;
  }
  return score;
}
function paletteSources(q, only) {
  const out = [];
  const doc = S.exp && !S.noDoc;
  if (doc && only !== "add") {
    for (const rid of Object.keys(S.exp.routines)) {
      out.push({group: "Go to", icon: "screen", label: `Screen “${rid}”`, sub: typeof screenSummary === "function" ? safe(() => screenSummary(rid)) : "", run: () => EDGE.setView("screen", {routine: rid})});
      for (const c of comps(rid)) out.push({group: "Go to", icon: (typeof TYPE_ICON !== "undefined" && TYPE_ICON[c.type]) || "screen", label: `${rid} › ${c.id}`, sub: friendlyName(c.type), keys: c.type, run: () => EDGE.select({kind: "component", routine: rid, id: c.id}, {pulse: true}), minQ: 1});
    }
    walkFlow((n, p) => {
      if (n?.loop !== undefined) out.push({group: "Go to", icon: "loop", label: `Trial list “${n.loop}”`, run: () => EDGE.select({kind: "loop", path: p}, {pulse: true})});
      if (n?.statemachine !== undefined) out.push({group: "Go to", icon: "workflow", label: `Workflow “${n.statemachine}”`, run: () => EDGE.select({kind: "machine", path: p}, {pulse: true})});
    });
    (S.exp.devices || []).forEach((d, i) => out.push({group: "Go to", icon: "device", label: `Device “${d.id}”`, sub: d.type, run: () => EDGE.select({kind: "device", index: i}, {pulse: true})}));
    const ms = Array.isArray(S.exp.measures) ? S.exp.measures : Object.entries(S.exp.measures || {}).map(([id, m]) => ({id, ...m}));
    for (const m of ms) out.push({group: "Go to", icon: "measures", label: `Measure “${m.label || m.id || m.name}”`, run: () => EDGE.go("measures"), minQ: 1});
  }
  if (doc && (q || only === "add")) {
    const target = S.routine && S.exp.routines[S.routine] ? S.routine : null;
    if (target) for (const type of Object.keys(S.schema.components)) out.push({group: "Add", icon: "plus", label: `${friendlyName(type)} to “${target}”`, sub: S.mode === "expert" ? type : "", keys: type,
      run: () => { if (S.ws !== "build" || S.view !== "screen") EDGE.setView("screen", {routine: target}); if (typeof addComponent === "function") addComponent(type); }});
  }
  if (only !== "add") {
    for (const it of EDGE.palette.items()) {
      if (typeof it.when === "function" && !safe(() => it.when())) continue;
      out.push({group: it.group || "Action", icon: it.icon || "command", label: it.label, shortcut: it.keys || "", run: it.run, keys: it.keywords || ""});
    }
    if (!only) for (const f of S.files || []) if (f.path !== S.path || S.noDoc) out.push({group: "Recent", icon: "file", label: `Open “${f.path.split("/").pop().replace(/\.(ya?ml|json)$/i, "")}”`, sub: f.path, run: () => openExperiment(f.path), minQ: 1});
  }
  return out;
}
function safe(fn) { try { return fn(); } catch { return ""; } }
function openPalette(initial = "", {only = null} = {}) {
  if (PAL.open) return;
  PAL.open = true;
  const opener = document.activeElement;
  const input = h("input", {class: "pal-input", type: "text", role: "combobox", "aria-expanded": "true", "aria-controls": "pal-list", "aria-autocomplete": "list",
    "aria-label": only === "add" ? "Add an item" : "Search screens, items, actions and help", autocomplete: "off", spellcheck: "false",
    placeholder: only === "add" ? `Add to “${S.routine || "this screen"}”…` : "Search screens, items, actions and help", value: initial});
  const list = h("ul", {class: "pal-list", id: "pal-list", role: "listbox", "aria-label": "Results"});
  const box = h("div", {class: "palette", role: "dialog", "aria-modal": "true", "aria-label": only === "add" ? "Quick add" : "Command palette"},
    h("div", {class: "pal-top"}, icon("search", "m"), input, h("kbd", {class: "kbd"}, "Esc")), list,
    h("div", {class: "pal-foot t-caption"}, h("span", {}, h("kbd", {class: "kbd"}, "↑"), h("kbd", {class: "kbd"}, "↓"), " to move"), h("span", {}, h("kbd", {class: "kbd"}, "Enter"), " to choose")));
  const scrim = h("div", {class: "scrim pal-scrim"}, box);
  $("#dialogs").append(scrim);
  const release = ui.trapFocus(box);
  let shown = [], active = 0, helpHits = [], helpFor = "", timer = null;
  const close = (restore = true) => {
    if (!PAL.open) return;
    PAL.open = false; release(); scrim.remove(); clearTimeout(timer);
    if (restore && opener && opener.isConnected) opener.focus?.();
  };
  PAL.close = close;
  const draw = () => {
    const q = input.value.trim();
    let items = paletteSources(q, only).filter((it) => !it.minQ || q.length >= it.minQ)
      .map((it) => ({...it, score: scoreMatch(`${it.label} ${it.sub || ""} ${it.keys || ""}`, q)})).filter((it) => it.score > 0);
    if (q && helpFor === q) items.push(...helpHits);
    const ORDER = ["Go to", "Add", "Action", "Help", "Recent"];
    const by = {};
    for (const it of items) (by[it.group] ||= []).push(it);
    shown = [];
    for (const g of [...ORDER, ...Object.keys(by).filter((g) => !ORDER.includes(g))]) {
      if (!by[g]) continue;
      const lim = q ? 8 : g === "Action" ? 8 : g === "Go to" ? 6 : 4;
      shown.push(...by[g].sort((a, b) => b.score - a.score).slice(0, lim));
    }
    const fb = q && only !== "add" ? safe(() => EDGE.palette.fallback()?.(q)) : null;
    if (fb && fb.label) shown.push({group: "", icon: "assistant", label: fb.label, shortcut: `${MOD} I`, run: fb.run, fallback: true});
    active = fb && q.split(/\s+/).length >= 4 ? shown.length - 1 : 0;
    list.replaceChildren();
    let last = null;
    if (!shown.length) list.append(h("li", {class: "pal-none", role: "presentation"}, q ? `Nothing called “${q}”. Try another word${assistantOn() ? ", or ask the assistant" : ""}.` : "Type to search."));
    shown.forEach((it, i) => {
      if (it.group !== last && it.group) list.append(h("li", {class: "pal-head", role: "presentation"}, it.group));
      if (it.fallback) list.append(h("li", {class: "pal-sep", role: "presentation"}));
      last = it.group;
      const li = h("li", {class: "pal-opt" + (it.fallback ? " fallback" : ""), role: "option", id: `pal-opt-${i}`, "aria-selected": i === active ? "true" : "false",
        onmousemove: () => setActive(i), onclick: () => choose(i)},
        icon(it.icon || "command"), h("span", {class: "lbl"}, it.label), it.sub ? h("span", {class: "sub"}, it.sub) : null, it.shortcut ? h("span", {class: "sc"}, it.shortcut) : null);
      list.append(li);
    });
    input.setAttribute("aria-activedescendant", shown.length ? `pal-opt-${active}` : "");
    if (q && q !== helpFor && only !== "add") {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        let results = [];
        try { results = (await api(`/api/help/search?q=${encodeURIComponent(q)}`)).results || []; } catch { results = []; }
        if (!PAL.open || input.value.trim() !== q) return;
        helpFor = q;
        helpHits = results.slice(0, 5).map((r) => ({group: "Help", icon: r.topic === "tutorial" ? "learn" : "book", label: `${r.section}`, sub: r.topic === "tutorial" ? "tutorial" : r.topic,
          run: () => (r.topic === "tutorial" ? startTutorial(r.anchor) : openHelp(r.topic, r.anchor)), score: 1}));
        const keep = shown[active]?.label;
        draw();
        const k = shown.findIndex((x) => x.label === keep); if (k >= 0) setActive(k);
      }, 220);
    }
  };
  const setActive = (i) => {
    if (i < 0 || i >= shown.length) return;
    list.querySelector(`#pal-opt-${active}`)?.setAttribute("aria-selected", "false");
    active = i;
    const li = list.querySelector(`#pal-opt-${i}`);
    li?.setAttribute("aria-selected", "true"); li?.scrollIntoView({block: "nearest"});
    input.setAttribute("aria-activedescendant", `pal-opt-${i}`);
  };
  const choose = async (i) => { const it = shown[i]; if (!it) return; close(false); try { await it.run(); } catch (e) { toast(e.message, {tone: "danger"}); } };
  input.addEventListener("input", draw);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(shown.length - 1, active + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(0, active - 1)); }
    else if (e.key === "Home" && e.ctrlKey) { e.preventDefault(); setActive(0); }
    else if (e.key === "Enter") { e.preventDefault(); choose(active); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "Tab") { e.preventDefault(); }
  });
  scrim.addEventListener("mousedown", (e) => { if (e.target === scrim) close(); });
  draw();
  setTimeout(() => { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }, 0);
}
function registerActions() {
  const A = (id, label, run, extra = {}) => EDGE.palette.register({id: "edge." + id, label, run, group: "Action", ...extra});
  const docOpen = () => !S.noDoc;
  A("new", "New experiment…", () => EDGE.go("home"), {icon: "file"});
  A("open", "Open an experiment…", () => openDialog(), {icon: "folder", keys: `${MOD} O`});
  A("import", "Import from PsychoPy, E-Prime, OpenSesame or jsPsych…", () => chooseImportFiles(), {icon: "import"});
  A("save", "Save", () => save(), {icon: "save", keys: `${MOD} S`, when: docOpen});
  A("savecopy", "Save a copy…", () => save(true), {icon: "save", keys: `${MOD} Shift S`, when: docOpen});
  A("history", "History: saved versions…", () => versionsDialog(), {icon: "history", when: docOpen});
  A("bundle", "Share as one file (.edgez)", () => $("#btn-bundle").click(), {icon: "package", when: docOpen});
  A("settings", "Experiment settings…", () => openExperimentSettings(), {icon: "settings", when: docOpen});
  A("try", "Try the whole experiment", () => tryNow("all"), {icon: "play", keys: `${MOD} Enter`, when: docOpen});
  A("testrun", "Start a test run", () => dryRun(), {icon: "test", keys: `${MOD} Shift Enter`, when: docOpen});
  A("check", "Check for problems", async () => { await validate(); openProblems(); }, {icon: "checklist", when: docOpen});
  A("addscreen", "Add a screen", () => { EDGE.go("build"); if (typeof newRoutine === "function") newRoutine(); }, {icon: "plus", when: docOpen});
  const ws = [["build", "Build", "design"], ["measures", "Measures", "measures"], ["test", "Test", "test"], ["run", "Run", "run"], ["data", "Data", "results"]];
  ws.forEach(([w, label, ic], i) => A("go." + w, `Go to ${label}`, () => EDGE.go(w), {icon: ic, keys: IS_MAC ? `⌃${i + 1}` : `Alt ${i + 1}`, when: docOpen}));
  A("home", "Go Home: all experiments", () => EDGE.go("home"), {icon: "home"});
  A("yaml", "Show the YAML", () => EDGE.setView("source"), {icon: "code", when: () => docOpen() && S.mode === "expert"});
  A("mode", "Switch to Expert mode", () => setMode("expert"), {icon: "settings", when: () => S.mode === "simple"});
  A("mode2", "Switch to Simple mode", () => setMode("simple"), {icon: "settings", when: () => S.mode === "expert"});
  A("prefs", "Preferences…", () => preferencesDialog(), {icon: "settings"});
  A("theme.dark", "Theme: dark", () => setTheme("dark"), {icon: "moon"});
  A("theme.light", "Theme: light", () => setTheme("light"), {icon: "sun"});
  A("theme.system", "Theme: same as the system", () => setTheme("system"), {icon: "screen"});
  A("keys", "Keyboard shortcuts", () => keyboardDialog(), {icon: "command", keys: "?"});
  A("help", "Help and tutorials", () => openHelp(), {icon: "help"});
  A("devices", "Find connected devices", () => { showTab("hardware"); if (typeof scanHardware === "function") scanHardware(); }, {icon: "chip", when: docOpen});
  A("computer", "Check this computer", () => computerDialog(), {icon: "screen"});
  A("support", "Make a support bundle", () => supportBundle(), {icon: "package", when: docOpen});
  A("undo", "Undo", () => undo(), {icon: "undo", keys: `${MOD} Z`, when: () => S.history.length > 0});
  A("redo", "Redo", () => redo(), {icon: "redo", keys: `${MOD} Shift Z`, when: () => S.future.length > 0});
}

/* ================================================================== keyboard map (§2.10) */
const isTyping = () => { const a = document.activeElement; return !!a && (["INPUT", "TEXTAREA", "SELECT"].includes(a.tagName) || a.isContentEditable); };
const REGIONS = ["#appbar", "#banner", "#proposal-bar", "#rail", "#sidebar", "#center", "#inspector", "#ws-home", "#ws-measures", "#ws-test", "#ws-run", "#ws-data", "#companion", "#statusbar"];
function cycleRegion(dir) {
  const regs = REGIONS.map((s) => $(s)).filter((el) => el && isShown(el) && el.offsetWidth > 0 && !(el.id === "rail" && !el.childElementCount));
  if (!regs.length) return;
  const cur = regs.findIndex((r) => r.contains(document.activeElement));
  const next = regs[(cur + dir + regs.length) % regs.length];
  const f = [...next.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select, textarea, [tabindex="0"]')].find(isShown);
  if (f) f.focus(); else { next.tabIndex = -1; next.focus(); }
}
function goUpOneLevel() {
  if (S.ws !== "build") return false;
  if ($("#ws-build").classList.contains("focus") && typeof toggleBigPreview === "function") { toggleBigPreview(); return true; }
  if (S.sel?.kind === "component") { S.sel = {kind: "routine", routine: S.sel.routine}; renderAll(); return true; }
  if (S.view === "screen" || S.view === "list" || S.view === "diagram") { EDGE.setView("story"); return true; }
  if (S.sel) { EDGE.select(null, {reveal: false}); return true; }
  return false;
}
function stepScreen(delta) {
  const order = routineInFlowOrder();
  if (!order.length) return;
  const i = order.indexOf(S.routine);
  const rid = order[Math.min(order.length - 1, Math.max(0, (i < 0 ? 0 : i + delta)))];
  if (typeof openScreen === "function") openScreen(rid); else EDGE.setView("screen", {routine: rid});
}
function deleteSelection() {
  const sel = S.sel; if (!sel) return;
  if (sel.kind === "component") {
    const list = comps(sel.routine); const i = list.findIndex((c) => c.id === sel.id); if (i < 0) return;
    list.splice(i, 1); S.sel = {kind: "routine", routine: sel.routine};
    commit(`Delete “${sel.id}”`);
    const idx = EDGE.historyIndex();
    toast(`Deleted “${sel.id}”.`, {action: {label: "Undo", run: () => { if (!EDGE.undoIf(idx)) toast(`Use Undo in the toolbar (${MOD}+Z).`); }}});
  } else if (sel.kind === "routine" && typeof deleteRoutine === "function") deleteRoutine(sel.routine);
  else if (sel.kind === "device") {
    const d = S.exp.devices[sel.index]; if (!d) return;
    S.exp.devices.splice(sel.index, 1); S.sel = null;
    commit(`Remove device “${d.id}”`);
    const idx = EDGE.historyIndex();
    toast(`Removed device “${d.id}”.`, {action: {label: "Undo", run: () => { if (!EDGE.undoIf(idx)) toast(`Use Undo in the toolbar (${MOD}+Z).`); }}});
  }
}
function duplicateSelection() {
  const sel = S.sel; if (!sel) return;
  if (sel.kind === "component") {
    const list = comps(sel.routine); const i = list.findIndex((c) => c.id === sel.id); if (i < 0) return;
    const cp = clone(list[i]); cp.id = uniqueId(list[i].id, allCompIds());
    list.splice(i + 1, 0, cp); S.sel = {kind: "component", routine: sel.routine, id: cp.id};
    commit(`Duplicate “${sel.id}”`);
  }
}
async function renameSelection() {
  const sel = S.sel; if (!sel) return;
  if (sel.kind === "routine" && typeof renameRoutine === "function") return renameRoutine(sel.routine);
  if (sel.kind === "component" && typeof renameComp === "function") {
    const c = findComp(sel.routine, sel.id); if (!c) return;
    const taken = new Set(comps(sel.routine).map((x) => x.id)); taken.delete(c.id);
    const v = await ui.prompt({title: `Rename “${c.id}”`, label: "Name", value: c.id, ok: "Rename", transform: (x) => ui.slug(x),
      validate: (x) => (!x ? "Type a name first." : taken.has(x) ? "Another item on this screen has that name." : null)});
    if (v && v !== c.id) renameComp(c, v);
  }
}
function onKey(e) {
  if (e.defaultPrevented) return;
  if ($("#play") && !$("#play").classList.contains("hidden")) return;          // Try it owns the keyboard
  const mod = e.ctrlKey || e.metaKey, key = e.key, low = key.length === 1 ? key.toLowerCase() : key;
  const typing = isTyping();
  const dialogOpen = !!document.querySelector("#dialogs .scrim") || !$("#modal").classList.contains("hidden");
  const inAssistant = !!document.activeElement?.closest?.("#assistant-panel, #home-describe");
  if (mod && !e.altKey && low === "k") { e.preventDefault(); if (!dialogOpen) openPalette(); return; }
  if (dialogOpen) { if (key === "Escape" && !$("#modal").classList.contains("hidden")) closeModal(); return; }
  if (mod && !e.altKey && low === "i") { e.preventDefault(); if (!assistantOn()) return; const A = assistantApi(); if (A?.open) A.open({focus: EDGE.focus()}); else EDGE.companion.open("assistant"); return; }
  if (mod && !e.altKey && low === "s") { e.preventDefault(); if (!S.noDoc) save(e.shiftKey); return; }
  if (mod && !e.altKey && low === "o") { e.preventDefault(); openDialog(); return; }
  if (mod && key === "Enter" && !inAssistant) {
    e.preventDefault();
    if (S.noDoc) return;
    if (e.shiftKey) return dryRun();
    if (S.proposal) return EDGE.proposal.apply();
    return tryNow(S.ws === "build" && S.view === "screen" && S.routine ? "screen" : "all");
  }
  if (mod && !typing && (low === "z" || low === "y")) { e.preventDefault(); if (low === "y" || e.shiftKey) redo(); else undo(); return; }
  const digit = /^Digit([1-5])$/.exec(e.code || "");
  if (digit && ((e.altKey && !mod) || (IS_MAC && e.ctrlKey && !e.metaKey && !e.altKey))) {
    e.preventDefault(); if (!S.noDoc) EDGE.go(["build", "measures", "test", "run", "data"][+digit[1] - 1]); return;
  }
  if (key === "F6") { e.preventDefault(); cycleRegion(e.shiftKey ? -1 : 1); return; }
  if (key === "F1") {
    e.preventDefault();
    const c = S.sel?.kind === "component" ? findComp(S.sel.routine, S.sel.id) : null;
    if (c && document.activeElement?.closest?.("#inspector, #props")) openHelp("reference/components", c.type); else openHelp();
    return;
  }
  if (key === "Escape") {
    if (document.activeElement?.closest?.("#proposal-bar") && S.proposal) { EDGE.proposal.discard(); return; }
    if (typing || inAssistant) return;
    if (T.tut && !T.min && document.activeElement?.closest?.("#coach")) { T.min = true; renderCoach(false); return; }
    if (goUpOneLevel()) e.preventDefault();
    return;
  }
  if (typing || mod && !["[", "]", "d"].includes(low) || e.altKey) return;
  if (S.noDoc) { if (key === "?") { e.preventDefault(); EDGE.companion.toggle("help"); if (EDGE.companion.isOpen("help")) renderHelpPanel(); } return; }
  if (key === "?") { e.preventDefault(); if (EDGE.companion.isOpen("help")) EDGE.companion.close(); else openHelp(); return; }
  if (S.ws !== "build") return;
  if (mod && (key === "[" || key === "]")) {
    e.preventDefault();
    if (typeof stepRow === "function") return stepRow(key === "]" ? 1 : -1);
    S.rowIndex = Math.max(0, (S.rowIndex || 0) + (key === "]" ? 1 : -1)); renderAll(); return;
  }
  if (mod && low === "d") { e.preventDefault(); duplicateSelection(); return; }
  if (mod) return;
  if (key === "[" || key === "]") { e.preventDefault(); stepScreen(key === "]" ? 1 : -1); return; }
  if (key === "/" && S.view === "screen") { e.preventDefault(); if (typeof quickAdd === "function") quickAdd(); else openPalette("", {only: "add"}); return; }
  if (key === "F2") { e.preventDefault(); renameSelection(); return; }
  if ((key === "Delete" || (key === "Backspace" && S.sel?.kind === "component")) && S.sel) { e.preventDefault(); deleteSelection(); }
}

/* ================================================================== wiring */
function wire() {
  // app bar
  $("#logo").addEventListener("click", (e) => { e.preventDefault(); EDGE.go("home"); });
  $("#docname").onclick = () => experimentMenu();
  $("#btn-save").onclick = () => (S.proposal ? toast("Apply or discard the assistant's changes first") : save());
  $("#btn-undo").onclick = undo; $("#btn-redo").onclick = redo;
  $("#btn-try").onclick = () => tryNow(S.ws === "build" && S.view === "screen" && S.routine ? "screen" : "all");
  $("#btn-try-menu").onclick = () => tryMenu();
  $("#assistant-toggle").onclick = () => { const A = assistantApi(); if (EDGE.companion.isOpen("assistant")) EDGE.companion.close(); else if (A?.open) A.open({focus: EDGE.focus()}); else EDGE.companion.open("assistant"); };
  $("#btn-help").onclick = () => { if (EDGE.companion.isOpen("help")) EDGE.companion.close(); else openHelp(); };
  $("#btn-more").onclick = () => moreMenu();
  $("#appbar-open").onclick = () => openDialog();
  $("#appbar-import").onclick = () => chooseImportFiles();
  // the Experiment menu (static markup in index.html, so its ids exist for tutorials and tests)
  $("#btn-new").onclick = () => EDGE.go("home");
  $("#btn-open").onclick = () => openDialog();
  $("#btn-import").onclick = () => chooseImportFiles();
  $("#menu-save").onclick = () => save();
  $("#menu-save-copy").onclick = () => save(true);
  $("#btn-versions").onclick = () => versionsDialog();
  $("#btn-bundle").onclick = () => {
    if (!S.path || S.noDoc) return toast("Save the experiment first: the shared file is made from the saved version.");
    if (S.dirty) toast("Sharing the saved version (you have unsaved changes).");
    location.href = `/api/bundle?path=${encodeURIComponent(S.path)}`;
  };
  $("#menu-settings").onclick = () => openExperimentSettings();
  $("#menu-yaml").onclick = () => EDGE.setView("source");
  $("#menu-copy-path").onclick = async () => {
    if (!S.path) return toast("This experiment isn't saved yet, so it has no file path.");
    try { await navigator.clipboard.writeText(S.path); toast("Copied " + S.path); } catch { toast(S.path, 8000); }
  };
  $("#menu-home").onclick = () => closeExperiment();
  // Build toolbar, sidebar and status bar
  ui.wireSeg($("#view-switch"), S.view === "diagram" ? "story" : S.view, (v) => EDGE.setView(v));
  ui.wireSeg($("#sidebar-tabs"), S.side || "add", (v) => showSide(v));
  ui.wireSeg($("#btn-mode"), S.mode, (v) => setMode(v));
  $("#btn-settings").onclick = () => openExperimentSettings();
  $("#btn-add-screen").onclick = () => { if (typeof newRoutine === "function") newRoutine({at: "end"}); };
  $("#btn-try-screen").onclick = () => tryNow(S.routine ? "screen" : "all");
  $("#preview-big").onclick = () => { if (typeof toggleBigPreview === "function") toggleBigPreview(); };
  $("#btn-validate").onclick = async () => { if (_problems) return closeProblems(); S.strict = S.strict || false; openProblems(); validate(); };
  $("#sb-palette").replaceChildren(h("kbd", {class: "kbd"}, MOD), h("kbd", {class: "kbd"}, "K"), h("span", {}, "Search"));
  $("#sb-palette").setAttribute("aria-label", `Search everything (${MOD}+K)`);
  $("#sb-palette").hidden = false;
  $("#sb-palette").onclick = () => openPalette();
  $("#sb-tutorial").onclick = () => { T.min = false; renderCoach(true); };
  $("#sb-recording").onclick = () => openRunningSession();
  // Test page
  $("#btn-dryrun").onclick = () => dryRun();
  $("#btn-check-again").onclick = async () => { await validate(); ui.announce(S._lastProblemText || ""); };
  $("#btn-try-test").onclick = () => tryNow("all");
  $("#btn-try-one").onclick = (e) => {
    const order = routineInFlowOrder();
    ui.menu(e.currentTarget, order.length ? order.map((rid) => ({label: `“${rid}” (5 trials)`, icon: "screen", run: () => { S.routine = rid; tryNow("screen"); }}))
      : [{label: "No screens yet", disabled: true}]);
  };
  // companion column
  document.querySelectorAll("#companion-tabs [data-ctab]").forEach((b) => b.onclick = () => EDGE.companion.open(b.dataset.ctab));
  $("#companion-tabs").addEventListener("keydown", (e) => {
    const tabs = [...document.querySelectorAll("#companion-tabs [data-ctab]")].filter((b) => !b.hidden);
    const i = tabs.indexOf(document.activeElement);
    if (i < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const j = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[j].focus(); EDGE.companion.open(tabs[j].dataset.ctab);
  });
  $("#companion-close").onclick = () => EDGE.companion.close();
  $("#proposal-bar").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); EDGE.proposal.discard(); } });
  $("#preview-play").onclick = () => { if (typeof playPreview === "function") playPreview(); };
  applyMode();
  $("#btn-scan").onclick = () => { if (typeof scanHardware === "function") scanHardware(); };
  $("#btn-add-device").onclick = () => (typeof openAddDevice === "function" ? openAddDevice() : deviceMenu());
  $("#palette-filter").oninput = () => { if (typeof renderPalette === "function") renderPalette(); };
  $("#btn-apply-yaml").onclick = async () => {
    try { const {experiment} = await api("/api/from_yaml", {yaml: $("#yaml").value});
      S.exp = normalize(experiment); fixSelection(); commit("Apply YAML"); toast("YAML applied"); }
    catch (e) { toast("YAML error: " + e.message, {tone: "danger", ms: 8000}); }
  };
  window.addEventListener("hashchange", () => routeFromHash());
  $("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };
  $("#modal").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); closeModal(); } });
  $("#preview-t").oninput = (e) => { S.previewT = +e.target.value; if (typeof renderPreview === "function") renderPreview(); if (typeof renderTimeline === "function") renderTimeline(); };
  const tl = $("#timeline");
  tl.ondragover = (e) => e.preventDefault();
  tl.ondrop = (e) => { const type = e.dataTransfer.getData("edge/component"); if (!type) return; e.preventDefault();
    const row = e.target.closest(".tl-row"); addComponent(type, row ? +row.dataset.idx + 1 : undefined); };
  document.addEventListener("keydown", onKey);
  window.addEventListener("beforeunload", (e) => { if (S.dirty && !S.noDoc) { e.preventDefault(); e.returnValue = ""; } });
  EDGE.on("run", () => { renderShell(); watchRun(); if (S.ws === "test") renderReadiness(); });
  EDGE.on("doc:loaded", () => { if (S.ws === "data") { D.sel = null; renderData(); } });
  registerActions();
}

window.addEventListener("DOMContentLoaded", () => boot().catch((e) => {
  console.error(e);
  document.body.replaceChildren(h("div", {class: "boot-fail"}, h("h1", {}, "The builder couldn't start"), h("p", {}, e.message),
    h("p", {}, "Close this tab and start EDGE again. If it keeps happening, run “edge doctor” in a terminal.")));
}));

/* ================================================================== the EDGE namespace (§7.5.1) */
/* Experiment names become folders: "Practice task" -> practice_task/practice_task.yaml, unique in this folder. */
async function _uniqueExperimentPath(name) {
  const base = ui.slug(name) || "experiment";
  let files = new Set();
  try { files = new Set((await refreshFiles()).map((f) => f.path)); } catch { /* offline: take the name */ }
  let slug = base, n = 2;
  while (files.has(`${slug}/${slug}.yaml`)) slug = `${base}_${n++}`;
  return {slug, path: `${slug}/${slug}.yaml`, files};
}
const hasNewViews = () => typeof renderListEditor === "function";
/* The canvas changed width (companion opened or closed): let the stage fit again. */
function refitStage() { if (S.ws === "build" && S.view === "screen" && typeof renderPreview === "function") setTimeout(() => { try { renderPreview(); } catch { /* P4a redraws on its own */ } }, 0); }

const EDGE = (() => {
  const handlers = {};
  const paletteItems = [];
  let paletteFallback = null;

  const fmt = {
    seconds(s) {
      if (s === null || s === undefined || isNaN(s)) return "";
      if (s < 1) return "less than a second";
      const r = Math.round(s);
      if (r === 1) return "about 1 second";
      if (r < 60) return `about ${r} s`;
      if (r < 600) { const m = Math.floor(r / 60), sec = r % 60; return `about ${m} min${sec ? ` ${sec} s` : ""}`; }
      if (r < 3600) return `about ${Math.round(r / 60)} min`;
      const hh = Math.floor(r / 3600), mm = Math.round((r % 3600) / 60);
      return `about ${hh} h${mm ? ` ${mm} min` : ""}`;
    },
    estimate(est) {
      if (!est) return "";
      const t = est.trials, time = fmt.seconds(est.seconds);
      return t ? `${t} trial${t === 1 ? "" : "s"} · ${time}` : time;
    },
  };

  const companion = {
    open(tab = "assistant", {persist = true, focus = true} = {}) {
      if (!["assistant", "help", "props"].includes(tab)) tab = "assistant";
      if (tab === "assistant" && !assistantOn()) tab = "help";
      const comp = $("#companion");
      const wasOpen = !comp.hidden;
      comp.hidden = false;
      S.companion = tab;
      layoutColumns();
      if (tab === "props" && !document.body.classList.contains("shared-right")) tab = S.companion = "help";
      for (const b of document.querySelectorAll("#companion-tabs [data-ctab]")) {
        const on = b.dataset.ctab === tab;
        b.setAttribute("aria-selected", on ? "true" : "false");
        b.tabIndex = on ? 0 : -1;
      }
      $("#assistant-panel").hidden = tab !== "assistant";
      $("#help-panel").hidden = tab !== "help";
      comp.classList.toggle("tab-props", tab === "props");
      $("#assistant-toggle").setAttribute("aria-expanded", tab === "assistant" ? "true" : "false");
      $("#btn-help").setAttribute("aria-pressed", tab === "help" ? "true" : "false");
      if (tab === "help" && !$("#help-panel .help-pane")) renderHelpPanel();
      if (persist && tab !== "props") saveLayout({companion: tab});
      if (!wasOpen) refitStage();
      E.emit("companion", {open: true, tab, focus});
      if (T.tut) setTimeout(updateCoach, 0);
    },
    close({persist = true} = {}) {
      const comp = $("#companion");
      if (comp.hidden) return;
      comp.hidden = true;
      $("#assistant-toggle").setAttribute("aria-expanded", "false");
      $("#btn-help").setAttribute("aria-pressed", "false");
      S.companion = null;
      layoutColumns();
      refitStage();
      if (persist) saveLayout({companion: null});
      E.emit("companion", {open: false, tab: null});
      if (comp.contains(document.activeElement) || document.activeElement === document.body) $("#btn-help")?.focus();
      if (T.tut) setTimeout(updateCoach, 0);
    },
    toggle(tab = "assistant") { if (companion.isOpen(tab)) companion.close(); else companion.open(tab); },
    isOpen(tab) { return !$("#companion").hidden && (!tab || S.companion === tab); },
    current() { return $("#companion").hidden ? null : S.companion; },
  };

  const E = {
    version: 1,
    on(name, fn) { (handlers[name] ||= new Set()).add(fn); return () => handlers[name].delete(fn); },
    emit(name, detail = {}) {
      for (const fn of [...(handlers[name] || [])]) {
        try { fn(detail); } catch (e) { console.error(`EDGE: a "${name}" listener failed`, e); }
      }
    },
    /* navigation */
    go(ws, opts = {}) {
      if (!WORKSPACES.includes(ws)) return;
      ui.closeMenus(); closeProblems();
      if (ws !== "home" && S.noDoc) { toast("Open or create an experiment first."); if (S.ws !== "home") E.go("home"); return; }
      const changed = S.ws !== ws;
      S.ws = ws;
      S.tab = ws === "data" ? "data" : ws === "build" && S.view === "source" ? "source"
        : ws === "test" && S.lastResults && !S.lastResults.failed && !S.lastResults.error ? "results" : null;
      if (ws !== "build") $("#sidebar")?.classList.remove("open");
      if (S.booted) syncHash(!!opts.replace);
      if (changed) E.emit("workspace", {ws});
      if (opts.render === false) return;
      renderAll();
      if (ws === "data") renderData();
      if (ws === "home") refreshFiles().then(() => { if (S.ws === "home") renderHome(); });
      if (changed) { const m = $(`#body > main.ws[data-ws="${ws}"]`); if (m) m.scrollTop = 0; }
    },
    ws() { return S.ws; },
    setView(view, opts = {}) {
      if (!VIEWS.includes(view)) return;
      if (S.noDoc) return;
      if (view === "source" && S.mode !== "expert") view = "story";
      if (view === "list" || view === "diagram") {
        if (opts.path) S.sel = {kind: view === "list" ? "loop" : "machine", path: opts.path};
        if (!hasNewViews()) view = "story";      // until P4a's trial-list and diagram views: the list's properties show in the inspector
      } else if (S.sel && ["machine", "state"].includes(S.sel.kind) && view !== "story") S.sel = null;
      if (opts.routine && S.exp.routines[opts.routine]) S.routine = opts.routine;
      if (view === "screen") {
        if (!S.routine) S.routine = routineInFlowOrder()[0] || Object.keys(S.exp.routines)[0] || null;
        if (S.routine && !(S.sel && S.sel.routine === S.routine)) S.sel = {kind: "routine", routine: S.routine};
      }
      const changed = S.view !== view;
      S.view = view;
      if (view === "source") S.tab = "source"; else if (S.tab === "source") S.tab = null;
      if (S.path && (view === "story" || view === "screen")) { const k = "view." + S.path; E.prefs.set(k, {...(E.prefs.get(k, {}) || {}), view}); }
      if (S.ws !== "build") E.go("build", {render: false});
      if (changed) E.emit("view", {view});
      renderAll();
    },
    select(sel, {reveal = true, pulse = false} = {}) {
      if (sel?.kind === "settings") { openExperimentSettings(); return; }
      S.sel = sel || null;
      if (sel?.routine && S.exp.routines[sel.routine]) S.routine = sel.routine;
      if (reveal) {
        if (S.ws !== "build") E.go("build", {render: false});
        if (sel?.kind === "component" || sel?.kind === "routine") { if (sel.kind === "component" || S.view === "source") S.view = "screen"; }
        else if (sel && ["loop", "branch", "machine", "state"].includes(sel.kind) && !["list", "diagram"].includes(S.view)) S.view = "story";
        else if (sel?.kind === "device") revealSide("devices");
        if (document.body.classList.contains("shared-right") && sel && companion.current() === "help") companion.open("props", {persist: false, focus: false});
      }
      renderAll();
      if (pulse) E.pulse($("#inspector"));
    },
    reveal(change) {
      if (!change || !S.exp) return;
      const k = change.kind, id = change.id;
      if (k === "component") { const rid = change.routine; if (findComp(rid, id)) E.select({kind: "component", routine: rid, id}, {pulse: true}); }
      else if (k === "routine") { const rid = change.routine || id; if (S.exp.routines[rid]) E.select({kind: "routine", routine: rid}, {pulse: true}); }
      else if (k === "loop") { const path = findFlowPath((n) => n.loop === id); if (path) E.select({kind: "loop", path}, {pulse: true}); }
      else if (k === "statemachine" || k === "workflow" || k === "machine") { const path = findFlowPath((n) => n.statemachine === id); if (path) E.select({kind: "machine", path}, {pulse: true}); }
      else if (k === "device") { const i = S.exp.devices.findIndex((d) => d.id === id); if (i >= 0) E.select({kind: "device", index: i}, {pulse: true}); }
      else if (k === "settings") openExperimentSettings();
      else if (k === "measures" || k === "measure") E.go("measures");
    },
    pulse(el) {
      if (!el) return;
      el.classList.remove("edge-pulse"); void el.offsetWidth; el.classList.add("edge-pulse");
      setTimeout(() => el.classList.remove("edge-pulse"), 900);
    },
    /* document */
    doc() { return S.exp; },
    path() { return S.noDoc ? null : (S.path || null); },
    snapshot() { return S._snapshot; },
    historyIndex() { return S.history.length; },
    replaceDoc(doc, label) {
      if (S.proposal) endProposal();
      S.exp = normalize(clone(doc)); fixSelection(); commit(label || "Replace the experiment");
      if (label) S.saveLabel = label;
    },
    undoIf(index) { if (S.proposal || S.history.length !== index) return false; undo(); return true; },
    async save() { await save(); return !S.dirty && !!S.path; },
    async ensurePath({suggest} = {}) {
      if (S.path && !S.noDoc) return S.path;
      const slug = await askExperimentName({title: "Name this experiment", ok: "Use this name",
        suggest: suggest || (["experiment", "my_experiment", "untitled"].includes(S.exp?.name) ? "" : S.exp?.name) || ""});
      if (!slug) return null;
      S.path = `${slug}/${slug}.yaml`; S.fingerprint = null; S.noDoc = false;
      if (!S.exp.name || ["experiment", "my_experiment", "untitled"].includes(S.exp.name)) S.exp.name = slug;
      renderDocName(); setDirty(true);
      return S.path;
    },
    async newExperiment({name, template = "blank", doc = null, save: doSave = true, go = "build"} = {}) {
      const {slug, path} = await _uniqueExperimentPath(name || doc?.name || template);
      const d = normalize(clone(doc || await api(`/api/template?name=${encodeURIComponent(template)}`)));
      d.name = slug;
      if (S.proposal) endProposal();
      if (doSave) {
        const r = await api(`/api/experiment?path=${encodeURIComponent(path)}&fingerprint=&label=${encodeURIComponent("Created")}`, d);
        loadDoc(d, path, r.fingerprint, {silent: true});
        S.savedAt = Date.now();
        E.prefs.set("last", path); rememberRecent(path);
        E.emit("doc:saved", {path});
        refreshFiles();
      } else {
        loadDoc(d, path, null, {silent: true});
        setDirty(true);
      }
      S.fresh = path;
      if (go) { S.view = "story"; E.go(go); }
      return path;
    },
    isFresh() { return !!S.fresh && S.fresh === S.path; },
    focus() {
      const s = S.sel;
      if (!s) return null;
      if (s.kind === "component") return {kind: "component", routine: s.routine, id: s.id};
      if (s.kind === "routine") return {kind: "routine", routine: s.routine};
      if (s.kind === "loop") { const n = selNode(); return n?.loop ? {kind: "loop", id: n.loop} : null; }
      if (s.kind === "device") { const d = S.exp.devices[s.index]; return d ? {kind: "device", id: d.id} : null; }
      if (s.kind === "settings") return {kind: "settings"};
      return null;
    },
    issues() { return S.issues; },
    fmt,
    /* the assistant's preview */
    proposal: {
      start({doc, marks = {}, label = "Assistant: changes", summary = "", conflict = false, jobId = null} = {}) {
        if (S.proposal) S.exp = JSON.parse(S._snapshot);      // a new preview replaces the old one; the base stays
        S.exp = normalize(clone(doc)); S.rev = (S.rev || 0) + 1;
        S.proposal = {marks, label, summary, conflict, jobId, edited: false};
        fixSelection();
        document.body.classList.add("proposal");
        clearAlert("assistant-external");
        renderAll();
        validate();
        E.emit("proposal", {active: true});
      },
      apply() {
        if (!S.proposal) return S.history.length;
        const label = S.proposal.label;
        endProposal(false);
        commit(label);                                       // pushes the base snapshot: ONE undo step
        S.saveLabel = label;
        const idx = S.history.length;
        E.emit("proposal", {active: false, applied: true});
        if (E.isFresh()) save(false, {label, toast: `Saved as ${S.path}`});
        return idx;
      },
      discard() {
        if (!S.proposal) return;
        S.exp = JSON.parse(S._snapshot); S.rev = (S.rev || 0) + 1;
        endProposal(false);
        fixSelection(); renderAll(); validate();
        E.emit("proposal", {active: false, applied: false});
      },
      active() { return !!S.proposal; },
    },
    companion,
    /* command palette */
    palette: {
      register(item) {
        if (!item || !item.id) return;
        const i = paletteItems.findIndex((x) => x.id === item.id);
        if (i >= 0) paletteItems[i] = item; else paletteItems.push(item);
      },
      setFallback(fn) { paletteFallback = typeof fn === "function" ? fn : null; },
      items() { return paletteItems.slice(); },
      fallback() { return paletteFallback; },
      open(text = "") { openPalette(text); },
    },
    prefs: {
      get(key, dflt) {
        let raw = null;
        try { raw = localStorage.getItem("edge." + key); } catch { return dflt; }
        if (raw === null) return dflt;
        if (/^[[{"]|^(true|false|null)$|^-?\d+(\.\d+)?$/.test(raw)) { try { return JSON.parse(raw); } catch { /* plain text */ } }
        return raw;
      },
      set(key, value) {
        try {
          if (value === undefined || value === null) localStorage.removeItem("edge." + key);
          else localStorage.setItem("edge." + key, typeof value === "string" ? value : JSON.stringify(value));
        } catch { /* private mode or quota */ }
        E.emit("prefs", {key, value});
      },
    },
    toast: (msg, opts = {}) => ui.toast(msg, opts),
    announce: (text, assertive = false) => ui.announce(text, {assertive}),
  };
  return E;
})();
window.EDGE = EDGE;
