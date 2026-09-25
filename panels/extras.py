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
from datetime import UTC, date, datetime, timedelta
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
SECTIONS = ("strategy", "strive", "fred", "yahoo", "onchain", "calendar", "markets")


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
PREFERRED_FIELDS = ("ufPrice", "timeStamp", "effYield", "taxEqvEffYield", "marketCredit", "currentDividend", "notional",
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
    try:  # BTC floor per instrument, used by the extra-data test copy only
        result["credit"] = {row["title"]: {key: row.get(key) for key in ("btcFloor", "notional", "isPreferred", "duration")}
                            for row in _json(STRATEGY + "credit") if row.get("title")}
    except Exception:  # optional: the panels never depend on it
        result["credit"] = {}
    return result


def _json_time(milliseconds):
    value = number(milliseconds)
    return datetime.fromtimestamp(value / 1000, UTC).isoformat() if value else None


# ── Strive ──────────────────────────────────────────────────────────────────
def _strive_dashboard_amplification() -> dict | None:
    """Strive's own "Amplification Ratio" inputs from its treasury dashboard (latest day)."""
    today = datetime.now(UTC).date()
    url = STRIVE.replace("base-data", "calculated") + "?" + urlencode(
        {"fromDate": (today - timedelta(days=10)).isoformat(), "toDate": today.isoformat()})
    rows = [row for row in (_json(url).get("data") or {}).get("btcNav") or [] if number(row.get("btcNav"))]
    if not rows:
        return None
    row = max(rows, key=lambda item: item.get("date", ""))
    nav, notional, debt = number(row["btcNav"]), number(row.get("preferredStockMarketCap")), number(row.get("debt")) or 0
    return {"date": row.get("date"), "btc_nav": nav, "sata_notional": notional, "debt": debt,
            "amplification_pct": (debt + notional) / nav * 100 if notional is not None else None}


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
    # Strive's stated annual rate (e.g. 0.13) from its public treasury feed. The
    # daily amount is that rate ÷ 12 split over the month's business days.
    stated, feed = None, {}
    try:
        feed = _json("https://strive.com/api/treasury").get("treasury") or {}
        stated = number(feed.get("dividendRate"))
    except Exception:  # the dashboard data above still gives the rate
        feed = {}
    computed = None
    if daily is not None and latest_paid.get("payDate"):
        pay = date.fromisoformat(latest_paid["payDate"])
        computed = sata_rate_from_daily(daily, pay.year, pay.month)
    return {
        "as_of": datetime.fromtimestamp(number(data.get("pulledAtTimestamp")) / 1000, UTC).isoformat()
        if number(data.get("pulledAtTimestamp")) else None,
        "cash": [{key: row.get(key) for key in ("date", "cash", "debt", "dividend_reserve_months", "marketable_securities")}
                 for row in cash[:20]],
        "shares": [{key: row.get(key) for key in ("date", "class_a_common", "class_b_common", "traditional_warrants",
                                                  "fully_diluted_shares", "options_legacy", "rsu_rsa")} for row in shares[:20]],
        "transactions": [{key: row.get(key) for key in ("transaction_date", "type", "btc_amount", "cost", "total_btc_holdings",
                                                        "cost_basis", "total_cost_basis")} for row in trades[:40]],
        "sata_dividends": [{key: row.get(key) for key in ("payDate", "recordDate", "cashAmount", "status")} for row in dividends[:120]],
        "sata_daily_dividend": daily,
        "sata_rate_pct": stated * 100 if stated else computed,
        "sata_rate_source": "strive.com/api/treasury dividendRate" if stated else "daily dividend × business days × 12",
        "treasury_feed": {key: feed.get(key) for key in ("asOf", "reserveMonths", "totalDividendCoverage", "dividendRate",
                                                         "btcHoldings", "cash", "marketableSecurities", "debt")} if feed else None,
        "sata_rate_as_of": latest_paid.get("payDate"),
        "dashboard_amplification": _optional(_strive_dashboard_amplification),
    }


def _optional(fetch):
    """A secondary figure that must never fail its section."""
    try:
        return fetch()
    except Exception:
        return None


def federal_holidays(year: int) -> set[date]:
    """US federal holidays as observed (Saturday → Friday, Sunday → Monday)."""
    def nth(month, weekday, n):
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))

    def last(month, weekday):
        day = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
        return day - timedelta(days=(day.weekday() - weekday) % 7)

    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 11, 11), date(year, 12, 25)]
    observed = {day - timedelta(days=1) if day.weekday() == 5 else day + timedelta(days=1) if day.weekday() == 6 else day
                for day in fixed}
    return observed | {nth(1, 0, 3), nth(2, 0, 3), last(5, 0), nth(9, 0, 1), nth(10, 0, 2), nth(11, 3, 4)}


