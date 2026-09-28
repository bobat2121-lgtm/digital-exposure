/**
 * A dependable clock for the X Control Panel (bobat2121-lgtm/X-Control-Panel).
 *
 * GitHub starts scheduled workflows late, sometimes by hours, and drops some outright, so the desk runs and the
 * Mon / Wed / Fri report-panel windows were being missed. Every five minutes this Worker asks GitHub to start the
 * right workflow now (workflow_dispatch), on New York time. The workflows still decide what's due (a desk run
 * inside its window, a panel on its day), so a repeat start (this clock plus GitHub's own late cron) does nothing.
 *
 * Needs the GH_DISPATCH_TOKEN secret: a fine-grained GitHub token limited to that repository with
 * "Actions: Read and write". Without it the clock logs and does nothing.
 */
import { TIME_ZONE } from "./schedule";

export const DISPATCH_CRON = "*/5 * * * *";
export const PANEL_REPO = "bobat2121-lgtm/X-Control-Panel";

export type Kick = { workflow: string; inputs?: Record<string, string>; why: string };

const ALL = [0, 1, 2, 3, 4, 5, 6], WEEKDAYS = [1, 2, 3, 4, 5];
const agent = (why: string): Kick => ({ workflow: "agent.yml", why });  // starts whatever is due + queued panel requests
const watch = (why: string): Kick => ({ workflow: "showcase.yml", inputs: { mode: "watch", panel: "", quiet: "false" }, why });

/** New York wall-clock times (HH:MM, on five-minute marks) and weekdays (0 = Sunday). Mirrors config/settings.yaml
 * slots and jobs, and the digital-exposure panel windows in the panel repo. */
export const PLAN: { at: string; days: number[]; kick: Kick }[] = [
  { at: "07:05", days: WEEKDAYS, kick: agent("pre-market desk") },
  { at: "11:20", days: ALL, kick: agent("AI desk") },
  { at: "12:50", days: WEEKDAYS, kick: agent("midday desk") },
  { at: "16:10", days: [5], kick: agent("Friday close desk") },
  { at: "17:00", days: [0], kick: agent("weekly review") },
  { at: "21:30", days: ALL, kick: agent("nightly") },
  // The Accretion Ledger (Monday, or Tuesday after an EDGAR Monday holiday: the workflow skips the other day),
  // the Coupon Sheet (Wednesday) and the Closing Mark (Friday), each with backup starts in case a run dies.
  { at: "07:40", days: [1, 2], kick: watch("Accretion Ledger window") },
  { at: "08:25", days: [1, 2], kick: watch("Accretion Ledger backup") },
  { at: "09:30", days: [1, 2], kick: watch("Accretion Ledger backup") },
  { at: "12:30", days: [3], kick: watch("Coupon Sheet window") },
  { at: "13:05", days: [3], kick: watch("Coupon Sheet backup") },
  { at: "16:05", days: [5], kick: watch("Closing Mark window") },
  { at: "16:40", days: [5], kick: watch("Closing Mark backup") },
  { at: "20:15", days: [0, 2, 4], kick: { workflow: "showcase.yml", inputs: { mode: "preflight", panel: "", quiet: "false" },
    why: "preflight for tomorrow's panel" } },
];
const MONITOR: Kick = { workflow: "monitor.yml", why: "news monitor" };  // every 15 minutes (:05, :20, :35, :50)

const eastern = new Intl.DateTimeFormat("en-US", { timeZone: TIME_ZONE, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const WEEKDAY: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

/** What to start at this tick (the cron's scheduled time, rounded to its minute). */
export function duePanelKicks(time: number): Kick[] {
  const parts = Object.fromEntries(eastern.formatToParts(new Date(time)).map(p => [p.type, p.value]));
  const hhmm = `${parts.hour}:${parts.minute}`, day = WEEKDAY[parts.weekday], minute = Number(parts.minute);
  const kicks = PLAN.filter(p => p.at === hhmm && p.days.includes(day)).map(p => p.kick);
  if (minute % 15 === 5) kicks.push(MONITOR);
  return kicks;
}

type DispatchEnv = { GH_DISPATCH_TOKEN?: string };

/** Ask GitHub to start each due workflow now. Returns one line per kick for the logs. */
export async function kickPanel(time: number, env: DispatchEnv, fetcher: typeof fetch = fetch): Promise<string[]> {
  const kicks = duePanelKicks(time);
  if (!kicks.length) return [];
  if (!env.GH_DISPATCH_TOKEN) {
    console.warn(JSON.stringify({ event: "panel_kick_skipped", reason: "GH_DISPATCH_TOKEN not set", due: kicks.map(k => k.why) }));
    return [];
  }
  const out: string[] = [];
  for (const k of kicks) {
    let status = 0;
    try {
      const r = await fetcher(`https://api.github.com/repos/${PANEL_REPO}/actions/workflows/${k.workflow}/dispatches`, {
        method: "POST",
        headers: { Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`, Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "capital-report-panel-clock", "Content-Type": "application/json" },
        body: JSON.stringify({ ref: "main", ...(k.inputs ? { inputs: k.inputs } : {}) }),
      });
      status = r.status;
    } catch (error) {
      console.error(JSON.stringify({ event: "panel_kick_error", workflow: k.workflow, why: k.why,
        error: error instanceof Error ? error.message : "fetch failed" }));
    }
    const line = `${k.workflow} (${k.why}): ${status === 204 ? "started" : `HTTP ${status || "error"}`}`;
    console.log(JSON.stringify({ event: "panel_kick", workflow: k.workflow, why: k.why, status }));
    out.push(line);
  }
  return out;
}
