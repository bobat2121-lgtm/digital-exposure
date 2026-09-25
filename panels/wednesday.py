"""Wednesday: "The Coupon Sheet." — spreads on the digital credit that funds
Strategy and Strive.

STRC (Strategy) and SATA (Strive) carry the treasuries, so each gets a hero
card: the spread over the 3-month bill, the spread stack over cash, Treasuries
and corporate credit, twelve weeks of spread history, par and liquidity.
STRF, STRK, STRD and STRE follow in a compact ladder. USD cover is read
against each issuer's own target on a weekly timeline, then the flow ledger
and the dated calendar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from . import themes
from .draw import Canvas, fontset, mix, width
from .extras import fred_latest, number

ET = ZoneInfo("America/New_York")
WIDTH, HEIGHT = 1800, 1400
TITLE = ("The ", "Coupon", " Sheet")
CONFIG = Path(__file__).resolve().parents[1] / "data" / "preview-config.json"
HEROES = ("STRC", "SATA")
REST = ("STRF", "STRK", "STRD", "STRE")
ISSUER = {"STRC": "Strategy", "STRF": "Strategy", "STRK": "Strategy", "STRD": "Strategy", "STRE": "Strategy", "SATA": "Strive"}
HERO_NOTE = {"STRC": "variable rate · paid semi-monthly", "SATA": "variable rate · paid every business day"}
KIND = {"STRC": "variable · semi-monthly", "SATA": "variable · daily", "STRF": "10% fixed · senior",
        "STRK": "8% · convertible", "STRD": "10% · non-cumulative", "STRE": "10% · euro"}
BENCHMARKS = (("SOFR", "SOFR"), ("3M bill", "DGS3MO"), ("10Y", "DGS10"), ("IG corp", "BAMLC0A0CMEY"),
              ("HY corp", "BAMLH0A0HYM2EY"))
HISTORY_DAYS = 84


@dataclass(frozen=True)
class Ladder:
    ticker: str
    price: float | None
    rate: float | None
    effective: float | None
    currency: str = "USD"


def _rows(extras, symbol):
    """Completed daily bars plus the provider's newer closing quote, if any."""
    item = (extras.get("yahoo") or {}).get(symbol) or {}
    rows = list(item.get("rows") or [])
    price, stamp = number(item.get("price")), item.get("as_of")
    if rows and price and stamp and symbol != "BTC-USD":
        day = datetime.fromisoformat(stamp).astimezone(ET).date().isoformat()
        if day > rows[-1]["date"]:
            rows.append({"date": day, "close": price, "volume": None})
    return rows


def _latest_price(extras, symbol):
    item = (extras.get("yahoo") or {}).get(symbol) or {}
    return number(item.get("price")) or (item.get("rows") or [{}])[-1].get("close")


def _pct(value, digits=2, signed=False, suffix="%"):
    if value is None:
        return "—"
    sign = "−" if round(value, digits) < 0 else "+" if signed and round(value, digits) > 0 else ""
    return f"{sign}{abs(value):,.{digits}f}{suffix}"


def _bp(value, signed=True):
    if value is None:
        return "—"
    sign = "−" if round(value) < 0 else "+" if signed and round(value) > 0 else ""
    return f"{sign}{abs(value):,.0f} bp"


def _money(value, digits=1, signed=False):
    if value is None:
        return "—"
    sign = "−" if value < 0 else "+" if signed and value > 0 else ""
    amount = abs(value)
    if amount >= 1e9:
        return f"{sign}${amount / 1e9:,.2f}B"
    if amount >= 1e6:
        return f"{sign}${amount / 1e6:,.{digits}f}m"
    if amount >= 1e3:
        return f"{sign}${amount / 1e3:,.0f}k"
    return f"{sign}${amount:,.0f}"


def _short(day):
    if not day:
        return "—"
    parsed = date.fromisoformat(str(day)[:10])
    return f"{parsed:%b} {parsed.day}"


def _asof(series, day):
    """Last FRED observation on or before ``day``."""
    value = None
    for stamp, level in series or []:
        if stamp > day:
            break
        if level is not None:
            value = level
    return value


def _strc_rate_at(item):
    """STRC's stated rate for the payment period covering a date (strategy.com history)."""
    schedule = sorted((entry["payDate"], number(entry.get("rate"))) for entry in item.get("dividendHistory") or []
                      if entry.get("payDate") and number(entry.get("rate")) is not None)
    current = number(item.get("currentDividend"))

    def rate(day):
        return next((value for pay, value in schedule if pay >= day), current)
    return rate


