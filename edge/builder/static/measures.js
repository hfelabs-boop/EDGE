/* EDGE builder: "Measures & data" — say what the experiment measures, and see everything it records.
 * Measures live in the experiment's `measures:` list; recording switches are each component's `save`
 * and each device's `record`. The plan (columns, streams, files) comes from /api/recording.
 */
"use strict";

const ROLE_HELP = {
  outcome: "the result you care about (dependent variable)",
  factor: "a condition you vary (independent variable): measures are summarised per level",
  covariate: "recorded to control for (e.g. age, a baseline score)",
  check: "a manipulation or attention check",
  info: "descriptive information about the participant",
};
const KIND_BADGE = {rt: "time", accuracy: "correct?", response: "response", answer: "answer", score: "score", gaze: "gaze",
  timing: "timing", condition: "condition", design: "design", variable: "variable", info: "participant", other: ""};
let _mopen = null;
const _autoIds = new WeakSet();   // measures whose id should follow their name

async function openMeasures() {
  _mopen = {scroll: 0};
  await drawMeasures();
  openModal();
}

async function drawMeasures() {
  const body = $("#modal-body");
  const scroller = $(".modal-box");
  const keep = scroller ? scroller.scrollTop : 0;
  let R;
  try { R = await api("/api/recording", {experiment: S.exp, path: S.path}); }
  catch (e) { toast("Could not work out what is recorded: " + e.message, 5000); return; }
  body.innerHTML = ""; _resetModal(); body.classList.add("measures");
  const plan = R.plan, ms = (S.exp.measures ||= []);
  const changed = async () => { if (!ms.length) delete S.exp.measures; commit(); S.exp.measures ||= []; await drawMeasures(); };
  const measuredBy = (col) => ms.find((m) => m && m.column === col);

  /* ---------- what you measure */
  body.append(h("h2", {}, "What this experiment measures"),
    h("p", {class: "lead"}, "Measures are the results you care about, and the conditions they depend on. After every session EDGE ",
      "summarises them per participant and condition (", h("code", {}, "measures.csv"), ") and checks them: never recorded, ",
      "many missing, or outside the range you expect."));
  const box = h("div", {class: "ms-list"});
  if (!ms.length) box.append(h("div", {class: "ms-empty"}, "No measures yet. ",
    R.suggestions.length ? "EDGE suggests the ones below, or click ★ next to anything in the list of recorded data." :
      "Click ★ next to anything in the list of recorded data below."));
  const loops = plan.loops.map((l) => l.loop);
  const colOptions = (cur) => {
    const sel = h("select", {class: "ms-col"});
    const groups = {};
    for (const [col, c] of Object.entries(plan.columns)) {
      if (!c.saved) continue;
      const g = c.source.startsWith("component:") ? `Screen “${c.source.slice(10).split(".")[0]}”` :
        c.source.startsWith("loop:") ? `Trial list “${c.source.slice(5)}”` : c.source === "participant" ? "Participant" :
        c.source === "variable" ? "Variables" : "Other";
      (groups[g] ||= []).push(col);
    }
    if (cur && !plan.columns[cur]) sel.append(h("option", {value: cur, selected: true}, `${cur} (not recorded!)`));
    for (const [g, cols] of Object.entries(groups)) sel.append(h("optgroup", {label: g},
      cols.map((col) => { const o = h("option", {value: col, title: plan.columns[col].desc}, col); if (col === cur) o.selected = true; return o; })));
    return sel;
  };
  const issuesFor = (i, m) => R.issues.filter((x) => x.where === `measures.${m.id}` || x.where.startsWith(`measures.${m.id}.`) || x.where === `measures[${i}]`);
  ms.forEach((m, i) => {
    if (!m || typeof m !== "object") return;
    const set = (k, v) => { if (v === "" || v === null || v === undefined) delete m[k]; else m[k] = v; changed(); };
    const role = m.role || "outcome";
    const card = h("div", {class: "ms-card role-" + role});
    const label = h("input", {class: "ms-label", value: m.label || m.id || "", placeholder: "name, e.g. Reaction time",
      onchange: (e) => { const v = e.target.value.trim(); m.label = v; if (!m.id || _autoIds.has(m)) { m.id = uniqueId(v.toLowerCase().replace(/\s+/g, "_") || "measure", new Set(ms.filter((x) => x !== m).map((x) => x.id))); } changed(); }});
    const roleSel = h("select", {title: ROLE_HELP[role], onchange: (e) => set("role", e.target.value)},
      Object.keys(R.roles).map((r) => { const o = h("option", {value: r}, R.roles[r]); if (r === role) o.selected = true; return o; }));
    const col = colOptions(m.column); col.onchange = (e) => set("column", e.target.value);
    const isFactor = role === "factor" || role === "info";
    const sum = h("select", {title: "how it is summarised per participant and condition", onchange: (e) => set("summary", e.target.value)},
      R.summaries.map((s) => { const o = h("option", {value: s}, s); if ((m.summary || (isFactor ? "none" : "mean")) === s) o.selected = true; return o; }));
    card.append(h("div", {class: "ms-row"}, label, roleSel,
      h("button", {class: "mini danger", title: "Remove this measure", onclick: () => { ms.splice(i, 1); changed(); }}, "✕")));
    card.append(h("div", {class: "ms-row"}, h("span", {class: "ms-k"}, "from"), col, isFactor ? null : h("span", {class: "ms-k"}, "summary"), isFactor ? null : sum));
    if (!isFactor) {
      const loopSel = h("select", {onchange: (e) => set("loop", e.target.value)}, h("option", {value: ""}, "all trials"),
        loops.map((l) => { const o = h("option", {value: l}, `trials of “${l}”`); if (m.loop === l) o.selected = true; return o; }));
      const only = h("input", {class: "expr", list: "expr-vars", value: m.trials || "", placeholder: "$resp.corr == 1 (optional)",
        onchange: (e) => { let v = e.target.value.trim(); if (v && !v.startsWith("$")) v = "$" + v; set("trials", v); }});
      const ex = m.expect || [];
      const lo = h("input", {type: "number", class: "st-num", value: ex[0] ?? "", placeholder: "min"});
      const hi = h("input", {type: "number", class: "st-num", value: ex[1] ?? "", placeholder: "max"});
      const setEx = () => set("expect", lo.value !== "" && hi.value !== "" ? [+lo.value, +hi.value] : null);
      lo.onchange = setEx; hi.onchange = setEx;
      const units = h("input", {class: "ms-units", value: m.units || "", placeholder: "units", onchange: (e) => set("units", e.target.value.trim())});
      card.append(h("div", {class: "ms-row"}, h("span", {class: "ms-k"}, "use"), loopSel, h("span", {class: "ms-k"}, "only when"), only));
      card.append(h("div", {class: "ms-row"}, h("span", {class: "ms-k"}, "expected between"), lo, h("span", {class: "ms-k"}, "and"), hi, units));
    }
    const line = R.lines[ms.slice(0, i).filter((x) => x && x.column).length];
    if (line && m.column) card.append(h("div", {class: "ms-say"}, "→ " + line));
    for (const x of issuesFor(i, m)) card.append(h("div", {class: "issue " + x.level}, x.message, x.hint ? h("small", {}, " " + x.hint) : null));
    box.append(card);
  });
  for (const x of R.issues.filter((x) => x.where === "measures")) box.append(h("div", {class: "issue " + x.level}, x.message));
  body.append(box);
  const addBlank = () => { const cand = Object.entries(plan.columns).filter(([col, c]) => c.saved && !ms.some((x) => x.column === col));
    const first = ["rt", "accuracy", "score", "response"].map((k) => cand.find(([, c]) => c.kind === k)).find(Boolean);
    const m = {id: uniqueId("measure", new Set(ms.map((x) => x.id))), label: "", role: "outcome", column: first ? first[0] : ""};
    _autoIds.add(m); ms.push(m); changed(); };
  const btns = h("div", {class: "btns"}, h("button", {onclick: addBlank}, "+ Add a measure"));
  body.append(btns);
  if (R.suggestions.length) {
    body.append(h("div", {class: "ms-suggest"}, h("b", {}, "✨ Suggested: "),
      ...R.suggestions.map((sg) => h("button", {class: "mini", title: `${R.roles[sg.role]} from ${sg.column}` + (sg.trials ? `, only when ${sg.trials.slice(1)}` : ""),
        onclick: () => { ms.push(sg); changed(); }}, `+ ${sg.label} (${sg.column})`)),
      R.suggestions.length > 1 ? h("button", {class: "mini primary", onclick: () => { ms.push(...R.suggestions); changed(); }}, "Add all") : null));
  }

  /* ---------- everything that is recorded */
  body.append(h("h2", {class: "ms-h2"}, "Everything that is recorded"),
    h("p", {class: "lead"}, "Worked out from your screens and devices before anything runs. Untick what you don't need; ★ makes a column a measure."));
  const star = (col, kind) => {
    const m = measuredBy(col);
    return h("button", {class: "mini ms-star" + (m ? " on" : ""), title: m ? `Measure “${m.label || m.id}” (click to edit above)` : "Make this a measure",
      onclick: () => { if (m) { $(".modal-box").scrollTop = 0; return; } ms.push(newMeasureFor(col, kind, plan)); changed(); }}, m ? "★" : "☆");
  };
  const colRow = (col, desc, units, kind, saved = true) => h("div", {class: "rec-col" + (saved ? "" : " off")},
    star(col, kind), h("code", {}, col), h("span", {class: "rec-desc"}, desc), units ? h("span", {class: "rec-units"}, units) : null,
    KIND_BADGE[kind] ? h("span", {class: "rec-kind k-" + kind}, KIND_BADGE[kind]) : null);
  const sec = (title, ...kids) => h("details", {class: "rec-sec", open: true}, h("summary", {}, title), ...kids);

  if (plan.participant.length) body.append(sec(`Participant information (${plan.participant.length})`,
    h("div", {class: "help"}, "Asked when a session starts; change the fields in Settings."),
    ...plan.participant.map((f) => colRow(f, "participant information field", "", "info"))));
  if (plan.loops.length) body.append(sec(`Trial lists (${plan.loops.length})`, ...plan.loops.map((l) => h("div", {class: "rec-group"},
    h("div", {class: "rec-head"}, `“${l.loop}” `, h("small", {}, `from ${l.source}`)),
    l.columns ? l.columns.map((c) => colRow(c, "trial-list column: the condition of each trial", "", "condition")) :
      h("div", {class: "help"}, "columns are worked out while the experiment runs")))));
  const byRoutine = {};
  for (const c of plan.components) (byRoutine[c.routine] ||= []).push(c);
  body.append(sec(`Screens: what each thing records (${plan.components.reduce((n, c) => n + (c.save ? c.outputs.length : 0), 0)} columns)`,
    ...Object.entries(byRoutine).map(([rid, cs]) => h("div", {class: "rec-group"}, h("div", {class: "rec-head"}, `Screen “${rid}”`),
      ...cs.filter((c) => c.outputs.length).map((c) => {
        const comp = findComp(rid, c.id);
        const tog = h("input", {type: "checkbox", title: "Save what this records in the data file"});
        tog.checked = c.save;
        tog.onchange = () => { if (!comp) return; if (tog.checked) delete comp.save; else comp.save = false; changed(); };
        return h("div", {class: "rec-comp" + (c.save ? "" : " off")},
          h("label", {class: "rec-comphead"}, tog, h("b", {}, c.id), ` ${friendlyName(c.type)}`, c.save ? "" : h("span", {class: "rec-off"}, " not saved")),
          ...c.outputs.map((o) => colRow(o.column, o.desc, o.units, o.kind, c.save)));
      })))));
  if (plan.variables.length) body.append(sec(`Variables (${plan.variables.length})`,
    ...plan.variables.map((v) => colRow(v, "experiment variable: its value at the end of each trial", "", "variable"))));
  body.append(sec(`Devices (${plan.devices.length})`, plan.devices.length ? null : h("div", {class: "help"}, "No devices: only behaviour is recorded."),
    ...plan.devices.map((d) => {
      const spec = S.exp.devices.find((x) => x.id === d.id);
      const tog = h("input", {type: "checkbox", title: "Write this device's data to disk"});
      tog.checked = d.record; tog.disabled = !d.streams.length;
      tog.onchange = () => { if (!spec) return; if (tog.checked) delete spec.record; else spec.record = false; changed(); };
      return h("div", {class: "rec-comp" + (d.record ? "" : " off")},
        h("label", {class: "rec-comphead"}, tog, h("b", {}, d.id), ` ${d.type}`, d.record || !d.streams.length ? "" : h("span", {class: "rec-off"}, " not recorded")),
        ...d.streams.map((s) => h("div", {class: "rec-col"}, h("span", {class: "rec-kind k-gaze"}, s.kind || "stream"),
          h("code", {}, `streams/${d.id}.${s.name}.csv`),
          h("span", {class: "rec-desc"}, `${s.what}: ${s.channels ? `${s.channels.length} channels` : "channels as the device reports them"}, ` +
            (s.srate ? `${s.srate} samples/s` : s.kind === "Events" ? "one row whenever an input changes" : "at the device's own rate")),
          s.channels ? h("details", {class: "rec-ch"}, h("summary", {}, "channels"), s.channels.join(", ")) : null)),
        d.note ? h("div", {class: "help"}, "↳ " + d.note) : null,
        d.markers ? h("div", {class: "help"}, "↳ receives the event markers") : null);
    })));
  body.append(sec("Always saved", ...plan.always.map((f) => h("div", {class: "rec-col"}, h("code", {}, f.file), h("span", {class: "rec-desc"}, f.what)))));
  body.append(h("div", {class: "btns"}, h("button", {class: "primary", onclick: closeModal}, "Done")));
  if (scroller) scroller.scrollTop = keep;
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

window.addEventListener("DOMContentLoaded", () => { const b = $("#btn-measures"); if (b) b.onclick = () => openMeasures(); });

/* ================================================================== live session monitor */
function fmtMeasure(m, v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v !== "number") return String(v);
  if (m && m.summary === "proportion") return Math.round(v * 100) + "%";
  if (m && m.units === "s" && Math.abs(v) < 20) return Math.round(v * 1000) + " ms";
  return (Math.abs(v) >= 100 ? v.toFixed(0) : +v.toPrecision(3)) + (m && m.units && m.units !== "s" ? " " + m.units : "");
}

