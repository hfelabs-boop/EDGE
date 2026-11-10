/* console.js: running a study day from the Run page (docs/BUILDER_GUIDE.md "Running a study day"). Owner: P4b.
 *   Study day card  - the participant queue (planned IDs, session, group, status), plan the next IDs, import or
 *                     export CSV, start the next participant, mark a no-show, the run log of the day
 *   Live console    - while a session records: where the participant is (screen, trial n of N), Pause/Resume,
 *                     Stop with a reason, signal quality per channel, notes with times, the participant's screen
 *                     (opt-in), and the experimenter window for a second monitor (?console=1)
 *   Notes           - the same notes panel after the session and on the Data page (notes.md / notes.json)
 * Server side: edge/studyday.py (/api/studyday/...), edge/quality.py, edge/monitor.py. */

const SD = {queue: null, qKey: "", loading: false, notes: [], notesRun: null, notesBusy: false, mirrorT: 0, screens: null,
  mirror: false, logOpen: false};
const SD_STATUS = {planned: ["", "Planned"], running: ["accent", "Running"], done: ["success", "Done"], aborted: ["warning", "Stopped early"],
  "no-show": ["outline", "No-show"]};
const CONSOLE_MODE = new URLSearchParams(location.search).get("console") === "1";

async function sdApi(path, body) { return api(path, body); }
function sdRefresh() { if (S.ws === "run" && typeof renderRunPage === "function") renderRunPage(); }

/* ================================================================== the queue */
async function sdLoadQueue(force = false) {
  if (!S.path) return null;
  const key = S.path;
  if (!force && SD.queue && SD.qKey === key) return SD.queue;
  if (SD.loading) return SD.queue;
  SD.loading = true;
  try { SD.queue = await sdApi(`/api/studyday/queue?path=${encodeURIComponent(S.path)}`); SD.qKey = key; }
  catch (e) { SD.queue = {error: e.message, entries: [], log: [], counts: {}}; SD.qKey = key; }
  finally { SD.loading = false; }
  return SD.queue;
}
async function sdQueueOp(op, extra = {}) {
  try {
    SD.queue = await sdApi("/api/studyday/queue", {path: S.path, op, ...extra}); SD.qKey = S.path;
    sdDrawQueue();
    return SD.queue;
  } catch (e) { toast(e.message, {tone: "danger", ms: 6000}); return null; }
}

/* The card on the Run page (before and after a session, and in the experimenter window). */
function studyDayCard() {
  const card = h("section", {class: "card pad run-card sd-card", id: "sd-card", "aria-labelledby": "sd-title"});
  if (!S.path) {
    card.append(h("h2", {class: "t-title-s", id: "sd-title"}, "Today's participants"),
      h("p", {class: "t-small t-2"}, "Save the experiment to plan participants for a study day."));
    return card;
  }
  card.append(h("div", {class: "t-caption"}, "Loading the participant queue…"));
  sdLoadQueue(!SD.queue || SD.qKey !== S.path).then(() => sdDrawQueue());
  return card;
}

