"""Pure normalized financial calculations shared by page and PNG export.

No financing flows are added to reported balances. Missing information produces
None, never an invented zero. Formatters decide between Not disclosed and N/M.
"""

from math import isfinite

from .models import CommonCapital, Company, CompanyMetrics, PreferredActivity, Snapshot, Trade


def _known(value: float | None) -> bool:
    return value is not None and isfinite(value)


def _nonnegative(value: float | None) -> bool:
    return _known(value) and value >= 0


def _difference(current: float | None, prior: float | None) -> float | None:
    return current - prior if _known(current) and _known(prior) else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if not _known(numerator) or not _known(denominator) or denominator <= 0:
        return None
    return numerator / denominator


def _percentage_change(current: float | None, prior: float | None) -> float | None:
    ratio = _ratio(current, prior)
    return None if ratio is None else (ratio - 1.0) * 100.0


def btc_value(snapshot: Snapshot, btc_price: float | None) -> float | None:
    if not _nonnegative(snapshot.btc_holdings) or not _nonnegative(btc_price):
        return None
    return snapshot.btc_holdings * btc_price


def liquid_assets(snapshot: Snapshot) -> float | None:
    """Use either an exclusive combined reserve or complete separate balances."""
    if snapshot.combined_liquid_assets is not None:
        if snapshot.cash is not None or snapshot.marketable_securities is not None:
            return None
        return snapshot.combined_liquid_assets if _nonnegative(snapshot.combined_liquid_assets) else None
    if not _nonnegative(snapshot.cash) or not _nonnegative(snapshot.marketable_securities):
        return None
    total = snapshot.cash + snapshot.marketable_securities
    return total if _known(total) else None


def net_treasury_nav(snapshot: Snapshot, btc_price: float | None) -> float | None:
    bitcoin = btc_value(snapshot, btc_price)
    liquid = liquid_assets(snapshot)
    inputs = (bitcoin, liquid, snapshot.debt_principal, snapshot.preferred_claims)
    if not all(_known(value) for value in inputs):
        return None
    return bitcoin + liquid - snapshot.debt_principal - snapshot.preferred_claims


def common_issuance_cash(activity: CommonCapital) -> float | None:
    """After-fee issuance cash, adding separately identified warrants once."""
    if not _nonnegative(activity.issuance_proceeds_after_fees):
        return None
    if activity.issuance_includes_warrants is True:
        return activity.issuance_proceeds_after_fees
    if activity.issuance_includes_warrants is False and _nonnegative(activity.separately_reported_warrant_cash):
        return activity.issuance_proceeds_after_fees + activity.separately_reported_warrant_cash
    return None


def calculate_common_capital(activity: CommonCapital) -> float | None:
    proceeds = common_issuance_cash(activity)
    if not _known(proceeds) or not _nonnegative(activity.buybacks_cash):
        return None
    return proceeds - activity.buybacks_cash


def common_average_sale_price(activity: CommonCapital) -> float | None:
    """Net issuance proceeds per share sold, before any repurchase cash flows."""
    if not _nonnegative(activity.issuance_proceeds_after_fees):
        return None
    price = _ratio(activity.issuance_proceeds_after_fees, activity.issued_shares)
    return price if _known(price) else None


def weekly_vwap(trades: tuple[Trade, ...] | None) -> float | None:
    """sum(price * volume) / sum(volume), not an unweighted mean price."""
    if not trades:
        return None
    if any(not _nonnegative(trade.price) or not _nonnegative(trade.volume) for trade in trades):
        return None
    volume = sum(trade.volume for trade in trades)
    if volume <= 0:
        return None
    return sum(trade.price * trade.volume for trade in trades) / volume


def common_equity_vwap(company: Company) -> float | None:
    """Use prior-week volume-weighted trades when supplied, never a spot quote."""
    price = (weekly_vwap(company.prior_week_equity_trades)
             if company.prior_week_equity_trades is not None
             else company.prior_week_equity_vwap)
    return price if _known(price) and price > 0 else None


def estimate_common_capital(company: Company, equity_vwap: float | None) -> float | None:
    """Net effective shares added times VWAP; reductions retain a negative sign.

    This proxy does not establish actual issuance, exercise, repurchase cash or
    fees. Disclosed cash flows must not be added to the net share-change proxy.
    """
    current_shares = company.current.effective_common_shares
    prior_shares = company.prior.effective_common_shares
    if not _nonnegative(current_shares) or not _nonnegative(prior_shares):
        return None
    share_change = current_shares - prior_shares
    if share_change == 0:
        return 0.0
    if not _known(equity_vwap) or equity_vwap <= 0:
        return None
    amount = share_change * equity_vwap
    return amount if _known(amount) else None


