import unittest

from report.strategy_period_baselines import strategy_period_baselines


class StrategyPeriodBaselineTests(unittest.TestCase):
    def test_baselines_use_reported_basic_shares_and_all_debt_principal(self):
        baselines = strategy_period_baselines(80_000, 1.1643)
        qtd, ytd = baselines["QTD"], baselines["YTD"]
        self.assertEqual((qtd.btc_holdings, qtd.effective_common_shares), (846_000, 371_604_000))
        self.assertEqual((ytd.btc_holdings, ytd.effective_common_shares), (672_500, 312_062_000))
        self.assertEqual(qtd.debt_principal, 6_753_703_000)
        self.assertEqual(ytd.debt_principal, 8_254_000_000)
        self.assertEqual(qtd.combined_liquid_assets, 2_400_000_000)
        self.assertEqual(ytd.combined_liquid_assets, 2_250_000_000)
        self.assertIsNone(qtd.cash)
        self.assertIsNone(qtd.marketable_securities)


    def test_year_end_strf_preference_is_above_par_and_future_dividends_excluded(self):
        ytd = strategy_period_baselines(80_000, 1)["YTD"]
        par_claims = (12_839_689 + 29_587_063 + 7_750_000 + 13_981_948 + 14_024_221) * 100
        self.assertAlmostEqual(ytd.preferred_claims, par_claims + 12_839_689 * 6.17, places=4)
        # The $27.121m GAAP payable concerns January's future dividend, not
        # additional accumulated December liquidation claims.
        self.assertAlmostEqual(ytd.preferred_claims - par_claims, 79_220_881.13, places=4)


    def test_fx_reprices_only_the_fixed_euro_claims_at_both_baselines(self):
        before = strategy_period_baselines(70_000, 1.16)
        after = strategy_period_baselines(90_000, 1.17)
        for period in ("QTD", "YTD"):
            self.assertAlmostEqual(after[period].preferred_claims - before[period].preferred_claims, 7_750_000)
            self.assertEqual(after[period].btc_holdings, before[period].btc_holdings)
            self.assertEqual(after[period].combined_liquid_assets, before[period].combined_liquid_assets)


    def test_missing_fx_preserves_btc_growth_inputs_without_fabricating_claims(self):
        baselines = strategy_period_baselines(None, None)
        self.assertIsNone(baselines["QTD"].preferred_claims)
        self.assertEqual(baselines["YTD"].btc_holdings, 672_500)
        with self.assertRaisesRegex(ValueError, "EUR/USD"):
            strategy_period_baselines(80_000, float("nan"))


if __name__ == "__main__":
    unittest.main()
