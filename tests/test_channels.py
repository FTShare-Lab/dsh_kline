import asyncio
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server
import chart_service
from tools.channels import channels, edit_channel
from tools.lines import LineError, edit_horizontal_line, horizontal_lines
from tools.trend_lines import edit_trend_line, trend_lines


def chart(interval="day"):
    dates = ["2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15"]
    rows = [{"time": int(datetime.fromisoformat(d + "T15:00:00+08:00").timestamp()),
             "open": 31, "high": 36, "low": 28, "close": 32, "volume": 1} for d in dates]
    return {"symbol": "TEST.X", "interval": interval, "count": len(rows), "chartCommands": [
        {"type": "SET_CANDLES", "rows": rows}, {"type": "DRAW_TREND_LINE", "id": "auto"}]}


def create(payload=None, **changes):
    params = {"start_time": "2026-09-10", "start_price": 30, "end_time": "2026-09-15", "end_price": 33,
              "parallel_time": "2026-09-11", "parallel_price": 33, "name": "上升通道", "color": "绿色"}
    params.update(changes)
    return edit_channel(payload or chart(), "create", **params)


class ChannelTests(unittest.TestCase):
    def test_three_point_geometry_uses_candle_index_not_calendar_gaps(self):
        base = chart(); original = deepcopy(base)
        p, c = create(base)
        self.assertEqual(base, original)
        self.assertEqual(c["width"], 2)
        self.assertEqual(c["slope_per_bar"], 1)
        self.assertEqual(c["geometry_basis"], "candle_index_linear_price")
        self.assertEqual(c["direction"], "ascending")
        self.assertEqual(c["upper"]["from"]["price"], 32)
        self.assertEqual(c["upper"]["to"]["price"], 35)
        self.assertEqual(c["lower"]["from"]["price"], 30)
        self.assertEqual(c["lower"]["to"]["price"], 33)
        self.assertEqual(c["color"], "success")
        self.assertTrue(c["show_midline"])
        # Monday is the third candle, not four elapsed calendar days later.
        _, monday = create(parallel_time="2026-09-14", parallel_price=34)
        self.assertEqual(monday["width"], 2)
        self.assertEqual(p["chartCommands"][:2], original["chartCommands"])

    def test_descending_lower_anchor_and_horizontal_channel(self):
        _, down = create(start_price=34, end_price=31, parallel_time="2026-09-14", parallel_price=30)
        self.assertEqual(down["direction"], "descending")
        self.assertEqual(down["signed_offset"], -2)
        self.assertEqual(down["upper"]["from"]["price"], 34)
        self.assertEqual(down["lower"]["to"]["price"], 29)
        _, flat = create(start_price=30, end_price=30, parallel_price=31)
        self.assertEqual(flat["direction"], "horizontal")
        self.assertEqual(flat["width"], 1)

    def test_atomic_crud_preserves_all_other_drawing_families(self):
        base, h = edit_horizontal_line(chart(), "create", price=31, name="H")
        base, t = edit_trend_line(base, "create", start_time="2026-09-10", start_price=30, end_time="2026-09-15", end_price=33)
        a, first = create(base)
        b, second = create(a, parallel_price=34, name="第二通道")
        updated, changed = edit_channel(b, "update", channel_id=first["id"], parallel_price=35,
                                       name="完整观察通道", color="红色", show_midline=False)
        self.assertEqual(changed["id"], first["id"])
        self.assertEqual(changed["width"], 4)
        self.assertEqual(changed["from"], first["from"])
        self.assertEqual(changed["to"], first["to"])
        self.assertEqual(changed["color"], "danger")
        self.assertFalse(changed["show_midline"])
        deleted, removed = edit_channel(updated, "delete", channel_id=first["id"])
        self.assertEqual(removed, changed)
        self.assertEqual(channels(deleted), [second])
        self.assertEqual(horizontal_lines(deleted), [h]); self.assertEqual(trend_lines(deleted), [t])
        self.assertEqual(channels(a), [first])
        read = channels(updated); read[0]["upper"]["to"]["price"] = 999
        self.assertNotEqual(channels(updated)[0]["upper"]["to"]["price"], 999)

    def test_modify_all_anchor_fields_and_recalculate(self):
        p, c = create()
        updated, changed = edit_channel(p, "update", channel_id=c["id"], start_time="2026-09-11", start_price=31,
                                       end_time="2026-09-14", end_price=32, parallel_time="2026-09-14", parallel_price=35)
        self.assertEqual(changed["width"], 3)
        self.assertEqual(changed["upper"]["to"]["price"], 35)
        self.assertEqual(changed["upper"]["from"]["price"], 34)
        self.assertEqual(updated["chartCommands"][0], p["chartCommands"][0])

    def test_invalid_geometry_and_fields_fail_without_mutation(self):
        base, c = create(); original = deepcopy(base)
        cases = [({"parallel_price": 31}, "zero_channel_width"),
                 ({"parallel_price": .1, "parallel_time": "2026-09-14"}, "invalid_channel_boundary"),
                 ({"start_time": "2026-09-15"}, "invalid_anchor_order"),
                 ({"end_time": "2026-09-10"}, "invalid_anchor_order"),
                 ({"start_time": "2026-09-14"}, "parallel_anchor_outside"),
                 ({"parallel_time": "2026-09-12"}, "anchor_not_found"),
                 ({"start_price": True}, "invalid_price"), ({"end_price": float("inf")}, "invalid_price"),
                 ({"parallel_price": -1}, "invalid_price"), ({"show_midline": 1}, "invalid_midline"),
                 ({"name": "a\nb"}, "invalid_name"), ({"color": "purple"}, "invalid_color"), ({}, "empty_update")]
        for args, code in cases:
            with self.subTest(args=args), self.assertRaises(LineError) as error:
                edit_channel(base, "update", channel_id=c["id"], **args)
            self.assertEqual(error.exception.code, code); self.assertEqual(base, original)
        for action in ["update", "delete"]:
            with self.assertRaises(LineError): edit_channel(base, action, channel_id="auto", name="x")
        with self.assertRaises(LineError): edit_channel(chart(), "create", start_price=30)

    def test_retries_normalize_alias_colors_and_capacity(self):
        a, c = create(request_id="channel-A")
        b, retry = create(a, request_id="channel-A", color="success")
        self.assertEqual(b, a); self.assertEqual(retry, c)
        with self.assertRaises(LineError): create(b, request_id="channel-A", parallel_price=34)
        for _ in range(29): a, _ = create(a)
        with self.assertRaises(LineError): create(a)
        same_parent, retry_parent = create(request_id="channel-A")
        self.assertEqual(retry_parent["id"], c["id"])

    def test_intraday_exact_times_and_period_date_matching(self):
        p = chart("minute"); rows = p["chartCommands"][0]["rows"]
        _, c = create(p, start_time=str(rows[0]["time"]), end_time=str(rows[-1]["time"]),
                      parallel_time="2026-09-11T15:00:00+08:00")
        self.assertEqual(c["interval"], "minute")
        with self.assertRaises(LineError): create(p)
        for interval in ["week", "month", "quarter", "year"]:
            _, c = create(chart(interval)); self.assertEqual(c["interval"], interval)

    def test_malformed_row_clock_cannot_make_channel(self):
        duplicate = chart(); duplicate["chartCommands"][0]["rows"].append(deepcopy(duplicate["chartCommands"][0]["rows"][1]))
        with self.assertRaises(LineError): create(duplicate)
        backwards = chart(); backwards["chartCommands"][0]["rows"].reverse()
        with self.assertRaises(LineError): create(backwards)

    def test_public_snapshot_chain_readback_scope_warning_and_no_fetch(self):
        snapshots = {"a" * 32: chart()}
        def publish(payload):
            token = str(len(snapshots)) * 32; snapshots[token] = deepcopy(payload)
            return token, "http://127.0.0.1"
        async def run():
            c = (await server.create_channel("a" * 32, "TEST.X", "2026-09-10", 30, "2026-09-15", 33, "2026-09-11", 33, "上升通道", "绿色")).structuredContent
            self.assertEqual(c["channel"]["color"], "success")
            self.assertTrue(c["verification_required"]); self.assertFalse(c["render_verified"])
            u = (await server.update_channel(c["chart_session"], "TEST.X", c["channel"]["id"], parallel_price=35, show_midline=False)).structuredContent
            state = (await server.get_channels(u["chart_session"], "TEST.X")).structuredContent
            self.assertEqual(state["channels"][0]["width"], 4)
            self.assertEqual(u["parent_chart_session"], c["chart_session"])
            d = (await server.delete_channel(u["chart_session"], "TEST.X", c["channel"]["id"])).structuredContent
            self.assertEqual(d["channels"], [])
            self.assertEqual(channels(snapshots[c["chart_session"]])[0]["width"], 2)
            self.assertTrue((await server.get_channels("a" * 32, "OTHER.X")).isError)
            self.assertTrue((await server.get_channels("z" * 32, "TEST.X")).isError)
            w = (await server.create_channel("a" * 32, "TEST.X", "2026-09-10", 30, "2026-09-15", 33, "2026-09-11", 99)).structuredContent
            self.assertTrue(w["warnings"])
            self.assertEqual(w["candle_price_range"], {"low": 28, "high": 36})
        with patch("server.read_chart_snapshot", side_effect=lambda t: deepcopy(snapshots.get(t))), patch("server.publish_chart", side_effect=publish), patch("server.fetch_candles", side_effect=AssertionError("must not fetch")):
            asyncio.run(run())

    def test_failure_never_publishes_and_publish_error_is_sanitized(self):
        with patch("server.read_chart_snapshot", return_value=chart()), patch("server.publish_chart") as publish:
            r = asyncio.run(server.create_channel("a" * 32, "TEST.X", "2026-09-10", 30, "2026-09-15", 33, "2026-09-11", 31))
            self.assertTrue(r.isError); self.assertIn("zero_channel_width", r.content[0].text); publish.assert_not_called()
        with patch("server.read_chart_snapshot", return_value=chart()), patch("server.publish_chart", side_effect=OSError("secret")):
            r = asyncio.run(server.create_channel("a" * 32, "TEST.X", "2026-09-10", 30, "2026-09-15", 33, "2026-09-11", 33))
            self.assertTrue(r.isError); self.assertNotIn("secret", str(r))

    def test_schema_requires_three_explicit_anchors(self):
        tools = asyncio.run(server.mcp.list_tools())
        self.assertTrue({"create_channel", "get_channels", "update_channel", "delete_channel", "verify_chart_drawings"} <= {t.name for t in tools})
        schema = next(t.inputSchema for t in tools if t.name == "create_channel")
        self.assertTrue({"start_time", "start_price", "end_time", "end_price", "parallel_time", "parallel_price"} <= set(schema["required"]))
        self.assertIn("绿色", schema["properties"]["color"]["enum"])

    def test_real_snapshot_publication_verification_and_whole_channel_deletion(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(chart_service, "RUNTIME_DIR", Path(directory)), patch.object(
            chart_service, "RUNTIME_SESSION_FILE", Path(directory) / "services" / "owned.json"
        ):
            service = chart_service.ChartService("127.0.0.1", 0)
            try:
                base, _ = service.publish(chart())
                with patch.object(chart_service, "_service", service):
                    c = asyncio.run(server.create_channel(base, "TEST.X", "2026-09-10", 30, "2026-09-15", 33, "2026-09-11", 33, "完整上升通道", "绿色")).structuredContent
                    saved = chart_service.read_chart_snapshot(c["chart_session"])
                    self.assertEqual(channels(saved)[0]["upper"]["to"]["price"], 35)
                    verified = asyncio.run(server.verify_chart_drawings(c["chart_session"], "TEST.X", [{"kind": "channel", "id": c["channel"]["id"], "name": "完整上升通道", "color": "绿色"}]))
                    self.assertTrue(verified.structuredContent["matches"])
                    self.assertNotIn(service.auth_token, str(verified))
                    deleted = asyncio.run(server.delete_channel(c["chart_session"], "TEST.X", c["channel"]["id"])).structuredContent
                    self.assertEqual(channels(chart_service.read_chart_snapshot(deleted["chart_session"])), [])
                    self.assertEqual(len(channels(chart_service.read_chart_snapshot(c["chart_session"]))), 1)
                    self.assertEqual(channels(chart_service.read_chart_snapshot(base)), [])
            finally:
                service.httpd.shutdown(); service.httpd.server_close()


if __name__ == "__main__": unittest.main()
