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
from .draw import T_BIG, T_BODY, T_HERO, T_LABEL, T_MIN, T_VALUE, Canvas, fontset, mix, width
from .extras import fred_latest, number

ET = ZoneInfo("America/New_York")
WIDTH, HEIGHT = 1440, 1920
TITLE = ("The ", "Coupon", " Sheet")
CONFIG = Path(__file__).resolve().parents[1] / "data" / "preview-config.json"
HEROES = ("STRC", "SATA")
REST = ("STRF", "STRK", "STRD", "STRE")
ISSUER = {"STRC": "Strategy", "STRF": "Strategy", "STRK": "Strategy", "STRD": "Strategy", "STRE": "Strategy", "SATA": "Strive"}
HERO_NOTE = {"STRC": "variable rate · paid semi-monthly", "SATA": "variable rate · paid every business day"}
KIND = {"STRC": "variable · semi-monthly", "SATA": "variable · daily", "STRF": "10% fixed · senior",
        "STRK": "8% · convertible", "STRD": "10% · non-cumulative", "STRE": "10% · euro"}
# The 3-month bill is the headline: it is Strategy's stated risk-free rate, the
# bill Jeff Walton benchmarks digital credit against, and it matches STRC/SATA's
# roughly one-month rate reset. The 10Y, IG and HY show the credit comparison.
BENCHMARKS = (("SOFR", "SOFR"), ("3M bill", "DGS3MO"), ("10Y", "DGS10"), ("IG corp", "BAMLC0A0CMEY"),
              ("HY corp", "BAMLH0A0HYM2EY"))
SERIES = dict(BENCHMARKS)
DEFAULT_HEADLINE = "3M bill"
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
    headline = (config.get("spread_benchmark") or {}).get("label") or DEFAULT_HEADLINE
    headline = headline if headline in SERIES else DEFAULT_HEADLINE
    bill = levels.get(headline)

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
                bill_then = _asof(fred.get(SERIES[headline]), row["date"])
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
    return {"ladder": ladder, "references": references, "bill": bill, "headline": headline, "heroes": heroes, "rest": rest,
            "liquidity": liquidity, "btc_adv": btc_adv, "credit_adv": credit_adv, "ledger": ledger,
            "calendar": calendar[:5], "coverage": coverage, "cover": _cover_history(rows, extras, config, monday),
            "sata_rate": sata_rate, "stamp": stamp, "now": now, "stale": tuple(extras.get("stale") or ())}


# ── rendering ───────────────────────────────────────────────────────────────
# Portrait, phone-first (see draw.T_*): heroes, the rest of the ladder, USD
# cover beside the calendar, then the flow ledger.
M, GAP = 40, 24
HALF = (WIDTH - 2 * M - GAP) // 2
SHORT = {"SOFR": "SOFR", "3M bill": "3M bill", "10Y": "10Y", "IG corp": "IG corp", "HY corp": "HY corp"}


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
    draw.rectangle((14, 14, WIDTH - 15, HEIGHT - 15), outline=p.deep, width=3)
    draw.rectangle((22, 22, WIDTH - 23, HEIGHT - 23), outline=mix(p.deep, p.bg, .45), width=1)
    for x, y in ((14, 14), (WIDTH - 15, 14), (14, HEIGHT - 15), (WIDTH - 15, HEIGHT - 15)):
        draw.rectangle((x - 6, y - 6, x + 6, y + 6), fill=p.accent)


def _card(canvas, box, p, theme, accent=None):
    if theme.key == "classic":
        canvas.card(box, p.card, p.radius, accent=accent, accent_height=6, outline=p.line)
    else:
        themes.card(canvas, box, p, accent, theme, 6)


def _heading(canvas, x, y, text, p, right=None, right_x=None):
    canvas.text(x, y, text.upper(), T_LABEL, p.deep, True, max_width=(right_x - x) * .68 if right_x else None)
    if right and right_x:
        canvas.text(right_x, y + 2, right, T_MIN, p.muted, align="right", max_width=(right_x - x) * .32)


