/* hardware.js: plug and play in the builder. Owner: plug and play.
 * The server watches the USB/serial ports, LSL streams, gamepads, microphones, monitors and eye trackers
 * (edge/hotplug.py, identified with edge/hardware_db.py) and this page long-polls /api/hardware/events for
 * "connected" / "disconnected" events. A recognised device gets a notice: "Cedrus RB-840 response pad connected —
 * Add to this experiment" (or "Add as …" choices when it could be several things). Adding it creates the device
 * with the right options, optionally a matching response item on the current screen, or a setting (a second
 * monitor becomes the participant's monitor), all as one undoable step. The Devices tab shows whether each of the
 * experiment's devices is connected now (hwStatusChip, used by deviceCard in build.js), and unplugging one of them
 * shows a warning. Preference: "Add recognised devices automatically" (EDGE.prefs hardware.autoAdd, off).
 * Loaded after build.js; uses its globals (S, h, icon, btn, commit, uniqueId, comps, renderDevices …). */
"use strict";

const HW = {since: null, items: [], status: {}, polling: false, seq: 0, errors: 0, notices: new Map(), statusKey: "", statusBusy: false};
const HW_ICON = {serial: "chip", lsl: "eeg", gamepad: "gamepad", audio: "microphone", monitor: "screen", tobii: "eyetracker",
  gazepoint: "eyetracker", labjack: "trigger", parallel: "trigger"};

/* ---------------------------------------------------------------- the event loop (long poll) */
async function hwStart() {
  if (HW.polling) return;
  HW.polling = true;
  while (HW.polling) {
    try {
      const url = HW.since === null ? "/api/hardware/events" : `/api/hardware/events?since=${HW.since}&wait=20`;
      const r = await api(url);
      HW.errors = 0;
      HW.items = r.connected || [];
      HW.portsSeen = r.ports_seen || {};
      const first = HW.since === null;
      HW.since = r.seq;
      if (first) { hwRefreshStatus(true); continue; }
      if ((r.events || []).length) await hwOnEvents(r.events);
    } catch (e) {
      HW.errors++;
      await new Promise((ok) => setTimeout(ok, Math.min(30000, 2000 * HW.errors)));
    }
  }
}
function hwStop() { HW.polling = false; }

const hwDocOpen = () => !!(S.exp && !S.noDoc);
const hwName = (it) => (it.identified || {}).name || it.label || it.name || it.port || "A device";
const hwWhere = (it) => [it.where || it.port || "", it.vid ? `USB ${it.vid}:${it.pid || ""}` : ""].filter(Boolean).join(" · ");
const hwSureWord = (it) => ((it.identified || {}).certainty === "probably" ? "Probably " : "");

/* Which experiment device (id) uses this connected item, from the last status answer. */
function hwUsedBy(it) {
  for (const [did, st] of Object.entries(HW.status || {})) if (st.item === it.id && (st.state === "connected" || st.state === "moved")) return did;
  if (!hwDocOpen()) return null;
  const all = Object.values(S.exp.routines || {}).flatMap((r) => r.components || []);
  if (it.kind === "gamepad" && all.some((c) => c.type === "gamepad")) return "a Gamepad item";
  if (it.kind === "audio" && all.some((c) => c.type === "microphone" && (c.device || "") === it.name)) return "a Voice recording item";
  if (it.kind === "monitor" && +(S.exp.settings?.window?.screen ?? 0) === +it.index) return "the participant's monitor";
  return null;
}

