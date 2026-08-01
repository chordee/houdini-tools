"""
server.py — houdini-lite MCP server

Aggregates tools from domain-specific handler modules:
  bgeo_handlers  — Houdini .bgeo.sc geometry cache tools
  usd_handlers   — USD scene inspection tools
  vdb_handlers   — OpenVDB volume cache inspection tools
"""

from mcp.server import MCPServer

import vdb_handlers

app = MCPServer("houdini-lite")

vdb_handlers.register(app)


def main():
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
