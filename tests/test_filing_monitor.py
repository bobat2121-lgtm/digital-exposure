"""Offline tests for the public filing feed, its trust boundaries, and provenance."""
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from report import filing_monitor as monitor


ORIGIN = "https://capital-report.example.workers.dev"
DOCUMENT = "https://www.sec.gov/Archives/edgar/data/1920406/000162828026059468/asst-20260831.htm"


def observation(**changes):
    return {"ticker": "ASST", "form": "8-K", "accession": "0001628280-26-059468",
            "acceptedAt": "2026-08-31T12:00:00.000Z", "firstSeenAt": "2026-09-07T11:00:15.000Z",
            "documentFetchedAt": None, "primaryDocumentUrl": DOCUMENT,
            "baseline": False, "status": "pending", "extracted": None, **changes}


class Response(BytesIO):
    def __init__(self, body, url):
        super().__init__(body)
        self.url = url
        self.read_sizes = []

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class MonitorConfigTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "sec-monitor.json"
        for context in (patch.object(monitor, "CONFIG_PATH", self.path), patch.dict(os.environ, {"SEC_MONITOR_URL": ""})):
            context.start()
            self.addCleanup(context.stop)

    def test_optional_config_and_environment_precedence(self):
        self.assertIsNone(monitor.monitor_url())
        self.path.write_text(json.dumps({"url": f"  {ORIGIN}/ "}), encoding="utf-8")
        self.assertEqual(monitor.monitor_url(), ORIGIN)
        with patch.dict(os.environ, {"SEC_MONITOR_URL": "https://override.example.workers.dev"}):
            self.assertEqual(monitor.monitor_url(), "https://override.example.workers.dev")

    def test_origin_rejects_non_worker_targets_and_ambiguous_components(self):
        invalid = ["http://capital-report.example.workers.dev", "https://workers.dev",
                   "https://capital-report.example.workers.dev.attacker.test",
                   "https://user@capital-report.example.workers.dev", ORIGIN + ":443",
                   ORIGIN + "/api/status", ORIGIN + "?target=other", ORIGIN + "#other"]
        for url in invalid:
            with self.subTest(url=url), patch.dict(os.environ, {"SEC_MONITOR_URL": url}):
                with self.assertRaises(ValueError):
                    monitor.monitor_url()

    def test_malformed_config_is_a_controlled_validation_error(self):
        for payload in ([], None, {"url": 123}, {"url": [ORIGIN]}):
            with self.subTest(payload=payload):
                self.path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    monitor.monitor_url()


