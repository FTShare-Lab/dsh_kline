"""Causal rule and guarded group tests; synthetic bars are not real market evidence."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from codex_runtime.functions import run_chart_function
from codex_runtime.state import CodexChartStore
from tools.closed_daily import closed_daily
from tools.chart_functions import ChartFunctionParameters, _calculate
from tools.lines import LineError
from tools.nine_count import nine_count
from tools.pattern_groups import edit_pattern_group
from tools.price_patterns import price_pattern_candidates

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)


def price_rows(knots, count, *, reflect=False):
    zone = ZoneInfo("Asia/Shanghai")
    origin = datetime(2025, 1, 1, 15, tzinfo=zone)
    out = []
    for index in range(count):
        left = max(k for k in knots if k <= index)
        right = min(k for k in knots if k >= index)
        close = knots[left] if left == right else knots[left] + (knots[right] - knots[left]) * (index - left) / (right - left)
        if reflect:
            close = 240 - close
        out.append({"time": int((origin + timedelta(days=index)).timestamp()), "open": close,
                    "high": close + .6, "low": close - .6, "close": close, "volume": 1000})
    return out


DOUBLE = {0: 100, 39: 115.6, 40: 120, 45: 113, 50: 120, 53: 112, 54: 111, 55: 110, 100: 110}
HEAD = {0: 100, 39: 119.5, 45: 125, 50: 115, 55: 132, 60: 116, 65: 125, 70: 113, 71: 112, 72: 111, 100: 111}


@pytest.mark.parametrize("kind,knots,reflect,expected", [
    ("double_top", DOUBLE, False, [40, 45, 50]),
    ("double_bottom", DOUBLE, True, [40, 45, 50]),
    ("head_shoulders_top", HEAD, False, [45, 50, 55, 60, 65]),
    ("head_shoulders_bottom", HEAD, True, [45, 50, 55, 60, 65]),
])
def test_four_shapes_are_known_only_after_right_confirmation(kind, knots, reflect, expected):
    rows = price_rows(knots, 101, reflect=reflect)
    short = price_pattern_candidates(rows[:expected[-1] + 2], symbol="600519.XSHG", provider="ftshare",
                                     pattern_types=[kind], now=NOW)
    assert short["candidate_count"] == 0
    result = price_pattern_candidates(rows, symbol="600519.XSHG", provider="ftshare",
                                      pattern_types=[kind], now=NOW)
    chosen = next(x for x in result["candidates"] if [a["index"] for a in x["anchors"]] == expected)
    assert chosen["available_at"] == rows[expected[-1] + 2]["time"]
    assert chosen["confirmed_at"] > chosen["available_at"]
    assert [e["type"] for e in chosen["events"]].count("price_confirmed") == 1
    assert chosen["status"] == "price_confirmed"
    prefix = price_pattern_candidates(rows[:expected[-1] + 3], symbol="600519.XSHG", provider="ftshare",
                                      pattern_types=[kind], now=NOW)["candidates"][0]
    assert prefix["anchors"] == chosen["anchors"]
    assert prefix["available_at"] == chosen["available_at"]


def test_single_close_cancels_pending_and_two_reclaims_fail_after_confirmation():
    knots = dict(DOUBLE)
    knots.update({53: 110, 54: 114, 55: 115, 100: 115})
    single = price_pattern_candidates(price_rows(knots, 80), symbol="600519.XSHG", provider="ftshare",
                                      pattern_types=["double_top"], now=NOW)["candidates"][0]
    assert "pending_confirmation" in [e["type"] for e in single["events"]]
    assert "pending_cancelled" in [e["type"] for e in single["events"]]
    assert single["confirmed_at"] is None
    knots = dict(DOUBLE)
    knots.update({56: 110, 57: 114, 58: 114, 100: 114})
    failed = price_pattern_candidates(price_rows(knots, 90), symbol="600519.XSHG", provider="ftshare",
                                      pattern_types=["double_top"], now=NOW)["candidates"][0]
    assert failed["status"] == "breakout_failed"
    assert [e["type"] for e in failed["events"]][-2:] == ["price_confirmed", "breakout_failed"]


def test_sixty_bar_confirmation_boundary_and_observation_end_are_causal():
    quiet = {i: value for i, value in DOUBLE.items() if i <= 50}
    quiet.update({53: 115, 120: 115})
    rows = price_rows(quiet, 114)
    def analyze(prefix):
        return price_pattern_candidates(prefix, symbol="600519.XSHG", provider="ftshare",
                                        pattern_types=["double_top"], now=NOW)["candidates"][0]
    assert analyze(rows[:113])["status"] == "candidate"  # index 112 is the 60th follow-up bar
    assert analyze(rows)["status"] == "expired"  # index 113 ends the candidate
    for index in (111, 112):
        rows[index].update(open=110, high=110.6, low=109.4, close=110)
    confirmed = analyze(rows[:113])
    assert confirmed["status"] == "price_confirmed"
    assert confirmed["confirmed_at"] == rows[112]["time"]
    assert "expired" not in [event["type"] for event in confirmed["events"]]
    followup = price_pattern_candidates(price_rows(DOUBLE, 80), symbol="600519.XSHG",
                                        provider="ftshare", pattern_types=["double_top"], now=NOW)["candidates"][0]
    assert followup["events"][-1]["type"] == "followup_complete"
    assert followup["status"] == "price_confirmed"


def test_platform_freezes_box_before_breakout_and_preserves_confirmation_event():
    closes = [100 + .1 * i for i in range(30)] + [101, 109, 101, 109, 105] * 4 + [113, 114] + [105] * 24
    rows = price_rows({i: c for i, c in enumerate(closes)}, len(closes))
    result = price_pattern_candidates(rows, symbol="600519.XSHG", provider="ftshare",
                                      pattern_types=["platform"], now=NOW)
    failed = next(x for x in result["candidates"] if x["status"] == "breakout_failed")
    assert failed["box"]["end_time"] < rows[50]["time"]
    assert failed["box"]["upper_price"] < rows[50]["high"]
    assert [e["type"] for e in failed["events"]] == ["candidate", "pending_confirmation", "price_confirmed", "breakout_failed"]


def test_nine_labels_are_causal_pause_after_nine_and_restart_after_reset():
    closes = [10] * 5 + list(range(11, 27))
    closes += [closes[-4], 28, 29, 30, 31, 32, 33, 34, 35, 36, 37]
    rows = price_rows({i: c for i, c in enumerate(closes)}, len(closes))
    result = nine_count(rows, symbol="600519.XSHG", provider="ftshare", display_bars=120 if len(rows) >= 120 else 30, now=NOW)
    first = [m for m in result["marks"] if m["index"] <= 20]
    assert [m["count"] for m in first] == list(range(1, 10))
    assert len(result["events"]) >= 1
    assert result["events"][0]["label"] == "上涨九转计数完成"
    assert all(m["index"] <= 13 for m in first)
    assert nine_count(rows[:14], symbol="600519.XSHG", provider="ftshare", display_bars=30, now=NOW)["marks"] == [
        m for m in result["marks"] if m["index"] < 14]


def test_nine_left_edge_equal_reversal_and_known_gap_are_explicit():
    closes = [10] * 5 + list(range(11, 26)) + [25] * 5 + list(range(24, 9, -1))
    rows = price_rows({i: value for i, value in enumerate(closes)}, len(closes))
    result = nine_count(rows, symbol="600519.XSHG", provider="ftshare", display_bars=120, now=NOW)
    assert result["marks"][0]["count"] == 1
    assert any(mark["direction"] == "down" and mark["count"] == 1 for mark in result["marks"])
    assert "left_boundary_run_censored_until_interruption" not in result["limitations"]
    clipped = price_rows({i: 10 + i for i in range(30)}, 30)
    clipped_result = nine_count(clipped, symbol="600519.XSHG", provider="ftshare", display_bars=30, now=NOW)
    assert clipped_result["marks"] == []
    assert "left_boundary_run_censored_until_interruption" in clipped_result["limitations"]
    segmented = nine_count(rows, symbol="600519.XSHG", provider="ftshare", display_bars=120,
                           known_gap_indexes=(10,), now=NOW)
    assert "known_gaps_segmented" in segmented["limitations"]
    assert not any(10 <= mark["index"] <= 14 for mark in segmented["marks"])
    assert segmented["marks"][:4] == result["marks"][:4]


@pytest.mark.parametrize("symbol,zone,before,after", [
    ("600519.XSHG", "Asia/Shanghai", (15, 39), (15, 40)),
    ("00700.HK", "Asia/Hong_Kong", (16, 19), (16, 20)),
    ("AAPL.US", "America/New_York", (16, 9), (16, 10)),
])
def test_conservative_exchange_cutoff(symbol, zone, before, after):
    local = ZoneInfo(zone)
    day = datetime(2026, 11, 9, 16, tzinfo=local)
    rows = [{"time": int(day.timestamp()), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100}]
    earlier = day.replace(hour=before[0], minute=before[1])
    later = day.replace(hour=after[0], minute=after[1])
    assert closed_daily(rows, symbol=symbol, interval="day", provider="ftshare", now=earlier)[0] == []
    assert closed_daily(rows, symbol=symbol, interval="day", provider="ftshare", now=later)[0] == rows


def test_unknown_source_excludes_today_and_non_daily_is_explicitly_rejected():
    zone = ZoneInfo("America/New_York")
    current = datetime(2026, 11, 9, 16, tzinfo=zone)
    rows = [{"time": int(current.timestamp()), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100}]
    selected, quality = closed_daily(rows, symbol="AAPL.US", interval="day", provider="unknown", now=current.replace(hour=17))
    assert selected == [] and "source_unknown_current_day_excluded" in quality["quality"]
    with pytest.raises(LineError, match="单日线"):
        closed_daily(rows, symbol="AAPL.US", interval="week", provider="ftshare", now=NOW)
    with pytest.raises(LineError, match="单日线"):
        closed_daily(rows, symbol="AAPL.US", interval="day", interval_value=None, provider="ftshare", now=NOW)


def test_dst_half_day_future_and_uncertain_current_date():
    for date in ((2026, 3, 6), (2026, 3, 9), (2026, 11, 2)):
        zone = ZoneInfo("America/New_York")
        session = datetime(*date, 16, 0, tzinfo=zone)
        row = {"time": int(session.timestamp()), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100}
        assert closed_daily([row], symbol="AAPL.US", interval="day", provider="ftshare",
                            now=session.replace(hour=16, minute=9))[0] == []
        assert closed_daily([row], symbol="AAPL.US", interval="day", provider="ftshare",
                            now=session.replace(hour=16, minute=10))[0] == [row]
    cn = ZoneInfo("Asia/Shanghai")
    half_day = datetime(2026, 11, 9, 12, 0, tzinfo=cn)
    row = {"time": int(half_day.timestamp()), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100}
    assert closed_daily([row], symbol="600519.XSHG", interval="day", provider="ftshare", now=half_day)[0] == []
    assert closed_daily([row], symbol="600519.XSHG", interval="day", provider="ftshare",
                        now=half_day.replace(hour=15, minute=40))[0] == [row]
    uncertain = dict(row, time=int(half_day.replace(hour=0).timestamp()))
    future = dict(row, time=int(half_day.replace(day=10).timestamp()))
    accepted, quality = closed_daily([uncertain, row, future], symbol="600519.XSHG", interval="day",
                                     provider="ftshare", now=half_day.replace(hour=15, minute=40))
    assert accepted == [row]
    assert "date_semantics_uncertain_current_day_excluded" in quality["quality"]
    assert "future_daily_bar_excluded" in quality["quality"]


def test_group_requires_scoped_analysis_and_updates_atomically():
    rows = price_rows(DOUBLE, 101)
    payload = {"symbol": "600519.XSHG", "interval": "day", "chartCommands": [{"type": "SET_CANDLES", "rows": rows}]}
    pattern = price_pattern_candidates(rows, symbol="600519.XSHG", provider="ftshare",
                                       pattern_types=["double_top"], now=NOW)["candidates"][0]
    edited, obj = edit_pattern_group(payload, "create", kind="price_pattern", pattern=pattern,
                                     rule_version="price_patterns_v1", as_of=rows[-1]["time"], request_id="one")
    assert obj["id"].startswith("pattern_") and len(edited["chartCommands"]) == 2
    renamed, after = edit_pattern_group(edited, "update", kind="price_pattern", group_id=obj["id"], name="双顶")
    assert after["id"] == obj["id"] and after["geometry_hash"] == obj["geometry_hash"]
    assert len(renamed["chartCommands"]) == 2 and edited["chartCommands"][1]["label"] == ""
    with pytest.raises(LineError, match="形成区间|锚点"):
        edit_pattern_group(payload | {"chartCommands": [{"type": "SET_CANDLES", "rows": rows[60:]}]}, "create",
                           kind="price_pattern", pattern=pattern, rule_version="price_patterns_v1",
                           as_of=rows[-1]["time"], request_id="cropped")
    removed, _ = edit_pattern_group(renamed, "delete", kind="price_pattern", group_id=obj["id"])
    assert len(removed["chartCommands"]) == 1


def test_codex_candidate_ref_cannot_be_forged_or_reused_after_revision():
    rows = price_rows(DOUBLE, 101)
    store = CodexChartStore()
    state = store.create({"symbol": "600519.XSHG", "interval": "day", "interval_value": 1,
                          "data_meta": {"source": "ftshare"}, "chartCommands": [{"type": "SET_CANDLES", "rows": rows}]})
    result = run_chart_function(store, state.context_ref, 1, state.chart_session, "600519.XSHG",
                                "price_pattern_candidates", {"pattern_types": ["double_top"]})
    assert result["summary"]["candidate_count"] >= 1
    with pytest.raises(LineError, match="候选"):
        store.prepare(state.context_ref, 1, state.chart_session, "600519.XSHG", "no", {
            "kind": "price_pattern", "action": "create", "candidate_result_ref": result["result_ref"], "candidate_number": 1})
    prepared = store.prepare(state.context_ref, 1, state.chart_session, "600519.XSHG", "yes", {
        "kind": "price_pattern", "action": "create", "candidate_result_ref": result["result_ref"],
        "candidate_number": 1, "user_confirmed_candidate": True})
    assert prepared["object"]["type"] == "DRAW_AGENT_PRICE_PATTERN"
    store.apply(state.context_ref, prepared["chart_session"])
    with pytest.raises(LineError, match="版本"):
        store.prepare(state.context_ref, 1, state.chart_session, "600519.XSHG", "stale", {
            "kind": "price_pattern", "action": "create", "candidate_result_ref": result["result_ref"],
            "candidate_number": 1, "user_confirmed_candidate": True})


def test_dsh_and_codex_share_exact_pattern_and_nine_summaries_and_guarded_nine_result():
    rows = price_rows(DOUBLE, 101)
    payload = {"symbol": "600519.XSHG", "interval": "day", "interval_value": 1,
               "data_meta": {"source": "ftshare"}, "chartCommands": [{"type": "SET_CANDLES", "rows": rows}]}
    store = CodexChartStore()
    state = store.create(payload)
    context = {"symbol": "600519.XSHG", "interval": "day", "source_interval": "day",
               "interval_value": 1, "data_provenance": {"provider": "ftshare"}}
    for function, params in (("price_pattern_candidates", {"pattern_types": ["double_top"]}),
                             ("nine_count", {"display_bars": 120})):
        codex = run_chart_function(store, state.context_ref, 1, state.chart_session,
                                   "600519.XSHG", function, params)
        dsh = _calculate(payload, function, ChartFunctionParameters(**params), candles=rows, context=context)
        assert codex["summary"] == dsh["summary"]
        if function == "nine_count" and codex["summary"]["marks"]:
            prepared = store.prepare(state.context_ref, 1, state.chart_session, "600519.XSHG", "nine", {
                "kind": "nine_count", "action": "create", "result_ref": codex["result_ref"]})
            assert prepared["object"]["type"] == "DRAW_AGENT_NINE_COUNT"
            store.apply(state.context_ref, prepared["chart_session"])
            with pytest.raises(LineError, match="版本"):
                store.prepare(state.context_ref, 1, state.chart_session, "600519.XSHG", "stale-nine", {
                    "kind": "nine_count", "action": "update", "object_id": prepared["object"]["id"],
                    "result_ref": codex["result_ref"]})


@pytest.mark.parametrize("case_index", range(20))
def test_frozen_real_daily_cases_and_independent_anchor_checks(case_index):
    fixture = json.loads((Path(__file__).parents[1] / "docs" / "fixtures" / "price-pattern-real-v1.json").read_text())
    case = fixture["cases"][case_index]
    series = fixture["series"][case["series"]]
    rows = series["rows"]
    result = price_pattern_candidates(rows, symbol=series["symbol"], provider=series["source"],
                                      volume_unit=series["volume_unit"], pattern_types=[case["class"]], now=NOW)
    if case["label"] == "negative":
        assert result["candidate_count"] == 0
        assert result["rejected_reasons"] == case["expected"]["rejected_reasons"]
        return
    expected = case["expected"]
    matches = [c for c in result["candidates"] if [a["time"] for a in c["anchors"]] == expected["anchor_times"]]
    assert matches, case
    chosen = matches[0]
    assert chosen["available_at"] == expected["available_at"]
    assert chosen["status"] == expected["status"]
    assert chosen["confirmed_at"] == expected["confirmed_at"]
    assert chosen["invalidated_at"] == expected["invalidated_at"]
    assert chosen.get("box") == expected["box"]
    positions = {row["time"]: i for i, row in enumerate(rows)}
    if case["class"] == "platform":
        assert positions[chosen["box"]["end_time"]] == positions[chosen["available_at"]]
        assert chosen["box"]["lower_price"] < chosen["box"]["upper_price"]
    else:
        for anchor in chosen["anchors"]:
            i = positions[anchor["time"]]
            neighbors = rows[i - 2:i] + rows[i + 1:i + 3]
            field = "high" if anchor["side"] == "high" else "low"
            compare = all(anchor["price"] > r[field] for r in neighbors) if field == "high" else all(anchor["price"] < r[field] for r in neighbors)
            assert compare and anchor["price"] == rows[i][field]
        assert positions[chosen["available_at"]] == positions[chosen["anchors"][-1]["time"]] + 2
