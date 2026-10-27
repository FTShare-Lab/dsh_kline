import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError
import chart_service
import server
from tools.chart_edits import ChartEdit, snapshot_inventory
from tools.chart_functions import ChartFunctionParameters, list_functions, run_function, resolve_result
from tools.chart_context import read_chart_context
from tools.chart_applications import read_edit_status, request_chart_apply
from tools.drawing_feedback import sanitize_drawing_feedback
from tools.drawing_verification import verify_drawings
from tools.fibonacci import DEFAULT_RATIOS, edit_fibonacci, fibonacci_levels, validate_ratios
from tools.lines import LineError
from tools.ta_functions import run_ta
import test_chart_edits as fixtures
from ta_sample import sample_rows


class FibonacciTests(unittest.TestCase):
    def test_up_and_down_prices_match_independent_known_values(self):
        self.assertEqual(fibonacci_levels(100, 200, [0, .5, .618, 1]),
                         [{'ratio': 0, 'price': 200}, {'ratio': .5, 'price': 150},
                          {'ratio': .618, 'price': 138.2}, {'ratio': 1, 'price': 100}])
        self.assertEqual(fibonacci_levels(200, 100, [.618]), [{'ratio': .618, 'price': 161.8}])
        for ratios in ([], [1, 0], [.5, .5], [True], [-.1], [1.1], [float('nan')], list(range(17))):
            with self.subTest(ratios=ratios), self.assertRaises(LineError): validate_ratios(ratios)
        with self.assertRaises(LineError): fibonacci_levels(100, 100, [0, 1])


class ChartFunctionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.GuardedEditTests('test_prepares_without_changing_source_context_or_other_shapes')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.record['guarded_apply_supported'] = True; self.f.save_context()
        self.params = dict(start_time='2026-09-10', start_price=30, end_time='2026-09-15', end_price=40)

    def run_function(self, function='fibonacci_retracement', params=None, **changes):
        args = dict(context_ref=self.f.ref, expected_revision=self.f.record['revision'],
                    chart_session=self.f.token, symbol=self.f.payload['symbol'], function=function,
                    parameters=ChartFunctionParameters(**(self.params if params is None else params)))
        args.update(changes)
        with patch('server.fetch_candles', side_effect=AssertionError('no fetch')), \
             patch('chart_service.publish_chart', side_effect=AssertionError('calculation must not publish')):
            return run_function(**args)

    def context(self): return read_chart_context(self.f.ref, candle_scope='loaded', limit=4000)

    def install_frozen_250_bars(self):
        rows = sample_rows()
        self.assertEqual(len(rows), 250)
        self.f.payload['chartCommands'][0]['rows'] = deepcopy(rows)
        self.f.record['state']['candles'] = deepcopy(rows)
        self.f.record['state']['visible_range'] = {
            'available': True, 'index_from': 99, 'index_to_exclusive': 250}
        self.f.save_snapshot(self.f.token, self.f.payload)
        self.f.save_context()
        return rows

    def adopt(self, prepared):
        """A simulated broker receipt, not a real browser acceptance."""
        path = self.f.runtime / 'edits' / '4242' / self.f.ref / 'applications' / (prepared['chart_session'] + '.json')
        request_chart_apply(self.f.ref, prepared['chart_session'])
        app = json.loads(path.read_text()); app.update(status='applied', confirmed_chart_session=prepared['chart_session'])
        chart_service._atomic_runtime_json(path, app)
        self.f.payload = chart_service.read_chart_snapshot(prepared['chart_session'])
        self.f.token = prepared['chart_session']
        self.f.record['revision'] += 1
        self.f.record['state'].update(source_chart_session=self.f.token, drawings=snapshot_inventory(self.f.payload))
        self.f.save_context()

    def test_catalog_and_mcp_schemas_are_additive_and_do_not_execute(self):
        catalog = list_functions()
        self.assertEqual([f['name'] for f in catalog['functions']],
                         ['fibonacci_retracement', 'parallel_channel', 'range_box', 'labeled_polyline',
                          'pivot_candidates', 'regression_channel', 'channel_candidates', 'range_candidates',
                          'price_series_line', 'conditional_annotation', 'price_band', 'price_sticks'])
        pivot = next(f for f in catalog['functions'] if f['name'] == 'pivot_candidates')
        self.assertIsNone(pivot['drawing_kind']); self.assertEqual(pivot['result_usage'], 'analysis_only')
        self.assertEqual(pivot['defaults']['right_bars'], 2)
        self.assertTrue(pivot['limits']['requires_complete_right_window'])
        regression = next(f for f in catalog['functions'] if f['name'] == 'regression_channel')
        self.assertIsNone(regression['drawing_kind']); self.assertEqual(regression['result_usage'], 'analysis_only')
        self.assertEqual(regression['defaults']['multiplier'], 2.0)
        self.assertEqual(regression['limits']['minimum_range_bars'], 10)
        channel_candidates = next(f for f in catalog['functions'] if f['name'] == 'channel_candidates')
        self.assertIsNone(channel_candidates['drawing_kind'])
        self.assertEqual(channel_candidates['result_usage'], 'analysis_only')
        self.assertEqual(channel_candidates['version'], '3')
        self.assertEqual(channel_candidates['defaults']['scope'], 'current')
        self.assertEqual(channel_candidates['defaults']['max_candidates'], 3)
        self.assertTrue(channel_candidates['limits']['requires_human_review'])
        range_candidates = next(f for f in catalog['functions'] if f['name'] == 'range_candidates')
        self.assertIsNone(range_candidates['drawing_kind'])
        self.assertEqual(range_candidates['result_usage'], 'analysis_only')
        self.assertEqual(range_candidates['defaults']['window_sizes'], [20, 30, 40, 60])
        self.assertTrue(range_candidates['limits']['requires_human_review'])
        series = next(f for f in catalog['functions'] if f['name'] == 'price_series_line')
        self.assertEqual(series['drawing_kind'], 'series_line')
        self.assertEqual(series['limits']['maximum_series_objects'], 8)
        annotation = next(f for f in catalog['functions'] if f['name'] == 'conditional_annotation')
        self.assertEqual(annotation['limits']['selection'], 'latest_matched_loaded_bar_only')
        band = next(f for f in catalog['functions'] if f['name'] == 'price_band')
        self.assertEqual(band['drawing_kind'], 'price_band')
        self.assertEqual(band['limits']['maximum_band_objects'], 4)
        sticks = next(f for f in catalog['functions'] if f['name'] == 'price_sticks')
        self.assertEqual(sticks['drawing_kind'], 'price_sticks')
        self.assertEqual(sticks['limits']['maximum_stick_objects'], 4)
        self.assertEqual(catalog['functions'][0]['version'], '1')
        self.assertEqual(catalog['functions'][0]['defaults']['ratios'], DEFAULT_RATIOS)
        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
        self.assertEqual(len(tools), 41)
        self.assertTrue({'list_ta_functions', 'run_ta_function', 'read_ta_result'} <= set(tools))
        self.assertIn('parameters', tools['run_chart_function'].inputSchema['properties'])
        self.assertIn('pivot_candidates', tools['run_chart_function'].inputSchema['properties']['function']['enum'])
        self.assertIn('regression_channel', tools['run_chart_function'].inputSchema['properties']['function']['enum'])
        self.assertIn('channel_candidates', tools['run_chart_function'].inputSchema['properties']['function']['enum'])
        self.assertIn('range_candidates', tools['run_chart_function'].inputSchema['properties']['function']['enum'])
        self.assertIn('price_series_line', tools['run_chart_function'].inputSchema['properties']['function']['enum'])
        self.assertIn('conditional_annotation', tools['run_chart_function'].inputSchema['properties']['function']['enum'])
        self.assertIn('price_band', tools['run_chart_function'].inputSchema['properties']['function']['enum'])
        self.assertIn('price_sticks', tools['run_chart_function'].inputSchema['properties']['function']['enum'])
        response = asyncio.run(server.list_chart_functions())
        self.assertEqual(response.structuredContent, catalog)
        self.assertEqual(json.loads(response.content[0].text.split(' · ', 1)[1]), catalog)
        for values in ({'price_scale': 'log'}, {'start_price': True}, {'ratios': [False]}, {'code': 'anything'}):
            with self.subTest(values=values), self.assertRaises(ValidationError): ChartFunctionParameters(**values)

    def test_pivot_candidates_are_deterministic_bounded_and_read_only(self):
        from datetime import datetime, timezone
        highs = [3, 4, 7, 5, 6, 6, 4, 8, 5, 4, 3]
        lows = [2, 3, 4, 2, 3, 1, 3, 4, 2, 3, 2]
        rows = [{"time": 1790000000 + i * 86400, "open": 3, "high": float(h), "low": float(l),
                 "close": 3, "volume": 1} for i, (h, l) in enumerate(zip(highs, lows))]
        self.f.record['state']['candles'] = deepcopy(rows); self.f.save_context()
        self.f.payload['chartCommands'][0]['rows'] = deepcopy(rows)
        self.f.payload['count'] = len(rows); self.f.save_snapshot(self.f.token, self.f.payload)
        before_context = self.f.path.read_bytes(); before_snapshot = deepcopy(self.f.payload)
        parameters = ChartFunctionParameters(left_bars=2, right_bars=2, mode='both', limit=10)
        args = dict(context_ref=self.f.ref, expected_revision=1, chart_session=self.f.token,
                    symbol=self.f.payload['symbol'], function='pivot_candidates', parameters=parameters)
        with patch('server.fetch_candles', side_effect=AssertionError('no market fetch')), \
             patch('chart_service.publish_chart', side_effect=AssertionError('analysis must not publish')):
            first = run_function(**args); second = run_function(**args)
        self.assertEqual(first['result_ref'], second['result_ref'])
        self.assertEqual(first['kind'], 'pivot_candidates'); self.assertFalse(first['chart_modified'])
        self.assertEqual(first['summary']['candidates'], [
            {'side': 'high', 'time': str(rows[2]['time']), 'price': 7.0, 'bars_ago': 8},
            {'side': 'low', 'time': str(rows[5]['time']), 'price': 1.0, 'bars_ago': 5},
            {'side': 'high', 'time': str(rows[7]['time']), 'price': 8.0, 'bars_ago': 3},
        ])
        self.assertEqual(first['summary']['rule'], 'strict_local_extremum')
        self.assertEqual(first['summary']['tie_policy'], 'equal_neighbor_is_not_a_pivot')
        self.assertEqual(first['summary']['confirmation'], 'complete_right_window_only')
        self.assertEqual(self.f.path.read_bytes(), before_context)
        self.assertEqual(self.f.payload, before_snapshot); self.assertEqual(self.f.published, [])
        with self.assertRaises(ValidationError): ChartFunctionParameters(left_bars=True)

    def test_regression_channel_function_is_bound_readonly_and_analysis_only(self):
        from datetime import date, datetime, timedelta, timezone
        rows = []
        first_day = date(2026, 9, 1)
        residuals = [-.2, .2, 0, 0, 0, 0, 0, 0, 0, 0, .2, -.2]
        for index in range(12):
            close = 20 + index * .5 + residuals[index]
            bar_day = first_day + timedelta(days=index)
            stamp = int(datetime.combine(bar_day, datetime.min.time(), timezone(timedelta(hours=8))).timestamp())
            rows.append({'time': stamp, 'open': close, 'high': close + .5, 'low': close - .5,
                         'close': close, 'volume': 100})
        self.f.payload['chartCommands'][0]['rows'] = deepcopy(rows)
        self.f.payload['count'] = len(rows)
        self.f.record['state']['candles'] = deepcopy(rows)
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        before = deepcopy(self.f.payload)
        parameters = ChartFunctionParameters(start_time='2026-09-01', end_time='2026-09-12', multiplier=2)
        args = dict(context_ref=self.f.ref, expected_revision=1, chart_session=self.f.token,
                    symbol=self.f.payload['symbol'], function='regression_channel', parameters=parameters)
        with patch('server.fetch_candles', side_effect=AssertionError('no market fetch')), \
             patch('chart_service.publish_chart', side_effect=AssertionError('analysis must not publish')):
            result = run_function(**args)
            repeated = run_function(**args)
        self.assertEqual(result['result_ref'], repeated['result_ref'])
        self.assertEqual(result['result_usage'], 'analysis_only')
        self.assertEqual(result['kind'], 'regression_channel')
        self.assertEqual(result['summary']['bar_count'], 12)
        self.assertEqual(result['summary']['price_source'], 'close')
        self.assertEqual(result['summary']['boundary_rule'],
                         'ols_close_plus_minus_multiplier_times_population_rms_residual')
        self.assertAlmostEqual(result['summary']['slope_per_bar'], .5, places=12)
        self.assertEqual(result['parameters'], {'start_time': str(rows[0]['time']),
                                                'end_time': str(rows[-1]['time']), 'multiplier': 2.0})
        self.assertFalse(result['chart_modified'])
        self.assertEqual(self.f.payload, before)
        self.f.assert_code('chart_function_result_not_drawable',
                           lambda: resolve_result(result['result_ref'], self.context(), 'regression_channel'))
        for values in ({'multiplier': True}, {'multiplier': 5.1}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ChartFunctionParameters(**values)

    def test_channel_candidates_function_is_reproducible_and_cannot_apply(self):
        from test_channel_candidates import trend_rows
        rows = trend_rows('ascending')
        for index, row in enumerate(rows):
            row['time'] = 1790000000 + index * 86400
        self.f.payload['chartCommands'][0]['rows'] = deepcopy(rows)
        self.f.payload['count'] = len(rows)
        self.f.record['state']['candles'] = deepcopy(rows)
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        before_context = self.f.path.read_bytes(); before_snapshot = deepcopy(self.f.payload)
        parameters = ChartFunctionParameters(direction='ascending', max_candidates=2)
        args = dict(context_ref=self.f.ref, expected_revision=1, chart_session=self.f.token,
                    symbol=self.f.payload['symbol'], function='channel_candidates', parameters=parameters)
        with patch('server.fetch_candles', side_effect=AssertionError('no market fetch')), \
             patch('chart_service.publish_chart', side_effect=AssertionError('analysis must not publish')):
            first = run_function(**args); second = run_function(**args)
        self.assertEqual(first['result_ref'], second['result_ref'])
        self.assertEqual(first['result_usage'], 'analysis_only')
        self.assertEqual(first['function_version'], '3')
        self.assertEqual(first['kind'], 'channel_candidates')
        self.assertEqual(first['summary']['returned'], 2)
        self.assertTrue(all(item['direction'] == 'ascending' for item in first['summary']['candidates']))
        self.assertFalse(first['chart_modified'])
        self.assertEqual(self.f.path.read_bytes(), before_context)
        self.assertEqual(self.f.payload, before_snapshot)
        self.assertEqual(self.f.published, [])
        self.f.assert_code('chart_function_result_not_drawable',
                           lambda: resolve_result(first['result_ref'], self.context(), 'channel_candidates'))
        for values in ({'lookback_bars': True}, {'max_candidates': 6}, {'direction': 'up'}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ChartFunctionParameters(**values)

    def test_range_candidates_function_is_reproducible_and_cannot_apply(self):
        from test_range_candidates import sideways_rows
        rows = sideways_rows()
        for index, row in enumerate(rows):
            row['time'] = 1790000000 + index * 86400
        self.f.payload['chartCommands'][0]['rows'] = deepcopy(rows)
        self.f.payload['count'] = len(rows)
        self.f.record['state']['candles'] = deepcopy(rows)
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        before_context = self.f.path.read_bytes(); before_snapshot = deepcopy(self.f.payload)
        parameters = ChartFunctionParameters(window_sizes=[20, 30], max_candidates=2)
        args = dict(context_ref=self.f.ref, expected_revision=1, chart_session=self.f.token,
                    symbol=self.f.payload['symbol'], function='range_candidates', parameters=parameters)
        with patch('server.fetch_candles', side_effect=AssertionError('no market fetch')), \
             patch('chart_service.publish_chart', side_effect=AssertionError('analysis must not publish')):
            first = run_function(**args); second = run_function(**args)
        self.assertEqual(first['result_ref'], second['result_ref'])
        self.assertEqual(first['result_usage'], 'analysis_only')
        self.assertEqual(first['kind'], 'range_candidates')
        self.assertEqual(first['parameters']['window_sizes'], [20, 30])
        self.assertEqual(first['summary']['returned'], 1)
        self.assertEqual(first['summary']['duplicates_suppressed'], 1)
        self.assertFalse(first['chart_modified'])
        self.assertEqual(self.f.path.read_bytes(), before_context)
        self.assertEqual(self.f.payload, before_snapshot)
        self.assertEqual(self.f.published, [])
        self.f.assert_code('chart_function_result_not_drawable',
                           lambda: resolve_result(first['result_ref'], self.context(), 'range_candidates'))
        for values in ({'window_sizes': [True]}, {'window_sizes': [15]}, {'max_candidates': 6}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ChartFunctionParameters(**values)

    def test_price_series_result_is_private_bound_and_guardedly_editable(self):
        params = {'value_source': {'kind': 'close'}, 'condition': {
            'left': {'kind': 'close'}, 'op': 'gte', 'right': {'constant': 32}}}
        before = deepcopy(self.f.payload)
        result = self.run_function('price_series_line', params)
        self.assertEqual(result['result_ref'], self.run_function('price_series_line', params)['result_ref'])
        self.assertEqual(result['kind'], 'series_line')
        self.assertEqual(result['summary']['matched_bars'], 4)
        self.assertFalse(result['chart_modified'])
        self.assertNotIn('render_values', result)
        self.assertEqual(self.f.payload, before)
        prepared = self.f.prepare(ChartEdit(kind='series_line', action='create', result_ref=result['result_ref'],
                                             name='条件收盘线', color='warning'))
        line = prepared['object']
        self.assertEqual(line['bar_count'], 4)
        self.assertEqual(line['valid_bars'], 4)
        self.assertNotIn('values', line)
        self.assertEqual(self.f.published[0]['chartCommands'][-1]['values'], [32.0] * 4)
        self.assertEqual(self.f.published[0]['chartCommands'][:-1], before['chartCommands'])
        self.adopt(prepared)
        recalculated = self.run_function('price_series_line', {'value_source': {'kind': 'sma', 'period': 2},
            'condition': {'left': {'kind': 'close'}, 'op': 'gt', 'right': {'constant': 31}}})
        edited = self.f.prepare(ChartEdit(kind='series_line', action='update', object_id=line['id'],
            result_ref=recalculated['result_ref']), expected_revision=2, request_id='recalculate')
        self.assertEqual(edited['object']['id'], line['id'])
        self.assertNotEqual(edited['object']['series_hash'], line['series_hash'])
        self.assertEqual(edited['object']['valid_bars'], 3)
        self.assertNotIn('values', edited['object'])
        self.assertEqual(self.f.published[-1]['chartCommands'][-1]['values'], [None, 32.0, 32.0, 32.0])
        self.adopt(edited)
        changed = self.f.prepare(ChartEdit(kind='series_line', action='update', object_id=line['id'],
                                           color='success'), expected_revision=3, request_id='color')
        self.assertEqual(changed['object']['id'], line['id'])
        self.assertEqual(changed['object']['series_hash'], edited['object']['series_hash'])
        self.assertEqual(changed['object']['color'], 'success')
        self.adopt(changed)
        removed = self.f.prepare(ChartEdit(kind='series_line', action='delete', object_id=line['id']),
                                 expected_revision=4, request_id='delete')
        self.assertEqual(removed['object']['id'], line['id'])
        self.assertEqual(self.f.published[-1]['chartCommands'], before['chartCommands'])
        self.f.assert_code('chart_function_result_mismatch',
            lambda: resolve_result(result['result_ref'], {**self.context(), 'symbol': 'OTHER.X'}, 'series_line'))

    def test_empty_price_series_cannot_prepare_a_drawing(self):
        result = self.run_function('price_series_line', {'value_source': {'kind': 'close'},
            'condition': {'left': {'kind': 'close'}, 'op': 'gt', 'right': {'constant': 1000}}})
        self.assertTrue(result['summary']['empty'])
        self.f.assert_code('empty_price_series', lambda: self.f.prepare(
            ChartEdit(kind='series_line', action='create', result_ref=result['result_ref'])))
        self.assertEqual(self.f.published, [])

    def test_selected_ta_sma_uses_guarded_series_lifecycle(self):
        original = deepcopy(self.f.payload)
        first = run_ta(self.f.ref, 1, self.f.token, self.f.payload['symbol'], 'SMA',
                       parameters={'timeperiod': 2})
        self.assertEqual(first['result_usage'], 'analysis_only')
        self.assertFalse(first['chart_modified'])
        self.assertEqual(first['selectable_render_targets'], [{'kind': 'series_line', 'output_name': 'real'}])
        self.assertEqual(self.f.payload, original)
        prepared = self.f.prepare(ChartEdit(kind='series_line', action='create',
            ta_result_ref=first['result_ref'], name='TA SMA2', color='warning'))
        created = prepared['object']
        self.assertEqual(created['source'], {'kind': 'sma', 'period': 2})
        self.assertNotIn('values', created)
        self.assertRegex(prepared['drawing_guard']['parameters']['digest_sha256'], r'^[a-f0-9]{64}$')
        self.assertNotIn('values', json.dumps(prepared))
        self.assertEqual(read_edit_status(self.f.ref, prepared['chart_session'])['apply_status'], 'not_requested')
        self.assertEqual(self.f.published[-1]['chartCommands'][-1]['values'][0], None)
        self.assertEqual(created['bar_count'], 4)
        self.assertEqual(self.f.published[0]['chartCommands'][:-1], original['chartCommands'])
        self.adopt(prepared)
        second = run_ta(self.f.ref, 2, self.f.token, self.f.payload['symbol'], 'SMA',
                        parameters={'timeperiod': 3})
        updated = self.f.prepare(ChartEdit(kind='series_line', action='update', object_id=created['id'],
            ta_result_ref=second['result_ref']), expected_revision=2, request_id='new-period')
        self.assertEqual(updated['object']['id'], created['id'])
        self.assertEqual(updated['object']['source'], {'kind': 'sma', 'period': 3})
        self.assertNotIn('values', updated['object'])
        self.assertEqual(self.f.published[-1]['chartCommands'][-1]['values'][:2], [None, None])
        self.adopt(updated)
        recolored = self.f.prepare(ChartEdit(kind='series_line', action='update', object_id=created['id'],
            color='success'), expected_revision=3, request_id='recolor')
        self.assertEqual(recolored['object']['id'], created['id'])
        self.assertEqual(recolored['object']['series_hash'], updated['object']['series_hash'])
        self.adopt(recolored)
        deleted = self.f.prepare(ChartEdit(kind='series_line', action='delete', object_id=created['id']),
                                 expected_revision=4, request_id='remove')
        self.assertEqual(deleted['object']['id'], created['id'])
        self.assertEqual(self.f.published[-1]['chartCommands'], original['chartCommands'])

    def test_ta_selection_rejects_wrong_function_source_and_stale_ref(self):
        args = (self.f.ref, 1, self.f.token, self.f.payload['symbol'])
        wma = run_ta(*args, 'WMA', parameters={'timeperiod': 2})
        opened = run_ta(*args, 'SMA', parameters={'timeperiod': 2}, price_sources={'price': 'open'})
        empty = run_ta(*args, 'SMA', parameters={'timeperiod': 5})
        self.assertEqual(empty['status'], 'no_finite_output')
        for result in (wma, opened, empty):
            self.assertEqual(result['selectable_render_targets'], [])
            self.f.assert_code('ta_result_not_drawable', lambda result=result: self.f.prepare(
                ChartEdit(kind='series_line', action='create', ta_result_ref=result['result_ref'])))
        self.f.assert_code('ta_result_not_drawable', lambda: self.f.prepare(
            ChartEdit(kind='rectangle', action='create', ta_result_ref=wma['result_ref'])))
        self.f.assert_code('conflicting_function_parameters', lambda: self.f.prepare(
            ChartEdit(kind='series_line', action='create', result_ref=wma['result_ref'],
                      ta_result_ref=wma['result_ref'])))
        self.assertEqual(self.f.published, [])
        sma = run_ta(*args, 'SMA', parameters={'timeperiod': 2})
        self.f.record['revision'] = 2; self.f.save_context()
        self.f.assert_code('ta_result_mismatch', lambda: self.f.prepare(
            ChartEdit(kind='series_line', action='create', ta_result_ref=sma['result_ref']),
            expected_revision=2, request_id='stale'))
        self.assertEqual(self.f.published, [])

    def test_250_bar_sma_prepare_returns_only_digest_not_prices(self):
        self.install_frozen_250_bars()
        calculated = run_ta(self.f.ref, 1, self.f.token, self.f.payload['symbol'], 'SMA',
                            parameters={'timeperiod': 17})
        prepared = self.f.prepare(ChartEdit(kind='series_line', action='create',
            ta_result_ref=calculated['result_ref'], name='TA SMA17', color='warning'))
        self.assertEqual(prepared['object']['bar_count'], 250)
        self.assertEqual(prepared['object']['valid_bars'], 234)
        self.assertEqual(set(prepared['drawing_guard']['parameters']), {'digest_sha256'})
        self.assertNotIn('values', json.dumps(prepared))
        self.assertLess(len(json.dumps(prepared)), 4000)
        self.assertEqual(len(self.f.published[0]['chartCommands'][-1]['values']), 250)
        self.assertEqual(read_edit_status(self.f.ref, prepared['chart_session'])['apply_status'], 'not_requested')

    def test_250_bar_band_prepare_returns_only_digest_not_prices(self):
        self.install_frozen_250_bars()
        calculated = self.run_function('price_band', {
            'upper_source': {'kind': 'high'}, 'lower_source': {'kind': 'low'}})
        prepared = self.f.prepare(ChartEdit(kind='price_band', action='create',
            result_ref=calculated['result_ref'], name='高低价带', color='warning'))
        self.assertEqual(prepared['object']['bar_count'], 250)
        self.assertEqual(prepared['object']['valid_bars'], 250)
        self.assertEqual(set(prepared['drawing_guard']['parameters']), {'digest_sha256'})
        self.assertNotIn('upper_values', json.dumps(prepared))
        self.assertNotIn('lower_values', json.dumps(prepared))
        self.assertLess(len(json.dumps(prepared)), 4000)
        self.assertEqual(len(self.f.published[0]['chartCommands'][-1]['upper_values']), 250)
        self.assertEqual(read_edit_status(self.f.ref, prepared['chart_session'])['apply_status'], 'not_requested')

    def test_250_bar_sticks_prepare_returns_only_digest_not_prices(self):
        self.install_frozen_250_bars()
        calculated = self.run_function('price_sticks', {
            'start_source': {'kind': 'high'}, 'end_source': {'kind': 'low'}})
        prepared = self.f.prepare(ChartEdit(kind='price_sticks', action='create',
            result_ref=calculated['result_ref'], name='高低柱线', color='warning'))
        self.assertEqual(prepared['object']['bar_count'], 250)
        self.assertEqual(prepared['object']['valid_bars'], 250)
        self.assertEqual(set(prepared['drawing_guard']['parameters']), {'digest_sha256'})
        self.assertNotIn('start_values', json.dumps(prepared))
        self.assertNotIn('end_values', json.dumps(prepared))
        self.assertLess(len(json.dumps(prepared)), 4000)
        self.assertEqual(len(self.f.published[0]['chartCommands'][-1]['start_values']), 250)
        self.assertEqual(read_edit_status(self.f.ref, prepared['chart_session'])['apply_status'], 'not_requested')

    def test_ta_ema_selected_line_keeps_one_id_through_recalculation_and_delete(self):
        self.install_frozen_250_bars()
        args = (self.f.ref, 1, self.f.token, self.f.payload['symbol'])
        first = run_ta(*args, 'EMA', parameters={'timeperiod': 17})
        self.assertEqual(first['selectable_render_targets'], [{'kind': 'series_line', 'output_name': 'real'}])
        self.assertEqual(first['summary']['real']['first_valid']['index'], 16)
        created = self.f.prepare(ChartEdit(kind='series_line', action='create',
            ta_result_ref=first['result_ref'], name='TA EMA17', color='warning'))
        obj = created['object']
        self.assertEqual(obj['source'], {'kind': 'ema', 'period': 17})
        self.assertEqual(obj['valid_bars'], 234)
        self.assertNotIn('values', json.dumps(created))
        self.assertEqual(self.f.published[-1]['chartCommands'][-1]['values'][-1],
                         first['summary']['real']['latest']['value'])
        self.adopt(created)
        second = run_ta(self.f.ref, 2, self.f.token, self.f.payload['symbol'], 'EMA',
                        parameters={'timeperiod': 20})
        changed = self.f.prepare(ChartEdit(kind='series_line', action='update', object_id=obj['id'],
            ta_result_ref=second['result_ref']), expected_revision=2, request_id='ema-period')
        self.assertEqual(changed['object']['id'], obj['id'])
        self.assertNotEqual(changed['object']['series_hash'], obj['series_hash'])
        self.assertEqual(changed['object']['source'], {'kind': 'ema', 'period': 20})
        self.adopt(changed)
        deleted = self.f.prepare(ChartEdit(kind='series_line', action='delete', object_id=obj['id']),
                                 expected_revision=3, request_id='ema-delete')
        self.assertEqual(deleted['object']['id'], obj['id'])
        self.assertFalse(any(c.get('type') == 'DRAW_AGENT_SERIES_LINE' for c in self.f.published[-1]['chartCommands']))

    def test_ta_bbands_selected_as_one_three_line_band_with_stable_id(self):
        self.install_frozen_250_bars()
        args = (self.f.ref, 1, self.f.token, self.f.payload['symbol'])
        first = run_ta(*args, 'BBANDS', parameters={'timeperiod': 20})
        self.assertEqual(first['selectable_render_targets'], [
            {'kind': 'price_band', 'output_names': ['upperband', 'middleband', 'lowerband']}])
        self.assertEqual(first['summary']['middleband']['first_valid']['index'], 19)
        created = self.f.prepare(ChartEdit(kind='price_band', action='create',
            ta_result_ref=first['result_ref'], name='TA BOLL20', color='warning'))
        obj = created['object']
        self.assertEqual(obj['valid_bars'], 231)
        self.assertEqual(obj['upper_source']['kind'], 'bbands')
        self.assertNotIn('middle_values', json.dumps(created))
        self.assertNotIn('upper_values', json.dumps(created))
        self.assertEqual(set(created['drawing_guard']['parameters']), {'digest_sha256'})
        candidate = self.f.published[-1]['chartCommands'][-1]
        self.assertEqual(len(candidate['upper_values']), 250)
        self.assertEqual(len(candidate['middle_values']), 250)
        self.assertEqual(len(candidate['lower_values']), 250)
        self.assertEqual(candidate['middle_values'][-1], first['summary']['middleband']['latest']['value'])
        self.assertEqual(read_edit_status(self.f.ref, created['chart_session'])['apply_status'], 'not_requested')
        self.adopt(created)
        second = run_ta(self.f.ref, 2, self.f.token, self.f.payload['symbol'], 'BBANDS',
                        parameters={'timeperiod': 10})
        changed = self.f.prepare(ChartEdit(kind='price_band', action='update', object_id=obj['id'],
            ta_result_ref=second['result_ref']), expected_revision=2, request_id='boll-period')
        self.assertEqual(changed['object']['id'], obj['id'])
        self.assertNotEqual(changed['object']['band_hash'], obj['band_hash'])
        self.adopt(changed)
        recolored = self.f.prepare(ChartEdit(kind='price_band', action='update', object_id=obj['id'],
            color='success'), expected_revision=3, request_id='boll-color')
        self.assertEqual(recolored['object']['id'], obj['id'])
        self.assertEqual(recolored['object']['band_hash'], changed['object']['band_hash'])
        self.adopt(recolored)
        deleted = self.f.prepare(ChartEdit(kind='price_band', action='delete', object_id=obj['id']),
                                 expected_revision=4, request_id='boll-delete')
        self.assertEqual(deleted['object']['id'], obj['id'])
        self.assertFalse(any(c.get('type') == 'DRAW_AGENT_PRICE_BAND' for c in self.f.published[-1]['chartCommands']))

    def test_ta_bbands_rejects_nonprice_or_unapproved_parameters(self):
        self.install_frozen_250_bars()
        args = (self.f.ref, 1, self.f.token, self.f.payload['symbol'])
        for kwargs in ({'parameters': {'timeperiod': 20, 'matype': 1}},
                       {'parameters': {'timeperiod': 20}, 'price_sources': {'price': 'open'}}):
            with self.subTest(kwargs=kwargs):
                result = run_ta(*args, 'BBANDS', **kwargs)
                self.assertEqual(result['selectable_render_targets'], [])
                self.f.assert_code('ta_result_not_drawable', lambda result=result: self.f.prepare(
                    ChartEdit(kind='price_band', action='create', ta_result_ref=result['result_ref'])))
        self.assertEqual(self.f.published, [])

    def test_conditional_annotation_uses_latest_match_and_existing_guarded_editor(self):
        condition = {'left': {'kind': 'close'}, 'op': 'gt', 'right': {'constant': 31}}
        params = {'annotation_kind': 'text_annotation', 'anchor_source': {'kind': 'high'},
                  'condition': condition, 'annotation_text': '收盘高于31'}
        result = self.run_function('conditional_annotation', params)
        self.assertEqual(result['kind'], 'text_annotation')
        self.assertEqual(result['summary']['matched_bars'], 4)
        self.assertEqual(result['summary']['bars_ago'], 0)
        self.assertFalse(result['chart_modified'])
        self.assertEqual(self.f.published, [])
        before = deepcopy(self.f.payload)
        created = self.f.prepare(ChartEdit(kind='text_annotation', action='create', result_ref=result['result_ref']))
        self.assertEqual(created['object']['price'], 36)
        self.assertEqual(created['object']['time'], before['chartCommands'][0]['rows'][-1]['time'])
        self.assertEqual(created['object']['text'], '收盘高于31')
        self.assertEqual(self.f.published[0]['chartCommands'][:-1], before['chartCommands'])
        self.adopt(created)
        revised = self.run_function('conditional_annotation', {**params, 'anchor_source': {'kind': 'low'},
            'annotation_text': '条件仍成立'})
        updated = self.f.prepare(ChartEdit(kind='text_annotation', action='update',
            object_id=created['object']['id'], result_ref=revised['result_ref']),
            expected_revision=2, request_id='mark-update')
        self.assertEqual(updated['object']['id'], created['object']['id'])
        self.assertEqual(updated['object']['text'], '条件仍成立')
        self.assertEqual(updated['object']['price'], 28)
        self.assertEqual(self.f.published[-1]['chartCommands'][:-1], before['chartCommands'])
        self.adopt(updated)
        deleted = self.f.prepare(ChartEdit(kind='text_annotation', action='delete',
            object_id=created['object']['id']), expected_revision=3, request_id='mark-delete')
        self.assertEqual(self.f.published[-1]['chartCommands'], before['chartCommands'])

    def test_conditional_annotation_supports_number_icon_and_safe_empty_result(self):
        base = {'anchor_source': {'kind': 'low'},
                'condition': {'left': {'kind': 'close'}, 'op': 'gte', 'right': {'constant': 32}}}
        for kind, content in [('number_annotation', {'annotation_value': 0.618}),
                              ('icon_annotation', {'annotation_icon': 'diamond'})]:
            result = self.run_function('conditional_annotation', {**base, 'annotation_kind': kind, **content})
            self.assertEqual(result['kind'], kind)
            params = resolve_result(result['result_ref'], self.context(), kind)
            self.assertEqual(params['anchor_price'], 28)
            self.assertEqual(params['anchor_time'], str(self.f.payload['chartCommands'][0]['rows'][-1]['time']))
        empty = self.run_function('conditional_annotation', {**base, 'annotation_kind': 'icon_annotation',
            'annotation_icon': 'arrow_up',
            'condition': {'left': {'kind': 'close'}, 'op': 'gt', 'right': {'constant': 100}}})
        self.assertTrue(empty['summary']['empty'])
        self.f.assert_code('no_conditional_match', lambda: self.f.prepare(
            ChartEdit(kind='icon_annotation', action='create', result_ref=empty['result_ref'])))
        self.f.assert_code('invalid_conditional_annotation_content', lambda: self.run_function(
            'conditional_annotation', {**base, 'annotation_kind': 'icon_annotation',
                'annotation_icon': 'diamond', 'annotation_text': 'wrong'}))
        self.f.assert_code('invalid_annotation_text', lambda: self.run_function(
            'conditional_annotation', {**base, 'annotation_kind': 'text_annotation',
                'annotation_text': '  ',
                'condition': {'left': {'kind': 'close'}, 'op': 'gt', 'right': {'constant': 100}}}))

    def test_conditional_annotation_does_not_assume_latest_bar_matches(self):
        self.f.payload['chartCommands'][0]['rows'][-1]['close'] = 30
        self.f.record['state']['candles'][-1]['close'] = 30
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        result = self.run_function('conditional_annotation', {
            'annotation_kind': 'icon_annotation', 'annotation_icon': 'arrow_up',
            'anchor_source': {'kind': 'low'},
            'condition': {'left': {'kind': 'close'}, 'op': 'gt', 'right': {'constant': 31}}})
        self.assertEqual(result['summary']['matched_bars'], 3)
        self.assertEqual(result['summary']['bars_ago'], 1)
        self.assertEqual(result['summary']['selected_time'],
                         str(self.f.payload['chartCommands'][0]['rows'][-2]['time']))

    def test_price_band_result_is_private_bound_and_guardedly_editable(self):
        params = {'upper_source': {'kind': 'high'}, 'lower_source': {'kind': 'low'}}
        before = deepcopy(self.f.payload)
        result = self.run_function('price_band', params)
        self.assertEqual(result['result_ref'], self.run_function('price_band', params)['result_ref'])
        self.assertEqual(result['kind'], 'price_band')
        self.assertEqual(result['summary']['matched_bars'], 4)
        self.assertNotIn('render_upper_values', result)
        created = self.f.prepare(ChartEdit(kind='price_band', action='create', result_ref=result['result_ref'],
            name='高低价带', color='warning'))
        band = created['object']
        self.assertEqual(band['valid_bars'], 4)
        self.assertEqual(set(created['drawing_guard']['parameters']), {'digest_sha256'})
        self.assertNotIn('upper_values', json.dumps(created))
        self.assertEqual(self.f.published[0]['chartCommands'][-1]['upper_values'], [36.0] * 4)
        self.assertEqual(self.f.published[0]['chartCommands'][-1]['lower_values'], [28.0] * 4)
        self.assertEqual(self.f.published[0]['chartCommands'][:-1], before['chartCommands'])
        self.adopt(created)
        recalculated = self.run_function('price_band', {'upper_source': {'kind': 'high'},
            'lower_source': {'kind': 'sma', 'period': 2}})
        changed = self.f.prepare(ChartEdit(kind='price_band', action='update', object_id=band['id'],
            result_ref=recalculated['result_ref']), expected_revision=2, request_id='band-recalc')
        self.assertEqual(changed['object']['id'], band['id'])
        self.assertNotEqual(changed['object']['band_hash'], band['band_hash'])
        self.assertEqual(self.f.published[-1]['chartCommands'][-1]['upper_values'][0], None)
        self.adopt(changed)
        removed = self.f.prepare(ChartEdit(kind='price_band', action='delete', object_id=band['id']),
            expected_revision=3, request_id='band-delete')
        self.assertEqual(self.f.published[-1]['chartCommands'], before['chartCommands'])

    def test_price_band_zero_match_cannot_be_drawn(self):
        result = self.run_function('price_band', {'upper_source': {'kind': 'high'},
            'lower_source': {'kind': 'low'}, 'condition': {'left': {'kind': 'close'},
                'op': 'gt', 'right': {'constant': 1000}}})
        self.assertTrue(result['summary']['empty'])
        self.f.assert_code('empty_price_band', lambda: self.f.prepare(
            ChartEdit(kind='price_band', action='create', result_ref=result['result_ref'])))
        self.assertEqual(self.f.published, [])

    def test_price_sticks_result_is_read_only_until_guarded_apply_and_reuses_identity(self):
        params = {'start_source': {'kind': 'high'}, 'end_source': {'kind': 'low'}}
        before = deepcopy(self.f.payload)
        result = self.run_function('price_sticks', params)
        self.assertEqual(result['result_ref'], self.run_function('price_sticks', params)['result_ref'])
        self.assertEqual(result['kind'], 'price_sticks')
        self.assertEqual(result['summary']['matched_bars'], 4)
        self.assertNotIn('render_start_values', result)
        created = self.f.prepare(ChartEdit(kind='price_sticks', action='create', result_ref=result['result_ref'],
            name='高低柱线', color='warning'))
        sticks = created['object']
        self.assertEqual(sticks['valid_bars'], 4)
        self.assertEqual(set(created['drawing_guard']['parameters']), {'digest_sha256'})
        self.assertNotIn('start_values', json.dumps(created))
        self.assertEqual(self.f.published[0]['chartCommands'][-1]['start_values'], [36.0] * 4)
        self.assertEqual(self.f.published[0]['chartCommands'][-1]['end_values'], [28.0] * 4)
        self.assertEqual(self.f.published[0]['chartCommands'][:-1], before['chartCommands'])
        self.adopt(created)
        changed = self.f.prepare(ChartEdit(kind='price_sticks', action='update', object_id=sticks['id'],
            color='info'), expected_revision=2, request_id='sticks-color')
        self.assertEqual(changed['object']['id'], sticks['id'])
        self.assertEqual(changed['object']['sticks_hash'], sticks['sticks_hash'])
        self.adopt(changed)
        removed = self.f.prepare(ChartEdit(kind='price_sticks', action='delete', object_id=sticks['id']),
            expected_revision=3, request_id='sticks-delete')
        self.assertEqual(self.f.published[-1]['chartCommands'], before['chartCommands'])

    def test_price_sticks_zero_match_cannot_be_drawn(self):
        result = self.run_function('price_sticks', {'start_source': {'kind': 'high'},
            'end_source': {'kind': 'low'}, 'condition': {'left': {'kind': 'close'},
                'op': 'gt', 'right': {'constant': 1000}}})
        self.assertTrue(result['summary']['empty'])
        self.f.assert_code('empty_price_sticks', lambda: self.f.prepare(
            ChartEdit(kind='price_sticks', action='create', result_ref=result['result_ref'])))
        self.assertEqual(self.f.published, [])

    def test_selected_channel_candidate_requires_confirmation_and_uses_saved_anchors(self):
        from test_channel_candidates import trend_rows
        rows = trend_rows('ascending')
        for index, row in enumerate(rows): row['time'] = 1790000000 + index * 86400
        self.f.payload['chartCommands'][0]['rows'] = deepcopy(rows)
        self.f.payload['count'] = len(rows)
        self.f.record['state']['candles'] = deepcopy(rows)
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        result = self.run_function('channel_candidates', {'direction': 'ascending', 'max_candidates': 2})
        self.assertGreater(result['summary']['returned'], 0)
        self.f.assert_code('candidate_confirmation_required', lambda: self.f.prepare(
            ChartEdit(kind='channel', action='create', candidate_result_ref=result['result_ref'], candidate_number=1)))
        self.f.assert_code('candidate_confirmation_required', lambda: self.f.prepare(
            ChartEdit(kind='channel', action='create', candidate_result_ref=result['result_ref'], candidate_number=1,
                      user_confirmed_candidate=False)))
        self.f.assert_code('candidate_not_found', lambda: self.f.prepare(
            ChartEdit(kind='channel', action='create', candidate_result_ref=result['result_ref'], candidate_number=5,
                      user_confirmed_candidate=True)))
        before = deepcopy(self.f.payload)
        prepared = self.f.prepare(ChartEdit(kind='channel', action='create',
            candidate_result_ref=result['result_ref'], candidate_number=1, user_confirmed_candidate=True))
        anchors = result['summary']['candidates'][0]['anchors']
        self.assertEqual(prepared['object']['from']['time'], anchors['from']['time'])
        self.assertEqual(prepared['object']['parallel']['price'], anchors['parallel']['price'])
        self.assertEqual(self.f.published[0]['chartCommands'][:-1], before['chartCommands'])
        self.f.record['state']['candles'][-1]['close'] += 0.1
        self.f.save_context()
        self.f.assert_code('chart_function_result_mismatch', lambda: self.f.prepare(
            ChartEdit(kind='channel', action='create', candidate_result_ref=result['result_ref'],
                      candidate_number=1, user_confirmed_candidate=True), request_id='stale'))

    def test_selected_range_candidate_uses_result_without_host_coordinate_copy(self):
        from test_range_candidates import sideways_rows
        rows = sideways_rows()
        for index, row in enumerate(rows): row['time'] = 1790000000 + index * 86400
        self.f.payload['chartCommands'][0]['rows'] = deepcopy(rows)
        self.f.payload['count'] = len(rows)
        self.f.record['state']['candles'] = deepcopy(rows)
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        result = self.run_function('range_candidates', {'window_sizes': [20, 30], 'max_candidates': 2})
        self.assertGreater(result['summary']['returned'], 0)
        prepared = self.f.prepare(ChartEdit(kind='rectangle', action='create',
            candidate_result_ref=result['result_ref'], candidate_number=1, user_confirmed_candidate=True,
            color='info'))
        candidate = result['summary']['candidates'][0]
        self.assertEqual(prepared['object']['lower_price'], candidate['lower_price'])
        self.assertEqual(prepared['object']['upper_price'], candidate['upper_price'])
        self.assertEqual(prepared['object']['start_time'], candidate['start_time'])

    def test_mcp_pivot_function_is_read_only_analysis_not_a_drawing_result(self):
        with patch('server.fetch_candles', side_effect=AssertionError('no market fetch')), \
             patch('chart_service.publish_chart', side_effect=AssertionError('analysis must not publish')):
            response = asyncio.run(server.run_chart_function(self.f.ref, 1, self.f.token, self.f.payload['symbol'],
                'pivot_candidates', ChartFunctionParameters(left_bars=1, right_bars=1)))
        data = response.structuredContent
        self.assertEqual(data['result_usage'], 'analysis_only')
        self.assertEqual(data['summary']['candidate_count'], 0)
        self.assertFalse(data['chart_modified'])
        self.assertIn('拐点候选分析完成，未绘图', response.content[0].text)
        self.assertNotIn('prepare_chart_edit', response.content[0].text.split(' · ', 1)[0])
        self.assertEqual(self.f.published, [])

    def test_mcp_channel_candidates_are_explicitly_analysis_only(self):
        from test_channel_candidates import trend_rows
        rows = trend_rows('ascending')
        for index, row in enumerate(rows):
            row['time'] = 1790000000 + index * 86400
        self.f.payload['chartCommands'][0]['rows'] = deepcopy(rows)
        self.f.payload['count'] = len(rows)
        self.f.record['state']['candles'] = deepcopy(rows)
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        with patch('server.fetch_candles', side_effect=AssertionError('no market fetch')), \
             patch('chart_service.publish_chart', side_effect=AssertionError('analysis must not publish')):
            response = asyncio.run(server.run_chart_function(self.f.ref, 1, self.f.token, self.f.payload['symbol'],
                'channel_candidates', ChartFunctionParameters()))
        data = response.structuredContent
        self.assertEqual(data['result_usage'], 'analysis_only')
        self.assertGreater(data['summary']['candidate_count'], 0)
        self.assertFalse(data['chart_modified'])
        self.assertIn('通道候选分析完成，未绘图', response.content[0].text)
        self.assertEqual(self.f.published, [])

    def test_mcp_range_candidates_are_explicitly_analysis_only(self):
        from test_range_candidates import sideways_rows
        rows = sideways_rows()
        for index, row in enumerate(rows):
            row['time'] = 1790000000 + index * 86400
        self.f.payload['chartCommands'][0]['rows'] = deepcopy(rows)
        self.f.payload['count'] = len(rows)
        self.f.record['state']['candles'] = deepcopy(rows)
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        with patch('server.fetch_candles', side_effect=AssertionError('no market fetch')), \
             patch('chart_service.publish_chart', side_effect=AssertionError('analysis must not publish')):
            response = asyncio.run(server.run_chart_function(self.f.ref, 1, self.f.token, self.f.payload['symbol'],
                'range_candidates', ChartFunctionParameters()))
        data = response.structuredContent
        self.assertEqual(data['result_usage'], 'analysis_only')
        self.assertGreater(data['summary']['candidate_count'], 0)
        self.assertFalse(data['chart_modified'])
        self.assertIn('平台区间候选分析完成，未绘图', response.content[0].text)
        self.assertEqual(self.f.published, [])

    def test_repeat_calculation_reuses_reference_without_context_or_snapshot_changes(self):
        before = self.f.path.read_bytes(); original = deepcopy(self.f.payload)
        result = self.run_function()
        for _ in range(10): self.assertEqual(self.run_function()['result_ref'], result['result_ref'])
        equivalent = {**self.params, 'start_time': result['parameters']['start_time'], 'ratios': DEFAULT_RATIOS}
        self.assertEqual(self.run_function(params=equivalent)['result_ref'], result['result_ref'])
        self.assertFalse(result['chart_modified']); self.assertFalse(result['render_verified'])
        self.assertEqual(self.f.path.read_bytes(), before); self.assertEqual(self.f.payload, original)
        self.assertEqual(len(list((self.f.runtime / 'functions' / '4242' / self.f.ref).glob('*.json'))), 1)
        self.assertEqual(self.f.published, [])
        stored = next((self.f.runtime / 'functions').rglob('*.json'))
        text = stored.read_text()
        self.assertIn('function_version', text); self.assertNotIn('api_key', text)
        self.assertNotIn('candles', result); self.assertGreaterEqual(result['calculation_ms'], 0)

    def test_function_references_feed_all_three_existing_guarded_editors(self):
        original = deepcopy(self.f.payload['chartCommands'])
        cases = [('fibonacci_retracement', self.params, 'fibonacci_retracement'),
                 ('parallel_channel', {**self.params, 'parallel_time': '2026-09-11', 'parallel_price': 38}, 'channel'),
                 ('range_box', {'start_time': '2026-09-10', 'end_time': '2026-09-15', 'lower_price': 29, 'upper_price': 35}, 'rectangle')]
        for index, (function, params, kind) in enumerate(cases, 1):
            self.f.record['revision'] = index; self.f.save_context()
            calculated = self.run_function(function, params)
            edit = ChartEdit(kind=kind, action='create', result_ref=calculated['result_ref'], name='计算样板', color='绿色')
            prepared = self.f.prepare(edit, expected_revision=index, request_id='function' + str(index))
            self.assertEqual(prepared['object']['color'], 'success')
            self.assertEqual(self.f.published[-1]['chartCommands'][:-1], original)
            self.assertEqual(read_edit_status(self.f.ref, prepared['chart_session'])['apply_status'], 'not_requested')
            self.assertEqual(self.f.prepare(edit, expected_revision=index, request_id='function' + str(index))['chart_session'], prepared['chart_session'])

    def test_workbench_json_parameters_use_the_same_validated_function_path(self):
        cases = [
            ('fibonacci_retracement', self.params),
            ('parallel_channel', {**self.params, 'parallel_time': '2026-09-11', 'parallel_price': 38}),
            ('range_box', {'start_time': '2026-09-10', 'end_time': '2026-09-15', 'lower_price': 29, 'upper_price': 35}),
            ('labeled_polyline', {'points': [
                {'label': 'A', 'time': '2026-09-10', 'price': 30},
                {'label': 'B', 'time': '2026-09-11', 'price': 35},
                {'label': 'C', 'time': '2026-09-15', 'price': 40},
            ]}),
        ]
        kinds = {'fibonacci_retracement': 'fibonacci_retracement', 'parallel_channel': 'channel',
                 'range_box': 'rectangle', 'labeled_polyline': 'labeled_polyline'}
        for index, (function, parameters) in enumerate(cases):
            with self.subTest(function=function):
                self.f.record['revision'] = index + 1
                self.f.save_context()
                binding = {
                    'context_ref': self.f.ref, 'expected_revision': self.f.record['revision'],
                    'chart_session': self.f.token, 'symbol': self.f.payload['symbol'],
                }
                response = chart_service._tool_dispatch('workbench_run_chart_function', {
                    **binding, 'function': function, 'parameters': parameters})
                self.assertTrue(response['ok'], response)
                self.assertEqual(response['function'], function)
                self.assertTrue(response['result_ref'])
                self.assertFalse(response['chart_modified'])
                prepared = chart_service._tool_dispatch('workbench_prepare_edit', {
                    **binding, 'request_id': f'json-workbench-{index}', 'edit': {
                        'kind': kinds[function], 'action': 'create', 'name': '工作台提案',
                        'color': '蓝色', 'result_ref': response['result_ref'],
                    }})
                self.assertTrue(prepared['ok'], prepared)
                self.assertEqual(prepared['object']['label'], '工作台提案')
                self.assertEqual(read_edit_status(self.f.ref, prepared['chart_session'])['apply_status'], 'not_requested')
        invalid = chart_service._tool_dispatch('workbench_run_chart_function', {
            'context_ref': self.f.ref, 'expected_revision': self.f.record['revision'],
            'chart_session': self.f.token, 'symbol': self.f.payload['symbol'],
            'function': 'parallel_channel', 'parameters': {'parallel_price': -1},
        })
        self.assertEqual(invalid['error'], 'invalid_function_parameters')

    def test_fibonacci_create_style_geometry_update_and_delete_keep_other_objects(self):
        original = deepcopy(self.f.payload['chartCommands'])
        result = self.run_function()
        first = self.f.prepare(ChartEdit(kind='fibonacci_retracement', action='create', result_ref=result['result_ref'], name='回撤', color='蓝色'))
        self.adopt(first)
        style = self.f.prepare(ChartEdit(kind='fibonacci_retracement', action='update', object_id=first['object']['id'], color='橙色'),
                               expected_revision=2, request_id='style', chart_session=self.f.token)
        self.assertEqual(style['object']['levels'], first['object']['levels']); self.adopt(style)
        changed = self.run_function(params={**self.params, 'end_price': 42, 'ratios': [0, .618, 1]})
        geometry = self.f.prepare(ChartEdit(kind='fibonacci_retracement', action='update', object_id=first['object']['id'], result_ref=changed['result_ref']),
                                  expected_revision=3, request_id='geometry', chart_session=self.f.token)
        self.assertEqual(geometry['object']['id'], first['object']['id'])
        self.assertAlmostEqual(geometry['object']['levels'][1]['price'], 34.584)
        self.assertTrue(verify_drawings(self.f.published[-1], [dict(kind='fibonacci_retracement', id=first['object']['id'], ratios=[0, .618, 1], end_price=42)])['matches'])
        self.adopt(geometry)
        deleted = self.f.prepare(ChartEdit(kind='fibonacci_retracement', action='delete', object_id=first['object']['id']),
                                expected_revision=4, request_id='delete', chart_session=self.f.token)
        self.assertEqual(self.f.published[-1]['chartCommands'], original)
        self.assertEqual(deleted['object']['id'], first['object']['id'])

    def test_result_cannot_cross_data_or_view_boundaries(self):
        result = self.run_function()
        for key, value in [('symbol', 'OTHER.X'), ('interval', 'week'), ('adjust', 'forward'), ('interval_value', 5)]:
            context = self.context(); context[key] = value
            self.f.assert_code('chart_function_result_mismatch', lambda: resolve_result(result['result_ref'], context, result['kind']))
        for key in ('view_id', 'conversation_id'):
            context = self.context(); context[key] = 'foreign'
            self.f.assert_code('chart_function_result_mismatch', lambda: resolve_result(result['result_ref'], context, result['kind']))
        context = self.context(); context['candles'][0]['volume'] += 1
        self.f.assert_code('chart_function_result_mismatch', lambda: resolve_result(result['result_ref'], context, result['kind']))
        self.f.assert_code('chart_function_result_mismatch', lambda: resolve_result(result['result_ref'], self.context(), 'channel'))
        context = self.context(); context['context_ref'] = 'z'*32
        self.f.assert_code('chart_function_result_unavailable', lambda: resolve_result(result['result_ref'], context, result['kind']))
        context = self.context()
        with patch.object(chart_service, 'HOST_PROCESS_ID', 4243):
            self.f.assert_code('chart_function_result_unavailable', lambda: resolve_result(result['result_ref'], context, result['kind']))

    def test_style_and_viewport_changes_do_not_invalidate_price_calculation(self):
        result = self.run_function()
        context = self.context(); context.update(revision=5, visible_range={'available': False}, drawings=[])
        self.assertEqual(resolve_result(result['result_ref'], context, result['kind']), result['parameters'])

    def test_mixed_reference_and_direct_geometry_is_rejected_before_preparation(self):
        result = self.run_function()
        self.f.assert_code('conflicting_function_parameters', lambda: self.f.prepare(
            ChartEdit(kind='fibonacci_retracement', action='create', result_ref=result['result_ref'], end_price=99)))
        self.assertEqual(self.f.published, [])

    def test_missing_ambiguous_invalid_and_irrelevant_parameters_never_guess(self):
        for params, code in [({}, 'missing_anchor'), ({**self.params, 'end_time': '2026-09-12'}, 'anchor_not_found'),
                             ({**self.params, 'end_time': '2026-09-10'}, 'invalid_anchor_order'),
                             ({**self.params, 'end_price': 30}, 'zero_fibonacci_range'),
                             ({**self.params, 'ratios': [.5, .5]}, 'invalid_fibonacci_ratios'),
                             ({**self.params, 'upper_price': 90}, 'invalid_function_parameters')]:
            self.f.assert_code(code, lambda: self.run_function(params=params))
        self.f.assert_code('unknown_chart_function', lambda: self.run_function('eval'))
        self.assertEqual(self.f.published, [])
        self.assertFalse((self.f.runtime / 'functions').exists())

    def test_compute_requires_fresh_aligned_active_context_and_no_concurrent_changes(self):
        self.f.assert_code('chart_context_revision_conflict', lambda: self.run_function(expected_revision=2))
        self.f.record['active'] = False; self.f.save_context()
        self.f.assert_code('chart_view_inactive', self.run_function)
        self.f.record['active'] = True; self.f.save_context()
        initial = self.context(); changed = deepcopy(initial); changed['revision'] += 1
        with patch('tools.chart_functions.read_chart_context', side_effect=[initial, changed]):
            self.f.assert_code('chart_context_revision_conflict', self.run_function)
        self.assertFalse((self.f.runtime / 'functions').exists())

    def test_corrupt_and_path_like_refs_are_never_loaded_or_repaired(self):
        result = self.run_function(); path = next((self.f.runtime / 'functions').rglob('*.json'))
        path.write_text('{}')
        self.f.assert_code('chart_function_result_unavailable', lambda: resolve_result(result['result_ref'], self.context(), result['kind']))
        self.f.assert_code('chart_function_result_invalid', self.run_function)
        self.f.assert_code('invalid_function_result_ref', lambda: resolve_result('../elsewhere', self.context(), result['kind']))
        self.assertEqual(path.read_text(), '{}')

    def test_fibonacci_editor_idempotence_limits_and_atomic_errors(self):
        p, obj = edit_fibonacci(self.f.payload, 'create', **self.params, request_id='fixed')
        again, retry = edit_fibonacci(p, 'create', **self.params, request_id='fixed')
        self.assertEqual(again, p); self.assertEqual(retry, obj)
        self.f.assert_code('request_conflict', lambda: edit_fibonacci(p, 'create', **{**self.params, 'end_price': 41}, request_id='fixed'))
        self.f.assert_code('zero_fibonacci_range', lambda: edit_fibonacci(p, 'update', fibonacci_id=obj['id'], end_price=30))
        self.assertEqual(p['chartCommands'][-1], obj)
        for i in range(29): p, _ = edit_fibonacci(p, 'create', **self.params)
        self.f.assert_code('too_many_fibonacci', lambda: edit_fibonacci(p, 'create', **self.params))

    def test_result_capacity_preserves_old_refs_and_does_not_block_replay(self):
        first = self.run_function()
        directory = self.f.runtime / 'functions' / '4242' / self.f.ref
        for i in range(63): chart_service._atomic_runtime_json(directory / ('fixture' + str(i) + '.json'), {})
        self.assertEqual(self.run_function()['result_ref'], first['result_ref'])
        self.f.assert_code('chart_function_capacity', lambda: self.run_function(params={**self.params, 'end_price': 41}))
        self.assertEqual(len(list(directory.glob('*.json'))), 64)
        self.assertEqual(resolve_result(first['result_ref'], self.context(), first['kind']), first['parameters'])

    def test_calculation_is_not_limited_by_existing_drawing_capacity(self):
        for _ in range(30): self.f.payload, _ = edit_fibonacci(self.f.payload, 'create', **self.params)
        self.f.record['state']['drawings'] = snapshot_inventory(self.f.payload)
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        result = self.run_function()
        self.f.assert_code('too_many_fibonacci', lambda: self.f.prepare(ChartEdit(kind=result['kind'], action='create', result_ref=result['result_ref'])))
        self.assertEqual(self.f.published, [])

    def test_week_and_minute_sources_keep_precise_time_and_size(self):
        for interval in ('week', 'minute'):
            self.f.payload['interval'] = interval
            self.f.payload['interval_value'] = 5 if interval == 'minute' else 1
            self.f.record['state'].update(interval=interval, interval_value=self.f.payload['interval_value'])
            self.f.record['state']['drawings'] = snapshot_inventory(self.f.payload)
            self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
            rows = self.f.payload['chartCommands'][0]['rows']
            params = {**self.params, 'start_time': str(rows[0]['time']), 'end_time': str(rows[-1]['time'])}
            result = self.run_function(params=params)
            self.assertEqual(result['data_scope']['interval'], interval)
            self.assertEqual(result['data_scope']['interval_value'], self.f.payload['interval_value'])
            if interval == 'minute': self.f.assert_code('ambiguous_anchor_time', self.run_function)

    def test_mcp_result_contains_summary_but_never_marks_calculation_as_application(self):
        result = asyncio.run(server.run_chart_function(self.f.ref, 1, self.f.token, self.f.payload['symbol'],
                            'fibonacci_retracement', ChartFunctionParameters(**self.params)))
        data = result.structuredContent
        self.assertEqual(json.loads(result.content[0].text.split(' · ', 1)[1]), data)
        self.assertFalse(data['chart_modified']); self.assertNotIn('chart_session', data)
        self.assertEqual(self.f.published, [])

    def test_python_feedback_accepts_fibonacci_without_claiming_pixels(self):
        allowed = [dict(id='F', kind='fibonacci_retracement')]
        raw = dict(schema_version=1, phase='applied', items=[dict(id='F', kind='fibonacci_retracement', status='created',
                   reason='overlay_registered', visibility='unknown')])
        cleaned = sanitize_drawing_feedback(raw, allowed)
        self.assertEqual(cleaned['report_status'], 'reported'); self.assertFalse(cleaned['pixel_verified'])
