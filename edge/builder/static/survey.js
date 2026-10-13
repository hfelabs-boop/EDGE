/* survey.js: the survey editor and the questionnaire library (SPEC §2.7 "Survey editor", W8). Owner: P4b.
 *   surveySummary()   - the compact question list the inspector shows for a survey item, with [Edit questions]
 *   openSurveyEditor  - a full-size dialog in three panes: the questions (with the survey's title and language), the
 *                       form of the selected question, and a live preview of the real page
 *   openLibrary       - validated questionnaires (PHQ-9, GAD-7, Big Five ...) to add with one click (dialog lg)
 *   surveyPreviewHtml - the rendered page for the screen preview in Build (cached)
 * Every change commits at once (one undo step each); the editor redraws on "doc:changed", so Undo works inside it.
 */
"use strict";

const QT = () => S.schema.survey.question_types;
const LIB = () => S.schema.survey.library;
const SCALES = () => S.schema.survey.scales;
const plain = (t) => String(t || "").replace(/<[^>]+>/g, "").trim();
const libItem = (id) => LIB().find((l) => l.id === id) || null;
const qLabel = (q) => (q.instrument ? "Questionnaire" : (QT()[q.type] || {}).label || q.type);
/* What a question says, in one line: its text, or the title of a validated questionnaire. */
const qText = (q, n = 60) => (q.instrument ? libItem(q.instrument)?.title || q.instrument : short(plain(q.text), n));

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
    form: {id, type, text: "Your contact details", fields: [{id: id + "_name", label: "Name", required: true}, {id: id + "_email", label: "E-mail", type: "email"}]},
    side_by_side: {id, type, text: "About each brand", items: [{id: id + "_a", text: "Brand A"}, {id: id + "_b", text: "Brand B"}],
                   columns: [{id: "aware", label: "Heard of it?", type: "single", options: ["Yes", "No"]}, {id: "quality", label: "Quality", type: "dropdown", scale: "quality5"}]},
    group: {id, type, text: "Sort these into groups.", items: ["Item 1", "Item 2", "Item 3"], groups: ["Group A", "Group B"]},
    hot_spot: {id, type, text: "Click the parts you notice first.", image: "", regions: [], mode: "select"},
    heat_map: {id, type, text: "Click where you would look first.", image: "", max_clicks: 1},
    graphic_slider: {id, type, text: "How do you feel?", style: "faces", points: 7, labels: ["Very bad", "Very good"]},
    drill_down: {id, type, text: "Where do you live?", levels: ["Country", "City"], rows: [["France", "Paris"], ["France", "Lyon"], ["Japan", "Tokyo"]]},
    highlight: {id, type, text: "Highlight what you like and dislike.", passage: "The food was great but the service was slow."},
    signature: {id, type, text: "Please sign to confirm.", required: true},
    timing: {id: newQuestionId(qs, "timing"), type},
    meta_info: {id: newQuestionId(qs, "meta"), type},
    file_upload: {id, type, text: "Attach a file.", max_mb: 10},
    captcha: {id: newQuestionId(qs, "captcha"), type, text: "Please type the code."},
    autocomplete: {id, type, text: "In which country do you live?", list: "countries"},
    tree_test: {id, type, text: "Where would you find it?", task: "Where would you go to return a product?",
                rows: [["Shop", "Phones"], ["Shop", "Laptops"], ["Help", "Returns"], ["Help", "Shipping"]], correct: "Help > Returns"},
    video_response: {id, type, text: "Please tell us about your experience.", max_seconds: 60},
    screen_capture: {id, type, text: "Show us the problem on your screen."},
    location: {id, type, text: "Where were you born?", allow_geolocation: false, image: ""},
  }[type];
  return clone(base);
}

/* ================================================================== the summary in the inspector */
function surveySummary(value, onChange) {
  const qs = Array.isArray(value) ? value : [];
  const box = h("div", {class: "sv-summary"});
  if (!qs.length) box.append(h("p", {class: "help"}, "No questions yet. Add your own, or a validated questionnaire."));
  else {
    const ul = h("ul", {class: "sv-sumlist", "aria-label": "Questions"});
    let page = 1;
    qs.forEach((q, i) => {
      if (q.type === "page_break") { page++; ul.append(h("li", {class: "sv-pb"}, `Page ${page}`)); return; }
      ul.append(h("li", {}, h("button", {type: "button", class: "sv-row", title: "Edit this question", onclick: () => openSurveyEditor(i)},
        h("span", {class: "sv-type"}, qLabel(q)), h("span", {class: "sv-txt"}, qText(q)))));
    });
    box.append(ul);
  }
  box.append(h("div", {class: "sv-btns"},
    h("button", {type: "button", class: "btn sm primary", "data-fkey": "sv:edit", onclick: () => openSurveyEditor(0)}, icon("survey"), "Edit questions"),
    h("button", {type: "button", class: "btn sm", onclick: () => openLibrary((ins) => { onChange([...qs, {instrument: ins.id}]); toast(`Added ${ins.title}.`); })},
      icon("plus"), "Add a questionnaire")));
  return box;
}

/* ================================================================== the editor (dialog .full) */
const SV = {sel: 0, rid: null, cid: null, setOpen: null, dlg: null, close: null, root: null, left: null, form: null, frame: null, problems: null, timer: null, redraw: null, off: null, drag: null};
let svSeq = 0;
function surveyComp() {
  let c = SV.rid && SV.cid ? findComp(SV.rid, SV.cid) : null;
  if (!c && S.sel?.kind === "component") c = findComp(S.sel.routine, S.sel.id);
  return c && c.type === "survey" ? c : null;
}

