"""The live Monday adapter publishes and downloads one captured snapshot."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image
from streamlit.testing.v1 import AppTest
import monday_page as page
from report import filing_monitor
from report.current_report import current_report
from report.filing_monitor import MonitorSnapshot
from report.price_refresh import PriceRefreshResult
from report.public_page import render_public_report


def quotes(bitcoin=82_000, day="2026-09-08"):
    return {"schema_version": 1, "fetched_at": f"{day}T16:30:00+00:00", "quotes": {
        symbol: {"symbol": symbol, "price": value, "as_of": f"{day}T16:29:00+00:00", "source_url": "https://example.test/quote"}
        for symbol, value in {"BTC-USD": bitcoin, "MSTR": 150, "ASST": 30, "STRC": 101, "EURUSD=X": 1.2}.items()}}


def resolve(prices, feed):
    return SimpleNamespace(report=current_report(prices), notice=None, version=feed.get("version", "test"))


class MondayAdapterTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path(filing_monitor.__file__).resolve().is_relative_to(ROOT / "report"))
        page.downloadable_report.clear()
        self.addCleanup(page.downloadable_report.clear)
        self.prices = quotes()
        self.snapshot = MonitorSnapshot({"schemaVersion": 1, "issuers": []},
                                        {"schemaVersion": 1, "filings": [], "version": "initial"})
        self.fetch = self.start_patch("monday_page.load_monitor_snapshot", return_value=self.snapshot)
        self.resolve = self.start_patch("monday_page.resolve_live_report", side_effect=resolve)
        self.start_patch("monday_page.render_monitor")
        self.start_patch("report.current_prices.urlopen", side_effect=AssertionError("No live price network in tests"))
        self.start_patch("report.filing_monitor.urlopen", side_effect=AssertionError("No SEC network in tests"))
        self.refresh = self.start_patch("monday_page.price_store", return_value=SimpleNamespace(
            refresh=lambda: PriceRefreshResult(deepcopy(self.prices))))

    def start_patch(self, target, *args, **kwargs):
        patcher = patch(target, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def app(self):
        return AppTest.from_string("import monday_page\nmonday_page.render()\n").run(timeout=30)

    def report_html(self, app):
        return next(element.proto.body for element in app.get("html") if '<div class="dcr">' in element.proto.body)

    def test_html_and_panel_only_png_are_built_from_one_immutable_view(self):
        prepared = page.prepare_snapshot(current_report(self.prices), self.prices)
        self.assertEqual(prepared.html, render_public_report(prepared.view))
        self.assertEqual(prepared.png, page.render_post_png(prepared.view))
        with Image.open(BytesIO(prepared.png)) as image:
            self.assertEqual(image.size, (1800, 1125))
            self.assertEqual(image.info["Title"], prepared.view.title)
        old_png, old_html = prepared.png, prepared.html
        self.prices["quotes"]["BTC-USD"]["price"] = 999_999
        self.assertEqual(prepared.png, old_png)
        self.assertEqual(prepared.html, old_html)
        self.assertNotIn("Refresh data", prepared.html)
        self.assertNotIn("weekly_report_tabs", prepared.html)

    def test_revisiting_tab_retains_data_and_download_manual_refresh_changes_both(self):
        app = self.app()
        self.assertEqual(len(app.exception), 0)
        first_html = self.report_html(app)
        first_download = app.get("download_button")[0].proto.url
        self.refresh.assert_called_once_with()
        self.fetch.assert_called_once_with(force=False)
        app.session_state["weekly_active_report"] = "Friday"
        app.run(timeout=30)
        self.assertEqual(len(app.get("download_button")), 0)
        app.session_state["weekly_active_report"] = "Monday"
        app.run(timeout=30)
        self.assertEqual(self.report_html(app), first_html)
        self.assertEqual(app.get("download_button")[0].proto.url, first_download)
        self.assertEqual(self.refresh.call_count, 1)
        self.assertEqual(self.fetch.call_count, 1)
        self.prices = quotes(83_000, "2026-09-09")
        app.button(key="monday_refresh").click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.refresh.call_count, 2)
        self.fetch.assert_called_with(force=True)
        self.assertNotEqual(self.report_html(app), first_html)
        self.assertNotEqual(app.get("download_button")[0].proto.url, first_download)
        self.assertEqual(app.session_state[page.PREPARED].html, self.report_html(app))
        self.assertEqual(app.session_state[page.PREPARED].png,
                         page.render_post_png(app.session_state[page.PREPARED].view))

    def test_new_browser_session_fetches_prices_again(self):
        first = self.app()
        self.prices = quotes(84_000, "2026-09-09")
        second = self.app()
        self.assertEqual(self.refresh.call_count, 2)
        self.assertNotEqual(self.report_html(first), self.report_html(second))
        self.assertNotEqual(first.get("download_button")[0].proto.url, second.get("download_button")[0].proto.url)

    def test_failed_png_never_publishes_new_html_or_changes_captured_download(self):
        state = {page.PRICES: PriceRefreshResult(self.prices)}
        original = page.refresh_report(state)
        self.prices["quotes"]["BTC-USD"]["price"] = 90_000
        with patch("monday_page.prepare_snapshot", side_effect=ValueError("Synthetic export failure")):
            result = page.refresh_report(state, force_monitor=True)
        self.assertIs(result, original)
        self.assertIs(state[page.PREPARED], original)
        self.assertIn("could not be applied", state[page.PROBLEM])
        self.refresh.assert_not_called()

    def test_stale_sec_feed_retains_snapshot_and_never_refetches_prices(self):
        state = {page.PRICES: PriceRefreshResult(self.prices)}
        original = page.refresh_report(state)
        self.fetch.return_value = MonitorSnapshot(self.snapshot.status, self.snapshot.feed, stale=True,
                                                 notice="SEC refresh unavailable.")
        with patch("monday_page.resolve_live_report", side_effect=AssertionError("Do not replace retained report")):
            result = page.refresh_report(state)
        self.assertIs(result, original)
        self.assertTrue(state[page.MONITOR].stale)
        self.refresh.assert_not_called()

    def test_unavailable_initial_prices_show_no_partial_panel_or_download(self):
        self.refresh.return_value = SimpleNamespace(refresh=lambda: PriceRefreshResult(None))
        app = self.app()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(len(app.get("download_button")), 0)
        self.fetch.assert_not_called()


class MondayMonitorNamespaceTests(unittest.TestCase):
    def test_force_refresh_clears_only_its_cache_and_uses_namespaced_fallback(self):
        cleared = []
        def cache_data(**kwargs):
            def decorate(function):
                function.clear = lambda: cleared.append(function.__name__)
                return function
            return decorate
        state = {"last_sec_monitor": ({"wrong": "page"}, {"wrong": "page"})}
        fake = SimpleNamespace(cache_data=cache_data, session_state=state)
        status, feed = {"schemaVersion": 1, "issuers": []}, {"schemaVersion": 1, "filings": []}
        with patch.dict("sys.modules", {"streamlit": fake}), \
             patch.object(filing_monitor, "monitor_url", return_value="https://example.workers.dev"), \
             patch.object(filing_monitor, "read_monitor", side_effect=[(status, feed), OSError("Synthetic timeout")]):
            first = filing_monitor.load_monitor_snapshot(force=True)
            later = filing_monitor.load_monitor_snapshot()
        self.assertEqual(cleared, ["cached_feed"])
        self.assertEqual(state["monday_last_sec_monitor"], (status, feed))
        self.assertTrue(later.stale)
        self.assertEqual(later.feed, first.feed)
        self.assertEqual(state["last_sec_monitor"][0], {"wrong": "page"})


if __name__ == "__main__":
    unittest.main()
