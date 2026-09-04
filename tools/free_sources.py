"""Built-in free market-data fallback for dsh_kline.

FTShare is the primary, promoted provider. This module is a *fallback* that
keeps basic broad-market data visible when the current FTShare plan cannot
serve it (anonymous/free tier without HK/US/index entitlements).

Design rules (mirror docs/provider-adaptation.md):
- Small, explicit registries only. No runtime discovery; no remote data ever
  adds a URL or executes code.
- Public, key-less HTTP endpoints only (Eastmoney push2his daily K-lines and
  Tencent qt.gtimg quote snapshots). No scraping of HTML.
- Every row keeps the canonical OHLCV shape (close-time, unix seconds) and the
  response carries ``source`` + ``source_url`` so callers can label the data as
  free fallback instead of silently pretending it came from FTShare.
- Bounded requests, short in-process cache, silent degradation on failure:
  a transient free-source error must never break the primary chart.

This module is provider-neutral at the row level and imports nothing from
tools.fetch (which imports this module for fallback wiring).
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Registries (small and explicit)
# ---------------------------------------------------------------------------

_CN_TZ = timezone(timedelta(hours=8))
_HK_TZ = timezone(timedelta(hours=8))
_US_TZ = timezone(timedelta(hours=-5))  # EST; used only for weekday calendar math

_HTTP_TIMEOUT_SECONDS = 8.0
_CACHE_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 96

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Eastmoney broad-market indices that the FTShare free/anonymous tier commonly
# cannot serve. key = dsh_kline canonical symbol, value = eastmoney secid.
EM_INDEX_SECIDS: dict[str, str] = {
    "000001.XSHG": "1.000001",  # 上证指数
    "000016.XSHG": "1.000016",  # 上证50
    "000300.XSHG": "1.000300",  # 沪深300
    "000905.XSHG": "1.000905",  # 中证500
    "000906.XSHG": "1.000906",  # 中证800
    "000852.XSHG": "1.000852",  # 中证1000
    "399001.XSHE": "0.399001",  # 深证成指
    "399006.XSHE": "0.399006",  # 创业板指
    "100.HSI": "100.HSI",  # 恒生指数
    "100.NDX": "100.NDX",  # 纳斯达克100
}

EM_INDEX_NAMES: dict[str, str] = {
    "000001.XSHG": "上证指数",
    "000016.XSHG": "上证50",
    "000300.XSHG": "沪深300",
    "000905.XSHG": "中证500",
    "000906.XSHG": "中证800",
    "000852.XSHG": "中证1000",
    "399001.XSHE": "深证成指",
    "399006.XSHE": "创业板指",
    "100.HSI": "恒生指数",
    "100.NDX": "纳斯达克100",
}

# Tencent quote codes for the real-time broad-market ticker strip.
# key = dsh_kline canonical symbol.
TENCENT_TICKER_SOURCES: dict[str, dict[str, str]] = {
    "100.HSI": {"code": "hkHSI", "market": "HK", "name": "恒生指数", "timezone": "Asia/Hong_Kong", "open": "09:30", "close": "16:00"},
    "100.NDX": {"code": "usNDX", "market": "US", "name": "纳斯达克100", "timezone": "America/New_York", "open": "09:30", "close": "16:00"},
    "000001.XSHG": {"code": "s_sh000001", "market": "CN", "name": "上证指数", "timezone": "Asia/Shanghai", "open": "09:30", "close": "15:00"},
    "000300.XSHG": {"code": "s_sh000300", "market": "CN", "name": "沪深300", "timezone": "Asia/Shanghai", "open": "09:30", "close": "15:00"},
    "399001.XSHE": {"code": "s_sz399001", "market": "CN", "name": "深证成指", "timezone": "Asia/Shanghai", "open": "09:30", "close": "15:00"},
}

SOURCE_URL = "https://push2his.eastmoney.com"
TENCENT_SOURCE_URL = "https://qt.gtimg.cn"
SOURCE_LABEL = "东方财富免费行情"
TENCENT_LABEL = "腾讯免费行情"

_cache_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, Any]] = {}


def _cache_get(key: tuple[str, str]) -> Any | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        stamp, value = entry
        if time.time() - stamp > _CACHE_TTL_SECONDS:
            _cache.pop(key, None)
            return None
        return value


def _cache_set(key: tuple[str, str], value: Any) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            oldest = min(_cache, key=lambda item: _cache[item][0])
            _cache.pop(oldest, None)
        _cache[key] = (time.time(), value)


def _http_get_json(url: str, *, referer: str | None = "https://quote.eastmoney.com/") -> Any | None:
    headers = {"User-Agent": _USER_AGENT}
    if referer:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - fallback must degrade silently
        return None


def _http_get_text(url: str) -> str | None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            return response.read().decode("gbk", errors="replace")
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Eastmoney daily K-line fallback (broad-market indices)
# ---------------------------------------------------------------------------


def _em_date_to_seconds(date_text: str, timezone_name: str = "Asia/Shanghai") -> int:
    """Parse YYYY-MM-DD into a close-time unix-second (day bars close same day)."""
    try:
        parsed = datetime.strptime(str(date_text)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return 0
    if timezone_name == "Asia/Hong_Kong":
        local = parsed.replace(tzinfo=_HK_TZ)
    elif timezone_name == "America/New_York":
        local = parsed.replace(hour=16, tzinfo=_US_TZ)
    else:
        local = parsed.replace(hour=15, tzinfo=_CN_TZ)
    return int(local.timestamp())


def _parse_em_kline_payload(payload: Any, timezone_name: str) -> list[dict[str, Any]]:
    """Parse eastmoney push2his klines into canonical OHLCV rows."""
    rows: list[dict[str, Any]] = []
    try:
        data = payload.get("data") or {}
        klines = data.get("klines") or []
    except AttributeError:
        return rows
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        # fields2=f51(date),f52(open),f53(close),f54(high),f55(low),f56(volume)
        date_text, open_px, close_px, high_px, low_px = parts[:5]
        volume = parts[5] if len(parts) > 5 else ""
        timestamp = _em_date_to_seconds(date_text, timezone_name)
        if not timestamp:
            continue
        try:
            row = {
                "time": timestamp,
                "open": float(open_px),
                "high": float(high_px),
                "low": float(low_px),
                "close": float(close_px),
                "volume": float(volume) if str(volume).replace(".", "", 1).isdigit() else 0.0,
            }
        except (TypeError, ValueError):
            continue
        rows.append(row)
    rows.sort(key=lambda item: int(item["time"]))
    return rows


def fetch_em_index_daily(symbol: str, *, limit: int = 120) -> list[dict[str, Any]] | None:
    """Fetch broad-market index daily K-lines from Eastmoney.

    Only symbols present in EM_INDEX_SECIDS are routed here. Returns canonical
    rows (oldest → newest) or None when unavailable.

    The upstream API is inconsistent across backend nodes about whether
    ``lmt`` counts from the beginning or the end of the requested range, so we
    always request a *recent* window that comfortably covers ``limit`` bars and
    slice the newest ones from the response.
    """
    secid = EM_INDEX_SECIDS.get(str(symbol or "").strip().upper())
    if not secid:
        return None
    wanted = max(2, min(int(limit), 4000))
    cache_key = ("em_index_daily", f"{secid}:{wanted}")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    # ~365 calendar days per year; daily bars ≈ 244/year. A factor of 2 gives
    # headroom for weekends/holidays without bloating the response.
    calendar_days = max(30, int(wanted * 1.7))
    beg_date = (datetime.now(_CN_TZ) - timedelta(days=calendar_days)).strftime("%Y%m%d")
    query = urllib.parse.urlencode(
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "klt": "101",
            "fqt": "0",
            "beg": beg_date,
            "end": "20500101",
            "lmt": str(wanted * 3),
        }
    )
    url = f"{SOURCE_URL}/api/qt/stock/kline/get?{query}"
    payload = _http_get_json(url)
    rows = _parse_em_kline_payload(payload, "Asia/Shanghai")
    if len(rows) < 2:
        return None
    result = rows[-wanted:]
    _cache_set(cache_key, result)
    return result


def em_symbol_supported(symbol: str) -> bool:
    return str(symbol or "").strip().upper() in EM_INDEX_SECIDS


# Tencent historical K-line fallback for the same broad indices. The Tencent
# daily bar array is [date, open, close, high, low, volume] (open before close),
# which differs from Eastmoney's [date, open, close, high, low, volume, ...] in
# name only after parsing — both place close at index 2 of the bar row.
_TENCENT_KLINE_CODES: dict[str, str] = {
    "100.HSI": "hkHSI",
    "100.NDX": "usNDX",
    "000001.XSHG": "sh000001",
    "000016.XSHG": "sh000016",
    "000300.XSHG": "sh000300",
    "000905.XSHG": "sh000905",
    "000906.XSHG": "sh000906",
    "000852.XSHG": "sh000852",
    "399001.XSHE": "sz399001",
    "399006.XSHE": "sz399006",
}


def _parse_tencent_kline_payload(payload: Any, timezone_name: str) -> list[dict[str, Any]]:
    """Parse Tencent fqkline response into canonical OHLCV rows."""
    rows: list[dict[str, Any]] = []
    try:
        data = payload.get("data") or {}
    except AttributeError:
        return rows
    for _code, node in data.items():
        # node: {"day": [[date, open, close, high, low, volume], ...], "qfqday": …}
        bars = node.get("day") if isinstance(node, Mapping) else None
        if not isinstance(bars, list):
            continue
        for bar in bars:
            if not isinstance(bar, (list, tuple)) or len(bar) < 6:
                continue
            date_text, open_px, close_px, high_px, low_px, volume = bar[:6]
            timestamp = _em_date_to_seconds(str(date_text), timezone_name)
            if not timestamp:
                continue
            try:
                rows.append(
                    {
                        "time": timestamp,
                        "open": float(open_px),
                        "high": float(high_px),
                        "low": float(low_px),
                        "close": float(close_px),
                        "volume": float(volume) if str(volume).replace(".", "", 1).isdigit() else 0.0,
                    }
                )
            except (TypeError, ValueError):
                continue
    rows.sort(key=lambda item: int(item["time"]))
    return rows


def fetch_tencent_index_daily(symbol: str, *, limit: int = 120) -> list[dict[str, Any]] | None:
    """Fetch broad-market index daily K-lines from Tencent (fallback feed).

    Mirrors ``fetch_em_index_daily`` in behavior and return shape. Returns
    canonical rows (oldest → newest) or None when unavailable.
    """
    canonical = str(symbol or "").strip().upper()
    code = _TENCENT_KLINE_CODES.get(canonical)
    if not code:
        return None
    wanted = max(2, min(int(limit), 4000))
    cache_key = ("tencent_index_daily", f"{code}:{wanted}")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    # Tencent returns the requested number of bars counting backwards from today.
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{wanted},qfq"
    payload = _http_get_json(url, referer=None)
    timezone_name = "Asia/Hong_Kong" if canonical == "100.HSI" else "America/New_York" if canonical == "100.NDX" else "Asia/Shanghai"
    rows = _parse_tencent_kline_payload(payload, timezone_name)
    if len(rows) < 2:
        return None
    result = rows[-wanted:]
    _cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Tencent real-time quote ticker
# ---------------------------------------------------------------------------

_TENCENT_FIELD_COUNT_MIN = 6


def _parse_tencent_index(code: str, market: str, text: str) -> dict[str, Any] | None:
    """Parse qt.gtimg response for the configured index quote codes.

    Field layouts differ by market family (verified live):
    - CN index (s_sh000001 …): name/code/close/change/change_pct at idx1..5.
    - HK index (hkHSI): close at idx3, prev close at idx4, tail carries change.
    - US index (usNDX): close at idx3, prev close at idx4.
    We compute change from prev close when present, else trust the given amount.
    """
    if not text:
        return None
    match = re.search(r'="([^"]+)"', text)
    if not match:
        return None
    fields = match.group(1).split("~")
    if len(fields) < _TENCENT_FIELD_COUNT_MIN:
        return None
    try:
        close = float(fields[3])
    except (TypeError, ValueError, IndexError):
        return None
    if close <= 0:
        return None
    name = fields[1] if len(fields) > 1 and fields[1] else code
    if market == "CN":
        # CN: idx4 = change amount, idx5 = change_pct; prev close is derived.
        try:
            change = float(fields[4])
            change_pct = float(fields[5])
        except (TypeError, ValueError, IndexError):
            return None
        previous = close - change if change else close
    else:
        # HK/US: idx4 = previous close; change is derived.
        try:
            previous = float(fields[4])
        except (TypeError, ValueError, IndexError):
            return None
        if previous <= 0:
            return None
        change = close - previous
        change_pct = change / previous * 100.0
    return {
        "market": market,
        "symbol": code,
        "name": name,
        "close": round(close, 3),
        "change": round(change, 3),
        "change_pct": round(change_pct, 3),
        "time": int(time.time()),
    }


def fetch_tencent_ticker_items() -> list[dict[str, Any]]:
    """Fetch real-time broad-index quotes for the bottom market strip.

    Returns the same item shape the FTShare ticker path uses, so the view
    renders identically. Empty list when the source is unreachable.
    """
    cache_key = ("tencent_ticker", "all")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    items: list[dict[str, Any]] = []
    for symbol, source in TENCENT_TICKER_SOURCES.items():
        url = f"{TENCENT_SOURCE_URL}/q={source['code']}"
        text = _http_get_text(url)
        item = _parse_tencent_index(source["code"], source["market"], text or "")
        if item is not None:
            item["symbol"] = symbol  # canonical dsh_kline symbol for click-through
            item["name"] = source["name"]
            # Carry session metadata so the caller can label delayed/closed
            # without owning the market-hours table.
            item["session_timezone"] = source.get("timezone", "Asia/Shanghai")
            item["session_open"] = source.get("open", "09:30")
            item["session_close"] = source.get("close", "15:00")
            items.append(item)
    _cache_set(cache_key, items)
    return items


def tencent_symbols() -> list[str]:
    return list(TENCENT_TICKER_SOURCES.keys())


def free_source_status() -> dict[str, Any]:
    """Safe capability summary for the built-in free feeds (no keys/secrets)."""
    return {
        "available": True,
        "source": "builtin_free",
        "label": "内置免费行情（东财 / 腾讯）",
        "index_kline_symbols": sorted(EM_INDEX_NAMES.keys()),
        "index_kline_count": len(EM_INDEX_NAMES),
        "ticker_symbols": tencent_symbols(),
        "ticker_count": len(tencent_symbols()),
        "note": "仅供免费基础体验，行情可能延迟，请勿用于交易决策。正式/实时数据请使用 FTShare。",
    }
