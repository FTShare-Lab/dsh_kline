"""Canonical OHLCV row helpers for dsh_kline.

Public API time unit: **unix seconds** (int) end-to-end.
The **only** place that multiplies by 1000 is the view (klinecharts needs ms).

Bar time (v1, pinned to 8001):
Canonical ``time`` = bar **close** timestamp. When the upstream source provides
an explicit start timestamp, ``open_time`` retains it as optional metadata.
  FTShare: prefer ``ts_millis`` (close), never silently prefer ``ts_millis_open``.
  Day bars: open/close same calendar day → fine.
  Minute bars: close-time shifts marks by ~1 interval — known landmine; v1 is
  day-first. Document only; do not switch to open without migrating 8001 marks.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

# Values above this are treated as milliseconds regardless of field name.
# unix-sec for year ~2286 ≈ 1e10; ms values for modern dates are ≥ 1e12.
_MS_THRESHOLD = 10_000_000_000  # 1e10

# A-share calendar dates are wall-clock China. Fixed offset (no DST) so the same
# "YYYY-MM-DD" is reproducible on UTC servers and Shanghai laptops.
_CN_TZ = timezone(timedelta(hours=8))


class RowsValidationError(ValueError):
    """Raised when incoming rows fail the contract gate."""


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date_text_to_sec(date_txt: str) -> int | None:
    """Parse YYYY-MM-DD as Asia/Shanghai midnight → unix seconds (portable)."""
    try:
        dt = datetime.strptime(date_txt[:10], "%Y-%m-%d").replace(tzinfo=_CN_TZ)
        return int(dt.timestamp())
    except Exception:
        return None


def _to_time_sec(v: Any) -> int | None:
    """Coerce a timestamp-like value to unix **seconds**.

    Magnitude-based ms detection (not field-name-based):
    if value > 1e10, treat as ms and ÷1000. Handles callers who stuff ms into
    a field named ``time``.
    """
    n = _to_float(v)
    if n is None or n <= 0:
        return None
    if n > _MS_THRESHOLD:
        n = n / 1000.0
    return int(n)


def _pick_raw_time(raw: dict[str, Any]) -> Any:
    """Pick bar **close** timestamp from heterogeneous keys.

    Semantic lock: every accepted field is interpreted as **close** time.
    If a data source puts open-time under ``ts``/``timestamp`` without also
    providing the FTShare close/open pair, the caller must align it first —
    otherwise marks silently drift vs 8001.

    Priority (locked):
      0. FTShare pair present (both ``ts_millis`` + ``ts_millis_open``):
         **always** ``ts_millis`` (close). Beats generic ``ts``/``time`` so a
         coincidental open-named ``ts`` cannot steal the bar clock.
      1. Explicit host canonical: ``time`` / ``timestamp`` / ``ts``
      2. FTShare close alone: ``ts_millis``
      3. Last resort open: ``ts_millis_open`` only if close missing
    """
    has_close = raw.get("ts_millis") is not None and raw.get("ts_millis") != ""
    has_open = raw.get("ts_millis_open") is not None and raw.get("ts_millis_open") != ""

    # FTShare contract detected → force close. Do not let generic ``ts`` win.
    if has_close and has_open:
        return raw.get("ts_millis")

    # Explicit host-provided canonical (interpreted as close by semantic lock).
    for key in ("time", "timestamp", "ts"):
        if raw.get(key) is not None and raw.get(key) != "":
            return raw.get(key)

    if has_close:
        return raw.get("ts_millis")

    if has_open:
        return raw.get("ts_millis_open")

    return None


def _pick_raw_open_time(raw: dict[str, Any]) -> Any:
    """Return an explicit bar-open timestamp without changing ``time`` semantics."""
    for key in ("ts_millis_open", "open_time", "open_timestamp", "start_time"):
        if raw.get(key) is not None and raw.get(key) != "":
            return raw.get(key)
    return None


def normalize_rows(rows: Any) -> list[dict[str, Any]]:
    """Normalize heterogeneous candle dicts to canonical rows (no length check).

    Accepts keys:
      time / timestamp / ts / ts_millis / ts_millis_open / date / trade_date
      open high low close volume/vol
      turnover / amount (optional passthrough — no v1 metric uses it)

    Output always:
      {time: sec, open, high, low, close, volume, [open_time?], [turnover?]}
      sorted ascending by time; duplicate times keep last.
    """
    out: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return out
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        t = _to_time_sec(_pick_raw_time(raw))
        if t is None:
                    date_txt = str(raw.get("date") or raw.get("trade_date") or "").strip()[:10]
                    if date_txt:
                        t = _date_text_to_sec(date_txt)
        o = _to_float(raw.get("open"))
        h = _to_float(raw.get("high"))
        l = _to_float(raw.get("low"))
        c = _to_float(raw.get("close"))
        vol = _to_float(raw.get("volume") if raw.get("volume") is not None else raw.get("vol"))
        if t is None or None in (o, h, l, c):
            # Drop incomplete bars (OHLC missing). validate_rows may still fail
            # if too few remain.
            continue
        row: dict[str, Any] = {
            "time": int(t),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": float(vol or 0.0),
        }
        open_time = _to_time_sec(_pick_raw_open_time(raw))
        if open_time is not None and open_time <= int(t):
            row["open_time"] = int(open_time)
        turnover = _to_float(
            raw.get("turnover") if raw.get("turnover") is not None else raw.get("amount")
        )
        if turnover is not None:
            row["turnover"] = float(turnover)
        out.append(row)

    # Contract: sort by time ascending (even if input was shuffled).
    out.sort(key=lambda r: r["time"])
    # De-dup by time (keep last) — basic hygiene; advanced "reject dups" is P1.
    dedup: dict[int, dict[str, Any]] = {}
    for r in out:
        dedup[int(r["time"])] = r
    return [dedup[k] for k in sorted(dedup)]


def validate_rows(rows: Any, *, min_len: int = 2) -> list[dict[str, Any]]:
    """Contract gate for calc_* / draw_*.

    P0 basics (hard fail):
      1. empty / fewer than min_len valid bars
      2. OHLC missing after normalize (absorbed into length failure;
         if input is non-empty list but all bars lack OHLC → explicit message)
      3. timestamps sorted ascending (normalize always sorts)

    P1 (not here): high < low reject/repair, gap handling, etc.
    """
    if rows is None:
        raise RowsValidationError("rows is required (got None)")
    if not isinstance(rows, list):
        raise RowsValidationError(f"rows must be a list, got {type(rows).__name__}")
    if len(rows) == 0:
        raise RowsValidationError("rows is empty")

    raw_count = len(rows)
    norm = normalize_rows(rows)

    if raw_count > 0 and len(norm) == 0:
        raise RowsValidationError(
            f"no valid bars after normalize (input had {raw_count} items; "
            "need time + open/high/low/close on each bar)"
        )
    if len(norm) < min_len:
        raise RowsValidationError(
            f"need at least {min_len} valid bars, got {len(norm)} "
            f"(input items={raw_count})"
        )

    # Defensive: enforce monotonic times (normalize already sorts + dedups).
    prev = None
    for r in norm:
        t = int(r["time"])
        if prev is not None and t < prev:
            raise RowsValidationError(
                f"timestamps not sorted after normalize (saw {t} after {prev})"
            )
        prev = t

    return norm
