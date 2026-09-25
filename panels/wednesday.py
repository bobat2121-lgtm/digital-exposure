"""Wednesday: "The Coupon Sheet." — the midweek digital credit monitor.

Covers Strategy's STRC, STRF, STRK, STRD, STRE and Strive's SATA: effective
yield against cash and credit benchmarks, price against $100 par, liquidity,
the issuance/buyback ledger from the Monday filings, coverage and the dated
calendar. A certificate-paper palette sets it apart from Monday's cream and
Friday's black while keeping the family type, cards and orange dot.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import math
from zoneinfo import ZoneInfo

from .draw import Canvas, imprint, mix, width
from .extras import fred_latest, number

ET = ZoneInfo("America/New_York")
WIDTH, HEIGHT = 1800, 1400
PAPER, CARD, INK, MUTED, SOFT = "#E6ECE7", "#F9FBF7", "#10302A", "#4E6A63", "#7D938D"
GREEN, DEEP, ORANGE, GOLD, RED, LINE = "#1F6F5C", "#15463B", "#E07A1F", "#B08A2E", "#A8433F", "#CBD8D1"
TITLE = ("The ", "Coupon", " Sheet")
ISSUER = {"STRC": "Strategy", "STRF": "Strategy", "STRK": "Strategy", "STRD": "Strategy", "STRE": "Strategy", "SATA": "Strive"}
KIND = {"STRC": "variable · monthly", "SATA": "variable · daily", "STRF": "10% fixed · senior",
        "STRK": "8% · convertible", "STRD": "10% · non-cumulative", "STRE": "10% · euro"}


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


def _par_stats(rows, today):
    closes = [(row["date"], row["close"]) for row in rows if row["date"] < today.isoformat() or True]
    if not closes:
        return {}
    last20 = closes[-20:]
    at_par = sum(1 for _, close in last20 if close >= 99.995)
    last_par = next((day for day, close in reversed(closes) if close >= 99.995), None)
    first_of_month = today.replace(day=1)
    prior_start = (first_of_month - timedelta(days=1)).replace(day=1)
    prior = [close for day, close in closes if prior_start.isoformat() <= day < first_of_month.isoformat()]
    return {"series": closes[-60:], "at_par_20": at_par, "sessions": len(last20), "last_par": last_par,
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
            entry.update(strc=net("STRC"), other=sum(v for v in (net(s) for s in ("STRF", "STRK", "STRD", "STRE")) if v is not None),
                         mstr=net("MSTR"), mstr_btc=number(facts.get("weekly_btc_purchases")),
                         strc_bought=number((securities.get("STRC") or {}).get("repurchasedShares")),
                         mstr_end=extraction["periodEnd"], mstr_start=extraction["periodStart"])
        else:
            change = number(facts.get("net_sata_shares_change")) if "net_sata_shares_change" in facts else None
            if change is None and isinstance(facts.get("net_sata_shares_change"), (int, float)):
                change = facts["net_sata_shares_change"]
            entry.update(sata=change * 100 if isinstance(change, (int, float)) else None,
                         asst_btc=number(facts.get("weekly_btc_purchases")))
    complete = [entry for entry in weeks.values() if "strc" in entry and "sata" in entry]
    return sorted(complete, key=lambda entry: entry["week"])[-4:]


def build(extras: dict, feed: dict, monday=None, *, now: datetime | None = None) -> dict:
    from report import live_report
    now = now or datetime.now(ET)
    today = now.date()
    rows = live_report._merged_filings(feed or {"filings": []}, live_report._load(live_report.CHECKPOINT))
    strategy = (extras.get("strategy") or {}).get("preferreds") or {}
    strive = extras.get("strive") or {}
    ladder = []
    for series in ("STRC", "STRF", "STRK", "STRD", "STRE"):
        item = strategy.get(series) or {}
        price = number(item.get("ufPrice"))
        rate = number(item.get("currentDividend"))
        effective = number(item.get("effYield")) or (rate * 100 / price if rate and price else None)
        ladder.append(Ladder(series, price, rate, effective, "EUR" if series == "STRE" else "USD"))
    sata_price = _latest_price(extras, "SATA")
    sata_rate = number(strive.get("sata_rate_pct"))
    ladder.append(Ladder("SATA", sata_price, sata_rate, sata_rate * 100 / sata_price if sata_rate and sata_price else None))
    ladder.sort(key=lambda item: -(item.effective or 0))
    references = [(label, fred_latest(extras, series)) for label, series in
                  (("SOFR", "SOFR"), ("3M bill", "DGS3MO"), ("10Y", "DGS10"), ("IG corp", "BAMLC0A0CMEY"), ("HY corp", "BAMLH0A0HYM2EY"))]
    bill = fred_latest(extras, "DGS3MO")[1]
    par = {ticker: _par_stats(_rows(extras, ticker), today) for ticker in ("STRC", "SATA")}
    notionals = {series: number((strategy.get(series) or {}).get("notional")) for series in strategy}
    sata_rows = sorted((row for row in rows if row["ticker"] == "ASST" and number(row["extracted"]["facts"].get("sata_shares"))),
                       key=lambda row: row["extracted"]["balanceDate"])
    sata_shares = number(sata_rows[-1]["extracted"]["facts"]["sata_shares"]) if sata_rows else None
    shares_out = {series: (notionals.get(series) or 0) / 100 or None for series in ("STRC", "STRF", "STRK", "STRD")}
    shares_out["SATA"] = sata_shares
    liquidity = {}
    for ticker in ("STRC", "SATA", "STRF", "STRK", "STRD"):
        dollars, shares = _adv(_rows(extras, ticker), 30, today.isoformat())
        liquidity[ticker] = {"adv": dollars, "turnover": shares / shares_out[ticker] * 100 if shares and shares_out.get(ticker) else None,
                             "notional": notionals.get(ticker) if ticker != "SATA" else (sata_shares * 100 if sata_shares else None)}
    btc_adv, _ = _adv(_rows(extras, "BTC-USD"), 30, datetime.now(UTC).date().isoformat(), usd_volume=True)
    credit_adv = sum(liquidity[t]["adv"] or 0 for t in ("STRC", "SATA"))
    ledger = _ledger(rows)
    for entry in ledger:
        volume = [row for row in _rows(extras, "STRC") if entry.get("mstr_start", "9") <= row["date"] <= entry.get("mstr_end", "0")]
        traded = sum(row["volume"] or 0 for row in volume)
        entry["buyback_share"] = entry["strc_bought"] / traded * 100 if entry.get("strc_bought") and traded else None
    events = {}
    for series in ("STRC", "STRF", "STRK", "STRD", "STRE"):
        item = strategy.get(series) or {}
        for label, key in (("record", "nextRecordDate"), ("pay", "nextPayoutDate")):
            day = item.get(key)
            if day and date.fromisoformat(day) >= today:
                events.setdefault((day, label), []).append(series)
    calendar = [(day, f"{' · '.join(series)} dividend {label}", "record date" if label == "record" else "payment")
                for (day, label), series in events.items()]
    warrants = None
    if monday is not None:
        warrants = (monday.extras.get("ASST") and monday.extras["ASST"].warrants) or None
    if warrants:
        calendar.append((warrants["expires"].date().isoformat(), "ASST warrant exercise deadline",
                         f"{warrants['count'] / 1e6:.1f}m @ ${warrants['strike']:.0f} · 5:00 pm ET"))
    quarter_end = date(today.year, 3 * ((today.month - 1) // 3) + 3, 1)
    quarter_end = (quarter_end.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    calendar.append((quarter_end.isoformat(), "Quarter end · QTD restarts", "next Monday ledger"))
    calendar.sort()
    coverage = {}
    if monday is not None:
        for ticker, item in monday.extras.items():
            coverage[ticker] = item
    stamp = max((row["date"] for row in _rows(extras, "STRC")), default=None)
    return {"ladder": ladder, "references": references, "bill": bill, "par": par, "liquidity": liquidity,
            "btc_adv": btc_adv, "credit_adv": credit_adv, "ledger": ledger, "calendar": calendar[:6],
            "coverage": coverage, "sata_rate": sata_rate, "stamp": stamp, "now": now,
            "floor": 12, "stale": tuple(extras.get("stale") or ())}


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


def _perforation(canvas: Canvas, x, y0, y1):
    canvas.line([(x, y0 + 14), (x, y1 - 14)], LINE, 2, dashed=True, dash=(5, 6))
    for y in (y0, y1):
        canvas.dot(x, y, 11, PAPER)


def _frame(canvas: Canvas):
    draw = canvas.draw
    draw.rectangle((16, 16, WIDTH - 17, HEIGHT - 17), outline=DEEP, width=3)
    draw.rectangle((24, 24, WIDTH - 25, HEIGHT - 25), outline=mix(DEEP, PAPER, .45), width=1)
    for x, y in ((16, 16), (WIDTH - 17, 16), (16, HEIGHT - 17), (WIDTH - 17, HEIGHT - 17)):
        draw.rectangle((x - 5, y - 5, x + 5, y + 5), fill=ORANGE)


def render_png(data: dict) -> tuple[bytes, list[str]]:
    canvas = Canvas((WIDTH, HEIGHT), PAPER)
    draw = canvas.draw
    _frame(canvas)
    _guilloche(canvas, (800, 60, 1130, 150), mix(GREEN, PAPER, .16))
    now = data["now"]
    stamp = data["stamp"]
    canvas.text(56, 44, "THE DIGITAL CREDIT REPORT  ·  WEDNESDAY  ·  DIGITAL CREDIT MONITOR", 18, ORANGE, True)
    imprint(canvas, 56, 122, TITLE, 56, ink=INK, muted="#4c6660", dot=ORANGE)
    canvas.text(56, 138, "Yield, par, liquidity and coverage for the preferreds that fund Strategy and Strive", 20, MUTED, max_width=1100)
    canvas.text(WIDTH - 56, 46, f"CLOSE · {date.fromisoformat(stamp):%a %b} {date.fromisoformat(stamp).day}, {date.fromisoformat(stamp).year}".upper()
                if stamp else "CLOSE", 19, DEEP, True, align="right")
    refs = {label: value for label, (_, value) in data["references"]}
    canvas.text(WIDTH - 56, 76, "  ·  ".join(f"{label} {value:.2f}%" for label, value in refs.items() if value is not None), 18, MUTED,
                align="right", max_width=600)
    canvas.text(WIDTH - 56, 104, f"FRED as of {_short(data['references'][0][1][0])} · prices at the close · STRE in EUR", 16, SOFT, align="right")

    # Hero: the yield ladder.
    box = (56, 176, 1130, 640)
    canvas.card(box, CARD, 14, outline=LINE)
    _perforation(canvas, 1130, 176, 640)
    canvas.text(80, 194, "THE LADDER · EFFECTIVE YIELD", 19, DEEP, True)
    strc = next((item for item in data["ladder"] if item.ticker == "STRC"), None)
    sata = next((item for item in data["ladder"] if item.ticker == "SATA"), None)
    if strc and sata and strc.effective and sata.effective:
        canvas.text(1106, 194, f"SATA − STRC {_pct(sata.effective - strc.effective, 2, True, ' pp')}", 18, MUTED, True, align="right")
    plot_left, plot_right, top = 330, 980, 286
    scale = max(16.0, max((item.effective or 0) for item in data["ladder"]) * 1.12)
    x_of = lambda value: plot_left + value / scale * (plot_right - plot_left)
    row_h = 54
    bottom = top + row_h * len(data["ladder"]) - 14
    for label, (_, value) in data["references"]:
        if value is None:
            continue
        x = x_of(value)
        canvas.line([(x, top - 16), (x, bottom)], mix(DEEP, CARD, .35), 1, dashed=True, dash=(3, 4))
    levels = []  # greedy rows so benchmark labels never overlap
    for label, (_, value) in sorted(data["references"], key=lambda item: item[1][1] or 0):
        if value is None:
            continue
        x, text = x_of(value), f"{label} {value:.2f}%"
        half = width(text, 13) / 2 + 6
        level = next((n for n, right in enumerate(levels) if x - half > right), len(levels))
        if level == len(levels):
            levels.append(0)
        levels[level] = x + half
        canvas.text(x, 222 + level * 17, text, 13, MUTED, align="center")
        canvas.line([(x, 222 + level * 17 + 16), (x, top - 16)], mix(DEEP, CARD, .35), 1, dashed=True, dash=(3, 4))
    for index, item in enumerate(data["ladder"]):
        y = top + index * row_h
        variable = item.ticker in ("STRC", "SATA")
        color = GREEN if variable else mix(GREEN, CARD, .45)
        canvas.text(80, y, item.ticker, 26, INK, True)
        canvas.text(170, y + 4, ISSUER[item.ticker], 16, MUTED)
        canvas.text(80, y + 30, KIND[item.ticker], 14, SOFT)
        currency = "€" if item.currency == "EUR" else "$"
        canvas.text(plot_left - 16, y + 2, f"{currency}{item.price:,.2f}" if item.price else "—", 20, INK, True, align="right")
        canvas.text(plot_left - 16, y + 28, f"rate {_pct(item.rate, 2)}", 14, SOFT, align="right")
        if item.effective:
            draw.rounded_rectangle((plot_left, y + 6, x_of(item.effective), y + 34), radius=6, fill=color)
            end = x_of(item.effective)
            canvas.text(end + 10, y + 6, _pct(item.effective, 2), 22, INK, True)
            if data["bill"] is not None:
                canvas.text(end + 10, y + 32, f"+{item.effective - data['bill']:.1f} pp vs bill", 13, MUTED)
    canvas.draw.rounded_rectangle((80, 230, 94, 242), radius=3, fill=GREEN)
    canvas.text(100, 226, "variable-rate digital credit", 14, MUTED)
    canvas.draw.rounded_rectangle((80, 252, 94, 264), radius=3, fill=mix(GREEN, CARD, .45))
    canvas.text(100, 248, "fixed-rate preferreds", 14, MUTED)
    canvas.text(80, 612, "Effective yield = stated rate × $100 ÷ price (Strategy KPIs; SATA from Strive's daily dividend × 252).",
                14, SOFT, max_width=1030)

    # Par tracker (coupon stub).
    box = (1148, 176, 1744, 640)
    canvas.card(box, CARD, 14, outline=LINE)
    canvas.text(1172, 194, "PAR TRACKER · 12 WEEKS", 19, DEEP, True)
    canvas.text(1720, 196, "band $99–$101", 15, MUTED, align="right")
    for index, ticker in enumerate(("STRC", "SATA")):
        stats = data["par"].get(ticker) or {}
        y0 = 234 + index * 202
        series = stats.get("series") or []
        price = series[-1][1] if series else None
        canvas.text(1172, y0, ticker, 24, INK, True)
        if price is not None:
            canvas.text(1250, y0 + 3, f"${price:,.2f}", 22, INK, True)
            diff = price - 100
            canvas.text(1720, y0 + 5, f"{'+' if diff >= 0 else '−'}${abs(diff):.2f} vs par", 18, GREEN if diff >= 0 else RED, True, align="right")
        plot = (1216, y0 + 40, 1720, y0 + 128)
        if len(series) > 2:
            values = [value for _, value in series]
            low, high = min(min(values), 98.5) - .3, max(max(values), 101.2) + .3
            px = lambda i: plot[0] + i / (len(series) - 1) * (plot[2] - plot[0])
            py = lambda v: plot[3] - (v - low) / (high - low) * (plot[3] - plot[1])
            draw.rectangle((plot[0], py(101), plot[2], py(99)), fill=mix(GOLD, CARD, .16))
            canvas.line([(plot[0], py(100)), (plot[2], py(100))], GOLD, 2)
            canvas.text(plot[0] - 6, py(100) - 8, "$100", 13, GOLD, True, align="right")
            canvas.text(plot[0] - 6, plot[3] - 12, f"${low:.0f}", 12, SOFT, align="right")
            canvas.line([(px(i), py(v)) for i, v in enumerate(values)], INK, 2)
            canvas.dot(px(len(values) - 1), py(values[-1]), 5, ORANGE)
            canvas.text(plot[0], plot[3] + 4, _short(series[0][0]), 12, SOFT)
            canvas.text(plot[2], plot[3] + 4, _short(series[-1][0]), 12, SOFT, align="right")
        at = stats.get("at_par_20")
        line = (f"Closed at/above par {at} of last {stats.get('sessions')} sessions · last ≥ $100 {_short(stats.get('last_par'))}"
                if at is not None else "Price history unavailable")
        canvas.text(1172, y0 + 150, line, 15, MUTED, max_width=548)
        if ticker == "SATA" and stats.get("prior_avg"):
            month = stats["prior_month"]
            met = stats["prior_avg"] >= 99
            canvas.text(1172, y0 + 170, f"Cut allowed only if prior-month avg ≥ $99: {month:%b} ${stats['prior_avg']:.2f} → {'allowed' if met else 'not allowed'}",
                        15, ORANGE if met else GREEN, True, max_width=548)
        elif ticker == "STRC":
            canvas.text(1172, y0 + 170, f"Stated rate {_pct(strc.rate, 2) if strc else '—'} · effective {_pct(strc.effective, 2) if strc else '—'}",
                        15, MUTED, max_width=548)

    # Liquidity.
    box = (56, 660, 700, 1010)
    canvas.card(box, CARD, 14, outline=LINE)
    canvas.text(80, 678, "LIQUIDITY · 30-DAY AVERAGE", 19, DEEP, True)
    canvas.text(676, 680, "$ / day · % of shares / day", 15, MUTED, align="right")
    ordered = sorted(data["liquidity"].items(), key=lambda item: -(item[1]["adv"] or 0))
    top_adv = max((item["adv"] or 0) for _, item in ordered) or 1
    for index, (ticker, item) in enumerate(ordered):
        y = 718 + index * 46
        canvas.text(80, y, ticker, 20, INK, True)
        bar_left, bar_right = 160, 520
        if item["adv"]:
            draw.rounded_rectangle((bar_left, y + 4, bar_left + item["adv"] / top_adv * (bar_right - bar_left), y + 24), radius=5,
                                   fill=GREEN if ticker in ("STRC", "SATA") else mix(GREEN, CARD, .45))
        canvas.text(bar_right + 10, y + 1, _money(item["adv"]), 18, INK, True)
        canvas.text(676, y + 2, _pct(item["turnover"], 2), 17, MUTED, align="right")
    ratio = data["credit_adv"] / data["btc_adv"] * 100 if data["btc_adv"] else None
    canvas.text(80, 956, f"STRC + SATA trade {_pct(ratio, 2)} of bitcoin's daily spot volume", 18, INK, True, max_width=600)
    canvas.text(80, 982, "Yahoo daily close × volume · STRE (Luxembourg) excluded", 14, SOFT, max_width=600)

    # Flow ledger.
    box = (718, 660, 1744, 1010)
    canvas.card(box, CARD, 14, outline=LINE)
    canvas.text(742, 678, "FLOW LEDGER · LAST FOUR FILING WEEKS", 19, DEEP, True)
    canvas.text(1720, 680, "+ issued / − repurchased", 15, MUTED, align="right")
    columns = (("WEEK OF", 742, "left"), ("STRC", 990, "right"), ("STRF/K/D/E", 1150, "right"), ("MSTR ATM", 1300, "right"),
               ("SATA", 1440, "right"), ("BUYBACK % VOL", 1590, "right"), ("BTC BOUGHT", 1720, "right"))
    for label, x, align in columns:
        canvas.text(x, 716, label, 13, MUTED, True, align=align)
    draw.line((742, 738, 1720, 738), fill=LINE)
    totals = {"strc": 0, "other": 0, "mstr": 0, "sata": 0}
    for index, entry in enumerate(data["ledger"]):
        y = 750 + index * 50
        values = (_short(entry["week"]), _money(entry.get("strc"), signed=True), _money(entry.get("other"), signed=True),
                  _money(entry.get("mstr"), signed=True), _money(entry.get("sata"), signed=True),
                  _pct(entry.get("buyback_share"), 0) if entry.get("buyback_share") else "—",
                  f"{(entry.get('mstr_btc') or 0):,.0f} · {(entry.get('asst_btc') or 0):,.0f}")
        for (_, x, align), value in zip(columns, values):
            color = RED if value.startswith("−") else GREEN if value.startswith("+") else INK
            canvas.text(x, y, value, 19, color if align == "right" and "$" in value else INK, True if "$" in value else False, align=align)
        for key in totals:
            totals[key] += entry.get(key) or 0
    y = 750 + len(data["ledger"]) * 50
    draw.line((742, y - 8, 1720, y - 8), fill=LINE)
    canvas.text(742, y, f"{len(data['ledger'])}-week total", 19, INK, True)
    for (key, x) in (("strc", 990), ("other", 1150), ("mstr", 1300), ("sata", 1440)):
        value = _money(totals[key], signed=True)
        canvas.text(x, y, value, 19, RED if value.startswith("−") else GREEN if value.startswith("+") else INK, True, align="right")
    canvas.text(1720, y, "MSTR · ASST", 14, SOFT, align="right")
    canvas.text(742, 982, "Monday 8-K cash (Strategy); SATA = net share change × $100. Buyback % = STRC repurchased ÷ STRC shares traded that week.",
                14, SOFT, max_width=980)

    # Coverage.
    box = (56, 1030, 980, 1318)
    canvas.card(box, CARD, 14, outline=LINE)
    canvas.text(80, 1048, "COVERAGE · WHAT STANDS BEHIND THE COUPONS", 19, DEEP, True)
    for index, (ticker, name) in enumerate((("MSTR", "Strategy"), ("ASST", "Strive"))):
        item = data["coverage"].get(ticker)
        x0 = 80 + index * 452
        canvas.text(x0, 1086, name, 22, INK, True)
        if not item:
            canvas.text(x0, 1120, "Monday balances unavailable", 16, MUTED)
            continue
        months = item.reserve_months
        canvas.text(x0, 1122, "USD COVER", 13, MUTED, True)
        canvas.text(x0 + 420, 1118, f"{months:.0f} months" if months else "—", 20, INK, True, align="right")
        bar = (x0, 1146, x0 + 420, 1160)
        draw.rounded_rectangle(bar, radius=7, fill=mix(GREEN, CARD, .12))
        if months:
            draw.rounded_rectangle((bar[0], bar[1], bar[0] + min(1, months / 48) * (bar[2] - bar[0]), bar[3]), radius=7, fill=GREEN)
            fx = bar[0] + data["floor"] / 48 * (bar[2] - bar[0])
            canvas.line([(fx, bar[1] - 6), (fx, bar[3] + 6)], ORANGE, 3)
            canvas.text(fx, bar[3] + 6, "12-mo floor" if ticker == "MSTR" else "12 mo", 12, ORANGE, align="center")
        stats = (("TOTAL COVERAGE", f"{item.coverage_years:.0f} yrs" if item.coverage_years else "—"),
                 ("BTC BREAK-EVEN", f"{_pct(item.breakeven_pct, 2)}/yr"),
                 ("DEBT + PREF ÷ BTC", _pct(item.amplification_pct, 1)))
        for n, (label, value) in enumerate(stats):
            sx = x0 + n * 146
            canvas.text(sx, 1200, label, 12, MUTED, True, max_width=140)
            canvas.text(sx, 1220, value, 22, INK, True, max_width=140)
        net = item.net_leverage_pct
        canvas.text(x0, 1262, "net cash (cash exceeds debt)" if net is not None and net < 0 else f"net leverage {_pct(net, 1)} (debt − cash) ÷ BTC",
                    15, MUTED, max_width=420)
    canvas.text(80, 1292, "Same dated balances as Monday's Accretion Ledger · coverage = (BTC + cash) ÷ annual preferred dividends",
                14, SOFT, max_width=880)

    # Calendar.
    box = (998, 1030, 1744, 1318)
    canvas.card(box, CARD, 14, outline=LINE)
    _perforation(canvas, 998, 1030, 1318)
    canvas.text(1022, 1048, "ON THE CALENDAR", 19, DEEP, True)
    today = now.date()
    for index, (day, label, note) in enumerate(data["calendar"]):
        y = 1086 + index * 36
        parsed = date.fromisoformat(day)
        canvas.pill(1022, y - 2, f"{parsed:%b} {parsed.day}".upper(), 14, CARD, DEEP)
        canvas.text(1112, y, label, 17, INK, True, max_width=380)
        canvas.text(1720, y + 1, f"{(parsed - today).days} d · {note}", 14, MUTED, align="right", max_width=230)
    if data.get("sata_rate"):
        canvas.text(1022, 1292, f"SATA pays every business day at a stated {data['sata_rate']:.2f}% · STRC semi-monthly", 14, SOFT, max_width=700)

    stale = data.get("stale") or ()
    footer = ("Sources: strategy.com KPIs · Strive dashboard · Yahoo Finance · FRED (SOFR, DGS3MO, DGS10, ICE BofA IG/HY) · "
              "SEC 8-K filings. Estimates are labeled; unavailable values show —.")
    if stale:
        footer += " Saved snapshot used for: " + ", ".join(stale) + "."
    canvas.text(56, 1336, footer, 15, MUTED, max_width=1688)
    png = canvas.save(metadata={"Title": "The Coupon Sheet", "Software": "The Digital Credit Report (preview)"})
    return png, canvas.overflows


def audit_rows(data: dict) -> list[dict]:
    rows = []
    for item in data["ladder"]:
        rows.append({"metric": f"{item.ticker} price", "value": f"{item.price:.2f} {item.currency}" if item.price else "—",
                     "source": "strategy.com KPIs" if item.ticker != "SATA" else "Yahoo Finance"})
        rows.append({"metric": f"{item.ticker} effective yield", "value": _pct(item.effective), "source": "rate × 100 ÷ price"})
    for label, (day, value) in data["references"]:
        rows.append({"metric": label, "value": f"{value:.2f}% ({day})" if value is not None else "—", "source": "FRED"})
    for ticker, stats in data["par"].items():
        rows.append({"metric": f"{ticker} closes at/above par, last 20", "value": str(stats.get("at_par_20")), "source": "Yahoo Finance"})
    for entry in data["ledger"]:
        rows.append({"metric": f"Week of {entry['week']} STRC net / SATA net", "value": f"{_money(entry.get('strc'), signed=True)} / {_money(entry.get('sata'), signed=True)}", "source": "SEC 8-K"})
    return rows
