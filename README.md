# The Monday Capital Report

A local, single-page Streamlit prototype comparing Strategy (MSTR) and Strive
(ASST). It opens with **Current prices · dated balances**, using the latest
saved market quotes and the verified August 30 / August 28 balance snapshots.
Use **Refresh prices** to update all five market references together. The
edition selector also preserves the **August 31 historical replay** and
September 7 **Illustrative example**. See [CURRENT_PRICES.md](CURRENT_PRICES.md)
for current quote sources, timing and the fixed balance/activity dates.

The replay now populates NAV/share, amplification and preferred/BTC using
reported balances and explicit estimates, marked **≈**. Strategy uses
reconstructed preferred claims, designated liquidity and a June 30 debt
carryforward; Strive uses dated company debt records and a conservative SATA
claim estimate. It is a historical reconstruction, not an archived 09:00 ET
snapshot. Equity references are August 28 closes; BTC is an August 31, 08:30 ET
observation. See [HISTORICAL_SOURCES.md](HISTORICAL_SOURCES.md) for component
math, sources, financing scope and the remaining estimation limits.

## Run locally

Python 3.11 or newer is required. From this repository:

In this prepared workspace, `./launch.ps1` reuses the installed local environment.
For a fresh checkout, use:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

On macOS/Linux, use `.venv/bin/python` instead. Open the local URL printed by
Streamlit (normally http://127.0.0.1:8501). Saved editions run without API keys or
network access; refreshing current prices or the historical VWAP requires a
network connection. Market refreshes preserve actual quote timestamps and
replace the saved snapshot only when all quotes validate successfully.

The app opens in **Post view**: a compact 1800 × 1125 card with both companies
side by side. The entire image scales to fit the browser window for a screenshot.
Use **Download post PNG** to save the full-resolution image for a weekly X post;
the downloaded resolution is independent of the screen size. This is the exact
image displayed in Post view, with no controls included in the download.

Choose **Detailed view** for the longer responsive report. Both views provide
**How the numbers are calculated** and **Sources & input audit** beneath the
card. Both layouts and downloads use the selected edition.
The redesigned Post view uses balanced text sizes, a separate weekly-change
column, total BTC held beside weekly purchases, and actual QTD/YTD basic-share
growth from reconciled period baselines. The bottom audit explains Strive's
40.8% issuer KPI versus this report's 45.56% basic-share result; see
[STRIVE_YIELD_AUDIT.md](STRIVE_YIELD_AUDIT.md) for the source reconciliation.
Formulas live below the card; VWAP and preferred transactions remain identified
on it. See [DESIGN_DEMO.md](DESIGN_DEMO.md) for the layout and
[PERIOD_GROWTH.md](PERIOD_GROWTH.md) for the calculations and source audit, and
[LIVE_UPDATES.md](LIVE_UPDATES.md) for the offline filing-update rehearsal and
the work required to connect live filings.
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

Below either view, expand **Sources & input audit**, select the window and click
**Pull ASST VWAP**. The equivalent command is:

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
- `report/current_prices.py`: fetch, validate and atomically save current quotes.
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
- `report/page.py` and `assets/report.css`: responsive HTML and visual styling.
- `report/png_export.py`: deterministic Pillow export with bundled logos/fonts.
- `report/post_export.py`: compact post image, using the same formatted figures.
- `assets/post.css`: scales the post image within the available viewport.
- `report/methodology.py`: expandable definitions and the underlying input audit.
- `tests/`: expected results, edge cases, and export validation.

Future providers can create the same `Report`, `Company` and `Snapshot` types.
Persist prior editions with their own prices and quantities. Supply prior
securities at current prices and foreign preferred claims at current FX for
constant-price NAV. A combined liquid-asset input supports disclosed totals
whose cash/securities split is unavailable, without counting reserves twice.
Only the optional equity-price refresh fetches external data. Automated filing
ingestion, scheduling and deployment are not included.

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

The main post uses shorter transaction notes, with the full explanations kept
in the source audit. **Price / basic NAV** names the report's basic-share
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
APIs. The export needs only Pillow and runs without browser automation.

See `VALIDATION.md` for the completed formula, layout and download checks.

