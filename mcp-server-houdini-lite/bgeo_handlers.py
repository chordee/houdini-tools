"""
bgeo_handlers.py — MCP tool definitions and handlers for Houdini bgeo tools
"""

import re
from pathlib import Path
from typing import Annotated

import mcp.types as types
from mcp.server import MCPServer
from mcp.shared.exceptions import MCPError
from pydantic import Field

from bgeo_reader import BgeoHeader, InvalidMagicError, ParseError, parse_header, parse_inspect
from blosc_io import BloscDecompressError, read_first_chunk
from bgeo_clips import BgeoClipsError, stitch_bgeo_clips

_BGEO_FRAME_RE = re.compile(r"^(.*)\.(\d+)\.bgeo\.sc$", re.IGNORECASE)


def register(mcp: MCPServer) -> None:
    mcp.tool()(bgeo_read_header)
    mcp.tool()(bgeo_list_sequence)
    mcp.tool()(bgeo_stitch_usd_clips)
    mcp.tool()(bgeo_inspect)


def _header_to_dict(h: BgeoHeader, path: str) -> dict:
    return {
        "path": path,
        "version": h.version,
        "npoints": h.npoints,
        "nprims": h.nprims,
    }


def bgeo_read_header(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a .bgeo.sc file")],
) -> dict:
    """Read metadata from a Houdini .bgeo.sc geometry cache file without loading the full geometry. Returns point/prim counts."""
    try:
        raw = read_first_chunk(path)
        header = parse_header(raw)
        return _header_to_dict(header, path)
    except FileNotFoundError as e:
        raise MCPError(types.INVALID_PARAMS, f"file not found: {path}") from e
    except InvalidMagicError as e:
        raise MCPError(types.INVALID_PARAMS, "invalid bgeo magic") from e
    except BloscDecompressError as e:
        raise MCPError(types.INVALID_PARAMS, "blosc decompression failed") from e
    except ParseError as e:
        raise MCPError(types.INVALID_PARAMS, f"bgeo parse error: {e}") from e


def bgeo_list_sequence(
    directory: Annotated[str, Field(min_length=1, description="Directory path containing the cache sequence(s)")],
    pattern: Annotated[str, Field(description="Glob pattern, default '*.bgeo.sc'")] = "*.bgeo.sc",
) -> dict:
    """Scan a directory for numbered .bgeo.sc files and group them into sequences by base name (the filename portion before the frame number). Multiple coexisting sequences in one directory are returned separately. Files whose frame number cannot be extracted are reported in 'unmatched'. No geometry data is read."""
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise MCPError(types.INVALID_PARAMS, f"directory not found: {directory}")

    files = sorted(dir_path.glob(pattern))
    sequences: dict[str, list[dict]] = {}
    unmatched: list[dict] = []

    for f in files:
        size = f.stat().st_size
        m = _BGEO_FRAME_RE.match(f.name)
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


def bgeo_stitch_usd_clips(
    filepath_template: Annotated[str, Field(min_length=1, description="Per-frame path template. Supports {frame:04d} or $F4 format.")],
    output_path: Annotated[str, Field(min_length=1, description="Absolute output path (.usd / .usda / .usdc)")],
    frame_range: Annotated[tuple[int, int] | None, Field(description="[start, end] frame range. If omitted, auto-detected from usdconfigsampleframe attributes.")] = None,
    primpath: Annotated[str | None, Field(description="Prim path on the output stage. If omitted, auto-detected from usdconfigpathprefix.")] = None,
    scene_range: Annotated[tuple[int, int] | None, Field(description="Scene timeline range [start, end]. Defaults to frame_range.")] = None,
    loop: Annotated[bool, Field(description="Loop file frames to fill scene_range. Default: false")] = False,
    clip_set: Annotated[str, Field(description='USD Clip Set name. Default: "default"')] = "default",
    strict: Annotated[bool, Field(description="Abort if any source file is missing. Default: false")] = False,
    gen_topology: Annotated[bool, Field(description="Auto-generate topology.usd from bgeo prim paths. Default: true")] = True,
    gen_manifest: Annotated[bool, Field(description="Auto-generate manifest.usd from bgeo point attributes. Default: true")] = True,
    probe_frame: Annotated[int | None, Field(description="Frame number to use as probe for topology/manifest. Defaults to first frame.")] = None,
    probe_file: Annotated[str | None, Field(description="Absolute path to a specific .bgeo.sc to use as probe. Overrides probe_frame.")] = None,
    fps: Annotated[float, Field(gt=0, allow_inf_nan=False, description="Output stage FPS. Default: 24")] = 24.0,
) -> dict:
    """Stitch per-frame .bgeo.sc cache files into a USD Value Clips stage. Reads usdconfigpathprefix and usdconfigsampleframe detail attributes from the .bgeo.sc files to auto-configure primpath and frame mapping. The output USD file references the original .bgeo.sc files as clip assets — a Houdini environment (or bgeo USD plugin) is required to load the geometry."""
    try:
        return stitch_bgeo_clips(
            filepath_template=filepath_template,
            output_path=output_path,
            frame_range=frame_range,
            primpath=primpath,
            scene_range=scene_range,
            loop=loop,
            clip_set=clip_set,
            strict=strict,
            gen_topology=gen_topology,
            gen_manifest=gen_manifest,
            probe_frame=probe_frame,
            probe_file=probe_file,
            fps=fps,
        )
    except FileNotFoundError as e:
        raise MCPError(types.INVALID_PARAMS, str(e)) from e
    except BgeoClipsError as e:
        raise MCPError(types.INVALID_REQUEST, str(e)) from e


def bgeo_inspect(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a .bgeo.sc file")],
) -> dict:
    """Inspect a Houdini .bgeo.sc geometry cache file and return rich metadata without loading the full geometry. Returns point/prim/vertex counts, all attribute definitions (name, size, storage, values) for all four scopes (point, prim, vertex, detail), primitive types, prim paths, and file info (software, date, timetocook, attribute_summary). Reads only the first Blosc chunk — fast even for multi-GB files."""
    try:
        raw = read_first_chunk(path)
        result = parse_inspect(raw)
        result["path"] = path
        return result
    except FileNotFoundError as e:
        raise MCPError(types.INVALID_PARAMS, f"file not found: {path}") from e
    except InvalidMagicError as e:
        raise MCPError(types.INVALID_PARAMS, "invalid bgeo magic") from e
    except BloscDecompressError as e:
        raise MCPError(types.INVALID_PARAMS, "blosc decompression failed") from e
    except ParseError as e:
        raise MCPError(types.INVALID_PARAMS, f"bgeo parse error: {e}") from e
