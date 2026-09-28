# Monday, Wednesday and Friday panels

The public app opens on three tabs, one report per posting day. Each tab has two
forms built from the same data:

- **The web report** fills the tab. It is laid out for reading on a computer and
  reflows for a phone, and carries more than the X image: every hero figure as a
  tile, the charts with hover values, and full tables.
- **The X image** is the phone-first PNG for posting on X. **Download X image**
  draws and saves it at the click, with prices as of that moment; **Preview X image**
  draws it in a dialog.

At the bottom of every tab, two collapsed sections list **Formulas** (every figure's
definition) and **Sources, notes and audit values**; the X image download and preview
come last. Only the open tab builds, and **Refresh data** re-fetches everything.

**Speed.** The data sources refresh in the background (`panels/live.py`): each keeps its
latest good copy, a view gets it at once, and a copy past its time (15 minutes; prices
and the filing feed 2 minutes) refreshes behind the scenes, so no view waits on a slow
provider. Only the first view after a restart waits (at most about 12 seconds, then the
saved snapshot, marked stale). FRED gets 8 seconds and falls back series by series: the
Treasury curve and the New York Fed fill in the bill, 2Y, 10Y, SOFR and fed funds, and
only the ICE BofA IG and HY yields stay on the snapshot. The X image is drawn only when
downloaded or previewed. `app.py` re-imports the app's modules when a deploy changes
them, because Streamlit's own watcher only reloads sessions that were open at the time.

**Prices** (`report/current_prices.py`). Before the open on a NYSE trading day (4:00 am
ET to the open), MSTR and ASST take their latest pre-market trade (Yahoo 1-minute bars
with extended hours, free); in the session every stock is live; otherwise (evenings,
weekends, holidays) the close. A stock with no pre-market trade yet keeps its close.
Preferreds never use pre-market prices. The Monday image stamps the price time under the
handle ("Pre-market 8:11 AM ET · Mon Sep 28", or "Close · Fri Sep 25"), and each company
card on the web shows its own.

| Day | Title | X image size | Posting time |
| --- | --- | --- | --- |
| Monday | The **Accretion** Ledger | 1440 × 1884 | after both 8-Ks |
| Wednesday | The **Coupon** Sheet | 1440 × 1920 (3:4) | midday, intraday prices (X Control Panel from 12:31 pm ET) |
| Friday | The **Closing** Mark | 1440 × 1920 (3:4) | Friday 4:00 pm ET mark |

The page has two styles, switched at the top: **Bloomberg** (the default) and
**Broadsheet**. The three day tabs sit under the switch, so every report comes in
both styles, and the web report and the X image change together. There is one
Monday funding layout (the waterfall). Links:

- `?style=bloomberg|broadsheet` picks the style and `?report=monday|wednesday|friday`
  opens a tab, e.g.
  <https://digital-credit-report.streamlit.app/?style=broadsheet&report=wednesday>.
  The address follows the switch, so a copied link opens the same view.
- `?classic=1` opens the detailed Monday and Friday reports, which are unchanged.
- The retired `?theme=`, `?layout=` and `?extra=` options are dropped from the
  address when a link still carries them. An unknown `?style=` opens Bloomberg.

## The web report

`panels/web.py` builds each tab from Streamlit elements, HTML tables and Altair
charts. Each style is a `Look` (colors and fonts) set per browser session through
a context variable, so two readers on different styles never share one:

- **Bloomberg:** a blue command bar with the date, amber data on black, square
  cards with a blue top strip, the title's key word as a reversed amber field.
  Inconsolata text, IBM Plex Mono titles.
- **Broadsheet:** newsprint paper, a blackletter masthead with the edition line
  over a double rule, sections under a heavy rule and hairline, hairline column
  rules. Archivo text, Playfair Display titles, UnifrakturMaguntia masthead.

Both keep the X image's company colors (Strategy orange, Strive gold, deepened on
paper), gains green with "+" and losses red with "−". The fonts are served from
`static/` (Streamlit static serving, `.streamlit/config.toml`), so no font request
leaves the app.

- **Computer:** cards sit side by side (Strategy next to Strive, STRC next to SATA)
  and the tables show every column.
- **Phone (640 px or narrower):** cards stack, tiles wrap to the screen width, text columns
  wrap while numbers stay on one line, and wide tables scroll sideways inside
  their card, never the page.
