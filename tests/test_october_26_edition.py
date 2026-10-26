"""The first settled SATS offering must enter both funding and senior claims."""
import json
from pathlib import Path
import unittest

from panels import extras, monday_preview
from report.calculations import calculate_company
from report.current_prices import load_current_prices
from report.live_report import activity_week_start, resolve_live_report

ROOT = Path(__file__).resolve().parents[1]


class October26EditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prices = load_current_prices()
        cls.feed = json.loads((ROOT / "data/latest-report-filings.json").read_text())
        cls.result = resolve_live_report(cls.prices, cls.feed, through_date="2026-10-25")
        cls.preview = monday_preview.build_preview(cls.result.report, cls.prices, cls.feed,
                                                  extras.load_extras(offline=True))

    def test_settled_sats_cash_is_distinct_from_its_senior_claim(self):
        company = next(c for c in self.result.report.companies if c.ticker == "ASST")
        metric = calculate_company(company, self.result.report.current_btc_price,
                                   self.result.report.prior_btc_price)
        self.assertEqual(company.balance_date, "2026-10-23")
        self.assertEqual(company.current.btc_holdings, 43_000)
        self.assertEqual(company.current.diluted_shares, 130_044_690)
        self.assertEqual(company.current.preferred_claims, 2_104_267_600)
        self.assertEqual(metric.net_preferred_capital, 609_000_000)
        self.assertEqual(self.preview.extras["ASST"].btc_cost, 511_430_832)
        self.assertEqual(self.preview.extras["ASST"].reported_btc_purchase_price, 82_732)

    def test_sats_coupon_counts_in_coverage_and_notional_in_amplification(self):
        e = self.preview.extras["ASST"]
        bitcoin = 43_000 * self.result.report.current_btc_price
        self.assertAlmostEqual(e.breakeven_pct, 287_392_288 / bitcoin * 100)
        self.assertAlmostEqual(e.amplification_pct, 2_103_017_600 / bitcoin * 100)

    def test_both_funding_waterfalls_reconcile(self):
        self.assertIsNone(self.result.notice)
        for ticker, e in self.preview.extras.items():
            with self.subTest(ticker=ticker):
                money_in, money_out = monday_preview.funding_flows(e)
                self.assertAlmostEqual(sum(v for _, v, _ in money_in),
                                       sum(v for _, v, _ in money_out), places=2)
        mstr = self.preview.extras["MSTR"]
        self.assertEqual(mstr.btc_bought, 0)
        self.assertEqual(mstr.preferred_out, 204_900_000)
        self.assertEqual(mstr.dividends, 0)

    def test_weekend_start_belongs_to_the_following_trading_week(self):
        self.assertEqual(activity_week_start({"periodStart": "2026-10-17"}), "2026-10-19")
        self.assertEqual(activity_week_start({"periodStart": "2026-10-18"}), "2026-10-19")
        self.assertEqual(activity_week_start({"periodStart": "2026-10-19"}), "2026-10-19")
        self.assertEqual(activity_week_start({"periodStart": "2026-10-13"}), "2026-10-12")


if __name__ == "__main__":
    unittest.main()
