export const POLL_INTERVAL_MS = 30_000;
export const TIME_ZONE = "America/New_York";
const eastern = new Intl.DateTimeFormat("en-US", {
  timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
export function easternDay(time: number): { date: string; weekday: string } {
  const parts = Object.fromEntries(eastern.formatToParts(new Date(time)).map(p => [p.type, p.value]));
  return { date: `${parts.year}-${parts.month}-${parts.day}`, weekday: parts.weekday };
}
/** Regular federal closures from SEC's EDGAR calendar; only Monday closures move this weekly job. */
export function isEdgarMondayHoliday(date: string): boolean {
  const day = new Date(`${date}T12:00:00Z`);
  if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== date || day.getUTCDay() !== 1) return false;
  const month = day.getUTCMonth() + 1, d = day.getUTCDate();
  return (month === 1 && (d <= 2 || (d >= 15 && d <= 21))) // New Year (including Sunday observance), MLK
    || (month === 2 && d >= 15 && d <= 21) // Washington's Birthday
    || (month === 5 && d >= 25) // Memorial Day
    || (month === 6 && (d === 19 || d === 20))
    || (month === 7 && (d === 4 || d === 5))
    || (month === 9 && d <= 7) // Labor Day
    || (month === 10 && d >= 8 && d <= 14) // Columbus Day (EDGAR closes even when equities trade)
    || (month === 11 && (d === 11 || d === 12))
    || (month === 12 && (d === 25 || d === 26));
}
/** Canonical Monday week key. Ordinary Tuesdays and holiday Mondays are ineligible. */
export function weeklyReleaseWeek(time: number): string | null {
  if (!Number.isFinite(time)) return null;
  const day = easternDay(time);
  if (day.weekday === "Mon") return isEdgarMondayHoliday(day.date) ? null : day.date;
  if (day.weekday !== "Tue") return null;
  const monday = new Date(Date.parse(`${day.date}T12:00:00Z`) - 86_400_000).toISOString().slice(0, 10);
  return isEdgarMondayHoliday(monday) ? monday : null;
}
export function inPollingWindow(now: number): boolean {
  const parts = Object.fromEntries(eastern.formatToParts(new Date(now)).map(p => [p.type, p.value]));
  const minute = Number(parts.hour) * 60 + Number(parts.minute);
  return weeklyReleaseWeek(now) !== null && minute >= 6 * 60 + 45 && minute < 9 * 60 + 30;
}
export function nextWindowStart(now: number): string {
  const day = new Date(now);
  day.setUTCHours(0, 0, 0, 0);
  for (let offset = 0; offset <= 8; offset++) {
    const midnight = day.getTime() + offset * 86_400_000;
    // At 06:45 New York the UTC hour is 10 in DST and 11 in standard time.
    for (const hour of [10, 11]) {
      const candidate = midnight + (hour * 60 + 45) * 60_000;
      if (candidate > now && inPollingWindow(candidate) && !inPollingWindow(candidate - 60_000))
        return new Date(candidate).toISOString();
    }
  }
  throw new Error("Could not resolve next weekly polling window");
}
export function nextAlarmTime(now: number, state: { lastAttemptAt: string | null; backoffUntil: number }): number | null {
  const candidate = Math.max(now + 1000, (state.lastAttemptAt ? Date.parse(state.lastAttemptAt) : now) + POLL_INTERVAL_MS, state.backoffUntil);
  return inPollingWindow(now) && inPollingWindow(candidate) ? candidate : null;
}
export function retryDelay(status: number | null, failures: number, retryAfter: string | null, now: number): number {
  const exponential = Math.min(15 * 60_000, 30_000 * 2 ** Math.min(failures - 1, 5));
  const minimum = status === 403 ? 30 * 60_000 : status === 429 ? 5 * 60_000 : exponential;
  const seconds = retryAfter && /^\d+$/.test(retryAfter) ? Number(retryAfter) * 1000 : null;
  const dateDelay = retryAfter && seconds === null ? Date.parse(retryAfter) - now : 0;
  const requested = seconds ?? (Number.isFinite(dateDelay) ? dateDelay : 0);
  // Never shorten a valid server-requested cooldown. Bound only to JavaScript's
  // representable Date range so an extreme header cannot create an invalid date.
  return Math.max(minimum, Math.min(8.64e15 - now, requested));
}
