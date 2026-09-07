"""Historical replay checks anchored to the dated source audit, not sample data."""
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image

from report import png_export
from report.calculations import calculate_company
from report.historical_data import historical_report
from report.historical_claims import strategy_claim_components, strive_preferred_claims
from report.png_export import render_png
from report.post_export import render_post_png
from report.presentation import build_report_view


class HistoricalReplayTests(unittest.TestCase):
    def setUp(self):
        self.report = historical_report()
        self.strategy, self.strive = self.report.companies
        self.view = build_report_view(self.report)

    def metrics(self, company):
        return calculate_company(company, self.report.current_btc_price,
                                 self.report.prior_btc_price)

    def test_strategy_uses_disclosed_cash_not_preferred_face_value(self):
        metrics = self.metrics(self.strategy)
        self.assertEqual(metrics.net_common_capital, 602_800_000)
        self.assertEqual(metrics.net_preferred_capital, -151_800_000)
        self.assertNotEqual(metrics.net_preferred_capital, -1_557_177 * 100)
        self.assertEqual(self.strategy.common_capital.issued_shares, 4_531_421)
        self.assertEqual(self.strategy.common_capital.repurchased_shares, 0)
        self.assertEqual(self.strategy.preferred_activity[0].repurchased_shares, 1_557_177)
        self.assertTrue(metrics.preferred_capital_reported)
        self.assertEqual(self.view.companies[0].common.value, "+$602.8m")
        self.assertEqual(self.view.companies[0].preferred.value, "−$151.8m")
        self.assertEqual(self.view.companies[0].common.label, "Net common capital")

    def test_strive_effective_denominator_and_bitcoin_growth(self):
        metrics = self.metrics(self.strive)
        self.assertEqual(self.strive.current.effective_common_shares, 83_470_035 + 9_792_535)
        self.assertEqual(self.strive.prior.effective_common_shares, 79_890_888 + 9_792_535)
        self.assertEqual(metrics.shares_change, 3_579_147)
        self.assertEqual(metrics.btc_change, 1_800)
        self.assertAlmostEqual(metrics.sats_per_share, 24_828.82468282828, places=7)
        self.assertAlmostEqual(metrics.sats_change_pct, 4.2673715406878365, places=10)
        self.assertEqual(self.view.companies[1].bitcoin.change, "+4.27% per share WoW")

    def test_cached_minute_estimate_produces_strive_capital_proxy(self):
        metrics = self.metrics(self.strive)
        self.assertAlmostEqual(self.strive.prior_week_equity_vwap, 21.48697766379118, places=12)
        self.assertIsNone(self.strive.prior_week_equity_trades)
        self.assertAlmostEqual(metrics.common_equity_vwap, 21.48697766379118, places=12)
        self.assertAlmostEqual(metrics.net_common_capital, 76_905_051.6444252, places=6)
        self.assertTrue(metrics.common_capital_estimated)
        self.assertIsNone(metrics.disclosed_net_common_capital)
        self.assertIsNone(metrics.common_issuance_cash)
        self.assertIsNone(metrics.common_buybacks_cash)
        self.assertEqual(self.view.companies[1].common.value, "+$76.9m")
        details = " ".join(self.view.companies[1].common.details)
        for required in ("+3,579,147", "$21.49 VWAP (est.)", "1-minute VWAP estimate",
                         "2026-08-24", "2026-08-28", "before fees"):
            self.assertIn(required, details)
        self.assertNotIn("reported proceeds", details.lower())

    def test_missing_cached_vwap_never_becomes_sample_or_spot_price(self):
        with patch("report.historical_data.load_estimate", return_value=None):
            report = historical_report()
        strive = report.companies[1]
        metrics = self.metrics(strive)
        view = build_report_view(report).companies[1]
        self.assertIsNone(strive.prior_week_equity_vwap)
        self.assertIsNone(strive.equity_vwap_note)
        self.assertIsNone(metrics.common_equity_vwap)
        self.assertIsNone(metrics.net_common_capital)
        self.assertIsNone(metrics.disclosed_net_common_capital)
        self.assertEqual(view.common.value, "Unavailable")
        self.assertIn("+3,579,147", " ".join(view.common.details))
        self.assertIn("VWAP not verified", " ".join(view.common.details))
        # Changing a financing estimate never alters the reported balances.
        self.assertEqual(strive.current, self.strive.current)
        self.assertEqual(strive.prior, self.strive.prior)
        self.assertEqual((strive.current.cash, strive.prior.cash),
                         (183_500_000, 171_900_000))
        baseline = self.metrics(self.strive)
        for field in ("net_nav", "nav_per_share", "constant_price_nav_change_pct",
                      "net_btc_amplification", "preferred_to_btc_pct"):
            with self.subTest(field=field):
                self.assertEqual(getattr(metrics, field), getattr(baseline, field))

    def test_strive_par_proxy_keeps_actual_gross_preferred_flows_unknown(self):
        activity = self.strive.preferred_activity[0]
        self.assertIsNone(activity.issued_shares)
        self.assertIsNone(activity.repurchased_shares)
        self.assertIsNone(activity.reported_issuance_proceeds)
        self.assertIsNone(activity.reported_repurchases_cash)
        self.assertEqual(activity.capital_method, "share_change_par")
        self.assertEqual(activity.net_share_change, 803_099)
        self.assertEqual(activity.issuance_price_assumption, 100)
        metrics = self.metrics(self.strive)
        self.assertEqual(metrics.net_preferred_capital, 80_309_900)
        self.assertFalse(metrics.preferred_capital_reported)
        view = self.view.companies[1].preferred
        self.assertEqual(view.value, "+$80.3m")
        self.assertEqual(view.label, "SATA capital")
        self.assertIn("estimated", view.overline)
        details = " ".join(view.details)
        for required in ("+803,099 net shares", "$100 assumed", "before fees", "actual financing cash not disclosed"):
            self.assertIn(required, details)

    def test_removing_strive_par_proxy_reveals_unknown_actual_cash_without_changing_nav(self):
        actual_cash_activity = replace(self.strive.preferred_activity[0], capital_method="reported",
                                       reported_issuance_proceeds=None, reported_repurchases_cash=None)
        actual_cash_company = replace(self.strive, preferred_activity=(actual_cash_activity,))
        actual_metrics = self.metrics(actual_cash_company)
        self.assertIsNone(actual_metrics.net_preferred_capital)
        actual_view = build_report_view(replace(self.report, companies=(self.strategy, actual_cash_company)))
        self.assertEqual(actual_view.companies[1].preferred.value, "Not disclosed")
        self.assertEqual(actual_cash_company.current, self.strive.current)
        self.assertEqual(actual_cash_company.prior, self.strive.prior)
        baseline = self.metrics(self.strive)
        for field in ("net_nav", "nav_per_share", "prior_net_nav", "constant_price_nav_change_pct",
                      "net_btc_amplification", "preferred_to_btc_pct", "preferred_claims_change"):
            with self.subTest(field=field):
                self.assertEqual(getattr(actual_metrics, field), getattr(baseline, field))

    def test_estimated_historical_valuations_are_populated_and_visibly_marked(self):
        # Independent reconciliation of the dated balances and claim schedules.
        expected = (
            (51_308_702_873.50, 122.02325153097748, -0.09440342137476687,
             "≈$122.02", "≈−0.09%"),
            (1_140_927_686.70, 12.233500392494006, 2.6726346949653923,
             "≈$12.23", "≈+2.67%"),
        )
        for company, view, values in zip(self.report.companies, self.view.companies, expected):
            with self.subTest(company=company.ticker):
                metrics = self.metrics(company)
                self.assertAlmostEqual(metrics.net_nav, values[0], places=4)
                self.assertAlmostEqual(metrics.nav_per_share, values[1], places=10)
                self.assertAlmostEqual(metrics.constant_price_nav_change_pct, values[2], places=10)
                for field in ("net_nav", "nav_per_share", "price_to_nav",
                              "constant_price_nav_change_pct", "net_btc_amplification",
                              "preferred_to_btc_pct"):
                    self.assertIsNotNone(getattr(metrics, field), field)
                self.assertEqual(view.nav_per_share, values[3])
                self.assertEqual(view.nav_change.value, values[4])
                self.assertTrue(company.valuation_estimated)
                self.assertTrue(company.preferred_claims_estimated)
                for display in (view.nav_per_share, view.price_to_nav, view.nav_change.value,
                                view.amplification.value, view.amplification.change,
                                view.preferred_ratio.value, view.preferred_ratio.change):
                    self.assertTrue(display.startswith("≈"), display)
                    self.assertNotIn("Unavailable", display)
                    self.assertNotIn("Not disclosed", display)
                self.assertTrue(view.nav_note.startswith("≈"))
                self.assertIn("Basic common shares", view.nav_note)
                self.assertIn("after debt & preferred claims", view.nav_note)

    def test_strategy_prior_denominator_uses_reported_basic_shares_at_disclosed_precision(self):
        metrics = self.metrics(self.strategy)
        self.assertEqual(self.strategy.current.effective_common_shares, 420_483_000)
        self.assertEqual(self.strategy.prior.effective_common_shares, 415_929_000)
        self.assertEqual(metrics.shares_change, 4_554_000)
        self.assertNotEqual(metrics.shares_change, self.strategy.common_capital.issued_shares)
        self.assertAlmostEqual(metrics.sats_change_pct, -0.5412871201282865, places=10)
        self.assertIn("rounded", self.strategy.share_basis_note)
        self.assertEqual(self.view.companies[0].bitcoin.change, "−0.54% per share WoW")

    def test_strategy_preferred_rollforward_and_all_series_claim_components(self):
        prior = strategy_claim_components("prior")
        current = strategy_claim_components("current")
        # Q2 ending STRC less each disclosed weekly retirement, then this week.
        prior_strc = 104_894_705 - 288_930 - 912_143 - 1_152_020 - 1_388_720 - 1_431_212
        self.assertEqual(prior_strc, 99_721_680)
        self.assertEqual(prior["STRC"]["shares"], prior_strc)
        self.assertEqual(current["STRC"]["shares"], 98_164_503)
        self.assertEqual(prior["STRC"]["shares"] - current["STRC"]["shares"], 1_557_177)
        expected_counts = {"STRF": 12_839_689, "STRK": 14_020_744,
                           "STRD": 14_024_221, "STRE": 7_750_000}
        self.assertEqual(set(current), {*expected_counts, "STRC"})
        for series, count in expected_counts.items():
            self.assertEqual(current[series]["shares"], count)
            self.assertEqual(prior[series]["shares"], count)
        self.assertEqual(current["STRC"]["base_preference"], Decimal("9816450300"))
        self.assertEqual(current["STRC"]["estimated_dividend_accrual"], Decimal("49082251.5"))
        self.assertEqual(prior["STRC"]["estimated_dividend_accrual"], Decimal("26592448"))
        # STRD has no cumulative accrual; STRE's euro claim receives FX once.
        for components in (prior, current):
            self.assertEqual(components["STRD"]["estimated_dividend_accrual"], 0)
            self.assertEqual(components["STRE"]["base_preference"], 775_000_000)
            self.assertEqual(components["STRE"]["currency"], "EUR")
        self.assertEqual(current["STRE"]["estimated_claims_usd"], Decimal("917371375"))
        self.assertAlmostEqual(self.strategy.current.preferred_claims, 14_911_463_133.50, places=4)
        self.assertAlmostEqual(self.strategy.prior.preferred_claims, 15_042_662_778.211111, places=4)
        self.assertEqual(self.strategy.current.debt_principal, 6_753_703_000)
        self.assertEqual(self.strategy.prior.debt_principal, 6_753_703_000)
        self.assertEqual(self.strategy.current.combined_liquid_assets, 6_710_000_000)
        self.assertEqual(self.strategy.prior.combined_liquid_assets, 6_690_000_000)
        for snapshot in (self.strategy.current, self.strategy.prior):
            self.assertIsNone(snapshot.cash)
            self.assertIsNone(snapshot.marketable_securities)

    def test_strive_zero_debt_and_conservative_preference_bound_do_not_imply_cash_flows(self):
        self.assertEqual(self.strive.current.debt_principal, 0)
        self.assertEqual(self.strive.prior.debt_principal, 0)
        self.assertEqual(self.strive.prior.preferred_claims, 827_081_500)
        lower = strive_preferred_claims("current", conservative=False)
        upper = strive_preferred_claims("current")
        self.assertEqual(lower, 907_391_400)
        self.assertAlmostEqual(upper, 907_482_139.14, places=6)
        self.assertAlmostEqual(upper - lower, 90_739.14, places=6)
        self.assertEqual(self.strive.current.preferred_claims, upper)
        # The financing proxy uses $100; it does not overwrite the $100.01
        # conservative ending claim used independently in the NAV calculation.
        self.assertEqual(self.strive.preferred_activity[0].issuance_price_assumption, 100)
        self.assertEqual(self.metrics(self.strive).net_preferred_capital, 80_309_900)
        self.assertNotAlmostEqual(self.metrics(self.strive).preferred_claims_change, 80_309_900)

    def test_strategy_constant_price_nav_reprices_prior_euro_claims_only(self):
        metrics = self.metrics(self.strategy)
        expected_prior_claims_at_current_fx = 15_038_258_883.766666
        self.assertAlmostEqual(self.strategy.prior_preferred_claims_at_current_prices,
                               expected_prior_claims_at_current_fx, places=4)
        prior_constant_nav = (840_447 * 78_414.14 + 6_690_000_000
                              - 6_753_703_000 - expected_prior_claims_at_current_fx)
        self.assertAlmostEqual(metrics.prior_nav_per_share_at_current_prices,
                               prior_constant_nav / 415_929_000, places=10)
        without_fx_override = self.metrics(replace(self.strategy, prior_preferred_claims_at_current_prices=None))
        self.assertNotAlmostEqual(metrics.constant_price_nav_change_pct,
                                  without_fx_override.constant_price_nav_change_pct)
        for field in ("prior_net_nav", "prior_nav_per_share", "prior_net_btc_amplification",
                      "prior_preferred_to_btc_pct", "amplification_change", "preferred_to_btc_change_pp"):
            self.assertEqual(getattr(metrics, field), getattr(without_fx_override, field))

    def test_unchanged_505000_strc_shares_reprice_at_the_current_mark(self):
        self.assertEqual(self.strive.prior.marketable_securities, 48_571_000)
        self.assertEqual(self.strive.current.marketable_securities, 49_152_000)
        current_price_per_strc_share = 49_152_000 / 505_000
        self.assertAlmostEqual(self.strive.prior_securities_at_current_prices,
                               505_000 * current_price_per_strc_share)
        metrics = self.metrics(self.strive)
        expected_prior_nav = 21_356 * 78_414.14 + 171_900_000 + 49_152_000 - 827_081_500
        self.assertAlmostEqual(metrics.prior_nav_per_share_at_current_prices,
                               expected_prior_nav / 89_683_423)

    def test_replay_metadata_and_quotes_have_historical_dates(self):
        self.assertFalse(self.report.illustrative)
        self.assertEqual(self.report.edition_id, "2026-08-31")
        self.assertEqual(self.report.current_btc_price, 78_414.14)
        self.assertEqual(self.report.prior_btc_price, 78_976.18)
        self.assertEqual(self.report.btc_quote_timestamp, "Aug 31 · 8:30 AM ET")
        self.assertIn("August 31, 2026", self.view.report_time)
        self.assertEqual(self.view.label, "HISTORICAL RECONSTRUCTION · ≈ ESTIMATED")
        self.assertEqual((self.strategy.stock_price, self.strive.stock_price), (127.31, 21.74))
        for company in self.report.companies:
            self.assertEqual(company.quote_session, "PRIOR CLOSE")
            self.assertEqual(company.quote_timestamp, "Aug 28 · 4:00 PM ET")

    def test_real_period_growth_is_present_for_both_companies(self):
        for company in self.view.companies:
            self.assertEqual(tuple(period.period for period in company.periods), ("QTD", "YTD"))
            for period in company.periods:
                for value in (period.btc_growth, period.nav_growth):
                    self.assertNotIn(value, ("—", "Not disclosed", "Unavailable"))
                    self.assertIn("%", value)

    def test_both_png_renderers_fit_and_show_historical_disclosures(self):
        for renderer in (render_png, render_post_png):
            with self.subTest(renderer=renderer.__name__):
                drawn = []
                original_text = png_export._Canvas.text

                def record(canvas, item, *args, **kwargs):
                    drawn.append(item.text)
                    # Keep each renderer's actual measured bounds checks active.
                    return original_text(canvas, item, *args, **kwargs)

                with patch.object(png_export._Canvas, "text", record):
                    image = Image.open(BytesIO(renderer(self.view)))
                    image.load()
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.width, 1800)
                if renderer is render_post_png:
                    self.assertEqual(image.height, 1125)
                self.assertIn(self.view.label, drawn)
                self.assertIn(self.view.footer, image.info["Description"])
                text = " ".join(drawn)
                for required in ("+$602.8m", "−$151.8m", "+$76.9m", "+$80.3m",
                                 "3,579,147", "$21.49", "PRIOR CLOSE", "803,099",
                                 "$100", "SATA capital", "$97.48",
                                 "≈$122.02", "≈$12.23", "≈−0.09%", "≈+2.67%",
                                 "PRICE / BASIC NAV"):
                    self.assertIn(required, text)
                for company in self.view.companies:
                    self.assertIn(company.bought.value, drawn)
                    self.assertIn(company.total_bitcoin.value, drawn)
                    expected_btc = "845,050 BTC" if company.ticker == "MSTR" else "23,156 BTC"
                    self.assertEqual(company.total_bitcoin.value, expected_btc)
                    for period in company.periods:
                        self.assertIn(period.btc_growth, drawn)
                        self.assertIn(period.nav_growth, drawn)
                if renderer is render_post_png:
                    # The compact image retains the financing inputs while
                    # full formulas and source provenance live below the panel.
                    self.assertIn("VWAP", text)
                    self.assertIn(self.view.companies[1].bitcoin.short_change, drawn)
                    self.assertNotIn("1-minute VWAP estimate", text)
                for forbidden in ("illustrative", "$27.50", "$99.0m", "Unavailable",
                                  "await verified baselines", "BTC value ÷ net treasury NAV",
                                  "financing + other balance changes"):
                    self.assertNotIn(forbidden.lower(), (text + str(image.info)).lower())


if __name__ == "__main__":
    unittest.main()