class MonitorFeedTests(unittest.TestCase):
    def test_json_fetch_is_bounded_and_uses_a_timeout(self):
        url = ORIGIN + "/api/status"
        response = Response(b'{"schemaVersion":1}', url)
        with patch.object(monitor, "urlopen", return_value=response) as open_url:
            self.assertEqual(monitor._get(url), {"schemaVersion": 1})
        self.assertEqual(response.read_sizes, [monitor.MAX_BYTES + 1])
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, url)
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(open_url.call_args.kwargs["timeout"], 8)

    def test_oversized_redirected_and_non_object_responses_are_rejected(self):
        url = ORIGIN + "/api/status"
        cases = [(b"{}" + b" " * 64, url), (b"{}", ORIGIN + "/other"),
                 (b"[]", url), (b"null", url), (b"malformed", url)]
        for body, destination in cases:
            with self.subTest(body=body[:10], destination=destination), \
                 patch.object(monitor, "MAX_BYTES", 32), \
                 patch.object(monitor, "urlopen", return_value=Response(body, destination)):
                with self.assertRaises(ValueError):
                    monitor._get(url)

    def test_status_and_feed_are_read_from_separate_public_endpoints(self):
        status = {"schemaVersion": 1, "issuers": [{"ticker": "ASST", "configured": True}]}
        feed = {"schemaVersion": 1, "filings": [observation()]}
        payloads = {ORIGIN + "/api/status": status, ORIGIN + "/api/filings": feed}
        original = deepcopy(payloads)
        with patch.object(monitor, "_get", side_effect=lambda url: payloads[url]) as get:
            self.assertEqual(monitor.read_monitor(ORIGIN), (status, feed))
        self.assertCountEqual([call.args[0] for call in get.call_args_list], payloads)
        self.assertEqual(payloads, original)

    def test_unknown_feed_versions_or_non_list_filings_are_rejected(self):
        invalid = [{"schemaVersion": 2, "filings": []}, {"schemaVersion": True, "filings": []},
                   {"schemaVersion": "1", "filings": []},
                   {"schemaVersion": 1, "filings": {}}, {"schemaVersion": 1}]
        status = {"schemaVersion": 1, "issuers": []}
        for feed in invalid:
            with self.subTest(feed=feed), patch.object(monitor, "_get", side_effect=lambda url: status if url.endswith("/status") else feed):
                with self.assertRaises(ValueError):
                    monitor.read_monitor(ORIGIN)

    def test_unknown_status_versions_or_invalid_issuers_are_rejected(self):
        invalid = [{"schemaVersion": 2, "issuers": []}, {"schemaVersion": True, "issuers": []},
                   {"schemaVersion": 1, "issuers": "bad"}]
        feed = {"schemaVersion": 1, "filings": []}
        for status in invalid:
            with self.subTest(status=status), patch.object(monitor, "_get", side_effect=lambda url: status if url.endswith("/status") else feed):
                with self.assertRaises(ValueError):
                    monitor.read_monitor(ORIGIN)

    def test_only_canonical_https_sec_archive_links_are_published(self):
        invalid = ["https://www.sec.gov.attacker.test/Archives/edgar/data/1/report.htm",
                   "https://www.sec.gov@attacker.test/Archives/edgar/data/1/report.htm",
                   "http://www.sec.gov/Archives/edgar/data/1/report.htm",
                   "https://attacker.test/Archives/edgar/data/1/report.htm",
                   "https://www.sec.gov/untrusted/report.htm", "javascript:alert(1)", None,
                   DOCUMENT.replace("https://", "https://user@"), DOCUMENT + "?download=other",
                   DOCUMENT + "#other", DOCUMENT.replace("www.sec.gov", "www.sec.gov:444")]
        feed = {"schemaVersion": 1, "filings": [observation(primaryDocumentUrl=url) for url in invalid] + [observation()]}
        self.assertEqual([row["Filing"] for row in monitor.filing_rows(feed)], [DOCUMENT])

    def test_baseline_is_separate_from_new_detection_without_mutating_source(self):
        feed = {"schemaVersion": 1, "filings": [observation(baseline=True, status="baseline"),
                observation(accession="0001628280-26-059469", status="ready_for_review",
                            documentFetchedAt="2026-09-07T11:00:18.000Z",
                            extracted={"balanceDate": "2026-09-06"})]}
        original = deepcopy(feed)
        baseline, new = monitor.filing_rows(feed)
        self.assertEqual(baseline["State"], "Initial baseline")
        self.assertEqual(new["State"], "ready_for_review")
        self.assertEqual(baseline["Document received"], "Pending")
        self.assertEqual(new["Balance date"], "2026-09-06")
        self.assertEqual(new["SEC accepted"], "2026-08-31T12:00:00.000Z")
        self.assertEqual(new["First observed"], "2026-09-07T11:00:15.000Z")
        self.assertEqual(feed, original)

    def test_bad_optional_extraction_and_non_records_do_not_crash_rows(self):
        feed = {"schemaVersion": 1, "filings": [None, "bad", 123, observation(extracted=["bad"])]}
        rows = monitor.filing_rows(feed)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Balance date"], "Not extracted")


if __name__ == "__main__":
    unittest.main()
