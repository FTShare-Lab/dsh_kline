"""In-memory, connection-scoped guarded chart state for Codex.

There is no filesystem journal, HTTP service, DSH browser observation, or
credential store in this module.  A stdio process represents one MCP
connection; App instances must additionally claim a chart before using the
private UI action.  Idle state is discarded after thirty minutes.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import secrets
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.annotations import ANNOTATION_COMMAND, ANNOTATION_KINDS, edit_annotation
from tools.channels import CHANNEL_COMMAND, edit_channel
from tools.fibonacci import FIBONACCI_COMMAND, edit_fibonacci
from tools.lines import LINE_COMMAND, LineError, edit_horizontal_line
from tools.polylines import POLYLINE_COMMAND, LabeledPoint, edit_polyline
from tools.price_bands import BAND_COMMAND, edit_price_band
from tools.price_series import SERIES_COMMAND, edit_price_series
from tools.price_sticks import STICKS_COMMAND, edit_price_sticks
from tools.rectangles import RECTANGLE_COMMAND, edit_rectangle
from tools.trend_lines import TREND_COMMAND, edit_trend_line

APP_RESOURCE_URI = "ui://ft-kline/chart-v1"
MCP_APP_MIME = "text/html;profile=mcp-app"
IDLE_SECONDS = 30 * 60
MAX_STATES = 16


class CodexChartEdit(BaseModel):
    """The same public guarded-edit fields as DSH, without DSH transport state."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["horizontal_line", "trend_line", "channel", "rectangle", "fibonacci_retracement", "labeled_polyline", "text_annotation", "number_annotation", "icon_annotation", "series_line", "price_band", "price_sticks", "all_drawings"]
    action: Literal["create", "update", "delete"]
    object_id: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=48)
    color: str | None = None
    price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    start_time: str | None = None
    end_time: str | None = None
    start_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    end_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    parallel_time: str | None = None
    parallel_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    lower_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    upper_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    show_midline: bool | None = None
    show_fill: bool | None = None
    points: list[LabeledPoint] | None = Field(default=None, min_length=2, max_length=8)
    point_label: str | None = Field(default=None, min_length=1, max_length=16)
    point_time: str | None = None
    point_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    anchor_time: str | None = None
    anchor_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    annotation_text: str | None = Field(default=None, max_length=120)
    annotation_value: float | None = Field(default=None, allow_inf_nan=False)
    annotation_icon: Literal["arrow_up", "arrow_down", "diamond"] | None = None
    ratios: list[float] | None = Field(default=None, min_length=1, max_length=16)
    result_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    ta_result_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    candidate_result_ref: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    candidate_number: int | None = Field(default=None, ge=1, le=5)
    user_confirmed_candidate: bool | None = None


_EDITABLE_COMMANDS = {LINE_COMMAND, TREND_COMMAND, CHANNEL_COMMAND, RECTANGLE_COMMAND,
                      FIBONACCI_COMMAND, POLYLINE_COMMAND, ANNOTATION_COMMAND,
                      SERIES_COMMAND, BAND_COMMAND, STICKS_COMMAND}
_KIND_COMMAND = {
    "horizontal_line": LINE_COMMAND, "trend_line": TREND_COMMAND, "channel": CHANNEL_COMMAND,
    "rectangle": RECTANGLE_COMMAND, "fibonacci_retracement": FIBONACCI_COMMAND,
    "labeled_polyline": POLYLINE_COMMAND, "series_line": SERIES_COMMAND,
    "price_band": BAND_COMMAND, "price_sticks": STICKS_COMMAND,
}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = next((item.get("rows") for item in payload.get("chartCommands", [])
                 if item.get("type") == "SET_CANDLES"), [])
    return deepcopy(rows) if isinstance(rows, list) else []


