#!/usr/bin/env python3
"""Live FTShare regression for the three supported equity markets."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.fetch import fetch_candles  # noqa: E402


def main() -> int:
    checks = [
        ("HK", "00700.HK"),
        ("US", "NVDA.US"),
        ("CN", "600519.XSHG"),
    ]
    summaries: list[dict[str, object]] = []
    for market, symbol in checks:
        result = fetch_candles(symbol, interval="day", limit=30, adjust="none")
        if not result.get("ok") or len(result.get("rows") or []) < 2:
            raise RuntimeError(f"{market} regression failed: {result.get('error') or result.get('message')}")
        summaries.append(
            {
                "market": market,
                "symbol": result.get("symbol"),
                "bars": len(result.get("rows") or []),
                "source": result.get("source"),
                "status": result.get("status"),
            }
        )

    invalid = fetch_candles("NOT A SYMBOL", interval="day")
    unsupported = fetch_candles("00700.HK", interval="hour")
    if invalid.get("error") != "invalid_symbol":
        raise RuntimeError(f"invalid-symbol regression failed: {invalid}")
    if unsupported.get("error") != "unsupported_interval":
        raise RuntimeError(f"unsupported-interval regression failed: {unsupported}")

    print(json.dumps({"ok": True, "markets": summaries, "errors": [invalid["error"], unsupported["error"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
