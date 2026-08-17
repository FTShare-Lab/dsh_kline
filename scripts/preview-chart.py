#!/usr/bin/env python3
"""Start a long-running chart session for local browser verification."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def _demo_rows(count: int = 180) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    for index in range(count):
        trend = 300 + index * 0.35
        cycle = ((index % 18) - 9) * 0.9
        close = trend + cycle
        rows.append(
            {
                "time": 1_735_689_600 + index * 86_400,
                "open": close - 1.8,
                "high": close + 4.2,
                "low": close - 4.7,
                "close": close,
                "volume": 12_000_000 + (index % 15) * 1_300_000,
            }
        )
    return rows


async def _publish(symbol: str, *, demo: bool) -> str:
    if demo:
        rows = _demo_rows()
        original_fetch = server.fetch_candles
        server.fetch_candles = lambda requested, **_kwargs: {
            "ok": True,
            "symbol": requested,
            "name": "dsh_kline Visual QA",
            "interval": "day",
            "adjust": "none",
            "rows": rows,
            "source": "local-visual-fixture",
            "status": "fixture",
            "as_of": rows[-1]["time"],
            "freshness": "visual_qa",
        }
        try:
            result = await server.analyze_kline(
                symbol,
                limit=160,
                indicators=["ma", "vol", "macd", "rsi", "boll", "atr", "vwap"],
                metrics=["rsi", "atr"],
            )
        finally:
            server.fetch_candles = original_fetch
    else:
        result = await server.analyze_kline(
            symbol,
            limit=220,
            indicators=["ma", "vol", "macd", "rsi", "boll", "atr", "vwap"],
            metrics=["rsi", "atr"],
        )
    if result.isError:
        raise RuntimeError(result.content[0].text)
    return str(result.structuredContent["chart_url"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Start a dsh_kline chart preview")
    parser.add_argument("symbol", nargs="?", default="00700.HK")
    parser.add_argument("--demo", action="store_true", help="Use deterministic local candles for visual QA")
    args = parser.parse_args()

    url = asyncio.run(_publish(args.symbol, demo=args.demo))
    print(url, flush=True)
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_args: stopped.set())
    stopped.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
