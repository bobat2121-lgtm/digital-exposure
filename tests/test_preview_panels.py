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

    def test_amplification_and_funding_follow_reported_balances(self):
        for company in self.report.companies:
            extra = self.preview.extras[company.ticker]
            bitcoin = company.current.btc_holdings * self.report.current_btc_price
            expected = (company.current.debt_principal + company.current.preferred_claims) / bitcoin * 100
            self.assertAlmostEqual(extra.amplification_pct, expected)
            self.assertIsNotNone(extra.net_funding)
        strategy = self.preview.extras["MSTR"]
        # Sep 14–20: $0 common, −$174.0m STRC, cash and reserve fell $310m.
        self.assertEqual(strategy.liquid_change, -310_000_000)
        self.assertAlmostEqual(strategy.net_funding, 0 - 174_000_000 + 310_000_000)

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
        self.assertTrue(any("Amplification = (debt + preferred claims) ÷ BTC value" in line for line in lines))


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
        strc = data["heroes"]["STRC"]
        self.assertAlmostEqual(strc["spreads"]["3M bill"], (strc["item"].effective - data["bill"]) * 100)
        from panels import themes
        for theme in themes.THEMES.values():
            with self.subTest(theme=theme.key):
                png, overflows = wednesday.render_png(data, theme)
                self.assertEqual(overflows, [])
                assert_phone_ready(self, png)


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
            with self.subTest(theme=theme.key):
                png, overflows = friday_preview.render_png(panel, derived, theme=theme)
                self.assertEqual(overflows, [])
                assert_phone_ready(self, png)
        self.assertTrue(friday_preview.notes(panel, derived))


if __name__ == "__main__":
    unittest.main()
