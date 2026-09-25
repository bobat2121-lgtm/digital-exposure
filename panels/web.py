"""The live web page for the three reports: dense and responsive (desktop and
phone), built from the same data as the X images. The PNG panels stay the
downloads; this layout is for people reading the site.

Everything is Neon Ledger. Text wears ink tokens; company colors mark identity
only. Chart colors are the brand hues stepped for the dark surface and checked
with the data-viz palette validator (Strategy #12A6C1, Strive #C43596: every
check passes on #0C1324). Each chart has a tooltip and a table twin elsewhere on
the page, and each report ends with its formulas.
"""
from __future__ import annotations

from datetime import date
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from . import friday_preview as fri
from . import monday_preview as mon
from . import wednesday as wed

BG, CARD, CARD2, LINE, OUTLINE = "#060A14", "#0C1324", "#101B31", "#1B2842", "#1C2B4A"
INK, MUTED, SOFT = "#E8F1FF", "#8FA2CC", "#5D6E96"
CYAN, MAGENTA, AMBER, GREEN, RED, YELLOW = "#22E3FF", "#FF3DCB", "#FFC23D", "#3DFFA2", "#FF4D7A", "#FFE14D"
# Chart steps of the company hues (validated on the dark card surface).
SERIES = {"MSTR": "#12A6C1", "ASST": "#C43596", "STRC": "#12A6C1", "SATA": "#C43596"}
DAY = {"monday": CYAN, "wednesday": MAGENTA, "friday": AMBER}
FONT = "Chakra Petch"

CSS = """
@font-face { font-family: 'Chakra Petch'; font-weight: 400 500; font-display: swap; src: url('app/static/chakrapetch-regular.ttf') format('truetype'); }
@font-face { font-family: 'Chakra Petch'; font-weight: 600 800; font-display: swap; src: url('app/static/chakrapetch-bold.ttf') format('truetype'); }
@font-face { font-family: 'Orbitron'; font-weight: 400 900; font-display: swap; src: url('app/static/orbitron-variable.ttf') format('truetype'); }
:root { color-scheme: dark; }
.stApp { background: radial-gradient(1200px 500px at 15% -10%, #0E1A33 0%, #060A14 60%) fixed; color: #E8F1FF;
  font-family: 'Chakra Petch', system-ui, sans-serif; }
.stApp p, .stApp li, .stApp label, .stApp td, .stApp th, .stApp button p { font-family: 'Chakra Petch', system-ui, sans-serif; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { visibility: hidden; }
.stMainBlockContainer { max-width: 1640px; padding: 18px 28px 40px; }
.stApp a { color: #22E3FF; }
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"] { color: #E8F1FF; }
[data-testid="stCaptionContainer"] { color: #8FA2CC; }
/* Report tabs */
.st-key-panel_tabs [role="tablist"] { gap: 6px; border-bottom: 1px solid #1C2B4A; position: sticky; top: 0; z-index: 50;
  background: rgba(6,10,20,.92); backdrop-filter: blur(6px); padding-top: 4px; }
.st-key-panel_tabs [role="tab"] { color: #8FA2CC; background: transparent; border-radius: 10px 10px 0 0; padding: 10px 18px; }
.st-key-panel_tabs [role="tab"] p { font-size: 15px; font-weight: 600; letter-spacing: .02em; }
.st-key-panel_tabs [role="tab"]:hover { color: #E8F1FF; background: #0C1324; }
.st-key-panel_tabs [role="tab"][aria-selected="true"] { color: #E8F1FF; background: #0C1324; }
.st-key-panel_tabs .react-aria-SelectionIndicator { background: #22E3FF; height: 3px; }
/* Cards are bordered containers */
[data-testid="stVerticalBlockBorderWrapper"] { background: #0C1324; border: 1px solid #1C2B4A !important; border-radius: 16px; }
/* Buttons and expanders */
[data-testid="stButton"] button, [data-testid="stDownloadButton"] button, [data-testid="stPopover"] button {
  color: #E8F1FF; background: #101B31; border: 1px solid #1C2B4A; border-radius: 10px; }
[data-testid="stButton"] button:hover, [data-testid="stDownloadButton"] button:hover,
[data-testid="stPopover"] button:hover { border-color: #22E3FF; color: #E8F1FF; background: #101B31; }
[data-testid="stPopoverBody"] { background: #0C1324; border: 1px solid #1C2B4A; }
[data-testid="stExpander"] { background: #0C1324; border: 1px solid #1C2B4A; border-radius: 14px; }
[data-testid="stExpander"] summary { color: #E8F1FF; background: #0C1324; border-radius: 14px; }
[data-testid="stExpander"] summary:hover { background: #101B31; }
[data-testid="stExpander"] summary p { font-weight: 600; }
/* Report blocks */
.dcr-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 6px 18px; margin: 6px 0 2px; }
.dcr-kicker { font-size: 13px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
.dcr-title { font-family: 'Orbitron', 'Chakra Petch', sans-serif; font-weight: 900; font-size: clamp(26px, 4.2vw, 46px);
  letter-spacing: .02em; line-height: 1.05; text-transform: uppercase; color: #E8F1FF; margin: 2px 0 4px; }
.dcr-title em { font-style: normal; text-shadow: 0 0 18px currentColor; }
.dcr-sub { color: #8FA2CC; font-size: 15px; }
.dcr-sub b { color: #E8F1FF; font-weight: 700; }
.dcr-card-h { display: flex; align-items: baseline; justify-content: space-between; gap: 8px 14px; flex-wrap: wrap; }
.dcr-card-h .n { font-size: 24px; font-weight: 700; color: #E8F1FF; }
.dcr-card-h .t { font-size: 14px; color: #8FA2CC; margin-left: 8px; }
.dcr-card-h .p { font-size: 24px; font-weight: 700; color: #E8F1FF; }
.dcr-bar { height: 4px; border-radius: 3px; margin: -2px 0 10px; }
.dcr-h { font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: #8FA2CC; margin: 12px 0 6px; }
.dcr-meta { color: #8FA2CC; font-size: 13.5px; }
.dcr-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(var(--min, 140px), 1fr)); gap: 8px; }
.dcr-tile { background: #101B31; border-radius: 12px; padding: 10px 12px 11px; text-align: center; min-width: 0; }
.dcr-tile .l { font-size: 11.5px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; color: #8FA2CC; }
.dcr-tile .v { font-size: 22px; font-weight: 700; color: #E8F1FF; line-height: 1.25; margin-top: 2px; }
.dcr-tile .s { font-size: 12.5px; color: #8FA2CC; margin-top: 1px; }
.dcr-big .v { font-size: 34px; }
.pos { color: #3DFFA2 !important; } .neg { color: #FF4D7A !important; } .warn { color: #FFE14D !important; }
.dcr-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
table.dcr { width: 100%; border-collapse: collapse; font-size: 14.5px; font-variant-numeric: tabular-nums; }
table.dcr th { color: #8FA2CC; font-size: 11.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  text-align: right; padding: 7px 8px; border-bottom: 1px solid #1C2B4A; white-space: nowrap; }
table.dcr td { color: #E8F1FF; text-align: right; padding: 7px 8px; border-bottom: 1px solid #16223A; white-space: nowrap; }
table.dcr th:first-child, table.dcr td:first-child { text-align: left; }
table.dcr td.w { white-space: normal; }
table.dcr tr.sec td { color: #8FA2CC; font-size: 11.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  padding-top: 13px; border-bottom: 1px solid #1C2B4A; }
table.dcr td .sub { display: block; color: #8FA2CC; font-size: 12px; }
table.dcr tr:hover td { background: #101B31; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 7px; vertical-align: 1px; }
.chip { display: inline-block; white-space: nowrap; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; letter-spacing: .06em; color: #060A14; }
.dcr-list { margin: 4px 0 0; padding-left: 18px; color: #E8F1FF; font-size: 14px; }
.dcr-list li { margin: 2px 0; }
.dcr-formulas dt { color: #E8F1FF; font-weight: 700; margin-top: 10px; font-size: 14.5px; }
.dcr-formulas dd { color: #B7C6E6; margin: 2px 0 0 0; font-size: 14px; }
.dcr-formulas h4 { color: #8FA2CC; font-size: 12px; letter-spacing: .12em; text-transform: uppercase; margin: 16px 0 0; }
@media (max-width: 640px) {
  .stMainBlockContainer { padding: 10px 12px 28px; }
  .st-key-panel_tabs [role="tab"] { padding: 8px 6px; flex: 1; height: auto; min-height: 44px; }
  .st-key-panel_tabs [role="tab"] p { font-size: 12.5px; white-space: normal; text-align: center; line-height: 1.25; }
  table.dcr td .sub { white-space: normal; }
  .dcr-tile .v { font-size: 19px; } .dcr-big .v { font-size: 27px; }
  table.dcr { font-size: 13px; } table.dcr th, table.dcr td { padding: 6px 5px; }
  .dcr-card-h .n, .dcr-card-h .p { font-size: 20px; }
}
"""


