"""Monday: "The Accretion Ledger." built on the live Monday report.

All base values (NAV, capital, shares, sats, growth) come unchanged from the
production ``ReportView``. This module adds USD/dividend coverage read against
each company's own target, a clear split between capital raised through the
ATMs and cash drawn from (or added to) balances, where the money went (bitcoin
versus dividends), each issuer's own amplification ratio, a same-window
multi-week growth column for both companies and Strive's warrant tag. The
funding block has three layouts (``VARIANTS``).
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

from .draw import T_BIG, T_BODY, T_HERO, T_LABEL, T_MIN, T_VALUE, Canvas, cap_middle, fontset, mix, width
from .extras import strategy_weeks
from . import themes

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data" / "preview-config.json"
ET = ZoneInfo("America/New_York")

WIDTH, HEIGHT = 1440, 1884  # within X's 3:4
MARGIN, GAP = 40, 24
PANEL = (WIDTH - 2 * MARGIN - GAP) // 2
INSET = 30
CARD_TOP = 236
TITLE = ("The ", "Accretion", " Ledger")


@dataclass(frozen=True)
class CompanyExtras:
    ticker: str
    amplification_pct: float | None = None      # (preferred notional + debt) ÷ BTC value, in % (Strive's ratio)
    amplification_change_pp: float | None = None
    amplification_x: float | None = None        # shown, in ×: each issuer's own formula (see build_preview)
    amplification_change_x: float | None = None
    amplification_source: str = ""
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
    btc_cost: float | None = None               # the week's bitcoin purchases (− sale proceeds)
    btc_cost_source: str = ""
    dividends: float | None = None              # the rest of the week's funding: dividends, interest, fees
    stated_dividends: float | None = None       # Strategy's 8-K figure for dividends and interest, if given
    reserve_months: float | None = None
    target_months: float | None = None
    target_kind: str = ""
    coverage_years: float | None = None
    breakeven_pct: float | None = None
    coverage_source: str = ""
    window: dict = field(default_factory=dict)
    warrants: dict | None = None
    cost_basis: float | None = None             # aggregate BTC purchase cost, fees included
    average_cost: float | None = None
    cost_source: str = ""
    filing_url: str | None = None               # the week's 8-K


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


def _average_close(extras, start, end):
    """Mean BTC-USD daily close over (start, end], for an estimated purchase cost."""
    rows = ((extras.get("yahoo") or {}).get("BTC-USD") or {}).get("rows") or []
    closes = [row["close"] for row in rows if row.get("close") and start < row.get("date", "") <= end]
    return sum(closes) / len(closes) if closes else None


def _btc_cost(ticker, company, facts, extras, btc_price):
    """The week's bitcoin cost, with its source: filed figures first, an estimate last."""
    bought, sold = _n(facts.get("weekly_btc_purchases")), _n(facts.get("weekly_btc_sales"))
    start, end = company.prior_balance_date or "", company.balance_date or ""
    if ticker == "MSTR":
        cost = _n(facts.get("weekly_btc_cost_usd"))
        if cost is not None:
            return cost, "SEC 8-K aggregate purchase price"
        week = strategy_weeks().get(end) or {}
        if "btc_cost_usd" in week or "btc_sale_proceeds_usd" in week:
            return ((_n(week.get("btc_cost_usd")) or 0) - (_n(week.get("btc_sale_proceeds_usd")) or 0),
                    "SEC 8-K aggregate purchase price (data/strategy-weekly-8k.json)")
    else:
        trades = [row for row in (extras.get("strive") or {}).get("transactions") or []
                  if row.get("type") == "purchase" and start < (row.get("transaction_date") or "") <= end
                  and _n(row.get("cost")) and _n(row.get("btc_amount"))]
        if trades and bought:
            # Price the filed quantity at the dashboard's cost per BTC for the same dates.
            per_btc = sum(_n(row["cost"]) for row in trades) / sum(_n(row["btc_amount"]) for row in trades)
            return bought * per_btc, "strive.com dashboard purchase cost"
    if bought == 0 and not sold:
        return 0.0, "no purchases"
    if bought and not sold:
        price = _average_close(extras, start, end) or btc_price
        return bought * price, "estimate: BTC bought × average BTC close for the week"
    return None, ""


