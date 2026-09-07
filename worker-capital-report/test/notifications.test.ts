import { env, exports } from "cloudflare:workers";
import { evictDurableObject, reset, runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { extractWeekly } from "../src/parser";
import { documentUrl } from "../src/sec";
import { discordEndpoint, SETUP_TEST_ID } from "../src/notifications";
import { ISSUERS, type Filing, type Ticker } from "../src/types";
import strategyHtml from "./fixtures/strategy-20260831.html?raw";

const ackAuth = { Authorization: "Bearer offline-streamlit-ack-token-000000000000000000" };
const adminAuth = { Authorization: "Bearer offline-test-token-0000000000000000000000" };
const hash = "a".repeat(64);
const week = "2026-09-14";
const messageId = "222222222222222222";
function filing(ticker: Ticker): Filing {
  const accession = ticker === "MSTR" ? "0001193125-26-375465" : "0001193125-26-375466";
  const url = documentUrl(ticker, accession, "weekly.htm");
  return { ...ISSUERS[ticker], accession, form: "8-K", filedDate: week, reportDate: week,
    acceptedAt: `${week}T11:00:00.000Z`, firstSeenAt: `${week}T11:00:10.000Z`, documentFetchedAt: `${week}T11:00:20.000Z`,
    primaryDocumentUrl: url, documents: [{ url, fetchedAt: `${week}T11:00:20.000Z`, sha256: hash }], status: "ready_for_review", baseline: false,
    extracted: extractWeekly(strategyHtml, "MSTR"), attempts: 1, nextDocumentAttemptAt: 0, error: null };
}
async function seed(record: Filing): Promise<void> {
  await runInDurableObject(env.ISSUER_POLLER.getByName(record.ticker), async (_instance, state) => {
    state.storage.sql.exec("INSERT OR REPLACE INTO filings(accession,accepted_at,body) VALUES(?,?,?)", record.accession, record.acceptedAt, JSON.stringify(record));
  });
}
function ackBody() {
  return { filings: [filing("MSTR"), filing("ASST")].map(value => ({ ticker: value.ticker, accession: value.accession, sha256: hash })) };
}
function acknowledge(body: unknown = ackBody(), headers = ackAuth) {
  return exports.default.fetch("https://worker.test/api/streamlit/ack", { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
function success(): Response { return Response.json({ id: messageId }); }
beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date(`${week}T12:00:00Z`)); });
afterEach(async () => { vi.restoreAllMocks(); vi.useRealTimers(); await reset(); });

describe("Streamlit receipt gating", () => {
  it("does not notify for cached receipts alone; requires a dedicated authenticated complete acknowledgement", async () => {
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => success());
    await seed(filing("MSTR")); await seed(filing("ASST"));
    await exports.default.fetch("https://worker.test/api/filings");
    expect(send).not.toHaveBeenCalled();
    expect((await acknowledge(ackBody(), adminAuth)).status).toBe(401);
    expect((await acknowledge({ filings: [ackBody().filings[0]] })).status).toBe(400);
    expect(send).not.toHaveBeenCalled();
    expect(await (await acknowledge()).json()).toMatchObject({ outcome: "sent", week });
    expect(send).toHaveBeenCalledTimes(1);
    const [url, request] = send.mock.calls[0];
    expect(String(url)).toContain("?wait=true");
    const payload = JSON.parse(String(request?.body));
    expect(payload.allowed_mentions).toEqual({ parse: [] });
    expect(payload.content).toContain("available in the Streamlit SEC monitor");
    expect(payload.content).toContain("financial cards have not been refreshed automatically");
    expect(payload.content).toContain(filing("MSTR").primaryDocumentUrl);
    expect(payload.content).toContain(filing("ASST").primaryDocumentUrl);
  });
  it("does not notify until both issuers have a persisted primary receipt", async () => {
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => success());
    await seed(filing("MSTR"));
    expect((await acknowledge()).status).toBe(409);
    expect(send).not.toHaveBeenCalled();
  });
  it.each(["wrong_hash", "baseline", "amendment", "non_monday", "different_monday", "future", "old", "missing_btc", "pending", "untrusted_url", "unfetched", "future_fetched"])("rejects %s before Discord", async reason => {
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => success());
    const bad = filing("ASST");
    if (reason === "wrong_hash") bad.documents[0].sha256 = "b".repeat(64);
    if (reason === "baseline") bad.baseline = true;
    if (reason === "amendment") bad.form = "8-K/A";
    if (reason === "non_monday") bad.acceptedAt = "2026-09-13T11:00:00Z";
    if (reason === "different_monday") bad.acceptedAt = "2026-09-07T11:00:00Z";
    if (reason === "future") bad.acceptedAt = "2026-09-21T11:00:00Z";
    if (reason === "old") bad.acceptedAt = "2026-08-24T11:00:00Z";
    if (reason === "missing_btc") delete bad.extracted!.facts.btc_holdings;
    if (reason === "pending") bad.status = "pending";
    if (reason === "untrusted_url") bad.primaryDocumentUrl = bad.documents[0].url = "https://example.com/filing.htm";
    if (reason === "unfetched") bad.documentFetchedAt = null;
    if (reason === "future_fetched") bad.documentFetchedAt = bad.documents[0].fetchedAt = "2026-09-14T13:00:00Z";
    await seed(filing("MSTR")); await seed(bad);
    expect((await acknowledge()).status).toBe(409);
    expect(send).not.toHaveBeenCalled();
  });
  it("accepts a partial weekly extraction with both BTC facts", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => success());
    const partial = filing("ASST"); partial.status = "partial"; partial.extracted!.extractionValidated = false;
    await seed(filing("MSTR")); await seed(partial);
    expect(await (await acknowledge()).json()).toMatchObject({ outcome: "sent" });
  });
  it("bounds and validates acknowledgement JSON, including duplicate tickers and arbitrary URL fields", async () => {
    const oversized = await exports.default.fetch("https://worker.test/api/streamlit/ack", { method: "POST", headers: ackAuth, body: "x".repeat(3000) });
    expect(oversized.status).toBe(400);
    expect((await acknowledge({ filings: [ackBody().filings[0], ackBody().filings[0]] })).status).toBe(400);
    expect((await acknowledge({ ...ackBody(), url: "https://example.com" })).status).toBe(400);
  });
});

