"""The public Digital Credit Report: python -m streamlit run app.py."""
import streamlit as st

from report.current_report import current_report
from report.filing_monitor import load_monitor_snapshot, render_monitor
from report.live_report import resolve_live_report
from report.methodology import PUBLIC_METHODOLOGY
from report.post_export import render_post_png
from report.price_refresh import PriceStore
from report.presentation import build_report_view
from report.public_page import public_stylesheet, render_public_report

st.set_page_config(page_title="The Digital Credit Report", page_icon="₿", layout="wide")


@st.cache_data(show_spinner=False, max_entries=32)
def downloadable_report(view):
    return render_post_png(view)


@st.cache_resource(show_spinner=False)
def price_store():
    return PriceStore()


st.html(public_stylesheet())
if "page_prices" not in st.session_state:
    # Browser reloads create a new session; SEC refreshes retain its quote marks.
    with st.spinner("Updating prices…"):
        st.session_state["page_prices"] = price_store().refresh()
price_result = st.session_state["page_prices"]
if price_result.prices is None:
    st.error("The report is temporarily unavailable. Please try again shortly.")
    st.stop()


def prepare_report(report, *, notice=None, version="saved"):
    """Only publish a new snapshot after both its web view and PNG are valid."""
    view = build_report_view(report, prices=price_result.prices)
    html = render_public_report(view)
    return {"report": report, "view": view, "html": html, "png": downloadable_report(view),
            "notice": notice, "version": version}


@st.fragment(run_every="15s")
def financial_report():
    snapshot = load_monitor_snapshot()
    previous = st.session_state.get("last_prepared_report")
    problem = None
    if snapshot.stale and previous is not None:
        prepared = previous
    else:
        try:
            feed = snapshot.feed or {"schemaVersion": 1, "filings": []}
            result = resolve_live_report(price_result.prices, feed)
            prepared = prepare_report(result.report, notice=result.notice, version=result.version)
            st.session_state["last_prepared_report"] = prepared
        except (ValueError, OSError, TypeError, KeyError):
            problem = "New filing update could not be applied."
            if previous is not None:
                prepared = previous
            else:
                try:
                    prepared = prepare_report(current_report(price_result.prices))
                    st.session_state["last_prepared_report"] = prepared
                except (ValueError, OSError, TypeError, KeyError):
                    st.error("The report is temporarily unavailable. Please try again shortly.")
                    return

    st.html(prepared["html"])
    if price_result.using_saved_prices:
        st.caption("Price refresh unavailable · showing last saved quotes.")
    if snapshot.stale or problem:
        reason = problem or snapshot.notice or "SEC refresh unavailable."
        st.caption(f"{reason} Retained report · {prepared['view'].subtitle}.")
    if prepared["notice"]:
        st.caption(prepared["notice"])

    with st.expander("Calculation overview", expanded=False):
        st.markdown(PUBLIC_METHODOLOGY.replace("$", r"\$"))

    with st.expander("Latest SEC filings", expanded=False):
        render_monitor(snapshot)

    st.download_button(
        "Download", data=prepared["png"], file_name="digital-credit-report.png", mime="image/png",
        icon=":material/download:", type="tertiary",
        help="Save the 1800 × 1125 report image for a post.", on_click="ignore",
    )


financial_report()
