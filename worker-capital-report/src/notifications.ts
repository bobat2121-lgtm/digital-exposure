import { DurableObject } from "cloudflare:workers";
import { boundedText, documentUrl } from "./sec";
import { ISSUERS, type Filing, type Ticker } from "./types";

export const REPORT_URL = "https://digital-credit-report.streamlit.app/";
export const SETUP_TEST_ID = "test:discord-setup-v1";
const DAY = 86_400_000;
const LEASE_MS = 60_000;
const MAX_ATTEMPTS = 24;
export interface AcknowledgedFiling { ticker: Ticker; accession: string; sha256: string }
export interface NotificationFiling extends AcknowledgedFiling { url: string }
interface NotificationState {
  kind: "weekly" | "test";
  week: string;
  status: "queued" | "sending" | "retry" | "sent" | "failed";
  filings: NotificationFiling[];
  acknowledgedAt: string;
  attempts: number;
  nextAttemptAt: number | null;
  sentAt: string | null;
  messageId: string | null;
  lastError: string | null;
}
export function awareTime(value: string | null | undefined): number {
  return typeof value === "string" && /(Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : NaN;
}
export function easternDay(time: number): { date: string; weekday: string } {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", weekday: "short" }).formatToParts(time);
  const value = (key: string) => parts.find(part => part.type === key)?.value ?? "";
  return { date: `${value("year")}-${value("month")}-${value("day")}`, weekday: value("weekday") };
}
export function recentMondays(now: number): string[] {
  return Array.from({ length: 15 }, (_, i) => easternDay(now - i * DAY)).filter(day => day.weekday === "Mon").map(day => day.date);
}
export function parseAcknowledgement(input: unknown): AcknowledgedFiling[] | null {
  if (!input || typeof input !== "object" || Array.isArray(input)) return null;
  const payload = input as Record<string, unknown>;
  if (Object.keys(payload).length !== 1 || !Array.isArray(payload.filings) || payload.filings.length !== 2) return null;
  const result: AcknowledgedFiling[] = [];
  for (const item of payload.filings) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    const filing = item as Record<string, unknown>;
    if (Object.keys(filing).sort().join(",") !== "accession,sha256,ticker"
      || (filing.ticker !== "MSTR" && filing.ticker !== "ASST")
      || typeof filing.accession !== "string" || !/^\d{10}-\d{2}-\d{6}$/.test(filing.accession)
      || typeof filing.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(filing.sha256)) return null;
    result.push({ ticker: filing.ticker, accession: filing.accession, sha256: filing.sha256 });
  }
  return new Set(result.map(filing => filing.ticker)).size === 2 ? result.sort((a, b) => a.ticker === b.ticker ? 0 : a.ticker === "MSTR" ? -1 : 1) : null;
}
/** Checks the persisted SEC receipt, never caller-provided URLs or extracted numbers. */
export function validateReceipt(filing: Filing | null, ack: AcknowledgedFiling, now: number): { week: string; filing: NotificationFiling } | null {
  if (!filing || filing.baseline !== false || filing.form !== "8-K" || filing.ticker !== ack.ticker || filing.accession !== ack.accession
    || filing.cik !== ISSUERS[ack.ticker].cik || !["ready_for_review", "partial"].includes(filing.status)) return null;
  const accepted = awareTime(filing.acceptedAt), fetched = awareTime(filing.documentFetchedAt);
  if (!Number.isFinite(accepted) || !Number.isFinite(fetched) || accepted > now || fetched > now || fetched < accepted || now - accepted > 14 * DAY) return null;
  const day = easternDay(accepted);
  if (day.weekday !== "Mon") return null;
  const facts = filing.extracted?.facts;
  if (!facts || !Number.isFinite(facts.btc_holdings) || facts.btc_holdings <= 0
    || !Number.isFinite(facts.weekly_btc_purchases) || facts.weekly_btc_purchases < 0) return null;
  const receipt = filing.documents[0];
  if (!receipt || receipt.sha256 !== ack.sha256 || receipt.url !== filing.primaryDocumentUrl || awareTime(receipt.fetchedAt) !== fetched) return null;
  try {
    const primary = new URL(filing.primaryDocumentUrl).pathname.split("/").pop() ?? "";
    if (filing.primaryDocumentUrl !== documentUrl(ack.ticker, ack.accession, primary)) return null;
  } catch { return null; }
  return { week: day.date, filing: { ...ack, url: filing.primaryDocumentUrl } };
}
export function discordEndpoint(secret: string | undefined): string | null {
  if (!secret) return null;
  try {
    const url = new URL(secret);
    if (url.protocol !== "https:" || url.hostname !== "discord.com" || url.port || url.username || url.password || url.search || url.hash
      || !/^\/api\/(?:v10\/)?webhooks\/\d{16,22}\/[A-Za-z0-9_-]{40,200}$/.test(url.pathname)) return null;
    url.searchParams.set("wait", "true");
    return url.toString();
  } catch { return null; }
}
function discordBody(state: NotificationState) {
  const content = state.kind === "test"
    ? `**Digital Credit Report — setup test**\nDiscord notifications are connected. This is a setup test; no new filing or report update is being announced.\n${REPORT_URL}`
    : `**Digital Credit Report — Monday 8-Ks available**\nStrategy and Strive's ${state.week} 8-Ks have been received and are available in the Streamlit SEC monitor.\n${REPORT_URL}\n${state.filings.map(filing => `${ISSUERS[filing.ticker].issuer}: <${filing.url}>`).join("\n")}\nReported filing facts are available for review; the report's financial cards have not been refreshed automatically.`;
  return { content, allowed_mentions: { parse: [] } };
}
function retryMilliseconds(response: Response, body: string, now: number): number {
  const header = response.headers.get("Retry-After");
  const seconds = header === null || header.trim() === "" ? NaN : Number(header);
  let delay = Number.isFinite(seconds) && seconds >= 0 ? seconds * 1000 : header ? Date.parse(header) - now : 0;
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "retry_after" in parsed && typeof parsed.retry_after === "number" && Number.isFinite(parsed.retry_after))
      delay = Math.max(Number.isFinite(delay) ? delay : 0, parsed.retry_after * 1000);
  } catch { /* Header still applies to a non-JSON response. */ }
  return Math.max(1000, Number.isFinite(delay) ? delay : 0);
}

