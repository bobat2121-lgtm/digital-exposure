import { describe, expect, it } from "vitest";
import { inPollingWindow, isEdgarMondayHoliday, nextAlarmTime, nextWindowStart, retryDelay, weeklyReleaseWeek } from "../src/schedule";
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
  it("moves Labor Day polling to Tuesday and retains its Monday notification key", () => {
    expect(inPollingWindow(time("2026-09-07T12:00:00Z"))).toBe(false);
    expect(inPollingWindow(time("2026-09-08T10:44:59Z"))).toBe(false);
    expect(inPollingWindow(time("2026-09-08T10:45:00Z"))).toBe(true);
    expect(inPollingWindow(time("2026-09-08T13:29:59Z"))).toBe(true);
    expect(inPollingWindow(time("2026-09-08T13:30:00Z"))).toBe(false);
    expect(weeklyReleaseWeek(time("2026-09-08T08:00:15Z"))).toBe("2026-09-07");
    expect(weeklyReleaseWeek(time("2026-09-15T12:00:00Z"))).toBeNull();
    expect(nextWindowStart(time("2026-09-07T12:00:00Z"))).toBe("2026-09-08T10:45:00.000Z");
    expect(nextWindowStart(time("2026-09-08T13:30:00Z"))).toBe("2026-09-14T10:45:00.000Z");
  });
  it.each(["2026-01-19", "2026-02-16", "2026-05-25", "2026-09-07", "2026-10-12", "2027-07-05", "2028-06-19", "2028-12-25", "2029-01-01", "2029-11-12"])("observes the SEC Monday closure %s", date => {
    expect(isEdgarMondayHoliday(date)).toBe(true);
    const tuesday = time(`${date}T12:00:00Z`) + 86_400_000;
    expect(weeklyReleaseWeek(tuesday)).toBe(date);
    expect(inPollingWindow(tuesday)).toBe(true);
  });
  it("does not shift a Friday holiday, ordinary Tuesday, malformed date, or weekend", () => {
    expect(isEdgarMondayHoliday("2026-07-03")).toBe(false);
    expect(isEdgarMondayHoliday("2026-02-30")).toBe(false);
    expect(weeklyReleaseWeek(time("2026-07-06T12:00:00Z"))).toBe("2026-07-06");
    expect(weeklyReleaseWeek(time("2026-07-07T12:00:00Z"))).toBeNull();
    expect(weeklyReleaseWeek(time("2026-09-09T12:00:00Z"))).toBeNull();
    expect(weeklyReleaseWeek(NaN)).toBeNull();
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
