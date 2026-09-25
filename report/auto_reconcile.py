"""Automatic Monday reconciliation for balance dates without reviewed inputs.

Reviewed entries in ``data/report-supplements.json`` always win. For a newer
weekly filing this module derives the same dated inputs the scheduled review
used to add by hand, from the filing chain and public data:

Strategy (rolled forward from the latest reviewed reconciliation file):
- basic shares: last reviewed Class A + B plus 8-K ATM shares sold less
  repurchased (employee issuance between reviews is not visible; the drift is
  ~0.002% a week and the next reviewed count resets it);
- preferred shares per series: last reviewed count plus 8-K issued less
  repurchased;
- preferred claims: max($100, ten-close mean before the balance business day)
  per USD series (STRE EUR 100) plus ordinary 30/360 accrual since the last
  scheduled payment (STRC semi-monthly from strategy.com; others quarterly);
- debt: last reviewed principal carried forward.

Strive: SATA shares from the filing at max($100, ten-close mean, prior close)
(the conservative certificate branch), daily dividends paid through Friday,
debt from the Strive dashboard (zero when absent).

Comparison marks: BTC and EUR/USD at the prior filing's SEC acceptance hour
(Yahoo hourly), STRC as the prior Strive filing's fair value ÷ held shares.
Strive's common-capital VWAP uses report.equity_vwap for the filing week.

Every generated entry is flagged ``auto_reconciled`` with its basis, so the
page can say which balances are awaiting review. Any failure leaves the entry
missing, which keeps the last complete report exactly as before.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import json
import os
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

DATA = Path(__file__).resolve().parents[1] / "data"
DEFAULT_SUPPLEMENTS = DATA / "report-supplements.json"
TTL = 1800
USD_SERIES = ("STRC", "STRF", "STRK", "STRD")
RATES = {"STRF": 10.0, "STRK": 8.0, "STRD": 10.0, "STRE": 10.0}
_cache: dict = {}
_lock = Lock()


def enabled(supplements_path: Path) -> bool:
    """On for the production data directory unless DCR_AUTO_RECONCILE=0."""
    return os.environ.get("DCR_AUTO_RECONCILE", "1") != "0" and Path(supplements_path) == DEFAULT_SUPPLEMENTS


def _cached(key, fetch):
    with _lock:
        hit = _cache.get(key)
        if hit and monotonic() - hit[0] < TTL:
            return hit[1]
    value = fetch()
    with _lock:
        _cache[key] = (monotonic(), value)
    return value


def _get_json(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (DigitalCreditReport/1.0)", "Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def _yahoo(symbol, interval, span):
    def fetch():
        params = urlencode({"interval": interval, "range": span, "includePrePost": "false", "events": "splits"})
        result = _get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?{params}")["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        return [(stamp, close) for stamp, close in zip(result.get("timestamp") or [], closes) if close]
    return _cached(("yahoo", symbol, interval, span), fetch)


def _strc_dividends():
    return _cached(("strc",), lambda: _get_json("https://api.strategy.com/btc/strcKpiData")[0])


def days360(start: date, end: date) -> int:
    """30/360 US day count, as used by the certificates' accrual convention."""
    d1, d2 = min(start.day, 30), end.day
    if d1 == 30 and d2 == 31:
        d2 = 30
    return 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)


