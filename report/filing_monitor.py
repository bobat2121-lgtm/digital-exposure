"""Read public SEC filing observations without credentials or write requests."""
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from http.client import HTTPException
import json
import os
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .calculations import bitcoin_activity_amount
from .presentation import btc_activity_value

CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "sec-monitor.json"
MAX_BYTES = 2_000_000
SHARED_MONITOR_TTL = 15
_SHARED_MONITOR_LIMIT = 4
_shared_monitor_lock = Lock()
_shared_monitor_cache: dict[str, tuple[float, tuple[dict, dict]]] = {}
_shared_monitor_inflight: dict[str, Future] = {}


def monitor_url() -> str | None:
    value = os.environ.get("SEC_MONITOR_URL", "").strip()
    if not value and CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("url", ""), str):
            raise ValueError("SEC monitor configuration must contain a URL string.")
        value = config.get("url", "").strip()
    if not value:
        return None
    return _validated_origin(value)


def _validated_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or
            not parsed.hostname.endswith(".workers.dev") or parsed.username or
            parsed.password or parsed.port or parsed.query or parsed.fragment or
            parsed.path not in ("", "/")):
        raise ValueError("SEC monitor must use its HTTPS workers.dev origin.")
    return value.rstrip("/")


def _get(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "DigitalCreditReport/1.0"})
    with urlopen(request, timeout=8) as response:
        if response.geturl() != url:
            raise ValueError("SEC monitor redirected unexpectedly.")
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("SEC monitor response exceeds the size limit.")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("SEC monitor returned an invalid response.")
    return payload


def read_monitor(origin: str) -> tuple[dict, dict]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        status_request = pool.submit(_get, origin + "/api/status")
        feed_request = pool.submit(_get, origin + "/api/filings")
        status, feed = status_request.result(), feed_request.result()
    if type(feed.get("schemaVersion")) is not int or feed["schemaVersion"] != 1 or not isinstance(feed.get("filings"), list):
        raise ValueError("SEC filing feed has an unsupported schema.")
    if (type(status.get("schemaVersion")) is not int or status["schemaVersion"] != 1 or
            not isinstance(status.get("issuers"), (list, dict))):
        raise ValueError("SEC monitor status has an unsupported schema.")
    return status, feed


def clear_shared_monitor_cache() -> None:
    """Clear completed cached reads; in-flight reads finish normally."""
    with _shared_monitor_lock:
        _shared_monitor_cache.clear()


def read_shared_monitor(origin: str, *, force: bool = False) -> tuple[dict, dict]:
    """Share one public SEC read across UI and background callers for 15 seconds.

    An in-flight refresh is joined even when the prior cache is still fresh.
    Each caller receives a deep copy. Failed refreshes propagate to all callers;
    only the report's session layer may choose to retain a dated old snapshot.
    This function has no Streamlit dependency or session-state access.
    """
    origin = _validated_origin(origin)
    started = monotonic()
    with _shared_monitor_lock:
        pending = _shared_monitor_inflight.get(origin)
        cached = _shared_monitor_cache.get(origin)
        if pending is not None:
            owner = False
        elif (cached is not None and monotonic() - cached[0] < SHARED_MONITOR_TTL
              and (not force or cached[0] > started)):
            return deepcopy(cached[1])
        else:
            pending = Future()
            _shared_monitor_inflight[origin] = pending
            owner = True
    if not owner:
        return deepcopy(pending.result())
    try:
        result = deepcopy(read_monitor(origin))
    except BaseException as error:
        # Wake every waiter on failure too; do not create a cached error or
        # silently substitute an expired successful feed.
        with _shared_monitor_lock:
            pending.set_exception(error)
            _shared_monitor_inflight.pop(origin, None)
        raise
    with _shared_monitor_lock:
        _shared_monitor_cache[origin] = (monotonic(), result)
        while len(_shared_monitor_cache) > _SHARED_MONITOR_LIMIT:
            oldest = min(_shared_monitor_cache, key=lambda key: _shared_monitor_cache[key][0])
            del _shared_monitor_cache[oldest]
        pending.set_result(result)
        _shared_monitor_inflight.pop(origin, None)
    return deepcopy(result)


