/* build.js: the Build workspace canvas (SPEC §2.6 W3–W7, §7.2 P4a, §7.5.4). Owner: P4a.
 * Owns the Build sidebar (Add palette renderPalette, Files tab renderFiles, Devices tab renderDevices, the Add device
 * dialog openAddDevice/deviceMenu, the inline hardware scan scanHardware), the rail and its flyouts, the toolbar parts
 * of the canvas (#crumbs, #est, #story-density, #btn-view-done), the storyboard as the flow editor (renderStoryboard:
 * cards, frames, insert targets, card and insert menus, drag and drop moveFlowNode, keyboard moves, List density, the
 * "not shown" row, the assistant's preview marks), the Screen view's flow strip, timeline and preview drawing
 * (renderTimeline, renderPreview, drawScreen, drawThumbnail, playPreview, the trial-row stepper, "In words":
 * describeRoutine), the Trial list view (renderListEditor), the workflow Diagram view (renderDiagram), quick add
 * (quickAdd), adding things (addComponent, newRoutine, addDevice), TYPE_ICON / DEVICE_ICON, and renderBuild(),
 * which renderAll() calls while the Build workspace is open. The stage editor itself lives in stage.js.
 */
"use strict";

/* ================================================================== icons and categories (SPEC §3.8) */
const TYPE_ICON = {
  text: "text", image: "image", shape: "shape", fixation: "fixation", sound: "sound", html: "page", survey: "survey",
  keyboard: "keyboard", device_response: "buttonbox", mouse: "mouse", slider: "rating",
  gaze_roi: "eye", gaze_follow: "gazefollow", calibrate: "calibrate",
  marker: "marker", variable: "variable", code: "code", wait: "pause_blank",
};
const DEVICE_ICON = {
  tobii: "eyetracker", gazepoint: "eyetracker", sim_eyetracker: "eyetracker", mouse_gaze: "eyetracker",
  gtec: "eeg", lsl_inlet: "eeg", sim_eeg: "eeg", mindware: "eeg", sim_physio: "eeg",
  trigger_adapter: "trigger", parallel_port: "trigger", ttl_serial: "trigger", ttl_loopback: "trigger", labjack: "trigger",
  serial_inputs: "buttonbox", parallel_inputs: "buttonbox", sim_inputs: "buttonbox", voice_key: "buttonbox",
  lsl_markers: "marker", udp_messages: "marker",
};
const BUILD_CAT = {stimulus: "show", response: "respond", eyetracking: "eye", hardware: "hw", logic: "logic"};
const BUILD_GROUPS = [["Show", "stimulus"], ["Respond", "response"], ["Eye tracking", "eyetracking"], ["Hardware", "hardware"], ["Logic", "logic"]];
const ORDER_WORDS = {random: "shuffled", sequential: "as listed", fullrandom: "shuffled across repeats",
  latin_square: "Latin square", counterbalance: "counterbalanced"};

function catKey(type) { return BUILD_CAT[S.schema?.components?.[type]?.category] || "logic"; }
function typeIcon(type) { return TYPE_ICON[type] || "info"; }
function deviceIcon(d) {
  if (d && d.type === "lsl_inlet" && /gaze|eye/i.test(String(d.options?.stream_type || ""))) return "eyetracker";
  return DEVICE_ICON[d?.type] || "device";
}

/* ================================================================== module state */
const BUILD = {
  listPath: null,        // the trial list shown in the Trial list view
  diagramPath: null,     // the workflow shown in the Diagram view
  returnView: "story",   // where [Done] goes back to
  focusKey: null,        // data-fkey to focus after the next render
  flyout: null,          // open rail flyout: add | files | devices
  pinned: false,         // the sidebar stays docked below 1280 px
  zoom: null,            // diagram zoom (null = fit the width)
  cell: {r: 0, c: 0},    // active cell of the trial-list grid
  thumbs: new Map(),     // thumbnail cache (key -> canvas)
  imgGen: 0,             // bumped when a picture finishes loading
  rows: {},              // trial-list rows by spec (file lists come from /api/conditions)
  lastClick: {key: null, t: 0},
  assets: {path: null, at: 0, lists: null},
  renderQueued: false,
  sayOpen: false,        // "In words" expanded
};

/* ================================================================== small helpers */
const buildAssistant = () => (window.Assistant || (typeof Assistant !== "undefined" ? Assistant : null));
const isRoutineNode = (n) => typeof n === "string" || (n && typeof n === "object" && n.routine !== undefined);
const typingIn = (el) => !!el && (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable);
const plural = (n, word, many) => `${n} ${n === 1 ? word : (many || word + "s")}`;
function fmtS(v) { if (typeof v !== "number" || isNaN(v)) return String(v); return `${Math.round(v * 1000) / 1000} s`; }
function samePath(a, b) { return !!a && !!b && a.length === b.length && a.every((x, i) => x === b[i]); }
function pathStartsWith(p, prefix) { return p.length >= prefix.length && prefix.every((x, i) => p[i] === x); }
function nodeAt(path) { try { return getNode(path); } catch { return undefined; } }
function nodeName(n) {
  if (isRoutineNode(n)) return routineOfNode(n);
  if (!n || typeof n !== "object") return "?";
  if (n.loop !== undefined) return n.loop;
  if (n.statemachine !== undefined) return n.statemachine;
  if (n.if !== undefined) return "if / otherwise";
  return "?";
}
function nodeWords(n) {
  if (isRoutineNode(n)) return `screen “${routineOfNode(n)}”`;
  if (n?.loop !== undefined) return `trial list “${n.loop}”`;
  if (n?.statemachine !== undefined) return `workflow “${n.statemachine}”`;
  if (n?.if !== undefined) return "if / otherwise";
  return "item";
}
/* Edits are paused while the assistant's changes are previewed (SPEC W16). */
function bEditable() {
  if (S.proposal) { toast("Apply or discard the assistant's changes first"); return false; }
  return true;
}
/* Deletions happen at once, with an undo toast instead of a confirmation (SPEC §2.9). */
function undoToast(msg) {
  const idx = EDGE.historyIndex();
  ui.toast(msg, {action: {label: "Undo", run: () => {
    if (!EDGE.undoIf(idx)) toast("Other changes came after this one: use Undo in the toolbar");
  }}});
}
/* Re-render without losing keyboard focus: the element with the same data-fkey gets it back. */
function keepFocus(root, fn) {
  const a = document.activeElement;
  const had = a && root.contains(a) ? a.dataset?.fkey : null;
  fn();
  const find = (k) => (k ? root.querySelector(`[data-fkey="${CSS.escape(k)}"]`) : null);
  let t = find(BUILD.focusKey);
  if (t) BUILD.focusKey = null; else t = find(had);
  if (!t || t === document.activeElement) return;
  t.focus({preventScroll: true});
  t.scrollIntoView?.({block: "nearest", inline: "nearest"});
}
function emptyState(ic, title, text, actions = []) {
  return h("div", {class: "empty"}, h("div", {class: "ic-wrap"}, icon(ic)),
    title ? h("h3", {class: "t-title-s"}, title) : null, text ? h("p", {}, text) : null,
    actions.filter(Boolean).length ? h("div", {class: "actions"}, actions.filter(Boolean)) : null);
}
function btn(label, onclick, {cls = "btn sm", ic: iconName = null, title = null, attrs = {}} = {}) {
  return h("button", {type: "button", class: cls, title, onclick, ...attrs}, iconName ? icon(iconName) : null, label);
}
function iconBtn(iconName, label, onclick, cls = "btn ghost icon sm", attrs = {}) {
  return h("button", {type: "button", class: cls, "aria-label": label, title: label, onclick, ...attrs}, icon(iconName));
}
/* Every list of the flow (top level, trial lists, branches, workflow phases) with its path. */
function forEachFlowList(fn) {
  fn(S.exp.flow, []);
  walkFlow((n, p) => {
    if (!n || typeof n !== "object") return;
    if (n.loop !== undefined) fn(n.children ||= [], [...p, "children"]);
    if (n.if !== undefined && !isRoutineNode(n)) { fn(n.then ||= [], [...p, "then"]); fn(n.else ||= [], [...p, "else"]); }
    if (n.statemachine !== undefined) for (const [name, st] of Object.entries(n.states || {})) fn(st.run ||= [], [...p, "states", name, "run"]);
  });
}
function pathOfList(arr) { let out = null; forEachFlowList((l, p) => { if (!out && l === arr) out = p; }); return out; }
function scheduleBuildRender() {
  if (BUILD.renderQueued) return;
  BUILD.renderQueued = true;
  requestAnimationFrame(() => { BUILD.renderQueued = false; if (S.exp && S.ws === "build") renderBuild(); });
}
/* A screen's trial lists, innermost last. */
function loopsAround(rid, doc = S.exp) {
  let best = null;
  const walk = (nodes, stack) => (nodes || []).forEach((n) => {
    if (isRoutineNode(n)) { if (routineOfNode(n) === rid && (!best || stack.length > best.length)) best = stack.slice(); return; }
    if (!n || typeof n !== "object") return;
    if (n.loop !== undefined) walk(n.children, [...stack, n]);
    if (n.if !== undefined) { walk(n.then, stack); walk(n.else, stack); }
    if (n.statemachine !== undefined) for (const st of Object.values(n.states || {})) walk(st.run, stack);
  });
  walk(doc.flow, []);
  return best || [];
}

/* ================================================================== plain words for formulas (SPEC W4 "In words") */
const FIELD_WORDS = {n: "trial number", accuracy: "accuracy", mean_rt: "mean response time", rt: "response time", keys: "key", corr: "correct",
  total: "number of trials", state: "phase", visit: "visit", clicked: "clicked item", response: "answer", value: "value"};
const OP_WORDS = {">=": "is at least", "<=": "is at most", ">": "is more than", "<": "is less than", "==": "is", "!=": "is not"};
function responseIds() {
  const out = new Set();
  for (const r of Object.values(S.exp?.routines || {})) for (const c of r.components || [])
    if (["keyboard", "mouse", "slider", "device_response", "survey", "html", "gaze_roi"].includes(c.type)) out.add(c.id);
  return out;
}
function termWords(t, resp) {
  t = t.trim();
  let m;
  if (/^-?\d+(\.\d+)?$/.test(t)) return t;
  if ((m = t.match(/^'([^']*)'$|^"([^"]*)"$/))) return `“${m[1] ?? m[2]}”`;   // a quoted text, not 'a' if c else 'b'
  if (t === "True") return "true";
  if (t === "False") return "false";
  if (t === "None") return "nothing";
  if ((m = t.match(/^([A-Za-z_]\w*)\.([A-Za-z_]\w*)$/))) {
    const [, a, b] = m;
    if (b === "rt" && resp.has(a)) return "the response time";
    if (b === "keys" && resp.has(a)) return "the key pressed";
    if (resp.has(a) && !FIELD_WORDS[b] && !["corr", "x", "y", "clicked", "button", "rating", "submitted"].includes(b)) return `the answer to “${b}”`;   // a survey question
    return `${a} ${FIELD_WORDS[b] || b}`;
  }
  if ((m = t.match(/^[A-Za-z_]\w*$/))) return `“${t}”`;
  return null;
}
function clauseWords(c, resp) {
  c = c.trim().replace(/^\((.*)\)$/, "$1").trim();
  let m;
  if ((m = c.match(/^not\s+([A-Za-z_]\w*)\.last$/))) return `it isn't the last round of “${m[1]}”`;
  if ((m = c.match(/^([A-Za-z_]\w*)\.last$/))) return `it is the last round of “${m[1]}”`;
  // accuracy as a percentage: "practice accuracy is at least 80 %"
  if ((m = c.match(/^([A-Za-z_]\w*)\.accuracy\s*(>=|<=|>|<)\s*(0?\.\d+|1(?:\.0+)?)$/))) return `“${m[1]}” accuracy ${OP_WORDS[m[2]]} ${Math.round(+m[3] * 100)} %`;
  if ((m = c.match(/^not\s+(.+)$/))) {
    const inner = c.slice(4).trim();
    if ((m = inner.match(/^([A-Za-z_]\w*)\.corr$/))) return resp.has(m[1]) ? "the response was wrong" : `${m[1]} was wrong`;
    const t = termWords(inner, resp); return t ? `${t} is not true` : null;
  }
  if ((m = c.match(/^([A-Za-z_]\w*)\.corr(?:\s*==\s*(1|True))?$/))) return resp.has(m[1]) ? "the response was correct" : `${m[1]} was correct`;
  if ((m = c.match(/^([A-Za-z_]\w*)\.corr\s*==\s*(0|False)$/))) return resp.has(m[1]) ? "the response was wrong" : `${m[1]} was wrong`;
  if ((m = c.match(/^([A-Za-z_]\w*)\.keys\s+is\s+None$/))) return "there was no response";
  if ((m = c.match(/^(.+?)\s*(>=|<=|==|!=|>|<)\s*(.+)$/))) {
    const a = termWords(m[1], resp), b = termWords(m[3], resp);
    if (a && b) return `${a} ${OP_WORDS[m[2]]} ${b}`;
    return null;
  }
  if (c === "True") return "always";
  if (c === "False") return "never";
  const t = termWords(c, resp);
  return t ? `${t} is true` : null;
}
/* Split "A if C else B" at the top level (outside quotes and brackets) → [A, C, B] or null. */
function splitTernary(s) {
  let depth = 0, q = null, ifAt = -1;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (q) { if (ch === q) q = null; continue; }
    if (ch === "'" || ch === '"') { q = ch; continue; }
    if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (!depth && ch === " ") {
      if (ifAt < 0 && s.startsWith(" if ", i)) ifAt = i;
      else if (ifAt >= 0 && s.startsWith(" else ", i)) return [s.slice(0, ifAt), s.slice(ifAt + 4, i), s.slice(i + 6)];
    }
  }
  return null;
}
/* "(a if c else b)" → "a if c else b", only when the outer brackets belong together */
function unwrapParens(t) {
  t = t.trim();
  while (t.startsWith("(") && t.endsWith(")")) {
    let depth = 0, q = null, closesAtEnd = true;
    for (let i = 0; i < t.length; i++) {
      const ch = t[i];
      if (q) { if (ch === q) q = null; continue; }
      if (ch === "'" || ch === '"') q = ch;
      else if (ch === "(") depth++;
      else if (ch === ")") { depth--; if (!depth && i < t.length - 1) { closesAtEnd = false; break; } }
    }
    if (!closesAtEnd) break;
    t = t.slice(1, -1).trim();
  }
  return t;
}
/* "$resp.corr == 1" -> "the response was correct"; "$word" -> "the trial list's “word”"; else "a computed value".
   kind "value" (a text, colour or number from a formula): "$'Correct!' if resp.corr else 'Wrong!'" →
   "“Correct!” when the response was correct, otherwise “Wrong!”". */