- **More than the X image:** Monday adds the 8-K link and filing detail per company;
  Wednesday adds the backing tiles (BTC floor, stated rate, prior month's average
  close), all six preferreds against every benchmark, and 30-day dollar volume;
  Friday adds the markets tiles (DVOL, 3-month basis, stablecoins) and turnover as
  small multiples.
- **Friday's BTC chart** on the web shows the last four years (`BTC_YEARS` in
  `panels/web.py`) on a log axis with $10k–$200k style steps; the 200W and 50W SMAs
  still come from the full price history. The X image's chart is unchanged.

## The X image: built for phones

X shows single images up to 3:4 uncropped in the mobile timeline. Taller images
are center-cropped. Tapping an image shows it at the phone's width, about 390 CSS
px, which is 0.27× of a 1440-px panel. So every panel follows these rules:

- **Size.** The panel is 1440 px wide and no taller than 3:4.
- **Type.** No text is smaller than 28 px (about 7.6 CSS px on a phone). Key
  figures are 44–92 px (`panels/draw.py`, `T_*`). The canvas flags any smaller text
  as an overflow, and the tests require zero overflows in every style and layout.
- **Signed.** Bloomberg and Broadsheet put the X handle **@WallyXIX** at the top
  right, on the title's line under the report line's right end (`HANDLE` in
  `panels/trial_styles.py`). A title long enough to reach it counts as an overflow.
- **Aligned type.** A text line's y is the top of its capitals, so lines of one size
  share a baseline whatever letters they hold, and a hero figure is centered by its
  capitals in the space between its label and the next row.
- **No footnotes in the image.** Methods, sources and definitions appear in the
  Formulas and Sources sections of the web page and in `audit.json`, never in the
  downloaded PNG.

## Styles

The page offers Bloomberg (`terminal`, the default) and Broadsheet (`broadsheet`). The
default is also what `render_previews.py` writes as `monday.png`, `wednesday.png` and
`friday.png`, so the Panel audit Action and anything else that reads those files gets
Bloomberg. The other looks remain in the renderer for `render_previews.py --themes` and
are not offered on the page. Every style draws the same numbers. Only the palette, type
and decoration change.

| Style | Look | Type (SIL OFL, in `assets/`) |
| --- | --- | --- |
| **Bloomberg** (`terminal`, default) | Bloomberg Terminal: amber data on black, a blue command bar ("DCR <GO>"), the title's key word as a reversed amber field, square cards with a blue top strip, blue section rules, a dotted zero line on Monday's waterfall | Inconsolata at 90% width (monospace that fits the phone layout), IBM Plex Mono Bold |
| **Broadsheet** (`broadsheet`) | Newsprint: a blackletter masthead with the edition line over a double rule, a Playfair Display headline, sections marked by a heavy rule over a hairline with a company-color flag, hairline column rules in the gutters | Archivo, Playfair Display, UnifrakturMaguntia |
| **Neon Ledger** (`neon`) | Cyberpunk trading terminal kept professional. Deep navy, faint grid, glowing key word. One neon per day. Strategy cyan, Strive magenta | Chakra Petch, Orbitron |
| **Classic** (`classic`) | The house style: Lato, a Gelasio serif key word, orange dot | Lato, Gelasio |
| **Brutal Orbit** (`orbit`) | Brutalism meets deep space. Concrete paper, 4 px black rules, square corners, hard offset shadows, a starfield header with an orbiting planet | Space Grotesk, Space Mono |

Bloomberg and Broadsheet use Joi's company colors (Strategy orange, Strive gold; deepened
on paper so the two stay apart for colorblind readers). Gains stay green and losses red in
both. They draw their own report line through `themes.kicker` and their inset boxes through
`themes.inset`, which leave every other look unchanged.

