"""Themes for the three panels: palettes per day, fonts, title style, décor.

classic  — the house style (cream Monday, certificate Wednesday, black Friday).
neon     — "Neon Ledger": cyberpunk HUD, professional restraint.
orbit    — "Brutal Orbit": brutalist concrete and heavy rules meets deep space.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import random

from PIL import Image, ImageDraw, ImageFilter

from .draw import Canvas, font, imprint, mix, width


@dataclass(frozen=True)
class Palette:
    bg: str
    card: str
    ink: str
    muted: str
    soft: str
    line: str
    tint: str
    accent: str          # brand accent (orange in classic)
    positive: str
    negative: str
    neutral: str
    accent2: str         # secondary: Strive stripe / certificate green / 50W blue
    accent3: str         # tertiary: par gold / realized violet
    band: str = "#56c4a0"
    deep: str = "#15463B"
    outline: str | None = None
    outline_width: int = 1
    radius: int = 12
    cash: str = "#EAF1F6"   # fill that marks cash as a balance, not capital raised


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    fontset: str
    monday: Palette
    wednesday: Palette
    friday: Palette
    title_style: str = "imprint"   # imprint | neon | block
    decor: str = "none"            # none | grid | orbit
    uppercase_titles: bool = False


CLASSIC = Theme(
    "classic", "Classic", "classic",
    monday=Palette("#F4F2EC", "#FFFFFF", "#182832", "#5B6C75", "#8A979E", "#DEE5E6", "#F4F6F6", "#EB7B21",
                   "#15745E", "#AE4355", "#B08A2E", "#182832", "#B08A2E", cash="#EDF3F7", radius=14),
    wednesday=Palette("#E6ECE7", "#F9FBF7", "#10302A", "#4E6A63", "#7D938D", "#CBD8D1", "#EEF3EF", "#E07A1F",
                      "#1F6F5C", "#A8433F", "#B08A2E", "#1F6F5C", "#B08A2E", deep="#15463B", outline="#CBD8D1", radius=14),
    friday=Palette("#0b0d0f", "#15191d", "#f5f3ed", "#9aa4ad", "#6f7a83", "#30363c", "#1c2126", "#e88029",
                   "#8cdbb5", "#f5a09b", "#d9c86a", "#7fb2ff", "#c39bff", band="#56c4a0", radius=10),
)

NEON = Theme(
    "neon", "Neon Ledger (cyberpunk)", "cyber",
    monday=Palette("#060A14", "#0C1324", "#E8F1FF", "#8FA2CC", "#5D6E96", "#1B2842", "#101B31", "#22E3FF",
                   "#3DFFA2", "#FF4D7A", "#FFE14D", "#FF3DCB", "#FFE14D", outline="#1F3358", radius=4, cash="#0F2338"),
    wednesday=Palette("#0A0714", "#120D22", "#F2E9FF", "#A796C9", "#6C5E8E", "#271C40", "#181129", "#FF3DCB",
                      "#3DFFA2", "#FF4D7A", "#FFE14D", "#22E3FF", "#FFE14D", deep="#FF3DCB", outline="#34245A", radius=4),
    friday=Palette("#04090A", "#0A1416", "#E6FFFB", "#88AEB0", "#557577", "#16292C", "#0E1C1F", "#FFC23D",
                   "#3DFFA2", "#FF4D7A", "#FFE14D", "#22E3FF", "#FF3DCB", band="#3DFFA2", outline="#1B3A3E", radius=4),
    title_style="neon", decor="grid", uppercase_titles=True,
)

ORBIT = Theme(
    "orbit", "Brutal Orbit (brutalist × space)", "brutal",
    monday=Palette("#D6D3CC", "#F3F1EC", "#0A0A0A", "#2F2F2F", "#6A6A6A", "#0A0A0A", "#E4E1DA", "#FF4F00",
                   "#157A3A", "#D7263D", "#C9A227", "#0B1026", "#FF4F00", outline="#0A0A0A", outline_width=4, radius=0,
                   cash="#DCE3F0"),
    wednesday=Palette("#CDD3D2", "#F1F3F2", "#0A0A0A", "#2F2F2F", "#6A6A6A", "#9AA3A2", "#E0E5E4", "#FF4F00",
                      "#157A3A", "#D7263D", "#C9A227", "#1F4FFF", "#C9A227", deep="#0B1026", outline="#0A0A0A",
                      outline_width=4, radius=0),
    friday=Palette("#050505", "#101010", "#F3F1EC", "#A8A6A0", "#6E6C66", "#383838", "#1A1A1A", "#FF4F00",
                   "#7CE38B", "#FF6A6A", "#F2D24B", "#8FB4FF", "#C9A0FF", band="#7CE38B", outline="#F3F1EC",
                   outline_width=3, radius=0),
    title_style="block", decor="orbit", uppercase_titles=True,
)

THEMES = {theme.key: theme for theme in (CLASSIC, NEON, ORBIT)}


def get(key: str | None) -> Theme:
    return THEMES.get(key or "classic", CLASSIC)


# ── shared themed drawing ───────────────────────────────────────────────────
def card(canvas: Canvas, box, p: Palette, accent: str | None = None, theme: Theme = CLASSIC, accent_height=4):
    x0, y0, x1, y1 = box
    if theme.decor == "orbit":
        # Brutalist: hard offset shadow, square corners, heavy rule.
        canvas.draw.rectangle((x0 + 8, y0 + 8, x1 + 8, y1 + 8), fill=p.outline or p.ink)
    canvas.draw.rounded_rectangle(box, radius=p.radius, fill=p.card,
                                  outline=p.outline, width=p.outline_width if p.outline else 0)
    if accent:
        inset = p.radius / 2
        canvas.draw.rectangle((x0 + inset, y0, x1 - inset, y0 + accent_height), fill=accent)
    if theme.decor == "grid":
        # HUD corner brackets.
        color, arm = accent or p.accent, 16
        for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            canvas.draw.line((cx, cy, cx + dx * arm, cy), fill=color, width=2)
            canvas.draw.line((cx, cy, cx, cy + dy * arm), fill=color, width=2)


def background(canvas: Canvas, p: Palette, theme: Theme, header_height=150, orbit_at=(1190, 76, .8)):
    """``orbit_at`` = (x, y, scale) of the planet, placed in each header's free space."""
    w, h = canvas.image.size
    if theme.decor == "grid":
        for x in range(0, w, 40):
            canvas.draw.line((x, 0, x, h), fill=mix(p.line, p.bg, .45), width=1)
        for y in range(0, h, 40):
            canvas.draw.line((0, y, w, y), fill=mix(p.line, p.bg, .45), width=1)
        canvas.draw.rectangle((0, 0, w, 4), fill=p.accent)
        canvas.draw.rectangle((0, 4, w * .38, 6), fill=p.accent2)
    elif theme.decor == "orbit":
        space = "#07091A"
        canvas.draw.rectangle((0, 0, w, header_height), fill=space)
        rng = random.Random(7)
        for _ in range(200):
            x, y, r = rng.uniform(0, w), rng.uniform(0, header_height), rng.choice((0.6, 0.8, 1.0, 1.3))
            shade = rng.choice(("#E6EBFF", "#8A93B8", "#5A6288", "#5A6288"))
            canvas.draw.ellipse((x - r, y - r, x + r, y + r), fill=shade)
        cx, cy, k = orbit_at
        for rx, ry in ((260, 44), (190, 30)):
            canvas.draw.ellipse((cx - rx * k, cy - ry * k, cx + rx * k, cy + ry * k), outline="#39406A", width=2)
        canvas.draw.ellipse((cx - 30 * k, cy - 30 * k, cx + 30 * k, cy + 30 * k), fill=p.accent)
        canvas.draw.ellipse((cx + 180 * k, cy - 8 * k, cx + 196 * k, cy + 8 * k), fill="#F3F1EC")
        canvas.draw.rectangle((0, header_height, w, header_height + 6), fill=p.accent)


