"""Four trial looks for the X images that push Neon Ledger further.

None of them is on the live page. Render them with
``scripts/render_previews.py --themes glass,hud,glitch,circuit``. Each keeps
the layouts, the numbers, the 28-px phone floor and the company colors
(Strategy cyan, Strive magenta). Only surfaces, cards, titles and light change.

glass    Aurora Glass: color blooms behind frosted cards; gradient titles.
hud      Chamfer HUD: cut-corner panels with lit edges, tick rulers, a knockout slab.
glitch   Signal Glitch: RGB-split title, signal streaks, hazard stripes.
circuit  Circuit Trace: routed traces and nodes, chip-outline cards.
terminal Bloomberg Terminal: amber data on black, a blue command bar, reversed title field.
broadsheet  Broadsheet: newsprint, blackletter masthead, serif headline, double and column rules.

The neon looks end with a bloom pass (``bloom``): saturated, bright pixels get a
soft glow and white text stays crisp. Terminal and Broadsheet stay flat.
"""
from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont

from .draw import Canvas, cap_middle, font

DECORS = ("glass", "hud", "glitch", "circuit", "terminal", "broadsheet")
KICKERS = ("terminal", "broadsheet")        # looks that draw their own report line
INSETS = ("terminal",)                      # looks that draw their own shaded boxes
TERMINAL_BLUE = "#1C3494"
STRATEGY, STRIVE, VIOLET = "#22E3FF", "#FF3DCB", "#7B61FF"
# The second stop of each day's title gradient (glass).
GRADIENT_END = {"#22E3FF": VIOLET, "#FF3DCB": "#8F5BFF", "#FFC23D": "#FF5E3A"}


