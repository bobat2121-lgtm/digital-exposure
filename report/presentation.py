"""Build one formatted report consumed unchanged by HTML and PNG renderers."""
from math import isfinite
from dataclasses import replace

from .calculations import (calculate_company, common_average_sale_price, preferred_activity_capital,
                           preferred_average_repurchase_price, weekly_vwap)
from .models import Company, CompanyMetrics, PreferredActivity, Report
from .view_types import CompanyView, MetricView, PeriodGrowthView, ReportView

MISSING = "Not disclosed"


def number(value: float | None, decimals: int = 2, *, prefix: str = "",
           suffix: str = "", signed: bool = False, divisor: float = 1) -> str:
    if value is None or not isfinite(value):
        return MISSING
    value = round(value / divisor, decimals)
    # Compare after rounding to suppress negative zero at the displayed precision.
    sign = "−" if value < 0 else "+" if signed and value > 0 else ""
    return f"{sign}{prefix}{abs(value):,.{decimals}f}{suffix}"


def money(value: float | None, *, signed: bool = False) -> str:
    return number(value, 1, prefix="$", suffix="m", divisor=1e6, signed=signed)


def ratio(value: float | None, nav: float | None) -> str:
    return "N/M" if nav is not None and nav <= 0 else number(value, suffix="×")


def _common_details(c: Company, m: CompanyMetrics) -> tuple[str, ...]:
    if m.common_capital_estimated:
        if m.common_equity_vwap is None:
            return (f"{number(m.shares_change, 0, signed=True)} net new common shares",
                    "Prior-week equity VWAP not verified · estimate unavailable")
        if c.equity_vwap_note:
            return (f"{number(m.shares_change, 0, signed=True)} net new shares × {number(m.common_equity_vwap, prefix='$')} VWAP (est.)",
                    c.equity_vwap_note)
        return (
            f"{number(m.shares_change, 2, divisor=1e6, suffix='m', signed=True)} net new shares × {number(m.common_equity_vwap, prefix='$')} prior-week equity VWAP",
            "Before fees · estimated from the share-count change",
        )
    issuance = f"Issuance: {money(c.common_capital.issuance_proceeds_after_fees, signed=True)}"
    buybacks = f"Buybacks: {money(m.common_buybacks_cash)}"
    note = c.common_capital.proceeds_basis if m.net_common_capital is not None else "Cash flows cannot be inferred from the share count"
    details = [f"{issuance} · {buybacks}"]
    if c.common_capital.issued_shares is not None:
        details.append(f"{number(c.common_capital.issued_shares, 0)} shares sold · {number(c.common_capital.repurchased_shares, 0)} repurchased")
    if c.common_capital.issuance_includes_warrants is False:
        details.append(f"Separate warrant cash: {money(c.common_capital.separately_reported_warrant_cash, signed=True)}")
    details.append(note)
    return tuple(details)


def _repurchase_price_details(a: PreferredActivity) -> tuple[str, ...]:
    price = preferred_average_repurchase_price(a)
    return () if price is None else (f"Avg. repurchase price: {number(price, prefix='$')}",)


def _preferred_details(c: Company) -> tuple[str, ...]:
    if c.preferred_activity_notes:
        return c.preferred_activity_notes
    details = []
    for a in c.preferred_activity:
        if a.capital_method == "reported":
            if a.issued_shares == 0 and a.repurchased_shares == 0:
                details.append(f"{a.series}: 0 issued / repurchased")
            else:
                details.extend((
                    f"{a.series}: {number(a.issued_shares, 0)} issued · {number(a.repurchased_shares, 0)} repurchased",
                    *_repurchase_price_details(a),
                    f"Reported proceeds {money(a.reported_issuance_proceeds)} · repurchase cost {money(a.reported_repurchases_cash)}",
                ))
            continue
        if a.series == "All other preferred series":
            details.append(f"Other preferred series: {money(preferred_activity_capital(a), signed=True)} net")
            continue
        issued = number(a.issued_shares, 0)
        repurchased = number(a.repurchased_shares, 2, divisor=1e6, suffix="m")
        price = number(a.issuance_price_assumption, 0, prefix="$")
        vwap = weekly_vwap(a.prior_week_trades) if a.prior_week_trades is not None else a.prior_week_vwap
        if a.issued_shares is None:
            details.append(f"{a.series} issuance: Not disclosed")
        elif a.issued_shares == 0:
            details.append(f"{a.series}: 0 issued · {repurchased} shares repurchased")
        else:
            details.append(f"{a.series}: {issued} shares issued × {price} assumed")
        if a.repurchased_shares == 0:
            details.append("Repurchases: 0 shares")
        elif a.repurchased_shares is None:
            details.append("Repurchases: Not disclosed")
        else:
            buyback_quantity = f"{repurchased} shares repurchased · " if a.issued_shares != 0 else ""
            details.append(f"{buyback_quantity}{number(vwap, prefix='$')} prior-week VWAP · estimated cash cost")
    return tuple(details)


