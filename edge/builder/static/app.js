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
};

const SCHED_FIELDS = {
  start: {type: "float", default: 0, help: "seconds from routine start (or expression)"},
  duration: {type: "float", default: null, help: "seconds; empty = until the routine ends"},
  start_after: {type: "component", default: null, help: "start when this component stops"},
  start_if: {type: "expr", default: null, help: "start when this expression becomes true"},
  stop_if: {type: "expr", default: null, help: "stop when this expression becomes true"},
  start_frame: {type: "int", default: null, help: "start on frame N (overrides start)"},
  duration_frames: {type: "int", default: null, help: "duration in frames (overrides duration)"},
  end_routine: {type: "bool", default: false, help: "end the routine when this responds or times out"},
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
  if (!r.ok || j.error) throw new Error(j.error || r.statusText);
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
  if (render) renderAll();
  scheduleValidate();
}
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
      if (n.if !== undefined) { walkFlow(fn, n.then ||= [], [...p, "then"]); walkFlow(fn, n.else ||= [], [...p, "else"]); }
    }
  });
}
function loopIds() { const s = new Set(); walkFlow((n) => { if (n?.loop) s.add(n.loop); }); return s; }

/* ------------------------------------------------------------------ boot */
async function boot() {
  S.schema = await api("/api/schema");
  const files = (await api("/api/files")).files;
  const last = localStorage.getItem("edge.last");
  if (last && files.some((f) => f.path === last)) await openFile(last);
  else if (files.length === 1) await openFile(files[0].path);
  else loadDoc(clone(await api("/api/template?name=blank")), null);
  wire();
}

function loadDoc(exp, path) {
  S.exp = normalize(exp); S.path = path; S.history = []; S.future = []; S._snapshot = JSON.stringify(S.exp);
  S.routine = routineInFlowOrder()[0] || Object.keys(S.exp.routines)[0] || null;
  S.sel = S.routine ? {kind: "routine", routine: S.routine} : {kind: "settings"};
  $("#filename").textContent = path || "untitled (not saved)";
  setDirty(false); renderAll(); validate();
}
function routineInFlowOrder() { const out = []; walkFlow((n) => { const r = routineOfNode(n); if (typeof r === "string" && !out.includes(r)) out.push(r); }); return out; }

async function openFile(path) {
  loadDoc(await api(`/api/experiment?path=${encodeURIComponent(path)}`), path);
  localStorage.setItem("edge.last", path);
}

async function save(asNew = false) {
  let path = S.path;
  if (!path || asNew) {
    path = prompt("Save as (path relative to the builder folder):", `${S.exp.name || "experiment"}.yaml`);
    if (!path) return;
  }
  await api(`/api/experiment?path=${encodeURIComponent(path)}`, S.exp);
  S.path = path; localStorage.setItem("edge.last", path);
  $("#filename").textContent = path; setDirty(false); toast("Saved " + path);
}

/* ------------------------------------------------------------------ render */
function renderAll() {
  renderPalette(); renderDevices(); renderRoutineTabs(); renderTimeline(); renderFlow(); renderProps(); renderPreview();
  if ($("#tab-source").classList.contains("active")) renderSource();
}

function renderPalette() {
  const f = $("#palette-filter").value.toLowerCase();
  const el = $("#palette"); el.innerHTML = "";
  const cats = {};
  for (const [type, d] of Object.entries(S.schema.components)) {
    if (f && !(type + d.description).toLowerCase().includes(f)) continue;
    (cats[d.category] ||= []).push([type, d]);
  }
  const order = ["stimulus", "response", "eyetracking", "hardware", "logic", "other"];
  for (const cat of order) {
    if (!cats[cat]) continue;
    el.append(h("div", {class: "pal-cat"}, cat));
    for (const [type, d] of cats[cat].sort()) {
      el.append(h("div", {class: "pal-item", title: d.description, draggable: "true",
        ondragstart: (e) => e.dataTransfer.setData("edge/component", type),
        onclick: () => addComponent(type)}, h("span", {class: `dot cat-${cat}`}), type));
    }
  }
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
  for (const rid of Object.keys(S.exp.routines)) {
    el.append(h("div", {class: "rtab" + (rid === S.routine ? " active" : ""),
      onclick: () => { S.routine = rid; S.sel = {kind: "routine", routine: rid}; S.previewT = 0; renderAll(); },
      ondblclick: () => renameRoutine(rid)}, rid));
  }
  el.append(h("div", {class: "rtab add", title: "New routine", onclick: () => newRoutine()}, "+ routine"));
}

