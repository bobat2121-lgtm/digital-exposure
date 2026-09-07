"""Render the fixed Imprint wordmark; no font software is copied into the output.

Example: python scripts/build_brand_title.py --serif-font C:/Windows/Fonts/georgiab.ttf
The app consumes the transparent PNG, so its Linux host needs no Georgia install.
"""
from argparse import ArgumentParser
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo


ASSETS = Path(__file__).resolve().parents[1] / "assets"
EM = 160


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--serif-font", type=Path, required=True)
    args = parser.parse_args()
    sans = ImageFont.truetype(str(ASSETS / "report-regular.ttf"), EM)
    serif = ImageFont.truetype(str(args.serif_font), EM)
    image = Image.new("RGBA", (5000, 320))
    draw = ImageDraw.Draw(image)
    x, baseline = 4.0, 220
    for text, font, spacing, color in (
        ("The ", sans, -.04 * EM, "#52646d"),
        ("Digital Credit", serif, -.06 * EM, "#1b2c34"),
        (" Report", sans, -.04 * EM, "#52646d"),
    ):
        for index, character in enumerate(text):
            advance = font.getlength(text[:index + 1]) - font.getlength(character)
            draw.text((x + advance + index * spacing, baseline), character,
                      font=font, anchor="ls", fill=color)
        x += font.getlength(text) + len(text) * spacing
    # Match the website's 6px dot, 5px gap and 1px baseline lift at 33px type.
    dot = EM * 6 / 33
    x += EM * 5 / 33
    bottom = baseline - EM / 33
    draw.ellipse((x, bottom - dot, x + dot, bottom), fill="#e88029")
    image = image.crop(image.getchannel("A").getbbox())
    metadata = PngInfo()
    metadata.add_text("Title", "The Digital Credit Report")
    metadata.add_text("EmSize", str(EM))
    metadata.add_text("Description", "Fixed Imprint wordmark: Georgia Bold and Lato Regular, orange endpoint.")
    target = ASSETS / "title-imprint.png"
    image.save(target, pnginfo=metadata, optimize=True)
    print(f"{target}: {image.width} × {image.height}")


if __name__ == "__main__":
    main()
