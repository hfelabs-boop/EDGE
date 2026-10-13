/* widgets.js: property widgets and the asset picker (SPEC §7.6 "stage.js -> widgets.js"). Owner: P4b.
 * Owns stageInput() and the friendlier editors it returns for the inspector: sliders with a number box, colour
 * swatches, segmented choices (with drawn shape glyphs), the font menu, X/Y and W/H boxes whose letters you can drag,
 * the 3 x 3 place grid and the file card; the unit helpers (winSize, toUnits, fromUnits, roundU, ...); the asset
 * picker dialog for pictures, sounds and web pages (openAssetPicker, assetList, uploadAsset); and playSound() for
 * previews in the builder (Try it plays its own sounds with playTrySound in simple.js).
 */
"use strict";

const ASSET_EXT = {
  image: [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tif", ".tiff"],
  audio: [".wav", ".mp3", ".ogg", ".flac", ".aiff", ".aif", ".m4a"],
  html: [".html", ".htm"],
};
const ASSET_WORD = {image: "picture", audio: "sound", html: "web page"};
const ASSET_FOLDER = {image: "images", audio: "sounds", html: "pages"};
const SWATCHES = ["white", "black", "grey", "red", "orange", "yellow", "green", "cyan", "blue", "purple", "magenta", "brown"];
const TONES = [[250, "Low"], [440, "Middle"], [1000, "High"], [2000, "Very high"]];

/* ---------------------------------------------------------------- units */
const winSize = () => (S.exp.settings.window || {}).size || [1280, 720];
const winUnits = () => (S.exp.settings.window || {}).units || "px";
const compUnits = (c) => (c && ["px", "norm", "height"].includes(c.units) ? c.units : winUnits());
function toUnits(v, axis, u) { const [W, H] = winSize(); return u === "norm" ? v / (axis === "x" ? W / 2 : H / 2) : u === "height" ? v / H : v; }
function fromUnits(v, axis, u) { const [W, H] = winSize(); return u === "norm" ? v * (axis === "x" ? W / 2 : H / 2) : u === "height" ? v * H : v; }
const roundU = (v, u) => (u === "norm" || u === "height" ? Math.round(v * 1000) / 1000 : Math.round(v));
const unitStep = (u) => (u === "norm" || u === "height" ? 0.01 : 1);
const decimals = (step) => Math.max(0, Math.ceil(-Math.log10(step) - 1e-9));
const expDir = () => (S.path ? S.path.replace(/[^/]*$/, "") : "");
const assetUrl = (rel) => `/api/file?path=${encodeURIComponent(expDir() + rel)}`;
const kindOf = (name) => Object.keys(ASSET_EXT).find((k) => ASSET_EXT[k].some((x) => name.toLowerCase().endsWith(x)));
const unitSuffix = (u) => ({px: "px", deg: "°"}[u] || "");

/* ---------------------------------------------------------------- property widgets */
/* Returns an input element for properties that have a friendlier editor than a text box, else null. */
function stageInput(name, p, value, onChange, opts = {}) {
  const type = p.type || "str";
  const live = opts.live || (() => {});
  if (type === "color") return colorInput(p, value, onChange, live);
  if (type === "file" && p.accept) return fileInput(p, value, onChange, opts.comp);
  if (type === "vec2") return vecInput(name, p, value, onChange, live, opts.comp);
  if (type === "choice" && opts.comp && (p.icons || ((p.choices || []).length <= 4 && (p.choices || []).every((c) => String(c).length <= 10)))) {
    const words = (p.choices || []).map((c) => choiceWord(c));
    if (p.icons || words.join("").length <= 30) return segmented(p, value, onChange);
  }
  if ((type === "float" || type === "int") && p.min !== undefined && p.max !== undefined) return sliderInput(p, value, onChange, live, opts.comp);
  if (type === "str" && p.suggest) return suggestInput(name, p, value, onChange);
  return null;
}
const choiceWord = (c) => (c === "" ? "Default" : (isSimple() && typeof CHOICE_WORDS !== "undefined" && CHOICE_WORDS[c]) || String(c).charAt(0).toUpperCase() + String(c).slice(1));

function sliderInput(p, value, onChange, live, comp) {
  if (value !== null && value !== undefined && typeof value !== "number") return null;
  let {min, max, step} = p;
  const u = compUnits(comp);
  if (p.length && u !== "px") { min = roundU(toUnits(min, "y", u), u); max = roundU(toUnits(max, "y", u), u); step = 0.005; }
  step = step ?? (max - min) / 100;
  const dec = p.type === "int" ? 0 : decimals(step);
  const fmt = (v) => +(+v).toFixed(dec);
  const rng = h("input", {type: "range", min, max, step, value: value ?? p.default ?? min, "aria-label": "Slider", tabindex: "-1"});
  const num = h("input", {class: "input num", inputmode: "decimal", value: value ?? "", placeholder: p.default != null ? String(p.default) : ""});
  rng.oninput = () => { num.value = fmt(rng.value); live(fmt(rng.value)); };
  rng.onchange = () => onChange(fmt(rng.value));
  num.onchange = () => { const v = num.value.trim(); if (v.startsWith("$")) return onChange(v); onChange(v === "" ? null : fmt(v.replace(",", "."))); };
  const suffix = p.length ? unitSuffix(u) : "";
  return h("div", {class: "st-slider"}, rng, suffix ? h("div", {class: "input-wrap"}, num, h("span", {class: "suffix"}, suffix)) : num);
}

const _cc = document.createElement("canvas").getContext("2d");
function colorHex(c) {
  if (typeof c !== "string" || !c || isExpr(c)) return null;
  _cc.fillStyle = "#000001"; _cc.fillStyle = c;
  const v = _cc.fillStyle;
  return v === "#000001" && c.toLowerCase() !== "#000001" ? null : v;
}
function colorInput(p, value, onChange, live) {
  if (value !== null && value !== undefined && typeof value !== "string") return null;
  const cur = value ?? p.default;
  const curHex = colorHex(cur);
  const sw = h("div", {class: "st-swatches", role: "group", "aria-label": "Colours"});
  const names = p.transparent ? [...SWATCHES, "none"] : SWATCHES;
  for (const c of names) {
    const none = c === "none";
    const on = none ? (cur == null || cur === "transparent" || cur === "none") : curHex && colorHex(c) === curHex;
    sw.append(h("button", {type: "button", class: "st-sw" + (none ? " none" : "") + (on ? " on" : ""), "aria-label": none ? "No colour (transparent)" : c,
      "aria-pressed": on ? "true" : "false", title: none ? "none (transparent)" : c,
      style: none ? "" : `background:${c}`, onclick: (e) => { e.preventDefault(); onChange(none ? (p.default == null ? null : "transparent") : c); }}));
  }
  const pick = h("input", {type: "color", class: "st-pick", title: "Any colour", "aria-label": "Pick any colour"});
  if (curHex && /^#[0-9a-f]{6}$/i.test(curHex)) pick.value = curHex;
  pick.oninput = (e) => live(e.target.value);
  pick.onchange = (e) => onChange(e.target.value);
  const txt = h("input", {class: "input", value: value ?? "", placeholder: p.default != null ? String(p.default) : "none", title: "A colour name or #hex",
    "aria-label": "Colour name or code", spellcheck: "false", onchange: (e) => onChange(e.target.value.trim() || null)});
  return h("div", {class: "st-color"}, sw, h("div", {class: "st-colorrow"}, pick, txt));
}

/* Shapes drawn as small inline SVGs (never Unicode pictographs). */
function shapeGlyph(kind) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", "ic"); svg.setAttribute("aria-hidden", "true");
  const el = (tag, attrs) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); svg.append(e); };
  if (kind === "rect") el("rect", {x: 4, y: 6, width: 16, height: 12, rx: 1});
  else if (kind === "circle") el("circle", {cx: 12, cy: 12, r: 7.5});
  else if (kind === "ellipse") el("ellipse", {cx: 12, cy: 12, rx: 9, ry: 5.5});
  else if (kind === "polygon") el("path", {d: "M12 4l8 6-3 9H7l-3-9z"});
  else if (kind === "line") el("path", {d: "M5 19L19 5"});
  else if (kind === "cross") el("path", {d: "M12 5v14M5 12h14"});
  else return null;
  return svg;
}
function segmented(p, value, onChange) {
  const cur = value ?? p.default;
  const group = h("div", {class: "seg st-seg" + (p.icons ? " shapes" : "")});
  for (const c of p.choices || []) {
    const glyph = p.icons ? shapeGlyph(c) : null;
    group.append(h("button", {type: "button", role: "radio", "data-value": String(c), title: choiceWord(c)}, glyph, glyph ? h("span", {class: "lbl"}, choiceWord(c)) : choiceWord(c)));
  }
  return ui.wireSeg(group, String(cur ?? ""), (v) => onChange(v === "" ? null : v));
}