def title(canvas: Canvas, x, baseline, words, size, p: Palette, theme: Theme, *, on_space=False):
    """Draw an edition title in the theme's style; returns the right edge."""
    if theme.title_style == "imprint":
        return imprint(canvas, x, baseline, words, size, ink=p.ink if not on_space else "#F3F1EC",
                       muted=mix(p.ink, p.bg, .72), dot=p.accent)
    text = "".join(words).upper() if theme.uppercase_titles else "".join(words)
    key = words[1].upper() if theme.uppercase_titles else words[1]
    prefix = words[0].upper() if theme.uppercase_titles else words[0]
    if theme.title_style == "neon":
        size = int(size * .82)
        layer = Image.new("RGBA", canvas.image.size, (0, 0, 0, 0))
        glow = ImageDraw.Draw(layer)
        face = font(size, True, True)
        glow.text((x + face.getlength(prefix), baseline), key, font=face, anchor="ls", fill=p.accent)
        layer = layer.filter(ImageFilter.GaussianBlur(9))
        canvas.image.paste(layer, (0, 0), layer)
        canvas.draw.text((x, baseline), prefix, font=face, anchor="ls", fill=p.muted)
        canvas.draw.text((x + face.getlength(prefix), baseline), key, font=face, anchor="ls", fill=p.accent)
        end = x + face.getlength(prefix + key)
        canvas.draw.text((end, baseline), words[2].upper(), font=face, anchor="ls", fill=p.ink)
        return end + face.getlength(words[2].upper())
    # block: heavy grotesk caps, key word knocked out of an accent slab.
    face = font(size, True)
    ink = "#F3F1EC" if on_space else p.ink
    canvas.draw.text((x, baseline), prefix, font=face, anchor="ls", fill=ink)
    kx = x + face.getlength(prefix)
    kw = face.getlength(key)
    canvas.draw.rectangle((kx - 6, baseline - size * .80, kx + kw + 8, baseline + size * .14), fill=p.accent)
    canvas.draw.text((kx, baseline), key, font=face, anchor="ls", fill="#0A0A0A")
    end = kx + kw + 14
    canvas.draw.text((end, baseline), words[2].upper().strip(), font=face, anchor="ls", fill=ink)
    return end + face.getlength(words[2].upper().strip())
