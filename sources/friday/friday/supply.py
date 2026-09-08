"""Public Checkonchain supply observations, without executing embedded scripts.

The preferred public chart publishes loss, profit and circulating BTC balances
independently. We divide each balance by its matching circulating supply. The
separate percent-profit chart is a fallback only: 100 minus its profit share is
explicitly a complementary loss estimate, not a Glassnode loss observation.

On-chain profit compares current price with the price when coins last moved;
it does not establish an owner's actual purchase cost. Provider definitions,
price marks and revisions can differ. These public HTML charts are not a
versioned API. Missing dates are never interpolated, and today's UTC observation
is withheld because the provider does not establish that it is a completed day.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timedelta, timezone
import json
import math
import re
import struct
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UTC = timezone.utc
SOURCE = "Checkonchain"
REGIONS_PAGE = "https://charts.checkonchain.com/btconchain/cointime/supply_activevaulted_0/supply_activevaulted_0_light.html"
REGIONS_URL = REGIONS_PAGE.replace("charts.checkonchain.com", "charts-cdn.checkonchain.com")
PERCENT_PAGE = "https://charts.checkonchain.com/btconchain/unrealised/pctsupplyinprofit_all/pctsupplyinprofit_all_light.html"
PERCENT_URL = PERCENT_PAGE.replace("charts.checkonchain.com", "charts-cdn.checkonchain.com")
MAX_BYTES = 8_000_000


class SupplyDataError(ValueError):
    """The public source cannot provide a validated historical series."""


def _utc(now):
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise SupplyDataError("Collection timestamp must include a timezone")
    return now.astimezone(UTC)


def _fetch_html(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (FridayPanel/1.0)", "Accept": "text/html"})
    with urlopen(request, timeout=20) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise SupplyDataError("Public chart exceeds the response size limit")
    return raw.decode("utf-8")


def _plot(html):
    if not isinstance(html, str) or len(html) > MAX_BYTES:
        raise SupplyDataError("Invalid public chart document")
    match = re.search(r'Plotly\.newPlot\(\s*"[^"\r\n]+"\s*,\s*', html)
    if not match:
        raise SupplyDataError("Public chart has no recognized Plotly data")
    decoder = json.JSONDecoder()
    try:
        traces, end = decoder.raw_decode(html, match.end())
        separator = re.match(r"\s*,\s*", html[end:])
        if not separator:
            raise SupplyDataError("Missing public chart layout")
        layout, _ = decoder.raw_decode(html, end + separator.end())
    except (ValueError, TypeError) as exc:
        raise SupplyDataError("Public chart JSON changed or is malformed") from exc
    if not isinstance(traces, list) or not isinstance(layout, dict):
        raise SupplyDataError("Invalid public chart structure")
    return traces, layout


def _values(encoded):
    if isinstance(encoded, list):
        return encoded
    if not isinstance(encoded, dict) or not isinstance(encoded.get("bdata"), str):
        raise SupplyDataError("Unsupported chart array")
    # Plotly's numeric typed-array payloads are decoded locally, never eval'd.
    formats = {"f8": "d", "f4": "f", "i1": "b", "u1": "B", "i2": "h", "u2": "H", "i4": "i", "u4": "I"}
    dtype = encoded.get("dtype")
    if dtype not in formats or encoded.get("shape") is not None:
        raise SupplyDataError("Unsupported chart array encoding")
    try:
        raw = base64.b64decode(encoded["bdata"], validate=True)
        size = struct.calcsize(formats[dtype])
        if len(raw) % size:
            raise ValueError("Misaligned bytes")
        return [item[0] for item in struct.iter_unpack("<" + formats[dtype], raw)]
    except (ValueError, struct.error) as exc:
        raise SupplyDataError("Invalid chart numeric array") from exc


def _day(value):
    if not isinstance(value, str):
        raise SupplyDataError("Invalid observation date")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SupplyDataError("Invalid observation date") from exc
    stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
    if stamp.time().isoformat() != "00:00:00" or stamp.date() < date(2009, 1, 3):
        raise SupplyDataError("Expected a UTC daily observation")
    return stamp.date()


def _series(traces, name):
    matches = [trace for trace in traces if isinstance(trace, dict) and trace.get("name") == name]
    if len(matches) != 1:
        raise SupplyDataError(f"Missing or ambiguous {name} series")
    trace = matches[0]
    dates, values = trace.get("x"), _values(trace.get("y"))
    if not isinstance(dates, list) or len(dates) != len(values):
        raise SupplyDataError(f"Mismatched {name} dates and values")
    result = {}
    for raw_date, value in zip(dates, values):
        # Some charts contain pre-genesis placeholders. Ignore only those
        # explicit calendar dates; later invalid date strings fail validation.
        if isinstance(raw_date, str) and raw_date[:10] in ("2009-01-01", "2009-01-02"):
            continue
        day = _day(raw_date)
        if day in result:
            raise SupplyDataError(f"Duplicate {name} observation date")
        if value is None:
            result[day] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SupplyDataError(f"Invalid {name} observation value")
        try:
            number = float(value)
        except (OverflowError, ValueError) as exc:
            raise SupplyDataError(f"Invalid {name} observation value") from exc
        if not math.isfinite(number):
            result[day] = None
        elif number < 0:
            raise SupplyDataError(f"Invalid {name} observation value")
        else:
            result[day] = number
    return result


def parse_public_supply(html, *, method="balances", now=None, min_history_days=1460):
    """Validate one source surface and return dated rows plus provenance.

    ``balances`` requires separately published loss/profit/total BTC series.
    ``complement`` requires the percent-profit surface and labels derived loss.
    The minimum observation count guards against silently serving a shortened
    response. A small value may be supplied for a bounded parser unit test.
    """
    now = _utc(now)
    if not isinstance(min_history_days, int) or min_history_days < 1:
        raise SupplyDataError("Minimum history must be positive")
    traces, layout = _plot(html)
    title_data = layout.get("title", {})
    if not isinstance(title_data, dict) or not isinstance(title_data.get("text"), str):
        raise SupplyDataError("Missing supply chart title")
    title = re.sub(r"<[^>]*>", "", title_data["text"]).strip()
    if method == "balances":
        if title != "Supply Regions Total Balance [BTC]":
            raise SupplyDataError("Unexpected supply chart identity")
        loss, profit, total = (_series(traces, name) for name in
                               ("Supply in Loss", "Supply in Profit", "Circulating Supply"))
        dates = sorted(set(loss) | set(profit) | set(total))
        page, url = REGIONS_PAGE, REGIONS_URL
    elif method == "complement":
        if title != "Percent Supply in Profit":
            raise SupplyDataError("Unexpected percent-profit chart identity")
        profit = _series(traces, "Percent Supply in Profit")
        dates = sorted(profit)
        page, url = PERCENT_PAGE, PERCENT_URL
    else:
        raise SupplyDataError("Unrecognized public supply method")
    rows, missing, excluded = [], 0, 0
    for day in dates:
        if day >= now.date():
            excluded += 1
            continue
        if method == "balances":
            l, p, t = loss.get(day), profit.get(day), total.get(day)
            if l is None or p is None or t is None or t == 0:
                missing += 1
                continue
            tolerance = max(0.0001, t * 1e-9)
            if t > 21_000_000 or l > t or p > t or l + p > t + tolerance:
                raise SupplyDataError("Supply balances exceed circulating supply")
            row = {"date": day.isoformat(), "pct": l / t * 100, "profit_pct": p / t * 100,
                   "btc": l, "profit_btc": p, "total_btc": t, "estimated": False}
        else:
            p = profit.get(day)
            if p is None:
                missing += 1
                continue
            if not 0 <= p <= 1:
                raise SupplyDataError("Percent-profit source is outside its fraction unit")
            row = {"date": day.isoformat(), "pct": (1 - p) * 100, "profit_pct": p * 100,
                   "btc": None, "profit_btc": None, "total_btc": None, "estimated": True}
        row.update(source=SOURCE, method="independent_balances" if method == "balances" else "complementary_loss_estimate")
        rows.append(row)
    if len(rows) < min_history_days:
        raise SupplyDataError("Public supply history is missing or unexpectedly short")
    as_of = rows[-1]["date"]
    age = (now.date() - date.fromisoformat(as_of)).days
    notices = []
    if method == "complement":
        notices.append("Loss is a complementary estimate: 100% minus Checkonchain's published percent supply in profit. It may include coins exactly at cost or omitted from the profit classification. No independent loss balance or BTC count is available in this fallback.")
    if age > 3:
        notices.append(f"Public supply observations are dated {as_of}, {age} days before collection; they are not a current reading.")
    gaps, crosses = [], []
    for previous, current in zip(rows, rows[1:]):
        days = (date.fromisoformat(current["date"]) - date.fromisoformat(previous["date"])).days
        if days != 1:
            gaps.append({"after": previous["date"], "before": current["date"]})
        elif previous["pct"] <= previous["profit_pct"] and current["pct"] > current["profit_pct"]:
            crosses.append(current["date"])
    if gaps:
        notices.append(f"Public supply history contains {len(gaps)} date gaps; missing observations were not interpolated.")
    basis = "independently published BTC balances divided by circulating supply" if method == "balances" else "published profit share; loss = 100% minus profit (estimate)"
    return {"rows": rows, "source": SOURCE, "sources": [page, url], "source_url": page,
            "caption": f"Checkonchain · {basis} · completed UTC dates through {as_of}.",
            "method": "independent_balances" if method == "balances" else "complementary_loss_estimate",
            "as_of": as_of, "fetched_at": now.isoformat(), "notices": notices,
            "diagnostics": {"observations": len(rows), "first_date": rows[0]["date"], "last_date": as_of,
                            "lag_days": age, "missing_or_unmatched": missing, "excluded_current_or_future": excluded,
                            "gaps": gaps, "loss_above_profit_crossings": crosses}}


def fetch_public_supply(*, now=None):
    """Fetch independent public balances, then an explicitly labeled fallback.

    Both sources are public chart documents; no account or API key is accessed.
    Raises SupplyDataError if neither source validates. No synthetic or bundled
    snapshot is substituted. A stale provider series retains its original date.
    """
    failures = []
    for method, url in (("balances", REGIONS_URL), ("complement", PERCENT_URL)):
        try:
            result = parse_public_supply(_fetch_html(url), method=method, now=now)
            if failures:
                result["notices"].insert(0, "Independent public supply balances were unavailable; using the separately labeled percent-profit fallback.")
            result["diagnostics"]["attempt_failures"] = failures
            return result
        except (SupplyDataError, HTTPError, URLError, OSError, UnicodeError) as exc:
            if isinstance(exc, HTTPError):
                reason = f"HTTP {exc.code}"
            elif isinstance(exc, SupplyDataError):
                reason = str(exc)
            else:
                reason = "Network or document decoding failed"
            failures.append({"method": method, "reason": reason})
    raise SupplyDataError("Both public supply sources are unavailable or failed validation")
