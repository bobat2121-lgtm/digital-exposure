"""Historical, regular-session HLC3 estimate; never a trade-level VWAP."""

from datetime import date, datetime, time, timedelta, timezone
import json
from math import fsum, isfinite
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
SOURCE_NOTE = (
    "Yahoo Finance unadjusted 1-minute HLC3 weighted by minute volume; "
    "an estimate, not reported trade VWAP or company issuance proceeds. "
    "Only retrieved regular-session bars are included, with no claim of full SIP coverage. "
    "Bars exclude the minute beginning at the close; closing-auction coverage follows "
    "the source's timestamps, and volume may differ from end-of-day daily bars."
)


def _datetime(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Session timestamps must include a timezone.")
    return parsed


def select_sessions(edition_date: date, window: str) -> list[dict]:
    """Return actual exchange sessions strictly before the edition date."""
    if window not in ("prior_week", "five_sessions"):
        raise ValueError("Window must be prior_week or five_sessions.")
    try:
        import exchange_calendars as calendars
    except ImportError as exc:
        raise ValueError("Exchange calendar is unavailable; install exchange_calendars.") from exc
    monday = edition_date - timedelta(days=edition_date.weekday())
    start = monday - timedelta(days=7) if window == "prior_week" else edition_date - timedelta(days=40)
    end = monday - timedelta(days=1) if window == "prior_week" else edition_date - timedelta(days=1)
    try:
        name = "NASDAQ" if "NASDAQ" in calendars.get_calendar_names() else "XNYS"
        schedule = calendars.get_calendar(name).schedule.loc[start.isoformat():end.isoformat()]
        if window == "five_sessions":
            schedule = schedule.tail(5)
        sessions = [{"date": stamp.date().isoformat(), "open": row["open"].isoformat(),
                     "close": row["close"].isoformat()} for stamp, row in schedule.iterrows()]
    except Exception as exc:
        raise ValueError(f"Exchange schedule unavailable for {start} through {end}.") from exc
    if not sessions or (window == "five_sessions" and len(sessions) != 5):
        raise ValueError("The selected window has insufficient completed trading sessions.")
    return sessions


def parse_estimate(payloads, sessions, *, symbol: str, edition_date: date,
                   window: str, request_urls=(), fetched_at=None, interval="1m") -> dict:
    """Validate full minute coverage and summarize supplied Yahoo payloads.

    Sessions are dictionaries with date and timezone-aware open/close values.
    No request, wall-clock window selection, or invented fill happens here.
    """
    if interval not in ("1m", "5m"):
        raise ValueError("Unsupported VWAP bar interval")
    step = 60 if interval == "1m" else 300
    if not sessions:
        raise ValueError("No completed sessions were supplied.")
    expected, bounds, daily_parts = {}, [], {}
    cutoff = datetime.combine(edition_date, time(9), NEW_YORK).timestamp()
    for session in sessions:
        day = str(session["date"])
        opening, closing = _datetime(session["open"]), _datetime(session["close"])
        if date.fromisoformat(day) >= edition_date or closing.timestamp() >= cutoff or closing <= opening:
            raise ValueError("Session extends beyond the historical edition cutoff.")
        if day in daily_parts:
            raise ValueError(f"Duplicate scheduled session: {day}.")
        start, end = int(opening.timestamp()), int(closing.timestamp())
        if start % 60 or end % 60 or (end - start) % step:
            raise ValueError("Session boundaries must align to whole bars.")
        bounds.append((start, end))
        daily_parts[day] = []
        for stamp in range(start, end, step):
            if stamp in expected:
                raise ValueError("Overlapping scheduled sessions.")
            expected[stamp] = day
    payloads = [payloads] if isinstance(payloads, dict) else payloads
    seen, excluded, normalized_bars = set(), 0, []
    for payload in payloads:
        try:
            chart = payload["chart"]
            if chart.get("error") or not chart.get("result"):
                raise ValueError("Yahoo returned no historical minute data.")
            result = chart["result"][0]
            meta = result.get("meta", {})
            if meta.get("symbol", symbol).upper() != symbol.upper():
                raise ValueError("Returned symbol does not match the requested equity.")
            if meta.get("dataGranularity", "1m") != interval:
                raise ValueError("The response does not contain the requested bar interval.")
            if meta.get("currency", "USD") != "USD":
                raise ValueError("Equity estimate requires USD prices.")
            timestamps = result["timestamp"]
            bars = result["indicators"]["quote"][0]
            if any(len(bars[field]) != len(timestamps) for field in ("open", "high", "low", "close", "volume")):
                raise ValueError("Minute-bar arrays have inconsistent lengths.")
            for index, stamp in enumerate(timestamps):
                if not isinstance(stamp, (int, float)) or not isfinite(stamp):
                    raise ValueError("Invalid minute-bar timestamp.")
                if stamp not in expected:
                    if any(start <= stamp < end for start, end in bounds):
                        raise ValueError("A bar inside the selected session is off the minute grid.")
                    excluded += 1
                    continue
                if stamp in seen:
                    raise ValueError("Duplicate eligible minute bar.")
                seen.add(stamp)
                opening_price, high, low, close, volume = (bars[field][index] for field in ("open", "high", "low", "close", "volume"))
                values = (opening_price, high, low, close, volume)
                if any(not isinstance(value, (int, float)) or not isfinite(value) for value in values):
                    raise ValueError("Missing or nonfinite price/volume in an eligible minute.")
                if min(opening_price, high, low, close) <= 0 or volume < 0 or high < low:
                    raise ValueError("Invalid price or negative volume in an eligible minute.")
                tolerance = max(high, close) * 1e-7
                if min(opening_price, close) < low - tolerance or max(opening_price, close) > high + tolerance:
                    raise ValueError("An eligible minute's open/close falls outside its high/low range.")
                normalized_bars.append({"timestamp": int(stamp), "open": opening_price, "high": high,
                                        "low": low, "close": close, "volume": volume})
                daily_parts[expected[stamp]].append(((high + low + close) / 3 * volume, volume))
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Malformed historical minute-data response.") from exc
    missing = len(expected) - len(seen)
    if missing:
        raise ValueError(f"Incomplete historical window: {missing} expected minute bars missing.")
    daily = []
    for day, parts in sorted(daily_parts.items()):
        volume = fsum(part[1] for part in parts)
        numerator = fsum(part[0] for part in parts)
        if volume <= 0:
            raise ValueError(f"No positive trading volume for {day}.")
        daily.append({"date": day, "value": numerator / volume, "bar_count": len(parts),
                      "total_volume": volume, "weighted_numerator": numerator})
    total_volume = fsum(day["total_volume"] for day in daily)
    numerator = fsum(day["weighted_numerator"] for day in daily)
    return {
        "symbol": symbol.upper(), "edition_date": edition_date.isoformat(),
        "value": numerator / total_volume, "method": f"hlc3_{interval}",
        "label": f"{step // 60}-minute VWAP estimate",
        "window": window, "session_start": daily[0]["date"], "session_end": daily[-1]["date"],
        "sessiondates": [day["date"] for day in daily], "bar_count": len(seen),
        "total_volume": total_volume, "weighted_numerator": numerator, "daily": daily,
        "bars": sorted(normalized_bars, key=lambda bar: bar["timestamp"]),
        "request_urls": list(request_urls),
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        "excluded_bar_count": excluded,
        "source_note": (SOURCE_NOTE.replace("1-minute", "5-minute").replace("minute volume", "bar volume")
                        .replace("the minute beginning", "the bar beginning")) if interval == "5m" else SOURCE_NOTE,
    }


def _fetch_window(symbol, sessions, interval="1m"):
    payloads, urls, remaining = [], [], list(sessions)
    while remaining:
        first = date.fromisoformat(remaining[0]["date"])
        group = [item for item in remaining if date.fromisoformat(item["date"]) < first + timedelta(days=7)]
        remaining = remaining[len(group):]
        last = date.fromisoformat(group[-1]["date"]) + timedelta(days=1)
        params = {"period1": int(datetime.combine(first, time(), NEW_YORK).timestamp()),
                  "period2": int(datetime.combine(last, time(), NEW_YORK).timestamp()),
                  "interval": interval, "includePrePost": "false", "includeAdjustedClose": "false"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol.upper(), safe='')}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                payloads.append(json.load(response))
        except Exception as exc:
            raise ValueError(f"Historical 1-minute data unavailable ({type(exc).__name__}); no estimate produced.") from exc
        urls.append(url)
    return payloads, urls


def pull_estimate(symbol: str, edition_date: date, window: str = "auto") -> dict:
    """Fetch prior-week data, or an explicitly labeled five-session fallback."""
    if window not in ("auto", "prior_week", "five_sessions"):
        raise ValueError("Window must be auto, prior_week, or five_sessions.")
    if not symbol or not isinstance(edition_date, date):
        raise ValueError("A symbol and edition date are required.")
    attempts = ("prior_week", "five_sessions") if window == "auto" else (window,)
    previous_dates, failure = None, None
    for actual_window in attempts:
        sessions = select_sessions(edition_date, actual_window)
        dates = tuple(item["date"] for item in sessions)
        if dates == previous_dates:
            raise ValueError(f"{failure} Five-session fallback is the same window; missing data cannot be filled.")
        previous_dates = dates
        try:
            payloads, urls = _fetch_window(symbol, sessions)
            result = parse_estimate(payloads, sessions, symbol=symbol, edition_date=edition_date,
                                    window=actual_window, request_urls=urls)
            if failure:
                result["fallback_reason"] = failure
            return result
        except ValueError as exc:
            failure = str(exc)
    raise ValueError(failure or "Historical VWAP estimate unavailable.")