# ── light ───────────────────────────────────────────────────────────────────
def bloom(image: Image.Image, strength=.9, radii=(4, 16), saturation=.5, value=.5) -> Image.Image:
    """Screen a blurred copy of the neon pixels back over the image."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255
    top, low = rgb.max(2), rgb.min(2)
    lit = ((top - low) > saturation * np.maximum(top, 1e-6)) & (top > value)
    source = Image.fromarray((rgb * lit[..., None] * 255).astype(np.uint8))
    glow = sum(np.asarray(source.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32) / 255 for r in radii)
    glow = np.clip(glow / len(radii) * strength, 0, 1)
    # Inside and right against a lit shape (dark text on a chip) the glow would
    # only wash out the ink, so it starts a few pixels out.
    near = np.asarray(Image.fromarray((lit * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)),
                      dtype=np.float32) / 255
    glow *= (1 - np.clip(near * 1.6, 0, 1))[..., None]
    out = 1 - (1 - rgb) * (1 - glow)
    return Image.fromarray((out * 255 + .5).astype(np.uint8))


def _rgb(color):
    return ImageColor.getrgb(color) if isinstance(color, str) else tuple(color)[:3]


def mix(color, background, opacity: float) -> tuple[int, int, int]:
    """draw.mix that also takes RGB tuples (accents can arrive pre-mixed)."""
    return tuple(round(b * (1 - opacity) + a * opacity) for a, b in zip(_rgb(color), _rgb(background)))


def _layer(canvas: Canvas) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    layer = Image.new("RGBA", canvas.image.size, (0, 0, 0, 0))
    return layer, ImageDraw.Draw(layer)


def _over(canvas: Canvas, layer: Image.Image, blur=0):
    if blur:
        layer = layer.filter(ImageFilter.GaussianBlur(blur))
    canvas.image.paste(layer, (0, 0), layer)


def _gradient_line(canvas: Canvas, x0, x1, y, height, color, fade=(1.0, 0.0)):
    """A horizontal bar whose opacity runs from fade[0] to fade[1]."""
    w = max(1, int(x1 - x0))
    alpha = np.linspace(fade[0], fade[1], w, dtype=np.float32)[None, :].repeat(height, 0)
    bar = Image.new("RGBA", (w, height), _rgb(color) + (255,))
    bar.putalpha(Image.fromarray((alpha * 255).astype(np.uint8)))
    canvas.image.paste(bar, (int(x0), int(y)), bar)


def _gradient_text(canvas: Canvas, x, baseline, text, face, start, end, glow=0.0):
    """Text filled with a left-to-right gradient; returns its right edge."""
    w, h = canvas.image.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((x, baseline), text, font=face, anchor="ls", fill=255)
    length = face.getlength(text)
    ramp = np.linspace(0, 1, max(1, int(length)), dtype=np.float32)
    a, b = np.array(_rgb(start), np.float32), np.array(_rgb(end), np.float32)
    row = (a[None, :] * (1 - ramp[:, None]) + b[None, :] * ramp[:, None]).astype(np.uint8)
    fill = np.zeros((h, w, 3), np.uint8)
    left = int(x)
    fill[:, left:left + row.shape[0]] = row[None, :min(row.shape[0], w - left)]
    fill[:, left + row.shape[0]:] = row[-1]
    fill[:, :left] = row[0]
    solid = Image.fromarray(fill)
    if glow:
        halo = mask.filter(ImageFilter.GaussianBlur(12)).point(lambda v: int(v * glow))
        canvas.image.paste(solid, (0, 0), halo)
    canvas.image.paste(solid, (0, 0), mask)
    return x + length


def _title_words(words):
    return words[0].upper(), words[1].upper(), words[2].upper()


def _fit_face(text, size, room, bold=True):
    face = font(size, bold, True)
    while face.getlength(text) > room and size > 40:
        size -= 2
        face = font(size, bold, True)
    return face


# ── background ──────────────────────────────────────────────────────────────
def background(canvas: Canvas, p, theme, header_height=226):
    {"glass": _bg_glass, "hud": _bg_hud, "glitch": _bg_glitch, "circuit": _bg_circuit, "terminal": _bg_terminal,
     "broadsheet": _bg_broadsheet}[theme.decor](canvas, p, header_height)
    if theme.decor == "circuit":
        canvas.finish = lambda image: bloom(_links(canvas, image, p), **BLOOM[theme.decor])
    elif theme.decor == "broadsheet":
        canvas.finish = lambda image: _column_rules(canvas, image, p)
    elif theme.decor in BLOOM:
        canvas.finish = lambda image: bloom(image, **BLOOM[theme.decor])


BLOOM = {"glass": {"strength": .95, "radii": (5, 20)}, "hud": {"strength": .8, "radii": (3, 12)},
         "glitch": {"strength": .75, "radii": (3, 12)}, "circuit": {"strength": .9, "radii": (4, 16)}}


def _bg_glass(canvas: Canvas, p, header_height):
    w, h = canvas.image.size
    k = 8
    blobs = ((260, 40, 520, 260, p.accent, .34), (1300, 120, 420, 240, GRADIENT_END.get(p.accent, VIOLET), .22),
             (330, 900, 440, 620, STRATEGY, .16), (1110, 900, 440, 620, STRIVE, .16),
             (720, h - 80, 620, 300, VIOLET, .16))
    field = Image.new("RGB", (w // k, h // k), p.bg)
    for cx, cy, rx, ry, color, strength in blobs:
        blob = Image.new("RGB", field.size, (0, 0, 0))
        ImageDraw.Draw(blob).ellipse(((cx - rx) / k, (cy - ry) / k, (cx + rx) / k, (cy + ry) / k),
                                     fill=tuple(round(c * strength) for c in _rgb(color)))
        field = ImageChops.add(field, blob.filter(ImageFilter.GaussianBlur(150 / k)))
    canvas.image.paste(field.resize((w, h), Image.BICUBIC))
    _gradient_line(canvas, 0, w, 0, 4, p.accent, (1, .15))


def _bg_hud(canvas: Canvas, p, header_height):
    w, h = canvas.image.size
    draw = canvas.draw
    dot = mix(p.line, p.bg, .9)
    for y in range(16, h, 32):
        for x in range(16, w, 32):
            draw.point((x, y), fill=dot)
            draw.point((x + 1, y), fill=dot)
    draw.rectangle((0, 0, w, 2), fill=p.accent)
    for x in range(0, w, 16):
        color = p.cycle[(x // 160) % len(p.cycle)] if p.cycle else p.accent
        draw.line((x, 3, x, 3 + (10 if x % 160 == 0 else 5)), fill=mix(color, p.bg, .55), width=1)
    corner = mix(p.accent, p.bg, .7)
    for cx, cy, dx, dy in ((12, h - 12, 1, -1), (w - 13, h - 12, -1, -1)):
        draw.line((cx, cy, cx + 28 * dx, cy), fill=corner, width=3)
        draw.line((cx, cy, cx, cy + 28 * dy), fill=corner, width=3)


def _bg_glitch(canvas: Canvas, p, header_height):
    w, h = canvas.image.size
    rng = random.Random(p.accent)
    layer, draw = _layer(canvas)
    for _ in range(70):
        y = rng.choice((rng.uniform(20, header_height + 20), rng.uniform(0, h)))
        x = rng.uniform(-100, w)
        length, thick = rng.uniform(40, 520), rng.choice((1, 1, 2, 2, 3, 5))
        color = _rgb(rng.choice((p.accent, p.accent, STRATEGY, STRIVE)))
        draw.rectangle((x, y, x + length, y + thick), fill=color + (rng.randint(18, 60),))
    for _ in range(14):
        x, y = rng.uniform(w * .55, w - 40), rng.uniform(70, 150)
        draw.rectangle((x, y, x + rng.uniform(6, 40), y + rng.uniform(3, 9)), fill=_rgb(p.accent) + (rng.randint(40, 110),))
    _over(canvas, layer)
    _hazard(canvas, 0, 0, w, 10, p.accent, p.bg)


def _hazard(canvas: Canvas, x0, y0, x1, y1, color, bg, period=22):
    stripe = Image.new("RGB", (int(x1 - x0), int(y1 - y0)), bg)
    draw = ImageDraw.Draw(stripe)
    height = y1 - y0
    for x in range(-int(height), int(x1 - x0) + period, period):
        draw.polygon([(x, height), (x + period / 2, height), (x + period / 2 + height, 0), (x + height, 0)], fill=color)
    canvas.image.paste(stripe, (int(x0), int(y0)))


def _bg_circuit(canvas: Canvas, p, header_height):
    w, h = canvas.image.size
    draw = canvas.draw
    dot = mix(p.line, p.bg, .8)
    for y in range(12, h, 24):  # a faint via grid
        for x in range(12, w, 24):
            draw.point((x, y), fill=dot)
    _gradient_line(canvas, 0, w, 0, 3, p.accent, (1, .2))
    # Buses down both margins, jogging at 45° once.
    for side, xs in ((0, (10, 18, 26)), (1, (w - 11, w - 19, w - 27))):
        for n, x in enumerate(xs):
            color = mix(p.accent if n == 1 else p.line, p.bg, .55 if n == 1 else .9)
            jog, top, bottom = h * (.42 + .06 * n), header_height + 30 + 30 * n, h - 70 - 24 * n
            step = 8 if side == 0 else -8
            draw.line([(x, top), (x, jog), (x + step, jog + 8), (x + step, bottom)], fill=color, width=2, joint="curve")
            draw.ellipse((x - 4, top - 4, x + 4, top + 4), outline=color, width=2)
            draw.ellipse((x + step - 3, bottom - 3, x + step + 3, bottom + 3), fill=color)


def _links(canvas: Canvas, image: Image.Image, p) -> Image.Image:
    """Traces across the gaps between neighboring cards, so the sheet reads as one board."""
    draw = ImageDraw.Draw(image)
    cards = getattr(canvas, "trial_cards", [])
    for a, color_a in cards:
        for b, color_b in cards:
            color = mix(color_a or color_b or p.accent, p.bg, .7)
            gap_x, gap_y = b[0] - a[2], b[1] - a[3]
            overlap_y = min(a[3], b[3]) - max(a[1], b[1])
            overlap_x = min(a[2], b[2]) - max(a[0], b[0])
            if 0 < gap_x <= 32 and overlap_y > 120:
                mid = max(a[1], b[1]) + overlap_y * .5
                for dy in (-10, 10):
                    draw.line((a[2], mid + dy, b[0], mid + dy), fill=color, width=2)
                    for x in (a[2] + 4, b[0] - 4):
                        draw.ellipse((x - 3, mid + dy - 3, x + 3, mid + dy + 3), fill=color)
            if 0 < gap_y <= 32 and overlap_x > 120:
                mid = max(a[0], b[0]) + min(overlap_x * .5, 160)
                for dx in (-10, 10):
                    draw.line((mid + dx, a[3], mid + dx, b[1]), fill=color, width=2)
    return image


# ── cards ───────────────────────────────────────────────────────────────────
def card(canvas: Canvas, box, p, accent, theme, accent_height=4):
    {"glass": _card_glass, "hud": _card_hud, "glitch": _card_glitch, "circuit": _card_circuit, "terminal": _card_terminal,
     "broadsheet": _card_broadsheet}[theme.decor](canvas, box, p, accent, accent_height)


def _rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _card_glass(canvas: Canvas, box, p, accent, accent_height):
    x0, y0, x1, y1 = (int(v) for v in box)
    radius = p.radius
    if accent:  # a soft underglow in the card's color
        layer, glow = _layer(canvas)
        glow.rounded_rectangle((x0 + 30, y0 + 40, x1 - 30, y1 + 10), radius=radius, fill=_rgb(accent) + (70,))
        _over(canvas, layer, blur=34)
    region = canvas.image.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(26))
    frost = Image.blend(region, Image.new("RGB", region.size, _rgb(p.card)), .55)
    frost = Image.blend(frost, Image.new("RGB", region.size, (255, 255, 255)), .035)
    canvas.image.paste(frost, (x0, y0), _rounded_mask(frost.size, radius))
    canvas.draw.rounded_rectangle((x0, y0, x1, y1), radius=radius, outline=mix("#FFFFFF", p.card, .13), width=2)
    # A lit top edge: brightest in the middle, gone at the corners.
    span = x1 - x0 - 2 * radius
    half = span // 2
    _gradient_line(canvas, x0 + radius, x0 + radius + half, y0, 2, "#FFFFFF", (0, .42))
    _gradient_line(canvas, x0 + radius + half, x1 - radius, y0, 2, "#FFFFFF", (.42, 0))
    if accent:
        _gradient_line(canvas, x0 + radius, x1 - radius, y0, max(4, accent_height - 1), accent, (1, .08))


def _chamfer(box, cut):
    x0, y0, x1, y1 = box
    return [(x0, y0), (x1 - cut, y0), (x1, y0 + cut), (x1, y1), (x0 + cut, y1), (x0, y1 - cut)]


def _card_hud(canvas: Canvas, box, p, accent, accent_height):
    x0, y0, x1, y1 = box
    cut = min(28, (y1 - y0) / 6)
    points = _chamfer(box, cut)
    canvas.draw.polygon(points, fill=p.card)
    canvas.draw.line(points + [points[0]], fill=p.outline, width=2, joint="curve")
    if accent is None and p.cycle:
        count = getattr(canvas, "trial_cycle", 0)
        canvas.trial_cycle = count + 1
        accent = p.cycle[count % len(p.cycle)]
    lit = accent or mix(p.accent, p.card, .55)
    # Lit corner: along the top edge, down the cut, a little way down the side.
    canvas.draw.line([(x1 - cut - 150, y0), (x1 - cut, y0), (x1, y0 + cut), (x1, y0 + cut + 46)], fill=lit, width=3, joint="curve")
    canvas.draw.line([(x0, y1 - cut - 46), (x0, y1 - cut), (x0 + cut, y1), (x0 + cut + 90, y1)],
                     fill=mix(lit, p.card, .55), width=3, joint="curve")
    # A slanted tab on the top-left edge.
    canvas.draw.polygon([(x0 + 22, y0 - 3), (x0 + 118, y0 - 3), (x0 + 110, y0 + 5), (x0 + 14, y0 + 5)], fill=lit)


def _card_glitch(canvas: Canvas, box, p, accent, accent_height):
    x0, y0, x1, y1 = box
    rng = random.Random(f"{x0:.0f}{y0:.0f}")
    canvas.draw.rounded_rectangle(box, radius=6, fill=p.card, outline=mix(p.ink, p.card, .09), width=1)
    color = accent or mix(p.accent, p.card, .6)
    canvas.draw.rectangle((x0, y0 + 6, x0 + 5, y1 - 6), fill=color)
    # One slice of the edge bar jumps sideways in the other channel.
    height = y1 - y0
    top = y0 + rng.uniform(.15, .65) * height
    ghost = STRIVE if _rgb(color) == _rgb(STRATEGY) else STRATEGY
    canvas.draw.rectangle((x0 - 5, top, x0 - 1, top + max(18, height * .12)), fill=ghost)
    canvas.draw.rectangle((x0 + 7, top + 10, x0 + 9, top + max(28, height * .12) + 10), fill=color)
    for n, share in enumerate((1, .6, .3)):
        sx = x1 - 22 - n * 14
        canvas.draw.rectangle((sx, y0 + 12, sx + 7, y0 + 19), fill=mix(color, p.card, share))


def _card_circuit(canvas: Canvas, box, p, accent, accent_height):
    x0, y0, x1, y1 = box
    edge = accent or p.outline
    canvas.draw.rounded_rectangle(box, radius=p.radius, fill=p.card, outline=mix(edge, p.card, .42), width=2)
    if accent:
        end = x0 + p.radius + min(220, (x1 - x0) * .42)
        canvas.draw.line((x0 + p.radius, y0, end, y0), fill=accent, width=4)
        canvas.draw.ellipse((end, y0 - 7, end + 14, y0 + 7), fill=p.card, outline=accent, width=3)
    if not hasattr(canvas, "trial_cards"):
        canvas.trial_cards = []
    canvas.trial_cards.append((tuple(box), accent))


# ── titles ──────────────────────────────────────────────────────────────────
def title(canvas: Canvas, x, baseline, words, size, p, theme):
    return {"glass": _title_glass, "hud": _title_hud, "glitch": _title_glitch, "circuit": _title_circuit,
            "terminal": _title_terminal, "broadsheet": _title_broadsheet}[theme.decor](canvas, x, baseline, words, size, p)


def _title_glass(canvas, x, baseline, words, size, p):
    prefix, key, suffix = _title_words(words)
    face = _fit_face(prefix + key + suffix, int(size * .8), canvas.image.width - 2 * x)
    canvas.draw.text((x, baseline), prefix, font=face, anchor="ls", fill=p.muted)
    kx = x + face.getlength(prefix)
    end = _gradient_text(canvas, kx, baseline, key, face, p.accent, GRADIENT_END.get(p.accent, VIOLET), glow=.55)
    canvas.draw.text((end, baseline), suffix, font=face, anchor="ls", fill=p.ink)
    return end + face.getlength(suffix)


def _title_hud(canvas, x, baseline, words, size, p):
    prefix, key, suffix = _title_words(words)
    face = _fit_face(prefix + key + suffix, int(size * 1.0), canvas.image.width - 2 * x - 60)
    draw = canvas.draw
    draw.text((x, baseline), prefix, font=face, anchor="ls", fill=p.ink)
    kx = x + face.getlength(prefix)
    kw = face.getlength(key.strip())
    lead = face.getlength(" ") if key.startswith(" ") else 0
    top, bottom = baseline + face.getbbox("H", anchor="ls")[1] - 12, baseline + 10
    slab = (kx + lead - 14, top, kx + lead + kw + 14, bottom)
    if p.slab2:
        mask = Image.new("L", canvas.image.size, 0)
        ImageDraw.Draw(mask).polygon(_chamfer(slab, 14), fill=255)
        ramp = Image.new("RGB", canvas.image.size, _rgb(p.accent))
        span = int(slab[2] - slab[0])
        a, b = np.array(_rgb(p.accent), np.float32), np.array(_rgb(p.slab2), np.float32)
        t = np.linspace(0, 1, span, dtype=np.float32)[:, None]
        strip = Image.fromarray((a * (1 - t) + b * t).astype(np.uint8)[None, :, :].repeat(int(bottom - top) + 2, 0))
        ramp.paste(strip, (int(slab[0]), int(top)))
        canvas.image.paste(ramp, (0, 0), mask)
    else:
        draw.polygon(_chamfer(slab, 14), fill=p.accent)
    draw.text((kx + lead, baseline), key.strip(), font=face, anchor="ls", fill=p.bg)
    end = kx + lead + kw + 14 + face.getlength(" ") * .6
    draw.text((end, baseline), suffix.strip(), font=face, anchor="ls", fill=p.ink)
    end += face.getlength(suffix.strip())
    # Hatching fills the rest of the line.
    left, right = end + 28, canvas.image.width - x
    if right - left > 90:
        hatch = Image.new("RGB", (int(right - left), int(bottom - top)), p.bg)
        _hatch(hatch, mix(p.accent, p.bg, .38))
        mask = Image.new("L", hatch.size, 0)
        hw, hh = hatch.size
        ImageDraw.Draw(mask).polygon([(hh, 0), (hw, 0), (hw - hh, hh), (0, hh)], fill=255)
        canvas.image.paste(hatch, (int(left), int(top)), mask)
    return end


def _hatch(image, color, period=12):
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for x in range(-h, w + period, period):
        draw.line((x, h, x + h, 0), fill=color, width=3)


def _title_glitch(canvas, x, baseline, words, size, p):
    """Crisp letters over two RGB ghosts; only the ghosts are sliced and displaced."""
    prefix, key, suffix = _title_words(words)
    face = _fit_face(prefix + key + suffix, int(size * .82), canvas.image.width - 2 * x - 20)
    w, h = canvas.image.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((x, baseline), prefix + key + suffix, font=face, anchor="ls", fill=255)
    end = x + face.getlength(prefix + key + suffix)
    rng = random.Random(prefix + key + suffix)
    cap = -face.getbbox("H", anchor="ls")[1]
    for dx, color in ((-5, STRATEGY), (5, STRIVE)):
        ghost = ImageChops.offset(mask, dx, 0)
        for _ in range(3):  # slices of each ghost jump sideways
            top = int(baseline - cap + rng.uniform(0, .85) * cap)
            band = (0, top, w, top + rng.randint(4, 9))
            piece = ghost.crop(band)
            ghost.paste(0, band)
            ghost.paste(piece, (rng.choice((-1, 1)) * rng.randint(10, 26), top))
        canvas.image.paste(Image.new("RGB", (w, h), _rgb(color)), (0, 0), ghost.point(lambda v: int(v * .65)))
    draw = canvas.draw
    draw.text((x, baseline), prefix, font=face, anchor="ls", fill=p.ink)
    kx = x + face.getlength(prefix)
    draw.text((kx, baseline), key, font=face, anchor="ls", fill=p.accent)
    draw.text((kx + face.getlength(key), baseline), suffix, font=face, anchor="ls", fill=p.ink)
    return end


def _title_circuit(canvas, x, baseline, words, size, p):
    prefix, key, suffix = _title_words(words)
    face = _fit_face(prefix + key + suffix, int(size * .78), canvas.image.width - 2 * x - 80)
    layer, glow = _layer(canvas)
    kx = x + face.getlength(prefix)
    glow.text((kx, baseline), key, font=face, anchor="ls", fill=_rgb(p.accent) + (255,))
    _over(canvas, layer, blur=10)
    draw = canvas.draw
    draw.text((x, baseline), prefix, font=face, anchor="ls", fill=p.muted)
    draw.text((kx, baseline), key, font=face, anchor="ls", fill=p.accent)
    end = kx + face.getlength(key)
    draw.text((end, baseline), suffix, font=face, anchor="ls", fill=p.ink)
    end += face.getlength(suffix)
    # A trace runs from the title to the margin and ends in a node.
    y = baseline - int(-face.getbbox("H", anchor="ls")[1] / 2)
    right = canvas.image.width - x - 10
    if right - end > 120:
        color = mix(p.accent, p.bg, .75)
        draw.line([(end + 24, y), (right - 60, y), (right - 36, y - 24)], fill=color, width=3, joint="curve")
        draw.ellipse((right - 44, y - 42, right - 20, y - 18), outline=p.accent, width=3)
        draw.ellipse((end + 18, y - 6, end + 30, y + 6), fill=p.accent)
    return end


# ── Bloomberg Terminal ──────────────────────────────────────────────────────
def _bg_terminal(canvas: Canvas, p, header_height):
    """Plain black: the terminal's look is its type and its bars."""


