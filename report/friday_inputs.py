"""Project the shared Monday financial model into Friday's input schema.

This module performs no network requests and uses no Streamlit APIs. The
caller supplies the same price/feed snapshot used for the Monday publication.
The accepted filing pair and date-specific supplements come from the shared
resolver; Friday never fills missing values from its older balance fixtures.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json

from . import live_report


PUBLICATION_BASIS = "latest_monday_disclosures"
NUMERIC_FIELDS = ("btc_held", "cash_usd", "securities_usd", "debt_usd", "preferred_usd", "shares")


def _accepted_at(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.astimezone(timezone.utc).isoformat() if stamp.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _selected_publications(feed, report):
    """Attach provenance from the exact newest reconciled activity week.

    The financial result remains authoritative. Reusing the resolver's merge
    validator prevents an incomplete new record from supplying provenance for
    a still-published older pair. A balance mismatch has no inferred timestamp.
    """
    rows = live_report._merged_filings(feed, live_report._load(live_report.CHECKPOINT))
    groups = {}
    for row in sorted(rows, key=lambda item: item.get("acceptedAt", "")):
        start = date.fromisoformat(row["extracted"]["periodStart"])
        week = (start - timedelta(days=start.weekday())).isoformat()
        groups.setdefault(week, {})[row["ticker"]] = row
    paired = sorted((week for week, members in groups.items() if set(members) == set(live_report.CIKS)), reverse=True)
    if not paired or paired[0] <= "2026-08-24":
        return {}
    chosen = groups[paired[0]]
    result = {}
    for company in report.companies:
        row = chosen.get(company.ticker)
        if row is None or row["extracted"]["balanceDate"] != company.balance_date:
            continue
        result[company.ticker] = {
            "accession": row["accession"], "accepted_at": _accepted_at(row.get("acceptedAt")),
            "filed_date": row.get("filedDate"), "balance_date": company.balance_date,
            "source_url": row["primaryDocumentUrl"], "documents": deepcopy(row.get("documents", [])),
        }
    return result


def resolve_friday_inputs(prices: dict, feed: dict, *, now=None) -> dict:
    """Return Monday's accepted financial inputs, including post-Friday releases.

    ``version`` is the shared resolver's filing/supplement version.
    ``input_version`` additionally covers the exact projected values and price
    snapshot, because STRC market value and EUR preferred claims can reprice
    without a new filing. The per-company opt-in marker is deliberately
    explicit: Friday still validates amounts and disclosure timestamps.

    A newer incomplete filing pair retains the same last verified pair as
    Monday, with the shared notice. A newly accepted pair with missing NAV
    fields retains those None values. An undated legacy-only fallback is not
    promoted into a published Friday company balance.
    """
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Publication observation time must include a timezone")
    now = now.astimezone(timezone.utc)
    resolved = live_report.resolve_live_report(prices, feed)
    publications = _selected_publications(feed, resolved.report)
    supplements = live_report._load(live_report.SUPPLEMENTS)
    companies = {}
    notices = [resolved.notice] if resolved.notice else []
    for company in resolved.report.companies:
        current = company.current
        publication = publications.get(company.ticker, {})
        combined = current.combined_liquid_assets
        values = {
            "btc_held": current.btc_holdings,
            "cash_usd": combined if combined is not None else current.cash,
            # Zero is structural here: the combined reserve already includes
            # its securities. Unknown separate securities remain unknown.
            "securities_usd": 0 if combined is not None else current.marketable_securities,
            "debt_usd": current.debt_principal, "preferred_usd": current.preferred_claims,
            "shares": current.effective_common_shares,
        }
        published = bool(publication.get("accepted_at") and company.balance_date
                         and datetime.fromisoformat(publication["accepted_at"]) <= now)
        if not published:
            values = {field: None for field in NUMERIC_FIELDS}
            notices.append(f"{company.ticker}: shared Monday publication has no validated dated filing available at observation time; Friday financial inputs are unavailable.")
        extra = supplements.get("balances", {}).get(company.ticker, {}).get(company.balance_date, {})
        sources = [publication.get("source_url"), *extra.get("sources", [])]
        marks = ("EURUSD=X",) if company.ticker == "MSTR" else ("STRC",)
        sources.extend(prices.get("quotes", {}).get(symbol, {}).get("source_url") for symbol in marks)
        notes = [
            "Same accepted filing pair and dated valuation inputs as the Monday report; later Monday disclosures may update the Friday panel.",
            "The same disclosed quantities and current included asset/claim marks are used for both weekly BTC price marks.",
        ]
        if combined is not None:
            notes.append("USD Reserve plus USD Cash are included once as combined liquid assets; no additional reserve securities are added.")
        if extra.get("limitations"):
            notes.append(extra["limitations"])
        companies[company.ticker] = {
            **values,
            "baseline_at": company.balance_date,
            "disclosed_at": publication.get("accepted_at"),
            "source": publication.get("source_url"),
            "sources": list(dict.fromkeys(source for source in sources if isinstance(source, str) and source)),
            "accession": publication.get("accession"),
            "share_basis": "basic", "estimated": company.valuation_estimated,
            "estimated_fields": ["preferred_usd"] if company.preferred_claims_estimated else [],
            "notes": notes,
            "allow_post_friday_disclosure": True, "publication_basis": PUBLICATION_BASIS,
            "publication_version": resolved.version,
            "provenance": {"resolver": "report.live_report.resolve_live_report",
                           "filing": deepcopy(publication), "supplement_revision": supplements.get("revision"),
                           "share_basis_note": company.share_basis_note},
        }
    result = {
        "companies": companies, "version": resolved.version,
        "notice": " ".join(dict.fromkeys(notices)) or None,
        "publications": publications,
        "balance_dates": {ticker: company["baseline_at"] for ticker, company in companies.items()},
        "publication_basis": PUBLICATION_BASIS, "report_edition": resolved.report.edition_id,
        "report_subtitle": resolved.report.subtitle, "market_as_of": prices.get("fetched_at"),
        "valuation_marks": dict(resolved.report.valuation_marks),
    }
    result["input_version"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()[:20]
    return result
