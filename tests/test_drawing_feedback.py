import asyncio
from copy import deepcopy
import json
import unittest

import chart_service
import server
from tools.drawing_feedback import sanitize_drawing_feedback
from tools.chart_applications import read_application, application_status
from tools.chart_edits import snapshot_inventory
import test_chart_context as context_fixtures
import test_chart_applications as application_fixtures


def feedback(objects, phase="current"):
    return {"schema_version": 1, "phase": phase, "pixel_verified": True, "service_token": "private-secret",
            "items": [{"id": d["id"], "kind": d["kind"], "status": "created", "reason": "overlay_registered",
                       "visibility": "unknown", "service_token": "private-secret"} for d in objects]}


class DrawingFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.allowed = [{"id": "H", "kind": "horizontal_line"}]

    def test_whitelist_drops_secrets_and_cannot_upgrade_pixel_verification(self):
        result = sanitize_drawing_feedback(feedback(self.allowed), self.allowed)
        self.assertEqual(result["report_status"], "reported")
        self.assertFalse(result["pixel_verified"]); self.assertFalse(result["render_verified"])
        self.assertNotIn("private-secret", json.dumps(result)); self.assertEqual(result["evidence_scope"], "chart_object_api")

    def test_missing_duplicate_foreign_or_wrong_kind_items_fail_closed(self):
        raw = feedback(self.allowed)
        for items in [[], raw["items"] * 2, [{**raw["items"][0], "id": "manual:H"}], [{**raw["items"][0], "kind": "rectangle"}]]:
            self.assertEqual(sanitize_drawing_feedback({**raw, "items": items}, self.allowed)["report_status"], "invalid")

    def test_malformed_schema_or_contradictory_evidence_never_becomes_reported(self):
        raw = feedback(self.allowed)
        for changes in [{"schema_version": True}, {"schema_version": 1.0}, {"phase": []}, {"items": [None]}, {"report_status": []}]:
            value = {**raw, **changes}
            if changes == {"report_status": []}: value["schema_version"] = 2
            self.assertEqual(sanitize_drawing_feedback(value, self.allowed)["report_status"], "invalid")
        for changes in [{"reason": "period_mismatch"}, {"visibility": "outside_time_viewport"}, {"status": []},
                        {"reason": "private-exception"}, {"time_range_overlap": "yes"}]:
            value = {**raw, "items": [{**raw["items"][0], **changes}]}
            self.assertEqual(sanitize_drawing_feedback(value, self.allowed)["report_status"], "invalid")

    def test_no_report_is_not_an_invented_success(self):
        result = sanitize_drawing_feedback(None, self.allowed)
        self.assertEqual(result["report_status"], "not_reported"); self.assertEqual(result["items"], [])
        self.assertFalse(result["render_verified"])

    def test_current_context_reads_feedback_without_mutating_view_or_revision(self):
        fixture = context_fixtures.ChartContextTests("test_loaded_and_viewport_ranges_sampling_and_read_only")
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.record["drawing_feedback"] = feedback(fixture.record["state"]["drawings"])
        fixture.save(); before = fixture.path.read_text()
        result = asyncio.run(server.get_chart_context(fixture.token)).structuredContent
        self.assertEqual(result["drawing_feedback"]["phase"], "current")
        self.assertEqual(result["drawing_feedback"]["items"][0]["status"], "created")
        self.assertEqual(result["revision"], 1); self.assertEqual(fixture.path.read_text(), before)
        self.assertNotIn("private-secret", json.dumps(result)); self.assertFalse(result["render_verified"])

    def test_application_feedback_is_historical_and_scoped_to_candidate_and_base_ids(self):
        fixture = application_fixtures.ChartApplicationTests("test_explicit_queue_is_idempotent_and_does_not_publish_or_mutate_current_context")
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.queue(); record = read_application(fixture.f.ref, fixture.candidate)
        inventory = snapshot_inventory(chart_service.read_chart_snapshot(fixture.candidate))
        record.update(status="applied", confirmed_chart_session=fixture.candidate, drawing_feedback=feedback(inventory, "applied"))
        chart_service._atomic_runtime_json(fixture.record_path(), record)
        fixture.f.record["state"]["state"] = "not_chart"; fixture.f.save_context()
        before = fixture.record_path().read_text()
        result = asyncio.run(server.get_chart_edit_status(fixture.f.ref, fixture.candidate)).structuredContent
        self.assertEqual(result["drawing_feedback"]["phase"], "applied")
        self.assertEqual(len(result["drawing_feedback"]["items"]), len(inventory))
        self.assertEqual(result["interaction"]["object_status"], "created")
        self.assertFalse(result["interaction"]["pixel_verified"])
        self.assertIn("像素未核验", result["interaction"]["message"])
        self.assertTrue(result["record_is_historical"]); self.assertFalse(result["render_verified"])
        self.assertEqual(fixture.record_path().read_text(), before)
        corrupt = deepcopy(record); corrupt["drawing_feedback"]["items"][0]["id"] = "foreign"
        self.assertEqual(application_status(corrupt)["drawing_feedback"]["report_status"], "invalid")


if __name__ == "__main__": unittest.main()