function exprInWords(v, kind = "condition") {
  if (!isExpr(v)) return v === undefined || v === null ? "" : String(v);
  const s = String(v).slice(1).trim();
  const resp = responseIds();
  let m;
  const tern = splitTernary(s);
  if (tern) {
    const [a, c, b] = tern.map(unwrapParens);
    const va = exprInWords("$" + a, "value"), vc = exprInWords("$" + c, "condition"), vb = exprInWords("$" + b, "value");
    if (vc === "a computed value") return "a computed value";
    return `${va} when ${vc}, otherwise ${vb}`;
  }
  if (kind === "value") { const t = termWords(s, resp); if (t && /^[“\d-]/.test(t)) return t; }
  if ((m = s.match(/^([A-Za-z_]\w*)$/))) return s === "True" ? "always" : s === "False" ? "never" : `the trial list's “${s}”`;
  if ((m = s.match(/^f(['"])(.*)\1$/))) {
    const names = [...new Set([...m[2].matchAll(/\{([^}]*)\}/g)].flatMap((x) => (x[1].match(/[A-Za-z_]\w*/g) || [])
      .filter((w) => !["if", "else", "and", "or", "not", "True", "False", "None", "round", "int", "str", "len"].includes(w))))];
    return names.length ? `a label made from ${names.map((x) => `“${x}”`).join(", ")}` : `the text “${m[2]}”`;
  }
  // a guard like "practice.accuracy is not None and …" only keeps the formula from failing: leave it out of the words
  const parts = s.replace(/^([A-Za-z_][\w.]*) is not None and (?=.*\b\1\b)/, "").split(/\s+(and|or)\s+/);
  const out = [];
  for (let i = 0; i < parts.length; i++) {
    if (i % 2) { out.push(parts[i]); continue; }
    const w = clauseWords(parts[i], resp);
    if (!w) return "a computed value";
    out.push(w);
  }
  return out.join(" ");
}

/* ================================================================== the Build workspace (SPEC §7.5.4) */
function currentBuildView() {
  let v = S.view || "story";
  if (v === "list" && !listPathNow()) v = "story";
  if (v === "diagram" && !diagramPathNow()) v = "story";
  if (v === "source" && isSimple()) v = "story";
  if (!["story", "screen", "list", "diagram", "source"].includes(v)) v = "story";
  return v;
}
function listPathNow() {
  if (BUILD.listPath && nodeAt(BUILD.listPath)?.loop !== undefined) return BUILD.listPath;
  if (S.sel?.kind === "loop" && nodeAt(S.sel.path)?.loop !== undefined) return S.sel.path;
  return null;
}
function diagramPathNow() {
  if (BUILD.diagramPath && nodeAt(BUILD.diagramPath)?.statemachine !== undefined) return BUILD.diagramPath;
  if (S.sel && ["machine", "state"].includes(S.sel.kind) && nodeAt(S.sel.path)?.statemachine !== undefined) return S.sel.path;
  return null;
}
/* Switch Build views through EDGE.setView (P1), which knows every view (story, screen, list, diagram, source). */
function setBuildView(view, opts = {}) { EDGE.setView(view, opts); }

function showBuildView(view) {
  for (const v of ["story", "screen", "list", "diagram", "source"]) { const el = $("#view-" + v); if (el) el.hidden = v !== view; }
  $("#canvas").dataset.view = view;
  $("#ws-build").dataset.view = view;
  const vis = {"btn-settings": view === "story", "btn-add-screen": view === "story" || view === "screen",
    "btn-try-screen": view === "screen", "preview-big": view === "screen", "btn-view-done": view === "list" || view === "diagram",
    "story-density": view === "story"};
  for (const [id, on] of Object.entries(vis)) { const el = $("#" + id); if (el) el.hidden = !on; }
  $("#view-switch").setValue?.(view === "diagram" || view === "list" ? "story" : view);
}

function renderBuild() {
  if (!S.exp || !S.schema) return;
  applyRail();
  renderPalette(); renderDevices();
  if (S.side === "files" && !$("#side-files")?.hidden) renderFilesSoon();
  const view = currentBuildView();
  if (S.view !== view && S.view !== "source") S.view = view;
  showBuildView(view);
  renderBuildToolbar(view);
  renderFlowStrip();
  if (view === "story") renderStoryboard($("#flow"));
  else if (view === "screen") { renderTimeline(); renderPreview(); }
  else if (view === "list") renderListEditor($("#list-editor"));
  else if (view === "diagram") renderDiagram($("#diagram"));
  BUILD.focusKey = null;
  buildFocusFallback(view);
}
/* Keyboard focus never drops to <body> when a view changes or the focused card goes away (open a screen, Esc back,
   Delete, Undo): it goes to the matching place of the new view (§3.7). */
document.addEventListener("pointerdown", () => { BUILD.focusIn = false; }, true);   // a click elsewhere: the mouse decides
document.addEventListener("focusin", (e) => {
  const ws = $("#ws-build");
  BUILD.focusIn = !!ws && ws.contains(e.target);
  if (BUILD.focusIn && e.target.dataset?.fkey) BUILD.lastFkey = e.target.dataset.fkey;
}, true);
function buildFocusFallback(view, later = false) {
  // once more after the late re-renders (validation, a trial list being read), which can replace what got focus
  if (!later) { clearTimeout(BUILD.focusT); BUILD.focusT = setTimeout(() => buildFocusFallback(currentBuildView(), true), 150); }
  const a = document.activeElement;
  if (!BUILD.focusIn || (a && a !== document.body && a.isConnected) || overlayOpen?.()) return;
  const root = $("#ws-build"); if (!root) return;
  const byKey = (k) => (k ? root.querySelector(`[data-fkey="${CSS.escape(k)}"]`) : null);
  let t = null;
  if (view === "story") {
    const k = BUILD.lastFkey || "";
    const m = k.match(/^(card|frame|row):(.*?)(\d+)$/);
    t = byKey(k) || (m && +m[3] > 0 ? byKey(`${m[1]}:${m[2]}${+m[3] - 1}`) : null)
      || (S.routine ? root.querySelector(`#flow .scard[data-rid="${CSS.escape(S.routine)}"]`) : null) || root.querySelector("#flow .scard, #flow [data-fkey^='row:']");
  } else if (view === "list") t = root.querySelector("#list-editor .le-grid [tabindex='0']") || root.querySelector("#list-editor button");
  if (!t) t = root.querySelector("#crumbs .crumb.here");
  if (!t) t = root.querySelector("#view-switch [aria-checked='true'], #view-switch button");
  t?.focus({preventScroll: true});
}

/* ---------------- toolbar parts: #est, #story-density, #crumbs, #btn-view-done */
function renderBuildToolbar(view) {
  updateBuildEst();
  const dens = $("#story-density");
  if (dens && !dens.childElementCount) {
    dens.append(h("button", {type: "button", role: "radio", "data-value": "cards", "aria-label": "Cards", title: "Cards: a picture of every screen"}, icon("storyboard"), h("span", {class: "lbl"}, "Cards")),
      h("button", {type: "button", role: "radio", "data-value": "list", "aria-label": "List", title: "List: compact, for large studies"}, icon("list"), h("span", {class: "lbl"}, "List")));
    ui.wireSeg(dens, storyDensity(), (v) => { setStoryDensity(v); renderStoryboard($("#flow")); });
  }
  dens?.setValue?.(storyDensity());
  const done = $("#btn-view-done");
  if (done && !done._wired) { done._wired = true; done.onclick = () => leaveSubView(); done.title = "Back (Esc)"; }
  const cr = $("#crumbs"); if (!cr) return;
  const parts = [];
  const sep = () => icon("chev-right", "crumb-sep");
  const link = (label, run, ic2) => h("button", {type: "button", class: "crumb", title: label, onclick: run}, ic2 ? icon(ic2) : null, h("span", {class: "crumb-t"}, label));
  if (view === "screen" && S.routine) {
    parts.push(link(typeof docName === "function" ? docName() : (S.exp.name || "experiment"), () => setBuildView("story"), "storyboard"));   // the name in the app bar, also after Save as
    for (const lp of loopsAround(S.routine)) {
      let p = null; walkFlow((n, pp) => { if (!p && n === lp) p = pp; });
      parts.push(sep(), link(lp.loop, () => p && openTrialList(p), "loop"));
    }
    parts.push(sep(), h("b", {class: "crumb here", "aria-current": "location", title: S.routine, tabindex: "-1", "data-fkey": "crumb:here"}, S.routine));
  } else if (view === "list") {
    const n = nodeAt(listPathNow());
    parts.push(link("Storyboard", () => leaveSubView("story"), "storyboard"), sep(), h("b", {class: "crumb here", "aria-current": "location", title: `Trial list “${n?.loop}”`, tabindex: "-1", "data-fkey": "crumb:here"}, icon("loop"), `Trial list “${n?.loop}”`));
  } else if (view === "diagram") {
    const m = nodeAt(diagramPathNow());
    parts.push(link("Storyboard", () => leaveSubView("story"), "storyboard"), sep(), h("b", {class: "crumb here", "aria-current": "location", title: `Workflow “${m?.statemachine}”`, tabindex: "-1", "data-fkey": "crumb:here"}, icon("workflow"), `Workflow “${m?.statemachine}”`));
  }
  keepFocus(cr, () => cr.replaceChildren(...parts));
  fitToolbar();
}
/* The toolbar never wraps or scrolls: labels give way to icons (each button keeps its aria-label and tooltip). */
function fitToolbar() {
  const tb = $("#build-toolbar"); if (!tb || !tb.clientWidth) return;
  tb.classList.remove("tight1", "tight2");
  if (tb.scrollWidth > tb.clientWidth + 1) tb.classList.add("tight1");
  if (tb.scrollWidth > tb.clientWidth + 1) tb.classList.add("tight2");
}
function updateBuildEst() {
  const el = $("#est"); if (!el || !S.exp) return;
  if (S.view !== "story" || !S.exp.flow.length) { el.textContent = ""; return; }
  const est = storyEstimate(updateBuildEst);
  el.textContent = est && !est.error ? EDGE.fmt.estimate(est) : est ? "" : "Estimating…";
  el.className = "t-caption";
}
function leaveSubView(to) {
  const back = to || (BUILD.returnView && !["list", "diagram"].includes(BUILD.returnView) ? BUILD.returnView : "story");
  if (back === "screen" && !S.routine) return setBuildView("story");
  if (S.sel && ["machine", "state"].includes(S.sel.kind) && back !== "story") S.sel = null;
  setBuildView(back);
}
function storyDensity() {
  const v = EDGE.prefs.get("view." + (S.path || "untitled"), {}) || {};
  return v.density === "list" ? "list" : "cards";
}
function setStoryDensity(d) {
  const key = "view." + (S.path || "untitled");
  EDGE.prefs.set(key, {...(EDGE.prefs.get(key, {}) || {}), density: d});
}

/* ================================================================== sidebar: rail and flyouts (SPEC §2.2, W7) */
/* P1's layoutColumns() decides the layout: #ws-build.rail-on shows the rail (below 1280 px, and between 1280 and 1599 px
 * while the companion is open). P4a fills the rail and opens the sidebar over the canvas as a flyout (#sidebar.open);
 * a pinned flyout (#sidebar.pinned, edge.layout.pinned) stays open until it is unpinned. */
const railOn = () => !!$("#ws-build")?.classList.contains("rail-on");
const flyoutOpen = () => railOn() && !!$("#sidebar")?.classList.contains("open");
function buildRailOnce() {
  const rail = $("#rail"), side = $("#sidebar");
  if (!rail || !side || rail.childElementCount) return;
  rail.append(...[["add", "plus", "Add", "Add to a screen"], ["files", "folder", "Files", "Pictures, sounds, pages and trial lists"],
    ["devices", "device", "Devices", "Eye trackers, EEG, response boxes, triggers"]].map(([sd, ic2, label, tip]) =>
    h("button", {type: "button", "data-side": sd, "aria-controls": "sidebar", "aria-expanded": "false", title: tip,
      onclick: () => toggleFlyout(sd)}, icon(ic2, "m"), h("span", {}, label))));
  side.prepend(h("div", {id: "sidebar-flyhead"}, h("span", {id: "sidebar-flytitle", class: "t-title-s"}),
    h("button", {type: "button", id: "sidebar-pin", class: "btn ghost icon sm", onclick: () => pinSidebar(!BUILD.pinned)}, icon("pin"))));
  side.addEventListener("keydown", (e) => { if (e.key === "Escape" && flyoutOpen() && !BUILD.pinned && !e.defaultPrevented) { e.preventDefault(); closeFlyout(true); } });
  if (typeof layoutColumns === "function") layoutColumns();
}
function applyRail() {
  const rail = $("#rail"), side = $("#sidebar");
  if (!rail || !side) return;
  buildRailOnce();
  const on = railOn();
  side.classList.toggle("pinned", BUILD.pinned);
  if (on && BUILD.pinned) side.classList.add("open");
  if (!on) side.classList.remove("open");
  const open = flyoutOpen();
  const title = $("#sidebar-flytitle");
  if (title) title.textContent = {add: "Add to a screen", files: "Files", devices: "Devices"}[S.side || "add"] || "";
  const pin = $("#sidebar-pin");
  if (pin) {
    pin.setAttribute("aria-pressed", BUILD.pinned ? "true" : "false");
    pin.setAttribute("aria-label", BUILD.pinned ? "Unpin: close the sidebar when you click elsewhere" : "Pin: keep the sidebar open");
    pin.title = pin.getAttribute("aria-label");
  }
  for (const b of rail.querySelectorAll("button[data-side]")) {
    const cur = open && (S.side || "add") === b.dataset.side;
    b.classList.toggle("on", cur);
    b.setAttribute("aria-expanded", cur ? "true" : "false");
  }
  const devBtn = rail.querySelector('[data-side="devices"]');
  if (devBtn) devBtn.dataset.count = S.exp?.devices?.length || "";
}
/* Opens the sidebar on a tab: as a flyout over the canvas when the rail shows, else just the tab. */
function openFlyout(tab = "add", {focus = true} = {}) {
  if (typeof showSide === "function") showSide(tab, {open: true});
  if (railOn()) $("#sidebar").classList.add("open");
  applyRail();
  if (focus && railOn()) setTimeout(() => {
    const f = tab === "add" ? $("#palette-filter") : $("#side-" + tab)?.querySelector("button, input, [tabindex='0']");
    f?.focus({preventScroll: true});
  }, 0);
}
function closeFlyout(restoreFocus = true) {
  const side = $("#sidebar"); if (!side) return;
  const was = side.classList.contains("open") ? (S.side || "add") : null;
  side.classList.remove("open", "dragging-from");
  if (BUILD.pinned) { BUILD.pinned = false; EDGE.prefs.set("layout", {...(EDGE.prefs.get("layout", {}) || {}), pinned: false}); }
  applyRail();
  if (restoreFocus && was) $(`#rail button[data-side="${was}"]`)?.focus();
}
function toggleFlyout(tab) { if (flyoutOpen() && (S.side || "add") === tab) closeFlyout(true); else openFlyout(tab); }
function pinSidebar(on) {
  BUILD.pinned = !!on;
  EDGE.prefs.set("layout", {...(EDGE.prefs.get("layout", {}) || {}), pinned: BUILD.pinned});
  applyRail();
}
function closeFlyoutAfterAdd() { if (flyoutOpen() && !BUILD.pinned) closeFlyout(false); }
function flyoutDragging(on) { $("#sidebar")?.classList.toggle("dragging-from", !!on && flyoutOpen() && !BUILD.pinned); if (!on) closeFlyoutAfterAdd(); }

/* ================================================================== sidebar: Add (SPEC W7) */
function paletteHidden(type) {
  if (!isSimple()) return false;
  if (typeof SIMPLE_HIDDEN !== "undefined" && SIMPLE_HIDDEN.has(type)) return true;
  const caps = new Set((S.exp.devices || []).flatMap((d) => S.schema.devices[d.type]?.capabilities || []));
  if (type === "gaze_roi" && !caps.has("gaze")) return true;
  if (type === "device_response" && !caps.has("input")) return true;
  return false;
}
function renderPalette() {
  const el = $("#palette"); if (!el || !S.schema || !S.exp) return;
  const f = ($("#palette-filter")?.value || "").trim().toLowerCase();
  const groups = {};
  let hidden = 0, shown = 0;
  for (const [type, d] of Object.entries(S.schema.components)) {
    const words = `${type} ${friendlyName(type)} ${d.description || ""}`.toLowerCase();
    if (f && !f.split(/\s+/).every((w) => words.includes(w))) continue;
    if (!f && paletteHidden(type)) { hidden++; continue; }
    (groups[d.category] ||= []).push(type);
    shown++;
  }
  keepFocus(el, () => {
    const out = [];
    for (const [label, cat] of BUILD_GROUPS) {
      const list = groups[cat]; if (!list) continue;
      out.push(h("div", {class: "pal-group", role: "group", "aria-label": label},
        h("div", {class: "t-overline pal-cat", "aria-hidden": "true"}, label), list.map(paletteItem)));
    }
    for (const [cat, list] of Object.entries(groups)) if (!BUILD_GROUPS.some(([, c]) => c === cat))
      out.push(h("div", {class: "pal-group", role: "group", "aria-label": "Other"}, h("div", {class: "t-overline pal-cat"}, "Other"), list.map(paletteItem)));
    if (!shown && f) {
      const a = buildAssistant();
      out.push(h("div", {class: "pal-none"}, h("p", {}, `Nothing called “${f}”. Try another word${a ? ", or ask the assistant" : ""}.`),
        a ? btn("Ask the assistant", () => a.open?.({text: f}), {ic: "assistant", cls: "btn sm assistant-outline"}) : null));
    }
    if (hidden) out.push(h("p", {class: "pal-more"}, `${hidden} more in Expert mode. Search finds them all.`));
    if (S.view === "screen" && S.routine) out.push(h("p", {class: "pal-tip"}, `Click adds to “${S.routine}”; drag onto the screen or a timeline row.`));
    el.replaceChildren(...out);
  });
}
function paletteItem(type) {
  const d = S.schema.components[type];
  return h("button", {type: "button", class: "pal-item", "data-type": type, "data-fkey": "pal:" + type, draggable: "true", title: d.description || "",
    onclick: (e) => paletteAdd(type, e.currentTarget),
    ondragstart: (e) => { e.dataTransfer.setData("edge/component", type); e.dataTransfer.effectAllowed = "copy"; flyoutDragging(true); },
    ondragend: () => flyoutDragging(false)},
  h("span", {class: `tile tint-${catKey(type)}`}, icon(typeIcon(type))),
  h("span", {class: "nm"}, friendlyName(type), !isSimple() ? h("span", {class: "pal-type mono"}, type) : null),
  h("span", {class: "add", "aria-hidden": "true"}, icon("plus")));
}
/* Click: adds to the open screen; elsewhere asks which screen (SPEC W3). */
async function paletteAdd(type, anchor) {
  if (!bEditable()) return;
  if (S.view === "screen" && S.routine && S.exp.routines[S.routine]) { await addComponent(type); closeFlyoutAfterAdd(); return; }
  const order = routineInFlowOrder();
  const all = [...order, ...Object.keys(S.exp.routines).filter((r) => !order.includes(r))];
  const addTo = async (rid) => { S.routine = rid; await addComponent(type); closeFlyoutAfterAdd(); };
  const fresh = async () => { const rid = await newRoutine(); if (rid) await addComponent(type); closeFlyoutAfterAdd(); };
  if (!all.length) return fresh();
  if (S.sel?.kind === "routine" && all.includes(S.sel.routine)) all.splice(all.indexOf(S.sel.routine), 1), all.unshift(S.sel.routine);
  ui.menu(anchor, [{head: `Add ${friendlyName(type)} to`}, ...all.slice(0, 30).map((rid) => ({label: rid, icon: "screen", run: () => addTo(rid)})),
    {sep: true}, {label: "New screen…", icon: "plus", run: fresh}], {placement: "right-start"});
}

/* ================================================================== sidebar: Files (SPEC W7) */
const DATA_EXT = [".csv", ".tsv", ".xlsx", ".json", ".txt"];
const FILE_KINDS = [["image", "Pictures", "images/"], ["audio", "Sounds", "sounds/"], ["html", "Web pages", "pages/"], ["data", "Trial lists and data", "conditions/"]];
let _filesTimer = null;
function renderFilesSoon() { clearTimeout(_filesTimer); _filesTimer = setTimeout(() => renderFiles(), 250); }
function fileKindOf(name) {
  const n = name.toLowerCase();
  if (DATA_EXT.some((x) => n.endsWith(x))) return "data";
  return typeof kindOf === "function" ? kindOf(name) : null;
}
function fileUsage() {
  const use = new Map();
  const add = (p, what) => { if (typeof p !== "string" || !p || isExpr(p)) return; if (!use.has(p)) use.set(p, []); use.get(p).push(what); };
  for (const [rid, r] of Object.entries(S.exp.routines)) for (const c of r.components || [])
    for (const k of ["image", "sound", "file"]) if (typeof c[k] === "string") add(c[k], {rid, id: c.id, text: `${rid} › ${c.id}`});
  walkFlow((n, path) => {
    if (!n || n.loop === undefined) return;
    const c = n.conditions, f = typeof c === "string" ? c : c && typeof c.file === "string" ? c.file : null;
    if (f) add(f, {loop: n.loop, path, text: `trial list “${n.loop}”`});
    if (Array.isArray(c)) for (const row of c) for (const v of Object.values(row || {}))
      if (typeof v === "string" && /\.[a-z0-9]{2,4}$/i.test(v)) add(v, {loop: n.loop, path, text: `trial list “${n.loop}”`});
  });
  return use;
}
async function assetLists(force = false) {
  const A = BUILD.assets;
  if (!force && A.path === S.path && A.lists && Date.now() - A.at < 8000) return A.lists;
  const lists = await Promise.all(FILE_KINDS.map(([k]) => (typeof assetList === "function" ? assetList(k) : Promise.resolve([]))));
  BUILD.assets = {path: S.path, at: Date.now(), lists};
  return lists;
}
async function renderFiles(force = false) {
  const el = $("#files"); if (!el || !S.exp) return;
  renderFiles.shownFor = S.path;
  const sec = $("#side-files");
  if (sec && !sec._wired) {
    sec._wired = true;
    sec.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); sec.classList.add("drop"); } });
    sec.addEventListener("dragleave", (e) => { if (e.target === sec) sec.classList.remove("drop"); });
    sec.addEventListener("drop", (e) => { if (!e.dataTransfer.files.length) return; e.preventDefault(); sec.classList.remove("drop"); uploadFiles([...e.dataTransfer.files]); });
  }
  if (!S.path) {
    el.replaceChildren(emptyState("folder", "Name the experiment first", "Its pictures, sounds, web pages and trial lists are kept in its own folder.",
      [btn("Name it…", async () => { if (await EDGE.ensurePath()) renderFiles(true); }, {cls: "btn sm primary"})]));
    return;
  }
  const lists = await assetLists(force);
  const used = fileUsage();
  const input = h("input", {type: "file", multiple: true, hidden: true, onchange: (e) => uploadFiles([...e.target.files])});
  const out = [h("div", {class: "files-head"}, btn("Add files", () => input.click(), {ic: "plus"}), h("span", {class: "t-caption"}, "or drop them here"), input)];
  FILE_KINDS.forEach(([kind, title, folder], i) => {
    const list = lists[i] || [];
    out.push(h("div", {class: "t-overline pal-cat"}, `${title} (${list.length})`));
    if (!list.length) out.push(h("p", {class: "files-none"}, `No ${title.toLowerCase()} yet. They go into ${folder} next to the experiment.`));
    for (const a of list) out.push(fileRow(kind, a, used.get(a.path) || []));
  });
  keepFocus(el, () => el.replaceChildren(...out));
}
function fileRow(kind, a, uses) {
  const name = a.path.split("/").pop();
  const ext = (name.split(".").pop() || "").toUpperCase().slice(0, 4);
  const meta = h("span", {class: "file-meta"});
  const size = a.size >= 1048576 ? `${(a.size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round((a.size || 0) / 1024))} KB`;
  meta.append(kind === "image" ? "" : size);
  let thumb;
  if (kind === "image") {
    thumb = h("img", {class: "file-thumb", alt: "", loading: "lazy", src: assetUrl(a.path)});
    thumb.onload = () => { meta.prepend(`${thumb.naturalWidth} × ${thumb.naturalHeight}`); };
  } else thumb = h("span", {class: `file-badge k-${kind}`, "aria-hidden": "true"}, kind === "audio" ? icon("sound") : ext);
  const usedTxt = uses.length ? h("span", {class: "file-used"}, `used in ${uses[0].text}${uses.length > 1 ? ` +${uses.length - 1}` : ""}`)
    : h("span", {class: "chip"}, "not used");
  const main = h("button", {type: "button", class: "file-main", "data-fkey": "file:" + a.path, title: a.path,
    onclick: (e) => fileOpen(kind, a, uses, e.currentTarget)},
  thumb, h("span", {class: "file-txt"}, h("span", {class: "file-name"}, name), h("span", {class: "file-sub"}, meta, usedTxt)));
  return h("div", {class: "file-row"}, main,
    kind === "audio" && typeof playSound === "function" ? iconBtn("play", `Listen to ${name}`, () => playSound(a.path)) : null,
    iconBtn("more", `More for ${name}`, (e) => fileMenu(e.currentTarget, kind, a, uses)));
}
function fileOpen(kind, a, uses, anchor) {
  const u = uses[0];
  if (kind === "data" && u?.path) return openTrialList(u.path);
  if (u?.rid && findComp(u.rid, u.id)) { S.routine = u.rid; selectComp(u.rid, u.id, false); setBuildView("screen"); return; }
  fileMenu(anchor, kind, a, uses);
}
function fileMenu(anchor, kind, a, uses) {
  const name = a.path.split("/").pop();
  const items = [];
  const comp = {image: "image", audio: "sound", html: "html"}[kind];
  if (comp && S.view === "screen" && S.routine) items.push({label: `Add to “${S.routine}”`, icon: "plus", run: async () => {
    if (!bEditable()) return; await addComponent(comp, undefined, {props: {[{image: "image", audio: "sound", html: "file"}[kind]]: a.path}}); }});
  if (kind === "data") {
    const loops = []; walkFlow((n, p) => { if (n?.loop !== undefined) loops.push([n, p]); });
    const targets = [...loops.map(([n, p]) => ({label: `Use for trial list “${n.loop}”`, icon: "loop", run: () => useFileForLoop(a.path, p)})),
      ...routineInFlowOrder().slice(0, 20).map((rid) => ({label: `Repeat “${rid}” with it`, icon: "screen", run: () => repeatWithFile(a.path, rid)}))];
    items.push({label: "Use as a trial list…", icon: "loop", items: targets.length ? targets : [{label: "Add a screen first", disabled: true}]});
    const lp = uses.find((u) => u.path);
    if (lp) items.push({label: "Open in the trial list view", icon: "table", run: () => openTrialList(lp.path)});
  }
  for (const u of uses.slice(0, 6)) if (u.rid) items.push({label: `Show it in ${u.text}`, icon: "screen", run: () => { selectComp(u.rid, u.id, false); setBuildView("screen"); }});
  const asst = buildAssistant();
  if (asst) items.push({sep: true}, {label: "Use with the assistant", icon: "assistant", run: () => asst.open?.({files: [a.path]})});
  if (!items.length) items.push({label: `${name} is not used yet`, disabled: true});
  ui.menu(anchor, items, {placement: "bottom-end"});
}
function useFileForLoop(rel, path) {
  if (!bEditable()) return;
  const n = nodeAt(path); if (!n) return;
  delete n.staircase; n.conditions = rel;
  commit(`Use ${rel} as the trial list “${n.loop}”`);
  openTrialList(path);
}
function repeatWithFile(rel, rid) {
  if (!bEditable()) return;
  let done = null;
  walkFlow((n, p) => { if (done || routineOfNode(n) !== rid || !isRoutineNode(n)) return;
    const {list, index} = parentOf(p);
    list[index] = {loop: uniqueId("trials", loopIds()), order: "random", repeats: 1, conditions: rel, children: [n]}; done = p; });
  if (!done) return;
  commit(`Repeat “${rid}” with ${rel}`);
  openTrialList(done);
}
async function uploadFiles(files) {
  if (!files.length) return;
  if (!S.path && !(await EDGE.ensurePath())) return;
  const dir = S.path.replace(/[^/]*$/, "");
  let n = 0;
  for (const f of files) {
    const kind = fileKindOf(f.name);
    if (!kind) { toast(`${f.name}: EDGE uses pictures, sounds, web pages and tables (CSV, Excel, JSON, text)`, {tone: "warning"}); continue; }
    if (kind !== "data" && typeof uploadAsset === "function") { if (await uploadAsset(f, kind)) n++; continue; }
    const rel = `conditions/${f.name.replace(/[^\w.\- ]+/g, "_")}`;
    const r = await fetch(`/api/upload?path=${encodeURIComponent(dir + rel)}`, {method: "POST", body: await f.arrayBuffer()});
    if (r.ok) n++; else toast(`Could not copy ${f.name}`, {tone: "danger"});
  }
  if (n) toast(`Added ${plural(n, "file")} to the experiment's folder`);
  BUILD.assets.at = 0;
  renderFiles(true);
}

/* ================================================================== sidebar: Devices (SPEC W7) */
const DEVICE_LABEL = {
  tobii: "Tobii Pro eye tracker", gazepoint: "Gazepoint eye tracker", lsl_inlet: "LSL stream", gtec: "g.tec amplifier",
  mindware: "MindWare BioLab", serial_inputs: "Response box (USB / serial)", labjack: "LabJack", parallel_inputs: "Parallel-port inputs",
  voice_key: "Voice key", ttl_serial: "USB trigger box", parallel_port: "Parallel-port triggers", lsl_markers: "LSL marker stream",
  udp_messages: "Messages from another program", sim_eyetracker: "Simulated eye tracker", sim_eeg: "Simulated EEG",
  sim_physio: "Simulated physiology", sim_inputs: "Simulated inputs", mouse_gaze: "Mouse as an eye tracker", ttl_loopback: "Virtual trigger output",
  trigger_adapter: "Trigger output",
};
function deviceLabel(d) {
  if (d.type === "trigger_adapter") {
    const t = S.schema.devices.trigger_adapter?.targets?.[(d.options || {}).target || "generic"];
    return t ? `Triggers to ${t.name}` : DEVICE_LABEL.trigger_adapter;
  }
  if (d.type === "lsl_inlet" && d.options?.stream_type) return `LSL stream (${d.options.stream_type})`;
  return DEVICE_LABEL[d.type] || d.type;
}
function renderDevices() {
  const el = $("#devices"); if (!el || !S.exp) return;
  const devs = S.exp.devices || [];
  const tab = $('#sidebar-tabs [data-side="devices"]');
  if (tab) {
    let c = tab.querySelector(".count");
    if (!c) { c = h("span", {class: "count"}); tab.append(c); }
    c.textContent = devs.length ? String(devs.length) : "";
  }
  keepFocus(el, () => {
    if (!devs.length) {
      el.replaceChildren(h("p", {class: "dev-none"}, "No devices. Keyboard and mouse always work. Add an eye tracker, EEG, a response box or a trigger output when you need one."));
      return;
    }
    el.replaceChildren(...devs.map((d, i) => deviceCard(d, i)));
  });
}
function deviceCard(d, i) {
  const sel = S.sel?.kind === "device" && S.sel.index === i;
  const info = S.schema.devices[d.type] || {};
  const test = (S.deviceTests || {})[d.id];
  const mark = proposalMark("devices", d.id);
  const status = test ? h("span", {class: "chip " + (test.ok ? "success" : "danger")}, h("span", {class: "dot"}),
    `${test.ok ? "Tested" : "Test failed"}${test.at ? " " + new Date(test.at).toTimeString().slice(0, 5) : ""}`)
    : h("span", {class: "chip"}, h("span", {class: "dot dot-off"}), "Not tested");
  return h("button", {type: "button", class: "dev-card" + (sel ? " selected" : "") + (mark ? " pv-" + mark : ""), "data-fkey": "dev:" + d.id,
    "aria-pressed": sel ? "true" : "false", onclick: () => { S.sel = {kind: "device", index: i}; closeFlyoutAfterAdd(); renderAll(); }},
  h("span", {class: "tile tint-hw"}, icon(deviceIcon(d), "m")),
  h("span", {class: "dev-txt"},
    h("span", {class: "dev-name"}, d.id, mark ? markBadge(mark) : null),
    h("span", {class: "dev-type"}, deviceLabel(d), !isSimple() ? h("span", {class: "mono"}, ` · ${d.type}`) : null, d.required === false ? " · optional" : null),
    h("span", {class: "dev-status"}, status,
      info.available === false ? h("span", {class: "chip warning", title: info.unavailable_reason || ""}, "needs setup") : null)));
}

/* Find connected devices (today's "Scan for hardware"): results inline in the Devices tab, each with [+ Add]. */
async function scanHardware(el) {
  if (!(el instanceof Element)) el = $("#tab-hardware") || $("#scan-results");
  if (typeof showTab === "function") showTab("hardware"); else EDGE.go("build");
  if (railOn()) openFlyout("devices", {focus: false});
  const b = $("#btn-scan");
  b?.setAttribute("aria-busy", "true");
  el.replaceChildren(h("div", {class: "scan-wait"}, h("span", {class: "spin"}), "Looking on the network, the USB and serial ports, and for Tobii and Gazepoint…"));
  const names = {lsl_streams: "LSL streams", serial_ports: "USB and serial ports", tobii: "Tobii eye trackers", gazepoint: "Gazepoint eye trackers"};
  try {
    const r = await api("/api/scan?timeout=1.5");
    const found = [];
    for (const [sec, items] of Object.entries(r)) for (const it of items || []) found.push([sec, it]);
    const out = [h("div", {class: "t-overline pal-cat"}, found.length ? `Found (${found.length})` : "Nothing found")];
    if (!found.length) out.push(h("p", {class: "dev-none"}, `Looked for ${Object.keys(r).map((k) => names[k] || k).join(", ")}. Check that the device is on and connected, then look again.`));
    for (const [sec, it] of found) {
      const {suggested, ...rest} = it;
      const label = rest.name || rest.description && rest.description !== "n/a" && rest.description || rest.port || rest.address || rest.model || names[sec] || sec;
      const sub = [names[sec] || sec, rest.port && rest.port !== label ? rest.port : null, rest.type || null].filter(Boolean).join(" · ");
      out.push(h("div", {class: "scan-row"},
        h("span", {class: "tile tint-hw"}, icon(suggested ? (DEVICE_ICON[suggested.type] || "device") : "chip")),
        h("span", {class: "dev-txt"}, h("span", {class: "dev-name"}, label), h("span", {class: "dev-type"}, sub),
          !isSimple() ? h("span", {class: "mono scan-raw"}, Object.entries(rest).map(([k, v]) => `${k}=${v}`).join("  ")) : null),
        suggested ? btn("Add", () => addDevice(suggested.type, suggested.options || {}), {ic: "plus"}) : null));
    }
    el.replaceChildren(...out);
  } catch (e) {
    el.replaceChildren(h("div", {class: "alert danger"}, icon("error"), h("div", {}, h("b", {}, "Couldn't look for devices"), e.message)));
  } finally { b?.removeAttribute("aria-busy"); }
}

function addDevice(type, options = {}, idHint = null) {
  if (!bEditable()) return null;
  const id = uniqueId(idHint || type.split("_")[0], new Set(S.exp.devices.map((d) => d.id)));
  const d = {id, type, options: {...options}};
  S.exp.devices.push(d);
  S.sel = {kind: "device", index: S.exp.devices.length - 1};
  if (typeof showSide === "function" && !railOn()) showSide("devices");
  commit(`Add device “${id}”`);
  toast(`Added ${deviceLabel(d)} as “${id}”. Test runs simulate it until it's connected.`);
  return id;
}

/* The Add device dialog (SPEC W7): groups from DEVICE_MENU and the trigger adapter's targets. */
const DEVICE_MENU = [
  ["Eye tracker", [["tobii", "Tobii Pro eye tracker"], ["gazepoint", "Gazepoint eye tracker"], ["lsl_inlet", "Any eye tracker on LSL", {stream_type: "Gaze"}]]],
  ["EEG / physiology", [["gtec", "g.tec amplifier (Unicorn, g.USBamp …)"], ["lsl_inlet", "Any LSL stream (EEG, physiology, motion …)", {stream_type: "EEG"}], ["mindware", "MindWare BioLab"]]],
  ["Response box & inputs", [["serial_inputs", "Button box, fMRI buttons or scanner trigger (USB)"], ["labjack", "LabJack: buttons, light sensor, TTL in and out"],
    ["parallel_inputs", "Buttons or TTL on a parallel port"], ["voice_key", "Voice key (microphone)"]]],
  ["Send triggers to…", [["ttl_serial", "USB trigger box (any)"], ["parallel_port", "Parallel-port TTL"]]],
  ["Marker stream", [["lsl_markers", "LSL marker stream (LabRecorder)"], ["udp_messages", "Messages from another program (UDP)"]]],
];
function deviceEntries() {
  const out = [];
  for (const [group, list] of DEVICE_MENU) {
    if (group === "Send triggers to…") {
      const adapter = S.schema.devices.trigger_adapter;
      for (const [key, t] of Object.entries(adapter?.targets || {}))
        out.push({group, type: "trigger_adapter", label: t.name, opts: {target: key}, idHint: key.split("_")[0] + "_trig",
          desc: `${t.wiring} Recorded in ${t.recorded_as}.`});
    }
    for (const [type, label, opts] of list) {
      const info = S.schema.devices[type]; if (!info) continue;
      out.push({group, type, label, opts: opts || {}, desc: info.description || "", unavailable: info.available === false ? (info.unavailable_reason || "needs an extra package") : null});
    }
  }
  if (!isSimple()) for (const type of Object.keys(S.schema.devices).filter((t) => t.startsWith("sim") || t === "mouse_gaze" || t === "ttl_loopback"))
    out.push({group: "Simulated (for testing)", type, label: DEVICE_LABEL[type] || type, opts: {}, desc: S.schema.devices[type].description || ""});
  return out;
}
function openAddDevice() {
  if (!bEditable()) return;
  const entries = deviceEntries();
  const groups = [...new Set(entries.map((x) => x.group))];
  let picked = null, only = null;
  const search = h("input", {class: "input", type: "search", placeholder: "Search devices (Tobii, BioSemi, LabJack, LSL…)", "aria-label": "Search devices"});
  const chips = h("div", {class: "adddev-chips", role: "group", "aria-label": "Kind of device"});
  const list = h("div", {class: "adddev-list"});
  const detail = h("div", {class: "adddev-detail", "aria-live": "polite"});
  let dlgEl = null, closeDlg = null;
  const setPicked = (x) => {
    picked = x;
    const add = dlgEl?.querySelector("footer .btn.primary"); if (add) add.disabled = !x;
    detail.replaceChildren();
    if (!x) { detail.append(h("p", {class: "t-caption"}, "Works without the hardware: simulated in test runs until it's connected.")); return; }
    put(detail, h("b", {}, x.label), h("p", {}, x.desc),
      x.unavailable ? h("p", {class: "adddev-warn"}, icon("warning"), ` On this computer: ${x.unavailable}`) : null,
      h("p", {class: "t-caption"}, "Works without the hardware: simulated in test runs until it's connected."));
  };
  const draw = () => {
    const f = search.value.trim().toLowerCase();
    list.replaceChildren();
    let first = null;
    for (const g of groups) {
      if (only && only !== g) continue;
      const items = entries.filter((x) => x.group === g && (!f || `${x.label} ${x.type} ${x.desc} ${g}`.toLowerCase().includes(f)));
      if (!items.length) continue;
      const gid = "adddev-g-" + groups.indexOf(g);
      const box = h("div", {class: "adddev-group", role: "group", "aria-labelledby": gid});
      for (const x of items) {
        const r = h("input", {type: "radio", name: "adddev", value: x.label});
        if (picked === x) r.checked = true;
        r.onchange = () => setPicked(x);
        const lab = h("label", {class: "adddev-opt", ondblclick: () => { setPicked(x); closeDlg?.("add"); }}, r,
          h("span", {class: "tile tint-hw"}, icon(x.type === "lsl_inlet" && x.opts.stream_type === "Gaze" ? "eyetracker" : (DEVICE_ICON[x.type] || "device"))),
          h("span", {class: "adddev-txt"}, h("span", {class: "adddev-name"}, x.label, !isSimple() ? h("span", {class: "mono"}, ` ${x.type}`) : null),
            x.unavailable ? h("span", {class: "t-caption"}, "needs setup on this computer") : null));
        box.append(lab);
        first ||= r;
      }
      list.append(h("div", {class: "t-overline adddev-head", id: gid}, g), box);
    }
    if (!list.childElementCount) list.append(h("p", {class: "t-2"}, `No device matches “${search.value}”.`));
  };
  chips.append(...groups.map((g) => h("button", {type: "button", class: "chip lg outline", "aria-pressed": "false", onclick: (e) => {
    only = only === g ? null : g;
    for (const c of chips.children) c.setAttribute("aria-pressed", c === e.currentTarget && only ? "true" : "false");
    draw();
  }}, g)));
  search.oninput = draw;
  draw(); setPicked(null);
  ui.dialog({title: "Add a device", icon: "device", size: "md", body: h("div", {class: "adddev"}, search, chips, list, detail),
    initialFocus: search,
    buttons: [{label: "Cancel", value: null}, {label: "Add device", value: "add", kind: "primary", disabled: true}],
    onOpen: (dlg, close) => { dlgEl = dlg; closeDlg = close; dlg.classList.add("adddev-dialog"); }})
    .then((v) => { if (v === "add" && picked) addDevice(picked.type, {...picked.opts}, picked.idHint || null); });
}
/* Kept name (SPEC §6.6): the old 35-item device menu now opens the Add device dialog. */
function deviceMenu() { openAddDevice(); }

