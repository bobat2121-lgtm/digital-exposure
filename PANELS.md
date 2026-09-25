# Monday, Wednesday and Friday panels

The public app opens on three tabs, one panel per posting day. Each tab fetches
fresh data when a browser session opens it, and offers **Refresh data**, a PNG
download and an **Audit values** list. Only the open tab builds.

| Day | Title | Classic paper | Size | Posting time |
| --- | --- | --- | --- | --- |
| Monday | The **Accretion** Ledger. | cream | 1800 × 1400 | after both 8-Ks |
| Wednesday | The **Coupon** Sheet. | certificate celadon, double-rule frame | 1800 × 1400 | after the 4:00 pm ET close |
| Friday | The **Closing** Mark. | black | 1800 × 1800 | Friday 4:00 pm ET mark |

Links:

- `?report=monday|wednesday|friday` opens a tab.
- `?theme=classic|neon|orbit` picks a style.
- `?classic=1` opens the detailed Monday and Friday reports, which are unchanged.

## Styles

All three styles draw the same numbers. Only the palette, type and decoration change.

| Style | Look | Type (SIL OFL, in `assets/`) |
| --- | --- | --- |
| **Classic** (default) | The house style: Lato, a Gelasio serif key word, orange dot | Lato, Gelasio |
| **Neon Ledger** (`neon`) | Cyberpunk trading terminal kept professional. Deep navy, faint grid, HUD corner brackets, glowing key word. One neon per day: cyan Monday, magenta Wednesday, amber Friday | Chakra Petch, Orbitron |
| **Brutal Orbit** (`orbit`) | Brutalism meets deep space. Concrete paper, 4 px black rules, square corners, hard offset shadows, a starfield header with an orbiting planet. The key word sits knocked out of a safety-orange slab | Space Grotesk, Space Mono |

Themes live in `panels/themes.py`. Fonts are switched per render through a context
variable (`panels.draw.fontset`), so concurrent sessions never share a style.

## Run locally

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

Without Streamlit:

```powershell
.venv\Scripts\python scripts\render_previews.py --out previews
.venv\Scripts\python scripts\render_previews.py --out previews --themes classic,neon,orbit
.venv\Scripts\python scripts\render_previews.py --out previews --offline   # saved inputs, demo Friday week
```

These commands write `monday.png`, `wednesday.png`, `friday.png` and `audit.json`.
Non-classic styles are written as `monday-neon.png` and so on.

## What each panel shows

### Monday — The Accretion Ledger

- **Capital raised** through the two ATMs, common and preferred, each with its
  share and price detail.
- **Cash on hand**, in a separate tinted box labeled "a balance, not new capital":
  Strategy's USD Reserve + USD Cash, and Strive's cash + held STRC. It shows the
  weekly draw or addition.
- **The funding bridge** in chips: `RAISED (ATM) + FROM CASH = DEPLOYED`, deployed
  into the week's BTC and other uses. Cash is never counted as a raise.
- Shares, and Strive's PIPE warrant flag (25.8m @ $27, deadline 5:00 pm ET Oct 13).
  The flag disappears after the deadline.
- BTC/share, NAV/share and debt + preferred ÷ BTC, with weekly change.
- **Coverage against each issuer's own target**:
  - Strategy's USD cover as a multiple of its 12-month floor.
  - Strive's as "at its 18-month goal".
  - Total coverage in years and BTC break-even.
- **Growth on one shared window.** The "N WK" column uses the same number of weekly
  filings for both companies. QTD and YTD restart automatically at each quarter.

### Wednesday — The Coupon Sheet

STRC and SATA carry the two treasuries, so they are the heroes. Each gets a card with:

- the spread over the 3-month bill, in basis points, as the headline;
- effective yield;
- a spread stack over SOFR, the 3-month bill, the 10-year, ICE BofA IG and HY;
- 12 weeks of spread history, using each day's close, stated rate and 3-month bill;
- par, 30-day ADV, turnover, amount outstanding and the rate rule. SATA may cut its
  rate only if the prior month averaged at least $99.

The rest of the panel:

- **The rest of the ladder** (STRF, STRK, STRD, STRE) as a compact table: price,
  stated and effective yield, spread over the bill and over HY, outstanding.
- **USD cover vs each issuer's own target**, as a 12-week timeline with the target
  line. Strive sits on its 18-month goal every week. Strategy stays far above its
  12-month floor.
- The four-week flow ledger and the dated calendar.

### Friday — The Closing Mark

Every reading is taken at the Friday 4:00 pm ET mark; none needs a Sunday close.

- Named 200W zones:
  - Very Cheap
  - Cheap
  - Fair Value
  - Expensive
  - Very Expensive
- 50W SMA, 20W SMA / 21W EMA band and realized price.
- The seven-cell cycle checklist, each cell printing its rule (below).
- Turnover, the STRC buyback share of volume, Fear & Greed regime and the macro
  strip (DXY, the 10-year, Fed funds − 2-year).

#### Cycle checklist rules

Every cell is BULL, BEAR or NEUTRAL by a fixed rule on the latest reading. The
headline counts the cells in each state. These are rule-based states, not forecasts.

| Cell | BULL | BEAR | NEUTRAL |
| --- | --- | --- | --- |
| 50W SMA | Friday 4 pm BTC mark above the 50-week SMA of Friday closes | at or below it | — |
| 20W / 21W band | mark above both the 20W SMA and 21W EMA | below both | inside the band |
| 50D / 200D | 50-day SMA above the 200-day (golden cross) | below (death cross) | history too short |
| Weekly RSI | RSI(14) on Friday closes ≥ 50 | < 50 | — |
| MVRV | below 1.0 (price under realized price) | above its mean + 1 standard deviation | otherwise |
| Puell Multiple | below the low band (mean − 0.85 sd, about 0.38) | above the high band (mean + 1.25 sd, about 3.16) | otherwise |
| Supply in profit | below 50% | above 95% | otherwise |

## Data (no API keys)

`panels/extras.py` fetches each source independently. A failed section falls back to
`data/preview-extras.json` and the panel lists it as a saved snapshot. Refresh that
file with `scripts/render_previews.py --save-extras`.

| Source | Used for |
| --- | --- |
| api.strategy.com `bitcoinKpis`, `mstrKpiData`, `{strc,strf,strk,strd,stre}KpiData` | USD months of dividends, annual dividends, preferred prices, rates and rate history, effective yields, notional, record/pay dates |
| strive.com `treasury/api/dashboard/base-data` | dividend reserve months, SATA dividend history (rate = daily × 252, monthly × 12), cash, shares |
| fred.stlouisfed.org `fredgraph.csv` | DGS10, DGS2, DGS3MO, DFF, SOFR, BAMLH0A0HYM2EY, BAMLC0A0CMEY |
| Yahoo chart API | preferred prices/volume, DX-Y.NYB, ^TNX, PFF, HYG, BTC-USD volume |
| Checkonchain public charts | MVRV with mean/±sd, realized price, Puell Multiple with bands |
| Monday filing feed (Cloudflare Worker) and committed checkpoint | issuance, buybacks, USD reserve/cash, SATA shares, warrants |

`data/preview-config.json` holds, each with a source:

- the dated warrant terms;
- Strategy's 12-month reserve floor;
- Strive's 18-month reserve goal.
