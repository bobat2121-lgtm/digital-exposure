"""Shared PIL drawing toolkit for the preview panels.

Text never clips silently: it shrinks to a floor size and is then ellipsized,
and every such event is recorded in ``Canvas.overflows`` so tests can require
a clean layout. Fonts are the bundled Lato (report-*.ttf) and Gelasio (OFL).
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import math
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parents[1] / "assets"

# Phone-first type scale for the 1440-px-wide panels. A phone shows the image
# about 390 CSS px wide (≈0.27 px per canvas px), so 28 px is the smallest
# text that stays legible there; key numbers are 44 px and up.
T_MIN, T_LABEL, T_BODY, T_VALUE, T_BIG, T_HERO = 28, 30, 34, 44, 64, 92


# Font sets per theme: (file, variable-font style or None). "key" is the
# display face for a title's key word (serif in the classic Imprint style).
FONT_SETS = {
    "classic": {"regular": ("report-regular.ttf", None), "bold": ("report-bold.ttf", None),
                "key": ("gelasio-variable.ttf", "Bold"), "key_regular": ("gelasio-variable.ttf", "Regular")},
    "cyber": {"regular": ("chakrapetch-regular.ttf", None), "bold": ("chakrapetch-bold.ttf", None),
              "key": ("orbitron-variable.ttf", "Black"), "key_regular": ("orbitron-variable.ttf", "Medium")},
    "brutal": {"regular": ("spacegrotesk-variable.ttf", "Regular"), "bold": ("spacegrotesk-variable.ttf", "Bold"),
               "key": ("spacegrotesk-variable.ttf", "Bold"), "key_regular": ("spacemono-regular.ttf", None),
               "mono": ("spacemono-bold.ttf", None)},
}
FONTSET: ContextVar[str] = ContextVar("panel_fontset", default="classic")


@contextmanager
def fontset(name: str):
    token = FONTSET.set(name if name in FONT_SETS else "classic")
    try:
        yield
    finally:
        FONTSET.reset(token)


@lru_cache(maxsize=256)
def _face(name: str, style: str | None, size: int) -> ImageFont.FreeTypeFont:
    face = ImageFont.truetype(str(ASSETS / name), size)
    if style:
        face.set_variation_by_name(style)
    return face


def font(size: int, bold: bool = False, serif: bool = False) -> ImageFont.FreeTypeFont:
    fonts = FONT_SETS[FONTSET.get()]
    role = ("key" if bold else "key_regular") if serif else ("bold" if bold else "regular")
    return _face(*fonts[role], size)


def width(text: str, size: int, bold: bool = False, serif: bool = False) -> float:
    return font(size, bold, serif).getlength(str(text))


def mix(color: str, background: str, opacity: float) -> tuple[int, int, int]:
    a, b = ImageColor.getrgb(color), ImageColor.getrgb(background)
    return tuple(round(bg * (1 - opacity) + fg * opacity) for fg, bg in zip(a, b))


class Canvas:
    def __init__(self, size: tuple[int, int], background: str, *, floor: int = 12):
        self.image = Image.new("RGB", size, background)
        self.draw = ImageDraw.Draw(self.image)
        self.background = background
        self.overflows: list[str] = []
        self.floor = floor          # text never shrinks below this size
        self.smallest: int | None = None  # smallest text size actually drawn

    # ── text ────────────────────────────────────────────────────────────────
    def fit(self, text: str, size: int, max_width: float | None, bold=False, serif=False, minimum=12) -> tuple[str, int]:
        text = str(text)
        minimum = max(minimum, self.floor)
        if max_width is None:
            return text, size
        while size > minimum and width(text, size, bold, serif) > max_width:
            size -= 1
        if width(text, size, bold, serif) > max_width:
            self.overflows.append(text)
            while text and width(text + "…", size, bold, serif) > max_width:
                text = text[:-1]
            text += "…"
        return text, size

    def text(self, x, y, text, size=22, color="#000", bold=False, *, max_width=None, align="left",
             serif=False, minimum=12, anchor_top=True) -> float:
        """Draw one line; return its right edge. ``align``: left, right or center."""
        if size < self.floor:
            self.overflows.append(f"below {self.floor}px: {text}")  # too small to read on a phone
        text, size = self.fit(text, size, max_width, bold, serif, minimum)
        if text:
            self.smallest = size if self.smallest is None else min(self.smallest, size)
        length = width(text, size, bold, serif)
        if align == "right":
            x -= length
        elif align == "center":
            x -= length / 2
        self.draw.text((x, y), text, font=font(size, bold, serif), fill=color, anchor="lt" if anchor_top else "ls")
        return x + length

    def wrap(self, text: str, max_width: float, size: int, bold=False) -> list[str]:
        lines, line = [], ""
        for word in str(text).split():
            candidate = f"{line} {word}" if line else word
            if width(candidate, size, bold) <= max_width or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        return lines

    def paragraph(self, x, y, text, max_width, size=18, color="#000", bold=False, leading=1.32, max_lines=None) -> float:
        lines = self.wrap(text, max_width, size, bold)
        if max_lines is not None and len(lines) > max_lines:
            self.overflows.append(text)
            lines = lines[:max_lines]
            lines[-1] = self.fit(lines[-1] + " …", size, max_width, bold)[0]
        for line in lines:
            self.text(x, y, line, size, color, bold, max_width=max_width)
            y += round(size * leading)
        return y

    # ── shapes ──────────────────────────────────────────────────────────────
    def card(self, box, fill, radius=12, accent=None, accent_height=4, outline=None):
        self.draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1 if outline else 0)
        if accent:
            x0, y0, x1, _ = box
            self.draw.rectangle((x0 + radius / 2, y0, x1 - radius / 2, y0 + accent_height), fill=accent)

    def line(self, points, color, width_px=2, dashed=False, dash=(9, 7)):
        points = [tuple(point) for point in points]
        if len(points) < 2:
            return
        if not dashed:
            self.draw.line(points, fill=color, width=width_px, joint="curve")
            return
        on, off = dash
        period, phase = on + off, 0.0
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            length = math.hypot(x1 - x0, y1 - y0)
            along = 0.0
            while along < length:
                position = phase % period
                step = min(length - along, (on - position) if position < on else (period - position))
                if position < on:
                    t0, t1 = along / length, (along + step) / length
                    self.draw.line((x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0, x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1),
                                   fill=color, width=width_px)
                along += step
                phase += step

    def dot(self, x, y, radius, fill, outline=None):
        self.draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill, outline=outline,
                          width=2 if outline else 0)

    def pill(self, x, y, text, size, fg, bg, bold=True, align="left", pad=(12, 5)) -> float:
        length = width(text, size, bold)
        x0 = x - length - 2 * pad[0] if align == "right" else x
        self.draw.rounded_rectangle((x0, y, x0 + length + 2 * pad[0], y + size + 2 * pad[1] + 2), radius=(size + 2 * pad[1]) // 2, fill=bg)
        self.text(x0 + pad[0], y + pad[1], text, size, fg, bold)
        return x0

    def chip(self, box, text, size, fg, bg, bold=True, radius=None) -> None:
        """A fixed-size rounded cell with its text centered on the ink, not the font box."""
        x0, y0, x1, y1 = box
        self.draw.rounded_rectangle(box, radius=(y1 - y0) // 2 if radius is None else radius, fill=bg)
        text, size = self.fit(text, size, x1 - x0 - 8, bold)
        if text:
            self.smallest = size if self.smallest is None else min(self.smallest, size)
        left, top, right, bottom = font(size, bold).getbbox(text, anchor="lt")
        x = (x0 + x1) / 2 - (left + right) / 2
        y = (y0 + y1) / 2 - (top + bottom) / 2
        self.draw.text((x, y), text, font=font(size, bold), fill=fg, anchor="lt")

    def save(self, *, metadata: dict | None = None) -> bytes:
        from io import BytesIO
        from PIL.PngImagePlugin import PngInfo
        info = PngInfo()
        for key, value in (metadata or {}).items():
            info.add_text(key, str(value))
        buffer = BytesIO()
        self.image.save(buffer, format="PNG", optimize=True, pnginfo=info, dpi=(144, 144))
        return buffer.getvalue()


def imprint(canvas: Canvas, x: float, y: float, words: tuple[str, str, str], size: int, *,
            ink: str, muted: str, dot: str) -> float:
    """The house title style: Lato bookends, a serif bold key word, orange dot.

    ``words`` is (prefix, key word, suffix), e.g. ("The ", "Accretion", " Ledger").
    ``y`` is the baseline. Returns the right edge after the dot.
    """
    prefix, key, suffix = words
    tracking = -.03 * size
    for text, serif, color, bold in ((prefix, False, muted, False), (key, True, ink, True), (suffix, False, muted, False)):
        face = font(size, bold, serif)
        for index, character in enumerate(text):
            advance = face.getlength(text[:index + 1]) - face.getlength(character)
            canvas.draw.text((x + advance + index * tracking, y), character, font=face, anchor="ls", fill=color)
        x += face.getlength(text) + len(text) * tracking
    radius = size * 3 / 33
    x += size * 5 / 33
    canvas.dot(x + radius, y - size / 33 - radius, radius, dot)
    return x + 2 * radius


def imprint_width(words: tuple[str, str, str], size: int) -> float:
    total = 0.0
    for text, serif, bold in ((words[0], False, False), (words[1], True, True), (words[2], False, False)):
        total += font(size, bold, serif).getlength(text) - .03 * size * len(text)
    return total + size * 11 / 33


def sparkline(canvas: Canvas, box, values, color, *, width_px=3, baseline=None, baseline_color=None,
              fill=None, dot_last=True, dot_color=None, domain=None):
    x0, y0, x1, y1 = box
    points = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(points) < 2:
        return None
    low, high = domain or (min(v for _, v in points), max(v for _, v in points))
    if baseline is not None:
        low, high = min(low, baseline), max(high, baseline)
    if high == low:
        high, low = high + 1, low - 1
    span = max(1, len(values) - 1)

    def xy(index, value):
        return x0 + index / span * (x1 - x0), y1 - (value - low) / (high - low) * (y1 - y0)

    if baseline is not None:
        by = xy(0, baseline)[1]
        canvas.line([(x0, by), (x1, by)], baseline_color or color, 1, dashed=True, dash=(4, 4))
    coords = [xy(index, value) for index, value in points]
    if fill:
        canvas.draw.polygon(coords + [(coords[-1][0], y1), (coords[0][0], y1)], fill=fill)
    canvas.line(coords, color, width_px)
    if dot_last:
        canvas.dot(*coords[-1], width_px + 2, dot_color or color)
    return coords
