"""Deterministic PNG export of the calculated Friday snapshot; no provider calls."""
from __future__ import annotations
from datetime import date, datetime, timezone
from io import BytesIO
import math
from pathlib import Path
from PIL import Image, ImageColor, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from .scaling import visible_price_domain
from .series import SENTIMENT_BANDS, smooth_sentiment, year_start

WIDTH, HEIGHT = 1800, 1600
ASSETS = Path(__file__).resolve().parents[1] / "assets"
BG, CARD, TEXT, MUTED = "#0b0d0f", "#15191d", "#f5f3ed", "#9aa4ad"
LINE, ORANGE, POSITIVE, NEGATIVE = "#30363c", "#e88029", "#8cdbb5", "#f5a09b"
BANDS = ("#304cba", "#198653", "#b8a528", "#c67b1b", "#ba3b48", "#7c4da3")


def _tint(color, opacity=.24):
    base, source = ImageColor.getrgb(CARD), ImageColor.getrgb(color)
    return tuple(round(background*(1-opacity)+foreground*opacity) for background, foreground in zip(base, source))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pct(value, digits=2, signed=True):
    if not _number(value):
        return "—"
    return f"{value:+.{digits}f}%" if signed else f"{value:.{digits}f}%"


def _money(value, digits=2):
    return f"${value:,.{digits}f}" if _number(value) else "—"


def _volume(value):
    if not _number(value):
        return "—"
    for unit, divisor in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= divisor:
            return f"${value / divisor:,.2f}{unit}"
    return _money(value, 0)


def _change_color(value):
    return POSITIVE if _number(value) and value > 0 else NEGATIVE if _number(value) and value < 0 else MUTED


def _date(value, short=False):
    try:
        parsed = date.fromisoformat(str(value)[:10])
        return f"{parsed:%b} {parsed.day}" if short else f"{parsed:%b} {parsed.day}, {parsed.year}"
    except (TypeError, ValueError):
        return "Date unavailable"


def _instant(value):
    """Use UTC coordinates for both dated history and separate live markers."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _coordinate(value):
    parsed = _instant(value)
    return parsed.toordinal() + (parsed.hour * 3600 + parsed.minute * 60 + parsed.second) / 86400


def _snapshot_label(value):
    try:
        return _instant(value).strftime("%b %d, %Y %H:%M UTC")
    except (TypeError, ValueError):
        return "time unavailable"


def marker_rows(rows, point):
    """Extend only the plotting axis; never turn a live marker into an SMA bar."""
    rows = list(rows)
    if point and rows:
        try:
            if _coordinate(point["date"]) > _coordinate(rows[-1]["date"]):
                rows.append({"date": point["date"]})
        except (KeyError, TypeError, ValueError):
            pass
    return rows


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, (list, tuple)) else []


def supply_caption(panel):
    """Keep the export's attribution and estimate status with the supplied data."""
    if panel.get("mode") == "demo":
        return "% of circulating BTC · illustrative data"
    history = _rows((panel.get("supply_loss") or {}).get("series"))
    latest = history[-1] if history else {}
    source = panel.get("supply_source") or latest.get("source") or "source unavailable"
    method = panel.get("supply_method") or latest.get("method")
    estimate = " · loss = 100% − profit (estimate)" if method == "complementary_loss_estimate" else ""
    return f"% of circulating BTC · {source}{estimate}"


def sentiment_caption(panel):
    """Attribute exactly the observation selected in the displayed model."""
    if panel.get("mode") == "demo":
        return "3-day average · illustrative sentiment"
    sentiment = panel.get("sentiment") or {}
    rows = display_rows(sentiment.get("series"),panel.get("chart_cutoff") or (panel.get("period") or {}).get("end"))
    source = panel.get("sentiment_source") or sentiment.get("source") or (rows[-1].get("source") if rows else None) or "source unavailable"
    reading = "raw index + dot" if sentiment.get("live_point") else "raw daily headline"
    if not _number(sentiment.get("value")):
        reading = "reading unavailable"
    if sentiment.get("as_of"):
        reading += " · " + _date(sentiment["as_of"])
    return f"3-day average · {source} · {reading}"


