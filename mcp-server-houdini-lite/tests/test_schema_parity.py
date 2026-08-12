"""Every converted tool must keep its name, description and parameter descriptions."""

import pytest

import server
from mcp.server import MCPServer
from schema_tools import capture_tools, load_baseline, normalize_schema

CONVERTED: list[str] = [
    "vdb_inspect", "vdb_stitch_volume_usd", "vdb_list_sequence",
    "bgeo_read_header", "bgeo_list_sequence", "bgeo_stitch_usd_clips", "bgeo_inspect",
    "usd_read_layer_metadata", "usd_read_hierarchy", "usd_read_hierarchy_composed",
    "usd_read_composition_arcs", "usd_read_cameras", "usd_read_prim_attributes",
    "usd_read_attribute_value",
    "usd_write_layer_metadata", "usd_create_expressions_layer", "usd_replace_anchors",
    "usd_add_sublayers", "usd_insert_sublayers", "usd_remove_sublayers",
    "usd_stitch_clips",
]


def test_converted_names_exist_in_baseline():
    """A typo in CONVERTED should fail here, not as a KeyError deep in the parametrized test."""
    baseline = load_baseline()
    missing = [name for name in CONVERTED if name not in baseline]
    assert not missing, f"names in CONVERTED but absent from baseline: {missing}"


def test_schema_normalizer_rejects_heterogeneous_tuple_items():
    schema = {
        "prefixItems": [
            {"type": "integer"},
            {"type": "string"},
        ]
    }

    with pytest.raises(ValueError, match="heterogeneous tuple"):
        normalize_schema(schema)


@pytest.mark.anyio
async def test_converted_matches_server_exposed_tools():
    """CONVERTED must track the tools exposed by the converted server.

    The guard skips only while server.app is the pre-conversion low-level
    Server. Once it is an MCPServer, its exposed tool names must equal the
    current CONVERTED list exactly; a forgotten list update would otherwise go
    unnoticed.
    """
    if not isinstance(server.app, MCPServer):
        pytest.skip("server.app is not yet an MCPServer (pre-Task-2 state)")

    exposed = set((await capture_tools(server.app)).keys())
    assert exposed == set(CONVERTED)


# Numeric/array bound keys that must match the baseline exactly. minLength is
# deliberately excluded: Field(min_length=1) is added migration-wide wherever a
# _require_str check used to live, so minLength legitimately appears where the
# baseline had none — that is not a schema regression.
_CONSTRAINT_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minItems", "maxItems")

# bgeo_stitch_usd_clips.fps legitimately gains exclusiveMinimum: 0 — the positivity
# check did not disappear, it moved: bgeo_clips.py already raised on fps <= 0 (and on
# non-finite values), and the migration re-expresses that as Field(gt=0) on the field
# itself, so it now surfaces in the schema. This is a deliberate, migration-mandated
# exception for this one tool+property, not a general weakening of the constraint check.
#
# usd_stitch_clips.fps gains exclusiveMinimum: 0 for a different reason — this one
# IS a deliberate behaviour change, not a preserved constraint. The usd path never
# validated fps, so a zero or negative value was written straight into the stage as
# timeCodesPerSecond, producing a file with a nonsense frame rate and no error. The
# baseline records the old, unvalidated schema; this entry records that we chose to
# diverge from it.
#
# usd_read_prim_attributes.limit and usd_read_attribute_value.max_elements gain
# minimum: 0 for the same reason as usd_stitch_clips.fps — a deliberate
# divergence from the baseline, not a preserved constraint. Both are used as
# slice bounds, so a negative value did not fail: limit=-1 evaluated attrs[:-1]
# and quietly dropped the last attribute, and max_elements=-1 returned an empty
# list still flagged array_truncated. Refusing beats answering wrongly. Zero
# stays legal — asking for none of them is coherent.
_EXPECTED_NEW_CONSTRAINTS = {
    ("bgeo_stitch_usd_clips", "fps"): {"exclusiveMinimum": 0},
    ("usd_stitch_clips", "fps"): {"exclusiveMinimum": 0},
    ("usd_read_prim_attributes", "limit"): {"minimum": 0},
    ("usd_read_attribute_value", "max_elements"): {"minimum": 0},
}


@pytest.mark.anyio
@pytest.mark.parametrize("tool_name", CONVERTED)
async def test_converted_tool_matches_baseline(tool_name):
    baseline = load_baseline()[tool_name]
    current = (await capture_tools(server.app))[tool_name]

    assert current["description"] == baseline["description"]

    base_props = baseline["input_schema"].get("properties", {})
    cur_props = current["input_schema"].get("properties", {})
    assert set(cur_props) == set(base_props)
    for name, spec in base_props.items():
        assert cur_props[name].get("description") == spec.get("description"), name
        assert cur_props[name].get("type") == spec.get("type"), name
        assert cur_props[name].get("default") == spec.get("default"), name
        assert cur_props[name].get("enum") == spec.get("enum"), name
        allowed_new = _EXPECTED_NEW_CONSTRAINTS.get((tool_name, name), {})
        for key in _CONSTRAINT_KEYS:
            expected = spec.get(key, allowed_new.get(key))
            assert cur_props[name].get(key) == expected, f"{name}.{key}"

    assert set(current["input_schema"].get("required", [])) == set(
        baseline["input_schema"].get("required", [])
    )
