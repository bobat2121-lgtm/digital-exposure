"""SATS issuance must remain distinct from SATA and from liquidation claims."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from panels import extras, monday_preview, themes
from report import auto_reconcile, live_report
from report.calculations import calculate_company
from report.current_prices import load_current_prices

ROOT = Path(__file__).resolve().parents[1]


class SataSatsIssuanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prices = load_current_prices()
        cls.feed = json.loads((ROOT / 'data/latest-report-filings.json').read_text())
        cls.result = live_report.resolve_live_report(cls.prices, cls.feed, through_date='2026-11-01')
        cls.preview = monday_preview.build_preview(cls.result.report, cls.prices, cls.feed,
                                                  extras.load_extras(offline=True))

    def test_november_2_separate_issuance_and_claims(self):
        self.assertIsNone(self.result.notice)
        company = next(c for c in self.result.report.companies if c.ticker == 'ASST')
        self.assertEqual(company.balance_date, '2026-10-30')
        self.assertEqual(company.current.btc_holdings, 43124)
        metric = calculate_company(company, self.result.report.current_btc_price,
                                   self.result.report.prior_btc_price)
        self.assertAlmostEqual(metric.net_preferred_capital, 322690.4988241124)
        self.assertAlmostEqual(company.current.preferred_claims, 2106694360.952381)
        self.assertEqual(self.preview.extras['ASST'].btc_cost, 10000000)
        self.assertEqual(self.preview.extras['ASST'].reported_btc_purchase_price, 80526)
        inflows, outflows = monday_preview.funding_flows(self.preview.extras['ASST'])
        self.assertEqual(dict((label, value) for label, value, _ in inflows)['SATA'], 0)
        self.assertAlmostEqual(dict((label, value) for label, value, _ in inflows)['SATS'], 322690.4988241124)
        self.assertNotIn('PREF', [label for label, _, _ in inflows])
        self.assertAlmostEqual(sum(x[1] for x in inflows), sum(x[1] for x in outflows))

    def test_missing_sats_price_never_becomes_zero_or_par_proceeds(self):
        original = live_report.load_estimate
        with patch.object(live_report, 'load_estimate', side_effect=lambda symbol, day:
                          None if symbol == 'SATS' and day == date(2026, 11, 2) else original(symbol, day)):
            result = live_report.resolve_complete_report(self.prices, self.feed)
        self.assertEqual(result.report.companies[1].balance_date, '2026-10-23')
        self.assertIn('last complete report', result.notice)

    def test_gross_sales_and_buybacks_are_not_netted_or_double_counted(self):
        e = monday_preview.CompanyExtras('ASST', common_in=10, common_out=0,
            preferred_in=120, preferred_out=30, preferred_by_series=(('SATA', 100, 20), ('SATS', 20, 10)),
            liquid_change=0, btc_cost=90, dividends=10)
        inflows, outflows = monday_preview.funding_flows(e)
        self.assertEqual(inflows, [('COMMON', 10, 'raise'), ('SATA', 100, 'raise'), ('SATS', 20, 'raise')])
        self.assertEqual(outflows[:2], [('SATA BUYBACK', 20, 'buyback'), ('SATS BUYBACK', 10, 'buyback')])
        self.assertEqual(sum(v for _, v, _ in inflows), sum(v for _, v, _ in outflows))

    def test_partial_collector_cannot_drop_outstanding_sats(self):
        row = deepcopy(next(r for r in self.feed['filings'] if r['ticker'] == 'ASST'))
        row['extracted']['balanceDate'] = '2026-11-06'
        row['extracted']['facts'].pop('sats_shares')
        supplements = json.loads((ROOT / 'data/report-supplements.json').read_text())
        updated, notes = auto_reconcile.augment([row], supplements)
        self.assertNotIn('2026-11-06', updated['balances']['ASST'])
        self.assertTrue(any('SATA and SATS claims' in note for note in notes))

    def test_both_image_styles_fit_the_separate_rows(self):
        for key in ('terminal', 'broadsheet'):
            with self.subTest(style=key):
                image, overflows = monday_preview.render_png(self.preview, themes.get(key))
                self.assertTrue(image.startswith(b'\x89PNG'))
                self.assertEqual(overflows, [])


if __name__ == '__main__':
    unittest.main()
