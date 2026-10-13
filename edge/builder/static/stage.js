/* stage.js: the screen preview as an editor (SPEC W4). Owner: P4a (split by P0; the widgets moved to widgets.js).
 * Owns ST and the stage interactions: click to select, drag to move with snapping, corner handles resize, the
 * round handle rotates, double-click text to type in place, arrow keys nudge, drop palette items or files from
 * the computer onto it (drawStageOverlay, startDrag, editInPlace, nudge, dropOnStage), the stage chrome (the
 * trial-row chip and the empty-screen drop zone: renderStageChrome), the Focus mode (toggleBigPreview), the
 * splitter between the stage and the timeline (wireSplitter) and wireStage(), which runs on DOMContentLoaded.
 */
"use strict";

/* ---------------------------------------------------------------- the screen preview as an editor */
const ST = {drag: null, guides: [], nudge: null};
const RESIZABLE = new Set(["text", "image", "shape", "fixation", "gaze_roi", "slider"]);
const ROTATABLE = new Set(["text", "image", "shape", "fixation"]);

function cvPoint(cv, e) {          // mouse → canvas pixels and window coordinates (px, y up, origin centre)
  const r = cv.getBoundingClientRect(), s = cv.width / r.width;
  const cx = (e.clientX - r.left) * s, cy = (e.clientY - r.top) * s;
  return {cx, cy, x: (cx - cv.width / 2) / cv._k, y: -(cy - cv.height / 2) / cv._k};
}
const toCanvas = (cv, x, y) => [cv.width / 2 + x * cv._k, cv.height / 2 - y * cv._k];
function local(b, x, y) { const t = b.rot * Math.PI / 180, dx = x - b.x, dy = y - b.y;
  return [Math.cos(t) * dx - Math.sin(t) * dy, Math.sin(t) * dx + Math.cos(t) * dy]; }
function world(b, lx, ly) { const t = -b.rot * Math.PI / 180;
  return [b.x + Math.cos(t) * lx - Math.sin(t) * ly, b.y + Math.sin(t) * lx + Math.cos(t) * ly]; }
function selBox(cv) { return S.sel?.kind === "component" && S.sel.routine === S.routine ? (cv._boxes || []).find((b) => b.id === S.sel.id) || null : null; }
function handles(cv, b) {
  const out = [];
  if (RESIZABLE.has(b.type) && !(b.type === "shape" && findComp(S.routine, b.id)?.shape === "line"))
    for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) out.push({kind: "resize", at: toCanvas(cv, ...world(b, sx * b.hw, sy * b.hh))});
  if (ROTATABLE.has(b.type)) out.push({kind: "rotate", at: toCanvas(cv, ...world(b, 0, b.hh + 26 / cv._k)), base: toCanvas(cv, ...world(b, 0, b.hh))});
  return out;
}

