// Runs every interactive tutorial end to end in a real browser, doing each step the way a person would
// (clicks, typing, drag and drop), and reports per step: was the target visible (after "Take me there"
// when the coach asks for it), did the coach cover it, did the check fire, and did the tutorial complete.
//
//   node tools/ui_check/tutorials.js                    # all tutorials, against $EDGE_URL
//   ONLY=first_experiment,trial_lists node tools/ui_check/tutorials.js
//
// The assistant step of "assistant_basics" needs a model: it runs once on $EDGE_URL without one (the step is
// skipped, as the tutorial says) and once on $EDGE_ASSISTANT_URL (a builder whose assistant points at the fake
// model service of tests/assistant_fakes.py; run.py starts both). Exit code 1 when any tutorial failed.
const path = require("path");
const fs = require("fs");
const { launch, newPage, openBuilder, sleep } = require("./pw.js");

const BASE = process.env.EDGE_URL || "http://127.0.0.1:8765";
const ASSIST = process.env.EDGE_ASSISTANT_URL || "";
const W = +(process.env.WIDTH || 1440), H = +(process.env.HEIGHT || 900);
const SHOTS = process.env.SHOTS || "";            // folder for a screenshot of every step (optional)
const ROOT = path.resolve(__dirname, "..", "..");
const PSYEXP = [path.join(ROOT, "tests/fixtures/psychopy/stroop.psyexp"), path.join(ROOT, "tests/fixtures/psychopy/trialTypes.csv")];

// ------------------------------------------------------------------ helpers a step uses
function helpers(page, notes) {
  const visible = (sel) => page.locator(sel).filter({ visible: true }).first();
  const click = async (sel, opts = {}) => {
    const loc = typeof sel === "string" ? visible(sel) : sel;
    try { await loc.click({ timeout: 4000, ...opts }); }
    catch (e) {
      const msg = String(e.message || e);
      if (/intercepts pointer events/.test(msg)) {
        const by = (msg.match(/<([^>]{0,80})> (?:from <[^>]*> subtree )?intercepts/) || [])[1] || "?";
        notes.push(`covered: ${typeof sel === "string" ? sel : "locator"} is under <${by}>; clicked it directly`);
        await loc.evaluate((x) => x.click());
      } else throw e;
    }
    await sleep(opts.wait ?? 350);
  };
  const dblclick = async (sel) => { await visible(sel).dblclick({ timeout: 4000 }); await sleep(600); };
  const type = async (text) => { await page.keyboard.type(text); };
  const enter = async (wait = 800) => { await page.keyboard.press("Enter"); await sleep(wait); };
  const fill = async (sel, value) => { const l = visible(sel); await l.fill(String(value)); await l.press("Tab"); await sleep(500); };
  const prop = (name, el = "input") => `#props [data-prop=${name}] ${el}`;
  const menu = async (text) => { await click(page.locator(".menu").filter({ visible: true }).getByText(text, { exact: false }).first()); };
  const dialog = () => page.locator(".scrim .dialog").last();
  const nameDialog = async (name) => {
    await dialog().locator("input").first().waitFor({ timeout: 4000 });
    await page.keyboard.press("Control+a"); await type(name); await enter(1200);
  };
  const newColumn = async (field, name) => {
    await page.hover(`#props [data-prop=${field}]`);
    await click(`#props [data-prop=${field}] .srcbtn`);
    await menu("New trial-list column");
    await nameDialog(name);
  };
  const keys = async (field, list) => {
    const box = `#props [data-prop=${field}] .kc-add`;
    await click(box); await page.keyboard.press("Backspace"); await sleep(250);
    for (const k of list) { await click(box); await page.keyboard.press(k); await sleep(250); }
  };
  const drag = async (from, to) => { await page.dragAndDrop(from, to); await sleep(900); };
  const addDevice = async (group, type) => {
    await click("#btn-add-device");
    await click(dialog().locator("button", { hasText: group }).first());
    await click(dialog().locator("label.adddev-opt", { hasText: type }).first());
    await click(dialog().locator("button", { hasText: "Add device" }));
    await sleep(800);
  };
  const waitIdle = async () => { await page.waitForFunction(() => !S.testing, null, { timeout: 120000 }); await sleep(500); };
  return { visible, click, dblclick, type, enter, fill, prop, menu, dialog, nameDialog, newColumn, keys, drag, addDevice, waitIdle };
}