# ── small builders ──────────────────────────────────────────────────────────
def style() -> None:
    st.html(f"<style>{CSS}</style>")


def _tone(text: str) -> str:
    stripped = str(text).replace("≈", "").strip()
    return "pos" if stripped.startswith("+") else "neg" if stripped.startswith("−") else ""


def tiles(items, min_width=140, big=False) -> str:
    """items: (label, value, sub, toned) — toned colors the value by its sign."""
    cells = []
    for label, value, sub, toned in items:
        tone = _tone(value) if toned else ""
        cells.append(f'<div class="dcr-tile{" dcr-big" if big else ""}"><div class="l">{escape(label)}</div>'
                     f'<div class="v {tone}">{escape(str(value))}</div>'
                     + (f'<div class="s">{sub}</div>' if sub else "") + "</div>")
    return f'<div class="dcr-tiles" style="--min:{min_width}px">{"".join(cells)}</div>'


def table(columns, rows, toned=(), left=(0,), wrap=(0,)) -> str:
    """rows: list of cells, or ("section", title) for a section divider. ``left`` columns align left;
    ``wrap`` columns (text) may wrap on phones, the rest (numbers) never break."""
    align = lambda index: ' style="text-align:left"' if index in left else ""
    head = "".join(f"<th{align(index)}>{escape(column)}</th>" for index, column in enumerate(columns))
    body = []
    for row in rows:
        if isinstance(row, tuple) and len(row) == 2 and row[0] == "section":
            body.append(f'<tr class="sec"><td colspan="{len(columns)}">{escape(row[1])}</td></tr>')
            continue
        cells = []
        for index, cell in enumerate(row):
            html = cell if isinstance(cell, Html) else escape(str(cell))
            tone = _tone(cell) if index in toned and not isinstance(cell, Html) else ""
            classes = " ".join(name for name in (tone, "w" if index in wrap else "") if name)
            cells.append(f'<td class="{classes}"{align(index)}>{html}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="dcr-scroll"><table class="dcr"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


class Html(str):
    """A table cell that is already HTML."""


def _nb(text) -> str:
    """Keep a short label on one line (dates, tickers, day counts) when table cells wrap on phones."""
    return str(text).replace(" ", "\u00a0")


def value_with(value, sub) -> Html:
    tone = _tone(sub)
    return Html(f'{escape(str(value))}<span class="sub {tone}">{escape(str(sub))}</span>' if sub else escape(str(value)))


def header(day: str, kicker: str, words: tuple[str, str, str], sub: str) -> None:
    color = DAY[day]
    st.html(f'<div class="dcr-kicker" style="color:{color}">{escape(kicker)}</div>'
            f'<div class="dcr-title">{escape(words[0])}<em style="color:{color}">{escape(words[1])}</em>{escape(words[2])}</div>'
            f'<div class="dcr-sub">{sub}</div>')


def heading_html(text: str, right: str = "") -> str:
    right_html = f'<span style="float:right;text-transform:none;letter-spacing:0;font-weight:500">{escape(right)}</span>' if right else ""
    return f'<div class="dcr-h">{escape(text)}{right_html}</div>'


def heading(text: str, right: str = "") -> None:
    st.html(heading_html(text, right))


def formulas(sections) -> None:
    """The collapsible formula list at the bottom of each report."""
    with st.expander("Formulas", icon=":material/function:"):
        html = []
        for title, items in sections:
            html.append(f"<h4>{escape(title)}</h4><dl>")
            html += [f"<dt>{escape(term)}</dt><dd>{escape(text)}</dd>" for term, text in items]
            html.append("</dl>")
        st.html(f'<div class="dcr-formulas">{"".join(html)}</div>')


def sources(footnotes, audit) -> None:
    with st.expander("Sources, notes and audit values", icon=":material/fact_check:"):
        st.html('<ul class="dcr-list">' + "".join(f"<li>{escape(line)}</li>" for line in footnotes) + "</ul>")
        if audit:
            st.html(table(("Value", "Shown", "Source"), [(row["metric"], row["value"], row["source"]) for row in audit],
                          left=(0, 1, 2), wrap=(0, 1, 2)))


def _chart(chart, height):
    return (chart.properties(height=height)
            .configure(background="transparent", font=FONT)
            .configure_view(stroke=None)
            .configure_axis(gridColor=LINE, domainColor=OUTLINE, tickColor=OUTLINE, labelColor=MUTED, titleColor=MUTED,
                            labelFontSize=12, titleFontSize=12, titleFontWeight=600)
            .configure_legend(labelColor=INK, titleColor=MUTED, orient="top", labelFontSize=12, symbolStrokeWidth=3)
            .configure_title(color=MUTED, fontSize=12, anchor="start"))


def show(chart, height=220) -> None:
    st.altair_chart(_chart(chart, height), theme=None, width="stretch")


def _m(value, digits=1, signed=False):
    return mon._money(value, signed=signed, digits=digits)


# ── Monday ──────────────────────────────────────────────────────────────────
def monday(preview, *, notices=()) -> None:
    view = preview.view
    stamp = view.report_time.replace("Updated ", "", 1)
    header("monday", "Digital Credit Report · Monday", ("The ", "Accretion", " Ledger"),
           f"<b>{escape(preview.period)}</b> · BTC <b>{escape(view.btc_price)}</b> · {escape(stamp)} · "
           "what last week's filings did to each common share")
    for notice in notices:
        st.caption(notice)
    companies = list(view.companies)
    columns = st.columns(len(companies), gap="medium")
    for column, company in zip(columns, companies):
        source = next(item for item in preview.report.companies if item.ticker == company.ticker)
        with column, st.container(border=True, key=f"mon_{company.ticker}"):
            _monday_company(company, preview.extras[company.ticker], source, preview.report.current_btc_price)
    left, right = st.columns(2, gap="medium")
    first, second = _scorecard(preview)
    with left, st.container(border=True, key="mon_scorecard"):
        st.html(heading_html("Side by side", "this week · change") + first)
    with right, st.container(border=True, key="mon_scorecard_2"):
        st.html(heading_html("Coverage, cost and growth") + second)


def _monday_company(c, e, source, btc_price) -> None:
    color = SERIES[c.ticker]
    link = f' · <a href="{escape(e.filing_url)}" target="_blank">8-K</a>' if e.filing_url else ""
    st.html(f'<div class="dcr-bar" style="background:{DAY["monday"] if c.ticker == "MSTR" else MAGENTA}"></div>'
            f'<div class="dcr-card-h"><div><span class="n">{escape(c.name)}</span><span class="t">{escape(c.ticker)}</span></div>'
            f'<div class="p">{escape(c.stock_price)}</div></div>'
            f'<div class="dcr-meta">Balance {escape(mon._short(source.balance_date))}{link} · '
            f'<b style="color:{INK}">{escape(mon._clean(c.price_to_nav))}</b> NAV</div>')
    paid = e.btc_cost / e.btc_bought if e.btc_cost and e.btc_bought else None
    st.html(tiles((
        ("Bitcoin bought", mon._btc(e.btc_bought, True), "", True),
        ("Held", mon._btc(e.btc_held), "", False),
        ("Price paid", f"${paid:,.0f}" if paid else "—", "per BTC this week", False),
        ("Cash on hand", _m(e.liquid_balance, 2), escape(e.liquid_detail), False),
    ), min_width=130))
    heading("Funding → where it went", "8-K week")
    _waterfall(e, color)
    lines = [*c.common.details[:2], *c.preferred.details[:3]]
    st.html(heading_html("Filing detail") + '<ul class="dcr-list">'
            + "".join(f"<li>{escape(line)}</li>" for line in lines if line) + "</ul>")


def _waterfall(e, color) -> None:
    drawn = -e.liquid_change if e.liquid_change is not None else None
    steps = [("COMMON", e.common_capital, "raise"), ("PREF", e.preferred_capital, "raise"),
             (mon.cash_step_label(e), drawn, "cash")]
    if any(value is None for _, value, _ in steps):
        st.caption("Funding detail unavailable")
        return
    rows, level = [], 0.0
    for label, value, kind in steps:
        shown = mon._money(value, signed=True) if kind == "raise" else mon._money(abs(value), signed=False)
        rows.append({"step": f"{label}  {shown}", "start": level / 1e6, "end": (level + value) / 1e6, "amount": shown,
                     "kind": "raise+" if kind == "raise" and value >= 0 else "raise−" if kind == "raise" else "cash"})
        level += value
    if e.btc_cost is not None:
        rows.append({"step": f"BTC  {mon._money(e.btc_cost, signed=False)}", "start": 0, "end": e.btc_cost / 1e6,
                     "amount": mon._money(e.btc_cost, signed=False), "kind": "btc"})
        rows.append({"step": f"DIVs  {mon._money(level - e.btc_cost, signed=False)}", "start": e.btc_cost / 1e6,
                     "end": level / 1e6, "amount": mon._money(level - e.btc_cost, signed=False), "kind": "divs"})
    frame = pd.DataFrame(rows)
    order = list(frame["step"])
    colors = alt.Scale(domain=["raise+", "raise−", "cash", "btc", "divs"], range=[GREEN, RED, SOFT, color, "#6E3A63" if color == SERIES["ASST"] else "#1F6674"])
    bars = alt.Chart(frame).mark_bar(cornerRadius=4, height=22).encode(
        y=alt.Y("step:N", sort=order, title=None, axis=alt.Axis(labelFontSize=13, labelColor=INK, labelFontWeight=600, ticks=False, domain=False)),
        x=alt.X("start:Q", title="$ millions", axis=alt.Axis(grid=True, tickCount=5)), x2="end:Q",
        color=alt.Color("kind:N", scale=colors, legend=None),
        tooltip=[alt.Tooltip("step:N", title="Step"), alt.Tooltip("amount:N", title="Amount")])
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=OUTLINE, strokeWidth=2).encode(x="x:Q")
    show(bars + zero, height=36 * len(rows))


