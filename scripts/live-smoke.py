#!/usr/bin/env python3
"""Call analyze_kline through the real stdio MCP protocol."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import quote, urlparse
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
            manifest = json.loads(Path(".runtime/chart-session.json").read_text(encoding="utf-8"))
            service_url = str(manifest.get("service_url") or "")
            parsed_service = urlparse(service_url)
            if parsed_service.scheme != "http" or parsed_service.hostname not in {"127.0.0.1", "localhost"}:
                raise SystemExit("missing loopback chart session service")
            if manifest.get("session") != data.get("chart_session"):
                raise SystemExit("runtime chart session does not match MCP result")
            session_url = f"{service_url}/api/session/{quote(str(data['chart_session']))}"
            with urlopen(session_url, timeout=5) as response:  # noqa: S310
                chart_session = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or chart_session.get("ok") is not True:
                raise SystemExit("native chart session API is unavailable")

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
                "chart_session": data.get("chart_session"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main_async())