function sdDrawQueue() {
  const card = document.getElementById("sd-card");
  if (!card) return;
  const Q = SD.queue || {entries: [], log: [], counts: {}};
  const live = S.run?.running;
  const head = h("div", {class: "card-head sd-head"}, h("h2", {class: "t-title-s", id: "sd-title"}, "Today's participants"),
    h("span", {class: "sd-counts t-small t-2"}, Q.entries.length ? sdCountsText(Q.counts) : ""), h("span", {class: "grow"}),
    h("button", {type: "button", class: "btn sm", "data-fkey": "sd:plan", onclick: () => sdPlanDialog()}, icon("plus"), "Plan participants"),
    h("button", {type: "button", class: "btn sm ghost icon", "aria-label": "More queue actions", "aria-haspopup": "menu", "data-tip": "Import, export…",
      onclick: (e) => ui.menu(e.currentTarget, [
        {label: "Import a list (CSV)…", icon: "import", run: () => sdImport()},
        {label: "Export the list (CSV)", icon: "export", run: () => sdExport()},
        {label: "Groups for counterbalancing…", icon: "list", run: () => sdGroupsDialog()},
        {label: "Remove done and no-shows", icon: "trash", run: () => sdQueueOp("clear_done")}])}, icon("more")));
  const out = [head];
  if (Q.error) out.push(h("div", {class: "alert danger"}, icon("error"), h("div", {}, Q.error)));
  const next = Q.entries.find((e) => e.id === Q.next);
  if (next && !live) {
    out.push(h("div", {class: "sd-next"},
      h("div", {class: "sd-next-txt"}, h("span", {class: "t-caption"}, "Next"), h("b", {}, `Participant ${next.participant}`),
        h("span", {class: "t-small t-2"}, [`session ${next.session}`, next.group ? `group ${next.group}` : null].filter(Boolean).join(" · "))),
      h("span", {class: "grow"}),
      h("label", {class: "sd-mirror t-small", "data-tip": "Shows a small copy of the participant's screen every 2 s. Taking it can cost a frame, so leave it off for timing-critical studies."},
        h("input", {type: "checkbox", checked: SD.mirror ? "" : null, onchange: (e) => { SD.mirror = e.target.checked; }}), "Show their screen"),
      h("button", {type: "button", class: "btn primary", "data-fkey": "sd:startnext", onclick: () => sdStart(next)}, icon("run"), `Start ${next.participant}`)));
  }
  if (!Q.entries.length) {
    out.push(h("p", {class: "t-small t-2 sd-empty"}, "Plan who comes today: the next free participant IDs, their session and group (counterbalancing). ",
      "Then start each one from here; the list keeps track of who is done, stopped early or didn't come."));
  } else {
    const tbl = h("table", {class: "grid sd-table"}, h("thead", {}, h("tr", {},
      h("th", {}, "Participant"), h("th", {}, "Session"), h("th", {}, "Group"), h("th", {}, "Status"), h("th", {class: "sd-com"}, "Comment"), h("th", {class: "x"}, h("span", {class: "sr-only"}, "Actions")))));
    const body = h("tbody");
    for (const e of Q.entries) body.append(sdRow(e, e.id === Q.next));
    tbl.append(body);
    out.push(h("div", {class: "table-wrap sd-wrap"}, tbl));
  }
  out.push(sdLogBox(Q.log || []));
  card.replaceChildren(...out);
}
function sdCountsText(c) {
  const bits = [];
  if (c.done) bits.push(`${c.done} done`);
  if (c.running) bits.push(`${c.running} running`);
  if (c.planned) bits.push(`${c.planned} to go`);
  if (c.aborted) bits.push(`${c.aborted} stopped early`);
  if (c["no-show"]) bits.push(`${c["no-show"]} no-show`);
  return bits.join(" · ");
}
function sdRow(e, isNext) {
  const [tone, word] = SD_STATUS[e.status] || ["", e.status];
  const editable = e.status !== "running";
  const cell = (k, cls, label) => h("td", {}, editable && ["planned", "no-show"].includes(e.status)
    ? h("input", {class: "input sd-in " + (cls || ""), value: e[k] ?? "", "aria-label": `${label} of ${e.participant}`, "data-fkey": `sd:${e.id}:${k}`,
      onchange: (ev) => sdQueueOp("update", {id: e.id, fields: {[k]: ev.target.value}})})
    : h("span", {class: "sd-static" + (cls === "mono" ? " mono" : "")}, e[k] || "–"));
  const acts = h("div", {class: "sd-acts"});
  if (e.status === "planned" && !S.run?.running)
    acts.append(h("button", {type: "button", class: "btn sm" + (isNext ? " primary" : ""), onclick: () => sdStart(e)}, icon("run"), "Start"));
  if (e.data && ["done", "aborted"].includes(e.status))
    acts.append(h("button", {type: "button", class: "btn sm ghost", onclick: () => sdOpenData(e.data)}, "Data"));
  const menu = [];
  if (e.status === "planned") menu.push({label: "Didn't come (no-show)…", run: () => sdNoShow(e)});
  if (["no-show", "aborted", "done"].includes(e.status)) menu.push({label: "Plan again", run: () => sdQueueOp("update", {id: e.id, fields: {status: "planned"}})});
  if (e.status !== "running") {
    menu.push({label: "Move up", run: () => sdQueueOp("move", {id: e.id, by: -1})}, {label: "Move down", run: () => sdQueueOp("move", {id: e.id, by: 1})});
    menu.push({label: "Remove from the list", icon: "trash", run: () => sdQueueOp("delete", {id: e.id})});
  }
  if (menu.length) acts.append(h("button", {type: "button", class: "btn sm ghost icon", "aria-label": `More for participant ${e.participant}`, "aria-haspopup": "menu",
    onclick: (ev) => ui.menu(ev.currentTarget, menu, {placement: "bottom-end"})}, icon("more")));
  const status = h("td", {}, h("span", {class: `chip ${tone}`, "data-tip": e.reason || null}, e.status === "running" ? h("span", {class: "dot"}) : null, word),
    e.reason && e.status !== "running" ? h("span", {class: "t-caption sd-reason"}, ` ${e.reason}`) : null);
  return h("tr", {class: "sd-row s-" + e.status + (isNext ? " next" : ""), "data-id": e.id},
    cell("participant", "mono", "ID"), cell("session", "num", "Session"), cell("group", "", "Group"), status,
    h("td", {class: "sd-com"}, h("input", {class: "input sd-in", value: e.comment || "", placeholder: "—", "aria-label": `Comment on ${e.participant}`,
      "data-fkey": `sd:${e.id}:comment`, onchange: (ev) => sdQueueOp("update", {id: e.id, fields: {comment: ev.target.value}})})),
    h("td", {class: "x"}, acts));
}
function sdLogBox(log) {
  const box = h("details", {class: "sd-log run-logbox", open: SD.logOpen ? "" : null, ontoggle: (e) => { SD.logOpen = e.target.open; }},
    h("summary", {}, `Run log of today${log.length ? ` (${log.length})` : ""}`));
  if (!log.length) box.append(h("p", {class: "t-caption"}, "Nothing yet today. Starts, ends, stops (with the reason), pauses, notes and no-shows are listed here."));
  else box.append(h("ol", {class: "sd-loglist t-small"}, log.slice().reverse().map((ev) => h("li", {class: "k-" + ev.kind},
    h("span", {class: "t-2 mono"}, clock(ev.time)), " ", ev.text || ev.kind))));
  return box;
}
function sdOpenData(rel) {
  if (typeof D !== "undefined") { D.filter = "participants"; D.sel = null; D.pick = String(rel).split("/").filter(Boolean).pop(); }
  if (typeof runClear === "function" && S.run && !S.run.running) runClear();
  EDGE.go("data");
}