/** A separate object per filing Monday; SEC alarms cannot cancel Discord retries. */
export class ReportNotifier extends DurableObject<Env> {
  private busy = false;
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS notification (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)");
  }
  private read(): NotificationState | null {
    const row = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM notification WHERE id=1").toArray()[0];
    return row ? JSON.parse(row.body) as NotificationState : null;
  }
  private save(state: NotificationState): void {
    this.ctx.storage.sql.exec("INSERT INTO notification(id,body) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", JSON.stringify(state));
  }
  async status() {
    const state = this.read();
    return { configured: discordEndpoint(this.env.DISCORD_WEBHOOK_URL) !== null, ...(state ?? { status: "waiting_for_streamlit" }), nextAlarmAt: await this.ctx.storage.getAlarm() };
  }
  async acknowledge(week: string, filings: NotificationFiling[], test = false) {
    // No await before the durable insert: concurrent acknowledgements see one record.
    if (!this.read()) this.save({ kind: test ? "test" : "weekly", week, filings, status: "queued", acknowledgedAt: new Date().toISOString(),
      attempts: 0, nextAttemptAt: Date.now(), sentAt: null, messageId: null, lastError: null });
    await this.dispatch();
    return this.status();
  }
  private async dispatch(): Promise<void> {
    if (this.busy) return;
    const state = this.read();
    if (!state || state.status === "sent" || state.status === "failed") return;
    if (state.nextAttemptAt && state.nextAttemptAt > Date.now()) { await this.ctx.storage.setAlarm(state.nextAttemptAt); return; }
    this.busy = true;
    try {
      const endpoint = discordEndpoint(this.env.DISCORD_WEBHOOK_URL);
      if (!endpoint) {
        state.status = "retry"; state.lastError = "Discord webhook configuration missing or invalid"; state.nextAttemptAt = Date.now() + 5 * 60_000;
        this.save(state); await this.ctx.storage.setAlarm(state.nextAttemptAt); return;
      }
      state.status = "sending"; state.attempts++; state.nextAttemptAt = Date.now() + LEASE_MS;
      this.save(state);
      // Persist a recovery alarm before the external side effect, including process interruption.
      await this.ctx.storage.setAlarm(state.nextAttemptAt);
      let failure = "Discord network request failed";
      let delay = Math.min(60 * 60_000, 15_000 * 2 ** Math.min(state.attempts - 1, 8));
      let permanent = false;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10_000);
      try {
        const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(discordBody(state)), redirect: "manual", signal: controller.signal });
        // Preserve HTTP status and Retry-After even when the error body is absent or malformed.
        if (!response.ok) {
          failure = `Discord HTTP ${response.status}`;
          if (response.status === 429) delay = Math.max(delay, retryMilliseconds(response, "", Date.now()));
          else permanent = response.status < 500 && response.status !== 408;
        }
        let body = "";
        try { if (response.body) body = await boundedText(response, 64 * 1024); }
        catch { if (response.ok) throw new Error("Invalid confirmation body"); }
        if (response.ok) {
          const parsed: unknown = JSON.parse(body);
          if (parsed && typeof parsed === "object" && "id" in parsed && typeof parsed.id === "string" && /^\d{16,22}$/.test(parsed.id)) {
            state.status = "sent"; state.sentAt = new Date().toISOString(); state.messageId = parsed.id; state.nextAttemptAt = null; state.lastError = null;
            this.save(state); await this.ctx.storage.deleteAlarm();
            console.log(JSON.stringify({ event: "discord_notification_sent", kind: state.kind, week: state.week, attempts: state.attempts }));
            return;
          }
          failure = "Discord success response missing message confirmation";
        } else {
          if (response.status === 429) delay = Math.max(delay, retryMilliseconds(response, body, Date.now()));
        }
      } catch (error) {
        // Once Discord confirmation is durable, cleanup failures must never repost it.
        if (state.status === "sent") return;
        failure = error instanceof Error && error.name === "AbortError" ? "Discord request timeout; delivery unconfirmed" : "Discord request failed; delivery unconfirmed";
      } finally { clearTimeout(timeout); }
      state.lastError = failure;
      state.status = permanent || state.attempts >= MAX_ATTEMPTS ? "failed" : "retry";
      state.nextAttemptAt = state.status === "retry" ? Date.now() + delay : null;
      this.save(state);
      if (state.nextAttemptAt) await this.ctx.storage.setAlarm(state.nextAttemptAt); else await this.ctx.storage.deleteAlarm();
      console.error(JSON.stringify({ event: "discord_notification_error", kind: state.kind, week: state.week, status: state.status, error: state.lastError }));
    } finally { this.busy = false; }
  }
  async alarm(): Promise<void> { await this.dispatch(); }
}
