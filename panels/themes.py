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

from . import trial_styles
from .draw import T_MIN, Canvas, font, imprint, mix, width


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
    strategy: str | None = None   # company colors, kept the same on every sheet
    strive: str | None = None
    zones: tuple | None = None    # the five 200W-zone colors (Friday), cheap → expensive
    cycle: tuple | None = None    # colors handed to cards that carry no accent of their own
    slab2: str | None = None      # second stop of a gradient title slab (HUD)

    def company(self, ticker: str) -> str:
        if ticker in ("MSTR", "STRC", "STRF", "STRK", "STRD", "STRE"):
            return self.strategy or self.accent
        return self.strive or self.accent2


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
                   "#3DFFA2", "#FF4D7A", "#FFE14D", "#FF3DCB", "#FFE14D", outline="#1C2B4A", radius=18, cash="#0F2338",
                   strategy="#22E3FF", strive="#FF3DCB"),
    wednesday=Palette("#0A0714", "#120D22", "#F2E9FF", "#A796C9", "#6C5E8E", "#271C40", "#181129", "#FF3DCB",
                      "#3DFFA2", "#FF4D7A", "#FFE14D", "#22E3FF", "#FFE14D", deep="#FF3DCB", outline="#2C2050", radius=18,
                      strategy="#22E3FF", strive="#FF3DCB"),
    friday=Palette("#04090A", "#0A1416", "#E6FFFB", "#88AEB0", "#557577", "#16292C", "#0E1C1F", "#FFC23D",
                   "#3DFFA2", "#FF4D7A", "#FFE14D", "#22E3FF", "#FF3DCB", band="#3DFFA2", outline="#18333A", radius=18,
                   strategy="#22E3FF", strive="#FF3DCB"),
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



# ── trial looks (panels/trial_styles.py; not on the live page) ─────────────
def _trial(key, label, fontset, surface, *, radius, title_style=None):
    """Neon's day accents and company colors on a trial's own surfaces.
    ``surface`` = (bg, card, tint, line, outline, ink, muted, soft)."""
    bg, card_fill, tint, line, outline, ink, muted, soft = surface

    def day(base: Palette) -> Palette:
        return replace(base, bg=bg, card=card_fill, tint=tint, line=line, outline=outline, ink=ink, muted=muted, soft=soft,
                       radius=radius, cash=tint)
    return Theme(key, label, fontset, day(NEON.monday), day(NEON.wednesday), day(NEON.friday),
                 title_style=title_style or key, decor=key, uppercase_titles=True)


GLASS = _trial("glass", "Aurora Glass", "glass",
               ("#05060C", "#0A0F1E", "#10172B", "#222C4A", "#26304F", "#EEF3FF", "#97A6CC", "#62709A"), radius=26)
HUD = _trial("hud", "Chamfer HUD", "hud",
             ("#020509", "#07101A", "#0B1826", "#153043", "#1D3A50", "#E6F6FF", "#86A7BE", "#557489"), radius=0)
GLITCH = _trial("glitch", "Signal Glitch", "cyber",
                ("#07070B", "#0E0E15", "#15151F", "#25253A", "#2A2A40", "#F4F4FF", "#A3A3C0", "#6C6C8C"), radius=6)
CIRCUIT = _trial("circuit", "Circuit Trace", "circuit",
                 ("#030811", "#08121F", "#0C1A2B", "#16304A", "#1A3552", "#E8F4FF", "#8AA9C9", "#56708F"), radius=14)



# ── Chamfer HUD colorways (trial) ───────────────────────────────────────────
# Gains stay green and losses red in every colorway (+ #3DFF9A, − #FF3B47).
# Company pairs and green/red were checked with the data-viz palette validator
# on each card surface; company names always label their colors.
UP, DOWN = "#3DFF9A", "#FF3B47"