def _scorecard(preview) -> str:
    extras = [preview.extras[c.ticker] for c in preview.view.companies]
    views = list(preview.view.companies)
    btc_price = preview.report.current_btc_price

    def row(label, cells):
        return [label, *cells]

    def gain(e):
        return mon._pct(btc_price / e.average_cost * 100 - 100, 1, True) if e.average_cost and btc_price else "—"

    rows = [("section", "Bitcoin and funding")]
    later = []
    rows.append(row("Bitcoin bought", [mon._btc(e.btc_bought, True) for e in extras]))
    rows.append(row("Bitcoin held", [mon._btc(e.btc_held) for e in extras]))
    rows.append(row("Capital raised (common + preferred)", [_m(e.raised, signed=True) for e in extras]))
    rows.append(row("Cash drawn (+) / kept (−)", [_m(-e.liquid_change if e.liquid_change is not None else None, signed=True) for e in extras]))
    rows.append(row("BTC: bitcoin cost", [_m(e.btc_cost) for e in extras]))
    rows.append(row("DIVs: dividends, interest, fees", [_m(e.dividends) for e in extras]))
    rows.append(row("Cash on hand", [value_with(_m(e.liquid_balance, 2), e.liquid_detail) for e in extras]))
    rows.append(("section", "Per share"))
    rows.append(row("BTC / share (sats)", [value_with(mon._clean(c.bitcoin.value).replace(" sats", ""), c.bitcoin.short_change) for c in views]))
    rows.append(row("NAV / share", [value_with(mon._clean(c.nav_per_share), mon._clean(c.nav_change.value)) for c in views]))
    rows.append(row("Price / NAV", [mon._clean(c.price_to_nav) for c in views]))
    rows.append(row("Amplification", [value_with(*mon._amplification(e)) for e in extras]))
    rows.append(row("Shares", [value_with(c.shares.value, mon._share_change(c)) for c in views]))
    rows, later = later, rows
    rows.append(("section", "Coverage"))
    rows.append(row("USD cover", [value_with(f"{e.reserve_months:.0f} mo" if e.reserve_months else "—", mon._cover_note(e)) for e in extras]))
    rows.append(row("Coverage (BTC + cash ÷ dividends)", [f"{e.coverage_years:.0f} yrs" if e.coverage_years else "—" for e in extras]))
    rows.append(row("Break-even BTC gain / yr", [mon._pct(e.breakeven_pct, 2) if e.breakeven_pct else "—" for e in extras]))
    rows.append(("section", "Bitcoin cost"))
    rows.append(row("Average cost", [f"${e.average_cost:,.0f}" if e.average_cost else "—" for e in extras]))
    rows.append(row("BTC price vs cost", [gain(e) for e in extras]))
    rows.append(row("Cost basis", [_m(e.cost_basis, 2) for e in extras]))
    rows.append(("section", "Growth"))
    weeks = extras[0].window.get("weeks")
    rows.append(row(f"{weeks}-week BTC / share" if weeks else "Multi-week BTC / share", [mon._pct(e.window.get("btc"), 1, True) for e in extras]))
    rows.append(row(f"{weeks}-week NAV / share" if weeks else "Multi-week NAV / share", [mon._pct(e.window.get("nav"), 1, True) for e in extras]))
    for index, label in enumerate(("QTD", "YTD")):
        rows.append(row(f"{label} BTC / share", [mon._one_decimal(c.periods[index].btc_growth) if len(c.periods) > index else "—" for c in views]))
        rows.append(row(f"{label} NAV / share", [mon._one_decimal(c.periods[index].nav_growth) if len(c.periods) > index else "—" for c in views]))
    head = ("", *(c.ticker for c in views))
    return table(head, later, toned=(1, 2)), table(head, rows, toned=(1, 2))