def _card_terminal(canvas: Canvas, box, p, accent, accent_height):
    x0, y0, x1, y1 = box
    canvas.draw.rectangle(box, fill=p.card, outline=p.outline, width=2)
    canvas.draw.rectangle((x0, y0, x1, y0 + 6), fill=accent or TERMINAL_BLUE)


def inset(canvas: Canvas, box, fill, radius, p, theme):
    """Terminal: a square shaded box under a blue strip, like the sections on Wed/Fri."""
    x0, y0, x1, y1 = box
    canvas.draw.rectangle(box, fill=fill)
    canvas.draw.rectangle((x0, y0, x1, y0 + 5), fill=TERMINAL_BLUE)


def _title_terminal(canvas, x, baseline, words, size, p):
    """THE [ACCRETION] LEDGER <GO>: the key word as a reversed amber field."""
    prefix, key, suffix = _title_words(words)
    go = "<GO>"
    face = _fit_face(prefix + key + suffix + " " + go, int(size * .84), canvas.image.width - 2 * x)
    draw = canvas.draw
    draw.text((x, baseline), prefix, font=face, anchor="ls", fill="#FFFFFF")
    kx = x + face.getlength(prefix)
    word = key.strip()
    lead = face.getlength(" ") if key.startswith(" ") else 0
    top = baseline + face.getbbox("H", anchor="ls")[1] - 10
    kw = face.getlength(word)
    draw.rectangle((kx + lead - 8, top, kx + lead + kw + 8, baseline + 12), fill=p.ink)
    draw.text((kx + lead, baseline), word, font=face, anchor="ls", fill=p.bg)
    end = kx + lead + kw + face.getlength(" ")
    draw.text((end, baseline), suffix.strip(), font=face, anchor="ls", fill="#FFFFFF")
    end += face.getlength(suffix.strip())
    small = font(30, True, False)
    draw.text((end + 18, baseline), go, font=small, anchor="ls", fill=p.soft)
    return end


