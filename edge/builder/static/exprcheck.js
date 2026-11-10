/* exprcheck.js: formulas checked while you type, with suggestions (builder editing, part 4). Owner: builder editing.
 * Every field that takes a $formula (an item's Formula fields, Only if / Starts when / Stops when, a screen's
 * "ends when", rules, workflow routes, a trial list's "Stop early when", if / otherwise, a measure's "Only when")
 * is an input or textarea with the class "expr". This file finds them by delegation (no change to the code that
 * draws them): while you type it asks the builder (POST /api/edit/check, debounced) whether the formula is valid
 * at that place of the experiment (syntax, unknown names with "did you mean", names that don't exist there, e.g. a
 * trial-list column on a screen outside that trial list) and shows the answer under the field, with a button that
 * applies the fix. It also offers the names available there (trial-list columns, variables, results such as
 * resp.rt, trial-list statistics, functions) in a suggestion list at the caret (Up/Down, Enter or Tab, Esc).
 * The place is worked out from the selection and the field (data-where on the input overrides it).
 */
"use strict";

const XC = {timer: null, seq: 0, cache: new Map(), last: new Map(), names: new Map(), pop: null, active: null};
const XC_KIND_WORDS = {column: "column", variable: "variable", participant: "participant", list: "trial list", workflow: "workflow",
  result: "result", time: "time", function: "function"};

function xcIsField(el) { return !!el && el.matches?.("input.expr, textarea.expr") && !el.disabled && !el.readOnly; }

/* Where the formula of this field is used: {routine} | {flow, field} | {flow, field: "route", state} | {field: "measure"}. */
function xcWhere(el) {
  if (el.dataset.where) { try { return JSON.parse(el.dataset.where); } catch { /* fall through */ } }
  if (el.closest("#ws-measures")) return {field: "measure"};
  const sel = S.sel || {};
  const prop = el.closest("[data-prop]")?.dataset.prop || "";
  if (el.closest("#list-editor")) { const p = typeof listPathNow === "function" ? listPathNow() : sel.path; return p ? {flow: p, field: "stop_if"} : {}; }
  if (sel.kind === "component" || sel.kind === "routine" || sel.kind === "components") return {routine: sel.routine || S.routine};
  if (sel.kind === "loop" && sel.path) return {flow: sel.path, field: ["repeats", "conditions"].includes(prop) ? prop : "stop_if"};
  if (sel.kind === "branch" && sel.path) return {flow: sel.path, field: "if"};
  if (sel.kind === "state" && sel.path && /^route:/.test(el.dataset.fkey || "")) return {flow: sel.path, field: "route", state: sel.name};
  if (S.view === "screen" && S.routine) return {routine: S.routine};
  return {};
}

const xcKey = (expr, where) => `${S.rev || 0}|${JSON.stringify(where)}|${expr}`;

/* The message box under a field (created next to the field, or at the end of its .expr-wrap). */
function xcBox(el, create = true) {
  const host = el.closest(".expr-wrap") || el.parentElement;
  let box = el._xcBox && el._xcBox.isConnected ? el._xcBox : null;
  if (!box && create) {
    box = h("div", {class: "xc-msg", role: "status", "aria-live": "polite", hidden: ""});
    if (host && host.classList.contains("expr-wrap")) host.append(box); else el.insertAdjacentElement("afterend", box);
    el._xcBox = box;
    const id = "xc-" + (++XC.seq);
    box.id = id;
    el.setAttribute("aria-describedby", [el.getAttribute("aria-describedby"), id].filter(Boolean).join(" "));
  }
  return box;
}

function xcShow(el, res) {
  const box = xcBox(el, !!(res && res.issues && res.issues.length));
  if (!box) return;
  const issues = (res && res.issues) || [];
  el.classList.toggle("xc-bad", issues.some((i) => i.level === "error"));
  el.classList.toggle("xc-warn", !issues.some((i) => i.level === "error") && issues.some((i) => i.level === "warning"));
  if (!issues.length) { box.hidden = true; box.replaceChildren(); el.removeAttribute("aria-invalid"); return; }
  if (issues.some((i) => i.level === "error")) el.setAttribute("aria-invalid", "true"); else el.removeAttribute("aria-invalid");
  box.hidden = false;
  box.replaceChildren(...issues.slice(0, 3).map((i) => {
    const tone = i.level === "error" ? "danger" : i.level === "warning" ? "warning" : "info";
    const fix = i.fix ? h("button", {type: "button", class: "btn sm xc-fix", "data-from": i.fix.from, "data-to": i.fix.to,
      onmousedown: (e) => e.preventDefault(),         // keep the focus (and the caret) in the field
      onclick: () => xcApplyFix(el, i.fix)}, `Use “${i.fix.to}”`) : null;
    return h("div", {class: "xc-line " + tone}, icon(tone === "danger" ? "error" : tone === "warning" ? "warning" : "info"),
      h("div", {class: "xc-txt"}, h("span", {}, i.message), i.hint ? h("span", {class: "xc-hint"}, i.hint.charAt(0).toUpperCase() + i.hint.slice(1) + ".") : null), fix);
  }));
}

