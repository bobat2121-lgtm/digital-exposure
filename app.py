"""The public Digital Credit Report: python -m streamlit run app.py."""
import streamlit as st

from report.current_report import current_report
from report.filing_monitor import render_monitor
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
    # Browser reloads create a new session. Widgets and the SEC fragment retain
    # this snapshot, keeping the visible report and its PNG in agreement.
    with st.spinner("Updating prices…"):
        st.session_state["page_prices"] = price_store().refresh()
price_result = st.session_state["page_prices"]
try:
    prices = price_result.prices
    if prices is None:
        raise ValueError("No complete price snapshot is available")
    report = current_report(prices)
    view = build_report_view(report, prices=prices)
except (ValueError, OSError):
    st.error("The report is temporarily unavailable. Please try again shortly.")
    st.stop()

st.html(render_public_report(view))
if price_result.using_saved_prices:
    st.caption("Price refresh unavailable · showing last saved quotes.")

with st.expander("Calculation overview", expanded=False):
    st.markdown(PUBLIC_METHODOLOGY.replace("$", r"\$"))

with st.expander("Latest SEC filings", expanded=False):
    render_monitor()

st.download_button(
    "Download", data=downloadable_report(view),
    file_name="digital-credit-report.png", mime="image/png",
    icon=":material/download:", type="tertiary",
    help="Save the 1800 × 1125 report image for a post.", on_click="ignore",
)
