"""Deterministic linear-regression channel statistics over an explicit bar range."""
from __future__ import annotations

import math

from core.rows import RowsValidationError, validate_rows
from tools.lines import LineError

MIN_REGRESSION_BARS = 10
MAX_REGRESSION_BARS = 4000


def regression_channel(rows, *, start_time, end_time, multiplier=2.0):
    """Fit close ~ candle-index over an inclusive explicit range.

    The channel boundaries are regression line +/- multiplier * population RMS
    residual. It returns statistics only and never creates a chart drawing.
    """
    if type(start_time) is not int or type(end_time) is not int or start_time >= end_time:
        raise LineError("invalid_regression_range", "回归区间起点必须早于终点且对应明确的K线。")
    if type(multiplier) not in (int, float) or not math.isfinite(multiplier) or not 0.5 <= multiplier <= 5:
        raise LineError("invalid_regression_multiplier", "multiplier 必须是0.5至5之间的有限数值。")
    try:
        candles = validate_rows(rows, min_len=MIN_REGRESSION_BARS)
    except RowsValidationError:
        raise LineError("insufficient_regression_history", "当前已加载K线不足10根，无法计算回归通道；未补取行情。") from None

    indexes = {int(row["time"]): index for index, row in enumerate(candles)}
    if start_time not in indexes or end_time not in indexes:
        raise LineError("regression_anchor_not_found", "回归区间两端必须精确对应当前已加载K线；未吸附或补取行情。")
    first, last = indexes[start_time], indexes[end_time]
    if first >= last:
        raise LineError("invalid_regression_range", "回归区间起点必须早于终点；未自动交换。")
    selected = candles[first:last + 1]
    if len(selected) < MIN_REGRESSION_BARS:
        raise LineError("insufficient_regression_range", "指定区间至少需要10根已加载K线。")
    if len(selected) > MAX_REGRESSION_BARS:
        raise LineError("regression_range_too_large", "指定回归区间最多4000根已加载K线。")

    prices = [float(row["close"]) for row in selected]
    if any(not math.isfinite(price) or price <= 0 for price in prices):
        raise LineError("invalid_regression_data", "回归区间收盘价必须为大于零的有限数值。")

    count = len(prices)
    x_mean = (count - 1) / 2
    y_mean = math.fsum(prices) / count
    denominator = math.fsum((index - x_mean) ** 2 for index in range(count))
    slope = math.fsum((index - x_mean) * (price - y_mean)
                      for index, price in enumerate(prices)) / denominator
    intercept = y_mean - slope * x_mean
    fitted = [intercept + slope * index for index in range(count)]
    residuals = [price - estimate for price, estimate in zip(prices, fitted)]
    residual_variance = math.fsum(value * value for value in residuals) / count
    residual_stddev = math.sqrt(max(0.0, residual_variance))
    total_variance = math.fsum((price - y_mean) ** 2 for price in prices)
    residual_sum_squares = math.fsum(value * value for value in residuals)
    r_squared = 1.0 if total_variance == 0 else 1 - residual_sum_squares / total_variance
    width = multiplier * residual_stddev
    line_start, line_end = fitted[0], fitted[-1]
    result = {
        "start_time": start_time,
        "end_time": end_time,
        "bar_count": count,
        "price_source": "close",
        "x_axis": "loaded_candle_index",
        "fit": "ordinary_least_squares",
        "slope_per_bar": slope,
        "regression_start_price": line_start,
        "regression_end_price": line_end,
        "residual_stddev_population": residual_stddev,
        "multiplier": float(multiplier),
        "channel_width": width,
        "upper_start_price": line_start + width,
        "upper_end_price": line_end + width,
        "lower_start_price": line_start - width,
        "lower_end_price": line_end - width,
        "r_squared": min(1.0, max(0.0, r_squared)),
        "direction": "ascending" if slope > 0 else "descending" if slope < 0 else "horizontal",
        "boundary_rule": "ols_close_plus_minus_multiplier_times_population_rms_residual",
        "automatic_anchor_selection": False,
    }
    if any(not math.isfinite(value) for key, value in result.items()
           if key not in {"start_time", "end_time", "bar_count", "price_source", "x_axis", "fit", "direction", "boundary_rule", "automatic_anchor_selection"}):
        raise LineError("invalid_regression_result", "回归计算产生非有限数值，未保存结果。")
    if result["lower_start_price"] <= 0 or result["lower_end_price"] <= 0:
        raise LineError("invalid_regression_boundary", "回归下轨必须保持正价格；请调整区间或 multiplier。")
    return result