def preferred_average_repurchase_price(activity: PreferredActivity) -> float | None:
    """Reported gross repurchase cash per share, independent of issuance flows."""
    if not _nonnegative(activity.reported_repurchases_cash):
        return None
    price = _ratio(activity.reported_repurchases_cash, activity.repurchased_shares)
    return price if _known(price) else None


def preferred_activity_capital(activity: PreferredActivity) -> float | None:
    """Reported cash, modeled gross activity, or a signed par-value proxy.

    Gross-activity modeling needs no price for an explicit zero quantity. The
    net-share proxy requires its stated price even at zero net change. Unknown
    gross quantities cannot be reconstructed from share-count changes or volume.
    Reported cash already carries the issuer's proceeds/cost basis and must not
    have modeled fees deducted again.
    """
    if activity.capital_method == "reported":
        if not _nonnegative(activity.reported_issuance_proceeds) or not _nonnegative(activity.reported_repurchases_cash):
            return None
        return activity.reported_issuance_proceeds - activity.reported_repurchases_cash
    if activity.capital_method == "share_change_par":
        if not _known(activity.net_share_change) or not _nonnegative(activity.issuance_price_assumption):
            return None
        if activity.fees is not None and not _nonnegative(activity.fees):
            return None
        amount = activity.net_share_change * activity.issuance_price_assumption
        amount -= activity.fees if activity.fees is not None else 0.0
        return amount if _known(amount) else None
    if activity.capital_method != "modeled":
        return None
    if not _nonnegative(activity.issued_shares) or not _nonnegative(activity.repurchased_shares):
        return None
    if activity.issued_shares == 0:
        issuance = 0.0
    elif _nonnegative(activity.issuance_price_assumption):
        issuance = activity.issued_shares * activity.issuance_price_assumption
    else:
        return None
    if activity.repurchased_shares == 0:
        repurchases = 0.0
    else:
        vwap = weekly_vwap(activity.prior_week_trades) if activity.prior_week_trades is not None else activity.prior_week_vwap
        if not _nonnegative(vwap):
            return None
        repurchases = activity.repurchased_shares * vwap
    if activity.fees is not None and not _nonnegative(activity.fees):
        return None
    return issuance - repurchases - (activity.fees if activity.fees is not None else 0.0)


def calculate_preferred_capital(activities: tuple[PreferredActivity, ...]) -> float | None:
    if not activities:
        return None
    amounts = tuple(preferred_activity_capital(activity) for activity in activities)
    if not all(_known(amount) for amount in amounts):
        return None
    return sum(amounts)