MONDAY_FORMULAS = (
    ("Funding", (
        ("Capital raised", "ATM net proceeds − repurchase cost, common and preferred, from each weekly 8-K. Strive's "
                           "common figure is an estimate: net share change × prior-week VWAP."),
        ("Cash drawn / kept", "Liquid assets last week − this week. Strategy: USD Reserve + USD Cash. Strive: cash + the STRC it holds."),
        ("Waterfall", "Common + preferred + cash drawn (or − cash kept) = BTC + DIVs."),
        ("BTC", "The week's bitcoin purchase cost, fees included: Strategy's 8-K \"Aggregate Purchase Price\"; "
                "Strive's dashboard purchase cost."),
        ("DIVs", "Funding − BTC: preferred dividends, interest, fees and other uses."),
        ("Price paid", "BTC ÷ bitcoin bought."),
    )),
    ("Per share", (
        ("BTC / share (sats)", "BTC held × 100,000,000 ÷ effective common shares."),
        ("NAV", "BTC held × BTC price + cash − debt − preferred claims."),
        ("NAV / share, price / NAV", "NAV ÷ effective common shares; share price ÷ NAV per share."),
        ("Amplification, Strategy", "BTC reserve ÷ net BTC reserve = BTC value ÷ (BTC value + USD − debt − preferred), "
                                    "strategy.com's KPI since July 23, 2026."),
        ("Amplification, Strive", "1 + (debt + SATA notional) ÷ BTC value; the ratio is Strive's dashboard "
                                  "\"Amplification Ratio\". The two are not comparable."),
        ("Weekly changes", "This week's balances vs last week's, each at its own week's BTC price (growth rows hold prices constant)."),
    )),
    ("Coverage", (
        ("USD cover (months)", "USD held ÷ monthly dividend obligations (Strategy's include interest), against Strategy's "
                               "12-month floor and Strive's 18-month goal."),
        ("Coverage (years)", "(BTC value + cash) ÷ annual obligations."),
        ("Break-even", "Annual obligations ÷ BTC value: the yearly BTC gain that pays them."),
    )),
    ("Bitcoin cost", (
        ("Average cost", "Aggregate purchase price ÷ BTC held, fees included."),
        ("BTC price vs cost", "BTC price ÷ average cost − 1."),
        ("Cost basis", "The aggregate purchase price of all BTC held."),
    )),
    ("Growth", (
        ("Multi-week, QTD, YTD", "Change in BTC / share or NAV / share from the window's first filing, at today's prices. "
                                 "The multi-week window uses the same number of filings for both companies."),
    )),
)


