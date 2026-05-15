"""
bgeo_handlers.py — MCP tool definitions and handlers for Houdini bgeo tools
"""

import json
import math
import re
from pathlib import Path

import mcp.types as types

from bgeo_reader import BgeoHeader, InvalidMagicError, ParseError, parse_header, parse_inspect
from blosc_io import BloscDecompressError, read_first_chunk
from bgeo_clips import BgeoClipsError, stitch_bgeo_clips

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    types.Tool(
        name="bgeo_read_header",
        description=(
            "Read metadata from a Houdini .bgeo.sc geometry cache file "
            "without loading the full geometry. Returns point/prim counts."
        ),
        inputSchema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a .bgeo.sc file",
                }
            },
        },
    ),
    types.Tool(
        name="bgeo_list_sequence",
        description=(
            "Scan a directory for a numbered .bgeo.sc sequence. "
            "Returns frame range, file count, and per-frame file sizes "
            "without reading any geometry data."
        ),
        inputSchema={
            "type": "object",
            "required": ["directory"],
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory path containing the cache sequence",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern, e.g. 'pyro_cache.*.bgeo.sc'. Defaults to '*.bgeo.sc'",
                    "default": "*.bgeo.sc",
                },
            },
        },
    ),
    types.Tool(
        name="bgeo_stitch_usd_clips",
        description=(
            "Stitch per-frame .bgeo.sc cache files into a USD Value Clips stage. "
            "Reads usdconfigpathprefix and usdconfigsampleframe detail attributes "
            "from the .bgeo.sc files to auto-configure primpath and frame mapping. "
            "The output USD file references the original .bgeo.sc files as clip assets — "
            "a Houdini environment (or bgeo USD plugin) is required to load the geometry."
        ),
        inputSchema={
            "type": "object",
            "required": ["filepath_template", "output_path"],
            "properties": {
                "filepath_template": {
                    "type": "string",
                    "description": "Per-frame path template. Supports {frame:04d} or $F4 format.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Absolute output path (.usd / .usda / .usdc)",
                },
                "frame_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "[start, end] frame range. If omitted, auto-detected from usdconfigsampleframe attributes.",
                },
                "primpath": {
                    "type": "string",
                    "description": "Prim path on the output stage. If omitted, auto-detected from usdconfigpathprefix.",
                },
                "scene_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Scene timeline range [start, end]. Defaults to frame_range.",
                },
                "loop": {
                    "type": "boolean",
                    "description": "Loop file frames to fill scene_range. Default: false",
                    "default": False,
                },
                "clip_set": {
                    "type": "string",
                    "description": 'USD Clip Set name. Default: "default"',
                    "default": "default",
                },
                "strict": {
                    "type": "boolean",
                    "description": "Abort if any source file is missing. Default: false",
                    "default": False,
                },
                "gen_topology": {
                    "type": "boolean",
                    "description": "Auto-generate topology.usd from bgeo prim paths. Default: true",
                    "default": True,
                },
                "gen_manifest": {
                    "type": "boolean",
                    "description": "Auto-generate manifest.usd from bgeo point attributes. Default: true",
                    "default": True,
                },
                "probe_frame": {
                    "type": "integer",
                    "description": "Frame number to use as probe for topology/manifest. Defaults to first frame.",
                },
                "probe_file": {
                    "type": "string",
                    "description": "Absolute path to a specific .bgeo.sc to use as probe. Overrides probe_frame.",
                },
                "fps": {
                    "type": "number",
                    "description": "Output stage FPS. Default: 24",
                    "default": 24.0,
                },
            },
        },
    ),
    types.Tool(
        name="bgeo_inspect",
        description=(
            "Inspect a Houdini .bgeo.sc geometry cache file and return rich metadata "
            "without loading the full geometry. Returns point/prim/vertex counts, "
            "all attribute definitions (name, size, storage, values) for all four "
            "scopes (point, prim, vertex, detail), primitive types, prim paths, "
            "and file info (software, date, timetocook, attribute_summary). "
            "Reads only the first Blosc chunk — fast even for multi-GB files."
        ),
        inputSchema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a .bgeo.sc file",
                }
            },
        },
    ),
]

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

async def call_bgeo_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "bgeo_read_header":
        return await _handle_read_header(arguments)
    if name == "bgeo_list_sequence":
        return await _handle_list_sequence(arguments)
    if name == "bgeo_stitch_usd_clips":
        return await _handle_stitch_bgeo_clips(arguments)
    if name == "bgeo_inspect":
        return await _handle_inspect(arguments)
    raise ValueError(f"unknown bgeo tool: {name}")

# ---------------------------------------------------------------------------
# bgeo_read_header
# ---------------------------------------------------------------------------

