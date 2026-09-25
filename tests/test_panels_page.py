"""Offline routing tests for the default three-panel page."""
from io import BytesIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PIL import Image
from streamlit.testing.v1 import AppTest

import panels_page

APP = Path(__file__).resolve().parents[1] / "app.py"


def tiny_png():
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "#000").save(buffer, format="PNG")
    return buffer.getvalue()


class PanelsPageTests(TestCase):
    def setUp(self):
        png = tiny_png()
        audit = [{"metric": "BTC price", "value": "$1", "source": "test"}]
        self.calls = {}
        targets = {
            "monday_png": (png, [], None, False, audit, ["note"]),
            "wednesday_png": (png, [], audit, ["note"]),
            "friday_png": (png, [], "2026-09-18", audit, ["note"]),
            "_extras": {"stale": []},
        }
        for name, value in targets.items():
            patcher = patch.object(panels_page, name, return_value=value)
            self.calls[name] = patcher.start()
            self.addCleanup(patcher.stop)

    def app(self, query=None):
        app = AppTest.from_file(str(APP), default_timeout=10)
        app.query_params.update(query or {})
        return app.run()

    def test_default_opens_monday_panel_only(self):
        app = self.app()
        self.assertEqual(len(app.exception), 0, [item.message for item in app.exception])
        self.assertEqual([tab.label for tab in app.tabs], list(panels_page.TABS.values()))
        self.calls["monday_png"].assert_called_once_with("neon", "c", False)
        self.calls["wednesday_png"].assert_not_called()
        self.calls["friday_png"].assert_not_called()
        self.assertEqual(app.query_params["report"], ["monday"])
        self.assertIsNone(app.query_params.get("theme"))  # the default style keeps the plain URL

    def test_deep_link_selects_tab_and_theme(self):
        app = self.app({"report": "friday", "theme": "classic"})
        self.assertEqual(len(app.exception), 0, [item.message for item in app.exception])
        self.calls["friday_png"].assert_called_once_with("classic", False)
        self.calls["monday_png"].assert_not_called()
        self.assertEqual(app.query_params["report"], ["friday"])

    def test_unknown_values_fall_back_to_monday_neon(self):
        app = self.app({"report": "sunday", "theme": "vapor", "layout": "z"})
        self.assertEqual(len(app.exception), 0, [item.message for item in app.exception])
        self.calls["monday_png"].assert_called_once_with("neon", "c", False)
        self.assertEqual(app.query_params["theme"], ["neon"])

    def test_monday_layout_link(self):
        app = self.app({"layout": "b"})
        self.assertEqual(len(app.exception), 0, [item.message for item in app.exception])
        self.calls["monday_png"].assert_called_once_with("neon", "b", False)

    def test_extra_link_opens_the_test_copy(self):
        app = self.app({"report": "wednesday", "extra": "1"})
        self.assertEqual(len(app.exception), 0, [item.message for item in app.exception])
        self.calls["wednesday_png"].assert_called_once_with("neon", True)
        self.assertEqual(app.query_params["extra"], ["1"])

    def test_classic_link_keeps_the_detailed_reports(self):
        with patch("monday_page.render") as monday:
            app = self.app({"classic": "1"})
        self.assertEqual(len(app.exception), 0, [item.message for item in app.exception])
        monday.assert_called_once_with()
        self.calls["monday_png"].assert_not_called()
