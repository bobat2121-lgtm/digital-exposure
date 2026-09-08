"""Fixed-timeframe charts using the observations displayed by the report."""
import json
import math

import altair as alt
import pandas as pd

from friday.scaling import visible_price_domain
from friday.series import SENTIMENT_BANDS, smooth_sentiment

ORANGE = "#e88029"
WHITE = "#f5f3ed"
MUTED = "#9aa4ad"
SENTIMENT_START = "2023-07-01"

# Shared with the PNG exporter. Bounds are price / anchor SMA multipliers.
BANDS = (
    {"label": "Below SMA", "lower": 0.0, "upper": 1.0, "color": "#304cba"},
    {"label": "0–50%", "lower": 1.0, "upper": 1.5, "color": "#198653"},
    {"label": "50–100%", "lower": 1.5, "upper": 2.0, "color": "#b8a528"},
    {"label": "100–150%", "lower": 2.0, "upper": 2.5, "color": "#c67b1b"},
    {"label": "150–200%", "lower": 2.5, "upper": 3.0, "color": "#ba3b48"},
    {"label": "200%+", "lower": 3.0, "upper": None, "color": "#7c4da3"},
)


def style(chart, height=270):
    return (chart.properties(height=height, background="transparent")
            .configure_view(stroke=None)
            .configure_axis(labelColor=MUTED, titleColor=MUTED, gridColor="#252b31",
                            domain=False, tickColor="#343c43", labelFontSize=12, titleFontSize=12)
            .configure_legend(labelColor=WHITE, title=None, orient="bottom", labelFontSize=12))


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _dated_frame(records):
    frame = pd.DataFrame(records)
    frame["date"] = pd.to_datetime(frame["date"], utc=True, format="mixed")
    return frame


def _inline(frame):
    """Use supported inline records without a global row-limit override.

    JSON converts pandas dates and missing values to portable ISO timestamps
    and nulls before validation. Price/SMA history uses _wide_records instead
    to retain full numeric precision.
    """
    return alt.InlineData(values=json.loads(frame.to_json(orient="records", date_format="iso")))


def _wide_records(rows, fields, *, bounded=False):
    """One dated record per observation, with invalid field values as null.

    Fold/area transforms derive plotting rows in Vega. Keeping this wide avoids
    copying every timestamp and tooltip value for every trace and guide, and
    preserves the provider's full numeric precision without a pandas roundtrip.
    """
    records = []
    for row in rows:
        record = {"date": row["date"]}
        for field in fields:
            value = row.get(field)
            record[field] = value if _finite(value) and (not bounded or 0 <= value <= 100) else None
        records.append(record)
    return records


def _field_labels(fields):
    return "(" + json.dumps(dict(fields)) + ")[datum.field]"


def time_bounds(rows, view="All", end=None):
    """Initial calendar-window bounds; this does not filter any observations."""
    if view not in ("YTD", "1Y", "2Y", "4Y", "All"):
        raise ValueError("Chart view must be YTD, 1Y, 2Y, 4Y or All")
    dates = pd.to_datetime([row["date"] for row in rows if row.get("date")], utc=True, errors="coerce")
    dates = dates[~dates.isna()]
    if len(dates) == 0:
        return None
    last = max(dates)
    if end is not None:
        last = max(last, pd.to_datetime(end, utc=True))
    first = (last.normalize().replace(month=1, day=1) if view == "YTD" else
             min(dates) if view == "All" else last - pd.DateOffset(years={"1Y": 1, "2Y": 2, "4Y": 4}[view]))
    if first == last:
        first = last - pd.Timedelta(days=1)
    return first.isoformat(), last.isoformat()


