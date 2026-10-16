from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import chart_service
import server
from tools.chart_sources import require_confirmed_view_source
from tools.chart_context import read_chart_context
from tools.chart_edits import ChartEdit
import test_chart_edits as fixtures


class CurrentViewSourceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.GuardedEditTests("test_prepares_without_changing_source_context_or_other_shapes")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.guard = {"protocol": "browser-source-v1", "context_ref": self.f.ref,
            "conversation_id": "A", "view_id": self.f.record["view_id"], "chart_session": self.f.token, "expected_revision": 1}
        self.f.payload["view_source_guard"] = self.guard
        self.f.save_snapshot(self.f.token, self.f.payload)
        self.proof = {"host_process_id": 4242, "context_ref": self.f.ref, "conversation_id": "A",
            "view_id": self.f.record["view_id"], "chart_session": self.f.token, "status": "confirmed"}
        self.path = self.f.runtime / "sources" / "4242" / self.f.ref / (self.f.token + ".json")
        chart_service._atomic_runtime_json(self.path, self.proof)

    def test_only_confirmed_owned_source_can_prepare_without_market_fetch(self):
        with patch("server.fetch_candles", side_effect=AssertionError("no fetch")):
            for status in ("offered", "rejected", "missing"):
                if status == "missing": self.path.unlink()
                else: chart_service._atomic_runtime_json(self.path, {**self.proof, "status": status})
                self.f.assert_code("chart_source_not_confirmed", self.f.prepare)
            chart_service._atomic_runtime_json(self.path, self.proof)
            for key, value in (("host_process_id", 4243), ("conversation_id", "B"), ("view_id", "z" * 32), ("chart_session", "z" * 32)):
                chart_service._atomic_runtime_json(self.path, {**self.proof, key: value})
                self.f.assert_code("chart_source_not_confirmed", self.f.prepare)
            chart_service._atomic_runtime_json(self.path, self.proof)
            result = self.f.prepare()
        self.assertEqual(result["operation_status"], "prepared")
        child = chart_service.read_chart_snapshot(result["chart_session"])
        self.assertNotIn("view_source_guard", child)
        self.assertEqual(child["drawing_guard"]["chart_session"], self.f.token)
        self.assertEqual(child["chartCommands"][:2], self.f.payload["chartCommands"][:2])

    def test_confirmed_source_does_not_bypass_exact_alignment_revision_or_manual_target_guards(self):
        original = deepcopy(self.f.record)
        for change in ("rows", "period", "revision", "inventory"):
            self.f.record = deepcopy(original)
            if change == "rows": self.f.record["state"]["candles"][0]["volume"] += 1
            if change == "period": self.f.record["state"]["interval"] = "week"
            if change == "revision": self.f.record["revision"] = 2
            if change == "inventory": self.f.record["state"]["drawings"] = []
            self.f.save_context()
            self.f.assert_code("chart_context_revision_conflict" if change == "revision" else "chart_snapshot_not_aligned", self.f.prepare)
        self.assertEqual(self.f.published, [])

    def test_source_guard_is_not_a_permission_for_old_snapshot_mutation_or_foreign_conversation(self):
        result = server._horizontal_line_operation("create", self.f.token, self.f.payload["symbol"], price=32)
        self.assertTrue(result.isError); self.assertEqual(result.structuredContent["error"], "current_view_source_requires_guarded_edit")
        context = read_chart_context(self.f.ref, candle_scope="loaded", limit=4000)
        context["conversation_id"] = "B"
        self.f.assert_code("chart_source_not_confirmed", lambda: require_confirmed_view_source(self.f.payload, context, self.f.token))
        self.assertEqual(self.f.published, [])

    def test_forged_aligned_diagnostic_never_bypasses_actual_source_proof_or_exact_candles(self):
        self.f.record["source_status"] = {"schema_version": 1, "reason": "source_matches_view", "edit_authorized": True}
        self.f.save_context()
        chart_service._atomic_runtime_json(self.path, {**self.proof, "status": "offered"})
        self.f.assert_code("chart_source_not_confirmed", self.f.prepare)
        chart_service._atomic_runtime_json(self.path, self.proof)
        self.f.record["state"]["candles"][0]["volume"] += 1
        self.f.save_context()
        self.f.assert_code("chart_snapshot_not_aligned", self.f.prepare)
        self.assertEqual(self.f.published, [])

    def test_other_period_channel_and_rectangle_stay_immutable_but_new_current_period_shape_is_allowed(self):
        for command in self.f.payload["chartCommands"]:
            if command["type"] in ("DRAW_AGENT_CHANNEL", "DRAW_AGENT_RECTANGLE"): command["interval"] = "week"
        self.f.save_snapshot(self.f.token, self.f.payload)
        for drawing in self.f.record["state"]["drawings"]:
            if drawing["kind"] in ("channel", "rectangle"): drawing["interval"] = "week"
        self.f.save_context()
        before = json.dumps(self.f.payload, sort_keys=True)
        for kind, object_id in (("channel", self.f.c["id"]), ("rectangle", self.f.r["id"])):
            for action in ("update", "delete"):
                fields = {"color": "orange"} if action == "update" else {}
                edit = ChartEdit(kind=kind, action=action, object_id=object_id, **fields)
                self.f.assert_code("drawing_interval_mismatch", lambda: self.f.prepare(edit))
        prepared = self.f.prepare(ChartEdit(kind="horizontal_line", action="create", price=31.5))
        self.assertEqual(prepared["operation_status"], "prepared")
        self.assertEqual(json.dumps(chart_service.read_chart_snapshot(self.f.token), sort_keys=True), before)


if __name__ == "__main__": unittest.main()