function numOr(v, d) { return typeof v === "number" ? v : d; }

function routineSpan(rid) {
  const r = S.exp.routines[rid];
  let max = numOr(r?.duration, 0);
  for (const c of comps(rid)) max = Math.max(max, numOr(c.start, 0) + numOr(c.duration, 0.5));
  return Math.max(2, Math.ceil(max * 1.15 * 2) / 2);
}

function renderTimeline() {
  const el = $("#timeline"); el.innerHTML = "";
  const rid = S.routine;
  if (!rid) { el.append(h("div", {class: "tl-empty"}, "No routines yet. Click “+ routine”.")); return; }
  const r = S.exp.routines[rid];
  const span = routineSpan(rid);
  $("#preview-t").max = span;
  el.append(h("div", {class: "tl-routine-info", onclick: () => { S.sel = {kind: "routine", routine: rid}; renderProps(); }},
    `Routine “${rid}”`, r.duration != null ? ` · duration ${r.duration}s` : "", r.end_if ? ` · ends if ${r.end_if}` : "",
    " · drag bars to move, drag right edge to resize, drop components here"));
  const ruler = h("div", {class: "tl-ruler"});
  const step = span > 10 ? 2 : span > 4 ? 1 : 0.5;
  for (let t = 0; t <= span + 1e-9; t += step) ruler.append(h("span", {style: `left:${(t / span) * 100}%`}, t + "s"));
  el.append(ruler);
  if (!comps(rid).length) el.append(h("div", {class: "tl-empty"}, "Empty routine — click a component in the palette or drag it here."));
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
        h("span", {class: `dot cat-${cat}`}), h("b", {}, c.id), h("span", {class: "ty"}, c.type)), track);
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
  return h("span", {class: "fl-add", title: "Insert here", onclick: (e) => flowInsertMenu(e, listPath, index)}, "+");
}

function samePath(a, b) { return a && b && a.length === b.length && a.every((x, i) => x === b[i]); }

