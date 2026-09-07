"""Shared, formatted presentation contract for the page and PNG renderer."""
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricView:
    label: str
    value: str
    details: tuple[str, ...] = ()
    change: str = ""
    tone: str = "neutral"
    overline: str = ""
    post_details: tuple[str, ...] = ()
    short_change: str = ""


@dataclass(frozen=True)
class PeriodGrowthView:
    period: str
    btc_growth: str
    nav_growth: str
    btc_tone: str = "neutral"
    nav_tone: str = "neutral"


@dataclass(frozen=True)
class CompanyView:
    name: str
    ticker: str
    logo: str
    stock_price: str
    quote_session: str
    quote_timestamp: str
    nav_per_share: str
    price_to_nav: str
    common: MetricView
    preferred: MetricView
    shares: MetricView
    bitcoin: MetricView
    nav_change: MetricView
    amplification: MetricView
    preferred_ratio: MetricView
    nav_note: str = "After debt & preferred claims · effective Class A + B shares"
    bought: MetricView | None = None
    periods: tuple[PeriodGrowthView, ...] = ()
    total_bitcoin: MetricView | None = None


@dataclass(frozen=True)
class ReportView:
    title: str
    report_time: str
    btc_price: str
    btc_timestamp: str
    companies: tuple[CompanyView, ...]
    label: str = "ILLUSTRATIVE DATA — TEST PREVIEW"
    subtitle: str = "What changed for the common shareholder?"
    footer: str = "All prices, timestamps and company figures are illustrative. No live market data."
    capital_period_label: str = "Capital this week"
    comparison_note: str = ""
