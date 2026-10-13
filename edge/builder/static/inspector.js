/* inspector.js: the inspector, i.e. the Properties column of Build (SPEC W8, §7.5.5). Owner: P4b.
 * Owns renderProps() for every selection kind: an item (component), a screen (routine), a trial list (loop), an
 * if / otherwise (branch), a workflow and its phases (machine, state), a device, and nothing selected (the
 * experiment overview with "Next steps"). It fills #props-title (.insp-head), #props (.insp-sec sections whose field
 * rows carry data-prop) and #props-foot (Duplicate / Delete). Also here: field() with the value-source token
 * (.srcbtn: same on every trial, from the trial list, new trial-list column, formula) and the bound-column chip
 * (.colchip), "More options · N set", trial-list columns (addTrialColumn), routes and rules editors, the read-only
 * state while the assistant's changes are previewed, deviceTestBox() (also used by the Test page), and the $variable
 * suggestions (updateExprVars). The Experiment settings dialog is openSettings() further down (W13).
 */
"use strict";

/* ================================================================== property tables */
const BASIC_PROPS = {
  text: ["text", "color", "height", "pos"], image: ["image", "size", "pos"], shape: ["shape", "size", "fill", "pos"],
  fixation: ["size", "fill"], sound: ["sound", "volume"], html: ["file", "html"], survey: ["questions", "title"], keyboard: ["keys", "correct"],
  device_response: ["device", "inputs", "correct", "keys"],
  mouse: ["clickable", "correct"], slider: ["ticks", "labels"], gaze_roi: ["target", "pos", "radius", "dwell"],
  gaze_follow: ["target"], calibrate: ["device"], marker: ["label"], variable: ["set", "when"], wait: [],
};
const BASIC_TIMING = ["start", "duration", "end_routine"];
/* Human names of the timing fields (also used by friendlyWhere() in app.js for problem locations). */
const FIELD_LABELS = {start: "Starts at", duration: "Lasts", end_routine: "Ends the screen", if: "Only if",
  start_after: "Starts after", start_if: "Starts when", stop_if: "Stops when", start_frame: "Starts on frame",
  duration_frames: "Lasts (frames)", disabled: "Turned off", save: "Save its results"};

const SCHED_FIELDS = {
  start: {type: "float", default: 0, unit: "s", help: "Seconds after the screen appears."},
  duration: {type: "float", default: null, unit: "s", placeholder: "to the end", help: "Empty: until the screen ends."},
  start_after: {type: "component", default: null, help: "Start when this item stops."},
  start_if: {type: "expr", default: null, help: "Start when this becomes true."},
  stop_if: {type: "expr", default: null, help: "Stop when this becomes true."},
  start_frame: {type: "int", default: null, help: "Start on this screen refresh (overrides “Starts at”)."},
  duration_frames: {type: "int", default: null, help: "Length in screen refreshes (overrides “Lasts”)."},
  end_routine: {type: "bool", default: false, help: "Move on when this gets a response or times out"},
  if: {type: "expr", default: null, help: "Include it only when this is true."},
  disabled: {type: "bool", default: false, help: "Kept in the file, but not shown or run."},
  save: {type: "bool", default: true, help: "Save what it records in the data file."},
};
const SCHED_KEYS = new Set(["id", "type", ...Object.keys(SCHED_FIELDS)]);

/* Plain names and help for properties ([label, help]); "type.prop" overrides "prop". Expert also shows the file key. */
const PROP_WORDS = {
  text: ["Text", "What to show."], color: ["Colour"], height: ["Letter height"], font: ["Font"], bold: ["Bold"], italic: ["Italic"],
  wrap_width: ["Line width before wrapping", "Empty: 90 % of the window."], direction: ["Text direction"], pos: ["Position"],
  opacity: ["Opacity", "0 is invisible, 1 is fully visible."], ori: ["Rotation", "Degrees, clockwise."],
  units: ["Units", "Empty: the experiment's units."], marker: ["Event marker", "Sent to every device when this starts."],
  keys: ["Keys", "Keys that count as an answer. None: any key."], store: ["Keep which key"], correct: ["Correct answer"],
  discard_previous: ["Ignore keys pressed before it starts"], record_release: ["Also save when keys are released"],
  response_marker: ["Marker at the response", "Sent to every device at the moment of the response."],
  image: ["Picture"], size: ["Size"], sound: ["Sound"], volume: ["Volume"], tone_duration: ["Tone length"],
  shape: ["Shape"], fill: ["Fill colour"], line_color: ["Line colour"], line_width: ["Line width"], radius: ["Radius"],
  vertices: ["Corners"], ticks: ["Points on the scale", "The first and the last are the ends of the scale."],
  labels: ["Labels", "Spread along the scale, separated by commas."], granularity: ["Step", "0: any value along the line."],
  marker_color: ["Marker colour"], require_confirm: ["Confirm with Enter or Space"], file: ["Web page"],
  html: ["Page content (HTML)", "Used when no web page file is chosen."], display: ["Show it in"], fullscreen: ["Full screen"],
  continue_button: ["Continue button"], continue_label: ["Continue button text"], questions: ["Questions"], title: ["Title"],
  language: ["Language", "Translates the buttons and messages, e.g. en, de, es, fr."], intro: ["Instructions on the first page"],
  progress_bar: ["Progress bar"], allow_back: ["Participants can go back"], submit_label: ["Last button text"],
  next_label: ["Next button text"], back_label: ["Back button text"], scores: ["Scores"], css: ["Extra CSS"],
  device: ["Device", "Empty: the first one that fits."], inputs: ["Inputs that count", "Separated by commas. None: any input."],
  buttons: ["Buttons that count"], clickable: ["Clickable items", "Names of items on this screen, separated by commas."],
  track: ["Save the mouse path"], target: ["Area of", "Use another item's area, e.g. a picture."],
  dwell: ["Dwell time", "Seconds of looking that complete it. Empty: entering is enough."], show: ["Show the area (for testing)"],
  set: ["Set", "The new value of each variable; a value can be a formula."], when: ["When"],
  on_begin: ["Code when the screen starts"], on_frame: ["Code on every screen refresh"], on_end: ["Code when the screen ends"],
  label: ["Marker label"], "mouse.correct": ["Correct item", "The name of the item that is the right answer."],
  "device_response.keys": ["Keys that also count", "For Try it and piloting without the device: key, then the input it stands for."],
  "sound.sound": ["Sound", "A sound file, or a tone (a number in Hz)."], "fixation.size": ["Size"],
};
const CHOICE_WORDS = {auto: "Automatic", ltr: "Left to right", rtl: "Right to left", first: "The first", last: "The last", all: "All of them",
  start: "At the start", end: "At the end", webview: "An app window", browser: "The web browser", yes: "Yes", no: "No",
  circle: "Circle", rect: "Rectangle", select: "Select", average: "Average of both eyes", left: "Left eye", right: "Right eye"};
const SECONDS_PROPS = new Set(["dwell", "tone_duration"]);
const UNIT_WORDS = {px: "px", norm: "", height: "", deg: "°"};

/* ================================================================== module state */
const INSP = {
  seq: 0,
  openMore: new Set(),        // "More options" rows that are open (per kind)
  formulaFor: null,           // a field switched to "Formula" before anything was typed
  focus: null,                // data-fkey to focus after the next render
  base: null,                 // the base document while the assistant's changes are previewed
  lastSel: "",
};

