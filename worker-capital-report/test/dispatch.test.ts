import { describe, expect, it, vi } from "vitest";
import { duePanelKicks, kickPanel, PLAN } from "../src/dispatch";

const at = (iso: string) => duePanelKicks(Date.parse(iso)).map(k => `${k.workflow}:${k.inputs?.mode ?? ""}`);

describe("X Control Panel clock", () => {
  it("starts the desk and the Accretion Ledger on New York time, summer and winter", () => {
    expect(at("2026-09-28T11:05:00Z")).toEqual(["agent.yml:", "monitor.yml:"]);  // Mon 07:05 EDT
    expect(at("2026-09-28T11:40:00Z")).toEqual(["showcase.yml:watch"]);           // Mon 07:40 EDT
    expect(at("2026-12-07T12:05:00Z")).toEqual(["agent.yml:", "monitor.yml:"]);  // Mon 07:05 EST
    expect(at("2026-12-07T12:40:00Z")).toEqual(["showcase.yml:watch"]);
    expect(at("2026-12-07T11:40:00Z")).toEqual([]);                               // 06:40 EST: too early
  });
  it("covers the Coupon Sheet, the Closing Mark, the weekly review and the preflights", () => {
    expect(at("2026-09-30T16:30:00Z")).toEqual(["showcase.yml:watch"]);           // Wed 12:30
    expect(at("2026-10-02T20:05:00Z")).toEqual(["showcase.yml:watch", "monitor.yml:"]);  // Fri 16:05
    expect(at("2026-10-02T20:10:00Z")).toEqual(["agent.yml:"]);                   // Fri 16:10 close desk
    expect(at("2026-10-04T21:00:00Z")).toEqual(["agent.yml:"]);                   // Sun 17:00 weekly
    expect(at("2026-10-05T00:15:00Z")).toEqual(["showcase.yml:preflight"]);       // Sun 20:15
    expect(at("2026-10-03T11:05:00Z")).toEqual(["monitor.yml:"]);                 // Saturday: no BTC desk
  });
  it("watches Tuesday too (the workflow only runs it after an EDGAR Monday holiday)", () => {
    expect(at("2026-09-08T11:40:00Z")).toEqual(["showcase.yml:watch"]);
  });
  it("keeps every time on a five-minute mark so the */5 trigger can hit it", () => {
    for (const p of PLAN) expect(Number(p.at.slice(3)) % 5).toBe(0);
  });
  it("asks GitHub to start each workflow, and does nothing without a token", async () => {
    const fetcher = vi.fn(async () => new Response(null, { status: 204 }));
    const lines = await kickPanel(Date.parse("2026-09-28T11:05:00Z"), { GH_DISPATCH_TOKEN: "t" }, fetcher as typeof fetch);
    expect(lines).toEqual(["agent.yml (pre-market desk): started", "monitor.yml (news monitor): started"]);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.github.com/repos/bobat2121-lgtm/X-Control-Panel/actions/workflows/agent.yml/dispatches");
    expect(JSON.parse(init.body as string)).toEqual({ ref: "main" });
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer t");
    expect(await kickPanel(Date.parse("2026-09-28T11:05:00Z"), {}, fetcher as typeof fetch)).toEqual([]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