async function sdPlanDialog() {
  const Q = SD.queue || {groups: []};
  const count = h("input", {class: "input num", id: "sd-n", value: "4", inputmode: "numeric"});
  const start = h("input", {class: "input num", id: "sd-first", placeholder: "next free", inputmode: "numeric"});
  const ses = h("input", {class: "input num", id: "sd-ses", value: "1", inputmode: "numeric"});
  const groups = h("input", {class: "input", id: "sd-groups", value: (Q.groups || []).join(", "), placeholder: "e.g. A, B"});
  const body = h("div", {class: "sd-plan"},
    h("div", {class: "field"}, h("label", {for: "sd-n"}, "How many participants"), count),
    h("div", {class: "field"}, h("label", {for: "sd-first"}, "First ID"), start, h("div", {class: "help"}, "Empty: the next number after every ID that has data or is planned.")),
    h("div", {class: "field"}, h("label", {for: "sd-ses"}, "Session"), ses),
    h("div", {class: "field"}, h("label", {for: "sd-groups"}, "Groups (counterbalancing)"), groups,
      h("div", {class: "help"}, "Given in turn: A, B, A, B… Each session gets the participant field “group”, which the experiment can use as $group.")));
  const ok = await ui.dialog({title: "Plan participants", icon: "person", size: "sm", body, initialFocus: count,
    buttons: [{label: "Cancel", value: false}, {label: "Add to the list", value: true, kind: "primary"}]});
  if (ok !== true) return;
  const n = parseInt(count.value, 10);
  if (!(n > 0)) { toast("Type how many participants to plan."); return; }
  const res = await sdQueueOp("add", {count: n, start: start.value.trim() || null, session: ses.value.trim() || "1",
    groups: groups.value.split(/[,;]/).map((g) => g.trim()).filter(Boolean)});
  if (res) ui.announce(`${countWord(res.added?.length || n, "participant")} added to the list.`);
}
async function sdGroupsDialog() {
  const v = await ui.prompt({title: "Groups for counterbalancing", label: "Groups, in the order they are given out", value: (SD.queue?.groups || []).join(", "),
    help: "Participants planned from now on get them in turn. Already planned participants keep theirs (change them in the list).", ok: "Save"});
  if (v === null) return;
  sdQueueOp("groups", {groups: v.split(/[,;]/).map((g) => g.trim()).filter(Boolean)});
}
function sdImport() {
  const inp = h("input", {type: "file", accept: ".csv,.tsv,.txt,text/csv", style: "display:none"});
  inp.addEventListener("change", async () => {
    const f = inp.files?.[0]; inp.remove();
    if (!f) return;
    const text = await f.text();
    let replace = false;
    if ((SD.queue?.entries || []).length) {
      const v = await ui.dialog({title: "Import the list", size: "sm", body: `${f.name}: add its participants to the list, or replace the list with it?`,
        buttons: [{label: "Cancel", value: null}, {label: "Replace the list", value: "replace"}, {label: "Add", value: "add", kind: "primary"}]});
      if (!v) return;
      replace = v === "replace";
    }
    const res = await sdQueueOp("import", {csv: text, replace});
    if (res) toast(`Imported: ${countWord(res.added, "new participant")}${res.updated ? `, ${res.updated} updated` : ""}.`, {tone: "success"});
  });
  document.body.append(inp); inp.click();
}
function sdExport() {
  const a = h("a", {href: `/api/studyday/export?path=${encodeURIComponent(S.path)}`, download: ""});
  document.body.append(a); a.click(); a.remove();
}
async function sdNoShow(e) {
  const why = await ui.prompt({title: `Participant ${e.participant} didn't come`, label: "Note (optional)", placeholder: "e.g. cancelled by e-mail", ok: "Mark as no-show"});
  if (why === null) return;
  try { SD.queue = await sdApi("/api/studyday/noshow", {path: S.path, id: e.id, reason: why}); sdDrawQueue(); }
  catch (err) { toast(err.message, {tone: "danger"}); }
}

