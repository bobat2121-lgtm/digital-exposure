"""Actual September filings, stale-feed recovery, and safe future-week projection."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from report.calculations import calculate_company
from report.current_prices import load_current_prices
from report.live_report import CHECKPOINT, SUPPLEMENTS, resolve_live_report
from report.period_growth import get_period_growth
from report.presentation import build_report_view
from report.post_export import render_post_png


def saved_feed():
    return json.loads(CHECKPOINT.read_text())


def current_rows(feed):
    return [row for row in feed["filings"] if row["filedDate"] == "2026-09-08"]


class LiveReportTests(unittest.TestCase):
    def setUp(self):
        self.prices = load_current_prices()
        self.feed = saved_feed()

    def resolve(self, feed=None):
        return resolve_live_report(self.prices, self.feed if feed is None else feed)

    def test_actual_filings_advance_balances_and_both_capital_methods(self):
        result = self.resolve()
        self.assertEqual(result.report.subtitle, "Balance dates: Strategy Sep 7 · Strive Sep 4")
        self.assertIsNone(result.notice)
        strategy, strive = result.report.companies
        self.assertEqual(strategy.current.btc_holdings, 845050)
        self.assertEqual(strategy.current.effective_common_shares, 420497000)
        self.assertEqual(strategy.weekly_btc_purchases, 0)
        self.assertEqual(strategy.weekly_btc_sales, 0)
        m, a = [calculate_company(c, result.report.current_btc_price, result.report.prior_btc_price)
                for c in result.report.companies]
        self.assertEqual(m.net_common_capital, 0)
        self.assertEqual(m.net_preferred_capital, -176300000)
        self.assertAlmostEqual(176300000 / 1810885, 97.355713, places=5)
        self.assertEqual(strive.current.btc_holdings, 24531)
        self.assertEqual(strive.current.effective_common_shares, 94934558)
        self.assertEqual(strive.weekly_btc_purchases, 1375)
        self.assertEqual(a.net_preferred_capital, 92151100)
        self.assertAlmostEqual(a.net_common_capital, 1671988 * 24.83868215153755)
        self.assertAlmostEqual(a.sats_change_pct, 4.072205398742024)
        self.assertAlmostEqual(m.sats_change_pct, -0.003329393550954851)
        view = build_report_view(result.report, prices=self.prices)
        self.assertEqual(view.label, "")
        self.assertTrue(render_post_png(view).startswith(b"\x89PNG"))

    def test_empty_or_older_feed_cannot_roll_back_checkpoint(self):
        old = deepcopy(self.feed)
        old["filings"] = [r for r in old["filings"] if r["filedDate"] != "2026-09-08"]
        for candidate in ({"schemaVersion": 1, "filings": []}, old):
            self.assertEqual(self.resolve(candidate).report, self.resolve().report)

    def test_partial_same_accession_retains_verified_facts_with_notice(self):
        bad = deepcopy(self.feed)
        row = current_rows(bad)[0]
        row["status"] = "partial"
        row["extracted"]["extractionValidated"] = False
        row["extracted"]["missing"] = ["common_issuance_proceeds_usd"]
        row["extracted"]["facts"].pop("common_issuance_proceeds_usd", None)
        result = self.resolve(bad)
        self.assertEqual(result.report, self.resolve().report)
        self.assertIn("awaits validation", result.notice)

    def test_malformed_nested_records_cannot_crash_or_replace_checkpoint(self):
        for field, value in (("documents", [1]), ("primaryDocumentUrl", {}),
                             ("extracted.securities", []), ("extracted.priorFacts", [1]),
                             ("extracted.facts.btc_holdings", True), ("extracted.facts.btc_holdings", float("inf"))):
            with self.subTest(field=field):
                bad = deepcopy(self.feed)
                target = current_rows(bad)[0]
                parts = field.split(".")
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                self.assertEqual(self.resolve(bad).report, self.resolve().report)

    def test_changed_document_hash_requires_reconciliation(self):
        changed = deepcopy(self.feed)
        current_rows(changed)[0]["documents"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "document changed"):
            self.resolve(changed)

    def test_amendment_is_visible_and_does_not_silently_overwrite(self):
        amended = deepcopy(self.feed)
        row = deepcopy(current_rows(amended)[0])
        row["form"] = "8-K/A"
        amended["filings"].append(row)
        result = self.resolve(amended)
        self.assertIn("awaits validation", result.notice)
        self.assertEqual(result.report, self.resolve().report)

    def test_new_activity_does_not_reuse_prior_date_nav_supplements(self):
        future = deepcopy(self.feed)
        for index, row in enumerate(current_rows(deepcopy(self.feed))):
            old_accession = row["accession"]
            row["accession"] = old_accession[:-6] + f"49990{index}"
            row["primaryDocumentUrl"] = row["primaryDocumentUrl"].replace(old_accession.replace("-", ""), row["accession"].replace("-", ""))
            row["documents"][0]["url"] = row["primaryDocumentUrl"]
            row["filedDate"] = "2026-09-14"
            row["acceptedAt"] = "2026-09-14T12:00:00Z"
            e = row["extracted"]
            e["periodStart"] = "2026-09-08" if row["ticker"] == "MSTR" else "2026-09-07"
            e["periodEnd"] = e["balanceDate"] = "2026-09-13" if row["ticker"] == "MSTR" else "2026-09-11"
            if row["ticker"] == "ASST":
                e["priorBalanceDate"] = "2026-09-04"
                e["priorFacts"] = deepcopy(e["facts"])
                e["facts"]["net_sata_shares_change"] = 0
            future["filings"].append(row)
        result = self.resolve(future)
        self.assertIn("NAV inputs pending", result.notice)
        self.assertIn("Strategy Sep 13", result.report.subtitle)
        self.assertIsNone(result.report.companies[0].current.effective_common_shares)
        for company in result.report.companies:
            self.assertIsNone(company.current.preferred_claims)
        self.assertIsNone(result.report.companies[1].prior_week_equity_vwap)

    def test_mismatched_prior_date_cannot_create_multiweek_capital_proxy(self):
        bad = deepcopy(self.feed)
        row = next(r for r in current_rows(bad) if r["ticker"] == "ASST")
        row["extracted"]["priorBalanceDate"] = "2026-08-14"
        row["extracted"]["priorFacts"] = {}
        with patch("report.live_report.CHECKPOINT", Path("missing-checkpoint-for-test.json")):
            result = self.resolve(bad)
        strive = result.report.companies[1]
        self.assertIsNone(strive.prior.effective_common_shares)
        metric = calculate_company(strive, result.report.current_btc_price, result.report.prior_btc_price)
        self.assertIsNone(metric.net_common_capital)
        self.assertIsNone(metric.sats_change_pct)

    def test_missing_old_security_marks_do_not_use_todays_marks_for_prior_ratios(self):
        from report import live_report
        original = live_report._load
        def load(path):
            value = original(path)
            if path == SUPPLEMENTS:
                value["balance_marks"] = {}
            return value
        with patch("report.live_report._load", side_effect=load):
            result = self.resolve()
        m, a = result.report.companies
        self.assertIsNone(m.prior.preferred_claims)
        self.assertIsNone(a.prior.marketable_securities)
        self.assertIsNotNone(m.prior_preferred_claims_at_current_prices)
        self.assertIsNotNone(a.prior_securities_at_current_prices)

    def test_period_baselines_expire_at_quarter_and_year_boundaries(self):
        result = self.resolve()
        for day, qtd_missing, ytd_missing in (("2026-09-30", False, False), ("2026-10-01", True, False), ("2027-01-04", True, True)):
            report = replace(result.report, companies=tuple(replace(c, balance_date=day) for c in result.report.companies))
            growth = get_period_growth(report, self.prices)
            for values in growth.values():
                self.assertEqual(values["QTD"].btc_per_share_growth_pct is None, qtd_missing)
                self.assertEqual(values["YTD"].btc_per_share_growth_pct is None, ytd_missing)

    def test_constant_price_nav_uses_current_marks_without_changing_old_ratios(self):
        initial = self.resolve()
        initial_metrics = [calculate_company(c, initial.report.current_btc_price, initial.report.prior_btc_price)
                           for c in initial.report.companies]
        self.prices["quotes"]["STRC"]["price"] *= 1.1
        self.prices["quotes"]["EURUSD=X"]["price"] *= 1.1
        newer = self.resolve()
        for old, company in zip(initial_metrics, newer.report.companies):
            metric = calculate_company(company, newer.report.current_btc_price, newer.report.prior_btc_price)
            self.assertEqual(metric.prior_net_btc_amplification, old.prior_net_btc_amplification)
            self.assertNotEqual(metric.prior_nav_per_share_at_current_prices, old.prior_nav_per_share_at_current_prices)


if __name__ == "__main__":
    unittest.main()
