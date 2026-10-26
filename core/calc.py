"""Single source of truth for indicators and metrics.

Rules (locked):
- Public API times are unix **seconds**.
- `calc_metrics` / `draw_kline` share the same functions + same defaults.
- Summary schemas are stable; full series returned only for chart rendering.
- No RSI divergence in v1.
- duration always emits both `duration_bars` and `duration_days` (calendar).
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from core.ta_engine import ENGINE_VERSION, NATIVE_VERSION, arrays as _ta_arrays, finite_map as _ta_map, talib


# ---------------------------------------------------------------------------
# Defaults (shared by calc_metrics + draw_kline)
# ---------------------------------------------------------------------------
DEFAULT_MA_PERIODS = [5, 10, 20, 30, 60]
DEFAULT_LOOKBACK = 60
DEFAULT_TOLERANCE_PCT = 0.5  # support/resistance touch band
DEFAULT_RSI_PERIOD = 14
DEFAULT_BOLL_PERIOD = 20
DEFAULT_BOLL_STD = 2.0
DEFAULT_ATR_PERIOD = 14
DEFAULT_VOLUME_MA = 20
DEFAULT_VOLUME_RATIO = 1.5
DEFAULT_MACD = (12, 26, 9)
DEFAULT_KDJ = (9, 3, 3)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _finite(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _round(v: float | None, n: int = 4) -> float | None:
    if v is None:
        return None
    return round(float(v), n)


def _calendar_days(t0: int, t1: int) -> int:
    """Calendar days between two unix-second timestamps (inclusive-ish span)."""
    if t1 < t0:
        t0, t1 = t1, t0
    return max(0, int((t1 - t0) // 86400))


def _closes(rows: list[dict[str, Any]]) -> list[float]:
    return [float(r["close"]) for r in rows]


def _highs(rows: list[dict[str, Any]]) -> list[float]:
    return [float(r["high"]) for r in rows]


def _lows(rows: list[dict[str, Any]]) -> list[float]:
    return [float(r["low"]) for r in rows]


def _volumes(rows: list[dict[str, Any]]) -> list[float]:
    return [float(r.get("volume") or 0.0) for r in rows]


def _times(rows: list[dict[str, Any]]) -> list[int]:
    return [int(r["time"]) for r in rows]


# ---------------------------------------------------------------------------
# Full series (used by draw_kline / SET_INDICATOR_SERIES)
# Keys of returned maps are **seconds** (str for JSON safety optional — we use int keys
# in python, tools will stringify).
# ---------------------------------------------------------------------------
def series_ma(
    rows: list[dict[str, Any]],
    periods: Iterable[int] | None = None,
) -> dict[str, dict[int, float]]:
    """Return {f"ma{p}": {time_sec: value}} for each period."""
    periods = list(periods or DEFAULT_MA_PERIODS)
    if not rows:
        return {f"ma{int(p)}": {} for p in periods}
    close = _ta_arrays(rows)["close"]
    return {f"ma{int(p)}": _ta_map(rows, talib.SMA(close, timeperiod=int(p))) for p in periods}


def series_vol_ma(
    rows: list[dict[str, Any]],
    period: int = DEFAULT_VOLUME_MA,
) -> dict[int, float]:
    if not rows:
        return {}
    volume = _ta_arrays(rows)["volume"]
    return _ta_map(rows, talib.SMA(volume, timeperiod=int(period)), digits=4)


def series_macd(
    rows: list[dict[str, Any]],
    fast: int = DEFAULT_MACD[0],
    slow: int = DEFAULT_MACD[1],
    signal: int = DEFAULT_MACD[2],
) -> dict[str, dict[int, float]]:
    """TA-Lib MACD; hist is DIF-DEA without the former x2 convention."""
    if not rows:
        return {"dif": {}, "dea": {}, "hist": {}}
    close = _ta_arrays(rows)["close"]
    dif, dea, hist = talib.MACD(close, fastperiod=int(fast), slowperiod=int(slow), signalperiod=int(signal))
    return {"dif": _ta_map(rows, dif), "dea": _ta_map(rows, dea), "hist": _ta_map(rows, hist)}


def series_kdj(
    rows: list[dict[str, Any]],
    n: int = DEFAULT_KDJ[0],
    m1: int = DEFAULT_KDJ[1],
    m2: int = DEFAULT_KDJ[2],
) -> dict[str, dict[int, float]]:
    if not rows:
        return {"k": {}, "d": {}, "j": {}}
    values = _ta_arrays(rows)
    k, d, j = talib.KDJ(values["high"], values["low"], values["close"],
                        fastk_period=int(n), slowk_period=int(m1), slowk_matype=13,
                        slowd_period=int(m2), slowd_matype=13)
    return {"k": _ta_map(rows, k, 4), "d": _ta_map(rows, d, 4), "j": _ta_map(rows, j, 4)}


def series_boll(
    rows: list[dict[str, Any]],
    period: int = DEFAULT_BOLL_PERIOD,
    std_mult: float = DEFAULT_BOLL_STD,
) -> dict[str, dict[int, float]]:
    if not rows:
        return {"mid": {}, "upper": {}, "lower": {}}
    close = _ta_arrays(rows)["close"]
    upper, mid, lower = talib.BBANDS(close, timeperiod=int(period), nbdevup=float(std_mult),
                                     nbdevdn=float(std_mult), matype=0)
    return {"mid": _ta_map(rows, mid), "upper": _ta_map(rows, upper), "lower": _ta_map(rows, lower)}


def series_rsi(
    rows: list[dict[str, Any]],
    period: int = DEFAULT_RSI_PERIOD,
) -> dict[int, float]:
    if not rows:
        return {}
    close = _ta_arrays(rows)["close"]
    return _ta_map(rows, talib.RSI(close, timeperiod=int(period)), digits=4)


def series_vwap(rows: list[dict[str, Any]]) -> dict[int, float]:
    """TA-Lib path-dependent VWAP anchored at the first supplied bar."""
    if not rows:
        return {}
    values = _ta_arrays(rows)
    return _ta_map(rows, talib.VWAP(values["high"], values["low"], values["close"], values["volume"]))


def series_atr(
    rows: list[dict[str, Any]],
    period: int = DEFAULT_ATR_PERIOD,
) -> dict[int, float]:
    if not rows:
        return {}
    values = _ta_arrays(rows)
    return _ta_map(rows, talib.ATR(values["high"], values["low"], values["close"], timeperiod=int(period)))


# ---------------------------------------------------------------------------
# Metric summaries (stable schemas for host LLM)
# ---------------------------------------------------------------------------
def metric_max_drawdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Peak-to-trough max drawdown on close series."""
    if not rows:
        return {
            "max_drawdown_pct": None,
            "peak": None,
            "trough": None,
            "duration_bars": 0,
            "duration_days": 0,
        }
    peak_idx = 0
    peak_price = float(rows[0]["close"])
    worst = 0.0
    worst_peak_idx = 0
    worst_trough_idx = 0
    for i, r in enumerate(rows):
        c = float(r["close"])
        if c > peak_price:
            peak_price = c
            peak_idx = i
        if peak_price > 0:
            dd = c / peak_price - 1.0
            if dd < worst:
                worst = dd
                worst_peak_idx = peak_idx
                worst_trough_idx = i
    peak = rows[worst_peak_idx]
    trough = rows[worst_trough_idx]
    t0, t1 = int(peak["time"]), int(trough["time"])
    return {
        "max_drawdown_pct": round(worst * 100.0, 4),
        "peak": {
            "time": t0,
            "price": round(float(peak["close"]), 4),
            "idx": worst_peak_idx,
        },
        "trough": {
            "time": t1,
            "price": round(float(trough["close"]), 4),
            "idx": worst_trough_idx,
        },
        "duration_bars": max(0, worst_trough_idx - worst_peak_idx),
        "duration_days": _calendar_days(t0, t1),
    }