/* Start a queue entry: saves first (like Start session), then the run page follows it as usual. */
async function sdStart(e) {
  if (S.run?.running) { toast("A session is recording: start the next one when it has ended."); return; }
  if (S.proposal) { toast("Apply or discard the assistant's changes first"); return; }
  const errors = (S.issues || []).filter((i) => i.level === "error");
  if (errors.length) { if (typeof openProblems === "function") openProblems({reason: `Can't start yet: ${countWord(errors.length, "thing")} to fix.`}); return; }
  if (!S.path || S.dirty) { if (!(await save())) return; }
  const F = (typeof RUN !== "undefined" && RUN.form && RUN.form.path === S.path) ? RUN.form : {simulate: false, fullscreen: !!S.exp.settings?.window?.fullscreen};
  let res;
  try { res = await sdApi("/api/studyday/start", {path: S.path, id: e.id, simulate: !!F.simulate, fullscreen: F.fullscreen !== false, mirror: !!SD.mirror}); }
  catch (err) { toast(`The session couldn't start: ${err.message}`, {tone: "danger", ms: 8000}); sdLoadQueue(true).then(sdDrawQueue); return; }
  S.run = {id: res.run_id, path: S.path, participant: res.participant, session: res.session, startedAt: Date.now(), running: true, simulate: !!F.simulate, mirror: !!SD.mirror, entry: res.entry};
  if (typeof RUN !== "undefined") { RUN.status = null; RUN.mon = null; RUN.key = ""; }
  SD.notes = []; SD.notesRun = res.run_id; SD.queue = null;
  ui.announce(`Recording participant ${res.participant}, session ${res.session}.`, {assertive: true});
  EDGE.emit("run", S.run);
  if (S.ws !== "run") EDGE.go("run"); else sdRefresh();
}