# ── Wednesday ───────────────────────────────────────────────────────────────
def wednesday(data, *, notices=()) -> None:
    stamp = data.get("stamp")
    refs = " · ".join(f"{label} <b>{wed._pct(value)}</b>" for label, (_, value) in data["references"])
    header("wednesday", "Digital Credit Report · Wednesday", ("The ", "Coupon", " Sheet"),
           f"{refs}{' · closes through ' + escape(wed._short(stamp)) if stamp else ''}")
    for notice in notices:
        st.caption(notice)
    columns = st.columns(2, gap="medium")
    for column, ticker in zip(columns, wed.HEROES):
        with column, st.container(border=True, key=f"wed_{ticker}"):
            _wednesday_hero(ticker, data)
    with st.container(border=True, key="wed_ladder"):
        heading("The ladder", "spreads in bp over each benchmark")
        st.html(_ladder(data))
    left, right = st.columns((5, 6), gap="medium")
    with left, st.container(border=True, key="wed_calendar"):
        heading("Calendar", "days away")
        today = data["now"].date()
        st.html(table(("Date", "Event", "Days"),
                      [(_nb(wed._short(day)), label, (date.fromisoformat(day) - today).days) for day, label, _ in data["calendar"]],
                      left=(0, 1), wrap=(1,)))
    with right, st.container(border=True, key="wed_flow"):
        heading("Flow ledger", "+ issued / − repurchased")
        st.html(_flow(data["ledger"]))


def _wednesday_hero(ticker, data) -> None:
    hero, color = data["heroes"][ticker], SERIES[ticker]
    item, par, liquidity = hero["item"], hero["par"], hero["liquidity"]
    headline = data["headline"]
    diff = item.price - 100 if item.price is not None else None
    vs_par = (f'<span class="{"pos" if diff >= 0 else "neg"}">{"+" if diff >= 0 else "−"}${abs(diff):.2f} vs par</span>'
              if diff is not None else "")
    st.html(f'<div class="dcr-bar" style="background:{CYAN if ticker == "STRC" else MAGENTA}"></div>'
            f'<div class="dcr-card-h"><div><span class="n">{ticker}</span><span class="t">{wed.ISSUER[ticker]} · '
            f'{wed.KIND.get(ticker, "")}</span></div><div class="p">${item.price:,.2f}</div></div>'
            f'<div class="dcr-meta">{vs_par}</div>')
    backing = dict((data.get("backing") or {}).get(ticker, {}).get("cells") or ())
    st.html(tiles((
        (f"Spread over {headline}", wed._bp(hero["spreads"].get(headline)), "", False),
        ("Effective yield", wed._pct(item.effective), f"stated {wed._pct(item.rate)} on $100", False),
    ), min_width=180, big=True))
    heading("Spread stack", "bp")
    frame = pd.DataFrame([{"benchmark": f"{wed.SHORT[label]}  {wed._bp(hero['spreads'].get(label)).replace(' bp', '')}",
                           "bp": hero["spreads"].get(label) or 0, "key": label == headline} for label, _ in wed.BENCHMARKS])
    stack = alt.Chart(frame).mark_bar(cornerRadius=4, height=18).encode(
        y=alt.Y("benchmark:N", sort=list(frame["benchmark"]), title=None,
                axis=alt.Axis(labelColor=INK, labelFontSize=13, ticks=False, domain=False)),
        x=alt.X("bp:Q", title="basis points", axis=alt.Axis(tickCount=5)),
        color=alt.condition("datum.key", alt.value(color), alt.value("#2B3A5C")),
        tooltip=[alt.Tooltip("benchmark:N", title="Over"), alt.Tooltip("bp:Q", title="Spread (bp)", format=",.0f")])
    show(stack, height=170)
    history = hero["history"]
    if len(history) > 2:
        heading(f"Spread over {headline} · 26 weeks", f"{min(v for _, v in history):,.0f}–{max(v for _, v in history):,.0f} bp")
        frame = pd.DataFrame({"date": pd.to_datetime([d for d, _ in history]), "bp": [v for _, v in history]})
        base = alt.Chart(frame).encode(x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %-d", tickCount=6)))
        line = base.mark_line(color=color, strokeWidth=2).encode(y=alt.Y("bp:Q", title="bp", scale=alt.Scale(zero=False)))
        hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False)
        points = base.mark_point(color=color, size=60, filled=True).encode(
            y="bp:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
            tooltip=[alt.Tooltip("date:T", title="Date", format="%b %-d, %Y"), alt.Tooltip("bp:Q", title="Spread (bp)", format=",.0f")]
        ).add_params(hover)
        show(line + points, height=190)
    at = par.get("at_par_20")
    cut = ""
    if ticker == "SATA" and par.get("prior_avg"):
        allowed = par["prior_avg"] >= 99
        cut = (f'<div class="dcr-meta" style="margin-top:8px">Rate cut <b style="color:{INK}">{"allowed" if allowed else "blocked"}</b>: '
               f'{par["prior_month"]:%B} closes averaged ${par["prior_avg"]:.2f} (a cut needs ≥ $99).</div>')
    st.html(tiles((
        ("≥ $100", f"{at}/{par.get('sessions')} days" if at is not None else "—", "last 20 closes", False),
        ("30D volume", wed._money(liquidity.get("adv"), 0) + "/d" if liquidity.get("adv") else "—", "", False),
        ("Size", wed._money(liquidity.get("notional")), "notional", False),
        ("BTC floor", backing.get("BTC FLOOR", "—"), "claims through this series", False),
        ("Stated rate", backing.get("STATED RATE", "—"), "", False),
        (next((label for label in backing if label.endswith("AVG")), "Prior avg").title(),
         next((value for label, value in backing.items() if label.endswith("AVG")), "—"), "prior-month close", False),
    ), min_width=170) + cut)
    cover = data["cover"]["MSTR" if ticker == "STRC" else "ASST"]
    heading(f"{cover['name']} USD cover", f"{cover['current']:.0f} mo · {cover['kind']} {cover['target']:.0f} mo"
            if cover["current"] and cover["target"] else "")
    if cover["weeks"]:
        frame = pd.DataFrame({"week": pd.to_datetime([d for d, _ in cover["weeks"]]), "months": [m for _, m in cover["weeks"]]})
        bars = alt.Chart(frame).mark_bar(color=color, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=18).encode(
            x=alt.X("week:T", title=None, axis=alt.Axis(format="%b %-d", tickCount=6)),
            y=alt.Y("months:Q", title="months"),
            tooltip=[alt.Tooltip("week:T", title="Balance date", format="%b %-d"), alt.Tooltip("months:Q", title="Months", format=".1f")])
        target = alt.Chart(pd.DataFrame({"t": [cover["target"]]})).mark_rule(color=AMBER, strokeDash=[6, 4], strokeWidth=2).encode(y="t:Q")
        show(bars + target, height=160)