def display_rows(rows, end=None, years=None, *, start=None):
    """Select a calendar display window without truncating the source history.

    Price observations are selected independently of whether an SMA exists.
    A leap-day cutoff uses February 28 in a non-leap destination year.
    """
    dated = []
    for row in _rows(rows):
        try:
            observed = date.fromisoformat(str(row.get("date"))[:10])
        except (TypeError, ValueError):
            continue
        dated.append((observed, row))
    if not dated:
        return []
    try:
        end_day = date.fromisoformat(str(end)[:10])
    except (TypeError, ValueError):
        end_day = max(day for day, _ in dated)
    start_day = date.fromisoformat(str(start)[:10]) if start is not None else date.min
    if years is not None:
        try:
            calendar_start = end_day.replace(year=end_day.year-years)
        except ValueError:
            calendar_start = end_day.replace(year=end_day.year-years, day=28)
        start_day = max(start_day, calendar_start)
    return [row for day, row in sorted(dated, key=lambda pair: pair[0]) if start_day <= day <= end_day]


def sma_segments(rows, key):
    """Keep actual contiguous SMA observations; never fill warmup or gaps."""
    result, segment = [], []
    for row in rows:
        if _number(row.get(key)) and row[key] > 0:
            segment.append(row)
        else:
            if segment:
                result.append(segment)
            segment = []
    if segment:
        result.append(segment)
    return result


def _clip_segment(start, end, box):
    """Clip one line to a rectangle before walking its dash pattern."""
    x, y = start
    dx, dy = end[0]-x, end[1]-y
    lower, upper = 0.0, 1.0
    for p, q in ((-dx,x-box[0]),(dx,box[2]-x),(-dy,y-box[1]),(dy,box[3]-y)):
        if p == 0:
            if q < 0:
                return None
            continue
        position = q/p
        if p < 0:
            lower = max(lower,position)
        else:
            upper = min(upper,position)
        if lower > upper:
            return None
    return (x+lower*dx,y+lower*dy),(x+upper*dx,y+upper*dy)


