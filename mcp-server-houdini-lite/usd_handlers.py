"""
usd_handlers.py — MCP tool definitions and handlers for USD tools
"""

import json

import mcp.types as types

from usd_tools import (
    UsdOpenError,
    read_layer_metadata,
    read_layer_hierarchy,
    read_composed_hierarchy,
    read_composition_arcs,
    replace_anchors,
    read_cameras,
    read_prim_attributes,
    read_attribute_value,
)
from usd_clips import StitchClipsError, stitch_clips

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    types.Tool(
        name="usd_read_layer_metadata",
        description=(
            "Read the customLayerData from a single USD layer file "
            "(.usd, .usda, .usdc, .usdz) without composition. "
            "Returns the file format and the customLayerData dictionary."
        ),
        inputSchema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a USD file",
                }
            },
        },
    ),
    types.Tool(
        name="usd_read_hierarchy",
        description=(
            "Read the prim hierarchy from a single USD layer without composition. "
            "References, sublayers, and payloads are NOT resolved — "
            "only prims defined directly in this file are returned. "
            "Fastest option for a quick structural overview of one file."
        ),
        inputSchema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a USD file",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum hierarchy depth to return (0 = unlimited, 1 = root prims only, etc.)",
                    "default": 0,
                },
            },
        },
    ),
    types.Tool(
        name="usd_read_hierarchy_composed",
        description=(
            "Read the fully composed USD prim hierarchy, resolving all "
            "references and sublayers. Payloads are intentionally not loaded "
            "to keep memory usage low. Use this when you need to see the "
            "complete scene structure across multiple referenced files."
        ),
        inputSchema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a USD file",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum hierarchy depth to return (0 = unlimited)",
                    "default": 0,
                },
            },
        },
    ),
    types.Tool(
        name="usd_read_composition_arcs",
        description=(
            "List the direct composition arcs declared in a single USD layer: "
            "sublayers, references, and payloads. No composition is performed — "
            "only arcs explicitly written in this file are returned. "
            "Use this to understand which other USD files this layer depends on."
        ),
        inputSchema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a USD file",
                }
            },
        },
    ),
    types.Tool(
        name="usd_replace_anchors",
        description=(
            "Replace multiple anchor asset paths (sublayers, references, payloads) "
            "in a single USD layer file in one operation. "
            "Edits the file in-place. "
            "Use usd_read_composition_arcs first to inspect existing anchors."
        ),
        inputSchema={
            "type": "object",
            "required": ["path", "replacements"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a USD file to modify",
                },
                "replacements": {
                    "type": "object",
                    "description": (
                        "Map of {old_asset_path: new_asset_path}. "
                        "Keys must match the exact strings stored in the USD file "
                        "(as returned by usd_read_composition_arcs)."
                    ),
                    "additionalProperties": {"type": "string"},
                },
            },
        },
    ),
    types.Tool(
        name="usd_stitch_clips",
        description=(
            "Stitch per-frame USD cache files into a single USD Value Clips stage. "
            "Automatically generates topology.usd and manifest.usd alongside the output. "
            "Supports frame looping, custom clip sets, and auto-detection of animated child prims."
        ),
        inputSchema={
            "type": "object",
            "required": ["filepath_template", "primpath", "output_path", "frame_range"],
            "properties": {
                "filepath_template": {
                    "type": "string",
                    "description": "Per-frame path template. Supports {frame:04d} or $F4 format.",
                },
                "primpath": {
                    "type": "string",
                    "description": "Target prim path on the stage, e.g. /Geometry",
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
                    "description": "Source file frame range [start, end] (inclusive)",
                },
                "scene_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Scene timeline frame range [start, end]. Defaults to frame_range.",
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
                "clip_primpath": {
                    "type": "string",
                    "description": "Prim path inside clip files. Defaults to primpath.",
                },
                "strict": {
                    "type": "boolean",
                    "description": "Abort if any source file is missing. Default: false",
                    "default": False,
                },
                "gen_topology": {
                    "type": "boolean",
                    "description": "Auto-generate topology.usd. Default: true",
                    "default": True,
                },
                "gen_manifest": {
                    "type": "boolean",
                    "description": "Auto-generate manifest.usd. Default: true",
                    "default": True,
                },
                "probe_frame": {
                    "type": "integer",
                    "description": "Frame used to generate topology/manifest. Defaults to first frame of frame_range.",
                },
                "auto_detect_prim": {
                    "type": "boolean",
                    "description": "Recursively detect animated child prims. Default: true",
                    "default": True,
                },
                "fps": {
                    "type": "number",
                    "description": "Output stage FPS. Auto-detected from probe frame if omitted.",
                },
            },
        },
    ),
    types.Tool(
        name="usd_read_prim_attributes",
        description=(
            "List attributes on a USD prim with progressive disclosure. "
            "Use detail='names' for a fast attribute name overview, "
            "'types' (default) to add type info and array sizes, or "
            "'samples' to also include time sample counts. "
            "Use filter to narrow by name prefix (e.g. 'primvars:'), "
            "and limit to cap the number of attributes returned."
        ),
        inputSchema={
            "type": "object",
            "required": ["path", "prim_path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a USD file",
                },
                "prim_path": {
                    "type": "string",
                    "description": "USD scene path of the prim to inspect (e.g. /Geo/mesh)",
                },
                "detail": {
                    "type": "string",
                    "enum": ["names", "types", "samples"],
                    "default": "types",
                    "description": (
                        "'names' → attribute names only; "
                        "'types' → add type_name, variability, is_array, array_size; "
                        "'samples' → also add has_time_samples, time_sample_count"
                    ),
                },
                "filter": {
                    "type": "string",
                    "description": "Return only attributes whose name starts with this prefix (e.g. 'primvars:')",
                },
                "limit": {
                    "type": "integer",
                    "default": 200,
                    "description": "Maximum number of attributes to return (default 200)",
                },
                "frame": {
                    "type": "number",
                    "description": "Time code used to evaluate array_size. Omit for default time.",
                },
                "load_payloads": {
                    "type": "boolean",
                    "default": False,
                    "description": "Load USD payloads. Required if the target prim is defined inside a payload. Default: false.",
                },
            },
        },
    ),
    types.Tool(
        name="usd_read_attribute_value",
        description=(
            "Read the value of a single named attribute on a USD prim. "
            "For array attributes, results are truncated to max_elements (default 100) "
            "to avoid large payloads; check array_total and array_truncated in the response."
        ),
        inputSchema={
            "type": "object",
            "required": ["path", "prim_path", "attribute_name"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a USD file",
                },
                "prim_path": {
                    "type": "string",
                    "description": "USD scene path of the prim (e.g. /Geo/mesh)",
                },
                "attribute_name": {
                    "type": "string",
                    "description": "Name of the attribute to read (e.g. 'points', 'xformOp:translate')",
                },
                "frame": {
                    "type": "number",
                    "description": "Time code at which to evaluate the attribute. Omit for default time.",
                },
                "max_elements": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum array elements to return (default 100)",
                },
                "load_payloads": {
                    "type": "boolean",
                    "default": False,
                    "description": "Load USD payloads. Required if the target prim is defined inside a payload. Default: false.",
                },
            },
        },
    ),
    types.Tool(
        name="usd_read_cameras",
        description=(
            "Find all Camera prims in a USD scene and read their lens and "
            "projection attributes (focalLength, aperture, clippingRange, "
            "fStop, focusDistance, projection, shutter). "
            "The stage is fully composed — references and sublayers are "
            "resolved — but payloads are not loaded. "
            "Use this to inspect camera settings from any USD file."
        ),
        inputSchema={
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a USD file (.usd, .usda, .usdc, .usdz)",
                },
                "frame": {
                    "type": "number",
                    "description": (
                        "Time code (frame number) at which to evaluate time-sampled "
                        "attributes. Omit to use the default (static) value."
                    ),
                },
            },
        },
    ),
]

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

