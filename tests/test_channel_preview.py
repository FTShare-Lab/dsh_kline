import asyncio
from copy import deepcopy
from datetime import datetime
import json
import unittest
from unittest.mock import patch
from mcp.server.fastmcp.exceptions import ToolError

import server
from tools.channel_preview import preview_channel
from tools.channels import edit_channel
from tools.chart_context import read_chart_context
from tools.lines import LineError
import test_chart_context as context_fixtures


def candles(n=6):
    return [dict(time=i + 1, open=31+i, close=32+i, low=30+i, high=33+i, volume=1) for i in range(n)]


def params(**changes):
    return dict(start_time="1", start_price=30, end_time="6", end_price=35,
                parallel_time="3", parallel_price=35, **changes)


class ChannelPreviewTests(unittest.TestCase):
    def test_reuses_exact_execution_geometry_without_mutation_or_pattern_score(self):
        rows = candles(); before = deepcopy(rows)
        result = preview_channel(rows, "day", **params())
        payload = {"interval": "day", "chartCommands": [{"type": "SET_CANDLES", "rows": rows}]}
        _, drawing = edit_channel(payload, "create", **params())
        self.assertEqual(result["geometry"], {k: drawing[k] for k in result["geometry"]})
        self.assertEqual(result["geometry"]["slope_per_bar"], 1)
        self.assertEqual(result["geometry"]["width"], 3)
        self.assertTrue(all(v["bar_count"] == 0 for v in result["summary"].values()))
        self.assertEqual(result["anchors"]["from"]["exact_matching_ohlc_fields"], ["low"])
        self.assertEqual(result["pattern_classification"], "not_provided")
        self.assertEqual(result["quality_score"], "not_provided")
        self.assertFalse(result["drawing_created"])
        self.assertFalse(result["render_verified"])
        self.assertEqual(rows, before)

    def test_signed_two_sided_wick_and_body_deviations_and_witnesses(self):
        rows = candles()
        rows[1].update(high=40, close=39)  # upper34: wick+6, body+5
        rows[4].update(low=30, open=31)   # lower34: wick-4, body-3
        result = preview_channel(rows, "day", **params())
        self.assertEqual(result["bars"][1]["high_minus_upper"], 6)
        self.assertEqual(result["bars"][1]["body_high_minus_upper"], 5)
        self.assertEqual(result["bars"][4]["low_minus_lower"], -4)
        self.assertEqual(result["bars"][4]["body_low_minus_lower"], -3)
        for key, excess, time in (("wick_above",6,2),("body_above",5,2),("wick_below",4,5),("body_below",3,5)):
            self.assertEqual(result["summary"][key]["bar_count"], 1)
            self.assertEqual(result["summary"][key]["max_price_excess"], excess)
            self.assertEqual(result["summary"][key]["max_excess_witness"]["time"], time)
        # Negative distance from upper is NOT a touch or a breach above it.
        self.assertLess(result["bars"][0]["body_high_minus_upper"], 0)

    def test_descending_and_horizontal_do_not_choose_anchors(self):
        for start, end, parallel, direction in ((40,35,35.25,"descending"),(30,30,35.25,"horizontal")):
            args = params(); args.update(start_price=start, end_price=end, parallel_price=parallel)
            result = preview_channel(candles(), "day", **args)
            self.assertEqual(result["geometry"]["direction"], direction)
            self.assertEqual(result["anchors"]["parallel"]["price"], parallel)
            self.assertEqual(result["anchors"]["parallel"]["exact_matching_ohlc_fields"], [])

    def test_calendar_gaps_and_minute_times_use_existing_bar_indices_and_plus08_labels(self):
        rows = candles(4)
        times = ["2026-09-10T15:00:00+08:00", "2026-09-11T15:00:00+08:00",
                 "2026-09-14T15:00:00+08:00", "2026-09-15T15:00:00+08:00"]
        for row, time in zip(rows, times): row["time"] = int(datetime.fromisoformat(time).timestamp())
        args = dict(start_time="2026-09-10",start_price=30,end_time="2026-09-15",end_price=33,
                    parallel_time="2026-09-11",parallel_price=34)
        result = preview_channel(rows,"day",**args)
        self.assertEqual(result["bars"][2]["lower_price"], 32)
        self.assertEqual(result["bars"][2]["date"], "2026-09-14")
        with self.assertRaises(LineError): preview_channel(rows,"minute",**args)
        args.update(start_time=times[0],end_time=times[-1],parallel_time=times[1])
        self.assertEqual(preview_channel(rows,"minute",**args)["geometry"], result["geometry"])

    def test_subset_no_extension_and_truncation_affects_bars_not_summary(self):
        rows = candles(8)
        rows[4]["high"] = 50
        args = params(); args.update(start_time="2",start_price=31,end_time="6",end_price=35)
        result = preview_channel(rows,"day",**args,bar_limit=1)
        self.assertEqual(result["bar_count"], 5)
        self.assertEqual([b["time"] for b in result["bars"]], [2])
        self.assertTrue(result["bar_selection"]["truncated"])
        self.assertEqual(result["summary"]["wick_above"]["max_excess_witness"]["time"], 5)
        self.assertEqual(result["bars"][0]["bar_offset"], 0)
        self.assertEqual(result["range_policy"], "inclusive_start_end_only_no_extension")

    def test_weekly_holiday_and_partial_week_anchors_use_actual_bars_not_assumed_fridays(self):
        # Wednesday holiday-week and Thursday partial-week closes are legal
        # existing bar dates. Missing Friday dates must not be snapped to them.
        dates = ["2026-09-18", "2026-09-25", "2026-09-30", "2026-10-09", "2026-10-15"]
        rows = candles(5)
        for row, date in zip(rows, dates):
            row["time"] = int(datetime.fromisoformat(date+"T15:00:00+08:00").timestamp())
        args = dict(start_time=dates[0], start_price=30, end_time=dates[-1], end_price=34,
                    parallel_time=dates[2], parallel_price=35)
        original = deepcopy(rows)
        preview = preview_channel(rows, "week", **args)
        self.assertEqual(preview["bar_count"], 5)
        self.assertEqual(preview["geometry"]["slope_per_bar"], 1)
        self.assertEqual(preview["geometry"]["width"], 3)
        self.assertEqual([b["date"] for b in preview["bars"]], dates)
        payload = {"interval": "week", "chartCommands": [{"type": "SET_CANDLES", "rows": rows}]}
        created, obj = edit_channel(payload, "create", **args, name="周线观察", color="blue")
        self.assertEqual(preview["geometry"], {k: obj[k] for k in preview["geometry"]})
        changed, wider = edit_channel(created, "update", channel_id=obj["id"], parallel_price=36,
                                     color="orange", show_midline=False)
        self.assertEqual(wider["id"], obj["id"])
        self.assertEqual(wider["lower"], obj["lower"])
        self.assertEqual(wider["width"], 4)
        self.assertEqual(wider["interval"], "week")
        self.assertEqual(wider["color"], "warning")
        self.assertFalse(wider["show_midline"])
        for missing in ("2026-10-02", "2026-10-16"):
            with self.assertRaises(LineError) as exc:
                preview_channel(rows, "week", **{**args, "parallel_time": missing})
            self.assertEqual(exc.exception.code, "anchor_not_found")
        self.assertEqual(rows, original)
        self.assertEqual(created["chartCommands"][-1], obj)
        self.assertEqual(changed["chartCommands"][0]["rows"], original)

    def test_roundoff_not_market_tolerance_and_bounded_tied_witness(self):
        rows = candles()
        rows[0]["high"] += 1e-14
        rows[1]["high"] += 1e-7
        rows[2]["high"] += 1e-7
        result = preview_channel(rows,"day",**params())
        self.assertGreater(result["bars"][0]["high_minus_upper"], 0)
        self.assertEqual(result["summary"]["wick_above"]["bar_count"], 2)
        self.assertEqual(result["summary"]["wick_above"]["max_excess_witness"]["time"], 2)
        self.assertEqual(result["touch_count"], "not_provided")

    def test_invalid_prices_times_geometry_and_limit_rejected(self):
        cases = [({"start_price":v}, "invalid_price") for v in (None,True,"30",0,-1,float("nan"),float("inf"))]
        cases += [({"end_time":"1"},"invalid_anchor_order"),({"parallel_time":"9"},"anchor_not_found"),
                  ({"start_time":"2","parallel_time":"1"},"parallel_anchor_outside"),
                  ({"parallel_price":32},"zero_channel_width"),({"parallel_price":.1},"invalid_channel_boundary"),
                  ({"bar_limit":True},"invalid_preview_limit"),({"bar_limit":4001},"invalid_preview_limit")]
        for changes, code in cases:
            with self.subTest(changes=changes):
                args = params(); args.update(changes)
                with self.assertRaises(LineError) as exc: preview_channel(candles(),"day",**args)
                self.assertEqual(exc.exception.code, code)

    def test_full_region_capacity_and_no_unknown_source_fields(self):
        rows = candles(4001)
        args = params(); args.update(end_time="4000",end_price=4029)
        result = preview_channel(rows,"day",**args,bar_limit=1)
        self.assertEqual(result["bar_count"],4000)
        args.update(end_time="4001",end_price=4030)
        with self.assertRaises(LineError) as exc: preview_channel(rows,"day",**args)
        self.assertEqual(exc.exception.code,"measurement_capacity")
        rows = candles(); rows[0]["secret"] = "not copied"
        self.assertNotIn("not copied",json.dumps(preview_channel(rows,"day",**params())))

    def test_live_tool_uses_full_validated_observation_no_fetch_publish_or_write(self):
        fixture = context_fixtures.ChartContextTests("test_loaded_and_viewport_ranges_sampling_and_read_only")
        fixture.setUp()
        try:
            fixture.record["state"]["candles"] = candles(); fixture.save()
            before = {p: p.read_bytes() for p in fixture.path.parents[2].rglob("*") if p.is_file()}
            with patch("server.fetch_candles",side_effect=AssertionError("no fetch")), \
                 patch("server.publish_chart",side_effect=AssertionError("no publish")), \
                 patch("server.prepare_guarded_chart_edit",side_effect=AssertionError("no prepare")), \
                 patch("server.request_chart_apply",side_effect=AssertionError("no apply")):
                result = asyncio.run(server.preview_chart_channel(fixture.token,**params(),bar_limit=1))
            self.assertFalse(result.isError)
            data = result.structuredContent
            self.assertEqual(data["channel_preview"]["bar_count"],6)
            self.assertEqual(len(data["channel_preview"]["bars"]),1)
            self.assertEqual(data["revision"],1)
            self.assertNotIn("chart_session",data)
            self.assertNotIn("candles",data)
            self.assertNotIn("channel_preview",read_chart_context(fixture.token))
            self.assertEqual(before,{p:p.read_bytes() for p in fixture.path.parents[2].rglob("*") if p.is_file()})
            for field,value,code in (("active",False,"chart_view_inactive"),("ambiguous",True,"ambiguous_chart_views"),
                                     ("observed_at_ms",1,"chart_context_stale"),("host_process_id",7,"chart_context_unavailable")):
                old = fixture.record[field]; fixture.record[field]=value; fixture.save()
                failure = asyncio.run(server.preview_chart_channel(fixture.token,**params()))
                self.assertTrue(failure.isError)
                self.assertEqual(failure.structuredContent["error"],code)
                fixture.record[field]=old
            fixture.record["state"]["state"]="loading"; fixture.save()
            self.assertEqual(asyncio.run(server.preview_chart_channel(fixture.token,**params())).structuredContent["error"],"chart_measurement_not_ready")
        finally: fixture.doCleanups()

    def test_public_tool_readonly_schema_and_host_guidance(self):
        tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name=="preview_chart_channel")
        self.assertTrue(tool.annotations.readOnlyHint)
        self.assertTrue(tool.annotations.idempotentHint)
        self.assertEqual(set(tool.inputSchema["required"]),{"context_ref",*params()})
        self.assertIn("never searches/fits/selects",tool.description)
        self.assertIn("does not disqualify a sloped channel",tool.description)
        self.assertIn("preview_chart_channel",server.mcp.instructions)
        for changes in ({"start_price":True},{"end_price":"35"},{"bar_limit":True},{"start_time":1}):
            args=params();args.update(changes)
            with self.assertRaisesRegex(ToolError, "validation error"):
                asyncio.run(server.mcp.call_tool("preview_chart_channel",{"context_ref":"a"*32,**args}))
