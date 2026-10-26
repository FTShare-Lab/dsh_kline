"""Small, read-only presentation helpers. Never interpret intent or authorize edits."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import get_args

from tools.lines import ColorInput


def drawing_capabilities() -> dict:
    return {"color_inputs": list(get_args(ColorInput)), "editable_origins": ["ai"],
            "drawing_selection_supported": False, "ambiguous_target": "ask_user",
            "unspecified_price_amount": "ask_user"}


def edit_interaction(data: dict, change: dict | None = None) -> dict:
    status = data.get("apply_status")
    states = {
        "not_requested": ("prepared", "修改方案已准备，尚未执行。", "read_current_context_before_apply"),
        "queued": ("pending", "修改已排队，尚未确认完成。", "check_original_candidate_status"),
        "delivered": ("pending", "修改已送达网页，尚未确认完成。", "check_original_candidate_status"),
        "rejected": ("not_confirmed", "本次修改被拒绝，未获成功确认。", "read_current_context_before_new_edit"),
        "failed": ("not_confirmed", "本次修改失败，请先检查失败原因。", "inspect_failure_do_not_resend"),
        "outcome_unknown": ("unknown", "本次修改结果尚不确定，不要重复执行。", "check_original_candidate_status_do_not_resend"),
    }
    value = states.get(status, ("unknown", "本次修改状态无法确认。", "stop_and_inspect"))
    token = data.get("candidate_chart_session")
    confirmed = (status == "applied" and isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9_-]{32}", token) is not None
                 and data.get("confirmed_chart_session") == data["candidate_chart_session"]
                 and data.get("confirmation_scope") == "view_state_only")
    if confirmed:
        value = ("confirmed", "本次修改已获网页状态确认；目标图形和画面像素仍需核验。", "read_current_context_before_next_edit")
        if data.get("needs_attention"):
            value = ("needs_review", "网页已确认应用，但图形反馈仍需检查；画面像素未核验。", "inspect_drawing_feedback")
    target = (change.get("after") or change.get("before") or {}).get("id") if isinstance(change, dict) else None
    feedback = data.get("drawing_feedback")
    item = next((entry for entry in feedback.get("items", []) if entry.get("id") == target), None) if (
        target and isinstance(feedback, dict) and feedback.get("report_status") == "reported"
        and feedback.get("phase") == "applied") else None
    object_status = item.get("status", "unknown") if item else "unknown"
    time_overlap = item.get("time_range_overlap") if item else None
    if confirmed and value[0] == "confirmed" and item:
        if object_status == "created":
            message = ("网页已确认应用，目标序列已在图表登记；画面像素未核验。" if item.get("reason") == "indicator_registered"
                       else "网页已确认应用，目标图形对象与锚点已核对；画面像素未核验。")
            if item.get("reason") != "indicator_registered":
                if time_overlap is False: message = "网页已确认应用，目标图形对象已核对，但在应用当时的时间视口之外；画面像素未核验。"
                elif time_overlap is True: message = "网页已确认应用，目标图形对象与锚点已核对，时间范围覆盖应用当时的视口；画面像素未核验。"
            value = (value[0], message, value[2])
        elif object_status == "removed":
            value = (value[0], "网页已确认删除，目标图形对象已从图表对象表移除；画面像素未核验。", value[2])
        elif object_status == "hidden":
            value = (value[0], "网页已确认应用，但目标图形在当前周期或数据范围内隐藏；画面像素未核验。", value[2])
    return {"status": value[0], "message": value[1], "next_action": value[2],
            "completion_confirmed": value[0] == "confirmed", "render_verified": False,
            "object_status": object_status, "time_range_overlap": time_overlap, "pixel_verified": False,
            "record_is_historical": data.get("record_is_historical") is True}


def edit_change(candidate: dict, parent: dict) -> dict | None:
    # Derive an object-level diff from the exact named snapshots, not prose or
    # a global latest chart. These are candidate effects, not a live receipt.
    from tools.chart_edits import snapshot_inventory
    try:
        guard = candidate["drawing_guard"]
        kind, action = guard["kind"], guard["action"]
        before = {obj["id"]: obj for obj in snapshot_inventory(parent)}
        after = {obj["id"]: obj for obj in snapshot_inventory(candidate)}
        if action == "create":
            added = set(after) - set(before)
            if len(added) != 1:
                return None
            target = added.pop()
        elif action in {"update", "delete"}:
            target = guard["object_id"]
        else:
            return None
        old, new = before.get(target), after.get(target)
        if (action == "create" and old is not None or action == "delete" and new is not None
            or action != "create" and old is None or action != "delete" and new is None
            or any(obj["kind"] != kind for obj in (old, new) if obj is not None)):
            return None
        fields = sorted(k for k in set(old or {}) | set(new or {})
                        if k not in {"id", "origin", "kind"} and (old or {}).get(k) != (new or {}).get(k))
        detail = {}
        if kind == "labeled_polyline" and old is not None and new is not None:
            previous_points = {p["label"]: p for p in old["points"]}
            next_points = {p["label"]: p for p in new["points"]}
            detail["point_changes"] = [{"label": label, "before": deepcopy(previous_points.get(label)),
                                        "after": deepcopy(next_points.get(label))}
                                       for label in sorted(previous_points.keys() | next_points.keys())
                                       if previous_points.get(label) != next_points.get(label)]
        return {"kind": kind, "action": action, "before": deepcopy(old), "after": deepcopy(new), **detail,
                "changed_fields": fields, "basis": "prepared_candidate_not_live_state",
                "other_ai_drawings_unchanged": {k: v for k, v in before.items() if k != target}
                    == {k: v for k, v in after.items() if k != target}}
    except (KeyError, TypeError, AttributeError):
        return None


def error_interaction(code: str) -> dict:
    if code in {"invalid_color", "invalid_price", "invalid_object_identity", "ambiguous_drawing_id", "drawing_not_editable",
                "invalid_annotation_text", "invalid_annotation_value", "invalid_annotation_anchor", "annotation_anchor_required", "annotation_not_found",
                "invalid_polyline_points", "invalid_point_label", "duplicate_point_label", "point_not_found", "point_label_required", "empty_point_update"}:
        next_action = "ask_user"
    elif code in {"chart_context_stale", "chart_view_inactive", "chart_context_revision_conflict",
                  "chart_snapshot_not_aligned", "chart_context_unavailable", "ambiguous_chart_views"}:
        next_action = "read_current_context"
    elif code in {"chart_application_unavailable", "chart_edit_outcome_unknown"}:
        next_action = "check_original_candidate_status_do_not_resend"
    else:
        next_action = "stop_and_inspect"
    result = {"status": "not_confirmed", "completion_confirmed": False, "next_action": next_action}
    if code == "invalid_color":
        result["color_inputs"] = list(get_args(ColorInput))
    return result
