"""Complete current-price snapshots with provider timestamps and atomic storage.

Stock metadata may describe an earlier regular-session close. Retrieval time
never substitutes for the provider's observation time, and a failed refresh
never replaces the previous complete cache.

Sessions (owner's rules, Sep 28, 2026): before the open on a NYSE trading day MSTR and
ASST take their latest pre-market trade (Yahoo 1-minute bars with extended hours, free);
during the session every stock is live; otherwise (evenings, weekends, holidays) the
close. Preferreds never use pre-market prices. Each quote carries its ``session`` and
``price_label`` says how to show it.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from http.client import HTTPException
import json
from math import isfinite
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


YAHOO_SYMBOLS = ("MSTR", "ASST", "STRC", "EURUSD=X")
REQUIRED_SYMBOLS = (*YAHOO_SYMBOLS, "BTC-USD")
SOURCE_URLS = {
    symbol: f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?interval=1d&range=5d"
    for symbol in YAHOO_SYMBOLS
}
SOURCE_URLS["BTC-USD"] = "https://api.strategy.com/btc/bitcoinKpis"
EXTENDED = ("MSTR", "ASST")  # the only symbols priced before the open
PRE_MARKET_URLS = {symbol: f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d&includePrePost=true"
                   for symbol in EXTENDED}
# CNBC's real-time quote stands in when Yahoo refuses (Oct 5, 2026: HTTP 429 to Streamlit Cloud all morning).
CNBC_SYMBOLS = {"MSTR": "MSTR", "ASST": "ASST", "STRC": "STRC", "EURUSD=X": "EUR="}
CNBC_URLS = {symbol: "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?" + urlencode(
    {"symbols": cnbc, "requestMethod": "itv", "noform": 1, "partnerId": 2, "fund": 1, "exthrs": 1, "output": "json"})
    for symbol, cnbc in CNBC_SYMBOLS.items()}
SESSIONS = ("pre-market", "regular", "close", "live")
NEW_YORK = ZoneInfo("America/New_York")
CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "current-prices.json"
FUTURE_TOLERANCE = timedelta(seconds=60)


@lru_cache(maxsize=1)
def _xnys():
    import exchange_calendars
    return exchange_calendars.get_calendar("XNYS")


def market_session(now: datetime | None = None) -> str:
    """'pre-market' from 4:00 am ET to the open on a NYSE trading day, 'regular' while it
    trades (early closes from the exchange calendar), else 'closed'."""
    local = _now(now).astimezone(NEW_YORK)
    day = local.date()
    try:
        calendar = _xnys()
        if not calendar.is_session(day.isoformat()):
            return "closed"
        opens = calendar.session_open(day.isoformat()).to_pydatetime()
        closes = calendar.session_close(day.isoformat()).to_pydatetime()
    except Exception:  # calendar unavailable or out of range: weekdays, 9:30 to 4:00
        if day.weekday() >= 5:
            return "closed"
        opens, closes = datetime.combine(day, time(9, 30), NEW_YORK), datetime.combine(day, time(16), NEW_YORK)
    if datetime.combine(day, time(4), NEW_YORK) <= local < opens:
        return "pre-market"
    return "regular" if opens <= local < closes else "closed"


def price_label(quote: dict) -> str:
    """How a price was observed: 'pre-market 8:11 AM ET', '11:02 AM ET' during the session,
    else its close, 'close Fri Sep 25'."""
    observed = datetime.fromisoformat(quote["as_of"]).astimezone(NEW_YORK)
    clock = f"{observed.hour % 12 or 12}:{observed:%M} {'AM' if observed.hour < 12 else 'PM'} ET"
    session = quote.get("session")
    if session == "pre-market":
        return f"pre-market {clock}"
    if session in ("regular", "live"):
        return clock
    return f"close {observed:%a %b} {observed.day}"


def _now(now: datetime | None = None) -> datetime:
    value = datetime.now(timezone.utc) if now is None else now
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("The current time must include a timezone")
    return value.astimezone(timezone.utc)


def _positive_number(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a positive finite number")
    try:
        valid = isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be a positive finite number")
    return float(value)


def _epoch(value, now: datetime, *, milliseconds: bool = False) -> str:
    stamp = _positive_number(value, "Quote timestamp")
    try:
        observed = datetime.fromtimestamp(stamp / (1000 if milliseconds else 1), timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("Quote timestamp is outside the supported date range") from exc
    if observed > now + FUTURE_TOLERANCE:
        raise ValueError("Quote timestamp is in the future")
    return observed.isoformat()


def _iso_timestamp(value, now: datetime, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO timestamp with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO timestamp with a timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    parsed = parsed.astimezone(timezone.utc)
    if parsed > now + FUTURE_TOLERANCE:
        raise ValueError(f"{label} is in the future")
    return parsed


def parse_yahoo_quote(payload: dict, expected_symbol: str, now: datetime) -> dict:
    """Extract the named security's regular-market quote without a price fallback."""
    now = _now(now)
    if expected_symbol not in YAHOO_SYMBOLS:
        raise ValueError("Unexpected Yahoo symbol")
    try:
        chart = payload["chart"]
        results = chart["result"]
        if chart.get("error") or not isinstance(results, list) or len(results) != 1:
            raise ValueError("Yahoo returned an error or no unique quote")
        meta = results[0]["meta"]
        if meta["symbol"] != expected_symbol:
            raise ValueError("Yahoo quote symbol does not match the requested symbol")
        price = _positive_number(meta["regularMarketPrice"], f"{expected_symbol} price")
        observed = _epoch(meta["regularMarketTime"], now)
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ValueError(f"Malformed Yahoo quote for {expected_symbol}") from exc
    return {"symbol": expected_symbol, "price": price, "as_of": observed,
            "session": "regular" if market_session(now) == "regular" else "close",
            "source_url": SOURCE_URLS[expected_symbol]}


