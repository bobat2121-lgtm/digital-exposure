"""Period growth from dated share counts and balances at one set of market marks.

Baseline providers reprice their securities and foreign-currency claims before
these calculations. Financing flows are never added to a balance snapshot.
"""

from dataclasses import dataclass
from decimal import Decimal
from math import isclose, isfinite

from .calculations import net_treasury_nav
from .current_prices import load_current_prices
from .historical_claims import ECB_USD_PER_EUR, strategy_claim_components
from .models import Report, Snapshot


PERIODS = ("QTD", "YTD")


@dataclass(frozen=True)
class PeriodGrowth:
    btc_per_share_growth_pct: float | None
    nav_per_share_growth_pct: float | None
    nav_not_meaningful: bool = False


def _finite(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def _per_share(value, shares) -> float | None:
    if not _finite(value) or not _finite(shares) or shares <= 0:
        return None
    result = value / shares
    return result if _finite(result) else None


def _growth(current, baseline) -> float | None:
    if not _finite(current) or not _finite(baseline) or baseline <= 0:
        return None
    result = (current / baseline - 1) * 100
    return result if _finite(result) else None


def calculate_period_growth(current: Snapshot, baselines: dict[str, Snapshot | None],
                            current_btc_price: float | None) -> dict[str, PeriodGrowth]:
    """Compare BTC/share and NAV/share without rounding either result.

    All snapshots must already use the same current security and FX marks.
    Missing inputs yield None. Nonpositive NAV is independently identified so
    presentation can show N/M instead of implying an ordinary growth rate.
    """
    if set(baselines) - set(PERIODS):
        raise ValueError("Period baselines must use QTD and/or YTD keys")
    current_btc = (_per_share(current.btc_holdings, current.effective_common_shares)
                   if _finite(current.btc_holdings) and current.btc_holdings >= 0 else None)
    current_nav = net_treasury_nav(current, current_btc_price)
    current_nav_per_share = _per_share(current_nav, current.effective_common_shares)
    result = {}
    for period in PERIODS:
        baseline = baselines.get(period)
        if baseline is None:
            result[period] = PeriodGrowth(None, None)
            continue
        baseline_btc = (_per_share(baseline.btc_holdings, baseline.effective_common_shares)
                        if _finite(baseline.btc_holdings) and baseline.btc_holdings >= 0 else None)
        baseline_nav = net_treasury_nav(baseline, current_btc_price)
        baseline_nav_per_share = _per_share(baseline_nav, baseline.effective_common_shares)
        not_meaningful = ((_finite(current_nav) and current_nav <= 0)
                          or (_finite(baseline_nav) and baseline_nav <= 0))
        result[period] = PeriodGrowth(
            btc_per_share_growth_pct=_growth(current_btc, baseline_btc),
            nav_per_share_growth_pct=None if not_meaningful else _growth(current_nav_per_share, baseline_nav_per_share),
            nav_not_meaningful=not_meaningful,
        )
    return result


def _strategy_baselines(btc_price, eurusd):
    from .strategy_period_baselines import strategy_period_baselines
    return strategy_period_baselines(btc_price, eurusd)


def _strive_baselines(strc_price):
    from .strive_period_baselines import strive_period_baselines
    return strive_period_baselines(strc_price)


def _quote_price(prices: dict, symbol: str) -> float:
    try:
        quote = prices["quotes"][symbol]
        value = quote["price"]
        if quote["symbol"] != symbol or not _finite(value) or value <= 0:
            raise ValueError(f"Invalid {symbol} period-comparison price")
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Missing {symbol} period-comparison price") from exc
    return value


def _market_marks(report: Report, prices: dict | None) -> tuple[float, float]:
    companies = {company.ticker: company for company in report.companies}
    if report.edition_id == "current-prices":
        prices = load_current_prices() if prices is None else prices
        if prices is None:
            raise ValueError("Current period growth requires the report's saved price snapshot")
        btc = _quote_price(prices, "BTC-USD")
        strc = _quote_price(prices, "STRC")
        fx = _quote_price(prices, "EURUSD=X")
        expected_claims = float(sum(row["estimated_claims_usd"] for row in
                                    strategy_claim_components("current", usd_per_eur=Decimal(str(fx))).values()))
        comparisons = (
            (report.current_btc_price, btc),
            (companies["ASST"].current.marketable_securities, 505_000 * strc),
            (companies["MSTR"].current.preferred_claims, expected_claims),
        )
        if any(not _finite(actual) or not isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-5)
               for actual, expected in comparisons):
            raise ValueError("Period growth prices do not match the report snapshot; rebuild from the same quotes")
        return fx, strc
    if report.edition_id == "2026-08-31":
        # Match the historical report's rounded fair-value mark exactly.
        strc = companies["ASST"].current.marketable_securities / 505_000
        return float(ECB_USD_PER_EUR["current"]), strc
    raise ValueError("No verified period baselines are configured for this report edition")


def get_period_growth(report: Report, prices: dict | None = None) -> dict[str, dict[str, PeriodGrowth]]:
    """Use actual June30/Dec31 baseline providers for the supported dated reports.

    Current mode accepts the same complete price snapshot used to build the
    report. Historical mode retains its historical marks. This function never
    fetches quotes and never mixes real baselines into an illustrative report.
    """
    if report.illustrative:
        return {}
    fx, strc = _market_marks(report, prices)
    baselines = {"MSTR": _strategy_baselines(report.current_btc_price, fx),
                 "ASST": _strive_baselines(strc)}
    return {company.ticker: calculate_period_growth(company.current, baselines[company.ticker], report.current_btc_price)
            for company in report.companies}