async def call_usd_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "usd_read_layer_metadata":
        return await _handle_read_layer_metadata(arguments)
    if name == "usd_read_hierarchy":
        return await _handle_read_hierarchy(arguments)
    if name == "usd_read_hierarchy_composed":
        return await _handle_read_hierarchy_composed(arguments)
    if name == "usd_read_composition_arcs":
        return await _handle_read_composition_arcs(arguments)
    if name == "usd_replace_anchors":
        return await _handle_replace_anchors(arguments)
    if name == "usd_read_cameras":
        return await _handle_read_cameras(arguments)
    if name == "usd_stitch_clips":
        return await _handle_stitch_clips(arguments)
    if name == "usd_read_prim_attributes":
        return await _handle_read_prim_attributes(arguments)
    if name == "usd_read_attribute_value":
        return await _handle_read_attribute_value(arguments)
    raise ValueError(f"unknown usd tool: {name}")

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _handle_read_layer_metadata(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    try:
        result = read_layer_metadata(path)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e)


async def _handle_read_hierarchy(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    max_depth = int(arguments.get("max_depth", 0))
    try:
        result = read_layer_hierarchy(path, max_depth=max_depth)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e)


async def _handle_read_hierarchy_composed(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    max_depth = int(arguments.get("max_depth", 0))
    try:
        result = read_composed_hierarchy(path, max_depth=max_depth)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e)


