"""Accessible HTML/CSS presentation. All displayed financial values come from the view."""
import base64
from dataclasses import replace
from html import escape
from pathlib import Path

from .view_types import CompanyView, MetricView, ReportView, btc_activity_metrics

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def asset_uri(name: str, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode((ASSETS / name).read_bytes()).decode("ascii")


def _details(metric: MetricView) -> str:
    return "".join(f'<p class="detail">{escape(line)}</p>' for line in metric.details)


def _row(metric: MetricView, css: str = "") -> str:
    value_class = "value missing" if metric.value in ("Not disclosed", "Unavailable") else "value"
    return f'''<section class="metric {css}">
      <div class="metric-top"><h3>{escape(metric.label)}</h3><span class="{value_class}">{escape(metric.value)}</span></div>
      <div class="metric-bottom"><div>{_details(metric)}</div><p class="change">{escape(metric.change)}</p></div>
    </section>'''


def _panel(c: CompanyView, capital_period_label: str) -> str:
    common = replace(c.common, details=c.common.post_details or c.common.details)
    preferred = replace(c.preferred, details=c.preferred.post_details or c.preferred.details)
    nav = MetricView("NAV per common share", c.nav_per_share, change=c.nav_change.value, tone=c.nav_change.tone)
    periods = "".join(f'<tr><th>{escape(p.period)}</th><td>{escape(p.btc_growth)}</td><td>{escape(p.nav_growth)}</td></tr>' for p in c.periods)
    period_table = f'<div class="period-panel"><table><thead><tr><th>Basic-share growth</th><th>BTC / share</th><th>NAV / share</th></tr></thead><tbody>{periods}</tbody></table></div>' if periods else ''
    return f'''<article class="company-panel {escape(c.logo)}" aria-label="{escape(c.name)} comparison panel">
      <header class="company-head">
        <img class="company-logo" src="{asset_uri(c.logo + '.svg', 'image/svg+xml')}" alt="{escape(c.name)} official logo">
        <div class="quote"><div class="stock-price">{escape(c.stock_price)}</div>
          <div class="session"><b>{escape(c.ticker)}</b><span>·</span>{escape(c.quote_session)}</div>
          <div class="quote-time">{escape(c.quote_timestamp)}</div>
        </div>
      </header>
      <section class="nav-summary">
        <div><h3>Net treasury NAV / share</h3><div class="nav-value">{escape(c.nav_per_share)}</div></div>
        <div class="nav-ratio"><h3>Price / basic NAV</h3><div>{escape(c.price_to_nav)}</div></div>
        <p class="nav-note">{escape(c.nav_note)}</p>
      </section>
      {''.join(_row(activity, 'bitcoin-activity') for activity in btc_activity_metrics(c))}
      {_row(c.total_bitcoin, 'bitcoin-held') if c.total_bitcoin else ''}
      <div class="capital-heading"><span>{escape(capital_period_label)}</span><span>+ raised / − repurchased</span></div>
      {_row(common, 'common-capital')}
      {_row(preferred, 'preferred-capital')}
      {_row(c.shares, 'shares-row')}
      {_row(c.bitcoin, 'bitcoin-row')}
      {_row(nav, 'nav-per-share-row')}
      {_row(c.amplification, 'amplification-row')}
      {_row(c.preferred_ratio, 'preferred-ratio-row')}
      {period_table}
    </article>'''


def render_header(v: ReportView) -> str:
    return f'''<div class="mcr"><header class="report-head">
      <div><div class="preview-label"><span class="preview-dot"></span>{escape(v.label)}</div>
        <h1>{escape(v.title)}</h1><p class="subtitle">{escape(v.subtitle)}</p></div>
      <div class="edition"><div class="edition-label">Monday edition</div><strong>{escape(v.report_time)}</strong>
        <div class="btc-price">BTC reference <b>{escape(v.btc_price)}</b></div><div class="btc-time">{escape(v.btc_timestamp)}</div></div>
    </header></div>'''


def render_panels(v: ReportView) -> str:
    return '<main class="mcr"><div class="report-grid">' + ''.join(_panel(c, v.capital_period_label) for c in v.companies) + '</div></main>'


def render_footer(v: ReportView) -> str:
    return f'<footer class="mcr report-footer"><span>{escape(v.footer)}</span><span>Same definitions. Same share basis.</span></footer>'


def render_post_preview(v: ReportView, png: bytes) -> str:
    """Show the exact downloadable post image, scaled only for the screen."""
    data = base64.b64encode(png).decode("ascii")
    summary = [v.title, v.label, v.report_time, f"BTC {v.btc_price}", v.subtitle, v.capital_period_label]
    for c in v.companies:
        summary.extend((c.name, c.ticker, c.stock_price, f"NAV/share {c.nav_per_share}", f"Price/basic NAV {c.price_to_nav}"))
        summary.append(c.nav_note)
        for activity in btc_activity_metrics(c):
            summary.append(f"{activity.label}: {activity.value}")
        if c.total_bitcoin:
            summary.append(f"{c.total_bitcoin.label}: {c.total_bitcoin.value}")
        for metric in (c.common, c.preferred, c.shares, c.bitcoin, c.nav_change, c.amplification, c.preferred_ratio):
            summary.append(f"{metric.label}: {metric.value} {metric.change}")
            if metric.overline:
                summary.append(metric.overline)
            summary.extend(metric.post_details or metric.details)
        for period in c.periods:
            summary.append(f"{period.period} basic-share growth: BTC/share {period.btc_growth}; NAV/share {period.nav_growth}")
    alt = escape(". ".join(summary))
    return f'''<figure class="post-preview" aria-label="Complete report for a weekly post">
      <img src="data:image/png;base64,{data}" alt="{alt}">
    </figure>'''


def stylesheet(post_view: bool = False) -> str:
    regular = asset_uri('report-regular.ttf', 'font/ttf')
    bold = asset_uri('report-bold.ttf', 'font/ttf')
    css = (ASSETS / 'report.css').read_text(encoding='utf-8')
    css += '\n.period-panel { padding: 22px 0; } .period-panel table { width:100%; border-collapse:collapse; } .period-panel th, .period-panel td { padding:12px; text-align:right; border-top:1px solid #DEE5E6; } .period-panel th:first-child { text-align:left; }'
    if post_view:
        css += (ASSETS / 'post.css').read_text(encoding='utf-8')
    return f"<style>@font-face{{font-family:Report;src:url('{regular}') format('truetype');font-weight:400;font-display:swap}}@font-face{{font-family:Report;src:url('{bold}') format('truetype');font-weight:700;font-display:swap}}{css}</style>"