/* ================================================================== during the session */
function consoleLivePanel() {
  const r = S.run;
  SD.notesRun = r.id;
  const now = h("div", {class: "sd-now", id: "sd-now", role: "status", "aria-live": "polite"}, h("span", {class: "t-2"}, "Starting…"));
  const pause = h("button", {type: "button", class: "btn", id: "sd-pause", "data-fkey": "sd:pause", onclick: () => sdPause()}, icon("pause"), "Pause");
  const win = CONSOLE_MODE ? null : h("button", {type: "button", class: "btn ghost", "data-fkey": "sd:window", onclick: () => openExperimenterWindow(),
    "data-tip": "Opens this console in its own window, on the monitor the participant doesn't see"}, icon("external"), "Experimenter window");
  const quality = h("section", {class: "mon-sec sd-quality", "aria-label": "Signal quality"}, h("h3", {class: "t-small mon-h"}, "Signal quality"),
    h("div", {id: "sd-qbody"}, h("p", {class: "t-small t-2"}, "Waiting for the devices…")));
  const mirror = r.mirror ? h("section", {class: "mon-sec sd-mirrorbox", "aria-label": "The participant's screen"}, h("h3", {class: "t-small mon-h"}, "The participant's screen"),
    h("img", {id: "sd-mirror", alt: "A small copy of the participant's screen, updated every 2 seconds", width: "320"}),
    h("p", {class: "t-caption"}, "Updated every 2 s.")) : null;
  const notes = notesPanel({run: r.id});
  return h("div", {class: "sd-live"},
    h("div", {class: "sd-bar"}, now, h("span", {class: "grow"}), pause, win),
    h("div", {class: "sd-livegrid"}, h("div", {class: "sd-col"}, quality, mirror), notes));
}
function consoleLiveUpdate(st) {
  const M = st.monitor || {};
  if (st.mirror && S.run && !S.run.mirror) { S.run.mirror = true; if (typeof RUN !== "undefined") RUN.key = ""; sdRefresh(); return; }
  const box = document.getElementById("sd-now");
  if (box) {
    const exp = M.start?.expected_trials, n = M.end?.trials ?? M.last?.n ?? 0;
    const scr = M.screen?.routine || M.last?.routine;
    const paused = !!M.paused, pausing = !!st.pausing;
    const bits = [];
    if (!M.start) bits.push(h("span", {class: "t-2"}, "Starting: opening the window and connecting devices…"));
    else {
      bits.push(h("span", {class: "sd-k"}, "Screen"), h("b", {}, scr ? `“${scr}”` : "–"));
      bits.push(h("span", {class: "sd-k"}, "Trial"), h("b", {}, `${n}${exp ? ` of about ${exp}` : ""}`));
      if (paused) bits.push(h("span", {class: "chip warning"}, icon("pause"), M.paused.before ? `Paused before “${M.paused.before}”` : "Paused"));
      else if (pausing) bits.push(h("span", {class: "chip outline"}, "Pausing at the next screen…"));
      const lr = M.last_response?.responses || {};
      const resp = Object.entries(lr).filter(([, v]) => v !== null && v !== "").slice(0, 3)
        .map(([k, v]) => (k.endsWith(".rt") && typeof v === "number" ? `${Math.round(v * 1000)} ms` : k.endsWith(".corr") ? (v ? "correct" : "wrong") : String(v)));
      if (resp.length) bits.push(h("span", {class: "sd-k"}, "Last"), h("span", {}, resp.join(" · ")));
    }
    box.replaceChildren(...bits);
    const pb = document.getElementById("sd-pause");
    if (pb) {
      const on = paused || pausing;
      pb.replaceChildren(icon(on ? "play" : "pause"), on ? "Resume" : "Pause");
      pb.disabled = !M.start || !!st.stopping;
      pb.dataset.on = on ? "1" : "";
    }
  }
  const qb = document.getElementById("sd-qbody");
  if (qb) qb.replaceChildren(...qualityView(M.quality?.devices, M.start?.devices));
  const img = document.getElementById("sd-mirror");
  if (img && M.mirror && M.mirror.elapsed !== SD.mirrorT) { SD.mirrorT = M.mirror.elapsed; img.src = `/api/studyday/mirror?id=${encodeURIComponent(S.run.id)}&t=${Date.now()}`; }
  if ((st.notes || 0) !== SD.notes.length && !SD.notesBusy) notesReload();
}

async function sdPause() {
  if (!S.run?.running) return;
  const b = document.getElementById("sd-pause");
  const resume = b?.dataset.on === "1";
  try { await sdApi("/api/studyday/pause", {id: S.run.id, pause: !resume}); if (b) b.dataset.on = resume ? "" : "1"; }
  catch (e) { toast(`Couldn't ${resume ? "resume" : "pause"}: ${e.message}`, {tone: "danger"}); }
  ui.announce(resume ? "Resuming." : "Pausing before the next screen.");
}

/* Stop with a reason: the reason goes into the notes, the queue and the run log. */
async function studyStop() {
  if (!S.run?.running) return;
  const reasons = ["Participant asked to stop", "Equipment problem", "Participant unwell", "Wrong participant or settings"];
  const input = h("input", {class: "input", id: "sd-why", placeholder: "Why? (optional)", autocomplete: "off"});
  const chips = h("div", {class: "sd-reasons"}, reasons.map((r) => h("button", {type: "button", class: "chip outline", onclick: () => { input.value = r; input.focus(); }}, r)));
  const ok = await ui.dialog({title: "Stop this session?", size: "sm", initialFocus: input,
    body: h("div", {}, h("p", {class: "t-small"}, "Everything recorded so far is kept. The participant is marked “stopped early” in the list."),
      h("div", {class: "field"}, h("label", {for: "sd-why"}, "Reason"), input), chips),
    buttons: [{label: "Keep running", value: false}, {label: "Stop session", value: true, kind: "danger"}]});
  if (ok !== true || !S.run?.running) return;
  const b = document.querySelector(".run-stopbtn");
  if (b) { b.disabled = true; b.replaceChildren(h("span", {class: "spin"}), "Stopping…"); }
  try { await sdApi("/api/studyday/stop", {id: S.run.id, reason: input.value.trim()}); notesReload(); }
  catch (e) { toast(`Couldn't stop it: ${e.message}`, {tone: "danger"}); }
}