def _ladder(data) -> str:
    heroes = data["heroes"]
    items = {item.ticker: item for item in data["ladder"]}
    liquidity = data["liquidity"]
    rows = []
    for ticker in (*wed.HEROES, *wed.REST):
        item = items.get(ticker)
        if item is None:
            continue
        spreads = heroes[ticker]["spreads"] if ticker in heroes else next(r["spreads"] for r in data["rest"] if r["item"].ticker == ticker)
        currency = "€" if item.currency == "EUR" else "$"
        dot = Html(f'<span style="white-space:nowrap"><span class="dot" style="background:'
                   f'{SERIES["STRC"] if ticker != "SATA" else SERIES["SATA"]}"></span>{ticker}</span>')
        rows.append((dot, f"{currency}{item.price:,.2f}" if item.price else "—", wed._pct(item.rate), wed._pct(item.effective),
                     *(wed._bp(spreads.get(label)).replace(" bp", "") for label, _ in wed.BENCHMARKS),
                     wed._money((liquidity.get(ticker) or {}).get("adv"), 0) if (liquidity.get(ticker) or {}).get("adv") else "—",
                     wed._money((liquidity.get(ticker) or {}).get("notional"))))
    columns = ("Series", "Price", "Stated", "Eff. yield", *(f"vs {wed.SHORT[label]}" for label, _ in wed.BENCHMARKS), "30D $ vol", "Size")
    return table(columns, rows, toned=(4, 5, 6, 7, 8))


def _flow(ledger) -> str:
    rows, totals = [], {"strc": 0, "other": 0, "mstr": 0, "sata": 0}
    for entry in ledger:
        rows.append((_nb(wed._short(entry["week"])), wed._money(entry.get("strc"), signed=True), wed._money(entry.get("other"), signed=True),
                     wed._money(entry.get("mstr"), signed=True), wed._money(entry.get("sata"), signed=True),
                     f"{(entry.get('mstr_btc') or 0):,.0f}", f"{(entry.get('asst_btc') or 0):,.0f}"))
        for key in totals:
            totals[key] += entry.get(key) or 0
    rows.append(("section", f"{len(ledger)} weeks"))
    rows.append(("Total", *(wed._money(totals[key], signed=True) for key in ("strc", "other", "mstr", "sata")),
                 f"{sum(e.get('mstr_btc') or 0 for e in ledger):,.0f}", f"{sum(e.get('asst_btc') or 0 for e in ledger):,.0f}"))
    return table(("Week of", "STRC", "STRF/K/D/E", "MSTR ATM", "SATA", "MSTR BTC", "ASST BTC"), rows, toned=(1, 2, 3, 4))


WEDNESDAY_FORMULAS = (
    ("Yields and spreads", (
        ("Effective yield", "Stated rate × $100 ÷ price."),
        ("Stated rate", "The annual dividend on $100 par. SATA's is Strive's stated rate; its daily dividend is the rate ÷ 12 "
                        "split over the month's business days."),
        ("Spread", "(Effective yield − benchmark yield) × 100, in basis points. Headline benchmark: the 3-month T-bill."),
        ("Benchmarks", "SOFR and EFFR from the NY Fed; the 3-month bill and 10-year from Treasury's daily par curve "
                       "(FRED for history); ICE BofA US Corporate (IG) and High Yield effective yields from FRED."),
        ("26-week history", "Each day's close, the stated rate in effect that day and that day's benchmark."),
    )),
    ("Par, liquidity and backing", (
        ("≥ $100", "Closes at or above $100 in the last 20 sessions."),
        ("30D volume", "Average of close × shares traded over the last 30 sessions."),
        ("Size", "Notional: shares outstanding × $100."),
        ("BTC floor", "(Debt + preferred notional senior to and including the series − USD cash) ÷ BTC held: the BTC price "
                      "below which those claims exceed the bitcoin. strategy.com publishes STRC's; SATA's uses the same formula."),
        ("Prior-month average", "Mean close over the prior calendar month. Strive may cut SATA's rate only if it is ≥ $99; a cut "
                                "is at most 0.25 pp plus any fall in SOFR, and never below 1-month term SOFR."),
        ("USD cover", "Strategy: (USD Reserve + USD Cash) ÷ current monthly dividends, from each week's 8-K. Strive: its "
                      "dashboard's reserve months."),
    )),
    ("Flows", (
        ("STRC and STRF/K/D/E", "ATM net proceeds − repurchase cost for the filing week."),
        ("SATA", "Net share change × $100."),
        ("MSTR ATM", "Common ATM net proceeds."),
    )),
)


