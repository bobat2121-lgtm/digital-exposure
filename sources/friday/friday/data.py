"""Portable data providers for the Friday panel.

The demo is entirely synthetic. Latest mode never falls back to demo observations.
Company balances use vetted SEC disclosures published before the Friday cutoff,
with explicitly estimated basic shares and senior claims where required.
Public feeds may be delayed, incomplete or rate limited.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
import random
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from friday.supply import fetch_public_supply
from friday.sentiment import fetch_cmc_sentiment, SOURCE_URL as CMC_SOURCE_URL
from friday.balances import company_balances
from friday.metrics import completed_week

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
SYMBOLS = ("BTC", "MSTR", "ASST", "STRC", "SATA")
DEMO_END = date(2026, 9, 4)
FULL_HISTORY_MAX_AGE = timedelta(hours=6)
_BASELINES = {
    "MSTR": {
        "btc_held": 845_050.0, "cash_usd": 6_710_000_000.0,
        "securities_usd": 0.0, "debt_usd": 6_753_703_000.0,
        "preferred_usd": 14_911_463_133.50, "shares": 420_483_000.0,
        "baseline_at": "2026-08-30", "disclosed_at": "2026-09-07T00:00:00+00:00",
        "source": "https://www.sec.gov/Archives/edgar/data/1050446/000119312526375463/mstr-20260831.htm",
        "sources": [
            "https://www.strategy.com/shares",
            "https://www.sec.gov/Archives/edgar/data/1050446/000105044626000044/mstr-20260630.htm",
        ],
        "share_basis": "Basic/effective Class A + B; rounded to 1,000 shares",
        "cash_basis": "Combined designated USD reserve and cash, including reserve securities once",
        "reconstructed": True, "estimated": True,
        "note": "Aug 30 economic snapshot reconstructed Sep 7. $6.71B is combined liquidity, not cash alone. Debt is a June 30 principal carryforward; preferred claims are estimated. Original share-table publication time was not recovered.",
    },
    "ASST": {
        "btc_held": 23_156.0, "cash_usd": 183_500_000.0,
        "securities_usd": 49_152_000.0, "debt_usd": 0.0,
        "preferred_usd": 907_482_139.14, "shares": 93_262_570.0,
        "baseline_at": "2026-08-28", "disclosed_at": "2026-09-07T00:00:00+00:00",
        "source": "https://www.sec.gov/Archives/edgar/data/1920406/000162828026059468/asst-20260831.htm",
        "sources": ["https://www.strive.com/treasury/api/dashboard/base-data"],
        "share_basis": "Basic/effective Class A + B, including applicable shares pending issuance",
        "cash_basis": "Cash and securities separate; securities are 505,000 STRC shares at the historical mark",
        "reconstructed": True, "estimated": True,
        "note": "Aug 28 economic snapshot recovered Sep 7; cash/debt record was revised Sep 6. STRC securities fixed at dated value. Preferred claim uses the conservative $100.01 per-share reconstruction. This is not an archive of information available on Sep 4.",
    },
}


def _now() -> datetime:
    return datetime.now(UTC)


def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and (result > 0 if positive else result >= 0) else None


def _fetch_json(url: str, headers: dict | None = None):
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; FridayPanelDemo/1.0)",
        "Accept": "application/json", **(headers or {}),
    })
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def _safe_error(exc: Exception) -> str:
    # Do not echo URLs, request headers or a provider response containing a key.
    if isinstance(exc, HTTPError):
        return f"provider returned HTTP {exc.code}"
    if isinstance(exc, (URLError, TimeoutError, OSError)):
        return "network unavailable or provider timed out"
    return "provider response failed validation"


def _yahoo_url(symbol: str, interval="1d", span=None) -> str:
    code = "BTC-USD" if symbol == "BTC" else symbol
    params = {
        "interval": interval, "includePrePost": "false",
        "includeAdjustedClose": "false", "events": "splits",
    }
    if span is not None:
        params["range"] = span
    else:
        # Explicit bounds avoid provider auto-aggregation of range=max. One
        # response contains full available daily history, including SMA warmup.
        params.update(period1=0, period2=int(_now().timestamp()))
    return "https://query1.finance.yahoo.com/v8/finance/chart/" + quote(code, safe="") + "?" + urlencode(params)


def _chart(payload: dict, symbol: str) -> dict:
    chart = payload["chart"]
    results = chart.get("result")
    if chart.get("error") or not results or len(results) != 1:
        raise ValueError("Missing chart")
    result = results[0]
    expected = "BTC-USD" if symbol == "BTC" else symbol
    if result["meta"].get("symbol") != expected:
        raise ValueError("Symbol mismatch")
    return result


def _latest_quote(meta: dict, now: datetime) -> dict | None:
    """Validate a current provider observation without turning it into a bar."""
    price = _number(meta.get("regularMarketPrice"), positive=True)
    stamp = _number(meta.get("regularMarketTime"), positive=True)
    if price is None or stamp is None:
        return None
    try:
        observed = datetime.fromtimestamp(stamp, UTC)
    except (ValueError, OverflowError, OSError):
        return None
    if observed > now or observed.year < 2000:
        return None
    return {
        "price": price, "as_of": observed.isoformat(),
        "source": "Yahoo Finance", "delayed": True,
    }


def _aware(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.astimezone(UTC) if stamp.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _next_full_refresh(now):
    """Revalidate at the next UTC day, equity close, or six-hour boundary."""
    deadlines = [now + FULL_HISTORY_MAX_AGE,
                 datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), UTC)]
    try:
        import exchange_calendars

        calendar = exchange_calendars.get_calendar("XNYS")
        first = now.astimezone(ET).date()
        for session in calendar.sessions_in_range(first.isoformat(), (first + timedelta(days=8)).isoformat()):
            close = calendar.session_close(session).to_pydatetime()
            if close > now:
                deadlines.append(close)
                break
    except (ImportError, ValueError, KeyError):
        # Without a verified exchange calendar, hourly full revalidation also
        # covers early closes without assuming a normal 16:00 close.
        deadlines.append(now + timedelta(hours=1))
    return min(deadlines).astimezone(UTC)


def _fetch_quote_refresh(symbol, history_fetched_at):
    """Short five-day request for a quote and newly effective split events.

    Returned candles are deliberately not merged with a differently adjusted
    historical series. A new split forces the same full validation as reload.
    """
    result = _chart(_fetch_json(_yahoo_url(symbol, span="5d")), symbol)
    if result["meta"].get("dataGranularity") != "1d":
        raise ValueError("Provider did not return a daily quote response")
    now = _now()
    splits = result.get("events", {}).get("splits", {})
    if not isinstance(splits, dict):
        raise ValueError("Invalid provider split events")
    changed = False
    for event in splits.values():
        if not isinstance(event, dict):
            raise ValueError("Invalid provider split event")
        stamp = _number(event.get("date"), positive=True)
        numerator = _number(event.get("numerator"), positive=True)
        denominator = _number(event.get("denominator"), positive=True)
        if stamp is None or numerator is None or denominator is None:
            raise ValueError("Invalid provider split event")
        effective = datetime.fromtimestamp(stamp, UTC)
        if history_fetched_at < effective <= now:
            changed = True
    return {"quote": _latest_quote(result["meta"], now), "split_changed": changed}


def _fetch_prices(symbol: str) -> tuple[list[dict], dict | None]:
    result = _chart(_fetch_json(_yahoo_url(symbol)), symbol)
    if result["meta"].get("dataGranularity") != "1d":
        raise ValueError("Provider did not return daily price history")
    quotes = result["indicators"]["quote"][0]
    timestamps = result.get("timestamp", [])
    closes = quotes.get("close", [])
    volumes = quotes.get("volume", [])
    now = _now()
    current_period = result.get("meta", {}).get("currentTradingPeriod", {}).get("regular", {})
    rows = {}
    for i, stamp in enumerate(timestamps):
        observed = datetime.fromtimestamp(stamp, UTC)
        if observed > now:
            continue
        day = observed.date() if symbol == "BTC" else observed.astimezone(ET).date()
        # Exclude incomplete daily bars. Calendar holidays are absent in provider data.
        if symbol == "BTC" and day >= now.date():
            continue
        if symbol != "BTC" and day == now.astimezone(ET).date():
            end_stamp = current_period.get("end")
            if not end_stamp or now.timestamp() < end_stamp:
                continue
        close = _number(closes[i] if i < len(closes) else None, positive=True)
        if close is None:
            continue
        volume = _number(volumes[i] if i < len(volumes) else None)
        rows[day.isoformat()] = {
            "date": day.isoformat(), "close": close, "volume": volume,
            "vwap": None, "source_timestamp": observed.isoformat(),
            "volume_unit": "USD reported crypto turnover" if symbol == "BTC" else "shares",
            # Yahoo quote.close is split-adjusted already. Do not apply the
            # event ratios again; adjclose would also include cash distributions.
            "price_basis": "Provider split-adjusted close" if symbol != "BTC" else "BTC UTC daily close",
        }
        # Preserve provider daily extrema on the same split-adjusted basis.
        # Missing OHLC does not invalidate an otherwise usable closing price.
        for field in ("open", "high", "low"):
            values = quotes.get(field, [])
            value = _number(values[i] if i < len(values) else None, positive=True)
            if value is not None:
                rows[day.isoformat()][field] = value
    if not rows:
        raise ValueError("No valid completed daily bars")
    quote = _latest_quote(result.get("meta", {}), now) if symbol in ("BTC", "MSTR", "ASST") else None
    return [rows[key] for key in sorted(rows)], quote


def _fetch_btc_equity_marks() -> dict:
    """Recent BTC hourly candles ending 16:00 ET; separate from UTC daily bars.

    Friday early-close sessions are explicitly supplied at 13:00 ET as a second
    candidate. The calculation/calendar layer chooses the applicable boundary.
    """
    result = _chart(_fetch_json(_yahoo_url("BTC", "1h", "1mo")), "BTC")
    closes = result["indicators"]["quote"][0].get("close", [])
    marks = {}
    now = _now()
    for i, stamp in enumerate(result.get("timestamp", [])):
        start = datetime.fromtimestamp(stamp, UTC)
        ending = start + timedelta(hours=1)
        local = ending.astimezone(ET)
        if ending > now or local.minute != 0 or local.hour not in (13, 16):
            continue
        close = _number(closes[i] if i < len(closes) else None, positive=True)
        if close is None:
            continue
        key = local.date().isoformat()
        record = marks.setdefault(key, {})
        suffix = "" if local.hour == 16 else "_early"
        record["close" + suffix] = close
        record["as_of" + suffix] = local.isoformat()
    return marks


def _fetch_supply_loss(key: str) -> list[dict]:
    since = int((_now() - timedelta(days=5 * 366)).timestamp())
    # Documented Glassnode query authentication; errors are sanitized upstream.
    query = urlencode({"a": "BTC", "i": "24h", "s": since, "api_key": key})
    root = "https://api.glassnode.com/v1/metrics/supply/"
    with ThreadPoolExecutor(max_workers=3) as pool:
        loss_future = pool.submit(_fetch_json, root + "loss_sum?" + query)
        supply_future = pool.submit(_fetch_json, root + "current?" + query)
        profit_future = pool.submit(_fetch_json, root + "profit_sum?" + query)
        losses, supplies = loss_future.result(), supply_future.result()
        try:
            profits = profit_future.result()
        except Exception:
            profits = []  # Loss remains usable; do not invent complementary profit.
    totals = {int(row["t"]): _number(row.get("v"), positive=True) for row in supplies}
    profit_by_time = {int(row["t"]): _number(row.get("v")) for row in profits}
    rows = []
    now = _now()
    for row in losses:
        stamp = int(row["t"])
        observed = datetime.fromtimestamp(stamp, UTC)
        loss, total = _number(row.get("v")), totals.get(stamp)
        if observed.date() >= now.date() or loss is None or total is None or loss > total:
            continue
        profit = profit_by_time.get(stamp)
        if profit is not None and (profit > total or loss + profit > total * (1 + 1e-8)):
            profit = None
        rows.append({"date": observed.date().isoformat(), "pct": loss / total * 100, "btc": loss,
                     "profit_pct": profit / total * 100 if profit is not None else None,
                     "profit_btc": profit, "total_btc": total})
    if not rows:
        raise ValueError("No matched supply observations")
    return sorted(rows, key=lambda item: item["date"])


def _supply_feed(key=""):
    notices = []
    if key:
        try:
            rows = _fetch_supply_loss(key)
            return {"rows": rows, "source": "Glassnode", "source_url": "https://docs.glassnode.com/basic-api/endpoints/supply",
                    "method": "independent_balances", "notices": [], "sources": ["https://docs.glassnode.com/basic-api/endpoints/supply"]}
        except Exception as exc:
            notices.append(f"Glassnode supply feed unavailable: {_safe_error(exc)}. Using the public Checkonchain source where available.")
    result = fetch_public_supply()
    result["notices"] = notices + result.get("notices", [])
    return result


def load_latest() -> dict:
    """Fetch independent public series; keep unavailable data visibly missing."""
    fetched_at = _now()
    cutoff = datetime.fromisoformat(completed_week(fetched_at)["as_of"])
    data = {
        "mode": "latest", "fetched_at": fetched_at.isoformat(),
        "prices": {symbol: [] for symbol in SYMBOLS}, "latest_quotes": {}, "sentiment": [],
        "sentiment_latest": {}, "sentiment_source": "CoinMarketCap", "sentiment_source_url": CMC_SOURCE_URL,
        "supply_loss": [], "btc_equity_marks": {}, "companies": company_balances(cutoff),
        "sources": {
            "prices": "Yahoo Finance chart API; provider close and volume, daily VWAP unavailable",
            "sentiment": "CoinMarketCap · " + CMC_SOURCE_URL,
            "supply_loss": "Checkonchain public daily supply balances",
            "companies": "SEC filings published August 24 and 31, 2026; latest eligible disclosure held fixed through Friday; basic shares and senior claims include labeled estimates",
        },
        "price_basis": "Provider close (split-adjusted where supplied by Yahoo); not dividend-adjusted total return",
        "btc_close_alignment": "Daily BTC bars use UTC. Recent equity-close BTC marks are separate 1-hour candle closes at 16:00/13:00 ET.",
        "notices": [
            "Latest charts show provider quotes separately from completed daily bars. Quote timestamps are provider observations and may be delayed; this is not a real-time consolidated feed.",
            "Dollar volume uses daily close × shares traded as an estimate; Yahoo daily data does not provide exact traded notional or VWAP.",
            "NAV uses BASIC Class A+B shares and the latest vetted disclosure published by the Friday cutoff. Disclosed quantities, cash and estimated senior claims are held fixed for both weekly price marks.",
            "Strategy liquid assets include $6.71B combined designated reserve/cash once; debt is carried from June 30. Strive STRC securities retain their August 28 mark.",
            "Long-history BTC SMA uses daily UTC closes; the weekly return and BTC-only NAV impact require matching ET equity-close BTC marks.",
            "Opening or refreshing a tab requests fresh quotes and indicators in the background. Validated history can be preloaded; full histories revalidate at UTC rollover, equity-session close, new stock splits, and at least every six hours.",
            "Fear & Greed uses CoinMarketCap throughout, starting July 2023. The live headline and dot use its latest reported index; the line uses a trailing three-day average of published daily observations. Friday values stop at the equity-close cutoff. Other sentiment providers are not mixed into the series.",
            "ASST opens in January. Its 200-day SMA uses full split-adjusted ticker history for warmup, including pre-merger Asset Entities sessions. Yahoo already reflects the February 6, 2026 1-for-20 reverse split; no second adjustment is applied.",
        ],
    }
    for ticker, company in data["companies"].items():
        data["notices"].extend(f"{ticker}: {note}" for note in company.get("notes", []))
        if company.get("source"):
            data["sources"][f"{ticker} balances"] = company["source"]
    base_notices = list(data["notices"])
    key = os.environ.get("GLASSNODE_API_KEY", "").strip()
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(_fetch_prices, symbol): ("price", symbol) for symbol in SYMBOLS}
        jobs[pool.submit(fetch_cmc_sentiment)] = ("sentiment_payload", "CoinMarketCap Fear & Greed")
        jobs[pool.submit(_fetch_btc_equity_marks)] = ("btc_equity_marks", "BTC aligned marks")
        jobs[pool.submit(_supply_feed, key)] = ("supply_payload", "Supply observations")
        for future in as_completed(jobs):
            kind, label = jobs[future]
            try:
                result = future.result()
            except Exception as exc:
                data["notices"].append(f"{label} unavailable: {_safe_error(exc)}. No synthetic fallback was used.")
                continue
            if kind == "price":
                rows, quote = result
                data["prices"][label] = rows
                if quote is not None:
                    data["latest_quotes"][label] = quote
                elif label in ("BTC", "MSTR", "ASST"):
                    data["notices"].append(f"{label} current quote unavailable or invalid; completed history retained.")
            elif kind == "sentiment_payload":
                data["sentiment"] = result["rows"]
                data["sentiment_latest"] = result.get("latest", {})
                data["sentiment_source"] = result["source"]
                data["sentiment_source_url"] = result["source_url"]
                data["sources"]["sentiment"] = result["source"] + " · " + result["source_url"]
                data["notices"].extend(result.get("notices", []))
            elif kind == "supply_payload":
                data["supply_loss"] = result["rows"]
                data["supply_source"] = result["source"]
                data["supply_source_url"] = result["source_url"]
                data["supply_method"] = result["method"]
                data["sources"]["supply_loss"] = result["source"] + " · " + result["source_url"]
                data["notices"].extend(result.get("notices", []))
            else:
                data[kind] = result
    for row in data["prices"]["BTC"]:
        mark = data["btc_equity_marks"].get(row["date"], {})
        if mark.get("close") is not None:
            row.update(equity_close=mark["close"], equity_close_at=mark["as_of"])
    if data["supply_loss"] and data["supply_loss"][-1].get("profit_pct") is None:
        data["notices"].append("Latest supply in profit is unavailable or unmatched; loss observations are retained.")
    finished = _now()
    data["fetched_at"] = finished.isoformat()
    data["refresh_meta"] = {
        "kind": "full", "reason": "Full requested load", "last_full_load_at": finished.isoformat(),
        "next_full_load_at": _next_full_refresh(finished).isoformat(), "base_notices": base_notices,
        "histories": {symbol: {"fetched_at": finished.isoformat() if data["prices"][symbol] else None,
                                "status": "validated" if data["prices"][symbol] else "unavailable"} for symbol in SYMBOLS},
        "indicators": {"sentiment": {"fetched_at": finished.isoformat() if data["sentiment"] else None,
                                      "status": "validated" if data["sentiment"] else "unavailable"},
                       "supply": {"fetched_at": finished.isoformat() if data["supply_loss"] else None,
                                  "status": "validated" if data["supply_loss"] else "unavailable"}},
    }
    return data


def _reload_history(current_data, reason):
    """A failed revalidation keeps dated history explicitly stale, without quotes."""
    fresh = load_latest()
    fresh["refresh_meta"]["reason"] = reason
    old_meta = current_data.get("refresh_meta", {})
    for symbol in SYMBOLS:
        if fresh["prices"][symbol] or not current_data.get("prices", {}).get(symbol):
            continue
        fresh["prices"][symbol] = deepcopy(current_data["prices"][symbol])
        fresh["latest_quotes"].pop(symbol, None)
        old = old_meta.get("histories", {}).get(symbol, {})
        fresh["refresh_meta"]["histories"][symbol] = {"fetched_at": old.get("fetched_at"), "status": "stale_last_good"}
        fresh["notices"].append(f"{symbol} history revalidation failed. Retained dated history from {old.get('fetched_at') or 'the prior load'} is stale; its current quote is withheld until revalidation succeeds.")
    for kind, field, metadata in (("sentiment", "sentiment", ("sentiment_source", "sentiment_source_url")),
                                   ("supply", "supply_loss", ("supply_source", "supply_source_url", "supply_method"))):
        if fresh[field] or not current_data.get(field):
            continue
        fresh[field] = deepcopy(current_data[field])
        for name in metadata:
            if name in current_data:
                fresh[name] = current_data[name]
        fresh["sources"][field] = current_data.get("sources", {}).get(field, fresh["sources"].get(field))
        old = old_meta.get("indicators", {}).get(kind, {})
        fresh["refresh_meta"]["indicators"][kind] = {"fetched_at": old.get("fetched_at"), "status": "stale_last_good"}
        fresh["notices"].append(f"{kind.capitalize()} revalidation failed. Retained observations and attribution from {old.get('fetched_at') or 'the prior load'} are stale.")
        if kind == "sentiment":
            fresh["sentiment_latest"] = {}
    return fresh


def refresh_latest(current_data):
    """Request fresh readings without repeatedly downloading full Yahoo history.

    This function returns a new dictionary. Full history is invalidated at each
    session close/UTC rollover, after a newly effective split, and within six
    hours even if no new bars exist (to pick up provider corrections). Failed
    current quotes are cleared; retained histories/indicators have explicit
    last-good timestamps and stale status. No synthetic fallback is introduced.
    """
    if current_data.get("mode") != "latest":
        return deepcopy(current_data)
    now = _now()
    meta = current_data.get("refresh_meta", {})
    loaded = _aware(meta.get("last_full_load_at"))
    deadline = _aware(meta.get("next_full_load_at"))
    histories = meta.get("histories", {})
    missing = [symbol for symbol in SYMBOLS if not current_data.get("prices", {}).get(symbol)
               or histories.get(symbol, {}).get("status") != "validated"]
    if missing or loaded is None or deadline is None or now < loaded or now >= deadline or now - loaded >= FULL_HISTORY_MAX_AGE:
        reason = "Missing or stale validated history" if missing else "Scheduled history revalidation"
        return _reload_history(current_data, reason)
    data = deepcopy(current_data)
    data["notices"] = list(meta.get("base_notices", []))
    data["latest_quotes"] = {}
    data["refresh_meta"]["kind"] = "incremental"
    data["refresh_meta"]["reason"] = "Fresh quote and indicator request; completed history reused"
    key = os.environ.get("GLASSNODE_API_KEY", "").strip()
    splits = []
    with ThreadPoolExecutor(max_workers=7) as pool:
        jobs = {pool.submit(_fetch_quote_refresh, symbol, _aware(histories[symbol]["fetched_at"]) or loaded): ("quote", symbol)
                for symbol in SYMBOLS}
        jobs[pool.submit(fetch_cmc_sentiment)] = ("sentiment", "CoinMarketCap Fear & Greed")
        jobs[pool.submit(_supply_feed, key)] = ("supply", "Supply observations")
        for future in as_completed(jobs):
            kind, label = jobs[future]
            try:
                result = future.result()
            except Exception as exc:
                if kind == "quote":
                    data["notices"].append(f"{label} current quote unavailable: {_safe_error(exc)}. Completed history remains dated to its last validated load.")
                else:
                    prior = data["refresh_meta"].setdefault("indicators", {}).setdefault(kind, {})
                    prior["status"] = "stale_last_good"
                    data["notices"].append(f"{label} refresh unavailable: {_safe_error(exc)}. Retained provider observations last fetched {prior.get('fetched_at') or 'on the prior load'} are stale.")
                    if kind == "sentiment":
                        data["sentiment_latest"] = {}
                continue
            if kind == "quote":
                if result["split_changed"]:
                    splits.append(label)
                elif result["quote"] is not None and label in ("BTC", "MSTR", "ASST"):
                    data["latest_quotes"][label] = result["quote"]
                elif result["quote"] is None and label in ("BTC", "MSTR", "ASST"):
                    data["notices"].append(f"{label} current quote unavailable or invalid; its completed history is retained.")
            elif kind == "sentiment":
                data["sentiment"] = result["rows"]
                data["sentiment_latest"] = result.get("latest", {})
                data["sentiment_source"], data["sentiment_source_url"] = result["source"], result["source_url"]
                data["sources"]["sentiment"] = result["source"] + " · " + result["source_url"]
                data["notices"].extend(result.get("notices", []))
                data["refresh_meta"].setdefault("indicators", {})[kind] = {"fetched_at": _now().isoformat(), "status": "validated"}
            else:
                data["supply_loss"] = result["rows"]
                data["supply_source"], data["supply_source_url"] = result["source"], result["source_url"]
                data["supply_method"] = result["method"]
                data["sources"]["supply_loss"] = result["source"] + " · " + result["source_url"]
                data["notices"].extend(result.get("notices", []))
                data["refresh_meta"].setdefault("indicators", {})[kind] = {"fetched_at": _now().isoformat(), "status": "validated"}
    if splits:
        return _reload_history(current_data, "New stock split detected: " + ", ".join(sorted(splits)))
    if data["supply_loss"] and data["supply_loss"][-1].get("profit_pct") is None:
        data["notices"].append("Latest supply in profit is unavailable or unmatched; loss observations are retained.")
    data["fetched_at"] = _now().isoformat()
    data["notices"] = list(dict.fromkeys(data["notices"]))
    return data


def load_demo() -> dict:
    """Deterministic illustrative dataset, ending Friday September 4, 2026."""
    # Four plotted years of a 200-week average need almost four additional
    # years before the visible range. Nine years also cover all F&G demo dates.
    days = [DEMO_END - timedelta(days=offset) for offset in range(9 * 366, -1, -1)]
    prices = {symbol: [] for symbol in SYMBOLS}
    end_values = {"BTC": 81_250.0, "MSTR": 134.85, "ASST": 23.42, "STRC": 99.65, "SATA": 100.15}
    base_volume = {"BTC": 220_000, "MSTR": 16_500_000, "ASST": 8_800_000, "STRC": 2_100_000, "SATA": 350_000}
    rng = random.Random(20260904)
    # Seeded innovations, clustered volatility and occasional shocks are only
    # for this clearly identified demo. Real provider data is never reshaped.
    btc_returns = {}
    volatility = 0.02
    for day in days:
        volatility = min(0.055, max(0.012, 0.92 * volatility + 0.08 * rng.uniform(0.012, 0.05)))
        shock = rng.gauss(0, 0.055) if rng.random() < 0.018 else 0
        btc_returns[day] = 0.00035 + rng.gauss(0, volatility) + shock
    try:
        import exchange_calendars

        calendar = exchange_calendars.get_calendar("XNYS")
        equity_days = [stamp.date() for stamp in calendar.sessions_in_range(days[0].isoformat(), DEMO_END.isoformat())][-756:]
        demo_calendar = "Synthetic equity observations follow actual XNYS sessions."
    except ImportError:
        calendar = None
        equity_days = [day for day in days if day.weekday() < 5][-756:]
        demo_calendar = "Synthetic equity observations use weekdays; exchange holidays are unverified."
    marks = {}
    for symbol in SYMBOLS:
        selected = days if symbol == "BTC" else equity_days
        log_level = 0.0
        levels, innovations = [], []
        for day in selected:
            if symbol in ("STRC", "SATA"):
                innovation = -0.08 * log_level + rng.gauss(0, 0.0028 if symbol == "STRC" else 0.004)
                if rng.random() < 0.025:
                    innovation += rng.gauss(0, 0.012)
            elif symbol == "BTC":
                innovation = btc_returns[day]
            else:
                innovation = btc_returns[day] * (1.25 if symbol == "MSTR" else 1.0) + rng.gauss(0, 0.021 if symbol == "MSTR" else 0.035)
            # Equity/Bitcoin fluctuations revert around a multi-year log trend;
            # anchoring a free random walk at today's price can create absurd
            # million-dollar historical BTC prices in an illustrative chart.
            log_level = log_level + innovation if symbol in ("STRC", "SATA") else 0.985 * log_level + innovation
            levels.append(log_level)
            innovations.append(innovation)
        for i, day in enumerate(selected):
            fraction = i / max(1, len(selected) - 1)
            if symbol in ("STRC", "SATA"):
                relative_log = levels[i] - levels[-1]
            else:
                start_ratio = 0.55 if symbol == "BTC" else 0.65
                relative_log = math.log(start_ratio) * (1 - fraction) + levels[i] - fraction * levels[-1]
            close = round(end_values[symbol] * math.exp(relative_log), 4)
            volume = round(base_volume[symbol] * math.exp(rng.gauss(-0.08, 0.44)) * (1 + min(2.5, abs(innovations[i]) * 13)))
            row = {"date": day.isoformat(), "close": close, "volume": float(volume), "vwap": round(close * math.exp(rng.gauss(0, 0.003)), 4)}
            if symbol == "BTC":
                asof = datetime.combine(day, datetime.min.time(), ET).replace(hour=16).isoformat()
                row.update(equity_close=close, equity_close_at=asof)
                marks[day.isoformat()] = {"close": close, "as_of": asof}
                if calendar is not None and calendar.is_session(day.isoformat()):
                    actual_close = calendar.session_close(day.isoformat()).to_pydatetime()
                    if actual_close.astimezone(ET).hour == 13:
                        marks[day.isoformat()].update(close_early=close, as_of_early=actual_close.isoformat())
            prices[symbol].append(row)
    # Long synthetic history supports the supply and sentiment demo; it is
    # never mixed with provider observations in Latest available mode.
    metric_days = [day for day in days if day >= date(2018, 2, 1)]
    sentiment, supply = [], []
    mood, pct = 52.0, 28.0
    for i, day in enumerate(metric_days):
        mood += 0.035 * (52 - mood) + btc_returns[day] * 115 + rng.gauss(0, 4.3)
        mood = min(99, max(1, mood))
        sentiment.append({"date": day.isoformat(), "value": float(round(mood))})
        pct += 0.02 * (28 - pct) - btc_returns[day] * 60 + rng.gauss(0, 1.35)
        pct = min(78, max(2, pct))
        loss_pct = round(pct, 2)
        total = 19_000_000 + i * 300
        loss = round(total * loss_pct / 100)
        if day >= DEMO_END.replace(year=DEMO_END.year - 4):
            supply.append({"date": day.isoformat(), "pct": loss_pct, "btc": loss,
                           "profit_pct": round(100 - loss_pct, 2), "profit_btc": total - loss, "total_btc": total})
    companies = deepcopy(_BASELINES)
    for company in companies.values():
        company.update(disclosed_at="2026-08-28T12:00:00+00:00", baseline_at="2026-08-27", source="Synthetic demonstration balance sheet", sources=[], reconstructed=False, estimated=True, note="Illustrative values only; not issuer disclosures.")
    return {
        "mode": "demo", "fetched_at": "2026-09-04T20:15:00+00:00",
        "prices": prices,
        "latest_quotes": {
            symbol: {"price": prices[symbol][-1]["close"], "as_of": "2026-09-04T20:00:00+00:00", "source": "Synthetic demo", "delayed": False}
            for symbol in ("BTC", "MSTR", "ASST")
        },
        "sentiment": sentiment, "supply_loss": supply,
        "companies": companies, "btc_equity_marks": marks,
        "sources": {"prices": "Synthetic demo", "sentiment": "Synthetic demo", "supply_loss": "Synthetic demo", "companies": "Synthetic demo"},
        "price_basis": "Synthetic prices and volumes; all observations illustrative",
        "btc_close_alignment": "Synthetic daily prices align to 16:00 ET",
        "notices": [
            "ILLUSTRATIVE DEMO — every price, volume, sentiment, on-chain value and balance input in this mode is synthetic or used illustratively, not a market observation.",
            "Demo ends Friday September 4, 2026. Seeded random innovations and shocks create illustrative market-like variation. " + demo_calendar,
            "Demo includes nine years of BTC prices for four plotted years of a valid 200-week SMA, three years of equity warmup, four years of supply data and synthetic sentiment from February 2018. ASST's January view uses prior ticker history for its SMA.",
        ],
    }
