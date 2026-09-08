import { DurableObject } from "cloudflare:workers";
import { timingSafeEqual } from "node:crypto";
import { extractWeekly, PARSER_VERSION } from "./parser";
import { boundedText, documentUrl, fetchSec, MAX_DOCUMENT_BYTES, MAX_SUBMISSIONS_BYTES, parseSubmissions, SecError, validUserAgent } from "./sec";
import { inPollingWindow, nextAlarmTime, nextWindowStart, POLL_INTERVAL_MS, retryDelay, TIME_ZONE } from "./schedule";
import { initialState, ISSUERS, type Filing, type PollState, type Ticker } from "./types";
import { LEGACY_SETUP_TEST_ID, SETUP_TEST_ID } from "./notifications";
import { awareTime, eligiblePublication, publishedFeed, recentMondays, type PublicationEvent } from "./feed";
export { ReportNotifier } from "./notifications";

const tickers = Object.keys(ISSUERS) as Ticker[];
function errorMessage(error: unknown): string { return error instanceof Error ? error.message : "Unexpected poll failure"; }
async function sha256(text: string): Promise<string> {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(bytes)].map(value => value.toString(16).padStart(2, "0")).join("");
}
function statusFor(filing: Filing): Filing["status"] {
  if (!filing.extracted || Object.keys(filing.extracted.facts).length === 0) return "not_weekly";
  return filing.extracted.extractionValidated ? "ready_for_review" : "partial";
}
/** Bounded parser migrations run through the normal SEC cadence and document retry path. */
function needsParserUpgrade(filing: Filing, now: number, activation: string): boolean {
  const previous = /^sec-weekly-v(\d+)$/.exec(filing.extracted?.parserVersion ?? "");
  const current = /^sec-weekly-v(\d+)$/.exec(PARSER_VERSION);
  const accepted = awareTime(filing.acceptedAt), seen = awareTime(filing.firstSeenAt), fetched = awareTime(filing.documentFetchedAt), activeAfter = awareTime(activation);
  return !!previous && !!current && Number(previous[1]) < Number(current[1])
    && filing.baseline === false && filing.form === "8-K" && ["ready_for_review", "partial", "not_weekly"].includes(filing.status)
    && [accepted, seen, fetched, activeAfter].every(Number.isFinite)
    && accepted <= now && now - accepted <= 14 * 86_400_000 && seen >= activeAfter && seen <= now && fetched >= Math.max(activeAfter, accepted) && fetched <= now;
}

