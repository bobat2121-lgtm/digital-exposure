# The Digital Credit Report

A single-page Streamlit report comparing Strategy (MSTR) and Strive (ASST).
The hosted app is at [digital-credit-report.streamlit.app](https://digital-credit-report.streamlit.app/).
This checkout contains the approved public redesign; see [DEPLOYMENT.md](DEPLOYMENT.md)
for rollout status. Each page opening or browser reload refreshes the existing market-price
sources while retaining the verified August 30 / August 28 balance snapshots. The Imprint title, responsive panels, and compact download
share the same figures. See [PUBLIC_REPORT.md](PUBLIC_REPORT.md) for the design
and [CURRENT_PRICES.md](CURRENT_PRICES.md) for quote sources and snapshot dates.

The live [capital-report SEC monitor](https://capital-report.alatimore06370.workers.dev/api/status)
checks both issuers every 30 seconds on Mondays, 06:45–09:30 Eastern. Its
[filing feed](https://capital-report.alatimore06370.workers.dev/api/filings)
appears under **Latest SEC filings** and refreshes every 15 seconds while
the report session is open. New filings and parsed facts update there;
**the financial cards retain their verified figures until all required NAV
inputs and supplemental balances are reconciled**. See
[LIVE_UPDATES.md](LIVE_UPDATES.md) for timing, parser coverage and limitations,
and [DEPLOYMENT.md](DEPLOYMENT.md) for the deployed services.

The replay now populates NAV/share, amplification and preferred/BTC using
reported balances and explicit estimates, marked **≈**. Strategy uses
reconstructed preferred claims, designated liquidity and a June 30 debt
carryforward; Strive uses dated company debt records and a conservative SATA
claim estimate. It is a historical reconstruction, not an archived 09:00 ET
snapshot. Equity references are August 28 closes; BTC is an August 31, 08:30 ET
observation. See [HISTORICAL_SOURCES.md](HISTORICAL_SOURCES.md) for component
math, sources, financing scope and the remaining estimation limits.

## Run locally

Use Python 3.12 to match the deployed environment. From this repository:

In this prepared workspace, `./launch.ps1` reuses the installed local environment.
For a fresh checkout, use:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py --server.address 127.0.0.1
```

On macOS/Linux, use `.venv/bin/python` instead. Open the local URL printed by
Streamlit (normally http://127.0.0.1:8501). The report renders without
API keys. Each new browser session attempts a complete price refresh from the
existing providers; ordinary reruns, downloads and SEC-feed updates reuse that
session’s prices. If refresh fails, the app retains the latest complete in-memory
snapshot or the bundled fallback and shows a short notice with the original
quote timestamps. It never writes the repository on a public visit. The read-only
filing monitor also uses the network; its outage retains the card and last feed.
Local scripts still support maintained quote snapshots and historical VWAP updates.

The public report has one responsive view: two aligned company panels on
computer screens, stacked panels on phones. A discreet **Download** button at
the bottom saves a fixed 1800 × 1125 PNG for X. There are no public edition
selectors, post/detail tabs, or price-refresh controls.

**Calculation overview** explains the metrics in 279 words. Market Activity
groups common capital, preferred capital, and effective common shares.
Strategy's proceeds-based average sale price, Strive's VWAP proxy, and
preferred repurchase prices remain visible. Total BTC, weekly changes,
and QTD/YTD growth use the shared calculation model. Source reconciliations
remain in [PUBLIC_CALCULATION_AUDIT.md](PUBLIC_CALCULATION_AUDIT.md),
[STRIVE_YIELD_AUDIT.md](STRIVE_YIELD_AUDIT.md), and [PERIOD_GROWTH.md](PERIOD_GROWTH.md).

You can also export without running Streamlit:

```powershell
.venv\Scripts\python export_png.py
.venv\Scripts\python refresh_prices.py
.venv\Scripts\python export_png.py --edition historical --layout detailed
.venv\Scripts\python export_png.py --edition illustrative --layout post
.venv\Scripts\python -m unittest discover -s tests -v
```

`--edition current|historical|illustrative` defaults to `current`;
`--layout post|detailed|x-demo` defaults to `post`. Current files use
the redesigned layout; `x-demo` is retained only as a labeled preview alias.
Current filenames are
`monday-capital-report-current-prices-<layout>.png`. Historical filenames are
`monday-capital-report-2026-08-31-post.png` and
`monday-capital-report-2026-08-31-detailed.png` for the replay, or
`monday-capital-report-illustrative-post.png` and
`monday-capital-report-illustrative-detailed.png` for the sample. Use
`--output <path>` to choose another destination.

## Refresh the ASST price estimate

Refresh the saved historical VWAP through the local script:

```powershell
.venv\Scripts\python pull_vwap.py --edition 2026-08-31 --window auto
```

`--edition YYYY-MM-DD` fixes the report date. `--window auto|prior_week|five_sessions`
defaults to `auto`: try the prior calendar week, then the previous five completed
trading sessions before the edition. Sessions follow the NASDAQ calendar,
including holidays and early closes. Both windows select August 24–28 for this
Monday replay. A failed refresh retains the dated cache; it never substitutes
today's latest price. Results and provenance are saved in
`data/asst-vwap-2026-08-31.json` for this edition.

The saved estimate is **$21.48698**, calculated as
`sum(((minute high + low + close) / 3) × minute volume) / sum(minute volume)`.
This uses 1,950 Yahoo regular-session minute bars with 60,213,874 shares of volume;
the daily historical volume totals 62,508,500. It is a **minute-bar VWAP estimate**
for the retrieved sessions, not an exact trade-weighted or consolidated-market
VWAP. Applying it to 3,579,147 net new shares gives **+$76.9m estimated common
capital before fees**, not actual issuance proceeds. An exact VWAP upgrade would
require suitable trade/VWAP data; credentialed provider integrations are not
implemented.

## Structure

- `report/models.py`: immutable provider-neutral input types.
- `report/historical_data.py`: sourced August 31 balances, flows and labeled estimates.
- `report/historical_claims.py`: reproducible preferred claims and debt carryforward.
- `report/current_prices.py`: existing provider fetch/validation and local saved snapshots.
- `report/price_refresh.py`: fresh fetch per opening with an isolated, complete in-memory fallback.
- `report/current_report.py`: reprice the dated snapshots without changing flows.
- `data/current-prices.json`: complete current quote cache with provider timestamps.
- `pull_vwap.py`: on-demand dated ASST minute-bar estimate refresh.
- `data/asst-vwap-2026-08-31.json`: saved estimate and source provenance.
- `data/strive-treasury-2026-08-31.json`: dated company debt and dividend evidence.
- `data/strategy-basic-shares-2026-08-31.json`: dated common-share provenance.
- `data/preferred-price-windows-2026-08-31.json`: raw-close formula inputs.
- `data/ecb-eurusd-2026-08-21-28.csv`: official dated EUR/USD reference rates.
- `report/sample_data.py`: explicit current and saved-prior illustrative fixtures.
- `report/calculations.py`: pure financial formulas and transaction rules.
- `report/presentation.py`: one formatted view, shared by page and image.
- `report/public_page.py` and `assets/public.css`: the responsive public report.
- `report/page.py` and `assets/report.css`: legacy detailed export presentation.
- `report/png_export.py`: deterministic Pillow export with bundled logos/fonts.
- `report/post_export.py`: compact post image, using the same formatted figures.
- `report/branding.py` and `assets/title-imprint.png`: the approved PNG title artwork.
- `report/methodology.py`: concise public definitions and preserved legacy methodology.
- `report/filing_monitor.py`: public feed validation and the 15-second Streamlit fragment.
- `data/sec-monitor.json`: deployed Worker origin, with no administration credentials.
- `worker-capital-report/`: SEC discovery, issuer parsers, Durable Object scheduling and tests.
- `tests/`: expected results, edge cases, and export validation.

Future providers can create the same `Report`, `Company` and `Snapshot` types.
Persist prior editions with their own prices and quantities. Supply prior
securities at current prices and foreign preferred claims at current FX for
constant-price NAV. A combined liquid-asset input supports disclosed totals
whose cash/securities split is unavailable, without counting reserves twice.
The Cloudflare Worker handles scheduled SEC discovery and supported filing
extraction. Streamlit reads its public feed and refreshes prices when a browser
session opens; local scripts can maintain the bundled fallback. Automatic publication of a complete financial card remains separate:
new filings must be reconciled with every required balance, claim and price
input before replacing the verified report.

## Data conventions

`None` means an input is unavailable or not disclosed; confirmed zero is
explicit. Missing gross transactions are never inferred from net share changes.
Effective common shares are Class A plus Class B, not EPS averages.

In the historical replay, Strategy's **+$602.8m** common capital is reported ATM
proceeds net of commissions. Its **−$151.8m** preferred capital is reported STRC
repurchase cash within the filing's STRF/STRC/STRK/STRD table. Unreported STRE
activity is not assumed zero. Strive discloses weekly outstanding-share changes,
but verified weekly gross financing cash is missing. Its common-capital row
uses the labeled minute-bar estimate above. The SATA capital row uses the
requested **803,099 net new shares × $100 = $80.3099m**, shown as **+$80.3m
estimated before fees**. Actual gross issuance, repurchase cash and fees remain
undisclosed. This financing proxy does not alter cash, preferred claims or NAV.

Strategy's valuation uses $6.71bn current / $6.69bn prior combined designated
liquidity, with reserve Treasury bills included once. Comparable debt principal
of $6.753703bn is explicitly carried from June 30 to both snapshots. Preferred
claims are reconstructed from series counts, certificate preference rules,
estimated unpaid dividend accruals and dated ECB EUR/USD rates. Prior STRE
claims are repriced at current FX for the weekly comparison. Both common
denominators come from dated company tables rounded to thousands. Ending-share
dividend accruals are estimates, not an exact record-holder liability ledger;
no additional operating-cash carryforward is included.

Strive's dated company records report zero debt at both Friday snapshots.
Cash and its 505,000-share STRC investment remain separate; prior STRC holdings
are marked at the current price for the weekly comparison. SATA's certificate
and dated quotes support $100 prior preference and $100–$100.01 current
preference. The report uses the conservative $100.01 endpoint and zero
additional unpaid accrual after the Friday payments, corroborated by company
payment history. The resulting **≈ $12.23 NAV/share** rises **≈ 2.67%** at
constant prices, while BTC/share rises **4.27%**. The approximately $80.4m
increase in senior preferred claims helps explain that gap.

The post uses short transaction notes; full source reconciliations remain in
the repository audit documents. **Price / basic NAV** names the report's basic-share
valuation basis explicitly; it is not a reproduction of either issuer's mNAV.

All historical valuation metrics carry **≈** because of these specific
assumptions and bounds. Reported financing cash is labeled separately. Sources
retrieved or updated after the edition date make this a reconstruction, even
when the underlying financial record is dated to the correct week.

In the illustrative edition, Strive common capital is **3.6m net new effective
shares × assumed $27.50 prior-week VWAP = $99.0m**, before fees. Preferred
issuance at $100 and repurchases at assumed weekly VWAP are modeled, including
the $93.75 STRC fixture input. These estimates never update balance-sheet
assets or claims. The sample's cash includes reserves once and its $50m STRC
investment is separate. Its net BTC increases are specified; gross purchases
are not disclosed. The methodology explains the sample's 4.26% BTC/share gain
versus 2.88% constant-price NAV/share gain. Preferred claims still reduce NAV
although their separate change row is omitted from the page and PNG.

## Assets and implementation references

The original company SVGs were supplied with the user's reference design;
the PNG logo assets are rasterizations of those files. Company marks remain
their respective owners' property. Lato fonts are bundled under the SIL Open
Font License in `assets/FONT-LICENSE.txt`, from the
[Google Fonts Lato source](https://github.com/google/fonts/tree/main/ofl/lato).

The app uses Streamlit's documented [HTML](https://docs.streamlit.io/develop/api-reference/text/st.html)
and [download button](https://docs.streamlit.io/develop/api-reference/widgets/st.download_button)
APIs. The export needs only Pillow and runs without browser automation. The
fixed [Imprint title artwork](assets/BRAND-TITLE.md) preserves the approved
Georgia/Lato appearance without bundling a Microsoft font.

See `VALIDATION.md` for the completed formula, layout and download checks.