function suggestInput(name, p, value, onChange) {
  const sel = h("select", {class: "input", onchange: async (e) => {
    let v = e.target.value;
    if (v === "__other") {
      v = await ui.prompt({title: "Another font", label: "Font name", value: value || "", ok: "Use this font",
        help: "It must be installed on the computer that runs the experiment."});
      if (v === null) { e.target.value = value || ""; return; }
      v = v.trim();
    }
    onChange(v || null);
  }});
  const opt = (v, label) => { const o = h("option", {value: v, style: v && v !== "__other" ? `font-family:'${v}'` : ""}, label); if ((value || "") === v) o.selected = true; return o; };
  sel.append(opt("", "System default"));
  if (value && !p.suggest.includes(value)) sel.append(opt(value, value));
  for (const f of p.suggest) sel.append(opt(f, f));
  sel.append(opt("__other", "Other…"));
  return sel;
}

/* X/Y (position) or W/H (size): number boxes whose letter you can drag sideways, plus helpers. */
const _unlocked = new Set();
function vecInput(name, p, value, onChange, live, comp) {
  if (value !== null && value !== undefined && !(Array.isArray(value) && value.length === 2 && value.every((x) => typeof x === "number"))) return null;
  const u = comp ? compUnits(comp) : "px";     // outside an item (e.g. the window size) it's pixels
  const isSize = name === "size";
  const cur = value ?? p.default;
  const vals = Array.isArray(cur) ? [...cur] : [null, null];
  const key = (comp ? comp.id : "") + "." + name;
  const lockable = isSize && p.aspect;
  const locked = () => lockable && !_unlocked.has(key);
  const natural = () => { if (comp?.type !== "image" || typeof comp.image !== "string" || !comp.image || isExpr(comp.image) || typeof imgCache !== "function") return null;
    const im = imgCache(comp.image); return im.naturalWidth ? [roundU(toUnits(im.naturalWidth, "x", u), u), roundU(toUnits(im.naturalHeight, "y", u), u)] : null; };
  const L = isSize ? ["W", "H"] : ["X", "Y"];
  const words = isSize ? ["Width", "Height"] : ["Horizontal position", "Vertical position"];
  const boxes = [0, 1].map((i) => h("input", {class: "input num with-axis" + (unitSuffix(u) ? " with-suffix" : ""), inputmode: "decimal", value: value ? value[i] : "", "aria-label": `${words[i]}${unitSuffix(u) ? " in " + (u === "px" ? "pixels" : "degrees") : ""}`,
    placeholder: vals[i] != null ? String(vals[i]) : (isSize ? "auto" : "0")}));
  const withAspect = (i, v, base) => {
    const out = [...(base[0] == null ? (natural() || [v, v]) : base)];
    const ratio = out[0] && out[1] ? out[1] / out[0] : 1;
    out[i] = v;
    if (locked()) out[1 - i] = roundU(i === 0 ? v * ratio : v / ratio, u);
    return out;
  };
  boxes.forEach((b, i) => { b.onchange = () => {
    if (b.value.trim() === "") return onChange(null);
    const v = +b.value.replace(",", ".");
    if (isNaN(v)) { b.value = value ? value[i] : ""; return; }
    onChange(withAspect(i, v, value ? [...value] : (Array.isArray(p.default) ? [...p.default] : [null, null])));
  }; });
  const scrub = (i) => h("span", {class: "axis", title: "Drag sideways to change, or type a number", "aria-hidden": "true",
    onmousedown: (e) => {
      e.preventDefault();
      const start = value ? [...value] : (natural() || (Array.isArray(p.default) ? [...p.default] : [0, 0]));
      const x0 = e.clientX; let last = start;
      const mv = (ev) => { const d = (ev.clientX - x0) * unitStep(u) * (ev.shiftKey ? 10 : 1);
        last = withAspect(i, roundU(start[i] + d, u), start); boxes[0].value = last[0]; boxes[1].value = last[1]; live(last); };
      const up = () => { window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
        if (JSON.stringify(last) !== JSON.stringify(start)) onChange(last); };
      window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
    }}, L[i]);
  const cell = (i) => h("div", {class: "input-wrap"}, scrub(i), boxes[i], unitSuffix(u) ? h("span", {class: "suffix"}, unitSuffix(u)) : null);
  const row = h("div", {class: "st-vec"}, cell(0), cell(1));
  if (lockable) row.append(h("button", {type: "button", class: "btn ghost icon sm st-lock" + (locked() ? " on" : ""), "aria-pressed": locked() ? "true" : "false",
    "aria-label": "Keep the proportions", title: locked() ? "Keeping the proportions (click to unlock)" : "Proportions unlocked (click to lock)",
    onclick: (e) => { e.preventDefault(); locked() ? _unlocked.add(key) : _unlocked.delete(key); renderProps(); }}, icon("lock")));
  const extra = [];
  if (isSize && comp?.type === "image") {
    const scale = (f) => (e) => { e.preventDefault(); const b = value || natural(); if (b) onChange([roundU(b[0] * f, u), roundU(b[1] * f, u)]); };
    extra.push(h("div", {class: "st-btnrow"},
      h("button", {type: "button", class: "btn sm" + (value == null ? " on" : ""), "aria-pressed": value == null ? "true" : "false", onclick: (e) => { e.preventDefault(); onChange(null); }, title: "The picture's own size in pixels"}, "Original size"),
      h("button", {type: "button", class: "btn sm ghost", "aria-label": "Half the size", onclick: scale(0.5)}, "½×"), h("button", {type: "button", class: "btn sm ghost", "aria-label": "Three quarters of the size", onclick: scale(0.75)}, "¾×"),
      h("button", {type: "button", class: "btn sm ghost", "aria-label": "One and a half times the size", onclick: scale(1.5)}, "1½×"), h("button", {type: "button", class: "btn sm ghost", "aria-label": "Twice the size", onclick: scale(2)}, "2×")));
  }
  if (name === "pos") return h("div", {class: "st-posrow"}, row, placeGrid(value || [0, 0], onChange, u));
  return h("div", {class: "st-vecwrap"}, row, ...extra);
}

