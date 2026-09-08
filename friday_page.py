"""Friday report view embedded in the combined weekly preview."""
from base64 import b64encode
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from friday.presentation import chart_spec, deferred_png
from friday.runtime import session_snapshot, SESSION_KEY
from friday.freshness import display_panel

ROOT = Path(__file__).resolve().parent / "sources" / "friday"


@st.cache_data(show_spinner=False)
def css():
    fonts = []
    for weight, name in [(400, "regular"), (700, "bold")]:
        font = b64encode((ROOT / "assets" / f"report-{name}.woff2").read_bytes()).decode()
        fonts.append(f"@font-face{{font-family:Report;src:url(data:font/woff2;base64,{font}) format('woff2');font-weight:{weight};font-display:swap}}")
    # The shell owns page color and sizing; report styles cannot leak into Monday.
    scoped = []
    rules = (ROOT / "assets" / "panel.css").read_text(encoding="utf-8")
    rules = rules[rules.index(".friday {"):]
    for line in rules.splitlines():
        if ".stMainBlockContainer" in line:
            continue
        if "{" in line and not line.lstrip().startswith("@"):
            selectors, body = line.split("{", 1)
            line = ",".join(".st-key-friday_report " + selector.strip() for selector in selectors.split(",")) + " {" + body
        scoped.append(line)
    spacing = '.st-key-friday_report, .st-key-friday_report [data-testid="stVerticalBlock"] { gap: 8px; }'
    return "<style>" + "".join(fonts) + "\n".join(scoped) + spacing + "</style>"


def number(value, fmt=",.2f", prefix="", suffix=""):
    return "—" if value is None else f"{prefix}{value:{fmt}}{suffix}"


def pct(value, signed=True):
    return number(value, "+.1f" if signed else ".1f", suffix="%")


def multiple(value):
    return number(value, ".2f", suffix="x")


def dollar_change(value):
    return "—" if value is None else f"{'+' if value >= 0 else '−'}${abs(value):,.2f}"


def dollars(value):
    if value is None:
        return "—"
    for unit, divisor in [("B", 1e9), ("M", 1e6), ("K", 1e3)]:
        if abs(value) >= divisor:
            return f"${value / divisor:,.2f}{unit}"
    return f"${value:,.0f}"


def tone(value):
    return "neutral" if value is None or value == 0 else "positive" if value > 0 else "negative"


def pretty_date(value):
    if not value:
        return "Unavailable"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%b %d, %Y")
    except ValueError:
        return str(value)


def pretty_time(value):
    if not value:
        return "Unavailable"
    try:
        instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if instant.tzinfo is None:
            return pretty_date(value)
        return instant.astimezone(ZoneInfo("America/New_York")).strftime("%b %d, %Y · %I:%M %p ET")
    except ValueError:
        return str(value)


def title(panel, source_mode):
    period = panel["period"]
    tag = "ILLUSTRATIVE DEMO" if source_mode == "demo" else "LATEST AVAILABLE DATA"
    st.html(f'''<header class="friday friday-head">
      <div><p class="eyebrow">FRIDAY CLOSE · {tag}</p>
      <h1>The <strong>Bitcoin &amp; Digital Credit</strong> Report<span class="orange-dot">.</span></h1></div>
      <div class="edition"><strong>{'Week ending ' + escape(pretty_date(period.get('week_ending', period['end']))) if period.get('end') else 'Loading Friday snapshot…'}</strong><br>Weekly market snapshot</div>
    </header>''')


