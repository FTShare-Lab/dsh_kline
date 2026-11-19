"""Codex transport for the shared multi-drawing request contract."""
from copy import deepcopy

from codex_runtime.functions import run_chart_function
from tools.drawing_requests import DrawingRequest, analysis_for
from tools.lines import LineError


def draw_many(store, context_ref, symbol, request_id, drawings):
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100 or not isinstance(drawings, list) or not 1 <= len(drawings) <= 8:
        raise LineError("invalid_drawing_task", "绘图任务需要稳定编号及1至8个图形。")
    requests = [r if isinstance(r, DrawingRequest) else DrawingRequest.model_validate(r) for r in drawings]
    state = store._state(context_ref)
    intent = {"symbol": symbol, "drawings": [r.model_dump() for r in requests]}
    previous = state.drawing_tasks.get(request_id)
    if previous:
        if previous["intent"] != intent:
            raise LineError("request_conflict", "同一绘图任务编号的参数不同。")
        result = deepcopy(previous["result"])
        result.pop("chart_payload", None)
        return {**result, "replayed": True, "record_is_historical": True}
    if len(state.drawing_tasks) >= 128:
        raise LineError("drawing_task_capacity", "绘图任务记录已满。")
    if str(symbol).casefold() != str(state.payload.get("symbol")).casefold():
        raise LineError("drawing_task_symbol_changed", "当前图不是指定标的。")
    binding = {"context_ref": context_ref, "expected_revision": state.revision,
               "chart_session": state.chart_session, "symbol": symbol}
    edits, items = [], []
    for request in requests:
        function, parameters, kind = analysis_for(request)
        result = run_chart_function(store, **binding, function=function, parameters=parameters)
        summary = result["summary"]
        available = bool(summary.get("marks")) if kind == "nine_count" else len(summary.get("candidates", [])) >= request.candidate_number
        item = {"tool": request.tool, "status": "selected" if available else "no_candidate"}
        items.append(item)
        if not available:
            continue
        edit = {"kind": kind, "action": "create"}
        if kind == "nine_count":
            edit["result_ref"] = result["result_ref"]
        else:
            edit.update(candidate_result_ref=result["result_ref"], candidate_number=request.candidate_number, user_confirmed_candidate=True)
        for key in ("name", "color"):
            if getattr(request, key) is not None:
                edit[key] = getattr(request, key)
        edits.append(edit)
    result = {"ok": True, "status": "no_candidate", "chart_modified": False, "items": items}
    if edits:
        prepared = store.prepare(**binding, request_id="multi:" + request_id,
                                 edit={"kind": "drawing_batch", "action": "create", "edits": edits})
        applied = store.apply(context_ref, prepared["chart_session"])
        for item, obj in zip((i for i in items if i["status"] == "selected"), prepared["object"]["objects"]):
            item.update(status="applied", object_id=obj.get("id"))
        result.update(status="applied", chart_modified=True, context_ref=context_ref,
                      candidate_chart_session=prepared["chart_session"], chart_payload=applied["chart_payload"],
                      confirmation_scope="server_state_and_optional_ui_receipt_not_pixels", ui_receipt=applied["ui_receipt"], render_verified=False)
    cached = deepcopy(result)
    cached.pop("chart_payload", None)
    state.drawing_tasks[request_id] = {"intent": intent, "result": cached}
    return result
