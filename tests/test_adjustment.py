import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

import server
import chart_service
import tools.fetch as fetch
from core.adjustment import normalize_adjustment
from test_provider_neutral import sample_rows as external_rows
from core.rows import validate_rows
import test_chart_edits as fixtures


def sample_rows(count):
    # Provider boundary fixtures are canonical seconds; external_rows uses milliseconds.
    return validate_rows(external_rows(count), min_len=2)


class AdjustmentTests(unittest.TestCase):
    def test_explicit_aliases_and_unknown_values(self):
        for value, expected in [("none", "none"), ("forward", "forward"), ("qfq", "forward"),
                                ("backward", "backward"), ("hfq", "backward"), (" QFQ ", "forward")]:
            self.assertEqual(normalize_adjustment(value), expected)
            self.assertEqual(fetch._adjust_to_sdk(value), expected)
        for value in [None, "", "null", "raw", "pre", "post", "unknown", True, 1, {}, []]:
            self.assertIsNone(normalize_adjustment(value))
            with self.assertRaises(ValueError): fetch._adjust_to_sdk(value)

    def test_invalid_input_is_rejected_before_fetch_resolution_publish_or_free_fallback(self):
        with patch("server.fetch_candles", side_effect=AssertionError("no fetch")), \
             patch("server._resolve_symbol_input", side_effect=AssertionError("no symbol lookup")), \
             patch("server.publish_chart", side_effect=AssertionError("no publish")), \
             patch("chart_service.fetch_candles", side_effect=AssertionError("no HTTP fetch")), \
             patch("tools.fetch._fetch_candles_ftshare", side_effect=AssertionError("no SDK")), \
             patch("tools.fetch._free_index_candles_result", side_effect=AssertionError("no fallback")):
            for value in ["bad", "", None, True, {}]:
                for fn, kwargs in [(server.analyze_kline, {"symbol": "TEST.X"}),
                                   (server.fetch_candles_tool, {"symbol": "TEST.X"}),
                                   (server.analyze_kline_rows, {"rows": sample_rows(4), "symbol": "TEST.X"})]:
                    result = asyncio.run(fn(adjust=value, **kwargs))
                    self.assertTrue(result.isError); self.assertEqual(result.structuredContent["error"], "unsupported_adjustment")
                self.assertEqual(fetch.fetch_candles("TEST.X", adjust=value)["error"], "unsupported_adjustment")
                self.assertEqual(chart_service._tool_dispatch("analyze_kline", {"symbol": "TEST.X", "adjust": value})["error"], "unsupported_adjustment")

    def test_tool_schemas_include_existing_public_values_and_precise_aliases(self):
        tools = asyncio.run(server.mcp.list_tools())
        for name in ["fetch_candles", "analyze_kline", "analyze_kline_rows"]:
            schema = next(t.inputSchema for t in tools if t.name == name)["properties"]["adjust"]
            self.assertEqual(schema["enum"], ["none", "forward", "backward", "qfq", "hfq"])
            self.assertIn("前复权", schema["description"])

    def test_analysis_uses_effective_metadata_without_transforming_rows(self):
        rows = sample_rows(4)
        for requested, effective in [("qfq", "forward"), ("hfq", "backward"), ("forward", "none")]:
            with patch("server._resolve_symbol_input", return_value=("TEST.X", "测试", None)), \
                 patch("server.fetch_candles", return_value={"ok": True, "symbol": "TEST.X", "rows": deepcopy(rows), "adjust": effective}) as get, \
                 patch("server.publish_chart", return_value=("s" * 32, "fixture")) as publish:
                response = asyncio.run(server.analyze_kline("TEST.X", limit=4, adjust=requested))
                result = response.structuredContent
            self.assertTrue(result["ok"])
            self.assertEqual(get.call_args.kwargs["adjust"], normalize_adjustment(requested))
            self.assertEqual(result["adjust"], effective)
            self.assertIn('"adjust":"' + effective + '"', response.content[0].text)
            payload = publish.call_args.args[0]
            self.assertEqual(payload["adjust"], effective)
            self.assertEqual(payload["chartCommands"][0]["rows"], rows)
            if effective != normalize_adjustment(requested): self.assertEqual(result["adjust_requested"], "forward")

    def test_unknown_provider_metadata_is_not_guessed_or_published(self):
        for value in [None, "", "unknown", {}]:
            data = {"ok": True, "rows": sample_rows(4), "adjust": value}
            with patch("server._resolve_symbol_input", return_value=("TEST.X", "测试", None)), \
                 patch("server.fetch_candles", return_value=data), patch("server.publish_chart", side_effect=AssertionError("no publish")), \
                 patch("chart_service.fetch_candles", return_value=data):
                self.assertEqual(asyncio.run(server.analyze_kline("TEST.X")).structuredContent["error"], "invalid_adjustment_metadata")
                self.assertEqual(chart_service._tool_dispatch("analyze_kline", {"symbol": "TEST.X"})["error"], "invalid_adjustment_metadata")

    def test_external_rows_and_http_use_same_canonical_names_and_effective_metadata(self):
        rows = sample_rows(4)
        with patch("server.publish_chart", return_value=("s" * 32, "fixture")) as publish:
            result = asyncio.run(server.analyze_kline_rows(rows, symbol="TEST.X", adjust="hfq")).structuredContent
        self.assertEqual(result["adjust"], "backward")
        self.assertEqual(publish.call_args.args[0]["chartCommands"][0]["rows"], rows)
        with patch("server._resolve_symbol_input", return_value=("TEST.X", "测试", None)), \
             patch("chart_service.fetch_candles", return_value={"ok": True, "rows": rows, "adjust": "none"}) as get:
            result = chart_service._tool_dispatch("analyze_kline", {"symbol": "TEST.X", "adjust": "qfq", "limit": 4})
        self.assertTrue(result["ok"]); self.assertEqual(result["adjust"], "none")
        self.assertEqual(result["adjust_requested"], "forward"); self.assertEqual(get.call_args.kwargs["adjust"], "forward")

    def test_provider_adapter_alias_and_free_index_truthful_metadata(self):
        with patch("tools.fetch._fetch_candles_ftshare", return_value={"ok": False, "error": "unavailable"}) as primary, \
             patch("tools.fetch.fetch_em_index_daily", return_value=sample_rows(4)), patch("tools.fetch.fetch_tencent_index_daily", return_value=None):
            result = fetch.fetch_candles("000300.XSHG", adjust="qfq", limit=4)
        self.assertTrue(result["ok"]); self.assertEqual(primary.call_args.kwargs["adjust"], "forward")
        self.assertEqual(result["adjust"], "none"); self.assertEqual(result["adjust_requested"], "forward")

    def test_guard_accepts_only_semantic_aliases_and_still_checks_all_rows(self):
        f = fixtures.GuardedEditTests("test_prepares_without_changing_source_context_or_other_shapes")
        f.setUp(); self.addCleanup(f.doCleanups)
        for observed, source in [("forward", "forward"), ("backward", "backward"), ("qfq", "forward"), ("hfq", "backward")]:
            with self.subTest(observed=observed, source=source):
                f.record["state"]["adjust"] = observed; f.payload["adjust"] = source
                f.save_context(); f.save_snapshot(f.token, f.payload)
                from tools.chart_context import read_chart_context
                from tools.chart_edits import require_alignment
                context = read_chart_context(f.ref, candle_scope="loaded", limit=4000)
                require_alignment(context, f.payload, f.token, f.payload["symbol"])
                for bad in ["none", "backward" if source == "forward" else "forward", "unknown", None]:
                    f.assert_code("chart_snapshot_not_aligned", lambda: require_alignment({**context, "adjust": bad}, f.payload, f.token, f.payload["symbol"]))
                dirty = deepcopy(context); dirty["candles"][0]["volume"] += 1
                f.assert_code("chart_snapshot_not_aligned", lambda: require_alignment(dirty, f.payload, f.token, f.payload["symbol"]))

    def test_us_generic_fallback_requests_unadjusted_rows_consistent_with_its_metadata(self):
        with patch("tools.fetch.ftshare_available", return_value=True), \
             patch("tools.fetch._ftshare_market_api", return_value=object()), \
             patch("tools.fetch._recent_candle_cache", return_value=None), \
             patch("tools.fetch._symbol_name", return_value="TEST"), \
             patch("tools.fetch._fetch_us_daily_candles", side_effect=OSError("fixture")), \
             patch("tools.fetch._fetch_generic_history", return_value=sample_rows(4)) as generic:
            result = fetch._fetch_candles_ftshare("NVDA.US", adjust="forward", limit=4)
        self.assertTrue(result["ok"])
        self.assertEqual(generic.call_args.kwargs["adjust_kind"], "none")
        self.assertEqual(result["adjust"], "none"); self.assertEqual(result["adjust_requested"], "forward")

    def test_global_index_without_adjustment_argument_never_claims_requested_adjustment(self):
        with patch("tools.fetch.ftshare_available", return_value=True), \
             patch("tools.fetch._ftshare_market_api", return_value=object()), \
             patch("tools.fetch._recent_candle_cache", return_value=None), \
             patch("tools.fetch._fetch_global_index_history", return_value=sample_rows(4)):
            result = fetch._fetch_candles_ftshare("100.NDX", adjust="backward", limit=4)
        self.assertTrue(result["ok"])
        self.assertEqual(result["adjust"], "none"); self.assertEqual(result["adjust_requested"], "backward")

    def test_public_forward_backward_analysis_can_prepare_and_queue_without_relabeling_prices(self):
        for adjust in ["forward", "backward"]:
            with self.subTest(adjust=adjust):
                f = fixtures.GuardedEditTests("test_prepares_without_changing_source_context_or_other_shapes")
                f.setUp()
                try:
                    rows = f.payload["chartCommands"][0]["rows"]
                    data = {"ok": True, "symbol": f.payload["symbol"], "rows": rows, "adjust": adjust}
                    with patch("server._resolve_symbol_input", return_value=(f.payload["symbol"], "测试", None)), \
                         patch("server.fetch_candles", return_value=data), patch("server.publish_chart", side_effect=f.publish):
                        analysis = asyncio.run(server.analyze_kline(f.payload["symbol"], limit=len(rows), adjust=adjust)).structuredContent
                    token = analysis["chart_session"]
                    self.assertEqual(chart_service.read_chart_snapshot(token)["adjust"], adjust)
                    f.record["guarded_apply_supported"] = True
                    f.record["state"].update(source_chart_session=token, adjust=adjust, drawings=[])
                    f.save_context()
                    candidate = f.prepare(chart_session=token)["chart_session"]
                    from tools.chart_applications import request_chart_apply
                    self.assertEqual(request_chart_apply(f.ref, candidate)["apply_status"], "queued")
                    self.assertEqual(chart_service.read_chart_snapshot(candidate)["chartCommands"][0]["rows"], rows)
                finally: f.doCleanups()
