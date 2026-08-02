"""
vdb_handlers.py — MCP tool definitions and handlers for VDB tools
"""

import re
from pathlib import Path
from typing import Annotated

import mcp.types as types
from mcp.server import MCPServer
from mcp.shared.exceptions import MCPError
from pydantic import Field

from vdb_tools import VdbParseError, read_vdb_inspect
from vdb_clips import VdbStitchError, stitch_vdb_volume_usd

_VDB_FRAME_RE = re.compile(r"^(.*)\.(\d+)\.vdb$", re.IGNORECASE)


def register(mcp: MCPServer) -> None:
    mcp.tool()(vdb_inspect)
    mcp.tool()(vdb_stitch_volume_usd)
    mcp.tool()(vdb_list_sequence)


def vdb_inspect(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a .vdb file")],
) -> dict:
    """Parse the header of an OpenVDB (.vdb) file and return its grids (name, raw grid type, friendly type label, instance parent) plus file-level metadata. Uses only the Python standard library — no pyopenvdb or Houdini required. No voxel data is loaded."""
    try:
        return read_vdb_inspect(path)
    except FileNotFoundError as e:
        raise MCPError(types.INVALID_PARAMS, str(e)) from e
    except VdbParseError as e:
        raise MCPError(types.INVALID_REQUEST, str(e)) from e


def vdb_stitch_volume_usd(
    filepath_template: Annotated[str, Field(min_length=1, description="Per-frame template; supports {frame:04d} or $F4 format.")],
    output_path: Annotated[str, Field(min_length=1, description="Absolute output path (.usd / .usda / .usdc). Must not already exist.")],
    frame_range: Annotated[tuple[int, int], Field(description="[start, end] frame range (inclusive).")],
    volume_name: Annotated[str, Field(min_length=1, description="Name of the UsdVol.Volume prim (single path segment, no slashes).")],
    parent_primpath: Annotated[str, Field(min_length=1, description="Absolute USD path to the parent Xform, e.g. '/scene'. Created if missing.")],
    probe_frame: Annotated[int | None, Field(description="Frame used to detect grids. Defaults to start of frame_range.")] = None,
    grids: Annotated[list[str] | None, Field(description="Explicit grid names to include. Defaults to all grids from probe.")] = None,
    strict: Annotated[bool, Field(description="Abort if any source file is missing. Default: false.")] = False,
) -> dict:
    """Stitch a numbered .vdb sequence into a single USD file containing a UsdVol.Volume with one UsdVol.OpenVDBAsset per grid. The filePath, fieldName, and fieldIndex attributes are time-sampled across frame_range. Grids are auto-detected from the probe frame unless an explicit list is given. No Houdini required. This tool writes files to disk."""
    try:
        return stitch_vdb_volume_usd(
            filepath_template=filepath_template,
            output_path=output_path,
            frame_range=frame_range,
            volume_name=volume_name,
            parent_primpath=parent_primpath,
            probe_frame=probe_frame,
            grids=grids,
            strict=strict,
        )
    except FileNotFoundError as e:
        raise MCPError(types.INVALID_PARAMS, str(e)) from e
    except VdbStitchError as e:
        raise MCPError(types.INVALID_REQUEST, str(e)) from e


def vdb_list_sequence(
    directory: Annotated[str, Field(min_length=1, description="Directory path to scan")],
    pattern: Annotated[str, Field(description="Glob pattern, default '*.vdb'")] = "*.vdb",
) -> dict:
    """Scan a directory for numbered .vdb files and group them into sequences by base name (the filename portion before the frame number). Multiple coexisting sequences in one directory are returned separately. Files whose frame number cannot be extracted are reported in 'unmatched'. No VDB headers are parsed."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise MCPError(types.INVALID_PARAMS, f"directory not found: {directory}")

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

    return {
        "directory":      directory,
        "sequence_count": len(out_sequences),
        "sequences":      out_sequences,
        "unmatched":      unmatched,
    }
