/* edit.js: multi-select and copy / paste in Build (builder editing, parts 1 and 2). Owner: builder editing.
 * Multi-select: Ctrl/Cmd-click (or Shift-click) adds items to the selection on the screen preview and the
 * timeline, and screens in the storyboard; dragging over an empty part of the preview, the timeline or the
 * storyboard draws a selection rectangle. Several items: S.sel = {kind: "components", routine, ids}; several
 * screens: S.sel = {kind: "routines", items: [{routine, path}]}. A group moves together (drag, arrow keys; on the
 * timeline its start times), and can be aligned, distributed, duplicated, deleted, copied, and given one value
 * for a property they share (Properties shows "Mixed" where they differ). Each action is one undo step.
 * Copy and paste: Ctrl/Cmd+C, X, V (and the context menus) copy items, screens (with their items) or a whole
 * trial list / if / workflow step, also between experiments and browser tabs: the system clipboard gets a JSON
 * payload, localStorage keeps a copy. Pasting renames what is taken (resp -> resp2, trial -> trial2), fixes the
 * references inside what was pasted ($resp.corr, start after, trial-list ids) and, from another experiment,
 * copies the pictures, sounds and trial-list files it uses into this experiment's folder (POST
 * /api/edit/paste_files, path-confined on the server).
 * Hooks into the other files are calls guarded by typeof: drawMultiOverlay (stage.js), itemInSelection /
 * screenInSelection / moveSelectedScreens / clipMenuItems / fileTableView (build.js), renderMultiProps
 * (inspector.js), fixMultiSelection / multiDelete / multiDuplicate (app.js).
 */
"use strict";

const ED = {band: null, drag: null, nudge: null, tlNudge: null, clipKey: "edge.clipboard"};
const ED_REF_PROPS = new Set(["start_after", "target", "clickable"]);

/* ================================================================== selection model */
function selectedItemIds(rid = S.routine) {
  const s = S.sel; if (!s || !rid) return [];
  if (s.kind === "components" && s.routine === rid) return s.ids.filter((id) => findComp(rid, id));
  if (s.kind === "component" && s.routine === rid) return findComp(rid, s.id) ? [s.id] : [];
  return [];
}
function itemInSelection(rid, id) { return S.sel?.kind === "components" && S.sel.routine === rid && S.sel.ids.includes(id); }
function setItemSelection(rid, ids, {render = true} = {}) {
  ids = [...new Set(ids)].filter((id) => findComp(rid, id));
  S.routine = rid;
  S.sel = !ids.length ? {kind: "routine", routine: rid} : ids.length === 1 ? {kind: "component", routine: rid, id: ids[0]}
    : {kind: "components", routine: rid, ids};
  if (render) renderAll();
  if (ids.length > 1) ui.announce(`${ids.length} items selected`);
}
function toggleItem(rid, id) {
  const cur = selectedItemIds(rid);
  setItemSelection(rid, cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]);
}

const edPathOfKey = (key) => key.split(".").map((x) => (/^\d+$/.test(x) ? +x : x));
function selectedScreens() {
  const s = S.sel; if (!s) return [];
  if (s.kind === "routines") return s.items;
  if (s.kind === "routine" && s.path) return [{routine: s.routine, path: s.path}];
  return [];
}
function screenInSelection(rid, path) { return S.sel?.kind === "routines" && S.sel.items.some((x) => x.routine === rid && samePath(x.path, path)); }
function setScreenSelection(items, {render = true} = {}) {
  const seen = new Set();
  items = items.filter((x) => { const k = JSON.stringify(x.path); if (seen.has(k)) return false; seen.add(k); return true; });
  if (!items.length) S.sel = null;
  else if (items.length === 1) { S.routine = items[0].routine; S.sel = {kind: "routine", routine: items[0].routine, path: items[0].path}; }
  else S.sel = {kind: "routines", items};
  if (render) renderAll();
  if (items.length > 1) ui.announce(`${items.length} screens selected`);
}
function cardInfo(card) {
  const key = card?.dataset.fkey || "";
  if (!key.startsWith("card:")) return null;
  return {routine: card.dataset.rid, path: edPathOfKey(key.slice(5))};
}
/* Called by fixSelection() after undo, redo and reloads: drop what no longer exists. */
function fixMultiSelection() {
  const s = S.sel; if (!s) return;
  if (s.kind === "components") {
    if (!S.exp.routines[s.routine]) { S.sel = null; return; }
    const ids = s.ids.filter((id) => findComp(s.routine, id));
    if (ids.length < 2) S.sel = ids.length ? {kind: "component", routine: s.routine, id: ids[0]} : {kind: "routine", routine: s.routine};
    else s.ids = ids;
  } else if (s.kind === "routines") {
    const items = s.items.filter((x) => { const n = nodeAt(x.path); return n !== undefined && isRoutineNode(n) && routineOfNode(n) === x.routine; });
    if (items.length < 2) S.sel = items.length ? {kind: "routine", routine: items[0].routine, path: items[0].path} : null;
    else s.items = items;
  }
}

/* ================================================================== the screen preview */
function edBoxes(cv) { return cv?._boxes || []; }
function drawMultiOverlay(cv) {
  const ids = S.sel?.kind === "components" && S.sel.routine === S.routine ? S.sel.ids : [];
  if (!ids.length && !ED.band?.stage) return;
  const ctx = cv.getContext("2d"); ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
  const dpr = cv.width / (cv.clientWidth || cv.width);
  const boxes = edBoxes(cv).filter((b) => ids.includes(b.id));
  let gx0 = Infinity, gy0 = Infinity, gx1 = -Infinity, gy1 = -Infinity;
  for (const b of boxes) {
    const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy]) => toCanvas(cv, ...world(b, sx * b.hw, sy * b.hh)));
    ctx.setLineDash([]);
    ctx.beginPath(); corners.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath();
    ctx.strokeStyle = "rgba(0,0,0,.4)"; ctx.lineWidth = 3.5 * dpr; ctx.stroke();
    ctx.strokeStyle = "#4d8dff"; ctx.lineWidth = 1.5 * dpr; ctx.stroke();
    for (const [x, y] of corners) { gx0 = Math.min(gx0, x); gy0 = Math.min(gy0, y); gx1 = Math.max(gx1, x); gy1 = Math.max(gy1, y); }
  }
  if (boxes.length > 1) {
    ctx.setLineDash([5 * dpr, 4 * dpr]); ctx.strokeStyle = "#4d8dff"; ctx.lineWidth = 1 * dpr;
    ctx.strokeRect(gx0 - 6 * dpr, gy0 - 6 * dpr, gx1 - gx0 + 12 * dpr, gy1 - gy0 + 12 * dpr);
    const label = ED.drag?.label || `${ids.length} items`;
    ctx.font = `${11 * dpr}px sans-serif`; const w = ctx.measureText(label).width + 10 * dpr;
    const y = Math.min(cv.height - 18 * dpr, gy1 + 10 * dpr), x = (gx0 + gx1) / 2;
    ctx.fillStyle = "rgba(20,30,50,.85)"; ctx.fillRect(x - w / 2, y, w, 16 * dpr);
    ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(label, x, y + 8 * dpr);
  }
  const band = ED.band?.stage ? ED.band : null;
  if (band) {
    const [ax, ay] = toCanvas(cv, band.x0, band.y0), [bx, by] = toCanvas(cv, band.x1, band.y1);
    ctx.setLineDash([]); ctx.fillStyle = "rgba(77,141,255,.15)"; ctx.strokeStyle = "#4d8dff"; ctx.lineWidth = 1 * dpr;
    ctx.fillRect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay));
    ctx.strokeRect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay));
  }
  ctx.restore();
}

