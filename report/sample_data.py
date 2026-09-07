"""Fictional interface fixtures, never a source of live financial information."""

from .models import CommonCapital, Company, PreferredActivity, Report, Snapshot


def sample_report() -> Report:
    """Return the user's illustrative Monday edition and saved prior quantities."""
    strategy = Company(
        name="Strategy",
        ticker="MSTR",
        stock_price=150.0,
        quote_session="PRE-MARKET",
        quote_timestamp="08:59:55 ET · illustrative",
        current=Snapshot(
            btc_holdings=845_000.0,
            effective_common_shares=420_000_000.0,
            cash=6_700_000_000.0,
            marketable_securities=0.0,
            debt_principal=6_750_000_000.0,
            preferred_claims=14_800_000_000.0,
        ),
        prior=Snapshot(
            btc_holdings=840_400.0,
            effective_common_shares=416_000_000.0,
            cash=6_670_000_000.0,
            marketable_securities=0.0,
            debt_principal=6_750_000_000.0,
            preferred_claims=14_960_000_000.0,
        ),
        common_capital=CommonCapital(
            issuance_proceeds_after_fees=600_000_000.0,
            buybacks_cash=0.0,
            issuance_includes_warrants=True,
            # No separately disclosed warrant exercise cash in this fixture.
            separately_reported_warrant_cash=None,
        ),
        preferred_activity=(
            PreferredActivity(
                series="STRC",
                issued_shares=0.0,
                repurchased_shares=1_600_000.0,
                prior_week_vwap=93.75,
            ),
            PreferredActivity(
                series="All other preferred series",
                issued_shares=0.0,
                repurchased_shares=0.0,
                issuance_price_assumption=None,
            ),
        ),
        prior_securities_at_current_prices=0.0,
    )
    strive = Company(
        name="Strive",
        ticker="ASST",
        stock_price=28.0,
        quote_session="PRE-MARKET",
        quote_timestamp="08:59:42 ET · illustrative",
        current=Snapshot(
            btc_holdings=23_200.0,
            effective_common_shares=94_000_000.0,
            cash=185_000_000.0,
            # STRC investment is a separate asset, never part of cash.
            marketable_securities=50_000_000.0,
            debt_principal=0.0,
            preferred_claims=910_000_000.0,
        ),
        prior=Snapshot(
            btc_holdings=21_400.0,
            effective_common_shares=90_400_000.0,
            cash=172_000_000.0,
            marketable_securities=50_000_000.0,
            debt_principal=0.0,
            preferred_claims=830_000_000.0,
        ),
        common_capital=CommonCapital(
            issuance_proceeds_after_fees=None,
            buybacks_cash=None,
            issuance_includes_warrants=None,
        ),
        preferred_activity=(
            PreferredActivity(
                series="SATA",
                issued_shares=800_000.0,
                repurchased_shares=0.0,
            ),
        ),
        # The supplied sample holds securities prices constant across editions.
        prior_securities_at_current_prices=50_000_000.0,
        common_capital_method="share_change_vwap",
        # User-selected illustrative assumption, not a historical market quote.
        prior_week_equity_vwap=27.50,
    )
    return Report(
        title="The Monday Capital Report",
        report_time="Monday, September 7, 2026 · 9:00 a.m. ET",
        illustrative=True,
        current_btc_price=80_000.0,
        prior_btc_price=78_000.0,
        btc_quote_timestamp="08:59:59 ET · illustrative",
        companies=(strategy, strive),
    )
