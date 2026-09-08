"""Historical-window and estimate checks, with no network dependency."""

from datetime import date, datetime, timezone
import importlib.util
import math
import unittest
from unittest.mock import patch

from report.equity_vwap import parse_estimate, pull_estimate, select_sessions


SESSIONS = [{"date": "2026-08-28", "open": "2026-08-28T13:30:00+00:00",
             "close": "2026-08-28T13:32:00+00:00"}]
START = int(datetime(2026, 8, 28, 13, 30, tzinfo=timezone.utc).timestamp())


def payload(stamps=None, highs=None, lows=None, closes=None, volumes=None):
    return {"chart": {"error": None, "result": [{
        "meta": {"symbol": "ASST", "dataGranularity": "1m", "currency": "USD"},
        "timestamp": stamps if stamps is not None else [START, START + 60],
        "indicators": {"quote": [{"open": list(closes) if closes is not None else [10, 20],
                                   "high": highs if highs is not None else [12, 22],
                                   "low": lows if lows is not None else [8, 18],
                                   "close": closes if closes is not None else [10, 20],
                                   "volume": volumes if volumes is not None else [1, 3]}]},
    }]}}


def summarize(data, sessions=SESSIONS):
    return parse_estimate(data, sessions, symbol="ASST", edition_date=date(2026, 8, 31), window="prior_week")


class EquityVwapTests(unittest.TestCase):
    def test_five_minute_estimate_requires_complete_grid_and_labels_resolution(self):
        session = [{"date": "2026-08-28", "open": "2026-08-28T13:30:00+00:00",
                    "close": "2026-08-28T13:40:00+00:00"}]
        data = payload(stamps=[START, START + 300])
        data["chart"]["result"][0]["meta"]["dataGranularity"] = "5m"
        kwargs = dict(symbol="ASST", edition_date=date(2026, 8, 31), window="prior_week", interval="5m")
        estimate = parse_estimate(data, session, **kwargs)
        self.assertEqual(estimate["value"], 17.5)
        self.assertEqual(estimate["method"], "hlc3_5m")
        self.assertEqual(estimate["label"], "5-minute VWAP estimate")
        data["chart"]["result"][0]["timestamp"][1] = START + 60
        with self.assertRaisesRegex(ValueError, "grid"):
            parse_estimate(data, session, **kwargs)

    def test_uses_minute_hlc3_and_unequal_volume_weights(self):
        result = summarize(payload(closes=[12, 18]))
        self.assertAlmostEqual(result["value"], ((12 + 8 + 12) / 3 + (22 + 18 + 18)) / 4)
        self.assertNotEqual(result["value"], (12 + 18 * 3) / 4)
        self.assertEqual(result["total_volume"], 4)
        self.assertEqual(result["method"], "hlc3_1m")
        self.assertEqual(result["bar_count"], 2)
        numerator = sum((bar["high"] + bar["low"] + bar["close"]) / 3 * bar["volume"] for bar in result["bars"])
        self.assertAlmostEqual(result["value"], numerator / result["total_volume"])

    def test_stray_quote_after_cutoff_is_excluded_before_price_validation(self):
        result = summarize(payload([START, START + 60, START + 7 * 86400],
                                   [12, 22, None], [8, 18, None], [10, 20, None], [1, 3, -1]))
        self.assertEqual(result["value"], 17.5)
        self.assertEqual(result["excluded_bar_count"], 1)
        self.assertEqual(result["session_end"], "2026-08-28")
        self.assertEqual([bar["timestamp"] for bar in result["bars"]], [START, START + 60])

    def test_missing_minute_or_entire_session_is_unavailable(self):
        with self.assertRaisesRegex(ValueError, "1 expected minute"):
            summarize(payload([START], [12], [8], [10], [1]))
        prior = {"date": "2026-08-27", "open": "2026-08-27T13:30:00+00:00",
                 "close": "2026-08-27T13:32:00+00:00"}
        with self.assertRaisesRegex(ValueError, "2 expected minute"):
            summarize(payload(), [prior, *SESSIONS])

    def test_invalid_prices_volume_and_duplicates_are_rejected(self):
        for field in ("open", "high", "low", "close", "volume"):
            for invalid in (None, math.nan, math.inf, -1):
                with self.subTest(field=field, invalid=invalid):
                    data = payload()
                    data["chart"]["result"][0]["indicators"]["quote"][0][field][0] = invalid
                    with self.assertRaises(ValueError):
                        summarize(data)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            summarize([payload(), payload()])
        with self.assertRaisesRegex(ValueError, "positive trading volume"):
            summarize(payload(volumes=[0, 0]))

    def test_same_window_fallback_does_not_requery_or_fill_missing_data(self):
        with patch("report.equity_vwap.select_sessions", return_value=SESSIONS), \
             patch("report.equity_vwap._fetch_window", side_effect=ValueError("Missing data")) as fetch:
            with self.assertRaisesRegex(ValueError, "same window"):
                pull_estimate("ASST", date(2026, 8, 31))
            self.assertEqual(fetch.call_count, 1)

    def test_distinct_fallback_preserves_actual_window_and_reason(self):
        prior = [{"date": "2026-08-27", "open": "2026-08-27T13:30:00+00:00",
                  "close": "2026-08-27T13:32:00+00:00"}]
        with patch("report.equity_vwap.select_sessions", side_effect=[prior, SESSIONS]), \
             patch("report.equity_vwap._fetch_window", side_effect=[ValueError("History unavailable"), ([payload()], ["https://example.test/data"])]):
            result = pull_estimate("ASST", date(2026, 8, 31))
        self.assertEqual(result["window"], "five_sessions")
        self.assertEqual(result["fallback_reason"], "History unavailable")
        self.assertEqual(result["request_urls"], ["https://example.test/data"])
        self.assertEqual(result["sessiondates"], ["2026-08-28"])

    @unittest.skipUnless(importlib.util.find_spec("exchange_calendars"), "exchange_calendars not installed")
    def test_calendar_holiday_and_five_session_windows_are_distinct(self):
        prior = select_sessions(date(2026, 7, 6), "prior_week")
        five = select_sessions(date(2026, 7, 6), "five_sessions")
        self.assertEqual([item["date"] for item in prior], ["2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02"])
        self.assertEqual([item["date"] for item in five], ["2026-06-26", "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02"])
        self.assertEqual(len(select_sessions(date(2026, 8, 31), "prior_week")), 5)


if __name__ == "__main__":
    unittest.main()