def parse_pre_market(payload: dict, symbol: str, now: datetime) -> dict | None:
    """The latest pre-market trade today (a 1-minute bar with a price), or None."""
    now = _now(now)
    try:
        result = payload["chart"]["result"][0]
        if result["meta"]["symbol"] != symbol:
            raise ValueError("Yahoo quote symbol does not match the requested symbol")
        stamps = result.get("timestamp") or []
        closes = result["indicators"]["quote"][0].get("close") or []
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Malformed Yahoo pre-market bars for {symbol}") from exc
    start = datetime.combine(now.astimezone(NEW_YORK).date(), time(4), NEW_YORK).timestamp()
    trades = [(stamp, close) for stamp, close in zip(stamps, closes)
              if isinstance(close, (int, float)) and close > 0 and start <= stamp <= now.timestamp()]
    if not trades:
        return None
    stamp, price = trades[-1]
    return {"symbol": symbol, "price": _positive_number(price, f"{symbol} pre-market price"),
            "as_of": _epoch(stamp, now), "session": "pre-market", "source_url": PRE_MARKET_URLS[symbol]}


def _pre_market(now: datetime) -> dict:
    """Pre-market quotes for MSTR and ASST; a symbol with no trade yet, or a failed request, keeps its close."""
    found = {}
    with ThreadPoolExecutor(max_workers=len(EXTENDED)) as pool:
        jobs = {symbol: pool.submit(_fetch_json, PRE_MARKET_URLS[symbol]) for symbol in EXTENDED}
        for symbol, job in jobs.items():
            try:
                quote_ = parse_pre_market(job.result(), symbol, now)
            except Exception:  # network or format: the close stands
                continue
            if quote_:
                found[symbol] = quote_
    return found


def _cnbc_number(value) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError("CNBC price is not a number") from exc


def _cnbc_time(value) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
    except (TypeError, ValueError) as exc:
        raise ValueError("CNBC quote time is malformed") from exc


