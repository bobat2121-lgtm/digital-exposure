"""Build financial panels from the public filing feed and dated NAV supplements.

Facts never become zero merely because a parser omitted them. Supplements are
date-specific: a new filing cannot reuse an old denominator or preferred claim.
The committed feed is a last verified checkpoint, not a replacement for polling.
"""
from dataclasses import dataclass, replace
from datetime import date, timedelta
import hashlib
import json
from math import isfinite, isclose
from pathlib import Path
import re
from urllib.parse import urlsplit

from .current_report import current_report
from .models import CommonCapital, Company, PreferredActivity, Report, Snapshot
from .vwap_store import load_estimate

DATA = Path(__file__).resolve().parents[1] / "data"
CHECKPOINT = DATA / "latest-report-filings.json"
SUPPLEMENTS = DATA / "report-supplements.json"
CIKS = {"MSTR": "1050446", "ASST": "1920406"}
# Series in Strategy's repurchase table. STRE (euro) trades under the ATM only.
REPURCHASE_SERIES = ("STRC", "STRF", "STRK", "STRD")
PREFERRED_SERIES = REPURCHASE_SERIES + ("STRE",)
ACTIVITY_FIELDS = ("issuedShares", "netIssuanceProceedsUsd", "repurchasedShares", "repurchaseCashUsd")


def _preferred_rows(securities):
    """Per-series activity; STRE appears only when the filing lists it.

    STRE is absent from Strategy's repurchase program table, so once that table
    was parsed for every covered series, STRE's repurchases are zero by scope,
    not by omission. Missing STRE issuance fields still leave the row invalid.
    """
    rows = {series: dict(securities.get(series, {})) for series in REPURCHASE_SERIES}
    if "STRE" in securities:
        stre = dict(securities["STRE"])
        covered = all(_number(rows[series].get(key)) is not None
                      for series in REPURCHASE_SERIES for key in ("repurchasedShares", "repurchaseCashUsd"))
        if covered and "repurchasedShares" not in stre and "repurchaseCashUsd" not in stre:
            stre.update(repurchasedShares=0, repurchaseCashUsd=0)
        rows["STRE"] = stre
    return rows


@dataclass(frozen=True)
class LiveReportResult:
    report: Report
    notice: str | None
    version: str


