"""The shareable edition stays fixed-size and carries all primary values."""
from dataclasses import replace
from io import BytesIO
from unittest.mock import patch
import unittest

from PIL import Image

from report import post_export
from report.post_export import render_post_png
from report.presentation import build_report_view
from report.sample_data import sample_report


class PostExportTests(unittest.TestCase):
    def test_fixed_landscape_edition_preserves_metrics_and_disclosure(self):
        view = build_report_view(sample_report())
        drawn = []
        original_text = post_export._Canvas.text

        def record(canvas, item, *args, **kwargs):
            drawn.append(item)
            return original_text(canvas, item, *args, **kwargs)

        with patch.object(post_export._Canvas, "text", record):
            image = Image.open(BytesIO(render_post_png(view)))
        self.assertEqual(image.size, (1800, 1125))
        self.assertEqual(image.format, "PNG")
        text_items = [item.text for item in drawn]
        self.assertIn(view.label, text_items)
        self.assertEqual(image.info["Title"], view.title)
        self.assertIn(view.footer, image.info["Description"])
        for company in view.companies:
            for value in (company.stock_price, company.quote_timestamp,
                          company.nav_per_share, company.price_to_nav):
                self.assertIn(value, text_items)
            for metric in (company.bought, company.total_bitcoin, company.common, company.preferred, company.shares,
                           company.bitcoin, company.nav_change,
                           company.amplification, company.preferred_ratio):
                self.assertIn(metric.value, text_items)
            for metric in (company.shares, company.bitcoin,
                           company.amplification, company.preferred_ratio):
                if metric.short_change:
                    matches = [item for item in drawn if item.text == metric.short_change]
                    self.assertTrue(matches, metric.short_change)
                    self.assertTrue(all(item.size <= 22 for item in matches))
            for period in company.periods:
                self.assertIn(period.period, text_items)
                self.assertIn(period.btc_growth, text_items)
                self.assertIn(period.nav_growth, text_items)
        text = " ".join(text_items)
        self.assertIn("$27.50", text)
        self.assertIn("VWAP", text)
        self.assertIn("est.", text)
        for formula in ("BTC value ÷ net treasury NAV", "financing + other balance changes",
                        "Cash + liquid assets + BTC", "await verified baselines"):
            self.assertNotIn(formula, text)
        first = view.companies[0]
        labels = (first.btc_activity[0].label, first.common.label, first.preferred.label,
                  first.shares.label, first.bitcoin.label)
        self.assertEqual([text_items.index(label) for label in labels],
                         sorted(text_items.index(label) for label in labels))
        self.assertEqual(image.getpixel((45, 170)), (255, 255, 255))
        self.assertEqual(image.getpixel((925, 170)), (255, 255, 255))

    def test_missing_values_and_nonpositive_nav_fit(self):
        view = build_report_view(sample_report())
        company = view.companies[0]
        for nav in ("Not disclosed", "−$12.50", "$0.00"):
            missing = replace(
                company, nav_per_share=nav, price_to_nav="N/M",
                stock_price="Not disclosed",
                common=replace(company.common, value="Not disclosed"),
                preferred=replace(company.preferred, value="Not disclosed"),
                bitcoin=replace(company.bitcoin, value="Not disclosed"),
                amplification=replace(company.amplification, value="N/M", change="N/M vs last Monday",
                                      short_change="N/M"),
            )
            image = Image.open(BytesIO(render_post_png(replace(view, companies=(missing, view.companies[1])))))
            self.assertEqual(image.size, (1800, 1125))

    def test_invalid_company_count_is_rejected(self):
        view = build_report_view(sample_report())
        with self.assertRaisesRegex(ValueError, "exactly two companies"):
            render_post_png(replace(view, companies=view.companies[:1]))


if __name__ == "__main__":
    unittest.main()