function openSurveyEditor(index = 0) {
  const sel = S.sel;
  if (!SV.dlg) {
    if (!sel || sel.kind !== "component") return;
    SV.rid = sel.routine; SV.cid = sel.id;
  }
  const c = surveyComp(); if (!c) return;
  if (S.proposal) { toast("Apply or discard the assistant's changes first"); return; }
  c.questions ||= [];
  SV.sel = Math.max(0, Math.min(index, c.questions.length - 1));
  if (SV.dlg) { renderSurveyEditor(); return; }
  SV.setOpen = null;
  SV.left = h("div", {class: "sv-left"});
  SV.form = h("div", {class: "sv-form", role: "region", "aria-label": "The selected question"});
  SV.frame = h("iframe", {class: "sv-frame", title: "Preview of the survey page", sandbox: "allow-scripts"});
  SV.problems = h("div", {class: "sv-problems", role: "status"});
  const right = h("div", {class: "sv-right"}, h("h3", {class: "t-overline"}, "Preview: the real page, try it"), SV.problems, SV.frame);
  SV.root = h("div", {class: "sv-cols"}, SV.left, SV.form, right);
  SV.off = EDGE.on("doc:changed", () => svScheduleRedraw());
  ui.dialog({title: `Survey “${c.id}”`, icon: "survey", size: "full", body: SV.root,
    buttons: [{label: "Done", value: null, kind: "primary"}],
    initialFocus: ".sv-pick[aria-current='true'], .sv-pick",       // the selected question, not the footer's Done
    returnFocus: () => document.querySelector('#props [data-fkey="sv:edit"]'),
    onOpen: (dlg, close) => {
      SV.dlg = dlg; SV.close = close;
      dlg.classList.add("survey-dialog");
      dlg.querySelector("footer")?.prepend(h("span", {class: "t-caption left"}, "Every change is saved into the experiment at once; Undo reverts it."));
    }}).then(() => {
    SV.off?.(); SV.off = null; SV.dlg = null; SV.close = null; SV.root = null; clearTimeout(SV.timer); clearTimeout(SV.redraw);
    if (S.ws === "build") renderAll();
  });
  renderSurveyEditor();
  SV.dlg?.querySelector(".sv-pick[aria-current='true'], .sv-pick")?.focus();     // start at the selected question
}

/* Commit a change; the editor redraws after the browser has moved focus (Tab), then gives focus back. */
function svCommit(label = "Edit the survey") {
  commit(`${label} (“${SV.cid || "survey"}”)`);
}
function svScheduleRedraw() {
  clearTimeout(SV.redraw);
  SV.redraw = setTimeout(() => { if (SV.dlg) { if (!surveyComp()) SV.close?.(null); else renderSurveyEditor(); } }, 0);
}

function renderSurveyEditor() {
  const c = surveyComp(); if (!c || !SV.root) return;
  const qs = (c.questions ||= []);
  SV.sel = Math.max(0, Math.min(SV.sel, qs.length - 1));
  // keep focus and the scroll positions across the redraw
  const a = document.activeElement;
  const keep = a && SV.root.contains(a) ? a.dataset?.fkey : null;
  const scroll = [SV.left.scrollTop, SV.form.scrollTop];
  svSeq = 0;
  SV.left.replaceChildren(svSettings(c), ...svQuestionList(c, qs));
  const q = qs[SV.sel];
  const form = [];
  if (q) renderQuestionForm(form, q, qs, c);
  else form.push(h("div", {class: "empty"}, h("span", {class: "ic-wrap"}, icon("survey")), h("p", {}, "No questions yet. Add a question, or a validated questionnaire from the library.")));
  SV.form.replaceChildren(...form.flat().filter(Boolean));
  [SV.left.scrollTop, SV.form.scrollTop] = scroll;
  if (keep) {
    const t = SV.root.querySelector(`[data-fkey="${CSS.escape(keep)}"]`);
    if (t) t.focus({preventScroll: true});
  }
  svPreview();
}

function svSettings(c) {
  const set = (k, v, label) => { if (v === "" || v === null || v === undefined) delete c[k]; else c[k] = v; svCommit(label); };
  if (SV.setOpen === null) SV.setOpen = innerHeight >= 860;
  const box = h("details", {class: "sv-settings", open: SV.setOpen ? "" : null},
    h("summary", {"data-fkey": "sv:settings"}, icon("chev-right", "chev"), h("span", {}, "Title and language"), h("span", {class: "t-caption sv-setcap"}, c.title || "No title")),
    h("div", {class: "sv-setbody"}, ...svSettingFields(c, set)));
  box.addEventListener("toggle", () => { SV.setOpen = box.open; });
  return box;
}
function svSettingFields(c, set) {
  return [
    svField("Title", c.title || "", (v) => set("title", v, "Change the survey title"), {key: "s:title"}),
    svField("Instructions on the first page", c.intro || "", (v) => set("intro", v, "Change the survey instructions"), {area: true, key: "s:intro"}),
    h("div", {class: "row2"},
      svSelect("Language of the buttons", c.language || "", [["", "Automatic"], ["en", "English"], ["de", "Deutsch"], ["es", "Español"], ["fr", "Français"], ["he", "Hebrew (right to left)"]],
        (v) => set("language", v, "Change the survey language"), "", "s:lang"),
      svSelect("Text direction", c.direction || "auto", [["auto", "Automatic"], ["ltr", "Left to right"], ["rtl", "Right to left"]],
        (v) => set("direction", v === "auto" ? "" : v, "Change the text direction"), "", "s:dir"))];
}