def calculate_company(company: Company, current_btc_price: float | None,
                      prior_btc_price: float | None) -> CompanyMetrics:
    current, prior = company.current, company.prior
    bitcoin, previous_bitcoin = btc_value(current, current_btc_price), btc_value(prior, prior_btc_price)
    nav, previous_nav = net_treasury_nav(current, current_btc_price), net_treasury_nav(prior, prior_btc_price)
    nav_per_share = _ratio(nav, current.effective_common_shares)
    previous_nav_per_share = _ratio(previous_nav, prior.effective_common_shares)
    sats = _ratio(current.btc_holdings, current.effective_common_shares)
    previous_sats = _ratio(prior.btc_holdings, prior.effective_common_shares)
    sats = None if sats is None else sats * 100_000_000.0
    previous_sats = None if previous_sats is None else previous_sats * 100_000_000.0
    amplification, previous_amplification = _ratio(bitcoin, nav), _ratio(previous_bitcoin, previous_nav)
    preferred_ratio, previous_preferred_ratio = _ratio(current.preferred_claims, bitcoin), _ratio(prior.preferred_claims, previous_bitcoin)
    preferred_pct = None if preferred_ratio is None else preferred_ratio * 100.0
    previous_preferred_pct = None if previous_preferred_ratio is None else previous_preferred_ratio * 100.0
    # Reprice prior BTC, securities and any foreign-currency preferred claims.
    # A combined reserve always needs an explicit current-price valuation.
    prior_repriced_securities = company.prior_securities_at_current_prices
    prior_repriced_liquid = None
    has_combined_reserve = prior.combined_liquid_assets is not None
    if has_combined_reserve:
        prior_repriced_liquid = company.prior_liquid_assets_at_current_prices
        # Preserve any erroneous separate balances so ambiguity is rejected.
        prior_repriced_securities = prior.marketable_securities
    elif prior.marketable_securities == 0 and prior_repriced_securities is None:
        prior_repriced_securities = 0.0
    prior_repriced_preferred = company.prior_preferred_claims_at_current_prices
    if prior_repriced_preferred is None:
        prior_repriced_preferred = prior.preferred_claims
    prior_at_current_prices = Snapshot(
        prior.btc_holdings, prior.effective_common_shares, prior.cash,
        prior_repriced_securities, prior.debt_principal, prior_repriced_preferred,
        combined_liquid_assets=prior_repriced_liquid,
    )
    previous_constant_nav = (
        None if has_combined_reserve and (
            prior_repriced_liquid is None or liquid_assets(prior) is None
        ) else net_treasury_nav(prior_at_current_prices, current_btc_price)
    )
    previous_constant_per_share = _ratio(previous_constant_nav, prior.effective_common_shares)
    disclosed_issuance_cash = common_issuance_cash(company.common_capital)
    disclosed_common_capital = calculate_common_capital(company.common_capital)
    if company.common_capital_method == "reported_atm":
        # Scope is the disclosed ATM program only. Do not imply that proceeds
        # include warrant exercises or add unrelated financing to this total.
        activity = company.common_capital
        disclosed_issuance_cash = (activity.issuance_proceeds_after_fees
                                  if _nonnegative(activity.issuance_proceeds_after_fees) else None)
        disclosed_common_capital = (disclosed_issuance_cash - activity.buybacks_cash
                                   if _known(disclosed_issuance_cash) and _nonnegative(activity.buybacks_cash)
                                   else None)
    equity_vwap = common_equity_vwap(company)
    common_capital_estimated = company.common_capital_method == "share_change_vwap"
    selected_common_capital = (estimate_common_capital(company, equity_vwap)
                               if common_capital_estimated else disclosed_common_capital)
    return CompanyMetrics(
        btc_value=bitcoin,
        net_nav=nav,
        nav_per_share=nav_per_share,
        price_to_nav=_ratio(company.stock_price, nav_per_share),
        net_common_capital=selected_common_capital,
        common_capital_estimated=common_capital_estimated,
        common_equity_vwap=equity_vwap,
        disclosed_net_common_capital=disclosed_common_capital,
        common_issuance_cash=disclosed_issuance_cash,
        common_buybacks_cash=company.common_capital.buybacks_cash,
        net_preferred_capital=calculate_preferred_capital(company.preferred_activity),
        preferred_fees_supplied=any(activity.capital_method in ("modeled", "share_change_par") and activity.fees is not None
                                    for activity in company.preferred_activity),
        effective_common_shares=current.effective_common_shares,
        shares_change=_difference(current.effective_common_shares, prior.effective_common_shares),
        shares_change_pct=_percentage_change(current.effective_common_shares, prior.effective_common_shares),
        sats_per_share=sats,
        sats_change_pct=_percentage_change(sats, previous_sats),
        btc_holdings=current.btc_holdings,
        btc_change=_difference(current.btc_holdings, prior.btc_holdings),
        weekly_btc_purchases=company.weekly_btc_purchases,
        constant_price_nav_change_pct=_percentage_change(nav_per_share, previous_constant_per_share),
        net_btc_amplification=amplification,
        amplification_change=_difference(amplification, previous_amplification),
        preferred_to_btc_pct=preferred_pct,
        preferred_to_btc_change_pp=_difference(preferred_pct, previous_preferred_pct),
        preferred_claims_change=_difference(current.preferred_claims, prior.preferred_claims),
        prior_net_nav=previous_nav,
        prior_nav_per_share=previous_nav_per_share,
        prior_nav_per_share_at_current_prices=previous_constant_per_share,
        prior_net_btc_amplification=previous_amplification,
        prior_preferred_to_btc_pct=previous_preferred_pct,
        preferred_capital_reported=bool(company.preferred_activity) and all(
            activity.capital_method == "reported" for activity in company.preferred_activity
        ),
    )