def _hud_way(key, label, surface, *, strategy, strive, days, lines, neutral, zones, cycle=None, slabs=(None, None, None)):
    """``surface`` = (bg, card, tint, line, outline, ink, muted, soft); ``days`` = the
    Monday, Wednesday and Friday accents; ``lines`` = Friday's (50W, 20W/21W band,
    realized) chart colors."""
    bg, card_fill, tint, line, outline, ink, muted, soft = surface
    fifty, band, realized = lines

    def day(base: Palette, accent, slab2) -> Palette:
        return replace(base, bg=bg, card=card_fill, tint=tint, line=line, outline=outline, ink=ink, muted=muted, soft=soft,
                       radius=0, cash=tint, accent=accent, deep=accent, positive=UP, negative=DOWN, neutral=neutral,
                       accent2=fifty, accent3=realized, band=band, strategy=strategy, strive=strive, zones=zones,
                       cycle=cycle, slab2=slab2)
    mon, wed, fri = days
    return Theme(key, label, "hud", day(NEON.monday, mon, slabs[0]), day(NEON.wednesday, wed, slabs[1]),
                 day(NEON.friday, fri, slabs[2]), title_style="hud", decor="hud", uppercase_titles=True)


YELLOW, CYAN = "#FCEE0A", "#00E5FF"
NIGHT_CITY = _hud_way(
    "hud-nightcity", "Chamfer HUD · Night City (yellow + cyan)",
    ("#0A0A05", "#12120A", "#1B1A0F", "#2F2D17", "#45421D", "#F7F5E3", "#BAB58F", "#7E7A58"),
    strategy=CYAN, strive=YELLOW, days=(YELLOW, YELLOW, YELLOW), lines=(CYAN, "#FFF7A6", "#A6F6FF"),
    neutral="#BAB58F", zones=(CYAN, "#7FF2FF", "#D9D6BE", "#FFF27A", YELLOW))

TRON_CYAN, TRON_ORANGE = "#00E1FF", "#FF8A00"
TRON = _hud_way(
    "hud-tron", "Chamfer HUD · Tron (cyan + orange)",
    ("#01060A", "#041019", "#071A2A", "#0E2B42", "#134063", "#E8FDFF", "#80B6CA", "#4F7C91"),
    strategy=TRON_CYAN, strive=TRON_ORANGE, days=(TRON_CYAN, TRON_ORANGE, TRON_CYAN),
    lines=(TRON_ORANGE, "#8CF3FF", "#FFC27A"), neutral="#80B6CA",
    zones=(TRON_CYAN, "#8CF3FF", "#D5E7EE", "#FFC27A", TRON_ORANGE))

LASER_BLUE, LASER_MAGENTA = "#4D8DFF", "#FF2BD6"
LASERLINE = _hud_way(
    "hud-laserline", "Chamfer HUD · Laserline (blue + magenta)",
    ("#05040E", "#0B0A1A", "#121128", "#22204A", "#2F2C66", "#F2F0FF", "#A8A6D8", "#6C6A9C"),
    strategy=LASER_BLUE, strive=LASER_MAGENTA, days=(LASER_BLUE, LASER_MAGENTA, LASER_BLUE),
    lines=(LASER_MAGENTA, "#A9C8FF", "#FF9BEB"), neutral="#A8A6D8",
    zones=(LASER_BLUE, "#A9C8FF", "#D8D6F0", "#FF9BEB", LASER_MAGENTA))

AMBER, HOLO_CYAN, HOLO_MAGENTA = "#FFA726", "#2BD9E8", "#FF3DCB"
BLADE_RUNNER = _hud_way(
    "hud-bladerunner", "Chamfer HUD · Blade Runner (amber + cyan + magenta)",
    ("#0C0705", "#160E0A", "#21150F", "#3A2519", "#553624", "#FFF1E4", "#CDA88C", "#8C6D59"),
    strategy=HOLO_CYAN, strive=HOLO_MAGENTA, days=(AMBER, AMBER, AMBER), lines=(HOLO_CYAN, "#FFD39A", HOLO_MAGENTA),
    neutral="#CDA88C", zones=(HOLO_CYAN, "#9DEFF6", "#E9D8C8", AMBER, HOLO_MAGENTA))