def _common_post_details(c: Company, m: CompanyMetrics) -> tuple[str, ...]:
    if c.common_capital_method == "reported_atm":
        sold = f"{number(c.common_capital.issued_shares, 0)} shares sold"
        average = common_average_sale_price(c.common_capital)
        return (f"{sold} · {number(average, prefix='$')} avg. sale price",) if average is not None else (sold,)
    if m.common_capital_estimated:
        if c.equity_vwap_note:
            return (f"{number(m.shares_change, 0, signed=True)} net shares · {number(m.common_equity_vwap, prefix='$')} VWAP est.",)
        if m.common_equity_vwap is None:
            return _common_details(c, m)
        return (
            f"{number(m.shares_change, 2, divisor=1e6, suffix='m', signed=True)} net shares · {number(m.common_equity_vwap, prefix='$')} equity VWAP est.",
        )
    return _common_details(c, m)


def _preferred_post_details(c: Company) -> tuple[str, ...]:
    if any(a.capital_method == "share_change_par" for a in c.preferred_activity):
        return tuple(f"{a.series}: {number(a.net_share_change, 0, signed=True)} net shares · {number(a.issuance_price_assumption, 0, prefix='$')} assumed"
                     for a in c.preferred_activity if a.capital_method == "share_change_par")
    if c.preferred_activity_notes:
        return c.preferred_activity_notes
    if all(a.capital_method == "reported" for a in c.preferred_activity):
        return tuple(line
            for a in c.preferred_activity
            if a.issued_shares != 0 or a.repurchased_shares != 0
            for line in (
                f"{a.series}: {number(a.repurchased_shares, 0)} repurchased" if a.issued_shares == 0 else f"{a.series}: {number(a.issued_shares, 0)} issued · {number(a.repurchased_shares, 0)} repurchased",
                *_repurchase_price_details(a),
            )
        )
    details = []
    for a in c.preferred_activity:
        if a.series == "All other preferred series":
            details.append(f"Other preferred series: {money(preferred_activity_capital(a), signed=True)}")
            continue
        issued = number(a.issued_shares, 0)
        repurchased = number(a.repurchased_shares, 2, divisor=1e6, suffix="m")
        vwap = weekly_vwap(a.prior_week_trades) if a.prior_week_trades is not None else a.prior_week_vwap
        if a.issued_shares == 0 and a.repurchased_shares is not None and a.repurchased_shares > 0:
            details.append(f"{a.series}: {repurchased} repurchased · {number(vwap, prefix='$')} VWAP est.")
        elif a.issued_shares is not None and a.issued_shares > 0 and a.repurchased_shares == 0:
            details.append(f"{a.series}: {issued} issued · {number(a.issuance_price_assumption, 0, prefix='$')} assumed")
        else:
            # Preserve unusual or missing gross disclosures without guessing.
            return _preferred_details(c)
    return tuple(details)