def _hero(canvas, box, ticker, hero, scale, p, theme, stripe, data):
    x0, y0, x1, y1 = box
    L, R = x0 + 28, x1 - 28
    item = hero["item"]
    _card(canvas, box, p, theme, stripe)
    end = canvas.text(L, y0 + 22, ticker, 60, p.ink, True, serif=True)
    canvas.text(end + 16, y0 + 40, ISSUER[ticker], T_LABEL, p.muted, True)
    if item.price is not None:
        canvas.text(R, y0 + 22, f"${item.price:,.2f}", T_VALUE, p.ink, True, align="right")
        diff = item.price - 100
        canvas.text(R, y0 + 76, f"{'+' if diff >= 0 else '−'}${abs(diff):.2f} vs par", T_MIN,
                    p.positive if diff >= 0 else p.negative, True, align="right")
    canvas.draw.line((L, y0 + 122, R, y0 + 122), fill=p.line, width=2)

    headline = data["headline"]
    canvas.text(L, y0 + 138, f"SPREAD OVER {SHORT[headline].upper()}", T_MIN, p.muted, True)
    canvas.text(R, y0 + 138, "YIELD", T_MIN, p.muted, True, align="right")
    canvas.text(L, y0 + 170, _bp(hero["spreads"].get(headline)), T_HERO, stripe if theme.key != "classic" else p.ink, True)
    canvas.text(R, y0 + 184, _pct(item.effective), T_VALUE + 8, p.ink, True, align="right")

    # Spread stack over each benchmark.
    y = y0 + 286
    bar_left, bar_right = L + 150, R - 118
    for label, _ in BENCHMARKS:
        spread = hero["spreads"].get(label)
        key = label == headline
        canvas.text(L, y + 4, SHORT[label], T_MIN, p.ink if key else p.muted, key)
        canvas.draw.rounded_rectangle((bar_left, y + 8, bar_right, y + 32), radius=min(5, p.radius), fill=p.tint)
        if spread is not None and spread > 0:
            canvas.draw.rounded_rectangle((bar_left, y + 8, bar_left + min(1, spread / scale) * (bar_right - bar_left), y + 32),
                                          radius=min(5, p.radius), fill=stripe if key else mix(stripe, p.card, .42))
        canvas.text(R, y + 2, _bp(spread).replace(" bp", ""), T_LABEL, p.ink, key, align="right")
        y += 44

    # Twelve weeks of spread over the headline benchmark.
    top = y + 14
    history = hero["history"]
    canvas.text(L, top, "12 WEEKS", T_MIN, p.muted, True)
    if len(history) > 2:
        values = [value for _, value in history]
        canvas.text(R, top, f"{min(values):,.0f}–{max(values):,.0f} bp", T_MIN, p.muted, align="right")
        plot = (L + 78, top + 44, R - 8, top + 136)
        low, high = min(values), max(values)
        pad = max(10.0, (high - low) * .12)
        lo, hi = low - pad, high + pad
        px = lambda i: plot[0] + i / (len(values) - 1) * (plot[2] - plot[0])
        py = lambda v: plot[3] - (v - lo) / (hi - lo) * (plot[3] - plot[1])
        for tick in (low, high):
            canvas.line([(plot[0], py(tick)), (plot[2], py(tick))], p.line, 1, dashed=True, dash=(4, 6))
            canvas.text(plot[0] - 10, py(tick) - 15, f"{tick:,.0f}", T_MIN, p.soft, align="right")
        points = [(px(i), py(v)) for i, v in enumerate(values)]
        canvas.draw.polygon(points + [(plot[2], plot[3]), (plot[0], plot[3])], fill=mix(stripe, p.card, .14))
        canvas.line(points, stripe, 4)
        canvas.dot(*points[-1], 8, stripe)
        canvas.text(plot[0], plot[3] + 8, _short(history[0][0]), T_MIN, p.soft)
        canvas.text(plot[2], plot[3] + 8, _short(history[-1][0]), T_MIN, p.soft, align="right")
    else:
        canvas.text(L, top + 70, "History unavailable", T_BODY, p.muted)

    # Par (or SATA's rate-cut test), liquidity and size.
    strip = top + 188
    canvas.draw.rounded_rectangle((L - 10, strip, R + 10, strip + 104), radius=min(10, p.radius + 4), fill=p.tint)
    par, liquidity = hero["par"], hero["liquidity"]
    at = par.get("at_par_20")
    first = ("≥ $100", f"{at}/{par.get('sessions')} days" if at is not None else "—", p.ink)
    if ticker == "SATA" and par.get("prior_avg"):
        # The prospectus allows a rate cut only if the prior month averaged ≥ $99.
        allowed = par["prior_avg"] >= 99
        first = ("CUT TEST", f"${par['prior_avg']:.2f}", p.accent if allowed else p.positive)
    cells = (first, ("30D VOLUME", _money(liquidity.get("adv"), 0) + "/d" if liquidity.get("adv") else "—", p.ink),
             ("SIZE", _money(liquidity.get("notional")), p.ink))
    cell = (R - L) / 3
    for n, (label, value, color) in enumerate(cells):
        cx = L + 4 + n * cell
        canvas.text(cx, strip + 12, label, T_MIN, p.muted, True, max_width=cell - 12)
        canvas.text(cx, strip + 48, value, T_VALUE - 6, color, True, max_width=cell - 12)

    # The issuer's USD cover against its own target: what stands behind the coupon.
    cover = data["cover"]["MSTR" if ticker == "STRC" else "ASST"]
    y = strip + 124
    weeks, target, current = cover["weeks"], cover["target"], cover["current"]
    canvas.text(L, y, "USD COVER", T_MIN, p.muted, True)
    canvas.text(L, y + 34, f"{current:.0f} mo" if current else "—", T_VALUE - 4, p.ink, True)
    if current and target:
        note = (f"at {target:.0f}-mo goal" if cover["kind"] == "goal" and abs(current - target) < .5
                else f"{current / target:.1f}× floor" if cover["kind"] == "floor" else f"{current - target:+.0f} vs goal")
        canvas.text(L, y + 84, note, T_MIN, p.positive if current >= target - .5 else p.negative, True, max_width=220)
    plot = (L + 250, y + 8, R, y + 112)
    if weeks and target:
        high = max(max(months for _, months in weeks), target) * 1.15
        slot = (plot[2] - plot[0]) / 12
        for n, (_, months) in enumerate(weeks):
            bx = plot[0] + (12 - len(weeks) + n) * slot
            h = months / high * (plot[3] - plot[1])
            color = p.positive if months >= target - .5 else p.negative
            canvas.draw.rectangle((bx + 3, plot[3] - h, bx + slot - 3, plot[3]), fill=mix(color, p.card, .6 if n < len(weeks) - 1 else 1))
        ty = plot[3] - target / high * (plot[3] - plot[1])
        canvas.line([(plot[0], ty), (plot[2], ty)], p.accent, 3, dashed=True, dash=(8, 5))
        canvas.draw.line((plot[0], plot[3], plot[2], plot[3]), fill=p.line, width=2)


