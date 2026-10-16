import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import chart_service
import server
from tools.lines import LineError, edit_horizontal_line, horizontal_lines


def chart():
    return {"symbol": "TEST.X", "interval": "day", "count": 2,
            "chartCommands": [{"type": "SET_CANDLES", "rows": [
                {"time": 1700000000, "open": 30, "high": 31, "low": 29, "close": 30, "volume": 1},
                {"time": 1700086400, "open": 30, "high": 31, "low": 29, "close": 30, "volume": 2},
            ]}, {"type": "SET_RANGE", "start": 1700000000, "end": 1700086400},
                {"type": "TEXT_MARKER", "id": "auto", "price": 31, "time": 1700086400}]}


class HorizontalLineTests(unittest.TestCase):
    def test_create_move_rename_delete_preserves_source(self):
        base = chart(); original = deepcopy(base)
        created, a = edit_horizontal_line(base, "create", price=30, name="A")
        with_b, b = edit_horizontal_line(created, "create", price=32, name="B")
        updated, moved = edit_horizontal_line(with_b, "update", line_id=a["id"], price=29.5, name="观察线")
        deleted, removed = edit_horizontal_line(updated, "delete", line_id=a["id"])
        self.assertEqual(base, original)
        self.assertEqual(horizontal_lines(created)[0]["price"], 30)
        self.assertEqual(moved["id"], a["id"])
        self.assertEqual(moved["label"], "观察线")
        self.assertEqual(moved["price"], 29.5)
        self.assertEqual(horizontal_lines(deleted), [b])
        self.assertEqual(removed, moved)
        self.assertEqual(deleted["chartCommands"][:3], original["chartCommands"])

    def test_invalid_prices_are_rejected_without_mutation(self):
        base = chart(); original = deepcopy(base)
        for price in [0, -1, float("nan"), float("inf"), True, "30"]:
            with self.subTest(price=price), self.assertRaises(LineError):
                edit_horizontal_line(base, "create", price=price)
        self.assertEqual(base, original)

    def test_unknown_ids_and_empty_updates_do_not_change_chart(self):
        created, line = edit_horizontal_line(chart(), "create", price=30)
        for action in ["update", "delete"]:
            with self.assertRaises(LineError) as error:
                edit_horizontal_line(created, action, line_id="auto", price=31)
            self.assertEqual(error.exception.code, "line_not_found")
        with self.assertRaises(LineError):
            edit_horizontal_line(created, "update", line_id=line["id"])
        self.assertEqual(horizontal_lines(created)[0]["price"], 30)

    def test_retries_are_idempotent_and_conflicts_fail(self):
        a, first = edit_horizontal_line(chart(), "create", price=30, name="A", request_id="request-A")
        b, second = edit_horizontal_line(a, "create", price=30, name="A", request_id="request-A")
        self.assertEqual(first, second)
        self.assertEqual(a, b)
        with self.assertRaises(LineError) as error:
            edit_horizontal_line(b, "create", price=32, name="A", request_id="request-A")
        self.assertEqual(error.exception.code, "request_conflict")

    def test_capacity_name_color_and_read_copy(self):
        base = chart()
        for i in range(60): base, _ = edit_horizontal_line(base, "create", price=i + 1)
        with self.assertRaises(LineError): edit_horizontal_line(base, "create", price=30)
        for args in [{"name": "x" * 49}, {"name": "a\nb"}, {"color": "purple"}, {"request_id": ""}]:
            with self.assertRaises(LineError): edit_horizontal_line(chart(), "create", price=30, **args)
        read = horizontal_lines(base); read[0]["price"] = 999
        self.assertEqual(horizontal_lines(base)[0]["price"], 1)

    def test_public_tools_end_to_end_without_fetching(self):
        snapshots = {"a" * 32: chart()}
        def read(token): return deepcopy(snapshots.get(token))
        def publish(payload):
            token = str(len(snapshots)) * 32
            snapshots[token] = deepcopy(payload)
            return token, "http://127.0.0.1:1"
        async def run():
            created = await server.create_horizontal_line("a" * 32, "TEST.X", 30, "A")
            c = created.structuredContent
            self.assertIn(c["line"]["id"], created.content[0].text)
            self.assertFalse(c["render_verified"])
            self.assertEqual(c["operation_status"], "published")
            updated = await server.update_horizontal_line(c["chart_session"], "TEST.X", c["line"]["id"], 29.5, "观察线")
            u = updated.structuredContent
            state = (await server.get_horizontal_lines(u["chart_session"], "TEST.X")).structuredContent
            self.assertEqual(state["lines"][0]["price"], 29.5)
            self.assertEqual(state["lines"][0]["label"], "观察线")
            deleted = await server.delete_horizontal_line(u["chart_session"], "TEST.X", c["line"]["id"])
            self.assertEqual(deleted.structuredContent["lines"], [])
            self.assertEqual(horizontal_lines(snapshots[c["chart_session"]])[0]["price"], 30)
            wrong = await server.create_horizontal_line("a" * 32, "OTHER.X", 30)
            missing = await server.get_horizontal_lines("x" * 32, "TEST.X")
            self.assertTrue(wrong.isError); self.assertTrue(missing.isError)
        with patch("server.read_chart_snapshot", side_effect=read), patch("server.publish_chart", side_effect=publish), patch(
            "server.fetch_candles", side_effect=AssertionError("drawing must not fetch")
        ):
            asyncio.run(run())

    def test_publish_failure_is_not_success(self):
        with patch("server.read_chart_snapshot", return_value=chart()), patch("server.publish_chart", side_effect=OSError("secret")):
            result = asyncio.run(server.create_horizontal_line("a" * 32, "TEST.X", 30))
        self.assertTrue(result.isError)
        self.assertNotIn("secret", str(result))

    def test_snapshot_scope_and_token_validation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(chart_service, "RUNTIME_DIR", Path(directory)):
            dest = Path(directory) / "sessions"; dest.mkdir()
            token = "a" * 32
            data = {"ok": True, "session": token, "host_process_id": chart_service.HOST_PROCESS_ID, "payload": chart()}
            path = dest / f"{token}.json"; path.write_text(json.dumps(data))
            self.assertEqual(chart_service.read_chart_snapshot(token), chart())
            self.assertIsNone(chart_service.read_chart_snapshot("../" + token))
            data["host_process_id"] += 1; path.write_text(json.dumps(data))
            self.assertIsNone(chart_service.read_chart_snapshot(token))

    def test_registered_schema_has_explicit_line_tools(self):
        tools = asyncio.run(server.mcp.list_tools())
        indexed = {t.name: t for t in tools}
        for name in ["create_horizontal_line", "get_horizontal_lines", "update_horizontal_line", "delete_horizontal_line"]:
            self.assertIn(name, indexed)
        self.assertEqual(indexed["create_horizontal_line"].inputSchema["required"], ["chart_session", "symbol", "price"])

    def test_real_publication_reads_persisted_snapshots_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(chart_service, "RUNTIME_DIR", Path(directory)), patch.object(
            chart_service, "RUNTIME_SESSION_FILE", Path(directory) / "services" / "owned.json"
        ):
            service = chart_service.ChartService("127.0.0.1", 0)
            try:
                base, _ = service.publish(chart())
                with patch.object(chart_service, "_service", service):
                    created = asyncio.run(server.create_horizontal_line(base, "TEST.X", 30, "A"))
                    data = created.structuredContent
                    self.assertTrue(data["chart_ready"])
                    self.assertNotIn(service.auth_token, str(created))
                    saved = chart_service.read_chart_snapshot(data["chart_session"])
                    self.assertEqual(horizontal_lines(saved)[0]["price"], 30)
                    self.assertEqual(horizontal_lines(chart_service.read_chart_snapshot(base)), [])
                    moved = asyncio.run(server.update_horizontal_line(data["chart_session"], "TEST.X", data["line"]["id"], price=29.5))
                    self.assertEqual(horizontal_lines(chart_service.read_chart_snapshot(moved.structuredContent["chart_session"]))[0]["price"],29.5)
                    deleted = asyncio.run(server.delete_horizontal_line(moved.structuredContent["chart_session"], "TEST.X", data["line"]["id"]))
                    self.assertEqual(horizontal_lines(chart_service.read_chart_snapshot(deleted.structuredContent["chart_session"])), [])
            finally:
                service.httpd.shutdown(); service.httpd.server_close()


if __name__ == "__main__": unittest.main()