/* ================================================================== signal quality */
const Q_WORD = {ok: "good", warn: "check", bad: "bad", wait: "waiting"};
function qualityView(devs, started) {
  const out = [];
  const entries = Object.entries(devs || {});
  if (!entries.length) {
    const any = Object.values(started || {}).some((d) => Object.values(d.streams || {}).some((s) => s.srate));
    out.push(h("p", {class: "t-small t-2"}, any ? "Measuring… (every 2 s)" : "No device records a signal in this experiment."));
    return out;
  }
  for (const [did, d] of entries) for (const [sname, q] of Object.entries(d.streams || {})) out.push(qualityStream(`${did}.${sname}`, q));
  return out;
}
function qualityStream(label, q) {
  const wrap = h("div", {class: "q-stream"});
  if (q.kind === "gaze") {
    const st = q.status || "wait";
    put(wrap, h("div", {class: "q-head"}, h("b", {}, label), h("span", {class: `q-pill q-${st}`}, Q_WORD[st] || st)),
      h("div", {class: "q-gaze"},
        qTile("Valid", q.validity_pct != null ? `${Math.round(q.validity_pct)} %` : "–", q.validity_pct == null ? "wait" : q.validity_pct < 60 ? "bad" : q.validity_pct < 85 ? "warn" : "ok"),
        q.left_pct != null ? qTile("Left eye", `${Math.round(q.left_pct)} %`, q.left_pct < 60 ? "bad" : q.left_pct < 85 ? "warn" : "ok") : null,
        q.right_pct != null ? qTile("Right eye", `${Math.round(q.right_pct)} %`, q.right_pct < 60 ? "bad" : q.right_pct < 85 ? "warn" : "ok") : null,
        q.pupil_pct != null ? qTile("Pupil", `${Math.round(q.pupil_pct)} %`, q.pupil_pct < 60 ? "bad" : q.pupil_pct < 85 ? "warn" : "ok") : null,
        qTile("Losses", `${q.losses ?? 0}`, (q.longest_loss_s || 0) >= 1 ? "warn" : "ok", q.longest_loss_s != null ? `longest ${q.longest_loss_s} s` : "")),
      (q.reasons || []).length ? h("p", {class: "t-caption q-why"}, q.reasons.join("; ")) : null);
    return wrap;
  }
  if (q.kind !== "signal") { wrap.append(h("p", {class: "t-caption"}, `${label}: ${(q.reasons || []).join("; ") || "no quality measure"}`)); return wrap; }
  const c = q.counts || {};
  const imp = q.impedance || {};
  wrap.append(h("div", {class: "q-head"}, h("b", {}, label),
    h("span", {class: "t-caption"}, `${c.ok || 0} good · ${c.warn || 0} to check · ${c.bad || 0} bad`),
    h("span", {class: "grow"}),
    imp.applies === false ? null : h("span", {class: "t-caption q-imp"}, imp.available ? "impedance in kΩ" : `impedance: ${imp.note || "not available from this device"}`)));
  const grid = h("div", {class: "q-grid", role: "list", "aria-label": `${label} channels`});
  for (const ch of q.channels || []) {
    const st = ch.status || "wait";
    const nums = st === "wait" ? "…" : `${fmtQ(ch.rms)} ${q.units || ""}`.trim();
    const line = ch.line_uv != null && st !== "wait" ? `${ch.line_hz} Hz ${fmtQ(ch.line_uv)}` : "";
    const tip = [`${ch.name}: ${Q_WORD[st] || st}`, ...(ch.reasons || []), ch.rms != null ? `RMS ${ch.rms} ${q.units || ""}` : null,
      ch.line_uv != null ? `${ch.line_hz} Hz: ${ch.line_uv} (${Math.round((ch.line_ratio || 0) * 100)} % of the power)` : null,
      ch.clipped ? `${Math.round(ch.clipped * 100)} % at the limit` : null, ch.impedance_kohm != null ? `impedance ${ch.impedance_kohm} kΩ` : null].filter(Boolean).join("\n");
    grid.append(h("div", {class: `q-ch q-${st}`, role: "listitem", "data-tip": tip, tabindex: "0", "aria-label": tip.replace(/\n/g, ". ")},
      h("b", {class: "q-name"}, ch.name), h("span", {class: "q-num"}, nums), line ? h("span", {class: "q-sub"}, line) : null,
      ch.impedance_kohm != null ? h("span", {class: "q-sub"}, `${fmtQ(ch.impedance_kohm)} kΩ`) : null));
  }
  wrap.append(grid);
  return wrap;
}
const qTile = (k, v, st, sub = "") => h("div", {class: `q-ch q-${st}`}, h("b", {class: "q-name"}, k), h("span", {class: "q-num"}, v), sub ? h("span", {class: "q-sub"}, sub) : null);
const fmtQ = (v) => (v == null ? "–" : Math.abs(v) >= 100 ? String(Math.round(v)) : Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(1));

