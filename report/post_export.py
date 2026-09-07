"""A fixed, landscape edition for a one-screen weekly social post.

The compact edition consumes the same formatted values as the full report.
Only presentation changes here: compact disclosure text comes from the view,
and the detailed edition retains the transaction audit and methodology.
"""
from __future__ import annotations

from .png_export import (
    INK, MUTED,
    _Canvas, _Text, _fit, _width, _wrap,
)
from .view_types import MetricView, ReportView


WIDTH = 1800
HEIGHT = 1125
MARGIN = 40
GAP = 36
PANEL_WIDTH = (WIDTH - 2 * MARGIN - GAP) // 2
INSET = 29
CONTENT_WIDTH = PANEL_WIDTH - 2 * INSET


def _text(canvas: _Canvas, text: str, left: float, top: float, width: float,
          *, size: int = 23, bold: bool = False, color: str = INK,
          bottom: float = HEIGHT, minimum: int = 17) -> None:
    size = _fit(text, size, width, bold, minimum=minimum)
    canvas.text(_Text(left, top, text, size, bold, color), right=left + width, bottom=bottom)


def _disclosure(canvas: _Canvas, details: tuple[str, ...], left: float, top: float,
                width: float, bottom: float, *, size: int = 19) -> None:
    """Fit the complete compact disclosure; fail rather than crop or ellipsize."""
    if not details:
        return
    text = " · ".join(details)
    for candidate_size in range(size, 16, -1):
        lines = _wrap(text, width, candidate_size)
        line_height = candidate_size + 5
        if top + (len(lines) - 1) * line_height + candidate_size <= bottom:
            for index, line in enumerate(lines):
                _text(canvas, line, left, top + index * line_height, width,
                      size=candidate_size, color=MUTED, bottom=bottom)
            return
    raise ValueError("Compact disclosure exceeds the post layout; provide shorter post_details.")


def _pair(canvas: _Canvas, metric: MetricView, left: float, top: float,
          width: float, *, value_size: int = 31, label_size: int = 23,
          color: str = INK) -> None:
    value_size = _fit(metric.value, value_size, width * .42, True)
    value_width = _width(metric.value, value_size, True)
    _text(canvas, metric.label, left, top + 4, width - value_width - 24,
          size=label_size, bold=True)
    canvas.right(metric.value, left + width, top, value_size, True, color)


def _detail_and_change(canvas: _Canvas, details: tuple[str, ...], change: str,
                       left: float, top: float, width: float, bottom: float) -> None:
    """Keep the formatted change intact while allowing a long missing value."""
    if not change:
        _disclosure(canvas, details, left, top, width, bottom)
        return
    change_size = _fit(change, 19, width * .48, minimum=17)
    change_width = _width(change, change_size)
    _disclosure(canvas, details, left, top, width - change_width - 20, bottom)
    canvas.right(change, left + width, top, change_size, color=MUTED)


def _post_details(metric: MetricView) -> tuple[str, ...]:
    return getattr(metric, "post_details", ()) or metric.details


def render_post_png(view: ReportView) -> bytes:
    """Render the balanced compact edition at 1800 × 1125."""
    from .demo_export import render_redesign_png
    return render_redesign_png(view)
