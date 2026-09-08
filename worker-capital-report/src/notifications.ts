import { DurableObject } from "cloudflare:workers";
import { boundedText } from "./sec";
import { awareTime, easternDay, publishedFeed, verifyPublishedPair, type NotificationFiling, type PublicationEvent } from "./feed";
import { ISSUERS } from "./types";

export const REPORT_URL = "https://digital-credit-report.streamlit.app/";
export const LEGACY_SETUP_TEST_ID = "test:discord-setup-v1";
export const SETUP_TEST_ID = "test:discord-unattended-v1";
const LEASE_MS = 60_000;
const MAX_ATTEMPTS = 24;
interface NotificationState {
  kind: "weekly" | "test";
  week: string;
  status: "queued" | "sending" | "retry" | "sent" | "failed";
  filings: NotificationFiling[];
  acknowledgedAt?: string; // Existing deployed records retain this field.
  publishedAt?: string;
  attempts: number;
  nextAttemptAt: number | null;
  sentAt: string | null;
  messageId: string | null;
  lastError: string | null;
}
interface PublicationState {
  week: string;
  revision: number;
  status: "waiting_for_peer" | "checking" | "retry" | "published" | "failed";
  nextCheckAt: number | null;
  failures: number;
  publishedAt: string | null;
  lastError: string | null;
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
    : `**Strategy + Strive Monday 8-Ks ingested**\nBoth ${state.week} filings are published to the Digital Credit Report data feed.\n${REPORT_URL}\n${state.filings.map(filing => {
      const quantity = (value: number) => value > 0 && value < 1e-8 ? "<0.00000001" : new Intl.NumberFormat("en-US", { maximumFractionDigits: 8 }).format(value);
      const activity = [filing.weekly_btc_purchases === undefined ? null : `Bought ${quantity(filing.weekly_btc_purchases)} BTC`,
        filing.weekly_btc_sales === undefined ? null : `Sold ${quantity(filing.weekly_btc_sales)} BTC`].filter(Boolean).join(" · ");
      return `${ISSUERS[filing.ticker].issuer}${activity ? ` — ${activity}` : ""}: <${filing.url}>`;
    }).join("\n")}\nStreamlit is expected to load the feed when opened. Financial cards await reconciliation.`;
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
  private checking = false;
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS notification (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)");
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS publication (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)");
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS candidates (accession TEXT NOT NULL, sha256 TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(accession,sha256))");
  }
  private read(): NotificationState | null {
    const row = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM notification WHERE id=1").toArray()[0];
    return row ? JSON.parse(row.body) as NotificationState : null;
  }
  private save(state: NotificationState): void {
    this.ctx.storage.sql.exec("INSERT INTO notification(id,body) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", JSON.stringify(state));
  }
  private publication(): PublicationState | null {
    const row = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM publication WHERE id=1").toArray()[0];
    return row ? JSON.parse(row.body) as PublicationState : null;
  }
  private savePublication(state: PublicationState): void {
    this.ctx.storage.sql.exec("INSERT INTO publication(id,body) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", JSON.stringify(state));
  }
  private async schedule(): Promise<void> {
    const notification = this.read(), publication = this.publication();
    const next = notification
      ? (["sent", "failed"].includes(notification.status) ? null : notification.nextAttemptAt)
      : publication?.nextCheckAt ?? null;
    if (next === null) await this.ctx.storage.deleteAlarm();
    else await this.ctx.storage.setAlarm(Math.max(Date.now() + 1, next));
  }
  async status() {
    const state = this.read();
    return { configured: discordEndpoint(this.env.DISCORD_WEBHOOK_URL) !== null, activation: this.env.NOTIFICATIONS_ACTIVE_AFTER,
      ...(state ?? { status: "waiting_for_filings" }), publication: this.publication(), nextAlarmAt: await this.ctx.storage.getAlarm() };
  }
  /** Internal handoff only: acknowledge durable candidate storage, not Discord delivery. */
  async candidate(event: PublicationEvent): Promise<{ received: true }> {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(event.week) || easternDay(Date.parse(`${event.week}T12:00:00Z`)).weekday !== "Mon"
      || !["MSTR", "ASST"].includes(event.filing.ticker) || !/^\d{10}-\d{2}-\d{6}$/.test(event.filing.accession)
      || !/^[a-f0-9]{64}$/.test(event.filing.sha256) || event.filing.url.length > 1024) throw new Error("Invalid publication event");
    await this.ctx.storage.transaction(async () => {
      const publication = this.publication() ?? { week: event.week, revision: 0, status: "waiting_for_peer", nextCheckAt: null, failures: 0, publishedAt: null, lastError: null };
      if (publication.week !== event.week) throw new Error("Publication week mismatch");
      const exists = this.ctx.storage.sql.exec("SELECT 1 FROM candidates WHERE accession=? AND sha256=?", event.filing.accession, event.filing.sha256).toArray().length > 0;
      if (!exists) {
        this.ctx.storage.sql.exec("INSERT INTO candidates(accession,sha256,body) VALUES(?,?,?)", event.filing.accession, event.filing.sha256, JSON.stringify(event.filing));
        publication.revision++;
        // A new event during an in-flight feed check leaves a durable follow-up wake-up.
        if (!this.read()) publication.nextCheckAt = Date.now();
        this.savePublication(publication);
      }
      await this.schedule();
    });
    return { received: true };
  }
  private async checkPublication(): Promise<void> {
    if (this.checking || this.read()) return;
    const snapshot = this.publication();
    if (!snapshot || snapshot.nextCheckAt === null || snapshot.nextCheckAt > Date.now()) return;
    this.checking = true;
    const candidates = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM candidates").toArray().map(row => JSON.parse(row.body) as NotificationFiling);
    try {
      if (new Set(candidates.map(candidate => candidate.ticker)).size !== 2) {
        snapshot.status = "waiting_for_peer"; snapshot.nextCheckAt = null; this.savePublication(snapshot); return;
      }
      snapshot.status = "checking"; snapshot.nextCheckAt = Date.now() + LEASE_MS;
      this.savePublication(snapshot); await this.schedule();
      let pair: NotificationFiling[] | null = null, failure = "Exact filing receipts are not in the published feed projection";
      try {
        const feed = await this.loadPublishedFeed();
        pair = verifyPublishedPair(feed.filings, candidates, snapshot.week, Date.now(), this.env.NOTIFICATIONS_ACTIVE_AFTER);
      } catch { failure = "Published feed verification failed"; }
      const latest = this.publication()!;
      if (pair && !this.read()) {
        const publishedAt = new Date().toISOString();
        latest.status = "published"; latest.nextCheckAt = null; latest.publishedAt = publishedAt; latest.lastError = null;
        // Publication confirmation and the delivery obligation commit together.
        this.ctx.storage.transactionSync(() => {
          this.savePublication(latest);
          this.save({ kind: "weekly", week: snapshot.week, filings: pair!, status: "queued", publishedAt,
            attempts: 0, nextAttemptAt: Date.now(), sentAt: null, messageId: null, lastError: null });
        });
      } else if (!this.read()) {
        latest.failures++; latest.lastError = failure;
        const expired = Date.now() - Date.parse(`${snapshot.week}T00:00:00Z`) > 15 * 86_400_000;
        latest.status = expired ? "failed" : "retry";
        latest.nextCheckAt = expired ? null : Date.now() + (latest.revision !== snapshot.revision ? 1 : Math.min(15 * 60_000, 15_000 * 2 ** Math.min(latest.failures - 1, 6)));
        this.savePublication(latest);
      }
    } finally { this.checking = false; await this.schedule(); }
  }
  async loadPublishedFeed() { return publishedFeed(this.env); }
  async setupTest() {
    if (!this.read()) this.save({ kind: "test", week: "setup", filings: [], status: "queued", publishedAt: new Date().toISOString(),
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
  async alarm(): Promise<void> {
    await this.checkPublication();
    await this.dispatch();
    await this.schedule();
  }
}
