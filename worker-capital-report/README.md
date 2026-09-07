# capital-report SEC poller

Cloudflare Worker and per-issuer SQLite Durable Objects monitor Strategy (CIK 1050446) and Strive (CIK 1920406). The public feed exposes new SEC 8-K / 8-K/A filings, their acceptance and retrieval timestamps, source-document hashes, and validated reported facts. Separate per-week Durable Objects notify Discord after both Monday filings are published to the feed. No browser session or Streamlit callback is needed.

## Schedule

- Monday **06:45 through 09:29:59 America/New_York**, every 30 seconds.
- A minute cron during Monday 10:00–14:59 UTC starts and repairs the alarm chain. An Eastern-time check applies the exact window and handles daylight saving automatically.
- One Durable Object per company owns deduplication, retry state and its alarm. Public page views do not cause SEC requests.
- At 09:30 Eastern the alarm chain stops. Holidays do not move the schedule to Tuesday. An authenticated manual poll can run outside the window.
- SEC errors can lengthen the interval: 403 pauses that issuer for at least 30 minutes; 429 honors Retry-After with a five-minute minimum; network/5xx failures use exponential backoff. Manual requests cannot bypass these pauses.

Thirty seconds is the polling target, not a guaranteed release-to-screen SLA. SEC availability, Cloudflare scheduling, document publication lag and Streamlit refresh time add latency. The recorded timestamps make actual detection and retrieval lag measurable.

## What updates automatically

The feed discovers and parses primary SEC filing HTML. It does **not** fabricate a complete NAV report from an incomplete filing.

The current Strategy parser extracts weekly BTC purchases, ending BTC holdings, common and preferred issuance/repurchase tables, and the two designated dollar liquidity balances when present. Its weekly 8-K does not provide every NAV input or a complete ending common share denominator.

The Strive parser extracts both balance dates, BTC, cash, STRC holdings, Class A/B and assumed-diluted share counts, SATA share counts, and net share changes. It does not label net share growth as actual gross issuance cash. Strive's common-capital VWAP estimate and SATA $100 assumption remain separate report calculations.

`extractionValidated: true` means the supported table shape and arithmetic checks passed. The filing status is `ready_for_review`; it is **not** a claim that debt, preferred claims, prices and all other report inputs were independently refreshed. Consumers should retain the last complete report until all necessary inputs have been reconciled. Unknown layouts remain `partial` or `not_weekly`; missing fields are omitted, never zero-filled. Primary documents containing only a link to a press-release exhibit require an additional parser before automatic extraction; the filing is still discovered immediately.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Configuration readiness, Eastern schedule, per-issuer success/error/retry/alarm state |
| GET | `/api/filings` | Up to 100 recent filing records, newest first |
| POST | `/api/admin/poll` | Authenticated single immediate polling cycle for both issuers |
| POST | `/api/admin/replay` | Authenticated offline parser/deduplication rehearsal in a separate namespace |
| POST | `/api/admin/notifications` | Private delivery state for the last three Mondays and setup test |
| POST | `/api/admin/discord-test` | Clearly labelled setup message, deduplicated with a stable separate test ID |

Read routes return `Cache-Control: public, max-age=15` and never contact SEC. The response schema version is `1`. The status response has an `issuers` array keyed by each item's `ticker` (`MSTR`, `ASST`). The feed response has a `filings` array; exact TypeScript contracts are in `src/types.ts`.

Each record retains:

- SEC accession, form, filing date, report date and timezone-qualified acceptance timestamp;
- first discovery time and first successful document fetch time;
- trusted primary SEC URL and SHA-256 of retrieved HTML;
- `baseline`, distinguishing already-existing filings discovered during setup;
- extraction, missing fields, validation issues, retry attempts and document errors.

Existing filings are baselined on the first successful scan. Only the three most recent baseline filings from the last 30 days are queued for document retrieval. A repeated accession leaves the original timestamps and data untouched. Amendments are independent accessions; they are not silently applied over earlier data. Corrections published by replacing a document under the same accession require manual review/reprocessing; the poller does not continuously redownload completed documents.

## Discord delivery

The issuer saves each eligible retrieved receipt, a publication outbox event and its recovery alarm in one SQLite transaction. It relays the event to the filing Monday's `ReportNotifier`. A failed relay remains pending and retries after a restart or after the SEC polling window closes; it does not change SEC backoff or make an extra SEC request.

The coordinator durably stores candidates and independently reads the same bounded feed projection used by `/api/filings`. Both exact accessions, hashes and trusted SEC URLs must be present. Each receipt must be a non-baseline primary `8-K`, accepted on the same Eastern Monday within 14 days, with completed retrieval timestamps and weekly BTC holdings/purchases. Partial weekly extractions with those two BTC facts qualify; amendments, unrelated filings and historical setup records do not.

