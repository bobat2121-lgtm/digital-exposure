"""Complete current-price snapshots with provider timestamps and atomic storage.

Stock metadata may describe an earlier regular-session close. Retrieval time
never substitutes for the provider's observation time, and a failed refresh
never replaces the previous complete cache.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from math import isfinite
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote
from urllib.request import Request, urlopen


YAHOO_SYMBOLS = ("MSTR", "ASST", "STRC", "EURUSD=X")
REQUIRED_SYMBOLS = (*YAHOO_SYMBOLS, "BTC-USD")
SOURCE_URLS = {
    symbol: f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?interval=1d&range=5d"
    for symbol in YAHOO_SYMBOLS
}
SOURCE_URLS["BTC-USD"] = "https://api.strategy.com/btc/bitcoinKpis"
CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "current-prices.json"
FUTURE_TOLERANCE = timedelta(seconds=60)


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
            "source_url": SOURCE_URLS[expected_symbol]}


def parse_btc_quote(payload: dict, now: datetime) -> dict:
    """Use Strategy's Bitcoin price and its millisecond observation timestamp."""
    now = _now(now)
    try:
        result = payload["results"]
        price = _positive_number(result["ufPrice"], "BTC-USD price")
        observed = _epoch(result["msTimestamp"], now, milliseconds=True)
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed Strategy Bitcoin quote") from exc
    return {"symbol": "BTC-USD", "price": price, "as_of": observed,
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
        if record.get("source_url") != SOURCE_URLS[symbol]:
            raise ValueError(f"Saved {symbol} quote has an unexpected source URL")
        quotes[symbol] = {"symbol": symbol, "price": price, "as_of": observed.isoformat(),
                          "source_url": SOURCE_URLS[symbol]}
    return {"schema_version": 1, "fetched_at": fetched.isoformat(), "quotes": quotes}


def _fetch_json(url: str) -> dict:
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; MondayCapitalReport/1.0)",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def pull_current_prices(*, now: datetime | None = None) -> dict:
    """Fetch and validate all five prices, returning no partial update.

    Call save_current_prices only after this function succeeds. No cache is
    modified during network requests or parsing.
    """
    if now is not None:
        _now(now)
    with ThreadPoolExecutor(max_workers=5) as pool:
        payloads = dict(zip(REQUIRED_SYMBOLS, pool.map(_fetch_json, (
            SOURCE_URLS[symbol] for symbol in REQUIRED_SYMBOLS
        ))))
    fetched = _now(now)
    quotes = {symbol: parse_yahoo_quote(payloads[symbol], symbol, fetched)
              for symbol in YAHOO_SYMBOLS}
    quotes["BTC-USD"] = parse_btc_quote(payloads["BTC-USD"], fetched)
    return _validate_snapshot({"schema_version": 1, "fetched_at": fetched.isoformat(),
                               "quotes": quotes}, fetched)


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
