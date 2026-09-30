"""The public app: Monday, Wednesday and Friday reports.

Two styles, chosen at the top of the page: Bloomberg (the default) and
Broadsheet. Under the switch, each day's tab shows a web layout built for reading
on a computer or a phone (``panels.web``), from the same data as the X image. The
X image, the phone-first PNG in the chosen style, is the download at the bottom
of each tab, after the formulas and sources. ``?style=bloomberg|broadsheet`` and
``?report=monday|wednesday|friday`` deep-link a view; the detailed Monday and
Friday reports remain at ``?classic=1``.

Speed: the data sources refresh in the background (``panels.live``), so a view
never waits on a slow provider; only the open tab builds; and the X image is
drawn when it is downloaded or previewed, with prices as of that click.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

ROOT = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
TABS = {"monday": "Monday · Accretion Ledger", "wednesday": "Wednesday · Coupon Sheet",
        "friday": "Friday · Closing Mark"}
# Seconds each source's copy stays current, and the longest a view waits when there is no copy yet.
TTL = {"extras": 900, "prices": 120, "feed": 120, "friday": 900, "treasury": 120}
FIRST_WAIT = {"extras": 12, "prices": 8, "feed": 8, "friday": 30, "treasury": 6}
STALE_QUOTES = 1800  # a price copy older than this is labelled as saved quotes


def _fetchers():
    from friday.live_inputs import fetch_snapshot
    from panels.extras import fetch_live_treasury, load_extras
    from report.current_prices import pull_current_prices
    from report.filing_monitor import load_monitor_snapshot

    def feed():
        snapshot = load_monitor_snapshot(force=True)
        if not snapshot.feed:
            raise ValueError("filing feed unavailable")
        return snapshot.feed
    return {"extras": load_extras, "prices": pull_current_prices, "feed": feed, "friday": fetch_snapshot,
            "treasury": fetch_live_treasury}


def _live(name: str, *, block: bool = False):
    from panels import live
    return live.get(name, _fetchers()[name], TTL[name], wait=FIRST_WAIT[name], block=block)


def _warm():
    """Start every source on the first view after a restart, so the other tabs are ready too."""
    if "PYTEST_CURRENT_TEST" not in os.environ:
        from panels import live
        live.warm(_fetchers())


def _extras():
    from panels.extras import load_extras
    value, _ = _live("extras")
    return value if value is not None else load_extras(offline=True)  # still loading: the snapshot, marked stale


def _prices(fresh: bool = False):
    """(prices, saved?) — fresh waits for prices under a minute old: the X image uses them."""
    from panels import live
    from report.current_prices import load_current_prices, pull_current_prices
    if fresh:
        value, age = live.get("prices", pull_current_prices, 60, wait=8, block=True)
    else:
        value, age = _live("prices")
    if value is None:
        return load_current_prices(), True
    return value, age > STALE_QUOTES


def _treasury(fresh: bool = False) -> dict:
    """Live 3M bill and 10Y quotes, refreshed every two minutes (extras every 15): the Coupon Sheet adds
    the day's move to Treasury's close. The X image waits for quotes under a minute old."""
    from panels import live
    from panels.extras import fetch_live_treasury
    if fresh:
        value, _ = live.get("treasury", fetch_live_treasury, 60, wait=6, block=True)
    else:
        value, _ = _live("treasury")
    return value or {}


def _feed():
    value, _ = _live("feed")
    if value is not None:
        return value
    return json.loads((ROOT / "data" / "latest-report-filings.json").read_text(encoding="utf-8"))


def _friday_data():
    value, _ = _live("friday")
    if value is None:
        from friday.live_inputs import fetch_snapshot
        return fetch_snapshot()  # no copy after the wait: fetch in the page, as before
    return value


def _monday(fresh: bool = False):
    from report.live_report import resolve_complete_report
    from panels.monday_preview import build_preview
    prices, saved = _prices(fresh)
    feed = _feed()
    result = resolve_complete_report(prices, feed)
    return build_preview(result.report, prices, feed, _extras()), result.notice, saved


def _theme(style: str):
    from panels import themes, web
    return themes.get(web.LOOKS[style].key)


def monday_report():
    from panels.monday_preview import audit_rows, notes
    preview, notice, saved = _monday()
    return {"preview": preview, "audit": audit_rows(preview), "notes": notes(preview),
            "notices": [line for line in (notice, "Saved quotes (price refresh unavailable)." if saved else "") if line]}


def wednesday_report(fresh: bool = False):
    from panels.wednesday import audit_rows, build, notes
    preview, _, _ = _monday()
    extras = _extras()
    extras["treasury_live"] = _treasury(fresh) or extras.get("treasury_live") or {}
    data = build(extras, _feed(), preview)
    return {"data": data, "audit": audit_rows(data), "notes": notes(data, extra=True), "notices": []}


def friday_report():
    from friday import metrics
    from panels.friday_preview import audit_rows, derive, notes
    data = _friday_data()
    panel = metrics.compute_panel(data)
    extras = _extras()
    stale = tuple(extras.get("stale") or ())
    derived = derive(panel, data, extras, _feed())
    week_end = panel["period"].get("end")
    notices = [f"Week ended {week_end}. After 4:00 pm ET on Friday this becomes the current week."] if week_end else []
    inputs = data.get("financial_inputs") or {}
    if inputs.get("status") not in (None, "current") and inputs.get("notice"):
        notices.append(f"Price/NAV: {inputs['notice']}")  # otherwise the tiles just show '—'
    return {"panel": panel, "derived": derived, "stale": stale, "audit": audit_rows(panel, derived),
            "notes": notes(panel, derived, stale, extra=True), "notices": notices}


def x_image(name: str, style: str) -> bytes:
    """The X image, drawn now: Monday re-prices MSTR and ASST as of this moment (pre-market,
    live or the close); Wednesday takes the 3M bill and 10Y as of this moment; otherwise the
    page's latest data."""
    from panels import friday_preview, monday_preview, wednesday
    theme = _theme(style)
    if name == "Monday":
        preview, _, _ = _monday(fresh=True)
        return monday_preview.render_png(preview, theme)[0]
    if name == "Wednesday":
        return wednesday.render_png(wednesday_report(fresh=True)["data"], theme)[0]
    report = friday_report()
    return friday_preview.render_png(report["panel"], report["derived"], stale=report["stale"], theme=theme)[0]


