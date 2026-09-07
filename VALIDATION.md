# Report and SEC monitor validation

Validated locally September 7, 2026 with Python 3.12, Streamlit 1.63.0 and Pillow 12.3.0.

## Completed checks

- All **129 Python tests pass** (31.095 seconds). Coverage includes the financial calculations, source-based
  period baselines, missing/nonpositive inputs, consistent market marks, quote
  refresh success/failure, the offline filing rehearsal, and all report layouts.
  Eleven monitor-client tests validate bounded responses, schemas, trusted SEC
  links and baseline separation. AppTest verifies that new feed observations
  and outages retain the report PNG and saved quote cache. These tests block
  network access even when the production monitor URL is configured.
- All **35 Worker tests pass** in workerd, covering actual historical HTML,
  parser validation, 30-second alarms, DST and schedule boundaries, persistent
  duplicates, amendments, concurrent polls, source backoff, bounded retrieval,
  read-only public routes and isolated authenticated replay.
- The redesigned Post view follows the requested order, uses restrained type
  sizes and small colored growth figures, removes formulas, and retains VWAP,
  preferred transaction and average-repurchase disclosures.
- Total BTC held tracks the ending snapshot in HTML, both PNG layouts and
  accessible preview text. Zero and unknown holdings remain distinct. The
  bottom panel has more padding and row spacing, retaining the 1800 × 1125 size.
  The capital-period heading now has additional clearance below the BTC row.
- Strive's live API YTD yield reproduces as 40.81516346%; the report's basic-share
  result reconciles to 45.55897656%. The source audit documents the different
  share bases and the unresolved historical RSU count in the issuer data.
- Current and historical reports contain actual QTD/YTD growth. Illustrative
  inputs never inherit real-company baselines. Strive's baseline dividends were
  reconciled to accrued claims; full future GAAP payables are not added.
- Streamlit AppTest checks the two view modes and both bottom explanation/source
  expanders, along with price refresh and recovery. Browser inspection verified
  the current card, methodology expansion and all period results. The full card
  and collapsed explanation controls fit the observed 842 × 698 viewport.
- Measured renderer bounds checks pass for all editions, long disclosures, and
  missing values. The seven saved PNG fingerprints below were recomputed after
  the capital-heading spacing change.

## Live Worker verification

The [production status endpoint](https://capital-report.alatimore06370.workers.dev/api/status)
is live on Worker version `8c4fcbcb-3ffd-4658-81bd-d9bf828bf2d4`.
At **2026-09-07T21:38:50Z**, the live smoke run confirmed public schema version
1, HTTP 401 for an unauthenticated admin call, and successful real SEC polls
for MSTR and ASST, fetching two documents per issuer. Both historical HTML
replays returned `validated_for_review`; repeats returned `duplicate` without
altering the live feed. Next scheduled window: **September 14 at 06:45 EDT**.

This validates deployment, connectivity and parser/replay behavior. It does not
establish release-to-screen latency for a new filing or automatic publication
of fully reconciled financial cards. See LIVE_UPDATES.md for that distinction.

## Public Streamlit verification

The public [Digital Credit Report](https://digital-credit-report.streamlit.app/)
was deployed from `bobat2121-lgtm/digital-exposure`, branch `main`, entrypoint
`app.py`, using Python 3.12. Browser verification on September 7 confirmed the
current Post view, both logos, total BTC, the added capital-heading clearance,
dated market marks and QTD/YTD results. The complete card and collapsed
explanation controls fit the observed 842 × 698 viewport.

The methodology expander reproduced the Strive 40.8% versus 45.56% denominator
explanation. The Sources & input audit expander connected to the production
Worker and displayed both issuers configured, successful SEC checks at
21:44:38–39 UTC, no source errors, and extracted filing facts.

Both view modes and all three report editions rendered successfully on the
deployed app. The PNG download control was exercised. The hosted current Post
PNG is 1800 × 1125; its decompressed PNG scanlines exactly match the local
export (SHA-256 `c4567c2cd70e60c84c0eda432287091d6a02586fe744df243fac19eb65efb1c8`).
Cloud and Windows PNG compression produce different file bytes without
changing the rendered pixels.

## Data timing

The saved quotes were retrieved September 7 at 16:34:47 ET: BTC $79,207.14,
MSTR $142.80, ASST $27.14, STRC $97.75 and EUR/USD 1.1625. Equity observations
retain September 4 closing times. Verified ending balances remain Strategy
August 30 and Strive August 28; financing activity is August 24–30. QTD begins
June 30 and YTD December 31, 2025. All NAV growth is at constant prices with
explicitly estimated claims. See PERIOD_GROWTH.md for values and provenance.

## Export fingerprints

- `monday-capital-report-current-prices-post.png` — 1800 × 1125
  SHA-256: `0c028a898873a3e99cbc50e4a1c67e82c2d886880540f9f267e0b80fb69fa7da`
- `monday-capital-report-current-prices-detailed.png` — 1800 × 1988
  SHA-256: `3ec4d52863956521290376fef7124a32742f43c4034d88063b9c7e89135198f9`
- `monday-capital-report-2026-08-31-post.png` — 1800 × 1125
  SHA-256: `a0831bad951aa5c3533353fead122ad7689cffb4d75410a7de091aea3b5665b3`
- `monday-capital-report-2026-08-31-detailed.png` — 1800 × 1988
  SHA-256: `eb7119757511c9bb65a062f050d84dc836abf6b609e03f6623c89115d744e930`
- `monday-capital-report-post.png` — 1800 × 1125
  SHA-256: `cbfecd33088a340c8c9c4e861943d0ee7b042badb13a129b43e0aaf5ab5fc66f`
- `monday-capital-report-illustrative.png` — 1800 × 1710
  SHA-256: `81df33d500afcd9ad8b2886010cd9454218aeee6705bb4383bceb4bbee4b9bfc`
- `monday-capital-report-current-prices-x-demo.png` — 1800 × 1125
  SHA-256: `b3bc64d12310a453bc7fbc69fa4d7aea2066aac5bf899209cfc6e61b0feed7b3`

The live monitor is connected through `data/sec-monitor.json`. Financial cards
remain on the stated verified balance dates until complete supplemental inputs
are reconciled. Public Streamlit site deployment and browser verification are
recorded separately in DEPLOYMENT.md.
