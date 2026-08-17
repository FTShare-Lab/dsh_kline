"""Optional ftshare-backed candle fetch.

ftshare is an *optional* dependency:
- installed → fetch_candles works
- missing  → returns structured error `ftshare_not_installed`

Discovery order:
1. already importable ``ftshare`` from the active Python environment
2. optional ``FTSHARE_SDK_SRC`` env pointing to a package checkout

This module never searches for or imports another MCP repository.
"""

from __future__ import annotations

import os
import json
import re
import sys
import time
from copy import deepcopy
from datetime import datetime, time as clock_time, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


_SYMBOL_SEARCH_CACHE_TTL_SECONDS = 300.0
_SYMBOL_SEARCH_CACHE_MAX_ENTRIES = 96
_symbol_search_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_SECURITY_WORKSPACE_CACHE_TTL_SECONDS = 300.0
_security_workspace_cache: dict[str, tuple[float, dict[str, Any]]] = {}
# A short hot cache serves a search-result prefetch immediately when the user
# opens the same symbol.  It is deliberately much shorter than the stale
# fallback cache below: this is a latency optimization, not an availability
# substitute for live provider data.
_CANDLE_CACHE_FRESH_SECONDS = 45.0
_CANDLE_CACHE_TTL_SECONDS = 15 * 60.0
_candle_cache: dict[tuple[str, str, int, int, int, str], tuple[float, dict[str, Any]]] = {}
SYMBOL_DIRECTORY_VERSION = 4
SYMBOL_DIRECTORY_TTL_SECONDS = 24 * 60 * 60
SYMBOL_DIRECTORY_RETRY_SECONDS = 60 * 60
SYMBOL_DIRECTORY_MAX_ITEMS = 20_000
CN_BROAD_INDEXES = (
    {"symbol": "000001.XSHG", "name": "上证指数", "market": "CN_INDEX", "aliases": "沪指 上证综指 上证综合指数 shanghai composite"},
    {"symbol": "000016.XSHG", "name": "上证50", "market": "CN_INDEX", "aliases": "上证五十 sse 50"},
    {"symbol": "000010.XSHG", "name": "上证180", "market": "CN_INDEX", "aliases": "上证一百八 sse 180"},
    {"symbol": "000009.XSHG", "name": "上证380", "market": "CN_INDEX", "aliases": "上证三百八 sse 380"},
    {"symbol": "000047.XSHG", "name": "上证全指", "market": "CN_INDEX", "aliases": "上证全指数"},
    {"symbol": "000300.XSHG", "name": "沪深300", "market": "CN_INDEX", "aliases": "沪深三百 csi300 csi 300"},
    {"symbol": "000688.XSHG", "name": "科创50", "market": "CN_INDEX", "aliases": "科创五十 star 50"},
    {"symbol": "000903.XSHG", "name": "中证A100", "market": "CN_INDEX", "aliases": "中证a100 csi a100"},
    {"symbol": "000905.XSHG", "name": "中证500", "market": "CN_INDEX", "aliases": "中证五百 csi500 csi 500"},
    {"symbol": "000906.XSHG", "name": "中证800", "market": "CN_INDEX", "aliases": "中证八百 csi800 csi 800"},
    {"symbol": "000852.XSHG", "name": "中证1000", "market": "CN_INDEX", "aliases": "中证一千 csi1000 csi 1000"},
    {"symbol": "000985.XSHG", "name": "中证全指", "market": "CN_INDEX", "aliases": "中证全指数 csi all share"},
    {"symbol": "399001.XSHE", "name": "深证成指", "market": "CN_INDEX", "aliases": "深指 深成指 shenzhen component"},
    {"symbol": "399005.XSHE", "name": "中小100", "market": "CN_INDEX", "aliases": "中小板100"},
    {"symbol": "399006.XSHE", "name": "创业板指", "market": "CN_INDEX", "aliases": "创业板指数 chinext"},
    {"symbol": "399303.XSHE", "name": "国证2000", "market": "CN_INDEX", "aliases": "国证两千 cn2000"},
    {"symbol": "399310.XSHE", "name": "国证A50", "market": "CN_INDEX", "aliases": "国证a50 cn a50"},
    {"symbol": "899050.BJSE", "name": "北证50", "market": "CN_INDEX", "aliases": "北证五十 beijing 50"},
)
CN_BROAD_INDEX_BY_SYMBOL = {item["symbol"]: item for item in CN_BROAD_INDEXES}

_SYMBOL_DIRECTORY_SEED = (
    *({key: value for key, value in item.items() if key != "aliases"} for item in CN_BROAD_INDEXES),
    {"symbol": "100.HSI", "name": "恒生指数", "market": "HK_INDEX"},
    {"symbol": "00700.HK", "name": "腾讯控股", "market": "HK"},
    {"symbol": "09988.HK", "name": "阿里巴巴-W", "market": "HK"},
    {"symbol": "AAPL.US", "name": "Apple", "market": "US"},
    {"symbol": "MSFT.US", "name": "Microsoft", "market": "US"},
    {"symbol": "NVDA.US", "name": "NVIDIA", "market": "US"},
    {"symbol": "AMD.US", "name": "超威半导体", "market": "US"},
)
_BUILTIN_SEARCH_ALIASES = {
    **{item["symbol"]: item["aliases"] for item in CN_BROAD_INDEXES},
    "100.HSI": "恒指 hang seng hsi",
    "00700.HK": "腾讯 tencent",
    "09988.HK": "阿里 阿里巴巴 alibaba baba",
    "AAPL.US": "苹果 apple",
    "MSFT.US": "微软 microsoft",
    "NVDA.US": "英伟达 英伟达公司 nvidia",
    "AMD.US": "超威半导体 超微半导体 amd advanced micro devices",
}


def _ftshare_src_candidates() -> list[Path]:
    custom = (os.environ.get("FTSHARE_SDK_SRC") or "").strip()
    if not custom:
        return []
    source = Path(custom).expanduser()
    return [source, source / "src"]


def _path_makes_ftshare_importable(path: Path) -> bool:
    """True if putting ``path`` on sys.path would expose package ftshare."""
    return (path / "ftshare" / "__init__.py").is_file() or (path / "ftshare").is_dir()


def _maybe_inject_local_ftshare() -> str | None:
    """Try to make ``import ftshare`` work. Returns injected path or None."""
    try:
        import ftshare  # noqa: F401

        return None
    except Exception:
        pass

    for src in _ftshare_src_candidates():
        if not src.exists():
            continue
        # Prefer …/src that contains ftshare/; also accept path that *is* the package parent.
        inject: Path | None = None
        if _path_makes_ftshare_importable(src):
            inject = src
        elif src.name == "ftshare" and _path_makes_ftshare_importable(src.parent):
            inject = src.parent
        if inject is None:
            continue
        s = str(inject.resolve())
        if s not in sys.path:
            sys.path.insert(0, s)
        try:
            import ftshare  # noqa: F401

            return s
        except Exception:
            try:
                sys.path.remove(s)
            except ValueError:
                pass
            continue
    return None


_INJECTED_FTSHARE_PATH = _maybe_inject_local_ftshare()


def ftshare_available() -> bool:
    try:
        import ftshare  # noqa: F401

        return True
    except Exception:
        _maybe_inject_local_ftshare()
        try:
            import ftshare  # noqa: F401

            return True
        except Exception:
            return False


def ftshare_status() -> dict[str, Any]:
    """Debug helper for hosts / ops."""
    ok = ftshare_available()
    info: dict[str, Any] = {
        "available": ok,
        "python": sys.executable,
        "injected_path": _INJECTED_FTSHARE_PATH,
    }
    if ok:
        try:
            import ftshare

            info["module_file"] = getattr(ftshare, "__file__", None)
            try:
                info["distribution_version"] = distribution_version("ftshare")
            except PackageNotFoundError:
                info["distribution_version"] = None
        except Exception as exc:  # noqa: BLE001
            info["import_error"] = str(exc)
    return info


def _interval_to_sdk(unit: str) -> str:
    u = (unit or "day").strip().lower()
    return {
        "minute": "Minute",
        "day": "Day",
        "week": "Week",
        "month": "Month",
        # FTShare exposes Month and Year, but not a native quarter enum.
        # Quarter bars are aggregated from monthly candles below.
        "quarter": "Month",
        "year": "Year",
    }.get(u, "Day")


def _adjust_to_sdk(adjust: str) -> str:
    a = (adjust or "none").strip().lower()
    if a in ("", "none", "null", "raw"):
        return "none"
    if a in ("forward", "qfq", "pre"):
        return "forward"
    if a in ("backward", "hfq", "post"):
        return "backward"
    return "none"


def _normalize_raw(raw: Any) -> list[dict[str, Any]]:
    """Single ingest path shared with calc/draw (close-time bar, seconds)."""
    from core.rows import normalize_rows

    # Some FTShare POST endpoints return the decoded service envelope even
    # with ``as_dataframe=False``; GET endpoints commonly return the extracted
    # list. Keep the SDK-specific envelope handling at this adapter boundary.
    payload: Any = raw
    if isinstance(raw, Mapping):
        data = raw.get("data")
        if isinstance(data, list):
            payload = data
        elif isinstance(data, Mapping):
            for key in ("items", "records", "results", "data"):
                if isinstance(data.get(key), list):
                    payload = data[key]
                    break
    return normalize_rows(payload)


