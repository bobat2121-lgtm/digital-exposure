"""Monday disclosure updates reprice Friday balances without rebuilding markets."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT / "sources" / "friday", ROOT):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from friday import metrics


def company(**changes):
    return {
        "btc_held": 100, "cash_usd": 1_000_000, "securities_usd": 200_000,
        "debt_usd": 500_000, "preferred_usd": 700_000, "shares": 100_000,
        "disclosed_at": "2026-08-28T12:00:00+00:00", "baseline_at": "2026-08-23",
        "sources": [{"url": "https://www.sec.gov/example", "field": "btc_held"}],
        **changes,
    }


def monday_company(**changes):
    return company(
        **{"allow_post_friday_disclosure": True, "publication_basis": "latest_monday_disclosures",
           "disclosed_at": "2026-09-08T12:00:00+00:00", "baseline_at": "2026-09-06", **changes}
    )


def market_data(now="2026-09-08T18:00:00+00:00"):
    period = metrics.completed_week(datetime.fromisoformat(now))
    days = [*period["previous_sessions"], *period["sessions"]]
    prices = {ticker: [] for ticker in ("BTC", "MSTR", "ASST", "STRC", "SATA")}
    marks = {}
    for day in days:
        fraction = (period["sessions"].index(day) + 1) / len(period["sessions"]) if day in period["sessions"] else 0
        values = {"BTC": 90_000 + fraction * 10_000, "MSTR": 100 + fraction * 32,
                  "ASST": 10 + fraction * 5, "STRC": 100, "SATA": 100}
        for ticker, value in values.items():
            prices[ticker].append({"date": day, "close": value, "volume": 1_000})
        close = metrics._close(datetime.fromisoformat(day).date(), metrics._calendar()).isoformat()
        marks[day] = {"close": 80_000 + fraction * 8_000, "as_of": close}
    return {
        "mode": "latest", "fetched_at": now, "prices": prices, "btc_equity_marks": marks,
        "companies": {ticker: company() for ticker in ("MSTR", "ASST")},
        "sentiment": [{"date": period["end"], "value": 40}],
        "supply_loss": [{"date": period["end"], "pct": 30, "profit_pct": 70}],
        "notices": ["Keep this provider notice."],
    }


class FridayBalanceMetricsTests(TestCase):
    def test_post_friday_requires_both_exact_per_company_markers(self):
        close = datetime.fromisoformat("2026-09-04T20:00:00+00:00")
        for markers in ({}, {"allow_post_friday_disclosure": True},
                        {"publication_basis": "latest_monday_disclosures"},
                        {"allow_post_friday_disclosure": "true", "publication_basis": "latest_monday_disclosures"},
                        {"allow_post_friday_disclosure": False, "publication_basis": "latest_monday_disclosures"},
                        {"allow_post_friday_disclosure": True, "publication_basis": "latest"}):
            with self.subTest(markers=markers):
                accepted, reason = metrics._baseline(company(disclosed_at="2026-09-08T12:00:00+00:00", **markers), close)
                self.assertFalse(accepted)
                self.assertIn("after this Friday", reason)
        self.assertEqual(metrics._baseline(monday_company(), close), (True, None))
        self.assertEqual(metrics._baseline(company(), close), (True, None))

    def test_markers_do_not_admit_undated_or_invalid_numeric_inputs(self):
        close = datetime.fromisoformat("2026-09-04T20:00:00+00:00")
        for changes in ({"disclosed_at": None}, {"disclosed_at": "not a date"}, {"shares": 0},
                        {"debt_usd": -1}, {"preferred_usd": None}, {"securities_usd": float("nan")}):
            with self.subTest(changes=changes):
                self.assertFalse(metrics._baseline(monday_company(**changes), close)[0])

    def test_new_monday_quantities_apply_to_both_frozen_price_endpoints(self):
        data = market_data()
        panel = metrics.compute_panel(data)
        changed = {"MSTR": monday_company(), "ASST": monday_company(
            btc_held=50, cash_usd=200_000, securities_usd=500_000, debt_usd=100_000,
            preferred_usd=200_000, shares=50_000)}
        result = metrics.reprice_company_inputs(panel, data, changed)
        mstr, asst = result["treasury"]
        self.assertEqual((mstr["start_nav_per_share"], mstr["nav_per_share"]), (80, 88))
        self.assertAlmostEqual(mstr["nav_change_pct"], 10)
        self.assertEqual(mstr["btc_effect_per_share"], 8)
        self.assertEqual((mstr["start_nav_multiple"], mstr["nav_multiple"], mstr["nav_multiple_change"]), (1.25, 1.5, .25))
        self.assertEqual(mstr["premium_pct"], 50)
        self.assertEqual((asst["start_nav_per_share"], asst["nav_per_share"]), (88, 96))
        self.assertEqual(result["period"]["end"], "2026-09-04")
        self.assertEqual(mstr["baseline_disclosed_at"], changed["MSTR"]["disclosed_at"])
        self.assertEqual(mstr["baseline_at"], "2026-09-06")
        self.assertEqual(mstr["publication_basis"], "latest_monday_disclosures")
        self.assertIn("post-Friday", mstr["series_basis"])
        for field in ("btc_held", "cash_usd", "securities_usd", "debt_usd", "preferred_usd", "shares"):
            self.assertEqual(mstr[field], changed["MSTR"][field])
        self.assertEqual(mstr["nav_series"][0]["nav_per_share"], 80)
        self.assertEqual(mstr["nav_series"][-1]["nav_per_share"], 88)

    def test_missing_new_field_blanks_nav_without_carrying_old_values(self):
        data = market_data()
        panel = metrics.compute_panel(data)
        for missing in ("btc_held", "cash_usd", "securities_usd", "debt_usd", "preferred_usd", "shares"):
            with self.subTest(missing=missing):
                new = monday_company(**{missing: None})
                result = metrics.reprice_company_inputs(panel, data, {"MSTR": new, "ASST": monday_company()})
                mstr = result["treasury"][0]
                self.assertIsNone(mstr[missing])
                self.assertFalse(mstr["valid"])
                self.assertIn(missing, mstr["reason"])
                self.assertEqual(mstr["nav_series"], [])
                for field in ("nav_per_share", "nav_change_pct", "nav_multiple", "start_nav_multiple", "nav_multiple_change", "premium_pct"):
                    self.assertIsNone(result["header"]["companies"]["MSTR"][field])
                self.assertEqual(result["header"]["companies"]["MSTR"]["price"], 132)
                self.assertTrue(result["treasury"][1]["valid"])

    def test_cash_and_securities_are_separate_and_strategy_combined_cash_is_counted_once(self):
        data = market_data()
        result = metrics.reprice_company_inputs(metrics.compute_panel(data), data, {
            "MSTR": monday_company(cash_usd=1_200_000, securities_usd=0),
            "ASST": monday_company(cash_usd=1_000_000, securities_usd=200_000),
        })
        mstr, asst = result["treasury"]
        self.assertEqual(mstr["nav_per_share"], asst["nav_per_share"])
        self.assertEqual(mstr["cash_usd"], 1_200_000)
        self.assertEqual(mstr["securities_usd"], 0)
        self.assertEqual(asst["cash_usd"], 1_000_000)
        self.assertEqual(asst["securities_usd"], 200_000)

    def test_reprice_preserves_market_containers_and_never_recomputes_full_panel(self):
        data = market_data()
        panel = metrics.compute_panel(data)
        panel["chart_specs"] = {"ready": {"BTC": {"dataset": [1, 2, 3]}}}
        changed = {ticker: monday_company(btc_held=101) for ticker in ("MSTR", "ASST")}
        original_data, original_panel, original_companies = deepcopy(data), deepcopy(panel), deepcopy(changed)
        with ExitStack() as stack:
            for name in ("compute_panel", "completed_week", "_trends", "_trend_history", "_liquidity", "_indicator"):
                stack.enter_context(patch.object(metrics, name, side_effect=AssertionError(f"Unexpected {name}")))
            result = metrics.reprice_company_inputs(panel, data, changed)
        self.assertIsNot(result, panel)
        for field in panel:
            if field not in ("header", "treasury", "notices"):
                self.assertIs(result[field], panel[field], field)
        self.assertIs(result["header"]["btc"], panel["header"]["btc"])
        self.assertIsNot(result["header"]["companies"], panel["header"]["companies"])
        self.assertIsNot(result["treasury"], panel["treasury"])
        self.assertEqual(data, original_data)
        self.assertEqual(panel, original_panel)
        self.assertEqual(changed, original_companies)
        self.assertEqual(data["fetched_at"], "2026-09-08T18:00:00+00:00")

    def test_reprice_matches_full_calculation_at_regular_and_early_exchange_closes(self):
        for stamp in ("2026-09-08T18:00:00+00:00", "2026-11-27T18:05:00+00:00"):
            with self.subTest(stamp=stamp):
                data = market_data(stamp)
                panel = metrics.compute_panel(data)
                changed = {ticker: monday_company(btc_held=123, preferred_usd=999_000) for ticker in ("MSTR", "ASST")}
                expected = metrics.compute_panel({**data, "companies": changed})
                result = metrics.reprice_company_inputs(panel, data, changed)
                self.assertEqual(result["header"], expected["header"])
                self.assertEqual(result["treasury"], expected["treasury"])
                if "11-27" in stamp:
                    self.assertEqual(result["period"]["as_of"], "2026-11-27T18:00:00+00:00")
                    self.assertEqual(len(result["period"]["sessions"]), 4)

    def test_ineligible_other_company_does_not_inherit_post_friday_permission(self):
        data = market_data()
        panel = metrics.compute_panel(data)
        changed = {"MSTR": monday_company(), "ASST": company(disclosed_at="2026-09-08T12:00:00+00:00")}
        result = metrics.reprice_company_inputs(panel, data, changed)
        self.assertTrue(result["treasury"][0]["valid"])
        self.assertFalse(result["treasury"][1]["valid"])
        self.assertEqual(result["treasury"][1]["publication_basis"], "available_by_friday_close")
        self.assertIsNone(result["treasury"][1]["btc_held"])
        self.assertIsNone(result["header"]["companies"]["ASST"]["nav_multiple"])

    def test_missing_endpoint_and_nonpositive_nav_keep_existing_missing_value_rules(self):
        data = market_data()
        end = "2026-09-04"
        data["prices"]["BTC"] = [row for row in data["prices"]["BTC"] if row["date"] != end]
        data["btc_equity_marks"].pop(end)
        panel = metrics.compute_panel(data)
        result = metrics.reprice_company_inputs(panel, data, {ticker: monday_company() for ticker in ("MSTR", "ASST")})
        self.assertIsNone(result["treasury"][0]["nav_per_share"])
        self.assertIn("endpoint", result["treasury"][0]["reason"])
        data = market_data()
        result = metrics.reprice_company_inputs(metrics.compute_panel(data), data, {
            ticker: monday_company(debt_usd=100_000_000) for ticker in ("MSTR", "ASST")})
        self.assertLess(result["treasury"][0]["nav_per_share"], 0)
        self.assertIsNone(result["treasury"][0]["nav_multiple"])
        self.assertIsNone(result["treasury"][0]["nav_multiple_change"])

    def test_reprice_replaces_only_obsolete_company_reason_notices(self):
        data = market_data()
        data["companies"] = {ticker: company(disclosed_at="2026-09-08T12:00:00+00:00") for ticker in ("MSTR", "ASST")}
        panel = metrics.compute_panel(data)
        self.assertTrue(any("historical NAV withheld" in notice for notice in panel["notices"]))
        result = metrics.reprice_company_inputs(panel, data, {
            "MSTR": monday_company(), "ASST": monday_company(preferred_usd=None)})
        self.assertFalse(any("historical NAV withheld" in notice for notice in result["notices"]))
        self.assertIn("Keep this provider notice.", result["notices"])
        self.assertTrue(any("ASST:" in notice and "preferred_usd" in notice for notice in result["notices"]))
        non_financial = [notice for notice in panel["notices"] if not notice.startswith(("MSTR:", "ASST:"))]
        self.assertTrue(all(notice in result["notices"] for notice in non_financial))
