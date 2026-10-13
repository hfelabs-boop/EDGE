/* measures.js: the Measures page and the session checks (SPEC W9, W11). Owner: P4b.
 * Owns the Measures workspace page (renderMeasuresPage; openMeasures goes there; drawMeasures is kept): what the
 * experiment measures (measure cards with a role, column, summary, trials, condition and expected range) and
 * everything that is recorded (columns with stars, save switches per item and device, timing details folded in
 * Simple). Also the pieces the Run and Test pages use: the live session monitor (monitorView), the recording summary
 * (recordingSummary), the computer check (computerCheckBox), the crash report (crashBox) and the go / no-go
 * preflight (preflightBox). Measures live in the experiment's `measures:` list; recording switches are each item's
 * `save` and each device's `record`; the plan (columns, streams, files) comes from /api/recording.
 */
"use strict";

const ROLE_HELP = {
  outcome: "The result you care about (dependent variable).",
  factor: "A condition you vary (independent variable): the other measures are summarised per level.",
  covariate: "Recorded to control for, e.g. age or a baseline score.",
  check: "A manipulation or attention check.",
  info: "Descriptive information about the participant.",
};
const ROLE_WORDS = {outcome: "Outcome", factor: "Condition", covariate: "Control", check: "Check", info: "Info"};
const KIND_BADGE = {rt: "time", accuracy: "correct?", response: "response", answer: "answer", score: "score", gaze: "gaze",
  timing: "timing", condition: "condition", design: "design", variable: "variable", info: "participant", other: ""};
const OUT_WORDS = {keys: "key pressed", rt: "response time", corr: "correct? 1/0", time: "time of the response", onset: "when it appeared",
  duration: "how long it was shown", rating: "rating", clicked: "what was clicked", x: "click position (x)", y: "click position (y)",
  entered: "looked at it? 1/0", dwell_time: "time spent looking", completed: "looked long enough? 1/0", first_entry: "first look",
  submitted: "form sent? 1/0", input: "input", released: "when the key was let go"};
const SUMMARY_WORDS = {mean: "Mean", median: "Median", sd: "Spread (SD) of", min: "Smallest", max: "Largest", sum: "Total", count: "Number of",
  proportion: "Proportion of", first: "First", last: "Last", none: ""};
const _autoIds = new WeakSet();   // measures whose id should follow their name
const MS = {R: null, key: "", loading: null, q: "", only: "all", open: new Set(["participant", "loops", "screens", "devices", "always"]), prev: null, back: null, err: null};

/* Kept name: open the Measures page. */
async function openMeasures() { EDGE.go("measures"); }
/* Kept name: (re)draw the Measures page. */
async function drawMeasures() { MS.key = ""; renderMeasuresPage($("#ws-measures")); }

const measureList = () => (Array.isArray(S.exp.measures) ? S.exp.measures : (S.exp.measures = []));
function measuresChanged(label = "Change the measures") {
  const ms = measureList();
  if (!ms.length) delete S.exp.measures;
  commit(label);
  if (!S.exp.measures) S.exp.measures = [];
}

/* The Measures page: idempotent; the recording plan is fetched once per version of the document. */
function renderMeasuresPage(el) {
  el = el || $("#ws-measures");
  if (!el || !S.exp || S.noDoc) return;
  const key = (S.path || "") + "|" + (S._snapshot || JSON.stringify(S.exp)).length + "|" + S.rev;
  if (MS.key !== key) {
    MS.key = key;
    const ask = MS.loading = api("/api/recording", {experiment: S.exp, path: S.path}).then((R) => {
      if (MS.loading !== ask) return;
      MS.R = R; MS.err = null; MS.loading = null;
      if (S.ws === "measures") drawMeasuresPage(el);
    }).catch((e) => { if (MS.loading !== ask) return; MS.loading = null; MS.err = e.message; if (S.ws === "measures") drawMeasuresPage(el); });
    if (!el.childElementCount) el.append(h("div", {class: "ms-page"}, msHead(), h("p", {class: "t-2"}, h("span", {class: "spin"}), " Working out what is recorded…")));
    return;
  }
  drawMeasuresPage(el);
}
function msHead() {
  const back = MS.back && ["run", "test"].includes(MS.back)
    ? h("button", {type: "button", class: "chip lg ms-back", onclick: () => EDGE.go(MS.back)}, icon("chev-left"), `Back to ${MS.back === "run" ? "Run" : "Test"}`) : null;
  return h("header", {class: "page-head ms-head"}, back, h("h1", {class: "t-title-l", id: "ms-title"}, "Measures"), h("span", {class: "grow"}),
    helpLink("EXPERIMENT_FORMAT", "measures"));
}
function drawMeasuresPage(el) {
  const a = document.activeElement;
  const keep = a && el.contains(a) ? a.dataset?.fkey : null;
  const typed = keep && "value" in a && a.value !== a.defaultValue ? {value: a.value, start: a.selectionStart, end: a.selectionEnd} : null;
  const scroll = el.scrollTop;
  const R = MS.R;
  if (!R) {
    el.replaceChildren(h("div", {class: "ms-page"}, msHead(), MS.err ? h("div", {class: "alert danger"}, icon("error"), h("div", {}, h("b", {}, "Couldn't work out what is recorded"), MS.err)) : h("p", {class: "t-2"}, h("span", {class: "spin"}), " Working out what is recorded…")));
    return;
  }
  el.replaceChildren(h("div", {class: "ms-page"}, msHead(),
    h("p", {class: "ms-lead t-2"}, "Say what this experiment measures. After every session EDGE summarises it per participant and condition, and checks it against what you expect."),
    h("div", {class: "ms-grid"}, msMeasuresCard(R), msRecordedCard(R))));
  el.scrollTop = scroll;
  if (keep) {
    const t = el.querySelector(`[data-fkey="${CSS.escape(keep)}"]`);
    if (t) { if (typed && "value" in t) { t.value = typed.value; try { t.setSelectionRange(typed.start, typed.end); } catch { /* not text */ } } t.focus({preventScroll: true}); }
  }
}