function svQuestionList(c, qs) {
  const list = h("ol", {class: "sv-list", "aria-label": "Questions"});
  let page = 1;
  list.append(h("li", {class: "sv-page t-overline", "aria-hidden": "true"}, "Page 1"));
  qs.forEach((q, i) => {
    const pb = q.type === "page_break";
    if (pb) page++;
    const text = pb ? `Page ${page} starts here` : qText(q, 70) || "(no text)";
    const sub = pb ? "Page break" : qLabel(q) + (q.required ? " · required" : "") + (q.show_if ? " · only if…" : "");
    const pick = h("button", {type: "button", class: "sv-pick", "data-fkey": `svq:${i}`, "aria-current": i === SV.sel ? "true" : null,
      title: "Alt+↑ / Alt+↓ moves it", onclick: () => { SV.sel = i; renderSurveyEditor(); },
      onkeydown: (e) => { if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); svMove(qs, i, e.key === "ArrowUp" ? -1 : 1); } }},
    h("span", {class: "sv-n", "aria-hidden": "true"}, pb ? "" : String(i + 1)), h("span", {class: "sv-t"}, h("small", {}, sub), h("span", {}, text)));
    const acts = h("span", {class: "sv-acts"},
      h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Move question ${i + 1} up`, title: "Move up", disabled: i === 0 ? "" : null, onclick: () => svMove(qs, i, -1)}, icon("chev-down", "flip")),
      h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Duplicate question ${i + 1}`, title: "Duplicate", onclick: () => {
        const cp = clone(q); if (cp.id) cp.id = newQuestionId(qs, cp.id + "_copy");
        (cp.items || []).forEach((it, k) => { if (it && typeof it === "object") it.id = (cp.id || "item") + "_" + (k + 1); });
        qs.splice(i + 1, 0, cp); SV.sel = i + 1; svCommit("Duplicate a question");
      }}, icon("duplicate")),
      h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Delete question ${i + 1}`, title: "Delete", onclick: () => {
        const idx = EDGE.historyIndex();
        qs.splice(i, 1); SV.sel = Math.max(0, i - 1); svCommit("Delete a question");
        ui.toast(pb ? "Deleted the page break." : `Deleted “${short(plain(q.text) || qLabel(q), 40)}”.`, {action: {label: "Undo", run: () => { if (!EDGE.undoIf(idx + 1)) toast("Other changes came after this one: use Undo."); }}});
      }}, icon("trash")));
    const li = h("li", {class: "sv-item" + (i === SV.sel ? " sel" : "") + (pb ? " pb" : ""), draggable: "true"}, pick, acts);
    li.addEventListener("dragstart", (e) => { SV.drag = i; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(i)); li.classList.add("dragging"); });
    li.addEventListener("dragend", () => { SV.drag = null; li.classList.remove("dragging"); });
    li.addEventListener("dragover", (e) => { if (SV.drag === null) return; e.preventDefault(); li.classList.add("drop-before"); });
    li.addEventListener("dragleave", () => li.classList.remove("drop-before"));
    li.addEventListener("drop", (e) => {
      e.preventDefault(); li.classList.remove("drop-before");
      const from = SV.drag; SV.drag = null;
      if (from === null || from === i) return;
      const [m] = qs.splice(from, 1); qs.splice(from < i ? i - 1 : i, 0, m); SV.sel = from < i ? i - 1 : i; svCommit("Move a question");
    });
    list.append(li);
  });
  const head = h("div", {class: "sv-qhead"}, h("h3", {class: "t-title-s"}, "Questions"), h("span", {class: "t-caption"}, countWord(qs.filter((q) => q.type !== "page_break").length, "question")));
  const addBtn = h("button", {type: "button", class: "btn sm primary", "aria-haspopup": "menu", "data-fkey": "sv:add", onclick: (e) => svAddMenu(e.currentTarget, qs)}, icon("plus"), "Add a question", icon("chev-down"));
  const add = h("div", {class: "sv-add"}, addBtn,
    h("button", {type: "button", class: "btn sm", "data-fkey": "sv:lib", onclick: () => openLibrary((ins) => {
      qs.splice(SV.sel + 1, 0, {instrument: ins.id}); SV.sel = Math.min(SV.sel + 1, qs.length - 1); svCommit(`Add ${ins.title}`);
    }, true)}, icon("book"), "From the library"));
  return [head, list, add];
}
function svMove(qs, i, delta) {
  const j = i + delta; if (j < 0 || j >= qs.length) return;
  [qs[i], qs[j]] = [qs[j], qs[i]]; SV.sel = j;
  svCommit("Move a question");
  setTimeout(() => SV.root?.querySelector(`[data-fkey="svq:${j}"]`)?.focus(), 10);
}
function svAddMenu(anchor, qs) {
  const groups = {};
  for (const [t, d] of Object.entries(QT())) (groups[d.group || "Other"] ||= []).push([t, d]);
  const items = [];
  for (const [g, arr] of Object.entries(groups)) {
    items.push({head: g});
    for (const [t, d] of arr) items.push({label: d.label, run: () => {
      qs.splice(SV.sel + 1, 0, defaultQuestion(t, qs)); SV.sel = Math.min(SV.sel + (qs.length > 1 ? 1 : 0), qs.length - 1); svCommit(`Add a question (${d.label})`);
    }});
  }
  ui.menu(anchor, items);
}

/* ---------------- small form controls (they carry data-fkey so focus survives a redraw) */
function svField(label, value, onChange, opts = {}) {
  const id = "sv-f-" + (++svSeq);
  const fkey = "sv:" + (opts.key || label);
  const inp = opts.area
    ? h("textarea", {class: "input" + (opts.mono ? " mono" : ""), id, rows: opts.rows || 2, dir: "auto", placeholder: opts.placeholder || "", "data-fkey": fkey,
      onchange: (e) => onChange(e.target.value)}, value ?? "")
    : h("input", {class: "input" + (opts.type === "number" ? " num" : ""), id, value: value ?? "", dir: opts.type ? null : "auto", type: opts.type || "text",
      placeholder: opts.placeholder || "", "data-fkey": fkey, onchange: (e) => onChange(e.target.value)});
  return h("div", {class: "field"}, label ? h("label", {for: id}, label) : null, inp, opts.help ? h("div", {class: "help"}, opts.help) : null);
}
function svCheck(label, value, onChange, help) {
  const sw = ui.switch(!!value, (v) => onChange(v), {label, caption: help});
  sw.switchButton.dataset.fkey = "sv:" + label;
  return h("div", {class: "field switch-field"}, sw);
}
function svSelect(label, value, choices, onChange, help, key) {
  const id = "sv-f-" + (++svSeq);
  const sel = h("select", {class: "input", id, "data-fkey": "sv:" + (key || label), "aria-label": label ? null : "Type of question", onchange: (e) => onChange(e.target.value)},
    choices.map(([v, l]) => { const o = h("option", {value: v}, l); if (String(value) === String(v)) o.selected = true; return o; }));
  if (!label) return sel;
  return h("div", {class: "field"}, h("label", {for: id}, label), sel, help ? h("div", {class: "help"}, help) : null);
}
const numOrBlank = (v) => (v === "" || v === null || v === undefined ? undefined : (isNaN(Number(v)) ? v : Number(v)));

/* options <-> text: "1 = Strongly disagree" keeps a code, plain lines are their own value */
function optionsToText(opts) {
  return (opts || []).map((o) => (typeof o === "object" ? (String(o.value) === String(o.label) ? o.label : `${o.value} = ${o.label}`) : String(o))).join("\n");
}
function textToOptions(t) {
  return t.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l) => {
    const m = l.match(/^(-?\d+(?:\.\d+)?|[A-Za-z_]\w*)\s*=\s*(.+)$/);
    if (m) return {value: isNaN(Number(m[1])) ? m[1] : Number(m[1]), label: m[2].trim()};
    return l;
  });
}
function optionLabels(q) {
  if (q.options) return q.options.map((o) => (typeof o === "object" ? o.label : String(o)));
  if (q.scale && SCALES()[q.scale]) return SCALES()[q.scale].options.map((o) => o.label);
  return [];
}

/* ---------------- the form of one question */
function renderQuestionForm(form, q, qs, comp) {
  const set = (k, v) => { if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) delete q[k]; else q[k] = v; svCommit("Edit a question"); };
  if (q.instrument) return renderInstrumentForm(form, q, qs, comp);
  const t = q.type, d = QT()[t] || {};
  const typeSel = t !== "page_break" ? svSelect("", t, Object.entries(QT()).filter(([k]) => k !== "page_break").map(([k, x]) => [k, x.label]), (v) => {
    const nq = defaultQuestion(v, qs); nq.id = q.id || nq.id; if (q.text && nq.text !== undefined) nq.text = q.text; if (q.required !== undefined && d.answer) nq.required = q.required;
    if (q.options && nq.options && ["single", "dropdown", "multiple", "rank", "constant_sum"].includes(v)) nq.options = q.options;
    qs[SV.sel] = nq; svCommit("Change the type of a question");
  }, "", "q:type") : null;
  form.push(h("div", {class: "sv-formhead"}, h("h3", {class: "t-title-m"}, d.label || t), typeSel));
  if (t === "page_break") { form.push(h("p", {class: "t-2"}, "Questions after this start on a new page. Participants press Next to continue, and can go back unless you turn that off.")); return; }
  if (d.answer) form.push(svField("Data name (column)", q.id || "", (v) => {
    v = v.trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(v)) { toast("Use letters, digits and _ only, starting with a letter."); renderSurveyEditor(); return; }
    q.id = v; svCommit("Rename a question");
  }, {help: `Saved as ${comp.id}.${q.id || "…"}`, key: "q:id"}));
  form.push(svField(t === "text_block" ? "Text (HTML allowed)" : "Question", q.text || "", (v) => set("text", v), {area: true, rows: t === "text_block" ? 6 : 3, key: "q:text",
    help: d.answer ? "Show an earlier answer with {{answer.<name>}}; trial values with {{column}}." : ""}));
  if (!d.answer) return;
  form.push(svCheck("Required", q.required, (v) => set("required", v || undefined), "Participants must answer it before going on."));
  const opt = h("section", {class: "sv-sub", "aria-label": "Answers"}, h("h4", {class: "sv-subhead t-overline"}, "Answers"));
  if (["single", "dropdown", "multiple", "likert", "matrix", "rank", "constant_sum"].includes(t)) {
    const scaleChoices = [["", "My own options"], ...Object.entries(SCALES()).map(([k, s]) => [k, s.title])];
    if (["likert", "matrix", "single"].includes(t)) put(opt, svSelect("Answer scale", q.scale && !q.options ? q.scale : "", scaleChoices, (v) => {
      if (v) { q.scale = v; delete q.options; } else { q.options = q.options || (q.scale ? clone(SCALES()[q.scale].options) : ["Option 1", "Option 2"]); delete q.scale; }
      svCommit("Change the answer scale");
    }, "A standard scale, or type your own options.", "q:scale"));
    if (!(q.scale && !q.options && ["likert", "matrix", "single"].includes(t)))
      put(opt, svField("Options (one per line)", optionsToText(q.options), (v) => set("options", textToOptions(v)),
        {area: true, rows: 5, key: "q:options", help: "Write “1 = Strongly disagree” to save a number code instead of the text."}));
    else put(opt, h("p", {class: "help"}, SCALES()[q.scale].options.map((o) => `${o.value} = ${o.label}`).join(" · ")));
  }
  if (["single", "multiple"].includes(t)) put(opt, svSelect("Layout", q.layout || "vertical", [["vertical", "One per line"], ["horizontal", "Side by side"], ...(t === "multiple" ? [["listbox", "A multi-select box"]] : [])], (v) => set("layout", v === "vertical" ? undefined : v)));
  if (["single", "dropdown", "multiple", "rank", "constant_sum", "matrix"].includes(t)) put(opt, svCheck(t === "matrix" ? "Shuffle the statements" : "Shuffle the options", q.randomize, (v) => set("randomize", v || undefined),
    "The order each participant saw is saved."));
  if (t === "single") put(opt, svSelect("“Other, please specify” box for", q.other_option || "", [["", "None"], ...optionLabels(q).map((l) => [l, l])], (v) => set("other_option", v || undefined)));
  if (t === "multiple") {
    put(opt, h("div", {class: "row2"}, svField("At least", q.min_choices ?? "", (v) => set("min_choices", numOrBlank(v)), {type: "number"}),
      svField("At most", q.max_choices ?? "", (v) => set("max_choices", numOrBlank(v)), {type: "number"})));
    put(opt, svSelect("Exclusive option (unticks the others)", (q.exclusive || [])[0] ?? "", [["", "None"], ...optionLabels(q).map((l) => [l, l])], (v) => set("exclusive", v ? [v] : undefined),
      "For example “None of these”."));
  }
  if (t === "matrix") put(opt, svField("Statements (one per line; end with (R) to reverse-score)", (q.items || []).map((it) => plain(it.text) + (it.reverse ? " (R)" : "")).join("\n"), (v) => {
    const ls = v.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    q.items = ls.map((l, k) => { const rev = /\(R\)\s*$/.test(l); const old = (q.items || [])[k];
      return {id: old?.id || `${q.id}_${k + 1}`, text: l.replace(/\s*\(R\)\s*$/, ""), ...(rev ? {reverse: true} : {})}; });
    svCommit("Change the statements");
  }, {area: true, rows: 6, key: "q:items", help: `Each statement is saved as ${q.id}_1, ${q.id}_2 …`}));
  if (t === "semantic") {
    put(opt, svField("Word pairs (one per line: left | right)", (q.items || []).map((it) => `${it.left} | ${it.right}`).join("\n"), (v) => {
      q.items = v.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((l, k) => { const [x, y] = l.split("|").map((s) => (s || "").trim()); const old = (q.items || [])[k];
        return {id: old?.id || `${q.id}_${k + 1}`, left: x, right: y || ""}; });
      svCommit("Change the word pairs");
    }, {area: true, rows: 5, key: "q:pairs"}));
    put(opt, svField("Points", q.points ?? 7, (v) => set("points", numOrBlank(v)), {type: "number"}));
  }
  if (t === "scale") put(opt, svField("Points", q.points ?? 7, (v) => set("points", numOrBlank(v)), {type: "number"}));
  if (["scale", "slider"].includes(t)) put(opt, h("div", {class: "row2"},
    svField("Left label", (q.labels || [])[0] || "", (v) => set("labels", [v, (q.labels || [])[1] || ""])),
    svField("Right label", (q.labels || [])[1] || "", (v) => set("labels", [(q.labels || [])[0] || "", v]))));
  if (["slider", "number"].includes(t)) put(opt, h("div", {class: "row2"},
    svField("Lowest", q.min ?? "", (v) => set("min", numOrBlank(v)), {type: "number"}), svField("Highest", q.max ?? "", (v) => set("max", numOrBlank(v)), {type: "number"})),
  svField("Step", q.step ?? "", (v) => set("step", numOrBlank(v)), {type: "number"}));
  if (t === "text") put(opt, svSelect("Check the answer", q.validate || "", [["", "Anything"], ["email", "An e-mail address"], ["number", "A number"], ["integer", "A whole number"]], (v) => set("validate", v || undefined)),
    svField("Pattern (regular expression, optional)", q.pattern || "", (v) => set("pattern", v || undefined), {help: "For example [A-Z]{2}[0-9]{4} for a participant code."}));
  if (["text", "essay"].includes(t)) put(opt, h("div", {class: "row2"},
    t === "essay" ? svField("Min characters", q.min_length ?? "", (v) => set("min_length", numOrBlank(v)), {type: "number"}) : null,
    svField("Max characters", q.max_length ?? "", (v) => set("max_length", numOrBlank(v)), {type: "number"})));
  if (t === "constant_sum") put(opt, svField("Total", q.total ?? 100, (v) => set("total", numOrBlank(v)), {type: "number"}));
  if (["single", "likert", "dropdown", "text", "number"].includes(t)) put(opt, svField("Correct answer (a knowledge or attention check, optional)", q.correct ?? "", (v) => set("correct", numOrBlank(v)),
    {help: "Add a score with the method “correct” to count right answers."}));
  renderExtraFields(opt, q, t, set, comp);
  form.push(opt, renderShowIf(q, qs), h("section", {class: "sv-sub"}, svField("Help text under the question", q.help || "", (v) => set("help", v || undefined))));
}

function renderShowIf(q, qs) {
  const box = h("section", {class: "sv-sub", "aria-label": "Display logic"}, h("h4", {class: "sv-subhead t-overline"}, "Show it"));
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
    const id = "sv-f-" + (++svSeq);
    box.append(h("div", {class: "field"}, h("label", {for: id}, "Advanced condition (JSON)"),
      h("input", {class: "input mono", id, value: JSON.stringify(cond), "data-fkey": "sv:showif:json", onchange: (e) => {
        try { q.show_if = JSON.parse(e.target.value); svCommit("Change when a question is shown"); } catch { toast("That isn't valid JSON."); }
      }})));
    return box;
  }
  const qsel = h("select", {class: "input", "aria-label": "Show it", "data-fkey": "sv:showif:q"}, h("option", {value: ""}, "Always"),
    earlier.map(([id, lab]) => { const o = h("option", {value: id}, "Only if " + lab); if (id === key) o.selected = true; return o; }));
  const osel = h("select", {class: "input", "aria-label": "Comparison", "data-fkey": "sv:showif:op"},
    [["=", "is"], ["!=", "is not"], [">", "is more than"], [">=", "is at least"], ["<", "is less than"], ["<=", "is at most"], ["contains", "includes"], ["answered", "was answered"]]
      .map(([v, l]) => { const o = h("option", {value: v}, l); if (v === op) o.selected = true; return o; }));
  const src = earlier.find(([id]) => id === key);
  const opts = src && src[2].options ? src[2].options.map((o) => (typeof o === "object" ? o : {value: o, label: o})) : src && src[2].scale ? SCALES()[src[2].scale].options : [];
  const vinp = opts.length
    ? h("select", {class: "input", "aria-label": "Value", "data-fkey": "sv:showif:v"}, opts.map((o) => { const e = h("option", {value: String(o.value)}, o.label); if (String(o.value) === String(val)) e.selected = true; return e; }))
    : h("input", {class: "input", "aria-label": "Value", "data-fkey": "sv:showif:v", value: op === "answered" ? "" : (val ?? ""), placeholder: "value"});
  const optsOf = (x) => (x && x.options ? x.options.map((o) => (typeof o === "object" ? o : {value: o, label: o})) : x && x.scale ? SCALES()[x.scale].options : []);
  const apply = () => {
    const k = qsel.value; if (!k) { delete q.show_if; return svCommit("Always show a question"); }
    if (k !== key) {       // another question: start from its first answer, so what is stored is what is shown
      const nq = (earlier.find(([id]) => id === k) || [])[2];
      const first = optsOf(nq)[0];
      const o2 = nq && nq.type === "multiple" ? "contains" : "=";
      const v2 = first ? first.value : "";
      q.show_if = first ? (o2 === "=" ? {[k]: v2} : {[k]: {[o2]: v2}}) : {[k]: {answered: true}};
      return svCommit("Change when a question is shown");
    }
    const o = osel.value; let v = vinp.value; v = numOrBlank(v) ?? v;
    const match = opts.find((x) => String(x.value) === String(vinp.value)); if (match) v = match.value;
    q.show_if = o === "answered" ? {[k]: {answered: true}} : o === "=" ? {[k]: v} : {[k]: {[o]: v}};
    svCommit("Change when a question is shown");
  };
  qsel.onchange = apply; osel.onchange = apply; vinp.onchange = apply;
  box.append(h("div", {class: "sv-cond"}, qsel, key ? osel : null, key && op !== "answered" ? vinp : null));
  if (!earlier.length) box.append(h("p", {class: "help"}, "A question can depend on the answers to questions before it."));
  return box;
}

function renderInstrumentForm(form, q, qs, comp) {
  const ins = libItem(q.instrument);
  if (!ins) { form.push(h("div", {class: "alert danger"}, icon("error"), h("div", {}, `Unknown questionnaire “${q.instrument}”.`))); return; }
  form.push(h("div", {class: "sv-ins"},
    h("div", {class: "sv-formhead"}, h("h3", {class: "t-title-m"}, ins.title)),
    h("p", {}, ins.description),
    h("p", {class: "sv-meta"}, `${countWord(ins.items, "item")} · about ${ins.minutes} min · scores: ${ins.scores.join(", ") || "none"}`),
    h("p", {class: "help"}, h("b", {}, "Cite: "), ins.citation), h("p", {class: "help"}, h("b", {}, "Licence: "), ins.licence),
    svSelect("Answers required", q.required === undefined ? "" : q.required ? "yes" : "no", [["", "As published (usually yes)"], ["yes", "All required"], ["no", "All optional"]],
      (v) => { if (v === "") delete q.required; else q.required = v === "yes"; svCommit("Change a questionnaire"); }, "", "ins:req"),
    h("div", {class: "sv-btns"}, h("button", {type: "button", class: "btn", onclick: async () => {
      const ok = await ui.confirm({title: `Copy the items of ${ins.title}?`, ok: "Copy the items",
        message: `The ${countWord(ins.items, "item")} of ${ins.title} are copied into this survey so you can edit them. Scoring is kept; edits to the wording mean it is no longer the validated version.`});
      if (!ok) return;
      let full;
      try { full = await api("/api/survey/instrument", {id: ins.id}); } catch (e) { toast(`Couldn't copy it: ${e.message}`, {tone: "danger"}); return; }
      qs.splice(SV.sel, 1, ...full.questions);
      comp.scores = {...(comp.scores || {}), ...(full.scores || {})};
      svCommit(`Copy the items of ${ins.title}`);
    }}, icon("duplicate"), "Customize (copy the items here)")),
    h("p", {class: "help"}, "Check the wording and licence against the original before collecting data, especially for translations or clinical and commercial use.")));
}