// ------------------------------------------------------------------ what a person does at each step
// One function per step (null: just read and press Next / the check fires by itself).
const PLAYS = {
  first_experiment: [
    null,
    async (x) => { await x.click(".rtab.add"); await x.nameDialog("trial"); },
    async (x) => { await x.click(".pal-item[data-type=text]"); },
    async (x) => { await x.newColumn("text", "word"); },
    async (x) => { await x.newColumn("color", "ink"); },
    async (x) => { await x.click(".pal-item[data-type=keyboard]"); await x.keys("keys", ["r", "g", "b"]); await x.newColumn("correct", "key"); },
    async (x, page) => {
      await x.click(".pal-item[data-type=fixation]"); await x.fill(x.prop("duration"), 0.5);
      await x.click("#timeline [data-fkey='tl:trial:text']"); await x.fill(x.prop("start"), 0.5);
    },
    async (x) => { await x.click("#flow .frame.loop >> text=Open list"); },
    async (x, page) => {
      const row = async (r, vals) => { await x.click(`#list-editor td[data-r="${r}"][data-c="0"]`);
        for (let i = 0; i < vals.length; i++) { await x.type(vals[i]); await page.keyboard.press(i < vals.length - 1 ? "Tab" : "Enter"); } await page.waitForTimeout(250); };
      await row(0, ["RED", "red", "r"]); await row(1, ["RED", "green", "g"]);
      await x.click("#list-editor .le-foot >> text=Row"); await row(2, ["BLUE", "blue", "b"]);
    },
    async (x) => { await x.fill(x.prop("repeats"), 2); await x.click("#btn-view-done"); },
    async (x) => { await x.click("#btn-dryrun"); await x.waitIdle(); },
    async (x) => { await x.click("#btn-save"); await x.nameDialog("stroop_" + Date.now().toString(36)); },
  ],
  trial_lists: [
    async (x) => { await x.click("#flow .frame.loop .lbl"); },
    async (x, page) => { await x.fill(x.prop("repeats"), 3); await page.selectOption(x.prop("order", "select"), { label: "Shuffled across repeats" }); },
    async (x) => { await x.click("#props .more-row"); await x.fill("#props [data-prop=max_repeat] input[data-fkey='mr:ink']", 2); },
    async (x) => { await x.click("#flow .frame.loop >> text=Open list"); },
    async (x) => { await x.click("#list-editor .seg >> text=Every combination"); },
    null,
    async (x) => { await x.click("#btn-dryrun"); await x.waitIdle(); },
    async (x) => { await x.click("[data-tab=data]"); await x.click("#ws-data [role=radio][data-value=tests]"); },
  ],
  workflow_practice: [
    null,
    async (x) => { await x.click("#flow .ins >> nth=0"); await x.menu("Workflow (practice until good"); },
    async (x) => { await x.click(".sm-state .sm-name"); await x.fill(x.prop("name"), "practice"); },
    async (x) => { await x.drag("section.frame.loop[aria-label='Trial list practice'] .frame-head", ".sm-state .ins"); },
    async (x) => {
      await x.click(".fl-box.sm >> text=Add a phase"); await x.nameDialog("main");
      await x.drag("section.frame.loop[aria-label='Trial list main'] .frame-head", ".sm-state:nth-child(2) .ins");
    },
    async (x, page) => {
      await x.click(".sm-state:nth-child(1) .sm-name"); await x.click("#props >> text=Add a route");
      await x.fill("#route-0-if", "$practice.accuracy >= 0.8");
      await page.selectOption("#route-0-goto", "main"); await page.waitForTimeout(400);
      await page.selectOption("#route-1-goto", "practice"); await page.waitForTimeout(400);
    },
    async (x) => { await x.fill(x.prop("max_visits"), 3); },
    async (x) => { await x.click(".fl-box.sm > .fl-head >> text=Open diagram"); },
    async (x) => { await x.click("#btn-dryrun"); await x.waitIdle(); },
  ],
  eyetracking: [
    async (x) => { await x.addDevice("Simulated (for testing)", "sim_eyetracker"); },
    async (x) => { await x.dblclick("#flow .scard"); },
    async (x, page) => { await x.click(".pal-item[data-type=gaze_roi]"); await page.selectOption(x.prop("target", "select"), "left_box"); },
    async (x, page) => { await x.click(".pal-item[data-type=gaze_roi]"); await page.selectOption(x.prop("target", "select"), "right_box"); },
    async (x) => { await x.click("#timeline [data-fkey='tl:look:left_box']"); await x.fill(x.prop("marker"), "squares_on"); },
    async (x) => { await x.addDevice("Marker stream", "lsl_markers"); },
    async (x) => { await x.click("#btn-dryrun"); await x.waitIdle(); },
  ],
  html_questionnaire: [
    async (x) => { await x.click(".rtab.add"); await x.nameDialog("survey"); },
    async (x) => { await x.click(".pal-item[data-type=html]"); },
    async (x) => { await x.fill(x.prop("html", "textarea"), FORM); },
    async (x) => { await x.click("#view-switch [data-view=story]"); },
    async (x) => { await x.click("#btn-dryrun"); await x.waitIdle(); },
  ],
  rules_and_feedback: [
    async (x) => { await x.click("#flow .scard >> nth=0"); },
    async (x) => { await x.click("#props >> text=Add a rule"); },
    async (x) => { await x.fill("#rule-0-when", "$t > 1.5 and resp.keys is None"); },
    async (x, page) => { await page.selectOption("[data-fkey='rule:0:do:0']", "start"); await page.waitForTimeout(500);
      await page.selectOption("[data-prop='rules.0'] .rule-do select[aria-label='Which item']", "hint"); },
    async (x) => { await x.dblclick("#flow .scard >> nth=1"); await x.click("#timeline [data-fkey='tl:feedback:fb']"); await x.fill(x.prop("if"), "$practice.n < 6"); },
    async (x) => { await x.click("#btn-dryrun"); await x.waitIdle(); },
  ],
  data_and_export: [
    async (x) => { await x.click("#btn-dryrun"); await x.waitIdle(); },
    async (x) => { await x.click("[data-tab=data]"); await x.click("#ws-data [role=radio][data-value=tests]"); await x.click("#ws-data .ds-list button >> nth=0").catch(() => {}); },
    async (x) => { await x.click("#ws-data [role=tab] >> text=Summary"); await x.click("#ws-data [role=tab] >> text=What each column means"); },
    async (x, page) => { await x.click(page.locator("#data-detail button", { hasText: "Export" }).first()); await page.keyboard.press("Escape"); },
    async (x) => { await x.click("#nav-build"); },
    async (x) => {
      await x.click("#btn-settings");
      await x.click(x.dialog().getByText("Data files", { exact: true })); await x.click(x.dialog().getByText("Excel (.xlsx)"));
      await x.click(x.dialog().locator("button", { hasText: "Done" }));
    },
    async (x) => { await x.click("[data-tab=source]"); },
  ],
  import_existing: [
    null,
    async (x, page) => {
      await x.click("#btn-import");
      const [fc] = await Promise.all([page.waitForEvent("filechooser"), x.click(x.dialog().locator("button", { hasText: "Choose files" }))]);
      await fc.setFiles(PSYEXP);
      await x.dialog().getByText("Open and test").waitFor({ timeout: 30000 });
    },
    async (x) => { await x.click(x.dialog().locator("button", { hasText: "Open and test" })); await x.waitIdle(); },
    null,
  ],
  survey_builder: [
    null,
    async (x) => { await x.dblclick("#flow .scard"); await x.click(".pal-item[data-type=survey]"); },
    async (x) => { await x.click("#props >> text=Edit questions", { wait: 1200 }); },
    async (x, page) => {
      await x.click(x.dialog().locator("button", { hasText: "From the library" }), { wait: 1000 });
      await x.dialog().locator("input[type=search], input").first().fill("life"); await page.waitForTimeout(600);
      await x.click(x.dialog().locator(":is(article,section,div)", { hasText: "Satisfaction With Life" }).locator("button", { hasText: "Add" }).last(), { wait: 1200 });
    },
    async (x, page) => {
      const d = x.dialog();
      await x.click(d.locator("button", { hasText: "Add a question" })); await x.menu("Multiple choice (checkboxes)");
      await d.getByLabel("Question", { exact: true }).fill("Which of these do you do at least once a week?"); await page.keyboard.press("Tab");
      await d.getByLabel("Options (one per line)").fill("Sport\nMusic\nReading\nNone of these"); await page.keyboard.press("Tab"); await page.waitForTimeout(400);
      await d.getByLabel("Exclusive option (unticks the others)").selectOption({ label: "None of these" });
      await d.getByLabel("Data name (column)").fill("weekly"); await page.keyboard.press("Tab");
    },
    async (x, page) => {
      const d = x.dialog();
      await x.click(d.locator("button", { hasText: "Add a question" }));
      await x.click(page.locator(".menu").filter({ visible: true }).getByText("Number", { exact: true }));
      await d.getByLabel("Data name (column)").fill("sport_hours"); await page.keyboard.press("Tab");
      await d.getByLabel("Question", { exact: true }).fill("How many hours of sport per week?"); await page.keyboard.press("Tab");
      await d.getByLabel("Show it").selectOption({ index: 2 }); await page.waitForTimeout(400);
      await d.getByLabel("Comparison").selectOption({ label: "includes" }); await page.waitForTimeout(300);
      await d.getByLabel("Value").selectOption({ label: "Sport" });
    },
    { pre: async (x) => { await x.click(x.dialog().locator("button", { hasText: "Done" }).last()); },
      play: async (x) => { await x.click("#btn-dryrun"); await x.waitIdle(); } },
    null,
  ],
  assistant_basics: [
    null,
    async (x) => { await x.click("#assistant-toggle", { wait: 900 }); },
    async (x) => { await x.click("#assistant-provider-chip", { wait: 900 }); },
    null,
    async (x) => {
      const more = x.dialog().getByText("What is sent where");
      if (await more.count()) await x.click(more);
      await x.click(x.dialog().locator("button", { hasText: "Cancel" }));
    },
    "ask",
    null,
  ],
};
const FORM = `<h2>How do you feel?</h2>
<form>
  <label><input type="radio" name="mood" value="1" required> bad</label>
  <label><input type="radio" name="mood" value="2"> okay</label>
  <label><input type="radio" name="mood" value="3"> great</label>
  <p>Age <input type="number" name="age" min="18" max="99"></p>
  <button>Continue</button>
</form>`;