function sparkline(vals, expect) {
  const nums = vals.map((v) => (typeof v === "number" ? v : typeof v === "boolean" ? +v : null));
  const ok = nums.filter((v) => v !== null);
  const W = 220, H = 36;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "mon-spark");
  if (ok.length < 2) return svg;
  const lo = Math.min(...ok, ...(expect ? [expect[0]] : [])), hi = Math.max(...ok, ...(expect ? [expect[1]] : []));
  const x = (i) => (i / Math.max(1, nums.length - 1)) * (W - 4) + 2, y = (v) => H - 3 - ((v - lo) / ((hi - lo) || 1)) * (H - 6);
  const ns = "http://www.w3.org/2000/svg";
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

/* What the run window shows while a participant is running. update(status) redraws it. */
function monitorView() {
  const el = h("div", {class: "mon"});
  const update = (st) => {
    const M = st.monitor || {}, start = M.start, last = M.last, end = M.end;
    el.innerHTML = "";
    if (!start) { el.append(h("div", {class: "mon-wait"}, st.running ? "Starting: opening the window and connecting devices…" : "")); return; }
    const ms = start.measures || [], mById = Object.fromEntries(ms.map((m) => [m.id, m]));
    const n = (end || last || {}).trials ?? (last ? last.n : 0) ?? 0;
    const elapsed = (end || M.devices || last || {}).elapsed || 0;
    const exp = start.expected_trials;
    const pct = exp ? Math.min(100, Math.round(100 * n / exp)) : null;
    const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
    const eta = exp && n > 1 && n < exp ? ` · about ${mmss(elapsed / n * (exp - n))} left` : "";
    el.append(h("div", {class: "mon-prog"},
      h("div", {class: "mon-bar"}, h("div", {style: `width:${pct ?? 0}%`})),
      h("div", {class: "mon-progtxt"}, `Trial ${n}${exp ? ` of about ${exp}` : ""} · ${mmss(elapsed)} elapsed${eta}`)));
    const warns = [];
    // measures, live
    const hist = M.history || [];
    const run = (end || last || {}).running || {};
    const kpis = h("div", {class: "mon-kpis"});
    for (const m of ms.filter((m) => m.role !== "factor")) {
      const r = run[m.id] || {};
      const series = hist.map((t) => (t.values || {})[m.id]).filter((v, i) => Object.prototype.hasOwnProperty.call(hist[i].values || {}, m.id));
      const out = m.expect ? series.filter((v) => typeof v === "number" && (v < m.expect[0] || v > m.expect[1])).length : 0;
      const missRate = r.n + r.missing ? r.missing / (r.n + r.missing) : 0;
      if (missRate > 0.2 && r.n + r.missing >= 5) warns.push(`${m.label || m.id}: missing on ${Math.round(missRate * 100)}% of trials so far`);
      const tail = series.slice(-5);
      if (tail.length === 5 && tail.every((v) => v === null || v === "")) warns.push(`${m.label || m.id}: no value on the last 5 trials. Is the participant still responding?`);
      if (out) warns.push(`${m.label || m.id}: ${out} value(s) outside ${m.expect[0]}–${m.expect[1]}`);
      kpis.append(h("div", {class: "mon-kpi" + (missRate > 0.2 || out ? " warn" : "")},
        h("span", {class: "mon-kl"}, m.label || m.id), h("b", {}, fmtMeasure(m, r.value)),
        h("small", {}, `${m.summary} of ${r.n || 0}` + (r.missing ? ` · ${r.missing} missing` : "")),
        sparkline(series.slice(-120), m.expect)));
    }
    if (!ms.filter((m) => m.role !== "factor").length) kpis.append(h("div", {class: "mon-kpi note"},
      "No measures declared, so there's nothing to follow here. Define them in ", h("b", {}, "Measures & data"), " to watch reaction times, accuracy or scores live."));
    el.append(kpis);
    // nobody responding?
    const asked = hist.filter((t) => Object.keys(t.responses || {}).some((k) => /\.(keys|input|rt|rating|clicked)$/.test(k)));
    let silent = 0;
    for (let i = asked.length - 1; i >= 0; i--) {
      if (Object.entries(asked[i].responses).some(([k, v]) => /\.(keys|input|rt|rating|clicked)$/.test(k) && v !== null && v !== "")) break;
      silent++;
    }
    if (!end && silent >= 3) warns.unshift(`No response on the last ${silent} trials. Is the participant still responding, and is the keyboard/response box connected?`);
    // last screen that asked for a response
    const shown = M.last_response || last;
    if (shown) {
      const last = shown;
      const resp = Object.entries(last.responses || {}).filter(([, v]) => v !== null && v !== "");
      el.append(h("div", {class: "mon-last"}, h("b", {}, "Last: "), `${last.routine}`,
        ...Object.entries(last.factors || {}).map(([k, v]) => h("span", {class: "mon-chip"}, `${(mById[k] || {}).label || k} = ${v}`)),
        ...resp.map(([k, v]) => h("span", {class: "mon-chip r"}, `${k} ${k.endsWith(".rt") && typeof v === "number" ? Math.round(v * 1000) + " ms" : k.endsWith(".corr") ? (v ? "✓" : "✗") : v}`))));
    }
    // devices
    const devs = M.devices?.devices || {};
    if (Object.keys(start.devices || {}).length) {
      const tbl = h("div", {class: "mon-devs"});
      for (const [did, d] of Object.entries(start.devices)) {
        const live = devs[did]?.streams || {};
        const names = Object.keys(d.streams || {});
        if (!names.length) tbl.append(h("div", {class: "mon-dev"}, h("span", {class: "dot ok"}), h("b", {}, did), ` ${d.type} · sends markers`));
        for (const s of names) {
          const L = live[s] || {}, status = end ? "done" : L.status || "wait";
          if (!end && status === "silent") warns.push(`${did}.${s}: no data for more than a second. Check the device and its cable.`);
          if (!end && status === "low") warns.push(`${did}.${s}: ${L.rate} samples/s, expected ${L.nominal}`);
          tbl.append(h("div", {class: "mon-dev"}, h("span", {class: "dot " + status}), h("b", {}, `${did}.${s}`),
            h("span", {}, L.rate != null ? ` ${L.rate}/s` : " …", L.nominal ? ` (nominal ${L.nominal})` : ""),
            h("small", {}, ` ${L.samples ?? 0} samples · ${d.streams[s].channels} ch`)));
        }
      }
      el.append(h("div", {class: "mon-h"}, "Devices"), tbl);
    }
    if (warns.length) el.prepend(h("div", {class: "mon-warns"}, ...warns.map((w) => h("div", {class: "issue warning"}, "⚠ " + w))));
    if (end && end.errors?.length) el.append(h("div", {class: "issue error"}, end.errors.slice(0, 3).join("; ")));
  };
  return {el, update};
}