/* ---------------- what this experiment measures */
function msMeasuresCard(R) {
  const plan = R.plan, ms = measureList();
  const card = h("section", {class: "card ms-card-main", "aria-labelledby": "ms-what"}, h("div", {class: "card-head ms-cardhead"}, h("h2", {class: "t-title-s", id: "ms-what"}, "What this experiment measures")));
  const sugg = (R.suggestions || []).filter((sg) => !ms.some((m) => m && m.column === sg.column && (m.role || "outcome") === (sg.role || "outcome")));
  if (sugg.length) card.append(h("div", {class: "ms-suggest"}, h("span", {class: "ms-sugg-l"}, icon("star"), "Suggested:"),
    ...sugg.map((sg, i) => h("button", {type: "button", class: "chip lg accent", "data-fkey": "sugg:" + i, title: `${ROLE_WORDS[sg.role] || "Outcome"} from ${sg.column}` + (sg.trials ? `, only when ${inspInWords(sg.trials) || sg.trials}` : ""),
      onclick: () => { ms.push(sg); measuresChanged(`Add the measure “${sg.label}”`); }}, icon("plus"), sg.label)),
    sugg.length > 1 ? h("button", {type: "button", class: "btn sm", onclick: () => { ms.push(...sugg); measuresChanged("Add the suggested measures"); }}, "Add all") : null));
  const list = h("div", {class: "ms-list"});
  if (!ms.length) list.append(h("div", {class: "empty dropzone ms-empty"}, h("span", {class: "ic-wrap"}, icon("measures")),
    h("p", {}, "Say what this experiment measures to see it summarised after every session."),
    h("p", {class: "t-small"}, sugg.length ? "Start from the suggestions above, or click the star next to anything that is recorded." : "Click the star next to anything that is recorded, or add a measure.")));
  const loops = plan.loops.map((l) => l.loop);
  let lineIdx = 0;
  ms.forEach((m, i) => {
    if (!m || typeof m !== "object") return;
    const line = m.column ? R.lines[lineIdx++] : null;
    list.append(measureCard(m, i, plan, loops, line, R));
  });
  for (const x of R.issues.filter((x) => x.where === "measures")) list.append(h("div", {class: "alert " + (x.level === "error" ? "danger" : "warning")}, icon(x.level === "error" ? "error" : "warning"), h("div", {}, x.message)));
  card.append(list);
  const A = typeof inspAssistant === "function" ? inspAssistant() : window.Assistant;
  card.append(h("div", {class: "ms-actions"},
    h("button", {type: "button", class: "btn", "data-fkey": "ms:add", onclick: () => addBlankMeasure(plan)}, icon("plus"), "Add a measure"),
    A?.open && !EDGE.prefs.get("assistant.hidden", false) ? h("button", {type: "button", class: "btn assistant-outline", onclick: () => A.open({text: "Suggest measures for this experiment: "})}, icon("assistant"), "Suggest measures for my question") : null));
  return card;
}
function addBlankMeasure(plan) {
  const ms = measureList();
  const cand = Object.entries(plan.columns).filter(([col, c]) => c.saved && !ms.some((x) => x.column === col));
  const first = ["rt", "accuracy", "score", "response"].map((k) => cand.find(([, c]) => c.kind === k)).find(Boolean);
  const m = {id: uniqueId("measure", new Set(ms.map((x) => x.id))), label: "", role: "outcome", column: first ? first[0] : ""};
  _autoIds.add(m); ms.push(m);
  MS.focusNew = ms.length - 1;
  measuresChanged("Add a measure");
}
function measureCard(m, i, plan, loops, line, R) {
  const ms = measureList();
  const set = (k, v, label) => { if (v === "" || v === null || v === undefined) delete m[k]; else m[k] = v; measuresChanged(label || `Change the measure “${m.label || m.id}”`); };
  const role = m.role || "outcome";
  const card = h("article", {class: "ms-card role-" + role, "aria-label": `Measure ${m.label || m.id}`});
  const lid = `ms-${i}-label`;
  const label = h("input", {class: "input ms-label", id: lid, value: m.label || m.id || "", placeholder: "Name, e.g. Reaction time", "aria-label": "Name of the measure", "data-fkey": `ms:${i}:label`,
    onchange: (e) => setTimeout(() => {
      const v = e.target.value.trim(); m.label = v;
      if (!m.id || _autoIds.has(m)) m.id = uniqueId(v.toLowerCase().replace(/\s+/g, "_") || "measure", new Set(ms.filter((x) => x !== m).map((x) => x.id)));
      measuresChanged("Rename a measure");
    }, 0)});
  const roleSeg = ui.seg(Object.keys(ROLE_WORDS).filter((r) => !R.roles || r in R.roles).map((r) => ({value: r, label: ROLE_WORDS[r], title: ROLE_HELP[r]})), role,
    (v) => setTimeout(() => set("role", v, `Change the role of “${m.label || m.id}”`), 0), {ariaLabel: "Role", size: "sm"});
  roleSeg.classList.add("ms-role");
  card.append(h("div", {class: "ms-top"}, label, roleSeg,
    h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Remove the measure ${m.label || m.id}`, title: "Remove",
      onclick: () => { ms.splice(i, 1); measuresChanged(`Remove the measure “${m.label || m.id}”`); ui.toast(`Removed the measure “${m.label || m.id}”.`, {action: {label: "Undo", run: () => undo()}}); }}, icon("trash"))));
  const isFactor = role === "factor" || role === "info";
  const row = (...kids) => h("div", {class: "ms-row"}, ...kids);
  const fld = (labelText, id, ctl, cls = "") => h("div", {class: "ms-f " + cls}, h("label", {for: id}, labelText), ctl);
  const colId = `ms-${i}-col`;
  const col = msColumnSelect(m.column, plan, colId, i);
  col.onchange = (e) => setTimeout(() => set("column", e.target.value), 0);
  if (isFactor) card.append(row(fld("From", colId, col, "wide")));
  else {
    const sid = `ms-${i}-sum`;
    const sum = h("select", {class: "input", id: sid, "data-fkey": `ms:${i}:sum`, title: "How it is summarised per participant and condition", onchange: (e) => setTimeout(() => set("summary", e.target.value), 0)},
      R.summaries.map((s) => { const o = h("option", {value: s}, s === "none" ? "No summary" : (SUMMARY_WORDS[s] || s).replace(/ of$/, "")); if ((m.summary || "mean") === s) o.selected = true; return o; }));
    card.append(row(fld("From", colId, col, "wide"), fld("Summary", sid, sum)));
    const uid = `ms-${i}-loop`, oid = `ms-${i}-only`;
    const loopSel = h("select", {class: "input", id: uid, "data-fkey": `ms:${i}:loop`, onchange: (e) => setTimeout(() => set("loop", e.target.value), 0)}, h("option", {value: ""}, "All trials"),
      loops.map((l) => { const o = h("option", {value: l}, `Trials of “${l}”`); if (m.loop === l) o.selected = true; return o; }));
    const only = h("input", {class: "input expr", id: oid, list: "expr-vars", value: m.trials || "", placeholder: "always, or e.g. $resp.corr == 1", spellcheck: "false", "data-fkey": `ms:${i}:only`,
      onchange: (e) => setTimeout(() => { let v = e.target.value.trim(); if (v && !v.startsWith("$")) v = "$" + v; set("trials", v); }, 0)});
    const say = m.trials ? inspInWords(m.trials) : "";
    card.append(row(fld("Use", uid, loopSel), h("div", {class: "ms-f wide"}, h("label", {for: oid}, "Only when"), only, say && say !== m.trials ? h("span", {class: "say"}, `In words: ${say}.`) : null)));
    const ex = m.expect || [];
    const lo = h("input", {class: "input num", id: `ms-${i}-lo`, inputmode: "decimal", value: ex[0] ?? "", placeholder: "min", "aria-label": "Expected at least", "data-fkey": `ms:${i}:lo`});
    const hi = h("input", {class: "input num", inputmode: "decimal", value: ex[1] ?? "", placeholder: "max", "aria-label": "Expected at most", "data-fkey": `ms:${i}:hi`});
    const setEx = () => setTimeout(() => set("expect", lo.value.trim() !== "" && hi.value.trim() !== "" ? [+lo.value.replace(",", "."), +hi.value.replace(",", ".")] : null), 0);
    lo.onchange = setEx; hi.onchange = setEx;
    const units = h("input", {class: "input ms-units", value: m.units || "", placeholder: "units", "aria-label": "Units", "data-fkey": `ms:${i}:units`, onchange: (e) => setTimeout(() => set("units", e.target.value.trim()), 0)});
    card.append(row(h("div", {class: "ms-f"}, h("label", {for: `ms-${i}-lo`}, "Expected between"), h("div", {class: "ms-range"}, lo, h("span", {class: "t-2"}, "and"), hi, units))));
  }
  const sentence = measureSentence(m, plan);
  if (sentence && m.column) card.append(h("p", {class: "ms-say"}, icon("chev-right"), sentence));
  if (line && !isSimple()) card.append(h("p", {class: "t-caption mono ms-line"}, line));
  const issues = R.issues.filter((x) => x.where === `measures.${m.id}` || String(x.where).startsWith(`measures.${m.id}.`) || x.where === `measures[${i}]`);
  for (const x of issues) card.append(h("div", {class: "alert " + (x.level === "error" ? "danger" : "warning")}, icon(x.level === "error" ? "error" : "warning"), h("div", {}, x.message, x.hint ? h("div", {class: "t-caption"}, x.hint) : null)));
  if (MS.focusNew === i) { MS.focusNew = null; setTimeout(() => $("#" + lid)?.focus(), 0); }
  return card;
}
function msColumnSelect(cur, plan, id, i) {
  const sel = h("select", {class: "input ms-col", id, "data-fkey": `ms:${i}:col`});
  const groups = {};
  for (const [col, c] of Object.entries(plan.columns)) {
    if (!c.saved) continue;
    const g = c.source.startsWith("component:") ? `Screen “${c.source.slice(10).split(".")[0]}”` :
      c.source.startsWith("loop:") ? `Trial list “${c.source.slice(5)}”` : c.source === "participant" ? "Participant" :
      c.source === "variable" ? "Variables" : "Other";
    (groups[g] ||= []).push(col);
  }
  if (!cur) sel.append(h("option", {value: "", selected: ""}, "Choose a column…"));
  if (cur && !plan.columns[cur]) sel.append(h("option", {value: cur, selected: ""}, `${cur} (not recorded)`));
  for (const [g, cols] of Object.entries(groups)) sel.append(h("optgroup", {label: g},
    cols.map((col) => { const w = OUT_WORDS[col.split(".").pop()]; const o = h("option", {value: col, title: plan.columns[col].desc}, col.includes(".") && w ? `${col} · ${w}` : col); if (col === cur) o.selected = true; return o; })));
  return sel;
}
/* "Median response time on trials where the response was correct, in “trials”; expected 0.15–2.5 s." */
function measureSentence(m, plan) {
  const role = m.role || "outcome";
  const c = plan.columns[m.column] || {};
  const what = c.kind === "rt" ? "response time" : c.kind === "accuracy" ? "correct answers" : OUT_WORDS[String(m.column).split(".").pop()] || `“${m.column}”`;
  if (role === "factor") return `The other measures are summarised for each value of “${m.column}”.`;
  if (role === "info") return `“${m.column}” is kept as information about the participant.`;
  const sum = m.summary || "mean";
  let s = sum === "none" ? `Every value of ${what}` : sum === "proportion" && c.kind === "accuracy" ? "Proportion of correct answers" : `${SUMMARY_WORDS[sum] || sum} ${what}`;
  if (m.trials) s += ` on trials where ${inspInWords(m.trials) || "its condition holds"}`;
  if (m.loop) s += ` in “${m.loop}”`;
  if (Array.isArray(m.expect) && m.expect.length === 2) s += `; expected ${m.expect[0]}–${m.expect[1]}${m.units ? " " + m.units : ""}`;
  return s + ".";
}
function newMeasureFor(col, kind, plan) {
  const ms = S.exp.measures || [];
  const taken = new Set(ms.map((m) => m.id));
  const base = col.replace(/\./g, "_");
  const m = {id: uniqueId(kind === "rt" ? "rt" : kind === "accuracy" ? "accuracy" : base, taken), column: col};
  if (kind === "condition") { m.role = "factor"; m.label = col; }
  else if (kind === "info") { m.role = "info"; m.label = col; }
  else {
    m.role = "outcome";
    const comp = col.split(".")[0];
    m.label = kind === "rt" ? "Reaction time" : kind === "accuracy" ? "Accuracy" : col;
    m.summary = kind === "accuracy" ? "proportion" : kind === "rt" ? "median" : ["answer", "score"].includes(kind) ? "first" : "mean";
    if (kind === "rt" && plan.columns[`${comp}.corr`]) m.trials = `$${comp}.corr == 1`;
    if (plan.columns[col]?.units) m.units = plan.columns[col].units;
    const src = plan.columns[col]?.source || "";
    const rid = src.startsWith("component:") ? src.slice(10).split(".")[0] : null;
    const lp = rid && typeof enclosing === "function" ? enclosing(rid).loops.map((l) => l.loop).filter((l) => !/practi/i.test(l)).pop() : null;
    if (lp) m.loop = lp;
  }
  return m;
}

/* ---------------- everything that is recorded */
function msRecordedCard(R) {
  const plan = R.plan, ms = measureList();
  const measuredBy = (col) => ms.find((m) => m && m.column === col);
  const q = MS.q.trim().toLowerCase();
  const match = (...t) => !q || t.some((x) => String(x || "").toLowerCase().includes(q));
  const card = h("section", {class: "card ms-card-rec", "aria-labelledby": "ms-rec"}, h("div", {class: "card-head ms-cardhead"}, h("h2", {class: "t-title-s", id: "ms-rec"}, "Everything that is recorded")),
    h("p", {class: "t-small t-2 ms-reclead"}, "Worked out before anything runs. Switch off what you don't need; the star makes a column a measure."));
  const search = h("input", {class: "input", type: "search", value: MS.q, placeholder: "Search columns…", "aria-label": "Search columns", "data-fkey": "ms:search",
    oninput: (e) => { MS.q = e.target.value; clearTimeout(MS._qt); MS._qt = setTimeout(() => drawMeasuresPage($("#ws-measures")), 150); }});
  const only = ui.seg([{value: "all", label: "All"}, {value: "saved", label: "Saved"}], MS.only, (v) => { MS.only = v; drawMeasuresPage($("#ws-measures")); }, {ariaLabel: "Which columns", size: "sm"});
  card.append(h("div", {class: "ms-tools"}, h("div", {class: "input-wrap ms-search"}, icon("search", "lead"), search), only));
  const star = (col, kind) => {
    const m = measuredBy(col);
    return h("button", {type: "button", class: "btn ghost icon sm ms-star" + (m ? " on" : ""), "aria-pressed": m ? "true" : "false",
      "aria-label": m ? `It's a measure: “${m.label || m.id}”. Show it` : `Make ${col} a measure`, title: m ? `It's a measure: show it` : "Make this a measure",
      onclick: () => {
        if (m) { const i = ms.indexOf(m); const t = document.querySelector(`[data-fkey="ms:${i}:label"]`); t?.scrollIntoView({behavior: "smooth", block: "center"}); t?.focus({preventScroll: true}); return; }
        ms.push(newMeasureFor(col, kind, plan)); measuresChanged(`Make ${col} a measure`);
      }}, icon("star"));
  };
  const colRow = (col, desc, units, kind, saved = true, out = null) => {
    const short = out ? OUT_WORDS[out.key] || desc : desc;
    return h("li", {class: "rec-col" + (saved ? "" : " off")}, star(col, kind), h("code", {class: "mono rec-name", title: col}, col),
      h("span", {class: "rec-desc", title: desc}, isSimple() ? short : desc), units ? h("span", {class: "rec-units mono"}, units) : null,
      KIND_BADGE[kind] && !isSimple() ? h("span", {class: "chip rec-kind k-" + kind}, KIND_BADGE[kind]) : null);
  };
  const sec = (id, title, count, kids, {open} = {}) => {
    const d = h("details", {class: "rec-sec", open: (open ?? MS.open.has(id)) || q ? "" : null}, h("summary", {}, icon("chev-right", "chev"), h("span", {class: "rec-t"}, title), h("span", {class: "rec-n t-caption"}, String(count))), ...kids);
    d.addEventListener("toggle", () => { if (d.open) MS.open.add(id); else MS.open.delete(id); });
    return d;
  };
  const savedOnly = MS.only === "saved";
  const body = h("div", {class: "rec-body"});
  // participant
  const pcols = plan.participant.filter((f) => match(f));
  if (pcols.length) body.append(sec("participant", "Participant", pcols.length,
    [h("ul", {class: "rec-cols"}, pcols.map((f) => colRow(f, "Asked when the session starts", "", "info"))),
      h("p", {class: "t-caption rec-hint"}, "Change the fields in ", h("button", {type: "button", class: "linkbtn", onclick: () => openSettings?.("participant")}, "Experiment settings"), ".")]));
  // trial lists
  for (const l of plan.loops) {
    const cols = (l.columns || []).filter((c) => match(c, l.loop));
    if (l.columns && !cols.length && q) continue;
    body.append(sec("loop:" + l.loop, `Trial list “${l.loop}”`, l.columns ? l.columns.length : "…",
      [h("p", {class: "t-caption rec-hint"}, `From ${l.source}.`), l.columns ? h("ul", {class: "rec-cols"}, cols.map((c) => colRow(c, "The condition of each trial", "", "condition")))
        : h("p", {class: "t-caption"}, "Its columns are known when the experiment runs.")]));
  }
  // screens
  const byRoutine = {};
  for (const c of plan.components) (byRoutine[c.routine] ||= []).push(c);
  for (const [rid, cs] of Object.entries(byRoutine)) {
    const kids = [];
    let n = 0;
    for (const c of cs.filter((c) => c.outputs.length)) {
      if (savedOnly && !c.save) continue;
      const outs = c.outputs.filter((o) => match(o.column, o.desc, c.id, rid));
      if (!outs.length) continue;
      const comp = findComp(rid, c.id);
      const timing = outs.filter((o) => o.kind === "timing" || /\.(onset|duration|time)$/.test(o.column));
      const main = outs.filter((o) => !timing.includes(o));
      n += outs.length;
      const sw = ui.switch(c.save, (v) => { if (!comp) return; if (v) delete comp.save; else comp.save = false; measuresChanged(`${v ? "Save" : "Don't save"} what “${c.id}” records`); },
        {label: `${c.id}`, caption: friendlyName(c.type) + (c.save ? "" : " · not saved")});
      sw.classList.add("rec-switch");
      sw.switchButton.setAttribute("aria-label", `Save what ${c.id} records`);
      const comp1 = h("div", {class: "rec-comp" + (c.save ? "" : " off")}, sw);
      if (main.length) comp1.append(h("ul", {class: "rec-cols"}, main.map((o) => colRow(o.column, o.desc, o.units, o.kind, c.save, o))));
      if (timing.length) {
        const tid = `timing:${rid}.${c.id}`;
        const open = !isSimple() || MS.open.has(tid) || !!q;
        const d = h("details", {class: "rec-timing", open: open ? "" : null}, h("summary", {}, icon("chev-right", "chev"), `Timing details (${timing.length})`),
          h("ul", {class: "rec-cols"}, timing.map((o) => colRow(o.column, o.desc, o.units, o.kind, c.save, o))));
        d.addEventListener("toggle", () => { if (d.open) MS.open.add(tid); else MS.open.delete(tid); });
        comp1.append(d);
      }
      kids.push(comp1);
    }
    if (kids.length) body.append(sec("screen:" + rid, `Screen “${rid}”`, n, kids, {open: MS.open.has("screen:" + rid) || MS.open.has("screens")}));
  }
  // variables
  const vars = plan.variables.filter((v) => match(v));
  if (vars.length) body.append(sec("variables", "Variables", vars.length, [h("ul", {class: "rec-cols"}, vars.map((v) => colRow(v, "Its value at the end of each trial", "", "variable")))]));
  // devices
  const devs = plan.devices.filter((d) => (!savedOnly || d.record) && match(d.id, d.type, ...d.streams.map((s) => s.name)));
  const devKids = devs.map((d) => {
    const spec = S.exp.devices.find((x) => x.id === d.id);
    const sw = ui.switch(d.record, (v) => { if (!spec) return; if (v) delete spec.record; else spec.record = false; measuresChanged(`${v ? "Record" : "Don't record"} “${d.id}”`); },
      {label: d.id, caption: (typeof deviceLabel === "function" && spec ? deviceLabel(spec) : d.type) + (d.record || !d.streams.length ? "" : " · not recorded")});
    if (!d.streams.length) sw.switchButton.disabled = true;
    sw.classList.add("rec-switch");
    return h("div", {class: "rec-comp" + (d.record ? "" : " off")}, sw,
      d.streams.length ? h("ul", {class: "rec-cols"}, d.streams.map((s) => h("li", {class: "rec-col"}, h("span", {class: "chip rec-kind k-gaze"}, s.kind || "stream"),
        h("code", {class: "mono rec-name"}, `${d.id}.${s.name}`),
        h("span", {class: "rec-desc"}, `${s.what}: ${s.channels ? `${s.channels.length} channels` : "channels as the device reports them"}, ` +
          (s.srate ? `${s.srate} samples/s` : s.kind === "Events" ? "one row whenever an input changes" : "at the device's own rate"))))) : null,
      d.note ? h("p", {class: "t-caption rec-hint"}, cap(d.note) + ".") : null,
      d.markers ? h("p", {class: "t-caption rec-hint"}, "It receives the event markers.") : null);
  });
  body.append(sec("devices", "Devices and streams", plan.devices.length, devKids.length ? devKids : [h("p", {class: "t-caption rec-hint"}, "No devices: only behaviour is recorded.")]));
  const always = plan.always.filter((f) => match(f.file, f.what));
  if (always.length) body.append(sec("always", "Always saved", always.length, [h("ul", {class: "rec-cols"}, always.map((f) => h("li", {class: "rec-col"}, icon("file"), h("code", {class: "mono rec-name"}, f.file), h("span", {class: "rec-desc"}, cap(f.what)))))]));
  if (!body.childElementCount) body.append(h("p", {class: "t-2"}, `Nothing called “${MS.q}”.`));
  card.append(body);
  return card;
}
EDGE.on("workspace", ({ws}) => {
  if (ws === "measures") { MS.back = MS.prev; MS.key = ""; }
  MS.prev = ws;
});
EDGE.on("doc:loaded", () => { MS.key = ""; MS.R = null; MS.q = ""; });

/* ================================================================== live session monitor (Run page) */
function fmtMeasure(m, v) {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v !== "number") return String(v);
  if (m && m.summary === "proportion") return Math.round(v * 100) + " %";
  if (m && m.units === "s" && Math.abs(v) < 20) return Math.round(v * 1000) + " ms";
  return (Math.abs(v) >= 100 ? v.toFixed(0) : +v.toPrecision(3)) + (m && m.units && m.units !== "s" ? " " + m.units : "");
}

function sparkline(vals, expect) {
  const nums = vals.map((v) => (typeof v === "number" ? v : typeof v === "boolean" ? +v : null));
  const ok = nums.filter((v) => v !== null);
  const W = 220, H = 36;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "mon-spark"); svg.setAttribute("preserveAspectRatio", "none"); svg.setAttribute("aria-hidden", "true");
  if (ok.length < 2) return svg;
  const lo = Math.min(...ok, ...(expect ? [expect[0]] : [])), hi = Math.max(...ok, ...(expect ? [expect[1]] : []));
  const x = (i) => (i / Math.max(1, nums.length - 1)) * (W - 4) + 2, y = (v) => H - 3 - ((v - lo) / ((hi - lo) || 1)) * (H - 6);
  if (expect) { const band = document.createElementNS(ns, "rect"); band.setAttribute("x", 0); band.setAttribute("width", W);
    band.setAttribute("y", y(expect[1])); band.setAttribute("height", Math.max(1, y(expect[0]) - y(expect[1]))); band.setAttribute("class", "mon-band"); svg.append(band); }
  const path = document.createElementNS(ns, "polyline");
  path.setAttribute("points", nums.map((v, i) => (v === null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean).join(" "));
  path.setAttribute("class", "mon-line"); svg.append(path);
  nums.forEach((v, i) => { if (v === null || (expect && (v < expect[0] || v > expect[1]))) {
    const c = document.createElementNS(ns, "circle"); c.setAttribute("cx", x(i)); c.setAttribute("cy", v === null ? H - 2 : y(v)); c.setAttribute("r", 2.2);
    c.setAttribute("class", v === null ? "mon-miss" : "mon-out"); svg.append(c); } });
  return svg;
}

/* What the Run page shows while a participant is running. update(status) redraws it (no transitions while recording). */
function monitorView() {
  const el = h("div", {class: "mon"});
  const update = (st) => {
    const M = st.monitor || {}, start = M.start, last = M.last, end = M.end;
    if (!start) { el.replaceChildren(h("p", {class: "mon-wait t-2"}, st.running ? "Starting: opening the window and connecting devices…" : "")); return; }
    const ms = start.measures || [], mById = Object.fromEntries(ms.map((m) => [m.id, m]));
    const n = (end || last || {}).trials ?? (last ? last.n : 0) ?? 0;
    const exp = start.expected_trials;
    const pct = exp ? Math.min(100, Math.round(100 * n / exp)) : null;
    const out = [];
    out.push(h("div", {class: "mon-prog"},
      h("div", {class: "mon-progtxt"}, h("b", {}, `Trial ${n}${exp ? ` of about ${exp}` : ""}`), last?.routine ? h("span", {class: "t-caption"}, `screen “${last.routine}”`) : null),
      h("div", {class: "mon-bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(exp || 0), "aria-valuenow": String(n), "aria-label": "Trials done"}, h("div", {style: `width:${pct ?? 0}%`}))));
    const warns = [];
    const hist = M.history || [];
    const run = (end || last || {}).running || {};
    const kpis = h("div", {class: "mon-kpis"});
    for (const m of ms.filter((m) => m.role !== "factor")) {
      const r = run[m.id] || {};
      const series = hist.map((t) => (t.values || {})[m.id]).filter((v, i) => Object.prototype.hasOwnProperty.call(hist[i].values || {}, m.id));
      const outN = m.expect ? series.filter((v) => typeof v === "number" && (v < m.expect[0] || v > m.expect[1])).length : 0;
      const missRate = r.n + r.missing ? r.missing / (r.n + r.missing) : 0;
      if (missRate > 0.2 && r.n + r.missing >= 5) warns.push(`${m.label || m.id}: missing on ${Math.round(missRate * 100)} % of the trials so far.`);
      const tail = series.slice(-5);
      if (tail.length === 5 && tail.every((v) => v === null || v === "")) warns.push(`${m.label || m.id}: no value on the last 5 trials. Is the participant still responding?`);
      if (outN) warns.push(`${m.label || m.id}: ${countWord(outN, "value")} outside ${m.expect[0]}–${m.expect[1]}.`);
      kpis.append(h("div", {class: "kpi mon-kpi" + (missRate > 0.2 || outN ? " warn" : "")},
        h("span", {class: "mon-kl"}, m.label || m.id), h("b", {}, fmtMeasure(m, r.value)),
        h("span", {class: "t-caption"}, `${m.summary || "value"} of ${r.n || 0}` + (r.missing ? ` · ${r.missing} missing` : "") + (m.expect ? ` · expected ${m.expect[0]}–${m.expect[1]}` : "")),
        sparkline(series.slice(-120), m.expect)));
    }
    const left = h("section", {class: "mon-sec", "aria-label": "Measures so far"}, h("h3", {class: "t-small mon-h"}, "Measures so far"));
    if (!ms.filter((m) => m.role !== "factor").length) left.append(h("p", {class: "t-small t-2"}, "No measures declared, so there is nothing to follow here. Say what you measure on the ",
      h("button", {type: "button", class: "linkbtn", onclick: () => EDGE.go("measures")}, "Measures"), " page to watch reaction times, accuracy or scores live."));
    else left.append(kpis);
    // nobody responding?
    const asked = hist.filter((t) => Object.keys(t.responses || {}).some((k) => /\.(keys|input|rt|rating|clicked)$/.test(k)));
    let silent = 0;
    for (let i = asked.length - 1; i >= 0; i--) {
      if (Object.entries(asked[i].responses).some(([k, v]) => /\.(keys|input|rt|rating|clicked)$/.test(k) && v !== null && v !== "")) break;
      silent++;
    }
    if (!end && silent >= 3) warns.unshift(`No response on the last ${silent} trials. Is the participant still responding, and is the keyboard or response box connected?`);
    // the last response
    const shown = M.last_response || last;
    if (shown) {
      const resp = Object.entries(shown.responses || {}).filter(([, v]) => v !== null && v !== "");
      const bits = resp.map(([k, v]) => k.endsWith(".rt") && typeof v === "number" ? `${Math.round(v * 1000)} ms` : k.endsWith(".corr") ? (v ? "correct" : "wrong") : String(v));
      const factors = Object.entries(shown.factors || {}).map(([k, v]) => `${(mById[k] || {}).label || k} ${v}`);
      left.append(h("p", {class: "t-small mon-last"}, h("span", {class: "t-2"}, "Last response: "), [...bits, ...factors].join(" · ") || "none", h("span", {class: "t-caption"}, ` (screen “${shown.routine}”)`)));
    }
    // devices
    const devs = M.devices?.devices || {};
    const right = h("section", {class: "mon-sec", "aria-label": "Devices"}, h("h3", {class: "t-small mon-h"}, "Devices"));
    if (Object.keys(start.devices || {}).length) {
      const tbl = h("ul", {class: "mon-devs"});
      for (const [did, d] of Object.entries(start.devices)) {
        const live = devs[did]?.streams || {};
        const names = Object.keys(d.streams || {});
        if (!names.length) tbl.append(h("li", {class: "mon-dev"}, h("span", {class: "dot ok"}), h("b", {}, did), h("span", {class: "t-caption"}, `${d.type} · sends markers`)));
        for (const s of names) {
          const L = live[s] || {}, status = end ? "done" : L.status || "wait";
          if (!end && status === "silent") warns.push(`${did}.${s}: no data for more than a second. Check the device and its cable.`);
          if (!end && status === "low") warns.push(`${did}.${s}: ${L.rate} samples/s, expected ${L.nominal}.`);
          tbl.append(h("li", {class: "mon-dev"}, h("span", {class: "dot " + status, title: status}), h("b", {}, `${did}.${s}`),
            h("span", {}, L.rate != null ? `${L.rate}${L.nominal ? ` / ${L.nominal}` : ""} Hz` : "…", status === "low" ? " (too slow)" : status === "silent" ? " (no data)" : ""),
            h("span", {class: "t-caption"}, `${L.samples ?? 0} samples · ${d.streams[s].channels} ch`)));
        }
      }
      right.append(tbl);
    } else right.append(h("p", {class: "t-small t-2"}, "No devices: keyboard and mouse only."));
    out.push(h("div", {class: "mon-grid"}, left, right));
    if (warns.length) out.unshift(h("div", {class: "mon-warns", role: "alert"}, ...warns.map((w) => h("div", {class: "alert warning"}, icon("warning"), h("div", {}, w)))));
    if (end && end.errors?.length) out.push(h("div", {class: "alert danger"}, icon("error"), h("div", {}, end.errors.slice(0, 3).join("; "))));
    el.replaceChildren(...out);
  };
  return {el, update};
}

/* A short "this session will record …" summary for the Run page. */
async function recordingSummary() {
  let R; try { R = await api("/api/recording", {experiment: S.exp, path: S.path}); } catch { return null; }
  const p = R.plan;
  const cols = p.components.reduce((n, c) => n + (c.save ? c.outputs.length : 0), 0);
  const streams = p.devices.flatMap((d) => (d.record ? d.streams.map((s) => `${d.id}.${s.name}`) : []));
  const ms = S.exp.measures || [];
  const box = h("div", {class: "rec-summary"});
  box.append(h("p", {}, h("b", {}, "Measures: "), ms.length ? ms.map((m) => m.label || m.id).join(" · ")
    : h("span", {class: "warn-txt"}, "none declared. You can still run, but say what you measure to get live values, measures.csv and checks.")));
  box.append(h("p", {}, h("b", {}, "Recorded: "), `${cols} response and timing columns`, p.loops.length ? `, the trial lists ${p.loops.map((l) => `“${l.loop}”`).join(", ")}` : "",
    streams.length ? `, the streams ${streams.join(", ")}` : "", ", event markers and screen timing."));
  box.append(h("button", {type: "button", class: "btn sm ghost rec-review", onclick: () => EDGE.go("measures")}, "Review measures", icon("chev-right")));
  return box;
}

/* ================================================================== computer check (before a session) */
async function computerCheckBox() {
  const box = h("div", {class: "pc-check"}, h("p", {class: "t-small t-2"}, h("span", {class: "spin"}), " Checking this computer…"));
  const draw = async () => {
    let r;
    try { r = await api("/api/system_check" + (S.path ? `?path=${encodeURIComponent(S.path)}` : "")); }
    catch (e) { box.replaceChildren(h("div", {class: "alert warning"}, icon("warning"), h("div", {}, "The check couldn't run: " + e.message))); return; }
    const bad = r.checks.filter((c) => c.level === "warning" || c.level === "error");
    const info = r.checks.filter((c) => c.level === "info");
    const out = [];
    if (!bad.length) out.push(h("div", {class: "alert success"}, icon("success"), h("div", {}, h("b", {}, "Nothing on this computer that would affect timing"), info.length ? `${countWord(info.length, "note")} below.` : "")));
    else out.push(h("div", {class: "alert warning"}, icon("warning"), h("div", {}, h("b", {}, `${countWord(bad.length, "thing")} to look at`), "They can affect the timing of your experiment.")));
    const ul = h("ul", {class: "pc-list"});
    for (const c of [...bad, ...info]) {
      const li = h("li", {class: "pc-item l-" + c.level}, icon(c.level === "info" ? "info" : c.level === "error" ? "error" : "warning"),
        h("div", {}, h("b", {}, c.title), h("div", {class: "t-small t-2"}, c.detail), c.fix ? h("div", {class: "t-small pc-fix"}, c.fix) : null));
      if (c.fixable) li.append(h("button", {type: "button", class: "btn sm", onclick: async (e) => {
        e.currentTarget.disabled = true; e.currentTarget.textContent = "Fixing…";
        const res = await api("/api/system_fix", {id: c.id}).catch((err) => ({ok: false, error: err.message}));
        toast(res.ok ? `Done: ${res.done}` : `Couldn't fix it: ${res.error}`, {tone: res.ok ? "success" : "danger", ms: 6000});
        draw();
      }}, "Fix"));
      ul.append(li);
    }
    if (ul.childElementCount) out.push(ul);
    box.replaceChildren(...out);
  };
  draw();
  return box;
}

