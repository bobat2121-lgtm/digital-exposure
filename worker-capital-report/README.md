# capital-report SEC poller

Cloudflare Worker and two SQLite Durable Objects monitor Strategy (CIK 1050446) and Strive (CIK 1920406). The public feed exposes new SEC 8-K / 8-K/A filings, their acceptance and retrieval timestamps, source-document hashes, and validated reported facts.

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

Read routes return `Cache-Control: public, max-age=15` and never contact SEC. The response schema version is `1`. The status response has an `issuers` array keyed by each item's `ticker` (`MSTR`, `ASST`). The feed response has a `filings` array; exact TypeScript contracts are in `src/types.ts`.

Each record retains:

- SEC accession, form, filing date, report date and timezone-qualified acceptance timestamp;
- first discovery time and first successful document fetch time;
- trusted primary SEC URL and SHA-256 of retrieved HTML;
- `baseline`, distinguishing already-existing filings discovered during setup;
- extraction, missing fields, validation issues, retry attempts and document errors.

Existing filings are baselined on the first successful scan. Only the three most recent baseline filings from the last 30 days are queued for document retrieval. A repeated accession leaves the original timestamps and data untouched. Amendments are independent accessions; they are not silently applied over earlier data. Corrections published by replacing a document under the same accession require manual review/reprocessing; the poller does not continuously redownload completed documents.

## Deploy to the existing Worker

Install dependencies with `npm ci`. Generate bindings with `npm run types`. Then run `npm run check`, `npm test`, and `npm run dry-run`.

Set two production secrets through Cloudflare or Wrangler:

```text
npx wrangler secret put SEC_USER_AGENT
npx wrangler secret put ADMIN_TOKEN
npm run deploy
```

`SEC_USER_AGENT` must identify the actual application and a monitored contact email. `ADMIN_TOKEN` must be a cryptographically random token at least 32 characters long. Do not put production values in the repository, browser JavaScript, Streamlit frontend, logs, or command arguments. `.dev.vars.example` contains blank local-development placeholders only.

The config deploys to **capital-report** and provisions a SQLite Durable Object class through migration `v1`. It does not need KV, R2 or a database account ID. Inspect the existing Worker's bindings/migrations before applying this new migration to any Worker that already has production Durable Objects.

After deployment, set `CAPITAL_REPORT_ADMIN_TOKEN` in the shell environment and run:

```text
node scripts/smoke.mjs https://YOUR-WORKER.workers.dev --poll
```

The script checks public status, rejects an unauthenticated mutation, optionally bootstraps one real SEC scan, and replays both real historical fixtures twice to prove parser acceptance and persistent duplicate handling. Replays never change the live filing feed. The script prints a compact JSON result without the token. Keep the token only in a secure secret store after use.

Configure the Streamlit server with the public worker base URL (`SEC_MONITOR_URL`, or the committed `data/sec-monitor.json` configuration in this repository's client). The admin token is unnecessary for reading the feed.

## Validation and source fixtures

35 tests run in workerd, covering actual primary-filing HTML, arithmetic reconciliation, missing/changed layouts, unsafe URLs, malformed SEC responses, body limits, DST transitions, window boundaries, durable 30-second alarms, duplicate receipts after eviction, amendments, 403/429 backoff (including server cooldowns longer than a day), 404 document retries, network failure preservation, concurrent polling, public read-only routes and authenticated replay isolation.

The test plugin currently ships an older runtime. `vitest.config.ts` selects the workerd binary bundled with the pinned production Wrangler so tests use the same September 7 compatibility date. Tests mock SEC requests and do not use a real contact or send network requests to EDGAR. Some dependencies emit source-map warnings during tests; the checks themselves pass.

- [Strategy August 31, 2026 weekly 8-K](https://www.sec.gov/Archives/edgar/data/1050446/000119312526375463/mstr-20260831.htm)
- [Strive August 31, 2026 weekly 8-K](https://www.sec.gov/Archives/edgar/data/1920406/000162828026059468/asst-20260831.htm)
- [SEC fair-access rules and public data APIs](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- [Cloudflare Durable Object alarms](https://developers.cloudflare.com/durable-objects/api/alarms/)
- [Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)
- [Cloudflare Workers best practices](https://developers.cloudflare.com/workers/best-practices/workers-best-practices/)