def _number(value, *, signed=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not isfinite(value) or (value < 0 and not signed):
            return None
    except OverflowError:
        return None
    return value


def _day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _short(value):
    parsed = _day(value)
    return f"{parsed:%b} {parsed.day}" if parsed else "date unavailable"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _eligible(filing):
    if not isinstance(filing, dict) or filing.get("ticker") not in CIKS or filing.get("form") != "8-K":
        return False
    if not isinstance(filing.get("primaryDocumentUrl"), str):
        return False
    try:
        url = urlsplit(filing["primaryDocumentUrl"])
    except ValueError:
        return False
    accession = filing.get("accession", "")
    if not isinstance(accession, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        return False
    if (url.scheme != "https" or url.netloc != "www.sec.gov" or url.query or url.fragment
            or not url.path.startswith(f"/Archives/edgar/data/{CIKS[filing['ticker']]}/{accession.replace('-', '')}/")):
        return False
    documents = filing.get("documents")
    if (not isinstance(documents, list) or len(documents) != 1 or not isinstance(documents[0], dict)
            or documents[0].get("url") != filing["primaryDocumentUrl"]
            or not isinstance(documents[0].get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", documents[0]["sha256"])
            or not filing.get("documentFetchedAt")
            or documents[0].get("fetchedAt") != filing["documentFetchedAt"]):
        return False
    extraction = filing.get("extracted")
    if not isinstance(extraction, dict) or not isinstance(extraction.get("facts"), dict):
        return False
    if not isinstance(extraction.get("priorFacts", {}), dict) or not isinstance(extraction.get("securities", {}), dict):
        return False
    if any(not isinstance(row, dict) for row in extraction.get("securities", {}).values()):
        return False
    if (extraction.get("issues") or extraction.get("missing")
            or extraction.get("extractionValidated") is not True or filing.get("status") != "ready_for_review"):
        return False
    start, end, balance = (_day(extraction.get(key)) for key in ("periodStart", "periodEnd", "balanceDate"))
    if not start or not end or not balance or not start <= balance <= end or not 3 <= (end - start).days <= 10:
        return False
    facts = extraction["facts"]
    for key, value in facts.items():
        if _number(value, signed=key.startswith("net_")) is None:
            return False
    for key, value in extraction.get("priorFacts", {}).items():
        if _number(value, signed=key.startswith("net_")) is None:
            return False
    if filing["ticker"] == "MSTR":
        required = ("btc_holdings", "common_issued_shares", "common_issuance_proceeds_usd",
                    "common_repurchased_shares", "common_repurchases_cash_usd")
        if any(_number(facts.get(key)) is None for key in required):
            return False
        securities = extraction.get("securities", {})
        if set(securities) - {"MSTR", *PREFERRED_SERIES}:
            return False
        for row in _preferred_rows(securities).values():
            if any(_number(row.get(key)) is None for key in ACTIVITY_FIELDS):
                return False
    else:
        if any(_number(facts.get(key)) is None for key in
               ("btc_holdings", "effective_common_shares", "common_shares_class_a", "common_shares_class_b", "sata_shares")):
            return False
        if facts["effective_common_shares"] != facts["common_shares_class_a"] + facts["common_shares_class_b"]:
            return False
    return any(_number(facts.get(key)) is not None for key in
               ("weekly_btc_purchases", "weekly_btc_sales", "btc_holdings"))


def load_supplements(rows=None):
    """Reviewed supplements, plus auto-reconciled entries for newer filings.

    Auto entries exist only where no reviewed entry does (see
    report.auto_reconcile). ``rows`` are the eligible merged filings.
    """
    supplements = _load(SUPPLEMENTS)
    if rows is None:
        return supplements
    from . import auto_reconcile
    if not auto_reconcile.enabled(SUPPLEMENTS):
        return supplements
    try:
        merged, _ = auto_reconcile.augment(rows, supplements)
        return merged
    except Exception:  # never let automation block the reviewed report
        return supplements


def _vwap(filing):
    """Archived Strive VWAP estimate, else an automatic one for that week."""
    filed = date.fromisoformat(filing["filedDate"])
    estimate = load_estimate("ASST", filed)
    from . import auto_reconcile
    if estimate is None and auto_reconcile.enabled(SUPPLEMENTS):
        try:
            estimate = dict(auto_reconcile.vwap_estimate(filed))
            estimate["display_note"] = ("5-minute" if estimate.get("method") == "hlc3_5m" else "1-minute") + " VWAP estimate · automatic"
        except Exception:
            estimate = None
    return estimate


def _merged_filings(feed, checkpoint):
    rows = {row["accession"]: row for row in checkpoint.get("filings", []) if _eligible(row)}
    for row in feed.get("filings", []):
        if _eligible(row):
            prior = rows.get(row["accession"])
            if prior and prior.get("documents") and row.get("documents"):
                if prior["documents"][0].get("sha256") != row["documents"][0].get("sha256"):
                    raise ValueError("A verified filing document changed; reconciliation is required")
            rows[row["accession"]] = row
    return list(rows.values())


def _snapshot(ticker, balance_date, facts, supplements, prices):
    extra = supplements.get("balances", {}).get(ticker, {}).get(balance_date, {})
    def fact(key, supplement_key=None):
        value = _number(facts.get(key))
        other = _number(extra.get(supplement_key or key))
        if value is not None and other is not None and not isclose(value, other, rel_tol=1e-10, abs_tol=1e-5):
            raise ValueError(f"{ticker} {balance_date} filing and supplement disagree: {key}")
        return value if value is not None else other
    holdings = fact("btc_holdings")
    shares = fact("effective_common_shares")
    if shares is not None and shares <= 0:
        shares = None
    debt = fact("debt_principal")
    usd_claims = _number(extra.get("preferred_claims_usd"))
    eur_claims = _number(extra.get("preferred_claims_eur"))
    claims = (usd_claims + eur_claims * prices["quotes"]["EURUSD=X"]["price"]
              if usd_claims is not None and eur_claims is not None else None)
    if ticker == "MSTR":
        reserve, cash = fact("usd_reserve_usd"), fact("usd_cash_usd")
        liquid = reserve + cash if reserve is not None and cash is not None else _number(extra.get("combined_liquid_assets"))
        return Snapshot(holdings, shares, None, None, debt, claims, combined_liquid_assets=liquid)
    held_shares = fact("held_strc_shares")
    securities = held_shares * prices["quotes"]["STRC"]["price"] if held_shares is not None else None
    return Snapshot(holdings, shares, fact("cash_and_equivalents_usd"), securities, debt, claims)


def _complete(snapshot):
    from .calculations import liquid_assets
    return (all(_number(value) is not None for value in (
                snapshot.btc_holdings, snapshot.effective_common_shares,
                snapshot.debt_principal, snapshot.preferred_claims, liquid_assets(snapshot)))
            and snapshot.effective_common_shares > 0)


def _rolling_baselines(ticker, balance, all_filings, supplements, prices):
    """Quarter/year-start baselines from the last reconciled weekly balance.

    Each period starts from the latest complete balance dated on or before the
    prior quarter (or year) end, at most ten days earlier, so the first week of
    a new quarter shows only that week's change. Balances are repriced at the
    current marks exactly like the prior-week comparison. Exact dated records
    in data/period-baselines.json and the reviewed providers take precedence.
    """
    from .dated_baselines import baseline_dates
    result = []
    for period, end in baseline_dates(date.fromisoformat(balance)).items():
        end_day = date.fromisoformat(end)
        candidates = {}
        for row in sorted(all_filings, key=lambda item: item.get("acceptedAt", "")):
            if row["ticker"] != ticker:
                continue
            extraction = row["extracted"]
            for day, facts, own in ((extraction.get("priorBalanceDate"), extraction.get("priorFacts") or {}, False),
                                    (extraction["balanceDate"], extraction["facts"], True)):
                parsed = _day(day)
                if parsed and end_day - timedelta(days=10) <= parsed <= end_day and facts:
                    # A filing's own balance supersedes another filing's comparative.
                    if own or day not in candidates or not candidates[day][1]:
                        candidates[day] = (facts, own)
        for day in sorted(candidates, reverse=True):
            snapshot = _snapshot(ticker, day, candidates[day][0], supplements, prices)
            if _complete(snapshot):
                result.append((period, end, day, snapshot))
                break
    return tuple(result)


def _company(ticker, filing, all_filings, supplements, prices):
    extraction = filing["extracted"]
    facts = extraction["facts"]
    balance = extraction["balanceDate"]
    previous = sorted((row for row in all_filings if row["ticker"] == ticker
                       and row["extracted"]["balanceDate"] < balance),
                      key=lambda row: row["extracted"]["balanceDate"], reverse=True)
    previous = previous[0] if previous else None
    prior_date = extraction.get("priorBalanceDate")
    if prior_date:
        matched = next((row for row in sorted(all_filings, key=lambda row: row.get("acceptedAt", ""), reverse=True)
                        if row["ticker"] == ticker and row["extracted"]["balanceDate"] == prior_date), None)
        prior_facts = extraction.get("priorFacts") or (matched["extracted"]["facts"] if matched else {})
    elif extraction.get("priorFacts"):
        # Undated comparative facts cannot be assigned another filing's date.
        prior_facts = {}
    else:
        prior_date = previous["extracted"]["balanceDate"] if previous else None
        prior_facts = previous["extracted"]["facts"] if previous else {}
    start = date.fromisoformat(extraction["periodStart"])
    if not prior_date or not start - timedelta(days=4) <= date.fromisoformat(prior_date) < start:
        prior_date, prior_facts = None, {}
    current = _snapshot(ticker, balance, facts, supplements, prices)
    prior_marked = _snapshot(ticker, prior_date, prior_facts, supplements, prices)
    prior_prices = {**prices, "quotes": {symbol: dict(quote) for symbol, quote in prices["quotes"].items()}}
    for symbol, value in supplements.get("balance_marks", {}).get(prior_date, {}).items():
        if symbol in prior_prices["quotes"] and _number(value) is not None:
            prior_prices["quotes"][symbol]["price"] = value
    prior = _snapshot(ticker, prior_date, prior_facts, supplements, prior_prices)
    dated_marks = supplements.get("balance_marks", {}).get(prior_date, {})
    prior_extra = supplements.get("balances", {}).get(ticker, {}).get(prior_date, {})
    if ticker == "MSTR" and prior_extra.get("preferred_claims_eur", 0) > 0 and "EURUSD=X" not in dated_marks:
        prior = replace(prior, preferred_claims=None)
    if ticker == "ASST" and prior_facts.get("held_strc_shares", 0) > 0 and "STRC" not in dated_marks:
        prior = replace(prior, marketable_securities=None)
    # A BTC bridge is checked only when both gross directions were disclosed.
    bought, sold = (_number(facts.get(key)) for key in ("weekly_btc_purchases", "weekly_btc_sales"))
    if all(value is not None for value in (bought, sold, current.btc_holdings, prior.btc_holdings)):
        if not isclose(current.btc_holdings, prior.btc_holdings + bought - sold, abs_tol=1.0):
            raise ValueError(f"{ticker} BTC balances do not reconcile with its disclosed trades")
    if ticker == "MSTR":
        common = CommonCapital(
            _number(facts.get("common_issuance_proceeds_usd")), _number(facts.get("common_repurchases_cash_usd")),
            issued_shares=_number(facts.get("common_issued_shares")),
            repurchased_shares=_number(facts.get("common_repurchased_shares")),
            proceeds_basis="Reported ATM proceeds · net of commissions")
        activity = []
        for series, row in _preferred_rows(extraction.get("securities", {})).items():
            activity.append(PreferredActivity(series, _number(row.get("issuedShares")),
                _number(row.get("repurchasedShares")), issuance_price_assumption=None,
                capital_method="reported", reported_issuance_proceeds=_number(row.get("netIssuanceProceedsUsd")),
                reported_repurchases_cash=_number(row.get("repurchaseCashUsd"))))
        # Keep a compact second line while retaining every series' cash in the sum.
        other = activity[1:]
        def total(field):
            values = [getattr(row, field) for row in other]
            return sum(values) if all(value is not None for value in values) else None
        activity = (activity[0], PreferredActivity(" / ".join(row.series for row in other), total("issued_shares"),
            total("repurchased_shares"), issuance_price_assumption=None, capital_method="reported",
            reported_issuance_proceeds=total("reported_issuance_proceeds"),
            reported_repurchases_cash=total("reported_repurchases_cash")))
        estimate = None
        method = "reported_atm"
    else:
        common = CommonCapital(None, None)
        change = _number(facts.get("net_sata_shares_change"), signed=True)
        current_sata, prior_sata = _number(facts.get("sata_shares")), _number(prior_facts.get("sata_shares"))
        if change is not None and current_sata is not None and prior_sata is not None:
            if change != current_sata - prior_sata:
                raise ValueError("SATA net shares do not reconcile")
        activity = (PreferredActivity("SATA", None, None, issuance_price_assumption=100,
                                     capital_method="share_change_par", net_share_change=change),)
        estimate = _vwap(filing)
        if estimate and (estimate["session_start"] < extraction["periodStart"]
                         or estimate["session_end"] > extraction["periodEnd"]):
            raise ValueError("ASST VWAP does not match the filing's activity period")
        method = "share_change_vwap"
    quote = prices["quotes"][ticker]
    from .current_report import quote_time
    return Company(
        name="Strategy" if ticker == "MSTR" else "Strive", ticker=ticker,
        stock_price=quote["price"], quote_session="LAST PRICE", quote_timestamp=quote_time(quote["as_of"]),
        current=current, prior=prior, common_capital=common, preferred_activity=tuple(activity),
        prior_securities_at_current_prices=prior_marked.marketable_securities,
        prior_liquid_assets_at_current_prices=prior_marked.combined_liquid_assets,
        prior_preferred_claims_at_current_prices=prior_marked.preferred_claims,
        weekly_btc_purchases=bought, weekly_btc_sales=sold,
        common_capital_method=method, prior_week_equity_vwap=estimate["value"] if estimate else None,
        equity_vwap_note=estimate.get("display_note", "1-minute VWAP estimate · before fees") if estimate else None,
        share_basis_note="A + B · rounded to 1,000" if ticker == "MSTR" else "Class A + Class B · effective shares",
        preferred_activity_notes=("Net share change × $100 · before fees",) if ticker == "ASST" else (),
        valuation_estimated=True, preferred_claims_estimated=True,
        valuation_note="≈ Basic common shares · after debt & preferred claims",
        balance_date=balance, prior_balance_date=prior_date,
        period_baselines=_rolling_baselines(ticker, balance, all_filings, supplements, prices)), prior_date


def resolve_live_report(prices: dict, feed: dict, *, through_date: str | None = None) -> LiveReportResult:
    """Read-only projection: new reported inputs advance; missing NAV inputs stay missing."""
    if not isinstance(feed, dict) or feed.get("schemaVersion") != 1 or not isinstance(feed.get("filings"), list):
        raise ValueError("Unsupported filing feed")
    checkpoint = _load(CHECKPOINT)
    rows = _merged_filings(feed, checkpoint)
    supplements = load_supplements(rows)
    if through_date is not None:
        cutoff = date.fromisoformat(through_date)
        rows = [row for row in rows if date.fromisoformat(row["extracted"]["balanceDate"]) <= cutoff]
    groups = {}
    for row in sorted(rows, key=lambda item: item.get("acceptedAt", "")):
        period_start = date.fromisoformat(row["extracted"]["periodStart"])
        # The week after a Monday holiday can begin Tue for Strategy and Mon
        # for Strive; both still belong to the same activity week.
        week = (period_start - timedelta(days=period_start.weekday())).isoformat()
        groups.setdefault(week, {})[row["ticker"]] = row
    paired = sorted((period for period, filings in groups.items() if set(filings) == set(CIKS)), reverse=True)
    if not paired or paired[0] <= "2026-08-24":
        report = current_report(prices)
        return LiveReportResult(report, "Awaiting a newer reconciled filing pair · " + report.subtitle, "2026-08-31")
    start = paired[0]
    chosen = groups[start]
    built = [_company(ticker, chosen[ticker], rows, supplements, prices) for ticker in CIKS]
    companies = tuple(item[0] for item in built)
    base = current_report(prices)
    end = max(row["extracted"]["periodEnd"] for row in chosen.values())
    dates = " · ".join(f"{company.name} {_short(chosen[company.ticker]['extracted']['balanceDate'])}" for company in companies)
    previous_date = max((item[1] for item in built if item[1]), default=None)
    previous_price = supplements.get("comparison_btc_prices", {}).get(previous_date)
    report = replace(base, edition_id="live-prices", companies=companies,
        subtitle="Balance dates: " + dates,
        capital_period_label=f"Market Activity · {_short(start)}–{_short(end)}",
        prior_comparison_date=_short(supplements.get("comparison_release_dates", {}).get(previous_date, previous_date)),
        prior_btc_price=_number(previous_price),
        valuation_marks=tuple((symbol, prices["quotes"][symbol]["price"]) for symbol in ("BTC-USD", "STRC", "EURUSD=X")),
        data_label="REPORTED FILINGS · DATED NAV ESTIMATES")
    missing = [c.name for c in companies if any(value is None for value in
        (c.current.btc_holdings, c.current.effective_common_shares, c.current.debt_principal, c.current.preferred_claims))
        or (c.current.combined_liquid_assets is None and (c.current.cash is None or c.current.marketable_securities is None))]
    notice = ("New filings loaded · " + ", ".join(missing) + " NAV inputs pending; unavailable figures are not carried forward.") if missing else None
    automatic = [f"{c.name} {_short(c.balance_date)}" for c in companies
                 if supplements.get("balances", {}).get(c.ticker, {}).get(c.balance_date, {}).get("auto_reconciled")]
    if automatic and not missing:
        notice = "Automatically reconciled from the filings and public data · " + " · ".join(automatic) + " · review pending."
    if max(groups, default=start) > start:
        notice = "One newer filing received · awaiting its matching weekly report. " + report.subtitle
    newest_release = max(row["filedDate"] for row in chosen.values())
    pending = [row for row in feed["filings"] if isinstance(row, dict) and row.get("ticker") in CIKS
               and isinstance(row.get("filedDate"), str) and row["filedDate"] >= newest_release
               and (row.get("form") == "8-K/A" or row.get("status") in ("pending", "partial", "document_error")
                    or (row.get("status") == "ready_for_review" and not _eligible(row)))]
    if pending:
        notice = "New filing data awaits validation · showing the last verified filing pair. " + report.subtitle
    version_data = [(row["accession"], row.get("documents"), row["extracted"]) for row in chosen.values()]
    automatic_inputs = {ticker: supplements.get("balances", {}).get(ticker, {}).get(chosen[ticker]["extracted"]["balanceDate"])
                        for ticker in chosen}
    version = hashlib.sha256(json.dumps([version_data, supplements.get("revision"), automatic_inputs],
                                        sort_keys=True, default=str).encode()).hexdigest()[:16]
    return LiveReportResult(report, notice, version)


def _complete_panel_inputs(report, prices):
    """Require actual inputs, including comparisons; zero and negative NAV are valid.

    Do not require a BTC sale when only purchases were disclosed, or a positive
    NAV ratio when the denominator is nonpositive (the view correctly uses N/M).
    """
    from .calculations import calculate_company, liquid_assets
    from .period_growth import get_period_growth

    if _number(report.prior_btc_price) is None:
        return False
    for company in report.companies:
        for snapshot in (company.current, company.prior):
            if any(_number(value) is None for value in (
                    snapshot.btc_holdings, snapshot.effective_common_shares,
                    snapshot.debt_principal, snapshot.preferred_claims, liquid_assets(snapshot))):
                return False
            if snapshot.effective_common_shares <= 0:
                return False
        metric = calculate_company(company, report.current_btc_price, report.prior_btc_price)
        if metric.net_common_capital is None or metric.net_preferred_capital is None:
            return False
        if metric.common_capital_estimated and metric.common_equity_vwap is None:
            return False
        if company.weekly_btc_purchases is None and company.weekly_btc_sales is None:
            return False
    growth = get_period_growth(report, prices)
    return all(period.btc_per_share_growth_pct is not None
               and (period.nav_per_share_growth_pct is not None or period.nav_not_meaningful)
               for periods in growth.values() for period in periods.values())


def resolve_complete_report(prices: dict, feed: dict) -> LiveReportResult:
    """Publish a complete Monday edition; keep later incomplete filings in the feed.

    Resolve older pairs from their own dated inputs, including on a fresh
    session. Never fill the new edition with old claims, shares, or prices.
    """
    newest = resolve_live_report(prices, feed)
    if _complete_panel_inputs(newest.report, prices):
        return newest
    latest_date = max(c.balance_date or "" for c in newest.report.companies)
    rows = _merged_filings(feed, _load(CHECKPOINT))
    cutoffs = sorted({row["extracted"]["balanceDate"] for row in rows
                      if row["extracted"]["balanceDate"] < latest_date}, reverse=True)
    for cutoff in cutoffs:
        candidate = resolve_live_report(prices, feed, through_date=cutoff)
        if _complete_panel_inputs(candidate.report, prices):
            return replace(candidate, notice=(
                "New filing inputs are being reconciled · showing the last complete report. "
                + candidate.report.subtitle))
    raise ValueError("No complete dated Monday report is available")