SW_CYAN, SW_MAGENTA, SW_VIOLET, SW_AMBER = "#2DE2FF", "#FF2BD6", "#A56BFF", "#FFB13D"
SYNTHWAVE = _hud_way(
    "hud-synthwave", "Chamfer HUD · Synthwave (cyan, magenta, violet, amber)",
    ("#0B0419", "#140A28", "#1E1038", "#341D5A", "#4A2B80", "#FFF0FF", "#C6A9E8", "#876BAA"),
    strategy=SW_CYAN, strive=SW_MAGENTA, days=(SW_VIOLET, SW_MAGENTA, SW_AMBER), lines=(SW_CYAN, SW_VIOLET, SW_MAGENTA),
    neutral="#C6A9E8", zones=(SW_VIOLET, SW_CYAN, "#D6C8F0", SW_AMBER, SW_MAGENTA),
    cycle=(SW_VIOLET, SW_AMBER, SW_CYAN, SW_MAGENTA), slabs=(SW_MAGENTA, SW_AMBER, SW_MAGENTA))

TK_CYAN, TK_MAGENTA, TK_YELLOW, TK_VIOLET, TK_ORANGE = "#00F0FF", "#FF2BD6", "#FFE600", "#9D5CFF", "#FF9A1A"
NEON_TOKYO = _hud_way(
    "hud-tokyo", "Chamfer HUD · Neon Tokyo (full spectrum)",
    ("#05030D", "#0B0818", "#120E24", "#251E40", "#352C5C", "#F4F2FF", "#ABA5D3", "#6F6A98"),
    strategy=TK_CYAN, strive=TK_MAGENTA, days=(TK_YELLOW, TK_VIOLET, TK_ORANGE), lines=(TK_CYAN, TK_VIOLET, TK_YELLOW),
    neutral=TK_YELLOW, zones=(TK_VIOLET, TK_CYAN, TK_YELLOW, TK_ORANGE, TK_MAGENTA),
    cycle=(TK_VIOLET, TK_YELLOW, TK_ORANGE, TK_CYAN, TK_MAGENTA), slabs=(TK_ORANGE, TK_MAGENTA, TK_YELLOW))

HUD_WAYS = (NIGHT_CITY, TRON, LASERLINE, BLADE_RUNNER, SYNTHWAVE, NEON_TOKYO)

# Blade Runner variants with company colors outside blue and pink: the warm
# family (gold, orange, lemon) against violet, or warm against warm.
BR_SURFACE = ("#0C0705", "#160E0A", "#21150F", "#3A2519", "#553624", "#FFF1E4", "#CDA88C", "#8C6D59")
BR_ORANGE, BR_GOLD, BR_VIOLET = "#FF8C1A", "#FFD04D", "#A67CFF"
BR_VEGAS = _hud_way(
    "br-vegas", "Blade Runner · Vegas Haze (orange × violet, gold title)", BR_SURFACE,
    strategy=BR_ORANGE, strive=BR_VIOLET, days=(BR_GOLD, BR_GOLD, BR_GOLD), lines=(BR_ORANGE, "#FFE6A8", BR_VIOLET),
    neutral="#CDA88C", zones=(BR_VIOLET, "#CDB8FF", "#E9D8C8", BR_GOLD, BR_ORANGE))

TY_GOLD, TY_VIOLET = "#FFCF3F", "#8E6BFF"
BR_TYRELL = _hud_way(
    "br-tyrell", "Blade Runner · Tyrell Gold (gold × deep violet, orange title)",
    ("#090705", "#12100A", "#1C1810", "#332C1A", "#4A4024", "#FFF6E0", "#CDBB8C", "#8C7C58"),
    strategy=TY_GOLD, strive=TY_VIOLET, days=(BR_ORANGE, BR_ORANGE, BR_ORANGE), lines=(TY_GOLD, "#FFC48A", TY_VIOLET),
    neutral="#CDBB8C", zones=(TY_VIOLET, "#BBA6FF", "#E6DCC4", TY_GOLD, BR_ORANGE))