/* Nine standard places as one control: a radio group with one Tab stop; the arrow keys move and choose in 2D, Home and
   End jump to the top-left and bottom-right corners. */
function placeGrid(cur, onChange, u) {
  const [W, H] = winSize();
  const grid = h("div", {class: "placegrid", role: "radiogroup", "aria-label": "Position on screen"});
  const cells = [], values = [];
  for (const [yy, ny] of [[H / 3, "top"], [0, "middle"], [-H / 3, "bottom"]])
    for (const [xx, nx] of [[-W / 3, "left"], [0, "centre"], [W / 3, "right"]]) {
      const v = [roundU(toUnits(xx, "x", u), u), roundU(toUnits(yy, "y", u), u)];
      const on = Math.abs(cur[0] - v[0]) < 1e-6 && Math.abs(cur[1] - v[1]) < 1e-6;
      const label = ny === "middle" && nx === "centre" ? "Centre of the screen" : `${ny} ${nx}`.replace(/^./, (c) => c.toUpperCase());
      const i = cells.length;
      const cell = h("button", {type: "button", class: "pg-cell" + (on ? " on" : ""), role: "radio", "aria-label": label, "aria-checked": on ? "true" : "false",
        title: label, tabindex: "-1", "data-fkey": "pg:" + i, onclick: (e) => { e.preventDefault(); onChange(v); }});
      cells.push(cell); values.push(v);
      grid.append(cell);
    }
  const sel = cells.findIndex((c) => c.getAttribute("aria-checked") === "true");
  cells[sel >= 0 ? sel : 4].tabIndex = 0;
  grid.addEventListener("keydown", (e) => {
    const i = cells.indexOf(document.activeElement);
    if (i < 0) return;
    const r = Math.floor(i / 3), c = i % 3;
    const to = {ArrowRight: [r, Math.min(2, c + 1)], ArrowLeft: [r, Math.max(0, c - 1)], ArrowDown: [Math.min(2, r + 1), c], ArrowUp: [Math.max(0, r - 1), c],
      Home: [0, 0], End: [2, 2]}[e.key];
    if (!to) return;
    e.preventDefault(); e.stopPropagation();
    const j = to[0] * 3 + to[1];
    if (j === i) return;
    cells.forEach((x, k) => { x.tabIndex = k === j ? 0 : -1; });
    cells[j].focus();
    onChange(values[j]);
  });
  return grid;
}

