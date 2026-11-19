from copy import deepcopy
import unittest
from unittest.mock import patch

import chart_service
import test_chart_edits as fixtures
from tools.chart_edits import ChartEdit, snapshot_inventory
from tools.chart_applications import application_path, read_edit_status


class DrawingTransactionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.GuardedEditTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.record["guarded_apply_supported"] = True
        self.f.save_context()

    def apply_fixture(self, prepared):
        token = prepared["chart_session"]
        chart_service._atomic_runtime_json(application_path(self.f.ref, token), {
            "host_process_id": 4242, "context_ref": self.f.ref, "candidate_chart_session": token,
            "status": "applied", "confirmed_chart_session": token, "conversation_id": "A",
            "view_id": "c" * 32, "request_id": prepared["request_id"], "created_at_ms": 100000})
        payload = chart_service.read_chart_snapshot(token)
        self.f.record["state"].update(drawings=snapshot_inventory(payload), source_chart_session=token)
        self.f.record["revision"] += 1
        self.f.save_context()
        return payload

    def test_batch_is_one_candidate_and_preserves_source_until_applied(self):
        source = deepcopy(self.f.payload)
        edit = ChartEdit(kind="drawing_batch", action="create", edits=[
            {"kind": "horizontal_line", "action": "create", "price": 29.0},
            {"kind": "horizontal_line", "action": "create", "price": 34.0}])
        result = self.f.prepare(edit)
        self.assertEqual(len(self.f.published), 1)
        self.assertEqual(len(result["object"]["objects"]), 2)
        self.assertNotEqual(*[o["id"] for o in result["object"]["objects"]])
        self.assertEqual(chart_service.read_chart_snapshot(self.f.token), source)
        self.assertEqual(self.f.prepare(edit)["chart_session"], result["chart_session"])
        self.assertEqual(read_edit_status(self.f.ref, result["chart_session"])["apply_status"], "not_requested")

    def test_invalid_second_edit_publishes_nothing(self):
        edit = ChartEdit(kind="drawing_batch", action="create", edits=[
            {"kind": "horizontal_line", "action": "create", "price": 29.0},
            {"kind": "trend_line", "action": "create", "start_time": "2026-09-10"}])
        with self.assertRaises(Exception):
            self.f.prepare(edit)
        self.assertEqual(self.f.published, [])

    def test_batch_rejects_nested_or_duplicate_targets(self):
        for children in ([{"kind": "drawing_batch", "action": "create", "edits": [{"kind": "horizontal_line", "action": "create", "price": 29.0}]}],
                         [{"kind": "horizontal_line", "action": "update", "object_id": self.f.h["id"], "price": p} for p in (29.0, 30.0)]):
            with self.assertRaises(Exception):
                self.f.prepare(ChartEdit(kind="drawing_batch", action="create", edits=children))
        self.assertEqual(self.f.published, [])

    def test_undo_and_redo_restore_only_drawing_commands(self):
        created = self.f.prepare(ChartEdit(kind="horizontal_line", action="create", price=29.0))
        after = self.apply_fixture(created)
        undo = self.f.prepare(ChartEdit(kind="drawing_history", action="update", history_session=created["chart_session"], history_direction="undo"),
                              chart_session=created["chart_session"], expected_revision=2, request_id="undo")
        restored = self.apply_fixture(undo)
        self.assertEqual(snapshot_inventory(restored), snapshot_inventory(self.f.payload))
        self.assertEqual(restored["chartCommands"][0], after["chartCommands"][0])
        redo = self.f.prepare(ChartEdit(kind="drawing_history", action="create", history_session=created["chart_session"], history_direction="redo"),
                              chart_session=undo["chart_session"], expected_revision=3, request_id="redo")
        self.assertEqual(snapshot_inventory(chart_service.read_chart_snapshot(redo["chart_session"])), snapshot_inventory(after))

    def test_unconfirmed_or_changed_drawing_history_cannot_overwrite(self):
        created = self.f.prepare(ChartEdit(kind="horizontal_line", action="create", price=29.0))
        edit = ChartEdit(kind="drawing_history", action="create", history_session=created["chart_session"], history_direction="undo")
        from tools.drawing_history import restore_drawings
        context = {**self.f.record["state"], "context_ref": self.f.ref, "conversation_id": "A", "view_id": "c" * 32}
        self.f.assert_code("chart_application_unavailable", lambda: restore_drawings(self.f.payload, context, created["chart_session"], "undo"))
        self.apply_fixture(created)
        # A later confirmed edit must not be overwritten by undoing an older one.
        updated = self.f.prepare(ChartEdit(kind="horizontal_line", action="update", object_id=self.f.h["id"], price=28.0),
                                 chart_session=created["chart_session"], expected_revision=2, request_id="later")
        self.apply_fixture(updated)
        self.f.assert_code("drawing_history_conflict", lambda: self.f.prepare(edit, chart_session=updated["chart_session"], expected_revision=3, request_id="changed"))

    def test_history_keeps_fresh_metadata_but_rejects_other_data_sources(self):
        from tools.drawing_restore import restore_drawing_commands
        before = deepcopy(self.f.payload)
        before["data_meta"] = {"source": "ftshare", "fetched_at": 1}
        from tools.lines import edit_horizontal_line
        after, _ = edit_horizontal_line(before, "update", line_id=self.f.h["id"], price=29.0)
        current = deepcopy(after)
        current["data_meta"]["fetched_at"] = 2
        restored, _ = restore_drawing_commands(current, before, after, "day", "undo")
        self.assertEqual(restored["data_meta"]["fetched_at"], 2)
        self.assertEqual(snapshot_inventory(restored), snapshot_inventory(before))
        current["data_meta"]["source"] = "tencent_free"
        self.f.assert_code("drawing_history_binding_changed", lambda: restore_drawing_commands(current, before, after, "day", "undo"))


def test_history_action_contract_keeps_legacy_create_but_not_deletion_or_batch_update():
    from tools.chart_edits import edit_parameters
    for action in ("create", "update"):
        assert edit_parameters(ChartEdit(kind="drawing_history", action=action, history_session="a"*32, history_direction="undo"))["history_direction"] == "undo"
    import pytest
    from tools.lines import LineError
    with pytest.raises(LineError):
        edit_parameters(ChartEdit(kind="drawing_history", action="delete", history_session="a"*32, history_direction="undo"))
    with pytest.raises(LineError):
        edit_parameters(ChartEdit(kind="drawing_batch", action="update", edits=[{"kind":"horizontal_line","action":"create","price":1}]))