**Trial looks (not live).** Four looks that push Neon Ledger further are under review for
the X images: Aurora Glass (`glass`), Chamfer HUD (`hud`), Signal Glitch (`glitch`) and
Circuit Trace (`circuit`). They keep the layouts, numbers, type floor and company colors;
only surfaces, cards, titles and light change (`panels/trial_styles.py`, display faces
Unbounded, Tektur and Michroma under SIL OFL in `assets/`). Render them with
`render_previews.py --themes glass,hud,glitch,circuit`. Chamfer HUD also comes in six colorways (`hud-nightcity`, `hud-tron`,
`hud-laserline`, `hud-bladerunner`, `hud-synthwave`, `hud-tokyo`, from 2 colors to 5+);
every one keeps gains green (#3DFF9A) and losses red (#FF3B47). Blade Runner has four
further variants with company colors outside blue and pink: `br-vegas` (orange × violet),
`br-tyrell` (gold × deep violet), `br-joi` (orange × gold) and `br-rain` (lavender × lemon).

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
.venv\Scripts\python scripts\render_previews.py --out previews --themes terminal,broadsheet
.venv\Scripts\python scripts\render_previews.py --out previews --offline   # saved inputs, demo Friday week
```

These commands write `monday.png`, `wednesday.png`, `friday.png` (Bloomberg) and
`audit.json`. Other styles are written as `monday-broadsheet.png` and so on. The page
names its downloads by style: `monday-bloomberg.png`, `monday-broadsheet.png`.

## What each panel shows

### Monday — The Accretion Ledger

Each company card follows the business: bitcoin bought, then how it was funded,
then what it did per share.

- **Header:** the company's official wordmark as its name (`assets/strategy.*`,
  `assets/strive.*`; white on dark cards, Strive's orange bar kept), price, price/NAV
  and the balance date.
- **Bitcoin bought and held.**
- **The funding block.** The page and the X image use the waterfall. Layouts A and
  B remain in the renderer only (`panels/monday_preview.py`):
  - **C · Waterfall** (default, the main format), read top to bottom, one row per
    step: COMMON + PREF, plus cash drawn (FROM CASH) or minus cash kept (TO CASH),
    then where it went: **BTC** (the week's bitcoin purchase cost, fees included)
    and **DIVs** (the rest: preferred dividends, interest and fees).
    - Strategy's BTC cost is the 8-K's "Aggregate Purchase Price" (filing feed,
      else `data/strategy-weekly-8k.json`). Strive's is its dashboard's purchase
      cost for the same dates. If neither exists, BTC bought × the week's average
      close is used and the audit flags it.
    - When Strategy's 8-K states its dividends and interest (Sep 14–20: $57.4m),
      the footnote shows it. DIVs can differ by a few million because the 8-K
      rounds balances to $0.01B.
  - **B · Ledger:** common ATM + preferred ATM = raised, as a short statement, with
    cash below.
  - **A · Headline:** common ATM and preferred ATM as two large tiles, then one
    cash line.

  In every layout, cash is a balance and is never counted as a raise. The cash box
  shows its makeup: Strategy's "$5.04B reserve + $1.05B USD cash", and Strive's
  "$229.6m cash + $49.7m STRC" (the STRC it holds).
- **Per share:** BTC/share, NAV/share, amplification and shares, each with its
  weekly change. Amplification uses each issuer's own formula, shown in ×:
  - Strategy: BTC reserve ÷ net BTC reserve (BTC + USD − debt − preferred),
    strategy.com's `amplification` KPI since Jul 23, 2026 (about 1.25×).
  - Strive: 1 + (debt + SATA notional) ÷ BTC value. The ratio is the "Amplification
    Ratio" on Strive's treasury dashboard, shown as 1 + that ratio in ×. The audit
    checks the ratio against Strive's dashboard figure.

  The two measure different things and are not comparable.

  Strive's PIPE warrant tag (25.8M @ $27, due Oct 13) disappears after the deadline.
- **Coverage against each issuer's own target** (each cell's text is centered, with a
  short note: "of dividends", "BTC gain / yr"):
  - Strategy's USD cover as a multiple of its 12-month floor.
  - Strive's as "at 18-mo goal".
  - Total coverage in years and BTC break-even.
- **Bitcoin cost:** average cost per BTC, the BTC price vs that cost, and the cost
  basis (Strategy's 8-K; Strive's dashboard).
- **Growth on one shared window.** The "N WK" column uses the same number of weekly
  filings for both companies. QTD and YTD restart automatically at each quarter.

### Wednesday — The Coupon Sheet

Posted midday on purpose, so the image reads **INTRADAY** with that day's preferred
prices (after 4:00 pm ET it reads CLOSE). The benchmarks post after the close (SOFR, IG
and HY a day later), so at midday they are the prior day's; the page footnote dates each one.

STRC and SATA carry the two treasuries, so they are the heroes. Each gets a card with:

- the spread over the 3-month bill, in basis points, as the headline;
- effective yield;
- a spread stack over SOFR, the 3-month bill, the 10-year, ICE BofA IG and HY;
- 26 weeks of spread history, using each day's close, stated rate and 3-month bill;
- the same row for both: closes at or above $100 (last 20 sessions), 30-day volume
  and size. SATA's rate-cut test is in the page footnote: Strive may lower SATA's
  rate only if its closes over the prior month averaged at least $99, by at most
  0.25 pp plus any fall in SOFR, and never below 1-month term SOFR (SATA pricing term
  sheet, Jan 22, 2026).
- the issuer's USD cover against its own target, as a 12-week bar timeline with the
  target line. Strive sits on its 18-month goal every week. Strategy's weeks come from
  its 8-K balances: the filing feed, and before it `data/strategy-weekly-8k.json`
  (USD Cash began Aug 23, 2026; earlier weeks are the USD Reserve alone).

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
- **The calendar** (next seven dates, in order; each date centered in a fixed-width
  chip), assembled from:
  - Strategy's pay dates.
  - The warrant deadline.
  - The next FOMC decision, from the Fed's calendar.
  - Earnings dates, only once confirmed: a confirmed entry in `data/calendar-events.json`,
    or Nasdaq's date after the company announces it. Estimates are never shown.
  - Any other curated events. The weekly audit task maintains the curated file.
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

## Extra data: on the web report, test copies of the X image

The web report always shows this extra data. The X images leave it out to stay
succinct. `render_previews.py --extra` (and the Panel audit Action) still draws test
copies of the Wednesday and Friday X images with it (`wednesday-extra.png`,
`friday-extra.png`); they stay 1440 wide and within 3:4, with no text under 28 px.
(Monday's bitcoin cost box, first tried here, is now part of the regular panel.)

- **Wednesday:** a backing row in each hero card, the same for STRC and SATA: BTC
  floor, stated rate and the prior month's average close. BTC floor = (debt +
  preferred notional senior to and including the series − USD cash) ÷ BTC held.
  strategy.com publishes STRC's; SATA's uses the same formula.
- **Friday:** a markets band: BTC implied volatility (Deribit DVOL), the 3-month
  futures basis (Deribit, annualized) and stablecoin supply (DefiLlama), each with
  its 7-day change. The checklist and BTC chart are shorter to make room.

## Data (no API keys)

`panels/extras.py` fetches each source independently. A failed section falls back to
`data/preview-extras.json` and the panel lists it as a saved snapshot. Refresh that
file with `scripts/render_previews.py --save-extras`.

| Source | Used for |
| --- | --- |
| api.strategy.com `bitcoinKpis`, `mstrKpiData`, `{strc,strf,strk,strd,stre}KpiData` | USD months of dividends, annual dividends, preferred prices, rates and rate history, effective yields, notional, record/pay dates |
| strive.com `treasury/api/dashboard/base-data`, `api/treasury` | dividend reserve months, SATA stated rate and dividend history (daily amount × the month's business days × 12), cash, shares |
| fred.stlouisfed.org `fredgraph.csv` | DGS10, DGS2, DGS3MO, DFF, SOFR, BAMLH0A0HYM2EY, BAMLC0A0CMEY |
| Yahoo chart API | preferred prices/volume, DX-Y.NYB, ^TNX, PFF, HYG, BTC-USD volume |
| Checkonchain public charts | MVRV with mean/±sd, realized price, Puell Multiple with bands |
| Monday filing feed (Cloudflare Worker) and committed checkpoint | issuance, buybacks, USD reserve/cash, BTC purchase cost and cost basis, SATA shares, warrants |
| `data/strategy-weekly-8k.json` (transcribed from SEC EDGAR, each week linked) | Strategy's weekly BTC cost, USD Reserve/Cash and cost basis from Mar 1, 2026, before the feed carried them |
| Deribit public API, DefiLlama (web report and test copies) | DVOL, 3-month futures basis, stablecoin supply |

Rates come from the same-day official sources first:

- **Treasury daily par yield curve:** 3M, 2Y and 10Y.
- **NY Fed API:** SOFR and EFFR.

FRED fills in history and serves as the fallback.

## Audit

`scripts/audit_panels.py` recomputes every headline figure and cross-checks it
against strategy.com and Strive's dashboard. The **Panel audit** GitHub Action
(`.github/workflows/panel-audit.yml`) runs it Monday, Wednesday and Friday. It
publishes `checks.json`, `audit.json` and the PNGs to the `audit` branch for the
weekly ChatGPT task (`CHATGPT_AUDIT_TASK.md`). Findings and the auto-update map
are in `PANEL_AUDIT.md`.

`data/preview-config.json` holds, each with a source:

- the dated warrant terms;
- Strategy's 12-month reserve floor;
- Strive's 18-month reserve goal.