def metric_support_resistance(
    rows: list[dict[str, Any]],
    *,
    lookback: int = DEFAULT_LOOKBACK,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    max_levels: int = 5,
) -> dict[str, Any]:
    """Fractal swing highs/lows clustered by tolerance_pct."""
    n = len(rows)
    lookback = max(5, min(int(lookback), n))
    window = rows[-lookback:]
    offset = n - len(window)
    # fractal: local max/min with 2-bar wings
    swings_high: list[tuple[int, float]] = []
    swings_low: list[tuple[int, float]] = []
    for i in range(2, len(window) - 2):
        h = float(window[i]["high"])
        l = float(window[i]["low"])
        if (
            h >= float(window[i - 1]["high"])
            and h >= float(window[i - 2]["high"])
            and h >= float(window[i + 1]["high"])
            and h >= float(window[i + 2]["high"])
        ):
            swings_high.append((offset + i, h))
        if (
            l <= float(window[i - 1]["low"])
            and l <= float(window[i - 2]["low"])
            and l <= float(window[i + 1]["low"])
            and l <= float(window[i + 2]["low"])
        ):
            swings_low.append((offset + i, l))

    def cluster(levels: list[tuple[int, float]], *, kind: str) -> list[dict[str, Any]]:
        if not levels:
            return []
        # sort by price
        levels = sorted(levels, key=lambda x: x[1])
        clusters: list[list[tuple[int, float]]] = []
        for idx, price in levels:
            placed = False
            for cl in clusters:
                rep = sum(p for _, p in cl) / len(cl)
                if rep > 0 and abs(price - rep) / rep * 100.0 <= tolerance_pct:
                    cl.append((idx, price))
                    placed = True
                    break
            if not placed:
                clusters.append([(idx, price)])
        out: list[dict[str, Any]] = []
        last_close = float(rows[-1]["close"])
        for cl in clusters:
            prices = [p for _, p in cl]
            idxs = [i for i, _ in cl]
            level = sum(prices) / len(prices)
            # A later bar crossing the level invalidates its original role.
            # Keep historical pivots out of the current support/resistance set.
            later = rows[max(idxs) + 1:]
            if kind == "support" and any(float(r["low"]) < level for r in later):
                continue
            if kind == "resistance" and any(float(r["high"]) > level for r in later):
                continue
            # touches: bars whose high/low within band
            band = level * (tolerance_pct / 100.0)
            touches = 0
            for r in window:
                if kind == "resistance":
                    if abs(float(r["high"]) - level) <= band:
                        touches += 1
                elif abs(float(r["low"]) - level) <= band:
                    touches += 1
            out.append(
                {
                    "price": round(level, 4),
                    "touches": int(touches),
                    "strength": round(min(1.0, touches / 5.0), 3),
                    "last_idx": int(max(idxs)),
                    "last_time": int(rows[max(idxs)]["time"]),
                    "side": "above" if level >= last_close else "below",
                }
            )
        # Rank all candidates first. Side filtering happens before the limit so
        # stale levels cannot consume the five available slots.
        out.sort(key=lambda x: (-x["touches"], abs(x["price"] - last_close)))
        return out

    last_close = float(rows[-1]["close"])
    supports = [x for x in cluster(swings_low, kind="support") if x["price"] <= last_close][:max_levels]
    resistances = [
        x
        for x in cluster(swings_high, kind="resistance")
        if x["price"] >= last_close
    ][:max_levels]
    return {
        "method": "fractal",
        "lookback": lookback,
        "tolerance_pct": float(tolerance_pct),
        "support": supports,
        "resistance": resistances,
    }


