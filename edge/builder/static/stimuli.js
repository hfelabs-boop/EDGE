/* stimuli.js: video and vision-science stimuli in the builder, and the Colour & gamma settings.
 * Owner: the stimuli feature (edge/video.py, edge/vision.py, edge/gamma.py are its Python side).
 *
 * - names, icons and the video asset kind for the items movie, grating, gabor, noise and dots;
 * - drawStimFrame(ctx, kind, p): Try it draws what the engine sent (px, y up; simple.js has already moved, rotated
 *   and faded the context): a <video> element kept in step with the engine's video time, gratings / Gabors / noise
 *   computed on a canvas, dots at the positions the engine computed;
 * - drawStimPreview(ctx, c, env): the screen preview and thumbnails (build.js drawScreen): a representative frame
 *   from the item's settings (a poster frame of the video, or a labelled placeholder);
 * - gammaSettings(w): the Experiment settings section that holds settings.window.gamma and the measuring procedure.
 * Loaded last: it extends the tables of app.js, build.js and widgets.js and reads no state at load time otherwise.
 */
"use strict";

/* ------------------------------------------------------------------ names, icons, assets */
(function stimRegister() {
  const icons = {
    movie: '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M10 9.5v5l4.5-2.5z"/><path d="M3.5 9h2M3.5 15h2M18.5 9h2M18.5 15h2"/>',
    grating: '<circle cx="12" cy="12" r="8.5"/><path d="M8 4.5v15M12 3.5v17M16 4.5v15"/>',
    gabor: '<circle cx="12" cy="12" r="8.5" stroke-dasharray="2 2"/><path d="M9.5 7v10M12 5.5v13M14.5 7v10"/>',
    noise: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M7 7h2v2H7zM12 7h2v2h-2zM9 10h2v2H9zM15 10h2v2h-2zM7 13h2v2H7zM12 14h2v2h-2zM16 16h1v1h-1z" class="dotf"/>',
    dots: '<circle cx="12" cy="12" r="8.5"/><path d="M7.5 10.5l2 0M11 8l2 0M13 13l2 0M8.5 15l2 0M14 16.5l2 0" /><path d="M16 9.5l2 0"/>',
  };
  if (typeof EDGE_ICONS !== "undefined") {
    Object.assign(EDGE_ICONS, icons);
    const sprite = document.getElementById("edge-icon-sprite");
    if (sprite) {
      for (const [k, v] of Object.entries(icons)) {
        if (sprite.querySelector(`#i-${k}`)) continue;
        const s = document.createElementNS("http://www.w3.org/2000/svg", "symbol");
        s.setAttribute("id", "i-" + k); s.setAttribute("viewBox", "0 0 24 24"); s.innerHTML = v;
        sprite.append(s);
      }
    }
  }
  if (typeof FRIENDLY !== "undefined") Object.assign(FRIENDLY, {movie: ["Video", "Show"], grating: ["Grating", "Show"],
    gabor: ["Gabor patch", "Show"], noise: ["Visual noise", "Show"], dots: ["Moving dots (RDK)", "Show"]});
  if (typeof TYPE_ICON !== "undefined") Object.assign(TYPE_ICON, {movie: "movie", grating: "grating", gabor: "gabor", noise: "noise", dots: "dots"});
  if (typeof SIMPLE_HIDDEN !== "undefined") for (const t of ["grating", "gabor", "noise", "dots"]) SIMPLE_HIDDEN.add(t);   // search finds them
  if (typeof PROP_WORDS !== "undefined") {   // plain names in the inspector ("type.prop" so other items keep theirs)
    const pat = {sf: ["Spatial frequency"], sf_units: ["Spatial frequency in"], phase: ["Phase", "In cycles: 0.5 is half a cycle."],
      tf: ["Drift speed (temporal frequency)", "Hz. 0: the bars stand still; positive: they move right at rotation 0."], wave: ["Wave"],
      contrast: ["Contrast", "0: uniform grey, 1: full contrast (linear on a gamma-calibrated monitor)."], mask: ["Mask"],
      sigma: ["Gaussian width (sigma)", "Empty: a sixth of the size."], edge: ["Soft edge", "Raised-cosine mask: fraction of the radius."], color: ["Colour"]};
    const words = {"movie.movie": ["Video", "A video file (MP4, WebM …) next to the experiment, or a trial-list column."],
      "movie.loop": ["Loop", "Start again at the end, until the item's duration ends."], "movie.volume": ["Volume", "0 mutes the sound track."],
      "movie.size": ["Size", "Empty: the video's own size."], "gabor.sigma": ["Gaussian width (sigma)", "The patch is 6 × sigma unless a size is given."],
      "noise.noise_type": ["Noise"], "noise.element_size": ["Element size", "Empty: one screen pixel."], "noise.dynamic": ["New noise while it is shown"],
      "noise.update_frames": ["Refreshes per noise sample"], "noise.seed": ["Seed", "Empty: different each time, reproducible from the session's seed."],
      "dots.n_dots": ["Number of dots"], "dots.coherence": ["Coherence", "Fraction of dots moving in the signal direction."],
      "dots.direction": ["Direction", "Degrees: 0 right, 90 up, 180 left, 270 down."], "dots.speed": ["Speed", "Per second."],
      "dots.dot_size": ["Dot size"], "dots.lifetime": ["Dot lifetime", "In frames. 0: for ever."], "dots.noise_dots": ["Noise dots"],
      "dots.field_shape": ["Aperture"], "dots.size": ["Aperture size"], "dots.color": ["Dot colour"],
      "dots.seed": ["Seed", "Empty: different each time, reproducible from the session's seed."]};
    for (const t of ["grating", "gabor", "noise"]) for (const [k, v] of Object.entries(pat)) words[`${t}.${k}`] ||= v;
    for (const [k, v] of Object.entries(words)) if (!(k in PROP_WORDS)) PROP_WORDS[k] = v;
  }
  if (typeof CHOICE_WORDS !== "undefined") {
    const c = {sin: "Sine", sqr: "Square", gauss: "Gaussian", raisedcos: "Soft circle", none: "None", white: "White", pink: "Pink (1/f)",
      brown: "Brown (1/f²)", binary: "Binary", same: "Each its own direction", random_walk: "Random walk", random_position: "Jump around",
      square: "Square", "cycles/deg": "cycles per degree", "cycles/px": "cycles per pixel"};
    for (const [k, v] of Object.entries(c)) if (!(k in CHOICE_WORDS)) CHOICE_WORDS[k] = v;
  }
  if (typeof ASSET_EXT !== "undefined") {
    ASSET_EXT.video = [".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".mpg", ".mpeg", ".wmv", ".ogv"];
    ASSET_WORD.video = "video"; ASSET_FOLDER.video = "videos";
  }
  if (!document.getElementById("stimuli-css")) {
    const css = document.createElement("style");
    css.id = "stimuli-css";
    css.textContent = `
.gamma-table { border-collapse: collapse; margin: var(--sp-2, 8px) 0; }
.gamma-table th, .gamma-table td { padding: 2px 10px 2px 0; text-align: left; font-size: var(--fs-small, 13px); }
.gamma-table .input.num { width: 7em; }
.gamma-swatch { display: inline-block; width: 14px; height: 14px; border-radius: 3px; border: 1px solid var(--border, #8884); vertical-align: -2px; }
.gamma-measure ol { margin: 0 0 var(--sp-2, 8px) 1.2em; padding: 0; }
.gamma-result { margin-top: var(--sp-2, 8px); display: flex; gap: var(--sp-3, 12px); align-items: flex-start; flex-wrap: wrap; }
.gamma-result pre { margin: 0; white-space: pre-wrap; }
.gamma-plot { width: 260px; height: 150px; color: var(--text-2, #666); }
#gamma-name { width: 9em; }
.gamma-patch { position: fixed; inset: 0; z-index: 2147483000; display: flex; align-items: flex-end; justify-content: center; }
.gamma-bar { margin: 0 0 16px; display: flex; gap: 10px; align-items: center; background: #000c; color: #ddd; padding: 6px 10px; border-radius: 6px; font: 13px sans-serif; }
.gamma-in { width: 8em; font: 14px monospace; background: #111; color: #eee; border: 1px solid #555; border-radius: 4px; padding: 3px 6px; }`;
    document.head.append(css);
  }
  if (typeof SETTINGS_SECTIONS !== "undefined" && !SETTINGS_SECTIONS.some(([k]) => k === "colour")) {
    const i = SETTINGS_SECTIONS.findIndex(([k]) => k === "screen");
    SETTINGS_SECTIONS.splice(i + 1, 0, ["colour", "Colour & gamma"]);
  }
})();

/* ------------------------------------------------------------------ small helpers */
const STIM = {videos: new Map(), drawn: new Set(), patterns: new Map(), poster: new Map()};

function stimRng(seed) {        // mulberry32: a seeded generator for the browser's noise and preview dots
  let a = (seed >>> 0) || 1;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
function stimRgb(c) {         // a colour as 0..1 channel weights (white = 1,1,1)
  const cv = stimRgb._cv ||= document.createElement("canvas").getContext("2d");
  if (Array.isArray(c)) {
    let v = c.map(Number);
    if (v.some((x) => x < 0)) v = v.map((x) => (x + 1) / 2); else if (v.every((x) => x <= 1) && c.some((x) => String(x).includes("."))) v = v.map((x) => x); else v = v.map((x) => x / 255);
    return v.slice(0, 3);
  }
  cv.fillStyle = "#fff"; cv.fillStyle = typeof c === "string" && c ? c : "#fff";
  const s = cv.fillStyle;
  if (s.startsWith("#")) return [1, 3, 5].map((i) => parseInt(s.slice(i, i + 2), 16) / 255);
  const m = s.match(/[\d.]+/g) || [255, 255, 255];
  return m.slice(0, 3).map((x) => +x / 255);
}
function stimFileUrl(src, base) {
  return `/api/file?path=${encodeURIComponent((base ? base.replace(/[^/]*$/, "") : "") + src)}`;
}

/* ------------------------------------------------------------------ patterns (px params) -> canvas */
const STIM_MAX = 384;   // computed at most this many pixels across, then scaled (the browser shows a sketch)
function stimMask(w, h, mask, sigmaPx, edge, i, j, sc) {
  const px = (i + 0.5 - w / 2) * sc, py = (j + 0.5 - h / 2) * sc, W = w * sc, H = h * sc;
  if (mask === "gauss") { const s = sigmaPx || Math.max(W, H) / 6; return Math.exp(-(px * px + py * py) / (2 * s * s)); }
  const r = Math.hypot(px / (W / 2), py / (H / 2));
  if (mask === "circle") return r <= 1 ? 1 : 0;
  if (mask === "raisedcos") { const e = Math.min(Math.max(edge || 0.2, 1e-6), 1); if (r <= 1 - e) return 1; if (r >= 1) return 0; return 0.5 * (1 + Math.cos(Math.PI * (r - (1 - e)) / e)); }
  return 1;
}
function stimNoise(nw, nh, type, seed) {
  const rnd = stimRng(seed), out = new Float32Array(nw * nh);
  if (type === "binary") { for (let i = 0; i < out.length; i++) out[i] = rnd() < 0.5 ? -1 : 1; return out; }
  if (type === "pink" || type === "brown") {      // octaves of smoothed white noise: a cheap 1/f-like look
    const oct = Math.max(1, Math.floor(Math.log2(Math.max(nw, nh))));
    for (let o = 0; o < oct; o++) {
      const step = 2 ** o, gw = Math.ceil(nw / step) + 2, gh = Math.ceil(nh / step) + 2;
      const g = new Float32Array(gw * gh); for (let k = 0; k < g.length; k++) g[k] = rnd() * 2 - 1;
      const wgt = type === "pink" ? step : step * step;
      for (let y = 0; y < nh; y++) for (let x = 0; x < nw; x++) {
        const fx = x / step, fy = y / step, x0 = fx | 0, y0 = fy | 0, tx = fx - x0, ty = fy - y0;
        const v = g[y0 * gw + x0] * (1 - tx) * (1 - ty) + g[y0 * gw + x0 + 1] * tx * (1 - ty) + g[(y0 + 1) * gw + x0] * (1 - tx) * ty + g[(y0 + 1) * gw + x0 + 1] * tx * ty;
        out[y * nw + x] += v * wgt;
      }
    }
    let m = 0; for (const v of out) m = Math.max(m, Math.abs(v)); if (m) for (let i = 0; i < out.length; i++) out[i] /= m;
    return out;
  }
  for (let i = 0; i < out.length; i++) out[i] = rnd() * 2 - 1;
  return out;
}
function stimPattern(kind, p) {
  const [W, H] = (p.size || [256, 256]).map((v) => Math.max(1, Math.abs(+v || 1)));
  const sc = Math.max(1, Math.max(W, H) / STIM_MAX);      // px of the stimulus per computed pixel
  const w = Math.max(1, Math.round(W / sc)), h = Math.max(1, Math.round(H / sc));
  const key = JSON.stringify([kind, w, h, p.sf, p.phase, p.wave, p.contrast, p.color, p.mask, p.sigma, p.edge, p.noise_type, p.seed, p.sample, p.element]);
  if (STIM.patterns.has(key)) return STIM.patterns.get(key);
  const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
  const ctx = cv.getContext("2d"), img = ctx.createImageData(w, h), d = img.data;
  const col = stimRgb(p.color), c = Math.max(-1, Math.min(1, +(p.contrast ?? 1)));
  let noise = null, nw = 0, el = 1;
  if (kind === "noise") {
    el = Math.max(1, +p.element || 1) / sc;
    nw = Math.max(1, Math.ceil(w / el)); const nh = Math.max(1, Math.ceil(h / el));
    noise = stimNoise(nw, nh, p.noise_type || "white", ((+p.seed || 0) * 1000003 + (+p.sample || 0)) >>> 0);
  }
  const sf = (+p.sf || 0) * sc, ph = +p.phase || 0;
  for (let j = 0; j < h; j++) {
    for (let i = 0; i < w; i++) {
      let m;
      if (noise) m = noise[Math.min(Math.ceil(h / el) - 1, (j / el) | 0) * nw + Math.min(nw - 1, (i / el) | 0)];
      else { const v = Math.sin(2 * Math.PI * (sf * (i + 0.5 - w / 2) - ph)); m = p.wave === "sqr" ? (v >= 0 ? 1 : -1) : v; }
      const inten = Math.max(0, Math.min(1, 0.5 * (1 + c * m)));
      const k = ((h - 1 - j) * w + i) * 4;     // rows bottom to top, like the experiment window
      d[k] = inten * col[0] * 255; d[k + 1] = inten * col[1] * 255; d[k + 2] = inten * col[2] * 255;
      d[k + 3] = 255 * stimMask(w, h, p.mask || "none", p.sigma, p.edge, i, j, sc);
    }
  }
  ctx.putImageData(img, 0, 0);
  if (STIM.patterns.size > 48) STIM.patterns.delete(STIM.patterns.keys().next().value);
  STIM.patterns.set(key, cv);
  return cv;
}
function stimDrawPattern(ctx, kind, p) {
  const cv = stimPattern(kind, p), [W, H] = (p.size || [256, 256]).map((v) => Math.abs(+v || 1));
  ctx.save(); ctx.scale(1, -1); ctx.imageSmoothingEnabled = true; ctx.drawImage(cv, -W / 2, -H / 2, W, H); ctx.restore();
  return [W / 2, H / 2];
}
function stimDrawDots(ctx, dots, p) {
  ctx.fillStyle = typeof cssColor === "function" ? cssColor(p.color, "#fff") : String(p.color || "#fff");
  const r = Math.max(0.5, (+p.dot_size || 4) / 2);
  ctx.beginPath();
  for (const [x, y] of dots) { ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 2 * Math.PI); }
  ctx.fill();
}

/* ------------------------------------------------------------------ video */
function stimVideo(src, base) {
  const key = (base || "") + "|" + src;
  let v = STIM.videos.get(key);
  if (!v) {
    v = document.createElement("video");
    v.preload = "auto"; v.playsInline = true; v.crossOrigin = "anonymous";
    v.src = stimFileUrl(src, base);
    v.addEventListener("error", () => { v._failed = true; });
    STIM.videos.set(key, v);
  }
  return v;
}
function stimPlaceholder(ctx, w, h, label, minPx = 0) {
  ctx.save(); ctx.strokeStyle = "#8a93a3"; ctx.fillStyle = "rgba(40,44,52,0.85)"; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
  ctx.fillRect(-w / 2, -h / 2, w, h); ctx.strokeRect(-w / 2, -h / 2, w, h); ctx.setLineDash([]);
  ctx.scale(1, -1); ctx.fillStyle = "#cfd5df";
  const s = Math.min(w, h) * 0.18; ctx.beginPath(); ctx.moveTo(-s * 0.5, -s * 0.7 - h * 0.08); ctx.lineTo(s * 0.7, -h * 0.08); ctx.lineTo(-s * 0.5, s * 0.7 - h * 0.08); ctx.closePath(); ctx.fill();
  ctx.font = `${Math.max(14, minPx, Math.min(24, h * 0.1))}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(label, 0, h * 0.22, w * 0.9);
  ctx.restore();
}
/* Try it: the engine says which video time belongs on this refresh (p.vt); the <video> plays and is nudged back in
 * step when it drifts more than a few frames. */
function stimDrawMovie(ctx, p) {
  const base = typeof S !== "undefined" ? S.path : "";
  const v = stimVideo(p.movie, base);
  STIM.drawn.add(v);
  const sz = p.size || [v.videoWidth || 320, v.videoHeight || 180];
  v.loop = false; v.volume = Math.max(0, Math.min(1, p.volume ?? 1)); v.muted = !(p.volume > 0);
  if (v.readyState >= 1 && Math.abs(v.currentTime - (p.vt || 0)) > 0.15) { try { v.currentTime = p.vt || 0; } catch { /* not seekable yet */ } }
  if (v.paused && !v.ended && !v._failed) v.play().catch(() => { v.muted = true; v.play().catch(() => {}); });
  if (v.readyState >= 2 && !v._failed) { ctx.save(); ctx.scale(1, -1); ctx.drawImage(v, -sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); ctx.restore(); }
  else stimPlaceholder(ctx, sz[0], sz[1], v._failed ? "this browser can't play this video (the experiment window can)" : "loading the video…");
}
/* After each Try-it frame: videos the engine no longer draws are paused. */
function stimFrameDone() {
  for (const v of STIM.videos.values()) if (!STIM.drawn.has(v) && !v.paused) v.pause();
  STIM.drawn.clear();
}
function stimStopVideos() { for (const v of STIM.videos.values()) { try { v.pause(); } catch { /* gone */ } } STIM.drawn.clear(); }

/* ------------------------------------------------------------------ Try it */
function drawStimFrame(ctx, kind, p) {
  if (kind === "movie") { stimDrawMovie(ctx, p); return true; }
  if (kind === "grating" || kind === "gabor" || kind === "noise") { stimDrawPattern(ctx, kind, p); return true; }
  if (kind === "dots") { stimDrawDots(ctx, p.dots || [], p); return true; }
  return false;
}

/* ------------------------------------------------------------------ the builder's preview */
const STIM_TYPES = new Set(["movie", "grating", "gabor", "noise", "dots"]);
/* env: {conv(v, axis), W, H, minPx, t, st, base, box(c, hw, hh), doc, units} from drawScreen; returns true when drawn. */
function drawStimPreview(ctx, c, env) {
  if (!STIM_TYPES.has(c.type)) return false;
  const win = (env.doc || (typeof S !== "undefined" ? S.exp : {}))?.settings?.window || {};
  const mon = win.monitor || {};
  const units = c.units || win.units || "px";
  const ppd = 2 * (+mon.distance_cm || 60) * Math.tan(Math.PI / 360) * ((+mon.width_px || env.W) / (+mon.width_cm || 53));
  const L = (v, axis = "y") => units === "deg" ? (+v || 0) * ppd : env.conv(+v || 0, axis);
  const num = (v, d) => (typeof v === "number" && isFinite(v) ? v : d);
  const size2 = (v, d) => Array.isArray(v) ? [L(v[0], "x"), L(v[1], "y")] : typeof v === "number" ? [L(v), L(v)] : d;
  const tt = Math.max(0, (env.t || 0) - (env.st || 0));
  if (c.type === "movie") {
    const src = typeof c.movie === "string" && c.movie && !isExpr(c.movie) ? c.movie : null;
    let sz = size2(c.size, null);
    if (src) {
      const v = stimPoster(src, env.base, tt);
      if (!sz) sz = v.videoWidth ? [v.videoWidth, v.videoHeight] : [320, 180];
      if (v.readyState >= 2 && !v._failed) { ctx.save(); ctx.scale(1, -1); ctx.drawImage(v, -sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); ctx.restore(); }
      else stimPlaceholder(ctx, sz[0], sz[1], `video: ${src.split("/").pop()}`, env.minPx);
    } else stimPlaceholder(ctx, ...(sz || [320, 180]), c.movie ? "video from the trial list" : "no video yet", env.minPx);
    sz ||= [320, 180];
    env.box(c, sz[0] / 2, sz[1] / 2);
    return true;
  }
  if (c.type === "dots") {
    const sz = size2(c.size, [L(300, "x"), L(300)]);
    const n = Math.min(5000, Math.max(0, num(c.n_dots, 100) | 0)), rnd = stimRng(num(c.seed, 1) + 7);
    const dots = [];
    for (let i = 0; i < n * 3 && dots.length < n; i++) {
      const x = (rnd() - 0.5) * sz[0], y = (rnd() - 0.5) * sz[1];
      if ((c.field_shape || "circle") === "square" || (x / (sz[0] / 2)) ** 2 + (y / (sz[1] / 2)) ** 2 <= 1) dots.push([x, y]);
    }
    ctx.save(); ctx.strokeStyle = "rgba(160,170,190,0.35)"; ctx.setLineDash([5, 5]); ctx.lineWidth = 1.5; ctx.beginPath();
    if ((c.field_shape || "circle") === "square") ctx.rect(-sz[0] / 2, -sz[1] / 2, sz[0], sz[1]); else ctx.ellipse(0, 0, sz[0] / 2, sz[1] / 2, 0, 0, 2 * Math.PI);
    ctx.stroke(); ctx.restore();
    stimDrawDots(ctx, dots, {color: typeof c.color === "string" && !isExpr(c.color) ? c.color : "#fff", dot_size: L(num(c.dot_size, 4))});
    // the signal direction, as a faint arrow (0 = right, 90 = up)
    const a = num(c.direction, 0) * Math.PI / 180, r = Math.min(sz[0], sz[1]) * 0.18;
    ctx.save(); ctx.strokeStyle = "rgba(255,200,80,0.8)"; ctx.lineWidth = Math.max(2, r * 0.06); ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(r * Math.cos(a), r * Math.sin(a));
    ctx.lineTo(r * 0.75 * Math.cos(a - 0.3), r * 0.75 * Math.sin(a - 0.3)); ctx.moveTo(r * Math.cos(a), r * Math.sin(a)); ctx.lineTo(r * 0.75 * Math.cos(a + 0.3), r * 0.75 * Math.sin(a + 0.3)); ctx.stroke(); ctx.restore();
    env.box(c, sz[0] / 2, sz[1] / 2);
    return true;
  }
  // grating, gabor, noise
  const sigma = c.sigma !== undefined && c.sigma !== null && !isExpr(c.sigma) ? L(c.sigma) : c.type === "gabor" ? L(30) : null;
  let sz = size2(c.size, null);
  if (!sz) sz = c.type === "gabor" ? [6 * sigma, 6 * sigma] : [L(256, "x"), L(256)];
  const sfUnits = c.sf_units || "cycles/deg";
  const sf = num(c.sf, 2), cpp = sfUnits === "cycles/px" ? sf : sf / ppd;
  const p = {size: sz, sf: cpp, phase: num(c.phase, 0) + num(c.tf, 0) * tt, wave: c.wave || "sin", contrast: num(c.contrast, 1),
    color: typeof c.color === "string" && !isExpr(c.color) ? c.color : "white", mask: c.type === "gabor" ? "gauss" : c.mask || "none",
    sigma, edge: num(c.edge, 0.2), noise_type: c.noise_type || "white", seed: num(c.seed, 1), sample: c.dynamic ? Math.floor(tt * 60 / Math.max(1, num(c.update_frames, 1))) : 0,
    element: c.element_size ? L(c.element_size) : 1};
  stimDrawPattern(ctx, c.type, p);
  env.box(c, sz[0] / 2, sz[1] / 2);
  return true;
}
/* A video element per file for the preview: seeks to the shown moment and repaints the preview when the frame is there. */
function stimPoster(src, base, t) {
  const key = (base || "") + "|" + src;
  let v = STIM.poster.get(key);
  if (!v) {
    v = document.createElement("video");
    v.preload = "auto"; v.muted = true; v.playsInline = true;
    v.src = stimFileUrl(src, base);
    const repaint = () => { if (typeof BUILD !== "undefined") BUILD.imgGen++; if (typeof S !== "undefined" && S.view === "screen" && typeof renderPreview === "function") renderPreview(); if (typeof scheduleBuildRender === "function") scheduleBuildRender(); };
    v.addEventListener("loadeddata", repaint); v.addEventListener("seeked", repaint);
    v.addEventListener("error", () => { v._failed = true; repaint(); });
    STIM.poster.set(key, v);
  }
  const want = Math.min(Math.max(0, t), (v.duration || 1e9) - 0.05);
  if (v.readyState >= 1 && !v.seeking && Math.abs(v.currentTime - want) > 0.04) { try { v.currentTime = want; } catch { /* not yet */ } }
  return v;
}

/* ------------------------------------------------------------------ Experiment settings → Colour & gamma */
function gammaSettings(w) {
  const out = [];
  const g = w.gamma, mon = w.monitor || {};
  const mode = g === undefined || g === null ? (mon.calibration ? "file" : "none") : typeof g === "number" ? "one" : Array.isArray(g) ? "rgb" : "file";
  out.push(h("p", {class: "t-small t-2"}, "Gratings, Gabors and noise are set in linear contrast. A monitor's light is not proportional to the pixel value (its gamma is about 2.2), so EDGE corrects for it when it knows the monitor's gamma: measure it once with a photometer."));
  out.push(h("div", {class: "field", "data-prop": "window.gamma"}, h("div", {class: "lbl-row"}, h("span", {class: "label", id: "set-gamma-l"}, "Gamma correction")),
    inspSeg([{value: "none", label: "None"}, {value: "one", label: "One value"}, {value: "rgb", label: "Per colour"}, {value: "file", label: "Calibration file"}], mode, (v) => {
      if (v === mode) return;
      if (mon.calibration && v !== "file") { w.monitor = {...mon}; delete w.monitor.calibration; }
      setProp(w, "gamma", v === "none" ? null : v === "one" ? 2.2 : v === "rgb" ? [2.2, 2.2, 2.2] : (mon.calibration || "calibration/monitor.json"), "Change the gamma correction");
    }, "set-gamma-l")));
  const numIn = (val, label, on) => h("input", {class: "input num", value: val ?? "", inputmode: "decimal", "aria-label": label, "data-fkey": "set:gamma:" + label,
    onchange: (e) => inspLater(() => { const x = Number(String(e.target.value).replace(",", ".")); if (!(x > 0)) { settingsDraw(); return; } on(x); })});
  if (mode === "one") out.push(h("div", {class: "set-size"}, numIn(g, "Gamma", (x) => setProp(w, "gamma", x, "Change the gamma")), h("span", {class: "t-2"}, "typical monitors: 2.0 to 2.4")));
  if (mode === "rgb") out.push(h("div", {class: "set-size"}, ...["Red", "Green", "Blue"].map((nm, i) => [h("span", {class: "t-2"}, nm), numIn(g[i], nm, (x) => { const v = [...g]; v[i] = x; setProp(w, "gamma", v, "Change the gamma"); })]).flat()));
  if (mode === "file") {
    const cur = typeof g === "string" ? g : mon.calibration || "";
    out.push(h("div", {class: "field"}, h("div", {class: "lbl-row"}, h("label", {for: "set-gamma-file"}, "Calibration file")),
      h("input", {class: "input mono", id: "set-gamma-file", value: cur, "data-fkey": "set:gamma:file", placeholder: "calibration/monitor.json",
        onchange: (e) => inspLater(() => setProp(w, "gamma", e.target.value.trim() || null, "Change the calibration file"))}),
      h("div", {class: "help"}, "A file made by Measure the monitor (or edge gamma), in the experiment's calibration folder.")));
  }
  if (mode !== "none") {
    const m = w.gamma_method || "auto";
    out.push(h("div", {class: "field", "data-prop": "window.gamma_method"}, h("div", {class: "lbl-row"}, h("span", {class: "label", id: "set-gm-l"}, "Correct")),
      inspSeg([{value: "auto", label: "Automatic"}, {value: "ramp", label: "The whole screen"}, {value: "stimuli", label: "Only gratings, Gabors, noise"}], m,
        (v) => setProp(w, "gamma_method", v === "auto" ? null : v, "Change how gamma is corrected"), "set-gm-l"),
      h("div", {class: "help"}, {auto: "The graphics card's gamma table where the computer allows it, otherwise the patterns and the background only.",
        ramp: "The graphics card's gamma table: pictures and text become linear too (as in PsychoPy).",
        stimuli: "Only the procedural patterns and the background colour are corrected; pictures, videos and text are shown as they are."}[m])));
  }
  out.push(h("div", {class: "set-actions"}, h("button", {type: "button", class: "btn", onclick: () => gammaMeasure(w)}, icon("sun"), "Measure the monitor…")),
    h("p", {class: "t-caption"}, "session.json records which calibration each session used. The most exact readings come from the experiment window itself: ",
      h("span", {class: "mono"}, "edge gamma experiment.yaml --show"), "."));
  return out;
}

/* The measuring procedure: grey patches full screen, one reading per level, fit, save calibration/<name>.json. */
async function gammaMeasure(w) {
  if (!S.path || S.noDoc) { toast("Save the experiment first: the calibration is stored next to it."); return; }
  const st = {n: 9, levels: [], readings: []};
  const setN = (n) => { st.n = Math.max(3, Math.min(33, n | 0)); st.levels = Array.from({length: st.n}, (_, i) => +(i / (st.n - 1)).toFixed(4)); st.readings = st.levels.map((_, i) => st.readings[i] ?? ""); };
  setN(9);
  const body = h("div", {class: "gamma-measure"});
  const result = h("div", {class: "gamma-result", role: "status"});
  const draw = () => {
    const rows = st.levels.map((lv, i) => h("tr", {},
      h("td", {}, String(i + 1)), h("td", {}, h("span", {class: "gamma-swatch", style: `background:rgb(${Math.round(lv * 255)},${Math.round(lv * 255)},${Math.round(lv * 255)})`}), ` ${lv} (${Math.round(lv * 255)})`),
      h("td", {}, h("input", {class: "input num", value: st.readings[i], inputmode: "decimal", "aria-label": `Reading for level ${i + 1}`, "data-gamma-i": i,
        oninput: (e) => { st.readings[i] = e.target.value; }})),
      h("td", {}, h("button", {type: "button", class: "btn sm ghost", onclick: () => gammaPatches(st, i, draw)}, "Show"))));
    body.replaceChildren(
      h("ol", {class: "t-small"},
        h("li", {}, "Warm the monitor up for 30 minutes; set brightness and contrast as for the study; turn off dynamic contrast, night light and picture modes."),
        h("li", {}, "Darken the room. Hold the photometer at the centre of the screen."),
        h("li", {}, "Show the patches full screen, read each level and type the luminance (cd/m²); Enter goes to the next level.")),
      h("div", {class: "set-size"}, h("label", {for: "gamma-n"}, "Levels"), h("input", {class: "input num", id: "gamma-n", value: st.n, inputmode: "numeric",
        onchange: (e) => { setN(+e.target.value || 9); draw(); }}),
        h("button", {type: "button", class: "btn primary sm", onclick: () => gammaPatches(st, 0, draw)}, icon("play"), "Show the patches full screen"),
        h("button", {type: "button", class: "btn sm ghost", onclick: () => gammaPaste(st, draw)}, "Paste readings…")),
      h("table", {class: "gamma-table"}, h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, "Grey level"), h("th", {}, "Luminance"), h("th", {}, ""))), h("tbody", {}, rows)));
  };
  const nameIn = h("input", {class: "input", id: "gamma-name", value: "monitor", "aria-label": "Calibration file name"});
  let closeFn = () => {};
  const values = () => st.readings.map((x) => (String(x ?? "").trim() === "" ? NaN : Number(String(x).replace(",", "."))));
  const fit = async (save) => {
    const r = values();
    if (r.some((x) => !isFinite(x))) { result.textContent = "Type a reading for every level first (or paste them)."; return null; }
    try {
      const res = await api("/api/gamma", {path: S.path, levels: st.levels, readings: r, save: !!save, name: nameIn.value.trim() || "monitor"});
      result.replaceChildren(h("pre", {class: "mono t-small"}, res.summary), gammaPlot(st.levels, r, res.fit.grey));
      return res;
    } catch (e) { result.textContent = e.message; return null; }
  };
  const actions = h("div", {class: "set-actions"},
    h("button", {type: "button", class: "btn", onclick: () => fit(false)}, "Fit"),
    h("label", {for: "gamma-name", class: "t-2"}, "Save as calibration/"), nameIn, h("span", {class: "t-2"}, ".json"),
    h("button", {type: "button", class: "btn primary", onclick: async () => {
      const res = await fit(true);
      if (!res || !res.file) return;
      if (w.monitor?.calibration) { w.monitor = {...w.monitor}; delete w.monitor.calibration; }
      setProp(w, "gamma", res.file, "Use the new gamma calibration");
      toast(`Saved ${res.file}: gamma ${res.gamma[0].toFixed(2)}`);
      closeFn("saved");
    }}, "Save and use"));
  const wrap = h("div", {}, body, actions, result);
  draw();
  await ui.dialog({title: "Measure the monitor", icon: "sun", size: "lg", body: wrap, buttons: [{label: "Close", value: null}],
    onOpen: (dlg, close) => { closeFn = close; }, initialFocus: "[data-gamma-i='0']"});
}
/* Full-screen grey patches: type the reading, Enter for the next level, arrows to move, Esc to stop. */
function gammaPatches(st, start, redraw) {
  let i = start;
  const input = h("input", {class: "gamma-in", inputmode: "decimal", "aria-label": "Luminance reading"});
  const cap = h("div", {class: "gamma-cap"});
  const ov = h("div", {class: "gamma-patch", tabindex: "-1"}, h("div", {class: "gamma-bar"}, cap, input));
  const show = () => { const g = Math.round(st.levels[i] * 255); ov.style.background = `rgb(${g},${g},${g})`; cap.textContent = `Level ${i + 1} of ${st.levels.length} (${st.levels[i]}, pixel ${g}) · reading in cd/m², Enter: next · Esc: done`; input.value = st.readings[i] ?? ""; input.focus(); input.select(); };
  const close = () => { document.removeEventListener("keydown", key, true); if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); ov.remove(); redraw(); };
  const key = (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); st.readings[i] = input.value; close(); }
    else if (e.key === "Enter") { e.preventDefault(); st.readings[i] = input.value; if (i < st.levels.length - 1) { i++; show(); } else close(); }
    else if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); st.readings[i] = input.value; i = Math.max(0, Math.min(st.levels.length - 1, i + (e.key === "ArrowRight" ? 1 : -1))); show(); }
  };
  document.addEventListener("keydown", key, true);
  document.body.append(ov);
  ov.requestFullscreen?.().catch(() => {});
  show();
}
async function gammaPaste(st, redraw) {
  const ta = h("textarea", {class: "input mono", rows: 8, placeholder: "one reading per line, black to white\nor CSV: level,luminance", "aria-label": "Readings"});
  const v = await ui.dialog({title: "Paste readings", body: h("div", {}, ta), buttons: [{label: "Cancel", value: null}, {label: "Use", value: "use", kind: "primary"}], initialFocus: ta});
  if (v !== "use") return;
  const rows = ta.value.trim().split(/\r?\n/).map((l) => l.split(/[,;\t ]+/).filter(Boolean)).filter((r) => r.length && r.every((x) => isFinite(Number(x.replace(",", ".")))));
  if (!rows.length) { toast("No numbers found."); return; }
  if (rows[0].length >= 2) {
    const lv = rows.map((r) => Number(r[0])), mx = Math.max(...lv);
    st.levels = lv.map((x) => mx > 1 ? +(x / 255).toFixed(4) : x); st.readings = rows.map((r) => r[1]); st.n = rows.length;
  } else {
    st.n = rows.length; st.levels = Array.from({length: st.n}, (_, i) => +(i / Math.max(1, st.n - 1)).toFixed(4)); st.readings = rows.map((r) => r[0]);
  }
  redraw();
}
/* The readings and the fitted curve, drawn small (SVG, follows the theme). */
function gammaPlot(levels, lum, fit) {
  const W = 260, H = 150, pad = 26, NS = "http://www.w3.org/2000/svg";
  const lo = Math.min(...lum), hi = Math.max(...lum);
  const X = (v) => pad + v * (W - pad - 8), Y = (L) => H - pad - (L - lo) / Math.max(1e-9, hi - lo) * (H - pad - 8);
  const svg = document.createElementNS(NS, "svg"); svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "gamma-plot"); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Measured luminance and the fitted curve, gamma ${fit ? fit.gamma : ""}`);
  let d = ""; for (let i = 0; i <= 40; i++) { const v = i / 40; d += (i ? "L" : "M") + X(v).toFixed(1) + "," + Y(fit.l0 + fit.k * v ** fit.gamma).toFixed(1); }
  svg.innerHTML = `<path d="M${pad},${H - pad}H${W - 8}M${pad},${H - pad}V8" stroke="currentColor" opacity=".35" fill="none"/>`
    + `<path d="${d}" stroke="var(--accent, #2f6fde)" stroke-width="2" fill="none"/>`
    + levels.map((v, i) => `<circle cx="${X(v).toFixed(1)}" cy="${Y(lum[i]).toFixed(1)}" r="3.2" fill="currentColor"/>`).join("")
    + `<text x="${pad}" y="${H - 8}" font-size="10" fill="currentColor">0</text><text x="${W - 16}" y="${H - 8}" font-size="10" fill="currentColor">1</text>`;
  return svg;
}