def business_days_in_month(year: int, month: int) -> int:
    holidays = federal_holidays(year)
    day, count = date(year, month, 1), 0
    while day.month == month:
        if day.weekday() < 5 and day not in holidays:
            count += 1
        day += timedelta(days=1)
    return count


def sata_rate_from_daily(daily: float, year: int, month: int) -> float:
    """Annual % rate: the monthly dividend (daily × business days) × 12, to the nearest 0.05%."""
    return round(daily * business_days_in_month(year, month) * 12 * 100 / 5) * 5 / 100


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
        result = {series: job.result() for series, job in jobs.items()}
    # FRED republishes these a day or two late; overlay the same-day official
    # sources when they are newer. An overlay failure keeps the FRED series.
    for overlay in (fetch_treasury_curve, fetch_nyfed_rates):
        try:
            _overlay(result, overlay())
        except Exception:  # network or format change: FRED alone is still valid
            pass
    return result


def _overlay(series_map: dict, newer: dict) -> None:
    for series, rows in newer.items():
        if series not in series_map:
            continue
        known = series_map[series]
        last = known[-1][0] if known else ""
        known.extend([day, value] for day, value in sorted(rows) if day > last)


TREASURY_CURVE = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                  "{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
TREASURY_COLUMNS = {"3 Mo": "DGS3MO", "2 Yr": "DGS2", "10 Yr": "DGS10"}


def fetch_treasury_curve(today: date | None = None) -> dict:
    """US Treasury daily par yield curve: same-day source of FRED's DGS series."""
    today = today or datetime.now(UTC).date()
    text = _get(TREASURY_CURVE.format(year=today.year), "text/csv").decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    result = {series: [] for series in TREASURY_COLUMNS.values()}
    for row in reader:
        try:
            day = datetime.strptime(row["Date"], "%m/%d/%Y").date().isoformat()
        except (KeyError, ValueError):
            continue
        for column, series in TREASURY_COLUMNS.items():
            value = number(row.get(column))
            if value is not None:
                result[series].append((day, value))
    return result


def fetch_nyfed_rates() -> dict:
    """New York Fed SOFR and EFFR, published each morning for the prior business day."""
    result = {}
    for series, path in (("SOFR", "rates/secured/sofr/last/10.json"), ("DFF", "rates/unsecured/effr/last/10.json")):
        rows = json.loads(_get("https://markets.newyorkfed.org/api/" + path, "application/json"))["refRates"]
        result[series] = [(row["effectiveDate"], number(row["percentRate"])) for row in rows if number(row.get("percentRate")) is not None]
    return result


# ── Calendar ────────────────────────────────────────────────────────────────
FOMC_PAGE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
MONTHS = {name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1)}
MONTHS.update({name[:3]: index for name, index in list(MONTHS.items())})


def parse_fomc(html: str) -> list[str]:
    """Decision days (the last day of each scheduled meeting) from the Fed's calendar page."""
    import re
    days = []
    for block in re.split(r'<h4><a id="\d+">', html)[1:]:
        year = re.match(r"(\d{4}) FOMC Meetings", block)
        if not year:
            continue
        for month_text, day_text in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?'
                                               r'fomc-meeting__date[^>]*>([^<]+)<', block, re.S):
            if "notation" in day_text.lower() or "unscheduled" in day_text.lower():
                continue
            months = [MONTHS.get(part.strip().lower()[:3]) for part in month_text.split("/")]
            numbers = [int(value) for value in re.findall(r"\d+", day_text)]
            if not numbers or not months[0]:
                continue
            month = months[-1] if len(numbers) > 1 and numbers[-1] < numbers[0] and months[-1] else months[0]
            days.append(date(int(year.group(1)), month, numbers[-1]).isoformat())
    return sorted(set(days))


