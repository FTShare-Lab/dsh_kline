import unittest
from unittest.mock import patch

import chart_service


class WorkbenchBridgeTests(unittest.TestCase):
    def test_curated_routes_refuse_nonselected_functions_before_calculation(self):
        ta = chart_service._tool_dispatch('workbench_run_ta', {'name': 'RSI'})
        chart = chart_service._tool_dispatch('workbench_run_chart_function', {'function': 'pivot_candidates'})
        self.assertEqual(ta['error'], 'workbench_function_not_selected')
        self.assertEqual(chart['error'], 'workbench_function_not_selected')

    def test_curated_candidate_routes_reach_the_read_only_function(self):
        for function in ('channel_candidates', 'range_candidates'):
            with self.subTest(function=function), patch('tools.chart_functions.run_function', return_value={'ok': True, 'analysis_only': True}) as run:
                result = chart_service._tool_dispatch('workbench_run_chart_function', {'function': function})
                self.assertEqual(result, {'ok': True, 'analysis_only': True})
                run.assert_called_once_with(function=function)

    def test_curated_edit_route_refuses_nonselected_kind(self):
        result = chart_service._tool_dispatch('workbench_prepare_edit', {'edit': {
            'kind': 'price_sticks', 'action': 'create', 'name': 'not selected',
        }})
        self.assertEqual(result['error'], 'workbench_kind_not_selected')

    def test_clear_route_allows_delete_only_for_existing_ai_families(self):
        for kind in ('text_annotation', 'number_annotation', 'icon_annotation', 'price_sticks'):
            with self.subTest(kind=kind), patch('tools.chart_edits.prepare_chart_edit', return_value={'ok': True}) as prepare:
                result = chart_service._tool_dispatch('workbench_prepare_edit', {'edit': {
                    'kind': kind, 'action': 'delete', 'object_id': 'draw-1',
                }})
                self.assertTrue(result['ok'])
                self.assertEqual(prepare.call_args.kwargs['edit'].kind, kind)
            create = chart_service._tool_dispatch('workbench_prepare_edit', {'edit': {
                'kind': kind, 'action': 'create',
            }})
            self.assertEqual(create['error'], 'workbench_kind_not_selected')

    def test_batch_clear_route_accepts_only_delete_without_object_id(self):
        with patch('tools.chart_edits.prepare_chart_edit', return_value={'ok': True}) as prepare:
            result = chart_service._tool_dispatch('workbench_prepare_edit', {'edit': {
                'kind': 'all_drawings', 'action': 'delete',
            }})
            self.assertTrue(result['ok'])
            self.assertEqual(prepare.call_args.kwargs['edit'].kind, 'all_drawings')
        create = chart_service._tool_dispatch('workbench_prepare_edit', {'edit': {
            'kind': 'all_drawings', 'action': 'create',
        }})
        self.assertEqual(create['error'], 'workbench_kind_not_selected')


if __name__ == '__main__':
    unittest.main()
