import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import chart_service
import server
from tools.chart_context import read_chart_context
from tools.lines import LineError


class ChartContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        for target, value in [("RUNTIME_DIR", Path(self.directory.name)), ("HOST_PROCESS_ID", 4242)]:
            patcher = patch.object(chart_service, target, value); patcher.start(); self.addCleanup(patcher.stop)
        clock = patch("tools.chart_context.time.time", return_value=100); clock.start(); self.addCleanup(clock.stop)
        self.token = "a" * 32
        self.path = Path(self.directory.name) / "views" / "4242" / (self.token + ".json")
        self.path.parent.mkdir(parents=True)
        self.record = {"ok": True, "context_ref": self.token, "host_process_id": 4242, "conversation_id": "A", "view_id": "b" * 32,
            "revision": 1, "active": True, "ambiguous": False, "observed_at_ms": 100000, "state": {
                "schema_version": 1, "state": "ready", "symbol": "TEST.X", "name": "测试", "interval": "day", "range_key": "custom", "active_page": "chart",
                "candles": [{"time": t, "open": 31, "high": 33, "low": 30, "close": 32, "volume": 1} for t in range(1, 5)],
                "visible_range": {"available": True, "index_from": 1, "index_to_exclusive": 3},
                "drawings": [{"id": "H", "kind": "horizontal_line", "origin": "ai", "name": "完整线", "price": 31}],
                "selection": {"kind": "candle", "time": 2}, "indicators": ["vol"], "data_status": "delayed"}}
        self.save()

    def save(self): self.path.write_text(json.dumps(self.record), encoding="utf-8")

    def test_loaded_and_viewport_ranges_sampling_and_read_only(self):
        result = read_chart_context(self.token)
        self.assertEqual(result["loaded_range"]["count"], 4); self.assertEqual(result["visible_range"]["count"], 2)
        self.assertEqual([r["time"] for r in result["candles"]], [2, 3])
        limited = read_chart_context(self.token, candle_scope="loaded", limit=2)
        self.assertEqual([r["time"] for r in limited["candles"]], [3, 4])
        self.assertTrue(limited["candle_selection"]["truncated"])
        self.assertEqual(read_chart_context(self.token, candle_scope="none")["candles"], [])
        self.assertFalse(result["live_view_editable"]); self.assertFalse(result["render_verified"])
        self.assertEqual(result["selected_drawing_status"], "not_supported")

    def test_icon_annotation_survives_python_context_read(self):
        self.record["state"]["drawings"].append({"id": "I", "kind": "icon_annotation", "origin": "ai",
            "name": "向上提示", "color": "info", "interval": "day", "time": 2, "price": 31.2, "icon": "arrow_up"})
        self.save()
        result = read_chart_context(self.token)
        drawing = next(item for item in result["drawings"] if item["id"] == "I")
        self.assertEqual((drawing["kind"], drawing["icon"], drawing["time"], drawing["price"]),
            ("icon_annotation", "arrow_up", 2, 31.2))

    def test_unknown_viewport_is_not_loaded_range(self):
        self.record["state"]["visible_range"] = {"available": False}; self.save()
        result = read_chart_context(self.token)
        self.assertFalse(result["visible_range"]["available"]); self.assertEqual(result["candles"], [])
        self.assertEqual(result["loaded_range"]["count"], 4)

    def test_source_diagnostic_allowlist_drops_arbitrary_fields_and_does_not_claim_edit_authority(self):
        self.record["source_status"] = {"schema_version": 1, "reason": "source_matches_view", "phase": "forged",
            "edit_authorized": True, "path": "test-secret", "message": "untrusted"}
        self.save()
        result = read_chart_context(self.token, candle_scope="loaded")
        self.assertEqual(result["source_status"], {"schema_version": 1, "scope": "source_handoff", "phase": "aligned",
            "reason": "source_matches_view", "next_action": "continue_guarded_workflow", "edit_authorized": False})
        self.assertEqual(result["source_snapshot_alignment"], "not_verified")
        self.assertFalse(result["live_view_editable"])
        self.assertEqual(result["revision"], 1)
        self.assertNotIn("test-secret", json.dumps(result))
        for raw in (None, {"schema_version": True, "reason": "source_matches_view"}, {"schema_version": 1, "reason": []}):
            self.record["source_status"] = raw; self.save()
            self.assertEqual(read_chart_context(self.token)["source_status"]["reason"], "not_checked")

    def test_deterministic_date_labels_preserve_raw_candles_and_sampling(self):
        for row, timestamp in zip(self.record["state"]["candles"], [1788850800, 1789369200, 1791788400, 1791874800]):
            row["time"] = timestamp
        self.record["state"]["selection"] = None
        self.save()
        result = read_chart_context(self.token, candle_scope="loaded", limit=2)
        labels = result["time_display"]
        self.assertEqual(labels["loaded_start"]["date"], "2026-09-08")
        self.assertEqual(labels["loaded_end"]["date"], "2026-10-13")
        self.assertEqual(labels["visible_start"]["date"], "2026-09-14")
        self.assertEqual(labels["visible_end"]["date"], "2026-10-12")
        self.assertEqual(labels["sample_labels"][0]["iso"], "2026-10-12T15:00:00+08:00")
        self.assertEqual([r["time"] for r in labels["sample_labels"]], [r["time"] for r in result["candles"]])
        self.assertEqual(set(result["candles"][0]), {"time", "open", "high", "low", "close", "volume"})
        self.assertEqual(read_chart_context(self.token, candle_scope="none")["time_display"]["sample_labels"], [])

    def test_stale_inactive_ambiguous_foreign_or_missing_never_fall_back(self):
        original = deepcopy(self.record)
        cases = [({"observed_at_ms": 69000}, "chart_context_stale"), ({"active": False}, "chart_view_inactive"),
                 ({"ambiguous": True}, "ambiguous_chart_views"), ({"host_process_id": 4243}, "chart_context_unavailable")]
        for changes, code in cases:
            self.record = {**original, **changes}; self.save()
            with self.assertRaises(LineError) as error: read_chart_context(self.token)
            self.assertEqual(error.exception.code, code)
        with self.assertRaises(LineError): read_chart_context("../" + self.token)
        with self.assertRaises(LineError): read_chart_context("c" * 32)

    def test_loading_or_nonchart_state_does_not_present_old_candles(self):
        for state in ["loading", "not_chart", "empty", "error"]:
            self.record["state"]["state"] = state; self.save()
            result = read_chart_context(self.token)
            self.assertEqual(result["candles"], []); self.assertEqual(result["drawings"], [])
            self.assertEqual(result["loaded_range"]["count"], 0)

    def test_malformed_viewport_and_candle_clock_rejected(self):
        original = deepcopy(self.record)
        for kind in ["viewport", "clock", "bool"]:
            self.record = deepcopy(original)
            if kind == "viewport": self.record["state"]["visible_range"]["index_to_exclusive"] = 999
            if kind == "clock": self.record["state"]["candles"].reverse()
            if kind == "bool": self.record["state"]["candles"][0]["open"] = True
            self.save()
            with self.assertRaises(LineError): read_chart_context(self.token)

    def test_unknown_credentials_not_copied_and_capabilities_cannot_be_upgraded(self):
        self.record["service_token"] = "private-secret"
        self.record["state"]["service_token"] = "private-secret"
        self.record["state"]["candles"][0]["service_token"] = "private-secret"
        self.record["state"]["drawings"][0].update(service_token="private-secret", context_editable=True)
        self.record["state"].update(live_view_editable=True, render_verified=True)
        self.save(); result = read_chart_context(self.token)
        self.assertNotIn("private-secret", json.dumps(result))
        self.assertFalse(result["drawings"][0]["context_editable"]); self.assertFalse(result["render_verified"])

    def test_public_tool_is_read_only_and_never_fetches_or_publishes(self):
        before = self.path.read_text()
        with patch("server.fetch_candles", side_effect=AssertionError("no fetch")), patch("server.publish_chart", side_effect=AssertionError("no publish")):
            result = asyncio.run(server.get_chart_context(self.token))
            self.assertTrue(result.structuredContent["ok"])
            missing = asyncio.run(server.get_chart_context("x" * 32)); self.assertTrue(missing.isError)
        self.assertEqual(self.path.read_text(), before)
        tools = asyncio.run(server.mcp.list_tools())
        tool = next(t for t in tools if t.name == "get_chart_context")
        self.assertTrue(tool.annotations.readOnlyHint)
        self.assertEqual(tool.inputSchema["required"], ["context_ref"])

    def test_provenance_is_whitelisted_read_only_and_not_alignment_authority(self):
        state = self.record["state"]
        state.update(interval="week", source_interval="day", source_chart_session="c" * 32,
            data_provenance={"provider": "ftshare", "transformation": "local_aggregation", "source_url": "test-secret",
                "aggregation": {"timezone": "Asia/Shanghai", "completeness": "complete", "key": "test-secret"}})
        self.save()
        before = self.path.read_text()
        with patch("server.fetch_candles", side_effect=AssertionError("no fetch")), patch("server.publish_chart", side_effect=AssertionError("no publish")):
            result = asyncio.run(server.get_chart_context(self.token, candle_scope="none")).structuredContent
        self.assertEqual(result["data_provenance"]["transformation"], "local_aggregation")
        self.assertEqual(result["data_provenance"]["aggregation"]["completeness"], "not_verified")
        self.assertEqual(result["source_snapshot_alignment"], "not_verified")
        self.assertFalse(result["render_verified"]); self.assertFalse(result["live_view_editable"])
        self.assertNotIn("test-secret", json.dumps(result)); self.assertEqual(self.path.read_text(), before)
        for value in ("loading", "not_chart", "empty", "error"):
            state["state"] = value; self.save()
            provenance = read_chart_context(self.token)["data_provenance"]
            self.assertEqual(provenance["provider"], "unknown"); self.assertEqual(provenance["transformation"], "unknown")
            self.assertIsNone(provenance["source_interval"]); self.assertIsNone(provenance["aggregation"])


if __name__ == "__main__": unittest.main()