def metric_ma_cross(
    rows: list[dict[str, Any]],
    *,
    ma_periods: list[int] | None = None,
) -> dict[str, Any]:
    """All C(n,2) pairs among ma_periods. Distinguish empty crosses vs not requested.

    Schema:
      {
        "periods": [5,10,20],
        "pairs": ["5x10","5x20","10x20"],
        "crosses": [{time, idx, type: golden|death, fast, slow, price}],
        "pair_stats": {"5x10": {"cross_count": 0, "last": null}, ...}
      }
    """
    periods = sorted({int(p) for p in (ma_periods or DEFAULT_MA_PERIODS) if int(p) > 0})
    pairs = [(periods[i], periods[j]) for i in range(len(periods)) for j in range(i + 1, len(periods))]
    pair_keys = [f"{a}x{b}" for a, b in pairs]
    series = series_ma(rows, periods)
    closes = _closes(rows)
    times = _times(rows)
    crosses: list[dict[str, Any]] = []
    pair_stats: dict[str, Any] = {k: {"cross_count": 0, "last": None} for k in pair_keys}

    for a, b in pairs:
        key = f"{a}x{b}"
        ma_a = series.get(f"ma{a}", {})
        ma_b = series.get(f"ma{b}", {})
        prev_diff: float | None = None
        for i, t in enumerate(times):
            va = ma_a.get(int(t))
            vb = ma_b.get(int(t))
            if va is None or vb is None:
                prev_diff = None
                continue
            diff = va - vb
            # Exact touch (diff==0) carries no cross direction; keep previous sign.
            # Using <=0 / >=0 would phantom-cross on flat MA equalities (limit-up days).
            if diff == 0:
                continue
            if prev_diff is not None:
                # golden: fast crosses above slow (a is faster = smaller period)
                if prev_diff < 0 < diff:
                    item = {
                        "time": int(t),
                        "idx": i,
                        "type": "golden",
                        "fast": a,
                        "slow": b,
                        "price": round(closes[i], 4),
                    }
                    crosses.append(item)
                    pair_stats[key]["cross_count"] += 1
                    pair_stats[key]["last"] = item
                elif prev_diff > 0 > diff:
                    item = {
                        "time": int(t),
                        "idx": i,
                        "type": "death",
                        "fast": a,
                        "slow": b,
                        "price": round(closes[i], 4),
                    }
                    crosses.append(item)
                    pair_stats[key]["cross_count"] += 1
                    pair_stats[key]["last"] = item
            prev_diff = diff

    crosses.sort(key=lambda x: x["time"])
    return {
        "periods": periods,
        "pairs": pair_keys,
        "crosses": crosses,
        "pair_stats": pair_stats,
        # Convenience: empty crosses means computed but none found (pairs non-empty).
        # Missing pair key in pair_stats would mean "not computed" — we always fill all pairs.
    }


