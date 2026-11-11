"""The two hosts must turn a selected automatic result into the same edit."""
import pytest

from tools.automatic_analysis import candidate_edit_parameters, candidate_function_for_kind
from tools.lines import LineError
from tools.chart_edits import ChartEdit, edit_parameters
from codex_runtime.state import CodexChartEdit, _edit_parameters


@pytest.mark.parametrize("kind,function,summary,expected", [
    ("horizontal_line", "recent_drawing_candidates", {"drawing_type": "horizontal", "candidates": [
        {"anchors": [{"time": 10, "price": 11.0}]}]}, {"price": 11.0}),
    ("trend_line", "recent_drawing_candidates", {"drawing_type": "trend", "candidates": [
        {"anchors": [{"time": 10, "price": 11.0}, {"time": 20, "price": 12.0}]}]},
     {"start_time": "10", "start_price": 11.0, "end_time": "20", "end_price": 12.0}),
    ("fibonacci_retracement", "recent_drawing_candidates", {"drawing_type": "fibonacci", "candidates": [
        {"anchors": [{"time": 10, "price": 11.0}, {"time": 20, "price": 12.0}]}]},
     {"start_time": "10", "start_price": 11.0, "end_time": "20", "end_price": 12.0}),
    ("labeled_polyline", "recent_drawing_candidates", {"drawing_type": "abc", "candidates": [
        {"anchors": [{"time": 10, "price": 11.0}, {"time": 20, "price": 12.0},
                     {"time": 30, "price": 10.0}]}]},
     {"points": [{"label": "A", "time": "10", "price": 11.0},
                 {"label": "B", "time": "20", "price": 12.0},
                 {"label": "C", "time": "30", "price": 10.0}]}),
    ("channel", "channel_candidates", {"candidates": [{"anchors": {
        "from": {"time": 10, "price": 11.0}, "to": {"time": 20, "price": 12.0},
        "parallel": {"time": 15, "price": 13.0}}}]},
     {"start_time": "10", "start_price": 11.0, "end_time": "20", "end_price": 12.0,
      "parallel_time": "15", "parallel_price": 13.0}),
    ("rectangle", "range_candidates", {"candidates": [{"start_time": 10, "end_time": 20,
        "lower_price": 11.0, "upper_price": 13.0}]},
     {"start_time": "10", "end_time": "20", "lower_price": 11.0, "upper_price": 13.0}),
    ("price_pattern", "price_pattern_candidates", {"rule_version": "price_patterns_v1", "as_of": 30,
        "candidates": [{"type": "double_bottom", "as_of": 30}]},
     {"pattern": {"type": "double_bottom", "as_of": 30}, "rule_version": "price_patterns_v1", "as_of": 30}),
])
def test_selected_candidate_uses_one_mapping_in_both_hosts(kind, function, summary, expected):
    assert candidate_function_for_kind(kind) == function
    assert candidate_edit_parameters(kind, summary, 1) == expected


def test_selected_candidate_rejects_missing_or_forged_material():
    with pytest.raises(LineError, match="不支持"):
        candidate_function_for_kind("nine_count")
    for summary, number in (({"candidates": []}, 1), ({"candidates": [{}]}, 2),
                            ({"candidates": [{}]}, True)):
        with pytest.raises(LineError, match="候选"):
            candidate_edit_parameters("rectangle", summary, number)
    with pytest.raises(LineError, match="规则版本"):
        candidate_edit_parameters("price_pattern", {"candidates": [{"type": "double_top"}]}, 1)
    with pytest.raises(LineError, match="不匹配"):
        candidate_edit_parameters("trend_line", {"drawing_type": "horizontal", "candidates": [
            {"anchors": [{"time": 10, "price": 11.0}, {"time": 20, "price": 12.0}]}]}, 1)


@pytest.mark.parametrize("kind", ["horizontal_line", "trend_line", "fibonacci_retracement",
                                   "labeled_polyline", "channel", "rectangle", "price_pattern"])
def test_both_hosts_accept_a_bound_candidate_and_reject_mixed_manual_coordinates(kind):
    fields = {"kind": kind, "action": "create", "candidate_result_ref": "a" * 64,
              "candidate_number": 1, "user_confirmed_candidate": True}
    assert edit_parameters(ChartEdit(**fields))["candidate_result_ref"] == "a" * 64
    assert _edit_parameters(CodexChartEdit(**fields))["candidate_result_ref"] == "a" * 64
    if kind == "horizontal_line":
        mixed = {**fields, "price": 11.0}
    elif kind == "trend_line":
        mixed = {**fields, "start_price": 11.0}
    else:
        return
    with pytest.raises(LineError, match="候选"):
        edit_parameters(ChartEdit(**mixed))
    with pytest.raises(LineError, match="候选"):
        _edit_parameters(CodexChartEdit(**mixed))