def company_view(c: Company, m: CompanyMetrics, *, historical: bool = False,
                 prior_comparison_date: str | None = None) -> CompanyView:
    def available(value: float | None, formatted: str) -> str:
        return "Unavailable" if historical and value is None and formatted != "N/M" else formatted

    def valuation(value: float | None, formatted: str, *, claims_only: bool = False) -> str:
        display = available(value, formatted)
        estimated = c.preferred_claims_estimated if claims_only else c.valuation_estimated
        return f"≈{display}" if estimated and value is not None and isfinite(value) and display != "N/M" else display

    nav_change = m.constant_price_nav_change_pct
    amplification_comparison = f"vs {prior_comparison_date}" if prior_comparison_date else "vs last Monday"
    preferred_comparison = f"vs {prior_comparison_date}" if prior_comparison_date else "WoW"
    amp_delta = number(m.amplification_change, 2, suffix="×", signed=True)
    if ((m.net_nav is not None and m.net_nav <= 0) or
            (m.prior_net_nav is not None and m.prior_net_nav <= 0)):
        amp_delta = "N/M"
    preferred_label = "STRC + all preferred series" if c.ticker == "MSTR" else "SATA preferred capital"
    if m.preferred_capital_reported:
        preferred_label = "STRC + preferred capital"
        preferred_overline = "Net preferred capital · reported cash"
    elif any(a.capital_method == "share_change_par" for a in c.preferred_activity):
        preferred_label = "SATA capital" if c.ticker == "ASST" else "Preferred capital (est.)"
        preferred_overline = "Net preferred capital · estimated"
    elif c.preferred_activity_notes:
        preferred_overline = "Net preferred capital · cash flows not disclosed"
    else:
        preferred_overline = "Net preferred capital · estimated, before fees" if not m.preferred_fees_supplied else "Net preferred capital · estimated, less supplied fees"
    common_label = "Net common capital (est.)" if m.common_capital_estimated else "Net common capital"
    return CompanyView(
        name=c.name, ticker=c.ticker, logo=c.name.lower(),
        stock_price=number(c.stock_price, prefix="$"), quote_session=c.quote_session,
        quote_timestamp=c.quote_timestamp,
        nav_per_share=valuation(m.nav_per_share, number(m.nav_per_share, prefix="$")),
        price_to_nav=valuation(m.price_to_nav, ratio(m.price_to_nav, m.net_nav)),
        nav_note=c.valuation_note or "After debt & preferred claims · effective Class A + B shares",
        common=MetricView(common_label, available(m.net_common_capital, money(m.net_common_capital, signed=True)),
                          _common_details(c, m), post_details=_common_post_details(c, m)),
        preferred=MetricView(preferred_label, money(m.net_preferred_capital, signed=True),
                             _preferred_details(c), overline=preferred_overline, post_details=_preferred_post_details(c)),
        shares=MetricView("Total effective common shares",
                          number(m.effective_common_shares, 2, divisor=1e6, suffix="m"),
                          (c.share_basis_note,),
                          "Prior share count unverified" if historical and m.shares_change is None else f"{number(m.shares_change, 2, divisor=1e6, suffix='m', signed=True)} ({number(m.shares_change_pct, suffix='%', signed=True)}) WoW"),
        bitcoin=MetricView("Bitcoin per common share", number(m.sats_per_share, 0, suffix=" sats"),
                           (f"{number(m.btc_holdings, 0)} BTC held · {number(m.weekly_btc_purchases, 0)} bought",) if historical and m.btc_change == m.weekly_btc_purchases and m.weekly_btc_purchases is not None else
                           (f"{number(m.btc_holdings, 0)} BTC held · {number(m.btc_change, 0, signed=True)} net added",
                            f"Weekly BTC purchases: {number(m.weekly_btc_purchases, 0)}"),
                           "Weekly change unavailable" if historical and m.sats_change_pct is None else f"{number(m.sats_change_pct, suffix='%', signed=True)} per share WoW",
                           tone="positive" if m.sats_change_pct is not None and m.sats_change_pct > 0 else "negative" if m.sats_change_pct is not None and m.sats_change_pct < 0 else "neutral",
                           short_change=number(m.sats_change_pct, suffix='%', signed=True)),
        nav_change=MetricView("Reported-week NAV/share" if prior_comparison_date else "Weekly NAV/share change", valuation(nav_change, number(nav_change, suffix="%", signed=True)),
                              ("At constant market prices", "Historical debt / liquidation claims not verified") if historical and nav_change is None else ("At constant market prices", "Includes financing and other balance changes"),
                              tone="positive" if nav_change is not None and nav_change > 0 else "negative" if nav_change is not None and nav_change < 0 else "neutral",
                              post_details=("Historical debt / liquidation claims not verified",) if historical and nav_change is None else ("At constant market prices",) if historical else ("At constant prices · financing + other balance changes",)),
        amplification=MetricView("Net BTC amplification", valuation(m.net_btc_amplification, ratio(m.net_btc_amplification, m.net_nav)),
                                 (),
                                 "NAV inputs unverified" if historical and m.net_btc_amplification is None else f"{valuation(m.amplification_change, amp_delta)} {amplification_comparison}",
                                 short_change=valuation(m.amplification_change, amp_delta)),
        preferred_ratio=MetricView("Preferred / BTC", valuation(m.preferred_to_btc_pct, number(m.preferred_to_btc_pct, suffix="%"), claims_only=True),
                                   change="Claims unverified" if historical and m.preferred_to_btc_pct is None else f"{valuation(m.preferred_to_btc_change_pp, number(m.preferred_to_btc_change_pp, suffix=' pp', signed=True), claims_only=True)} {preferred_comparison}",
                                   short_change=valuation(m.preferred_to_btc_change_pp, number(m.preferred_to_btc_change_pp, suffix=' pp', signed=True), claims_only=True)),
        bought=MetricView("Bitcoin Bought", number(m.weekly_btc_purchases, 0, suffix=" BTC")),
        total_bitcoin=MetricView("Total BTC held", number(m.btc_holdings, 0, suffix=" BTC")),
    )


