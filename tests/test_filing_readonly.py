"""The public monitor can render new filings using GETs and no credentials."""
from io import BytesIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from report import filing_monitor as monitor


class PublicMonitorTests(unittest.TestCase):
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
