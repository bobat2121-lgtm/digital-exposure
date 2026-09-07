import { readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";

const base = new URL(process.argv[2] ?? "");
if (base.protocol !== "https:" || base.username || base.password || base.pathname !== "/") throw new Error("Use the HTTPS Worker base URL");
const token = process.env.CAPITAL_REPORT_ADMIN_TOKEN;
if (!token || token.length < 32) throw new Error("Set CAPITAL_REPORT_ADMIN_TOKEN in the environment");
async function request(path, options = {}) {
  const response = await fetch(new URL(path, base), { ...options, signal: AbortSignal.timeout(60000) });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}
const status = await request("/api/status");
if (status.schemaVersion !== 1 || status.issuers?.length !== 2) throw new Error("Unexpected status contract");
const denied = await fetch(new URL("/api/admin/poll", base), { method: "POST", signal: AbortSignal.timeout(10000) });
if (denied.status !== 401) throw new Error("Admin route did not reject unauthenticated access");
const report = { checkedAt: new Date().toISOString(), worker: base.origin,
  configured: status.issuers.every(issuer => issuer.configured), schedule: status.schedule,
  unauthenticatedMutationRejected: true, poll: null, replays: [] };
if (process.argv.includes("--poll")) report.poll = await request("/api/admin/poll", { method: "POST", headers: { Authorization: `Bearer ${token}` } });
const replayId = `smoke-${randomUUID()}`;
for (const [ticker, name] of [["MSTR", "strategy-20260831.html"], ["ASST", "strive-20260831.html"]]) {
  const html = await readFile(new URL(`../test/fixtures/${name}`, import.meta.url), "utf8");
  const options = { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, replayId, html }) };
  const first = await request("/api/admin/replay", options);
  const repeated = await request("/api/admin/replay", options);
  if (first.outcome !== "validated_for_review" || repeated.outcome !== "duplicate" || first.livePublicationChanged !== false)
    throw new Error(`${ticker}: replay did not validate and deduplicate in isolation`);
  report.replays.push({ ticker, outcome: first.outcome, repeat: repeated.outcome, digest: first.digest, durationMs: first.durationMs });
}
const feed = await request("/api/filings");
report.filingCount = feed.filings.length;
report.passed = report.configured && report.replays.length === 2;
console.log(JSON.stringify(report, null, 2));
if (!report.passed) process.exitCode = 1;
