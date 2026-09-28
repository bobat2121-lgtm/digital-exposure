"""The Monday publish Action's script, without network: fixed providers, a stubbed check.

Every case starts from the September 28 edition (the last one reviewed by hand), so
later weeks saved by the Action itself never change these tests.
"""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from report import auto_reconcile as ar
from report import vwap_store

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
spec = importlib.util.spec_from_file_location("monday_publish", ROOT / "scripts" / "monday_publish.py")
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)

EDITION = "2026-09-28"
CHECKPOINT = json.loads((DATA / "latest-report-filings.json").read_text(encoding="utf-8"))
CHECKPOINT["filings"] = [row for row in CHECKPOINT["filings"] if row["filedDate"] <= EDITION]
SUPPLEMENTS = json.loads((DATA / "report-supplements.json").read_text(encoding="utf-8"))
for _ticker, _balances in SUPPLEMENTS["balances"].items():
    SUPPLEMENTS["balances"][_ticker] = {day: row for day, row in _balances.items() if day <= "2026-09-27"}
for _field in ("comparison_btc_prices", "comparison_release_dates", "balance_marks"):
    SUPPLEMENTS[_field] = {day: row for day, row in SUPPLEMENTS[_field].items() if day <= "2026-09-20"}
SUPPLEMENTS["revision"] = "2026-09-28.1"
SEP28 = {row["ticker"]: row for row in CHECKPOINT["filings"]
         if row["filedDate"] == EDITION and row["status"] == "ready_for_review"}
PRICES = json.loads((DATA / "release-prices" / "2026-09-28.json").read_text(encoding="utf-8"))
MONDAY_8_20 = datetime(2026, 10, 5, 12, 20, tzinfo=UTC)  # 8:20 am EDT, Oct 5


def seed_sep27():
    record = json.loads((DATA / "reconciliation-2026-09-28.json").read_text(encoding="utf-8"))
    return {"date": record["strategy_shares"]["balance_date"], "common": record["strategy_shares"]["basic_shares"],
            "series": {name: row["shares"] for name, row in record["strategy_claims"].items()},
            "source": "reconciliation-2026-09-28.json", "debt": record["strategy_debt"]}


def shifted(row, days, *, filed, accepted, suffix):
    """A copy of a real weekly 8-K moved ``days`` later, under a new accession."""
    new = deepcopy(row)
    new["accession"] = row["accession"][:-6] + suffix
    new["primaryDocumentUrl"] = row["primaryDocumentUrl"].replace(row["accession"].replace("-", ""), new["accession"].replace("-", ""))
    new["documents"][0]["url"] = new["primaryDocumentUrl"]
    new["filedDate"], new["acceptedAt"], new["firstSeenAt"] = filed, accepted, accepted
    move = lambda value: (date.fromisoformat(value) + timedelta(days=days)).isoformat()
    extraction = new["extracted"]
    for key in ("periodStart", "periodEnd", "balanceDate"):
        extraction[key] = move(extraction[key])
    if new["ticker"] == "ASST":
        extraction["priorBalanceDate"] = (date.fromisoformat(extraction["balanceDate"]) - timedelta(days=7)).isoformat()
        extraction["priorFacts"] = deepcopy(row["extracted"]["facts"])
        extraction["facts"]["net_sata_shares_change"] = 0
    return new


def week(days, *, filed, accepted, suffix, tickers=("MSTR", "ASST")):
    return [shifted(SEP28[ticker], days, filed=filed, accepted=accepted, suffix=suffix) for ticker in tickers]


def feed_with(*rows):
    feed = deepcopy(CHECKPOINT)
    feed["filings"] = list(rows) + feed["filings"]
    return feed


OCT5 = week(7, filed="2026-10-05", accepted="2026-10-05T12:00:10Z", suffix="777777")


# Fixed providers: daily closes on every weekday, hourly marks, STRC's schedule, the note list.
def _weekdays(start, end):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


CLOSES = {"STRF": 104.0, "STRC": 99.0, "STRK": 74.0, "STRD": 72.0, "SATA": 99.97, "BTC-USD": 80_000.0, "EURUSD=X": 1.15}


