"""Monday: "The Accretion Ledger." built on the live Monday report.

All base values (NAV, capital, shares, sats, growth) come unchanged from the
production ``ReportView``. This module adds USD/dividend coverage read against
each company's own target, a clear split between capital raised through the
ATMs and cash drawn from (or added to) balances, amplification ((debt +
preferred) ÷ BTC), a same-window multi-week growth column for both companies
and Strive's warrant tag. The funding block has three layouts (``VARIANTS``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from report import live_report as lr
from report.calculations import btc_value, calculate_company, liquid_assets, net_treasury_nav
from report.models import Report
from report.presentation import build_report_view
from report.view_types import CompanyView, ReportView

from .draw import T_BIG, T_BODY, T_HERO, T_LABEL, T_MIN, T_VALUE, Canvas, fontset, mix, width
from . import themes

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "preview-config.json"
ET = ZoneInfo("America/New_York")

WIDTH, HEIGHT = 1440, 1800
MARGIN, GAP = 40, 24
PANEL = (WIDTH - 2 * MARGIN - GAP) // 2
INSET = 30
CARD_TOP = 236
TITLE = ("The ", "Accretion", " Ledger")


@dataclass(frozen=True)
class CompanyExtras:
    ticker: str
    amplification_pct: float | None = None
    amplification_change_pp: float | None = None
    preferred_pct: float | None = None
    debt_pct: float | None = None
    net_leverage_pct: float | None = None
    raised: float | None = None
    common_capital: float | None = None
    preferred_capital: float | None = None
    preferred_note: str = ""
    btc_bought: float | None = None
    btc_held: float | None = None
    liquid_balance: float | None = None
    liquid_change: float | None = None
    liquid_detail: str = ""
    net_funding: float | None = None
    reserve_months: float | None = None
    target_months: float | None = None
    target_kind: str = ""
    coverage_years: float | None = None
    breakeven_pct: float | None = None
    coverage_source: str = ""
    window: dict = field(default_factory=dict)
    warrants: dict | None = None


@dataclass(frozen=True)
class MondayPreview:
    report: Report
    view: ReportView
    extras: dict
    kicker: str
    subtitle: str
    notes: tuple = field(default_factory=tuple)
    period: str = ""


def _n(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _money(value, signed=True, digits=1):
    if value is None:
        return "—"
    sign = "−" if value < 0 else "+" if signed and value > 0 else ""
    amount = abs(value)
    if amount >= 1e9:
        return f"{sign}${amount / 1e9:,.2f}B"
    return f"{sign}${amount / 1e6:,.{digits}f}m"


def _pct(value, digits=1, signed=False, suffix="%"):
    if value is None:
        return "—"
    sign = "−" if round(value, digits) < 0 else "+" if signed and round(value, digits) > 0 else ""
    return f"{sign}{abs(value):,.{digits}f}{suffix}"


def _short(day):
    parsed = date.fromisoformat(day) if isinstance(day, str) else day
    return f"{parsed:%b} {parsed.day}"


def _clean(value: str) -> str:
    return value.replace("≈", "")


def _facts(rows, ticker, balance):
    matches = [row for row in rows if row["ticker"] == ticker and row["extracted"]["balanceDate"] == balance]
    return matches[-1]["extracted"]["facts"] if matches else {}


def _weekly_snapshots(rows, supplements, prices, ticker, through):
    """Complete dated balances at today's marks, newest last."""
    out = {}
    for row in sorted(rows, key=lambda item: item.get("acceptedAt", "")):
        extraction = row["extracted"]
        if row["ticker"] != ticker or extraction["balanceDate"] > through:
            continue
        snapshot = lr._snapshot(ticker, extraction["balanceDate"], extraction["facts"], supplements, prices)
        if lr._complete(snapshot):
            out[extraction["balanceDate"]] = snapshot
    return sorted(out.items())