def _rest(canvas, box, rest, p, theme, headline):
    x0, y0, x1, y1 = box
    L, R = x0 + 28, x1 - 28
    _card(canvas, box, p, theme)
    _heading(canvas, L, y0 + 18, "The rest of the ladder", p, "bp", R)
    columns = (("PRICE", L + 262), ("YIELD", L + 412), (f"OVER {SHORT[headline].upper()}", L + 646), ("OVER HY", R))
    for label, x in columns:
        canvas.text(x, y0 + 64, label, T_MIN, p.muted, True, align="right")
    canvas.draw.line((L, y0 + 102, R, y0 + 102), fill=p.line, width=2)
    for index, row in enumerate(rest):
        item = row["item"]
        y = y0 + 112 + index * 42
        currency = "€" if item.currency == "EUR" else "$"
        canvas.text(L, y, item.ticker, T_BODY, p.ink, True)
        values = (f"{currency}{item.price:,.2f}" if item.price else "—", _pct(item.effective),
                  _bp(row["spreads"].get(headline)).replace(" bp", ""), _bp(row["spreads"].get("HY corp")).replace(" bp", ""))
        for n, ((_, x), value) in enumerate(zip(columns, values)):
            canvas.text(x, y, value, T_BODY, p.ink, n in (1, 2), align="right")