# ── Friday ──────────────────────────────────────────────────────────────────
def friday(panel, derived, *, notices=()) -> None:
    period = panel.get("period") or {}
    week_end = period.get("week_ending", period.get("end"))
    sub = (f"Week of <b>{escape(fri._short(period.get('start')))}–{escape(fri._short(week_end))}</b> · marked at the Friday "
           "4:00 pm ET close" if week_end else "")
    header("friday", "Digital Credit Report · Friday", ("The ", "Closing", " Mark"), sub)
    for notice in notices:
        st.caption(notice)
    btc = (panel.get("header") or {}).get("btc") or {}
    companies = (panel.get("header") or {}).get("companies") or {}
    tile_rows = [("Bitcoin", fri._money(btc.get("price")), f'<span class="{_tone(fri._pct(btc.get("weekly_return_pct"), 2, True))}">'
                  f'{fri._pct(btc.get("weekly_return_pct"), 2, True)} week</span> · {escape(derived["zone"] or "")} '
                  f'{fri._pct(derived["extension"], 0, True)} vs 200W', False)]
    for ticker in ("MSTR", "ASST"):
        item = companies.get(ticker) or {}
        ext = ((panel.get("trends") or {}).get(ticker) or {}).get("averages", {}).get("200D", {}).get("extension_pct")
        multiple, change = item.get("nav_multiple"), item.get("nav_multiple_change")
        tile_rows.append((f"{ticker} price / NAV", f"{multiple:.2f}×" if multiple else "—",
                          (f'<span class="{_tone(f"{change:+.2f}")}">{change:+.2f}× wk</span> · ' if change is not None else "")
                          + f"NAV/sh {fri._money(item.get('nav_per_share'), 2)} · {fri._pct(ext, 1, True)} vs 200D", False))
    sentiment = panel.get("sentiment") or {}
    label, _, days = derived["regime"]
    tile_rows.append(("Fear & Greed", f"{sentiment.get('value'):.0f}" if isinstance(sentiment.get("value"), (int, float)) else "—",
                      f"{escape(label or '')} · {max(1, round((days or 0) / 7))} wk" if label else "", False))
    markets = derived.get("markets") or {}
    tile_rows += [
        ("BTC implied vol (DVOL)", f"{markets['dvol']:.1f}" if markets.get("dvol") is not None else "—",
         f"{markets['dvol_change']:+.1f} wk".replace("-", "−") if markets.get("dvol_change") is not None else "", False),
        ("3M futures basis", fri._pct(markets.get("basis"), 1), "annualized", False),
        ("Stablecoin supply", f"${markets['stablecoins'] / 1e9:,.1f}B" if markets.get("stablecoins") else "—",
         f"{markets['stablecoins_change'] / 1e9:+.1f}B wk".replace("-", "−") if markets.get("stablecoins_change") is not None else "", False),
    ]
    st.html(tiles(tile_rows, min_width=190))
    macro = derived["macro"]
    columns = st.columns(3, gap="small")
    specs = (("US dollar index", macro["dxy"], "index", 101.0, "{:.2f}"), ("US 10-year", macro["tnx"], "%", None, "{:.2f}%"),
             ("Fed funds − 2-year", [(d, v * 100) for d, v in macro["gap"]], "bp", 0.0, "{:+.0f} bp"))
    for column, (title, rows, unit, reference, fmt) in zip(columns, specs):
        with column, st.container(border=True, key=f"fri_{unit}"):
            last = rows[-1][1] if rows else None
            heading(title, fmt.format(last).replace("-", "−") if last is not None else "")
            _macro_chart(rows, unit, reference)
    left, right = st.columns((5, 7), gap="medium")
    with left, st.container(border=True, key="fri_checklist"):
        tally = derived["tally"]
        heading("Cycle checklist", f"bull {tally['BULL']} · neutral {tally['NEUTRAL']} · bear {tally['BEAR']}")
        colors = {"BULL": GREEN, "BEAR": RED, "NEUTRAL": YELLOW}
        st.html(table(("Reading", "Now", "Level", "State"), left=(0,), wrap=(0, 2), rows=[
            (fri.CHECK_LABELS.get(label, label), _nb(value), derived["thresholds"].get(label, ""),
             Html(f'<span class="chip" style="background:{colors[state]}">{state}</span>'))
            for label, value, _note, state in derived["checklist"]]))
    with right, st.container(border=True, key="fri_btc"):
        heading("BTC · 200-week SMA", f"{fri._pct(derived['extension'], 1, True)} vs 200W")
        _btc_chart(panel, derived)
    with st.container(border=True, key="fri_turnover"):
        heading("Weekly turnover", "shares traded ÷ outstanding · 12 weeks")
        _turnover(derived["turnover"])