/* Items whose position can be changed by hand (not from the trial list), with their units. */
function movableItems(rid, ids) {
  return ids.map((id) => findComp(rid, id)).filter((c) => c && (S.schema.components[c.type]?.props || {}).pos && !isExpr(c.pos)
    && !(Array.isArray(c.pos) && c.pos.some(isExpr)));
}

function stageMouseDown(cv, e) {
  if (e.button !== 0 || !cv._k || S.proposal || !S.routine) return;
  const p = cvPoint(cv, e), hit = hitTest(cv, p);
  const ctrl = e.ctrlKey || e.metaKey;
  const single = S.sel?.kind === "component" && S.sel.routine === S.routine ? S.sel.id : null;
  if (hit && hit.kind === "move" && (ctrl || (e.shiftKey && single && single !== hit.box.id) || (e.shiftKey && S.sel?.kind === "components"))) {
    e.stopImmediatePropagation(); e.preventDefault(); cv.focus();
    toggleItem(S.routine, hit.box.id);
    return;
  }
  if (hit && hit.kind === "move" && itemInSelection(S.routine, hit.box.id)) {
    e.stopImmediatePropagation(); e.preventDefault(); cv.focus();
    startGroupDrag(cv, e, p, hit.box.id);
    return;
  }
  if (!hit) {
    e.stopImmediatePropagation(); e.preventDefault(); cv.focus();
    const add = ctrl || e.shiftKey;
    ED.band = {stage: true, x0: p.x, y0: p.y, x1: p.x, y1: p.y, base: add ? selectedItemIds() : [], moved: false};
    const mv = (ev) => {
      const q = cvPoint(cv, ev);
      Object.assign(ED.band, {x1: q.x, y1: q.y});
      if (Math.hypot(q.cx - p.cx, q.cy - p.cy) > 4) ED.band.moved = true;
      renderPreview();
    };
    const up = () => {
      window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
      const b = ED.band; ED.band = null;
      if (!b.moved) {          // a click on an empty part: back to the screen (as before)
        if (S.sel?.kind === "component" || S.sel?.kind === "components") { S.sel = {kind: "routine", routine: S.routine}; renderAll(); } else renderPreview();
        return;
      }
      const x0 = Math.min(b.x0, b.x1), x1 = Math.max(b.x0, b.x1), y0 = Math.min(b.y0, b.y1), y1 = Math.max(b.y0, b.y1);
      const inside = edBoxes(cv).filter((o) => o.x + o.hw >= x0 && o.x - o.hw <= x1 && o.y + o.hh >= y0 && o.y - o.hh <= y1).map((o) => o.id);
      setItemSelection(S.routine, [...b.base, ...inside]);
    };
    window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
  }
}

function startGroupDrag(cv, e, p0, hitId) {
  const rid = S.routine, ids = selectedItemIds(rid);
  const items = movableItems(rid, ids).map((c) => ({c, u: compUnits(c), pos0: Array.isArray(c.pos) ? [+c.pos[0] || 0, +c.pos[1] || 0] : [0, 0]}));
  ED.drag = {p0, items, moved: false, before: JSON.stringify(comps(rid)), hitId};
  const mv = (ev) => {
    const d = ED.drag; if (!d) return;
    const q = cvPoint(cv, ev);
    if (!d.moved && Math.hypot(q.cx - p0.cx, q.cy - p0.cy) < 3) return;
    d.moved = true;
    let dx = q.x - p0.x, dy = q.y - p0.y;
    if (ev.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0; }
    for (const it of d.items) it.c.pos = [roundU(it.pos0[0] + toUnits(dx, "x", it.u), it.u), roundU(it.pos0[1] + toUnits(dy, "y", it.u), it.u)];
    d.label = `moved ${Math.round(dx)}, ${Math.round(dy)} px`;
    renderPreview();
  };
  const up = () => {
    window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
    const d = ED.drag; ED.drag = null;
    if (d.moved && JSON.stringify(comps(rid)) !== d.before) commit(`Move ${d.items.length} items`);
    else if (!d.moved) setItemSelection(rid, [d.hitId]);      // a click on one of them: just that one
    else renderPreview();
  };
  window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
}

/* Arrow keys move the whole group (1 or 10 px); one undo step when the keys rest. */
function groupNudge(e, rid) {
  const arrows = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1]};
  if (!arrows[e.key] || e.altKey || e.ctrlKey || e.metaKey) return false;
  const items = movableItems(rid, selectedItemIds(rid));
  e.preventDefault(); e.stopImmediatePropagation();
  if (!bEditable()) return true;
  if (!items.length) { toast("These positions come from the trial list: change them there."); return true; }
  const [dx, dy] = arrows[e.key];
  for (const c of items) {
    const u = compUnits(c), st = unitStep(u) * (e.shiftKey ? 10 : 1), p0 = Array.isArray(c.pos) ? c.pos : [0, 0];
    c.pos = [roundU((+p0[0] || 0) + dx * st, u), roundU((+p0[1] || 0) + dy * st, u)];
  }
  renderPreview();
  clearTimeout(ED.nudge); ED.nudge = setTimeout(() => { ED.nudge = null; commit(`Move ${items.length} items`); }, 500);
  return true;
}

/* ================================================================== align and distribute */
function edItemBounds(rid, ids) {
  const cv = $("#preview"), boxes = S.view === "screen" && S.routine === rid ? edBoxes(cv) : [];
  return movableItems(rid, ids).map((c) => {
    const u = compUnits(c), b = boxes.find((x) => x.id === c.id);
    const x = fromUnits(+c.pos?.[0] || 0, "x", u), y = fromUnits(+c.pos?.[1] || 0, "y", u);
    return {c, u, x, y, hw: b ? b.hw : 0, hh: b ? b.hh : 0};
  });
}
const ALIGN = [["left", "Align left edges"], ["hcenter", "Align centres (left to right)"], ["right", "Align right edges"],
  ["top", "Align top edges"], ["vcenter", "Align middles (top to bottom)"], ["bottom", "Align bottom edges"],
  ["hdist", "Space evenly left to right"], ["vdist", "Space evenly top to bottom"]];
