/* EDGE builder: easy editing of what participants see and hear.
 * - property widgets: sliders, colour swatches, X/Y and W/H boxes you can drag, icon buttons, font menu
 * - file pickers for pictures, sounds and pages (browse the experiment folder, upload, drag and drop)
 * - the screen preview as an editor: click to select, drag to move, corners resize, handle rotates,
 *   double-click text to type, arrow keys nudge, drop palette items or files from the computer onto it
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

/* ---------------------------------------------------------------- property widgets */
/* Returns an input element for properties that have a friendlier editor than a text box, else null. */
function stageInput(name, p, value, onChange, opts = {}) {
  const type = p.type || "str";
  const live = opts.live || (() => {});
  if (type === "color") return colorInput(p, value, onChange, live);
  if (type === "file" && p.accept) return fileInput(p, value, onChange, opts.comp);
  if (type === "vec2") return vecInput(name, p, value, onChange, live, opts.comp);
  if (type === "choice" && opts.comp && (p.icons || ((p.choices || []).length <= 4 && (p.choices || []).every((c) => String(c).length <= 10))))
    return segmented(p, value, onChange);
  if ((type === "float" || type === "int") && p.min !== undefined && p.max !== undefined) return sliderInput(p, value, onChange, live, opts.comp);
  if (type === "str" && p.suggest) return suggestInput(name, p, value, onChange);
  return null;
}

