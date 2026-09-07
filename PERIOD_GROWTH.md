# QTD and YTD growth audit

Calculated September 7, 2026. QTD starts June 30, 2026; YTD starts December 31, 2025. The ending balances remain **August 30 for Strategy and August 28 for Strive**. Updating market prices does not advance those filing dates.

| Company | Period | BTC / basic share growth | NAV / basic share growth, constant prices |
|---|---|---:|---:|
| Strategy | QTD | −11.72% | ≈−2.63% |
| Strategy | YTD | −6.74% | ≈−1.69% |
| Strive | QTD | +2.43% | ≈+3.40% |
| Strive | YTD | +45.56% | ≈+18.45% |

These are reconstructed per-share balance changes through the stated ending dates. They are not investment returns or the issuers' separately defined BTC Yield. Values below reproduce this saved quote snapshot; refreshing prices can change NAV growth while leaving BTC/share growth unchanged.

Strive's published **40.8% YTD BTC Yield** reproduces exactly using its assumed-diluted denominators of 44,766,899 and 96,523,351 shares. This report's **45.56%** uses basic A + B shares. See [STRIVE_YIELD_AUDIT.md](STRIVE_YIELD_AUDIT.md) for the share bridge, exact arithmetic and unresolved year-end award-count discrepancy in the issuer's API.

## Market marks

The complete quote cache was fetched September 7 at 16:34:47.986 ET. Each observation retains its provider timestamp; the equity observations are Friday closing prices.

