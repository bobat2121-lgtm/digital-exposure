"""Read public SEC filing observations without credentials or write requests."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "sec-monitor.json"
MAX_BYTES = 2_000_000


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
        rows.append({
            "Company": filing.get("ticker", ""), "Form": filing.get("form", ""),
            "Accession": filing.get("accession", ""),
            "SEC accepted": filing.get("acceptedAt", ""),
            "First observed": filing.get("firstSeenAt", ""),
            "Document received": filing.get("documentFetchedAt") or "Pending",
            "State": "Initial baseline" if filing.get("baseline") else filing.get("status", ""),
            "Filing": url, "Balance date": extracted.get("balanceDate") or "Not extracted",
        })
    return rows


def render_monitor() -> None:
    """A Streamlit fragment polls the cached feed every 15s in active sessions."""
    import streamlit as st

    @st.cache_data(ttl=15, show_spinner=False)
    def cached_feed(origin):
        return read_monitor(origin)

    @st.fragment(run_every="15s")
    def monitor_fragment():
        try:
            origin = monitor_url()
            if not origin:
                st.caption("The SEC monitor is not connected in this environment.")
                return
            status, feed = cached_feed(origin)
            st.session_state["last_sec_monitor"] = (status, feed)
        except (OSError, ValueError, TypeError, KeyError):
            st.warning("Latest filings are temporarily unavailable. Verified report balances are retained.")
            previous = st.session_state.get("last_sec_monitor")
            if not previous:
                return
            status, feed = previous
            st.caption("Last successfully retrieved feed; it may be stale.")
        st.caption("SEC checks: Mondays, 6:45–9:30 a.m. ET. Discord alerts run independently of this page.")
        st.caption("Polling window active." if status.get("schedule", {}).get("active") else "Outside the Monday polling window; saved observations are shown.")
        st.caption("Filings appear after ingestion. Report balances advance after reconciliation.")
        rows = filing_rows(feed)
        if rows:
            st.dataframe(rows[:20], hide_index=True, column_config={"Filing": st.column_config.LinkColumn("SEC filing")})
        else:
            st.caption("No filing observations recorded yet.")

    monitor_fragment()