/* ================================================================== small helpers */
const inspAssistant = () => (window.Assistant || (typeof Assistant !== "undefined" ? Assistant : null));
const inspEditable = () => { if (S.proposal) { toast("Apply or discard the assistant's changes first"); return false; } return true; };
const inspCapWords = (k) => { const s = String(k).replace(/_/g, " "); return s.charAt(0).toUpperCase() + s.slice(1); };
const inspCatClass = (type) => {
  if (typeof catKey === "function") return catKey(type);
  return {stimulus: "show", response: "respond", eyetracking: "eye", hardware: "hw", logic: "logic"}[S.schema?.components?.[type]?.category] || "logic";
};
const inspTypeIcon = (type) => (typeof TYPE_ICON !== "undefined" && TYPE_ICON[type]) || "screen";
const inspDeviceIcon = (d) => (typeof deviceIcon === "function" ? deviceIcon(d) : (typeof DEVICE_ICON !== "undefined" && DEVICE_ICON[d?.type]) || "device");
const inspDeviceWords = (d) => (typeof deviceLabel === "function" ? deviceLabel(d) : d.type);
const inspInWords = (v, kind) => { try { return typeof exprInWords === "function" ? exprInWords(v, kind) : ""; } catch { return ""; } };
const inspPlural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
/* Deletions happen at once, with an undo toast (SPEC §2.9). */
function inspUndoToast(msg) {
  const idx = EDGE.historyIndex();
  ui.toast(msg, {action: {label: "Undo", run: () => { if (!EDGE.undoIf(idx)) toast(`Other changes came after this one: use Undo in the toolbar (${MOD}+Z).`); }}});
}
/* Commit after the browser has moved focus (Tab), so the re-render can give focus back to the next field. */
const inspLater = (fn) => setTimeout(fn, 0);
function inspPropWords(name, type) {
  const w = PROP_WORDS[`${type}.${name}`] || PROP_WORDS[name] || FIELD_LABELS[name] && [FIELD_LABELS[name]] || [inspCapWords(name)];
  return {label: w[0], help: w[1] || ""};
}
/* A value for people: formulas in words in Simple, raw otherwise. */
function inspValueWords(v) {
  if (v === null || v === undefined || v === "") return "empty";
  if (isExpr(v)) return isSimple() ? (inspInWords(v) || "a formula") : v;
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/* ================================================================== renderProps: the inspector for S.sel */
function renderProps() {
  const insp = $("#inspector"), el = $("#props"), title = $("#props-title"), foot = $("#props-foot");
  if (!insp || !el || !S.exp || !S.schema) return;
  updateExprVars();
  // keep focus (and anything typed but not yet committed) across the re-render
  const a = document.activeElement;
  const keepKey = INSP.focus || (a && insp.contains(a) ? a.dataset?.fkey : null);
  const typed = a && insp.contains(a) && a.dataset?.fkey && ("value" in a) && a.value !== a.defaultValue && !INSP.focus
    ? {value: a.value, start: a.selectionStart, end: a.selectionEnd} : null;
  const selKey = JSON.stringify(S.sel ?? null);
  const sameSel = selKey === INSP.lastSel;
  const scroll = sameSel ? el.scrollTop : 0;
  INSP.lastSel = selKey;
  INSP.focus = null;
  INSP.base = null;
  if (S.proposal) { try { INSP.base = JSON.parse(S._snapshot); } catch { INSP.base = null; } }
  title.replaceChildren(); el.replaceChildren(); foot.replaceChildren();
  insp.classList.toggle("proposed", !!S.proposal);
  const sel = S.sel;
  try {
    if (sel?.kind === "component") renderComponentProps(el, sel);
    else if (sel?.kind === "routine" && S.exp.routines[sel.routine]) renderScreenProps(el, sel.routine);
    else if (sel?.kind === "loop") renderLoopProps(el, getNode(sel.path));
    else if (sel?.kind === "branch") renderBranchProps(el, sel.path);
    else if (sel?.kind === "machine") renderMachineProps(el);
    else if (sel?.kind === "state") renderStateProps(el);
    else if (sel?.kind === "device" && S.exp.devices[sel.index]) renderDeviceProps(el, S.exp.devices[sel.index], sel.index);
    else inspOverview(el);
  } catch (e) {
    console.error(e);
    el.replaceChildren(h("div", {class: "insp-sec"}, h("div", {class: "alert danger"}, icon("error"), h("div", {}, "This can't be shown here.", h("div", {class: "t-caption"}, e.message)))));
  }
  if (S.proposal) inspReadOnly(insp);
  el.scrollTop = scroll;
  if (keepKey) {
    const t = insp.querySelector(`[data-fkey="${CSS.escape(keepKey)}"]`);
    if (t && !t.disabled) {
      if (typed && "value" in t) { t.value = typed.value; try { t.setSelectionRange(typed.start, typed.end); } catch { /* not a text field */ } }
      t.focus({preventScroll: true});
      if (!sameSel) t.scrollIntoView?.({block: "nearest"});
    }
  }
}
/* Kept name: the settings used to be shown in the inspector; they are a dialog now (openSettings). */
function renderSettings(el) { inspOverview(el || $("#props")); }

/* ---------------- header, sections, footer */
function inspHead({tile, ic, over, overClass = "", key = "", name, rename = null, help = null, menu = null}) {
  const title = $("#props-title");
  const nameEl = rename
    ? h("button", {type: "button", class: "insp-name t-title-m", title: `${name} · Rename (F2)`, "aria-label": `${name}. Rename`, "data-fkey": "head:rename", onclick: rename}, name)
    : h("div", {class: "insp-name t-title-m", title: name}, name);
  const menuBtn = menu ? h("button", {type: "button", class: "btn ghost icon sm", "aria-label": "More actions", "data-tip": "More actions", "data-tip-pos": "end",
    "aria-haspopup": "menu", "aria-expanded": "false", "data-fkey": "head:menu", onclick: (e) => ui.menu(e.currentTarget, menu(), {placement: "bottom-end"})}, icon("more")) : null;
  title.replaceChildren(...[
    h("span", {class: "tile " + tile}, icon(ic, "m")),
    h("div", {class: "names"}, h("div", {class: "t-overline " + overClass}, h("span", {class: "ov-t"}, over), key && !isSimple() ? h("span", {class: "key mono"}, key) : null,
      S.proposal ? h("span", {class: "chip assistant", title: "The assistant's proposed version"}, icon("assistant"), "Proposed") : null), nameEl),
    help, menuBtn].filter(Boolean));
}
function inspSec(title, {caption = null, actions = null, cls = ""} = {}) {
  const head = title ? h("div", {class: "sec-head"}, h("h3", {class: "t-title-s"}, title), caption ? h("span", {class: "t-caption"}, caption) : null, actions) : null;
  return h("section", {class: "insp-sec " + cls}, head);
}
function inspFoot(...kids) { $("#props-foot").replaceChildren(...kids.flat().filter(Boolean)); }
/* "More options · N set": properties most people never need, folded away (remembered while the builder is open). */
function moreOptions(items, key, label) {
  const n = items.filter(([, set]) => set).length;
  const open = INSP.openMore.has(key) || !isSimple();
  const id = "more-" + key + "-" + (++INSP.seq);
  const body = h("div", {class: "more-body", id, hidden: open ? null : ""}, items.map(([f]) => f));
  const row = h("button", {type: "button", class: "more-row", "aria-expanded": open ? "true" : "false", "aria-controls": id, "data-fkey": "more:" + key,
    onclick: () => {
      const now = row.getAttribute("aria-expanded") !== "true";
      row.setAttribute("aria-expanded", now ? "true" : "false"); body.hidden = !now;
      if (now) INSP.openMore.add(key); else INSP.openMore.delete(key);
    }}, icon("chev-right", "chev"), label || "More options", n ? h("span", {class: "chip accent"}, `${n} set`) : null);
  return h("div", {class: "more"}, row, body);
}

/* ---------------- read-only while the assistant's changes are previewed (W8, W16) */
function inspReadOnly(insp) {
  const note = h("div", {class: "insp-proposed-note alert assistant"}, icon("assistant"), h("div", {}, "Apply the assistant's changes to edit this."));
  $("#props").prepend(note);
  for (const x of insp.querySelectorAll("input, select, textarea, button")) {
    if (x.classList.contains("help-link") || x.closest(".insp-keep")) continue;
    x.disabled = true;
    x.title = x.title || "Apply or discard the assistant's changes first";
  }
}
/* "~~0.5 s~~ → random 0.3–0.7 s" under a field the assistant changed. */
function inspWasLine(before, after) {
  return h("div", {class: "was", "aria-label": `Changed from ${inspValueWords(before)} to ${inspValueWords(after)}`},
    h("s", {}, inspValueWords(before)), icon("chev-right"), h("b", {}, inspValueWords(after)));
}

/* ================================================================== field(): one property row */
function setProp(obj, k, v, label) {
  if (v === null || v === undefined || v === "") delete obj[k]; else obj[k] = v;
  commit(label || undefined);
}

function parseVal(type, raw) {
  if (raw === "" || raw === null || raw === undefined) return null;
  if (typeof raw === "string" && isExpr(raw)) return raw;
  switch (type) {
    case "float": { const n = Number(String(raw).replace(",", ".")); return isNaN(n) ? raw : n; }
    case "int": { const n = Number(String(raw).trim().replace(",", ".")); return Number.isInteger(n) ? n : raw; }
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

/* The trial-list column a value is bound to ("$word" -> "word"), when the screen's trial list has that column. */
function inspBoundColumn(v, cols) {
  if (!isExpr(v)) return null;
  const s = String(v).trim();
  return /^\$[A-Za-z_]\w*$/.test(s) && cols.includes(s.slice(1)) ? s.slice(1) : null;
}
/* "RED, GREEN, BLUE": a few values of a column from the trial lists around the screen. */
function inspColumnExamples(rid, col, n = 3) {
  const vals = [];
  try {
    for (const lp of (rid ? enclosing(rid).loops : [])) {
      const rows = typeof loopRowsFor === "function" ? loopRowsFor(lp) : Array.isArray(lp.conditions) ? lp.conditions : null;
      for (const r of rows || []) { const v = r && r[col]; if (v !== undefined && v !== null && v !== "" && !vals.includes(String(v))) vals.push(String(v)); }
    }
  } catch { /* rows are still loading */ }
  return vals.length ? vals.slice(0, n).join(", ") + (vals.length > n ? ", …" : "") : "";
}

function field(name, p, value, onChange, opts = {}) {
  p = p || {};
  const type = p.type || "str";
  const prop = opts.prop ?? name;
  const id = "f-" + (++INSP.seq);
  const fkey = "f:" + (opts.fkey || prop);
  const words = inspPropWords(name, opts.comp?.type);
  const label = opts.label || words.label;
  const expert = !isSimple();
  let help = opts.help ?? (expert ? (p.help ? cap(p.help) : words.help) : words.help);
  const wrap = h("div", {class: "field", "data-prop": prop});
  const rid = opts.routine ?? (opts.comp ? S.sel?.routine : null) ?? S.routine;
  // Simple: names, list repeats, switches and the screen's maximum length never get a value source
  const sourceable = !!opts.comp && !opts.noExpr && !["expr", "code", "bool", "survey"].includes(type);
  const cols = sourceable ? columnsForScreen(rid) : [];
  const col = inspBoundColumn(value, cols);
  const pendingFormula = INSP.formulaFor === `${JSON.stringify(S.sel)}|${prop}`;
  let source = type === "expr" || type === "code" ? "formula" : !isExpr(value) ? (pendingFormula ? "formula" : "fixed") : col && !pendingFormula ? "column" : "formula";
  if (type === "bool" && !isExpr(value)) source = "fixed";
  const commitValue = (v) => { INSP.formulaFor = null; if (JSON.stringify(v ?? null) !== JSON.stringify(value ?? null)) inspLater(() => onChange(v)); };
  const baseVal = opts.baseValue;
  const changed = opts.hasBase && JSON.stringify(baseVal ?? null) !== JSON.stringify(value ?? null);
  if (changed) wrap.classList.add("changed");

  /* a switch for true / false */
  if (type === "bool" && source === "fixed") {
    const sw = ui.switch(!!(value ?? p.default), (v) => inspLater(() => onChange(v)), {label, caption: opts.caption ?? help, id});
    sw.switchButton.dataset.fkey = fkey;
    wrap.classList.add("switch-field");
    wrap.append(sw);
    if (expert && name !== prop) wrap.append(h("span", {class: "key mono"}, name));
    if (changed) wrap.append(inspWasLine(baseVal, value));
    return wrap;
  }

  /* the label row: label, the file key (Expert), the value-source token */
  const lbl = h("label", {for: id, class: opts.hideLabel ? "sr-only" : null}, label, p.required && !value ? h("span", {class: "req", title: "Needed"}, " *") : null);
  const row = h("div", {class: "lbl-row"}, lbl, expert && opts.key !== false ? h("span", {class: "key mono"}, opts.key || name) : null);
  const srcBtn = sourceable ? inspSourceButton({name, prop, label, type, p, value, col, cols, source, rid, onChange, commitValue}) : null;
  if (opts.hideLabel) { wrap.classList.add("nolabel"); wrap.append(lbl); } else { if (srcBtn) row.append(srcBtn); wrap.append(row); }
  if (changed) wrap.append(inspWasLine(baseVal, value));

  let input;
  const commitText = (raw) => {
    if (type === "expr" && raw && !raw.trim().startsWith("$")) raw = "$" + raw.trim();
    const v = source === "formula" && type !== "expr" && type !== "code" ? (raw.trim() ? (raw.trim().startsWith("$") ? raw.trim() : "$" + raw.trim()) : null) : parseVal(type, raw);
    // a number field never stores text: "0,3s" or "half a second" would only fail when the experiment runs
    if ((type === "float" || type === "int") && typeof v === "string" && !isExpr(v)) {
      toast(`“${raw.trim()}” isn't ${type === "int" ? "a whole number" : "a number"}. Type ${type === "int" ? "e.g. 3" : "e.g. 0.3"}, or choose Formula ($…) for a value that changes.`, {tone: "warning", ms: 7000});
      inspLater(() => renderProps());
      return;
    }
    commitValue(v);
  };
  if (type === "survey" && typeof surveySummary === "function") {
    input = surveySummary(value, onChange);
  } else if (source === "column") {
    input = inspColChip(col, rid, () => inspToFixed({col, rid, p, onChange}));
  } else if (source === "formula") {
    const multi = type === "code" || type === "text" && String(value ?? "").includes("\n");
    input = multi
      ? h("textarea", {class: "input expr", rows: type === "code" ? 7 : 3, spellcheck: "false", placeholder: type === "code" ? "# Python" : "$ formula",
        onchange: (e) => commitText(e.target.value)}, value ?? "")
      : h("input", {class: "input expr", list: "expr-vars", value: value ?? "", spellcheck: "false", autocomplete: "off",
        placeholder: type === "expr" ? (opts.placeholder || "$ condition, e.g. $score > 5") : "$ formula, e.g. $score + 1",
        onchange: (e) => commitText(e.target.value)});
    if (type !== "code") {
      const say = h("div", {class: "say"});
      const field = input;     // the real <input>/<textarea>: `input` becomes the wrapper below
      const kind = type === "expr" ? "condition" : "value";
      const upd = () => {
        const v = String(field.value || "").trim();
        let w = v ? inspInWords(v.startsWith("$") ? v : "$" + v, kind) : "";
        if (w === "a computed value") w = "";
        if (w && kind === "value") w = `${name === "text" ? "Shows" : "Uses"} ${w}`;
        say.textContent = w && w !== v ? `In words: ${w}.` : ""; say.hidden = !say.textContent;
      };
      field.addEventListener("input", upd); upd();
      input = h("div", {class: "expr-wrap"}, field, say);
    }
  } else if (!opts.readonlyClick && typeof stageInput === "function" && (input = stageInput(name, p, value, onChange, {...opts, id}))) {
    // a picker, slider, colour swatches, X/Y or the file card (widgets.js)
  } else if (type === "choice") {
    const choices = p.choices || [];
    input = h("select", {class: "input", onchange: (e) => commitValue(e.target.value === "" ? null : e.target.value)},
      choices.map((c) => { const o = h("option", {value: c}, c === "" ? "(default)" : (isSimple() && CHOICE_WORDS[c]) || c); if ((value ?? p.default) === c) o.selected = true; return o; }));
  } else if (type === "list" && name === "keys" && opts.comp?.type === "keyboard") {
    input = inspKeyChips(value, (v) => commitValue(v), id);
  } else if (type === "dict" && (name === "set" || name === "keys" || name === "code_map") && (value === undefined || value === null || (typeof value === "object" && !Array.isArray(value)))) {
    input = inspKvEditor(value || {}, (v) => commitValue(Object.keys(v).length ? v : null), {
      keyLabel: name === "keys" ? "Key" : name === "code_map" ? "Marker" : "Variable", valueLabel: name === "keys" ? "Counts as" : name === "code_map" ? "Code" : "New value",
      add: name === "keys" ? "Add a key" : name === "code_map" ? "Add a marker" : "Add a variable"});
  } else if (type === "text" || type === "code" || type === "dict" || type === "json") {
    const mono = type !== "text";
    input = h("textarea", {class: "input" + (mono ? " mono" : ""), rows: type === "code" ? 7 : 3, dir: mono ? null : "auto", spellcheck: mono ? "false" : null,
      onchange: (e) => commitText(e.target.value)}, showVal(type, value));
  } else if (type === "device" || type === "component") {
    const list = type === "device" ? S.exp.devices.map((d) => d.id) : comps(rid).map((c) => c.id).filter((x) => x !== opts.comp?.id);
    input = h("select", {class: "input", onchange: (e) => commitValue(e.target.value || null)},
      h("option", {value: ""}, type === "device" ? "Automatic" : "None"),
      list.map((o) => { const op = h("option", {value: o}, o); if (value === o) op.selected = true; return op; }),
      value && !list.includes(value) ? h("option", {value, selected: ""}, `${value} (missing)`) : null);
  } else if (opts.readonlyClick) {
    input = h("input", {class: "input", value: value ?? "", readonly: "", onclick: opts.readonlyClick});
  } else {
    const num = type === "float" || type === "int";
    const unit = opts.unit ?? p.unit ?? (SECONDS_PROPS.has(name) ? "s" : p.length ? UNIT_WORDS[typeof compUnits === "function" ? compUnits(opts.comp) : "px"] : "");
    const inp = h("input", {class: "input" + (num ? " num" : ""), value: showVal(type, value), dir: num ? null : "auto", inputmode: num ? "decimal" : null,
      placeholder: opts.placeholder ?? p.placeholder ?? (p.default != null && p.default !== "" ? showVal(type, p.default) : ""), onchange: (e) => commitText(e.target.value)});
    input = unit ? h("div", {class: "input-wrap"}, inp, h("span", {class: "suffix"}, unit)) : inp;
  }
  // label the control, and give it a focus key so it keeps focus when the inspector re-renders
  const ctl = input && (input.matches?.("input, select, textarea") ? input
    : input.querySelector?.("input:not([type=hidden]):not([tabindex='-1']), select, textarea") || input.querySelector?.("button"));
  if (ctl) { if (!ctl.id) ctl.id = id; else lbl.htmlFor = ctl.id; if (!ctl.dataset.fkey) ctl.dataset.fkey = fkey; }
  else lbl.removeAttribute("for");
  if (pendingFormula && ctl) INSP.focus = fkey;
  if (opts.hideLabel && srcBtn) input = h("div", {class: "ctl-row"}, input, srcBtn);
  wrap.append(input);
  if (help && source !== "column") wrap.append(h("div", {class: "help"}, help));
  else if (source === "column") wrap.append(h("div", {class: "help"}, "Each trial uses its own value from the trial list."));
  return wrap;
}

/* The value-source token and its menu (W8): same on every trial · from the trial list ▸ · new column… · formula. */
function inspSourceButton({name, prop, label, type, p, value, col, cols, source, rid, onChange, commitValue}) {
  const words = {fixed: "Same on every trial", column: "Trial list", formula: "Formula"}[source];
  const b = h("button", {type: "button", class: "srcbtn " + source, "aria-haspopup": "menu", "aria-expanded": "false", "data-fkey": "src:" + prop,
    "aria-label": `${label}: ${source === "fixed" ? "the same on every trial" : source === "column" ? `from the trial list column “${col}”` : "a formula"}. Change where the value comes from`,
    title: "Where the value comes from"},
  source === "column" ? icon("loop") : source === "formula" ? icon("code") : null, words);
  b.onclick = () => {
    if (!inspEditable()) return;
    const items = [{head: "Value comes from"},
      {label: "Same on every trial", checked: source === "fixed", run: () => (source === "fixed" ? null : inspToFixed({col, rid, p, onChange, value, source}))},
      cols.length ? {label: "From the trial list", checked: source === "column", items: cols.map((c) => {
        const ex = inspColumnExamples(rid, c, 2);
        return {label: ex ? `${c} · e.g. ${ex}` : c, checked: col === c, run: () => commitValue("$" + c)};
      })} : {label: "From the trial list", disabled: true, title: "This screen isn't repeated by a trial list yet: choose “New trial-list column…”"},
      {label: "New trial-list column…", icon: "plus", run: async () => {
        const c = await addTrialColumn(name, isExpr(value) ? "" : value);
        if (c) onChange("$" + c);
      }},
      ...inspFeedbackPreset({name, type, rid, commitValue}),
      {label: "Formula ($…)", checked: source === "formula", run: () => {
        if (source === "formula") return;
        // empty, or already a formula such as $word (a column): edit it as a formula, nothing changes until typed
        if (value === null || value === undefined || value === "" || isExpr(value)) { INSP.formulaFor = `${JSON.stringify(S.sel)}|${prop}`; renderProps(); return; }
        commitValue(typeof value === "number" ? "$" + value : "$" + JSON.stringify(typeof value === "string" ? value : value));
      }}];
    ui.menu(b, items, {placement: "bottom-end"});
  };
  return b;
}
/* The response that a feedback screen is about: the last response with a correct answer at or before this screen. */
function inspScoredResponse(rid) {
  const order = typeof routineInFlowOrder === "function" ? routineInFlowOrder() : Object.keys(S.exp.routines);
  const upto = order.includes(rid) ? order.slice(0, order.indexOf(rid) + 1) : order;
  let hit = null;
  for (const r of upto) for (const c of S.exp.routines[r]?.components || [])
    if (["keyboard", "mouse", "device_response"].includes(c.type) && c.correct !== undefined && c.correct !== null && c.correct !== "") hit = c.id;
  return hit;
}
/* "Depends on whether the response was correct": Correct!/Wrong! feedback without typing a formula. */
function inspFeedbackPreset({name, type, rid, commitValue}) {
  const isText = name === "text" && (type === "str" || type === "text");
  const isColour = type === "color" || /colou?r$|^fill$/.test(name);
  if (!isText && !isColour) return [];
  const resp = inspScoredResponse(rid);
  if (!resp) return [];
  const v = isText ? `$"Correct!" if ${resp}.corr else "Wrong!"` : `$"#55dd55" if ${resp}.corr else "#ff5555"`;
  return [{label: `Depends on whether “${resp}” was correct`, icon: "check", title: isText ? "Shows “Correct!” or “Wrong!”: change the words in the formula" : "Green when correct, red when wrong",
    run: () => commitValue(v)}];
}
/* Back to "the same on every trial": a bound column keeps the current row's value. */
function inspToFixed({col, rid, p, onChange}) {
  INSP.formulaFor = null;
  let v = p?.default ?? null;
  if (col) { const row = typeof sampleRowFor === "function" ? sampleRowFor(rid) : {}; if (row[col] !== undefined) v = row[col]; }
  onChange(v);
}
/* The bound-value chip: [table] word   RED, GREEN, BLUE   ×  (click opens the Trial list view at that column). */
function inspColChip(col, rid, unbind) {
  const ex = inspColumnExamples(rid, col);
  return h("div", {class: "colchip"},
    h("button", {type: "button", class: "cc-open", "data-fkey": "col:" + col, title: "Open the trial list at this column",
      "aria-label": `From the trial list column “${col}”${ex ? `, for example ${ex}` : ""}. Open the trial list`, onclick: () => selectLoopWithColumn(col)},
    icon("table"), h("b", {}, col), ex ? h("span", {class: "eg"}, ex) : null),
    h("button", {type: "button", class: "cc-x", "aria-label": `Use the same value on every trial instead of “${col}”`, title: "Same on every trial", onclick: () => { if (inspEditable()) unbind(); }}, icon("close")));
}
/* Keys as chips: r × g × b × [+ key]; pressing a key while the box is focused adds it. */
function inspKeyChips(value, onChange, id) {
  const keys = Array.isArray(value) ? value.map(String) : typeof value === "string" && value ? value.split(/[\s,]+/).filter(Boolean) : [];
  const keyName = (e) => (typeof KEYMAP !== "undefined" && KEYMAP[e.key]) || (e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase());
  const add = h("input", {class: "kc-add", id, placeholder: keys.length ? "+ key" : "Press a key to add it", "aria-label": "Add a key: press it", readonly: "",
    onkeydown: (e) => {
      if (e.key === "Tab" || e.key === "Escape") return;
      if (e.key === "Backspace" && keys.length) { e.preventDefault(); onChange(keys.slice(0, -1)); return; }
      if (e.ctrlKey || e.metaKey || e.altKey || ["Shift", "Control", "Alt", "Meta", "CapsLock"].includes(e.key)) return;
      e.preventDefault();
      const k = keyName(e);
      if (!keys.includes(k)) onChange([...keys, k]);
    }});
  return h("label", {class: "keychips input", for: id},
    keys.map((k, i) => h("span", {class: "chip"}, h("span", {class: "mono"}, k),
      h("button", {type: "button", class: "x", tabindex: "-1", "aria-label": `Remove the key ${k}`,
        // focus stays in the key box (not <body>), so a following Backspace removes a key, never the whole item
        onclick: () => { add.focus({preventScroll: true}); onChange(keys.filter((_, j) => j !== i)); }}, icon("close")))),
    add);
}
/* A small two-column table for {name: value} settings (variables, keys, marker codes). */
function inspKvEditor(obj, onChange, {keyLabel = "Name", valueLabel = "Value", add = "Add", parse = (v) => parseVal("float", v), mono = true, fixedKeys = []} = {}) {
  const rows = Object.entries(obj || {});
  const out = () => Object.fromEntries(rows.filter(([k]) => k));
  const tbl = h("table", {class: "grid kv"}, h("thead", {}, h("tr", {}, h("th", {}, keyLabel), h("th", {}, valueLabel), h("th", {class: "x"}, h("span", {class: "sr-only"}, "Remove")))));
  const body = h("tbody");
  rows.forEach(([k, v], i) => {
    const locked = fixedKeys.includes(k);
    const kIn = h("input", {class: "input" + (mono ? " mono" : ""), value: k, "aria-label": keyLabel, readonly: locked ? "" : null, "data-fkey": `kv:${keyLabel}:${i}:k`,
      onchange: (e) => { const nk = e.target.value.trim(); if (nk && nk !== k && rows.some(([x]) => x === nk)) { toast(`There is already “${nk}”.`); e.target.value = k; return; } rows[i] = [nk, rows[i][1]]; inspLater(() => onChange(out())); }});
    const vIn = h("input", {class: "input" + (isExpr(v) ? " expr" : ""), value: typeof v === "object" && v !== null ? JSON.stringify(v) : v ?? "", "aria-label": `${valueLabel} of ${k || "the new row"}`, "data-fkey": `kv:${keyLabel}:${i}:v`,
      onchange: (e) => { rows[i] = [rows[i][0], parse(e.target.value)]; inspLater(() => onChange(out())); }});
    body.append(h("tr", {}, h("td", {}, kIn), h("td", {}, vIn), h("td", {class: "x"}, locked ? null :
      h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Remove ${k || "this row"}`, title: "Remove", onclick: () => { rows.splice(i, 1); inspLater(() => onChange(out())); }}, icon("trash")))));
  });
  tbl.append(body);
  return h("div", {class: "kv-wrap"}, rows.length ? tbl : null,
    h("button", {type: "button", class: "btn sm ghost kv-add", "data-fkey": `kv:${keyLabel}:add`, onclick: () => {
      let n = 1, k = keyLabel === "Key" ? "f" : `${keyLabel.toLowerCase().split(" ")[0]}_${n}`;
      while (rows.some(([x]) => x === k)) k = `${keyLabel.toLowerCase().split(" ")[0]}_${++n}`;
      rows.push([k, keyLabel === "Key" ? "left" : ""]); inspLater(() => onChange(out()));
    }}, icon("plus"), add));
}

/* ================================================================== an item (component) */
function renderComponentProps(el, sel) {
  const c = findComp(sel.routine, sel.id); if (!c) return inspOverview(el);
  const d = S.schema.components[c.type] || {props: {}};
  const cat = inspCatClass(c.type);
  const list = comps(sel.routine); const i = list.indexOf(c);
  const baseComp = INSP.base ? (INSP.base.routines?.[sel.routine]?.components || []).find((x) => x.id === c.id) : null;
  const isNew = INSP.base && !baseComp;
  const rename = () => inspRenameItem(c);
  inspHead({tile: "tint-" + cat, ic: inspTypeIcon(c.type), over: friendlyName(c.type), overClass: "c-" + cat, key: c.type, name: c.id, rename,
    help: helpLink("reference/components", c.type, friendlyName(c.type)),
    menu: () => [
      {label: "Rename…", icon: "design", shortcut: "F2", run: rename},
      {label: "Duplicate", icon: "duplicate", shortcut: `${MOD} D`, run: () => inspDuplicateItem(c)},
      {sep: true},
      {label: "Draw earlier (behind)", icon: "chev-down", shortcut: "Alt ↑", disabled: i <= 0, run: () => inspMoveItem(c, -1)},
      {label: "Draw later (on top)", icon: "chev-down", shortcut: "Alt ↓", disabled: i >= list.length - 1, run: () => inspMoveItem(c, 1)},
      {sep: true},
      {label: `Help for ${friendlyName(c.type)}`, icon: "book", shortcut: "F1", run: () => openHelp("reference/components", c.type)},
      inspAssistant()?.open && !EDGE.prefs.get("assistant.hidden", false) ? {label: "Ask the assistant about this", icon: "assistant", run: () => inspAssistant().open({focus: EDGE.focus()})} : null,
      {sep: true},
      {label: "Delete", icon: "trash", shortcut: "Delete", danger: true, run: () => inspDeleteItem(c)},
    ].filter(Boolean)});
  if (isNew) el.append(h("div", {class: "insp-sec"}, h("span", {class: "pv-badge add"}, "New"), " ", h("span", {class: "t-caption"}, "Added by the assistant.")));
  if (d.description && !isSimple()) el.append(h("p", {class: "insp-desc t-caption"}, d.description));
  const props = d.props || {};
  const expert = !isSimple();
  const basic = new Set(BASIC_PROPS[c.type] || Object.keys(props));
  const shapeExtra = {circle: ["radius"], line: ["start", "end", "line_width"], polygon: ["vertices"], cross: ["line_width"]}[c.shape || (c.type === "fixation" ? "cross" : "")];
  if (shapeExtra && (c.type === "shape" || c.type === "fixation")) {
    if (["circle", "line", "polygon"].includes(c.shape)) basic.delete("size");
    shapeExtra.forEach((k) => basic.add(k));
  }
  const isSet = (k, p) => c[k] !== undefined && c[k] !== null && JSON.stringify(c[k]) !== JSON.stringify(p?.default ?? null);
  const fieldFor = (k, p, extra = {}) => field(k, p, c[k], (v) => setProp(c, k, v, `Change “${c.id}”`), {
    comp: c, routine: sel.routine, hasBase: !!baseComp, baseValue: baseComp?.[k], ...extra,
    live: (v) => { if (v === null || v === undefined) delete c[k]; else c[k] = v; if (typeof renderPreview === "function") renderPreview(); }});
  const hasPos = !!props.pos;
  const POS = new Set(["pos", "size", ...(expert ? ["ori", "units"] : [])]);
  const content = inspSec("Content"), position = hasPos ? inspSec("Position", {caption: "or drag it on the screen"}) : null, timing = inspSec("Timing");
  const more = [];
  for (const [k, p] of Object.entries(props)) {
    const target = POS.has(k) && position ? position : content;
    const f = fieldFor(k, p, k === "pos" && target === position ? {hideLabel: true, help: ""} : {});
    if (expert || basic.has(k) || p.required) target.append(f); else more.push([f, isSet(k, p)]);
  }
  // timing: "Starts at" and "Lasts" side by side, then the "Ends the screen" switch
  const tf = {};
  for (const [k, p] of Object.entries(SCHED_FIELDS)) {
    const f = field(k, p, c[k], (v) => setProp(c, k, v, `Change the timing of “${c.id}”`), {label: FIELD_LABELS[k], routine: sel.routine,
      hasBase: !!baseComp, baseValue: baseComp?.[k], noExpr: true,
      caption: k === "end_routine" ? "Move on when this gets a response or times out" : undefined,
      help: k === "start" || k === "duration" ? "" : undefined});
    tf[k] = f;
    if (k === "start" || k === "duration") continue;
    if (expert || BASIC_TIMING.includes(k)) timing.append(f); else more.push([f, isSet(k, p)]);
  }
  timing.insertBefore(h("div", {class: "row2"}, tf.start, tf.duration), timing.querySelector(".field") || null);
  const custom = Object.keys(c).filter((k) => !SCHED_KEYS.has(k) && !props[k]);
  for (const k of custom) {
    const f = field(k, {type: "json"}, c[k], (v) => setProp(c, k, v), {label: k, key: false});
    if (expert) content.append(f); else more.push([f, true]);
  }
  if (content.querySelector(".field")) el.append(content);
  if (position && position.querySelector(".field")) el.append(position);
  el.append(timing);
  if (more.length) el.append(moreOptions(more, "comp:" + c.type));
  inspFoot(h("button", {type: "button", class: "btn sm", "data-fkey": "foot:dup", onclick: () => inspDuplicateItem(c)}, icon("duplicate"), "Duplicate"),
    h("button", {type: "button", class: "btn sm ghost danger-quiet", "data-fkey": "foot:del", onclick: () => inspDeleteItem(c)}, icon("trash"), "Delete"));
}
/* Rename an item or a trial list and everything that refers to it: formulas ($resp.corr, $trials.accuracy),
 * measures, "starts after", gaze-area targets, clickable items, rule actions. The server does it with the same
 * code as MCP (editing.py), so a rename means the same thing from every entry point. → true when renamed */
async function renameWithRefs(kind, old, nu, routine = null) {
  const rev = S.rev;
  let r = null;
  try { r = await api("/api/rename", {experiment: S.exp, kind, old, new: nu, routine}); }
  catch (e) { toast(`Not renamed: ${e.message}`, {tone: "danger"}); return false; }
  if (S.rev !== rev) { toast("The experiment changed meanwhile: rename it again."); return false; }
  S.exp = normalize(r.experiment);
  const where = ((r.changes || []).join(" ").match(/updated the references in (.*)$/) || [])[1];
  const nPlaces = where ? where.split(", ").length : 0;
  if (nPlaces) INSP.renameNote = `Renamed “${old}” to “${nu}” and updated ${nPlaces === 1 ? "the place" : `${nPlaces} places`} that used it (formulas, measures, targets).`;
  return true;
}
async function renameComp(c, v) {
  if (!v || v === c.id) return;
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(v)) return toast("Use letters, digits and _ only.");
  const rid = Object.keys(S.exp.routines).find((k) => comps(k).includes(c));
  if (!rid) return;
  if (findComp(rid, v)) return toast("Another item on this screen has that name.");
  const old = c.id;
  if (!(await renameWithRefs("component", old, v, rid))) return;
  if (S.sel?.kind === "component" && S.sel.routine === rid && S.sel.id === old) S.sel = {...S.sel, id: v};
  commit(`Rename “${old}”`);
  if (INSP.renameNote) { toast(INSP.renameNote); INSP.renameNote = null; }
}
async function renameLoop(n, v) {
  const old = n.loop;
  if (!v || v === old) return;
  const path = S.sel?.path;
  if (!(await renameWithRefs("loop", old, v))) { return; }
  if (S.sel && path && ["loop"].includes(S.sel.kind)) S.sel = {...S.sel};
  commit(`Rename the trial list “${old}”`);
  if (INSP.renameNote) { toast(INSP.renameNote); INSP.renameNote = null; }
}
async function inspRenameItem(c) {
  if (!inspEditable()) return;
  const taken = new Set(comps(S.sel.routine).map((x) => x.id)); taken.delete(c.id);
  const v = await ui.prompt({title: `Rename “${c.id}”`, label: "Name", value: c.id, ok: "Rename", transform: (x) => ui.slug(x),
    help: `Formulas refer to it by this name, e.g. ${c.id}.rt for a response time.`,
    validate: (x) => (!x ? "Type a name first." : taken.has(x) ? "Another item on this screen has that name." : null)});
  if (v && v !== c.id) renameComp(c, v);
}
function inspDuplicateItem(c) {
  if (!inspEditable()) return;
  const list = comps(S.sel.routine); const i = list.indexOf(c); if (i < 0) return;
  const cp = clone(c); cp.id = uniqueId(c.id, allCompIds());
  list.splice(i + 1, 0, cp); S.sel = {kind: "component", routine: S.sel.routine, id: cp.id};
  INSP.focus = "foot:dup";
  commit(`Duplicate “${c.id}”`);
}
function inspMoveItem(c, delta) {
  if (!inspEditable()) return;
  const list = comps(S.sel.routine); const i = list.indexOf(c), j = i + delta;
  if (i < 0 || j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
  commit(`Move “${c.id}” ${delta < 0 ? "behind" : "on top"}`);
}
function inspDeleteItem(c) {
  if (!inspEditable()) return;
  const rid = S.sel.routine;
  const list = comps(rid); const i = list.indexOf(c); if (i < 0) return;
  list.splice(i, 1); S.sel = {kind: "routine", routine: rid};
  commit(`Delete “${c.id}”`);
  inspUndoToast(`Deleted “${c.id}”.`);
}

/* ================================================================== a screen (routine) */
function renderScreenProps(el, rid) {
  const r = S.exp.routines[rid];
  const base = INSP.base?.routines?.[rid];
  const rename = () => (typeof renameRoutine === "function" ? renameRoutine(rid) : null);
  inspHead({tile: "t-screen", ic: "screen", over: "Screen", key: "routine", name: rid, rename,
    help: helpLink("EXPERIMENT_FORMAT", "routines-and-components"),
    menu: () => [
      {label: "Open", icon: "screen", shortcut: "Enter", run: () => (typeof openScreen === "function" ? openScreen(rid) : EDGE.setView("screen", {routine: rid}))},
      {label: "Rename…", icon: "design", shortcut: "F2", run: rename},
      {label: "Duplicate screen", icon: "duplicate", run: () => inspDuplicateScreen(rid)},
      {label: "Try only this screen (5 trials)", icon: "play", run: () => (typeof tryNow === "function" ? tryNow("screen") : startPlay(rid))},
      inspAssistant()?.open && !EDGE.prefs.get("assistant.hidden", false) ? {label: "Ask the assistant about this screen", icon: "assistant", run: () => inspAssistant().open({focus: {kind: "routine", routine: rid}})} : null,
      {sep: true},
      {label: "Delete screen", icon: "trash", danger: true, run: () => deleteRoutine(rid)},
    ].filter(Boolean)});
  if (INSP.base && !base) el.append(h("div", {class: "insp-sec"}, h("span", {class: "pv-badge add"}, "New"), " ", h("span", {class: "t-caption"}, "Added by the assistant.")));
  const sec = inspSec("Screen");
  const name = h("input", {class: "input mono", id: "insp-screen-name", value: rid, spellcheck: "false", "data-fkey": "f:name", autocomplete: "off",
    onchange: (e) => inspLater(() => inspRenameScreen(rid, e.target.value))});
  sec.append(h("div", {class: "field", "data-prop": "name"}, h("div", {class: "lbl-row"}, h("label", {for: "insp-screen-name"}, "Name")), name,
    h("div", {class: "help"}, "Letters, digits and _; the storyboard shows it.")));
  sec.append(field("duration", {type: "float", unit: "s", placeholder: "until a response"}, r.duration, (v) => setProp(r, "duration", v, `Change “${rid}”`),
    {label: "Lasts at most", noExpr: true, hasBase: !!base, baseValue: base?.duration, help: "Empty: until a response, or until everything on it has finished."}));
  sec.append(field("description", {type: "text"}, r.description, (v) => setProp(r, "description", v, `Change “${rid}”`), {label: "Notes", noExpr: true, help: "For you and your colleagues; participants don't see it."}));
  el.append(sec);
  // how it ends: the sentence, and "also ends when" (Expert, or when it is set)
  const ends = inspSec("How it ends");
  ends.append(inspHowItEnds(rid));
  const endIf = field("end_if", {type: "expr"}, r.end_if, (v) => setProp(r, "end_if", v, `Change how “${rid}” ends`),
    {label: "Also ends when", hasBase: !!base, baseValue: base?.end_if, help: "A formula, e.g. $t > 3 or $resp.keys == 'q'."});
  if (!isSimple() || r.end_if) ends.append(endIf); else ends.append(moreOptions([[endIf, false]], "screen-ends"));
  el.append(ends);
  // rules: react while the screen runs
  // Simple: collapsed unless the screen has rules
  if (isSimple() && !(Array.isArray(r.rules) && r.rules.length)) {
    const body = h("div", {class: "rules-body"});
    renderRulesEditor(body, r);
    el.append(moreOptions([[body, false]], "screen-rules", "Rules: react while the screen runs"));
  } else {
    const rules = inspSec("Rules", {caption: "react while the screen runs", actions: helpLink("EXPERIMENT_FORMAT", "routine-rules-when-do")});
    renderRulesEditor(rules, r);
    el.append(rules);
  }
  inspFoot(h("button", {type: "button", class: "btn sm", "data-fkey": "foot:dup", onclick: () => inspDuplicateScreen(rid)}, icon("duplicate"), "Duplicate screen"),
    h("button", {type: "button", class: "btn sm ghost danger-quiet", "data-fkey": "foot:del", onclick: () => { if (inspEditable() && typeof deleteRoutine === "function") deleteRoutine(rid); }}, icon("trash"), "Delete screen"));
}
/* "How it ends", in words: the response that ends it, its length, or a warning when nothing ends it. */
function inspHowItEnds(rid) {
  const r = S.exp.routines[rid] || {};
  const live = (r.components || []).filter((c) => c.disabled !== true);
  const resp = live.find((c) => c.end_routine);
  const parts = [];
  let ic = "pause_blank", tone = "";
  if (resp) {
    ic = inspTypeIcon(resp.type);
    const what = {keyboard: `a key is pressed${typeof keysWords === "function" && resp.keys ? ` (${keysWords(resp.keys)})` : ""}`, mouse: "the participant clicks",
      slider: "the participant gives a rating", html: "the form is sent", survey: "the questions are answered", gaze_roi: "the participant looks at the area",
      device_response: "a button is pressed"}[resp.type] || `“${resp.id}” finishes`;
    parts.push(`When ${what}`);
    if (typeof resp.duration === "number") parts.push(`or after ${inspFmtSec(numOr(resp.start, 0) + resp.duration)} at most`);
  }
  const early = !resp && !r.end_if && typeof r.duration === "number" && typeof itemsEnd === "function" ? itemsEnd(rid) : null;
  if (early !== null && early < r.duration) {
    parts.push(`When everything on it has finished, after ${inspFmtSec(early)}: before its ${inspFmtSec(r.duration)}, which is only a maximum. To show it for ${inspFmtSec(r.duration)}, give an item that length or add a Pause / blank`);
    tone = "warn"; ic = "warning";
  } else if (typeof r.duration === "number") parts.push(resp ? `or after ${inspFmtSec(r.duration)} at most` : `After ${inspFmtSec(r.duration)}`);
  else if (isExpr(r.duration)) parts.push(`${resp ? "or after" : "After"} a length computed on each trial`);
  if (r.end_if) parts.push(`${parts.length ? "or when" : "When"} ${inspInWords(r.end_if) || "its condition is true"}`);
  if (!parts.length) {
    const end = Math.max(0, ...live.map((c) => (typeof c.duration === "number" ? numOr(c.start, 0) + c.duration : 0)));
    const open = live.some((c) => typeof c.duration !== "number" && !["variable", "code", "marker", "sound"].includes(c.type));
    if (!live.length) { parts.push("It is empty: add something to it"); tone = "todo"; }
    else if (end && !open) parts.push(`When everything on it has finished (after ${inspFmtSec(end)})`);
    else { parts.push("Nothing ends it yet: add a response that ends the screen, or give it a length"); tone = "warn"; ic = "warning"; }
  }
  const text = parts.join(", ").replace(/, or/g, " or") + ".";
  return h("p", {class: "insp-say ends " + tone}, icon(ic), h("span", {}, text));
}
const inspFmtSec = (v) => (typeof fmtS === "function" ? fmtS(v) : `${Math.round(v * 1000) / 1000} s`);
function inspRenameScreen(rid, raw) {
  if (!inspEditable() || !S.exp.routines[rid]) return;
  const nid = ui.slug(raw);
  if (!nid || nid === rid) { renderProps(); return; }
  if (S.exp.routines[nid]) { toast(`There is already a screen called “${nid}”.`); renderProps(); return; }
  const r = {}; for (const [k, v] of Object.entries(S.exp.routines)) r[k === rid ? nid : k] = v;
  S.exp.routines = r;
  walkFlow((n, path) => { const {list, index} = parentOf(path); if (n === rid) list[index] = nid; else if (n && n.routine === rid) n.routine = nid; });
  if (S.routine === rid) S.routine = nid;
  if (S.sel?.routine === rid) S.sel = {...S.sel, routine: nid};
  if (nid !== raw.trim()) toast(`Saved as ${nid}`);
  commit(`Rename screen “${rid}”`);
}
function inspDuplicateScreen(rid) {
  if (!inspEditable() || !S.exp.routines[rid]) return;
  if (typeof duplicateRoutine === "function") return duplicateRoutine(rid, findFlowPath((n) => routineOfNode(n) === rid) || null);
  const nid = uniqueId(rid, new Set(Object.keys(S.exp.routines)));
  S.exp.routines[nid] = clone(S.exp.routines[rid]); S.exp.flow.push(nid);
  S.routine = nid; S.sel = {kind: "routine", routine: nid};
  commit(`Duplicate “${rid}”`);
}

/* ================================================================== trial-list columns available to a screen */
function loopColumns(lp) {
  if (!lp) return [];
  if (lp.staircase) return [lp.staircase.variable || "level"];
  const c = lp.conditions;
  if (Array.isArray(c)) return [...new Set(c.flatMap((r) => Object.keys(r || {})))];
  if (c && c.factorial) return Object.keys(c.factorial);
  if (c && typeof firstRow === "function") return Object.keys(firstRow(c) || {});
  return [];
}
function columnsForScreen(rid) {
  if (!rid) return [];
  const out = [];
  for (const lp of enclosing(rid).loops) for (const c of loopColumns(lp)) if (!out.includes(c)) out.push(c);
  return out;
}
function loopRowsLabel(n) {
  const c = n.conditions;
  const rows = Array.isArray(c) ? c.length : c && c.factorial ? Object.values(c.factorial).reduce((a, v) => a * (Array.isArray(v) ? v.length : 1), 1) : null;
  return rows == null ? (typeof c === "string" ? c : "repeat") : inspPlural(rows, "row");
}
function innermostLoopPath(rid) {
  let best = null;
  walkFlow((n, path) => {
    if (routineOfNode(n) !== rid) return;
    let cur = S.exp.flow, lpPath = null;
    for (let i = 0; i < path.length; i++) { if (cur && cur.loop !== undefined) lpPath = path.slice(0, i); cur = cur[path[i]]; }
    if (lpPath && (!best || lpPath.length > best.length)) best = lpPath;
  });
  return best;
}
/* Open the trial list that has this column (the Trial list view at that column, or the list's properties). */
function selectLoopWithColumn(col) {
  const rid = S.sel?.routine || S.routine;
  let path = null;
  walkFlow((n, p) => { if (!path && n?.loop !== undefined && loopColumns(n).includes(col) && (!rid || (typeof routinesInside === "function" ? routinesInside(n) : []).includes(rid))) path = p; });
  path = path || innermostLoopPath(rid);
  if (!path) return;
  if (typeof openTrialList === "function") openTrialList(path, {column: col});
  else { S.sel = {kind: "loop", path}; renderAll(); }
}
/* Add a column to the trial list around the current screen, making the trial list when there is none.
 * Resolves to the column name (the caller binds the field to it), or null. */
async function addTrialColumn(suggest, fill) {
  if (!inspEditable()) return null;
  const rid = S.sel?.routine || S.routine;
  const taken = new Set(columnsForScreen(rid));
  const base = suggest === "text" ? "word" : suggest === "image" ? "picture" : suggest === "sound" ? "sound_file" : suggest || "column";
  const path0 = innermostLoopPath(rid);
  const lp0 = path0 ? getNode(path0) : null;
  if (lp0 && (typeof lp0.conditions === "string" || typeof lp0.conditions?.file === "string")) {
    const file = typeof lp0.conditions === "string" ? lp0.conditions : lp0.conditions.file;
    toast(`This trial list comes from ${file}: add the column in that file, or copy the list into the experiment first.`,
      {ms: 9000, action: typeof openTrialList === "function" ? {label: "Open list", run: () => openTrialList(path0)} : null});
    return null;
  }
  if (lp0 && lp0.staircase) { toast("This trial list is a staircase: add the column to a trial list around it instead."); return null; }
  const name = await ui.prompt({title: "New trial-list column", label: "Column name", value: uniqueId(base, taken), ok: "Add column",
    help: lp0 ? `Each trial of “${lp0.loop}” can have its own value in this column.` : `This screen gets a trial list with this column. Fill in one row per trial.`,
    transform: (v) => ui.slug(v), validate: (v) => (!v ? "Type a name first." : taken.has(v) ? `The trial list already has a column “${v}”.` : null)});
  if (!name) return null;
  const v = fill === null || fill === undefined ? "" : fill;
  const path = innermostLoopPath(rid);
  if (path) {
    const lp = getNode(path);
    if (lp.conditions && lp.conditions.factorial) lp.conditions.factorial[name] = [v];
    else { lp.conditions = Array.isArray(lp.conditions) && lp.conditions.length ? lp.conditions : [{}]; lp.conditions.forEach((r) => { if (!(name in r)) r[name] = v; }); }
    toast(`Added the column “${name}” to the trial list “${lp.loop}”.`, {action: typeof openTrialList === "function" ? {label: "Open list", run: () => openTrialList(path, {column: name})} : null});
  } else {
    // no trial list yet: wrap every top-level use of this screen in a new one
    const id = uniqueId("trials", loopIds());
    let wrapped = false;
    walkFlow((n, p) => { if (wrapped || routineOfNode(n) !== rid) return; const {list, index} = parentOf(p);
      list[index] = {loop: id, order: "random", repeats: 1, conditions: [{[name]: v}, {[name]: v}], children: [n]}; wrapped = true; });
    if (!wrapped) S.exp.flow.push({loop: id, order: "random", repeats: 1, conditions: [{[name]: v}, {[name]: v}], children: [rid]});
    const path2 = findFlowPath((n) => n.loop === id);
    toast(`Made a trial list “${id}” around “${rid}” with the column “${name}”. Fill in one row per trial.`,
      {ms: 9000, action: typeof openTrialList === "function" && path2 ? {label: "Open list", run: () => openTrialList(path2, {column: name})} : null});
  }
  return name;
}

/* ================================================================== a trial list (loop) */
const ORDER_LABELS = {random: "Shuffled each time", sequential: "As listed", fullrandom: "Shuffled across repeats",
  latin_square: "Latin square by participant number", counterbalance: "Counterbalanced by participant number"};
function inspLoopRowCount(n) {
  if (n.staircase) return null;
  const c = n.conditions;
  if (Array.isArray(c)) return c.length;
  if (c && c.factorial) return Object.values(c.factorial).reduce((a, v) => a * (Array.isArray(v) ? v.length : 1), 1);
  if (c && typeof loopRowsFor === "function") { const rows = loopRowsFor(n); return Array.isArray(rows) ? rows.length : null; }
  return c ? null : 1;
}
function renderLoopProps(el, n) {
  if (!n || n.loop === undefined) return inspOverview(el);
  const path = S.sel.path;
  const base = INSP.base ? (() => { let b = null; try { const walk = (nodes) => (nodes || []).forEach((x) => { if (b || !x || typeof x !== "object") return; if (x.loop === n.loop) b = x; walk(x.children); walk(x.then); walk(x.else); Object.values(x.states || {}).forEach((s) => walk(s.run)); }); walk(INSP.base.flow); } catch { /* none */ } return b; })() : null;
  const rename = () => (typeof renameNode === "function" ? renameNode(n, path) : inspRenameLoop(n));
  const canList = typeof openTrialList === "function";
  inspHead({tile: "tint-hw", ic: "loop", over: "Trial list", overClass: "c-hw", key: "loop", name: n.loop, rename,
    help: helpLink("COOKBOOK", "trial-lists-and-randomization"),
    menu: () => [
      canList ? {label: "Open the trial list", icon: "table", shortcut: "Enter", run: () => openTrialList(path)} : null,
      {label: "Rename…", icon: "design", shortcut: "F2", run: rename},
      {sep: true},
      {label: "Remove the trial list (keep its screens)", icon: "trash", danger: true, run: () => inspUnwrapLoop(path)},
    ].filter(Boolean)});
  const inside = (typeof routinesInside === "function" ? routinesInside(n) : (n.children || []).map((x) => (typeof x === "string" ? x : x.routine || x.loop)).filter(Boolean));
  el.append(h("p", {class: "insp-lead t-small"}, "Repeats: ", inside.length ? inside.map((x, i) => [i ? h("span", {class: "t-3"}, " → ") : null, h("b", {}, x)]) : h("span", {class: "t-3"}, "nothing yet")));
  // where the rows come from
  const rows = inspSec("Rows");
  const c = n.conditions;
  const mode = n.staircase ? "staircase" : typeof c === "string" || typeof c?.file === "string" ? "file" : c && c.factorial ? "factorial" : Array.isArray(c) ? "table" : "none";
  const cnt = inspLoopRowCount(n);
  const cols = loopColumns(n);
  const summary = {
    table: `Typed here · ${cnt === null ? "" : inspPlural(cnt, "row")}${cols.length ? ` · ${inspPlural(cols.length, "column")}` : ""}`,
    file: `From ${typeof c === "string" ? c : c?.file} · ${cnt === null ? "loading…" : inspPlural(cnt, "row")}`,
    factorial: `Every combination · ${cnt === null ? "" : inspPlural(cnt, "row")}`,
    staircase: `Staircase on “${n.staircase?.variable || "level"}”`,
    none: "No rows: the screens just repeat",
  }[mode];
  rows.append(h("div", {class: "rows-sum"}, icon(mode === "file" ? "file" : mode === "staircase" ? "results" : "table"), h("span", {}, summary)));
  if (cols.length && mode !== "staircase") rows.append(h("p", {class: "t-caption cols"}, "Columns: ", cols.map((x, i) => [i ? ", " : "", h("span", {class: "mono"}, x)])));
  if (canList) {
    rows.append(h("button", {type: "button", class: "btn sm", "data-fkey": "loop:open", onclick: () => openTrialList(path)}, icon("table"), "Open list"));
  } else {
    // without the Trial list view (P4a), the rows are edited here
    const modeSel = field("conditions source", {type: "choice", choices: ["none", "table", "file", "factorial", "staircase"]}, mode, (v) => {
      delete n.staircase;
      if (v === "none") delete n.conditions;
      else if (v === "table") n.conditions = Array.isArray(n.conditions) ? n.conditions : [{condition: "A"}, {condition: "B"}];
      else if (v === "file") n.conditions = "conditions.csv";
      else if (v === "factorial") n.conditions = {factorial: {factor_a: ["a1", "a2"], factor_b: ["b1", "b2"]}};
      else if (v === "staircase") { delete n.conditions; n.staircase = {variable: "level", start: 0.5, step: [0.1, 0.05], down: 3, up: 1, min: 0, max: 1, reversals: 8, max_trials: 60, correct: "resp.corr"}; }
      commit(`Change the rows of “${n.loop}”`);
    }, {label: "Rows come from", noExpr: true});
    rows.append(modeSel);
    if (mode === "table") rows.append(condTable(n));
    if (mode === "file") rows.append(field("file", {type: "str"}, c, (v) => { n.conditions = v; commit(); }, {label: "File", noExpr: true, help: "CSV, TSV, Excel or JSON, next to the experiment."}));
    if (mode === "factorial") rows.append(field("factors", {type: "dict"}, c.factorial, (v) => { n.conditions.factorial = v; commit(); }, {label: "Factors and levels", noExpr: true}));
    if (mode === "staircase") rows.append(field("staircase", {type: "dict"}, n.staircase, (v) => { n.staircase = v; commit(); }, {label: "Staircase", noExpr: true}));
  }
  el.append(rows);
  // order and repeats
  const order = inspSec(null);
  if (mode !== "staircase") {
    const orders = S.schema.loop_orders || Object.keys(ORDER_LABELS);
    const cur = n.order || "sequential";
    const oid = "insp-order";
    order.append(h("div", {class: "field", "data-prop": "order"}, h("div", {class: "lbl-row"}, h("label", {for: oid}, "Order"), !isSimple() ? h("span", {class: "key mono"}, "order") : null),
      h("select", {class: "input", id: oid, "data-fkey": "f:order", onchange: (e) => inspLater(() => setProp(n, "order", e.target.value, `Change the order of “${n.loop}”`))},
        orders.map((o) => { const op = h("option", {value: o, title: o}, (ORDER_LABELS[o] || inspCapWords(o)) + (!isSimple() ? ` (${o})` : "")); if (o === cur) op.selected = true; return op; })),
      base && base.order !== n.order ? inspWasLine(ORDER_LABELS[base.order || "sequential"], ORDER_LABELS[cur]) : null));
    const reps = +n.repeats || 1;
    const rid = "insp-repeats";
    const repIn = h("input", {class: "input num", id: rid, value: n.repeats ?? 1, inputmode: "numeric", "data-fkey": "f:repeats",
      onchange: (e) => inspLater(() => { const v = parseVal("int", e.target.value); setProp(n, "repeats", v === 1 ? null : v, `Change the repeats of “${n.loop}”`); })});
    order.append(h("div", {class: "field", "data-prop": "repeats"}, h("div", {class: "lbl-row"}, h("label", {for: rid}, "Repeat the list"), !isSimple() ? h("span", {class: "key mono"}, "repeats") : null),
      h("div", {class: "inline-num"}, repIn, h("span", {}, reps === 1 ? "time" : "times"), cnt !== null ? h("span", {class: "t-2"}, `= ${inspPlural(cnt * reps, "trial")}`) : null),
      base && (base.repeats ?? 1) !== (n.repeats ?? 1) ? inspWasLine(base.repeats ?? 1, n.repeats ?? 1) : null));
  } else {
    order.append(h("p", {class: "t-small t-2"}, `It adapts “${n.staircase.variable || "level"}” after every trial and stops after ${inspPlural(n.staircase.reversals ?? 8, "reversal")} or ${inspPlural(n.staircase.max_trials ?? 100, "trial")}.`));
  }
  el.append(order);
  // constraints: "More options" in Simple
  const more = [];
  if (mode !== "staircase") {
    more.push([inspMaxRepeat(n, cols), n.max_repeat != null]);
    more.push([field("select", {type: "str"}, n.select === undefined ? null : typeof n.select === "string" ? n.select : JSON.stringify(n.select), (v) => setProp(n, "select", parseVal("json", v)),
      {label: "Use only rows", noExpr: true, placeholder: "all", help: "E.g. 0:10 for the first ten rows, or [0, 3, 5]."}), n.select != null]);
  }
  more.push([field("stop_if", {type: "expr"}, n.stop_if, (v) => setProp(n, "stop_if", v, `Change “${n.loop}”`), {label: "Stop early when", help: "Checked after each trial, e.g. $resp.corr == 0."}), !!n.stop_if]);
  if (isSimple()) el.append(moreOptions(more, "loop"));
  else { const s = inspSec("Constraints"); more.forEach(([f]) => s.append(f)); el.append(s); }
  inspFoot(h("button", {type: "button", class: "btn sm ghost danger-quiet", "data-fkey": "foot:del", onclick: () => inspUnwrapLoop(path)}, icon("trash"), "Remove the trial list, keep its screens"));
}
/* "No more than N in a row": per column ({"ink": 2}); other forms ({"kind": {"deviant": 1}}) are edited as text. */
function inspMaxRepeat(n, cols) {
  const mr = n.max_repeat;
  const simple = mr == null || (typeof mr === "object" && !Array.isArray(mr) && Object.values(mr).every((v) => typeof v === "number"));
  if (!simple || !cols.length) {
    return field("max_repeat", {type: "dict"}, mr, (v) => setProp(n, "max_repeat", v), {label: "No more than N in a row", noExpr: true,
      help: "Per column, e.g. {\"ink\": 2}; or per value, e.g. {\"kind\": {\"deviant\": 1}}."});
  }
  const wrap = h("div", {class: "field", "data-prop": "max_repeat"}, h("div", {class: "lbl-row"}, h("span", {class: "label"}, "No more than N in a row"), !isSimple() ? h("span", {class: "key mono"}, "max_repeat") : null));
  const grid = h("div", {class: "mr-grid"});
  for (const col of cols) {
    const id = "mr-" + col + "-" + (++INSP.seq);
    grid.append(h("label", {for: id, class: "mono"}, col),
      h("input", {class: "input num", id, value: (mr || {})[col] ?? "", placeholder: "any", inputmode: "numeric", "data-fkey": "mr:" + col,
        onchange: (e) => inspLater(() => {
          const v = parseInt(e.target.value, 10);
          const next = {...(n.max_repeat || {})};
          if (isNaN(v) || v < 1) delete next[col]; else next[col] = v;
          setProp(n, "max_repeat", Object.keys(next).length ? next : null, `Change “${n.loop}”`);
        })}));
  }
  wrap.append(grid, h("div", {class: "help"}, "The same value at most this many trials in a row. Empty: no limit."));
  return wrap;
}
async function inspRenameLoop(n) {
  if (!inspEditable()) return;
  const taken = loopIds(); taken.delete(n.loop);
  const v = await ui.prompt({title: "Rename the trial list", label: "Name", value: n.loop, ok: "Rename", transform: (x) => ui.slug(x),
    validate: (x) => (!x ? "Type a name first." : taken.has(x) ? `There is already something called “${x}”.` : null)});
  if (v && v !== n.loop) await renameLoop(n, v);
}
function inspUnwrapLoop(path) {
  if (!inspEditable()) return;
  const n = getNode(path); if (!n) return;
  const {list, index} = parentOf(path);
  list.splice(index, 1, ...(n.children || []));
  S.sel = null;
  if (S.view === "list") S.view = "story";
  commit(`Remove the trial list “${n.loop}”`);
  inspUndoToast(`Removed the trial list “${n.loop}”; its screens stay.`);
}
/* Inline rows (used only when the Trial list view is not available). */
function condTable(n) {
  const rows = n.conditions;
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const tbl = h("table", {class: "grid cond-table"});
  tbl.append(h("thead", {}, h("tr", {}, cols.map((c) => h("th", {}, h("input", {class: "input mono", value: c, "aria-label": `Column ${c}`, onchange: (e) => {
    const nc = e.target.value.trim();
    if (nc && nc !== c && cols.includes(nc)) { toast(`There is already a column “${nc}”`); e.target.value = c; return; }
    rows.forEach((r, i) => { const out = {}; for (const [k, v] of Object.entries(r)) { if (k === c) { if (nc) out[nc] = v; } else out[k] = v; } rows[i] = out; });
    commit(); }}))), h("th", {}, h("button", {type: "button", class: "btn ghost icon sm", "aria-label": "Add a column", title: "Add a column",
    onclick: () => { const nc = uniqueId("column", new Set(cols)); rows.forEach((r) => r[nc] = ""); if (!rows.length) rows.push({[nc]: ""}); commit(); }}, icon("plus"))))));
  const body = h("tbody");
  rows.forEach((r, i) => body.append(h("tr", {}, cols.map((c) => h("td", {}, h("input", {class: "input", value: showVal("", r[c]), "aria-label": `Row ${i + 1}, ${c}`, onchange: (e) => {
    const raw = e.target.value; r[c] = raw !== "" && !isNaN(Number(raw)) ? Number(raw) : raw; commit(); }}))),
    h("td", {}, h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Delete row ${i + 1}`, onclick: () => { rows.splice(i, 1); commit(); }}, icon("trash"))))));
  tbl.append(body);
  return h("div", {class: "field", "data-prop": "conditions"}, h("div", {class: "table-wrap"}, tbl),
    h("button", {type: "button", class: "btn sm ghost", onclick: () => { rows.push(Object.fromEntries(cols.map((c) => [c, ""]))); commit(); }}, icon("plus"), "Row"));
}

/* ================================================================== if / otherwise (branch) */
function renderBranchProps(el, path) {
  const n = getNode(path);
  if (!n || n.if === undefined) return inspOverview(el);
  inspHead({tile: "t-branch", ic: "branch", over: "If / otherwise", overClass: "c-branch", key: "if", name: "Only if…",
    help: helpLink("EXPERIMENT_FORMAT", "workflow-logic"),
    menu: () => [{label: "Remove the condition (keep its screens)", icon: "trash", danger: true, run: () => inspUnwrapBranch(path)}]});
  const sec = inspSec("Condition");
  sec.append(field("if", {type: "expr"}, n.if, (v) => setProp(n, "if", v || "$True", "Change the condition"),
    {label: "Show the screens only when", placeholder: "$ condition, e.g. $score >= 8", help: "A formula: the “then” screens run when it is true, the “otherwise” screens when it is false."}));
  const names = (nodes) => (nodes || []).map((x) => (typeof x === "string" ? x : x?.routine || x?.loop || x?.statemachine || "if / otherwise"));
  sec.append(h("p", {class: "t-small"}, h("b", {}, "Then: "), names(n.then).join(", ") || h("span", {class: "t-3"}, "nothing")),
    h("p", {class: "t-small"}, h("b", {}, "Otherwise: "), names(n.else).join(", ") || h("span", {class: "t-3"}, "nothing")));
  el.append(sec);
  inspFoot(h("button", {type: "button", class: "btn sm ghost danger-quiet", "data-fkey": "foot:del", onclick: () => inspUnwrapBranch(path)}, icon("trash"), "Remove the condition, keep its screens"));
}
function inspUnwrapBranch(path) {
  if (!inspEditable()) return;
  const n = getNode(path); if (!n) return;
  const {list, index} = parentOf(path);
  list.splice(index, 1, ...(n.then || []), ...(n.else || []));
  S.sel = null;
  commit("Remove the condition");
  inspUndoToast("Removed the condition; its screens stay.");
}

/* ================================================================== a workflow (state machine) and its phases */
async function addState(path) {
  if (!inspEditable()) return;
  const m = getNode(path); if (!m) return;
  const taken = new Set(Object.keys(m.states || {}));
  const name = await ui.prompt({title: "Add a phase", label: "Name", value: uniqueId(taken.size ? "phase" : "practice", taken), ok: "Add phase",
    placeholder: "e.g. practice, main, debrief", help: "A phase runs some screens or trial lists, then its routes decide what comes next.",
    transform: (v) => ui.slug(v), validate: (v) => (!v ? "Type a name first." : taken.has(v) ? `There is already a phase “${v}”.` : null)});
  if (!name) return;
  m.states ||= {};
  m.states[name] = {run: [], next: [{goto: "end"}]};
  if (!m.start) m.start = name;
  S.sel = {kind: "state", path, name};
  commit(`Add the phase “${name}”`);
}
async function renameState(path, old, given = null) {
  if (!inspEditable()) return;
  const m = getNode(path);
  const taken = new Set(Object.keys(m.states || {})); taken.delete(old);
  const nn = given !== null ? ui.slug(given) : await ui.prompt({title: `Rename the phase “${old}”`, label: "Name", value: old, ok: "Rename",
    transform: (v) => ui.slug(v), validate: (v) => (!v ? "Type a name first." : taken.has(v) ? `There is already a phase “${v}”.` : null)});
  if (!nn || nn === old) { if (given !== null) renderProps(); return; }
  if (taken.has(nn)) { toast(`There is already a phase “${nn}”.`); renderProps(); return; }
  const states = {};
  for (const [k, v] of Object.entries(m.states)) states[k === old ? nn : k] = v;
  for (const st of Object.values(states)) for (const t of st.next || []) if (typeof t === "object" && t.goto === old) t.goto = nn;
  for (const st of Object.values(states)) st.next = (st.next || []).map((t) => (t === old ? nn : t));
  m.states = states;
  if (m.start === old) m.start = nn;
  // rules "go to a workflow phase" on the screens of this workflow
  let rules = 0;
  const inMachine = new Set(); walkFlow((x) => { const r = routineOfNode(x); if (typeof r === "string") inMachine.add(r); }, Object.values(states).flatMap((st) => st.run || []));
  for (const rid of inMachine) for (const rule of S.exp.routines[rid]?.rules || [])
    for (const a of Array.isArray(rule?.do) ? rule.do : [rule?.do]) if (a && typeof a === "object" && a.goto === old) { a.goto = nn; rules++; }
  if (rules) toast(`Also updated ${rules === 1 ? "the rule" : `${rules} rules`} that go${rules === 1 ? "es" : ""} to “${old}”.`);
  S.sel = {kind: "state", path, name: nn};
  commit(`Rename the phase “${old}”`);
}
function renderMachineProps(el) {
  const path = S.sel.path;
  const m = getNode(path);
  if (!m || m.statemachine === undefined) return inspOverview(el);
  const canDiagram = typeof openDiagram === "function";
  const rename = async () => {
    if (!inspEditable()) return;
    const taken = loopIds(); taken.delete(m.statemachine);
    const v = await ui.prompt({title: "Rename the workflow", label: "Name", value: m.statemachine, ok: "Rename", transform: (x) => ui.slug(x),
      validate: (x) => (!x ? "Type a name first." : taken.has(x) ? `There is already something called “${x}”.` : null)});
    if (v && v !== m.statemachine) { const old = m.statemachine; m.statemachine = v; commit(`Rename the workflow “${old}”`); }
  };
  inspHead({tile: "t-workflow", ic: "workflow", over: "Workflow", overClass: "c-workflow", key: "statemachine", name: m.statemachine, rename,
    help: helpLink("EXPERIMENT_FORMAT", "workflows-state-machines"),
    menu: () => [canDiagram ? {label: "Open diagram", icon: "workflow", run: () => openDiagram(path)} : null,
      {label: "Rename…", icon: "design", run: rename}, {label: "Add a phase", icon: "plus", run: () => addState(path)},
      {sep: true}, {label: "Remove the workflow", icon: "trash", danger: true, run: () => inspRemoveWorkflow(path)}].filter(Boolean)});
  el.append(h("p", {class: "insp-lead t-small t-2"}, "One phase runs at a time. When a phase finishes, its routes decide the next phase or the end: practice until good, screening, adaptive blocks."));
  const sec = inspSec("Phases", {actions: canDiagram ? h("button", {type: "button", class: "btn sm ghost", onclick: () => openDiagram(path)}, icon("workflow"), "Open diagram") : null});
  const names = Object.keys(m.states || {});
  const startId = "insp-start";
  sec.append(h("div", {class: "field", "data-prop": "start"}, h("div", {class: "lbl-row"}, h("label", {for: startId}, "First phase"), !isSimple() ? h("span", {class: "key mono"}, "start") : null),
    h("select", {class: "input", id: startId, "data-fkey": "f:start", onchange: (e) => inspLater(() => { m.start = e.target.value; commit("Change the first phase"); })},
      names.map((x) => { const o = h("option", {value: x}, x); if (x === m.start) o.selected = true; return o; }))));
  const list = h("div", {class: "phase-list", role: "list"});
  for (const name of names) {
    const st = m.states[name];
    const runs = typeof phaseRuns === "function" ? phaseRuns(st) : (st.run || []).map((x) => (typeof x === "string" ? x : x.routine || x.loop || "…"));
    list.append(h("button", {type: "button", role: "listitem", class: "phase-row", "data-fkey": "phase:" + name, onclick: () => { S.sel = {kind: "state", path, name}; renderAll(); }},
      icon(name === m.start ? "play" : "workflow"), h("span", {class: "pn"}, h("b", {}, name), h("span", {class: "t-caption"}, runs.length ? runs.join(" → ") : "empty")),
      st.max_visits ? h("span", {class: "chip"}, `at most ${st.max_visits}×`) : null, icon("chev-right", "chev")));
  }
  sec.append(list, h("button", {type: "button", class: "btn sm ghost", "data-fkey": "phase:add", onclick: () => addState(path)}, icon("plus"), "Add a phase"));
  el.append(sec);
  if (!isSimple()) {
    const adv = inspSec("Advanced");
    adv.append(field("max_steps", {type: "int"}, m.max_steps, (v) => setProp(m, "max_steps", v), {label: "Safety limit on phase changes", noExpr: true}));
    adv.append(h("p", {class: "t-caption"}, "In formulas: ", h("code", {class: "mono"}, `$${m.statemachine}.state`), ", ", h("code", {class: "mono"}, `$${m.statemachine}.visit`), " (visits of the current phase), and trial-list results such as ", h("code", {class: "mono"}, "$practice.accuracy"), "."));
    el.append(adv);
  }
  inspFoot(h("button", {type: "button", class: "btn sm ghost danger-quiet", "data-fkey": "foot:del", onclick: () => inspRemoveWorkflow(path)}, icon("trash"), "Remove the workflow"));
}
function inspRemoveWorkflow(path) {
  if (!inspEditable()) return;
  const m = getNode(path); if (!m) return;
  const {list, index} = parentOf(path);
  list.splice(index, 1);
  S.sel = null;
  if (S.view === "diagram") S.view = "story";
  commit(`Remove the workflow “${m.statemachine}”`);
  inspUndoToast(`Removed the workflow “${m.statemachine}”. Its screens are still defined.`);
}
function renderStateProps(el) {
  const path = S.sel.path;
  const m = getNode(path), name = S.sel.name, st = m?.states?.[name];
  if (!st) { S.sel = m ? {kind: "machine", path} : null; return m ? renderMachineProps(el) : inspOverview(el); }
  inspHead({tile: "t-workflow", ic: "workflow", over: `Phase of “${m.statemachine}”`, overClass: "c-workflow", key: "state", name, rename: () => renameState(path, name),
    help: helpLink("EXPERIMENT_FORMAT", "workflows-state-machines"),
    menu: () => [{label: "Rename…", icon: "design", run: () => renameState(path, name)},
      m.start !== name ? {label: "Make it the first phase", icon: "play", run: () => { if (inspEditable()) { m.start = name; commit("Change the first phase"); } }} : null,
      {label: "Back to the workflow", icon: "chev-left", run: () => { S.sel = {kind: "machine", path}; renderAll(); }},
      {sep: true}, {label: "Delete phase", icon: "trash", danger: true, run: () => inspDeleteState(path, name)}].filter(Boolean)});
  const sec = inspSec("Phase");
  const nid = "insp-phase-name";
  sec.append(h("div", {class: "field", "data-prop": "name"}, h("div", {class: "lbl-row"}, h("label", {for: nid}, "Name")),
    h("input", {class: "input mono", id: nid, value: name, "data-fkey": "f:name", spellcheck: "false", autocomplete: "off", onchange: (e) => inspLater(() => renameState(path, name, e.target.value))})));
  sec.append(field("description", {type: "text"}, st.description, (v) => setProp(st, "description", v), {label: "Notes", noExpr: true}));
  const runs = typeof phaseRuns === "function" ? phaseRuns(st) : (st.run || []).map((x) => (typeof x === "string" ? x : x.routine || x.loop || "…"));
  sec.append(h("p", {class: "t-small"}, h("b", {}, "Runs: "), runs.length ? runs.join(" → ") : h("span", {class: "t-3"}, "nothing yet"),
    h("span", {class: "t-caption"}, runs.length ? "" : " Add screens or trial lists to it in the storyboard (its + buttons).")));
  el.append(sec);
  // routes
  const routes = inspSec("Then go to…", {caption: "checked top to bottom"});
  // viewing a phase changes nothing in the file: routes written as plain names are only normalised when present
  if (Array.isArray(st.next) && st.next.some((t) => typeof t === "string")) st.next = st.next.map((t) => (typeof t === "string" ? {goto: t} : t));
  const nexts = Array.isArray(st.next) ? st.next : [];
  const targets = [...Object.keys(m.states), "end"];
  const tWord = (x) => (x === "end" ? "The end of the workflow" : x === name ? `${x} (again)` : x);
  nexts.forEach((t, i) => {
    const gid = `route-${i}-goto`, cid = `route-${i}-if`;
    const goto = h("select", {class: "input", id: gid, "data-fkey": `route:${i}:goto`, onchange: (e) => inspLater(() => { t.goto = e.target.value; commit("Change a route"); })},
      targets.map((x) => { const o = h("option", {value: x}, tWord(x)); if (t.goto === x) o.selected = true; return o; }));
    const cond = h("input", {class: "input expr", id: cid, list: "expr-vars", value: t.if || "", placeholder: "Otherwise (always)", spellcheck: "false", "data-fkey": `route:${i}:if`,
      onchange: (e) => inspLater(() => { const v = e.target.value.trim(); if (v) t.if = v.startsWith("$") ? v : "$" + v; else delete t.if; commit("Change a route"); })});
    const say = t.if ? inspInWords(t.if) : "";
    const box = h("div", {class: "route", "data-prop": `next.${i}`},
      h("div", {class: "route-head"}, h("span", {class: "route-n"}, String(i + 1)), h("label", {for: cid}, t.if ? "When" : "Otherwise"), h("span", {class: "grow"}),
        h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Move route ${i + 1} up`, title: "Move up", disabled: i === 0 ? "" : null,
          onclick: () => { if (inspEditable() && i > 0) { [st.next[i - 1], st.next[i]] = [st.next[i], st.next[i - 1]]; commit("Reorder the routes"); } }}, icon("chev-down", "flip")),
        h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Remove route ${i + 1}`, title: "Remove", onclick: () => { if (inspEditable()) { st.next.splice(i, 1); commit("Remove a route"); } }}, icon("trash"))),
      cond, say && say !== t.if ? h("div", {class: "say"}, `In words: ${say}.`) : null,
      h("div", {class: "route-goto"}, h("label", {for: gid}, "go to"), goto),
      !isSimple() ? h("input", {class: "input mono", value: t.set ? JSON.stringify(t.set) : "", placeholder: 'and set variables, e.g. {"block": 2}', "aria-label": "Set variables when this route is taken",
        onchange: (e) => inspLater(() => { try { const v = e.target.value.trim(); if (v) t.set = JSON.parse(v); else delete t.set; commit("Change a route"); } catch { toast("That isn't valid JSON."); } })}) : null);
    routes.append(box);
  });
  routes.append(field("max_visits", {type: "int"}, st.max_visits, (v) => setProp(st, "max_visits", v, `Change the phase “${name}”`), {label: "Repeat this phase at most", unit: "times", noExpr: true,
    placeholder: "no limit", help: "After this many visits it stops repeating and takes the first route elsewhere."}));
  routes.append(h("button", {type: "button", class: "btn sm ghost", "data-fkey": "route:add", onclick: () => { if (inspEditable()) { (st.next ||= []).push({goto: "end"}); INSP.focus = `route:${st.next.length - 1}:if`; commit("Add a route"); } }}, icon("plus"), "Add a route"));
  routes.append(h("p", {class: "t-caption"}, "Example: when ", h("code", {class: "mono"}, "$practice.accuracy >= 0.8"), " go to main; otherwise go to practice again, at most 3 times."));
  el.append(routes);
  inspFoot(m.start !== name ? h("button", {type: "button", class: "btn sm", onclick: () => { if (inspEditable()) { m.start = name; commit("Change the first phase"); } }}, icon("play"), "Make it the first phase") : null,
    h("button", {type: "button", class: "btn sm ghost danger-quiet", "data-fkey": "foot:del", onclick: () => inspDeleteState(path, name)}, icon("trash"), "Delete phase"));
}
function inspDeleteState(path, name) {
  if (!inspEditable()) return;
  const m = getNode(path); if (!m?.states?.[name]) return;
  delete m.states[name];
  for (const s2 of Object.values(m.states)) s2.next = (s2.next || []).filter((t) => (typeof t === "string" ? t : t.goto) !== name);
  if (m.start === name) m.start = Object.keys(m.states)[0] || "";
  S.sel = {kind: "machine", path};
  commit(`Delete the phase “${name}”`);
  inspUndoToast(`Deleted the phase “${name}”.`);
}

