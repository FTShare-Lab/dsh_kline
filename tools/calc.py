"""Small calculation wrapper used by the standalone dsh_kline MCP server."""

from __future__ import annotations

from typing import Any

from core.calc import AVAILABLE_METRICS, calc_metrics as _calc_metrics
from core.rows import validate_rows


def run_calc_metrics(
    rows: Any,
    metrics: list[str] | None = None,
    *,
    rsi_period: int = 14,
    boll_period: int = 20,
    boll_std: float = 2.0,
    atr_period: int = 14,
    volume_ma: int = 20,
    ma_periods: list[int] | None = None,
) -> dict[str, Any]:
    normalized = validate_rows(rows, min_len=2)
    result = _calc_metrics(
        normalized,
        metrics=metrics,
        rsi_period=rsi_period,
        boll_period=boll_period,
        boll_std=boll_std,
        atr_period=atr_period,
        volume_ma=volume_ma,
        ma_periods=ma_periods,
    )
    result["available_metrics"] = list(AVAILABLE_METRICS)
    result["analysis_window"] = {
        "start_time": int(normalized[0]["time"]),
        "end_time": int(normalized[-1]["time"]),
        "bars": len(normalized),
    }
    return result