function drawStageOverlay(cv) {
  const ctx = cv.getContext("2d"); ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
  const dpr = cv.width / (cv.clientWidth || cv.width);
  for (const g of ST.guides) {
    ctx.strokeStyle = "#ff3d9a"; ctx.lineWidth = dpr; ctx.setLineDash([4 * dpr, 3 * dpr]); ctx.beginPath();
    if (g.axis === "x") { const [px] = toCanvas(cv, g.v, 0); ctx.moveTo(px, 0); ctx.lineTo(px, cv.height); }
    else { const [, py] = toCanvas(cv, 0, g.v); ctx.moveTo(0, py); ctx.lineTo(cv.width, py); }
    ctx.stroke();
  }
  const b = selBox(cv);
  if (b) {
    const outline = () => { ctx.beginPath();
      [[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(([sx, sy], i) => { const [px, py] = toCanvas(cv, ...world(b, sx * b.hw, sy * b.hh)); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
      ctx.closePath(); ctx.stroke(); };
    ctx.setLineDash([]);
    ctx.strokeStyle = "rgba(0,0,0,.4)"; ctx.lineWidth = 3.5 * dpr; outline();
    ctx.strokeStyle = "#4d8dff"; ctx.lineWidth = 1.5 * dpr; outline();
    for (const hd of handles(cv, b)) {
      ctx.fillStyle = "#fff"; ctx.strokeStyle = "#4d8dff"; ctx.lineWidth = 1.5 * dpr;
      if (hd.kind === "rotate") {
        ctx.beginPath(); ctx.moveTo(...hd.base); ctx.lineTo(...hd.at); ctx.stroke();
        ctx.beginPath(); ctx.arc(...hd.at, 5 * dpr, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
      } else { const s = 4 * dpr; ctx.beginPath(); ctx.rect(hd.at[0] - s, hd.at[1] - s, 2 * s, 2 * s); ctx.fill(); ctx.stroke(); }
    }
    if (ST.drag?.label) {
      ctx.font = `${11 * dpr}px sans-serif`; const w = ctx.measureText(ST.drag.label).width + 10 * dpr;
      const [px, py] = toCanvas(cv, ...world(b, 0, -b.hh)); const y = Math.min(cv.height - 18 * dpr, py + 8 * dpr);
      ctx.fillStyle = "rgba(20,30,50,.85)"; ctx.fillRect(px - w / 2, y, w, 16 * dpr);
      ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(ST.drag.label, px, y + 8 * dpr);
    }
  }
  ctx.restore();
}

function hitTest(cv, p) {
  const b = selBox(cv), dpr = cv.width / (cv.clientWidth || cv.width);
  if (b) for (const hd of handles(cv, b)) if (Math.hypot(hd.at[0] - p.cx, hd.at[1] - p.cy) <= 8 * dpr) return {box: b, kind: hd.kind};
  const tol = 4 / cv._k;
  const boxes = cv._boxes || [];
  for (let i = boxes.length - 1; i >= 0; i--) {
    const [lx, ly] = local(boxes[i], p.x, p.y);
    if (Math.abs(lx) <= boxes[i].hw + tol && Math.abs(ly) <= boxes[i].hh + tol) return {box: boxes[i], kind: "move"};
  }
  return null;
}

/* Which property a corner handle changes, and whether it can be changed by hand (not from the trial list). */
function resizeProp(c) {
  if (c.type === "text") return "height";
  const shape = c.shape || (c.type === "fixation" ? "cross" : c.type === "gaze_roi" ? "circle" : "rect");
  if (c.type === "slider" || c.type === "image") return "size";
  if (shape === "circle") return "radius";
  if (shape === "polygon") return "vertices";
  return "size";
}

function startDrag(cv, e) {
  if (!cv._k || e.button !== 0) return;
  const p = cvPoint(cv, e);
  const hit = hitTest(cv, p);
  if (!hit) {
    if (S.sel?.kind === "component") { S.sel = {kind: "routine", routine: S.routine}; renderProps(); renderTimeline(); renderPreview(); }
    return;
  }
  const c = findComp(S.routine, hit.box.id); if (!c) return;
  if (S.sel?.kind !== "component" || S.sel.id !== c.id) { S.sel = {kind: "component", routine: S.routine, id: c.id}; renderProps(); renderTimeline(); renderPreview(); }
  if (S.proposal) return;   // the assistant's preview is read-only
  const b = selBox(cv) || hit.box;
  const prop = hit.kind === "move" ? "pos" : hit.kind === "rotate" ? "ori" : resizeProp(c);
  if (isExpr(c[prop])) {
    const col = String(c[prop]).slice(1);
    return toast(`This ${prop === "pos" ? "position" : prop === "ori" ? "rotation" : "size"} comes from the trial list (“${col}”). Change it there, or make it the same on every trial in Properties.`);
  }
  e.preventDefault(); cv.focus();
  ST.drag = {kind: hit.kind, c, b: {...b}, p0: p, before: JSON.stringify(c), u: b.units, moved: false,
    size0: Array.isArray(c.size) ? [...c.size] : c.size, height0: numOr(c.height, 40), radius0: numOr(c.radius, c.type === "fixation" ? 6 : 50),
    verts0: Array.isArray(c.vertices) ? clone(c.vertices) : null};
  const mv = (ev) => dragMove(cv, ev);
  const up = () => { window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up); endDrag(); };
  window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
}

function dragMove(cv, e) {
  const d = ST.drag; if (!d) return;
  const p = cvPoint(cv, e), c = d.c, u = d.u, b = d.b;
  if (!d.moved && Math.hypot(p.cx - d.p0.cx, p.cy - d.p0.cy) < 3) return;
  d.moved = true; ST.guides = [];
  if (d.kind === "move") {
    let dx = p.x - d.p0.x, dy = p.y - d.p0.y;
    if (e.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
    let nx = b.x + dx, ny = b.y + dy;
    if (!e.altKey) {          // snap to the centre of the screen and to other things' centres
      const snap = 8 / cv._k;
      const xs = [0, ...(cv._boxes || []).filter((o) => o.id !== c.id).map((o) => o.x)];
      const ys = [0, ...(cv._boxes || []).filter((o) => o.id !== c.id).map((o) => o.y)];
      const bx = xs.find((v) => Math.abs(nx - v) < snap), by = ys.find((v) => Math.abs(ny - v) < snap);
      if (bx !== undefined) { nx = bx; ST.guides.push({axis: "x", v: bx}); }
      if (by !== undefined) { ny = by; ST.guides.push({axis: "y", v: by}); }
    }
    c.pos = [roundU(toUnits(nx, "x", u), u), roundU(toUnits(ny, "y", u), u)];
    d.label = `x ${c.pos[0]}, y ${c.pos[1]}`;
  } else if (d.kind === "rotate") {
    const a = Math.atan2(p.y - b.y, p.x - b.x) * 180 / Math.PI;
    let ori = 90 - a; ori = ((ori + 180) % 360 + 360) % 360 - 180;
    ori = e.shiftKey ? Math.round(ori / 15) * 15 : Math.round(ori);
    if (Math.abs(ori) <= 3) ori = 0;
    c.ori = ori; d.label = `${ori}°`;
  } else {
    const [lx, ly] = local(b, p.x, p.y);
    const ax = Math.max(1, Math.abs(lx)), ay = Math.max(1, Math.abs(ly));
    const f = Math.max(ax / Math.max(1, b.hw), ay / Math.max(1, b.hh));
    const prop = resizeProp(c);
    if (prop === "height") { c.height = Math.max(unitStep(u), roundU(d.height0 * f, u)); d.label = `letters ${c.height}`; }
    else if (prop === "radius") { c.radius = Math.max(unitStep(u), roundU(toUnits(Math.max(ax, ay), "y", u), u)); d.label = `radius ${c.radius}`; }
    else if (prop === "vertices" && d.verts0) { c.vertices = d.verts0.map(([vx, vy]) => [roundU(vx * f, u), roundU(vy * f, u)]); d.label = `${Math.round(f * 100)}%`; }
    else if (c.type === "fixation" && !Array.isArray(c.size)) { c.size = Math.max(unitStep(u), roundU(toUnits(2 * Math.max(ax, ay), "y", u), u)); d.label = `size ${c.size}`; }
    else {
      const keep = (c.type === "image") !== e.shiftKey;   // pictures keep their proportions unless Shift is held; shapes the other way round
      const w = keep ? 2 * b.hw * f : 2 * ax, hh = keep ? 2 * b.hh * f : 2 * ay;
      c.size = [Math.max(unitStep(u), roundU(toUnits(w, "x", u), u)), Math.max(unitStep(u), roundU(toUnits(hh, "y", u), u))];
      d.label = `${c.size[0]} × ${c.size[1]}`;
    }
  }
  renderPreview();
}

function endDrag() {
  const d = ST.drag; ST.drag = null; ST.guides = [];
  if (d && d.moved && JSON.stringify(d.c) !== d.before) commit(d.kind === "move" ? `Move “${d.c.id}”` : d.kind === "rotate" ? `Rotate “${d.c.id}”` : `Resize “${d.c.id}”`); else renderPreview();
}

function hoverCursor(cv, e) {
  if (ST.drag || !cv._k) return;
  const hit = hitTest(cv, cvPoint(cv, e));
  cv.style.cursor = !hit ? "default" : hit.kind === "move" ? "move" : hit.kind === "rotate" ? "grab" : "nwse-resize";
  cv.title = hit ? `${friendlyName(hit.box.type)} “${hit.box.id}”: drag to move` + (hit.box.type === "text" ? ", double-click to type" : hit.box.type === "image" ? ", double-click to change the picture" : "") : "";
}

function editInPlace(cv, e) {
  const hit = hitTest(cv, cvPoint(cv, e)); if (!hit) return;
  const c = findComp(S.routine, hit.box.id); if (!c) return;
  if (S.proposal) return toast("Apply or discard the assistant's changes first");
  if (c.type === "image") return openAssetPicker("image", (v) => setProp(c, "image", v), c.image);
  if (c.type !== "text") return;
  if (isExpr(c.text)) return toast("This text comes from the trial list or a formula: edit it in Properties on the right.");
  const b = hit.box, r = cv.getBoundingClientRect(), s = r.width / cv.width;
  const [px, py] = toCanvas(cv, b.x, b.y);
  const w = Math.max(160, 2 * b.hw * cv._k * s + 40), hh = Math.max(40, 2 * b.hh * cv._k * s + 16);
  const ta = h("textarea", {class: "st-inplace", dir: "auto",
    style: `left:${px * s - w / 2}px;top:${py * s - hh / 2}px;width:${w}px;height:${hh}px;font-size:${Math.max(12, numOr(c.height, 40) * cv._k * s * (b.units === "px" ? 1 : fromUnits(1, "y", b.units)))}px;color:${colorHex(c.color) || "#fff"}`}, String(c.text ?? ""));
  let finished = false;
  const done = (keep) => { if (finished) return; finished = true; const v = ta.value; ta.remove(); if (keep && v !== c.text) setProp(c, "text", v); };
  ta.onkeydown = (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); done(true); } else if (ev.key === "Escape") { ev.stopPropagation(); done(false); } };
  ta.onblur = () => done(true);
  cv.parentElement.append(ta); ta.focus(); ta.select();
}

function nudge(cv, e) {
  const arrows = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1]};
  if (!arrows[e.key] || S.sel?.kind !== "component") return;
  const c = findComp(S.sel.routine, S.sel.id); if (!c || !(S.schema.components[c.type]?.props || {}).pos) return;
  e.preventDefault();
  if (S.proposal) return toast("Apply or discard the assistant's changes first");
  if (isExpr(c.pos)) return toast("The position comes from the trial list: change it there.");
  const u = compUnits(c), st = unitStep(u) * (e.shiftKey ? 10 : 1), [dx, dy] = arrows[e.key];
  const p0 = Array.isArray(c.pos) ? c.pos : [0, 0];
  if (!ST.nudge) ST.nudge = {before: JSON.stringify(c)};
  c.pos = [roundU(p0[0] + dx * st, u), roundU(p0[1] + dy * st, u)];
  renderPreview();
  clearTimeout(ST.nudge.t);
  ST.nudge.t = setTimeout(() => { ST.nudge = null; commit(`Move “${c.id}”`); }, 500);
}

/* Drop a palette item or files from the computer onto the screen: it appears where it was dropped. */
async function dropOnStage(cv, e) {
  e.preventDefault(); cv.classList.remove("drop"); $("#preview-wrap .stage-empty")?.classList.remove("drop");
  if (S.proposal) return toast("Apply or discard the assistant's changes first");
  const p = cvPoint(cv, e);
  const at = (type) => { const u = compUnits(null);
    return S.schema.components[type]?.props?.pos ? {pos: [roundU(toUnits(p.x, "x", u), u), roundU(toUnits(p.y, "y", u), u)]} : {}; };
  const type = e.dataTransfer.getData("edge/component");
  if (type) return addComponent(type, undefined, {props: at(type), picker: true});
  for (const f of [...e.dataTransfer.files]) {
    const kind = kindOf(f.name);
    if (!kind) { toast(`${f.name}: drop pictures, sounds or .html pages`, 4000); continue; }
    const rel = await uploadAsset(f, kind); if (!rel) return;
    const t = {image: "image", audio: "sound", html: "html"}[kind];
    addComponent(t, undefined, {props: {...at(t), [{image: "image", audio: "sound", html: "file"}[kind]]: rel}});
  }
}

/* Focus (#preview-big): the stage takes the whole canvas; the timeline and the flow strip come back with Esc. */
function toggleBigPreview(force) {
  const on = typeof force === "boolean" ? force : !$("#ws-build").classList.contains("focus");
  $("#ws-build").classList.toggle("focus", on);
  try { localStorage.setItem("edge.bigPreview", on ? "1" : ""); } catch {}
  const b = $("#preview-big");
  b.setAttribute("aria-pressed", on ? "true" : "false");
  const tip = on ? "Show the timeline again (Esc)" : "Focus: a bigger screen for arranging things";
  b.title = tip; b.setAttribute("aria-label", on ? "Leave focus" : "Focus");
  const lbl = b.querySelector(".lbl"); if (lbl) lbl.textContent = on ? "Leave focus" : "Focus";
  requestAnimationFrame(() => { if (S.exp) renderPreview(); });
}

/* The stage's chrome: the trial-row chip ("Row 1 of 9 · word RED · ink red") and the empty-screen drop zone. */
function renderStageChrome(cv) {
  const stack = cv.parentElement; if (!stack) return;
  const rid = S.routine;
  let chip = stack.querySelector(".trial-chip");
  const info = rid && typeof rowInfo === "function" ? rowInfo(rid) : null;
  if (info && info.count) {
    const row = sampleRowFor(rid);
    const used = [];
    for (const c of comps(rid)) for (const v of Object.values(c)) {
      if (!isExpr(v)) continue;
      for (const w of String(v).match(/[A-Za-z_]\w*/g) || []) if (w in row && !used.includes(w) && !(w in (S.exp.variables || {}))) used.push(w);
    }
    const txt = [`Row ${Math.min(S.rowIndex || 0, info.count - 1) + 1} of ${info.count}`, ...used.slice(0, 3).map((k) => `${k} ${short(String(row[k]), 14)}`)].join(" · ");
    if (!chip) { chip = h("span", {class: "trial-chip", "aria-hidden": "true"}); stack.append(chip); }
    chip.textContent = txt;
  } else chip?.remove();
  let empty = stack.querySelector(".stage-empty");
  const isEmpty = rid && S.exp.routines[rid] && !comps(rid).length;
  if (!isEmpty) { empty?.remove(); return; }
  if (empty && empty.dataset.rid === rid) return;
  empty?.remove();
  const add = (type) => h("button", {type: "button", class: "btn sm", onclick: () => addComponent(type)}, icon(TYPE_ICON[type] || "plus"), friendlyName(type));
  empty = h("div", {class: "stage-empty empty dropzone", "data-rid": rid},
    h("p", {}, "Drop pictures, sounds or web pages here, or pick something from Add."),
    h("div", {class: "actions"}, ["text", "image", "keyboard", "fixation"].filter((t) => S.schema.components[t]).map(add)));
  empty.addEventListener("dragover", (e) => { const t = e.dataTransfer.types; if (t.includes("edge/component") || t.includes("Files")) { e.preventDefault(); empty.classList.add("drop"); } });
  empty.addEventListener("dragleave", (e) => { if (e.target === empty) empty.classList.remove("drop"); });
  empty.addEventListener("drop", (e) => dropOnStage(cv, e));
  stack.append(empty);
}

function wireStage() {
  const cv = $("#preview"); if (!cv) return;
  cv.tabIndex = 0;
  cv.addEventListener("mousedown", (e) => startDrag(cv, e));
  cv.addEventListener("mousemove", (e) => hoverCursor(cv, e));
  cv.addEventListener("dblclick", (e) => editInPlace(cv, e));
  cv.addEventListener("keydown", (e) => nudge(cv, e));
  cv.addEventListener("dragover", (e) => { const t = e.dataTransfer.types; if (t.includes("edge/component") || t.includes("Files")) { e.preventDefault(); cv.classList.add("drop"); } });
  cv.addEventListener("dragleave", () => cv.classList.remove("drop"));
  cv.addEventListener("drop", (e) => dropOnStage(cv, e));
  cv.addEventListener("focus", () => { const hint = $("#stage-hint"); if (hint) hint.classList.add("on"); });
  cv.addEventListener("blur", () => $("#stage-hint")?.classList.remove("on"));
  const hint = $("#stage-hint");
  if (hint) { hint.textContent = "Click to select · drag to move · corners resize · the round handle rotates · double-click text to type · arrows nudge · Space plays"; hint.id = "stage-hint"; cv.setAttribute("aria-describedby", "stage-hint"); }
  $("#preview-big").onclick = () => toggleBigPreview();
  let big = false; try { big = !!localStorage.getItem("edge.bigPreview"); } catch {}
  if (big) toggleBigPreview(true);
  window.addEventListener("resize", () => { if (S.exp) renderPreview(); });
  wireSplitter();
}

/* P0: the splitter between the stage and the timeline (drag, or arrow keys); remembered in edge.layout. */
function wireSplitter() {
  const sp = $("#splitter"), view = $("#view-screen"); if (!sp || !view) return;
  const set = (pct, save) => {
    pct = Math.round(Math.max(25, Math.min(80, pct)));
    view.style.setProperty("--stage-split", pct + "%");
    sp.setAttribute("aria-valuenow", pct);
    if (S.exp && S.view === "screen") renderPreview();
    if (save) EDGE.prefs.set("layout", {...(EDGE.prefs.get("layout", {}) || {}), split: pct});
    return pct;
  };
  sp.setAttribute("aria-valuemin", "25"); sp.setAttribute("aria-valuemax", "80");
  sp.title = "Drag to resize the screen and the timeline (or use the arrow keys)";
  let cur = set(Number((EDGE.prefs.get("layout", {}) || {}).split) || 60, false);
  sp.addEventListener("mousedown", (e) => {
    e.preventDefault();
    const r = view.getBoundingClientRect();
    const mv = (ev) => { cur = set(((ev.clientY - r.top) / r.height) * 100, false); };
    const up = () => { window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up); set(cur, true); };
    window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
  });
  sp.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault(); cur = set(cur + (e.key === "ArrowUp" ? -5 : 5), true);
  });
}
window.addEventListener("DOMContentLoaded", wireStage);