/* ================================================================== crash report (what / where / when / state) */
function crashBox(rep) {
  if (!rep) return null;
  const row = (k, v) => (v ? h("div", {class: "crash-row"}, h("span", {}, k), h("div", {}, v)) : null);
  const trial = Object.entries(rep.trial || {}).map(([k, v]) => `${k} #${typeof v === "number" ? v + 1 : v}`).join(", ");
  const vars = Object.entries(rep.variables || {}).slice(0, 14).map(([k, v]) => `${k} = ${JSON.stringify(v)}`).join(" · ");
  return h("div", {class: "crash alert danger"}, icon("error"), h("div", {class: "crash-body"},
    h("b", {}, "The experiment stopped because of an error"),
    row("What", `${rep.type}: ${rep.message}`),
    row("Where", [rep.component ? `item “${rep.component}” (${friendlyName(rep.component_type) || rep.component_type})` : "", rep.routine ? `screen “${rep.routine}”` : ""].filter(Boolean).join(" · ")),
    row("When", rep.phase_text + (rep.routine_time ? `, ${rep.routine_time.toFixed(3)} s into the screen` : "")),
    row("Trial", trial),
    rep.user_code ? row("Code", h("code", {class: "mono"}, `line ${rep.user_code.line} of ${rep.user_code.where}: ${rep.user_code.code}`)) : null,
    row("State", vars),
    rep.hint ? h("div", {class: "crash-hint"}, icon("info"), h("span", {}, rep.hint)) : null,
    h("p", {class: "t-caption"}, "Everything recorded until then is saved."),
    rep.routine && typeof openScreen === "function" ? h("button", {type: "button", class: "btn sm", onclick: () => {
      closeModal?.(); ui.closeMenus?.();
      if (rep.component && findComp(rep.routine, rep.component)) EDGE.select({kind: "component", routine: rep.routine, id: rep.component}, {pulse: true});
      else openScreen(rep.routine);
    }}, "Show me") : null));
}