async function hwOnEvents(events) {
  const before = {...HW.status};
  await hwRefreshStatus(true);
  for (const ev of events) {
    const it = ev.item || {};
    if (ev.event === "connected") {
      hwDismiss("gone:" + it.id);
      for (const [k, n] of HW.notices) if (k.startsWith("gone:") && n.item && n.item.id === it.id) hwDismiss(k);
      const moved = Object.entries(HW.status).find(([, st]) => st.item === it.id && st.state === "moved");
      if (moved && hwDocOpen()) { hwMovedNotice(it, moved[0], ev.was_port); continue; }
      const back = Object.entries(before).find(([did, st]) => st.state === "missing" && HW.status[did]?.item === it.id);
      if (back) { toast(`${hwName(it)} is connected again (“${back[0]}”).`, {tone: "success"}); continue; }
      if (hwUsedBy(it)) continue;
      const offers = (it.identified || {}).offers || [];
      if (hwDocOpen() && EDGE.prefs.get("hardware.autoAdd", false) && (it.identified || {}).certainty !== "ask" && offers[0]?.device) {
        hwApply(it, offers[0], false, {auto: true});
        continue;
      }
      hwConnectedNotice(it);
    } else if (ev.event === "disconnected") {
      hwDismiss("new:" + it.id);
      const lost = Object.entries(before).filter(([did, st]) => st.item === it.id && (st.state === "connected" || st.state === "moved")
        && HW.status[did]?.state !== "connected" && HW.status[did]?.state !== "moved");
      if (lost.length && hwDocOpen()) hwGoneNotice(it, lost.map(([did]) => did));
      else ui.announce(`${hwName(it)} was unplugged.`);
    }
  }
  if (S.view === "hardware" || document.querySelector("#tab-hardware .scan-row")) { /* the Find devices list is a snapshot: refresh it */
    const el = $("#tab-hardware"); if (el && el.querySelector(".scan-row, #scan-found") && typeof scanHardware === "function") scanHardware(el, {quiet: true});
  }
}

/* ---------------------------------------------------------------- the experiment's devices: connected now? */
async function hwRefreshStatus(force = false) {
  if (!hwDocOpen()) { HW.status = {}; return; }
  const devs = (S.exp.devices || []).map((d) => ({id: d.id, type: d.type, options: d.options || {}}));
  const key = JSON.stringify(devs) + "@" + HW.since;
  if (!force && key === HW.statusKey) return;
  HW.statusKey = key;
  if (!devs.length) { HW.status = {}; return; }
  try {
    const r = await api("/api/hardware/status", {devices: devs});
    HW.status = r.status || {};
  } catch { return; }
  if (typeof renderDevices === "function") renderDevices();
}
/* The chip on a device card in the Devices tab (build.js deviceCard). */
function hwStatusChip(d) {
  const st = HW.status?.[d.id];
  if (!st || st.state === "unknown") return null;
  if (st.state === "connected") return h("span", {class: "chip success hw-chip", title: st.detail || "", "data-hw-state": "connected"}, h("span", {class: "dot"}), "Connected");
  if (st.state === "moved") return h("span", {class: "chip warning hw-chip", title: `It is plugged into another socket: ${st.detail}`, "data-hw-state": "moved"}, h("span", {class: "dot"}), `On ${st.port_now} now`);
  // an optional device (required: false) that isn't there is normal: shown plainly, not as a problem
  return h("span", {class: "chip hw-chip" + (d.required === false ? " outline" : " danger"), title: st.detail || "", "data-hw-state": "missing"},
    h("span", {class: "dot" + (d.required === false ? " dot-off" : "")}), "Not connected");
}

/* ---------------------------------------------------------------- notices */
function hwHost() {
  let host = document.getElementById("hw-notices");
  if (!host) { host = h("div", {id: "hw-notices", role: "region", "aria-label": "Devices plugged in or out", "aria-live": "polite"}); document.body.append(host); }
  return host;
}
function hwDismiss(key) {
  const n = HW.notices.get(key);
  if (n) { n.el.remove(); HW.notices.delete(key); }
}
function hwNotice(key, {tone = "", icon: ic = "chip", title, sub, body = [], actions = [], item = null}) {
  hwDismiss(key);
  const close = iconBtn("close", "Dismiss", () => hwDismiss(key), "btn ghost icon sm hw-x");
  const el = h("div", {class: "hw-notice" + (tone ? " " + tone : ""), role: tone === "warning" ? "alert" : "status", "data-hw": key},
    h("span", {class: "tile tint-hw", "aria-hidden": "true"}, icon(ic, "m")),
    h("div", {class: "hw-body"}, h("b", {class: "hw-title"}, title), sub ? h("div", {class: "hw-sub t-caption"}, sub) : null, ...body,
      actions.length ? h("div", {class: "hw-acts"}, ...actions) : null),
    close);
  hwHost().append(el);
  HW.notices.set(key, {el, item});
  while (HW.notices.size > 4) hwDismiss(HW.notices.keys().next().value);
  return el;
}