def parse_cnbc_quote(payload: dict, symbol: str, now: datetime) -> dict:
    """CNBC's real-time quote, labelled by session like Yahoo's. For MSTR and ASST before the open, its
    pre-market trade from today stands in for the close, as Yahoo's 1-minute bars do."""
    now = _now(now)
    try:
        rows = payload["FormattedQuoteResult"]["FormattedQuote"]
        row = next(row for row in rows if isinstance(row, dict) and row.get("symbol") == CNBC_SYMBOLS[symbol])
    except (KeyError, TypeError, StopIteration) as exc:
        raise ValueError(f"Malformed CNBC quote for {symbol}") from exc
    price = _positive_number(_cnbc_number(row.get("last")), f"{symbol} price")
    observed = _cnbc_time(row.get("last_time")).astimezone(timezone.utc)
    if observed > now + FUTURE_TOLERANCE:
        raise ValueError("Quote timestamp is in the future")
    session = market_session(now)
    quote_ = {"symbol": symbol, "price": price, "as_of": observed.isoformat(),
              "session": "regular" if session == "regular" else "close", "source_url": CNBC_URLS[symbol]}
    extended = row.get("ExtendedMktQuote") or {}
    if session == "pre-market" and symbol in EXTENDED and extended.get("type") == "PRE_MKT":
        try:
            stamp = _cnbc_time(extended.get("last_time")).astimezone(timezone.utc)
            last = _positive_number(_cnbc_number(extended.get("last")), f"{symbol} pre-market price")
        except ValueError:
            return quote_  # no usable pre-market trade: the close stands
        start = datetime.combine(now.astimezone(NEW_YORK).date(), time(4), NEW_YORK)
        if start <= stamp <= now + FUTURE_TOLERANCE:
            quote_.update(price=last, as_of=stamp.isoformat(), session="pre-market")
    return quote_


def parse_btc_quote(payload: dict, now: datetime) -> dict:
    """Use Strategy's Bitcoin price and its millisecond observation timestamp."""
    now = _now(now)
    try:
        result = payload["results"]
        price = _positive_number(result["ufPrice"], "BTC-USD price")
        observed = _epoch(result["msTimestamp"], now, milliseconds=True)
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed Strategy Bitcoin quote") from exc
    return {"symbol": "BTC-USD", "price": price, "as_of": observed, "session": "live",
            "source_url": SOURCE_URLS["BTC-USD"]}


def _validate_snapshot(snapshot: dict, now: datetime) -> dict:
    """Return canonical UTC data; historical observation age is not an error."""
    if not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 1:
        raise ValueError("Unsupported current-price cache schema")
    fetched = _iso_timestamp(snapshot.get("fetched_at"), now, "Retrieval timestamp")
    records = snapshot.get("quotes")
    if not isinstance(records, dict) or set(records) != set(REQUIRED_SYMBOLS):
        raise ValueError("Current prices require exactly MSTR, ASST, STRC, EURUSD=X and BTC-USD")
    quotes = {}
    for symbol in REQUIRED_SYMBOLS:
        record = records[symbol]
        if not isinstance(record, dict) or record.get("symbol") != symbol:
            raise ValueError(f"Saved quote does not match {symbol}")
        price = _positive_number(record.get("price"), f"{symbol} price")
        observed = _iso_timestamp(record.get("as_of"), now, f"{symbol} observation timestamp")
        if observed > fetched + FUTURE_TOLERANCE:
            raise ValueError(f"{symbol} observation is after the recorded retrieval")
        source = record.get("source_url")
        from_cnbc = symbol in CNBC_URLS and source == CNBC_URLS[symbol]
        if not from_cnbc and source not in {SOURCE_URLS[symbol], PRE_MARKET_URLS.get(symbol, SOURCE_URLS[symbol])}:
            raise ValueError(f"Saved {symbol} quote has an unexpected source URL")
        session = record.get("session")
        # Yahoo's pre-market trades come only from its 1-minute bars; CNBC's one quote serves every session.
        if session is not None and (session not in SESSIONS or (not from_cnbc and (session == "pre-market") != (source != SOURCE_URLS[symbol]))):
            raise ValueError(f"Saved {symbol} quote has an unexpected session")
        quotes[symbol] = {"symbol": symbol, "price": price, "as_of": observed.isoformat(),
                          **({"session": session} if session else {}), "source_url": source}
    return {"schema_version": 1, "fetched_at": fetched.isoformat(), "quotes": quotes}


YAHOO_HOST, YAHOO_MIRROR = "https://query1.finance.yahoo.com/", "https://query2.finance.yahoo.com/"


def _fetch_once(url: str) -> dict:
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; MondayCapitalReport/1.0)",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def _fetch_json(url: str) -> dict:
    """Yahoo serves the same chart API from query2, so a refused or failed query1 request tries it once."""
    try:
        return _fetch_once(url)
    except (OSError, ValueError, HTTPException):
        if not url.startswith(YAHOO_HOST):
            raise
        return _fetch_once(YAHOO_MIRROR + url[len(YAHOO_HOST):])