_CN_SYMBOL_SUFFIXES = {
    "SH": "XSHG",
    "XSHG": "XSHG",
    "SZ": "XSHE",
    "XSHE": "XSHE",
    "BJ": "BJSE",
    "BJSE": "BJSE",
}


def _canonical_market_symbol(symbol: str) -> str:
    """Normalize explicit mainland exchange suffixes without guessing a market.

    A bare six-digit code is intentionally left bare: for example ``000688``
    can mean the 科创50 index or 国城矿业. Only an explicit exchange-qualified
    identifier is safe to route to an index endpoint or an equity endpoint.
    """
    raw = str(symbol or "").strip().upper()
    code, separator, suffix = raw.rpartition(".")
    if separator and code and suffix in _CN_SYMBOL_SUFFIXES:
        return f"{code}.{_CN_SYMBOL_SUFFIXES[suffix]}"
    return raw


def _broad_index_for_symbol(symbol: str) -> Mapping[str, str] | None:
    return CN_BROAD_INDEX_BY_SYMBOL.get(_canonical_market_symbol(symbol))


def _ambiguous_broad_index_result(symbol: str) -> dict[str, Any] | None:
    """Require an exchange suffix where a bare code can select a broad index."""
    raw = str(symbol or "").strip().upper()
    if "." in raw or len(raw) != 6 or not raw.isdigit():
        return None
    matches = [item for item in CN_BROAD_INDEXES if item["symbol"].split(".", 1)[0] == raw]
    if not matches:
        return None
    index = matches[0]
    return {
        "ok": False,
        "error": "ambiguous_symbol",
        "error_code": "ambiguous_symbol",
        "message": (
            f"{raw} is ambiguous: it can identify the {index['name']} broad index "
            "or an exchange-listed stock. Use a full exchange-qualified symbol."
        ),
        "symbol": raw,
        "index_candidate": {"symbol": index["symbol"], "name": index["name"], "market": "CN_INDEX"},
        "next_action": "Use the canonical index symbol, or provide the stock's explicit .SH/.SZ/.BJ suffix.",
        "retryable": False,
    }


def _index_candles_provider_unavailable_result(symbol: str) -> dict[str, Any]:
    """Fail closed rather than silently returning a same-code A-share stock."""
    index = _broad_index_for_symbol(symbol)
    assert index is not None
    canonical_symbol = str(index["symbol"])
    return {
        "ok": False,
        "error": "index_candles_provider_unavailable",
        "error_code": "index_candles_provider_unavailable",
        "message": (
            "The installed FTShare SDK exposes this A-share index identity but not a verified "
            "A-share index K-line history endpoint. No stock fallback was used, so a same-code "
            "equity cannot be mislabeled as the index."
        ),
        "symbol": canonical_symbol,
        "name": str(index["name"]),
        "asset_type": "CN_INDEX",
        "source": "ftshare",
        "next_action": "Pass verified index OHLCV rows from a provider that supports this index into draw_kline.",
        "retryable": False,
    }


def _exchange_timezone(symbol: str) -> str:
    """Return the IANA trading timezone used for calendar aggregation."""
    normalized = str(symbol or "").strip().upper()
    if normalized.endswith((".HK", ".HKG")) or normalized.startswith("100.HSI"):
        return "Asia/Hong_Kong"
    if _is_us_symbol(normalized) or normalized.startswith("100.NDX"):
        return "America/New_York"
    return "Asia/Shanghai"


