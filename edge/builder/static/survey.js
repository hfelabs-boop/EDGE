/* EDGE builder: the survey editor.
 *   surveySummary()  – the compact list shown in Properties for a survey component
 *   openSurveyEditor – a wide editor: question list, question form, live preview of the real page
 *   openLibrary      – validated questionnaires (PHQ-9, GAD-7, Big Five …) to add with one click
 * Loaded after app.js and simple.js; uses S, h, $, api, commit, toast, put, clone.
 */
"use strict";

const QT = () => S.schema.survey.question_types;
const LIB = () => S.schema.survey.library;
const SCALES = () => S.schema.survey.scales;
const qLabel = (q) => q.instrument ? `📋 ${(LIB().find((l) => l.id === q.instrument) || {}).title || q.instrument}` : (QT()[q.type] || {}).label || q.type;
const plain = (t) => String(t || "").replace(/<[^>]+>/g, "").trim();

function newQuestionId(qs, base) {
  const taken = new Set();
  const walk = (list) => (list || []).forEach((q) => { if (q.id) taken.add(q.id); (q.items || []).forEach((it) => it.id && taken.add(it.id)); });
  walk(qs);
  return uniqueId(base || "q1", taken);
}

function defaultQuestion(type, qs) {
  const id = newQuestionId(qs, {text_block: "info", page_break: null}[type] === undefined ? "q" + ((qs || []).length + 1) : "info");
  const base = {
    text_block: {type, text: "<p>Instructions or a section heading.</p>"},
    page_break: {type},
    single: {id, type, text: "Your question?", options: ["Option 1", "Option 2", "Option 3"], required: true},
    dropdown: {id, type, text: "Your question?", options: ["Option 1", "Option 2", "Option 3"]},
    multiple: {id, type, text: "Select all that apply.", options: ["Option 1", "Option 2", "Option 3"]},
    likert: {id, type, text: "A statement to rate.", scale: "agree5", required: true},
    matrix: {id, type, text: "How much do you agree with each statement?", scale: "agree5", required: true,
             items: [{id: id + "_1", text: "First statement"}, {id: id + "_2", text: "Second statement"}]},
    semantic: {id, type, text: "The task was …", points: 7, items: [{id: id + "_1", left: "boring", right: "interesting"},
                                                                  {id: id + "_2", left: "easy", right: "difficult"}]},
    scale: {id, type, text: "How do you feel right now?", points: 9, labels: ["Very bad", "Very good"], required: true},
    nps: {id, type, text: "How likely are you to recommend this to a friend?", required: true},
    slider: {id, type, text: "Rate on the line.", min: 0, max: 100, step: 1, labels: ["Not at all", "Extremely"], required: true},
    text: {id, type, text: "Your answer:"},
    essay: {id, type, text: "Please describe …", rows: 5},
    number: {id, type, text: "How many …?", min: 0, max: 100},
    date: {id, type, text: "Date:"},
    rank: {id, type, text: "Put these in order of preference.", options: ["Option A", "Option B", "Option C"]},
    constant_sum: {id, type, text: "Divide 100 points across these options.", options: ["Option A", "Option B"], total: 100, required: true},
  }[type];
  return clone(base);
}

/* ---------------- compact summary in the Properties panel */
function surveySummary(value, onChange) {
  const qs = Array.isArray(value) ? value : [];
  const box = h("div", {class: "sv-summary"});
  if (!qs.length) put(box, h("div", {class: "help"}, "No questions yet."));
  let page = 1;
  qs.forEach((q, i) => {
    if (q.type === "page_break") { page++; put(box, h("div", {class: "sv-pb"}, `— page ${page} —`)); return; }
    put(box, h("div", {class: "sv-row", onclick: () => openSurveyEditor(i)},
      h("span", {class: "sv-type"}, qLabel(q)), h("span", {}, q.instrument ? "" : short(plain(q.text), 46))));
  });
  put(box, h("div", {class: "btns"},
    h("button", {class: "primary", onclick: () => openSurveyEditor(0)}, "✎ Edit questions"),
    h("button", {onclick: () => openLibrary((ins) => { onChange([...qs, {instrument: ins.id}]); toast(`Added ${ins.title}`); })}, "+ Questionnaire")));
  return box;
}

