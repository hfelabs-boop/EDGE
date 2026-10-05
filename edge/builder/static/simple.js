/* EDGE builder: features for people who are new to experiment building.
 *   storyboard   – every screen in order, as pictures, with trial counts and the session length
 *   wizard       – a finished experiment from a few plain questions
 *   try it       – do the experiment yourself inside the builder (real engine, simulated hardware)
 *   run dialog   – participant id, session, hardware and screen choices before a real session
 * Loaded after app.js and uses its helpers (S, h, $, api, drawScreen, …).
 */
"use strict";

/* Element.append() would print "null" for skipped optional parts. */
function put(el, ...kids) { el.append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false)); }

/* ================================================================== storyboard */
let _estimate = {key: null, value: null};
function storyEstimate(onReady) {
  const key = JSON.stringify(S.exp.flow) + JSON.stringify(Object.fromEntries(Object.entries(S.exp.routines).map(([k, r]) => [k, [r.duration, (r.components || []).map((c) => [c.start, c.duration, c.end_routine])]])));
  if (_estimate.key === key) return _estimate.value;
  _estimate = {key, value: null};
  api("/api/estimate", {experiment: S.exp, path: S.path}).then((r) => { if (_estimate.key === key) { _estimate.value = r; onReady(); } }).catch(() => {});
  return null;
}

function thumbTime(rid) {
  // a moment that shows the main stimulus: just after the last visual thing has appeared
  let t = 0;
  for (const c of comps(rid)) {
    const d = S.schema.components[c.type];
    if (!d || !d.visual || c.start_after || c.start_if || c.if || typeof c.start !== "number" && c.start != null) continue;
    t = Math.max(t, numOr(c.start, 0));
  }
  return t + 0.01;
}

function screenSummary(rid) {
  const r = S.exp.routines[rid] || {};
  const resp = (r.components || []).find((c) => c.end_routine);
  const bits = [];
  if (resp) {
    const what = {keyboard: `waits for ${Array.isArray(resp.keys) ? resp.keys.join(" / ") : "a key"}`, mouse: "waits for a click",
      slider: "waits for a rating", html: "waits for the form", survey: "waits for the answers", gaze_roi: "waits for a look"}[resp.type] || `ends with ${resp.id}`;
    bits.push(resp.duration != null ? `${what} (max ${resp.duration}s)` : what);
  }
  if (typeof r.duration === "number") bits.push(`${r.duration}s`);
  else if (!resp) {
    const end = Math.max(0, ...(r.components || []).map((c) => numOr(c.start, 0) + numOr(c.duration, 0)));
    if (end) bits.push(`${Math.round(end * 100) / 100}s`);
  }
  return bits.join(" · ") || "—";
}

function renderStoryboard(el) {
  el.classList.add("story-host");
  const est = storyEstimate(() => { if (S.view === "story") renderTimeline(); });
  put(el, h("div", {class: "story-head"},
    h("b", {}, S.exp.name || "experiment"),
    h("span", {class: "story-est"}, est && !est.error ? ` · ${est.text}` : est && est.error ? "" : " · estimating…"),
    h("span", {style: "flex:1"}),
    h("span", {class: "help"}, "Click a screen to edit it. ")));
  if (!S.exp.flow.length) {
    put(el, h("div", {class: "tl-empty"}, "Nothing here yet. ",
      h("button", {class: "accent", onclick: () => openWizard()}, "✨ Answer a few questions"), " or click “+ screen” above."));
    return;
  }
  const row = h("div", {class: "story"});
  storyNodes(S.exp.flow, row, []);
  put(el, row);
  const unused = Object.keys(S.exp.routines).filter((rid) => !routineInFlowOrder().includes(rid));
  if (unused.length) put(el, h("div", {class: "help story-unused"}, "Not in the flow (never shown): ",
    unused.map((rid) => h("a", {href: "#", onclick: (e) => { e.preventDefault(); openScreen(rid); }}, rid + " "))));
}

