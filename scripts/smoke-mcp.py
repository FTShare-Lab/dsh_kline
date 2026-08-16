#!/usr/bin/env python3
"""Discover the standalone dsh_kline MCP server through stdio."""

from __future__ import annotations

import argparse
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    args = parser.parse_args()

    server = StdioServerParameters(
        command=args.python,
        args=["server.py"],
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            names = {tool.name for tool in result.tools}

    required = {"analyze_kline", "fetch_candles", "calc_metrics", "health"}
    missing = sorted(required - names)
    if missing:
        raise SystemExit(f"missing required MCP tools: {', '.join(missing)}")

    print(
        "standalone dsh_kline MCP discovery OK: "
        f"{len(names)} tools; required={', '.join(sorted(required))}"
    )


if __name__ == "__main__":
    asyncio.run(main_async())
