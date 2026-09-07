import { env, exports } from "cloudflare:workers";
import { evictDurableObject, reset, runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { eligiblePublication, type PublicationEvent } from "../src/feed";
import { documentUrl } from "../src/sec";
import { ISSUERS, initialState, type Filing, type Ticker } from "../src/types";
import { extractWeekly } from "../src/parser";
import strategy from "./fixtures/strategy-20260831.html?raw";
import strive from "./fixtures/strive-20260831.html?raw";

const week = "2026-09-14";
function record(ticker: Ticker): Filing {
  const accession = ticker === "MSTR" ? "0001193125-26-375465" : "0001628280-26-059469";
  const url = documentUrl(ticker, accession, "weekly.htm");
  return { ...ISSUERS[ticker], accession, form: "8-K", filedDate: week, reportDate: week,
    acceptedAt: `${week}T11:00:00Z`, firstSeenAt: `${week}T11:00:10Z`, documentFetchedAt: `${week}T11:00:20Z`,
    primaryDocumentUrl: url, documents: [{ url, fetchedAt: `${week}T11:00:20Z`, sha256: "a".repeat(64) }], baseline: false,
    status: "ready_for_review", extracted: extractWeekly(ticker === "MSTR" ? strategy : strive, ticker), attempts: 1, nextDocumentAttemptAt: 0, error: null };
}
async function seed(ticker: Ticker, outbox = false): Promise<PublicationEvent> {
  const filing = record(ticker), event = eligiblePublication(filing, Date.now(), env.NOTIFICATIONS_ACTIVE_AFTER)!;
  await runInDurableObject(env.ISSUER_POLLER.getByName(ticker), async (_instance, state) => {
    state.storage.sql.exec("INSERT OR REPLACE INTO state(id,body) VALUES(1,?)", JSON.stringify({ ...initialState(ticker), initializedAt: `${week}T10:00:00Z` }));
    state.storage.sql.exec("INSERT OR REPLACE INTO filings(accession,accepted_at,body) VALUES(?,?,?)", filing.accession, filing.acceptedAt, JSON.stringify(filing));
    if (outbox) {
      state.storage.sql.exec("INSERT INTO publication_outbox(accession,body,status,attempts,next_attempt_at) VALUES(?,?,'pending',0,?)", filing.accession, JSON.stringify(event), Date.now());
      await state.storage.setAlarm(Date.now() + 1000);
    }
  });
  return event;
}
function submissions(ticker: Ticker): string {
  const filing = record(ticker);
  return JSON.stringify({ cik: Number(ISSUERS[ticker].cik), filings: { recent: { accessionNumber: [filing.accession], form: ["8-K"], filingDate: [week], reportDate: [week],
    acceptanceDateTime: [filing.acceptedAt], primaryDocument: ["weekly.htm"] } } });
}
beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date(`${week}T12:00:00Z`)); });
afterEach(async () => { vi.restoreAllMocks(); vi.useRealTimers(); await reset(); });