function storyNodes(nodes, into, path) {
  nodes.forEach((n, i) => {
    const p = [...path, i];
    if (typeof n === "string" || (n && n.routine !== undefined)) put(into, storyCard(routineOfNode(n), n.if));
    else if (n.loop !== undefined) {
      const box = h("div", {class: "story-loop"});
      const reps = n.repeats && n.repeats !== 1 ? ` × ${n.repeats}` : "";
      put(box, h("div", {class: "story-loop-head", title: "Click to edit the trial list", onclick: () => { S.sel = {kind: "loop", path: p}; renderAll(); }},
        `⟳ ${n.loop}: ${n.staircase ? "staircase" : loopRowsLabel(n)}${reps}${n.order && n.order !== "sequential" ? ", " + n.order + " order" : ""}`));
      const inner = h("div", {class: "story"}); storyNodes(n.children || [], inner, [...p, "children"]); put(box, inner);
      put(into, box);
    } else if (n.statemachine !== undefined) {
      const box = h("div", {class: "story-loop sm"});
      put(box, h("div", {class: "story-loop-head", onclick: () => { S.sel = {kind: "machine", path: p}; renderAll(); }}, `⚙ workflow ${n.statemachine} (click to see the diagram)`));
      const inner = h("div", {class: "story"});
      for (const [name, st] of Object.entries(n.states || {})) {
        const sb = h("div", {class: "story-loop state"}, h("div", {class: "story-loop-head", onclick: () => { S.sel = {kind: "state", path: p, name}; renderAll(); }},
          `${n.start === name ? "▶ " : ""}${name}${st.max_visits ? ` (≤ ${st.max_visits}×)` : ""}`));
        const si = h("div", {class: "story"}); storyNodes(st.run || [], si, [...p, "states", name, "run"]); put(sb, si); put(inner, sb);
      }
      put(box, inner); put(into, box);
    } else if (n.if !== undefined) {
      const box = h("div", {class: "story-loop branch"});
      put(box, h("div", {class: "story-loop-head", onclick: () => { S.sel = {kind: "branch", path: p}; renderAll(); }}, `◇ if ${short(n.if, 30)}`));
      const a = h("div", {class: "story"}); storyNodes(n.then || [], a, [...p, "then"]);
      const b = h("div", {class: "story"}); storyNodes(n.else || [], b, [...p, "else"]);
      put(box, a, h("div", {class: "help"}, "otherwise"), b); put(into, box);
    }
  });
}

function storyCard(rid, cond) {
  const cv = h("canvas", {width: 192, height: 108, class: "story-thumb"});
  try { drawScreen(cv, rid, thumbTime(rid)); } catch { /* preview is best effort */ }
  return h("div", {class: "story-card", title: "Click to edit this screen", onclick: () => openScreen(rid)},
    cv, h("div", {class: "story-name"}, rid, cond ? h("span", {class: "cond-badge"}, "if") : null),
    h("div", {class: "story-sub"}, screenSummary(rid)));
}

/* ================================================================== design wizard */
const W = {step: 0, a: null, preview: null};
const WIZ_STEPS = ["What they see", "How they respond", "Timing", "Practice & feedback", "Blocks & texts", "Questionnaires & devices"];

function wizardDefaults() {
  return {name: "my_experiment", stimulus: {kind: "word", items: [
    {stimulus: "LEFT", correct: "f", condition: "left"}, {stimulus: "RIGHT", correct: "j", condition: "right"}]},
    response: {kind: "keys", keys: ["f", "j"]}, timing: {fixation: 0.5, stimulus_duration: "", response_deadline: 2, iti: 0.5},
    feedback: true, practice: {mode: "until", criterion: 0.8, max_rounds: 3}, blocks: {count: 2, repeats: 2, order: "random"},
    instructions: "", thanks: "", devices: [], questionnaires: []};
}

function openWizard() {
  if (S.dirty && !confirm("Start a new experiment? Unsaved changes to the current one will be lost (save first to keep them).")) return;
  W.step = 0; W.a = wizardDefaults();
  renderWizard();
}