def filing_rows(feed: dict) -> list[dict]:
    """Keep baseline observations distinct from newly detected filings."""
    rows = []
    for filing in feed.get("filings", []):
        if not isinstance(filing, dict):
            continue
        url = filing.get("primaryDocumentUrl", "")
        parsed = urlsplit(url) if isinstance(url, str) else None
        if (not parsed or parsed.scheme != "https" or parsed.hostname != "www.sec.gov" or
                parsed.netloc != "www.sec.gov" or parsed.query or parsed.fragment or
                not parsed.path.startswith("/Archives/edgar/data/")):
            continue
        extracted = filing.get("extracted") or {}
        if not isinstance(extracted, dict):
            extracted = {}
        facts = extracted.get("facts")
        if not isinstance(facts, dict):
            facts = {}
        activity = {}
        for label, field in (("Bitcoin Bought", "weekly_btc_purchases"), ("Bitcoin Sold", "weekly_btc_sales")):
            amount = bitcoin_activity_amount(facts.get(field))
            activity[label] = btc_activity_value(amount)
        rows.append({
            "Company": filing.get("ticker", ""), "Form": filing.get("form", ""),
            "Accession": filing.get("accession", ""),
            "SEC accepted": filing.get("acceptedAt", ""),
            "First observed": filing.get("firstSeenAt", ""),
            "Document received": filing.get("documentFetchedAt") or "Pending",
            "State": "Initial baseline" if filing.get("baseline") else filing.get("status", ""),
            "Filing": url, "Balance date": extracted.get("balanceDate") or "Not extracted",
            **activity,
        })
    return rows


@dataclass(frozen=True)
class MonitorSnapshot:
    status: dict | None
    feed: dict | None
    stale: bool = False
    notice: str | None = None


def load_monitor_snapshot(*, force: bool = False) -> MonitorSnapshot:
    """One cached public feed for the financial cards and their filing details."""
    import streamlit as st

    try:
        origin = monitor_url()
        if not origin:
            return MonitorSnapshot(None, None, stale=True, notice="SEC monitor is not connected.")
        status, feed = read_shared_monitor(origin, force=force)
        st.session_state["monday_last_sec_monitor"] = (status, feed)
        return MonitorSnapshot(status, feed)
    except (OSError, ValueError, TypeError, KeyError, HTTPException):
        previous = st.session_state.get("monday_last_sec_monitor")
        status, feed = previous if previous else (None, None)
        return MonitorSnapshot(status, feed, stale=True, notice="SEC refresh unavailable.")


def render_monitor(snapshot: MonitorSnapshot | None = None) -> None:
    """Render the same snapshot used by the cards; the app owns the refresh loop."""
    import streamlit as st

    snapshot = snapshot or load_monitor_snapshot()
    if snapshot.stale:
        st.caption(snapshot.notice or "SEC refresh unavailable.")
        if snapshot.feed is not None:
            st.caption("Last successfully retrieved feed; it may be stale.")
    if snapshot.status is None or snapshot.feed is None:
        return
    schedule = snapshot.status.get("schedule") or {}
    if not isinstance(schedule, dict):
        schedule = {}
    st.caption("SEC checks: Monday, 6:45–9:30 a.m. ET; Tuesday after an EDGAR Monday holiday. Discord runs independently.")
    st.caption("Polling window active." if schedule.get("active") else "Outside the weekly polling window; saved observations are shown.")
    rows = filing_rows(snapshot.feed)
    if rows:
        st.dataframe(rows[:20], hide_index=True, column_config={"Filing": st.column_config.LinkColumn("SEC filing")})
    else:
        st.caption("No filing observations recorded yet.")
