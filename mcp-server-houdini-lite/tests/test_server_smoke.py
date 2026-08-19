"""Smoke tests for the houdini-lite MCP server over an in-memory transport."""

import json
from pathlib import Path

import pytest
from mcp.client.client import Client
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS

import server

BASELINE_PATH = Path(__file__).parent / "schema_baseline.json"
with open(BASELINE_PATH, encoding="utf-8") as f:
    BASELINE_TOOL_NAMES = set(json.load(f).keys())

# Tools added after the SDK v2 migration. The baseline is a snapshot of the
# pre-migration server, so it can never contain them; listing them here keeps
# the guard meaningful — an unlisted new tool, or a disappearing old one, still
# fails — without pretending they were part of that snapshot.
ADDED_TOOL_NAMES = {
    "usd_read_asset_paths",
    "usd_read_layer_dependencies",
    "usd_read_render_settings",
}


@pytest.mark.anyio
async def test_list_tools_exposes_every_declared_tool():
    async with Client(server.app) as client:
        result = await client.list_tools()

    assert {t.name for t in result.tools} == BASELINE_TOOL_NAMES | ADDED_TOOL_NAMES


@pytest.mark.anyio
async def test_unknown_tool_is_reported_as_an_error_result():
    async with Client(server.app) as client:
        result = await client.call_tool("no_such_tool", {})

    assert result.is_error is True
    assert "no_such_tool" in result.content[0].text


@pytest.mark.anyio
async def test_missing_file_error_reaches_the_caller_intact(tmp_path):
    missing_path = str(tmp_path / "missing.bgeo.sc")
    async with Client(server.app) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("bgeo_read_header", {"path": missing_path})

    assert exc.value.code == INVALID_PARAMS
    assert missing_path in exc.value.message


@pytest.mark.anyio
async def test_every_handler_error_keeps_a_diagnosable_code_and_message(tmp_path):
    """Every tool must fail with a diagnosable message, never a bare -32603."""
    missing_dir = tmp_path / "missing"
    checks = [
        ("bgeo_read_header", {"path": str(missing_dir / "missing.bgeo.sc")}),
        ("bgeo_inspect", {"path": str(missing_dir / "missing.bgeo.sc")}),
        ("bgeo_list_sequence", {"directory": str(missing_dir)}),
        ("vdb_inspect", {"path": str(missing_dir / "missing.vdb")}),
        ("vdb_list_sequence", {"directory": str(missing_dir)}),
        ("usd_read_hierarchy", {"path": str(missing_dir / "missing.usda")}),
    ]

    async with Client(server.app) as client:
        for name, arguments in checks:
            with pytest.raises(MCPError) as exc:
                await client.call_tool(name, arguments)
            assert exc.value.code != INTERNAL_ERROR, f"{name} lost its error code"
            assert exc.value.message != "Internal server error", f"{name} lost its message"


@pytest.mark.anyio
async def test_reading_a_real_usd_layer_returns_parsable_json(tmp_path):
    from pxr import Usd, UsdGeom

    usd_path = tmp_path / "sample.usda"
    stage = Usd.Stage.CreateNew(str(usd_path))
    UsdGeom.Xform.Define(stage, "/root")
    UsdGeom.Sphere.Define(stage, "/root/sphere")
    stage.GetRootLayer().Save()

    async with Client(server.app) as client:
        result = await client.call_tool("usd_read_hierarchy", {"path": str(usd_path)})

    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert "/root" in json.dumps(payload)


NON_NUMERIC_ARGS = [
    ("usd_read_hierarchy", {"path": "/unused/x.usda", "max_depth": "deep"}),
    ("usd_read_hierarchy_composed", {"path": "/unused/x.usda", "max_depth": "deep"}),
    ("usd_read_cameras", {"path": "/unused/x.usda", "frame": "now"}),
    ("usd_read_prim_attributes", {"path": "/unused/x.usda", "prim_path": "/r", "limit": "many"}),
    ("usd_read_prim_attributes", {"path": "/unused/x.usda", "prim_path": "/r", "frame": "now"}),
    ("usd_read_attribute_value",
     {"path": "/unused/x.usda", "prim_path": "/r", "attribute_name": "a", "max_elements": "lots"}),
    ("bgeo_stitch_usd_clips",
     {"filepath_template": "/unused/x.$F4.bgeo.sc", "output_path": "/unused/o.usda", "frame_range": ["bad", 2]}),
    ("bgeo_stitch_usd_clips",
     {"filepath_template": "/unused/x.$F4.bgeo.sc", "output_path": "/unused/o.usda", "probe_frame": "abc"}),
    ("usd_stitch_clips",
     {"filepath_template": "/unused/x.$F4.usd", "output_path": "/unused/o.usda", "primpath": "/r",
      "frame_range": ["bad", 2]}),
    ("vdb_stitch_volume_usd",
     {"filepath_template": "/unused/x.$F4.vdb", "output_path": "/unused/o.usda", "volume_name": "d",
      "parent_primpath": "/r", "frame_range": ["bad", 2]}),
]


@pytest.mark.anyio
@pytest.mark.parametrize("tool_name,arguments", NON_NUMERIC_ARGS)
async def test_non_numeric_argument_is_rejected(tool_name, arguments):
    async with Client(server.app) as client:
        result = await client.call_tool(tool_name, arguments)

    assert result.is_error is True
    assert tool_name in result.content[0].text
