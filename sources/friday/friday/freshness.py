"""Pure display projections: cached history never becomes a current reading.

Only copied summary containers are changed. Historical series are retained as
read-only inputs; the authoritative snapshot and its frozen export stay intact.
Fetch validation and observation age are separate: a freshly checked provider
may legitimately report the same dated close or completed daily observation.
"""
from datetime import datetime
import math
from numbers import Real


TICKERS = ("BTC", "MSTR", "ASST")
LIQUIDITY_TICKERS = ("MSTR", "ASST", "STRC", "SATA")


def _number(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _stamp(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _empty_trend(ticker):
    names = ("200W",) if ticker == "BTC" else ("50D", "200D")
    return {"series": [], "averages": {name: {"value": None, "extension_pct": None} for name in names},
            "price": None, "price_as_of": None, "latest_quote": None, "live_point": None}


def _empty_panel():
    return {"mode": "latest", "period": {"end": None, "week_ending": None, "as_of": None},
            "header": {"btc": {}, "companies": {}}, "treasury": [],
            "liquidity": [{"ticker": ticker, "weekly_series": []} for ticker in LIQUIDITY_TICKERS],
            "trends": {ticker: _empty_trend(ticker) for ticker in TICKERS},
            "live_trends": {ticker: _empty_trend(ticker) for ticker in TICKERS},
            **{name: {"series": []} for name in ("sentiment", "supply_loss", "live_sentiment", "live_supply_loss")}}


def _numeric_summary(row):
    """Mask scalar readings without changing dated historical arrays/metadata."""
    return {key: None if isinstance(value, Real) and not isinstance(value, bool) else value
            for key, value in row.items()}


def _indicator(indicator, state):
    result = dict(indicator)
    if state != "ready":
        result = _numeric_summary(result)
        for field in ("value", "change", "as_of", "observation_date", "classification", "source_timestamp",
                      "previous_value", "previous_as_of", "btc", "profit_pct", "profit_btc",
                      "latest_observation", "live_point"):
            result[field] = None
        result["value_basis"] = "Current reading loading" if state == "loading" else "Current reading unavailable"
    result["_reading_state"] = state
    return result


def _valid_quote(quote, fetched_at):
    if not isinstance(quote, dict) or not _number(quote.get("price")) or quote["price"] <= 0:
        return False
    observed, fetched = _stamp(quote.get("as_of")), _stamp(fetched_at)
    return observed is not None and (fetched is None or observed <= fetched)


def _trend(trend, state, *, quote_ready, history_ready):
    result = dict(trend)
    result["averages"] = {name: dict(value) for name, value in (trend.get("averages") or {}).items()}
    if not quote_ready:
        for field in ("price", "price_as_of", "as_of", "latest_quote", "live_point"):
            result[field] = None
        result["price_basis"] = "Current quote loading" if state == "loading" else "Current quote unavailable"
    for average in result["averages"].values():
        if not history_ready:
            average["value"] = None
            average["as_of"] = None
        if not quote_ready or not history_ready:
            average["extension_pct"] = None
    result["_reading_state"] = state
    return result


def display_panel(snapshot_or_None, *, pending=False, failed=False):
    """Return a fresh-reading view while retaining exact cached chart history.

    Pending/failed requests hide every displayed summary, including Friday
    summaries. Once settled, Friday summaries remain authoritative and live
    fields are admitted separately by their provider outcome. Callers must
    use the original snapshot for exports, and suppress any chart-generated
    current callout when ``_reading_state`` is not ``ready``.
    """
    snapshot = snapshot_or_None or {}
    data = snapshot.get("data") or {}
    original = snapshot.get("panel") or _empty_panel()
    result = dict(original)
    demo = data.get("mode", snapshot.get("mode", original.get("mode"))) == "demo"
    blocked = pending or failed or snapshot_or_None is None
    blocked_state = "loading" if pending else "unavailable"
    meta = data.get("refresh_meta") or {}

    if blocked:
        header = original.get("header") or {}
        result["header"] = {**header,
                            "btc": _numeric_summary(header.get("btc") or {}),
                            "companies": {ticker: _numeric_summary(row) for ticker, row in (header.get("companies") or {}).items()}}
        result["treasury"] = [_numeric_summary(row) for row in original.get("treasury", [])]
        result["liquidity"] = [_numeric_summary(row) for row in original.get("liquidity", [])]

    trends = original.get("live_trends") or original.get("trends") or {}
    result["live_trends"] = {}
    for ticker in TICKERS:
        trend = trends.get(ticker) or _empty_trend(ticker)
        quote_ready = not blocked and (demo or _valid_quote(trend.get("latest_quote"), data.get("fetched_at")))
        history_ready = not blocked and (demo or (meta.get("histories") or {}).get(ticker, {}).get("status") == "validated")
        state = blocked_state if blocked else "ready" if quote_ready else "unavailable"
        result["live_trends"][ticker] = _trend(trend, state, quote_ready=quote_ready, history_ready=history_ready)

    for live, frozen, provider in (("live_sentiment", "sentiment", "sentiment"),
                                    ("live_supply_loss", "supply_loss", "supply")):
        indicator = original.get(live) or original.get(frozen) or {"series": []}
        validated = demo or (meta.get("indicators") or {}).get(provider, {}).get("status") == "validated"
        available = validated and _number(indicator.get("value")) and 0 <= indicator["value"] <= 100
        state = blocked_state if blocked else "ready" if available else "unavailable"
        result[live] = _indicator(indicator, state)
    return result
