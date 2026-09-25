# Panel redesign previews

Three panels share one family: Lato type, the Imprint title style (Lato bookends,
a serif key word, orange dot), rounded cards and the orange accent. Each day has
its own paper so the edition is recognizable at a glance.

| Day | Title | Paper | Size | Posting time |
| --- | --- | --- | --- | --- |
| Monday | The **Accretion** Ledger. | cream | 1800 × 1400 | after both 8-Ks |
| Wednesday | The **Coupon** Sheet. | certificate celadon, double-rule frame | 1800 × 1400 | after the 4:00 pm ET close |
| Friday | The **Closing** Mark. | black | 1800 × 1800 | Friday 4:00 pm ET mark |

The key word is set in Gelasio Bold (`assets/gelasio-variable.ttf`, SIL OFL,
`assets/GELASIO-OFL.txt`), a metric-compatible Georgia alternative, so no
Microsoft font is bundled. "The Digital Credit Report" stays as each panel's kicker.

## Run locally

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

Open `http://127.0.0.1:8501/?preview=1`. The live Monday and Friday tabs are unchanged
at the normal URL. Every preview tab fetches fresh data when a session opens it,
has a **Refresh data** button, a PNG download and an **Audit values** list.

Without Streamlit:

```powershell
.venv\Scripts\python scripts\render_previews.py --out previews
.venv\Scripts\python scripts\render_previews.py --out previews --offline   # saved inputs, demo Friday week
```

Both write `monday.png`, `wednesday.png`, `friday.png` and `audit.json`.

## What each panel adds

**Monday — The Accretion Ledger.** Every existing figure, plus:
- USD cover (months of preferred dividends), total coverage in years and the BTC
  break-even growth rate.
- A cash/USD-reserve change row and the net funding bridge:
  `capital raised + cash drawn = funding for BTC and other uses`.
- Amplification as the percent the podcasts and dashboards quote:
  `(debt + preferred) ÷ BTC`, with its preferred, debt and net-leverage parts.
- A sats-per-share sparkline over every reconciled weekly filing.
- Strive's PIPE warrant flag (25.8m @ $27, deadline 5:00 pm ET Oct 13). It disappears
  after the deadline.
- One estimate legend instead of a ≈ on every number, and larger secondary text.

**Wednesday — The Coupon Sheet.** New panel:
- The ladder: effective yields for STRC, SATA, STRF, STRK, STRD and STRE against
  SOFR, the 3-month bill, the 10-year, and ICE BofA investment-grade and high-yield.
- Par tracker: STRC and SATA over 12 weeks with a $99–$101 band, closes at or
  above par, and SATA's rate-cut test. The prospectus allows a cut only if the prior
  dividend period averaged at least $99.
- 30-day liquidity and turnover, and STRC + SATA as a share of BTC spot volume.
- A four-week flow ledger from the Monday 8-Ks, including buybacks as % of STRC volume.
- Coverage for both issuers and a dated calendar: record/pay dates, warrant deadline,
  quarter end.

**Friday — The Closing Mark.** Every reading is taken at the Friday 4:00 pm ET mark;
none needs a Sunday close. It adds:
- Named 200W zones: Very Cheap, Cheap, Fair Value, Expensive, Very Expensive.
- The 50W SMA, 20W SMA / 21W EMA band and realized price on the BTC chart.
- A "vs 50W" status line.
- The seven-cell cycle checklist: 50W, band, 50D/200D, weekly RSI, MVRV, Puell,
  supply in profit.
- Turnover (% of shares traded) instead of raw dollars, and the STRC buyback share of volume.
- Fear & Greed regime and duration, and a supply-in-profit bottom zone.
- The macro strip: DXY vs 101, the US 10-year, and Fed funds minus the 2-year.
- 50D/200D cross flags on MSTR and ASST.

## Data (no API keys)

`panels/extras.py` fetches each source independently. A failed section falls back to
`data/preview-extras.json` and the panel lists it as a saved snapshot. Refresh that
file with `scripts/render_previews.py --save-extras`.

| Source | Used for |
| --- | --- |
| api.strategy.com `bitcoinKpis`, `mstrKpiData`, `{strc,strf,strk,strd,stre}KpiData` | USD months of dividends, annual dividends, preferred prices, rates, effective yields, notional, record/pay dates |
| strive.com `treasury/api/dashboard/base-data` | dividend reserve months, SATA daily dividend (rate = daily × 252), cash, shares |
| fred.stlouisfed.org `fredgraph.csv` | DGS10, DGS2, DGS3MO, DFF, SOFR, BAMLH0A0HYM2EY, BAMLC0A0CMEY |
| Yahoo chart API | preferred prices/volume, DX-Y.NYB, ^TNX, PFF, HYG, BTC-USD volume |
| Checkonchain public charts | MVRV with mean/±sd, realized price, Puell Multiple with bands |
| Monday filing feed (Cloudflare Worker) and committed checkpoint | issuance, buybacks, USD reserve/cash, SATA shares, warrants |

`data/preview-config.json` holds the dated warrant terms and the Strategy 12-month
reserve floor, each with a source.