def _aggregate_quarters(rows: list[dict[str, Any]], *, timezone_name: str = "Asia/Shanghai") -> list[dict[str, Any]]:
    """Aggregate normalized month candles into chronological calendar quarters."""
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        timestamp = int(row["time"])
        date = datetime.fromtimestamp(timestamp, tz=ZoneInfo(timezone_name))
        key = (date.year, (date.month - 1) // 3 + 1)
        grouped.setdefault(key, []).append(row)

    quarters: list[dict[str, Any]] = []
    for key in sorted(grouped):
        bucket = sorted(grouped[key], key=lambda item: int(item["time"]))
        quarters.append(
            {
                "time": int(bucket[-1]["time"]),
                "open": float(bucket[0]["open"]),
                "high": max(float(item["high"]) for item in bucket),
                "low": min(float(item["low"]) for item in bucket),
                "close": float(bucket[-1]["close"]),
                "volume": sum(float(item.get("volume") or 0) for item in bucket),
            }
        )
    return quarters


def _is_us_symbol(symbol: str) -> bool:
    normalized = str(symbol or "").strip().upper()
    return normalized.endswith((".US", ".NASDAQ", ".NYSE"))


def _is_hk_symbol(symbol: str) -> bool:
    normalized = str(symbol or "").strip().upper()
    return normalized.endswith((".HK", ".HKG"))


def _bare_us_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().split(".")[0]


def _aggregate_interval(
    rows: list[dict[str, Any]], interval: str, *, timezone_name: str = "America/New_York"
) -> list[dict[str, Any]]:
    """Aggregate normalized daily rows for a source with daily-only history."""
    normalized = str(interval or "day").strip().lower()
    if normalized == "day":
        return list(rows)
    grouped: dict[tuple[int, ...], list[dict[str, Any]]] = {}
    for row in rows:
        date = datetime.fromtimestamp(int(row["time"]), tz=ZoneInfo(timezone_name))
        if normalized == "week":
            iso = date.isocalendar()
            key = (iso.year, iso.week)
        elif normalized == "month":
            key = (date.year, date.month)
        elif normalized == "quarter":
            key = (date.year, (date.month - 1) // 3 + 1)
        else:
            key = (date.year,)
        grouped.setdefault(key, []).append(row)
    aggregated: list[dict[str, Any]] = []
    for key in sorted(grouped):
        bucket = sorted(grouped[key], key=lambda item: int(item["time"]))
        aggregated.append(
            {
                "time": int(bucket[-1]["time"]),
                "open": float(bucket[0]["open"]),
                "high": max(float(item["high"]) for item in bucket),
                "low": min(float(item["low"]) for item in bucket),
                "close": float(bucket[-1]["close"]),
                "volume": sum(float(item.get("volume") or 0.0) for item in bucket),
            }
        )
    return aggregated


def _fetch_us_daily_candles(market: Any, symbol: str, limit: int) -> Any:
    """Use FTShare's dedicated US history endpoint instead of stock_candlesticks.

    The generic endpoint is optimized for mainland symbols and can return an
    incomplete US slice.  The dedicated endpoint only permits a three-day
    start/end span, so requesting a long calendar range silently produces an
    empty slice.  Page through the endpoint without date filters, then trim
    after normalization so callers keep the same ``limit`` contract.
    """
    return market.eastmoney_us_stock_daily_ohlc(
        stock_code=_bare_us_symbol(symbol),
        all_pages=True,
        page_size=200,
        as_dataframe=False,
    )


def _fetch_hk_candles(market: Any, symbol: str, interval: str, limit: int, adjust: str) -> Any:
    """Use FTShare's dedicated HK history endpoint when it supports the period."""
    method = getattr(market, "hk_candlesticks", None)
    if not callable(method):
        raise AttributeError("FTShare hk_candlesticks is unavailable")
    normalized = str(interval or "day").strip().lower()
    if normalized not in {"day", "month", "quarter", "year"}:
        raise ValueError(f"HK endpoint does not support {normalized}")
    today = datetime.now(ZoneInfo("Asia/Hong_Kong")).date()
    days_per_bar = {"day": 1.5, "month": 32, "quarter": 92, "year": 370}[normalized]
    lookback_days = max(30, int(int(limit) * days_per_bar))
    adjustment = _adjust_to_sdk(adjust) or "none"
    raw = method(
        trade_code=symbol,
        interval_unit=normalized,
        since_date=(today - timedelta(days=lookback_days)).isoformat(),
        until_date=today.isoformat(),
        interval_value=1,
        limit=max(2, int(limit)),
        adjust_kind=adjustment,
        as_dataframe=False,
    )
    # The current FTShare HK endpoint can return a successful but stale archive
    # response (for example, 2010 bars for a live request). Treat that as an
    # upstream failure so the view never labels unrelated stale data as current.
    rows = _normalize_raw(raw)
    if len(rows) < 2:
        raise RuntimeError("FTShare HK history returned fewer than two valid candles")
    latest = datetime.fromtimestamp(int(rows[-1]["time"]), tz=ZoneInfo("Asia/Hong_Kong")).date()
    if latest < datetime.now(ZoneInfo("Asia/Hong_Kong")).date() - timedelta(days=45):
        raise RuntimeError(f"FTShare HK history is stale (latest bar: {latest.isoformat()})")
    return raw


def _until_ms() -> int:
    # Stable-ish now; callers can still pass their own window via limit.
    return int(time.time() * 1000)


def _history_since_ms(limit: int, interval: str) -> int:
    """Return a conservative single-page start within FTShare's 12-month cap."""
    normalized = str(interval or "day").strip().lower()
    days_per_bar = {
        "day": 3,
        "week": 10,
        "month": 32,
        "quarter": 92,
        "year": 370,
    }.get(normalized, 3)
    lookback_days = min(360, max(2, int(limit or 220) * days_per_bar))
    return max(_until_ms() - lookback_days * 86_400_000, 0)


def _fetch_generic_history(
    market: Any,
    *,
    symbol: str,
    interval: str,
    interval_unit: str,
    interval_value: int,
    adjust_kind: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Page daily-or-larger history without exceeding FTShare's 12-month window."""
    normalized = str(interval or "day").strip().lower()
    requested = max(2, int(limit or 220))
    # Quarter candles are assembled from monthly rows, so collect three times
    # the requested output count before aggregation.
    target_rows = min(12_000, requested * 3 if normalized == "quarter" else requested)
    days_per_bar = {
        "day": 3,
        "week": 10,
        "month": 32,
        "quarter": 32,
        "year": 360,
    }.get(normalized, 3)
    window_days = min(360, max(30, requested * days_per_bar))
    estimated_rows_per_page = max(1, window_days // max(1, days_per_bar))
    max_pages = min(32, max(1, (target_rows + estimated_rows_per_page - 1) // estimated_rows_per_page + 1))
    page_limit = min(4000, max(2, target_rows))
    until_ms = _until_ms()
    rows_by_time: dict[int, dict[str, Any]] = {}

    for _page in range(max_pages):
        since_ms = max(0, until_ms - window_days * 86_400_000)
        raw = market.stock_candlesticks(
            symbol=symbol,
            interval_unit=interval_unit,
            interval_value=interval_value,
            adjust_kind=adjust_kind,
            since_ts_millis=since_ms,
            until_ts_millis=until_ms,
            limit=page_limit,
            as_dataframe=False,
        )
        chunk = _normalize_raw(raw)
        if not chunk:
            break
        previous_count = len(rows_by_time)
        for row in chunk:
            rows_by_time[int(row["time"])] = row
        if len(rows_by_time) >= target_rows:
            break
        minimum_full_page = max(2, min(target_rows, estimated_rows_per_page) * 3 // 4)
        if len(chunk) < minimum_full_page:
            break
        earliest_ms = min(int(row["time"]) for row in chunk) * 1000
        next_until_ms = earliest_ms - 1
        if len(rows_by_time) == previous_count or next_until_ms <= 0 or next_until_ms >= until_ms:
            break
        until_ms = next_until_ms

    return [rows_by_time[key] for key in sorted(rows_by_time)]


def _symbol_name(market: Any, symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    # Codes such as 000001 are ambiguous in vendor search (it can resolve to
    # 平安银行). The candle request has already selected the index endpoint, so
    # retain the canonical index identity instead of relabeling its chart.
    if normalized in COMPARISON_INDEX_NAMES:
        return COMPARISON_INDEX_NAMES[normalized]
    for item in _SYMBOL_DIRECTORY_SEED:
        if normalized == str(item["symbol"]).upper():
            return str(item["name"])
    try:
        code = str(symbol or "").split(".")[0]
        rows = market.search(query=code, limit=8, as_dataframe=False)
        fallback: str | None = None
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            name: str | None = None
            for key in ("name", "stock_name", "security_name", "index_name", "symbol_name"):
                if row.get(key):
                    name = str(row[key]).strip()
                    break
            if not name or name.upper() in {normalized, code.upper()}:
                continue
            row_symbol = _canonical_market_symbol(
                _canonical_directory_symbol(
                    row.get("symbol")
                    or row.get("symbol_id")
                    or row.get("stock_code")
                    or row.get("index_code")
                    or row.get("ticker")
                    or row.get("code"),
                    market=row.get("market") or row.get("board"),
                )
            )
            if row_symbol == normalized:
                return name
            fallback = fallback or name
        if fallback:
            return fallback
    except Exception:
        pass
    try:
        cached = _read_symbol_directory_cache()
        for item in list(cached.get("items") or []) if isinstance(cached, Mapping) else []:
            if not isinstance(item, Mapping):
                continue
            candidate_symbol = _canonical_market_symbol(
                _canonical_directory_symbol(
                    item.get("symbol") or item.get("code") or item.get("stock_code"),
                    market=item.get("market") or item.get("board"),
                )
            )
            candidate_name = str(item.get("name") or item.get("stock_name") or "").strip()
            if candidate_symbol == normalized and candidate_name and candidate_name.upper() not in {normalized, code.upper()}:
                return candidate_name
    except Exception:
        pass
    return symbol


def _ftshare_unavailable_result() -> dict[str, Any]:
    """Return one consistent optional-dependency error for data tools."""
    st = ftshare_status()
    return {
        "ok": False,
        "error": "ftshare_not_installed",
        "message": (
            "ftshare is not importable in this MCP process. "
            f"python={st.get('python')}. "
            "Install the FTShare SDK using the same interpreter that starts this MCP, "
            "or pass rows from FTShare-MCP / another data source into draw_kline."
        ),
        "python": st.get("python"),
        "hint_candidates": [str(p) for p in _ftshare_src_candidates()[:8]],
    }


def _candle_cache_key(
    symbol: str, interval: str, interval_value: int, session_count: int, limit: int, adjust: str
) -> tuple[str, str, int, int, int, str]:
    return (
        str(symbol).strip().upper(),
        str(interval).strip().lower(),
        int(interval_value),
        int(session_count),
        int(limit),
        str(adjust).strip().lower(),
    )


def _cache_candles(key: tuple[str, str, int, int, int, str], payload: dict[str, Any]) -> None:
    if payload.get("ok") and isinstance(payload.get("rows"), list) and len(payload["rows"]) >= 2:
        _candle_cache[key] = (time.time(), deepcopy(payload))


def _compatible_candle_cache_entry(
    key: tuple[str, str, int, int, int, str],
) -> tuple[tuple[str, str, int, int, int, str], tuple[float, dict[str, Any]]] | None:
    """Return the exact or smallest compatible larger candle response."""
    cached = _candle_cache.get(key)
    if cached:
        return key, cached

    # A larger daily response contains all history needed by a smaller view.
    # Limit is intentionally the only relaxed part of the cache key: mixing
    # different intervals, sessions, or adjustments would change the series.
    compatible = [
        (candidate_key, candidate)
        for candidate_key, candidate in _candle_cache.items()
        if candidate_key[:4] == key[:4]
        and candidate_key[5] == key[5]
        and candidate_key[4] >= key[4]
    ]
    if not compatible:
        return None
    return min(compatible, key=lambda item: (item[0][4] - key[4], -item[1][0]))


def _recent_candle_cache(key: tuple[str, str, int, int, int, str]) -> dict[str, Any] | None:
    """Return a compatible provider result only while it is still hot."""
    match = _compatible_candle_cache_entry(key)
    if match is None:
        return None
    source_key, (cached_at, payload) = match
    age = max(0, int(time.time() - cached_at))
    if age > _CANDLE_CACHE_FRESH_SECONDS:
        return None
    fresh = deepcopy(payload)
    fresh.update(
        {
            "ok": True,
            "cached": True,
            "cache_age_seconds": age,
            "freshness": "recent_memory_cache",
            "message": "Using candles fetched moments ago from the in-memory cache.",
        }
    )
    if source_key != key:
        fresh["cache_source_limit"] = source_key[4]
    return fresh


def _cached_candle_fallback(
    key: tuple[str, str, int, int, int, str], error: Exception | str
) -> dict[str, Any] | None:
    match = _compatible_candle_cache_entry(key)
    if match is None:
        return None
    source_key, (cached_at, payload) = match
    age = max(0, int(time.time() - cached_at))
    if age > _CANDLE_CACHE_TTL_SECONDS:
        _candle_cache.pop(source_key, None)
        return None
    fallback = deepcopy(payload)
    fallback.update(
        {
            "ok": True,
            "status": "stale",
            "cached": True,
            "cache_age_seconds": age,
            "freshness": "recent_cached_fallback",
            "message": "FTShare is temporarily unavailable; showing the most recent cached candles.",
            "upstream_error": str(error)[:500],
        }
    )
    if source_key != key:
        fallback["cache_source_limit"] = source_key[4]
    return fallback


def _symbol_directory_cache_path() -> Path:
    configured = (os.environ.get("DSH_KLINE_CACHE_DIR") or "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".cache" / "dsh_kline"
    return root / f"symbol-directory-v{SYMBOL_DIRECTORY_VERSION}.json"


def _read_symbol_directory_cache() -> dict[str, Any] | None:
    path = _symbol_directory_cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("version") != SYMBOL_DIRECTORY_VERSION:
        return None
    if not isinstance(payload.get("items"), list):
        return None
    return payload


def _write_symbol_directory_cache(payload: dict[str, Any]) -> None:
    path = _symbol_directory_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        # A read-only runtime may still serve the fetched directory to this app session.
        return


def _rows_from_directory_response(raw: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, Mapping)]
    if isinstance(raw, Mapping):
        for key in ("items", "data", "results", "rows", "list"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    return []


def _canonical_directory_symbol(symbol: Any, *, market: Any = None, default_market: str = "") -> str:
    """Normalize vendor directory identifiers to the symbols accepted by candles."""
    value = str(symbol or "").strip()
    if not value:
        return ""
    market_text = str(market or "").strip().upper()
    default_text = str(default_market or "").strip().upper()
    # Eastmoney's U.S. directory uses secid=105.AAPL and market=105. The
    # candle endpoint expects AAPL.US (or another documented U.S. suffix).
    if default_text == "US" or market_text == "105" or value.upper().startswith("105."):
        code = value.split(".", 1)[1] if "." in value else value
        return f"{code.upper()}.US"
    return value


def _directory_items(rows: Any, default_market: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for row in _rows_from_directory_response(rows):
        symbol = next(
            (
                row.get(key)
                for key in ("symbol", "symbol_id", "stock_code", "code", "secid", "index_code", "ticker")
                if row.get(key) not in (None, "")
            ),
            None,
        )
        name = next(
            (
                row.get(key)
                for key in ("name", "stock_name", "security_name", "index_name", "symbol_name")
                if row.get(key) not in (None, "")
            ),
            None,
        )
        if symbol is None or name is None:
            continue
        market = row.get("market") or row.get("board") or default_market
        normalized_market = "US" if str(market).strip().upper() == "105" else str(market).strip()
        normalized_symbol = _canonical_directory_symbol(symbol, market=market, default_market=default_market)
        items.append({"symbol": normalized_symbol, "name": str(name).strip(), "market": normalized_market})
    return [item for item in items if item["symbol"] and item["name"]]


def _merge_symbol_directory(*groups: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    merged: list[dict[str, str]] = []
    for group in groups:
        for item in group:
            symbol = str(item.get("symbol") or "").strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            merged.append({
                "symbol": symbol,
                "name": str(item.get("name") or symbol).strip(),
                "market": str(item.get("market") or "OTHER").strip(),
            })
    return sorted(merged, key=lambda item: (item["market"], item["symbol"]))


def _directory_coverage(
    items: list[dict[str, str]],
    *,
    complete_markets: set[str] | None = None,
    partial_markets: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Expose coverage claims separately from cached search candidates."""
    complete = complete_markets or set()
    partial = partial_markets or set()
    counts: dict[str, int] = {}
    for item in items:
        market = str(item.get("market") or "OTHER")
        counts[market] = counts.get(market, 0) + 1
    markets = set(counts) | complete | partial
    return {
        market: {
            "count": counts.get(market, 0),
            "complete": market in complete,
            "status": "complete" if market in complete else "partial",
        }
        for market in sorted(markets)
    }


def register_symbol_directory(
    items: Any,
    *,
    source: str,
    source_version: str | None = None,
    complete_markets: list[str] | None = None,
    ttl_seconds: int = SYMBOL_DIRECTORY_TTL_SECONDS,
) -> dict[str, Any]:
    """Persist a directory supplied by a host or another MCP data provider.

    This server intentionally does not invoke peer MCP servers itself. The host
    fetches its preferred directory and registers it here; the MCP App then
    searches the local snapshot without another vendor round trip.
    """
    provider = str(source or "").strip()
    if not provider:
        return {"ok": False, "error": "invalid_source", "message": "source is required"}
    normalized = _merge_symbol_directory(_directory_items(items, "OTHER"))
    if not normalized:
        return {
            "ok": False,
            "error": "invalid_directory",
            "message": "items must include at least one symbol/code and name entry",
        }
    if len(normalized) > SYMBOL_DIRECTORY_MAX_ITEMS:
        return {
            "ok": False,
            "error": "directory_too_large",
            "message": f"directory exceeds {SYMBOL_DIRECTORY_MAX_ITEMS} items",
            "count": len(normalized),
        }

    now = int(time.time())
    ttl = max(300, min(int(ttl_seconds or SYMBOL_DIRECTORY_TTL_SECONDS), 7 * 24 * 60 * 60))
    claimed_complete = {str(value).strip() for value in (complete_markets or []) if str(value).strip()}
    payload = {
        "ok": True,
        "version": SYMBOL_DIRECTORY_VERSION,
        "generated_at": now,
        "expires_at": now + ttl,
        "items": normalized,
        "count": len(normalized),
        "source": "external",
        "provider_mode": "external",
        "provider_id": provider[:120],
        "source_version": str(source_version or "")[:120],
        "coverage": _directory_coverage(normalized, complete_markets=claimed_complete),
        "stale": False,
        "refreshed": True,
        "needs_external_refresh": False,
    }
    _write_symbol_directory_cache(payload)
    return payload


def symbol_directory(*, force_refresh: bool = False) -> dict[str, Any]:
    """Load a versioned local symbol directory and refresh it from FTShare when stale.

    The chart app stores this compact name/code directory in localStorage. It is
    deliberately separate from quotes: price and status still come from FTShare.
    """
    now = int(time.time())
    cached = _read_symbol_directory_cache()
    cached_expires = int(cached.get("expires_at") or 0) if cached else 0
    if cached and not force_refresh and cached_expires > now:
        return {**cached, "ok": True, "stale": False, "refreshed": False}

    # An external directory is host-owned. Keep it searchable when it expires;
    # only the provider that created it can authoritatively refresh it.
    if cached and cached.get("provider_mode") == "external":
        return {
            **cached,
            "ok": True,
            "stale": True,
            "refreshed": False,
            "needs_external_refresh": True,
            "message": "External directory has expired; ask the host to refresh and register a new snapshot.",
        }

    seed = [dict(item) for item in _SYMBOL_DIRECTORY_SEED]
    if not ftshare_available():
        items = _merge_symbol_directory(list(cached.get("items") or []) if cached else [], seed)
        return {
            "ok": True,
            "version": SYMBOL_DIRECTORY_VERSION,
            "generated_at": int(cached.get("generated_at") or now) if cached else now,
            "expires_at": now + SYMBOL_DIRECTORY_RETRY_SECONDS,
            "items": items,
            "count": len(items),
            "source": "cache" if cached else "seed",
            "provider_mode": "builtin" if cached else "seed",
            "provider_id": "FTShare SDK" if cached else "seed",
            "coverage": _directory_coverage(items, partial_markets={item["market"] for item in seed}),
            "stale": True,
            "refreshed": False,
            "needs_external_refresh": False,
            "message": "FTShare unavailable; using the last local symbol directory.",
        }

    import ftshare as ft

    market = ft.market_api(timeout=20)
    source_specs = (
        ("stock_list", "CN", {}, True),
        ("index_description_all", "CN_INDEX", {}, True),
        # The installed FTShare endpoint caps a single page at 200. The SDK
        # paginates when ``all_pages`` is set, so 200 retains complete coverage
        # instead of raising its client-side page-size validation error.
        ("eastmoney_us_stock_list", "US", {"all_pages": True, "page_size": 200}, True),
    )
    fetched_groups: list[list[dict[str, str]]] = []
    errors: list[str] = []
    completed_markets: set[str] = set()
    for method_name, default_market, kwargs, is_complete in source_specs:
        method = getattr(market, method_name, None)
        if not callable(method):
            errors.append(f"{method_name}: unavailable in installed FTShare client")
            continue
        try:
            group = _directory_items(method(as_dataframe=False, **kwargs), default_market)
            if group and is_complete:
                completed_markets.add(default_market)
            fetched_groups.append(group)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{method_name}: {exc}")

    fetched_count = sum(len(group) for group in fetched_groups)
    if fetched_count:
        items = _merge_symbol_directory(*fetched_groups, seed)
        payload = {
            "ok": True,
            "version": SYMBOL_DIRECTORY_VERSION,
            "generated_at": now,
            "expires_at": now + SYMBOL_DIRECTORY_TTL_SECONDS,
            "items": items,
            "source": "ftshare",
            "provider_mode": "builtin",
            "provider_id": "FTShare SDK",
            "coverage": _directory_coverage(
                items,
                complete_markets=completed_markets,
                partial_markets={item["market"] for item in seed} - completed_markets,
            ),
            "stale": False,
            "refreshed": True,
            "needs_external_refresh": False,
        }
        payload["count"] = len(payload["items"])
        if errors:
            payload["warnings"] = errors
        _write_symbol_directory_cache(payload)
        return payload

    items = _merge_symbol_directory(list(cached.get("items") or []) if cached else [], seed)
    fallback = {
        "ok": True,
        "version": SYMBOL_DIRECTORY_VERSION,
        "generated_at": int(cached.get("generated_at") or now) if cached else now,
        "expires_at": now + SYMBOL_DIRECTORY_RETRY_SECONDS,
        "items": items,
        "count": len(items),
        "source": "cache" if cached else "seed",
        "provider_mode": "builtin" if cached else "seed",
        "provider_id": "FTShare SDK" if cached else "seed",
        "coverage": _directory_coverage(items, partial_markets={item["market"] for item in seed}),
        "stale": True,
        "refreshed": False,
        "needs_external_refresh": False,
        "message": "FTShare directory refresh failed; using the last local symbol directory.",
    }
    if errors:
        fallback["refresh_errors"] = errors[:3]
    _write_symbol_directory_cache(fallback)
    return fallback


def search_symbols(query: str, *, limit: int = 8) -> dict[str, Any]:
    """Search FTShare securities for the chart workspace symbol picker."""
    q = str(query or "").strip()
    if not q:
        return {"ok": False, "error": "invalid_query", "message": "query is required"}
    lim = max(1, min(int(limit or 8), 20))
    cache_key = (q.casefold(), lim)
    now = time.monotonic()
    cached = _symbol_search_cache.get(cache_key)
    if cached and now - cached[0] < _SYMBOL_SEARCH_CACHE_TTL_SECONDS:
        # Return a shallow copy so a caller cannot mutate the shared cache.
        return {**cached[1], "results": list(cached[1].get("results") or [])}

    query_text = "".join(q.casefold().split())
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: Mapping[str, Any]) -> None:
        market = item.get("market") or item.get("board")
        symbol = _canonical_market_symbol(
            _canonical_directory_symbol(
                item.get("symbol")
                or item.get("symbol_id")
                or item.get("secid")
                or item.get("stock_code")
                or item.get("index_code")
                or item.get("ticker")
                or item.get("code"),
                market=market,
                default_market="US" if str(market or "").strip() == "105" else "",
            )
        )
        if not symbol:
            return
        name = next(
            (
                item.get(key)
                for key in ("name", "stock_name", "security_name", "index_name", "symbol_name")
                if item.get(key)
            ),
            symbol,
        )
        if symbol in seen:
            for result in results:
                if result["symbol"] == symbol and result["name"] == symbol and str(name) != symbol:
                    result["name"] = str(name)
                    break
            return
        if len(results) >= lim:
            return
        seen.add(symbol)
        result: dict[str, Any] = {"symbol": symbol, "name": str(name)}
        for key in ("board", "close", "change", "change_rate", "market"):
            if item.get(key) is not None:
                result[key] = "US" if key == "market" and str(item[key]).strip() == "105" else item[key]
        results.append(result)

    # Always keep essential indices and common U.S./HK names discoverable even
    # when a vendor directory is partial or a multilingual vendor search misses
    # an alias such as "英伟达".
    for item in _SYMBOL_DIRECTORY_SEED:
        searchable = "".join(
            f"{item['symbol']} {item['name']} {_BUILTIN_SEARCH_ALIASES.get(item['symbol'], '')}".casefold().split()
        )
        if query_text and query_text in searchable:
            add(item)

    source = "builtin"
    warning = None
    if ftshare_available():
        import ftshare as ft

        market = ft.market_api(timeout=20)
        try:
            raw = market.search(query=q, limit=lim, as_dataframe=False)
            for row in raw if isinstance(raw, list) else []:
                if isinstance(row, Mapping):
                    add(row)
            source = "ftshare+builtin"
        except Exception as exc:  # noqa: BLE001
            warning = f"ftshare search failed: {exc}"
    else:
        warning = "FTShare unavailable; showing built-in symbol matches only."

    payload = {"ok": True, "query": q, "count": len(results), "results": results, "source": source}
    if warning:
        payload["warning"] = warning
    _symbol_search_cache[cache_key] = (now, payload)
    if len(_symbol_search_cache) > _SYMBOL_SEARCH_CACHE_MAX_ENTRIES:
        oldest_key = min(_symbol_search_cache, key=lambda key: _symbol_search_cache[key][0])
        _symbol_search_cache.pop(oldest_key, None)
    return {**payload, "results": list(results)}


MARKET_TICKER_SOURCES = (
    {"market": "HK", "name": "恒生指数", "symbol": "100.HSI", "kind": "global", "timezone": "Asia/Hong_Kong", "open": "09:30", "close": "16:00"},
    {"market": "US", "name": "纳斯达克", "symbol": "100.NDX", "kind": "global", "timezone": "America/New_York", "open": "09:30", "close": "16:00"},
)
# Kept as a public compatibility name for integrations that read this mapping.
COMPARISON_INDEX_NAMES = {item["symbol"]: item["name"] for item in CN_BROAD_INDEXES}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _ticker_timestamp(row: Mapping[str, Any]) -> float:
    raw = row.get("ts_millis") or row.get("time") or row.get("timestamp")
    number = _number(raw)
    if number is not None:
        return number
    date = str(row.get("trade_date") or row.get("date") or "")
    try:
        return datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _ticker_item(source: Mapping[str, str], raw: Any) -> dict[str, Any] | None:
    rows = [row for row in raw if isinstance(row, Mapping)] if isinstance(raw, list) else []
    if not rows:
        return None
    rows.sort(key=_ticker_timestamp)
    latest = rows[-1]
    close = _number(latest.get("close"))
    if close is None:
        return None
    previous = _number(rows[-2].get("close")) if len(rows) > 1 else None
    change = _number(latest.get("change_amount"))
    change_pct = _number(latest.get("change_pct"))
    if previous not in (None, 0):
        change = close - previous
        change_pct = change / previous * 100
    if change is None or change_pct is None:
        return None
    timestamp = _ticker_timestamp(latest)
    return {
        "market": source["market"],
        "symbol": source["symbol"],
        "name": str(latest.get("name") or source["name"]),
        "close": close,
        "change": change,
        "change_pct": change_pct,
        "time": int(timestamp / 1000) if timestamp > 10_000_000_000 else int(timestamp),
    }


def _market_status(source: Mapping[str, str], now: datetime) -> str:
    """Return the intentionally conservative delayed/closed label for a feed.

    FTShare's compact index endpoints are daily snapshots, so we never label
    them as real-time. During a local market session the snapshot is useful but
    delayed; outside it the display is explicitly marked as closed.
    """
    try:
        local_now = now.astimezone(ZoneInfo(source["timezone"]))
        if local_now.weekday() >= 5:
            return "closed"
        open_at = clock_time.fromisoformat(source["open"])
        close_at = clock_time.fromisoformat(source["close"])
        return "delayed" if open_at <= local_now.time() <= close_at else "closed"
    except (KeyError, ValueError):
        return "delayed"


def _symbol_market_status(symbol: str, now: datetime | None = None) -> str:
    """Return the market-session state for a symbol without claiming real-time data."""
    normalized = str(symbol or "").upper()
    if normalized.endswith((".HK", ".HKG")) or normalized.startswith("100.HSI"):
        source = {"timezone": "Asia/Hong_Kong", "open": "09:30", "close": "16:00"}
    elif normalized.endswith((".US", ".NASDAQ", ".NYSE")) or normalized.startswith("100.NDX"):
        source = {"timezone": "America/New_York", "open": "09:30", "close": "16:00"}
    else:
        source = {"timezone": "Asia/Shanghai", "open": "09:30", "close": "15:00"}
    return "open" if _market_status(source, now or datetime.now(timezone.utc)) == "delayed" else "closed"


def _candle_freshness(symbol: str, rows: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    """Describe candle freshness without claiming a real-time provider feed.

    FTShare OHLCV responses do not expose a universal quote timestamp.  We can
    still report the latest supplied bar and whether it belongs to the current
    exchange session; callers should treat ``delayed`` as end-of-bar data, not a
    tick-level quote.
    """
    exchange_timezone = _exchange_timezone(symbol)
    current = now or datetime.now(timezone.utc)
    local_now = current.astimezone(ZoneInfo(exchange_timezone))
    latest = max((int(row.get("time") or 0) for row in rows), default=0)
    if not latest:
        return {"status": "stale", "as_of": None, "freshness": "no_candle_timestamp", "exchange_timezone": exchange_timezone}
    latest_local = datetime.fromtimestamp(latest, tz=ZoneInfo(exchange_timezone))
    market_status = _symbol_market_status(symbol, current)
    if market_status == "closed":
        status = "closed"
    elif latest_local.date() == local_now.date():
        status = "delayed"
    else:
        status = "stale"
    return {
        "status": status,
        "as_of": latest,
        "freshness": "derived_from_latest_candle",
        "exchange_timezone": exchange_timezone,
    }


def fetch_market_ticker() -> dict[str, Any]:
    """Fetch a compact A/HK/US index ticker, degrading silently per source.

    The view only renders when this returns one or more valid points. This
    deliberately keeps a transient vendor error out of the user-facing chart.
    """
    fetched_at = int(time.time())
    if not ftshare_available():
        return {
            "ok": True,
            "items": [],
            "source": "ftshare_unavailable",
            "updated_at": fetched_at,
            "status": "unavailable",
        }

    import ftshare as ft

    market = ft.market_api(timeout=8)
    items: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for source in MARKET_TICKER_SOURCES:
        try:
            raw = market.global_index_daily_kline(
                secid=source["symbol"],
                as_dataframe=False,
            )
        except Exception:
            continue
        item = _ticker_item(source, raw)
        if item is not None:
            item["status"] = _market_status(source, now)
            items.append(item)
    statuses = {item.get("status") for item in items}
    status = "delayed" if "delayed" in statuses else "closed" if statuses else "unavailable"
    return {"ok": True, "items": items, "source": "ftshare", "updated_at": fetched_at, "status": status}


def _latest_session_close_millis(timezone_name: str) -> int:
    """Return the latest weekday close in the exchange timezone.

    FTShare's minute endpoint expects a completed session boundary more
    reliably than a wall-clock timestamp late at night. Exchange holidays are
    harmless here: an empty chunk simply advances to the preceding session.
    """
    now = datetime.now(ZoneInfo(timezone_name))
    # US sessions can include 16:00--20:00 ET after-hours bars. Requesting the
    # fully completed extended session preserves them when FTShare provides
    # them, while the returned per-bar session label remains the source of truth.
    close_by_timezone = {
        "Asia/Shanghai": (15, 0),
        "Asia/Hong_Kong": (16, 0),
        "America/New_York": (20, 0),
    }
    hour, minute = close_by_timezone.get(timezone_name, (15, 0))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < candidate:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return int(candidate.timestamp() * 1000)


def _intraday_session_label(timestamp: int, timezone_name: str) -> str:
    """Classify a bar by its exchange-local start time without inventing bars."""
    local = datetime.fromtimestamp(int(timestamp), tz=ZoneInfo(timezone_name)).time()
    if timezone_name == "America/New_York":
        if clock_time(4, 0) <= local < clock_time(9, 30):
            return "pre_market"
        if clock_time(9, 30) <= local < clock_time(16, 0):
            return "regular"
        if clock_time(16, 0) <= local < clock_time(20, 0):
            return "after_hours"
        return "overnight"
    if timezone_name == "Asia/Hong_Kong":
        if clock_time(9, 30) <= local < clock_time(12, 0):
            return "morning"
        if clock_time(13, 0) <= local < clock_time(16, 0):
            return "afternoon"
        return "outside_regular"
    if clock_time(9, 30) <= local < clock_time(11, 30):
        return "morning"
    if clock_time(13, 0) <= local < clock_time(15, 0):
        return "afternoon"
    return "outside_regular"


def _annotate_intraday_rows(rows: list[dict[str, Any]], *, timezone_name: str, interval_value: int) -> list[dict[str, Any]]:
    """Attach exact open timestamps when supplied and a display-only session label."""
    step_seconds = max(1, int(interval_value)) * 60
    for row in rows:
        close_time = int(row["time"])
        start_time = int(row.get("open_time") or (close_time - step_seconds))
        row["session"] = _intraday_session_label(start_time, timezone_name)
    return rows


def fetch_candles(
    symbol: str,
    *,
    interval: str = "day",
    interval_value: int = 1,
    session_count: int | None = None,
    limit: int = 220,
    adjust: str = "none",
) -> dict[str, Any]:
    """Fetch OHLCV via ftshare SDK.

    Notes:
    - The SDK accepts lowercase adjustment enum values: none/forward/backward.
    - Quarterly bars are aggregated from monthly candles because FTShare does
      not expose a native Quarter variant.
    - ``limit`` is roughly calendar-days lookback on ftshare; we do **not**
      overfetch/correct here (keep the new MCP thin). Agent wanting N bars
      should request a larger limit.
    """
    sym = _canonical_market_symbol(symbol)
    if not sym:
        return {"ok": False, "error": "invalid_symbol", "message": "symbol is required"}
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,63}", sym):
        return {"ok": False, "error": "invalid_symbol", "message": f"invalid symbol: {symbol}"}
    normalized_interval = (interval or "day").strip().lower()
    supported_intervals = {"minute", "day", "week", "month", "quarter", "year"}
    if normalized_interval not in supported_intervals:
        return {
            "ok": False,
            "error": "unsupported_interval",
            "message": f"unsupported interval: {interval}",
            "supported_intervals": sorted(supported_intervals),
        }
    ambiguous = _ambiguous_broad_index_result(sym)
    if ambiguous is not None:
        return ambiguous
    if _broad_index_for_symbol(sym) is not None:
        return _index_candles_provider_unavailable_result(sym)

    fetched_at = int(time.time())
    if not ftshare_available():
        return _ftshare_unavailable_result()

    import ftshare as ft

    unit = _interval_to_sdk(interval)
    adj = _adjust_to_sdk(adjust)
    step = max(1, min(int(interval_value or 1), 240))
    sessions = max(1, min(int(session_count or 1), 10))
    lim = max(1, min(int(limit or 220), 4000))
    exchange_timezone = _exchange_timezone(sym)
    if normalized_interval == "minute" and _is_hk_symbol(sym):
        return {
            "ok": False,
            "error": "intraday_provider_unavailable",
            "error_code": "intraday_provider_unavailable",
            "message": "The current FTShare Python SDK has no verified Hong Kong minute-candle endpoint.",
            "symbol": sym,
            "source": "ftshare",
            "next_action": "Use daily-or-larger Hong Kong candles, or pass verified minute rows from another provider.",
            "retryable": False,
        }
    cache_key = _candle_cache_key(sym, normalized_interval, step, sessions, lim, adjust)
    fresh_cache = _recent_candle_cache(cache_key)
    if fresh_cache is not None:
        return fresh_cache

    market = ft.market_api(timeout=20)
    raw: Any = None
    fetch_error: Exception | None = None
    us_daily_history_error: Exception | None = None
    hk_history_error: Exception | None = None
    for attempt in range(2):
        try:
            if _is_us_symbol(sym) and normalized_interval != "minute":
                try:
                    raw = _fetch_us_daily_candles(market, sym, lim)
                except Exception as exc:  # noqa: BLE001
                    # The dedicated US endpoint is preferred when it is healthy,
                    # but it has independently returned 5xx responses in
                    # production. Fall back to the generic history endpoint so
                    # daily 10D/30D/YTD charts do not fail while minute data works.
                    us_daily_history_error = exc
                    raw = _fetch_generic_history(
                        market,
                        symbol=sym,
                        interval=normalized_interval,
                        interval_unit=unit,
                        interval_value=step,
                        adjust_kind=adj,
                        limit=lim,
                    )
            elif _is_hk_symbol(sym) and normalized_interval in {"day", "month", "quarter", "year"}:
                try:
                    raw = _fetch_hk_candles(market, sym, normalized_interval, lim, adjust)
                except Exception as exc:  # noqa: BLE001
                    hk_history_error = exc
                    raw = _fetch_generic_history(
                        market,
                        symbol=sym,
                        interval=normalized_interval,
                        interval_unit=unit,
                        interval_value=step,
                        adjust_kind=adj,
                        limit=lim,
                    )
            elif normalized_interval == "minute":
                # FTShare minute history is restricted to short natural-date
                # windows. Page backwards from the latest session close and retain
                # the requested number of *trading* sessions after de-duplication.
                # This is intentionally not a calendar-day slice: a 5D chart means
                # five sessions even across a weekend.
                cutoff = _latest_session_close_millis(exchange_timezone)
                unique: dict[int, dict[str, Any]] = {}
                previous_earliest: int | None = None
                # FTShare rejects windows that span more than three natural
                # days. Keep each page to two days and walk backwards until the
                # requested number of trading sessions has been collected.
                page_window_days = 2
                max_pages = max(6, sessions * 2 + 2)
                for _page in range(max_pages):
                    page = market.stock_candlesticks(
                        symbol=sym,
                        interval_unit="Minute",
                        interval_value=step,
                        adjust_kind=adj,
                        since_ts_millis=max(
                            0,
                            cutoff - page_window_days * 86_400_000,
                        ),
                        until_ts_millis=cutoff,
                        limit=min(500, max(lim, sessions * 250)),
                        as_dataframe=False,
                    )
                    chunk = _normalize_raw(page)
                    if not chunk:
                        break
                    for row in chunk:
                        unique[int(row["time"])] = row
                    earliest = min(int(row["time"]) for row in chunk)
                    if previous_earliest is not None and earliest >= previous_earliest:
                        break
                    previous_earliest = earliest
                    local_dates = {
                        datetime.fromtimestamp(int(row["time"]), tz=ZoneInfo(exchange_timezone)).date()
                        for row in unique.values()
                    }
                    if len(local_dates) >= sessions:
                        break
                    cutoff = earliest * 1000 - 1
                raw = list(unique.values())
            else:
                raw = _fetch_generic_history(
                    market,
                    symbol=sym,
                    interval=normalized_interval,
                    interval_unit=unit,
                    interval_value=step,
                    adjust_kind=adj,
                    limit=lim,
                )
            fetch_error = None
            break
        except Exception as exc:  # noqa: BLE001
            fetch_error = exc
            if attempt == 0:
                time.sleep(0.35)
    if fetch_error is not None:
        fallback = _cached_candle_fallback(cache_key, fetch_error)
        if fallback is not None:
            return fallback
        return {
            "ok": False,
            "error": "fetch_failed",
            "message": f"ftshare stock_candlesticks failed: {fetch_error}",
            "symbol": sym,
            "source": "ftshare",
            "updated_at": fetched_at,
            "status": "delayed",
            "market_status": _symbol_market_status(sym),
        }

    rows = _normalize_raw(raw)
    if normalized_interval == "minute" and rows:
        rows = _annotate_intraday_rows(rows, timezone_name=exchange_timezone, interval_value=step)
        dates = sorted(
            {
                datetime.fromtimestamp(int(row["time"]), tz=ZoneInfo(exchange_timezone)).date()
                for row in rows
            }
        )
        selected_dates = set(dates[-sessions:])
        rows = [
            row
            for row in rows
            if datetime.fromtimestamp(int(row["time"]), tz=ZoneInfo(exchange_timezone)).date() in selected_dates
        ]
    if _is_us_symbol(sym) and normalized_interval != "minute":
        rows = _aggregate_interval(rows[-lim:], interval, timezone_name=exchange_timezone)
    elif normalized_interval == "quarter":
        rows = _aggregate_quarters(rows, timezone_name=exchange_timezone)[-lim:]
    elif not _is_hk_symbol(sym) and normalized_interval != "minute" and len(rows) > lim:
        rows = rows[-lim:]
    if len(rows) < 2:
        empty_error = "FTShare returned fewer than two valid candles"
        fallback = _cached_candle_fallback(cache_key, empty_error)
        if fallback is not None:
            return fallback
        result = {
            "ok": False,
            "error": "insufficient_candles",
            "message": empty_error,
            "symbol": sym,
            "source": "ftshare",
            "updated_at": fetched_at,
            "status": "delayed",
            "market_status": _symbol_market_status(sym),
        }
        if hk_history_error is not None:
            result["warning"] = "FTShare HK history was stale or unavailable; generic candle fallback had insufficient data."
            result["upstream_error"] = str(hk_history_error)[:500]
            result["fallback"] = "generic_stock_candlesticks"
        return result
    name = _symbol_name(market, sym)
    freshness = _candle_freshness(sym, rows)
    result = {
        "ok": True,
        "symbol": sym,
        "name": name,
        "interval": normalized_interval,
        "interval_value": step,
        "session_count": sessions if normalized_interval == "minute" else None,
        "adjust": (adjust or "none").strip().lower(),
        "count": len(rows),
        "rows": rows,
        "source": "ftshare",
        "updated_at": fetched_at,
        "status": freshness["status"],
        "market_status": _symbol_market_status(sym),
        "exchange_timezone": freshness["exchange_timezone"],
        "as_of": freshness["as_of"],
        "freshness": freshness["freshness"],
    }
    if us_daily_history_error is not None:
        result["warning"] = "FTShare US daily history endpoint failed; used generic candle fallback."
        result["upstream_error"] = str(us_daily_history_error)[:500]
        result["fallback"] = "generic_stock_candlesticks"
    if hk_history_error is not None:
        result["warning"] = "FTShare HK history endpoint failed; used generic candle fallback."
        result["upstream_error"] = str(hk_history_error)[:500]
        result["fallback"] = "generic_stock_candlesticks"
    if normalized_interval == "minute":
        sessions_seen = sorted({str(row.get("session") or "") for row in rows if row.get("session")})
        result["timestamp_semantics"] = "time is bar close in Unix seconds; open_time is present only when supplied by FTShare."
        result["sessions"] = sessions_seen
    _cache_candles(cache_key, result)
    return result


def _workspace_rows(raw: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in _rows_from_directory_response(raw)]


_US_INCOME_FIELD_MAP = {
    "revenue": "total_revenue",
    "tot_revenue": "total_revenue",
    "net_income": "net_income",
    "net_incattparesh": "net_income",
    "gross_profit": "gross_profit",
    "operating_income": "operating_income",
    "basic_eps": "basic_eps",
    "dilute_eps": "diluted_eps",
}


def _pivot_us_income_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn FTShare U.S. ``ind_name`` / ``ind_value`` records into report rows."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        end_date = str(row.get("end_date") or row.get("report_date") or "").strip()
        period = str(row.get("ind_type") or row.get("report_type") or "").strip()
        source_name = str(row.get("ind_name") or "").strip().lower()
        value = row.get("ind_value")
        target_name = _US_INCOME_FIELD_MAP.get(source_name)
        if not end_date or not target_name or value in (None, ""):
            continue
        item = groups.setdefault(
            (end_date, period),
            {
                "report_date": f"{end_date} {period}".strip(),
                "end_date": end_date,
                "report_type": period,
                "currency": row.get("currency") or row.get("currency_code") or "USD",
            },
        )
        item.setdefault(target_name, value)
    return [groups[key] for key in sorted(groups, reverse=True)]


def _workspace_value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _display_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    absolute = abs(number)
    if absolute >= 100_000_000:
        return f"{number / 100_000_000:.2f}亿"
    if absolute >= 10_000:
        return f"{number / 10_000:.2f}万"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _cn_stock_code(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    return normalized.replace(".XSHG", ".SH").replace(".XSHE", ".SZ")


def _workspace_market(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if _is_us_symbol(normalized):
        return "US"
    if normalized.endswith((".HK", ".HKG")) or normalized.startswith("100.HSI"):
        return "HK"
    return "CN"


def _workspace_news(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Normalize articles while retaining source provenance when supplied."""
    items: list[dict[str, str]] = []
    for row in rows[:12]:
        title = _workspace_value(row, "title", "news_title", "headline", "name")
        if not title:
            continue
        items.append(
            {
                "title": str(title),
                "time": str(_workspace_value(row, "time", "publish_time", "datetime", "date") or "--"),
                "summary": str(_workspace_value(row, "summary", "content", "abstract", "digest") or ""),
                "kind": str(_workspace_value(row, "kind", "source", "media", "category") or "资讯"),
                "source_url": str(_workspace_value(row, "source_url", "url", "link", "article_url") or ""),
                "article_id": str(_workspace_value(row, "article_id", "news_id", "id", "uuid") or ""),
                "entity_id": str(_workspace_value(row, "symbol", "security_id", "entity_id", "stock_code") or ""),
            }
        )
    return items


def _workspace_financials(rows: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_rows: list[list[str]] = []
    metrics: list[dict[str, str]] = []
    for index, row in enumerate(rows[:8]):
        period = _workspace_value(row, "report_date", "end_date", "period", "report_period", "report_type_cn", "date") or "--"
        # FTShare's wide A-share income records use t_revenue/n_profit while
        # other adapters commonly use total_revenue/net_income. Keep both
        # families so a valid record never becomes a row of placeholder values.
        revenue = _workspace_value(row, "total_operate_income", "total_revenue", "t_revenue", "revenue", "operating_revenue")
        profit = _workspace_value(row, "net_profit", "n_profit", "net_income", "netprofit", "parent_netprofit", "parcomp_n_profit")
        margin = _workspace_value(row, "gross_margin", "grossprofit_margin")
        cash = _workspace_value(row, "operate_cash_flow", "operating_cash_flow", "cash_from_operations")
        normalized_rows.append([str(period), _display_number(revenue), _display_number(profit), _display_number(margin), _display_number(cash)])
        if index == 0:
            for label, value in (("营业收入", revenue), ("净利润", profit), ("毛利率", margin), ("经营现金流", cash)):
                if value not in (None, ""):
                    metrics.append({"label": label, "value": _display_number(value)})
    currency = _workspace_value(rows[0], "currency", "currency_code", "unit", "currency_unit") if rows else None
    return {"metrics": metrics, "rows": normalized_rows, "unit": str(currency or "未声明")}


def _workspace_holders(rows: list[dict[str, Any]]) -> dict[str, Any]:
    flattened: list[dict[str, Any]] = []
    for record in rows:
        nested = record.get("fen_holders")
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, Mapping):
                    flattened.append(
                        {
                            **dict(item),
                            "report_date": _workspace_value(record, "report_date", "publish_date", "end_date", "date"),
                        }
                    )
        else:
            flattened.append(record)
    items: list[dict[str, Any]] = []
    for row in flattened[:10]:
        name = _workspace_value(row, "holder_name", "shareholder_name", "name", "holder")
        if not name:
            continue
        percent = _workspace_value(row, "hold_ratio", "holding_ratio", "shareholding_ratio", "share_ratio", "percent", "ratio")
        shares = _workspace_value(row, "hold_amount", "holding_amount", "shareholding", "shares", "hold_num")
        change = _workspace_value(row, "change_ratio", "change_percentage", "change", "hold_change")
        try:
            percent_number = float(percent) if percent not in (None, "") else 0.0
        except (TypeError, ValueError):
            percent_number = 0.0
        items.append({"name": str(name), "percent": percent_number, "shares": _display_number(shares), "change": str(change or "--")})
    updated = _workspace_value(rows[0], "report_date", "publish_date", "end_date", "date") if rows else None
    return {"updated_at": str(updated or "--"), "items": items}


def _workspace_overview_metrics(
    financials: Mapping[str, Any], balance_rows: list[dict[str, Any]], cashflow_rows: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """Build a compact factual company snapshot from FTShare wide tables."""
    metrics = list(financials.get("metrics") or [])[:2]
    balance = balance_rows[0] if balance_rows else {}
    cashflow = cashflow_rows[0] if cashflow_rows else {}
    assets = _workspace_value(balance, "t_assets", "total_assets", "assets")
    liability_ratio = _workspace_value(balance, "asset_liability_ratio", "debt_to_assets")
    operating_cash = _workspace_value(cashflow, "net_oper_cash_flow", "operate_cash_flow", "operating_cash_flow")
    if assets not in (None, ""):
        metrics.append({"label": "总资产", "value": _display_number(assets)})
    if liability_ratio not in (None, ""):
        try:
            metrics.append({"label": "资产负债率", "value": f"{float(liability_ratio):.2f}%"})
        except (TypeError, ValueError):
            pass
    if operating_cash not in (None, ""):
        metrics.append({"label": "经营现金流", "value": _display_number(operating_cash)})
    return metrics[:5]


def _display_percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    return f"{number:.2f}%"


def _workspace_overview_details(
    *,
    basic: Mapping[str, Any],
    financial_rows: list[dict[str, Any]],
    balance_rows: list[dict[str, Any]],
    cashflow_rows: list[dict[str, Any]],
    holder_count_rows: list[dict[str, Any]],
    pledge_rows: list[dict[str, Any]],
    share_change_rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Normalize the factual fields that make an equity profile actionable.

    FTShare endpoints use different field names across source families. Keep a
    compact, de-duplicated list so the frontend can omit unavailable fields
    instead of rendering a table full of placeholders.
    """
    details: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(label: str, value: Any, *keys: str, style: str = "text", group: str = "经营与资本结构") -> None:
        candidate = value if value not in (None, "") else _workspace_value(row, *keys)
        if candidate in (None, "") or label in seen:
            return
        rendered = _display_percent(candidate) if style == "percent" else _display_number(candidate) if style == "number" else str(candidate)
        if rendered == "--":
            return
        seen.add(label)
        details.append({"label": label, "value": rendered, "group": group})

    row: Mapping[str, Any] = basic
    add("成立日期", None, "establish_date", "found_date", "setup_date", "founded_date", group="公司档案")
    add("注册资本", None, "registered_capital", "reg_capital", "register_capital", style="number", group="公司档案")
    add("法人代表", None, "legal_representative", "legal_person", "chairman", "representative", group="公司档案")
    add("注册地", None, "registered_address", "address", "province", "city", group="公司档案")
    add("主营业务", None, "main_business", "business_scope", "business", "description", group="公司档案")

    row = financial_rows[0] if financial_rows else {}
    add("最新报告期", None, "report_date", "end_date", "period", "report_period", "report_type_cn", "date")
    add("营业收入同比", None, "revenue_yoy", "total_revenue_yoy", "yoy_revenue", "operate_income_yoy", style="percent")
    add("净利润同比", None, "net_profit_yoy", "n_profit_yoy", "yoy_netprofit", "net_income_yoy", style="percent")
    add("净资产收益率", None, "roe", "roe_weighted", "return_on_equity", style="percent")
    add("每股收益", None, "basic_eps", "eps", "diluted_eps")

    row = balance_rows[0] if balance_rows else {}
    add("总负债", None, "t_liabilities", "total_liabilities", "liabilities", style="number")
    add("归母权益", None, "total_hldr_eqy_exc_min_int", "total_hldr_eqy_inc_min_int", "total_equity", "shareholders_equity", style="number")
    add("货币资金", None, "money_cap", "cash", "cash_and_equivalents", style="number")
    add("应收账款", None, "accounts_receivable", "acct_rcv", "receivables", style="number")
    add("存货", None, "inventories", "inventory", style="number")

    row = cashflow_rows[0] if cashflow_rows else {}
    add("投资现金流", None, "net_invest_cash_flow", "invest_cash_flow", "cash_from_investment", style="number")
    add("筹资现金流", None, "net_finance_cash_flow", "finance_cash_flow", "cash_from_financing", style="number")
    add("期末现金余额", None, "cash_equ_end_period", "cash_end", "ending_cash", style="number")

    row = holder_count_rows[0] if holder_count_rows else {}
    add("股东户数", None, "holder_num", "holder_count", "holders_num", "shareholder_num", style="number", group="股东与治理")
    add("股东户数变动", None, "holder_num_change", "holder_change", "change_ratio", "change_percentage", style="percent", group="股东与治理")

    row = pledge_rows[0] if pledge_rows else {}
    add("股份质押比例", None, "pledge_ratio", "pledged_ratio", "pledge_percent", style="percent", group="股东与治理")
    add("质押股份", None, "pledge_shares", "pledged_shares", "pledge_amount", style="number", group="股东与治理")

    row = share_change_rows[0] if share_change_rows else {}
    add("最近增减持日期", None, "change_date", "announce_date", "end_date", "date", group="股东与治理")
    add("最近增减持比例", None, "change_ratio", "change_percentage", "ratio", style="percent", group="股东与治理")
    return details[:24]


def _workspace_optional_rows(market: Any, method_name: str, **kwargs: Any) -> list[dict[str, Any]]:
    """Call an optional FTShare endpoint without making its availability fatal."""
    method = getattr(market, method_name, None)
    if not callable(method):
        return []
    return _workspace_rows(method(as_dataframe=False, **kwargs))


def fetch_security_workspace(symbol: str, *, name: str | None = None) -> dict[str, Any]:
    """Load FTShare news and company data into the provider-neutral app schema.

    This is deliberately independent from ``fetch_candles``: a slow or missing
    company endpoint must never delay the chart.  Each section is best-effort,
    and callers can later replace the same ``security_workspace`` contract with
    another licensed provider.
    """
    sym = str(symbol or "").strip()
    if not sym:
        return {"ok": False, "error": "invalid_symbol", "message": "symbol is required"}
    key = sym.upper()
    cached = _security_workspace_cache.get(key)
    now = time.time()
    if cached and now - cached[0] < _SECURITY_WORKSPACE_CACHE_TTL_SECONDS:
        return {"ok": True, "cached": True, "security_workspace": cached[1]}
    if not ftshare_available():
        return _ftshare_unavailable_result()

    import ftshare as ft

    market = ft.market_api(timeout=12)
    display_name = str(name or sym)
    market_name = _workspace_market(sym)
    try:
        resolved = _symbol_name(market, sym)
        if resolved and resolved != sym:
            display_name = resolved
    except Exception:
        pass
    errors: list[str] = []
    news_rows: list[dict[str, Any]] = []
    financial_rows: list[dict[str, Any]] = []
    holder_rows: list[dict[str, Any]] = []
    basic_rows: list[dict[str, Any]] = []
    balance_rows: list[dict[str, Any]] = []
    cashflow_rows: list[dict[str, Any]] = []
    holder_count_rows: list[dict[str, Any]] = []
    pledge_rows: list[dict[str, Any]] = []
    share_change_rows: list[dict[str, Any]] = []
    try:
        # Include the stable symbol in the semantic query. Provider-specific
        # adapters can later replace this with a direct entity/article endpoint.
        news_query = f"{display_name} {sym}" if display_name != sym else sym
        news_rows = _workspace_rows(market.semantic_search_news(query=news_query, limit=12, as_dataframe=False))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"news: {exc}")
    try:
        if market_name == "US":
            bare = _bare_us_symbol(sym)
            basic_rows = _workspace_rows(market.us_basic(stock_code=bare, limit=1, as_dataframe=False))
            # FTShare U.S. income data is a narrow indicator table. Request
            # enough records for several reports, then pivot it before the
            # shared overview/financial renderer consumes it.
            financial_rows = _pivot_us_income_rows(
                _workspace_rows(market.us_income(stock_code=bare, limit=200, as_dataframe=False))
            )
        elif market_name == "CN":
            code = _cn_stock_code(sym)
            basic_rows = _workspace_optional_rows(market, "company_list", stock_code=code, limit=1)
            financial_rows = _workspace_rows(market.income(stock_code=code, limit=8, as_dataframe=False))
            holder_rows = _workspace_rows(market.stock_holders(stock_code=code, limit=10, as_dataframe=False))
        else:
            errors.append("company: HK company adapter is not implemented")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"company: {exc}")
    if market_name == "CN":
        code = _cn_stock_code(sym)
        try:
            balance_rows = _workspace_rows(market.balance(stock_code=code, limit=8, as_dataframe=False))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"balance: {exc}")
        try:
            cashflow_rows = _workspace_rows(market.cashflow(stock_code=code, limit=8, as_dataframe=False))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"cashflow: {exc}")
        for label, method_name, kwargs in (
            ("holder_count", "stock_holders_number", {"stock_code": code, "limit": 2}),
            ("pledge", "stock_pledge_detail", {"stock_code": code, "limit": 1}),
            ("share_change", "stock_share_chg", {"stock_code": code, "limit": 1}),
        ):
            try:
                rows = _workspace_optional_rows(market, method_name, **kwargs)
                if label == "holder_count":
                    holder_count_rows = rows
                elif label == "pledge":
                    pledge_rows = rows
                else:
                    share_change_rows = rows
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: {exc}")
    basic = basic_rows[0] if basic_rows else {}
    financials = _workspace_financials(financial_rows)
    overview_metrics = _workspace_overview_metrics(financials, balance_rows, cashflow_rows)
    overview_details = _workspace_overview_details(
        basic=basic,
        financial_rows=financial_rows,
        balance_rows=balance_rows,
        cashflow_rows=cashflow_rows,
        holder_count_rows=holder_count_rows,
        pledge_rows=pledge_rows,
        share_change_rows=share_change_rows,
    )
    overview = {
        "company_name": str(_workspace_value(basic, "name", "company_name", "stock_name") or display_name),
        "market": market_name,
        "industry": str(_workspace_value(basic, "industry", "sector", "industry_name") or "--"),
        "listing_date": str(_workspace_value(basic, "listing_date", "list_date", "ipo_date") or "--"),
        "website": str(_workspace_value(basic, "website", "url", "company_website") or "--"),
        "employees": str(_workspace_value(basic, "employees", "employee_count") or "--"),
        "description": str(_workspace_value(basic, "description", "business_scope", "introduction") or "--"),
        # Company profile fields are not available for every FTShare market
        # adapter. Reuse factual, latest reported financial metrics rather
        # than rendering an empty Company page in that case.
        "metrics": overview_metrics,
        "details": overview_details,
    }
    workspace = {
        "symbol": sym,
        "source": {
            "name": "FTShare",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "status": "retrieved",
            "retrieved_at": int(time.time()),
            "query": news_query,
        },
        "news": _workspace_news(news_rows),
        "overview": overview,
        "financials": financials,
        "holders": _workspace_holders(holder_rows),
        "errors": errors,
        "sections": {
            "news": {"state": "available" if news_rows else "empty"},
            "overview": {"state": "available" if (basic_rows or overview_metrics) else ("unsupported" if market_name == "HK" else "empty")},
            "financials": {"state": "available" if financials["metrics"] else ("unsupported" if market_name == "HK" else "empty")},
            "holders": {"state": "available" if holder_rows else ("unsupported" if market_name in {"HK", "US"} else "empty")},
        },
    }
    _security_workspace_cache[key] = (now, workspace)
    return {"ok": True, "cached": False, "security_workspace": workspace}


def fetch_comparison_candles(symbol: str, *, limit: int = 390) -> dict[str, Any]:
    """Fetch daily comparison data without silently changing instrument type.

    The browser normalizes successful series against their first comparable
    close. A broad-index request returns the same explicit provider capability
    error as ``fetch_candles`` until a verified A-share index source is wired.
    """
    sym = _canonical_market_symbol(symbol)
    if not sym:
        return {"ok": False, "error": "invalid_symbol", "message": "symbol is required"}
    return fetch_candles(sym, interval="day", limit=limit, adjust="none")
