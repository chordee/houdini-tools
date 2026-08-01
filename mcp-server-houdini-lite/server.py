"""
server.py — houdini-lite MCP server

Aggregates tools from domain-specific handler modules:
  bgeo_handlers  — Houdini .bgeo.sc geometry cache tools
  usd_handlers   — USD scene inspection tools
  vdb_handlers   — OpenVDB volume cache inspection tools
"""

import asyncio

import mcp.types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError

from bgeo_handlers import TOOLS as BGEO_TOOLS, call_bgeo_tool
from usd_handlers import TOOLS as USD_TOOLS, call_usd_tool
from vdb_handlers import TOOLS as VDB_TOOLS, call_vdb_tool

TOOLS = BGEO_TOOLS + USD_TOOLS + VDB_TOOLS

_BGEO_TOOL_NAMES = {t.name for t in BGEO_TOOLS}
_USD_TOOL_NAMES  = {t.name for t in USD_TOOLS}
_VDB_TOOL_NAMES  = {t.name for t in VDB_TOOLS}


async def list_tools(
    ctx: ServerRequestContext,
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def call_tool(
    ctx: ServerRequestContext,
    params: types.CallToolRequestParams,
) -> types.CallToolResult:
    name = params.name
    arguments = params.arguments or {}

    if name in _BGEO_TOOL_NAMES:
        content = await call_bgeo_tool(name, arguments)
    elif name in _USD_TOOL_NAMES:
        content = await call_usd_tool(name, arguments)
    elif name in _VDB_TOOL_NAMES:
        content = await call_vdb_tool(name, arguments)
    else:
        raise MCPError(types.METHOD_NOT_FOUND, f"unknown tool: {name}")

    return types.CallToolResult(content=content)


app = Server("houdini-lite", on_list_tools=list_tools, on_call_tool=call_tool)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