// ------------------------------------------------------------------ the runner
async function stepState(page) {
  return page.evaluate(() => {
    const st = T.tut && T.tut.steps[T.i];
    const sel = st && st.target;
    const shown = (e) => !!e && e.offsetParent !== null && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== "hidden";
    let targets = [];
    try { targets = sel ? [...document.querySelectorAll(sel)] : []; } catch {}
    const t = targets.find(shown);
    const c = document.querySelector("#coach");
    let covered = false;
    if (t && c) {
      const a = t.getBoundingClientRect(), b = c.getBoundingClientRect();
      const ix = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)), iy = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
      covered = ix * iy > 0.5 * a.width * a.height;
    }
    const reveal = c && c.querySelector(".coach-reveal:not([hidden])");
    return { i: T.i, n: T.tut ? T.tut.steps.length : 0, title: st && st.title, target: sel || null, check: st && st.check || null,
      visible: sel ? !!t : null, covered, reveal: reveal ? reveal.innerText.trim() : null,
      passedAtStart: !!(st && st.check && tutorialCheck(st.check)), done: !!(c && c.classList.contains("done")) };
  });
}

async function runTutorial(browser, base, id, { ask = false } = {}) {
  const { page, log, ctx } = await newPage(browser, { width: W, height: H });
  const notes = [];
  const x = helpers(page, notes);
  const result = { tutorial: id + (ask ? " (with a model)" : ""), url: base, steps: [], completed: false, errors: [] };
  try {
    await openBuilder(page, base, `?tutorial=${id}`);
    await page.waitForFunction(() => typeof T !== "undefined" && T.tut, null, { timeout: 15000 });
    await sleep(900);
    const plays = PLAYS[id];
    const n = await page.evaluate(() => T.tut.steps.length);
    if (plays.length !== n) result.errors.push(`the runner knows ${plays.length} steps, the tutorial has ${n}`);
    for (let i = 0; i < n; i++) {
      await page.waitForFunction((k) => T.tut && T.i === k, i, { timeout: 15000 });
      await sleep(1000);                                        // the coach reveals in-workspace targets at 180-900 ms
      const mark = notes.length;
      const entry = plays[i];
      const pre = entry && entry.pre, play0 = entry && entry.play ? entry.play : entry;
      if (pre) await pre(x, page).catch((e) => notes.push("preparation failed: " + String(e.message || e).split("\n")[0]));
      let s = await stepState(page);
      const rec = { step: i + 1, title: s.title, target: s.target, visible: s.visible, via: null, covered: s.covered, check: s.check ? Object.keys(s.check).join("+") : null,
        passedAtStart: s.passedAtStart, fired: null, notes: [] };
      if (s.target && !s.visible && s.reveal) {                 // "First open Test" → Take me there, like a person would
        rec.via = s.reveal.replace(/\s*Take me there$/, "");
        await x.click("#coach >> text=Take me there", { wait: 900 });
        s = await stepState(page); rec.visible = s.visible; rec.covered = s.covered;
      }
      if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${id}${ask ? "_ask" : ""}_${String(i + 1).padStart(2, "0")}.png`) });
      const play = play0;
      try {
        if (play === "ask") {
          if (ask) {
            await x.fill("#assistant-input", "A Stroop task: the words RED, GREEN and BLUE in red, green or blue ink; the participant presses r, g or b for the ink colour.").catch(() => {});
            await page.focus("#assistant-input"); await page.keyboard.press("Enter");
            await page.locator(".assistant-result").first().waitFor({ timeout: 90000 });
            await sleep(800);
            if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${id}_ask_result.png`) });
            await x.click(page.locator(".assistant-result button", { hasText: "Apply" }).first(), { wait: 1200 });
          } else { await x.click("#coach >> text=Skip step"); rec.notes.push("skipped (no model)"); }
        } else if (play) await play(x, page);
      } catch (e) { rec.notes.push("action failed: " + String(e.message || e).split("\n")[0]); }
      rec.notes.push(...notes.slice(mark));
      // the check fires (the coach moves on by itself), or the step has none and we press Next / Finish
      if (s.check && play !== "ask" || (play === "ask" && ask)) {
        rec.fired = await page.waitForFunction((k) => !T.tut || T.i > k, i, { timeout: 20000 }).then(() => true, () => false);
        if (!rec.fired) { rec.notes.push("check did not fire; pressed Skip step"); await x.click("#coach >> text=Skip step").catch(() => {}); }
      } else if (play !== "ask") {
        await x.click("#coach .coach-next");
      }
      result.steps.push(rec);
    }
    await page.waitForFunction(() => { const c = document.querySelector("#coach"); return c && c.classList.contains("done"); }, null, { timeout: 10000 });
    result.completed = await page.evaluate(() => /Tutorial complete\./.test(document.querySelector("#coach").innerText));
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${id}${ask ? "_ask" : ""}_done.png`) });
  } catch (e) {
    result.errors.push(String(e.message || e).split("\n")[0]);
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${id}${ask ? "_ask" : ""}_failed.png`) }).catch(() => {});
  }
  result.pageErrors = log.filter((l) => !/favicon|ERR_ABORTED/.test(l));
  await ctx.close();
  return result;
}

