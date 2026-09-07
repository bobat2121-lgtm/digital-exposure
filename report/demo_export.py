"""Balanced compact report; all financial values come from the shared view."""
from dataclasses import replace
from io import BytesIO

from .png_export import INK, LINE, MUTED, ORANGE, _Canvas, _metadata
from .post_export import WIDTH, HEIGHT, MARGIN, GAP, PANEL_WIDTH, INSET, _text, _pair, _disclosure, _post_details
from .view_types import CompanyView, MetricView, ReportView

GREEN, RED = "#15745E", "#AE4355"


def demo_report_view(view: ReportView) -> ReportView:
    return replace(view, label=f"REDESIGN PREVIEW · {view.label}")


def _color(tone: str) -> str:
    return {"positive": GREEN, "negative": RED}.get(tone, INK)


def _metric(canvas, label, value, change, left, right, y, tone="neutral"):
    width = right - left
    _text(canvas, label, left, y + 3, width * .44, size=23, bold=True)
    canvas.right(value, left + width * .71, y, 28, True, width=width * .25)
    canvas.right(change, right, y + 5, 22, True, _color(tone), width=width * .25)


def _company(canvas: _Canvas, c: CompanyView, index: int, capital_period: str) -> None:
    x = MARGIN + index * (PANEL_WIDTH + GAP)
    left, right = x + INSET, x + PANEL_WIDTH - INSET
    width = right - left
    draw = canvas.draw
    draw.rounded_rectangle((x, 154, x + PANEL_WIDTH, 1077), radius=14, fill="#FFFFFF")
    draw.rectangle((x, 154, x + PANEL_WIDTH, 159), fill=ORANGE if index == 0 else INK)
    canvas.logo(c, left, 171)
    canvas.right(c.stock_price, right, 171, 32, True, width=width - 294)
    canvas.right(f"{c.ticker} · {c.quote_session}", right, 212, 17, color=MUTED, width=width - 294)
    canvas.right(c.quote_timestamp, right, 235, 17, color=MUTED, width=width - 294)
    draw.line((left, 263, right, 263), fill=LINE)
    _text(canvas, "NET TREASURY NAV / SHARE", left, 279, width * .64, size=19, bold=True, color=MUTED)
    canvas.right("PRICE / BASIC NAV", right, 279, 18, True, MUTED)
    _text(canvas, c.nav_per_share, left, 313, width * .64, size=38, bold=True)
    canvas.right(c.price_to_nav, right, 316, 34, True, width=width * .32)
    draw.line((left, 366, right, 366), fill=LINE)

    bought = c.bought or MetricView("New Bitcoin bought", "Not disclosed")
    total_bitcoin = c.total_bitcoin or MetricView("Total BTC held", "Not disclosed")
    _text(canvas, bought.label, left, 378, width * .49, size=21, bold=True, color=MUTED)
    _text(canvas, bought.value, left, 407, width * .49, size=28, bold=True)
    canvas.right(total_bitcoin.label, right, 378, 21, True, MUTED, width=width * .49)
    canvas.right(total_bitcoin.value, right, 407, 28, True, width=width * .49)
    _text(canvas, capital_period.upper(), left, 456, width * .59, size=17, bold=True, color=ORANGE)
    canvas.right("+ RAISED / − REPURCHASED", right, 457, 17, color=MUTED)
    _pair(canvas, c.common, left, 483, width, value_size=29, label_size=23)
    _disclosure(canvas, _post_details(c.common), left, 520, width, 562, size=18)
    _pair(canvas, c.preferred, left, 563, width, value_size=29, label_size=23)
    _disclosure(canvas, ("\n".join(_post_details(c.preferred)),), left, 602, width, 646, size=18)
    draw.line((left, 657, right, 657), fill=LINE)
    _pair(canvas, c.shares, left, 675, width, value_size=29, label_size=23)
    canvas.right(c.shares.change, right, 715, 18, color=MUTED, width=width)
    draw.line((left, 748, right, 748), fill=LINE)
    canvas.right("VALUE", left + width * .71, 762, 16, True, MUTED)
    canvas.right("WEEKLY Δ", right, 762, 16, True, MUTED)
    _metric(canvas, c.bitcoin.label, c.bitcoin.value, c.bitcoin.short_change, left, right, 788, c.bitcoin.tone)
    _metric(canvas, "NAV per common share", c.nav_per_share, c.nav_change.value, left, right, 831, c.nav_change.tone)
    _metric(canvas, c.amplification.label, c.amplification.value, c.amplification.short_change, left, right, 874)
    _metric(canvas, c.preferred_ratio.label, c.preferred_ratio.value, c.preferred_ratio.short_change, left, right, 917)

    draw.rounded_rectangle((left, 965, right, 1070), radius=8, fill="#F4F6F6")
    _text(canvas, "BASIC-SHARE GROWTH", left + 16, 980, width * .44, size=16, bold=True, color=MUTED)
    columns = (left + width * .71, right - 16)
    for period, column in zip(c.periods, columns):
        canvas.right(period.period, column, 980, 16, True, MUTED)
        canvas.right(period.btc_growth, column, 1009, 22, True, _color(period.btc_tone), width=width * .25)
        canvas.right(period.nav_growth, column, 1041, 22, True, _color(period.nav_tone), width=width * .25)
    _text(canvas, "BTC / share", left + 16, 1010, width * .44, size=20, bold=True)
    _text(canvas, "NAV / share", left + 16, 1042, width * .44, size=20, bold=True)
    if not c.periods:
        canvas.right("QTD / YTD not provided", right - 12, 1032, 19, color=MUTED, width=width * .52)


def render_redesign_png(view: ReportView) -> bytes:
    if len(view.companies) != 2:
        raise ValueError("The Monday Capital Report requires exactly two companies.")
    canvas = _Canvas(HEIGHT)
    canvas.draw.rectangle((0, 0, WIDTH, 6), fill=ORANGE)
    _text(canvas, view.label, MARGIN, 27, WIDTH - 2 * MARGIN, size=18, bold=True, color=ORANGE)
    _text(canvas, view.title, MARGIN, 64, 1100, size=40, bold=True)
    _text(canvas, view.subtitle, MARGIN, 115, 1040, size=20, color=MUTED)
    canvas.right(view.report_time, WIDTH - MARGIN, 66, 21, True, width=620)
    canvas.right(f"BTC {view.btc_price} · {view.btc_timestamp}", WIDTH - MARGIN, 115, 19, color=MUTED, width=640)
    for index, company in enumerate(view.companies):
        _company(canvas, company, index, view.capital_period_label)
    footer = "NAV growth at constant prices · ≈ estimates · Methodology on Streamlit"
    if view.comparison_note:
        footer += " · " + view.comparison_note
    _text(canvas, footer, MARGIN, 1093, WIDTH - 2 * MARGIN, size=17, color=MUTED, bottom=HEIGHT - 5)
    result = BytesIO()
    canvas.image.save(result, format="PNG", optimize=True, pnginfo=_metadata(view), dpi=(144, 144))
    return result.getvalue()


def render_demo_png(view: ReportView) -> bytes:
    return render_redesign_png(view)
