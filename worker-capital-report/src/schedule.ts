export const POLL_INTERVAL_MS = 30_000;
export const TIME_ZONE = "America/New_York";
const eastern = new Intl.DateTimeFormat("en-US", {
  timeZone: TIME_ZONE, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
export function inPollingWindow(now: number): boolean {
  const parts = Object.fromEntries(eastern.formatToParts(new Date(now)).map(p => [p.type, p.value]));
  const minute = Number(parts.hour) * 60 + Number(parts.minute);
  return parts.weekday === "Mon" && minute >= 6 * 60 + 45 && minute < 9 * 60 + 30;
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
  throw new Error("Could not resolve next Monday polling window");
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