def _window_records(rows, bounds, *, dates=None):
    """Serialize a fixed window and its nearest neighboring observations.

    Calculations and scale bounds must use the full history before this step.
    The extra observation on either side preserves clipped line segments at
    the window edges, including null gaps, without inventing boundary values.
    Records are returned unchanged; no averaging or numeric conversion occurs.
    """
    if dates is None:
        dates = pd.to_datetime([row["date"] for row in rows], utc=True,
                               format="mixed", errors="coerce")
    start, end = (pd.Timestamp(value) for value in bounds)
    chosen = {index for index, stamp in enumerate(dates) if start <= stamp <= end}
    before = [(stamp, index) for index, stamp in enumerate(dates) if stamp < start]
    after = [(stamp, index) for index, stamp in enumerate(dates) if stamp > end]
    if before:
        chosen.add(max(before)[1])
    if after:
        chosen.add(min(after)[1])
    return [row for index, row in enumerate(rows) if index in chosen]


def _time_scale(bounds):
    # Explicit UTC DateTime values survive Vega-Lite/Streamlit time-domain
    # normalization; raw epoch numbers can be coerced inconsistently there.
    values = []
    for value in bounds:
        stamp = pd.Timestamp(value).tz_convert("UTC")
        values.append(alt.DateTime(year=stamp.year, month=stamp.month, date=stamp.day,
                                  hours=stamp.hour, minutes=stamp.minute, seconds=stamp.second,
                                  milliseconds=stamp.microsecond // 1000, utc=True))
    return alt.Scale(type="utc", domain=values, nice=False)


def line_chart(rows, fields, *, y_title, height=270, point=None, bounded=False, view="All"):
    names = [field[0] for field in fields]
    records = [row for row in _wide_records(rows, names, bounded=bounded)
               if any(row[field] is not None for field in names)]
    if not records:
        return None
    labels = [field[1] for field in fields]
    colors = [field[2] for field in fields]
    bounds = time_bounds(records, view, point.get("date") if point else None)
    if view != "All":
        records = _window_records(records, bounds)
    base = (alt.Chart(alt.InlineData(values=records))
            .transform_fold(names, as_=["field", "value"])
            .transform_filter("isValid(datum.value)")
            .transform_calculate(series=_field_labels((field, label) for field, label, _ in fields))).encode(
        x=alt.X("date:T", title=None, scale=_time_scale(bounds), axis=alt.Axis(format="%b %y", tickCount=5)),
        y=alt.Y("value:Q", title=y_title, scale=alt.Scale(domain=[0, 100], nice=False) if bounded else alt.Scale(zero=False)),
        color=alt.Color("series:N", scale=alt.Scale(domain=labels, range=colors)),
        tooltip=[alt.Tooltip("date:T", title="Date", format="%b %d, %Y"),
                 alt.Tooltip("series:N", title="Metric"),
                 alt.Tooltip("value:Q", title=y_title, format=",.2f")])
    chart = base.mark_line(strokeWidth=2, interpolate="linear", clip=True)
    if point is not None and point.get("close") is not None:
        marker_frame = pd.DataFrame([{"date": pd.to_datetime(point["date"], utc=True), "value": point["close"]}])
        marker = alt.Chart(_inline(marker_frame)).mark_point(color=ORANGE, filled=True, size=80, stroke=WHITE, strokeWidth=1.5, clip=True).encode(
            x="date:T", y="value:Q", tooltip=[alt.Tooltip("date:T", title="Provider quote (UTC)", format="%b %d, %Y %H:%M"), alt.Tooltip("value:Q", title="Latest quote · USD", format="$,.2f")])
        chart = chart + marker
    return style(chart, height)


def daily_volume(rows):
    if not rows:
        return None
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    return style(alt.Chart(frame).mark_bar(color=ORANGE, cornerRadiusTopLeft=3,
                  cornerRadiusTopRight=3).encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %d", tickCount=6)),
        y=alt.Y("dollars:Q", title="Dollars traded", axis=alt.Axis(format="$~s", labelExpr="replace(datum.label, 'G', 'B')")),
        tooltip=[alt.Tooltip("date:T", title="Session", format="%b %d, %Y"),
                 alt.Tooltip("dollars:Q", title="Dollar volume", format="$,.0f")]), 210)


def weekly_volume(items, height=260):
    """Twelve completed weeks of grouped dollar bars, with a shared USD axis.

    ``items`` is a pair of liquidity dictionaries (MSTR/ASST or STRC/SATA),
    each containing ticker and weekly_series. Incomplete weeks remain gaps.
    """
    records = []
    tickers = [item["ticker"] for item in items]
    for item in items:
        ticker = item["ticker"]
        for row in item.get("weekly_series", [])[-12:]:
            ending = row.get("week_ending") or row.get("date")
            if ending is None:
                continue
            complete = row.get("complete", True)
            amount = row.get("dollars")
            records.append({
                "date": ending, "ticker": ticker,
                "dollars": amount if complete and _finite(amount) and amount >= 0 else None,
                "change_pct": row.get("change_pct"),
                "basis": "Close × volume estimate" if row.get("estimated") else "VWAP × volume",
                "coverage": f"{row.get('observed_sessions', '—')}/{row.get('expected_sessions', '—')} sessions",
            })
    if not records or not any(row["dollars"] is not None for row in records):
        return None
    frame = _dated_frame(records)
    frame["week"] = frame["date"].dt.strftime("%b %d")
    week_order = frame.sort_values("date")["week"].drop_duplicates().tolist()
    colors = [ORANGE if ticker in ("MSTR", "STRC") else WHITE for ticker in tickers]
    chart = alt.Chart(frame).mark_bar().encode(
        x=alt.X("week:O", title=None, sort=week_order,
                axis=alt.Axis(labelAngle=-35, labelPadding=8)),
        xOffset=alt.XOffset("ticker:N", sort=tickers),
        y=alt.Y("dollars:Q", title="Weekly dollars traded", scale=alt.Scale(zero=True),
                axis=alt.Axis(format="$~s", labelExpr="replace(datum.label, 'G', 'B')", tickCount=5)),
        color=alt.Color("ticker:N", scale=alt.Scale(domain=tickers, range=colors)),
        tooltip=[alt.Tooltip("date:T", title="Week ending", format="%b %d, %Y"),
                 alt.Tooltip("ticker:N", title="Security"),
                 alt.Tooltip("dollars:Q", title="Weekly turnover", format="$,.0f"),
                 alt.Tooltip("change_pct:Q", title="Week-over-week (%)", format="+.1f"),
                 alt.Tooltip("basis:N", title="Basis"),
                 alt.Tooltip("coverage:N", title="Coverage")],
    )
    return style(chart, height)


def supply_chart(rows, height=270, view="4Y"):
    """Four-year chart; full inputs remain available to select other periods."""
    return line_chart(rows, [("pct", "Supply in loss", "#ef5864"),
                             ("profit_pct", "Supply in profit", ORANGE)],
                      y_title="Circulating supply (%)", height=height, bounded=True, view=view)


def sentiment_chart(rows, height=270, latest=None, show_current=True):
    """Observations since July 1, 2023 with fixed date and score axes."""
    candidates = smooth_sentiment(rows)
    beginning = pd.Timestamp(SENTIMENT_START, tz="UTC")
    if not any(row["date"] >= SENTIMENT_START for row in candidates):
        return None
    ending = pd.Timestamp(candidates[-1]["date"], tz="UTC")
    latest_stamp = pd.to_datetime(latest.get("date") or latest.get("as_of"), utc=True, errors="coerce") if latest else None
    latest_valid = (show_current and latest_stamp is not None and not pd.isna(latest_stamp) and latest_stamp >= ending
                    and _finite(latest.get("value")) and 0 <= latest["value"] <= 100)
    if latest_valid:
        ending = latest_stamp
    # Leave a small empty margin so the current marker is fully visible at
    # the right edge. This adds no observations or forecast to the history.
    ending += pd.Timedelta(days=14)
    bounds = beginning.isoformat(), ending.isoformat()
    observations = _window_records(
        [{"date": row["date"], "value": row["smoothed_value"], "raw_value": row["value"]}
         for row in candidates], bounds)
    x = alt.X("date:T", title=None, scale=_time_scale(bounds), axis=alt.Axis(format="%b %y", tickCount=5))
    y = alt.Y("value:Q", title="Fear & Greed", scale=alt.Scale(domain=[0, 100], nice=False),
              axis=alt.Axis(values=[0, 20, 40, 60, 80, 100]))
    shading = alt.Chart(pd.DataFrame(SENTIMENT_BANDS)).mark_rect(opacity=0.09).encode(
        y=alt.Y("lower:Q", scale=alt.Scale(domain=[0, 100], nice=False), title="Fear & Greed"),
        y2="upper:Q", color=alt.Color("color:N", scale=None, legend=None),
    )
    labels = [band["label"] for band in SENTIMENT_BANDS]
    colors = [band["color"] for band in SENTIMENT_BANDS]
    color = alt.Color("state:N", scale=alt.Scale(domain=labels, range=colors),
                      legend=alt.Legend(symbolType="stroke", columns=3))
    state = "".join(f"datum.value < {band['upper']} ? {json.dumps(band['label'])} : " for band in SENTIMENT_BANDS[:-1]) + json.dumps(labels[-1])
    observation_base = alt.Chart(alt.InlineData(values=observations)).transform_calculate(state=state)
    if len(observations) > 1:
        line = (observation_base.transform_window(
            end_date="lead(date)", end_value="lead(value)", sort=[alt.SortField(field="date", order="ascending")],
        ).transform_filter("isValid(datum.end_date)")).mark_rule(strokeWidth=2.1, clip=True).encode(
            x=x, x2="end_date:T", y=y, y2="end_value:Q", color=color,
            tooltip=[alt.Tooltip("date:T", title="Date", format="%b %d, %Y"),
                     alt.Tooltip("raw_value:Q", title="Daily index", format=".0f"),
                     alt.Tooltip("value:Q", title="3-day average", format=".1f"),
                     alt.Tooltip("state:N", title="Chart range")],
        )
    else:
        line = observation_base.mark_point(filled=True, size=40, clip=True).encode(x=x, y=y, color=color)
    layers = [shading, line]
    if not show_current:
        return style(alt.layer(*layers).resolve_scale(color="independent"), height)
    current = latest if latest_valid else candidates[-1]
    value = current["value"]  # Always the reported index, never the smoothed mean.
    band = next((band for band in SENTIMENT_BANDS if value < band["upper"]), SENTIMENT_BANDS[-1])
    classification = current.get("classification") or band["label"].title()
    stamp = latest_stamp if latest_valid else pd.Timestamp(observations[-1]["date"], tz="UTC")
    prefix = "Latest reported" if latest_valid else "Latest daily"
    indicator = alt.Chart(_inline(_dated_frame([{
        "date": stamp.isoformat(), "value": value, "classification": classification,
        "label": f"{prefix} · {value:.0f} · {classification}",
    }])))
    guide = indicator.mark_rule(color=band["color"], strokeDash=[4, 5], opacity=0.45, clip=True).encode(y=y)
    marker = indicator.mark_point(filled=True, size=175, color=band["color"], stroke=WHITE,
                                  strokeWidth=2, clip=False).encode(
        x=x, y=y, tooltip=[alt.Tooltip("date:T", title="Observation (UTC)", format="%b %d, %Y %H:%M"),
                          alt.Tooltip("value:Q", title="Reported index", format=".0f"),
                          alt.Tooltip("classification:N", title="Classification")])
    # Put the label inside the plot even at 0 or 100. A dark outline keeps it
    # legible where historical lines cross beneath it.
    label_style = dict(align="right", baseline="middle", dx=-14, dy=25 if value >= 85 else -22,
                       fontSize=13, fontWeight=700)
    halo = indicator.mark_text(**label_style, color="#15191d", stroke="#15191d", strokeWidth=5).encode(x=x, y=y, text="label:N")
    callout = indicator.mark_text(**label_style, color=band["color"]).encode(x=x, y=y, text="label:N")
    layers.extend([guide, marker, halo, callout])
    chart = alt.layer(*layers).resolve_scale(color="independent")
    return style(chart, height)


def sma_chart(trend, ticker, height=380, view=None):
    """Price and distinct SMA traces over dynamic, numeric extension bands.

    Bands use each observation's completed 200W/200D SMA. Live quotes remain
    independent markers and do not create a daily bar or change the anchor.
    Default views are four years for BTC, one year for MSTR and YTD for ASST.
    All observations remain available to the fixed timeframe controls.
    """
    rows = [row for row in trend.get("series", [])
            if row.get("date") and _finite(row.get("close")) and row["close"] > 0]
    if not rows:
        return None
    main_name = "200W" if ticker == "BTC" else "200D"
    main_key = "sma_" + main_name.lower()
    anchor_rows = [row for row in rows if _finite(row.get(main_key)) and row[main_key] > 0]
    live = trend.get("live_point")
    view = view or ("4Y" if ticker == "BTC" else "YTD" if ticker == "ASST" else "1Y")
    endpoint = live.get("date") if live else trend.get("price_as_of")
    bounds = time_bounds(rows, view, endpoint)
    start, end = (pd.Timestamp(value) for value in bounds)
    dates = pd.to_datetime([row["date"] for row in rows], utc=True, format="mixed")
    visible = [row for row, stamp in zip(rows, dates) if start <= stamp <= end]
    live_date = pd.to_datetime(live.get("date"), utc=True, errors="coerce") if live else None
    visible_live = live if live_date is not None and not pd.isna(live_date) and start <= live_date <= end else None
    ymin, ymax = visible_price_domain(visible, visible_live, anchor_key=main_key if ticker == "ASST" else None)
    # Keep the full-history cap consistent between timeframes while the y-axis
    # is based solely on the selected window. Trim only after these decisions.
    band_cap = max(ymax, max(row["close"] for row in rows) * 1.10,
                   max((row[main_key] * 3.35 for row in anchor_rows), default=0))
    # Frame the market's movement. Higher extension bands can be clipped; they
    # must not flatten the price trace by forcing a zero-to-3x-SMA price axis.
    yscale = alt.Scale(domain=[ymin, ymax], zero=False, nice=False)
    x = alt.X("date:T", title=None, scale=_time_scale(bounds), axis=alt.Axis(format="%b %y", tickCount=7))
    y = alt.Y("value:Q", title="Price (USD)", scale=yscale,
              axis=alt.Axis(format="$~s", tickCount=6))
    # Every historical layer inherits one shared wide dataset from the chart.
    # Layer-local transforms expand guides/series only in the browser; dates,
    # OHLC values and anchors are serialized exactly once per observation.
    source_fields = ["close", main_key, "low", "high"]
    if ticker != "BTC":
        source_fields.append("sma_50d")
    plotted_rows = rows if view == "All" else _window_records(rows, bounds, dates=dates)
    history = alt.InlineData(values=_wide_records(plotted_rows, source_fields))
    base = alt.Chart()
    layers = []
    if anchor_rows:
        anchor = f"datum.{main_key}"
        anchor_base = base.transform_filter(f"isValid({anchor}) && {anchor} > 0")
        for band in BANDS:
            upper = str(band_cap) if band["upper"] is None else f"{anchor} * {band['upper']}"
            layers.append(anchor_base.transform_calculate(
                lower=f"{anchor} * {band['lower']}", upper=upper,
            ).mark_area(interpolate="linear", opacity=0.24, color=band["color"], clip=True).encode(
                x=x, y=alt.Y("lower:Q", title="Price (USD)", scale=yscale, stack=None), y2="upper:Q",
            ))
        # Fine guides follow the SMA itself, so band thresholds remain exact.
        guides = {f"guide_{index}":f"{anchor} * {multiple}" for index,multiple in enumerate((1.5,2.0,2.5,3.0))}
        layers.append(anchor_base.transform_calculate(**guides).transform_fold(list(guides),as_=["level","value"]).mark_line(
            color=WHITE, opacity=0.23, strokeWidth=0.7, strokeDash=[3, 5], interpolate="linear", clip=True
        ).encode(x=x, y=y, detail="level:N"))
    labels, colors, dashes, widths = [f"{ticker} price"], [WHITE], [[]], [2.0]
    fields = [("close", labels[0])]
    if anchor_rows:
        labels.append(f"{main_name} SMA")
        colors.append(ORANGE)
        dashes.append([8, 5])
        widths.append(3.1)
        fields.append((main_key, labels[-1]))
    if ticker != "BTC" and any(_finite(row.get("sma_50d")) for row in rows):
        labels.append("50D SMA")
        colors.append("#7d8995")
        dashes.append([2, 3])
        widths.append(1.25)
        fields.append(("sma_50d", "50D SMA"))
    tooltip = [alt.Tooltip("date:T", title="Observation", format="%b %d, %Y"),
               alt.Tooltip("series:N", title="Series"),
               alt.Tooltip("value:Q", title="USD", format="$,.2f")]
    if any(_finite(row.get("low")) or _finite(row.get("high")) for row in rows):
        tooltip.extend([alt.Tooltip("low:Q", title="Session low", format="$,.2f"),
                        alt.Tooltip("high:Q", title="Session high", format="$,.2f")])
    tooltip.append(alt.Tooltip("extension:Q", title=f"Price vs {main_name} SMA (%)", format="+.1f"))
    lines = (base.transform_fold([field for field,_ in fields],as_=["field","value"])
             .transform_filter("isValid(datum.value)")
             .transform_calculate(
                 series=_field_labels(fields),
                 low="datum.field === 'close' ? datum.low : null",
                 high="datum.field === 'close' ? datum.high : null",
                 extension=f"isValid(datum.{main_key}) && datum.{main_key} > 0 ? (datum.close / datum.{main_key} - 1) * 100 : null",
             )).mark_line(interpolate="linear", strokeWidth=2.4, clip=True).encode(
        x=x, y=y,
        color=alt.Color("series:N", scale=alt.Scale(domain=labels, range=colors),
                        legend=alt.Legend(orient="top", symbolStrokeWidth=3)),
        strokeDash=alt.StrokeDash("series:N", scale=alt.Scale(domain=labels, range=dashes), legend=None),
        strokeWidth=alt.StrokeWidth("series:N", scale=alt.Scale(domain=labels, range=widths), legend=None),
        tooltip=tooltip,
    )
    layers.append(lines)
    if anchor_rows:
        last = anchor_rows[-1]
        level_labels = [{"date": last["date"], "value": last[main_key] * multiple,
                         "label": f"{main_name} SMA · 0%" if multiple == 1 else f"+{int((multiple-1)*100)}%"}
                        for multiple in (1.0, 1.5, 2.0, 2.5, 3.0)]
        layers.append(alt.Chart(_dated_frame(level_labels)).mark_text(
            align="right", baseline="bottom", dx=-7, dy=-5, fontSize=11,
            fontWeight=600, color=WHITE, clip=True,
        ).encode(x=x, y=y, text="label:N"))
    else:
        missing = _dated_frame([{"date": rows[-1]["date"], "value": ymax - (ymax - ymin) * 0.04,
                                 "label": f"{main_name} SMA: insufficient completed history"}])
        layers.append(alt.Chart(missing).mark_text(align="right", color=MUTED, fontSize=12,
                      dx=-7).encode(x=x, y=y, text="label:N"))
    if live and live.get("date") and _finite(live.get("close")):
        frame = _dated_frame([{"date": live["date"], "value": live["close"]}])
        layers.append(alt.Chart(frame).mark_point(size=105, filled=True, color=ORANGE,
                     stroke=WHITE, strokeWidth=1.8, clip=True).encode(
            x=x, y=y, tooltip=[alt.Tooltip("date:T", title="Provider quote (UTC)", format="%b %d, %Y %H:%M"),
                              alt.Tooltip("value:Q", title="Latest quote · USD", format="$,.2f")]))
    chart = alt.layer(*layers,data=history).resolve_scale(color="independent")
    return style(chart, height)
