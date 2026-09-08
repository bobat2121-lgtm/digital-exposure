"""Nonblocking session refreshes over a persistent, shared historical cache."""
from pathlib import Path
from tempfile import gettempdir
from time import monotonic

import streamlit as st

from friday import data as providers
from friday import metrics
from friday.presentation import prepare_chart_specs
from friday.snapshot_service import SnapshotService

SESSION_KEY = 'friday_snapshot_v4'
JOB_KEY = 'friday_snapshot_job_v4'
# Hosting owns the checkout. Historical cache files belong in writable runtime
# storage and can be rebuilt after a host restart without changing report files.
CACHE_PATH = Path(gettempdir()) / 'digital-credit-report' / 'friday-cache' / 'market-snapshot.json'
SOURCE_FIELDS = ('supply_source', 'supply_source_url', 'supply_method', 'sentiment_source', 'sentiment_source_url')


@st.cache_resource(show_spinner=False)
def get_service():
    return SnapshotService(CACHE_PATH, prepare=prepare_chart_specs)


def session_snapshot(state, mode, refresh=None):
    """Every opening/reload/refresh starts fresh work and returns without waiting.

    Only completed results for this session's latest request become readings.
    Cached snapshots are available immediately for dated historical charts;
    freshness.display_panel hides their numeric summaries while work is pending.
    """
    existing = state.get(SESSION_KEY)
    if mode == 'demo':
        if existing is not None and existing['mode'] == mode and refresh is None:
            return existing
        state.pop(JOB_KEY, None)
        data = providers.load_demo()
        panel = metrics.compute_panel(data)
        panel['mode'] = mode
        for field in SOURCE_FIELDS:
            panel[field] = data.get(field)
        state[SESSION_KEY] = {'mode': mode, 'data': data, 'panel': panel,
                              'pending': False, 'error': None, 'updated_at': monotonic()}
        return state[SESSION_KEY]

    if existing is None or existing['mode'] != mode or refresh is not None:
        service = get_service()
        cached = service.peek()
        # A previously completed local result is still useful if shared-cache
        # publication failed; this does not make its readings current.
        if cached is None and existing and existing['mode'] == mode:
            cached = existing
        state[JOB_KEY] = service.request()
        state[SESSION_KEY] = {**(cached or {}), 'mode': mode, 'pending': True,
                              'error': None, 'updated_at': monotonic()}

    snapshot = state[SESSION_KEY]
    future = state.get(JOB_KEY)
    if snapshot.get('pending') and future is not None and future.done():
        try:
            result = future.result()
            snapshot = {**result, 'mode': mode, 'pending': False, 'error': None,
                        'updated_at': monotonic()}
        except Exception:
            # Provider exception details may contain URLs/credentials.
            snapshot = {**snapshot, 'pending': False,
                        'error': 'Fresh readings could not be loaded. Historical charts remain available; press Refresh data to retry.',
                        'updated_at': monotonic()}
        state[SESSION_KEY] = snapshot
        state.pop(JOB_KEY, None)
    return snapshot
