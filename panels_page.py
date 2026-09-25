"""The public app: Monday, Wednesday and Friday panels.

Each tab fetches fresh data when a browser session opens it (cached briefly
across sessions) and renders the downloadable PNG from those inputs. Only the
open tab builds. ``?report=monday|wednesday|friday`` deep-links a tab and
``?theme=classic|neon|orbit`` picks a style; the detailed Monday and Friday
reports remain at ``?classic=1``.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

ROOT = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
TABS = {"monday": "Monday · The Accretion Ledger", "wednesday": "Wednesday · The Coupon Sheet",
        "friday": "Friday · The Closing Mark"}
STYLES = {"classic": "Classic", "neon": "Neon Ledger", "orbit": "Brutal Orbit"}


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
def monday_png(style="classic"):
    from panels import themes
    from panels.monday_preview import audit_rows, render_png
    preview, notice, saved = _monday()
    png, overflows = render_png(preview, themes.get(style))
    return png, overflows, notice, saved, audit_rows(preview)


@st.cache_data(ttl=300, show_spinner=False)
def wednesday_png(style="classic"):
    from panels import themes
    from panels.wednesday import audit_rows, build, render_png
    preview, _, _ = _monday()
    data = build(_extras(), _feed(), preview)
    png, overflows = render_png(data, themes.get(style))
    return png, overflows, audit_rows(data)


@st.cache_data(ttl=300, show_spinner=False)
def friday_png(style="classic"):
    from friday import metrics
    from panels import themes
    from panels.friday_preview import audit_rows, derive, render_png
    data = _friday_data()
    panel = metrics.compute_panel(data)
    extras = _extras()
    derived = derive(panel, data, extras, _feed())
    png, overflows = render_png(panel, derived, stale=tuple(extras.get("stale") or ()), theme=themes.get(style))
    return png, overflows, panel["period"].get("end"), audit_rows(panel, derived)


def _refresh():
    st.cache_data.clear()


def _show(png, name, style, overflows, notes=(), audit=()):
    st.image(png, width="stretch")
    suffix = "" if style == "classic" else f"-{style}"
    st.download_button(f"Download {name} panel", data=png, file_name=f"{name.lower()}{suffix}.png", mime="image/png",
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
    if "panel_tabs" not in st.session_state:
        st.session_state["panel_tabs"] = TABS.get(st.query_params.get("report"), TABS["monday"])
    if "panel_style" not in st.session_state:
        st.session_state["panel_style"] = st.query_params.get("theme") if st.query_params.get("theme") in STYLES else "classic"
    top = st.columns([3, 2], vertical_alignment="center")
    with top[0]:
        st.segmented_control("Style", list(STYLES), format_func=STYLES.get, key="panel_style", label_visibility="collapsed")
    with top[1]:
        st.button("Refresh data", on_click=_refresh, key="panels_refresh", icon=":material/refresh:")
    style = st.session_state.get("panel_style") or "classic"
    if st.query_params.get("theme", "classic") != style:
        st.query_params["theme"] = style
    if style != "classic":
        st.caption(f"{STYLES[style]} is a cosmetic preview: same numbers, different styling.")
    extras = _extras()
    if extras.get("stale"):
        st.caption("Saved snapshot used for: " + ", ".join(extras["stale"]))
    monday, wednesday, friday = st.tabs(list(TABS.values()), key="panel_tabs", on_change="rerun")
    active = next((key for key, tab in zip(TABS, (monday, wednesday, friday)) if tab.open), "monday")
    if st.query_params.get("report") != active:
        st.query_params["report"] = active
    # Only the open tab fetches and renders.
    if active == "monday":
        with monday, st.spinner("Building Monday…"):
            png, overflows, notice, saved, audit = monday_png(style)
            _show(png, "Monday", style, overflows, (notice, "Saved quotes (price refresh unavailable)." if saved else ""), audit)
    elif active == "wednesday":
        with wednesday, st.spinner("Building Wednesday…"):
            png, overflows, audit = wednesday_png(style)
            _show(png, "Wednesday", style, overflows, (), audit)
    else:
        with friday, st.spinner("Building Friday… (full price history, about 10 seconds)"):
            png, overflows, week_end, audit = friday_png(style)
            _show(png, "Friday", style, overflows,
                  (f"Week ended {week_end}. After 4:00 pm ET on Friday this becomes the current week.",), audit)
    st.caption(f"Rendered {datetime.now(ET):%b %d, %Y · %I:%M %p ET} · "
               "[Detailed Monday and Friday reports](?classic=1)")