/* ================================================================== preflight: go / no-go before a real session */
const PF_GO = {experiment: ["Show the problems", () => (typeof openProblems === "function" ? openProblems() : EDGE.go("test"))],
  test_run: ["Go to Test", () => EDGE.go("test")], measures: ["Go to Measures", () => EDGE.go("measures")],
  computer: ["Check this computer", () => (typeof computerDialog === "function" ? computerDialog() : null)],
  software: ["Check this computer", () => (typeof computerDialog === "function" ? computerDialog() : null)]};
function preflightBox(onVerdict) {
  const box = h("div", {class: "pf"}, h("p", {class: "pf-busy t-small t-2"}, h("span", {class: "spin"}), " Checking the experiment, a test run with a virtual participant, the lock and this computer…"));
  const ICON = {ok: "success", info: "dot", warning: "warning", error: "error"};
  const draw = async () => {
    let r;
    try { r = await api("/api/preflight", {path: S.path}); }
    catch (e) { box.replaceChildren(h("div", {class: "alert warning"}, icon("warning"), h("div", {}, "The check couldn't run: " + e.message))); onVerdict("go with warnings"); return; }
    const tone = {"go": "success", "go with warnings": "warning", "no-go": "danger"}[r.verdict] || "info";
    const word = {"go": "GO: ready for participants", "go with warnings": "GO, with something to check", "no-go": "NO-GO: not ready yet"}[r.verdict] || r.verdict;
    const out = [h("div", {class: "pf-verdict alert " + tone, role: "status"}, icon(tone === "success" ? "success" : tone === "danger" ? "error" : "warning"),
      h("div", {}, h("b", {}, word), h("span", {class: "t-caption"}, ` · checked in ${r.seconds} s`)))];
    const list = h("div", {class: "pf-list"});
    for (const s of r.sections) {
      const bad = s.items.filter((i) => i.level !== "ok");
      const status = s.status === "info" ? "info" : s.status;
      const summary = h("summary", {}, icon(ICON[status] || "dot", "pf-ic"), h("span", {class: "pf-t"}, s.title.replace(/ \(virtual participant\)$/, "")),
        h("span", {class: "pf-s t-caption"}, (bad[0] || s.items[0])?.text || ""), icon("chev-right", "chev"));
      const sec = h("details", {class: "pf-sec s-" + status, open: s.status === "error" || s.status === "warning" ? "" : null}, summary);
      for (const it of (bad.length ? bad : s.items)) {
        const row = h("div", {class: "pf-item l-" + it.level}, h("div", {}, it.text,
          it.detail ? h("div", {class: "t-caption"}, it.detail) : null, it.hint ? h("div", {class: "t-small pf-hint"}, it.hint) : null,
          it.crash && typeof crashBox === "function" ? crashBox(it.crash) : null));
        if (it.fixable) row.append(h("button", {type: "button", class: "btn sm", onclick: async (e) => { e.currentTarget.disabled = true; e.currentTarget.textContent = "Fixing…";
          const res = await api("/api/system_fix", {id: it.check_id}).catch((err) => ({ok: false, error: err.message}));
          toast(res.ok ? `Done: ${res.done}` : `Couldn't fix it: ${res.error}`, {tone: res.ok ? "success" : "danger", ms: 6000}); draw(); }}, "Fix"));
        sec.append(row);
      }
      const go = PF_GO[s.id];
      if (go && (s.status === "error" || s.status === "warning")) sec.append(h("div", {class: "pf-go"}, h("button", {type: "button", class: "btn sm", onclick: go[1]}, go[0])));
      if (s.id === "lock") {
        const unlocked = s.items.some((i) => /not locked/.test(i.text));
        sec.append(h("div", {class: "pf-go"}, h("button", {type: "button", class: "btn sm", title: "Record versions, file fingerprints and a golden participant, so any inspLater change is caught",
          onclick: async (e) => {
            if (typeof lockExperiment === "function") { await lockExperiment(); draw(); return; }
            e.currentTarget.disabled = true;
            try { const l = await api("/api/lock", {path: S.path}); toast(`Locked: ${countWord(l.files || 0, "file")}, golden participant ${l.trials ?? "–"} trials.`, {tone: "success"}); } catch (err) { toast("Couldn't lock it: " + err.message, {tone: "danger"}); }
            draw();
          }}, icon("lock"), unlocked ? "Lock after piloting…" : "Lock again…")));
      }
      list.append(sec);
    }
    out.push(list, h("p", {class: "t-caption pf-foot"}, "Having trouble? ", h("a", {href: `/api/support_bundle?path=${encodeURIComponent(S.path)}`}, "Make a support bundle"),
      " (everything needed to ask for help, without participant data)."));
    box.replaceChildren(...out);
    onVerdict(r.verdict);
  };
  draw();
  return box;
}
