"""The negative-bound guard has to live in the functions, not only the schema.

PR #17 gave usd_read_prim_attributes.limit and usd_read_attribute_value
.max_elements a ge=0 constraint, which stops the MCP path. The functions
underneath still accepted a negative value, and both feed it to a slice:
limit=-1 evaluates attrs[:-1] and drops the last attribute, max_elements=-1
yields an empty list still flagged array_truncated. Every other caller —
another tool, a test, a script — reached the original defect untouched.
"""

import pytest
from pxr import Sdf, Usd, UsdGeom

from usd_tools import read_attribute_value, read_prim_attributes


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


@pytest.mark.parametrize("bad", [-1, -100])
def test_read_prim_attributes_rejects_a_negative_limit(stage_path, bad):
    with pytest.raises(ValueError, match="limit"):
        read_prim_attributes(stage_path, "/geo", limit=bad)


@pytest.mark.parametrize("bad", [-1, -100])
def test_read_attribute_value_rejects_negative_max_elements(stage_path, bad):
    with pytest.raises(ValueError, match="max_elements"):
        read_attribute_value(stage_path, "/geo", "points", max_elements=bad)


def test_zero_stays_legal_for_both(stage_path):
    """Asking for none of them is coherent, and the flags still say so."""
    attrs = read_prim_attributes(stage_path, "/geo", limit=0)
    assert attrs["attributes"] == []
    assert attrs["truncated"] is True

    value = read_attribute_value(stage_path, "/geo", "points", max_elements=0)
    assert value["value"] == []
    assert value["array_total"] == 6
    assert value["array_truncated"] is True


def test_an_ordinary_bound_still_works(stage_path):
    """Guards against a check that rejects everything."""
    assert len(read_prim_attributes(stage_path, "/geo", limit=2)["attributes"]) == 2
    assert len(read_attribute_value(stage_path, "/geo", "points", max_elements=2)["value"]) == 2