def _sata_rate_at(strive):
    """SATA's stated rate on a date from Strive's dividend history.

    Daily payments (June 2026 onward) annualize over 252 business days; the
    earlier monthly payments over 12.
    """
    changes, last = [], None
    for row in sorted(strive.get("sata_dividends") or [], key=lambda row: row.get("payDate") or ""):
        amount = number(row.get("cashAmount"))
        if amount is None or not row.get("payDate"):
            continue
        rate = round(amount * (252 if amount < .5 else 12), 4)
        if rate != last:
            changes.append((row["payDate"], rate))
            last = rate
    current = number(strive.get("sata_rate_pct"))

    def rate(day):
        value = None
        for pay, level in changes:
            if pay > day:
                break
            value = level
        return value if value is not None else (changes[0][1] if changes else current)
    return rate


def _par_stats(rows, today):
    closes = [(row["date"], row["close"]) for row in rows if row.get("close") is not None]
    if not closes:
        return {}
    last20 = closes[-20:]
    first_of_month = today.replace(day=1)
    prior_start = (first_of_month - timedelta(days=1)).replace(day=1)
    prior = [close for day, close in closes if prior_start.isoformat() <= day < first_of_month.isoformat()]
    return {"at_par_20": sum(1 for _, close in last20 if close >= 99.995), "sessions": len(last20),
            "last_par": next((day for day, close in reversed(closes) if close >= 99.995), None),
            "prior_month": prior_start, "prior_avg": sum(prior) / len(prior) if prior else None}


def _adv(rows, days=30, today=None, *, usd_volume=False):
    window = [row for row in rows if row.get("volume") is not None and (today is None or row["date"] < today)][-days:]
    if not window:
        return None, None
    # Yahoo reports crypto volume in USD already; equities in shares.
    dollars = sum(row["volume"] if usd_volume else row["volume"] * row["close"] for row in window) / len(window)
    shares = sum(row["volume"] for row in window) / len(window)
    return dollars, shares


def _ledger(feed_rows):
    """Weekly issuance/buyback cash by activity week from validated filings."""
    weeks = {}
    for row in feed_rows:
        extraction = row["extracted"]
        start = date.fromisoformat(extraction["periodStart"])
        week = (start - timedelta(days=start.weekday())).isoformat()
        entry = weeks.setdefault(week, {"week": week})
        facts = extraction["facts"]
        if row["ticker"] == "MSTR":
            securities = extraction.get("securities", {})

            def net(series):
                item = securities.get(series) or {}
                issued, bought = number(item.get("netIssuanceProceedsUsd")), number(item.get("repurchaseCashUsd"))
                return (issued or 0) - (bought or 0) if issued is not None or bought is not None else None
            entry.update(strc=net("STRC"), other=sum(v for v in (net(s) for s in REST) if v is not None),
                         mstr=net("MSTR"), mstr_btc=number(facts.get("weekly_btc_purchases")),
                         strc_bought=number((securities.get("STRC") or {}).get("repurchasedShares")),
                         mstr_end=extraction["periodEnd"], mstr_start=extraction["periodStart"])
        else:
            change = facts.get("net_sata_shares_change")
            change = number(change) if not isinstance(change, (int, float)) else change
            entry.update(sata=change * 100 if isinstance(change, (int, float)) else None,
                         asst_btc=number(facts.get("weekly_btc_purchases")))
    complete = [entry for entry in weeks.values() if "strc" in entry and "sata" in entry]
    return sorted(complete, key=lambda entry: entry["week"])[-4:]


def _cover_history(rows, extras, config, monday):
    """Weekly USD cover in months, newest last, with each issuer's own target."""
    strategy_kpis = (extras.get("strategy") or {}).get("btc") or {}
    annual = number(strategy_kpis.get("totalAnnualDividends"))
    weekly = {}
    for row in rows:
        facts = row["extracted"]["facts"]
        reserve, cash = number(facts.get("usd_reserve_usd")), number(facts.get("usd_cash_usd"))
        if row["ticker"] == "MSTR" and annual and reserve is not None and cash is not None:
            weekly[row["extracted"]["balanceDate"]] = (reserve + cash) / (annual / 12)
    strategy = sorted(weekly.items())[-12:]
    strive = sorted((row["date"], number(row.get("dividend_reserve_months")))
                    for row in (extras.get("strive") or {}).get("cash") or []
                    if row.get("date") and number(row.get("dividend_reserve_months")) is not None)
    # Weeks before SATA existed report zero; start at the first funded week.
    first = next((index for index, (_, months) in enumerate(strive) if months > 0), len(strive))
    strive = strive[first:][-12:]

    def target(ticker, key):
        item = monday.extras.get(ticker) if monday is not None else None
        return (item.target_months if item and item.target_months else None) or number((config.get(key) or {}).get("value"))
    return {
        "MSTR": {"name": "Strategy", "weeks": strategy, "current": number(strategy_kpis.get("usdMonthsOfDividends")),
                 "target": target("MSTR", "strategy_reserve_floor_months"), "kind": "floor",
                 "basis": "(USD Reserve + USD Cash) ÷ current monthly dividends"},
        "ASST": {"name": "Strive", "weeks": strive, "current": strive[-1][1] if strive else None,
                 "target": target("ASST", "strive_reserve_goal_months"), "kind": "goal",
                 "basis": "Strive dashboard dividend reserve"},
    }


