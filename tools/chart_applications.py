"""Explicit application requests and historical state receipts; never a pixel receipt."""
from __future__ import annotations

import json
import os
import re
import time

import chart_service
from tools.chart_context import read_chart_context
from tools.lines import LineError
from tools.drawing_feedback import sanitize_drawing_feedback

STATUSES = {"queued", "delivered", "applied", "rejected", "failed", "outcome_unknown"}


def application_path(context_ref: str, candidate: str):
    if any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", v) for v in (context_ref, candidate)):
        raise LineError("invalid_chart_application_reference", "请使用准备结果的 context_ref 和候选 chart_session，不猜测引用。")
    return chart_service.RUNTIME_DIR / "edits" / str(chart_service.HOST_PROCESS_ID) / context_ref / "applications" / (candidate + ".json")


def _read(path):
    try:
        if path.stat().st_size > chart_service.MAX_REQUEST_BYTES: raise ValueError("too large")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict): raise ValueError("not an object")
        return data
    except (OSError, ValueError, TypeError):
        raise LineError("chart_application_unavailable", "应用记录不可用，未猜测网页状态或自动重发。") from None


def read_application(context_ref: str, candidate: str) -> dict:
    data = _read(application_path(context_ref, candidate))
    if (data.get("host_process_id") != chart_service.HOST_PROCESS_ID or data.get("context_ref") != context_ref
        or data.get("candidate_chart_session") != candidate or data.get("status") not in STATUSES):
        raise LineError("invalid_chart_application", "应用记录身份或状态不一致。")
    return data


def _present(path) -> bool:
    """Only ENOENT is absence; unreadable/corrupt records must not become 'not requested'."""
    try:
        path.stat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise LineError("chart_application_unavailable", "记录无法核对，未推断尚未请求应用。") from None


