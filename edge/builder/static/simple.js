/* simple.js: the wizard, Try it and the Run page (SPEC W20, W10 "Try it", W11). Owner: P4b.
 *   wizard   - "Answer a few questions": a dialog with a stepper and a live preview of one trial (openWizard,
 *              createFromWizard); it creates <name>/<name>.yaml, opens it and starts a test run
 *   try it   - do the experiment yourself in the builder with the real engine and simulated hardware: tryIt(scope)
 *              starts at once (no chooser), the overlay #play has dark chrome and an end panel docked at its bottom
 *              (startPlay, stopPlay, playTrySound, finishPlay)
 *   run      - the Run workspace page: before the session (participant, session, devices, screen, preflight,
 *              unreviewed assistant code, today's sessions), the live monitor while it records, and the result
 *              after it (renderRunPage, runDialog, startRun; S.run and EDGE.emit("run"))
 */
"use strict";

/* ================================================================== the wizard (W20) */
const W = {step: 0, a: null, preview: null, dlg: null, name: "", nameTouched: false, paste: false, body: null, foot: null, thumb: null, est: null};
const WIZ_STEPS = ["What they see", "How they respond", "Timing", "Practice & feedback", "Blocks & texts", "Questionnaires & devices"];

function wizardDefaults() {
  return {name: "my_experiment", stimulus: {kind: "word", items: [
    {stimulus: "LEFT", correct: "f", condition: "left"}, {stimulus: "RIGHT", correct: "j", condition: "right"}]},
    response: {kind: "keys", keys: ["f", "j"]}, timing: {fixation: 0.5, stimulus_duration: "", response_deadline: 2, iti: 0.5},
    feedback: true, practice: {mode: "until", criterion: 0.8, max_rounds: 3}, blocks: {count: 2, repeats: 2, order: "random"},
    instructions: "", thanks: "", devices: [], questionnaires: []};
}

function openWizard() {
  W.step = 0; W.a = wizardDefaults(); W.name = ""; W.nameTouched = false; W.paste = false;
  const stepper = h("ol", {class: "wiz-stepper", "aria-label": "Steps"});
  const page = h("div", {class: "wiz-page", role: "region", "aria-live": "polite"});
  const thumb = h("canvas", {class: "wiz-thumb", width: 480, height: 270, role: "img", "aria-label": "Preview of one trial"});
  const est = h("p", {class: "wiz-est t-small", role: "status"}, "Working it out…");
  const preview = h("aside", {class: "wiz-preview", "aria-label": "Preview"}, h("h3", {class: "t-overline"}, "Preview of one trial"), h("div", {class: "wiz-thumbwrap"}, thumb), est);
  const nameIn = h("input", {class: "input", id: "wiz-name", value: "", placeholder: "e.g. word task", autocomplete: "off", spellcheck: "false",
    oninput: (e) => { W.name = e.target.value; W.nameTouched = true; wizNameHint(); }});
  const nameHint = h("span", {class: "t-caption wiz-namehint"});
  const back = h("button", {type: "button", class: "btn", onclick: () => { if (W.step > 0) { W.step--; renderWizard(); } }}, "Back");
  const next = h("button", {type: "button", class: "btn primary", onclick: () => { if (W.step < WIZ_STEPS.length - 1) { W.step++; renderWizard(); } else createFromWizard(); }}, "Next");
  const createNow = h("button", {type: "button", class: "btn", title: "Create it now with the other answers as they are", onclick: () => createFromWizard()}, "Create and test");
  const foot = h("div", {class: "wiz-foot"}, h("label", {for: "wiz-name", class: "wiz-namelbl"}, "Name"), nameIn, nameHint, h("span", {class: "grow"}), back, createNow, next);
  const root = h("div", {class: "wiz"}, h("div", {class: "wiz-main"}, stepper, page, preview), foot);
  Object.assign(W, {stepperEl: stepper, pageEl: page, thumb, est, nameIn, nameHint, backBtn: back, nextBtn: next, createBtn: createNow, preview});
  const p = ui.dialog({title: "New experiment: answer a few questions", icon: "checklist", size: "lg", body: root, buttons: [],
    initialFocus: "#wiz-name", onOpen: (dlg, close) => { W.dlg = dlg; W.close = close; dlg.classList.add("wizard-dialog"); }});
  renderWizard();
  p.then(() => { W.dlg = null; W.close = null; });
}
function wizSlug() { return ui.slug(W.name || W.a?.name || "") || "my_experiment"; }
async function wizNameHint() {
  const slug = wizSlug();
  W.nameHint.textContent = `saved as ${slug}/${slug}.yaml`;
}

