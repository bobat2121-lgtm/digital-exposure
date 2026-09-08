"""Monday report adapter for the isolated two-report demo.

Importing this module fetches nothing and renders nothing. The shell owns page
configuration and calls render() only for the active tab.
"""
from dataclasses import dataclass
from time import monotonic

import streamlit as st

from report.current_report import current_report
from report.filing_monitor import MonitorSnapshot, load_monitor_snapshot, render_monitor
from report.live_report import resolve_live_report
from report.methodology import PUBLIC_METHODOLOGY
from report.models import Report
from report.post_export import render_post_png
from report.price_refresh import PriceStore
from report.presentation import build_report_view
from report.public_page import public_stylesheet, render_public_report
from report.view_types import ReportView


PRICES = "monday_page_prices"
PREPARED = "monday_prepared_report"
MONITOR = "monday_monitor_snapshot"
PROBLEM = "monday_report_problem"
LAST_POLL = "monday_last_monitor_check"
REFRESH = "monday_refresh_requested"
SKIP_POLL = "monday_skip_initial_poll"
POLL_SECONDS = 15


@dataclass(frozen=True)
class PreparedMonday:
    report: Report
    view: ReportView
    html: str
    png: bytes
    notice: str | None
    version: str


@st.cache_resource(show_spinner=False)
def price_store():
    return PriceStore()


@st.cache_data(show_spinner=False, max_entries=16)
def downloadable_report(view):
    return render_post_png(view)


@st.cache_data(show_spinner=False, max_entries=1)
def stylesheet():
    return public_stylesheet()


def prepare_snapshot(report, prices, *, notice=None, version="saved"):
    """Prepare both outputs before publishing either one to session state."""
    view = build_report_view(report, prices=prices)
    html = render_public_report(view)
    png = downloadable_report(view)
    return PreparedMonday(report, view, html, png, notice, version)


def refresh_report(state, *, force_monitor=False):
    """SEC updates retain the session's quote marks and last complete output."""
    state[LAST_POLL] = monotonic()
    state[PROBLEM] = None
    snapshot = load_monitor_snapshot(force=force_monitor)
    state[MONITOR] = snapshot
    previous = state.get(PREPARED)
    if snapshot.stale and previous is not None:
        return previous
    prices = state[PRICES].prices
    try:
        result = resolve_live_report(prices, snapshot.feed or {"schemaVersion": 1, "filings": []})
        candidate = prepare_snapshot(result.report, prices, notice=result.notice, version=result.version)
    except (ValueError, OSError, TypeError, KeyError):
        state[PROBLEM] = "New filing update could not be applied."
        if previous is not None:
            return previous
        try:
            candidate = prepare_snapshot(current_report(prices), prices)
        except (ValueError, OSError, TypeError, KeyError):
            return None
    state[PREPARED] = candidate
    return candidate


def _request_refresh():
    st.session_state[REFRESH] = True


def _active():
    return st.session_state.get("weekly_active_report", "Monday") == "Monday"


@st.fragment(run_every="15s")
def financial_report():
    if not _active():
        return
    state = st.session_state
    # A tab revisit immediately shows its completed snapshot. Subsequent timer
    # ticks perform the normal SEC checks without refetching market prices.
    skip = state.pop(SKIP_POLL, False)
    if not skip and monotonic() - state.get(LAST_POLL, 0) >= POLL_SECONDS:
        refresh_report(state)
    prepared = state.get(PREPARED)
    if prepared is None:
        st.error("The Monday report is temporarily unavailable. Try Refresh data.")
        return
    snapshot = state.get(MONITOR) or MonitorSnapshot(None, None, stale=True, notice="SEC refresh unavailable.")
    st.html(prepared.html)
    if state[PRICES].using_saved_prices:
        st.caption("Price refresh unavailable · showing last saved quotes.")
    if snapshot.stale or state.get(PROBLEM):
        reason = state.get(PROBLEM) or snapshot.notice or "SEC refresh unavailable."
        st.caption(f"{reason} Retained report · {prepared.view.subtitle}.")
    if prepared.notice:
        st.caption(prepared.notice)
    with st.expander("Calculation overview", expanded=False):
        st.markdown(PUBLIC_METHODOLOGY.replace("$", r"\$"))
    with st.expander("Latest SEC filings", expanded=False):
        render_monitor(snapshot)
    st.download_button(
        "Download Monday panel", data=prepared.png, file_name="monday-digital-credit-report.png",
        mime="image/png", key="monday_download", icon=":material/download:", type="tertiary",
        help="Save the displayed report snapshot as a panel-only 1800 × 1125 PNG.", on_click="ignore",
    )


def render():
    if not _active():
        return
    st.html(stylesheet())
    st.button("Refresh data", key="monday_refresh", on_click=_request_refresh,
              help="Refresh Monday market prices and SEC data together.")
    state = st.session_state
    manual = state.pop(REFRESH, False)
    first_open = PRICES not in state
    if first_open or manual:
        with st.spinner("Updating Monday data…"):
            result = price_store().refresh()
            if result.prices is not None:
                state[PRICES] = result
                refresh_report(state, force_monitor=manual)
            elif PREPARED not in state:
                st.error("The Monday report is temporarily unavailable. Try Refresh data.")
                return
            else:
                state[PROBLEM] = "Price refresh unavailable."
    elif PREPARED not in state:
        refresh_report(state)
    state[SKIP_POLL] = True
    financial_report()
