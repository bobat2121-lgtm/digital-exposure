"""Run with: python -m streamlit run app.py"""
import streamlit as st
from pathlib import Path
from datetime import date

from report.historical_data import historical_report
from report.current_prices import load_current_prices, pull_current_prices, save_current_prices
from report.current_report import ACTIVITY_EDITION, current_report, quote_rows
from report.methodology import METHODOLOGY, POST_METHODOLOGY, input_rows
from report.page import render_footer, render_header, render_panels, render_post_preview, stylesheet
from report.png_export import render_png
from report.post_export import render_post_png
from report.presentation import build_report_view, number
from report.sample_data import sample_report
from report.vwap_store import load_estimate, save_estimate

st.set_page_config(page_title="digital-credit-report", page_icon="₿", layout="wide")

@st.cache_data(show_spinner=False)
def downloadable_report(report_view, mode):
    return render_post_png(report_view) if mode == "Post view" else render_png(report_view)

edition_column, mode_column, refresh_column, download_column = st.columns([1.25, 1.1, .65, 1], vertical_alignment="center", wrap=False)
with edition_column:
    edition = st.selectbox("Report edition", ("Current prices · dated balances", "Aug 31, 2026 · Historical replay", "Illustrative example"),
                           label_visibility="collapsed", key="report_edition")
is_current = edition.startswith("Current prices")
with refresh_column:
    if st.button("Refresh prices", disabled=not is_current, help="Update stock, BTC, STRC and EUR/USD quotes; keep the displayed balance and activity dates fixed."):
        try:
            with st.spinner("Updating quotes…"):
                save_current_prices(pull_current_prices())
        except (ValueError, OSError) as exc:
            st.session_state["price_refresh_error"] = f"Price refresh failed; saved quotes retained. {exc}"
        else:
            st.session_state.pop("price_refresh_error", None)
            st.rerun()
prices = None
if is_current:
    if st.session_state.get("price_refresh_error"):
        st.warning(st.session_state["price_refresh_error"])
    try:
        prices = load_current_prices()
        report = current_report(prices)
    except (ValueError, OSError) as exc:
        st.error(str(exc))
        st.stop()
else:
    report = historical_report() if edition.startswith("Aug 31") else sample_report()
view = build_report_view(report, prices=prices)
if st.session_state.get("report_view_mode") == "X design demo":
    st.session_state["report_view_mode"] = "Post view"
with mode_column:
    mode = st.radio("View mode", ("Post view", "Detailed view"), horizontal=True,
                    label_visibility="collapsed", key="report_view_mode")
post_view = mode == "Post view"
png = downloadable_report(view, mode)
layout_name = "post" if post_view else "detailed"
with download_column:
    st.download_button(
        "Download post PNG" if post_view else "Download detailed PNG", data=png,
        file_name=f"monday-capital-report-{report.edition_id}-{layout_name}.png",
        mime="image/png", help="Full-resolution image of the selected edition, with both companies side by side.",
        on_click="ignore",
    )
st.html(stylesheet(post_view=post_view))
if post_view:
    st.html(render_post_preview(view, png))
else:
    st.html(render_header(view))
    st.html(render_panels(view))
    st.html(render_footer(view))

with st.expander("How the numbers are calculated", expanded=False):
    st.markdown(POST_METHODOLOGY.replace("$", r"\$"))
    period_rows = []
    for company in view.companies:
        periods = {period.period: period for period in company.periods}
        if periods:
            for label, field in (("BTC/share growth", "btc_growth"), ("NAV/share growth", "nav_growth")):
                period_rows.append({"Company": company.name, "Metric": label,
                                    **{period: getattr(periods[period], field) for period in ("QTD", "YTD")}})
    if period_rows:
        st.table(period_rows)
        st.markdown(
            "**Strive's September 7 yield audit.** Its [dashboard](https://www.strive.com/treasury?tab=asst) "
            "reports **40.8% BTC Yield YTD** and "
            "uses an assumed-diluted share count of 44,766,899 → 96,523,351. "
            "Our **45.56%** uses actual Class A + B common shares: 44,713,285 → 93,262,570. "
            "Both apply ending BTC/share ÷ year-end BTC/share − 1 to the August 28 holdings. "
            "The issuer includes options and employee awards in its ending denominator. "
            "Its zero year-end award count remains unreconciled with the 10-K; "
            "the full reproduction and source comparison are in the input audit below."
        )