/** One durable coordination boundary per issuer; public reads never call the SEC. */
export class IssuerPoller extends DurableObject<Env> {
  private busy = false;
  private relaying = false;
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)");
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS filings (accession TEXT PRIMARY KEY, accepted_at TEXT NOT NULL, body TEXT NOT NULL)");
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS publication_outbox (accession TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL, next_attempt_at INTEGER NOT NULL, error TEXT)");
  }
  private state(ticker: Ticker): PollState {
    const row = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM state WHERE id=1").toArray()[0];
    const state: PollState = row ? JSON.parse(row.body) : initialState(ticker);
    if (state.ticker !== ticker) throw new Error("Durable issuer mismatch");
    return state;
  }
  private saveState(state: PollState): void {
    this.ctx.storage.sql.exec("INSERT INTO state(id,body) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", JSON.stringify(state));
  }
  private saveFiling(filing: Filing): void {
    this.ctx.storage.sql.exec("INSERT INTO filings(accession,accepted_at,body) VALUES(?,?,?) ON CONFLICT(accession) DO UPDATE SET body=excluded.body",
      filing.accession, filing.acceptedAt, JSON.stringify(filing));
  }
  private async saveReceipt(filing: Filing): Promise<void> {
    const event = eligiblePublication(filing, Date.now(), this.env.NOTIFICATIONS_ACTIVE_AFTER);
    // Receipt, publication obligation and recovery alarm commit as one SQLite transaction.
    await this.ctx.storage.transaction(async () => {
      this.saveFiling(filing);
      if (event) this.ctx.storage.sql.exec(`INSERT INTO publication_outbox(accession,body,status,attempts,next_attempt_at) VALUES(?,?,'pending',0,?)
        ON CONFLICT(accession) DO UPDATE SET body=excluded.body,status='pending',attempts=0,next_attempt_at=excluded.next_attempt_at,error=NULL
        WHERE publication_outbox.body!=excluded.body OR publication_outbox.status='discarded'`,
        filing.accession, JSON.stringify(event), Date.now());
      await this.reschedule(this.state(filing.ticker));
    });
  }
  async publicationStatus() {
    return this.ctx.storage.sql.exec<{ accession: string; status: string; attempts: number; next_attempt_at: number; error: string | null }>(
      "SELECT accession,status,attempts,next_attempt_at,error FROM publication_outbox ORDER BY next_attempt_at DESC LIMIT 50").toArray();
  }
  async relayToNotifier(event: PublicationEvent): Promise<void> {
    await this.env.REPORT_NOTIFIER.getByName(`week:${event.week}`).candidate(event);
  }
  async relayPublications(): Promise<void> {
    if (this.relaying) return;
    this.relaying = true;
    try {
      const events = this.ctx.storage.sql.exec<{ accession: string; body: string; attempts: number }>(
        "SELECT accession,body,attempts FROM publication_outbox WHERE status='pending' AND next_attempt_at<=? ORDER BY next_attempt_at LIMIT 10", Date.now()).toArray();
      for (const row of events) {
        const event = JSON.parse(row.body) as PublicationEvent;
        const receipt = await this.filing(row.accession);
        const eligible = receipt && eligiblePublication(receipt, Date.now(), this.env.NOTIFICATIONS_ACTIVE_AFTER);
        if (!eligible || JSON.stringify(eligible) !== JSON.stringify(event)) {
          this.ctx.storage.sql.exec("UPDATE publication_outbox SET status='discarded',error='Receipt no longer qualifies' WHERE accession=?", row.accession); continue;
        }
        const attempts = row.attempts + 1;
        await this.ctx.storage.transaction(async () => {
          this.ctx.storage.sql.exec("UPDATE publication_outbox SET attempts=?,next_attempt_at=? WHERE accession=?", attempts, Date.now() + 60_000, row.accession);
          await this.reschedule(this.state(event.filing.ticker));
        });
        try {
          await this.relayToNotifier(event);
          this.ctx.storage.sql.exec("UPDATE publication_outbox SET status='delivered',error=NULL WHERE accession=?", row.accession);
        } catch {
          // Publication retries never modify SEC failures or its cooldown.
          this.ctx.storage.sql.exec("UPDATE publication_outbox SET next_attempt_at=?,error='Notification coordinator handoff failed' WHERE accession=?",
            Date.now() + Math.min(15 * 60_000, 15_000 * 2 ** Math.min(attempts - 1, 6)), row.accession);
        }
      }
    } finally {
      this.relaying = false;
      const state = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM state WHERE id=1").toArray()[0];
      if (state) await this.reschedule(JSON.parse(state.body) as PollState);
    }
  }
  async filings(limit = 100): Promise<Filing[]> {
    return this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM filings ORDER BY accepted_at DESC LIMIT ?", Math.min(200, Math.max(1, limit)))
      .toArray().map(row => JSON.parse(row.body) as Filing);
  }
  async filing(accession: string): Promise<Filing | null> {
    const row = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM filings WHERE accession=?", accession).toArray()[0];
    return row ? JSON.parse(row.body) as Filing : null;
  }
  async status(ticker: Ticker) {
    const state = this.state(ticker);
    return { ...ISSUERS[ticker], ...state, nextAlarmAt: await this.ctx.storage.getAlarm(),
      configured: validUserAgent(this.env.SEC_USER_AGENT),
      storedFilings: this.ctx.storage.sql.exec<{ count: number }>("SELECT COUNT(*) AS count FROM filings").one().count,
      publicationMode: "reported_facts_for_review" };
  }
  private async reschedule(state: PollState): Promise<void> {
    const sec = nextAlarmTime(Date.now(), state);
    const publication = this.ctx.storage.sql.exec<{ next: number | null }>("SELECT MIN(next_attempt_at) AS next FROM publication_outbox WHERE status='pending'").one().next;
    const times = [sec, publication].filter((time): time is number => time !== null);
    const when = times.length ? Math.max(Date.now() + 1000, Math.min(...times)) : null;
    if (when === null) await this.ctx.storage.deleteAlarm();
    else await this.ctx.storage.setAlarm(when);
  }
  async poll(ticker: Ticker, force = false) {
    if (this.busy) return { ticker, outcome: "busy" };
    const now = Date.now();
    let state = this.state(ticker);
    if (!validUserAgent(this.env.SEC_USER_AGENT)) return { ticker, outcome: "configuration_required" };
    if (!force && !inPollingWindow(now)) { await this.relayPublications(); await this.reschedule(state); return { ticker, outcome: "outside_window" }; }
    // A manual poll cannot override SEC rate limits or a recent in-flight attempt.
    if (state.backoffUntil > now) { await this.reschedule(state); return { ticker, outcome: "backoff", backoffUntil: state.backoffUntil }; }
    if (state.lastAttemptAt && now - Date.parse(state.lastAttemptAt) < POLL_INTERVAL_MS - 100) {
      await this.reschedule(state); return { ticker, outcome: "not_due" };
    }
    this.busy = true;
    state.lastAttemptAt = new Date(now).toISOString(); state.pollCount++;
    this.saveState(state);
    let discovered = 0, fetched = 0;
    try {
      const conditional: Record<string, string> = {};
      if (state.etag) conditional["If-None-Match"] = state.etag;
      if (state.lastModified) conditional["If-Modified-Since"] = state.lastModified;
      const response = await fetchSec(`https://data.sec.gov/submissions/CIK${ISSUERS[ticker].cik}.json`, this.env.SEC_USER_AGENT, MAX_SUBMISSIONS_BYTES, conditional);
      if (response.text !== null) {
        const filings = parseSubmissions(response.text, ticker, Date.now(), !state.initializedAt);
        const seen = new Set(this.ctx.storage.sql.exec<{ accession: string }>("SELECT accession FROM filings").toArray().map(row => row.accession));
        this.ctx.storage.transactionSync(() => {
          for (const [index, filing] of filings.entries()) {
            if (seen.has(filing.accession)) continue;
            // Bootstrap records are clearly historical. Fetch only three recent filings to populate a useful baseline.
            if (filing.baseline && (index >= 3 || now - Date.parse(filing.acceptedAt) > 30 * 86_400_000)) filing.status = "baseline";
            this.saveFiling(filing);
            if (!filing.baseline) discovered++;
          }
          state.initializedAt ??= new Date(now).toISOString();
          state.lastDiscoveryAt = new Date(Date.now()).toISOString();
          state.etag = response.etag; state.lastModified = response.lastModified;
          this.saveState(state);
        });
      }
      state.lastSuccessAt = new Date(Date.now()).toISOString();
      state.failures = 0; state.backoffUntil = 0; state.error = null;
      this.saveState(state);
      const pending = (await this.filings(200)).filter(f => (f.status === "pending" || f.status === "document_error"
        || needsParserUpgrade(f, Date.now(), this.env.NOTIFICATIONS_ACTIVE_AFTER)) && f.nextDocumentAttemptAt <= Date.now()).slice(0, 2);
      for (const filing of pending) {
        const priorReceipt = needsParserUpgrade(filing, Date.now(), this.env.NOTIFICATIONS_ACTIVE_AFTER) ? structuredClone(filing) : null;
        // Each document attempt is persisted before network I/O, so restarts retain retry provenance.
        filing.attempts++; filing.nextDocumentAttemptAt = Date.now() + POLL_INTERVAL_MS; this.saveFiling(filing);
        try {
          const document = await fetchSec(filing.primaryDocumentUrl, this.env.SEC_USER_AGENT, MAX_DOCUMENT_BYTES);
          if (!document.text) throw new SecError("SEC returned no primary document", 404);
          const fetchedAt = new Date(Date.now()).toISOString();
          filing.extracted = extractWeekly(document.text, ticker);
          filing.documents = [{ url: filing.primaryDocumentUrl, fetchedAt, sha256: await sha256(document.text) }];
          filing.documentFetchedAt = fetchedAt; filing.status = statusFor(filing); filing.error = null;
          filing.nextDocumentAttemptAt = 0; await this.saveReceipt(filing); fetched++;
        } catch (error) {
          const sec = error instanceof SecError ? error : new SecError("Filing parser failed; manual review required");
          const retryReceipt = priorReceipt ?? filing;
          if (!priorReceipt) retryReceipt.status = "document_error";
          retryReceipt.attempts = filing.attempts; retryReceipt.error = sec.message;
          retryReceipt.nextDocumentAttemptAt = Date.now() + retryDelay(sec.status, filing.attempts, sec.retryAfter, Date.now());
          this.saveFiling(retryReceipt);
          if (sec.status === 403 || sec.status === 429) throw sec;
        }
      }
      console.log(JSON.stringify({ event: "sec_poll", ticker, discovered, fetched, pollCount: state.pollCount }));
      return { ticker, outcome: "ok", discovered, fetched };
    } catch (error) {
      const sec = error instanceof SecError ? error : new SecError(errorMessage(error));
      state.failures++; state.error = sec.message;
      state.backoffUntil = Date.now() + retryDelay(sec.status, state.failures, sec.retryAfter, Date.now());
      this.saveState(state);
      console.error(JSON.stringify({ event: "sec_poll_error", ticker, error: state.error, retryAt: new Date(state.backoffUntil).toISOString() }));
      return { ticker, outcome: "error", error: state.error, backoffUntil: state.backoffUntil };
    } finally {
      try { await this.relayPublications(); await this.reschedule(state); } finally { this.busy = false; }
    }
  }
  async alarm(): Promise<void> {
    try {
      await this.relayPublications();
      const row = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM state WHERE id=1").toArray()[0];
      if (row) await this.poll((JSON.parse(row.body) as PollState).ticker);
    } finally {
      // An alarm may fire during an in-flight relay/poll. Busy guards must not consume its recovery wake-up.
      const row = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM state WHERE id=1").toArray()[0];
      if (row) await this.reschedule(JSON.parse(row.body) as PollState);
    }
  }
  /** Authenticated recovery for one already-known recent receipt; never accepts a caller URL or facts. */
  async reprocess(ticker: Ticker, accession: string, includeDocument = false) {
    if (this.busy) return { ticker, accession, outcome: "busy" };
    const row = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM filings WHERE accession=?", accession).toArray()[0];
    const filing: Filing | null = row ? JSON.parse(row.body) : null;
    const now = Date.now(), activeAfter = awareTime(this.env.NOTIFICATIONS_ACTIVE_AFTER);
    if (!filing || filing.ticker !== ticker || filing.cik !== ISSUERS[ticker].cik || filing.form !== "8-K" || filing.baseline !== false
      || !Number.isFinite(activeAfter) || !Number.isFinite(awareTime(filing.acceptedAt)) || awareTime(filing.acceptedAt) > now
      || now - awareTime(filing.acceptedAt) > 14 * 86_400_000 || !Number.isFinite(awareTime(filing.firstSeenAt))
      || awareTime(filing.firstSeenAt) < activeAfter || awareTime(filing.firstSeenAt) > now)
      return { ticker, accession, outcome: "ineligible" };
    const primary = new URL(filing.primaryDocumentUrl).pathname.split("/").pop() ?? "";
    if (filing.primaryDocumentUrl !== documentUrl(ticker, accession, primary)) return { ticker, accession, outcome: "ineligible" };
    const state = this.state(ticker);
    if (!validUserAgent(this.env.SEC_USER_AGENT)) return { ticker, accession, outcome: "configuration_required" };
    const backoffUntil = Math.max(state.backoffUntil, filing.nextDocumentAttemptAt);
    if (backoffUntil > now) return { ticker, accession, outcome: "backoff", backoffUntil };
    if (state.lastAttemptAt && now - Date.parse(state.lastAttemptAt) < POLL_INTERVAL_MS - 100) return { ticker, accession, outcome: "not_due" };
    this.busy = true;
    state.lastAttemptAt = new Date(now).toISOString(); state.pollCount++; this.saveState(state);
    filing.attempts++; filing.nextDocumentAttemptAt = now + POLL_INTERVAL_MS; this.saveFiling(filing);
    try {
      const document = await fetchSec(filing.primaryDocumentUrl, this.env.SEC_USER_AGENT, MAX_DOCUMENT_BYTES);
      if (!document.text) throw new SecError("SEC returned no primary document", 404);
      const fetchedAt = new Date(Date.now()).toISOString(), hash = await sha256(document.text);
      filing.extracted = extractWeekly(document.text, ticker);
      filing.documents = [{ url: filing.primaryDocumentUrl, fetchedAt, sha256: hash }];
      filing.documentFetchedAt = fetchedAt; filing.status = statusFor(filing); filing.error = null; filing.nextDocumentAttemptAt = 0;
      await this.saveReceipt(filing);
      state.lastSuccessAt = fetchedAt; state.failures = 0; state.error = null; state.backoffUntil = 0; this.saveState(state);
      return { ticker, accession, outcome: "reprocessed", filing,
        ...(includeDocument ? { document: { url: filing.primaryDocumentUrl, sha256: hash, html: document.text } } : {}) };
    } catch (error) {
      const sec = error instanceof SecError ? error : new SecError("Filing reprocessing failed");
      state.failures++; state.error = sec.message;
      state.backoffUntil = Date.now() + retryDelay(sec.status, state.failures, sec.retryAfter, Date.now()); this.saveState(state);
      // Preserve the last published receipt when recovery fails. The admin can retry after this cooldown.
      return { ticker, accession, outcome: "error", error: state.error, backoffUntil: state.backoffUntil };
    } finally {
      try { await this.relayPublications(); await this.reschedule(state); } finally { this.busy = false; }
    }
  }
  /** This method is only reachable through an authenticated route in a separate replay namespace. */
  async replay(ticker: Ticker, html: string) {
    const started = Date.now();
    const extraction = extractWeekly(html, ticker);
    const digest = await sha256(html);
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS replay (digest TEXT PRIMARY KEY, result TEXT NOT NULL)");
    const prior = this.ctx.storage.sql.exec<{ result: string }>("SELECT result FROM replay WHERE digest=?", digest).toArray()[0];
    if (prior) return { simulation: true, outcome: "duplicate", digest, extracted: extraction, durationMs: Date.now() - started };
    const result = { simulation: true, outcome: extraction.extractionValidated ? "validated_for_review" : "rejected", digest,
      extracted: extraction, durationMs: Date.now() - started, livePublicationChanged: false };
    this.ctx.storage.sql.exec("INSERT INTO replay(digest,result) VALUES(?,?)", digest, JSON.stringify(result));
    return result;
  }
}