`NOTIFICATIONS_ACTIVE_AFTER` is the fixed initial activation cutoff, **2026-09-08T00:00:00Z**. Both first discovery and completed retrieval must be on or after it. Preserve this value on future deployments: advancing it would discard eligible pending events. Existing receipts are not retroactively queued. Already-sent records and existing Discord retry deadlines survive the upgrade.

Candidate revisions preserve a follow-up check when another event arrives during feed verification. Once the pair is verified, the coordinator atomically saves publication time and its Discord delivery obligation. Public feed reads remain read-only. The retired `/api/streamlit/ack` route returns 404; the Worker and Streamlit no longer need its token.

Discord requests use `wait=true`, disable mentions and confirm a returned message ID. The combined message links both SEC filings and the report, states that the filings are published to the feed, and says Streamlit is expected to load that feed when opened. Financial cards still await reconciliation; no completed browser rendering is claimed.

Discord 429 responses honor the `Retry-After` header and JSON `retry_after`; timeouts and 5xx responses retry with exponential backoff. A separate alarm continues after SEC polling closes, with up to 24 delivery attempts. Other 4xx failures stop and appear only in authenticated notification status. Secrets and Discord response bodies are never logged. Rarely, Discord may accept a message just before a timeout or process interruption; because webhooks have no idempotency key, retrying unconfirmed delivery can duplicate that message. Confirmed sends remain deduplicated.

`POST /api/admin/notifications` shows publication checks, issuer outboxes and delivery state. `POST /api/admin/discord-test` uses the stable new `test:discord-unattended-v1` key, sends a clearly labelled setup message once, and leaves the old `test:discord-setup-v1` receipt intact. These routes require the existing admin Bearer token. Terminal failed deliveries require operator recovery; repeated acknowledgements or page views cannot reset them.

## Deploy to the existing Worker

Install dependencies with `npm ci`. Generate bindings with `npm run types`. Then run `npm run check`, `npm test`, and `npm run dry-run`.

Set three production secrets through Cloudflare or Wrangler:

```text
npx wrangler secret put SEC_USER_AGENT
npx wrangler secret put ADMIN_TOKEN
npx wrangler secret put DISCORD_WEBHOOK_URL
npm run deploy
```

`SEC_USER_AGENT` must identify the actual application and a monitored contact email. `ADMIN_TOKEN` must be a cryptographically random token at least 32 characters long. `DISCORD_WEBHOOK_URL` is the Discord webhook secret. Do not put production values in the repository, browser JavaScript, Streamlit frontend, logs, or command arguments. `.dev.vars.example` contains blank local-development placeholders only.

The config deploys to **capital-report**. Migration `v1` provisions `IssuerPoller`; additive migration `v2` provisions `ReportNotifier` without replacing issuer storage. The unattended update adds tables inside these existing classes and needs no additional migration. It does not need KV, R2 or a database account ID.

After deployment, set `CAPITAL_REPORT_ADMIN_TOKEN` in the shell environment and run:

```text
node scripts/smoke.mjs https://YOUR-WORKER.workers.dev --poll
```

The script checks public status, rejects an unauthenticated mutation, optionally bootstraps one real SEC scan, and replays both real historical fixtures twice to prove parser acceptance and persistent duplicate handling. Replays never change the live filing feed. The script prints a compact JSON result without the token. Keep the token only in a secure secret store after use.

Configure the Streamlit server with the public worker base URL (`SEC_MONITOR_URL`, or the committed `data/sec-monitor.json` configuration in this repository's client). The admin token is unnecessary for reading the feed.

## Validation and source fixtures

71 tests run in workerd, covering SEC parsing and polling, no-browser publication, atomic receipt/outbox/alarm storage, failed handoffs and busy-alarm recovery after 09:30, shared feed projection checks, concurrent candidate revisions, activation and receipt gating, persisted Discord cooldowns, restart deduplication, rate limits, timeouts, permanent errors and isolated setup tests.

The test plugin currently ships an older runtime. `vitest.config.ts` selects the workerd binary bundled with the pinned production Wrangler so tests use the same September 7 compatibility date. Tests mock SEC and Discord requests and use dummy secrets; no messages or live EDGAR requests are sent. Some dependencies emit source-map warnings during tests; the checks themselves pass.

- [Strategy August 31, 2026 weekly 8-K](https://www.sec.gov/Archives/edgar/data/1050446/000119312526375463/mstr-20260831.htm)
- [Strive August 31, 2026 weekly 8-K](https://www.sec.gov/Archives/edgar/data/1920406/000162828026059468/asst-20260831.htm)
- [SEC fair-access rules and public data APIs](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [Cloudflare Durable Object alarms](https://developers.cloudflare.com/durable-objects/api/alarms/)
- [Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)
- [Cloudflare Workers best practices](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/)
- [Discord webhook execution](https://docs.discord.com/developers/resources/webhook#execute-webhook)
- [Discord rate limits](https://docs.discord.com/developers/topics/rate-limits)
