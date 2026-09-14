"""Regression for the September 14 upload and incomplete future editions."""
from copy import deepcopy
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image
from report import live_report
from report.calculations import calculate_company
from report.current_prices import load_current_prices
from report.presentation import build_report_view
from report.public_page import render_public_report
from report.post_export import render_post_png


class MondayReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.prices = load_current_prices()
        self.feed = json.loads(live_report.CHECKPOINT.read_text())

    def resolve(self, feed=None):
        return live_report.resolve_complete_report(self.prices, self.feed if feed is None else feed)

    def test_september_14_numbers_and_comparisons_render_on_web_and_png(self):
        result = self.resolve()
        self.assertIsNone(result.notice)
        self.assertEqual(result.report.subtitle, "Balance dates: Strategy Sep 13 · Strive Sep 11")
        strategy, strive = result.report.companies
        self.assertEqual(strategy.current.effective_common_shares, 420497000)
        self.assertEqual(strategy.current.combined_liquid_assets, 6400000000)
        self.assertEqual(strive.current.effective_common_shares, 94968764)
        self.assertEqual(strive.current.preferred_claims, 1039900579.66)
        self.assertEqual(strive.current.debt_principal, 0)
        metrics = [calculate_company(c, result.report.current_btc_price, result.report.prior_btc_price)
                   for c in result.report.companies]
        self.assertEqual(metrics[0].net_common_capital, 0)
        self.assertEqual(metrics[0].net_preferred_capital, -139300000)
        self.assertEqual(metrics[0].sats_change_pct, 0)
        self.assertAlmostEqual(metrics[0].sats_per_share, 845050 / 420497000 * 100000000)
        self.assertEqual(metrics[1].net_preferred_capital, 40254100)
        self.assertAlmostEqual(metrics[1].net_common_capital, 930815.800876725)
        for metric in metrics:
            for field in ("nav_per_share", "price_to_nav", "constant_price_nav_change_pct",
                          "amplification_change", "preferred_to_btc_change_pp"):
                self.assertIsNotNone(getattr(metric, field), field)
        view = build_report_view(result.report, prices=self.prices)
        html = render_public_report(view)
        for missing in ("Unavailable", "Not disclosed", "unverified", "NaN"):
            self.assertNotIn(missing, html)
        for company in view.companies:
            for period in company.periods:
                self.assertIn("%", period.btc_growth)
                self.assertIn("%", period.nav_growth)
        with Image.open(BytesIO(render_post_png(view))) as image:
            self.assertEqual(image.size, (1800, 1125))

    def test_new_browser_with_empty_feed_retains_reconciled_september_14(self):
        self.assertEqual(self.resolve({"schemaVersion": 1, "filings": []}).report, self.resolve().report)

    def test_future_incomplete_pair_cannot_erase_last_complete_numbers(self):
        future = deepcopy(self.feed)
        for index, row in enumerate(deepcopy(self.feed["filings"])):
            if row["filedDate"] != "2026-09-14":
                continue
            old = row["accession"]
            row["accession"] = old[:-6] + f"59990{index}"
            row["primaryDocumentUrl"] = row["primaryDocumentUrl"].replace(old.replace("-", ""), row["accession"].replace("-", ""))
            row["documents"][0]["url"] = row["primaryDocumentUrl"]
            row.update(filedDate="2026-09-21", acceptedAt="2026-09-21T12:00:00Z")
            e = row["extracted"]
            e["periodStart"] = "2026-09-14"
            e["periodEnd"] = e["balanceDate"] = "2026-09-20" if row["ticker"] == "MSTR" else "2026-09-18"
            if row["ticker"] == "ASST":
                e["priorBalanceDate"] = "2026-09-11"
                e["priorFacts"] = deepcopy(e["facts"])
                e["facts"]["net_sata_shares_change"] = 0
            future["filings"].append(row)
        raw = live_report.resolve_live_report(self.prices, future)
        self.assertIsNone(raw.report.companies[0].current.preferred_claims)
        repaired = self.resolve(future)
        self.assertEqual(repaired.report, self.resolve().report)
        self.assertIn("last complete report", repaired.notice)
        self.assertIn("Strategy Sep 13", repaired.notice)

    def test_missing_new_vwap_waits_for_complete_inputs(self):
        original = live_report.load_estimate
        with patch.object(live_report, "load_estimate", side_effect=lambda ticker, day:
                          None if day == date(2026, 9, 14) else original(ticker, day)):
            result = self.resolve()
        self.assertEqual(result.report.subtitle, "Balance dates: Strategy Sep 7 · Strive Sep 4")
        self.assertIn("last complete report", result.notice)
        self.assertIsNotNone(result.report.companies[1].prior_week_equity_vwap)

    def test_missing_prior_marks_do_not_publish_incomplete_week_over_week_cells(self):
        original = live_report._load
        def without_comparison(path):
            data = original(path)
            if path == live_report.SUPPLEMENTS:
                data["comparison_btc_prices"].pop("2026-09-07")
            return data
        with patch.object(live_report, "_load", side_effect=without_comparison):
            result = self.resolve()
        self.assertEqual(result.report.subtitle, "Balance dates: Strategy Sep 7 · Strive Sep 4")
        self.assertIsNotNone(result.report.prior_btc_price)

    def test_monday_adapter_uses_complete_publication_resolver(self):
        import monday_page
        self.assertIs(monday_page.resolve_live_report, live_report.resolve_complete_report)


if __name__ == "__main__":
    unittest.main()