def header(panel, pending=False):
    btc = panel["header"]["btc"]
    change = btc.get("weekly_return_pct")
    blocks = [f'''<article class="headline btc"><div class="label"><b>BITCOIN</b><span>Friday close</span></div>
      <div class="value">{'Updating…' if pending else number(btc.get('price'), ',.0f', '$')}</div>
      <div class="meta"><span class="{tone(change)}">{pct(change)}</span> <span>week over week</span></div>
      <div class="submetric"><span>Previous close</span><span>{number(btc.get('start_price'), ',.0f', '$')}</span></div></article>''']
    treasuries = {item["ticker"]: item for item in panel["treasury"]}
    for ticker, name in [("MSTR", "Strategy"), ("ASST", "Strive")]:
        item = panel["header"]["companies"].get(ticker, {})
        treasury = treasuries.get(ticker, {})
        change = treasury.get("nav_change_pct")
        ratio = item.get('nav_multiple')
        if ratio is None and item.get('premium_pct') is not None:
            ratio = 1 + item['premium_pct'] / 100
        multiple_change = item.get('nav_multiple_change')
        balance_items = [
            ("Bitcoin Held", number(treasury.get('btc_held'), ',.0f'), f"Disclosure: {pretty_date(treasury.get('baseline_disclosed_at'))}"),
            ("Cash", dollars(treasury.get('cash_usd')), "USD Reserve + USD Cash" if ticker == "MSTR" else "Cash balance"),
        ]
        if ticker == "MSTR":
            balance_items.append(("Debt", dollars(treasury.get('debt_usd')), "Debt principal"))
        balance_row = ''.join(f'<div class="balance-item" title="{escape(note)}"><span>{label}</span><b>{value}</b></div>' for label, value, note in balance_items)
        blocks.append(f'''<article class="headline"><div class="label"><b>{ticker}</b><span>{name} · Price / NAV</span></div>
          <div class="value">{'Updating…' if pending else multiple(ratio)}</div>
          <div class="meta"><span>Price / NAV WoW</span> <b>{number(multiple_change, '+.2f', suffix='x')}</b></div>
          <div class="meta">Share price <b>{number(item.get('price'), ',.2f', '$')}</b> &nbsp;·&nbsp; Est. NAV <b>{number(item.get('nav_per_share'), ',.2f', '$')}</b></div>
          <div class="balance-row {'with-debt' if ticker == 'MSTR' else ''}">{balance_row}</div>
          <div class="submetric"><span>NAV / share WoW</span><span class="{tone(change)}">{dollar_change(treasury.get('btc_effect_per_share'))} &nbsp;({pct(change)})</span></div></article>''')
    st.html('<div class="friday headline-grid">' + "".join(blocks) + '</div>')


def section(label, detail=""):
    st.html(f'<div class="friday section-label"><h2>{escape(label)}</h2><span>{escape(detail)}</span></div>')


def prepared_chart(prepared, name, kind, payload, **kwargs):
    if prepared is not None and name in prepared:
        return prepared[name]
    return chart_spec(kind, payload, **kwargs)


def chart_placeholder(height):
    st.html(f'<div class="friday chart-placeholder" role="status" style="height:{height}px">Loading historical chart…</div>')


@st.fragment
def volume_panel(items, label, pending=False, prepared=None):
    rows = []
    for item in items:
        value = item.get("dollars")
        change = item.get("change_pct")
        estimate = "≈ " if item.get("estimated") and value is not None else ""
        rows.append(f'''<div class="weekly-summary"><div class="volume-label"><b>{escape(item['ticker'])}</b><strong>{'Updating…' if pending else estimate + dollars(value)}</strong></div>
          <p><span>{pct(change)} WoW</span><span>{pct(item.get('vs_4week_average_pct'))} vs 4-week avg.</span></p></div>''')
    estimated = any(item.get("estimated") for item in items)
    st.html(f'<section class="friday liquidity"><h3>{escape(label)}</h3><div class="weekly-summary-grid">' + "".join(rows) + '</div></section>')
    with st.expander(f"Weekly trading history · {label}", expanded=True):
        chart = prepared_chart(prepared, 'volume:common' if label == 'Common stocks' else 'volume:preferred', "volume", items)
        if chart is not None:
            st.vega_lite_chart(spec=chart, width="stretch")
        elif pending:
            chart_placeholder(250)
        else:
            st.caption("Weekly trading history unavailable.")
        if estimated:
            st.caption("≈ Estimated dollar volume")