| Mark | Value | Observed at, Eastern time | Provider |
|---|---:|---|---|
| BTC/USD | $79,207.14 | Sep 7, 16:34:37.968 | [Strategy API](https://api.strategy.com/btc/bitcoinKpis) |
| STRC | $97.75 | Sep 4, 16:00:00 | [Yahoo chart](https://query1.finance.yahoo.com/v8/finance/chart/STRC?interval=1d&range=5d) |
| EUR/USD | 1.1625 | Sep 7, 16:34:30 | [Yahoo chart](https://query1.finance.yahoo.com/v8/finance/chart/EURUSD%3DX?interval=1d&range=5d) |
| MSTR | $142.80 | Sep 4, 16:00:01 | [Yahoo chart](https://query1.finance.yahoo.com/v8/finance/chart/MSTR?interval=1d&range=5d) |
| ASST | $27.14 | Sep 4, 16:00:01 | [Yahoo chart](https://query1.finance.yahoo.com/v8/finance/chart/ASST?interval=1d&range=5d) |

MSTR and ASST market prices inform the report's valuation ratios; they do not enter these two growth calculations.

## Calculation and dated inputs

For each endpoint:

```
BTC/share = BTC holdings / basic common shares
NAV/share = (BTC holdings × BTC price + liquid assets − debt principal − preferred claims)
            / basic common shares
Growth % = (ending per-share value / baseline per-share value − 1) × 100
```

Both endpoints use the same BTC price, STRC price and EUR/USD rate. Financing flows are already reflected in the balances and are never added again. Missing inputs remain unavailable; nonpositive NAV is shown as N/M. Calculations preserve precision until presentation.

All dollar figures in the next table are millions, except NAV/share. Strategy liquidity is its designated USD reserve; Strive liquidity is cash plus the disclosed STRC quantity marked at $97.75. The basic denominator excludes EPS weighted-average and assumed-dilution shares.

| Company / balance date | BTC | Basic common shares | Liquid assets, $m | Debt, $m | Preferred claims, $m | NAV/share |
|---|---:|---:|---:|---:|---:|---:|
| Strategy · Dec 31, 2025 | 672,500 | 312,062,000 | 2,250.000 | 8,254.000 | 8,023.450481 | $125.742164 |
| Strategy · Jun 30, 2026 | 846,000 | 371,604,000 | 2,400.000 | 6,753.703 | 15,478.873400 | $126.954134 |
| Strategy · Aug 30, 2026 | 845,050 | 420,483,000 | 6,710.000 | 6,753.703 | 14,910.044884 | $123.620327 |
| Strive · Dec 31, 2025 | 7,627 | 44,713,285 | 67.499 | 0 | 202.300230 | $10.496022 |
| Strive · Jun 30, 2026 | 19,864 | 81,944,827 | 194.829750 | 0 | 782.950200 | $12.023336 |
| Strive · Aug 28, 2026 | 23,156 | 93,262,570 | 232.863750 | 0 | 907.482139 | $12.432663 |

Strategy's historical BTC and basic shares come from the [issuer's shares table](https://www.strategy.com/shares). June reserve, debt and preferred schedules come from its [Q2 10-Q](https://www.sec.gov/Archives/edgar/data/1050446/000105044626000044/mstr-20260630.htm); December schedules come from its [2025 10-K](https://www.sec.gov/Archives/edgar/data/1050446/000105044626000020/mstr-20251231.htm). Basic shares are reported in thousands. The designated reserve excludes consolidated operating cash and retains its disclosed amount; the underlying short-term portfolio is not repriced instrument by instrument.

Strive's [Q2 10-Q](https://www.sec.gov/Archives/edgar/data/1920406/000162828026054985/asst-20260630.htm) supplies both baseline columns, including cash of $145.466m/$67.499m and STRC holdings of 505,000/zero. Its comparative common shares already reflect the reverse split. Dollar disclosures are rounded and BTC counts approximate whole coins. Ending weekly inputs, carried-forward debt and preferred reconstruction are documented in [HISTORICAL_SOURCES.md](HISTORICAL_SOURCES.md).

Strategy's June basic-share total has a small source discrepancy: the issuer website shows 371.604m, while its 10-Q shows 371.603m under the same stated scope. This report retains the website total. The filing alternative changes BTC/share growth by about 0.00024 percentage point; displayed QTD BTC and NAV growth are unchanged.

## Preferred claims and dividend timing

The common rule is liquidation preference plus dividends accumulated through the balance date. A GAAP dividends-payable balance can include a declared future payment and is not automatically an accrued liquidation claim.

Strategy's June domestic base preference is $14,577,935,900. December's is $7,122,512,981.13, including STRF's reported **$106.17** preference. Both add €775m of STRE at the same current exchange rate. The baseline reconstruction assumes ordinary dividends paid at each period-end payment date. The annual filing identifies its $27.1m payable as the future January STRC declaration. The [June STRC certificate](https://www.sec.gov/Archives/edgar/data/1050446/000119312526270366/d144149dex31.htm) preserves the June 30 payment before the next accrual begins July 1. Future declarations are excluded from period-end accrued claims.

Strive explicitly reports $100 preference at both baseline dates. The [issuer payment history](https://www.strive.com/treasury/api/dashboard/base-data) confirms June 30's daily dividend paid. Under the [amended certificate](https://www.sec.gov/Archives/edgar/data/1920406/000162828026034802/certi1.htm), ordinary accrual after that payment is zero: June claims are 7,829,502 × $100 = **$782,950,200**.

December falls between paid December 15 and scheduled January 15 dividends. The [original certificate](https://www.sec.gov/Archives/edgar/data/1920406/000114036125041210/ny20056805x9_ex4-1.htm) specifies a 360-day year of twelve 30-day months. The [December 15 announcement](https://investors.strive.com/news-events/news-releases/news-details/2025/Strive-Increases-SATA-Perpetual-Preferred-Stock-Dividend-to-12-25/default.aspx) sets 12.25% effective December 16. The estimate uses half the nominal monthly period:

```
Dec 31 accrued dividend = 2,012,729 × $100 × 12.25% × 15/360
                       = $1,027,330.427083
Dec 31 preferred claims = $201,272,900 + accrued dividend
                        = $202,300,230.427083
```

This uses ending shares; the first-dividend terms of December ATM issuances can alter the exact aggregate accrual. The full $2.053m declared payable is not added, and cash is not reduced again. This limitation, rounded disclosures and current claim estimates support the ≈ NAV label.

At August 28, SATA's reconstructed preference is bounded at $100–$100.01; the report uses the conservative upper value. Holding other inputs fixed, this produces QTD NAV growth of **3.40444%–3.41253%** and YTD of **18.45119%–18.46046%**. This narrow sensitivity covers only that current preference ambiguity, not every disclosure or accrual estimate.

## Reproduce and verify

`report/period_growth.py` combines the two dated baseline providers with the report's market snapshot. `get_period_growth(report, prices=quotes)` requires the same quotes used to build a current report, rejects mismatched market marks, and returns no real-baseline comparisons for illustrative reports.

From the repository, run:

```
python -m unittest discover -s tests -p test_period_growth.py -v
```

All eight focused tests passed, including independent numerical reconciliation, dilution, missing inputs, nonpositive NAV, fixed market marks and prevention of mixed quote snapshots. The two baseline providers have separate source-input tests.