def fake_yahoo(symbol, interval, span):
    if interval == "1h":
        start = datetime(2026, 9, 1, tzinfo=UTC)
        return [(int((start + timedelta(hours=hour)).timestamp()), CLOSES[symbol]) for hour in range(24 * 60)]
    return [(int(datetime(day.year, day.month, day.day, 20, tzinfo=UTC).timestamp()), CLOSES[symbol])
            for day in _weekdays(date(2026, 7, 1), date(2026, 10, 30))]


STRC_KPI = {"currentDividend": 12, "dividendHistory": [
    {"payDate": "2026-09-15", "rate": 12}, {"payDate": "2026-09-30", "rate": 12},
    {"payDate": "2026-10-15", "rate": 12}, {"payDate": "2026-10-30", "rate": 12}]}


def vwap_for(filed):
    days = [(filed - timedelta(days=7 - offset)).isoformat() for offset in range(5)]
    return {"symbol": "ASST", "edition_date": filed.isoformat(), "value": 30.1, "method": "hlc3_5m",
            "label": "5-minute VWAP estimate", "window": "prior_week", "session_start": days[0], "session_end": days[-1],
            "sessiondates": days, "daily": [{"date": day, "value": 30.1} for day in days]}


def summarize(feed, prices):
    """The page's view, reduced to what the check compares: the newest balance dates."""
    rows = mp.live_report._merged_filings(feed, {})
    newest = {ticker: max(row["extracted"]["balanceDate"] for row in rows if row["ticker"] == ticker) for ticker in mp.TICKERS}
    return {"companies": {ticker: {"name": mp.NAMES[ticker], "balance_date": day, "balance_label": mp._short(day),
                                   "bitcoin_bought": "1,000 BTC", "money": "in COMMON +$1.00B · out BTC −$1.00B"}
                          for ticker, day in newest.items()}, "heads_up": [], "notice": None}


class Providers(unittest.TestCase):
    listed = 6_713_750_000  # strategy.com's note list, matching the reviewed convertibles

    def setUp(self):
        for target, value in (("_yahoo", fake_yahoo), ("_strc_dividends", lambda: STRC_KPI),
                              ("_convertibles", lambda: self.listed), ("_seed", lambda before=None: seed_sep27())):
            patcher = patch.object(ar, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)


