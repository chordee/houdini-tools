"""Smoke tests for the houdini-lite MCP server over an in-memory transport."""

import json
from pathlib import Path

import pytest
from mcp.client.client import Client
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS

import server

MISSING_PATH = "D:/does/not/exist/nowhere.bgeo.sc"

BASELINE_PATH = Path(__file__).parent / "schema_baseline.json"
with open(BASELINE_PATH, encoding="utf-8") as f:
    BASELINE_TOOL_NAMES = set(json.load(f).keys())


@pytest.mark.anyio
async def test_list_tools_exposes_every_declared_tool():
    async with Client(server.app) as client:
        result = await client.list_tools()

    assert {t.name for t in result.tools} == BASELINE_TOOL_NAMES


@pytest.mark.anyio
async def test_unknown_tool_is_reported_as_an_error_result():
    async with Client(server.app) as client:
        result = await client.call_tool("no_such_tool", {})

    assert result.is_error is True
    assert "no_such_tool" in result.content[0].text


@pytest.mark.anyio
async def test_missing_file_error_reaches_the_caller_intact():
    async with Client(server.app) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("bgeo_read_header", {"path": MISSING_PATH})

    assert exc.value.code == INVALID_PARAMS
    assert MISSING_PATH in exc.value.message


@pytest.mark.anyio
async def test_no_handler_error_degrades_to_opaque_internal_error():
    """Every tool must fail with a diagnosable message, never a bare -32603."""
    checks = [
        ("bgeo_read_header", {"path": MISSING_PATH}),
        ("bgeo_inspect", {"path": MISSING_PATH}),
        ("bgeo_list_sequence", {"directory": "D:/does/not/exist"}),
        ("vdb_inspect", {"path": "D:/does/not/exist/nowhere.vdb"}),
        ("vdb_list_sequence", {"directory": "D:/does/not/exist"}),
        ("usd_read_hierarchy", {"path": "D:/does/not/exist/nowhere.usda"}),
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
    ("usd_read_hierarchy", {"path": "D:/x.usda", "max_depth": "deep"}),
    ("usd_read_hierarchy_composed", {"path": "D:/x.usda", "max_depth": "deep"}),
    ("usd_read_cameras", {"path": "D:/x.usda", "frame": "now"}),
    ("usd_read_prim_attributes", {"path": "D:/x.usda", "prim_path": "/r", "limit": "many"}),
    ("usd_read_prim_attributes", {"path": "D:/x.usda", "prim_path": "/r", "frame": "now"}),
    ("usd_read_attribute_value",
     {"path": "D:/x.usda", "prim_path": "/r", "attribute_name": "a", "max_elements": "lots"}),
    ("bgeo_stitch_usd_clips",
     {"filepath_template": "D:/x.$F4.bgeo.sc", "output_path": "D:/o.usda", "frame_range": ["bad", 2]}),
    ("bgeo_stitch_usd_clips",
     {"filepath_template": "D:/x.$F4.bgeo.sc", "output_path": "D:/o.usda", "probe_frame": "abc"}),
    ("usd_stitch_clips",
     {"filepath_template": "D:/x.$F4.usd", "output_path": "D:/o.usda", "primpath": "/r",
      "frame_range": ["bad", 2]}),
    ("vdb_stitch_volume_usd",
     {"filepath_template": "D:/x.$F4.vdb", "output_path": "D:/o.usda", "volume_name": "d",
      "parent_primpath": "/r", "frame_range": ["bad", 2]}),
]


@pytest.mark.anyio
@pytest.mark.parametrize("tool_name,arguments", NON_NUMERIC_ARGS)
async def test_non_numeric_argument_is_rejected(tool_name, arguments):
    async with Client(server.app) as client:
        result = await client.call_tool(tool_name, arguments)

    assert result.is_error is True
    assert tool_name in result.content[0].text
