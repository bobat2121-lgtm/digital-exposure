"""The Friday bridge must publish the same validated financial model as Monday."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from report import live_report
from report.current_prices import load_current_prices
from report.friday_inputs import NUMERIC_FIELDS, resolve_friday_inputs


NOW = datetime(2026, 9, 8, 23, 30, tzinfo=timezone.utc)
FUTURE = datetime(2026, 9, 14, 15, 30, tzinfo=timezone.utc)


def future_rows(feed):
    """Synthetic next-week accepted records based on the actual parser schema."""
    rows = []
    for index, current in enumerate(row for row in feed["filings"] if row["filedDate"] == "2026-09-08"):
        row = deepcopy(current)
        previous_accession = row["accession"]
        row["accession"] = previous_accession[:-6] + f"49990{index}"
        row["primaryDocumentUrl"] = row["primaryDocumentUrl"].replace(previous_accession.replace("-", ""), row["accession"].replace("-", ""))
        row["documents"][0]["url"] = row["primaryDocumentUrl"]
        row.update(filedDate="2026-09-14", acceptedAt="2026-09-14T12:00:00Z")
        extracted = row["extracted"]
        extracted["periodStart"] = "2026-09-08" if row["ticker"] == "MSTR" else "2026-09-07"
        extracted["periodEnd"] = extracted["balanceDate"] = "2026-09-13" if row["ticker"] == "MSTR" else "2026-09-11"
        if row["ticker"] == "ASST":
            extracted["priorBalanceDate"] = "2026-09-04"
            extracted["priorFacts"] = deepcopy(extracted["facts"])
            extracted["facts"]["net_sata_shares_change"] = 0
        rows.append(row)
    return rows


class FridayInputsTests(unittest.TestCase):
    def setUp(self):
        self.prices = load_current_prices()
        self.feed = json.loads(live_report.CHECKPOINT.read_text(encoding="utf-8"))

    def resolve(self, feed=None, prices=None, now=NOW):
        return resolve_friday_inputs(self.prices if prices is None else prices,
                                     self.feed if feed is None else feed, now=now)

    def test_actual_september_checkpoint_maps_exact_monday_balances(self):
        shared = live_report.resolve_live_report(self.prices, self.feed)
        result = self.resolve()
        self.assertEqual(result["version"], shared.version)
        self.assertEqual(result["balance_dates"], {"MSTR": "2026-09-07", "ASST": "2026-09-04"})
        self.assertIsNone(result["notice"])
        for company in shared.report.companies:
            with self.subTest(ticker=company.ticker):
                mapped = result["companies"][company.ticker]
                current = company.current
                self.assertEqual(mapped["btc_held"], current.btc_holdings)
                self.assertEqual(mapped["shares"], current.effective_common_shares)
                self.assertEqual(mapped["debt_usd"], current.debt_principal)
                self.assertEqual(mapped["preferred_usd"], current.preferred_claims)
                assets = current.combined_liquid_assets if current.combined_liquid_assets is not None else current.cash + current.marketable_securities
                self.assertEqual(mapped["cash_usd"] + mapped["securities_usd"], assets)
                self.assertTrue(mapped["allow_post_friday_disclosure"])
                self.assertEqual(mapped["publication_basis"], "latest_monday_disclosures")
                source = next(row for row in self.feed["filings"] if row["accession"] == mapped["accession"])
                self.assertEqual(mapped["source"], source["primaryDocumentUrl"])
                self.assertEqual(datetime.fromisoformat(mapped["disclosed_at"]), datetime.fromisoformat(source["acceptedAt"].replace("Z", "+00:00")))
                self.assertGreater(mapped["disclosed_at"][:10], "2026-09-04")
        mstr, asst = (result["companies"][ticker] for ticker in ("MSTR", "ASST"))
        self.assertEqual(mstr["btc_held"], 845050)
        self.assertEqual(mstr["shares"], 420497000)
        self.assertEqual(mstr["securities_usd"], 0)
        self.assertEqual(asst["btc_held"], 24531)
        self.assertEqual(asst["shares"], 94934558)

    def test_empty_or_older_feed_uses_same_published_checkpoint_as_monday(self):
        actual = self.resolve()
        result = self.resolve({"schemaVersion": 1, "filings": []})
        self.assertEqual(result, actual)

    def test_newer_single_filing_waits_for_same_pair_without_mixing_issuers(self):
        feed = deepcopy(self.feed)
        feed["filings"].append(next(row for row in future_rows(feed) if row["ticker"] == "MSTR"))
        result = self.resolve(feed, now=FUTURE)
        prior = self.resolve()
        self.assertEqual(result["companies"], prior["companies"])
        self.assertEqual(result["publications"], prior["publications"])
        self.assertIn("awaiting its matching", result["notice"])

    def test_new_complete_pair_keeps_missing_nav_fields_unknown(self):
        feed = deepcopy(self.feed)
        rows = future_rows(feed)
        mstr = next(row for row in rows if row["ticker"] == "MSTR")
        asst = next(row for row in rows if row["ticker"] == "ASST")
        mstr["extracted"]["facts"].pop("usd_reserve_usd")
        mstr["extracted"]["facts"].pop("usd_cash_usd")
        asst["extracted"]["facts"].pop("cash_and_equivalents_usd")
        feed["filings"].extend(rows)
        result = self.resolve(feed, now=FUTURE)
        self.assertEqual(result["balance_dates"], {"MSTR": "2026-09-13", "ASST": "2026-09-11"})
        self.assertIn("NAV inputs pending", result["notice"])
        self.assertIsNone(result["companies"]["MSTR"]["shares"])
        for company in result["companies"].values():
            self.assertIsNone(company["preferred_usd"])
            self.assertIsNone(company["debt_usd"])
            self.assertIsNone(company["cash_usd"])
            self.assertIsNotNone(company["btc_held"])
        self.assertIsNone(result["companies"]["MSTR"]["securities_usd"])

    def test_partial_same_accession_keeps_checkpoint_values_and_provenance(self):
        feed = deepcopy(self.feed)
        row = next(row for row in feed["filings"] if row["ticker"] == "MSTR" and row["filedDate"] == "2026-09-08")
        row["status"] = "partial"
        row["extracted"]["extractionValidated"] = False
        result = self.resolve(feed)
        self.assertEqual(result["companies"], self.resolve()["companies"])
        self.assertIn("awaits validation", result["notice"])

    def test_shared_dated_debt_changes_and_missing_values_flow_through(self):
        original = live_report._load
        before = self.resolve()
        for debt in (5_753_703_000, None):
            def load(path):
                data = original(path)
                if path == live_report.SUPPLEMENTS:
                    data["revision"] = "debt-test-" + str(debt)
                    extra = data["balances"]["MSTR"]["2026-09-07"]
                    if debt is None:
                        extra.pop("debt_principal", None)
                    else:
                        extra["debt_principal"] = debt
                return data
            with self.subTest(debt=debt), patch.object(live_report, "_load", side_effect=load):
                shared = live_report.resolve_live_report(self.prices, self.feed)
                result = self.resolve()
                self.assertEqual(result["companies"]["MSTR"]["debt_usd"], debt)
                self.assertEqual(result["companies"]["MSTR"]["debt_usd"], shared.report.companies[0].current.debt_principal)
                self.assertNotEqual(result["input_version"], before["input_version"])

    def test_new_reported_debt_fact_is_identical_to_shared_resolver(self):
        feed = deepcopy(self.feed)
        feed["filings"].extend(future_rows(feed))
        mstr = next(row for row in feed["filings"] if row["ticker"] == "MSTR" and row["filedDate"] == "2026-09-14")
        mstr["extracted"]["facts"]["debt_principal"] = 5_000_000_000
        result = self.resolve(feed, now=FUTURE)
        self.assertEqual(result["companies"]["MSTR"]["debt_usd"], 5_000_000_000)
        self.assertIsNone(result["companies"]["MSTR"]["preferred_usd"])

    def test_changed_strc_fx_marks_update_inputs_without_changing_filing_version(self):
        before = self.resolve()
        prices = deepcopy(self.prices)
        prices["quotes"]["STRC"]["price"] += 2
        prices["quotes"]["EURUSD=X"]["price"] += .1
        result = self.resolve(prices=prices)
        self.assertEqual(result["version"], before["version"])
        self.assertNotEqual(result["input_version"], before["input_version"])
        self.assertGreater(result["companies"]["ASST"]["securities_usd"], before["companies"]["ASST"]["securities_usd"])
        self.assertGreater(result["companies"]["MSTR"]["preferred_usd"], before["companies"]["MSTR"]["preferred_usd"])

    def test_legacy_undated_fallback_is_not_a_new_friday_publication(self):
        with patch.object(live_report, "CHECKPOINT", Path("missing-friday-checkpoint-for-test.json")):
            result = self.resolve({"schemaVersion": 1, "filings": []})
        for company in result["companies"].values():
            self.assertTrue(all(company[field] is None for field in NUMERIC_FIELDS))
            self.assertIsNone(company["disclosed_at"])
        self.assertIn("financial inputs are unavailable", result["notice"])

    def test_future_or_naive_publication_timestamp_cannot_admit_numbers(self):
        for stamp in ("2026-09-09T12:00:00Z", "2026-09-08T12:00:00"):
            feed = deepcopy(self.feed)
            for row in feed["filings"]:
                if row["filedDate"] == "2026-09-08":
                    row["acceptedAt"] = stamp
            with self.subTest(stamp=stamp):
                result = self.resolve(feed)
                for company in result["companies"].values():
                    self.assertTrue(all(company[field] is None for field in NUMERIC_FIELDS))

    def test_input_and_returned_provenance_are_independent(self):
        before_prices, before_feed = deepcopy(self.prices), deepcopy(self.feed)
        result = self.resolve()
        result["companies"]["MSTR"]["provenance"]["filing"]["documents"][0]["sha256"] = "changed"
        result["publications"]["ASST"]["documents"].clear()
        self.assertEqual(self.prices, before_prices)
        self.assertEqual(self.feed, before_feed)

    def test_shared_resolver_validation_error_does_not_fall_back_to_fixture(self):
        with self.assertRaisesRegex(ValueError, "Unsupported filing feed"):
            self.resolve({"schemaVersion": 9, "filings": []})
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.resolve(now=datetime(2026, 9, 8))