let _svCache = {key: null};
function svPreview() {
  clearTimeout(SV.timer);
  SV.timer = setTimeout(async () => {
    const c = surveyComp(); if (!c || !SV.frame) return;
    const spec = {questions: c.questions, title: c.title, intro: c.intro, scores: c.scores, progress_bar: c.progress_bar, allow_back: c.allow_back,
      language: c.language, direction: c.direction,
      submit_label: c.submit_label, next_label: c.next_label, back_label: c.back_label, labels: c.labels, css: c.css};
    const key = JSON.stringify(spec);
    if (SV.frame.dataset.key === key) return;
    try {
      const r = await api("/api/survey/render", {spec, path: S.path});
      if (!SV.problems) return;
      SV.problems.replaceChildren(...(r.problems || []).map((p) => h("div", {class: "alert danger"}, icon("error"), h("div", {}, cap(p)))));
      if (!(r.problems || []).length) { SV.frame.srcdoc = r.html; SV.frame.dataset.key = key; }
    } catch (e) { SV.problems?.replaceChildren(h("div", {class: "alert warning"}, icon("warning"), h("div", {}, e.message))); }
  }, 250);
}

/* the survey page shown in the screen preview (and its cache) */
function surveyPreviewHtml(c, done) {
  const spec = {questions: c.questions || [], title: c.title, intro: c.intro, scores: c.scores, language: c.language, direction: c.direction};
  const key = JSON.stringify(spec);
  if (_svCache.key === key) return _svCache.html;
  _svCache = {key, html: null};
  api("/api/survey/render", {spec, path: S.path}).then((r) => { if (_svCache.key === key) { _svCache.html = r.html || `<pre style="padding:20px;color:#c00">${(r.problems || []).join("\n")}</pre>`; done(); } }).catch(() => {});
  return null;
}

