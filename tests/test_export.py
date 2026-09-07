"""Export contract checks complement the manual visual review."""
from dataclasses import replace
from html.parser import HTMLParser
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image

from report import png_export
from report.page import render_panels, render_post_preview
from report.png_export import render_png
from report.post_export import render_post_png
from report.presentation import build_report_view
from report.sample_data import sample_report


class ExportTests(unittest.TestCase):
    def test_total_bitcoin_tracks_snapshot_holdings_in_html_and_both_png_layouts(self):
        report = sample_report()
        # Distinct non-fixture totals catch a hardcoded balance, a stale prior
        # balance, or accidentally showing the weekly purchase quantity here.
        totals = (912_345, 34_567)
        companies = tuple(replace(company, current=replace(company.current, btc_holdings=total),
                                  weekly_btc_purchases=10 + index)
                          for index, (company, total) in enumerate(zip(report.companies, totals)))
        view = build_report_view(replace(report, companies=companies))
        expected = ("912,345 BTC", "34,567 BTC")
        for company, value in zip(view.companies, expected):
            self.assertEqual(company.total_bitcoin.value, value)
            self.assertNotEqual(company.total_bitcoin.value, company.bought.value)

        class TextAndAlt(HTMLParser):
            def __init__(self):
                super().__init__()
                self.content = []

            def handle_data(self, data):
                self.content.append(data)

            def handle_starttag(self, tag, attrs):
                self.content.extend(value for name, value in attrs if name == "alt" and value)

        parser = TextAndAlt()
        parser.feed(render_panels(view))
        html = " ".join(parser.content)
        for value in expected:
            self.assertIn(value, html)

        for renderer in (render_png, render_post_png):
            with self.subTest(renderer=renderer.__name__):
                drawn = []
                original = png_export._Canvas.text

                def record(canvas, item, *args, **kwargs):
                    drawn.append(item.text)
                    return original(canvas, item, *args, **kwargs)

                with patch.object(png_export._Canvas, "text", record):
                    data = renderer(view)
                image = Image.open(BytesIO(data))
                image.load()
                self.assertEqual(image.width, 1800)
                for company, value in zip(view.companies, expected):
                    self.assertIn(value, drawn)
                    self.assertIn(company.total_bitcoin.label, drawn)
                if renderer is render_post_png:
                    self.assertEqual(image.size, (1800, 1125))
                    preview = TextAndAlt()
                    preview.feed(render_post_preview(view, data))
                    for value in expected:
                        self.assertIn(value, " ".join(preview.content))

    def test_total_bitcoin_distinguishes_zero_from_unknown(self):
        report = sample_report()
        first, second = report.companies
        for balance, display in ((0, "0 BTC"), (None, "Not disclosed")):
            with self.subTest(balance=balance):
                changed = replace(first, current=replace(first.current, btc_holdings=balance))
                view = build_report_view(replace(report, companies=(changed, second)))
                self.assertEqual(view.companies[0].total_bitcoin.value, display)
                self.assertEqual(changed.current.btc_holdings, balance)

    def test_png_is_a_complete_side_by_side_illustrative_report(self):
        view = build_report_view(sample_report())
        image = Image.open(BytesIO(render_png(view)))
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.width, 1800)
        self.assertTrue(1500 <= image.height <= 1900)
        self.assertEqual(image.info["Title"], view.title)
        self.assertIn(view.label, image.info["Description"])
        self.assertIn(view.footer, image.info["Description"])
        # Both matching panels remain present in the exported canvas.
        self.assertEqual(image.getpixel((60, 240)), (255, 255, 255))
        self.assertEqual(image.getpixel((940, 240)), (255, 255, 255))


    def test_missing_values_and_nonmeaningful_ratios_fit_without_clipping(self):
        view = build_report_view(sample_report())
        company = view.companies[0]
        missing = replace(
            company,
            nav_per_share="Not disclosed", price_to_nav="N/M", stock_price="Not disclosed",
            common=replace(company.common, value="Not disclosed"),
            amplification=replace(company.amplification, value="N/M", change="N/M vs last Monday"),
        )
        image = Image.open(BytesIO(render_png(replace(view, companies=(missing, view.companies[1])))))
        self.assertEqual(image.width, 1800)


    def test_long_disclosures_expand_both_panels_instead_of_cropping(self):
        view = build_report_view(sample_report())
        original = Image.open(BytesIO(render_png(view)))
        company = view.companies[0]
        expanded = replace(company, preferred=replace(
            company.preferred,
            details=("Detailed transaction disclosure with more information. " * 15,),
            post_details=(),
        ))
        image = Image.open(BytesIO(render_png(replace(view, companies=(expanded, view.companies[1])))))
        self.assertGreater(image.height, original.height)
        with self.assertRaisesRegex(ValueError, "exactly two companies"):
            render_png(replace(view, companies=(company,)))


if __name__ == "__main__":
    unittest.main()
