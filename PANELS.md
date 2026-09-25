# Monday, Wednesday and Friday panels

The public app opens on three tabs, one panel per posting day. Each tab fetches
fresh data when a browser session opens it, and offers **Refresh data**, a PNG
download, the footnotes and an **Audit values** list. Only the open tab builds.

| Day | Title | Size | Posting time |
| --- | --- | --- | --- |
| Monday | The **Accretion** Ledger | 1440 × 1800 (4:5) | after both 8-Ks |
| Wednesday | The **Coupon** Sheet | 1440 × 1920 (3:4) | after the 4:00 pm ET close |
| Friday | The **Closing** Mark | 1440 × 1920 (3:4) | Friday 4:00 pm ET mark |

Links:

- `?report=monday|wednesday|friday` opens a tab.
- `?theme=neon|classic|orbit` picks a style. Neon Ledger is the default.
- `?layout=a|b|c` picks Monday's funding block.
- `?classic=1` opens the detailed Monday and Friday reports, which are unchanged.

## Built for phones

X shows single images up to 3:4 uncropped in the mobile timeline. Taller images
are center-cropped. Tapping an image shows it at the phone's width, about 390 CSS
px, which is 0.27× of a 1440-px panel. So every panel follows these rules:

- **Size.** The panel is 1440 px wide and no taller than 3:4.
- **Type.** No text is smaller than 28 px (about 7.6 CSS px on a phone). Key
  figures are 44–92 px (`panels/draw.py`, `T_*`). The canvas flags any smaller text
  as an overflow, and the tests require zero overflows in every style and layout.
- **No footnotes in the image.** Methods, sources and definitions appear under the
  image on the web page and in `audit.json`, never in the downloaded PNG.

## Styles

All three styles draw the same numbers. Only the palette, type and decoration change.

| Style | Look | Type (SIL OFL, in `assets/`) |
| --- | --- | --- |
| **Neon Ledger** (`neon`, default) | Cyberpunk trading terminal kept professional. Deep navy, faint grid, HUD corner brackets, glowing key word. One neon per day: cyan Monday, magenta Wednesday, amber Friday. Company colors hold on every sheet: Strategy cyan, Strive magenta | Chakra Petch, Orbitron |
| **Classic** (`classic`) | The house style: Lato, a Gelasio serif key word, orange dot | Lato, Gelasio |
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

Each company card follows the business: bitcoin bought, then how it was funded,
then what it did per share.

- **Header:** price, price/NAV and the balance date.
- **Bitcoin bought and held.**
- **The funding block, in three layouts** (page selector, `?layout=`):
  - **A · Headline:** common ATM and preferred ATM as two large tiles, then one
    cash line.
  - **B · Ledger** (default): common ATM + preferred ATM = raised, as a short
    statement, with cash below.
  - **C · Waterfall:** a waterfall of common + preferred + cash = into BTC.

  In every layout, cash is a balance ("drew $310.0m · $6.09B on hand") and is never
  counted as a raise.
- **Per share:** BTC/share, NAV/share, amplification ((debt + preferred) ÷ BTC
  value) and shares, each with its weekly change. Strive's PIPE warrant tag (25.8M @
  $27, due Oct 13) disappears after the deadline.
- **Coverage against each issuer's own target:**
  - Strategy's USD cover as a multiple of its 12-month floor.
  - Strive's as "at 18-mo goal".
  - Total coverage in years and BTC break-even.
- **Growth on one shared window.** The "N WK" column uses the same number of weekly
  filings for both companies. QTD and YTD restart automatically at each quarter.

### Wednesday — The Coupon Sheet

STRC and SATA carry the two treasuries, so they are the heroes. Each gets a card with:

- the spread over the 3-month bill, in basis points, as the headline;
- effective yield;
- a spread stack over SOFR, the 3-month bill, the 10-year, ICE BofA IG and HY;
- 12 weeks of spread history, using each day's close, stated rate and 3-month bill;
- closes at or above $100, 30-day volume and size. For SATA the first cell is instead
  its rate-cut test: the prospectus allows a cut only if the prior month averaged at
  least $99.
- the issuer's USD cover against its own target, as a 12-week bar timeline with the
  target line. Strive sits on its 18-month goal every week; Strategy stays far above
  its 12-month floor.

**Why the 3-month bill.** Jeff Walton, Strive's Chief Risk Officer, calls digital
credit a "moderate duration" instrument. Some examples:

- [tnorth.com, Mar 25, 2026](https://tnorth.com/digital-credit/thesis/): "a
  moderate-duration capital instrument".
- [X, Mar 11, 2026](https://x.com/PunterJeff/status/2031706638759932054):
  "+$3.9 Million per year vs T-Bills".
- [Strive update, May 14, 2026](https://www.sec.gov/Archives/edgar/data/1920406/000095010326007179/dp246652_fwp.htm):
  "A three-month T-Bill".

Strategy's own sources point the same way:

- It defines its risk-free rate as the 3-month Treasury yield.
- Its STRC briefing compares STRC against 0–3 month bills (SGOV).
- Saylor benchmarks STRC to the one-month Treasury.

Both securities reset their rate monthly around $100 par, so their rate duration is
about a month. The 2-year note would add term premium a holder is not exposed to.
The "moderate duration" is credit exposure, and the IG and HY spreads cover that.
Switch the headline in `data/preview-config.json` (`spread_benchmark`) if needed.

The rest of the panel:

- **The rest of the ladder** (STRF, STRK, STRD, STRE): price, effective yield, and
  spread over the bill and over HY.
- **The calendar:** record and pay dates, the warrant deadline and quarter end.
- **The four-week flow ledger**, with centered columns.

### Friday — The Closing Mark

Every reading is taken at the Friday 4:00 pm ET mark; none needs a Sunday close.

- **Tiles:**
  - BTC with its weekly change and 200W zone.
  - MSTR and ASST price/NAV with the weekly change, NAV/share and distance from
    the 200-day SMA.
- **The macro strip:** DXY, the 10-year, and Fed funds − 2-year. Each chart is
  marked with its high/low values, start and end dates, and a labeled reference
  line (DXY 101).
- **The cycle checklist:** one reading per line, each with the level that decides its
  state, and a Bull/Neutral/Bear tally.
- **BTC chart:** the 200W SMA zones with the 50W, 20W, 21W EMA and realized price.
  The zones are named Very Cheap, Cheap, Fair Value, Expensive and Very Expensive.
- **Weekly turnover** for MSTR, ASST, STRC and SATA (12-week bars), and Fear & Greed.

The supply-in-profit, Fear & Greed and 200-day charts appear as their headline
numbers; full history stays in the detailed Friday report (`?classic=1`).

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