function ok(r) {
  return r.completed && !r.errors.length && r.steps.every((s) => (s.target ? s.visible : true) && !s.covered &&
    (s.check && !/skipped \(no model\)/.test(s.notes.join()) ? s.fired && !s.passedAtStart : true) && !s.notes.some((n) => /failed|did not fire/.test(n)));
}

(async () => {
  if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });
  const only = process.env.ONLY ? process.env.ONLY.split(",").filter((id) => PLAYS[id]) : Object.keys(PLAYS);
  const browser = await launch();
  const results = [];
  for (const id of only) {
    results.push(await runTutorial(browser, BASE, id));
    if (id === "assistant_basics" && ASSIST) results.push(await runTutorial(browser, ASSIST, id, { ask: true }));
  }
  await browser.close();
  let failed = 0;
  for (const r of results) {
    const good = ok(r); if (!good) failed++;
    console.log(`${good ? "PASS" : "FAIL"}  ${r.tutorial}: ${r.steps.length} steps, ${r.completed ? "completed" : "NOT completed"}`);
    for (const s of r.steps) {
      const bits = [s.target ? (s.visible ? "target visible" : "TARGET NOT VISIBLE") + (s.via ? ` (after ${s.via})` : "") : "no target",
        s.covered ? "COVERED BY THE COACH" : null, s.check ? (s.fired ? `check ${s.check} fired` : s.passedAtStart ? `check ${s.check} PASSED AT STEP START` : `check ${s.check} DID NOT FIRE`) : null,
        s.passedAtStart && s.fired ? "but it already passed at step start" : null].filter(Boolean);
      console.log(`   ${String(s.step).padStart(2)}. ${s.title}: ${bits.join(", ")}${s.notes.length ? "  [" + s.notes.join("; ") + "]" : ""}`);
    }
    for (const e of r.errors) console.log("   error: " + e);
    for (const e of r.pageErrors) console.log("   page: " + e);
  }
  if (process.env.REPORT) fs.writeFileSync(process.env.REPORT, JSON.stringify(results, null, 1));
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
