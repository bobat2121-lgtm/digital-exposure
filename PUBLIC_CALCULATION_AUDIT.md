# Public calculation overview audit

Audited September 7, 2026 against the existing calculation code and saved financial inputs. This audit reconciles the explanation to the implementation; it does not independently refresh issuer disclosures or market quotes. Financial inputs and NAV calculations are unchanged; Strategy average sale price is an added presentation calculation.

The new `PUBLIC_METHODOLOGY` in `report/methodology.py` is **270 words**, versus 468 words in the previous overview before its separate yield-audit paragraph and table. It preserves legacy methodology constants and retains the assumptions that materially affect interpretation after the Sources & input audit section is removed.

## Findings

- **Share basis:** BTC/share, NAV/share, and growth all use split-adjusted actual Class A + B common shares. They do not use EPS weighted-average or issuer assumed-diluted shares.
- **NAV scope:** The legacy cash/reserves wording needed clarification. Strategy uses designated treasury liquidity only, rather than all consolidated operating cash. It is counted once and held at its disclosed USD value in constant-price comparisons. Strive uses cash plus its separately marked STRC investment.
- **Liabilities:** NAV subtracts debt principal and contractual preferred claims, including the dated dividend-accrual assumptions. Strategy debt is a June 30 carryforward. Rounded balances and reconstructed preferred claims mean NAV remains approximate.
- **Financing:** Strategy common capital uses disclosed net proceeds less reported buyback cash. The calculation's `reported_atm` scope does not add unknown warrant proceeds. Strive common capital is a net-share-change × prior-week ASST VWAP proxy before fees; it cannot identify gross cash issuance or distinguish noncash share changes. The saved VWAP uses volume-weighted one-minute typical prices. SATA capital is net new preferred shares × the requested $100 assumption, before fees. These flows never overwrite NAV balances.
- **Repurchases:** Average repurchase price divides gross repurchase cash by repurchased shares, independently of issuance proceeds. The Strategy example is $151.8 million ÷ 1,557,177 = $97.4841007, displayed $97.48.
- **Common sale price:** Strategy's $602.8 million net issuance proceeds divided by 4,531,421 shares sold gives $133.026703985, displayed $133.03. The numerator is after sales fees and before subtracting buyback cash. This is a proceeds-based average, not an equity VWAP or the gross execution price.
- **Weekly comparisons:** BTC/share and share-count growth use dated quantities. NAV/share growth marks both balance snapshots at current BTC, security, and FX prices. Amplification and Preferred/BTC changes instead compare against the prior edition's own market prices, as absolute multiples and percentage points.
- **QTD/YTD:** June 30, 2026 and December 31, 2025 are the baselines. All NAV portfolios share the ending market marks but retain their dated quantities, debt and contractual claims. Growth is cumulative per-share change, not a stock return or an annualized yield.
- **Strive dashboard:** Saved API inputs reproduce 40.81516346% using assumed dilution, while the report produces 45.55897656% using basic common shares. BTC rounding accounts for only about 0.005 percentage point. The issuer's zero year-end award count remains unreconciled with the saved 10-K comparison; the shortened explanation retains that uncertainty.
- **Missing/negative inputs:** Missing data is not replaced with zero. Price/NAV and amplification are N/M for nonpositive NAV. Preferred/BTC can remain meaningful when BTC value is positive even if NAV is nonpositive, so the overview names the affected ratios explicitly.

## Recalculation from saved September 7 quotes

The balances end August 30 for Strategy and August 28 for Strive. The current quote snapshot was retrieved September 7; equity quotes are September 4 closes.

| Metric | Strategy | Strive |
|---|---:|---:|
| Net treasury NAV/share | $123.62032656 | $12.43266344 |
| Price/basic NAV | 1.15514984× | 2.18295944× |
| Common capital | $602,800,000 | $76,905,051.64 VWAP proxy |
| Preferred capital | −$151,800,000 | $80,309,900 at $100/share |
| BTC/share WoW | −0.54128712% | +4.26737154% |
| NAV/share WoW, constant prices | −0.10021213% | +2.69623982% |
| QTD BTC/share | −11.72372862% | +2.42618522% |
| QTD NAV/share, constant prices | −2.62599366% | +3.40444253% |
| YTD BTC/share | −6.74275898% | +45.55897656% |
| YTD NAV/share, constant prices | −1.68745099% | +18.45119376% |

The shortened public wording is consistent with these calculations. No NAV or financial-data correction was required for the public report design.

Validation: **68 existing calculation, current-report, period-growth, and historical-data tests passed**. The figures above were recalculated directly from the saved quote snapshot without a network refresh.

Reviewed: `calculations.py`, `period_growth.py`, `current_report.py`, `historical_data.py`, `historical_claims.py`, both period-baseline providers, the saved Strive yield audit, and the previous public explanation.
