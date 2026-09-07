"""The public Digital Credit Report: python -m streamlit run app.py."""
import streamlit as st

from report.current_prices import load_current_prices
from report.current_report import current_report
from report.filing_monitor import render_monitor
from report.methodology import PUBLIC_METHODOLOGY
from report.post_export import render_post_png
from report.presentation import build_report_view
from report.public_page import public_stylesheet, render_public_report

st.set_page_config(page_title="The Digital Credit Report", page_icon="₿", layout="wide")


@st.cache_data(show_spinner=False)
def downloadable_report(view):
    return render_post_png(view)


st.html(public_stylesheet())
try:
    prices = load_current_prices()
    report = current_report(prices)
    view = build_report_view(report, prices=prices)
except (ValueError, OSError):
    st.error("The report is temporarily unavailable. Please try again shortly.")
    st.stop()

st.html(render_public_report(view))

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
