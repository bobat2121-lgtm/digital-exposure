import { DurableObject } from "cloudflare:workers";
import { timingSafeEqual } from "node:crypto";
import { extractWeekly } from "./parser";
import { boundedText, fetchSec, MAX_DOCUMENT_BYTES, MAX_SUBMISSIONS_BYTES, parseSubmissions, SecError, validUserAgent } from "./sec";
import { inPollingWindow, nextAlarmTime, nextWindowStart, POLL_INTERVAL_MS, retryDelay, TIME_ZONE } from "./schedule";
import { initialState, ISSUERS, type Filing, type PollState, type Ticker } from "./types";
import { parseAcknowledgement, recentMondays, SETUP_TEST_ID, validateReceipt } from "./notifications";
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

/** One durable coordination boundary per issuer; public reads never call the SEC. */
export class IssuerPoller extends DurableObject<Env> {
  private busy = false;
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)");
    this.ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS filings (accession TEXT PRIMARY KEY, accepted_at TEXT NOT NULL, body TEXT NOT NULL)");
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
    const when = nextAlarmTime(Date.now(), state);
    if (when === null) await this.ctx.storage.deleteAlarm();
    else await this.ctx.storage.setAlarm(when);
  }
  async poll(ticker: Ticker, force = false) {
    if (this.busy) return { ticker, outcome: "busy" };
    const now = Date.now();
    let state = this.state(ticker);
    if (!validUserAgent(this.env.SEC_USER_AGENT)) return { ticker, outcome: "configuration_required" };
    if (!force && !inPollingWindow(now)) { await this.ctx.storage.deleteAlarm(); return { ticker, outcome: "outside_window" }; }
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
      const pending = (await this.filings(200)).filter(f => (f.status === "pending" || f.status === "document_error") && f.nextDocumentAttemptAt <= Date.now()).slice(0, 2);
      for (const filing of pending) {
        // Each document attempt is persisted before network I/O, so restarts retain retry provenance.
        filing.attempts++; filing.nextDocumentAttemptAt = Date.now() + POLL_INTERVAL_MS; this.saveFiling(filing);
        try {
          const document = await fetchSec(filing.primaryDocumentUrl, this.env.SEC_USER_AGENT, MAX_DOCUMENT_BYTES);
          if (!document.text) throw new SecError("SEC returned no primary document", 404);
          const fetchedAt = new Date(Date.now()).toISOString();
          filing.extracted = extractWeekly(document.text, ticker);
          filing.documents = [{ url: filing.primaryDocumentUrl, fetchedAt, sha256: await sha256(document.text) }];
          filing.documentFetchedAt = fetchedAt; filing.status = statusFor(filing); filing.error = null;
          filing.nextDocumentAttemptAt = 0; this.saveFiling(filing); fetched++;
        } catch (error) {
          const sec = error instanceof SecError ? error : new SecError("Filing parser failed; manual review required");
          filing.status = "document_error"; filing.error = sec.message;
          filing.nextDocumentAttemptAt = Date.now() + retryDelay(sec.status, filing.attempts, sec.retryAfter, Date.now());
          this.saveFiling(filing);
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
      try { await this.reschedule(state); } finally { this.busy = false; }
    }
  }
  async alarm(): Promise<void> {
    const row = this.ctx.storage.sql.exec<{ body: string }>("SELECT body FROM state WHERE id=1").toArray()[0];
    if (row) await this.poll((JSON.parse(row.body) as PollState).ticker);
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
          timezone: TIME_ZONE, days: ["Monday"], start: "06:45", end: "09:30", intervalSeconds: 30,
          active: inPollingWindow(now), nextWindowStart: nextWindowStart(now) },
          publicationMode: "reported_facts_for_review", issuers: await Promise.all(tickers.map(ticker => env.ISSUER_POLLER.getByName(ticker).status(ticker))) }, env);
      }
      if (request.method === "GET" && path === "/api/filings") {
        const all = (await Promise.all(tickers.map(ticker => env.ISSUER_POLLER.getByName(ticker).filings(100)))).flat();
        return json({ schemaVersion: 1, generatedAt: new Date().toISOString(), publicationMode: "reported_facts_for_review",
          filings: all.sort((a, b) => b.acceptedAt.localeCompare(a.acceptedAt)).slice(0, 100) }, env);
      }
      if (path === "/api/streamlit/ack") {
        if (request.method !== "POST") return json({ error: "POST required" }, env, 405, false);
        if (!(await authorized(request, env.STREAMLIT_ACK_TOKEN))) return json({ error: "Unauthorized" }, env, 401, false);
        let input: unknown;
        try { input = JSON.parse(await boundedText(new Response(request.body, { headers: request.headers }), 2048)); }
        catch { return json({ error: "Acknowledgement requires a bounded JSON body" }, env, 400, false); }
        const acknowledgements = parseAcknowledgement(input);
        if (!acknowledgements) return json({ error: "Acknowledgement requires one MSTR and one ASST accession and SHA-256" }, env, 400, false);
        const receipts = await Promise.all(acknowledgements.map(async ack => validateReceipt(await env.ISSUER_POLLER.getByName(ack.ticker).filing(ack.accession), ack, Date.now())));
        const [strategy, strive] = receipts;
        if (!strategy || !strive || strategy.week !== strive.week) return json({ error: "Both matching Monday filing receipts must be available" }, env, 409, false);
        const notification = await env.REPORT_NOTIFIER.getByName(`week:${strategy.week}`).acknowledge(strategy.week, [strategy.filing, strive.filing]);
        return json({ schemaVersion: 1, week: strategy.week, outcome: notification.status === "sent" ? "sent" : notification.status === "failed" ? "failed" : "queued",
          notification: { status: notification.status } }, env, 200, false);
      }
      if (path.startsWith("/api/admin/")) {
        if (request.method !== "POST") return json({ error: "POST required" }, env, 405, false);
        if (!(await authorized(request, env.ADMIN_TOKEN))) return json({ error: "Unauthorized" }, env, 401, false);
        if (path === "/api/admin/notifications") {
          const weeks = await Promise.all(recentMondays(Date.now()).map(async week => ({ week, ...await env.REPORT_NOTIFIER.getByName(`week:${week}`).status() })));
          return json({ schemaVersion: 1, weeks, setupTest: await env.REPORT_NOTIFIER.getByName(SETUP_TEST_ID).status() }, env, 200, false);
        }
        if (path === "/api/admin/discord-test") {
          return json({ schemaVersion: 1, testId: SETUP_TEST_ID, notification: await env.REPORT_NOTIFIER.getByName(SETUP_TEST_ID).acknowledge("setup", [], true) }, env, 200, false);
        }
        if (path === "/api/admin/poll") {
          const results = [];
          for (const ticker of tickers) results.push(await env.ISSUER_POLLER.getByName(ticker).poll(ticker, true));
          return json({ schemaVersion: 1, results }, env, 200, false);
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