function renderNode(n, path) {
  const selected = S.sel && ["loop", "branch", "flowref"].includes(S.sel.kind) && samePath(S.sel.path, path);
  if (typeof n === "string" || (n && n.routine !== undefined)) {
    const rid = routineOfNode(n);
    return h("div", {class: "fl-routine" + (rid === S.routine ? " active" : "") + (selected ? " sel" : ""),
      title: n.if ? `runs only if ${n.if}` : "click: edit routine · right-click: options",
      onclick: () => { S.routine = rid; S.sel = {kind: "routine", routine: rid, path}; S.previewT = 0; renderAll(); },
      oncontextmenu: (e) => { e.preventDefault(); nodeMenu(e, path); }}, rid, n.if ? " ⁇" : "");
  }
  if (n.loop !== undefined) {
    const desc = n.staircase ? `staircase on ${n.staircase.variable || "level"}` :
      `${n.order || "sequential"}${n.repeats && n.repeats !== 1 ? " × " + n.repeats : ""}`;
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
  setTimeout(() => document.addEventListener("click", () => m.remove(), {once: true}), 0);
}

function flowInsertMenu(e, listPath, index) {
  const list = getNode(listPath);
  const items = Object.keys(S.exp.routines).map((rid) => [`Routine: ${rid}`, () => { list.splice(index, 0, rid); commit(); }]);
  items.push("-",
    ["New routine…", () => { const rid = newRoutine(false); if (rid) { list.splice(index, 0, rid); commit(); } }],
    ["Loop", () => { const id = uniqueId("trials", loopIds()); list.splice(index, 0, {loop: id, order: "random", repeats: 1, conditions: [{}], children: []});
      S.sel = {kind: "loop", path: [...listPath, index]}; commit(); }],
    ["Branch (if / else)", () => { list.splice(index, 0, {if: "$True", then: [], else: []}); S.sel = {kind: "branch", path: [...listPath, index]}; commit(); }]);
  menu(e, items);
}

function nodeMenu(e, path) {
  const {list, index} = parentOf(path);
  menu(e, [
    ["Move left", () => { if (index > 0) { [list[index - 1], list[index]] = [list[index], list[index - 1]]; commit(); } }],
    ["Move right", () => { if (index < list.length - 1) { [list[index + 1], list[index]] = [list[index], list[index + 1]]; commit(); } }],
    ["Wrap in loop", () => { list[index] = {loop: uniqueId("block", loopIds()), order: "sequential", repeats: 2, children: [list[index]]}; commit(); }],
    ["Run only if…", () => { const c = prompt("Expression (e.g. $score > 5):", "$True"); if (!c) return;
      const n = list[index]; if (typeof n === "string" || n.routine) list[index] = {routine: routineOfNode(n), if: c};
      else list[index] = {if: c, then: [n], else: []}; commit(); }],
    "-",
    ["Remove from flow", () => { list.splice(index, 1); S.sel = null; commit(); }],
  ]);
}

/* ---------------- components & routines */
function addComponent(type, at) {
  if (!S.routine) newRoutine(false);
  const rid = S.routine;
  const d = S.schema.components[type];
  const c = {id: uniqueId(type === "keyboard" ? "resp" : type, new Set(comps(rid).map((x) => x.id))), type};
  for (const [k, p] of Object.entries(d.props)) if (p.required) c[k] = p.default ?? (p.type === "text" || p.type === "str" ? "" : null);
  if (type === "text") c.text = "Hello";
  if (type === "keyboard") { c.keys = ["space"]; c.end_routine = true; }
  if (type === "marker") c.label = "event";
  if (d.visual && !["slider"].includes(type) && !comps(rid).some((x) => x.end_routine) && S.exp.routines[rid].duration == null) c.duration = 1.0;
  if (at != null) comps(rid).splice(at, 0, c); else comps(rid).push(c);
  S.sel = {kind: "component", routine: rid, id: c.id};
  commit();
}

function selectComp(rid, id, render = true) { S.routine = rid; S.sel = {kind: "component", routine: rid, id}; if (render) renderAll(); }

function newRoutine(render = true) {
  const rid = prompt("Routine name:", uniqueId("routine", new Set(Object.keys(S.exp.routines))));
  if (!rid) return null;
  const id = uniqueId(rid, new Set(Object.keys(S.exp.routines)));
  S.exp.routines[id] = {components: []};
  S.routine = id; S.sel = {kind: "routine", routine: id};
  if (render) commit(); return id;
}

function renameRoutine(rid) {
  const nid = prompt("Rename routine:", rid);
  if (!nid || nid === rid) return;
  if (S.exp.routines[nid]) return toast("A routine with that name exists");
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
  const el = $("#props"); el.innerHTML = "";
  const sel = S.sel || {kind: "settings"};
  const title = $("#props-title");
  if (sel.kind === "component") {
    const c = findComp(sel.routine, sel.id); if (!c) return;
    const d = S.schema.components[c.type];
    title.textContent = `${c.id} · ${c.type}`;
    el.append(h("div", {class: "desc"}, d?.description || "Unknown component type"));
    el.append(field("id", {type: "str"}, c.id, (v) => renameComp(c, v), {noExpr: true}));
    el.append(h("div", {class: "group"}, "Properties"));
    for (const [k, p] of Object.entries(d?.props || {})) el.append(field(k, p, c[k], (v) => setProp(c, k, v)));
    el.append(h("div", {class: "group"}, "Timing"));
    for (const [k, p] of Object.entries(SCHED_FIELDS)) el.append(field(k, p, c[k], (v) => setProp(c, k, v)));
    const custom = Object.keys(c).filter((k) => !SCHED_KEYS.has(k) && !(d?.props || {})[k]);
    if (custom.length) { el.append(h("div", {class: "group"}, "Other")); for (const k of custom) el.append(field(k, {type: "json"}, c[k], (v) => setProp(c, k, v))); }
    const list = comps(sel.routine); const i = list.indexOf(c);
    el.append(h("div", {class: "btns"},
      h("button", {onclick: () => { if (i > 0) { [list[i - 1], list[i]] = [list[i], list[i - 1]]; commit(); } }, title: "Draw earlier (behind)"}, "↑"),
      h("button", {onclick: () => { if (i < list.length - 1) { [list[i + 1], list[i]] = [list[i], list[i + 1]]; commit(); } }, title: "Draw later (on top)"}, "↓"),
      h("button", {onclick: () => { const cp = clone(c); cp.id = uniqueId(c.id, new Set(list.map((x) => x.id))); list.splice(i + 1, 0, cp); S.sel.id = cp.id; commit(); }}, "Duplicate"),
      h("button", {class: "danger", onclick: () => { list.splice(i, 1); S.sel = {kind: "routine", routine: sel.routine}; commit(); }}, "Delete")));
  } else if (sel.kind === "routine") {
    const r = S.exp.routines[sel.routine]; if (!r) return;
    title.textContent = `Routine · ${sel.routine}`;
    el.append(h("div", {class: "desc"}, "A routine is one screen/event sequence (a trial, instructions, feedback). Add components from the palette."));
    el.append(field("name", {type: "str"}, sel.routine, (v) => renameRoutine(sel.routine), {noExpr: true, readonlyClick: () => renameRoutine(sel.routine)}));
    el.append(field("duration", {type: "float", help: "hard limit in seconds (empty = until components end)"}, r.duration, (v) => setProp(r, "duration", v)));
    el.append(field("end_if", {type: "expr", help: "end when this expression becomes true"}, r.end_if, (v) => setProp(r, "end_if", v)));
    el.append(field("description", {type: "text"}, r.description, (v) => setProp(r, "description", v), {noExpr: true}));
    el.append(h("div", {class: "btns"},
      h("button", {onclick: () => { const nid = uniqueId(sel.routine, new Set(Object.keys(S.exp.routines))); S.exp.routines[nid] = clone(r); S.routine = nid; S.sel = {kind: "routine", routine: nid}; commit(); }}, "Duplicate"),
      h("button", {class: "danger", onclick: () => deleteRoutine(sel.routine)}, "Delete routine")));
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
  if (!confirm(`Delete routine “${rid}” and remove it from the flow?`)) return;
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
  let exprMode = isExpr(value) || type === "expr";
  const fx = opts.noExpr || type === "expr" || type === "code" || type === "bool" ? null :
    h("span", {class: "fx" + (exprMode ? " on" : ""), title: "Toggle expression ($...)",
      onclick: () => { exprMode = !exprMode;
        if (exprMode) onChange("$" + (value === null || value === undefined ? "" : showVal(type, value)));
        else onChange(parseVal(type, String(value || "").replace(/^\$/, ""))); }}, "fx");
  wrap.append(h("label", {}, h("span", {}, name + (p.required ? " *" : "")), fx));
  let input;
  const commitText = (e) => {
    let raw = e.target.value;
    if (type === "expr" && raw && !raw.startsWith("$")) raw = "$" + raw;
    const v = exprMode && type !== "expr" ? (raw.startsWith("$") ? raw : "$" + raw) : parseVal(type, raw);
    if (JSON.stringify(v) !== JSON.stringify(value ?? null)) onChange(v);
  };
  if (exprMode && type !== "code") {
    input = h("input", {class: "expr", value: value ?? "", placeholder: "$expression", onchange: commitText});
  } else if (type === "bool") {
    input = h("input", {type: "checkbox", onchange: (e) => onChange(e.target.checked)});
    input.checked = value ?? p.default ?? false;
  } else if (type === "choice") {
    input = h("select", {onchange: (e) => onChange(e.target.value === "" ? null : e.target.value)},
      (p.choices || []).map((c) => { const o = h("option", {value: c}, c === "" ? "(default)" : c); if ((value ?? p.default) === c) o.selected = true; return o; }));
  } else if (type === "text" || type === "code" || type === "dict" || type === "json") {
    input = h("textarea", {rows: type === "code" ? 6 : 3, onchange: commitText}, showVal(type, value));
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
    input = h("input", {value: showVal(type, value), placeholder: p.default != null ? showVal(type, p.default) : "", onchange: commitText});
  }
  wrap.append(input);
  if (p.help) wrap.append(h("div", {class: "help"}, p.help));
  return wrap;
}

function renderLoopProps(el, n, title) {
  title.textContent = `Loop · ${n.loop}`;
  el.append(h("div", {class: "desc"}, "Repeats its children once per condition row. Rows become variables (use them as $column)."));
  el.append(field("id", {type: "str"}, n.loop, (v) => { if (v) { n.loop = v; commit(); } }, {noExpr: true}));
  const mode = n.staircase ? "staircase" : typeof n.conditions === "string" ? "file" :
    (n.conditions && n.conditions.factorial) ? "factorial" : n.conditions ? "table" : "none";
  el.append(field("conditions source", {type: "choice", choices: ["none", "table", "file", "factorial", "staircase"]}, mode, (v) => {
    delete n.staircase;
    if (v === "none") delete n.conditions;
    else if (v === "table") n.conditions = Array.isArray(n.conditions) ? n.conditions : [{condition: "A"}, {condition: "B"}];
    else if (v === "file") n.conditions = "conditions.csv";
    else if (v === "factorial") n.conditions = {factorial: {factor_a: ["a1", "a2"], factor_b: ["b1", "b2"]}};
    else if (v === "staircase") { delete n.conditions; n.staircase = {variable: "level", start: 0.5, step: [0.1, 0.05], down: 3, up: 1, min: 0, max: 1, reversals: 8, max_trials: 60, correct: "resp.corr"}; }
    commit();
  }, {noExpr: true}));
  if (mode === "table") el.append(condTable(n));
  if (mode === "file") {
    el.append(field("file", {type: "str", help: "CSV / TSV / XLSX / JSON, relative to the experiment file"}, n.conditions, (v) => { n.conditions = v; commit(); }, {noExpr: true}));
    const pv = h("div", {class: "help"}, "loading preview…"); el.append(pv);
    api(`/api/conditions?spec=${encodeURIComponent(JSON.stringify(n.conditions))}&exp=${encodeURIComponent(S.path || "")}`)
      .then((j) => { pv.replaceWith(rowsTable(j.rows.slice(0, 12))); }).catch((e) => pv.textContent = e.message);
  }
  if (mode === "factorial") el.append(field("factors", {type: "dict", help: '{"color": ["red","green"], "size": [1,2]} → all combinations'}, n.conditions.factorial, (v) => { n.conditions.factorial = v; commit(); }, {noExpr: true}));
  if (mode === "staircase") el.append(field("staircase", {type: "dict", help: "variable, start, step, down, up, min, max, reversals, max_trials, correct (expression), log"}, n.staircase, (v) => { n.staircase = v; commit(); }, {noExpr: true}));
  if (mode !== "staircase") {
    el.append(field("order", {type: "choice", choices: S.schema.loop_orders, help: "latin_square/counterbalance use the participant number"}, n.order || "sequential", (v) => setProp(n, "order", v), {noExpr: true}));
    el.append(field("repeats", {type: "int"}, n.repeats ?? 1, (v) => setProp(n, "repeats", v)));
    el.append(field("max_repeat", {type: "dict", help: '{"color": 2} or {"kind": {"deviant": 1}}: limit identical values in a row'}, n.max_repeat, (v) => setProp(n, "max_repeat", v), {noExpr: true}));
    el.append(field("select", {type: "str", help: 'subset of rows: "0:10" or [0, 3, 5]'}, n.select, (v) => setProp(n, "select", parseVal("json", v)), {noExpr: true}));
  }
  el.append(field("stop_if", {type: "expr", help: "checked after each iteration, e.g. $resp.corr == 0"}, n.stop_if, (v) => setProp(n, "stop_if", v)));
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
    const nc = e.target.value.trim(); if (!nc) { rows.forEach((r) => delete r[c]); } else rows.forEach((r) => { r[nc] = r[c]; if (nc !== c) delete r[c]; });
    commit(); }}))), h("th", {}, h("button", {class: "mini", title: "add column", onclick: () => { const nc = uniqueId("var", new Set(cols)); rows.forEach((r) => r[nc] = ""); if (!rows.length) rows.push({[nc]: ""}); commit(); }}, "+"))));
  rows.forEach((r, i) => tbl.append(h("tr", {}, cols.map((c) => h("td", {}, h("input", {value: showVal("", r[c]), onchange: (e) => {
    const raw = e.target.value; r[c] = raw !== "" && !isNaN(Number(raw)) ? Number(raw) : raw; commit(); }}))),
    h("td", {}, h("button", {class: "mini danger", onclick: () => { rows.splice(i, 1); commit(); }}, "×")))));
  return h("div", {class: "field"}, h("label", {}, "conditions"), h("div", {style: "overflow:auto"}, tbl),
    h("button", {class: "mini", style: "margin-top:4px", onclick: () => { rows.push(Object.fromEntries(cols.map((c) => [c, ""]))); commit(); }}, "+ row"));
}

