"""
server.py — houdini-lite MCP server

Aggregates tools from domain-specific handler modules:
  bgeo_handlers  — Houdini .bgeo.sc geometry cache tools
  usd_handlers   — USD scene inspection tools
"""

import asyncio

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from bgeo_handlers import TOOLS as BGEO_TOOLS, call_bgeo_tool
from usd_handlers import TOOLS as USD_TOOLS, call_usd_tool

app = Server("houdini-lite")

TOOLS = BGEO_TOOLS + USD_TOOLS

_BGEO_TOOL_NAMES = {t.name for t in BGEO_TOOLS}
_USD_TOOL_NAMES  = {t.name for t in USD_TOOLS}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name in _BGEO_TOOL_NAMES:
        return await call_bgeo_tool(name, arguments)
    if name in _USD_TOOL_NAMES:
        return await call_usd_tool(name, arguments)
    raise ValueError(f"unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