describe("durable Discord delivery", () => {
  it("deduplicates concurrent acknowledgements and retains sent state across eviction", async () => {
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => success());
    await seed(filing("MSTR")); await seed(filing("ASST"));
    await Promise.all([acknowledge(), acknowledge(), acknowledge()]);
    expect(send).toHaveBeenCalledTimes(1);
    await evictDurableObject(env.REPORT_NOTIFIER.getByName(`week:${week}`));
    expect(await (await acknowledge()).json()).toMatchObject({ outcome: "sent" });
    expect(send).toHaveBeenCalledTimes(1);
  });
  it("honors Discord's 429 delay, persists it across eviction, and retries outside the SEC window", async () => {
    const send = vi.spyOn(globalThis, "fetch").mockImplementationOnce(async () => Response.json({ retry_after: 7200.5 }, { status: 429, headers: { "Retry-After": "7200" } }))
      .mockImplementation(async () => success());
    await seed(filing("MSTR")); await seed(filing("ASST"));
    expect(await (await acknowledge()).json()).toMatchObject({ outcome: "queued" });
    const stub = env.REPORT_NOTIFIER.getByName(`week:${week}`);
    const next = Date.parse(`${week}T14:00:00Z`) + 500;
    expect((await stub.status()).nextAlarmAt).toBe(next);
    await evictDurableObject(stub);
    await acknowledge(); expect(send).toHaveBeenCalledTimes(1);
    vi.setSystemTime(new Date(next));
    expect(await runDurableObjectAlarm(stub)).toBe(true);
    expect(await stub.status()).toMatchObject({ status: "sent", attempts: 2, messageId, nextAlarmAt: null });
    expect(send).toHaveBeenCalledTimes(2);
  });
  it.each(["5xx", "timeout"])("retries a %s failure without accepting another pair", async reason => {
    const send = vi.spyOn(globalThis, "fetch").mockImplementationOnce(async () => {
      if (reason === "timeout") throw new DOMException("URL must not be logged", "AbortError");
      return new Response("service unavailable", { status: 503 });
    }).mockImplementation(async () => success());
    await seed(filing("MSTR")); await seed(filing("ASST"));
    expect(await (await acknowledge()).json()).toMatchObject({ outcome: "queued" });
    const stub = env.REPORT_NOTIFIER.getByName(`week:${week}`);
    vi.setSystemTime(new Date(Date.parse(`${week}T12:00:00Z`) + 15_000));
    await runDurableObjectAlarm(stub);
    expect(await stub.status()).toMatchObject({ status: "sent", attempts: 2 });
    expect(send).toHaveBeenCalledTimes(2);
  });
  it.each([429, 401])("retains HTTP %s policy when the response has no body", async status => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(null, { status, headers: { "Retry-After": "900" } }));
    await seed(filing("MSTR")); await seed(filing("ASST")); await acknowledge();
    const result = await env.REPORT_NOTIFIER.getByName(`week:${week}`).status();
    expect(result).toMatchObject({ status: status === 429 ? "retry" : "failed", lastError: `Discord HTTP ${status}` });
    expect(result.nextAlarmAt).toBe(status === 429 ? Date.parse(`${week}T12:15:00Z`) : null);
  });
  it("recovers a durable in-flight lease after restart", async () => {
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => success());
    const stub = env.REPORT_NOTIFIER.getByName(`week:${week}`);
    await runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec("INSERT INTO notification(id,body) VALUES(1,?)", JSON.stringify({ kind: "weekly", week, status: "sending", filings: [],
        acknowledgedAt: `${week}T11:59:00Z`, attempts: 1, nextAttemptAt: Date.now() + 60_000, sentAt: null, messageId: null, lastError: null }));
      await state.storage.setAlarm(Date.now() + 60_000);
    });
    await evictDurableObject(stub);
    vi.setSystemTime(new Date(`${week}T12:01:00Z`)); await runDurableObjectAlarm(stub);
    expect(await stub.status()).toMatchObject({ status: "sent", attempts: 2 });
    expect(send).toHaveBeenCalledTimes(1);
  });
  it("keeps a confirmed durable send when alarm cleanup fails", async () => {
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => success());
    const stub = env.REPORT_NOTIFIER.getByName(`week:${week}`);
    await runInDurableObject(stub, async (instance, state) => {
      const cleanup = vi.spyOn(state.storage, "deleteAlarm").mockRejectedValueOnce(new Error("Storage cleanup failure"));
      await instance.acknowledge(week, []);
      expect(await instance.status()).toMatchObject({ status: "sent", messageId });
      cleanup.mockRestore();
    });
    await evictDurableObject(stub);
    vi.setSystemTime(new Date(`${week}T12:01:00Z`)); await runDurableObjectAlarm(stub);
    expect(await stub.status()).toMatchObject({ status: "sent", messageId });
    expect(send).toHaveBeenCalledTimes(1);
  });
  it("stops permanent failures, keeps diagnostics private, and never leaks the webhook", async () => {
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json({ message: "Unknown Webhook" }, { status: 404 }));
    await seed(filing("MSTR")); await seed(filing("ASST"));
    const response = await (await acknowledge()).json();
    expect(response).toMatchObject({ outcome: "failed" });
    expect(JSON.stringify(response)).not.toContain("Discord HTTP");
    const stub = env.REPORT_NOTIFIER.getByName(`week:${week}`);
    expect(await stub.status()).toMatchObject({ status: "failed", nextAlarmAt: null, lastError: "Discord HTTP 404" });
    await acknowledge(); expect(send).toHaveBeenCalledTimes(1);
    expect((await exports.default.fetch("https://worker.test/api/admin/notifications", { method: "POST" })).status).toBe(401);
    const status = await exports.default.fetch("https://worker.test/api/admin/notifications", { method: "POST", headers: adminAuth });
    expect(await status.text()).not.toContain(env.DISCORD_WEBHOOK_URL);
  });
  it("uses a separate stable setup-test id and labels the message clearly", async () => {
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => success());
    for (let i = 0; i < 2; i++) await exports.default.fetch("https://worker.test/api/admin/discord-test", { method: "POST", headers: adminAuth });
    expect(send).toHaveBeenCalledTimes(1);
    expect(String(send.mock.calls[0][1]?.body)).toContain("setup test");
    expect(await env.REPORT_NOTIFIER.getByName(SETUP_TEST_ID).status()).toMatchObject({ status: "sent", kind: "test" });
    expect(await env.REPORT_NOTIFIER.getByName(`week:${week}`).status()).toMatchObject({ status: "waiting_for_streamlit" });
  });
  it("accepts only the configured Discord host and webhook path", () => {
    expect(discordEndpoint(env.DISCORD_WEBHOOK_URL)).toContain("?wait=true");
    for (const url of ["https://example.com/api/webhooks/123/test", env.DISCORD_WEBHOOK_URL + "?wait=false", env.DISCORD_WEBHOOK_URL.replace("discord.com", "discord.com.evil.test")])
      expect(discordEndpoint(url)).toBeNull();
  });
});
