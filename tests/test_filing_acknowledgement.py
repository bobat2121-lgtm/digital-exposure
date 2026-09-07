"""Offline checks for the Streamlit-to-Worker publication acknowledgement."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from report import filing_monitor as monitor


ORIGIN = "https://capital-report.example.workers.dev"
NOW = datetime(2026, 9, 7, 16, tzinfo=timezone.utc)
TOKEN = "ack-test-token-" + "x" * 48


def filing(ticker="MSTR", **changes):
    cik = {"MSTR": "1050446", "ASST": "1920406"}[ticker]
    accession = {"MSTR": "0001193125-26-375463", "ASST": "0001628280-26-059468"}[ticker]
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/report.htm"
    received = "2026-09-07T12:00:20.000Z"
    return {
        "ticker": ticker, "accession": accession, "form": "8-K", "baseline": False,
        "acceptedAt": "2026-09-07T12:00:00.000Z", "documentFetchedAt": received,
        "primaryDocumentUrl": url, "status": "ready_for_review",
        "documents": [{"url": url, "fetchedAt": received, "sha256": ("a" if ticker == "MSTR" else "b") * 64}],
        "extracted": {"facts": {"btc_holdings": 100, "weekly_btc_purchases": 0}}, **changes,
    }


def feed(*records):
    return {"schemaVersion": 1, "filings": list(records or (filing(), filing("ASST")))}


class Response(BytesIO):
    def __init__(self, body=b'{"outcome":"queued"}', url=ORIGIN + "/api/streamlit/ack"):
        super().__init__(body)
        self.url = url
        self.read_sizes = []

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class AcknowledgementSelectionTests(unittest.TestCase):
    def select(self, payload):
        return monitor.select_acknowledgement(payload, now=NOW)

    def test_exact_pair_in_stable_order_without_mutating_feed(self):
        payload = feed(filing("ASST", status="partial"), filing())
        original = deepcopy(payload)
        pair = self.select(payload)
        self.assertEqual([record["ticker"] for record in pair], ["MSTR", "ASST"])
        self.assertEqual([record["sha256"] for record in pair], ["a" * 64, "b" * 64])
        self.assertTrue(all(set(record) == {"ticker", "accession", "sha256"} for record in pair))
        self.assertEqual(payload, original)

    def test_baseline_pending_amendment_and_unrelated_filings_do_not_qualify(self):
        for changes in ({"baseline": True}, {"baseline": None}, {"form": "8-K/A"},
                        {"status": "pending"}, {"status": "not_weekly"},
                        {"documentFetchedAt": None}, {"documentFetchedAt": "2026-09-08T12:00:00Z"},
                        {"documentFetchedAt": "2026-09-07T11:59:59Z"},
                        {"extracted": None}, {"extracted": {"facts": {"btc_holdings": 100}}},
                        {"extracted": {"facts": {"btc_holdings": True, "weekly_btc_purchases": 1}}},
                        {"extracted": {"facts": {"btc_holdings": 0, "weekly_btc_purchases": 1}}},
                        {"extracted": {"facts": {"btc_holdings": 100, "weekly_btc_purchases": -1}}},
                        {"extracted": {"facts": {"btc_holdings": float("nan"), "weekly_btc_purchases": 1}}},
                        {"extracted": {"facts": {"btc_holdings": 10 ** 1000, "weekly_btc_purchases": 1}}}):
            with self.subTest(changes=changes):
                self.assertIsNone(self.select(feed(filing(**changes), filing("ASST"))))
        malformed = filing()
        malformed["ticker"] = ["MSTR"]
        self.assertIsNone(self.select(feed(None, "bad", malformed, filing("ASST"))))

    def test_acceptance_must_be_recent_same_eastern_monday_and_timezone_aware(self):
        for accepted in ("2026-09-07T03:59:59Z", "2026-09-08T04:00:00Z", "2026-09-07T12:00:00",
                         "2026-08-31T12:00:00Z", "2026-08-17T12:00:00Z", "bad", None):
            with self.subTest(accepted=accepted):
                self.assertIsNone(self.select(feed(filing(acceptedAt=accepted), filing("ASST"))))
        payload = feed(filing(acceptedAt="2026-09-08T03:59:59Z"), filing("ASST", acceptedAt="2026-09-08T03:59:59Z"))
        for record in payload["filings"]:
            record["documentFetchedAt"] = record["documents"][0]["fetchedAt"] = "2026-09-08T04:00:20Z"
        self.assertIsNotNone(monitor.select_acknowledgement(payload, now=datetime(2026, 9, 8, 5, tzinfo=timezone.utc)))

    def test_uses_latest_complete_monday_pair_and_latest_primary_per_issuer(self):
        older = [filing(ticker, acceptedAt="2026-08-31T12:00:00Z") for ticker in ("MSTR", "ASST")]
        later = filing(acceptedAt="2026-09-07T13:00:00Z")
        later["documentFetchedAt"] = later["documents"][0]["fetchedAt"] = "2026-09-07T13:00:20Z"
        later["documents"][0]["sha256"] = "c" * 64
        pair = self.select(feed(*older, filing(), filing("ASST"), later))
        self.assertEqual(pair[0]["sha256"], "c" * 64)
        self.assertEqual(pair[1]["sha256"], "b" * 64)

    def test_hash_document_url_and_fetch_time_are_required(self):
        source = filing()
        invalid_documents = [None, [], [{}], [{**source["documents"][0], "sha256": "A" * 64}],
                             [{**source["documents"][0], "sha256": "a" * 63}],
                             [{**source["documents"][0], "fetchedAt": None}],
                             [{**source["documents"][0], "fetchedAt": "2026-09-07T12:00:21Z"}],
                             [{**source["documents"][0], "fetchedAt": "2026-09-08T12:00:00Z"}],
                             [{**source["documents"][0], "url": source["primaryDocumentUrl"] + "other"}]]
        for documents in invalid_documents:
            with self.subTest(documents=documents):
                self.assertIsNone(self.select(feed(filing(documents=documents), filing("ASST"))))
        for url in ("https://attacker.test/report.htm", source["primaryDocumentUrl"].replace("1050446", "1920406"),
                    source["primaryDocumentUrl"].replace("000119312526375463", "000119312526375999")):
            bad = filing(primaryDocumentUrl=url, documents=[{**source["documents"][0], "url": url}])
            self.assertIsNone(self.select(feed(bad, filing("ASST"))))


class AcknowledgementTransportTests(unittest.TestCase):
    def setUp(self):
        self.pair = monitor.select_acknowledgement(feed(), now=NOW)

    def test_bounded_https_post_uses_bearer_header_and_no_redirect_handler(self):
        response = Response()
        opener = Mock()
        opener.open.return_value = response
        with patch.object(monitor, "build_opener", return_value=opener) as build:
            self.assertEqual(monitor.acknowledge_filings(ORIGIN, self.pair, TOKEN), "queued")
        self.assertIsInstance(build.call_args.args[0], monitor._NoRedirect)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, ORIGIN + "/api/streamlit/ack")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
        self.assertEqual(json.loads(request.data), {"filings": self.pair})
        self.assertNotIn(TOKEN, request.data.decode())
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 8)
        self.assertEqual(response.read_sizes, [monitor.ACK_MAX_BYTES + 1])

    def test_redirect_handler_never_builds_a_forwarded_request(self):
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code):
                self.assertIsNone(monitor._NoRedirect().redirect_request(None, None, code, "redirect", {}, "https://attacker.test"))

    def test_only_positive_durable_outcomes_are_successful(self):
        for outcome in ("queued", "sent", "duplicate"):
            opener = Mock()
            opener.open.return_value = Response(json.dumps({"outcome": outcome}).encode())
            with patch.object(monitor, "build_opener", return_value=opener):
                self.assertEqual(monitor.acknowledge_filings(ORIGIN, self.pair, TOKEN), outcome)
        for body in (b"{}", b"[]", b"malformed", b'{"outcome":"failed"}', b" " * (monitor.ACK_MAX_BYTES + 1)):
            opener = Mock()
            opener.open.return_value = Response(body)
            with self.subTest(body=body[:30]), patch.object(monitor, "build_opener", return_value=opener):
                with self.assertRaises(ValueError):
                    monitor.acknowledge_filings(ORIGIN, self.pair, TOKEN)

    def test_redirects_and_network_errors_do_not_expose_credentials(self):
        for result in (Response(url="https://attacker.test/"), HTTPError(ORIGIN, 502, TOKEN, {}, None), OSError(TOKEN)):
            opener = Mock()
            if isinstance(result, Exception):
                opener.open.side_effect = result
            else:
                opener.open.return_value = result
            with patch.object(monitor, "build_opener", return_value=opener):
                with self.assertRaises(ValueError) as caught:
                    monitor.acknowledge_filings(ORIGIN, self.pair, TOKEN)
            self.assertNotIn(TOKEN, str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)

    def test_invalid_destination_secret_or_pair_never_sends(self):
        for origin, token, pair in (("http://capital-report.example.workers.dev", TOKEN, self.pair),
                                    ("https://attacker.test", TOKEN, self.pair), (ORIGIN + "/other", TOKEN, self.pair),
                                    (ORIGIN, "short", self.pair), (ORIGIN, TOKEN + "\r\n", self.pair),
                                    (ORIGIN, TOKEN, self.pair[:1]), (ORIGIN, TOKEN, [self.pair[0]] * 2)):
            with self.subTest(origin=origin), patch.object(monitor, "build_opener") as build:
                with self.assertRaises(ValueError):
                    monitor.acknowledge_filings(origin, pair, token)
                build.assert_not_called()


class AcknowledgementSessionTests(unittest.TestCase):
    def setUp(self):
        select = monitor.select_acknowledgement
        replacement = patch.object(monitor, "select_acknowledgement", side_effect=lambda payload: select(payload, now=NOW))
        replacement.start()
        self.addCleanup(replacement.stop)

    def test_missing_secret_or_unrendered_company_never_acknowledges(self):
        payload = feed()
        rows = monitor.filing_rows(payload)
        with patch.object(monitor, "acknowledge_filings") as acknowledge:
            self.assertFalse(monitor.acknowledge_rendered_filings(ORIGIN, payload, rows, {}, None))
            self.assertFalse(monitor.acknowledge_rendered_filings(ORIGIN, payload, rows[:1], {}, TOKEN))
        acknowledge.assert_not_called()

    def test_retry_after_failure_and_cache_only_confirmed_pair(self):
        payload = feed()
        state = {}
        rows = monitor.filing_rows(payload)
        with patch.object(monitor, "acknowledge_filings", side_effect=[ValueError("unavailable"), "queued"]) as acknowledge:
            self.assertFalse(monitor.acknowledge_rendered_filings(ORIGIN, payload, rows, state, TOKEN))
            self.assertNotIn(monitor.ACK_SESSION_KEY, state)
            self.assertTrue(monitor.acknowledge_rendered_filings(ORIGIN, payload, rows, state, TOKEN))
            self.assertTrue(monitor.acknowledge_rendered_filings(ORIGIN, payload, rows, state, TOKEN))
            self.assertEqual(acknowledge.call_count, 2)

    def test_credential_comes_from_environment_or_server_secrets(self):
        with patch.dict(os.environ, {"STREAMLIT_ACK_TOKEN": TOKEN}), patch.dict("sys.modules", {"streamlit": SimpleNamespace(secrets={"STREAMLIT_ACK_TOKEN": "unused"})}):
            self.assertEqual(monitor._ack_token(), TOKEN)
        with patch.dict(os.environ, {"STREAMLIT_ACK_TOKEN": ""}), patch.dict("sys.modules", {"streamlit": SimpleNamespace(secrets={"STREAMLIT_ACK_TOKEN": TOKEN})}):
            self.assertEqual(monitor._ack_token(), TOKEN)
        with patch.dict(os.environ, {"STREAMLIT_ACK_TOKEN": ""}), patch.dict("sys.modules", {"streamlit": SimpleNamespace(secrets={})}):
            self.assertIsNone(monitor._ack_token())


if __name__ == "__main__":
    unittest.main()