/* ---------------- the editor */
const SV = {sel: 0, comp: null, frame: null, timer: null};
function surveyComp() {
  const sel = S.sel;
  if (!sel || sel.kind !== "component") return null;
  const c = findComp(sel.routine, sel.id);
  return c && c.type === "survey" ? c : null;
}

function openSurveyEditor(index = 0) {
  const c = surveyComp(); if (!c) return;
  c.questions ||= [];
  SV.sel = Math.min(index, Math.max(0, c.questions.length - 1));
  renderSurveyEditor();
}

function svCommit(rerenderList = true) {
  commit(false); renderProps();
  if (rerenderList) renderSurveyEditor(); else svPreview();
}

function renderSurveyEditor() {
  const c = surveyComp(); if (!c) return closeModal();
  const qs = c.questions;
  const body = $("#modal-body"); body.innerHTML = ""; body.className = "sveditor";
  const list = h("div", {class: "sv-list"});
  let page = 1;
  put(list, h("div", {class: "sv-page"}, "Page 1"));
  qs.forEach((q, i) => {
    if (q.type === "page_break") { page++; }
    const row = h("div", {class: "sv-item" + (i === SV.sel ? " sel" : "") + (q.type === "page_break" ? " pb" : ""), draggable: "true",
      onclick: () => { SV.sel = i; renderSurveyEditor(); }},
      q.type === "page_break" ? h("span", {class: "sv-pbl"}, `— page break — page ${page} starts`) :
        [h("span", {class: "sv-n"}, String(i + 1)), h("div", {class: "sv-t"}, h("small", {}, qLabel(q) + (q.required ? " · required" : "") + (q.show_if ? " · conditional" : "")),
          h("div", {}, q.instrument ? (LIB().find((l) => l.id === q.instrument) || {}).description?.slice(0, 70) + "…" : short(plain(q.text), 60) || "(no text)"))],
      h("span", {class: "sv-acts"},
        h("button", {class: "mini", title: "Move up", onclick: (e) => { e.stopPropagation(); if (i > 0) { [qs[i - 1], qs[i]] = [qs[i], qs[i - 1]]; SV.sel = i - 1; svCommit(); } }}, "↑"),
        h("button", {class: "mini", title: "Duplicate", onclick: (e) => { e.stopPropagation(); const cp = clone(q); if (cp.id) cp.id = newQuestionId(qs, cp.id + "_copy");
          (cp.items || []).forEach((it, k) => { it.id = (cp.id || "item") + "_" + (k + 1); }); qs.splice(i + 1, 0, cp); SV.sel = i + 1; svCommit(); }}, "⧉"),
        h("button", {class: "mini danger", title: "Delete", onclick: (e) => { e.stopPropagation(); qs.splice(i, 1); SV.sel = Math.max(0, i - 1); svCommit(); }}, "×")));
    row.addEventListener("dragstart", (e) => e.dataTransfer.setData("edge/q", String(i)));
    row.addEventListener("dragover", (e) => e.preventDefault());
    row.addEventListener("drop", (e) => { e.preventDefault(); const from = +e.dataTransfer.getData("edge/q"); if (isNaN(from) || from === i) return;
      const [m] = qs.splice(from, 1); qs.splice(i, 0, m); SV.sel = i; svCommit(); });
    put(list, row);
  });
  const addMenu = (e) => {
    const groups = {};
    for (const [t, d] of Object.entries(QT())) (groups[d.group] ||= []).push([t, d]);
    const items = [];
    for (const [g, arr] of Object.entries(groups)) { if (items.length) items.push("-");
      for (const [t, d] of arr) items.push([`${d.label}  ·  ${g}`, () => { qs.splice(SV.sel + 1, 0, defaultQuestion(t, qs)); SV.sel = Math.min(SV.sel + 1, qs.length - 1); if (!qs[SV.sel]) SV.sel = qs.length - 1; svCommit(); }]); }
    menu(e, items);
  };
  put(list, h("div", {class: "sv-add"},
    h("button", {class: "primary", onclick: addMenu}, "+ Question"),
    h("button", {onclick: () => openLibrary((ins) => { qs.splice(SV.sel + 1, 0, {instrument: ins.id}); SV.sel = Math.min(SV.sel + 1, qs.length - 1); svCommit(); }, true)}, "+ From library")));

  const form = h("div", {class: "sv-form"});
  const q = qs[SV.sel];
  if (q) renderQuestionForm(form, q, qs, c); else put(form, h("div", {class: "help"}, "Add a question, or a validated questionnaire from the library."));

  const settings = h("div", {class: "sv-settings"},
    svField("Title", c.title || "", (v) => { if (v) c.title = v; else delete c.title; svCommit(false); }),
    svField("Instructions on the first page", c.intro || "", (v) => { if (v) c.intro = v; else delete c.intro; svCommit(false); }, {area: true}));
  SV.frame = h("iframe", {class: "sv-frame", title: "Survey preview", sandbox: "allow-scripts"});
  const probs = h("div", {class: "sv-problems"});
  SV.problems = probs;
  put(body, h("div", {class: "sv-head"}, h("h3", {}, `Survey · ${c.id}`), h("span", {class: "help"}, "Changes are saved into the experiment as you type. The preview on the right is the real page; try it."),
    h("button", {class: "mini sv-close", onclick: () => { closeModal(); renderAll(); }}, "Done")),
    h("div", {class: "sv-cols"}, h("div", {class: "sv-left"}, settings, list), form, h("div", {class: "sv-right"}, probs, SV.frame)));
  openModal(); svPreview();
}

