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


def _sma(values: list[float | None], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0:
        return out
    window = 0.0
    count = 0
    for i, v in enumerate(values):
        if v is None:
            # restart window on missing
            window = 0.0
            count = 0
            continue
        window += v
        count += 1
        if count > period:
            prev = values[i - period]
            if prev is not None:
                window -= prev
            count = period
        if count >= period:
            out[i] = window / period
    return out


def _ema(values: list[float | None], period: int) -> list[float | None]:
    """EMA with SMA-of-first-period seed (NOT used by MACD).

    Kept for non-Tongdaxin paths / future helpers. MACD must use `_ema_tdx`.
    """
    out: list[float | None] = [None] * len(values)
    if period <= 0:
        return out
    k = 2.0 / (period + 1)
    prev: float | None = None
    for i, v in enumerate(values):
        if v is None:
            out[i] = prev
            continue
        if prev is None:
            # seed with SMA of first `period` finite values if possible
            seed_vals = [x for x in values[: i + 1] if x is not None]
            if len(seed_vals) < period:
                continue
            prev = sum(seed_vals[-period:]) / period
            out[i] = prev
        else:
            prev = v * k + prev * (1 - k)
            out[i] = prev
    return out


def _ema_tdx(values: list[float | None], period: int) -> list[float | None]:
    """Tongdaxin / Eastmoney EMA seed: Y[0] = first finite X, then recurse.

    k = 2 / (period + 1). Emits from the first finite input (no SMA warm-up).
    Used only by `series_macd` (DIF EMAs + DEA on DIF). RSI/ATR stay on their
    own Wilder-style paths and are intentionally not switched here.
    """
    out: list[float | None] = [None] * len(values)
    if period <= 0:
        return out
    k = 2.0 / (period + 1)
    prev: float | None = None
    for i, v in enumerate(values):
        if v is None:
            out[i] = prev
            continue
        if prev is None:
            prev = float(v)  # Y[0] = X[0]
            out[i] = prev
        else:
            prev = float(v) * k + prev * (1.0 - k)
            out[i] = prev
    return out


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
    closes = _closes(rows)
    times = _times(rows)
    out: dict[str, dict[int, float]] = {}
    for p in periods:
        sma = _sma([float(c) for c in closes], int(p))
        m: dict[int, float] = {}
        for t, v in zip(times, sma):
            if v is not None:
                m[int(t)] = round(float(v), 6)
        out[f"ma{int(p)}"] = m
    return out


def series_vol_ma(
    rows: list[dict[str, Any]],
    period: int = DEFAULT_VOLUME_MA,
) -> dict[int, float]:
    vols = _volumes(rows)
    times = _times(rows)
    sma = _sma(vols, int(period))
    m: dict[int, float] = {}
    for t, v in zip(times, sma):
        if v is not None:
            m[int(t)] = round(float(v), 4)
    return m


def series_macd(
    rows: list[dict[str, Any]],
    fast: int = DEFAULT_MACD[0],
    slow: int = DEFAULT_MACD[1],
    signal: int = DEFAULT_MACD[2],
) -> dict[str, dict[int, float]]:
    """MACD series — full Tongdaxin / Eastmoney path.

    - EMA seed: Y[0]=X[0] recursive (`_ema_tdx`), not SMA-of-first-period
    - hist = 2*(DIF-DEA) (column height matches 东财 terminal habit)
    - Keys = unix **seconds**
    """
    closes = [float(c) for c in _closes(rows)]
    times = _times(rows)
    ema_fast = _ema_tdx(closes, int(fast))
    ema_slow = _ema_tdx(closes, int(slow))
    dif: list[float | None] = []
    for a, b in zip(ema_fast, ema_slow):
        if a is None or b is None:
            dif.append(None)
        else:
            dif.append(a - b)
    dea = _ema_tdx(dif, int(signal))
    hist: list[float | None] = []
    for d, e in zip(dif, dea):
        if d is None or e is None:
            hist.append(None)
        else:
            # 通达信 / 东财口径：MACD 柱 = 2*(DIF-DEA)。西方标准 MACD 柱是 DIF-DEA（不×2）。
            hist.append((d - e) * 2.0)
    out = {"dif": {}, "dea": {}, "hist": {}}
    for t, d, e, h in zip(times, dif, dea, hist):
        if d is not None:
            out["dif"][int(t)] = round(float(d), 6)
        if e is not None:
            out["dea"][int(t)] = round(float(e), 6)
        if h is not None:
            out["hist"][int(t)] = round(float(h), 6)
    return out  # type: ignore[return-value]


def series_kdj(
    rows: list[dict[str, Any]],
    n: int = DEFAULT_KDJ[0],
    m1: int = DEFAULT_KDJ[1],
    m2: int = DEFAULT_KDJ[2],
) -> dict[str, dict[int, float]]:
    highs = _highs(rows)
    lows = _lows(rows)
    closes = _closes(rows)
    times = _times(rows)
    k_map: dict[int, float] = {}
    d_map: dict[int, float] = {}
    j_map: dict[int, float] = {}
    k_prev, d_prev = 50.0, 50.0
    n = max(1, int(n))
    m1 = max(1, int(m1))
    m2 = max(1, int(m2))
    for i in range(len(rows)):
        start = max(0, i - n + 1)
        hh = max(highs[start : i + 1])
        ll = min(lows[start : i + 1])
        if hh == ll:
            rsv = 50.0
        else:
            rsv = (closes[i] - ll) / (hh - ll) * 100.0
        k = (m1 - 1) / m1 * k_prev + 1 / m1 * rsv
        d = (m2 - 1) / m2 * d_prev + 1 / m2 * k
        j = 3 * k - 2 * d
        k_prev, d_prev = k, d
        t = int(times[i])
        k_map[t] = round(k, 4)
        d_map[t] = round(d, 4)
        j_map[t] = round(j, 4)
    return {"k": k_map, "d": d_map, "j": j_map}


def series_boll(
    rows: list[dict[str, Any]],
    period: int = DEFAULT_BOLL_PERIOD,
    std_mult: float = DEFAULT_BOLL_STD,
) -> dict[str, dict[int, float]]:
    closes = _closes(rows)
    times = _times(rows)
    period = max(1, int(period))
    mid_map: dict[int, float] = {}
    up_map: dict[int, float] = {}
    low_map: dict[int, float] = {}
    for i in range(len(rows)):
        if i + 1 < period:
            continue
        window = closes[i + 1 - period : i + 1]
        mean = sum(window) / period
        var = sum((x - mean) ** 2 for x in window) / period
        sd = math.sqrt(var)
        t = int(times[i])
        mid_map[t] = round(mean, 6)
        up_map[t] = round(mean + std_mult * sd, 6)
        low_map[t] = round(mean - std_mult * sd, 6)
    return {"mid": mid_map, "upper": up_map, "lower": low_map}


def series_rsi(
    rows: list[dict[str, Any]],
    period: int = DEFAULT_RSI_PERIOD,
) -> dict[int, float]:
    closes = _closes(rows)
    times = _times(rows)
    period = max(1, int(period))
    out: dict[int, float] = {}
    if len(closes) < period + 1:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1 + rs)
    out[int(times[period])] = round(rsi, 4)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        gain = max(d, 0.0)
        loss = max(-d, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - 100.0 / (1 + rs)
        out[int(times[i])] = round(rsi, 4)
    return out


def series_vwap(rows: list[dict[str, Any]]) -> dict[int, float]:
    """Return the session-window VWAP series keyed by unix seconds.

    The chart deliberately anchors VWAP at the first supplied context bar.  The
    view fetches warm-up history independently from the visible range, so a
    range switch does not make the line jump or require another provider call.
    """
    total_price_volume = 0.0
    total_volume = 0.0
    out: dict[int, float] = {}
    for row in rows:
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        volume = max(0.0, float(row.get("volume") or 0.0))
        if volume <= 0:
            continue
        total_price_volume += ((high + low + close) / 3.0) * volume
        total_volume += volume
        if total_volume > 0:
            out[int(row["time"])] = round(total_price_volume / total_volume, 6)
    return out


def series_atr(
    rows: list[dict[str, Any]],
    period: int = DEFAULT_ATR_PERIOD,
) -> dict[int, float]:
    highs = _highs(rows)
    lows = _lows(rows)
    closes = _closes(rows)
    times = _times(rows)
    period = max(1, int(period))
    trs: list[float] = []
    for i in range(len(rows)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)
    out: dict[int, float] = {}
    if len(trs) < period:
        return out
    atr = sum(trs[:period]) / period
    out[int(times[period - 1])] = round(atr, 6)
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[int(times[i])] = round(atr, 6)
    return out


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
            # touches: bars whose high/low within band
            band = level * (tolerance_pct / 100.0)
            touches = 0
            for r in window:
                            if kind == "resistance":
                                # Count only high-side near-touches within band.
                                if abs(float(r["high"]) - level) <= band:
                                    touches += 1
                            else:
                                if abs(float(r["low"]) - level) <= band:
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
        # keep levels on the correct side of last close preferentially, sort by touches
        out.sort(key=lambda x: (-x["touches"], abs(x["price"] - last_close)))
        return out[:max_levels]

    supports = [
        x for x in cluster(swings_low, kind="support") if x["price"] <= float(rows[-1]["close"]) * 1.01
    ]
    resistances = [
        x
        for x in cluster(swings_high, kind="resistance")
        if x["price"] >= float(rows[-1]["close"]) * 0.99
    ]
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
