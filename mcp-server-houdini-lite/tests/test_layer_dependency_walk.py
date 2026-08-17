"""read_layer_dependencies answers "what files does this scene need".

read_composition_arcs answers a different question — what one layer declares,
grouped by arc type, keeping the authored string that usd_replace_anchors
matches on. It stops at depth 1, so a layer reachable only through another
layer is invisible to it. The two overlap on the direct dependencies and
neither subsumes the other.

Each record says which layer introduced it, because when a dependency is
missing, the layer that declares it is the thing you have to go and fix.
"""

import json

import pytest
from pxr import Usd

from usd_tools import read_layer_dependencies


def _layer(path, sublayers=(), refs=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    if refs:
        prim = stage.DefinePrim("/R")
        for ref in refs:
            prim.GetReferences().AddReference(ref, "/R")
    stage.GetRootLayer().subLayerPaths = list(sublayers)
    stage.GetRootLayer().Save()
    return path


def _by_name(result):
    return {p["resolved_path"].rsplit("/", 1)[-1]: p for p in result["dependencies"]}


def test_a_layer_reachable_only_through_another_is_found(tmp_path):
    """The whole reason this exists — read_composition_arcs stops at depth 1."""
    _layer(tmp_path / "leaf.usda")
    _layer(tmp_path / "mid.usda", refs=["./leaf.usda"])
    root = _layer(tmp_path / "root.usda", sublayers=["./mid.usda"])

    deps = _by_name(read_layer_dependencies(str(root)))

    assert set(deps) == {"mid.usda", "leaf.usda"}
    assert deps["mid.usda"]["depth"] == 1
    assert deps["leaf.usda"]["depth"] == 2


def test_a_missing_dependency_names_the_layer_that_declares_it(tmp_path):
    """A flat list of paths leaves you hunting for who asked for the file."""
    _layer(tmp_path / "mid.usda", refs=["./gone.usda"])
    root = _layer(tmp_path / "root.usda", sublayers=["./mid.usda"])

    deps = _by_name(read_layer_dependencies(str(root)))

    assert deps["gone.usda"]["resolved"] == "missing"
    assert deps["gone.usda"]["introduced_by"] == str(tmp_path / "mid.usda").replace("\\", "/")


def test_the_root_itself_is_not_listed_as_its_own_dependency(tmp_path):
    _layer(tmp_path / "mid.usda")
    root = _layer(tmp_path / "root.usda", sublayers=["./mid.usda"])

    names = set(_by_name(read_layer_dependencies(str(root))))

    assert names == {"mid.usda"}


def test_a_cycle_terminates(tmp_path):
    """Two layers sublayering each other must not recurse forever."""
    a = tmp_path / "a.usda"
    b = tmp_path / "b.usda"
    _layer(a)
    _layer(b, sublayers=["./a.usda"])
    stage = Usd.Stage.Open(str(a))
    stage.GetRootLayer().subLayerPaths = ["./b.usda"]
    stage.GetRootLayer().Save()

    deps = _by_name(read_layer_dependencies(str(a)))

    assert set(deps) == {"b.usda"}, "a.usda is the root and must not reappear"


def test_a_layer_reached_twice_is_reported_once(tmp_path):
    """Diamond: both branches pull in the same leaf."""
    _layer(tmp_path / "leaf.usda")
    _layer(tmp_path / "left.usda", refs=["./leaf.usda"])
    _layer(tmp_path / "right.usda", refs=["./leaf.usda"])
    root = _layer(tmp_path / "root.usda", sublayers=["./left.usda", "./right.usda"])

    result = read_layer_dependencies(str(root))
    leaves = [d for d in result["dependencies"] if d["resolved_path"].endswith("leaf.usda")]

    assert len(leaves) == 1


def test_every_path_uses_one_separator(tmp_path):
    """USD hands back realPath for a layer it opened and a computed path for one
    it could not, and on Windows those disagree on the separator."""
    _layer(tmp_path / "mid.usda", refs=["./gone.usda"])
    root = _layer(tmp_path / "root.usda", sublayers=["./mid.usda"])

    result = read_layer_dependencies(str(root))

    for dep in result["dependencies"]:
        assert "\\" not in dep["resolved_path"], dep
        assert "\\" not in dep["introduced_by"], dep


def test_missing_count_summarises_the_breakage(tmp_path):
    _layer(tmp_path / "ok.usda")
    root = _layer(tmp_path / "root.usda", sublayers=["./ok.usda", "./gone.usda"])

    result = read_layer_dependencies(str(root))

    assert result["dependency_count"] == 2
    assert result["missing_count"] == 1


def test_the_result_is_capped_and_says_so(tmp_path):
    for i in range(4):
        _layer(tmp_path / f"s{i}.usda")
    root = _layer(tmp_path / "root.usda", sublayers=[f"./s{i}.usda" for i in range(4)])

    capped = read_layer_dependencies(str(root), limit=2)

    assert len(capped["dependencies"]) == 2
    assert capped["truncated"] is True
    assert capped["dependency_count"] == 4, "the count reports the whole walk"


def test_a_missing_root_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_layer_dependencies(str(tmp_path / "nope.usda"))


def test_a_resolver_uri_is_not_run_through_path_arithmetic(tmp_path):
    """ComputeAbsolutePath eats one slash of omniverse:// and yields a broken
    string. Reporting that as a resolved path — and the layer as missing —
    invents a location the resolver never named."""
    root = _layer(tmp_path / "root.usda", sublayers=["omniverse://server/asset.usd"])

    entry = read_layer_dependencies(str(root))["dependencies"][0]

    assert entry["resolved"] == "uri"
    assert entry["resolved_path"] is None
    assert entry["asset_path"] == "omniverse://server/asset.usd"


def test_no_mangled_uri_reaches_the_output(tmp_path):
    """The specific corruption, asserted directly: // must never become /."""
    root = _layer(
        tmp_path / "root.usda",
        sublayers=["omniverse://server/a.usd", "asset:lib/model.usda"],
    )

    result = read_layer_dependencies(str(root))

    assert "omniverse:/server" not in json.dumps(result)
    assert {d["resolved"] for d in result["dependencies"]} == {"uri"}


def test_a_uri_is_not_counted_as_a_missing_file(tmp_path):
    """missing_count drives "is this scene complete"; a URI is not breakage."""
    root = _layer(tmp_path / "root.usda", sublayers=["omniverse://server/a.usd"])

    assert read_layer_dependencies(str(root))["missing_count"] == 0


def test_an_unexpanded_expression_variable_is_not_a_path(tmp_path):
    root = _layer(tmp_path / "root.usda", sublayers=["`${SHOT}`/layer.usda"])

    entry = read_layer_dependencies(str(root))["dependencies"][0]

    assert entry["resolved"] == "expression"
    assert entry["resolved_path"] is None


def test_the_authored_string_is_kept_for_a_resolved_layer_too(tmp_path):
    """Knowing what was written is what lets a caller go and fix it."""
    _layer(tmp_path / "mid.usda")
    root = _layer(tmp_path / "root.usda", sublayers=["./mid.usda"])

    entry = read_layer_dependencies(str(root))["dependencies"][0]

    assert entry["asset_path"] == "./mid.usda"
    assert entry["resolved"] == "ok"


def test_a_negative_limit_is_rejected(tmp_path):
    """The MCP schema stops this, but a direct caller bypasses the schema, and
    a negative slice bound silently drops a suffix instead of capping."""
    root = _layer(tmp_path / "root.usda")

    with pytest.raises(ValueError, match="limit"):
        read_layer_dependencies(str(root), limit=-1)
