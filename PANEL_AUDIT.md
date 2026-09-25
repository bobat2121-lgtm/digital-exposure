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
  - Amplification = (debt + preferred claims) ÷ BTC value.
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
  - The panel uses (debt + preferred claims) ÷ BTC value. That is Strive's
    current definition (its dashboard's "Amplification Ratio") and Strategy's
    definition before July 23, 2026 (strategy.com field `debtPrefByBN`, 29.3%).
  - On July 23, 2026 Strategy redefined its own "amplification" KPI as BTC
    Reserve ÷ Net Reserve, about 1.25×
    ([Strategy FWP, Aug 24, 2026](https://www.sec.gov/Archives/edgar/data/1050446/000119312526363557/d431748dfwp.htm)).
  - The panel keeps one formula for both companies and states it in the page
    footnote. Readers who know Strategy's new KPI may expect 1.25× for MSTR.
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

1. **Weekly BTC purchase cost and average price.** This splits DEPLOYED into
   bitcoin vs. dividends and fees. For example, Strategy bought 950 BTC for
   $75.7m, so the other $60m of its $136m was dividends and fees.
   - Strive: `strive.com/api/treasury` `latestPurchase` (available now).
   - Strategy: the 8-K's aggregate purchase price. This needs the capital-report
     Worker to extract it, because SEC rejects anonymous requests from this app.
2. **Remaining ATM capacity (dry powder).** From the 8-K "Available for Issuance
   and Sale" table. As of Aug 30: MSTR $19.09B, STRC $17.51B. Worker extraction.
3. **Strategy's own KPIs.** mNAV (1.20×), BTC Gain YTD (`btcGainYTD`) and its new
   amplification (1.25×), all from `api.strategy.com/btc/bitcoinKpis`, updated
   intraday.
4. **Average cost basis and unrealized gain.** Strategy: 846,000 BTC at $75,416
   average. Strive: dashboard `total_cost_basis`.
5. **Remaining buyback authorization.** STRC: $875.1m left, from the 8-K.

### Wednesday — The Coupon Sheet (digital credit yields and spreads)

1. **Strategy's credit metrics**, which show what stands behind each coupon:
   BTC Rating 6.3×, BTC Credit 50 bp and BTC Floor $13,265 per series, from
   `api.strategy.com/btc/credit`.
2. **Tax-equivalent yield** (return-of-capital treatment). STRC: 19.4%, from
   `taxEqvEffYield` in each series' KPI feed. Prominent in the issuers'
   marketing.
3. **Strategy's "market credit" spread.** STRC's yield minus a
   duration-matched Treasury (5.07%): 7.13%, from `marketCredit`. This is the
   credit-spread framing, next to the panel's carry-over-cash headline.
4. **Next announced rate.** STRC's rate is posted on the month's last business
   day; SATA's around mid-month. Partly covered by the calendar; a "next rate"
   line in each hero card would complete it.
5. **Implied volatility and credit rating.** STRC implied volatility is 10.2
   (`impliedVolatility`). S&P rates Strategy B− (assigned Oct 27, 2025).

### Friday — The Closing Mark (market regime at the Friday close)

1. **Spot BTC ETF net flows over 7 days:** `etfNetFlows7d` in `bitcoinKpis`.
2. **Futures basis and perpetual funding:**
   - 3-month basis: `futuresBasis3m`, 4.9%.
   - Perpetual funding rates: OKX public API, every 8 hours.
3. **MSTR 30-day implied volatility:** Cboe delayed-quote JSON.
4. **BTC DVOL and options skew:** Deribit public API, real time.
5. **Stablecoin supply:** DefiLlama, daily.

Items 1–2 fit the macro strip. Adding them means trading space with the phone
layout, so each is a design choice for you to make, not a fix.

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

