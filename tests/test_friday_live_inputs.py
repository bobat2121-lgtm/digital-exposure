"""Offline coverage of the shared financial-feed orchestration and light polls."""
from copy import deepcopy
from concurrent.futures import Future
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT / "sources" / "friday", ROOT):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from PIL import Image
from friday import live_inputs, runtime
from friday.data import load_demo
from friday.metrics import compute_panel
from friday.presentation import deferred_png, _cached_png
from report import live_report
from report.current_prices import load_current_prices
from report.friday_inputs import resolve_friday_inputs


NOW = datetime(2026, 9, 8, 23, 30, tzinfo=timezone.utc)
FUTURE = datetime(2026, 9, 14, 15, 30, tzinfo=timezone.utc)
STAMP = "2026-09-08T23:00:00+00:00"
ORIGIN = "https://capital-report.example.workers.dev"


def next_pair(feed):
    result = deepcopy(feed)
    for index, source in enumerate(row for row in feed["filings"] if row["filedDate"] == "2026-09-08"):
        row = deepcopy(source)
        accession = row["accession"]
        row["accession"] = accession[:-6] + f"59990{index}"
        row["primaryDocumentUrl"] = row["primaryDocumentUrl"].replace(accession.replace("-", ""), row["accession"].replace("-", ""))
        row["documents"][0]["url"] = row["primaryDocumentUrl"]
        row.update(filedDate="2026-09-14", acceptedAt="2026-09-14T12:00:00Z")
        extracted = row["extracted"]
        extracted["periodStart"] = "2026-09-08" if row["ticker"] == "MSTR" else "2026-09-07"
        extracted["periodEnd"] = extracted["balanceDate"] = "2026-09-13" if row["ticker"] == "MSTR" else "2026-09-11"
        if row["ticker"] == "ASST":
            extracted["priorBalanceDate"] = "2026-09-04"
            extracted["priorFacts"] = deepcopy(extracted["facts"])
            extracted["facts"]["net_sata_shares_change"] = 0
        result["filings"].append(row)
    return result


class FridayLiveInputsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.market = load_demo()
        cls.market.update(mode="latest", fetched_at=STAMP)
        cls.nav_prices = load_current_prices()
        cls.feed = json.loads(live_report.CHECKPOINT.read_text(encoding="utf-8"))
        cls.financial = resolve_friday_inputs(cls.nav_prices, cls.feed, now=NOW)
        cls.financial.update(status="current", checked_at=STAMP, using_saved_nav_prices=False)
        cls.base_data = live_inputs.apply_financial_data(cls.market, {
            "financial_inputs": cls.financial, "nav_prices": cls.nav_prices})
        cls.base_panel = compute_panel(cls.base_data)
        cls.base_panel["financial_inputs"] = deepcopy(cls.financial)

    def setUp(self):
        self.worker = self.start_patch("friday.live_inputs.read_shared_monitor", return_value=({}, deepcopy(self.feed)))
        self.start_patch("friday.live_inputs.monitor_url", return_value=ORIGIN)
        self.store = SimpleNamespace(refresh=Mock(return_value=SimpleNamespace(
            prices=deepcopy(self.nav_prices), using_saved_prices=False)))
        self.store_factory = self.start_patch("friday.live_inputs.nav_price_store", return_value=self.store)
        # Any accidental route outside the mocked orchestration boundary fails.
        self.start_patch("report.filing_monitor.urlopen", side_effect=AssertionError("No Worker network in tests"))
        self.start_patch("report.current_prices.urlopen", side_effect=AssertionError("No quote network in tests"))

    def start_patch(self, target, *args, **kwargs):
        patcher = patch(target, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def state(self):
        snapshot = {"mode": "latest", "pending": False, "error": None,
                    "data": deepcopy(self.base_data), "panel": deepcopy(self.base_panel),
                    "charts": {"ready": {"sma:BTC:4Y": {"mark": "line"}}, "history": {}},
                    "updated_at": 123.0, "request_id": 5, "revision": 5}
        return {"weekly_active_report": "Friday", runtime.SESSION_KEY: snapshot}

    def test_refresh_wrapper_combines_fresh_market_with_actual_current_pair(self):
        previous = deepcopy(self.base_data)
        before = deepcopy(previous)
        newer_market = deepcopy(self.market)
        newer_market["fetched_at"] = "2026-09-08T23:01:00+00:00"
        with patch("friday.data.refresh_latest", return_value=newer_market) as refresh, \
             patch("friday.data.load_latest", side_effect=AssertionError("Existing history must refresh")):
            result = live_inputs.fetch_snapshot(previous)
        refresh.assert_called_once_with(previous)
        self.worker.assert_called_once_with(ORIGIN, force=True)
        self.store.refresh.assert_called_once_with()
        self.assertEqual(result["fetched_at"], newer_market["fetched_at"])
        self.assertEqual(result["companies"]["ASST"]["btc_held"], 24531)
        self.assertEqual(result["companies"]["MSTR"]["cash_usd"], 6_540_000_000)
        self.assertEqual(result["companies"], self.financial["companies"])
        self.assertEqual(result["financial_inputs"]["status"], "current")
        self.assertEqual(previous, before)

    def test_first_worker_outage_uses_explicit_shared_checkpoint(self):
        self.worker.side_effect = OSError("test outage")
        with patch("friday.data.load_latest", return_value=deepcopy(self.market)) as load, \
             patch("friday.data.refresh_latest", side_effect=AssertionError("No previous market history")):
            result = live_inputs.fetch_snapshot()
        load.assert_called_once_with()
        self.assertEqual(result["companies"], self.financial["companies"])
        self.assertEqual(result["financial_inputs"]["status"], "checkpoint")
        self.assertIn("verified saved filing edition", result["financial_inputs"]["notice"])

    def test_existing_worker_outage_retains_whole_financial_edition_and_its_marks(self):
        previous = deepcopy(self.base_data)
        before = deepcopy(previous)
        changed_marks = deepcopy(self.nav_prices)
        changed_marks["quotes"]["STRC"]["price"] += 10
        self.store.refresh.return_value.prices = changed_marks
        self.worker.side_effect = OSError("test outage")
        result = live_inputs.fetch_financial_inputs(previous)
        self.assertEqual(result["financial_inputs"]["status"], "retained")
        self.assertEqual(result["financial_inputs"]["companies"], previous["companies"])
        self.assertEqual(result["financial_inputs"]["input_version"], previous["financial_inputs"]["input_version"])
        self.assertEqual(result["nav_prices"], previous["nav_prices"])
        self.assertEqual(previous, before)

    def test_new_pair_missing_nav_inputs_blanks_old_values(self):
        future = next_pair(self.feed)
        self.worker.return_value = ({}, future)
        with patch("friday.live_inputs.resolve_friday_inputs", side_effect=lambda prices, feed: resolve_friday_inputs(prices, feed, now=FUTURE)):
            result = live_inputs.fetch_financial_inputs(self.base_data, refresh_prices=False)
        self.assertEqual(result["financial_inputs"]["status"], "current")
        self.assertEqual(result["financial_inputs"]["companies"]["MSTR"]["baseline_at"], "2026-09-13")
        for company in result["financial_inputs"]["companies"].values():
            self.assertIsNone(company["debt_usd"])
            self.assertIsNone(company["preferred_usd"])
            self.assertIsNotNone(company["btc_held"])
        self.assertIsNone(result["financial_inputs"]["companies"]["MSTR"]["shares"])
        applied = live_inputs.apply_financial_data(self.base_data, result)
        panel = compute_panel(applied)
        self.assertTrue(all(item["nav_per_share"] is None for item in panel["treasury"]))
        self.assertTrue(all(item["nav_per_share"] is not None for item in self.base_panel["treasury"]))
        self.store_factory.assert_not_called()

    def test_older_pair_cannot_regress_a_newer_publication(self):
        previous = deepcopy(self.base_data)
        for company in previous["financial_inputs"]["companies"].values():
            company["baseline_at"] = "2026-09-13"
            company["btc_held"] += 1000
        before = deepcopy(previous)
        result = live_inputs.fetch_financial_inputs(previous, refresh_prices=False)
        self.assertEqual(result["financial_inputs"]["companies"], previous["financial_inputs"]["companies"])
        self.assertEqual(result["financial_inputs"]["status"], "retained")
        self.assertIn("older filing edition", result["financial_inputs"]["notice"])
        self.assertEqual(previous, before)

    def test_balance_only_poll_without_nav_prices_never_fetches_quotes(self):
        for previous in ({}, {**deepcopy(self.base_data), "nav_prices": None}):
            with self.subTest(previous=bool(previous)):
                result = live_inputs.fetch_financial_inputs(previous, refresh_prices=False)
                self.assertIsNone(result["nav_prices"])
                self.assertEqual(result["financial_inputs"]["status"], "retained" if previous else "unavailable")
                if previous:
                    self.assertEqual(result["financial_inputs"]["companies"], previous["financial_inputs"]["companies"])
        self.store_factory.assert_not_called()
        self.worker.assert_not_called()

    def test_older_publication_on_same_balance_date_cannot_replace_a_later_receipt(self):
        previous = deepcopy(self.base_data)
        later = previous["financial_inputs"]
        later["companies"]["MSTR"]["disclosed_at"] = "2026-09-08T11:00:00+00:00"
        later["companies"]["MSTR"]["debt_usd"] -= 100_000_000
        later["version"], later["input_version"] = "later-receipt", "later-values"
        result = live_inputs.fetch_financial_inputs(previous, refresh_prices=False)
        self.assertEqual(result["financial_inputs"]["companies"], later["companies"])
        self.assertEqual(result["financial_inputs"]["version"], "later-receipt")
        self.assertEqual(result["financial_inputs"]["status"], "retained")

    def test_older_cache_and_completed_future_keep_newer_session_financial_inputs(self):
        state = self.state()
        stale = deepcopy(state[runtime.SESSION_KEY])
        current = state[runtime.SESSION_KEY]
        newer = deepcopy(current["data"]["financial_inputs"])
        newer["companies"]["MSTR"]["disclosed_at"] = "2026-09-08T11:00:00+00:00"
        newer["companies"]["MSTR"]["debt_usd"] -= 100_000_000
        newer["version"], newer["input_version"] = "later-receipt", "later-values"
        current["data"] = live_inputs.apply_financial_data(current["data"], {
            "financial_inputs": newer, "nav_prices": current["data"]["nav_prices"]})
        current["panel"] = runtime.metrics.reprice_company_inputs(current["panel"], current["data"], current["data"]["companies"])
        current["panel"]["financial_inputs"] = deepcopy(newer)
        expected_nav = current["panel"]["header"]["companies"]["MSTR"]["nav_per_share"]
        future = Future()
        service = Mock()
        service.peek.return_value = stale
        service.request.return_value = future
        with patch("friday.runtime.get_service", return_value=service):
            pending = runtime.session_snapshot(state, "latest", "manual")
            self.assertTrue(pending["pending"])
            self.assertEqual(pending["data"]["financial_inputs"]["version"], "later-receipt")
            self.assertEqual(pending["data"]["companies"], newer["companies"])
            completed = deepcopy(stale)
            completed["data"]["fetched_at"] = "2026-09-08T23:05:00+00:00"
            completed["panel"]["fetched_at"] = completed["data"]["fetched_at"]
            future.set_result(completed)
            ready = runtime.session_snapshot(state, "latest")
        self.assertFalse(ready["pending"])
        self.assertEqual(ready["data"]["fetched_at"], "2026-09-08T23:05:00+00:00")
        self.assertEqual(ready["data"]["companies"], newer["companies"])
        self.assertEqual(ready["panel"]["header"]["companies"]["MSTR"]["nav_per_share"], expected_nav)
        self.assertIs(ready["charts"], completed["charts"])
        service.request.assert_called_once_with()
        self.worker.assert_not_called()
        self.store_factory.assert_not_called()

    def test_poll_changes_financial_cards_without_fetching_or_rebuilding_charts(self):
        state = self.state()
        original = state[runtime.SESSION_KEY]
        original_data, original_panel = deepcopy(original["data"]), deepcopy(original["panel"])
        changed = deepcopy(self.financial)
        changed["companies"]["MSTR"]["debt_usd"] -= 100_000_000
        changed["version"], changed["input_version"] = "changed-debt", "changed-debt-values"
        with patch("friday.live_inputs.resolve_friday_inputs", return_value=changed), \
             patch("friday.data.load_latest", side_effect=AssertionError("No full market load on financial poll")), \
             patch("friday.data.refresh_latest", side_effect=AssertionError("No market refresh on financial poll")), \
             patch("friday.runtime.prepare_chart_specs", side_effect=AssertionError("No chart rebuild")), \
             patch("friday.runtime.metrics.compute_panel", side_effect=AssertionError("No full recalculation")):
            self.assertTrue(runtime.poll_company_inputs(state, force=True))
        result = state[runtime.SESSION_KEY]
        self.worker.assert_called_once_with(ORIGIN, force=False)
        self.store_factory.assert_not_called()
        self.assertEqual(result["data"]["fetched_at"], original_data["fetched_at"])
        self.assertEqual(result["panel"]["fetched_at"], original_panel["fetched_at"])
        self.assertEqual(result["updated_at"], original["updated_at"])
        self.assertIs(result["charts"], original["charts"])
        for field in ("trends", "live_trends", "sentiment", "live_sentiment", "supply_loss", "live_supply_loss", "liquidity"):
            self.assertIs(result["panel"][field], original["panel"][field])
        self.assertEqual(original["data"], original_data)
        self.assertEqual(original["panel"], original_panel)
        prior_nav = original["panel"]["header"]["companies"]["MSTR"]["nav_per_share"]
        new_nav = result["panel"]["header"]["companies"]["MSTR"]["nav_per_share"]
        self.assertGreater(new_nav, prior_nav)

    def test_unchanged_poll_only_updates_check_time_and_returns_no_rerun(self):
        state = self.state()
        original = state[runtime.SESSION_KEY]
        with patch("friday.runtime.metrics.reprice_company_inputs", side_effect=AssertionError("Unchanged data must not reprice")):
            self.assertFalse(runtime.poll_company_inputs(state, force=True))
        result = state[runtime.SESSION_KEY]
        self.assertIs(result["panel"], original["panel"])
        self.assertIs(result["charts"], original["charts"])
        self.assertEqual(result["data"]["fetched_at"], original["data"]["fetched_at"])
        self.assertNotEqual(result["data"]["financial_inputs"]["checked_at"], original["data"]["financial_inputs"]["checked_at"])
        self.store_factory.assert_not_called()

    def test_hidden_pending_failed_and_missing_snapshot_never_poll(self):
        for kind in ("hidden", "pending", "failed", "missing"):
            state = self.state()
            if kind == "hidden":
                state["weekly_active_report"] = "Monday"
            elif kind == "pending":
                state[runtime.SESSION_KEY]["pending"] = True
            elif kind == "failed":
                state[runtime.SESSION_KEY]["error"] = "prior failure"
            else:
                state.pop(runtime.SESSION_KEY)
            with self.subTest(kind=kind):
                self.assertFalse(runtime.poll_company_inputs(state, force=True))
        self.worker.assert_not_called()
        self.store_factory.assert_not_called()

    def test_recent_poll_is_throttled_without_network(self):
        state = self.state()
        state[runtime.BALANCE_POLL_KEY] = 100
        with patch("friday.runtime.monotonic", return_value=110):
            self.assertFalse(runtime.poll_company_inputs(state))
        self.worker.assert_not_called()

    def test_download_captures_selected_financial_edition_without_network(self):
        _cached_png.cache_clear()
        self.addCleanup(_cached_png.cache_clear)
        panel = deepcopy(self.base_panel)
        download = deferred_png(panel, snapshot_as_of=STAMP)
        panel["financial_inputs"]["version"] = "later-state"
        panel["treasury"][0]["baseline_at"] = "2099-01-01"
        with Image.open(BytesIO(download())) as image:
            self.assertEqual(image.info["financial_edition"], self.financial["version"])
            self.assertEqual(image.info["balance_dates"], "MSTR:2026-09-07; ASST:2026-09-04")
            self.assertEqual(image.info["financial_week_end"], "2026-09-04")
            self.assertEqual(image.info["snapshot_as_of"], STAMP)
        self.worker.assert_not_called()
        self.store_factory.assert_not_called()