def _inventory(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    kinds = {value: key for key, value in _KIND_COMMAND.items()}
    for command in payload.get("chartCommands", []):
        kind = command.get("kind") if command.get("type") == ANNOTATION_COMMAND else kinds.get(command.get("type"))
        if kind not in {*_KIND_COMMAND, *ANNOTATION_KINDS}:
            continue
        item = {"id": command.get("id"), "kind": kind, "origin": "ai",
                "name": command.get("label", ""), "color": command.get("color", "info"),
                "interval": command.get("interval", payload.get("interval"))}
        if kind == "horizontal_line": item["price"] = command.get("price")
        elif kind == "rectangle":
            item.update({key: command.get(key) for key in ("start_time", "end_time", "lower_price", "upper_price", "show_fill")})
        elif kind == "labeled_polyline": item["points"] = deepcopy(command.get("points"))
        elif kind in {"series_line", "price_band", "price_sticks"}:
            digest = {"series_line": "series_hash", "price_band": "band_hash", "price_sticks": "sticks_hash"}[kind]
            item.update({"bar_count": command.get("bar_count"), digest: command.get(digest)})
        elif kind in ANNOTATION_KINDS:
            item.update({key: command.get(key) for key in ("time", "price", "text", "value", "icon") if key in command})
        else:
            item["points"] = [deepcopy(command.get("from")), deepcopy(command.get("to"))]
            if command.get("parallel") is not None: item["points"].append(deepcopy(command["parallel"]))
            if kind == "channel": item["show_midline"] = command.get("show_midline")
            if kind == "fibonacci_retracement": item["ratios"] = deepcopy(command.get("ratios"))
        result.append(item)
    return result


def _edit_parameters(edit: CodexChartEdit) -> dict[str, Any]:
    fields = edit.model_dump(exclude_none=True)
    for key in ("kind", "action", "object_id"):
        fields.pop(key, None)
    common = {"name", "color", "result_ref", "ta_result_ref", "candidate_result_ref", "candidate_number", "user_confirmed_candidate"}
    allowed = common | {
        "horizontal_line": {"price"},
        "trend_line": {"start_time", "end_time", "start_price", "end_price"},
        "channel": {"start_time", "end_time", "start_price", "end_price", "parallel_time", "parallel_price", "show_midline"},
        "rectangle": {"start_time", "end_time", "lower_price", "upper_price", "show_fill"},
        "fibonacci_retracement": {"start_time", "end_time", "start_price", "end_price", "ratios"},
        "labeled_polyline": {"points", "point_label", "point_time", "point_price"},
        "text_annotation": {"anchor_time", "anchor_price", "annotation_text"},
        "number_annotation": {"anchor_time", "anchor_price", "annotation_value"},
        "icon_annotation": {"anchor_time", "anchor_price", "annotation_icon"},
        "series_line": set(), "price_band": set(), "price_sticks": set(), "all_drawings": set(),
    }[edit.kind]
    if fields.keys() - allowed or (edit.action == "delete" and fields):
        raise LineError("invalid_edit_fields", "参数不适用于该图形；删除只填写对象标识。")
    if edit.kind == "all_drawings" and (edit.action != "delete" or edit.object_id is not None):
        raise LineError("invalid_object_identity", "清空当前图只使用 all_drawings/delete，不指定对象 ID。")
    if edit.kind != "all_drawings" and ((edit.action == "create") != (edit.object_id is None)):
        raise LineError("invalid_object_identity", "创建不指定 object_id；修改或删除必须使用当前图的稳定对象 ID。")
    candidate_fields = {"candidate_result_ref", "candidate_number", "user_confirmed_candidate"}
    if fields.keys() & candidate_fields and (edit.action != "create" or edit.kind not in {"channel", "rectangle"}
            or not candidate_fields <= fields.keys() or edit.user_confirmed_candidate is not True
            or fields.keys() - candidate_fields - {"name", "color", "show_midline", "show_fill"}):
        raise LineError("candidate_confirmation_required", "候选必须由用户明确选定后才可创建图形。")
    return fields


@dataclass
class Candidate:
    token: str
    request_id: str
    revision: int
    fingerprint: str
    edited_payload: dict[str, Any]
    edit: dict[str, Any]
    object: dict[str, Any]
    status: str = "prepared"
    ui_acknowledged: bool = False
    render_failure: str | None = None


@dataclass
class ChartState:
    context_ref: str
    chart_session: str
    payload: dict[str, Any]
    revision: int = 1
    app_instance: str | None = None
    last_access: float = field(default_factory=time.monotonic)
    candidates: dict[str, Candidate] = field(default_factory=dict)
    request_ids: dict[str, Candidate] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    session_key: str | None = None
    # The reused chart UI has a watchlist rail.  For Codex it is deliberately
    # scoped to this in-memory chart conversation rather than the DSH profile.
    watchlist: dict[str, Any] = field(default_factory=lambda: {
        "version": 1, "revision": 0, "updated_at": 0, "groups": [], "items": [],
        "activeGroupId": "default", "sort": "manual",
    })


class CodexChartStore:
    """A small process-memory store; no state is written outside this process."""
    def __init__(self, *, idle_seconds: int = IDLE_SECONDS, now=time.monotonic) -> None:
        self.idle_seconds, self._now = idle_seconds, now
        self._items: dict[str, ChartState] = {}

    def prune(self) -> None:
        deadline = self._now() - self.idle_seconds
        for ref, state in list(self._items.items()):
            if state.last_access < deadline:
                state.session_key = None
                del self._items[ref]

    def create(self, payload: dict[str, Any]) -> ChartState:
        self.prune()
        while len(self._items) >= MAX_STATES:
            oldest = min(self._items.values(), key=lambda value: value.last_access)
            oldest.session_key = None
            del self._items[oldest.context_ref]
        ref, session = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        state = ChartState(context_ref=ref, chart_session=session, payload=deepcopy(payload), last_access=self._now())
        state.payload.update({"context_ref": ref, "chart_session": session, "source_chart_session": session,
                              "chart_ready": True, "chart_ui": {"ready": True, "mode": "mcp_apps",
                              "resource_uri": APP_RESOURCE_URI}})
        self._items[ref] = state
        return state

    def close(self, context_ref: str, *, app_instance: str | None = None) -> None:
        state = self._items.get(context_ref)
        if state and (not app_instance or state.app_instance == app_instance):
            state.session_key = None
            del self._items[context_ref]

    def _state(self, context_ref: str, *, app_instance: str | None = None, claim: bool = False) -> ChartState:
        self.prune()
        state = self._items.get(context_ref)
        if state is None:
            raise LineError("chart_context_unavailable", "当前对话图表会话已结束或已空闲超时，请重新生成图表。")
        if app_instance:
            if claim and state.app_instance is None:
                # One visible App iframe has one active chart.  When it moves
                # to a different symbol/source, discard its former context so
                # a stale context cannot write into a chart it no longer owns.
                for ref, other in list(self._items.items()):
                    if ref != context_ref and other.app_instance == app_instance:
                        other.session_key = None
                        del self._items[ref]
                state.app_instance = app_instance
            if state.app_instance != app_instance:
                raise LineError("chart_app_instance_mismatch", "该图表属于另一活动 App 实例，不能跨窗口使用。")
        state.last_access = self._now()
        return state

    def context(self, context_ref: str) -> dict[str, Any]:
        state = self._state(context_ref)
        rows = _rows(state.payload)
        return {"ok": True, "context_ref": state.context_ref, "revision": state.revision,
                "source_chart_session": state.chart_session, "symbol": state.payload.get("symbol"),
                "interval": state.payload.get("interval"), "interval_value": state.payload.get("interval_value", 1),
                "adjust": state.payload.get("adjust", "none"), "state": "ready", "candles": rows,
                "loaded_range": {"start": rows[0]["time"], "end": rows[-1]["time"], "count": len(rows)} if rows else None,
                "candle_selection": {"scope": "loaded", "truncated": False, "count": len(rows)},
                "drawings": _inventory(state.payload), "data_provenance": "codex_memory_current_connection",
                "edit_capability": "guarded", "expires_after_idle_seconds": self.idle_seconds}

    def claim(self, context_ref: str, app_instance: str) -> dict[str, Any]:
        if not isinstance(app_instance, str) or not 16 <= len(app_instance) <= 160:
            raise LineError("invalid_app_instance", "App instance 标识无效。")
        state = self._state(context_ref, app_instance=app_instance, claim=True)
        return {"ok": True, "context_ref": state.context_ref, "revision": state.revision,
                "chart_session": state.chart_session, "connection_scope": "current_stdio_connection"}

    def chart_payload(self, context_ref: str, *, app_instance: str | None = None) -> dict[str, Any]:
        state = self._state(context_ref, app_instance=app_instance)
        payload = deepcopy(state.payload)
        payload.update({"context_ref": state.context_ref, "chart_session": state.chart_session,
                        "source_chart_session": state.chart_session, "revision": state.revision,
                        "chart_ready": True, "chart_ui": {"ready": True, "mode": "mcp_apps", "resource_uri": APP_RESOURCE_URI}})
        return payload

    def get_watchlist(self, context_ref: str, *, app_instance: str) -> dict[str, Any]:
        """Return the volatile App watchlist; it never reaches disk or DSH."""
        state = self._state(context_ref, app_instance=app_instance, claim=True)
        return {"ok": True, "watchlist": deepcopy(state.watchlist), "persistent": False}

    def save_watchlist(self, context_ref: str, watchlist: Any, *, app_instance: str) -> dict[str, Any]:
        """Save a bounded, UI-shaped list within the active App session only."""
        if not isinstance(watchlist, dict):
            raise LineError("invalid_watchlist", "自选列表格式无效。")
        state = self._state(context_ref, app_instance=app_instance, claim=True)
        expected = max(0, int(watchlist.get("revision") or 0))
        if expected != int(state.watchlist.get("revision") or 0):
            return {"ok": False, "error": "watchlist_conflict", "watchlist": deepcopy(state.watchlist), "persistent": False}
        groups = [
            {"id": str(item.get("id"))[:64], "name": str(item.get("name"))[:24]}
            for item in (watchlist.get("groups") or []) if isinstance(item, dict) and item.get("id") and item.get("name")
        ][:12]
        allowed = {item["id"] for item in groups} | {"default"}
        items = [
            {"symbol": str(item.get("symbol"))[:32], "name": str(item.get("name") or item.get("symbol"))[:80],
             "groupId": str(item.get("groupId"))[:64]}
            for item in (watchlist.get("items") or [])
            if isinstance(item, dict) and item.get("symbol") and str(item.get("groupId") or "default") in allowed
        ][:240]
        state.watchlist = {
            "version": 1, "revision": expected + 1, "updated_at": int(time.time() * 1000),
            "groups": groups, "items": items,
            "activeGroupId": str(watchlist.get("activeGroupId") or "default") if str(watchlist.get("activeGroupId") or "default") in allowed else "default",
            "sort": str(watchlist.get("sort") or "manual") if str(watchlist.get("sort") or "manual") in {"manual", "change_desc", "change_asc"} else "manual",
        }
        return {"ok": True, "watchlist": deepcopy(state.watchlist), "persistent": False}

    def store_result(self, context_ref: str, *, revision: int, kind: str, result: dict[str, Any]) -> str:
        state = self._state(context_ref)
        if revision != state.revision:
            raise LineError("chart_context_revision_conflict", "当前图已变化，请重新读取上下文。")
        record = {"context_ref": context_ref, "chart_session": state.chart_session, "revision": revision,
                  "kind": kind, "result": deepcopy(result)}
        ref = _hash(record)
        if len(state.results) >= 64 and ref not in state.results:
            raise LineError("chart_function_capacity", "当前对话已保存的函数结果达到上限。")
        state.results[ref] = record
        return ref

    def result(self, state: ChartState, ref: str, kind: str) -> dict[str, Any]:
        record = state.results.get(ref)
        if not record or record.get("revision") != state.revision or record.get("kind") != kind:
            raise LineError("chart_function_result_mismatch", "结果引用不属于当前图版本或目标图形。")
        value = record.get("result")
        if not isinstance(value, dict):
            raise LineError("chart_function_result_invalid", "结果引用无效。")
        return deepcopy(value)

    def raw_result(self, context_ref: str, ref: str, *, revision: int) -> dict[str, Any]:
        """Read an in-memory analysis result without making it a drawing input."""
        state = self._state(context_ref)
        record = state.results.get(ref)
        if not record or record.get("revision") != revision:
            raise LineError("chart_function_result_mismatch", "结果引用不属于当前图版本。")
        return deepcopy(record)

    def _resolve_params(self, state: ChartState, edit: CodexChartEdit, params: dict[str, Any]) -> dict[str, Any]:
        for key in ("result_ref", "ta_result_ref"):
            ref = params.pop(key, None)
            if ref:
                params.update(self.result(state, ref, edit.kind))
        candidate_ref = params.pop("candidate_result_ref", None)
        number = params.pop("candidate_number", None)
        params.pop("user_confirmed_candidate", None)
        if candidate_ref:
            candidates = self.result(state, candidate_ref, "channel_candidates" if edit.kind == "channel" else "range_candidates").get("candidates")
            if not isinstance(candidates, list) or not isinstance(number, int) or not 1 <= number <= len(candidates):
                raise LineError("candidate_not_found", "所选候选不存在或不属于当前图。")
            selected = candidates[number - 1]
            if edit.kind == "channel":
                anchors = selected.get("anchors", {})
                try:
                    params.update({"start_time": str(anchors["from"]["time"]), "start_price": anchors["from"]["price"],
                                   "end_time": str(anchors["to"]["time"]), "end_price": anchors["to"]["price"],
                                   "parallel_time": str(anchors["parallel"]["time"]), "parallel_price": anchors["parallel"]["price"]})
                except (TypeError, KeyError):
                    raise LineError("candidate_result_invalid", "通道候选锚点不完整。") from None
            else:
                try:
                    params.update({"start_time": str(selected["start_time"]), "end_time": str(selected["end_time"]),
                                   "lower_price": selected["lower_price"], "upper_price": selected["upper_price"]})
                except (TypeError, KeyError):
                    raise LineError("candidate_result_invalid", "平台候选边界不完整。") from None
        return params

    def _edit_payload(self, payload: dict[str, Any], edit: CodexChartEdit, params: dict[str, Any], request_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if edit.kind == "all_drawings":
            copy = deepcopy(payload)
            old = len(copy.get("chartCommands", []))
            copy["chartCommands"] = [item for item in copy.get("chartCommands", []) if item.get("type") not in _EDITABLE_COMMANDS]
            if old == len(copy["chartCommands"]):
                raise LineError("drawing_not_found", "当前图没有可清空的 AI 图形。")
            return copy, {"kind": "all_drawings", "deleted_count": old - len(copy["chartCommands"])}
        arguments = dict(params)
        argument_id = {"horizontal_line": "line_id", "trend_line": "line_id", "channel": "channel_id",
                       "rectangle": "rectangle_id", "fibonacci_retracement": "fibonacci_id",
                       "labeled_polyline": "polyline_id", "series_line": "series_id", "price_band": "band_id",
                       "price_sticks": "sticks_id", "text_annotation": "annotation_id",
                       "number_annotation": "annotation_id", "icon_annotation": "annotation_id"}[edit.kind]
        if edit.object_id is not None: arguments[argument_id] = edit.object_id
        if edit.action == "create": arguments["request_id"] = request_id
        if edit.kind == "horizontal_line": return edit_horizontal_line(payload, edit.action, **arguments)
        if edit.kind == "trend_line": return edit_trend_line(payload, edit.action, **arguments)
        if edit.kind == "channel": return edit_channel(payload, edit.action, **arguments)
        if edit.kind == "rectangle": return edit_rectangle(payload, edit.action, **arguments)
        if edit.kind == "fibonacci_retracement": return edit_fibonacci(payload, edit.action, **arguments)
        if edit.kind == "labeled_polyline": return edit_polyline(payload, edit.action, **arguments)
        if edit.kind in ANNOTATION_KINDS:
            arguments["kind"] = edit.kind
            arguments["text"] = arguments.pop("annotation_text", None)
            arguments["value"] = arguments.pop("annotation_value", None)
            arguments["icon"] = arguments.pop("annotation_icon", None)
            return edit_annotation(payload, edit.action, **arguments)
        if edit.kind == "series_line": return edit_price_series(payload, edit.action, **arguments)
        if edit.kind == "price_band": return edit_price_band(payload, edit.action, **arguments)
        return edit_price_sticks(payload, edit.action, **arguments)

    def prepare(self, context_ref: str, expected_revision: int, chart_session: str, symbol: str,
                request_id: str, edit: CodexChartEdit | dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128 or any(ord(char) < 32 for char in request_id):
            raise LineError("invalid_request_id", "request_id 必须为1至128字符。")
        try:
            parsed = edit if isinstance(edit, CodexChartEdit) else CodexChartEdit.model_validate(edit)
        except ValidationError as exc:
            raise LineError("invalid_chart_edit", "绘图参数无效。") from exc
        state = self._state(context_ref)
        if expected_revision != state.revision:
            raise LineError("chart_context_revision_conflict", "当前图观察版本已变化，请重新读取。")
        if chart_session != state.chart_session or str(symbol).casefold() != str(state.payload.get("symbol", "")).casefold():
            raise LineError("chart_snapshot_not_aligned", "图表会话、标的或当前版本不一致。")
        params = self._resolve_params(state, parsed, _edit_parameters(parsed))
        fingerprint = _hash({"revision": expected_revision, "chart_session": chart_session, "symbol": str(symbol).casefold(),
                             "edit": parsed.model_dump(exclude_none=True), "parameters": params})
        previous = state.request_ids.get(request_id)
        if previous:
            if previous.fingerprint != fingerprint:
                raise LineError("request_conflict", "同一 request_id 的参数不同。")
            return self._candidate_result(state, previous, replayed=True)
        if any(candidate.revision == expected_revision for candidate in state.request_ids.values()):
            raise LineError("chart_edit_revision_consumed", "该版本已有准备结果；请先应用或重新读取上下文。")
        edited, object_value = self._edit_payload(state.payload, parsed, params, request_id)
        candidate = Candidate(token=secrets.token_urlsafe(24), request_id=request_id, revision=expected_revision,
                              fingerprint=fingerprint, edited_payload=edited,
                              edit={"kind": parsed.kind, "action": parsed.action, "object_id": parsed.object_id}, object=object_value)
        state.candidates[candidate.token] = candidate
        state.request_ids[request_id] = candidate
        return self._candidate_result(state, candidate)

    def _candidate_result(self, state: ChartState, candidate: Candidate, *, replayed: bool = False) -> dict[str, Any]:
        return {"ok": True, "scope": "guarded_preparation", "operation_status": candidate.status,
                "apply_status": "not_requested" if candidate.status == "prepared" else candidate.status,
                "render_verified": False, "pixel_verified": False, "ui_receipt": "not_reported" if not candidate.ui_acknowledged else "rendered",
                "context_ref": state.context_ref, "expected_revision": candidate.revision, "chart_session": candidate.token,
                "parent_chart_session": state.chart_session, "symbol": state.payload.get("symbol"),
                "interval": state.payload.get("interval"), "request_id": candidate.request_id,
                "edit": deepcopy(candidate.edit), "object": deepcopy(candidate.object), "replayed": replayed,
                "source_snapshot_alignment": "verified_for_preparation"}

    def apply(self, context_ref: str, candidate_chart_session: str) -> dict[str, Any]:
        state = self._state(context_ref)
        candidate = state.candidates.get(candidate_chart_session)
        if candidate is None:
            raise LineError("chart_edit_candidate_not_found", "候选不属于当前对话或已经失效。")
        if candidate.status == "applied":
            return self.status(context_ref, candidate_chart_session)
        if candidate.revision != state.revision:
            candidate.status = "rejected"
            raise LineError("chart_context_revision_conflict", "图表已变化，候选不能覆盖新版本。")
        state.payload = deepcopy(candidate.edited_payload)
        state.revision += 1
        state.chart_session = secrets.token_urlsafe(24)
        candidate.status = "applied"
        return {**self.status(context_ref, candidate_chart_session), "chart_payload": self.chart_payload(context_ref)}

    def acknowledge(self, context_ref: str, candidate_chart_session: str, *, rendered: bool, reason: str | None = None) -> dict[str, Any]:
        state = self._state(context_ref)
        candidate = state.candidates.get(candidate_chart_session)
        if candidate is None or candidate.status != "applied":
            raise LineError("chart_edit_candidate_not_found", "只有已提交候选才能回执渲染状态。")
        candidate.ui_acknowledged = bool(rendered)
        candidate.render_failure = None if rendered else str(reason or "ui_render_failed")[:240]
        return self.status(context_ref, candidate_chart_session)

    def status(self, context_ref: str, candidate_chart_session: str) -> dict[str, Any]:
        state = self._state(context_ref)
        candidate = state.candidates.get(candidate_chart_session)
        if candidate is None:
            raise LineError("chart_edit_candidate_not_found", "候选不属于当前对话。")
        return {"ok": True, "context_ref": context_ref, "candidate_chart_session": candidate_chart_session,
                "apply_status": candidate.status, "state_commit": candidate.status == "applied",
                "ui_receipt": "rendered" if candidate.ui_acknowledged else ("failed" if candidate.render_failure else "not_reported"),
                "ui_failure": candidate.render_failure, "render_verified": False, "pixel_verified": False,
                "confirmation_scope": "server_state_and_optional_ui_receipt_not_pixels",
                "current_revision": state.revision, "current_chart_session": state.chart_session}
