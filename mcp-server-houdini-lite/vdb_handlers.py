"""
vdb_handlers.py — MCP tool definitions and handlers for VDB tools
"""

import json
import re
from pathlib import Path

import mcp.types as types

from vdb_tools import VdbParseError, read_vdb_inspect

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    types.Tool(
        name="vdb_inspect",
        description=(
            "Parse the header of an OpenVDB (.vdb) file and return its grids "
            "(name, raw grid type, friendly type label, instance parent) plus "
            "file-level metadata. Uses only the Python standard library — no "
            "pyopenvdb or Houdini required. No voxel data is loaded."
        ),
        inputSchema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a .vdb file",
                }
            },
        },
    ),
    types.Tool(
        name="vdb_list_sequence",
        description=(
            "Scan a directory for numbered .vdb files and group them into "
            "sequences by base name (the filename portion before the frame "
            "number). Multiple coexisting sequences in one directory are "
            "returned separately. Files whose frame number cannot be extracted "
            "are reported in 'unmatched'. No VDB headers are parsed."
        ),
        inputSchema={
            "type": "object",
            "required": ["directory"],
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory path to scan",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern, default '*.vdb'",
                    "default": "*.vdb",
                },
            },
        },
    ),
]

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

async def call_vdb_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "vdb_inspect":
        return await _handle_inspect(arguments)
    if name == "vdb_list_sequence":
        return await _handle_list_sequence(arguments)
    raise ValueError(f"unknown vdb tool: {name}")


# ---------------------------------------------------------------------------
# vdb_inspect
# ---------------------------------------------------------------------------

async def _handle_inspect(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    try:
        result = read_vdb_inspect(path)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except FileNotFoundError as e:
        raise ValueError(f"[-32602] {e}")
    except VdbParseError as e:
        raise ValueError(f"[-32600] {e}")


# ---------------------------------------------------------------------------
# vdb_list_sequence
# ---------------------------------------------------------------------------

_VDB_FRAME_RE = re.compile(r"^(.*)\.(\d+)\.vdb$", re.IGNORECASE)


async def _handle_list_sequence(arguments: dict) -> list[types.TextContent]:
    directory = arguments.get("directory", "")
    pattern = arguments.get("pattern", "*.vdb")

    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise ValueError(f"[-32602] directory not found: {directory}")

    files = sorted(dir_path.glob(pattern))
    sequences: dict[str, list[dict]] = {}
    unmatched: list[dict] = []

    for f in files:
        size = f.stat().st_size
        m = _VDB_FRAME_RE.match(f.name)
        if m:
            base = m.group(1)
            frame = int(m.group(2))
            sequences.setdefault(base, []).append({
                "frame":      frame,
                "filename":   f.name,
                "size_bytes": size,
            })
        else:
            unmatched.append({"filename": f.name, "size_bytes": size})

    out_sequences = []
    for base in sorted(sequences.keys()):
        frames = sorted(sequences[base], key=lambda x: x["frame"])
        total_size = sum(x["size_bytes"] for x in frames)
        frame_numbers = [x["frame"] for x in frames]
        out_sequences.append({
            "base_name":        base,
            "frame_count":      len(frames),
            "frame_range":      {"first": min(frame_numbers), "last": max(frame_numbers)},
            "total_size_bytes": total_size,
            "frames":           frames,
        })

    result = {
        "directory":      directory,
        "sequence_count": len(out_sequences),
        "sequences":      out_sequences,
        "unmatched":      unmatched,
    }
    return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
