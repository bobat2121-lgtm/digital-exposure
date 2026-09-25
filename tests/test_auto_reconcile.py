"""Automatic Monday reconciliation, without network: fixed provider data."""
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from report import auto_reconcile as ar
from report import live_report as lr
from report.current_prices import load_current_prices

DATA = Path(__file__).resolve().parents[1] / "data"
FILINGS = json.loads((DATA / "latest-report-filings.json").read_text())
SUPPLEMENTS = json.loads((DATA / "report-supplements.json").read_text())


def _stamp(day, hour=20):
    return int(datetime(day.year, day.month, day.day, hour, tzinfo=UTC).timestamp())


def _closes(values, end=date(2026, 9, 25)):
    days, day = [], end
    while len(days) < len(values):
        day -= timedelta(days=1)
        if day.weekday() < 5:
            days.append(day)
    return [(_stamp(d), value) for d, value in zip(reversed(days), values)]


# Ten closes strictly before Friday Sep 18 average exactly $103.85 for STRF.
STRF = [103.4, 103.6, 103.8, 104.0, 104.2, 103.9, 103.7, 103.95, 104.05, 103.9]
PROVIDER = {
    "STRF": _closes(STRF + [104.1, 104.0, 103.9, 103.8, 103.7], date(2026, 9, 25)),
    "STRC": _closes([98.0] * 20), "STRK": _closes([74.0] * 20), "STRD": _closes([72.0] * 20),
    "SATA": _closes([99.96] * 19 + [99.97]),
}
STRC_KPI = {"currentDividend": 12, "dividendHistory": [
    {"payDate": "2026-08-31", "rate": 11.75}, {"payDate": "2026-09-15", "rate": 12},
    {"payDate": "2026-09-30", "rate": 12}, {"payDate": "2026-10-15", "rate": 12}]}


def fake_yahoo(symbol, interval, span):
    if interval == "1h":
        base = 77_500.0 if symbol == "BTC-USD" else 1.1540
        start = datetime(2026, 9, 1, tzinfo=UTC)
        return [(int((start + timedelta(hours=h)).timestamp()), base) for h in range(24 * 40)]
    if symbol in ("BTC-USD", "EURUSD=X"):
        return _closes([1.0] * 60)
    # Shift daily windows so each balance date sees the fixture's ten closes.
    return PROVIDER[symbol]


def seed_sep13():
    record = json.loads((DATA / "reconciliation-2026-09-14.json").read_text())
    return {"date": record["strategy_shares"]["balance_date"], "common": record["strategy_shares"]["basic_shares"],
            "series": {name: row["shares"] for name, row in record["strategy_claims"].items()}, "source": "test"}