class GateTests(unittest.TestCase):
    def test_saved_week_is_already_published(self):
        decision = mp.gate(CHECKPOINT, SUPPLEMENTS, datetime(2026, 9, 28, 14, tzinfo=UTC))
        self.assertEqual(decision.state, "already published")
        self.assertEqual(decision.reason, "Strategy Sep 27 · Strive Sep 25 saved")

    def test_half_a_pair_waits(self):
        decision = mp.gate(feed_with(OCT5[0]), SUPPLEMENTS, MONDAY_8_20)
        self.assertEqual(decision.state, "waiting")
        self.assertIn("Strive's weekly 8-K not yet validated", decision.reason)

    def test_a_new_pair_goes_ahead(self):
        decision = mp.gate(feed_with(*OCT5), SUPPLEMENTS, MONDAY_8_20)
        self.assertEqual(decision.state, "publish")
        self.assertEqual({ticker: row["extracted"]["balanceDate"] for ticker, row in decision.pair.items()},
                         {"MSTR": "2026-10-04", "ASST": "2026-10-02"})
        self.assertFalse(decision.redo)

    def test_a_filing_awaiting_validation_holds_it(self):
        pending = deepcopy(OCT5[1])
        pending.update(accession="0001628280-26-888888", status="pending")
        decision = mp.gate(feed_with(*OCT5, pending), SUPPLEMENTS, MONDAY_8_20)
        self.assertEqual(decision.state, "waiting")
        self.assertIn("await validation", decision.reason)

    def test_a_pair_older_than_three_days_waits_unless_forced(self):
        thursday = datetime(2026, 10, 8, 13, tzinfo=UTC)
        self.assertEqual(mp.gate(feed_with(*OCT5), SUPPLEMENTS, thursday).state, "waiting")
        self.assertEqual(mp.gate(feed_with(*OCT5), SUPPLEMENTS, thursday, force=True).state, "publish")

    def test_tuesday_filings_after_a_holiday_monday(self):
        # Columbus Day, Mon Oct 12, 2026: EDGAR is closed while NYSE trades, so the 8-Ks come Tuesday.
        monday, tuesday = datetime(2026, 10, 12, 12, 20, tzinfo=UTC), datetime(2026, 10, 13, 12, 20, tzinfo=UTC)
        self.assertTrue(mp.in_window(monday) and mp.in_window(tuesday))
        self.assertEqual(mp.gate(CHECKPOINT, SUPPLEMENTS, monday).state, "already published")
        late = week(14, filed="2026-10-13", accepted="2026-10-13T12:00:05Z", suffix="666666")
        decision = mp.gate(feed_with(*late), SUPPLEMENTS, tuesday)
        self.assertEqual(decision.state, "publish")
        self.assertEqual(decision.reason, "Strategy Oct 11 · Strive Oct 9")

    def test_publishing_window_in_daylight_and_standard_time(self):
        edt = lambda hour, minute, day=28: datetime(2026, 9, day, hour + 4, minute, tzinfo=UTC)
        est = lambda hour, minute: datetime(2026, 11, 2, hour + 5, minute, tzinfo=UTC)
        self.assertFalse(mp.in_window(edt(7, 49)))
        self.assertTrue(mp.in_window(edt(7, 50)) and mp.in_window(edt(10, 30)) and mp.in_window(edt(9, 0, day=29)))
        self.assertFalse(mp.in_window(edt(10, 31)) or mp.in_window(edt(8, 0, day=30)))  # Wednesday
        self.assertTrue(mp.in_window(est(7, 50)) and mp.in_window(est(10, 30)))
        self.assertFalse(mp.in_window(est(7, 49)))


