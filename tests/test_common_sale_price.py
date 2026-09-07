"""Reported sale prices use the issued-share denominator and net issuance cash."""
from dataclasses import replace
import math
import unittest

from report.calculations import calculate_company, common_average_sale_price
from report.historical_data import historical_report
from report.models import CommonCapital
from report.presentation import company_view


class CommonSalePriceTests(unittest.TestCase):
    def test_strategy_disclosure_uses_shares_sold_and_two_decimals(self):
        report = historical_report()
        strategy = report.companies[0]
        metrics = calculate_company(strategy, report.current_btc_price, report.prior_btc_price)
        self.assertAlmostEqual(common_average_sale_price(strategy.common_capital),
                               602_800_000 / 4_531_421)
        self.assertNotEqual(metrics.shares_change, strategy.common_capital.issued_shares)
        self.assertEqual(company_view(strategy, metrics).common.post_details,
                         ("4,531,421 shares sold · $133.03 avg. sale price",))

    def test_buybacks_and_separate_warrant_cash_do_not_change_sale_price(self):
        activity = CommonCapital(600, 0, False, 0, issued_shares=4)
        self.assertEqual(common_average_sale_price(activity), 150)
        for buybacks, warrants in ((100, 90), (None, None), (math.inf, math.inf)):
            with self.subTest(buybacks=buybacks, warrants=warrants):
                changed = replace(activity, buybacks_cash=buybacks,
                                  separately_reported_warrant_cash=warrants)
                self.assertEqual(common_average_sale_price(changed), 150)

    def test_invalid_or_missing_sale_inputs_do_not_produce_a_price(self):
        activity = CommonCapital(600, 0, issued_shares=4)
        for proceeds in (None, -1, math.nan, math.inf, -math.inf):
            with self.subTest(proceeds=proceeds):
                self.assertIsNone(common_average_sale_price(
                    replace(activity, issuance_proceeds_after_fees=proceeds)))
        for shares in (None, 0, -1, math.nan, math.inf, -math.inf):
            with self.subTest(shares=shares):
                self.assertIsNone(common_average_sale_price(replace(activity, issued_shares=shares)))
        self.assertIsNone(common_average_sale_price(replace(activity, issued_shares=1e-320)))
        self.assertEqual(common_average_sale_price(
            replace(activity, issuance_proceeds_after_fees=0)), 0)

    def test_missing_sale_inputs_do_not_render_an_invented_average(self):
        report = historical_report()
        strategy = report.companies[0]
        for changes in ({"issued_shares": None}, {"issued_shares": 0},
                        {"issuance_proceeds_after_fees": None},
                        {"issuance_proceeds_after_fees": math.inf}):
            with self.subTest(changes=changes):
                company = replace(strategy, common_capital=replace(strategy.common_capital, **changes))
                metrics = calculate_company(company, report.current_btc_price, report.prior_btc_price)
                details = company_view(company, metrics).common.post_details
                self.assertFalse(any("avg. sale price" in line for line in details))


if __name__ == "__main__":
    unittest.main()