def _kicker_terminal(canvas: Canvas, left_x, right_x, left, right, p):
    """The command bar: [DCR] <GO> and the report line on terminal blue."""
    w = canvas.image.width
    canvas.draw.rectangle((0, 18, w, 70), fill=TERMINAL_BLUE)
    face = font(28, True, False)
    tag = "DCR"
    tw = face.getlength(tag)
    # Every piece of the bar is centered on its capitals, on the bar's middle line (44).
    y = 44 - cap_middle(28, True)
    canvas.draw.rectangle((left_x - 6, 24, left_x + tw + 8, 64), fill=p.ink)
    canvas.draw.text((left_x + 1, y), tag, font=face, anchor="lt", fill=p.bg)
    x = canvas.text(left_x + tw + 22, y, "<GO>", 28, "#FFFFFF", True)
    right_edge = right_x - (face.getlength(right) + 30 if right else 0)
    canvas.text(x + 18, 44 - cap_middle(28, False), left, 28, "#FFFFFF", False, max_width=right_edge - x - 18)
    if right:
        canvas.text(right_x, y, right, 28, p.ink, True, align="right")


# ── Broadsheet ──────────────────────────────────────────────────────────────
MASTHEAD = "The Digital Credit Report"


def _bg_broadsheet(canvas: Canvas, p, header_height):
    """Newsprint, a touch darker toward the edges."""
    w, h = canvas.image.size
    yy, xx = np.mgrid[0:h:8, 0:w:8].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w * .75)) ** 2 + ((yy - h / 2) / (h * .75)) ** 2)
    shade = np.clip((d - .45) * .10, 0, .06)[..., None]
    paper = np.array(_rgb(p.bg), np.float32)
    small = Image.fromarray((paper * (1 - shade) + np.array([96, 80, 50], np.float32) * shade).astype(np.uint8))
    canvas.image.paste(small.resize((w, h), Image.BILINEAR))


