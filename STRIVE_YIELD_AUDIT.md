# Why Strive shows 40.8% YTD

Strive's dashboard reports **40.8% BTC Yield YTD** using its assumed-diluted share series. This report shows **45.56% growth in BTC per actual Class A + Class B common share**. The difference comes mainly from the share denominator; neither number measures a stock-price return.

Verified September 7, 2026 against the [Strive ASST dashboard](https://www.strive.com/treasury?tab=asst), its [base-data API](https://www.strive.com/treasury/api/dashboard/base-data), and its [full-history calculated API](https://www.strive.com/treasury/api/dashboard/calculated?fromDate=2025-05-06&toDate=2026-09-07&currency=USD&stockSymbol=ASST). The API labels the calculation September 7; the latest underlying BTC and share records remain dated **August 28**. These are live reconstructed records, not an archived December 31 or August 31 API snapshot.

The relevant public API fields are preserved in [the dated audit extract](data/strive-yield-audit-2026-09-07.json), retrieved at 20:58:20 UTC. This preserves the inputs used here even if the issuer later revises its historical series.

| Input | December 31, 2025 | August 28, 2026 |
|---|---:|---:|
| Class A common | 34,936,745 | 83,470,035 |
| Class B common | 9,776,540 | 9,792,535 |
| Actual common shares: A + B | **44,713,285** | **93,262,570** |
| Pre-funded warrant equivalents in issuer API | 53,614 | 0 |
| Legacy options in issuer API | 0 | 991,941 |
| RSU/RSA equivalents in issuer API | 0 | 2,268,840 |
| Issuer assumed-diluted denominator | **44,766,899** | **96,523,351** |
| Exact BTC in issuer API | 7,626.81383149 | 23,156.23499144 |
| Rounded BTC used by this report | 7,627 | 23,156 |

All share counts above use the post-February 6, 2026 reverse-split basis. The 2025 filing's comparative share figures are already adjusted; applying the 1-for-20 adjustment again would be incorrect. The [2025 10-K](https://www.sec.gov/Archives/edgar/data/1920406/000162828026019879/asst-20251231.htm) and [June 2026 10-Q](https://www.sec.gov/Archives/edgar/data/1920406/000162828026054985/asst-20260630.htm) provide the filing cross-checks.

The same growth formula applies to either share basis:

```text
BTC/share growth = [(ending BTC / ending shares)
                   / (baseline BTC / baseline shares) - 1] × 100

Issuer API:
[(23,156.23499144 / 96,523,351)
 / (7,626.81383149 / 44,766,899) - 1] × 100 = 40.81516346%

Report's actual common shares:
[(23,156 / 93,262,570)
 / (7,627 / 44,713,285) - 1] × 100 = 45.55897656%
```

The API directly returns `btcYieldYtd.value = 40.81516346240643`, with baseline 17,036.7257993 sats per assumed-diluted share and ending 23,990.2932830. The [ASST client code](https://www.strive.com/treasury/_next/static/chunks/f1dc0e1087fa4659.js) displays that API value to one decimal. Its [share helpers](https://www.strive.com/treasury/_next/static/chunks/6d31345061446cf5.js) add pre-funded warrants, options, convertible equivalents and RSU/RSA equivalents to A + B for assumed dilution; traditional warrants are excluded from that helper. Convertible equivalents are zero at these two dates.

Using rounded BTC with the issuer denominator gives **40.81029732%**, which also displays as 40.8%. BTC rounding therefore explains only about **0.005 percentage point**, not the roughly 4.75-point gap.

The same distinction applies to QTD: the API reports **2.23830843%** using June 30's 19,863.91793136 BTC and 84,653,128 assumed-diluted shares. This report uses 19,864 BTC and 81,944,827 basic shares at June 30, producing **2.42618522%** (displayed **2.43%**). Market prices do not affect either BTC/share growth calculation.

One historical denominator discrepancy remains: the issuer API records zero RSU/RSA equivalents at December 31, while Note 8 of the [2025 10-K](https://www.sec.gov/Archives/edgar/data/1920406/000162828026019879/asst-20251231.htm) reports approximately **822,000 unvested RSUs**, explicitly split-adjusted. The public calculation does not explain this difference. We can reproduce the dashboard exactly, but have not independently reconciled every component of its historical assumed-diluted denominator.

The report therefore retains the consistent actual-common-share definition and labels the section **Basic-share growth**. Matching the issuer KPI would require a separate, clearly named assumed-diluted series. Its NAV/share growth continues to include cash, securities, debt and preferred claims; BTC/share growth does not account for those senior claims.