def _windows(report, rows, supplements, prices):
    """Same number of weekly filings back for both companies (up to four)."""
    series = {c.ticker: _weekly_snapshots(rows, supplements, prices, c.ticker, c.balance_date) for c in report.companies}
    weeks = min(min(len(points) - 1 for points in series.values()), 4) if series else 0
    result = {}
    for company in report.companies:
        points = series[company.ticker]
        if weeks < 1 or len(points) <= weeks:
            result[company.ticker] = {}
            continue
        start_day, start = points[-1 - weeks]
        current = company.current
        btc_now = current.btc_holdings / current.effective_common_shares
        btc_then = start.btc_holdings / start.effective_common_shares
        nav_now = net_treasury_nav(current, report.current_btc_price)
        nav_then = net_treasury_nav(start, report.current_btc_price)
        result[company.ticker] = {
            "weeks": weeks, "start": start_day,
            "btc": (btc_now / btc_then - 1) * 100,
            "nav": ((nav_now / current.effective_common_shares) / (nav_then / start.effective_common_shares) - 1) * 100
            if nav_now and nav_then and nav_now > 0 and nav_then > 0 else None,
        }
    return result


def _coverage(ticker, company, btc_price, extras, facts):
    bitcoin = btc_value(company.current, btc_price)
    liquid = liquid_assets(company.current)
    if ticker == "MSTR":
        kpis = (extras.get("strategy") or {}).get("btc") or {}
        annual = _n(kpis.get("totalAnnualDividends"))
        months = _n(kpis.get("usdMonthsOfDividends"))
        source = "strategy.com KPIs"
    else:
        strive = extras.get("strive") or {}
        rate = _n(strive.get("sata_rate_pct"))
        sata = _n(facts.get("sata_shares"))
        annual = sata * 100 * rate / 100 if sata and rate else None
        latest = (strive.get("cash") or [{}])[0]
        months = _n(latest.get("dividend_reserve_months"))
        source = "strive.com dashboard, SATA stated rate " + (_pct(rate) if rate else "n/a")
    years = (bitcoin + liquid) / annual if annual and bitcoin is not None and liquid is not None else None
    breakeven = annual / bitcoin * 100 if annual and bitcoin else None
    return months, years, breakeven, source


def _warrants(ticker, company, facts, config, now):
    terms = (config or {}).get("asst_warrants")
    count = _n(facts.get("traditional_warrant_shares"))
    if ticker != "ASST" or not terms or not count:
        return None
    expires = datetime.fromisoformat(terms["expires_at"])
    if now >= expires:
        return None
    strike = terms["strike_usd"]
    price = company.stock_price
    return {"count": count, "strike": strike, "proceeds": count * strike, "expires": expires,
            "in_the_money": price - strike if price else None, "days": (expires.date() - now.astimezone(ET).date()).days}


