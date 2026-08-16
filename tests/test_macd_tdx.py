"""Independent Tongdaxin MACD reference vs series_macd.

The reference EMA is intentionally reimplemented here (not imported from
core.calc._ema_tdx) so a production seed bug cannot green-wash itself.
"""

from __future__ import annotations

import math
from typing import Sequence

from core.calc import series_macd


def _ref_ema_tdx(values: Sequence[float | None], period: int) -> list[float | None]:
    """Standalone Tongdaxin EMA: Y[0]=first finite X, k=2/(n+1)."""
    out: list[float | None] = [None] * len(values)
    if period <= 0:
        return out
    k = 2.0 / (period + 1)
    prev: float | None = None
    for i, v in enumerate(values):
        if v is None:
            out[i] = prev
            continue
        x = float(v)
        if prev is None:
            prev = x
            out[i] = prev
        else:
            prev = x * k + prev * (1.0 - k)
            out[i] = prev
    return out


def _ref_macd(
    closes: Sequence[float],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, list[float | None]]:
    """Standalone MACD: tdx EMA + hist = 2*(DIF-DEA)."""
    vals: list[float | None] = [float(c) for c in closes]
    ema_f = _ref_ema_tdx(vals, fast)
    ema_s = _ref_ema_tdx(vals, slow)
    dif: list[float | None] = []
    for a, b in zip(ema_f, ema_s):
        if a is None or b is None:
            dif.append(None)
        else:
            dif.append(a - b)
    dea = _ref_ema_tdx(dif, signal)
    hist: list[float | None] = []
    for d, e in zip(dif, dea):
        if d is None or e is None:
            hist.append(None)
        else:
            hist.append(2.0 * (d - e))
    return {"dif": dif, "dea": dea, "hist": hist}


def _synthetic_closes(n: int = 80, seed: float = 30.0) -> list[float]:
    closes: list[float] = []
    p = seed
    for i in range(n):
        # mild oscillation so DIF/DEA are non-trivial
        p = max(1.0, p + math.sin(i / 5.0) * 0.4 + math.cos(i / 11.0) * 0.25)
        closes.append(round(p, 4))
    return closes


def _rows_from_closes(closes: Sequence[float], t0: int = 1_700_000_000) -> list[dict]:
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "time": t0 + i * 86400,
                "open": c,
                "high": c + 0.2,
                "low": c - 0.2,
                "close": c,
                "volume": 1_000_000.0,
            }
        )
    return rows


def test_macd_matches_independent_tdx_reference() -> None:
    closes = _synthetic_closes(90)
    rows = _rows_from_closes(closes)
    got = series_macd(rows, 12, 26, 9)
    ref = _ref_macd(closes, fast=12, slow=26, signal=9)

    times = [r["time"] for r in rows]
    # With Y[0]=X[0], DIF/DEA/hist exist from bar 0.
    assert len(got["dif"]) == len(times)
    assert len(got["dea"]) == len(times)
    assert len(got["hist"]) == len(times)

    for i, t in enumerate(times):
        for name in ("dif", "dea", "hist"):
            rv = ref[name][i]
            assert rv is not None
            gv = got[name][t]
            # production rounds to 6 decimals on store
            assert abs(gv - round(float(rv), 6)) < 1e-9, (
                f"{name}[{i}] t={t}: got={gv} ref_rounded={round(float(rv), 6)} raw_ref={rv}"
            )

    # hist identity on stored maps: each of dif/dea/hist rounded independently →
    # abs(hist - 2*(dif-dea)) can be up to ~2e-6 (two 6dp ULPs).
    for t in got["hist"]:
        expect = 2.0 * (got["dif"][t] - got["dea"][t])
        assert abs(got["hist"][t] - expect) <= 5e-6


def test_macd_tdx_seed_differs_from_sma_seed_early_bars() -> None:
    """Sanity: first-value seed ≠ SMA seed on early bars (why P2-3 exists)."""
    closes = _synthetic_closes(40, seed=15.0)
    # SMA-seed EMA (local, not production MACD path)
    def ema_sma(vals: list[float], period: int) -> list[float | None]:
        out: list[float | None] = [None] * len(vals)
        k = 2.0 / (period + 1)
        prev: float | None = None
        for i, v in enumerate(vals):
            if prev is None:
                if i + 1 < period:
                    continue
                prev = sum(vals[i + 1 - period : i + 1]) / period
                out[i] = prev
            else:
                prev = v * k + prev * (1 - k)
                out[i] = prev
        return out

    tdx = _ref_ema_tdx(closes, 12)
    sma = ema_sma(closes, 12)
    # first bar: tdx has value, sma usually None
    assert tdx[0] is not None
    assert sma[0] is None
    # after warm-up both exist; early values should differ on oscillating series
    diffs = [
        abs(tdx[i] - sma[i])  # type: ignore[operator]
        for i in range(len(closes))
        if tdx[i] is not None and sma[i] is not None
    ]
    assert diffs and max(diffs) > 1e-6, "expected early-bar divergence between seeds"


def test_macd_hist_is_double_dif_minus_dea_on_fixture() -> None:
    closes = [10.0, 10.5, 11.0, 10.8, 10.2, 10.0, 10.4, 11.2, 11.5, 11.1] * 6
    rows = _rows_from_closes(closes)
    got = series_macd(rows)
    for t in got["hist"]:
        # production rounds dif/dea/hist independently → ~2 ULP at 6dp vs 2*(dif-dea)
        expect = 2.0 * (got["dif"][t] - got["dea"][t])
        assert abs(got["hist"][t] - expect) <= 5e-6