/* ================================================================== the assistant's preview marks (SPEC W16) */
function proposalMark(kind, id) {
  const m = S.proposal?.marks?.[kind];
  const v = m && m[id];
  return v === "added" ? "add" : v === "changed" ? "mod" : v === "removed" ? "del" : null;
}
function markBadge(mark) {
  return h("span", {class: "pv-badge " + mark}, mark === "add" ? "+ New" : mark === "mod" ? "~ Changed" : "− Removed");
}

/* ================================================================== storyboard: the flow editor (SPEC W3) */
let _estimate = {key: null, value: null, waiters: []};
function storyEstimate(onReady) {
  const key = JSON.stringify(S.exp.flow) + JSON.stringify(S.exp.settings?.window || {}) + JSON.stringify(Object.fromEntries(Object.entries(S.exp.routines)
    .map(([k, r]) => [k, [r.duration, r.end_if, (r.components || []).map((c) => [c.type, c.start, c.duration, c.end_routine, c.if])]])));
  if (_estimate.key === key) {
    if (_estimate.value === null && typeof onReady === "function" && _estimate.waiters.length < 12) _estimate.waiters.push(onReady);
    return _estimate.value;
  }
  _estimate = {key, value: null, waiters: typeof onReady === "function" ? [onReady] : []};
  api("/api/estimate", {experiment: S.exp, path: S.path}).then((r) => {
    if (_estimate.key !== key) return;
    _estimate.value = r;
    const w = _estimate.waiters; _estimate.waiters = [];
    for (const f of w) { try { f(); } catch (e) { console.error(e); } }
  }).catch(() => { if (_estimate.key === key) _estimate.value = {error: true}; });
  return null;
}

/* The moment that shows the main stimulus: just after the last visual thing has appeared. */
function thumbTime(rid, doc = S.exp) {
  let t = 0;
  for (const c of doc.routines?.[rid]?.components || []) {
    const d = S.schema.components[c.type];
    if (!d || !d.visual || c.start_after || c.start_if || c.if || c.disabled === true || (typeof c.start !== "number" && c.start != null)) continue;
    t = Math.max(t, numOr(c.start, 0));
  }
  return t + 0.01;
}

/* When everything on a screen has finished (seconds), or null when something lasts until the screen ends (or
 * can't be known here). A screen's own length is a maximum: it ends earlier when all its items are done. */
function itemsEnd(rid, doc = S.exp) {
  const hz = 60;
  let end = 0;
  for (const c of doc.routines?.[rid]?.components || []) {
    if (c.disabled === true) continue;
    let st = c.start_after || c.start_if || c.if ? null : typeof c.start === "number" ? c.start : c.start == null ? 0 : null;
    if (typeof c.start_frame === "number") st = c.start_frame / hz;
    if (st === null) return null;
    let e = null;
    if (typeof c.duration === "number") e = st + c.duration;
    else if (typeof c.duration_frames === "number") e = st + c.duration_frames / hz;
    else if (c.stop_if) return null;
    else if (c.type === "sound" && typeof c.sound === "number" && typeof c.tone_duration === "number") e = st + c.tone_duration;
    else if (["variable", "marker"].includes(c.type)) e = st;
    if (e === null) return null;
    end = Math.max(end, e);
  }
  return end;
}
/* "How it ends", one line: "waits for space", "r / g / b · max 2 s", "0.6 s". */
function screenSummary(rid) {
  const r = S.exp.routines[rid] || {};
  const resp = (r.components || []).find((c) => c.end_routine && c.disabled !== true);
  const bits = [];
  if (resp) {
    const keys = Array.isArray(resp.keys) ? resp.keys.join(" / ") : typeof resp.keys === "string" && !isExpr(resp.keys) ? resp.keys : null;
    const what = {keyboard: keys ? (resp.keys.length === 1 || typeof resp.keys === "string" ? `waits for ${keys}` : keys) : "waits for a key",
      mouse: "waits for a click", slider: "waits for a rating", html: "waits for the form", survey: "waits for the answers",
      gaze_roi: "waits for a look", device_response: "waits for a button"}[resp.type] || `ends with ${resp.id}`;
    bits.push(what);
    if (typeof resp.duration === "number") bits.push(`max ${fmtS(numOr(resp.start, 0) + resp.duration)}`);
  }
  const early = !resp && !r.end_if && typeof r.duration === "number" ? itemsEnd(rid) : null;
  if (early !== null && early < r.duration) bits.push(`${fmtS(early)}, not ${fmtS(r.duration)}`);   // its items end first: the length is a maximum
  else if (typeof r.duration === "number") bits.push(resp ? `max ${fmtS(r.duration)}` : fmtS(r.duration));
  else if (isExpr(r.duration)) { const m = String(r.duration).match(/^\$([A-Za-z_]\w*)$/); bits.push(m ? `lasts “${m[1]}” s` : "computed length"); }
  else if (!resp) {
    const end = Math.max(0, ...(r.components || []).map((c) => numOr(c.start, 0) + numOr(c.duration, 0)));
    if (end) bits.push(fmtS(end));
  }
  if (r.end_if && !bits.length) bits.push("ends on a condition");
  return [...new Set(bits)].join(" · ") || (r.components?.length ? "no end set" : "empty");
}
function summaryIcon(rid) {
  const r = S.exp.routines[rid] || {};
  const resp = (r.components || []).find((c) => c.end_routine && c.disabled !== true);
  return resp ? [typeIcon(resp.type), catKey(resp.type)] : ["clock", "logic"];
}

function renderStoryboard(el) {
  el = el || $("#flow");
  if (!el || !S.exp) return;
  const density = storyDensity();
  el.classList.add("story-host");
  el.dataset.density = density;
  keepFocus(el, () => {
    const out = [];
    const removed = S.proposal?.marks?.removed || [];
    if (removed.length) out.push(h("div", {class: "alert danger story-removed"}, icon("trash"), h("div", {class: "msg"}, h("b", {}, "Removed by the assistant: "),
      removed.map((r) => r.id || r.kind).join(", "))));
    if (!S.exp.flow.length) { if (!ASST_CANVAS.busy) out.push(emptyFlow()); }   // while the assistant builds, its note shows instead
    else out.push(density === "list" ? storyList() : storySeq(S.exp.flow, [], true));
    const inFlow = new Set(routineInFlowOrder());
    const unused = Object.keys(S.exp.routines).filter((rid) => !inFlow.has(rid));
    if (unused.length) out.push(notShownRow(unused));
    el.replaceChildren(...out);
  });
}
function emptyFlow() {
  const a = buildAssistant();
  return emptyState("storyboard", "Your experiment is empty.", "An experiment is screens shown in order: instructions, trials, a goodbye.", [
    btn("Add a screen", () => newRoutine(), {cls: "btn primary", ic: "plus"}),
    a ? btn("Describe it", () => a.open?.({text: ""}), {cls: "btn assistant-outline", ic: "assistant"}) : null,
    typeof openWizard === "function" ? btn("Answer a few questions", () => openWizard(), {cls: "btn", ic: "checklist"}) : null]);
}
function notShownRow(unused) {
  return h("div", {class: "alert warning notshown", role: "group", "aria-label": "Screens that are not shown"}, icon("warning"),
    h("div", {class: "msg"}, h("b", {}, "Not shown in the experiment: "),
      h("span", {class: "notshown-list"}, unused.map((rid) => h("span", {class: "notshown-item"},
        h("button", {type: "button", class: "linkish", title: "Open this screen", onclick: () => openScreen(rid)}, rid),
        btn("Add back", () => { if (!bEditable()) return; S.exp.flow.push(rid); BUILD.focusKey = "card:" + (S.exp.flow.length - 1); commit(`Add “${rid}” back`); }),
        btn("Delete", () => deleteRoutine(rid), {cls: "btn sm ghost danger-quiet"}))))));
}

/* One list item per step: the step and the insert target after it (the first one also has the target before it),
 * so a step never wraps away from its targets. */
function storySeq(nodes, path, top = false) {
  const seq = h("div", {class: "seq" + (top ? " top" : ""), role: "list", "aria-label": top ? "The experiment's screens, in order" : null});
  if (!nodes.length) { seq.append(h("div", {class: "sgroup", role: "listitem"}, insItem(path, 0, "only"))); return seq; }
  nodes.forEach((n, i) => {
    const last = i === nodes.length - 1;
    seq.append(h("div", {class: "sgroup", role: "listitem"},
      i === 0 ? insItem(path, 0, "first") : null,
      storyItem(n, [...path, i]),
      last && top ? null : insItem(path, i + 1, last ? "end" : "between", nodes, i)));
  });
  // the top level's "Add a step" may wrap onto its own row, so a wide last frame keeps the room
  if (top) seq.append(h("div", {class: "sgroup", role: "listitem"}, insItem(path, nodes.length, "top-end", nodes, nodes.length - 1)));
  return seq;
}
function insItem(listPath, index, where, nodes, i) {
  const label = where === "top-end" ? "Add a step at the end" : where === "only" ? "Add a step here"
    : where === "first" ? "Add a step at the start" : where === "end" ? "Add a step at the end of this part"
      : `Add a step after “${nodeName(nodes?.[i])}”`;
  const target = h("button", {type: "button", class: "ins", "data-fkey": `ins:${listPath.join(".")}:${index}`, "aria-label": label, title: label,
    "data-coach": !listPath.length && index === 0 ? "flow-start" : null,     // the outermost "+ at the start" (tutorials point at it)
    onclick: (e) => flowInsertMenu(e.currentTarget, listPath, index)}, icon("plus"));
  const item = h("div", {class: "ins-item " + where}, target,
    where === "top-end" ? h("button", {type: "button", class: "ins-text", tabindex: "-1", onclick: () => flowInsertMenu(target, listPath, index)}, "Add a step") : null);
  dropTarget(item, target, listPath, index);
  return item;
}
function dropTarget(zone, mark, listPath, index) {
  zone.addEventListener("dragover", (e) => {
    if (!e.dataTransfer.types.includes("edge/flowpath") || !mark.classList.contains("drop-ok")) return;
    e.preventDefault(); e.dataTransfer.dropEffect = "move"; mark.classList.add("drop-hover");
  });
  zone.addEventListener("dragleave", () => mark.classList.remove("drop-hover"));
  zone.addEventListener("drop", (e) => {
    const raw = e.dataTransfer.getData("edge/flowpath"); if (!raw) return;
    e.preventDefault(); e.stopPropagation(); mark.classList.remove("drop-hover");
    moveFlowNode(JSON.parse(raw), listPath, index);
  });
  mark.dataset.list = JSON.stringify(listPath); mark.dataset.index = index;
}
/* Drag a card or a frame: valid insert targets grow and turn accent while dragging (SPEC W3). */
function makeDraggable(el, path) {
  el.draggable = true;
  el.addEventListener("dragstart", (e) => {
    if (e.target !== el && !el.contains(e.target)) return;
    e.stopPropagation();
    if (S.proposal) { e.preventDefault(); return bEditable(); }
    e.dataTransfer.setData("edge/flowpath", JSON.stringify(path));
    e.dataTransfer.effectAllowed = "move";
    el.classList.add("dragging");
    document.body.classList.add("flow-dragging");
    const {list: src, index: si} = parentOf(path);
    for (const m of document.querySelectorAll("#flow .ins, #flow .srow-drop")) {
      const lp = JSON.parse(m.dataset.list || "[]"), idx = +m.dataset.index;
      const inside = pathStartsWith(lp, path);
      const noop = nodeAt(lp) === src && (idx === si || idx === si + 1);
      m.classList.toggle("drop-ok", !inside && !noop);
    }
  });
  el.addEventListener("dragend", () => {
    el.classList.remove("dragging");
    document.body.classList.remove("flow-dragging");
    for (const m of document.querySelectorAll("#flow .drop-ok, #flow .drop-hover")) m.classList.remove("drop-ok", "drop-hover");
  });
  return el;
}

function storyItem(n, path) {
  if (isRoutineNode(n)) return storyCardItem(n, path);
  if (n && n.loop !== undefined) return loopFrame(n, path);
  if (n && n.statemachine !== undefined) return workflowFrame(n, path);
  if (n && n.if !== undefined) return branchFrame(n, path);
  return h("div", {class: "sitem"}, h("span", {class: "chip warning"}, "Unknown step"));
}
function nodeSelected(kind, path) { return S.sel?.kind === kind && samePath(S.sel.path, path); }