function alignItems(how, rid = S.routine, ids = selectedItemIds(rid)) {
  if (!bEditable()) return;
  const bs = edItemBounds(rid, ids);
  if (bs.length < 2 || (how.endsWith("dist") && bs.length < 3)) return toast(how.endsWith("dist") ? "Select three or more items to space them evenly." : "Select two or more items to align them.");
  const set = (b, x, y) => { b.c.pos = [roundU(toUnits(x, "x", b.u), b.u), roundU(toUnits(y, "y", b.u), b.u)]; };
  const minL = Math.min(...bs.map((b) => b.x - b.hw)), maxR = Math.max(...bs.map((b) => b.x + b.hw));
  const minB = Math.min(...bs.map((b) => b.y - b.hh)), maxT = Math.max(...bs.map((b) => b.y + b.hh));
  if (how === "left") bs.forEach((b) => set(b, minL + b.hw, b.y));
  else if (how === "right") bs.forEach((b) => set(b, maxR - b.hw, b.y));
  else if (how === "hcenter") { const cx = (minL + maxR) / 2; bs.forEach((b) => set(b, cx, b.y)); }
  else if (how === "top") bs.forEach((b) => set(b, b.x, maxT - b.hh));
  else if (how === "bottom") bs.forEach((b) => set(b, b.x, minB + b.hh));
  else if (how === "vcenter") { const cy = (minB + maxT) / 2; bs.forEach((b) => set(b, b.x, cy)); }
  else if (how === "hdist") {
    const s = [...bs].sort((a, b) => a.x - b.x), first = s[0].x, step = (s[s.length - 1].x - first) / (s.length - 1);
    s.forEach((b, i) => set(b, first + i * step, b.y));
  } else if (how === "vdist") {
    const s = [...bs].sort((a, b) => b.y - a.y), first = s[0].y, step = (s[s.length - 1].y - first) / (s.length - 1);
    s.forEach((b, i) => set(b, b.x, first + i * step));
  }
  commit(`${ALIGN.find((a) => a[0] === how)?.[1] || "Align"} of ${bs.length} items`);
}

/* ================================================================== the timeline */
function timelineItemOf(el) {
  const k = (el.closest("[data-fkey]")?.dataset.fkey || "").replace(/^bar:/, "");
  const m = k.match(/^tl:(.*):([^:]+)$/);
  return m ? {routine: m[1], id: m[2]} : null;
}
function timelineMouseDown(e) {
  if (e.button !== 0 || S.proposal) return;
  const tl = $("#timeline");
  const ctrl = e.ctrlKey || e.metaKey;
  const it = e.target.closest(".tl-label, .tl-bar") ? timelineItemOf(e.target) : null;
  if (it && (ctrl || e.shiftKey)) {
    e.stopImmediatePropagation(); e.preventDefault();
    toggleItem(it.routine, it.id);
    return;
  }
  const bar = e.target.closest(".tl-bar");
  if (it && bar && !e.target.classList.contains("h") && itemInSelection(it.routine, it.id)) {
    e.stopImmediatePropagation();
    const c = findComp(it.routine, it.id);
    if (c) dragGroupBars(e, c, bar.parentElement, routineSpan(it.routine));
    return;
  }
  if (it || !e.target.closest(".tl-body") || e.target.closest("button, a, input, .tl-rules")) return;
  // a rectangle over the bars, from an empty part of the timeline
  e.preventDefault();
  const rid = S.routine, base = ctrl || e.shiftKey ? selectedItemIds(rid) : [];
  const band = h("div", {class: "ed-band"}); document.body.append(band);
  const x0 = e.clientX, y0 = e.clientY;
  let moved = false;
  const pick = (ev) => {
    const r = {l: Math.min(x0, ev.clientX), r: Math.max(x0, ev.clientX), t: Math.min(y0, ev.clientY), b: Math.max(y0, ev.clientY)};
    Object.assign(band.style, {left: r.l + "px", top: r.t + "px", width: r.r - r.l + "px", height: r.b - r.t + "px"});
    const ids = [];
    for (const bar of tl.querySelectorAll(".tl-bar")) {
      const q = bar.getBoundingClientRect(), row = bar.closest(".tl-row").getBoundingClientRect();
      const hit = q.right >= r.l && q.left <= r.r && row.bottom >= r.t && row.top <= r.b;
      bar.closest(".tl-row").classList.toggle("ed-hit", hit);
      if (hit) { const x = timelineItemOf(bar); if (x) ids.push(x.id); }
    }
    return ids;
  };
  const mv = (ev) => { if (Math.hypot(ev.clientX - x0, ev.clientY - y0) > 4) moved = true; if (moved) pick(ev); };
  const up = (ev) => {
    window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
    const ids = moved ? pick(ev) : [];
    band.remove();
    tl.querySelectorAll(".ed-hit").forEach((x) => x.classList.remove("ed-hit"));
    if (moved) setItemSelection(rid, [...base, ...ids]);
  };
  window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
}
/* Dragging a bar of a selected group moves every bar of the group in time. */
function dragGroupBars(e, c, track, span) {
  const rid = S.routine;
  if (!itemInSelection(rid, c.id)) return false;
  e.preventDefault(); e.stopPropagation();
  const items = selectedItemIds(rid).map((id) => findComp(rid, id)).filter((x) => x && !isExpr(x.start) && !x.start_after && !x.start_if);
  const s0 = new Map(items.map((x) => [x.id, numOr(x.start, 0)]));
  const rect = track.getBoundingClientRect(), x0 = e.clientX;
  let moved = false;
  const snap = (v) => Math.max(0, Math.round(v * 20) / 20);
  const minStart = Math.min(...s0.values());
  const mv = (ev) => {
    if (Math.abs(ev.clientX - x0) > 2) moved = true;
    if (!moved) return;
    const dt = Math.max(-minStart, ((ev.clientX - x0) / rect.width) * span);
    for (const x of items) x.start = snap(s0.get(x.id) + dt);
    renderTimeline(); renderPreview();
  };
  const up = () => {
    document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up);
    if (moved) commit(`Change the timing of ${items.length} items`); else setItemSelection(rid, [c.id]);
  };
  document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up);
  return true;
}
function timelineGroupKeys(e) {
  const it = e.target.closest?.(".tl-label, .tl-bar") ? timelineItemOf(e.target) : null;
  if (!it || !itemInSelection(it.routine, it.id) || e.altKey) return;
  const mod = e.ctrlKey || e.metaKey;
  if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !mod) {
    e.preventDefault(); e.stopImmediatePropagation();
    if (!bEditable()) return;
    const items = selectedItemIds(it.routine).map((id) => findComp(it.routine, id)).filter((x) => x && !isExpr(x.start) && !x.start_after && !x.start_if);
    const d = (e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 0.5 : 0.05);
    const dd = Math.max(d, -Math.min(...items.map((x) => numOr(x.start, 0))));
    for (const x of items) x.start = Math.round((numOr(x.start, 0) + dd) * 1000) / 1000;
    BUILD.focusKey = e.target.closest("[data-fkey]")?.dataset.fkey;
    renderTimeline(); renderPreview();
    clearTimeout(ED.tlNudge); ED.tlNudge = setTimeout(() => { ED.tlNudge = null; commit(`Change the timing of ${items.length} items`); }, 450);
    ui.announce(`${items.length} items moved ${dd > 0 ? "later" : "earlier"} by ${Math.abs(Math.round(dd * 1000) / 1000)} s`);
  } else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); e.stopImmediatePropagation(); multiDelete(); }
  else if (mod && e.key.toLowerCase() === "d") { e.preventDefault(); e.stopImmediatePropagation(); multiDuplicate(); }
}

