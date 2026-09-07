"""Current quote validation and cache transaction tests without network access."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from report import current_prices
from report.current_prices import (
    load_current_prices, parse_btc_quote, parse_yahoo_quote,
    pull_current_prices, save_current_prices,
)


NOW = datetime(2026, 9, 7, 16, 30, tzinfo=timezone.utc)
FRIDAY_CLOSE = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)
BTC_OBSERVED = datetime(2026, 9, 7, 16, 29, 45, 456000, tzinfo=timezone.utc)


def yahoo_payload(symbol="MSTR", price=142.80, observed=FRIDAY_CLOSE):
    return {"chart": {"error": None, "result": [{"meta": {
        "symbol": symbol, "regularMarketPrice": price,
        "regularMarketTime": observed.timestamp(),
        # These must not displace the requested regular-session observation.
        "postMarketPrice": 999.0, "previousClose": 111.0,
    }}]}}


def btc_payload(price=78_863.01, observed=BTC_OBSERVED):
    return {"results": {"ufPrice": price, "msTimestamp": observed.timestamp() * 1000},
            "timestamp": NOW.isoformat()}


def valid_snapshot():
    quotes = {symbol: parse_yahoo_quote(yahoo_payload(symbol), symbol, NOW)
              for symbol in ("MSTR", "ASST", "STRC", "EURUSD=X")}
    quotes["BTC-USD"] = parse_btc_quote(btc_payload(), NOW)
    return {"schema_version": 1, "fetched_at": NOW.isoformat(), "quotes": quotes}


class CurrentPriceTests(unittest.TestCase):
    def test_regular_quote_preserves_friday_close_time_and_source_identity(self):
        quote = parse_yahoo_quote(yahoo_payload(), "MSTR", NOW)
        self.assertEqual(quote["symbol"], "MSTR")
        self.assertEqual(quote["price"], 142.80)
        self.assertEqual(quote["as_of"], "2026-09-04T20:00:00+00:00")
        self.assertNotEqual(quote["as_of"], NOW.isoformat())
        self.assertEqual(quote["source_url"],
                         "https://query1.finance.yahoo.com/v8/finance/chart/MSTR?interval=1d&range=5d")
        fx = parse_yahoo_quote(yahoo_payload("EURUSD=X", 1.1643), "EURUSD=X", NOW)
        self.assertEqual(fx["price"], 1.1643)
        self.assertIn("EURUSD%3DX", fx["source_url"])

    def test_bitcoin_uses_millisecond_observation_not_response_generation_time(self):
        quote = parse_btc_quote(btc_payload(), NOW)
        self.assertEqual(quote["symbol"], "BTC-USD")
        self.assertEqual(quote["price"], 78_863.01)
        self.assertEqual(quote["as_of"], "2026-09-07T16:29:45.456000+00:00")
        self.assertEqual(quote["source_url"], "https://api.strategy.com/btc/bitcoinKpis")

    def test_missing_or_wrong_yahoo_identity_and_source_errors_fail(self):
        with self.assertRaisesRegex(ValueError, "symbol"):
            parse_yahoo_quote(yahoo_payload("ASST"), "MSTR", NOW)
        missing_symbol = yahoo_payload()
        del missing_symbol["chart"]["result"][0]["meta"]["symbol"]
        for payload in (None, {}, missing_symbol, {"chart": {"result": []}},
                        {"chart": {"result": None, "error": {"description": "missing"}}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_yahoo_quote(payload, "MSTR", NOW)
        with self.assertRaises(ValueError):
            parse_yahoo_quote(yahoo_payload("OTHER"), "OTHER", NOW)
        for payload in (None, {}, {"results": {}}, {"results": None}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_btc_quote(payload, NOW)

    def test_prices_must_be_positive_finite_numeric_values(self):
        for price in (None, 0, -1, math.nan, math.inf, -math.inf, "142.80", True, 10 ** 400):
            with self.subTest(price=price):
                with self.assertRaises(ValueError):
                    parse_yahoo_quote(yahoo_payload(price=price), "MSTR", NOW)
                with self.assertRaises(ValueError):
                    parse_btc_quote(btc_payload(price=price), NOW)

    def test_epoch_timestamps_reject_missing_nonfinite_and_excessive_future_values(self):
        for stamp in (None, 0, -1, math.nan, math.inf, "1788797394", True, 1e300):
            with self.subTest(stamp=stamp):
                yahoo = yahoo_payload()
                yahoo["chart"]["result"][0]["meta"]["regularMarketTime"] = stamp
                btc = btc_payload()
                btc["results"]["msTimestamp"] = stamp
                with self.assertRaises(ValueError):
                    parse_yahoo_quote(yahoo, "MSTR", NOW)
                with self.assertRaises(ValueError):
                    parse_btc_quote(btc, NOW)
        for seconds in (60, 61):
            future = NOW + timedelta(seconds=seconds)
            for parser, payload in (
                (lambda value: parse_yahoo_quote(value, "MSTR", NOW), yahoo_payload(observed=future)),
                (lambda value: parse_btc_quote(value, NOW), btc_payload(observed=future)),
            ):
                with self.subTest(seconds=seconds):
                    if seconds == 60:
                        self.assertEqual(parser(payload)["as_of"], future.isoformat())
                    else:
                        with self.assertRaisesRegex(ValueError, "future"):
                            parser(payload)
        with self.assertRaisesRegex(ValueError, "timezone"):
            parse_btc_quote(btc_payload(), NOW.replace(tzinfo=None))

    def test_pull_requires_five_quotes_and_uses_bounded_requests_without_saving(self):
        payloads = {current_prices.SOURCE_URLS[symbol]: yahoo_payload(symbol)
                    for symbol in current_prices.YAHOO_SYMBOLS}
        payloads[current_prices.SOURCE_URLS["BTC-USD"]] = btc_payload()
        requests = []

        def response(request, timeout):
            requests.append((request, timeout))
            return BytesIO(json.dumps(payloads[request.full_url]).encode("utf-8"))

        with patch("report.current_prices.urlopen", side_effect=response), \
             patch("report.current_prices.save_current_prices") as save:
            snapshot = pull_current_prices(now=NOW)
        self.assertEqual(set(snapshot["quotes"]), {"MSTR", "ASST", "STRC", "EURUSD=X", "BTC-USD"})
        self.assertEqual(snapshot["fetched_at"], NOW.isoformat())
        self.assertEqual(snapshot["quotes"]["MSTR"]["as_of"], FRIDAY_CLOSE.isoformat())
        self.assertEqual(len(requests), 5)
        for request, timeout in requests:
            self.assertEqual(timeout, 20)
            self.assertTrue(request.get_header("User-agent"))
        save.assert_not_called()

    def test_one_failed_or_malformed_source_prevents_refresh_and_preserves_old_cache(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "current-prices.json"
            save_current_prices(valid_snapshot(), path, now=NOW)
            original = path.read_bytes()
            for failure in ("network", "malformed"):
                def source(url):
                    symbol = next(symbol for symbol, value in current_prices.SOURCE_URLS.items() if value == url)
                    if symbol == "ASST":
                        if failure == "network":
                            raise OSError("source offline")
                        return yahoo_payload("WRONG")
                    return btc_payload() if symbol == "BTC-USD" else yahoo_payload(symbol)

                with self.subTest(failure=failure), patch("report.current_prices._fetch_json", side_effect=source):
                    with self.assertRaises((OSError, ValueError)):
                        snapshot = pull_current_prices(now=NOW)
                        save_current_prices(snapshot, path, now=NOW)
                self.assertEqual(path.read_bytes(), original)

    def test_cache_rejects_incomplete_mislabeled_invalid_and_future_data_before_writing(self):
        invalid = []
        for field, value in (("price", math.nan), ("price", -1), ("symbol", "OTHER"),
                             ("source_url", ""), ("as_of", NOW.replace(tzinfo=None).isoformat()),
                             ("as_of", (NOW + timedelta(seconds=61)).isoformat())):
            snapshot = valid_snapshot()
            snapshot["quotes"]["ASST"][field] = value
            invalid.append(snapshot)
        missing = valid_snapshot()
        del missing["quotes"]["STRC"]
        invalid.extend((missing, {**valid_snapshot(), "quotes": {}},
                        {**valid_snapshot(), "schema_version": True},
                        {**valid_snapshot(), "fetched_at": NOW.replace(tzinfo=None).isoformat()},
                        {**valid_snapshot(), "fetched_at": (NOW + timedelta(seconds=61)).isoformat()}))
        extra = valid_snapshot()
        extra["quotes"]["OTHER"] = deepcopy(extra["quotes"]["ASST"])
        invalid.append(extra)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "current-prices.json"
            save_current_prices(valid_snapshot(), path, now=NOW)
            original = path.read_bytes()
            for snapshot in invalid:
                with self.subTest(snapshot=snapshot), self.assertRaises(ValueError):
                    save_current_prices(snapshot, path, now=NOW)
                self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_load_accepts_old_observations_and_normalizes_aware_offsets(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "current-prices.json"
            self.assertIsNone(load_current_prices(path, now=NOW))
            snapshot = valid_snapshot()
            snapshot["quotes"]["MSTR"]["as_of"] = "2026-08-07T16:00:00-04:00"
            save_current_prices(snapshot, path, now=NOW)
            loaded = load_current_prices(path, now=NOW + timedelta(days=90))
            self.assertEqual(loaded["quotes"]["MSTR"]["as_of"], "2026-08-07T20:00:00+00:00")
            self.assertEqual(loaded["fetched_at"], NOW.isoformat())
            # Loading independently validates disk contents too.
            snapshot["quotes"]["MSTR"]["price"] = 0
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_current_prices(path, now=NOW)

    def test_failed_atomic_replace_preserves_good_cache_and_cleans_pending_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "current-prices.json"
            save_current_prices(valid_snapshot(), path, now=NOW)
            original = path.read_bytes()
            changed = valid_snapshot()
            changed["quotes"]["ASST"]["price"] = 23.0
            with patch("report.current_prices.Path.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    save_current_prices(changed, path, now=NOW)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