/* ---------------------------------------------------------------- files: pictures, sounds, pages */
function fileInput(p, value, onChange, comp) {
  const kind = p.accept;
  if (value !== null && value !== undefined && typeof value !== "string" && !(kind === "audio" && typeof value === "number")) return null;
  const cur = value ?? p.default;
  const isTone = kind === "audio" && typeof cur === "number";
  const card = h("div", {class: "st-file", title: "Drop a file here to use it"});
  if (kind === "image") card.append(cur ? h("img", {class: "st-thumb", src: assetUrl(cur), alt: ""}) : h("span", {class: "st-thumb empty"}, icon("image")));
  else if (kind === "html") card.append(h("span", {class: "st-thumb empty"}, icon("page")));
  if (kind === "audio" && cur !== "" && cur != null)
    card.append(h("button", {type: "button", class: "btn ghost icon sm", "aria-label": "Listen", title: "Listen", onclick: (e) => { e.preventDefault(); playSound(cur, comp?.volume, comp?.tone_duration); }}, icon("play")));
  card.append(h("div", {class: "st-fname"}, isTone ? `Tone · ${cur} Hz` : cur ? String(cur) : h("span", {class: "t-3"}, `No ${ASSET_WORD[kind]} yet`)));
  card.append(h("button", {type: "button", class: "btn sm" + (cur ? "" : " primary"), onclick: (e) => { e.preventDefault(); openAssetPicker(kind, onChange, cur); }}, cur ? "Change…" : "Choose…"));
  card.ondragover = (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); card.classList.add("drop"); } };
  card.ondragleave = () => card.classList.remove("drop");
  card.ondrop = async (e) => {
    e.preventDefault(); card.classList.remove("drop");
    const f = [...e.dataTransfer.files][0]; if (!f) return;
    const rel = await uploadAsset(f, kind); if (rel) onChange(rel);
  };
  return card;
}

