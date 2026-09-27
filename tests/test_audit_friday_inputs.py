"""The audit fails blank Friday price/NAV tiles and says why (they used to pass as '—')."""
import importlib.util
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("audit_panels", ROOT / "scripts" / "audit_panels.py")
audit_panels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_panels)


def rows(mstr, asst):
    return [{"metric": "MSTR price / NAV", "value": mstr}, {"metric": "ASST price / NAV", "value": asst}]


class FridayInputsAuditTests(TestCase):
    def setUp(self):
        audit_panels.CHECKS.clear()

    def results(self):
        return {item["id"]: item for item in audit_panels.CHECKS}

    def test_blank_tiles_fail_with_the_reason(self):
        dataset = {"financial_inputs": {"status": "unavailable", "error": "OSError: quote host down",
                                        "notice": "Monday balance inputs could not be validated"}}
        audit_panels.audit_friday_inputs(dataset, rows("—", "—"))
        found = self.results()
        self.assertEqual(found["inputs"]["status"], "FAIL")
        for ticker in ("MSTR", "ASST"):
            self.assertEqual(found[f"{ticker}.price_nav"]["status"], "FAIL")
            self.assertIn("OSError: quote host down", found[f"{ticker}.price_nav"]["detail"])

    def test_current_inputs_pass(self):
        audit_panels.audit_friday_inputs({"financial_inputs": {"status": "current"}}, rows("1.19x", "2.08x"))
        self.assertEqual({item["status"] for item in audit_panels.CHECKS}, {"PASS"})

    def test_saved_edition_warns(self):
        dataset = {"financial_inputs": {"status": "checkpoint", "notice": "Monday filing feed unavailable"}}
        audit_panels.audit_friday_inputs(dataset, rows("1.19x", "2.08x"))
        found = self.results()
        self.assertEqual(found["inputs"]["status"], "WARN")
        self.assertEqual(found["MSTR.price_nav"]["status"], "PASS")
