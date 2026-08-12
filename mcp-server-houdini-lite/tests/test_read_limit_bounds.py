"""limit and max_elements must reject negative values instead of misreporting.

Neither field had a lower bound, and Python's slicing turns a negative one into
a plausible wrong answer rather than an error: limit=-1 evaluates attrs[:-1] and
silently drops the last attribute, while max_elements=-1 yields an empty list
that is still flagged array_truncated. A caller reading either result has no way
to tell it apart from a genuine one, which is worse than a refusal.

Zero stays legal — "return none of them" is a coherent request, and the
truncation flags already describe that result honestly.
"""

import json

import pytest
from mcp.client.client import Client
from mcp.shared.exceptions import MCPError
from pxr import Sdf, Usd, UsdGeom

import server


@pytest.fixture
def stage_path(tmp_path):
    path = tmp_path / "s.usda"
    stage = Usd.Stage.CreateNew(str(path))
    mesh = UsdGeom.Mesh.Define(stage, "/geo")
    for i in range(3):
        mesh.GetPrim().CreateAttribute(f"attr{i}", Sdf.ValueTypeNames.Float).Set(float(i))
    mesh.CreatePointsAttr([(0, 0, 0)] * 6)
    stage.GetRootLayer().Save()
    return str(path)


async def _call(name, arguments):
    """Return (refused, payload_or_text). Either error channel counts as refused."""
    async with Client(server.app) as client:
        try:
            result = await client.call_tool(name, arguments)
        except MCPError as e:
            return True, e.message
    if result.is_error:
        return True, result.content[0].text
    return False, json.loads(result.content[0].text)


@pytest.mark.anyio
@pytest.mark.parametrize("bad", [-1, -100])
async def test_negative_limit_is_refused_not_silently_applied(stage_path, bad):
    refused, payload = await _call(
        "usd_read_prim_attributes",
        {"path": stage_path, "prim_path": "/geo", "limit": bad},
    )

    assert refused, f"limit={bad} was accepted and returned: {payload}"


@pytest.mark.anyio
@pytest.mark.parametrize("bad", [-1, -100])
async def test_negative_max_elements_is_refused_not_silently_applied(stage_path, bad):
    refused, payload = await _call(
        "usd_read_attribute_value",
        {
            "path": stage_path,
            "prim_path": "/geo",
            "attribute_name": "points",
            "max_elements": bad,
        },
    )

    assert refused, f"max_elements={bad} was accepted and returned: {payload}"


@pytest.mark.anyio
async def test_zero_limit_is_still_a_legal_request(stage_path):
    refused, payload = await _call(
        "usd_read_prim_attributes",
        {"path": stage_path, "prim_path": "/geo", "limit": 0},
    )

    assert not refused, f"limit=0 must stay legal, got: {payload}"
    assert payload["attributes"] == []
    assert payload["truncated"] is True, "an empty result must say it was cut short"


@pytest.mark.anyio
async def test_zero_max_elements_is_still_a_legal_request(stage_path):
    refused, payload = await _call(
        "usd_read_attribute_value",
        {
            "path": stage_path,
            "prim_path": "/geo",
            "attribute_name": "points",
            "max_elements": 0,
        },
    )

    assert not refused, f"max_elements=0 must stay legal, got: {payload}"
    assert payload["value"] == []
    assert payload["array_total"] == 6
    assert payload["array_truncated"] is True, "an empty array must say it was cut short"


@pytest.mark.anyio
async def test_an_ordinary_limit_still_returns_attributes(stage_path):
    """Guards against a bound that rejects everything."""
    refused, payload = await _call(
        "usd_read_prim_attributes",
        {"path": stage_path, "prim_path": "/geo", "limit": 2},
    )

    assert not refused, payload
    assert len(payload["attributes"]) == 2
