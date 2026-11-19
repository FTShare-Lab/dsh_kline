"""Restore drawings from a confirmed operation, never restore market/view state."""

import chart_service
from tools.lines import LineError


def restore_drawings(payload, context, session, direction):
    from tools.chart_applications import read_application

    receipt = read_application(context["context_ref"], session)
    if (receipt.get("status") != "applied" or receipt.get("confirmed_chart_session") != session
            or receipt.get("conversation_id") != context["conversation_id"]
            or receipt.get("view_id") != context["view_id"]):
        raise LineError("drawing_history_unconfirmed", "只能撤销或重做本视图已确认的绘图操作。")
    after = chart_service.read_chart_snapshot(session)
    before = chart_service.read_chart_snapshot(after.get("drawing_parent_session")) if after else None
    if before is None or after.get("drawing_guard", {}).get("kind") == "drawing_history":
        raise LineError("drawing_history_unavailable", "原始绘图记录不可用，未恢复旧图表。")

    from tools.drawing_restore import restore_drawing_commands
    return restore_drawing_commands(payload, before, after, context["interval"], direction)