/* ================================================================== the storyboard */
function storyClick(e) {
  const card = e.target.closest?.(".scard"); if (!card) return;
  if (!(e.ctrlKey || e.metaKey || e.shiftKey)) return;
  const info = cardInfo(card); if (!info || !S.exp.routines[info.routine]) return;
  e.stopImmediatePropagation(); e.preventDefault();
  const cur = selectedScreens();
  const has = cur.some((x) => samePath(x.path, info.path));
  setScreenSelection(has ? cur.filter((x) => !samePath(x.path, info.path)) : [...cur, info]);
}
function storyMouseDown(e) {
  if (e.button !== 0 || e.target.closest(".scard, .sitem, button, a, input, select, textarea, .frame-head, .ins-item, .alert, [draggable=true]")) return;
  const host = $("#flow"); if (!host) return;
  const ctrl = e.ctrlKey || e.metaKey || e.shiftKey;
  const base = ctrl ? selectedScreens() : [];
  const x0 = e.clientX, y0 = e.clientY;
  let moved = false, band = null;
  const pick = (ev) => {
    const r = {l: Math.min(x0, ev.clientX), r: Math.max(x0, ev.clientX), t: Math.min(y0, ev.clientY), b: Math.max(y0, ev.clientY)};
    Object.assign(band.style, {left: r.l + "px", top: r.t + "px", width: r.r - r.l + "px", height: r.b - r.t + "px"});
    const out = [];
    for (const card of host.querySelectorAll(".scard")) {
      const q = card.getBoundingClientRect();
      const hit = q.right >= r.l && q.left <= r.r && q.bottom >= r.t && q.top <= r.b;
      card.classList.toggle("ed-hit", hit);
      const info = hit && cardInfo(card);
      if (info && S.exp.routines[info.routine]) out.push(info);
    }
    return out;
  };
  const mv = (ev) => {
    if (!moved && Math.hypot(ev.clientX - x0, ev.clientY - y0) > 5) { moved = true; band = h("div", {class: "ed-band"}); document.body.append(band); }
    if (moved) { ev.preventDefault(); pick(ev); }
  };
  const up = (ev) => {
    window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
    if (!moved) return;
    const items = pick(ev);
    band.remove();
    host.querySelectorAll(".ed-hit").forEach((x) => x.classList.remove("ed-hit"));
    setScreenSelection([...base, ...items]);
  };
  window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
}
/* Dropping one card of a selected group on a + moves the whole group there, in its order (called by the drop target). */
function moveSelectedScreens(from, toList, toIndex) {
  const sel = selectedScreens();
  if (sel.length < 2 || !sel.some((x) => samePath(x.path, from))) return false;
  if (!bEditable()) return true;
  const dst = getNode(toList);
  // take the nodes out from the last to the first (paths stay valid), remembering where the target list ends up
  const sorted = [...sel].sort((a, b) => cmpPath(b.path, a.path));
  const nodes = [];
  let idx = toIndex;
  for (const s of sorted) {
    const {list, index} = parentOf(s.path);
    nodes.unshift(list.splice(index, 1)[0]);
    if (list === dst && index < idx) idx--;
  }
  dst.splice(idx, 0, ...nodes);
  const lp = pathOfList(dst);
  if (lp) setScreenSelection(nodes.map((n, i) => ({routine: routineOfNode(n), path: [...lp, idx + i]})), {render: false});
  else S.sel = null;
  commit(`Move ${nodes.length} screens`);
  ui.announce(`Moved ${nodes.length} screens`);
  return true;
}
function cmpPath(a, b) {
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    if (a[i] === b[i]) continue;
    return typeof a[i] === "number" && typeof b[i] === "number" ? a[i] - b[i] : String(a[i]).localeCompare(String(b[i]));
  }
  return a.length - b.length;
}
function storyKeys(e) {
  if (S.sel?.kind !== "routines" || !e.target.closest?.(".scard")) return;
  const info = cardInfo(e.target.closest(".scard"));
  if (!info || !screenInSelection(info.routine, info.path)) return;
  const mod = e.ctrlKey || e.metaKey;
  if (e.key === "Delete" || (e.key === "Backspace" && !mod)) { e.preventDefault(); e.stopImmediatePropagation(); multiDelete(); }
  else if (mod && e.key.toLowerCase() === "d") { e.preventDefault(); e.stopImmediatePropagation(); multiDuplicate(); }
}

/* ================================================================== group actions (one undo step each) */
function multiDelete() {
  const s = S.sel;
  if (s?.kind === "components") {
    if (!bEditable()) return true;
    const list = comps(s.routine), n = s.ids.length;
    for (const id of s.ids) { const i = list.findIndex((c) => c.id === id); if (i >= 0) list.splice(i, 1); }
    S.sel = {kind: "routine", routine: s.routine};
    commit(`Delete ${n} items`);
    undoToast(`Deleted ${n} items.`);
    return true;
  }
  if (s?.kind === "routines") {
    if (!bEditable()) return true;
    const sorted = [...s.items].sort((a, b) => cmpPath(b.path, a.path));
    for (const x of sorted) { const {list, index} = parentOf(x.path); list.splice(index, 1); }
    S.sel = null;
    commit(`Remove ${sorted.length} screens from the experiment`);
    undoToast(`Removed ${sorted.length} screens from the experiment. They are listed under “Not shown in the experiment”.`);
    return true;
  }
  return false;
}
function multiDuplicate() {
  const s = S.sel;
  if (s?.kind === "components") {
    if (!bEditable()) return true;
    const list = comps(s.routine);
    const copies = edCopyItems(s.ids.map((id) => findComp(s.routine, id)).filter(Boolean), s.routine, {offset: false});
    const last = Math.max(...s.ids.map((id) => list.findIndex((c) => c.id === id)));
    list.splice(last + 1, 0, ...copies);
    setItemSelection(s.routine, copies.map((c) => c.id), {render: false});
    commit(`Duplicate ${copies.length} items`);
    return true;
  }
  if (s?.kind === "routines") {
    if (!bEditable()) return true;
    const sorted = [...s.items].sort((a, b) => cmpPath(b.path, a.path));
    const made = [];
    for (const x of sorted) {
      const nid = copyRoutine(x.routine);
      const {list, index} = parentOf(x.path);
      list.splice(index + 1, 0, nid);
      made.unshift(nid);
    }
    S.sel = null;
    commit(`Duplicate ${made.length} screens`);
    toast(`Made copies: ${made.map((x) => `“${x}”`).join(", ")}`);
    return true;
  }
  return false;
}

