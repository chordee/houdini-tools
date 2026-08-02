"""A malformed USD file must be reported the same way a malformed VDB is.

usd_tools' docstrings promise UsdOpenError for a file that cannot be opened as
a USD layer, but USD raises pxr.Tf.ErrorException before the None-check those
docstrings describe is reached. The exception escapes the handlers' except
clauses, so the caller gets a raw Tf message in an is_error result instead of
the translated -32600 the VDB path returns for the same class of problem.
"""

import pytest
from mcp.client.client import Client
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_REQUEST

import server
from usd_tools import (
    UsdOpenError,
    read_composition_arcs,
    read_layer_hierarchy,
    read_layer_metadata,
    read_composed_hierarchy,
    read_cameras,
)


@pytest.fixture
def malformed_usd(tmp_path):
    path = tmp_path / "broken.usda"
    path.write_text("this is not usd at all\n", encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    "func",
    [read_layer_metadata, read_layer_hierarchy, read_composition_arcs,
     read_composed_hierarchy, read_cameras],
)
def test_library_raises_usd_open_error_for_a_malformed_file(func, malformed_usd):
    with pytest.raises(UsdOpenError):
        func(malformed_usd)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool_name",
    ["usd_read_layer_metadata", "usd_read_hierarchy", "usd_read_composition_arcs",
     "usd_read_hierarchy_composed", "usd_read_cameras"],
)
async def test_tool_reports_invalid_request_for_a_malformed_file(tool_name, malformed_usd):
    async with Client(server.app) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool(tool_name, {"path": malformed_usd})

    assert exc.value.code == INVALID_REQUEST
    assert malformed_usd in exc.value.message


@pytest.mark.anyio
async def test_a_missing_file_is_still_invalid_params_not_invalid_request(tmp_path):
    """Guards against collapsing the two codes into one."""
    missing = str(tmp_path / "nope.usda")
    async with Client(server.app) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("usd_read_hierarchy", {"path": missing})

    assert exc.value.code == -32602
