import { env } from "cloudflare:workers";
import { evictDurableObject, reset, runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { extractWeekly } from "../src/parser";
import { eligiblePublication, validateReceipt } from "../src/feed";
import { documentUrl } from "../src/sec";
import { ISSUERS, type Filing, type Ticker } from "../src/types";

const period = "During the period from September 7, 2026 through September 13, 2026";
const weekly = (body: string) => `<html><p>${period}.</p>${body}</html>`;
function activityTable(headers: string[], cells: string[], caption = "Weekly Bitcoin activity"): string {
  return `<table><caption>${caption}</caption><tr>${headers.map(text => `<th>${text}</th>`).join("")}</tr><tr>${cells.map(text => `<td>${text}</td>`).join("")}</tr></table>`;
}
function record(ticker: Ticker, html: string): Filing {
  const accession = ticker === "MSTR" ? "0001193125-26-375465" : "0001628280-26-059469";
  const url = documentUrl(ticker, accession, "weekly.htm");
  return { ...ISSUERS[ticker], accession, form: "8-K", filedDate: "2026-09-14", reportDate: "2026-09-13",
    acceptedAt: "2026-09-14T11:00:00Z", firstSeenAt: "2026-09-14T11:00:10Z", documentFetchedAt: "2026-09-14T11:00:20Z",
    primaryDocumentUrl: url, documents: [{ url, fetchedAt: "2026-09-14T11:00:20Z", sha256: "a".repeat(64) }], baseline: false,
    status: "partial", extracted: extractWeekly(html, ticker), attempts: 1, nextDocumentAttemptAt: 0, error: null };
}
beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-09-14T12:00:00Z")); });
afterEach(async () => { vi.restoreAllMocks(); vi.useRealTimers(); await reset(); });

describe("explicit weekly BTC purchases and sales", () => {
  it.each(["MSTR", "ASST"] as const)("parses a %s sales-only table, independent of dollar proceeds", ticker => {
    const result = extractWeekly(weekly(activityTable(["BTC Sold", "Aggregate Sale Proceeds (in millions)", "Aggregate BTC Holdings"], ["1,250.5", "$", "98.6", "20,000"])), ticker);
    expect(result.issues).toEqual([]);
    expect(result.facts).toMatchObject({ weekly_btc_sales: 1250.5, btc_holdings: 20000 });
    expect(result.facts).not.toHaveProperty("weekly_btc_purchases");
    expect(result.missing).not.toContain("weekly_btc_activity");
  });
  it.each(["MSTR", "ASST"] as const)("keeps %s gross buys and sales in separately labelled columns", ticker => {
    const result = extractWeekly(weekly(activityTable(["BTC Purchased", "BTC Sold", "Sale Proceeds (USD)", "Aggregate BTC Holdings"], ["100", "25", "$2,000,000", "5,075"])), ticker);
    expect(result.issues).toEqual([]);
    expect(result.facts).toMatchObject({ weekly_btc_purchases: 100, weekly_btc_sales: 25, btc_holdings: 5075 });
  });
  it.each(["Strategy", "Strive"])("parses %s weekly prose and retains a coordinated sale", issuer => {
    const result = extractWeekly(weekly(`<p>During the reporting period, ${issuer} purchased 100 bitcoin and subsequently sold 25 bitcoin.</p><p>As of September 13, 2026, ${issuer} held 5,075 bitcoin.</p>`), issuer === "Strategy" ? "MSTR" : "ASST");
    expect(result.issues).toEqual([]);
    expect(result.facts).toMatchObject({ weekly_btc_purchases: 100, weekly_btc_sales: 25, btc_holdings: 5075 });
  });
  it("supports sales-only prose and explicit zero holdings after a full liquidation", () => {
    const result = extractWeekly(`<p>${period}, Strive sold 23,156 bitcoin for cash.</p><p>As of September 13, 2026, Strive held 0 bitcoin.</p>`, "ASST");
    expect(result.facts).toMatchObject({ weekly_btc_sales: 23156, btc_holdings: 0 });
    expect(result.facts).not.toHaveProperty("weekly_btc_purchases");
  });
  it.each(["sold", "bought", "acquired"])("supports disclosed approximate quantities with the verb %s", verb => {
    const result = extractWeekly(weekly(`<p>During the reporting period, Strategy ${verb} approximately 704 bitcoins.</p>`), "MSTR");
    expect(result.facts[verb === "sold" ? "weekly_btc_sales" : "weekly_btc_purchases"]).toBe(704);
  });
  it("reads label/value rows without treating ending holdings as a sale", () => {
    const result = extractWeekly(weekly("<table><caption>Weekly Bitcoin activity</caption><tr><td>Bitcoin purchased</td><td>100</td></tr><tr><td>Bitcoin sold</td><td>25</td></tr><tr><td>Bitcoin held</td><td>5,075</td></tr></table>"), "ASST");
    expect(result.issues).toEqual([]);
    expect(result.facts).toMatchObject({ weekly_btc_purchases: 100, weekly_btc_sales: 25, btc_holdings: 5075 });
  });
  it("retains explicit zero activity without filling an absent other side", () => {
    const result = extractWeekly(weekly(activityTable(["BTC Sold", "Aggregate BTC Holdings"], ["0", "0"])), "MSTR");
    expect(result.facts).toMatchObject({ weekly_btc_sales: 0, btc_holdings: 0 });
    expect(result.facts).not.toHaveProperty("weekly_btc_purchases");
  });
  it.each(["-25", "(25)", "$25", "1,2,3", "N/A"])("flags an invalid BTC quantity %s without disguising it as zero", quantity => {
    const result = extractWeekly(weekly(activityTable(["BTC Purchased", "BTC Sold", "Aggregate BTC Holdings"], ["100", quantity, "5075"])), "MSTR");
    expect(result.issues.some(issue => /weekly_btc_sales|BTC activity:/.test(issue))).toBe(true);
    expect(result.facts).not.toHaveProperty("weekly_btc_sales");
  });
  it("does not infer trades from a negative holdings change, equity sales, or USD sale proceeds", () => {
    const html = weekly("<p>During the reporting period, Strive sold 1,000 shares of common stock for $20,000. Bitcoin holdings decreased by 25 due to transfers.</p>"
      + activityTable(["BTC Sales Proceeds (USD)", "Aggregate BTC Holdings"], ["$2,000,000", "5075"]));
    const result = extractWeekly(html, "ASST");
    expect(result.facts).not.toHaveProperty("weekly_btc_sales");
    expect(result.facts).not.toHaveProperty("weekly_btc_purchases");
  });
  it("does not extract cumulative trades merely because the filing also contains weekly dates", () => {
    const result = extractWeekly(weekly("<p>Since inception, Strive purchased 1,000 bitcoin.</p><p>During the reporting period, Strive stated that it has cumulatively sold 100 bitcoin since inception.</p>"
      + activityTable(["BTC Sold", "Aggregate BTC Holdings"], ["100", "5075"], "Cumulative BTC sales since inception")), "ASST");
    expect(result.facts).not.toHaveProperty("weekly_btc_sales");
    expect(result.facts).not.toHaveProperty("weekly_btc_purchases");
  });
  it("flags conflicting weekly activity quantities for review", () => {
    const result = extractWeekly(weekly(`<p>During the reporting period, Strategy sold 25 bitcoin.</p>${activityTable(["BTC Sold", "Aggregate BTC Holdings"], ["30", "5075"])}`), "MSTR");
    expect(result.issues).toContain("Conflicting weekly_btc_sales values");
  });
});

describe("BTC activity publication eligibility and Discord", () => {
  const validHtml = weekly(activityTable(["BTC Sold", "Aggregate BTC Holdings"], ["25", "0"]));
  it("qualifies sales-only and zero-holdings receipts without changing outbox event keys", () => {
    const filing = record("MSTR", validHtml);
    const event = eligiblePublication(filing, Date.now(), env.NOTIFICATIONS_ACTIVE_AFTER);
    expect(event).not.toBeNull();
    expect(Object.keys(event!.filing).sort()).toEqual(["accession", "sha256", "ticker", "url"]);
  });
  it.each([
    { btc_holdings: 0, weekly_btc_sales: 0 },
    { btc_holdings: 100, weekly_btc_purchases: 20, weekly_btc_sales: 5 },
    { btc_holdings: 100, weekly_btc_purchases: 0 },
  ])("allows explicit nonnegative gross activity %j", facts => {
    const filing = record("MSTR", validHtml); filing.extracted!.facts = JSON.parse(JSON.stringify(facts));
    expect(eligiblePublication(filing, Date.now(), env.NOTIFICATIONS_ACTIVE_AFTER)).not.toBeNull();
  });
  it.each([
    { btc_holdings: 100 }, { btc_holdings: -1, weekly_btc_sales: 25 },
    { btc_holdings: 100, weekly_btc_purchases: 20, weekly_btc_sales: -5 },
    { btc_holdings: 100, weekly_btc_purchases: -1, weekly_btc_sales: 5 },
    { btc_holdings: 100, weekly_btc_sales: "25" },
    { btc_holdings: 100, weekly_btc_purchases: 20, weekly_btc_sales: null },
    { btc_holdings: 100, weekly_btc_sales: Infinity },
  ])("rejects absent or malformed supplied gross activity %j", facts => {
    const filing = record("MSTR", validHtml); filing.extracted!.facts = JSON.parse(JSON.stringify(facts));
    expect(eligiblePublication(filing, Date.now(), env.NOTIFICATIONS_ACTIVE_AFTER)).toBeNull();
  });
  it.each(["Invalid weekly_btc_sales quantity", "Conflicting weekly_btc_purchases values", "Reporting period is reversed", "Strive table and purchase period dates disagree"])("rejects a partial receipt carrying %s", issue => {
    const filing = record("MSTR", validHtml); filing.extracted!.issues.push(issue);
    expect(validateReceipt(filing, { ticker: filing.ticker, accession: filing.accession, sha256: filing.documents[0].sha256 }, Date.now())).toBeNull();
  });
  it("notifies both gross directions once, and does not duplicate after sales candidate replay or restart", async () => {
    const sent: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => { sent.push(String(init?.body)); return Response.json({ id: "444444444444444444" }); });
    const notifier = env.REPORT_NOTIFIER.getByName("week:2026-09-14");
    const events = [];
    for (const ticker of ["MSTR", "ASST"] as const) {
      const html = ticker === "MSTR" ? weekly(activityTable(["BTC Purchased", "BTC Sold", "Aggregate BTC Holdings"], ["100", "25", "5075"]))
        : weekly(activityTable(["BTC Sold", "Aggregate BTC Holdings"], ["0.000000001", "0"]));
      const filing = record(ticker, html), event = eligiblePublication(filing, Date.now(), env.NOTIFICATIONS_ACTIVE_AFTER)!;
      await runInDurableObject(env.ISSUER_POLLER.getByName(ticker), async (_instance, state) => {
        state.storage.sql.exec("INSERT INTO filings(accession,accepted_at,body) VALUES(?,?,?)", filing.accession, filing.acceptedAt, JSON.stringify(filing));
      });
      events.push(event); await notifier.candidate(event);
    }
    await runDurableObjectAlarm(notifier);
    expect(sent).toHaveLength(1);
    expect(sent[0]).toContain("Strategy — Bought 100 BTC · Sold 25 BTC");
    expect(sent[0]).toContain("Strive — Sold <0.00000001 BTC");
    expect(sent[0]).not.toContain("Bought 75");
    await evictDurableObject(notifier);
    for (const event of events) await notifier.candidate(event);
    await runDurableObjectAlarm(notifier);
    expect(sent).toHaveLength(1);
    expect(await notifier.status()).toMatchObject({ status: "sent", messageId: "444444444444444444" });
  });
});