@st.fragment
def metric_expander(label, value, delta, rows, field, y_title, *, unit="", source="", note="", classification="", latest=None, reading_state="ready", prepared=None):
    metric = number(value, ".1f" if unit else ".0f", suffix=unit)
    movement = number(delta, "+.1f", suffix=" pp" if unit == "%" else " pts")
    summary = f"**{label}** · **{metric}** · {movement} WoW" if value is not None else f"**{label}** · Data unavailable"
    if value is not None and classification:
        summary += f" · {classification}"
    if reading_state == "loading":
        summary = f"**{label}** · Updating…"
    widget_key = f"friday_condition_{field}"
    st.session_state[widget_key] = st.session_state.get(f"friday_open_{widget_key}", True)
    expander = st.expander(summary, expanded=True, key=widget_key, on_change=remember_open, args=(widget_key,))
    # All charts start loaded. Keep cached children mounted when collapsed so
    # a quick reopen avoids rebuilding the plot.
    with expander:
        kind = "supply" if field == "pct" else "sentiment"
        chart = prepared_chart(prepared, kind, kind, rows, latest=latest, show_current=reading_state == 'ready')
        if chart is not None:
            st.vega_lite_chart(spec=chart, width="stretch", key=f"friday_static_{field}")
            st.caption("4-year view" if field == "pct" else "Since July 2023 · line: 3-day average · dot: latest reported index" if latest else "Since July 2023 · 3-day average")
        elif reading_state == 'loading':
            chart_placeholder(360)
        else:
            st.info("This data source is not connected. No sample values are substituted.")
    if source:
        st.caption(source)


def remember_open(widget_key):
    """Each chart keeps its own preference when a live header label changes."""
    st.session_state[f"friday_open_{widget_key}"] = st.session_state.get(widget_key, True)


@st.fragment
def trend_expander(ticker, trend, source_mode, prepared=None):
    average = "200W" if ticker == "BTC" else "200D"
    metric = trend.get("averages", {}).get(average, {})
    label = f"**{ticker}** · **{pct(metric.get('extension_pct'))}** vs {average} SMA"
    reading_state = trend.get('_reading_state', 'ready')
    if reading_state != 'ready':
        label = f"**{ticker}** · {'Updating…' if reading_state == 'loading' else 'Current quote unavailable'}"
    widget_key = f"friday_sma_{ticker}"
    st.session_state[widget_key] = st.session_state.get(f"friday_open_{widget_key}", True)
    expander = st.expander(label, expanded=True, key=widget_key, on_change=remember_open, args=(widget_key,))
    # Do not unregister this chart's controls on collapse: Streamlit would
    # otherwise discard the selected period and Vega's mounted view.
    with expander:
        averages = trend.get("averages", {})
        cols = st.columns(1 + len(averages))
        cols[0].metric("BTC price" if ticker == "BTC" else f"{ticker} stock price", 'Updating…' if reading_state == 'loading' else number(trend.get("price"), ",.2f", "$"))
        for col, (name, value) in zip(cols[1:], averages.items()):
            col.metric(f"{name} SMA", 'Updating…' if reading_state == 'loading' else number(value.get("value"), ",.4f" if ticker == "ASST" else ",.2f", "$"), pct(value.get("extension_pct")), delta_color="off")
        history_key = f"friday_history_widget_{ticker}"
        history_preference = f"friday_history_preference_{ticker}"
        restore_preference(history_key, history_preference, "4Y" if ticker == "BTC" else "YTD" if ticker == "ASST" else "1Y")
        view = st.segmented_control(
            "Chart history", ["YTD", "1Y", "2Y", "4Y", "All"] if ticker == "ASST" else ["1Y", "2Y", "4Y", "All"],
            required=True, key=history_key, on_change=remember_preference, args=(history_key, history_preference), help="Choose the chart's fixed timeframe. All shows the full loaded history; moving averages always use the full calculation history.",
        )
        chart_input = {field: trend.get(field) for field in ("series", "live_point", "price_as_of")}
        chart = prepared_chart(prepared, f'sma:{ticker}:{view}', "sma", chart_input, ticker=ticker, view=view)
        if chart is not None:
            st.vega_lite_chart(spec=chart, width="stretch", key=f"friday_static_{ticker}_{view}")
            st.caption("Price-scaled view · upper SMA bands may be outside the chart")
            if ticker == "ASST":
                st.caption("January opening view · SMA uses preceding split-adjusted ASST ticker history")
        elif reading_state == 'loading':
            chart_placeholder(390)
        else:
            st.caption("Price history unavailable.")
        if source_mode == "latest":
            st.caption(f"Source: Yahoo Finance · split-adjusted daily closes" if ticker != "BTC" else "Source: Yahoo Finance · weekly BTC closes")
            if reading_state == 'ready':
                st.caption(f"Quote: {pretty_time(trend.get('price_as_of'))}")
            elif trend.get('series'):
                st.caption(f"Cached history through {pretty_date(trend['series'][-1]['date'])} · {'updating readings' if reading_state == 'loading' else 'current quote unavailable'}")