def _refresh():
    from panels import live
    live.expire()


@st.dialog("X image", width="large")
def _preview(name: str, style: str):
    with st.spinner("Drawing the X image…"):
        st.image(x_image(name, style), width="stretch")


def _download(name: str, style: str):
    """The X image in the chosen style: drawn when downloaded (prices as of the click) or previewed."""
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        st.download_button("Download X image", data=lambda: x_image(name, style), file_name=f"{name.lower()}-{style}.png",
                           mime="image/png", icon=":material/download:", on_click="ignore", key=f"download_{name}")
        if st.button("Preview X image", icon=":material/image:", key=f"preview_{name}"):
            _preview(name, style)


def _footer(name: str, formulas, report: dict, style: str):
    """The end of every tab: formulas, sources, then the X image download."""
    from panels import web
    web.formulas(formulas)
    web.sources(report["notes"], report["audit"])
    _download(name, style)


STYLES = {"bloomberg": "Bloomberg", "broadsheet": "Broadsheet"}


def _style() -> str:
    """The chosen style: the switch, else ?style=, else Bloomberg."""
    from panels import web
    if "panel_style" not in st.session_state:
        wanted = st.query_params.get("style")
        st.session_state["panel_style"] = STYLES.get(wanted, STYLES[web.DEFAULT_LOOK])
    chosen = st.session_state.get("panel_style") or STYLES[web.DEFAULT_LOOK]
    return next(key for key, label in STYLES.items() if label == chosen)


def render():
    from panels import web
    style = _style()
    look = web.LOOKS[style]
    web.use(look)
    web.style(look)
    if "panel_tabs" not in st.session_state:
        st.session_state["panel_tabs"] = TABS.get(st.query_params.get("report"), TABS["monday"])
    _warm()
    st.html(web.masthead(f"{datetime.now(ET):%A, %B} {datetime.now(ET).day}, {datetime.now(ET):%Y}"))
    with st.container(horizontal=True, vertical_alignment="center"):
        st.segmented_control("Style", list(STYLES.values()), key="panel_style", label_visibility="collapsed",
                             selection_mode="single", required=True)
        st.button("Refresh data", on_click=_refresh, key="panels_refresh", icon=":material/refresh:")
    extras = _extras()
    stale = [section for section in extras.get("stale") or ()]
    if stale:
        st.caption("Saved snapshot used for: " + ", ".join(stale))
    monday, wednesday, friday = st.tabs(list(TABS.values()), key="panel_tabs", on_change="rerun")
    active = next((key for key, tab in zip(TABS, (monday, wednesday, friday)) if tab.open), "monday")
    if st.query_params.get("report") != active:
        st.query_params["report"] = active
    if st.query_params.get("style") != style:
        st.query_params["style"] = style
    for retired in ("theme", "layout", "extra"):  # retired options; ?style= picks the look now
        if retired in st.query_params:
            del st.query_params[retired]
    # Only the open tab builds.
    if active == "monday":
        with monday:
            with st.spinner("Building Monday…"):
                report = monday_report()
            web.monday(report["preview"], notices=report["notices"])
            _footer("Monday", web.MONDAY_FORMULAS, report, style)
    elif active == "wednesday":
        with wednesday:
            with st.spinner("Building Wednesday…"):
                report = wednesday_report()
            web.wednesday(report["data"], notices=report["notices"])
            _footer("Wednesday", web.WEDNESDAY_FORMULAS, report, style)
    else:
        with friday:
            with st.spinner("Building Friday…"):
                report = friday_report()
            web.friday(report["panel"], report["derived"], notices=report["notices"])
            _footer("Friday", web.FRIDAY_FORMULAS, report, style)
    st.caption(f"Rendered {datetime.now(ET):%b %d, %Y · %I:%M %p ET} · "
               "[Detailed Monday and Friday reports](?classic=1)")
