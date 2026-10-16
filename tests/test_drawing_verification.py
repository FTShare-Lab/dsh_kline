import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

import server
from mcp.server.fastmcp.exceptions import ToolError
from tools.lines import LineError, edit_horizontal_line, validate_line_fields
from tools.trend_lines import edit_trend_line
from tools.channels import edit_channel
from tools.drawing_verification import DrawingExpectation, verify_drawings
from test_channels import chart, create


class DrawingVerificationTests(unittest.TestCase):
    def test_catches_abbreviated_label_omitted_color_and_wrong_price(self):
        p, h = edit_horizontal_line(chart(), "create", price=30, name="T")
        original = deepcopy(p)
        expected = {"kind": "horizontal_line", "id": h["id"], "name": "下降T", "color": "绿色", "price": 31}
        result = verify_drawings(p, [expected])
        self.assertFalse(result["matches"]); self.assertFalse(result["snapshot_verified"])
        self.assertEqual({m["field"] for m in result["checks"][0]["mismatches"]}, {"name", "color", "price"})
        self.assertEqual(result["checks"][0]["actual"]["color"], "info")
        corrected, _ = edit_horizontal_line(p, "update", line_id=h["id"], name="下降T", color="绿色", price=31)
        verified = verify_drawings(corrected, [expected])
        self.assertTrue(verified["matches"]); self.assertFalse(verified["render_verified"])
        self.assertEqual(verified["verification_scope"], "provided_expectations_only")
        self.assertEqual(p, original)

    def test_trend_and_channel_expected_anchor_fields(self):
        p, trend = edit_trend_line(chart(), "create", start_time="2026-09-10", start_price=30, end_time="2026-09-15", end_price=33, name="完整趋势", color="红色")
        p, channel = create(p)
        specs = [DrawingExpectation(kind="trend_line", id=trend["id"], name="完整趋势", color="danger", start_time="2026-09-10", start_price=30, end_time="2026-09-15T07:00:00Z", end_price=33),
                 DrawingExpectation(kind="channel", id=channel["id"], parallel_time="2026-09-11", parallel_price=33, show_midline=True, color="green")]
        self.assertTrue(verify_drawings(p, specs)["matches"])
        changed = specs[1].model_copy(update={"parallel_price": 34, "show_midline": False})
        mismatches = verify_drawings(p, [changed])["checks"][0]["mismatches"]
        self.assertEqual({m["field"] for m in mismatches}, {"parallel_price", "show_midline"})

    def test_exists_checks_and_empty_name_are_not_skipped(self):
        p, c = create()
        spec = {"kind": "channel", "id": c["id"], "exists": False}
        self.assertFalse(verify_drawings(p, [spec])["matches"])
        deleted, _ = edit_channel(p, "delete", channel_id=c["id"])
        self.assertTrue(verify_drawings(deleted, [spec])["matches"])
        self.assertFalse(verify_drawings(deleted, [{**spec, "exists": True}])["matches"])
        self.assertFalse(verify_drawings(p, [{"kind": "channel", "id": c["id"], "name": ""}])["matches"])

    def test_invalid_expectations_and_duplicate_id_are_rejected(self):
        p, c = create()
        for specs in [[], [{}], [{"kind": "channel", "id": c["id"], "unknown": 1}],
                      [{"kind": "horizontal_line", "id": "H", "start_price": 31}],
                      [{"kind": "channel", "id": c["id"], "exists": False, "name": "x"}],
                      [{"kind": "channel", "id": c["id"], "start_price": True}],
                      [{"kind": "channel", "id": c["id"], "color": "purple"}],
                      [{"kind": "channel", "id": c["id"], "name": "a\nb"}],
                      [{"kind": "channel", "id": c["id"], "start_time": "2026-09-12"}]]:
            with self.assertRaises(LineError): verify_drawings(p, specs)
        p["chartCommands"].append(deepcopy(c))
        with self.assertRaises(LineError): verify_drawings(p, [{"kind": "channel", "id": c["id"]}])

    def test_color_aliases_are_shared_and_idempotent(self):
        for canonical, aliases in {"info": ["info", "blue", "蓝色"], "success": ["success", "green", "绿色"],
                                   "warning": ["warning", "orange", "橙色"], "danger": ["danger", "red", "红色"]}.items():
            for color in aliases:
                _, name, normalized = validate_line_fields(name="完整名称", color=color)
                self.assertEqual(name, "完整名称"); self.assertEqual(normalized, canonical)
                p, h = edit_horizontal_line(chart(), "create", price=31, color=color, request_id="H")
                retry, second = edit_horizontal_line(p, "create", price=31, color=canonical, request_id="H")
                self.assertEqual(p, retry); self.assertEqual(h, second)

    def test_public_verification_is_scoped_and_read_only(self):
        p, c = create()
        async def run():
            r = await server.verify_chart_drawings("a" * 32, "TEST.X", [DrawingExpectation(kind="channel", id=c["id"], name="上升通道", color="绿色")])
            self.assertTrue(r.structuredContent["matches"])
            self.assertFalse(r.structuredContent["render_verified"])
            self.assertEqual(r.structuredContent["chart_session"], "a" * 32)
            wrong = await server.verify_chart_drawings("a" * 32, "OTHER.X", [DrawingExpectation(kind="channel", id=c["id"])])
            self.assertTrue(wrong.isError)
            mismatch = await server.verify_chart_drawings("a" * 32, "TEST.X", [DrawingExpectation(kind="channel", id=c["id"], color="红色")])
            self.assertFalse(mismatch.structuredContent["matches"])
            self.assertIn('"matches":false', mismatch.content[0].text)
        with patch("server.read_chart_snapshot", return_value=p), patch("server.publish_chart", side_effect=AssertionError("verification must not publish")), patch("server.fetch_candles", side_effect=AssertionError("no fetch")):
            asyncio.run(run())

    def test_instruction_contract_does_not_claim_intent_or_visual_verification(self):
        self.assertIn("original USER-requested fields", server.mcp.instructions)
        self.assertIn("not visual verification", server.mcp.instructions)
        tools = asyncio.run(server.mcp.list_tools())
        schema = next(t.inputSchema for t in tools if t.name == "verify_chart_drawings")
        self.assertIn("expectations", schema["required"])
        self.assertEqual(schema["properties"]["expectations"]["minItems"], 1)
        self.assertTrue(next(t.annotations.readOnlyHint for t in tools if t.name == "verify_chart_drawings"))

    def test_registered_tool_validation_rejects_bool_prices_and_midline_strings(self):
        calls = [("create_horizontal_line", {"chart_session": "a" * 32, "symbol": "TEST.X", "price": True}),
                 ("create_trend_line", {"chart_session": "a" * 32, "symbol": "TEST.X", "start_time": "2026-09-10", "start_price": True, "end_time": "2026-09-15", "end_price": 33}),
                 ("create_channel", {"chart_session": "a" * 32, "symbol": "TEST.X", "start_time": "2026-09-10", "start_price": 30,
                                     "end_time": "2026-09-15", "end_price": 33, "parallel_time": "2026-09-11", "parallel_price": 33, "show_midline": "false"})]
        with patch("server.read_chart_snapshot") as read:
            for name, arguments in calls:
                with self.assertRaises(ToolError): asyncio.run(server.mcp._tool_manager.call_tool(name, arguments))
            read.assert_not_called()
        p, c = create()
        with patch("server.read_chart_snapshot", return_value=p), patch("server.publish_chart") as publish:
            result = asyncio.run(server.mcp._tool_manager.call_tool("verify_chart_drawings", {
                "chart_session": "a" * 32, "symbol": "TEST.X", "expectations": [{"kind": "channel", "id": c["id"], "name": "上升通道", "color": "绿色"}]}))
            self.assertTrue(result.structuredContent["matches"]); publish.assert_not_called()


if __name__ == "__main__": unittest.main()