def _calendar(canvas, box, data, p, theme):
    x0, y0, x1, y1 = box
    L, R = x0 + 28, x1 - 28
    _card(canvas, box, p, theme)
    _heading(canvas, L, y0 + 18, "Calendar", p, "days", R)
    today = data["now"].date()
    for index, (day, label, note) in enumerate(data["calendar"][:5]):
        y = y0 + 64 + index * 42
        parsed = date.fromisoformat(day)
        canvas.pill(L, y - 4, f"{parsed:%b} {parsed.day}".upper(), T_MIN, p.card, p.deep, pad=(10, 4))
        short = label.replace(" dividend ", " ").replace("STRF · STRK · STRD · STRE", "STRF/K/D/E").replace(
            "ASST warrant exercise deadline", "ASST warrants").replace("Quarter end · QTD restarts", "Quarter end")
        canvas.text(L + 128, y, short, T_MIN, p.ink, True, max_width=R - L - 180)
        canvas.text(R, y, f"{(parsed - today).days}", T_MIN, p.muted, align="right")


def _flow(canvas, box, ledger, p, theme):
    x0, y0, x1, y1 = box
    L, R = x0 + 28, x1 - 28
    _card(canvas, box, p, theme)
    _heading(canvas, L, y0 + 20, "Flow ledger · last four filing weeks", p, "+ issued / − repurchased", R)
    labels = ("WEEK", "STRC", "STRF/K/D/E", "MSTR ATM", "SATA", "BTC BOUGHT")
    span = (R - L) / len(labels)
    centers = [L + span * (n + .5) for n in range(len(labels))]
    for label, x in zip(labels, centers):
        canvas.text(x, y0 + 66, label, T_MIN, p.muted, True, align="center", max_width=span - 8)
    canvas.draw.line((L, y0 + 104, R, y0 + 104), fill=p.line, width=2)
    totals = {"strc": 0, "other": 0, "mstr": 0, "sata": 0}
    for index, entry in enumerate(ledger):
        y = y0 + 114 + index * 46
        values = (_short(entry["week"]), _money(entry.get("strc"), signed=True), _money(entry.get("other"), signed=True),
                  _money(entry.get("mstr"), signed=True), _money(entry.get("sata"), signed=True),
                  f"{(entry.get('mstr_btc') or 0):,.0f} · {(entry.get('asst_btc') or 0):,.0f}")
        for value, x in zip(values, centers):
            money = "$" in value
            color = p.negative if money and value.startswith("−") else p.positive if money and value.startswith("+") else p.ink
            canvas.text(x, y, value, T_BODY - 2, color, money, align="center", max_width=span - 8)
        for key in totals:
            totals[key] += entry.get(key) or 0
    y = y0 + 118 + len(ledger) * 46
    canvas.draw.line((L, y - 8, R, y - 8), fill=p.line, width=2)
    canvas.text(centers[0], y + 2, f"{len(ledger)} WK", T_BODY - 2, p.ink, True, align="center")
    for key, x in zip(("strc", "other", "mstr", "sata"), centers[1:5]):
        value = _money(totals[key], signed=True)
        canvas.text(x, y + 2, value, T_BODY - 2, p.negative if value.startswith("−") else p.positive if value.startswith("+") else p.ink,
                    True, align="center", max_width=span - 8)
    canvas.text(centers[5], y + 6, "MSTR · ASST", T_MIN, p.soft, align="center")