def render_png(panel: dict) -> bytes:
    """Render an immutable display projection without consulting providers."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw, fonts = ImageDraw.Draw(canvas), {}

    def font(size, bold=False):
        key = size, bold
        if key not in fonts:
            fonts[key] = ImageFont.truetype(str(ASSETS / ("report-bold.ttf" if bold else "report-regular.ttf")), size)
        return fonts[key]

    def text(x, y, value, size=23, color=TEXT, bold=False, max_width=None, align="left"):
        value, current = str(value), size
        while max_width and draw.textlength(value, font=font(current, bold)) > max_width and current > 15:
            current -= 1
        if max_width and draw.textlength(value, font=font(current, bold)) > max_width:
            while value and draw.textlength(value + "…", font=font(current, bold)) > max_width:
                value = value[:-1]
            value += "…"
        if align == "right":
            x -= draw.textlength(value, font=font(current, bold))
        draw.text((x, y), value, font=font(current, bold), fill=color)

    def card(box, accent=None):
        draw.rounded_rectangle(box, radius=10, fill=CARD)
        if accent:
            draw.rectangle((box[0], box[1], box[2], box[1]+3), fill=accent)

    def stroke(points, color, width=3, dashed=False, target=None, clip=None):
        target = draw if target is None else target
        if dashed:
            # Continuous dash distance avoids changing style with sample density.
            phase = 0.0
            for start, end in zip(points, points[1:]):
                if clip is not None:
                    clipped = _clip_segment(start,end,clip)
                    if clipped is None:
                        continue
                    start,end = clipped
                dx, dy = end[0]-start[0], end[1]-start[1]
                length = math.hypot(dx, dy)
                along = 0.0
                while along < length:
                    span = min(length-along, 10-phase % 10)
                    if phase % 20 < 10:
                        t1, t2 = along/length, (along+span)/length
                        target.line((start[0]+dx*t1, start[1]+dy*t1, start[0]+dx*t2, start[1]+dy*t2), fill=color, width=width)
                    along += span
                    phase += span
        elif len(points) > 1:
            target.line(points, fill=color, width=width)

    def time_points(rows, key, plot, low, high):
        x0, y0, x1, y1 = plot
        points, segments = [], []
        dates = [_coordinate(row["date"]) for row in rows]
        span = max(1, dates[-1]-dates[0]) if dates else 1
        for i, row in enumerate(rows):
            value = row.get(key)
            if _number(value):
                points.append((x0+(dates[i]-dates[0])/span*(x1-x0), y1-(value-low)/(high-low)*(y1-y0)))
            else:
                if points:
                    segments.append(points)
                points = []
        if points:
            segments.append(points)
        return segments

    def date_labels(rows, plot):
        if rows:
            first = date.fromisoformat(str(rows[0]["date"])[:10]).strftime("%b %Y")
            last = date.fromisoformat(str(rows[-1]["date"])[:10]).strftime("%b %Y")
            text(plot[0], plot[3]+10, first, 16, MUTED)
            text(plot[2], plot[3]+10, last, 16, MUTED, align="right")
            first_day = date.fromisoformat(str(rows[0]["date"])[:10])
            last_day = date.fromisoformat(str(rows[-1]["date"])[:10])
            if (last_day-first_day).days >= 700:
                middle = date.fromordinal((first_day.toordinal()+last_day.toordinal())//2)
                label = middle.strftime("%b %Y")
                center = (plot[0]+plot[2])/2
                text(center-draw.textlength(label,font=font(16))/2,plot[3]+10,label,16,MUTED)

    def marker(point, rows, key, plot, low, high, color):
        if not point or not rows or not _number(point.get(key)):
            return
        x0, y0, x1, y1 = plot
        try:
            first, last, observed = _coordinate(rows[0]["date"]), _coordinate(rows[-1]["date"]), _coordinate(point["date"])
        except (KeyError, TypeError, ValueError):
            return
        if not first <= observed <= last or not low <= point[key] <= high:
            return
        x = x0 + (observed-first)/max(1, last-first)*(x1-x0)
        y = y1 - (point[key]-low)/(high-low)*(y1-y0)
        draw.ellipse((x-5,y-5,x+5,y+5),fill=color,outline=CARD,width=2)

    def ordinary_chart(rows, fields, plot, *, low=0, high=100, color_bands=None, latest=None):
        rows = _rows(rows)
        rows = marker_rows(rows, latest)
        x0, y0, x1, y1 = plot
        fractions = (0, .5, 1)
        if color_bands:
            fractions = (0, .2, .4, .6, .8, 1)
            for band in color_bands:
                top = y1-(band["upper"]-low)/(high-low)*(y1-y0)
                bottom = y1-(band["lower"]-low)/(high-low)*(y1-y0)
                draw.rectangle((x0,top,x1,bottom),fill=_tint(band["color"],.09))
        for fraction in fractions:
            y = y1-fraction*(y1-y0)
            draw.line((x0, y, x1, y), fill=LINE)
            text(x0-10, y-10, f"{low+(high-low)*fraction:.0f}", 16, MUTED, align="right")
        valid = False
        for key, color in fields:
            if color_bands and rows:
                # Match the interactive chart: each segment is colored by
                # its starting smoothed reading, without changing the values.
                dates = [_coordinate(row["date"]) for row in rows]
                span = max(1,dates[-1]-dates[0])
                points = [(x0+(day-dates[0])/span*(x1-x0),y1-(row[key]-low)/(high-low)*(y1-y0))
                          if _number(row.get(key)) else None for day,row in zip(dates,rows)]
                for i,(start,end) in enumerate(zip(points,points[1:])):
                    if start is None or end is None:
                        continue
                    band = next((band for band in color_bands if rows[i][key]<band["upper"]),color_bands[-1])
                    stroke([start,end],band["color"],2 if len(rows)>500 else 3)
                    valid = True
                if len(rows)==1 and points[0] is not None:
                    band = next((band for band in color_bands if rows[0][key]<band["upper"]),color_bands[-1])
                    x,y = points[0]
                    draw.ellipse((x-2,y-2,x+2,y+2),fill=band["color"])
                    valid = True
                continue
            for segment in time_points(rows, key, plot, low, high) if rows else []:
                if len(segment) > 1:
                    valid = True
                    stroke(segment, color, 2 if len(rows)>500 else 3)
        if not valid:
            text(x0+15, y0+40, "History unavailable", 21, MUTED)
        if latest:
            value = latest.get("value")
            band = next((band for band in SENTIMENT_BANDS if _number(value) and value < band["upper"]), SENTIMENT_BANDS[-1])
            marker(latest, rows, "value", plot, low, high, band["color"])
        date_labels(rows, plot)

    period, header = panel.get("period") or {}, panel.get("header") or {}
    chart_cutoff = panel.get("chart_cutoff") or period.get("end")
    demo = panel.get("mode") == "demo"
    draw.rectangle((0, 0, WIDTH, 5), fill=ORANGE)
    text(54, 34, "THE FRIDAY CLOSE", 19, ORANGE, True)
    text(54, 64, "Bitcoin & Digital Credit", 49, TEXT, True)
    text(1746, 39, "DEMO · SYNTHETIC SAMPLE DATA" if demo else "LATEST AVAILABLE · ESTIMATED", 19, ORANGE, True, align="right")
    text(1746, 75, f"Week ended {_date(period.get('week_ending', period.get('end')))}", 25, align="right")
    text(1746, 111, "Charts refreshed " + _snapshot_label(panel["snapshot_as_of"]) if panel.get("export_basis") == "displayed_latest" and panel.get("snapshot_as_of") else "U.S. market close · Eastern time", 18, MUTED, align="right")

    columns = [(54,160,606,363), (624,160,1176,363), (1194,160,1746,363)]
    btc = header.get("btc") or {}
    card(columns[0], ORANGE)
    text(78, 179, "BITCOIN", 21, bold=True)
    text(78, 212, _money(btc.get("price"), 0), 52, bold=True)
    change = btc.get("weekly_return_pct")
    text(78, 276, _pct(change)+" this week", 26, _change_color(change), True)
    text(78, 325, "Previous close → Friday close", 19, MUTED)
    companies = header.get("companies") or {}
    treasury = {row.get("ticker"):row for row in _rows(panel.get("treasury"))}
    for ticker, box in zip(("MSTR","ASST"), columns[1:]):
        x0, _, x1, _ = box
        company, baseline = companies.get(ticker) or {}, treasury.get(ticker) or {}
        card(box, TEXT)
        text(x0+24, 179, ticker, 21, bold=True)
        text(x1-24, 180, "PRICE / NAV", 18, MUTED, align="right")
        multiple = company.get("nav_multiple")
        text(x0+24, 212, f"{multiple:.2f}x" if _number(multiple) else "—", 52, bold=True)
        multiple_change=company.get("nav_multiple_change",baseline.get("nav_multiple_change"))
        multiple_change_label=f"WoW {multiple_change:+.2f}x" if _number(multiple_change) else "WoW —"
        text(x1-24,232,multiple_change_label,22,_change_color(multiple_change),align="right")
        text(x0+24, 268, f"NAV/share  {_money(company.get('nav_per_share',baseline.get('nav_per_share')))}", 22, MUTED)
        holdings = baseline.get("btc_held")
        held = f"{holdings:,.0f}" if _number(holdings) else "—"
        balances = [f"Bitcoin Held  {held}", f"Cash  {_volume(baseline.get('cash_usd'))}"]
        if ticker == "MSTR":
            balances.append(f"Debt  {_volume(baseline.get('debt_usd'))}")
        text(x0+24, 294, "   ·   ".join(balances), 18, MUTED, max_width=x1-x0-48)
        draw.line((x0+24,323,x1-24,323), fill=LINE)
        valid = baseline.get("valid",True)
        impact, impact_pct = baseline.get("btc_effect_per_share"), baseline.get("nav_change_pct")
        if not valid:
            impact = impact_pct = None
        amount = f"{'+' if impact >= 0 else '−'}${abs(impact):,.2f}" if _number(impact) else "—"
        text(x0+24,329,"NAV/share WoW  "+amount,20,_change_color(impact),max_width=380)
        text(x1-24,329,_pct(impact_pct),20,_change_color(impact_pct),align="right")

    text(54,391,"WEEKLY DOLLAR TRADING VOLUME",22,bold=True)
    text(1746,394,"Last 12 completed weeks · regular sessions",19,MUTED,align="right")
    liquidity = {row.get("ticker"):row for row in _rows(panel.get("liquidity"))}
    for box, title, tickers in [((54,432,891,758),"Common stock",("MSTR","ASST")),((909,432,1746,758),"Preferred stock",("STRC","SATA"))]:
        x0,y0,x1,y1=box
        card(box)
        text(x0+24,y0+17,title,21,MUTED)
        history={ticker:{str(row.get("date",row.get("week_ending"))):row for row in _rows(liquidity.get(ticker,{}).get("weekly_series"))[-12:]} for ticker in tickers}
        weeks=sorted(set().union(*(set(rows) for rows in history.values())))[-12:]
        for i,ticker in enumerate(tickers):
            item=liquidity.get(ticker,{})
            x=x0+24+i*400
            color=ORANGE if i==0 else TEXT
            draw.rectangle((x,y0+53,x+13,y0+66),fill=color)
            value=item.get("dollars") if item.get("complete",True) else None
            label=("≈ " if item.get("estimated") and _number(value) else "")+_volume(value)
            text(x+23,y0+46,f"{ticker}  {label}",25,color,True,max_width=360)
            text(x,y0+82,f"WoW {_pct(item.get('change_pct'),1)}  ·  4wk {_pct(item.get('vs_4week_average_pct'),1)}",17,MUTED,max_width=360)
        plot=(x0+80,y0+125,x1-25,y0+260)
        amounts=[row.get("dollars") for rows in history.values() for row in rows.values() if row.get("complete",True)]
        top=max([v for v in amounts if _number(v) and v>0] or [1])*1.05
        for ratio in (0,.5,1):
            y=plot[3]-ratio*(plot[3]-plot[1])
            draw.line((plot[0],y,plot[2],y),fill=LINE)
            text(plot[0]-9,y-9,_volume(top*ratio),15,MUTED,align="right")
        if not weeks:
            text(plot[0]+15,plot[1]+42,"Weekly history unavailable",21,MUTED)
        for j,week in enumerate(weeks):
            group=(plot[2]-plot[0])/max(1,len(weeks))
            center=plot[0]+group*(j+.5)
            bar=min(17,group*.3)
            for i,ticker in enumerate(tickers):
                row=history[ticker].get(week,{})
                value=row.get("dollars") if row.get("complete",True) else None
                left=center+(i-1)*bar+i*3
                if _number(value) and value>=0:
                    draw.rectangle((left,plot[3]-value/top*(plot[3]-plot[1]),left+bar,plot[3]),fill=ORANGE if i==0 else TEXT)
                else:
                    text(left,plot[3]-18,"—",14,MUTED)
            if j in (0,3,7,len(weeks)-1):
                label=_date(week,True)
                text(center-draw.textlength(label,font=font(15))/2,plot[3]+10,label,15,MUTED)
        note="≈ Close × volume estimate" if any(liquidity.get(t,{}).get("estimated") for t in tickers) else "Total dollars traded"
        text(x0+24,y1-27,note+" · separate scale for each pair",16,MUTED)

    text(54,786,"BITCOIN SUPPLY & SENTIMENT",22,bold=True)
    text(1746,789,"Displayed latest readings" if panel.get("export_basis") == "displayed_latest" else "Daily observations",19,MUTED,align="right")
    loss=panel.get("supply_loss") or {}
    sentiment=panel.get("sentiment") or {}
    card((54,827,891,1121))
    text(78,844,"SUPPLY IN LOSS / PROFIT",21,MUTED,True)
    text(863,847,"4 YEARS",17,MUTED,True,align="right")
    text(78,880,_pct(loss.get("value"),1,False)+" in loss",34,NEGATIVE,True)
    text(520,880,_pct(loss.get("profit_pct"),1,False)+" in profit",34,ORANGE,True)
    ordinary_chart(display_rows(loss.get("series"),chart_cutoff,4),(("value",NEGATIVE),("profit_pct",ORANGE)),(112,941,863,1069))
    text(78,1099,supply_caption(panel),15,MUTED,max_width=785)
    card((909,827,1746,1121))
    text(933,844,"FEAR & GREED",21,MUTED,True)
    text(1718,847,"FROM JUL 2023",17,MUTED,True,align="right")
    value=sentiment.get("value")
    text(933,880,f"{value:.0f} / 100" if _number(value) else "—",34,TEXT,True)
    if _number(value) and 0 <= value <= 100:
        # Classify the exact selected display value, preserving provider naming.
        band=next((band for band in SENTIMENT_BANDS if value < band["upper"]),SENTIMENT_BANDS[-1])
        level=sentiment.get("classification") or band["label"].title()
        badge_width=draw.textlength(level,font=font(20,True))+28
        draw.rounded_rectangle((1130,882,1130+badge_width,920),radius=10,
                               fill=_tint(band["color"],.16),outline=band["color"],width=1)
        text(1144,888,level,20,band["color"],True)
    delta=sentiment.get("change")
    text(1718,890,f"{delta:+.1f} points WoW" if _number(delta) else "Weekly change —",22,MUTED,align="right")
    smoothed_sentiment=smooth_sentiment(_rows(sentiment.get("series")),window=3)
    ordinary_chart(display_rows(smoothed_sentiment,chart_cutoff,start="2023-07-01"),(("smoothed_value",ORANGE),),(966,941,1718,1069),color_bands=SENTIMENT_BANDS,latest=sentiment.get("live_point"))
    text(933,1099,sentiment_caption(panel),15,MUTED,max_width=785)

    text(54,1147,"PRICE & MOVING-AVERAGE EXTENSIONS",22,bold=True)
    text(1746,1150,"Bands: 0%, +50%, +100%, +150%, +200% above SMA",19,MUTED,align="right")
    for i,(ticker,average,key) in enumerate((("BTC","200W","sma_200w"),("MSTR","200D","sma_200d"),("ASST","200D","sma_200d"))):
        x0=54+i*570
        x1=x0+552
        y0,y1=1188,1518
        card((x0,y0,x1,y1))
        item=(panel.get("trends") or {}).get(ticker) or {}
        metric=(item.get("averages") or {}).get(average) or {}
        text(x0+22,y0+17,f"{ticker} · {average} SMA",23,TEXT,True)
        text(x1-22,y0+16,_pct(metric.get("extension_pct"),1),27,TEXT,True,align="right")
        stroke([(x0+22,y0+63),(x0+51,y0+63)],TEXT,4)
        text(x0+60,y0+51,"BTC price" if ticker=="BTC" else "Stock price",18,TEXT)
        stroke([(x0+212,y0+63),(x0+243,y0+63)],ORANGE,3,True)
        text(x0+252,y0+51,average+" SMA",18,ORANGE)
        years=4 if ticker=="BTC" else 1
        price_cutoff=item.get("price_as_of") or chart_cutoff
        live_point=item.get("live_point")
        if ticker=="ASST":
            try:
                asst_start=year_start(price_cutoff)
            except (TypeError,ValueError):
                asst_start=None
            text(x1-22,y0+53,"From Jan 1" if asst_start else "Date unavailable",17,MUTED,align="right")
            rows=display_rows(item.get("series"),price_cutoff,start=asst_start)
        else:
            text(x1-22,y0+53,"4 years" if years==4 else "1 year",17,MUTED,align="right")
            rows=display_rows(item.get("series"),price_cutoff,years)
        rows=marker_rows(rows,live_point)
        segments=sma_segments(rows,key)
        anchors=[row[key] for segment in segments for row in segment]
        prices=[row["close"] for row in rows if _number(row.get("close")) and row["close"]>0]
        plot=(x0+70,y0+95,x1-72,y0+279)
        if not anchors or len(prices)<2:
            if len(prices)>1:
                low,high=visible_price_domain(rows,live_point,anchor_key=key if ticker=="ASST" else None)
                ordinary_chart(rows,(("close",TEXT),),plot,low=low,high=high)
                marker(live_point,rows,"close",plot,low,high,TEXT)
                text(x0+22,y1-25,average+" SMA unavailable · insufficient history",15,MUTED,max_width=508)
            else:
                text(x0+24,y0+155,"Price / SMA history unavailable",21,MUTED)
            continue
        low,high=visible_price_domain(rows,live_point,anchor_key=key if ticker=="ASST" else None)
        xleft,ytop,xright,ybottom=plot
        # Pillow clips this local layer at the plot rectangle, preserving the
        # real sloped boundaries instead of clamping them onto chart edges.
        layer=Image.new("RGB",(xright-xleft+1,ybottom-ytop+1),CARD)
        layer_draw=ImageDraw.Draw(layer)
        layer_box=(0,0,layer.width-1,layer.height-1)
        dates=[_coordinate(row["date"]) for row in rows]
        span=max(1,dates[-1]-dates[0])
        def px(row):
            observed=_coordinate(row["date"])
            return xleft+(observed-dates[0])/span*(xright-xleft)
        def py(value):
            return ybottom-(value-low)/(high-low)*(ybottom-ytop)
        def local(points):
            return [(x-xleft,y-ytop) for x,y in points]
        for segment in segments:
            if len(segment)<2:
                continue
            values=[row[key] for row in segment]
            coords=[px(row) for row in segment]
            ceiling=max(high,max(values)*3.35)
            bounds=[[py(0)]*len(segment)]+[[py(value*multiple) for value in values] for multiple in (1,1.5,2,2.5,3)]+[[py(ceiling)]*len(segment)]
            for band,color in enumerate(BANDS):
                points=list(zip(coords,bounds[band]))+list(reversed(list(zip(coords,bounds[band+1]))))
                layer_draw.polygon(local(points),fill=_tint(color))
        for level in (0,.5,1):
            value=low+level*(high-low)
            text(xleft-8,py(value)-8,_volume(value),14,MUTED,align="right")
        label_centers=[]
        for n,multiple in enumerate((1,1.5,2,2.5,3)):
            for segment in segments:
                points=[(px(row),py(row[key]*multiple)) for row in segment]
                stroke(local(points),ORANGE if n==0 else "#6d7073",3 if n==0 else 1,True,target=layer_draw,clip=layer_box)
            if segments:
                boundary=segments[-1][-1][key]*multiple
                label_y=py(boundary)
                if low <= boundary <= high and all(abs(label_y-other)>=18 for other in label_centers):
                    text(xright+8,label_y-8,f"{n*50:+d}%" if n else "0%",15,ORANGE if n==0 else MUTED)
                    label_centers.append(label_y)
        for segment in time_points(rows,"close",plot,low,high):
            stroke(local(segment),TEXT,4,target=layer_draw)
        canvas.paste(layer,(xleft,ytop))
        marker(live_point,rows,"close",plot,low,high,TEXT)
        date_labels(rows,plot)
        caption="USD · SMA includes premerger ticker history" if ticker=="ASST" else "Price in USD · bands follow the SMA"
        if not _number(rows[0].get(key)):
            first_anchor=date.fromisoformat(str(segments[0][0]["date"])[:10]).strftime("%b %Y")
            caption=f"{average} SMA starts {first_anchor} · price in USD"
        text(x0+22,y1-25,caption,15,MUTED,max_width=508)

    footer="SYNTHETIC DEMO · All values and histories are illustrative. Not a current market report." if demo else "Estimated basic treasury NAV · disclosed quantities held fixed · unavailable data shown as —"
    text(54,1540,footer,18,ORANGE if demo else MUTED,max_width=1692)
    text(54,1570,"NAV/share WoW isolates BTC price; shares, cash, other assets and senior claims stay fixed. 4wk = prior four-week average.",16,MUTED,max_width=1692)
    output=BytesIO()
    metadata=PngInfo()
    for field in ("export_basis", "snapshot_as_of", "chart_cutoff"):
        if panel.get(field):
            metadata.add_text(field,str(panel[field]))
    metadata.add_text("financial_week_end",str(period.get("end") or "unavailable"))
    if not demo:
        for field in ("sentiment_source","sentiment_source_url"):
            if panel.get(field):
                metadata.add_text(field,str(panel[field]))
        if sentiment.get("as_of"):
            metadata.add_text("sentiment_as_of",str(sentiment["as_of"]))
        if _number(sentiment.get("value")):
            metadata.add_text("sentiment_value",str(sentiment["value"]))
        if loss.get("as_of"):
            metadata.add_text("supply_as_of",str(loss["as_of"]))
        for ticker,item in (panel.get("trends") or {}).items():
            if item.get("price_as_of"):
                metadata.add_text(ticker+"_price_as_of",str(item["price_as_of"]))
    canvas.save(output,format="PNG",optimize=True,pnginfo=metadata)
    return output.getvalue()