/* ================================================================== routine rules ("when → do") */
const RULE_ACTIONS = {
  end_routine: {label: "End the screen", param: null},
  start: {label: "Start an item", param: "component"},
  stop: {label: "Stop an item", param: "component"},
  set: {label: "Set variables", param: "set"},
  marker: {label: "Send a marker", param: "text"},
  goto: {label: "Go to a workflow phase", param: "state"},
  log: {label: "Write to the log", param: "text"},
};
function renderRulesEditor(el, r) {
  const rules = Array.isArray(r.rules) ? r.rules : [];
  const compIds = (r.components || []).map((c) => c.id);
  const states = new Set(); walkFlow((n) => { if (n?.statemachine) Object.keys(n.states || {}).forEach((x) => states.add(x)); }); states.add("end");
  if (!rules.length) el.append(h("p", {class: "t-small t-2"}, "For example: when 3 s have passed, show a hint; when the participant presses Q, end the screen."));
  rules.forEach((rule, i) => {
    rule.do = Array.isArray(rule.do) ? rule.do : (rule.do ? [rule.do] : []);
    const wid = `rule-${i}-when`;
    const box = h("div", {class: "route rule", "data-prop": `rules.${i}`});
    const repeat = ui.switch(!!rule.repeat, (v) => inspLater(() => { if (v) rule.repeat = true; else delete rule.repeat; commit("Change a rule"); }), {label: "Every time it becomes true"});
    box.append(h("div", {class: "route-head"}, h("span", {class: "route-n"}, String(i + 1)), h("label", {for: wid}, "When"), h("span", {class: "grow"}),
      h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Delete rule ${i + 1}`, title: "Delete rule",
        onclick: () => { if (!inspEditable()) return; rules.splice(i, 1); if (!rules.length) delete r.rules; commit("Delete a rule"); inspUndoToast("Deleted the rule."); }}, icon("trash"))));
    const when = h("input", {class: "input expr", id: wid, list: "expr-vars", value: rule.when || "", placeholder: "$t > 3", spellcheck: "false", "data-fkey": `rule:${i}:when`,
      onchange: (e) => inspLater(() => { const v = e.target.value.trim(); rule.when = v ? (v.startsWith("$") ? v : "$" + v) : "$False"; commit("Change a rule"); })});
    const say = rule.when ? inspInWords(rule.when) : "";
    put(box, when, say && say !== rule.when ? h("div", {class: "say"}, `In words: ${say}.`) : null, repeat, h("div", {class: "route-goto"}, h("b", {}, "Do")));
    rule.do.forEach((a0, j) => {
      const a = typeof a0 === "string" ? {[a0]: true} : (a0 || {});
      const kind = Object.keys(a)[0] || "end_routine";
      const sel = h("select", {class: "input", "aria-label": `Rule ${i + 1}, action ${j + 1}`, "data-fkey": `rule:${i}:do:${j}`, onchange: (e) => inspLater(() => {
        const k = e.target.value;
        rule.do[j] = {[k]: k === "end_routine" ? true : k === "set" ? {x: 1} : (k === "start" || k === "stop") ? "" : k === "goto" ? [...states][0] : "event"};
        commit("Change a rule"); })},
      Object.entries(RULE_ACTIONS).map(([k, d]) => { const o = h("option", {value: k}, d.label); if (k === kind) o.selected = true; return o; }));
      let param = null;
      const pt = RULE_ACTIONS[kind]?.param;
      if (pt === "component") param = h("select", {class: "input" + (a[kind] ? "" : " invalid"), "aria-label": "Which item", "aria-invalid": a[kind] ? null : "true", onchange: (e) => inspLater(() => { rule.do[j] = {[kind]: e.target.value}; commit("Change a rule"); })},
        a[kind] && compIds.includes(a[kind]) ? null : h("option", {value: "", selected: "", disabled: ""}, a[kind] ? `${a[kind]} (missing)` : "Choose an item…"),
        compIds.map((c) => { const o = h("option", {value: c}, c); if (a[kind] === c) o.selected = true; return o; }));
      else if (pt === "state") param = h("select", {class: "input", "aria-label": "Which phase", onchange: (e) => inspLater(() => { rule.do[j] = {goto: e.target.value}; commit("Change a rule"); })},
        [...states].map((c) => { const o = h("option", {value: c}, c === "end" ? "The end" : c); if (a.goto === c) o.selected = true; return o; }));
      else if (pt === "set") param = inspKvEditor(typeof a.set === "object" && a.set ? a.set : {}, (v) => { rule.do[j] = {set: v}; commit("Change a rule"); }, {keyLabel: "Variable", valueLabel: "New value", add: "Add a variable"});
      else if (pt === "text") param = h("input", {class: "input", value: a[kind] ?? "", "aria-label": RULE_ACTIONS[kind].label, onchange: (e) => inspLater(() => { rule.do[j] = {[kind]: e.target.value}; commit("Change a rule"); })});
      box.append(h("div", {class: "rule-do" + (pt === "set" ? " stack" : "")}, sel, param,
        h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Remove action ${j + 1}`, title: "Remove", onclick: () => { if (inspEditable()) { rule.do.splice(j, 1); commit("Change a rule"); } }}, icon("close"))));
    });
    box.append(h("button", {type: "button", class: "btn sm ghost", onclick: () => { if (inspEditable()) { rule.do.push({end_routine: true}); commit("Change a rule"); } }}, icon("plus"), "Add an action"));
    el.append(box);
  });
  el.append(h("button", {type: "button", class: "btn sm", "data-fkey": "rule:add", onclick: () => {
    if (!inspEditable()) return;
    r.rules = Array.isArray(r.rules) ? r.rules : [];
    r.rules.push({when: "$t > 1", do: [{end_routine: true}]});
    INSP.focus = `rule:${r.rules.length - 1}:when`;
    commit("Add a rule");
  }}, icon("plus"), "Add a rule"));
}

