"""Admission check for scheduled Monday publication; never accepts fallback data."""
from dataclasses import asdict
from datetime import date
from io import BytesIO

from PIL import Image

from .dated_baselines import baseline_dates
from .live_report import resolve_live_report, _complete_panel_inputs
from .post_export import render_post_png
from .presentation import build_report_view
from .public_page import public_stylesheet, render_public_report


def publication_check(prices: dict, feed: dict):
    result = resolve_live_report(prices, feed)
    report = result.report
    if result.notice:
        raise ValueError(result.notice)
    if not _complete_panel_inputs(report, prices):
        raise ValueError("Latest filing pair has incomplete NAV, capital, comparison or period-growth inputs")
    view = build_report_view(report, prices=prices)
    html = render_public_report(view)
    for missing in ("Unavailable", "Not disclosed", "unverified", "NaN"):
        if missing in html:
            raise ValueError(f"Rendered report contains {missing}")
    png = render_post_png(view)
    with Image.open(BytesIO(png)) as rendered:
        rendered.verify()
    summary = {
        "status": "complete", "version": result.version, "subtitle": report.subtitle,
        "price_fetched_at": prices["fetched_at"],
        "companies": {company.ticker: {
            "balance_date": company.balance_date,
            "prior_balance_date": company.prior_balance_date,
            "required_period_baselines": baseline_dates(date.fromisoformat(company.balance_date)),
            "current": asdict(company.current),
        } for company in report.companies},
    }
    return summary, '<!doctype html><meta charset="utf-8">' + public_stylesheet() + html, png
