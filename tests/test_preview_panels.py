"""Offline preview panels: saved extras snapshot, committed filings, demo Friday data."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "sources" / "friday") not in sys.path:
    sys.path.insert(0, str(ROOT / "sources" / "friday"))

from panels import extras as extras_module
from panels import friday_preview, monday_preview, wednesday
from report.current_prices import load_current_prices
from report.live_report import resolve_complete_report

FEED = json.loads((ROOT / "data" / "latest-report-filings.json").read_text())


def assert_phone_ready(case, png):
    """X shows up to 3:4 uncropped; the type scale assumes a 1440-px width."""
    from io import BytesIO
    from PIL import Image
    image = Image.open(BytesIO(png))
    case.assertEqual(image.width, 1440)
    case.assertLessEqual(image.height / image.width, 4 / 3)


def offline_extras():
    return extras_module.load_extras(offline=True)


class ExtrasTests(unittest.TestCase):
    def test_offline_snapshot_supplies_every_section_marked_stale(self):
        extras = offline_extras()
        for section in extras_module.SECTIONS:
            self.assertIsNotNone(extras[section], section)
        self.assertEqual(sorted(extras["stale"]), sorted(extras_module.SECTIONS))

    def test_failed_section_falls_back_to_snapshot(self):
        def broken():
            raise OSError("offline")
        with patch.dict(extras_module.FETCHERS, {"fred": broken}):
            extras = extras_module.load_extras(("fred",))
        self.assertEqual(extras["stale"], ["fred"])
        self.assertEqual(extras["fred"], extras_module.load_snapshot()["fred"])

    def test_number_rejects_non_numeric(self):
        self.assertIsNone(extras_module.number(True))
        self.assertIsNone(extras_module.number("nan"))
        self.assertEqual(extras_module.number("1,234.5"), 1234.5)


class MondayPreviewTests(unittest.TestCase):
    def setUp(self):
        self.prices = load_current_prices()
        self.report = resolve_complete_report(self.prices, FEED).report
        self.preview = monday_preview.build_preview(self.report, self.prices, FEED, offline_extras())

    def test_amplification_is_btc_reserve_over_net_reserve_for_both(self):
        from report.calculations import liquid_assets
        strive = next(c for c in self.report.companies if c.ticker == "ASST")
        current = strive.current
        bitcoin = current.btc_holdings * self.report.current_btc_price
        net = bitcoin + liquid_assets(current) - current.debt_principal - current.preferred_claims
        asst = self.preview.extras["ASST"]
        self.assertAlmostEqual(asst.amplification_x, bitcoin / net)
        self.assertTrue(monday_preview._amplification(asst)[0].endswith("×"))
        # Strive's own % ratio stays available for the audit.
        self.assertAlmostEqual(asst.amplification_pct, (current.debt_principal + current.preferred_claims) / bitcoin * 100)
        # Strategy shows its strategy.com KPI.
        strategy = self.preview.extras["MSTR"]
        kpi = offline_extras()["strategy"]["btc"]["amplification"]
        self.assertAlmostEqual(strategy.amplification_x, kpi)
        self.assertEqual(monday_preview._amplification(strategy)[0], f"{kpi:.2f}×")

    def test_funding_splits_into_bitcoin_and_dividends(self):
        strategy = self.preview.extras["MSTR"]
        # Sep 14–20: $0 common, −$174.0m STRC, cash and reserve fell $310m.
        self.assertEqual(strategy.liquid_change, -310_000_000)
        self.assertAlmostEqual(strategy.net_funding, 0 - 174_000_000 + 310_000_000)
        # The 8-K: 950 BTC for $75.7m; $57.4m of dividends and interest (the rest is balance rounding).
        self.assertEqual(strategy.btc_cost, 75_700_000)
        self.assertEqual(strategy.stated_dividends, 57_400_000)
        self.assertAlmostEqual(strategy.dividends, 136_000_000 - 75_700_000)
        for extra in self.preview.extras.values():
            self.assertAlmostEqual(extra.btc_cost + extra.dividends, extra.net_funding)
            self.assertFalse(extra.btc_cost_source.startswith("estimate"), extra.ticker)

    def test_filed_bitcoin_cost_wins_over_the_transcribed_history(self):
        company = next(c for c in self.report.companies if c.ticker == "MSTR")
        cost, source = monday_preview._btc_cost("MSTR", company, {"weekly_btc_cost_usd": 1.0, "weekly_btc_purchases": 950},
                                                offline_extras(), self.report.current_btc_price)
        self.assertEqual((cost, source), (1.0, "SEC 8-K aggregate purchase price"))

    def test_unfiled_bitcoin_cost_is_estimated_from_the_weeks_closes(self):
        from dataclasses import replace
        company = next(c for c in self.report.companies if c.ticker == "MSTR")
        later = replace(company, balance_date="2099-01-04", prior_balance_date="2098-12-28")
        extras = {"yahoo": {"BTC-USD": {"rows": [{"date": "2098-12-30", "close": 100.0}, {"date": "2099-01-02", "close": 200.0}]}}}
        cost, source = monday_preview._btc_cost("MSTR", later, {"weekly_btc_purchases": 10}, extras, 1.0)
        self.assertEqual(cost, 10 * 150.0)
        self.assertTrue(source.startswith("estimate"))

    def test_warrant_flag_disappears_after_the_deadline(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        late = datetime(2026, 10, 14, 9, tzinfo=ZoneInfo("America/New_York"))
        preview = monday_preview.build_preview(self.report, self.prices, FEED, offline_extras(), now=late)
        self.assertIsNone(preview.extras["ASST"].warrants)
        self.assertIsNotNone(self.preview.extras["ASST"].warrants)

    def test_every_layout_and_style_renders_phone_ready(self):
        # Overflows include any text drawn below the 28-px phone minimum.
        from panels import themes
        for theme in themes.THEMES.values():
            for layout in monday_preview.VARIANTS:
                with self.subTest(theme=theme.key, layout=layout):
                    png, overflows = monday_preview.render_png(self.preview, theme, layout)
                    self.assertEqual(overflows, [])
                    assert_phone_ready(self, png)

    def test_extra_data_test_copy_stays_phone_ready(self):
        from panels import themes
        for theme in themes.THEMES.values():
            with self.subTest(theme=theme.key):
                png, overflows = monday_preview.render_png(self.preview, theme, extra=True)
                self.assertEqual(overflows, [])
                assert_phone_ready(self, png)
        strategy, strive = self.preview.extras["MSTR"], self.preview.extras["ASST"]
        # Sep 20 8-K: 846,000 BTC for $63.80B, $75,416 each; Strive's dashboard cost basis.
        self.assertEqual((strategy.cost_basis, strategy.average_cost), (63_800_000_000, 75_416))
        self.assertAlmostEqual(strive.average_cost, strive.cost_basis / 26_355.180562789996, places=6)

    def test_waterfall_labels_cash_by_direction(self):
        # Strategy drew $310m of cash; Strive kept $25.3m of its raise as cash.
        self.assertEqual(monday_preview.cash_step_label(self.preview.extras["MSTR"]), "FROM CASH")
        self.assertEqual(monday_preview.cash_step_label(self.preview.extras["ASST"]), "TO CASH")

    def test_strive_cash_shows_its_strc_portion(self):
        strive = self.preview.extras["ASST"]
        company = next(c for c in self.report.companies if c.ticker == "ASST")
        self.assertIn("STRC", strive.liquid_detail)
        self.assertIn(monday_preview._money(company.current.marketable_securities, False), strive.liquid_detail)

    def test_footnotes_live_on_the_page(self):
        lines = monday_preview.notes(self.preview)
        self.assertTrue(any(line.startswith("Amplification = BTC reserve ÷ net BTC reserve") for line in lines))
        self.assertTrue(any(line.startswith("BTC = the week's bitcoin purchase cost") for line in lines))


class WednesdayTests(unittest.TestCase):
    def test_ladder_sorted_and_panel_renders(self):
        prices = load_current_prices()
        report = resolve_complete_report(prices, FEED).report
        monday = monday_preview.build_preview(report, prices, FEED, offline_extras())
        data = wednesday.build(offline_extras(), FEED, monday)
        yields = [item.effective for item in data["ladder"] if item.effective is not None]
        self.assertEqual(yields, sorted(yields, reverse=True))
        sata = next(item for item in data["ladder"] if item.ticker == "SATA")
        self.assertAlmostEqual(sata.effective, sata.rate * 100 / sata.price)
        self.assertEqual(len(data["ledger"]), 4)
        self.assertEqual(data["headline"], "3M bill")
        # Strategy's USD cover reaches back through the transcribed 8-K balances (12 weeks).
        self.assertEqual(len(data["cover"]["MSTR"]["weeks"]), 12)
        self.assertEqual(data["cover"]["MSTR"]["weeks"][0][0], "2026-07-05")
        strc = data["heroes"]["STRC"]
        self.assertAlmostEqual(strc["spreads"]["3M bill"], (strc["item"].effective - data["bill"]) * 100)
        from panels import themes
        for theme in themes.THEMES.values():
            for extra in (False, True):
                with self.subTest(theme=theme.key, extra=extra):
                    png, overflows = wednesday.render_png(data, theme, extra=extra)
                    self.assertEqual(overflows, [])
                    assert_phone_ready(self, png)
        # strategy.com's STRC floor matches (debt + STRF + STRC notional − USD) ÷ BTC held; SATA uses the same formula.
        self.assertGreater(data["backing"]["STRC"]["floor"], 0)
        self.assertGreater(data["backing"]["SATA"]["floor"], 0)


class FridayPreviewTests(unittest.TestCase):
    def test_indicator_helpers(self):
        self.assertEqual(friday_preview.zone(-5)[0], "VERY CHEAP")
        self.assertEqual(friday_preview.zone(24.7)[0], "CHEAP")
        self.assertEqual(friday_preview.zone(75)[0], "FAIR VALUE")
        self.assertEqual(friday_preview.zone(120)[0], "EXPENSIVE")
        self.assertEqual(friday_preview.zone(400)[0], "VERY EXPENSIVE")
        self.assertEqual(friday_preview._rsi(list(range(1, 40))), 100.0)
        self.assertAlmostEqual(friday_preview._ema([2.0] * 30, 21), 2.0)
        self.assertIsNone(friday_preview._sma([1, 2], 3))

    def test_demo_week_renders_with_every_section(self):
        from friday import data, metrics
        dataset = data.load_demo()
        panel = metrics.compute_panel(dataset)
        derived = friday_preview.derive(panel, dataset, offline_extras(), FEED)
        self.assertEqual(sum(derived["tally"].values()), 7)
        self.assertEqual(set(derived["turnover"]), {"MSTR", "ASST", "STRC", "SATA"})
        self.assertEqual(set(derived["thresholds"]), {label for label, *_ in derived["checklist"]})
        from panels import themes
        for theme in themes.THEMES.values():
            for extra in (False, True):
                with self.subTest(theme=theme.key, extra=extra):
                    png, overflows = friday_preview.render_png(panel, derived, theme=theme, extra=extra)
                    self.assertEqual(overflows, [])
                    assert_phone_ready(self, png)
        self.assertTrue(friday_preview.notes(panel, derived))
        markets = derived["markets"]
        self.assertIsNotNone(markets["dvol"])
        self.assertIsNotNone(markets["basis"])
        self.assertIsNotNone(markets["stablecoins"])
        self.assertTrue(any(line.startswith("Test copy: DVOL") for line in friday_preview.notes(panel, derived, extra=True)))


if __name__ == "__main__":
    unittest.main()
