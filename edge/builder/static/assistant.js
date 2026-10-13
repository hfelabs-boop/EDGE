/* assistant.js: the assistant panel (companion tab), the Home "Describe it" card, Assistant settings and the privacy
 * consent (SPEC W1, W2, W16, W17; assistant spec §11). Owner: P3.
 *
 * Talks to the app only through EDGE (§7.5.1), ui (§7.5.3) and the shared helpers h(), icon(), api(); the backend is
 * /api/assistant/* (assistant spec §10). Defines the global `Assistant` (§7.5.2), also as window.Assistant.
 * Optional helpers of other modules (tryNow, dryRun, openHelp, startWizard, confirmLeaveDirty, shortRoot,
 * renderFiles) are called only when they exist.
 *
 * Model text, file previews and file content never go into innerHTML: everything is built with textContent
 * (a tiny Markdown subset: paragraphs, lists, **bold**, `code`).
 */
"use strict";

const Assistant = (() => {
  /* ================================================================ constants */
  const PROVIDERS = ["anthropic", "openai", "ollama", "lmstudio"];
  const INFO = {
    anthropic: {title: "Claude (Anthropic)", text: "Best results. Online, needs an API key.", short: "Best results · API key · online", icon: "cloud", cloud: true},
    openai: {title: "OpenAI-compatible", text: "OpenAI, OpenRouter or another service.", short: "OpenAI, OpenRouter… · API key", icon: "cloud", cloud: true},
    ollama: {title: "Ollama", text: "Free. Runs on this computer.", short: "Free · on this computer", icon: "chip", cloud: false},
    lmstudio: {title: "LM Studio", text: "Free. Runs on this computer.", short: "Free · on this computer", icon: "chip", cloud: false},
  };
  const DEFAULT_URL = {ollama: "http://localhost:11434", lmstudio: "http://localhost:1234/v1",
    anthropic: "https://api.anthropic.com", openai: "https://api.openai.com/v1"};
  const ACCEPT = ".png,.jpg,.jpeg,.gif,.bmp,.webp,.tif,.tiff,.svg,.wav,.mp3,.ogg,.flac,.m4a,.aiff,.aif,.csv,.tsv,.xlsx,"
    + ".txt,.md,.json,.yaml,.yml,.html,.htm,.xls,.docx,.doc,.pdf,.odt";
  const ACCEPT_WORDS = "Pictures, CSV, Excel, text, JSON, HTML";
  const MAX_MSGS = 50;
  const HOME_EXAMPLES = [
    "e.g. “Stroop task: colour words in red, green or blue ink; press R, G or B for the ink colour. Practice until 80 % correct, then 2 blocks of 36.”",
    "e.g. “Show each picture from my folder for 4 seconds after a fixation cross, in random order, and record where people look.”",
    "e.g. “A consent page, then a questionnaire with age, gender and the 10 items of the attached list on a 1–5 scale.”",
  ];
  const HOME_TRY = [
    ["Visual search with eye tracking", "Visual search with eye tracking: find the T among Ls on a grid of 8, 16 or 24 letters; press space when found; record gaze; 3 blocks of 40 trials with a short break between blocks."],
    ["Auditory oddball with EEG triggers", "Auditory oddball: 80 % low tones (500 Hz) and 20 % high tones (1000 Hz), 100 ms each, every 1 s with 0.2 s jitter; press space for the high tones; send a trigger to the EEG at every tone; 2 blocks of 150 tones."],
    ["Consent page and a questionnaire", "A consent page with an I agree button, then a questionnaire: age, gender, handedness, and the PHQ-9 on its usual 0–3 scale. Thank them at the end."],
  ];
  const KEY = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "") ? "⌘" : "Ctrl";

  /* ================================================================ state */
  const st = {
    view: null,                  // GET /api/assistant/status (the public view: never a key)
    unavailable: false,          // the endpoints are missing: the feature hides itself
    key: null,                   // transcript key in EDGE.prefs ("assistant.<path>")
    convId: null,                // the server's conversation id for this experiment
    convFromThisPage: false,     // created or confirmed during this page session (no recap needed)
    msgs: [],                    // the visible transcript (persisted, at most 50)
    jobs: new Map(),             // live jobs of this page session, by id
    job: null,                   // the running job (one at a time)
    previewJob: null,            // the job whose result is in EDGE.proposal
    pending: [],                 // attachments waiting in the panel composer
    panelPath: null,             // folder reserved by a panel attachment while no experiment is open
    focusOff: false,             // the researcher removed the "About: …" chip
    forcedFocus: null,           // focus given by an entry point (fixIssue) until the selection changes
    lastFocusKey: "",
    lastAppliedAt: 0,
    panelBuilt: false,
    stick: true,
    home: {el: null, compact: false, expanded: false, atts: [], path: null, nameEdited: false, nameTimer: null,
      placeholder: 0, text: "", name: ""},
    els: {},
    tick: null,
    pasteCount: 0,
  };
  let readyResolve = null;
  const readyPromise = new Promise((res) => { readyResolve = res; });

  /* ================================================================ small helpers */
  const enc = encodeURIComponent;
  const q = (s) => `“${s}”`;
  const nowClock = () => new Date().toTimeString().slice(0, 5);
  const isExpert = () => !document.body.classList.contains("mode-simple");
  const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
  const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const prefs = {
    get: (k, d) => { try { return EDGE.prefs.get(k, d); } catch { return d; } },
    set: (k, v) => { try { EDGE.prefs.set(k, v); } catch { /* storage off */ } },
  };
  const g = (name) => (typeof window[name] === "function" ? window[name] : null);   // optional globals of other modules
  const call = (name, ...args) => { const f = g(name); if (f) { try { return f(...args); } catch (e) { console.error(e); } } return undefined; };
  function safe(fn, dflt = null) { try { return fn(); } catch { return dflt; } }
  const docPath = () => safe(() => EDGE.path(), null);

  function btn(label, onclick, {kind = "", ic = null, id = null, tip = null, sm = true} = {}) {
    const b = h("button", {type: "button", class: `btn${sm ? " sm" : ""}${kind ? " " + kind : ""}`, id, "data-tip": tip});
    if (ic) b.append(icon(ic));
    if (label) b.append(document.createTextNode(label));
    b.addEventListener("click", onclick);
    return b;
  }
  function iconBtn(ic, label, onclick, {id = null, cls = "ghost", pos = null, sm = true} = {}) {
    const b = h("button", {type: "button", class: `btn icon${sm ? " sm" : ""} ${cls}`, id, "aria-label": label, "data-tip": label,
      "data-tip-pos": pos});
    b.append(icon(ic));
    b.addEventListener("click", onclick);
    return b;
  }
  const errText = (e) => (e ? (e.data && e.data.error) || e.message || String(e) : "Something went wrong.");
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch { /* not allowed here: fall back */ }
    const ta = h("textarea", {style: "position:fixed;left:-9999px;top:0", "aria-hidden": "true"});
    ta.value = text; document.body.append(ta); ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    return ok;
  }

  /* --- Markdown subset → DOM (textContent only) */
  function inlineMd(s) {
    const frag = document.createDocumentFragment();
    const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
    let last = 0, m;
    while ((m = re.exec(s))) {
      if (m.index > last) frag.append(document.createTextNode(s.slice(last, m.index)));
      const t = m[0];
      frag.append(t.startsWith("**") ? h("strong", {}, t.slice(2, -2)) : h("code", {}, t.slice(1, -1)));
      last = m.index + t.length;
    }
    if (last < s.length) frag.append(document.createTextNode(s.slice(last)));
    return frag;
  }
  function mdNodes(text) {
    const out = h("div", {class: "md"});
    const LI = /^\s*([-*•]|\d+[.)])\s+/;
    let para = null, list = null;
    for (const raw of String(text ?? "").replace(/\r/g, "").split("\n")) {
      const line = raw.replace(/\s+$/, "");
      if (!line.trim()) { para = null; list = null; continue; }
      if (LI.test(line)) {
        para = null;
        const ordered = /^\s*\d/.test(line);
        if (!list || (list.tagName === "OL") !== ordered) { list = h(ordered ? "ol" : "ul", {}); out.append(list); }
        list.append(h("li", {}, inlineMd(line.replace(LI, ""))));
        continue;
      }
      list = null;
      const head = /^#{1,6}\s+(.*)$/.exec(line);
      if (head) { para = null; out.append(h("p", {}, h("strong", {}, head[1]))); continue; }
      if (!para) { para = h("p", {}); out.append(para); } else para.append(h("br"));
      para.append(inlineMd(line));
    }
    return out;
  }
  /* a hint such as "Run `ollama pull qwen2.5:14b` in a terminal" with copyable code chips */
  function hintNodes(text) {
    const p = h("p", {class: "hint"});
    for (const part of String(text || "").split(/(`[^`]+`)/)) {
      if (/^`[^`]+`$/.test(part)) {
        const code = part.slice(1, -1);
        const chip = h("button", {type: "button", class: "codechip", "aria-label": `Copy ${code}`, "data-tip": "Copy"},
          h("code", {}, code), icon("duplicate"));
        chip.addEventListener("click", async () => {
          EDGE.toast((await copyText(code)) ? "Copied. Paste it into a terminal." : "Couldn't copy: select the text and copy it.");
        });
        p.append(chip);
      } else if (part) p.append(document.createTextNode(part));
    }
    return p;
  }

  /* --- SHA-256 (synchronous) for the code-review gate: the same hash as code_hashes() in edge/assistant/tools.py */
  const SHA_K = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb,
    0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f,
    0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
  function sha256(str) {
    const msg = new TextEncoder().encode(str);
    const n = msg.length;
    const total = Math.ceil((n + 9) / 64) * 64;
    const buf = new Uint8Array(total);
    buf.set(msg); buf[n] = 0x80;
    const dv = new DataView(buf.buffer);
    dv.setUint32(total - 4, (n * 8) >>> 0);
    dv.setUint32(total - 8, Math.floor((n * 8) / 0x100000000));
    const H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    const W = new Uint32Array(64);
    const rotr = (x, r) => (x >>> r) | (x << (32 - r));
    for (let off = 0; off < total; off += 64) {
      for (let i = 0; i < 16; i++) W[i] = dv.getUint32(off + i * 4);
      for (let i = 16; i < 64; i++) {
        const s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >>> 3);
        const s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >>> 10);
        W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
      }
      let [a, b, c, d, e, f, gg, hh] = H;
      for (let i = 0; i < 64; i++) {
        const t1 = (hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & gg)) + SHA_K[i] + W[i]) >>> 0;
        const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0;
        hh = gg; gg = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
      }
      H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
      H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + gg) >>> 0; H[7] = (H[7] + hh) >>> 0;
    }
    return H.map((x) => x.toString(16).padStart(8, "0")).join("");
  }
  /* Python's json.dumps for a string (ensure_ascii): non-ASCII as \uXXXX */
  const pyStr = (s) => JSON.stringify(String(s)).replace(/[\u0080-￿]/g, (ch) => "\\u" + ch.charCodeAt(0).toString(16).padStart(4, "0"));
  function codeHash(c) {
    const parts = ["on_begin", "on_frame", "on_end"].map((k) => {
      const v = c && c[k];
      return typeof v === "string" || !v ? pyStr(v || "") : JSON.stringify(v);
    });
    return sha256("[" + parts.join(", ") + "]");
  }

  /* ================================================================ status and providers */
  async function refreshStatus() {
    try {
      st.view = await api("/api/assistant/status");
      st.unavailable = false;
    } catch (e) {
      if (e.status === 404 || e.status === 405) st.unavailable = true;
    }
    if (readyResolve) { readyResolve(publicStatus()); readyResolve = null; }
    renderHeadAndState();
    if (st.home.el) renderHome();
    return st.view;
  }
  const providerOf = (v = st.view) => (v && v.provider && PROVIDERS.includes(v.provider) ? v.provider : null);
  const prow = (name, v = st.view) => ((v && v.providers) || {})[name] || {};
  function modelLabel(name, model) {
    if (!model) return "";
    if (name === "anthropic") {
      const r = (((st.view || {}).recommended_models || {}).anthropic || []).find((m) => m.id === model);
      return r ? r.label : model;
    }
    return model;
  }
  const isLocal = (name) => !!name && !INFO[name].cloud && prow(name).on_this_computer !== false;
  function serviceName(name) {
    if (name === "anthropic") return "Anthropic";
    if (name === "openai") return prow("openai").service || "OpenAI";
    const app = name === "ollama" ? "Ollama" : "LM Studio";
    const host = safe(() => new URL(prow(name).base_url).hostname, "");
    return isLocal(name) ? app : `${app} at ${host || "another computer"}`;
  }
  function publicStatus() {
    const v = st.view, p = providerOf(v), r = p ? prow(p, v) : {};
    return {configured: !!(v && v.configured), provider: p, label: providerLabel(), kind: p ? (isLocal(p) ? "local" : "cloud") : null,
      model: r.model || null, consented: p ? r.consented !== false : false, unavailable: st.unavailable};
  }
  /* "Ollama · qwen2.5:14b · on this computer", "Claude Opus 5.5 · online", "Not set up" */
  function providerLabel() {
    const v = st.view, p = providerOf(v);
    if (!v || !p || !v.configured) return "Not set up";
    const m = modelLabel(p, prow(p, v).model);
    if (p === "anthropic") return `${m || "Claude"} · online`;
    if (p === "openai") return `${serviceName("openai")} · ${m || "no model"} · online`;
    return `${p === "ollama" ? "Ollama" : "LM Studio"} · ${m || "no model"} · ${isLocal(p) ? "on this computer" : "on another computer"}`;
  }
  function providerChip(onclick, {id = null, lg = false} = {}) {
    const on = !!(st.view && st.view.configured);
    const b = h("button", {type: "button", class: `prov${on ? " on" : ""}${lg ? " lg" : ""}`, id,
      "aria-label": `Assistant: ${providerLabel()}. Open Assistant settings`, "data-tip": "Assistant settings"},
    h("span", {class: "live", "aria-hidden": "true"}), h("span", {class: "txt"}, providerLabel()), icon("chev-down"));
    b.addEventListener("click", onclick);
    return b;
  }
  function privacyLine() {
    const p = providerOf();
    if (!p || !(st.view && st.view.configured)) return null;
    if (isLocal(p)) return h("p", {class: "asst-privacy"}, icon("lock"), "On this computer: nothing is sent anywhere.");
    return h("p", {class: "asst-privacy"}, icon("cloud"),
      INFO[p].cloud ? `Sent to ${serviceName(p)} to answer. Your API key stays on this computer.` : `Sent to ${serviceName(p)} to answer.`);
  }

  /* ================================================================ transcript persistence (assistant spec §11.6) */
  const keyFor = (path) => "assistant." + (path || "untitled");
  function loadTranscript(path) {
    st.key = keyFor(path);
    const saved = prefs.get(st.key, null);
    st.msgs = saved && Array.isArray(saved.messages) ? saved.messages.slice(-MAX_MSGS) : [];
    st.convId = saved && typeof saved.conversation === "string" ? saved.conversation : null;
    st.convFromThisPage = false;
    for (const m of st.msgs) delete m.live;     // cards from an earlier page session are history now
  }
  function persist() {
    if (!st.key) return;
    const messages = st.msgs.slice(-MAX_MSGS).map((m) => { const o = {...m}; delete o.live; return o; });
    prefs.set(st.key, {conversation: st.convId, messages});
  }
  function pushMsg(m) {
    st.msgs.push(m);
    if (st.msgs.length > MAX_MSGS) st.msgs.splice(0, st.msgs.length - MAX_MSGS);
    persist();
  }
  const recap = () => st.msgs.filter((m) => (m.role === "user" || m.role === "assistant") && m.text).slice(-6)
    .map((m) => ({role: m.role, text: String(m.text).slice(0, 1500)}));

  /* ================================================================ marks for the preview (§7.5.2) */
  function flowNodes(flow, out = []) {
    for (const n of flow || []) {
      if (!n || typeof n !== "object") continue;
      out.push(n);
      flowNodes(n.children, out); flowNodes(n.then, out); flowNodes(n.else, out);
      for (const s of Object.values(n.states || {})) if (s && typeof s === "object") flowNodes(s.run, out);
    }
    return out;
  }
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const childName = (k) => (typeof k === "string" ? k : String((k && (k.loop || k.routine || k.statemachine || k.if)) || "?"));
  function computeMarks(base, next) {
    const marks = {routines: {}, components: {}, loops: {}, devices: {}, machines: {}, removed: []};
    base = base || {}; next = next || {};
    const rb = base.routines || {}, ra = next.routines || {};
    for (const [rid, r] of Object.entries(ra)) {
      if (!(rid in rb)) { marks.routines[rid] = "added"; continue; }
      if (same(rb[rid], r)) continue;
      marks.routines[rid] = "changed";
      const cb = new Map(((rb[rid] || {}).components || []).map((c) => [c && c.id, c]));
      const ca = new Map(((r || {}).components || []).map((c) => [c && c.id, c]));
      for (const [cid, c] of ca) {
        if (!cb.has(cid)) marks.components[`${rid}/${cid}`] = "added";
        else if (!same(cb.get(cid), c)) marks.components[`${rid}/${cid}`] = "changed";
      }
      for (const cid of cb.keys()) if (!ca.has(cid)) marks.removed.push({kind: "component", id: `${rid}/${cid}`, routine: rid});
    }
    for (const rid of Object.keys(rb)) if (!(rid in ra)) marks.removed.push({kind: "routine", id: rid});
    const byKey = (doc, key) => new Map(flowNodes(doc.flow).filter((n) => n[key] !== undefined).map((n) => [String(n[key]), n]));
    const strip = (n) => { const o = {...n}; delete o.children; return o; };
    for (const [key, bucket, kind] of [["loop", "loops", "loop"], ["statemachine", "machines", "workflow"]]) {
      const lb = byKey(base, key), la = byKey(next, key);
      for (const [id, n] of la) {
        if (!lb.has(id)) marks[bucket][id] = "added";
        else if (!same(strip(lb.get(id)), strip(n)) || !same((lb.get(id).children || []).map(childName), (n.children || []).map(childName))) marks[bucket][id] = "changed";
      }
      for (const id of lb.keys()) if (!la.has(id)) marks.removed.push({kind, id});
    }
    const db = new Map((base.devices || []).map((d) => [d && d.id, d])), da = new Map((next.devices || []).map((d) => [d && d.id, d]));
    for (const [id, d] of da) { if (!db.has(id)) marks.devices[id] = "added"; else if (!same(db.get(id), d)) marks.devices[id] = "changed"; }
    for (const id of db.keys()) if (!da.has(id)) marks.removed.push({kind: "device", id});
    if (!same(base.settings || {}, next.settings || {})) marks.settings = "changed";
    if (!same(base.measures || [], next.measures || [])) marks.measures = "changed";
    return marks;
  }

  /* ================================================================ the code-review gate (assistant spec §11.6) */
  const listPref = (k) => { const v = prefs.get(k, []); return Array.isArray(v) ? v : []; };
  function rememberWritten(review) {
    const hashes = (review || []).filter((r) => r.kind === "code" && /^[0-9a-f]{64}$/.test(r.hash || "")).map((r) => r.hash);
    if (hashes.length) prefs.set("assistant.code", [...new Set([...listPref("assistant.code"), ...hashes])].slice(-500));
  }
  function codeComponents(doc) {
    const out = [];
    for (const [rid, r] of Object.entries((doc && doc.routines) || {})) {
      for (const c of (r && r.components) || []) if (c && c.type === "code") out.push({routine: rid, id: c.id, comp: c});
    }
    return out;
  }
  function unreviewedCode(doc) {
    const written = new Set(listPref("assistant.code"));
    if (!written.size) return [];
    const reviewed = new Set(listPref("assistant.reviewed"));
    return codeComponents(doc || safe(() => EDGE.doc())).map((x) => ({...x, hash: codeHash(x.comp)}))
      .filter((x) => written.has(x.hash) && !reviewed.has(x.hash)).map(({routine, id}) => ({routine, id}));
  }
  function markReviewed(routine, id) {
    const c = codeComponents(safe(() => EDGE.doc())).find((x) => x.routine === routine && x.id === id);
    if (!c) return false;
    prefs.set("assistant.reviewed", [...new Set([...listPref("assistant.reviewed"), codeHash(c.comp)])].slice(-500));
    for (const job of st.jobs.values()) refreshJob(job);
    return true;
  }

  /* ================================================================ the panel: skeleton */
  const panelEl = () => document.getElementById("assistant-panel");

  function buildPanel() {
    const panel = panelEl();
    if (!panel) return;
    panel.classList.add("asst-host");
    const head = h("div", {class: "asst-head"});
    const log = h("div", {class: "asst-log", role: "log", "aria-label": "Conversation with the assistant", tabindex: "-1"});
    const ctx = h("div", {class: "asst-ctx", hidden: true});
    const atts = h("div", {id: "assistant-attachments", class: "atts", role: "list", "aria-label": "Attached files", hidden: true});
    const input = h("textarea", {id: "assistant-input", rows: "2", "aria-label": "Describe a change, or ask a question",
      placeholder: "Describe a change, or ask a question…"});
    const fileIn = h("input", {type: "file", multiple: true, accept: ACCEPT, hidden: true, tabindex: "-1", "aria-hidden": "true"});
    const attachBtn = iconBtn("attach", "Attach files", () => fileIn.click(), {id: "assistant-attach", pos: "start"});
    attachBtn.setAttribute("data-tip", "Attach files (copied into this experiment's folder)");
    const sendBtn = h("button", {type: "button", id: "assistant-send", class: "btn sm icon primary", "aria-label": "Send",
      "data-tip": "Send (Enter)", "data-tip-pos": "end"}, icon("send"));
    const tools = h("div", {class: "row"}, attachBtn, h("span", {class: "types"}, ACCEPT_WORDS), h("span", {class: "grow"}), sendBtn);
    const box = h("div", {class: "box"}, atts, input, tools);
    const keys = h("p", {class: "asst-keys"}, "Enter sends · Shift+Enter new line");
    const priv = h("div", {class: "asst-priv-host"});
    const composer = h("div", {class: "composer"}, ctx, box, keys, priv, fileIn);
    const drop = h("div", {class: "asst-drop", hidden: true, "aria-hidden": "true"}, icon("attach", "l"), h("b", {}, "Drop files to attach"),
      h("span", {class: "t-small"}, "They are copied into this experiment's folder."));
    const root = h("div", {class: "asst"}, head, log, composer, drop);
    panel.replaceChildren(root);
    st.els = {panel, root, head, log, ctx, atts, input, fileIn, attachBtn, sendBtn, box, keys, priv, composer, drop};

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submitPanel(); }
    });
    input.addEventListener("input", () => { autosize(input); updateSendState(); });
    input.addEventListener("paste", (e) => onPaste(e, (files) => attachFiles(files, "panel")));
    sendBtn.addEventListener("click", () => submitPanel());
    fileIn.addEventListener("change", () => { const f = [...fileIn.files]; fileIn.value = ""; attachFiles(f, "panel"); });
    wireDrop(root, (on) => { drop.hidden = !on; }, (files) => attachFiles(files, "panel"));
    root.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && e.target !== input && st.previewJob && EDGE.proposal.active()) {
        e.preventDefault(); e.stopPropagation(); EDGE.proposal.apply();
      }
    });
    log.addEventListener("scroll", () => { st.stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 40; });
    st.panelBuilt = true;
    renderHeadAndState();
    renderLog();
    renderContext();
    renderPending();
  }
  function autosize(ta) {
    ta.style.height = "auto";
    ta.style.height = Math.min(200, Math.max(44, ta.scrollHeight)) + "px";
  }
  function onPaste(e, attach) {
    const items = [...((e.clipboardData && e.clipboardData.items) || [])].filter((it) => it.kind === "file");
    if (!items.length) return;
    e.preventDefault();
    let pics = 0;
    const files = items.map((it) => it.getAsFile()).filter(Boolean).map((f) => {
      if (/^image\//.test(f.type) && (!f.name || /^image\.\w+$/.test(f.name))) {
        const ext = (f.type.split("/")[1] || "png").replace("jpeg", "jpg");
        st.pasteCount++; pics++;
        return new File([f], `pasted-image-${st.pasteCount}.${ext}`, {type: f.type});
      }
      return f;
    });
    attach(files);
    if (pics) EDGE.announce(`Attaching ${plural(pics, "pasted picture")}.`);
  }
  function wireDrop(zone, show, attach) {
    let depth = 0;
    const hasFiles = (e) => [...((e.dataTransfer && e.dataTransfer.types) || [])].includes("Files");
    zone.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth++; show(true); });
    zone.addEventListener("dragover", (e) => { if (!hasFiles(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
    zone.addEventListener("dragleave", (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) show(false); });
    zone.addEventListener("drop", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault(); e.stopPropagation(); depth = 0; show(false);
      const files = [...(e.dataTransfer.files || [])];
      if (files.length) attach(files);
    });
  }

  function renderHeadAndState() {
    if (!st.panelBuilt) return;
    const {head, priv, input, keys} = st.els;
    const menuBtn = iconBtn("more", "Assistant menu", (e) => openPanelMenu(e.currentTarget), {id: "assistant-menu", pos: "end"});
    menuBtn.setAttribute("aria-haspopup", "menu");
    head.replaceChildren(icon("assistant", "lead"), providerChip(() => openSettings(), {id: "assistant-provider-chip"}),
      h("span", {class: "grow"}), menuBtn);
    priv.replaceChildren(...[privacyLine()].filter(Boolean));
    const configured = !!(st.view && st.view.configured);
    input.placeholder = st.job ? "Wait for the assistant to finish"
      : st.previewJob && safe(() => EDGE.proposal.active(), false) ? "Say what to change in this proposal, or ask a question…"
      : "Describe a change, or ask a question…";
    keys.hidden = !configured;
    updateSendState();
    if (!st.msgs.length || !configured) renderLog();
  }
  function updateSendState() {
    if (!st.panelBuilt) return;
    const {sendBtn, input, attachBtn} = st.els;
    const busy = !!st.job;
    input.disabled = busy;
    attachBtn.disabled = busy;
    const configured = !!(st.view && st.view.configured);
    sendBtn.disabled = busy || (configured && !input.value.trim());
    sendBtn.setAttribute("data-tip", configured ? "Send (Enter)" : "Set up the assistant first");
  }

  /* the ⋯ menu: New conversation · Assistant settings · Copy conversation */
  function openPanelMenu(anchor) {
    const m = ui.menu(anchor, [
      {label: "New conversation", icon: "plus", run: () => newConversation()},
      {label: "Assistant settings", icon: "settings", run: () => openSettings()},
      {label: "Copy conversation", icon: "duplicate", disabled: !st.msgs.length, run: () => copyConversation()},
    ], {placement: "bottom-end"});
    const items = m && m.el ? [...m.el.querySelectorAll('[role^="menuitem"]')] : [];
    if (items[1]) items[1].id = "assistant-settings";
  }
  function newConversation() {
    if (st.job) { EDGE.toast("Wait for the assistant to finish, or press Stop."); return; }
    st.msgs = []; st.convId = null; st.convFromThisPage = true;
    persist();
    renderLog();
    if (st.els.input) st.els.input.focus();
    EDGE.announce("New conversation.");
  }
  async function copyConversation() {
    const lines = st.msgs.map((m) => {
      if (m.role === "user") return `You: ${m.text}${(m.atts || []).length ? `\n  (attached: ${m.atts.map((a) => a.name).join(", ")})` : ""}`;
      if (m.role === "assistant") {
        const job = m.jobId ? st.jobs.get(m.jobId) : null;
        const changes = ((job && job.result && job.result.changes) || []).map((c) => `  - ${c.text}`).join("\n");
        return `Assistant: ${m.text || m.error || ""}${changes ? "\n" + changes : ""}${m.state ? `\n  (${m.state})` : ""}`;
      }
      return m.text ? `(${m.text})` : "";
    }).filter(Boolean);
    EDGE.toast((await copyText(lines.join("\n\n"))) ? "Copied the conversation." : "Couldn't copy the conversation.");
  }

  /* ================================================================ the log */
  function renderLog() {
    if (!st.panelBuilt) return;
    const nodes = [];
    if (st.unavailable) {
      nodes.push(h("div", {class: "asst-intro"}, h("p", {class: "t-2"}, "The assistant isn't available in this version of EDGE. Everything else works without it.")));
    } else if (st.view && !st.view.configured) nodes.push(setupIntro());
    for (const m of st.msgs) nodes.push(msgNode(m));
    if (st.view && st.view.configured && !st.msgs.length) nodes.push(readyIntro());
    st.els.log.replaceChildren(...nodes);
    scrollLog(true);
  }
  function scrollLog(force = false) {
    const log = st.els.log;
    if (log && (force || st.stick)) requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
  }

  /* (a) not set up */
  function setupIntro() {
    const cards = PROVIDERS.map((p) => {
      const b = h("button", {type: "button", class: "prov-card", "data-provider": p},
        h("span", {class: "pc-head"}, icon(INFO[p].icon), h("b", {}, INFO[p].title)), h("span", {class: "pc-text"}, INFO[p].short));
      b.addEventListener("click", () => openSettings(p));
      return b;
    });
    return h("div", {class: "asst-intro setup"},
      h("h3", {class: "t-title-s"}, "Build and change experiments by describing them"),
      h("p", {class: "t-2"}, "Describe what you want in your own words and attach your files. You see and approve every change."),
      h("div", {class: "prov-grid", role: "group", "aria-label": "Choose where the assistant runs"}, cards),
      h("p", {class: "t-caption"}, "Everything else in EDGE works without it."));
  }

  /* (b) ready, new conversation: suggestions for what is open */
  function suggestions() {
    const doc = safe(() => EDGE.doc(), null) || {};
    const routines = doc.routines || {};
    const empty = !(doc.flow || []).length && !Object.values(routines).some((r) => ((r && r.components) || []).length);
    if (empty) {
      return ["Build a Stroop task with 2 blocks of 36 trials", "Add instructions and a thank-you screen",
        "Make a consent page and a short questionnaire", "Explain how an experiment is made"];
    }
    const out = [];
    const f = currentFocus();
    if (f && f.kind === "component") out.push(`Make ${q(f.id)} bigger`);
    else if (Object.values(routines).some((r) => ((r && r.components) || []).some((c) => c && c.type === "text"))) out.push("Make the words bigger");
    out.push("Add a 300–700 ms jittered fixation");
    if (!flowNodes(doc.flow).some((n) => /practice/i.test(String(n.loop || n.routine || n.statemachine || "")))) out.push("Add a practice block with feedback");
    if ((safe(() => EDGE.issues(), []) || []).some((i) => i.level === "error" || i.level === "warning")) out.push("Fix the problems Check found");
    out.push("Explain this experiment");
    return out.slice(0, 5);
  }
  function readyIntro() {
    const list = h("div", {class: "asst-try", role: "list"});
    for (const s of suggestions()) {
      const b = h("button", {type: "button", class: "try-chip", role: "listitem"}, s);
      b.addEventListener("click", () => {
        const input = st.els.input;
        input.value = s; autosize(input); updateSendState(); input.focus();
        input.setSelectionRange(s.length, s.length);
      });
      list.append(b);
    }
    return h("div", {class: "asst-intro ready"},
      h("p", {class: "t-2"}, "Describe a change in your own words, or ask about this experiment. Nothing changes until you apply it."),
      h("p", {class: "t-overline"}, "Try"), list);
  }

  /* messages */
  function attStatic(a) {
    return h("span", {class: "att static", role: "listitem", title: a.summary || a.name},
      h("span", {class: `ft ${badgeClass(a.kind, a.name)}`}, badgeText(a.kind, a.name)),
      h("span", {class: "nm"}, a.name), a.short ? h("span", {class: "sz"}, a.short) : null);
  }
  const whoLine = () => h("div", {class: "who"}, icon("assistant"), "Assistant");
  function msgNode(m) {
    if (m.role === "user") {
      return h("div", {class: "asst-msg user"}, h("span", {class: "sr-only"}, "You: "), mdNodes(m.text),
        (m.atts || []).length ? h("div", {class: "atts", role: "list"}, m.atts.map(attStatic)) : null);
    }
    if (m.role === "note") return h("p", {class: "asst-note"}, m.text);
    const job = m.jobId ? st.jobs.get(m.jobId) : null;
    if (job) { job.node = jobNode(job); return job.node; }
    /* an answer or a result from an earlier page session */
    const body = [whoLine()];
    if (m.text) body.push(mdNodes(m.text));
    if (m.n) {
      const word = {applied: "Applied", undone: "Undone", discarded: "Discarded", preview: "Not applied"}[m.state] || "";
      body.push(h("p", {class: `asst-past ${m.state || ""}`}, icon(m.state === "applied" ? "success" : "info"),
        `${plural(m.n, "change")}${word ? ` · ${word}` : ""}${m.time ? ` · ${m.time}` : ""}`));
    } else if (m.state === "failed" && m.error) {
      body.push(h("p", {class: "asst-past failed"}, icon("error"), m.error));
    }
    return h("div", {class: "asst-msg ai"}, body);
  }

  /* ================================================================ the context chip ("About: screen “trial” ×") */
  function focusWords(f) {
    if (!f) return "";
    if (f.kind === "component") return `item ${q(f.id)} in ${q(f.routine)}`;
    if (f.kind === "routine") return `screen ${q(f.routine)}`;
    if (f.kind === "loop") return `trial list ${q(f.id)}`;
    if (f.kind === "device") return `device ${q(f.id)}`;
    if (f.kind === "settings") return "the experiment settings";
    return "";
  }
  function currentFocus() { return st.focusOff ? null : st.forcedFocus || safe(() => EDGE.focus(), null); }
  function renderContext() {
    if (!st.panelBuilt) return;
    const ctx = st.els.ctx;
    const key = JSON.stringify(safe(() => EDGE.focus(), null));
    if (key !== st.lastFocusKey) { st.focusOff = false; st.forcedFocus = null; st.lastFocusKey = key; }
    const f = currentFocus();
    if (!f || !focusWords(f) || !(st.view && st.view.configured)) { ctx.replaceChildren(); ctx.hidden = true; return; }
    const x = h("button", {type: "button", class: "x", "aria-label": `Don't send ${focusWords(f)} as context`, "data-tip": "Don't send this"}, icon("close"));
    x.addEventListener("click", () => { st.focusOff = true; renderContext(); if (st.els.input) st.els.input.focus(); });
    ctx.replaceChildren(h("span", {class: "ctx-chip"}, h("span", {class: "t-3"}, "About:"), h("span", {class: "what"}, focusWords(f)), x));
    ctx.hidden = false;
  }

  /* ================================================================ attachments */
  const BADGE = {csv: "CSV", tsv: "TSV", xlsx: "XLSX", json: "JSON", yaml: "YAML", yml: "YAML", html: "HTML", htm: "HTML", txt: "TXT", md: "MD"};
  const extOf = (name) => ((/\.([a-z0-9]+)$/i.exec(name || "") || [])[1] || "").toLowerCase();
  function badgeText(kind, name) {
    if (kind === "image") return "IMG";
    if (kind === "audio") return "AUDIO";
    return BADGE[extOf(name)] || (extOf(name) || "FILE").toUpperCase().slice(0, 5);
  }
  function badgeClass(kind, name) {
    const e = extOf(name);
    if (kind === "image") return "img";
    if (kind === "audio") return "audio";
    if (kind === "table" || ["csv", "tsv", "xlsx"].includes(e)) return "csv";
    if (["json", "yaml", "yml"].includes(e) || kind === "json") return "json";
    if (["html", "htm"].includes(e) || kind === "html") return "html";
    return "txt";
  }
  /* what EDGE understood, short: "9 rows × 4: word, ink, congruent, correct_key" */
  function shortPreview(p) {
    if (!p) return "";
    const k = p.kind;
    if (k === "table" && p.table) {
      const cols = (p.table.columns || []).map((c) => c.name);
      return `${p.table.rows} rows × ${cols.length}: ${cols.slice(0, 4).join(", ")}${cols.length > 4 ? ", …" : ""}`;
    }
    if (k === "image" && p.image) return p.image.width ? `${p.image.width} × ${p.image.height}` : "picture";
    if (k === "text" && p.text) return plural(p.text.lines, "line");
    if (k === "audio" && p.audio) return p.audio.seconds != null ? `${p.audio.seconds} s` : `${p.audio.format || ""} sound`;
    if (k === "html" && p.html) {
      const fields = (((p.html.forms || [])[0] || {}).fields || []).map((f) => f.name).filter(Boolean);
      return fields.length ? `form: ${fields.slice(0, 4).join(", ")}` : (p.html.title || "web page");
    }
    if (k === "json" && p.json) { const rc = (p.json.row_candidates || [])[0]; return rc ? `${rc.rows} rows` : "data"; }
    const s = String(p.summary || "");
    return s.includes(" — ") ? s.split(" — ").slice(1).join(" — ") : "";
  }
  const attList = (where) => (where === "home" ? st.home.atts : st.pending);
  const rerenderAtts = (where) => (where === "home" ? renderHomeAtts() : renderPending());

  async function suggestSlug(text) {
    try { return (await api(`/api/assistant/suggest_path?name=${enc(text || "experiment")}`)).path.split("/")[0]; }
    catch { return ui.slug(text) || "experiment"; }
  }
  async function ensureFolder(where, files) {
    if (where === "home") return homeReservePath(files);
    const path = docPath();
    if (path) return path;
    const stem = ((st.els.input && st.els.input.value) || "").trim().split(/\s+/).slice(0, 4).join(" ")
      || ((files[0] && files[0].name) || "").replace(/\.[^.]*$/, "");
    if (safe(() => EDGE.ws(), "") === "home") {          // nothing is open: reserve a folder for the new experiment
      if (!st.panelPath) { const slug = await suggestSlug(stem); st.panelPath = `${slug}/${slug}.yaml`; }
      return st.panelPath;
    }
    return EDGE.ensurePath({suggest: await suggestSlug(stem)});
  }
  async function attachFiles(files, where = "panel", existing = []) {
    if (!files.length && !existing.length) return;
    if (where === "panel" && st.job) { EDGE.toast("Wait for the assistant to finish, or press Stop."); return; }
    const exp = await ensureFolder(where, files);
    if (!exp) return;
    const list = attList(where);
    const work = [];
    const mk = (name, extra) => ({id: Math.random().toString(36).slice(2), name, kind: "", exp, state: "busy", preview: null, file: null, error: null, ...extra});
    for (const f of files) { const a = mk(f.name || "file", {}); list.push(a); work.push(uploadOne(a, f, where)); }
    for (const rel of existing) { const a = mk(String(rel).split("/").pop(), {file: rel, existing: true}); list.push(a); work.push(previewOne(a, where)); }
    rerenderAtts(where);
    await Promise.all(work);
    const ok = list.filter((a) => a.state === "ok").length;
    if (ok) EDGE.announce(`${plural(ok, "file")} attached.`);
    call("renderFiles");
  }
  async function uploadOne(a, f, where) {
    try {
      const r = await fetch(`/api/assistant/attach?exp=${enc(a.exp)}&name=${enc(a.name)}`,
        {method: "POST", headers: {"Content-Type": "application/octet-stream"}, body: f});
      let j;
      try { j = await r.json(); } catch { j = {error: r.statusText || "The builder did not answer"}; }
      if (!r.ok || j.error) throw Object.assign(new Error(j.error || r.statusText), {data: j});
      Object.assign(a, {preview: j.attachment, file: j.attachment.file, kind: j.attachment.kind, name: j.attachment.name,
        stored: j.stored || {}, state: "ok"});
    } catch (e) {
      const d = e.data || {};
      Object.assign(a, {state: "error", error: [d.error || e.message, d.hint].filter(Boolean).join(" ")});
    }
    rerenderAtts(where);
  }
  async function previewOne(a, where) {
    try {
      const j = await api(`/api/assistant/preview?exp=${enc(a.exp)}&file=${enc(a.file)}`);
      Object.assign(a, {preview: j.attachment, kind: j.attachment.kind, name: j.attachment.name, state: "ok"});
    } catch (e) { Object.assign(a, {state: "error", error: errText(e)}); }
    rerenderAtts(where);
  }
  function removeAtt(where, ids) {
    const list = attList(where);
    for (const id of ids) {
      const i = list.findIndex((a) => a.id === id);
      if (i < 0) continue;
      const [a] = list.splice(i, 1);
      if (a.state === "ok" && a.file && !a.existing && !(a.stored && a.stored.reused)) {
        api("/api/assistant/detach", {exp: a.exp, file: a.file}).then(() => call("renderFiles")).catch(() => { /* kept: harmless */ });
      }
    }
    if (where === "panel" && !st.pending.length) st.panelPath = null;
    rerenderAtts(where);
  }
  /* chips (several pictures collapse into one "faces · 12 pictures" chip) */
  function attChips(where) {
    const list = attList(where);
    const imgs = list.filter((a) => a.state === "ok" && a.kind === "image");
    const group = imgs.length >= 4;
    const out = [];
    if (group) {
      const names = imgs.map((a) => a.name.replace(/\.[^.]*$/, ""));
      let pre = names[0] || "";
      for (const n of names) while (pre && !n.startsWith(pre)) pre = pre.slice(0, -1);
      pre = pre.replace(/[-_ .\d]+$/, "");
      const label = pre.length >= 3 ? pre : "pictures";
      const x = h("button", {type: "button", class: "x", "aria-label": `Remove the ${imgs.length} pictures`, "data-tip": "Remove"}, icon("close"));
      x.addEventListener("click", () => removeAtt(where, imgs.map((a) => a.id)));
      const main = h("button", {type: "button", class: "att-main", "aria-label": `${label}: ${imgs.length} pictures. Show them`},
        h("span", {class: "ft img"}, "IMG"), h("span", {class: "nm"}, label), h("span", {class: "sz"}, `${imgs.length} pictures`), icon("success", "ok"));
      main.addEventListener("click", (e) => previewPopover(e.currentTarget, imgs));
      out.push(h("span", {class: "att", role: "listitem"}, main, x));
    }
    for (const a of list) {
      if (group && a.state === "ok" && a.kind === "image") continue;
      const x = h("button", {type: "button", class: "x", "aria-label": `Remove ${a.name}`, "data-tip": "Remove"}, icon("close"));
      x.addEventListener("click", () => removeAtt(where, [a.id]));
      if (a.state === "busy") {
        out.push(h("span", {class: "att busy", role: "listitem", "aria-busy": "true"}, h("span", {class: "spin", "aria-hidden": "true"}),
          h("span", {class: "nm"}, a.name), h("span", {class: "sz"}, "Copying…"), x));
      } else if (a.state === "error") {
        out.push(h("span", {class: "att err", role: "listitem", title: a.error},
          h("span", {class: "ft bad", "aria-hidden": "true"}, "!"), h("span", {class: "nm"}, a.name), h("span", {class: "sz why"}, a.error), x));
      } else {
        const p = a.preview || {};
        const warn = (p.warnings || []).length || (p.table && (p.table.needs_conversion || p.table.participant_data));
        const main = h("button", {type: "button", class: "att-main", title: p.summary || a.name, "aria-label": `${a.name}: ${shortPreview(p)}. Show what EDGE read`},
          h("span", {class: `ft ${badgeClass(a.kind, a.name)}`}, badgeText(a.kind, a.name)), h("span", {class: "nm"}, a.name),
          h("span", {class: "sz"}, shortPreview(p)), warn ? icon("warning", "warn") : icon("success", "ok"));
        main.addEventListener("click", (e) => previewPopover(e.currentTarget, [a]));
        out.push(h("span", {class: "att", role: "listitem"}, main, x));
      }
    }
    return out;
  }
  function renderPending() {
    if (!st.panelBuilt) return;
    const chips = attChips("panel");
    st.els.atts.replaceChildren(...chips);
    if (chips.length) st.els.atts.append(h("p", {class: "att-note"}, "Attached files are copied into this experiment's folder."));
    st.els.atts.hidden = !chips.length;
    updateSendState();
  }
  /* the chip's popover: a table's first 10 rows (and its sheets), a thumbnail grid, or the first 40 lines */
  function previewPopover(anchor, list) {
    const box = h("div", {class: "att-pop", role: "dialog", "aria-label": "What EDGE read"});
    const first = list[0] && list[0].preview;
    if (list.length > 1 || (first && first.kind === "image")) {
      box.append(h("p", {class: "t-small"}, h("b", {}, list.length > 1 ? `${list.length} pictures` : first.name),
        list.length === 1 && shortPreview(first) ? ` · ${shortPreview(first)}` : ""));
      const grid = h("div", {class: "thumbs"});
      for (const a of list.slice(0, 24)) {
        grid.append(h("figure", {}, h("img", {src: `/api/file?path=${enc(a.preview.path)}`, alt: a.name, loading: "lazy"}), h("figcaption", {}, a.name)));
      }
      box.append(grid);
      if (first && first.image && first.image.vision === "metadata_only") {
        box.append(h("p", {class: "t-caption"}, `The model gets only the name and size: ${first.image.vision_reason}.`));
      }
    } else if (first && first.kind === "table" && first.table) {
      const t = first.table;
      const cols = (t.columns || []).map((c) => c.name);
      box.append(h("p", {class: "t-small"}, h("b", {}, first.name), ` · ${t.rows} rows × ${cols.length} columns${t.sheet ? ` · sheet ${q(t.sheet)}` : ""}`));
      if ((t.sheets || []).length > 1) {
        box.append(h("p", {class: "t-caption"}, "Sheets: " + t.sheets.map((s) => `${s.name} (${s.rows} rows${s.active ? ", the one EDGE uses" : ""})`).join(" · ")));
      }
      box.append(h("div", {class: "tbl"}, h("table", {class: "grid"}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", {class: "mono"}, c)))),
        h("tbody", {}, (t.first_rows || []).slice(0, 10).map((r) => h("tr", {}, cols.map((c) => h("td", {}, r[c] == null ? "" : String(r[c])))))))));
      if (t.rows > 10) box.append(h("p", {class: "t-caption"}, `and ${plural(t.rows - 10, "more row")}`));
      for (const n of (t.notes || []).slice(0, 3)) box.append(h("p", {class: "t-caption"}, n));
      if (t.participant_data) box.append(h("p", {class: "t-caption warn"}, icon("warning"), "This looks like recorded participant data."));
    } else if (first) {
      box.append(h("p", {class: "t-small"}, h("b", {}, first.name), shortPreview(first) ? ` · ${shortPreview(first)}` : ""));
      const text = first.kind === "text" ? (first.text || {}).excerpt
        : first.kind === "json" ? (first.json || {}).excerpt || (first.json || {}).structure
          : first.kind === "html" ? (first.html || {}).text || (first.html || {}).excerpt || (first.html || {}).title : "";
      if (text) box.append(h("pre", {class: "mono"}, String(text).split("\n").slice(0, 40).join("\n")));
    }
    for (const w of ((first && first.warnings) || []).slice(0, 3)) box.append(h("p", {class: "t-caption warn"}, icon("warning"), w));
    const close = h("button", {type: "button", class: "btn sm"}, "Close");
    box.append(h("div", {class: "pop-foot"}, close));
    const pop = ui.popover(anchor, box, {placement: "top-start"});
    close.addEventListener("click", () => pop.close());
  }

  /* the participant-data guard (client side, online services only) */
  async function guardParticipantData(atts) {
    const p = providerOf();
    if (!p || isLocal(p)) return "send";
    const risky = atts.filter((a) => a.preview && a.preview.table && a.preview.table.participant_data);
    if (!risky.length) return "send";
    const names = risky.map((a) => q(a.name)).join(", ");
    const v = await ui.dialog({title: "Send participant data?", icon: "warning", size: "sm",
      body: h("div", {}, h("p", {}, `This looks like recorded participant data: ${names}. It would be sent to ${serviceName(p)}.`),
        h("p", {class: "t-small t-2"}, "Remove it unless you are allowed to share it with that service.")),
      buttons: [{label: "Send anyway", value: "send"}, {label: "Remove it", value: "remove", kind: "primary"}]});
    if (v === "send") return "send";
    if (v === "remove") return {remove: risky.map((a) => a.id)};
    return "cancel";
  }

  /* ================================================================ sending a request */
  async function submitPanel() {
    const input = st.els.input;
    const text = input.value.trim();
    if (!(st.view && st.view.configured)) { openSettings(); return; }
    if (st.job) return;
    if (!text) { input.focus(); return; }
    if (st.pending.some((a) => a.state === "busy")) { EDGE.toast("Wait until the files are copied."); return; }
    const atts = st.pending.filter((a) => a.state === "ok");
    if (!docPath() && safe(() => EDGE.ws(), "") === "home") {
      /* nothing is open: the panel builds a new experiment, like the Home card */
      const guard = await guardParticipantData(atts);
      if (guard === "cancel") return;
      if (guard.remove) { removeAtt("panel", guard.remove); EDGE.toast("Removed it. Press Send to ask without it."); return; }
      const name = st.panelPath ? st.panelPath.split("/")[0] : await suggestSlug(text.split(/\s+/).slice(0, 3).join(" "));
      if (g("confirmLeaveDirty") && !(await call("confirmLeaveDirty"))) return;
      try { await EDGE.newExperiment({name, template: "blank", save: false, go: "build"}); }
      catch (e) { EDGE.toast(`Couldn't start the experiment: ${errText(e)}`, {tone: "danger"}); return; }
      st.panelPath = null;
      input.value = ""; autosize(input);
      st.pending = []; renderPending();
      EDGE.companion.open("assistant");
      send(text, {atts, guarded: true});
      return;
    }
    send(text, {atts, focus: currentFocus(), fromPanel: true});
  }

  async function send(text, {atts = [], focus = null, fromPanel = false, guarded = false} = {}) {
    if (st.job) { EDGE.toast("The assistant is still working on your last request."); return null; }
    if (!(st.view && st.view.configured)) { openSettings(); return null; }
    if (!guarded) {
      const guard = await guardParticipantData(atts);
      if (guard === "cancel") return null;
      if (guard.remove) { removeAtt("panel", guard.remove); EDGE.toast("Removed it. Press Send to ask without it."); return null; }
    }
    const path = docPath();
    if (atts.length && !path) { EDGE.toast("Name the experiment first: attached files are kept in its folder."); return null; }
    const proposalActive = safe(() => EDGE.proposal.active(), false);
    const job = {id: null, status: "submitting", message: text, atts: atts.map((a) => ({...a})), focus, path,
      baseSnapshot: EDGE.snapshot(), basedOn: proposalActive && st.previewJob ? st.previewJob.id : null,
      events: [], steps: [], notes: [], since: 0, started: Date.now(), elapsed: 0, result: null, error: null,
      phase: null, node: null, msg: null};
    if (fromPanel) {
      st.els.input.value = ""; autosize(st.els.input);
      st.pending = st.pending.filter((a) => !atts.includes(a));
      renderPending();
    }
    const userMsg = {role: "user", text, time: nowClock(),
      atts: job.atts.map((a) => ({name: a.name, kind: a.kind, short: shortPreview(a.preview), summary: (a.preview && a.preview.summary) || ""}))};
    pushMsg(userMsg);
    job.id = "pending-" + Date.now();
    job.msg = {role: "assistant", text: "", time: nowClock(), live: true, jobId: job.id};
    st.jobs.set(job.id, job);
    pushMsg(job.msg);
    st.job = job;
    st.forcedFocus = null;
    renderHeadAndState();
    renderLog();
    const body = {experiment: EDGE.doc(), path: path || undefined, message: text,
      attachments: job.atts.map((a) => a.file).filter(Boolean), focus: focus || undefined, conversation_id: st.convId || undefined,
      recap: !st.convFromThisPage && st.msgs.length > 2 ? recap().slice(0, -1) : undefined,
      options: {reviewed_code: listPref("assistant.reviewed").slice(-500)}};
    let r;
    try {
      r = await api("/api/assistant/ask", body);
    } catch (e) {
      const d = e.data || {};
      if (e.status === 409 && d.code === "consent_required") {
        /* first request to an online service: the privacy note, then the same request again */
        st.job = null;
        st.jobs.delete(job.id);
        st.msgs = st.msgs.filter((m) => m !== userMsg && m !== job.msg);
        persist(); renderLog(); renderHeadAndState();
        if (await consentDialog(d.provider || providerOf(), (d.privacy || {}).cloud)) return send(text, {atts, focus, guarded: true});
        if (fromPanel) { st.els.input.value = text; autosize(st.els.input); st.pending.push(...atts); renderPending(); }
        return null;
      }
      job.status = "failed";
      job.error = {code: d.code || "request", message: d.error || e.message, hint: d.hint || ""};
      finishJob(job);
      if (d.code === "not_configured") openSettings();
      return job;
    }
    st.jobs.delete(job.id);
    job.id = r.job_id;
    job.msg.jobId = job.id;
    st.jobs.set(job.id, job);
    if (r.conversation_reset && st.convId) {
      st.msgs.splice(st.msgs.length - 2, 0, {role: "note", text: "The builder restarted, so this is a new conversation. The assistant got a summary of the earlier messages."});
    }
    st.convId = r.conversation_id; st.convFromThisPage = true;
    job.status = "running";
    persist();
    renderLog();
    startTick();
    poll(job);
    return job;
  }

  function startTick() {
    if (st.tick) return;
    st.tick = setInterval(() => {
      const job = st.job;
      if (!job) { clearInterval(st.tick); st.tick = null; return; }
      const el = job.node && job.node.querySelector(".asst-working .time");
      if (el) el.textContent = mmss((Date.now() - job.started) / 1000);
    }, 1000);
  }

  async function poll(job) {
    let fails = 0;
    while (job.status === "running" || job.status === "queued") {
      let j;
      try {
        j = await api(`/api/assistant/job?id=${enc(job.id)}&since=${job.since}&wait=10`);
        fails = 0;
      } catch (e) {
        if (job.status === "cancelled") return;
        if (e.status === 400) { job.status = "failed"; job.error = {code: "lost", message: "The builder lost this request (it was restarted).", hint: "Ask again."}; break; }
        if (++fails > 5) { job.status = "failed"; job.error = {code: "lost", message: "Can't reach the builder.", hint: "Check that EDGE is still running, then ask again."}; break; }
        await new Promise((res) => setTimeout(res, 1500));
        continue;
      }
      if (job.status === "cancelled") return;
      for (const ev of j.events || []) addEvent(job, ev);
      if (typeof j.next === "number") job.since = j.next;
      if (["done", "incomplete", "failed", "cancelled", "discarded", "applied"].includes(j.status)) {
        job.status = j.status === "discarded" || j.status === "applied" ? "done" : j.status;
        job.result = j.result;
        job.error = j.error;
        break;
      }
      refreshJob(job);
    }
    finishJob(job);
  }
  function addEvent(job, ev) {
    job.events.push(ev);
    if (ev.kind === "tool") {
      const key = ev.call || `${ev.tool}-${ev.seq}`;
      const i = job.steps.findIndex((s) => s.key === key);
      const step = {key, kind: "tool", text: ev.text, state: ev.state || (ev.ok === false ? "failed" : "done"), detail: ev.detail};
      if (i >= 0) job.steps[i] = step; else job.steps.push(step);
    } else if (ev.kind === "note") {
      if (ev.text) job.notes.push(ev.text);
    } else if (ev.kind === "status" || ev.kind === "warning" || ev.kind === "retry") {
      job.steps.push({key: "e" + ev.seq, kind: ev.kind, text: ev.text});
    }
  }

  async function stopJob() {
    const job = st.job;
    if (!job || !job.id || job.id.startsWith("pending-")) return;
    job.status = "cancelled";
    finishJob(job);
    try { await api("/api/assistant/cancel", {id: job.id}); } catch { /* it ends anyway */ }
  }

  /* the job ended: an answer, a preview, an automatic apply, a conflict or a failure */
  function finishJob(job) {
    if (job.finished) { refreshJob(job); return; }
    job.finished = true;
    job.elapsed = (Date.now() - job.started) / 1000;
    if (st.job === job) st.job = null;
    const res = job.result, msg = job.msg;
    if (job.status === "cancelled") {
      msg.state = "cancelled"; msg.text = "Stopped. Nothing was changed.";
    } else if (job.status === "failed" || !res) {
      job.status = "failed";
      msg.state = "failed";
      msg.error = (job.error && job.error.message) || "The assistant stopped with a problem.";
    } else {
      msg.text = (res.summary && res.summary.message) || job.notes.join("\n\n");
      if (res.changed) {
        rememberWritten(res.review);
        msg.n = (res.changes || []).length;
        decideApply(job);
      } else job.phase = "answer";
    }
    persist();
    renderHeadAndState();
    refreshJob(job);
    announceJob(job);
  }
  function announceJob(job) {
    const msg = job.msg, n = msg.n || 0;
    if (job.status === "cancelled") return;
    const what = job.phase === "answer" ? `The assistant answered: ${String(msg.text || "").slice(0, 300)}`
      : job.phase === "preview" ? `The assistant proposes ${plural(n, "change")}. Review them, then apply or discard.`
        : job.phase === "applied" ? `Applied ${plural(n, "change")}.`
          : job.phase === "conflict" ? "The assistant finished, but you changed the experiment meanwhile."
            : job.status === "failed" ? `The assistant stopped: ${msg.error}` : "";
    if (what) EDGE.announce(what);
    if (EDGE.companion.isOpen("assistant") || job.phase === "applied") return;
    const show = {label: "Show", run: () => open({})};
    if (job.phase === "preview" || job.phase === "conflict") EDGE.toast(`The assistant proposes ${plural(n, "change")}.`, {action: {label: "Review", run: () => open({})}});
    else if (job.phase === "answer") EDGE.toast("The assistant answered.", {action: show});
    else if (job.status === "failed") EDGE.toast("The assistant stopped with a problem.", {tone: "danger", action: show});
  }

  function shortTitle(res) {
    const t = String((res && res.summary && res.summary.title) || "").replace(/[.…]+$/, "");
    if (t && t.length <= 60) return t.charAt(0).toLowerCase() + t.slice(1);
    const c = String((((res && res.changes) || [])[0] || {}).text || "changes");
    const s = c.length > 60 ? c.slice(0, 57) + "…" : c;
    return s.charAt(0).toLowerCase() + s.slice(1);
  }
  function decideApply(job) {
    const res = job.result;
    if (job.path !== docPath()) {
      job.phase = "elsewhere";
      api("/api/assistant/discard", {id: job.id}).catch(() => {});
      return;
    }
    const basedOnGone = job.basedOn && !(st.previewJob && st.previewJob.id === job.basedOn && EDGE.proposal.active());
    const conflict = job.baseSnapshot !== EDGE.snapshot() || !!basedOnGone;
    const review = conflict || !!res.confirm || res.status === "incomplete";
    if (!review && prefs.get("assistant.autoApply", false)) {
      /* Preferences › "Apply its changes right away (you can always undo)" — assistant spec §11.3 */
      if (EDGE.proposal.active()) EDGE.proposal.discard();
      EDGE.replaceDoc(res.experiment, `Assistant: ${shortTitle(res)}`);
      job.appliedIndex = EDGE.historyIndex();
      markApplied(job, true);
      if (EDGE.isFresh()) EDGE.save();
      EDGE.toast(`Applied ${plural((res.changes || []).length, "change")}.`, {action: {label: "Undo", run: () => undoJob(job)}});
      return;
    }
    startPreview(job, conflict);
  }
  function startPreview(job, conflict = false) {
    const res = job.result;
    const chain = job.basedOn && st.previewJob && st.previewJob.id === job.basedOn ? [...(st.previewJob.chain || [st.previewJob.id])] : [];
    job.chain = [...chain, job.id];
    let base = {};
    try { base = JSON.parse(EDGE.snapshot()); } catch { base = {}; }
    for (const other of st.jobs.values()) if (other !== job && (other.phase === "preview" || other.phase === "conflict")) { other.phase = "replaced"; refreshJob(other); }
    st.previewJob = job;
    job.phase = conflict ? "conflict" : "preview";
    job.msg.state = "preview";
    EDGE.proposal.start({doc: res.experiment, marks: computeMarks(base, res.experiment), label: `Assistant: ${shortTitle(res)}`,
      summary: (res.summary && res.summary.title) || "", conflict, jobId: job.id});
  }
  /* EDGE.proposal ended: from the card, the proposal bar, Ctrl+Enter, Esc, an external change or a document switch */
  function onProposal(d) {
    const job = st.previewJob;
    if (!job || (d && d.active)) { renderHeadAndState(); return; }
    st.previewJob = null;
    if (d && d.applied) {
      job.appliedIndex = EDGE.historyIndex();
      markApplied(job, false);
      if (!EDGE.companion.isOpen("assistant")) {
        EDGE.toast(`Applied ${plural((job.result.changes || []).length, "change")}.`, {action: {label: "Undo", run: () => undoJob(job)}});
      }
    } else {
      job.phase = "discarded";
      job.msg.state = "discarded";
      if (!job.discardedServer) for (const id of job.chain || [job.id]) api("/api/assistant/discard", {id}).then(() => call("renderFiles")).catch(() => {});
      job.discardedServer = true;
    }
    persist();
    refreshJob(job);
    renderHeadAndState();
  }
  function markApplied(job, auto) {
    job.phase = "applied";
    job.appliedAt = nowClock();
    job.msg.state = "applied";
    job.msg.time = job.appliedAt;
    st.lastAppliedAt = Date.now();
    if (!job.discardedServer) for (const id of job.chain || [job.id]) api("/api/assistant/applied", {id}).catch(() => {});
    persist();
    refreshJob(job);
    if (!auto) EDGE.announce(`Applied ${plural((job.result.changes || []).length, "change")}.`);
  }
  function undoJob(job) {
    if (EDGE.undoIf(job.appliedIndex)) { setUndone(job, true); EDGE.announce("Undone."); }
    else EDGE.toast(`Use Undo in the toolbar (${KEY}+Z): the experiment changed since.`);
  }
  function setUndone(job, undone) {
    job.phase = undone ? "undone" : "applied";
    job.msg.state = job.phase;
    persist();
    refreshJob(job);
  }
  function onDocChanged(d) {
    const label = d && d.label;
    if (label !== "Undo" && label !== "Redo") return;
    const idx = EDGE.historyIndex();
    for (const job of st.jobs.values()) {
      if (job.phase === "applied" && label === "Undo" && idx === job.appliedIndex - 1) setUndone(job, true);
      else if (job.phase === "undone" && label === "Redo" && idx === job.appliedIndex) setUndone(job, false);
    }
  }

  /* ================================================================ the job card */
  function refreshJob(job) {
    if (!job.node || !job.node.isConnected) return;
    const n = jobNode(job);
    job.node.replaceWith(n);
    job.node = n;
    scrollLog();
  }
  function stepNode(s) {
    const ic = s.kind === "tool" ? (s.state === "running" ? h("span", {class: "spin", "aria-hidden": "true"}) : icon(s.state === "failed" ? "error" : "check"))
      : s.kind === "warning" ? icon("warning") : h("span", {class: "pip", "aria-hidden": "true"});
    return h("li", {class: `asst-step ${s.kind} ${s.state || ""}`, title: s.detail || null}, ic,
      h("span", {}, s.text, s.state === "failed" && s.detail ? h("span", {class: "sr-only"}, `: ${s.detail}`) : null));
  }
  function jobNode(job) {
    const res = job.result;
    const parts = [whoLine()];
    if (["running", "submitting", "queued"].includes(job.status)) {
      for (const t of job.notes) parts.push(mdNodes(t));
      const steps = h("ul", {class: "asst-steps", id: "assistant-steps", "aria-label": "What the assistant is doing"}, job.steps.map(stepNode));
      if (!job.steps.length) steps.append(stepNode({kind: "status", text: job.status === "submitting" ? "Sending your request…" : "Starting…"}));
      parts.push(steps);
      const stop = btn("Stop", () => stopJob(), {ic: "stop", id: "assistant-stop"});
      if (!job.id || job.id.startsWith("pending-")) stop.disabled = true;
      parts.push(h("div", {class: "asst-working"}, h("span", {class: "spin", "aria-hidden": "true"}),
        h("span", {}, "Working · ", h("span", {class: "time"}, mmss((Date.now() - job.started) / 1000))), h("span", {class: "grow"}), stop));
      return h("div", {class: "asst-msg ai job running", "aria-busy": "true"}, parts);
    }
    if (job.status === "cancelled") {
      parts.push(h("p", {class: "asst-note"}, "Stopped. Nothing was changed."));
      return h("div", {class: "asst-msg ai job"}, parts);
    }
    if (job.status === "failed" || !res) {
      parts.push(failedCard(job));
      return h("div", {class: "asst-msg ai job"}, parts);
    }
    const text = (res.summary && res.summary.message) || job.notes.join("\n\n");
    if (text) parts.push(mdNodes(text));
    if (res.changed) parts.push(resultCard(job));
    if (job.steps.length) {
      const tools = job.steps.filter((s) => s.kind === "tool").length;
      parts.push(h("details", {class: "asst-details"}, h("summary", {}, `What it did: ${plural(tools || job.steps.length, "step")} · ${mmss(job.elapsed || 0)}`),
        h("ul", {class: "asst-steps"}, job.steps.map(stepNode))));
    }
    if (res.usage && res.usage.suggest_new_conversation) {
      const b = h("button", {type: "button", class: "linkbtn"}, "Start a new conversation");
      b.addEventListener("click", () => newConversation());
      parts.push(h("p", {class: "asst-note"}, "This conversation is getting long. ", b, " to keep answers fast."));
    }
    return h("div", {class: `asst-msg ai job ${job.phase || ""}`}, parts);
  }

  const GLYPH = {added: ["add", "+", "New"], changed: ["mod", "~", "Changed"], renamed: ["mod", "~", "Renamed"], removed: ["del", "−", "Removed"]};
  function revealable(c) {
    if (c.action === "removed") return false;
    if (c.kind === "routine") return !!(c.routine && safe(() => EDGE.doc().routines[c.routine], null));
    if (["loop", "workflow", "device"].includes(c.kind)) return !!c.id;
    return ["settings", "measures"].includes(c.kind);
  }
  function changeRow(c, live) {
    const [cls, glyph, word] = GLYPH[c.action] || GLYPH.changed;
    const text = String(c.text || "");
    const m = /^(.*?):\s(.+)$/.exec(text);
    const inner = [h("span", {class: `g ${cls}`, "aria-hidden": "true"}, glyph),
      h("span", {class: "tx"}, h("span", {class: "sr-only"}, `${word}: `), m ? m[1] : text, m ? h("small", {}, m[2]) : null)];
    if (live && revealable(c)) {
      const b = h("button", {type: "button", class: "chg", "data-tip": "Show it", "data-tip-pos": "start"}, inner);
      b.addEventListener("click", () => { try { EDGE.reveal(c); } catch (e) { console.error(e); } });
      return h("li", {}, b);
    }
    return h("li", {}, h("div", {class: "chg static"}, inner));
  }
  function checkLines(job) {
    const res = job.result;
    const out = [];
    const issues = (res.issues || []).filter((i) => i.level === "error" || i.level === "warning");
    const errors = issues.filter((i) => i.level === "error");
    if (!issues.length) out.push(h("li", {class: "ok"}, icon("success"), "Checked: no problems"));
    else {
      const li = h("li", {class: errors.length ? "bad" : "warn"}, icon(errors.length ? "error" : "warning"),
        h("span", {}, errors.length ? `${plural(errors.length, "problem")}: ${errors[0].message}` : `${plural(issues.length, "thing")} to check: ${issues[0].message}`));
      if (errors.length && !["discarded", "replaced", "elsewhere"].includes(job.phase)) {
        const fix = h("button", {type: "button", class: "linkbtn"}, "Ask to fix it");
        fix.addEventListener("click", () => {
          const input = st.els.input;
          input.value = `Fix this problem: ${errors[0].message}`; autosize(input); updateSendState(); input.focus();
        });
        li.append(" ", fix);
      }
      out.push(li);
    }
    const dr = res.dry_run;
    if (dr && dr.ran) {
      const ok = dr.ok !== false && /^OK/i.test(String((dr.verdict || [])[0] || "OK"));
      out.push(h("li", {class: ok ? "ok" : "warn"}, icon(ok ? "success" : "warning"),
        ok ? `Test run: ${plural(dr.trials || 0, "trial")}, OK` : `Test run: ${(dr.verdict || ["it found problems"])[0]}`));
    } else if ((dr && dr.skipped) || (res.review || []).some((r) => r.kind === "code")) {
      out.push(h("li", {class: "warn"}, icon("warning"), "Not test-run: it contains code you need to read first"));
    }
    if (res.estimate && res.estimate.text) out.push(h("li", {class: "muted"}, icon("clock"), String(res.estimate.text).replace(/^./, (ch) => ch.toUpperCase())));
    return h("ul", {class: "check"}, out);
  }
  function reviewChips(job) {
    const res = job.result;
    const reviewed = new Set(listPref("assistant.reviewed"));
    const out = [];
    for (const r of res.review || []) {
      const done = r.kind === "code" && reviewed.has(r.hash);
      const row = h("div", {class: `assistant-review${done ? " done" : ""}`}, icon(done ? "success" : r.kind === "code" ? "code" : "warning"),
        h("span", {class: "tx"}, done ? `You read the code in ${q(r.routine)} › ${r.id}.` : r.text));
      const acts = h("span", {class: "acts"});
      if (!done && (r.routine || r.id) && !["discarded", "replaced", "elsewhere"].includes(job.phase)) {
        acts.append(btn("Show me", () => {
          if (r.kind === "device" || r.kind === "network") EDGE.reveal({kind: "device", id: r.id});
          else if (r.routine) EDGE.select({kind: "component", routine: r.routine, id: r.id}, {pulse: true});
        }, {kind: "ghost"}));
      }
      if (!done && r.kind === "code" && job.phase === "applied") {
        acts.append(btn("I've read it", () => { if (markReviewed(r.routine, r.id)) EDGE.toast(`Marked the code in ${q(r.routine)} › ${r.id} as read.`); }, {}));
      }
      if (acts.childElementCount) row.append(acts);
      out.push(row);
    }
    return out;
  }
  function resultCard(job) {
    const res = job.result;
    const live = ["preview", "conflict", "applied", "undone"].includes(job.phase) && job.path === docPath();
    const n = (res.changes || []).length;
    const name = (job.path || "").split("/").pop().replace(/\.(ya?ml|json)$/i, "") || "the experiment";
    const card = h("section", {class: `changes assistant-result ${job.phase || ""}`, "aria-label": `Proposed changes: ${plural(n, "change")}`});
    let diffHost = null, yamlBtn = null;
    if (isExpert() && !["discarded", "replaced", "elsewhere"].includes(job.phase)) {
      yamlBtn = h("button", {type: "button", class: "btn sm ghost", "aria-expanded": "false"}, icon("code"), "YAML");
      diffHost = h("div", {class: "yaml-diff", hidden: true});
      yamlBtn.addEventListener("click", () => toggleDiff(job, yamlBtn, diffHost));
    }
    const list = h("ul", {class: "chg-list"}, (res.changes || []).map((c) => changeRow(c, live)));
    if (job.phase === "applied" || job.phase === "undone") {
      const undone = job.phase === "undone";
      card.append(h("div", {class: `applied-line${undone ? " undone" : ""}`}, icon(undone ? "undo" : "success", "m"),
        h("b", {}, undone ? `Undid ${plural(n, "change")}` : `Applied ${plural(n, "change")}`), h("span", {class: "t-3"}, job.appliedAt ? ` · ${job.appliedAt}` : "")));
      if (!undone) {
        const acts = h("div", {class: "acts"}, btn("Undo", () => undoJob(job), {ic: "undo", kind: "assistant-undo"}));
        if (g("tryNow") || g("tryIt")) acts.append(btn("Try it", () => (g("tryNow") ? call("tryNow", "all") : call("tryIt", "all")), {ic: "play"}));
        if (g("dryRun")) acts.append(btn("Start test run", () => call("dryRun"), {ic: "test"}));
        card.append(acts);
      }
      card.append(...reviewChips(job));
      const det = h("details", {class: "chg-more"}, h("summary", {}, `What changed (${n})`), list, checkLines(job));
      if (yamlBtn) det.append(h("div", {class: "more-acts"}, yamlBtn), diffHost);
      card.append(det);
      if (isExpert() && res.usage) card.append(usageLine(res.usage));
      return card;
    }
    const header = h("header", {}, icon("assistant"), h("b", {}, `${plural(n, "change")} to ${name}`));
    if (yamlBtn) header.append(yamlBtn);
    card.append(header, list, checkLines(job), ...reviewChips(job));
    if (diffHost) card.append(diffHost);
    const notes = [];
    const alert = (title, text) => h("div", {class: "alert warning slim"}, icon("warning"), h("div", {}, h("b", {}, title), text ? h("p", {}, text) : null));
    if (job.phase === "conflict") notes.push(alert("You changed the experiment while the assistant worked.", "Applying replaces your changes since then."));
    if (!["discarded", "replaced", "elsewhere"].includes(job.phase)) {
      if (res.confirm) notes.push(alert(res.confirm.text || "This replaces most of your experiment.", "Check the preview before you apply it."));
      if (res.status === "incomplete") notes.push(alert("The assistant ran out of steps.", "This is what it did so far."));
      if ((res.files_created || []).length) notes.push(h("p", {class: "files-note"}, `Discard removes the ${plural(res.files_created.length, "file")} it made. Your attached files stay.`));
    }
    card.append(...notes);
    const foot = h("footer", {});
    if (job.phase === "preview" && live) {
      foot.append(btn("Apply", () => applyFromCard(job), {kind: "primary", ic: "check", tip: `${KEY}+Enter`}),
        btn("Discard", () => EDGE.proposal.discard()), h("span", {class: "grow"}),
        btn("Change something…", () => { st.els.input.focus(); }, {kind: "ghost"}));
    } else if (job.phase === "conflict" && live) {
      foot.append(btn("Ask again with my changes", () => askAgain(job), {kind: "primary", ic: "refresh"}),
        btn("Apply anyway", () => applyFromCard(job)), btn("Discard", () => EDGE.proposal.discard(), {kind: "ghost"}));
    } else if (job.phase === "discarded") {
      foot.append(h("span", {class: "state"}, icon("close"), "Discarded"));
      if (!(res.files_created || []).length && res.experiment && job.path === docPath() && !st.job) foot.append(btn("Show again", () => showAgain(job), {kind: "ghost"}));
    } else if (job.phase === "replaced") {
      foot.append(h("span", {class: "state"}, "Replaced by the newer proposal below"));
    } else if (job.phase === "elsewhere") {
      foot.append(h("span", {class: "state"}, "This answer was for another experiment. Open it and ask again."));
    }
    if (foot.childElementCount) card.append(foot);
    if (isExpert() && res.usage) card.append(usageLine(res.usage));
    return card;
  }
  function usageLine(u) {
    const fmt = (x) => Number(x || 0).toLocaleString("en").replace(/,/g, " ");
    return h("p", {class: "usage mono"}, `${u.model || ""} · ${plural(u.turns || 0, "turn")} · ${fmt(u.input_tokens)} in · ${fmt(u.output_tokens)} out`
      + (u.cache_read_input_tokens ? ` · ${fmt(u.cache_read_input_tokens)} from cache` : ""));
  }
  function applyFromCard(job) { if (st.previewJob === job && EDGE.proposal.active()) EDGE.proposal.apply(); }
  function showAgain(job) {
    if (EDGE.proposal.active()) EDGE.proposal.discard();
    job.discardedServer = true;
    job.basedOn = null;
    startPreview(job, job.baseSnapshot !== EDGE.snapshot());
    refreshJob(job);
  }
  function askAgain(job) {
    if (st.previewJob === job && EDGE.proposal.active()) EDGE.proposal.discard();
    send(job.message, {atts: job.atts, focus: job.focus, guarded: true});
  }
  async function toggleDiff(job, button, host) {
    const show = host.hidden;
    host.hidden = !show;
    button.setAttribute("aria-expanded", show ? "true" : "false");
    if (!show || host.childElementCount) return;
    host.append(h("p", {class: "t-caption"}, "Working out the differences…"));
    try {
      let base = {};
      try { base = JSON.parse(job.baseSnapshot); } catch { base = {}; }
      const [a, b] = await Promise.all([api("/api/to_yaml", base), api("/api/to_yaml", job.result.experiment)]);
      host.replaceChildren(diffView(a.yaml, b.yaml));
    } catch (e) { host.replaceChildren(h("p", {class: "t-caption"}, `Couldn't show the YAML: ${errText(e)}`)); }
  }
  /* a line diff (LCS) with 2 lines of context */
  function diffView(oldText, newText) {
    const A = String(oldText).split("\n"), B = String(newText).split("\n");
    const n = A.length, m = B.length;
    if (n * m > 4e6) return h("p", {class: "t-caption"}, "The experiment is too long to compare here.");
    const L = Array.from({length: n + 1}, () => new Uint32Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    const ops = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (A[i] === B[j]) { ops.push([" ", A[i]]); i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) ops.push(["-", A[i++]]); else ops.push(["+", B[j++]]);
    }
    while (i < n) ops.push(["-", A[i++]]);
    while (j < m) ops.push(["+", B[j++]]);
    if (!ops.some((o) => o[0] !== " ")) return h("p", {class: "t-caption"}, "The YAML is the same.");
    const keep = ops.map((o, k) => o[0] !== " " || ops.slice(Math.max(0, k - 2), k + 3).some((x) => x[0] !== " "));
    const pre = h("pre", {class: "mono diff", tabindex: "0", "aria-label": "Differences in the YAML"});
    let gap = false;
    ops.forEach((o, k) => {
      if (!keep[k]) { if (!gap) { pre.append(h("span", {class: "gap"}, "…\n")); gap = true; } return; }
      gap = false;
      pre.append(h("span", {class: o[0] === "+" ? "add" : o[0] === "-" ? "del" : ""}, `${o[0]} ${o[1]}\n`));
    });
    return pre;
  }

  function failedCard(job) {
    const e = job.error || {};
    const code = e.code || "";
    const p = providerOf();
    const acts = h("div", {class: "actions"});
    if (!["not_configured", "bad_key", "billing", "forbidden", "refused", "consent_required", "invalid_setting"].includes(code)) {
      acts.append(btn("Try again", () => send(job.message, {atts: job.atts, focus: job.focus, guarded: true}), {ic: "refresh"}));
    }
    if (["not_configured", "bad_key", "forbidden", "billing", "model_not_found", "model_not_pulled", "no_model_loaded", "server_not_running",
      "tools_unsupported", "context_too_long", "timeout", "connection_failed", "tls_failed"].includes(code)) {
      acts.append(btn("Assistant settings", () => openSettings(), {ic: "settings"}));
    }
    if (code === "context_too_long") acts.append(btn("New conversation", () => newConversation()));
    if (code === "server_not_running" && g("openHelp")) acts.append(btn(p === "lmstudio" ? "How to start LM Studio" : "How to start Ollama", () => call("openHelp", "ASSISTANT"), {kind: "ghost"}));
    return h("div", {class: "alert danger asst-failed", role: "alert"}, icon("error"),
      h("div", {}, h("b", {}, e.message || "The assistant stopped with a problem."), e.hint ? hintNodes(e.hint) : null,
        acts.childElementCount ? acts : null));
  }

  /* ================================================================ entry points: open / ask / fixIssue */
  function open({text = "", focus = null, send: doSend = false, files = null} = {}) {
    if (!panelEl()) return;
    if (!st.panelBuilt) init();
    if (focus) { st.forcedFocus = focus; st.focusOff = false; }
    EDGE.companion.open("assistant");
    renderContext();
    const input = st.els.input;
    if (text) { input.value = text; autosize(input); updateSendState(); }
    if (files && files.length) {
      attachFiles(files.filter((f) => typeof Blob !== "undefined" && f instanceof Blob), "panel", files.filter((f) => typeof f === "string"));
    }
    if (doSend && text) {
      if (!(st.view && st.view.configured)) { openSettings(); return; }
      if (!st.job) { submitPanel(); return; }
    }
    setTimeout(() => { if (!input.disabled) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); } }, 0);
  }
  function focusFromWhere(where) {
    const w = String(where || "");
    let m = /^routines\.([^.[\]]+)\.([^.[\]]+)/.exec(w);
    if (m) return {kind: "component", routine: m[1], id: m[2]};
    m = /^routines\.([^.[\]]+)/.exec(w);
    if (m) return {kind: "routine", routine: m[1]};
    m = /^devices\[(\d+)\]/.exec(w);
    if (m) { const d = safe(() => EDGE.doc().devices[+m[1]], null); return d ? {kind: "device", id: d.id} : null; }
    if (w.startsWith("settings")) return {kind: "settings"};
    return null;
  }
  function fixIssue(issue) {
    const f = focusFromWhere(issue && issue.where);
    if (f && f.kind === "component" && safe(() => EDGE.doc().routines[f.routine], null)) {
      safe(() => EDGE.select({kind: "component", routine: f.routine, id: f.id}, {reveal: false}));
    }
    open({text: "Fix: " + ((issue && issue.message) || ""), focus: f, send: false});
  }

  /* ================================================================ the Home "Describe it" card (W1, W2) */
  function mountComposer(el, {compact = false} = {}) {
    if (!el) return;
    const H = st.home;
    H.el = el;
    H.compact = !!compact;
    if (!H.text && !H.atts.length) H.expanded = false;
    H.placeholder = (H.placeholder + 1) % HOME_EXAMPLES.length;
    renderHome();
  }
  function renderHome() {
    const H = st.home, el = H.el;
    if (!el || !el.isConnected) return;
    const active = document.activeElement;
    const hadFocus = active && el.contains(active) ? active.dataset.k : null;
    const caret = hadFocus === "text" || hadFocus === "name" ? [active.selectionStart, active.selectionEnd] : null;
    const full = !H.compact || H.expanded || !!H.text || H.atts.length > 0;
    const configured = !!(st.view && st.view.configured);
    const ta = h("textarea", {class: "describe-input", "data-k": "text", rows: full ? "4" : "1", id: "home-describe-input",
      "aria-label": "Describe your experiment", "aria-describedby": "describe-hint",
      placeholder: full ? `Describe your experiment: what participants see, how they respond, how many trials…\n${HOME_EXAMPLES[H.placeholder]}` : "Describe a new experiment…"});
    ta.value = H.text;
    ta.addEventListener("input", () => { H.text = ta.value; onHomeText(); if (!full) { H.expanded = true; renderHome(); } });
    ta.addEventListener("focus", () => { if (!full) { H.expanded = true; renderHome(); } });
    ta.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); buildIt(); }
      if (e.key === "Escape" && H.compact && !H.text && !H.atts.length) { H.expanded = false; renderHome(); }
    });
    ta.addEventListener("paste", (e) => onPaste(e, (files) => attachFiles(files, "home")));
    const build = h("button", {type: "button", class: "btn assistant", "data-k": "build", "data-tip": configured ? `${KEY}+Enter` : null},
      icon(configured ? "assistant" : "settings"), configured ? "Build it" : "Set up the assistant");
    build.addEventListener("click", () => (configured ? buildIt() : openSettings()));
    if (!full) {
      el.replaceChildren(h("section", {class: "describe compact card", "aria-label": "Describe a new experiment"},
        h("span", {class: "lead-ic", "aria-hidden": "true"}, icon("assistant")), ta, build));
      restoreFocus(el, hadFocus, caret);
      return;
    }
    const fileIn = h("input", {type: "file", multiple: true, accept: ACCEPT, hidden: true, tabindex: "-1", "aria-hidden": "true"});
    fileIn.addEventListener("change", () => { const f = [...fileIn.files]; fileIn.value = ""; attachFiles(f, "home"); });
    const attach = h("button", {type: "button", class: "btn sm ghost", "data-k": "attach"}, icon("attach"), "Attach files");
    attach.addEventListener("click", () => fileIn.click());
    const atts = h("div", {class: "atts home-atts", role: "list", "aria-label": "Attached files", hidden: true});
    const box = h("div", {class: "describe-box"}, ta, atts,
      h("div", {class: "describe-tools"}, attach, h("span", {class: "t-caption", id: "describe-hint"}, `${ACCEPT_WORDS} · ${KEY}+Enter builds`)));
    const nameIn = h("input", {class: "input", id: "home-describe-name", "data-k": "name", spellcheck: "false", autocomplete: "off",
      placeholder: "my_experiment", "aria-describedby": "home-describe-where"});
    nameIn.value = H.name;
    if (H.path) nameIn.readOnly = true;
    const where = h("span", {class: "t-caption where", id: "home-describe-where"});
    const updateWhere = () => {
      const root = String(call("shortRoot") || "").replace(/\/$/, "");
      where.textContent = H.path ? "Your files are in this folder. Remove them to change the name."
        : `saved in ${root ? root + "/" : ""}${ui.slug(H.name) || "…"}/`;
    };
    nameIn.addEventListener("input", () => { H.name = nameIn.value; H.nameEdited = true; updateWhere(); });
    updateWhere();
    const nameRow = h("div", {class: "describe-name"}, h("label", {for: "home-describe-name"}, "Name"), nameIn, where);
    const actions = h("div", {class: "describe-actions"}, providerChip(() => openSettings(), {lg: true}), h("span", {class: "grow"}), build);
    const wiz = h("button", {type: "button", class: "linkbtn"}, "Answer a few questions");
    wiz.addEventListener("click", () => (g("startWizard") ? call("startWizard") : call("openWizard")));
    const notSet = configured ? null : h("p", {class: "t-small t-2 describe-nomodel"}, "No model? ", wiz, " builds the same kind of experiment without one.");
    const tries = h("div", {class: "describe-try"}, h("span", {class: "t-caption"}, "Try:"), HOME_TRY.map(([label, text]) => {
      const b = h("button", {type: "button", class: "try-chip"}, label);
      b.addEventListener("click", () => { H.text = text; H.expanded = true; onHomeText(); renderHome(); const t = el.querySelector("textarea"); if (t) t.focus(); });
      return b;
    }));
    const err = h("p", {class: "describe-err", role: "alert", hidden: true});
    const card = h("section", {class: "describe card", "aria-labelledby": "describe-title"},
      h("div", {class: "describe-head"}, h("span", {class: "chip assistant lg", id: "describe-title"}, icon("assistant"), "Describe it"),
        h("span", {class: "t-small t-2"}, "The assistant builds a first version you can check and change.")),
      box, nameRow, actions, notSet, err, tries, fileIn);
    wireDrop(card, (on) => card.classList.toggle("drop", on), (files) => attachFiles(files, "home"));
    card.addEventListener("focusout", () => setTimeout(() => {
      if (H.compact && H.expanded && !H.text && !H.atts.length && card.isConnected && !card.contains(document.activeElement)
        && !document.querySelector(".scrim")) { H.expanded = false; renderHome(); }
    }, 200));
    el.replaceChildren(card);
    renderHomeAtts();
    autosizeHome(ta);
    restoreFocus(el, hadFocus, caret);
  }
  function autosizeHome(ta) { ta.style.height = "auto"; ta.style.height = Math.min(260, Math.max(96, ta.scrollHeight + 2)) + "px"; }
  function restoreFocus(el, k, caret) {
    if (!k) return;
    const t = el.querySelector(`[data-k="${k}"]`);
    if (!t) return;
    t.focus();
    if (caret && t.setSelectionRange) { try { t.setSelectionRange(caret[0], caret[1]); } catch { /* not a text field */ } }
  }
  function renderHomeAtts() {
    const H = st.home;
    if (!H.el) return;
    const host = H.el.querySelector(".home-atts");
    if (!host) { if (H.atts.length) { H.expanded = true; renderHome(); } return; }
    if (!H.atts.length && H.path) { H.path = null; renderHome(); return; }
    const chips = attChips("home");
    host.replaceChildren(...chips);
    host.hidden = !chips.length;
    const nameIn = H.el.querySelector("#home-describe-name");
    if (nameIn) { nameIn.readOnly = !!H.path; if (H.path) nameIn.value = H.name; }
    const where = H.el.querySelector("#home-describe-where");
    if (where && H.path) where.textContent = "Your files are in this folder. Remove them to change the name.";
  }
  function onHomeText() {
    const H = st.home;
    const ta = H.el && H.el.querySelector("textarea");
    if (ta) autosizeHome(ta);
    if (H.nameEdited || H.path) return;
    clearTimeout(H.nameTimer);
    H.nameTimer = setTimeout(async () => {
      const words = H.text.replace(/[“”"']/g, " ").split(/[\s:;,.!?()]+/).filter(Boolean).slice(0, 3).join(" ");
      const name = words ? await suggestSlug(words) : "";
      if (H.nameEdited || H.path) return;
      H.name = name;
      const inp = H.el && H.el.querySelector("#home-describe-name");
      if (inp) { inp.value = name; const where = H.el.querySelector("#home-describe-where"); const root = String(call("shortRoot") || "").replace(/\/$/, "");
        if (where) where.textContent = `saved in ${root ? root + "/" : ""}${ui.slug(name) || "…"}/`; }
    }, 450);
  }
  /* the first attached file reserves the folder <name>/ (no YAML file exists until Build it) */
  async function homeReservePath(files) {
    const H = st.home;
    if (H.path) return H.path;
    let slug = ui.slug(H.name);
    if (!slug) {
      const stem = H.text.trim().split(/\s+/).slice(0, 3).join(" ") || ((files[0] && files[0].name) || "experiment").replace(/\.[^.]*$/, "");
      slug = await suggestSlug(stem);
    } else {
      try {
        const files2 = (await api("/api/files")).files || [];
        const known = new Set(files2.map((f) => (typeof f === "string" ? f : f.path)));
        if (known.has(`${slug}/${slug}.yaml`)) slug = await suggestSlug(slug);
      } catch { /* keep it */ }
    }
    H.name = slug; H.nameEdited = true;
    H.path = `${slug}/${slug}.yaml`;
    return H.path;
  }
  async function buildIt() {
    const H = st.home;
    const err = H.el && H.el.querySelector(".describe-err");
    const showErr = (t) => { if (err) { err.hidden = !t; err.replaceChildren(...(t ? [icon("error"), t] : [])); } };
    if (!(st.view && st.view.configured)) { openSettings(); return; }
    const text = H.text.trim();
    if (!text) { showErr("Describe the experiment first."); const t = H.el && H.el.querySelector("textarea"); if (t) t.focus(); return; }
    if (H.atts.some((a) => a.state === "busy")) { showErr("Wait until the files are copied."); return; }
    showErr("");
    const atts = H.atts.filter((a) => a.state === "ok");
    const guard = await guardParticipantData(atts);
    if (guard === "cancel") return;
    if (guard.remove) { removeAtt("home", guard.remove); EDGE.toast("Removed it. Press Build it to continue without it."); return; }
    if (g("confirmLeaveDirty") && !(await call("confirmLeaveDirty"))) return;
    const name = H.path ? H.path.split("/")[0] : (ui.slug(H.name) || await suggestSlug(text.split(/\s+/).slice(0, 3).join(" ")));
    let path;
    try { path = await EDGE.newExperiment({name, template: "blank", save: false, go: "build"}); }
    catch (e) { showErr(`Couldn't start the experiment: ${errText(e)}`); return; }
    const reserved = H.path;
    Object.assign(H, {text: "", atts: [], path: null, name: "", nameEdited: false, expanded: false});
    if (reserved && path !== reserved) EDGE.toast(`The name was taken, so the experiment is ${path}. Attach the files again if the assistant can't find them.`);
    open({});
    await send(text, {atts, guarded: true});
  }

  /* ================================================================ Assistant settings (W17) */
  async function openSettings(provider = null) {
    await refreshStatus();
    const v = st.view || {};
    if (st.unavailable) { EDGE.toast("The assistant isn't available in this version of EDGE."); return false; }
    const S2 = {provider: provider && PROVIDERS.includes(provider) ? provider : providerOf(v) || "anthropic", fields: {},
      options: {...(v.options || {})}, keyMode: {}, models: {}, modelErr: {}, other: {}, loading: null};
    for (const p of PROVIDERS) {
      const r = prow(p, v);
      S2.fields[p] = {base_url: r.base_url || DEFAULT_URL[p], model: r.model || "", effort: r.effort || "high", preset: r.preset || "openai",
        num_ctx: r.num_ctx || 16384, tool_mode: r.tool_mode || "auto", api_key: ""};
      S2.keyMode[p] = r.has_key && r.key_source === "config" ? "stored" : "new";
    }
    const errors = {};
    const body = h("div", {class: "asst-settings"});
    const fieldsHost = h("div", {class: "prov-fields"});
    const result = h("div", {class: "test-result", "aria-live": "polite"});
    const cards = PROVIDERS.map((p) => {
      const b = h("button", {type: "button", class: "prov-card", role: "radio", id: `assistant-provider-${p}`, "data-provider": p,
        "aria-checked": p === S2.provider ? "true" : "false", tabindex: p === S2.provider ? "0" : "-1"},
      h("span", {class: "pc-head"}, h("span", {class: "radio", "aria-hidden": "true"}), h("b", {}, INFO[p].title)),
      h("span", {class: "pc-text"}, INFO[p].text),
      h("span", {class: `pc-kind ${INFO[p].cloud ? "cloud" : "local"}`}, icon(INFO[p].icon), INFO[p].cloud ? "Online" : "On this computer"));
      b.addEventListener("click", () => choose(p));
      return b;
    });
    const group = h("div", {class: "prov-cards", role: "radiogroup", "aria-labelledby": "asst-where"}, cards);
    group.addEventListener("keydown", (e) => {
      const i = PROVIDERS.indexOf(S2.provider);
      let j = null;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") j = (i + 1) % PROVIDERS.length;
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") j = (i + PROVIDERS.length - 1) % PROVIDERS.length;
      if (j !== null) { e.preventDefault(); choose(PROVIDERS[j]); cards[j].focus(); }
    });
    function choose(p) {
      S2.provider = p;
      cards.forEach((c) => { const on = c.dataset.provider === p; c.setAttribute("aria-checked", on ? "true" : "false"); c.tabIndex = on ? 0 : -1; });
      result.replaceChildren();
      renderFields();
      if (!INFO[p].cloud && !S2.models[p]) loadModels(p);
    }
    const opt = (k, label, caption) => ui.switch(S2.options[k] !== false, (val) => { S2.options[k] = val; }, {label, caption});
    const switches = h("div", {class: "asst-switches"},
      opt("auto_dry_run", "Test-run every change with a virtual participant", "You see at once whether the result runs."),
      opt("send_images", "Let the assistant see the pictures I attach", "The model must support pictures."),
      opt("keep_history", "Keep a history of applied changes next to the experiment", "In .edge/assistant, in the experiment's folder."));
    if ((v.config_warnings || []).some((w) => w !== "api_key_cleared")) {
      body.append(h("div", {class: "alert warning slim"}, icon("warning"), h("div", {}, h("p", {}, "The settings file had a problem, so EDGE started from the defaults."))));
    }
    body.append(h("h3", {class: "t-title-s", id: "asst-where"}, "Where should the assistant run?"), group, fieldsHost, h("hr"), switches, result);

    function fieldRow(label, control, {help = null, id = null, err = null, suffix = null} = {}) {
      const errEl = h("div", {class: "err", role: "alert", hidden: true});
      if (err) errors[err] = {el: errEl, input: control.matches && control.matches("input,select") ? control : control.querySelector && control.querySelector("input,select")};
      return h("div", {class: "field"}, h("label", {for: id}, label), suffix ? h("div", {class: "inline"}, control, suffix) : control,
        errEl, help ? h("div", {class: "help"}, help) : null);
    }
    function keyField(p) {
      const r = prow(p, v);
      const id = `asst-key-${p}`;
      const help = `Stored only on this computer, in ${v.config_path || "the EDGE settings folder"}. Never in experiment files, bundles or support bundles.`;
      if (S2.keyMode[p] === "stored") {
        const masked = h("input", {class: "input mono", id, readonly: true, "aria-label": "API key (stored, hidden)"});
        masked.value = `••••••••••••••••${r.key_last4 && r.key_last4 !== "set" ? r.key_last4 : ""}`;
        const rep = btn("Replace", () => { S2.keyMode[p] = "new"; renderFields(); const i = fieldsHost.querySelector(`#${id}`); if (i) i.focus(); });
        const rem = btn("Remove", () => { S2.keyMode[p] = "remove"; renderFields(); }, {kind: "danger-quiet"});
        return fieldRow("API key", masked, {id, help, suffix: h("span", {class: "btn-group"}, rep, rem), err: `${p}.api_key`});
      }
      if (S2.keyMode[p] === "remove") {
        return h("div", {class: "field"}, h("span", {class: "label"}, "API key"),
          h("div", {class: "alert warning slim"}, icon("warning"), h("div", {}, h("p", {}, "The stored key will be removed when you save."),
            h("div", {class: "actions"}, btn("Keep it", () => { S2.keyMode[p] = "stored"; renderFields(); })))));
      }
      const inp = h("input", {class: "input mono", id, type: "password", autocomplete: "off", spellcheck: "false", placeholder: p === "anthropic" ? "sk-ant-…" : "sk-…"});
      inp.value = S2.fields[p].api_key;
      inp.addEventListener("input", () => { S2.fields[p].api_key = inp.value.trim(); clearErr(`${p}.api_key`); });
      const eye = iconBtn("eye", "Show the key", () => {
        const showing = inp.type === "text";
        inp.type = showing ? "password" : "text";
        eye.setAttribute("aria-label", showing ? "Show the key" : "Hide the key");
        eye.setAttribute("data-tip", showing ? "Show the key" : "Hide the key");
        eye.replaceChildren(icon(showing ? "eye" : "eyeoff"));
      }, {sm: false});
      const env = r.key_source && String(r.key_source).startsWith("env") ? `Using the key from ${r.key_env || "the environment"} (…${r.key_last4}). Paste a key to use another one. ` : "";
      const keep = r.has_key && r.key_source === "config" ? btn("Keep the stored key", () => { S2.fields[p].api_key = ""; S2.keyMode[p] = "stored"; renderFields(); }, {kind: "ghost"}) : null;
      return fieldRow("API key", inp, {id, help: env + help, suffix: h("span", {class: "btn-group"}, eye, keep), err: `${p}.api_key`});
    }
    function modelControl(p, options) {
      const id = `asst-model-${p}`;
      const cur = S2.fields[p].model;
      if (!options.length || S2.other[p]) {
        const inp = h("input", {class: "input mono", id, spellcheck: "false", autocomplete: "off",
          placeholder: p === "ollama" ? "qwen2.5:14b" : p === "anthropic" ? "claude-opus-5-5" : "model name"});
        inp.value = cur;
        inp.addEventListener("input", () => { S2.fields[p].model = inp.value.trim(); clearErr(`${p}.model`); });
        return inp;
      }
      const sel = h("select", {class: "input", id});
      if (cur && !options.some((o) => o.id === cur)) sel.append(h("option", {value: cur}, cur));
      if (!cur) sel.append(h("option", {value: ""}, "Choose a model"));
      for (const o of options) sel.append(h("option", {value: o.id}, o.text));
      sel.append(h("option", {value: "__other"}, "Another model (type its name)…"));
      sel.value = cur || "";
      sel.addEventListener("change", () => {
        if (sel.value === "__other") { S2.other[p] = true; renderFields(); const i = fieldsHost.querySelector(`#${id}`); if (i) i.focus(); return; }
        S2.fields[p].model = sel.value; clearErr(`${p}.model`);
      });
      return sel;
    }
    function localOptions(p) {
      return [...(S2.models[p] || [])].sort((a, b) => (b.recommended ? 1 : 0) - (a.recommended ? 1 : 0))
        .map((m) => ({id: m.id, text: [m.label || m.id, m.recommended ? "recommended" : "", m.tools ? "tools" : m.tools === false ? "no tools" : "",
          m.vision ? "pictures" : "", m.note || ""].filter(Boolean).join(" · ")}));
    }
    const refreshBtn = (p) => btn("Refresh", () => loadModels(p, true), {ic: "refresh"});
    async function loadModels(p, loud = false) {
      S2.modelErr[p] = null; S2.loading = p;
      if (S2.provider === p) renderFields();
      try {
        const r = await api(`/api/assistant/models?provider=${enc(p)}`);
        S2.models[p] = r.models || [];
        if (r.error) S2.modelErr[p] = r.error;
      } catch (e) { S2.modelErr[p] = {message: errText(e)}; S2.models[p] = []; }
      S2.loading = null;
      if (S2.models[p].length) S2.other[p] = false;
      if (S2.provider === p && body.isConnected) renderFields();
      if (loud && !S2.modelErr[p]) EDGE.announce(`${plural(S2.models[p].length, "model")} found.`);
    }
    function renderFields() {
      const p = S2.provider, F = S2.fields[p], out = [];
      for (const k of Object.keys(errors)) delete errors[k];
      if (p === "anthropic") {
        out.push(keyField(p));
        const recs = (((v.recommended_models || {}).anthropic) || []).map((m) => ({id: m.id, text: `${m.label} · ${m.note}`}));
        out.push(fieldRow("Model", modelControl(p, recs), {id: "asst-model-anthropic", err: `${p}.model`}));
        if (isExpert()) {
          const eff = h("select", {class: "input", id: "asst-effort"}, ["low", "medium", "high", "xhigh", "max"].map((e) => h("option", {value: e}, e)));
          eff.value = F.effort; eff.addEventListener("change", () => { F.effort = eff.value; });
          const addr = h("input", {class: "input mono", id: "asst-url-anthropic", spellcheck: "false"});
          addr.value = F.base_url;
          addr.addEventListener("input", () => { F.base_url = addr.value.trim(); clearErr(`${p}.base_url`); });
          out.push(h("details", {class: "advanced", open: F.base_url !== DEFAULT_URL.anthropic ? true : null}, h("summary", {}, "Advanced"),
            h("div", {class: "row2"}, fieldRow("Effort", eff, {id: "asst-effort"}), fieldRow("Address", addr, {id: "asst-url-anthropic", err: `${p}.base_url`}))));
        }
      } else if (p === "openai") {
        const seg = ui.seg([{value: "openai", label: "OpenAI"}, {value: "openrouter", label: "OpenRouter"}, {value: "custom", label: "Custom address"}],
          F.preset, (val) => { F.preset = val; renderFields(); }, {ariaLabel: "Service"});
        out.push(h("div", {class: "field"}, h("span", {class: "label"}, "Service"), seg));
        if (F.preset === "custom") {
          const addr = h("input", {class: "input mono", id: "asst-url-openai", spellcheck: "false", placeholder: "https://…/v1"});
          addr.value = F.base_url === DEFAULT_URL.openai ? "" : F.base_url;
          addr.addEventListener("input", () => { F.base_url = addr.value.trim(); clearErr(`${p}.base_url`); });
          out.push(fieldRow("Address", addr, {id: "asst-url-openai", err: `${p}.base_url`, help: "The service's OpenAI-compatible address, usually ending in /v1."}));
        }
        out.push(keyField(p));
        const opts = (S2.models[p] || []).map((m) => ({id: m.id, text: m.label && m.label !== m.id ? `${m.label} (${m.id})` : m.id}));
        out.push(fieldRow("Model", modelControl(p, opts), {id: "asst-model-openai", err: `${p}.model`, suffix: refreshBtn(p),
          help: S2.modelErr[p] ? "Save the key first to list the models, or type a model name." : null}));
      } else {
        const addr = h("input", {class: "input mono", id: `asst-url-${p}`, spellcheck: "false"});
        addr.value = F.base_url;
        addr.addEventListener("input", () => { F.base_url = addr.value.trim(); clearErr(`${p}.base_url`); });
        out.push(fieldRow("Address", addr, {id: `asst-url-${p}`, err: `${p}.base_url`,
          help: p === "ollama" ? "Change it only if Ollama runs elsewhere." : "Change it only if LM Studio's server runs elsewhere."}));
        out.push(fieldRow("Model", modelControl(p, localOptions(p)), {id: `asst-model-${p}`, err: `${p}.model`, suffix: refreshBtn(p),
          help: "Small models (7–8 B) manage single changes. To build whole experiments from a description use a 14 B+ model or Claude."}));
        if (S2.loading === p) out.push(h("p", {class: "t-caption loading"}, h("span", {class: "spin", "aria-hidden": "true"}), "Looking for models…"));
        const me = S2.modelErr[p];
        if (me && S2.loading !== p) {
          out.push(h("div", {class: "alert warning slim"}, icon("warning"), h("div", {}, h("b", {}, me.message || "Couldn't list the models."), me.hint ? hintNodes(me.hint) : null)));
        }
        if (isExpert()) {
          const adv = [];
          if (p === "ollama") {
            const ctx = h("input", {class: "input", id: "asst-numctx", type: "number", min: "2048", max: "262144", step: "1024"});
            ctx.value = String(F.num_ctx);
            ctx.addEventListener("input", () => { F.num_ctx = parseInt(ctx.value, 10) || 16384; clearErr("ollama.num_ctx"); });
            adv.push(fieldRow("Context size", ctx, {id: "asst-numctx", err: "ollama.num_ctx"}));
          }
          const tm = h("select", {class: "input", id: `asst-toolmode-${p}`}, [["auto", "Automatic"], ["native", "Native tools"], ["json", "JSON"]].map(([val, label]) => h("option", {value: val}, label)));
          tm.value = F.tool_mode; tm.addEventListener("change", () => { F.tool_mode = tm.value; });
          adv.push(fieldRow("Tool mode", tm, {id: `asst-toolmode-${p}`}));
          out.push(h("details", {class: "advanced"}, h("summary", {}, "Advanced"), h("div", {class: "row2"}, adv)));
        }
      }
      if (INFO[p].cloud) {
        out.push(h("details", {class: "privacy"}, h("summary", {}, icon("cloud"), "What is sent where"),
          ...String((v.privacy || {}).cloud || "").split(/\n\n+/).map((t) => h("p", {class: "t-small t-2"}, t.replace(/^What is sent where\.\s*/, "")))));
      } else {
        out.push(h("p", {class: "asst-privacy"}, icon("lock"), "On this computer: nothing is sent anywhere."));
      }
      fieldsHost.replaceChildren(...out);
    }
    function clearErr(k) { const e = errors[k]; if (e) { e.el.hidden = true; e.el.replaceChildren(); if (e.input) e.input.removeAttribute("aria-invalid"); } }
    function showErr(field, message) {
      const k = errors[field] ? field : Object.keys(errors).find((x) => field && (field.startsWith(x) || x.startsWith(field)));
      const e = k && errors[k];
      if (e) {
        e.el.replaceChildren(icon("error"), message); e.el.hidden = false;
        if (e.input) { e.input.setAttribute("aria-invalid", "true"); e.input.focus(); }
      } else result.replaceChildren(h("div", {class: "alert danger"}, icon("error"), h("div", {}, h("b", {}, message))));
    }
    function patchFor(p) {
      const F = S2.fields[p], out = {};
      if (p === "anthropic") {
        out.model = F.model || null;
        if (isExpert()) { out.effort = F.effort; out.base_url = F.base_url || null; }
      } else if (p === "openai") {
        out.preset = F.preset;
        if (F.preset === "custom") out.base_url = F.base_url || null;
        out.model = F.model || null;
      } else {
        out.base_url = F.base_url || null;
        out.model = F.model || null;
        if (isExpert()) { out.tool_mode = F.tool_mode; if (p === "ollama") out.num_ctx = F.num_ctx; }
      }
      if (INFO[p].cloud) {
        if (S2.keyMode[p] === "remove") out.api_key = "";
        else if (S2.keyMode[p] === "new" && F.api_key) out.api_key = F.api_key;
      }
      return out;
    }
    async function test(testBtn) {
      const p = S2.provider;
      const settings = patchFor(p);
      if (settings.api_key === "") delete settings.api_key;
      for (const k of Object.keys(settings)) if (settings[k] === null) delete settings[k];
      testBtn.setAttribute("aria-busy", "true"); testBtn.disabled = true;
      const lbl = testBtn.querySelector(".lbl");
      lbl.textContent = "Testing…";
      testBtn.prepend(h("span", {class: "spin", "aria-hidden": "true"}));
      result.replaceChildren(h("p", {class: "t-small t-2"}, INFO[p].cloud ? "Connecting…" : "Connecting (a local model can take a minute to load)…"));
      let r;
      try { r = await api("/api/assistant/test", {provider: p, settings}); }
      catch (e) { r = {ok: false, error: {message: errText(e), hint: (e.data && e.data.hint) || ""}}; }
      testBtn.removeAttribute("aria-busy"); testBtn.disabled = false;
      lbl.textContent = "Test connection";
      const sp = testBtn.querySelector(".spin"); if (sp) sp.remove();
      result.replaceChildren(testResult(p, r));
      if (r.ok && !INFO[p].cloud && !(S2.models[p] || []).length) loadModels(p);
    }
    function testResult(p, r) {
      if (r.ok) {
        const caps = r.capabilities || {};
        const bits = [caps.tools === false ? "no tools (JSON mode)" : "tools ✓", caps.vision ? "pictures ✓" : caps.vision === false ? "no pictures" : null,
          caps.context_tokens ? `context ${Number(caps.context_tokens).toLocaleString("en").replace(/,/g, " ")}` : null].filter(Boolean);
        const who = [r.server, modelLabel(p, r.model)].filter(Boolean).join(" · ");
        return h("div", {class: "alert success"}, icon("success"), h("div", {},
          h("b", {}, `Connected${who ? " to " + who : ""}${r.latency_ms != null ? ` in ${(r.latency_ms / 1000).toFixed(1)} s` : ""}`),
          h("p", {}, bits.join(" · ")), ...(r.warnings || []).map((w) => h("p", {class: "t-small"}, w))));
      }
      const e = r.error || {};
      const acts = h("div", {class: "actions"});
      if (e.code === "server_not_running" && g("openHelp")) acts.append(btn(p === "lmstudio" ? "How to start LM Studio ›" : "How to start Ollama ›", () => call("openHelp", "ASSISTANT"), {kind: "ghost"}));
      return h("div", {class: "alert danger"}, icon("error"), h("div", {}, h("b", {}, e.message || "Couldn't connect."),
        e.hint ? hintNodes(e.hint) : null, acts.childElementCount ? acts : null));
    }
    renderFields();
    if (!INFO[S2.provider].cloud) loadModels(S2.provider);

    const res = await ui.dialog({title: "Assistant settings", icon: "assistant", size: "md", body, buttons: [],
      onOpen: (dlg, close) => {
        dlg.id = "assistant-settings";
        dlg.classList.add("asst-settings-dlg");
        const testBtn = h("button", {type: "button", class: "btn left", id: "assistant-test"}, icon("refresh"), h("span", {class: "lbl"}, "Test connection"));
        testBtn.addEventListener("click", () => test(testBtn));
        const cancel = h("button", {type: "button", class: "btn"}, "Cancel");
        cancel.addEventListener("click", () => close(null));
        const save = h("button", {type: "button", class: "btn primary"}, "Save");
        save.addEventListener("click", async () => {
          const p = S2.provider;
          const patch = {provider: p, [p]: patchFor(p), options: {send_images: S2.options.send_images !== false,
            auto_dry_run: S2.options.auto_dry_run !== false, keep_history: S2.options.keep_history !== false}};
          for (const k of Object.keys(patch[p])) if (patch[p][k] === null) delete patch[p][k];
          if (!patch[p].model) { showErr(`${p}.model`, "Choose a model."); return; }
          if (INFO[p].cloud && S2.keyMode[p] === "new" && !S2.fields[p].api_key && !prow(p, v).has_key) { showErr(`${p}.api_key`, "Paste the API key."); return; }
          save.setAttribute("aria-busy", "true"); save.disabled = true;
          try {
            st.view = await api("/api/assistant/config", patch);
            close("saved");
          } catch (e) {
            save.removeAttribute("aria-busy"); save.disabled = false;
            showErr((e.data && e.data.field) || "", errText(e));
          }
        });
        dlg.append(h("footer", {}, testBtn, cancel, save));
      }});
    const warnings = (st.view && st.view.config_warnings) || [];
    await refreshStatus();
    if (res !== "saved") return false;
    const p = providerOf();
    if (p && prow(p).consented === false) {
      const ok = await consentDialog(p);
      if (!ok) return false;
    }
    if (warnings.includes("api_key_cleared")) EDGE.toast("The stored key was removed because the address changed. Paste it again.", {ms: 8000});
    else EDGE.toast(st.view && st.view.configured ? `The assistant is ready: ${providerLabel()}.` : "Saved.");
    renderLog();
    renderContext();
    return true;
  }

  /* the privacy note (assistant spec §13.4) before the first request to an online service */
  async function consentDialog(provider, text = null) {
    const t = text || (st.view && st.view.privacy && st.view.privacy.cloud) || "";
    const paras = String(t).split(/\n\n+/).filter(Boolean);
    const body = h("div", {class: "consent"}, paras.map((s, i) => (i === 0 && /^What is sent where\./.test(s)
      ? h("p", {}, h("b", {}, "What is sent where. "), s.replace(/^What is sent where\.\s*/, ""))
      : h("p", {class: i ? "t-small t-2" : ""}, s))));
    const v = await ui.dialog({title: "Before EDGE sends anything online", icon: "cloud", size: "sm", body,
      onOpen: (dlg) => { dlg.id = "assistant-consent"; },
      buttons: [{label: "Use a local model instead", value: "local"}, {label: "Continue", value: "ok", kind: "primary"}]});
    if (v === "ok") {
      try { await api("/api/assistant/consent", {provider: provider || providerOf()}); await refreshStatus(); return true; }
      catch (e) { EDGE.toast(`Couldn't save your answer: ${errText(e)}`, {tone: "danger"}); return false; }
    }
    if (v === "local") setTimeout(() => openSettings("ollama"), 0);
    return false;
  }

  /* ================================================================ wiring */
  function onDocLoaded(d) {
    const path = d && "path" in d ? d.path : docPath();
    if (keyFor(path) === st.key) return;
    persist();
    loadTranscript(path);
    st.pending = []; st.panelPath = null;
    st.focusOff = false; st.forcedFocus = null;
    if (st.previewJob && st.previewJob.path !== path) st.previewJob = null;
    renderLog(); renderPending(); renderContext(); renderHeadAndState();
  }
  function onDocSaved(d) {
    const path = d && d.path;
    if (!path || keyFor(path) === st.key) return;
    /* an untitled experiment got its name: the conversation moves with it */
    const oldKey = st.key;
    for (const job of st.jobs.values()) if (keyFor(job.path) === oldKey) job.path = path;
    st.key = keyFor(path);
    persist();
    if (oldKey === keyFor(null)) prefs.set(oldKey, null);
  }
  function init() {
    if (!panelEl()) return;
    if (!st.key) loadTranscript(docPath());
    buildPanel();
    refreshStatus();
  }

  try {
    EDGE.on("app:ready", () => { if (!st.panelBuilt) init(); else { onDocLoaded({path: docPath()}); refreshStatus(); } });
    EDGE.on("doc:loaded", onDocLoaded);
    EDGE.on("doc:saved", onDocSaved);
    EDGE.on("doc:changed", onDocChanged);
    EDGE.on("proposal", onProposal);
    EDGE.on("selection", () => renderContext());
    EDGE.on("mode", () => { for (const job of st.jobs.values()) refreshJob(job); });
    EDGE.on("companion", (d) => {
      if (!(d && d.open && d.tab === "assistant")) return;
      if (!st.panelBuilt) init();
      renderContext();
      if (d.focus !== false && st.els.input && !st.els.input.disabled) setTimeout(() => { if (!document.querySelector(".scrim")) st.els.input.focus(); }, 0);
    });
    EDGE.palette.setFallback((text) => {
      const t = String(text || "").trim();
      if (!t || st.unavailable || prefs.get("assistant.hidden", false)) return null;
      return {label: `Ask the assistant: “${t.length > 60 ? t.slice(0, 57) + "…" : t}”`,
        run: () => open({text: t, send: t.split(/\s+/).length >= 3 && !!(st.view && st.view.configured)})};
    });
    EDGE.palette.register({id: "assistant.new", label: "Assistant: new conversation", group: "Assistant", icon: "assistant",
      run: () => { open({}); newConversation(); }});
    EDGE.palette.register({id: "assistant.settings", label: "Assistant settings", group: "Assistant", icon: "settings", run: () => openSettings()});
  } catch (e) { console.error("EDGE assistant: couldn't connect to the app", e); }
  if (document.readyState !== "loading") setTimeout(() => { if (!st.panelBuilt) init(); }, 0);

  /* ================================================================ the public API (§7.5.2) */
  return {
    get ready() { return readyPromise; },
    status: publicStatus,
    mountComposer,
    open,
    ask: (text, opts = {}) => open({...opts, text, send: true}),
    fixIssue,
    openSettings,
    busy: () => !!st.job,
    get lastAppliedAt() { return st.lastAppliedAt; },
    unreviewedCode,
    markReviewed,
    refresh: refreshStatus,
    codeHash,
  };
})();
window.Assistant = Assistant;