/* ================================================================== Properties for several items or screens */
const MULTI_TYPES = new Set(["color", "float", "int", "bool", "choice", "str", "text", "vec2"]);
const MULTI_SKIP = new Set(["id", "type", "marker", "units", "start_frame", "duration_frames"]);
function sharedProps(list) {
  const schemas = list.map((c) => S.schema.components[c.type]?.props || {});
  const first = Object.entries(schemas[0] || {}).filter(([k, p]) => MULTI_TYPES.has(p.type || "str") && !MULTI_SKIP.has(k)
    && schemas.every((s) => s[k] && (s[k].type || "str") === (p.type || "str")));
  return first;
}
function mixedValue(list, k) {
  const vals = list.map((c) => JSON.stringify(c[k] ?? null));
  return {mixed: new Set(vals).size > 1, value: list[0][k]};
}
function multiField(list, k, p, label, rid) {
  const {mixed, value} = mixedValue(list, k);
  const f = field(k, p, mixed ? undefined : value, (v) => {
    if (!inspEditable()) return;
    for (const c of list) { if (v === null || v === undefined || v === "") delete c[k]; else c[k] = clone(v); }
    commit(`Change ${(label || k).toLowerCase()} of ${list.length} items`);
  }, {comp: list[0], routine: rid, placeholder: mixed ? "Mixed" : undefined, fkey: "multi:" + k});
  if (mixed) {
    f.classList.add("mixed");
    const row = f.querySelector(".lbl-row") || f;
    row.append(h("span", {class: "chip mixed-chip", title: "The selected items have different values: a new value replaces all of them"}, "Mixed"));
  }
  return f;
}
function renderMultiProps(el, sel) {
  if (sel.kind === "routines") return renderMultiScreens(el, sel);
  const rid = sel.routine, list = sel.ids.map((id) => findComp(rid, id)).filter(Boolean);
  inspHead({tile: "t-show", ic: "duplicate", over: `On “${rid}”`, name: `${list.length} items selected`,
    menu: () => [{label: "Copy", icon: "duplicate", shortcut: `${MOD} C`, run: () => copySelection()},
      {label: "Duplicate", icon: "duplicate", shortcut: `${MOD} D`, run: () => multiDuplicate()},
      {sep: true}, {label: "Delete", icon: "trash", danger: true, shortcut: "Delete", run: () => multiDelete()}]});
  const names = h("p", {class: "t-small ed-names"}, list.map((c, i) => [i ? ", " : "", h("button", {type: "button", class: "linkish", title: "Select only this item",
    onclick: () => setItemSelection(rid, [c.id])}, c.id)]));
  const head = inspSec(null); head.append(names, h("p", {class: "t-caption"}, `${MOD}-click or Shift-click adds or removes items; drag on an empty part of the screen to select with a rectangle.`));
  el.append(head);
  const movable = movableItems(rid, sel.ids);
  if (movable.length >= 2) {
    const arr = inspSec("Arrange", {caption: movable.length < list.length ? `${movable.length} of ${list.length} can be moved` : null});
    const ab = (how, ic, cls = "") => h("button", {type: "button", class: "btn ghost icon sm ed-align " + cls, "data-align": how, title: ALIGN.find((a) => a[0] === how)[1],
      "aria-label": ALIGN.find((a) => a[0] === how)[1], disabled: how.endsWith("dist") && movable.length < 3 ? "" : null, onclick: () => alignItems(how, rid)}, edAlignIcon(how));
    arr.append(h("div", {class: "ed-align-row", role: "group", "aria-label": "Align"}, ...["left", "hcenter", "right", "top", "vcenter", "bottom"].map((x) => ab(x)),
      h("span", {class: "ed-sep"}), ab("hdist"), ab("vdist")));
    el.append(arr);
  }
  const shared = sharedProps(list);
  const sec = inspSec("Shared properties", {caption: shared.length ? "a new value applies to all of them" : null});
  for (const [k, p] of shared) sec.append(multiField(list, k, p, inspPropWords(k, list[0].type).label, rid));
  for (const k of BASIC_TIMING) sec.append(multiField(list, k, SCHED_FIELDS[k], FIELD_LABELS[k], rid));
  el.append(sec);
  inspFoot(btn("Duplicate", () => multiDuplicate(), {ic: "duplicate"}), btn("Copy", () => copySelection(), {cls: "btn sm ghost"}),
    h("span", {class: "grow"}), btn("Delete", () => multiDelete(), {cls: "btn sm ghost danger-quiet", ic: "trash"}));
}
function edAlignIcon(how) {
  const lines = {left: "M4 3v18M8 7h12M8 15h8", right: "M20 3v18M4 7h12M8 15h8", hcenter: "M12 3v18M5 7h14M8 15h8",
    top: "M3 4h18M7 8v12M15 8v8", bottom: "M3 20h18M7 4v12M15 8v8", vcenter: "M3 12h18M7 5v14M15 8v8",
    hdist: "M4 4v16M20 4v16M10 7v10M14 7v10", vdist: "M4 4h16M4 20h16M7 10h10M7 14h10"}[how];
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", "ic"); svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "2"); svg.setAttribute("stroke-linecap", "round");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path"); path.setAttribute("d", lines); svg.append(path);
  return svg;
}
function renderMultiScreens(el, sel) {
  const items = sel.items.filter((x) => S.exp.routines[x.routine]);
  inspHead({tile: "t-screen", ic: "screen", over: "Storyboard", name: `${items.length} screens selected`,
    menu: () => [{label: "Copy", icon: "duplicate", shortcut: `${MOD} C`, run: () => copySelection()},
      {label: "Duplicate", icon: "duplicate", shortcut: `${MOD} D`, run: () => multiDuplicate()},
      {sep: true}, {label: "Remove from the experiment", shortcut: "Delete", run: () => multiDelete()},
      {label: "Delete screens", icon: "trash", danger: true, run: () => deleteScreens(items.map((x) => x.routine))}]});
  const head = inspSec(null);
  head.append(h("p", {class: "t-small ed-names"}, items.map((x, i) => [i ? " → " : "", h("button", {type: "button", class: "linkish", onclick: () => setScreenSelection([x])}, x.routine)])),
    h("p", {class: "t-caption"}, `${MOD}-click or Shift-click adds or removes screens; drag on an empty part of the storyboard to select with a rectangle. Drag one of them onto a + to move them all.`));
  el.append(head);
  const rs = [...new Set(items.map((x) => x.routine))].map((r) => S.exp.routines[r]);
  const sec = inspSec("Shared properties", {caption: "a new value applies to all of them"});
  const {mixed, value} = mixedValue(rs, "duration");
  const f = field("duration", {type: "float", unit: "s", placeholder: mixed ? "Mixed" : "until a response"}, mixed ? undefined : value, (v) => {
    if (!inspEditable()) return;
    for (const r of rs) { if (v === null || v === undefined || v === "") delete r.duration; else r.duration = v; }
    commit(`Change how long ${rs.length} screens last`);
  }, {label: "Lasts at most", noExpr: true, fkey: "multi:duration", help: "Empty: until a response."});
  if (mixed) { f.classList.add("mixed"); (f.querySelector(".lbl-row") || f).append(h("span", {class: "chip mixed-chip"}, "Mixed")); }
  sec.append(f);
  el.append(sec);
  inspFoot(btn("Duplicate", () => multiDuplicate(), {ic: "duplicate"}), btn("Copy", () => copySelection(), {cls: "btn sm ghost"}),
    h("span", {class: "grow"}), btn("Remove", () => multiDelete(), {cls: "btn sm ghost danger-quiet", ic: "trash"}));
}
function deleteScreens(rids) {
  if (!bEditable()) return;
  for (const rid of rids) {
    delete S.exp.routines[rid];
    const prune = (list) => { for (let i = list.length - 1; i >= 0; i--) { const n = list[i];
      if (isRoutineNode(n) && routineOfNode(n) === rid) list.splice(i, 1);
      else if (n && typeof n === "object") { if (n.children) prune(n.children); if (n.then) prune(n.then); if (n.else) prune(n.else);
        if (n.states) for (const st of Object.values(n.states)) if (st.run) prune(st.run); } } };
    prune(S.exp.flow);
  }
  if (!S.exp.routines[S.routine]) S.routine = routineInFlowOrder()[0] || Object.keys(S.exp.routines)[0] || null;
  S.sel = null;
  commit(`Delete ${rids.length} screens`);
  undoToast(`Deleted ${rids.length} screens.`);
}