function storyCardItem(n, path) {
  const rid = routineOfNode(n);
  const exists = !!S.exp.routines[rid];
  const mark = proposalMark("routines", rid);
  const sel = S.sel?.kind === "routine" && S.sel.routine === rid && (!S.sel.path || samePath(S.sel.path, path));
  const [capIc, capCat] = exists ? summaryIcon(rid) : ["warning", "respond"];
  const summary = exists ? screenSummary(rid) : "this screen doesn't exist";
  const key = "card:" + path.join(".");
  const card = h("button", {type: "button", class: "scard" + (sel ? " selected" : "") + (mark ? " pv-" + mark : "") + (exists ? "" : " missing"),
    "data-fkey": key, "data-rid": rid, "aria-pressed": sel ? "true" : "false",
    "aria-label": `Screen ${rid}${n.if ? ", shown only if " + exprInWords(n.if) : ""}: ${summary}`,
    title: "Click to select · double-click or Enter to open · right-click for more"},
  h("span", {class: "thumb"}, exists ? thumbCanvas(rid, path) : null),
  h("span", {class: "meta"},
    h("span", {class: "name"}, h("span", {class: "nm", title: rid}, rid), n.if ? h("span", {class: "chip warning if-chip", title: "Shown only if " + exprInWords(n.if)}, "if") : null,
      mark ? markBadge(mark) : null),
    h("span", {class: "cap"}, icon(capIc, "c-" + capCat), h("span", {class: "cap-txt"}, summary))));
  bindNodeControl(card, n, path, key);
  card.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("edge/component") && exists) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; card.classList.add("drop-target"); } });
  card.addEventListener("dragleave", () => card.classList.remove("drop-target"));
  card.addEventListener("drop", async (e) => {
    const type = e.dataTransfer.getData("edge/component"); if (!type) return;
    e.preventDefault(); e.stopPropagation(); card.classList.remove("drop-target");
    if (!bEditable()) return;
    S.routine = rid; await addComponent(type);
  });
  const more = h("button", {type: "button", class: "btn ghost icon sm scard-more", tabindex: "-1", "aria-label": `More for “${rid}”`, title: "More",
    onclick: (e) => { e.stopPropagation(); nodeMenu(e.currentTarget, path); }}, icon("more"));
  return makeDraggable(h("div", {class: "sitem card-item"}, card, more), path);
}
/* Clicks, double clicks and keys shared by cards, frame headers, list rows and flow-strip pills. */
function bindNodeControl(ctl, n, path, key) {
  ctl.addEventListener("click", (e) => {
    const now = Date.now();
    const dbl = BUILD.lastClick.key === key && now - BUILD.lastClick.t < 450;
    BUILD.lastClick = {key: dbl ? null : key, t: now};
    if (dbl || e.detail >= 2) return openNode(n, path);
    selectNode(n, path);
  });
  ctl.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); nodeMenu(e, path); });
  ctl.addEventListener("keydown", (e) => nodeKeys(e, n, path, ctl));
}
function selectNode(n, path) {
  if (isRoutineNode(n)) { const rid = routineOfNode(n); if (!S.exp.routines[rid]) return; S.routine = rid; S.sel = {kind: "routine", routine: rid, path}; }
  else if (n.loop !== undefined) S.sel = {kind: "loop", path};
  else if (n.statemachine !== undefined) S.sel = {kind: "machine", path};
  else if (n.if !== undefined) S.sel = {kind: "branch", path};
  renderAll();
}
function openNode(n, path) {
  if (isRoutineNode(n)) return openScreen(routineOfNode(n));
  if (n.loop !== undefined) return openTrialList(path);
  if (n.statemachine !== undefined) return openDiagram(path);
  selectNode(n, path);
}
function storyFocusables() { return [...document.querySelectorAll("#flow .scard, #flow .frame-head > .lbl, #flow .sm-name, #flow .srow-main")].filter((x) => x.offsetParent !== null); }
function moveStoryFocus(from, dir) {
  const all = storyFocusables();
  const i = all.indexOf(from); if (i < 0) return;
  let t = null;
  if (dir === "left") t = all[i - 1];
  else if (dir === "right") t = all[i + 1];
  else {
    const r = from.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    let best = Infinity;
    for (const x of all) {
      if (x === from) continue;
      const q = x.getBoundingClientRect(), qx = q.left + q.width / 2, qy = q.top + q.height / 2;
      const dy = dir === "down" ? qy - cy : cy - qy;
      if (dy <= 4) continue;
      const score = dy + Math.abs(qx - cx) * 0.6;
      if (score < best) { best = score; t = x; }
    }
  }
  if (t) { t.focus(); t.scrollIntoView({block: "nearest", inline: "nearest"}); }
}
function nodeKeys(e, n, path, ctl) {
  const mod = e.ctrlKey || e.metaKey;
  const arrows = {ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down"};
  if (e.altKey && arrows[e.key]) { e.preventDefault(); e.stopPropagation(); moveNodeBy(path, ["left", "up"].includes(arrows[e.key]) ? -1 : 1); return; }
  if (arrows[e.key] && !mod && !e.shiftKey) { e.preventDefault(); e.stopPropagation(); moveStoryFocus(ctl, arrows[e.key]); return; }
  if ((e.key === "Home" || e.key === "End") && !mod && !e.shiftKey) {        // the first or last step of the storyboard
    const all = [...document.querySelectorAll("#flow [data-fkey^='card:'], #flow [data-fkey^='frame:'], #flow [data-fkey^='row:']")].filter((x) => x.offsetParent);
    const t = e.key === "Home" ? all[0] : all[all.length - 1];
    if (t) { e.preventDefault(); e.stopPropagation(); t.focus(); t.scrollIntoView({block: "nearest", inline: "nearest"}); }
    return;
  }
  if (e.key === "Enter" && !mod) { e.preventDefault(); e.stopPropagation(); openNode(n, path); return; }
  if ((e.key === "F10" && e.shiftKey) || e.key === "ContextMenu") { e.preventDefault(); e.stopPropagation(); nodeMenu(ctl, path); return; }
  if (e.key === "Delete" || (e.key === "Backspace" && !mod)) { e.preventDefault(); e.stopPropagation(); removeFromFlow(path); return; }
  if (e.key === "F2") { e.preventDefault(); e.stopPropagation(); renameNode(n, path); return; }
  if (mod && e.key.toLowerCase() === "d") { e.preventDefault(); e.stopPropagation(); if (isRoutineNode(n)) duplicateRoutine(routineOfNode(n), path); return; }
  if (e.key === "Escape" && S.sel) { e.preventDefault(); e.stopPropagation(); S.sel = null; renderAll(); }
}

function loopDesc(n) {
  const bits = [];
  const c = n.conditions;
  if (n.staircase) bits.push(`staircase on “${n.staircase.variable || "level"}”`);
  else if (typeof c === "string" || (c && typeof c.file === "string")) {
    const f = typeof c === "string" ? c : c.file;
    const rows = BUILD.rows[JSON.stringify(c) + "|" + (S.path || "")];
    bits.push(f.split("/").pop() + (Array.isArray(rows) ? ` · ${plural(rows.length, "row")}` : ""));
    if (!rows) loopRows(c);
  } else if (c && c.factorial) {
    const k = Object.values(c.factorial).reduce((a, v) => a * (Array.isArray(v) ? v.length : 1), 1);
    bits.push(`every combination · ${plural(k, "row")}`);
  } else if (Array.isArray(c)) bits.push(plural(c.length, "row"));
  // no trial list: the screens inside just repeat ("repeats 2 times"), there is nothing "missing"
  if (c === undefined || c === null) bits.push(n.repeats != null && n.repeats !== 1 ? `repeats ${n.repeats} times` : "runs once");
  else if (n.repeats != null && n.repeats !== 1) bits[bits.length - 1] += ` × ${n.repeats}`;
  if (!n.staircase) bits.push(ORDER_WORDS[n.order || "sequential"] || n.order);
  if (n.stop_if) bits.push("stops early");
  return bits.join(" · ");
}
function frameHead(kind, n, path, label, meta, actions) {
  const key = "frame:" + path.join(".");
  const lbl = h("button", {type: "button", class: "lbl", "data-fkey": key, title: kind === "loop" ? "Click to select · double-click to open the list" : "Click to select"},
    icon(kind), h("span", {class: "frame-title"}, label));
  bindNodeControl(lbl, n, path, key);
  const head = h("div", {class: "frame-head" + (kind === "workflow" ? " fl-head" : "")}, lbl, meta ? h("span", {class: "frame-meta"}, meta) : null,
    h("span", {class: "actions"}, actions, iconBtn("more", `More for ${nodeWords(n)}`, (e) => nodeMenu(e.currentTarget, path), "btn ghost icon sm")));
  head.addEventListener("click", (e) => { if (e.target === head) selectNode(n, path); });
  return head;
}
function loopFrame(n, path) {
  const sel = nodeSelected("loop", path);
  const mark = proposalMark("loops", n.loop);
  const frame = h("section", {class: "frame loop" + (sel ? " selected" : "") + (mark ? " pv-" + mark : ""), "aria-label": `Trial list ${n.loop}`},
    frameHead("loop", n, path, `Trial list “${n.loop}”`, loopDesc(n), [mark ? markBadge(mark) : null,
      btn("Open list", () => openTrialList(path), {cls: "btn sm ghost", ic: "table"})]),
    storySeq(n.children ||= [], [...path, "children"]));
  return makeDraggable(h("div", {class: "sitem frame-item"}, frame), path);
}
function branchFrame(n, path) {
  const sel = nodeSelected("branch", path);
  const words = n.if === "$True" || n.if === true ? "… (no condition yet)" : exprInWords(n.if);
  const frame = h("section", {class: "frame branch" + (sel ? " selected" : ""), "aria-label": "If / otherwise"},
    frameHead("branch", n, path, `Only if ${words}`, !isSimple() ? h("span", {class: "mono"}, String(n.if)) : null, []),
    h("div", {class: "lanes"},
      h("div", {class: "lane"}, h("span", {class: "lane-lbl"}, "then"), storySeq(n.then ||= [], [...path, "then"])),
      h("div", {class: "lane"}, h("span", {class: "lane-lbl"}, "otherwise"), storySeq(n.else ||= [], [...path, "else"]))));
  return makeDraggable(h("div", {class: "sitem frame-item"}, frame), path);
}
function routesInWords(st) {
  const nx = (st.next || []).map((t) => typeof t === "string" ? {goto: t} : t);
  if (!nx.length) return "then the end";
  return nx.map((t, i) => `→ ${t.goto === "end" ? "the end" : t.goto}${t.if ? " when " + exprInWords(t.if) : nx.length > 1 && i === nx.length - 1 ? " otherwise" : ""}`).join(" · ");
}
function workflowFrame(n, path) {
  const sel = nodeSelected("machine", path);
  const mark = proposalMark("loops", n.statemachine);
  const states = Object.entries(n.states ||= {});
  const box = h("div", {class: "sm-states"});
  for (const [name, st] of states) {
    const isSel = S.sel?.kind === "state" && samePath(S.sel.path, path) && S.sel.name === name;
    const key = `state:${path.join(".")}:${name}`;
    const nameBtn = h("button", {type: "button", class: "sm-name", "data-fkey": key, title: "Select this phase"},
      n.start === name ? icon("play") : null, h("span", {}, name));
    nameBtn.addEventListener("click", () => { S.sel = {kind: "state", path, name}; renderAll(); });
    nameBtn.addEventListener("dblclick", () => openDiagram(path));
    nameBtn.addEventListener("keydown", (e) => {
      const arrows = {ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down"};
      if (arrows[e.key] && !e.altKey && !e.ctrlKey) { e.preventDefault(); moveStoryFocus(nameBtn, arrows[e.key]); }
    });
    box.append(h("div", {class: "sm-state" + (n.start === name ? " start" : "") + (isSel ? " selected" : "")},
      h("div", {class: "sm-head"}, nameBtn, st.max_visits ? h("span", {class: "t-caption"}, `at most ${plural(st.max_visits, "time")}`) : null),
      storySeq(st.run ||= [], [...path, "states", name, "run"]),
      h("div", {class: "sm-next"}, routesInWords(st))));
  }
  box.append(btn("Add a phase", () => { if (bEditable() && typeof addState === "function") addState(path); }, {cls: "btn sm ghost sm-add", ic: "plus"}));
  const frame = h("section", {class: "frame workflow fl-box sm" + (sel ? " selected" : "") + (mark ? " pv-" + mark : ""), "aria-label": `Workflow ${n.statemachine}`},
    frameHead("workflow", n, path, `Workflow “${n.statemachine}”`, plural(states.length, "phase"), [mark ? markBadge(mark) : null,
      btn("Open diagram", () => openDiagram(path), {cls: "btn sm ghost", ic: "workflow"})]),
    box);
  return makeDraggable(h("div", {class: "sitem frame-item"}, frame), path);
}

/* List density: the same flow as an indented list for large studies (SPEC W3). */
function storyList() {
  const ul = h("div", {class: "slist", role: "list", "aria-label": "The experiment's screens, in order"});
  let num = 0;
  const row = (n, path, depth, kind) => {
    const key = "row:" + path.join(".");
    const rid = isRoutineNode(n) ? routineOfNode(n) : null;
    const sel = rid ? S.sel?.kind === "routine" && S.sel.routine === rid && (!S.sel.path || samePath(S.sel.path, path))
      : nodeSelected({loop: "loop", branch: "branch", workflow: "machine"}[kind], path);
    const mark = rid ? proposalMark("routines", rid) : n.loop ? proposalMark("loops", n.loop) : null;
    let main;
    if (rid) {
      num++;
      const [ic2, cat] = S.exp.routines[rid] ? summaryIcon(rid) : ["warning", "respond"];
      main = h("button", {type: "button", class: "srow-main", "data-fkey": key},
        h("span", {class: "srow-num"}, String(num)), icon("screen"), h("span", {class: "srow-name"}, rid),
        n.if ? h("span", {class: "chip warning"}, "if") : null, mark ? markBadge(mark) : null,
        h("span", {class: "srow-cap"}, icon(ic2, "c-" + cat), S.exp.routines[rid] ? screenSummary(rid) : "this screen doesn't exist"));
    } else {
      const label = kind === "loop" ? `Trial list “${n.loop}” · ${loopDesc(n)}` : kind === "branch" ? `Only if ${exprInWords(n.if)}` : `Workflow “${n.statemachine}”`;
      main = h("button", {type: "button", class: "srow-main frame-row k-" + kind, "data-fkey": key}, h("span", {class: "srow-num"}), icon(kind), h("span", {class: "srow-name"}, label), mark ? markBadge(mark) : null);
    }
    bindNodeControl(main, n, path, key);
    const actions = h("span", {class: "srow-actions"},
      kind === "loop" ? btn("Open list", () => openTrialList(path), {cls: "btn sm ghost"}) : kind === "workflow" ? btn("Open diagram", () => openDiagram(path), {cls: "btn sm ghost"}) : null,
      iconBtn("more", `More for ${nodeWords(n)}`, (e) => nodeMenu(e.currentTarget, path)));
    const index = path[path.length - 1];
    const lp = path.slice(0, -1);
    const before = h("span", {class: "srow-drop before", "data-list": JSON.stringify(lp), "data-index": index});
    const after = h("span", {class: "srow-drop after", "data-list": JSON.stringify(lp), "data-index": index + 1});
    const r = h("div", {class: "srow" + (sel ? " selected" : "") + (mark ? " pv-" + mark : ""), role: "listitem", style: `--depth:${depth}`}, before, main, actions, after);
    r.addEventListener("dragover", (e) => {
      if (!e.dataTransfer.types.includes("edge/flowpath")) return;
      const top = e.clientY < r.getBoundingClientRect().top + r.offsetHeight / 2;
      const m = top ? before : after;
      if (!m.classList.contains("drop-ok")) return;
      e.preventDefault(); before.classList.toggle("drop-hover", top); after.classList.toggle("drop-hover", !top);
    });
    r.addEventListener("dragleave", () => { before.classList.remove("drop-hover"); after.classList.remove("drop-hover"); });
    r.addEventListener("drop", (e) => {
      const raw = e.dataTransfer.getData("edge/flowpath"); if (!raw) return;
      const m = before.classList.contains("drop-hover") ? before : after.classList.contains("drop-hover") ? after : null;
      before.classList.remove("drop-hover"); after.classList.remove("drop-hover");
      if (!m) return;
      e.preventDefault(); e.stopPropagation();
      moveFlowNode(JSON.parse(raw), JSON.parse(m.dataset.list), +m.dataset.index);
    });
    ul.append(makeDraggable(r, path));
  };
  const lane = (label, depth) => ul.append(h("div", {class: "srow lane-row", role: "listitem", style: `--depth:${depth}`}, h("span", {class: "lane-lbl"}, label)));
  const walk = (nodes, path, depth) => (nodes || []).forEach((n, i) => {
    const p = [...path, i];
    if (isRoutineNode(n)) row(n, p, depth, "screen");
    else if (n.loop !== undefined) { row(n, p, depth, "loop"); walk(n.children, [...p, "children"], depth + 1); }
    else if (n.if !== undefined) { row(n, p, depth, "branch"); lane("then", depth + 1); walk(n.then, [...p, "then"], depth + 1); lane("otherwise", depth + 1); walk(n.else, [...p, "else"], depth + 1); }
    else if (n.statemachine !== undefined) {
      row(n, p, depth, "workflow");
      for (const [name, st] of Object.entries(n.states || {})) {
        const b = h("button", {type: "button", class: "srow-main", "data-fkey": `lstate:${p.join(".")}:${name}`, onclick: () => { S.sel = {kind: "state", path: p, name}; renderAll(); }},
          h("span", {class: "srow-num"}), icon("play"), h("span", {class: "srow-name"}, `Phase “${name}”`), h("span", {class: "srow-cap"}, routesInWords(st)));
        ul.append(h("div", {class: "srow" + (S.sel?.kind === "state" && samePath(S.sel.path, p) && S.sel.name === name ? " selected" : ""), role: "listitem", style: `--depth:${depth + 1}`}, b));
        walk(st.run, [...p, "states", name, "run"], depth + 2);
      }
    }
  });
  walk(S.exp.flow, [], 0);
  const add = h("button", {type: "button", class: "btn sm ghost srow-add", "data-fkey": "ins::" + S.exp.flow.length, onclick: (e) => flowInsertMenu(e.currentTarget, [], S.exp.flow.length)}, icon("plus"), "Add a step");
  ul.append(h("div", {class: "srow add-row", role: "listitem"}, add));
  return ul;
}

/* Thumbnails: drawn at device-pixel-ratio 2 at the screen's main moment, with the first trial-list row's values. */
/* Values for a card: the first row of every trial list around that place in the flow. */
function rowForPath(path) {
  let row = {};
  for (let i = 1; i < path.length; i++) {
    const n = nodeAt(path.slice(0, i));
    if (n && !Array.isArray(n) && n.loop !== undefined) row = {...row, ...((loopRowsFor(n) || [])[0] || {})};
  }
  return {...(S.exp.variables || {}), ...row};
}
function thumbCanvas(rid, path) {
  const row = path ? rowForPath(path) : sampleRowFor(rid, 0);
  const key = JSON.stringify([rid, S.exp.routines[rid], row, S.exp.settings?.window, BUILD.imgGen, S.path]);
  let cv = BUILD.thumbs.get(key);
  if (!cv) {
    cv = document.createElement("canvas");
    cv.width = 432;
    try { drawScreen(cv, rid, thumbTime(rid), {row, minText: 18}); } catch (e) { /* a preview is best effort */ }
    BUILD.thumbs.set(key, cv);
    if (BUILD.thumbs.size > 300) BUILD.thumbs.delete(BUILD.thumbs.keys().next().value);
  }
  let out = cv;
  if (cv.parentNode) { out = document.createElement("canvas"); out.width = cv.width; out.height = cv.height; out.getContext("2d").drawImage(cv, 0, 0); }
  out.setAttribute("role", "img");
  out.setAttribute("aria-label", `Preview of “${rid}”`);
  return out;
}

/* ---------------- flow editing: insert, move, card menu (kept names: flowInsertMenu, nodeMenu, moveFlowNode) */
function flowInsertMenu(e, listPath, index) {
  if (!bEditable()) return;
  const list = getNode(listPath);
  const anchor = e instanceof Element ? e : e?.currentTarget instanceof Element ? e.currentTarget : e;
  const rids = [...routineInFlowOrder(), ...Object.keys(S.exp.routines).filter((r) => !routineInFlowOrder().includes(r))];
  const insert = (node, label, sel) => { list.splice(index, 0, node); if (sel) S.sel = sel; BUILD.focusKey = null; commit(label); };
  const asst = buildAssistant();
  const items = [{head: "Add here"},
    {label: "New screen…", icon: "screen", run: () => newRoutine({path: listPath, index})},
    {label: "Show an existing screen again", icon: "loop", disabled: !rids.length, items: rids.slice(0, 40).map((rid) => ({label: rid, icon: "screen",
      run: () => insert(rid, `Show “${rid}” again`, {kind: "routine", routine: rid, path: [...listPath, index]})}))},
    {label: "Copy of a screen", icon: "duplicate", disabled: !rids.length, items: rids.slice(0, 40).map((rid) => ({label: rid, icon: "screen",
      run: () => { const nid = copyRoutine(rid); insert(nid, `Copy “${rid}”`, {kind: "routine", routine: nid, path: [...listPath, index]}); }}))},
    {sep: true},
    {label: "Trial list (repeat screens for each row)", icon: "loop", run: () => {
      const id = uniqueId("trials", loopIds());
      insert({loop: id, order: "random", repeats: 1, conditions: [{condition: "A"}, {condition: "B"}], children: []}, `Add trial list “${id}”`, {kind: "loop", path: [...listPath, index]});
    }},
    {label: "If / otherwise", icon: "branch", run: () => insert({if: "$True", then: [], else: []}, "Add if / otherwise", {kind: "branch", path: [...listPath, index]})},
    {label: "Workflow (practice until good, screening…)", icon: "workflow", shortcut: isSimple() ? "advanced" : "", run: () => {
      const id = uniqueId("workflow", loopIds());
      insert({statemachine: id, start: "start", states: {start: {run: [], next: [{goto: "end"}]}}}, `Add workflow “${id}”`, {kind: "machine", path: [...listPath, index]});
    }},
    asst ? {sep: true} : null,
    asst ? {label: "Describe what goes here…", icon: "assistant", run: () => {
      const prev = index > 0 ? list[index - 1] : null, next = list[index] ?? null;
      const where = prev ? `after ${nodeWords(prev)}` : next ? `before ${nodeWords(next)}` : "here";
      asst.open?.({text: `Add ${where}: `});
    }} : null,
  ].filter(Boolean);
  return ui.menu(anchor, items);
}

function moveFlowNode(from, toList, toIndex) {
  if (!bEditable()) return;
  if (pathStartsWith(toList, from)) return toast("Can't move an item into itself");
  const {list: srcList, index: srcIdx} = parentOf(from);
  const node = srcList[srcIdx];
  const dst = getNode(toList);
  srcList.splice(srcIdx, 1);
  let idx = toIndex;
  if (dst === srcList && srcIdx < toIndex) idx -= 1;
  dst.splice(idx, 0, node);
  const dp = pathOfList(dst);
  if (dp) {
    const np = [...dp, idx];
    if (S.sel && S.sel.path && samePath(S.sel.path, from)) S.sel = {...S.sel, path: np};
    else if (S.sel?.path && pathStartsWith(S.sel.path, from)) S.sel = null;
    BUILD.focusKey = (isRoutineNode(node) ? "card:" : "frame:") + np.join(".");
    if (storyDensity() === "list") BUILD.focusKey = "row:" + np.join(".");
  }
  commit(`Move “${nodeName(node)}”`);
  ui.announce(`Moved ${nodeWords(node)}`);
}
function moveNodeBy(path, delta) {
  if (!bEditable()) return;
  const {list, index} = parentOf(path);
  const j = index + delta;
  if (j >= 0 && j < list.length) { moveFlowNode(path, path.slice(0, -1), delta > 0 ? j + 1 : j); return; }
  // at the edge of a trial list, branch lane or phase: step out of it
  const lp = path.slice(0, -1);
  let up = lp.slice(0, -1);
  while (up.length && typeof up[up.length - 1] !== "number") up = up.slice(0, -1);
  if (!up.length) return ui.announce(delta < 0 ? "Already the first step" : "Already the last step");
  const owner = parentOf(up);
  moveFlowNode(path, up.slice(0, -1), owner.index + (delta > 0 ? 1 : 0));
}
function canMoveBy(path, delta) { const {list, index} = parentOf(path); return (index + delta >= 0 && index + delta < list.length) || path.length > 1; }

function nodeMenu(e, path) {
  const n = nodeAt(path); if (n === undefined) return;
  const anchor = e instanceof Element ? e : e;
  const moves = [{label: "Move earlier", icon: "chev-left", shortcut: "Alt ←", disabled: !canMoveBy(path, -1), run: () => moveNodeBy(path, -1)},
    {label: "Move later", icon: "chev-right", shortcut: "Alt →", disabled: !canMoveBy(path, 1), run: () => moveNodeBy(path, 1)}];
  let items;
  if (isRoutineNode(n)) {
    const rid = routineOfNode(n);
    items = [{label: "Open", icon: "screen", shortcut: "Enter", run: () => openScreen(rid)},
      {label: "Rename…", shortcut: "F2", run: () => renameRoutine(rid)},
      {label: "Duplicate", icon: "duplicate", shortcut: "Ctrl D", run: () => duplicateRoutine(rid, path)},
      {sep: true}, ...moves,
      {label: "Repeat with a trial list", icon: "loop", run: () => wrapInLoop(path)},
      {label: n.if ? "Change the condition…" : "Show only if…", icon: "branch", run: () => showOnlyIf(path)},
      n.if ? {label: "Always show it", run: () => { if (!bEditable()) return; const {list, index} = parentOf(path); list[index] = rid; commit(`Always show “${rid}”`); }} : null,
      {sep: true},
      {label: "Remove from the experiment", shortcut: "Delete", run: () => removeFromFlow(path)},
      {label: "Delete screen", icon: "trash", danger: true, run: () => deleteRoutine(rid)}];
  } else if (n.loop !== undefined) {
    items = [{label: "Open list", icon: "table", run: () => openTrialList(path)},
      {label: "Rename…", shortcut: "F2", run: () => renameNode(n, path)},
      {sep: true}, ...moves,
      {label: "Show only if…", icon: "branch", run: () => showOnlyIf(path)},
      {sep: true},
      {label: "Remove the trial list (keep its screens)", run: () => unwrapNode(path)},
      {label: "Remove from the experiment", icon: "trash", danger: true, shortcut: "Delete", run: () => removeFromFlow(path)}];
  } else if (n.statemachine !== undefined) {
    items = [{label: "Open diagram", icon: "workflow", run: () => openDiagram(path)},
      {label: "Add a phase", icon: "plus", run: () => { if (bEditable() && typeof addState === "function") addState(path); }},
      {sep: true}, ...moves,
      {sep: true},
      {label: "Remove from the experiment", icon: "trash", danger: true, shortcut: "Delete", run: () => removeFromFlow(path)}];
  } else {
    items = [{label: "Change the condition…", icon: "branch", run: () => showOnlyIf(path)},
      {sep: true}, ...moves,
      {sep: true},
      {label: "Remove the condition (keep its screens)", run: () => unwrapNode(path)},
      {label: "Remove from the experiment", icon: "trash", danger: true, shortcut: "Delete", run: () => removeFromFlow(path)}];
  }
  return ui.menu(anchor, items.filter(Boolean));
}

function removeFromFlow(path) {
  if (!bEditable()) return;
  const {list, index} = parentOf(path);
  const n = list[index];
  list.splice(index, 1);
  if (S.sel?.path && pathStartsWith(S.sel.path, path)) S.sel = null;
  if (S.sel?.kind === "routine" && isRoutineNode(n) && S.sel.routine === routineOfNode(n) && !S.sel.path) S.sel = null;
  commit(`Remove “${nodeName(n)}” from the experiment`);
  undoToast(isRoutineNode(n) ? `Removed “${routineOfNode(n)}” from the experiment.` : `Removed ${nodeWords(n)} from the experiment.`);
}
function unwrapNode(path) {
  if (!bEditable()) return;
  const {list, index} = parentOf(path);
  const n = list[index];
  const kids = n.loop !== undefined ? (n.children || []) : n.if !== undefined ? [...(n.then || []), ...(n.else || [])] : [];
  list.splice(index, 1, ...kids);
  S.sel = null;
  commit(n.loop !== undefined ? `Remove the trial list “${n.loop}”` : "Remove the condition");
  undoToast(n.loop !== undefined ? `Removed the trial list “${n.loop}”. Its screens stay.` : "Removed the condition. Its screens stay.");
}
function wrapInLoop(path) {
  if (!bEditable()) return;
  const {list, index} = parentOf(path);
  const n = list[index];
  const id = uniqueId("trials", loopIds());
  list[index] = {loop: id, order: "random", repeats: 1, conditions: [{condition: "A"}, {condition: "B"}], children: [n]};
  S.sel = {kind: "loop", path};
  BUILD.focusKey = "frame:" + path.join(".");
  commit(`Repeat “${nodeName(n)}” with a trial list`);
  ui.toast(`Made a trial list “${id}” around “${nodeName(n)}”.`, {action: {label: "Open the list", run: () => openTrialList(path)}});
}
function normFormula(v) { v = String(v || "").trim(); return !v ? "" : v.startsWith("$") ? v : "$" + v; }
/* A formula field with its sentence under it (replaces the old prompt "Run only if…"). */
async function askCondition(title, value) {
  const id = "cond-" + Date.now();
  const input = h("input", {class: "input expr", id, value: value || "", placeholder: "$score > 5", spellcheck: "false", autocomplete: "off"});
  const say = h("div", {class: "help cond-say"});
  const upd = () => { const v = normFormula(input.value); say.textContent = v ? `In words: ${exprInWords(v)}.` : "For example $score > 5, or $practice.accuracy >= 0.8."; };
  input.addEventListener("input", upd); upd();
  const v = await ui.dialog({title, size: "sm", icon: "branch", initialFocus: input,
    body: h("div", {class: "field"}, h("label", {for: id}, "Show it only when"), input, say),
    buttons: [{label: "Cancel", value: null}, {label: "Save condition", value: "ok", kind: "primary"}],
    onOpen: (dlg, close) => input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); close("ok"); } })});
  return v === "ok" ? normFormula(input.value) || null : null;
}
async function showOnlyIf(path) {
  if (!bEditable()) return;
  const n = nodeAt(path);
  const cond = await askCondition(isRoutineNode(n) ? `Show “${routineOfNode(n)}” only if…` : n.if !== undefined && !isRoutineNode(n) ? "Only if…" : `Show ${nodeWords(n)} only if…`,
    typeof n === "object" && n.if ? n.if : "");
  if (!cond) return;
  const cur = nodeAt(path);
  const {list, index} = parentOf(path);
  if (isRoutineNode(cur)) list[index] = {routine: routineOfNode(cur), if: cond};
  else if (cur.if !== undefined && cur.then !== undefined) cur.if = cond;
  else list[index] = {if: cond, then: [cur], else: []};
  commit(`Show ${nodeWords(cur)} only if…`);
}
async function renameNode(n, path) {
  if (isRoutineNode(n)) return renameRoutine(routineOfNode(n));
  if (!bEditable()) return;
  if (n.loop === undefined) return;
  const taken = loopIds(); taken.delete(n.loop);
  const v = await ui.prompt({title: "Rename the trial list", label: "Name", value: n.loop, ok: "Rename", transform: (x) => ui.slug(x),
    validate: (x) => !x ? "Type a name first." : taken.has(x) ? `There is already something called “${x}”.` : null});
  if (!v || v === n.loop) return;
  if (typeof renameLoop === "function") return renameLoop(n, v);     // inspector.js: formulas and measures follow
  const old = n.loop; n.loop = v;
  commit(`Rename the trial list “${old}”`);
}

/* ================================================================== screens and items (kept names) */
function openScreen(rid) {
  if (!S.exp.routines[rid]) return;
  if (S.ws !== "build") EDGE.go("build", {render: false});
  if (S.routine !== rid) S.rowIndex = 0;
  S.routine = rid;
  S.sel = {kind: "routine", routine: rid};
  S.previewT = thumbTime(rid);
  setBuildView("screen", {routine: rid});
  if (S.view === "screen") { const t = $("#preview-t"); if (t) t.value = S.previewT; renderPreview(); }
}
function routineSpan(rid) {
  const r = S.exp.routines[rid];
  let max = numOr(r?.duration, 0);
  for (const c of comps(rid)) max = Math.max(max, numOr(c.start, 0) + numOr(c.duration, 0.5));
  return Math.max(2, Math.ceil(max * 1.15 * 2) / 2);
}
function copyRoutine(rid) {
  const nid = uniqueId(rid, new Set(Object.keys(S.exp.routines)));
  S.exp.routines[nid] = clone(S.exp.routines[rid]);
  return nid;
}
function duplicateRoutine(rid, path) {
  if (!bEditable() || !S.exp.routines[rid]) return;
  const nid = copyRoutine(rid);
  let np = null;
  if (path) { const {list, index} = parentOf(path); list.splice(index + 1, 0, nid); np = [...path.slice(0, -1), index + 1]; }
  else S.exp.flow.push(nid), np = [S.exp.flow.length - 1];
  S.sel = {kind: "routine", routine: nid, path: np};
  BUILD.focusKey = "card:" + np.join(".");
  commit(`Duplicate “${rid}”`);
  toast(`Made a copy: “${nid}”`);
}

async function addComponent(type, at, opts = {}) {
  if (!bEditable()) return null;
  if (!S.routine || !S.exp.routines[S.routine]) { const rid = await newRoutine(); if (!rid) return null; }
  let rid = S.routine;
  let moved = null;
  if ((type === "survey" || type === "html") && comps(rid).length) {
    // a page needs the whole screen: give it its own, right after this one in the flow
    const nid = uniqueId(type === "survey" ? "questionnaire" : "page", new Set(Object.keys(S.exp.routines)));
    S.exp.routines[nid] = {components: []};
    let placed = false;
    walkFlow((n, path) => { if (placed || !isRoutineNode(n) || routineOfNode(n) !== rid) return; const {list, index} = parentOf(path); list.splice(index + 1, 0, nid); placed = true; });
    if (!placed) S.exp.flow.push(nid);
    moved = [rid, nid];
    S.routine = rid = nid; at = undefined;
  }
  const d = S.schema.components[type];
  const base = {keyboard: "resp", device_response: "button", mouse: "click", slider: "rating", image: "picture", fixation: "fixation", html: "page"}[type] || type;
  const c = {id: uniqueId(base, new Set(comps(rid).map((x) => x.id))), type};
  for (const [k, p] of Object.entries(d.props)) if (p.required) c[k] = p.default ?? (p.type === "text" || p.type === "str" ? "" : null);
  if (type === "text") c.text = "Hello";
  if (type === "keyboard") { c.keys = ["space"]; c.end_routine = true; }
  if (type === "device_response") {
    c.end_routine = true;
    const dev = S.exp.devices.find((x) => (S.schema.devices[x.type]?.capabilities || []).includes("input"));
    if (dev) c.device = dev.id;
    else setTimeout(() => ui.toast("Add the button box, TTL input or voice key under Devices, or give keyboard stand-ins in “keys”.",
      {action: {label: "Add device", run: () => openAddDevice()}}), 60);
  }
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
    if (freed.length) setTimeout(() => toast(`${freed.map((x) => `“${x.id}”`).join(", ")} now stay${freed.length === 1 ? "s" : ""} on the screen until the response`), 50);
  }
  Object.assign(c, opts.props || {});
  if (at != null) comps(rid).splice(at, 0, c); else comps(rid).push(c);
  S.sel = {kind: "component", routine: rid, id: c.id};
  if (S.view !== "screen") { S.view = "screen"; S.previewT = thumbTime(rid); EDGE.emit("view", {view: "screen"}); }
  revealCompTime(c);
  BUILD.focusKey = null;
  commit(`Add ${friendlyName(type)}`);
  if (moved) undoToast(`Put “${c.id}” on its own screen after “${moved[0]}”.`);
  if ((opts.picker || !opts.props) && (type === "image" || type === "sound") && typeof openAssetPicker === "function")
    setTimeout(() => openAssetPicker(type === "image" ? "image" : "audio", (v) => { const cc = findComp(rid, c.id); if (cc) setProp(cc, type, v); }), 80);
  return c.id;
}
/* The playhead follows the selection: an item that isn't visible at the current time brings the time to its start. */
function revealCompTime(c) {
  if (!c || typeof c.start === "string" || c.start_after || c.start_if) return;
  const st = numOr(c.start, 0), du = numOr(c.duration, Infinity);
  const t = S.previewT || 0;
  if (t < st || t >= st + du) { S.previewT = Math.round((st + 0.01) * 1000) / 1000; const r = $("#preview-t"); if (r) r.value = S.previewT; }
}
function selectComp(rid, id, render = true) {
  S.routine = rid;
  S.sel = {kind: "component", routine: rid, id};
  revealCompTime(findComp(rid, id));
  if (render) renderAll();
}

/* New screens always enter the flow where they were made (SPEC W3). newRoutine() keeps working with no arguments. */
async function newRoutine(opts = {}) {
  if (typeof opts === "boolean") opts = {render: opts};
  if (!bEditable()) return null;
  const taken = new Set(Object.keys(S.exp.routines));
  const suggest = uniqueId(taken.size ? "screen" : "trial", taken);
  const name = await ui.prompt({title: "New screen", label: "Name", value: suggest, ok: "Add screen",
    placeholder: "e.g. trial, instructions, feedback", help: "A screen is one step of the experiment: instructions, a trial, feedback.",
    transform: (v) => ui.slug(v), validate: (v) => !v ? "Type a name first." : taken.has(v) ? `There is already a screen called “${v}”.` : null});
  if (!name) return null;
  if (S.exp.routines[name]) return null;
  S.exp.routines[name] = {components: []};
  if (opts.path && Array.isArray(nodeAt(opts.path))) nodeAt(opts.path).splice(opts.index ?? nodeAt(opts.path).length, 0, name);
  else if (opts.at !== "none") S.exp.flow.push(name);
  S.routine = name; S.sel = {kind: "routine", routine: name}; S.previewT = 0; S.rowIndex = 0;
  if (S.ws !== "build") EDGE.go("build", {render: false});
  if (S.view !== "screen") { S.view = "screen"; EDGE.emit("view", {view: "screen"}); }
  if (opts.render !== false) commit(`Add screen “${name}”`);
  return name;
}

async function renameRoutine(rid) {
  if (!bEditable() || !S.exp.routines[rid]) return;
  const taken = new Set(Object.keys(S.exp.routines)); taken.delete(rid);
  const nid = await ui.prompt({title: "Rename screen", label: "Name", value: rid, ok: "Rename", transform: (v) => ui.slug(v),
    validate: (v) => !v ? "Type a name first." : taken.has(v) ? `There is already a screen called “${v}”.` : null});
  if (!nid || nid === rid || !S.exp.routines[rid]) return;
  const r = {}; for (const [k, v] of Object.entries(S.exp.routines)) r[k === rid ? nid : k] = v;
  S.exp.routines = r;
  walkFlow((n, path) => {
    const {list, index} = parentOf(path);
    if (n === rid) list[index] = nid; else if (n && n.routine === rid) n.routine = nid;
  });
  if (S.routine === rid) S.routine = nid;
  if (S.sel?.routine === rid) S.sel = {...S.sel, routine: nid};
  commit(`Rename screen “${rid}”`);
}

