"""Display-only series transformations; headline observations stay unchanged."""

from collections import deque
from datetime import date, timedelta
from math import isfinite
from numbers import Real

SENTIMENT_BANDS = (
    {"label": "Extreme fear", "lower": 0, "upper": 20, "color": "#ec5963"},
    {"label": "Fear", "lower": 20, "upper": 40, "color": "#ee9949"},
    {"label": "Neutral", "lower": 40, "upper": 60, "color": "#e8d95b"},
    {"label": "Greed", "lower": 60, "upper": 80, "color": "#a4d641"},
    {"label": "Extreme greed", "lower": 80, "upper": 100, "color": "#28c994"},
)


def year_start(value):
    return date.fromisoformat(str(value)[:10]).replace(month=1, day=1).isoformat()


def smooth_sentiment(rows, window=3):
    """Trailing calendar-day mean, retaining the unmodified daily index.

    Never fills missing dates, extrapolates, or uses future observations. The
    caller must use original rows for headlines and week-over-week changes.
    """
    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        raise ValueError("window must be a positive whole number of days")
    daily = {}
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("date"))[:10])
        except ValueError:
            continue
        value = row.get("value")
        if isinstance(value, Real) and not isinstance(value, bool) and isfinite(value) and 0 <= value <= 100:
            daily[day] = dict(row)
    trail, result = deque(), []
    for day, row in sorted(daily.items()):
        cutoff = day - timedelta(days=window - 1)
        while trail and trail[0][0] < cutoff:
            trail.popleft()
        trail.append((day, row["value"]))
        result.append({**row, "date": day.isoformat(),
                       "smoothed_value": sum(value for _, value in trail) / len(trail)})
    return result