/* ================================================================== copy and paste */
function edReplaceRefs(v, map, {exprOnly = false} = {}) {
  // names of items, screens or trial lists inside what is pasted: $resp.corr, start_after: resp, [resp, …]
  if (typeof v === "string") {
    if (isExpr(v)) {
      let out = v;
      for (const [a, b] of Object.entries(map)) {
        if (a === b) continue;
        out = out.replace(new RegExp(`(^|[^\\w.'"])${a.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=\\.\\w)`, "g"), (m, pre) => pre + b);
      }
      return out;
    }
    return !exprOnly && Object.prototype.hasOwnProperty.call(map, v) ? map[v] : v;
  }
  if (Array.isArray(v)) return v.map((x) => edReplaceRefs(x, map, {exprOnly}));
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, edReplaceRefs(x, map, {exprOnly: exprOnly || !ED_REF_PROPS.has(k)})]));
  return v;
}
function edReplaceExact(v, map) {
  if (typeof v === "string") return Object.prototype.hasOwnProperty.call(map, v) ? map[v] : v;
  if (Array.isArray(v)) return v.map((x) => edReplaceExact(x, map));
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, edReplaceExact(x, map)]));
  return v;
}
/* Copies of items for one screen: new names where taken, references between them fixed, optionally moved a little. */
function edCopyItems(items, rid, {offset = true} = {}) {
  const taken = new Set(comps(rid).map((c) => c.id));
  const map = {};
  for (const c of items) { const nid = uniqueId(c.id, taken); taken.add(nid); map[c.id] = nid; }
  return items.map((c) => {
    const cp = edReplaceRefs(clone(c), map);
    // a property that names another item (start_after, target) keeps its name unless that item was copied too
    for (const k of ED_REF_PROPS) if (typeof c[k] === "string") cp[k] = map[c[k]] ?? c[k];
    if (c.type === "mouse" && Array.isArray(c.clickable)) cp.clickable = c.clickable.map((x) => map[x] ?? x);
    cp.id = map[c.id];
    if (offset && Array.isArray(cp.pos) && !cp.pos.some(isExpr)) { const u = compUnits(cp); cp.pos = [roundU((+cp.pos[0] || 0) + toUnits(20, "x", u), u), roundU((+cp.pos[1] || 0) - toUnits(20, "y", u), u)]; }
    return cp;
  });
}
function edRoutinesIn(nodes, out = new Set()) {
  for (const n of nodes || []) {
    if (isRoutineNode(n)) out.add(routineOfNode(n));
    else if (n && typeof n === "object") { edRoutinesIn(n.children, out); edRoutinesIn(n.then, out); edRoutinesIn(n.else, out); for (const st of Object.values(n.states || {})) edRoutinesIn(st.run, out); }
  }
  return out;
}
function clipPayload() {
  const s = S.sel; if (!s || !S.exp) return null;
  const from = {path: S.noDoc ? null : S.path, root: S.root || "", name: S.exp.name || ""};
  const base = {edge: "edge-clipboard", v: 1, from, variables: clone(S.exp.variables || {}), devices: (S.exp.devices || []).map((d) => d.id)};
  if (s.kind === "component" || s.kind === "components") {
    const ids = selectedItemIds(s.routine);
    const items = comps(s.routine).filter((c) => ids.includes(c.id));        // in drawing order
    return items.length ? {...base, kind: "items", routine: s.routine, items: clone(items)} : null;
  }
  if (s.kind === "routine" || s.kind === "routines") {
    const sel = s.kind === "routines" ? [...s.items].sort((a, b) => cmpPath(a.path, b.path)) : [{routine: s.routine, path: s.path}];
    const flow = sel.map((x) => (x.path ? clone(nodeAt(x.path)) : x.routine)).filter((n) => n !== undefined);
    const routines = {};
    for (const r of edRoutinesIn(flow)) if (S.exp.routines[r]) routines[r] = clone(S.exp.routines[r]);
    return flow.length ? {...base, kind: "screens", flow, routines} : null;
  }
  if (["loop", "branch", "machine"].includes(s.kind) && s.path) {
    const n = nodeAt(s.path); if (!n || typeof n !== "object") return null;
    const routines = {};
    for (const r of edRoutinesIn([n])) if (S.exp.routines[r]) routines[r] = clone(S.exp.routines[r]);
    return {...base, kind: n.loop !== undefined ? "trial_list" : "flow", flow: [clone(n)], routines};
  }
  return null;
}
function clipWords(p) {
  if (!p) return "";
  if (p.kind === "items") return p.items.length === 1 ? `“${p.items[0].id}”` : `${p.items.length} items`;
  if (p.kind === "screens") return p.flow.length === 1 ? `the screen “${routineOfNode(p.flow[0])}”` : `${p.flow.length} screens`;
  if (p.kind === "trial_list") return `the trial list “${p.flow[0].loop}”`;
  return "the step";
}
function storeClip(p) {
  const text = JSON.stringify(p);
  try { localStorage.setItem(ED.clipKey, text); } catch { /* full or private */ }
  return text;
}
function copySelection({cut = false, viaEvent = null} = {}) {
  const p = clipPayload();
  if (!p) { toast("Select an item, a screen or a trial list to copy."); return null; }
  const text = storeClip(p);
  if (viaEvent) { viaEvent.clipboardData.setData("text/plain", text); viaEvent.preventDefault(); }
  else if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).catch(() => { /* localStorage has it */ });
  if (cut) {
    if (S.sel?.kind === "components" || S.sel?.kind === "routines") multiDelete();
    else if (typeof deleteSelection === "function" && (S.sel?.kind === "component" || S.sel?.kind === "routine")) {
      if (S.sel.kind === "routine" && S.sel.path && typeof removeFromFlow === "function") removeFromFlow(S.sel.path); else deleteSelection();
    } else if (S.sel?.path && typeof removeFromFlow === "function") removeFromFlow(S.sel.path);
    ui.announce(`Cut ${clipWords(p)}`);
  } else toast(`Copied ${clipWords(p)}. Paste with ${MOD}+V, also in another experiment.`, {ms: 2500});
  return p;
}
function parseClip(text) {
  if (!text || typeof text !== "string" || !text.trimStart().startsWith("{")) return null;
  try { const p = JSON.parse(text); return p && p.edge === "edge-clipboard" && p.v === 1 ? p : null; } catch { return null; }
}
async function readClip() {
  try { if (navigator.clipboard?.readText) { const p = parseClip(await navigator.clipboard.readText()); if (p) return p; } } catch { /* not allowed: localStorage */ }
  try { return parseClip(localStorage.getItem(ED.clipKey)); } catch { return null; }
}
function hasClip() { try { return !!parseClip(localStorage.getItem(ED.clipKey)); } catch { return false; } }

