"""Quarter rollover from weekly balances, and STRE rows in Strategy filings."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from report.calculations import calculate_company
from report.current_prices import load_current_prices
from report.live_report import resolve_live_report
from report.period_growth import get_period_growth
from report.presentation import build_report_view
from report.post_export import render_post_png

FIXTURES = Path(__file__).parent / "fixtures"
CHECKPOINT = FIXTURES / "filings-2026-09-08.json"
SUPPLEMENTS = FIXTURES / "supplements-2026-09-08.json"
SHIFT = timedelta(days=28)
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _shift(value):
    """Move every ISO date (or timestamp) four weeks later, keeping weekdays."""
    if isinstance(value, dict):
        return {_shift(key): _shift(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_shift(item) for item in value]
    if isinstance(value, str) and DAY.match(value):
        moved = (date.fromisoformat(value[:10]) + SHIFT).isoformat()
        return moved + value[10:]
    return value


def _q4_feed():
    """The Aug 31 / Sep 8 fixture pair becomes the last Q3 and first Q4 weeks."""
    feed = json.loads(CHECKPOINT.read_text())
    rows = []
    for row in feed["filings"]:
        moved = deepcopy(row)
        extraction = moved["extracted"]
        for key in ("periodStart", "periodEnd", "balanceDate", "priorBalanceDate"):
            if extraction.get(key):
                extraction[key] = _shift(extraction[key])
        for key in ("filedDate", "acceptedAt", "documentFetchedAt"):
            if moved.get(key):
                moved[key] = _shift(moved[key])
        for document in moved.get("documents", []):
            if document.get("fetchedAt"):
                document["fetchedAt"] = _shift(document["fetchedAt"])
        rows.append(moved)
    return {"schemaVersion": 1, "filings": rows}


def _q4_supplements():
    supplements = json.loads(SUPPLEMENTS.read_text())
    for key in ("balances", "comparison_btc_prices", "comparison_release_dates", "balance_marks"):
        section = supplements[key]
        if key == "balances":
            supplements[key] = {ticker: _shift(dates) for ticker, dates in section.items()}
        else:
            supplements[key] = {_shift(day): _shift(value) for day, value in section.items()}
    return supplements


class QuarterRolloverTests(unittest.TestCase):
    def setUp(self):
        self.prices = load_current_prices()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        supplements = Path(self.directory.name) / "supplements.json"
        supplements.write_text(json.dumps(_q4_supplements()))
        # No committed checkpoint: the rollover must come from the feed alone.
        for name, value in (("CHECKPOINT", Path(self.directory.name) / "absent.json"), ("SUPPLEMENTS", supplements)):
            patcher = patch("report.live_report." + name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_first_q4_week_starts_from_last_q3_weekly_balance(self):
        report = resolve_live_report(self.prices, _q4_feed()).report
        self.assertEqual([c.balance_date for c in report.companies], ["2026-10-05", "2026-10-02"])
        growth = get_period_growth(report, self.prices)
        for company, baseline in zip(report.companies, ("2026-09-27", "2026-09-25")):
            qtd, ytd = growth[company.ticker]["QTD"], growth[company.ticker]["YTD"]
            self.assertEqual(qtd.baseline_date, baseline)
            self.assertIsNone(ytd.baseline_date)
            self.assertIsNotNone(ytd.btc_per_share_growth_pct)
            # Week one of the quarter is exactly that week's per-share change.
            weekly = calculate_company(company, report.current_btc_price, report.prior_btc_price)
            self.assertAlmostEqual(qtd.btc_per_share_growth_pct, weekly.sats_change_pct, places=9)

    def test_rollover_note_reaches_the_rendered_panel(self):
        report = resolve_live_report(self.prices, _q4_feed()).report
        view = build_report_view(report, prices=self.prices)
        notes = {c.ticker: [p.baseline_note for p in c.periods] for c in view.companies}
        self.assertEqual(notes, {"MSTR": ["from Sep 27 balance", ""], "ASST": ["from Sep 25 balance", ""]})
        self.assertTrue(render_post_png(view).startswith(b"\x89PNG"))

    def test_missing_quarter_end_week_leaves_qtd_unavailable(self):
        feed = _q4_feed()
        feed["filings"] = [row for row in feed["filings"] if row["extracted"]["balanceDate"] > "2026-09-30"]
        for row in feed["filings"]:
            row["extracted"].pop("priorFacts", None)
        report = resolve_live_report(self.prices, feed).report
        growth = get_period_growth(report, self.prices)
        for values in growth.values():
            self.assertIsNone(values["QTD"].btc_per_share_growth_pct)

    def test_stale_weekly_balance_is_not_a_quarter_start(self):
        """A balance more than ten days before quarter end is not used."""
        feed = _q4_feed()
        for row in feed["filings"]:
            extraction = row["extracted"]
            if extraction["balanceDate"] < "2026-09-30":
                for key in ("periodStart", "periodEnd", "balanceDate"):
                    extraction[key] = (date.fromisoformat(extraction[key]) - timedelta(days=14)).isoformat()
            extraction.pop("priorFacts", None)
            extraction.pop("priorBalanceDate", None)
        report = resolve_live_report(self.prices, feed).report
        for company in report.companies:
            self.assertEqual(company.period_baselines, ())


class StreRowTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("CHECKPOINT", CHECKPOINT), ("SUPPLEMENTS", SUPPLEMENTS)):
            patcher = patch("report.live_report." + name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.prices = load_current_prices()
        self.feed = json.loads(CHECKPOINT.read_text())

    def _strategy_row(self, feed):
        return next(row for row in feed["filings"] if row["ticker"] == "MSTR" and row["filedDate"] == "2026-09-08")

    def test_stre_issuance_keeps_the_filing_eligible_and_counts_its_cash(self):
        feed = deepcopy(self.feed)
        self._strategy_row(feed)["extracted"]["securities"]["STRE"] = {"issuedShares": 100_000, "netIssuanceProceedsUsd": 10_000_000}
        report = resolve_live_report(self.prices, feed).report
        self.assertIn("Strategy Sep 7", report.subtitle)
        strategy = report.companies[0]
        self.assertEqual(strategy.preferred_activity[1].series, "STRF / STRK / STRD / STRE")
        metric = calculate_company(strategy, report.current_btc_price, report.prior_btc_price)
        self.assertEqual(metric.net_preferred_capital, -176_300_000 + 10_000_000)

    def test_reported_stre_repurchase_is_used_when_present(self):
        feed = deepcopy(self.feed)
        self._strategy_row(feed)["extracted"]["securities"]["STRE"] = {
            "issuedShares": 0, "netIssuanceProceedsUsd": 0, "repurchasedShares": 1_000, "repurchaseCashUsd": 90_000}
        strategy = resolve_live_report(self.prices, feed).report.companies[0]
        metric = calculate_company(strategy, 1, 1)
        self.assertEqual(metric.net_preferred_capital, -176_300_000 - 90_000)

    def test_incomplete_stre_issuance_is_still_rejected(self):
        feed = deepcopy(self.feed)
        self._strategy_row(feed)["extracted"]["securities"]["STRE"] = {"issuedShares": 100_000}
        report = resolve_live_report(self.prices, feed).report
        # The previous verified edition remains; no STRE cash is invented.
        self.assertIn("Strategy Sep 7", report.subtitle)
        self.assertEqual(report.companies[0].preferred_activity[1].series, "STRF / STRK / STRD")


if __name__ == "__main__":
    unittest.main()
