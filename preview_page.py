"""Preview tabs for the redesigned Monday, Wednesday and Friday panels.

Opened only with ``?preview=1``; the live Monday/Friday tabs are unchanged.
Every tab fetches fresh data when a browser session opens it (cached for 15
minutes across sessions) and renders the downloadable PNG from those inputs.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

ROOT = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
TABS = ("Monday · The Accretion Ledger", "Wednesday · The Coupon Sheet", "Friday · The Closing Mark")


@st.cache_data(ttl=900, show_spinner=False)
def _extras():
    from panels.extras import load_extras
    return load_extras()


@st.cache_data(ttl=300, show_spinner=False)
def _prices():
    from report.current_prices import load_current_prices, pull_current_prices
    try:
        return pull_current_prices(), False
    except Exception:
        return load_current_prices(), True


@st.cache_data(ttl=300, show_spinner=False)
def _feed():
    from report.filing_monitor import load_monitor_snapshot
    snapshot = load_monitor_snapshot(force=True)
    if snapshot.feed:
        return snapshot.feed
    return json.loads((ROOT / "data" / "latest-report-filings.json").read_text(encoding="utf-8"))


@st.cache_data(ttl=900, show_spinner=False)
def _friday_data():
    from friday.live_inputs import fetch_snapshot
    return fetch_snapshot()


def _monday():
    from report.live_report import resolve_complete_report
    from panels.monday_preview import build_preview
    prices, saved = _prices()
    feed = _feed()
    result = resolve_complete_report(prices, feed)
    return build_preview(result.report, prices, feed, _extras()), result.notice, saved


@st.cache_data(ttl=300, show_spinner=False)
def monday_png():
    from panels.monday_preview import audit_rows, render_png
    preview, notice, saved = _monday()
    png, overflows = render_png(preview)
    return png, overflows, notice, saved, audit_rows(preview)


@st.cache_data(ttl=300, show_spinner=False)
def wednesday_png():
    from panels.wednesday import audit_rows, build, render_png
    preview, _, _ = _monday()
    data = build(_extras(), _feed(), preview)
    png, overflows = render_png(data)
    return png, overflows, audit_rows(data)


@st.cache_data(ttl=300, show_spinner=False)
def friday_png():
    from friday import metrics
    from panels.friday_preview import audit_rows, derive, render_png
    data = _friday_data()
    panel = metrics.compute_panel(data)
    extras = _extras()
    derived = derive(panel, data, extras, _feed())
    png, overflows = render_png(panel, derived, stale=tuple(extras.get("stale") or ()))
    return png, overflows, panel["period"].get("end"), audit_rows(panel, derived)


def _refresh():
    st.cache_data.clear()


def _show(png, name, overflows, notes=(), audit=()):
    st.image(png, width="stretch")
    st.download_button(f"Download {name} panel", data=png, file_name=f"{name.lower()}-preview.png", mime="image/png",
                       icon=":material/download:", on_click="ignore", key=f"download_{name}")
    for note in notes:
        if note:
            st.caption(note)
    if overflows:
        st.warning("Some text was shortened to fit: " + "; ".join(overflows[:5]))
    if audit:
        with st.expander(f"Audit values · {name}", expanded=False):
            st.markdown("\n".join(f"- **{row['metric']}**: {row['value']} · _{row['source']}_" for row in audit))


def render():
    st.markdown("**Preview · not the live report.** Numbers load from the same public sources each time this page opens.")
    st.button("Refresh data", on_click=_refresh, key="preview_refresh")
    extras = _extras()
    if extras.get("stale"):
        st.caption("Saved snapshot used for: " + ", ".join(extras["stale"]))
    monday, wednesday, friday = st.tabs(TABS)
    with monday:
        with st.spinner("Building Monday…"):
            png, overflows, notice, saved, audit = monday_png()
        _show(png, "Monday", overflows, (notice, "Saved quotes (price refresh unavailable)." if saved else ""), audit)
    with wednesday:
        with st.spinner("Building Wednesday…"):
            png, overflows, audit = wednesday_png()
        _show(png, "Wednesday", overflows, (), audit)
    with friday:
        with st.spinner("Building Friday… (full price history, about 10 seconds)"):
            png, overflows, week_end, audit = friday_png()
        _show(png, "Friday", overflows, (f"Week ended {week_end}. After 4:00 pm ET on Friday this becomes the current week.",), audit)
    st.caption(f"Rendered {datetime.now(ET):%b %d, %Y · %I:%M %p ET}")
