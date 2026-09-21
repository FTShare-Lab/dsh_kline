"""Render one normalized analysis for either UI without starting host services."""
from typing import Any, Callable


def render_analysis(result: dict[str, Any], renderer: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    chart = result["chart"]
    payload = renderer(
        chart["rows"], indicators=chart["indicators"], ma_periods=chart["ma_periods"],
        marks=chart["marks"], interval=result["interval"], symbol=result["symbol"],
        name=result["name"], data_source=result["source"], **chart["render_options"],
    )
    payload["adjust"] = result["adjust"]
    return payload
