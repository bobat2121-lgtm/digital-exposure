"""Explanations and input audit displayed outside the main comparison panels."""
from .models import Report
from .calculations import liquid_assets
from .presentation import number

PUBLIC_METHODOLOGY = """
**Shares & NAV.** Per-share figures use split-adjusted Class A + B common shares.
NAV is BTC value + cash/securities − debt principal − preferred liquidation
claims, including accrued dividends. Strategy includes its designated
treasury liquidity only. Price/basic NAV divides the stock price by NAV/share.

**Bitcoin.** Bought and Sold show reported gross activity separately, never inferred
from changes in holdings; total BTC is ending holdings.
BTC/common share is holdings divided by shares, in sats (100 million/BTC).

**Market activity.** Strategy common capital uses disclosed net proceeds less buybacks.
Average sale price = net issuance proceeds ÷ shares sold, after fees.
Strive uses net new shares × prior-week equity VWAP, estimated from one-minute
bars, before fees; noncash share changes can affect this proxy. Preferred capital
uses issuance cash less repurchases; SATA uses net new shares × $100 before
fees. Repurchase average = repurchase cash ÷ shares repurchased.

**Growth.** WoW compares the dated snapshots; QTD starts June 30, 2026 and YTD
December 31, 2025. Growth is ending per-share value ÷ starting value − 1.
NAV growth holds BTC, securities and FX prices constant at current marks;
Strategy's liquidity stays at its disclosed USD value. These are not stock returns.

**Ratios.** Net BTC amplification = BTC value ÷ NAV. Preferred/BTC = preferred
claims ÷ BTC value. Their weekly changes use the prior edition's own prices,
in multiples and percentage points respectively.

**Estimates.** ≈ includes rounded balances, reconstructed claims and Strategy's
June 30 debt carryforward. Quotes can be newer than balances. Missing inputs
stay unavailable. Price/NAV and amplification are N/M when NAV ≤ 0.

**Strive YTD, August 28.** Its 40.8% uses assumed dilution; our 45.56% uses basic
shares. The issuer's year-end award count remains unreconciled.
"""

POST_METHODOLOGY = """
**Share basis.** All per-share measures use actual effective Class A + Class B
common shares, adjusted consistently for stock splits. They do not use EPS
weighted-average shares or either issuer's assumed diluted KPI denominator.

**Net treasury NAV/share.** Bitcoin market value + cash/reserves + securities
market value − debt principal − preferred liquidation claims, divided by common
shares. Cash and securities are counted once. Preferred claims include applicable
unpaid/accrued dividends; a future declared dividend is not automatically accrued.
**Price/basic NAV** is the common stock price divided by this NAV/share.

**Bitcoin bought / sold.** Gross purchases and sales reported for the displayed
week are shown separately, never inferred from changes in holdings. Unreported
activity stays not disclosed. **Total BTC held** is the ending holding at the displayed
balance date, rounded to whole BTC. **BTC/common share** is BTC held divided by common
shares, displayed in satoshis (100 million sats per BTC).

**Common capital.** Strategy uses reported proceeds net of sales commissions,
less reported repurchase cash. Strive uses the change in common shares times
the prior week's equity VWAP estimate, before fees; this is not disclosed gross
issuance cash. The saved ASST VWAP weights one-minute typical prices by volume.

**Preferred capital.** Issuance proceeds less repurchase cash. Where actual cash
is disclosed, use it directly. Strive's SATA estimate uses the net share increase
at the requested $100 per share assumption. Sales/repurchases and any VWAP are
identified on the card. Average repurchase price is total gross repurchase cash
divided by shares repurchased; it excludes issuance proceeds.

**Weekly changes.** BTC/share and common-share changes compare the two dated
balance snapshots. NAV/share growth values both weeks at the same current BTC,
securities and FX prices, then computes current NAV/share ÷ prior NAV/share − 1.
It includes all balance and share-count changes, not only financing.

**Net BTC amplification** is BTC market value ÷ net treasury NAV. **Preferred/BTC**
is preferred claims ÷ BTC market value. Their changes are an absolute multiple
change and percentage-point change, respectively. They compare with the saved
prior edition's own prices; the current-price card identifies that edition date
in its footer. A higher amplification is not automatically better.

**QTD and YTD growth.** Ending BTC/share ÷ baseline BTC/share − 1; for NAV/share,
use the same ratio after marking both portfolios at the current asset prices
and FX. QTD starts June 30, 2026 and YTD starts December 31, 2025. Results end at
the displayed balance dates, even when market quotes are newer. Keep each date's
debt and contractual preferred claims. These are cumulative per-share growth
measures, not stock returns, dividend yields, or annualized rates. They use a
common definition rather than importing issuer dashboard yields.

**Precision and gaps.** ≈ marks estimates, including rounded disclosures and
reconstructed claims. N/M denotes a nonpositive NAV denominator. A missing input
is never replaced with zero. The sources and period-baseline audit are below.
"""

