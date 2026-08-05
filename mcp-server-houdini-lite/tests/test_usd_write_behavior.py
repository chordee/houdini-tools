import json

import pytest
from mcp.client.client import Client
from pxr import Sdf, Usd

import server
from usd_tools import read_composition_arcs


async def _call_tool(name, arguments):
    async with Client(server.app) as client:
        result = await client.call_tool(name, arguments)

    assert result.is_error is False
    return json.loads(result.content[0].text)


def _create_layer(path, sublayers=()):
    layer = Sdf.Layer.CreateNew(str(path))
    layer.subLayerPaths = list(sublayers)
    layer.Save()
    return layer


@pytest.mark.anyio
async def test_write_layer_metadata_exports_without_modifying_source(tmp_path):
    source_path = tmp_path / "source.usda"
    output_path = tmp_path / "output.usda"
    source = _create_layer(source_path)

    payload = await _call_tool(
        "usd_write_layer_metadata",
        {
            "path": str(source_path),
            "metadata": {
                "framesPerSecond": 30.0,
                "customLayerData": {"owner": "test"},
            },
            "output_path": str(output_path),
        },
    )

    output = Sdf.Layer.FindOrOpen(str(output_path))
    assert payload["mode"] == "export"
    assert output_path.exists()
    assert source.HasFramesPerSecond() is False
    assert source.customLayerData == {}
    source.Reload()
    assert source.HasFramesPerSecond() is False
    assert source.customLayerData == {}
    assert output.framesPerSecond == 30.0
    assert dict(output.customLayerData) == {"owner": "test"}


@pytest.mark.anyio
async def test_create_expressions_layer_writes_only_expression_variables(tmp_path):
    output_path = tmp_path / "expressions.usda"
    variables = {"SHOW": "demo", "ENABLED": True, "TAKE": 2}

    payload = await _call_tool(
        "usd_create_expressions_layer",
        {
            "output_path": str(output_path),
            "expression_variables": variables,
        },
    )

    layer = Sdf.Layer.FindOrOpen(str(output_path))
    assert payload["expression_variables"] == variables
    assert output_path.exists()
    assert dict(layer.expressionVariables) == variables
    assert list(layer.rootPrims) == []


@pytest.mark.anyio
async def test_replace_anchors_updates_sublayer_reference_and_payload(tmp_path):
    _create_layer(tmp_path / "old-sub.usda")
    for name in ("old-ref.usda", "old-payload.usda"):
        stage = Usd.Stage.CreateNew(str(tmp_path / name))
        stage.DefinePrim("/Asset")
        stage.GetRootLayer().Save()

    source_path = tmp_path / "source.usda"
    stage = Usd.Stage.CreateNew(str(source_path))
    stage.GetRootLayer().subLayerPaths = ["old-sub.usda"]
    root = stage.DefinePrim("/Root")
    root.GetReferences().AddReference("old-ref.usda", "/Asset")
    root.GetPayloads().AddPayload("old-payload.usda", "/Asset")
    stage.GetRootLayer().Save()

    replacements = {
        "old-sub.usda": "new-sub.usda",
        "old-ref.usda": "new-ref.usda",
        "old-payload.usda": "new-payload.usda",
    }
    payload = await _call_tool(
        "usd_replace_anchors",
        {"path": str(source_path), "replacements": replacements},
    )

    arcs = read_composition_arcs(str(source_path))
    assert payload["total_replaced"] == 3
    assert arcs["sublayers"] == ["new-sub.usda"]
    assert [item["asset_path"] for item in arcs["references"]] == ["new-ref.usda"]
    assert [item["asset_path"] for item in arcs["payloads"]] == ["new-payload.usda"]


@pytest.mark.anyio
async def test_add_sublayers_prepends_in_input_order_to_export(tmp_path):
    source_path = tmp_path / "source.usda"
    output_path = tmp_path / "output.usda"
    source = _create_layer(source_path, ["existing.usda"])

    payload = await _call_tool(
        "usd_add_sublayers",
        {
            "path": str(source_path),
            "sublayers": ["a.usda", "b.usda"],
            "position": "prepend",
            "output_path": str(output_path),
        },
    )

    output = Sdf.Layer.FindOrOpen(str(output_path))
    assert list(source.subLayerPaths) == ["existing.usda"]
    source.Reload()
    assert list(source.subLayerPaths) == ["existing.usda"]
    assert list(output.subLayerPaths) == ["a.usda", "b.usda", "existing.usda"]
    assert payload["final_sublayers"] == ["a.usda", "b.usda", "existing.usda"]


@pytest.mark.anyio
async def test_insert_sublayers_preserves_order_at_requested_index(tmp_path):
    source_path = tmp_path / "source.usda"
    layer = _create_layer(source_path, ["a.usda", "d.usda"])

    payload = await _call_tool(
        "usd_insert_sublayers",
        {
            "path": str(source_path),
            "sublayers": ["b.usda", "c.usda"],
            "index": 1,
        },
    )

    layer.Reload()
    assert list(layer.subLayerPaths) == ["a.usda", "b.usda", "c.usda", "d.usda"]
    assert payload["final_sublayers"] == ["a.usda", "b.usda", "c.usda", "d.usda"]


@pytest.mark.anyio
async def test_remove_sublayers_removes_match_and_reports_missing(tmp_path):
    source_path = tmp_path / "source.usda"
    layer = _create_layer(source_path, ["a.usda", "b.usda", "c.usda"])

    payload = await _call_tool(
        "usd_remove_sublayers",
        {
            "path": str(source_path),
            "sublayers": ["b.usda", "missing.usda"],
        },
    )

    layer.Reload()
    assert list(layer.subLayerPaths) == ["a.usda", "c.usda"]
    assert payload["removed"] == ["b.usda"]
    assert payload["not_found"] == ["missing.usda"]
