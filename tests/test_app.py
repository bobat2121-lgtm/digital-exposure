"""Every browser opening gets one complete quote refresh shared by web and PNG."""
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


FALLBACK_CAPTION = "Price refresh unavailable · showing last saved quotes."


class PublicAppTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache_path = Path(directory.name) / "current-prices.json"
        self.start_patch("report.current_prices.CACHE_PATH", self.cache_path)
        self.quote_network = self.start_patch("report.current_prices.urlopen", side_effect=AssertionError("Tests must not call a market provider"))
        self.monitor_network = self.start_patch("report.filing_monitor.urlopen", side_effect=AssertionError("Tests must not call the live SEC monitor"))
        self.monitor_render = self.start_patch("report.filing_monitor.render_monitor")
        st.cache_data.clear()
        st.cache_resource.clear()
        self.addCleanup(st.cache_data.clear)
        self.addCleanup(st.cache_resource.clear)
        self.saved = {
            "schema_version": 1, "fetched_at": "2026-09-01T16:30:00+00:00",
            "quotes": {symbol: {"symbol": symbol, "price": price,
                                "as_of": "2026-09-01T16:29:00+00:00", "source_url": SOURCE_URLS[symbol]}
                       for symbol, price in {"MSTR": 150.0, "ASST": 30.0, "STRC": 101.0,
                                             "EURUSD=X": 1.2, "BTC-USD": 82_000.0}.items()},
        }
        save_current_prices(self.saved, now=datetime(2026, 9, 7, tzinfo=timezone.utc))
        self.fresh = self.quote_snapshot("2026-09-02", 83_000.0, 31.0)
        self.pull = self.start_patch("report.price_refresh.pull_current_prices", return_value=deepcopy(self.fresh))
        self.app_path = Path(__file__).resolve().parents[1] / "app.py"

    def start_patch(self, target, *args, **kwargs):
        patcher = patch(target, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def quote_snapshot(self, day, bitcoin, asst):
        result = deepcopy(self.saved)
        result["fetched_at"] = f"{day}T16:30:00+00:00"
        for quote in result["quotes"].values():
            quote["as_of"] = f"{day}T16:29:00+00:00"
        result["quotes"]["BTC-USD"]["price"] = bitcoin
        result["quotes"]["ASST"]["price"] = asst
        return result

    def open_app(self):
        return AppTest.from_file(str(self.app_path)).run(timeout=30)

    def assert_unavailable(self, app):
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(app.error[0].value, "The report is temporarily unavailable. Please try again shortly.")
        self.assertEqual(len(app.get("download_button")), 0)
        self.assertEqual(len(app.expander), 0)
        self.assertFalse(any('class="credit-grid"' in element.proto.body for element in app.get("html")))

    def report_html(self, app):
        return next(element.proto.body for element in app.get("html")
                    if '<div class="dcr">' in element.proto.body)

    def test_public_open_refreshes_without_adding_price_controls(self):
        app = self.open_app()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.pull.assert_called_once_with()
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
        for content in ("The Digital Credit Report", 'aria-label="Strategy comparison panel"',
                        'aria-label="Strive comparison panel"', "845,050", "23,156", "VWAP", "$97.48", "BTC $83,000"):
            self.assertIn(content, html)
        for removed in ("Current price demo", "CURRENT PRICE DEMO", "Reported net proceeds", "Sources &amp; input audit",
                        "post-preview", "data:image/png", "Post view"):
            self.assertNotIn(removed, html)
        self.assertEqual(len(app.markdown), 1)
        self.assertIn("Strategy includes its designated", app.markdown[0].value)
        self.assertIn("June 30 debt carryforward", app.markdown[0].value)
        self.assertIn("year-end award count remains unreconciled", app.markdown[0].value)
        self.assertNotIn(FALLBACK_CAPTION, [caption.value for caption in app.caption])

    def test_reruns_keep_one_session_snapshot_and_do_not_refetch_or_write_cache(self):
        original = self.cache_path.read_bytes()
        app = self.open_app()
        initial_html = self.report_html(app)
        initial_download = app.get("download_button")[0].proto.url
        self.pull.side_effect = AssertionError("A normal rerun must reuse the opening snapshot")
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.report_html(app), initial_html)
        self.assertEqual(app.get("download_button")[0].proto.url, initial_download)
        self.pull.assert_called_once_with()
        self.assertEqual(self.cache_path.read_bytes(), original)
        self.assertEqual(load_current_prices(), self.saved)
        self.quote_network.assert_not_called()
        self.monitor_network.assert_not_called()

    def test_new_open_refreshes_web_and_png_together_without_changing_balances(self):
        original = self.cache_path.read_bytes()
        newest = self.quote_snapshot("2026-09-03", 84_000.0, 32.0)
        self.pull.side_effect = [deepcopy(self.fresh), newest]
        with patch("report.public_page.render_public_report", wraps=render_public_report) as web, \
             patch("report.post_export.render_post_png", wraps=render_post_png) as export:
            first_app = self.open_app()
            self.assertEqual(len(first_app.exception), 0)
            first_view = web.call_args.args[0]
            self.assertEqual(export.call_args.args[0], first_view)
            first_download = first_app.get("download_button")[0].proto.url
            second_app = self.open_app()
            self.assertEqual(len(second_app.exception), 0)
            latest_view = web.call_args.args[0]
            self.assertEqual(export.call_args.args[0], latest_view)
            self.assertEqual(self.pull.call_count, 2)
            self.assertNotEqual(latest_view.btc_price, first_view.btc_price)
            self.assertNotEqual(latest_view.companies[1].stock_price, first_view.companies[1].stock_price)
            self.assertNotEqual(second_app.get("download_button")[0].proto.url, first_download)
            self.assertEqual(latest_view.subtitle, first_view.subtitle)
            self.assertEqual(latest_view.capital_period_label, first_view.capital_period_label)
            for previous, current in zip(first_view.companies, latest_view.companies):
                self.assertEqual(current.shares, previous.shares)
                self.assertEqual(current.btc_activity, previous.btc_activity)
                self.assertEqual(current.total_bitcoin, previous.total_bitcoin)
        self.assertEqual(self.cache_path.read_bytes(), original)

    def test_failed_refresh_uses_saved_prices_and_original_quote_timestamp(self):
        self.pull.side_effect = ValueError("Provider unavailable")
        with patch("report.public_page.render_public_report", wraps=render_public_report) as web, \
             patch("report.post_export.render_post_png", wraps=render_post_png) as export:
            app = self.open_app()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 0)
            self.assertEqual(web.call_args.args[0], export.call_args.args[0])
            self.assertEqual(web.call_args.args[0].report_time, "Updated Sep 1, 2026 · 12:30 PM ET")
        self.assertIn("BTC $82,000", self.report_html(app))
        self.assertIn(FALLBACK_CAPTION, [caption.value for caption in app.caption])
        self.assertNotIn("Provider unavailable", self.report_html(app))

    def test_later_failed_open_retains_newest_successful_in_memory_quotes(self):
        self.pull.side_effect = [deepcopy(self.fresh), OSError("Timeout")]
        first_app = self.open_app()
        second_app = self.open_app()
        self.assertEqual(len(second_app.exception), 0)
        self.assertEqual(self.pull.call_count, 2)
        self.assertEqual(self.report_html(second_app), self.report_html(first_app))
        self.assertEqual(second_app.get("download_button")[0].proto.url,
                         first_app.get("download_button")[0].proto.url)
        self.assertIn(FALLBACK_CAPTION, [caption.value for caption in second_app.caption])
        self.assertEqual(load_current_prices(), self.saved)

    def test_fresh_prices_work_without_a_bundled_snapshot(self):
        self.cache_path.unlink()
        app = self.open_app()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        self.assertIn("BTC $83,000", self.report_html(app))
        self.assertFalse(self.cache_path.exists())

    def test_missing_or_corrupt_fallback_with_failed_refresh_shows_no_partial_report(self):
        self.pull.side_effect = ValueError("Provider unavailable")
        self.cache_path.unlink()
        first_app = self.open_app()
        self.assert_unavailable(first_app)
        self.cache_path.write_text("{invalid JSON", encoding="utf-8")
        second_app = self.open_app()
        self.assert_unavailable(second_app)
        self.assertEqual(self.pull.call_count, 2)
        self.monitor_render.assert_not_called()

    def test_storage_and_provider_failure_show_public_error_without_private_details(self):
        original = self.cache_path.read_bytes()
        self.pull.side_effect = OSError("Private provider error")
        with patch("report.price_refresh.load_current_prices", side_effect=OSError("Private cache path is inaccessible")):
            app = self.open_app()
        self.assert_unavailable(app)
        self.assertEqual(self.cache_path.read_bytes(), original)
        self.assertNotIn("Private", app.error[0].value)


if __name__ == "__main__":
    unittest.main()
