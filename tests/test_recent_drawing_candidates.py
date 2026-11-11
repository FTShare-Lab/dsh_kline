"""Automatic drawing suggestions must use recent confirmed daily bars."""
from datetime import datetime, timedelta, timezone
from math import pi, sin
from zoneinfo import ZoneInfo

import pytest

from tools.chart_functions import ChartFunctionParameters, _calculate
from tools.price_patterns import price_pattern_candidates
from tools.recent_drawing_candidates import recent_drawing_candidates
from codex_runtime.functions import run_chart_function
from codex_runtime.state import CodexChartStore


def oscillating_rows(origin, count):
    rows = []
    for index in range(count):
        close = 100 + index * .2 + 5 * sin(index * pi / 6)
        rows.append({"time": int((origin + timedelta(days=index)).timestamp()),
                     "open": close, "high": close + 1, "low": close - 1,
                     "close": close, "volume": 1000})
    return rows


@pytest.mark.parametrize("kind,count", [("horizontal", 1), ("trend", 2),
                                         ("fibonacci", 2)])
def test_recent_tools_select_confirmed_anchors_from_closed_daily_rows(kind, count):
    rows = oscillating_rows(datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")), 130)
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    result = recent_drawing_candidates(rows, symbol="600519.XSHG", provider="ftshare",
                                       drawing_type=kind, now=now)
    assert result["candidate_count"] > 0
    for candidate in result["candidates"]:
        assert len(candidate["anchors"]) == count
        assert candidate["latest_anchor_bars_ago"] <= 30
        assert candidate["latest_anchor_time"] <= rows[-3]["time"]  # two right bars confirm it
    context = {"symbol": "600519.XSHG", "interval": "day", "source_interval": "day",
               "interval_value": 1, "data_provenance": {"provider": "ftshare"}}
    shared = _calculate(None, "recent_drawing_candidates",
                        ChartFunctionParameters(drawing_type=kind), candles=rows, context=context)
    assert shared["summary"]["candidates"] == result["candidates"]


def abc_rows(c_price=105):
    origin = datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    knots = {0: 80, 30: 120, 40: 110, 47: 114, 55: c_price, 79: 115}
    rows = []
    for index in range(80):
        left = max(key for key in knots if key <= index)
        right = min(key for key in knots if key >= index)
        close = knots[left] if left == right else knots[left] + (knots[right] - knots[left]) * (index-left)/(right-left)
        rows.append({"time": int((origin + timedelta(days=index)).timestamp()),
                     "open": close, "high": close + .5, "low": close - .5,
                     "close": close, "volume": 1000})
    return rows


def test_abc_requires_origin_and_completed_third_leg_beyond_a():
    now = datetime(2026, 11, 10, tzinfo=timezone.utc)
    valid = recent_drawing_candidates(abc_rows(), symbol="600519.XSHG", provider="ftshare",
                                      drawing_type="abc", now=now)
    assert valid["rule_version"] == "recent_drawing_v2"
    assert valid["candidate_count"] == 1
    assert valid["candidates"][0]["side"] == "abc_down"
    assert [point["time"] for point in valid["candidates"][0]["anchors"]] == [abc_rows()[i]["time"] for i in (40, 47, 55)]
    assert valid["candidates"][0]["origin"]["time"] == abc_rows()[30]["time"]
    incomplete = recent_drawing_candidates(abc_rows(111), symbol="600519.XSHG", provider="ftshare",
                                           drawing_type="abc", now=now)
    assert incomplete["candidate_count"] == 0


@pytest.mark.parametrize("drawing_type,kind,command", [
    ("horizontal", "horizontal_line", "DRAW_HORIZONTAL_LINE"),
    ("trend", "trend_line", "DRAW_AGENT_TREND_LINE"),
    ("fibonacci", "fibonacci_retracement", "DRAW_AGENT_FIBONACCI"),
    ("abc", "labeled_polyline", "DRAW_AGENT_POLYLINE"),
])
def test_recent_candidate_uses_guarded_ref_for_create_and_update(drawing_type, kind, command):
    rows = abc_rows() if drawing_type == "abc" else oscillating_rows(
        datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")), 130)
    payload = {"symbol": "600519.XSHG", "interval": "day", "interval_value": 1,
               "data_meta": {"source": "ftshare"}, "chartCommands": [{"type": "SET_CANDLES", "rows": rows}]}
    store = CodexChartStore()
    state = store.create(payload)
    def analyze():
        current = store.context(state.context_ref)
        result = run_chart_function(store, state.context_ref, current["revision"], current["source_chart_session"],
                                    "600519.XSHG", "recent_drawing_candidates", {"drawing_type": drawing_type})
        assert result["summary"]["candidate_count"] > 0
        return current, result
    current, result = analyze()
    edit = {"kind": kind, "action": "create", "candidate_result_ref": result["result_ref"],
            "candidate_number": 1, "user_confirmed_candidate": True}
    prepared = store.prepare(state.context_ref, current["revision"], current["source_chart_session"],
                             "600519.XSHG", "first", edit)
    assert prepared["object"]["type"] == command
    object_id = prepared["object"]["id"]
    store.apply(state.context_ref, prepared["chart_session"])
    current, result = analyze()
    edited = store.prepare(state.context_ref, current["revision"], current["source_chart_session"],
                           "600519.XSHG", "second", {**edit, "action": "update", "object_id": object_id,
                                                       "candidate_result_ref": result["result_ref"]})
    assert edited["object"]["id"] == object_id


def test_open_current_day_does_not_change_automatic_anchors():
    zone = ZoneInfo("Asia/Shanghai")
    today = datetime(2026, 11, 9, 15, tzinfo=zone)
    rows = oscillating_rows(today - timedelta(days=130), 131)
    rows[-1]["high"] = 10000  # a dramatic but still open daily bar
    now = today.replace(hour=15, minute=30)
    full = recent_drawing_candidates(rows, symbol="600519.XSHG", provider="ftshare",
                                     drawing_type="trend", now=now)
    closed = recent_drawing_candidates(rows[:-1], symbol="600519.XSHG", provider="ftshare",
                                       drawing_type="trend", now=now)
    assert full["candidates"] == closed["candidates"]
    assert full["as_of"] == rows[-2]["time"]


def test_manual_shape_anchors_only_select_a_rule_validated_candidate():
    zone = ZoneInfo("Asia/Shanghai")
    origin = datetime(2025, 1, 1, 15, tzinfo=zone)
    knots = {0: 100, 39: 115.6, 40: 120, 45: 113, 50: 120,
             53: 112, 54: 111, 55: 110, 100: 110}
    rows = []
    for index in range(101):
        left = max(key for key in knots if key <= index)
        right = min(key for key in knots if key >= index)
        close = knots[left] if left == right else knots[left] + (knots[right] - knots[left]) * (index-left)/(right-left)
        rows.append({"time": int((origin + timedelta(days=index)).timestamp()),
                     "open": close, "high": close + .6, "low": close - .6,
                     "close": close, "volume": 1000})
    times = tuple(rows[index]["time"] for index in (40, 45, 50))
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    valid = price_pattern_candidates(rows, symbol="600519.XSHG", provider="ftshare",
                                     pattern_types=["double_top"], anchor_times=times, now=now)
    invalid = price_pattern_candidates(rows, symbol="600519.XSHG", provider="ftshare",
                                       pattern_types=["double_top"],
                                       anchor_times=(rows[39]["time"], *times[1:]), now=now)
    assert valid["candidate_count"] == 1
    assert invalid["candidate_count"] == 0
    assert invalid["rejected_reasons"]["manual_selection_not_recognized"] == 1
