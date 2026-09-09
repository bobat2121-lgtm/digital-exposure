"""A UI-free public SEC cache shared by both report refresh paths."""
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from threading import Event, Lock
import unittest
from unittest.mock import patch

from report import filing_monitor as monitor


ORIGIN = "https://capital-report.example.workers.dev"


def response(version):
    return ({"schemaVersion": 1, "issuers": [{"ticker": "MSTR", "version": version}]},
            {"schemaVersion": 1, "filings": [{"accession": version, "extracted": {"facts": {"btc_holdings": 845050}}}]})


class SharedMonitorTests(unittest.TestCase):
    def setUp(self):
        monitor.clear_shared_monitor_cache()
        self.addCleanup(monitor.clear_shared_monitor_cache)

    def test_exact_ttl_forced_refresh_and_origin_normalization(self):
        clock = [100.0]
        with patch.object(monitor, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(monitor, "read_monitor", side_effect=[response("one"), response("two"), response("three")]) as read:
            self.assertEqual(monitor.read_shared_monitor(ORIGIN), response("one"))
            clock[0] = 114.999
            self.assertEqual(monitor.read_shared_monitor(ORIGIN + "/"), response("one"))
            self.assertEqual(read.call_count, 1)
            clock[0] = 115.0
            self.assertEqual(monitor.read_shared_monitor(ORIGIN), response("two"))
            self.assertEqual(monitor.read_shared_monitor(ORIGIN, force=True), response("three"))
            self.assertEqual(read.call_count, 3)
            self.assertEqual({call.args[0] for call in read.call_args_list}, {ORIGIN})

    def test_provider_and_caller_mutation_cannot_change_another_report_snapshot(self):
        source = response("one")
        original = deepcopy(source)
        with patch.object(monitor, "read_monitor", return_value=source) as read, \
             patch.dict("sys.modules", {"streamlit": None}):
            monday = monitor.read_shared_monitor(ORIGIN)
            source[1]["filings"][0]["extracted"]["facts"]["btc_holdings"] = -1
            monday[0]["issuers"].clear()
            monday[1]["filings"][0]["accession"] = "modified-by-caller"
            friday = monitor.read_shared_monitor(ORIGIN)
            self.assertEqual(friday, original)
            self.assertIsNot(friday[1], monday[1])
            read.assert_called_once_with(ORIGIN)

    def _concurrent_refresh(self, *, failure=False, prime=False):
        """Hold one network call until every additional caller has joined it."""
        if prime:
            with patch.object(monitor, "read_monitor", return_value=response("old")):
                monitor.read_shared_monitor(ORIGIN)
        entered, release, all_waiting = Event(), Event(), Event()
        arrivals, arrivals_lock = [0], Lock()
        waiting_count = 6

        class ObservedFuture(Future):
            def result(self, timeout=None):
                with arrivals_lock:
                    arrivals[0] += 1
                    if arrivals[0] == waiting_count:
                        all_waiting.set()
                return super().result(timeout)

        def fetch(origin):
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("Test did not release the public request")
            if failure:
                raise OSError("Synthetic SEC outage")
            return response("new")

        with patch.object(monitor, "Future", ObservedFuture), \
             patch.object(monitor, "read_monitor", side_effect=fetch) as read, \
             ThreadPoolExecutor(max_workers=waiting_count + 1) as pool:
            owner = pool.submit(monitor.read_shared_monitor, ORIGIN, force=prime)
            self.assertTrue(entered.wait(timeout=2))
            waiters = [pool.submit(monitor.read_shared_monitor, ORIGIN, force=index % 2 == 0)
                       for index in range(waiting_count)]
            try:
                self.assertTrue(all_waiting.wait(timeout=2), "Concurrent readers did not join the in-flight request")
            finally:
                release.set()
            results = []
            for future in [owner, *waiters]:
                if failure:
                    with self.assertRaisesRegex(OSError, "Synthetic SEC outage"):
                        future.result(timeout=3)
                else:
                    results.append(future.result(timeout=3))
            read.assert_called_once_with(ORIGIN)
        return results

    def test_concurrent_forced_and_regular_reads_join_one_refresh(self):
        results = self._concurrent_refresh(prime=True)
        self.assertTrue(all(value == response("new") for value in results))
        results[0][1]["filings"].clear()
        self.assertTrue(all(value == response("new") for value in results[1:]))
        with patch.object(monitor, "read_monitor", side_effect=AssertionError("Fresh result should be cached")):
            self.assertEqual(monitor.read_shared_monitor(ORIGIN), response("new"))

    def test_failed_concurrent_fetch_is_shared_but_never_cached(self):
        self._concurrent_refresh(failure=True)
        with patch.object(monitor, "read_monitor", return_value=response("recovered")) as read:
            self.assertEqual(monitor.read_shared_monitor(ORIGIN), response("recovered"))
            read.assert_called_once_with(ORIGIN)

    def test_expired_failure_raises_instead_of_returning_previous_success(self):
        clock = [100.0]
        with patch.object(monitor, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(monitor, "read_monitor", side_effect=[response("old"), OSError("Unavailable"), response("recovered")]) as read:
            self.assertEqual(monitor.read_shared_monitor(ORIGIN), response("old"))
            clock[0] = 115.0
            with self.assertRaisesRegex(OSError, "Unavailable"):
                monitor.read_shared_monitor(ORIGIN)
            self.assertEqual(monitor.read_shared_monitor(ORIGIN), response("recovered"))
            self.assertEqual(read.call_count, 3)

    def test_force_failure_is_not_replaced_by_fresh_cached_data(self):
        with patch.object(monitor, "read_monitor", side_effect=[response("old"), ValueError("Unsupported schema")]):
            monitor.read_shared_monitor(ORIGIN)
            with self.assertRaisesRegex(ValueError, "Unsupported schema"):
                monitor.read_shared_monitor(ORIGIN, force=True)

    def test_origins_are_isolated_and_clear_starts_a_new_read(self):
        other = "https://other-report.example.workers.dev"
        with patch.object(monitor, "read_monitor", side_effect=[response("one"), response("two"), response("three")]) as read:
            self.assertEqual(monitor.read_shared_monitor(ORIGIN), response("one"))
            self.assertEqual(monitor.read_shared_monitor(other), response("two"))
            monitor.clear_shared_monitor_cache()
            self.assertEqual(monitor.read_shared_monitor(ORIGIN), response("three"))
            self.assertEqual(read.call_count, 3)
        with patch.object(monitor, "read_monitor") as read:
            with self.assertRaises(ValueError):
                monitor.read_shared_monitor("http://unsafe.example.test")
            read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
