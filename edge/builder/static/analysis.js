/* analysis.js: the Data page's "Eye & signals" tab (docs/DATA.md "Analyses"). Owner: data analysis. Runs the analyses of edge/analysis on one session:
 * fixations and saccades, area-of-interest (AOI) reports, and epochs/averages of EEG or pupil size around markers.
 * renderAnalysis(panel, sessionPath, info) draws it; info comes from /api/analysis_info, results from
 * /api/analyze and the files are downloaded through /api/file. Uses app.js helpers (h, api, icon, toast, dataTable).
 */
"use strict";

const AN = {last: {}, busy: false, opts: {}, n: 0};

function anField(label, input, help) {
  const id = input.id || (input.id = `an-f${++AN.n}`);
  return h("div", {class: "field"}, h("label", {for: id}, label), input, help ? h("div", {class: "help"}, help) : null);
}
function anNum(value, attrs = {}) {
  return h("input", {class: "input", type: "number", step: "any", value: value ?? "", ...attrs});
}
function anList(text) {
  return String(text || "").split(/[,\n]/).map((s) => s.trim()).filter(Boolean);
}

function renderAnalysis(panel, path, info) {
  const o = AN.opts[path] || (AN.opts[path] = {method: "ivt", by: (info.conditions || []).join(", "), aois: "",
    stream: (info.signals[0] || {}).name || (info.pupil ? "pupil" : ""), markers: new Set(), tmin: -0.2, tmax: 0.8,
    b0: -0.2, b1: 0, reject: "", eby: ""});
  const out = h("div", {class: "an-results", "aria-live": "polite"});
  const cards = h("div", {class: "an-cards"});

  const run = async (kind, options, btn) => {
    if (AN.busy) return;
    AN.busy = true;
    btn.disabled = true;
    const old = [...btn.childNodes];
    btn.replaceChildren(h("span", {class: "spin", "aria-hidden": "true"}), "Working…");
    out.replaceChildren(h("div", {class: "t-caption"}, "Analysing… long recordings take a little while."));
    try {
      const res = await api("/api/analyze", {path, kind, options});
      AN.last[path] = res;
      drawAnalysisResult(out, res);
    } catch (e) {
      out.replaceChildren(h("div", {class: "alert danger"}, icon("error"), h("div", {}, h("b", {}, "The analysis didn't run. "), e.message)));
    } finally {
      AN.busy = false;
      btn.disabled = false;
      btn.replaceChildren(...old);
    }
  };

  if (info.gaze.length) {
    const method = ui.seg([{value: "ivt", label: "Velocity (I-VT)"}, {value: "idt", label: "Dispersion (I-DT)"}], o.method,
      (v) => { o.method = v; thr.value = ""; thr.placeholder = v === "ivt" ? "30" : "1.0"; minDur.placeholder = v === "ivt" ? "0.06" : "0.1"; thrLabel.textContent = v === "ivt" ? "Speed limit (deg/s)" : "Spread limit (deg)"; },
      {ariaLabel: "Fixation method", size: "sm"});
    const thr = anNum("", {placeholder: o.method === "ivt" ? "30" : "1.0"});
    const thrLabel = h("span", {}, o.method === "ivt" ? "Speed limit (deg/s)" : "Spread limit (deg)");
    const minDur = anNum("", {placeholder: o.method === "ivt" ? "0.06" : "0.1"});
    const by = h("input", {class: "input", value: o.by, placeholder: "e.g. congruent, image"});
    by.oninput = () => { o.by = by.value; };
    const aois = h("textarea", {class: "input mono", rows: 3, placeholder: "face:rect:0,100,300,200\ncentre:circle:0,0,80"}, o.aois);
    aois.oninput = () => { o.aois = aois.value; };
    const found = Object.entries(info.aois || {});
    const fopts = () => {
      const x = {method: o.method};
      if (thr.value !== "") x[o.method === "ivt" ? "velocity_threshold" : "dispersion_threshold"] = +thr.value;
      if (minDur.value !== "") x.min_duration = +minDur.value;
      return x;
    };
    const bFix = h("button", {class: "btn sm"}, icon("eye"), "Find fixations");
    bFix.onclick = () => run("fixations", fopts(), bFix);
    const bAoi = h("button", {class: "btn sm primary"}, icon("table"), "Areas of interest report");
    bAoi.onclick = () => run("aoi", {...fopts(), aois: String(o.aois).split("\n").map((s) => s.trim()).filter(Boolean), by: anList(o.by)}, bAoi);
    cards.append(h("section", {class: "card an-card", "aria-label": "Fixations and areas of interest"},
      h("h3", {class: "t-title-s"}, icon("eyetracker"), "Fixations and areas of interest"),
      h("p", {class: "t-small t-2"}, `Finds fixations and saccades in the gaze recording (${info.gaze.join(", ")}), then measures, per trial, how soon, how long and how often each area was looked at.`),
      h("div", {class: "field"}, h("span", {class: "label"}, "Method"), method),
      h("div", {class: "row2"}, anField(thrLabel, thr), anField("Shortest fixation (s)", minDur)),
      h("div", {class: "field"}, h("span", {class: "label"}, "Areas from the experiment"),
        found.length ? h("div", {class: "an-chips"}, found.flatMap(([r, ids]) => ids.map((id) => h("span", {class: "chip outline", title: `on the screen “${r}”`}, icon("eye"), id))))
          : h("div", {class: "help"}, "No gaze areas, pictures or shapes: add your own below.")),
      anField("Your own areas (one per line)", aois, "name:rect:x,y,width,height or name:circle:x,y,radius, in pixels from the screen centre (up is +y); add :screen at the end to use it on one screen only."),
      anField("Compare by (trial list columns)", by),
      h("div", {class: "btn-group"}, bAoi, bFix)));
  }

  const signals = [...info.signals.map((s) => ({value: s.name, label: `${s.name} (${s.kind || "signal"}, ${s.channels.length} channels)`})),
    ...(info.pupil ? [{value: "pupil", label: "Pupil size (eye tracker)"}] : [])];
  if (signals.length) {
    const sel = h("select", {class: "input"}, signals.map((s) => h("option", {value: s.value, selected: s.value === o.stream ? "" : null}, s.label)));
    sel.onchange = () => { o.stream = sel.value; };
    const marks = Object.entries(info.markers || {});
    const markBox = h("div", {class: "an-chips", role: "group", "aria-label": "Markers"},
      marks.length ? marks.map(([m, n]) => {
        const cb = h("input", {type: "checkbox", checked: o.markers.has(m) ? "" : null});
        cb.onchange = () => { cb.checked ? o.markers.add(m) : o.markers.delete(m); };
        return h("label", {class: "chip outline an-mark"}, cb, h("span", {class: "mono"}, m), h("span", {class: "t-caption"}, `${n}×`));
      }) : h("div", {class: "help"}, "This session has no markers: give items a marker to cut epochs around them."));
    const tmin = anNum(o.tmin), tmax = anNum(o.tmax), b0 = anNum(o.b0), b1 = anNum(o.b1);
    const reject = anNum(o.reject, {placeholder: "automatic"});
    const eby = h("select", {class: "input"}, [h("option", {value: ""}, "The marker"),
      ...(info.conditions || []).map((c) => h("option", {value: c, selected: o.eby === c ? "" : null}, `Trial list column: ${c}`))]);
    for (const [el, k] of [[tmin, "tmin"], [tmax, "tmax"], [b0, "b0"], [b1, "b1"], [reject, "reject"], [eby, "eby"]]) el.addEventListener("change", () => { o[k] = el.value; });
    const bEp = h("button", {class: "btn sm primary"}, icon("eeg"), "Cut epochs and average");
    bEp.onclick = () => {
      if (!o.markers.size) { out.replaceChildren(h("div", {class: "alert warning"}, icon("warning"), h("div", {}, "Tick the markers to cut epochs around."))); return; }
      const x = {stream: sel.value, markers: [...o.markers], tmin: +tmin.value, tmax: +tmax.value, baseline: b0.value === "" || b1.value === "" ? null : [+b0.value, +b1.value]};
      if (reject.value !== "") x.reject = +reject.value;
      if (eby.value) x.by = [eby.value];
      run("epochs", x, bEp);
    };
    cards.append(h("section", {class: "card an-card", "aria-label": "Epochs"},
      h("h3", {class: "t-title-s"}, icon("eeg"), "Epochs and averages (EEG, pupil)"),
      h("p", {class: "t-small t-2"}, "Cuts the recording around each marker, subtracts the baseline, leaves out epochs with artefacts and averages the rest per condition. Pupil size has blinks filled in first."),
      anField("Signal", sel),
      h("div", {class: "field"}, h("span", {class: "label"}, "Markers"), markBox),
      h("div", {class: "row2"}, anField("From (s)", tmin), anField("To (s)", tmax)),
      h("div", {class: "row2"}, anField("Baseline from (s)", b0), anField("Baseline to (s)", b1)),
      h("div", {class: "row2"}, anField("Reject above (peak to peak)", reject, "Empty: 150 µV for EEG, none for pupil."), anField("Conditions", eby)),
      h("div", {class: "btn-group"}, bEp)));
  }
  if (!cards.childElementCount) {
    panel.replaceChildren(h("p", {class: "t-2 pad"}, "This session has no eye-tracking, EEG or other recording to analyse."));
    return;
  }
  panel.replaceChildren(h("div", {class: "an-wrap"}, cards, out));
  if (AN.last[path]) drawAnalysisResult(out, AN.last[path]);
}