def build_preview(report: Report, prices: dict, feed: dict, extras: dict, *, now: datetime | None = None) -> MondayPreview:
    now = now or datetime.now(ET)
    view = build_report_view(report, prices=prices)
    rows = lr._merged_filings(feed, lr._load(lr.CHECKPOINT))
    supplements = lr.load_supplements(rows)
    config = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    windows = _windows(report, rows, supplements, prices)
    result = {}
    for company in report.companies:
        ticker = company.ticker
        facts = _facts(rows, ticker, company.balance_date)
        prior_facts = _facts(rows, ticker, company.prior_balance_date) if company.prior_balance_date else {}
        bitcoin = btc_value(company.current, report.current_btc_price)
        prior_bitcoin = btc_value(company.prior, report.prior_btc_price)
        current, prior = company.current, company.prior
        amp = ((current.debt_principal + current.preferred_claims) / bitcoin * 100
               if bitcoin and current.debt_principal is not None and current.preferred_claims is not None else None)
        prior_amp = ((prior.debt_principal + prior.preferred_claims) / prior_bitcoin * 100
                     if prior_bitcoin and prior.debt_principal is not None and prior.preferred_claims is not None else None)
        liquid, prior_liquid = liquid_assets(current), liquid_assets(prior)
        liquid_change = liquid - prior_liquid if liquid is not None and prior_liquid is not None else None
        if ticker == "MSTR":
            reserve, cash = _n(facts.get("usd_reserve_usd")), _n(facts.get("usd_cash_usd"))
            detail = (f"{_money(reserve, False)} reserve + {_money(cash, False)} USD cash"
                      if None not in (reserve, cash) else "USD Reserve + USD Cash")
        else:
            # Strive's liquidity includes the STRC it holds; show that portion.
            detail = f"{_money(current.cash, False)} cash + {_money(current.marketable_securities, False)} STRC"
        metrics = calculate_company(company, report.current_btc_price, report.prior_btc_price)
        raised = (metrics.net_common_capital + metrics.net_preferred_capital
                  if None not in (metrics.net_common_capital, metrics.net_preferred_capital) else None)
        funding = raised - liquid_change if raised is not None and liquid_change is not None else None
        months, years, breakeven, source = _coverage(ticker, company, report.current_btc_price, extras, facts)
        key = "strategy_reserve_floor_months" if ticker == "MSTR" else "strive_reserve_goal_months"
        target = _n((config.get(key) or {}).get("value"))
        if ticker == "MSTR":
            strc = ((next((row for row in rows if row["ticker"] == ticker and row["extracted"]["balanceDate"] == company.balance_date), {})
                     .get("extracted") or {}).get("securities") or {}).get("STRC") or {}
            bought_back = _n(strc.get("repurchasedShares"))
            note = "STRC buyback" if bought_back else "STRC · STRF · STRK · STRD"
        else:
            change = _n(facts.get("net_sata_shares_change"))
            note = f"SATA {change / 1e3:+,.0f}k sh" if change is not None else "SATA"
        result[ticker] = CompanyExtras(
            ticker=ticker, amplification_pct=amp,
            common_capital=metrics.net_common_capital, preferred_capital=metrics.net_preferred_capital,
            preferred_note=note, btc_bought=_n(facts.get("weekly_btc_purchases")), btc_held=current.btc_holdings,
            amplification_change_pp=amp - prior_amp if amp is not None and prior_amp is not None else None,
            preferred_pct=current.preferred_claims / bitcoin * 100 if bitcoin and current.preferred_claims is not None else None,
            debt_pct=current.debt_principal / bitcoin * 100 if bitcoin and current.debt_principal is not None else None,
            net_leverage_pct=(current.debt_principal - liquid) / bitcoin * 100 if bitcoin and liquid is not None and current.debt_principal is not None else None,
            raised=raised, liquid_balance=liquid, liquid_change=liquid_change, liquid_detail=detail, net_funding=funding,
            reserve_months=months, target_months=target, target_kind="floor" if ticker == "MSTR" else "goal",
            coverage_years=years, breakeven_pct=breakeven, coverage_source=source,
            window=windows.get(ticker, {}), warrants=_warrants(ticker, company, facts, config, now))
    period = report.capital_period_label.split("·")[-1].strip()
    kicker = f"THE DIGITAL CREDIT REPORT  ·  MONDAY  ·  8-K WEEK {period.upper()}"
    dates = " · ".join(f"{c.name} {_short(c.balance_date)}" for c in report.companies if c.balance_date)
    subtitle = f"What last week's filings did to each common share  ·  Balances: {dates}"
    notes = tuple(f"{t} data stale" for t in extras.get("stale", []))
    return MondayPreview(report, view, result, kicker, subtitle, notes, f"8-K week {period}")


# ── rendering ───────────────────────────────────────────────────────────────
# Portrait, phone-first: 1440 px wide so a phone shows it ~0.27× (see draw.T_*).
# Both company cards share one row grid so every figure lines up across.
VARIANTS = {"headline": "A · Headline", "ledger": "B · Ledger", "waterfall": "C · Waterfall"}
DEFAULT_VARIANT = "waterfall"
TOP_H = 372        # the variant-specific funding block
ROW_H = 76         # per-share rows


