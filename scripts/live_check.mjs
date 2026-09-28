// Load the public page in a real browser and report what a visitor sees: time to content,
// Streamlit exceptions, console errors and a screenshot per view. Used by
// .github/workflows/live-check.yml; run locally with `node scripts/live_check.mjs [base-url]`.
//
// With --expect "MSTR=Sep 27,ASST=Sep 25" it checks the Monday view instead, reloading it until both
// company cards read those balance dates ("Balance Sep 27 · …"), for at most --minutes (default 12).
// The Monday publish Action uses this before it pings Discord.
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const args = process.argv.slice(2);
const option = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);
const positional = args.filter((arg, i) => !arg.startsWith("--") && !["--expect", "--minutes"].includes(args[i - 1]));
const BASE = (positional[0] || "https://digital-credit-report.streamlit.app").replace(/\/$/, "");
const EXPECT = option("--expect");
const MINUTES = Number(option("--minutes") || 12);
const VIEWS = [
  ["bloomberg-monday", "/?style=bloomberg&report=monday", 1440],
  ["broadsheet-wednesday", "/?style=broadsheet&report=wednesday", 1440],
  ["bloomberg-friday", "/?style=bloomberg&report=friday", 1440],
  ["phone-monday", "/?report=monday", 390],
];
const LIMIT_S = 240;
const OUT = "live-check";
mkdirSync(OUT, { recursive: true });

// Content is a card from the open tab; an exception or error box means the build failed.
async function status(frame) {
  return frame.evaluate(() => {
    const exc = document.querySelector('[data-testid="stException"]');
    if (exc) return { state: "exception", detail: exc.innerText.slice(0, 1500) };
    const alert = document.querySelector('[data-testid="stAlertContentError"]');
    if (alert) return { state: "error", detail: alert.innerText.slice(0, 600) };
    if (document.querySelector('[class*="st-key-mon_"], [class*="st-key-wed_"], [class*="st-key-fri_"]'))
      return { state: "content", detail: "" };
    const running = document.querySelector('[data-testid="stStatusWidget"]');
    return { state: "waiting", detail: running ? running.innerText.slice(0, 80) : "" };
  }).catch(() => null);
}

// The app runs in the /~/+/ frame on Community Cloud and in the main frame locally.
const appFrames = (page) => page.frames().filter((f) => f.url().includes("/~/+/") || f === page.mainFrame());

// Open a view and wait until it shows content, an error or LIMIT_S passes.
async function open(page, url) {
  let result = { state: "timeout", detail: "" };
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
    for (let i = 0; i < LIMIT_S * 2; i++) {
      await page.waitForTimeout(500);
      // A sleeping Community Cloud app shows a wake-up button first.
      const wake = page.getByRole("button", { name: /get this app back up/i });
      if (await wake.count().catch(() => 0)) await wake.first().click().catch(() => {});
      const seen = (await Promise.all(appFrames(page).map(status))).filter(Boolean);
      const done = seen.find((s) => s.state !== "waiting");
      if (done) return done;
      result = seen[0] || result;
    }
  } catch (error) {
    result = { state: "navigation-error", detail: String(error).slice(0, 400) };
  }
  return result;
}

// Each Monday company card's balance line, e.g. {MSTR: "Balance Sep 27 · 8-K · 1.19× NAV · 9:51 AM ET"}.
async function balanceLines(page, tickers) {
  const lines = {};
  for (const frame of appFrames(page)) {
    const found = await frame.evaluate((tickers) => Object.fromEntries(tickers.map((ticker) => {
      const meta = document.querySelector(`.st-key-mon_${ticker} .dcr-meta`);
      return [ticker, meta ? meta.innerText.replace(/\s+/g, " ").trim() : null];
    })), tickers).catch(() => ({}));
    for (const [ticker, line] of Object.entries(found)) if (line) lines[ticker] = line;
  }
  return lines;
}

const escapeRegExp = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

async function expectBalances(browser) {
  const expected = Object.fromEntries(EXPECT.split(",").map((pair) => pair.split("=").map((part) => part.trim())));
  const tickers = Object.keys(expected);
  // "Balance Sep 27 · …", and not "Balance Sep 2 · …" for Sep 2.
  const shows = (lines) => tickers.every((ticker) =>
    new RegExp(`^Balance ${escapeRegExp(expected[ticker])}(?!\\d)`).test(lines[ticker] || ""));
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const started = Date.now();
  const deadline = started + MINUTES * 60000;
  let lines = {}, result, attempt = 0;
  for (;;) {
    attempt += 1;
    result = await open(page, BASE + "/?report=monday");
    // The cards can land a moment after the first content.
    for (let i = 0; i < 30 && result.state === "content"; i++) {
      lines = await balanceLines(page, tickers);
      if (shows(lines)) break;
      await page.waitForTimeout(1000);
    }
    console.log(`attempt ${attempt} (${((Date.now() - started) / 60000).toFixed(1)} min) ${result.state} ${JSON.stringify(lines)}`);
    if (shows(lines) || Date.now() > deadline) break;
    await page.waitForTimeout(30000);
  }
  const matched = shows(lines);
  await page.screenshot({ path: `${OUT}/monday-balances.png`, fullPage: false });
  writeFileSync(`${OUT}/results.json`, JSON.stringify(
    { base: BASE, checked_at: new Date().toISOString(), expect: expected, lines, matched, attempts: attempt, state: result.state }, null, 2));
  console.log(matched ? `Both cards show ${EXPECT}` : `The page did not show ${EXPECT} within ${MINUTES} minutes`);
  await page.close();
  return matched;
}

const browser = await chromium.launch();
if (EXPECT) {
  process.exitCode = (await expectBalances(browser)) ? 0 : 1;
} else {
  const results = [];
  for (const [name, path, width] of VIEWS) {
    const page = await browser.newPage({ viewport: { width, height: 1100 } });
    const consoleErrors = [];
    page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200)); });
    const started = Date.now();
    const result = await open(page, BASE + path);
    const seconds = (Date.now() - started) / 1000;
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
    results.push({ name, url: BASE + path, seconds: Math.round(seconds * 10) / 10, ...result, consoleErrors: consoleErrors.slice(0, 5) });
    console.log(`${name.padEnd(22)} ${result.state.padEnd(16)} ${seconds.toFixed(1)}s ${result.detail ? "| " + result.detail.replace(/\s+/g, " ").slice(0, 300) : ""}`);
    await page.close();
  }
  writeFileSync(`${OUT}/results.json`, JSON.stringify({ base: BASE, checked_at: new Date().toISOString(), results }, null, 2));
  process.exitCode = results.every((r) => r.state === "content") ? 0 : 1;
}
await browser.close();
