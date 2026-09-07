"""Provider-neutral inputs and calculated values for the illustrative report.

Money is in US dollars; percentages in calculated results use percentage units.
None means an input was not disclosed. A reported zero must be explicit.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    btc_holdings: float | None
    effective_common_shares: float | None
    cash: float | None
    marketable_securities: float | None
    debt_principal: float | None
    preferred_claims: float | None
    # Exclusive alternative when the issuer discloses cash and securities as
    # one reserve. Leave both separate asset fields unknown to avoid overlap.
    combined_liquid_assets: float | None = None


@dataclass(frozen=True)
class CommonCapital:
    issuance_proceeds_after_fees: float | None
    buybacks_cash: float | None
    # True: the issuance total already includes all warrant-exercise cash.
    # False: separately_reported_warrant_cash must be supplied, even if zero.
    # None: scope is unknown, so total net common capital is not calculable.
    issuance_includes_warrants: bool | None = None
    separately_reported_warrant_cash: float | None = None
    issued_shares: float | None = None
    repurchased_shares: float | None = None
    proceeds_basis: str = "Disclosed cash proceeds after fees"


@dataclass(frozen=True)
class Trade:
    price: float
    volume: float


@dataclass(frozen=True)
class PreferredActivity:
    series: str
    issued_shares: float | None
    repurchased_shares: float | None
    issuance_price_assumption: float | None = 100.0
    # Market trading data from the prior reporting week; these volumes never
    # establish how many shares the company itself issued or repurchased.
    prior_week_trades: tuple[Trade, ...] | None = None
    prior_week_vwap: float | None = None
    fees: float | None = None
    # Reported amounts retain the issuer's cash basis. Prices and share counts
    # are supporting disclosures; they never replace the reported cash amounts.
    capital_method: str = "modeled"
    reported_issuance_proceeds: float | None = None
    reported_repurchases_cash: float | None = None
    # Signed outstanding-share change for an explicit par-value capital proxy.
    # It does not establish gross issuance, repurchases or disclosed cash flows.
    net_share_change: float | None = None


@dataclass(frozen=True)
class Company:
    name: str
    ticker: str
    stock_price: float | None
    quote_session: str
    quote_timestamp: str
    current: Snapshot
    prior: Snapshot
    common_capital: CommonCapital
    preferred_activity: tuple[PreferredActivity, ...]
    # Explicitly mark-to-current-price value of prior securities holdings.
    # Do not substitute the old edition's fair value without a price assumption.
    prior_securities_at_current_prices: float | None = None
    weekly_btc_purchases: float | None = None
    # Share-change VWAP is a signed financing proxy, not disclosed cash proceeds.
    common_capital_method: str = "disclosed_cash"
    prior_week_equity_vwap: float | None = None
    prior_week_equity_trades: tuple[Trade, ...] | None = None
    share_basis_note: str = "Class A + Class B · effective shares"
    preferred_activity_notes: tuple[str, ...] = ()
    equity_vwap_note: str | None = None
    prior_liquid_assets_at_current_prices: float | None = None
    prior_preferred_claims_at_current_prices: float | None = None
    valuation_estimated: bool = False
    preferred_claims_estimated: bool = False
    valuation_note: str | None = None


@dataclass(frozen=True)
class Report:
    title: str
    report_time: str
    illustrative: bool
    current_btc_price: float | None
    prior_btc_price: float | None
    btc_quote_timestamp: str
    companies: tuple[Company, ...]
    edition_id: str = "illustrative"
    data_label: str | None = None
    footer: str | None = None
    subtitle: str | None = None
    capital_period_label: str = "Capital this week"
    prior_comparison_date: str | None = None


@dataclass(frozen=True)
class CompanyMetrics:
    btc_value: float | None
    net_nav: float | None
    nav_per_share: float | None
    price_to_nav: float | None
    net_common_capital: float | None
    common_capital_estimated: bool
    common_equity_vwap: float | None
    disclosed_net_common_capital: float | None
    common_issuance_cash: float | None
    common_buybacks_cash: float | None
    net_preferred_capital: float | None
    preferred_fees_supplied: bool
    effective_common_shares: float | None
    shares_change: float | None
    shares_change_pct: float | None
    sats_per_share: float | None
    sats_change_pct: float | None
    btc_holdings: float | None
    btc_change: float | None
    weekly_btc_purchases: float | None
    constant_price_nav_change_pct: float | None
    net_btc_amplification: float | None
    amplification_change: float | None
    preferred_to_btc_pct: float | None
    preferred_to_btc_change_pp: float | None
    preferred_claims_change: float | None
    prior_net_nav: float | None
    prior_nav_per_share: float | None
    prior_nav_per_share_at_current_prices: float | None
    prior_net_btc_amplification: float | None
    prior_preferred_to_btc_pct: float | None
    preferred_capital_reported: bool = False