function renderWizard() {
  if (!W.dlg) return;
  const a = W.a;
  // the stepper
  W.stepperEl.replaceChildren(...WIZ_STEPS.map((t, i) => h("li", {}, h("button", {type: "button", class: "wiz-st" + (i === W.step ? " on" : i < W.step ? " done" : ""),
    "aria-current": i === W.step ? "step" : null, onclick: () => { W.step = i; renderWizard(); }},
  h("span", {class: "n", "aria-hidden": "true"}, i < W.step ? icon("check") : String(i + 1)), h("span", {class: "t"}, t, i < W.step ? h("span", {class: "sr-only"}, " (done)") : null)))));
  const page = W.pageEl;
  const els = [];
  const radio = (group, value, label, sub, on, ic) => h("button", {type: "button", role: "radio", class: "wiz-choice" + (ic ? "" : " dot"), "aria-checked": on ? "true" : "false", "data-group": group,
    onclick: () => { value(); renderWizard(); }}, ic ? h("span", {class: "wc-ic"}, icon(ic, "m")) : null, h("span", {class: "wc-t"}, h("b", {}, label), sub ? h("small", {}, sub) : null));
  const group = (label, ...kids) => { const g = h("div", {class: "wiz-row", role: "radiogroup", "aria-label": label}, ...kids); wizRadioCards(g); return g; };
  let fid = 0;
  const num = (label, get, set, help, unit = "s") => {
    const id = "wiz-f-" + (++fid);
    const inp = h("input", {class: "input num", id, inputmode: "decimal", value: get() ?? "", placeholder: unit === "s" ? "none" : "",
      oninput: (e) => { const v = e.target.value.trim().replace(",", "."); set(v === "" ? "" : +v); wizPreview(); }});
    return h("div", {class: "field"}, h("label", {for: id}, label), unit ? h("div", {class: "input-wrap wiz-num"}, inp, h("span", {class: "suffix"}, unit)) : h("div", {class: "wiz-num"}, inp),
      help ? h("div", {class: "help"}, help) : null);
  };
  const text = (label, get, set, ph, rows) => {
    const id = "wiz-f-" + (++fid);
    return h("div", {class: "field"}, h("label", {for: id}, label),
      rows ? h("textarea", {class: "input", id, rows, dir: "auto", placeholder: ph || "", oninput: (e) => { set(e.target.value); wizPreview(); }}, get() || "")
        : h("input", {class: "input", id, dir: "auto", value: get() ?? "", placeholder: ph || "", oninput: (e) => { set(e.target.value); wizPreview(); }}));
  };
  const check = (label, sub, on, set, title) => {
    const id = "wiz-c-" + (++fid);
    const cb = h("input", {type: "checkbox", id, onchange: (e) => { set(e.target.checked); wizPreview(); }}); cb.checked = !!on;
    return h("label", {class: "wiz-check", for: id, title: title || null}, cb, h("span", {}, h("b", {}, label), sub ? h("small", {}, sub) : null));
  };
  const title = h("h3", {class: "t-title-s wiz-title"}, ["What do participants see?", "How do participants respond?", "Timing", "Practice and feedback", "Blocks and texts", "Questionnaires and devices"][W.step]);
  els.push(title);
  if (W.step === 0) {
    els.push(group("What participants see",
      radio("kind", () => { a.stimulus.kind = "word"; }, "Words", "Text on the screen", a.stimulus.kind === "word", "text"),
      radio("kind", () => { a.stimulus.kind = "picture"; }, "Pictures", "Image files", a.stimulus.kind === "picture", "image"),
      radio("kind", () => { a.stimulus.kind = "sound"; }, "Sounds", "Files, or a tone in Hz", a.stimulus.kind === "sound", "sound"),
      radio("kind", () => { a.stimulus.kind = "shape"; }, "Shapes", "Circle, rectangle, cross…", a.stimulus.kind === "shape", "shape")));
    const keys = a.response.kind === "keys";
    els.push(h("p", {class: "t-small t-2"}, keys ? "One row per stimulus. The correct key is the right answer (leave it empty when there is none). The condition is a label for your analysis, e.g. congruent or incongruent."
      : "One row per stimulus. The condition is a label for your analysis."));
    const first = a.stimulus.kind === "picture" ? "Picture file (in images/)" : a.stimulus.kind === "sound" ? "Sound file or Hz" : a.stimulus.kind === "shape" ? "Shape" : "Word";
    const tbl = h("table", {class: "grid wiz-items"}, h("thead", {}, h("tr", {}, h("th", {}, first), keys ? h("th", {class: "k"}, "Correct key") : null, h("th", {}, "Condition"), h("th", {class: "x"}, h("span", {class: "sr-only"}, "Remove")))));
    const body = h("tbody");
    a.stimulus.items.forEach((it, i) => body.append(h("tr", {},
      h("td", {}, h("input", {class: "input", value: it.stimulus ?? "", "aria-label": `${first}, row ${i + 1}`, oninput: (e) => { it.stimulus = e.target.value; wizPreview(); }})),
      keys ? h("td", {class: "k"}, h("input", {class: "input mono", value: it.correct ?? "", "aria-label": `Correct key, row ${i + 1}`, oninput: (e) => { it.correct = e.target.value; wizPreview(); }})) : null,
      h("td", {}, h("input", {class: "input", value: it.condition ?? "", "aria-label": `Condition, row ${i + 1}`, oninput: (e) => { it.condition = e.target.value; wizPreview(); }})),
      h("td", {class: "x"}, h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Remove row ${i + 1}`, title: "Remove", onclick: () => { a.stimulus.items.splice(i, 1); renderWizard(); }}, icon("trash"))))));
    tbl.append(body);
    els.push(h("div", {class: "table-wrap wiz-tablewrap"}, tbl));
    els.push(h("div", {class: "wiz-btns"},
      h("button", {type: "button", class: "btn sm", onclick: () => { a.stimulus.items.push({stimulus: "", correct: "", condition: ""}); renderWizard();
        setTimeout(() => W.pageEl.querySelector("tbody tr:last-child input")?.focus(), 0); }}, icon("plus"), "Row"),
      h("button", {type: "button", class: "btn sm ghost", "aria-expanded": W.paste ? "true" : "false", onclick: () => { W.paste = !W.paste; renderWizard(); }}, icon("table"), "Paste rows from a spreadsheet")));
    if (W.paste) {
      const ta = h("textarea", {class: "input mono", rows: 5, id: "wiz-paste", placeholder: "RED\tr\tcongruent\nGREEN\tg\tincongruent"});
      els.push(h("div", {class: "field wiz-paste"}, h("label", {for: "wiz-paste"}, "Paste rows: stimulus, correct key, condition (tab or comma separated), one per line"), ta,
        h("div", {class: "wiz-btns"}, h("button", {type: "button", class: "btn sm primary", onclick: () => {
          const rows = ta.value.split(/\r?\n/).filter((l) => l.trim()).map((l) => { const c = l.split(/\t|,/).map((x) => x.trim()); return {stimulus: c[0], correct: c[1] || "", condition: c[2] || ""}; });
          if (!rows.length) { ta.focus(); return; }
          a.stimulus.items = rows; W.paste = false; renderWizard(); toast(`Used ${countWord(rows.length, "row")}.`);
        }}, "Use these rows"), h("button", {type: "button", class: "btn sm ghost", onclick: () => { W.paste = false; renderWizard(); }}, "Cancel"))));
      setTimeout(() => $("#wiz-paste")?.focus(), 0);
    }
    if (a.stimulus.kind === "picture") els.push(h("p", {class: "t-caption"}, "After creating, put the picture files in the images/ folder next to the experiment. EDGE makes placeholders until then."));
  } else if (W.step === 1) {
    const r = a.response;
    els.push(group("How participants respond",
      radio("resp", () => { r.kind = "keys"; }, "Press a key", "e.g. F for left, J for right", r.kind === "keys", "keyboard"),
      radio("resp", () => { r.kind = "mouse"; }, "Click", "On the stimulus", r.kind === "mouse", "mouse"),
      radio("resp", () => { r.kind = "rating"; }, "Rate on a scale", "e.g. 1 to 7", r.kind === "rating", "rating"),
      radio("resp", () => { r.kind = "none"; }, "No response", "Just watch or listen", r.kind === "none", "eye")));
    if (r.kind === "keys") {
      const chips = typeof inspKeyChips === "function" ? inspKeyChips(r.keys || [], (v) => { r.keys = v; renderWizard(); wizPreview(); }, "wiz-keys")
        : h("input", {class: "input", id: "wiz-keys", value: (r.keys || []).join(" "), oninput: (e) => { r.keys = e.target.value.split(/[\s,]+/).filter(Boolean); wizPreview(); }});
      els.push(h("div", {class: "field"}, h("label", {for: "wiz-keys"}, "Keys participants may press"), chips,
        h("div", {class: "help"}, "Click the box and press the keys. Key names: letters, digits, space, left, right, up, down, return.")));
    }
    if (r.kind === "rating") els.push(h("div", {class: "row2"}, num("Points on the scale", () => r.ticks ?? 7, (v) => r.ticks = v || 7, "", ""),
      text("Labels at the ends (separated by a comma)", () => (r.labels || ["not at all", "very much"]).join(", "), (v) => r.labels = v.split(",").map((x) => x.trim()).filter(Boolean))));
  } else if (W.step === 2) {
    const t = a.timing;
    els.push(h("div", {class: "row2"},
      num("Fixation cross before each stimulus", () => t.fixation, (v) => t.fixation = v === "" ? 0 : v, "0: none"),
      num("Show the stimulus for", () => t.stimulus_duration, (v) => t.stimulus_duration = v, "Empty: until they respond")),
    h("div", {class: "row2"},
      a.response.kind !== "none" ? num("Time limit to respond", () => t.response_deadline, (v) => t.response_deadline = v, "Empty: wait as long as it takes. With a limit, a missing answer counts as too slow.") : h("span"),
      num("Blank pause between trials", () => t.iti, (v) => t.iti = v === "" ? 0 : v)));
  } else if (W.step === 3) {
    const pr = a.practice, keys = a.response.kind === "keys";
    els.push(check("Show “Correct!” or “Wrong” after each trial in the main part too", keys ? "Practice always shows feedback." : "Feedback needs correct keys (step 1).", a.feedback, (v) => { a.feedback = v; }));
    els.push(h("h4", {class: "wiz-sub"}, "Practice"));
    els.push(group("Practice",
      radio("prac", () => { pr.mode = "none"; }, "No practice", "", pr.mode === "none"),
      radio("prac", () => { pr.mode = "once"; }, "Practice once", "Every stimulus once", pr.mode === "once"),
      radio("prac", () => { pr.mode = "until"; }, "Practice until good enough", "Repeat until accurate", pr.mode === "until")));
    if (pr.mode === "until") {
      els.push(h("div", {class: "row2"}, num("Proportion correct needed (0–1)", () => pr.criterion, (v) => pr.criterion = v, "", ""), num("At most this many rounds", () => pr.max_rounds, (v) => pr.max_rounds = v, "", "")));
      if (!keys) els.push(h("div", {class: "alert warning"}, icon("warning"), h("div", {}, "Needs correct keys: without them practice runs once.")));
    }
  } else if (W.step === 4) {
    const b = a.blocks;
    const oid = "wiz-order";
    els.push(h("div", {class: "row2"},
      num("Number of blocks", () => b.count, (v) => b.count = Math.max(1, Math.round(+v || 1)), "", ""),
      num("Each stimulus appears, per block", () => b.repeats, (v) => b.repeats = Math.max(1, Math.round(+v || 1)), "", "times")),
    h("div", {class: "field"}, h("label", {for: oid}, "Order within a block"), h("select", {class: "input", id: oid, onchange: (e) => { b.order = e.target.value; wizPreview(); }},
      [["random", "Shuffled each time"], ["sequential", "As listed"], ["fullrandom", "Shuffled across repeats"]].map(([v, l]) => { const o = h("option", {value: v}, l); if (b.order === v) o.selected = true; return o; }))),
    b.count > 1 ? text("Text on the break screen between blocks", () => b.break_text, (v) => b.break_text = v, "Take a short break. Press SPACE when ready.") : null,
    text("Instructions (empty: written for you from your answers)", () => a.instructions, (v) => a.instructions = v, "", 3),
    text("Goodbye text", () => a.thanks, (v) => a.thanks = v, "Thank you! You're done."));
  } else if (W.step === 5) {
    const opts = [["sim_eyetracker", "Eye tracker", "Simulated for now; switch to Tobii or Gazepoint in the device settings"],
      ["sim_eeg", "EEG", "Simulated for now; switch to g.tec or an LSL stream"], ["lsl_markers", "LSL markers", "Send every event to LabRecorder"],
      ["ttl_loopback", "Trigger box (TTL)", "Simulated for now; switch to serial TTL or a parallel port"]];
    els.push(h("p", {class: "t-small t-2"}, "Consent and demographics come before the task, the others after it. Each is a validated, scored questionnaire; change them later in the survey editor."));
    const qbox = h("div", {class: "wiz-qs"});
    let cat = null;
    for (const ins of S.schema.survey.library) {
      if (ins.category !== cat) { cat = ins.category; qbox.append(h("div", {class: "wiz-qcat t-overline"}, cat)); }
      qbox.append(check(ins.title, `${countWord(ins.items, "item")} · about ${ins.minutes} min`, a.questionnaires.includes(ins.id),
        (v) => { a.questionnaires = v ? [...a.questionnaires, ins.id] : a.questionnaires.filter((x) => x !== ins.id); }, ins.description));
    }
    els.push(qbox, h("h4", {class: "wiz-sub"}, "Devices"), h("p", {class: "t-small t-2"}, "Optional. Everything works without hardware; devices can be added or changed later."));
    const dbox = h("div", {class: "wiz-devs"});
    for (const [type, label, sub] of opts) dbox.append(check(label, sub, a.devices.includes(type), (v) => { a.devices = v ? [...a.devices, type] : a.devices.filter((x) => x !== type); }));
    els.push(dbox);
  }
  page.replaceChildren(...els.filter(Boolean));
  page.scrollTop = 0;
  const last = W.step === WIZ_STEPS.length - 1;
  W.backBtn.disabled = W.step === 0;
  W.nextBtn.replaceChildren(); put(W.nextBtn, last ? icon("test") : null, last ? "Create and test" : "Next", last ? null : icon("chev-right"));
  W.nextBtn.querySelectorAll(".ic").forEach((x) => x.classList.toggle("after", !last));
  W.createBtn.hidden = last;
  if (!W.nameTouched) { W.nameIn.placeholder = "e.g. word task"; }
  wizNameHint();
  wizPreview();
}
/* Radio cards: one tab stop, arrow keys move (APG radio group). */
function wizRadioCards(g) {
  const radios = () => [...g.querySelectorAll('[role="radio"]')];
  const on = radios().find((b) => b.getAttribute("aria-checked") === "true") || radios()[0];
  radios().forEach((b) => { b.tabIndex = b === on ? 0 : -1; });
  g.addEventListener("keydown", (e) => {
    const list = radios(), i = list.indexOf(document.activeElement);
    if (i < 0 || !["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const j = (i + (["ArrowRight", "ArrowDown"].includes(e.key) ? 1 : -1) + list.length) % list.length;
    const grp = list[j].dataset.group;
    list[j].click();
    setTimeout(() => W.pageEl?.querySelector(`[role=radio][data-group="${grp}"][aria-checked=true]`)?.focus(), 0);
  });
}

function wizardAnswers() {
  const a = clone(W.a);
  a.name = wizSlug();
  for (const k of ["stimulus_duration", "response_deadline"]) if (a.timing[k] === "") a.timing[k] = "none";
  if (a.response.kind !== "keys") a.stimulus.items.forEach((it) => delete it.correct);
  return a;
}
let _wizT = null;
function wizPreview() {
  clearTimeout(_wizT);
  _wizT = setTimeout(async () => {
    if (!W.dlg) return;
    try {
      const r = await api("/api/wizard", {answers: wizardAnswers()});
      if (!W.dlg) return;
      if (!r.ok) { W.est.className = "wiz-est t-small bad"; W.est.replaceChildren(icon("warning"), " ", r.error); return; }
      W.est.className = "wiz-est t-small";
      const e = r.estimate || {};
      W.est.replaceChildren(`This makes ${EDGE.fmt.estimate({trials: e.trials, seconds: e.seconds}).replace(" · ", ", ")}.`);
      W.doc = r.experiment;
      const rid = wizTrialScreen(r.experiment);
      if (typeof drawThumbnail === "function" && rid) {
        try { drawThumbnail(r.experiment, W.thumb, {rid, path: null}); } catch { /* the preview is a nicety */ }
        W.thumb.setAttribute("aria-label", `Preview of one trial: screen “${rid}”`);
      }
    } catch (e) { W.est.textContent = e.message; }
  }, 250);
}
/* The trial screen of the generated experiment: "trial", or the first screen inside a trial list. */
function wizTrialScreen(doc) {
  if (doc.routines?.trial) return "trial";
  let found = null;
  const walk = (nodes, inLoop) => (nodes || []).forEach((n) => {
    if (found) return;
    const r = typeof n === "string" ? n : n?.routine;
    if (r && inLoop) { found = r; return; }
    if (n && typeof n === "object") { walk(n.children, inLoop || n.loop !== undefined); walk(n.then, inLoop); walk(n.else, inLoop); Object.values(n.states || {}).forEach((s) => walk(s.run, inLoop)); }
  });
  walk(doc.flow, false);
  return found || Object.keys(doc.routines || {})[0] || null;
}
function describeWizardFlow(doc) {
  const names = [];
  walkFlowOf(doc.flow, (n) => { const r = routineOfNode(n); if (typeof r === "string" && !names.includes(r)) names.push(r); });
  return "screens " + names.join(" → ") + ".";
}
function walkFlowOf(nodes, fn) {
  for (const n of nodes || []) { fn(n); if (n && typeof n === "object") { walkFlowOf(n.children, fn); walkFlowOf(n.then, fn); walkFlowOf(n.else, fn);
    for (const st of Object.values(n.states || {})) walkFlowOf(st.run, fn); } }
}

async function createFromWizard() {
  const a = wizardAnswers();
  const slug = a.name;
  let name = slug, n = 2;
  let files = [];
  try { files = (await api("/api/files")).files.map((f) => f.path); } catch { /* the server says so below */ }
  while (files.includes(`${name}/${name}.yaml`)) name = `${slug}_${n++}`;
  a.name = name;
  if (typeof confirmLeaveDirty === "function" && !(await confirmLeaveDirty())) return;
  const btn = W.nextBtn;
  if (btn) { btn.setAttribute("aria-busy", "true"); btn.disabled = true; }
  let r;
  try { r = await api("/api/wizard", {answers: a, save_as: `${name}/${name}.yaml`}); }
  catch (e) { if (btn) { btn.removeAttribute("aria-busy"); btn.disabled = false; } return toast(e.message, {tone: "danger", ms: 8000}); }
  if (!r.ok) { if (btn) { btn.removeAttribute("aria-busy"); btn.disabled = false; } return toast(r.error, {tone: "danger", ms: 8000}); }
  W.close?.(null);
  clearDraft();
  await openFile(r.path, {silent: true});
  S.view = "story";
  EDGE.go("build");
  toast(`Created ${r.path}: ${EDGE.fmt.estimate({trials: r.estimate?.trials, seconds: r.estimate?.seconds})}. Checking it with a virtual participant…`);
  await dryRun();
  if (a.stimulus.kind === "picture") toast(`Put your pictures in ${name}/images/ (the names in the trial list must match).`, {ms: 10000});
}

/* ================================================================== Try it (W10) */
const P = {on: false, sound: 0, scale: 1, size: [1280, 720], audio: null, imgs: {}, keysDown: new Set(), back: null, last: null, opener: null, routine: null};
const KEYMAP = {" ": "space", "Enter": "return", "ArrowLeft": "left", "ArrowRight": "right", "ArrowUp": "up", "ArrowDown": "down",
  "Escape": "escape", "Backspace": "backspace", "Tab": "tab", "Shift": "lshift", "Control": "lctrl", "Alt": "lalt"};

/* Try it at once: the whole experiment, or only the open screen (5 trials). The Try ▾ menu and the Test card say which. */
function tryIt(scope = "all") {
  if (scope === "screen" && S.routine && S.exp.routines[S.routine]) return startPlay(S.routine);
  return startPlay(null);
}

async function startPlay(routine) {
  if (P.on) return;
  let r, err = null;
  try { r = await api("/api/play/start", {experiment: S.exp, path: S.path, routine, max_trials: 5}); }
  catch (e) { err = e.message; }
  if (err !== null || !r?.ok) {
    // must-fix problems: show them where they are (the Problems popover), not as a raw message
    S.strict = true;
    try { if (typeof validate === "function") await validate(); } catch { /* the message below says it */ }
    const n = typeof problemGroups === "function" ? problemGroups().error.length : (S.issues || []).filter((i) => i.level === "error").length;
    if (n && typeof openProblems === "function") openProblems({reason: `Can't start yet: ${countWord(n, "thing")} to fix.`});
    else toast(`Try it couldn't start: ${err || r?.error || "the experiment has a problem"}`, {tone: "danger", ms: 8000});
    return;
  }
  P.on = true; P.sound = 0; P.size = r.size; P.routine = routine; P.last = null;
  P.opener = document.activeElement;
  P.back = {ws: S.ws, view: S.view, routine: S.routine, sel: S.sel ? clone(S.sel) : null};
  const el = $("#play");
  el.replaceChildren();
  el.setAttribute("role", "dialog"); el.setAttribute("aria-modal", "true"); el.setAttribute("aria-label", "Try it");
  el.classList.remove("hidden", "ended");
  const cv = h("canvas", {id: "play-canvas", tabindex: "0", role: "img", "aria-label": "The experiment, as a participant sees it"});
  const frame = h("iframe", {id: "play-page", class: "hidden", title: "Web page of the experiment"});
  let est = null;
  try { est = !routine && typeof storyEstimate === "function" ? storyEstimate(() => {}) : null; } catch { est = null; }
  const scope = routine ? ` · only “${routine}”, 5 trials` : est && est.trials ? ` · ${countWord(est.trials, "trial")}` : "";
  const stop = h("button", {type: "button", class: "btn sm play-stop", onclick: stopPlay}, icon("stop"), "Stop");
  put(el, h("div", {class: "play-bar"},
    h("span", {class: "play-title"}, h("b", {}, `Trying “${S.exp.name || docName()}”`), h("span", {class: "play-scope"}, scope)),
    h("span", {class: "play-hint"}, "Respond like a participant · Esc stops"), h("span", {class: "grow"}), stop),
  h("div", {class: "play-stage"}, cv, frame),
  h("div", {class: "play-end", id: "play-end", hidden: ""}));
  const fit = () => {
    const stage = el.querySelector(".play-stage"); const [w, hh] = P.size;
    const k = Math.min(stage.clientWidth / w, stage.clientHeight / hh);
    cv.width = Math.max(1, Math.round(w * k)); cv.height = Math.max(1, Math.round(hh * k)); P.scale = k;
    frame.style.width = cv.width + "px"; frame.style.height = cv.height + "px";
    if (P.last) drawPlayFrame(cv, P.last);
  };
  fit(); window.addEventListener("resize", fit); P.fit = fit;
  cv.addEventListener("mousedown", (e) => playMouse(e, cv, true));
  cv.addEventListener("mouseup", (e) => playMouse(e, cv, false));
  cv.addEventListener("mousemove", (e) => { if (!P._mv || Date.now() - P._mv > 40) { P._mv = Date.now(); playMouse(e, cv, null); } });
  document.addEventListener("keydown", playKey, true);
  document.addEventListener("keyup", playKey, true);
  cv.focus({preventScroll: true});
  ui.announce(`Trying ${S.exp.name || docName()}. Respond like a participant. Escape stops.`);
  playLoop(cv, frame);
}

function playMouse(e, cv, down) {
  if (!P.on) return;
  const r = cv.getBoundingClientRect();
  const x = (e.clientX - r.left - cv.width / 2) / P.scale, y = -(e.clientY - r.top - cv.height / 2) / P.scale;
  const name = down === null ? "move" : ["left", "middle", "right"][e.button] || "left";
  api("/api/play/input", {kind: "mouse", name, down: down !== false, pos: [x, y]}).catch(() => {});
}
function playKey(e) {
  if (!P.on || e.target?.closest?.("#play-page")) return;
  if (e.target?.closest?.(".play-bar") && (e.key === "Enter" || e.key === " " || e.key === "Tab")) return;   // the Stop button stays usable
  e.preventDefault(); e.stopPropagation();
  const name = KEYMAP[e.key] || e.key.toLowerCase();
  const down = e.type === "keydown";
  if (down && e.repeat) return;
  if (name === "escape" && down) { stopPlay(); return; }
  api("/api/play/input", {kind: "key", name, down}).catch(() => {});
}

async function playLoop(cv, frame) {
  while (P.on) {
    let f;
    try { f = await api(`/api/play/frame?sound=${P.sound}`); } catch (e) { await new Promise((r) => setTimeout(r, 200)); continue; }
    if (!P.on) return;
    if (f.drawn) { P.last = f; drawPlayFrame(cv, f); }
    for (const snd of f.sounds || []) { P.sound = Math.max(P.sound, snd.id); playTrySound(snd); }
    if (f.page) { if (frame.dataset.src !== f.page) { frame.src = f.page; frame.dataset.src = f.page; } frame.classList.remove("hidden"); }
    else if (!frame.classList.contains("hidden")) { frame.classList.add("hidden"); frame.dataset.src = ""; cv.focus?.(); }
    if (!f.running) { finishPlay(f); return; }
    await new Promise((r) => requestAnimationFrame(r));
  }
}

function cssColor(c, fallback) {
  if (c === null || c === undefined) return fallback;
  if (Array.isArray(c)) {
    let v = c.map(Number);
    if (v.some((x) => x < 0)) v = v.map((x) => (x + 1) * 127.5);
    else if (v.every((x) => x <= 1) && c.some((x) => String(x).includes("."))) v = v.map((x) => x * 255);
    return `rgba(${v[0] | 0},${v[1] | 0},${v[2] | 0},${v.length > 3 ? v[3] / 255 : 1})`;
  }
  return String(c) === "transparent" ? "rgba(0,0,0,0)" : String(c);
}

function drawPlayFrame(cv, f) {
  const ctx = cv.getContext("2d"), k = P.scale;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = cssColor(f.background, "#000"); ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.translate(cv.width / 2, cv.height / 2); ctx.scale(k, -k);
  for (const [kind, p] of f.drawn || []) {
    const [x, y] = p.pos || [0, 0];
    ctx.save(); ctx.translate(x, y); ctx.rotate(-(p.ori || 0) * Math.PI / 180);
    ctx.globalAlpha = Math.max(0, Math.min(1, p.opacity ?? 1));
    if (kind === "text") {
      ctx.scale(1, -1); ctx.fillStyle = cssColor(p.color, "#fff");
      const hgt = p.height || 40; ctx.font = `${p.italic ? "italic " : ""}${p.bold ? "bold " : ""}${hgt}px ${p.font || "sans-serif"}`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.direction = p.direction === "rtl" || (p.direction !== "ltr" && /[֐-׿יִ-ﭏ]/.test(String(p.text ?? ""))) ? "rtl" : "ltr";
      const lines = wrapLines(ctx, String(p.text ?? ""), p.wrap_width || P.size[0] * 0.9);
      lines.forEach((ln, i) => ctx.fillText(ln, 0, (i - (lines.length - 1) / 2) * hgt * 1.25));
    } else if (kind === "image") {
      const img = playImage(p.image);
      if (img.complete && img.naturalWidth) { const sz = p.size || [img.naturalWidth, img.naturalHeight]; ctx.scale(1, -1); ctx.drawImage(img, -sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); }
      else { ctx.strokeStyle = "#888"; ctx.strokeRect(-100, -75, 200, 150); }
    } else {
      ctx.fillStyle = cssColor(p.fill, "#fff"); ctx.strokeStyle = cssColor(p.line_color, cssColor(p.fill, "#fff")); ctx.lineWidth = p.line_width || 2;
      const sz = Array.isArray(p.size) ? p.size : [p.size || 100, p.size || 100];
      const fillIt = p.fill !== null && p.fill !== "transparent", strokeIt = !!p.line_color;
      ctx.beginPath();
      if (kind === "rect") ctx.rect(-sz[0] / 2, -sz[1] / 2, sz[0], sz[1]);
      else if (kind === "circle") ctx.arc(0, 0, p.radius || 50, 0, 2 * Math.PI);
      else if (kind === "ellipse") ctx.ellipse(0, 0, sz[0] / 2, sz[1] / 2, 0, 0, 2 * Math.PI);
      else if (kind === "polygon" && (p.vertices || []).length) { p.vertices.forEach(([vx, vy], i) => i ? ctx.lineTo(vx, vy) : ctx.moveTo(vx, vy)); ctx.closePath(); }
      if (kind === "line" || kind === "cross") {
        ctx.strokeStyle = cssColor(p.line_color || p.fill, "#fff");
        if (kind === "line") { ctx.moveTo(...(p.start || [-50, 0])); ctx.lineTo(...(p.end || [50, 0])); }
        else { const s = sz[0] / 2; ctx.moveTo(-s, 0); ctx.lineTo(s, 0); ctx.moveTo(0, -s); ctx.lineTo(0, s); }
        ctx.stroke();
      } else { if (fillIt) ctx.fill(); if (strokeIt) ctx.stroke(); }
    }
    ctx.restore();
  }
}
function wrapLines(ctx, text, width) {
  const out = [];
  for (const para of text.split("\n")) {
    let line = "";
    for (const w of para.split(" ")) {
      const t = line ? line + " " + w : w;
      if (ctx.measureText(t).width > width && line) { out.push(line); line = w; } else line = t;
    }
    out.push(line);
  }
  return out;
}
function playImage(src) {
  if (!P.imgs[src]) { const im = new Image(); im.src = `/api/file?path=${encodeURIComponent((S.path ? S.path.replace(/[^/]*$/, "") : "") + src)}`; P.imgs[src] = im; }
  return P.imgs[src];
}
/* A sound event of the running experiment ({source, volume, tone_duration}): a tone in Hz or a file next to it.
 * (It used to be a second global playSound, which the asset picker's playSound in widgets.js silently replaced.) */
function playTrySound(snd) {
  try {
    const src = snd.source;
    if (typeof src === "number" || /^\d+(\.\d+)?$/.test(String(src))) {
      P.audio ||= new (window.AudioContext || window.webkitAudioContext)();
      const osc = P.audio.createOscillator(), g = P.audio.createGain();
      osc.frequency.value = +src; g.gain.value = 0.2 * (snd.volume ?? 1);
      osc.connect(g).connect(P.audio.destination); osc.start(); osc.stop(P.audio.currentTime + (+snd.tone_duration || +snd.duration || 0.3));
    } else if (src) {
      const a = new Audio(`/api/file?path=${encodeURIComponent((S.path ? S.path.replace(/[^/]*$/, "") : "") + src)}`); a.volume = Math.max(0, Math.min(1, snd.volume ?? 1));
      a.play().catch(() => {});
    }
  } catch { /* sound is best effort in the browser */ }
}

async function stopPlay() {
  if (!P.on) return;
  try { const st = await api("/api/play/stop", {}); finishPlay({...st, running: false}); } catch { finishPlay({running: false}); }
}
/* The session ended: the end panel docks at the bottom of the overlay (W10) instead of a dialog. */
function finishPlay(f) {
  if (!P.on) return;
  P.on = false;
  document.removeEventListener("keydown", playKey, true); document.removeEventListener("keyup", playKey, true);
  S.triedAt = Date.now();
  const el = $("#play");
  el.classList.add("ended");
  el.querySelector(".play-stop")?.remove();
  el.querySelector(".play-hint").textContent = "";
  const res = f.result || {};
  const title = f.error ? "The experiment stopped with a problem" : res.aborted ? "Stopped" : "Done!";
  const facts = [];
  if (res.screens !== undefined) {
    facts.push(countWord(res.trials ?? 0, "trial"), countWord(res.responses ?? 0, "response"));
    if (res.accuracy != null) facts.push(`${Math.round(res.accuracy * 100)} % correct`);
    if (res.mean_rt != null) facts.push(`${Math.round(res.mean_rt * 1000)} ms mean`);
  }
  const end = $("#play-end");
  const again = h("button", {type: "button", class: "btn primary", onclick: () => { closePlay(false); startPlay(P.routine); }}, icon("refresh"), "Try again");
  const data = h("button", {type: "button", class: "btn", onclick: () => {
    closePlay(false);
    const dir = String(res.data_dir || "").replace(/\\/g, "/").split("/").filter(Boolean).pop() || null;
    if (typeof D !== "undefined") { D.filter = "tests"; D.sel = null; D.pick = dir; }
    EDGE.go("data");
  }}, icon("results"), "See this data");
  const back = h("button", {type: "button", class: "btn", onclick: () => closePlay(true)}, "Back to editing");
  end.replaceChildren(
    h("div", {class: "pe-main"},
      h("div", {class: "pe-head " + (f.error ? "bad" : res.aborted ? "stopped" : "ok")}, icon(f.error ? "error" : res.aborted ? "stop" : "success", "m"), h("b", {}, title), facts.length ? h("span", {class: "pe-facts"}, facts.join(" · ")) : null),
      f.error ? h("pre", {class: "pe-err mono"}, f.error) : null,
      f.error ? h("p", {class: "pe-note"}, "The Problems list and the documentation explain most messages. The last lines of the log:") : null,
      f.error && (f.log || []).length ? h("details", {class: "pe-log"}, h("summary", {}, "Log"), h("pre", {class: "mono"}, (f.log || []).join("\n"))) : null,
      !f.error && res.note ? h("p", {class: "pe-note"}, "Times measured in a browser are approximate. Use Run with a participant for real data.") : null),
    h("div", {class: "pe-btns"}, again, res.data_dir ? data : null, back));
  end.hidden = false;
  P.fit?.();
  end.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePlay(true); } });
  P.release = ui.trapFocus(el);
  setTimeout(() => again.focus(), 0);
  ui.announce(`${title}${facts.length ? ". " + facts.join(", ") : ""}`);
}
/* Close the overlay; "Back to editing" returns to the workspace, screen and selection you started from. */
function closePlay(restore) {
  const el = $("#play");
  window.removeEventListener("resize", P.fit);
  P.release?.(); P.release = null;
  el.classList.add("hidden"); el.classList.remove("ended"); el.replaceChildren();
  el.removeAttribute("role"); el.removeAttribute("aria-modal");
  if (restore && P.back) {
    const b = P.back;
    if (b.routine && S.exp.routines[b.routine]) S.routine = b.routine;
    S.sel = b.sel; if (typeof fixSelection === "function") fixSelection();
    if (b.ws === "build" && b.view) S.view = b.view;
    if (S.ws !== b.ws) EDGE.go(b.ws); else renderAll();
    if (P.opener && P.opener.isConnected) P.opener.focus?.();
  }
}

/* ================================================================== Run with a participant (W11) */
const RUN = {key: "", form: null, info: null, pf: null, pfKey: "", rec: null, recKey: "", poll: null, mon: null, status: null, today: null, todayKey: "",
  verdict: null, anyway: false, starting: false};
/* Kept name: "Run with a participant" goes to the Run page. */
function runDialog() { EDGE.go("run"); }

function runPhase() {
  if (S.noDoc || !S.exp) return "nodoc";
  if (S.run && S.run.path && S.run.path !== S.path && S.run.running) return "other";
  if (S.run && (!S.run.path || S.run.path === S.path)) return S.run.running ? "live" : "after";
  return "before";
}
function renderRunPage(el) {
  el = el || $("#ws-run");
  if (!el) return;
  const phase = runPhase();
  const key = `${phase}|${S.path || ""}|${S.run?.id || ""}`;
  const a = document.activeElement;
  const keep = a && el.contains(a) ? a.dataset?.fkey : null;
  const scroll = el.scrollTop;
  if (phase === "live") {
    if (RUN.key !== key || !el.querySelector(".run-live")) { RUN.key = key; el.replaceChildren(runLiveView()); }
    runPoll();
    return;
  }
  RUN.key = key;
  if (phase === "after") el.replaceChildren(runAfterView());
  else if (phase === "other") el.replaceChildren(runOtherView());
  else if (phase === "nodoc") el.replaceChildren(h("div", {class: "empty"}, h("p", {}, "Open an experiment first.")));
  else el.replaceChildren(runBeforeView());
  el.scrollTop = scroll;
  if (keep) el.querySelector(`[data-fkey="${CSS.escape(keep)}"]`)?.focus({preventScroll: true});
}
const runHead = (title, extra) => h("header", {class: "page-head"}, h("h1", {class: "t-title-l", id: "run-title"}, title), h("span", {class: "grow"}), extra || null);
function runDataDir() { return (RUN.info?.data_dir || (S.path ? S.path.replace(/[^/]*$/, "") + ((S.exp.settings?.data || {}).dir || "data") : "data")).replace(/\/?$/, "/"); }

/* ---------------- before the session */
function runBeforeView() {
  const exp = S.exp;
  if (!RUN.form || RUN.form.path !== S.path) {
    RUN.form = {path: S.path, pid: "", ses: "1", simulate: false, fullscreen: (exp.settings?.window?.fullscreen ?? true) !== false, extra: {}};
    RUN.info = null; RUN.anyway = false; RUN.verdict = null;
    if (S.path) api(`/api/next_participant?path=${encodeURIComponent(S.path)}`).then((info) => {
      RUN.info = info;
      if (!RUN.form.pid) RUN.form.pid = info.suggestion;
      if (S.ws === "run" && runPhase() === "before") renderRunPage();
    }).catch(() => {});
  }
  const F = RUN.form;
  const hasDevices = (exp.devices || []).length > 0;
  // this session
  const sess = h("section", {class: "card pad run-card run-session", "aria-labelledby": "run-sess-title"}, h("h2", {class: "t-title-s", id: "run-sess-title"}, "This session"));
  const used = RUN.info?.used || [];
  const pidWarn = F.pid && used.includes(F.pid.trim());
  const pid = h("input", {class: "input run-pid", id: "run-pid", value: F.pid, autocomplete: "off", spellcheck: "false", "data-fkey": "run:pid", "aria-describedby": "run-pid-help",
    oninput: (e) => { F.pid = e.target.value; const w = used.includes(F.pid.trim()); help.replaceChildren(...pidHelp(w)); help.classList.toggle("warn", w); }});
  const help = h("div", {class: "help" + (pidWarn ? " warn" : ""), id: "run-pid-help"}, ...pidHelp(pidWarn));
  function pidHelp(warn) {
    if (warn) return [icon("warning"), ` Participant ${F.pid.trim()} already has data. A new session folder is made; nothing is overwritten.`];
    if (!used.length) return [RUN.info ? "The first participant of this experiment." : ""];
    return [`Next free number. ${runUsedRange(used)} already ${used.length === 1 ? "has" : "have"} data.`];
  }
  sess.append(h("div", {class: "field"}, h("label", {for: "run-pid"}, "Participant ID"), pid, help));
  sess.append(h("div", {class: "field"}, h("label", {for: "run-ses"}, "Session"),
    h("input", {class: "input num run-ses", id: "run-ses", value: F.ses, inputmode: "numeric", "data-fkey": "run:ses", oninput: (e) => { F.ses = e.target.value; }})));
  const segRow = (label, id, opts, value, on) => { const s = ui.seg(opts, value, on); s.setAttribute("aria-labelledby", id); return h("div", {class: "field run-segrow"}, h("span", {class: "label", id}, label), s); };
  if (hasDevices) put(sess, segRow("Devices", "run-dev-l", [{value: "real", label: "Real devices"}, {value: "sim", label: "Simulated"}], F.simulate ? "sim" : "real",
    (v) => { F.simulate = v === "sim"; renderRunPage(); }),
  F.simulate ? h("p", {class: "t-caption run-note"}, "No hardware is used: every device is simulated. Use it for a pilot without the lab equipment.") : null);
  sess.append(segRow("Screen", "run-scr-l", [{value: "1", label: "Full screen"}, {value: "0", label: "In a window"}], F.fullscreen ? "1" : "0", (v) => { F.fullscreen = v === "1"; }));
  const mon = exp.settings?.window?.screen ?? 0;
  sess.append(h("p", {class: "t-small run-monitor"}, h("span", {class: "label"}, "Monitor"), ` ${+mon === 0 ? "Main (1)" : `Monitor ${+mon + 1}`} `,
    h("button", {type: "button", class: "linkbtn", onclick: () => (typeof openSettings === "function" ? openSettings("screen") : null)}, "Change")));
  const extraFields = Object.entries(exp.settings?.participant || {}).filter(([k]) => !["participant", "session"].includes(k));
  if (extraFields.length) {
    const box = h("div", {class: "run-extra"}, h("h3", {class: "t-small run-sub"}, "Also asked"));
    for (const [k, dflt] of extraFields) {
      const id = "run-x-" + k;
      if (!(k in F.extra)) F.extra[k] = dflt ?? "";
      box.append(h("div", {class: "field"}, h("label", {for: id}, inspCapWords(k)), h("input", {class: "input", id, value: F.extra[k] ?? "", "data-fkey": "run:x:" + k, oninput: (e) => { F.extra[k] = e.target.value; }})));
    }
    box.append(h("p", {class: "t-caption"}, "Fields from Experiment settings › Participant info."));
    sess.append(box);
  }
  // what will be recorded
  const recKey = String(S.rev) + "|" + (S.path || "");
  if (RUN.recKey !== recKey || !RUN.rec) {
    RUN.recKey = recKey;
    RUN.rec = h("div", {class: "run-rec"}, h("p", {class: "t-caption"}, "Working out what is recorded…"));
    const host = RUN.rec;
    if (typeof recordingSummary === "function") recordingSummary().then((b) => { host.replaceChildren(...(b ? [b] : [h("p", {class: "t-caption"}, "Couldn't work it out.")])); });
  }
  sess.append(h("h3", {class: "t-small run-sub"}, "What will be recorded"), RUN.rec);
  // before you start: the preflight, unreviewed assistant code
  const pre = h("section", {class: "card pad run-card run-pre", "aria-labelledby": "run-pre-title"});
  const pfHead = h("div", {class: "card-head"}, h("h2", {class: "t-title-s", id: "run-pre-title"}, "Before you start"));
  pre.append(pfHead);
  const pfKey = `${S.path || ""}|${S.fingerprint || ""}`;
  if (!S.path) {
    pre.append(h("div", {class: "alert info"}, icon("info"), h("div", {}, h("b", {}, "Not saved yet"), "The check runs on the saved experiment. Save it to check it; Start session saves it first.",
      h("div", {class: "actions"}, h("button", {type: "button", class: "btn sm", onclick: async () => { if (await save()) renderRunPage(); }}, icon("save"), "Save")))));
  } else {
    if (RUN.pfKey !== pfKey || !RUN.pf) {
      RUN.pfKey = pfKey; RUN.verdict = null; RUN.anyway = false;
      RUN.pf = typeof preflightBox === "function" ? preflightBox((v) => { RUN.verdict = v; if (S.ws === "run" && runPhase() === "before") renderRunPage(); }) : h("div");
    }
    pfHead.append(h("button", {type: "button", class: "btn sm ghost", "data-fkey": "run:recheck", onclick: () => { RUN.pfKey = ""; renderRunPage(); }}, icon("refresh"), "Check again"));
    if (S.dirty) pre.append(h("p", {class: "t-caption run-note"}, "This checks the saved version. Start session saves your changes first."));
    pre.append(RUN.pf);
  }
  const code = runUnreviewedCode();
  if (code.length) pre.append(h("div", {class: "alert warning run-code"}, icon("warning"), h("div", {},
    h("b", {}, code.length === 1 ? "Code written by the assistant hasn't been reviewed" : `${code.length} pieces of code written by the assistant haven't been reviewed`),
    h("ul", {class: "plain"}, code.map((c) => h("li", {}, `“${c.routine}” › ${c.id} `,
      h("button", {type: "button", class: "btn sm ghost", onclick: () => EDGE.select({kind: "component", routine: c.routine, id: c.id}, {pulse: true})}, "Review it"),
      h("button", {type: "button", class: "btn sm ghost", onclick: () => { try { inspAssistantApi()?.markReviewed?.(c.routine, c.id); } catch { /* no assistant */ } renderRunPage(); }}, "I've read it")))),
    h("p", {class: "t-caption"}, "Read the code before running real participants: it runs with full access to this computer."))));
  pre.append(runToday());
  // the sticky footer: [Start anyway] [Start session]
  const nogo = RUN.verdict === "no-go";
  const busy = S.path && !RUN.verdict;
  const blocked = !!S.proposal;
  const start = h("button", {type: "button", class: "btn primary lg run-start", "data-fkey": "run:start", "aria-busy": RUN.starting ? "true" : null,
    disabled: blocked || (nogo && !RUN.anyway) || RUN.starting ? "" : null, onclick: () => runStartSession()},
  RUN.starting ? h("span", {class: "spin"}) : icon("run"), RUN.starting ? "Starting…" : !S.path || S.dirty ? "Save and start" : busy ? "Start session" : "Start session");
  const anyway = nogo && !RUN.anyway && !blocked ? h("button", {type: "button", class: "linkbtn run-anyway", onclick: () => { RUN.anyway = true; renderRunPage(); }}, "Start anyway (not recommended)") : null;
  const foot = h("footer", {class: "run-foot"},
    h("p", {class: "t-small t-2"}, blocked ? "Apply or discard the assistant's changes first." : `The experiment opens in its own window. Data is saved to ${runDataDir()} as it runs.`),
    h("span", {class: "grow"}), anyway, start);
  return h("div", {class: "run-page"}, runHead("Run with a participant", helpLink("BUILDER_GUIDE", "", "running a session")),
    h("div", {class: "run-grid"}, sess, pre), foot);
}
function inspAssistantApi() { return window.Assistant || (typeof Assistant !== "undefined" ? Assistant : null); }
function runUnreviewedCode() {
  try { const A = inspAssistantApi(); return (A && typeof A.unreviewedCode === "function" ? A.unreviewedCode(S.exp) : []) || []; } catch { return []; }
}
function runUsedRange(used) {
  const nums = used.filter((u) => /^\d+$/.test(u)).sort((a, b) => +a - +b);
  const others = used.filter((u) => !/^\d+$/.test(u));
  const parts = [];
  if (nums.length) {
    const contiguous = nums.every((n, i) => i === 0 || +n === +nums[i - 1] + 1);
    parts.push(contiguous && nums.length > 2 ? `${nums[0]}–${nums[nums.length - 1]}` : nums.slice(0, 5).join(", ") + (nums.length > 5 ? ", …" : ""));
  }
  if (others.length) parts.push(others.slice(0, 3).join(", ") + (others.length > 3 ? ", …" : ""));
  return parts.join(", ");
}
/* Today's sessions of this experiment: "005 done 09:02 · 006 stopped early 09:40". */
function runToday() {
  const box = h("div", {class: "run-today"});
  const key = `${S.path}|${S.files?.length || 0}|${S.run?.id || ""}`;
  const draw = () => {
    const today = new Date().toDateString();
    const mine = (RUN.today || []).filter((s) => !s.dry_run && (typeof sessionBelongs === "function" ? sessionBelongs(s) : true) && s.started && new Date(s.started).toDateString() === today);
    box.replaceChildren(h("h3", {class: "t-small run-sub"}, "Today"),
      mine.length ? h("ul", {class: "run-today-list"}, mine.slice(0, 8).map((s) => h("li", {},
        icon(s.aborted ? "warning" : s.errors ? "error" : "success", s.aborted ? "c-warn" : s.errors ? "c-bad" : "c-ok"),
        h("b", {}, String(s.participant ?? "?")), ` session ${s.session ?? 1} · ${clock(s.started)}`, s.aborted ? " · stopped early (data kept)" : s.errors ? ` · ${countWord(s.errors, "problem")} in the report` : "")))
        : h("p", {class: "t-caption"}, "No sessions yet today."),
      h("button", {type: "button", class: "btn sm ghost", onclick: () => { if (typeof D !== "undefined") { D.filter = "participants"; D.sel = null; } EDGE.go("data"); }}, "All sessions in Data", icon("chev-right")));
  };
  if (RUN.todayKey !== key) {
    RUN.todayKey = key;
    api("/api/sessions").then((r) => { RUN.today = r.sessions || []; draw(); }).catch(() => { RUN.today = []; draw(); });
  }
  draw();
  return box;
}
async function runStartSession() {
  if (S.proposal) return toast("Apply or discard the assistant's changes first");
  const F = RUN.form;
  if (!F.pid.trim()) { toast("Type a participant ID first."); $("#run-pid")?.focus(); return; }
  if (!S.path || S.dirty) { if (!(await save())) return; }
  S.strict = true;
  if (typeof renderIssues === "function") renderIssues();
  const errors = (S.issues || []).filter((i) => i.level === "error");
  if (errors.length && !RUN.anyway) {
    if (typeof openProblems === "function") openProblems({reason: `Can't start yet: ${countWord(errors.length, "thing")} to fix.`});
    return;
  }
  RUN.starting = true; renderRunPage();
  try { await startRun(F.pid.trim(), F.ses.trim() || "1", !!F.simulate, F.fullscreen, F.extra); }
  finally { RUN.starting = false; if (S.ws === "run") renderRunPage(); }
}
/* Start a real session (the experiment opens in its own window) and show the live monitor. */
async function startRun(participant, session, simulate, fullscreen, extra = {}) {
  if (!participant) { toast("Type a participant ID first."); return; }
  let run_id;
  try { ({run_id} = await api("/api/run", {path: S.path, participant: {...extra, participant, session: session || "1"}, simulate: !!simulate, fullscreen: fullscreen !== false})); }
  catch (e) { toast(`The session couldn't start: ${e.message}`, {tone: "danger", ms: 8000}); return; }
  S.run = {id: run_id, path: S.path, participant, session: session || "1", startedAt: Date.now(), running: true, simulate: !!simulate};
  RUN.status = null; RUN.mon = null; RUN.key = "";
  ui.announce(`Recording participant ${participant}, session ${session || 1}.`, {assertive: true});
  EDGE.emit("run", S.run);
  if (S.ws !== "run") EDGE.go("run"); else renderRunPage();
}

/* ---------------- during the session: the live monitor on the page */
function runLiveView() {
  const r = S.run;
  RUN.mon = typeof monitorView === "function" ? monitorView() : {el: h("div"), update: () => {}};
  const stop = h("button", {type: "button", class: "btn danger run-stopbtn", "data-fkey": "run:stop", onclick: () => runStopSession()}, icon("stop"), "Stop session");
  const head = h("div", {class: "run-livehead", role: "status"},
    h("span", {class: "rec-dot", "aria-hidden": "true"}), h("b", {}, `Recording participant ${r.participant}, session ${r.session ?? 1}`),
    h("span", {class: "run-clock t-2", id: "run-clock"}, ""), h("span", {class: "grow"}), stop);
  const stLine = h("p", {class: "t-small t-2 run-stline", id: "run-stline"}, r.recovered ? "Found the session again after the page reloaded." : "Starting: opening the window and connecting devices…");
  const log = h("pre", {class: "run-log mono", id: "run-log"});
  return h("div", {class: "run-live"}, runHead("Run with a participant"), h("section", {class: "card pad run-livecard"}, head, stLine, RUN.mon.el,
    h("details", {class: "run-logbox"}, h("summary", {}, "Log"), log)),
  h("p", {class: "t-caption run-note"}, "You can keep working: the recording pill on the Run tab brings you back here. Saved changes apply to the next participant."));
}
function runPoll() {
  if (RUN.poll || !S.run?.id) return;
  const tick = async () => {
    RUN.poll = null;
    const run = S.run;
    if (!run?.id) return;
    let st;
    try { st = await api(`/api/run_status?id=${encodeURIComponent(run.id)}`); }
    catch (e) {
      if (/unknown run/i.test(e.message)) { S.run = null; EDGE.emit("run", null); if (S.ws === "run") renderRunPage(); return; }
      if (S.ws === "run") RUN.poll = setTimeout(tick, 1500);
      return;
    }
    RUN.status = st;
    if (S.run !== run) return;
    runLiveUpdate(st);
    if (!st.running) {
      if (S.run.running) {
        S.run.running = false; S.run.returncode = st.returncode; S.run.endedAt = Date.now();
        ui.announce(`The session of participant ${S.run.participant} ended.`, {assertive: true});
        EDGE.emit("run", S.run);
        if (typeof refreshFiles === "function") refreshFiles().then(() => { if (typeof renderBadges === "function") renderBadges(); });
      }
      RUN.todayKey = "";
      if (S.ws === "run") renderRunPage();
      return;
    }
    if (S.ws === "run") RUN.poll = setTimeout(tick, 800);
  };
  RUN.poll = setTimeout(tick, 0);
}
function runLiveUpdate(st) {
  RUN.mon?.update(st);
  const log = $("#run-log"); if (log) log.textContent = (st.output || []).slice(-40).join("\n");
  const line = $("#run-stline");
  if (line) line.textContent = st.stopping ? "Stopping: saving the data…" : st.running ? (st.monitor?.start ? "The experiment window is open." : "Starting: opening the window and connecting devices…") : "";
  const clk = $("#run-clock");
  if (clk && S.run) {
    const t0 = S.run.startedAt || Date.now(), s = Math.max(0, (Date.now() - t0) / 1000);
    const M = st.monitor || {}, exp = M.start?.expected_trials, n = (M.end || M.last || {}).trials ?? (M.last ? M.last.n : 0) ?? 0;
    const el = (M.end || M.devices || M.last || {}).elapsed || s;
    const left = exp && n > 1 && n < exp ? ` · about ${runMmss(el / n * (exp - n))} left` : "";
    clk.textContent = `${runMmss(el)} elapsed${left}`;
  }
}
const runMmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60) % 60).padStart(2, "0")}`;
async function runStopSession() {
  if (!S.run?.running) return;
  const ok = await ui.confirm({title: "Stop this session?", message: "Everything recorded so far is kept.", ok: "Stop session", cancel: "Keep running", danger: true});
  if (!ok || !S.run?.running) return;
  const b = document.querySelector(".run-stopbtn");
  if (b) { b.disabled = true; b.replaceChildren(h("span", {class: "spin"}), "Stopping…"); }
  try { await api(`/api/run_stop?id=${encodeURIComponent(S.run.id)}`, {}); } catch (e) { toast(`Couldn't stop it: ${e.message}`, {tone: "danger"}); }
}