function hwTargetScreen() {
  if (!hwDocOpen()) return null;
  if (S.view === "screen" && S.routine && S.exp.routines?.[S.routine]) return S.routine;     // the screen being edited
  // otherwise the screen where the participant answers (a response with a correct answer first: the trial screen)
  const order = typeof routineInFlowOrder === "function" ? routineInFlowOrder() : Object.keys(S.exp.routines || {});
  const isResp = (c) => S.schema?.components?.[c.type]?.category === "response";
  const score = (rid) => Math.max(0, ...comps(rid).map((c) => (isResp(c) ? 1 + (c.correct != null && c.correct !== "" ? 2 : 0) : 0)));
  let best = order[0] || null, top = -1;
  for (const rid of order) { const s = score(rid); if (s > top) { best = rid; top = s; } }
  return best;
}
const hwOfferWords = (o) => o.label;

function hwConnectedNotice(it) {
  const ident = it.identified || {};
  const offers = ident.offers || [];
  const name = hwName(it);
  const title = `${name} connected`;
  const sub = [ident.certainty === "probably" ? "probably" : "", hwWhere(it)].filter(Boolean).join(" · ");
  const body = [], actions = [];
  if (!hwDocOpen()) {
    body.push(h("p", {class: "t-small"}, "Open an experiment to add it."));
    return hwNotice("new:" + it.id, {icon: HW_ICON[it.kind] || "chip", title, sub, body, item: it});
  }
  if (!offers.length) {
    body.push(h("p", {class: "t-small"}, it.kind === "monitor" ? "The main monitor: nothing to add." : "Nothing to add for it."));
    return hwNotice("new:" + it.id, {icon: HW_ICON[it.kind] || "chip", title, sub, body, item: it});
  }
  const rid = hwTargetScreen();
  // "also add a response item" (when the offer has one and also adds a device)
  const also = h("input", {type: "checkbox", id: "hw-also-" + HW.seq, checked: ""});
  const alsoRow = h("label", {class: "hw-also t-small", for: also.id}, also, h("span", {class: "hw-also-txt"}));
  const setAlso = (o) => {
    const show = !!(o && o.device && o.item && rid);
    alsoRow.hidden = !show;
    if (show) alsoRow.querySelector(".hw-also-txt").textContent = ` Also add a “${o.item.label || o.item.type}” item to the screen “${rid}”`;
  };
  HW.seq++;
  if (ident.certainty === "ask") {
    body.push(h("p", {class: "t-small hw-q"}, ident.question || "What is it?"));
    const list = h("div", {class: "hw-choices"});
    offers.forEach((o) => list.append(btn(`Add as ${o.label.charAt(0).toLowerCase() + o.label.slice(1)}`, () => hwApply(it, o, also.checked && !alsoRow.hidden, {notice: "new:" + it.id}),
      {cls: "btn sm hw-choice", title: o.summary || ""})));
    body.push(list);
    setAlso(offers.find((o) => o.device && o.item));
    alsoRow.querySelector(".hw-also-txt").textContent = rid ? ` Also add a response item to the screen “${rid}” (for a button box)` : "";
    alsoRow.hidden = !rid || !offers.some((o) => o.device && o.item);
    body.push(alsoRow);
  } else {
    const main = offers[0];
    const as = main.device ? `As: ${main.label.charAt(0).toLowerCase() + main.label.slice(1)}${main.device.options?.port ? ` on ${main.device.options.port}` : ""}` : "";
    const what = [as, main.summary].filter(Boolean).join(". ");
    if (what) body.push(h("p", {class: "t-caption hw-as"}, what.charAt(0).toUpperCase() + what.slice(1)));
    setAlso(main);
    body.push(alsoRow);
    actions.push(btn(hwAddLabel(main), () => hwApply(it, main, also.checked && !alsoRow.hidden, {notice: "new:" + it.id}),
      {cls: "btn sm primary hw-add", title: main.label}));
    if (offers.length > 1) actions.push(btn("Add as…", (e) => ui.menu(e.currentTarget, offers.slice(1).map((o) => ({label: hwOfferWords(o), icon: "plus",
      run: () => hwApply(it, o, also.checked && !alsoRow.hidden, {notice: "new:" + it.id})}))), {cls: "btn sm hw-more"}));
  }
  if (ident.identify === "cedrus") actions.push(btn("Identify", (e) => hwIdentify(it, e.currentTarget), {cls: "btn sm ghost hw-identify",
    title: "Ask the box what it is (Cedrus's read-only query commands)"}));
  actions.push(btn("Not now", () => hwDismiss("new:" + it.id), {cls: "btn sm ghost"}));
  hwNotice("new:" + it.id, {icon: HW_ICON[it.kind] || "chip", title, sub, body, actions, item: it});
}
function hwAddLabel(o) {
  if (o.setting) return o.label;
  if (!o.device && o.item) return `Add a ${o.item.label || o.item.type} item`;
  return "Add to this experiment";
}

