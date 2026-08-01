"""
server.py — houdini-lite MCP server

Aggregates tools from domain-specific handler modules:
  bgeo_handlers  — Houdini .bgeo.sc geometry cache tools
  usd_handlers   — USD scene inspection tools
  vdb_handlers   — OpenVDB volume cache inspection tools
"""

from mcp.server import MCPServer

import bgeo_handlers
import vdb_handlers

app = MCPServer("houdini-lite")

bgeo_handlers.register(app)
vdb_handlers.register(app)


def main():
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