function deleteRoutine(rid) {
  if (!bEditable() || !S.exp.routines[rid]) return;
  delete S.exp.routines[rid];
  const prune = (list) => { for (let i = list.length - 1; i >= 0; i--) { const n = list[i];
    if (isRoutineNode(n) && routineOfNode(n) === rid) list.splice(i, 1);
    else if (n && typeof n === "object") { if (n.children) prune(n.children); if (n.then) prune(n.then); if (n.else) prune(n.else);
      if (n.states) for (const st of Object.values(n.states)) if (st.run) prune(st.run); } } };
  prune(S.exp.flow);
  if (S.routine === rid) S.routine = routineInFlowOrder()[0] || Object.keys(S.exp.routines)[0] || null;
  if (S.sel?.routine === rid) S.sel = null;
  if (S.view === "screen" && !S.routine) S.view = "story";
  commit(`Delete screen “${rid}”`);
  undoToast(`Deleted “${rid}”.`);
}

/* ================================================================== trial-list rows (preview values, the row stepper) */
function factorialRows(spec) {
  const f = spec.factorial || {};
  const names = Object.keys(f);
  let rows = [{}];
  for (const k of names) { const lv = Array.isArray(f[k]) ? f[k] : [f[k]]; rows = rows.flatMap((r) => lv.map((v) => ({...r, [k]: v}))); }
  const extra = spec.extra && typeof spec.extra === "object" ? spec.extra : {};
  return rows.map((r) => ({...r, ...extra}));
}
/* Rows of a trial list: an array, or null while a file is loading (re-renders when it arrives). */
function loopRows(spec, path = S.path) {
  if (!spec) return [];
  if (Array.isArray(spec)) return spec.filter((r) => r && typeof r === "object");
  if (spec.factorial) return factorialRows(spec);
  const key = JSON.stringify(spec) + "|" + (path || "");
  const have = BUILD.rows[key];
  if (Array.isArray(have)) return have;
  if (have && have.error && Date.now() - (have.at || 0) < 3000) return [];
  if (have === undefined || (have && have.error)) {       // a file that was missing may have been added since
    BUILD.rows[key] = null;
    api(`/api/conditions?spec=${encodeURIComponent(JSON.stringify(spec))}&exp=${encodeURIComponent(path || "")}`)
      .then((j) => { BUILD.rows[key] = j.rows || []; scheduleBuildRender(); if (typeof renderPreview === "function" && S.view === "screen") renderPreview();
        if (typeof renderProps === "function" && S.ws === "build") renderProps(); })     // value sources: "from the trial list"
      .catch((e) => { BUILD.rows[key] = {error: e.message, at: Date.now()}; scheduleBuildRender(); });
  }
  return null;
}
function loopRowsError(spec, path = S.path) { const v = BUILD.rows[JSON.stringify(spec) + "|" + (path || "")]; return v && v.error ? v.error : null; }
/* Kept for inspector.js: the first row of a trial list ({} while a file loads). */
function firstRow(spec) { const rows = loopRows(spec); return (rows && rows[0]) || {}; }
function loopRowsFor(lp, path) {
  if (lp.staircase) return [{[lp.staircase.variable || "level"]: lp.staircase.start}];
  return loopRows(lp.conditions, path);
}
/* Values for the preview: every trial list around the screen (the innermost one at row `index`), plus the variables. */
function sampleRowFor(rid, index = S.rowIndex || 0, doc = S.exp, path = S.path) {
  const loops = loopsAround(rid, doc);
  let row = {};
  loops.forEach((lp, i) => {
    const fileList = typeof lp.conditions === "string" || typeof lp.conditions?.file === "string";
    const rows = (doc !== S.exp && !path && fileList) ? [] : loopRowsFor(lp, path) || [];
    const k = i === loops.length - 1 ? Math.min(Math.max(0, index), Math.max(0, rows.length - 1)) : 0;
    row = {...row, ...(rows[k] || {})};
  });
  return {...(doc.variables || {}), ...row};
}
function rowInfo(rid) {
  const loops = loopsAround(rid);
  if (!loops.length) return null;
  const lp = loops[loops.length - 1];
  const rows = loopRowsFor(lp);
  if (!rows) return {loop: lp, rows: null, count: 0};
  return {loop: lp, rows, count: rows.length};
}
function stepRow(delta) {
  const info = rowInfo(S.routine);
  if (!info || !info.count) return;
  S.rowIndex = Math.min(info.count - 1, Math.max(0, (S.rowIndex || 0) + delta));
  renderPreview(); renderTimelineHead();
  if (typeof renderProps === "function") renderProps();
  ui.announce(`Row ${S.rowIndex + 1} of ${info.count}`);
}
function renderRowStepper() {
  const el = $("#row-stepper"); if (!el) return;
  const info = S.view === "screen" && S.routine ? rowInfo(S.routine) : null;
  if (!info || !info.count) { el.replaceChildren(); el.hidden = true; return; }
  el.hidden = false;
  const i = Math.min(S.rowIndex || 0, info.count - 1);
  if (el.dataset.sig === `${info.loop.loop}:${i}:${info.count}` && el.childElementCount) return;
  el.dataset.sig = `${info.loop.loop}:${i}:${info.count}`;
  el.replaceChildren(h("span", {class: "rs-lbl"}, "Row"),
    iconBtn("chev-left", "Previous trial-list row (Ctrl+[)", () => stepRow(-1), "btn ghost icon sm", {disabled: i <= 0 ? "" : null}),
    h("span", {class: "rs-n mono", "aria-live": "polite"}, `${i + 1} of ${info.count}`),
    iconBtn("chev-right", "Next trial-list row (Ctrl+])", () => stepRow(1), "btn ghost icon sm", {disabled: i >= info.count - 1 ? "" : null}));
}

/* ================================================================== preview: drawing a screen */
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
  if (!S.exp) return;
  const t = S.previewT || 0;
  const lbl = $("#preview-label"); if (lbl) lbl.textContent = `${t.toFixed(2)} s`;
  const range = $("#preview-t"); if (range && document.activeElement !== range) range.value = t;
  // web pages and surveys are previewed live in an iframe on top of the canvas
  const frame = $("#preview-html");
  const page = comps(S.routine).find((c) => (c.type === "html" || c.type === "survey") && numOr(c.start, 0) <= t && (c.duration == null || t < numOr(c.start, 0) + c.duration));
  if (page && page.type === "survey") {
    const html = typeof surveyPreviewHtml === "function" ? surveyPreviewHtml(page, renderPreview) : null;
    if (html && frame.dataset.survey !== html.length + ":" + html.slice(-200)) { frame.removeAttribute("src"); frame.dataset.src = ""; frame.srcdoc = html; frame.dataset.survey = html.length + ":" + html.slice(-200); }
    frame.classList.remove("hidden");
  } else if (page && (page.file || page.html)) {
    frame.dataset.survey = "";
    if (page.file && !isExpr(page.file)) {
      const rel = (S.path ? S.path.replace(/[^/]*$/, "") : "") + page.file;
      // {{name}} placeholders show this trial's values, as participants see them (participant: an example id)
      const vals = {participant: "001", session: "1", ...sampleRowFor(S.routine)};
      const key = rel + "|" + JSON.stringify(vals);
      if (frame.dataset.src !== key) {      // by path, so the page's own stylesheets, scripts and pictures load
        frame.dataset.src = key; frame.removeAttribute("srcdoc");
        frame.src = pageUrl(rel);
        fetch(pageUrl(rel)).then((r) => (r.ok ? r.text() : null)).then((txt) => {
          if (!txt || frame.dataset.src !== key || !/\{\{\s*[\w.]+\s*\}\}/.test(txt)) return;
          const esc = (v) => String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
          const html = txt.replace(/\{\{\s*([\w.]+)\s*\}\}/g, (m, k) => (vals[k] !== undefined && vals[k] !== null ? esc(vals[k]) : m));
          const tag = `<base href="${pageUrl(rel.replace(/[^/]*$/, ""))}">`;
          frame.removeAttribute("src");
          frame.srcdoc = /<base\b/i.test(html) ? html : /<head\b[^>]*>/i.test(html) ? html.replace(/<head\b[^>]*>/i, (m) => m + tag) : tag + html;
        }).catch(() => { /* the page as it is */ });
      }
    } else if (page.html) {
      const doc = pageWithBase(page.html);
      if (frame.srcdoc !== doc || frame.dataset.src) { frame.dataset.src = ""; frame.removeAttribute("src"); frame.srcdoc = doc; }
    }
    frame.classList.remove("hidden");
  } else frame.classList.add("hidden");
  const cv = $("#preview");
  if (!cv || S.view !== "screen" || $("#view-screen")?.hidden) return;
  fitPreview(cv);
  const want = Math.round((cv.clientWidth || 480) * Math.min(2, window.devicePixelRatio || 1));
  if (cv.width !== want) cv.width = want;
  if (S.routine && S.exp.routines[S.routine]) drawScreen(cv, S.routine, t);
  else { const ctx = cv.getContext("2d"); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.fillStyle = (S.exp.settings.window || {}).background || "#000"; ctx.fillRect(0, 0, cv.width, cv.height); }
  if (typeof drawStageOverlay === "function") drawStageOverlay(cv);
  renderRowStepper();
  if (typeof renderStageChrome === "function") renderStageChrome(cv);
  updatePlayhead();
}

/* A page of the experiment by its path (/api/page/<key>/<folder>/<file>, S.pageBase from /api/files): its relative
 * links resolve inside the experiment folder. The builder serves it sandboxed (no origin): it can't call the API. */
function pageUrl(rel) { return (S.pageBase || "/api/page/-/") + String(rel).split("/").map(encodeURIComponent).join("/"); }
/* A page written inline (html:) gets a <base> in the experiment folder, so its relative links resolve there too. */
function pageWithBase(html) {
  if (!S.path || /<base\b/i.test(html)) return html;
  const tag = `<base href="${pageUrl(S.path.replace(/[^/]*$/, ""))}">`;
  return /<head\b[^>]*>/i.test(html) ? html.replace(/<head\b[^>]*>/i, (m) => m + tag) : /^\s*<!doctype[^>]*>/i.test(html) ? html.replace(/^\s*<!doctype[^>]*>/i, (m) => m + tag) : tag + html;
}

/* The stage sits above the timeline: the preview is sized to fit the stage's width and height. */
function fitPreview(cv) {
  const stack = cv.parentElement, wrap = $("#preview-wrap");
  if (!wrap || !wrap.clientWidth || !stack) return;
  const cs = getComputedStyle(wrap);
  const others = [...wrap.children].filter((c) => c !== stack && c.offsetParent !== null && getComputedStyle(c).position !== "absolute");
  const gap = parseFloat(cs.rowGap) || 0;
  const availW = wrap.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const availH = wrap.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)
    - others.reduce((a, c) => a + c.offsetHeight, 0) - gap * others.length;
  const [W, H] = (S.exp.settings.window || {}).size || [1280, 720];
  const k = Math.max(0.02, Math.min(availW / W, availH / H));
  const w = Math.max(64, Math.floor(W * k)), hh = Math.max(36, Math.floor(H * k));
  stack.style.width = w + "px"; stack.style.height = hh + "px";
  cv.style.width = w + "px"; cv.style.height = hh + "px";
}

/* Draw one screen at time t onto a canvas. opts: {doc, row, path, minText} (doc defaults to the open experiment;
 * minText is the smallest text size in canvas pixels, for thumbnails). The old 4th argument (a row object) still works. */
function drawScreen(cv, rid, t, opts = {}) {
  if (opts && Object.keys(opts).length && !("doc" in opts || "row" in opts || "minText" in opts || "path" in opts)) opts = {row: opts};
  opts = opts || {};
  const doc = opts.doc || S.exp;
  const base = opts.path !== undefined ? opts.path : S.path;
  const ctx = cv.getContext("2d");
  const win = doc.settings?.window || {};
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
  const row = opts.row || sampleRowFor(rid, undefined, doc, base);
  const minPx = opts.minText ? opts.minText / k : 0;
  cv._boxes = []; cv._k = k; cv._W = W; cv._H = H;
  const box = (c, hw, hh) => cv._boxes.push({id: c.id, type: c.type, x: pos(c.pos || [0, 0])[0], y: pos(c.pos || [0, 0])[1], hw, hh, rot: numOr(c.ori, 0), units});
  for (const c0 of doc.routines?.[rid]?.components || []) {
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
        const m = c.text.match(/^\$\s*(['"])(.*?)\1\s+if\b/) || c.text.match(/^\$\s*f?(['"])((?:(?!\1).)*)\1\s*$/);
        c.text = m ? m[2].replace(/\{[^}]*\}/g, "…") : (cv.id === "preview" ? c.text : "…");
      }
      ctx.scale(1, -1); ctx.fillStyle = color(c.color, "#fff");
      const hgt = Math.max(conv(numOr(c.height, 40), "y"), minPx);
      ctx.font = `${c.bold ? "bold " : ""}${hgt}px sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.direction = c.direction === "rtl" || (c.direction !== "ltr" && /[֐-׿יִ-ﭏ]/.test(String(c.text ?? ""))) ? "rtl" : "ltr";
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
    } else if (c.type === "image" && typeof c.image === "string" && c.image && !isExpr(c.image) && (base || !opts.doc)) {
      const img = imgCache(c.image, base);
      if (img.complete && img.naturalWidth) { const sz = Array.isArray(c.size) ? [conv(c.size[0], "x"), conv(c.size[1], "y")] : [img.naturalWidth, img.naturalHeight];
        ctx.scale(1, -1); ctx.drawImage(img, -sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); box(c, sz[0] / 2, sz[1] / 2); }
      else { ctx.strokeStyle = "#888"; ctx.strokeRect(-100, -75, 200, 150); box(c, 100, 75); }
    } else if (c.type === "image") {
      ctx.strokeStyle = "#888"; ctx.setLineDash([6, 4]); ctx.strokeRect(-100, -75, 200, 150);
      ctx.scale(1, -1); ctx.fillStyle = "#888"; ctx.font = `${Math.max(22, minPx)}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(c.image ? "picture from the trial list" : "no picture yet", 0, 0); box(c, 100, 75);
    } else if (c.type === "slider") {
      const sz = Array.isArray(c.size) ? c.size : [800, 30]; ctx.fillStyle = color(c.color, "#fff");
      ctx.fillRect(-sz[0] / 2, -2, sz[0], 4); box(c, sz[0] / 2, Math.max(10, sz[1] / 2));
    } else if (c.type === "survey" && cv.id !== "preview") {
      ctx.scale(1, -1); ctx.fillStyle = "#f7f8fa"; ctx.fillRect(-W * 0.32, -H * 0.4, W * 0.64, H * 0.8);
      ctx.fillStyle = "#2f6fde"; ctx.fillRect(-W * 0.28, -H * 0.33, W * 0.3, H * 0.025);
      for (let q = 0; q < 4; q++) { ctx.fillStyle = "#fff"; ctx.fillRect(-W * 0.28, -H * 0.27 + q * H * 0.15, W * 0.56, H * 0.12);
        ctx.fillStyle = "#c5ccd6"; for (let j = 0; j < 5; j++) { ctx.beginPath(); ctx.arc(-W * 0.12 + j * W * 0.08, -H * 0.2 + q * H * 0.15, H * 0.018, 0, 7); ctx.fill(); } }
    } else if (c.type === "html" && cv.id !== "preview") {
      ctx.scale(1, -1); ctx.fillStyle = "#fff"; ctx.fillRect(-W * 0.3, -H * 0.35, W * 0.6, H * 0.7);
      ctx.fillStyle = "#c5ccd6"; for (let j = 0; j < 5; j++) ctx.fillRect(-W * 0.24, -H * 0.24 + j * H * 0.1, W * (j % 2 ? 0.34 : 0.48), H * 0.035);
    } else if (c.type === "sound") {
      // a speaker with two waves (no glyphs: the preview must not depend on fonts)
      ctx.scale(1, -1); ctx.translate(0, -H * 0.3); const s = H * 0.06;
      ctx.fillStyle = "#9ab"; ctx.strokeStyle = "#9ab"; ctx.lineWidth = s * 0.18;
      ctx.beginPath(); ctx.moveTo(-s, -s * 0.4); ctx.lineTo(-s * 0.45, -s * 0.4); ctx.lineTo(s * 0.1, -s); ctx.lineTo(s * 0.1, s); ctx.lineTo(-s * 0.45, s * 0.4); ctx.lineTo(-s, s * 0.4); ctx.closePath(); ctx.fill();
      for (const rr of [0.55, 0.95]) { ctx.beginPath(); ctx.arc(s * 0.1, 0, s * rr, -0.8, 0.8); ctx.stroke(); }
    } else if (c.type === "gaze_roi" && !c.target) {
      ctx.strokeStyle = "#a070ff"; ctx.setLineDash([8, 6]); ctx.lineWidth = 2;
      if ((c.shape || "circle") === "circle") { const r = conv(numOr(c.radius, 100), "y"); ctx.beginPath(); ctx.arc(0, 0, r, 0, 2 * Math.PI); ctx.stroke(); box(c, r, r); }
      else { const sz = Array.isArray(c.size) ? [conv(c.size[0], "x"), conv(c.size[1], "y")] : [200, 200]; ctx.strokeRect(-sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); box(c, sz[0] / 2, sz[1] / 2); }
    }
    ctx.restore();
  }
}
const _imgs = {};
function imgCache(src, base = S.path) {
  const key = (base || "") + "|" + src;
  if (!_imgs[key]) {
    const im = new Image();
    im.onload = () => { BUILD.imgGen++; if (S.view === "screen") renderPreview(); scheduleBuildRender(); };
    im.src = `/api/file?path=${encodeURIComponent((base ? base.replace(/[^/]*$/, "") : "") + src)}`;
    _imgs[key] = im;
  }
  return _imgs[key];
}
/* A thumbnail of any experiment: its first screen in flow order at its main moment (Home, the wizard, examples).
 * Pass {path} (the experiment's file) so its pictures and file-based trial lists can be found. */
function drawThumbnail(doc, canvas, {rid = null, path = null, row = null, minText = 18} = {}) {
  if (!doc || !canvas) return null;
  doc = normalize(clone(doc));
  if (!rid) {
    const walk = (nodes) => { for (const n of nodes || []) { if (rid) return; if (isRoutineNode(n)) { if (doc.routines[routineOfNode(n)]) rid = routineOfNode(n); }
      else if (n && typeof n === "object") { walk(n.children); walk(n.then); walk(n.else); for (const st of Object.values(n.states || {})) walk(st.run); } } };
    walk(doc.flow);
    rid ||= Object.keys(doc.routines)[0] || null;
  }
  if (!canvas.width || canvas.width === 300) canvas.width = Math.round((canvas.clientWidth || 216) * 2);
  if (!rid) { const ctx = canvas.getContext("2d"); ctx.fillStyle = (doc.settings.window || {}).background || "#000"; ctx.fillRect(0, 0, canvas.width, canvas.height); return null; }
  try { drawScreen(canvas, rid, thumbTime(rid, doc), {doc, path, row: row || sampleRowFor(rid, 0, doc, path), minText}); } catch (e) { /* best effort */ }
  return rid;
}

/* ---------------- play the preview at real speed */
let _play = null;
function playPreview() {
  const b = $("#preview-play");
  const show = (playing) => { if (!b) return; b.replaceChildren(icon(playing ? "pause" : "play")); b.setAttribute("aria-label", playing ? "Pause" : "Play this screen"); b.dataset.tip = playing ? "Pause (Space)" : "Play this screen at real speed (Space)"; };
  if (_play) { cancelAnimationFrame(_play.raf); _play = null; show(false); return; }
  if (!S.routine) return;
  const span = routineSpan(S.routine);
  const t0 = performance.now() - ((S.previewT || 0) >= span - 0.02 ? 0 : (S.previewT || 0) * 1000);
  show(true);
  const step = () => {
    if (S.view !== "screen" || S.ws !== "build") { _play = null; show(false); return; }
    S.previewT = Math.min(span, (performance.now() - t0) / 1000);
    renderPreview();
    if (S.previewT >= span) { _play = null; show(false); return; }
    _play.raf = requestAnimationFrame(step);
  };
  _play = {raf: requestAnimationFrame(step)};
}

