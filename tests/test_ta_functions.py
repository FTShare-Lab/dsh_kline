import asyncio
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import talib

import chart_service
import server
from core.calc import calc_metrics, series_atr, series_boll, series_kdj, series_ma, series_macd, series_rsi, series_vwap
from core.ta_engine import ENGINE_VERSION, calculate, catalog
from tools.draw import draw_kline
from tools.lines import LineError
from tools.ta_functions import list_ta_catalog, read_ta, run_ta
import test_chart_edits as fixtures


ROOT = Path(__file__).resolve().parents[1]
FROZEN = json.loads((ROOT / 'benchmarks/2026-10-12/frozen-charts/B05-2.json').read_text())
ROWS = next(command['rows'] for command in FROZEN['chartCommands'] if command['type'] == 'SET_CANDLES')


class TalibEngineTests(unittest.TestCase):
    def test_new_chart_and_summary_identify_calculation_engine(self):
        chart = draw_kline(ROWS, indicators=['ma', 'macd', 'atr'])
        summary = calc_metrics(ROWS, ['bollinger', 'rsi', 'atr'])
        self.assertEqual(chart['calculation_engine']['wrapper_version'], ENGINE_VERSION)
        self.assertEqual(summary['calculation_engine'], chart['calculation_engine'])

    def test_all_201_functions_are_registered_callable_and_deterministic(self):
        entries = catalog()
        self.assertEqual(len(entries), 201)
        self.assertEqual(len({item['name'] for item in entries}), 201)
        for entry in entries:
            with self.subTest(name=entry['name']):
                info, values = calculate(entry['name'], ROWS)
                self.assertEqual(info['output_names'], list(values))
                self.assertTrue(all(len(series) == len(ROWS) for series in values.values()))
                self.assertEqual(values, calculate(entry['name'], ROWS)[1])
        self.assertTrue(all(value is None for value in calculate('ACOS', ROWS)[1]['real']))
        self.assertTrue(all(value is None for value in calculate('ASIN', ROWS)[1]['real']))
        self.assertIn(0, calculate('CDLHAMMER', ROWS)[1]['integer'])

    def test_parameter_and_current_ohlcv_source_validation(self):
        self.assertNotEqual(calculate('SMA', ROWS, price_sources={'price': 'open'})[1]['real'][-1],
                            calculate('SMA', ROWS)[1]['real'][-1])
        self.assertIsNotNone(calculate('MAVP', ROWS, periods_constant=14)[1]['real'][-1])
        self.assertEqual(
            calculate('BBANDS', ROWS, parameters={'timeperiod': 20, 'nbdevup': 2, 'nbdevdn': 2})[1],
            calculate('BBANDS', ROWS, parameters={'timeperiod': 20, 'nbdevup': 2.0, 'nbdevdn': 2.0})[1],
        )
        for kwargs in ({'parameters': {'code': 1}}, {'parameters': {'timeperiod': True}},
                       {'parameters': {'timeperiod': float('nan')}}, {'price_sources': {'price': 'outside'}},
                       {'price_sources': {'price0': 'close'}}, {'periods_constant': 15}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                calculate('SMA', ROWS, **kwargs)
        with self.assertRaisesRegex(ValueError, r"SMA price_sources keys must be \['price'\]"):
            calculate('SMA', ROWS, price_sources={'inReal': 'close'})
        with self.assertRaises(ValueError):
            calculate('MAVP', ROWS, periods_constant=40)
        with self.assertRaises(ValueError):
            calculate('SMA', ROWS * 17)

    def test_existing_indicator_maps_use_talib_values_and_warmup(self):
        time = ROWS[-1]['time']
        high = np.asarray([r['high'] for r in ROWS])
        low = np.asarray([r['low'] for r in ROWS])
        close = np.asarray([r['close'] for r in ROWS])
        volume = np.asarray([r['volume'] for r in ROWS])
        self.assertEqual(series_ma(ROWS, [20])['ma20'][time], round(float(talib.SMA(close, 20)[-1]), 6))
        self.assertEqual(series_boll(ROWS)['mid'][time], round(float(talib.BBANDS(close)[1][-1]), 6))
        self.assertEqual(series_rsi(ROWS)[time], round(float(talib.RSI(close, 14)[-1]), 4))
        self.assertEqual(series_atr(ROWS)[time], round(float(talib.ATR(high, low, close, 14)[-1]), 6))
        self.assertEqual(min(ROWS.index(row) for row in ROWS if row['time'] in series_atr(ROWS)), 14)
        macd = talib.MACD(close)
        self.assertEqual(series_macd(ROWS)['hist'][time], round(float(macd[2][-1]), 6))
        self.assertEqual(series_kdj(ROWS)['j'][time], round(float(talib.KDJ(high, low, close)[2][-1]), 4))
        self.assertEqual(series_vwap(ROWS)[time], round(float(talib.VWAP(high, low, close, volume)[-1]), 6))


class TalibChartToolsTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.GuardedEditTests('test_prepares_without_changing_source_context_or_other_shapes')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def run_case(self, name='SMA', **kwargs):
        with patch('chart_service.publish_chart', side_effect=AssertionError('read-only')):
            return run_ta(self.f.ref, self.f.record['revision'], self.f.token,
                          self.f.payload['symbol'], name, **kwargs)

    def read(self, result, output_name='real', **kwargs):
        return read_ta(self.f.ref, self.f.record['revision'], self.f.token,
                       self.f.payload['symbol'], result['result_ref'], output_name, **kwargs)

    def test_catalog_pages_and_mcp_tools(self):
        page = list_ta_catalog(group='Pattern Recognition', limit=10)
        self.assertEqual(page['engine_version'], ENGINE_VERSION)
        self.assertEqual(page['total_catalog'], 201)
        self.assertEqual(page['total_matches'], 61)
        self.assertEqual(len(page['functions']), 10)
        self.assertEqual(list_ta_catalog(query='SMA')['total_matches'], 1)
        tools = {item.name for item in asyncio.run(server.mcp.list_tools())}
        self.assertTrue({'list_ta_functions', 'run_ta_function', 'read_ta_result'} <= tools)

    def test_result_is_bound_paginated_deterministic_and_does_not_publish(self):
        original = deepcopy(self.f.payload)
        observation = self.f.path.read_bytes()
        result = self.run_case(parameters={'timeperiod': 2})
        self.assertEqual(result['result_ref'], self.run_case(parameters={'timeperiod': 2})['result_ref'])
        self.assertEqual(result['result_usage'], 'analysis_only')
        self.assertFalse(result['chart_modified'])
        self.assertEqual(self.f.payload, original)
        self.assertEqual(self.f.path.read_bytes(), observation)
        page = self.read(result, limit=2)
        self.assertEqual(len(page['items']), 2)
        self.assertIsNone(page['items'][0]['value'])
        self.assertIsNotNone(page['items'][1]['value'])
        with self.assertRaises(LineError) as error:
            self.read(result, output_name='not_an_output')
        self.assertEqual(error.exception.code, 'ta_output_unknown')
        for change in ('symbol', 'interval', 'adjust', 'rows', 'revision'):
            with self.subTest(change=change):
                original_record = deepcopy(self.f.record)
                if change == 'symbol': self.f.record['state']['symbol'] = 'OTHER.X'
                elif change == 'interval': self.f.record['state']['interval'] = 'week'
                elif change == 'adjust': self.f.record['state']['adjust'] = 'qfq'
                elif change == 'rows': self.f.record['state']['candles'][0]['volume'] += 1
                else: self.f.record['revision'] += 1
                self.f.save_context()
                with self.assertRaises(LineError): self.read(result)
                self.f.record = original_record; self.f.save_context()

    def test_no_finite_output_and_bad_parameters(self):
        result = self.run_case('ACOS')
        self.assertEqual(result['status'], 'no_finite_output')
        self.assertIsNone(result['summary']['real']['latest'])
        self.assertFalse(result['chart_modified'])
        for kwargs in ({'name': 'NOPE'}, {'parameters': {'code': 1}},
                       {'price_sources': {'price': 'volume'}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(LineError):
                self.run_case(**kwargs)

    def test_bounded_result_cache_does_not_block_seventeenth_function_call(self):
        first = self.run_case('SMA', parameters={'timeperiod': 2})
        latest = None
        for period in range(3, 19):
            latest = self.run_case('SMA', parameters={'timeperiod': period})
        self.assertIsNotNone(latest)
        self.assertEqual(self.read(latest)['result_ref'], latest['result_ref'])
        with self.assertRaises(LineError) as error:
            self.read(first)
        self.assertEqual(error.exception.code, 'ta_result_unavailable')