def metric_volume_breakout(
    rows: list[dict[str, Any]],
    *,
    volume_ma: int = DEFAULT_VOLUME_MA,
    volume_ratio: float = DEFAULT_VOLUME_RATIO,
    ma_period: int = 20,
) -> dict[str, Any]:
    """Volume spike + close cross above/below MA."""
    times = _times(rows)
    closes = _closes(rows)
    vols = _volumes(rows)
    ma_map = series_ma(rows, [ma_period]).get(f"ma{ma_period}", {})
    vol_ma_map = series_vol_ma(rows, volume_ma)
    events: list[dict[str, Any]] = []
    for i in range(1, len(rows)):
        t = int(times[i])
        t_prev = int(times[i - 1])
        ma = ma_map.get(t)
        ma_prev = ma_map.get(t_prev)
        vma = vol_ma_map.get(t)
        if ma is None or ma_prev is None or not vma or vma <= 0:
            continue
        ratio = vols[i] / vma
        if ratio < volume_ratio:
            continue
        c, c_prev = closes[i], closes[i - 1]
        direction = None
        if c_prev <= ma_prev and c > ma:
            direction = "breakout_up"
        elif c_prev >= ma_prev and c < ma:
            direction = "breakdown"
        if not direction:
            continue
        events.append(
            {
                "time": t,
                "idx": i,
                "price": round(c, 4),
                "ma": round(ma, 4),
                "volume": round(vols[i], 2),
                "volume_ma": round(vma, 2),
                "volume_ratio": round(ratio, 3),
                "direction": direction,
                "ma_period": ma_period,
            }
        )
    return {
        "volume_ma": int(volume_ma),
        "volume_ratio": float(volume_ratio),
        "ma_period": int(ma_period),
        "events": events,
        "count": len(events),
    }