def build_report_view(report: Report, *, prices: dict | None = None) -> ReportView:
    if not report.illustrative and not (report.data_label and report.footer):
        raise ValueError("Historical reports require a data label and source footer.")
    metadata = {}
    for field, value in (("label", report.data_label), ("footer", report.footer), ("subtitle", report.subtitle)):
        if value is not None:
            metadata[field] = value
    if report.edition_id == "current-prices" and not report.illustrative:
        metadata["label"] = ""
        metadata["footer"] = "Dated balances at the displayed market prices · ≈ estimates. Calculation overview on Streamlit."
    from .period_growth import get_period_growth
    period_growth = get_period_growth(report, prices) if report.edition_id in ("current-prices", "2026-08-31") and not report.illustrative else {}

    def tone(value):
        return "positive" if value is not None and value > 0 else "negative" if value is not None and value < 0 else "neutral"

    companies = []
    for c in report.companies:
        company = company_view(c, calculate_company(c, report.current_btc_price, report.prior_btc_price),
                               historical=not report.illustrative, prior_comparison_date=report.prior_comparison_date)
        periods = []
        for label, growth in period_growth.get(c.ticker, {}).items():
            btc = number(growth.btc_per_share_growth_pct, suffix="%", signed=True)
            nav = "N/M" if growth.nav_not_meaningful else number(growth.nav_per_share_growth_pct, suffix="%", signed=True)
            if growth.btc_per_share_growth_pct is not None:
                btc = "≈" + btc
            if growth.nav_per_share_growth_pct is not None:
                nav = "≈" + nav
            periods.append(PeriodGrowthView(label, btc, nav, tone(growth.btc_per_share_growth_pct), tone(growth.nav_per_share_growth_pct)))
        companies.append(replace(company, periods=tuple(periods)))
    return ReportView(
        title=report.title.replace("The Monday Capital Report", "The Digital Credit Report"),
        report_time=report.report_time,
        capital_period_label=report.capital_period_label,
        btc_price=number(report.current_btc_price, 0, prefix="$"),
        btc_timestamp=report.btc_quote_timestamp,
        companies=tuple(companies),
        comparison_note=f"Market-ratio changes vs {report.prior_comparison_date}" if report.prior_comparison_date else "",
        **metadata,
    )