def _cost_basis(ticker, company, facts, extras):
    """Aggregate and average BTC purchase cost at the balance date (test copy)."""
    if ticker == "MSTR":
        basis, average = _n(facts.get("btc_cost_basis_usd")), _n(facts.get("btc_average_cost_usd"))
        if basis and average:
            return basis, average, "SEC 8-K"
        week = strategy_weeks().get(company.balance_date) or {}
        if week.get("btc_cost_basis_usd") and week.get("btc_average_cost_usd"):
            return week["btc_cost_basis_usd"], week["btc_average_cost_usd"], "SEC 8-K (data/strategy-weekly-8k.json)"
        return None, None, ""
    rows = sorted((row for row in (extras.get("strive") or {}).get("transactions") or []
                   if (row.get("transaction_date") or "") <= (company.balance_date or "")
                   and _n(row.get("total_cost_basis")) and _n(row.get("total_btc_holdings"))),
                  key=lambda row: row["transaction_date"])
    if not rows:
        return None, None, ""
    basis, held = _n(rows[-1]["total_cost_basis"]), _n(rows[-1]["total_btc_holdings"])
    return basis, basis / held, "strive.com dashboard cost basis"


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
        # Strive's amplification ratio: (notional preferred + debt) ÷ BTC value.
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
        btc_cost, cost_source = _btc_cost(ticker, company, facts, extras, report.current_btc_price)
        stated = _n(facts.get("usd_reserve_dividends_interest_usd"))
        if stated is None and ticker == "MSTR":
            stated = _n((strategy_weeks().get(company.balance_date) or {}).get("reserve_dividends_interest_usd"))
        if ticker == "MSTR":
            # Strategy's amplification (strategy.com KPI since Jul 23, 2026): BTC reserve ÷ net BTC reserve.
            kpi = _n(((extras.get("strategy") or {}).get("btc") or {}).get("amplification"))
            amp_x, amp_source = (kpi, "strategy.com KPI") if kpi else (metrics.net_btc_amplification, "derived")
            amp_change_x = metrics.amplification_change
        else:
            # Strive's own "Amplification Ratio" (its dashboard): (debt + SATA notional) ÷ BTC value.
            # Shown as exposure in ×: 1 + the ratio (a 50.5% ratio reads 1.51×).
            amp_x = 1 + amp / 100 if amp is not None else None
            amp_change_x = (amp - prior_amp) / 100 if amp is not None and prior_amp is not None else None
            amp_source = "Strive's formula: 1 + (debt + SATA notional) ÷ BTC value"
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
        cost_basis, average_cost, basis_source = _cost_basis(ticker, company, facts, extras)
        result[ticker] = CompanyExtras(
            ticker=ticker, amplification_pct=amp,
            amplification_x=amp_x, amplification_change_x=amp_change_x, amplification_source=amp_source,
            common_capital=metrics.net_common_capital, preferred_capital=metrics.net_preferred_capital,
            preferred_note=note, btc_bought=_n(facts.get("weekly_btc_purchases")), btc_held=current.btc_holdings,
            amplification_change_pp=amp - prior_amp if amp is not None and prior_amp is not None else None,
            btc_cost=btc_cost, btc_cost_source=cost_source, stated_dividends=stated,
            dividends=funding - btc_cost if funding is not None and btc_cost is not None else None,
            preferred_pct=current.preferred_claims / bitcoin * 100 if bitcoin and current.preferred_claims is not None else None,
            debt_pct=current.debt_principal / bitcoin * 100 if bitcoin and current.debt_principal is not None else None,
            net_leverage_pct=(current.debt_principal - liquid) / bitcoin * 100 if bitcoin and liquid is not None and current.debt_principal is not None else None,
            raised=raised, liquid_balance=liquid, liquid_change=liquid_change, liquid_detail=detail, net_funding=funding,
            reserve_months=months, target_months=target, target_kind="floor" if ticker == "MSTR" else "goal",
            coverage_years=years, breakeven_pct=breakeven, coverage_source=source,
            window=windows.get(ticker, {}), warrants=_warrants(ticker, company, facts, config, now),
            cost_basis=cost_basis, average_cost=average_cost, cost_source=basis_source,
            filing_url=next((row.get("primaryDocumentUrl") for row in reversed(rows) if row["ticker"] == ticker
                             and row["extracted"]["balanceDate"] == company.balance_date), None))
    period = report.capital_period_label.split("·")[-1].strip()
    kicker = f"THE DIGITAL CREDIT REPORT  ·  MONDAY  ·  8-K WEEK {period.upper()}"
    dates = " · ".join(f"{c.name} {_short(c.balance_date)}" for c in report.companies if c.balance_date)
    subtitle = f"What last week's filings did to each common share  ·  Balances: {dates}"
    notes = tuple(f"{t} data stale" for t in extras.get("stale", []) if t != "markets")  # markets: Friday test copy only
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
COST_BOX_H = 104   # test copy: the bitcoin cost box


