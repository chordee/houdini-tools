"""
vdb_handlers.py — MCP tool definitions and handlers for VDB tools
"""

import json
import re
from pathlib import Path

import mcp.types as types

from vdb_tools import VdbParseError, read_vdb_inspect
from vdb_clips import VdbStitchError, stitch_vdb_volume_usd

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
        name="vdb_stitch_volume_usd",
        description=(
            "Stitch a numbered .vdb sequence into a single USD file "
            "containing a UsdVol.Volume with one UsdVol.OpenVDBAsset per "
            "grid. The filePath, fieldName, and fieldIndex attributes are "
            "time-sampled across frame_range. Grids are auto-detected from "
            "the probe frame unless an explicit list is given. No Houdini "
            "required. This tool writes files to disk."
        ),
        inputSchema={
            "type": "object",
            "required": [
                "filepath_template",
                "output_path",
                "frame_range",
                "volume_name",
                "parent_primpath",
            ],
            "properties": {
                "filepath_template": {
                    "type": "string",
                    "description": "Per-frame template; supports {frame:04d} or $F4 format.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Absolute output path (.usd / .usda / .usdc). Must not already exist.",
                },
                "frame_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "[start, end] frame range (inclusive).",
                },
                "volume_name": {
                    "type": "string",
                    "description": "Name of the UsdVol.Volume prim (single path segment, no slashes).",
                },
                "parent_primpath": {
                    "type": "string",
                    "description": "Absolute USD path to the parent Xform, e.g. '/scene'. Created if missing.",
                },
                "probe_frame": {
                    "type": "integer",
                    "description": "Frame used to detect grids. Defaults to start of frame_range.",
                },
                "grids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit grid names to include. Defaults to all grids from probe.",
                },
                "strict": {
                    "type": "boolean",
                    "description": "Abort if any source file is missing. Default: false.",
                    "default": False,
                },
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
    if name == "vdb_stitch_volume_usd":
        return await _handle_stitch_volume_usd(arguments)
    raise ValueError(f"unknown vdb tool: {name}")


# ---------------------------------------------------------------------------
# vdb_inspect
# ---------------------------------------------------------------------------

async def _handle_inspect(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    if not path:
        raise ValueError("[-32602] 'path' is required")
    try:
        result = read_vdb_inspect(path)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except FileNotFoundError as e:
        raise ValueError(f"[-32602] {e}") from e
    except VdbParseError as e:
        raise ValueError(f"[-32600] {e}") from e


# ---------------------------------------------------------------------------
# vdb_stitch_volume_usd
# ---------------------------------------------------------------------------

async def _handle_stitch_volume_usd(arguments: dict) -> list[types.TextContent]:
    filepath_template = arguments.get("filepath_template", "")
    output_path       = arguments.get("output_path", "")
    frame_range_raw   = arguments.get("frame_range")
    volume_name       = arguments.get("volume_name", "")
    parent_primpath   = arguments.get("parent_primpath", "")

    if not filepath_template or not output_path or not volume_name or not parent_primpath:
        raise ValueError(
            "[-32602] filepath_template, output_path, volume_name, "
            "and parent_primpath are required"
        )
    if not isinstance(frame_range_raw, list) or len(frame_range_raw) != 2:
        raise ValueError("[-32602] frame_range must be a [start, end] integer array")

    frame_range     = (int(frame_range_raw[0]), int(frame_range_raw[1]))
    probe_frame_raw = arguments.get("probe_frame")
    probe_frame     = int(probe_frame_raw) if probe_frame_raw is not None else None
    grids_raw       = arguments.get("grids")
    grids           = [str(g) for g in grids_raw] if isinstance(grids_raw, list) else None
    strict          = bool(arguments.get("strict", False))

    try:
        result = stitch_vdb_volume_usd(
            filepath_template=filepath_template,
            output_path=output_path,
            frame_range=frame_range,
            volume_name=volume_name,
            parent_primpath=parent_primpath,
            probe_frame=probe_frame,
            grids=grids,
            strict=strict,
        )
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except FileNotFoundError as e:
        raise ValueError(f"[-32602] {e}") from e
    except VdbStitchError as e:
        raise ValueError(f"[-32600] {e}") from e


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