def _header_to_dict(h: BgeoHeader, path: str) -> dict:
    return {
        "path": path,
        "version": h.version,
        "npoints": h.npoints,
        "nprims": h.nprims,
    }


async def _handle_read_header(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    try:
        raw = read_first_chunk(path)
        header = parse_header(raw)
        result = _header_to_dict(header, path)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except FileNotFoundError:
        raise ValueError(f"file not found: {path}")
    except InvalidMagicError:
        raise ValueError("invalid bgeo magic")
    except BloscDecompressError:
        raise ValueError("blosc decompression failed")
    except ParseError as e:
        raise ValueError(f"bgeo parse error: {e}")

# ---------------------------------------------------------------------------
# bgeo_inspect
# ---------------------------------------------------------------------------

async def _handle_inspect(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    try:
        raw = read_first_chunk(path)
        result = parse_inspect(raw)
        result["path"] = path
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except FileNotFoundError:
        raise ValueError(f"file not found: {path}")
    except InvalidMagicError:
        raise ValueError("invalid bgeo magic")
    except BloscDecompressError:
        raise ValueError("blosc decompression failed")
    except ParseError as e:
        raise ValueError(f"bgeo parse error: {e}")

# ---------------------------------------------------------------------------
# bgeo_list_sequence
# ---------------------------------------------------------------------------

_FRAME_RE = re.compile(r"\.(\d+)\.bgeo\.sc$", re.IGNORECASE)


def _extract_frame(filename: str):
    """Extract frame number from filename; returns None if not found."""
    m = _FRAME_RE.search(filename)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)", filename)
    if m:
        return int(m.group(1))
    return None


async def _handle_list_sequence(arguments: dict) -> list[types.TextContent]:
    directory = arguments.get("directory", "")
    pattern = arguments.get("pattern", "*.bgeo.sc")

    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise ValueError(f"directory not found: {directory}")

    files = sorted(dir_path.glob(pattern))
    if not files:
        result = {
            "directory": directory,
            "frame_count": 0,
            "frame_range": None,
            "total_size_bytes": 0,
            "frames": [],
        }
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    frames = []
    total_size = 0
    frame_numbers = []

    for f in files:
        size = f.stat().st_size
        total_size += size
        frame_num = _extract_frame(f.name)
        if frame_num is not None:
            frame_numbers.append(frame_num)
        frames.append({
            "frame": frame_num,
            "filename": f.name,
            "size_bytes": size,
        })

    frame_range = None
    if frame_numbers:
        frame_range = {"first": min(frame_numbers), "last": max(frame_numbers)}

    result = {
        "directory": directory,
        "frame_count": len(frames),
        "frame_range": frame_range,
        "total_size_bytes": total_size,
        "frames": frames,
    }
    return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


# ---------------------------------------------------------------------------
# bgeo_stitch_usd_clips
# ---------------------------------------------------------------------------

async def _handle_stitch_bgeo_clips(arguments: dict) -> list[types.TextContent]:
    filepath_template = arguments.get("filepath_template", "")
    output_path       = arguments.get("output_path", "")

    if not filepath_template or not output_path:
        raise ValueError("[-32602] filepath_template and output_path are required")

    frame_range_raw  = arguments.get("frame_range")
    frame_range      = (int(frame_range_raw[0]), int(frame_range_raw[1])) if isinstance(frame_range_raw, list) and len(frame_range_raw) == 2 else None
    scene_range_raw  = arguments.get("scene_range")
    scene_range      = (int(scene_range_raw[0]), int(scene_range_raw[1])) if isinstance(scene_range_raw, list) and len(scene_range_raw) == 2 else None
    primpath         = arguments.get("primpath")
    loop             = bool(arguments.get("loop", False))
    clip_set         = str(arguments.get("clip_set", "default"))
    strict           = bool(arguments.get("strict", False))
    gen_topology     = bool(arguments.get("gen_topology", True))
    gen_manifest     = bool(arguments.get("gen_manifest", True))
    probe_frame_raw  = arguments.get("probe_frame")
    probe_frame      = int(probe_frame_raw) if probe_frame_raw is not None else None
    probe_file       = arguments.get("probe_file")
    fps_raw          = arguments.get("fps", 24.0)
    try:
        fps = float(fps_raw)
    except (TypeError, ValueError) as err:
        raise ValueError(f"[-32602] invalid fps: {fps_raw!r}") from err
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError(f"[-32602] fps must be a finite positive number, got: {fps!r}")

    try:
        result = stitch_bgeo_clips(
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
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except FileNotFoundError as e:
        raise ValueError(f"[-32602] {e}")
    except BgeoClipsError as e:
        raise ValueError(f"[-32600] {e}")