function renderWizard() {
  const body = $("#modal-body"); body.innerHTML = ""; body.className = "wizard";
  const a = W.a;
  put(body, h("h2", {}, "New experiment"),
    h("div", {class: "wiz-steps"}, WIZ_STEPS.map((t, i) => h("span", {class: "wiz-step" + (i === W.step ? " on" : i < W.step ? " done" : ""),
      onclick: () => { W.step = i; renderWizard(); }}, `${i + 1}. ${t}`))));
  const page = h("div", {class: "wiz-page"});
  const radio = (group, value, label, sub, on) => h("label", {class: "wiz-choice" + (on ? " on" : "")},
    h("input", {type: "radio", name: group, checked: on || null, onchange: () => { value(); renderWizard(); }}), h("b", {}, label), sub ? h("small", {}, sub) : null);
  const num = (label, get, set, help) => h("div", {class: "field"}, h("label", {}, label),
    h("input", {type: "number", step: "0.1", min: "0", value: get() ?? "", placeholder: "empty = no limit", oninput: (e) => { set(e.target.value === "" ? "" : +e.target.value); wizPreview(); }}),
    help ? h("div", {class: "help"}, help) : null);
  const text = (label, get, set, ph, rows) => h("div", {class: "field"}, h("label", {}, label),
    rows ? h("textarea", {rows, placeholder: ph || "", oninput: (e) => { set(e.target.value); wizPreview(); }}, get() || "")
      : h("input", {value: get() ?? "", placeholder: ph || "", oninput: (e) => { set(e.target.value); wizPreview(); }}));
  if (W.step === 0) {
    put(page, text("Name of the experiment", () => a.name, (v) => a.name = v, "e.g. word_task"));
    put(page, h("div", {class: "wiz-row"},
      radio("kind", () => { a.stimulus.kind = "word"; }, "Words", "text on the screen", a.stimulus.kind === "word"),
      radio("kind", () => { a.stimulus.kind = "picture"; }, "Pictures", "image files", a.stimulus.kind === "picture"),
      radio("kind", () => { a.stimulus.kind = "sound"; }, "Sounds", "files, or a number = tone in Hz", a.stimulus.kind === "sound"),
      radio("kind", () => { a.stimulus.kind = "shape"; }, "Shapes", "circle, rect, cross …", a.stimulus.kind === "shape")));
    const keys = a.response.kind === "keys";
    put(page, h("div", {class: "help"}, keys ? "One row per stimulus. The correct key is what a right answer would be (leave it empty if there is no right answer). The condition is a label for your analysis (e.g. congruent / incongruent)."
      : "One row per stimulus. The condition is a label for your analysis."));
    const tbl = h("table", {class: "grid wiz-items"}, h("tr", {}, h("th", {}, a.stimulus.kind === "picture" ? "picture file (in images/)" : a.stimulus.kind === "sound" ? "sound file or Hz" : a.stimulus.kind === "shape" ? "shape" : "word"),
      keys ? h("th", {}, "correct key") : null, h("th", {}, "condition"), h("th", {})));
    a.stimulus.items.forEach((it, i) => tbl.append(h("tr", {},
      h("td", {}, h("input", {value: it.stimulus ?? "", oninput: (e) => { it.stimulus = e.target.value; wizPreview(); }})),
      keys ? h("td", {}, h("input", {value: it.correct ?? "", style: "width:70px", oninput: (e) => { it.correct = e.target.value; wizPreview(); }})) : null,
      h("td", {}, h("input", {value: it.condition ?? "", oninput: (e) => { it.condition = e.target.value; wizPreview(); }})),
      h("td", {}, h("button", {class: "mini danger", onclick: () => { a.stimulus.items.splice(i, 1); renderWizard(); }}, "×")))));
    put(page, tbl, h("div", {class: "btns"}, h("button", {class: "mini", onclick: () => { a.stimulus.items.push({stimulus: "", correct: "", condition: ""}); renderWizard(); }}, "+ row"),
      h("button", {class: "mini", title: "Paste rows from a spreadsheet (tab or comma separated: stimulus, correct key, condition)", onclick: () => {
        const t = prompt("Paste rows (stimulus, correct key, condition), one per line:"); if (!t) return;
        a.stimulus.items = t.split(/\r?\n/).filter((l) => l.trim()).map((l) => { const c = l.split(/\t|,/).map((x) => x.trim()); return {stimulus: c[0], correct: c[1] || "", condition: c[2] || ""}; });
        renderWizard(); }}, "Paste from a spreadsheet")));
    if (a.stimulus.kind === "picture") put(page, h("div", {class: "help"}, "After creating, put the picture files in the images/ folder next to the experiment (the builder shows where)."));
  } else if (W.step === 1) {
    const r = a.response;
    put(page, h("div", {class: "wiz-row"},
      radio("resp", () => { r.kind = "keys"; }, "Press a key", "e.g. F for left, J for right", r.kind === "keys"),
      radio("resp", () => { r.kind = "mouse"; }, "Click", "on the stimulus", r.kind === "mouse"),
      radio("resp", () => { r.kind = "rating"; }, "Rating scale", "e.g. 1 to 7", r.kind === "rating"),
      radio("resp", () => { r.kind = "none"; }, "No response", "just watch / listen", r.kind === "none")));
    if (r.kind === "keys") put(page, text("Keys participants may press (separated by spaces)", () => (r.keys || []).join(" "), (v) => r.keys = v.split(/[\s,]+/).filter(Boolean), "f j"),
      h("div", {class: "help"}, "Key names: letters, numbers, space, left, right, up, down, return."));
    if (r.kind === "rating") put(page, num("Number of points on the scale", () => r.ticks ?? 7, (v) => r.ticks = v || 7),
      text("Labels at the ends (separated by a comma)", () => (r.labels || ["not at all", "very much"]).join(", "), (v) => r.labels = v.split(",").map((x) => x.trim()).filter(Boolean)));
  } else if (W.step === 2) {
    const t = a.timing;
    put(page, num("Fixation cross before each stimulus (seconds, 0 = none)", () => t.fixation, (v) => t.fixation = v === "" ? 0 : v),
      num("Show the stimulus for (seconds)", () => t.stimulus_duration, (v) => t.stimulus_duration = v, "empty = until they respond"),
      a.response.kind !== "none" ? num("Time limit to respond (seconds)", () => t.response_deadline, (v) => t.response_deadline = v, "empty = wait as long as it takes; with a limit, a missing answer counts as “too slow”") : null,
      num("Blank pause between trials (seconds)", () => t.iti, (v) => t.iti = v === "" ? 0 : v));
  } else if (W.step === 3) {
    const pr = a.practice, keys = a.response.kind === "keys";
    const fb = h("input", {type: "checkbox", onchange: (e) => { a.feedback = e.target.checked; wizPreview(); }}); fb.checked = !!a.feedback;
    put(page, h("label", {class: "wiz-check"}, fb, " Show “Correct!” / “Wrong” after each trial in the main part too"),
      h("div", {class: "help"}, keys ? "Practice always shows feedback." : "Feedback needs correct keys (step 1)."));
    put(page, h("h4", {}, "Practice"), h("div", {class: "wiz-row"},
      radio("prac", () => { pr.mode = "none"; }, "No practice", "", pr.mode === "none"),
      radio("prac", () => { pr.mode = "once"; }, "Practice once", "every stimulus once", pr.mode === "once"),
      radio("prac", () => { pr.mode = "until"; }, "Practice until good enough", "repeat until accurate", pr.mode === "until")));
    if (pr.mode === "until") put(page, h("div", {class: "wiz-row"},
      num("Proportion correct needed (0–1)", () => pr.criterion, (v) => pr.criterion = v),
      num("At most this many rounds", () => pr.max_rounds, (v) => pr.max_rounds = v)),
      !keys ? h("div", {class: "help", style: "color:var(--warn)"}, "Needs correct keys: without them practice runs once.") : null);
  } else if (W.step === 4) {
    const b = a.blocks;
    put(page, h("div", {class: "wiz-row"},
      num("Number of blocks", () => b.count, (v) => b.count = Math.max(1, Math.round(+v || 1))),
      num("Each stimulus appears, per block (times)", () => b.repeats, (v) => b.repeats = Math.max(1, Math.round(+v || 1)))),
      h("div", {class: "field"}, h("label", {}, "Order within a block"), (() => { const sel = h("select", {onchange: (e) => { b.order = e.target.value; wizPreview(); }},
        [["random", "random (shuffled)"], ["sequential", "as listed"], ["fullrandom", "fully random across repeats"]].map(([v, l]) => { const o = h("option", {value: v}, l); if (b.order === v) o.selected = true; return o; })); return sel; })()),
      b.count > 1 ? text("Text on the break screen between blocks", () => b.break_text, (v) => b.break_text = v, "Take a short break. Press SPACE when ready.") : null,
      text("Instructions (empty = written for you from your answers)", () => a.instructions, (v) => a.instructions = v, "", 3),
      text("Goodbye text", () => a.thanks, (v) => a.thanks = v, "Thank you! You're done."));
  } else if (W.step === 5) {
    const opts = [["sim_eyetracker", "Eye tracker", "simulated for now; switch to Tobii or Gazepoint in the device settings"],
      ["sim_eeg", "EEG", "simulated for now; switch to g.tec or an LSL stream"], ["lsl_markers", "LSL markers", "send every event to LabRecorder"],
      ["ttl_loopback", "Trigger box (TTL)", "simulated for now; switch to serial TTL or parallel port"]];
    put(page, h("h4", {}, "Questionnaires"), h("div", {class: "help"}, "Consent and demographics come before the task, the others after it. Each is a validated, scored instrument; edit them later in the survey editor."));
    const qbox = h("div", {class: "wiz-qs"});
    let cat = null;
    for (const ins of S.schema.survey.library) {
      if (ins.category !== cat) { cat = ins.category; put(qbox, h("div", {class: "wiz-qcat"}, cat)); }
      const cb = h("input", {type: "checkbox", onchange: (e) => { a.questionnaires = e.target.checked ? [...a.questionnaires, ins.id] : a.questionnaires.filter((x) => x !== ins.id); wizPreview(); }});
      cb.checked = a.questionnaires.includes(ins.id);
      put(qbox, h("label", {class: "wiz-check", title: ins.description}, cb, " ", h("b", {}, ins.title), h("small", {}, `  ${ins.items} items · ~${ins.minutes} min`)));
    }
    put(page, qbox, h("h4", {}, "Devices"));
    put(page, h("div", {class: "help"}, "Optional. Everything works without hardware; devices can be added or changed later."));
    for (const [type, label, sub] of opts) {
      const cb = h("input", {type: "checkbox", onchange: (e) => { a.devices = e.target.checked ? [...a.devices, type] : a.devices.filter((x) => x !== type); wizPreview(); }});
      cb.checked = a.devices.includes(type);
      put(page, h("label", {class: "wiz-check"}, cb, " ", h("b", {}, label), h("small", {}, "  " + sub)));
    }
  }
  put(body, page);
  W.preview = h("div", {class: "wiz-preview"}, "…");
  put(body, W.preview);
  put(body, h("div", {class: "btns wiz-btns"},
    h("button", {onclick: closeModal}, "Cancel"), h("span", {style: "flex:1"}),
    W.step > 0 ? h("button", {onclick: () => { W.step--; renderWizard(); }}, "← Back") : null,
    W.step < WIZ_STEPS.length - 1 ? h("button", {class: "primary", onclick: () => { W.step++; renderWizard(); }}, "Next →") : null,
    h("button", {class: W.step === WIZ_STEPS.length - 1 ? "primary" : "accent", onclick: createFromWizard}, "Create experiment")));
  openModal(); wizPreview();
}

