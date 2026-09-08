"""Gross BTC activity stays distinct across the public page and both PNG layouts."""
from dataclasses import replace
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image

from report.page import render_panels, render_post_preview
from report.png_export import _Canvas, render_png
from report.post_export import render_post_png
from report.presentation import build_report_view
from report.public_page import render_public_report
from report.sample_data import sample_report


class BitcoinActivityDisplayTests(unittest.TestCase):
    def view(self, bought, sold, *, ending_holdings=500):
        source = sample_report()
        first, second = source.companies
        first = replace(first, weekly_btc_purchases=bought, weekly_btc_sales=sold,
                        prior=replace(first.prior, btc_holdings=1_000),
                        current=replace(first.current, btc_holdings=ending_holdings))
        second = replace(second, weekly_btc_purchases=None, weekly_btc_sales=None)
        return build_report_view(replace(source, companies=(first, second)))

    def assert_rendered(self, view, expected):
        self.assertEqual([(m.label, m.value) for m in view.companies[0].btc_activity], expected)
        for renderer in (render_public_report, render_panels):
            html = renderer(view)
            for label, value in expected:
                self.assertIn(f"<h3>{label}</h3>", html)
                self.assertIn(value.replace("<", "&lt;"), html)
            self.assertIn("Total BTC held", html)
            for label in {"Bitcoin Bought", "Bitcoin Sold"} - {item[0] for item in expected}:
                self.assertNotIn(f"<h3>{label}</h3>", html)

        for renderer in (render_post_png, render_png):
            drawn = []
            original = _Canvas.text

            def record(canvas, item, *args, **kwargs):
                drawn.append(item.text)
                return original(canvas, item, *args, **kwargs)

            with patch.object(_Canvas, "text", record):
                data = renderer(view)
            image = Image.open(BytesIO(data))
            image.load()
            self.assertEqual(image.width, 1800)
            if renderer is render_post_png:
                self.assertEqual(image.height, 1125)
                alt = render_post_preview(view, data)
                for label, value in expected:
                    self.assertIn(f"{label}: {value}".replace("<", "&lt;"), alt)
            for label, value in expected:
                self.assertIn(label, drawn)
                self.assertIn(value, drawn)
            for label in {"Bitcoin Bought", "Bitcoin Sold"} - {item[0] for item in expected}:
                self.assertNotIn(label, drawn)
            # A two-sided week must not drop the other company's final rows.
            self.assertEqual(drawn.count("Preferred / BTC"), 2)
            self.assertEqual(drawn.count("Total BTC held"), 2)
            for company in view.companies:
                self.assertIn(company.total_bitcoin.value, drawn)
                self.assertIn(company.preferred_ratio.value, drawn)

    def test_sales_only_and_complete_liquidation_keep_the_sale_label(self):
        view = self.view(None, 1_000, ending_holdings=0)
        self.assert_rendered(view, [("Bitcoin Sold", "1,000 BTC")])
        self.assertEqual(view.companies[0].total_bitcoin.value, "0 BTC")

    def test_buy_and_sale_are_separate_gross_amounts(self):
        view = self.view(1_250, 300)
        self.assert_rendered(view, [("Bitcoin Bought", "1,250 BTC"), ("Bitcoin Sold", "300 BTC")])
        self.assertNotIn("950 BTC", render_public_report(view))

    def test_purchase_only_and_reported_zero_sales_keep_the_buy_label(self):
        self.assert_rendered(self.view(1_250, 0), [("Bitcoin Bought", "1,250 BTC")])

    def test_falling_holdings_do_not_establish_a_sale(self):
        self.assert_rendered(self.view(None, None), [("Bitcoin activity", "Not disclosed")])

    def test_confirmed_zero_is_not_undisclosed(self):
        self.assert_rendered(self.view(0, 0), [("Bitcoin Bought", "0 BTC"), ("Bitcoin Sold", "0 BTC")])
        self.assertEqual(self.view(0, None).companies[0].btc_activity[0].value, "0 BTC")
        self.assertEqual(self.view(None, 0).companies[0].btc_activity[0].label, "Bitcoin Sold")

    def test_reported_fractions_remain_visible_in_both_formats(self):
        self.assert_rendered(self.view(125.5, .00000001),
                             [("Bitcoin Bought", "125.5 BTC"), ("Bitcoin Sold", "0.00000001 BTC")])
        self.assert_rendered(self.view(None, .000000005), [("Bitcoin Sold", "<0.00000001 BTC")])

    def test_large_fractional_activity_still_fits_the_compact_export(self):
        view = self.view(1_234_567.12345678, 1_234_567.12345678)
        self.assertIn('class="bitcoin-pair multi-activity long-activity"', render_public_report(view))
        self.assert_rendered(view,
                             [("Bitcoin Bought", "1,234,567.12345678 BTC"),
                              ("Bitcoin Sold", "1,234,567.12345678 BTC")])


if __name__ == "__main__":
    unittest.main()
