"""Focused checks of normalized finance rules, independent of presentation."""

from dataclasses import replace
import math
import unittest

from report.calculations import (
    calculate_common_capital,
    calculate_company,
    calculate_preferred_capital,
    liquid_assets,
    net_treasury_nav,
    preferred_activity_capital,
    weekly_vwap,
)
from report.models import CommonCapital, PreferredActivity, Snapshot, Trade
from report.presentation import build_report_view, company_view, number
from report.sample_data import sample_report


class CalculationTests(unittest.TestCase):
    def setUp(self):
        self.report = sample_report()
        self.strategy, self.strive = self.report.companies

    def metrics(self, company):
        return calculate_company(company, self.report.current_btc_price, self.report.prior_btc_price)

    def test_fixture_matches_every_expected_metric(self):
        expected = (
            (self.strategy, (125.60, 1.19, 600e6, -150e6, 201190, 0.11, 1.28, -0.016, 21.89, -0.93, -160e6)),
            (self.strive, (12.56, 2.23, 99e6, 80e6, 24681, 2.88, 1.57, -0.001, 49.03, -0.69, 80e6)),
        )
        for company, values in expected:
            with self.subTest(company=company.name):
                metrics = self.metrics(company)
                actual = (
                    round(metrics.nav_per_share, 2),
                    round(metrics.price_to_nav, 2),
                    metrics.net_common_capital,
                    metrics.net_preferred_capital,
                    round(metrics.sats_per_share),
                    round(metrics.constant_price_nav_change_pct, 2),
                    round(metrics.net_btc_amplification, 2),
                    round(metrics.amplification_change, 3),
                    round(metrics.preferred_to_btc_pct, 2),
                    round(metrics.preferred_to_btc_change_pp, 2),
                    metrics.preferred_claims_change,
                )
                self.assertEqual(actual, values)

    def test_conceptual_cash_investment_keeps_nav_and_changes_distinct_ratios(self):
        before = Snapshot(100.0, 1.0, 50.0, 0.0, 0.0, 50.0)
        after = replace(before, btc_holdings=150.0, cash=0.0)
        company = replace(self.strategy, current=after, prior=before, prior_securities_at_current_prices=0.0)
        metrics = calculate_company(company, 1.0, 1.0)
        self.assertEqual(metrics.net_nav, 100.0)
        self.assertEqual(metrics.prior_net_nav, 100.0)
        self.assertEqual(metrics.prior_net_btc_amplification, 1.0)
        self.assertEqual(metrics.net_btc_amplification, 1.5)
        self.assertEqual(metrics.prior_preferred_to_btc_pct, 50.0)
        self.assertAlmostEqual(metrics.preferred_to_btc_pct, 100 / 3)
        self.assertEqual(metrics.constant_price_nav_change_pct, 0.0)

    def test_prior_edition_uses_its_own_bitcoin_price_for_amplification(self):
        metrics = self.metrics(self.strategy)
        prior_btc = 840_400 * 78_000
        prior_nav = prior_btc + 6_670e6 - 6_750e6 - 14_960e6
        self.assertAlmostEqual(metrics.prior_net_btc_amplification, prior_btc / prior_nav)
        wrong_price = calculate_company(self.strategy, 80_000, 80_000)
        self.assertNotAlmostEqual(metrics.amplification_change, wrong_price.amplification_change)

    def test_constant_price_change_is_independent_of_prior_btc_price(self):
        metrics = self.metrics(self.strive)
        changed_prior_price = calculate_company(self.strive, 80_000, 10_000)
        self.assertEqual(metrics.constant_price_nav_change_pct, changed_prior_price.constant_price_nav_change_pct)
        prior_constant_nav = 21_400 * 80_000 + 172e6 + 50e6 - 830e6
        expected = ((1181e6 / 94e6) / (prior_constant_nav / 90.4e6) - 1) * 100
        self.assertAlmostEqual(metrics.constant_price_nav_change_pct, expected)

    def test_constant_price_change_reprices_other_securities(self):
        before = Snapshot(100.0, 10.0, 0.0, 100.0, 0.0, 0.0)
        after = replace(before, marketable_securities=200.0)
        company = replace(self.strategy, current=after, prior=before, prior_securities_at_current_prices=200.0)
        metrics = calculate_company(company, 1.0, 1.0)
        self.assertEqual(metrics.constant_price_nav_change_pct, 0.0)
        missing_revaluation = self.metrics(replace(company, prior_securities_at_current_prices=None))
        self.assertIsNone(missing_revaluation.constant_price_nav_change_pct)

    def test_combined_reserve_rejects_overlapping_balances_and_invalid_totals(self):
        combined = Snapshot(100.0, 10.0, None, None, 20.0, 30.0, 70.0)
        self.assertEqual(liquid_assets(combined), 70.0)
        for balances in ({"cash": 50.0}, {"marketable_securities": 20.0},
                         {"cash": 50.0, "marketable_securities": 20.0}, {"cash": 0.0}):
            with self.subTest(balances=balances):
                ambiguous = replace(combined, **balances)
                self.assertIsNone(liquid_assets(ambiguous))
                self.assertIsNone(net_treasury_nav(ambiguous, 1.0))
        for amount in (-1.0, math.nan, math.inf):
            with self.subTest(amount=amount):
                self.assertIsNone(liquid_assets(replace(combined, combined_liquid_assets=amount)))
        self.assertIsNone(liquid_assets(replace(combined, combined_liquid_assets=None)))

    def test_combined_and_split_assets_produce_identical_nav_with_explicit_repricing(self):
        prior = Snapshot(100.0, 10.0, 30.0, 40.0, 20.0, 30.0)
        current = replace(prior, marketable_securities=50.0)
        split = replace(self.strategy, current=current, prior=prior,
                        prior_securities_at_current_prices=45.0)
        combined = replace(
            split,
            current=replace(current, cash=None, marketable_securities=None, combined_liquid_assets=80.0),
            prior=replace(prior, cash=None, marketable_securities=None, combined_liquid_assets=70.0),
            prior_securities_at_current_prices=None,
            prior_liquid_assets_at_current_prices=75.0,
        )
        split_metrics = calculate_company(split, 2.0, 1.0)
        self.assertEqual(calculate_company(combined, 2.0, 1.0), split_metrics)
        self.assertEqual(split_metrics.net_nav, 230.0)
        self.assertEqual(split_metrics.prior_net_nav, 120.0)
        self.assertEqual(split_metrics.prior_nav_per_share_at_current_prices, 22.5)

    def test_combined_reserve_without_explicit_repricing_preserves_nav_but_not_weekly_change(self):
        prior = Snapshot(100.0, 10.0, None, None, 20.0, 30.0, 70.0)
        company = replace(self.strategy, current=replace(prior, combined_liquid_assets=80.0),
                          prior=prior, prior_liquid_assets_at_current_prices=None)
        metrics = calculate_company(company, 2.0, 1.0)
        self.assertEqual(metrics.net_nav, 230.0)
        self.assertEqual(metrics.prior_net_nav, 120.0)
        self.assertIsNotNone(metrics.net_btc_amplification)
        self.assertIsNone(metrics.prior_nav_per_share_at_current_prices)
        self.assertIsNone(metrics.constant_price_nav_change_pct)

    def test_preferred_fx_repricing_only_changes_constant_price_comparison(self):
        snapshot = Snapshot(100.0, 10.0, 0.0, 0.0, 0.0, 50.0)
        company = replace(self.strategy, current=snapshot, prior=snapshot,
                          prior_securities_at_current_prices=0.0)
        original = calculate_company(company, 2.0, 1.0)
        repriced = calculate_company(replace(company, prior_preferred_claims_at_current_prices=60.0), 2.0, 1.0)
        self.assertEqual(original.prior_nav_per_share_at_current_prices, 15.0)
        self.assertEqual(repriced.prior_nav_per_share_at_current_prices, 14.0)
        self.assertAlmostEqual(repriced.constant_price_nav_change_pct, (15.0 / 14.0 - 1) * 100)
        for field in ("net_nav", "prior_net_nav", "nav_per_share", "prior_nav_per_share",
                      "net_btc_amplification", "prior_net_btc_amplification", "amplification_change",
                      "preferred_to_btc_pct", "prior_preferred_to_btc_pct",
                      "preferred_to_btc_change_pp", "preferred_claims_change"):
            with self.subTest(field=field):
                self.assertEqual(getattr(repriced, field), getattr(original, field))
        self.assertEqual(repriced.prior_net_btc_amplification, 2.0)
        self.assertEqual(repriced.prior_preferred_to_btc_pct, 50.0)

    def test_preferred_change_is_percentage_points(self):
        metrics = self.metrics(self.strive)
        self.assertAlmostEqual(metrics.preferred_to_btc_change_pp, metrics.preferred_to_btc_pct - metrics.prior_preferred_to_btc_pct)
        relative_pct = (metrics.preferred_to_btc_pct / metrics.prior_preferred_to_btc_pct - 1) * 100
        self.assertNotAlmostEqual(metrics.preferred_to_btc_change_pp, relative_pct)

    def test_net_common_capital_can_be_negative(self):
        activity = CommonCapital(10.0, 30.0, True)
        self.assertEqual(calculate_common_capital(activity), -20.0)

    def test_warrants_are_added_exactly_once(self):
        already_included = CommonCapital(110.0, 5.0, True, 10.0)
        separate = CommonCapital(100.0, 5.0, False, 10.0)
        self.assertEqual(calculate_common_capital(already_included), 105.0)
        self.assertEqual(calculate_common_capital(separate), 105.0)

    def test_warrant_unknown_and_confirmed_zero_are_distinct(self):
        self.assertIsNone(calculate_common_capital(CommonCapital(100.0, 0.0, False, None)))
        self.assertIsNone(calculate_common_capital(CommonCapital(100.0, 0.0, None, 0.0)))
        self.assertEqual(calculate_common_capital(CommonCapital(100.0, 0.0, False, 0.0)), 100.0)
        self.assertEqual(calculate_common_capital(CommonCapital(100.0, 0.0, True, None)), 100.0)

    def test_reported_atm_common_capital_has_explicit_scope_without_warrant_assertion(self):
        activity = CommonCapital(602.8e6, 0.0, None, 10e6)
        company = replace(self.strategy, common_capital=activity, common_capital_method="reported_atm")
        metrics = self.metrics(company)
        self.assertEqual(metrics.net_common_capital, 602.8e6)
        self.assertEqual(metrics.disclosed_net_common_capital, 602.8e6)
        self.assertEqual(metrics.common_issuance_cash, 602.8e6)
        self.assertFalse(metrics.common_capital_estimated)
        self.assertIsNone(calculate_common_capital(activity))
        self.assertIsNone(self.metrics(replace(company, common_capital_method="disclosed_cash")).net_common_capital)
        for field in ("issuance_proceeds_after_fees", "buybacks_cash"):
            for invalid in (None, -1.0, math.nan, math.inf):
                with self.subTest(field=field, invalid=invalid):
                    invalid_company = replace(company, common_capital=replace(activity, **{field: invalid}))
                    self.assertIsNone(self.metrics(invalid_company).net_common_capital)

    def test_unknown_common_components_do_not_become_zero(self):
        self.assertIsNone(calculate_common_capital(CommonCapital(None, 0.0, True)))
        self.assertIsNone(calculate_common_capital(CommonCapital(10.0, None, True)))
        self.assertIsNone(self.metrics(self.strive).disclosed_net_common_capital)

    def test_strive_common_capital_proxy_uses_net_new_shares_and_prior_week_vwap(self):
        metrics = self.metrics(self.strive)
        self.assertEqual(metrics.shares_change, 3.6e6)
        self.assertEqual(metrics.common_equity_vwap, 27.5)
        self.assertEqual(metrics.net_common_capital, 99e6)
        self.assertTrue(metrics.common_capital_estimated)
        self.assertIsNone(metrics.disclosed_net_common_capital)
        self.assertIsNone(metrics.common_issuance_cash)
        self.assertIsNone(metrics.common_buybacks_cash)
        self.assertFalse(self.metrics(self.strategy).common_capital_estimated)
        self.assertEqual(self.metrics(self.strategy).disclosed_net_common_capital, 600e6)

    def test_common_capital_proxy_requires_valid_vwap_without_spot_quote_fallback(self):
        for price in (None, 0.0, -27.5, math.nan, math.inf):
            with self.subTest(price=price):
                company = replace(self.strive, prior_week_equity_vwap=price)
                metrics = self.metrics(company)
                self.assertIsNone(metrics.common_equity_vwap)
                self.assertIsNone(metrics.net_common_capital)

    def test_common_capital_proxy_prefers_volume_weighted_trades(self):
        company = replace(self.strive, prior_week_equity_vwap=99.0,
                          prior_week_equity_trades=(Trade(20.0, 1.0), Trade(30.0, 3.0)))
        metrics = self.metrics(company)
        self.assertEqual(metrics.common_equity_vwap, 27.5)
        self.assertEqual(metrics.net_common_capital, 99e6)
        for trades in ((), (Trade(30.0, 0.0),), (Trade(30.0, -1.0),), (Trade(math.nan, 1.0),)):
            with self.subTest(trades=trades):
                invalid = self.metrics(replace(company, prior_week_equity_trades=trades))
                self.assertIsNone(invalid.common_equity_vwap)
                self.assertIsNone(invalid.net_common_capital)

    def test_common_capital_proxy_preserves_negative_flows_and_zero_needs_no_vwap(self):
        reduced = replace(self.strive, current=replace(self.strive.current, effective_common_shares=86.8e6))
        self.assertEqual(self.metrics(reduced).net_common_capital, -99e6)
        unchanged = replace(self.strive, prior=self.strive.current, prior_week_equity_vwap=None)
        self.assertEqual(self.metrics(unchanged).net_common_capital, 0.0)

    def test_common_capital_proxy_rejects_missing_or_invalid_share_counts(self):
        for shares in (None, -1.0, math.nan, math.inf):
            for snapshot in ("current", "prior"):
                with self.subTest(shares=shares, snapshot=snapshot):
                    company = replace(self.strive, **{
                        snapshot: replace(getattr(self.strive, snapshot), effective_common_shares=shares)
                    })
                    self.assertIsNone(self.metrics(company).net_common_capital)

    def test_common_capital_proxy_does_not_double_count_cash_flows_or_change_balances(self):
        baseline = self.metrics(self.strive)
        company = replace(self.strive, common_capital=CommonCapital(100e6, 20e6, False, 10e6))
        metrics = self.metrics(company)
        self.assertEqual(metrics.net_common_capital, 99e6)
        self.assertEqual(metrics.disclosed_net_common_capital, 90e6)
        self.assertEqual(metrics.common_issuance_cash, 110e6)
        for field in ("net_nav", "nav_per_share", "constant_price_nav_change_pct", "net_btc_amplification"):
            self.assertEqual(getattr(metrics, field), getattr(baseline, field))

    def test_vwap_uses_volume_weights(self):
        trades = (Trade(90.0, 1.0), Trade(95.0, 3.0))
        self.assertEqual(weekly_vwap(trades), 93.75)
        activity = PreferredActivity("STRC", 0.0, 1_600_000.0, prior_week_trades=trades)
        self.assertEqual(preferred_activity_capital(activity), -150e6)
        self.assertIsNone(weekly_vwap(()))
        self.assertIsNone(weekly_vwap((Trade(90.0, 0.0),)))
        self.assertIsNone(weekly_vwap((Trade(90.0, -1.0),)))

    def test_gross_preferred_issuance_and_repurchases_are_separate(self):
        activity = PreferredActivity("SATA", 10.0, 6.0, prior_week_vwap=90.0)
        self.assertEqual(preferred_activity_capital(activity), 460.0)
        self.assertNotEqual(preferred_activity_capital(activity), (10.0 - 6.0) * 100)
        with_fees = replace(activity, fees=25.0)
        self.assertEqual(preferred_activity_capital(with_fees), 435.0)

    def test_missing_preferred_gross_quantities_remain_unknown(self):
        traded = (Trade(100.0, 800_000.0),)
        self.assertIsNone(preferred_activity_capital(PreferredActivity("SATA", None, 0.0, prior_week_trades=traded)))
        self.assertIsNone(preferred_activity_capital(PreferredActivity("SATA", 0.0, None, prior_week_trades=traded)))
        self.assertIsNone(preferred_activity_capital(PreferredActivity("STRC", 0.0, 10.0)))
        self.assertIsNone(calculate_preferred_capital(()))
        self.assertIsNone(calculate_preferred_capital((PreferredActivity("STRC", 10.0, 0.0), PreferredActivity("Other", None, 0.0))))

    def test_reported_preferred_cash_takes_priority_over_notional_or_market_prices(self):
        reported = PreferredActivity(
            "STRC", 0.0, 1_557_177.0, prior_week_vwap=99.0,
            capital_method="reported", reported_issuance_proceeds=0.0,
            reported_repurchases_cash=151.8e6,
        )
        self.assertEqual(preferred_activity_capital(reported), -151.8e6)
        self.assertNotEqual(preferred_activity_capital(reported), -reported.repurchased_shares * 100)
        no_counts_or_prices = replace(reported, issued_shares=None, repurchased_shares=None,
                                     issuance_price_assumption=None, prior_week_vwap=None)
        self.assertEqual(preferred_activity_capital(no_counts_or_prices), -151.8e6)

    def test_reported_preferred_missing_or_invalid_cash_never_falls_back_to_model(self):
        reported = PreferredActivity(
            "SATA", 10.0, 0.0, capital_method="reported",
            reported_issuance_proceeds=980.0, reported_repurchases_cash=0.0,
        )
        for field in ("reported_issuance_proceeds", "reported_repurchases_cash"):
            for invalid in (None, -1.0, math.nan, math.inf):
                with self.subTest(field=field, invalid=invalid):
                    activity = replace(reported, **{field: invalid})
                    self.assertIsNone(preferred_activity_capital(activity))
                    self.assertIsNone(calculate_preferred_capital((reported, activity)))

    def test_reported_preferred_fees_are_not_deducted_twice(self):
        reported = PreferredActivity(
            "SATA", 10.0, 1.0, fees=20.0, capital_method="reported",
            reported_issuance_proceeds=980.0, reported_repurchases_cash=95.0,
        )
        company = replace(self.strive, preferred_activity=(reported,))
        metrics = self.metrics(company)
        self.assertEqual(metrics.net_preferred_capital, 885.0)
        self.assertFalse(metrics.preferred_fees_supplied)
        self.assertTrue(metrics.preferred_capital_reported)

    def test_preferred_reported_flag_requires_nonempty_all_reported_series(self):
        reported = PreferredActivity(
            "STRC", None, None, capital_method="reported",
            reported_issuance_proceeds=0.0, reported_repurchases_cash=151.8e6,
        )
        zero = replace(reported, series="STRF", reported_repurchases_cash=0.0)
        metrics = self.metrics(replace(self.strategy, preferred_activity=(reported, zero)))
        self.assertEqual(metrics.net_preferred_capital, -151.8e6)
        self.assertTrue(metrics.preferred_capital_reported)
        for activities in ((), (reported, PreferredActivity("STRF", 0.0, 0.0))):
            with self.subTest(activities=activities):
                self.assertFalse(self.metrics(replace(self.strategy, preferred_activity=activities)).preferred_capital_reported)

    def test_zero_preferred_activity_does_not_require_prices(self):
        zero = PreferredActivity("Other", 0.0, 0.0, issuance_price_assumption=None)
        self.assertEqual(preferred_activity_capital(zero), 0.0)
        self.assertIsNone(preferred_activity_capital(replace(zero, issued_shares=1.0)))

    def test_preferred_share_change_par_proxy_preserves_sign_and_unknown_gross_flows(self):
        activity = PreferredActivity("SATA", None, None, capital_method="share_change_par",
                                     net_share_change=803_099.0)
        self.assertEqual(preferred_activity_capital(activity), 80_309_900.0)
        self.assertEqual(preferred_activity_capital(replace(activity, net_share_change=-803_099.0)), -80_309_900.0)
        self.assertIsNone(activity.issued_shares)
        self.assertIsNone(activity.repurchased_shares)
        self.assertIsNone(activity.reported_issuance_proceeds)
        self.assertIsNone(activity.reported_repurchases_cash)
        # Known gross cash or market VWAP cannot be added to the chosen proxy.
        unrelated = replace(activity, issued_shares=900_000.0, repurchased_shares=96_901.0,
                            reported_issuance_proceeds=90e6, reported_repurchases_cash=9e6,
                            prior_week_vwap=97.0)
        self.assertEqual(preferred_activity_capital(unrelated), 80_309_900.0)

    def test_preferred_share_change_par_proxy_rejects_invalid_inputs_and_requires_explicit_price(self):
        activity = PreferredActivity("SATA", None, None, capital_method="share_change_par", net_share_change=10.0)
        for field, invalid_values in (
            ("net_share_change", (None, math.nan, math.inf, -math.inf)),
            ("issuance_price_assumption", (None, -1.0, math.nan, math.inf)),
            ("fees", (-1.0, math.nan, math.inf)),
        ):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    invalid = replace(activity, **{field: value})
                    self.assertIsNone(preferred_activity_capital(invalid))
                    self.assertIsNone(calculate_preferred_capital((activity, invalid)))
        self.assertEqual(preferred_activity_capital(replace(activity, net_share_change=0.0)), 0.0)
        self.assertEqual(preferred_activity_capital(replace(activity, issuance_price_assumption=0.0)), 0.0)
        self.assertIsNone(preferred_activity_capital(replace(activity, net_share_change=0.0,
                                                          issuance_price_assumption=None)))
        self.assertIsNone(preferred_activity_capital(replace(activity, net_share_change=1e308,
                                                          issuance_price_assumption=1e308)))

    def test_preferred_share_change_par_fees_are_deducted_once(self):
        activity = PreferredActivity("SATA", None, None, capital_method="share_change_par",
                                     net_share_change=10.0, fees=25.0)
        self.assertEqual(preferred_activity_capital(activity), 975.0)
        self.assertEqual(preferred_activity_capital(replace(activity, net_share_change=-10.0)), -1025.0)
        self.assertEqual(preferred_activity_capital(replace(activity, net_share_change=0.0)), -25.0)
        metrics = self.metrics(replace(self.strive, preferred_activity=(activity,)))
        self.assertEqual(metrics.net_preferred_capital, 975.0)
        self.assertTrue(metrics.preferred_fees_supplied)
        self.assertFalse(metrics.preferred_capital_reported)

    def test_preferred_share_change_par_proxy_does_not_change_nav_or_reported_balances(self):
        baseline = self.metrics(self.strive)
        activity = PreferredActivity("SATA", None, None, capital_method="share_change_par",
                                     net_share_change=803_099.0)
        company = replace(self.strive, preferred_activity=(activity,))
        metrics = self.metrics(company)
        self.assertEqual(metrics.net_preferred_capital, 80_309_900.0)
        self.assertEqual(company.current, self.strive.current)
        self.assertEqual(company.prior, self.strive.prior)
        for field in ("net_nav", "nav_per_share", "prior_net_nav", "constant_price_nav_change_pct",
                      "net_btc_amplification", "preferred_to_btc_pct", "preferred_claims_change"):
            with self.subTest(field=field):
                self.assertEqual(getattr(metrics, field), getattr(baseline, field))

    def test_financing_flows_do_not_overwrite_assets_or_claims(self):
        metrics = self.metrics(self.strategy)
        altered = replace(
            self.strategy,
            common_capital=CommonCapital(9e12, 0.0, True),
            preferred_activity=(PreferredActivity("STRC", 9e9, 0.0),),
        )
        changed = self.metrics(altered)
        for field in ("net_nav", "nav_per_share", "net_btc_amplification", "preferred_to_btc_pct", "preferred_claims_change"):
            self.assertEqual(getattr(metrics, field), getattr(changed, field))
        self.assertEqual(metrics.preferred_claims_change, -160e6)
        self.assertEqual(metrics.net_preferred_capital, -150e6)

    def test_balance_changes_do_not_establish_gross_btc_purchases(self):
        for company in self.report.companies:
            metrics = self.metrics(company)
            self.assertGreater(metrics.btc_change, 0)
            self.assertIsNone(metrics.weekly_btc_purchases)

    def test_debt_and_preferred_stay_unconverted_cash_and_securities_once(self):
        snapshot = Snapshot(100.0, 10.0, 50.0, 20.0, 30.0, 40.0)
        self.assertEqual(net_treasury_nav(snapshot, 1.0), 100.0)
        company = replace(self.strategy, current=snapshot)
        metrics = calculate_company(company, 1.0, 1.0)
        self.assertEqual(metrics.nav_per_share, 10.0)
        self.assertEqual(metrics.effective_common_shares, 10.0)

    def test_nonpositive_nav_disables_amplification_and_price_to_nav(self):
        for preferred_claims in (100.0, 150.0):
            with self.subTest(preferred_claims=preferred_claims):
                snapshot = Snapshot(100.0, 10.0, 0.0, 0.0, 0.0, preferred_claims)
                metrics = calculate_company(replace(self.strategy, current=snapshot), 1.0, 1.0)
                self.assertIsNone(metrics.net_btc_amplification)
                self.assertIsNone(metrics.price_to_nav)
                self.assertIsNone(metrics.amplification_change)
                self.assertLessEqual(metrics.net_nav, 0.0)

    def test_missing_assets_disable_nav_but_preserve_independent_metrics(self):
        company = replace(self.strategy, current=replace(self.strategy.current, cash=None))
        metrics = self.metrics(company)
        self.assertIsNone(metrics.net_nav)
        self.assertIsNone(metrics.nav_per_share)
        self.assertIsNone(metrics.price_to_nav)
        self.assertIsNone(metrics.net_btc_amplification)
        self.assertIsNotNone(metrics.sats_per_share)
        self.assertIsNotNone(metrics.preferred_to_btc_pct)

    def test_missing_price_zero_shares_zero_btc_and_nonfinite_values(self):
        metrics = calculate_company(self.strategy, None, 78_000.0)
        self.assertIsNone(metrics.net_nav)
        self.assertIsNotNone(metrics.sats_per_share)
        no_shares = self.metrics(replace(self.strategy, current=replace(self.strategy.current, effective_common_shares=0.0)))
        self.assertIsNone(no_shares.nav_per_share)
        self.assertIsNone(no_shares.sats_per_share)
        no_btc = self.metrics(replace(self.strategy, current=replace(self.strategy.current, btc_holdings=0.0)))
        self.assertIsNone(no_btc.preferred_to_btc_pct)
        self.assertIsNone(net_treasury_nav(replace(self.strategy.current, cash=math.nan), 80_000.0))
        self.assertIsNone(calculate_common_capital(CommonCapital(math.inf, 0.0, True)))

    def test_small_amplification_delta_never_renders_negative_zero(self):
        self.assertEqual(number(-0.004, 2, suffix="×", signed=True), "0.00×")
        self.assertEqual(number(-0.0, 2, suffix="×", signed=True), "0.00×")
        self.assertEqual(number(-0.006, 2, suffix="×", signed=True), "−0.01×")
        metrics = self.metrics(self.strive)
        original_delta = metrics.amplification_change
        self.assertNotEqual(original_delta, round(original_delta, 2))
        view = company_view(self.strive, metrics)
        self.assertEqual(view.amplification.change, "0.00× vs last Monday")
        self.assertEqual(metrics.amplification_change, original_delta)

    def test_presentation_distinguishes_nonpositive_nav_from_missing_inputs(self):
        zero_nav = Snapshot(100.0, 10.0, 0.0, 0.0, 0.0, 100.0)
        company = replace(self.strategy, current=zero_nav)
        view = company_view(company, calculate_company(company, 1.0, 1.0))
        self.assertEqual(view.price_to_nav, "N/M")
        self.assertEqual(view.amplification.value, "N/M")
        self.assertEqual(view.amplification.change, "N/M vs last Monday")
        missing = replace(self.strategy, current=replace(self.strategy.current, cash=None))
        view = company_view(missing, self.metrics(missing))
        self.assertEqual(view.price_to_nav, "Not disclosed")
        self.assertEqual(view.amplification.value, "Not disclosed")

    def test_shared_view_preserves_fixture_signs_and_missing_disclosure(self):
        strategy, strive = build_report_view(self.report).companies
        self.assertEqual(strategy.common.value, "+$600.0m")
        self.assertEqual(strategy.preferred.value, "−$150.0m")
        self.assertEqual(strategy.amplification.change, "−0.02× vs last Monday")
        self.assertEqual(strategy.preferred_ratio.change, "−0.93 pp WoW")
        self.assertEqual(strive.common.value, "+$99.0m")
        self.assertEqual(strive.preferred.value, "+$80.0m")
        self.assertEqual(strive.amplification.change, "0.00× vs last Monday")
        self.assertIn("Weekly BTC purchases: Not disclosed", strive.bitcoin.details)


if __name__ == "__main__":
    unittest.main()