function svField(label, value, onChange, opts = {}) {
  const inp = opts.area ? h("textarea", {rows: opts.rows || 2, onchange: (e) => onChange(e.target.value)}, value ?? "")
    : h("input", {value: value ?? "", type: opts.type || "text", placeholder: opts.placeholder || "", onchange: (e) => onChange(e.target.value)});
  return h("div", {class: "field"}, h("label", {}, h("span", {}, label)), inp, opts.help ? h("div", {class: "help"}, opts.help) : null);
}
function svCheck(label, value, onChange, help) {
  const cb = h("input", {type: "checkbox", onchange: (e) => onChange(e.target.checked)}); cb.checked = !!value;
  return h("div", {class: "field"}, h("label", {class: "sv-cb"}, cb, " ", label), help ? h("div", {class: "help"}, help) : null);
}
function svSelect(label, value, choices, onChange, help) {
  const sel = h("select", {onchange: (e) => onChange(e.target.value)}, choices.map(([v, l]) => { const o = h("option", {value: v}, l); if (String(value) === String(v)) o.selected = true; return o; }));
  return h("div", {class: "field"}, h("label", {}, h("span", {}, label)), sel, help ? h("div", {class: "help"}, help) : null);
}
const numOrBlank = (v) => v === "" || v === null || v === undefined ? undefined : (isNaN(Number(v)) ? v : Number(v));

/* options <-> text: "1 = Strongly disagree" keeps a code, plain lines are their own value */
function optionsToText(opts) {
  return (opts || []).map((o) => typeof o === "object" ? (String(o.value) === String(o.label) ? o.label : `${o.value} = ${o.label}`) : String(o)).join("\n");
}
function textToOptions(t) {
  return t.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l) => {
    const m = l.match(/^(-?\d+(?:\.\d+)?|[A-Za-z_]\w*)\s*=\s*(.+)$/);
    if (m) return {value: isNaN(Number(m[1])) ? m[1] : Number(m[1]), label: m[2].trim()};
    return l;
  });
}
function optionLabels(q) {
  if (q.options) return q.options.map((o) => typeof o === "object" ? o.label : String(o));
  if (q.scale && SCALES()[q.scale]) return SCALES()[q.scale].options.map((o) => o.label);
  return [];
}

