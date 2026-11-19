from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from codex_runtime.state import CodexChartStore
from codex_runtime.drawing_tasks import draw_many
from tools.lines import LineError
from test_codex_v060 import payload
from test_recent_drawing_candidates import oscillating_rows


def test_codex_batch_undo_redo_preserves_other_data_and_rejects_unconfirmed_history():
    store = CodexChartStore()
    state = store.create(payload())
    original = deepcopy(state.payload)
    def prepare(edit, request):
        return store.prepare(state.context_ref, state.revision, state.chart_session, "TEST.X", request, edit)
    first = prepare({"kind": "drawing_batch", "action": "create", "edits": [
        {"kind": "horizontal_line", "action": "create", "price": 100.0},
        {"kind": "horizontal_line", "action": "create", "price": 110.0}]}, "two")
    assert len(first["object"]["objects"]) == 2
    store.apply(state.context_ref, first["chart_session"])
    after = deepcopy(state.payload)
    edit = {"kind": "drawing_history", "action": "update", "history_session": first["chart_session"], "history_direction": "undo"}
    with pytest.raises(LineError, match="App"):
        prepare(edit, "unconfirmed")
    store.acknowledge(state.context_ref, first["chart_session"], rendered=True)
    undo = prepare(edit, "undo")
    store.apply(state.context_ref, undo["chart_session"])
    assert state.payload["chartCommands"] == original["chartCommands"]
    store.acknowledge(state.context_ref, undo["chart_session"], rendered=True)
    redo = prepare({**edit, "history_direction": "redo"}, "redo")
    store.apply(state.context_ref, redo["chart_session"])
    assert state.payload["chartCommands"] == after["chartCommands"]


def test_codex_multi_tool_task_uses_same_candidates_and_replay_cannot_restore_old_payload():
    store = CodexChartStore()
    value = payload()
    value.update(symbol="600519.XSHG", data_meta={"source": "ftshare"})
    value["chartCommands"][0]["rows"] = oscillating_rows(datetime(2025, 1, 1, 15, tzinfo=ZoneInfo("Asia/Shanghai")), 130)
    state = store.create(value)
    args = (store, state.context_ref, value["symbol"], "combo", [{"tool": "horizontal"}, {"tool": "trend"}])
    result = draw_many(*args)
    assert result["status"] == "applied"
    assert len(result["items"]) == 2
    assert all(item["status"] == "applied" for item in result["items"])
    revision = state.revision
    replay = draw_many(*args)
    assert replay["replayed"] is True
    assert "chart_payload" not in replay
    assert state.revision == revision
