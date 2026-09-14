"""Calendar-selected, source-dated baselines for future quarterly rollovers."""
from datetime import date, timedelta
import json
from math import isfinite
from pathlib import Path

from .models import Snapshot

BASELINES = Path(__file__).resolve().parents[1] / "data" / "period-baselines.json"


def baseline_dates(measurement: date) -> dict[str, str]:
    quarter_start = date(measurement.year, 3 * ((measurement.month - 1) // 3) + 1, 1)
    return {"QTD": (quarter_start - timedelta(days=1)).isoformat(),
            "YTD": date(measurement.year - 1, 12, 31).isoformat()}


def dated_baseline(ticker: str, balance_date: str, eurusd: float, strc: float) -> Snapshot | None:
    if not BASELINES.exists():
        return None
    payload = json.loads(BASELINES.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        raise ValueError("Unsupported period baseline schema")
    row = payload.get("balances", {}).get(ticker, {}).get(balance_date)
    if row is None:
        return None
    if row.get("balance_date") != balance_date or not row.get("sources") or not row.get("basis"):
        raise ValueError("Period baseline requires its exact balance date, sources and basis")

    def number(key):
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
            raise ValueError(f"Invalid {ticker} {balance_date} baseline {key}")
        return value

    holdings, shares = number("btc_holdings"), number("effective_common_shares")
    if shares <= 0:
        raise ValueError("Period baseline needs a positive basic share denominator")
    claims = number("preferred_claims_usd") + number("preferred_claims_eur") * eurusd
    debt = number("debt_principal")
    if ticker == "MSTR":
        return Snapshot(holdings, shares, None, None, debt, claims,
                        combined_liquid_assets=number("combined_liquid_assets"))
    if ticker == "ASST":
        return Snapshot(holdings, shares, number("cash"), number("held_strc_shares") * strc, debt, claims)
    raise ValueError("Unsupported baseline issuer")