/* ================================================================== a device */
const DEVICE_SWITCHES = [["required", "Stop the session if it can't connect", "Off: the session goes on without it (the data say so)."],
  ["record", "Save its data", "Its streams are written into the session folder."], ["markers", "Send it event markers", "Every event marker of the experiment also goes to it."]];
const SIM_TUNING = new Set(["clock_offset", "clock_drift_ppm", "transport_jitter", "seed"]);
/* Plain names of device options (the file key is the caption in Expert). */
const DEVICE_OPT_WORDS = {port: "Port", code_map: "Marker codes", srate: "Samples per second", samplerate: "Samples per second", pulse_ms: "Pulse length (ms)",
  record_releases: "Also record releases", address: "Address", inputs: "Inputs", light_inputs: "Light-sensor inputs", clock_offset: "Clock offset (s)",
  clock_drift_ppm: "Clock drift (ppm)", transport_jitter: "Transport jitter (s)", seed: "Random seed", baudrate: "Baud rate", protocol: "Protocol", name: "Name",
  stream_type: "Stream type", source_id: "Source ID", host: "Host", calibration_points: "Calibration points", serial: "Serial number", lsl_name: "LSL stream name",
  lsl_type: "LSL stream type", reset_code: "Reset code", poll_hz: "Checks per second", follow_mouse: "Follow the mouse", noise_px: "Noise (px)",
  heart_rate: "Heart rate (beats per minute)", channels: "Channels", format: "Format", timeout: "Timeout (s)", connect_timeout: "Connection timeout (s)",
  calibration_timeout: "Calibration timeout (s)", frequency: "Frequency (Hz)", eye: "Eye", mode: "Mode", model: "Model", device: "Device", target: "Target",
  threshold_db: "Threshold (dB)", min_ms: "Shortest sound (ms)", release_ms: "Release (ms)", connection: "Connection", bits: "Trigger lines (bits)",
  wait_for_consumers: "Wait for a recorder", gaze_source: "Gaze source", gaze_channels: "Gaze channels", marker_format: "Marker format",
  digital_inputs: "Digital inputs", analog_inputs: "Analog inputs", license_file: "Licence file", input_name: "Input name"};