def _macro_chart(rows, unit, reference) -> None:
    rows = [(day, value) for day, value in rows if value is not None]
    if len(rows) < 3:
        st.caption("History unavailable")
        return
    frame = pd.DataFrame({"date": pd.to_datetime([d for d, _ in rows]), "value": [v for _, v in rows]})
    base = alt.Chart(frame).encode(x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %-d", tickCount=4)))
    line = base.mark_line(color=INK, strokeWidth=2).encode(y=alt.Y("value:Q", title=unit, scale=alt.Scale(zero=False)))
    hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False)
    points = base.mark_point(color=AMBER, size=55, filled=True).encode(
        y="value:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("date:T", title="Date", format="%b %-d, %Y"), alt.Tooltip("value:Q", title=unit, format=",.2f")]
    ).add_params(hover)
    layers = line + points
    if reference is not None:
        layers += alt.Chart(pd.DataFrame({"r": [reference]})).mark_rule(color=AMBER, strokeDash=[6, 4]).encode(y="r:Q")
    show(layers, height=170)


def _btc_chart(panel, derived) -> None:
    series = ((panel.get("trends") or {}).get("BTC") or {}).get("series") or []
    weekly = [row for row in series if row.get("close")]
    if len(weekly) < 10:
        st.caption("History unavailable")
        return
    sma50 = dict(derived.get("sma50w_series") or [])
    realized = {day: value for day, value in derived.get("realized") or []}
    records = []
    for row in weekly:
        day = row["date"]
        for name, value in (("BTC", row.get("close")), ("200W SMA", row.get("sma_200w")), ("50W SMA", sma50.get(day)),
                            ("Realized", realized.get(day))):
            if value:
                records.append({"date": day, "series": name, "usd": value})
    frame = pd.DataFrame(records)
    frame["date"] = pd.to_datetime(frame["date"])
    order = ["BTC", "200W SMA", "50W SMA", "Realized"]
    colors = alt.Scale(domain=order, range=[INK, AMBER, "#12A6C1", "#C43596"])
    base = alt.Chart(frame).encode(x=alt.X("date:T", title=None, axis=alt.Axis(format="%Y", tickCount=8)))
    lines = base.mark_line(strokeWidth=2).encode(
        y=alt.Y("usd:Q", title="USD (log)", scale=alt.Scale(type="log"),
                axis=alt.Axis(format="$~s", values=[100, 1_000, 10_000, 100_000, 1_000_000])),
        color=alt.Color("series:N", scale=colors, sort=order, title=None),
        strokeWidth=alt.condition("datum.series == 'BTC'", alt.value(2.2), alt.value(1.6)))
    hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False)
    rule = alt.Chart(frame).transform_pivot("series", value="usd", groupby=["date"]).mark_rule(color=SOFT).encode(
        x="date:T", opacity=alt.condition(hover, alt.value(0.8), alt.value(0)),
        tooltip=[alt.Tooltip("date:T", title="Week", format="%b %-d, %Y")]
        + [alt.Tooltip(f"{name}:Q", title=name, format="$,.0f") for name in order]).add_params(hover)
    show(lines + rule, height=300)


def _turnover(turnover) -> None:
    records = []
    for ticker in ("MSTR", "ASST", "STRC", "SATA"):
        for week in (turnover.get(ticker) or [])[-12:]:
            if week.get("pct") is not None:
                records.append({"ticker": ticker, "week": week["week"], "pct": week["pct"]})
    if not records:
        st.caption("Turnover unavailable")
        return
    frame = pd.DataFrame(records)
    frame["week"] = pd.to_datetime(frame["week"])
    columns = st.columns(4, gap="small")
    for column, ticker in zip(columns, ("MSTR", "ASST", "STRC", "SATA")):
        part = frame[frame["ticker"] == ticker]
        with column:
            latest = part["pct"].iloc[-1] if len(part) else None
            st.html(f'<div class="dcr-meta"><span class="dot" style="background:{SERIES[ticker]}"></span>'
                    f'<b style="color:{INK}">{ticker}</b> · {latest:.1f}% last week</div>' if latest is not None else "")
            bars = alt.Chart(part).mark_bar(color=SERIES[ticker], cornerRadiusTopLeft=3, cornerRadiusTopRight=3, size=10).encode(
                x=alt.X("week:T", title=None, axis=alt.Axis(format="%b %-d", tickCount=3)),
                y=alt.Y("pct:Q", title="% / week"),
                tooltip=[alt.Tooltip("week:T", title="Week of", format="%b %-d"), alt.Tooltip("pct:Q", title="Turnover %", format=".1f")])
            show(bars, height=130)


FRIDAY_FORMULAS = (
    ("Tiles", (
        ("Weekly change", "Friday 4:00 pm ET mark ÷ the prior Friday's mark − 1."),
        ("Price / NAV", "Share price ÷ NAV per share, where NAV = BTC × price + cash − debt − preferred claims."),
        ("vs 200D", "Share price ÷ its 200-day simple moving average − 1."),
        ("200W zone", "BTC ÷ its 200-week SMA − 1: below 0 Very Cheap, 0–50% Cheap, 50–100% Fair Value, 100–150% Expensive, "
                      "150%+ Very Expensive."),
        ("Fear & Greed", "CoinMarketCap's index, 3-day average; the regime is its current band."),
        ("DVOL", "Deribit's 30-day BTC implied volatility index, daily close."),
        ("3M futures basis", "(Future price ÷ index − 1) × 365 ÷ days to expiry, for the Deribit BTC future closest to 3 months."),
        ("Stablecoin supply", "USD-pegged stablecoins in circulation (DefiLlama); change over 7 days."),
    )),
    ("Macro", (
        ("US dollar index", "ICE DXY (Yahoo DX-Y.NYB); reference line at 101."),
        ("US 10-year", "10-year Treasury yield."),
        ("Fed funds − 2-year", "Effective fed funds rate − 2-year Treasury yield, in bp; reference line at 0."),
    )),
    ("Cycle checklist", tuple((fri.CHECK_LABELS.get(label, label), rule) for label, rule in fri.RULES.items())),
    ("Other", (
        ("Turnover", "Weekly shares traded ÷ shares outstanding (preferreds: notional ÷ $100)."),
        ("Realized price", "Checkonchain's realised price: the average price at which each BTC last moved."),
    )),
)
