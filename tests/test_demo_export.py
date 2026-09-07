"""The legacy demo export uses the standard social layout and real period data."""
from dataclasses import replace
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image

from report import post_export
from report.current_report import current_report
from report.demo_export import demo_report_view, render_demo_png, GREEN, RED
from report.historical_data import historical_report
from report.presentation import build_report_view
from report.post_export import render_post_png
from report.sample_data import sample_report


class DemoExportTests(unittest.TestCase):
    def test_all_editions_fit_and_keep_primary_figures_and_disclosures(self):
        for source in (current_report, historical_report, sample_report):
            with self.subTest(edition=source.__name__):
                view = demo_report_view(build_report_view(source()))
                drawn = []
                original = post_export._Canvas.text

                def record(canvas, item, *args, **kwargs):
                    drawn.append(item)
                    return original(canvas, item, *args, **kwargs)

                with patch.object(post_export._Canvas, "text", record):
                    image = Image.open(BytesIO(render_demo_png(view)))
                self.assertEqual(image.size, (1800, 1125))
                text = [item.text for item in drawn]
                self.assertIn(view.label, text)
                self.assertTrue(view.label.startswith("REDESIGN PREVIEW"))
                self.assertNotIn("await verified baselines", " ".join(text))
                for company in view.companies:
                    for value in (company.stock_price, company.quote_timestamp,
                                  company.nav_per_share, company.price_to_nav):
                        self.assertIn(value, text)
                    for metric in (company.bought, company.total_bitcoin, company.common, company.preferred, company.shares,
                                   company.bitcoin, company.nav_change,
                                   company.amplification, company.preferred_ratio):
                        self.assertIn(metric.value, text)
                    growth = company.bitcoin.short_change
                    growth_items = [item for item in drawn if item.text == growth]
                    self.assertTrue(growth_items)
                    self.assertTrue(all(item.size <= 22 for item in growth_items))
                    if source is not sample_report:
                        self.assertEqual(tuple(period.period for period in company.periods), ("QTD", "YTD"))
                    else:
                        self.assertEqual(company.periods, ())
                    for period in company.periods:
                        self.assertIn(period.btc_growth, text)
                        self.assertIn(period.nav_growth, text)
                        if source is not sample_report:
                            self.assertNotIn(period.btc_growth, ("—", "Not disclosed", "Unavailable"))
                            self.assertNotIn(period.nav_growth, ("—", "Not disclosed", "Unavailable"))
                self.assertNotIn("BTC value ÷ net treasury NAV", text)
                emphasized = [item for item in drawn if item.color in (GREEN, RED)]
                self.assertTrue(emphasized)
                self.assertTrue(all(item.size <= 22 for item in emphasized))

    def test_legacy_wrapper_uses_standard_layout_and_rejects_invalid_company_count(self):
        standard = build_report_view(current_report())
        self.assertEqual(render_demo_png(standard), render_post_png(standard))
        demo = demo_report_view(standard)
        self.assertTrue(demo.label.startswith("REDESIGN PREVIEW"))
        with self.assertRaisesRegex(ValueError, "exactly two companies"):
            render_demo_png(replace(demo, companies=demo.companies[:1]))


if __name__ == "__main__":
    unittest.main()