function renderDeviceProps(el, d, index) {
  const info = S.schema.devices[d.type] || {options: {}, capabilities: []};
  const base = INSP.base ? (INSP.base.devices || []).find((x) => x.id === d.id) : null;
  const rename = async () => {
    if (!inspEditable()) return;
    const taken = new Set(S.exp.devices.map((x) => x.id)); taken.delete(d.id);
    const v = await ui.prompt({title: `Rename the device “${d.id}”`, label: "Name", value: d.id, ok: "Rename", transform: (x) => ui.slug(x),
      validate: (x) => (!x ? "Type a name first." : taken.has(x) ? `There is already a device “${x}”.` : null)});
    if (v && v !== d.id) { const old = d.id; d.id = v; commit(`Rename the device “${old}”`); }
  };
  inspHead({tile: "tint-hw", ic: inspDeviceIcon(d), over: "Device", overClass: "c-hw", key: d.type, name: d.id, rename,
    help: helpLink("reference/devices", d.type, inspDeviceWords(d)),
    menu: () => [{label: "Rename…", icon: "design", run: rename}, {label: "Test this device", icon: "play", run: () => $("#props .dtb-test")?.click()},
      {label: `Help for ${inspDeviceWords(d)}`, icon: "book", run: () => openHelp("reference/devices", d.type)},
      {sep: true}, {label: "Remove device", icon: "trash", danger: true, run: () => inspRemoveDevice(index)}]});
  el.append(h("p", {class: "insp-lead t-small"}, h("b", {}, inspDeviceWords(d)), info.description ? h("span", {class: "t-2"}, " · " + info.description) : null));
  if (info.available === false) el.append(h("div", {class: "insp-sec"}, h("div", {class: "alert warning"}, icon("warning"), h("div", {}, h("b", {}, "Needs setup on this computer"), info.unavailable_reason || "",
    h("div", {class: "t-caption"}, "Test runs and Try it use its simulator until then.")))));
  // connection
  const con = inspSec("Connection");
  const types = Object.keys(S.schema.devices);
  const tid = "insp-dev-type";
  con.append(h("div", {class: "field", "data-prop": "type"}, h("div", {class: "lbl-row"}, h("label", {for: tid}, "Kind of device"), !isSimple() ? h("span", {class: "key mono"}, "type") : null),
    h("select", {class: "input", id: tid, "data-fkey": "f:type", onchange: (e) => inspLater(() => { d.type = e.target.value; d.options = {}; commit(`Change the device “${d.id}”`); })},
      types.map((t) => { const o = h("option", {value: t}, (typeof DEVICE_LABEL !== "undefined" && DEVICE_LABEL[t]) || inspCapWords(t)); if (t === d.type) o.selected = true; return o; }))));
  if (d.type === "trigger_adapter" && info.targets) {
    const t = info.targets[(d.options || {}).target || "generic"];
    if (t) con.append(h("div", {class: "dev-wiring"}, h("b", {}, t.name), h("div", {}, h("span", {class: "t-3"}, "Wiring: "), t.wiring),
      h("div", {}, h("span", {class: "t-3"}, "Recorded as: "), t.recorded_as),
      h("div", {class: "t-caption"}, `${t.bits ? `${t.bits} trigger line${t.bits > 1 ? "s" : ""}, codes 1–${(1 << t.bits) - 1}` : "Markers as text labels"}, usually through ${t.connection}.`)));
  }
  if ((info.capabilities || []).includes("input")) con.append(h("p", {class: "t-caption"},
    "Its inputs can be responses: add “Button box / external input” to a screen. Name the inputs below (e.g. 1: left, 2: right); an input named “light” is a light sensor on the screen, and the session report then measures the real display latency."));
  d.options ||= {};
  const more = [];
  for (const [k, p] of Object.entries(info.options || {})) {
    if (SIM_TUNING.has(k) && isSimple() && d.options[k] === undefined) continue;
    const f = field(k, p, d.options[k], (v) => { if (v === null || v === undefined || v === "") delete d.options[k]; else d.options[k] = v; commit(`Change the device “${d.id}”`); },
      {noExpr: true, label: DEVICE_OPT_WORDS[k] || inspCapWords(k), fkey: "opt:" + k, prop: "options." + k, hasBase: !!base, baseValue: base?.options?.[k]});
    if (SIM_TUNING.has(k) && isSimple()) more.push([f, true]); else con.append(f);
  }
  if (more.length) con.append(moreOptions(more, "dev-sim", "Simulator tuning"));
  el.append(con);
  // recording
  const rec = inspSec("Recording");
  for (const [k, label, caption] of DEVICE_SWITCHES)
    rec.append(field(k, {type: "bool", default: true}, d[k] ?? true, (v) => { if (v === true) delete d[k]; else d[k] = v; commit(`Change the device “${d.id}”`); },
      {label, caption, noExpr: true, hasBase: !!base, baseValue: base?.[k]}));
  el.append(rec);
  if ((info.capabilities || []).includes("calibration")) {
    const cal = inspSec("Calibration");
    cal.append(field("calibrate", {type: "bool", default: false}, d.calibrate ?? false, (v) => { if (v) d.calibrate = true; else delete d.calibrate; commit(`Change the device “${d.id}”`); },
      {label: "Calibrate at the start of each session", caption: "Or add “Calibrate eye tracker” to a screen to calibrate at a chosen moment.", noExpr: true}));
    el.append(cal);
  }
  const test = inspSec("Test");
  test.append(deviceTestBox(index));
  el.append(test);
  inspFoot(h("button", {type: "button", class: "btn sm ghost danger-quiet", "data-fkey": "foot:del", onclick: () => inspRemoveDevice(index)}, icon("trash"), "Remove device"));
}
function inspRemoveDevice(index) {
  if (!inspEditable()) return;
  const d = S.exp.devices[index]; if (!d) return;
  S.exp.devices.splice(index, 1); S.sel = null;
  commit(`Remove the device “${d.id}”`);
  inspUndoToast(`Removed the device “${d.id}”.`);
}