function hwGoneNotice(it, dids) {
  const list = dids.map((d) => `“${d}”`).join(", ");
  const live = S.run?.running ? " A session is running: its responses or triggers are lost until it is plugged in again." : " Plug it back in before you start a session.";
  hwNotice("gone:" + it.id, {tone: "warning", icon: "warning", title: `${hwName(it)} was unplugged`,
    sub: hwWhere(it), body: [h("p", {class: "t-small"}, `The experiment uses it as ${list}.${live}`)], item: it});
  ui.announce(`${hwName(it)} was unplugged. The experiment uses it as ${list}.`, {assertive: true});
}

function hwMovedNotice(it, did, was) {
  const d = S.exp.devices.find((x) => x.id === did); if (!d) return;
  hwNotice("new:" + it.id, {icon: HW_ICON[it.kind] || "chip", title: `${hwName(it)} is on ${it.port} now`,
    sub: `“${did}” is set to ${d.options?.port || was || "another port"}`,
    body: [h("p", {class: "t-small"}, "It was plugged into another USB socket, so it got another port name.")],
    actions: [btn(`Use ${it.port}`, () => {
      if (!bEditable()) return;
      d.options = {...(d.options || {}), port: it.port};
      commit(`Use ${it.port} for “${did}”`);
      hwDismiss("new:" + it.id); hwRefreshStatus(true);
    }, {cls: "btn sm primary"}), btn("Not now", () => hwDismiss("new:" + it.id), {cls: "btn sm ghost"})], item: it});
}

async function hwIdentify(it, b) {
  b.disabled = true;
  try {
    const r = await api("/api/hardware/identify", {id: it.id});
    if (!r.ok) toast(`It didn't answer: ${r.error}`, {tone: "warning"});
    else toast(`It answered: ${[r.product_name, r.name, r.model ? `model ${r.model}` : ""].filter(Boolean).join(", ") || r.protocol || "nothing"}`);
  } catch (e) { toast(`Couldn't ask it: ${e.message}`, {tone: "danger"}); }
  b.disabled = false;
}