/* A short "this session will record …" summary for the run dialog. */
async function recordingSummary() {
  let R; try { R = await api("/api/recording", {experiment: S.exp, path: S.path}); } catch { return null; }
  const p = R.plan;
  const cols = p.components.reduce((n, c) => n + (c.save ? c.outputs.length : 0), 0);
  const streams = p.devices.flatMap((d) => (d.record ? d.streams.map((s) => `${d.id}.${s.name}`) : []));
  const box = h("div", {class: "rec-summary"});
  box.append(h("div", {}, h("b", {}, "Measures: "), R.lines.length ? R.lines.join(" · ") : h("span", {class: "warn-txt"}, "none declared. You can still run, but say what you measure to get live values, measures.csv and checks.")));
  box.append(h("div", {}, h("b", {}, "Recorded: "), `${cols} response/timing columns`, p.loops.length ? `, trial lists ${p.loops.map((l) => l.loop).join(", ")}` : "",
    streams.length ? `, streams ${streams.join(", ")}` : "", `, event markers and screen timing.`));
  box.append(h("a", {href: "#", onclick: (e) => { e.preventDefault(); openMeasures(); }}, "Review measures & data →"));
  return box;
}

/* ================================================================== computer check (before a session) */
async function computerCheckBox() {
  const box = h("div", {class: "pc-check"}, h("span", {class: "help"}, "Checking this computer…"));
  const draw = async () => {
    let r;
    try { r = await api("/api/system_check" + (S.path ? `?path=${encodeURIComponent(S.path)}` : "")); }
    catch { box.innerHTML = ""; return; }
    const bad = r.checks.filter((c) => c.level === "warning" || c.level === "error");
    const info = r.checks.filter((c) => c.level === "info");
    box.innerHTML = "";
    if (!bad.length) {
      box.append(h("div", {class: "ok"}, "✓ Computer check: nothing that would affect timing", info.length ? h("small", {}, ` (${info.length} note${info.length > 1 ? "s" : ""})`) : null));
    } else box.append(h("b", {}, `Computer check: ${bad.length} thing${bad.length > 1 ? "s" : ""} to look at`));
    for (const c of [...bad, ...info]) {
      const row = h("div", {class: "issue " + (c.level === "info" ? "info" : c.level)}, h("b", {}, c.title), h("div", {}, c.detail),
        c.fix ? h("div", {class: "pc-fix"}, "→ ", c.fix) : null);
      if (c.fixable) row.append(h("button", {class: "mini", onclick: async (e) => {
        e.target.disabled = true; e.target.textContent = "Fixing…";
        const res = await api("/api/system_fix", {id: c.id}).catch((err) => ({ok: false, error: err.message}));
        toast(res.ok ? `Done: ${res.done}` : `Could not fix: ${res.error}`, 5000);
        draw();
      }}, "Fix"));
      if (c.level === "info") row.classList.add("pc-info");
      box.append(row);
    }
  };
  draw();
  return box;
}
