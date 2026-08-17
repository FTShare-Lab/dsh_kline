#!/usr/bin/env python3
"""Call analyze_kline through the real stdio MCP protocol."""

from __future__ import annotations

import argparse
import asyncio
import json
from urllib.parse import urlparse
from urllib.request import urlopen

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--symbol", default="00700.HK")
    parser.add_argument("--limit", type=int, default=60)
    args = parser.parse_args()

    server = StdioServerParameters(command=args.python, args=["server.py"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "analyze_kline",
                {
                    "symbol": args.symbol,
                    "interval": "day",
                    "limit": args.limit,
                    "indicators": ["ma", "vol", "macd", "rsi", "boll", "atr", "vwap"],
                    "metrics": ["rsi", "atr"],
                },
            )

            data = result.structuredContent or {}
            if result.isError or data.get("ok") is False:
                detail = result.content[0].text if result.content else data.get("message") or data.get("error")
                raise SystemExit(f"analyze_kline failed: {detail}")
            chart_url = str(data.get("chart_url") or "")
            if urlparse(chart_url).scheme != "http" or urlparse(chart_url).hostname not in {"127.0.0.1", "localhost"}:
                raise SystemExit(f"missing loopback chart URL: {chart_url}")
            with urlopen(chart_url, timeout=5) as response:  # noqa: S310
                chart_html = response.read().decode("utf-8")
            if response.status != 200 or "window.__DSH_CHART_SESSION__=" not in chart_html:
                raise SystemExit("chart session did not return standalone HTML")

    if data.get("source") != "ftshare":
        raise SystemExit(f"unexpected source: {data.get('source')}")
    if data.get("count") != args.limit:
        raise SystemExit(f"expected {args.limit} bars, got {data.get('count')}")
    indicator_last = data.get("indicator_last") or {}
    if indicator_last.get("rsi") is None or not isinstance(indicator_last.get("macd"), dict):
        raise SystemExit("missing RSI or MACD values")

    print(
        json.dumps(
            {
                "ok": True,
                "symbol": data.get("symbol"),
                "name": data.get("name"),
                "source": data.get("source"),
                "count": data.get("count"),
                "status": data.get("status"),
                "as_of": data.get("as_of"),
                "latest": data.get("latest"),
                "indicator_last": indicator_last,
                "chart_url": data.get("chart_url"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main_async())
