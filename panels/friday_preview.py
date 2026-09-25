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
from .draw import T_BIG, T_BODY, T_LABEL, T_MIN, T_VALUE, Canvas, fontset, imprint, mix, sparkline, width
from .extras import fred_latest, number

ET = ZoneInfo("America/New_York")
WIDTH, HEIGHT = 1440, 1920
BG, CARD, TEXT, MUTED, SOFT = "#0b0d0f", "#15191d", "#f5f3ed", "#9aa4ad", "#6f7a83"
LINE, ORANGE, POSITIVE, NEGATIVE, NEUTRAL = "#30363c", "#e88029", "#8cdbb5", "#f5a09b", "#d9c86a"
BLUE, VIOLET, BAND = "#7fb2ff", "#c39bff", "#56c4a0"
TITLE = ("The ", "Closing", " Mark")
THEME = themes.CLASSIC
# Rendering swaps the module palette for the requested theme; the lock keeps
# concurrent Streamlit sessions from drawing with each other's colors.
_LOCK = threading.RLock()
# How each checklist reading maps to a state (anything else is NEUTRAL).
CHECK_LABELS = {"50W SMA": "50W SMA", "20W / 21W BAND": "20W / 21W band", "50D / 200D": "50D / 200D",
                "WEEKLY RSI": "Weekly RSI", "MVRV": "MVRV", "PUELL MULTIPLE": "Puell Multiple",
                "SUPPLY IN PROFIT": "Supply in profit"}
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


def _card(canvas, box, accent=None, accent_height=4):
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
    # The level that decides each state, shown beside the reading.
    thresholds = {
        "50W SMA": f"50W ${sma50w / 1e3:,.1f}k" if sma50w else "",
        "20W / 21W BAND": f"${band_low / 1e3:,.1f}k–${band_high / 1e3:,.1f}k" if band_low else "",
        "50D / 200D": f"since {_short(btc_cross_since)}" if btc_cross_since else "",
        "WEEKLY RSI": "bull ≥ 50",
        "MVRV": f"bull < 1 · bear > {plus1:.2f}" if plus1 else "bull < 1",
        "PUELL MULTIPLE": f"bull < {low:.2f} · bear > {high:.2f}" if low and high else "",
        "SUPPLY IN PROFIT": "bull < 50% · bear > 95%",
    }

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
            "checklist": checklist, "tally": tally, "thresholds": thresholds, "turnover": turnover, "shares": shares, "buyback": buyback,
            "regime": (label, color, days), "macro": macro, "markets": _markets(extras)}


