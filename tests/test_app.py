"""Public report integration using isolated, complete saved quote snapshots."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from report.current_prices import SOURCE_URLS, load_current_prices, save_current_prices
from report.post_export import render_post_png
from report.public_page import render_public_report


class PublicAppTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache_path = Path(directory.name) / "current-prices.json"
        cache_patch = patch("report.current_prices.CACHE_PATH", self.cache_path)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        network_patch = patch("report.current_prices.urlopen", side_effect=AssertionError("Public visits must not fetch quotes"))
        self.quote_network = network_patch.start()
        self.addCleanup(network_patch.stop)
        feed_patch = patch("report.filing_monitor.read_monitor", side_effect=AssertionError("The public page must not request a filing feed"))
        self.filing_feed = feed_patch.start()
        self.addCleanup(feed_patch.stop)
        monitor_network_patch = patch("report.filing_monitor.urlopen", side_effect=AssertionError("The public page must not call SEC monitoring"))
        self.monitor_network = monitor_network_patch.start()
        self.addCleanup(monitor_network_patch.stop)
        monitor_render_patch = patch("report.filing_monitor.render_monitor")
        self.monitor_render = monitor_render_patch.start()
        self.addCleanup(monitor_render_patch.stop)
        st.cache_data.clear()
        self.addCleanup(st.cache_data.clear)
        self.prices = {
            "schema_version": 1, "fetched_at": "2026-09-01T16:30:00+00:00",
            "quotes": {symbol: {"symbol": symbol, "price": price,
                                "as_of": "2026-09-01T16:29:00+00:00", "source_url": SOURCE_URLS[symbol]}
                       for symbol, price in {"MSTR": 150.0, "ASST": 30.0, "STRC": 101.0,
                                             "EURUSD=X": 1.2, "BTC-USD": 82_000.0}.items()},
        }
        save_current_prices(self.prices, now=datetime(2026, 9, 7, tzinfo=timezone.utc))
        self.app_path = Path(__file__).resolve().parents[1] / "app.py"

    def assert_unavailable(self, app):
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(app.error[0].value, "The report is temporarily unavailable. Please try again shortly.")
        self.assertEqual(len(app.get("download_button")), 0)
        self.assertEqual(len(app.expander), 0)
        self.assertFalse(any('class="credit-grid"' in element.proto.body for element in app.get("html")))

    def report_html(self, app):
        # Streamlit can move style-only HTML into its event container, so DOM
        # iteration order is not a reliable way to identify the visible report.
        return next(element.proto.body for element in app.get("html")
                    if '<div class="dcr">' in element.proto.body)

    def test_public_report_has_one_overview_and_discreet_download(self):
        app = AppTest.from_file(str(self.app_path)).run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        for element_type in ("selectbox", "radio", "tabs", "button", "dataframe", "table"):
            self.assertEqual(len(app.get(element_type)), 0, element_type)
        self.assertEqual([expander.label for expander in app.expander], ["Calculation overview", "Latest SEC filings"])
        self.monitor_render.assert_called_once()
        download = app.get("download_button")[0].proto
        self.assertEqual(len(app.get("download_button")), 1)
        self.assertEqual(download.label, "Download")
        self.assertEqual(download.type, "tertiary")
        self.assertTrue(download.ignore_rerun)
        self.assertTrue(download.url.endswith(".png"))

        html = self.report_html(app)
        self.assertIn("The Digital Credit Report", html)
        self.assertIn('aria-label="Strategy comparison panel"', html)
        self.assertIn('aria-label="Strive comparison panel"', html)
        self.assertIn("845,050", html)
        self.assertIn("23,156", html)
        self.assertIn("VWAP", html)
        self.assertIn("$97.48", html)
        for removed in ("Current price demo", "CURRENT PRICE DEMO", "Reported net proceeds", "Sources &amp; input audit",
                        "post-preview", "data:image/png", "Post view"):
            self.assertNotIn(removed, html)
        self.assertEqual(len(app.markdown), 1)
        self.assertIn("Strategy includes its designated", app.markdown[0].value)
        self.assertIn("June 30 debt carryforward", app.markdown[0].value)
        self.assertIn("year-end award count remains unreconciled", app.markdown[0].value)

    def test_public_reruns_preserve_saved_quotes_and_do_not_request_live_sources(self):
        original = self.cache_path.read_bytes()
        app = AppTest.from_file(str(self.app_path)).run(timeout=30)
        initial_html = self.report_html(app)
        initial_download = app.get("download_button")[0].proto.url
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.report_html(app), initial_html)
        self.assertEqual(app.get("download_button")[0].proto.url, initial_download)
        self.assertEqual(self.cache_path.read_bytes(), original)
        self.assertEqual(load_current_prices(), self.prices)
        self.quote_network.assert_not_called()
        self.filing_feed.assert_not_called()
        self.monitor_network.assert_not_called()

    def test_saved_quote_update_changes_web_and_download_together_without_changing_balances(self):
        with patch("report.public_page.render_public_report", wraps=render_public_report) as web, \
             patch("report.post_export.render_post_png", wraps=render_post_png) as export:
            app = AppTest.from_file(str(self.app_path)).run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            first_view = web.call_args.args[0]
            self.assertEqual(export.call_args.args[0], first_view)
            first_download = app.get("download_button")[0].proto.url

            refreshed = deepcopy(self.prices)
            refreshed["quotes"]["ASST"]["price"] = 31.0
            refreshed["quotes"]["BTC-USD"]["price"] = 83_000.0
            save_current_prices(refreshed, now=datetime(2026, 9, 7, tzinfo=timezone.utc))
            app.run(timeout=30)
            self.assertEqual(len(app.exception), 0)
            latest_view = web.call_args.args[0]
            self.assertEqual(export.call_args.args[0], latest_view)
            self.assertNotEqual(latest_view.btc_price, first_view.btc_price)
            self.assertNotEqual(latest_view.companies[1].stock_price, first_view.companies[1].stock_price)
            self.assertNotEqual(app.get("download_button")[0].proto.url, first_download)
            self.assertEqual(latest_view.subtitle, first_view.subtitle)
            self.assertEqual(latest_view.capital_period_label, first_view.capital_period_label)
            for previous, current in zip(first_view.companies, latest_view.companies):
                self.assertEqual(current.shares, previous.shares)
                self.assertEqual(current.bought, previous.bought)
                self.assertEqual(current.total_bitcoin, previous.total_bitcoin)
            self.assertEqual(load_current_prices(), refreshed)

    def test_missing_or_corrupt_quote_snapshot_shows_error_without_partial_report(self):
        self.cache_path.unlink()
        app = AppTest.from_file(str(self.app_path)).run(timeout=30)
        self.assert_unavailable(app)
        self.cache_path.write_text("{invalid JSON", encoding="utf-8")
        app.run(timeout=30)
        self.assert_unavailable(app)
        self.quote_network.assert_not_called()
        self.filing_feed.assert_not_called()

    def test_storage_failure_shows_public_error_and_retains_cache(self):
        original = self.cache_path.read_bytes()
        with patch("report.current_prices.load_current_prices", side_effect=OSError("Private cache path is inaccessible")):
            app = AppTest.from_file(str(self.app_path)).run(timeout=30)
        self.assert_unavailable(app)
        self.assertEqual(self.cache_path.read_bytes(), original)
        self.assertNotIn("Private cache path", app.error[0].value)


if __name__ == "__main__":
    unittest.main()