/* ================================================================== notes (during, after, on the Data page) */
function notesPanel(target) {
  const list = h("ol", {class: "sd-notes", id: "sd-notelist", "aria-label": "Notes"});
  const ta = h("textarea", {class: "input sd-notein", id: "sd-notein", rows: "2", placeholder: "A note on this session (Enter adds it)", "data-fkey": "sd:note",
    onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); add(); } }});
  const add = async () => {
    const text = ta.value.trim();
    if (!text) return;
    SD.notesBusy = true;
    try { const r = await sdApi("/api/studyday/notes", {...target, op: "add", text}); SD.notes = r.notes || []; ta.value = ""; drawNotes(list, target); }
    catch (e) { toast(`The note wasn't saved: ${e.message}`, {tone: "danger"}); }
    finally { SD.notesBusy = false; }
  };
  const box = h("section", {class: "mon-sec sd-notesbox", "aria-labelledby": "sd-notes-h"},
    h("h3", {class: "t-small mon-h", id: "sd-notes-h"}, "Notes"),
    h("div", {class: "sd-noteadd"}, ta, h("button", {type: "button", class: "btn sm", onclick: add}, icon("plus"), "Add")),
    target.run && S.run?.running && (S.exp?.settings?.window?.keep_focus ?? true) ? h("p", {class: "t-caption"},
      "On the computer that shows the experiment, the experiment window takes the keyboard back while it runs: press Pause to type a longer note, then Resume.") : null,
    list,
    h("p", {class: "t-caption"}, "Saved in the session folder (notes.md) and shown in Data and in exports."));
  SD.notesTarget = target;
  SD.notes = [];
  notesReload(list, target);
  return box;
}
async function notesReload(list, target) {
  target = target || SD.notesTarget; list = list || document.getElementById("sd-notelist");
  if (!target || !list) return;
  const q = target.run ? `run=${encodeURIComponent(target.run)}` : `session=${encodeURIComponent(target.session)}`;
  try { SD.notes = (await sdApi(`/api/studyday/notes?${q}`)).notes || []; } catch { return; }
  drawNotes(list, target);
}
function drawNotes(list, target) {
  if (!list) return;
  list.replaceChildren(...(SD.notes.length ? SD.notes.map((n, i) => noteItem(n, i, list, target))
    : [h("li", {class: "t-caption sd-nonote"}, "No notes yet.")]));
}
function noteItem(n, i, list, target) {
  const el = n.elapsed != null ? ` +${Math.floor(n.elapsed / 60)}:${String(Math.round(n.elapsed % 60) % 60).padStart(2, "0")}` : "";
  const text = h("span", {class: "sd-ntext"}, n.text);
  const li = h("li", {class: "sd-note" + (n.auto ? " auto" : "")}, h("span", {class: "mono t-2 sd-ntime"}, clock(n.time) + el), text,
    n.edited ? h("span", {class: "t-caption"}, " (edited)") : null,
    h("span", {class: "grow"}),
    h("button", {type: "button", class: "btn sm ghost icon", "aria-label": "Change this note", "data-tip": "Change", onclick: async () => {
      const v = await ui.prompt({title: "Change the note", label: `Note from ${clock(n.time)}`, value: n.text, ok: "Save"});
      if (v === null) return;
      try { SD.notes = (await sdApi("/api/studyday/notes", {...target, op: "edit", index: i, text: v})).notes; drawNotes(list, target); }
      catch (e) { toast(e.message, {tone: "danger"}); }
    }}, icon("text")),
    h("button", {type: "button", class: "btn sm ghost icon", "aria-label": "Delete this note", "data-tip": "Delete", onclick: async () => {
      if (!(await ui.confirm({title: "Delete this note?", message: n.text, ok: "Delete", danger: true}))) return;
      try { SD.notes = (await sdApi("/api/studyday/notes", {...target, op: "delete", index: i})).notes; drawNotes(list, target); }
      catch (e) { toast(e.message, {tone: "danger"}); }
    }}, icon("trash")));
  return li;
}
/* Data page: the notes of the selected session (only real sessions: test runs have none). */
function sessionNotesBox(rel) {
  return h("div", {class: "sd-datanotes"}, notesPanel({session: rel}));
}

/* ================================================================== the second monitor */
async function sdScreens() {
  if (SD.screens) return SD.screens;
  try { SD.screens = (await sdApi("/api/studyday/screens")).screens || []; } catch { SD.screens = []; }
  return SD.screens;
}
/* The experimenter window: this console in its own browser window, placed on a monitor the participant's
 * window doesn't use (Chrome/Edge can place it there with the Window Management permission; elsewhere drag it). */
