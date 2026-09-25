"""Public, keyless market inputs shared by the preview panels.

Every section is fetched independently. A failed section falls back to the
last saved snapshot (``data/preview-extras.json``) and is marked stale, so a
panel never mixes invented values with live ones. Missing values stay None.

Sources (no API keys):
- api.strategy.com  bitcoinKpis, mstrKpiData, {strc,strf,strk,strd,stre}KpiData
- strive.com/treasury/api/dashboard/base-data
- fred.stlouisfed.org fredgraph.csv (Treasury, SOFR, Fed funds, ICE BofA indices)
- query1.finance.yahoo.com chart API (preferreds, DXY, 10Y, PFF, HYG)
- charts-cdn.checkonchain.com public Plotly charts (MVRV, realized price, Puell)
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import UTC, date, datetime
import io
import json
import math
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "preview-extras.json"
USER_AGENT = "Mozilla/5.0 (compatible; DigitalCreditReport/1.0)"
MAX_BYTES = 9_000_000

STRATEGY = "https://api.strategy.com/btc/"
STRIVE = "https://strive.com/treasury/api/dashboard/base-data"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"
CHECKONCHAIN = "https://charts-cdn.checkonchain.com/btconchain/"

PREFERREDS = ("STRC", "STRF", "STRK", "STRD", "STRE")
FRED_SERIES = {
    "DGS10": "10-year Treasury", "DGS2": "2-year Treasury", "DGS3MO": "3-month Treasury bill",
    "DFF": "Effective fed funds", "SOFR": "SOFR",
    "BAMLH0A0HYM2EY": "ICE BofA US High Yield effective yield",
    "BAMLC0A0CMEY": "ICE BofA US Corporate (IG) effective yield",
}
YAHOO_SYMBOLS = ("STRC", "SATA", "STRF", "STRK", "STRD", "PFF", "HYG", "DX-Y.NYB", "^TNX", "BTC-USD")
SECTIONS = ("strategy", "strive", "fred", "yahoo", "onchain")


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").strip()
        if not value:
            return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _get(url: str, accept: str = "application/json") -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urlopen(request, timeout=20) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Response exceeds the size limit")
    return raw


def _json(url: str):
    return json.loads(_get(url))


# ── Strategy ────────────────────────────────────────────────────────────────
BTC_FIELDS = ("latestPrice", "btcHoldings", "mNav", "amplification", "debtByBN", "prefByBN", "debtPrefByBN",
              "totalAnnualDividends", "btcYearsOfDividends", "usdMonthsOfDividends", "totalYearsOfCoverage",
              "btcBreakevenArr", "bitcoinHurdleArr", "realizedPrice", "ma200w", "fearGreedIndex",
              "etfNetFlows7d", "futuresBasis3m", "btcDominanceExStables", "netBtcReserve", "totalReserve")
PREFERRED_FIELDS = ("ufPrice", "timeStamp", "effYield", "taxEqvEffYield", "currentDividend", "notional",
                    "vwap1mo", "impliedVolatility", "averageVolume", "dailyVolume", "sharesVolume",
                    "nextRecordDate", "nextPayoutDate", "riskFreeRate", "marketCap")


def fetch_strategy() -> dict:
    btc = _json(STRATEGY + "bitcoinKpis")["results"]
    result = {"btc": {key: btc.get(key) for key in BTC_FIELDS}, "as_of": _json_time(btc.get("msTimestamp"))}
    for key in ("btcHoldings",):
        result["btc"][key] = number(result["btc"][key])
    mstr = _json(STRATEGY + "mstrKpiData")[0]
    result["mstr"] = {key: mstr.get(key) for key in ("ufPrice", "timeStamp", "debt", "pref", "entVal", "marketCap", "btcCor")}
    preferreds = {}
    for series in PREFERREDS:
        row = _json(STRATEGY + series.lower() + "KpiData")[0]
        if row.get("company") != series:
            raise ValueError(f"Strategy returned the wrong series for {series}")
        item = {key: row.get(key) for key in PREFERRED_FIELDS}
        item["dividendHistory"] = [
            {key: entry.get(key) for key in ("period", "recordDate", "payDate", "cashAmount", "rate")}
            for entry in row.get("dividendHistory") or [] if isinstance(entry, dict)][-24:]
        preferreds[series] = item
    result["preferreds"] = preferreds
    return result


def _json_time(milliseconds):
    value = number(milliseconds)
    return datetime.fromtimestamp(value / 1000, UTC).isoformat() if value else None


# ── Strive ──────────────────────────────────────────────────────────────────
def fetch_strive() -> dict:
    data = _json(STRIVE)["data"]
    cash = sorted(data.get("cashDebt") or [], key=lambda row: row.get("date", ""), reverse=True)
    shares = sorted(data.get("shares") or [], key=lambda row: row.get("date", ""), reverse=True)
    trades = sorted(data.get("transactions") or [], key=lambda row: row.get("transaction_date", ""), reverse=True)
    dividends = sorted((row for row in data.get("preferredDividends") or [] if row.get("ticker") == "SATA"),
                       key=lambda row: row.get("payDate", ""), reverse=True)
    paid = [row for row in dividends if row.get("status") == "paid"]
    latest_paid = paid[0] if paid else {}
    daily = number(latest_paid.get("cashAmount"))
    return {
        "as_of": datetime.fromtimestamp(number(data.get("pulledAtTimestamp")) / 1000, UTC).isoformat()
        if number(data.get("pulledAtTimestamp")) else None,
        "cash": [{key: row.get(key) for key in ("date", "cash", "debt", "dividend_reserve_months", "marketable_securities")}
                 for row in cash[:20]],
        "shares": [{key: row.get(key) for key in ("date", "class_a_common", "class_b_common", "traditional_warrants",
                                                  "fully_diluted_shares", "options_legacy", "rsu_rsa")} for row in shares[:20]],
        "transactions": [{key: row.get(key) for key in ("transaction_date", "type", "btc_amount", "cost", "total_btc_holdings",
                                                        "cost_basis", "total_cost_basis")} for row in trades[:40]],
        "sata_dividends": [{key: row.get(key) for key in ("payDate", "recordDate", "cashAmount", "status")} for row in dividends[:60]],
        # SATA pays every business day; 252 payments per year is the stated-rate basis.
        "sata_daily_dividend": daily,
        "sata_rate_pct": daily * 252 if daily is not None else None,
        "sata_rate_as_of": latest_paid.get("payDate"),
    }


# ── FRED ────────────────────────────────────────────────────────────────────
def fetch_fred_series(series: str, keep: int = 420) -> list[list]:
    text = _get(FRED + urlencode({"id": series}), "text/csv").decode("utf-8")
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 2 or row[0] in ("DATE", "observation_date"):
            continue
        value = number(row[1])
        if value is not None:
            rows.append([row[0], value])
    if not rows:
        raise ValueError(f"FRED {series} returned no observations")
    return rows[-keep:]


def fetch_fred() -> dict:
    with ThreadPoolExecutor(max_workers=len(FRED_SERIES)) as pool:
        jobs = {series: pool.submit(fetch_fred_series, series) for series in FRED_SERIES}
        return {series: job.result() for series, job in jobs.items()}


# ── Yahoo ───────────────────────────────────────────────────────────────────
def fetch_yahoo_symbol(symbol: str, span: str = "1y") -> dict:
    params = urlencode({"interval": "1d", "range": span, "includePrePost": "false", "events": "splits"})
    chart = _json(YAHOO + quote(symbol, safe="") + "?" + params)["chart"]
    if chart.get("error") or not chart.get("result"):
        raise ValueError(f"Yahoo returned no chart for {symbol}")
    result = chart["result"][0]
    meta = result.get("meta", {})
    if meta.get("symbol") != symbol:
        raise ValueError("Yahoo symbol mismatch")
    quotes = result["indicators"]["quote"][0]
    rows = []
    for index, stamp in enumerate(result.get("timestamp") or []):
        close = number((quotes.get("close") or [None])[index] if index < len(quotes.get("close") or []) else None)
        if close is None or close <= 0:
            continue
        volume = number((quotes.get("volume") or [None])[index] if index < len(quotes.get("volume") or []) else None)
        day = datetime.fromtimestamp(stamp, UTC).date().isoformat()
        rows.append({"date": day, "close": close, "volume": volume})
    return {"rows": rows, "price": number(meta.get("regularMarketPrice")),
            "as_of": datetime.fromtimestamp(meta["regularMarketTime"], UTC).isoformat() if meta.get("regularMarketTime") else None}


def fetch_yahoo() -> dict:
    with ThreadPoolExecutor(max_workers=len(YAHOO_SYMBOLS)) as pool:
        jobs = {symbol: pool.submit(fetch_yahoo_symbol, symbol) for symbol in YAHOO_SYMBOLS}
        return {symbol: job.result() for symbol, job in jobs.items()}


# ── Checkonchain ────────────────────────────────────────────────────────────
def _plot_series(page: str) -> dict:
    import sys
    friday = ROOT / "sources" / "friday"
    if str(friday) not in sys.path:
        sys.path.insert(0, str(friday))
    from friday import supply
    traces, _ = supply._plot(_get(CHECKONCHAIN + page, "text/html").decode("utf-8"))
    series = {}
    for trace in traces:
        if not isinstance(trace, dict) or not trace.get("name") or not isinstance(trace.get("x"), list):
            continue
        values = supply._values(trace.get("y"))
        points = [(str(x)[:10], number(y)) for x, y in zip(trace["x"], values)]
        series[trace["name"]] = [[day, value] for day, value in points if value is not None]
    return series


def _last(rows):
    return rows[-1] if rows else [None, None]


def fetch_onchain() -> dict:
    mvrv = _plot_series("unrealised/mvrv_all/mvrv_all_light.html")
    puell = _plot_series("mining/puellmultiple/puellmultiple_light.html")
    if "MVRV" not in mvrv or "Realised Price" not in mvrv or "Puell Multiple" not in puell:
        raise ValueError("Checkonchain chart structure changed")
    weekly = [row for row in mvrv["Realised Price"] if date.fromisoformat(row[0]).weekday() == 4][-260:]
    day, value = _last(mvrv["MVRV"])
    return {
        "as_of": day,
        "mvrv": value, "mvrv_mean": _last(mvrv.get("Mean", []))[1], "mvrv_plus1sd": _last(mvrv.get("+1.0sd", []))[1],
        "realized_price": _last(mvrv["Realised Price"])[1], "realized_weekly": weekly,
        "puell": _last(puell["Puell Multiple"])[1],
        "puell_low": _last(puell.get("Mean-0.85sd", []))[1], "puell_high": _last(puell.get("Mean+1.25sd", []))[1],
        "source": "Checkonchain public charts",
    }


FETCHERS = {"strategy": fetch_strategy, "strive": fetch_strive, "fred": fetch_fred,
            "yahoo": fetch_yahoo, "onchain": fetch_onchain}


def load_snapshot() -> dict:
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_extras(sections=SECTIONS, *, offline: bool = False) -> dict:
    """Fetch each section live; fall back per section to the saved snapshot."""
    saved = load_snapshot()
    result = {"fetched_at": datetime.now(UTC).isoformat(), "errors": [], "stale": []}
    if offline:
        for section in sections:
            result[section] = saved.get(section)
            result["stale"].append(section)
        result["fetched_at"] = saved.get("fetched_at")
        return result
    with ThreadPoolExecutor(max_workers=len(sections)) as pool:
        jobs = {section: pool.submit(FETCHERS[section]) for section in sections}
        for section, job in jobs.items():
            try:
                result[section] = job.result()
            except Exception as exc:  # network, provider or validation failure
                result["errors"].append(f"{section}: {type(exc).__name__}")
                result[section] = saved.get(section)
                result["stale"].append(section)
    return result


def save_snapshot(extras: dict) -> Path:
    payload = {key: value for key, value in extras.items() if key not in ("errors", "stale")}
    SNAPSHOT.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return SNAPSHOT


def fred_latest(extras: dict, series: str):
    rows = ((extras.get("fred") or {}).get(series)) or []
    return (rows[-1][0], rows[-1][1]) if rows else (None, None)