/* ---------------- after the session */
function runAfterView() {
  const r = S.run, st = RUN.status || {};
  const out = st.output || [];
  const saved = out.find((l) => l.startsWith("Saved to "));
  const why = out.find((l) => l.startsWith("EDGE could not run"));
  const crash = st.monitor?.end?.crash;
  const stopped = !crash && (st.monitor?.end?.aborted || st.returncode === 1);
  const trials = st.monitor?.end?.trials ?? st.monitor?.last?.n;
  const secs = r.endedAt && r.startedAt ? Math.max(1, Math.round((r.endedAt - r.startedAt) / 1000)) : null;
  const facts = [`participant ${r.participant}`, secs ? (secs < 90 ? `${secs} s` : `${Math.round(secs / 60)} min`) : null, trials != null ? countWord(trials, "trial") : null,
    saved ? runShortPath(saved.replace(/^Saved to /, "")) : null].filter(Boolean).join(" · ");
  let banner;
  if (why) banner = h("div", {class: "alert danger"}, icon("error"), h("div", {}, h("b", {}, "The session couldn't start"), why.replace("EDGE could not run the experiment: ", "")));
  else if (st.returncode === 0 && !stopped) banner = h("div", {class: "alert success"}, icon("success"), h("div", {}, h("b", {}, "Session saved"), facts));
  else if (stopped) banner = h("div", {class: "alert warning"}, icon("warning"), h("div", {}, h("b", {}, "Stopped early; the data so far is saved"), facts));
  else if (st.returncode !== undefined && st.returncode !== null) banner = h("div", {class: "alert danger"}, icon("error"), h("div", {}, h("b", {}, `The session ended with a problem (code ${st.returncode})`), facts));
  else banner = h("div", {class: "alert info"}, icon("info"), h("div", {}, h("b", {}, "The session ended"), facts));
  const checks = (st.monitor?.end?.measures || st.monitor?.end?.checks || []);
  const next = RUN.info?.suggestion && RUN.info.suggestion !== String(r.participant) ? RUN.info.suggestion : (/^\d+$/.test(String(r.participant)) ? String(+r.participant + 1).padStart(String(r.participant).length, "0") : "");
  const card = h("section", {class: "card pad run-after"}, banner,
    crash && typeof crashBox === "function" ? crashBox(crash) : null,
    Array.isArray(checks) && checks.length ? h("p", {class: "t-small"}, "Measures vs expected: ", checks.map((c) => icon(c.ok === false ? "warning" : "check", c.ok === false ? "c-warn" : "c-ok"))) : null,
    h("div", {class: "run-afterbtns"},
      h("button", {type: "button", class: "btn primary", "data-fkey": "run:data", onclick: () => { if (typeof D !== "undefined") { D.filter = "participants"; D.sel = null; D.pick = saved ? saved.replace(/^Saved to /, "").replace(/\\/g, "/").split("/").filter(Boolean).pop() : null; } runClear(); EDGE.go("data"); }}, icon("results"), "See the data"),
      h("button", {type: "button", class: "btn", "data-fkey": "run:next", onclick: () => { runClear(); RUN.form = null; renderRunPage(); }}, `Next participant${next ? ` (${next})` : ""}`),
      h("button", {type: "button", class: "btn ghost", onclick: () => { runClear(); EDGE.go("build"); }}, "Back to Build")),
    out.length ? h("details", {class: "run-logbox", open: why ? "" : null}, h("summary", {}, "Log"), h("pre", {class: "run-log mono"}, out.slice(-60).join("\n"))) : null);
  return h("div", {class: "run-page"}, runHead("Run with a participant"), card);
}
/* "/home/…/stroop/data/007_1_…" -> "stroop/data/007_1_…" (the folder next to the experiment, as people know it). */
function runShortPath(p) {
  const path = String(p || "").replace(/\\/g, "/");
  const dir = (S.run?.path || S.path || "").split("/").slice(0, -1).join("/");
  const i = dir ? path.lastIndexOf("/" + dir + "/") : -1;
  return i >= 0 ? path.slice(i + 1) : path.split("/").filter(Boolean).slice(-3).join("/");
}
function runClear() { S.run = null; RUN.status = null; RUN.mon = null; RUN.key = ""; RUN.pfKey = ""; EDGE.emit("run", null); }
function runOtherView() {
  const r = S.run;
  const name = (r.path || "").split("/").pop().replace(/\.(ya?ml|json)$/i, "");
  return h("div", {class: "run-page"}, runHead("Run with a participant"),
    h("div", {class: "alert info"}, icon("run"), h("div", {}, h("b", {}, `A session of “${name}” is recording`), `Participant ${r.participant}. Start the next one when it has ended.`,
      h("div", {class: "actions"}, h("button", {type: "button", class: "btn sm", onclick: () => (typeof openRunningSession === "function" ? openRunningSession() : null)}, "Open it")))));
}
/* While the Run page is open, keep polling a running session (after a reload, P1 restores S.run from /api/runs). */
EDGE.on("workspace", ({ws}) => { if (ws === "run" && S.run?.running) runPoll(); });
EDGE.on("doc:loaded", () => { RUN.form = null; RUN.pf = null; RUN.pfKey = ""; RUN.rec = null; RUN.recKey = ""; RUN.todayKey = ""; });
EDGE.on("doc:saved", () => { if (S.ws === "run") renderRunPage(); });
