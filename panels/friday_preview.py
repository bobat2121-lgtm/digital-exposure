"""Friday preview: "The Closing Mark." — marked at the Friday 4:00 pm ET close.

Consumes the production Friday panel (``friday.metrics.compute_panel``) and its
raw provider data, plus ``panels.extras``. New readings computed here:
50-week SMA and the 20W SMA / 21W EMA band from Friday closes, weekly RSI(14),
50D/200D cross, named 200W zones, share turnover, Fear & Greed regime length,
the seven-cell cycle checklist and the macro strip. Nothing here uses a
Sunday close: every weekly reading is taken at the Friday mark.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import threading
from zoneinfo import ZoneInfo

from friday.export import display_rows, sma_segments
from friday.series import SENTIMENT_BANDS, smooth_sentiment, year_start

from . import themes
from .draw import Canvas, fontset, imprint, mix, sparkline, width
from .extras import fred_latest, number

ET = ZoneInfo("America/New_York")
WIDTH, HEIGHT = 1800, 1800
BG, CARD, TEXT, MUTED, SOFT = "#0b0d0f", "#15191d", "#f5f3ed", "#9aa4ad", "#6f7a83"
LINE, ORANGE, POSITIVE, NEGATIVE, NEUTRAL = "#30363c", "#e88029", "#8cdbb5", "#f5a09b", "#d9c86a"
BLUE, VIOLET, BAND = "#7fb2ff", "#c39bff", "#56c4a0"
TITLE = ("The ", "Closing", " Mark")
THEME = themes.CLASSIC
# Rendering swaps the module palette for the requested theme; the lock keeps
# concurrent Streamlit sessions from drawing with each other's colors.
_LOCK = threading.RLock()
# How each checklist reading maps to a state (anything else is NEUTRAL).
RULES = {"50W SMA": "bull above · bear at/below", "20W / 21W BAND": "bull above · bear below",
         "50D / 200D": "bull golden · bear death", "WEEKLY RSI": "bull ≥ 50 · bear < 50",
         "MVRV": "bull < 1 · bear > avg + 1 sd", "PUELL MULTIPLE": "bull < low · bear > high band",
         "SUPPLY IN PROFIT": "bull < 50% · bear > 95%"}
# Crypto Currently's names for distance above the 200-week SMA. Its thresholds
# are not published; these follow the levels quoted in its weekly reports.
ZONES = ((0, "VERY CHEAP", "#304cba"), (50, "CHEAP", "#198653"), (100, "FAIR VALUE", "#b8a528"),
         (150, "EXPENSIVE", "#c67b1b"), (None, "VERY EXPENSIVE", "#ba3b48"))


def _use(theme):
    global BG, CARD, TEXT, MUTED, SOFT, LINE, ORANGE, POSITIVE, NEGATIVE, NEUTRAL, BLUE, VIOLET, BAND, THEME
    p = theme.friday
    BG, CARD, TEXT, MUTED, SOFT = p.bg, p.card, p.ink, p.muted, p.soft
    LINE, ORANGE, POSITIVE, NEGATIVE, NEUTRAL = p.line, p.accent, p.positive, p.negative, p.neutral
    BLUE, VIOLET, BAND, THEME = p.accent2, p.accent3, p.band, theme


def _card(canvas, box, accent=None, accent_height=3):
    if THEME.key == "classic":
        canvas.card(box, CARD, 10, accent, accent_height)
    else:
        themes.card(canvas, box, THEME.friday, accent, THEME, accent_height)


def zone(extension):
    if extension is None:
        return None, MUTED
    for upper, name, color in ZONES:
        if upper is None or extension < upper:
            return name, color
    return ZONES[-1][1], ZONES[-1][2]


def _sma(values, count):
    return sum(values[-count:]) / count if len(values) >= count else None


def _ema(values, count):
    if len(values) < count:
        return None
    k, ema = 2 / (count + 1), sum(values[:count]) / count
    for value in values[count:]:
        ema = value * k + ema * (1 - k)
    return ema


def _rsi(values, count=14):
    if len(values) <= count:
        return None
    gains = [max(b - a, 0) for a, b in zip(values, values[1:])]
    losses = [max(a - b, 0) for a, b in zip(values, values[1:])]
    gain, loss = sum(gains[:count]) / count, sum(losses[:count]) / count
    for g, l in zip(gains[count:], losses[count:]):
        gain, loss = (gain * (count - 1) + g) / count, (loss * (count - 1) + l) / count
    return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)


def _weekly_btc(data, cutoff):
    """Completed Friday UTC daily closes before the Friday mark (as the 200W)."""
    rows = [row for row in data.get("prices", {}).get("BTC", [])
            if date.fromisoformat(row["date"]).weekday() == 4 and row["date"] < cutoff]
    return [(row["date"], row["close"]) for row in rows]


def _rolling(series, fn):
    out, values = [], []
    for day, close in series:
        values.append(close)
        out.append((day, fn(values)))
    return out


def _turnover(data, ticker, shares, period, calendar_sessions):
    """Weekly shares traded as % of shares outstanding, last 12 completed weeks."""
    rows = {row["date"]: row for row in data.get("prices", {}).get(ticker, [])}
    monday = date.fromisoformat(period["start"])
    weeks = []
    for offset in range(11, -1, -1):
        start = monday - timedelta(weeks=offset)
        sessions = [day.isoformat() for day in calendar_sessions(start, start + timedelta(days=4))]
        volumes = [number(rows.get(day, {}).get("volume")) for day in sessions]
        complete = all(value is not None for value in volumes) and bool(sessions)
        traded = sum(value for value in volumes if value is not None)
        weeks.append({"week": (start + timedelta(days=4)).isoformat(),
                      "pct": traded / shares * 100 if complete and shares else None, "shares": traded if complete else None})
    return weeks


def _regime(series):
    """Current Fear & Greed band of the 3-day average and how long it has held."""
    smooth = smooth_sentiment(series, window=3)
    if not smooth:
        return None, None, None
    def band(value):
        return next((item for item in SENTIMENT_BANDS if value < item["upper"]), SENTIMENT_BANDS[-1])
    current = band(smooth[-1]["smoothed_value"])
    start = smooth[-1]["date"]
    for row in reversed(smooth):
        if band(row["smoothed_value"]) is not current:
            break
        start = row["date"]
    days = (date.fromisoformat(smooth[-1]["date"]) - date.fromisoformat(start)).days + 1
    return current["label"], current["color"], days


def _cross(series):
    """50D vs 200D state and the date it last flipped."""
    state, since = None, None
    for row in series:
        fast, slow = number(row.get("sma_50d")), number(row.get("sma_200d"))
        if fast is None or slow is None:
            continue
        current = fast > slow
        if current != state:
            state, since = current, row["date"]
    return state, since


def derive(panel: dict, data: dict, extras: dict, feed: dict) -> dict:
    """``feed`` is the Monday filing feed; only validated filings are used."""
    from friday.metrics import _sessions, _calendar
    from report import live_report
    feed_rows = live_report._merged_filings(feed or {"filings": []}, live_report._load(live_report.CHECKPOINT))
    period = panel["period"]
    btc_price = panel["header"]["btc"].get("price")
    cutoff = datetime.fromisoformat(period["as_of"]).astimezone(ZoneInfo("UTC")).date().isoformat()
    weekly = _weekly_btc(data, cutoff)
    closes = [close for _, close in weekly]
    sma50w, sma20w, ema21w = _sma(closes, 50), _sma(closes, 20), _ema(closes, 21)
    # Friday marks above the 50W: this Friday's 4 pm mark, then prior Fridays.
    above = 0
    if btc_price and sma50w and btc_price > sma50w:
        above = 1
        for index in range(len(closes) - 1, -1, -1):
            average = _sma(closes[:index + 1], 50)
            if average is None or closes[index] <= average:
                break
            above += 1
    extension = ((panel.get("trends") or {}).get("BTC", {}).get("averages", {}).get("200W", {}) or {}).get("extension_pct")
    zone_name, zone_color = zone(extension)
    daily = [row["close"] for row in data.get("prices", {}).get("BTC", []) if row["date"] < cutoff]
    btc_cross = (_sma(daily, 50) or 0) > (_sma(daily, 200) or 0) if len(daily) >= 200 else None
    btc_cross_since = None
    if len(daily) >= 200:
        dates = [row["date"] for row in data["prices"]["BTC"] if row["date"] < cutoff]
        state = None
        for index in range(199, len(daily)):
            current = sum(daily[index - 49:index + 1]) / 50 > sum(daily[index - 199:index + 1]) / 200
            if current != state:
                state, btc_cross_since = current, dates[index]
    rsi = _rsi(closes)
    onchain = extras.get("onchain") or {}
    supply = panel.get("supply_loss") or {}
    profit = number(supply.get("profit_pct"))
    mvrv, mean, plus1 = onchain.get("mvrv"), onchain.get("mvrv_mean"), onchain.get("mvrv_plus1sd")
    puell, low, high = onchain.get("puell"), onchain.get("puell_low"), onchain.get("puell_high")
    band_low, band_high = (min(sma20w, ema21w), max(sma20w, ema21w)) if sma20w and ema21w else (None, None)

    def status(bull, bear):
        return "BULL" if bull else "BEAR" if bear else "NEUTRAL"

    checklist = [
        ("50W SMA", f"{_pct(_change(btc_price, sma50w), 1, True)}", f"Fri mark vs ${sma50w / 1e3:,.1f}k" if sma50w else "—",
         status(btc_price and sma50w and btc_price > sma50w, btc_price and sma50w and btc_price <= sma50w)),
        ("20W / 21W BAND", "above" if btc_price and band_high and btc_price > band_high else "below" if btc_price and band_low and btc_price < band_low else "inside",
         f"${band_low / 1e3:,.1f}k–${band_high / 1e3:,.1f}k" if band_low else "—",
         status(btc_price and band_high and btc_price > band_high, btc_price and band_low and btc_price < band_low)),
        ("50D / 200D", "golden cross" if btc_cross else "death cross" if btc_cross is False else "—",
         f"since {_short(btc_cross_since)}" if btc_cross_since else "", status(btc_cross is True, btc_cross is False)),
        ("WEEKLY RSI", f"{rsi:.0f}" if rsi is not None else "—", "14 Friday closes · 50 line",
         status(rsi is not None and rsi >= 50, rsi is not None and rsi < 50)),
        ("MVRV", f"{mvrv:.2f}" if mvrv else "—", f"realized ${onchain.get('realized_price', 0) / 1e3:,.1f}k · avg {mean:.2f}" if mvrv and mean else "—",
         status(mvrv is not None and mvrv < 1, mvrv is not None and plus1 is not None and mvrv > plus1)),
        ("PUELL MULTIPLE", f"{puell:.2f}" if puell else "—", f"bands {low:.2f}–{high:.2f}" if low and high else "—",
         status(puell is not None and low is not None and puell < low, puell is not None and high is not None and puell > high)),
        ("SUPPLY IN PROFIT", f"{profit:.1f}%" if profit is not None else "—", "bottoms 40–50% · heat 95%+",
         status(profit is not None and profit < 50, profit is not None and profit > 95)),
    ]
    tally = {key: sum(1 for *_, value in checklist if value == key) for key in ("BULL", "NEUTRAL", "BEAR")}

    # Turnover: basic common shares; preferred shares = notional / $100.
    treasury = {row["ticker"]: row for row in panel.get("treasury", [])}
    strategy = (extras.get("strategy") or {}).get("preferreds") or {}
    strc_shares = (number(strategy.get("STRC", {}).get("notional")) or 0) / 100 or None
    sata_rows = [row for row in feed_rows if row.get("ticker") == "ASST" and number(row["extracted"]["facts"].get("sata_shares"))]
    sata_rows.sort(key=lambda row: row["extracted"]["balanceDate"])
    sata_shares = number(sata_rows[-1]["extracted"]["facts"]["sata_shares"]) if sata_rows else None
    shares = {"MSTR": treasury.get("MSTR", {}).get("shares"), "ASST": treasury.get("ASST", {}).get("shares"),
              "STRC": strc_shares, "SATA": sata_shares}
    calendar = _calendar()
    sessions = lambda start, end: _sessions(start, end, calendar)
    turnover = {ticker: _turnover(data, ticker, shares[ticker], period, sessions) for ticker in shares}
    mstr_rows = [row for row in feed_rows if row.get("ticker") == "MSTR"]
    mstr_rows.sort(key=lambda row: row["extracted"]["balanceDate"])
    buyback = None
    if mstr_rows:
        latest = mstr_rows[-1]["extracted"]
        repurchased = number((latest.get("securities", {}).get("STRC") or {}).get("repurchasedShares"))
        start, end = latest["periodStart"], latest["periodEnd"]
        strc_rows = [row for row in data.get("prices", {}).get("STRC", []) if start <= row["date"] <= end]
        traded = sum(number(row.get("volume")) or 0 for row in strc_rows)
        if repurchased is not None and traded:
            buyback = {"shares": repurchased, "pct": repurchased / traded * 100, "start": start, "end": end}

    label, color, days = _regime((panel.get("sentiment") or {}).get("series") or [])
    macro = _macro(extras)
    return {"sma50w": sma50w, "sma20w": sma20w, "ema21w": ema21w, "weeks_above_50w": above, "rsi": rsi,
            "extension": extension, "zone": zone_name, "zone_color": zone_color,
            "weekly": weekly, "sma50w_series": _rolling(weekly, lambda v: _sma(v, 50)),
            "sma20w_series": _rolling(weekly, lambda v: _sma(v, 20)), "ema21w_series": _rolling(weekly, lambda v: _ema(v, 21)),
            "realized": onchain.get("realized_weekly") or [], "realized_price": onchain.get("realized_price"),
            "checklist": checklist, "tally": tally, "turnover": turnover, "shares": shares, "buyback": buyback,
            "regime": (label, color, days), "macro": macro,
            "crosses": {ticker: _cross((panel.get("trends") or {}).get(ticker, {}).get("series") or []) for ticker in ("MSTR", "ASST")}}


def _macro(extras):
    yahoo = extras.get("yahoo") or {}

    def series(symbol):
        rows = (yahoo.get(symbol) or {}).get("rows") or []
        return [(row["date"], row["close"]) for row in rows]

    dxy = series("DX-Y.NYB")
    tnx = series("^TNX")
    fred = extras.get("fred") or {}
    ff = {day: value for day, value in fred.get("DFF", [])}
    two = fred.get("DGS2", [])
    gap = [(day, ff[day] - value) for day, value in two if day in ff]

    def weekly_change(rows):
        if len(rows) < 6:
            return None
        return rows[-1][1] - rows[-6][1]

    return {
        "dxy": dxy[-65:], "dxy_change": weekly_change(dxy),
        "tnx": tnx[-65:], "tnx_change": weekly_change(tnx),
        "gap": gap[-65:], "gap_change": weekly_change(gap),
        "ff": fred_latest(extras, "DFF"), "two": fred_latest(extras, "DGS2"),
    }


def _change(end, start):
    return (end / start - 1) * 100 if end and start else None


def _pct(value, digits=1, signed=False):
    if value is None:
        return "—"
    sign = "−" if round(value, digits) < 0 else "+" if signed and round(value, digits) > 0 else ""
    return f"{sign}{abs(value):,.{digits}f}%"


def _short(day):
    if not day:
        return ""
    parsed = date.fromisoformat(str(day)[:10])
    return f"{parsed:%b} {parsed.day}"


def _money(value, digits=0):
    return f"${value:,.{digits}f}" if value is not None else "—"


def _volume(value):
    if value is None:
        return "—"
    for unit, divisor in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= divisor:
            return f"${value / divisor:,.2f}{unit}"
    return f"${value:,.0f}"


def _tone(value):
    return POSITIVE if value is not None and value > 0 else NEGATIVE if value is not None and value < 0 else MUTED


# ── charts ──────────────────────────────────────────────────────────────────
def _ordinal(day):
    return date.fromisoformat(str(day)[:10]).toordinal()


def _plot(canvas, box, series, low, high, start, end):
    """series: list of dicts {points: [(day, value)], color, width, dashed}."""
    x0, y0, x1, y1 = box
    span = max(1, end - start)

    def xy(day, value):
        return x0 + (_ordinal(day) - start) / span * (x1 - x0), y1 - (value - low) / (high - low) * (y1 - y0)

    for item in series:
        points = [xy(day, value) for day, value in item["points"]
                  if value is not None and start <= _ordinal(day) <= end]
        points = [(x, min(max(y, y0), y1)) for x, y in points]
        canvas.line(points, item["color"], item.get("width", 2), dashed=item.get("dashed", False), dash=item.get("dash", (9, 7)))
    return xy


def _axis(canvas, box, low, high, start, end, fmt):
    x0, y0, x1, y1 = box
    for fraction in (0, .5, 1):
        y = y1 - fraction * (y1 - y0)
        canvas.draw.line((x0, y, x1, y), fill=LINE)
        canvas.text(x0 - 8, y - 9, fmt(low + (high - low) * fraction), 14, MUTED, align="right")
    first, last = date.fromordinal(start), date.fromordinal(end)
    canvas.text(x0, y1 + 8, f"{first:%b %Y}", 15, MUTED)
    canvas.text(x1, y1 + 8, f"{last:%b %Y}", 15, MUTED, align="right")


def _price(value):
    if value >= 1000:
        return f"${value / 1e3:,.0f}k"
    return f"${value:,.0f}"


def _btc_chart(canvas, box, panel, derived):
    trend = (panel.get("trends") or {}).get("BTC") or {}
    rows = display_rows(trend.get("series"), (panel.get("period") or {}).get("end"), 4)
    rows = [row for row in rows if date.fromisoformat(row["date"]).weekday() == 4]
    if len(rows) < 2:
        canvas.text(box[0] + 20, box[1] + 40, "BTC history unavailable", 20, MUTED)
        return
    start, end = _ordinal(rows[0]["date"]), _ordinal(rows[-1]["date"])
    prices = [row["close"] for row in rows]
    sma = [row.get("sma_200w") for row in rows]
    visible_sma = [value for value in sma if value]
    low = min(prices + visible_sma + [value for _, value in derived["realized"] if value and _ordinal(_) >= start]) * .9
    high = max(max(prices), max(visible_sma) * 2.6) * 1.02
    x0, y0, x1, y1 = box
    xy = lambda day, value: (x0 + (_ordinal(day) - start) / max(1, end - start) * (x1 - x0),
                             y1 - (value - low) / (high - low) * (y1 - y0))
    # Named zones between multiples of the 200W SMA.
    multiples = (0, 1, 1.5, 2, 2.5, 99)
    segment = [row for row in rows if row.get("sma_200w")]
    for index, (_, name, color) in enumerate(ZONES):
        lower, upper = multiples[index], multiples[index + 1]
        top = [xy(row["date"], min(high, row["sma_200w"] * upper) if upper < 99 else high) for row in segment]
        bottom = [xy(row["date"], max(low, row["sma_200w"] * lower) if lower else low) for row in segment]
        polygon = [(x, min(max(y, y0), y1)) for x, y in top + list(reversed(bottom))]
        if len(polygon) > 2:
            canvas.draw.polygon(polygon, fill=mix(color, CARD, .20))
    _axis(canvas, box, low, high, start, end, _price)
    # Zone labels on the right edge, at each band's midpoint on the last SMA.
    last_sma = segment[-1]["sma_200w"] if segment else None
    if last_sma:
        for index, (_, name, color) in enumerate(ZONES):
            lower, upper = multiples[index], min(multiples[index + 1], high / last_sma)
            mid = last_sma * (lower + upper) / 2 if index else (low + last_sma) / 2
            y = xy(rows[-1]["date"], mid)[1]
            if y0 + 8 < y < y1 - 8:
                canvas.text(x1 + 8, y - 8, name.title(), 14, mix(color, TEXT, .55), True)
    series = [
        {"points": [(row["date"], row.get("sma_200w")) for row in rows], "color": ORANGE, "width": 3, "dashed": True},
        {"points": [(day, value) for day, value in derived["realized"]], "color": VIOLET, "width": 2, "dashed": True, "dash": (4, 5)},
        {"points": derived["sma50w_series"], "color": BLUE, "width": 2},
        {"points": derived["sma20w_series"], "color": BAND, "width": 2},
        {"points": derived["ema21w_series"], "color": BAND, "width": 2, "dashed": True, "dash": (5, 4)},
        {"points": [(row["date"], row["close"]) for row in rows], "color": TEXT, "width": 3},
    ]
    _plot(canvas, box, series, low, high, start, end)
    mark = panel["header"]["btc"].get("price")
    if mark:
        x, y = xy(rows[-1]["date"], mark)
        canvas.dot(x, y, 6, TEXT, outline=CARD)


def _equity_chart(canvas, box, panel, ticker, derived):
    trend = (panel.get("trends") or {}).get(ticker) or {}
    end = trend.get("price_as_of") or (panel.get("period") or {}).get("end")
    rows = display_rows(trend.get("series"), end, start=year_start(end)) if ticker == "ASST" else display_rows(trend.get("series"), end, 1)
    if len(rows) < 2:
        canvas.text(box[0] + 20, box[1] + 30, "History unavailable", 18, MUTED)
        return
    start, stop = _ordinal(rows[0]["date"]), _ordinal(rows[-1]["date"])
    values = [row["close"] for row in rows] + [row["sma_200d"] for row in rows if row.get("sma_200d")]
    low, high = min(values) * .92, max(values) * 1.06
    _axis(canvas, box, low, high, start, stop, lambda v: f"${v:,.0f}")
    x0, y0, x1, y1 = box
    xy = lambda day, value: (x0 + (_ordinal(day) - start) / max(1, stop - start) * (x1 - x0),
                             y1 - (value - low) / (high - low) * (y1 - y0))
    for multiple, color in ((1.5, "#6d7073"), (2, "#6d7073")):
        points = [xy(row["date"], row["sma_200d"] * multiple) for row in rows if row.get("sma_200d")]
        points = [(x, y) for x, y in points if y0 <= y <= y1]
        canvas.line(points, color, 1, dashed=True, dash=(4, 5))
    series = [
        {"points": [(row["date"], row.get("sma_200d")) for row in rows], "color": ORANGE, "width": 3, "dashed": True},
        {"points": [(row["date"], row.get("sma_50d")) for row in rows], "color": BLUE, "width": 2},
        {"points": [(row["date"], row["close"]) for row in rows], "color": TEXT, "width": 3},
    ]
    _plot(canvas, box, series, low, high, start, stop)


# ── render ──────────────────────────────────────────────────────────────────
def render_png(panel: dict, derived: dict, *, stale: tuple = (), theme: themes.Theme = themes.CLASSIC) -> tuple[bytes, list[str]]:
    with _LOCK, fontset(theme.fontset):
        _use(theme)
        try:
            return _render(panel, derived, stale)
        finally:
            _use(themes.CLASSIC)


def _render(panel: dict, derived: dict, stale: tuple) -> tuple[bytes, list[str]]:
    canvas = Canvas((WIDTH, HEIGHT), BG)
    draw = canvas.draw
    period, header = panel.get("period") or {}, panel.get("header") or {}
    week_end = period.get("week_ending", period.get("end"))
    if THEME.key == "classic":
        draw.rectangle((0, 0, WIDTH, 5), fill=ORANGE)
    else:
        themes.background(canvas, THEME.friday, THEME, header_height=142, orbit_at=(1040, 62, .62))
    canvas.text(54, 26, f"THE DIGITAL CREDIT REPORT  ·  FRIDAY  ·  WEEK ENDED {_short(week_end).upper()}", 18, ORANGE, True)
    if THEME.key == "classic":
        imprint(canvas, 54, 104, TITLE, 54, ink=TEXT, muted="#aab3ba", dot=ORANGE)
    else:
        themes.title(canvas, 54, 104, TITLE, 54, THEME.friday, THEME, on_space=THEME.decor == "orbit")
    canvas.text(54, 120, "Bitcoin, treasury premiums, liquidity & cycle — every reading marked at the Friday 4:00 pm ET close",
                19, MUTED, max_width=1180)
    canvas.text(1746, 30, "MARKED FRI 4:00 PM ET", 19, ORANGE, True, align="right")
    canvas.text(1746, 60, f"Week of {_short(period.get('start'))}–{_short(week_end)}, {date.fromisoformat(str(week_end)[:10]).year}"
                if week_end else "", 24, TEXT, align="right")
    canvas.text(1746, 96, "Balances: " + " · ".join(f"{row['ticker']} {_short(row.get('baseline_at'))}"
                                                     for row in panel.get("treasury", []) if row.get("baseline_at")),
                17, MUTED, align="right")

    # Row A: BTC + treasury tiles.
    btc = header.get("btc") or {}
    tiles = [(54, 150, 606, 340), (624, 150, 1176, 340), (1194, 150, 1746, 340)]
    _card(canvas, tiles[0], ORANGE)
    canvas.text(78, 166, "BITCOIN", 20, TEXT, True)
    canvas.text(582, 168, "FRI 4 PM MARK", 16, MUTED, True, align="right")
    canvas.text(78, 196, _money(btc.get("price")), 50, TEXT, True)
    change = btc.get("weekly_return_pct")
    canvas.text(78, 256, _pct(change, 2, True) + " this week", 24, _tone(change), True)
    zone_name, zone_color = derived["zone"], derived["zone_color"]
    if zone_name:
        canvas.pill(582, 252, f"{zone_name} · {_pct(derived['extension'], 1, True)} vs 200W", 15, TEXT, mix(zone_color, CARD, .75), align="right")
    sma50 = derived["sma50w"]
    vs = _change(btc.get("price"), sma50)
    status = (f"Above the 50W SMA (${sma50 / 1e3:,.1f}k) by {_pct(vs, 1)} · {derived['weeks_above_50w']} straight Friday"
              f"{'s' if derived['weeks_above_50w'] != 1 else ''}" if vs is not None and vs > 0
              else f"Below the 50W SMA (${sma50 / 1e3:,.1f}k) by {_pct(abs(vs), 1)}" if vs is not None else "50W SMA unavailable")
    canvas.text(78, 302, status, 18, POSITIVE if vs and vs > 0 else NEGATIVE if vs else MUTED, max_width=504)
    companies = header.get("companies") or {}
    treasury = {row.get("ticker"): row for row in panel.get("treasury", [])}
    for ticker, box in zip(("MSTR", "ASST"), tiles[1:]):
        x0, _, x1, _ = box
        company, base = companies.get(ticker) or {}, treasury.get(ticker) or {}
        _card(canvas, box, TEXT)
        canvas.text(x0 + 24, 166, ticker, 20, TEXT, True)
        canvas.text(x1 - 24, 168, "PRICE / NAV", 16, MUTED, True, align="right")
        multiple = company.get("nav_multiple")
        canvas.text(x0 + 24, 196, f"{multiple:.2f}x" if multiple else "—", 50, TEXT, True)
        delta = company.get("nav_multiple_change")
        canvas.text(x1 - 24, 214, f"WoW {delta:+.2f}x" if delta is not None else "WoW —", 22, _tone(delta), align="right")
        canvas.text(x0 + 24, 256, f"NAV/share {_money(company.get('nav_per_share'), 2)}   ·   price {_money(company.get('price'), 2)}", 20, MUTED, max_width=500)
        impact, impact_pct = base.get("btc_effect_per_share"), base.get("nav_change_pct")
        amount = f"{'+' if impact >= 0 else '−'}${abs(impact):,.2f}" if impact is not None else "—"
        state, since = derived["crosses"].get(ticker, (None, None))
        cross = ("golden cross" if state else "death cross" if state is False else "") + (f" since {_short(since)}" if since else "")
        canvas.text(x0 + 24, 290, f"NAV/share WoW {amount} ({_pct(impact_pct, 2, True)})", 19, _tone(impact), max_width=300)
        canvas.text(x1 - 24, 290, f"50D/200D {cross}", 17, MUTED, align="right", max_width=210)

    # Macro strip.
    macro = derived["macro"]
    strip = [
        ("US DOLLAR INDEX", macro["dxy"], f"{macro['dxy'][-1][1]:.2f}" if macro["dxy"] else "—",
         f"{macro['dxy_change']:+.2f} WoW · 101 resistance" if macro["dxy_change"] is not None else "101 resistance", 101.0),
        ("US 10-YEAR YIELD", macro["tnx"], f"{macro['tnx'][-1][1]:.2f}%" if macro["tnx"] else "—",
         f"{macro['tnx_change'] * 100:+.0f} bp WoW" if macro["tnx_change"] is not None else "", None),
        ("FED FUNDS − 2-YEAR", macro["gap"], f"{macro['gap'][-1][1] * 100:+.0f} bp" if macro["gap"] else "—",
         (f"FF {macro['ff'][1]:.2f}% vs 2Y {macro['two'][1]:.2f}% · {_short(macro['two'][0])}" if macro["two"][1] else ""), 0.0),
    ]
    for index, (label, rows, value, note, reference) in enumerate(strip):
        x0 = 54 + index * 570
        box = (x0, 352, x0 + 552, 440)
        _card(canvas, box)
        canvas.text(x0 + 20, 364, label, 15, MUTED, True)
        canvas.text(x0 + 20, 386, value, 30, TEXT, True)
        canvas.text(x0 + 20, 420, note, 14, MUTED, max_width=300)
        if len(rows) > 2:
            sparkline(canvas, (x0 + 330, 372, x0 + 532, 424), [v for _, v in rows], ORANGE, width_px=2,
                      baseline=reference, baseline_color=SOFT)

    # Turnover.
    canvas.text(54, 458, "WEEKLY TURNOVER · % OF SHARES OUTSTANDING TRADED", 21, TEXT, True)
    canvas.text(1746, 461, "12 completed weeks · Friday close · same scale within each pair", 17, MUTED, align="right")
    liquidity = {row.get("ticker"): row for row in panel.get("liquidity", [])}
    for box, title, tickers in (((54, 490, 891, 760), "Common stock", ("MSTR", "ASST")),
                                ((909, 490, 1746, 760), "Preferred stock", ("STRC", "SATA"))):
        x0, y0, x1, y1 = box
        _card(canvas, box)
        canvas.text(x0 + 22, y0 + 14, title, 19, MUTED)
        for i, ticker in enumerate(tickers):
            weeks = derived["turnover"][ticker]
            latest = weeks[-1]["pct"] if weeks else None
            color = ORANGE if i == 0 else TEXT
            x = x0 + 22 + i * 400
            canvas.draw.rectangle((x, y0 + 50, x + 12, y0 + 62), fill=color)
            canvas.text(x + 22, y0 + 42, f"{ticker}  {_pct(latest, 2)}/wk", 24, color, True, max_width=360)
            dollars = liquidity.get(ticker, {}).get("dollars")
            shares = derived["shares"].get(ticker)
            canvas.text(x, y0 + 76, f"≈{_volume(dollars)} traded · {shares / 1e6:,.1f}m shares out" if shares else "shares outstanding n/a",
                        15, MUTED, max_width=370)
        plot = (x0 + 70, y0 + 106, x1 - 22, y0 + 208)
        values = [week["pct"] for ticker in tickers for week in derived["turnover"][ticker] if week["pct"] is not None]
        top = max(values or [1]) * 1.1
        for fraction in (0, .5, 1):
            y = plot[3] - fraction * (plot[3] - plot[1])
            canvas.draw.line((plot[0], y, plot[2], y), fill=LINE)
            canvas.text(plot[0] - 8, y - 9, f"{top * fraction:.1f}%", 14, MUTED, align="right")
        weeks = derived["turnover"][tickers[0]]
        group = (plot[2] - plot[0]) / max(1, len(weeks))
        bar = min(16, group * .3)
        for j in range(len(weeks)):
            center = plot[0] + group * (j + .5)
            for i, ticker in enumerate(tickers):
                value = derived["turnover"][ticker][j]["pct"]
                left = center + (i - 1) * bar + i * 3
                if value is not None:
                    canvas.draw.rectangle((left, plot[3] - value / top * (plot[3] - plot[1]), left + bar, plot[3]),
                                          fill=ORANGE if i == 0 else TEXT)
            if j in (0, 4, 8, len(weeks) - 1):
                canvas.text(center, plot[3] + 8, _short(weeks[j]["week"]), 14, MUTED, align="center")
        if tickers[0] == "STRC" and derived["buyback"]:
            b = derived["buyback"]
            canvas.text(x0 + 22, y1 - 26, f"Strategy repurchased {b['shares'] / 1e6:.2f}m STRC = {b['pct']:.0f}% of STRC volume "
                        f"({_short(b['start'])}–{_short(b['end'])} filing week)", 15, MUTED, max_width=x1 - x0 - 44)
        else:
            canvas.text(x0 + 22, y1 - 26, "Turnover = weekly shares traded ÷ basic shares (preferred: notional ÷ $100)",
                        15, MUTED, max_width=x1 - x0 - 44)

    # Cycle checklist.
    tally = derived["tally"]
    canvas.text(54, 780, "CYCLE CHECKLIST", 21, TEXT, True)
    canvas.text(1746, 783, f"Bull {tally['BULL']}  ·  Neutral {tally['NEUTRAL']}  ·  Bear {tally['BEAR']}", 19, TEXT, True, align="right")
    cell = (1692 - 6 * 12) / 7
    colors = {"BULL": POSITIVE, "BEAR": NEGATIVE, "NEUTRAL": NEUTRAL}
    for index, (label, value, note, state) in enumerate(derived["checklist"]):
        x0 = 54 + index * (cell + 12)
        _card(canvas, (x0, 812, x0 + cell, 932))
        canvas.draw.rectangle((x0 + 6, 812, x0 + cell - 6, 815), fill=colors[state])
        canvas.text(x0 + 14, 826, label, 14, MUTED, True, max_width=cell - 28)
        canvas.text(x0 + 14, 846, value, 26, TEXT, True, max_width=cell - 28)
        canvas.text(x0 + 14, 880, note, 13, MUTED, max_width=cell - 28, minimum=11)
        canvas.text(x0 + 14, 899, state, 14, colors[state], True)
        canvas.text(x0 + 14, 917, RULES.get(label, ""), 11, SOFT, max_width=cell - 28, minimum=10)

    # Supply & sentiment.
    canvas.text(54, 952, "BITCOIN SUPPLY & SENTIMENT", 21, TEXT, True)
    canvas.text(1746, 955, "Latest readings · daily observations", 17, MUTED, align="right")
    supply = panel.get("supply_loss") or {}
    sentiment = panel.get("sentiment") or {}
    box = (54, 984, 891, 1240)
    _card(canvas, box)
    canvas.text(76, 998, "SUPPLY IN PROFIT / LOSS", 18, MUTED, True)
    canvas.text(871, 1000, "4 YEARS", 15, MUTED, True, align="right")
    canvas.text(76, 1024, _pct(supply.get("profit_pct"), 1) + " in profit", 30, ORANGE, True)
    canvas.text(460, 1024, _pct(supply.get("value"), 1) + " in loss", 30, NEGATIVE, True)
    rows = display_rows(supply.get("series"), panel.get("chart_cutoff") or period.get("end"), 4)
    plot = (110, 1072, 866, 1186)
    if len(rows) > 2:
        start, end = _ordinal(rows[0]["date"]), _ordinal(rows[-1]["date"])
        x0, y0, x1, y1 = plot
        y40, y50 = y1 - .40 * (y1 - y0), y1 - .50 * (y1 - y0)
        canvas.draw.rectangle((x0, y50, x1, y40), fill=mix(POSITIVE, CARD, .10))
        _axis(canvas, plot, 0, 100, start, end, lambda v: f"{v:.0f}")
        canvas.line([(x0, y50), (x1, y50)], SOFT, 1, dashed=True, dash=(4, 4))
        _plot(canvas, plot, [{"points": [(r["date"], r.get("profit_pct")) for r in rows], "color": ORANGE, "width": 2},
                             {"points": [(r["date"], r.get("value")) for r in rows], "color": NEGATIVE, "width": 2}], 0, 100, start, end)
        cross = None
        for previous, current in zip(rows, rows[1:]):
            if (number(previous.get("profit_pct")) or 0) <= (number(previous.get("value")) or 0) and \
               (number(current.get("profit_pct")) or 0) > (number(current.get("value")) or 0):
                cross = current["date"]
        if cross:
            x = x0 + (_ordinal(cross) - start) / max(1, end - start) * (x1 - x0)
            canvas.line([(x, y0), (x, y1)], TEXT, 1, dashed=True, dash=(3, 4))
            label = f"profit > loss since {_short(cross)}"
            canvas.text(x - 6 if x > x1 - 190 else x + 6, y0 + 2, label, 13, TEXT, align="right" if x > x1 - 190 else "left")
    canvas.text(76, 1216, "% of circulating BTC · shaded 40–50% = past bottom zone · Checkonchain · last-moved price as cost basis", 14, MUTED, max_width=790)

    box = (909, 984, 1746, 1240)
    _card(canvas, box)
    canvas.text(931, 998, "FEAR & GREED", 18, MUTED, True)
    canvas.text(1726, 1000, "FROM JUL 2023", 15, MUTED, True, align="right")
    value = number(sentiment.get("value"))
    canvas.text(931, 1024, f"{value:.0f} / 100" if value is not None else "—", 30, TEXT, True)
    label, color, days = derived["regime"]
    if label:
        weeks = days // 7
        held = f"{label} · {weeks} wk" if weeks else f"{label} · {days} d"
        canvas.pill(1110, 1026, held, 17, color, mix(color, CARD, .18))
    delta = sentiment.get("change")
    canvas.text(1726, 1030, f"{delta:+.1f} pts WoW" if delta is not None else "", 19, MUTED, align="right")
    smooth = display_rows(smooth_sentiment(sentiment.get("series") or [], window=3), panel.get("chart_cutoff") or period.get("end"),
                          start="2023-07-01")
    plot = (966, 1072, 1721, 1186)
    if len(smooth) > 2:
        start, end = _ordinal(smooth[0]["date"]), _ordinal(smooth[-1]["date"])
        x0, y0, x1, y1 = plot
        for band in SENTIMENT_BANDS:
            canvas.draw.rectangle((x0, y1 - band["upper"] / 100 * (y1 - y0), x1, y1 - band["lower"] / 100 * (y1 - y0)),
                                  fill=mix(band["color"], CARD, .08))
        _axis(canvas, plot, 0, 100, start, end, lambda v: f"{v:.0f}")
        span = max(1, end - start)
        points = [(x0 + (_ordinal(r["date"]) - start) / span * (x1 - x0), y1 - r["smoothed_value"] / 100 * (y1 - y0), r["smoothed_value"]) for r in smooth]
        for (ax, ay, av), (bx, by, _) in zip(points, points[1:]):
            band = next((b for b in SENTIMENT_BANDS if av < b["upper"]), SENTIMENT_BANDS[-1])
            canvas.draw.line((ax, ay, bx, by), fill=band["color"], width=2)
    canvas.text(931, 1216, "3-day average · CoinMarketCap · regime = current band of the 3-day average", 14, MUTED, max_width=790)

    # Price vs moving averages.
    canvas.text(54, 1260, "PRICE VS MOVING AVERAGES", 21, TEXT, True)
    canvas.text(1746, 1263, "BTC zones = distance above the 200W SMA · equities 200D with +50% / +100% guides", 17, MUTED, align="right")
    box = (54, 1292, 1150, 1730)
    _card(canvas, box)
    canvas.text(76, 1306, "BTC · 200W SMA ZONES", 20, TEXT, True)
    canvas.text(1128, 1306, f"{_pct(derived['extension'], 1, True)} vs 200W", 22, TEXT, True, align="right")
    legend = [("BTC Fri close", TEXT, False), ("200W SMA", ORANGE, True), ("50W SMA", BLUE, False),
              ("20W SMA", BAND, False), ("21W EMA", BAND, True), ("Realized price", VIOLET, True)]
    lx = 76
    for name, color, dashed in legend:
        canvas.line([(lx, 1348), (lx + 26, 1348)], color, 3, dashed=dashed, dash=(6, 4))
        lx = canvas.text(lx + 32, 1339, name, 15, color) + 20
    _btc_chart(canvas, (136, 1376, 1040, 1686), panel, derived)
    canvas.text(76, 1706, "Weekly = Friday closes · zone names after Crypto Currently; thresholds 0 / +50 / +100 / +150%", 14, MUTED, max_width=1050)
    for index, ticker in enumerate(("MSTR", "ASST")):
        y0 = 1292 + index * 225
        box = (1168, y0, 1746, y0 + 213)
        _card(canvas, box)
        trend = (panel.get("trends") or {}).get(ticker) or {}
        metric = ((trend.get("averages") or {}).get("200D") or {})
        canvas.text(1188, y0 + 12, f"{ticker} · 200D SMA", 19, TEXT, True)
        canvas.text(1726, y0 + 12, _pct(metric.get("extension_pct"), 1, True), 21, TEXT, True, align="right")
        canvas.text(1726, y0 + 38, "From Jan 1" if ticker == "ASST" else "1 year", 14, MUTED, align="right")
        _equity_chart(canvas, (1236, y0 + 58, 1716, y0 + 180), panel, ticker, derived)

    canvas.text(54, 1748, "Estimated basic treasury NAV · Monday balances held fixed · checklist BULL/BEAR are rule-based states, "
                "not forecasts · — = unavailable", 16, MUTED, max_width=1692)
    sources = "Yahoo Finance · CoinMarketCap · Checkonchain · FRED (DFF, DGS2) · strategy.com"
    if stale:
        sources += " · saved snapshot used for: " + ", ".join(stale)
    canvas.text(54, 1772, sources, 15, SOFT, max_width=1692)
    png = canvas.save(metadata={"Title": "The Closing Mark", "financial_week_end": period.get("end", "")})
    return png, canvas.overflows


def audit_rows(panel: dict, derived: dict) -> list[dict]:
    btc = (panel.get("header") or {}).get("btc") or {}
    macro = derived["macro"]
    rows = [
        {"metric": "Week ended", "value": str((panel.get("period") or {}).get("end")), "source": "exchange calendar"},
        {"metric": "BTC Friday 4 pm mark", "value": _money(btc.get("price")), "source": "Yahoo BTC-USD hourly"},
        {"metric": "BTC weekly change", "value": _pct(btc.get("weekly_return_pct"), 2, True), "source": "derived"},
        {"metric": "BTC vs 200W SMA", "value": f"{_pct(derived['extension'], 1, True)} ({derived['zone']})", "source": "derived"},
        {"metric": "50W SMA", "value": _money(derived["sma50w"]), "source": "Friday closes"},
        {"metric": "20W SMA / 21W EMA", "value": f"{_money(derived['sma20w'])} / {_money(derived['ema21w'])}", "source": "Friday closes"},
        {"metric": "Weekly RSI(14)", "value": f"{derived['rsi']:.1f}" if derived["rsi"] is not None else "—", "source": "Friday closes"},
        {"metric": "DXY", "value": f"{macro['dxy'][-1][1]:.2f}" if macro["dxy"] else "—", "source": "Yahoo DX-Y.NYB"},
        {"metric": "US 10Y", "value": f"{macro['tnx'][-1][1]:.2f}%" if macro["tnx"] else "—", "source": "Yahoo ^TNX"},
        {"metric": "Fed funds − 2Y", "value": f"{macro['gap'][-1][1] * 100:+.0f} bp" if macro["gap"] else "—", "source": "FRED DFF, DGS2"},
        {"metric": "Fear & Greed", "value": str((panel.get("sentiment") or {}).get("value")), "source": "CoinMarketCap"},
    ]
    for label, value, note, state in derived["checklist"]:
        rows.append({"metric": f"Checklist · {label}", "value": f"{value} ({state})", "source": f"{note} · rule: {RULES.get(label, '')}"})
    for company in ("MSTR", "ASST"):
        item = ((panel.get("header") or {}).get("companies") or {}).get(company) or {}
        rows.append({"metric": f"{company} price / NAV", "value": f"{item.get('nav_multiple'):.2f}x" if item.get("nav_multiple") else "—", "source": "derived"})
    return rows