/* ---------------- device tests: [Test this device] [Use the simulator] + results (inspector and the Test page) */
const DEVTEST = new Map();     // "id|type" -> {running, simulate, result, error, at}
function deviceTestBox(index) {
  const d = S.exp.devices[index];
  if (!d) return h("div");
  const info = S.schema.devices[d.type] || {capabilities: []};
  const key = `${d.id}|${d.type}`;
  const isInput = (info.capabilities || []).includes("input");
  const box = h("div", {class: "dtb", "data-device": d.id});
  const draw = () => {
    const st = DEVTEST.get(key) || {};
    const busy = !!st.running;
    const testBtn = h("button", {type: "button", class: "btn sm dtb-test", "aria-busy": busy && !st.simulate ? "true" : null, disabled: busy ? "" : null,
      title: "Connect to the real device: its data rate, inputs and a test marker", onclick: () => run(false)},
    busy && !st.simulate ? h("span", {class: "spin"}) : icon("play"), busy && !st.simulate ? "Testing…" : "Test this device");
    const simBtn = h("button", {type: "button", class: "btn sm ghost dtb-sim", "aria-busy": busy && st.simulate ? "true" : null, disabled: busy ? "" : null,
      title: "The same test with its simulator: no hardware needed", onclick: () => run(true)},
    busy && st.simulate ? h("span", {class: "spin"}) : icon("chip"), busy && st.simulate ? "Testing…" : "Use the simulator");
    const out = h("div", {class: "dtb-out", role: "status", "aria-live": "polite"});
    if (busy) out.append(h("p", {class: "t-small t-2"}, isInput ? "Testing for 5 s: press the buttons or speak now…" : "Connecting and listening for 3 s…"));
    else if (st.error) out.append(inspStatusLine("error", "The test couldn't run", st.error));
    else if (st.result) {
      const r = st.result;
      const when = `${st.simulate ? "Simulator" : "Device"} · ${clock(new Date(st.at))}`;
      if (!r.connected) out.append(inspStatusLine("error", "Not connected", [r.error || "unknown problem", r.hint ? ` ${r.hint}` : ""].join(""), when));
      else {
        const bad = (m) => /no data|only|did not|failed|no inputs/i.test(m);
        out.append(h("div", {class: "dtb-head"}, h("span", {class: "chip " + ((r.messages || []).some(bad) ? "warning" : "success")}, icon((r.messages || []).some(bad) ? "warning" : "success"),
          (r.messages || []).some(bad) ? "Connected, with something to check" : "OK"), h("span", {class: "t-caption"}, when)));
        const ul = h("ul", {class: "dtb-list"});
        for (const m of r.messages || []) ul.append(h("li", {class: bad(m) ? "warn" : "ok"}, icon(bad(m) ? "warning" : "check"), h("span", {}, m)));
        for (const [name, s] of Object.entries(r.streams || {})) if (s.first) ul.append(h("li", {class: "info"}, icon("info"), h("span", {class: "t-caption"}, `${name} first sample: ${s.first.join(", ")}`)));
        out.append(ul);
      }
    } else out.append(h("p", {class: "t-caption"}, "Not tested yet."));
    box.replaceChildren(h("div", {class: "dtb-btns"}, testBtn, simBtn), out);
  };
  const run = async (simulate) => {
    const dev = S.exp.devices.find((x) => x.id === d.id) || d;
    DEVTEST.set(key, {running: true, simulate});
    draw();
    try {
      const r = await api("/api/device_test", {experiment: S.exp, path: S.path, id: dev.id, simulate, seconds: isInput ? 5 : 3});
      const ok = !!r.connected && !(r.messages || []).some((m) => /no data|only|did not|failed|no inputs/i.test(m));
      DEVTEST.set(key, {result: r, simulate, at: Date.now()});
      S.deviceTests = {...(S.deviceTests || {}), [dev.id]: {ok, at: Date.now(), simulated: simulate}};
      ui.announce(`${dev.id}: ${r.connected ? (ok ? "test passed" : "connected, with something to check") : "not connected"}`);
    } catch (e) {
      DEVTEST.set(key, {error: e.message, simulate, at: Date.now()});
      S.deviceTests = {...(S.deviceTests || {}), [dev.id]: {ok: false, at: Date.now(), simulated: simulate}};
    }
    // redraw every box of this device (the inspector and the Test page can both show it)
    document.querySelectorAll(`.dtb[data-device="${CSS.escape(d.id)}"]`).forEach((b) => b._draw?.());
    if (typeof renderDevices === "function" && S.ws === "build") renderDevices();
    if (typeof renderReadiness === "function" && S.ws === "test") renderReadiness();   // "Devices to test" counts it
  };
  box._draw = draw;
  draw();
  return box;
}
function inspStatusLine(level, title, text, when) {
  return h("div", {class: "alert " + (level === "error" ? "danger" : level)}, icon(level === "error" ? "error" : level), h("div", {}, h("b", {}, title), text ? h("div", {}, text) : null, when ? h("div", {class: "t-caption"}, when) : null));
}

