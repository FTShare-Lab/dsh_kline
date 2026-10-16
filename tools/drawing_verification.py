"""Read-only comparison of explicitly requested parameters with a named snapshot."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tools.lines import ColorInput, LINE_COMMAND, LineError, validate_line_fields
from tools.trend_lines import TREND_COMMAND, resolve_anchor_time
from tools.channels import CHANNEL_COMMAND
from tools.rectangles import RECTANGLE_COMMAND


class DrawingExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["horizontal_line", "trend_line", "channel", "rectangle"]
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


def verify_drawings(payload: dict, expectations: list[DrawingExpectation | dict]) -> dict:
    if not isinstance(expectations, list) or not 1 <= len(expectations) <= 180:
        raise LineError("invalid_expectations", "请提供 1 至 180 项明确的图形核对条件，不能用空列表声称核验通过。")
    types = {"horizontal_line": LINE_COMMAND, "trend_line": TREND_COMMAND, "channel": CHANNEL_COMMAND, "rectangle": RECTANGLE_COMMAND}
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
        }[spec.kind]
        if spec.kind == "channel":
            supported |= {"parallel_time", "parallel_price", "show_midline"}
        if fields - supported or not spec.exists and fields:
            raise LineError("invalid_expectation_fields", "核对条件包含不适用的字段；删除核对只能指定类型、ID 和 exists=false。")
        _, normalized_name, normalized_color = validate_line_fields(name=spec.name, color=spec.color)
        if spec.name is not None: requested["name"] = normalized_name
        if spec.color is not None: requested["color"] = normalized_color
        for field in fields:
            if field.endswith("_time"):
                requested[field] = resolve_anchor_time(payload, requested[field])
        candidates = [c for c in payload.get("chartCommands", []) if c.get("type") == types[spec.kind] and c.get("id") == spec.id]
        if len(candidates) > 1:
            raise LineError("ambiguous_drawing_id", "该 ID 对应多个图形，不能安全核对。")
        drawing = candidates[0] if candidates else None
        actual = {"exists": drawing is not None}
        if drawing:
            actual.update(name=drawing.get("label", ""), color=drawing.get("color", "info"))
            if spec.kind == "horizontal_line": actual["price"] = drawing.get("price")
            elif spec.kind == "rectangle":
                actual.update({f: drawing.get(f) for f in ("start_time", "end_time", "lower_price", "upper_price", "show_fill")})
            else:
                for prefix, key in points.items():
                    if key in drawing:
                        actual[prefix + "_time"] = drawing[key].get("time")
                        actual[prefix + "_price"] = drawing[key].get("price")
                if spec.kind == "channel": actual["show_midline"] = drawing.get("show_midline")
        compare = fields | {"exists"}
        mismatches = [{"field": f, "expected": requested[f], "actual": actual.get(f)}
                      for f in sorted(compare) if requested[f] != actual.get(f)]
        checks.append({"kind": spec.kind, "id": spec.id, "matches": not mismatches,
                       "expected": requested, "actual": actual, "mismatches": mismatches})
    matched = all(c["matches"] for c in checks)
    return {"matches": matched, "snapshot_verified": matched, "render_verified": False,
            "verification_scope": "provided_expectations_only", "checks": checks}
