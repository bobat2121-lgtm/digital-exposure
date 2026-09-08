import { env, exports } from "cloudflare:workers";
import { evictDurableObject, reset, runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { eligiblePublication } from "../src/feed";
import { extractWeekly } from "../src/parser";
import { documentUrl } from "../src/sec";
import { ISSUERS, initialState, type Filing, type Ticker } from "../src/types";
import strive from "./fixtures/strive-20260831.html?raw";
import strategyHoliday from "./fixtures/strategy-20260908.html?raw";

// Focused disclosure fixture; the authenticated recovery path separately returns original SEC HTML for audit.
const noTradeHtml = `<p>During the period between August 31, 2026 and September 7, 2026, Strategy did not sell any shares under its at-the-market offering program and did not purchase or sell any bitcoin.</p>
<table><tr><th>During Period August 31, 2026 to September 7, 2026</th></tr><tr><th>Security</th><th>Shares Repurchased</th><th>Aggregate Purchase Price (in millions)</th></tr><tr><td>STRC Stock</td><td>1,810,885</td><td>176.3</td></tr><tr><td>MSTR Stock</td><td>0</td><td>0</td></tr></table>`;
const auth = { Authorization: "Bearer offline-test-token-0000000000000000000000", "Content-Type": "application/json" };
function filing(ticker: Ticker): Filing {
  const accession = ticker === "MSTR" ? "0001193125-26-384402" : "0001628280-26-060809";
  const url = documentUrl(ticker, accession, "weekly.htm");
  return { ...ISSUERS[ticker], accession, form: "8-K", filedDate: "2026-09-08", reportDate: "2026-09-08", acceptedAt: "2026-09-08T08:00:15Z",
    firstSeenAt: "2026-09-08T12:25:09Z", documentFetchedAt: "2026-09-08T12:25:10Z", primaryDocumentUrl: url,
    documents: [{ url, fetchedAt: "2026-09-08T12:25:10Z", sha256: "a".repeat(64) }], baseline: false, status: "partial",
    extracted: extractWeekly(ticker === "MSTR" ? noTradeHtml : strive, ticker), attempts: 1, nextDocumentAttemptAt: 0, error: null };
}
async function seed(record: Filing, backoffUntil = 0) {
  await runInDurableObject(env.ISSUER_POLLER.getByName(record.ticker), async (_instance, state) => {
    state.storage.sql.exec("INSERT OR REPLACE INTO state(id,body) VALUES(1,?)", JSON.stringify({ ...initialState(record.ticker), initializedAt: "2026-09-07T12:00:00Z", backoffUntil }));
    state.storage.sql.exec("INSERT OR REPLACE INTO filings(accession,accepted_at,body) VALUES(?,?,?)", record.accession, record.acceptedAt, JSON.stringify(record));
  });
}
function recover(record: Filing, includeDocument = false) {
  return exports.default.fetch("https://worker.test/api/admin/reprocess", { method: "POST", headers: auth,
    body: JSON.stringify({ ticker: record.ticker, accession: record.accession, includeDocument }) });
}
// Run controlled alarms after the fixture release date; past-due native alarms can otherwise race a fake Date clock.
beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-09-14T12:30:00Z")); });
afterEach(async () => { vi.restoreAllMocks(); vi.useRealTimers(); await reset(); });

describe("explicit zero-activity treasury disclosure", () => {
  it("parses both zero BTC directions and zero ATM issuance without inventing holdings", () => {
    const result = extractWeekly(noTradeHtml, "MSTR");
    expect(result.facts).toMatchObject({ weekly_btc_purchases: 0, weekly_btc_sales: 0, common_issued_shares: 0, common_issuance_proceeds_usd: 0 });
    expect(result.facts).not.toHaveProperty("btc_holdings");
    expect(result.securities.STRC).toMatchObject({ issuedShares: 0, netIssuanceProceedsUsd: 0, repurchasedShares: 1810885, repurchaseCashUsd: 176300000 });
    expect(result.issues).toEqual([]); expect(result.missing).toEqual(["btc_holdings"]);
    expect(eligiblePublication(filing("MSTR"), Date.now(), env.NOTIFICATIONS_ACTIVE_AFTER)?.week).toBe("2026-09-07");
  });
  it.each(["missing_sale", "positive_buy", "negative_holdings", "malformed_holdings", "missing_period", "missing_capital", "historical_statement"])("rejects incomplete or invalid zero-activity case %s", kind => {
    const record = filing("MSTR"), e = record.extracted!;
    if (kind === "missing_sale") delete e.facts.weekly_btc_sales;
    if (kind === "positive_buy") e.facts.weekly_btc_purchases = 1;
    if (kind === "negative_holdings") e.facts.btc_holdings = -1;
    if (kind === "malformed_holdings") e.facts.btc_holdings = NaN;
    if (kind === "missing_period") e.periodStart = null;
    if (kind === "missing_capital") delete e.facts.common_issued_shares;
    if (kind === "historical_statement") record.extracted = extractWeekly(noTradeHtml.replace("Strategy did not", "Historically, Strategy did not"), "MSTR");
    expect(eligiblePublication(record, Date.now(), env.NOTIFICATIONS_ACTIVE_AFTER)).toBeNull();
  });
});

describe("authenticated holiday recovery", () => {
  it("upgrades a previously published receipt during the regular poll without duplicating its confirmed notification", async () => {
    const record = filing("MSTR"); record.extracted!.parserVersion = "sec-weekly-v3";
    await seed(record);
    const issuer = env.ISSUER_POLLER.getByName("MSTR"), notifier = env.REPORT_NOTIFIER.getByName("week:2026-09-07");
    await runInDurableObject(notifier, async (_instance, state) => {
      state.storage.sql.exec("INSERT INTO notification(id,body) VALUES(1,?)", JSON.stringify({ kind: "weekly", week: "2026-09-07", status: "sent", filings: [],
        publishedAt: "2026-09-08T12:29:00Z", attempts: 1, nextAttemptAt: 0, sentAt: "2026-09-08T12:29:00Z", messageId: "333333333333333333", lastError: null }));
    });
    const network = vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
      expect(String(input)).not.toContain("discord.com");
      return String(input).includes("submissions") ? new Response(null, { status: 304 }) : new Response(strategyHoliday);
    });
    expect(await issuer.poll("MSTR")).toMatchObject({ outcome: "ok", fetched: 1 });
    const upgraded = await issuer.filing(record.accession);
    expect(upgraded).toMatchObject({ status: "ready_for_review", firstSeenAt: record.firstSeenAt, acceptedAt: record.acceptedAt,
      extracted: { parserVersion: "sec-weekly-v4", facts: { btc_holdings: 845050, weekly_btc_purchases: 0, weekly_btc_sales: 0 } } });
    await evictDurableObject(issuer); await evictDurableObject(notifier);
    vi.setSystemTime(new Date(Date.now() + 30_000));
    expect(await issuer.poll("MSTR")).toMatchObject({ outcome: "ok", fetched: 0 });
    await runDurableObjectAlarm(notifier);
    expect(await notifier.status()).toMatchObject({ status: "sent", attempts: 1, messageId: "333333333333333333" });
    expect(network).toHaveBeenCalledTimes(3);
  });
  it("retains a published old-parser receipt after failed upgrade and retries after its document cooldown", async () => {
    const record = filing("MSTR"); record.extracted!.parserVersion = "sec-weekly-v3";
    await seed(record); const issuer = env.ISSUER_POLLER.getByName("MSTR");
    let available = false, documents = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async input => {
      if (String(input).includes("submissions")) return new Response(null, { status: 304 });
      documents++; return available ? new Response(strategyHoliday) : new Response("unavailable", { status: 503, headers: { "Retry-After": "300" } });
    });
    await issuer.poll("MSTR");
    expect(await issuer.filing(record.accession)).toMatchObject({ status: "partial", documents: record.documents,
      extracted: record.extracted, nextDocumentAttemptAt: Date.now() + 300_000 });
    await evictDurableObject(issuer); vi.setSystemTime(new Date(Date.now() + 30_000));
    await issuer.poll("MSTR"); expect(documents).toBe(1);
    available = true; vi.setSystemTime(new Date(Date.now() + 270_000));
    expect(await issuer.poll("MSTR")).toMatchObject({ fetched: 1 });
    expect((await issuer.filing(record.accession))?.status).toBe("ready_for_review");
  });
  it.each(["baseline", "before_activation", "too_old", "amendment", "same_version", "newer_version"])("does not automatically reparse %s records", async kind => {
    const record = filing("MSTR"); record.extracted!.parserVersion = "sec-weekly-v3";
    if (kind === "baseline") record.baseline = true;
    if (kind === "before_activation") record.firstSeenAt = "2026-09-07T23:59:59Z";
    if (kind === "too_old") record.acceptedAt = "2026-08-01T12:00:00Z";
    if (kind === "amendment") record.form = "8-K/A";
    if (kind === "same_version") record.extracted!.parserVersion = "sec-weekly-v4";
    if (kind === "newer_version") record.extracted!.parserVersion = "sec-weekly-v5";
    await seed(record);
    const network = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(null, { status: 304 }));
    expect(await env.ISSUER_POLLER.getByName("MSTR").poll("MSTR")).toMatchObject({ fetched: 0 });
    expect(network).toHaveBeenCalledTimes(1);
  });
  it("reprocesses existing Tuesday receipts, preserves provenance, and sends once with no browser", async () => {
    const mstr = filing("MSTR"), asst = filing("ASST");
    mstr.extracted = { ...extractWeekly(noTradeHtml, "MSTR"), parserVersion: "sec-weekly-v2", facts: {} };
    await seed(mstr); await seed(asst);
    const sent: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input).startsWith("https://discord.com")) { sent.push(String(init?.body)); return Response.json({ id: "333333333333333333" }); }
      return new Response(String(input).includes("1920406") ? strive : noTradeHtml);
    });
    const first = await recover(mstr, true);
    expect(first.headers.get("Cache-Control")).toBe("no-store");
    const body = await first.json<{ filing: Filing; document: { html: string; sha256: string } }>();
    expect(body.document.html).toBe(noTradeHtml);
    expect(body.document.sha256).toBe(body.filing.documents[0].sha256);
    expect(body.filing.firstSeenAt).toBe(mstr.firstSeenAt); expect(body.filing.acceptedAt).toBe(mstr.acceptedAt);
    const notifier = env.REPORT_NOTIFIER.getByName("week:2026-09-07");
    await runDurableObjectAlarm(notifier); expect(sent).toHaveLength(0);
    expect(await (await recover(asst)).json()).toMatchObject({ outcome: "reprocessed" });
    expect(await env.ISSUER_POLLER.getByName("MSTR").publicationStatus()).toMatchObject([{ status: "delivered" }]);
    expect(await env.ISSUER_POLLER.getByName("ASST").publicationStatus()).toMatchObject([{ status: "delivered" }]);
    await runDurableObjectAlarm(notifier);
    expect(await notifier.status()).toMatchObject({ status: "sent" });
    expect(sent).toHaveLength(1); expect(sent[0]).toContain("week of 2026-09-07");
    expect(sent[0]).toContain("Bought 0 BTC"); expect(sent[0]).toContain("Sold 0 BTC");
    await evictDurableObject(notifier); await evictDurableObject(env.ISSUER_POLLER.getByName("MSTR"));
    vi.setSystemTime(new Date("2026-09-14T13:31:00Z"));
    await Promise.all([recover(mstr), recover(asst)]); await runDurableObjectAlarm(notifier);
    expect(sent).toHaveLength(1);
    expect(await env.ISSUER_POLLER.getByName("MSTR").publicationStatus()).toMatchObject([{ status: "delivered", attempts: 1 }]);
  });
  it("does not bypass SEC cooldown or discard the published receipt on a failed refetch", async () => {
    const record = filing("MSTR"), issuer = env.ISSUER_POLLER.getByName("MSTR");
    await seed(record, Date.now() + 900_000);
    const network = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("rate", { status: 429, headers: { "Retry-After": "1800" } }));
    expect(await (await recover(record)).json()).toMatchObject({ outcome: "backoff" }); expect(network).not.toHaveBeenCalled();
    vi.setSystemTime(new Date(Date.now() + 900_000));
    expect(await (await recover(record)).json()).toMatchObject({ outcome: "error", backoffUntil: Date.now() + 1_800_000 });
    expect((await issuer.filing(record.accession))?.documents).toEqual(record.documents);
    expect(await (await recover(record)).json()).toMatchObject({ outcome: "backoff" }); expect(network).toHaveBeenCalledTimes(1);
  });
  it.each(["baseline", "before_activation", "too_old", "unknown", "untrusted_url"])("rejects recovery of %s receipts", async kind => {
    const record = filing("MSTR");
    if (kind === "baseline") record.baseline = true;
    if (kind === "before_activation") record.firstSeenAt = "2026-09-07T23:59:59Z";
    if (kind === "too_old") record.acceptedAt = "2026-08-01T12:00:00Z";
    if (kind === "untrusted_url") record.primaryDocumentUrl = "https://example.com/weekly.htm";
    if (kind !== "unknown") await seed(record);
    const network = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No network"));
    expect((await recover(record)).status).toBe(409); expect(network).not.toHaveBeenCalled();
  });
  it("protects recovery input and keeps public feed reads read-only", async () => {
    const network = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No network"));
    const endpoint = "https://worker.test/api/admin/reprocess";
    expect((await exports.default.fetch(endpoint, { method: "POST", body: "{}" })).status).toBe(401);
    expect((await exports.default.fetch(endpoint, { headers: auth })).status).toBe(405);
    for (const body of ["invalid", "x".repeat(2048), JSON.stringify({ ticker: "MSTR", accession: filing("MSTR").accession, url: "https://example.com" })])
      expect((await exports.default.fetch(endpoint, { method: "POST", headers: auth, body })).status).toBe(400);
    await exports.default.fetch("https://worker.test/api/filings"); expect(network).not.toHaveBeenCalled();
  });
});
