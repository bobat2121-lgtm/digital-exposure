from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from report import dated_baselines, live_report
from report.current_prices import load_current_prices
from report.publication_check import publication_check


class PublicationCheckTests(unittest.TestCase):
    def test_complete_edition_produces_auditable_html_and_png(self):
        feed = json.loads(live_report.CHECKPOINT.read_text())
        summary, html, png = publication_check(load_current_prices(), feed)
        self.assertEqual(summary["status"], "complete")
        self.assertIn("Strategy", html)
        self.assertTrue(png.startswith(b"\x89PNG"))

    def test_missing_latest_claims_fail_instead_of_publishing_older_edition(self):
        original = live_report._load
        def missing(path):
            value = original(path)
            if path == live_report.SUPPLEMENTS:
                latest = max(value["balances"]["MSTR"])
                value["balances"]["MSTR"][latest].pop("preferred_claims_usd")
            return value
        feed = json.loads(live_report.CHECKPOINT.read_text())
        with patch.object(live_report, "_load", side_effect=missing):
            with self.assertRaises(ValueError):
                publication_check(load_current_prices(), feed)

    def test_calendar_rollover_uses_exact_quarter_and_year_end(self):
        self.assertEqual(dated_baselines.baseline_dates(date(2026, 10, 5)),
                         {"QTD": "2026-09-30", "YTD": "2025-12-31"})
        self.assertEqual(dated_baselines.baseline_dates(date(2027, 1, 4)),
                         {"QTD": "2026-12-31", "YTD": "2026-12-31"})

    def test_future_baselines_reprice_claims_and_securities_without_nearest_date_fallback(self):
        row = {"balance_date": "2026-09-30", "sources": ["https://www.strive.com/treasury"],
               "basis": "test fixture", "btc_holdings": 100, "effective_common_shares": 1000,
               "cash": 50, "held_strc_shares": 5, "debt_principal": 0,
               "preferred_claims_usd": 20, "preferred_claims_eur": 10}
        with TemporaryDirectory() as folder:
            path = Path(folder) / "baselines.json"
            path.write_text(json.dumps({"schemaVersion": 1, "balances": {"ASST": {"2026-09-30": row}}}))
            with patch.object(dated_baselines, "BASELINES", path):
                actual = dated_baselines.dated_baseline("ASST", "2026-09-30", 1.2, 99)
                self.assertEqual(actual.marketable_securities, 495)
                self.assertEqual(actual.preferred_claims, 32)
                self.assertIsNone(dated_baselines.dated_baseline("ASST", "2026-10-01", 1.2, 99))
                invalid = deepcopy(row)
                invalid["debt_principal"] = None
                path.write_text(json.dumps({"schemaVersion": 1, "balances": {"ASST": {"2026-09-30": invalid}}}))
                with self.assertRaises(ValueError):
                    dated_baselines.dated_baseline("ASST", "2026-09-30", 1.2, 99)


if __name__ == "__main__":
    unittest.main()