JOI_GOLD = "#FFE14D"
BR_JOI = _hud_way(
    "br-joi", "Blade Runner · Joi (orange × gold, violet title)",
    ("#0B070B", "#140C12", "#1E121B", "#35202F", "#4C2D43", "#FBEFF6", "#C4A6B8", "#86687A"),
    strategy=BR_ORANGE, strive=JOI_GOLD, days=(BR_VIOLET, BR_VIOLET, BR_VIOLET), lines=(BR_ORANGE, "#FFF0A6", "#CDB8FF"),
    neutral="#C4A6B8", zones=("#CDB8FF", BR_VIOLET, "#E6D6DE", JOI_GOLD, BR_ORANGE))

RAIN_LAVENDER, RAIN_LEMON, RAIN_ORANGE = "#C7ABFF", "#F2EA4A", "#FF8A2A"
BR_RAIN = _hud_way(
    "br-rain", "Blade Runner · Rain (lavender × lemon, orange title)",
    ("#0A0908", "#100E0D", "#191614", "#2E2925", "#433C36", "#F4EEE8", "#B9ADA2", "#7C736A"),
    strategy=RAIN_LAVENDER, strive=RAIN_LEMON, days=(RAIN_ORANGE, RAIN_ORANGE, RAIN_ORANGE),
    lines=(RAIN_LAVENDER, "#FFD2A8", RAIN_LEMON), neutral="#B9ADA2",
    zones=(RAIN_LAVENDER, "#E0D2FF", "#E4DDD6", RAIN_LEMON, RAIN_ORANGE))

BR_WAYS = (BR_VEGAS, BR_TYRELL, BR_JOI, BR_RAIN)


# ── Terminal and Broadsheet (trial, built from the style studies) ──────────
# Company colors follow Joi (Strategy orange, Strive gold), deepened on paper.
def _styled(key, label, fontset, decor, surface, *, accent, strategy, strive, lines, neutral, zones, up, down,
            uppercase=True):
    """``surface`` = (bg, card, tint, line, outline, ink, muted, soft); ``lines`` =
    Friday's (50W, 20W/21W band, realized) chart colors."""
    bg, card_fill, tint, line, outline, ink, muted, soft = surface
    fifty, band, realized = lines

    def day(base: Palette) -> Palette:
        return replace(base, bg=bg, card=card_fill, tint=tint, line=line, outline=outline, ink=ink, muted=muted, soft=soft,
                       radius=0, cash=tint, accent=accent, deep=accent, positive=up, negative=down, neutral=neutral,
                       accent2=fifty, accent3=realized, band=band, strategy=strategy, strive=strive, zones=zones)
    return Theme(key, label, fontset, day(NEON.monday), day(NEON.wednesday), day(NEON.friday),
                 title_style=decor, decor=decor, uppercase_titles=uppercase)


TERMINAL = _styled(
    "terminal", "Bloomberg Terminal (amber on black)", "terminal", "terminal",
    ("#000000", "#060606", "#121212", "#262626", "#2E2E2E", "#FFA028", "#C8C8C8", "#808080"),
    accent="#FFFFFF", strategy="#FF8C1A", strive="#FFE14D", lines=("#6FA8FF", "#B8B8B8", "#FFE14D"),
    neutral="#9A9A9A", zones=("#6FA8FF", "#9FC6FF", "#C8C8C8", "#FFB02E", "#FF7A45"), up="#4BE38B", down="#FF5050")

BROADSHEET = _styled(
    "broadsheet", "Broadsheet (newsprint)", "broadsheet", "broadsheet",
    ("#F1ECDF", "#F1ECDF", "#E6DFCD", "#C9BFAB", "#1B1813", "#1B1813", "#5A544A", "#8A8272"),
    accent="#1F3A5F", strategy="#D0620E", strive="#A57C00", lines=("#6F8FAF", "#9A8F7A", "#B07D2B"),
    neutral="#8A8272", zones=("#3F5F7F", "#7F95A8", "#8A8272", "#B07D2B", "#A8452A"), up="#0B7F41", down="#B8232F",
    uppercase=False)

