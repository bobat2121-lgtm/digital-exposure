"""Period growth uses basic shares and identical market marks, with no network."""

from copy import deepcopy
from dataclasses import replace
import math
import unittest
from unittest.mock import patch

from report.current_report import current_report
from report.historical_data import historical_report
from report.models import Snapshot
from report.period_growth import calculate_period_growth, get_period_growth
from report.sample_data import sample_report


def prices():
    values = {"MSTR": 150.0, "ASST": 30.0, "STRC": 100.0, "EURUSD=X": 1.2, "BTC-USD": 80_000.0}
    return {"fetched_at": "2026-09-07T20:00:00+00:00", "quotes": {
        symbol: {"symbol": symbol, "price": value, "as_of": "2026-09-04T20:00:00+00:00"}
        for symbol, value in values.items()}}


class PeriodGrowthTests(unittest.TestCase):
    def test_per_share_growth_accounts_for_dilution_and_preserves_precision(self):
        current = Snapshot(150, 12, 30, 0, 20, 10)
        baseline = Snapshot(100, 10, 20, 0, 20, 10)
        growth = calculate_period_growth(current, {"QTD": baseline, "YTD": baseline}, 2)
        for result in growth.values():
            self.assertEqual(result.btc_per_share_growth_pct, 25)
            expected_nav = ((300 / 12) / (190 / 10) - 1) * 100
            self.assertAlmostEqual(result.nav_per_share_growth_pct, expected_nav, places=12)
            self.assertNotEqual(result.nav_per_share_growth_pct, round(result.nav_per_share_growth_pct, 2))
            self.assertFalse(result.nav_not_meaningful)

    def test_identical_balances_at_identical_current_marks_have_zero_growth(self):
        # Both snapshots contain 505 securities marked at the same supplied
        # price and a euro liability marked at the same supplied FX rate.
        for btc, security, fx in ((2.0, 90.0, 1.1), (3.0, 110.0, 1.3)):
            snapshot = Snapshot(100, 10, 20, 505 * security, 0, 50 * fx)
            result = calculate_period_growth(snapshot, {"QTD": snapshot}, btc)["QTD"]
            self.assertEqual(result.btc_per_share_growth_pct, 0)
            self.assertEqual(result.nav_per_share_growth_pct, 0)

    def test_missing_nav_inputs_preserve_independent_bitcoin_growth(self):
        current = Snapshot(150, 12, 30, 0, 20, 10)
        baseline = Snapshot(100, 10, 20, None, 20, 10)
        result = calculate_period_growth(current, {"QTD": baseline}, 2)
        self.assertEqual(result["QTD"].btc_per_share_growth_pct, 25)
        self.assertIsNone(result["QTD"].nav_per_share_growth_pct)
        self.assertFalse(result["QTD"].nav_not_meaningful)
        self.assertIsNone(result["YTD"].btc_per_share_growth_pct)
        no_price = calculate_period_growth(current, {"QTD": replace(baseline, marketable_securities=0)}, None)["QTD"]
        self.assertEqual(no_price.btc_per_share_growth_pct, 25)
        self.assertIsNone(no_price.nav_per_share_growth_pct)

    def test_nonpositive_nav_is_not_meaningful_while_bad_denominators_are_missing(self):
        positive = Snapshot(100, 10, 0, 0, 0, 0)
        for amount in (100, 101):
            nonpositive = replace(positive, preferred_claims=amount)
            for current, baseline in ((positive, nonpositive), (nonpositive, positive)):
                result = calculate_period_growth(current, {"QTD": baseline}, 1)["QTD"]
                self.assertTrue(result.nav_not_meaningful)
                self.assertIsNone(result.nav_per_share_growth_pct)
                self.assertEqual(result.btc_per_share_growth_pct, 0)
        for shares in (None, 0, -1, math.nan, math.inf):
            with self.subTest(shares=shares):
                result = calculate_period_growth(positive, {"QTD": replace(positive, effective_common_shares=shares)}, 1)["QTD"]
                self.assertIsNone(result.btc_per_share_growth_pct)
                self.assertIsNone(result.nav_per_share_growth_pct)
        empty = replace(positive, btc_holdings=0)
        self.assertIsNone(calculate_period_growth(positive, {"QTD": empty}, 1)["QTD"].btc_per_share_growth_pct)
        self.assertEqual(calculate_period_growth(empty, {"QTD": positive}, 1)["QTD"].btc_per_share_growth_pct, -100)

    def test_illustrative_report_never_uses_real_baselines_or_loads_quotes(self):
        with patch("report.period_growth._strategy_baselines") as strategy, \
             patch("report.period_growth._strive_baselines") as strive, \
             patch("report.period_growth.load_current_prices") as load:
            self.assertEqual(get_period_growth(sample_report()), {})
        strategy.assert_not_called()
        strive.assert_not_called()
        load.assert_not_called()

    def test_provider_wiring_uses_current_or_historical_marks_without_mutating_reports(self):
        quotes = prices()
        current = current_report(quotes)
        historical = historical_report()
        baseline = Snapshot(100, 10, 20, 0, 0, 10)
        with patch("report.period_growth._strategy_baselines", return_value={"QTD": baseline, "YTD": baseline}) as strategy, \
             patch("report.period_growth._strive_baselines", return_value={"QTD": baseline, "YTD": baseline}) as strive:
            result = get_period_growth(current, quotes)
            strategy.assert_called_once_with(80_000, 1.2)
            strive.assert_called_once_with(100)
            self.assertEqual(set(result), {"MSTR", "ASST"})
            self.assertEqual(set(result["MSTR"]), {"QTD", "YTD"})
            strategy.reset_mock()
            strive.reset_mock()
            get_period_growth(historical, quotes)
            strategy.assert_called_once_with(78_414.14, 1.1643)
            strive.assert_called_once_with(49_152_000 / 505_000)
        self.assertEqual(historical_report(), historical)
        self.assertEqual(current_report(quotes), current)

    def test_mismatched_refresh_snapshot_cannot_mix_market_marks(self):
        quotes = prices()
        report = current_report(quotes)
        for symbol in ("BTC-USD", "STRC", "EURUSD=X"):
            changed = deepcopy(quotes)
            changed["quotes"][symbol]["price"] *= 1.01
            with self.subTest(symbol=symbol), self.assertRaisesRegex(ValueError, "do not match"):
                get_period_growth(report, changed)

    def test_actual_dated_baselines_match_independent_period_reconciliation(self):
        quotes = prices()
        result = get_period_growth(current_report(quotes), quotes)
        # Reconciled independently at BTC $80,000, STRC $100 and EUR/USD 1.20.
        # June/December basic-share denominators and liability schedules come
        # from the dated baseline source audit, not EPS weighted-average shares.
        expected = {
            "MSTR": {"QTD": (-11.723728620563223, -2.7490359571840206),
                     "YTD": (-6.742758979943475, -1.7385561868589083)},
            "ASST": {"QTD": (2.4261852218935287, 3.371448962543413),
                     "YTD": (45.558976564617204, 18.9106370123344)},
        }
        for ticker, periods in expected.items():
            for period, (bitcoin, nav) in periods.items():
                with self.subTest(ticker=ticker, period=period):
                    self.assertAlmostEqual(result[ticker][period].btc_per_share_growth_pct, bitcoin, places=10)
                    self.assertAlmostEqual(result[ticker][period].nav_per_share_growth_pct, nav, places=10)
                    self.assertFalse(result[ticker][period].nav_not_meaningful)


if __name__ == "__main__":
    unittest.main()