function renderQuestionForm(form, q, qs, comp) {
  const set = (k, v, rerender = false) => { if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) delete q[k]; else q[k] = v; svCommit(rerender); };
  if (q.instrument) return renderInstrumentForm(form, q, qs, comp);
  const t = q.type, d = QT()[t] || {};
  put(form, h("div", {class: "sv-formhead"}, h("b", {}, d.label || t),
    t !== "page_break" ? svSelect("", t, Object.entries(QT()).filter(([k]) => k !== "page_break").map(([k, x]) => [k, x.label]), (v) => {
      const nq = defaultQuestion(v, qs); nq.id = q.id || nq.id; if (q.text && nq.text !== undefined) nq.text = q.text; if (q.required !== undefined && d.answer) nq.required = q.required;
      if (q.options && nq.options && ["single", "dropdown", "multiple", "rank", "constant_sum"].includes(v)) nq.options = q.options;
      qs[SV.sel] = nq; svCommit(); }) : null));
  if (t === "page_break") { put(form, h("p", {class: "help"}, "Questions after this start on a new page. Participants press Next to continue (and can go Back unless you turn that off).")); return; }
  if (d.answer) put(form, svField("Data name (column)", q.id || "", (v) => { v = v.trim(); if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(v)) return toast("Letters, digits and _ only"); q.id = v; svCommit(); },
    {help: `saved as ${comp.id}.${q.id || "…"}`}));
  put(form, svField(t === "text_block" ? "Text (HTML allowed)" : "Question", q.text || "", (v) => set("text", v, true), {area: true, rows: t === "text_block" ? 6 : 3,
    help: d.answer ? "Show an earlier answer with {{answer.<name>}}; trial values with {{column}}." : ""}));
  if (!d.answer) return;
  put(form, svCheck("Required (forced response)", q.required, (v) => set("required", v || undefined, true)));
  const opt = h("div", {class: "sv-sub"});
  if (["single", "dropdown", "multiple", "likert", "matrix", "rank", "constant_sum"].includes(t)) {
    const scaleChoices = [["", "my own options"], ...Object.entries(SCALES()).map(([k, s]) => [k, s.title])];
    if (["likert", "matrix", "single"].includes(t)) put(opt, svSelect("Answer scale", q.scale && !q.options ? q.scale : "", scaleChoices, (v) => {
      if (v) { q.scale = v; delete q.options; } else { q.options = q.options || (q.scale ? clone(SCALES()[q.scale].options) : ["Option 1", "Option 2"]); delete q.scale; } svCommit(); },
      "a standard scale, or type your own options"));
    if (!(q.scale && !q.options && ["likert", "matrix", "single"].includes(t)))
      put(opt, svField("Options (one per line)", optionsToText(q.options), (v) => set("options", textToOptions(v), true),
        {area: true, rows: 5, help: "Write “1 = Strongly disagree” to save a number code instead of the text."}));
    else put(opt, h("div", {class: "help"}, SCALES()[q.scale].options.map((o) => `${o.value} = ${o.label}`).join(" · ")));
  }
  if (["single", "multiple"].includes(t)) put(opt, svSelect("Layout", q.layout || "vertical", [["vertical", "one per line"], ["horizontal", "side by side"]], (v) => set("layout", v === "vertical" ? undefined : v)));
  if (["single", "dropdown", "multiple", "rank", "constant_sum", "matrix"].includes(t)) put(opt, svCheck(t === "matrix" ? "Shuffle the statements" : "Shuffle the options", q.randomize, (v) => set("randomize", v || undefined),
    "the order each participant saw is saved"));
  if (t === "single") put(opt, svSelect("“Other, please specify” text box for", q.other_option || "", [["", "(none)"], ...optionLabels(q).map((l) => [l, l])], (v) => set("other_option", v || undefined)));
  if (t === "multiple") {
    put(opt, h("div", {class: "row2"}, svField("At least", q.min_choices ?? "", (v) => set("min_choices", numOrBlank(v)), {type: "number"}),
      svField("At most", q.max_choices ?? "", (v) => set("max_choices", numOrBlank(v)), {type: "number"})));
    put(opt, svSelect("Exclusive option (unticks the others)", (q.exclusive || [])[0] ?? "", [["", "(none)"], ...optionLabels(q).map((l) => [l, l])], (v) => set("exclusive", v ? [v] : undefined),
      "e.g. “None of these”"));
  }
  if (t === "matrix") put(opt, svField("Statements (one per line; end with (R) to reverse-score)", (q.items || []).map((it) => plain(it.text) + (it.reverse ? " (R)" : "")).join("\n"), (v) => {
    const lines = v.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    q.items = lines.map((l, k) => { const rev = /\(R\)\s*$/.test(l); const old = (q.items || [])[k];
      return {id: old?.id || `${q.id}_${k + 1}`, text: l.replace(/\s*\(R\)\s*$/, ""), ...(rev ? {reverse: true} : {})}; });
    svCommit(true); }, {area: true, rows: 6, help: `each statement is saved as ${q.id}_1, ${q.id}_2 …`}));
  if (t === "semantic") {
    put(opt, svField("Word pairs (one per line: left | right)", (q.items || []).map((it) => `${it.left} | ${it.right}`).join("\n"), (v) => {
      q.items = v.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l, k) => { const [a, b] = l.split("|").map((x) => (x || "").trim()); const old = (q.items || [])[k];
        return {id: old?.id || `${q.id}_${k + 1}`, left: a, right: b || ""}; }); svCommit(true); }, {area: true, rows: 5}));
    put(opt, svField("Points", q.points ?? 7, (v) => set("points", numOrBlank(v)), {type: "number"}));
  }
  if (t === "scale") put(opt, svField("Points", q.points ?? 7, (v) => set("points", numOrBlank(v)), {type: "number"}));
  if (["scale", "slider"].includes(t)) put(opt, h("div", {class: "row2"},
    svField("Left label", (q.labels || [])[0] || "", (v) => set("labels", [v, (q.labels || [])[1] || ""])),
    svField("Right label", (q.labels || [])[1] || "", (v) => set("labels", [(q.labels || [])[0] || "", v]))));
  if (["slider", "number"].includes(t)) put(opt, h("div", {class: "row2"},
    svField("Min", q.min ?? "", (v) => set("min", numOrBlank(v)), {type: "number"}), svField("Max", q.max ?? "", (v) => set("max", numOrBlank(v)), {type: "number"}),
    svField("Step", q.step ?? "", (v) => set("step", numOrBlank(v)), {type: "number"})));
  if (t === "text") put(opt, svSelect("Check the answer", q.validate || "", [["", "anything"], ["email", "e-mail address"], ["number", "number"], ["integer", "whole number"]], (v) => set("validate", v || undefined)),
    svField("Pattern (regular expression, optional)", q.pattern || "", (v) => set("pattern", v || undefined), {help: "e.g. [A-Z]{2}[0-9]{4} for a participant code"}));
  if (["text", "essay"].includes(t)) put(opt, h("div", {class: "row2"},
    t === "essay" ? svField("Min characters", q.min_length ?? "", (v) => set("min_length", numOrBlank(v)), {type: "number"}) : null,
    svField("Max characters", q.max_length ?? "", (v) => set("max_length", numOrBlank(v)), {type: "number"})));
  if (t === "constant_sum") put(opt, svField("Total", q.total ?? 100, (v) => set("total", numOrBlank(v)), {type: "number"}));
  if (["single", "likert", "dropdown", "text", "number"].includes(t)) put(opt, svField("Correct answer (knowledge or attention check, optional)", q.correct ?? "", (v) => set("correct", numOrBlank(v)),
    {help: "add a score with method “correct” to count right answers"}));
  put(form, opt);
  put(form, renderShowIf(q, qs));
  put(form, svField("Help text under the question", q.help || "", (v) => set("help", v || undefined, true)));
}