async def _handle_read_composition_arcs(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    try:
        result = read_composition_arcs(path)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e)


async def _handle_replace_anchors(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    replacements = arguments.get("replacements")
    if replacements is None:
        replacements = {}
    elif not isinstance(replacements, dict):
        raise ValueError("[-32602] replacements must be an object")
    try:
        result = replace_anchors(path, replacements)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e)


async def _handle_read_cameras(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    frame_raw = arguments.get("frame")
    frame = float(frame_raw) if frame_raw is not None else None
    try:
        result = read_cameras(path, frame=frame)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e)

async def _handle_stitch_clips(arguments: dict) -> list[types.TextContent]:
    import os
    filepath_template = arguments.get("filepath_template", "")
    primpath          = arguments.get("primpath", "")
    output_path       = arguments.get("output_path", "")
    frame_range_raw   = arguments.get("frame_range")

    if not filepath_template or not primpath or not output_path:
        raise ValueError("[-32602] filepath_template, primpath, and output_path are required")
    if not isinstance(frame_range_raw, list) or len(frame_range_raw) != 2:
        raise ValueError("[-32602] frame_range must be a [start, end] integer array")
    frame_range = (int(frame_range_raw[0]), int(frame_range_raw[1]))

    scene_range_raw  = arguments.get("scene_range")
    scene_range      = (int(scene_range_raw[0]), int(scene_range_raw[1])) if scene_range_raw else None
    loop             = bool(arguments.get("loop", False))
    clip_set         = str(arguments.get("clip_set", "default"))
    clip_primpath    = arguments.get("clip_primpath")
    strict           = bool(arguments.get("strict", False))
    gen_topology     = bool(arguments.get("gen_topology", True))
    gen_manifest     = bool(arguments.get("gen_manifest", True))
    probe_frame_raw  = arguments.get("probe_frame")
    probe_frame      = int(probe_frame_raw) if probe_frame_raw is not None else None
    auto_detect_prim = bool(arguments.get("auto_detect_prim", True))
    fps_raw          = arguments.get("fps")
    fps              = float(fps_raw) if fps_raw is not None else None

    try:
        result = stitch_clips(
            filepath_template=filepath_template,
            primpath=primpath,
            output_path=output_path,
            frame_range=frame_range,
            scene_range=scene_range,
            loop=loop,
            clip_set=clip_set,
            clip_primpath=clip_primpath,
            strict=strict,
            gen_topology=gen_topology,
            gen_manifest=gen_manifest,
            probe_frame=probe_frame,
            auto_detect_prim=auto_detect_prim,
            fps=fps,
        )
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except (FileNotFoundError, StitchClipsError) as e:
        raise _usd_error(e)


async def _handle_read_prim_attributes(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    prim_path = arguments.get("prim_path", "")
    detail = str(arguments.get("detail", "types"))
    filter_prefix = arguments.get("filter") or None
    limit = int(arguments.get("limit", 200))
    frame_raw = arguments.get("frame")
    frame = float(frame_raw) if frame_raw is not None else None
    load_payloads = bool(arguments.get("load_payloads", False))
    try:
        result = read_prim_attributes(path, prim_path, detail=detail, filter_prefix=filter_prefix, limit=limit, frame=frame, load_payloads=load_payloads)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except (FileNotFoundError, UsdOpenError, ValueError) as e:
        raise _usd_error(e)


async def _handle_read_attribute_value(arguments: dict) -> list[types.TextContent]:
    path = arguments.get("path", "")
    prim_path = arguments.get("prim_path", "")
    attribute_name = arguments.get("attribute_name", "")
    frame_raw = arguments.get("frame")
    frame = float(frame_raw) if frame_raw is not None else None
    max_elements = int(arguments.get("max_elements", 100))
    load_payloads = bool(arguments.get("load_payloads", False))
    try:
        result = read_attribute_value(path, prim_path, attribute_name, frame=frame, max_elements=max_elements, load_payloads=load_payloads)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e)


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _usd_error(e: Exception) -> ValueError:
    code = -32602 if isinstance(e, FileNotFoundError) else -32600
    return ValueError(f"[{code}] {e}")
