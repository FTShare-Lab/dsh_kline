import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError
import chart_service
import server
from tools.chart_context import read_chart_context
from tools.chart_edits import ChartEdit, prepare_chart_edit, snapshot_inventory
from tools.chart_applications import read_edit_status
from tools.lines import LineError, edit_horizontal_line
from tools.trend_lines import edit_trend_line
from tools.channels import edit_channel
from tools.rectangles import edit_rectangle
from test_channels import chart


class GuardedEditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.runtime = Path(self.directory.name)
        for name, value in [("RUNTIME_DIR", self.runtime), ("HOST_PROCESS_ID", 4242)]:
            p = patch.object(chart_service, name, value); p.start(); self.addCleanup(p.stop)
        p = patch("tools.chart_context.time.time", return_value=100); p.start(); self.addCleanup(p.stop)
        self.ref, self.token = "a" * 32, "b" * 32
        self.payload = chart()
        self.payload["adjust"] = "none"
        self.payload, self.h = edit_horizontal_line(self.payload, "create", price=31, name="H")
        self.payload, self.t = edit_trend_line(self.payload, "create", start_time="2026-09-10", start_price=30,
                                             end_time="2026-09-15", end_price=33)
        self.payload, self.c = edit_channel(self.payload, "create", start_time="2026-09-10", start_price=30,
            end_time="2026-09-15", end_price=33, parallel_time="2026-09-11", parallel_price=32)
        self.payload, self.r = edit_rectangle(self.payload, "create", start_time="2026-09-10", end_time="2026-09-15",
                                              lower_price=30, upper_price=33)
        self.record = {"ok": True, "context_ref": self.ref, "host_process_id": 4242,
            "conversation_id": "A", "view_id": "c" * 32, "revision": 1, "observed_at_ms": 100000,
            "active": True, "ambiguous": False, "state": {"schema_version": 1, "state": "ready",
                "symbol": self.payload["symbol"], "interval": "day", "interval_value": 1, "adjust": "none", "range_key": "custom",
                "source_chart_session": self.token, "candles": deepcopy(self.payload["chartCommands"][0]["rows"]),
                "visible_range": {"available": True, "index_from": 1, "index_to_exclusive": 3},
                "drawings": snapshot_inventory(self.payload), "indicators": ["vol"], "selection": None}}
        self.path = self.runtime / "views" / "4242" / (self.ref + ".json")
        self.published = []
        self.save_context(); self.save_snapshot(self.token, self.payload)

    def save_context(self): chart_service._atomic_runtime_json(self.path, self.record)

    def save_snapshot(self, token, payload):
        chart_service._atomic_runtime_json(self.runtime / "sessions" / (token + ".json"),
            {"ok": True, "host_process_id": 4242, "session": token, "payload": payload})

    def publish(self, payload):
        token = str(len(self.published) + 1).zfill(32)
        self.published.append(deepcopy(payload)); self.save_snapshot(token, payload)
        return token, "fixture"

    def prepare(self, edit=None, **changes):
        arguments = {"context_ref": self.ref, "expected_revision": 1, "chart_session": self.token,
            "symbol": self.payload["symbol"], "request_id": "R", "edit": edit or ChartEdit(kind="horizontal_line", action="create", price=32),
            "publish": self.publish}
        arguments.update(changes)
        return prepare_chart_edit(**arguments)

    def assert_code(self, code, callback):
        with self.assertRaises(LineError) as error: callback()
        self.assertEqual(error.exception.code, code)

    def test_prepares_without_changing_source_context_or_other_shapes(self):
        before = self.path.read_text(); source = deepcopy(self.payload)
        result = self.prepare(ChartEdit(kind="horizontal_line", action="update", object_id=self.h["id"], price=29.5, name="完整观察线", color="绿色"))
        self.assertEqual(result["operation_status"], "prepared"); self.assertEqual(result["apply_status"], "not_requested")
        self.assertFalse(result["render_verified"]); self.assertEqual(result["object"]["id"], self.h["id"])
        self.assertEqual(result["object"]["label"], "完整观察线"); self.assertEqual(result["object"]["color"], "success")
        self.assertEqual(result["drawing_guard"]["conversation_id"], "A")
        self.assertEqual(result["drawing_guard"]["view_id"], "c" * 32)
        self.assertEqual(self.path.read_text(), before); self.assertEqual(chart_service.read_chart_snapshot(self.token), source)
        self.assertEqual(self.published[0]["chartCommands"][:2], source["chartCommands"][:2])
        self.assertEqual(self.published[0]["chartCommands"][3:], source["chartCommands"][3:])

    def test_batch_clear_is_one_guarded_candidate_for_current_interval_only(self):
        weekly = deepcopy(self.payload["chartCommands"][1])
        weekly["id"] = "weekly-line"
        weekly["interval"] = "week"
        self.payload["chartCommands"].append(weekly)
        self.record["state"]["drawings"] = snapshot_inventory(self.payload)
        self.save_context(); self.save_snapshot(self.token, self.payload)
        before = deepcopy(self.payload)
        result = self.prepare(ChartEdit(kind="all_drawings", action="delete"))
        self.assertEqual(result["object"]["deleted_count"], 4)
        self.assertEqual([cmd["id"] for cmd in self.published[0]["chartCommands"] if cmd.get("id")], ["auto", "weekly-line"])
        self.assertEqual(self.payload, before)
        self.assertEqual(result["drawing_guard"]["kind"], "all_drawings")
        self.assertEqual(result["apply_status"], "not_requested")
        self.assertEqual(read_edit_status(self.ref, result["chart_session"])["apply_status"], "not_requested")

    def test_batch_clear_refuses_wrong_action_and_stale_observation(self):
        self.assert_code("invalid_object_identity", lambda: self.prepare(ChartEdit(kind="all_drawings", action="create")))
        self.assert_code("invalid_object_identity", lambda: self.prepare(ChartEdit(kind="all_drawings", action="delete", object_id=self.h["id"])))
        self.record["revision"] = 2; self.save_context()
        self.assert_code("chart_context_revision_conflict", lambda: self.prepare(ChartEdit(kind="all_drawings", action="delete")))
        self.assertEqual(self.published, [])

    def test_same_request_replays_same_token_and_normalizes_color_aliases(self):
        first = self.prepare(ChartEdit(kind="horizontal_line", action="create", price=32, name=" A ", color="绿色"))
        second = self.prepare(ChartEdit(kind="horizontal_line", action="create", price=32, name="A", color="success"))
        self.assertEqual(first["chart_session"], second["chart_session"]); self.assertTrue(second["replayed"])
        self.assertEqual(first["object"]["id"], second["object"]["id"]); self.assertEqual(len(self.published), 1)
        self.assert_code("request_conflict", lambda: self.prepare(ChartEdit(kind="horizontal_line", action="create", price=33)))
        self.assertEqual(len(self.published), 1)

    def test_different_requests_cannot_branch_from_consumed_revision(self):
        self.prepare()
        self.assert_code("chart_edit_revision_consumed", lambda: self.prepare(request_id="other"))
        self.assertEqual(len(self.published), 1)

    def test_stale_revision_period_symbol_range_rows_and_ai_state_rejected(self):
        original = deepcopy(self.record)
        cases = [("revision", "chart_context_revision_conflict"), ("symbol", "chart_snapshot_not_aligned"),
                 ("period", "chart_snapshot_not_aligned"), ("range", "chart_snapshot_not_aligned"),
                 ("adjust", "chart_snapshot_not_aligned"), ("unknown_adjust", "chart_snapshot_not_aligned"),
                 ("rows", "chart_snapshot_not_aligned"), ("drawings", "chart_snapshot_not_aligned")]
        for change, code in cases:
            self.record = deepcopy(original)
            if change == "revision": self.record["revision"] = 2
            if change == "symbol": self.record["state"]["symbol"] = "OTHER.X"
            if change == "period": self.record["state"]["interval"] = "week"
            if change == "adjust": self.record["state"]["adjust"] = "qfq"
            if change == "unknown_adjust": self.record["state"]["adjust"] = None
            if change == "range": self.record["state"]["candles"] = self.record["state"]["candles"][1:]
            if change == "rows": self.record["state"]["candles"][0]["volume"] += 1
            if change == "drawings": self.record["state"]["drawings"][0]["price"] += 1
            self.save_context(); self.assert_code(code, self.prepare)
        self.assertEqual(self.published, [])

    def test_inactive_ambiguous_stale_loading_and_missing_source_rejected(self):
        original = deepcopy(self.record)
        for changes, code in [({"active": False}, "chart_view_inactive"), ({"ambiguous": True}, "ambiguous_chart_views"),
                              ({"observed_at_ms": 9000}, "chart_context_stale")]:
            self.record = {**original, **changes}; self.save_context(); self.assert_code(code, self.prepare)
        self.record = deepcopy(original); self.record["state"]["state"] = "loading"; self.save_context()
        self.assert_code("chart_edit_context_not_ready", self.prepare)
        self.record = deepcopy(original); self.record["state"]["source_chart_session"] = None; self.save_context()
        self.assert_code("chart_snapshot_not_aligned", self.prepare)
        self.assertEqual(self.published, [])

    def test_manual_targets_and_ambiguous_ai_ids_rejected(self):
        self.record["state"]["drawings"].append({"id": "manual:X", "kind": "horizontal_line", "origin": "manual", "price": 32})
        self.save_context()
        self.assert_code("drawing_not_editable", lambda: self.prepare(ChartEdit(kind="horizontal_line", action="delete", object_id="manual:X")))
        self.record["state"]["drawings"].append(deepcopy(self.record["state"]["drawings"][0])); self.save_context()
        self.assert_code("ambiguous_drawing_id", self.prepare); self.assertEqual(self.published, [])

    def test_changes_during_preparation_do_not_publish(self):
        initial = read_chart_context(self.ref, candle_scope="loaded", limit=4000)
        for field, value in [("revision", 2), ("visible_range", {"available": False}), ("selection", {"kind": "candle", "time": 1})]:
            changed = deepcopy(initial); changed[field] = value
            with patch("tools.chart_edits.read_chart_context", side_effect=[initial, changed]):
                self.assert_code("chart_context_revision_conflict", self.prepare)
        self.assertEqual(self.published, [])

    def test_invalid_edit_does_not_consume_revision(self):
        self.assert_code("invalid_price_bounds", lambda: self.prepare(ChartEdit(kind="rectangle", action="update", object_id=self.r["id"], lower_price=34)))
        self.assert_code("invalid_edit_fields", lambda: self.prepare(ChartEdit(kind="channel", action="update", object_id=self.c["id"], price=32)))
        self.assert_code("invalid_edit_fields", lambda: self.prepare(ChartEdit(kind="horizontal_line", action="delete", object_id=self.h["id"], name="x")))
        self.assert_code("invalid_object_identity", lambda: self.prepare(ChartEdit(kind="horizontal_line", action="create", object_id="x", price=32)))
        self.assertTrue(self.prepare()["ok"]); self.assertEqual(len(self.published), 1)

    def test_four_families_update_with_stable_ids_and_no_fetch(self):
        edits = [ChartEdit(kind="horizontal_line", action="delete", object_id=self.h["id"]),
                 ChartEdit(kind="trend_line", action="update", object_id=self.t["id"], end_price=34),
                 ChartEdit(kind="channel", action="update", object_id=self.c["id"], show_midline=False),
                 ChartEdit(kind="rectangle", action="update", object_id=self.r["id"], show_fill=False)]
        for index, edit in enumerate(edits, 1):
            self.record["revision"] = index; self.save_context()
            result = self.prepare(edit, expected_revision=index, request_id="R" + str(index))
            self.assertEqual(result["object"]["id"], edit.object_id)
        self.assertEqual(len(self.published), 4)

    def test_publication_failure_stops_retries_even_with_different_request_id(self):
        def uncertain(payload):
            self.publish(payload); raise OSError("after publish")
        self.assert_code("chart_edit_outcome_unknown", lambda: self.prepare(publish=uncertain))
        self.assert_code("chart_edit_outcome_unknown", self.prepare)
        self.assert_code("chart_edit_revision_consumed", lambda: self.prepare(request_id="other"))
        self.assertEqual(len(self.published), 1)
        self.assertEqual(self.record["state"]["drawings"], snapshot_inventory(self.payload))

    def test_result_journal_failure_keeps_preparing_record_and_never_republishes(self):
        atomic = chart_service._atomic_runtime_json; journal_writes = 0
        def fail_final_record(destination, document):
            nonlocal journal_writes
            if destination.name == "journal.json":
                journal_writes += 1
                if journal_writes > 1: raise OSError("result record unavailable")
            return atomic(destination, document)
        with patch("chart_service._atomic_runtime_json", side_effect=fail_final_record):
            self.assert_code("chart_edit_outcome_unknown", self.prepare)
        self.assert_code("chart_edit_outcome_unknown", self.prepare)
        self.assertEqual(len(self.published), 1)
        journal = self.runtime / "edits" / "4242" / self.ref / "journal.json"
        self.assertEqual(json.loads(journal.read_text())["entries"][0]["status"], "preparing")

    def test_journal_replay_uses_disk_and_lock_blocks_another_worker(self):
        def concurrent(payload):
            self.assert_code("chart_edit_busy", lambda: self.prepare(request_id="parallel"))
            return self.publish(payload)
        first = self.prepare(publish=concurrent)
        second = self.prepare(publish=lambda _: self.fail("must not publish again"))
        self.assertEqual(first["chart_session"], second["chart_session"])
        journal = self.runtime / "edits" / "4242" / self.ref / "journal.json"
        self.assertEqual(json.loads(journal.read_text())["entries"][0]["status"], "prepared")
        self.assertFalse((journal.parent / "prepare.lock").exists())

    def test_corrupt_journal_never_resets_retry_history(self):
        journal = self.runtime / "edits" / "4242" / self.ref / "journal.json"
        chart_service._atomic_runtime_json(journal, {"entries": "corrupt"})
        self.assert_code("chart_edit_journal_invalid", self.prepare)
        self.assertEqual(json.loads(journal.read_text()), {"entries": "corrupt"}); self.assertEqual(self.published, [])

    def test_capacity_does_not_discard_history_or_publish(self):
        journal = self.runtime / "edits" / "4242" / self.ref / "journal.json"
        history = {"entries": [{"request_id": "old" + str(i), "revision": i + 2,
                               "fingerprint": "0" * 64, "status": "preparing"} for i in range(64)]}
        chart_service._atomic_runtime_json(journal, history)
        self.assert_code("chart_edit_capacity", self.prepare)
        self.assertEqual(json.loads(journal.read_text()), history); self.assertEqual(self.published, [])

    def test_interrupted_preparing_record_never_republishes(self):
        self.prepare()
        journal = self.runtime / "edits" / "4242" / self.ref / "journal.json"
        saved = json.loads(journal.read_text()); saved["entries"][0]["status"] = "preparing"
        saved["entries"][0].pop("result"); chart_service._atomic_runtime_json(journal, saved)
        self.assert_code("chart_edit_outcome_unknown", self.prepare)
        self.assert_code("chart_edit_revision_consumed", lambda: self.prepare(request_id="new"))
        self.assertEqual(len(self.published), 1)

    def test_prepared_candidates_cannot_bypass_guards_through_legacy_mutations(self):
        result = self.prepare()
        with patch("server.publish_chart", side_effect=AssertionError("no bypass publication")):
            blocked = asyncio.run(server.update_horizontal_line(result["chart_session"], self.payload["symbol"], self.h["id"], price=30))
        self.assertTrue(blocked.isError); self.assertEqual(blocked.structuredContent["error"], "prepared_chart_not_applied")
        self.record["revision"] = 2; self.record["state"]["source_chart_session"] = result["chart_session"]
        self.record["state"]["drawings"] = snapshot_inventory(self.published[0]); self.save_context()
        self.assert_code("prepared_chart_not_applied", lambda: self.prepare(expected_revision=2, request_id="next", chart_session=result["chart_session"]))

    def test_create_and_delete_all_families_are_guarded(self):
        creates = [ChartEdit(kind="trend_line", action="create", start_time="2026-09-10", start_price=30,
                            end_time="2026-09-15", end_price=33),
                   ChartEdit(kind="channel", action="create", start_time="2026-09-10", start_price=30,
                            end_time="2026-09-15", end_price=33, parallel_time="2026-09-11", parallel_price=32),
                   ChartEdit(kind="rectangle", action="create", start_time="2026-09-10", end_time="2026-09-15", lower_price=30, upper_price=33)]
        deletes = [ChartEdit(kind=kind, action="delete", object_id=obj["id"]) for kind, obj in
                   [("horizontal_line", self.h), ("trend_line", self.t), ("channel", self.c), ("rectangle", self.r)]]
        for revision, edit in enumerate(creates + deletes, 1):
            self.record["revision"] = revision; self.save_context()
            result = self.prepare(edit, expected_revision=revision, request_id="R" + str(revision))
            inventory = snapshot_inventory(self.published[-1])
            self.assertEqual(any(d["id"] == result["object"]["id"] for d in inventory), edit.action == "create")

    def test_truncated_loaded_data_is_not_used_to_prepare(self):
        row = self.record["state"]["candles"][0]
        self.record["state"]["candles"] = [{**row, "time": row["time"] + i} for i in range(4001)]
        self.save_context(); self.assert_code("chart_edit_context_not_ready", self.prepare)
        self.assertEqual(self.published, [])

    def test_minute_unknown_or_different_granularity_rejected(self):
        self.payload["interval"] = "minute"; self.payload["interval_value"] = 5
        self.record["state"]["interval"] = "minute"
        # Update fallback interval fields so the minute check is the rejection reason.
        self.record["state"]["drawings"] = snapshot_inventory(self.payload)
        self.save_snapshot(self.token, self.payload)
        for step in [None, 1]:
            self.record["state"]["interval_value"] = step; self.save_context()
            self.assert_code("chart_snapshot_not_aligned", self.prepare)
        self.record["state"]["interval_value"] = 5; self.save_context(); self.assertTrue(self.prepare()["ok"])

    def test_mcp_contract_is_preparation_and_schema_rejects_wrong_types(self):
        with patch("chart_service.publish_chart", side_effect=self.publish), patch("server.fetch_candles", side_effect=AssertionError("no market fetch")):
            result = asyncio.run(server.prepare_chart_edit(self.ref, 1, self.token, self.payload["symbol"], "R",
                ChartEdit(kind="horizontal_line", action="create", price=32)))
        self.assertTrue(result.structuredContent["ok"])
        self.assertEqual(result.structuredContent["apply_status"], "not_requested")
        tools = asyncio.run(server.mcp.list_tools()); tool = next(t for t in tools if t.name == "prepare_chart_edit")
        self.assertEqual(set(tool.inputSchema["required"]), {"context_ref", "expected_revision", "chart_session", "symbol", "request_id", "edit"})
        for wrong in [{"price": True}, {"price": float("inf")}, {"unknown": 1}, {"show_fill": 1}]:
            with self.assertRaises(ValidationError): ChartEdit(kind="horizontal_line", action="create", **wrong)

    def test_actual_chart_service_candidate_retains_guard_and_original_snapshot(self):
        service = chart_service.ChartService("127.0.0.1", 0)
        self.addCleanup(service.httpd.server_close); self.addCleanup(service.httpd.shutdown)
        result = self.prepare(publish=service.publish)
        candidate = chart_service.read_chart_snapshot(result["chart_session"])
        self.assertEqual(candidate["drawing_guard"]["expected_revision"], 1)
        self.assertTrue(candidate["drawing_guard"]["requires_live_apply"])
        self.assertEqual(chart_service.read_chart_snapshot(self.token), self.payload)


if __name__ == "__main__": unittest.main()