async function assetList(kind) {
  const q = `/api/assets?kind=${kind}` + (S.path ? `&exp=${encodeURIComponent(S.path)}` : "");
  try { return (await api(q)).assets; } catch { return []; }
}

/* Copy a file from this computer into the experiment folder (images/, sounds/, pages/). */
async function uploadAsset(file, kind) {
  if (kindOf(file.name) !== kind) { toast(`${file.name} is not a ${ASSET_WORD[kind]} file (${ASSET_EXT[kind].join(" ")}).`, {ms: 6000}); return null; }
  if (!S.path || S.noDoc) {
    const p = typeof EDGE.ensurePath === "function" ? await EDGE.ensurePath({}) : (await save(), S.path);
    if (!p) return null;
  }
  const existing = new Map((await assetList(kind)).map((a) => [a.path, a.size]));
  const clean = file.name.replace(/[^\w.\- ]+/g, "_");
  let rel = `${ASSET_FOLDER[kind]}/${clean}`;
  if (existing.has(rel) && existing.get(rel) === file.size) return rel;   // already there
  for (let i = 2; existing.has(rel); i++) rel = `${ASSET_FOLDER[kind]}/${clean.replace(/(\.[^.]*)?$/, `_${i}$1`)}`;
  const r = await fetch(`/api/upload?path=${encodeURIComponent(expDir() + rel)}`, {method: "POST", body: await file.arrayBuffer()});
  if (!r.ok) { toast(`Couldn't copy ${file.name} into the experiment folder.`, {tone: "danger", ms: 6000}); return null; }
  return rel;
}