/* ================================================================== the questionnaire library (dialog .lg) */
function openLibrary(onPick, returnToEditor = false) {
  const filter = h("input", {class: "input", type: "search", placeholder: "Search: depression, Big Five, workload, consent…", "aria-label": "Search the questionnaires"});
  const grid = h("div", {class: "svlib-grid", role: "list"});
  let closeFn = () => {};
  const draw = () => {
    grid.replaceChildren();
    const f = filter.value.trim().toLowerCase();
    let cat = null, n = 0;
    for (const ins of LIB()) {
      if (f && !(ins.title + ins.description + ins.category + ins.id).toLowerCase().includes(f)) continue;
      if (ins.category !== cat) { cat = ins.category; grid.append(h("h3", {class: "svlib-cat t-overline"}, cat)); }
      n++;
      grid.append(h("article", {class: "card svlib-card", role: "listitem", "aria-label": ins.title},
        h("h4", {}, ins.title),
        h("span", {class: "t-caption"}, `${countWord(ins.items, "item")} · about ${ins.minutes} min${ins.scores.length ? " · scored" : ""}`),
        h("p", {}, ins.description), h("p", {class: "svlib-cite"}, ins.citation),
        h("button", {type: "button", class: "btn sm primary", "aria-label": `Add ${ins.title}`, onclick: () => { onPick(ins); closeFn(ins.id); }}, icon("plus"), "Add")));
    }
    if (!n) grid.append(h("p", {class: "svlib-none t-2"}, `Nothing called “${filter.value}”. Try another word.`));
  };
  filter.oninput = draw;
  const body = h("div", {class: "svlib"}, h("p", {class: "t-2"}, "Validated, free-to-use questionnaires with their scoring. Each adds its own data columns and scores."),
    h("div", {class: "input-wrap svlib-search"}, icon("search", "lead"), filter), grid);
  draw();
  void returnToEditor;   // the editor stays open underneath; closing the library returns to it
  return ui.dialog({title: "Questionnaire library", icon: "book", size: "lg", body, initialFocus: filter,
    buttons: [{label: "Close", value: null}], onOpen: (_dlg, close) => { closeFn = close; }});
}

