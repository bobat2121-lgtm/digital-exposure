"""Dated Strategy balances for growth using a common BTC price and EUR/USD rate.

Sources are the 2026 Q2 10-Q, 2025 10-K, and issuer basic-share table. The
snapshots use designated treasury liquidity, consistently with the report's
August snapshot; consolidated operating cash is outside that chosen scope.
"""

from decimal import Decimal
from math import isfinite

from .models import Snapshot


STRATEGY_PERIOD_SOURCE_URLS = {
    "QTD": (
        "https://www.sec.gov/Archives/edgar/data/1050446/"
        "000105044626000044/mstr-20260630.htm"
    ),
    "YTD": (
        "https://www.sec.gov/Archives/edgar/data/1050446/"
        "000105044626000020/mstr-20251231.htm"
    ),
    "shares": "https://www.strategy.com/shares",
    "STRC_dividend_periods": (
        "https://www.sec.gov/Archives/edgar/data/1050446/"
        "000119312526270366/d144149dex31.htm"
    ),
}
STRATEGY_PERIOD_BASELINE_DATES = {"QTD": "2026-06-30", "YTD": "2025-12-31"}
STRATEGY_PERIOD_BASELINE_NOTE = (
    "Strategy uses issuer basic Class A + B shares rounded to thousands. "
    "June's website total is 371.604m versus 371.603m in the 10-Q; "
    "the published website total is retained consistently with August. "
    "Baseline liquidity is the disclosed $2.40bn / $2.25bn designated USD reserve; "
    "no additional undisclosed treasury cash is assumed. Debt is principal, "
    "including secured loans. Preferred claims use dated liquidation preferences "
    "(December STRF: $106.17) and current EUR/USD for STRE. Both baselines are "
    "after scheduled dividend payments, with zero further accumulated dividends "
    "assumed; future-period declared dividends are excluded. NAV growth is an estimate."
)

# Exact series share counts from the preferred-stock notes. Liquidation
# preferences are dated contractual claims, not preferred market values.
_PREFERRED_USD_COMPONENTS = {
    "QTD": ((12_839_689, "100"), (104_894_705, "100"),
            (14_020_744, "100"), (14_024_221, "100")),
    "YTD": ((12_839_689, "106.17"), (29_587_063, "100"),
            (13_981_948, "100"), (14_024_221, "100")),
}
_STRE_EUR_CLAIMS = Decimal(7_750_000) * Decimal(100)


def _preferred_claims(period: str, eurusd: float | None) -> float | None:
    if eurusd is None:
        return None
    usd_claims = sum(
        Decimal(shares) * Decimal(preference)
        for shares, preference in _PREFERRED_USD_COMPONENTS[period]
    )
    return float(usd_claims + _STRE_EUR_CLAIMS * Decimal(str(eurusd)))


def strategy_period_baselines(
    btc_price: float | None, eurusd: float | None
) -> dict[str, Snapshot]:
    """Return June 30 QTD and December 31 YTD starting snapshots.

    BTC stays in coins; the growth calculator applies ``btc_price`` to both
    dates. STRE's euro claims are translated here at the supplied current FX.
    Missing FX leaves only preferred claims unknown, preserving BTC/share.
    """
    for name, price in (("BTC price", btc_price), ("EUR/USD", eurusd)):
        if price is not None and (
            isinstance(price, bool) or not isfinite(price) or price <= 0
        ):
            raise ValueError(f"{name} must be finite and positive")

    # Both dates follow scheduled dividend payments. In particular, the 10-K
    # explicitly identifies its $27.1m payable as January's future STRC dividend.
    # June's certificate preserves the June 30 payment and begins the next
    # accrual period July 1; future declared July/August payments are not accrued
    # June claims. Do not stack the GAAP payable on this claim calculation.
    return {
        "QTD": Snapshot(
            btc_holdings=846_000,
            # Website's explicit basic total; 10-Q KPI table says 371.603m.
            # Both have the same stated scope. The 1,000-share discrepancy
            # is unresolved; do not assert an unsupported revision or cause.
            effective_common_shares=371_604_000,
            cash=None,
            marketable_securities=None,
            combined_liquid_assets=2_400_000_000,
            debt_principal=6_713_659_000 + 40_044_000,
            preferred_claims=_preferred_claims("QTD", eurusd),
        ),
        "YTD": Snapshot(
            btc_holdings=672_500,
            effective_common_shares=312_062_000,
            cash=None,
            marketable_securities=None,
            combined_liquid_assets=2_250_000_000,
            debt_principal=8_213_659_000 + 40_341_000,
            preferred_claims=_preferred_claims("YTD", eurusd),
        ),
    }