with st.expander("Sources & input audit", expanded=False):
    if not report.illustrative:
        from report.filing_monitor import render_monitor
        render_monitor()
    if report.illustrative:
        st.markdown(METHODOLOGY.replace("$", r"\$"))
    else:
        if is_current:
            st.markdown("**Current quote snapshot**")
            st.caption("Refresh prices updates market marks only. Balance snapshots remain Strategy August 30 and Strive August 28; capital activity remains August 24–30.")
            st.table(quote_rows(prices))
            st.markdown((Path(__file__).parent / "CURRENT_PRICES.md").read_text(encoding="utf-8").replace("$", r"\$"))
        activity_edition = date.fromisoformat(ACTIVITY_EDITION if is_current else report.edition_id)
        st.markdown("**Strive equity VWAP input**")
        windows = {"Prior week, then previous 5 trading days": "auto",
                   "Previous calendar week": "prior_week",
                   "Previous 5 completed trading days": "five_sessions"}
        selected_window = st.selectbox("Price window", tuple(windows), key="vwap_window")
        if st.button("Pull ASST VWAP", help="Refresh the selected historical window from Yahoo's one-minute bars."):
            from report.equity_vwap import pull_estimate
            try:
                with st.spinner("Pulling completed trading sessions…"):
                    refreshed = pull_estimate("ASST", activity_edition, windows[selected_window])
                    save_estimate(refreshed, "ASST", activity_edition)
            except (ValueError, OSError) as exc:
                st.warning(f"Refresh failed; the saved estimate is retained. {exc}")
            else:
                st.rerun()
        saved_vwap = load_estimate("ASST", activity_edition)
        if saved_vwap:
            st.caption(f"1-minute VWAP estimate: USD {saved_vwap['value']:.5f} · {saved_vwap['session_start']} to {saved_vwap['session_end']} · {saved_vwap['bar_count']:,} bars.")
            st.table([{"Session": row["date"], "VWAP estimate (USD)": f"{row['value']:.5f}",
                       "1-minute bars": row["bar_count"], "Bar volume": f"{row['total_volume']:,.0f}"}
                      for row in saved_vwap["daily"]])
            st.markdown("Source: [Yahoo Finance ASST](https://finance.yahoo.com/quote/ASST/history/). The estimate weights each minute's (high + low + close) / 3 by its volume. It covers retrieved regular-session bars; it is not an exact trade-by-trade VWAP or reported issuance proceeds.")
        if is_current:
            st.markdown("**Underlying August 31 balance and financing source audit**")
        st.markdown((Path(__file__).parent / "HISTORICAL_SOURCES.md").read_text(encoding="utf-8").replace("$", r"\$"))
    period_audit = Path(__file__).parent / "PERIOD_GROWTH.md"
    if not report.illustrative and period_audit.exists():
        st.markdown(period_audit.read_text(encoding="utf-8").replace("$", r"\$"))
    strive_yield_audit = Path(__file__).parent / "STRIVE_YIELD_AUDIT.md"
    if not report.illustrative and strive_yield_audit.exists():
        st.markdown(strive_yield_audit.read_text(encoding="utf-8").replace("$", r"\$"))
    st.markdown("**Balance audit — Strategy Aug 30 / Aug 23; Strive Aug 28 / Aug 21**" if is_current else "**Input audit — current edition and saved prior Monday**")
    st.caption(f"BTC reference (USD): current {number(report.current_btc_price)} · prior Monday {number(report.prior_btc_price)}.")
    st.table(input_rows(report))
