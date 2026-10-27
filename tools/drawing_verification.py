"""Read-only comparison of explicitly requested parameters with a named snapshot."""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.lines import ColorInput, LINE_COMMAND, LineError, validate_line_fields
from tools.trend_lines import TREND_COMMAND, resolve_anchor_time
from tools.channels import CHANNEL_COMMAND
from tools.rectangles import RECTANGLE_COMMAND
from tools.fibonacci import FIBONACCI_COMMAND, validate_ratios
from tools.polylines import POLYLINE_COMMAND, normalize_point_label
from tools.annotations import ANNOTATION_COMMAND, ANNOTATION_KINDS
from tools.price_series import SERIES_COMMAND
from tools.price_bands import BAND_COMMAND
from tools.price_sticks import STICKS_COMMAND


class DrawingExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["horizontal_line", "trend_line", "channel", "rectangle", "fibonacci_retracement", "labeled_polyline", "text_annotation", "number_annotation", "icon_annotation", "series_line", "price_band", "price_sticks"]
    id: str = Field(min_length=1, max_length=128, description="工具返回的稳定图形 ID，不按名称猜测")
    exists: bool = Field(default=True, strict=True, description="删除后填 false，并且不传其他期望参数")
    name: str | None = Field(default=None, max_length=48, description="用户原始指定的完整名称，不能缩写；空字符串也会核对")
    color: ColorInput | None = Field(default=None, description="用户原始指定颜色，可直接填绿色、红色等，核对时标准化")
    price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    start_time: str | None = None
    start_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    end_time: str | None = None
    end_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    parallel_time: str | None = None
    parallel_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    show_midline: bool | None = Field(default=None, strict=True)
    lower_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    upper_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    show_fill: bool | None = Field(default=None, strict=True)
    point_label: str | None = Field(default=None, min_length=1, max_length=16)
    point_time: str | None = None
    point_price: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    time: str | None = None
    text: str | None = Field(default=None, max_length=120)
    value: float | None = Field(default=None, allow_inf_nan=False, strict=True)
    icon: Literal["arrow_up", "arrow_down", "diamond"] | None = None
    ratios: list[Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]] | None = Field(default=None, min_length=1, max_length=16)
    series_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    bar_count: int | None = Field(default=None, strict=True, ge=1, le=4000)
    band_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    sticks_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def verify_drawings(payload: dict, expectations: list[DrawingExpectation | dict]) -> dict:
    if not isinstance(expectations, list) or not 1 <= len(expectations) <= 180:
        raise LineError("invalid_expectations", "请提供 1 至 180 项明确的图形核对条件，不能用空列表声称核验通过。")
    types = {"horizontal_line": LINE_COMMAND, "trend_line": TREND_COMMAND, "channel": CHANNEL_COMMAND, "rectangle": RECTANGLE_COMMAND,
             "fibonacci_retracement": FIBONACCI_COMMAND, "labeled_polyline": POLYLINE_COMMAND,
             "text_annotation": ANNOTATION_COMMAND, "number_annotation": ANNOTATION_COMMAND, "icon_annotation": ANNOTATION_COMMAND,
             "series_line": SERIES_COMMAND, "price_band": BAND_COMMAND, "price_sticks": STICKS_COMMAND}
    allowed = {"name", "color"}
    points = {"start": "from", "end": "to", "parallel": "parallel"}
    checks = []
    for raw in expectations:
        try:
            spec = raw if isinstance(raw, DrawingExpectation) else DrawingExpectation.model_validate(raw)
        except ValidationError as exc:
            raise LineError("invalid_expectations", "核对参数无效，请检查图形类型、字段、价格与颜色。") from exc
        requested = spec.model_dump(exclude_none=True)
        fields = set(requested) - {"kind", "id", "exists"}
        supported = allowed | {
            "horizontal_line": {"price"},
            "trend_line": {"start_time", "start_price", "end_time", "end_price"},
            "channel": {"start_time", "start_price", "end_time", "end_price"},
            "rectangle": {"start_time", "end_time", "lower_price", "upper_price", "show_fill"},
            "fibonacci_retracement": {"start_time", "start_price", "end_time", "end_price", "ratios"},
            "labeled_polyline": {"point_label", "point_time", "point_price"},
            "text_annotation": {"time", "price", "text"},
            "number_annotation": {"time", "price", "value"},
            "icon_annotation": {"time", "price", "icon"},
            "series_line": {"series_hash", "bar_count"},
            "price_band": {"band_hash", "bar_count"},
            "price_sticks": {"sticks_hash", "bar_count"},
        }[spec.kind]
        if spec.kind == "channel":
            supported |= {"parallel_time", "parallel_price", "show_midline"}
        if fields - supported or not spec.exists and fields:
            raise LineError("invalid_expectation_fields", "核对条件包含不适用的字段；删除核对只能指定类型、ID 和 exists=false。")
        if spec.kind == "labeled_polyline" and spec.point_label is None and {"point_time", "point_price"} & fields:
            raise LineError("point_label_required", "核对单点需要明确的点名。")
        _, normalized_name, normalized_color = validate_line_fields(name=spec.name, color=spec.color)
        if spec.name is not None: requested["name"] = normalized_name
        if spec.color is not None: requested["color"] = normalized_color
        if spec.ratios is not None: requested["ratios"] = validate_ratios(spec.ratios)
        if spec.point_label is not None: requested["point_label"] = normalize_point_label(spec.point_label)
        for field in fields:
            if field.endswith("_time"):
                requested[field] = resolve_anchor_time(payload, requested[field])
        if spec.kind in ANNOTATION_KINDS and "time" in fields:
            requested["time"] = resolve_anchor_time(payload, requested["time"])
        candidates = [c for c in payload.get("chartCommands", []) if c.get("type") == types[spec.kind] and c.get("id") == spec.id]
        if len(candidates) > 1:
            raise LineError("ambiguous_drawing_id", "该 ID 对应多个图形，不能安全核对。")
        drawing = candidates[0] if candidates else None
        actual = {"exists": drawing is not None}
        if drawing:
            actual.update(name=drawing.get("label", ""), color=drawing.get("color", "info"))
            if spec.kind == "horizontal_line": actual["price"] = drawing.get("price")
            elif spec.kind in ANNOTATION_KINDS:
                actual.update(time=drawing.get("time"), price=drawing.get("price"))
                field = "text" if spec.kind == "text_annotation" else "value"
                if spec.kind == "icon_annotation": actual["icon"] = drawing.get("icon")
                else: actual[field] = drawing.get(field)
            elif spec.kind == "rectangle":
                actual.update({f: drawing.get(f) for f in ("start_time", "end_time", "lower_price", "upper_price", "show_fill")})
            elif spec.kind == "labeled_polyline":
                actual["points"] = drawing.get("points")
                targets = [p for p in drawing.get("points", []) if p.get("label") == requested.get("point_label")]
                if len(targets) > 1: raise LineError("duplicate_point_label", "目标点名重复，不能安全核对。")
                if targets:
                    actual.update(point_label=targets[0]["label"], point_time=targets[0]["time"], point_price=targets[0]["price"])
            elif spec.kind == "series_line":
                actual.update(series_hash=drawing.get("series_hash"), bar_count=drawing.get("bar_count"))
            elif spec.kind == "price_band":
                actual.update(band_hash=drawing.get("band_hash"), bar_count=drawing.get("bar_count"))
            elif spec.kind == "price_sticks":
                actual.update(sticks_hash=drawing.get("sticks_hash"), bar_count=drawing.get("bar_count"))
            else:
                for prefix, key in points.items():
                    if key in drawing:
                        actual[prefix + "_time"] = drawing[key].get("time")
                        actual[prefix + "_price"] = drawing[key].get("price")
                if spec.kind == "channel": actual["show_midline"] = drawing.get("show_midline")
                if spec.kind == "fibonacci_retracement":
                    actual["ratios"] = drawing.get("ratios")
                    actual["levels"] = drawing.get("levels")
        compare = fields | {"exists"}
        mismatches = [{"field": f, "expected": requested[f], "actual": actual.get(f)}
                      for f in sorted(compare) if requested[f] != actual.get(f)]
        checks.append({"kind": spec.kind, "id": spec.id, "matches": not mismatches,
                       "expected": requested, "actual": actual, "mismatches": mismatches})
    matched = all(c["matches"] for c in checks)
    return {"matches": matched, "snapshot_verified": matched, "render_verified": False,
            "verification_scope": "provided_expectations_only", "checks": checks}
