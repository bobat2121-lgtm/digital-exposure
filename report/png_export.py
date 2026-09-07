"""Print-quality PNG presentation of the same formatted view used by the page.

There are intentionally no financial formulas here. All displayed values,
changes and transaction descriptions come from ``ReportView``. Row heights are
measured across both companies before either panel is drawn, preserving their
alignment even when a disclosure wraps to additional lines.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .view_types import CompanyView, MetricView, ReportView


ASSETS = Path(__file__).resolve().parents[1] / "assets"
WIDTH = 1800
MARGIN = 50
GAP = 48
PANEL_WIDTH = (WIDTH - 2 * MARGIN - GAP) // 2
INSET = 34
CONTENT_WIDTH = PANEL_WIDTH - 2 * INSET
BACKGROUND = "#F4F2EC"
INK = "#182832"
MUTED = "#61727B"
ORANGE = "#EB7B21"
LINE = "#DEE5E6"
TEAL = "#15745E"
TEAL_BG = "#EEF5F1"


@lru_cache(maxsize=32)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "report-bold.ttf" if bold else "report-regular.ttf"
    return ImageFont.truetype(str(ASSETS / name), size=size)


def _width(text: str, size: int, bold: bool = False) -> float:
    return _font(size, bold).getlength(text)


def _fit(text: str, size: int, width: float, bold: bool = False, minimum: int = 17) -> int:
    while size > minimum and _width(text, size, bold) > width:
        size -= 1
    if _width(text, size, bold) > width:
        raise ValueError(f"Single-line content does not fit: {text!r}")
    return size


def _wrap(text: str, width: float, size: int, bold: bool = False) -> list[str]:
    """Wrap every word without dropping text; split exceptional long tokens."""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if _width(candidate, size, bold) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ""
            if _width(word, size, bold) <= width:
                line = word
                continue
            for character in word:
                if line and _width(line + character, size, bold) > width:
                    lines.append(line)
                    line = ""
                line += character
        lines.append(line)
    return lines


@dataclass(frozen=True)
class _Text:
    x: float
    y: float
    text: str
    size: int
    bold: bool = False
    color: str = INK


@dataclass(frozen=True)
class _Row:
    text: tuple[_Text, ...]
    height: int
    box: bool = False


def _lines(items: list[_Text], text: str, x: float, y: float, width: float,
           size: int, bold: bool = False, color: str = MUTED) -> float:
    for line in _wrap(text, width, size, bold):
        items.append(_Text(x, y, line, size, bold, color))
        y += round(size * 1.36)
    return y


def _metric_row(metric: MetricView, kind: str, minimum: int) -> _Row:
    items: list[_Text] = []
    supporting = kind == "supporting"
    callout = kind == "callout"
    prominent = kind == "amplification"
    pad = 21 if callout else 0
    usable_width = CONTENT_WIDTH - 2 * pad
    label_size = 22 if supporting else 26 if prominent else 25
    value_size = 26 if supporting else 40 if callout or prominent else 33
    label_color = MUTED if supporting else INK
    value_color = TEAL if callout and metric.tone == "positive" else MUTED if supporting else INK
    value_size = _fit(metric.value, value_size, usable_width * .46, True)
    value_width = _width(metric.value, value_size, True)
    first_y = 24 if callout else 18
    overline = getattr(metric, "overline", "")
    if overline:
        first_y = _lines(items, overline, pad, first_y, usable_width,
                         18, False, MUTED) + 9
    label_width = usable_width - value_width - 28
    label_end = _lines(items, metric.label, pad, first_y, label_width,
                       label_size, not supporting, label_color)
    items.append(_Text(pad + usable_width - value_width, first_y - 2,
                       metric.value, value_size, True, value_color))
    detail_y = max(label_end, first_y + round(value_size * 1.15)) + 8
    detail_size = 18 if callout else 20 if prominent else 19
    detail_width = usable_width
    change_size = 20 if prominent else 19
    change_width = _width(metric.change, change_size)
    separate_change = bool(metric.change) and change_width > usable_width * .53
    if metric.change and not separate_change:
        detail_width -= change_width + 22
        items.append(_Text(pad + usable_width - change_width, detail_y,
                           metric.change, change_size, False, MUTED))
    next_y = detail_y
    for index, detail in enumerate(metric.details):
        emphasize = kind == "preferred" and index == 0
        next_y = _lines(items, detail, pad, next_y, detail_width,
                        detail_size, emphasize, MUTED)
    if metric.change and separate_change:
        next_y = _lines(items, metric.change, pad, next_y, usable_width,
                        change_size, False, MUTED)
    elif metric.change:
        next_y = max(next_y, detail_y + round(change_size * 1.36))
    return _Row(tuple(items), max(minimum, round(next_y + (26 if callout else 20))), callout)


def _company_rows(company: CompanyView) -> tuple[_Row, ...]:
    rows = []
    if company.bought:
        rows.append(_metric_row(company.bought, "common", 85))
    if company.total_bitcoin:
        rows.append(_metric_row(company.total_bitcoin, "common", 85))
    rows.extend((
        _metric_row(replace(company.common, details=company.common.post_details or company.common.details), "common", 108),
        _metric_row(replace(company.preferred, details=company.preferred.post_details or company.preferred.details, overline=""), "preferred", 125),
        _metric_row(company.shares, "shares", 110),
        _metric_row(company.bitcoin, "bitcoin", 120),
        _metric_row(MetricView("NAV per common share", company.nav_per_share, change=company.nav_change.value), "common", 110),
        _metric_row(company.amplification, "amplification", 126),
        _metric_row(company.preferred_ratio, "supporting", 88),
    ))
    for period in company.periods:
        rows.extend((
            _metric_row(MetricView(f"{period.period} · BTC / basic share growth", period.btc_growth), "supporting", 80),
            _metric_row(MetricView(f"{period.period} · NAV / basic share growth", period.nav_growth), "supporting", 80),
        ))
    return tuple(rows)


class _Canvas:
    def __init__(self, height: int):
        self.image = Image.new("RGB", (WIDTH, height), BACKGROUND)
        self.draw = ImageDraw.Draw(self.image)

    def text(self, item: _Text, x: float = 0, y: float = 0,
             right: float | None = None, bottom: float | None = None) -> None:
        font = _font(item.size, item.bold)
        px, py = x + item.x, y + item.y
        box = self.draw.textbbox((px, py), item.text, font=font, anchor="lt")
        limit_right = self.image.width if right is None else right
        limit_bottom = self.image.height if bottom is None else bottom
        if box[0] < 0 or box[1] < 0 or box[2] > limit_right + 1 or box[3] > limit_bottom + 1:
            raise ValueError(f"Export content would clip: {item.text!r}")
        self.draw.text((px, py), item.text, font=font, anchor="lt", fill=item.color)

    def right(self, text: str, right: float, y: float, size: int,
              bold: bool = False, color: str = INK, width: float | None = None) -> None:
        if width is not None:
            size = _fit(text, size, width, bold)
        self.text(_Text(right - _width(text, size, bold), y, text, size, bold, color))

    def logo(self, company: CompanyView, x: int, y: int) -> None:
        path = ASSETS / f"{company.logo}.png"
        with Image.open(path) as asset:
            logo = asset.convert("RGBA")
        alpha_box = logo.getchannel("A").getbbox()
        if alpha_box:
            logo = logo.crop(alpha_box)
        logo.thumbnail((272, 73), Image.Resampling.LANCZOS)
        self.image.paste(logo, (x, y + (73 - logo.height) // 2), logo)


def render_png(view: ReportView) -> bytes:
    """Return a complete, side-by-side PNG for the two-company report.

    The canvas grows for longer disclosures instead of cropping them. Every
    text draw is bounds checked, and corresponding rows share measured heights.
    """
    if len(view.companies) != 2:
        raise ValueError("The Monday Capital Report requires exactly two companies.")

    rows = tuple(_company_rows(company) for company in view.companies)
    row_heights = tuple(max(left.height, right.height) for left, right in zip(*rows))
    panel_top = 220
    header_height = 128
    nav_height = 172
    capital_heading_height = 60
    rows_top = panel_top + header_height + nav_height + capital_heading_height
    panel_bottom = rows_top + sum(row_heights) + 14
    footer_lines = _wrap(view.footer, WIDTH - 2 * MARGIN, 19)
    height = panel_bottom + 64 + len(footer_lines) * 26
    canvas = _Canvas(height)
    draw = canvas.draw
    draw.rectangle((0, 0, WIDTH, 7), fill=ORANGE)
    canvas.text(_Text(MARGIN, 40, view.label, 21, True, ORANGE))
    title_size = _fit(view.title, 48, 1090, True)
    canvas.text(_Text(MARGIN, 86, view.title, title_size, True))
    canvas.text(_Text(MARGIN, 149, view.subtitle, 25, False, MUTED))
    canvas.right(view.report_time, WIDTH - MARGIN, 90, 23, True, width=570)
    btc_line = f"BTC REFERENCE {view.btc_price}"
    canvas.right(btc_line, WIDTH - MARGIN, 130, 19, False, MUTED, width=570)
    canvas.right(view.btc_timestamp, WIDTH - MARGIN, 157, 18, False, MUTED, width=570)

    for index, company in enumerate(view.companies):
        panel_x = MARGIN + index * (PANEL_WIDTH + GAP)
        left = panel_x + INSET
        right = panel_x + PANEL_WIDTH - INSET
        draw.rounded_rectangle((panel_x, panel_top, panel_x + PANEL_WIDTH, panel_bottom),
                               radius=13, fill="#FFFFFF")
        draw.rectangle((panel_x, panel_top, panel_x + PANEL_WIDTH, panel_top + 5),
                       fill=ORANGE if index == 0 else INK)
        canvas.logo(company, left, panel_top + 26)
        canvas.right(company.stock_price, right, panel_top + 31, 36, True, width=CONTENT_WIDTH - 294)
        canvas.right(f"{company.ticker} · {company.quote_session}", right,
                     panel_top + 80, 18, False, MUTED, width=CONTENT_WIDTH - 294)
        canvas.right(company.quote_timestamp, right, panel_top + 105,
                     17, False, MUTED, width=CONTENT_WIDTH - 294)

        nav_y = panel_top + header_height
        draw.line((left, nav_y, right, nav_y), fill=LINE, width=1)
        canvas.text(_Text(left, nav_y + 27, "NET TREASURY NAV / SHARE", 20, True, MUTED))
        canvas.right("PRICE / BASIC NAV", right, nav_y + 27, 20, True, MUTED)
        nav_size = _fit(company.nav_per_share, 61, CONTENT_WIDTH * .65, True)
        canvas.text(_Text(left, nav_y + 69, company.nav_per_share, nav_size, True))
        canvas.right(company.price_to_nav, right, nav_y + 81, 44, True, width=CONTENT_WIDTH * .29)
        canvas.text(_Text(left, nav_y + 145,
                          company.nav_note,
                          _fit(company.nav_note, 18, CONTENT_WIDTH), False, MUTED), right=right)
        capital_y = nav_y + nav_height
        draw.line((left, capital_y, right, capital_y), fill=LINE, width=1)
        canvas.text(_Text(left, capital_y + 25, view.capital_period_label.upper(), 20, True, ORANGE))
        canvas.right("+ RAISED  /  − REPURCHASED", right, capital_y + 27, 17, False, MUTED)

        row_y = rows_top
        for row_index, (row, row_height) in enumerate(zip(rows[index], row_heights)):
            if row_index == 2:
                draw.line((left, row_y, right, row_y), fill=LINE, width=1)
            if row.box:
                draw.rounded_rectangle((left, row_y + 4, right, row_y + row_height - 9),
                                       radius=9, fill=TEAL_BG)
            for item in row.text:
                canvas.text(item, left, row_y, right=right, bottom=row_y + row_height - 8)
            row_y += row_height

    for i, line in enumerate(footer_lines):
        canvas.text(_Text(MARGIN, panel_bottom + 28 + i * 26, line, 19, False, MUTED))
    result = BytesIO()
    canvas.image.save(result, format="PNG", optimize=True,
                      pnginfo=_metadata(view), dpi=(144, 144))
    return result.getvalue()


def _metadata(view: ReportView):
    from PIL.PngImagePlugin import PngInfo

    metadata = PngInfo()
    metadata.add_text("Title", view.title)
    metadata.add_text("Description", view.label + ". " + view.footer)
    metadata.add_text("Software", "The Monday Capital Report local prototype")
    return metadata