def _header(canvas, data, p, theme):
    on_space = theme.decor == "orbit"
    muted = "#AEB6D6" if on_space else p.muted
    canvas.text(M, 34, "DIGITAL CREDIT REPORT · WEDNESDAY", T_MIN, p.accent, True)
    stamp = data["stamp"]
    if stamp:
        parsed = date.fromisoformat(stamp)
        closed = parsed < data["now"].date() or data["now"].hour >= 16
        canvas.text(WIDTH - M, 34, f"{'CLOSE' if closed else 'INTRADAY'} {parsed:%a %b} {parsed.day}".upper(), T_MIN, p.accent,
                    True, align="right")
    themes.title(canvas, M, 146, TITLE, 76, p, theme, on_space=on_space)
    refs = "  ·  ".join(f"{SHORT[label]} {value:.2f}%" for label, (_, value) in data["references"] if value is not None)
    canvas.text(M, 176, refs, T_MIN, muted, max_width=WIDTH - 2 * M)


def render_png(data: dict, theme: themes.Theme = themes.DEFAULT) -> tuple[bytes, list[str]]:
    p = theme.wednesday
    with fontset(theme.fontset):
        canvas = Canvas((WIDTH, HEIGHT), p.bg, floor=T_MIN)
        if theme.key == "classic":
            _frame(canvas, p)
            _guilloche(canvas, (1000, 70, 1390, 150), mix(p.positive, p.bg, .16))
        else:
            themes.background(canvas, p, theme, header_height=226, orbit_at=(1150, 110, .55))
        _header(canvas, data, p, theme)
        heroes = data["heroes"]
        scale = max((value for hero in heroes.values() for value in hero["spreads"].values() if value is not None), default=1000) * 1.04
        top = 226
        for index, ticker in enumerate(HEROES):
            x0 = M + index * (HALF + GAP)
            _hero(canvas, (x0, top, x0 + HALF, top + 966), ticker, heroes[ticker], scale, p, theme, p.company(ticker), data)
        y = top + 984
        split = M + 868
        _rest(canvas, (M, y, split, y + 300), data["rest"], p, theme, data["headline"])
        _calendar(canvas, (split + GAP, y, WIDTH - M, y + 300), data, p, theme)
        y += 318
        _flow(canvas, (M, y, WIDTH - M, y + 356), data["ledger"], p, theme)
        png = canvas.save(metadata={"Title": "The Coupon Sheet", "Theme": theme.key})
    return png, canvas.overflows


def notes(data: dict) -> list[str]:
    """Footnotes for the web page; the X image carries none."""
    headline = data["headline"]
    stale = data.get("stale") or ()
    return [line for line in (
        "Effective yield = stated rate × $100 ÷ price (Strategy KPIs; SATA = Strive's daily dividend × 252). "
        f"Spreads = effective yield − benchmark, in basis points. Headline benchmark: {headline} — Strategy's stated "
        "risk-free rate and the bill Jeff Walton compares digital credit to; both preferreds reset monthly around $100 par.",
        "Benchmarks from FRED: SOFR, DGS3MO (3M bill), DGS10 (10Y), ICE BofA US Corporate (IG) and "
        f"High Yield effective yields, as of {_short(data['references'][0][1][0])}.",
        "12-week history uses each day's close, the stated rate in effect that day and the benchmark that day.",
        "USD cover: Strategy (USD Reserve + USD Cash) ÷ current monthly dividends against its 12-month floor; "
        "Strive's dashboard reserve against its 18-month goal.",
        "Flow ledger: Strategy 8-K cash; SATA = net share change × $100. SATA may cut its rate only if the prior month "
        "averaged at least $99.",
        "Saved snapshot used for: " + ", ".join(stale) + "." if stale else "",
    ) if line]


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
