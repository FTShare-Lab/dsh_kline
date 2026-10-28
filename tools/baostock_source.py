"""Bounded, key-less A-share daily candle fallback via BaoStock's public SDK.

The SDK keeps a process-global socket and may wait indefinitely for a reply.
Run each request in a short-lived child process so a failing free service cannot
block the MCP server or contaminate another chart's provider connection.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SOURCE = "baostock_free"
SOURCE_URL = "https://www.baostock.com/"
_SHANGHAI = timezone(timedelta(hours=8))
_MAX_ROWS = 10_000
_TIMEOUT_SECONDS = 12
_FIELDS = "date,code,open,high,low,close,volume"
_ADJUST_FLAGS = {"none": "3", "forward": "2", "backward": "1"}
_CACHE_TTL_SECONDS = 90
_CACHE_MAX_ENTRIES = 64
_cache: dict[tuple[str, int, str], tuple[float, list[dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


def source_status() -> dict[str, Any]:
    """Report installed capability without pretending to probe connectivity."""
    return {
        "installed": importlib.util.find_spec("baostock") is not None,
        "capabilities": ["cn_a_share_historical_daily_candles"],
        "requires_key": False,
        "reachability": "not_probed",
        "source_url": SOURCE_URL,
    }


def eligible_stock_code(symbol: str) -> str | None:
    """Require an explicit exchange and an A-share stock prefix.

    This deliberately excludes indices, funds, B shares and bare codes. The
    BaoStock query does not accept our canonical symbol suffixes directly.
    """
    value = str(symbol or "").strip().upper()
    match = re.fullmatch(r"(\d{6})\.(XSHG|XSHE)", value)
    if not match:
        return None
    code, market = match.groups()
    if market == "XSHG" and code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh.{code}"
    if market == "XSHE" and code.startswith(("000", "001", "002", "003", "300", "301", "302")):
        return f"sz.{code}"
    return None


def _normalize_rows(raw_rows: Any, expected_code: str) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list) or len(raw_rows) > _MAX_ROWS:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in raw_rows:
        if not isinstance(raw, list) or len(raw) != 7 or raw[1] != expected_code:
            return []
        try:
            date = datetime.strptime(raw[0], "%Y-%m-%d").replace(hour=15, tzinfo=_SHANGHAI)
            stamp = int(date.timestamp())
            opened, high, low, closed, volume = map(float, raw[2:])
        except (TypeError, ValueError, OverflowError):
            return []
        if (
            stamp in seen or not all(map(math.isfinite, (opened, high, low, closed, volume)))
            or min(opened, high, low, closed) <= 0 or volume < 0
            or high < max(opened, low, closed) or low > min(opened, high, closed)
        ):
            return []
        seen.add(stamp)
        rows.append({"time": stamp, "open": opened, "high": high, "low": low, "close": closed, "volume": volume})
    rows.sort(key=lambda item: item["time"])
    return rows


def fetch_stock_daily(symbol: str, *, limit: int, adjust: str) -> list[dict[str, Any]] | None:
    """Return recent normalized daily OHLCV, or None without changing state."""
    code = eligible_stock_code(symbol)
    if not code or adjust not in _ADJUST_FLAGS:
        return None
    wanted = max(2, min(int(limit), 4000))
    cache_key = (code, wanted, adjust)
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return deepcopy(cached[1])
    request = {"code": code, "limit": wanted, "adjustflag": _ADJUST_FLAGS[adjust]}
    # The fallback needs no account credential. Do not inherit the host's
    # FTShare key, DSH tokens, or unrelated secrets into the child process.
    child_env = {
        key: value for key, value in os.environ.items()
        if not re.search(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", key, re.IGNORECASE)
    }
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            input=json.dumps(request), text=True, capture_output=True,
            timeout=_TIMEOUT_SECONDS, check=False, env=child_env,
        )
        if process.returncode != 0 or len(process.stdout) > 1_500_000:
            return None
        payload = json.loads(process.stdout)
        rows = _normalize_rows(payload.get("rows"), code)
        if len(rows) < 2:
            return None
        result = rows[-wanted:]
        with _cache_lock:
            if len(_cache) >= _CACHE_MAX_ENTRIES:
                oldest = min(_cache, key=lambda item: _cache[item][0])
                _cache.pop(oldest, None)
            _cache[cache_key] = (time.monotonic(), result)
        return deepcopy(result)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return None


def _worker() -> int:
    """Isolated SDK session; all SDK chatter stays out of the JSON protocol."""
    try:
        request = json.load(sys.stdin)
        code = str(request["code"])
        wanted = int(request["limit"])
        flag = str(request["adjustflag"])
        if not re.fullmatch(r"(?:sh|sz)\.\d{6}", code) or not 2 <= wanted <= 4000 or flag not in _ADJUST_FLAGS.values():
            return 1
        import baostock as bs

        socket.setdefaulttimeout(5)
        end = datetime.now(_SHANGHAI).date()
        start = end - timedelta(days=min(365 * 30, max(365, int(wanted * 1.8))))
        with contextlib.redirect_stdout(io.StringIO()):
            login = bs.login()
            if str(login.error_code) != "0":
                return 1
            try:
                result = bs.query_history_k_data_plus(
                    code, _FIELDS, start_date=start.isoformat(), end_date=end.isoformat(),
                    frequency="d", adjustflag=flag,
                )
                if str(result.error_code) != "0" or list(result.fields or []) != _FIELDS.split(","):
                    return 1
                rows = []
                while result.next():
                    if len(rows) >= _MAX_ROWS:
                        return 1
                    rows.append(result.get_row_data())
            finally:
                bs.logout()
        sys.stdout.write(json.dumps({"rows": rows}, separators=(",", ":")))
        return 0
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 - child must fail closed
        return 1


if __name__ == "__main__":
    raise SystemExit(_worker() if sys.argv[1:] == ["--worker"] else 1)
