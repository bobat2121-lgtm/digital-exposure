"""Use the same validated financial edition as Monday, without UI calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from http.client import HTTPException
import json

from report.filing_monitor import monitor_url, read_shared_monitor
from report.friday_inputs import resolve_friday_inputs
from report.price_refresh import PriceStore


@lru_cache(maxsize=1)
def nav_price_store():
    return PriceStore()


def _retained(previous, message, checked_at):
    old = previous.get("financial_inputs") or {}
    return {
        "financial_inputs": {**deepcopy(old), "status": "retained" if old.get("companies") else "unavailable",
                             "notice": message, "checked_at": checked_at},
        "nav_prices": deepcopy(previous.get("nav_prices")),
    }


def would_regress(candidate, previous):
    prior_inputs = previous.get("financial_inputs") or {}
    old = prior_inputs.get("companies") or {}
    for ticker, baseline in old.items():
        prior_date = baseline.get("baseline_at")
        current = (candidate.get("companies") or {}).get(ticker, {})
        new_date = current.get("baseline_at")
        if prior_date and (not new_date or new_date < prior_date):
            return True
        prior_release, new_release = baseline.get('disclosed_at'), current.get('disclosed_at')
        if new_date == prior_date and prior_release and (not new_release or new_release < prior_release):
            return True
    prior_check, new_check = prior_inputs.get('checked_at'), candidate.get('checked_at')
    if (old and prior_check and new_check and new_check < prior_check
            and candidate.get('version') != prior_inputs.get('version')):
        return True
    if (old and candidate.get('status') in ('retained', 'checkpoint', 'unavailable')
            and candidate.get('version') != prior_inputs.get('version')):
        return True
    return False


def fetch_financial_inputs(previous=None, *, refresh_prices=True):
    """Fresh disclosures; retain NAV marks during a balance-only feed check.

    No individual missing value is filled from an older financial edition.
    A failed request retains a whole dated edition with a visible notice.
    """
    previous = previous or {}
    checked_at = datetime.now(timezone.utc).isoformat()
    prices = deepcopy(previous.get("nav_prices"))
    saved_marks = (previous.get("financial_inputs") or {}).get("using_saved_nav_prices", False)
    try:
        if refresh_prices:
            refreshed = nav_price_store().refresh()
            prices, saved_marks = refreshed.prices, refreshed.using_saved_prices
        if prices is None:
            raise ValueError("NAV valuation marks unavailable")
        origin = monitor_url()
        if not origin:
            raise ValueError("SEC monitor unavailable")
        try:
            _, feed = read_shared_monitor(origin, force=refresh_prices)
        except (OSError, ValueError, TypeError, KeyError, HTTPException):
            if (previous.get("financial_inputs") or {}).get("companies"):
                return _retained(previous, "Monday filing check unavailable · retaining the last validated balance inputs.", checked_at)
            # The same committed checkpoint used by Monday permits a first visit
            # during a feed outage. It is explicitly identified as a checkpoint.
            result = resolve_friday_inputs(prices, {"schemaVersion": 1, "filings": []})
            result.update(status="checkpoint", notice="Monday filing feed unavailable · showing the verified saved filing edition.")
        else:
            result = resolve_friday_inputs(prices, feed)
            result["status"] = "current"
        if would_regress(result, previous):
            return _retained(previous, "An older filing edition was received · retaining the newer validated balance inputs.", checked_at)
        result.update(checked_at=checked_at, using_saved_nav_prices=saved_marks)
        if saved_marks:
            result["notice"] = " ".join(filter(None, (result.get("notice"), "NAV valuation marks use the last complete saved quote snapshot.")))
        return {"financial_inputs": result, "nav_prices": deepcopy(prices)}
    except (OSError, ValueError, TypeError, KeyError, HTTPException):
        return _retained(previous, "Monday balance inputs could not be validated · retaining the last complete edition where available.", checked_at)


def financial_key(result):
    """Ignore successful check timestamps; only meaningful changes repaint UI."""
    payload = result.get("financial_inputs") or {}
    return json.dumps({key: value for key, value in payload.items() if key != "checked_at"},
                      sort_keys=True, allow_nan=False)


def apply_financial_data(data, result):
    inputs = result.get("financial_inputs") or {}
    sources = {key: value for key, value in data.get("sources", {}).items()
               if key not in ("MSTR balances", "ASST balances")}
    # Migrate historical caches without preserving retired financial captions.
    notices = [item for item in data.get("notices", []) if not item.startswith((
        "NAV uses BASIC Class A+B shares and the latest vetted disclosure published by the Friday cutoff.",
        "Strategy liquid assets include $6.71B"))]
    return {**data, **result, "companies": deepcopy(inputs.get("companies") or {}),
            "notices": notices,
            "sources": {**sources, "companies": "Same validated filing edition and dated NAV inputs as the Monday Digital Credit Report"}}


def fetch_snapshot(previous=None):
    """Market feeds and the Monday financial feed load independently in parallel."""
    from friday import data as providers
    with ThreadPoolExecutor(max_workers=2) as pool:
        market = pool.submit(providers.refresh_latest, previous) if previous else pool.submit(providers.load_latest)
        financial = pool.submit(fetch_financial_inputs, previous)
        return apply_financial_data(market.result(), financial.result())
