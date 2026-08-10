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
    """A layer whose /Root both references and payloads the same asset path."""
    layer = Sdf.Layer.CreateNew(str(path))
    prim = Sdf.PrimSpec(layer, "Root", Sdf.SpecifierDef)
    prim.referenceList.Add(Sdf.Reference(asset_path, "/Asset"))
    prim.payloadList.Add(Sdf.Payload(asset_path, "/Asset"))
    layer.Save()
    return layer


def _internal_arc_layer(path):
    """Reference and payload with no asset path — they target this layer stack."""
    layer = Sdf.Layer.CreateNew(str(path))
    Sdf.PrimSpec(layer, "Source", Sdf.SpecifierDef)
    target = Sdf.PrimSpec(layer, "Target", Sdf.SpecifierDef)
    target.referenceList.Add(Sdf.Reference("", "/Source"))
    target.payloadList.Add(Sdf.Payload("", "/Source"))
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

    arcs = read_composition_arcs(str(tmp_path / "root.usda"))
    expected = str(tmp_path / "asset.usda").replace("\\", "/")

    for kind in ("references", "payloads"):
        arc = arcs[kind][0]
        assert arc["asset_path"] == "./asset.usda", f"{kind}: authored string must be untouched"
        assert arc["resolved_path"] == expected, kind
        assert arc["resolved"] == "ok", kind


def test_an_internal_arc_has_nothing_to_resolve(tmp_path):
    """An empty asset path targets this layer stack; it is not a failed lookup."""
    _internal_arc_layer(tmp_path / "root.usda")

    arcs = read_composition_arcs(str(tmp_path / "root.usda"))

    for kind in ("references", "payloads"):
        arc = arcs[kind][0]
        assert arc["asset_path"] == "", kind
        assert arc["target_prim_path"] == "/Source", kind
        assert arc["resolved"] == "internal", kind
        assert arc["resolved_path"] is None, kind


def test_sublayers_stays_a_list_of_authored_strings(tmp_path):
    """replace_anchors matches these; changing the shape would break that pairing."""
    _layer(tmp_path / "root.usda", ["./a.usda", "b.usda"])

    arcs = read_composition_arcs(str(tmp_path / "root.usda"))

    assert arcs["sublayers"] == ["./a.usda", "b.usda"]
    assert [e["asset_path"] for e in arcs["sublayers_resolved"]] == ["./a.usda", "b.usda"]


def test_a_scheme_without_double_slash_is_still_a_uri(tmp_path):
    """USD dispatches on the scheme; asset:… never reaches the filesystem."""
    _layer(tmp_path / "root.usda", ["asset:library/model.usda"])

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["resolved"] == "uri"
    assert entry["resolved_path"] is None


def test_a_windows_drive_letter_is_not_mistaken_for_a_scheme():
    """C: looks like a scheme but is a drive; only 2+ characters make a scheme.

    Asserted against the pattern directly, because building a real C:-rooted
    layer only exercises this on Windows and the classifier must behave the
    same wherever the tests run.
    """
    from usd_tools import _URI_SCHEME_RE

    for drive_path in ("C:/target.usda", "C:\target.usda", "d:/x.usd"):
        assert not _URI_SCHEME_RE.match(drive_path), drive_path
    for uri in ("omniverse://server/a.usd", "asset:library/model.usda", "ar:pkg"):
        assert _URI_SCHEME_RE.match(uri), uri


def test_an_absolute_path_on_this_platform_resolves(tmp_path):
    """The integration half: whatever absolute form this OS uses must still work."""
    target = _layer(tmp_path / "target.usda")
    _layer(tmp_path / "root.usda", [target.realPath.replace("\\", "/")])

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["resolved"] == "ok"
    assert entry["resolved_path"] == target.realPath.replace("\\", "/")


def test_a_directory_target_is_not_a_usable_layer(tmp_path):
    """Path.exists() is true for a directory, which cannot be opened as a layer."""
    (tmp_path / "assets").mkdir()
    _layer(tmp_path / "root.usda", ["./assets"])

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["resolved"] == "missing"


def test_a_package_relative_path_resolves_to_the_package(tmp_path):
    """foo.usdz[inner.usd] names a layer inside a package; the file is the package."""
    package = tmp_path / "bundle.usdz"
    package.write_bytes(b"")
    _layer(tmp_path / "root.usda", ["./bundle.usdz[inner/mesh.usd]"])

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["asset_path"] == "./bundle.usdz[inner/mesh.usd]", "authored string kept"
    assert entry["resolved_path"] == str(package).replace("\\", "/")
    assert entry["resolved"] == "ok"


def test_format_arguments_are_not_part_of_the_filename(tmp_path):
    """:SDF_FORMAT_ARGS: carries options, not path components."""
    target = _layer(tmp_path / "a.usd")
    _layer(tmp_path / "root.usda", ["./a.usd:SDF_FORMAT_ARGS:fps=24"])

    entry = read_composition_arcs(str(tmp_path / "root.usda"))["sublayers_resolved"][0]

    assert entry["resolved_path"] == target.realPath.replace("\\", "/")
    assert entry["resolved"] == "ok"