def build(extras: dict, feed: dict, monday=None, *, now: datetime | None = None) -> dict:
    from report import live_report
    now = now or datetime.now(ET)
    today = now.date()
    rows = live_report._merged_filings(feed or {"filings": []}, live_report._load(live_report.CHECKPOINT))
    config = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    strategy = (extras.get("strategy") or {}).get("preferreds") or {}
    strive = extras.get("strive") or {}
    fred = extras.get("fred") or {}
    ladder = []
    for series in ("STRC",) + REST:
        item = strategy.get(series) or {}
        price = number(item.get("ufPrice"))
        rate = number(item.get("currentDividend"))
        effective = number(item.get("effYield")) or (rate * 100 / price if rate and price else None)
        ladder.append(Ladder(series, price, rate, effective, "EUR" if series == "STRE" else "USD"))
    sata_price = _latest_price(extras, "SATA")
    sata_rate = number(strive.get("sata_rate_pct"))
    ladder.append(Ladder("SATA", sata_price, sata_rate, sata_rate * 100 / sata_price if sata_rate and sata_price else None))
    ladder.sort(key=lambda item: -(item.effective or 0))
    by_ticker = {item.ticker: item for item in ladder}
    references = [(label, fred_latest(extras, code)) for label, code in BENCHMARKS]
    levels = {label: value for label, (_, value) in references}
    bill = levels.get("3M bill")

    def spreads(effective):
        return {label: (effective - value) * 100 if effective is not None and value is not None else None
                for label, value in levels.items()}

    notionals = {series: number((strategy.get(series) or {}).get("notional")) for series in strategy}
    sata_rows = sorted((row for row in rows if row["ticker"] == "ASST" and number(row["extracted"]["facts"].get("sata_shares"))),
                       key=lambda row: row["extracted"]["balanceDate"])
    sata_shares = number(sata_rows[-1]["extracted"]["facts"]["sata_shares"]) if sata_rows else None
    shares_out = {series: (notionals.get(series) or 0) / 100 or None for series in ("STRC",) + REST}
    shares_out["SATA"] = sata_shares
    liquidity = {}
    for ticker in HEROES + REST:
        dollars, shares = _adv(_rows(extras, ticker), 30, today.isoformat()) if ticker != "STRE" else (None, None)
        liquidity[ticker] = {"adv": dollars, "turnover": shares / shares_out[ticker] * 100 if shares and shares_out.get(ticker) else None,
                             "notional": notionals.get(ticker) if ticker != "SATA" else (sata_shares * 100 if sata_shares else None)}
    btc_adv, _ = _adv(_rows(extras, "BTC-USD"), 30, datetime.now(UTC).date().isoformat(), usd_volume=True)
    credit_adv = sum(liquidity[t]["adv"] or 0 for t in HEROES)

    rate_at = {"STRC": _strc_rate_at(strategy.get("STRC") or {}), "SATA": _sata_rate_at(strive)}
    heroes = {}
    for ticker in HEROES:
        item = by_ticker[ticker]
        price_rows = _rows(extras, ticker)
        history = []
        if price_rows:
            start = (date.fromisoformat(price_rows[-1]["date"]) - timedelta(days=HISTORY_DAYS)).isoformat()
            for row in price_rows:
                bill_then = _asof(fred.get("DGS3MO"), row["date"])
                rate = rate_at[ticker](row["date"])
                if row["date"] >= start and row.get("close") and rate and bill_then is not None:
                    history.append((row["date"], (rate * 100 / row["close"] - bill_then) * 100))
        par = _par_stats(price_rows, today)
        heroes[ticker] = {"item": item, "spreads": spreads(item.effective), "history": history, "par": par,
                          "liquidity": liquidity[ticker]}
    rest = [{"item": by_ticker[ticker], "spreads": spreads(by_ticker[ticker].effective), "liquidity": liquidity[ticker]}
            for ticker in REST if ticker in by_ticker]

    ledger = _ledger(rows)
    for entry in ledger:
        volume = [row for row in _rows(extras, "STRC") if entry.get("mstr_start", "9") <= row["date"] <= entry.get("mstr_end", "0")]
        traded = sum(row["volume"] or 0 for row in volume)
        entry["buyback_share"] = entry["strc_bought"] / traded * 100 if entry.get("strc_bought") and traded else None
    events = {}
    for series in ("STRC",) + REST:
        item = strategy.get(series) or {}
        for label, key in (("record", "nextRecordDate"), ("pay", "nextPayoutDate")):
            day = item.get(key)
            if day and date.fromisoformat(day) >= today:
                events.setdefault((day, label), []).append(series)
    calendar = [(day, f"{' · '.join(series)} dividend {label}", "record date" if label == "record" else "payment")
                for (day, label), series in events.items()]
    warrants = (monday.extras.get("ASST") and monday.extras["ASST"].warrants) or None if monday is not None else None
    if warrants:
        calendar.append((warrants["expires"].date().isoformat(), "ASST warrant exercise deadline",
                         f"{warrants['count'] / 1e6:.1f}m @ ${warrants['strike']:.0f} · 5 pm ET"))
    quarter_end = date(today.year, 3 * ((today.month - 1) // 3) + 3, 1)
    quarter_end = (quarter_end.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    calendar.append((quarter_end.isoformat(), "Quarter end · QTD restarts", "next Monday ledger"))
    calendar.sort()
    coverage = dict(monday.extras) if monday is not None else {}
    stamp = max((row["date"] for row in _rows(extras, "STRC")), default=None)
    return {"ladder": ladder, "references": references, "bill": bill, "heroes": heroes, "rest": rest,
            "liquidity": liquidity, "btc_adv": btc_adv, "credit_adv": credit_adv, "ledger": ledger,
            "calendar": calendar[:5], "coverage": coverage, "cover": _cover_history(rows, extras, config, monday),
            "sata_rate": sata_rate, "stamp": stamp, "now": now, "stale": tuple(extras.get("stale") or ())}


# ── rendering ───────────────────────────────────────────────────────────────
def _guilloche(canvas: Canvas, box, color):
    """Fine interlaced waves, as on a printed bond certificate."""
    x0, y0, x1, y1 = box
    for phase in range(0, 360, 30):
        points = []
        for x in range(int(x0), int(x1), 6):
            t = (x - x0) / 90
            y = (y0 + y1) / 2 + math.sin(t + math.radians(phase)) * (y1 - y0) * .42 * math.cos(t / 3.1)
            points.append((x, y))
        canvas.line(points, color, 1)


def _frame(canvas: Canvas, p):
    draw = canvas.draw
    draw.rectangle((16, 16, WIDTH - 17, HEIGHT - 17), outline=p.deep, width=3)
    draw.rectangle((24, 24, WIDTH - 25, HEIGHT - 25), outline=mix(p.deep, p.bg, .45), width=1)
    for x, y in ((16, 16), (WIDTH - 17, 16), (16, HEIGHT - 17), (WIDTH - 17, HEIGHT - 17)):
        draw.rectangle((x - 5, y - 5, x + 5, y + 5), fill=p.accent)


def _card(canvas, box, p, theme, accent=None):
    if theme.key == "classic":
        canvas.card(box, p.card, p.radius, accent=accent, accent_height=5, outline=p.line)
    else:
        themes.card(canvas, box, p, accent, theme, 5)


def _heading(canvas, x, y, text, p, theme, right=None, right_x=None):
    canvas.text(x, y, text.upper(), 19, p.deep, True, max_width=(right_x - x) * .66 if right_x else None)
    if right and right_x:
        canvas.text(right_x, y + 2, right, 15, p.muted, align="right", max_width=(right_x - x) * .34)


def _hero(canvas, box, ticker, hero, scale, p, theme, stripe, data):
    x0, y0, x1, y1 = box
    L, R = x0 + 26, x1 - 26
    item = hero["item"]
    _card(canvas, box, p, theme, stripe)
    end = canvas.text(L, y0 + 20, ticker, 48, p.ink, True, serif=True)
    canvas.text(end + 16, y0 + 28, ISSUER[ticker], 20, p.ink, True)
    canvas.text(end + 16, y0 + 54, HERO_NOTE[ticker], 16, p.muted)
    if item.price is not None:
        canvas.text(R, y0 + 20, f"${item.price:,.2f}", 32, p.ink, True, align="right")
        diff = item.price - 100
        canvas.text(R, y0 + 60, f"{'+' if diff >= 0 else '−'}${abs(diff):.2f} vs $100 par", 17,
                    p.positive if diff >= 0 else p.negative, True, align="right")
    canvas.draw.line((L, y0 + 96, R, y0 + 96), fill=p.line)

    # Headline spread and yield.
    bill_spread = hero["spreads"].get("3M bill")
    canvas.text(L, y0 + 112, "SPREAD OVER 3M BILL", 15, p.muted, True)
    canvas.text(L, y0 + 132, _bp(bill_spread), 58, stripe if theme.key != "classic" else p.ink, True)
    canvas.text(L, y0 + 200, f"{_pct(item.effective)} effective − {_pct(data['bill'])} bill", 15, p.soft, max_width=250)
    canvas.text(L, y0 + 236, "EFFECTIVE YIELD", 15, p.muted, True)
    canvas.text(L, y0 + 256, _pct(item.effective), 34, p.ink, True)
    canvas.text(L, y0 + 298, f"stated {_pct(item.rate)} × $100 ÷ price", 15, p.soft, max_width=250)

    # Spread stack.
    sx = L + 290
    canvas.text(sx, y0 + 112, "SPREAD STACK · OVER", 15, p.muted, True)
    canvas.text(R, y0 + 112, "bp", 15, p.muted, True, align="right")
    bar_left, bar_right = sx + 150, R - 92
    levels = {label: value for label, (_, value) in data["references"]}
    for n, (label, _) in enumerate(BENCHMARKS):
        y = y0 + 142 + n * 36
        spread, level = hero["spreads"].get(label), levels.get(label)
        key = label == "3M bill"
        canvas.text(sx, y + 2, label, 18, p.ink, key)
        canvas.text(sx + 76, y + 5, _pct(level) if level is not None else "—", 14, p.soft)
        canvas.draw.rounded_rectangle((bar_left, y + 5, bar_right, y + 23), radius=min(4, p.radius), fill=p.tint)
        if spread is not None and spread > 0:
            canvas.draw.rounded_rectangle((bar_left, y + 5, bar_left + min(1, spread / scale) * (bar_right - bar_left), y + 23),
                                          radius=min(4, p.radius), fill=stripe if key else mix(stripe, p.card, .45))
        canvas.text(R, y + 1, _bp(spread).replace(" bp", ""), 20, p.ink, key, align="right")

    # Twelve weeks of spread over the bill.
    top = y0 + 336
    history = hero["history"]
    canvas.text(L, top, "SPREAD OVER 3M BILL · 12 WEEKS", 15, p.muted, True)
    if len(history) > 2:
        values = [value for _, value in history]
        canvas.text(R, top, f"range {min(values):,.0f}–{max(values):,.0f} bp · now {values[-1]:,.0f}", 15, p.muted, align="right")
        plot = (L + 64, top + 30, R - 8, top + 118)
        low, high = min(values), max(values)
        pad = max(10.0, (high - low) * .15)
        low, high = low - pad, high + pad
        px = lambda i: plot[0] + i / (len(values) - 1) * (plot[2] - plot[0])
        py = lambda v: plot[3] - (v - low) / (high - low) * (plot[3] - plot[1])
        for tick in (low + pad, high - pad):
            canvas.line([(plot[0], py(tick)), (plot[2], py(tick))], p.line, 1, dashed=True, dash=(3, 5))
            canvas.text(plot[0] - 10, py(tick) - 9, f"{tick:,.0f}", 14, p.soft, align="right")
        points = [(px(i), py(v)) for i, v in enumerate(values)]
        canvas.draw.polygon(points + [(plot[2], plot[3]), (plot[0], plot[3])], fill=mix(stripe, p.card, .12))
        canvas.line(points, stripe, 3)
        canvas.dot(*points[-1], 6, stripe)
        canvas.text(plot[0], plot[3] + 6, _short(history[0][0]), 13, p.soft)
        canvas.text(plot[2], plot[3] + 6, _short(history[-1][0]), 13, p.soft, align="right")
    else:
        canvas.text(L, top + 60, "Spread history unavailable", 16, p.muted)

    # Par and liquidity strip.
    strip = y0 + 482
    canvas.draw.rounded_rectangle((L - 8, strip, R + 8, strip + 80), radius=min(8, p.radius), fill=p.tint)
    par, liquidity = hero["par"], hero["liquidity"]
    at = par.get("at_par_20")
    cells = (("CLOSED ≥ $100", f"{at} of {par.get('sessions')}" if at is not None else "—", "last 20 sessions"),
             ("30-DAY ADV", _money(liquidity.get("adv")), "Yahoo close × volume"),
             ("TURNOVER", _pct(liquidity.get("turnover")) + "/day" if liquidity.get("turnover") else "—", "of shares outstanding"),
             ("OUTSTANDING", _money(liquidity.get("notional")), "at $100 par"))
    cell = (R - L) / 4
    for n, (label, value, note) in enumerate(cells):
        cx = L + n * cell
        canvas.text(cx, strip + 10, label, 13, p.muted, True, max_width=cell - 12)
        canvas.text(cx, strip + 28, value, 22, p.ink, True, max_width=cell - 12)
        canvas.text(cx, strip + 56, note, 13, p.soft, max_width=cell - 12)
    rule_y = strip + 92
    if ticker == "SATA" and par.get("prior_avg"):
        allowed = par["prior_avg"] >= 99
        canvas.text(L, rule_y, f"Rate cut allowed only if the prior month averaged ≥ $99 · {par['prior_month']:%b} "
                    f"${par['prior_avg']:.2f} → {'allowed' if allowed else 'not allowed'}", 16,
                    p.accent if allowed else p.positive, True, max_width=R - L)
    elif ticker == "STRC":
        last = _short(par.get("last_par")) if par.get("last_par") else "—"
        share = data["credit_adv"] / data["btc_adv"] * 100 if data["btc_adv"] else None
        canvas.text(L, rule_y, f"Rate set monthly by Strategy · last close ≥ $100 {last} · "
                    f"STRC + SATA trade {_pct(share)} of bitcoin's spot volume", 16, p.muted, True, max_width=R - L)


def _rest(canvas, box, rest, p, theme):
    x0, y0, x1, y1 = box
    L, R = x0 + 24, x1 - 24
    _card(canvas, box, p, theme)
    _heading(canvas, L, y0 + 16, "The rest of the ladder · Strategy fixed-rate series", p, theme, "bp over benchmark · STRE in EUR", R)
    columns = (("SERIES", L, "left"), ("PRICE", L + 420, "right"), ("STATED", L + 520, "right"),
               ("EFFECTIVE", L + 640, "right"), ("OVER 3M BILL", L + 790, "right"), ("OVER HY", L + 900, "right"),
               ("OUTSTANDING", R, "right"))
    for label, x, align in columns:
        canvas.text(x, y0 + 50, label, 13, p.muted, True, align=align)
    canvas.draw.line((L, y0 + 70, R, y0 + 70), fill=p.line)
    for index, row in enumerate(rest):
        item = row["item"]
        y = y0 + 80 + index * 34
        currency = "€" if item.currency == "EUR" else "$"
        canvas.text(L, y, item.ticker, 21, p.ink, True)
        canvas.text(L + 72, y + 4, KIND[item.ticker], 15, p.soft, max_width=250)
        values = (f"{currency}{item.price:,.2f}" if item.price else "—", _pct(item.rate), _pct(item.effective),
                  _bp(row["spreads"].get("3M bill")).replace(" bp", ""), _bp(row["spreads"].get("HY corp")).replace(" bp", ""),
                  _money(row["liquidity"].get("notional")))
        for n, ((_, x, _), value) in enumerate(zip(columns[1:], values)):
            canvas.text(x, y + 1, value, 19, p.ink, n in (2, 3), align="right")


def _calendar(canvas, box, data, p, theme):
    x0, y0, x1, y1 = box
    L, R = x0 + 24, x1 - 24
    _card(canvas, box, p, theme)
    _heading(canvas, L, y0 + 16, "On the calendar", p, theme, "days away", R)
    today = data["now"].date()
    for index, (day, label, note) in enumerate(data["calendar"]):
        y = y0 + 52 + index * 30
        parsed = date.fromisoformat(day)
        canvas.pill(L, y - 2, f"{parsed:%b} {parsed.day}".upper(), 13, p.card, p.deep)
        canvas.text(L + 86, y, label, 16, p.ink, True, max_width=R - L - 150)
        canvas.text(R, y + 1, f"{(parsed - today).days} d", 15, p.muted, align="right")


def _cover(canvas, box, cover, p, theme):
    x0, y0, x1, y1 = box
    L, R = x0 + 24, x1 - 24
    _card(canvas, box, p, theme)
    _heading(canvas, L, y0 + 16, "USD cover · vs each issuer's own target", p, theme, "months of preferred dividends", R)
    for index, ticker in enumerate(("MSTR", "ASST")):
        item = cover[ticker]
        top = y0 + 52 + index * 120
        weeks, target, current = item["weeks"], item["target"], item["current"]
        canvas.text(L, top, item["name"], 20, p.ink, True)
        value = f"{current:.0f} months" if current else "—"
        end = canvas.text(L + 110, top, value, 20, p.ink, True)
        if current and target:
            on = sum(1 for _, months in weeks if months >= target - .5)
            if item["kind"] == "goal":
                note = f"at its {target:.0f}-month goal {on} of {len(weeks)} weeks" if abs(current - target) < .5 else \
                    f"{current - target:+.0f} vs its {target:.0f}-month goal"
            else:
                note = f"{current / target:.1f}× its {target:.0f}-month floor · above it {on} of {len(weeks)} weeks"
            canvas.text(end + 14, top + 3, note, 16, p.positive if current >= target - .5 else p.negative, True, max_width=R - end - 14)
        plot = (L, top + 28, R, top + 96)
        if not weeks or not target:
            canvas.text(L, top + 44, "Weekly history unavailable", 15, p.muted)
            continue
        high = max(max(months for _, months in weeks), target) * 1.18
        gutter = 104
        slot = (plot[2] - plot[0] - gutter) / 12
        base = plot[3]
        for n, (day, months) in enumerate(weeks):
            bx = plot[0] + gutter + (12 - len(weeks) + n) * slot
            height = months / high * (plot[3] - plot[1])
            color = p.positive if months >= target - .5 else p.negative
            canvas.draw.rectangle((bx + 3, base - height, bx + slot - 3, base), fill=mix(color, p.card, .78 if n < len(weeks) - 1 else 1))
        ty = base - target / high * (plot[3] - plot[1])
        canvas.line([(plot[0] + gutter - 6, ty), (plot[2], ty)], p.accent, 2, dashed=True, dash=(6, 4))
        canvas.text(plot[0], ty - 9, f"{target:.0f}-mo {item['kind']}", 14, p.accent, True, max_width=gutter - 12)
        canvas.draw.line((plot[0] + gutter - 6, base, plot[2], base), fill=p.line)
        canvas.text(plot[2], base + 3, f"{_short(weeks[0][0])} → {_short(weeks[-1][0])}", 12, p.soft, align="right")


def _flow(canvas, box, ledger, p, theme):
    x0, y0, x1, y1 = box
    L, R = x0 + 24, x1 - 24
    _card(canvas, box, p, theme)
    _heading(canvas, L, y0 + 16, "Flow ledger · last four filing weeks", p, theme, "+ issued / − repurchased", R)
    columns = (("WEEK OF", L, "left"), ("STRC", L + 212, "right"), ("STRF/K/D/E", L + 324, "right"),
               ("MSTR ATM", L + 442, "right"), ("SATA", L + 550, "right"), ("STRC BUYBACK", L + 654, "right"),
               ("BTC BOUGHT", R, "right"))
    for label, x, align in columns:
        canvas.text(x, y0 + 50, label, 13, p.muted, True, align=align)
    canvas.draw.line((L, y0 + 70, R, y0 + 70), fill=p.line)
    totals = {"strc": 0, "other": 0, "mstr": 0, "sata": 0}
    for index, entry in enumerate(ledger):
        y = y0 + 80 + index * 34
        values = (_short(entry["week"]), _money(entry.get("strc"), signed=True), _money(entry.get("other"), signed=True),
                  _money(entry.get("mstr"), signed=True), _money(entry.get("sata"), signed=True),
                  f"{entry['buyback_share']:.0f}% of vol" if entry.get("buyback_share") else "—",
                  f"{(entry.get('mstr_btc') or 0):,.0f} · {(entry.get('asst_btc') or 0):,.0f}")
        for (_, x, align), value in zip(columns, values):
            money = "$" in value
            color = p.negative if money and value.startswith("−") else p.positive if money and value.startswith("+") else p.ink
            canvas.text(x, y, value, 18, color, money, align=align)
        for key in totals:
            totals[key] += entry.get(key) or 0
    y = y0 + 84 + len(ledger) * 34
    canvas.draw.line((L, y - 6, R, y - 6), fill=p.line)
    canvas.text(L, y, f"{len(ledger)}-week total", 18, p.ink, True)
    for key, (_, x, _) in zip(("strc", "other", "mstr", "sata"), columns[1:5]):
        value = _money(totals[key], signed=True)
        canvas.text(x, y, value, 18, p.negative if value.startswith("−") else p.positive if value.startswith("+") else p.ink,
                    True, align="right")
    canvas.text(R, y + 2, "MSTR · ASST", 13, p.soft, align="right")
    canvas.text(L, y1 - 28, "Strategy 8-K cash; SATA = net share change × $100. Buyback = STRC repurchased ÷ STRC shares traded.",
                13, p.soft, max_width=R - L)


def _header(canvas, data, p, theme):
    on_space = theme.decor == "orbit"
    muted = "#AEB6D6" if on_space else p.muted
    light = "#F3F1EC" if on_space else p.deep
    canvas.text(56, 44, "THE DIGITAL CREDIT REPORT  ·  WEDNESDAY  ·  DIGITAL CREDIT SPREADS", 18, p.accent, True)
    themes.title(canvas, 56, 122, TITLE, 56, p, theme, on_space=on_space)
    canvas.text(56, 138, "What STRC and SATA pay over cash, Treasuries and corporate credit · the rest of the ladder below",
                20, muted, max_width=1060)
    stamp = data["stamp"]
    if stamp:
        parsed = date.fromisoformat(stamp)
        closed = parsed < data["now"].date() or data["now"].hour >= 16
        canvas.text(WIDTH - 56, 46, f"{'CLOSE' if closed else 'INTRADAY'} · {parsed:%a %b} {parsed.day}, {parsed.year}".upper(),
                    19, light, True, align="right")
    refs = "  ·  ".join(f"{label} {value:.2f}%" for label, (_, value) in data["references"] if value is not None)
    canvas.text(WIDTH - 56, 76, refs, 18, muted, align="right", max_width=620)
    heroes = data["heroes"]
    gap = (heroes["SATA"]["item"].effective - heroes["STRC"]["item"].effective) * 100 \
        if heroes["SATA"]["item"].effective and heroes["STRC"]["item"].effective else None
    canvas.text(WIDTH - 56, 104, f"FRED as of {_short(data['references'][0][1][0])} · SATA over STRC {_bp(gap)}", 16,
                muted, align="right", max_width=620)


def render_png(data: dict, theme: themes.Theme = themes.CLASSIC) -> tuple[bytes, list[str]]:
    p = theme.wednesday
    with fontset(theme.fontset):
        canvas = Canvas((WIDTH, HEIGHT), p.bg)
        if theme.key == "classic":
            _frame(canvas, p)
            _guilloche(canvas, (760, 40, 1090, 108), mix(p.positive, p.bg, .16))
        else:
            themes.background(canvas, p, theme, header_height=160, orbit_at=(930, 70, .62))
        _header(canvas, data, p, theme)
        heroes = data["heroes"]
        scale = max((value for hero in heroes.values() for value in hero["spreads"].values() if value is not None), default=1000) * 1.06
        for index, ticker in enumerate(HEROES):
            x0 = 56 + index * 852
            _hero(canvas, (x0, 176, x0 + 836, 780), ticker, heroes[ticker], scale, p, theme,
                  p.accent if ticker == "STRC" else p.accent2, data)
        _rest(canvas, (56, 796, 1172, 1006), data["rest"], p, theme)
        _calendar(canvas, (1190, 796, 1744, 1006), data, p, theme)
        _cover(canvas, (56, 1022, 900, 1316), data["cover"], p, theme)
        _flow(canvas, (918, 1022, 1744, 1316), data["ledger"], p, theme)
        stale = data.get("stale") or ()
        footer = ("Effective yield = stated rate × $100 ÷ price (Strategy KPIs; SATA = Strive daily dividend × 252). "
                  "Sources: strategy.com · strive.com · Yahoo Finance · FRED (SOFR, DGS3MO, DGS10, ICE BofA IG/HY) · SEC 8-Ks.")
        if stale:
            footer += " Saved snapshot: " + ", ".join(stale) + "."
        canvas.text(56, 1330, footer, 15, p.muted, max_width=1688)
        canvas.text(56, 1352, "USD cover: Strategy (USD Reserve + USD Cash) ÷ current monthly dividends; Strive's dashboard reserve. "
                    "Spread history uses each day's close, stated rate and 3M bill.", 14, p.soft, max_width=1688)
        png = canvas.save(metadata={"Title": "The Coupon Sheet", "Theme": theme.key})
    return png, canvas.overflows


def audit_rows(data: dict) -> list[dict]:
    rows = []
    for item in data["ladder"]:
        rows.append({"metric": f"{item.ticker} price", "value": f"{item.price:.2f} {item.currency}" if item.price else "—",
                     "source": "strategy.com KPIs" if item.ticker != "SATA" else "Yahoo Finance"})
        rows.append({"metric": f"{item.ticker} effective yield", "value": _pct(item.effective), "source": "rate × 100 ÷ price"})
    for label, (day, value) in data["references"]:
        rows.append({"metric": label, "value": f"{value:.2f}% ({day})" if value is not None else "—", "source": "FRED"})
    for ticker, hero in data["heroes"].items():
        for label, spread in hero["spreads"].items():
            rows.append({"metric": f"{ticker} spread over {label}", "value": _bp(spread), "source": "effective − benchmark"})
        rows.append({"metric": f"{ticker} closes ≥ $100, last 20", "value": str(hero["par"].get("at_par_20")), "source": "Yahoo Finance"})
    for ticker, item in data["cover"].items():
        rows.append({"metric": f"{item['name']} USD cover (months) vs {item['kind']}",
                     "value": f"{item['current']:.1f} vs {item['target']:.0f}" if item["current"] and item["target"] else "—",
                     "source": item["basis"]})
    for entry in data["ledger"]:
        rows.append({"metric": f"Week of {entry['week']} STRC net / SATA net",
                     "value": f"{_money(entry.get('strc'), signed=True)} / {_money(entry.get('sata'), signed=True)}", "source": "SEC 8-K"})
    return rows
