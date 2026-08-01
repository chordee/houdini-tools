"""
usd_handlers.py — MCP tool definitions and handlers for USD tools
"""

import json
from typing import Annotated, Literal

import mcp.types as types
from mcp.server import MCPServer
from mcp.shared.exceptions import MCPError
from pydantic import Field

from handler_args import to_float, to_int

from usd_tools import (
    UsdOpenError,
    add_sublayers,
    create_expressions_layer,
    insert_sublayers,
    read_layer_metadata,
    read_layer_hierarchy,
    read_composed_hierarchy,
    read_composition_arcs,
    replace_anchors,
    read_cameras,
    read_prim_attributes,
    read_attribute_value,
    remove_sublayers,
    write_layer_metadata,
)
from usd_clips import StitchClipsError, stitch_clips

# ---------------------------------------------------------------------------
# @mcp.tool() registrations (converted tools)
# ---------------------------------------------------------------------------


def register(mcp: MCPServer) -> None:
    mcp.tool()(usd_read_layer_metadata)
    mcp.tool()(usd_read_hierarchy)
    mcp.tool()(usd_read_hierarchy_composed)
    mcp.tool()(usd_read_composition_arcs)
    mcp.tool()(usd_read_cameras)
    mcp.tool()(usd_read_prim_attributes)
    mcp.tool()(usd_read_attribute_value)
    mcp.tool()(usd_write_layer_metadata)
    mcp.tool()(usd_create_expressions_layer)
    mcp.tool()(usd_replace_anchors)
    mcp.tool()(usd_add_sublayers)
    mcp.tool()(usd_insert_sublayers)
    mcp.tool()(usd_remove_sublayers)


def usd_read_layer_metadata(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a USD file")],
) -> dict:
    """Read layer-level metadata from a single USD layer file (.usd, .usda, .usdc, .usdz) without composition. Returns the file format and all standard layer metadata fields: defaultPrim, startTimeCode, endTimeCode, framesPerSecond, timeCodesPerSecond, metersPerUnit, upAxis, customLayerData, and expressionVariables. A field that has not been authored in the file is reported as null (distinguishing 'unauthored' from a legitimate authored zero / empty value)."""
    try:
        return read_layer_metadata(path)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_read_hierarchy(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a USD file")],
    max_depth: Annotated[int, Field(description="Maximum hierarchy depth to return (0 = unlimited, 1 = root prims only, etc.)")] = 0,
) -> dict:
    """Read the prim hierarchy from a single USD layer without composition. References, sublayers, and payloads are NOT resolved — only prims defined directly in this file are returned. Fastest option for a quick structural overview of one file."""
    try:
        return read_layer_hierarchy(path, max_depth=max_depth)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_read_hierarchy_composed(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a USD file")],
    max_depth: Annotated[int, Field(description="Maximum hierarchy depth to return (0 = unlimited)")] = 0,
) -> dict:
    """Read the fully composed USD prim hierarchy, resolving all references and sublayers. Payloads are intentionally not loaded to keep memory usage low. Use this when you need to see the complete scene structure across multiple referenced files."""
    try:
        return read_composed_hierarchy(path, max_depth=max_depth)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_read_composition_arcs(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a USD file")],
) -> dict:
    """List the direct composition arcs declared in a single USD layer: sublayers, references, and payloads. No composition is performed — only arcs explicitly written in this file are returned. Use this to understand which other USD files this layer depends on."""
    try:
        return read_composition_arcs(path)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_read_cameras(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a USD file (.usd, .usda, .usdc, .usdz)")],
    frame: Annotated[float | None, Field(description="Time code (frame number) at which to evaluate time-sampled attributes. Omit to use the default (static) value.")] = None,
) -> dict:
    """Find all Camera prims in a USD scene and read their lens and projection attributes (focalLength, aperture, clippingRange, fStop, focusDistance, projection, shutter). The stage is fully composed — references and sublayers are resolved — but payloads are not loaded. Use this to inspect camera settings from any USD file."""
    try:
        return read_cameras(path, frame=frame)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_read_prim_attributes(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a USD file")],
    prim_path: Annotated[str, Field(min_length=1, description="USD scene path of the prim to inspect (e.g. /Geo/mesh)")],
    detail: Annotated[Literal["names", "types", "samples"], Field(description="'names' → attribute names only; 'types' → add type_name, variability, is_array, array_size; 'samples' → also add has_time_samples, time_sample_count")] = "types",
    filter: Annotated[str | None, Field(description="Return only attributes whose name starts with this prefix (e.g. 'primvars:')")] = None,
    limit: Annotated[int, Field(description="Maximum number of attributes to return (default 200)")] = 200,
    frame: Annotated[float | None, Field(description="Time code used to evaluate array_size. Omit for default time.")] = None,
    load_payloads: Annotated[bool, Field(description="Load USD payloads. Required if the target prim is defined inside a payload. Default: false.")] = False,
) -> dict:
    """List attributes on a USD prim with progressive disclosure. Use detail='names' for a fast attribute name overview, 'types' (default) to add type info and array sizes, or 'samples' to also include time sample counts. Use filter to narrow by name prefix (e.g. 'primvars:'), and limit to cap the number of attributes returned."""
    try:
        return read_prim_attributes(path, prim_path, detail=detail, filter_prefix=filter, limit=limit, frame=frame, load_payloads=load_payloads)
    except (FileNotFoundError, UsdOpenError, ValueError) as e:
        raise _usd_error(e) from e


