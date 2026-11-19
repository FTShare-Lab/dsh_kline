from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import unittest

from tools.exchange_time import exchange_clock, time_display
from tools.trend_lines import resolve_anchor_time
from tools.chart_measurements import measure_chart_region
from tools.channel_preview import preview_channel


class ExchangeTimeTests(unittest.TestCase):
    def test_us_dates_dst_and_exact_date_input_share_clock_without_mutating_rows(self):
        stamps = [int(datetime.fromisoformat(t).timestamp()) for t in
                  ('2026-10-09T16:00:00-04:00', '2026-11-17T16:00:00-05:00')]
        rows = [dict(time=t, open=10, high=12, low=8, close=11, volume=1) for t in stamps]
        before = deepcopy(rows)
        drawing = {'id': 'abc', 'points': [{'label': '0', 'time': stamps[0]}, {'label': 'C', 'time': stamps[1]}]}
        result = time_display('SLV.US', rows, [drawing], sample=rows, visible=rows)
        self.assertEqual(result['timezone'], 'America/New_York')
        self.assertEqual(result['basis'], 'exchange_local')
        self.assertEqual(result['sample_labels'][0]['iso'], '2026-10-09T16:00:00-04:00')
        self.assertEqual(result['sample_labels'][1]['iso'], '2026-11-17T16:00:00-05:00')
        self.assertEqual(result['drawing_anchors'][0]['points'][1]['date'], '2026-11-17')
        payload = {'symbol': 'SLV.US', 'interval': 'day', 'chartCommands': [{'type': 'SET_CANDLES', 'rows': rows}]}
        for date, timestamp in zip(('2026-10-09', '2026-11-17'), stamps):
            self.assertEqual(resolve_anchor_time(payload, date), timestamp)
            self.assertEqual(resolve_anchor_time(payload, str(timestamp)), timestamp)
        self.assertEqual(rows, before)

    def test_cn_hk_and_explicit_unknown_market_fallback(self):
        for symbol, zone, basis in [('600000.XSHG', 'Asia/Shanghai', 'exchange_local'),
                                    ('00700.HK', 'Asia/Hong_Kong', 'exchange_local'),
                                    ('100.NDX', 'America/New_York', 'exchange_local'),
                                    ('100.SPX', 'America/New_York', 'exchange_local'),
                                    ('100.DJIA', 'America/New_York', 'exchange_local'),
                                    ('PDD.NASDAQ', 'America/New_York', 'exchange_local'),
                                    ('SLV.NYSE', 'America/New_York', 'exchange_local'),
                                    ('100.HSI', 'Asia/Hong_Kong', 'exchange_local'),
                                    ('00700.HKG', 'Asia/Hong_Kong', 'exchange_local'),
                                    ('TEST.X', 'Asia/Shanghai', 'legacy_timezone_fallback')]:
            self.assertEqual((exchange_clock(symbol)[0].key, exchange_clock(symbol)[1]), (zone, basis))

    def test_frozen_slv_abc_dates_measurement_and_preview_match_new_york(self):
        data = json.loads((Path(__file__).parent / 'fixtures/slv_2026_11_17_abc.json').read_text())
        rows = data['rows']
        source = {'symbol': 'SLV.US', 'interval': 'day', 'chartCommands': [{'type': 'SET_CANDLES', 'rows': rows}]}
        start = resolve_anchor_time(source, '2026-10-09')
        self.assertEqual(start, 1791576000)
        measured = measure_chart_region(rows, 'day', '2026-10-09', '2026-10-26', symbol='SLV.US')
        self.assertEqual(measured['boundary_evidence']['wick_envelope']['upper']['date'], '2026-10-09')
        self.assertEqual(measured['boundary_evidence']['wick_envelope']['lower']['date'], '2026-10-26')
        preview = preview_channel(rows, 'day', start_time='2026-10-09', start_price=55.25,
                                  end_time='2026-10-26', end_price=47.86,
                                  parallel_time='2026-10-14', parallel_price=50.01, symbol='SLV.US')
        self.assertEqual(preview['bars'][0]['date'], '2026-10-09')
        self.assertTrue(preview['bars'][0]['iso'].endswith('-04:00'))

if __name__ == '__main__': unittest.main()


def test_codex_context_has_same_exchange_dates_as_dsh():
    from codex_runtime.state import CodexChartStore
    from test_codex_v060 import payload
    value = payload()
    rows = json.loads((Path(__file__).parent / 'fixtures/slv_2026_11_17_abc.json').read_text())['rows']
    value['symbol'] = 'SLV.US'
    value['chartCommands'][0]['rows'] = rows
    store = CodexChartStore()
    state = store.create(value)
    context = store.context(state.context_ref)
    assert context['time_display']['timezone'] == 'America/New_York'
    assert context['time_display']['loaded_end']['date'] == '2026-11-17'
    assert context['time_display']['loaded_end']['iso'].endswith('-05:00')
    assert context['candles'] == rows