class FreezeTests(Providers):
    def setUp(self):
        super().setUp()
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "report-supplements.json").write_text(mp._dump(SUPPLEMENTS), encoding="utf-8")
        (self.data / "latest-report-filings.json").write_text(mp._dump(CHECKPOINT), encoding="utf-8")
        patcher = patch.object(vwap_store, "DATA", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.checks = []

    def check(self, frozen):
        self.checks.append(frozen)
        return {"summary": {"status": "complete"}, "prices": PRICES}

    def publish(self, feed, now=MONDAY_8_20, **options):
        options.setdefault("check", self.check)
        return mp.publish(now=now, feed=feed, root=self.root, summarize=summarize, pull_vwap=vwap_for, **options)

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_writes_only_the_new_weeks_entries_in_the_saved_formats(self):
        before = self.snapshot()
        result = self.publish(feed_with(*OCT5))
        self.assertEqual((result["status"], result["edition"], result["revision"]), ("published", "2026-10-05", "2026-10-05.1"))
        self.assertEqual(result["expect"], "MSTR=Oct 4,ASST=Oct 2")
        self.assertEqual(self.checks, [True])  # checked with the in-memory reconciliation off
        after = self.snapshot()
        self.assertEqual(sorted(set(after) - set(before)),
                         ["data/asst-vwap-2026-10-05.json", "data/release-prices/2026-10-05.json"])
        self.assertFalse(list(self.data.glob("reconciliation-*.json")))
        for name, raw in after.items():
            text = raw.decode("utf-8")
            self.assertEqual(text, json.dumps(json.loads(text), indent=2) + "\n", name)

        saved = json.loads(after["data/report-supplements.json"])
        for ticker, day in (("MSTR", "2026-10-04"), ("ASST", "2026-10-02")):
            entry = saved["balances"][ticker].pop(day)
            self.assertTrue(entry["auto_reconciled"])
            for key in mp.REQUIRED[ticker]:
                self.assertIsInstance(entry[key], (int, float), key)
        self.assertEqual(saved["balances"]["MSTR"]["2026-09-27"], SUPPLEMENTS["balances"]["MSTR"]["2026-09-27"])
        self.assertEqual(saved.pop("comparison_release_dates"), {**SUPPLEMENTS["comparison_release_dates"], "2026-09-27": "2026-09-28"})
        self.assertEqual(saved.pop("comparison_btc_prices"), {**SUPPLEMENTS["comparison_btc_prices"], "2026-09-27": 80_000.0})
        self.assertEqual(saved.pop("balance_marks"), {**SUPPLEMENTS["balance_marks"], "2026-09-27": {"EURUSD=X": 1.15},
                                                      "2026-09-25": {"STRC": 98.54059405940595},
                                                      "2026-10-02": {"STRC": 98.54059405940595}})
        self.assertEqual(saved.pop("revision"), "2026-10-05.1")
        reference = {key: value for key, value in SUPPLEMENTS.items()
                     if key not in ("comparison_release_dates", "comparison_btc_prices", "balance_marks", "revision")}
        self.assertEqual(saved, reference)  # everything else, preferred_audit_files included, as it was

        checkpoint = json.loads(after["data/latest-report-filings.json"])
        self.assertEqual([row["accession"] for row in checkpoint["filings"][:2]], [row["accession"] for row in OCT5])
        self.assertEqual(checkpoint["filings"][2:], CHECKPOINT["filings"])
        self.assertEqual(checkpoint["reconciledAt"], MONDAY_8_20.isoformat())
        vwap = vwap_store.load_estimate("ASST", date(2026, 10, 5))
        self.assertEqual((vwap["value"], vwap["display_note"]), (30.1, "5-minute VWAP estimate · automatic"))
        self.assertEqual(json.loads(after["data/release-prices/2026-10-05.json"]), PRICES)

    def test_a_second_run_does_nothing(self):
        self.publish(feed_with(*OCT5))
        before = self.snapshot()
        result = self.publish(feed_with(*OCT5))
        self.assertEqual((result["status"], result["reason"]), ("already published", "Strategy Oct 4 · Strive Oct 2 saved"))
        self.assertEqual(self.snapshot(), before)

    def test_dry_run_writes_nothing(self):
        before = self.snapshot()
        result = self.publish(feed_with(*OCT5), dry_run=True)
        self.assertEqual((result["status"], result["revision"]), ("dry run", "2026-10-05.1"))
        self.assertEqual(self.checks, [False])  # the in-memory edition, as the page shows it
        self.assertEqual(self.snapshot(), before)

    def test_unavailable_source_writes_nothing(self):
        before = self.snapshot()
        def offline(*_):
            raise OSError("offline")
        with patch.object(ar, "_yahoo", offline), self.assertRaisesRegex(mp.PublishError, "unavailable"):
            self.publish(feed_with(*OCT5))
        self.assertEqual(self.snapshot(), before)

    def test_missing_mark_writes_nothing(self):
        before = self.snapshot()
        def no_mark(*_):
            raise OSError("no hourly bar")
        with patch.object(ar, "_hour_mark", no_mark), self.assertRaisesRegex(mp.PublishError, "comparison BTC price for 2026-09-27"):
            self.publish(feed_with(*OCT5))
        self.assertEqual(self.snapshot(), before)

    def test_missing_vwap_writes_nothing(self):
        before = self.snapshot()
        def unavailable(filed):
            raise ValueError("Incomplete historical window")
        with self.assertRaisesRegex(mp.PublishError, "Strive VWAP unavailable"):
            mp.publish(now=MONDAY_8_20, feed=feed_with(*OCT5), root=self.root, check=self.check,
                       summarize=summarize, pull_vwap=unavailable)
        self.assertEqual(self.snapshot(), before)

    def test_failed_check_restores_every_file(self):
        before = self.snapshot()
        def failing(frozen):
            raise mp.PublishError("publication check failed: Rendered report contains Unavailable")
        with self.assertRaisesRegex(mp.PublishError, "publication check failed"):
            self.publish(feed_with(*OCT5), check=failing)
        self.assertEqual(self.snapshot(), before)

    def test_page_on_an_older_edition_restores_every_file(self):
        before = self.snapshot()
        stale = lambda feed, prices: summarize(CHECKPOINT, prices)
        with self.assertRaisesRegex(mp.PublishError, "not the new pair"):
            mp.publish(now=MONDAY_8_20, feed=feed_with(*OCT5), root=self.root, check=self.check,
                       summarize=stale, pull_vwap=vwap_for)
        self.assertEqual(self.snapshot(), before)

    def test_force_redoes_automatic_entries_only(self):
        self.publish(feed_with(*OCT5))
        again = self.publish(feed_with(*OCT5), force=True)
        self.assertEqual((again["status"], again["revision"]), ("published", "2026-10-05.2"))
        self.assertEqual(sorted(again["added"]["balances"]), ["ASST", "MSTR"])
        with self.assertRaisesRegex(mp.PublishError, "reviewed figures"):
            self.publish(CHECKPOINT, now=datetime(2026, 9, 28, 13, tzinfo=UTC), force=True)

    def test_a_later_automatic_week_still_compares_strategy_debt(self):
        self.publish(feed_with(*OCT5))
        oct12 = week(14, filed="2026-10-12", accepted="2026-10-12T12:00:10Z", suffix="666666")
        self.listed = 8_713_750_000  # a new convertible tranche appears on strategy.com
        result = self.publish(feed_with(*oct12, *OCT5), now=datetime(2026, 10, 12, 12, 20, tzinfo=UTC))
        entry = result["added"]["balances"]["MSTR"]["2026-10-11"]
        self.assertEqual(entry["debt_principal"], 40_044_000 + 8_713_750_000)
        self.assertTrue(entry["debt_change"].startswith("Strategy debt $6.75B → $8.75B"))

    def test_revision_format(self):
        self.assertEqual(mp.bump_revision("2026-09-28.1", "2026-10-05"), "2026-10-05.1")
        self.assertEqual(mp.bump_revision("2026-10-05.1", "2026-10-05"), "2026-10-05.2")
        self.assertEqual(mp.bump_revision(None, "2026-10-13"), "2026-10-13.1")


class ReplayTests(Providers):
    def test_replay_derives_the_saved_week_again_from_the_earlier_reconciliation(self):
        seeds = []
        def seed(before=None):
            seeds.append(before)
            return seed_sep27() if before is None else {**seed_sep27(), "date": "2026-09-20", "source": "earlier"}
        with TemporaryDirectory() as folder:
            data = Path(folder) / "data"
            data.mkdir()
            (data / "report-supplements.json").write_text(mp._dump(SUPPLEMENTS), encoding="utf-8")
            (data / "latest-report-filings.json").write_text(mp._dump(CHECKPOINT), encoding="utf-8")
            before = {path.name: path.read_bytes() for path in data.iterdir()}
            with patch.object(ar, "_seed", seed):
                outcome = mp.replay(EDITION, root=Path(folder),
                                    pull_vwap=lambda filed: {"value": 29.784960002314584, "method": "hlc3_5m"})
            self.assertEqual({path.name: path.read_bytes() for path in data.iterdir()}, before)  # read-only
        self.assertIn(EDITION, seeds)
        fields = {item["field"]: item for item in outcome["comparisons"]}
        claims = fields["MSTR 2026-09-27 preferred_claims_usd"]
        self.assertEqual(claims["saved"], SUPPLEMENTS["balances"]["MSTR"]["2026-09-27"]["preferred_claims_usd"])
        self.assertIsInstance(claims["derived"], float)  # derived again, not copied from the saved week
        self.assertEqual(claims["tolerance"], 0.005)
        self.assertEqual(fields["MSTR 2026-09-27 effective_common_shares"]["tolerance"], 10_000)
        self.assertEqual(fields["comparison_btc_prices 2026-09-20"]["derived"], 80_000.0)
        self.assertEqual(fields["balance_marks 2026-09-18 STRC"]["difference"], 0)
        self.assertEqual(fields["ASST VWAP 2026-09-28 (hlc3_5m saved, hlc3_5m now)"]["difference"], 0)
        self.assertIn("balance_marks 2026-09-25 STRC", outcome["derived_only"])

    def test_tolerances(self):
        self.assertTrue(mp._compare("claims", 100.0, 100.004, 0.005)["within_tolerance"])
        self.assertFalse(mp._compare("claims", 100.0, 100.01, 0.005)["within_tolerance"])
        self.assertFalse(mp._compare("debt", 5, None, 0)["within_tolerance"])
        self.assertIsNone(mp._compare("mark", 1.0, 2.0, None)["within_tolerance"])


class DiscordTests(unittest.TestCase):
    SUMMARY = {"companies": {
        "MSTR": {"name": "Strategy", "balance_label": "Sep 27", "bitcoin_bought": "1,666 BTC",
                 "money": "in COMMON +$231.0m · out STRC BUYBACK −$174.0m, BTC −$140.1m"},
        "ASST": {"name": "Strive", "balance_label": "Sep 25", "bitcoin_bought": "455 BTC",
                 "money": "in COMMON +$30.1m, PREF +$10.1m · out BTC −$38.0m, DIVs −$2.2m"}},
        "heads_up": []}
    COMMIT = "https://github.com/bobat2121-lgtm/digital-exposure/commit/abc1234"

    def test_one_embed_with_dates_bitcoin_flows_and_links(self):
        payload = mp.discord_payload(self.SUMMARY, commit_url=self.COMMIT)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})  # never pings anyone
        (embed,) = payload["embeds"]
        self.assertEqual(embed["title"], "📘 Accretion Ledger updated")
        self.assertEqual(embed["description"],
                         "Strategy balance Sep 27 · Strive balance Sep 25 · automatic reconciliation from the 8-Ks")
        fields = {field["name"]: field["value"] for field in embed["fields"]}
        self.assertEqual(fields["Strategy · bitcoin bought"], "1,666 BTC")
        self.assertEqual(fields["Strive · bitcoin bought"], "455 BTC")
        self.assertEqual(fields["Strive · money in / money out"], self.SUMMARY["companies"]["ASST"]["money"])
        self.assertNotIn("Strategy debt heads-up", fields)
        self.assertIn(mp.PAGE_URL, fields["Links"])
        self.assertIn(self.COMMIT, fields["Links"])

    def test_debt_heads_up_gets_its_own_field(self):
        summary = {**self.SUMMARY, "heads_up": ["Strategy debt $6.75B → $8.75B: strategy.com lists $8.71B of convertible notes"]}
        fields = {field["name"]: field["value"] for field in mp.discord_payload(summary, commit_url=self.COMMIT)["embeds"][0]["fields"]}
        self.assertTrue(fields["Strategy debt heads-up"].startswith("Strategy debt $6.75B → $8.75B"))

    def test_setup_ping_is_labelled(self):
        payload = mp.ping_payload()
        self.assertEqual(payload["embeds"][0]["title"], "Setup test — Monday publish workflow (no new edition)")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_command_line_prints_the_message(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "summary.json"
            path.write_text(json.dumps(self.SUMMARY), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(mp.main(["--discord", str(path), "--commit-url", self.COMMIT]), 0)
        self.assertEqual(json.loads(out.getvalue()), mp.discord_payload(self.SUMMARY, commit_url=self.COMMIT))


class DeriveEntriesTests(Providers):
    def test_additions_are_only_what_was_not_saved(self):
        rows = mp.live_report._merged_filings(feed_with(*OCT5), {})
        merged, added, notes = ar.derive_entries(rows, SUPPLEMENTS)
        self.assertEqual(notes, ["Strategy 2026-10-04", "Strive 2026-10-02"])
        self.assertEqual({ticker: sorted(days) for ticker, days in added["balances"].items()},
                         {"MSTR": ["2026-10-04"], "ASST": ["2026-10-02"]})
        self.assertEqual(sorted(added["balance_marks"]), ["2026-09-25", "2026-09-27", "2026-10-02"])
        self.assertNotIn("auto_reconciled_notes", merged)
        self.assertEqual(ar.derive_entries(rows, merged)[1],
                         {"balances": {}, "comparison_btc_prices": {}, "comparison_release_dates": {}, "balance_marks": {}})


if __name__ == "__main__":
    unittest.main()