const AN_TITLES = {epochs: "Epochs", fixations: "Fixations", aoi: "Areas of interest"};
function drawAnalysisResult(out, res) {
  const s = res.summary || {};
  const kpi = (v, l) => h("div", {class: "kpi"}, h("b", {}, v), h("span", {}, l));
  const kp = res.kind === "epochs"
    ? [kpi(s.epochs, "epochs"), kpi(s.kept, "kept"), kpi(s.rejected, "rejected"), kpi(`${s.srate} Hz`, (s.channels || []).length + " channel(s)")]
    : [kpi(s.fixations, "fixations"), kpi(s.saccades, "saccades"), kpi(s.mean_fixation_duration == null ? "–" : `${Math.round(s.mean_fixation_duration * 1000)} ms`, "mean fixation"),
       kpi(s.screen ? `${s.screen.px_per_deg}` : "–", "pixels per degree")];
  const notes = (res.notes || []).map((n) => h("div", {class: "alert info"}, icon("info"), h("div", {}, n)));
  const tables = Object.entries(res.tables || {}).map(([name, rows]) => {
    const cols = rows.length ? Object.keys(rows[0]) : [];
    return h("div", {class: "an-table"}, h("h4", {class: "t-title-s"}, name.charAt(0).toUpperCase() + name.slice(1)),
      h("div", {class: "table-wrap"}, dataTable(cols, rows)));
  });
  const png = (res.files || []).find((f) => f.endsWith(".png"));
  const files = h("ul", {class: "export-list"}, (res.files || []).map((f) => h("li", {}, h("a", {href: `/api/file?download=1&path=${encodeURIComponent(f)}`}, icon("export"), f.split("/").pop()))));
  out.replaceChildren(h("h3", {class: "t-title-m"}, AN_TITLES[res.kind] || res.kind),
    h("div", {class: "kpis"}, kp), ...notes,
    png ? h("img", {class: "an-plot", src: `/api/file?path=${encodeURIComponent(png)}`, alt: "Average per condition"}) : "",
    ...tables, h("h4", {class: "t-title-s"}, "Download"), files,
    h("p", {class: "t-caption"}, "Saved in the session's analysis folder. What each column means: Help › Saving, loading and data › Analyses."));
}
