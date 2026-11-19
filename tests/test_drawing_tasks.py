import unittest
from unittest.mock import patch

import test_chart_edits as fixtures
from tools.drawing_tasks import draw_many
from tools.lines import LineError


class DrawingTaskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = fixtures.GuardedEditTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    async def test_one_task_analyzes_two_tools_and_prepares_one_atomic_batch(self):
        candidates = {"result_ref": "d" * 64, "summary": {"candidates": [{"anchors": []}]}}
        prepared = {"chart_session": "e" * 32, "object": {"objects": [{"id": "ABC"}, {"id": "CH"}]}}
        with patch("tools.drawing_tasks.run_function", return_value=candidates) as analyze, \
             patch("tools.drawing_tasks.prepare_chart_edit", return_value=prepared) as prepare, \
             patch("tools.drawing_tasks.request_chart_apply", return_value={"apply_status": "applied"}) as apply:
            args = (self.f.ref, self.f.payload["symbol"], "task-1", [{"tool": "abc"}, {"tool": "channel", "direction": "descending"}])
            result = await draw_many(*args)
            self.assertEqual(result["status"], "applied")
            self.assertEqual([i["object_id"] for i in result["items"]], ["ABC", "CH"])
            self.assertEqual(analyze.call_count, 2)
            self.assertEqual(prepare.call_count, 1)
            self.assertEqual(prepare.call_args.kwargs["edit"].kind, "drawing_batch")
            self.assertEqual(len(prepare.call_args.kwargs["edit"].edits), 2)
            self.assertTrue((await draw_many(*args))["replayed"])
            self.assertEqual(apply.call_count, 1)
            self.assertEqual(analyze.call_count, 2)

    async def test_absent_candidate_does_not_prevent_other_tool_or_force_geometry(self):
        analyses = [{"result_ref": "d" * 64, "summary": {"candidates": []}},
                    {"result_ref": "f" * 64, "summary": {"candidates": [{}]}}]
        with patch("tools.drawing_tasks.run_function", side_effect=analyses), \
             patch("tools.drawing_tasks.prepare_chart_edit", return_value={"chart_session": "e" * 32, "object": {"objects": [{"id": "CH"}]}}) as prepare, \
             patch("tools.drawing_tasks.request_chart_apply", return_value={"apply_status": "applied"}):
            result = await draw_many(self.f.ref, self.f.payload["symbol"], "mixed", [{"tool": "abc"}, {"tool": "channel"}])
            self.assertEqual([i["status"] for i in result["items"]], ["no_candidate", "applied"])
            self.assertEqual(len(prepare.call_args.kwargs["edit"].edits), 1)

    async def test_pending_task_reuses_exact_candidate_and_can_be_checked_without_reanalysis(self):
        with patch("tools.drawing_tasks.run_function", return_value={"result_ref": "d" * 64, "summary": {"candidates": [{}]}}) as analyze, \
             patch("tools.drawing_tasks.prepare_chart_edit", return_value={"chart_session": "e" * 32, "object": {"objects": [{"id": "ABC"}]}}), \
             patch("tools.drawing_tasks.request_chart_apply", side_effect=[{"apply_status": "queued"}, {"apply_status": "applied"}]):
            args = (self.f.ref, self.f.payload["symbol"], "pending", [{"tool": "abc"}])
            first = await draw_many(*args, wait_ms=0)
            self.assertFalse(first["chart_modified"])
            second = await draw_many(*args, wait_ms=0)
            self.assertEqual(first["candidate_chart_session"], second["candidate_chart_session"])
            self.assertEqual(second["items"][0]["status"], "applied")
            self.assertEqual(analyze.call_count, 1)

    async def test_wrong_instrument_and_reused_request_with_different_intent_are_rejected(self):
        with self.assertRaises(LineError) as error:
            await draw_many(self.f.ref, "WRONG.US", "wrong", [{"tool": "abc"}])
        self.assertEqual(error.exception.code, "drawing_task_symbol_changed")
        with patch("tools.drawing_tasks.run_function", return_value={"summary": {"candidates": []}}):
            await draw_many(self.f.ref, self.f.payload["symbol"], "empty", [{"tool": "abc"}])
            with self.assertRaises(LineError) as error:
                await draw_many(self.f.ref, self.f.payload["symbol"], "empty", [{"tool": "channel"}])
            self.assertEqual(error.exception.code, "request_conflict")