def failure_reason(error: Exception) -> str:
    """A short reason for the page's notice: 'HTTP 429', 'URLError: timed out'."""
    code = getattr(error, "code", None)
    if isinstance(code, int):
        return f"HTTP {code}"
    return f"{type(error).__name__}: {error}"[:120]


def pull_current_prices(*, now: datetime | None = None, fallback: dict | None = None) -> dict:
    """Fetch and validate all five prices.

    Without ``fallback`` any failure raises and nothing partial is returned. With an earlier complete
    snapshot as ``fallback`` (the page passes its last good copy), a Yahoo quote that fails comes from
    CNBC instead, and a source that still fails keeps that snapshot's quote, at its own earlier
    observation time, listed under ``"saved"`` with the reason. One refused request no longer throws
    away the other live prices (Oct 5, 2026: Yahoo answered Streamlit Cloud with HTTP 429 and the page
    sat on saved quotes all morning). If every source fails it still raises.

    Call save_current_prices only after this function succeeds. No cache is
    modified during network requests or parsing.
    """
    if now is not None:
        _now(now)

    def attempt(url):
        try:
            return _fetch_json(url), None
        except Exception as error:  # reported per source below
            return None, error

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = dict(zip(REQUIRED_SYMBOLS, pool.map(attempt, (SOURCE_URLS[symbol] for symbol in REQUIRED_SYMBOLS))))
    fetched = _now(now)
    quotes, failed = {}, {}
    for symbol in REQUIRED_SYMBOLS:
        payload, error = results[symbol]
        try:
            if error is not None:
                raise error
            quotes[symbol] = (parse_btc_quote(payload, fetched) if symbol == "BTC-USD"
                              else parse_yahoo_quote(payload, symbol, fetched))
        except Exception as problem:
            if fallback is None:
                raise
            failed[symbol] = failure_reason(problem)
    for symbol in [symbol for symbol in failed if symbol in CNBC_URLS]:
        try:
            quotes[symbol] = parse_cnbc_quote(_fetch_json(CNBC_URLS[symbol]), symbol, fetched)
            del failed[symbol]
        except Exception as problem:
            failed[symbol] += f"; CNBC {failure_reason(problem)}"
    if len(failed) == len(REQUIRED_SYMBOLS):
        raise ValueError("No price source answered: " + "; ".join(f"{s} {why}" for s, why in failed.items()))
    if market_session(fetched) == "pre-market":
        quotes.update(_pre_market(fetched))
        for symbol in EXTENDED if fallback is not None else ():
            if symbol in quotes and quotes[symbol]["session"] != "pre-market":
                try:  # Yahoo's bars failed or show no trade yet: CNBC's pre-market trade, if any
                    cnbc = parse_cnbc_quote(_fetch_json(CNBC_URLS[symbol]), symbol, fetched)
                except Exception:
                    continue
                if cnbc["session"] == "pre-market":
                    quotes[symbol] = cnbc
    saved = {}
    if failed:
        earlier = _validate_snapshot(fallback, fetched)["quotes"]
        for symbol, reason in failed.items():
            if symbol not in quotes:  # else a pre-market trade stood in for the failed close
                quotes[symbol] = earlier[symbol]
                saved[symbol] = reason
    snapshot = _validate_snapshot({"schema_version": 1, "fetched_at": fetched.isoformat(),
                                   "quotes": quotes}, fetched)
    if saved:
        snapshot["saved"] = saved
    return snapshot


def load_current_prices(path: Path | None = None, *, now: datetime | None = None) -> dict | None:
    """Read a complete cache, preserving older session timestamps without an age limit."""
    path = CACHE_PATH if path is None else Path(path)
    if not path.exists():
        return None
    return _validate_snapshot(json.loads(path.read_text(encoding="utf-8")), _now(now))


def save_current_prices(snapshot: dict, path: Path | None = None, *, now: datetime | None = None) -> Path:
    """Validate first, then replace the cache atomically on the same filesystem."""
    validated = _validate_snapshot(snapshot, _now(now))
    path = CACHE_PATH if path is None else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            pending = Path(handle.name)
            json.dump(validated, handle, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        pending.replace(path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return path
