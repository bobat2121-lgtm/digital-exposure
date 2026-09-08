"""Page openings fetch afresh while complete fallback snapshots remain isolated."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event, Lock
import unittest
from unittest.mock import patch

from report.current_prices import SOURCE_URLS
from report.price_refresh import PriceStore


def snapshot(day, bitcoin=82_000.0):
    return {
        "schema_version": 1,
        "fetched_at": f"2026-09-{day:02d}T16:30:00+00:00",
        "quotes": {symbol: {"symbol": symbol, "price": price,
                            "as_of": f"2026-09-{day:02d}T16:29:00+00:00",
                            "source_url": SOURCE_URLS[symbol]}
                   for symbol, price in {"MSTR": 150.0, "ASST": 30.0, "STRC": 101.0,
                                         "EURUSD=X": 1.2, "BTC-USD": bitcoin}.items()},
    }


class PriceRefreshTests(unittest.TestCase):
    def setUp(self):
        self.saved = snapshot(1)
        self.fresh = snapshot(2, 83_000.0)
        self.newest = snapshot(3, 84_000.0)
        self.load = self.start_patch("report.price_refresh.load_current_prices", return_value=deepcopy(self.saved))
        self.pull = self.start_patch("report.price_refresh.pull_current_prices", return_value=deepcopy(self.fresh))
        self.write = self.start_patch("report.current_prices.save_current_prices", side_effect=AssertionError("Visitor refreshes must not write files"))

    def start_patch(self, target, *args, **kwargs):
        patcher = patch(target, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def test_each_opening_attempts_a_new_complete_refresh(self):
        self.pull.side_effect = [deepcopy(self.fresh), deepcopy(self.newest)]
        store = PriceStore()
        first, second = store.refresh(), store.refresh()
        self.assertEqual(first.prices, self.fresh)
        self.assertEqual(second.prices, self.newest)
        self.assertFalse(first.using_saved_prices)
        self.assertFalse(second.using_saved_prices)
        self.assertEqual(self.pull.call_count, 2)
        self.write.assert_not_called()

    def test_provider_failure_preserves_complete_saved_snapshot_and_timestamps(self):
        # The existing provider validates its complete bundle and raises when
        # any source is missing/invalid; a partial bundle is never returned.
        self.pull.side_effect = ValueError("One provider response is incomplete")
        result = PriceStore().refresh()
        self.assertTrue(result.using_saved_prices)
        self.assertEqual(result.prices, self.saved)
        self.write.assert_not_called()

    def test_later_failure_uses_newest_success_instead_of_older_bundled_quotes(self):
        self.pull.side_effect = [deepcopy(self.fresh), deepcopy(self.newest), OSError("Timeout")]
        store = PriceStore()
        store.refresh()
        store.refresh()
        result = store.refresh()
        self.assertTrue(result.using_saved_prices)
        self.assertEqual(result.prices, self.newest)
        self.write.assert_not_called()

    def test_missing_or_corrupt_bundled_fallback_does_not_block_a_fresh_success(self):
        for error in (OSError("Missing"), ValueError("Malformed snapshot")):
            with self.subTest(error=type(error).__name__):
                self.load.side_effect = error
                result = PriceStore().refresh()
                self.assertFalse(result.using_saved_prices)
                self.assertEqual(result.prices, self.fresh)

    def test_failed_source_and_failed_fallback_return_no_partial_report(self):
        self.load.side_effect = ValueError("Malformed snapshot")
        self.pull.side_effect = OSError("Provider unavailable")
        result = PriceStore().refresh()
        self.assertTrue(result.using_saved_prices)
        self.assertIsNone(result.prices)

    def test_visitors_cannot_mutate_each_others_fallback_prices(self):
        source = deepcopy(self.fresh)
        self.pull.side_effect = [source, OSError("Timeout")]
        store = PriceStore()
        first = store.refresh()
        first.prices["quotes"]["BTC-USD"]["price"] = 1.0
        source["quotes"]["MSTR"]["price"] = 2.0
        second = store.refresh()
        self.assertEqual(second.prices, self.fresh)

    def test_one_older_provider_timestamp_rejects_the_entire_new_bundle(self):
        regressed = snapshot(4, 90_000.0)
        regressed["quotes"]["MSTR"]["as_of"] = self.saved["quotes"]["MSTR"]["as_of"]
        self.pull.side_effect = [deepcopy(self.newest), regressed]
        store = PriceStore()
        store.refresh()
        result = store.refresh()
        self.assertTrue(result.using_saved_prices)
        self.assertEqual(result.prices, self.newest)
        self.assertNotEqual(result.prices["quotes"]["BTC-USD"]["price"], 90_000.0)

    def test_slow_older_request_cannot_replace_a_newer_completed_request(self):
        entered, release = Event(), Event()
        counter_lock = Lock()
        calls = 0
        delayed = deepcopy(self.fresh)
        delayed["fetched_at"] = "2026-09-04T16:30:00+00:00"

        def pull():
            nonlocal calls
            with counter_lock:
                calls += 1
                order = calls
            if order == 1:
                entered.set()
                if not release.wait(3):
                    raise AssertionError("The concurrent newer refresh did not finish")
                return delayed
            if order == 2:
                return deepcopy(self.newest)
            raise OSError("Provider unavailable")

        self.pull.side_effect = pull
        store = PriceStore()
        with ThreadPoolExecutor(max_workers=1) as pool:
            earlier = pool.submit(store.refresh)
            try:
                self.assertTrue(entered.wait(3))
                recent = store.refresh()
                self.assertEqual(recent.prices, self.newest)
            finally:
                release.set()
            older_result = earlier.result(timeout=3)
        self.assertEqual(older_result.prices, self.newest)
        self.assertEqual(store.refresh().prices, self.newest)


if __name__ == "__main__":
    unittest.main()
