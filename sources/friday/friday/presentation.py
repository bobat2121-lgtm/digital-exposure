"""Bounded presentation caches; chart data and PNG calculations stay exact."""
from functools import lru_cache, partial
import json

import streamlit as st

from friday.charts import sma_chart, supply_chart, sentiment_chart, weekly_volume
from friday.export import render_png


@st.cache_data(show_spinner=False, max_entries=48)
def chart_spec(kind, payload, *, ticker=None, view=None, latest=None, show_current=True):
    """UI fallback; background preparation uses the same pure builder."""
    return build_chart_spec(kind, payload, ticker=ticker, view=view, latest=latest, show_current=show_current)


def build_chart_spec(kind, payload, *, ticker=None, view=None, latest=None, show_current=True):
    """No Streamlit calls: safe to prepare before publishing a background job."""
    return _build_chart_spec(kind, json.dumps(payload, sort_keys=True), ticker, view,
                             json.dumps(latest, sort_keys=True), show_current)


@lru_cache(maxsize=96)
def _build_chart_spec(kind, payload_json, ticker, view, latest_json, show_current):
    payload, latest = json.loads(payload_json), json.loads(latest_json)
    if kind == "sma":
        chart = sma_chart(payload, ticker, height=390, view=view)
    elif kind == "supply":
        chart = supply_chart(payload, height=360)
    elif kind == "sentiment":
        chart = sentiment_chart(payload, height=360, latest=latest, show_current=show_current)
    elif kind == "volume":
        chart = weekly_volume(payload, height=250)
    else:
        raise ValueError("Unknown chart kind")
    if chart is None:
        return None
    spec = chart.to_dict()
    # Streamlit supports this renderer override. Canvas keeps every point and
    # tooltip while avoiding thousands of SVG elements on the page.
    spec["usermeta"] = {"embedOptions": {"renderer": "canvas"}}
    return spec


def prepare_chart_specs(panel):
    """Prepare opening periods and a historical-only view before the UI needs them.

    The historical view has no current quote or sentiment marker. Cache keys
    contain exact historical inputs, so quote-only refreshes reuse its specs.
    """
    ready, history = {}, {}
    volume = {row['ticker']: row for row in panel.get('liquidity', [])}
    for name, tickers in [('common', ('MSTR', 'ASST')), ('preferred', ('STRC', 'SATA'))]:
        spec = build_chart_spec('volume', [volume.get(t, {'ticker': t}) for t in tickers])
        ready[f'volume:{name}'] = history[f'volume:{name}'] = spec
    supply = panel.get('live_supply_loss', panel.get('supply_loss', {}))
    ready['supply'] = history['supply'] = build_chart_spec('supply', supply.get('series', []))
    sentiment = panel.get('live_sentiment', panel.get('sentiment', {}))
    ready['sentiment'] = build_chart_spec('sentiment', sentiment.get('series', []), latest=sentiment.get('live_point'))
    history['sentiment'] = build_chart_spec('sentiment', sentiment.get('series', []), show_current=False)
    for ticker in ('BTC', 'MSTR', 'ASST'):
        trend = panel.get('live_trends', panel.get('trends', {})).get(ticker, {})
        payload = {field: trend.get(field) for field in ('series', 'live_point', 'price_as_of')}
        historical = {'series': trend.get('series', []), 'live_point': None, 'price_as_of': None}
        # Do not delay fresh readings by preparing every possible period.
        # Alternate periods use the same full history and are cached on demand.
        views = ('4Y',) if ticker == 'BTC' else ('YTD',) if ticker == 'ASST' else ('1Y',)
        for view in views:
            key = f'sma:{ticker}:{view}'
            ready[key] = build_chart_spec('sma', payload, ticker=ticker, view=view)
            history[key] = build_chart_spec('sma', historical, ticker=ticker, view=view)
    return {'ready': ready, 'history': history}


def displayed_export_panel(panel, *, snapshot_as_of=None):
    """Copy the visible report, keeping its financial week and chart dates distinct.

    ``panel`` must be the freshness-filtered display model, so unavailable
    readings remain unavailable in the image. No provider or clock is consulted.
    The JSON roundtrip makes this independent of subsequent session updates.
    """
    fields = ("mode", "period", "header", "liquidity", "treasury", "trends",
              "sentiment", "supply_loss", "supply_source", "supply_source_url",
              "supply_method", "sentiment_source", "sentiment_source_url")
    projected = {field: panel.get(field) for field in fields}
    if panel.get("mode") == "latest":
        for target, live in (("trends", "live_trends"), ("supply_loss", "live_supply_loss"),
                             ("sentiment", "live_sentiment")):
            if live in panel:
                projected[target] = panel[live]
        projected["chart_cutoff"] = snapshot_as_of
        projected["export_basis"] = "displayed_latest"
    else:
        projected["chart_cutoff"] = (panel.get("period") or {}).get("end")
        projected["export_basis"] = "synthetic_preview"
    projected["snapshot_as_of"] = snapshot_as_of
    return json.loads(json.dumps(projected, allow_nan=False))


def frozen_export_key(panel, *, snapshot_as_of=None):
    """Capture the displayed dataset, including live values and provenance."""
    return json.dumps(displayed_export_panel(panel, snapshot_as_of=snapshot_as_of),
                      sort_keys=True, separators=(",", ":"), allow_nan=False)


@lru_cache(maxsize=8)
def _cached_png(snapshot_json):
    return render_png(json.loads(snapshot_json))


def deferred_png(panel, *, snapshot_as_of=None):
    """Freeze the displayed dataset now; only render those bytes on download."""
    return partial(_cached_png, frozen_export_key(panel, snapshot_as_of=snapshot_as_of))