def _card_broadsheet(canvas: Canvas, box, p, accent, accent_height):
    """A section, not a box: a heavy rule over a hairline, flagged in the company color."""
    x0, y0, x1, y1 = box
    canvas.draw.rectangle((x0, y0, x1, y0 + 3), fill=p.ink)
    canvas.draw.rectangle((x0, y0 + 8, x1, y0 + 9), fill=p.ink)
    if accent:
        canvas.draw.rectangle((x0, y0 - 3, x0 + min(150, (x1 - x0) * .35), y0 + 3), fill=accent)
    if not hasattr(canvas, "trial_cards"):
        canvas.trial_cards = []
    canvas.trial_cards.append((tuple(box), accent))


def _column_rules(canvas: Canvas, image: Image.Image, p) -> Image.Image:
    """Hairline column rules in the gutters between side-by-side sections."""
    draw = ImageDraw.Draw(image)
    cards = [box for box, _ in getattr(canvas, "trial_cards", [])]
    for a in cards:
        for b in cards:
            gap = b[0] - a[2]
            overlap = min(a[3], b[3]) - max(a[1], b[1])
            if 0 < gap <= 48 and overlap > 80:
                x = (a[2] + b[0]) / 2
                draw.line((x, max(a[1], b[1]) + 16, x, min(a[3], b[3])), fill=_rgb(p.ink), width=1)
    return image