def metric_bollinger(
    rows: list[dict[str, Any]],
    *,
    period: int = DEFAULT_BOLL_PERIOD,
    std_mult: float = DEFAULT_BOLL_STD,
) -> dict[str, Any]:
    series = series_boll(rows, period=period, std_mult=std_mult)
    last_t = int(rows[-1]["time"])
    last_c = float(rows[-1]["close"])
    mid = series["mid"].get(last_t)
    upper = series["upper"].get(last_t)
    lower = series["lower"].get(last_t)
    width_pct = None
    pct_b = None
    if mid is not None and upper is not None and lower is not None and upper != lower and mid != 0:
        width_pct = round((upper - lower) / mid * 100.0, 4)
        pct_b = round((last_c - lower) / (upper - lower), 4)
    return {
        "period": int(period),
        "std_mult": float(std_mult),
        "last": {
            "time": last_t,
            "close": round(last_c, 4),
            "mid": _round(mid),
            "upper": _round(upper),
            "lower": _round(lower),
            "width_pct": width_pct,
            "pct_b": pct_b,
        },
    }


def metric_rsi(
    rows: list[dict[str, Any]],
    *,
    period: int = DEFAULT_RSI_PERIOD,
) -> dict[str, Any]:
    """RSI summary. No divergence in v1."""
    s = series_rsi(rows, period=period)
    if not s:
        return {"period": int(period), "last": None, "overbought": [], "oversold": []}
    last_t = max(s)
    last_v = s[last_t]
    overbought = [
        {"time": t, "value": v} for t, v in s.items() if v >= 70
    ][-10:]
    oversold = [
        {"time": t, "value": v} for t, v in s.items() if v <= 30
    ][-10:]
    return {
        "period": int(period),
        "last": {"time": int(last_t), "value": last_v},
        "overbought": overbought,
        "oversold": oversold,
        # divergence intentionally omitted in v1
    }


def metric_atr(
    rows: list[dict[str, Any]],
    *,
    period: int = DEFAULT_ATR_PERIOD,
) -> dict[str, Any]:
    s = series_atr(rows, period=period)
    if not s:
        return {"period": int(period), "last": None, "atr_pct": None}
    last_t = max(s)
    last_atr = s[last_t]
    last_c = float(rows[-1]["close"])
    atr_pct = round(last_atr / last_c * 100.0, 4) if last_c else None
    return {
        "period": int(period),
        "last": {"time": int(last_t), "value": last_atr},
        "atr_pct": atr_pct,
    }


# ---------------------------------------------------------------------------
# Public aggregators
# ---------------------------------------------------------------------------
AVAILABLE_METRICS = (
    "max_drawdown",
    "support_resistance",
    "ma_cross",
    "volume_breakout",
    "bollinger",
    "rsi",
    "atr",
)


