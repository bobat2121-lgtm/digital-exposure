"""The page's background data store: a view never waits on a source that has a copy."""
import threading
import time
from unittest import TestCase

from panels import live


class LiveTests(TestCase):
    def setUp(self):
        live._entries.clear()
        self.addCleanup(live._entries.clear)

    def test_first_view_waits_for_the_first_copy(self):
        value, age = live.get("a", lambda: {"n": 1}, ttl=60, wait=5)
        self.assertEqual(value, {"n": 1})
        self.assertLess(age, 1)

    def test_a_stale_copy_is_served_at_once_and_refreshed_in_the_background(self):
        live.get("a", lambda: {"n": 1}, ttl=60, wait=5)
        live._entries["a"].at -= 120  # two minutes old
        release = threading.Event()

        def slow():
            release.wait(5)
            return {"n": 2}
        started = time.monotonic()
        value, _ = live.get("a", slow, ttl=60, wait=5)
        self.assertLess(time.monotonic() - started, 1)  # didn't wait for the slow source
        self.assertEqual(value, {"n": 1})
        release.set()
        live._entries["a"].thread.join(5)
        self.assertEqual(live.get("a", slow, ttl=60)[0], {"n": 2})

    def test_block_waits_for_a_fresh_copy(self):
        live.get("p", lambda: 1, ttl=60, wait=5)
        live._entries["p"].at -= 120
        self.assertEqual(live.get("p", lambda: 2, ttl=60, wait=5, block=True)[0], 2)

    def test_a_failed_refresh_keeps_the_last_good_copy(self):
        live.get("a", lambda: "good", ttl=60, wait=5)
        live.expire()

        def broken():
            raise OSError("provider down")
        self.assertEqual(live.get("a", broken, ttl=60, wait=5, block=True)[0], "good")
        self.assertIn("provider down", live.status()["a"][1])

    def test_no_copy_after_the_wait_returns_none_and_keeps_fetching(self):
        release = threading.Event()
        value, age = live.get("slow", lambda: release.wait(5) and "late", ttl=60, wait=0.05)
        self.assertEqual((value, age), (None, None))
        release.set()
        live._entries["slow"].thread.join(5)
        self.assertEqual(live.get("slow", lambda: "never", ttl=60)[0], "late")

    def test_views_get_copies(self):
        first, _ = live.get("d", lambda: {"rows": [1]}, ttl=60, wait=5)
        first["rows"].append(2)
        self.assertEqual(live.get("d", lambda: None, ttl=60)[0], {"rows": [1]})

    def test_warm_starts_only_missing_sources(self):
        calls = []
        live.get("have", lambda: 1, ttl=60, wait=5)
        live.warm({"have": lambda: calls.append("have"), "new": lambda: calls.append("new") or 2})
        live._entries["new"].thread.join(5)
        self.assertEqual(calls, ["new"])