def _tone_text(text, p):
    stripped = text.replace("≈", "").strip()
    return p.positive if stripped.startswith("+") else p.negative if stripped.startswith("−") else p.ink


def _cover_note(e: CompanyExtras):
    if not e.reserve_months or not e.target_months:
        return ""
    if e.target_kind == "goal":
        gap = e.reserve_months - e.target_months
        return f"at {e.target_months:.0f}-mo goal" if abs(gap) < .5 else f"{gap:+.0f} vs {e.target_months:.0f}-mo goal"
    return f"{e.reserve_months / e.target_months:.1f}× floor"


def _btc(value, signed=False):
    if value is None:
        return "—"
    sign = "+" if signed and value > 0 else "−" if value < 0 else ""
    digits = 0 if abs(value) >= 100 or float(value).is_integer() else 2
    return f"{sign}{abs(value):,.{digits}f} BTC"


def _one_decimal(text: str) -> str:
    """"+12.08%" → "+12.1%" for the growth grid."""
    raw = _clean(text).strip()
    try:
        value = float(raw.replace("−", "-").replace("+", "").replace("%", "").replace(",", ""))
    except ValueError:
        return raw
    return _pct(value, 1, True)


def _cash_line(e: CompanyExtras):
    change = e.liquid_change
    if change is None:
        return f"Cash on hand {_money(e.liquid_balance, False)}"
    verb = "drew" if change < 0 else "added" if change > 0 else "unchanged"
    amount = f" {_money(abs(change), False)}" if change else ""
    return f"Cash {verb}{amount} · {_money(e.liquid_balance, False)} on hand"


CASH_BOX_H = 96


def _cash_box(canvas, e, L, R, y, p, headline=None):
    """The cash balance and what it is made of (Strive: cash + STRC held)."""
    canvas.draw.rounded_rectangle((L, y, R, y + CASH_BOX_H), radius=min(10, p.radius + 4), fill=p.cash)
    canvas.text(L + 18, y + 12, headline or _cash_line(e), T_LABEL, p.ink, max_width=R - L - 36)
    canvas.text(L + 18, y + 54, e.liquid_detail, T_MIN, p.muted, max_width=R - L - 36)


def _common_note(e: CompanyExtras):
    if e.ticker == "ASST":
        return "estimate"
    return "no shares sold" if not e.common_capital else "MSTR"


def _top_headline(canvas, e, L, R, y, p, stripe):
    """A · Headline: the two ATMs as big tiles, then one cash line."""
    half = (R - L - 20) / 2
    for n, (label, value, note) in enumerate((("COMMON ATM", e.common_capital, _common_note(e)),
                                             ("PREFERRED ATM", e.preferred_capital, e.preferred_note))):
        x = L + n * (half + 20)
        canvas.draw.rounded_rectangle((x, y, x + half, y + 210), radius=min(10, p.radius + 4), fill=p.tint)
        canvas.text(x + 18, y + 18, label, T_MIN, stripe, True, max_width=half - 36)
        text = _money(value)
        canvas.text(x + 18, y + 62, text, T_BIG - 4, _tone_text(text, p), True, max_width=half - 36)
        canvas.text(x + 18, y + 150, note, T_MIN, p.muted, max_width=half - 36)
    _cash_box(canvas, e, L, R, y + 236, p)


def _top_ledger(canvas, e, L, R, y, p, stripe):
    """B · Ledger: common + preferred = raised, with cash kept apart below."""
    rows = (("Common ATM", e.common_capital, _common_note(e) if e.ticker == "ASST" else ""),
            ("Preferred ATM", e.preferred_capital, e.preferred_note))
    for label, value, note in rows:
        text = _money(value)
        canvas.text(L, y, label, T_BODY, p.muted)
        if note:
            canvas.text(L, y + 42, note, T_MIN, p.soft, max_width=(R - L) * .55)
        canvas.text(R, y + 8, text, T_VALUE, _tone_text(text, p), True, align="right")
        y += 92
    canvas.draw.line((L, y - 4, R, y - 4), fill=p.line, width=2)
    text = _money(e.raised)
    canvas.text(L, y + 12, "Raised", T_BODY, p.ink, True)
    canvas.text(R, y + 6, text, T_VALUE, p.ink, True, align="right")
    _cash_box(canvas, e, L, R, y + 86, p)


