"""The approved fixed wordmark, rendered without host-specific font dependencies."""
from functools import lru_cache
from pathlib import Path

from PIL import Image


TITLE = "The Digital Credit Report"


@lru_cache(maxsize=8)
def _wordmark(size: int) -> Image.Image:
    with Image.open(Path(__file__).resolve().parents[1] / "assets/title-imprint.png") as source:
        scale = size / int(source.info["EmSize"])
        image = source.convert("RGBA")
    return image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)


def draw_title(canvas, title: str, left: int, top: int, *, size: int, width: int) -> bool:
    """Draw the approved brand, or let the caller handle a different title."""
    if title != TITLE:
        return False
    image = _wordmark(size)
    if image.width > width or left < 0 or top < 0 or left + image.width > canvas.image.width or top + image.height > canvas.image.height:
        raise ValueError("The report wordmark would exceed the export header.")
    canvas.image.paste(image, (left, top), image)
    return True
