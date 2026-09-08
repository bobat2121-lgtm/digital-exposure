# Digital Credit Report deployment

Public report: [digital-credit-report.streamlit.app](https://digital-credit-report.streamlit.app/).
Worker: [capital-report.alatimore06370.workers.dev](https://capital-report.alatimore06370.workers.dev/).

## Streamlit configuration

| Field | Value |
| --- | --- |
| Repository | `bobat2121-lgtm/digital-exposure` |
| Branch | `main` |
| Entrypoint | `app.py` |
| Subdomain | `digital-credit-report` |
| Python | `3.12` |
| App access | Public |

Community Cloud automatically updates the app from `main`. The public release
uses the Imprint dot title, responsive company panels, Market Activity section,
QTD/YTD panel, concise calculation overview and a discreet PNG download. Phones
stack the company panels; the downloadable image stays 1800 × 1125.

On each new browser session or page reload, the report requests a complete
price snapshot from the existing sources. It keeps that snapshot for normal
reruns, downloads and SEC-feed updates. If a refresh fails, the newest complete
in-memory snapshot or bundled fallback is retained with its original timestamps
and a short notice. Public visits do not write repository files.

The public Worker feed remains read-only. There are no public refresh/VWAP
controls or notification credentials in the app. Refreshing quotes does not
advance the financial balance dates or alter the Worker polling schedule.

The root entrypoint, requirements, `report/`, `assets/` and `data/` must remain in
Git. Dependencies are pinned; Lato fonts and fixed title artwork are bundled.
No Georgia font installation is required on the Linux host. The local launcher
binds to `127.0.0.1`; hosting controls the production bind address. CORS and XSRF
protection retain Streamlit's defaults.

## Independent Discord notifications

The unattended Worker was deployed September 7, 2026. Code upload version:
`39f0b038-b045-4f4f-a187-05c716f16684`. Final active version after removing the
unused acknowledgement secret: **`93111efc-60dd-4f3c-a14d-687ef7111626`**.

SEC polling remains Monday 06:45–09:30 America/New_York, targeting 30-second
intervals. The next window after deployment is September 14, 2026 at 06:45 EDT.
The fixed initial notification cutoff is `2026-09-08T00:00:00Z`; preserve it on
future deployments so pending eligible receipts are not discarded.

Each completed filing creates a durable publication event. The per-Monday
coordinator verifies both exact filings and hashes in the feed Streamlit reads,
then sends a combined Discord alert. Persistent retries continue outside the
SEC window without making new SEC requests. Existing sent records and Discord
cooldowns survive deployment. No Streamlit page or browser acknowledgement is
required. The retired acknowledgement route returns 404.

The notification confirms **filing-feed publication**. Financial cards keep
their dated verified balances until reconciliation; the message does not claim
that the cards were automatically recalculated or that a browser rendered them.
See [LIVE_UPDATES.md](LIVE_UPDATES.md) and the [Worker runbook](worker-capital-report/README.md).

## Verification

- All **135 Python tests** passed. The read-only monitor's 12 relevant tests
  passed again after its public error message was shortened.
- All **71 Worker tests**, TypeScript checks and Wrangler dry-run passed.
  Tests cover no-browser ingestion, exact feed verification, failed handoffs,
  restart recovery, concurrent arrivals, late-window retries and deduplication.
- Local desktop and 375px phone layouts were inspected; the mobile panels stack
  without horizontal overflow. The X image was rendered and inspected.
- At `2026-09-07T23:42:29Z`, the live Worker retained all 100 public filing
  records, rejected unauthenticated administration with 401, and returned 404
  for the retired acknowledgement route.
- The new, clearly labeled Discord setup test was confirmed on its first
  attempt. Repeating it retained message ID `1546666994848497726` and attempt
  count 1. The earlier setup receipt remains intact; no historical weekly alert
  was sent. This test ran without opening the hosted Streamlit page.

The local fixture tests exercise the complete unattended ingestion path. The
live setup test verifies deployed Discord delivery. Actual release-to-alert
latency still needs a future real Monday pair; 30 seconds is a polling target,
not a guaranteed end-to-end delivery time.

## Credentials and public access

Discord and administration credentials belong in Cloudflare secrets, never
Git or browser code. The unused Cloudflare `STREAMLIT_ACK_TOKEN` was deleted.
The Streamlit application no longer reads it. Future private data connections
should use Community Cloud's server secret settings.

The public repository reveals source and formulas, not deployment privileges.
The targeted repository/history scan identified only dummy test credentials.
See [SECURITY.md](SECURITY.md) for scope, residual risks and maintenance guidance.

After each release, verify the hosted title, both panels, calculation overview,
Latest SEC filings and PNG download. Keep Worker health checks separate from
page checks: a successful page load alone does not prove a new filing was ingested.

## Bitcoin activity update — September 7, 2026

The web report and generated PNG now label explicit gross activity as Bitcoin
Bought or Bitcoin Sold, showing both when both are reported. Missing activity
stays unknown; a change in holdings never establishes a purchase or sale.
The public filing table also exposes the separate reported quantities.

Worker version `21cb4dc4-6f33-4ca8-88fc-918a8ac38798` uses parser
`sec-weekly-v2`. Sales-only filings, including zero ending BTC holdings, can
qualify for the existing paired Monday notification. Conflicting or malformed
BTC activity is held for review. The alert includes gross Bought/Sold amounts
from the verified public feed; publication checks, retries and deduplication
are unchanged. No market-price feed or widget was added.

Validation: 144 Python tests passed, followed by nine focused activity/monitor
tests after the final formatting guard; 107 Worker tests, TypeScript and dry-run
passed. Sale-only, mixed activity and long fractional quantities fit the
1800 × 1125 PNG and a 375px phone layout. Production report balances still
advance after reconciliation. Synthetic sale scenarios were tested locally,
never published as real filings or sent to the live Discord channel.

## Page-load price refresh — September 7, 2026

Each browser opening/reload fetches the existing five sources once. The shared
fallback stays in server memory; concurrent requests cannot replace newer
quotes with older observations. Downloads and normal reruns keep the session's
complete snapshot. The PNG cache is bounded to 32 entries. No extended-hours
feed, real-time widget, repository write or Worker change is involved.

All 156 Python tests passed, including 16 focused store/app checks. A live-source
smoke request returned a complete fresh bundle in about three seconds. Stock
timestamps correctly remained at the prior regular-session close.