def fetch_earnings(ticker: str) -> dict | None:
    """Nasdaq's next earnings date. Usually Zacks' estimate until the company confirms it."""
    import re
    data = _json(f"https://api.nasdaq.com/api/analyst/{ticker}/earnings-date")
    text = ((data or {}).get("data") or {}).get("reportText") or ""
    found = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if not found:
        return None
    month, day, year = (int(value) for value in found.groups())
    return {"date": date(year, month, day).isoformat(), "estimated": "estimated" in text.lower(), "source": "nasdaq.com"}


def fetch_calendar() -> dict:
    result = {"fomc": parse_fomc(_get(FOMC_PAGE, "text/html").decode("utf-8", "replace")), "earnings": {}}
    for ticker in ("MSTR", "ASST"):
        try:
            result["earnings"][ticker] = fetch_earnings(ticker)
        except Exception:  # an estimate is optional; FOMC dates still stand
            result["earnings"][ticker] = None
    if not result["fomc"]:
        raise ValueError("FOMC calendar returned no meetings")
    return result


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


# ── Markets (the extra-data test copies) ────────────────────────────────────
DERIBIT = "https://www.deribit.com/api/v2/public/"


def _deribit_basis() -> dict:
    """Annualized basis of the BTC future expiring closest to three months out."""
    now = datetime.now(UTC)
    best = None
    for row in _json(DERIBIT + "get_book_summary_by_currency?" + urlencode({"currency": "BTC", "kind": "future"}))["result"]:
        name = row.get("instrument_name", "")
        try:
            expiry = datetime.strptime(name.split("-")[1], "%d%b%y").replace(hour=8, tzinfo=UTC)
        except (IndexError, ValueError):
            continue  # the perpetual
        days = (expiry - now).total_seconds() / 86400
        mark, index = number(row.get("mark_price")), number(row.get("estimated_delivery_price"))
        if days >= 30 and mark and index and (best is None or abs(days - 91) < abs(best["days"] - 91)):
            best = {"instrument": name, "days": round(days, 1), "mark": mark, "index": index,
                    "annualized_pct": (mark / index - 1) * 365 / days * 100}
    if best is None:
        raise ValueError("Deribit returned no dated BTC future")
    return best


def fetch_markets() -> dict:
    """BTC implied volatility (Deribit DVOL), 3-month futures basis and stablecoin supply (DefiLlama)."""
    now = datetime.now(UTC)
    start = int((now - timedelta(days=45)).timestamp() * 1000)
    dvol = _json(DERIBIT + "get_volatility_index_data?" + urlencode(
        {"currency": "BTC", "start_timestamp": start, "end_timestamp": int(now.timestamp() * 1000), "resolution": "1D"}))
    dvol_rows = [[datetime.fromtimestamp(row[0] / 1000, UTC).date().isoformat(), number(row[4])]
                 for row in dvol["result"]["data"] if number(row[4]) is not None]
    stable = _json("https://stablecoins.llama.fi/stablecoincharts/all")
    supply = [[datetime.fromtimestamp(int(row["date"]), UTC).date().isoformat(),
               number((row.get("totalCirculatingUSD") or {}).get("peggedUSD"))] for row in stable[-45:]]
    supply = [row for row in supply if row[1]]
    if not dvol_rows or not supply:
        raise ValueError("Deribit or DefiLlama returned no data")
    return {"as_of": now.isoformat(), "dvol": dvol_rows, "basis": _deribit_basis(), "stablecoins_usd": supply,
            "source": "Deribit public API (DVOL, futures); DefiLlama stablecoins (USD-pegged supply)"}


FETCHERS = {"strategy": fetch_strategy, "strive": fetch_strive, "fred": fetch_fred, "calendar": lambda: fetch_calendar(),
            "yahoo": fetch_yahoo, "onchain": fetch_onchain, "markets": fetch_markets}


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


STRATEGY_WEEKS = ROOT / "data" / "strategy-weekly-8k.json"


def strategy_weeks() -> dict[str, dict]:
    """Strategy's transcribed weekly 8-K figures by balance date (history before the feed)."""
    try:
        weeks = json.loads(STRATEGY_WEEKS.read_text(encoding="utf-8")).get("weeks") or []
    except (OSError, ValueError):
        return {}
    return {week["balance_date"]: week for week in weeks if week.get("balance_date")}
