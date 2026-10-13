// Shared Playwright helpers for the UI checks (tutorial runs and documentation screenshots).
// Playwright is not a dependency of EDGE: it is found in the global node_modules (npm install -g playwright).
// Environment: EDGE_URL (the builder, default http://127.0.0.1:8765), EDGE_ASSISTANT_URL (a second builder whose
// assistant points at a fake model service, see run.py), CHROMIUM (a chromium executable, optional).
const { execSync } = require("child_process");
const fs = require("fs");

function loadPlaywright() {
  try { return require("playwright"); } catch {}
  const root = execSync("npm root -g").toString().trim();
  return require(root + "/playwright");
}
const pw = loadPlaywright();

async function launch() {
  const exe = process.env.CHROMIUM || (fs.existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined);
  return pw.chromium.launch(exe ? { executablePath: exe } : {});
}

/* A fresh browser context (no localStorage, no drafts) with a log of everything that went wrong in the page. */
async function newPage(browser, { width = 1440, height = 900, dark = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: dark ? "dark" : "light", deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const log = [];
  page.on("console", (m) => { if (m.type() === "error") log.push(`[console.error] ${m.text()}`); });
  page.on("pageerror", (e) => log.push(`[pageerror] ${e.message} ${(e.stack || "").split("\n")[1] || ""}`.trim()));
  page.on("response", (r) => { if (r.status() >= 500) log.push(`[http ${r.status()}] ${r.url()}`); });
  page.on("dialog", (d) => { log.push(`[native dialog] ${d.type()} ${d.message()}`); d.dismiss().catch(() => {}); });
  return { ctx, page, log };
}

/* Open the builder (optionally with ?tutorial=id) and wait until it has booted. */
async function openBuilder(page, base, query = "") {
  await page.goto(base.replace(/\/$/, "") + "/" + query);
  await page.waitForFunction(() => window.EDGE && typeof S !== "undefined" && S.schema, null, { timeout: 30000 });
  await page.waitForTimeout(800);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

module.exports = { pw, launch, newPage, openBuilder, sleep };
