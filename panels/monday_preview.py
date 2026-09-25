"""Monday preview: "The Accretion Ledger." built on the live Monday report.

All base values (NAV, capital, shares, sats, growth) come unchanged from the
production ``ReportView``. This module only adds: USD/dividend coverage, the
weekly funding bridge, amplification as a percent of BTC, a weekly sats/share
sparkline, the Strive warrant flag, a single estimate legend, and larger
secondary text for phones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from report import live_report as lr
from report.calculations import btc_value, liquid_assets
from report.models import Report
from report.presentation import build_report_view
from report.view_types import CompanyView, ReportView

from .draw import Canvas, imprint, mix, sparkline, width

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "preview-config.json"
ET = ZoneInfo("America/New_York")

WIDTH, HEIGHT = 1800, 1400
MARGIN, GAP = 40, 36
PANEL = (WIDTH - 2 * MARGIN - GAP) // 2
INSET = 29
BG, CARD, INK, MUTED, SOFT = "#F4F2EC", "#FFFFFF", "#182832", "#5B6C75", "#8A979E"
ORANGE, GREEN, RED, LINE, TINT = "#EB7B21", "#15745E", "#AE4355", "#DEE5E6", "#F4F6F6"
TITLE = ("The ", "Accretion", " Ledger")


@dataclass(frozen=True)
class CompanyExtras:
    ticker: str
    amplification_pct: float | None = None
    amplification_change_pp: float | None = None
    preferred_pct: float | None = None
    debt_pct: float | None = None
    net_leverage_pct: float | None = None
    liquid_change: float | None = None
    liquid_detail: str = ""
    net_funding: float | None = None
    reserve_months: float | None = None
    coverage_years: float | None = None
    breakeven_pct: float | None = None
    coverage_source: str = ""
    history: tuple = ()
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


def _history(rows, supplements, prices, ticker, through):
    points = {}
    for row in sorted(rows, key=lambda item: item.get("acceptedAt", "")):
        extraction = row["extracted"]
        if row["ticker"] != ticker or extraction["balanceDate"] > through:
            continue
        snapshot = lr._snapshot(ticker, extraction["balanceDate"], extraction["facts"], supplements, prices)
        if snapshot.btc_holdings and snapshot.effective_common_shares:
            points[extraction["balanceDate"]] = snapshot.btc_holdings / snapshot.effective_common_shares * 1e8
    return tuple(sorted(points.items()))[-12:]


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
    supplements = lr._load(lr.SUPPLEMENTS)
    config = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
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
            old_reserve, old_cash = _n(prior_facts.get("usd_reserve_usd")), _n(prior_facts.get("usd_cash_usd"))
            detail = (f"USD Reserve {_money(reserve, False)} ({_money(reserve - old_reserve)}) · USD Cash {_money(cash, False)} ({_money(cash - old_cash)})"
                      if None not in (reserve, cash, old_reserve, old_cash) else "USD Reserve + USD Cash")
        else:
            detail = f"Cash {_money(current.cash, False)} · STRC held {_money(current.marketable_securities, False)}"
        from report.calculations import calculate_company
        metrics = calculate_company(company, report.current_btc_price, report.prior_btc_price)
        funding = (metrics.net_common_capital + metrics.net_preferred_capital - liquid_change
                   if None not in (metrics.net_common_capital, metrics.net_preferred_capital, liquid_change) else None)
        months, years, breakeven, source = _coverage(ticker, company, report.current_btc_price, extras, facts)
        result[ticker] = CompanyExtras(
            ticker=ticker, amplification_pct=amp,
            amplification_change_pp=amp - prior_amp if amp is not None and prior_amp is not None else None,
            preferred_pct=current.preferred_claims / bitcoin * 100 if bitcoin and current.preferred_claims is not None else None,
            debt_pct=current.debt_principal / bitcoin * 100 if bitcoin and current.debt_principal is not None else None,
            net_leverage_pct=(current.debt_principal - liquid) / bitcoin * 100 if bitcoin and liquid is not None and current.debt_principal is not None else None,
            liquid_change=liquid_change, liquid_detail=detail, net_funding=funding,
            reserve_months=months, coverage_years=years, breakeven_pct=breakeven, coverage_source=source,
            history=_history(rows, supplements, prices, ticker, company.balance_date),
            warrants=_warrants(ticker, company, facts, config, now))
    period = report.capital_period_label.split("·")[-1].strip()
    kicker = f"THE DIGITAL CREDIT REPORT  ·  MONDAY  ·  8-K WEEK {period.upper()}"
    dates = " · ".join(f"{c.name} {_short(c.balance_date)}" for c in report.companies if c.balance_date)
    subtitle = f"What last week's filings did to each common share  ·  Balances: {dates}"
    notes = tuple(f"{t} data stale" for t in extras.get("stale", []))
    return MondayPreview(report, view, result, kicker, subtitle, notes)


# ── rendering ───────────────────────────────────────────────────────────────
def _tone(value):
    return GREEN if value is not None and value > 0 else RED if value is not None and value < 0 else INK


def _tone_text(text):
    stripped = text.replace("≈", "").strip()
    return GREEN if stripped.startswith("+") else RED if stripped.startswith("−") else INK


def _row(canvas, left, right, y, label, value, *, detail="", value_color=INK, label_size=23, value_size=29, detail_size=20):
    canvas.text(left, y + 3, label, label_size, INK, True, max_width=(right - left) * .58)
    canvas.text(right, y, value, value_size, value_color, True, align="right", max_width=(right - left) * .38)
    if detail:
        canvas.text(left, y + 38, detail, detail_size, MUTED, max_width=right - left, minimum=16)


def _company(canvas: Canvas, c: CompanyView, e: CompanyExtras, index: int, period_label: str):
    x = MARGIN + index * (PANEL + GAP)
    left, right = x + INSET, x + PANEL - INSET
    span = right - left
    top, bottom = 160, HEIGHT - 70
    draw = canvas.draw
    canvas.card((x, top, x + PANEL, bottom), CARD, radius=14)
    draw.rectangle((x, top, x + PANEL, top + 5), fill=ORANGE if index == 0 else INK)
    from report.png_export import _Canvas  # reuse the approved logo placement
    logo_host = _Canvas.__new__(_Canvas)
    logo_host.image, logo_host.draw = canvas.image, canvas.draw
    logo_host.logo(c, left, top + 18)
    canvas.text(right, top + 17, c.stock_price, 32, INK, True, align="right")
    canvas.text(right, top + 58, f"{c.ticker} · last price", 18, MUTED, align="right")
    canvas.text(right, top + 81, c.quote_timestamp, 18, MUTED, align="right")
    y = top + 112
    draw.line((left, y, right, y), fill=LINE)
    canvas.text(left, y + 14, "NET TREASURY NAV / SHARE", 19, MUTED, True)
    canvas.text(right, y + 14, "PRICE / BASIC NAV", 19, MUTED, True, align="right")
    canvas.text(left, y + 44, _clean(c.nav_per_share), 40, INK, True)
    canvas.text(right, y + 46, _clean(c.price_to_nav), 36, INK, True, align="right")
    y += 104
    draw.line((left, y, right, y), fill=LINE)
    activity = c.btc_activity[0] if c.btc_activity else None
    canvas.text(left, y + 12, activity.label if activity else "Bitcoin activity", 21, MUTED, True)
    canvas.text(left, y + 40, activity.value if activity else "—", 29, INK, True)
    total = c.total_bitcoin.value if c.total_bitcoin else "—"
    canvas.text(right, y + 12, "Total BTC held", 21, MUTED, True, align="right")
    canvas.text(right, y + 40, total, 29, INK, True, align="right")
    y += 90
    canvas.text(left, y, period_label.upper(), 18, ORANGE, True, max_width=span * .62)
    canvas.text(right, y + 1, "+ RAISED / − USED", 17, MUTED, align="right")
    y += 30
    _row(canvas, left, right, y, c.common.label, c.common.value, detail=" · ".join(c.common.post_details or c.common.details))
    y += 74
    _row(canvas, left, right, y, c.preferred.label, c.preferred.value,
         detail=" · ".join((c.preferred.post_details or c.preferred.details)))
    y += 74
    cash_label = "USD Reserve + Cash change" if e.ticker == "MSTR" else "Cash change"
    _row(canvas, left, right, y, cash_label, _money(e.liquid_change), detail=e.liquid_detail)
    y += 74
    # Funding bridge: capital raised plus cash drawn equals what funded BTC and other uses.
    draw.rounded_rectangle((left, y, right, y + 44), radius=8, fill=mix(ORANGE, CARD, .09))
    bought = activity.value if activity else "BTC"
    canvas.text(left + 14, y + 11, f"Net funding for {bought} & other uses", 20, INK, True, max_width=span * .66)
    canvas.text(right - 14, y + 9, _money(e.net_funding), 24, INK, True, align="right")
    y += 60
    canvas.text(left, y + 3, c.shares.label, 23, INK, True, max_width=span * .6)
    canvas.text(right, y, c.shares.value, 29, INK, True, align="right")
    canvas.text(left, y + 38, " · ".join(c.shares.details), 20, MUTED, max_width=span * .5)
    canvas.text(right, y + 38, c.shares.change, 20, MUTED, align="right")
    if e.warrants:
        w = e.warrants
        flag = f"WARRANTS · DEADLINE {w['expires']:%b} {w['expires'].day}".upper()
        canvas.pill(left, y + 70, flag, 15, "#FFFFFF", ORANGE)
        itm = f"in the money +${w['in_the_money']:.2f}" if w["in_the_money"] and w["in_the_money"] > 0 else "out of the money"
        canvas.text(left + width(flag, 15, True) + 36, y + 72,
                    f"{w['count'] / 1e6:.1f}m @ ${w['strike']:.0f} · {_money(w['proceeds'], False, 0)} if exercised · {itm}",
                    19, MUTED, max_width=span - width(flag, 15, True) - 36, minimum=15)
    y += 108
    draw.line((left, y, right, y), fill=LINE)
    value_x = left + span * .72
    canvas.text(value_x, y + 12, "VALUE", 16, MUTED, True, align="right")
    canvas.text(right, y + 12, "WEEKLY Δ", 16, MUTED, True, align="right")
    y += 38
    # BTC per share with a sparkline of every reconciled weekly balance.
    canvas.text(left, y + 3, "Bitcoin per common share", 23, INK, True)
    canvas.text(value_x, y, _clean(c.bitcoin.value), 28, INK, True, align="right")
    canvas.text(right, y + 5, c.bitcoin.short_change, 22, _tone_text(c.bitcoin.short_change), True, align="right")
    values = [value for _, value in e.history]
    if len(values) >= 2:
        sparkline(canvas, (left + 2, y + 40, left + 132, y + 62), values, ORANGE if index == 0 else INK, width_px=3)
        first = e.history[0]
        change = (e.history[-1][1] / first[1] - 1) * 100
        canvas.text(left + 146, y + 40, f"{len(values)} weekly filings since {_short(first[0])}: {_pct(change, 2, True)} sats/share",
                    19, MUTED, max_width=span - 150)
    y += 76
    nav = _clean(c.nav_change.value)
    canvas.text(left, y + 3, "NAV per common share", 23, INK, True)
    canvas.text(value_x, y, _clean(c.nav_per_share), 28, INK, True, align="right")
    canvas.text(right, y + 5, nav, 22, _tone_text(nav), True, align="right")
    y += 46
    canvas.text(left, y + 3, "Amplification · debt + pref ÷ BTC", 23, INK, True, max_width=span * .56)
    canvas.text(value_x, y, _pct(e.amplification_pct), 28, INK, True, align="right")
    canvas.text(right, y + 5, _pct(e.amplification_change_pp, 2, True, " pp"), 22, INK, True, align="right")
    net = ("net cash" if e.net_leverage_pct is not None and e.net_leverage_pct < 0
           else f"net leverage {_pct(e.net_leverage_pct)}")
    canvas.text(left, y + 36, f"Preferred {_pct(e.preferred_pct)} · debt {_pct(e.debt_pct)} · {net} (debt − cash)",
                19, MUTED, max_width=span)
    y += 70
    # Coverage strip: three company-level funding-risk readings.
    draw.rounded_rectangle((left, y, right, y + 92), radius=8, fill=TINT)
    cells = (("USD COVER", f"{e.reserve_months:.0f} months" if e.reserve_months else "—", "of preferred dividends"),
             ("TOTAL COVERAGE", f"{e.coverage_years:.0f} years" if e.coverage_years else "—", "BTC + cash ÷ dividends"),
             ("BTC BREAK-EVEN", f"{_pct(e.breakeven_pct, 2)}/yr" if e.breakeven_pct else "—", "dividends ÷ BTC value"))
    cell = (span - 32) / 3
    for n, (label, value, note) in enumerate(cells):
        cx = left + 16 + n * cell
        canvas.text(cx, y + 12, label, 15, MUTED, True, max_width=cell - 10)
        canvas.text(cx, y + 33, value, 26, INK, True, max_width=cell - 10)
        canvas.text(cx, y + 66, note, 15, SOFT, max_width=cell - 10)
    y += 104
    draw.rounded_rectangle((left, y, right, bottom - 16), radius=8, fill=TINT)
    canvas.text(left + 16, y + 13, "BASIC-SHARE GROWTH", 16, MUTED, True)
    columns = (left + span * .72, right - 16)
    for period, column in zip(c.periods, columns):
        canvas.text(column, y + 13, period.period, 16, MUTED, True, align="right")
        btc = _clean(period.btc_growth)
        nav_growth = _clean(period.nav_growth)
        canvas.text(column, y + 40, btc, 22, _tone_text(btc), True, align="right")
        canvas.text(column, y + 71, nav_growth, 22, _tone_text(nav_growth), True, align="right")
    notes = [f"{p.period} {p.baseline_note}" for p in c.periods if p.baseline_note]
    if notes:
        canvas.text(left + 16 + width("BASIC-SHARE GROWTH", 16, True) + 14, y + 14, " · ".join(notes), 14, SOFT, max_width=span * .3)
    canvas.text(left + 16, y + 41, "BTC / share", 20, INK, True)
    canvas.text(left + 16, y + 72, "NAV / share", 20, INK, True)


def render_png(preview: MondayPreview) -> tuple[bytes, list[str]]:
    view = preview.view
    canvas = Canvas((WIDTH, HEIGHT), BG)
    canvas.draw.rectangle((0, 0, WIDTH, 6), fill=ORANGE)
    canvas.text(MARGIN, 24, preview.kicker, 18, ORANGE, True, max_width=1080)
    imprint(canvas, MARGIN, 104, TITLE, 54, ink="#1b2c34", muted="#52646d", dot="#e88029")
    canvas.text(MARGIN, 120, preview.subtitle, 20, MUTED, max_width=1080)
    canvas.text(WIDTH - MARGIN, 30, f"BTC {view.btc_price}", 31, INK, True, align="right")
    stamp = view.report_time.replace("Updated ", "Quotes ", 1)
    canvas.text(WIDTH - MARGIN, 72, stamp, 19, MUTED, align="right", max_width=620)
    if view.comparison_note:
        canvas.text(WIDTH - MARGIN, 100, view.comparison_note, 17, SOFT, align="right", max_width=620)
    for index, company in enumerate(view.companies):
        _company(canvas, company, preview.extras[company.ticker], index, view.capital_period_label)
    footer = ("Estimates: NAV, price/NAV, amplification, coverage and growth use dated balances, reconstructed "
              "preferred claims and the displayed prices · NAV growth at constant prices · Methodology on Streamlit")
    canvas.text(MARGIN, HEIGHT - 52, footer, 17, MUTED, max_width=WIDTH - 2 * MARGIN)
    sources = " · ".join(f"{e.ticker} {e.coverage_source}" for e in preview.extras.values())
    canvas.text(MARGIN, HEIGHT - 28, "Net funding = capital raised + cash drawn. Coverage inputs: " + sources
                + " (SATA dividends paid each business day).", 16, SOFT, max_width=WIDTH - 2 * MARGIN)
    png = canvas.save(metadata={"Title": "The Accretion Ledger", "Software": "The Digital Credit Report (preview)"})
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
            {"metric": f"{company.ticker} cash / reserve change", "value": _money(extra.liquid_change), "source": "SEC 8-K"},
            {"metric": f"{company.ticker} NAV / share (est.)", "value": _clean(company.nav_per_share), "source": "derived"},
            {"metric": f"{company.ticker} price / basic NAV", "value": _clean(company.price_to_nav), "source": "derived"},
            {"metric": f"{company.ticker} sats per share", "value": company.bitcoin.value, "source": "derived"},
            {"metric": f"{company.ticker} amplification (debt+pref ÷ BTC)", "value": _pct(extra.amplification_pct), "source": "derived"},
            {"metric": f"{company.ticker} USD cover (months)", "value": f"{extra.reserve_months:.1f}" if extra.reserve_months else "—", "source": extra.coverage_source},
            {"metric": f"{company.ticker} QTD BTC/share", "value": next((_clean(p.btc_growth) for p in company.periods if p.period == "QTD"), "—"), "source": "derived"},
        ]
    return rows