function renderDeviceProps(el, d, index, title) {
  const info = S.schema.devices[d.type] || {options: {}, capabilities: []};
  title.textContent = `Device · ${d.id}`;
  el.append(h("div", {class: "desc"}, info.description || d.type,
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
  const cv = $("#preview"); const ctx = cv.getContext("2d");
  const win = S.exp.settings.window || {};
  const [W, H] = win.size || [1280, 720];
  cv.height = Math.round(cv.width * H / W);
  const k = cv.width / W;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = win.background || "#000"; ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.translate(cv.width / 2, cv.height / 2); ctx.scale(k, -k);
  const units = win.units || "px";
  const conv = (v, axis) => units === "norm" ? v * (axis === "x" ? W / 2 : H / 2) : units === "height" ? v * H : v;
  const pos = (p) => Array.isArray(p) ? [conv(+p[0] || 0, "x"), conv(+p[1] || 0, "y")] : [0, 0];
  const t = S.previewT; $("#preview-label").textContent = `t = ${t.toFixed(2)} s`;
  const row = sampleRowFor(S.routine);
  for (const c0 of comps(S.routine)) {
    const c = Object.fromEntries(Object.entries(c0).map(([kk, v]) => [kk, previewVal(v, row)]));
    const st = numOr(c.start, 0), du = numOr(c.duration, Infinity);
    if (c.start_after || c.start_if || t < st || t >= st + du || c.disabled === true) continue;
    const [x, y] = pos(c.pos || [0, 0]);
    ctx.save(); ctx.translate(x, y); ctx.globalAlpha = Math.max(0, Math.min(1, typeof c.opacity === "number" ? c.opacity : 1));
    ctx.rotate(-(numOr(c.ori, 0)) * Math.PI / 180);
    const color = (v, d) => (typeof v === "string" && !isExpr(v) ? v : d);
    if (c.type === "text") {
      ctx.scale(1, -1); ctx.fillStyle = color(c.color, "#fff");
      const hgt = conv(numOr(c.height, 40), "y"); ctx.font = `${c.bold ? "bold " : ""}${hgt}px sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const lines = String(c.text ?? "").split("\n"); lines.forEach((ln, i) => ctx.fillText(ln, 0, (i - (lines.length - 1) / 2) * hgt * 1.25));
    } else if (c.type === "shape" || c.type === "fixation") {
      const shape = c.shape || (c.type === "fixation" ? "cross" : "rect");
      ctx.fillStyle = color(c.fill, "#fff"); ctx.strokeStyle = color(c.line_color, color(c.fill, "#fff"));
      ctx.lineWidth = numOr(c.line_width, shape === "cross" ? 4 : 2);
      const sz = Array.isArray(c.size) ? [conv(c.size[0], "x"), conv(c.size[1], "y")] : [conv(numOr(c.size, shape === "cross" ? 40 : 100), "y"), conv(numOr(c.size, 100), "y")];
      if (shape === "rect") { ctx.fillRect(-sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); if (c.line_color) ctx.strokeRect(-sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); }
      else if (shape === "circle") { ctx.beginPath(); ctx.arc(0, 0, conv(numOr(c.radius, 50), "y"), 0, 2 * Math.PI); ctx.fill(); }
      else if (shape === "ellipse") { ctx.beginPath(); ctx.ellipse(0, 0, sz[0] / 2, sz[1] / 2, 0, 0, 2 * Math.PI); ctx.fill(); }
      else if (shape === "cross") { const s = sz[0] / 2; ctx.beginPath(); ctx.moveTo(-s, 0); ctx.lineTo(s, 0); ctx.moveTo(0, -s); ctx.lineTo(0, s); ctx.stroke(); }
      else if (shape === "polygon" && Array.isArray(c.vertices) && c.vertices.length) { ctx.beginPath(); c.vertices.forEach(([vx, vy], i) => i ? ctx.lineTo(conv(vx, "x"), conv(vy, "y")) : ctx.moveTo(conv(vx, "x"), conv(vy, "y"))); ctx.closePath(); ctx.fill(); }
    } else if (c.type === "image" && typeof c.image === "string" && !isExpr(c.image)) {
      const img = imgCache(c.image);
      if (img.complete && img.naturalWidth) { const sz = Array.isArray(c.size) ? [conv(c.size[0], "x"), conv(c.size[1], "y")] : [img.naturalWidth, img.naturalHeight];
        ctx.scale(1, -1); ctx.drawImage(img, -sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); }
      else { ctx.strokeStyle = "#888"; ctx.strokeRect(-100, -75, 200, 150); }
    } else if (c.type === "slider") {
      const sz = Array.isArray(c.size) ? c.size : [800, 30]; ctx.fillStyle = color(c.color, "#fff");
      ctx.fillRect(-sz[0] / 2, -2, sz[0], 4);
    } else if (c.type === "gaze_roi" && !c.target) {
      ctx.strokeStyle = "#a070ff"; ctx.setLineDash([8, 6]); ctx.lineWidth = 2;
      if ((c.shape || "circle") === "circle") { ctx.beginPath(); ctx.arc(0, 0, conv(numOr(c.radius, 100), "y"), 0, 2 * Math.PI); ctx.stroke(); }
      else { const sz = c.size || [200, 200]; ctx.strokeRect(-sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); }
    }
    ctx.restore();
  }
}
const _imgs = {};
function imgCache(src) { if (!_imgs[src]) { const im = new Image(); im.onload = renderPreview;
  im.src = `/api/file?path=${encodeURIComponent((S.path ? S.path.replace(/[^/]*$/, "") : "") + src)}`; _imgs[src] = im; } return _imgs[src]; }

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
  if (!S.issues.length) { el.append(h("div", {class: "ok"}, "✓ No problems found. Try a dry run.")); return; }
  for (const i of S.issues) el.append(h("div", {class: `issue ${i.level}`, onclick: () => gotoIssue(i)},
    `${i.level.toUpperCase()}  ${i.where}: ${i.message}${i.hint ? "  (" + i.hint + ")" : ""}`));
}
function gotoIssue(i) {
  const m = i.where.match(/^routines\.([^.]+)(?:\.([^.]+))?/);
  if (m && S.exp.routines[m[1]]) { S.routine = m[1]; S.sel = m[2] && findComp(m[1], m[2]) ? {kind: "component", routine: m[1], id: m[2]} : {kind: "routine", routine: m[1]}; renderAll(); }
  const d = i.where.match(/^devices\.(.+)/);
  if (d) { const idx = S.exp.devices.findIndex((x) => x.id === d[1]); if (idx >= 0) { S.sel = {kind: "device", index: idx}; renderAll(); } }
}

function showTab(name) {
  document.querySelectorAll("#console .tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll("#console .tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
  if (name === "source") renderSource();
}

async function renderSource() { $("#yaml").value = (await api("/api/to_yaml", S.exp)).yaml; }

async function dryRun() {
  showTab("results");
  const el = $("#tab-results"); el.innerHTML = "Running a virtual participant through the whole experiment…";
  try {
    const r = await api("/api/dryrun", {experiment: S.exp, path: S.path});
    if (!r.ok) { el.innerHTML = ""; el.append(h("div", {class: "issue error"}, "Fix errors first:"), r.issues.map((i) => h("div", {class: "issue error"}, `${i.where}: ${i.message}`))); return; }
    renderResults(r);
  } catch (e) { el.innerHTML = ""; el.append(h("pre", {class: "issue error"}, e.message)); }
}

function renderResults(r) {
  const el = $("#tab-results"); el.innerHTML = "";
  const t = r.summary.timing || {}, rep = r.report;
  const kpi = (v, l) => h("div", {class: "kpi"}, h("b", {}, v), h("span", {}, l));
  const mins = t.frames && t.refresh_rate_hz ? (t.frames / t.refresh_rate_hz / 60).toFixed(1) + " min" : "–";
  el.append(h("div", {class: "kpis"}, kpi(mins, "session length"), kpi(r.trials.length, "routine runs"),
    kpi(Object.keys(r.summary.devices).length, "devices (simulated)"), kpi(Object.keys(r.summary.marker_codebook).length, "marker labels"),
    kpi(r.summary.errors.length, "errors")));
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
function openModal() { $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); }

/* ---------------- wiring */
function wire() {
  $("#btn-new").onclick = newFromTemplate;
  $("#btn-open").onclick = openDialog;
  $("#btn-save").onclick = () => save();
  $("#btn-undo").onclick = undo; $("#btn-redo").onclick = redo;
  $("#btn-settings").onclick = () => { S.sel = {kind: "settings"}; renderAll(); };
  $("#btn-validate").onclick = () => { validate(); showTab("issues"); };
  $("#btn-dryrun").onclick = dryRun;
  $("#btn-run").onclick = runReal;
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
  });
  window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
}

boot().catch((e) => { document.body.innerHTML = `<pre style="padding:20px;color:#d33">Failed to start: ${e.message}</pre>`; });