def _markets(extras):
    """Test copy: BTC implied volatility, 3-month futures basis and stablecoin supply, with weekly changes."""
    markets = extras.get("markets") or {}

    def latest_and_week(rows):
        rows = [(day, value) for day, value in rows or [] if value is not None]
        if not rows:
            return None, None, None
        last_day = date.fromisoformat(rows[-1][0])
        prior = next((value for day, value in reversed(rows) if date.fromisoformat(day) <= last_day - timedelta(days=7)), None)
        return rows[-1][1], rows[-1][1] - prior if prior is not None else None, rows[-1][0]

    dvol, dvol_change, dvol_day = latest_and_week(markets.get("dvol"))
    supply, supply_change, supply_day = latest_and_week(markets.get("stablecoins_usd"))
    basis = markets.get("basis") or {}
    return {"dvol": dvol, "dvol_change": dvol_change, "dvol_day": dvol_day,
            "basis": basis.get("annualized_pct"), "basis_instrument": basis.get("instrument"), "basis_days": basis.get("days"),
            "stablecoins": supply, "stablecoins_change": supply_change, "stablecoins_day": supply_day,
            "as_of": markets.get("as_of")}


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
        canvas.text(x0 - 12, y - 15, fmt(low + (high - low) * fraction), T_MIN, MUTED, align="right")
    first, last = date.fromordinal(start), date.fromordinal(end)
    canvas.text(x0, y1 + 10, f"{first:%b %Y}", T_MIN, MUTED)
    canvas.text(x1, y1 + 10, f"{last:%b %Y}", T_MIN, MUTED, align="right")


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
            if y0 + 14 < y < y1 - 14:
                canvas.text(x1 + 14, y - 15, name.title(), T_MIN, mix(color, TEXT, .55), True, max_width=210)
    series = [
        {"points": [(row["date"], row.get("sma_200w")) for row in rows], "color": ORANGE, "width": 4, "dashed": True},
        {"points": [(day, value) for day, value in derived["realized"]], "color": VIOLET, "width": 3, "dashed": True, "dash": (5, 5)},
        {"points": derived["sma50w_series"], "color": BLUE, "width": 3},
        {"points": derived["sma20w_series"], "color": BAND, "width": 3},
        {"points": derived["ema21w_series"], "color": BAND, "width": 3, "dashed": True, "dash": (6, 4)},
        {"points": [(row["date"], row["close"]) for row in rows], "color": TEXT, "width": 4},
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
def render_png(panel: dict, derived: dict, *, stale: tuple = (), theme: themes.Theme = themes.DEFAULT,
               extra: bool = False) -> tuple[bytes, list[str]]:
    """``extra`` renders the test copy with a markets band (DVOL, basis, stablecoins)."""
    with _LOCK, fontset(theme.fontset):
        _use(theme)
        try:
            return _render(panel, derived, stale, extra)
        finally:
            _use(themes.CLASSIC)


def _render(panel: dict, derived: dict, stale: tuple, extra: bool = False) -> tuple[bytes, list[str]]:
    """Portrait, phone-first (see draw.T_*). Tiles, macro, checklist, BTC zones, liquidity."""
    canvas = Canvas((WIDTH, HEIGHT), BG, floor=T_MIN)
    draw = canvas.draw
    M = 40
    period, header = panel.get("period") or {}, panel.get("header") or {}
    week_end = period.get("week_ending", period.get("end"))
    if THEME.key == "classic":
        draw.rectangle((0, 0, WIDTH, 8), fill=ORANGE)
    else:
        themes.background(canvas, THEME.friday, THEME, header_height=226, orbit_at=(1120, 104, .55))
    canvas.text(M, 34, "DIGITAL CREDIT REPORT · FRIDAY", T_MIN, ORANGE, True)
    canvas.text(WIDTH - M, 34, "MARKED FRI 4:00 PM ET", T_MIN, ORANGE, True, align="right")
    if THEME.key == "classic":
        imprint(canvas, M, 146, TITLE, 76, ink=TEXT, muted="#aab3ba", dot=ORANGE)
    else:
        themes.title(canvas, M, 146, TITLE, 76, THEME.friday, THEME, on_space=THEME.decor == "orbit")
    if week_end:
        canvas.text(M, 170, f"Week of {_short(period.get('start'))}–{_short(week_end)}, "
                    f"{date.fromisoformat(str(week_end)[:10]).year}", T_BODY, TEXT, True)

    # Row 1: bitcoin and the two treasuries' premiums.
    third = (WIDTH - 2 * M - 2 * 24) / 3
    top = 226
    boxes = [(M + n * (third + 24), top, M + n * (third + 24) + third, top + 232) for n in range(3)]
    btc = header.get("btc") or {}
    x0, _, x1, _ = boxes[0]
    _card(canvas, boxes[0], ORANGE, 5)
    canvas.text(x0 + 24, top + 22, "BITCOIN", T_MIN, MUTED, True)
    canvas.text(x0 + 24, top + 58, _money(btc.get("price")), T_BIG, TEXT, True, max_width=third - 48)
    change = btc.get("weekly_return_pct")
    canvas.text(x0 + 24, top + 134, _pct(change, 2, True) + " week", T_BODY, _tone(change), True)
    if derived["zone"]:
        canvas.pill(x0 + 24, top + 178, f"{derived['zone']} · {_pct(derived['extension'], 0, True)} vs 200W", T_MIN,
                    TEXT, mix(derived["zone_color"], CARD, .8), pad=(12, 4))
    companies = header.get("companies") or {}
    treasury = {row.get("ticker"): row for row in panel.get("treasury", [])}
    for ticker, box in zip(("MSTR", "ASST"), boxes[1:]):
        x0, _, x1, _ = box
        company, base = companies.get(ticker) or {}, treasury.get(ticker) or {}
        color = THEME.friday.company(ticker)
        _card(canvas, box, color, 5)
        canvas.text(x0 + 24, top + 22, f"{ticker} · PRICE / NAV", T_MIN, MUTED, True)
        multiple = company.get("nav_multiple")
        canvas.text(x0 + 24, top + 58, f"{multiple:.2f}×" if multiple else "—", T_BIG, TEXT, True)
        delta = company.get("nav_multiple_change")
        canvas.text(x1 - 24, top + 80, f"{delta:+.2f}× wk" if delta is not None else "—", T_BODY, _tone(delta), True, align="right")
        canvas.text(x0 + 24, top + 136, f"NAV/sh {_money(company.get('nav_per_share'), 2)}", T_LABEL, TEXT, max_width=third - 48)
        trend = (panel.get("trends") or {}).get(ticker) or {}
        ext = (((trend.get("averages") or {}).get("200D") or {}).get("extension_pct"))
        canvas.text(x0 + 24, top + 180, f"{_pct(ext, 1, True)} vs 200D", T_LABEL, _tone(ext), True, max_width=third - 48)

    # Row 2: the macro strip, each chart marked with its range, dates and reference.
    macro = derived["macro"]
    top = 476
    strip = (
        ("US DOLLAR INDEX", macro["dxy"], lambda v: f"{v:.1f}", f"{macro['dxy'][-1][1]:.2f}" if macro["dxy"] else "—",
         macro["dxy_change"], lambda v: _minus(f"{v:+.2f}"), 101.0, "101"),
        ("US 10-YEAR", macro["tnx"], lambda v: f"{v:.2f}%", f"{macro['tnx'][-1][1]:.2f}%" if macro["tnx"] else "—",
         macro["tnx_change"], lambda v: _minus(f"{v * 100:+.0f} bp"), None, None),
        ("FED FUNDS − 2Y", macro["gap"], lambda v: _minus(f"{v * 100:+.0f}"), _minus(f"{macro['gap'][-1][1] * 100:+.0f} bp") if macro["gap"] else "—",
         macro["gap_change"], lambda v: _minus(f"{v * 100:+.0f} bp"), 0.0, "0"),
    )
    for n, (label, rows, fmt, value, change, change_fmt, reference, ref_label) in enumerate(strip):
        x0 = M + n * (third + 24)
        box = (x0, top, x0 + third, top + 244)
        _card(canvas, box)
        canvas.text(x0 + 24, top + 20, label, T_MIN, MUTED, True, max_width=third - 48)
        canvas.text(x0 + 24, top + 56, value, T_VALUE, TEXT, True)
        if change is not None:
            canvas.text(x0 + third - 24, top + 64, f"{change_fmt(change)} wk", T_MIN, MUTED, True, align="right")
        _marked_chart(canvas, (x0 + 24, top + 114, x0 + third - 24, top + 230), rows, fmt, reference, ref_label)

    # Row 3: the cycle checklist, one reading per line.
    top = 740
    tally = derived["tally"]
    canvas.text(M, top, "CYCLE CHECKLIST", T_LABEL, TEXT, True)
    colors = {"BULL": POSITIVE, "BEAR": NEGATIVE, "NEUTRAL": NEUTRAL}
    x = WIDTH - M
    for state in ("BEAR", "NEUTRAL", "BULL"):
        x = canvas.pill(x, top - 4, f"{state} {tally[state]}", T_MIN, BG, colors[state], align="right", pad=(12, 4)) - 12
    row = 48 if extra else 54  # the test copy tightens rows to make room for its markets band
    box = (M, top + 48, WIDTH - M, top + 48 + 7 * row + 22)
    _card(canvas, box)
    for index, (label, value, note, state) in enumerate(derived["checklist"]):
        y = top + 62 + index * row
        if index:
            draw.line((M + 24, y - 8, WIDTH - M - 24, y - 8), fill=LINE, width=1)
        canvas.text(M + 28, y + 4, CHECK_LABELS.get(label, label), T_BODY, TEXT, True, max_width=360)
        canvas.text(M + 400, y + 4, value, T_BODY, TEXT, True, max_width=280)
        canvas.text(M + 700, y + 8, derived.get("thresholds", {}).get(label, ""), T_MIN, MUTED, max_width=390)
        canvas.pill(WIDTH - M - 28, y, state, T_MIN, BG, colors[state], align="right", pad=(14, 4))

    # Row 4: BTC against the 200-week SMA zones.
    top = box[3] + 20
    chart_box = (M, top, WIDTH - M, top + (360 if extra else 440))
    _card(canvas, chart_box)
    canvas.text(M + 28, top + 20, "BTC · 200W SMA ZONES", T_LABEL, TEXT, True)
    canvas.text(WIDTH - M - 28, top + 20, f"{_pct(derived['extension'], 1, True)} vs 200W", T_LABEL, TEXT, True, align="right")
    legend = [("BTC", TEXT, False), ("200W", ORANGE, True), ("50W", BLUE, False), ("20W", BAND, False),
              ("21W EMA", BAND, True), ("Realized", VIOLET, True)]
    lx = M + 28
    for name, color, dashed in legend:
        canvas.line([(lx, top + 82), (lx + 34, top + 82)], color, 4, dashed=dashed, dash=(7, 5))
        lx = canvas.text(lx + 42, top + 66, name, T_MIN, color, True) + 26
    _btc_chart(canvas, (M + 116, top + 118, WIDTH - M - 230, chart_box[3] - 54), panel, derived)
    if extra:
        top = chart_box[3] + 16
        _markets_band(canvas, (M, top, WIDTH - M, top + 104), derived["markets"])
        chart_box = (M, top, WIDTH - M, top + 104)

    # Row 5: weekly turnover and sentiment.
    top = chart_box[3] + 16
    canvas.text(M, top, "WEEKLY TURNOVER · SHARES TRADED ÷ OUTSTANDING", T_MIN, MUTED, True)
    top += 42
    fifth = (WIDTH - 2 * M - 4 * 18) / 5
    for n, ticker in enumerate(("MSTR", "ASST", "STRC", "SATA")):
        x0 = M + n * (fifth + 18)
        weeks = derived["turnover"].get(ticker) or []
        latest = weeks[-1]["pct"] if weeks else None
        _card(canvas, (x0, top, x0 + fifth, top + 196), THEME.friday.company(ticker), 5)
        canvas.text(x0 + 20, top + 18, ticker, T_MIN, MUTED, True, max_width=fifth - 40)
        canvas.text(x0 + 20, top + 52, f"{latest:.1f}%" if latest is not None else "—", T_VALUE, TEXT, True)
        values = [week["pct"] for week in weeks[-12:]]
        top_value = max([v for v in values if v is not None] or [1])
        bar = (fifth - 40) / 12
        base = top + 172
        draw.line((x0 + 20, base, x0 + fifth - 20, base), fill=LINE, width=2)
        for j, value in enumerate(values):
            if value is None:
                continue
            h = value / top_value * 56
            bx = x0 + 20 + j * bar
            draw.rectangle((bx + 2, base - h, bx + bar - 2, base), fill=THEME.friday.company(ticker) if j == len(values) - 1
                           else mix(THEME.friday.company(ticker), CARD, .45))
        canvas.text(x0 + fifth - 20, top + 64, "/wk", T_MIN, MUTED, align="right")
    x0 = M + 4 * (fifth + 18)
    sentiment = panel.get("sentiment") or {}
    label, color, days = derived["regime"]
    _card(canvas, (x0, top, x0 + fifth, top + 196), color or MUTED, 5)
    canvas.text(x0 + 20, top + 18, "FEAR & GREED", T_MIN, MUTED, True, max_width=fifth - 40)
    value = sentiment.get("value")
    canvas.text(x0 + 20, top + 52, f"{value:.0f}" if isinstance(value, (int, float)) else "—", T_VALUE, TEXT, True)
    if label:
        weeks_held = max(1, round((days or 0) / 7))
        canvas.text(x0 + 20, top + 106, f"{label} · {weeks_held} wk", T_MIN, color or MUTED, True, max_width=fifth - 40)
    if isinstance(value, (int, float)):
        gx0, gx1, gy = x0 + 20, x0 + fifth - 20, top + 160
        draw.rounded_rectangle((gx0, gy, gx1, gy + 10), radius=5, fill=LINE)
        gx = gx0 + value / 100 * (gx1 - gx0)
        canvas.dot(gx, gy + 5, 10, TEXT)

    png = canvas.save(metadata={"Title": "The Closing Mark", "Theme": THEME.key, "financial_week_end": period.get("end", "")})
    return png, canvas.overflows


def _markets_band(canvas, box, markets):
    """Test copy: one row of market-structure readings with their weekly change."""
    x0, y0, x1, _ = box
    _card(canvas, box)
    cells = (("BTC IMPLIED VOL · DVOL", f"{markets['dvol']:.1f}" if markets.get("dvol") is not None else "—",
              _minus(f"{markets['dvol_change']:+.1f} wk") if markets.get("dvol_change") is not None else ""),
             ("3M FUTURES BASIS", _pct(markets.get("basis"), 1), "annualized"),
             ("STABLECOIN SUPPLY", f"${markets['stablecoins'] / 1e9:,.1f}B" if markets.get("stablecoins") else "—",
              _minus(f"{markets['stablecoins_change'] / 1e9:+.1f}B wk") if markets.get("stablecoins_change") is not None else ""))
    cell = (x1 - x0 - 48) / 3
    for n, (label, value, note) in enumerate(cells):
        cx = x0 + 24 + n * cell
        canvas.text(cx, y0 + 14, label, T_MIN, MUTED, True, max_width=cell - 16)
        end = canvas.text(cx, y0 + 50, value, T_VALUE, TEXT, True, max_width=cell * .55)
        if note:
            canvas.text(end + 14, y0 + 62, note, T_MIN, MUTED, True, max_width=cx + cell - end - 30)


def _minus(text: str) -> str:
    return text.replace("-", "−")


def _marked_chart(canvas, box, rows, fmt, reference=None, ref_label=None):
    """A small line chart with its range labeled, start/end dates and a reference line."""
    x0, y0, x1, y1 = box
    rows = [(day, value) for day, value in rows if value is not None]
    if len(rows) < 3:
        canvas.text(x0, y0 + 20, "History unavailable", T_MIN, MUTED)
        return
    values = [value for _, value in rows]
    low, high = min(values), max(values)
    if reference is not None and low - (high - low) * .6 <= reference <= high + (high - low) * .6:
        low, high = min(low, reference), max(high, reference)
    pad = (high - low) * .08 or .5
    low, high = low - pad, high + pad
    plot = (x0, y0, x1 - 96, y1 - 38)
    px = lambda i: plot[0] + i / (len(rows) - 1) * (plot[2] - plot[0])
    py = lambda v: plot[3] - (v - low) / (high - low) * (plot[3] - plot[1])
    # Frame: range labels on the right edge, dates below.
    top_value, bottom_value = max(values), min(values)
    for value in (top_value, bottom_value):
        canvas.line([(plot[0], py(value)), (plot[2], py(value))], LINE, 1, dashed=True, dash=(3, 5))
        canvas.text(plot[2] + 8, py(value) - 15, fmt(value), T_MIN, MUTED)
    if reference is not None and low <= reference <= high:
        canvas.line([(plot[0], py(reference)), (plot[2], py(reference))], ORANGE, 2, dashed=True, dash=(8, 5))
        ry = py(reference)
        # Label the reference at the left, above or below the line, clear of the data's start.
        above = rows[0][1] < reference
        canvas.text(plot[0], ry - 34 if above else ry + 4, ref_label, T_MIN, ORANGE, True)
    canvas.draw.line((plot[0], plot[3], plot[2], plot[3]), fill=LINE, width=2)
    points = [(px(i), py(v)) for i, (_, v) in enumerate(rows)]
    canvas.line(points, ORANGE if THEME.key == "classic" else TEXT, 3)
    canvas.dot(*points[-1], 6, ORANGE)
    canvas.text(plot[0], plot[3] + 6, _short(rows[0][0]), T_MIN, MUTED)
    canvas.text(plot[2], plot[3] + 6, _short(rows[-1][0]), T_MIN, MUTED, align="right")


def notes(panel: dict, derived: dict, stale: tuple = (), extra: bool = False) -> list[str]:
    """Footnotes for the web page; the X image carries none."""
    b = derived.get("buyback")
    m = derived.get("markets") or {}
    stale = tuple(section for section in stale if extra or section != "markets")  # markets feeds the test copy only
    rules = "; ".join(f"{label}: {rule}" for label, rule in RULES.items())
    return [line for line in (
        "Every weekly reading is taken at the Friday 4:00 pm ET mark. Price/NAV uses estimated basic treasury NAV with "
        "Monday balances held fixed.",
        f"Cycle checklist rules (rule-based states, not forecasts): {rules}.",
        "Zones = BTC's distance above its 200-week SMA: below 0 Very Cheap, 0–50% Cheap, 50–100% Fair Value, "
        "100–150% Expensive, 150%+ Very Expensive (names after Crypto Currently).",
        "Turnover = weekly shares traded ÷ basic shares (preferreds: notional ÷ $100)."
        + (f" Strategy repurchased {b['shares'] / 1e6:.2f}m STRC = {b['pct']:.0f}% of STRC volume in the "
           f"{_short(b['start'])}–{_short(b['end'])} filing week." if b else ""),
        "Fear & Greed: CoinMarketCap 3-day average; the regime is its current band.",
        "Sources: Yahoo Finance · CoinMarketCap · Checkonchain · FRED (DFF, DGS2) · strategy.com.",
        (f"Test copy: DVOL = Deribit's 30-day BTC implied volatility index (daily close {_short(m.get('dvol_day'))}). "
         f"3M futures basis = the {m.get('basis_instrument') or 'nearest-quarter'} future's premium over the BTC index, "
         f"annualized ({m.get('basis_days') or '—'} days to expiry; Deribit). Stablecoin supply = USD-pegged stablecoins "
         f"in circulation (DefiLlama, {_short(m.get('stablecoins_day'))}). Changes are over 7 days. These are live "
         "readings, not Friday 4:00 pm marks.") if extra else "",
        "Saved snapshot used for: " + ", ".join(stale) + "." if stale else "",
    ) if line]


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
    m = derived.get("markets") or {}
    rows += [
        {"metric": "Test copy · BTC DVOL", "value": f"{m['dvol']:.2f} ({m.get('dvol_day')})" if m.get("dvol") is not None else "—",
         "source": "Deribit get_volatility_index_data"},
        {"metric": "Test copy · 3M futures basis (annualized)", "value": _pct(m.get("basis"), 2),
         "source": f"Deribit {m.get('basis_instrument') or '—'} mark ÷ index"},
        {"metric": "Test copy · stablecoin supply", "value": f"${m['stablecoins'] / 1e9:,.2f}B ({m.get('stablecoins_day')})" if m.get("stablecoins") else "—",
         "source": "DefiLlama stablecoincharts/all (peggedUSD)"},
    ]
    return rows
