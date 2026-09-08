"""The embedded Friday panel downloads its immutable displayed dataset."""
from concurrent.futures import Future
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import importlib
import sys
from unittest import TestCase
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT / 'sources' / 'friday', ROOT):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from PIL import Image, ImageChops
from streamlit.testing.v1 import AppTest
import friday_page as page
from friday.data import load_demo
from friday.metrics import compute_panel
from friday.freshness import display_panel
from friday.presentation import displayed_export_panel, deferred_png, _cached_png, prepare_chart_specs
from friday.export import render_png, display_rows, marker_rows
from friday.runtime import session_snapshot, SESSION_KEY

STAMP = '2026-09-08T22:00:00+00:00'


def example_panel():
    row = {'date': '2026-09-04', 'close': 100, 'sma_200d': 80, 'sma_200w': 80}
    live = {'series': [dict(row, date='2025-01-02'), row, dict(row, date='2026-09-07', close=110)],
            'price': 120, 'price_as_of': '2026-09-08T21:00:00+00:00',
            'averages': {'200D': {'value': 80, 'extension_pct': 50}, '200W': {'value': 80, 'extension_pct': 50}},
            'live_point': {'date': '2026-09-08T21:00:00+00:00', 'close': 120, 'sma_200d': 80, 'sma_200w': 80}}
    return {'mode': 'latest', 'period': {'end': '2026-09-04', 'week_ending': '2026-09-04'},
            'header': {'btc': {'price': 80000}, 'companies': {}}, 'treasury': [], 'liquidity': [],
            'trends': {'BTC': {'price': 100}}, 'live_trends': {t: deepcopy(live) for t in ('BTC', 'MSTR', 'ASST')},
            'supply_loss': {'value': 30, 'series': []},
            'live_supply_loss': {'value': 45, 'profit_pct': 55, 'as_of': '2026-09-07', 'series': [
                {'date': '2026-09-04', 'value': 30, 'profit_pct': 70}, {'date': '2026-09-07', 'value': 45, 'profit_pct': 55}]},
            'sentiment': {'value': 40, 'series': []},
            'live_sentiment': {'value': 82, 'classification': 'Extreme Greed', 'as_of': '2026-09-08T21:30:00+00:00',
                'series': [{'date': '2026-09-04', 'value': 40}, {'date': '2026-09-07', 'value': 65}],
                'live_point': {'date': '2026-09-08T21:30:00+00:00', 'value': 82}},
            'sentiment_source': 'CoinMarketCap', 'supply_source': 'Checkonchain'}


class FridayExportTests(TestCase):
    def test_projection_keeps_financial_week_and_uses_displayed_live_charts(self):
        panel = example_panel()
        before = deepcopy(panel)
        projected = displayed_export_panel(panel, snapshot_as_of=STAMP)
        self.assertEqual(projected['period']['end'], '2026-09-04')
        self.assertEqual(projected['header']['btc']['price'], 80000)
        self.assertEqual(projected['sentiment']['value'], 82)
        self.assertEqual(projected['supply_loss']['value'], 45)
        self.assertEqual(projected['trends']['BTC']['price'], 120)
        self.assertEqual(projected['chart_cutoff'], STAMP)
        self.assertEqual(projected['snapshot_as_of'], STAMP)
        self.assertEqual(projected['export_basis'], 'displayed_latest')
        panel['live_trends']['BTC']['series'][0]['close'] = 999
        self.assertEqual(projected['trends']['BTC']['series'][0]['close'], 100)
        projected['header']['btc']['price'] = 1
        self.assertEqual(panel['header'], before['header'])

    def test_unavailable_live_readings_do_not_reinstate_frozen_numbers(self):
        panel = example_panel()
        snapshot = {'mode': 'latest', 'panel': panel, 'data': {'mode': 'latest', 'fetched_at': STAMP,
                    'refresh_meta': {'indicators': {'sentiment': {'status': 'unavailable'}, 'supply': {'status': 'unavailable'}}}}}
        visible = display_panel(snapshot)
        projected = displayed_export_panel(visible, snapshot_as_of=STAMP)
        self.assertIsNone(projected['sentiment']['value'])
        self.assertIsNone(projected['supply_loss']['value'])
        self.assertIsNone(projected['trends']['BTC']['price'])
        self.assertIsNone(projected['trends']['BTC']['live_point'])
        self.assertEqual(projected['sentiment']['series'], panel['live_sentiment']['series'])

    def test_download_captures_now_and_never_fetches_on_click(self):
        _cached_png.cache_clear()
        self.addCleanup(_cached_png.cache_clear)
        panel = example_panel()
        with patch('friday.presentation.render_png', return_value=b'captured image') as render, \
             patch('friday.data.load_latest', side_effect=AssertionError('No fetch on download')), \
             patch('friday.data.refresh_latest', side_effect=AssertionError('No refresh on download')):
            download = deferred_png(panel, snapshot_as_of=STAMP)
            render.assert_not_called()
            panel['live_sentiment']['value'] = 12
            panel['header']['btc']['price'] = 90000
            self.assertEqual(download(), b'captured image')
            received = render.call_args.args[0]
            self.assertEqual(received['sentiment']['value'], 82)
            self.assertEqual(received['header']['btc']['price'], 80000)
            download()
            self.assertEqual(render.call_count, 1)
            deferred_png(panel, snapshot_as_of=STAMP)()
            self.assertEqual(render.call_count, 2)

    def test_png_uses_post_friday_rows_markers_and_explicit_dates(self):
        projected = displayed_export_panel(example_panel(), snapshot_as_of=STAMP)
        with patch('friday.export.display_rows', wraps=display_rows) as windows:
            image_bytes = render_png(projected)
        self.assertTrue(all(call.args[1] != '2026-09-04' for call in windows.call_args_list))
        with Image.open(BytesIO(image_bytes)) as image:
            self.assertEqual(image.size, (1800, 1600))
            self.assertEqual(image.info['financial_week_end'], '2026-09-04')
            self.assertEqual(image.info['snapshot_as_of'], STAMP)
            self.assertEqual(image.info['chart_cutoff'], STAMP)
            self.assertEqual(image.info['sentiment_value'], '82')
            self.assertEqual(image.info['sentiment_as_of'], '2026-09-08T21:30:00+00:00')
            self.assertEqual(image.info['BTC_price_as_of'], '2026-09-08T21:00:00+00:00')
            before = image.copy()
        without = deepcopy(projected)
        without['sentiment']['live_point'] = None
        for trend in without['trends'].values():
            trend['live_point'] = None
        with Image.open(BytesIO(render_png(without))) as image:
            self.assertIsNotNone(ImageChops.difference(before.crop((54, 827, 1746, 1518)), image.crop((54, 827, 1746, 1518))).getbbox())

    def test_live_marker_axis_stub_never_creates_a_completed_price_or_sma_bar(self):
        rows = [{'date': '2026-09-04', 'close': 100, 'sma_200d': 80}]
        point = {'date': '2026-09-08T20:00:00Z', 'close': 120, 'sma_200d': 80}
        plotted = marker_rows(rows, point)
        self.assertEqual(plotted[-1], {'date': point['date']})
        self.assertEqual(len(rows), 1)
        self.assertEqual(point['close'], 120)

    def test_demo_uses_its_fixed_preview_without_latest_overlay(self):
        panel = example_panel()
        panel['mode'] = 'demo'
        projected = displayed_export_panel(panel, snapshot_as_of=STAMP)
        self.assertEqual(projected['sentiment']['value'], 40)
        self.assertEqual(projected['chart_cutoff'], '2026-09-04')

    def test_import_does_not_configure_page_fetch_or_render(self):
        with patch('streamlit.set_page_config') as config, patch('friday.runtime.session_snapshot') as fetch, \
             patch('streamlit.html') as html:
            importlib.reload(page)
            config.assert_not_called()
            fetch.assert_not_called()
            html.assert_not_called()
        # Restore the real imported symbol after the patch scope.
        importlib.reload(page)


class FridaySessionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        data = load_demo()
        data.update(mode='latest', fetched_at=STAMP)
        for ticker in ('BTC', 'MSTR', 'ASST'):
            data['latest_quotes'][ticker] = {'price': 123, 'as_of': '2026-09-08T21:00:00+00:00', 'source': 'Yahoo Finance'}
        data['refresh_meta'] = {'histories': {ticker: {'status': 'validated'} for ticker in data['prices']},
                               'indicators': {'sentiment': {'status': 'validated'}, 'supply': {'status': 'validated'}}}
        panel = compute_panel(data)
        cls.snapshot = {'mode': 'latest', 'data': data, 'panel': panel, 'charts': prepare_chart_specs(panel)}

    def test_unmount_restores_preferences_and_does_not_refetch_completed_data(self):
        future = Future()
        service = Mock()
        service.peek.return_value = self.snapshot
        service.request.return_value = future
        source = '''import streamlit as st
import friday_page
visible = st.checkbox("Show Friday", value=True, key="test_visible")
st.session_state['weekly_active_report'] = 'Friday' if visible else 'Monday'
if visible:
    friday_page.render()
else:
    st.write('Monday placeholder')
'''
        with patch('friday.runtime.get_service', return_value=service):
            app = AppTest.from_string(source, default_timeout=60).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.session_state[SESSION_KEY]['pending'])
            future.set_result(self.snapshot)
            app.run()
            self.assertFalse(app.exception)
            app.segmented_control(key='friday_history_widget_BTC').set_value('2Y').run()
            self.assertFalse(app.toggle)
            self.assertNotIn('friday_source_widget', [widget.key for widget in app.segmented_control])
            self.assertFalse(app.exception)
            self.assertEqual(service.request.call_count, 1)
            app.checkbox(key='test_visible').uncheck().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['friday_history_preference_BTC'], '2Y')
            app.checkbox(key='test_visible').check().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.segmented_control(key='friday_history_widget_BTC').value, '2Y')
            self.assertFalse(app.toggle)
            self.assertFalse(app.session_state[SESSION_KEY]['pending'])
            self.assertEqual(service.request.call_count, 1)
            next_future = Future()
            service.request.return_value = next_future
            app.button(key='friday_refresh_button').click().run()
            self.assertTrue(app.session_state[SESSION_KEY]['pending'])
            self.assertEqual(service.request.call_count, 2)
            app2 = AppTest.from_string(source, default_timeout=60).run()
            self.assertTrue(app2.session_state[SESSION_KEY]['pending'])
            self.assertEqual(service.request.call_count, 3)

    def test_hidden_poll_does_not_refresh_or_rerun(self):
        state = {'weekly_active_report': 'Monday'}
        with patch.object(page.st, 'session_state', state), patch.object(page, 'session_snapshot') as poll, patch.object(page.st, 'rerun') as rerun:
            page.finish_refresh.__wrapped__()
            poll.assert_not_called()
            rerun.assert_not_called()