function sliderInput(p, value, onChange, live, comp) {
  if (value !== null && value !== undefined && typeof value !== "number") return null;
  let {min, max, step} = p;
  const u = compUnits(comp);
  if (p.length && u !== "px") { min = roundU(toUnits(min, "y", u), u); max = roundU(toUnits(max, "y", u), u); step = 0.005; }
  step = step ?? (max - min) / 100;
  const dec = p.type === "int" ? 0 : decimals(step);
  const fmt = (v) => +(+v).toFixed(dec);
  const rng = h("input", {type: "range", min, max, step, value: value ?? p.default ?? min, "aria-label": "slider"});
  const num = h("input", {type: "number", class: "st-num", step, value: value ?? "", placeholder: p.default != null ? String(p.default) : ""});
  rng.oninput = () => { num.value = fmt(rng.value); live(fmt(rng.value)); };
  rng.onchange = () => onChange(fmt(rng.value));
  num.onchange = () => onChange(num.value === "" ? null : fmt(num.value));
  return h("div", {class: "st-slider"}, rng, num);
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
  const sw = h("div", {class: "st-swatches"});
  const names = p.transparent ? [...SWATCHES, "none"] : SWATCHES;
  for (const c of names) {
    const none = c === "none";
    const on = none ? (cur == null || cur === "transparent" || cur === "none") : curHex && colorHex(c) === curHex;
    sw.append(h("button", {class: "st-sw" + (none ? " none" : "") + (on ? " on" : ""), title: none ? "none (transparent)" : c,
      style: none ? "" : `background:${c}`, onclick: (e) => { e.preventDefault(); onChange(none ? (p.default == null ? null : "transparent") : c); }}));
  }
  const pick = h("input", {type: "color", class: "st-pick", title: "Any colour"});
  if (curHex && /^#[0-9a-f]{6}$/i.test(curHex)) pick.value = curHex;
  pick.oninput = (e) => live(e.target.value);
  pick.onchange = (e) => onChange(e.target.value);
  const txt = h("input", {value: value ?? "", placeholder: p.default != null ? String(p.default) : "none", title: "a colour name, #hex, or $expression",
    onchange: (e) => onChange(e.target.value.trim() || null)});
  return h("div", {class: "st-color"}, sw, h("div", {class: "row2"}, pick, txt));
}

function segmented(p, value, onChange) {
  const cur = value ?? p.default;
  return h("div", {class: "st-seg"}, (p.choices || []).map((c) => h("button", {class: "st-segb" + (c === cur ? " on" : ""), title: c === "" ? "default" : c,
    onclick: (e) => { e.preventDefault(); onChange(c === "" ? null : c); }},
    p.icons?.[c] ? h("span", {class: "ic"}, p.icons[c]) : null, h("small", {}, c === "" ? "default" : c))));
}

function suggestInput(name, p, value, onChange) {
  const sel = h("select", {onchange: (e) => {
    let v = e.target.value;
    if (v === "__other") { v = prompt("Font name (it must be installed on the computer that runs the experiment):", value || ""); if (v === null) { e.target.value = value || ""; return; } }
    onChange(v || null);
  }});
  const opt = (v, label) => { const o = h("option", {value: v, style: v && v !== "__other" ? `font-family:'${v}'` : ""}, label); if ((value || "") === v) o.selected = true; return o; };
  sel.append(opt("", "(system default)"));
  if (value && !p.suggest.includes(value)) sel.append(opt(value, value));
  for (const f of p.suggest) sel.append(opt(f, f));
  sel.append(opt("__other", "Other…"));
  return sel;
}

/* X/Y (position) or W/H (size): number boxes whose letter you can drag sideways, plus helpers. */
const _unlocked = new Set();
function vecInput(name, p, value, onChange, live, comp) {
  if (value !== null && value !== undefined && !(Array.isArray(value) && value.length === 2 && value.every((x) => typeof x === "number"))) return null;
  const u = comp ? compUnits(comp) : "px";     // outside a component (e.g. the window size) it's pixels
  const isSize = name === "size";
  const cur = value ?? p.default;
  const vals = Array.isArray(cur) ? [...cur] : [null, null];
  const key = (comp ? comp.id : "") + "." + name;
  const lockable = isSize && p.aspect;
  const locked = () => lockable && !_unlocked.has(key);
  const natural = () => { if (comp?.type !== "image" || typeof comp.image !== "string" || !comp.image || isExpr(comp.image)) return null;
    const im = imgCache(comp.image); return im.naturalWidth ? [roundU(toUnits(im.naturalWidth, "x", u), u), roundU(toUnits(im.naturalHeight, "y", u), u)] : null; };
  const boxes = [0, 1].map((i) => h("input", {type: "number", class: "st-num", step: unitStep(u), value: value ? value[i] : "",
    placeholder: vals[i] != null ? String(vals[i]) : (isSize ? "auto" : "0")}));
  const withAspect = (i, v, base) => {
    const out = [...(base[0] == null ? (natural() || [v, v]) : base)];
    const ratio = out[0] && out[1] ? out[1] / out[0] : 1;
    out[i] = v;
    if (locked()) out[1 - i] = roundU(i === 0 ? v * ratio : v / ratio, u);
    return out;
  };
  boxes.forEach((b, i) => { b.onchange = () => {
    if (b.value === "") return onChange(null);
    onChange(withAspect(i, +b.value, value ? [...value] : (Array.isArray(p.default) ? [...p.default] : [null, null])));
  }; });
  const scrub = (i, label) => h("span", {class: "st-axis", title: "Drag sideways to change, or type a number",
    onmousedown: (e) => {
      e.preventDefault();
      const start = value ? [...value] : (natural() || (Array.isArray(p.default) ? [...p.default] : [0, 0]));
      const x0 = e.clientX; let last = start;
      const mv = (ev) => { const d = (ev.clientX - x0) * unitStep(u) * (ev.shiftKey ? 10 : 1);
        last = withAspect(i, roundU(start[i] + d, u), start); boxes[0].value = last[0]; boxes[1].value = last[1]; live(last); };
      const up = () => { window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
        if (JSON.stringify(last) !== JSON.stringify(start)) onChange(last); };
      window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
    }}, label);
  const L = isSize ? ["W", "H"] : ["X", "Y"];
  const row = h("div", {class: "st-vec"}, scrub(0, L[0]), boxes[0], scrub(1, L[1]), boxes[1]);
  if (lockable) row.append(h("button", {class: "mini st-lock" + (locked() ? " on" : ""), title: locked() ? "Keeping the proportions (click to unlock)" : "Proportions unlocked (click to lock)",
    onclick: (e) => { e.preventDefault(); locked() ? _unlocked.add(key) : _unlocked.delete(key); renderProps(); }}, locked() ? "🔒" : "🔓"));
  const extra = [];
  if (isSize && comp?.type === "image") {
    const scale = (f) => (e) => { e.preventDefault(); const b = value || natural(); if (b) onChange([roundU(b[0] * f, u), roundU(b[1] * f, u)]); };
    extra.push(h("div", {class: "st-btnrow"},
      h("button", {class: "mini" + (value == null ? " on" : ""), onclick: (e) => { e.preventDefault(); onChange(null); }, title: "The picture's own size in pixels"}, "Original size"),
      h("button", {class: "mini", onclick: scale(0.5)}, "½×"), h("button", {class: "mini", onclick: scale(0.75)}, "¾×"),
      h("button", {class: "mini", onclick: scale(1.5)}, "1½×"), h("button", {class: "mini", onclick: scale(2)}, "2×")));
  }
  if (name === "pos") extra.push(placeGrid(value || [0, 0], onChange, u));
  return h("div", {}, row, ...extra);
}

function placeGrid(cur, onChange, u) {
  const [W, H] = winSize();
  const grid = h("div", {class: "st-place", title: "Put it in a standard place"});
  for (const [yy, ny] of [[H / 3, "top"], [0, "middle"], [-H / 3, "bottom"]])
    for (const [xx, nx] of [[-W / 3, "left"], [0, "centre"], [W / 3, "right"]]) {
      const v = [roundU(toUnits(xx, "x", u), u), roundU(toUnits(yy, "y", u), u)];
      const on = Math.abs(cur[0] - v[0]) < 1e-6 && Math.abs(cur[1] - v[1]) < 1e-6;
      grid.append(h("button", {class: "st-cell" + (on ? " on" : ""), title: ny === "middle" && nx === "centre" ? "centre of the screen" : `${ny} ${nx}`,
        onclick: (e) => { e.preventDefault(); onChange(v); }}));
    }
  return h("div", {class: "st-placerow"}, grid, h("span", {class: "help"}, "or drag it on the screen preview"));
}

/* ---------------------------------------------------------------- files: pictures, sounds, pages */
function fileInput(p, value, onChange, comp) {
  const kind = p.accept;
  if (value !== null && value !== undefined && typeof value !== "string" && !(kind === "audio" && typeof value === "number")) return null;
  const cur = value ?? p.default;
  const isTone = kind === "audio" && typeof cur === "number";
  const card = h("div", {class: "st-file", title: "Drop a file here to use it"});
  if (kind === "image" && cur) card.append(h("img", {class: "st-thumb", src: assetUrl(cur), alt: ""}));
  if (kind === "audio" && cur !== "" && cur != null)
    card.append(h("button", {class: "mini st-play", title: "Listen", onclick: (e) => { e.preventDefault(); playSound(cur, comp?.volume, comp?.tone_duration); }}, "▶"));
  card.append(h("div", {class: "st-fname"}, isTone ? `Tone · ${cur} Hz` : cur ? String(cur) : `No ${ASSET_WORD[kind]} yet`));
  card.append(h("button", {class: "primary mini", onclick: (e) => { e.preventDefault(); openAssetPicker(kind, onChange, cur); }}, cur ? "Change…" : "Choose…"));
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

/* Copy a file from the participant's computer into the experiment folder (images/, sounds/, pages/). */
async function uploadAsset(file, kind) {
  if (kindOf(file.name) !== kind) { toast(`${file.name} is not a ${ASSET_WORD[kind]} file (${ASSET_EXT[kind].join(" ")})`, 4000); return null; }
  if (!S.path) {
    toast("Save the experiment first, so the file can be stored next to it", 4000);
    await save(); if (!S.path) return null;
  }
  const existing = new Map((await assetList(kind)).map((a) => [a.path, a.size]));
  const clean = file.name.replace(/[^\w.\- ]+/g, "_");
  let rel = `${ASSET_FOLDER[kind]}/${clean}`;
  if (existing.has(rel) && existing.get(rel) === file.size) return rel;   // already there
  for (let i = 2; existing.has(rel); i++) rel = `${ASSET_FOLDER[kind]}/${clean.replace(/(\.[^.]*)?$/, `_${i}$1`)}`;
  const r = await fetch(`/api/upload?path=${encodeURIComponent(expDir() + rel)}`, {method: "POST", body: await file.arrayBuffer()});
  if (!r.ok) { toast(`Could not copy ${file.name}`, 4000); return null; }
  return rel;
}

let _audio = null;
function playSound(v, volume, duration) {
  if (_audio) { try { _audio.pause?.(); _audio.stop?.(); } catch {} _audio = null; }
  const vol = typeof volume === "number" ? Math.max(0, Math.min(1, volume)) : 1;
  if (typeof v === "number" || (typeof v === "string" && /^\d+(\.\d+)?$/.test(v))) {
    const ac = playSound._ac ||= new (window.AudioContext || window.webkitAudioContext)();
    const o = ac.createOscillator(), g = ac.createGain();
    o.frequency.value = +v; g.gain.value = 0.3 * vol; o.connect(g).connect(ac.destination);
    o.start(); o.stop(ac.currentTime + (typeof duration === "number" ? duration : 0.2));
    _audio = o;
  } else if (typeof v === "string" && v && !isExpr(v)) {
    _audio = new Audio(assetUrl(v)); _audio.volume = vol;
    _audio.play().catch(() => toast("This browser can't play that file (the experiment may still can)"));
  }
}

/* The picker dialog: what's in the experiment folder, upload or drop new files, tones for sounds. */
async function openAssetPicker(kind, onPick, cur) {
  const body = $("#modal-body"); body.innerHTML = ""; _resetModal(); body.classList.add("assetpick");
  const word = ASSET_WORD[kind];
  const pick = (v) => { closeModal(); onPick(v); };
  const search = h("input", {type: "search", placeholder: `Search ${word}s…`, class: "st-search"});
  const input = h("input", {type: "file", multiple: true, accept: ASSET_EXT[kind].join(","), style: "display:none"});
  const grid = h("div", {class: kind === "image" ? "st-grid" : "st-list"});
  const status = h("div", {class: "help"});
  let items = [];
  const draw = () => {
    grid.innerHTML = "";
    const f = search.value.toLowerCase();
    const shown = items.filter((a) => a.path.toLowerCase().includes(f));
    status.textContent = items.length ? `${shown.length} of ${items.length} in the experiment folder` : "";
    if (!items.length) grid.append(h("div", {class: "st-empty"}, `No ${word}s in the experiment folder yet.`, h("br"), `Click “Upload from computer” or drop files here.`));
    for (const a of shown) {
      const sel = a.path === cur;
      if (kind === "image") grid.append(h("div", {class: "st-tile" + (sel ? " on" : ""), title: a.path, onclick: () => pick(a.path)},
        h("img", {src: assetUrl(a.path), loading: "lazy", alt: ""}), h("span", {}, a.path.split("/").pop()), a.folder ? h("small", {}, a.folder) : null));
      else grid.append(h("div", {class: "st-row" + (sel ? " on" : ""), title: a.path},
        kind === "audio" ? h("button", {class: "mini", title: "Listen", onclick: (e) => { e.stopPropagation(); playSound(a.path); }}, "▶") : null,
        h("span", {class: "st-rowname", onclick: () => pick(a.path)}, a.path), h("small", {}, `${Math.max(1, Math.round(a.size / 1024))} KB`),
        h("button", {class: "mini primary", onclick: () => pick(a.path)}, "Use")));
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
  const drop = h("div", {class: "st-drop"}, grid);
  drop.ondragover = (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); drop.classList.add("drop"); } };
  drop.ondragleave = (e) => { if (e.target === drop) drop.classList.remove("drop"); };
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("drop"); addFiles([...e.dataTransfer.files]); };
  const tones = kind === "audio" ? h("div", {class: "st-tones"}, h("b", {}, "Or a beep (pure tone): "),
    ...TONES.map(([hz, label]) => h("span", {class: "st-tone" + (cur === hz ? " on" : "")},
      h("button", {class: "mini", title: "Listen", onclick: () => playSound(hz)}, "▶"),
      h("button", {class: "mini", onclick: () => pick(hz)}, `${label} · ${hz} Hz`))),
    (() => { const hz = h("input", {type: "number", min: 20, max: 20000, step: 10, value: typeof cur === "number" ? cur : 440, class: "st-num"});
      return h("span", {class: "st-tone"}, hz, " Hz ", h("button", {class: "mini", onclick: () => playSound(+hz.value)}, "▶"), h("button", {class: "mini", onclick: () => pick(+hz.value)}, "Use")); })()) : null;
  body.append(...[h("h3", {}, `Choose a ${word}`),
    h("div", {class: "st-toolbar"}, search, h("button", {class: "primary", onclick: () => input.click()}, "⬆ Upload from computer"), input),
    status, drop, tones,
    h("p", {class: "help"}, kind === "html" ? "Pages are stored next to the experiment, in pages/." :
      `A different ${word} on each trial? Close this and use the menu next to the field: “+ New trial-list column…”.`),
    h("div", {class: "btns"}, h("button", {onclick: () => closeModal()}, "Cancel"))].filter(Boolean));
  openModal();
  search.focus();
  await refresh();
}

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
    ctx.setLineDash([5 * dpr, 4 * dpr]); ctx.strokeStyle = "#4d8dff"; ctx.lineWidth = 1.5 * dpr; ctx.beginPath();
    [[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(([sx, sy], i) => { const [px, py] = toCanvas(cv, ...world(b, sx * b.hw, sy * b.hh)); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
    ctx.closePath(); ctx.stroke(); ctx.setLineDash([]);
    for (const hd of handles(cv, b)) {
      ctx.fillStyle = "#fff"; ctx.strokeStyle = "#4d8dff"; ctx.lineWidth = 1.5 * dpr;
      if (hd.kind === "rotate") {
        ctx.beginPath(); ctx.moveTo(...hd.base); ctx.lineTo(...hd.at); ctx.stroke();
        ctx.beginPath(); ctx.arc(...hd.at, 5 * dpr, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
      } else { const s = 4 * dpr; ctx.fillRect(hd.at[0] - s, hd.at[1] - s, 2 * s, 2 * s); ctx.strokeRect(hd.at[0] - s, hd.at[1] - s, 2 * s, 2 * s); }
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
  const b = selBox(cv) || hit.box;
  const prop = hit.kind === "move" ? "pos" : hit.kind === "rotate" ? "ori" : resizeProp(c);
  if (isExpr(c[prop])) {
    const col = String(c[prop]).slice(1);
    return toast(`“${prop}” comes from the trial list (${col}). Change it there, or set it to Fixed in the panel on the right.`, 4500);
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
  if (d && d.moved && JSON.stringify(d.c) !== d.before) commit(); else renderPreview();
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
  if (c.type === "image") return openAssetPicker("image", (v) => setProp(c, "image", v), c.image);
  if (c.type !== "text") return;
  if (isExpr(c.text)) return toast("This text comes from the trial list or a formula: edit it in the panel on the right.", 4000);
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
  if (isExpr(c.pos)) return toast("The position comes from the trial list: change it there.");
  const u = compUnits(c), st = unitStep(u) * (e.shiftKey ? 10 : 1), [dx, dy] = arrows[e.key];
  const p0 = Array.isArray(c.pos) ? c.pos : [0, 0];
  if (!ST.nudge) ST.nudge = {before: JSON.stringify(c)};
  c.pos = [roundU(p0[0] + dx * st, u), roundU(p0[1] + dy * st, u)];
  renderPreview();
  clearTimeout(ST.nudge.t);
  ST.nudge.t = setTimeout(() => { ST.nudge = null; commit(); }, 500);
}

/* Drop a palette item or files from the computer onto the screen: it appears where it was dropped. */
async function dropOnStage(cv, e) {
  e.preventDefault(); cv.classList.remove("drop");
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

function toggleBigPreview(force) {
  const on = force ?? !$("#routine-body").classList.contains("big");
  $("#routine-body").classList.toggle("big", on);
  try { localStorage.setItem("edge.bigPreview", on ? "1" : ""); } catch {}
  $("#preview-big").textContent = on ? "⤡" : "⤢";
  $("#preview-big").title = on ? "Smaller preview" : "Bigger preview, for arranging things on the screen";
  requestAnimationFrame(() => { if (S.exp) renderPreview(); });
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
  $("#preview-big").onclick = () => toggleBigPreview();
  let big = false; try { big = !!localStorage.getItem("edge.bigPreview"); } catch {}
  if (big) toggleBigPreview(true);
  window.addEventListener("resize", () => { if (S.exp) renderPreview(); });
}
window.addEventListener("DOMContentLoaded", wireStage);