def business_day(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _daily_closes(symbol, before: date, count=10):
    rows = [(datetime.fromtimestamp(stamp, UTC).date(), close) for stamp, close in _yahoo(symbol, "1d", "6mo")]
    return [close for day, close in rows if day < before][-count:]


def _base(symbol, balance: date, *, prior_close=False):
    closes = _daily_closes(symbol, business_day(balance))
    if len(closes) < 10:
        raise ValueError(f"{symbol}: fewer than ten closes before {balance}")
    candidates = [100.0, sum(closes) / len(closes)] + ([closes[-1]] if prior_close else [])
    return round(max(candidates), 3), closes


def _hour_mark(symbol, instant: datetime):
    """Close of the hourly bar containing ``instant``; daily close if older."""
    bars = _yahoo(symbol, "1h", "1mo")
    target = instant.timestamp()
    eligible = [(stamp, close) for stamp, close in bars if stamp <= target]
    if eligible and target - eligible[-1][0] <= 3 * 3600:
        return eligible[-1][1]
    daily = [(datetime.fromtimestamp(stamp, UTC).date(), close) for stamp, close in _yahoo(symbol, "1d", "6mo")]
    match = [close for day, close in daily if day <= instant.date()]
    if not match:
        raise ValueError(f"{symbol}: no mark at {instant}")
    return match[-1]


def _strc_accrual(balance: date):
    """(annual $ rate, 30/360 days) since the last STRC payment on or before balance."""
    history = _strc_dividends().get("dividendHistory") or []
    pays = sorted((date.fromisoformat(row["payDate"]), row) for row in history if row.get("payDate"))
    past = [(day, row) for day, row in pays if day <= balance]
    upcoming = [(day, row) for day, row in pays if day > balance]
    if not past:
        raise ValueError("STRC payment history unavailable")
    rate = upcoming[0][1].get("rate") if upcoming else _strc_dividends().get("currentDividend")
    return float(rate), days360(past[-1][0], balance)


def _quarter_start(balance: date) -> date:
    ends = [date(balance.year - 1, 12, 31)] + [date(balance.year, month, day) for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))]
    return max(day for day in ends if day <= balance)


def _seed():
    """Latest reviewed reconciliation with Strategy share and series counts."""
    for path in sorted(DATA.glob("reconciliation-*.json"), reverse=True):
        record = json.loads(path.read_text(encoding="utf-8"))
        shares, claims = record.get("strategy_shares") or {}, record.get("strategy_claims") or {}
        if shares.get("balance_date") and shares.get("basic_shares") and claims:
            return {"date": shares["balance_date"], "common": shares["basic_shares"],
                    "series": {series: row["shares"] for series, row in claims.items()}, "source": path.name}
    return None


def _strategy_entry(balance: date, common, series, debt, facts):
    notes, usd, eur = [], 0.0, 0.0
    rate, strc_days = _strc_accrual(balance)
    quarter_days = days360(_quarter_start(balance), balance)
    components = {}
    for name, shares in series.items():
        if name == "STRE":
            base, per = 100.0, RATES["STRE"] * quarter_days / 360
            eur += shares * (base + per)
            components[name] = {"shares": shares, "base": base, "accrual_days": quarter_days, "currency": "EUR"}
            continue
        base, _ = _base(name, balance)
        annual, days = (rate, strc_days) if name == "STRC" else (RATES[name], quarter_days)
        usd += shares * (base + annual * days / 360)
        components[name] = {"shares": shares, "base": base, "accrual_days": days, "annual": annual}
    notes.append(f"Basic shares roll the reviewed count forward with 8-K ATM activity; employee issuance since review is not included.")
    notes.append(f"Claims: max($100, ten-close mean) plus 30/360 accrual — STRC {strc_days} days at ${rate:g}, quarterly series {quarter_days} days; scheduled payments assumed paid.")
    return {"effective_common_shares": common, "debt_principal": debt, "preferred_claims_usd": usd,
            "preferred_claims_eur": eur, "auto_reconciled": True, "components": components,
            "limitations": " ".join(notes),
            "sources": ["https://api.strategy.com/btc/strcKpiData", "https://query1.finance.yahoo.com/v8/finance/chart/"]}