def usd_read_attribute_value(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a USD file")],
    prim_path: Annotated[str, Field(min_length=1, description="USD scene path of the prim (e.g. /Geo/mesh)")],
    attribute_name: Annotated[str, Field(min_length=1, description="Name of the attribute to read (e.g. 'points', 'xformOp:translate')")],
    frame: Annotated[float | None, Field(description="Time code at which to evaluate the attribute. Omit for default time.")] = None,
    max_elements: Annotated[int, Field(description="Maximum array elements to return (default 100)")] = 100,
    load_payloads: Annotated[bool, Field(description="Load USD payloads. Required if the target prim is defined inside a payload. Default: false.")] = False,
) -> dict:
    """Read the value of a single named attribute on a USD prim. For array attributes, results are truncated to max_elements (default 100) to avoid large payloads; check array_total and array_truncated in the response."""
    try:
        return read_attribute_value(path, prim_path, attribute_name, frame=frame, max_elements=max_elements, load_payloads=load_payloads)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_write_layer_metadata(
    path: Annotated[str, Field(min_length=1, description="Absolute path to an existing USD file to edit")],
    metadata: Annotated[dict, Field(description="Map of metadata field name to new value. Allowed fields: defaultPrim, startTimeCode, endTimeCode, framesPerSecond, timeCodesPerSecond, metersPerUnit, upAxis, customLayerData, expressionVariables. Value null clears the field.")],
    output_path: Annotated[str | None, Field(description="Optional. If given, export the modified layer to this path (must not already exist) instead of saving in-place. The source file is not touched.")] = None,
) -> dict:
    """Update layer-level metadata on a USD layer. Only fields present in the 'metadata' argument are touched; unmentioned fields are left as-is. A field value of null clears the field back to its unauthored state. Dict-valued fields (customLayerData / expressionVariables) are fully replaced. By default the file is saved in-place; pass 'output_path' to export to a new file instead (source is not touched, and the extension determines format — so this can also convert .usda <-> .usdc). expressionVariables values are restricted to str / bool / int / homogeneous list of those."""
    try:
        return write_layer_metadata(path, metadata, output_path=output_path)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_create_expressions_layer(
    output_path: Annotated[str, Field(min_length=1, description="Absolute path to the new USD layer (must not exist)")],
    expression_variables: Annotated[dict, Field(description="Non-empty dict of variable name to value")],
) -> dict:
    """Create a new USD layer at output_path containing ONLY the given expressionVariables metadata (no prims, no other layer metadata). Useful for pipeline config layers that are sublayered or referenced by other USDs to inject variables. expression_variables values are restricted to str / bool / int / homogeneous list of those. output_path must not already exist; file format is determined by the extension (.usd / .usda / .usdc)."""
    try:
        return create_expressions_layer(output_path, expression_variables)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_replace_anchors(
    path: Annotated[str, Field(min_length=1, description="Absolute path to a USD file to modify")],
    replacements: Annotated[dict[str, str], Field(description="Map of {old_asset_path: new_asset_path}. Keys must match the exact strings stored in the USD file (as returned by usd_read_composition_arcs).")],
) -> dict:
    """Replace multiple anchor asset paths (sublayers, references, payloads) in a single USD layer file in one operation. Edits the file in-place. Use usd_read_composition_arcs first to inspect existing anchors."""
    try:
        return replace_anchors(path, replacements)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_add_sublayers(
    path: Annotated[str, Field(min_length=1, description="Absolute path to an existing USD file to edit")],
    sublayers: Annotated[list[str], Field(min_length=1, description="Non-empty list of sublayer asset path strings to add. Stored as-is — pass the exact string you want to appear in subLayerPaths.")],
    position: Annotated[Literal["prepend", "append"], Field(description="'prepend' = insert at the top of subLayerPaths (strongest); 'append' = insert at the bottom (weakest).")],
    output_path: Annotated[str | None, Field(description="Optional. If given, export the modified layer to this path (must not already exist) instead of saving in-place. The source file is not touched.")] = None,
) -> dict:
    """Add one or more sublayer asset paths to a USD layer's subLayerPaths list. position='prepend' puts the new entries at the top (strongest), so for input ['A','B','C'] the final list is ['A','B','C', ...existing]. position='append' puts them at the bottom (weakest), so final = [...existing, 'A','B','C']. Entries whose string is already present are skipped (no-op) and reported in 'skipped'; anonymous identifiers (starting with 'anon:') are rejected. By default the file is saved in-place; pass 'output_path' to export to a new file instead (source is not touched, must not already exist; extension decides format)."""
    try:
        return add_sublayers(path, sublayers, position, output_path=output_path)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_insert_sublayers(
    path: Annotated[str, Field(min_length=1, description="Absolute path to an existing USD file to edit")],
    sublayers: Annotated[list[str], Field(min_length=1, description="Non-empty list of sublayer asset path strings to insert (stored as-is).")],
    index: Annotated[int, Field(ge=0, description="0-based insertion index. Must be in [0, len(existing_subLayerPaths)] inclusive.")],
    output_path: Annotated[str | None, Field(description="Optional. If given, export the modified layer to this path (must not already exist) instead of saving in-place. The source file is not touched.")] = None,
) -> dict:
    """Insert one or more sublayer asset paths at an explicit position in a USD layer's subLayerPaths. 'index' is 0-based against the current list length: 0 = top (strongest, same as usd_add_sublayers prepend), len(existing) = bottom (weakest, same as append). Values outside [0, len] — including negatives — raise. Multiple entries inserted at index i preserve input order and land at i, i+1, i+2, ... Same dedup and anonymous-identifier rejection as usd_add_sublayers. By default saves in-place; pass 'output_path' to export to a new file instead."""
    try:
        return insert_sublayers(path, sublayers, index, output_path=output_path)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