STUDY_WAYS = (TERMINAL, BROADSHEET)

THEMES = {theme.key: theme for theme in (CLASSIC, NEON, ORBIT, GLASS, HUD, GLITCH, CIRCUIT, *HUD_WAYS, *BR_WAYS,
                                                *STUDY_WAYS)}


DEFAULT = NEON


def get(key: str | None) -> Theme:
    return THEMES.get(key or DEFAULT.key, DEFAULT)


# ── shared themed drawing ───────────────────────────────────────────────────
def card(canvas: Canvas, box, p: Palette, accent: str | None = None, theme: Theme = CLASSIC, accent_height=4):
    if theme.decor in trial_styles.DECORS:
        return trial_styles.card(canvas, box, p, accent, theme, accent_height)
    x0, y0, x1, y1 = box
    if theme.decor == "orbit":
        # Brutalist: hard offset shadow, square corners, heavy rule.
        canvas.draw.rectangle((x0 + 8, y0 + 8, x1 + 8, y1 + 8), fill=p.outline or p.ink)
    canvas.draw.rounded_rectangle(box, radius=p.radius, fill=p.card,
                                  outline=p.outline, width=p.outline_width if p.outline else 0)
    if accent and theme.decor == "grid":
        # Neon: a rounded light bar inset along the top edge, with a faint wash beneath it.
        inset = p.radius + 6
        wash = mix(accent, p.card, .07)
        canvas.draw.rounded_rectangle((x0 + 2, y0 + 2, x1 - 2, y0 + 2 + 2 * p.radius), radius=p.radius, fill=wash)
        canvas.draw.rectangle((x0 + 2, y0 + 2 + p.radius, x1 - 2, y0 + 2 + 2 * p.radius), fill=p.card)
        canvas.draw.rounded_rectangle((x0 + inset, y0 - 1, x1 - inset, y0 + accent_height - 1), radius=accent_height // 2, fill=accent)
    elif accent:
        inset = p.radius / 2
        canvas.draw.rectangle((x0 + inset, y0, x1 - inset, y0 + accent_height), fill=accent)


def background(canvas: Canvas, p: Palette, theme: Theme, header_height=150, orbit_at=(1190, 76, .8)):
    """``orbit_at`` = (x, y, scale) of the planet, placed in each header's free space."""
    if theme.decor in trial_styles.DECORS:
        return trial_styles.background(canvas, p, theme, header_height)
    w, h = canvas.image.size
    if theme.decor == "grid":
        # A faint 48-px grid and a soft glow behind the title.
        glow = Image.new("RGB", (w, header_height * 2), p.bg)
        ImageDraw.Draw(glow).ellipse((-w * .2, -header_height, w * .75, header_height * 1.2), fill=mix(p.accent, p.bg, .10))
        canvas.image.paste(glow.filter(ImageFilter.GaussianBlur(90)), (0, 0))
        for x in range(0, w, 48):
            canvas.draw.line((x, 0, x, h), fill=mix(p.line, p.bg, .28), width=1)
        for y in range(0, h, 48):
            canvas.draw.line((0, y, w, y), fill=mix(p.line, p.bg, .28), width=1)
        canvas.draw.rectangle((0, 0, w, 4), fill=p.accent)
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


def kicker(canvas: Canvas, left_x, right_x, left: str, right: str | None, p: Palette, theme: Theme):
    """The report line above the title ("DIGITAL CREDIT REPORT · MONDAY" and the period)."""
    if theme.decor in trial_styles.KICKERS:
        return trial_styles.kicker(canvas, left_x, right_x, left, right, p, theme)
    canvas.text(left_x, 34, left, T_MIN, p.accent, True)
    if right:
        canvas.text(right_x, 34, right, T_MIN, p.accent, True, align="right")


def title(canvas: Canvas, x, baseline, words, size, p: Palette, theme: Theme, *, on_space=False):
    """Draw an edition title in the theme's style; returns the right edge."""
    if theme.decor in trial_styles.DECORS:
        return trial_styles.title(canvas, x, baseline, words, size, p, theme)
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
