"""Reported average repurchase prices retain their gross-cash basis."""

from dataclasses import replace
import math
import unittest

from report.calculations import calculate_company
from report.historical_data import historical_report
from report.models import PreferredActivity
from report.presentation import build_report_view, company_view


class PreferredDisplayTests(unittest.TestCase):
    def setUp(self):
        self.report = historical_report()
        self.strategy = self.report.companies[0]

    def preferred_view(self, activity):
        company = replace(self.strategy, preferred_activity=(activity,))
        metrics = calculate_company(company, self.report.current_btc_price, self.report.prior_btc_price)
        return company_view(company, metrics).preferred, metrics

    def assert_average_follows_count(self, view, count, price):
        for layout, lines in (("detail", view.details), ("post", view.post_details)):
            with self.subTest(layout=layout):
                count_index = next(index for index, line in enumerate(lines)
                                   if count in line and "repurchased" in line)
                self.assertLess(count_index + 1, len(lines))
                average_line = lines[count_index + 1]
                self.assertIn(price, average_line)
                self.assertIn("price", average_line.lower())
                self.assertNotIn("VWAP", average_line)

    def test_historical_strc_average_is_directly_below_repurchase_count_in_both_layouts(self):
        view = build_report_view(self.report).companies[0].preferred
        self.assertEqual(round(151_800_000 / 1_557_177, 2), 97.48)
        self.assert_average_follows_count(view, "1,557,177", "$97.48")
        self.assertEqual(view.value, "−$151.8m")

    def test_reported_average_uses_gross_buyback_cash_even_with_issuance_and_other_price_inputs(self):
        activity = PreferredActivity(
            "STRC", 200.0, 10.0, capital_method="reported",
            reported_issuance_proceeds=16_000.0, reported_repurchases_cash=975.0,
            prior_week_vwap=77.0, issuance_price_assumption=100.0, fees=25.0,
        )
        view, metrics = self.preferred_view(activity)
        self.assert_average_follows_count(view, "10", "$97.50")
        self.assertEqual(metrics.net_preferred_capital, 15_025.0)
        self.assertNotEqual(975 / 10, abs(metrics.net_preferred_capital) / 10)
        # Missing issuance cash does not hide a separately calculable buyback average.
        view, metrics = self.preferred_view(replace(activity, reported_issuance_proceeds=None))
        self.assert_average_follows_count(view, "10", "$97.50")
        self.assertIsNone(metrics.net_preferred_capital)

    def test_unknown_or_invalid_repurchase_inputs_do_not_invent_an_average(self):
        activity = PreferredActivity("STRC", 0.0, 10.0, capital_method="reported",
                                     reported_issuance_proceeds=0.0, reported_repurchases_cash=975.0)
        for field, values in (("repurchased_shares", (None, 0.0, -1.0, math.nan, math.inf)),
                              ("reported_repurchases_cash", (None, -1.0, math.nan, math.inf))):
            for value in values:
                with self.subTest(field=field, value=value):
                    view, _ = self.preferred_view(replace(activity, **{field: value}))
                    for lines in (view.details, view.post_details):
                        self.assertFalse(any("price" in line.lower() for line in lines), lines)
                        self.assertNotIn("$97.50", " ".join(lines))

    def test_explicit_zero_cash_is_distinct_from_modeled_market_vwap(self):
        reported = PreferredActivity("STRC", 0.0, 10.0, capital_method="reported",
                                     reported_issuance_proceeds=0.0, reported_repurchases_cash=0.0)
        view, _ = self.preferred_view(reported)
        self.assert_average_follows_count(view, "10", "$0.00")
        modeled = replace(reported, capital_method="modeled", reported_repurchases_cash=None,
                          prior_week_vwap=97.5)
        view, _ = self.preferred_view(modeled)
        for lines in (view.details, view.post_details):
            self.assertIn("VWAP", " ".join(lines))
            self.assertNotIn("Avg. repurchase price", " ".join(lines))


if __name__ == "__main__":
    unittest.main()
