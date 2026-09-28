// Load the public page in a real browser and report what a visitor sees: time to content,
// Streamlit exceptions, console errors and a screenshot per view. Used by
// .github/workflows/live-check.yml; run locally with `node scripts/live_check.mjs [base-url]`.
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = (process.argv[2] || "https://digital-credit-report.streamlit.app").replace(/\/$/, "");
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

const browser = await chromium.launch();
const results = [];
for (const [name, path, width] of VIEWS) {
  const page = await browser.newPage({ viewport: { width, height: 1100 } });
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200)); });
  const started = Date.now();
  let result = { state: "timeout", detail: "" };
  try {
    await page.goto(BASE + path, { waitUntil: "domcontentloaded", timeout: 90000 });
    for (let i = 0; i < LIMIT_S * 2; i++) {
      await page.waitForTimeout(500);
      // A sleeping Community Cloud app shows a wake-up button first.
      const wake = page.getByRole("button", { name: /get this app back up/i });
      if (await wake.count().catch(() => 0)) await wake.first().click().catch(() => {});
      const frames = page.frames().filter((f) => f.url().includes("/~/+/") || f === page.mainFrame());
      const seen = (await Promise.all(frames.map(status))).filter(Boolean);
      const done = seen.find((s) => s.state !== "waiting");
      if (done) { result = done; break; }
      result = seen[0] || result;
    }
  } catch (error) {
    result = { state: "navigation-error", detail: String(error).slice(0, 400) };
  }
  const seconds = (Date.now() - started) / 1000;
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
  results.push({ name, url: BASE + path, seconds: Math.round(seconds * 10) / 10, ...result, consoleErrors: consoleErrors.slice(0, 5) });
  console.log(`${name.padEnd(22)} ${result.state.padEnd(16)} ${seconds.toFixed(1)}s ${result.detail ? "| " + result.detail.replace(/\s+/g, " ").slice(0, 300) : ""}`);
  await page.close();
}
await browser.close();
writeFileSync(`${OUT}/results.json`, JSON.stringify({ base: BASE, checked_at: new Date().toISOString(), results }, null, 2));
process.exitCode = results.every((r) => r.state === "content") ? 0 : 1;
