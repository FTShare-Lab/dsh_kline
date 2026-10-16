"""Validate browser-confirmed current-view source identity; never fetch or bind here."""
from __future__ import annotations

import json
import re

import chart_service
from tools.lines import LineError


def require_confirmed_view_source(payload: dict, context: dict, token: str) -> None:
    guard = payload.get("view_source_guard")
    if not guard:
        return
    try:
        if (not isinstance(guard, dict) or guard.get("protocol") != "browser-source-v1"
            or guard.get("chart_session") != token or guard.get("conversation_id") != context.get("conversation_id")
            or not isinstance(guard.get("context_ref"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{32}", guard["context_ref"])
            or not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", token)):
            raise ValueError("owner")
        path = chart_service.RUNTIME_DIR / "sources" / str(chart_service.HOST_PROCESS_ID) / guard["context_ref"] / (token + ".json")
        if path.stat().st_size > chart_service.MAX_REQUEST_BYTES:
            raise ValueError("size")
        proof = json.loads(path.read_text(encoding="utf-8"))
        if (proof.get("status") != "confirmed" or proof.get("host_process_id") != chart_service.HOST_PROCESS_ID
            or proof.get("chart_session") != token or proof.get("context_ref") != guard["context_ref"]
            or proof.get("conversation_id") != guard["conversation_id"] or proof.get("view_id") != guard.get("view_id")):
            raise ValueError("proof")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise LineError("chart_source_not_confirmed", "当前图来源尚未由所属网页核对绑定；请等待重新上报并读取新上下文，不重取行情或使用旧图绕过。") from None