/* ================================================================== nothing selected: the experiment overview */
function inspNextSteps() {
  const g = typeof problemGroups === "function" ? problemGroups() : {error: []};
  const nMeasures = Array.isArray(S.exp.measures) ? S.exp.measures.length : Object.keys(S.exp.measures || {}).length;
  const f = (S.files || []).find((x) => x.path === S.path);
  const ts = typeof testState === "function" ? testState() : "none";
  return [
    {done: S.exp.flow.length > 0 && !g.error.length, label: "Build your screens", go: () => EDGE.setView("story")},
    {done: !!S.triedAt, label: "Try it yourself", go: () => (typeof tryNow === "function" ? tryNow("all") : tryIt("all"))},
    {done: nMeasures > 0, label: "Say what you measure", go: () => EDGE.go("measures")},
    {done: ts === "passed", label: "Start a test run", go: () => (typeof dryRun === "function" ? dryRun() : EDGE.go("test"))},
    {done: !S.dirty && !!S.path, label: "Save", go: () => save()},
    {done: (f?.sessions?.real || 0) > 0, label: "Run a pilot participant", go: () => EDGE.go("run")},
  ];
}
function inspOverview(el) {
  const exp = S.exp;
  inspHead({tile: "t-exp", ic: "test", over: "Experiment", name: exp.name || docName(), rename: () => openSettings("general"),
    help: helpLink("BUILDER_GUIDE", "", "the builder")});
  const head = h("section", {class: "insp-sec ov"});
  head.append(exp.description ? h("p", {class: "ov-desc"}, exp.description)
    : h("p", {class: "ov-desc t-3"}, h("button", {type: "button", class: "linkbtn", onclick: () => openSettings("general")}, "Add a description"), " so you remember what it is for."));
  let est = null;
  try { est = typeof storyEstimate === "function" ? storyEstimate(() => { if (!S.sel && S.ws === "build") renderProps(); }) : null; } catch { est = null; }
  if (est && !est.error) head.append(h("p", {class: "ov-est"}, icon("pause_blank"), EDGE.fmt.estimate(est)));
  el.append(head);
  const hiddenKey = "nextsteps.hidden." + (S.path || "untitled");
  const hidden = !!EDGE.prefs.get(hiddenKey, false);
  const steps = inspNextSteps();
  if (!hidden) {
    const sec = inspSec("Next steps", {actions: h("button", {type: "button", class: "btn sm ghost", onclick: () => { EDGE.prefs.set(hiddenKey, true); renderProps(); }}, "Hide")});
    const ul = h("ul", {class: "steps"});
    for (const s of steps) ul.append(h("li", {class: s.done ? "done" : ""}, h("button", {type: "button", class: "step", onclick: s.go, "aria-label": `${s.label}${s.done ? ": done" : ""}`},
      s.done ? icon("success", "st-ic") : h("span", {class: "st-ic todo", "aria-hidden": "true"}), h("span", {class: "lbl"}, s.label), s.done ? null : icon("chev-right", "chev"))));
    sec.append(ul);
    el.append(sec);
  }
  const w = exp.settings?.window || {}, dw = S.schema.default_settings?.window || {};
  const size = w.size || dw.size || [1280, 720];
  const bg = w.background ?? dw.background ?? "#000000";
  const win = inspSec("Window");
  win.append(h("p", {class: "ov-win"}, h("span", {class: "sw", style: `background:${typeof bg === "string" ? bg : "#000"}`}), `${size[0]} × ${size[1]} · ${typeof bg === "string" ? bg : "custom"} · ${(w.fullscreen ?? dw.fullscreen) ? "full screen" : "in a window"}`));
  const nMeasures = Array.isArray(exp.measures) ? exp.measures.length : Object.keys(exp.measures || {}).length;
  win.append(h("div", {class: "ov-btns"},
    h("button", {type: "button", class: "btn sm", "data-fkey": "ov:settings", onclick: () => openSettings()}, icon("settings"), "Experiment settings…"),
    h("button", {type: "button", class: "btn sm", onclick: () => EDGE.go("measures")}, icon("measures"), `Measures (${nMeasures})`),
    h("button", {type: "button", class: "btn sm", onclick: () => { if (typeof revealSide === "function") revealSide("devices"); else if (typeof showSide === "function") showSide("devices", {open: true}); }}, icon("device"), `Devices (${exp.devices.length})`)));
  if (hidden) win.append(h("button", {type: "button", class: "linkbtn ov-show", onclick: () => { EDGE.prefs.set(hiddenKey, null); renderProps(); }}, "Show next steps"));
  el.append(win);
}

/* ================================================================== the Experiment settings dialog (W13) */
const SETTINGS_SECTIONS = [["general", "General"], ["screen", "Screen"], ["participant", "Participant info"], ["data", "Data files"],
  ["markers", "Markers", true], ["variables", "Variables", true], ["repro", "Reproducibility"]];
