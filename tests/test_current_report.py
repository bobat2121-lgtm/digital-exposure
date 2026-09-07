"""Current market repricing keeps the dated operating and financing inputs fixed."""

from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image

from report import png_export
from report.calculations import calculate_company
from report.current_report import current_report, quote_rows
from report.historical_data import historical_report
from report.png_export import render_png
from report.post_export import render_post_png
from report.presentation import build_report_view


def quote_fixture():
    values = {"MSTR": 150.0, "ASST": 30.0, "STRC": 101.0, "EURUSD=X": 1.2, "BTC-USD": 82_000.0}
    return {
        "schema_version": 1, "fetched_at": "2026-09-07T16:30:00+00:00",
        "quotes": {symbol: {"symbol": symbol, "price": price,
                            "as_of": "2026-09-07T16:29:00+00:00" if symbol in ("BTC-USD", "EURUSD=X") else "2026-09-04T20:00:00+00:00",
                            "source_url": "https://api.strategy.com/btc/bitcoinKpis" if symbol == "BTC-USD" else
                            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.replace('=', '%3D')}?interval=1d&range=5d"}
                   for symbol, price in values.items()},
    }


class CurrentReportTests(unittest.TestCase):
    def metrics(self, report, company):
        return calculate_company(company, report.current_btc_price, report.prior_btc_price)

    def test_current_prices_revalue_btc_securities_and_fx_without_changing_dated_balances_or_flows(self):
        historical = historical_report()
        prices = quote_fixture()
        original_prices = deepcopy(prices)
        report = current_report(prices)
        strategy, strive = report.companies
        old_strategy, old_strive = historical.companies
        # Independent native-currency claim schedule: ending shares, $100 base,
        # dated dividend accruals, and the supplied EUR/USD conversion once.
        expected_current_claims = (
            98_164_503 * 100.5 + 12_839_689 * (100 + 10 * 60 / 360)
            + 14_020_744 * (100 + 8 * 60 / 360) + 14_024_221 * 100
            + 7_750_000 * (100 + 10 * 60 / 360) * 1.2
        )
        expected_prior_claims_at_fx = (
            99_721_680 * (100 + 12 * 8 / 360) + 12_839_689 * (100 + 10 * 53 / 360)
            + 14_020_744 * (100 + 8 * 53 / 360) + 14_024_221 * 100
            + 7_750_000 * (100 + 10 * 53 / 360) * 1.2
        )
        self.assertAlmostEqual(strategy.current.preferred_claims, expected_current_claims, places=4)
        self.assertAlmostEqual(strategy.prior_preferred_claims_at_current_prices, expected_prior_claims_at_fx, places=4)
        self.assertEqual(strategy.current, replace(old_strategy.current, preferred_claims=strategy.current.preferred_claims))
        self.assertEqual(strive.current, replace(old_strive.current, marketable_securities=51_005_000))
        self.assertEqual(strive.prior_securities_at_current_prices, 505_000 * 101)
        expected_current_nav = (
            845_050 * 82_000 + 6_710_000_000 - 6_753_703_000 - expected_current_claims,
            23_156 * 82_000 + 183_500_000 + 51_005_000 - 907_482_139.14,
        )
        expected_prior_constant_nav = (
            840_447 * 82_000 + 6_690_000_000 - 6_753_703_000 - expected_prior_claims_at_fx,
            21_356 * 82_000 + 171_900_000 + 51_005_000 - 827_081_500,
        )
        for index, (company, old) in enumerate(zip(report.companies, historical.companies)):
            with self.subTest(symbol=company.ticker):
                self.assertEqual(company.prior, old.prior)
                for field in ("btc_holdings", "effective_common_shares", "cash", "debt_principal", "combined_liquid_assets"):
                    self.assertEqual(getattr(company.current, field), getattr(old.current, field))
                for field in ("common_capital", "preferred_activity", "weekly_btc_purchases", "prior_week_equity_vwap"):
                    self.assertEqual(getattr(company, field), getattr(old, field))
                metrics = self.metrics(report, company)
                self.assertAlmostEqual(metrics.net_nav, expected_current_nav[index], places=4)
                self.assertAlmostEqual(metrics.nav_per_share, expected_current_nav[index] / company.current.effective_common_shares)
                expected_prior_per_share = expected_prior_constant_nav[index] / company.prior.effective_common_shares
                self.assertAlmostEqual(metrics.prior_nav_per_share_at_current_prices, expected_prior_per_share)
                self.assertAlmostEqual(metrics.constant_price_nav_change_pct,
                                       (metrics.nav_per_share / expected_prior_per_share - 1) * 100)
        self.assertEqual((strategy.stock_price, strive.stock_price), (150.0, 30.0))
        self.assertEqual(report.current_btc_price, 82_000.0)
        self.assertEqual(report.prior_btc_price, 78_976.18)
        self.assertEqual(historical_report(), historical)
        self.assertEqual(prices, original_prices)

    def test_price_moves_change_current_ratios_and_constant_comparison_but_preserve_prior_monday(self):
        prices = quote_fixture()
        baseline = current_report(prices)
        higher_btc = deepcopy(prices)
        higher_btc["quotes"]["BTC-USD"]["price"] = 90_000.0
        changed = current_report(higher_btc)
        for old, new in zip(baseline.companies, changed.companies):
            with self.subTest(symbol=new.ticker):
                self.assertEqual(new, old)
                before, after = self.metrics(baseline, old), self.metrics(changed, new)
                self.assertAlmostEqual(after.net_nav - before.net_nav, new.current.btc_holdings * 8_000)
                self.assertAlmostEqual(after.prior_nav_per_share_at_current_prices - before.prior_nav_per_share_at_current_prices,
                                       new.prior.btc_holdings * 8_000 / new.prior.effective_common_shares)
                for field in ("price_to_nav", "constant_price_nav_change_pct", "net_btc_amplification", "preferred_to_btc_pct"):
                    self.assertNotAlmostEqual(getattr(before, field), getattr(after, field))
                for field in ("prior_net_nav", "prior_nav_per_share", "prior_net_btc_amplification",
                              "prior_preferred_to_btc_pct", "sats_per_share", "sats_change_pct",
                              "net_common_capital", "net_preferred_capital"):
                    self.assertEqual(getattr(before, field), getattr(after, field))
                prior_bitcoin = new.prior.btc_holdings * 78_976.18
                self.assertAlmostEqual(after.prior_net_btc_amplification, prior_bitcoin / after.prior_net_nav)
        # A common-stock quote alone changes price/NAV, not treasury NAV.
        higher_equities = deepcopy(prices)
        for symbol in ("MSTR", "ASST"):
            higher_equities["quotes"][symbol]["price"] *= 1.1
        equities = current_report(higher_equities)
        for before_company, after_company in zip(baseline.companies, equities.companies):
            before, after = self.metrics(baseline, before_company), self.metrics(equities, after_company)
            self.assertAlmostEqual(after.price_to_nav, before.price_to_nav * 1.1)
            self.assertEqual(replace(after, price_to_nav=before.price_to_nav), before)

    def test_current_renderers_fit_and_preserve_capital_dates_and_provider_quote_times(self):
        prices = quote_fixture()
        report = current_report(prices)
        view = build_report_view(report, prices=prices)
        self.assertEqual(report.edition_id, "current-prices")
        self.assertFalse(report.illustrative)
        self.assertEqual(view.report_time, "Updated Sep 7, 2026 · 12:30 PM ET")
        self.assertEqual(view.btc_timestamp, "Sep 7 · 12:29 PM ET")
        self.assertEqual(view.capital_period_label, "Market Activity · Aug 24–30")
        self.assertEqual(report.prior_comparison_date, "Aug 24")
        for company in view.companies:
            self.assertEqual(company.nav_change.label, "Reported-week NAV/share")
            self.assertTrue(company.amplification.change.endswith("vs Aug 24"))
            self.assertTrue(company.preferred_ratio.change.endswith("vs Aug 24"))
        rows = {row["Instrument"]: row for row in quote_rows(prices)}
        self.assertEqual(set(rows), {"MSTR", "ASST", "STRC", "EURUSD=X", "BTC-USD"})
        self.assertEqual(rows["EURUSD=X"]["Price (USD)"], "1.20000")
        self.assertEqual(rows["STRC"]["Quote time (ET)"], "Sep 4 · 4:00 PM ET")
        for renderer in (render_png, render_post_png):
            with self.subTest(renderer=renderer.__name__):
                drawn = []
                original_text = png_export._Canvas.text

                def record(canvas, item, *args, **kwargs):
                    drawn.append(item.text)
                    return original_text(canvas, item, *args, **kwargs)

                with patch.object(png_export._Canvas, "text", record):
                    image = Image.open(BytesIO(renderer(view)))
                    image.load()
                self.assertEqual(image.width, 1800)
                if renderer is render_post_png:
                    self.assertEqual(image.height, 1125)
                text = " ".join(drawn)
                header_time = (view.report_time.replace("Updated ", "Quotes updated ", 1)
                               if renderer is render_post_png else view.report_time)
                self.assertEqual(image.info["Title"], "The Digital Credit Report")
                for required in (header_time,
                                 "Balance dates: Strategy Aug 30 · Strive Aug 28", "MARKET ACTIVITY · AUG 24–30",
                                 "Sep 4 · 4:00 PM ET", "LAST PRICE",
                                 "$150.00", "$30.00", "+$602.8m", "+$76.9m", "+$80.3m",
                                 "NAV per common share", "vs Aug 24"):
                    self.assertIn(required, text)
                if renderer is render_post_png:
                    self.assertIn(f"BTC {view.btc_price}", drawn)
                    self.assertNotIn(view.btc_timestamp, text)
                else:
                    self.assertIn(view.btc_timestamp, text)
                self.assertNotIn("CAPITAL THIS WEEK", text)
                self.assertNotIn("vs last Monday", text)
                self.assertNotIn("ILLUSTRATIVE", text)
                self.assertNotIn("CURRENT PRICE DEMO", text)
                self.assertNotIn("reported net proceeds", text)
                for source, company in zip(report.companies, view.companies):
                    expected_btc = f"{source.current.btc_holdings:,.0f} BTC"
                    self.assertEqual(company.total_bitcoin.value, expected_btc)
                    self.assertIn(expected_btc, drawn)
                self.assertIn(view.footer, image.info["Description"])


if __name__ == "__main__":
    unittest.main()
