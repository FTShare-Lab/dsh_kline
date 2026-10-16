import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import chart_service
import server
from tools.chart_applications import request_chart_apply, read_application, application_status, read_edit_status, confirmed_source
from tools.chart_edits import ChartEdit, snapshot_inventory
from tools.lines import LineError
import test_chart_edits as fixtures


class ChartApplicationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GuardedEditTests("test_prepares_without_changing_source_context_or_other_shapes")
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture
        self.f.record["guarded_apply_supported"] = True; self.f.save_context()
        self.prepared = self.f.prepare()
        self.candidate = self.prepared["chart_session"]

    def queue(self): return request_chart_apply(self.f.ref, self.candidate)
    def record_path(self):
        return self.f.runtime / "edits" / "4242" / self.f.ref / "applications" / (self.candidate + ".json")

    def test_prepared_status_is_read_only_and_does_not_wait_or_grant_application_authority(self):
        before = {p.relative_to(self.f.runtime): p.read_bytes() for p in self.f.runtime.rglob("*") if p.is_file()}
        with patch("server.fetch_candles", side_effect=AssertionError("no fetch")), patch("chart_service.publish_chart", side_effect=AssertionError("no publish")), \
             patch("server.asyncio.sleep", side_effect=AssertionError("prepared must not wait")), \
             patch("tools.chart_applications.read_chart_context", side_effect=AssertionError("not current view proof")):
            result = asyncio.run(server.get_chart_edit_status(self.f.ref, self.candidate, wait_ms=5000)).structuredContent
        self.assertEqual(result["operation_status"], "prepared")
        self.assertEqual(result["apply_status"], "not_requested")
        self.assertEqual(result["candidate_chart_session"], self.candidate)
        self.assertEqual(result["confirmation_scope"], "not_confirmed")
        for key in ("render_verified", "current_view_verified", "edit_authorized", "application_record_present"):
            self.assertFalse(result[key])
        self.assertTrue(result["record_is_historical"])
        self.assertNotIn("drawing_guard", result); self.assertNotIn("parameters", result)
        self.assertEqual(before, {p.relative_to(self.f.runtime): p.read_bytes() for p in self.f.runtime.rglob("*") if p.is_file()})
        self.assertFalse(confirmed_source(chart_service.read_chart_snapshot(self.candidate), self.f.record, self.candidate))
        self.f.assert_code("chart_application_unavailable", lambda: read_application(self.f.ref, self.candidate))

    def test_prepared_history_survives_inactive_expired_or_missing_view_but_cannot_apply(self):
        expected = read_edit_status(self.f.ref, self.candidate)
        self.f.record.update(active=False, revision=10); self.f.save_context()
        self.assertEqual(read_edit_status(self.f.ref, self.candidate), expected)
        self.f.assert_code("chart_view_inactive", self.queue)
        self.f.record.update(active=True, observed_at_ms=0); self.f.save_context()
        self.assertEqual(read_edit_status(self.f.ref, self.candidate), expected)
        self.f.assert_code("chart_context_stale", self.queue)
        self.f.path.unlink()
        self.assertEqual(read_edit_status(self.f.ref, self.candidate), expected)
        self.assertFalse(self.record_path().exists())

    def test_prepared_status_requires_exact_candidate_owner_and_journal_proof(self):
        path = self.record_path().parent.parent / "journal.json"
        original = json.loads(path.read_text())
        for changes in [{"status": "preparing"}, {"status": "outcome_unknown"}, {"fingerprint": "wrong"},
                        {"revision": 2}, {"request_id": "foreign"}, {"result": {}},
                        {"result": {**original["entries"][0]["result"], "view_id": "foreign"}},
                        {"result": {**original["entries"][0]["result"], "chart_session": self.f.token}}]:
            with self.subTest(changes=changes):
                chart_service._atomic_runtime_json(path, {"entries": [{**original["entries"][0], **changes}]})
                self.f.assert_code("chart_edit_outcome_unknown", lambda: read_edit_status(self.f.ref, self.candidate))
        chart_service._atomic_runtime_json(path, original)
        for entries in [[], None, original["entries"] * 2]:
            chart_service._atomic_runtime_json(path, {"entries": entries})
            self.f.assert_code("chart_edit_outcome_unknown", lambda: read_edit_status(self.f.ref, self.candidate))
        chart_service._atomic_runtime_json(path, original)
        self.f.assert_code("invalid_chart_application", lambda: read_edit_status(self.f.ref, self.f.token))
        self.f.assert_code("invalid_chart_application", lambda: read_edit_status("x" * 32, self.candidate))
        with patch.object(chart_service, "HOST_PROCESS_ID", 4243):
            self.f.assert_code("invalid_chart_application", lambda: read_edit_status(self.f.ref, self.candidate))

    def test_missing_or_corrupt_journal_is_not_reported_as_not_requested(self):
        path = self.record_path().parent.parent / "journal.json"
        for contents in [None, [], "not an object"]:
            chart_service._atomic_runtime_json(path, contents)
            self.f.assert_code("chart_application_unavailable", lambda: read_edit_status(self.f.ref, self.candidate))
        path.unlink()
        self.f.assert_code("chart_application_unavailable", lambda: read_edit_status(self.f.ref, self.candidate))

    def test_candidate_malformed_guard_or_wrong_host_is_not_prepared_proof(self):
        payload = chart_service.read_chart_snapshot(self.candidate)
        for changes in [{"view_id": None}, {"conversation_id": None}, {"expected_revision": True},
                        {"requires_live_apply": False}, {"chart_session": None}, {"parameters": None}]:
            self.f.save_snapshot(self.candidate, {**payload, "drawing_guard": {**payload["drawing_guard"], **changes}})
            self.f.assert_code("invalid_chart_application", lambda: read_edit_status(self.f.ref, self.candidate))
        chart_service._atomic_runtime_json(self.f.runtime / "sessions" / (self.candidate + ".json"),
            {"ok": True, "session": self.candidate, "host_process_id": 4243, "payload": payload})
        self.f.assert_code("invalid_chart_application", lambda: read_edit_status(self.f.ref, self.candidate))

    def test_lock_or_missing_pending_record_prevents_not_requested_claim(self):
        directory = self.record_path().parent.parent
        lock = directory / "prepare.lock"
        chart_service._atomic_runtime_json(lock, {})
        self.f.assert_code("chart_edit_busy", lambda: read_edit_status(self.f.ref, self.candidate))
        lock.unlink()
        for pending in [self.candidate, "x" * 32, None]:
            chart_service._atomic_runtime_json(directory / "pending.json", {"candidate_chart_session": pending})
            self.f.assert_code("chart_application_unavailable" if pending is not None else "invalid_chart_application_reference",
                               lambda: read_edit_status(self.f.ref, self.candidate))
        self.assertFalse(self.record_path().exists())

    def test_actual_application_states_take_precedence_and_corruption_does_not_fall_back(self):
        self.queue(); original = read_application(self.f.ref, self.candidate)
        for status in ["queued", "delivered", "applied", "rejected", "failed", "outcome_unknown"]:
            chart_service._atomic_runtime_json(self.record_path(), {**original, "status": status})
            self.assertEqual(read_edit_status(self.f.ref, self.candidate)["apply_status"], status)
        chart_service._atomic_runtime_json(self.record_path(), {**original, "status": "bad"})
        self.f.assert_code("invalid_chart_application", lambda: read_edit_status(self.f.ref, self.candidate))
        chart_service._atomic_runtime_json(self.record_path(), [])
        self.f.assert_code("chart_application_unavailable", lambda: read_edit_status(self.f.ref, self.candidate))

    def test_parent_application_does_not_confirm_prepared_child(self):
        self.queue(); proof = read_application(self.f.ref, self.candidate)
        proof.update(status="applied", confirmed_chart_session=self.candidate)
        chart_service._atomic_runtime_json(self.record_path(), proof)
        self.f.record["revision"] = 2
        self.f.record["state"].update(source_chart_session=self.candidate, drawings=snapshot_inventory(chart_service.read_chart_snapshot(self.candidate)))
        self.f.save_context()
        child = self.f.prepare(chart_session=self.candidate, expected_revision=2, request_id="child")["chart_session"]
        self.assertEqual(read_edit_status(self.f.ref, child)["apply_status"], "not_requested")
        proof["status"] = "outcome_unknown"; chart_service._atomic_runtime_json(self.record_path(), proof)
        self.f.assert_code("chart_apply_busy", lambda: read_edit_status(self.f.ref, child))

    def test_application_created_during_status_read_is_not_hidden(self):
        from tools.chart_applications import _read
        def read_then_queue(path):
            value = _read(path)
            if path.name == "journal.json": self.queue()
            return value
        with patch("tools.chart_applications._read", side_effect=read_then_queue):
            # Queue's own journal read must not recursively trigger this interception.
            def queue_without_interception():
                with patch("tools.chart_applications._read", _read): request_chart_apply(self.f.ref, self.candidate)
            with patch.object(self, "queue", side_effect=queue_without_interception):
                self.assertEqual(read_edit_status(self.f.ref, self.candidate)["apply_status"], "queued")

    def test_unreadable_application_path_is_not_absence(self):
        from pathlib import Path
        stat = Path.stat
        def guarded_stat(path, *args, **kwargs):
            if path == self.record_path(): raise PermissionError("private diagnostic")
            return stat(path, *args, **kwargs)
        with patch.object(Path, "stat", guarded_stat):
            self.f.assert_code("chart_application_unavailable", lambda: read_edit_status(self.f.ref, self.candidate))

    def test_explicit_queue_is_idempotent_and_does_not_publish_or_mutate_current_context(self):
        before = self.f.path.read_text()
        first = self.queue(); saved = self.record_path().read_text(); second = self.queue()
        self.assertEqual(first, second); self.assertEqual(first["apply_status"], "queued")
        self.assertEqual(saved, self.record_path().read_text()); self.assertEqual(self.f.path.read_text(), before)
        self.assertEqual(len(self.f.published), 1); self.assertFalse(first["render_verified"])
        self.assertEqual(first["confirmation_scope"], "not_confirmed")

    def test_changed_revision_or_view_rejects_queue(self):
        original = deepcopy(self.f.record)
        self.f.record["revision"] = 2; self.f.save_context()
        self.f.assert_code("chart_context_revision_conflict", self.queue)
        self.f.record = original; self.f.record["view_id"] = "d" * 32; self.f.save_context()
        self.f.assert_code("invalid_chart_application", self.queue)
        self.assertFalse(self.record_path().exists())

    def test_unprepared_or_foreign_candidate_is_not_applied(self):
        self.f.assert_code("invalid_chart_application", lambda: request_chart_apply(self.f.ref, self.f.token))
        self.f.assert_code("invalid_chart_application_reference", lambda: request_chart_apply("../" + self.f.ref, self.candidate))
        self.f.assert_code("chart_context_unavailable", lambda: request_chart_apply("x" * 32, self.candidate))

    def test_old_browser_without_apply_protocol_is_not_sent_a_command(self):
        self.f.record["guarded_apply_supported"] = False; self.f.save_context()
        self.f.assert_code("chart_apply_protocol_unavailable", self.queue)
        self.assertFalse(self.record_path().exists())

    def test_successful_prepare_log_is_required(self):
        journal = self.record_path().parent.parent / "journal.json"
        chart_service._atomic_runtime_json(journal, {"entries": []})
        self.f.assert_code("chart_edit_outcome_unknown", self.queue)
        self.assertFalse(self.record_path().exists())

    def test_unconfirmed_previous_application_cannot_be_overwritten(self):
        self.queue()
        previous = read_application(self.f.ref, self.candidate); previous["status"] = "outcome_unknown"
        chart_service._atomic_runtime_json(self.record_path(), previous)
        self.f.record["revision"] = 2; self.f.save_context()
        next_candidate = self.f.prepare(expected_revision=2, request_id="next")["chart_session"]
        self.f.assert_code("chart_apply_busy", lambda: request_chart_apply(self.f.ref, next_candidate))
        self.assertEqual(read_application(self.f.ref, self.candidate)["status"], "outcome_unknown")

    def test_delivered_retry_is_historical_and_does_not_redeliver(self):
        self.queue(); record = read_application(self.f.ref, self.candidate); record["status"] = "delivered"
        chart_service._atomic_runtime_json(self.record_path(), record)
        self.f.record["active"] = False; self.f.save_context()
        self.assertEqual(self.queue()["apply_status"], "delivered")
        self.assertEqual(read_application(self.f.ref, self.candidate), record)

    def test_confirmed_source_supports_next_preparation_but_unknown_source_does_not(self):
        self.queue(); proof = read_application(self.f.ref, self.candidate)
        candidate_payload = chart_service.read_chart_snapshot(self.candidate)
        self.f.record["revision"] = 2
        self.f.record["state"]["source_chart_session"] = self.candidate
        self.f.record["state"]["drawings"] = snapshot_inventory(candidate_payload)
        self.f.save_context()
        self.f.assert_code("prepared_chart_not_applied", lambda: self.f.prepare(chart_session=self.candidate, expected_revision=2, request_id="R2"))
        proof.update(status="applied", confirmed_chart_session=self.candidate)
        chart_service._atomic_runtime_json(self.record_path(), proof)
        next_prepared = self.f.prepare(chart_session=self.candidate, expected_revision=2, request_id="R2")
        self.assertTrue(next_prepared["ok"]); self.assertEqual(next_prepared["parent_chart_session"], self.candidate)
        self.assertEqual(len(self.f.published), 2)

    def test_public_status_is_read_only_and_does_not_expose_delivery_or_internal_state(self):
        self.queue(); record = read_application(self.f.ref, self.candidate)
        record.update(lease_id="private-lease", service_token="private-secret")
        chart_service._atomic_runtime_json(self.record_path(), record); before = self.record_path().read_text()
        with patch("server.fetch_candles", side_effect=AssertionError("no fetch")), patch("chart_service.publish_chart", side_effect=AssertionError("no publish")):
            result = asyncio.run(server.get_chart_edit_status(self.f.ref, self.candidate, wait_ms=1))
        text = json.dumps(result.structuredContent)
        self.assertNotIn("private-secret", text); self.assertNotIn("private-lease", text); self.assertNotIn("base_state", text)
        self.assertTrue(result.structuredContent["record_is_historical"])
        self.assertEqual(self.record_path().read_text(), before)
        tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == "get_chart_edit_status")
        self.assertTrue(tool.annotations.readOnlyHint)

    def test_confirmed_daily_channel_survives_weekly_rejection_and_fresh_daily_return(self):
        # Mirrors the real web round trip: the UI aggregates daily rows, keeps
        # the confirmed daily source, and hides (not rewrites) daily channels.
        self.queue(); proof = read_application(self.f.ref, self.candidate)
        proof.update(status="applied", confirmed_chart_session=self.candidate)
        chart_service._atomic_runtime_json(self.record_path(), proof)
        source = chart_service.read_chart_snapshot(self.candidate)
        self.f.record["state"].update(source_chart_session=self.candidate,
            drawings=snapshot_inventory(source), source_interval="day", ui_interval="day")
        daily = deepcopy(self.f.record["state"])
        rows = daily["candles"]
        weekly = [dict(time=group[-1]["time"], open=group[0]["open"], close=group[-1]["close"],
            high=max(r["high"] for r in group), low=min(r["low"] for r in group),
            volume=sum(r["volume"] for r in group)) for group in (rows[:2], rows[2:])]
        self.f.record["revision"] = 3
        self.f.record["state"].update(interval="week", ui_interval="week", candles=weekly,
                                     visible_range={"available": False})
        self.f.save_context()
        journal = self.f.runtime / "edits" / "4242" / self.f.ref / "journal.json"
        before_journal = journal.read_bytes()
        change = ChartEdit(kind="channel", action="update", object_id=self.f.c["id"], color="orange")
        self.f.assert_code("chart_snapshot_not_aligned", lambda: self.f.prepare(change,
            chart_session=self.candidate, expected_revision=3, request_id="weekly-orange"))
        self.assertEqual(journal.read_bytes(), before_journal)
        self.assertEqual(len(self.f.published), 1)
        self.assertEqual(chart_service.read_chart_snapshot(self.candidate), source)
        self.assertEqual(read_application(self.f.ref, self.candidate), proof)
        # Restoring daily rows does not revive an old revision. A fresh one can
        # prepare again; rejection did not consume it or authorize an application.
        self.f.record["state"] = daily; self.f.record["revision"] = 4; self.f.save_context()
        self.f.assert_code("chart_context_revision_conflict", lambda: self.f.prepare(change,
            chart_session=self.candidate, expected_revision=2, request_id="stale-daily"))
        prepared = self.f.prepare(change, chart_session=self.candidate, expected_revision=4, request_id="daily-orange")
        self.assertEqual(prepared["object"]["color"], "warning")
        self.assertEqual(prepared["object"]["from"], self.f.c["from"])
        self.assertEqual(prepared["object"]["to"], self.f.c["to"])
        self.assertEqual(prepared["object"]["parallel"], self.f.c["parallel"])
        self.assertEqual(prepared["apply_status"], "not_requested")
        self.assertEqual(chart_service.read_chart_snapshot(self.candidate), source)

    def test_application_reader_rejects_bad_ownership_status_and_missing_record(self):
        self.f.assert_code("chart_application_unavailable", lambda: read_application(self.f.ref, self.candidate))
        self.queue(); original = read_application(self.f.ref, self.candidate)
        for changes in [{"host_process_id": 4243}, {"candidate_chart_session": "x" * 32}, {"status": "fake"}]:
            chart_service._atomic_runtime_json(self.record_path(), {**original, **changes})
            self.f.assert_code("invalid_chart_application", lambda: read_application(self.f.ref, self.candidate))

    def test_public_apply_returns_queued_and_keeps_original_snapshot_immutable(self):
        result = asyncio.run(server.apply_chart_edit(self.f.ref, self.candidate))
        self.assertEqual(result.structuredContent["apply_status"], "queued")
        self.assertEqual(chart_service.read_chart_snapshot(self.f.token), self.f.payload)
        self.assertEqual(application_status(read_application(self.f.ref, self.candidate))["apply_status"], "queued")


if __name__ == "__main__": unittest.main()
