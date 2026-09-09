"""The public monitor can render new filings using GETs and no credentials."""
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from report import filing_monitor as monitor


class PublicMonitorTests(unittest.TestCase):
    def fake_streamlit(self):
        return SimpleNamespace(
            cache_data=lambda **_: lambda function: function,
            session_state={}, caption=Mock(), warning=Mock(), dataframe=Mock(),
            column_config=SimpleNamespace(LinkColumn=lambda label: label),
        )

    def test_cards_and_details_reuse_the_same_snapshot_without_a_second_request(self):
        st = self.fake_streamlit()
        snapshot = monitor.MonitorSnapshot({'schemaVersion': 1, 'issuers': []},
                                           {'schemaVersion': 1, 'filings': []})
        with patch.dict('sys.modules', {'streamlit': st}), \
             patch.object(monitor, 'read_monitor', side_effect=AssertionError('Must reuse card snapshot')) as read:
            monitor.render_monitor(snapshot)
        read.assert_not_called()
        self.assertTrue(any('No filing observations' in call.args[0] for call in st.caption.call_args_list))

    def test_feed_failure_returns_last_successful_snapshot_as_stale(self):
        st = self.fake_streamlit()
        status = {'schemaVersion': 1, 'issuers': []}
        feed = {'schemaVersion': 1, 'filings': [{'accession': 'latest-complete'}]}
        with patch.dict('sys.modules', {'streamlit': st}), \
             patch.object(monitor, 'monitor_url', return_value='https://report.example.workers.dev'), \
             patch.object(monitor, 'read_shared_monitor', side_effect=[(status, feed), OSError('Timed out')]):
            first = monitor.load_monitor_snapshot()
            second = monitor.load_monitor_snapshot()
        self.assertFalse(first.stale)
        self.assertTrue(second.stale)
        self.assertEqual(second.feed, first.feed)
        self.assertEqual(second.status, first.status)
        self.assertEqual(second.notice, 'SEC refresh unavailable.')

    def test_disconnected_monitor_is_explicit_and_does_not_fetch(self):
        st = self.fake_streamlit()
        with patch.dict('sys.modules', {'streamlit': st}), \
             patch.object(monitor, 'monitor_url', return_value=None), \
             patch.object(monitor, 'read_monitor') as read:
            result = monitor.load_monitor_snapshot()
        self.assertTrue(result.stale)
        self.assertIsNone(result.feed)
        self.assertIn('not connected', result.notice)
        read.assert_not_called()

    def test_filing_rows_keep_bought_and_sold_separate_without_inventing_zeros(self):
        base = {
            'ticker': 'ASST', 'form': '8-K', 'baseline': False,
            'primaryDocumentUrl': 'https://www.sec.gov/Archives/edgar/data/1920406/filing.htm',
        }
        for facts, expected in (
            ({'weekly_btc_sales': 125.25}, ('Not disclosed', '125.25 BTC')),
            ({'weekly_btc_purchases': 500, 'weekly_btc_sales': 125}, ('500 BTC', '125 BTC')),
            ({'weekly_btc_purchases': 0, 'weekly_btc_sales': 0}, ('0 BTC', '0 BTC')),
            ({'btc_holdings': 0}, ('Not disclosed', 'Not disclosed')),
            ({'weekly_btc_purchases': True, 'weekly_btc_sales': -5}, ('Not disclosed', 'Not disclosed')),
            ({'weekly_btc_sales': 1e-9}, ('Not disclosed', '<0.00000001 BTC')),
        ):
            with self.subTest(facts=facts):
                row = monitor.filing_rows({'filings': [dict(base, extracted={'facts': facts})]})[0]
                self.assertEqual((row['Bitcoin Bought'], row['Bitcoin Sold']), expected)

    def test_render_fetches_public_feed_without_credentials_or_acknowledgement(self):
        origin = 'https://capital-report.example.workers.dev'
        payloads = {
            origin + '/api/status': {'schemaVersion': 1, 'issuers': [], 'schedule': {'active': False}},
            origin + '/api/filings': {'schemaVersion': 1, 'filings': [{
                'ticker': ticker, 'form': '8-K', 'accession': accession,
                'baseline': False, 'status': 'ready_for_review',
                'primaryDocumentUrl': f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/report.htm',
            } for ticker, cik, accession in (
                ('MSTR', '1050446', '0001193125-26-375463'),
                ('ASST', '1920406', '0001628280-26-059468'),
            )]},
        }
        # There is deliberately no st.secrets or outgoing POST implementation.
        st = SimpleNamespace(
            cache_data=lambda **_: lambda function: function,
            fragment=lambda **_: lambda function: function,
            session_state={}, caption=Mock(), warning=Mock(), dataframe=Mock(),
            column_config=SimpleNamespace(LinkColumn=lambda label: label),
        )
        def response(request, **kwargs):
            self.assertEqual(request.get_method(), 'GET')
            self.assertIsNone(request.get_header('Authorization'))
            self.assertIsNone(request.data)
            body = BytesIO(json.dumps(payloads[request.full_url]).encode())
            body.geturl = lambda: request.full_url
            return body

        with patch.dict('sys.modules', {'streamlit': st}), \
                patch.object(monitor, 'monitor_url', return_value=origin), \
                patch.object(monitor, 'urlopen', side_effect=response) as read:
            monitor.render_monitor()
        self.assertEqual(read.call_count, 2)
        self.assertEqual({row['Company'] for row in st.dataframe.call_args.args[0]}, {'MSTR', 'ASST'})
        st.warning.assert_not_called()


if __name__ == '__main__':
    unittest.main()