/* ---------------------------------------------------------------- adding (one undo step) */
function hwApply(it, offer, withItem, {auto = false, notice = null} = {}) {
  if (!hwDocOpen()) return toast("Open an experiment first: found devices are added to it.");
  if (!bEditable()) return null;
  const done = [];
  let did = null, compAt = null;
  if (offer.device) {
    const dv = offer.device;
    did = uniqueId(dv.id || dv.type.split("_")[0], new Set((S.exp.devices || []).map((d) => d.id)));
    S.exp.devices = S.exp.devices || [];
    S.exp.devices.push({id: did, type: dv.type, options: JSON.parse(JSON.stringify(dv.options || {}))});
    done.push(`the device “${did}”`);
  }
  if (offer.item && (withItem || !offer.device)) {
    const rid = hwTargetScreen();
    if (!rid) {
      if (!offer.device) return toast("Add a screen first: the item goes on a screen.", {tone: "warning"});
    } else {
      const t = offer.item.type;
      const base = {device_response: "button", microphone: "voice", gamepad: "pad"}[t] || t;
      const c = {id: uniqueId(base, new Set(comps(rid).map((x) => x.id))), type: t};
      if (t === "microphone") Object.assign(c, {duration: 3.0, stop_after_speech: true, end_routine: true});
      Object.assign(c, JSON.parse(JSON.stringify(offer.item.props || {})));
      if (t === "microphone" && !c.device) delete c.device;
      if (t === "device_response" && did) c.device = did;
      comps(rid).push(c);
      compAt = {rid, id: c.id};
      done.push(`a ${offer.item.label || t} item on “${rid}”`);
    }
  }
  if (offer.setting) {
    let o = S.exp; const p = offer.setting.path;
    for (const k of p.slice(0, -1)) { if (!o[k] || typeof o[k] !== "object") o[k] = {}; o = o[k]; }
    o[p[p.length - 1]] = offer.setting.value;
    done.push(offer.label.toLowerCase());
  }
  if (!done.length) return null;
  if (did) S.sel = {kind: "device", index: S.exp.devices.length - 1};
  else if (compAt) S.sel = {kind: "component", routine: compAt.rid, id: compAt.id};
  commit(`Add ${hwName(it)}`);
  if (notice) hwDismiss(notice);
  hwDismiss("new:" + it.id);
  undoToast(`${auto ? "Added automatically: " : "Added "}${hwName(it)}: ${done.join(" and ")}.`);
  hwRefreshStatus(true);
  return did;
}

/* ---------------------------------------------------------------- Find devices rows (build.js scanHardware) */
function hwRowActions(it) {
  const offers = (it.identified || {}).offers || [];
  const used = hwUsedBy(it);
  if (used) return [h("span", {class: "chip success"}, h("span", {class: "dot"}), used.startsWith("a ") || used.startsWith("the ") ? `Used: ${used}` : `Used as “${used}”`)];
  if (!offers.length) return [];
  const withItem = (o) => !!(o.device && o.item && hwTargetScreen() && !(comps(hwTargetScreen()).some((c) => c.type === o.item.type)));
  if ((it.identified || {}).certainty === "ask" || offers.length > 1) {
    const first = (it.identified || {}).certainty === "ask" ? null : offers[0];
    const out = [];
    if (first) out.push(btn("Add", () => hwApply(it, first, withItem(first)), {ic: "plus", title: first.label}));
    out.push(btn(first ? "Add as…" : "Add as…", (e) => ui.menu(e.currentTarget, (first ? offers.slice(1) : offers).map((o) => ({label: o.label, icon: "plus",
      run: () => hwApply(it, o, withItem(o))}))), {ic: first ? null : "plus"}));
    return out;
  }
  return [btn("Add", () => hwApply(it, offers[0], withItem(offers[0])), {ic: "plus", title: offers[0].label})];
}

EDGE.on("app:ready", () => { if (!HW.polling) hwStart(); });
EDGE.on("doc:loaded", () => { for (const k of [...HW.notices.keys()]) if (k.startsWith("gone:")) hwDismiss(k); HW.statusKey = ""; hwRefreshStatus(true); });
EDGE.on("doc:changed", () => { setTimeout(() => hwRefreshStatus(), 0); });
