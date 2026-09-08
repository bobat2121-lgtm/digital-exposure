# Live SEC filing monitor

The **capital-report** Cloudflare Worker is live. It discovers Strategy and
Strive 8-K / 8-K/A filings, retrieves primary documents, and publishes parsed
facts with source links and timestamps:

- [Monitor status](https://capital-report.alatimore06370.workers.dev/api/status)
- [Filing feed](https://capital-report.alatimore06370.workers.dev/api/filings)

The Streamlit financial panels and **Latest SEC filings** read this public feed
in one fragment every **15 seconds** while a session is open. Web and PNG use
the same report and the same page-load quote snapshot. No administrator token
is needed, and page views never trigger SEC requests.

## Schedule and behavior

Each issuer has a SQLite Durable Object that owns its polling state, filings,
deduplication, and retry alarm. SEC polling targets **every 30 seconds on
Mondays from 06:45 until 09:30 America/New_York**, shifted to Tuesday when
Monday is an EDGAR federal holiday. A minute Monday/Tuesday cron repairs the
alarm chain; the Eastern-time gate handles holidays and daylight saving.
Ordinary Tuesdays remain inactive.

Source failures can extend the interval. A 403 pauses the issuer for at least
30 minutes; a 429 honors Retry-After with a five-minute minimum. Other failures
use exponential backoff. Manual polls cannot bypass source cooldowns. The
status endpoint exposes success/error and next-alarm information.

Initial observations are marked **Initial baseline** so old filings discovered
during setup are separate from newly detected releases. Repeated accessions
retain their original timestamps and facts. Amendments have independent
accessions. The feed includes SEC acceptance, first-observed and successful
document-retrieval times, plus the source URL and SHA-256 of retrieved HTML.

## What updates on the report

New filing observations and extracted facts appear automatically. Supported
weekly tables and explicit zero-activity prose are checked for units and arithmetic.
`ready_for_review` and `extractionValidated: true` mean those extraction checks
passed; they do not establish a complete NAV calculation. Unknown or incomplete
layouts remain `partial`, `not_weekly`, or `document_error`, with missing inputs
and errors visible. A primary filing that only links to a press-release exhibit
is discovered, but requires another parser before those exhibit facts can be
extracted automatically.

**Validated filing pairs now advance the financial cards.** The resolver pairs
the activity week, preserving each company's balance date. Partial parses,
changed document hashes and amendments do not silently replace a verified
edition. Pending or rejected updates have a visible dated notice.

The SEC filing supplies BTC activity, balances and financing disclosures.
`data/report-supplements.json` supplies separately reconciled, date-specific
Strategy basic shares and debt, native-currency preferred claims, and Strive
debt. `data/latest-report-filings.json` is the last verified checkpoint for
new sessions during a feed outage. A complete new pair can advance reported
figures without supplemental NAV inputs: affected NAV figures then become
unavailable with an explicit notice; old claims or denominators are never
carried forward silently. **Supplement reconciliation is still required for
fully automatic future NAV editions.**

Strive common capital uses the exact dated saved VWAP; SATA uses net new
shares × $100. September 8 uses complete five-minute bars because two
one-minute observations were missing. Prior-week gaps suppress WoW
calculations; QTD/YTD become unavailable when their configured baseline expires.
Each candidate is calculated and rendered to both web and PNG before replacing
the session's report. Feed or rendering failures retain the last successful
version and show its balance dates.

## Discord notification

Cloudflare sends one combined alert after both new weekly primary 8-Ks are
retrieved, recognized as weekly BTC updates and published to the feed used by
Streamlit. No browser session is required. There is no separate document
upload into Streamlit: the app reads the Worker feed when opened and refreshes
it during an active session.

Each issuer atomically stores its receipt, a publication outbox event and a
recovery alarm. Failed handoffs retry after restart and after 09:30 without
extending SEC polling. The Monday coordinator verifies exact accessions,
SHA-256 hashes and source URLs through the same projection as `/api/filings`.
It persists the verified pair and publication time before sending Discord.

Both filings must be primary 8-Ks accepted in the same scheduled release week
(Monday, or Tuesday after an EDGAR Monday holiday),
received within 14 days and contain nonnegative BTC holdings plus an explicit
nonnegative weekly purchase or sale quantity. Sales-only filings and zero
holdings after liquidation qualify. Gross `weekly_btc_purchases` and optional
`weekly_btc_sales` remain separate; holdings declines, USD proceeds and equity
sales are never substituted for BTC sold. Malformed supplied activity or
BTC/reporting-period extraction errors prevent notification. Baselines,
amendments, unrelated filings and incomplete retrievals cannot qualify.
The fixed initial activation cutoff is **2026-09-08T00:00:00Z**; discovery and
retrieval must be on or after it. Preserve this cutoff on future deployments
so pending events remain eligible. Previously ingested records are not queued.

The message shows `Bought` and/or `Sold` quantities from the verified feed,
confirms feed publication and says Streamlit is expected to load
the feed when opened. It does not claim successful browser receipt or updated
financial cards. Candidate revisions retain a new event arriving during
verification. Existing confirmed sends and Discord retry deadlines survive
deployments. Discord retries continue independently of SEC polling. A rare
ambiguous network failure after Discord accepts a message may still duplicate
an unconfirmed delivery; confirmed sends remain deduplicated.

## September 8 recovery

The initial deployment skipped Labor Day's Tuesday releases, and the public
panels were still wired to the August 31 reconstruction. Both gaps were
corrected. The Strategy parser also now handles “approximately” before BTC
holdings and explicit zero BTC/ATM trading outside the usual tables.

Recovered filings: Strategy `0001193125-26-384402`, Strive
`0001628280-26-060809`. Strategy reports 845,050 BTC, no BTC trades or ATM sales,
and 1,810,885 STRC shares repurchased for $176.3m. Strive reports 24,531 BTC,
1,375 BTC bought, 94,934,558 effective common shares and 9,995,425 SATA shares.
The combined alert was confirmed sent at **2026-09-08T12:35:26.197Z**, attempt 1.

The dated NAV reconciliation includes STRF's $101.993 base preference,
newly declared accrued STRD dividends, and the scheduled STRC payment reset
assumption. Strive's September 4 SATA preference is $100 under both
certificate branches. Full audit inputs are committed in the dated JSON files.

Only Cloudflare stores `DISCORD_WEBHOOK_URL`. Streamlit requires no notification
secret. The old `/api/streamlit/ack` route is retired and returns 404, and
`STREAMLIT_ACK_TOKEN` can be removed from both secret stores after rollout.

Authenticated `POST /api/admin/notifications` returns publication checks,
outboxes and delivery failures. `POST /api/admin/discord-test` uses the separate
stable key `test:discord-unattended-v1`, sends one clearly labelled setup test,
and preserves the prior setup receipt. The Worker runbook documents retries
and operational limits. Public feed routes remain read-only.

## Initial deployment verification

Worker version: `8c4fcbcb-3ffd-4658-81bd-d9bf828bf2d4`.
Production secrets were configured in Cloudflare. The live smoke check at
**2026-09-07T21:38:50Z** confirmed:

- Public status/feed schema version 1 and rejection of unauthenticated admin
  requests with HTTP 401.
- A successful real SEC poll for each issuer, fetching two documents each.
- Both real historical HTML fixtures returned `validated_for_review` in the
  isolated replay endpoint; repeated replay returned `duplicate`.

The bootstrap scan verifies connectivity and document processing. It does
not measure the delay for a newly published Monday filing. The 30-second SEC
target and 15-second page refresh are scheduling intervals, not guaranteed
release-to-screen latency. SEC dissemination, delayed documents, retries,
Cloudflare scheduling, and page caching also contribute.

See [the Worker runbook](worker-capital-report/README.md) for endpoints,
deployment commands, credentials, parser coverage and the authenticated smoke
script. Worker tests use mocked SEC and Discord requests in workerd. They include
no-browser publication, atomic outbox storage, post-window retry and race
recovery. Python tests cover read-only feed refresh, trusted links, baseline
separation, stale-feed recovery and preservation of the report PNG and quotes.

## Archived offline publication rehearsal

The earlier local rehearsal below remains useful for testing complete-report
validation and atomic publication. It is separate from the live discovery and
parser feed, and its fixture does not change the Streamlit report.

Run this offline rehearsal from the repository using the installed environment:

In this prepared Windows workspace, `./replay_filing_update.ps1` automatically
uses the available environment. Alternatively, with Python activated:

```powershell
python replay_filing_update.py --output-dir work/filing-replay
python -m unittest discover -s tests -p test_filing_replay.py -v
```

In the prepared Windows workspace, use `..\..\work\.venv\Scripts\python.exe`
in place of `python`. The September 7 rehearsal passed all three scenarios:
publication took **979.680 ms** locally, duplicate handling **0.742 ms**, and
incomplete-input rejection **0.072 ms**. Rendering both PNGs took **941.600 ms**
of the publication phase. The six focused tests also passed, covering missing
supplemental inputs, rendering failure and atomic-replacement failure. These
are one machine's rehearsal measurements, not live SEC latency measurements.

Every default run creates a fresh directory containing the valid and invalid
input fixtures, `published-replay.json`, and readable/JSON results. It exercises:

1. A new accession: parse normalized JSON, validate facts and the complete
   report candidate, calculate metrics, render both PNG layouts, then publish
   the complete JSON with one atomic file replacement.
2. The same accession and content: return `duplicate`, with no recalculation,
   rendering, rewrite or additional financing flows.
3. An incomplete new input: reject it and retain the previous publication byte
   for byte. Conflicting content under an existing accession also fails.

The fixture uses the documented [Strategy August 31 8-K](https://www.sec.gov/Archives/edgar/data/1050446/000119312526375463/mstr-20260831.htm)
facts: $602.8m ATM proceeds, 1,557,177 STRC shares repurchased for $151.8m, and
4,603 BTC purchased. This is a **manually normalized JSON fixture**, not an
HTML extraction test. Other company balances, basic shares, claims estimates,
market prices and Strive inputs come separately from `historical_report()`;
the rehearsal does not claim that the weekly filing supplies them all.
Changed preferred share activity is rejected until its supplemental claims
schedule is rebuilt, preventing a new count from silently using old claims.

The SEC acceptance timestamp is 08:00:15 ET. Receipt at 08:00:30 is an explicit
simulation, making detection latency **15 seconds by construction**. Parse,
validation, rendering and atomic-write durations are measured locally with a
monotonic clock. The reported combined time mixes that simulated delay with
measured processing; it is not evidence of live detection speed or a production
latency guarantee. Phase timings identify what needs measurement next.

The published JSON contains the complete report, calculated metrics, source
metadata and hashes/sizes of the two PNGs rendered in memory. It is isolated
from the Streamlit app, its historical fixtures and `data/current-prices.json`.
To replay an edited fixture against an existing rehearsal directory:

```powershell
python replay_filing_update.py --input path/to/fixture-valid.json --output-dir path/to/run-directory
```

The live Worker now supplies discovery, source timestamps, accession/amendment
handling, retry/backoff, primary-document hashes and supported issuer parsers.
The archived rehearsal needed reconciled supplemental inputs and
a publication store consumed by the financial cards; the live consumer is
described above. This archived
fixture assumes a simple BTC purchase bridge; disposals and transfers require
additional rules. Its local publisher is single-writer.

## Historical release observations

The five August 2026 Monday observations show Strategy's weekly 8-K accepted
at approximately 08:00:15–16 ET. Strive's usual observations were 07:59:24–49,
with an earlier **06:59:35 ET on August 10**. These are acceptance times, not
guaranteed release times or first-public-availability timestamps. Sources:
[Strategy Aug31 filing detail](https://www.sec.gov/Archives/edgar/data/1050446/000119312526375463/0001193125-26-375463-index.htm),
[Strive Aug31 filing detail](https://www.sec.gov/Archives/edgar/data/1920406/000162828026059468/0001628280-26-059468-index.htm),
[Strive Aug10 filing detail](https://www.sec.gov/Archives/edgar/data/1920406/000162828026054983/0001628280-26-054983-index.htm),
and the official submissions histories for [Strategy](https://data.sec.gov/submissions/CIK0001050446.json)
and [Strive](https://data.sec.gov/submissions/CIK0001920406.json).

The [SEC Webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)
describes documents as often available 1–3 minutes after acceptance, potentially
later under load; the first public availability does not have its own published
timestamp. The [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
describes submissions processing as typically under one second **after
dissemination**. Those are different intervals. A parser cannot process a
document before the source makes it available.

The deployed schedule starts at 06:45 Eastern to cover those observed release
times. Its identifying User-Agent and source backoff follow the SEC's
[fair-access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).
Unrelated 8-Ks are recorded without advancing the weekly financial report.

## Future acceptance target for automatic card publication

Acceptance testing should log these stages against the same accession and
publication version:

1. `accepted_at`: SEC's source timestamp, preserved without modification.
2. `first_seen`: the monitor's first successful retrieval of public filing
   metadata; separately record first successful document retrieval.
3. `parsed_at` and `validated_at`: complete extraction and reconciled report
   inputs, with missing fields recorded explicitly.
4. `published_at`: the committed complete version, after calculations and
   rendering checks succeed.
5. `browser_displayed_at`: browser verification that the page loaded that exact
   accession/version, rather than retaining an older cached card.

An initial engineering acceptance target is **p95 ≤120 seconds from the
monitor's public `first_seen` to verified browser display**, measured across a
declared sample of real releases. This is a target to test, not a guarantee;
report sample size, failures, maximum latency and acceptance-to-first-seen
delay separately. Exercise duplicate notices, partial documents, delayed
supplemental data, amendments, source failures and browser cache invalidation.
Any incomplete update must retain the previous complete displayed version and
surface a clear freshness/error state. The offline test measures only the
local processing portion of that future end-to-end workflow.