/* ================================================================== fields of the specialised question types */
const lines = (v) => String(v || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
const cells = (l) => l.split("|").map((x) => x.trim());
const pathsToRows = (v) => lines(v).map((l) => l.split(/\s*(?:>|›)\s*/).filter(Boolean));
const rowsToText = (rows) => (rows || []).map((r) => r.join(" > ")).join("\n");
function treeToRows(tree, prefix = []) {
  if (!tree) return [];
  const keys = Array.isArray(tree) ? tree : Object.keys(tree);
  return keys.flatMap((k) => { const child = Array.isArray(tree) ? null : tree[k]; const p = [...prefix, String(k)];
    return child && (Array.isArray(child) ? child.length : Object.keys(child).length) ? treeToRows(child, p) : [p]; });
}
function rowsToTreeJS(rows) {
  const tree = {};
  for (const r of rows) { let node = tree; r.forEach((part, i) => { if (i === r.length - 1) { node[part] ||= {}; } else node = node[part] ||= {}; }); }
  const clean = (n) => { const ks = Object.keys(n); return ks.length ? Object.fromEntries(ks.map((k) => [k, clean(n[k])])) : []; };
  return clean(tree);
}

/* A picture for a question: a file next to the experiment (picked or uploaded with the asset picker) or a web address. */
function imageField(q, set, label = "Picture") {
  const id = "sv-f-" + (++svSeq);
  return h("div", {class: "field"}, h("label", {for: id}, label),
    h("div", {class: "sv-imgrow"},
      h("input", {class: "input", id, value: q.image || "", placeholder: "images/picture.png", "data-fkey": "sv:img:" + label, onchange: (e) => set("image", e.target.value.trim())}),
      h("button", {type: "button", class: "btn", onclick: () => openAssetPicker("image", (v) => set("image", v || ""), q.image || null)}, icon("image"), "Choose…")),
    h("div", {class: "help"}, "A file next to the experiment (e.g. images/shelf.png), or a web address."));
}

/* Hot-spot regions: drag on the picture to draw one, then name it. */
function regionEditor(q, set) {
  if (!q.image) return h("p", {class: "help"}, "Choose a picture first, then drag on it to draw the regions.");
  const box = h("div", {class: "sv-regions"});
  const src = /^(https?:|data:|\/)/.test(q.image) ? q.image : `/api/file?path=${encodeURIComponent((S.path || "").replace(/[^/]*$/, "") + q.image)}`;
  const img = h("img", {src, draggable: "false", alt: "The picture of this question: drag on it to add a region"});
  const stage = h("div", {class: "sv-regstage"}, img);
  const draw = () => {
    stage.querySelectorAll(".sv-reg").forEach((x) => x.remove());
    (q.regions || []).forEach((r) => stage.append(h("div", {class: "sv-reg", style: `left:${r.x}%;top:${r.y}%;width:${r.w}%;height:${r.h}%`}, r.label || r.id)));
  };
  let start = null, ghost = null;
  const pct = (e) => { const b = img.getBoundingClientRect(); return [Math.max(0, Math.min(100, (e.clientX - b.left) / b.width * 100)), Math.max(0, Math.min(100, (e.clientY - b.top) / b.height * 100))]; };
  stage.addEventListener("mousedown", (e) => { e.preventDefault(); start = pct(e); ghost = h("div", {class: "sv-reg ghost"}); stage.append(ghost); });
  stage.addEventListener("mousemove", (e) => { if (!start) return; const p = pct(e);
    ghost.style.cssText = `left:${Math.min(start[0], p[0])}%;top:${Math.min(start[1], p[1])}%;width:${Math.abs(p[0] - start[0])}%;height:${Math.abs(p[1] - start[1])}%`; });
  stage.addEventListener("mouseup", async (e) => {
    if (!start) return; const p = pct(e); ghost.remove();
    const r = {x: +Math.min(start[0], p[0]).toFixed(1), y: +Math.min(start[1], p[1]).toFixed(1), w: +Math.abs(p[0] - start[0]).toFixed(1), h: +Math.abs(p[1] - start[1]).toFixed(1)};
    start = null; if (r.w < 2 || r.h < 2) return;
    const label = await ui.prompt({title: "Name this region", label: "Name", value: `Region ${(q.regions || []).length + 1}`, ok: "Add region",
      placeholder: "e.g. Logo, Price", help: "Shown to you in the data; participants don't see it unless you show the names."});
    if (label === null || !label.trim()) return;
    const taken = new Set((q.regions || []).map((x) => x.id));
    q.regions = [...(q.regions || []), {id: uniqueId(label.toLowerCase().replace(/[^a-z0-9]+/g, "_") || "region", taken), label: label.trim(), ...r}];
    set("regions", q.regions);
  });
  img.onload = draw; draw();
  box.append(stage, h("p", {class: "help"}, "Drag on the picture to add a region."),
    ...(q.regions || []).map((r, i) => h("div", {class: "sv-regrow"},
      h("input", {class: "input", value: r.label || r.id, "aria-label": `Name of region ${i + 1}`, "data-fkey": `sv:reg:${i}`, onchange: (e) => { r.label = e.target.value; set("regions", q.regions); }}),
      h("small", {}, `${r.id}: ${r.x}, ${r.y}, ${r.w} × ${r.h} %`),
      h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Delete region ${r.label || r.id}`, title: "Delete", onclick: () => { q.regions.splice(i, 1); set("regions", q.regions); }}, icon("trash")))));
  return box;
}

function renderExtraFields(opt, q, t, set, comp) {
  const num = (label, key, help) => svField(label, q[key] ?? "", (v) => set(key, numOrBlank(v)), {type: "number", help});
  const check = (label, key, help) => svCheck(label, q[key], (v) => set(key, v || undefined), help);
  const itemLines = (label, help) => svField(label, (q.items || []).map((it) => (typeof it === "object" ? (it.text ?? it.label) : it)).join("\n"), (v) => {
    q.items = lines(v).map((l, k) => { const old = (q.items || [])[k]; return {id: (old && old.id) || `${q.id}_${k + 1}`, text: l}; }); set("items", q.items); }, {area: true, rows: 4, help});
  if (t === "text_block") put(opt, svField("Picture, video or sound (optional)", q.media || "", (v) => set("media", v.trim()), {placeholder: "images/intro.png or sounds/tone.mp3"}),
    svField("Caption", q.caption || "", (v) => set("caption", v)));
  if (t === "text") put(opt, check("Hide what is typed (password)", "secret"), num("Min characters", "min_length"));
  if (t === "date") put(opt, h("div", {class: "row2"}, svField("Earliest", q.min || "", (v) => set("min", v), {type: "date"}), svField("Latest", q.max || "", (v) => set("max", v), {type: "date"})));
  if (t === "number") put(opt, svField("Unit shown after the box", q.unit || "", (v) => set("unit", v)));
  if (t === "matrix") put(opt, check("Several answers per row (checkboxes)", "multi"),
    svSelect("Display", q.display || "table", [["table", "A table"], ["dropdown", "A drop-down per row"]], (v) => set("display", v === "table" ? undefined : v)));
  if (t === "scale" || t === "slider") put(opt, itemLines("Several statements, one per line (optional)", "Each gets its own row and data column."));
  if (t === "slider") put(opt, svField("Unit", q.unit || "", (v) => set("unit", v)));
  if (t === "rank") put(opt, svSelect("How participants rank", q.method || "drag", [["drag", "Drag and drop"], ["select", "A drop-down per option"], ["text", "Type the numbers"]], (v) => set("method", v === "drag" ? undefined : v)));
  if (t === "constant_sum") put(opt, svSelect("The amounts must", q.must_total || "exact", [["exact", "Add up exactly to the total"], ["at_most", "Not exceed the total"], ["at_least", "Reach at least the total"]], (v) => set("must_total", v === "exact" ? undefined : v)),
    svField("Unit (e.g. % or €)", q.unit || "", (v) => set("unit", v)));
  if (t === "graphic_slider") put(opt, svSelect("Style", q.style || "faces", [["faces", "Faces"], ["stars", "Stars"], ["hearts", "Hearts"]], (v) => set("style", v)), num("Points", "points"),
    h("div", {class: "row2"}, svField("Left label", (q.labels || [])[0] || "", (v) => set("labels", [v, (q.labels || [])[1] || ""])), svField("Right label", (q.labels || [])[1] || "", (v) => set("labels", [(q.labels || [])[0] || "", v]))));
  if (t === "form") put(opt, svField("Fields, one per line: name | label | type | required", (q.fields || []).map((f) => [f.id, f.label, f.type || "text", f.required ? "required" : ""].join(" | ").replace(/ \| $/, "")).join("\n"),
    (v) => set("fields", lines(v).map((l) => { const [id, label, type, req] = cells(l); return {id, label: label || id, ...(type && type !== "text" ? {type} : {}), ...(req ? {required: true} : {})}; })),
    {area: true, rows: 5, mono: true, help: "Types: text, email, number, tel, date, password, url."}));
  if (t === "side_by_side") put(opt, itemLines("Rows (one per line)"),
    svField("Columns, one per line: name | heading | type | options separated by ;", (q.columns || []).map((c) => [c.id, c.label, c.type || "single", c.scale ? "scale:" + c.scale : (c.options || []).map((o) => (typeof o === "object" ? o.label : o)).join("; ")].join(" | ")).join("\n"),
      (v) => set("columns", lines(v).map((l) => { const [id, label, type, op] = cells(l); const c = {id, label: label || id, type: type || "single"};
        if (op && op.startsWith("scale:")) c.scale = op.slice(6).trim(); else if (op) c.options = op.split(";").map((x) => x.trim()).filter(Boolean); return c; })),
      {area: true, rows: 4, mono: true, help: "Types: single, multiple, dropdown, text, number. Options can be scale:agree5."}));
  if (t === "group") put(opt, svField("Items to sort (one per line)", (q.items || []).map((x) => (typeof x === "object" ? x.label : x)).join("\n"), (v) => set("items", lines(v)), {area: true, rows: 4}),
    svField("Groups (one per line)", (q.groups || []).map((x) => (typeof x === "object" ? x.label : x)).join("\n"), (v) => set("groups", lines(v)), {area: true, rows: 3}),
    check("Rank the items inside each group", "rank_within"), check("Every item must be placed", "require_all"), check("Shuffle the items", "randomize"));
  if (t === "hot_spot") put(opt, imageField(q, set), svSelect("Clicking a region", q.mode || "select", [["select", "Selects it"], ["rate", "Likes it or dislikes it"]], (v) => set("mode", v)),
    num("At most this many selected", "max_select"), check("Show the region names", "show_labels"), regionEditor(q, set));
  if (t === "heat_map") put(opt, imageField(q, set), num("Clicks allowed", "max_clicks"));
  if (t === "location") put(opt, imageField(q, set, "Map picture (optional)"), check("Offer “use my current location”", "allow_geolocation", "Uses the device's location service; the browser asks for permission."),
    svField("Map edges for latitude and longitude: north, south, west, east (optional)", q.bounds ? [q.bounds.north, q.bounds.south, q.bounds.west, q.bounds.east].join(", ") : "",
      (v) => { const n = v.split(",").map((x) => Number(x.trim())); set("bounds", n.length === 4 && n.every((x) => !isNaN(x)) ? {north: n[0], south: n[1], west: n[2], east: n[3]} : undefined); },
      {help: "For a north-up map in a simple (equirectangular) projection."}));
  if (t === "drill_down") put(opt, svField("List names (comma separated)", (q.levels || []).join(", "), (v) => set("levels", v.split(",").map((x) => x.trim()).filter(Boolean))),
    svField("Choices, one path per line (France > Paris)", rowsToText(q.rows || treeToRows(q.tree)), (v) => { delete q.tree; set("rows", pathsToRows(v)); }, {area: true, rows: 6, help: "Or give a CSV file with one column per list below."}),
    svField("…or a CSV or Excel file", q.file || "", (v) => set("file", v.trim())));
  if (t === "highlight") put(opt, svField("Passage to highlight", q.passage || "", (v) => set("passage", v), {area: true, rows: 4}),
    svField("Categories, one per line: name | label | colour", (q.categories || []).map((c) => [c.id, c.label, c.color].join(" | ")).join("\n"),
      (v) => set("categories", lines(v).map((l) => { const [id, label, color] = cells(l); return {id, label: label || id, color: color || "#ffe58a"}; })), {area: true, rows: 3, help: "Empty: like and dislike."}));
  if (t === "file_upload") put(opt, svField("Allowed files", q.accept || "", (v) => set("accept", v), {placeholder: ".pdf,.png,image/*"}), num("Largest size (MB)", "max_mb"));
  if (t === "video_response") put(opt, check("Sound only (no camera)", "audio_only"), h("div", {class: "row2"}, num("Shortest (seconds)", "min_seconds"), num("Longest (seconds)", "max_seconds")),
    h("p", {class: "help"}, "The browser asks for permission to use the camera and microphone. The recording is saved as a file in the session folder."));
  if (t === "screen_capture") put(opt, h("p", {class: "help"}, "Participants capture their screen (the browser asks which screen or window), can black out private parts, and the image is saved in the session folder."));
  if (t === "captcha") put(opt, num("Characters", "length"), h("p", {class: "help"}, "An offline typed-code check. It slows down simple bots; it is not a substitute for an online service such as reCAPTCHA."));
  if (t === "timing") put(opt, h("div", {class: "row2"}, num("Shortest time before Next (s)", "min_seconds"), num("Go on by itself after (s)", "max_seconds")),
    check("Show the countdown on the Next button", "show_countdown"), h("p", {class: "help"}, "Invisible to participants. Records the first and last click, the time of sending and the clicks on this page."));
  if (t === "meta_info") put(opt, h("p", {class: "help"}, "Invisible. Saves the browser, operating system, screen and window size, pixel ratio, language, time zone and touch support."));
  if (t === "autocomplete") put(opt, svSelect("Suggestions from", q.list || "", [["", "My own options"], ["countries", "The countries of the world"], ["languages", "Languages"]], (v) => {
    if (v) { q.list = v; delete q.options; } else { delete q.list; q.options = q.options || ["Option 1"]; } svCommit("Change the suggestions"); }),
  !q.list ? svField("Options (one per line)", optionsToText(q.options), (v) => set("options", textToOptions(v)), {area: true, rows: 5}) : null,
  check("Accept answers that are not in the list", "free_text"));
  if (t === "tree_test") put(opt, svField("Task", q.task || "", (v) => set("task", v), {area: true}),
    svField("Menu, one path per line (Help > Returns)", rowsToText(q.rows || treeToRows(q.tree)), (v) => { q.tree = rowsToTreeJS(pathsToRows(v)); delete q.rows; set("tree", q.tree); }, {area: true, rows: 6}),
    svField("Correct destinations, one per line", Array.isArray(q.correct) ? q.correct.map((c) => (Array.isArray(c) ? c.join(" > ") : c)).join("\n") : (q.correct || ""),
      (v) => { const c = lines(v); set("correct", c.length > 1 ? c : c[0]); }, {area: true, rows: 2}), check("Branches can be chosen too (not only end points)", "select_any"));
  void comp;
}
