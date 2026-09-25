"""Monday: "The Accretion Ledger." built on the live Monday report.

All base values (NAV, capital, shares, sats, growth) come unchanged from the
production ``ReportView``. This module adds USD/dividend coverage read against
each company's own target, a clear split between capital raised through the
ATMs and cash drawn from (or added to) balances, the funding bridge, leverage
as a percent of BTC, a same-window multi-week growth column for both
companies, and Strive's warrant flag.
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

from .draw import Canvas, fontset, mix, width
from . import themes

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "preview-config.json"
ET = ZoneInfo("America/New_York")

WIDTH, HEIGHT = 1800, 1400
MARGIN, GAP = 40, 36
PANEL = (WIDTH - 2 * MARGIN - GAP) // 2
INSET = 29
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
            detail = (f"USD Reserve {_money(reserve, False)} · USD Cash {_money(cash, False)}"
                      if None not in (reserve, cash) else "USD Reserve + USD Cash")
        else:
            detail = f"Cash {_money(current.cash, False)} · STRC held {_money(current.marketable_securities, False)}"
        metrics = calculate_company(company, report.current_btc_price, report.prior_btc_price)
        raised = (metrics.net_common_capital + metrics.net_preferred_capital
                  if None not in (metrics.net_common_capital, metrics.net_preferred_capital) else None)
        funding = raised - liquid_change if raised is not None and liquid_change is not None else None
        months, years, breakeven, source = _coverage(ticker, company, report.current_btc_price, extras, facts)
        key = "strategy_reserve_floor_months" if ticker == "MSTR" else "strive_reserve_goal_months"
        target = _n((config.get(key) or {}).get("value"))
        result[ticker] = CompanyExtras(
            ticker=ticker, amplification_pct=amp,
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
    return MondayPreview(report, view, result, kicker, subtitle, notes)


# ── rendering ───────────────────────────────────────────────────────────────
def _tone_text(text, p):
    stripped = text.replace("≈", "").strip()
    return p.positive if stripped.startswith("+") else p.negative if stripped.startswith("−") else p.ink


def _cover_note(e: CompanyExtras):
    if not e.reserve_months or not e.target_months:
        return "of preferred dividends"
    if e.target_kind == "goal":
        gap = e.reserve_months - e.target_months
        return f"at its {e.target_months:.0f}-month goal" if abs(gap) < .5 else f"{gap:+.0f} vs {e.target_months:.0f}-month goal"
    return f"{e.reserve_months / e.target_months:.1f}× the {e.target_months:.0f}-month floor"


def _chip(canvas, x, y, label, value, p, fill, *, strong=False, w=None):
    w = w or max(width(label, 13, True), width(value, 22, True)) + 28
    canvas.draw.rounded_rectangle((x, y, x + w, y + 58), radius=min(8, p.radius), fill=fill,
                                  outline=p.outline if p.outline_width > 1 else None, width=2 if p.outline_width > 1 else 0)
    canvas.text(x + 14, y + 8, label, 13, p.muted, True)
    canvas.text(x + 14, y + 26, value, 22, p.ink, True)
    return x + w


def _company(canvas: Canvas, c: CompanyView, e: CompanyExtras, index: int, period_label: str, theme, p):
    x = MARGIN + index * (PANEL + GAP)
    left, right = x + INSET, x + PANEL - INSET
    span = right - left
    top, bottom = 172, HEIGHT - 72
    draw = canvas.draw
    stripe = p.accent if index == 0 else p.accent2
    themes.card(canvas, (x, top, x + PANEL, bottom), p, stripe, theme, 5)
    from report.png_export import _Canvas  # approved logo placement
    host = _Canvas.__new__(_Canvas)
    host.image, host.draw = canvas.image, canvas.draw
    if theme.key == "classic" or theme.decor == "orbit" and p.card.startswith("#F"):
        host.logo(c, left, top + 18)
    else:
        canvas.text(left, top + 26, c.name.upper(), 40, p.ink, True)
    canvas.text(right, top + 17, c.stock_price, 32, p.ink, True, align="right")
    canvas.text(right, top + 58, f"{c.ticker} · last price", 18, p.muted, align="right")
    canvas.text(right, top + 81, c.quote_timestamp, 18, p.muted, align="right")
    y = top + 112
    draw.line((left, y, right, y), fill=p.line)
    canvas.text(left, y + 14, "NET TREASURY NAV / SHARE", 18, p.muted, True)
    canvas.text(right, y + 14, "PRICE / BASIC NAV", 18, p.muted, True, align="right")
    canvas.text(left, y + 42, _clean(c.nav_per_share), 40, p.ink, True)
    canvas.text(right, y + 44, _clean(c.price_to_nav), 36, p.ink, True, align="right")
    y += 100
    draw.line((left, y, right, y), fill=p.line)
    activity = c.btc_activity[0] if c.btc_activity else None
    canvas.text(left, y + 12, activity.label if activity else "Bitcoin activity", 20, p.muted, True)
    canvas.text(left, y + 38, activity.value if activity else "—", 29, p.ink, True)
    total = c.total_bitcoin.value if c.total_bitcoin else "—"
    canvas.text(right, y + 12, "Total BTC held", 20, p.muted, True, align="right")
    canvas.text(right, y + 38, total, 29, p.ink, True, align="right")

    # A — capital raised through the ATMs.
    y += 88
    canvas.text(left, y, "CAPITAL RAISED · " + period_label.split("·")[-1].strip().upper(), 17, p.accent, True, max_width=span * .7)
    canvas.text(right, y + 1, "ATM · + ISSUED / − REPURCHASED", 14, p.muted, True, align="right")
    y += 28
    for metric in (c.common, c.preferred):
        canvas.text(left, y + 3, metric.label, 23, p.ink, True, max_width=span * .6)
        canvas.text(right, y, metric.value, 29, _tone_text(metric.value, p), True, align="right")
        detail = " · ".join(metric.post_details or metric.details)
        canvas.text(left, y + 37, detail, 18, p.muted, max_width=span, minimum=15)
        y += 70

    # B — cash on hand: a balance, not new capital.
    box = (left, y + 4, right, y + 96)
    draw.rounded_rectangle(box, radius=min(10, p.radius + 2), fill=p.cash,
                           outline=p.outline if p.outline_width > 1 else None, width=2 if p.outline_width > 1 else 0)
    cash_label = "USD RESERVE + CASH" if e.ticker == "MSTR" else "CASH ON HAND"
    canvas.text(left + 16, y + 16, f"{cash_label} · A BALANCE, NOT NEW CAPITAL", 14, p.muted, True, max_width=span * .7)
    canvas.text(left + 16, y + 38, _money(e.liquid_balance, False), 28, p.ink, True)
    canvas.text(left + 16, y + 72, e.liquid_detail, 16, p.muted, max_width=span * .62)
    change = e.liquid_change
    verb = "drawn this week" if change is not None and change < 0 else "added this week" if change else "unchanged"
    canvas.text(right - 16, y + 30, _money(abs(change) if change is not None else None, False), 28,
                p.negative if change is not None and change < 0 else p.positive if change else p.ink, True, align="right")
    canvas.text(right - 16, y + 66, verb, 16, p.muted, align="right")
    y += 110

    # C — the funding bridge: raised + drawn = deployed.
    drawn = -e.liquid_change if e.liquid_change is not None else None
    cx = left
    cx = _chip(canvas, cx, y, "RAISED (ATM)", _money(e.raised), p, mix(p.accent, p.card, .10))
    canvas.text(cx + 12, y + 16, "+", 26, p.muted, True)
    cx = _chip(canvas, cx + 36, y, "FROM CASH" if (drawn or 0) >= 0 else "TO CASH", _money(drawn), p, p.cash)
    canvas.text(cx + 12, y + 16, "=", 26, p.muted, True)
    cx = _chip(canvas, cx + 36, y, "DEPLOYED", _money(e.net_funding, False), p, mix(p.positive, p.card, .12))
    bought = activity.value if activity else "BTC"
    canvas.text(cx + 14, y + 8, f"into {bought}", 18, p.ink, True, max_width=right - cx - 14)
    canvas.text(cx + 14, y + 32, "& other uses (dividends, fees)", 15, p.muted, max_width=right - cx - 14)
    y += 76

    canvas.text(left, y + 3, c.shares.label, 23, p.ink, True, max_width=span * .6)
    canvas.text(right, y, c.shares.value, 29, p.ink, True, align="right")
    canvas.text(right, y + 37, c.shares.change, 18, p.muted, align="right")
    if e.warrants:
        w = e.warrants
        flag = f"WARRANTS · DEADLINE {w['expires']:%b} {w['expires'].day}".upper()
        canvas.pill(left, y + 34, flag, 13, p.card, p.accent)
        itm = f"+${w['in_the_money']:.2f} ITM" if w["in_the_money"] and w["in_the_money"] > 0 else "out of the money"
        canvas.text(left + width(flag, 13, True) + 32, y + 36, f"{w['count'] / 1e6:.1f}m @ ${w['strike']:.0f} · {itm}",
                    16, p.muted, max_width=span * .56 - width(flag, 13, True) - 32, minimum=13)
    y += 72
    draw.line((left, y, right, y), fill=p.line)
    value_x = left + span * .72
    canvas.text(value_x, y + 10, "VALUE", 15, p.muted, True, align="right")
    canvas.text(right, y + 10, "WEEKLY Δ", 15, p.muted, True, align="right")
    y += 34
    rows = (("Bitcoin per common share", _clean(c.bitcoin.value), c.bitcoin.short_change),
            ("NAV per common share", _clean(c.nav_per_share), _clean(c.nav_change.value)),
            ("Debt + preferred ÷ BTC", _pct(e.amplification_pct), _pct(e.amplification_change_pp, 2, True, " pp")))
    for index_row, (label, value, delta) in enumerate(rows):
        canvas.text(left, y + 3, label, 23, p.ink, True)
        canvas.text(value_x, y, value, 28, p.ink, True, align="right")
        tone = _tone_text(delta, p) if index_row < 2 else p.ink
        canvas.text(right, y + 5, delta, 21, tone, True, align="right")
        y += 44
    y += 8
    # Coverage, read against each company's own target.
    draw.rounded_rectangle((left, y, right, y + 90), radius=min(8, p.radius), fill=p.tint)
    cells = (("USD COVER", f"{e.reserve_months:.0f} months" if e.reserve_months else "—", _cover_note(e)),
             ("TOTAL COVERAGE", f"{e.coverage_years:.0f} years" if e.coverage_years else "—", "BTC + cash ÷ dividends"),
             ("BTC BREAK-EVEN", f"{_pct(e.breakeven_pct, 2)}/yr" if e.breakeven_pct else "—", "dividends ÷ BTC value"))
    cell = (span - 32) / 3
    for n, (label, value, note) in enumerate(cells):
        cx = left + 16 + n * cell
        canvas.text(cx, y + 11, label, 14, p.muted, True, max_width=cell - 10)
        canvas.text(cx, y + 31, value, 25, p.ink, True, max_width=cell - 10)
        on_target = n == 0 and e.reserve_months and e.target_months and e.reserve_months >= e.target_months - .5
        canvas.text(cx, y + 64, note, 14, p.positive if on_target else p.soft, on_target, max_width=cell - 10)
    y += 102
    draw.rounded_rectangle((left, y, right, bottom - 14), radius=min(8, p.radius), fill=p.tint)
    canvas.text(left + 16, y + 12, "BASIC-SHARE GROWTH", 15, p.muted, True)
    weeks = e.window.get("weeks")
    columns = [(left + span * .52, f"{weeks} WK" if weeks else "WK", _pct(e.window.get("btc"), 2, True) if weeks else "—",
                _pct(e.window.get("nav"), 2, True) if weeks else "—")]
    for period, column in zip(c.periods, (left + span * .75, right - 16)):
        columns.append((column, period.period, _clean(period.btc_growth), _clean(period.nav_growth)))
    for column, label, btc, nav in columns:
        canvas.text(column, y + 14, label, 15, p.muted, True, align="right")
        canvas.text(column, y + 48, btc, 24, _tone_text(btc, p), True, align="right")
        canvas.text(column, y + 88, nav, 24, _tone_text(nav, p), True, align="right")
    canvas.text(left + 16, y + 50, "BTC / share", 21, p.ink, True)
    canvas.text(left + 16, y + 90, "NAV / share", 21, p.ink, True)
    start = e.window.get("start")
    if start:
        canvas.text(left + span * .52, bottom - 38, f"since {_short(start)} filing", 13, p.soft, align="right")


def _header(canvas, preview, theme, p):
    view = preview.view
    on_space = theme.decor == "orbit"
    light = "#F3F1EC" if on_space else p.ink
    muted = "#AEB6D6" if on_space else p.muted
    canvas.text(MARGIN, 26, preview.kicker, 18, p.accent, True, max_width=1080)
    themes.title(canvas, MARGIN, 106, TITLE, 54, p, theme, on_space=on_space)
    canvas.text(MARGIN, 122, preview.subtitle, 20, muted, max_width=1080)
    canvas.text(WIDTH - MARGIN, 30, f"BTC {view.btc_price}", 31, light, True, align="right")
    stamp = view.report_time.replace("Updated ", "Quotes ", 1)
    canvas.text(WIDTH - MARGIN, 72, stamp, 19, muted, align="right", max_width=620)
    if view.comparison_note:
        canvas.text(WIDTH - MARGIN, 100, view.comparison_note, 17, muted, align="right", max_width=620)


def render_png(preview: MondayPreview, theme: themes.Theme = themes.CLASSIC) -> tuple[bytes, list[str]]:
    p = theme.monday
    with fontset(theme.fontset):
        canvas = Canvas((WIDTH, HEIGHT), p.bg)
        themes.background(canvas, p, theme, header_height=158, orbit_at=(1200, 70, .8))
        if theme.decor == "none":
            canvas.draw.rectangle((0, 0, WIDTH, 6), fill=p.accent)
        _header(canvas, preview, theme, p)
        for index, company in enumerate(preview.view.companies):
            _company(canvas, company, preview.extras[company.ticker], index, preview.view.capital_period_label, theme, p)
        canvas.text(MARGIN, HEIGHT - 56, "Estimates: NAV, price/NAV, leverage, coverage and growth use dated balances, reconstructed "
                    "preferred claims and the displayed prices · growth at constant prices · methodology on Streamlit",
                    16, p.muted, max_width=WIDTH - 2 * MARGIN)
        sources = " · ".join(f"{e.ticker} {e.coverage_source}" for e in preview.extras.values())
        canvas.text(MARGIN, HEIGHT - 32, "Capital raised = ATM issuance − repurchases. Cash is an existing balance. "
                    "Coverage inputs: " + sources + ".", 15, p.soft, max_width=WIDTH - 2 * MARGIN)
        png = canvas.save(metadata={"Title": "The Accretion Ledger", "Theme": theme.key})
    return png, canvas.overflows


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
            {"metric": f"{company.ticker} cash balance / change", "value": f"{_money(extra.liquid_balance, False)} / {_money(extra.liquid_change)}", "source": "SEC 8-K"},
            {"metric": f"{company.ticker} deployed (raised + cash drawn)", "value": _money(extra.net_funding, False), "source": "derived"},
            {"metric": f"{company.ticker} NAV / share (est.)", "value": _clean(company.nav_per_share), "source": "derived"},
            {"metric": f"{company.ticker} price / basic NAV", "value": _clean(company.price_to_nav), "source": "derived"},
            {"metric": f"{company.ticker} sats per share", "value": company.bitcoin.value, "source": "derived"},
            {"metric": f"{company.ticker} debt + preferred ÷ BTC", "value": _pct(extra.amplification_pct), "source": "derived"},
            {"metric": f"{company.ticker} USD cover (months)", "value": f"{extra.reserve_months:.1f} ({_cover_note(extra)})" if extra.reserve_months else "—", "source": extra.coverage_source},
            {"metric": f"{company.ticker} {extra.window.get('weeks', '?')}-week BTC/share", "value": _pct(extra.window.get("btc"), 2, True), "source": f"since {extra.window.get('start', '—')}"},
            {"metric": f"{company.ticker} QTD BTC/share", "value": next((_clean(p.btc_growth) for p in company.periods if p.period == "QTD"), "—"), "source": "derived"},
        ]
    return rows