def _title_broadsheet(canvas, x, baseline, words, size, p):
    """The headline in a heavy Didone-style serif, set in sentence case."""
    text = "".join(words)
    face = _fit_face(text, int(size * .9), canvas.image.width - 2 * x)
    canvas.draw.text((x, baseline), text, font=face, anchor="ls", fill=p.ink)
    return x + face.getlength(text)


def _kicker_broadsheet(canvas: Canvas, left_x, right_x, left, right, p):
    """The masthead, the edition line and the double rule under them."""
    from .draw import ASSETS
    mast = ImageFont.truetype(str(ASSETS / "unifrakturmaguntia.ttf"), 52)
    # Baseline 56: the masthead's descenders (11 px) clear the rule at 72, and the
    # edition line sits on the same baseline.
    baseline = 56
    canvas.draw.text((left_x, baseline), MASTHEAD, font=mast, anchor="ls", fill=p.ink)
    day = left.split("·")[-1].strip().title()
    line = f"{day} edition" + (f" · {right}" if right else "")
    canvas.text(right_x, baseline, line.upper(), 28, p.ink, True, align="right",
                max_width=right_x - left_x - mast.getlength(MASTHEAD) - 40, anchor_top=False)
    canvas.draw.rectangle((left_x, 72, right_x, 76), fill=p.ink)
    canvas.draw.rectangle((left_x, 81, right_x, 82), fill=p.ink)


def kicker(canvas: Canvas, left_x, right_x, left, right, p, theme):
    {"terminal": _kicker_terminal, "broadsheet": _kicker_broadsheet}[theme.decor](canvas, left_x, right_x, left, right, p)
