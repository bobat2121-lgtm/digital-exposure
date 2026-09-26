# Panel audit — September 25, 2026

Covers the three X panels: Monday "The Accretion Ledger", Wednesday "The Coupon
Sheet" and Friday "The Closing Mark". The deterministic part of this audit now
runs by itself. `scripts/audit_panels.py` recomputes every headline figure from
raw inputs and cross-checks it against the issuers' published KPIs. The
**Panel audit** GitHub Action runs it Monday, Wednesday and Friday and publishes
the results to the [`audit` branch](https://github.com/bobat2121-lgtm/digital-exposure/tree/audit):

- `checks.json` — every check with PASS / WARN / FAIL.
- `audit.json` — every displayed value with its source, plus the page footnotes.
- `monday.png`, `wednesday.png`, `friday.png` — the rendered panels.

The weekly ChatGPT task (`CHATGPT_AUDIT_TASK.md`) reads those files.

**Result on Sep 25, 2026: 85 PASS, 2 WARN, 0 FAIL**, both locally and on GitHub's
runners. The two WARNs are the MSTR and ASST earnings dates, which are still
Nasdaq estimates; the weekly task replaces them with confirmed dates.

### Second round (Sep 25, 2026): 92 PASS, 2 WARN, 0 FAIL

- **DEPLOYED is now BTC + DIVs.** Monday's waterfall reads down, one row per step,
  and ends in the week's bitcoin cost (BTC) and the rest (DIVs). Strategy's cost is
  the 8-K's aggregate purchase price; Strive's is its dashboard's purchase cost. For
  Sep 14–20, Strategy's $136.0m = $75.7m BTC + $60.3m DIVs. Its 8-K put dividends and
  interest at $57.4m; the gap is rounding in its $0.01B balances. New checks:
  `btc_cost`, `btc_divs` and `MSTR.divs_8k`.
- **Each issuer's own amplification.** MSTR shows strategy.com's `amplification`
  (BTC reserve ÷ net BTC reserve, 1.25×); ASST shows Strive's (notional preferred +
  debt) ÷ BTC value, written as 1 + the ratio (Strive's dashboard 50.5% → 1.51×).
  `MSTR.amp_model` checks that the 8-K model used for the weekly change stays within
  0.05× of strategy.com (1.27× vs 1.25×); `ASST.amp_dashboard` checks Strive's figure
  against its dashboard. (A brief interim version applied Strategy's formula to
  Strive, 1.61×; that is not Strive's measure and was reverted.)
- **Strategy's USD cover now has 12 weeks.** The filing feed started with the Aug 24
  8-K, so it held only four weeks of USD Reserve and USD Cash balances. The earlier
  weeks were transcribed from the 8-Ks into `data/strategy-weekly-8k.json`, each linked
  to its SEC filing: USD Reserve $2.55B on Jul 5, $5.10B plus $1.59B of USD Cash on
  Aug 23. New weeks arrive through the feed.
- **The spread charts cover 26 weeks** (`STRC.history`, `SATA.history`).
- **SATA's cut test reads "RATE CUT: Allowed/Blocked"**; the footnote gives the month's
  average and the cap and floor.
- **Calendar dates** sit centered in fixed-width chips.
- **The 8 failing export tests on main** were fixed: right-aligned text now measures
  its inked width, so a trailing glyph such as "y" no longer trips the clip check.
- **Filing worker.** The parser now also records `weekly_btc_cost_usd`,
  `btc_cost_basis_usd`, `btc_average_cost_usd` and `usd_reserve_dividends_interest_usd`.
  Deployed Sep 25 (version `dd589cb4`); the new facts start with the Sep 28 filings.
- **Extra data** from section 3 is on the web report; the X images leave it out.
  Test copies of the X images (`render_previews.py --extra`) still carry it; see PANELS.md.

### Third round (Sep 26, 2026): 96 PASS, 2 WARN, 0 FAIL

- **Blank Friday tiles now fail.** The scheduled run at 8:07 pm ET on Sep 25 drew "—" for MSTR and ASST
  price/NAV and left all four turnover tiles empty, yet reported 0 FAIL: turnover only warned, and price/NAV
  wasn't checked. The Friday balance inputs had failed to load, and `fetch_financial_inputs` swallowed the
  exception, so nothing said why.
  - `friday.live_inputs` now keeps the exception as `error` next to its notice.
  - New checks: `friday.inputs` (Monday balance inputs loaded for Friday: FAIL when unavailable, WARN on a
    saved edition, with the notice and error), and `MSTR.price_nav` / `ASST.price_nav` (drawn on the image).
    The four turnover checks now FAIL instead of WARN, with the reason.
  - `audit.json` records the Friday inputs' status, notice and error. The web report shows the notice when
    price/NAV couldn't load.
- The cause of the Sep 25 failure isn't known yet. The next occurrence records it in `checks.json`.

## 1. Does everything update automatically?

Yes, except the items in the last table below. Every source is fetched when a page
opens, is cached for 5–15 minutes, and falls back to a labeled saved snapshot if it
fails.

### Monday — The Accretion Ledger

| Input | Source | Refresh | If the source fails |
| --- | --- | --- | --- |
| BTC bought/held, ATM common and preferred, USD Reserve and cash, SATA shares, Strive cash and STRC held | capital-report Worker reading SEC 8-Ks, Mon 06:45–09:30 ET (Tue after an EDGAR holiday) | automatic | the last complete edition stays up |
| Strategy shares and preferred claims | `report/auto_reconcile.py`: last reviewed reconciliation + 8-K activity + Yahoo 10-close means + strategy.com STRC schedule | automatic | the week stays missing and the last edition stays up |
| Strive claims, cash, debt, reserve months | Strive dashboard API | automatic | saved snapshot, labeled |
| Strive common-capital VWAP | Yahoo 1-min (else 5-min) bars | automatic | the week stays missing |
| MSTR / ASST / BTC prices | `report.current_prices` | on page open | saved quotes, labeled |
| USD cover, coverage, break-even | strategy.com KPIs; Strive dashboard | automatic | saved snapshot |
| QTD / YTD baselines | automatic quarter rollover | automatic | last complete report |

### Wednesday — The Coupon Sheet

| Input | Source | Refresh | If the source fails |
| --- | --- | --- | --- |
| STRC/STRF/STRK/STRD/STRE prices, rates, effective yields, notional, record and pay dates | strategy.com KPIs (intraday) | automatic | saved snapshot |
| SATA price | Yahoo | automatic | saved snapshot |
| SATA stated rate and history | Strive `api/treasury` `dividendRate`; history = daily amount × the month's business days × 12 | automatic | saved snapshot |
| 3M bill, 2Y, 10Y | **Treasury daily par curve (same day)**, then FRED | automatic | FRED alone |
| SOFR, EFFR | **NY Fed API (next morning)**, then FRED | automatic | FRED alone |
| ICE BofA IG / HY yields | FRED (one-day lag) | automatic | saved snapshot |
| 12-week spread history | Yahoo closes + rate in effect each day + benchmark each day | automatic | "History unavailable" |
| USD cover timeline | 8-K reserve facts; Strive dashboard | automatic | "History unavailable" |
| Flow ledger | 8-K feed | automatic | last four complete weeks |
| Calendar | strategy.com dates, **Fed FOMC calendar**, **Nasdaq earnings estimate**, curated `data/calendar-events.json` | automatic; the curated file is weekly | estimates marked "est." |

### Friday — The Closing Mark

| Input | Source | Refresh | If the source fails |
| --- | --- | --- | --- |
| BTC 4 pm mark, weekly and daily closes, 200W/200D trends | `friday.live_inputs` (Yahoo) | automatic; rolls to the new week at 4:00 pm ET Friday | saved snapshot |
| MVRV, realized price, Puell with bands | Checkonchain | daily | saved snapshot |
| Supply in profit | Checkonchain, via the Friday package | daily | — |
| Fear & Greed | CoinMarketCap | daily | — |
| DXY, US 10Y | Yahoo | intraday | saved snapshot |
| Fed funds − 2Y | NY Fed EFFR and Treasury 2Y, then FRED | daily | FRED |
| Turnover | Yahoo volume ÷ shares from filings and KPIs | automatic | — |
| Price/NAV | Monday balances via `load_supplements` | automatic | — |

### Not automatic (all watched by the audit)

| Item | Why | Guard |
| --- | --- | --- |
| Strategy debt | Carried forward from the last reviewed reconciliation; strategy.com reports convertible notes only | FAIL when it moves >1% from strategy.com's debt (catches a new convertible or a conversion) |
| A new Strategy preferred series | The roll-forward knows STRC, STRF, STRK, STRD and STRE | FAIL when claims drift >5% from strategy.com's preferred notional |
| Reserve targets (12-month floor, 18-month goal), warrant terms, spread benchmark | Company policy, set in `data/preview-config.json` | Weekly task checks for policy changes; warrants hide themselves after Oct 13 |
| Confirmed earnings dates, STRC/SATA rate announcements | No reliable keyless feed | Weekly task edits `data/calendar-events.json` |

Two operational notes:

- **GitHub schedule pause.** GitHub disables scheduled workflows in public repositories
  after 60 days with no repository activity. The weekly task's commits keep the
  repository active. If they stop, re-enable the workflow under **Actions → Panel audit**.
- **Streamlit sleep.** Streamlit Community Cloud may put the app to sleep after a
  period without visits. The PNGs on the `audit` branch are produced independently
  of the app.

## 2. Formulas and calculations

Each figure below was recomputed independently from raw inputs. All passed.

- **Monday, both companies:**
  - Sats/share = BTC held ÷ effective common shares.
  - NAV/share = (BTC × price + cash − debt − preferred claims) ÷ shares.
  - Price/NAV.
  - Amplification = (debt + preferred claims) ÷ BTC value (ASST). MSTR shows
    strategy.com's KPI (second round).
  - Raised = common + preferred.
  - Cash change, and deployed = raised − cash change.
- **Monday cross-checks against strategy.com:**

  | Check | Result |
  | --- | --- |
  | BTC held | exact |
  | Shares vs market cap ÷ price | 0.00% gap |
  | USD cover months | exact |
  | Coverage years | 0.02% gap |
  | BTC break-even | 0.0004 pp gap |
  | Debt | 0.59% gap: $39.7m of non-convertible debt that strategy.com's figure excludes |
  | Amplification vs strategy.com's debt + pref ÷ BTC NAV | 0.3 pp gap: the panel uses liquidation claims, including accrued dividends and STRF's price floor; strategy.com uses notional |

- **Monday cross-checks against Strive's dashboard:**
  - Cash, debt, Class A + B shares and reserve months: exact.
  - STRC held: 0.1% gap (filing fair value vs dashboard mark).
  - BTC held: exact.
  - Deployed $111.6m vs BTC cost $107.7m. The remaining $3.9m is dividends and fees, as expected.
- **Wednesday:**
  - All six effective yields equal strategy.com's `effYield`, or rate ÷ price for SATA.
  - All ten spreads recompute exactly.
  - STRC 30-day dollar volume is within 0.2% of strategy.com's average.
  - The SATA rate matches Strive's stated rate (13.00%). No announced change is pending.
- **Friday:**
  - 50W SMA: exact.
  - Weekly RSI: exact, via an independent exponential form.
  - Zone matches its extension.
  - Tally matches its cells.
  - The week shown is the latest completed Friday.
  - MVRV is within 5% of mark ÷ realized price; the gap is timing, since Checkonchain uses its own daily close.

### Fixed in this audit

1. **3M bill, 2Y, 10Y, SOFR and Fed funds were 1–2 business days stale.** FRED
   republishes the Treasury and NY Fed series late. The panels now read the
   same-day Treasury curve and the NY Fed API first. On Sep 25 the bill moved from
   4.19% (FRED, Sep 23) to 4.24% (Treasury, Sep 24), a 5 bp change in both headline
   spreads.
2. **"INTO BTC" overstated bitcoin spending.** The waterfall's last bar is raised ±
   cash, which also pays dividends and fees. Strategy's $136.0m included the Sep 15
   STRC dividend. It is now labeled **DEPLOYED**. The 8-K's aggregate purchase price
   would split it exactly; see recommendation M1.
3. **The Coupon Sheet calendar lacked macro and earnings dates.** It now adds the
   next FOMC decision (parsed from the Fed's calendar) and earnings dates (curated
   confirmed dates, else Nasdaq's estimate marked "est.").
4. **SATA's rate conversion was wrong in some months.** SATA's monthly dividend is
   split evenly over the month's business days
   ([Strive 8-K, May 14, 2026](https://www.sec.gov/Archives/edgar/data/1920406/000162828026034802/asst-20260513.htm)).
   So the annual rate is the daily amount × that month's business days × 12, not
   × 252. July has 22 business days, so the old formula showed 12.42% instead of
   13.00%, and SATA's 12-week spread history had a false July dip of about 58 bp.
   - The current rate now comes from Strive's stated `dividendRate` (13.00%).
   - History uses the federal business-day calendar.
   - Two new checks confirm both against Strive.
5. **Audit hardening.** The independent audit script, the GitHub Action and
   fault-tolerant rendering (one failed source no longer blocks the other panels).
6. **Calendar content.** The calendar now shows the next seven coupon-relevant
   dates: pay dates, rate announcements, FOMC, earnings, votes and deadlines.
   Record dates and quarter-end were removed. The curated file is seeded with
   sourced events:
   - STRC's October rate announcement (Sep 30).
   - The Oct 28 STRC daily-dividend vote.
   - STRC's first daily payment if approved (Nov 2).
   - SATA's next rate announcement (est. Oct 15).

### Definitions to know

- **"Amplification" means different things now.**
  - Strive: (notional preferred + debt) ÷ BTC value, its "Bitcoin amplification
    ratio" ([Strive FWP, May 14, 2026](https://www.sec.gov/Archives/edgar/data/1920406/000095010326007179/dp246652_fwp.htm)).
    Strategy used the same ratio before July 23, 2026 (strategy.com `debtPrefByBN`).
  - On July 23, 2026 Strategy redefined its own "amplification" KPI as BTC
    Reserve ÷ Net Reserve, about 1.25×
    ([Strategy FWP, Aug 24, 2026](https://www.sec.gov/Archives/edgar/data/1050446/000119312526363557/d431748dfwp.htm)).
  - Since the second round, each card shows its issuer's own definition, both
    written in × (ASST 1 + Strive's 50.5% = 1.51×).
- **Strategy's USD cover and coverage include interest.** Its "dividends" in
  `usdMonthsOfDividends`, `totalYearsOfCoverage` and `btcBreakevenArr` are all
  annual interest + dividends ($1.62B). The footnotes now say so.
- **Strategy's mNAV** (price ÷ net BTC per fully diluted share, 1.20×) and the
  panel's price / basic NAV (1.19×) differ slightly by design.
- **SATA's rate-cut test** uses the average of daily closing prices over the prior
  dividend period (not VWAP), with a $99 threshold
  ([term sheet](https://www.sec.gov/Archives/edgar/data/1920406/000114036126001962/ny20063534x4_fwp.htm)).
  This matches the panel.

## 3. Data these sheets are missing

Ranked by importance to each sheet's theme. All sources are keyless.

### Monday — The Accretion Ledger (buying bitcoin and raising capital)

1. **Weekly BTC purchase cost and average price.** *Done in the second round*
   (BTC + DIVs). Strive: its dashboard's purchase cost. Strategy: the 8-K's aggregate
   purchase price, now extracted by the filing Worker (after its next deploy) and
   transcribed for Mar 1–Sep 20, 2026 in `data/strategy-weekly-8k.json`.
2. **Remaining ATM capacity (dry powder).** From the 8-K "Available for Issuance
   and Sale" table. As of Aug 30: MSTR $19.09B, STRC $17.51B. Worker extraction.
3. **Strategy's own KPIs.** mNAV (1.20×), BTC Gain YTD (`btcGainYTD`) and its new
   amplification (1.25×, *shown since the second round*), all from
   `api.strategy.com/btc/bitcoinKpis`, updated intraday.
4. **Average cost basis and unrealized gain.** Strategy: 846,000 BTC at $75,416
   average. Strive: dashboard `total_cost_basis`. *In the Monday test copy.*
5. **Remaining buyback authorization.** STRC: $875.1m left, from the 8-K.

### Wednesday — The Coupon Sheet (digital credit yields and spreads)

1. **Strategy's credit metrics**, which show what stands behind each coupon:
   BTC Floor $13,265 per series, from `api.strategy.com/btc/credit` (*BTC floor in
   the Wednesday test copy*). On Sep 25 the same endpoint returned 0 for BTC Rating
   and null for BTC Credit, so those two are not shown.
2. **Tax-equivalent yield** (return-of-capital treatment). STRC: 19.4%, from
   `taxEqvEffYield` in each series' KPI feed. Prominent in the issuers'
   marketing. *In the Wednesday test copy.*
3. **Strategy's "market credit" spread** (*in the Wednesday test copy*). STRC's yield minus a
   duration-matched Treasury (5.07%): 7.13%, from `marketCredit`. This is the
   credit-spread framing, next to the panel's carry-over-cash headline.
4. **Next announced rate.** STRC's rate is posted on the month's last business
   day; SATA's around mid-month. Partly covered by the calendar; a "next rate"
   line in each hero card would complete it.
5. **Implied volatility and credit rating.** STRC implied volatility is 10.2
   (`impliedVolatility`). S&P rates Strategy B− (assigned Oct 27, 2025).

### Friday — The Closing Mark (market regime at the Friday close)

1. **Spot BTC ETF net flows over 7 days:** `etfNetFlows7d` in `bitcoinKpis`. Not in
   the test copy: the API does not state its unit (BTC or $m), and strategy.com's
   page, which would, blocks automated reads.
2. **Futures basis and perpetual funding:**
   - 3-month basis: `futuresBasis3m`, 4.9% (*in the Friday test copy, computed from
     Deribit's quarterly future: 5.0% on Sep 25, matching strategy.com's rounded 5*).
   - Perpetual funding rates: OKX public API, every 8 hours.
3. **MSTR 30-day implied volatility:** Cboe delayed-quote JSON.
4. **BTC DVOL and options skew:** Deribit public API, real time. *DVOL is in the
   Friday test copy.*
5. **Stablecoin supply:** DefiLlama, daily. *In the Friday test copy.*

The web report shows these; the X images leave them out. Test copies of the X images
(`render_previews.py --extra`, published by the Panel audit Action) show them in the
image so you can judge them before anything changes on X.

## 4. Design pass

- **Neon Ledger cards:** 18 px radius, hairline borders, one rounded accent bar,
  and no corner brackets. The background grid is fainter, with a soft glow
  behind the title.
- **Monday rhythm:** no divider lines inside the cards. Every section sits on a
  shared grid, so both columns align. The coverage and growth sections are
  matching tinted modules. The canvas is trimmed to 1440 × 1760.
- **Coupon Sheet:** extra room at the bottom of the hero cards, a wider calendar,
  and slimmer date pills. The flow ledger's rows are tighter and its columns stay
  centered.
- **Type:** every panel still passes the 28-px phone minimum in every style and
  layout (enforced by the tests).

