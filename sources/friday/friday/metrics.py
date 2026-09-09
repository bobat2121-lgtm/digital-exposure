"""Point-in-time calculations for the Friday Bitcoin and Digital Credit panel.

All percentages are expressed in percentage points (12.5 means 12.5%).
Missing or incomplete observations produce None, never a fabricated zero.
Company amounts use the Monday report's basic-share, net-treasury convention.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
# Nasdaq marketplace effective date, after the Sep 12 combination close:
# https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2025-507
ASST_REGIME_START = date(2025, 9, 15)
TICKERS = ("MSTR", "ASST", "STRC", "SATA")


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> date | None:
    try:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (TypeError, ValueError):
        return None


def _calendar():
    try:
        import exchange_calendars

        return exchange_calendars.get_calendar("XNYS")
    except ImportError:
        return None


def _sessions(start: date, end: date, calendar: Any) -> list[date]:
    if calendar is not None:
        return [stamp.date() for stamp in calendar.sessions_in_range(start.isoformat(), end.isoformat())]
    return [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]


def _close(day: date, calendar: Any) -> datetime:
    if calendar is not None:
        return calendar.session_close(day.isoformat()).to_pydatetime()
    return datetime.combine(day, time(16), NY)


def completed_week(now: datetime, calendar: Any = None) -> dict[str, Any]:
    """Select the last fully closed exchange week, including holiday short weeks.

    A Good Friday week completes at Thursday's close; Thanksgiving week uses
    Friday's early close. All close comparisons use aware instants.
    """
    calendar = _calendar() if calendar is None else calendar
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    monday = now.astimezone(NY).date()
    monday -= timedelta(days=monday.weekday())
    sessions = _sessions(monday, monday + timedelta(days=4), calendar)
    if not sessions or now < _close(sessions[-1], calendar):
        monday -= timedelta(days=7)
        sessions = _sessions(monday, monday + timedelta(days=4), calendar)
    previous_start = monday - timedelta(days=7)
    previous = _sessions(previous_start, previous_start + timedelta(days=4), calendar)
    return {
        "start": monday.isoformat(),
        "end": sessions[-1].isoformat(),
        "week_ending": (monday + timedelta(days=4)).isoformat(),
        "previous_start": previous_start.isoformat(),
        "previous_end": previous[-1].isoformat(),
        "as_of": _close(sessions[-1], calendar).isoformat(),
        "calendar": "XNYS" if calendar is not None else "weekday fallback (holidays unverified)",
        "sessions": [day.isoformat() for day in sessions],
        "previous_sessions": [day.isoformat() for day in previous],
        "price_alignment": "Daily close proxy; BTC daily candle is not the equity-close timestamp",
    }


def _clean_prices(rows: list[dict[str, Any]], end: date) -> dict[str, dict[str, Any]]:
    cleaned = {}
    for row in rows:
        day = _date(row.get("date"))
        close = _number(row.get("close"))
        if day is not None and day <= end and close is not None and close > 0:
            cleaned[day.isoformat()] = {**row, "date": day.isoformat(), "close": close}
    return dict(sorted(cleaned.items()))


def _change(end: float | None, start: float | None) -> float | None:
    return (end / start - 1) * 100 if end is not None and start is not None and start > 0 else None


def _mark(row: dict[str, Any] | None, equity: bool = False) -> float | None:
    return _number(row.get("equity_close" if equity else "close")) if row else None


def _equity_marks(prices: dict[str, dict], marks: dict, period: dict, calendar: Any) -> dict:
    """Validate marks against each actual exchange close, including 13:00 days.

    The current Friday BTC UTC daily candle is still open at the equity close.
    A separately timestamped intraday mark can supply the weekly endpoint without
    fabricating that day's daily close or contaminating the SMA series.
    """
    result = {day: dict(row) for day, row in prices.items()}
    for day in [period["previous_end"], *period["sessions"]]:
        expected = _close(_date(day), calendar)
        row = result.setdefault(day, {"date": day})
        mark = marks.get(day, {})
        candidates = [
            (mark.get("close"), mark.get("as_of")),
            (mark.get("close_early"), mark.get("as_of_early")),
            (row.get("equity_close"), row.get("equity_close_at")),
        ]
        row.pop("equity_close", None)
        row.pop("equity_close_at", None)
        for value, stamp in candidates:
            value, stamp = _number(value), _datetime(stamp)
            if value is not None and value > 0 and stamp is not None and stamp == expected:
                row.update(equity_close=value, equity_close_at=stamp.isoformat())
                break
    return result


def _liquidity(ticker: str, prices: dict[str, dict], period: dict, calendar: Any) -> dict:
    def aggregate(sessions: list[str]) -> dict:
        series = []
        estimated = False
        for day in sessions:
            row = prices.get(day)
            if not row:
                continue
            volume = _number(row.get("volume"))
            vwap = _number(row.get("vwap"))
            if volume is None or volume < 0:
                continue
            exact = vwap is not None and vwap > 0
            dollars = volume * (vwap if exact else row["close"])
            estimated = estimated or not exact
            series.append({"date": day, "dollars": dollars})
        complete = len(series) == len(sessions)
        observed = sum(row["dollars"] for row in series) if series else None
        return {"dollars": observed if complete else None, "observed_dollars": observed, "complete": complete, "estimated": estimated, "observed_sessions": len(series), "series": series}

    current, previous = aggregate(period["sessions"]), aggregate(period["previous_sessions"])
    history = []
    monday = _date(period["start"])
    # The extra thirteenth week supplies the first displayed week's comparison.
    for offset in range(12, -1, -1):
        start = monday - timedelta(weeks=offset)
        friday = start + timedelta(days=4)
        sessions = [day.isoformat() for day in _sessions(start, friday, calendar)]
        week = aggregate(sessions)
        history.append({
            "week_ending": friday.isoformat(), "date": friday.isoformat(),
            "dollars": week["dollars"],
            "change_pct": _change(week["dollars"], history[-1]["dollars"] if history else None),
            "complete": week["complete"], "estimated": week["estimated"],
            "observed_sessions": week["observed_sessions"], "expected_sessions": len(sessions),
        })
    prior_four = history[-5:-1]
    average = sum(row["dollars"] for row in prior_four) / 4 if len(prior_four) == 4 and all(row["complete"] for row in prior_four) else None
    return {
        "ticker": ticker,
        **current,
        "previous_dollars": previous["dollars"],
        "previous_complete": previous["complete"],
        "change_pct": _change(current["dollars"], previous["dollars"]),
        "expected_sessions": len(period["sessions"]),
        "volume_basis": "Estimated: daily close × shares traded" if current["estimated"] else "Daily VWAP × shares traded",
        "weekly_series": history[-12:],
        "prior_4week_average_dollars": average,
        "vs_4week_average_pct": _change(current["dollars"], average),
    }


def _latest_monday_inputs(company: dict) -> bool:
    """An explicit bridge marker admits later, genuinely dated disclosures."""
    return (company.get("allow_post_friday_disclosure") is True
            and company.get("publication_basis") == "latest_monday_disclosures")


def _publication_eligible(company: dict, close_at: datetime) -> bool:
    disclosed = _datetime(company.get("disclosed_at"))
    return disclosed is not None and (disclosed <= close_at or _latest_monday_inputs(company))


def _baseline(company: dict, close_at: datetime) -> tuple[bool, str | None]:
    disclosed = _datetime(company.get("disclosed_at"))
    if disclosed is None:
        return False, "Dated company disclosure unavailable"
    if disclosed > close_at and not _latest_monday_inputs(company):
        return False, "Available company snapshot was disclosed after this Friday; historical NAV withheld"
    for key in ("btc_held", "cash_usd", "debt_usd", "preferred_usd", "shares"):
        value = _number(company.get(key))
        if value is None or value < 0 or (key == "shares" and value == 0):
            return False, f"Company baseline is missing a valid {key} value"
    securities = _number(company.get("securities_usd", 0))
    if securities is None or securities < 0:
        return False, "Company baseline is missing a valid securities_usd value"
    return True, None


def _nav(company: dict, btc: float | None) -> float | None:
    if btc is None:
        return None
    return (float(company["btc_held"]) * btc + float(company["cash_usd"]) + float(company.get("securities_usd", 0)) - float(company["debt_usd"]) - float(company["preferred_usd"])) / float(company["shares"])


def _treasury(ticker: str, company: dict, btc_prices: dict, equity_prices: dict, period: dict, use_equity: bool) -> dict:
    valid, reason = _baseline(company, _datetime(period["as_of"]))
    eligible = _publication_eligible(company, _datetime(period["as_of"]))
    frozen_balances = {}
    for field in ("btc_held", "cash_usd", "debt_usd", "securities_usd", "preferred_usd"):
        value = _number(company.get(field))
        frozen_balances[field] = value if eligible and value is not None and value >= 0 else None
    start_btc = _mark(btc_prices.get(period["previous_end"]), use_equity)
    end_btc = _mark(btc_prices.get(period["end"]), use_equity)
    if valid and (start_btc is None or end_btc is None):
        valid, reason = False, "BTC price is missing at a required weekly endpoint"
    start_nav = _nav(company, start_btc) if valid else None
    end_nav = _nav(company, end_btc) if valid else None
    start_price = _mark(equity_prices.get(period["previous_end"]))
    end_price = _mark(equity_prices.get(period["end"]))
    premium = _change(end_price, end_nav)
    start_multiple = start_price / start_nav if start_price is not None and start_nav is not None and start_nav > 0 else None
    end_multiple = end_price / end_nav if end_price is not None and end_nav is not None and end_nav > 0 else None
    nav_series = []
    if valid:
        # This is a price-only reconstruction with ONE frozen baseline, not a
        # history of contemporaneously reported company balance sheets.
        for day in [period["previous_end"], *period["sessions"]]:
            nav = _nav(company, _mark(btc_prices.get(day), use_equity))
            if nav is not None:
                nav_series.append({"date": day, "nav_per_share": nav, "premium_pct": _change(_mark(equity_prices.get(day)), nav)})
    return {
        "ticker": ticker,
        **frozen_balances,
        "nav_per_share": end_nav,
        "start_nav_per_share": start_nav,
        "nav_change_pct": _change(end_nav, start_nav),
        "btc_effect_per_share": float(company["btc_held"]) * (end_btc - start_btc) / float(company["shares"]) if valid else None,
        "premium_pct": premium,
        "nav_multiple": end_multiple,
        "start_nav_multiple": start_multiple,
        "nav_multiple_change": end_multiple - start_multiple if end_multiple is not None and start_multiple is not None else None,
        "baseline_disclosed_at": company.get("disclosed_at"),
        "baseline_at": company.get("baseline_at"),
        "publication_basis": "latest_monday_disclosures" if _latest_monday_inputs(company) else "available_by_friday_close",
        "shares": _number(company.get("shares")),
        "share_basis": "basic",
        "estimated_fields": list(company.get("estimated_fields", [])),
        "baseline_notes": list(company.get("notes", [])),
        "baseline_sources": list(company.get("sources", [])),
        "nav_series": nav_series,
        "series_basis": ("Price-only reconstruction using one latest Monday disclosure baseline, including post-Friday disclosures"
                         if _latest_monday_inputs(company) else "Price-only reconstruction using one frozen disclosed baseline"),
        "valid": valid,
        "reason": reason if reason else ("Premium unavailable because estimated common NAV is nonpositive" if end_nav is not None and end_nav <= 0 else None),
    }


def reprice_company_inputs(panel: dict, data: dict, companies: dict) -> dict:
    """Replace company valuations while retaining the exact market snapshot.

    Both weekly endpoints use the same new disclosed quantities. No provider,
    SMA, indicator, liquidity, chart builder or current clock is consulted.
    Unchanged chart/history containers are shared read-only; changed containers
    are new, so neither the authoritative snapshot nor ``companies`` is mutated.
    """
    period = panel["period"]
    end = _date(period["end"])
    wanted = {period["previous_end"], *period["sessions"]}
    prices = {}
    for ticker in ("BTC", "MSTR", "ASST"):
        relevant = [row for row in data.get("prices", {}).get(ticker, [])
                    if (day := _date(row.get("date"))) is not None and day.isoformat() in wanted]
        prices[ticker] = _clean_prices(relevant, end)
    btc = _equity_marks(prices["BTC"], data.get("btc_equity_marks", {}), period, _calendar())
    use_equity = all((_mark(btc.get(day), True) or 0) > 0 for day in (period["previous_end"], period["end"]))
    treasury = [_treasury(ticker, companies.get(ticker, {}), btc, prices[ticker], period, use_equity)
                for ticker in ("MSTR", "ASST")]
    original_header = panel.get("header", {})
    header_companies = dict(original_header.get("companies", {}))
    for row in treasury:
        ticker = row["ticker"]
        header_companies[ticker] = {
            **header_companies.get(ticker, {}),
            **{field: row[field] for field in (
                "nav_per_share", "nav_change_pct", "premium_pct", "nav_multiple",
                "start_nav_multiple", "nav_multiple_change")},
        }
    prior_reasons = {f"{row['ticker']}: {row['reason']}." for row in panel.get("treasury", []) if row.get("reason")}
    notices = [notice for notice in panel.get("notices", []) if notice not in prior_reasons]
    notices.extend(f"{row['ticker']}: {row['reason']}." for row in treasury if row.get("reason"))
    return {**panel, "header": {**original_header, "companies": header_companies},
            "treasury": treasury, "notices": list(dict.fromkeys(notices))}


@lru_cache(maxsize=12)
def _trend_history(ticker: str, history: tuple[tuple, ...]) -> tuple[dict, tuple[dict, ...]]:
    """Cache exact completed-history calculations, never current prices.

    The key contains every relevant date, close and OHLC value. Corrections,
    split-adjusted backfills and chart extrema changes invalidate it even when
    the final date is unchanged. Twelve entries bound retained histories across
    live/frozen cutoffs and refreshes. The internal result is never exposed.
    """
    windows = {"200W": 200} if ticker == "BTC" else {"50D": 50, "200D": 200}
    series = []
    sums = {name: 0.0 for name in windows}
    for index, row in enumerate(history):
        point = {"date": row[0], "close": row[1]}
        for field, value in zip(("open", "high", "low"), row[2:]):
            if value is not None:
                point[field] = value
        for name, count in windows.items():
            sums[name] += row[1]
            if index >= count:
                sums[name] -= history[index - count][1]
            point[f"sma_{name.lower()}"] = sums[name] / count if index + 1 >= count else None
        series.append(point)
    averages = {}
    for name, count in windows.items():
        value = series[-1].get(f"sma_{name.lower()}") if series else None
        averages[name] = {"value": value, "observations": len(history), "required": count, "as_of": history[-1][0] if history else None,
                          "first_valid_at": history[count - 1][0] if len(history) >= count else None,
                          "window_start": history[-count][0] if len(history) >= count else None}
    return averages, tuple(series)


def _trends(ticker: str, prices: dict[str, dict], end: str) -> dict:
    history = []
    for row in prices.values():
        # Friday daily BTC closes form a consistently sampled series, separate
        # from the aligned weekly 4pm performance marks.
        if ticker == "BTC" and _date(row["date"]).weekday() != 4:
            continue
        ohlc = []
        for field in ("open", "high", "low"):
            value = _number(row.get(field))
            ohlc.append(value if value is not None and value > 0 else None)
        history.append((row["date"], row["close"], *ohlc))
    cached_averages, cached_series = _trend_history(ticker, tuple(history))
    current = _mark(prices.get(end))
    # These records contain scalar values only. Copy each record and container
    # rather than deepcopy every scalar; consumers cannot mutate cache entries.
    averages = {name: {**row, "extension_pct": _change(current, row["value"])} for name, row in cached_averages.items()}
    series = [dict(row) for row in cached_series]
    return {
        "price": current,
        "price_as_of": end if current is not None else None,
        "averages": averages,
        "series": series,
        "regime_start": ASST_REGIME_START.isoformat() if ticker == "ASST" else None,
        "basis": "Friday BTC daily candle closes; 200 weekly observations" if ticker == "BTC" else "Full split-adjusted ASST ticker history, including pre-merger observations for SMA warmup; Strive began trading September 15, 2025; February 6, 2026 reverse split is already reflected in provider closes" if ticker == "ASST" else "Split-adjusted daily closes",
    }


def _aware_stamp(value: Any) -> datetime | None:
    """Parse a provider timestamp without inventing a timezone."""
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _indicator(rows: list[dict], field: str, period: dict, *, cutoff: datetime | None = None,
               previous_cutoff: datetime | None = None) -> dict:
    def observations(last_day: str, instant: datetime | None) -> list[dict]:
        clean = {}
        for row in rows:
            day, value = _date(row.get("date")), _number(row.get(field))
            stamp = _aware_stamp(row.get("as_of")) if "as_of" in row else None
            # Daily CMC observations retain their source observation instant.
            # Later Friday observations cannot enter the 4pm frozen edition.
            if instant is not None and "as_of" in row and (stamp is None or stamp > instant):
                continue
            if day is not None and day.isoformat() <= last_day and value is not None and 0 <= value <= 100:
                prior = clean.get(day.isoformat())
                prior_stamp = _aware_stamp(prior.get("as_of")) if prior else None
                # Newest eligible timestamp wins, independent of API order.
                if prior_stamp is None or stamp is None or stamp >= prior_stamp:
                    clean[day.isoformat()] = {**row, "date": day.isoformat(), "value": value}
        return [clean[day] for day in sorted(clean)]

    series = observations(period["end"], cutoff)
    latest = series[-1] if series else None
    # Reapply the prior cutoff before deduplicating, so a later update to the
    # prior Friday cannot erase that day's valid earlier comparison point.
    previous = observations(period["previous_end"], previous_cutoff) if previous_cutoff is not None else [row for row in series if row["date"] <= period["previous_end"]]
    prior = previous[-1] if previous else None
    return {
        "value": latest["value"] if latest else None,
        "change": latest["value"] - prior["value"] if latest and prior and latest["date"] > prior["date"] else None,
        "as_of": latest.get("as_of", latest["date"]) if latest else None,
        "observation_date": latest["date"] if latest else None,
        "classification": latest.get("classification") if latest else None,
        "source": latest.get("source") if latest else None,
        "source_timestamp": latest.get("source_timestamp") if latest else None,
        "previous_value": prior["value"] if prior else None,
        "previous_as_of": prior.get("as_of", prior["date"]) if prior else None,
        "stale": latest is not None and latest["date"] != period["end"],
        "series": series,
        "btc": _number(latest.get("btc")) if latest else None,
        "profit_pct": _number(latest.get("profit_pct")) if latest and _number(latest.get("profit_pct")) is not None and 0 <= float(latest["profit_pct"]) <= 100 else None,
        "profit_btc": _number(latest.get("profit_btc")) if latest else None,
    }


def _live_sentiment(rows: list[dict], snapshot: dict, period: dict, cutoff: datetime) -> dict:
    """Overlay a raw latest index on the live headline, never on daily history.

    Daily chart smoothing remains display-only. Its input excludes the latest
    snapshot, so an intraday update cannot replace a daily observation or mute
    an extreme value in the headline. The frozen Friday metric never calls
    this overlay and remains independent even when fetched on a later day.
    """
    result = _indicator(rows, "value", period, cutoff=cutoff, previous_cutoff=cutoff - timedelta(days=7))
    result.update(latest_observation=None, live_point=None, value_basis="Historical daily observation")
    if not isinstance(snapshot, dict):
        return result
    value, stamp = _number(snapshot.get("value")), _aware_stamp(snapshot.get("as_of"))
    if value is None or isinstance(snapshot.get("value"), bool) or not 0 <= value <= 100 or stamp is None or stamp > cutoff:
        return result
    daily_stamp = _aware_stamp(result.get("as_of"))
    daily_date = _date(result.get("observation_date"))
    if daily_stamp is not None and stamp < daily_stamp:
        return result
    if daily_stamp is None and daily_date is not None and stamp.astimezone(timezone.utc).date() < daily_date:
        return result
    observation = {**snapshot, "value": value, "as_of": stamp.isoformat()}
    prior = result["previous_value"]
    prior_stamp = _aware_stamp(result.get("previous_as_of"))
    prior_date = _date(result.get("previous_as_of"))
    comparable = prior is not None and (stamp > prior_stamp if prior_stamp is not None
                                      else prior_date is not None and stamp.date() > prior_date)
    result.update(
        value=value, change=value - prior if comparable else None,
        as_of=stamp.isoformat(), observation_date=stamp.astimezone(timezone.utc).date().isoformat(),
        classification=snapshot.get("classification"), source=snapshot.get("source", result.get("source")),
        source_timestamp=snapshot.get("source_timestamp", snapshot.get("as_of")),
        stale=stamp.astimezone(timezone.utc).date().isoformat() != period["end"],
        latest_observation=observation,
        live_point={"date": stamp.isoformat(), "value": value, "classification": snapshot.get("classification"), "kind": "latest snapshot"},
        value_basis="Latest provider snapshot; chart history remains daily observations",
    )
    return result


def _live_quote(ticker: str, quote: dict, rows: dict, collected_at: datetime, calendar: Any) -> dict | None:
    """Accept a timestamped quote only if it is newer than completed history."""
    if not isinstance(quote, dict):
        return None
    try:
        raw_stamp = quote.get("as_of")
        parsed = raw_stamp if isinstance(raw_stamp, datetime) else datetime.fromisoformat(str(raw_stamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
    except (TypeError, ValueError):
        return None
    price, stamp = _number(quote.get("price")), _datetime(quote.get("as_of"))
    if price is None or price <= 0 or stamp is None or stamp > collected_at:
        return None
    if rows:
        last_day = _date(max(rows))
        if ticker == "BTC":
            history_available = datetime.combine(last_day + timedelta(days=1), time.min, timezone.utc)
        else:
            try:
                history_available = _close(last_day, calendar)
            except (ValueError, KeyError):
                return None
        if stamp < history_available:
            return None
    return {"price": price, "as_of": stamp.isoformat(), "source": quote.get("source", "Provider"), "delayed": quote.get("delayed", True)}


def compute_panel(data: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Convert provider data into the shared UI/export contract.

    Demo is anchored to September 4, 2026. Latest selects the last completed
    exchange week at collection time. Daily price history is never treated as
    an intraday mark; optional equity_close fields explicitly supply that mark.
    """
    if now is None:
        now = datetime(2026, 9, 4, 20, 5, tzinfo=timezone.utc) if data.get("mode") == "demo" else (_datetime(data.get("fetched_at")) or datetime.now(timezone.utc))
    calendar = _calendar()
    period = completed_week(now, calendar)
    end = _date(period["end"])
    prices = {ticker: _clean_prices(data.get("prices", {}).get(ticker, []), end) for ticker in ("BTC", *TICKERS)}
    weekly_btc = _equity_marks(prices["BTC"], data.get("btc_equity_marks", {}), period, calendar)
    use_equity = all((_mark(weekly_btc.get(day), True) or 0) > 0 for day in (period["previous_end"], period["end"]))
    if use_equity:
        period["price_alignment"] = "BTC and equities marked at the regular-session equity close"
    end_btc = _mark(weekly_btc.get(period["end"]), use_equity)
    start_btc = _mark(weekly_btc.get(period["previous_end"]), use_equity)
    treasury = [_treasury(ticker, data.get("companies", {}).get(ticker, {}), weekly_btc, prices[ticker], period, use_equity) for ticker in ("MSTR", "ASST")]
    header = {
        "btc": {"price": end_btc, "weekly_return_pct": _change(end_btc, start_btc), "start_price": start_btc, "end_date": period["end"]},
        "companies": {},
    }
    for row in treasury:
        ticker = row["ticker"]
        price = _mark(prices[ticker].get(period["end"]))
        header["companies"][ticker] = {"price": price, "weekly_return_pct": _change(price, _mark(prices[ticker].get(period["previous_end"]))), "nav_per_share": row["nav_per_share"], "nav_change_pct": row["nav_change_pct"], "premium_pct": row["premium_pct"], "nav_multiple": row["nav_multiple"], "start_nav_multiple": row["start_nav_multiple"], "nav_multiple_change": row["nav_multiple_change"]}
    liquidity = [_liquidity(ticker, prices[ticker], period, calendar) for ticker in TICKERS]
    notices = list(data.get("notices", []))
    if calendar is None:
        notices.append("Exchange calendar unavailable: holiday and early-close validation is provisional.")
    if not use_equity:
        notices.append("BTC uses daily close proxies for weekly performance and NAV; these are not simultaneous with the equity close.")
    for row in treasury:
        if row["reason"]:
            notices.append(f"{row['ticker']}: {row['reason']}.")
    for row in liquidity:
        if not row["complete"]:
            notices.append(f"{row['ticker']}: weekly dollar volume unavailable ({row['observed_sessions']}/{row['expected_sessions']} sessions supplied).")
    # A UTC daily candle dated Friday ends after the Friday equity close. Keep
    # that still-open bar out of the frozen 200W mean, even in a later refresh.
    frozen_btc_cutoff = _datetime(period["as_of"]).astimezone(timezone.utc).date()
    frozen_btc = {day: row for day, row in prices["BTC"].items() if _date(day) < frozen_btc_cutoff}
    trends = {ticker: _trends(ticker, frozen_btc if ticker == "BTC" else prices[ticker], period["end"]) for ticker in ("BTC", "MSTR", "ASST")}
    trends["BTC"]["price"] = end_btc
    trends["BTC"]["price_as_of"] = period["as_of"] if use_equity else period["end"]
    trends["BTC"]["basis"] = "200 completed Friday UTC daily closes available before the equity close; extension uses the BTC weekly endpoint price"
    for average in trends["BTC"]["averages"].values():
        average["extension_pct"] = _change(end_btc, average["value"])
    live_end = now.astimezone(timezone.utc).date()
    live_period = {**period, "end": live_end.isoformat(), "previous_end": (live_end - timedelta(days=7)).isoformat()}
    live_prices = {ticker: _clean_prices(data.get("prices", {}).get(ticker, []), live_end) for ticker in ("BTC", "MSTR", "ASST")}
    live_trends = {}
    collected_at = min(now, _datetime(data.get("fetched_at")) or now)
    live_prices["BTC"] = {day: row for day, row in live_prices["BTC"].items() if _date(day) < collected_at.astimezone(timezone.utc).date()}
    for ticker, rows in live_prices.items():
        last = max(rows) if rows else live_end.isoformat()
        live_trends[ticker] = {**_trends(ticker, rows, last), "as_of": max(rows) if rows else None}
        quote = _live_quote(ticker, data.get("latest_quotes", {}).get(ticker, {}), rows, collected_at, calendar)
        live_trends[ticker].update(latest_quote=quote, live_point=None)
        if quote is not None:
            trend = live_trends[ticker]
            trend.update(price=quote["price"], price_as_of=quote["as_of"], price_basis="Latest provider quote; may be delayed")
            point = {"date": quote["as_of"], "close": quote["price"], "kind": "latest quote"}
            for name, average in trend["averages"].items():
                average["extension_pct"] = _change(quote["price"], average["value"])
                point[f"sma_{name.lower()}"] = average["value"]
            # Separate marker: never append a quote to completed bars or feed it
            # into a moving-average denominator.
            trend["live_point"] = point
    return {
        "mode": data.get("mode", "demo"),
        "fetched_at": data.get("fetched_at"),
        "period": period,
        "header": header,
        "liquidity": liquidity,
        "treasury": treasury,
        "trends": trends,
        "sentiment": _indicator(data.get("sentiment", []), "value", period,
                                cutoff=_datetime(period["as_of"]), previous_cutoff=_close(_date(period["previous_end"]), calendar)),
        "supply_loss": _indicator(data.get("supply_loss", []), "pct", period),
        "live_trends": live_trends,
        "live_sentiment": _live_sentiment(data.get("sentiment", []), data.get("sentiment_latest", {}), live_period, collected_at),
        "live_supply_loss": _indicator(data.get("supply_loss", []), "pct", live_period),
        "notices": list(dict.fromkeys(notices)),
        "sources": data.get("sources", []),
    }