def cash_step_label(e: CompanyExtras) -> str:
    """FROM CASH when the balance fell (it funded buying), TO CASH when it rose."""
    return "TO CASH" if (e.liquid_change or 0) > 0 else "FROM CASH"


def _top_waterfall(canvas, e, L, R, y, p, stripe):
    """C · Waterfall: common + preferred ± cash = what went into bitcoin.

    Cash is labeled by direction: FROM CASH when the balance funded purchases,
    TO CASH when part of the raise was kept (the bar then steps down).
    """
    drawn = -e.liquid_change if e.liquid_change is not None else None
    steps = (("COMMON", e.common_capital), ("PREF", e.preferred_capital), (cash_step_label(e), drawn))
    if any(value is None for _, value in steps):
        canvas.text(L, y + 60, "Funding detail unavailable", T_BODY, p.muted)
        return
    levels, level = [], 0.0
    for _, value in steps:
        levels.append((level, level + value))
        level += value
    points = [v for pair in levels for v in pair] + [0.0, level]
    low, high = min(points), max(points)
    span = (high - low) or 1
    top, bottom = y + 40, y + 184
    py = lambda v: bottom - (v - low) / span * (bottom - top)
    # The cash column is wider so "FROM CASH" fits at the phone minimum.
    shares = (.24, .22, .29, .25)
    edges = [L]
    for share in shares:
        edges.append(edges[-1] + share * (R - L))
    canvas.line([(L, py(0)), (R, py(0))], p.line, 2)
    bars = [(label, value, a, b, p.soft if n == 2 else p.positive if value >= 0 else p.negative)
            for n, ((label, value), (a, b)) in enumerate(zip(steps, levels))]
    bars.append(("INTO BTC", level, 0.0, level, stripe))
    for n, (label, value, a, b, color) in enumerate(bars):
        x, slot = edges[n], edges[n + 1] - edges[n]
        y0, y1 = sorted((py(a), py(b)))
        canvas.draw.rectangle((x + 14, y0, x + slot - 14, max(y1, y0 + 4)), fill=mix(color, p.card, .85))
        if n < 3:
            canvas.line([(x + slot - 14, py(b)), (x + slot + 14, py(b))], p.soft, 2, dashed=True, dash=(5, 4))
        # Raises carry their sign; cash and the total are plain amounts (the label gives direction).
        text = _money(value, signed=True) if n < 2 else _money(abs(value), signed=False)
        above = value >= 0 or n == 3
        ty = y0 - 38 if above else y1 + 6
        canvas.text(x + slot / 2, ty, text, T_MIN, _tone_text(text, p) if n < 2 else p.ink, True, align="center",
                    max_width=slot - 4)
        canvas.text(x + slot / 2, y + 230, label, T_MIN, p.muted, True, align="center", max_width=slot - 4)
    _cash_box(canvas, e, L, R, y + TOP_H - CASH_BOX_H, p, f"Cash on hand {_money(e.liquid_balance, False)}")


TOPS = {"headline": _top_headline, "ledger": _top_ledger, "waterfall": _top_waterfall}


def _logo(canvas, c, theme, p, x, y):
    if theme.key == "classic" or theme.decor == "orbit" and p.card.startswith("#F"):
        from report.png_export import _Canvas  # approved logo artwork
        host = _Canvas.__new__(_Canvas)
        host.image, host.draw = canvas.image, canvas.draw
        host.logo(c, x, y)
    else:
        canvas.text(x, y + 6, c.name.upper(), T_VALUE, p.ink, True)


