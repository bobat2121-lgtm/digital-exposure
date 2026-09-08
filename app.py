"""Public Monday and Friday reports sharing one Streamlit entrypoint."""
from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parent
friday_source = ROOT / "sources" / "friday"
if str(friday_source) not in sys.path:
    sys.path.insert(0, str(friday_source))

st.set_page_config(page_title="Weekly Reports | Digital Credit", page_icon="₿", layout="wide")

MONDAY = "Monday · Digital Credit"
FRIDAY = "Friday · Bitcoin & Digital Credit"
if "weekly_report_tabs" not in st.session_state:
    st.session_state["weekly_report_tabs"] = FRIDAY if st.query_params.get("report") == "friday" else MONDAY

monday, friday = st.tabs([MONDAY, FRIDAY], key="weekly_report_tabs", on_change="rerun")
active = "Friday" if friday.open else "Monday"
st.session_state["weekly_active_report"] = active
if st.query_params.get("report") != active.lower():
    st.query_params["report"] = active.lower()

dark = active == "Friday"
colors = {
    "background": "#0b0d0f" if dark else "#f5f3ed",
    "card": "#15191d" if dark else "#ffffff",
    "text": "#f5f3ed" if dark else "#1b2c34",
    "muted": "#b1b9bf" if dark else "#627078",
    "border": "#30363c" if dark else "#dce1de",
    "hover": "#242a30" if dark else "#eceee9",
    "scheme": "dark" if dark else "light",
}
shell_css = (ROOT / "assets" / "shell.css").read_text(encoding="utf-8")
for name, value in colors.items():
    shell_css = shell_css.replace("{{" + name + "}}", value)
st.html("<style>" + shell_css + "</style>")

# Hidden pages never render charts, poll providers, or register timers.
if monday.open:
    with monday:
        from monday_page import render
        render()
elif friday.open:
    with friday:
        from friday_page import render
        render()
