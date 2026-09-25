"""The public app: Monday, Wednesday and Friday reports.

Each tab shows a web layout built for reading on a computer or a phone
(``panels.web``), from the same data as the X image. The X image, the phone-first
PNG, is the download at the bottom of each tab, after the formulas and sources.
Each tab fetches fresh data when a browser session opens it (cached briefly
across sessions), and only the open tab builds.
``?report=monday|wednesday|friday`` deep-links a tab; the detailed Monday and
Friday reports remain at ``?classic=1``. The page has one style (Neon Ledger) and
one Monday funding layout (the waterfall), so every shared link looks the same.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

ROOT = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
TABS = {"monday": "Monday · Accretion Ledger", "wednesday": "Wednesday · Coupon Sheet",
        "friday": "Friday · Closing Mark"}


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
def monday_report():
    from panels.monday_preview import audit_rows, notes, render_png
    preview, notice, saved = _monday()
    png, overflows = render_png(preview)
    return {"preview": preview, "png": png, "overflows": overflows, "audit": audit_rows(preview), "notes": notes(preview),
            "notices": [line for line in (notice, "Saved quotes (price refresh unavailable)." if saved else "") if line]}


@st.cache_data(ttl=300, show_spinner=False)
def wednesday_report():
    from panels.wednesday import audit_rows, build, notes, render_png
    preview, _, _ = _monday()
    data = build(_extras(), _feed(), preview)
    png, overflows = render_png(data)
    return {"data": data, "png": png, "overflows": overflows, "audit": audit_rows(data), "notes": notes(data, extra=True),
            "notices": []}


@st.cache_data(ttl=300, show_spinner=False)
def friday_report():
    from friday import metrics
    from panels.friday_preview import audit_rows, derive, notes, render_png
    data = _friday_data()
    panel = metrics.compute_panel(data)
    extras = _extras()
    stale = tuple(extras.get("stale") or ())
    derived = derive(panel, data, extras, _feed())
    png, overflows = render_png(panel, derived, stale=stale)
    week_end = panel["period"].get("end")
    return {"panel": panel, "derived": derived, "png": png, "overflows": overflows, "audit": audit_rows(panel, derived),
            "notes": notes(panel, derived, stale, extra=True),
            "notices": [f"Week ended {week_end}. After 4:00 pm ET on Friday this becomes the current week."] if week_end else []}


def _refresh():
    st.cache_data.clear()


def _download(name: str, report: dict):
    """The X image: the phone-first PNG, offered as a download with a preview."""
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        st.download_button("Download X image", data=report["png"], file_name=f"{name.lower()}.png", mime="image/png",
                           icon=":material/download:", on_click="ignore", key=f"download_{name}")
        with st.popover("Preview X image", icon=":material/image:"):
            st.image(report["png"], width="stretch")
    if report["overflows"]:
        st.warning("Some text in the X image was shortened to fit: " + "; ".join(report["overflows"][:5]))


def _footer(name: str, formulas, report: dict):
    """The end of every tab: formulas, sources, then the X image download."""
    from panels import web
    web.formulas(formulas)
    web.sources(report["notes"], report["audit"])
    _download(name, report)


def render():
    from panels import web
    web.style()
    if "panel_tabs" not in st.session_state:
        st.session_state["panel_tabs"] = TABS.get(st.query_params.get("report"), TABS["monday"])
    with st.container(horizontal=True, vertical_alignment="center"):
        st.html('<div class="dcr-kicker" style="color:#8FA2CC">The Digital Credit Report</div>')
        st.button("Refresh data", on_click=_refresh, key="panels_refresh", icon=":material/refresh:")
    extras = _extras()
    stale = [section for section in extras.get("stale") or ()]
    if stale:
        st.caption("Saved snapshot used for: " + ", ".join(stale))
    monday, wednesday, friday = st.tabs(list(TABS.values()), key="panel_tabs", on_change="rerun")
    active = next((key for key, tab in zip(TABS, (monday, wednesday, friday)) if tab.open), "monday")
    if st.query_params.get("report") != active:
        st.query_params["report"] = active
    for retired in ("theme", "layout", "extra"):  # options removed so every shared link looks the same
        if retired in st.query_params:
            del st.query_params[retired]
    # Only the open tab fetches and renders.
    if active == "monday":
        with monday:
            with st.spinner("Building Monday…"):
                report = monday_report()
            web.monday(report["preview"], notices=report["notices"])
            _footer("Monday", web.MONDAY_FORMULAS, report)
    elif active == "wednesday":
        with wednesday:
            with st.spinner("Building Wednesday…"):
                report = wednesday_report()
            web.wednesday(report["data"], notices=report["notices"])
            _footer("Wednesday", web.WEDNESDAY_FORMULAS, report)
    else:
        with friday:
            with st.spinner("Building Friday… (full price history, about 10 seconds)"):
                report = friday_report()
            web.friday(report["panel"], report["derived"], notices=report["notices"])
            _footer("Friday", web.FRIDAY_FORMULAS, report)
    st.caption(f"Rendered {datetime.now(ET):%b %d, %Y · %I:%M %p ET} · "
               "[Detailed Monday and Friday reports](?classic=1)")
