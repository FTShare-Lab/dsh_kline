import asyncio
from copy import deepcopy
import json
from typing import get_args
import unittest
from unittest.mock import patch

import chart_service
import server
from tools.chart_edits import ChartEdit
from tools.drawing_interaction import drawing_capabilities, edit_change, edit_interaction, error_interaction
from tools.lines import ColorInput
import test_chart_edits as fixtures


class DrawingInteractionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.GuardedEditTests('test_prepares_without_changing_source_context_or_other_shapes')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_capabilities_match_existing_color_schema_without_granting_selection_or_authority(self):
        caps = drawing_capabilities()
        accepted = set(get_args(ColorInput))
        self.assertEqual(set(caps['color_inputs']), accepted)
        self.assertEqual(caps['editable_origins'], ['ai'])
        self.assertFalse(caps['drawing_selection_supported'])
        self.assertEqual(caps['ambiguous_target'], 'ask_user')
        self.assertEqual(caps['unspecified_price_amount'], 'ask_user')
        self.assertNotIn('edit_authorized', caps)

    def test_tool_discovery_unambiguously_routes_all_current_chart_writes_without_removing_legacy_tools(self):
        tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
        self.assertEqual(len(tools), 41)
        self.assertIn('run_chart_function', tools)
        self.assertIn('list_chart_functions', tools)
        route = 'get_chart_context -> prepare_chart_edit -> apply_chart_edit -> get_chart_edit_status'
        for family in ('horizontal_line', 'trend_line', 'channel', 'rectangle'):
            for action in ('create', 'update', 'delete'):
                description = tools[f'{action}_{family}'].description
                self.assertTrue(description.startswith('LEGACY SNAPSHOT ONLY.'))
                self.assertIn(route, description)
                self.assertIn('Only explicit snapshot-editing requests', description)
        self.assertTrue(tools['prepare_chart_edit'].description.startswith('DEFAULT entry for ALL browser-chart'))
        self.assertIn('For ALL current-view drawing creates/updates/deletes', server.mcp.instructions)
        self.assertNotIn('For explicit horizontal-line drawing use create_horizontal_line', server.mcp.instructions)

    def test_prepared_pending_and_uncertain_states_never_claim_completion(self):
        cases = [('not_requested', 'prepared', 'read_current_context_before_apply'),
                 ('queued', 'pending', 'check_original_candidate_status'),
                 ('delivered', 'pending', 'check_original_candidate_status'),
                 ('outcome_unknown', 'unknown', 'check_original_candidate_status_do_not_resend'),
                 ('rejected', 'not_confirmed', 'read_current_context_before_new_edit'),
                 ('failed', 'not_confirmed', 'inspect_failure_do_not_resend'),
                 ('unexpected', 'unknown', 'stop_and_inspect')]
        for raw, status, next_action in cases:
            with self.subTest(raw=raw):
                value = edit_interaction({'apply_status': raw})
                self.assertEqual(value['status'], status)
                self.assertEqual(value['next_action'], next_action)
                self.assertFalse(value['completion_confirmed'])

    def test_applied_requires_matching_receipt_and_keeps_historical_and_pixel_limits(self):
        raw = dict(apply_status='applied', candidate_chart_session='a'*32, confirmed_chart_session='a'*32,
                   confirmation_scope='view_state_only', record_is_historical=True)
        result = edit_interaction(raw)
        self.assertEqual(result['status'], 'confirmed')
        self.assertTrue(result['completion_confirmed'])
        self.assertTrue(result['record_is_historical'])
        self.assertFalse(result['render_verified'])
        for changes in ({'confirmed_chart_session': 'b'*32}, {'confirmation_scope': 'not_confirmed'},
                        {'candidate_chart_session': '', 'confirmed_chart_session': ''},
                        {'needs_attention': True}):
            value = edit_interaction({**raw, **changes})
            self.assertFalse(value['completion_confirmed'])
            self.assertNotEqual(value['status'], 'confirmed')

    def test_receipt_describes_only_the_edited_object_and_never_claims_pixels(self):
        raw = dict(apply_status='applied', candidate_chart_session='a'*32, confirmed_chart_session='a'*32,
                   confirmation_scope='view_state_only', drawing_feedback=dict(report_status='reported', phase='applied', items=[
                       dict(id='other', status='failed', time_range_overlap=None),
                       dict(id='target', status='created', time_range_overlap=True)]))
        change = dict(action='create', before=None, after=dict(id='target'))
        result = edit_interaction(raw, change)
        self.assertEqual(result['object_status'], 'created')
        self.assertIs(result['time_range_overlap'], True)
        self.assertFalse(result['pixel_verified'])
        self.assertIn('像素未核验', result['message'])
        self.assertNotIn('像素已', result['message'])
        raw['drawing_feedback']['items'][1]['time_range_overlap'] = False
        self.assertIn('时间视口之外', edit_interaction(raw, change)['message'])
        raw['drawing_feedback']['items'][1]['status'] = 'removed'
        self.assertIn('已从图表对象表移除', edit_interaction(raw, dict(action='delete', before=dict(id='target'), after=None))['message'])
        self.assertEqual(edit_interaction(raw, dict(action='create', before=None, after=dict(id='absent')))['object_status'], 'unknown')

    def test_change_reports_exact_target_before_after_without_touching_snapshots(self):
        result = self.f.prepare(ChartEdit(kind='horizontal_line', action='update', object_id=self.f.h['id'], price=30.8))
        candidate = chart_service.read_chart_snapshot(result['chart_session'])
        original = deepcopy(candidate)
        change = edit_change(candidate, self.f.payload)
        self.assertEqual(change['action'], 'update')
        self.assertEqual(change['before']['price'], 31)
        self.assertEqual(change['after']['price'], 30.8)
        self.assertEqual(change['before']['id'], change['after']['id'])
        self.assertEqual(change['changed_fields'], ['price'])
        self.assertTrue(change['other_ai_drawings_unchanged'])
        self.assertEqual(candidate, original)
        candidate['chartCommands'][0]['private_secret'] = 'not-for-output'
        self.assertNotIn('not-for-output', json.dumps(edit_change(candidate, self.f.payload)))

    def test_delete_retains_name_and_does_not_claim_other_objects_unchanged_if_modified(self):
        result = self.f.prepare(ChartEdit(kind='horizontal_line', action='delete', object_id=self.f.h['id']))
        candidate = chart_service.read_chart_snapshot(result['chart_session'])
        change = edit_change(candidate, self.f.payload)
        self.assertEqual(change['before']['name'], 'H')
        self.assertIsNone(change['after'])
        self.assertTrue(change['other_ai_drawings_unchanged'])
        other = next(c for c in candidate['chartCommands'] if c.get('id') == self.f.t['id'])
        other['label'] = 'changed'
        self.assertFalse(edit_change(candidate, self.f.payload)['other_ai_drawings_unchanged'])
        self.assertIsNone(edit_change({}, self.f.payload))

    def test_create_and_noop_are_not_invented_changes(self):
        result = self.f.prepare(ChartEdit(kind='horizontal_line', action='create', price=30, name='新增'))
        candidate = chart_service.read_chart_snapshot(result['chart_session'])
        change = edit_change(candidate, self.f.payload)
        self.assertIsNone(change['before'])
        self.assertEqual(change['after']['name'], '新增')
        self.assertEqual(change['after']['price'], 30)
        self.assertTrue(change['other_ai_drawings_unchanged'])
        candidate['drawing_guard']['action'] = 'update'
        candidate['drawing_guard']['object_id'] = self.f.h['id']
        self.assertEqual(edit_change(candidate, self.f.payload)['changed_fields'], [])

    def test_error_hints_do_not_retry_unknown_requests_or_choose_substitute_colors(self):
        for code in ('chart_application_unavailable', 'chart_edit_outcome_unknown'):
            self.assertEqual(error_interaction(code)['next_action'], 'check_original_candidate_status_do_not_resend')
        self.assertEqual(error_interaction('unexpected')['next_action'], 'stop_and_inspect')
        self.assertEqual(error_interaction('invalid_color')['next_action'], 'ask_user')
        self.assertEqual(error_interaction('ambiguous_drawing_id')['next_action'], 'ask_user')
        self.assertEqual(error_interaction('chart_context_revision_conflict')['next_action'], 'read_current_context')

    def test_public_feedback_is_in_text_and_structure_and_status_remains_read_only(self):
        prepared = self.f.prepare(ChartEdit(kind='horizontal_line', action='update', object_id=self.f.h['id'], price=30.8))
        with patch('server.prepare_guarded_chart_edit', return_value=prepared):
            result = asyncio.run(server.prepare_chart_edit(self.f.ref, 1, self.f.token, self.f.payload['symbol'], 'R',
                ChartEdit(kind='horizontal_line', action='update', object_id=self.f.h['id'], price=30.8)))
        self.assertEqual(result.structuredContent['interaction']['status'], 'prepared')
        self.assertEqual(result.structuredContent['change']['after']['price'], 30.8)
        self.assertEqual(json.loads(result.content[0].text.split(' · ', 1)[1]), result.structuredContent)
        before = {p: p.read_bytes() for p in self.f.runtime.rglob('*') if p.is_file()}
        with patch('server.fetch_candles', side_effect=AssertionError('no fetch')), \
             patch('chart_service.publish_chart', side_effect=AssertionError('no publish')):
            status = asyncio.run(server.get_chart_edit_status(self.f.ref, prepared['chart_session']))
        self.assertEqual(status.structuredContent['interaction']['status'], 'prepared')
        self.assertEqual(status.structuredContent['change'], result.structuredContent['change'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.f.runtime.rglob('*') if p.is_file()})
        error = server._drawing_error(server.LineError('invalid_color', '不支持此颜色'))
        self.assertTrue(error.isError)
        self.assertEqual(error.structuredContent['interaction']['next_action'], 'ask_user')
        self.assertIn('color_inputs', error.content[0].text)

    def test_other_three_families_report_updates_and_deletes_without_changing_other_objects(self):
        cases = [('trend_line', self.f.t, {'end_price': 34}, ['points']),
                 ('channel', self.f.c, {'show_midline': False}, ['show_midline']),
                 ('rectangle', self.f.r, {'upper_price': 34, 'show_fill': False}, ['show_fill', 'upper_price'])]
        revision = 0
        for kind, target, fields, changed_fields in cases:
            for action in ('update', 'delete'):
                with self.subTest(kind=kind, action=action):
                    revision += 1
                    self.f.record['revision'] = revision
                    self.f.save_context()
                    prepared = self.f.prepare(ChartEdit(kind=kind, action=action, object_id=target['id'],
                        **(fields if action == 'update' else {})), expected_revision=revision, request_id=str(revision))
                    candidate = chart_service.read_chart_snapshot(prepared['chart_session'])
                    change = edit_change(candidate, self.f.payload)
                    self.assertEqual(change['kind'], kind)
                    self.assertEqual(change['before']['id'], target['id'])
                    self.assertTrue(change['other_ai_drawings_unchanged'])
                    if action == 'delete':
                        self.assertIsNone(change['after'])
                    else:
                        self.assertEqual(change['after']['id'], target['id'])
                        self.assertEqual(change['changed_fields'], changed_fields)

    def test_missing_parent_omits_optional_diff_without_losing_prepared_protocol_fields(self):
        prepared = self.f.prepare()
        original = deepcopy(prepared)
        read = server.read_chart_snapshot
        with patch('server.read_chart_snapshot', side_effect=lambda token: None if token == self.f.token else read(token)):
            result = server._chart_edit_result(prepared).structuredContent
        self.assertNotIn('change', result)
        self.assertEqual(result['interaction']['status'], 'prepared')
        self.assertFalse(result['interaction']['completion_confirmed'])
        self.assertEqual({key: result[key] for key in prepared}, original)
        self.assertEqual(prepared, original)

    def test_foreign_context_never_receives_candidate_diff_or_changes_original_proof(self):
        prepared = self.f.prepare()
        for key, value in [('context_ref', 'x'*32), ('conversation_id', 'other'),
                           ('view_id', 'y'*32), ('expected_revision', 999)]:
            with self.subTest(key=key):
                supplied = {**prepared, key: value}
                result = server._chart_edit_result(supplied).structuredContent
                self.assertNotIn('change', result)
                self.assertEqual({name: result[name] for name in supplied}, supplied)
                self.assertFalse(result['interaction']['completion_confirmed'])


if __name__ == '__main__':
    unittest.main()