def _share_change(c: CompanyView):
    text = _clean(c.shares.change)
    # "+2.03m (+2.14%) WoW" → "+2.14%"
    if "(" in text and ")" in text:
        return text[text.index("(") + 1:text.index(")")]
    return text.replace(" WoW", "")


def _company(canvas: Canvas, c: CompanyView, e: CompanyExtras, report_company, index: int, theme, p, variant):
    x0 = MARGIN + index * (PANEL + GAP)
    x1 = x0 + PANEL
    L, R = x0 + INSET, x1 - INSET
    top, bottom = CARD_TOP, HEIGHT - MARGIN
    stripe = p.company(c.ticker)
    themes.card(canvas, (x0, top, x1, bottom), p, stripe, theme, 6)
    _logo(canvas, c, theme, p, L, top + 22)
    canvas.text(R, top + 22, c.stock_price, T_VALUE, p.ink, True, align="right")
    canvas.text(L, top + 102, f"{c.ticker} · balance {_short(report_company.balance_date)}", T_MIN, p.muted)
    canvas.text(R, top + 96, f"{_clean(c.price_to_nav)} NAV", T_BODY, stripe, True, align="right")
    canvas.draw.line((L, top + 146, R, top + 146), fill=p.line, width=2)

    # Bitcoin bought — the point of the week — then how it was funded.
    y = top + 164
    canvas.text(L, y, "BITCOIN BOUGHT", T_LABEL, p.muted, True)
    canvas.text(R, y, "HELD", T_LABEL, p.muted, True, align="right")
    canvas.text(L, y + 36, _btc(e.btc_bought, True), T_BIG + 8, p.ink, True, max_width=(R - L) * .6)
    canvas.text(R, y + 52, _btc(e.btc_held), T_VALUE - 4, p.ink, True, align="right", max_width=(R - L) * .4)
    y += 146
    canvas.draw.line((L, y, R, y), fill=p.line, width=2)
    TOPS.get(variant, _top_ledger)(canvas, e, L, R, y + 22, p, stripe)
    y += 22 + TOP_H + 26

    # Per share: value and weekly change.
    canvas.draw.line((L, y, R, y), fill=p.line, width=2)
    value_x = L + (R - L) * .74
    canvas.text(L, y + 14, "PER SHARE", T_MIN, p.muted, True)
    canvas.text(R, y + 14, "WEEK", T_MIN, p.muted, True, align="right")
    y += 58
    rows = (("BTC / share", _clean(c.bitcoin.value).replace(" sats", ""), c.bitcoin.short_change, True),
            ("NAV / share", _clean(c.nav_per_share), _clean(c.nav_change.value), True),
            ("Amplification", _pct(e.amplification_pct), _pct(e.amplification_change_pp, 2, True, " pp"), False),
            ("Shares", c.shares.value, _share_change(c), False))
    for label, value, delta, toned in rows:
        canvas.text(L, y + 6, label, T_BODY, p.ink, True, max_width=(R - L) * .36)
        canvas.text(value_x, y, value, T_VALUE - 2, p.ink, True, align="right", max_width=(R - L) * .38)
        canvas.text(R, y + 6, delta, T_BODY, _tone_text(delta, p) if toned else p.muted, True, align="right",
                    max_width=(R - L) * .25)
        y += ROW_H
    if e.warrants:
        w = e.warrants
        canvas.pill(L, y - 8, f"{w['count'] / 1e6:.1f}M WARRANTS @ ${w['strike']:.0f} · DUE {w['expires']:%b} {w['expires'].day}".upper(),
                    T_MIN, p.card, stripe, pad=(14, 6))
    y += 52

    # Coverage against each issuer's own target.
    box_h = 132
    canvas.draw.rounded_rectangle((L - 10, y, R + 10, y + box_h), radius=min(10, p.radius + 4), fill=p.tint)
    on_target = e.reserve_months and e.target_months and e.reserve_months >= e.target_months - .5
    cells = (("USD COVER", f"{e.reserve_months:.0f} mo" if e.reserve_months else "—", _cover_note(e), on_target),
             ("COVERAGE", f"{e.coverage_years:.0f} yrs" if e.coverage_years else "—", "", False),
             ("BREAK-EVEN", f"{_pct(e.breakeven_pct, 2)}" if e.breakeven_pct else "—", "", False))
    cell = (R - L) / 3
    for n, (label, value, note, good) in enumerate(cells):
        cx = L + 6 + n * cell
        canvas.text(cx, y + 16, label, T_MIN, p.muted, True, max_width=cell - 12)
        canvas.text(cx, y + 52, value, T_VALUE - 4, p.ink, True, max_width=cell - 12)
        if note:
            canvas.text(cx, y + 96, note, T_MIN, p.positive if good else p.soft, good, max_width=cell - 12)
    y += box_h + 26

    # Growth: the same multi-week window for both companies, then QTD and YTD.
    weeks = e.window.get("weeks")
    columns = [(f"{weeks} WK" if weeks else "WK", _pct(e.window.get("btc"), 1, True) if weeks else "—",
                _pct(e.window.get("nav"), 1, True) if weeks else "—")]
    columns += [(period.period, _one_decimal(period.btc_growth), _one_decimal(period.nav_growth)) for period in c.periods[:2]]
    label_w = (R - L) * .34
    col_w = (R - L - label_w) / max(1, len(columns))
    canvas.text(L, y + 8, "GROWTH", T_MIN, p.muted, True)
    for n, (label, btc, nav) in enumerate(columns):
        cx = L + label_w + (n + 1) * col_w
        canvas.text(cx, y + 8, label, T_MIN, p.muted, True, align="right")
        canvas.text(cx, y + 52, btc, T_BODY + 2, _tone_text(btc, p), True, align="right", max_width=col_w - 8)
        canvas.text(cx, y + 112, nav, T_BODY + 2, _tone_text(nav, p), True, align="right", max_width=col_w - 8)
    canvas.text(L, y + 56, "BTC / share", T_BODY - 2, p.ink, True, max_width=label_w - 8)
    canvas.text(L, y + 116, "NAV / share", T_BODY - 2, p.ink, True, max_width=label_w - 8)