const EXPORT_FORMATS = [["csv", "CSV"], ["xlsx", "Excel (.xlsx)"], ["tsv", "TSV"], ["json", "JSON"], ["jsonl", "JSON lines"], ["parquet", "Parquet"], ["mat", "MATLAB (.mat)"], ["bids", "BIDS"]];
const SETTINGS_UI = {section: "general", body: null, json: new Set()};
function openSettings(section = "general") {
  if (!S.exp || S.noDoc) return toast("Open or create an experiment first.");
  const avail = SETTINGS_SECTIONS.filter(([, , exp]) => !exp || !isSimple()).map(([k]) => k);
  SETTINGS_UI.section = avail.includes(section) ? section : "general";
  const nav = h("div", {class: "set-nav", role: "tablist", "aria-orientation": "vertical", "aria-label": "Settings sections"});
  const body = h("div", {class: "set-body", role: "tabpanel", tabindex: "-1"});
  SETTINGS_UI.body = body; SETTINGS_UI.nav = nav;
  const drawNav = () => {
    nav.replaceChildren(...SETTINGS_SECTIONS.filter(([, , exp]) => !exp || !isSimple()).map(([k, label]) => h("button", {type: "button", role: "tab", id: "set-tab-" + k,
      "aria-selected": k === SETTINGS_UI.section ? "true" : "false", tabindex: k === SETTINGS_UI.section ? "0" : "-1", "aria-controls": "set-panel",
      // the clicked tab is replaced: focus the new one, so focus stays in the dialog (Esc still closes it)
      onclick: () => { SETTINGS_UI.section = k; drawNav(); settingsDraw(); nav.querySelector(`#set-tab-${k}`)?.focus(); }}, label)));
  };
  nav.addEventListener("keydown", (e) => {
    const tabs = [...nav.querySelectorAll("[role=tab]")]; const i = tabs.indexOf(document.activeElement);
    if (i < 0 || !["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const j = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (i + (e.key === "ArrowDown" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[j].click(); nav.querySelector(`#set-tab-${SETTINGS_UI.section}`)?.focus();
  });
  body.id = "set-panel";
  drawNav(); settingsDraw();
  const off = EDGE.on("doc:changed", () => { if (SETTINGS_UI.body?.isConnected) settingsDraw(); });
  const off2 = EDGE.on("mode", () => { if (SETTINGS_UI.body?.isConnected) { drawNav(); settingsDraw(); } });
  ui.dialog({title: "Experiment settings", icon: "settings", size: "lg", body: h("div", {class: "set-grid"}, nav, body),
    buttons: [{label: "Done", value: null, kind: "primary"}], initialFocus: "#set-tab-" + SETTINGS_UI.section,
    onOpen: (dlg) => {
      dlg.classList.add("settings-dialog");
      dlg.querySelector("footer")?.prepend(h("span", {class: "t-caption set-note"}, "Changes apply as you make them; Undo reverts them."));
    }}).then(() => { off(); off2(); SETTINGS_UI.body = null; });
}
function settingsDraw() {
  const body = SETTINGS_UI.body; if (!body) return;
  const a = document.activeElement;
  const keep = a && body.contains(a) ? a.dataset?.fkey : null;
  const st = S.exp.settings; st.window ||= {}; st.data ||= {};
  const def = S.schema.default_settings || {window: {}, data: {}};
  const w = st.window, dw = def.window || {};
  const sec = SETTINGS_UI.section;
  const out = [];
  const title = SETTINGS_SECTIONS.find(([k]) => k === sec)?.[1] || "";
  body.setAttribute("aria-labelledby", "set-tab-" + sec);
  out.push(h("h3", {class: "t-title-s set-title"}, title));
  const nf = (name, p, value, onChange, opts = {}) => field(name, p, value, onChange, {noExpr: true, ...opts});
  if (sec === "general") {
    out.push(nf("name", {type: "str"}, S.exp.name, (v) => { S.exp.name = v || "experiment"; commit("Rename the experiment"); }, {label: "Name", help: "Shown in the data files; the file keeps its own name."}));
    out.push(nf("description", {type: "text"}, S.exp.description, (v) => setProp(S.exp, "description", v, "Change the description"), {label: "Description", help: "What it is for, in a sentence or two."}));
  } else if (sec === "screen") {
    const size = w.size || dw.size || [1280, 720];
    const num = (i) => h("input", {class: "input num", value: size[i], inputmode: "numeric", "aria-label": i ? "Height in pixels" : "Width in pixels", "data-fkey": "set:size:" + i,
      onchange: (e) => inspLater(() => { const v = parseInt(e.target.value, 10); if (!(v > 0)) { settingsDraw(); return; } const s = [...size]; s[i] = v; setProp(w, "size", s, "Change the window size"); })});
    out.push(h("div", {class: "field", "data-prop": "window.size"}, h("div", {class: "lbl-row"}, h("span", {class: "label"}, "Size of the experiment window")),
      h("div", {class: "set-size"}, num(0), h("span", {}, "×"), num(1), h("span", {class: "t-2"}, "pixels"),
        h("button", {type: "button", class: "btn sm ghost", onclick: () => setProp(w, "size", [Math.round(screen.width * (devicePixelRatio || 1)), Math.round(screen.height * (devicePixelRatio || 1))], "Use this monitor's size")}, "Use this monitor's size"))));
    out.push(h("div", {class: "field", "data-prop": "window.fullscreen"}, h("div", {class: "lbl-row"}, h("span", {class: "label", id: "set-fs-l"}, "Show it")),
      inspSeg([{value: "1", label: "Full screen"}, {value: "0", label: "In a window"}], (w.fullscreen ?? dw.fullscreen) ? "1" : "0", (v) => setProp(w, "fullscreen", v === "1", "Change how the window is shown"), "set-fs-l")));
    const mon = w.screen ?? dw.screen ?? 0;
    out.push(h("div", {class: "field", "data-prop": "window.screen"}, h("div", {class: "lbl-row"}, h("label", {for: "set-mon"}, "On monitor")),
      h("select", {class: "input", id: "set-mon", "data-fkey": "set:mon", onchange: (e) => inspLater(() => setProp(w, "screen", +e.target.value || null, "Change the monitor"))},
        [0, 1, 2, 3].map((i) => { const o = h("option", {value: i}, i === 0 ? "Main (1)" : `Monitor ${i + 1}`); if (+mon === i) o.selected = true; return o; }))));
    const bgField = nf("background", {type: "color", default: dw.background}, w.background, (v) => setProp(w, "background", v, "Change the background"), {label: "Background", key: false});
    out.push(bgField);
    const units = w.units ?? dw.units ?? "px";
    out.push(h("div", {class: "field", "data-prop": "window.units"}, h("div", {class: "lbl-row"}, h("span", {class: "label", id: "set-units-l"}, "Measure sizes in")),
      inspSeg([{value: "px", label: "Pixels"}, {value: "norm", label: "Fraction of the screen"}, {value: "height", label: "Fraction of the height"}, {value: "deg", label: "Degrees"}],
        units, (v) => setProp(w, "units", v, "Change the units"), "set-units-l"),
      h("div", {class: "help"}, {px: "Pixels of the experiment window.", norm: "−1 to 1 across the screen, from the centre.", height: "1 is the height of the window.", deg: "Degrees of visual angle at the viewing distance."}[units] || "")));
    if (units === "deg") {
      const m = w.monitor || dw.monitor || {};
      const cm = (k, label) => nf(k, {type: "float", unit: "cm"}, (w.monitor || {})[k] ?? null, (v) => { w.monitor = {...(w.monitor || {})}; if (v === null) delete w.monitor[k]; else w.monitor[k] = v; commit("Change the monitor size"); },
        {label, placeholder: String(m[k] ?? ""), key: false, prop: "window.monitor." + k});
      out.push(h("div", {class: "row2"}, cm("width_cm", "Screen width"), cm("distance_cm", "Viewing distance")), h("p", {class: "t-caption"}, "Degrees need the screen width and the viewing distance."));
    }
  } else if (sec === "participant") {
    st.participant ||= {};
    out.push(h("p", {class: "t-small t-2"}, "Asked when a session starts (on the Run page). The value here is filled in by default; participant and session are always asked."));
    out.push(inspKvEditor(st.participant, (v) => { st.participant = v; commit("Change the participant info"); },
      {keyLabel: "Field", valueLabel: "Default value", add: "Add a field, e.g. age, group", parse: (x) => x, mono: false, fixedKeys: ["participant", "session"]}));
  } else if (sec === "data") {
    const dd = def.data || {};
    out.push(nf("dir", {type: "str"}, st.data.dir, (v) => setProp(st.data, "dir", v, "Change the data folder"), {label: "Data folder", placeholder: dd.dir || "data", key: false, prop: "data.dir",
      help: "Next to the experiment file. Each session gets its own folder inside it."}));
    const pattern = st.data.filename || dd.filename || "{participant}_{session}_{experiment}_{date}";
    const now = new Date(), p2 = (x) => String(x).padStart(2, "0");
    const example = pattern.replace(/\{participant\}/g, "007").replace(/\{session\}/g, "1").replace(/\{experiment\}/g, S.exp.name || "experiment")
      .replace(/\{date\}/g, `${now.getFullYear()}-${p2(now.getMonth() + 1)}-${p2(now.getDate())}_${p2(now.getHours())}${p2(now.getMinutes())}${p2(now.getSeconds())}`).replace(/\{[^}]*\}/g, "…");
    if (!isSimple()) out.push(nf("filename", {type: "str"}, st.data.filename, (v) => setProp(st.data, "filename", v, "Change the file names"), {label: "Session folder name", placeholder: dd.filename, key: false, prop: "data.filename",
      help: "Uses {participant}, {session}, {experiment}, {date} and participant-info fields."}));
    out.push(h("p", {class: "t-caption set-example"}, "e.g. ", h("span", {class: "mono"}, `${st.data.dir || dd.dir || "data"}/${example}/`)));
    const ex = new Set(st.data.exports || dd.exports || ["csv"]);
    out.push(h("div", {class: "field", "data-prop": "data.exports"}, h("div", {class: "lbl-row"}, h("span", {class: "label"}, "Also save as")),
      h("div", {class: "set-checks"}, EXPORT_FORMATS.map(([k, label]) => {
        const id = "set-ex-" + k;
        const cb = h("input", {type: "checkbox", id, "data-fkey": id, onchange: (e) => inspLater(() => {
          const next = new Set(st.data.exports || dd.exports || ["csv"]); if (e.target.checked) next.add(k); else next.delete(k);
          setProp(st.data, "exports", [...next], "Change the export formats"); })});
        cb.checked = ex.has(k);
        return h("label", {class: "check", for: id}, cb, label);
      })), h("div", {class: "help"}, "Written at the end of every session, next to the trial data.")));
    if (!isSimple()) {
      const seeded = st.seed !== null && st.seed !== undefined;
      out.push(h("div", {class: "field", "data-prop": "seed"}, h("div", {class: "lbl-row"}, h("span", {class: "label", id: "set-seed-l"}, "Randomness")),
        inspSeg([{value: "new", label: "New every session"}, {value: "same", label: "The same every time"}], seeded ? "same" : "new",
          (v) => setProp(st, "seed", v === "same" ? (st.seed ?? 1) : null, "Change the randomness"), "set-seed-l"),
        seeded ? h("div", {class: "set-seed"}, h("label", {for: "set-seed"}, "Seed"), h("input", {class: "input num", id: "set-seed", value: st.seed, inputmode: "numeric", "data-fkey": "set:seed",
          onchange: (e) => inspLater(() => { const v = parseInt(e.target.value, 10); setProp(st, "seed", isNaN(v) ? null : v, "Change the seed"); })})) : null,
        h("div", {class: "help"}, "The seed of each session is saved in session.json either way.")));
      out.push(nf("save_frame_log", {type: "bool", default: true}, st.data.save_frame_log ?? true, (v) => setProp(st.data, "save_frame_log", v ? null : false, "Change the frame log"),
        {label: "Save a log of every screen refresh", caption: "Needed for the timing report."}));
    }
  } else if (sec === "markers") {
    st.markers ||= {};
    out.push(h("p", {class: "t-small t-2"}, "Event markers go to every device that takes them. Give a label a number code here; unlisted labels get codes automatically."));
    out.push(inspJsonToggle("markers", () => inspKvEditor(st.markers.codes || {}, (v) => setProp(st.markers, "codes", Object.keys(v).length ? v : null, "Change the marker codes"),
      {keyLabel: "Label", valueLabel: "Code", add: "Add a marker", parse: (x) => parseVal("int", x)}),
    () => nf("codes", {type: "dict"}, st.markers.codes, (v) => setProp(st.markers, "codes", v, "Change the marker codes"), {label: "Marker codes (JSON)", key: false, prop: "markers.codes"})));
  } else if (sec === "variables") {
    out.push(h("p", {class: "t-small t-2"}, "Variables keep a value across trials (a score, a counter). Set them with “Set a variable” or a rule; use them in formulas."));
    out.push(inspJsonToggle("variables", () => inspKvEditor(S.exp.variables || {}, (v) => { S.exp.variables = v; commit("Change the variables"); },
      {keyLabel: "Variable", valueLabel: "Starts at", add: "Add a variable"}),
    () => nf("variables", {type: "dict"}, S.exp.variables, (v) => { S.exp.variables = v || {}; commit("Change the variables"); }, {label: "Variables (JSON)", key: false})));
  } else if (sec === "repro") {
    const f = (S.files || []).find((x) => x.path === S.path);
    out.push(h("p", {class: "t-small t-2"}, "After piloting, lock this version: EDGE records the software versions, the file fingerprints and a golden participant, so you can show later that nothing changed."));
    out.push(h("div", {class: "set-actions"},
      h("button", {type: "button", class: "btn", onclick: () => (typeof lockExperiment === "function" ? lockExperiment() : null)}, icon("lock"), f?.locked ? "Lock again…" : "Lock this version…"),
      h("button", {type: "button", class: "btn ghost", onclick: () => settingsVerify()}, icon("checklist"), "Check it against the lock")),
    h("div", {class: "set-verify", id: "set-verify"}));
    out.push(h("p", {class: "t-small t-2"}, "Having trouble? A support bundle has everything needed to ask for help, without participant data."),
      h("div", {class: "set-actions"}, h("button", {type: "button", class: "btn", onclick: () => (typeof supportBundle === "function" ? supportBundle() : null)}, icon("package"), "Make a support bundle")));
  }
  if (S.proposal) out.splice(1, 0, h("div", {class: "alert assistant set-proposed"}, icon("assistant"), h("div", {}, "Apply or discard the assistant's changes to edit the settings.")));
  body.replaceChildren(...out);
  if (S.proposal) for (const x of body.querySelectorAll("input, select, textarea, button")) { x.disabled = true; x.title = x.title || "Apply or discard the assistant's changes first"; }
  if (keep) body.querySelector(`[data-fkey="${CSS.escape(keep)}"]`)?.focus({preventScroll: true});
}
function inspSeg(options, value, onChange, labelledBy) {
  const s = ui.seg(options, value, (v) => inspLater(() => onChange(v)));
  s.setAttribute("aria-labelledby", labelledBy);
  return s;
}
/* Expert: "Edit as JSON" next to a table. */
function inspJsonToggle(key, table, json) {
  const asJson = SETTINGS_UI.json.has(key);
  const wrap = h("div", {class: "json-toggle"});
  wrap.append(asJson ? json() : table());
  if (!isSimple()) wrap.append(h("button", {type: "button", class: "linkbtn", onclick: () => { if (asJson) SETTINGS_UI.json.delete(key); else SETTINGS_UI.json.add(key); settingsDraw(); }}, asJson ? "Edit as a table" : "Edit as JSON"));
  return wrap;
}
async function settingsVerify() {
  const out = $("#set-verify"); if (!out) return;
  if (!S.path) { out.replaceChildren(inspStatusLine("warning", "Save the experiment first", "")); return; }
  out.replaceChildren(h("p", {class: "t-small"}, h("span", {class: "spin"}), " Checking…"));
  try {
    const r = await api(`/api/verify?path=${encodeURIComponent(S.path)}&golden=1`);
    const ok = r.ok !== false && !(r.problems || r.differences || []).length;
    out.replaceChildren(inspStatusLine(ok ? "success" : "warning", ok ? "Nothing changed since the lock." : "Something changed since the lock.",
      (r.problems || r.differences || r.messages || []).slice(0, 6).map((x) => (typeof x === "string" ? x : x.message || JSON.stringify(x))).join(" · ")));
  } catch (e) { out.replaceChildren(inspStatusLine("warning", "Couldn't check it", /lock/i.test(e.message) ? "This version isn't locked yet." : e.message)); }
}

/* ================================================================== $variable suggestions for formula fields */
function updateExprVars() {
  let dl = document.getElementById("expr-vars");
  if (!dl) { dl = h("datalist", {id: "expr-vars"}); document.body.append(dl); }
  const vars = new Set(["$t", "$frame", "$participant", "$session"]);
  const rid = S.routine;
  const {loops, machines} = rid ? enclosing(rid) : {loops: [], machines: []};
  for (const lp of loops) {
    for (const k of loopColumns(lp)) vars.add("$" + k);
    ["n", "total", "accuracy", "n_correct", "mean_rt", "repeat"].forEach((k) => vars.add(`$${lp.loop}.${k}`));
  }
  for (const m of machines) ["state", "visit"].forEach((k) => vars.add(`$${m.statemachine}.${k}`));
  walkFlow((n) => { if (n?.loop) ["accuracy", "n_correct", "mean_rt", "total"].forEach((k) => vars.add(`$${n.loop}.${k}`)); });
  Object.keys(S.exp.variables || {}).forEach((k) => vars.add("$" + k));
  const results = {keyboard: ["keys", "rt", "corr"], mouse: ["clicked", "x", "y", "rt", "corr"], slider: ["rating", "rt"],
    gaze_roi: ["entered", "dwell_time", "completed", "first_entry"], html: ["submitted", "rt"], device_response: ["input", "rt", "corr"]};
  for (const r of Object.values(S.exp.routines)) for (const c of r.components || [])
    for (const k of results[c.type] || []) vars.add(`$${c.id}.${k}`);
  const key = [...vars].sort().join("|");
  if (dl.dataset.key === key) return;
  dl.dataset.key = key;
  dl.replaceChildren(...[...vars].sort().map((v) => h("option", {value: v})));
}

EDGE.on("doc:loaded", () => { INSP.formulaFor = null; INSP.lastSel = ""; DEVTEST.clear(); });
/* the overview's Next steps follow saves and test runs (also the assistant's auto-save) */
const inspOverviewRefresh = () => { if (S.exp && !S.sel && S.ws === "build" && !S.noDoc && typeof renderProps === "function") renderProps(); };
EDGE.on("doc:saved", () => setTimeout(inspOverviewRefresh, 0));
EDGE.on("tested", () => setTimeout(inspOverviewRefresh, 0));
EDGE.on("tried", () => setTimeout(inspOverviewRefresh, 0));