def _cash_box(canvas, e, L, R, y, p, headline=None):
    """The cash balance and what it is made of (Strive: cash + STRC held)."""
    box = (L, y, R, y + CASH_BOX_H)
    canvas.draw.rounded_rectangle(box, radius=min(10, p.radius + 4), fill=p.cash)
    canvas.cells(box, [[(headline or _cash_line(e), T_LABEL, p.ink, False), (e.liquid_detail, T_MIN, p.muted, False)]],
                 inset=36)


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
    """C · Waterfall, read down: common + preferred ± cash = BTC + DIVs.

    One row per step, so every label and amount stays at phone size. Cash is
    labeled by direction: FROM CASH when the balance funded the week, TO CASH
    when part of the raise was kept (its bar steps back). BTC is the week's
    bitcoin cost; DIVs is the rest (dividends, interest and fees).
    """
    drawn = -e.liquid_change if e.liquid_change is not None else None
    sources = (("COMMON", e.common_capital), ("PREF", e.preferred_capital), (cash_step_label(e), drawn))
    if any(value is None for _, value in sources):
        canvas.text(L, y + 60, "Funding detail unavailable", T_BODY, p.muted)
        return
    steps, level = [], 0.0
    for n, (label, value) in enumerate(sources):
        # Raises carry their sign; cash is a plain amount (its label gives the direction).
        text = _money(value, signed=True) if n < 2 else _money(abs(value), signed=False)
        steps.append((label, text, level, level + value, p.soft if n == 2 else p.positive if value >= 0 else p.negative,
                      _tone_text(text, p) if n < 2 else p.ink))
        level += value
    if e.btc_cost is not None:
        rest = level - e.btc_cost
        steps.append(("BTC", _money(e.btc_cost, signed=False), 0.0, e.btc_cost, stripe, p.ink))
        steps.append(("DIVs", _money(rest, signed=False), e.btc_cost, level, mix(stripe, p.card, .45), p.ink))
    else:
        steps.append(("BTC + DIVs", _money(level, signed=False), 0.0, level, stripe, p.ink))
    row_h, gap = 50, 12
    label_w, value_w = 180, 146
    bx0, bx1 = L + label_w, R - value_w - 10
    points = [0.0] + [value for step in steps for value in step[2:4]]
    low, high = min(points), max(points)
    span = (high - low) or 1
    px = lambda v: bx0 + (v - low) / span * (bx1 - bx0)
    rows_y = [y + 2 + n * row_h + (gap if n >= 3 else 0) for n in range(len(steps))]
    canvas.draw.line((px(0), rows_y[0] + 2, px(0), rows_y[-1] + 48), fill=p.line, width=2)
    canvas.draw.line((L, rows_y[3] - gap / 2 - 1, R, rows_y[3] - gap / 2 - 1), fill=p.line, width=2)
    for n, (label, text, a, b, color, tone) in enumerate(steps):
        ry = rows_y[n]
        x0, x1 = sorted((px(a), px(b)))
        fill = color if isinstance(color, tuple) else mix(color, p.card, .85)  # DIVs arrives pre-tinted
        canvas.draw.rounded_rectangle((x0, ry + 8, max(x1, x0 + 4), ry + 42), radius=min(4, p.radius), fill=fill)
        # Center both texts on the bar (ry + 25) by their cap height, not the font box.
        canvas.text(L, ry + 25 - cap_middle(T_MIN), label, T_MIN, p.muted, True, max_width=label_w - 10)
        canvas.text(R, ry + 25 - cap_middle(T_LABEL), text, T_LABEL, tone, True, align="right", max_width=value_w)
        if n + 1 < len(steps) and steps[n + 1][2] == b:  # each step starts where the last one ended
            canvas.line([(px(b), ry + 42), (px(b), rows_y[n + 1] + 8)], p.soft, 2, dashed=True, dash=(4, 4))
    # The total carries down to where the uses end.
    canvas.line([(px(level), rows_y[2] + 42), (px(level), rows_y[-1] + 8)], p.soft, 2, dashed=True, dash=(4, 4))
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


