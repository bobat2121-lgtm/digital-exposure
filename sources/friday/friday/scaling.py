"""Shared price-only axis limits for interactive charts and PNG exports."""

import math
from numbers import Real


def visible_price_domain(rows, live_point=None, padding=0.08, anchor_key=None):
    """Return a padded domain from the supplied visible market observations.

    Callers select the time window first. Intraday extrema and open/close values
    all qualify; extension bands never influence this domain. Callers may name
    a base SMA to keep it visible when it lies above or below the price range.
    A separate visible live quote may extend it without inventing a candle.
    """
    if not isinstance(padding, Real) or not math.isfinite(padding) or padding < 0:
        raise ValueError("padding must be finite and nonnegative")
    observations = list(rows)
    if live_point is not None:
        observations.append(live_point)
    fields = ("low", "high", "open", "close") + ((anchor_key,) if anchor_key else ())
    values = [float(row[field]) for row in observations
              for field in fields
              if isinstance(row.get(field), Real) and not isinstance(row[field], bool)
              and math.isfinite(row[field]) and row[field] >= 0]
    if not values:
        return 0.0, 1.0
    low, high = min(values), max(values)
    span = high - low
    margin = span * padding if span else max(abs(low) * 0.01, 0.01)
    return max(0.0, low - margin), high + margin