function renderShowIf(q, qs) {
  const box = h("div", {class: "sv-sub"}, h("div", {class: "sv-subhead"}, "Display logic"));
  const earlier = [];
  for (const x of qs.slice(0, SV.sel)) {
    if (x.instrument) continue;
    if (x.type === "matrix" || x.type === "semantic") (x.items || []).forEach((it) => earlier.push([it.id, `${it.id}: ${short(plain(it.text || it.left), 30)}`, x]));
    else if ((QT()[x.type] || {}).answer && x.id) earlier.push([x.id, `${x.id}: ${short(plain(x.text), 30)}`, x]);
  }
  const cond = q.show_if;
  const simple = cond && Object.keys(cond).length === 1 && !["any", "all"].includes(Object.keys(cond)[0]);
  const key = simple ? Object.keys(cond)[0] : "";
  let op = "=", val = "";
  if (simple) { const v = cond[key]; if (v !== null && typeof v === "object" && !Array.isArray(v)) { op = Object.keys(v)[0]; val = v[op]; } else val = v; }
  if (cond && !simple) {
    put(box, h("div", {class: "help"}, "Advanced condition (edit as JSON):"), h("input", {value: JSON.stringify(cond), onchange: (e) => { try { q.show_if = JSON.parse(e.target.value); svCommit(true); } catch { toast("Not valid JSON"); } }}));
    return box;
  }
  const qsel = h("select", {}, h("option", {value: ""}, "always show"), earlier.map(([id, lab]) => { const o = h("option", {value: id}, "only if " + lab); if (id === key) o.selected = true; return o; }));
  const osel = h("select", {}, [["=", "is"], ["!=", "is not"], [">", ">"], [">=", "≥"], ["<", "<"], ["<=", "≤"], ["contains", "includes"], ["answered", "was answered"]].map(([v, l]) => { const o = h("option", {value: v}, l); if (v === op) o.selected = true; return o; }));
  const src = earlier.find(([id]) => id === key);
  const labels = src ? optionLabels(src[2]) : [];
  const opts = src && src[2].options ? src[2].options.map((o) => typeof o === "object" ? o : {value: o, label: o}) : src && src[2].scale ? SCALES()[src[2].scale].options : [];
  const vinp = opts.length ? h("select", {}, opts.map((o) => { const e = h("option", {value: String(o.value)}, o.label); if (String(o.value) === String(val)) e.selected = true; return e; }))
    : h("input", {value: op === "answered" ? "" : (val ?? ""), placeholder: "value"});
  const apply = () => {
    const k = qsel.value; if (!k) { delete q.show_if; return svCommit(true); }
    const o = osel.value; let v = vinp.value; v = numOrBlank(v) ?? v;
    const match = opts.find((x) => String(x.value) === String(vinp.value)); if (match) v = match.value;
    q.show_if = o === "answered" ? {[k]: {answered: true}} : o === "=" ? {[k]: v} : {[k]: {[o]: v}}; svCommit(true);
  };
  qsel.onchange = apply; osel.onchange = apply; vinp.onchange = apply;
  put(box, h("div", {class: "sv-cond"}, qsel, key ? osel : null, key && op !== "answered" ? vinp : null));
  if (!earlier.length) put(box, h("div", {class: "help"}, "Questions can depend on answers to questions before them."));
  void labels;
  return box;
}