describe("issuer publication outbox", () => {
  it("ingests two new SEC documents, publishes the feed and sends one Discord message with no browser session", async () => {
    const sent: string[] = [];
    const network = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.startsWith("https://discord.com")) { sent.push(String(init?.body)); return Response.json({ id: "333333333333333333" }); }
      const ticker = /1920406/.test(url) ? "ASST" : "MSTR";
      return new Response(url.includes("submissions") ? submissions(ticker) : ticker === "MSTR" ? strategy : strive);
    });
    for (const ticker of ["MSTR", "ASST"] as const) {
      const stub = env.ISSUER_POLLER.getByName(ticker);
      await runInDurableObject(stub, async (_instance, state) => state.storage.sql.exec("INSERT INTO state(id,body) VALUES(1,?)", JSON.stringify({ ...initialState(ticker), initializedAt: `${week}T10:00:00Z` })));
      expect(await stub.poll(ticker)).toMatchObject({ outcome: "ok", discovered: 1, fetched: 1 });
      expect(await stub.publicationStatus()).toMatchObject([{ status: "delivered", attempts: 1 }]);
    }
    expect(sent).toHaveLength(0);
    const notifier = env.REPORT_NOTIFIER.getByName(`week:${week}`);
    await runDurableObjectAlarm(notifier);
    expect(sent).toHaveLength(1);
    expect(await notifier.status()).toMatchObject({ status: "sent", publication: { status: "published" } });
    const feed = await (await exports.default.fetch("https://worker.test/api/filings")).json<{ filings: Filing[] }>();
    expect(feed.filings).toHaveLength(2);
    expect(network).toHaveBeenCalledTimes(5);
    await evictDurableObject(notifier); await runDurableObjectAlarm(notifier);
    expect(sent).toHaveLength(1);
  });
  it("keeps a failed coordinator handoff durable across eviction and retries after SEC polling closes", async () => {
    vi.setSystemTime(new Date(`${week}T13:29:55Z`));
    await seed("MSTR", true);
    const notifier = env.REPORT_NOTIFIER.getByName(`week:${week}`), issuer = env.ISSUER_POLLER.getByName("MSTR");
    await runInDurableObject(issuer, async instance => {
      const relay = vi.spyOn(instance, "relayToNotifier").mockRejectedValueOnce(new Error("RPC unavailable"));
      await instance.relayPublications(); relay.mockRestore();
    });
    expect(await issuer.publicationStatus()).toMatchObject([{ status: "pending", attempts: 1, error: "Notification coordinator handoff failed" }]);
    expect(await issuer.status("MSTR")).toMatchObject({ failures: 0, backoffUntil: 0, nextAlarmAt: Date.parse(`${week}T13:30:10Z`) });
    await evictDurableObject(issuer);
    vi.setSystemTime(new Date(`${week}T13:30:10Z`));
    const network = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No SEC fetch after pre-open"));
    await runDurableObjectAlarm(issuer);
    expect(await issuer.publicationStatus()).toMatchObject([{ status: "delivered", attempts: 2 }]);
    expect(network).not.toHaveBeenCalled();
    expect((await issuer.status("MSTR")).nextAlarmAt).toBeNull();
  });
  it("retains an alarm when another alarm fires during an in-flight handoff", async () => {
    vi.setSystemTime(new Date(`${week}T13:30:00Z`));
    await seed("MSTR", true);
    const issuer = env.ISSUER_POLLER.getByName("MSTR"), notifier = env.REPORT_NOTIFIER.getByName(`week:${week}`);
    await runInDurableObject(issuer, async (instance, state) => {
      let release: () => void = () => {}, started: () => void = () => {};
      const ready = new Promise<void>(resolve => { started = resolve; });
      const handoff = vi.spyOn(instance, "relayToNotifier").mockImplementationOnce(async () => { started(); await new Promise<void>(resolve => { release = resolve; }); throw new Error("Interrupted handoff"); });
      const relay = instance.relayPublications(); await ready;
      vi.setSystemTime(new Date(`${week}T13:31:00Z`));
      await state.storage.deleteAlarm(); await instance.alarm();
      expect((await instance.status("MSTR")).nextAlarmAt).toBeGreaterThan(Date.now());
      release(); await relay; handoff.mockRestore();
    });
    await evictDurableObject(issuer);
    vi.setSystemTime(new Date(`${week}T13:31:15Z`)); await runDurableObjectAlarm(issuer);
    expect(await issuer.publicationStatus()).toMatchObject([{ status: "delivered", attempts: 2 }]);
  });
  it("rolls back the publication event if the receipt recovery alarm cannot commit", async () => {
    const issuer = env.ISSUER_POLLER.getByName("MSTR");
    vi.spyOn(globalThis, "fetch").mockImplementation(async input => new Response(String(input).includes("submissions") ? submissions("MSTR") : strategy));
    await runInDurableObject(issuer, async (instance, state) => {
      state.storage.sql.exec("INSERT INTO state(id,body) VALUES(1,?)", JSON.stringify({ ...initialState("MSTR"), initializedAt: `${week}T10:00:00Z` }));
      const original = state.storage.setAlarm.bind(state.storage);
      const alarm = vi.spyOn(state.storage, "setAlarm").mockImplementation(async time => {
        const pending = state.storage.sql.exec<{ count: number }>("SELECT COUNT(*) AS count FROM publication_outbox").one().count;
        if (pending) throw new Error("Alarm persistence unavailable");
        return original(time);
      });
      await instance.poll("MSTR"); alarm.mockRestore();
      expect(await instance.publicationStatus()).toEqual([]);
      expect((await instance.filings())[0].status).toBe("document_error");
    });
  });
});

