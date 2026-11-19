"""Common named drawing requests and analysis mapping for both hosts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class DrawingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["horizontal", "trend", "fibonacci", "abc", "channel", "rectangle",
                  "double_top", "double_bottom", "head_shoulders_top", "head_shoulders_bottom", "platform", "nine_count"]
    direction: Literal["ascending", "descending", "both"] = "both"
    lookback_bars: int = Field(default=240, strict=True, ge=60, le=300)
    candidate_number: int = Field(default=1, strict=True, ge=1, le=5)
    name: str | None = Field(default=None, max_length=48)
    color: Literal["info", "warning", "danger", "success"] | None = None


def analysis_for(request):
    tool = request.tool
    if tool in {"horizontal", "trend", "fibonacci", "abc"}:
        return "recent_drawing_candidates", {"drawing_type": tool, "lookback_bars": request.lookback_bars, "max_candidates": 5}, {
            "horizontal": "horizontal_line", "trend": "trend_line", "fibonacci": "fibonacci_retracement", "abc": "labeled_polyline"}[tool]
    if tool == "channel":
        return "channel_candidates", {"direction": request.direction, "lookback_bars": request.lookback_bars,
                                      "closed_daily_only": True, "max_candidates": 5}, "channel"
    if tool == "rectangle":
        return "range_candidates", {"closed_daily_only": True, "max_candidates": 5}, "rectangle"
    if tool == "nine_count":
        return "nine_count", {"display_bars": 30}, "nine_count"
    return "price_pattern_candidates", {"pattern_types": [tool], "lookback_bars": request.lookback_bars,
                                        "max_candidates": 5}, "price_pattern"

