import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError
import chart_service
import server
import test_chart_edits as fixtures
from tools.chart_edits import ChartEdit, snapshot_inventory
from tools.chart_functions import ChartFunctionParameters, list_functions, run_function
from tools.chart_context import read_chart_context
from tools.chart_applications import request_chart_apply, read_edit_status
from tools.drawing_feedback import sanitize_drawing_feedback
from tools.drawing_interaction import edit_change, error_interaction
from tools.drawing_verification import verify_drawings
from tools.polylines import LabeledPoint, POLYLINE_COMMAND, edit_polyline, resolve_points, validate_stored_points


def points():
    return [dict(label='A', time='2026-09-10', price=30), dict(label='B', time='2026-09-11', price=34),
            dict(label='C', time='2026-09-14', price=31)]


class PolylineTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.GuardedEditTests('test_prepares_without_changing_source_context_or_other_shapes')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.record['guarded_apply_supported'] = True; self.f.save_context()

    def calculate(self, raw=None):
        with patch('chart_service.publish_chart', side_effect=AssertionError('no publication')), \
             patch('server.fetch_candles', side_effect=AssertionError('no fetch')):
            return run_function(self.f.ref, self.f.record['revision'], self.f.token, self.f.payload['symbol'],
                                'labeled_polyline', ChartFunctionParameters(points=points() if raw is None else raw))

    def adopt(self, prepared):
        """Simulated matching broker proof; real cross-language/browser tests are separate."""
        token = prepared['chart_session']
        request_chart_apply(self.f.ref, token)
        path = self.f.runtime / 'edits' / '4242' / self.f.ref / 'applications' / (token + '.json')
        app = json.loads(path.read_text()); app.update(status='applied', confirmed_chart_session=token)
        chart_service._atomic_runtime_json(path, app)
        self.f.payload = chart_service.read_chart_snapshot(token); self.f.token = token
        self.f.record['revision'] += 1
        self.f.record['state'].update(source_chart_session=token, drawings=snapshot_inventory(self.f.payload))
        self.f.save_context()

    def prepare(self, edit, request):
        return self.f.prepare(edit, expected_revision=self.f.record['revision'], chart_session=self.f.token, request_id=request)

    def test_registry_uses_generic_points_not_wave_templates_or_new_tools(self):
        f = next(item for item in list_functions()['functions'] if item['name'] == 'labeled_polyline')
        self.assertEqual(f['name'], 'labeled_polyline'); self.assertEqual(f['required_parameters'], ['points'])
        array_schema = next(s for s in f['parameter_schema']['properties']['points']['anyOf'] if s.get('type') == 'array')
        self.assertEqual(array_schema['maxItems'], 8)
        self.assertIn('LabeledPoint', f['parameter_schema']['$defs'])
        self.assertEqual(len(asyncio.run(server.mcp.list_tools())), 41)
        custom = [{**p, 'label': str(i)} for i, p in enumerate(points(), 1)]
        self.assertEqual([p['label'] for p in self.calculate(custom)['summary']['points']], ['1', '2', '3'])
        self.assertFalse(self.calculate()['summary']['automatic_wave_recognition'])

    def test_calculation_returns_reusable_reference_without_mutating_any_chart(self):
        original = deepcopy(self.f.payload); observation = self.f.path.read_bytes()
        result = self.calculate()
        for _ in range(10): self.assertEqual(self.calculate()['result_ref'], result['result_ref'])
        equivalent = [{**p, 'time': resolved['time']} for p, resolved in zip(points(), result['parameters']['points'])]
        self.assertEqual(self.calculate(equivalent)['result_ref'], result['result_ref'])
        self.assertEqual(self.f.payload, original); self.assertEqual(self.f.path.read_bytes(), observation)
        self.assertFalse(result['chart_modified']); self.assertFalse(result['pattern_quality_verified'])
        self.assertEqual(self.f.published, [])

    def test_create_move_only_C_recolor_and_delete_preserve_group_and_other_objects(self):
        original = deepcopy(self.f.payload['chartCommands'])
        # A second group may also contain A/B/C; stable object ID scopes the edit.
        self.f.payload, second = edit_polyline(self.f.payload, 'create', points=points(), name='保留组')
        self.f.record['state']['drawings'] = snapshot_inventory(self.f.payload)
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        result = self.calculate()
        created = self.prepare(ChartEdit(kind='labeled_polyline', action='create', result_ref=result['result_ref'], name='ABC样板', color='蓝色'), 'create')
        obj = created['object']; self.assertEqual(obj['type'], POLYLINE_COMMAND)
        self.assertEqual(read_edit_status(self.f.ref, created['chart_session'])['apply_status'], 'not_requested')
        self.adopt(created)
        changed = self.prepare(ChartEdit(kind='labeled_polyline', action='update', object_id=obj['id'], point_label='C',
                                         point_time='2026-09-15', point_price=32), 'move')
        after = changed['object']
        self.assertEqual(after['id'], obj['id']); self.assertEqual(after['points'][:2], obj['points'][:2])
        self.assertEqual(after['points'][2]['price'], 32); self.assertEqual(after['points'][2]['label'], 'C')
        candidate = chart_service.read_chart_snapshot(changed['chart_session'])
        delta = edit_change(candidate, self.f.payload)
        self.assertEqual([p['label'] for p in delta['point_changes']], ['C'])
        self.assertTrue(delta['other_ai_drawings_unchanged']); self.adopt(changed)
        style = self.prepare(ChartEdit(kind='labeled_polyline', action='update', object_id=obj['id'], name='完整ABC', color='橙色'), 'style')
        self.assertEqual(style['object']['points'], after['points']); self.assertEqual(style['object']['color'], 'warning')
        self.assertEqual(edit_change(chart_service.read_chart_snapshot(style['chart_session']), self.f.payload)['point_changes'], [])
        self.adopt(style)
        deleted = self.prepare(ChartEdit(kind='labeled_polyline', action='delete', object_id=obj['id']), 'delete')
        self.assertEqual(deleted['object']['id'], obj['id'])
        self.assertEqual(self.f.published[-1]['chartCommands'], original + [second])

    def test_invalid_paths_never_sort_snap_or_publish(self):
        for raw, code in [([points()[0]], 'invalid_polyline_points'),
                          ([points()[0], {**points()[1], 'label': ' A '}], 'duplicate_point_label'),
                          ([points()[1], points()[0]], 'invalid_anchor_order'),
                          ([points()[0], {**points()[1], 'time': '2026-09-12'}], 'anchor_not_found'),
                          ([points()[0], {**points()[1], 'label': ' '}], 'invalid_point_label'),
                          ([points()[0], {**points()[1], 'label': 'B\n'}], 'invalid_point_label')]:
            self.f.assert_code(code, lambda: edit_polyline(self.f.payload, 'create', points=raw))
        self.assertEqual(self.f.published, [])

    def test_schema_rejects_missing_labels_unknown_fields_bad_prices_and_lengths(self):
        for raw in [dict(time='1', price=30), dict(label='A', time='1', price=True),
                    dict(label='A', time='1', price=float('inf')), dict(label='A', time='1', price=-1),
                    dict(label='A', time='1', price=30, arbitrary_code='x')]:
            with self.subTest(raw=raw), self.assertRaises(ValidationError): LabeledPoint(**raw)
        for raw in [[], points()*3]:
            with self.assertRaises(ValidationError): ChartFunctionParameters(points=raw)

    def test_bad_single_point_edits_are_atomic_and_never_replace_whole_group(self):
        payload, obj = edit_polyline(self.f.payload, 'create', points=points())
        original = deepcopy(payload)
        for params, code in [({'point_price': 32}, 'point_label_required'),
                             ({'point_label': 'C'}, 'empty_point_update'),
                             ({'point_label': 'D', 'point_price': 32}, 'point_not_found'),
                             ({'point_label': 'C', 'point_time': '2026-09-10'}, 'invalid_anchor_order'),
                             ({'point_label': 'C', 'point_time': '2026-09-12'}, 'anchor_not_found'),
                             ({'points': points()}, 'polyline_replacement_not_supported'),
                             ({}, 'empty_update')]:
            self.f.assert_code(code, lambda: edit_polyline(payload, 'update', polyline_id=obj['id'], **params))
            self.assertEqual(payload, original)

    def test_guarded_schema_disallows_reference_mixed_geometry_or_whole_replacement(self):
        ref = self.calculate()['result_ref']
        self.f.assert_code('conflicting_function_parameters', lambda: self.prepare(
            ChartEdit(kind='labeled_polyline', action='create', result_ref=ref, points=points()), 'mixed'))
        self.f.assert_code('polyline_replacement_not_supported', lambda: self.prepare(
            ChartEdit(kind='labeled_polyline', action='update', object_id='existing', result_ref=ref), 'replace'))
        self.f.assert_code('invalid_edit_fields', lambda: self.prepare(
            ChartEdit(kind='labeled_polyline', action='delete', object_id='existing', point_label='C'), 'delete-extra'))
        self.assertEqual(self.f.published, [])

    def test_retry_is_idempotent_and_geometry_conflicts_do_not_overwrite(self):
        payload, obj = edit_polyline(self.f.payload, 'create', points=points(), request_id='fixed')
        repeated, again = edit_polyline(payload, 'create', points=points(), request_id='fixed')
        self.assertEqual(repeated, payload); self.assertEqual(obj, again)
        changed = points(); changed[-1]['price'] = 32
        self.f.assert_code('request_conflict', lambda: edit_polyline(payload, 'create', points=changed, request_id='fixed'))
        ref = self.calculate()['result_ref']
        first = self.prepare(ChartEdit(kind='labeled_polyline', action='create', result_ref=ref), 'repeat')
        second = self.prepare(ChartEdit(kind='labeled_polyline', action='create', result_ref=ref), 'repeat')
        self.assertEqual(first['chart_session'], second['chart_session']); self.assertTrue(second['replayed'])
        self.assertEqual(len(self.f.published), 1)

    def test_name_and_color_never_resolve_or_edit_another_group(self):
        payload, one = edit_polyline(self.f.payload, 'create', points=points(), name='同名')
        payload, two = edit_polyline(payload, 'create', points=points(), name='同名')
        changed, updated = edit_polyline(payload, 'update', polyline_id=one['id'], point_label='C', point_price=32)
        self.assertEqual(next(c for c in changed['chartCommands'] if c.get('id') == two['id']), two)
        self.assertEqual(updated['id'], one['id'])
        self.f.assert_code('polyline_not_found', lambda: edit_polyline(payload, 'update', polyline_id='同名', point_label='C', point_price=32))
        self.assertEqual(error_interaction('point_not_found')['next_action'], 'ask_user')

    def test_point_verification_checks_exact_requested_label_time_and_price(self):
        p, obj = edit_polyline(self.f.payload, 'create', points=points())
        expected = dict(kind='labeled_polyline', id=obj['id'], point_label='C', point_time='2026-09-14', point_price=31)
        self.assertTrue(verify_drawings(p, [expected])['matches'])
        result = verify_drawings(p, [{**expected, 'point_price': 32}])
        self.assertEqual(result['checks'][0]['mismatches'][0]['field'], 'point_price')
        self.assertFalse(verify_drawings(p, [{**expected, 'point_label': 'D'}])['matches'])
        self.f.assert_code('point_label_required', lambda: verify_drawings(p, [dict(kind='labeled_polyline', id=obj['id'], point_price=31)]))
        removed, _ = edit_polyline(p, 'delete', polyline_id=obj['id'])
        self.assertTrue(verify_drawings(removed, [dict(kind='labeled_polyline', id=obj['id'], exists=False)])['matches'])

    def test_capacity_readonly_calculation_and_boundary_point_counts(self):
        payload = self.f.payload
        for _ in range(30): payload, _ = edit_polyline(payload, 'create', points=points())
        self.f.assert_code('too_many_polylines', lambda: edit_polyline(payload, 'create', points=points()))
        self.f.payload = payload; self.f.record['state']['drawings'] = snapshot_inventory(payload)
        self.f.save_context(); self.f.save_snapshot(self.f.token, payload)
        self.assertEqual(self.calculate()['summary']['point_count'], 3)
        two = points()[:2]
        self.assertEqual(len(resolve_points(payload, two)), 2)
        raw = [dict(label=str(i), time=i+1, price=30) for i in range(8)]
        self.assertEqual(len(validate_stored_points(raw)), 8)
        self.f.assert_code('invalid_polyline_points', lambda: validate_stored_points(raw + [dict(label='9', time=9, price=30)]))

    def test_labeled_inventory_is_canonical_and_source_period_isolation_remains(self):
        payload, obj = edit_polyline(self.f.payload, 'create', points=points())
        self.f.payload = payload; self.f.record['state']['drawings'] = snapshot_inventory(payload)
        self.f.save_context(); self.f.save_snapshot(self.f.token, payload)
        observed = read_chart_context(self.f.ref)['drawings'][-1]
        self.assertEqual(observed['points'], obj['points']); self.assertEqual(observed['kind'], 'labeled_polyline')
        self.f.payload['interval'] = 'week'; self.f.record['state']['interval'] = 'week'
        self.f.record['state']['drawings'] = snapshot_inventory(self.f.payload)
        self.f.save_context(); self.f.save_snapshot(self.f.token, self.f.payload)
        self.f.assert_code('drawing_interval_mismatch', lambda: self.prepare(
            ChartEdit(kind='labeled_polyline', action='update', object_id=obj['id'], point_label='C', point_price=32), 'wrong-period'))

    def test_minute_date_is_ambiguous_but_exact_times_work(self):
        self.f.payload['interval'] = 'minute'; self.f.payload['interval_value'] = 5
        self.f.assert_code('ambiguous_anchor_time', lambda: edit_polyline(self.f.payload, 'create', points=points()))
        rows = self.f.payload['chartCommands'][0]['rows']
        raw = [{**p, 'time': str(row['time'])} for p, row in zip(points(), rows)]
        _, obj = edit_polyline(self.f.payload, 'create', points=raw)
        self.assertEqual([p['time'] for p in obj['points']], [r['time'] for r in rows[:3]])

    def test_mcp_computation_and_feedback_do_not_claim_a_render(self):
        response = asyncio.run(server.run_chart_function(self.f.ref, 1, self.f.token, self.f.payload['symbol'],
                              'labeled_polyline', ChartFunctionParameters(points=points())))
        self.assertFalse(response.structuredContent['chart_modified']); self.assertEqual(self.f.published, [])
        report = sanitize_drawing_feedback(dict(schema_version=1, phase='applied', items=[dict(id='P', kind='labeled_polyline',
                    status='created', reason='overlay_registered', visibility='unknown')]), [dict(id='P', kind='labeled_polyline')])
        self.assertEqual(report['report_status'], 'reported'); self.assertFalse(report['pixel_verified'])
