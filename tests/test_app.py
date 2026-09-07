"""View switching and price-refresh integration with an isolated quote cache."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from report.current_prices import SOURCE_URLS, load_current_prices, save_current_prices


class AppViewTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache_path = Path(directory.name) / "current-prices.json"
        cache_patch = patch("report.current_prices.CACHE_PATH", self.cache_path)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        network_patch = patch("report.current_prices.urlopen", side_effect=AssertionError("Tests must not use the network"))
        network_patch.start()
        self.addCleanup(network_patch.stop)
        monitor_patch = patch("report.filing_monitor.monitor_url", return_value=None)
        monitor_patch.start()
        self.addCleanup(monitor_patch.stop)
        monitor_network_patch = patch("report.filing_monitor.urlopen", side_effect=AssertionError("Tests must not use the network"))
        monitor_network_patch.start()
        self.addCleanup(monitor_network_patch.stop)
        self.prices = {
            "schema_version": 1, "fetched_at": "2026-09-01T16:30:00+00:00",
            "quotes": {symbol: {"symbol": symbol, "price": price,
                                "as_of": "2026-09-01T16:29:00+00:00", "source_url": SOURCE_URLS[symbol]}
                       for symbol, price in {"MSTR": 150.0, "ASST": 30.0, "STRC": 101.0,
                                             "EURUSD=X": 1.2, "BTC-USD": 82_000.0}.items()},
        }
        save_current_prices(self.prices, now=datetime(2026, 9, 7, tzinfo=timezone.utc))
        self.app_path = Path(__file__).resolve().parents[1] / "app.py"

    def refresh_button(self, app):
        return next(button for button in app.button if button.label == "Refresh prices")

    def assert_bottom_audits_available(self, app):
        labels = [expander.label.lower() for expander in app.expander]
        self.assertEqual(len(labels), 2)
        self.assertTrue(any("method" in label or "calculated" in label for label in labels), labels)
        self.assertTrue(any("source" in label or "input" in label for label in labels), labels)

    def test_post_is_default_and_details_remain_available(self):
        app = AppTest.from_file(str(self.app_path)).run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.radio[0].value, "Post view")
        self.assertEqual(app.radio[0].options, ["Post view", "Detailed view"])
        self.assertEqual(app.selectbox[0].value, "Current prices · dated balances")
        self.assertFalse(self.refresh_button(app).disabled)
        self.assertEqual(len(app.get("download_button")), 1)
        self.assert_bottom_audits_available(app)

        app.radio[0].set_value("Detailed view").run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assert_bottom_audits_available(app)
        self.assertEqual(len(app.get("download_button")), 1)

        app.selectbox[0].set_value("Illustrative example").run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(self.refresh_button(app).disabled)
        self.assert_bottom_audits_available(app)
        app.selectbox[0].set_value("Aug 31, 2026 · Historical replay").run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(self.refresh_button(app).disabled)
        self.assert_bottom_audits_available(app)

        app.radio[0].set_value("Post view").run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assert_bottom_audits_available(app)
        app.selectbox[0].set_value("Current prices · dated balances").run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(self.refresh_button(app).disabled)
        self.assertEqual(len(app.get("download_button")), 1)
        self.assert_bottom_audits_available(app)

    def test_successful_price_refresh_saves_complete_snapshot_and_rerenders(self):
        app = AppTest.from_file(str(self.app_path)).run(timeout=30)
        refreshed = deepcopy(self.prices)
        refreshed["quotes"]["ASST"]["price"] = 31.0
        refreshed["quotes"]["BTC-USD"]["price"] = 83_000.0
        with patch("report.current_prices.pull_current_prices", return_value=refreshed) as pull:
            self.refresh_button(app).click().run(timeout=30)
        pull.assert_called_once_with()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.warning), 0)
        self.assertEqual(load_current_prices(), refreshed)
        self.assertEqual(app.selectbox[0].value, "Current prices · dated balances")
        self.assertEqual(len(app.get("download_button")), 1)

    def test_failed_price_refresh_retains_saved_quotes_and_recovery_clears_warning(self):
        app = AppTest.from_file(str(self.app_path)).run(timeout=30)
        original = self.cache_path.read_bytes()
        with patch("report.current_prices.pull_current_prices", side_effect=ValueError("Missing ASST quote")) as pull:
            self.refresh_button(app).click().run(timeout=30)
        pull.assert_called_once_with()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.cache_path.read_bytes(), original)
        self.assertEqual(len(app.warning), 1)
        self.assertIn("saved quotes retained", app.warning[0].value)
        self.assertIn("Missing ASST quote", app.warning[0].value)
        self.assertEqual(len(app.get("download_button")), 1)
        with patch("report.current_prices.pull_current_prices", return_value=self.prices):
            self.refresh_button(app).click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.warning), 0)
        self.assertEqual(load_current_prices(), self.prices)

    def test_monitor_updates_and_outage_preserve_report_and_last_feed(self):
        import streamlit as st
        from report.page import render_post_preview

        origin = "https://capital-report-test.example.workers.dev"
        status = {"schemaVersion": 1, "issuers": [{"ticker": "MSTR", "configured": True,
                  "lastSuccessAt": "2026-09-07T12:01:00.000Z", "inWindow": True}]}
        baseline = {"ticker": "MSTR", "form": "8-K", "accession": "0001050446-26-000100",
                    "acceptedAt": "2026-09-07T12:00:00.000Z", "firstSeenAt": "2026-09-07T12:00:20.000Z",
                    "primaryDocumentUrl": "https://www.sec.gov/Archives/edgar/data/1050446/000105044626000100/mstr-20260907.htm",
                    "baseline": True, "status": "baseline", "extracted": None}
        feed = {"schemaVersion": 1, "filings": [baseline]}
        original_quotes = self.cache_path.read_bytes()
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        with patch("report.filing_monitor.monitor_url", return_value=origin), \
             patch("report.filing_monitor.read_monitor", return_value=(status, feed)) as read, \
             patch("report.page.render_post_preview", wraps=render_post_preview) as preview:
            app = AppTest.from_file(str(self.app_path)).run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.warning), 0)
            original_view, original_png = preview.call_args.args
            self.assertEqual(app.dataframe[0].value.iloc[0]["State"], "Initial baseline")

            new_filing = {**baseline, "accession": "0001050446-26-000101", "baseline": False,
                          "firstSeenAt": "2026-09-07T12:01:10.000Z", "status": "ready_for_review",
                          "extracted": {"parserVersion": "1", "periodStart": "2026-08-31", "periodEnd": "2026-09-06",
                                        "balanceDate": "2026-09-06", "priorBalanceDate": "2026-08-30",
                                        "facts": {}, "priorFacts": {}, "securities": {}, "missing": [],
                                        "issues": [], "extractionValidated": True}}
            updated_feed = {"schemaVersion": 1, "filings": [new_filing, baseline]}
            read.return_value = (status, updated_feed)
            st.cache_data.clear()
            app.run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.dataframe[0].value.iloc[0]["State"], "ready_for_review")
            self.assertEqual(preview.call_args.args, (original_view, original_png))

            read.side_effect = OSError("Monitor request timed out")
            st.cache_data.clear()
            app.run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.warning), 1)
            self.assertIn("Verified report balances are retained", app.warning[0].value)
            self.assertTrue(any("may be stale" in caption.value for caption in app.caption))
            self.assertEqual(len(app.dataframe[0].value), 2)
            self.assertEqual(preview.call_args.args, (original_view, original_png))
            self.assertEqual(self.cache_path.read_bytes(), original_quotes)
            self.assert_bottom_audits_available(app)


if __name__ == "__main__":
    unittest.main()