/* ================================================================== the timeline (SPEC W4) */
function timelineSource(c) {
  const bits = [friendlyName(c.type)];
  const main = {text: c.text, image: c.image, sound: c.sound, html: c.file}[c.type];
  if (isExpr(main)) { const m = String(main).match(/^\$([A-Za-z_]\w*)$/); bits.push(m ? `from “${m[1]}”` : "computed"); }
  else if (c.type === "text" && typeof c.text === "string") bits.push(`“${short(c.text.replace(/\s+/g, " "), 24)}”`);
  else if (c.type === "keyboard" && Array.isArray(c.keys)) bits.push(c.keys.join(" / "));
  if (c.end_routine) bits.push("ends the screen");
  if (c.type === "variable" && c.when === "end") bits.push("at the end");
  if (c.if) bits.push("only sometimes");
  return bits.join(" · ");
}
function timelineAria(c) {
  const st = typeof c.start === "number" ? `starts at ${c.start} seconds` : c.start == null ? "starts at the beginning" : "starts on a formula";
  const du = typeof c.duration === "number" ? `lasts ${c.duration} seconds` : "until the screen ends";
  return `${c.id}, ${friendlyName(c.type)}, ${st}, ${du}${c.end_routine ? ", ends the screen" : ""}`;
}
function renderTimeline() {
  if (S.view !== "screen") { updateBuildEst(); return; }   // P1 calls this when the estimate arrives; other views render elsewhere
  const el = $("#timeline"); if (!el || !S.exp) return;
  el.classList.add("timeline");
  const rid = S.routine;
  keepFocus(el, () => {
    if (!rid || !S.exp.routines[rid]) {
      el.replaceChildren(emptyState("screen", "No screen is open", "Pick a screen in the storyboard, or add one.", [btn("Add a screen", () => newRoutine(), {cls: "btn primary", ic: "plus"})]));
      return;
    }
    const span = routineSpan(rid);
    const range = $("#preview-t"); if (range) range.max = span;
    const head = h("div", {class: "tl-head"});
    const grid = h("div", {class: "tl-grid"});
    const ruler = h("div", {class: "tl-ruler", "aria-hidden": "true"}, h("span", {class: "tl-ruler-lbl"}));
    const ticks = h("div", {class: "ticks"});
    const step = span > 12 ? 2 : span > 4 ? 1 : 0.5;
    for (let t = 0; t <= span + 1e-9; t += step) {
      const last = t + step > span + 1e-9;
      ticks.append(h("span", {style: `left:${(t / span) * 100}%`}, (step < 1 ? t.toFixed(1) : String(t)) + (last ? " s" : "")));
    }
    ruler.append(ticks);
    const body = h("div", {class: "tl-body", role: "list", "aria-label": `Items on “${rid}”`});
    const list = comps(rid);
    list.forEach((c, idx) => body.append(timelineRow(rid, c, idx, span)));
    if (!list.length) {
      const a = buildAssistant();
      body.append(h("div", {class: "tl-empty"}, h("span", {}, "Nothing on this screen yet."),
        a ? btn("Describe this screen", () => a.open?.({text: `On the screen “${rid}”, show `}), {cls: "btn sm assistant-outline", ic: "assistant"}) : null));
    }
    body.append(h("div", {class: "tl-playhead", "aria-hidden": "true"}));
    const r = S.exp.routines[rid];
    const nRules = (r.rules || []).length;
    const rules = h("div", {class: "tl-rules"}, icon("rules"),
      h("button", {type: "button", class: "linkish", onclick: () => { EDGE.select({kind: "routine", routine: rid}, {pulse: true}); }}, `Rules (${nRules})`),
      h("span", {class: "t-caption"}, "react while the screen runs"),
      btn("Add a rule", () => { EDGE.select({kind: "routine", routine: rid}, {pulse: true}); }, {cls: "btn sm ghost", ic: "plus"}));
    put(grid, ruler, body, (nRules || !isSimple() || list.length) ? rules : null);
    body.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("edge/component")) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
    body.addEventListener("drop", (e) => { const type = e.dataTransfer.getData("edge/component"); if (!type) return; e.preventDefault(); e.stopPropagation(); addComponent(type); });
    el.replaceChildren(head, grid);
    renderTimelineHead();
  });
  updatePlayhead();
}
function renderTimelineHead() {
  const head = $("#timeline .tl-head"); if (!head || !S.routine || !S.exp.routines[S.routine]) return;
  const text = describeRoutine(S.routine);
  const say = h("button", {type: "button", class: "say" + (BUILD.sayOpen ? " open" : ""), "aria-expanded": BUILD.sayOpen ? "true" : "false",
    title: isSimple() ? `With the formulas: ${describeRoutine(S.routine, {plain: false})}` : (BUILD.sayOpen ? "" : text),
    onclick: () => { BUILD.sayOpen = !BUILD.sayOpen; renderTimelineHead(); }}, h("b", {}, "In words: "), text);
  const add = h("button", {type: "button", class: "btn sm ghost", "data-fkey": "tl-add", title: "Add an item at the playhead (/)", onclick: (e) => quickAdd(e.currentTarget)},
    icon("plus"), "Add", h("span", {class: "kbd"}, "/"));
  head.replaceChildren(say, add);
  const cv = $("#preview"); if (cv) cv.setAttribute("aria-label", `Preview of “${S.routine}” at ${(S.previewT || 0).toFixed(2)} s: ${text}`);
}
function timelineRow(rid, c, idx, span) {
  const cat = catKey(c.type);
  const sel = S.sel?.kind === "component" && S.sel.routine === rid && S.sel.id === c.id;
  const r = S.exp.routines[rid];
  const start = numOr(c.start, 0);
  const conditional = isExpr(c.start) || !!c.start_after || !!c.start_if || c.start_frame != null || !!c.if;
  const open = c.duration == null && c.duration_frames == null;
  const dur = open ? (numOr(r.duration, span) - start) : numOr(c.duration, (c.duration_frames || 30) / 60);
  const mark = proposalMark("components", `${rid}/${c.id}`);
  const key = `tl:${rid}:${c.id}`;
  const label = h("button", {type: "button", class: "tl-label", "data-fkey": key, "aria-label": timelineAria(c), "aria-pressed": sel ? "true" : "false",
    title: c.id, onclick: () => selectComp(rid, c.id)},
  icon(typeIcon(c.type), "c-" + cat), h("b", {}, c.id), h("span", {}, timelineSource(c)), mark ? markBadge(mark) : null);
  const bar = h("button", {type: "button", class: `tl-bar bg-${cat}` + (open ? " open" : "") + (conditional ? " cond" : "") + (c.end_routine ? " ends" : ""),
    "data-fkey": "bar:" + key, tabindex: "-1", "aria-label": timelineAria(c) + ". Arrow keys move it; Alt+arrows change its length.",
    style: `left:${(start / span) * 100}%;width:${Math.max(0.6, (Math.max(0.02, dur) / span) * 100)}%`,
    title: `${c.id}: from ${fmtS(start)}${open ? " until the screen ends" : ` for ${fmtS(dur)}`}`},
  h("span", {class: "h", "aria-hidden": "true"}));
  bar.addEventListener("mousedown", (e) => dragBar(e, c, bar.parentElement, span, e.target.classList.contains("h") ? "resize" : "move"));
  bar.addEventListener("click", (e) => e.preventDefault());
  for (const x of [label, bar]) x.addEventListener("keydown", (e) => timelineKeys(e, rid, c, x));
  const track = h("div", {class: "tl-track"}, bar);
  const row = h("div", {class: "tl-row" + (sel ? " sel" : "") + (mark ? " pv-row-" + mark : ""), role: "listitem", "data-idx": idx}, label, track);
  row.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("edge/component")) { e.preventDefault(); e.stopPropagation(); row.classList.add("drop-after"); } });
  row.addEventListener("dragleave", () => row.classList.remove("drop-after"));
  row.addEventListener("drop", (e) => { const type = e.dataTransfer.getData("edge/component"); if (!type) return;
    e.preventDefault(); e.stopPropagation(); row.classList.remove("drop-after"); addComponent(type, idx + 1); });
  return row;
}
let _tlNudge = null;
function timelineKeys(e, rid, c, el) {
  const list = comps(rid);
  const idx = list.findIndex((x) => x.id === c.id);
  const isBar = el.classList.contains("tl-bar");
  const mod = e.ctrlKey || e.metaKey;
  const done = () => { e.preventDefault(); e.stopPropagation(); };
  if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !mod) {
    done();
    if (!bEditable()) return;
    const sign = e.key === "ArrowRight" ? 1 : -1, stepv = e.shiftKey ? 0.5 : 0.05;
    if (e.altKey) {
      const span = routineSpan(rid);
      const cur = typeof c.duration === "number" ? c.duration : Math.max(0.05, span - numOr(c.start, 0));
      c.duration = Math.max(0.05, Math.round((cur + sign * stepv) * 1000) / 1000);
    } else {
      if (isExpr(c.start) || c.start_after || c.start_if) return toast("This item starts on a formula or another item: change it in the panel on the right.");
      c.start = Math.max(0, Math.round((numOr(c.start, 0) + sign * stepv) * 1000) / 1000);
    }
    S.sel = {kind: "component", routine: rid, id: c.id};
    revealCompTime(c);
    BUILD.focusKey = el.dataset.fkey;
    if (!_tlNudge) _tlNudge = {};
    clearTimeout(_tlNudge.t);
    _tlNudge.t = setTimeout(() => { _tlNudge = null; commit(`Change the timing of “${c.id}”`); }, 450);
    renderTimeline(); renderPreview();
    ui.announce(`${c.id}: starts at ${numOr(c.start, 0)} s${typeof c.duration === "number" ? `, lasts ${c.duration} s` : ""}`);
    return;
  }
  if ((e.key === "ArrowUp" || e.key === "ArrowDown") && e.altKey) {
    done();
    if (!bEditable()) return;
    const j = idx + (e.key === "ArrowDown" ? 1 : -1);
    if (j < 0 || j >= list.length) return;
    [list[idx], list[j]] = [list[j], list[idx]];
    BUILD.focusKey = el.dataset.fkey;
    commit(`Move “${c.id}” ${e.key === "ArrowDown" ? "down" : "up"} in the drawing order`);
    return;
  }
  if ((e.key === "ArrowUp" || e.key === "ArrowDown") && !mod) {
    done();
    const rows = [...document.querySelectorAll(`#timeline .${isBar ? "tl-bar" : "tl-label"}`)];
    const t = rows[rows.indexOf(el) + (e.key === "ArrowDown" ? 1 : -1)];
    t?.focus();
    return;
  }
  if (e.key === "Enter") {
    done();
    if (!(S.sel?.kind === "component" && S.sel.id === c.id)) selectComp(rid, c.id);
    setTimeout(() => {
      // the first selector that matches, in this order (a selector list would return the first field in the panel)
      const f = ['#props [data-prop="start"] input', '#props [data-prop="start"] [tabindex]', "#props input"].map((q) => $(q)).find(Boolean);
      f?.focus();
    }, 0);
    return;
  }
  if (e.key === "Delete" || e.key === "Backspace") {
    done();
    if (!bEditable()) return;
    list.splice(idx, 1);
    S.sel = {kind: "routine", routine: rid};
    commit(`Delete “${c.id}”`);
    undoToast(`Deleted “${c.id}”.`);
    return;
  }
  if (mod && e.key.toLowerCase() === "d") {
    done();
    if (!bEditable()) return;
    const copy = clone(c); copy.id = uniqueId(c.id, new Set(list.map((x) => x.id)));
    list.splice(idx + 1, 0, copy);
    S.sel = {kind: "component", routine: rid, id: copy.id};
    BUILD.focusKey = `tl:${rid}:${copy.id}`;
    commit(`Duplicate “${c.id}”`);
    return;
  }
  if (e.key === "F2") {
    done();
    renameItem(rid, c);
    return;
  }
  if (e.key === "Escape") { done(); S.sel = {kind: "routine", routine: rid}; renderAll(); }
}
async function renameItem(rid, c) {
  if (!bEditable()) return;
  const taken = new Set(comps(rid).map((x) => x.id)); taken.delete(c.id);
  const v = await ui.prompt({title: `Rename “${c.id}”`, label: "Name", value: c.id, ok: "Rename", transform: (x) => ui.slug(x),
    validate: (x) => !x ? "Type a name first." : taken.has(x) ? `There is already an item called “${x}” on this screen.` : null});
  if (!v || v === c.id) return;
  if (typeof renameComp === "function") renameComp(c, v);
  else { c.id = v; S.sel = {kind: "component", routine: rid, id: v}; commit(`Rename “${v}”`); }
}
function dragBar(e, c, track, span, mode) {
  if (e.button !== 0) return;
  e.preventDefault(); e.stopPropagation();
  if (S.proposal) return bEditable();
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
    revealCompTime(c);
    renderTimeline(); renderPreview();
  };
  const onUp = () => {
    document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp);
    BUILD.focusKey = `bar:tl:${S.routine}:${c.id}`;
    if (moved) commit(`Change the timing of “${c.id}”`); else renderAll();
  };
  document.addEventListener("mousemove", onMove); document.addEventListener("mouseup", onUp);
}
function updatePlayhead() {
  const ph = $("#timeline .tl-playhead"); if (!ph || !S.routine) return;
  const span = routineSpan(S.routine);
  const f = Math.max(0, Math.min(1, (S.previewT || 0) / span));
  ph.style.left = `calc(var(--tl-label-w) + (100% - var(--tl-label-w) - var(--sp-8)) * ${f})`;
}

/* ---------------- the flow strip (Screen view, SPEC W4) */
function renderFlowStrip() {
  const el = $("#flowstrip"); if (!el || !S.exp) return;
  const show = currentBuildView() === "screen";
  el.hidden = !show;
  if (!show) return;
  if (!el._wired) {
    el._wired = true;
    el.setAttribute("role", "navigation");
    el.setAttribute("aria-label", "The experiment's order");
    el.addEventListener("scroll", () => stripFades(el), {passive: true});
    el.addEventListener("wheel", (e) => { if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && el.scrollWidth > el.clientWidth) { el.scrollLeft += e.deltaY; e.preventDefault(); } }, {passive: false});
  }
  keepFocus(el, () => {
    const out = [stripIns([], 0, "Add a step at the start")];
    stripNodes(S.exp.flow, [], out);
    if (!S.exp.flow.length) out.push(h("span", {class: "t-caption fs-empty"}, "The experiment is empty"));
    out.push(stripIns([], S.exp.flow.length, "Add a step at the end"));
    el.replaceChildren(...out);
  });
  const on = el.querySelector(".fs-node.on");
  if (on) { const r = on.getBoundingClientRect(), b = el.getBoundingClientRect(); if (r.left < b.left || r.right > b.right) el.scrollLeft += r.left - b.left - b.width / 2 + r.width / 2; }
  stripFades(el);
}
function stripFades(el) {
  el.classList.toggle("fade-l", el.scrollLeft > 2);
  el.classList.toggle("fade-r", el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
}
function stripIns(listPath, index, label) {
  return h("button", {type: "button", class: "ins", "data-fkey": `fsins:${listPath.join(".")}:${index}`, "aria-label": label, title: label,
    onclick: (e) => flowInsertMenu(e.currentTarget, listPath, index)}, icon("plus"));
}
function stripNodes(nodes, path, out) {
  (nodes || []).forEach((n, i) => {
    const p = [...path, i];
    if (i > 0) out.push(icon("chev-right", "fs-sep"));
    if (isRoutineNode(n)) {
      const rid = routineOfNode(n);
      const on = rid === S.routine;
      const mark = proposalMark("routines", rid);
      const key = "fs:" + p.join(".");
      const b = h("button", {type: "button", class: "fs-node" + (on ? " on" : "") + (mark ? " pv-" + mark : ""), "data-fkey": key,
        "aria-current": on ? "step" : null, title: `Open “${rid}” (right-click for more)`}, rid, n.if ? h("span", {class: "fs-if"}, "if") : null);
      b.addEventListener("click", () => openScreen(rid));
      b.addEventListener("contextmenu", (e) => { e.preventDefault(); nodeMenu(e, p); });
      b.addEventListener("keydown", (e) => { if ((e.key === "F10" && e.shiftKey) || e.key === "ContextMenu") { e.preventDefault(); nodeMenu(b, p); } });
      out.push(b);
    } else if (n && n.loop !== undefined) {
      const rows = loopRowsFor(n);
      const g = h("span", {class: "fs-group"}, h("button", {type: "button", class: "lbl", "data-fkey": "fsg:" + p.join("."), title: `Open the trial list “${n.loop}”`,
        onclick: () => openTrialList(p)}, icon("loop"), n.loop, Array.isArray(rows) ? h("span", {class: "fs-rows"}, `${rows.length}${n.repeats > 1 ? "×" + n.repeats : ""}`) : null));
      const inner = []; stripNodes(n.children, [...p, "children"], inner);
      g.append(...inner);
      out.push(g);
    } else if (n && n.if !== undefined) {
      const g = h("span", {class: "fs-group branch"}, h("button", {type: "button", class: "lbl", title: "Only if " + exprInWords(n.if), onclick: () => { S.sel = {kind: "branch", path: p}; setBuildView("story"); }}, icon("branch"), "if"));
      const a = []; stripNodes(n.then, [...p, "then"], a);
      const b2 = []; stripNodes(n.else, [...p, "else"], b2);
      put(g, ...a, b2.length ? h("span", {class: "fs-else"}, "otherwise") : null, ...b2);
      out.push(g);
    } else if (n && n.statemachine !== undefined) {
      const g = h("span", {class: "fs-group workflow"}, h("button", {type: "button", class: "lbl", title: `Open the diagram of “${n.statemachine}”`, onclick: () => openDiagram(p)}, icon("workflow"), n.statemachine));
      Object.entries(n.states || {}).forEach(([name, st], k) => {
        if (k) g.append(icon("chev-right", "fs-sep"));
        const inner = []; stripNodes(st.run, [...p, "states", name, "run"], inner);
        g.append(h("span", {class: "fs-phase"}, name), ...inner);
      });
      out.push(g);
    }
  });
}
function screenNeighbour(delta) {
  const order = routineInFlowOrder();
  const i = order.indexOf(S.routine);
  return order[i < 0 ? 0 : i + delta] || null;
}

/* ================================================================== "In words" (SPEC W4) */
function keysWords(keys) {
  if (!keys) return "any key";
  if (isExpr(keys)) return "the keys from the trial list";
  const list = (Array.isArray(keys) ? keys : String(keys).split(/[,\s]+/)).filter(Boolean).map((k) => k.length === 1 ? k.toUpperCase() : k === "space" ? "Space" : k);
  if (list.length === 1) return list[0];
  return list.slice(0, -1).join(", ") + " or " + list[list.length - 1];
}
function valueWords(v, what) {
  if (isExpr(v)) { const m = String(v).match(/^\$([A-Za-z_]\w*)$/); return m ? `the trial list's “${m[1]}”` : `a computed ${what}`; }
  return null;
}
function itemWords(c) {
  switch (c.type) {
    case "text": { const w = valueWords(c.text, "text") || (typeof c.text === "string" ? `the text “${short(c.text.replace(/\s+/g, " "), 40)}”` : "a text");
      const col = isExpr(c.color) ? (String(c.color).match(/^\$([A-Za-z_]\w*)$/) ? ` in the colour from “${c.color.slice(1)}”` : " in a computed colour") : "";
      return w + col; }
    case "image": return valueWords(c.image, "picture") ? `the picture from ${valueWords(c.image, "picture").replace("the trial list's", "the trial list's column")}` : c.image ? `the picture ${String(c.image).split("/").pop()}` : "a picture (not chosen yet)";
    case "shape": return `a ${({rect: "rectangle", circle: "circle", ellipse: "ellipse", line: "line", polygon: "polygon", cross: "cross"})[c.shape || "rect"] || "shape"}`;
    case "fixation": return "a fixation cross";
    case "sound": return typeof c.sound === "number" ? `a ${c.sound} Hz tone` : valueWords(c.sound, "sound") ? `the sound from ${valueWords(c.sound, "sound")}` : c.sound ? `the sound ${String(c.sound).split("/").pop()}` : "a sound";
    case "html": return c.file ? `the web page ${String(c.file).split("/").pop()}` : "a web page";
    case "survey": return `a survey (${plural((c.questions || []).filter((q) => q.type !== "page_break").length, "question")})`;
    case "keyboard": return `waits for ${keysWords(c.keys)}`;
    case "mouse": return "waits for a click";
    case "slider": return "a rating scale";
    case "device_response": return "waits for a button";
    case "gaze_roi": return "watches where they look";
    case "gaze_follow": return "moves an item with the gaze";
    case "calibrate": return "calibrates the eye tracker";
    case "marker": return `sends the marker “${c.label}”`;
    case "variable": return `sets ${Object.keys(c.set || {}).map((k) => `“${k}”`).join(", ") || "a variable"}`;
    case "code": return "runs code";
    case "wait": return "a pause";
    default: return friendlyName(c.type);
  }
}
const _RESPONSE_TYPES = new Set(["keyboard", "mouse", "slider", "html", "survey", "gaze_roi", "device_response"]);
const _WAITS = new Set(["keyboard", "mouse", "gaze_roi", "device_response"]);
/* Plain words for a screen (Simple), or the detailed technical sentence (Expert: plain=false). */
function describeRoutine(rid, {plain = isSimple()} = {}) {
  const r = S.exp.routines[rid];
  if (!r || !(r.components || []).length) return "This screen is empty.";
  if (!plain) return describeRoutineExpert(rid);
  const live = r.components.filter((c) => c.disabled !== true);
  const shows = live.filter((c) => !_WAITS.has(c.type) && !["variable", "code", "marker"].includes(c.type));
  const waits = live.filter((c) => _WAITS.has(c.type));
  const logic = live.filter((c) => ["variable", "code", "marker"].includes(c.type));
  shows.sort((a, b) => numOr(a.start, 0) - numOr(b.start, 0));
  const out = [];
  const startOf = (c) => c.start_after ? `after “${c.start_after}”` : (c.start_if || isExpr(c.start)) ? "when its condition is true" : null;
  let chain = "", prevEnd = null, prevStart = null;
  /* Identical neighbours (same item words, start and length) read as one phrase: "2 rectangles". */
  const phrase = (c) => {
    let what = itemWords(c);
    if (c.type === "sound") what = "plays " + what;
    if (typeof c.duration === "number") what += ` for ${fmtS(c.duration)}`;
    else if (c.type !== "sound") what += _RESPONSE_TYPES.has(c.type) ? " until it is answered" : " until the screen ends";
    if (c.if) what += " (only sometimes)";
    if (c.end_routine) what += _RESPONSE_TYPES.has(c.type) ? ", and answering it ends the screen" : ", and it ends the screen";
    return what;
  };
  const runs = [];
  for (const c of shows) {
    const what = phrase(c), last = runs[runs.length - 1];
    if (last && last.what === what && numOr(last.c.start, 0) === numOr(c.start, 0) && startOf(last.c) === startOf(c)) last.n++;
    else runs.push({c, what, n: 1});
  }
  for (const {c, what: w, n} of runs) {
    const st = typeof c.start === "number" ? c.start : 0;
    const special = startOf(c);
    let what = w;
    if (n > 1) {
      const m = what.match(/^an? (fixation cross|rectangle|circle|ellipse|line|polygon|cross|picture|sound)\b/);
      what = m ? `${n} ${m[1].endsWith("cross") ? m[1] + "es" : m[1] + "s"}${what.slice(m[0].length)}` : `${what} (${n} of them)`;
    }
    if (!chain) chain = (special ? `${special[0].toUpperCase()}${special.slice(1)} it ` : st > 0 ? `At ${fmtS(st)} it ` : "") + (c.type === "sound" ? "" : "shows ") + what;
    else if (special) chain += `; ${special} it ${c.type === "sound" ? "" : "shows "}${what}`;
    else if (prevEnd !== null && Math.abs(st - prevEnd) < 1e-6) chain += `, then ${what}`;
    else if (st === prevStart) chain += `, and ${what}`;
    else chain += `; at ${fmtS(st)} ${what}`;
    prevEnd = typeof c.duration === "number" && !special ? st + c.duration : null;
    prevStart = st;
  }
  if (chain) out.push(chain.charAt(0).toUpperCase() + chain.slice(1) + ".");
  const areas = waits.filter((c) => c.type === "gaze_roi").length;
  const said = new Set();
  for (const c of waits) {
    const st = typeof c.start === "number" ? c.start : 0;
    const special = startOf(c);
    const words = c.type === "gaze_roi" && areas > 1 ? `watches where they look (${areas} areas)` : itemWords(c);
    let s = `${special ? `${special[0].toUpperCase()}${special.slice(1)} it` : st > 0 ? `From ${fmtS(st)} it` : "It"} ${words}`;
    if (typeof c.duration === "number") s += ` (at most ${fmtS(c.duration)})`;
    if (c.if) s += " (only sometimes)";
    if (c.end_routine) s += "; the response ends the screen";
    if (!said.has(s)) { said.add(s); out.push(s + "."); }
  }
  if (typeof r.duration === "number") out.push(`The screen lasts ${live.some((c) => c.end_routine) ? "at most " : ""}${fmtS(r.duration)}.`);
  else if (isExpr(r.duration)) out.push(`The screen lasts ${exprInWords(r.duration)} seconds.`);
  if (r.end_if) out.push(`It ends early when ${exprInWords(r.end_if)}.`);
  for (const c of logic) out.push(`${c.when === "end" ? "At the end it" : "It"} ${itemWords(c)}.`);
  if ((r.rules || []).length) out.push(`${plural(r.rules.length, "rule")} react${r.rules.length === 1 ? "s" : ""} while it runs.`);
  const ends = live.some((c) => c.end_routine) || r.duration != null || r.end_if || live.some((c) => typeof c.duration === "number");
  if (!ends) out.push("Nothing ends it yet: add a response that ends it, or give it a length.");
  return out.join(" ");
}
function describeRoutineExpert(rid) {
  const r = S.exp.routines[rid];
  const fmt = (v) => isExpr(v) ? `“${v}”` : `${v} s`;
  const out = [];
  for (const c of r.components) {
    if (c.disabled === true) continue;
    const when = c.start_after ? `after ${c.start_after} ends` : c.start_if ? `when ${c.start_if}` : c.start_frame != null ? `from frame ${c.start_frame}` :
      (numOr(c.start, 0) === 0 && !isExpr(c.start) ? "from the start" : `at ${fmt(c.start)}`);
    const dur = c.duration != null ? `for ${fmt(c.duration)}` : c.duration_frames != null ? `for ${c.duration_frames} frames` : "until the screen ends";
    let s2 = `${c.id}: ${itemWords(c)}`;
    if (c.type === "text" && isExpr(c.text)) s2 = `${c.id} shows text ${c.text}`;
    if (!["code", "variable", "marker"].includes(c.type)) s2 += ` ${when}, ${_RESPONSE_TYPES.has(c.type) && c.duration == null ? "until answered" : dur}`;
    if (c.end_routine) s2 += "; this ends the screen";
    if (c.if) s2 += ` (only when ${c.if})`;
    if (c.marker) s2 += `; marks “${typeof c.marker === "object" ? c.marker.onset : c.marker}”`;
    out.push(s2 + ".");
  }
  if (r.duration != null) out.push(`The screen lasts at most ${fmt(r.duration)}.`);
  if (r.end_if) out.push(`It ends early when ${r.end_if}.`);
  for (const rule of r.rules || []) out.push(`When ${rule.when}: ${(Array.isArray(rule.do) ? rule.do : [rule.do]).map((a) => typeof a === "string" ? a.replace("_", " ") : Object.entries(a || {}).map(([k, v]) => k === "end_routine" ? "end the screen" : `${k} ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" ")).join(", ")}.`);
  return out.join(" ");
}

/* ================================================================== quick add (/) (SPEC W18) */
function quickAdd(anchor) {
  if (!bEditable()) return;
  if (S.view !== "screen" || !S.routine || !S.exp.routines[S.routine]) {
    if (S.routine && S.exp.routines[S.routine]) openScreen(S.routine); else return newRoutine();
  }
  const rid = S.routine;
  const t = S.previewT > 0.015 ? Math.round(S.previewT * 100) / 100 : 0;
  const lid = "qa-list-" + Date.now();
  const input = h("input", {class: "input", type: "text", role: "combobox", "aria-expanded": "true", "aria-controls": lid, "aria-autocomplete": "list",
    "aria-label": `Add to “${rid}”`, placeholder: `Add to “${rid}”: type to search`, autocomplete: "off", spellcheck: "false"});
  const list = h("ul", {class: "qa-list", role: "listbox", id: lid, "aria-label": "Things to add"});
  let active = 0, shown = [], pop = null;
  const pick = (type) => { pop?.close(); addComponent(type, undefined, {props: t ? {start: t} : {}, picker: true}); };
  const draw = () => {
    const f = input.value.trim().toLowerCase();
    const all = Object.keys(S.schema.components).filter((type) => {
      const words = `${type} ${friendlyName(type)} ${S.schema.components[type].description || ""}`.toLowerCase();
      return f ? f.split(/\s+/).every((w) => words.includes(w)) : !paletteHidden(type);
    });
    shown = all.sort((a, b) => (paletteHidden(a) - paletteHidden(b)) || (f ? friendlyName(a).toLowerCase().indexOf(f) - friendlyName(b).toLowerCase().indexOf(f) : 0)).slice(0, 12);
    active = Math.min(active, Math.max(0, shown.length - 1));
    list.replaceChildren(...shown.map((type, i) => h("li", {role: "option", id: `${lid}-${i}`, class: "qa-opt" + (i === active ? " on" : ""), "aria-selected": i === active ? "true" : "false",
      onmousedown: (e) => { e.preventDefault(); pick(type); }, onmousemove: () => { if (active !== i) { active = i; draw(); } }},
    h("span", {class: `tile tint-${catKey(type)}`}, icon(typeIcon(type))), h("span", {class: "qa-name"}, friendlyName(type)),
    !isSimple() || f ? h("span", {class: "mono t-caption"}, type) : null)));
    if (!shown.length) list.append(h("li", {class: "qa-none", role: "presentation"}, `Nothing called “${input.value}”.`));
    input.setAttribute("aria-activedescendant", shown.length ? `${lid}-${active}` : "");
  };
  input.addEventListener("input", () => { active = 0; draw(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(shown.length - 1, active + 1); draw(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); draw(); }
    else if (e.key === "Enter") { e.preventDefault(); if (shown[active]) pick(shown[active]); }
  });
  draw();
  const box = h("div", {class: "qa"}, input, list, h("div", {class: "qa-foot"}, `Enter adds it at ${fmtS(t)} · Esc closes`));
  pop = ui.popover(anchor instanceof Element && anchor.isConnected ? anchor : ($("#timeline .tl-head .btn") || $("#preview-wrap")), box, {placement: "bottom-end"});
  setTimeout(() => input.focus(), 0);
}

/* ================================================================== the Trial list view (SPEC W5) */
function openTrialList(path, {column = null} = {}) {
  const n = nodeAt(path);
  if (!n || n.loop === undefined) return;
  BUILD.listPath = path;
  BUILD.listColumn = column;
  if (S.view !== "list") BUILD.returnView = S.view === "diagram" ? "story" : (S.view || "story");
  BUILD.cell = {r: 0, c: 0};
  S.sel = {kind: "loop", path};
  if (S.view === "list") renderAll(); else setBuildView("list", {path});
}
function listCols(rows) { const out = []; for (const r of rows) for (const k of Object.keys(r || {})) if (!out.includes(k)) out.push(k); return out; }
function cellValue(raw) { const s = String(raw); return s !== "" && s.trim() !== "" && !isNaN(Number(s)) ? Number(s) : s; }
function routinesInside(n) {
  const out = new Set();
  const walk = (nodes) => (nodes || []).forEach((x) => {
    if (isRoutineNode(x)) out.add(routineOfNode(x));
    else if (x && typeof x === "object") { walk(x.children); walk(x.then); walk(x.else); for (const st of Object.values(x.states || {})) walk(st.run); }
  });
  walk(n.children);
  return [...out];
}
function columnUse(n, cols) {
  const use = Object.fromEntries(cols.map((c) => [c, []]));
  // the names an expression reads: quoted text is left out, except the {…} parts of an f-string
  const names = (v) => String(v).slice(1).replace(/(['"])(?:(?!\1).)*\1/g, (m) => " " + [...m.matchAll(/\{([^}]*)\}/g)].map((x) => x[1]).join(" ") + " ")
    .match(/[A-Za-z_]\w*/g) || [];
  const scan = (v, at) => {
    if (isExpr(v)) { for (const w of new Set(names(v))) if (use[w]) use[w].push(at); }
    else if (v && typeof v === "object") for (const x of Object.values(v)) scan(x, at);
  };
  for (const rid of routinesInside(n)) {
    const r = S.exp.routines[rid] || {};
    for (const c of r.components || []) for (const [prop, v] of Object.entries(c)) scan(v, {rid, id: c.id, prop});
    // the screen's own fields: how long it lasts, when it ends, its rules
    for (const prop of ["duration", "end_if", "rules"]) if (r[prop] !== undefined) scan(prop === "end_if" && typeof r[prop] === "string" && !isExpr(r[prop]) ? "$" + r[prop] : r[prop], {rid, id: rid, prop});
  }
  for (const prop of ["stop_if", "select"]) if (n[prop] !== undefined) scan(typeof n[prop] === "string" && !isExpr(n[prop]) ? "$" + n[prop] : n[prop], {rid: null, id: n.loop, prop});
  return use;
}
function knownNames(rid) {
  const out = new Set(["True", "False", "None", "t", "frame", "trial", "participant", "session", "rng", "random"]);
  for (const k of Object.keys(S.exp.variables || {})) out.add(k);
  for (const r of Object.values(S.exp.routines)) for (const c of r.components || []) out.add(c.id);
  for (const id of loopIds()) out.add(id);
  for (const k of Object.keys(S.exp.settings?.participant || {})) out.add(k);
  for (const lp of loopsAround(rid)) for (const k of (loopRowsFor(lp) || []).flatMap((r) => Object.keys(r || {}))) out.add(k);
  return out;
}
function closest(word, options) {
  let best = null, bd = 3;
  const dist = (a, b) => { const d = Array.from({length: a.length + 1}, (_, i) => [i]); for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return d[a.length][b.length]; };
  for (const o of options) { const x = dist(word.toLowerCase(), o.toLowerCase()); if (x < bd) { bd = x; best = o; } }
  return best;
}
function listWarnings(n, cols) {
  const out = [];
  for (const rid of routinesInside(n)) {
    const known = knownNames(rid);
    for (const c of S.exp.routines[rid]?.components || []) for (const [prop, v] of Object.entries(c)) {
      const m = isExpr(v) && String(v).match(/^\$([A-Za-z_]\w*)$/);
      if (!m || known.has(m[1]) || cols.includes(m[1])) continue;
      const near = closest(m[1], cols);
      out.push(h("div", {class: "alert warning le-warn"}, icon("warning"), h("div", {}, `“${rid}” › ${c.id} uses a column “${m[1]}” that this list doesn't have.`,
        near ? ` Did you mean “${near}”?` : "", " ", btn("Go there", () => { selectComp(rid, c.id, false); setBuildView("screen"); }, {cls: "btn sm ghost"}))));
    }
  }
  return out;
}
function renderListEditor(el) {
  el = el || $("#list-editor");
  const path = listPathNow();
  const n = path && nodeAt(path);
  if (!el || !n || n.loop === undefined) return;
  const c = n.conditions;
  const mode = n.staircase ? "staircase" : typeof c === "string" || (c && typeof c.file === "string") ? "file" : c && c.factorial ? "factorial" : "table";
  const seg = ui.seg([{value: "table", label: "Typed here"}, {value: "file", label: "A file"}, {value: "factorial", label: "Every combination"}, {value: "staircase", label: "Staircase"}],
    mode, (v) => switchListSource(n, path, v), {ariaLabel: "Rows come from"});
  if (S.proposal) seg.querySelectorAll("button").forEach((b) => { b.disabled = true; });
  let content;
  if (mode === "file") content = fileListView(n, path);
  else if (mode === "factorial") content = factorialEditor(n, path);
  else if (mode === "staircase") content = staircaseEditor(n, path);
  else content = tableEditor(n, path);
  const reps = +n.repeats || 1;
  const rows = loopRowsFor(n);
  const count = h("p", {class: "le-count t-caption"}, n.staircase ? `Runs until ${plural(n.staircase.reversals ?? 8, "reversal")} or ${plural(n.staircase.max_trials ?? 100, "trial")}.`
    : Array.isArray(rows) ? `${plural(rows.length, "row")}${reps !== 1 ? ` × ${reps} repeats` : ""} = ${plural(rows.length * reps, "trial")} of “${routinesInside(n).join("”, “") || "nothing yet"}”` : "");
  keepFocus(el, () => el.replaceChildren(
    h("div", {class: "le-head"}, h("span", {class: "label", id: "le-src-lbl"}, "Rows come from"), seg),
    content, count));
  if (mode === "table") focusListCell(el);
}
async function switchListSource(n, path, mode) {
  if (!bEditable()) return renderAll();
  const c = n.conditions;
  if (mode === "file") {
    const f = await pickDataFile(typeof c === "string" ? c : null);
    if (!f) return renderAll();
    delete n.staircase; n.conditions = f;
    commit(`Use ${f} as the trial list “${n.loop}”`);
    return;
  }
  if (mode === "table") {
    let rows = null;
    if (n.staircase) rows = [{[n.staircase.variable || "level"]: n.staircase.start ?? 0.5}];
    else if (c && c.factorial) rows = factorialRows(c);
    else if (typeof c === "string" || (c && c.file)) { rows = loopRows(c); if (!rows) { toast("The file is still loading: try again in a moment"); return renderAll(); } rows = clone(rows); }
    delete n.staircase;
    n.conditions = rows && rows.length ? rows : [{condition: "A"}, {condition: "B"}];
    commit(`Type the rows of “${n.loop}” here`);
    return;
  }
  if (mode === "factorial") {
    const rows = Array.isArray(c) ? c : (loopRows(c) || []);
    const f = {};
    for (const col of listCols(rows)) { const lv = [...new Set(rows.map((r) => r[col]).filter((v) => v !== "" && v != null))]; if (lv.length && lv.length <= 8) f[col] = lv; }
    delete n.staircase;
    n.conditions = {factorial: Object.keys(f).length ? f : {factor_a: ["a1", "a2"], factor_b: ["b1", "b2"]}};
    commit(`Make “${n.loop}” every combination`);
    return;
  }
  if (mode === "staircase") {
    delete n.conditions;
    n.staircase = {variable: "level", start: 0.5, step: [0.1, 0.05], down: 3, up: 1, min: 0, max: 1, reversals: 8, max_trials: 60, correct: "resp.corr"};
    commit(`Make “${n.loop}” a staircase`);
  }
}
async function pickDataFile(cur) {
  const files = typeof assetList === "function" ? await assetList("data") : [];
  const input = h("input", {type: "file", hidden: true, accept: DATA_EXT.join(",")});
  const search = h("input", {class: "input", type: "search", placeholder: "Search files…", "aria-label": "Search files"});
  const list = h("div", {class: "pick-list", role: "listbox", "aria-label": "Tables in the experiment's folder"});
  let resolveClose = null;
  const draw = () => {
    const f = search.value.toLowerCase();
    const shown = files.filter((a) => a.path.toLowerCase().includes(f));
    list.replaceChildren(...shown.map((a) => h("button", {type: "button", class: "pick-row" + (a.path === cur ? " on" : ""), role: "option", "aria-selected": a.path === cur ? "true" : "false",
      onclick: () => resolveClose?.(a.path)}, icon("table"), h("span", {class: "mono"}, a.path), h("span", {class: "t-caption"}, `${Math.max(1, Math.round(a.size / 1024))} KB`))));
    if (!shown.length) list.append(h("p", {class: "t-2"}, files.length ? "No file matches." : "No tables in the experiment's folder yet. Upload one from your computer."));
  };
  search.oninput = draw; draw();
  input.onchange = async () => {
    const f = input.files[0]; if (!f) return;
    if (!S.path && !(await EDGE.ensurePath())) return;
    const rel = `conditions/${f.name.replace(/[^\w.\- ]+/g, "_")}`;
    const r = await fetch(`/api/upload?path=${encodeURIComponent(S.path.replace(/[^/]*$/, "") + rel)}`, {method: "POST", body: await f.arrayBuffer()});
    if (r.ok) { BUILD.assets.at = 0; resolveClose?.(rel); } else toast(`Could not copy ${f.name}`, {tone: "danger"});
  };
  const v = await ui.dialog({title: "Choose a table", icon: "table", size: "md", initialFocus: search,
    body: h("div", {class: "pick"}, search, list, h("p", {class: "t-caption"}, "CSV, TSV, Excel (.xlsx), JSON or text, inside the experiment's folder."), input),
    buttons: [{label: "Upload from computer…", value: "upload", left: true}, {label: "Cancel", value: null}],
    onOpen: (dlg, close) => { resolveClose = close; dlg.querySelector("footer .btn.left").onclick = (e) => { e.preventDefault(); e.stopPropagation(); input.click(); }; }});
  return v && v !== "upload" ? v : null;
}