def report(snapshot, source_mode):
    pending, failed = snapshot.get('pending', False), bool(snapshot.get('error'))
    data = snapshot.get('data', {})
    panel = display_panel(snapshot, pending=pending, failed=failed)
    charts = snapshot.get('charts', {})
    historical = charts.get('history')
    ready = charts.get('ready')
    title(panel, source_mode)
    if source_mode == "demo":
        st.info("Synthetic preview — all prices and indicators are sample values. Choose Latest available for market history and current readings.")
    if pending:
        st.caption("Updating readings… Historical charts use the last validated data while fresh feeds load.")
    elif failed:
        st.warning(snapshot['error'])
    elif source_mode == 'latest':
        st.caption(f"Readings refreshed: {pretty_time(data.get('fetched_at'))}")
    header(panel, pending=pending)
    section("Trading liquidity", "12 completed weeks · dollar volume")
    volume = {item["ticker"]: item for item in panel["liquidity"]}
    left, right = st.columns(2, gap="medium")
    with left:
        volume_panel([volume[t] for t in ("MSTR", "ASST")], "Common stocks", pending, historical if pending or failed else ready)
    with right:
        volume_panel([volume[t] for t in ("STRC", "SATA")], "Preferred stocks", pending, historical if pending or failed else ready)

    section("Bitcoin conditions", "Latest available readings" if source_mode == "latest" else "Expand a metric for its historical chart")
    loss = panel.get("live_supply_loss", panel["supply_loss"]) if source_mode == "latest" else panel["supply_loss"]
    sentiment = panel.get("live_sentiment", panel["sentiment"]) if source_mode == "latest" else panel["sentiment"]
    provider = "Illustrative data" if source_mode == "demo" else data.get("supply_source", "Supply source unavailable")
    source_link = data.get("supply_source_url")
    source_caption = f"Source: [{provider}]({source_link})" if source_link else provider
    if data.get("supply_method") == "complementary_loss_estimate":
        source_caption += " · loss estimated as 100% minus profit"
    loss_state = loss.get('_reading_state', 'ready')
    loss_stamp = f"as of {pretty_date(loss.get('as_of'))}" if loss_state == 'ready' else f"cached history through {pretty_date(loss['series'][-1]['date'])}" if loss.get('series') else "loading history" if pending else "history unavailable"
    metric_expander("Supply in loss", loss.get("value"), loss.get("change"), loss.get("series", []), "pct", "Supply in loss · %", unit="%", source=source_caption + f" · {loss_stamp}", note="Share of BTC supply last moved at a price above the current price.", reading_state=loss_state, prepared=ready if loss_state == 'ready' else historical)
    sentiment_provider = data.get("sentiment_source", "Sentiment source unavailable")
    sentiment_link = data.get("sentiment_source_url")
    sentiment_caption = f"Source: [{sentiment_provider}]({sentiment_link})" if sentiment_link else sentiment_provider
    sentiment_state = sentiment.get('_reading_state', 'ready')
    sentiment_stamp = f"as of {pretty_time(sentiment.get('as_of'))}" if sentiment_state == 'ready' else f"cached history through {pretty_date(sentiment['series'][-1]['date'])}" if sentiment.get('series') else "loading history" if pending else "history unavailable"
    metric_expander("Fear & Greed", sentiment.get("value"), sentiment.get("change"), sentiment.get("series", []), "value", "Sentiment · 0–100", source="Illustrative sentiment data" if source_mode == "demo" else sentiment_caption + f" · {sentiment_stamp}", classification=sentiment.get("classification", ""), latest=sentiment.get("live_point"), reading_state=sentiment_state, prepared=ready if sentiment_state == 'ready' else historical)

    section("SMA extensions", "Latest quotes · moving averages use completed history" if source_mode == "latest" else "Price above / below its moving average")
    trend_data = panel.get("live_trends", panel["trends"]) if source_mode == "latest" else panel["trends"]
    for ticker in ("BTC", "MSTR", "ASST"):
        trend = trend_data.get(ticker, {})
        trend_expander(ticker, trend, source_mode, ready if trend.get('_reading_state', 'ready') == 'ready' else historical)

    st.download_button("Download Friday panel", b'' if pending or failed else deferred_png(panel, snapshot_as_of=data.get('fetched_at')), disabled=pending or failed, file_name=f"friday-bitcoin-credit-{str(panel['period']['end'])[:10]}.png", mime="image/png", icon=":material/download:", help="Download this displayed dataset. Financial cards use Friday close; indicator charts include the displayed latest readings. No new data is fetched.", on_click="ignore", key="friday_download_panel")

    with st.expander("Calculations, sources & disclosures", expanded=False):
        if source_mode == "demo":
            st.markdown("**Illustrative demo:** all values and histories are synthetic. Jagged sample paths demonstrate chart styling; they are not market observations.")
        st.markdown("**Price / NAV** = common share price ÷ estimated net treasury NAV per basic share. For example, 1.25x represents a 25% premium; 0.90x represents a 10% discount.")
        st.markdown("**Price / NAV WoW** is the change in the multiple, in x, using each Friday's stock price and BTC mark against the same frozen disclosed quantities. It is a price-only comparison, not a reconstruction of two independently reported balance sheets.")
        st.markdown("**Estimated net treasury NAV** = BTC value + cash and other included liquid assets − debt principal − preferred claims. The denominator matches the Monday report: actual Class A + Class B shares.")
        st.markdown("**Friday assumption:** no additional assets bought or financing changes assumed before disclosure. The same disclosed balance sheet is valued at both BTC price marks; Monday's Digital Credit Report handles new disclosures.")
        st.markdown("**NAV/share WoW** shows the dollar and percentage change from repricing BTC against that same balance sheet. Other assets, claims and the share count stay fixed.")
        st.markdown("**Weekly liquidity:** 12 completed exchange weeks. WoW compares adjacent weeks; the four-week comparison uses the four completed weeks before the latest week. Short holiday weeks contain fewer sessions. Missing or incomplete weeks are unavailable, not zero. Public-feed dollar volume is estimated as daily close × shares traded when VWAP is unavailable.")
        st.markdown("**Charts and downloads:** financial headers and weekly liquidity use Friday close. Indicator charts and the downloaded panel use the displayed latest validated readings, which may be delayed. The download captures this dataset without requesting new feeds. Price and supply lines connect observations directly. Fear & Greed uses CoinMarketCap throughout. Its line uses a trailing three-calendar-day average of published daily observations; its live headline and dot use the latest reported raw index. The download preserves the same raw headline and current marker; its collection time and each observation date are retained. Supply in profit/loss uses coins' last-moved price as a cost-basis proxy, not investors' actual profit or loss.")
        st.markdown("**Chart history:** BTC SMA opens on four years, MSTR on one year, and ASST on January 1 of the observation year. The timeframe buttons select fixed chart windows; All shows the full loaded history. Moving averages use full history before the visible window. Supply shows four years, and Fear & Greed starts July 1, 2023. The PNG uses those same default periods. Chart zooming and panning are disabled.")
        st.markdown("**SMA bands:** 0%, +50%, +100%, +150% and +200% are multiples of the dated moving average. The vertical axis fits visible prices with padding; upper extension bands can fall outside the plot. White lines show BTC or stock closing price; the orange dashed line is the reference SMA. BTC uses 200 completed Friday observations available at the cutoff. Equities use 50/200 completed trading days. These are trend levels, not valuation ratings.")
        st.markdown("**ASST history:** the Strive market change took effect [September 15, 2025](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2025-507). To show the 200-day SMA from January, its warmup includes earlier Asset Entities ticker history. It is a continuous ticker SMA, not a Strive-only operating-history measure. Prices and SMAs use the same split-adjusted share basis, including the [1-for-20 reverse split effective February 6, 2026](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-70).")
        st.markdown("**Supply source:** the public Checkonchain series provides separate supply-in-loss, supply-in-profit and circulating-supply balances on matching dates; each share is divided by the same total. If only its percent-profit series is available, loss is explicitly labeled a complementary estimate. Glassnode remains available when its API is configured. Today's incomplete UTC supply observation is excluded.")
        for ticker, trend in trend_data.items():
            st.caption(f"{ticker} price: {pretty_time(trend.get('price_as_of') or trend.get('as_of'))}")
            if ticker == "ASST":
                for name, average in trend.get("averages", {}).items():
                    if average.get("value") is not None:
                        st.caption(f"ASST {name} SMA: {number(average['value'], ',.4f', '$')} · mean of {average['required']} completed session closes · {pretty_date(average.get('window_start'))} to {pretty_date(average.get('as_of'))}. Current intraday quotes are excluded from this average.")
        for item in panel["treasury"]:
            st.markdown(f"**{item['ticker']}** · Disclosure {pretty_date(item.get('baseline_disclosed_at'))} · BTC-only NAV change {number(item.get('btc_effect_per_share'), '+,.2f', '$')} per share.")
            if not item.get("valid", True):
                st.caption(item.get("reason") or "Eligible baseline unavailable.")
        st.caption(f"Market data fetched: {data.get('fetched_at', 'Unavailable')}")
        if data.get("refresh_meta", {}).get("last_full_load_at"):
            st.caption(f"Full price history requested: {pretty_time(data['refresh_meta']['last_full_load_at'])}")
        st.caption("First opening Friday in a browser session, reloading the browser, and using Refresh data request fresh feeds in the background. Switching away and back reuses the session snapshot. Historical charts can appear from a dated, validated cache; summary readings remain placeholders until the request finishes. Timeframe controls use the same complete calculation history.")
        if snapshot.get('timings'):
            st.caption(f"Latest refresh timing: {snapshot['timings']}")
        st.caption(str(panel["period"].get("price_alignment", "")))
        for key, value in data.get("sources", {}).items():
            st.caption(f"{key.replace('_', ' ').capitalize()}: {value}")
        for notice in dict.fromkeys(data.get("notices", []) + panel.get("notices", [])):
            st.caption(notice)



