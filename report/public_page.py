"""Responsive public report; the fixed-size post image is a download only."""
from html import escape

from .page import ASSETS, asset_uri
from .view_types import CompanyView, MetricView, ReportView


def _tone(value: str) -> str:
    return value if value in {"positive", "negative", "neutral"} else "neutral"


def _capital(metric: MetricView, css: str) -> str:
    notes = "".join(f'<p class="transaction-note">{escape(line)}</p>'
                    for line in (metric.post_details or metric.details))
    return f'''<section class="capital-row {css}">
      <div class="capital-value"><h3>{escape(metric.label)}</h3><strong>{escape(metric.value)}</strong></div>
      {notes}</section>'''


def _metric(label: str, value: str, delta: str, tone: str = "neutral", *, featured: bool = False) -> str:
    css = "btc-growth-row" if featured else ""
    return f'''<tr class="{css}"><th scope="row">{escape(label)}</th>
      <td class="metric-value">{escape(value)}</td>
      <td><span class="delta {_tone(tone)}">{escape(delta)}</span></td></tr>'''


def _company(c: CompanyView, period: str) -> str:
    btc = c.bought.value if c.bought else "Not disclosed"
    total = c.total_bitcoin.value if c.total_bitcoin else "Not disclosed"
    metric_rows = (
        _metric("Bitcoin per common share", c.bitcoin.value,
                c.bitcoin.short_change or c.bitcoin.change, c.bitcoin.tone, featured=True)
        + _metric("NAV per common share", c.nav_per_share, c.nav_change.value, c.nav_change.tone)
        + _metric("Net BTC amplification", c.amplification.value,
                  c.amplification.short_change or c.amplification.change)
        + _metric("Preferred / BTC", c.preferred_ratio.value,
                  c.preferred_ratio.short_change or c.preferred_ratio.change)
    )
    period_headers = "".join(f'<th scope="col">{escape(p.period)}</th>' for p in c.periods)
    btc_periods = "".join(f'<td class="{_tone(p.btc_tone)}">{escape(p.btc_growth)}</td>' for p in c.periods)
    nav_periods = "".join(f'<td class="{_tone(p.nav_tone)}">{escape(p.nav_growth)}</td>' for p in c.periods)
    growth = f'''<section class="growth-panel"><table aria-label="{escape(c.name)} quarter and year growth">
      <thead><tr><th scope="col">Basic-share growth</th>{period_headers}</tr></thead>
      <tbody><tr><th scope="row">BTC / share</th>{btc_periods}</tr>
      <tr><th scope="row">NAV / share</th>{nav_periods}</tr></tbody></table></section>''' if c.periods else ''
    return f'''<article class="credit-card {escape(c.logo)}" aria-label="{escape(c.name)} comparison panel">
      <header class="issuer-head">
        <img src="{asset_uri(c.logo + '.svg', 'image/svg+xml')}" alt="{escape(c.name)}" class="issuer-logo">
        <div class="equity-quote"><strong>{escape(c.stock_price)}</strong>
          <span>{escape(c.ticker)} · {escape(c.quote_session.lower())}</span>
          <time>{escape(c.quote_timestamp)}</time></div>
      </header>
      <section class="valuation-pair">
        <div><h3>Net treasury NAV / share</h3><strong>{escape(c.nav_per_share)}</strong></div>
        <div><h3>Price / basic NAV</h3><strong>{escape(c.price_to_nav)}</strong></div>
      </section>
      <section class="bitcoin-pair">
        <div><h3>Bitcoin Bought</h3><strong>{escape(btc)}</strong></div>
        <div><h3>Total BTC held</h3><strong>{escape(total)}</strong></div>
      </section>
      <section class="market-activity" aria-label="{escape(c.name)} market activity">
        <div class="capital-period"><span>{escape(period)}</span><span>+ raised / − repurchased</span></div>
        {_capital(c.common, 'common-capital')}
        {_capital(c.preferred, 'preferred-capital')}
        <div class="common-shares"><div><h3>{escape(c.shares.label)}</h3><strong>{escape(c.shares.value)}</strong></div>
          <p>{escape(c.shares.change)}</p></div>
      </section>
      <section class="weekly-metrics"><table aria-label="{escape(c.name)} weekly per-share comparison">
        <colgroup><col class="metric-label-col"><col class="metric-value-col"><col class="metric-delta-col"></colgroup>
        <thead><tr><th scope="col"><span class="screen-reader-only">Metric</span></th><th scope="col">Value</th><th scope="col">WoW Δ</th></tr></thead>
        <tbody>{metric_rows}</tbody></table></section>
      {growth}
    </article>'''


def render_public_report(view: ReportView) -> str:
    cards = "".join(_company(c, view.capital_period_label) for c in view.companies)
    title = ('<span class="title-prefix">The </span>'
             '<span class="title-focus">Digital Credit</span>'
             '<span class="title-suffix"> Report</span>'
             if view.title == "The Digital Credit Report" else escape(view.title))
    return f'''<div class="dcr">
      <header class="credit-report-head">
        <div><h1 class="title-lockup" aria-label="{escape(view.title)}">{title}</h1><p>{escape(view.subtitle)}</p></div>
        <div class="market-summary"><strong>BTC {escape(view.btc_price)}</strong>
          <span>{escape(view.report_time.replace('Updated ', 'Quotes updated ', 1))}</span></div>
      </header>
      <main class="credit-grid" aria-label="Strategy and Strive weekly capital report">{cards}</main>
      <footer class="credit-footnote">≈ estimates · NAV growth at constant prices · {escape(view.comparison_note)}.</footer>
    </div>'''


def public_stylesheet() -> str:
    regular = asset_uri('report-regular.woff2', 'font/woff2')
    bold = asset_uri('report-bold.woff2', 'font/woff2')
    css = (ASSETS / 'public.css').read_text(encoding='utf-8')
    return f"<style>@font-face{{font-family:Report;src:url('{regular}') format('woff2');font-weight:400;font-display:swap}}@font-face{{font-family:Report;src:url('{bold}') format('woff2');font-weight:700;font-display:swap}}{css}</style>"