function xcApplyFix(el, fix) {
  const esc = fix.from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(^|[^\\w.'"])${esc}(?![\\w])`, "g");
  const v = el.value.replace(re, (m, pre) => pre + fix.to);
  if (v === el.value) return;
  el.value = v;
  el.focus();
  el.dispatchEvent(new Event("input", {bubbles: true}));
  el.dispatchEvent(new Event("change", {bubbles: true}));
  ui.announce(`Changed to ${fix.to}`);
}

async function xcCheck(el, {quiet = false} = {}) {
  if (!S.exp || !el.isConnected) return;
  const expr = String(el.value || "").trim();
  if (!expr || expr === "$") { xcShow(el, null); return; }
  const where = xcWhere(el);
  const key = xcKey(expr, where);
  if (XC.cache.has(key)) { xcShow(el, XC.cache.get(key)); return; }
  // a field drawn again after a change shows its last answer until it is checked again (on focus or typing)
  if (quiet) { const last = XC.last.get(JSON.stringify(where) + "|" + expr); if (last) xcShow(el, last); return; }
  const mine = ++XC.seq;
  el._xcSeq = mine;
  let res;
  try {
    res = await api("/api/edit/check", {experiment: S.exp, path: S.noDoc ? null : S.path, expr, where: {...where, names: !XC.names.has(xcNamesKey(where))}});
  } catch { return; }            // the builder went away: say nothing rather than something wrong
  if (res.names) XC.names.set(xcNamesKey(where), res.names);
  if (XC.cache.size > 300) XC.cache.clear();
  XC.cache.set(key, res);
  if (XC.last.size > 300) XC.last.clear();
  XC.last.set(JSON.stringify(where) + "|" + expr, res);
  if (el._xcSeq !== mine || String(el.value || "").trim() !== expr) return;       // typed on meanwhile
  xcShow(el, res);
}
const xcNamesKey = (where) => `${S.rev || 0}|${JSON.stringify(where)}`;

async function xcLoadNames(el) {
  const where = xcWhere(el), k = xcNamesKey(where);
  if (XC.names.has(k)) return XC.names.get(k);
  try {
    const r = await api("/api/edit/names", {experiment: S.exp, path: S.noDoc ? null : S.path, where});
    if (XC.names.size > 50) XC.names.clear();
    XC.names.set(k, r.names || []);
    return r.names || [];
  } catch { return []; }
}

/* ---------------- suggestions at the caret */
function xcToken(el) {
  const pos = el.selectionStart ?? el.value.length;
  const before = el.value.slice(0, pos);
  if ((before.match(/'/g) || []).length % 2 || (before.match(/"/g) || []).length % 2) return null;     // inside quoted text
  const m = before.match(/([A-Za-z_][\w]*(?:\.[\w]*)?)$/);
  if (!m) return null;
  if (/\d/.test(before.charAt(before.length - m[1].length - 1) || "")) return null;
  return {text: m[1], start: pos - m[1].length, end: pos};
}

function xcClosePop() { if (XC.pop) { XC.pop.el.remove(); XC.pop = null; } }

async function xcSuggest(el) {
  const tok = xcToken(el);
  if (!tok || (tok.text.length < 1)) return xcClosePop();
  const names = await xcLoadNames(el);
  if (document.activeElement !== el) return;
  const t = tok.text.toLowerCase();
  const starts = names.filter((n) => n.name.toLowerCase().startsWith(t) && n.name !== tok.text);
  const inside = names.filter((n) => !n.name.toLowerCase().startsWith(t) && n.name.toLowerCase().includes(t) && t.length >= 2);
  const list = [...starts, ...inside].slice(0, 8);
  if (!list.length) return xcClosePop();
  xcClosePop();
  const pop = h("div", {class: "xc-pop menu", role: "listbox", "aria-label": "Names you can use here"});
  list.forEach((n, i) => pop.append(h("div", {class: "xc-opt" + (i === 0 ? " on" : ""), role: "option", id: `xc-opt-${i}`, "aria-selected": i === 0 ? "true" : "false",
    onmousedown: (e) => { e.preventDefault(); xcAccept(el, n.name); }},
  h("span", {class: "mono xc-name"}, n.name), h("span", {class: "xc-kind"}, n.detail || XC_KIND_WORDS[n.kind] || n.kind))));
  document.body.append(pop);
  const r = el.getBoundingClientRect();
  pop.style.left = Math.max(4, Math.min(innerWidth - 300, r.left)) + "px";
  const below = r.bottom + 4 + 260 < innerHeight;
  pop.style.top = (below ? r.bottom + 4 : Math.max(4, r.top - 4 - Math.min(260, list.length * 30 + 8))) + "px";
  pop.style.minWidth = Math.min(320, Math.max(200, r.width)) + "px";
  XC.pop = {el: pop, input: el, items: list, i: 0, tok};
  el.setAttribute("aria-activedescendant", "xc-opt-0");
}

function xcAccept(el, name) {
  const tok = xcToken(el); if (!tok) return xcClosePop();
  const v = el.value;
  const funcs = /^(abs|round|min|max|len|sum|int|float|str|mean|sorted|range|any|all|bool|list)$|^(math|random|statistics)\.\w+$/;
  const ins = name + (funcs.test(name) && !/^math\.(pi|e)$/.test(name) ? "(" : "");
  const pre = "";          // the fields add the leading $ themselves when they save
  el.value = v.slice(0, tok.start) + pre + ins + v.slice(tok.end);
  const caret = tok.start + pre.length + ins.length;
  el.setSelectionRange(caret, caret);
  xcClosePop();
  el.dispatchEvent(new Event("input", {bubbles: true}));
}

function xcPopKeys(e) {
  const p = XC.pop; if (!p || e.target !== p.input) return;
  const move = (d) => {
    const opts = [...p.el.querySelectorAll(".xc-opt")];
    p.i = (p.i + d + opts.length) % opts.length;
    opts.forEach((o, j) => { o.classList.toggle("on", j === p.i); o.setAttribute("aria-selected", j === p.i ? "true" : "false"); });
    p.input.setAttribute("aria-activedescendant", `xc-opt-${p.i}`);
    opts[p.i].scrollIntoView({block: "nearest"});
  };
  if (e.key === "ArrowDown") { e.preventDefault(); e.stopPropagation(); move(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); e.stopPropagation(); move(-1); }
  else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); e.stopPropagation(); xcAccept(p.input, p.items[p.i].name); }
  else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); xcClosePop(); }
}

/* ---------------- wiring (delegated: fields are redrawn often) */
function xcSchedule(el, ms = 280) {
  clearTimeout(XC.timer);
  XC.timer = setTimeout(() => xcCheck(el), ms);
}
function wireExprCheck() {
  document.addEventListener("focusin", (e) => {
    const el = e.target; if (!xcIsField(el)) return;
    if (el.getAttribute("list") === "expr-vars") { el.dataset.list = "expr-vars"; el.removeAttribute("list"); }    // our suggestions replace the datalist
    el.setAttribute("autocomplete", "off");
    el.setAttribute("aria-autocomplete", "list");
    XC.active = el;
    xcLoadNames(el);
    if (String(el.value || "").trim()) xcSchedule(el, 60);
  });
  document.addEventListener("focusout", (e) => { if (XC.pop && e.target === XC.pop.input) setTimeout(xcClosePop, 120); });
  document.addEventListener("input", (e) => {
    const el = e.target; if (!xcIsField(el)) return;
    xcSchedule(el);
    xcSuggest(el);
  });
  document.addEventListener("keydown", xcPopKeys, true);
  document.addEventListener("scroll", () => xcClosePop(), true);
  // fields drawn again after a change keep their message (from the cache: no new request)
  const mo = new MutationObserver((muts) => {
    for (const m of muts) for (const n of m.addedNodes) {
      if (!(n instanceof Element)) continue;
      const fields = n.matches?.("input.expr, textarea.expr") ? [n] : [...n.querySelectorAll?.("input.expr, textarea.expr") || []];
      for (const f of fields) if (String(f.value || "").trim()) xcCheck(f, {quiet: true});
    }
  });
  mo.observe(document.body, {childList: true, subtree: true});
  EDGE.on("doc:loaded", () => { XC.cache.clear(); XC.last.clear(); XC.names.clear(); });
}
window.addEventListener("DOMContentLoaded", wireExprCheck);
