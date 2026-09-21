"""Shared input validation and local symbol resolution."""

from __future__ import annotations

import re
from typing import Any, Callable


SUPPORTED_INTERVALS = ("minute", "day", "week", "month", "quarter", "year")
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,15}(?:\.[A-Z]{2,6})?$", re.IGNORECASE)


def validate_interval(value: Any) -> tuple[str | None, dict[str, Any] | None]:
    raw = str(value or "").strip().lower()
    if raw in SUPPORTED_INTERVALS:
        return raw, None
    return None, {
        "error": "unsupported_interval",
        "message": f"不支持的 K 线周期“{value}”。请选择：{'、'.join(SUPPORTED_INTERVALS)}。",
        "supported_intervals": list(SUPPORTED_INTERVALS),
    }


def resolve_symbol_input(value: Any, search_fn: Callable[..., dict[str, Any]]) -> tuple[str | None, str | None, dict[str, Any] | None]:
    raw = str(value or "").strip()
    if not raw:
        return None, None, {
            "error": "invalid_symbol",
            "message": "请输入标的代码或名称，例如 600519.SH、00700.HK、NVDA.US。",
        }
    directory = search_fn(raw, limit=8)
    results = directory.get("results") if isinstance(directory, dict) else None
    if isinstance(results, list) and results:
        exact_codes = [item for item in results if str(item.get("symbol", "")).split(".")[0] == raw]
        if len(exact_codes) > 1:
            return None, None, {"error": "ambiguous_symbol", "message": "该代码对应多个市场或标的，请选择完整代码。", "candidates": exact_codes}
        folded = raw.casefold()
        exact = next(
            (item for item in results if str(item.get("symbol") or "").casefold() == folded
             or str(item.get("name") or "").casefold() == folded),
            results[0],
        )
        symbol = str(exact.get("symbol") or "").strip().upper()
        if symbol:
            return symbol, str(exact.get("name") or symbol), None
    from tools.fetch import _canonical_market_symbol

    normalized = _canonical_market_symbol(raw)
    if SYMBOL_PATTERN.fullmatch(normalized):
        return normalized, None, None
    return None, None, {
        "error": "invalid_symbol",
        "message": f"未找到标的“{raw}”。" + (str(directory.get("message")) if directory.get("message") else "请使用完整代码，例如 600519.SH、00700.HK、NVDA.US。"),
        "query": raw,
        "candidates": results[:5] if isinstance(results, list) else [],
    }


__all__ = ["SYMBOL_PATTERN", "SUPPORTED_INTERVALS", "resolve_symbol_input", "validate_interval"]