METHODOLOGY = """
**Normalized dashboard definitions.** These are this report's comparison rules,
not exact replicas of either company's published methodology. All prices,
balances, cash flows and timestamps in this edition are fictional test inputs.

**Net treasury NAV** = B + C + S − D − P, where B is BTC holdings × latest BTC
price; C is cash and cash equivalents, including designated reserves exactly
once; S is marketable securities at fair value; D is outstanding debt principal;
and P is preferred liquidation claims. Cash reserves remain assets while held.
Strive's illustrative $50m STRC investment is in securities, separately from cash.
Debt and preferred claims remain unconverted.

**Common-share measures.** NAV/share = net treasury NAV ÷ effective Class A +
Class B common shares. This is not the weighted-average EPS share count.
Price / net NAV = stock price ÷ NAV/share. BTC/common share = BTC holdings ÷
effective common shares; multiply by 100,000,000 for sats/share.

**Net BTC amplification** = B ÷ net treasury NAV. Its weekly change is the
absolute difference in multiples from the saved previous Monday, using that
edition's own BTC price and quantities. Changes use two decimals; negative
zero is suppressed. **Preferred / BTC** = P ÷ B. Its weekly change is a
percentage-point difference, not a relative percentage change.

**Weekly NAV/share change at constant market prices.** Both weeks' quantities
are valued at the same latest BTC and other asset prices, then current
NAV/share ÷ previous NAV/share − 1. The sample securities prices stay constant.
This includes financing and other balance changes; it is not solely an issuance
effect. Share and sats changes compare with the saved prior edition.

**Strategy net common capital.** Disclosed issuance proceeds after fees, including
separately identified warrant-exercise cash exactly once, minus cash spent on
common buybacks. The Strategy fixture treats the $600m issuance total as
inclusive of any warrant cash; no separate warrant amount is disclosed.

**Strive estimated net common capital.** Net new effective common shares × the
prior reporting week's equity VWAP. The illustrative estimate uses 94.0m −
90.4m = 3.6m shares and an assumed $27.50 prior-week ASST VWAP, giving $99.0m
before fees. This is a share-count-based estimate requested for the prototype;
it is not disclosed cash proceeds. Strive's actual issuance, buyback and warrant
cash remain unknown. The model treats the net increase as new shares added to
the market; it cannot distinguish cash issuance from noncash changes or
offsetting issuance and buybacks. Do not subtract buyback cash or add warrant
cash again to this estimate. It does not change reported cash, NAV or claims.
VWAP uses volume-weighted prior-week equity trades when supplied; the sample
uses the explicit illustrative VWAP input and never substitutes today's quote.

**Estimated net preferred capital.** Newly issued SATA/STRC shares × an assumed
$100, minus repurchased shares × the prior reporting week's volume-weighted
average trading price (VWAP). VWAP = sum(trade price × trade volume) ÷
sum(trade volume). The $100 issuance assumption is not evidence of execution
prices. The Strategy fixture uses the supplied $93.75 prior-week VWAP estimate;
there is no underlying trade tape in this sample. Other Strategy series are
pooled with STRC and have explicitly zero activity in this fixture.

“Net” means net of repurchases; modeled preferred capital is before fees unless
fees are explicitly supplied. If only some fees are supplied, remaining fees
are still unknown. Capital flows never overwrite reported cash or preferred
claims. For example, Strategy's modeled $150m STRC repurchase cost and $160m
decline in claims remain separate.

**Missing information.** Not disclosed means an input is unavailable, not zero.
Trading volume and net share-count changes cannot establish gross issuance,
repurchases or warrant exercises. The BTC holdings changes are shown as net
BTC added; gross weekly purchases are not separately supplied in this fixture.
Price/NAV and amplification show N/M when net NAV is nonpositive. Comparisons
with a nonpositive denominator are not meaningful.

**Why the two BTC ratios differ.** With $100m BTC, $50m cash, $50m preferred and
no debt, NAV is $100m, amplification is 1.00×, and Preferred/BTC is 50%. Investing
the $50m cash in BTC leaves NAV at $100m, raises amplification to 1.50×, and
lowers Preferred/BTC to 33.33%.

**Why Strive's BTC/share grows faster than NAV/share in this sample.** BTC
holdings rise 8.41% and common shares rise 3.98%, so BTC/share grows 4.26%.
At the same $80,000 BTC price in both weeks, $144m more BTC + $13m more cash −
$80m more preferred claims = $77m more NAV, a 6.97% increase. After the same
3.98% share-count growth, NAV/share increases 2.88% ($12.21 to $12.56).
BTC/share measures BTC holdings only; NAV/share also accounts for cash,
securities, debt and preferred claims. The added claims absorb part of the
BTC gain. Their effect stays in NAV even though the separate claims-change
row has been removed from the panels.
"""


def input_rows(report: Report) -> list[dict[str, str]]:
    fields = (
        ("BTC holdings", "btc_holdings", False),
        ("Effective common shares", "effective_common_shares", False),
        ("Cash (reserves included once)", "cash", True),
        ("Marketable securities", "marketable_securities", True),
        ("Total cash + securities (combined where disclosed)", "liquid_assets", True),
        ("Debt principal", "debt_principal", True),
        ("Preferred liquidation claims", "preferred_claims", True),
    )
    rows = []
    for label, field, dollars in fields:
        row = {"Illustrative input" if report.illustrative else "Historical input": label}
        for c in report.companies:
            for edition in ("current", "prior"):
                snapshot = getattr(c, edition)
                value = liquid_assets(snapshot) if field == "liquid_assets" else getattr(snapshot, field)
                combined_component = snapshot.combined_liquid_assets is not None and field in ("cash", "marketable_securities")
                display = "Included in combined total" if combined_component else "Not verified" if value is None and not report.illustrative else number(value, 0, prefix="$" if dollars else "")
                if not report.illustrative and value is not None:
                    if field == "preferred_claims" and c.preferred_claims_estimated:
                        display = "≈" + display
                    elif field == "debt_principal" and c.ticker == "MSTR":
                        display += " (June 30 carryforward)"
                    elif field == "liquid_assets" and snapshot.combined_liquid_assets is not None:
                        display += " (designated liquidity)"
                row[f"{c.name} {edition}"] = display
        rows.append(row)
    return rows