class AutoReconcileTests(unittest.TestCase):
    def setUp(self):
        for target, value in (("_yahoo", fake_yahoo), ("_strc_dividends", lambda: STRC_KPI)):
            patcher = patch.object(ar, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.rows = lr._merged_filings(FILINGS, {})

    def test_days360(self):
        self.assertEqual(ar.days360(date(2026, 6, 30), date(2026, 9, 20)), 80)
        self.assertEqual(ar.days360(date(2026, 8, 31), date(2026, 9, 13)), 13)
        self.assertEqual(ar.days360(date(2026, 9, 15), date(2026, 9, 20)), 5)

    def test_roll_forward_reproduces_the_reviewed_september_20_inputs(self):
        supplements = deepcopy(SUPPLEMENTS)
        reviewed = supplements["balances"]["MSTR"].pop("2026-09-20")
        reviewed_asst = supplements["balances"]["ASST"].pop("2026-09-18")
        with patch.object(ar, "_seed", seed_sep13):
            result, notes = ar.augment(self.rows, supplements)
        self.assertEqual(notes, ["Strategy 2026-09-20", "Strive 2026-09-18"])
        entry = result["balances"]["MSTR"]["2026-09-20"]
        self.assertTrue(entry["auto_reconciled"])
        self.assertAlmostEqual(entry["preferred_claims_usd"], reviewed["preferred_claims_usd"], places=2)
        self.assertAlmostEqual(entry["preferred_claims_eur"], reviewed["preferred_claims_eur"], places=2)
        self.assertEqual(entry["debt_principal"], reviewed["debt_principal"])
        # Employee issuance between reviews is invisible to the 8-K roll-forward.
        self.assertEqual(entry["effective_common_shares"], 420_497_000)
        self.assertLess(abs(entry["effective_common_shares"] / reviewed["effective_common_shares"] - 1), 1e-4)
        self.assertEqual(result["balances"]["ASST"]["2026-09-18"]["preferred_claims_usd"], reviewed_asst["preferred_claims_usd"])

    def test_reviewed_entries_are_never_replaced(self):
        result, notes = ar.augment(self.rows, deepcopy(SUPPLEMENTS))
        self.assertEqual(notes, [])
        self.assertEqual(result["balances"], SUPPLEMENTS["balances"])

    def test_provider_failure_leaves_the_week_missing(self):
        def broken(*_):
            raise OSError("offline")
        supplements = deepcopy(SUPPLEMENTS)
        supplements["balances"]["MSTR"].pop("2026-09-20")
        with patch.object(ar, "_seed", seed_sep13), patch.object(ar, "_yahoo", broken):
            result, notes = ar.augment(self.rows, supplements)
        self.assertNotIn("2026-09-20", result["balances"]["MSTR"])
        self.assertTrue(any("unavailable" in note for note in notes))


class AutomaticEditionTests(unittest.TestCase):
    """A new filing pair with no reviewed inputs publishes a complete edition."""

    def test_next_week_is_complete_and_labelled(self):
        feed = deepcopy(FILINGS)
        for row in [r for r in FILINGS["filings"] if r["filedDate"] == "2026-09-21"]:
            new = deepcopy(row)
            new["accession"] = row["accession"][:-6] + "777777"
            new["primaryDocumentUrl"] = row["primaryDocumentUrl"].replace(row["accession"].replace("-", ""), new["accession"].replace("-", ""))
            new["documents"][0]["url"] = new["primaryDocumentUrl"]
            new["filedDate"], new["acceptedAt"] = "2026-09-28", "2026-09-28T12:00:00Z"
            e = new["extracted"]
            shift = lambda value: (date.fromisoformat(value) + timedelta(days=7)).isoformat()
            e["periodStart"], e["periodEnd"], e["balanceDate"] = shift(e["periodStart"]), shift(e["periodEnd"]), shift(e["balanceDate"])
            if new["ticker"] == "ASST":
                e["priorBalanceDate"], e["priorFacts"] = row["extracted"]["balanceDate"], deepcopy(row["extracted"]["facts"])
                e["facts"]["net_sata_shares_change"] = 0
                e["facts"]["net_common_shares_change"] = 0
                e["facts"]["weekly_btc_purchases"] = 0
            else:
                e["facts"]["weekly_btc_purchases"] = 0
                e["facts"].pop("weekly_btc_sales", None)
                for security in e["securities"].values():
                    security.update(issuedShares=0, netIssuanceProceedsUsd=0, repurchasedShares=0, repurchaseCashUsd=0)
                e["facts"].update(common_issued_shares=0, common_issuance_proceeds_usd=0,
                                  common_repurchased_shares=0, common_repurchases_cash_usd=0)
            feed["filings"].append(new)
        vwap = {"value": 29.5, "method": "hlc3_5m", "session_start": "2026-09-21", "session_end": "2026-09-25"}
        with patch.object(ar, "_yahoo", fake_yahoo), patch.object(ar, "_strc_dividends", lambda: STRC_KPI), \
                patch.object(ar, "vwap_estimate", lambda filed: vwap):
            prices = load_current_prices()
            result = lr.resolve_complete_report(prices, feed)
        self.assertIn("Strategy Sep 27", result.report.subtitle)
        self.assertIn("Strive Sep 25", result.report.subtitle)
        self.assertIn("Automatically reconciled", result.notice)
        strategy = result.report.companies[0]
        self.assertEqual(strategy.current.effective_common_shares, 420_507_000)
        self.assertIsNotNone(strategy.current.preferred_claims)


if __name__ == "__main__":
    unittest.main()
