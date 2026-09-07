"""Display SEC filings and acknowledge delivery without changing report balances."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from math import isfinite
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo

CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "sec-monitor.json"
MAX_BYTES = 2_000_000
ACK_MAX_BYTES = 16_384
ACK_SESSION_KEY = "last_sec_monitor_acknowledgement"
EASTERN = ZoneInfo("America/New_York")


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


def _timestamp(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _finite_number(value) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False


def select_acknowledgement(feed: dict, now: datetime | None = None) -> list[dict[str, str]] | None:
    """Choose the newest same-Monday pair of retrieved weekly primary filings."""
    published = {(row["Company"], row["Accession"]) for row in filing_rows(feed)
                 if isinstance(row["Company"], str) and isinstance(row["Accession"], str)}
    now = now or datetime.now(timezone.utc)
    weeks: dict[str, dict[str, tuple[datetime, dict[str, str]]]] = {}
    for filing in feed.get("filings", []):
        if not isinstance(filing, dict):
            continue
        ticker, accession = filing.get("ticker"), filing.get("accession")
        if (ticker not in ("MSTR", "ASST") or not isinstance(accession, str) or
                not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or
                (ticker, accession) not in published or filing.get("baseline") is not False or
                filing.get("form") != "8-K" or filing.get("status") not in ("ready_for_review", "partial")):
            continue
        accepted = _timestamp(filing.get("acceptedAt"))
        received = _timestamp(filing.get("documentFetchedAt"))
        if (not accepted or not now - timedelta(days=14) <= accepted <= now or
                accepted.astimezone(EASTERN).weekday() != 0 or not received or not accepted <= received <= now):
            continue
        extracted = filing.get("extracted")
        facts = extracted.get("facts") if isinstance(extracted, dict) else None
        if not isinstance(facts, dict):
            continue
        holdings, purchased = facts.get("btc_holdings"), facts.get("weekly_btc_purchases")
        if not _finite_number(holdings) or holdings <= 0 or not _finite_number(purchased) or purchased < 0:
            continue
        documents = filing.get("documents")
        document = documents[0] if isinstance(documents, list) and documents else None
        digest = document.get("sha256") if isinstance(document, dict) else None
        document_received = _timestamp(document.get("fetchedAt")) if isinstance(document, dict) else None
        cik = {"MSTR": "1050446", "ASST": "1920406"}[ticker]
        if (not isinstance(document, dict) or document.get("url") != filing.get("primaryDocumentUrl") or
                not urlsplit(document.get("url", "")).path.startswith(f"/Archives/edgar/data/{cik}/{accession.replace('-', '')}/") or
                not document_received or document_received != received or
                not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            continue
        monday = accepted.astimezone(EASTERN).date().isoformat()
        week = weeks.setdefault(monday, {})
        if ticker not in week or accepted > week[ticker][0]:
            week[ticker] = (accepted, {"ticker": ticker, "accession": accession, "sha256": digest})
    for monday in sorted(weeks, reverse=True):
        if set(weeks[monday]) == {"MSTR", "ASST"}:
            return [weeks[monday][ticker][1] for ticker in ("MSTR", "ASST")]
    return None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # Never forward the server-only acknowledgement credential to a redirect.
        return None


def acknowledge_filings(origin: str, filings: list[dict[str, str]], token: str) -> str:
    """Acknowledge the rendered pair; errors deliberately contain no credentials."""
    try:
        origin = _validated_origin(origin)
        if not isinstance(token, str) or not 32 <= len(token) <= 1024 or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise ValueError("Invalid acknowledgement credential")
        if (not isinstance(filings, list) or len(filings) != 2 or
                any(not isinstance(filing, dict) or set(filing) != {"ticker", "accession", "sha256"} for filing in filings) or
                {filing["ticker"] for filing in filings} != {"MSTR", "ASST"} or
                any(not isinstance(filing["accession"], str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", filing["accession"]) or
                    not isinstance(filing["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", filing["sha256"]) for filing in filings)):
            raise ValueError("Invalid acknowledgement pair")
        url = origin + "/api/streamlit/ack"
        request = Request(url, data=json.dumps({"filings": filings}, separators=(",", ":")).encode("utf-8"),
                          headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                                   "Accept": "application/json", "User-Agent": "DigitalCreditReport/1.0"}, method="POST")
        with build_opener(_NoRedirect()).open(request, timeout=8) as response:
            if response.geturl() != url:
                raise ValueError("Unexpected acknowledgement redirect")
            data = response.read(ACK_MAX_BYTES + 1)
        if len(data) > ACK_MAX_BYTES:
            raise ValueError("Acknowledgement response too large")
        payload = json.loads(data)
        if not isinstance(payload, dict) or payload.get("outcome") not in ("queued", "sent", "duplicate"):
            raise ValueError("Acknowledgement was not accepted")
        return payload["outcome"]
    except (OSError, ValueError, TypeError, KeyError):
        raise ValueError("SEC filing acknowledgement could not be confirmed.") from None


def _ack_token() -> str | None:
    value = os.environ.get("STREAMLIT_ACK_TOKEN", "").strip()
    if not value:
        try:
            import streamlit as st
            value = st.secrets.get("STREAMLIT_ACK_TOKEN", "")
        except (OSError, KeyError):
            return None
    return value if isinstance(value, str) and value else None


def acknowledge_rendered_filings(origin: str, feed: dict, rows: list[dict], session_state, token: str | None) -> bool:
    """Keep successful acknowledgements in this session; failed attempts can retry."""
    if not token:
        return False
    pair = select_acknowledgement(feed)
    if not pair or not {(filing["ticker"], filing["accession"]) for filing in pair}.issubset(
            {(row.get("Company"), row.get("Accession")) for row in rows}):
        return False
    key = tuple((filing["ticker"], filing["accession"], filing["sha256"]) for filing in pair)
    if session_state.get(ACK_SESSION_KEY) == key:
        return True
    try:
        acknowledge_filings(origin, pair, token)
    except ValueError:
        return False
    session_state[ACK_SESSION_KEY] = key
    return True


def render_monitor() -> None:
    """A Streamlit fragment polls the cached feed every 15s in active sessions."""
    import streamlit as st

    @st.cache_data(ttl=15, show_spinner=False)
    def cached_feed(origin):
        return read_monitor(origin)

    @st.fragment(run_every="15s")
    def monitor_fragment():
        st.markdown("**Live SEC filing monitor**")
        feed_fresh = False
        try:
            origin = monitor_url()
            if not origin:
                st.caption("The SEC monitor is not connected in this environment.")
                return
            status, feed = cached_feed(origin)
            st.session_state["last_sec_monitor"] = (status, feed)
            feed_fresh = True
        except (OSError, ValueError, TypeError, KeyError) as exc:
            st.warning(f"SEC monitor is temporarily unavailable. Verified report balances are retained. {exc}")
            previous = st.session_state.get("last_sec_monitor")
            if not previous:
                return
            status, feed = previous
            st.caption("Last successfully retrieved feed; it may be stale.")
        st.caption("SEC checks every 30 seconds on Mondays, 6:45–9:30 a.m. Eastern. This feed refreshes every 15 seconds while the page is open.")
        st.caption("Polling window active." if status.get("schedule", {}).get("active") else "Outside the Monday polling window; saved observations are shown.")
        st.caption("New filings appear here immediately after detection. The report card keeps its dated, verified balances until all required NAV inputs are reconciled.")
        issuers = status.get("issuers", [])
        if isinstance(issuers, dict):
            issuers = list(issuers.values())
        if isinstance(issuers, list) and issuers:
            st.table([{key: value for key, value in issuer.items() if key in
                       ("ticker", "lastAttemptAt", "lastSuccessAt", "nextAlarmAt", "error", "configured")}
                      for issuer in issuers if isinstance(issuer, dict)])
        rows = filing_rows(feed)
        if rows:
            st.dataframe(rows, hide_index=True, column_config={"Filing": st.column_config.LinkColumn("SEC filing")})
        else:
            st.caption("No filing observations recorded yet.")
        st.json(status, expanded=False)
        for filing in feed.get("filings", [])[:10]:
            if isinstance(filing, dict) and filing.get("extracted"):
                st.markdown(f"**{filing.get('ticker', '')} · {filing.get('accession', '')} — extracted filing facts**")
                st.json(filing["extracted"], expanded=False)
        if feed_fresh:
            acknowledge_rendered_filings(origin, feed, rows, st.session_state, _ack_token())

    monitor_fragment()
