import { env, exports } from "cloudflare:workers";
import { evictDurableObject, reset, runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Filing } from "../src/types";
import strategy from "./fixtures/strategy-20260831.html?raw";
const initialAccession = "0001193125-26-375463";
function submissions(accessions = [initialAccession], forms = ["8-K"]): string {
  return JSON.stringify({ cik: "1050446", filings: { recent: {
    accessionNumber: accessions, form: forms,
    filingDate: accessions.map(() => "2026-08-31"), reportDate: accessions.map(() => "2026-08-31"),
    acceptanceDateTime: accessions.map(() => "2026-08-31T12:00:15.000Z"),
    primaryDocument: accessions.map(() => "mstr-20260831.htm"),
  } } });
}
const auth = { Authorization: "Bearer offline-test-token-0000000000000000000000" };
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-14T12:00:00Z"));
});
afterEach(async () => { vi.restoreAllMocks(); vi.useRealTimers(); await reset(); });
describe("durable poller integration", () => {
  it("baselines existing filings, deduplicates receipts, and detects a separate amendment after eviction", async () => {
    let discovery = submissions();
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async input => new Response(String(input).includes("submissions") ? discovery : strategy));
    const stub = env.ISSUER_POLLER.getByName("MSTR");
    expect(await stub.poll("MSTR", true)).toMatchObject({ outcome: "ok", discovered: 0, fetched: 1 });
    const first = (await stub.filings())[0];
    expect(first.baseline).toBe(true); expect(first.status).toBe("ready_for_review");
    expect(first.documentFetchedAt).toBe("2026-09-14T12:00:00.000Z");
    expect(first.documents[0].sha256).toMatch(/^[a-f0-9]{64}$/);
    await evictDurableObject(stub);
    vi.setSystemTime(new Date("2026-09-14T12:00:30Z"));
    expect(await stub.poll("MSTR", true)).toMatchObject({ outcome: "ok", discovered: 0, fetched: 0 });
    expect((await stub.filings())[0]).toEqual(first);
    discovery = submissions(["0001193125-26-375464", initialAccession], ["8-K/A", "8-K"]);
    vi.setSystemTime(new Date("2026-09-14T12:01:00Z"));
    expect(await stub.poll("MSTR", true)).toMatchObject({ outcome: "ok", discovered: 1, fetched: 1 });
    const amendment = (await stub.filings()).find(f => f.form === "8-K/A");
    expect(amendment?.baseline).toBe(false); expect(amendment?.firstSeenAt).toBe("2026-09-14T12:01:00.000Z");
    expect(fetcher).toHaveBeenCalledTimes(5);
  });
  it("does not fetch outside Monday pre-open, and stops an alarm at 09:30 Eastern", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(submissions()));
    const stub = env.ISSUER_POLLER.getByName("MSTR");
    vi.setSystemTime(new Date("2026-09-14T13:30:00Z"));
    expect(await stub.poll("MSTR")).toMatchObject({ outcome: "outside_window" });
    expect(fetcher).not.toHaveBeenCalled();
    await runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec("INSERT INTO state(id,body) VALUES(1,?)", JSON.stringify({ ticker: "MSTR" }));
      await state.storage.setAlarm(Date.now() + 30000);
    });
    expect(await runDurableObjectAlarm(stub)).toBe(true);
    expect(await runDurableObjectAlarm(stub)).toBe(false);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("arms a real durable alarm, skips an early cron tick, then polls at thirty seconds", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async input => new Response(String(input).includes("submissions") ? submissions() : strategy));
    const stub = env.ISSUER_POLLER.getByName("MSTR");
    await stub.poll("MSTR");
    expect((await stub.status("MSTR")).nextAlarmAt).toBe(Date.parse("2026-09-14T12:00:30Z"));
    expect(await stub.poll("MSTR")).toMatchObject({ outcome: "not_due" });
    vi.setSystemTime(new Date("2026-09-14T12:00:30Z"));
    expect(await runDurableObjectAlarm(stub)).toBe(true);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect((await stub.status("MSTR")).nextAlarmAt).toBe(Date.parse("2026-09-14T12:01:00Z"));
  });
  it("backs off a 403 without a manual override or disguised retry", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("blocked", { status: 403 }));
    const stub = env.ISSUER_POLLER.getByName("MSTR");
    expect(await stub.poll("MSTR", true)).toMatchObject({ outcome: "error", error: "SEC HTTP 403" });
    vi.setSystemTime(new Date("2026-09-14T12:00:31Z"));
    expect(await stub.poll("MSTR", true)).toMatchObject({ outcome: "backoff" });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect((await stub.status("MSTR")).backoffUntil).toBe(Date.parse("2026-09-14T12:30:00Z"));
  });
  it("honors a 429 Retry-After", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("rate", { status: 429, headers: { "Retry-After": "900" } }));
    const stub = env.ISSUER_POLLER.getByName("MSTR");
    await stub.poll("MSTR", true);
    expect((await stub.status("MSTR")).backoffUntil).toBe(Date.parse("2026-09-14T12:15:00Z"));
  });
  it("retries a document that is not ready without changing first-seen or acceptance timestamps", async () => {
    let ready = false;
    vi.spyOn(globalThis, "fetch").mockImplementation(async input => String(input).includes("submissions")
      ? new Response(submissions()) : ready ? new Response(strategy) : new Response("not ready", { status: 404 }));
    const stub = env.ISSUER_POLLER.getByName("MSTR");
    await stub.poll("MSTR", true);
    const pending = (await stub.filings())[0];
    expect(pending.status).toBe("document_error"); expect(pending.documentFetchedAt).toBeNull();
    ready = true; vi.setSystemTime(new Date("2026-09-14T12:00:30Z"));
    await stub.poll("MSTR", true);
    const parsed = (await stub.filings())[0];
    expect(parsed.status).toBe("ready_for_review"); expect(parsed.attempts).toBe(2);
    expect(parsed.firstSeenAt).toBe(pending.firstSeenAt); expect(parsed.acceptedAt).toBe(pending.acceptedAt);
    expect(parsed.documentFetchedAt).toBe("2026-09-14T12:00:30.000Z");
  });
  it("keeps cached filings after a network timeout", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async input => new Response(String(input).includes("submissions") ? submissions() : strategy));
    const stub = env.ISSUER_POLLER.getByName("MSTR");
    await stub.poll("MSTR", true); const before = await stub.filings();
    fetcher.mockRejectedValue(new DOMException("aborted", "AbortError"));
    vi.setSystemTime(new Date("2026-09-14T12:00:30Z"));
    expect(await stub.poll("MSTR", true)).toMatchObject({ outcome: "error", error: "SEC request timeout" });
    expect(await stub.filings()).toEqual(before);
  });
  it("serializes concurrent polls within one issuer", async () => {
    const stub = env.ISSUER_POLLER.getByName("MSTR");
    await runInDurableObject(stub, async instance => {
      let release: () => void = () => {};
      const fetcher = vi.spyOn(globalThis, "fetch").mockImplementationOnce(async () => {
        await new Promise<void>(resolve => { release = resolve; });
        return new Response(submissions());
      }).mockImplementation(async () => new Response(strategy));
      const first = instance.poll("MSTR", true);
      expect(await instance.poll("MSTR", true)).toMatchObject({ outcome: "busy" });
      release(); await first;
      expect(fetcher).toHaveBeenCalledTimes(2);
    });
  });
});
describe("public read routes and protected replay", () => {
  it("serves cached read-only status and feed without contacting SEC", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Public request must not poll"));
    const status = await exports.default.fetch("https://worker.test/api/status");
    expect(status.headers.get("Cache-Control")).toBe("public, max-age=15");
    const body = await status.json<{ schemaVersion: number; issuers: { ticker: string }[] }>();
    expect(body.schemaVersion).toBe(1); expect(body.issuers.map(i => i.ticker)).toEqual(["MSTR", "ASST"]);
    const feed = await exports.default.fetch("https://worker.test/api/filings");
    expect((await feed.json<{ filings: Filing[] }>()).filings).toEqual([]);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("denies unauthenticated mutations and GET requests to admin endpoints", async () => {
    expect((await exports.default.fetch("https://worker.test/api/admin/poll", { method: "POST" })).status).toBe(401);
    expect((await exports.default.fetch("https://worker.test/api/admin/poll", { headers: auth })).status).toBe(405);
  });
  it("replays real HTML twice with durable deduplication and no live publication", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Replay must be offline"));
    const request = { method: "POST", headers: { ...auth, "Content-Type": "application/json" }, body: JSON.stringify({ ticker: "MSTR", replayId: "deployment-test", html: strategy }) };
    const first = await exports.default.fetch("https://worker.test/api/admin/replay", request);
    expect(await first.json()).toMatchObject({ simulation: true, outcome: "validated_for_review", livePublicationChanged: false });
    const second = await exports.default.fetch("https://worker.test/api/admin/replay", request);
    expect(await second.json()).toMatchObject({ simulation: true, outcome: "duplicate" });
    expect(await env.ISSUER_POLLER.getByName("MSTR").filings()).toEqual([]);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
