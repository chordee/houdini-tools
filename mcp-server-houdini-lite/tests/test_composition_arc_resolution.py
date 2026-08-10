"""read_composition_arcs reports where an asset path actually points.

The authored string is what replace_anchors matches on, so it stays untouched.
Alongside it each arc now carries where that string resolves to and why, because
"./USD/torus.usd" alone does not tell you whether the target is there, and the
usual reason a reference fails to load is that it anchors somewhere unexpected.

Not every asset path can be resolved by path arithmetic. A bare relative name
uses search semantics and simply is not found when the file is absent; an
asset-resolver URI belongs to the resolver; an unexpanded expression variable is
not a path yet. Those report no resolved_path rather than a plausible-looking
wrong one — USD's own ComputeAbsolutePath turns "omniverse://srv/a.usd" into
"omniverse:/srv/a.usd", which is a broken string, not an answer.
"""

from pxr import Sdf

from usd_tools import read_composition_arcs


def _layer(path, sublayers=(), expression_variables=None):
    layer = Sdf.Layer.CreateNew(str(path))
    layer.subLayerPaths = list(sublayers)
    if expression_variables:
        layer.expressionVariables = expression_variables
    layer.Save()
    return layer


def _referencing_layer(path, asset_path):
    layer = Sdf.Layer.CreateNew(str(path))
    prim = Sdf.PrimSpec(layer, "Root", Sdf.SpecifierDef)
    prim.referenceList.Add(Sdf.Reference(asset_path, "/Asset"))
    layer.Save()
    return layer


def test_relative_sublayer_resolves_against_the_layer(tmp_path):
    _layer(tmp_path / "target.usda")
    _layer(tmp_path / "root.usda", ["./target.usda"])

    arcs = read_composition_arcs(str(tmp_path / "root.usda"))
    entry = arcs["sublayers_resolved"][0]

    assert arcs["sublayers"] == ["./target.usda"], "authored string must be untouched"
    assert entry["asset_path"] == "./target.usda"
    assert entry["resolved_path"] == str(tmp_path / "target.usda").replace("\\", "/")
    assert entry["resolved"] == "ok"


def test_a_missing_target_still_reports_where_it_looked(tmp_path):
    """The most common reason an arc fails to load, so the path is the answer."""
    _layer(tmp_path / "root.usda", ["./gone.usda"])

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["resolved"] == "missing"
    assert entry["resolved_path"] == str(tmp_path / "gone.usda").replace("\\", "/")


def test_a_bare_name_that_is_not_found_claims_nothing(tmp_path):
    """Bare names use search semantics; without a hit there is no path to report."""
    _layer(tmp_path / "root.usda", ["gone.usda"])

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["resolved"] == "unresolved"
    assert entry["resolved_path"] is None


def test_a_bare_name_that_exists_resolves(tmp_path):
    _layer(tmp_path / "sibling.usda")
    _layer(tmp_path / "root.usda", ["sibling.usda"])

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["resolved"] == "ok"
    assert entry["resolved_path"] == str(tmp_path / "sibling.usda").replace("\\", "/")


def test_a_resolver_uri_is_left_to_the_resolver(tmp_path):
    """ComputeAbsolutePath mangles omniverse:// into omniverse:/ — do not ship that."""
    _layer(tmp_path / "root.usda", ["omniverse://server/asset.usd"])

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["resolved"] == "uri"
    assert entry["resolved_path"] is None
    assert entry["asset_path"] == "omniverse://server/asset.usd"


def test_an_unexpanded_expression_variable_is_not_a_path(tmp_path):
    _layer(tmp_path / "root.usda", ["`${SHOT}`/asset.usda"], {"SHOT": "sh010"})

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["resolved"] == "expression"
    assert entry["resolved_path"] is None


def test_an_absolute_path_passes_through(tmp_path):
    target = _layer(tmp_path / "target.usda")
    _layer(tmp_path / "root.usda", [target.realPath.replace("\\", "/")])

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["resolved"] == "ok"
    assert entry["resolved_path"] == target.realPath.replace("\\", "/")


def test_references_and_payloads_gain_the_same_fields(tmp_path):
    _layer(tmp_path / "asset.usda")
    _referencing_layer(tmp_path / "root.usda", "./asset.usda")

    ref = read_composition_arcs(str(tmp_path / "root.usda"))["references"][0]

    assert ref["asset_path"] == "./asset.usda", "authored string must be untouched"
    assert ref["resolved_path"] == str(tmp_path / "asset.usda").replace("\\", "/")
    assert ref["resolved"] == "ok"


def test_sublayers_stays_a_list_of_authored_strings(tmp_path):
    """replace_anchors matches these; changing the shape would break that pairing."""
    _layer(tmp_path / "root.usda", ["./a.usda", "b.usda"])

    arcs = read_composition_arcs(str(tmp_path / "root.usda"))

    assert arcs["sublayers"] == ["./a.usda", "b.usda"]
    assert [e["asset_path"] for e in arcs["sublayers_resolved"]] == ["./a.usda", "b.usda"]
