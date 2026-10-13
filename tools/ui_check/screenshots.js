// Makes the screenshots used in the documentation (docs/*.png) at 1440 × 900, light theme.
//
//   EDGE_URL=… EDGE_ASSISTANT_URL=… OUT=docs node tools/ui_check/screenshots.js
//
// $EDGE_URL must serve a folder with stroop/stroop.yaml, questionnaire/questionnaire.yaml and
// online_questionnaire/wellbeing_survey.yaml (run.py sets one up). $EDGE_ASSISTANT_URL is a builder whose
// assistant points at the fake model service (tests/assistant_fakes.py, scenario "stroop"); without it
// assistant.png is skipped. ONLY=builder,wizard limits the set.
const path = require("path");
const { launch, newPage, openBuilder, sleep } = require("./pw.js");

const BASE = process.env.EDGE_URL || "http://127.0.0.1:8765";
const ASSIST = process.env.EDGE_ASSISTANT_URL || "";
const OUT = path.resolve(process.env.OUT || path.join(__dirname, "..", "..", "docs"));
const ONLY = process.env.ONLY ? process.env.ONLY.split(",") : null;

async function open(page, file, ws = "build") {
  await page.evaluate(([p, w]) => { S.dirty = false; return openExperiment(p, w); }, [file, ws]);
  await sleep(1200);
}
/* No hover tooltips, focus rings or toasts in the pictures. */
async function tidy(page) {
  await page.mouse.move(1, 899);
  await page.evaluate(() => { document.activeElement && document.activeElement.blur && document.activeElement.blur();
    document.querySelectorAll("#toast > *, .toast").forEach((t) => t.remove()); });
  await sleep(400);
}

const SHOTS = {
  // the main picture: a screen of the Stroop example with its word selected
  async builder(page) {
    await openBuilder(page, BASE);
    await open(page, "stroop/stroop.yaml");
    await page.evaluate(() => { EDGE.setView("story"); });
    await sleep(500);
    await page.locator("#flow .scard", { hasText: "trial" }).first().dblclick();
    await sleep(900);
    await page.click("#timeline [data-fkey='tl:trial:stimulus']");
    await sleep(900);
    await tidy(page);
  },
  // the design wizard on its first page, with a name
  async wizard(page) {
    await openBuilder(page, BASE);
    await page.evaluate(() => EDGE.go("home"));
    await sleep(800);
    await page.evaluate(() => openWizard());
    await sleep(1200);
    const name = page.locator(".scrim .dialog input").filter({ visible: true }).last();
    if (await name.count()) { await name.fill("stroop_task").catch(() => {}); }
    await sleep(600);
    await tidy(page);
  },
  // the questionnaire example's workflow in the storyboard, its first phase selected (its routes in Properties)
  async workflow(page) {
    await openBuilder(page, BASE);
    await open(page, "questionnaire/questionnaire.yaml");
    await page.evaluate(() => EDGE.setView("story"));
    await sleep(700);
    await page.locator(".fl-box.sm .sm-state .sm-name").first().click();
    await sleep(900);
    await tidy(page);
  },
  // the survey editor on the online questionnaire template
  async survey_editor(page) {
    await openBuilder(page, BASE);
    await open(page, "online_questionnaire/wellbeing_survey.yaml");
    const where = await page.evaluate(() => { for (const [rid, r] of Object.entries(S.exp.routines)) for (const c of r.components || []) if (c.type === "survey" && (c.questions || []).length > 2) return [rid, c.id]; return null; });
    await page.evaluate(([rid, cid]) => { EDGE.setView("screen", { routine: rid }); EDGE.select({ kind: "component", routine: rid, id: cid }); }, where);
    await sleep(900);
    await page.locator("#props").getByText("Edit questions").click();
    await sleep(1500);
    const swls = page.locator(".scrim .dialog .sv-list").getByText("Satisfaction With Life", { exact: false }).first();
    if (await swls.count()) { await swls.click().catch(() => {}); await sleep(900); }
    await tidy(page);
  },
  // the assistant: a Stroop task built from a description, as a preview to apply
  async assistant(page) {
    if (!ASSIST) return "skipped: no EDGE_ASSISTANT_URL";
    await openBuilder(page, ASSIST, "?tutorial=assistant_basics");          // an empty experiment, no coach in the picture
    await page.evaluate(() => { stopTutorial(); });
    await sleep(500);
    await page.click("#assistant-toggle");
    await sleep(900);
    await page.fill("#assistant-input", "A Stroop task: the words RED, GREEN and BLUE in red, green or blue ink. The participant presses r, g or b for the ink colour.");
    await page.keyboard.press("Enter");
    await page.locator(".assistant-result").first().waitFor({ timeout: 90000 });
    await sleep(1500);
    await page.evaluate(() => { const r = document.querySelector(".assistant-result"); if (r) r.scrollIntoView({ block: "end" }); });
    await tidy(page);
  },
};

(async () => {
  const browser = await launch();
  let failed = 0;
  for (const [name, make] of Object.entries(SHOTS)) {
    if (ONLY && !ONLY.includes(name)) continue;
    const { page, log, ctx } = await newPage(browser, { width: 1440, height: 900 });
    try {
      const note = await make(page);
      if (note) { console.log(`${name}: ${note}`); await ctx.close(); continue; }
      const file = path.join(OUT, `${name}.png`);
      await page.screenshot({ path: file });
      console.log(`${name}: ${file}${log.length ? "  (" + log.join("; ") + ")" : ""}`);
    } catch (e) { failed++; console.log(`${name}: FAILED ${String(e.message || e).split("\n")[0]}`); }
    await ctx.close();
  }
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
