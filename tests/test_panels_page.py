"""Offline tests for the default three-report page: routing, and each report's
web layout rendered end to end from real offline data (saved snapshot,
committed filings, demo Friday week)."""
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "sources" / "friday") not in sys.path:
    sys.path.insert(0, str(ROOT / "sources" / "friday"))

import panels_page  # noqa: E402

APP = ROOT / "app.py"


def in_order(node):
    """Every element under ``node`` as (type, label), in page order."""
    rows = [(getattr(node, "type", None), getattr(node, "label", None))]
    for key in sorted(getattr(node, "children", None) or {}):
        rows += in_order(node.children[key])
    return rows


def tiny_png():
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "#000").save(buffer, format="PNG")
    return buffer.getvalue()


@lru_cache(maxsize=1)
def offline_reports():
    from friday import data as friday_data, metrics
    from panels import extras as extras_module, friday_preview, monday_preview, wednesday
    from report.current_prices import load_current_prices
    from report.live_report import resolve_complete_report
    extras = extras_module.load_extras(offline=True)
    prices = load_current_prices()
    feed = json.loads((ROOT / "data" / "latest-report-filings.json").read_text())
    preview = monday_preview.build_preview(resolve_complete_report(prices, feed).report, prices, feed, extras)
    data = wednesday.build(extras, feed, preview)
    demo = friday_data.load_demo()
    panel = metrics.compute_panel(demo)
    derived = friday_preview.derive(panel, demo, extras, feed)
    common = {"png": tiny_png(), "overflows": [], "notices": []}
    return {
        "_extras": {"stale": []},
        "monday_report": {**common, "preview": preview, "audit": monday_preview.audit_rows(preview),
                          "notes": monday_preview.notes(preview)},
        "wednesday_report": {**common, "data": data, "audit": wednesday.audit_rows(data), "notes": wednesday.notes(data, True)},
        "friday_report": {**common, "panel": panel, "derived": derived, "audit": friday_preview.audit_rows(panel, derived),
                          "notes": friday_preview.notes(panel, derived, (), True)},
    }


class PanelsPageTests(TestCase):
    def setUp(self):
        self.calls = {}
        for name, value in offline_reports().items():
            patcher = patch.object(panels_page, name, return_value=value)
            self.calls[name] = patcher.start()
            self.addCleanup(patcher.stop)

    def app(self, query=None):
        app = AppTest.from_file(str(APP), default_timeout=60)
        app.query_params.update(query or {})
        return app.run()

    def assert_report(self, app):
        self.assertEqual(len(app.exception), 0, [item.message for item in app.exception])
        # Expanders with an icon come back from AppTest as status blocks.
        self.assertEqual([block.label for block in app.status], ["Formulas", "Sources, notes and audit values"])
        self.assertEqual(len(app.get("download_button")), 1)
        # The X image download closes the tab, after the formulas and sources.
        order = in_order(app.main)
        self.assertLess(order.index(("status", "Sources, notes and audit values")),
                        order.index(("download_button", "Download X image")))
        # One style, one funding layout: no selectors or test toggles on the shared page.
        self.assertEqual(len(app.segmented_control), 0)
        self.assertEqual(len(app.toggle), 0)

    def test_default_opens_monday_only(self):
        app = self.app()
        self.assert_report(app)
        self.assertEqual([tab.label for tab in app.tabs], list(panels_page.TABS.values()))
        self.calls["monday_report"].assert_called_once_with()
        self.calls["wednesday_report"].assert_not_called()
        self.calls["friday_report"].assert_not_called()
        self.assertEqual(app.query_params["report"], ["monday"])

    def test_each_report_renders_its_web_layout(self):
        for report in ("wednesday", "friday"):
            with self.subTest(report=report):
                app = self.app({"report": report})
                self.assert_report(app)
                self.calls[f"{report}_report"].assert_called()
                self.assertEqual(app.query_params["report"], [report])
        self.calls["monday_report"].assert_not_called()

    def test_retired_options_leave_shared_links(self):
        app = self.app({"report": "sunday", "theme": "vapor", "layout": "b", "extra": "1"})
        self.assert_report(app)
        self.calls["monday_report"].assert_called_once_with()
        self.assertEqual(app.query_params["report"], ["monday"])
        for retired in ("theme", "layout", "extra"):
            self.assertNotIn(retired, app.query_params)

    def test_classic_link_keeps_the_detailed_reports(self):
        with patch("monday_page.render") as monday:
            app = self.app({"classic": "1"})
        self.assertEqual(len(app.exception), 0, [item.message for item in app.exception])
        monday.assert_called_once_with()
        self.calls["monday_report"].assert_not_called()


class FormulaListTests(TestCase):
    def test_every_report_lists_its_formulas(self):
        from panels import web
        for sections in (web.MONDAY_FORMULAS, web.WEDNESDAY_FORMULAS, web.FRIDAY_FORMULAS):
            items = [item for _, entries in sections for item in entries]
            self.assertGreaterEqual(len(items), 8)
            self.assertTrue(all(term and text for term, text in items))
        terms = {term for _, entries in web.MONDAY_FORMULAS for term, _ in entries}
        self.assertTrue({"Amplification, Strategy", "Amplification, Strive", "BTC", "DIVs"} <= terms)
