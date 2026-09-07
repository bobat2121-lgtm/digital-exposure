"""Period-basis checks anchored to Strive's June 2026 10-Q disclosures."""

import unittest

from report.strive_period_baselines import strive_period_baselines


class StrivePeriodBaselineTests(unittest.TestCase):
    def test_uses_reported_common_not_eps_or_prefunded_denominators(self):
        baselines = strive_period_baselines(100)
        self.assertEqual(baselines["QTD"].effective_common_shares, 81_944_827)
        self.assertEqual(baselines["YTD"].effective_common_shares, 44_713_285)
        self.assertEqual(baselines["QTD"].preferred_claims, 782_950_200)
        self.assertAlmostEqual(baselines["YTD"].preferred_claims, 202_300_230.42708333)

    def test_only_elapsed_dividends_are_included_in_liquidation_claims(self):
        baselines = strive_period_baselines(100)
        # June 30 is after that day's settled dividend. The June 30 GAAP
        # payable is not a second accumulated claim at this payment boundary.
        self.assertEqual(baselines["QTD"].preferred_claims - 782_950_200, 0)
        # December 31 is halfway through the 30-day Dec 16–Jan 15 period;
        # it must not include the complete declared January payment.
        accrued = baselines["YTD"].preferred_claims - 201_272_900
        self.assertAlmostEqual(accrued, 1_027_330.4270833333)
        self.assertLess(accrued, 2_053_000)

    def test_current_price_revalues_only_the_disclosed_strc_portfolio(self):
        lower = strive_period_baselines(90)
        higher = strive_period_baselines(100)
        self.assertEqual(
            higher["QTD"].marketable_securities - lower["QTD"].marketable_securities,
            5_050_000,
        )
        self.assertEqual(lower["YTD"], higher["YTD"])
        self.assertEqual(lower["QTD"].cash, higher["QTD"].cash)
        self.assertEqual(lower["QTD"].preferred_claims, higher["QTD"].preferred_claims)

    def test_missing_quote_is_not_a_zero_position(self):
        baselines = strive_period_baselines(None)
        self.assertIsNone(baselines["QTD"].marketable_securities)
        self.assertEqual(baselines["YTD"].marketable_securities, 0)

    def test_nonfinite_or_negative_quote_cannot_create_a_nav(self):
        for price in (float("nan"), float("inf"), -1):
            with self.subTest(price=price), self.assertRaises(ValueError):
                strive_period_baselines(price)


if __name__ == "__main__":
    unittest.main()
