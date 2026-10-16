import asyncio
from copy import deepcopy
from datetime import datetime
import unittest
from unittest.mock import patch

import server
from tools.lines import LineError, edit_horizontal_line, horizontal_lines
from tools.trend_lines import edit_trend_line, trend_lines, resolve_anchor_time


def chart(interval="day"):
    times = [int(datetime.fromisoformat(s).timestamp()) for s in
             ["2026-09-10T15:00:00+08:00", "2026-09-11T15:00:00+08:00", "2026-09-14T15:00:00+08:00"]]
    return {"symbol": "TEST.X", "interval": interval, "count": 3, "chartCommands": [
        {"type": "SET_CANDLES", "rows": [{"time": t, "low": 29, "high": 34} for t in times]},
        {"type": "DRAW_TREND_LINE", "id": "auto"}]}


def create(payload=None, **kwargs):
    return edit_trend_line(payload or chart(), "create", start_time="2026-09-10", start_price=32,
                           end_time="2026-09-14", end_price=30, name="T1", **kwargs)


class TrendLineTests(unittest.TestCase):
    def test_crud_identity_copy_and_mixed_preservation(self):
        base, horizontal = edit_horizontal_line(chart(), "create", price=31, name="H")
        original = deepcopy(base)
        a, first = create(base)
        b, second = edit_trend_line(a, "create", start_time="2026-09-10", start_price=29,
                                   end_time="2026-09-14", end_price=31, name="T2")
        changed, updated = edit_trend_line(b, "update", line_id=first["id"], start_time="2026-09-11",
                                         end_price=29.5, name="下降参考", color="danger")
        deleted, removed = edit_trend_line(changed, "delete", line_id=first["id"])
        self.assertEqual(base, original)
        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(updated["from"]["price"], 32)
        self.assertEqual(updated["from"]["time"], chart()["chartCommands"][0]["rows"][1]["time"])
        self.assertEqual(updated["to"]["price"], 29.5)
        self.assertEqual(trend_lines(deleted), [second])
        self.assertEqual(removed, updated)
        self.assertEqual(horizontal_lines(deleted), [horizontal])
        self.assertEqual(deleted["chartCommands"][:2], original["chartCommands"][:2])
        read = trend_lines(changed); read[0]["from"]["price"] = 999
        self.assertEqual(trend_lines(changed)[0]["from"]["price"], 32)
        shortened, short = edit_trend_line(a, "update", line_id=first["id"], end_time="2026-09-11")
        self.assertEqual(short["to"]["time"], chart()["chartCommands"][0]["rows"][1]["time"])
        self.assertEqual(short["to"]["price"], 30)
        self.assertEqual(short["id"], first["id"])

    def test_exact_dates_and_explicit_times(self):
        for interval in ["day", "week", "month", "quarter", "year"]:
            p = chart(interval)
            self.assertEqual(resolve_anchor_time(p, "2026-09-10"), p["chartCommands"][0]["rows"][0]["time"])
        p = chart("5m"); expected = p["chartCommands"][0]["rows"][0]["time"]
        for value in [str(expected), "2026-09-10T15:00:00+08:00", "2026-09-10T07:00:00Z"]:
            self.assertEqual(resolve_anchor_time(p, value), expected)
        for value in ["2026-09-10", "2026-09-10T15:00:00", str(expected * 1000), "2026-09-10T15:00:01+08:00", "2026-02-30"]:
            with self.assertRaises(LineError): resolve_anchor_time(p, value)
        with self.assertRaises(LineError) as error: resolve_anchor_time(chart(), "2026-09-12")
        self.assertEqual(error.exception.code, "anchor_not_found")
        duplicate = chart()
        duplicate["chartCommands"][0]["rows"].append(deepcopy(duplicate["chartCommands"][0]["rows"][0]))
        with self.assertRaises(LineError) as ambiguous: resolve_anchor_time(duplicate, "2026-09-10")
        self.assertEqual(ambiguous.exception.code, "ambiguous_anchor_time")

    def test_failures_do_not_mutate(self):
        base, line = create(); original = deepcopy(base)
        for changes in [{"start_time": "2026-09-14"}, {"end_time": "2026-09-10"},
                        {"start_price": -1}, {"end_price": float("nan")}, {"start_price": True},
                        {"name": "a\nb"}, {"color": "purple"}, {}, {"end_time": "2026-09-12"}]:
            with self.assertRaises(LineError): edit_trend_line(base, "update", line_id=line["id"], **changes)
            self.assertEqual(base, original)
        for action in ["update", "delete"]:
            with self.assertRaises(LineError): edit_trend_line(base, action, line_id="auto", name="x")
        with self.assertRaises(LineError): edit_trend_line(chart(), "create", start_price=30)

    def test_retry_and_capacity(self):
        p, first = create(request_id="T")
        retry, second = create(p, request_id="T")
        self.assertEqual(retry, p); self.assertEqual(second, first)
        with self.assertRaises(LineError):
            edit_trend_line(p, "create", start_time="2026-09-10", start_price=31, end_time="2026-09-14", end_price=30, request_id="T")
        for _ in range(59): p, _ = create(p)
        with self.assertRaises(LineError): create(p)

    def test_public_tools_snapshot_chain_and_no_market_fetch(self):
        snapshots = {"a" * 32: chart()}
        def publish(payload):
            token = str(len(snapshots)) * 32; snapshots[token] = deepcopy(payload)
            return token, "http://127.0.0.1"
        async def run():
            created = (await server.create_trend_line("a" * 32, "TEST.X", "2026-09-10", 32, "2026-09-14", 30, "T1")).structuredContent
            self.assertFalse(created["render_verified"])
            self.assertEqual(created["parent_chart_session"], "a" * 32)
            line_id = created["line"]["id"]
            updated = (await server.update_trend_line(created["chart_session"], "TEST.X", line_id, end_price=29.5)).structuredContent
            state = (await server.get_trend_lines(updated["chart_session"], "TEST.X")).structuredContent
            self.assertEqual(state["lines"][0]["to"]["price"], 29.5)
            deleted = (await server.delete_trend_line(updated["chart_session"], "TEST.X", line_id)).structuredContent
            self.assertEqual(deleted["lines"], [])
            self.assertEqual(trend_lines(snapshots[created["chart_session"]])[0]["to"]["price"], 30)
            self.assertTrue((await server.get_trend_lines("a" * 32, "OTHER.X")).isError)
            self.assertTrue((await server.get_trend_lines("z" * 32, "TEST.X")).isError)
            warning = (await server.create_trend_line("a" * 32, "TEST.X", "2026-09-10", 99, "2026-09-14", 100)).structuredContent
            self.assertIn("warnings", warning)
            self.assertEqual(warning["out_of_range_prices"], [99, 100])
            self.assertEqual(warning["candle_price_range"], {"low": 29, "high": 34})
        with patch("server.read_chart_snapshot", side_effect=lambda t: deepcopy(snapshots.get(t))), patch("server.publish_chart", side_effect=publish), patch("server.fetch_candles", side_effect=AssertionError("no fetch")):
            asyncio.run(run())

    def test_publish_failure_and_validation_failure_do_not_publish(self):
        with patch("server.read_chart_snapshot", return_value=chart()), patch("server.publish_chart") as publish:
            result = asyncio.run(server.create_trend_line("a" * 32, "TEST.X", "2026-09-12", 32, "2026-09-14", 30))
            self.assertTrue(result.isError); publish.assert_not_called()
            self.assertIn("error=anchor_not_found", result.content[0].text)
        with patch("server.read_chart_snapshot", return_value=chart()), patch("server.publish_chart", side_effect=OSError("secret")):
            result = asyncio.run(server.create_trend_line("a" * 32, "TEST.X", "2026-09-10", 32, "2026-09-14", 30))
            self.assertTrue(result.isError); self.assertNotIn("secret", str(result))

    def test_mcp_schema_exposes_four_tools(self):
        tools = asyncio.run(server.mcp.list_tools())
        names = {t.name for t in tools}
        self.assertTrue({"create_trend_line", "get_trend_lines", "update_trend_line", "delete_trend_line"} <= names)
        schema = next(t.inputSchema for t in tools if t.name == "create_trend_line")
        self.assertTrue({"chart_session", "symbol", "start_time", "start_price", "end_time", "end_price"} <= set(schema["required"]))
        self.assertEqual(schema["properties"]["start_time"]["type"], "string")


if __name__ == "__main__":
    unittest.main()