def usd_remove_sublayers(
    path: Annotated[str, Field(min_length=1, description="Absolute path to an existing USD file to edit")],
    sublayers: Annotated[list[str], Field(min_length=1, description="Non-empty list of sublayer asset path strings to remove (exact string match).")],
    output_path: Annotated[str | None, Field(description="Optional. If given, export the modified layer to this path (must not already exist) instead of saving in-place. The source file is not touched.")] = None,
) -> dict:
    """Remove one or more sublayer asset paths from a USD layer's subLayerPaths list. Matches the exact stored strings (same strings returned by usd_read_composition_arcs). Entries not found are silently skipped and reported in 'not_found' — no error is raised, so partial removals always succeed. By default the file is saved in-place; pass 'output_path' to export to a new file instead (source is not touched)."""
    try:
        return remove_sublayers(path, sublayers, output_path=output_path)
    except (FileNotFoundError, UsdOpenError) as e:
        raise _usd_error(e) from e


# ---------------------------------------------------------------------------
# Tool definitions (not yet converted — Task 6)
# ---------------------------------------------------------------------------

TOOLS = [
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
]

# ---------------------------------------------------------------------------
# Router (not yet converted tools only)
# ---------------------------------------------------------------------------

async def call_usd_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "usd_stitch_clips":
        return await _handle_stitch_clips(arguments)
    raise MCPError(types.METHOD_NOT_FOUND, f"unknown usd tool: {name}")

# ---------------------------------------------------------------------------
# Handlers (not yet converted tools only)
# ---------------------------------------------------------------------------

async def _handle_stitch_clips(arguments: dict) -> list[types.TextContent]:
    import os
    filepath_template = _require_str(arguments, "filepath_template")
    primpath          = _require_str(arguments, "primpath")
    output_path       = _require_str(arguments, "output_path")
    frame_range_raw   = arguments.get("frame_range")

    if not isinstance(frame_range_raw, list) or len(frame_range_raw) != 2:
        raise MCPError(types.INVALID_PARAMS, "frame_range must be a [start, end] integer array")
    frame_range = (to_int(frame_range_raw[0], "frame_range"), to_int(frame_range_raw[1], "frame_range"))

    scene_range_raw  = arguments.get("scene_range")
    scene_range      = (to_int(scene_range_raw[0], "scene_range"), to_int(scene_range_raw[1], "scene_range")) if scene_range_raw else None
    loop             = bool(arguments.get("loop", False))
    clip_set         = str(arguments.get("clip_set", "default"))
    clip_primpath    = _optional_str(arguments, "clip_primpath")
    strict           = bool(arguments.get("strict", False))
    gen_topology     = bool(arguments.get("gen_topology", True))
    gen_manifest     = bool(arguments.get("gen_manifest", True))
    probe_frame_raw  = arguments.get("probe_frame")
    probe_frame      = to_int(probe_frame_raw, "probe_frame") if probe_frame_raw is not None else None
    auto_detect_prim = bool(arguments.get("auto_detect_prim", True))
    fps_raw          = arguments.get("fps")
    fps              = to_float(fps_raw, "fps") if fps_raw is not None else None

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
        raise _usd_error(e) from e


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _usd_error(e: Exception) -> MCPError:
    code = types.INVALID_PARAMS if isinstance(e, FileNotFoundError) else types.INVALID_REQUEST
    return MCPError(code, str(e))


def _require_str(arguments: dict, key: str) -> str:
    v = arguments.get(key)
    if not isinstance(v, str) or not v:
        raise MCPError(types.INVALID_PARAMS, f"'{key}' is required and must be a non-empty string")
    return v


def _optional_str(arguments: dict, key: str) -> str | None:
    v = arguments.get(key)
    if v is None or v == "":
        return None
    if not isinstance(v, str):
        raise MCPError(types.INVALID_PARAMS, f"'{key}' must be a string if provided")
    return v