@st.fragment(run_every="500ms", key="friday_pending_refresh")
def finish_refresh():
    # Poll only the Future. Never wait or fetch here, and do not rerender the
    # page until a complete prepared result is available for this session.
    if st.session_state.get('weekly_active_report') != 'Friday':
        return
    current = session_snapshot(st.session_state, 'latest')
    if not current.get('pending'):
        st.rerun()




def remember_preference(widget_key, preference_key):
    """Persist outside widget state, which Streamlit removes on tab unmount."""
    st.session_state[preference_key] = st.session_state[widget_key]


def restore_preference(widget_key, preference_key, default):
    if widget_key not in st.session_state:
        st.session_state[widget_key] = st.session_state.get(preference_key, default)


def queue_refresh():
    st.session_state["friday_refresh_request"] = "manual"


def render():
    """Render only the active Friday tab; importing this module does no work."""
    with st.container(key="friday_report"):
        st.html(css())
        snapshot = session_snapshot(st.session_state, "latest", st.session_state.pop("friday_refresh_request", None))
        st.button("Refresh data", on_click=queue_refresh, key="friday_refresh_button",
            disabled=bool(snapshot.get("pending")))
        report(snapshot, "latest")
        if st.session_state.get(SESSION_KEY, {}).get("pending"):
            finish_refresh()