/* ---------------- Typed here: an editable grid */
function tableEditor(n, path) {
  const rows = Array.isArray(n.conditions) ? n.conditions : [];   // drawing never changes the document (no rows = the screens just repeat)
  const cols = listCols(rows);
  if (!rows.length && !cols.length) return emptyListState(n, path);
  const use = columnUse(n, cols);
  const colour = colourColumns(use);
  const ro = !!S.proposal;
  const table = h("table", {class: "grid edit le-grid", role: "grid", "aria-label": `Trial list ${n.loop}`, "aria-rowcount": String(rows.length + 1), "aria-readonly": ro ? "true" : null});
  const headRow = h("tr", {}, h("th", {class: "le-num", scope: "col"}, "#"));
  cols.forEach((col, ci) => {
    const u = use[col] || [];
    headRow.append(h("th", {scope: "col", class: BUILD.listColumn === col ? "hl" : null},
      h("button", {type: "button", class: "le-colname", "data-fkey": "col:" + col, title: "Rename, insert or delete this column", onclick: (e) => columnMenu(e.currentTarget, n, col, ci)},
        h("span", {class: "mono"}, col), icon("chev-down")),
      h("div", {class: "le-use" + (u.length ? "" : " unused")}, u.length ? `▸ ${u[0].id} · ${u[0].prop}${u.length > 1 ? ` +${u.length - 1}` : ""}` : "(not used: for analysis)")));
  });
  headRow.append(h("th", {class: "le-addcol"}, iconBtn("plus", "Add a column", () => addListColumn(n, cols.length), "btn ghost icon sm", ro ? {disabled: ""} : {})));
  const tbody = h("tbody", {});
  rows.forEach((r, ri) => {
    const tr = h("tr", {"aria-rowindex": String(ri + 2)},
      h("th", {class: "le-num", scope: "row"}, h("button", {type: "button", class: "le-rowbtn", tabindex: "-1", title: "Insert or delete rows", onclick: (e) => rowMenu(e.currentTarget, n, ri)}, String(ri + 1))));
    cols.forEach((col, ci) => {
      const v = r?.[col];
      const td = h("td", {role: "gridcell", tabindex: "-1", "data-r": ri, "data-c": ci, "data-fkey": `cell:${ri}:${ci}`, class: BUILD.listColumn === col ? "hl" : null});
      td.append(...cellDisplay(v, colour.has(col)));
      td.addEventListener("mousedown", () => setActiveCell(table, ri, ci));
      td.addEventListener("dblclick", () => editCell(table, n, rows, cols, ri, ci));
      tr.append(td);
    });
    tr.append(h("td", {class: "le-pad"}));
    tbody.append(tr);
  });
  table.append(h("thead", {}, headRow), tbody);
  table.addEventListener("keydown", (e) => gridKeys(e, table, n, rows, cols));
  table.addEventListener("paste", (e) => { if (e.target.tagName === "INPUT") return; e.preventDefault(); pasteRows(n, e.clipboardData.getData("text/plain")); });
  table.addEventListener("focusin", (e) => { const td = e.target.closest("td[data-r]"); if (td) BUILD.cell = {r: +td.dataset.r, c: +td.dataset.c}; });
  const out = h("div", {class: "le-table"},
    h("div", {class: "le-gridwrap"}, table),
    h("div", {class: "le-foot"},
      btn("Row", () => { if (!bEditable()) return; rows.push(Object.fromEntries(cols.map((c) => [c, ""]))); BUILD.cell = {r: rows.length - 1, c: 0}; BUILD.focusKey = `cell:${rows.length - 1}:0`; commit("Add a row"); }, {ic: "plus", attrs: ro ? {disabled: ""} : {}}),
      btn("Paste from Excel", () => pasteDialog(n), {cls: "btn sm ghost", ic: "table", attrs: ro ? {disabled: ""} : {}}),
      h("span", {class: "t-caption le-hint"}, "Arrows move · Enter edits · Ctrl+V pastes rows from a spreadsheet")),
    ...listWarnings(n, cols));
  return out;
}
const COLOUR_PROPS = new Set(["color", "fill", "line_color", "background"]);
function colourColumns(use) { return new Set(Object.entries(use).filter(([, u]) => u.some((x) => COLOUR_PROPS.has(x.prop))).map(([c]) => c)); }
function cellDisplay(v, colour = false) {
  if (v === undefined || v === null || v === "") return [h("span", {class: "le-blank"}, "")];
  const s = String(v);
  const out = [];
  if (colour && typeof colorHex === "function" && colorHex(s)) out.push(h("span", {class: "le-swatch", style: `background:${colorHex(s)}`}));
  if (/\.(png|jpe?g|gif|bmp|webp|svg)$/i.test(s) && S.path) out.push(h("img", {class: "le-thumb", alt: "", loading: "lazy", src: assetUrl(s)}));
  if (/\.(wav|mp3|ogg|flac|m4a|aiff?)$/i.test(s)) out.push(icon("sound", "le-ic"));
  out.push(h("span", {class: typeof v === "number" ? "num" : null}, s));
  return out;
}
function setActiveCell(table, r, c) {
  BUILD.cell = {r, c};
  for (const td of table.querySelectorAll("td[data-r]")) td.tabIndex = +td.dataset.r === r && +td.dataset.c === c ? 0 : -1;
}
function focusListCell(root) {
  const table = root.querySelector(".le-grid"); if (!table) return;
  const {r, c} = BUILD.cell;
  let td = table.querySelector(`td[data-r="${r}"][data-c="${c}"]`) || table.querySelector("td[data-r]");
  if (!td) return;
  for (const x of table.querySelectorAll("td[data-r]")) x.tabIndex = x === td ? 0 : -1;
}
function gridKeys(e, table, n, rows, cols) {
  const td = e.target.closest("td[data-r]");
  if (!td || e.target.tagName === "INPUT") return;
  const r = +td.dataset.r, c = +td.dataset.c;
  const go = (rr, cc) => {
    rr = Math.max(0, Math.min(rows.length - 1, rr)); cc = Math.max(0, Math.min(cols.length - 1, cc));
    setActiveCell(table, rr, cc);
    const t = table.querySelector(`td[data-r="${rr}"][data-c="${cc}"]`); t?.focus(); t?.scrollIntoView({block: "nearest", inline: "nearest"});
  };
  const mod = e.ctrlKey || e.metaKey;
  if (e.key === "ArrowUp") { e.preventDefault(); go(r - 1, c); }
  else if (e.key === "ArrowDown") { e.preventDefault(); go(r + 1, c); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); go(r, c - 1); }
  else if (e.key === "ArrowRight") { e.preventDefault(); go(r, c + 1); }
  else if (e.key === "Home") { e.preventDefault(); go(mod ? 0 : r, 0); }
  else if (e.key === "End") { e.preventDefault(); go(mod ? rows.length - 1 : r, cols.length - 1); }
  // Tab and Shift+Tab leave the grid (APG grid: one Tab stop, arrows inside); only while a cell is being edited
  // does Tab move to the next cell, spreadsheet style (editCell)
  else if (e.key === "Enter" || e.key === "F2") { e.preventDefault(); editCell(table, n, rows, cols, r, c); }
  else if ((e.key === "Delete" || e.key === "Backspace") && !mod) {
    e.preventDefault();
    if (!bEditable()) return;
    if (rows[r][cols[c]] === "" || rows[r][cols[c]] == null) return;
    rows[r][cols[c]] = ""; BUILD.focusKey = `cell:${r}:${c}`; commit("Clear a cell");
  }
  else if (e.key.length === 1 && !mod && !e.altKey) { e.preventDefault(); editCell(table, n, rows, cols, r, c, e.key); }
}
function editCell(table, n, rows, cols, r, c, initial = null) {
  if (!bEditable()) return;
  const td = table.querySelector(`td[data-r="${r}"][data-c="${c}"]`); if (!td) return;
  const col = cols[c];
  const cur = rows[r]?.[col];
  const input = h("input", {class: "input le-input", value: initial !== null ? initial : (cur === undefined || cur === null ? "" : String(cur)), "aria-label": `Row ${r + 1}, ${col}`, spellcheck: "false"});
  td.replaceChildren(input);
  td.classList.add("editing");
  input.focus();
  if (initial === null) input.select(); else input.setSelectionRange(input.value.length, input.value.length);
  let finished = false;
  const finish = (save, move) => {
    if (finished) return; finished = true;
    const v = cellValue(input.value);
    const [dr, dc] = move || [0, 0];
    const nr = Math.max(0, Math.min(rows.length - 1, r + dr)), nc = Math.max(0, Math.min(cols.length - 1, c + dc));
    BUILD.cell = {r: nr, c: nc}; BUILD.focusKey = `cell:${nr}:${nc}`;
    if (save && v !== cur && !(v === "" && cur == null)) { rows[r][col] = v; commit(`Edit the trial list “${n.loop}”`); }
    else renderAll();
  };
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") { e.preventDefault(); finish(true, [e.shiftKey ? -1 : 1, 0]); }
    else if (e.key === "Tab") { e.preventDefault(); finish(true, [0, e.shiftKey ? -1 : 1]); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}
function parseTable(text) {
  text = String(text || "").replace(/\r\n?/g, "\n").replace(/\n+$/, "");
  if (!text.trim()) return [];
  const sep = text.includes("\t") ? "\t" : text.includes(";") && !text.includes(",") ? ";" : ",";
  return text.split("\n").map((l) => l.split(sep).map((x) => x.trim().replace(/^"(.*)"$/, "$1")));
}
function pasteRows(n, text, {replace = false, append = false} = {}) {
  if (!bEditable()) return;
  const grid = parseTable(text);
  if (!grid.length) return;
  const rows = Array.isArray(n.conditions) ? n.conditions : (n.conditions = []);
  if (replace) rows.length = 0;
  let cols = listCols(rows);
  let header = null;
  const first = grid[0];
  if (cols.length && first.every((x, j) => x === cols[j] || (j >= cols.length && x && isNaN(Number(x))))) header = first;
  else if (!cols.length && first.every((x) => x && isNaN(Number(x)))) header = first;
  const data = header ? grid.slice(1) : grid;
  const {r: r0, c: c0} = replace || !rows.length ? {r: 0, c: 0} : (header || append ? {r: rows.length, c: 0} : BUILD.cell);
  const width = Math.max(...grid.map((g) => g.length));
  for (let j = 0; j < width; j++) {
    const ci = c0 + j;
    if (ci >= cols.length) cols.push(uniqueId(header ? ui.slug(header[j]) || "column" : "column", new Set(cols)));
  }
  data.forEach((g, i) => {
    const ri = r0 + i;
    while (rows.length <= ri) rows.push(Object.fromEntries(cols.map((c) => [c, ""])));
    g.forEach((v, j) => { rows[ri][cols[c0 + j]] = cellValue(v); });
  });
  for (const r of rows) for (const c of cols) if (!(c in r)) r[c] = "";
  commit(`Paste ${plural(data.length, "row")} into “${n.loop}”`);
  toast(`Pasted ${plural(data.length, "row")}${header ? " (the first row was the column names)" : ""}`);
}
async function pasteDialog(n, replace = false) {
  if (!bEditable()) return;
  const ta = h("textarea", {class: "input mono", rows: "8", placeholder: "word\tink\tkey\nRED\tred\tr", "aria-label": "Rows to paste"});
  const has = Array.isArray(n.conditions) && n.conditions.length > 0 && !replace;
  const v = await ui.dialog({title: "Paste rows from a spreadsheet", icon: "table", size: "md", initialFocus: ta,
    body: h("div", {class: "field"}, h("p", {class: "t-2"}, "Copy the cells in Excel, LibreOffice or Google Sheets (with the row of column names), then paste them here."), ta),
    buttons: [{label: "Cancel", value: null}, has ? {label: "Add them after the rows", value: "add"} : null, {label: has ? "Replace all rows" : "Use these rows", value: "replace", kind: "primary"}].filter(Boolean)});
  if (v && ta.value.trim()) pasteRows(n, ta.value, {replace: v === "replace", append: v === "add"});
}
function rebuildRows(rows, fn) { rows.forEach((r, i) => { rows[i] = fn(r); }); }
async function addListColumn(n, at) {
  if (!bEditable()) return;
  const rows = Array.isArray(n.conditions) ? n.conditions : [];
  const cols = listCols(rows);
  const name = await ui.prompt({title: "New column", label: "Column name", value: uniqueId("column", new Set(cols)), ok: "Add column",
    help: "Something that changes from trial to trial: the word, its colour, the right key.",
    transform: (v) => ui.slug(v), validate: (v) => !v ? "Type a name first." : cols.includes(v) ? `There is already a column “${v}”.` : null});
  if (!name) return;
  if (!Array.isArray(n.conditions)) n.conditions = rows;
  if (!rows.length) rows.push({});
  rebuildRows(rows, (r) => { const out = {}; const keys = cols; keys.forEach((k, i) => { if (i === at) out[name] = ""; out[k] = r[k] ?? ""; }); if (at >= keys.length) out[name] = ""; return out; });
  BUILD.focusKey = "col:" + name;
  commit(`Add the column “${name}”`);
}
function columnMenu(anchor, n, col, ci) {
  const rows = n.conditions;
  ui.menu(anchor, [
    {label: "Rename…", run: () => renameListColumn(n, col)},
    {label: "Insert a column on the left…", run: () => addListColumn(n, ci)},
    {label: "Insert a column on the right…", run: () => addListColumn(n, ci + 1)},
    {sep: true},
    {label: "Delete the column", icon: "trash", danger: true, run: () => {
      if (!bEditable()) return;
      rebuildRows(rows, (r) => { const out = {...r}; delete out[col]; return out; });
      commit(`Delete the column “${col}”`);
      undoToast(`Deleted the column “${col}”.`);
    }}]);
}
async function renameListColumn(n, col) {
  if (!bEditable()) return;
  const rows = n.conditions, cols = listCols(rows);
  const nc = await ui.prompt({title: `Rename the column “${col}”`, label: "Column name", value: col, ok: "Rename", transform: (v) => ui.slug(v),
    validate: (v) => !v ? "Type a name first." : v !== col && cols.includes(v) ? `There is already a column “${v}”.` : null});
  if (!nc || nc === col) return;
  rebuildRows(rows, (r) => { const out = {}; for (const [k, v] of Object.entries(r)) out[k === col ? nc : k] = v; return out; });
  // keep the screens working: $old becomes $new in the items of this list's screens
  let changed = 0;
  const re = new RegExp(`\\$${col}\\b`, "g");
  for (const rid of routinesInside(n)) for (const c of S.exp.routines[rid]?.components || [])
    for (const [k, v] of Object.entries(c)) if (isExpr(v) && re.test(v)) { c[k] = v.replace(re, "$" + nc); changed++; re.lastIndex = 0; }
  BUILD.focusKey = "col:" + nc;
  commit(`Rename the column “${col}”`);
  if (changed) toast(`Renamed the column and updated ${plural(changed, "item")} that used it`);
}
function rowMenu(anchor, n, ri) {
  const rows = n.conditions, cols = listCols(rows);
  const blank = () => Object.fromEntries(cols.map((c) => [c, ""]));
  ui.menu(anchor, [
    {label: "Insert a row above", run: () => { if (!bEditable()) return; rows.splice(ri, 0, blank()); commit("Insert a row"); }},
    {label: "Insert a row below", run: () => { if (!bEditable()) return; rows.splice(ri + 1, 0, blank()); commit("Insert a row"); }},
    {label: "Duplicate the row", icon: "duplicate", run: () => { if (!bEditable()) return; rows.splice(ri + 1, 0, clone(rows[ri])); commit("Duplicate a row"); }},
    {sep: true},
    {label: "Delete the row", icon: "trash", danger: true, run: () => { if (!bEditable()) return; rows.splice(ri, 1); BUILD.cell = {r: Math.max(0, ri - 1), c: 0}; commit(`Delete row ${ri + 1}`); undoToast(`Deleted row ${ri + 1}.`); }}]);
}
function emptyListState(n, path) {
  const a = buildAssistant();
  return emptyState("table", "This trial list has no rows yet",
    "A trial list repeats its screens once per row. Each column is something that changes from trial to trial (the word, its colour, the right key). Type rows here, paste them from Excel, choose a file, or describe them.", [
      btn("Row", () => { if (!bEditable()) return; n.conditions = [{condition: ""}]; BUILD.cell = {r: 0, c: 0}; BUILD.focusKey = "cell:0:0"; commit("Add a row"); }, {cls: "btn primary", ic: "plus"}),
      btn("Paste from Excel", () => pasteDialog(n, true), {cls: "btn", ic: "table"}),
      btn("Choose a file", () => switchListSource(n, path, "file"), {cls: "btn", ic: "folder"}),
      a ? btn("Describe them", () => a.open?.({text: `Fill the trial list “${n.loop}” with rows: `}), {cls: "btn assistant-outline", ic: "assistant"}) : null]);
}

/* ---------------- A file: read-only rows from /api/conditions */
function fileListView(n, path) {
  const spec = n.conditions;
  const file = typeof spec === "string" ? spec : spec.file;
  const rows = loopRows(spec);
  const err = loopRowsError(spec);
  const cols = Array.isArray(rows) ? listCols(rows) : [];
  const info = h("div", {class: "le-fileinfo"}, h("span", {class: "label"}, "File"), h("span", {class: "mono le-file"}, file),
    h("span", {class: "t-caption"}, Array.isArray(rows) ? `${plural(rows.length, "row")} · ${plural(cols.length, "column")}` : err ? "can't be read" : "loading…"),
    h("span", {class: "grow"}),
    btn("Change file…", () => switchListSource(n, path, "file"), {cls: "btn sm", ic: "folder"}),
    btn("Copy into the experiment", () => { if (!bEditable()) return; if (!Array.isArray(rows)) return; n.conditions = clone(rows); commit(`Copy ${file} into the experiment`);
      toast(`The rows of ${file.split("/").pop()} are now typed in the experiment. The file itself is unchanged.`); }, {cls: "btn sm", attrs: Array.isArray(rows) ? {} : {disabled: ""}}),
    iconBtn("refresh", "Read the file again", () => { delete BUILD.rows[JSON.stringify(spec) + "|" + (S.path || "")]; renderAll(); }));
  const out = [info, h("div", {class: "alert info"}, icon("info"), h("div", {}, `This list comes from ${file.split("/").pop()}. Edit it in a spreadsheet app (EDGE reads it again when the file changes), or copy it into the experiment to edit it here.`,
    /\.xlsx$/i.test(file) ? " EDGE reads the first (active) sheet of an Excel file." : ""))];
  if (err) out.push(h("div", {class: "alert danger"}, icon("error"), h("div", {}, h("b", {}, `EDGE can't read ${file.split("/").pop()}`), err)));
  else if (!Array.isArray(rows)) out.push(h("div", {class: "le-loading"}, h("span", {class: "spin"}), "Reading the file…"));
  else {
    const use = columnUse(n, cols);
    const colour = colourColumns(use);
    const table = h("table", {class: "grid le-grid ro", "aria-label": `Rows of ${file}`},
      h("thead", {}, h("tr", {}, h("th", {class: "le-num"}, "#"), cols.map((c) => h("th", {class: BUILD.listColumn === c ? "hl" : null}, h("span", {class: "mono"}, c),
        h("div", {class: "le-use" + ((use[c] || []).length ? "" : " unused")}, (use[c] || []).length ? `▸ ${use[c][0].id} · ${use[c][0].prop}` : "(not used: for analysis)"))))),
      h("tbody", {}, rows.map((r, i) => h("tr", {}, h("th", {class: "le-num", scope: "row"}, String(i + 1)), cols.map((c) => h("td", {}, cellDisplay(r[c], colour.has(c))))))));
    out.push(h("div", {class: "le-gridwrap"}, table), h("p", {class: "t-caption"}, `Read-only: the rows come from the file.${rows.length >= 500 ? " Showing the first 500." : ""}`),
      ...listWarnings(n, cols));
  }
  return h("div", {class: "le-filebox"}, out);
}

/* ---------------- Every combination: factors and their levels */
function factorialEditor(n, path) {
  const spec = n.conditions; const f = spec.factorial ||= {};
  const names = Object.keys(f);
  const ro = !!S.proposal;
  const rename = (old, nn) => { const out = {}; for (const [k, v] of Object.entries(f)) out[k === old ? nn : k] = v; spec.factorial = out; };
  const box = h("div", {class: "le-factors"});
  names.forEach((name) => {
    const levels = Array.isArray(f[name]) ? f[name] : (f[name] = [f[name]]);
    const nameIn = h("input", {class: "input mono le-fname", value: name, "aria-label": "Factor name", disabled: ro ? "" : null,
      onchange: (e) => { const v = ui.slug(e.target.value); if (!v || v === name) { e.target.value = name; return; } if (f[v]) { toast(`There is already a factor “${v}”`); e.target.value = name; return; } rename(name, v); commit(`Rename the factor “${name}”`); }});
    const add = h("input", {class: "input le-addlevel", placeholder: "Add a level…", "aria-label": `Add a level to ${name}`, disabled: ro ? "" : null,
      onkeydown: (e) => { if (e.key === "Enter" && e.target.value.trim()) { e.preventDefault(); if (!bEditable()) return; levels.push(cellValue(e.target.value.trim())); BUILD.focusKey = "lvl:" + name; commit(`Add a level to “${name}”`); } }});
    add.dataset.fkey = "lvl:" + name;
    box.append(h("div", {class: "le-factor"}, nameIn,
      h("div", {class: "le-levels"}, levels.map((lv, i) => h("span", {class: "chip lg"}, String(lv),
        h("button", {type: "button", class: "x", "aria-label": `Remove ${lv}`, disabled: ro ? "" : null, onclick: () => { if (!bEditable()) return; levels.splice(i, 1); commit(`Remove a level of “${name}”`); }}, icon("close")))), add),
      iconBtn("trash", `Remove the factor ${name}`, () => { if (!bEditable()) return; delete f[name]; commit(`Remove the factor “${name}”`); undoToast(`Removed the factor “${name}”.`); })));
  });
  const total = names.reduce((a, k) => a * (Array.isArray(f[k]) ? f[k].length : 1), 1);
  const rows = factorialRows(spec);
  const cols = listCols(rows);
  return h("div", {class: "le-fact"},
    box,
    h("div", {class: "le-foot"}, btn("Add a factor", () => { if (!bEditable()) return; f[uniqueId("factor", new Set(names))] = ["a", "b"]; commit("Add a factor"); }, {ic: "plus", attrs: ro ? {disabled: ""} : {}}),
      h("span", {class: "le-total"}, names.length ? `${names.map((k) => (f[k] || []).length).join(" × ")} = ${plural(total, "row")}` : "No factors yet")),
    rows.length && cols.length ? h("div", {class: "le-gridwrap"}, h("table", {class: "grid le-grid ro", "aria-label": "Every combination"},
      h("thead", {}, h("tr", {}, h("th", {class: "le-num"}, "#"), cols.map((c) => h("th", {}, h("span", {class: "mono"}, c))))),
      h("tbody", {}, rows.slice(0, 60).map((r, i) => h("tr", {}, h("th", {class: "le-num"}, String(i + 1)), cols.map((c) => h("td", {}, cellDisplay(r[c])))))))) : null,
    rows.length > 60 ? h("p", {class: "t-caption"}, `Showing 60 of ${rows.length} rows.`) : null);
}

/* ---------------- Staircase: an adaptive procedure */
function staircaseEditor(n) {
  const sc = n.staircase;
  const ro = !!S.proposal;
  const set = (k, v, label) => { if (!bEditable()) return; if (v === "" || v === null || v === undefined || (typeof v === "number" && isNaN(v))) delete sc[k]; else sc[k] = v; commit(label || `Change the staircase of “${n.loop}”`); };
  const num = (k, label, help, dflt) => {
    const id = `sc-${k}`;
    return h("div", {class: "field"}, h("label", {for: id}, label),
      h("input", {class: "input", id, type: "number", step: "any", value: sc[k] ?? "", placeholder: dflt != null ? String(dflt) : "", disabled: ro ? "" : null,
        onchange: (e) => set(k, e.target.value === "" ? "" : Number(e.target.value))}), help ? h("div", {class: "help"}, help) : null);
  };
  const steps = Array.isArray(sc.step) ? sc.step : [sc.step ?? 0.1];
  const stepIn = (i, label, help) => h("div", {class: "field"}, h("label", {for: "sc-step" + i}, label),
    h("input", {class: "input", id: "sc-step" + i, type: "number", step: "any", value: steps[i] ?? "", disabled: ro ? "" : null, onchange: (e) => {
      const v = e.target.value === "" ? null : Number(e.target.value);
      const st = [...steps]; st[i] = v;
      const clean = st.filter((x) => x !== null && x !== undefined && !isNaN(x));
      set("step", clean.length > 1 ? clean : clean[0] ?? 0.1, "Change the staircase step");
    }}), help ? h("div", {class: "help"}, help) : null);
  const corr = h("input", {class: "input expr", id: "sc-correct", value: sc.correct ?? "resp.corr", disabled: ro ? "" : null, spellcheck: "false",
    onchange: (e) => set("correct", e.target.value.trim().replace(/^\$/, "") || "resp.corr", "Change when a trial counts as correct")});
  return h("div", {class: "le-stair"},
    h("p", {class: "t-2"}, `A staircase makes the task harder after correct answers and easier after mistakes, to find a threshold. Each trial gets the current value as “${sc.variable || "level"}”.`),
    h("div", {class: "le-stair-grid"},
      h("div", {class: "field"}, h("label", {for: "sc-var"}, "Variable"), h("input", {class: "input mono", id: "sc-var", value: sc.variable || "level", disabled: ro ? "" : null,
        onchange: (e) => set("variable", ui.slug(e.target.value) || "level", "Rename the staircase variable")}), h("div", {class: "help"}, "The name your screens use, e.g. contrast.")),
      num("start", "Start", "The first trial's value.", 0.5),
      stepIn(0, "Step", "How much it changes at first."),
      stepIn(1, "Step after the first reversal", "Smaller steps once it turns around (optional)."),
      num("down", "Right answers in a row → harder", null, 3),
      num("up", "Wrong answers in a row → easier", null, 1),
      num("min", "Lowest value", null, ""),
      num("max", "Highest value", null, ""),
      num("reversals", "Stop after this many reversals", null, 8),
      num("max_trials", "…or after this many trials", null, 100),
      h("div", {class: "field wide"}, h("label", {for: "sc-correct"}, "Correct when"), corr, h("div", {class: "help"}, `In words: ${exprInWords("$" + (sc.correct || "resp.corr"))}.`)),
      !isSimple() ? h("div", {class: "field wide"}, ui.switch(!!sc.log, (v) => set("log", v || "", "Change the staircase stepping"), {label: "Step in log units", caption: "For values like contrast that change by ratios."})) : null));
}

/* ================================================================== the workflow Diagram view (SPEC W6) */
function openDiagram(path) {
  const m = nodeAt(path);
  if (!m || m.statemachine === undefined) return;
  BUILD.diagramPath = path;
  BUILD.zoom = null;
  if (S.view !== "diagram") BUILD.returnView = S.view === "list" ? "story" : (S.view || "story");
  if (!(S.sel && ["machine", "state"].includes(S.sel.kind) && samePath(S.sel.path, path))) S.sel = {kind: "machine", path};
  if (S.view === "diagram") renderAll(); else setBuildView("diagram", {path});
}
function layoutMachine(m) {
  const names = Object.keys(m.states || {});
  const col = {}, queue = [m.start];
  if (m.start in (m.states || {})) col[m.start] = 0;
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
  const W = 180, H = 72, GX = 150, GY = 70;
  for (const n of names) { const c = col[n]; rows[c] = (rows[c] || 0); pos[n] = {x: 24 + c * (W + GX), y: 40 + rows[c] * (H + GY), w: W, h: H}; rows[c]++; }
  const endCol = Math.max(0, ...Object.values(col)) + 1;
  pos.end = {x: 24 + endCol * (W + GX), y: 40 + H / 2 - 20, w: 88, h: 40, end: true};
  for (const p of Object.values(pos)) p.y += 56;   // room for routes that arc over the phases
  return pos;
}
function phaseRuns(st) {
  return (st.run || []).map((x) => isRoutineNode(x) ? routineOfNode(x) : x.loop ? `${x.loop} (trial list)` : x.statemachine ? `${x.statemachine} (workflow)` : "if / otherwise");
}
function renderDiagram(el) {
  el = el || $("#diagram");
  const path = diagramPathNow();
  const m = path && nodeAt(path);
  if (!el || !m || m.statemachine === undefined) return;
  const pos = layoutMachine(m);
  const W = Math.max(...Object.values(pos).map((p) => p.x + p.w)) + 24;
  const H = Math.max(...Object.values(pos).map((p) => p.y + p.h)) + 110;
  const NS = "http://www.w3.org/2000/svg";
  const mk = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
  const svg = mk("svg", {width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: "dg-svg", "aria-hidden": "true"});
  const defs = mk("defs", {});
  const marker = mk("marker", {id: "dg-arrow", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse"});
  marker.append(mk("path", {d: "M0,0 L10,5 L0,10 z", class: "dg-head"}));
  const marker2 = mk("marker", {id: "dg-arrow-d", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse"});
  marker2.append(mk("path", {d: "M0,0 L10,5 L0,10 z", class: "dg-head dflt"}));
  defs.append(marker, marker2); svg.append(defs);
  const layer = h("div", {class: "dg-layer", style: `width:${W}px;height:${H}px`});
  layer.append(svg);
  for (const [name, st] of Object.entries(m.states || {})) {
    const a = pos[name];
    const nx = (st.next?.length ? st.next : [{goto: "end"}]).map((t) => typeof t === "string" ? {goto: t} : t);
    nx.forEach((t, i) => {
      const b = pos[t.goto] || pos.end;
      const dflt = !t.if;
      let label = t.if ? exprInWords(t.if) : nx.length > 1 ? "otherwise" : "";
      if (t.goto === name && st.max_visits) label += `${label ? " · " : ""}at most ${plural(st.max_visits, "time")}`;
      let d, lx, ly;
      if (t.goto === name) {          // the same phase again
        const x = a.x + a.w * 0.7, y = a.y;
        d = `M${x - 28},${y} C${x - 46},${y - 58} ${x + 34},${y - 58} ${x + 12},${y}`;
        lx = x - 8; ly = y - 66;
      } else if (b.x > a.x && b.x - (a.x + a.w) < 200) {   // forward to the next column
        const y1 = a.y + a.h / 2 + (i - (nx.length - 1) / 2) * 14;
        const y2 = b.y + b.h / 2;
        d = `M${a.x + a.w},${y1} C${a.x + a.w + 60},${y1} ${b.x - 60},${y2} ${b.x},${y2}`;
        lx = (a.x + a.w + b.x) / 2; ly = Math.min(y1, y2) - 22;
      } else if (b.x > a.x) {          // forward, skipping phases: arc over the top
        const y = Math.min(a.y, b.y) - 26 - i * 14;
        d = `M${a.x + a.w / 2},${a.y} C${a.x + a.w / 2},${y - 24} ${b.x + b.w / 2},${y - 24} ${b.x + b.w / 2},${b.y}`;
        lx = (a.x + a.w / 2 + b.x + b.w / 2) / 2; ly = y - 30;
      } else {                         // backward: arc underneath
        const y = Math.max(a.y + a.h, b.y + b.h) + 36 + i * 16;
        d = `M${a.x + a.w / 2},${a.y + a.h} C${a.x + a.w / 2},${y} ${b.x + b.w / 2},${y} ${b.x + b.w / 2},${b.y + b.h}`;
        lx = (a.x + a.w / 2 + b.x + b.w / 2) / 2; ly = y - 4;
      }
      svg.append(mk("path", {d, class: "dg-edge" + (dflt ? " dflt" : ""), "marker-end": dflt ? "url(#dg-arrow-d)" : "url(#dg-arrow)"}));
      if (label) layer.append(h("div", {class: "dg-label" + (dflt ? " dflt" : ""), style: `left:${lx}px;top:${ly}px`, title: t.if || "otherwise"}, label));
    });
  }
  for (const [name, p] of Object.entries(pos)) {
    if (p.end) { layer.append(h("div", {class: "dg-end", style: `left:${p.x}px;top:${p.y}px;width:${p.w}px;height:${p.h}px`}, "End")); continue; }
    const st = m.states[name];
    const runs = phaseRuns(st);
    const sel = S.sel?.kind === "state" && samePath(S.sel.path, path) && S.sel.name === name;
    const key = `dg:${name}`;
    const b = h("button", {type: "button", class: "dg-phase" + (name === m.start ? " start" : "") + (sel ? " selected" : ""), "data-fkey": key,
      style: `left:${p.x}px;top:${p.y}px;width:${p.w}px;height:${p.h}px`,
      "aria-label": `Phase ${name}${name === m.start ? " (first)" : ""}: runs ${runs.join(", ") || "nothing yet"}. ${routesInWords(st)}`,
      onclick: () => { S.sel = {kind: "state", path, name}; BUILD.focusKey = key; renderAll(); }},
    h("span", {class: "dg-name"}, name === m.start ? icon("play") : null, name),
    h("span", {class: "dg-runs"}, runs.length ? runs.join(" → ") : "empty: add screens"),
    st.max_visits ? h("span", {class: "dg-max"}, `at most ${plural(st.max_visits, "time")}`) : null);
    layer.append(b);
  }
  const vp = h("div", {class: "dg-viewport"});
  const scaler = h("div", {class: "dg-scaler"}, layer);
  vp.append(scaler);
  const zl = h("span", {class: "dg-zoomlbl mono"});
  const applyZoom = () => {
    const z = BUILD.zoom || 1;
    layer.style.transform = `scale(${z})`;
    scaler.style.width = W * z + "px"; scaler.style.height = H * z + "px";
    zl.textContent = Math.round(z * 100) + " %";
  };
  const zoomTo = (z) => { BUILD.zoom = Math.max(0.3, Math.min(2, z)); applyZoom(); };
  vp.addEventListener("wheel", (e) => { if (!(e.ctrlKey || e.metaKey)) return; e.preventDefault(); zoomTo((BUILD.zoom || 1) * Math.exp(-e.deltaY * 0.002)); }, {passive: false});
  vp.addEventListener("mousedown", (e) => { if (e.button !== 0 || e.target.closest("button")) return;
    BUILD.pan = {vp, x: e.clientX, y: e.clientY, l: vp.scrollLeft, t: vp.scrollTop}; vp.classList.add("panning"); e.preventDefault(); });
  const tools = h("div", {class: "dg-tools"},
    btn("Add a phase", () => { if (bEditable() && typeof addState === "function") addState(path); }, {cls: "btn sm", ic: "plus"}),
    h("span", {class: "grow"}),
    iconBtn("minus", "Zoom out", () => zoomTo((BUILD.zoom || 1) / 1.2)), zl, iconBtn("plus", "Zoom in", () => zoomTo((BUILD.zoom || 1) * 1.2)),
    btn("Fit", () => { BUILD.zoom = null; fit(true); }, {cls: "btn sm ghost"}));
  keepFocus(el, () => el.replaceChildren(
    h("div", {class: "dg-top"}, h("p", {class: "t-2"}, "After a phase finishes, its routes are checked from top to bottom; the first one that is true is taken."), tools),
    vp,
    h("p", {class: "t-caption dg-foot"}, "Click a phase to edit it in Properties. Arrows are routes; dashed arrows mean “otherwise”. Ctrl + wheel zooms.")));
  // Fit shows every phase and route (down to the 30 % zoomTo allows); on first open the width fits, down to 50 %
  const fit = (all = false) => {
    if (BUILD.zoom == null) {
      const w = vp.clientWidth - 8, hh = vp.clientHeight - 8;
      const k = all && hh > 40 ? Math.min(w / W, hh / H) : w / W;
      BUILD.zoom = Math.max(all ? 0.3 : 0.5, Math.min(1, k));
    }
    applyZoom();
  };
  fit();
}

/* ================================================================== keyboard: Build-only keys (SPEC §2.10) */
function overlayOpen() {
  return !!document.querySelector(".scrim, .menu:not([hidden]), .popover") || !$("#modal")?.classList.contains("hidden") || !$("#play")?.classList.contains("hidden");
}
document.addEventListener("keydown", (e) => {
  if (e.defaultPrevented || !S.exp || S.ws !== "build" || overlayOpen()) return;
  const t = e.target;
  if (typingIn(t)) return;
  const mod = e.ctrlKey || e.metaKey;
  const view = currentBuildView();
  if (e.key === "/" && !mod && !e.altKey && view === "screen") { e.preventDefault(); quickAdd($("#timeline .tl-head .btn")); return; }
  if ((e.key === "[" || e.key === "]") && mod && view === "screen") { e.preventDefault(); stepRow(e.key === "]" ? 1 : -1); return; }
  if ((e.key === "[" || e.key === "]") && !mod && !e.altKey) {
    e.preventDefault();
    const rid = screenNeighbour(e.key === "]" ? 1 : -1);
    if (!rid) return ui.announce(e.key === "]" ? "This is the last screen" : "This is the first screen");
    if (view === "screen") openScreen(rid);
    else if (view === "story") { S.routine = rid; S.sel = {kind: "routine", routine: rid}; BUILD.focusKey = null; renderAll();
      const card = document.querySelector(`#flow .scard[data-rid="${CSS.escape(rid)}"]`); card?.focus(); card?.scrollIntoView({block: "nearest"}); }
    return;
  }
  if (e.key === " " && t?.id === "preview" && view === "screen") { e.preventDefault(); playPreview(); return; }
  if (e.key === "Escape") {
    if ($("#ws-build").classList.contains("focus") && view === "screen") { e.preventDefault(); toggleBigPreview(false); return; }
    if (flyoutOpen() && !BUILD.pinned) { e.preventDefault(); closeFlyout(true); return; }
    if (view === "list" || view === "diagram") { e.preventDefault(); leaveSubView(); return; }
    if (view === "screen") {
      e.preventDefault();
      if (S.sel?.kind === "component") { S.sel = {kind: "routine", routine: S.routine}; renderAll(); }
      else setBuildView("story");
      return;
    }
    if (view === "story" && S.sel) { e.preventDefault(); S.sel = null; renderAll(); }
  }
});

/* ================================================================== the assistant on the canvas (W2) */
/* EDGE.emit("assistant", {busy, path, status, phase}) from assistant.js: while a job runs for this document the canvas says
 * so (a big note on an empty experiment, a slim strip otherwise); after the first Apply to an experiment, a one-time
 * callout points at what to check. */
const ASST_CANVAS = {busy: false, callout: null};
function onAssistantEvent(d = {}) {
  const mine = !d.path || !S.path || d.path === S.path;
  ASST_CANVAS.busy = !!d.busy && mine;
  if (!d.busy && d.phase === "applied" && mine && S.path) {
    const seen = EDGE.prefs.get("assistant.madeBy", []) || [];
    if (!seen.includes(S.path)) { ASST_CANVAS.callout = S.path; EDGE.prefs.set("assistant.madeBy", [...seen, S.path].slice(-200)); }
  }
  renderAssistantCanvas();
  if (S.exp && !S.exp.flow.length && S.ws === "build" && currentBuildView() === "story") renderStoryboard($("#flow"));
}
function renderAssistantCanvas() {
  const host = $("#canvas"); if (!host) return;
  let el = $("#asst-canvas");
  const callout = ASST_CANVAS.callout && ASST_CANVAS.callout === S.path && !ASST_CANVAS.busy && !S.proposal;
  const refit = () => { if (S.ws === "build" && currentBuildView() === "screen") requestAnimationFrame(() => renderPreview()); };
  if (!ASST_CANVAS.busy && !callout) { if (el) { el.remove(); refit(); } return; }
  if (!el) { el = h("div", {id: "asst-canvas"}); host.prepend(el); refit(); }
  // the big note: an empty experiment, or the first build of one just created from Home (W2: the blank "hello" screen)
  const firstBuild = typeof EDGE.isFresh === "function" && EDGE.isFresh() && !(EDGE.prefs.get("assistant.madeBy", []) || []).includes(S.path);
  const empty = S.exp && (!S.exp.flow.length || firstBuild);
  if (ASST_CANVAS.busy) {
    const key = "busy" + (empty ? ":empty" : "");
    if (el.dataset.key === key) return;
    el.dataset.key = key;
    el.className = empty ? "asst-building big" : "asst-building";
    el.setAttribute("role", "status");
    el.replaceChildren(h("div", {class: "box"}, icon("assistant", empty ? "l" : "m"), h("div", {},
      h("b", {}, empty ? "The assistant is building your experiment." : "The assistant is working on changes."),
      h("p", {}, empty ? "It appears here when it's ready for you to check. Nothing is changed until you apply it." : "Nothing is changed until you apply them."))));
    return;
  }
  if (el.dataset.key === "callout") return;
  el.dataset.key = "callout";
  el.className = "asst-callout";
  el.setAttribute("role", "region"); el.setAttribute("aria-label", "Made by the assistant");
  const firstList = (() => { let p = null; walkFlow((n, pp) => { if (!p && n && typeof n === "object" && n.loop !== undefined) p = pp; }); return p; })();
  const firstScreen = (() => { const order = routineInFlowOrder(); return order.find((rid) => loopsAround(rid).length) || order[0] || null; })();
  const close = () => { ASST_CANVAS.callout = null; renderAssistantCanvas(); };
  el.replaceChildren(icon("assistant", "m"), h("div", {class: "msg"}, h("b", {}, "Made by the assistant. "), "Check these:"),
    h("div", {class: "acts"},
      btn("Try it yourself", () => { close(); tryNow("all"); }, {ic: "play"}),
      firstList ? btn("Open the trial list", () => { close(); openTrialList(firstList); }, {ic: "table"}) : null,
      firstScreen ? btn("See the timing", () => { close(); openScreen(firstScreen); }, {ic: "timeline"}) : null),
    iconBtn("close", "Close", close));
}

/* ================================================================== wiring */
window.addEventListener("mousemove", (e) => { const p = BUILD.pan; if (!p) return; p.vp.scrollLeft = p.l - (e.clientX - p.x); p.vp.scrollTop = p.t - (e.clientY - p.y); });
window.addEventListener("mouseup", () => { if (BUILD.pan) { BUILD.pan.vp.classList.remove("panning"); BUILD.pan = null; } });
window.addEventListener("resize", () => { if (!S.exp) return; setTimeout(() => { applyRail(); fitToolbar(); }, 80); if (currentBuildView() === "story") return; scheduleBuildRender(); });
document.addEventListener("mousedown", (e) => {
  if (!flyoutOpen() || BUILD.pinned) return;
  const t = e.target;
  if (t.closest("#sidebar, #rail, .menu, .popover, .scrim, #modal")) return;
  closeFlyout(false);
}, true);
EDGE.on("doc:loaded", () => {
  BUILD.listPath = null; BUILD.diagramPath = null; BUILD.returnView = "story"; BUILD.zoom = null; BUILD.cell = {r: 0, c: 0};
  BUILD.thumbs.clear(); BUILD.assets.at = 0; BUILD.sayOpen = false;
  S.rowIndex = 0;
  if (S.routine) S.previewT = thumbTime(S.routine);
  if (S.side === "files") renderFilesSoon();
  scheduleBuildRender();
});
EDGE.on("doc:changed", () => { BUILD.assets.at = 0; });
EDGE.on("doc:saved", () => { if (S.ws === "build" && S.exp) renderBuildToolbar(currentBuildView()); });     // Save as: the first crumb is the new name
EDGE.on("assistant", onAssistantEvent);
EDGE.on("doc:loaded", () => { if (ASST_CANVAS.callout && ASST_CANVAS.callout !== S.path) ASST_CANVAS.callout = null; renderAssistantCanvas(); });
EDGE.on("proposal", () => renderAssistantCanvas());
EDGE.on("companion", () => { setTimeout(() => { applyRail(); fitToolbar(); }, 0); if (S.exp && S.ws === "build") requestAnimationFrame(() => { if (currentBuildView() === "screen") renderPreview(); }); });
EDGE.on("mode", () => { BUILD.thumbs.clear(); });
window.addEventListener("DOMContentLoaded", () => {
  const layout = EDGE.prefs.get("layout", {}) || {};
  BUILD.pinned = !!layout.pinned;
  buildRailOnce();
  const pal = $("#palette");
  pal?.addEventListener("keydown", (e) => {
    if (!["ArrowDown", "ArrowUp"].includes(e.key) || !e.target.classList.contains("pal-item")) return;
    e.preventDefault();
    const all = [...pal.querySelectorAll(".pal-item")];
    all[all.indexOf(e.target) + (e.key === "ArrowDown" ? 1 : -1)]?.focus();
  });
  $("#palette-filter")?.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); $("#palette .pal-item")?.focus(); }
    else if (e.key === "Enter") { e.preventDefault(); $("#palette .pal-item")?.click(); }
    else if (e.key === "Escape" && e.target.value) { e.preventDefault(); e.stopPropagation(); e.target.value = ""; renderPalette(); }
  });
  const stopRail = EDGE.on("app:ready", () => { stopRail?.(); applyRail(); });
  // Build actions for the command palette (Ctrl+K)
  const A = (id, label, run, extra = {}) => EDGE.palette?.register?.({id: "build." + id, label, run, group: "Action", ...extra});
  const inBuild = () => !!S.exp && !S.noDoc;
  A("add-device", "Add a device…", () => { EDGE.go("build"); openAddDevice(); }, {icon: "device", when: inBuild});
  A("quick-add", "Add an item to this screen…", () => quickAdd(), {icon: "plus", keys: "/", when: () => inBuild() && S.ws === "build" && S.view === "screen"});
  A("story", "Show the storyboard", () => setBuildView("story"), {icon: "storyboard", when: inBuild});
  A("density", "Storyboard: switch between cards and a list", () => { setStoryDensity(storyDensity() === "list" ? "cards" : "list"); setBuildView("story"); renderAll(); }, {icon: "list", when: inBuild});
  A("focus", "Focus on the screen (hide the timeline)", () => { if (S.view !== "screen" && S.routine) openScreen(S.routine); toggleBigPreview(); }, {icon: "expand", when: () => inBuild() && !!S.routine});
});