def read_edit_status(context_ref: str, candidate: str) -> dict:
    """Read historical preparation or application proof, without acquiring locks or writing.

    This is not an application reader: confirmed_source must still require a real receipt.
    An absent application alone proves nothing; require the exact successful preparation.
    """
    path = application_path(context_ref, candidate)
    if _present(path):
        return application_status(read_application(context_ref, candidate))
    directory = path.parent.parent

    def check_inflight():
        if _present(directory / "prepare.lock"):
            raise LineError("chart_edit_busy", "该视图正在处理或存在中断锁，不能断言尚未请求应用；未重发。")
        if _present(directory / "pending.json"):
            pending = _read(directory / "pending.json").get("candidate_chart_session")
            if pending == candidate:
                raise LineError("chart_application_unavailable", "存在应用请求索引但记录缺失，未推断尚未请求应用。")
            if read_application(context_ref, pending)["status"] not in {"applied", "rejected", "failed"}:
                raise LineError("chart_apply_busy", "该视图有等待或结果未确认的应用，未推断新的应用状态。")

    check_inflight()
    payload = chart_service.read_chart_snapshot(candidate)
    guard = payload.get("drawing_guard") if payload else None
    if (not isinstance(guard, dict) or guard.get("protocol") != "prepared-only-v1"
        or guard.get("context_ref") != context_ref or guard.get("requires_live_apply") is not True
        or payload.get("drawing_parent_session") != guard.get("chart_session")
        or not isinstance(guard.get("expected_revision"), int) or isinstance(guard["expected_revision"], bool)
        or guard["expected_revision"] <= 0 or not isinstance(guard.get("conversation_id"), str) or not guard["conversation_id"]
        or not isinstance(guard.get("view_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", guard["view_id"])
        or not isinstance(guard.get("request_id"), str) or not 1 <= len(guard["request_id"]) <= 128
        or not isinstance(guard.get("chart_session"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", guard["chart_session"])
        or not isinstance(guard.get("parameters"), dict) or guard.get("kind") not in ("horizontal_line", "trend_line", "channel", "rectangle", "fibonacci_retracement", "labeled_polyline", "text_annotation", "number_annotation", "icon_annotation", "series_line", "price_band", "price_sticks", "all_drawings")
        or guard.get("action") not in ("create", "update", "delete")):
        raise LineError("invalid_chart_application", "候选不属于该准备请求，未推断应用状态。")
    entries = _read(directory / "journal.json").get("entries")
    from tools.chart_edits import _hash
    identity = {key: guard.get(key) for key in ("context_ref", "expected_revision", "chart_session", "symbol",
                                               "kind", "action", "object_id", "parameters")}
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("request_id") == guard.get("request_id")] if isinstance(entries, list) and len(entries) <= 64 else []
    entry = matches[0] if len(matches) == 1 else {}
    result = entry.get("result")
    if (not isinstance(result, dict) or entry.get("status") != "prepared"
        or entry.get("revision") != guard.get("expected_revision") or entry.get("fingerprint") != _hash(identity)
        or result.get("ok") is not True or result.get("operation_status") != "prepared"
        or result.get("apply_status") != "not_requested" or result.get("chart_session") != candidate
        or result.get("parent_chart_session") != guard.get("chart_session") or result.get("drawing_guard") != guard
        or any(result.get(key) != guard.get(key) for key in
               ("context_ref", "expected_revision", "conversation_id", "view_id", "request_id"))):
        raise LineError("chart_edit_outcome_unknown", "未找到匹配的成功准备记录，未推断尚未请求应用。")
    # A concurrent apply may have completed while we read preparation proof. Prefer
    # its real record; a retained lock/index with no record remains uncertain.
    if _present(path):
        return application_status(read_application(context_ref, candidate))
    check_inflight()
    if _present(path):
        return application_status(read_application(context_ref, candidate))
    return {"ok": True, "operation_status": "prepared", "apply_status": "not_requested",
            **{key: result[key] for key in ("context_ref", "expected_revision", "conversation_id", "view_id", "request_id")},
            "candidate_chart_session": candidate, "parent_chart_session": result["parent_chart_session"],
            "application_record_present": False, "record_is_historical": True,
            "confirmation_scope": "not_confirmed", "render_verified": False,
            "current_view_verified": False, "edit_authorized": False}


def application_status(data: dict) -> dict:
    # Queued/delivered can be historical after a host interruption; never invent an acknowledgment.
    result = {k: data.get(k) for k in ("context_ref", "candidate_chart_session", "conversation_id", "view_id",
        "expected_revision", "created_at_ms", "expires_at_ms", "reason", "acknowledged_at_ms", "confirmed_chart_session")}
    expires = data.get("expires_at_ms")
    candidate = chart_service.read_chart_snapshot(data.get("candidate_chart_session"))
    if candidate:
        from tools.chart_edits import snapshot_inventory
        try:
            allowed = list({d["id"]: d for d in [*data.get("base_state", {}).get("drawings", []), *snapshot_inventory(candidate)]
                            if d.get("origin") == "ai"}.values())
            feedback = sanitize_drawing_feedback(data.get("drawing_feedback"), allowed)
        except (KeyError, TypeError, AttributeError): feedback = sanitize_drawing_feedback({"report_status": "invalid"}, [])
    else: feedback = sanitize_drawing_feedback(None, [])
    expired = isinstance(expires, (int, float)) and time.time() * 1000 > expires
    result.update(ok=True, apply_status=data["status"], render_verified=False,
                  expired=expired, needs_attention=data["status"] == "outcome_unknown" or expired and data["status"] in {"queued", "delivered"}
                  or feedback["report_status"] == "invalid" or any(i["status"] in {"failed", "unknown"} for i in feedback["items"]),
                  drawing_feedback=feedback,
                  confirmation_scope="view_state_only" if data["status"] == "applied" else "not_confirmed",
                  record_is_historical=True)
    return result


def confirmed_source(payload: dict, context: dict, token: str) -> bool:
    guard = payload.get("drawing_guard") or {}
    try: proof = read_application(guard.get("context_ref"), token)
    except LineError: return False
    return (proof["status"] == "applied" and proof.get("confirmed_chart_session") == token
            and proof.get("conversation_id") == context.get("conversation_id") == guard.get("conversation_id")
            and proof.get("view_id") == guard.get("view_id") and proof.get("request_id") == guard.get("request_id"))


def request_chart_apply(context_ref: str, candidate: str) -> dict:
    path = application_path(context_ref, candidate)
    directory = path.parent.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = directory / "prepare.lock"
    try: descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise LineError("chart_edit_busy", "该视图正在准备或申请应用，未并行修改。") from None
    os.close(descriptor)
    try:
        if path.exists():
            existing = read_application(context_ref, candidate)
            # Same immutable candidate has one delivery, including after a lost reply.
            if existing["status"] != "queued": return application_status(existing)
        else: existing = None
        context = read_chart_context(context_ref, candle_scope="loaded", limit=4000)
        if not context.get("guarded_apply_supported"):
            raise LineError("chart_apply_protocol_unavailable", "该网页尚未声明支持应用协议，请更新/重载插件网页；未发送修改指令。")
        payload = chart_service.read_chart_snapshot(candidate)
        guard = payload.get("drawing_guard") if payload else None
        if (not isinstance(guard, dict) or guard.get("protocol") != "prepared-only-v1"
            or guard.get("context_ref") != context_ref or guard.get("conversation_id") != context["conversation_id"]
            or guard.get("view_id") != context["view_id"]):
            raise LineError("invalid_chart_application", "候选不属于当前视图的准备请求，未申请应用。")
        if context["revision"] != guard.get("expected_revision"):
            raise LineError("chart_context_revision_conflict", "准备后当前图版本已变化，未申请应用。")
        journal = _read(directory / "journal.json")
        entries = journal.get("entries")
        if not isinstance(entries, list) or not any(e.get("status") == "prepared" and e.get("request_id") == guard.get("request_id")
            and isinstance(e.get("result"), dict) and e["result"].get("chart_session") == candidate for e in entries if isinstance(e, dict)):
            raise LineError("chart_edit_outcome_unknown", "未找到成功准备记录，不能申请应用。")
        source = chart_service.read_chart_snapshot(guard.get("chart_session"))
        if source is None: raise LineError("chart_session_not_found", "原始来源快照不可用。")
        from tools.chart_edits import require_alignment
        require_alignment(context, source, guard["chart_session"], guard["symbol"])
        pending = directory / "pending.json"
        if pending.exists():
            old_token = _read(pending).get("candidate_chart_session")
            if old_token != candidate:
                old = read_application(context_ref, old_token)
                if old["status"] not in {"applied", "rejected", "failed"}:
                    raise LineError("chart_apply_busy", "该视图有等待或结果未确认的应用，不能覆盖它。")
        if existing is None:
            observation = _read(chart_service.RUNTIME_DIR / "views" / str(chart_service.HOST_PROCESS_ID) / (context_ref + ".json"))
            if observation.get("revision") != guard["expected_revision"] or observation.get("view_id") != guard["view_id"]:
                raise LineError("chart_context_revision_conflict", "读取期间当前图版本已变化，未申请应用。")
            now = int(time.time() * 1000)
            existing = {"host_process_id": chart_service.HOST_PROCESS_ID, "context_ref": context_ref,
                "candidate_chart_session": candidate, "conversation_id": context["conversation_id"], "view_id": context["view_id"],
                "expected_revision": guard["expected_revision"], "request_id": guard["request_id"], "status": "queued",
                # Match the live-context lease: a slow host may spend more than
                # 30 seconds between queueing and the next browser publication.
                # Dispatch still rechecks the view revision and complete state.
                "created_at_ms": now, "expires_at_ms": now + 90_000, "base_state": observation["state"]}
            chart_service._atomic_runtime_json(path, existing)
        chart_service._atomic_runtime_json(pending, {"candidate_chart_session": candidate})
        return application_status(existing)
    finally: lock.unlink()