def calc_metrics(
    rows: list[dict[str, Any]],
    metrics: list[str] | None = None,
    *,
    lookback: int = DEFAULT_LOOKBACK,
    ma_periods: list[int] | None = None,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    rsi_period: int = DEFAULT_RSI_PERIOD,
    boll_period: int = DEFAULT_BOLL_PERIOD,
    boll_std: float = DEFAULT_BOLL_STD,
    atr_period: int = DEFAULT_ATR_PERIOD,
    volume_ma: int = DEFAULT_VOLUME_MA,
    volume_ratio: float = DEFAULT_VOLUME_RATIO,
) -> dict[str, Any]:
    """Compute selected metric **summaries** (no full series)."""
    wanted = list(metrics or list(AVAILABLE_METRICS))
    # preserve order, drop unknown
    ordered = [m for m in wanted if m in AVAILABLE_METRICS]
    unknown = [m for m in wanted if m not in AVAILABLE_METRICS]
    result: dict[str, Any] = {
        "calculation_engine": {"name": "TA-Lib", "wrapper_version": ENGINE_VERSION,
                               "native_version": NATIVE_VERSION},
        "count": len(rows),
        "start_time": int(rows[0]["time"]) if rows else None,
        "end_time": int(rows[-1]["time"]) if rows else None,
        "metrics_computed": ordered,
        "metrics_unknown": unknown,
    }
    for m in ordered:
        if m == "max_drawdown":
            result[m] = metric_max_drawdown(rows)
        elif m == "support_resistance":
            result[m] = metric_support_resistance(
                rows, lookback=lookback, tolerance_pct=tolerance_pct
            )
        elif m == "ma_cross":
            result[m] = metric_ma_cross(rows, ma_periods=ma_periods)
        elif m == "volume_breakout":
            result[m] = metric_volume_breakout(
                rows, volume_ma=volume_ma, volume_ratio=volume_ratio
            )
        elif m == "bollinger":
            result[m] = metric_bollinger(rows, period=boll_period, std_mult=boll_std)
        elif m == "rsi":
            result[m] = metric_rsi(rows, period=rsi_period)
        elif m == "atr":
            result[m] = metric_atr(rows, period=atr_period)
    return result


def calc_range(
    rows: list[dict[str, Any]],
    *,
    start_time: int | None = None,
    end_time: int | None = None,
    start_idx: int | None = None,
    end_idx: int | None = None,
) -> dict[str, Any]:
    """Interval stats over a sub-range of rows."""
    n = len(rows)
    if n == 0:
        raise ValueError("empty rows")

    if start_idx is not None or end_idx is not None:
        s = 0 if start_idx is None else max(0, min(n - 1, int(start_idx)))
        e = n - 1 if end_idx is None else max(0, min(n - 1, int(end_idx)))
    else:
        s, e = 0, n - 1
        if start_time is not None:
            st = int(start_time)
            # nearest >= start_time, else last
            s = next((i for i, r in enumerate(rows) if int(r["time"]) >= st), n - 1)
        if end_time is not None:
            et = int(end_time)
            e = next(
                (i for i in range(n - 1, -1, -1) if int(rows[i]["time"]) <= et),
                0,
            )
    if e < s:
        s, e = e, s
    win = rows[s : e + 1]
    if len(win) < 1:
        raise ValueError("empty range window")

    first, last = win[0], win[-1]
    o = float(first["open"])
    c = float(last["close"])
    hh = max(float(r["high"]) for r in win)
    ll = min(float(r["low"]) for r in win)
    ret_pct = (c / o - 1.0) * 100.0 if o else 0.0
    amp_pct = (hh - ll) / o * 100.0 if o else 0.0
    up_days = sum(1 for r in win if float(r["close"]) >= float(r["open"]))
    down_days = len(win) - up_days
    # consecutive runs
    max_up = max_down = cur_up = cur_down = 0
    for r in win:
        if float(r["close"]) >= float(r["open"]):
            cur_up += 1
            cur_down = 0
        else:
            cur_down += 1
            cur_up = 0
        max_up = max(max_up, cur_up)
        max_down = max(max_down, cur_down)
    total_vol = sum(float(r.get("volume") or 0) for r in win)
    avg_vol = total_vol / len(win) if win else 0.0
    dd = metric_max_drawdown(win)
    t0, t1 = int(first["time"]), int(last["time"])
    return {
        "start_idx": s,
        "end_idx": e,
        "start_time": t0,
        "end_time": t1,
        "bars": len(win),
        "duration_bars": len(win),
        "duration_days": _calendar_days(t0, t1),
        "open": round(o, 4),
        "close": round(c, 4),
        "high": round(hh, 4),
        "low": round(ll, 4),
        "return_pct": round(ret_pct, 4),
        "amplitude_pct": round(amp_pct, 4),
        "up_bars": up_days,
        "down_bars": down_days,
        "max_up_streak": max_up,
        "max_down_streak": max_down,
        "total_volume": round(total_vol, 2),
        "avg_volume": round(avg_vol, 2),
        "max_drawdown": dd,
    }
