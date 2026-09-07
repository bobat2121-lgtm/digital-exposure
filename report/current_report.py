"""Current market marks on the explicitly dated August balance snapshots.

Refreshes prices only. It does not roll forward financing, share counts or
native-currency preferred liabilities beyond the last verified disclosures.
"""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from .current_prices import load_current_prices
from .historical_claims import strategy_claim_components
from .historical_data import historical_report
from .models import Report

ET = ZoneInfo("America/New_York")
ACTIVITY_EDITION = "2026-08-31"


def quote_time(iso_timestamp: str) -> str:
    timestamp = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00")).astimezone(ET)
    return f"{timestamp:%b} {timestamp.day} · {timestamp.strftime('%I:%M %p').lstrip('0')} ET"


def _claims_at_fx(edition: str, fx: float) -> float:
    return float(sum(row["estimated_claims_usd"] for row in
                     strategy_claim_components(edition, usd_per_eur=Decimal(str(fx))).values()))


def current_report(prices: dict | None = None) -> Report:
    prices = load_current_prices() if prices is None else prices
    if prices is None:
        raise ValueError("No saved current prices. Use Refresh prices to fetch a complete snapshot.")
    quotes = prices["quotes"]
    base = historical_report()
    strategy, strive = base.companies
    fx = quotes["EURUSD=X"]["price"]
    current_strc_value = 505_000 * quotes["STRC"]["price"]
    refreshed = datetime.fromisoformat(prices["fetched_at"].replace("Z", "+00:00")).astimezone(ET)
    companies = (
        replace(
            strategy, stock_price=quotes["MSTR"]["price"], quote_session="LAST PRICE",
            quote_timestamp=quote_time(quotes["MSTR"]["as_of"]),
            current=replace(strategy.current, preferred_claims=_claims_at_fx("current", fx)),
            prior_preferred_claims_at_current_prices=_claims_at_fx("prior", fx),
        ),
        replace(
            strive, stock_price=quotes["ASST"]["price"], quote_session="LAST PRICE",
            quote_timestamp=quote_time(quotes["ASST"]["as_of"]),
            current=replace(strive.current, marketable_securities=current_strc_value),
            prior_securities_at_current_prices=current_strc_value,
        ),
    )
    return replace(
        base, edition_id="current-prices", companies=companies,
        report_time=f"Updated {refreshed:%b} {refreshed.day}, {refreshed.year} · {refreshed.strftime('%I:%M %p').lstrip('0')} ET",
        data_label="CURRENT PRICE DEMO · ≈ ESTIMATED",
        subtitle="Balance dates: Strategy Aug 30 · Strive Aug 28",
        capital_period_label="Capital · Aug 24–30",
        prior_comparison_date="Aug 24",
        footer="Latest available market quotes · dated balances held fixed · ≈ estimates. Definitions & sources below the report.",
        current_btc_price=quotes["BTC-USD"]["price"],
        btc_quote_timestamp=quote_time(quotes["BTC-USD"]["as_of"]),
    )


def quote_rows(prices: dict) -> list[dict[str, str]]:
    return [{"Instrument": symbol, "Price (USD)": f"{quote['price']:,.5f}" if symbol == "EURUSD=X" else f"{quote['price']:,.2f}",
             "Quote time (ET)": quote_time(quote["as_of"]), "Source": quote["source_url"]}
            for symbol, quote in prices["quotes"].items()]