def _times(value, signed=False):
    if value is None:
        return "—"
    if round(value, 2) == 0:
        return "0.00×"
    sign = "−" if value < 0 else "+" if signed else ""
    return f"{sign}{abs(value):.2f}×"


def _amplification(e: CompanyExtras) -> tuple[str, str]:
    """Each issuer's own ratio: Strategy's in ×, Strive's in %."""
    if e.amplification_x is not None:
        return _times(e.amplification_x), _times(e.amplification_change_x, True)
    return _pct(e.amplification_pct), _pct(e.amplification_change_pp, 2, True, " pp")


def _share_change(c: CompanyView):
    text = _clean(c.shares.change)
    # "+2.03m (+2.14%) WoW" → "+2.14%"
    if "(" in text and ")" in text:
        return text[text.index("(") + 1:text.index(")")]
    return text.replace(" WoW", "")


def _company(canvas: Canvas, c: CompanyView, e: CompanyExtras, report_company, index: int, theme, p, variant,
             btc_price=None):
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
    y = top + 168
    canvas.text(L, y, "BITCOIN BOUGHT", T_MIN, p.muted, True)
    canvas.text(R, y, "HELD", T_MIN, p.muted, True, align="right")
    canvas.text(L, y + 34, _btc(e.btc_bought, True), T_BIG + 8, p.ink, True, max_width=(R - L) * .6)
    canvas.text(R, y + 50, _btc(e.btc_held), T_VALUE - 4, p.ink, True, align="right", max_width=(R - L) * .4)
    y = top + 300
    TOPS.get(variant, _top_waterfall)(canvas, e, L, R, y, p, stripe)

    # Per share: value and weekly change.
    y += TOP_H + 36
    value_x = L + (R - L) * .74
    canvas.text(L, y, "PER SHARE", T_MIN, p.muted, True)
    canvas.text(R, y, "WEEK", T_MIN, p.muted, True, align="right")
    y += 44
    rows = (("BTC / share", _clean(c.bitcoin.value).replace(" sats", ""), c.bitcoin.short_change, True),
            ("NAV / share", _clean(c.nav_per_share), _clean(c.nav_change.value), True),
            ("Amplification", *_amplification(e), False),
            ("Shares", c.shares.value, _share_change(c), False))
    for label, value, delta, toned in rows:
        canvas.text(L, y + 6, label, T_BODY, p.ink, True, max_width=(R - L) * .36)
        canvas.text(value_x, y, value, T_VALUE - 2, p.ink, True, align="right", max_width=(R - L) * .38)
        canvas.text(R, y + 6, delta, T_BODY, _tone_text(delta, p) if toned else p.muted, True, align="right",
                    max_width=(R - L) * .25)
        y += ROW_H
    if e.warrants:
        w = e.warrants
        canvas.pill(L, y - 6, f"{w['count'] / 1e6:.1f}M WARRANTS @ ${w['strike']:.0f} · DUE {w['expires']:%b} {w['expires'].day}".upper(),
                    T_MIN, p.card, stripe, pad=(14, 6))
    y += 58

    # Coverage against each issuer's own target.
    box_h = 132
    radius = min(12, p.radius)
    canvas.draw.rounded_rectangle((L - 12, y, R + 12, y + box_h), radius=radius, fill=p.tint)
    on_target = e.reserve_months and e.target_months and e.reserve_months >= e.target_months - .5
    # Every cell carries a short note so the three stacks share one centered grid.
    cells = (("USD COVER", f"{e.reserve_months:.0f} mo" if e.reserve_months else "—", _cover_note(e),
              p.positive if on_target else p.soft, bool(on_target)),
             ("COVERAGE", f"{e.coverage_years:.0f} yrs" if e.coverage_years else "—", "of dividends", p.soft, False),
             ("BREAK-EVEN", f"{_pct(e.breakeven_pct, 2)}" if e.breakeven_pct else "—", "BTC gain / yr", p.soft, False))
    canvas.cells((L - 12, y, R + 12, y + box_h),
                 [[(label, T_MIN, p.muted, True), (value, T_VALUE - 4, p.ink, True), (note, T_MIN, color, bold)]
                  for label, value, note, color, bold in cells], gap=16)
    y += box_h + 20

    # What the bitcoin cost, and where the price sits against it.
    gain = btc_price / e.average_cost * 100 - 100 if btc_price and e.average_cost else None
    canvas.draw.rounded_rectangle((L - 12, y, R + 12, y + COST_BOX_H), radius=radius, fill=p.tint)
    cells = (("AVG COST", f"${e.average_cost:,.0f}" if e.average_cost else "—", p.ink),
             ("VS COST", _pct(gain, 1, True), _tone_text(_pct(gain, 1, True), p)),
             ("COST BASIS", _money(e.cost_basis, False), p.ink))
    canvas.cells((L - 12, y, R + 12, y + COST_BOX_H),
                 [[(label, T_MIN, p.muted, True), (value, T_VALUE - 4, color, True)] for label, value, color in cells])
    y += COST_BOX_H + 20

    # Growth: the same multi-week window for both companies, then QTD and YTD.
    weeks = e.window.get("weeks")
    columns = [(f"{weeks} WK" if weeks else "WK", _pct(e.window.get("btc"), 1, True) if weeks else "—",
                _pct(e.window.get("nav"), 1, True) if weeks else "—")]
    columns += [(period.period, _one_decimal(period.btc_growth), _one_decimal(period.nav_growth)) for period in c.periods[:2]]
    box_h = min(186, bottom - 28 - y)
    box = (L - 12, y, R + 12, y + box_h)
    canvas.draw.rounded_rectangle(box, radius=radius, fill=p.tint)
    table = [[("GROWTH", T_MIN, p.muted, True), ("BTC / share", T_BODY - 2, p.ink, True), ("NAV / share", T_BODY - 2, p.ink, True)]]
    table += [[(label, T_MIN, p.muted, True), (btc, T_BODY + 2, _tone_text(btc, p), True), (nav, T_BODY + 2, _tone_text(nav, p), True)]
              for label, btc, nav in columns]
    label_share = .36
    canvas.cells(box, table, gap=34, inset=8,
                 widths=[label_share] + [(1 - label_share) / len(columns)] * len(columns))


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
            _company(canvas, company, preview.extras[company.ticker], source, index, theme, p, variant,
                     preview.report.current_btc_price)
        png = canvas.save(metadata={"Title": "The Accretion Ledger", "Theme": theme.key, "Variant": variant})
    return png, canvas.overflows