def _header(canvas, preview, theme, p):
    view = preview.view
    on_space = theme.decor == "orbit"
    light = "#F3F1EC" if on_space else p.ink
    muted = "#AEB6D6" if on_space else p.muted
    canvas.text(MARGIN, 34, "DIGITAL CREDIT REPORT · MONDAY", T_MIN, p.accent, True)
    canvas.text(WIDTH - MARGIN, 34, preview.period.upper(), T_MIN, p.accent, True, align="right")
    themes.title(canvas, MARGIN, 146, TITLE, 76, p, theme, on_space=on_space)
    canvas.text(MARGIN, 170, f"BTC {view.btc_price}", T_VALUE - 6, light, True)
    stamp = view.report_time.replace("Updated ", "", 1)
    canvas.text(WIDTH - MARGIN, 176, stamp, T_MIN, muted, align="right", max_width=760)


def render_png(preview: MondayPreview, theme: themes.Theme = themes.DEFAULT, variant: str = DEFAULT_VARIANT) -> tuple[bytes, list[str]]:
    p = theme.monday
    with fontset(theme.fontset):
        canvas = Canvas((WIDTH, HEIGHT), p.bg, floor=T_MIN)
        themes.background(canvas, p, theme, header_height=226, orbit_at=(1060, 92, .6))
        if theme.decor == "none":
            canvas.draw.rectangle((0, 0, WIDTH, 8), fill=p.accent)
        _header(canvas, preview, theme, p)
        for index, company in enumerate(preview.view.companies):
            source = next(item for item in preview.report.companies if item.ticker == company.ticker)
            _company(canvas, company, preview.extras[company.ticker], source, index, theme, p, variant)
        png = canvas.save(metadata={"Title": "The Accretion Ledger", "Theme": theme.key, "Variant": variant})
    return png, canvas.overflows