function wizardAnswers() {
  const a = clone(W.a);
  for (const k of ["stimulus_duration", "response_deadline"]) if (a.timing[k] === "") a.timing[k] = "none";
  if (a.response.kind !== "keys") a.stimulus.items.forEach((it) => delete it.correct);
  return a;
}
let _wizT = null;
function wizPreview() {
  clearTimeout(_wizT);
  _wizT = setTimeout(async () => {
    if (!W.preview) return;
    try {
      const r = await api("/api/wizard", {answers: wizardAnswers()});
      W.preview.className = "wiz-preview" + (r.ok ? "" : " bad");
      W.preview.textContent = r.ok ? `This makes ${r.estimate.text}: ${describeWizardFlow(r.experiment)}` : "⚠ " + r.error;
    } catch (e) { W.preview.textContent = e.message; }
  }, 250);
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
  const slug = (a.name || "my_experiment").trim().replace(/[^0-9A-Za-z_]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase() || "my_experiment";
  let name = slug, n = 2;
  const files = (await api("/api/files")).files.map((f) => f.path);
  while (files.includes(`${name}/${name}.yaml`)) name = `${slug}_${n++}`;
  a.name = name;
  let r;
  try { r = await api("/api/wizard", {answers: a, save_as: `${name}/${name}.yaml`}); } catch (e) { return toast(e.message, 5000); }
  if (!r.ok) return toast(r.error, 5000);
  closeModal(); clearDraft();
  await openFile(r.path, {silent: true});
  S.view = "story"; renderAll();
  toast(`Created ${r.path}: ${r.estimate.text}. Checking it with a virtual participant…`, 5000);
  await dryRun();
  if (a.stimulus.kind === "picture") toast(`Put your pictures in ${name}/images/ (the names in the trial list must match)`, 8000);
}

/* ================================================================== Try it */
const P = {on: false, sound: 0, scale: 1, size: [1280, 720], audio: null, imgs: {}, keysDown: new Set()};
const KEYMAP = {" ": "space", "Enter": "return", "ArrowLeft": "left", "ArrowRight": "right", "ArrowUp": "up", "ArrowDown": "down",
  "Escape": "escape", "Backspace": "backspace", "Tab": "tab", "Shift": "lshift", "Control": "lctrl", "Alt": "lalt"};

function tryIt() {
  const routineHere = S.view === "screen" && S.routine;
  const body = $("#modal-body"); body.innerHTML = ""; body.className = "";
  put(body, h("h3", {}, "Try it yourself"),
    h("p", {}, "The experiment runs right here in the builder with the real engine. Respond as a participant would: press the keys, click, rate. Hardware is simulated and the data goes to the test-run folder."),
    h("div", {class: "choice", onclick: () => { closeModal(); startPlay(null); }}, h("b", {}, "▶ The whole experiment"), h("small", {}, "from the first screen to the last")),
    routineHere ? h("div", {class: "choice", onclick: () => { closeModal(); startPlay(S.routine); }}, h("b", {}, `▶ Just the screen “${S.routine}”`), h("small", {}, "5 trials with real values from its trial list")) : null,
    h("p", {class: "help"}, "Press Esc to stop at any time. Timing in a browser is approximate; for real data use “Run with a participant”."));
  openModal();
}

async function startPlay(routine) {
  let r;
  try { r = await api("/api/play/start", {experiment: S.exp, path: S.path, routine, max_trials: 5}); }
  catch (e) { return toast(e.message, 6000); }
  if (!r.ok) {
    showTab("issues"); validate();
    return toast("Can't start yet: " + (r.error || "fix the problems in the Check tab first"), 7000);
  }
  P.on = true; P.sound = 0; P.size = r.size;
  const el = $("#play"); el.innerHTML = ""; el.classList.remove("hidden");
  const cv = h("canvas", {id: "play-canvas"});
  const frame = h("iframe", {id: "play-page", class: "hidden", title: "web page"});
  put(el, h("div", {class: "play-bar"}, h("b", {}, `Trying “${S.exp.name}”${routine ? ` · screen ${routine}` : ""}`),
    h("span", {class: "help"}, " respond like a participant · Esc stops"), h("span", {style: "flex:1"}),
    h("button", {onclick: stopPlay}, "Stop")),
    h("div", {class: "play-stage"}, cv, frame));
  const fit = () => {
    const stage = el.querySelector(".play-stage"); const [w, hh] = P.size;
    const k = Math.min(stage.clientWidth / w, stage.clientHeight / hh);
    cv.width = Math.round(w * k); cv.height = Math.round(hh * k); P.scale = k;
    frame.style.width = cv.width + "px"; frame.style.height = cv.height + "px";
  };
  fit(); window.addEventListener("resize", fit); P.fit = fit;
  cv.addEventListener("mousedown", (e) => playMouse(e, cv, true));
  cv.addEventListener("mouseup", (e) => playMouse(e, cv, false));
  cv.addEventListener("mousemove", (e) => { if (!P._mv || Date.now() - P._mv > 40) { P._mv = Date.now(); playMouse(e, cv, null); } });
  document.addEventListener("keydown", playKey, true);
  document.addEventListener("keyup", playKey, true);
  playLoop(cv, frame);
}

function playMouse(e, cv, down) {
  const r = cv.getBoundingClientRect();
  const x = (e.clientX - r.left - cv.width / 2) / P.scale, y = -(e.clientY - r.top - cv.height / 2) / P.scale;
  const name = down === null ? "move" : ["left", "middle", "right"][e.button] || "left";
  api("/api/play/input", {kind: "mouse", name, down: down !== false, pos: [x, y]}).catch(() => {});
}
function playKey(e) {
  if (!P.on || e.target?.closest?.("#play-page")) return;
  e.preventDefault(); e.stopPropagation();
  const name = KEYMAP[e.key] || (e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase());
  const down = e.type === "keydown";
  if (down && e.repeat) return;
  if (name === "escape" && down) { stopPlay(); return; }
  api("/api/play/input", {kind: "key", name, down}).catch(() => {});
}

async function playLoop(cv, frame) {
  while (P.on) {
    let f;
    try { f = await api(`/api/play/frame?sound=${P.sound}`); } catch (e) { await new Promise((r) => setTimeout(r, 200)); continue; }
    if (f.drawn) drawPlayFrame(cv, f);
    for (const snd of f.sounds || []) { P.sound = Math.max(P.sound, snd.id); playSound(snd); }
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
  for (const [kind, p] of f.drawn) {
    const [x, y] = p.pos || [0, 0];
    ctx.save(); ctx.translate(x, y); ctx.rotate(-(p.ori || 0) * Math.PI / 180);
    ctx.globalAlpha = Math.max(0, Math.min(1, p.opacity ?? 1));
    if (kind === "text") {
      ctx.scale(1, -1); ctx.fillStyle = cssColor(p.color, "#fff");
      const hgt = p.height || 40; ctx.font = `${p.italic ? "italic " : ""}${p.bold ? "bold " : ""}${hgt}px ${p.font || "sans-serif"}`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
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
function playSound(snd) {
  try {
    const src = snd.source;
    if (typeof src === "number" || /^\d+(\.\d+)?$/.test(String(src))) {
      P.audio ||= new (window.AudioContext || window.webkitAudioContext)();
      const osc = P.audio.createOscillator(), g = P.audio.createGain();
      osc.frequency.value = +src; g.gain.value = 0.2 * (snd.volume ?? 1);
      osc.connect(g).connect(P.audio.destination); osc.start(); osc.stop(P.audio.currentTime + (+snd.tone_duration || 0.3));
    } else {
      const a = new Audio(`/api/file?path=${encodeURIComponent((S.path ? S.path.replace(/[^/]*$/, "") : "") + src)}`); a.volume = Math.min(1, snd.volume ?? 1); a.play();
    }
  } catch { /* sound is best effort in the browser */ }
}

async function stopPlay() {
  if (!P.on) return;
  try { const st = await api("/api/play/stop", {}); finishPlay({...st, running: false}); } catch { finishPlay({running: false}); }
}
function finishPlay(f) {
  if (!P.on) return;
  P.on = false;
  document.removeEventListener("keydown", playKey, true); document.removeEventListener("keyup", playKey, true);
  window.removeEventListener("resize", P.fit);
  const el = $("#play"); el.classList.add("hidden"); el.innerHTML = "";
  const res = f.result || {};
  const body = $("#modal-body"); body.innerHTML = ""; body.className = "";
  const kpi = (v, l) => h("div", {class: "kpi"}, h("b", {}, v), h("span", {}, l));
  put(body, h("h3", {}, f.error ? "The experiment stopped with a problem" : res.aborted ? "Stopped" : "Done!"));
  if (f.error) put(body, h("pre", {class: "issue error", style: "white-space:pre-wrap"}, f.error),
    h("p", {class: "help"}, "The Check tab and the documentation explain most messages. The last lines of the log are below."),
    h("pre", {class: "help", style: "white-space:pre-wrap;max-height:160px;overflow:auto"}, (f.log || []).join("\n")));
  if (res.screens !== undefined) put(body, h("div", {class: "kpis"},
    kpi(res.trials ?? 0, "trials"), kpi(res.responses ?? 0, "responses"),
    res.accuracy != null ? kpi(Math.round(res.accuracy * 100) + "%", "correct") : null,
    res.mean_rt != null ? kpi(Math.round(res.mean_rt * 1000) + " ms", "mean response time") : null),
    h("p", {class: "help"}, res.note || ""));
  put(body, h("div", {class: "btns"}, h("button", {class: "primary", onclick: () => { closeModal(); tryIt(); }}, "Try again"),
    h("button", {onclick: () => { closeModal(); D.dry = true; D.sel = null; showTab("data"); }}, "See the data"),
    h("button", {onclick: closeModal}, "Close")));
  openModal();
}

/* ================================================================== run with a participant */
async function runDialog() {
  if (!S.path || S.dirty) { await save(); if (!S.path) return; }
  const errors = (S.issues || []).filter((i) => i.level === "error");
  if (errors.length) { showTab("issues"); return toast(`Fix ${errors.length} problem(s) in the Check tab first`, 5000); }
  let info = {suggestion: "001", used: [], data_dir: "data"};
  try { info = await api(`/api/next_participant?path=${encodeURIComponent(S.path)}`); } catch { /* keep defaults */ }
  const hasDevices = S.exp.devices.length > 0;
  const body = $("#modal-body"); body.innerHTML = ""; body.className = "rundlg";
  const pid = h("input", {value: info.suggestion});
  const warn = h("div", {class: "help"});
  const checkPid = () => { warn.textContent = info.used.includes(pid.value.trim()) ? `⚠ Participant ${pid.value} already has data. A new session folder will be made, nothing is overwritten.` : ""; warn.style.color = "var(--warn)"; };
  pid.oninput = checkPid; checkPid();
  const ses = h("input", {value: "1"});
  const hw = h("select", {}, h("option", {value: "real"}, "Real devices"), h("option", {value: "sim"}, "Simulated (no hardware connected)"));
  const fs = h("select", {}, h("option", {value: "1"}, "Full screen"), h("option", {value: "0"}, "In a window"));
  if (S.exp.settings.window && S.exp.settings.window.fullscreen === false) fs.value = "0";
  put(body, h("h3", {}, "Run with a participant"),
    h("div", {class: "field"}, h("label", {}, "Participant ID"), pid, warn),
    h("div", {class: "field"}, h("label", {}, "Session"), ses),
    hasDevices ? h("div", {class: "field"}, h("label", {}, `Hardware (${S.exp.devices.map((d) => d.id).join(", ")})`), hw) : null,
    h("div", {class: "field"}, h("label", {}, "Screen"), fs),
    h("p", {class: "help"}, `The experiment opens in its own window on this computer. Data is saved to ${info.data_dir}/ as it runs; press Esc in the experiment window to stop early (everything so far is kept).`),
    h("div", {class: "btns"}, h("button", {onclick: closeModal}, "Cancel"),
      h("button", {class: "primary", onclick: () => startRun(pid.value.trim(), ses.value.trim(), hasDevices && hw.value === "sim", fs.value === "1")}, "Start")));
  openModal(); pid.focus(); pid.select();
}

async function startRun(participant, session, simulate, fullscreen) {
  if (!participant) return toast("Enter a participant ID");
  const {run_id} = await api("/api/run", {path: S.path, participant: {participant, session: session || "1"}, simulate, fullscreen});
  const body = $("#modal-body"); body.innerHTML = ""; body.className = "rundlg";
  const status = h("div", {class: "run-status"}, "Starting…");
  const log = h("pre", {class: "run-log"});
  put(body, h("h3", {}, `Participant ${participant}, session ${session || 1}`), status, log,
    h("div", {class: "btns"}, h("button", {onclick: closeModal}, "Hide (keeps running)")));
  openModal();
  const poll = async () => {
    let st; try { st = await api(`/api/run_status?id=${run_id}`); } catch { return; }
    log.textContent = st.output.slice(-14).join("\n");
    if (st.running) { status.textContent = "Running: the experiment window is open."; setTimeout(poll, 800); return; }
    const saved = st.output.find((l) => l.startsWith("Saved to "));
    const why = st.output.find((l) => l.startsWith("EDGE could not run"));
    if (why) { status.innerHTML = ""; put(status, h("b", {style: "color:var(--err)"}, "Could not start."), h("div", {}, why.replace("EDGE could not run the experiment: ", "")));
      body.querySelector(".btns").replaceChildren(h("button", {onclick: () => runDialog()}, "Try again"), h("button", {onclick: closeModal}, "Close")); return; }
    status.innerHTML = "";
    put(status, st.returncode === 0 ? h("b", {class: "ok"}, "✓ Finished.") : h("b", {style: "color:var(--warn)"}, st.returncode === 1 ? "Stopped early (data so far is saved)." : `Ended with a problem (code ${st.returncode}).`),
      saved ? h("div", {}, saved) : null);
    body.querySelector(".btns").replaceChildren(h("button", {class: "primary", onclick: () => { closeModal(); D.dry = false; D.sel = null; showTab("data"); }}, "See the data"),
      h("button", {onclick: () => runDialog()}, "Next participant"), h("button", {onclick: closeModal}, "Close"));
  };
  poll();
}
