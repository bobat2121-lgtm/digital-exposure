import { describe, expect, it } from "vitest";
import { inPollingWindow, nextAlarmTime, nextWindowStart, retryDelay } from "../src/schedule";
const time = Date.parse;
describe("Monday pre-open scheduling", () => {
  it.each([
    ["2026-09-14T10:44:59Z", false], ["2026-09-14T10:45:00Z", true],
    ["2026-09-14T13:29:59Z", true], ["2026-09-14T13:30:00Z", false],
    ["2026-09-15T12:00:00Z", false], ["2026-09-13T12:00:00Z", false],
    ["2026-12-07T11:44:59Z", false], ["2026-12-07T11:45:00Z", true],
    ["2026-12-07T14:29:59Z", true], ["2026-12-07T14:30:00Z", false],
  ])("%s is active=%s", (date, expected) => expect(inPollingWindow(time(date))).toBe(expected));
  it("resolves the DST transitions using Eastern time", () => {
    expect(nextWindowStart(time("2026-03-06T12:00:00Z"))).toBe("2026-03-09T10:45:00.000Z");
    expect(nextWindowStart(time("2026-10-30T12:00:00Z"))).toBe("2026-11-02T11:45:00.000Z");
  });
  it("keeps a thirty second cadence and stops at the closing boundary", () => {
    const now = time("2026-09-14T12:00:05Z");
    expect(nextAlarmTime(now, { lastAttemptAt: "2026-09-14T12:00:00Z", backoffUntil: 0 })).toBe(time("2026-09-14T12:00:30Z"));
    expect(nextAlarmTime(time("2026-09-14T13:29:35Z"), { lastAttemptAt: "2026-09-14T13:29:30Z", backoffUntil: 0 })).toBeNull();
  });
  it("honors SEC blocks and Retry-After without bypassing them", () => {
    expect(retryDelay(403, 1, null, 0)).toBe(1_800_000);
    expect(retryDelay(429, 1, "900", 0)).toBe(900_000);
    expect(retryDelay(503, 10, null, 0)).toBe(900_000);
  });
  it("respects Retry-After values longer than a day in seconds or HTTP-date form", () => {
    const now = time("2026-09-14T12:00:00Z");
    expect(retryDelay(429, 1, "172800", now)).toBe(2 * 86_400_000);
    expect(retryDelay(503, 1, "Thu, 17 Sep 2026 12:00:00 GMT", now)).toBe(3 * 86_400_000);
    const extreme = retryDelay(429, 1, "9".repeat(400), now);
    expect(Number.isFinite(extreme)).toBe(true);
    expect(Number.isFinite(new Date(now + extreme).getTime())).toBe(true);
  });
});