async function openExperimenterWindow() {
  const url = `${location.origin}/?console=1&path=${encodeURIComponent(S.path || "")}#/run`;
  const pIdx = +(S.exp?.settings?.window?.screen ?? 0) || 0;
  let feat = "popup,width=1100,height=800";
  let placed = false;
  try {
    if ("getScreenDetails" in window) {
      const det = await window.getScreenDetails();
      const scr = await sdScreens();
      const part = scr[pIdx];
      // the browser's screens are in CSS pixels, EDGE's in device pixels: match by position, then by order
      const same = (s) => part && Math.abs(s.left * (s.devicePixelRatio || 1) - part.x) < 8 && Math.abs(s.top * (s.devicePixelRatio || 1) - (part.y ?? s.top)) < 8;
      const other = part ? det.screens.find((s) => !same(s)) : det.screens.find((s, i) => i !== pIdx);
      if (other && det.screens.length > 1) {
        feat = `popup,left=${other.availLeft},top=${other.availTop},width=${Math.min(other.availWidth, 1400)},height=${other.availHeight}`;
        placed = true;
      }
    }
  } catch { /* permission refused or not supported: a normal window */ }
  const w = window.open(url, "edge-experimenter", feat);
  if (!w) { toast("The browser blocked the new window: allow pop-ups for the builder, or open the Run page in another window yourself.", {tone: "warning", ms: 8000}); return; }
  if (!placed) toast("Drag the experimenter window to the monitor the participant doesn't see.", {ms: 7000});
}

/* Which monitor shows the participant's window (settings.window.screen), with the real monitors listed. */
function participantScreenField() {
  const box = h("div", {class: "field sd-screen"});
  const draw = (scr) => {
    const cur = +(S.exp.settings?.window?.screen ?? 0) || 0;
    const opts = (scr.length ? scr : [{}]).map((s, i) => h("option", {value: i, selected: i === cur ? "" : null},
      `${i === 0 ? "Main (1)" : `Monitor ${i + 1}`}${s.width ? ` · ${s.width}×${s.height}` : ""}${s.rate ? ` · ${Math.round(s.rate)} Hz` : ""}`));
    if (cur >= opts.length) opts.push(h("option", {value: cur, selected: ""}, `Monitor ${cur + 1} (not connected now)`));
    const sel = h("select", {class: "input", id: "sd-scr", "data-fkey": "sd:screen", onchange: (e) => {
      S.exp.settings = S.exp.settings || {}; S.exp.settings.window = {...(S.exp.settings.window || {})};
      const v = +e.target.value;
      if (v) S.exp.settings.window.screen = v; else delete S.exp.settings.window.screen;
      commit("Choose the participant's monitor", false);
      sdRefresh();
    }}, opts);
    box.replaceChildren(h("label", {for: "sd-scr"}, "Participant's monitor"), sel,
      h("div", {class: "help"}, scr.length > 1 ? "The experiment opens on this monitor. Open the experimenter window on the other one once the session runs."
        : "One monitor found. With a second monitor, the experimenter can watch this page while the participant sees only the experiment."));
  };
  draw(SD.screens || []);
  sdScreens().then(draw);
  return box;
}

/* ================================================================== the experimenter window (?console=1) */
if (CONSOLE_MODE) {
  document.documentElement.classList.add("console-mode");
  document.title = "EDGE experimenter";
  EDGE.on("app:ready", async () => {
    const want = new URLSearchParams(location.search).get("path");
    if (want && want !== S.path && typeof openFile === "function") { try { await openFile(want); } catch { /* stays on what is open */ } }
    EDGE.go("run");
    sdFollowRuns();
    setInterval(sdFollowRuns, 2000);
  });
}
/* The experimenter window follows every session of this experiment, also those started in the main window. */
async function sdFollowRuns() {
  if (S.run?.running) { if (S.ws === "run" && runPhase() === "live" && !document.querySelector(".run-live")) sdRefresh(); return; }
  if (!S.path) return;
  let runs = [];
  try { runs = (await api("/api/runs")).runs || []; } catch { return; }
  const r = runs.find((x) => x.running && x.path === S.path);
  if (!r || S.run?.id === r.run_id) return;
  S.run = {id: r.run_id, path: r.path, participant: r.participant, session: r.session, startedAt: Date.parse(r.started) || Date.now(), running: true, mirror: !!r.mirror};
  if (typeof RUN !== "undefined") { RUN.status = null; RUN.mon = null; RUN.key = ""; }
  EDGE.emit("run", S.run);
  if (S.ws !== "run") EDGE.go("run"); else sdRefresh();
}
EDGE.on("doc:loaded", () => { SD.queue = null; SD.qKey = ""; });
EDGE.on("run", (r) => {
  if (!r || !r.running) SD.queue = null;
  // the experimenter window: a session found again after loading (or started in the main window) shows at once
  if (CONSOLE_MODE && r?.running && S.ws === "run" && typeof runPhase === "function" && runPhase() === "live" && !document.querySelector(".run-live")) setTimeout(sdRefresh, 0);
});