function renderInstrumentForm(form, q, qs, comp) {
  const ins = LIB().find((l) => l.id === q.instrument);
  if (!ins) { put(form, h("div", {class: "issue error"}, `Unknown questionnaire “${q.instrument}”.`)); return; }
  put(form, h("div", {class: "sv-formhead"}, h("b", {}, ins.title)),
    h("p", {}, ins.description),
    h("div", {class: "sv-meta"}, `${ins.items} items · about ${ins.minutes} min · scores: ${ins.scores.join(", ") || "none"}`),
    h("p", {class: "help"}, h("b", {}, "Cite: "), ins.citation), h("p", {class: "help"}, h("b", {}, "Licence: "), ins.licence),
    svSelect("Answers required", q.required === undefined ? "" : q.required ? "yes" : "no", [["", "as published (usually yes)"], ["yes", "all required"], ["no", "all optional"]],
      (v) => { if (v === "") delete q.required; else q.required = v === "yes"; svCommit(false); }),
    h("div", {class: "btns"}, h("button", {onclick: async () => {
      if (!confirm(`Copy the ${ins.items} items of ${ins.title} into this survey so you can edit them? Scoring is kept; edits to the wording mean it is no longer the validated version.`)) return;
      const full = await api("/api/survey/instrument", {id: ins.id});
      qs.splice(SV.sel, 1, ...full.questions);
      comp.scores = {...(comp.scores || {}), ...(full.scores || {})}; svCommit(); }}, "Customize (copy the items here)")),
    h("p", {class: "help"}, "Check the wording and licence against the original before collecting data, especially for translations or clinical and commercial use."));
}

