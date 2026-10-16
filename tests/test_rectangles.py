import asyncio
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import chart_service
import server
from mcp.server.fastmcp.exceptions import ToolError
from tools.lines import LineError, edit_horizontal_line, horizontal_lines
from tools.trend_lines import edit_trend_line, trend_lines
from tools.channels import channels
from tools.rectangles import rectangles, edit_rectangle
from tools.drawing_verification import verify_drawings
from test_channels import chart, create as create_channel


def create(payload=None, **changes):
    params = {"start_time": "2026-09-10", "end_time": "2026-09-15", "lower_price": 30, "upper_price": 33,
              "name": "完整整理平台", "color": "橙色"}
    params.update(changes)
    return edit_rectangle(payload or chart(), "create", **params)


class RectangleTests(unittest.TestCase):
    def test_exact_bounds_and_copy(self):
        base = chart(); original = deepcopy(base)
        p, r = create(base)
        rows = base["chartCommands"][0]["rows"]
        self.assertEqual(base, original)
        self.assertEqual(r["start_time"], rows[0]["time"])
        self.assertEqual(r["end_time"], rows[-1]["time"])
        self.assertEqual((r["lower_price"], r["upper_price"]), (30, 33))
        self.assertEqual(r["label"], "完整整理平台"); self.assertEqual(r["color"], "warning")
        self.assertTrue(r["show_fill"]); self.assertEqual(r["interval"], "day")
        self.assertEqual(p["chartCommands"][:2], original["chartCommands"])
        read = rectangles(p); read[0]["lower_price"] = 99
        self.assertEqual(rectangles(p)[0]["lower_price"], 30)
        r["lower_price"] = 99
        self.assertEqual(rectangles(p)[0]["lower_price"], 30)

    def test_mixed_crud_preserves_other_rectangles_and_drawing_families(self):
        base, h = edit_horizontal_line(chart(), "create", price=31, name="H")
        base, t = edit_trend_line(base, "create", start_time="2026-09-10", start_price=30, end_time="2026-09-15", end_price=33)
        base, c = create_channel(base)
        a, first = create(base)
        b, second = create(a, name="第二平台", lower_price=29, upper_price=34)
        moved, r = edit_rectangle(b, "update", rectangle_id=first["id"], lower_price=29.5,
                                 name="完整观察平台", color="绿色", show_fill=False)
        self.assertEqual(r["id"], first["id"])
        self.assertEqual(r["upper_price"], first["upper_price"])
        self.assertEqual(r["start_time"], first["start_time"]); self.assertEqual(r["end_time"], first["end_time"])
        self.assertEqual(r["color"], "success"); self.assertFalse(r["show_fill"])
        deleted, removed = edit_rectangle(moved, "delete", rectangle_id=first["id"])
        self.assertEqual(removed, r); self.assertEqual(rectangles(deleted), [second])
        self.assertEqual(horizontal_lines(deleted), [h]); self.assertEqual(trend_lines(deleted), [t]); self.assertEqual(channels(deleted), [c])
        self.assertEqual(deleted["chartCommands"][:2], base["chartCommands"][:2])
        self.assertEqual(rectangles(a), [first])

    def test_modify_time_range_and_both_bounds_atomically(self):
        p, r = create()
        updated, short = edit_rectangle(p, "update", rectangle_id=r["id"], start_time="2026-09-11", end_time="2026-09-14", lower_price=34, upper_price=36)
        rows = p["chartCommands"][0]["rows"]
        self.assertEqual(short["start_time"], rows[1]["time"]); self.assertEqual(short["end_time"], rows[2]["time"])
        self.assertEqual((short["lower_price"], short["upper_price"]), (34, 36))
        self.assertEqual(short["id"], r["id"])
        self.assertEqual(updated["chartCommands"][0], p["chartCommands"][0])

    def test_invalid_edits_never_mutate_or_swap_bounds(self):
        p, r = create(); original = deepcopy(p)
        cases = [({"start_time": "2026-09-15"}, "invalid_anchor_order"),
                 ({"end_time": "2026-09-10"}, "invalid_anchor_order"),
                 ({"start_time": "2026-09-12"}, "anchor_not_found"),
                 ({"lower_price": 33}, "invalid_price_bounds"), ({"upper_price": 29}, "invalid_price_bounds"),
                 ({"lower_price": -1}, "invalid_price"), ({"upper_price": float("nan")}, "invalid_price"),
                 ({"lower_price": True}, "invalid_price"), ({"show_fill": 1}, "invalid_fill"),
                 ({"name": "a\nb"}, "invalid_name"), ({"color": "purple"}, "invalid_color"), ({}, "empty_update")]
        for changes, code in cases:
            with self.subTest(changes=changes), self.assertRaises(LineError) as error:
                edit_rectangle(p, "update", rectangle_id=r["id"], **changes)
            self.assertEqual(error.exception.code, code); self.assertEqual(p, original)
        for action in ["update", "delete"]:
            with self.assertRaises(LineError): edit_rectangle(p, action, rectangle_id="auto", name="x")
        with self.assertRaises(LineError): edit_rectangle(chart(), "create", lower_price=30)

    def test_retry_alias_colors_capacity_and_new_parent_identity(self):
        a, r = create(request_id="R")
        retry, same = create(a, request_id="R", color="warning")
        self.assertEqual(retry, a); self.assertEqual(same, r)
        with self.assertRaises(LineError): create(a, request_id="R", upper_price=34)
        for _ in range(29): a, _ = create(a)
        with self.assertRaises(LineError): create(a)
        _, original_retry = create(request_id="R")
        self.assertEqual(original_retry["id"], r["id"])

    def test_minute_exact_clock_and_period_date_resolution(self):
        p = chart("minute"); rows = p["chartCommands"][0]["rows"]
        _, r = create(p, start_time=str(rows[0]["time"]), end_time="2026-09-15T07:00:00Z")
        self.assertEqual(r["interval"], "minute")
        with self.assertRaises(LineError): create(p)
        for interval in ["week", "month", "quarter", "year"]:
            _, r = create(chart(interval)); self.assertEqual(r["interval"], interval)

    def test_verification_checks_bounds_fill_and_type_applicability(self):
        p, r = create()
        expected = {"kind": "rectangle", "id": r["id"], "name": "完整整理平台", "color": "橙色",
                    "start_time": "2026-09-10", "end_time": "2026-09-15", "lower_price": 30, "upper_price": 33, "show_fill": True}
        checked = verify_drawings(p, [expected])
        self.assertTrue(checked["matches"]); self.assertFalse(checked["render_verified"])
        mismatch = verify_drawings(p, [{**expected, "lower_price": 29.5, "upper_price": 34, "show_fill": False}])
        self.assertEqual({m["field"] for m in mismatch["checks"][0]["mismatches"]}, {"lower_price", "upper_price", "show_fill"})
        for extra in [{"start_price": 30}, {"parallel_time": "2026-09-11"}, {"show_midline": False}, {"price": 31}]:
            with self.assertRaises(LineError): verify_drawings(p, [{**expected, **extra}])
        with self.assertRaises(LineError): verify_drawings(p, [{"kind": "channel", "id": "C", "show_fill": True}])
        deleted, _ = edit_rectangle(p, "delete", rectangle_id=r["id"])
        self.assertTrue(verify_drawings(deleted, [{"kind": "rectangle", "id": r["id"], "exists": False}])["matches"])

    def test_public_registered_tools_snapshot_chain_no_fetch_and_warnings(self):
        snapshots = {"a" * 32: chart()}
        def publish(payload):
            token = str(len(snapshots)) * 32; snapshots[token] = deepcopy(payload)
            return token, "http://127.0.0.1"
        async def run():
            result = await server.mcp._tool_manager.call_tool("create_rectangle", {"chart_session": "a" * 32, "symbol": "TEST.X",
                "start_time": "2026-09-10", "end_time": "2026-09-15", "lower_price": 30, "upper_price": 33, "name": "完整平台", "color": "红色"})
            c = result.structuredContent
            self.assertTrue(c["verification_required"]); self.assertFalse(c["render_verified"])
            self.assertEqual(c["rectangle"]["color"], "danger")
            u = (await server.update_rectangle(c["chart_session"], "TEST.X", c["rectangle"]["id"], lower_price=29.5, show_fill=False)).structuredContent
            state = (await server.get_rectangles(u["chart_session"], "TEST.X")).structuredContent
            self.assertEqual(state["rectangles"][0]["lower_price"], 29.5)
            self.assertEqual(u["parent_chart_session"], c["chart_session"])
            d = (await server.delete_rectangle(u["chart_session"], "TEST.X", c["rectangle"]["id"])).structuredContent
            self.assertEqual(d["rectangles"], [])
            self.assertEqual(rectangles(snapshots[c["chart_session"]])[0]["lower_price"], 30)
            self.assertTrue((await server.get_rectangles("a" * 32, "OTHER.X")).isError)
            self.assertTrue((await server.get_rectangles("z" * 32, "TEST.X")).isError)
            warning = (await server.create_rectangle("a" * 32, "TEST.X", "2026-09-10", "2026-09-15", 25, 99)).structuredContent
            self.assertEqual(warning["out_of_range_prices"], [25, 99])
            self.assertEqual(warning["candle_price_range"], {"low": 28, "high": 36})
        with patch("server.read_chart_snapshot", side_effect=lambda t: deepcopy(snapshots.get(t))), patch("server.publish_chart", side_effect=publish), patch("server.fetch_candles", side_effect=AssertionError("no fetch")):
            asyncio.run(run())

    def test_failures_do_not_publish_and_typed_schema_does_not_coerce_booleans(self):
        with patch("server.read_chart_snapshot", return_value=chart()), patch("server.publish_chart") as publish:
            result = asyncio.run(server.create_rectangle("a" * 32, "TEST.X", "2026-09-10", "2026-09-15", 33, 30))
            self.assertTrue(result.isError); self.assertIn("invalid_price_bounds", result.content[0].text); publish.assert_not_called()
        with patch("server.read_chart_snapshot") as read:
            params = {"chart_session": "a" * 32, "symbol": "TEST.X", "start_time": "2026-09-10", "end_time": "2026-09-15", "lower_price": 30, "upper_price": 33}
            for bad in [{"lower_price": True}, {"show_fill": "false"}]:
                with self.assertRaises(ToolError): asyncio.run(server.mcp._tool_manager.call_tool("create_rectangle", {**params, **bad}))
            read.assert_not_called()
        with patch("server.read_chart_snapshot", return_value=chart()), patch("server.publish_chart", side_effect=OSError("secret")):
            result = asyncio.run(server.create_rectangle("a" * 32, "TEST.X", "2026-09-10", "2026-09-15", 30, 33))
            self.assertTrue(result.isError); self.assertNotIn("secret", str(result))

    def test_real_publication_readback_verification_and_delete(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(chart_service, "RUNTIME_DIR", Path(directory)), patch.object(
            chart_service, "RUNTIME_SESSION_FILE", Path(directory) / "services" / "owned.json"
        ):
            service = chart_service.ChartService("127.0.0.1", 0)
            try:
                base, _ = service.publish(chart())
                with patch.object(chart_service, "_service", service):
                    created = asyncio.run(server.create_rectangle(base, "TEST.X", "2026-09-10", "2026-09-15", 30, 33, "完整平台", "绿色"))
                    c = created.structuredContent
                    self.assertNotIn(service.auth_token, str(created))
                    verified = asyncio.run(server.verify_chart_drawings(c["chart_session"], "TEST.X", [{"kind": "rectangle", "id": c["rectangle"]["id"], "lower_price": 30, "upper_price": 33, "color": "绿色"}]))
                    self.assertTrue(verified.structuredContent["matches"])
                    deleted = asyncio.run(server.delete_rectangle(c["chart_session"], "TEST.X", c["rectangle"]["id"])).structuredContent
                    self.assertEqual(rectangles(chart_service.read_chart_snapshot(deleted["chart_session"])), [])
                    self.assertEqual(len(rectangles(chart_service.read_chart_snapshot(c["chart_session"]))), 1)
            finally:
                service.httpd.shutdown(); service.httpd.server_close()

    def test_schema_and_instruction_require_real_rectangles_not_guessed_platforms(self):
        tools = asyncio.run(server.mcp.list_tools())
        self.assertTrue({"create_rectangle", "get_rectangles", "update_rectangle", "delete_rectangle"} <= {t.name for t in tools})
        schema = next(t.inputSchema for t in tools if t.name == "create_rectangle")
        self.assertTrue({"start_time", "end_time", "lower_price", "upper_price"} <= set(schema["required"]))
        self.assertTrue(next(t.annotations.readOnlyHint for t in tools if t.name == "get_rectangles"))
        self.assertIn("Ask for missing bounds", server.mcp.instructions)
        self.assertIn("replace a rectangle with two horizontal lines", server.mcp.instructions)


if __name__ == "__main__": unittest.main()
