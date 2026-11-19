"""One bound drawing task, one guarded application, per-tool outcomes."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import os


import chart_service
from tools.chart_context import read_chart_context
from tools.chart_functions import run_function
from tools.chart_edits import ChartEdit, prepare_chart_edit
from tools.chart_applications import request_chart_apply, read_edit_status
from tools.lines import LineError


from tools.drawing_requests import DrawingRequest, analysis_for

async def draw_many(context_ref, symbol, request_id, drawings, *, wait_ms=5000):
    """Idempotent task. No data fetching or automatic cross-view rebinding."""
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100 or any(ord(c) < 32 for c in request_id):
        raise LineError("invalid_request_id", "绘图任务需要稳定的请求编号。")
    if not isinstance(drawings, list) or not 1 <= len(drawings) <= 8:
        raise LineError("invalid_drawing_task", "一次绘图任务支持1至8个图形。")
    if type(wait_ms) is not int or not 0 <= wait_ms <= 5000:
        raise LineError("invalid_drawing_wait", "绘图等待时间超出允许范围。")
    requests = [r if isinstance(r, DrawingRequest) else DrawingRequest.model_validate(r) for r in drawings]
    # Validate the reference before using it as a directory component, including replays.
    from tools.chart_applications import application_path
    directory = application_path(context_ref, "a" * 32).parent.parent / "tasks"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (sha256(request_id.encode()).hexdigest() + ".json")
    intent = {"symbol": symbol, "drawings": [r.model_dump() for r in requests]}
    lock = path.with_suffix(".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise LineError("drawing_task_busy", "该绘图任务正在处理，请稍后核对原任务。") from None
    os.close(descriptor)
    try:
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["intent"] != intent:
                raise LineError("request_conflict", "同一任务编号的绘图要求已改变，未重复执行。")
            if record.get("result"):
                return {**record["result"], "replayed": True, "record_is_historical": True}
            if not record.get("candidate"):
                raise LineError("drawing_task_outcome_unknown", "原任务结果尚不确定，未重复创建图形。")
        else:
            if sum(1 for _ in directory.glob("*.json")) >= 128:
                raise LineError("drawing_task_capacity", "当前视图的绘图任务记录已达上限，请新建图表视图。")
            context = read_chart_context(context_ref, candle_scope="loaded", limit=4000)
            if context["symbol"].casefold() != symbol.strip().casefold():
                raise LineError("drawing_task_symbol_changed", "当前标的与绘图要求不一致，请先打开目标图。")
            binding = {"context_ref": context_ref, "expected_revision": context["revision"],
                       "chart_session": context["source_chart_session"], "symbol": context["symbol"]}
            record = {"intent": intent, "items": []}
            chart_service._atomic_runtime_json(path, record)
            edits = []
            for request in requests:
                function, parameters, kind = analysis_for(request)
                result = run_function(**binding, function=function, parameters=parameters)
                summary = result["summary"]
                available = bool(summary.get("marks")) if kind == "nine_count" else len(summary.get("candidates", [])) >= request.candidate_number
                item = {"tool": request.tool, "status": "selected" if available else "no_candidate"}
                record["items"].append(item)
                if not available:
                    item["reasons"] = summary.get("rejection_counts", summary.get("limitations", []))
                    continue
                edit = {"kind": kind, "action": "create"}
                if kind == "nine_count":
                    edit["result_ref"] = result["result_ref"]
                else:
                    edit.update(candidate_result_ref=result["result_ref"], candidate_number=request.candidate_number,
                                user_confirmed_candidate=True)
                for key in ("name", "color"):
                    if getattr(request, key) is not None:
                        edit[key] = getattr(request, key)
                edits.append(edit)
            if not edits:
                record["result"] = {"ok": True, "status": "no_candidate", "items": record["items"], "chart_modified": False}
                chart_service._atomic_runtime_json(path, record)
                return record["result"]
            prepared = prepare_chart_edit(**binding, request_id="multi:" + request_id,
                                          edit=ChartEdit(kind="drawing_batch", action="create", edits=edits))
            record["candidate"] = prepared["chart_session"]
            selected = (item for item in record["items"] if item["status"] == "selected")
            for item, obj in zip(selected, prepared["object"]["objects"]):
                item["object_id"] = obj.get("id")
            chart_service._atomic_runtime_json(path, record)
        candidate = record["candidate"]
        # request_apply is itself single-delivery and safe after a lost response.
        status = request_chart_apply(context_ref, candidate)
        deadline = asyncio.get_running_loop().time() + wait_ms / 1000
        while status["apply_status"] in {"queued", "delivered"} and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(.1)
            status = read_edit_status(context_ref, candidate)
        result = {"ok": True, "status": status["apply_status"], "context_ref": context_ref,
                  "candidate_chart_session": candidate, "items": record["items"],
                  "chart_modified": status["apply_status"] == "applied", "render_verified": False,
                  "drawing_feedback": status.get("drawing_feedback")}
        for item in result["items"]:
            if item["status"] != "no_candidate":
                item["status"] = status["apply_status"]
        if status["apply_status"] not in {"queued", "delivered"}:
            record["result"] = result
        chart_service._atomic_runtime_json(path, record)
        return result
    finally:
        lock.unlink()
