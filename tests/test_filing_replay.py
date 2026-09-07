"""Offline filing publication transactions, using only temporary directories."""

from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from report.filing_replay import process_filing_event, run_rehearsal, simulated_filing_event
from report.historical_data import historical_report


class FilingReplayTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "published-replay.json"

    def publish(self):
        result = process_filing_event(json.dumps(simulated_filing_event()), self.path)
        self.assertEqual(result["status"], "published", result)
        return result

    def test_new_accession_validates_and_renders_complete_candidate_before_publication(self):
        original_historical = historical_report()
        result = self.publish()
        state = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(state["simulation"])
        self.assertEqual(state["generation"], 1)
        self.assertEqual(state["metrics"]["MSTR"]["net_common_capital"], 602_800_000)
        self.assertEqual(state["metrics"]["MSTR"]["net_preferred_capital"], -151_800_000)
        self.assertEqual(state["metrics"]["MSTR"]["btc_holdings"], 845_050)
        self.assertEqual(state["report"]["data_label"], "OFFLINE FILING REPLAY · SIMULATION")
        self.assertEqual(set(state["render_validation"]), {"post", "detailed"})
        self.assertTrue(all(row["bytes"] > 1000 and len(row["sha256"]) == 64
                            for row in state["render_validation"].values()))
        self.assertEqual(list(result["phase_ms"]), ["parse_normalized_json", "validate_filing_facts",
                         "check_accession", "build_candidate", "validate_complete_candidate",
                         "validate_both_png_layouts", "atomic_publish"])
        self.assertEqual(result["simulated_detection_ms"], 15_000)
        self.assertAlmostEqual(result["simulated_release_to_publish_ms"], 15_000 + result["processing_ms"])
        self.assertTrue(all(value >= 0 for value in result["phase_ms"].values()))
        self.assertEqual(historical_report(), original_historical)

    def test_duplicate_receipt_is_no_op_even_with_later_observation_time(self):
        self.publish()
        original = self.path.read_bytes()
        event = simulated_filing_event()
        event["observed_at"] = "2026-08-31T12:01:00+00:00"
        with patch("report.filing_replay._candidate") as build, patch("report.filing_replay._atomic_publish") as publish:
            result = process_filing_event(event, self.path)
        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(result["generation"], 1)
        build.assert_not_called()
        publish.assert_not_called()
        self.assertEqual(self.path.read_bytes(), original)

    def test_missing_invalid_and_conflicting_input_retains_previous_publication(self):
        self.publish()
        original = self.path.read_bytes()
        bad = simulated_filing_event()
        bad["accession"] = "SIMULATION-INCOMPLETE-002"
        del bad["facts"]["common_issuance_proceeds_usd"]
        cases = [bad, "{malformed", {**simulated_filing_event(), "simulation": False}]
        for value in (None, -1, math.nan, math.inf, True):
            invalid = simulated_filing_event()
            invalid["accession"] = "SIMULATION-INVALID-003"
            invalid["facts"]["strc_repurchases_cash_usd"] = value
            cases.append(invalid)
        conflicting = simulated_filing_event()
        conflicting["facts"]["common_issuance_proceeds_usd"] += 1
        cases.append(conflicting)
        changed_claim_basis = deepcopy(bad)
        changed_claim_basis["facts"] = dict(simulated_filing_event()["facts"])
        changed_claim_basis["facts"]["strc_repurchased_shares"] += 1
        cases.append(changed_claim_basis)
        for event in cases:
            with self.subTest(event=event):
                result = process_filing_event(event, self.path)
                self.assertEqual(result["status"], "rejected", result)
                self.assertNotIn("atomic_publish", result["phase_ms"])
                self.assertEqual(self.path.read_bytes(), original)

    def test_missing_supplemental_value_or_render_failure_blocks_publication(self):
        self.publish()
        original = self.path.read_bytes()
        event = simulated_filing_event()
        event["accession"] = "SIMULATION-NEW-004"
        historical = historical_report()
        strategy, strive = historical.companies
        incomplete = replace(historical, companies=(replace(strategy, current=replace(strategy.current, debt_principal=None)), strive))
        with patch("report.filing_replay.historical_report", return_value=incomplete):
            result = process_filing_event(event, self.path)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("Incomplete candidate", result["error"])
        self.assertEqual(self.path.read_bytes(), original)
        with patch("report.filing_replay.render_post_png", side_effect=ValueError("layout overflow")):
            result = process_filing_event(event, self.path)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("layout overflow", result["error"])
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_atomic_replace_cleans_pending_file_and_retains_last_good_state(self):
        self.publish()
        original = self.path.read_bytes()
        event = simulated_filing_event()
        event["accession"] = "SIMULATION-NEW-005"
        with patch("report.filing_replay.Path.replace", side_effect=OSError("simulated disk failure")):
            result = process_filing_event(event, self.path)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_default_rehearsal_is_repeatable_and_does_not_use_app_publication_paths(self):
        first = run_rehearsal(self.directory)
        second = run_rehearsal(self.directory)
        self.assertTrue(first["passed"], first)
        self.assertTrue(second["passed"], second)
        self.assertNotEqual(first["output_dir"], second["output_dir"])
        self.assertEqual([row["status"] for row in first["scenarios"]], ["published", "duplicate", "rejected"])
        self.assertTrue(first["duplicate_preserved_bytes"])
        self.assertTrue(first["rejected_preserved_bytes"])
        for run in (first, second):
            self.assertTrue((Path(run["output_dir"]) / "rehearsal-results.md").exists())
        invalid_target = process_filing_event(simulated_filing_event(), self.directory / "current-prices.json")
        self.assertEqual(invalid_target["status"], "rejected")
        self.assertFalse((self.directory / "current-prices.json").exists())


if __name__ == "__main__":
    unittest.main()
