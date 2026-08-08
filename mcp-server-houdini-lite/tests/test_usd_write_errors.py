"""Refusals by the write tools, which the happy-path suite cannot reach.

test_usd_write_behavior.py asserts is_error is False in its helper, so every
case there is a success. These are the other half: the guards that stop a tool
from overwriting a file or writing a malformed layer. Getting these wrong is
worse than getting the happy path wrong — an unenforced output_path guard
destroys work that already exists.
"""

import pytest
from mcp.client.client import Client
from mcp.shared.exceptions import MCPError
from pxr import Sdf

import server


async def _call_expecting_failure(name, arguments):
    """Return (mcp_error_or_None, error_text). Either channel counts as refused."""
    async with Client(server.app) as client:
        try:
            result = await client.call_tool(name, arguments)
        except MCPError as e:
            return e, e.message
    assert result.is_error is True, f"{name} did not refuse: {result.content[0].text}"
    return None, result.content[0].text


def _layer_with(path, sublayers=()):
    layer = Sdf.Layer.CreateNew(str(path))
    layer.subLayerPaths = list(sublayers)
    layer.Save()
    return layer


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool_name,extra",
    [
        ("usd_write_layer_metadata", {"metadata": {"upAxis": "Y"}}),
        ("usd_add_sublayers", {"sublayers": ["a.usda"], "position": "append"}),
        ("usd_remove_sublayers", {"sublayers": ["a.usda"]}),
    ],
)
async def test_export_refuses_to_overwrite_an_existing_output(tool_name, extra, tmp_path):
    source_path = tmp_path / "source.usda"
    output_path = tmp_path / "taken.usda"
    _layer_with(source_path, ["a.usda"])
    existing = _layer_with(output_path)
    existing.customLayerData = {"keep": "me"}
    existing.Save()

    _, text = await _call_expecting_failure(
        tool_name,
        {"path": str(source_path), "output_path": str(output_path), **extra},
    )

    assert "already exists" in text
    # The pre-existing file must be exactly as it was.
    survivor = Sdf.Layer.FindOrOpen(str(output_path))
    survivor.Reload()
    assert dict(survivor.customLayerData) == {"keep": "me"}


@pytest.mark.anyio
async def test_create_expressions_layer_refuses_an_existing_output(tmp_path):
    output_path = tmp_path / "taken.usda"
    _layer_with(output_path)

    _, text = await _call_expecting_failure(
        "usd_create_expressions_layer",
        {"output_path": str(output_path), "expression_variables": {"A": "b"}},
    )

    assert "already exists" in text


@pytest.mark.anyio
@pytest.mark.parametrize("bad_index", [-1, 3])
async def test_insert_sublayers_rejects_an_out_of_range_index(bad_index, tmp_path):
    source_path = tmp_path / "source.usda"
    layer = _layer_with(source_path, ["a.usda", "b.usda"])

    _, text = await _call_expecting_failure(
        "usd_insert_sublayers",
        {
            "path": str(source_path),
            "sublayers": ["new.usda"],
            "index": bad_index,
        },
    )

    assert "index" in text
    layer.Reload()
    assert list(layer.subLayerPaths) == ["a.usda", "b.usda"]


@pytest.mark.anyio
async def test_insert_sublayers_accepts_the_boundary_index(tmp_path):
    """index == len(existing) is documented as valid; guard against off-by-one."""
    source_path = tmp_path / "source.usda"
    layer = _layer_with(source_path, ["a.usda", "b.usda"])

    async with Client(server.app) as client:
        result = await client.call_tool(
            "usd_insert_sublayers",
            {"path": str(source_path), "sublayers": ["z.usda"], "index": 2},
        )

    assert result.is_error is False
    layer.Reload()
    assert list(layer.subLayerPaths) == ["a.usda", "b.usda", "z.usda"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "variables",
    [
        {"BAD": 1.5},              # float is not an allowed leaf type
        {"BAD": [1, "two"]},       # list must be homogeneous
        {"BAD": {"nested": "no"}}, # dict is not an allowed leaf type
    ],
)
async def test_create_expressions_layer_rejects_unsupported_value_types(
    variables, tmp_path
):
    output_path = tmp_path / "out.usda"

    _, text = await _call_expecting_failure(
        "usd_create_expressions_layer",
        {"output_path": str(output_path), "expression_variables": variables},
    )

    assert "BAD" in text or "expressionVariables" in text
    assert not output_path.exists(), "a rejected layer must not be left on disk"
