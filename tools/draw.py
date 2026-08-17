"""Build standalone dsh_kline chart payloads and indicator commands.

All indicator series come from core.calc (same module as calc_metrics).
Public times are unix **seconds**; view multiplies by 1000 for klinecharts.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from core.calc import (
    DEFAULT_ATR_PERIOD,
    DEFAULT_BOLL_PERIOD,
    DEFAULT_BOLL_STD,
    DEFAULT_KDJ,
    DEFAULT_MACD,
    DEFAULT_MA_PERIODS,
    DEFAULT_RSI_PERIOD,
    DEFAULT_VOLUME_MA,
    series_atr,
    series_boll,
    series_kdj,
    series_ma,
    series_macd,
    series_rsi,
    series_vwap,
    series_vol_ma,
)
from core.rows import validate_rows

SUPPORTED_INDICATORS = ("ma", "vwap", "vol", "macd", "kdj", "boll", "rsi", "atr")


def _safe_https_url(value: Any) -> str | None:
    """Accept attribution URLs only when they are absolute HTTPS URLs."""
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 500:
        return None
    parsed = urlparse(candidate)
    return candidate if parsed.scheme == "https" and parsed.netloc else None


def _map_to_str_keys(m: dict[int, float]) -> dict[str, float]:
    """JSON object keys must be strings; values stay numbers. Keys are seconds."""
    return {str(int(k)): float(v) for k, v in m.items()}


def _normalize_marks(marks: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(marks, list):
        return out
    for index, m in enumerate(marks):
        if not isinstance(m, dict):
            continue
        try:
            t = int(m.get("time") or m.get("timestamp") or 0)
        except Exception:
            continue
        if t > 10_000_000_000:
            t = int(t / 1000)
        if t <= 0:
            continue
        price = m.get("price")
        try:
            price_f = float(price) if price is not None else None
        except Exception:
            price_f = None
        out.append(
            {
                "id": str(m.get("id") or f"marker:{t}:{index}")[:128],
                "time": t,
                "price": price_f,
                "text": str(m.get("text") or m.get("label") or "标注")[:48],
                "color": str(m.get("color") or "warning"),
            }
        )
    return out


def _normalize_lines(lines: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(lines, list):
        return out
    for index, ln in enumerate(lines):
        if not isinstance(ln, dict):
            continue
        fr = ln.get("from") or {}
        to = ln.get("to") or {}
        try:
            t0 = int(fr.get("time") or 0)
            t1 = int(to.get("time") or 0)
            p0 = float(fr.get("price"))
            p1 = float(to.get("price"))
        except Exception:
            continue
        if t0 > 10_000_000_000:
            t0 = int(t0 / 1000)
        if t1 > 10_000_000_000:
            t1 = int(t1 / 1000)
        if t0 <= 0 or t1 <= 0 or t0 == t1:
            continue
        out.append(
            {
                "id": str(ln.get("id") or f"line:{t0}:{t1}:{index}")[:128],
                "from": {"time": t0, "price": p0},
                "to": {"time": t1, "price": p1},
                "label": str(ln.get("label") or ln.get("text") or ""),
                "color": str(ln.get("color") or "danger"),
            }
        )
    return out


def _normalize_comparisons(comparisons: Any) -> list[dict[str, Any]]:
    """Validate optional benchmark series for direct, one-shot chart rendering."""
    if not isinstance(comparisons, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in comparisons[:3]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        rows = item.get("rows")
        if not symbol or not isinstance(rows, list):
            continue
        try:
            normalized_rows = validate_rows(rows, min_len=2)
        except (TypeError, ValueError):
            continue
        normalized.append(
            {
                "symbol": symbol[:48],
                "name": str(item.get("name") or symbol)[:120],
                "rows": normalized_rows,
            }
        )
    return normalized


def build_chart_commands(
    rows: list[dict[str, Any]],
    *,
    indicators: list[str] | None = None,
    ma_periods: list[int] | None = None,
    marks: Any = None,
    lines: Any = None,
    boll_period: int = DEFAULT_BOLL_PERIOD,
    boll_std: float = DEFAULT_BOLL_STD,
    volume_ma: int = DEFAULT_VOLUME_MA,
    rsi_period: int = DEFAULT_RSI_PERIOD,
    atr_period: int = DEFAULT_ATR_PERIOD,
) -> list[dict[str, Any]]:
    """Build chartCommands. Indicator series keys are **seconds** (view ×1000)."""
    requested_indicators = ["ma", "vol"] if indicators is None else indicators
    inds = [str(x).lower() for x in requested_indicators if str(x).lower() in SUPPORTED_INDICATORS]
    periods = list(ma_periods or DEFAULT_MA_PERIODS)
    cmds: list[dict[str, Any]] = []

    if rows:
        cmds.append(
            {
                "type": "SET_CANDLES",
                "rows": rows,  # view needs candles; host LLM content should still not dump them
            }
        )
        cmds.append(
            {
                "type": "SET_RANGE",
                "start": int(rows[0]["time"]),
                "end": int(rows[-1]["time"]),
            }
        )

    # MA series
    if "ma" in inds:
        ma_maps = series_ma(rows, periods)
        data = {name: _map_to_str_keys(m) for name, m in ma_maps.items()}
        cmds.append(
            {
                "type": "SET_INDICATOR_SERIES",
                "name": "ma",
                "pane": "candle",
                "params": {"periods": periods},
                "data": data,  # keys = seconds (stringified)
                "note": "data keys are unix seconds; view multiplies by 1000 for klinecharts",
            }
        )

    if "vwap" in inds:
        cmds.append(
            {
                "type": "SET_INDICATOR_SERIES",
                "name": "vwap",
                "pane": "candle",
                "params": {"anchor": "loaded_context"},
                "data": {"vwap": _map_to_str_keys(series_vwap(rows))},
                "note": "data keys are unix seconds; view multiplies by 1000 for klinecharts",
            }
        )

    if "vol" in inds:
        vol_map = series_vol_ma(rows, volume_ma)
        # raw volume is already on candles; only pass MA for overlay reference if needed
        cmds.append(
            {
                "type": "SET_INDICATOR_SERIES",
                "name": "vol",
                "pane": "vol",
                "params": {"ma_period": int(volume_ma)},
                "data": {"vol_ma": _map_to_str_keys(vol_map)},
                "note": "data keys are unix seconds; view multiplies by 1000 for klinecharts",
            }
        )

    if "macd" in inds:
        macd = series_macd(rows, *DEFAULT_MACD)
        cmds.append(
            {
                "type": "SET_INDICATOR_SERIES",
                "name": "macd",
                "pane": "macd",
                "params": {"fast": DEFAULT_MACD[0], "slow": DEFAULT_MACD[1], "signal": DEFAULT_MACD[2]},
                "data": {
                    "dif": _map_to_str_keys(macd["dif"]),
                    "dea": _map_to_str_keys(macd["dea"]),
                    "hist": _map_to_str_keys(macd["hist"]),
                },
                "note": "data keys are unix seconds; view multiplies by 1000 for klinecharts",
            }
        )

    if "kdj" in inds:
        kdj = series_kdj(rows, *DEFAULT_KDJ)
        cmds.append(
            {
                "type": "SET_INDICATOR_SERIES",
                "name": "kdj",
                "pane": "kdj",
                "params": {"n": DEFAULT_KDJ[0], "m1": DEFAULT_KDJ[1], "m2": DEFAULT_KDJ[2]},
                "data": {
                    "k": _map_to_str_keys(kdj["k"]),
                    "d": _map_to_str_keys(kdj["d"]),
                    "j": _map_to_str_keys(kdj["j"]),
                },
                "note": "data keys are unix seconds; view multiplies by 1000 for klinecharts",
            }
        )

    if "boll" in inds:
        boll = series_boll(rows, period=boll_period, std_mult=boll_std)
        cmds.append(
            {
                "type": "SET_INDICATOR_SERIES",
                "name": "boll",
                "pane": "candle",
                "params": {"period": int(boll_period), "std_mult": float(boll_std)},
                "data": {
                    "mid": _map_to_str_keys(boll["mid"]),
                    "upper": _map_to_str_keys(boll["upper"]),
                    "lower": _map_to_str_keys(boll["lower"]),
                },
                "note": "data keys are unix seconds; view multiplies by 1000 for klinecharts",
            }
        )

    if "rsi" in inds:
        rsi = series_rsi(rows, period=rsi_period)
        cmds.append(
            {
                "type": "SET_INDICATOR_SERIES",
                "name": "rsi",
                "pane": "rsi",
                "params": {"period": int(rsi_period)},
                "data": {"rsi": _map_to_str_keys(rsi)},
                "note": "data keys are unix seconds; view multiplies by 1000 for klinecharts",
            }
        )

    if "atr" in inds:
        atr = series_atr(rows, period=atr_period)
        cmds.append(
            {
                "type": "SET_INDICATOR_SERIES",
                "name": "atr",
                "pane": "atr",
                "params": {"period": int(atr_period)},
                "data": {"atr": _map_to_str_keys(atr)},
                "note": "data keys are unix seconds; view multiplies by 1000 for klinecharts",
            }
        )

    for ln in _normalize_lines(lines):
        cmds.append(
            {
                "type": "DRAW_TREND_LINE",
                "id": ln["id"],
                "from": ln["from"],
                "to": ln["to"],
                "label": ln["label"],
                "color": ln["color"],
            }
        )

    for mk in _normalize_marks(marks):
        # fallback price to nearest bar high if missing (labels sit above candle)
        price = mk["price"]
        if price is None:
            nearest = min(rows, key=lambda r: abs(int(r["time"]) - mk["time"])) if rows else None
            price = float(nearest["high"]) if nearest else 0.0
        cmds.append(
            {
                "type": "TEXT_MARKER",
                "id": mk["id"],
                "time": mk["time"],
                "price": float(price),
                "text": mk["text"],
                "color": mk["color"],
            }
        )

    return cmds


def draw_kline(
    rows: Any,
    *,
    indicators: list[str] | None = None,
    ma_periods: list[int] | None = None,
    marks: Any = None,
    lines: Any = None,
    comparisons: Any = None,
    security_workspace: Any = None,
    symbol: str | None = None,
    name: str | None = None,
    data_source: str | None = None,
    data_source_url: str | None = None,
    interval: str = "day",
    boll_period: int = DEFAULT_BOLL_PERIOD,
    boll_std: float = DEFAULT_BOLL_STD,
    volume_ma: int = DEFAULT_VOLUME_MA,
    rsi_period: int = DEFAULT_RSI_PERIOD,
    atr_period: int = DEFAULT_ATR_PERIOD,
) -> dict[str, Any]:
    """Return a self-contained chart session payload."""
    norm = validate_rows(rows, min_len=2)
    requested_indicators = ["ma", "vol"] if indicators is None else indicators
    inds = [str(x).lower() for x in requested_indicators if str(x).lower() in SUPPORTED_INDICATORS]
    cmds = build_chart_commands(
        norm,
        indicators=inds,
        ma_periods=ma_periods,
        marks=marks,
        lines=lines,
        boll_period=boll_period,
        boll_std=boll_std,
        volume_ma=volume_ma,
        rsi_period=rsi_period,
        atr_period=atr_period,
    )
    comparison_series = _normalize_comparisons(comparisons)
    if comparison_series:
        cmds.append({"type": "SET_COMPARISON_SERIES", "series": comparison_series})
    # Structured payload for the view (includes SET_CANDLES rows).
    # Content text stays compact for host LLM context.
    payload = {
        "symbol": symbol or "",
        "name": name or symbol or "",
        "interval": (interval or "day").lower(),
        "count": len(norm),
        "start_time": int(norm[0]["time"]),
        "end_time": int(norm[-1]["time"]),
        "indicators": inds,
        "chartCommands": cmds,
        # Convenience cards for view header
        "last_close": float(norm[-1]["close"]),
        "last_time": int(norm[-1]["time"]),
    }
    if isinstance(security_workspace, dict):
        # The app only consumes this provider-neutral schema. Supplying it with
        # the draw payload keeps news/company data visible even when the host
        # cannot issue a second in-app tools/call request.
        payload["security_workspace"] = security_workspace
    if data_source and str(data_source).strip():
        payload["data_meta"] = {"source": str(data_source).strip()[:120]}
        source_url = _safe_https_url(data_source_url)
        if source_url:
            payload["data_meta"]["source_url"] = source_url
    return payload