/* Copy the files the pasted part uses from the other experiment's folder; returns {renamed} (or null: nothing to do). */
async function edCarryFiles(p, fragment) {
  if (!p.from?.path || p.from.path === S.path) return null;
  if (p.from.root && S.root && p.from.root !== S.root) {
    toast("This was copied from an experiment in another folder: its pictures, sounds and trial-list files stay there. Add them with Files › Add files.", {tone: "warning", ms: 8000});
    return null;
  }
  if (!S.path || S.noDoc) { if (!(await EDGE.ensurePath({}))) return null; }
  try {
    const r = await api("/api/edit/paste_files", {from: p.from.path, to: S.path, fragment});
    const bits = [];
    if (r.copied?.length) bits.push(`copied ${countWord(r.copied.length, "file")} into this experiment's folder (${r.copied.slice(0, 3).join(", ")}${r.copied.length > 3 ? ", …" : ""})`);
    if (Object.keys(r.renamed || {}).length) bits.push(`renamed ${Object.entries(r.renamed).map(([a, b]) => `${a} → ${b}`).join(", ")} (a different file had that name)`);
    if (r.missing?.length) bits.push(`couldn't find ${r.missing.join(", ")}`);
    if (bits.length) toast(bits.join("; ").replace(/^./, (c) => c.toUpperCase()) + ".", {tone: r.missing?.length ? "warning" : undefined, ms: 7000});
    if (r.copied?.length && typeof renderFilesSoon === "function") { if (typeof BUILD !== "undefined" && BUILD.assets) BUILD.assets.at = 0; renderFilesSoon(); }
    return r;
  } catch (e) {
    toast(`The files couldn't be copied: ${e.message}`, {tone: "danger"});
    return null;
  }
}
function edMergeVariables(p) {
  const used = JSON.stringify([p.items, p.routines, p.flow]);
  for (const [k, v] of Object.entries(p.variables || {})) if (!(k in (S.exp.variables ||= {})) && new RegExp(`\\b${k}\\b`).test(used)) S.exp.variables[k] = v;
}
function edMissingDevices(p) {
  const have = new Set((S.exp.devices || []).map((d) => d.id)), miss = new Set();
  const scan = (c) => { if (c && typeof c.device === "string" && !have.has(c.device)) miss.add(c.device); };
  (p.items || []).forEach(scan);
  Object.values(p.routines || {}).forEach((r) => (r.components || []).forEach(scan));
  return [...miss];
}

async function pastePayload(p) {
  if (!p || !S.exp || S.noDoc) return false;
  if (!bEditable()) return true;
  if (p.kind === "items") return pasteItems(p);
  return pasteFlow(p);
}
async function pasteItems(p) {
  let rid = S.sel?.routine && S.exp.routines[S.sel.routine] && ["component", "components", "routine"].includes(S.sel?.kind) ? S.sel.routine
    : S.view === "screen" && S.exp.routines[S.routine] ? S.routine : null;
  if (!rid) { toast("Open or select a screen first: items are pasted onto a screen."); return true; }
  const files = await edCarryFiles(p, {routines: {_: {components: p.items}}});
  let items = edCopyItems(p.items, rid, {offset: p.routine === rid && p.from?.path === S.path});
  if (files?.renamed && Object.keys(files.renamed).length) items = items.map((c) => edReplaceExact(c, files.renamed));
  const list = comps(rid);
  const after = selectedItemIds(rid).map((id) => list.findIndex((c) => c.id === id)).filter((i) => i >= 0);
  list.splice(after.length ? Math.max(...after) + 1 : list.length, 0, ...items);
  edMergeVariables(p);
  S.routine = rid;
  setItemSelection(rid, items.map((c) => c.id), {render: false});
  if (S.view !== "screen") { S.view = "screen"; EDGE.emit("view", {view: "screen"}); }
  commit(`Paste ${items.length === 1 ? `“${items[0].id}”` : `${items.length} items`}`);
  const miss = edMissingDevices(p);
  if (miss.length) toast(`This experiment has no device called ${miss.map((x) => `“${x}”`).join(", ")}: add it under Devices, or choose another one in Properties.`, {tone: "warning", ms: 7000});
  return true;
}
async function pasteFlow(p) {
  const files = await edCarryFiles(p, {routines: p.routines, flow: p.flow});
  // new names for screens and trial lists that are taken here; references inside the pasted part follow
  const rmap = {}, takenR = new Set(Object.keys(S.exp.routines));
  for (const r of Object.keys(p.routines || {})) { const n = uniqueId(r, takenR); takenR.add(n); rmap[r] = n; }
  const lmap = {}, takenL = loopIds();
  const walk = (nodes) => (nodes || []).forEach((n) => {
    if (n && typeof n === "object") {
      for (const k of ["loop", "statemachine"]) if (typeof n[k] === "string") { const nn = uniqueId(n[k], takenL); takenL.add(nn); lmap[n[k]] = nn; }
      walk(n.children); walk(n.then); walk(n.else); for (const st of Object.values(n.states || {})) walk(st.run);
    }
  });
  walk(p.flow);
  const renameNodes = (nodes) => (nodes || []).map((n) => {
    if (typeof n === "string") return rmap[n] ?? n;
    if (!n || typeof n !== "object") return n;
    const o = {...n};
    if (typeof o.routine === "string") o.routine = rmap[o.routine] ?? o.routine;
    for (const k of ["loop", "statemachine"]) if (typeof o[k] === "string") o[k] = lmap[o[k]] ?? o[k];
    for (const k of ["children", "then", "else"]) if (Array.isArray(o[k])) o[k] = renameNodes(o[k]);
    if (o.states) o.states = Object.fromEntries(Object.entries(o.states).map(([sn, st]) => [sn, {...st, run: renameNodes(st.run)}]));
    for (const k of ["stop_if", "if"]) if (typeof o[k] === "string") o[k] = edReplaceRefs(o[k], lmap);
    return o;
  });
  let flow = renameNodes(clone(p.flow));
  let routines = Object.fromEntries(Object.entries(p.routines || {}).map(([r, def]) => [rmap[r], edReplaceRefs(clone(def), lmap, {exprOnly: true})]));
  if (files?.renamed && Object.keys(files.renamed).length) { flow = edReplaceExact(flow, files.renamed); routines = edReplaceExact(routines, files.renamed); }
  Object.assign(S.exp.routines, routines);
  // after the selected step (in its list), else at the end of the experiment
  let listPath = [], index = S.exp.flow.length;
  const at = S.sel?.path || (S.sel?.kind === "routines" ? [...S.sel.items].sort((a, b) => cmpPath(a.path, b.path)).pop()?.path : null);
  if (at && nodeAt(at) !== undefined) { listPath = at.slice(0, -1); index = at[at.length - 1] + 1; }
  const list = getNode(listPath) || S.exp.flow;
  list.splice(index, 0, ...flow);
  edMergeVariables(p);
  if (p.kind === "screens") setScreenSelection(flow.map((n, i) => ({routine: routineOfNode(n), path: [...listPath, index + i]})), {render: false});
  else S.sel = {kind: flow[0].loop !== undefined ? "loop" : flow[0].statemachine !== undefined ? "machine" : "branch", path: [...listPath, index]};
  if (S.view === "screen" && p.kind !== "screens") EDGE.emit("view", {view: S.view = "story"});
  const what = p.kind === "screens" ? (flow.length === 1 ? `the screen “${routineOfNode(flow[0])}”` : `${flow.length} screens`)
    : p.kind === "trial_list" ? `the trial list “${flow[0].loop}”` : "the step";
  commit(`Paste ${what}`);
  const renamed = Object.entries({...rmap, ...lmap}).filter(([a, b]) => a !== b);
  if (renamed.length) toast(`Pasted ${what}${renamed.length ? ` (renamed ${renamed.slice(0, 3).map(([a, b]) => `${a} → ${b}`).join(", ")}${renamed.length > 3 ? ", …" : ""}: the names were taken)` : ""}.`, {ms: 5000});
  const miss = edMissingDevices(p);
  if (miss.length) toast(`This experiment has no device called ${miss.map((x) => `“${x}”`).join(", ")}: add it under Devices.`, {tone: "warning", ms: 7000});
  return true;
}
async function pasteFromMenu() {
  const p = await readClip();
  if (!p) { toast(`Nothing to paste: copy an item, a screen or a trial list first (${MOD}+C).`); return; }
  await pastePayload(p);
}