let _svCache = {key: null};
function svPreview() {
  clearTimeout(SV.timer);
  SV.timer = setTimeout(async () => {
    const c = surveyComp(); if (!c || !SV.frame) return;
    const spec = {questions: c.questions, title: c.title, intro: c.intro, scores: c.scores, progress_bar: c.progress_bar, allow_back: c.allow_back,
      submit_label: c.submit_label, next_label: c.next_label, back_label: c.back_label, labels: c.labels, css: c.css};
    try {
      const r = await api("/api/survey/render", {spec});
      SV.problems.innerHTML = "";
      if (r.problems.length) put(SV.problems, r.problems.map((p) => h("div", {class: "issue error"}, cap(p))));
      else SV.frame.srcdoc = r.html;
    } catch (e) { SV.problems.textContent = e.message; }
  }, 250);
}

/* the survey page shown in the screen preview (and its cache) */
function surveyPreviewHtml(c, done) {
  const spec = {questions: c.questions || [], title: c.title, intro: c.intro, scores: c.scores};
  const key = JSON.stringify(spec);
  if (_svCache.key === key) return _svCache.html;
  _svCache = {key, html: null};
  api("/api/survey/render", {spec}).then((r) => { if (_svCache.key === key) { _svCache.html = r.html || `<pre style="padding:20px;color:#c00">${(r.problems || []).join("\n")}</pre>`; done(); } }).catch(() => {});
  return null;
}

/* ---------------- questionnaire library */
function openLibrary(onPick, returnToEditor = false) {
  const body = $("#modal-body"); body.innerHTML = ""; body.className = "svlib";
  const filter = h("input", {type: "search", placeholder: "Search: depression, Big Five, workload, consent …", class: "help-search"});
  const grid = h("div", {class: "svlib-grid"});
  const draw = () => {
    grid.innerHTML = "";
    const f = filter.value.toLowerCase();
    let cat = null;
    for (const ins of LIB()) {
      if (f && !(ins.title + ins.description + ins.category + ins.id).toLowerCase().includes(f)) continue;
      if (ins.category !== cat) { cat = ins.category; put(grid, h("h4", {class: "svlib-cat"}, cat)); }
      put(grid, h("div", {class: "card svlib-card"}, h("b", {}, ins.title),
        h("small", {}, `${ins.items} item${ins.items === 1 ? "" : "s"} · ~${ins.minutes} min${ins.scores.length ? " · scored" : ""}`),
        h("p", {}, ins.description), h("small", {class: "svlib-cite"}, ins.citation),
        h("div", {class: "btns"}, h("button", {class: "primary", onclick: () => { onPick(ins); if (!returnToEditor) closeModal(); }}, "Add"))));
    }
  };
  filter.oninput = draw;
  put(body, h("div", {class: "sv-head"}, h("h3", {}, "Questionnaire library"),
    h("span", {class: "help"}, "Validated, free-to-use instruments with their scoring. Each adds its own data columns and scores."),
    returnToEditor ? h("button", {class: "mini sv-close", onclick: () => renderSurveyEditor()}, "← Back to the editor") : h("button", {class: "mini sv-close", onclick: closeModal}, "Close")),
    filter, grid);
  draw(); openModal(); filter.focus();
}