describe("shared projection verification and event races", () => {
  it("delays notification until exact candidate hashes appear in the public projection", async () => {
    const mstr = await seed("MSTR"), asst = await seed("ASST");
    const notifier = env.REPORT_NOTIFIER.getByName(`week:${week}`), issuer = env.ISSUER_POLLER.getByName("ASST");
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json({ id: "333333333333333333" }));
    await notifier.candidate(mstr); await notifier.candidate(asst);
    await runInDurableObject(notifier, async instance => {
      const projection = vi.spyOn(instance, "loadPublishedFeed").mockResolvedValueOnce({ schemaVersion: 1, generatedAt: new Date().toISOString(), publicationMode: "reported_facts_for_review", filings: [] });
      await instance.alarm(); projection.mockRestore();
    });
    expect(send).not.toHaveBeenCalled();
    expect(await notifier.status()).toMatchObject({ publication: { status: "retry", nextCheckAt: Date.now() + 15_000 } });
    await evictDurableObject(notifier); vi.setSystemTime(new Date(`${week}T12:00:15Z`)); await runDurableObjectAlarm(notifier);
    expect(send).toHaveBeenCalledTimes(1);
  });
  it("keeps a new candidate arriving during feed verification for the next check", async () => {
    const mstr = await seed("MSTR"), asst = await seed("ASST");
    const notifier = env.REPORT_NOTIFIER.getByName(`week:${week}`), issuer = env.ISSUER_POLLER.getByName("ASST");
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json({ id: "333333333333333333" }));
    await notifier.candidate(mstr); await notifier.candidate({ ...asst, filing: { ...asst.filing, sha256: "b".repeat(64) } });
    await runInDurableObject(notifier, async instance => {
      let release: () => void = () => {}, started: () => void = () => {};
      const ready = new Promise<void>(resolve => { started = resolve; });
      const projection = vi.spyOn(instance, "loadPublishedFeed").mockImplementationOnce(async () => {
        started(); await new Promise<void>(resolve => { release = resolve; });
        return { schemaVersion: 1, generatedAt: new Date().toISOString(), publicationMode: "reported_facts_for_review", filings: [record("MSTR"), record("ASST")] };
      });
      const check = instance.alarm(); await ready;
      await instance.candidate(asst); release(); await check; projection.mockRestore();
    });
    expect(send).not.toHaveBeenCalled();
    expect(await notifier.status()).toMatchObject({ publication: { revision: 3, nextCheckAt: Date.now() + 1 } });
    vi.setSystemTime(new Date(Date.now() + 1)); await runDurableObjectAlarm(notifier);
    expect(send).toHaveBeenCalledTimes(1);
  });
  it("retains a pre-upgrade sent record and Discord retry deadline when new candidates arrive", async () => {
    const mstr = await seed("MSTR"), asst = await seed("ASST");
    const notifier = env.REPORT_NOTIFIER.getByName(`week:${week}`);
    const send = vi.spyOn(globalThis, "fetch").mockImplementation(async () => Response.json({ id: "333333333333333333" }));
    await runInDurableObject(notifier, async (_instance, state) => {
      state.storage.sql.exec("INSERT INTO notification(id,body) VALUES(1,?)", JSON.stringify({ kind: "weekly", week, status: "retry", filings: [mstr.filing, asst.filing],
        acknowledgedAt: `${week}T11:59:00Z`, attempts: 1, nextAttemptAt: Date.now() + 3_600_000, sentAt: null, messageId: null, lastError: "Discord HTTP 429" }));
    });
    await notifier.candidate(mstr); await notifier.candidate(asst);
    expect((await notifier.status()).nextAlarmAt).toBe(Date.now() + 3_600_000);
    await runDurableObjectAlarm(notifier); expect(send).not.toHaveBeenCalled();
    vi.setSystemTime(new Date(`${week}T13:00:00Z`)); await runDurableObjectAlarm(notifier);
    await evictDurableObject(notifier); await notifier.candidate(mstr); await notifier.candidate(asst);
    expect(await notifier.status()).toMatchObject({ status: "sent", messageId: "333333333333333333" });
    expect(send).toHaveBeenCalledTimes(1);
  });
});