/* Context-menu entries (the storyboard's ⋯ menu calls this; the preview and the timeline have their own menus). */
function clipMenuItems(path) {
  if (path && S.sel?.kind === "routines" && !S.sel.items.some((x) => samePath(x.path, path))) return [];
  return [{sep: true},
    {label: "Copy", icon: "duplicate", shortcut: `${MOD} C`, run: () => { if (path && !(S.sel?.kind === "routines")) edSelectPath(path); copySelection(); }},
    {label: "Paste after", icon: "plus", shortcut: `${MOD} V`, disabled: !hasClip(), run: () => { if (path && !(S.sel?.kind === "routines")) edSelectPath(path); pasteFromMenu(); }}];
}
function edSelectPath(path) {
  const n = nodeAt(path); if (n === undefined) return;
  if (isRoutineNode(n)) S.sel = {kind: "routine", routine: routineOfNode(n), path};
  else if (n.loop !== undefined) S.sel = {kind: "loop", path};
  else if (n.statemachine !== undefined) S.sel = {kind: "machine", path};
  else S.sel = {kind: "branch", path};
}
function itemMenu(e, rid, id) {
  if (id && !selectedItemIds(rid).includes(id)) setItemSelection(rid, [id]);
  const ids = selectedItemIds(rid), many = ids.length > 1, any = ids.length > 0;
  const items = [any ? {head: many ? `${ids.length} items` : "Item", name: many ? null : ids[0]} : {head: "Screen", name: rid},
    {label: "Copy", icon: "duplicate", shortcut: `${MOD} C`, disabled: !any, run: () => copySelection()},
    {label: "Cut", shortcut: `${MOD} X`, disabled: !any, run: () => copySelection({cut: true})},
    {label: "Paste", icon: "plus", shortcut: `${MOD} V`, disabled: !hasClip(), run: () => pasteFromMenu()},
    {label: "Duplicate", icon: "duplicate", shortcut: `${MOD} D`, disabled: !any, run: () => (many ? multiDuplicate() : duplicateSelection())},
    many && movableItems(rid, ids).length >= 2 ? {label: "Align", items: ALIGN.map(([how, label]) => ({label, disabled: how.endsWith("dist") && movableItems(rid, ids).length < 3, run: () => alignItems(how, rid, ids)}))} : null,
    {sep: true},
    {label: "Select all items", shortcut: `${MOD} A`, run: () => setItemSelection(rid, comps(rid).map((c) => c.id))},
    any ? {label: "Delete", icon: "trash", danger: true, shortcut: "Delete", run: () => (many ? multiDelete() : deleteSelection())} : null];
  ui.menu(e, items.filter(Boolean));
}

/* ================================================================== wiring */
function edEditableTarget(e) {
  const a = document.activeElement;
  if (typeof isTyping === "function" && isTyping()) return false;
  if (a?.closest?.(".le-grid, .ft-grid, #assistant-panel, #home-describe, .menu, [role=dialog]")) return false;
  const s = window.getSelection?.(); if (s && !s.isCollapsed && String(s).trim()) return false;      // text selected on the page
  return S.ws === "build" && !S.noDoc && !!S.exp;
}
function wireEditing() {
  const cv = $("#preview");
  if (cv) {
    cv.addEventListener("mousedown", (e) => stageMouseDown(cv, e), true);
    cv.addEventListener("keydown", (e) => { if (S.sel?.kind === "components" && S.sel.routine === S.routine) groupNudge(e, S.routine); }, true);
    cv.addEventListener("contextmenu", (e) => {
      if (!S.routine || !cv._k) return;
      e.preventDefault();
      const hit = hitTest(cv, cvPoint(cv, e));
      itemMenu(e, S.routine, hit?.box.id || null);
    });
  }
  const tl = $("#timeline");
  if (tl) {
    tl.addEventListener("mousedown", timelineMouseDown, true);
    tl.addEventListener("click", (e) => { if ((e.ctrlKey || e.metaKey || e.shiftKey) && e.target.closest(".tl-label")) { e.stopImmediatePropagation(); e.preventDefault(); } }, true);
    tl.addEventListener("keydown", timelineGroupKeys, true);
    tl.addEventListener("contextmenu", (e) => {
      const it = e.target.closest(".tl-label, .tl-bar") ? timelineItemOf(e.target) : null;
      if (!it && !e.target.closest(".tl-body")) return;
      e.preventDefault();
      itemMenu(e, S.routine, it?.id || null);
    });
  }
  const flow = $("#flow");
  if (flow) {
    flow.addEventListener("click", storyClick, true);
    flow.addEventListener("mousedown", storyMouseDown);
    flow.addEventListener("keydown", storyKeys, true);
    flow.addEventListener("contextmenu", (e) => {
      const card = e.target.closest(".scard");
      const info = card && cardInfo(card);
      if (info && S.sel?.kind === "routines" && screenInSelection(info.routine, info.path)) {
        e.preventDefault(); e.stopImmediatePropagation();
        const n = S.sel.items.length;
        ui.menu(e, [{head: `${n} screens`},
          {label: "Copy", icon: "duplicate", shortcut: `${MOD} C`, run: () => copySelection()},
          {label: "Cut", shortcut: `${MOD} X`, run: () => copySelection({cut: true})},
          {label: "Paste after", icon: "plus", shortcut: `${MOD} V`, disabled: !hasClip(), run: () => pasteFromMenu()},
          {label: "Duplicate", icon: "duplicate", shortcut: `${MOD} D`, run: () => multiDuplicate()},
          {sep: true}, {label: "Remove from the experiment", shortcut: "Delete", run: () => multiDelete()},
          {label: "Delete screens", icon: "trash", danger: true, run: () => deleteScreens(S.sel.items.map((x) => x.routine))}]);
        return;
      }
      if (!card && !e.target.closest(".frame-head, button, a")) {
        e.preventDefault();
        ui.menu(e, [{head: "Storyboard"}, {label: "Paste at the end", icon: "plus", shortcut: `${MOD} V`, disabled: !hasClip(), run: () => { S.sel = null; pasteFromMenu(); }}]);
      }
    }, true);
  }
  document.addEventListener("copy", (e) => { if (edEditableTarget(e) && S.sel) copySelection({viaEvent: e}); });
  document.addEventListener("cut", (e) => { if (edEditableTarget(e) && S.sel && !S.proposal) copySelection({cut: true, viaEvent: e}); });
  document.addEventListener("paste", (e) => {
    if (e.defaultPrevented || !edEditableTarget(e)) return;
    const p = parseClip(e.clipboardData?.getData("text/plain")) || null;
    if (!p) return;
    e.preventDefault();
    pastePayload(p);
  });
  // Ctrl/Cmd+A on the Screen view selects every item of the screen
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey || e.key.toLowerCase() !== "a" || !edEditableTarget(e) || S.view !== "screen" || !S.routine) return;
    if (!document.activeElement?.closest?.("#view-screen, #inspector") && document.activeElement !== document.body) return;
    e.preventDefault();
    setItemSelection(S.routine, comps(S.routine).map((c) => c.id));
  });
}
window.addEventListener("DOMContentLoaded", wireEditing);