/* A sound or a tone, for previews in the builder (the asset picker, the file card, the Files tab). */
let _audio = null;
function playSound(v, volume, duration) {
  if (_audio) { try { _audio.pause?.(); _audio.stop?.(); } catch { /* already stopped */ } _audio = null; }
  const vol = typeof volume === "number" ? Math.max(0, Math.min(1, volume)) : 1;
  if (typeof v === "number" || (typeof v === "string" && /^\d+(\.\d+)?$/.test(v))) {
    const ac = playSound._ac ||= new (window.AudioContext || window.webkitAudioContext)();
    const o = ac.createOscillator(), g = ac.createGain();
    o.frequency.value = +v; g.gain.value = 0.3 * vol; o.connect(g).connect(ac.destination);
    o.start(); o.stop(ac.currentTime + (typeof duration === "number" ? duration : 0.2));
    _audio = o;
  } else if (typeof v === "string" && v && !isExpr(v)) {
    _audio = new Audio(assetUrl(v)); _audio.volume = vol;
    _audio.play().catch(() => toast("This browser can't play that file (the experiment itself may still can)."));
  }
}

/* The asset picker: what is in the experiment folder, upload or drop new files, tones for sounds. */
async function openAssetPicker(kind, onPick, cur) {
  const word = ASSET_WORD[kind];
  let closeFn = () => {};
  const pick = (v) => closeFn(v === null || v === undefined ? "__none" : v);
  const search = h("input", {class: "input", type: "search", placeholder: `Search ${word}s…`, "aria-label": `Search ${word}s`});
  const input = h("input", {type: "file", multiple: "", accept: ASSET_EXT[kind].join(","), hidden: ""});
  const grid = h("div", {class: kind === "image" ? "ap-grid" : "ap-list", role: "list"});
  const status = h("p", {class: "t-caption ap-status", role: "status"});
  let items = [];
  const draw = () => {
    grid.replaceChildren();
    const f = search.value.toLowerCase();
    const shown = items.filter((a) => a.path.toLowerCase().includes(f));
    status.textContent = items.length ? `${shown.length} of ${items.length} in the experiment folder` : "";
    if (!items.length) {
      grid.append(h("div", {class: "empty ap-empty"}, h("span", {class: "ic-wrap"}, icon(kind === "image" ? "image" : kind === "audio" ? "sound" : "page")),
        h("p", {}, `No ${word}s in the experiment folder yet. Upload them from this computer, or drop files here. They are copied into ${ASSET_FOLDER[kind]}/ next to the experiment.`)));
      return;
    }
    if (!shown.length) grid.append(h("p", {class: "t-2 ap-none"}, `Nothing called “${search.value}”.`));
    for (const a of shown) {
      const sel = a.path === cur;
      const name = a.path.split("/").pop();
      if (kind === "image") grid.append(h("button", {type: "button", role: "listitem", class: "ap-tile" + (sel ? " on" : ""), title: a.path, "aria-label": `${a.path}${sel ? " (in use)" : ""}`, onclick: () => pick(a.path)},
        h("span", {class: "ap-img"}, h("img", {src: assetUrl(a.path), loading: "lazy", alt: ""})), h("span", {class: "ap-name"}, name), a.folder ? h("span", {class: "t-caption"}, a.folder) : null));
      else grid.append(h("div", {role: "listitem", class: "ap-row" + (sel ? " on" : "")},
        kind === "audio" ? h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Listen to ${name}`, title: "Listen", onclick: () => playSound(a.path)}, icon("play")) : h("span", {class: "ap-ic"}, icon("page")),
        h("span", {class: "ap-name", title: a.path}, a.path), h("span", {class: "t-caption"}, `${Math.max(1, Math.round(a.size / 1024))} KB`),
        h("button", {type: "button", class: "btn sm" + (sel ? "" : " primary"), "aria-label": `Use ${name}`, onclick: () => pick(a.path)}, sel ? "In use" : "Use")));
    }
  };
  const refresh = async () => { items = await assetList(kind); draw(); };
  const addFiles = async (files) => {
    const done = [];
    for (const f of files) { const rel = await uploadAsset(f, kind); if (rel) done.push(rel); }
    if (!S.path) return;
    if (done.length === 1) return pick(done[0]);
    await refresh();
    if (done.length) toast(`Added ${done.length} ${word}s to ${ASSET_FOLDER[kind]}/`);
  };
  input.onchange = () => addFiles([...input.files]);
  search.oninput = draw;
  const drop = h("div", {class: "ap-drop"}, grid);
  drop.ondragover = (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); drop.classList.add("drop"); } };
  drop.ondragleave = (e) => { if (e.target === drop) drop.classList.remove("drop"); };
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("drop"); addFiles([...e.dataTransfer.files]); };
  const tones = kind === "audio" ? (() => {
    const hz = h("input", {class: "input num", type: "number", min: 20, max: 20000, step: 10, value: typeof cur === "number" ? cur : 440, "aria-label": "Tone frequency in Hz"});
    return h("div", {class: "ap-tones"}, h("h3", {class: "t-title-s"}, "Or a beep (a pure tone)"),
      h("div", {class: "ap-tonelist"}, ...TONES.map(([f, label]) => h("span", {class: "ap-tone" + (cur === f ? " on" : "")},
        h("button", {type: "button", class: "btn ghost icon sm", "aria-label": `Listen to the ${label.toLowerCase()} tone`, title: "Listen", onclick: () => playSound(f)}, icon("play")),
        h("button", {type: "button", class: "btn sm", onclick: () => pick(f)}, `${label} · ${f} Hz`))),
      h("span", {class: "ap-tone"}, h("div", {class: "input-wrap ap-hz"}, hz, h("span", {class: "suffix"}, "Hz")),
        h("button", {type: "button", class: "btn ghost icon sm", "aria-label": "Listen to this tone", title: "Listen", onclick: () => playSound(+hz.value)}, icon("play")),
        h("button", {type: "button", class: "btn sm", onclick: () => pick(+hz.value)}, "Use"))));
  })() : null;
  const body = h("div", {class: "ap"},
    h("div", {class: "ap-toolbar"}, h("div", {class: "input-wrap ap-search"}, icon("search", "lead"), search),
      h("button", {type: "button", class: "btn", onclick: () => input.click()}, icon("import"), "Upload from this computer"), input),
    status, drop, tones,
    h("p", {class: "t-caption"}, kind === "html" ? "Pages are stored next to the experiment, in pages/." :
      `A different ${word} on each trial? Close this and use the value menu next to the field: “New trial-list column…”.`));
  const p = ui.dialog({title: `Choose a ${word}`, icon: kind === "image" ? "image" : kind === "audio" ? "sound" : "page", size: "lg", body,
    buttons: [{label: "Cancel", value: null}], initialFocus: search, onOpen: (_dlg, close) => { closeFn = close; }});
  refresh();
  const v = await p;
  if (v !== null && v !== undefined) onPick(v === "__none" ? null : v);
}
