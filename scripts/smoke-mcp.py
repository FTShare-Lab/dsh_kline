#!/usr/bin/env python3
"""Discover ft-kline-view through the MCP client protocol."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    server = StdioServerParameters(
        command=args.python,
        args=[str(root / "server.py")],
        cwd=str(root),
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            names = {tool.name for tool in result.tools}

    required = {"fetch_candles", "calc_metrics", "draw_kline", "doctor_view"}
    missing = sorted(required - names)
    if missing:
        raise SystemExit(f"missing required MCP tools: {', '.join(missing)}")

    print(
        "ft-kline-view MCP discovery OK: "
        f"{len(names)} tools; required={', '.join(sorted(required))}"
    )


if __name__ == "__main__":
    asyncio.run(main_async())