def notes(preview: MondayPreview) -> list[str]:
    """Footnotes for the web page; the X image carries none."""
    sources = " · ".join(f"{e.ticker}: {e.coverage_source}" for e in preview.extras.values())
    windows = " · ".join(f"{e.ticker} since {_short(e.window['start'])}" for e in preview.extras.values() if e.window.get("start"))
    return [line for line in (
        "Capital raised = ATM issuance − repurchases, common and preferred. Cash is an existing balance, never counted as a raise. "
        "Strive's common figure is an estimate: net share change × prior-week VWAP.",
        "Amplification = (debt + preferred) ÷ BTC value. NAV, price/NAV, amplification, coverage and growth are estimates from "
        "dated balances and reconstructed preferred claims at the displayed prices; growth holds prices constant.",
        "USD cover = months of preferred dividends, read against Strategy's 12-month floor and Strive's 18-month goal. "
        f"Coverage = (BTC + cash) ÷ annual dividends; break-even = dividends ÷ BTC value. {sources}.",
        f"Multi-week growth window: {windows}." if windows else "",
        *preview.notes,
    ) if line]


def audit_rows(preview: MondayPreview) -> list[dict]:
    """Plain-text values an auditor can check against primary sources."""
    rows = [{"metric": "BTC price", "value": preview.view.btc_price, "source": "api.strategy.com bitcoinKpis"}]
    for company in preview.view.companies:
        extra = preview.extras[company.ticker]
        report = next(c for c in preview.report.companies if c.ticker == company.ticker)
        rows += [
            {"metric": f"{company.ticker} balance date", "value": report.balance_date, "source": "SEC 8-K"},
            {"metric": f"{company.ticker} bitcoin bought", "value": company.btc_activity[0].value if company.btc_activity else "—", "source": "SEC 8-K"},
            {"metric": f"{company.ticker} total BTC held", "value": company.total_bitcoin.value if company.total_bitcoin else "—", "source": "SEC 8-K"},
            {"metric": f"{company.ticker} net common capital", "value": company.common.value, "source": "SEC 8-K ATM table" if company.ticker == "MSTR" else "share change × VWAP (est.)"},
            {"metric": f"{company.ticker} preferred capital", "value": company.preferred.value, "source": "SEC 8-K"},
            {"metric": f"{company.ticker} cash balance / change", "value": f"{_money(extra.liquid_balance, False)} / {_money(extra.liquid_change)} ({extra.liquid_detail})", "source": "SEC 8-K"},
            {"metric": f"{company.ticker} deployed (raised + cash drawn)", "value": _money(extra.net_funding, False), "source": "derived"},
            {"metric": f"{company.ticker} NAV / share (est.)", "value": _clean(company.nav_per_share), "source": "derived"},
            {"metric": f"{company.ticker} price / basic NAV", "value": _clean(company.price_to_nav), "source": "derived"},
            {"metric": f"{company.ticker} sats per share", "value": company.bitcoin.value, "source": "derived"},
            {"metric": f"{company.ticker} amplification (debt + preferred ÷ BTC)", "value": _pct(extra.amplification_pct), "source": "derived"},
            {"metric": f"{company.ticker} USD cover (months)", "value": f"{extra.reserve_months:.1f} ({_cover_note(extra)})" if extra.reserve_months else "—", "source": extra.coverage_source},
            {"metric": f"{company.ticker} {extra.window.get('weeks', '?')}-week BTC/share", "value": _pct(extra.window.get("btc"), 2, True), "source": f"since {extra.window.get('start', '—')}"},
            {"metric": f"{company.ticker} QTD BTC/share", "value": next((_clean(p.btc_growth) for p in company.periods if p.period == "QTD"), "—"), "source": "derived"},
        ]
    return rows
