"""Manually verified August 31 replay; see HISTORICAL_SOURCES.md for provenance.

Reported balances and explicitly marked valuation estimates are kept separate
from financing flows. This is a reconstruction, not a live data feed or an
unchanged archive of information available at the original 9am cutoff.
"""
from .models import CommonCapital, Company, PreferredActivity, Report, Snapshot
from .vwap_store import load_estimate
from .historical_claims import (
    STRATEGY_DEBT_CARRYFORWARD, strategy_preferred_claims, strive_preferred_claims,
)
from datetime import date


def historical_report() -> Report:
    equity_estimate = load_estimate("ASST", date(2026, 8, 31))
    return Report(
        title="The Monday Capital Report",
        report_time="Monday, August 31, 2026 · 9:00 AM ET",
        illustrative=False,
        edition_id="2026-08-31",
        data_label="HISTORICAL RECONSTRUCTION · ≈ ESTIMATED",
        subtitle="Week of August 24–30",
        footer="≈ Estimates · Capital estimates before fees. Definitions, assumptions & sources below the report.",
        current_btc_price=78_414.14,
        prior_btc_price=78_976.18,
        btc_quote_timestamp="Aug 31 · 8:30 AM ET",
        companies=(
            Company(
                name="Strategy", ticker="MSTR", stock_price=127.31,
                quote_session="PRIOR CLOSE", quote_timestamp="Aug 28 · 4:00 PM ET",
                # Company table as of Aug 30, rounded to thousands. Availability
                # at the original 9am cutoff cannot be established retrospectively.
                current=Snapshot(
                    845_050, 420_483_000, None, None, STRATEGY_DEBT_CARRYFORWARD,
                    strategy_preferred_claims("current"), combined_liquid_assets=6_710_000_000,
                ),
                prior=Snapshot(
                    840_447, 415_929_000, None, None, STRATEGY_DEBT_CARRYFORWARD,
                    strategy_preferred_claims("prior"), combined_liquid_assets=6_690_000_000,
                ),
                # Reserve Treasury bills already belong to combined liquidity.
                # An explicit constant-USD assumption avoids counting them twice.
                prior_liquid_assets_at_current_prices=6_690_000_000,
                prior_preferred_claims_at_current_prices=strategy_preferred_claims("prior", at_current_fx=True),
                valuation_estimated=True,
                preferred_claims_estimated=True,
                valuation_note="≈ Basic common shares · after debt & preferred claims",
                common_capital=CommonCapital(
                    602_800_000, 0, issued_shares=4_531_421, repurchased_shares=0,
                    proceeds_basis="Reported ATM proceeds · net of commissions",
                ),
                common_capital_method="reported_atm",
                preferred_activity=(
                    PreferredActivity(
                        "STRC", 0, 1_557_177, issuance_price_assumption=None, capital_method="reported",
                        reported_issuance_proceeds=0, reported_repurchases_cash=151_800_000,
                    ),
                    PreferredActivity(
                        "STRF / STRK / STRD", 0, 0, issuance_price_assumption=None, capital_method="reported",
                        reported_issuance_proceeds=0, reported_repurchases_cash=0,
                    ),
                ),
                weekly_btc_purchases=4_603,
                share_basis_note="A + B · rounded to 1,000",
            ),
            Company(
                name="Strive", ticker="ASST", stock_price=21.74,
                quote_session="PRIOR CLOSE", quote_timestamp="Aug 28 · 4:00 PM ET",
                current=Snapshot(23_156, 93_262_570, 183_500_000, 49_152_000, 0, strive_preferred_claims("current")),
                prior=Snapshot(21_356, 89_683_423, 171_900_000, 48_571_000, 0, strive_preferred_claims("prior")),
                valuation_estimated=True,
                preferred_claims_estimated=True,
                valuation_note="≈ Basic common shares · after debt & preferred claims",
                common_capital=CommonCapital(None, None),
                common_capital_method="share_change_vwap",
                prior_week_equity_vwap=equity_estimate["value"] if equity_estimate else None,
                equity_vwap_note=(
                    f"{equity_estimate['session_start']} to {equity_estimate['session_end']} · 1-minute VWAP estimate · before fees"
                    if equity_estimate else None
                ),
                # User-requested proxy; this does not establish gross issuance
                # or change the separately reconstructed liquidation claim.
                preferred_activity=(PreferredActivity(
                    "SATA", None, None, issuance_price_assumption=100,
                    capital_method="share_change_par", net_share_change=9_073_914 - 8_270_815,
                ),),
                preferred_activity_notes=(
                    "+803,099 net shares × $100 assumed · before fees",
                    "Share-change estimate; actual financing cash not disclosed",
                ),
                # Both weeks held 505,000 STRC shares; reprice prior at latest mark.
                prior_securities_at_current_prices=49_152_000,
                weekly_btc_purchases=1_800,
            ),
        ),
    )
