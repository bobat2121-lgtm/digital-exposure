"""Optional build step: python -m pip install fonttools brotli; run this file.

The application needs only the generated WOFF2 assets, not these build tools.
"""
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ASSETS = Path(__file__).resolve().parents[1] / "assets"
UNICODES = set(range(0x20, 0x180)) | set(range(0x370, 0x400)) | set(range(0x2000, 0x2300))


def build(style: str) -> None:
    font = TTFont(ASSETS / f"report-{style.lower()}.ttf")
    # Lato is a reserved name. Give this subset its own internal family name;
    # preserve the original copyright, author, and license records.
    names = {1: "Credit Report Sans", 2: style,
             3: f"Credit Report Sans subset 1.0 {style}",
             4: f"Credit Report Sans {style}", 6: f"CreditReportSans-{style}",
             16: "Credit Report Sans", 17: style}
    for record in font["name"].names:
        if record.nameID in names:
            record.string = names[record.nameID].encode(record.getEncoding())
    options = subset.Options()
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17]
    options.name_languages = [0x409]
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=UNICODES)
    subsetter.subset(font)
    font.flavor = "woff2"
    destination = ASSETS / f"report-{style.lower()}.woff2"
    font.save(destination)
    print(f"{destination.name}: {destination.stat().st_size:,} bytes")


if __name__ == "__main__":
    for style in ("Regular", "Bold"):
        build(style)
