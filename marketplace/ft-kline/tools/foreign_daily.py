"""Bounded, keyless Tencent HK/US daily history; no FTShare or A-share routes.

Prices are vendor-adjusted; volumes remain historical session shares, including
across splits. A day is anchored at 16:00 exchange time (not an execution tick).
See docs/free-foreign-daily.md for the verified contract and coverage limits.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
import math
import re
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from tools.free_sources import _cache_get, _cache_set

SOURCE_URL = "https://gu.qq.com/"
_BASE = "https://web.ifzq.gtimg.cn/appstock/app/"
_PAGE_SIZE = 640
_MAX_PAGES = 8
_MAX_BYTES = 2_000_000
_TIMEOUT = 6
_AGENT = "Mozilla/5.0 FT-KLine/0.6"


def foreign_market(symbol: str) -> str | None:
    if re.fullmatch(r"\d{5}\.HK", symbol):
        return "HK"
    if re.fullmatch(r"[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*\.US", symbol) and len(symbol) <= 28:
        return "US"
    return None


def _read(url: str, *, text: bool = False) -> Any:
    try:
        request = Request(url, headers={"User-Agent": _AGENT, "Referer": SOURCE_URL})
        with urlopen(request, timeout=_TIMEOUT) as response:
            raw = response.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            return None
        return raw.decode("gbk") if text else json.loads(raw.decode("utf-8"))
    except Exception:  # Public fallback failure must not break the primary provider.
        return None


def _us_code(root: str) -> str | None:
    key = ("tencent_us_identity", root)
    cached = _cache_get(key)
    if cached:
        return cached
    # The quote supplies only an identifier, never a URL or executable input.
    quote = _read("https://qt.gtimg.cn/q=" + "us" + root, text=True)
    if not isinstance(quote, str):
        return None
    lines = re.findall(r'v_us[A-Za-z0-9_.-]+="([^"\r\n]*)";', quote)
    if len(lines) != 1:
        return None
    fields = lines[0].split("~")
    identity = fields[2] if len(fields) > 2 else ""
    if identity not in {root + suffix for suffix in (".OQ", ".N", ".AM")}:
        return None
    code = "us" + identity
    _cache_set(key, code)
    return code


def _parse_page(payload: Any, code: str, series: str, zone: ZoneInfo, now: datetime,
                allow_negative: bool) -> tuple[list[dict], str | None] | None:
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return None
    data = payload.get("data")
    node = data.get(code) if isinstance(data, dict) else None
    bars = node.get(series) if isinstance(node, dict) else None
    if not isinstance(bars, list) or len(bars) > _PAGE_SIZE + 1:
        return None
    rows = []
    reason = None
    previous = ""
    for bar in bars:
        try:
            if not isinstance(bar, list) or len(bar) < 6:
                return None
            day = datetime.strptime(bar[0], "%Y-%m-%d")
            if day.strftime("%Y-%m-%d") != bar[0] or bar[0] <= previous:
                return None
            previous = bar[0]
            o, c, h, l, volume = map(float, bar[1:6])
            if not all(math.isfinite(x) for x in (o, c, h, l, volume)) or volume < 0:
                return None
            if l > min(o, c) or h < max(o, c) or l > h:
                return None
            if min(o, c, h, l) <= 0:
                if not allow_negative:
                    return None
                # Cumulative cash adjustments can make early HK qfq negative.
                # Keep only the contiguous newer positive-price tail, never
                # delete an interior invalid row and silently bridge a gap.
                rows.clear()
                reason = "non_positive_adjusted_prices"
                continue
            close = day.replace(hour=16, tzinfo=zone)
            cutoff = close + (timedelta(minutes=15) if zone.key == "Asia/Hong_Kong" else timedelta())
            if cutoff > now:
                continue  # Do not expose an unfinished daily candle as final.
            rows.append({"time": int(close.timestamp()), "open": o, "close": c,
                         "high": h, "low": l, "volume": volume})
        except (TypeError, ValueError, OverflowError):
            return None
    return rows, reason


def fetch_foreign_daily(symbol: str, *, limit: int = 220, adjust: str = "none") -> dict | None:
    market = foreign_market(symbol)
    if market is None or adjust not in {"none", "forward", "backward"}:
        return None
    if market == "US" and adjust == "backward":
        return None
    wanted = max(2, min(int(limit), 4000))
    key = ("tencent_foreign_daily", f"{symbol}:{wanted}:{adjust}")
    cached = _cache_get(key)
    if cached is not None:
        return deepcopy(cached)
    code = "hk" + symbol[:5] if market == "HK" else _us_code(symbol[:-3])
    if not code:
        return None
    mode, series = {"none": ("", "day"), "forward": ("qfq", "qfqday"),
                    "backward": ("hfq", "hfqday")}[adjust]
    route = "kline/kline" if not mode else ("hkfqkline/get" if market == "HK" else "usfqkline/get")
    zone = ZoneInfo("Asia/Hong_Kong" if market == "HK" else "America/New_York")
    now = datetime.now(zone)
    end = ""
    collected: dict[int, dict] = {}
    reason = "page_limit"
    pages = 0
    for _ in range(_MAX_PAGES):
        # Each older page overlaps the preceding boundary. Verify that prices
        # and share counts use the same basis before joining the two pages.
        count = min(_PAGE_SIZE, max(3, wanted - len(collected) + 2))
        url = _BASE + route + "?" + urlencode({"param": f"{code},day,,{end},{count},{mode}"})
        parsed = _parse_page(_read(url), code, series, zone, now, adjust == "forward")
        pages += 1
        if parsed is None:
            reason = "source_unavailable_or_invalid"
            break
        rows, boundary = parsed
        if not rows:
            reason = boundary or "source_history_exhausted"
            break
        if end and datetime.fromtimestamp(rows[-1]["time"], zone).date().isoformat() > end:
            reason = "source_ignored_history_boundary"
            break
        if collected and min(collected) not in {row["time"] for row in rows}:
            reason = "missing_page_overlap"
            break
        if any(stamp in collected and collected[stamp] != row for stamp, row in ((r["time"], r) for r in rows)):
            reason = "inconsistent_page_basis"
            break
        oldest = min(collected) if collected else None
        if oldest is not None and rows[0]["time"] >= oldest:
            reason = "source_history_exhausted"
            break
        collected.update((row["time"], row) for row in rows)
        if len(collected) >= wanted:
            reason = "requested_count_reached"
            break
        if boundary:
            reason = boundary
            break
        end = datetime.fromtimestamp(rows[0]["time"], zone).date().isoformat()
    rows = sorted(collected.values(), key=lambda row: row["time"])[-wanted:]
    if len(rows) < 2:
        return None
    result = {"rows": rows, "history_complete": len(rows) >= wanted,
              "history_start": rows[0]["time"], "history_end": rows[-1]["time"],
              "coverage_reason": reason, "history_pages": pages,
              "volume_unit": "shares", "volume_adjustment": "historical_session_shares",
              "price_adjustment": adjust, "timestamp_convention": "session_date_at_16_local",
              "source_symbol": code, "exchange_timezone": zone.key}
    _cache_set(key, deepcopy(result))
    return result