async function authorized(request: Request, secret: string | undefined): Promise<boolean> {
  if (!secret || secret.length < 32) return false;
  const supplied = request.headers.get("Authorization")?.replace(/^Bearer /, "") ?? "";
  if (supplied.length > 1024) return false;
  const [a, b] = await Promise.all([crypto.subtle.digest("SHA-256", new TextEncoder().encode(supplied)), crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret))]);
  return timingSafeEqual(new Uint8Array(a), new Uint8Array(b));
}
function json(value: unknown, env: Env, status = 200, cache = true): Response {
  return Response.json(value, { status, headers: { "Cache-Control": cache ? "public, max-age=15" : "no-store",
    "Access-Control-Allow-Origin": env.PUBLIC_ORIGIN, "Access-Control-Allow-Methods": "GET, OPTIONS",
    "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'" } });
}
export default {
  async fetch(request, env): Promise<Response> {
    try {
      const path = new URL(request.url).pathname;
      if (request.method === "OPTIONS") return json({}, env, 200, false);
      if (request.method === "GET" && (path === "/" || path === "/api/status")) {
        const now = Date.now();
        return json({ schemaVersion: 1, generatedAt: new Date(now).toISOString(), service: "capital-report", schedule: {
          timezone: TIME_ZONE, days: ["Monday", "Tuesday after an EDGAR Monday holiday"], start: "06:45", end: "09:30", intervalSeconds: 30,
          active: inPollingWindow(now), nextWindowStart: nextWindowStart(now) },
          publicationMode: "reported_facts_for_review", issuers: await Promise.all(tickers.map(ticker => env.ISSUER_POLLER.getByName(ticker).status(ticker))) }, env);
      }
      if (request.method === "GET" && path === "/api/filings") {
        return json(await publishedFeed(env), env);
      }
      if (path.startsWith("/api/admin/")) {
        if (request.method !== "POST") return json({ error: "POST required" }, env, 405, false);
        if (!(await authorized(request, env.ADMIN_TOKEN))) return json({ error: "Unauthorized" }, env, 401, false);
        if (path === "/api/admin/notifications") {
          const weeks = await Promise.all(recentMondays(Date.now()).map(async week => ({ week, ...await env.REPORT_NOTIFIER.getByName(`week:${week}`).status() })));
          return json({ schemaVersion: 1, mode: "unattended_feed_publication", activation: env.NOTIFICATIONS_ACTIVE_AFTER, weeks,
            outboxes: await Promise.all(tickers.map(async ticker => ({ ticker, events: await env.ISSUER_POLLER.getByName(ticker).publicationStatus() }))),
            previousSetupTest: await env.REPORT_NOTIFIER.getByName(LEGACY_SETUP_TEST_ID).status(),
            setupTest: await env.REPORT_NOTIFIER.getByName(SETUP_TEST_ID).status() }, env, 200, false);
        }
        if (path === "/api/admin/discord-test") {
          return json({ schemaVersion: 1, testId: SETUP_TEST_ID, notification: await env.REPORT_NOTIFIER.getByName(SETUP_TEST_ID).setupTest() }, env, 200, false);
        }
        if (path === "/api/admin/poll") {
          const results = [];
          for (const ticker of tickers) results.push(await env.ISSUER_POLLER.getByName(ticker).poll(ticker, true));
          return json({ schemaVersion: 1, results }, env, 200, false);
        }
        if (path === "/api/admin/reprocess") {
          let payload: Record<string, unknown>;
          try {
            const parsed: unknown = JSON.parse(await boundedText(new Response(request.body), 1024));
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Invalid input");
            payload = parsed as Record<string, unknown>;
          } catch { return json({ error: "Reprocess input invalid" }, env, 400, false); }
          if ((payload.ticker !== "MSTR" && payload.ticker !== "ASST") || typeof payload.accession !== "string"
            || !/^\d{10}-\d{2}-\d{6}$/.test(payload.accession) || (payload.includeDocument !== undefined && typeof payload.includeDocument !== "boolean")
            || Object.keys(payload).some(key => !["ticker", "accession", "includeDocument"].includes(key)))
            return json({ error: "Reprocess requires a known ticker and accession" }, env, 400, false);
          const result = await env.ISSUER_POLLER.getByName(payload.ticker).reprocess(payload.ticker, payload.accession, payload.includeDocument === true);
          return json({ schemaVersion: 1, ...result }, env, result.outcome === "ineligible" ? 409 : 200, false);
        }
        if (path === "/api/admin/replay") {
          const raw = await boundedText(new Response(request.body), MAX_DOCUMENT_BYTES + 1024);
          const input: unknown = JSON.parse(raw);
          if (!input || typeof input !== "object") return json({ error: "Replay input invalid" }, env, 400, false);
          const payload = input as Record<string, unknown>;
          if ((payload.ticker !== "MSTR" && payload.ticker !== "ASST") || typeof payload.html !== "string" || payload.html.length > MAX_DOCUMENT_BYTES
              || typeof payload.replayId !== "string" || !/^[A-Za-z0-9-]{1,80}$/.test(payload.replayId))
            return json({ error: "Replay requires ticker, bounded HTML, and replayId" }, env, 400, false);
          return json(await env.ISSUER_POLLER.getByName(`replay:${payload.ticker}:${payload.replayId}`).replay(payload.ticker, payload.html), env, 200, false);
        }
      }
      return json({ error: "Not found" }, env, 404, false);
    } catch (error) {
      console.error(JSON.stringify({ event: "request_error", error: errorMessage(error) }));
      return json({ error: "Request failed" }, env, 500, false);
    }
  },
  async scheduled(_controller, env, ctx): Promise<void> {
    if (!inPollingWindow(Date.now())) return;
    ctx.waitUntil((async () => {
      for (const ticker of tickers) await env.ISSUER_POLLER.getByName(ticker).poll(ticker);
    })());
  },
} satisfies ExportedHandler<Env>;