def notes(preview: MondayPreview) -> list[str]:
    """Footnotes for the web page; the X image carries none."""
    sources = " · ".join(f"{e.ticker}: {e.coverage_source}" for e in preview.extras.values())
    windows = " · ".join(f"{e.ticker} since {_short(e.window['start'])}" for e in preview.extras.values() if e.window.get("start"))
    costs = " · ".join(f"{e.ticker}: {e.btc_cost_source}" for e in preview.extras.values() if e.btc_cost_source)
    stated = " ".join(f"Strategy's 8-K put the week's dividends and interest at {_money(e.stated_dividends, False)}; the "
                      "difference is rounding in its $0.01B balances." for e in preview.extras.values()
                      if e.ticker == "MSTR" and e.stated_dividends is not None)
    return [line for line in (
        "Capital raised = ATM issuance − repurchases, common and preferred. Cash is an existing balance, never counted as a raise. "
        "The waterfall reads down: common + preferred + cash drawn (or − cash kept) = BTC + DIVs. "
        "Strive's common figure is an estimate: net share change × prior-week VWAP.",
        f"BTC = the week's bitcoin purchase cost, fees included ({costs}). DIVs = the rest of the week's funding: preferred "
        f"dividends and interest, plus fees and other uses. {stated}".strip(),
        "Amplification uses each issuer's own formula, shown in ×. Strategy: BTC reserve ÷ net BTC reserve (BTC + USD − "
        "debt − preferred), its strategy.com KPI since July 23, 2026. Strive: 1 + (debt + SATA notional) ÷ BTC value, "
        "where the ratio is the \"Amplification Ratio\" on its treasury dashboard; Strive has no debt. "
        "The two measure different things and are not comparable. Weekly changes come from the filed balances.",
        "NAV, price/NAV, coverage and growth are estimates from dated balances and reconstructed preferred "
        "claims at the displayed prices; growth holds prices constant.",
        "USD cover = months of dividend (and, for Strategy, interest) obligations held in USD, read against Strategy's 12-month "
        "floor and Strive's 18-month goal. Coverage = (BTC + cash) ÷ annual obligations; break-even = obligations ÷ BTC value. "
        f"{sources}.",
        f"Multi-week growth window: {windows}." if windows else "",
        ("Avg cost = aggregate bitcoin purchase price ÷ BTC held, fees included; vs cost = BTC price ÷ avg cost − 1; "
         "cost basis = the aggregate purchase price. "
         + " · ".join(f"{e.ticker}: {e.cost_source}" for e in preview.extras.values() if e.cost_source) + "."),
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
            {"metric": f"{company.ticker} funding (raised + cash drawn)", "value": _money(extra.net_funding, False), "source": "derived"},
            {"metric": f"{company.ticker} BTC (bitcoin cost)", "value": _money(extra.btc_cost, False), "source": extra.btc_cost_source or "—"},
            {"metric": f"{company.ticker} DIVs (funding − BTC)", "value": _money(extra.dividends, False),
             "source": "derived" + (f"; 8-K dividends + interest {_money(extra.stated_dividends, False)}" if extra.stated_dividends is not None else "")},
            {"metric": f"{company.ticker} NAV / share (est.)", "value": _clean(company.nav_per_share), "source": "derived"},
            {"metric": f"{company.ticker} BTC cost basis / average", "value":
             f"{_money(extra.cost_basis, False)} / ${extra.average_cost:,.0f}" if extra.average_cost else "—",
             "source": extra.cost_source or "—"},
            {"metric": f"{company.ticker} price / basic NAV", "value": _clean(company.price_to_nav), "source": "derived"},
            {"metric": f"{company.ticker} sats per share", "value": company.bitcoin.value, "source": "derived"},
            {"metric": f"{company.ticker} amplification ({'BTC reserve ÷ net BTC reserve' if company.ticker == 'MSTR' else '(debt + SATA notional) ÷ BTC value'})",
             "value": " / ".join(_amplification(extra)), "source": extra.amplification_source},
            {"metric": f"{company.ticker} USD cover (months)", "value": f"{extra.reserve_months:.1f} ({_cover_note(extra)})" if extra.reserve_months else "—", "source": extra.coverage_source},
            {"metric": f"{company.ticker} {extra.window.get('weeks', '?')}-week BTC/share", "value": _pct(extra.window.get("btc"), 2, True), "source": f"since {extra.window.get('start', '—')}"},
            {"metric": f"{company.ticker} QTD BTC/share", "value": next((_clean(p.btc_growth) for p in company.periods if p.period == "QTD"), "—"), "source": "derived"},
        ]
    return rows
