# Monday Capital Report — August 31, 2026 reconstruction

Reconstructed September 7 from dated filings, company records and market data. The edition represents the August 31 Monday report, comparing the previous week. It is **not an archived 09:00 ET snapshot**: some historical company records were recovered or updated afterward. Reported financing flows and balances are distinguished from valuation estimates, marked **≈**.

## Reported balances and financing

Strategy's [August 31 8-K](https://www.sec.gov/Archives/edgar/data/1050446/000119312526375463/mstr-20260831.htm) covers August 24–30; Strive's [August 31 8-K](https://www.sec.gov/Archives/edgar/data/1920406/000162828026059468/asst-20260831.htm) covers August 24–28. SEC acceptance was [08:00:15](https://www.sec.gov/Archives/edgar/data/1050446/000119312526375463/0001193125-26-375463-index.htm) and [07:59:24](https://www.sec.gov/Archives/edgar/data/1920406/000162828026059468/0001628280-26-059468-index.htm), respectively. Prior filings: [Strategy August 24](https://www.sec.gov/Archives/edgar/data/1050446/000119312526361845/mstr-20260824.htm), [Strive August 24](https://www.sec.gov/Archives/edgar/data/1920406/000162828026058518/asst-20260824.htm).

| Balance input | Prior | Current |
|---|---:|---:|
| Strategy BTC, Aug 23 → 30 | 840,447 | 845,050 |
| Strategy designated USD Reserve | $5.10bn | $5.10bn |
| Strategy designated USD Cash | $1.59bn | $1.61bn |
| Strategy effective common shares, A+B | 415,929,000 | 420,483,000 |
| Strive BTC, Aug 21 → 28 | 21,356 | 23,156 |
| Strive effective common shares, A+B | 89,683,423 | 93,262,570 |
| Strive SATA shares | 8,270,815 | 9,073,914 |
| Strive cash/equivalents | $171.9m | $183.5m |
| Strive STRC investment fair value | $48.571m | $49.152m |

Strategy's common denominators are the company's **rounded basic/effective counts**, at thousand-share precision: Class A 396.289m + Class B 19.640m previously, and 400.843m + 19.640m currently. Prior figures were recovered from search-indexed official [Polish](https://www.strategy.com/pl/shares) and [Chinese](https://www.strategy.com/zh/shares) tables dated August 23; the [live table](https://www.strategy.com/shares) now shows August 30. Original publication timestamps and unrounded counts were not recovered. Provenance is saved in `data/strategy-basic-shares-2026-08-31.json`. Effective counts include applicable shares pending issuance; the 4.554m change is not inferred from ATM sales alone. Strive's effective counts also include sold shares pending issuance.

Strategy reports **+$602.8m common capital**, net of sales commissions, from 4,531,421 ATM shares sold and no common repurchases in the disclosed table. **−$151.8m preferred capital** is the cash cost of 1,557,177 STRC repurchases. The average repurchase price is reported gross repurchase cash divided by shares repurchased: **$151,800,000 ÷ 1,557,177 = $97.48 per share**, rounded to two decimals. Issuance proceeds are excluded from that average. Its table covers STRF/STRC/STRK/STRD, with no preferred issuance and no other listed repurchases. The financing total retains that disclosure scope; it does not assert unreported STRE activity was zero. Reported cash is used directly, without deducting modeled fees again.

Strive bought 1,800 BTC and reports **+3,579,147 net common shares** and **+803,099 net SATA shares**. Separate weekly gross issuance, repurchases and financing cash were not recovered. Common capital uses the VWAP estimate below. At the user's requested $100 per new preferred share, **803,099 net new SATA shares × $100 = $80,309,900**, displayed as **+$80.3m estimated capital before fees**. This is a net-share proxy; actual issuance proceeds and repurchase cash remain undisclosed. The $100 financing assumption does not replace the separate $100.01 conservative liquidation-claim input or change NAV.

## ASST common-capital estimate

The [dated Yahoo minute-bar request](https://query1.finance.yahoo.com/v8/finance/chart/ASST?period1=1787544000&period2=1787976000&interval=1m&includePrePost=false&includeAdjustedClose=false), retrieved September 7, supplies 1,950 regular-session bars for August 24–28. The calculation is:

`sum(((minute high + low + close) / 3) × minute volume) / sum(minute volume)`

This gives **$21.48697766**. Multiplying by 3,579,147 net new common shares gives **$76,905,051.64**, displayed as **+$76.9m estimated before fees**. The historical edition does not use the illustrative $27.50 assumption.

This is a minute-bar VWAP estimate for retrieved regular sessions. It is not exact trade VWAP or actual company proceeds. Retrieved volume is **60,213,874**, versus **62,508,500** in [Yahoo's daily history](https://ca.finance.yahoo.com/quote/ASST/history/); it does not establish full consolidated-market coverage. The dated cache retains eligible OHLCV bars, daily totals, source URLs and retrieval time so the calculation remains reproducible after minute-data retention expires.

The app and `pull_vwap.py` can request the prior calendar week or previous five completed NASDAQ sessions, accounting for holidays and early closes. Both windows select August 24–28 for this Monday edition. Incomplete data fails validation; a failed refresh preserves the saved estimate and never substitutes today's price.

## Strategy valuation reconstruction

**Liquid assets:** $5.10bn Reserve + $1.59bn/$1.61bn Cash = **$6.69bn/$6.71bn combined designated liquidity**. Treasury bills already held within the reserve are included once. No quarterly operating-cash add-on is used. This designated total is a proxy for the requested cash-plus-securities asset input, without a verified weekly instrument split. The weekly comparison holds prior combined liquidity at its stated USD amount.

**Debt:** the [June 30 10-Q](https://www.sec.gov/Archives/edgar/data/1050446/000105044626000044/mstr-20260630.htm) reports $6,713,659,000 convertible principal + $40,044,000 other secured principal = **$6,753,703,000**, carried forward to both snapshots. This is an estimate of August debt: later amortization and other changes are not reconciled. Using the same scope avoids an artificial gain from the company's [August 31 methodology change](https://www.strategy.com/notes) excluding nonconvertible debt.

**Preferred shares:** the June 30 10-Q supplies starting counts. STRC starts at 104,894,705; reported repurchases of 288,930 + 912,143 + 1,152,020 + 1,388,720 + 1,431,212 leave **99,721,680 on August 23**. Another 1,557,177 leaves **98,164,503 on August 30**. Sources are the [July 27](https://assets.contentstack.io/v3/assets/bltf8d808d9b8cebd37/blt152e68ca79c6c3e2/6a66cd282ed54801f094c62c/form-8-k_07-27-2026.pdf), [August 3](https://assets.contentstack.io/v3/assets/bltf8d808d9b8cebd37/blt4e80364948bf437c/6a6ff89f0da6737125578aab/form-8-k_08-03-2026.pdf), [August 10](https://assets.contentstack.io/v3/assets/bltf8d808d9b8cebd37/blt5753b925d6f68e09/6a794ef9dcb43781cc2cf7c3/form-8-k_08-10-2026.pdf), [August 17](https://assets.contentstack.io/v3/assets/bltf8d808d9b8cebd37/blt71aa29aaea82420c/6a8208cbc260234bb6b39071/form-8-k_08-17-2026.pdf), and August 24/31 filings above. Other series retain their June 30 counts, with no subsequent changes identified through the target period.

The reconstruction adds ordinary accrued unpaid dividends to base liquidation preference:

| Series | Prior shares | Current shares | Estimated prior claims, USD m | Estimated current claims, USD m |
|---|---:|---:|---:|---:|
| STRF | 12,839,689 | 12,839,689 | 1,302.871775 | 1,305.368382 |
| STRC | 99,721,680 | 98,164,503 | 9,998.760448 | 9,865.532552 |
| STRK | 14,020,744 | 14,020,744 | 1,418.587721 | 1,420.768725 |
| STRD | 14,024,221 | 14,024,221 | 1,402.422100 | 1,402.422100 |
| STRE | 7,750,000 | 7,750,000 | 920.020734 | 917.371375 |

The US series use a $100 base preference. Their preceding-ten-session raw-close averages remain below $100 at both Friday endpoints; the relevant issuance conditions for a higher preceding-close branch were not triggered in the reconstructed filings. The price inputs are saved in `data/preferred-price-windows-2026-08-31.json`. STRF's August 27 close of $102.58 therefore does not alone raise its preference. [STRE's certificate](https://www.sec.gov/Archives/edgar/data/1050446/000119312525280178/d205736dex31.htm) fixes its base at €100 until the first additional post-IPO issuance; none was identified through the target period.

Accrual math is ending shares × annual dividend per share × accrued days / 360, with days counted under the 30/360 convention. For [STRF](https://www.sec.gov/Archives/edgar/data/1050446/000119312525062523/d943742dex31.htm), [STRK](https://www.sec.gov/Archives/edgar/data/1050446/000119312525020868/d791994dex31.htm) and STRE, use annual $10/$8/€10 and 53 prior / 60 current days. [STRC's amended terms](https://www.sec.gov/Archives/edgar/data/1050446/000119312526270366/d144149dex31.htm) make its 12% dividend semi-monthly: use annual $12 and 8 prior / 15 current days since the August 15 payment. [STRD](https://www.sec.gov/Archives/edgar/data/1050446/000119312525138477/d941529dex31.htm) is noncumulative; no next-quarter dividend was declared at either Sunday snapshot, so additional accrued claims are zero.

STRE base plus accrued euros is translated using verified [ECB daily reference rates](https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?startPeriod=2026-08-21&endPeriod=2026-08-28&format=csvdata): **1.1699 USD/EUR on August 21**, **1.1643 on August 28**, saved in `data/ecb-eurusd-2026-08-21-28.csv`. These are explicitly an alternative to Strategy's Friday 12:30 ET BFIX convention.

Total estimated preferred claims are **$15,042,662,778.21 prior** and **$14,911,463,133.50 current**. The constant-price weekly comparison also retranslates prior STRE at current FX, giving prior preferred claims of **$15,038,258,883.77**.

These are reconstructed claims, not an exact paying-agent liability reconciliation. Accruing on ending shares does not fully resolve dividend rights retained by record holders after repurchases. For example, the August 31 filing allocates $50.7m of proceeds to STRC dividends, versus $49.082m in the ending-share accrual estimate. The former is not added again to claims or subtracted again from reported liquidity. This limitation, debt carryforward, rounded shares and designated-liquidity scope justify the **≈** valuation labels.

## Strive debt and preferred claims

Strive's [company dashboard API](https://www.strive.com/treasury/api/dashboard/base-data) contains dated August 21 and August 28 cash/debt records showing **$0 debt at both dates**. Its [dated calculated endpoint](https://www.strive.com/treasury/api/dashboard/calculated?fromDate=2026-08-21&toDate=2026-08-28&currency=USD&stockSymbol=ASST) corroborates preferred shares. Filtered evidence is saved in `data/strive-treasury-2026-08-31.json`. The current cash/debt record was updated September 6, so the response is historical evidence recovered afterward, not proof of its exact original contents at 09:00 ET.

The [amended SATA certificate effective June 15](https://www.sec.gov/Archives/edgar/data/1920406/000162828026034802/certi1.htm) uses the maximum of $100, the preceding ten-close mean, and the prior close when an issuance sale occurs that day. Unadjusted [dated SATA quotes](https://query1.finance.yahoo.com/v8/finance/chart/SATA?period1=1785729600&period2=1787976000&interval=1d&includePrePost=false&includeAdjustedClose=false&events=div%2Csplits) give August 21 inputs of $99.466 / $99.91, establishing $100. August 28 inputs are $99.831 / $100.01, leaving a **$100–$100.01** range because the exact issuance day is unknown. The report conservatively uses **$100.01** currently.

The [July 14 filing](https://www.sec.gov/Archives/edgar/data/1920406/000162828026048231/asst-20260714.htm) declares $0.0516 per August business day. Company payment history marks all installments through the respective Fridays paid. These are **Friday after-payment snapshots**, so additional accumulated unpaid dividends are zero; this convention does not extend to Sunday or Monday before payment.

Thus prior claims are **8,270,815 × $100 = $827,081,500** and current estimated claims are **9,073,914 × $100.01 = $907,482,139.14**. The unresolved penny creates $90,739.14 of total claim uncertainty. Derived valuation metrics carry **≈**; normalized weekly NAV/share is approximately **+2.67%**, versus **+2.68%** at the $100 alternative. These liability estimates remain separate from the $100-per-new-share capital proxy above.

## Price references and calculation checks

| Reference | Value | Observation |
|---|---:|---|
| [BTC](https://fortune.com/article/price-of-bitcoin-08-31-2026/) | $78,414.14 | Aug 31, 08:30 ET |
| [MSTR](https://ca.finance.yahoo.com/quote/MSTR/history/) | $127.31 | Aug 28 close |
| [ASST](https://ca.finance.yahoo.com/quote/ASST/history/) | $21.74 | Aug 28 close |
| [Prior BTC](https://fortune.com/article/price-of-bitcoin-08-24-2026/) | $78,976.18 | Aug 24, 09:00 ET |

Net treasury NAV = BTC value + cash/securities − debt principal − preferred liquidation claims. NAV/share and BTC/share use the same effective A+B denominator. Price/NAV = common price / NAV/share; net BTC amplification = BTC value / NAV; preferred/BTC = preferred claims / BTC value. These are treasury metrics, not a full GAAP net-asset appraisal including operating liabilities.

Weekly NAV/share compares both snapshots at current BTC and security prices and current FX for foreign preferred claims. Strive held 505,000 STRC shares at both dates, so prior securities are repriced to the current $49.152m. Financing estimates never overwrite these balance inputs.

| Calculated result | Strategy | Strive |
|---|---:|---:|
| Current NAV/share | ≈ $122.02 | ≈ $12.23 |
| Weekly NAV/share, constant prices | ≈ −0.09% | ≈ +2.67% |
| Weekly BTC/share | −0.54% | +4.27% |
| Price / NAV | ≈ 1.04× | ≈ 1.78× |
| Net BTC amplification | ≈ 1.29× | ≈ 1.59× |
| Preferred claims / BTC | ≈ 22.50% | ≈ 49.98% |

Strive's BTC/share gain exceeds its NAV/share gain because BTC/share measures BTC quantity after common dilution, while NAV/share also deducts senior claims. Approximately $80.4m of additional SATA claims offsets part of its BTC increase, with cash rising $11.6m. Preferred claims remain in NAV even though their separate change row is omitted from the report.

## Why issuer mNAV differs from this report

The card now says **Price / basic NAV**. It uses effective A+B common shares
and estimated senior liquidation claims. Comparing it with newer company
dashboards changes both the observation date and the share/claim methodology.

| Basis using this edition's historical market prices | Strategy | Strive |
|---|---:|---:|
| Report's basic-share price / NAV | 1.0433× | 1.7771× |
| Approximate issuer method at those same prices | 1.0503× | 1.84× |
| Newer benchmark cited by the user | 1.15× | 2.23× |

[Strategy's current methodology](https://www.strategy.com/notes), changed July
23, uses price divided by net BTC dollars per fully diluted share. It includes
awards and in-the-money conversions, and uses preferred notional excluding
accrued dividends. At this edition's price, 424.479m diluted shares, $6.713659bn
convertible principal and $14.8072482bn preferred notional give $121.2144 per
share and approximately 1.0503×. This reconstruction retains our ECB FX
substitute. The report's 1.0433× instead uses 420.483m basic shares and the
broader estimated senior claims. Strategy's current mNAV is not EV/BTC.

The [Strategy KPI API](https://api.strategy.com/btc/bitcoinKpis), retrieved
September 7 around 12:10 ET, reports a headline **1.1517×**. Its headline lacks
a separate mark timestamp; an extended-session value of 1.1687× reconciles
to $142.73 / $122.127. The current regular stock reference is **September 4's
$142.80**, compared with this report's **August 28 $127.31**. These newer marks
explain much more of the gap than the roughly 0.007× methodology difference.

[Strive's ASST panel](https://www.strive.com/treasury) defaults to diluted
shares. Its [client calculation](https://www.strive.com/treasury/_next/static/chunks/f1dc0e1087fa4659.js)
uses price / net treasury NAV per share. The default denominator is
**96,523,351** shares: 93,262,570 effective shares + 991,941 options + 2,268,840
RSUs/RSAs. Its helper uses $100 per SATA share, while this report's liability
estimate conservatively uses $100.01. At the report's market prices, using the
issuer share basis produces roughly **1.84×**, rather than 1.78×.

Strive's [dated API inputs](https://www.strive.com/treasury/api/dashboard/calculated?fromDate=2026-08-21&toDate=2026-09-07&currency=USD&stockSymbol=ASST)
reproduce **2.23165×** for September 5: ASST **$27.14**, BTC **$79,831.57**,
net treasury NAV **$1,173,859,194.66**, and diluted NAV/share **$12.1614**.
That supports the quoted 2.23× without establishing when the user observed
it. September 7 inputs instead calculate 2.27418×. The stock price is well
above the report's August 28 **$21.74** reference. Newer company multiples
should not be substituted into this August 31 edition without updating all
dates and inputs together.