def augment(rows: list, supplements: dict, *, now: datetime | None = None) -> tuple[dict, list[str]]:
    """Return supplements with auto-reconciled entries for unreviewed filings."""
    result = deepcopy(supplements)
    balances = result.setdefault("balances", {})
    notes = []
    by_ticker = {}
    for row in sorted(rows, key=lambda item: item["extracted"]["balanceDate"]):
        by_ticker.setdefault(row["ticker"], {})[row["extracted"]["balanceDate"]] = row

    # Strategy: roll forward from the latest reviewed reconciliation.
    seed = _seed()
    mstr = by_ticker.get("MSTR", {})
    reviewed = balances.setdefault("MSTR", {})
    if seed and any(day > seed["date"] and day not in reviewed for day in mstr):
        common, series = seed["common"], dict(seed["series"])
        debt = (reviewed.get(seed["date"]) or {}).get("debt_principal")
        for day in sorted(mstr):
            if day <= seed["date"]:
                continue
            extraction = mstr[day]["extracted"]
            facts, securities = extraction["facts"], extraction.get("securities", {})
            common += (facts.get("common_issued_shares") or 0) - (facts.get("common_repurchased_shares") or 0)
            for name, activity in securities.items():
                if name == "MSTR":
                    continue
                series[name] = series.get(name, 0) + (activity.get("issuedShares") or 0) - (activity.get("repurchasedShares") or 0)
            existing = reviewed.get(day)
            if existing and existing.get("effective_common_shares") and existing.get("preferred_claims_usd") is not None:
                # A reviewed count resets the roll-forward.
                common = existing["effective_common_shares"]
                debt = existing.get("debt_principal", debt)
                continue
            if debt is None:
                break
            try:
                reviewed[day] = _strategy_entry(date.fromisoformat(day), common, series, debt, facts)
                notes.append(f"Strategy {day}")
            except Exception as exc:  # network or source validation
                notes.append(f"Strategy {day} unavailable ({type(exc).__name__})")
                break

    # Strive: SATA claims straight from each filing's share count.
    asst = by_ticker.get("ASST", {})
    reviewed_asst = balances.setdefault("ASST", {})
    latest_reviewed = max(reviewed_asst, default="")
    for day in sorted(asst):
        if day <= latest_reviewed or day in reviewed_asst:
            continue
        facts = asst[day]["extracted"]["facts"]
        sata = facts.get("sata_shares")
        if not sata:
            continue
        try:
            base, closes = _base("SATA", date.fromisoformat(day) + timedelta(days=1), prior_close=True)
        except Exception as exc:
            notes.append(f"Strive {day} unavailable ({type(exc).__name__})")
            continue
        reviewed_asst[day] = {"debt_principal": 0, "preferred_claims_usd": sata * base, "preferred_claims_eur": 0,
                              "auto_reconciled": True,
                              "limitations": f"SATA claims: {sata:,.0f} shares at ${base:.2f} (max of $100, ten-close mean, prior close); daily dividends assumed paid through the balance date.",
                              "sources": ["https://query1.finance.yahoo.com/v8/finance/chart/SATA"]}
        notes.append(f"Strive {day}")

    # Comparison marks for every prior date the report may need.
    marks = result.setdefault("balance_marks", {})
    btc = result.setdefault("comparison_btc_prices", {})
    released = result.setdefault("comparison_release_dates", {})
    newest_reviewed_mark = max(btc, default="")
    ordered = sorted(mstr)
    # Only a date that already has a following filing is a comparison date.
    for day, row in ((day, mstr[day]) for day in ordered[:-1]):
        if day <= newest_reviewed_mark or (day in btc and "EURUSD=X" in marks.get(day, {})):
            continue
        accepted = row.get("acceptedAt")
        try:
            instant = datetime.fromisoformat(accepted.replace("Z", "+00:00")) if accepted else None
            if instant is None:
                continue
            if day not in btc:
                btc[day] = _hour_mark("BTC-USD", instant)
                released[day] = row.get("filedDate") or instant.date().isoformat()
            marks.setdefault(day, {}).setdefault("EURUSD=X", _hour_mark("EURUSD=X", instant))
        except Exception:
            continue
    for day, row in asst.items():
        facts = row["extracted"]["facts"]
        value, held = facts.get("held_strc_fair_value_usd"), facts.get("held_strc_shares")
        if value and held and "STRC" not in marks.get(day, {}):
            marks.setdefault(day, {})["STRC"] = value / held
    if notes:
        result["auto_reconciled_notes"] = notes
    return result, notes


def vwap_estimate(filed: date):
    """Strive prior-week HLC3 estimate when no archived estimate exists."""
    from .equity_vwap import pull_estimate
    return _cached(("vwap", filed.isoformat()), lambda: pull_estimate("ASST", filed))
