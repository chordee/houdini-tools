"""read_asset_paths finds every file a stage points at, and says where it lands.

Textures were unreachable before this: you could read one asset attribute at a
time with usd_read_attribute_value, but only if you already knew the prim and
the attribute name — so finding a broken texture meant walking the whole stage
by hand, hundreds of calls for a normal look.

The scan is by attribute type, not by prim type. A shader-only walk misses the
case that matters most in a lighting scene: a DomeLight is not a UsdShade.Shader,
so its HDRI would never appear. Each record still carries a `kind` so a caller
can ask for just the textures.

Resolution goes through the composed stage's resolvedPath rather than the
layer arithmetic used for composition arcs, because a shader pulled in by a
reference anchors against ITS layer, not the root — anchoring against the root
would report a confidently wrong path.
"""

import json

import pytest
from mcp.client.client import Client
from pxr import Sdf, Usd, UsdGeom, UsdLux, UsdShade, UsdVol

import server
from usd_tools import read_asset_paths


def _texture_shader(stage, prim_path, asset_path, input_name="file"):
    shader = UsdShade.Shader.Define(stage, prim_path)
    shader.CreateIdAttr("UsdUVTexture")
    shader.CreateInput(input_name, Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(asset_path))
    return shader


def _stage_with(tmp_path, build):
    path = tmp_path / "look.usda"
    stage = Usd.Stage.CreateNew(str(path))
    build(stage)
    stage.GetRootLayer().Save()
    return str(path)


def _by_prim(result):
    return {a["prim_path"]: a for a in result["assets"]}


def _touch(tmp_path, *parts):
    target = tmp_path.joinpath(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"")
    return target


def test_a_texture_that_exists_resolves_to_an_absolute_path(tmp_path):
    target = _touch(tmp_path, "tex", "albedo.png")
    path = _stage_with(tmp_path, lambda s: _texture_shader(s, "/mtl/tex", "./tex/albedo.png"))

    entry = _by_prim(read_asset_paths(path))["/mtl/tex"]

    assert entry["asset_path"] == "./tex/albedo.png", "authored string must be untouched"
    assert entry["resolved_path"] == str(target).replace("\\", "/")
    assert entry["resolved"] == "ok"
    assert entry["kind"] == "texture"
    assert entry["attribute"] == "inputs:file"


def test_a_missing_texture_is_reported_not_dropped(tmp_path):
    """The whole point of the scan — a silent omission would hide the breakage."""
    path = _stage_with(tmp_path, lambda s: _texture_shader(s, "/mtl/tex", "./tex/gone.png"))

    entry = _by_prim(read_asset_paths(path))["/mtl/tex"]

    assert entry["resolved"] == "missing"
    assert entry["resolved_path"] is None
    assert entry["asset_path"] == "./tex/gone.png"


def test_a_udim_template_is_not_mistaken_for_a_missing_file(tmp_path):
    """<UDIM> never resolves — the resolver does not expand the token.

    Treating an empty resolvedPath as "missing" would flag every UDIM texture
    in a production look as broken.
    """
    path = _stage_with(
        tmp_path, lambda s: _texture_shader(s, "/mtl/tex", "./tex/color.<UDIM>.exr")
    )

    entry = _by_prim(read_asset_paths(path))["/mtl/tex"]

    assert entry["resolved"] == "udim"
    assert entry["asset_path"] == "./tex/color.<UDIM>.exr"


def test_a_dome_light_hdri_is_found(tmp_path):
    """A DomeLight is not a UsdShade.Shader, so a shader-only walk misses it."""

    def build(stage):
        dome = UsdLux.DomeLight.Define(stage, "/lights/dome")
        dome.CreateTextureFileAttr(Sdf.AssetPath("./hdri.exr"))

    _touch(tmp_path, "hdri.exr")
    path = _stage_with(tmp_path, build)

    entry = _by_prim(read_asset_paths(path))["/lights/dome"]

    assert entry["kind"] == "light"
    assert entry["attribute"] == "inputs:texture:file"
    assert entry["resolved"] == "ok"


def test_a_volume_cache_is_found_and_labelled(tmp_path):
    def build(stage):
        UsdVol.Volume.Define(stage, "/vol")
        vdb = UsdVol.OpenVDBAsset.Define(stage, "/vol/density")
        vdb.CreateFilePathAttr(Sdf.AssetPath("./smoke.vdb"))

    _touch(tmp_path, "smoke.vdb")
    path = _stage_with(tmp_path, build)

    entry = _by_prim(read_asset_paths(path))["/vol/density"]

    assert entry["kind"] == "volume"
    assert entry["attribute"] == "filePath"


def test_an_ordinary_asset_attribute_is_still_reported(tmp_path):
    """The scan is by attribute type, so nothing asset-valued escapes it."""

    def build(stage):
        mesh = UsdGeom.Mesh.Define(stage, "/geo")
        mesh.GetPrim().CreateAttribute("customAsset", Sdf.ValueTypeNames.Asset).Set(
            Sdf.AssetPath("./notes.txt")
        )

    path = _stage_with(tmp_path, build)

    entry = _by_prim(read_asset_paths(path))["/geo"]

    assert entry["kind"] == "other"
    assert entry["attribute"] == "customAsset"


def test_a_referenced_shader_anchors_against_its_own_layer(tmp_path):
    """The reason resolution goes through resolvedPath, not the root layer.

    The texture sits beside the referenced material, not beside the root, so
    root-layer arithmetic would produce a path that does not exist.
    """
    _touch(tmp_path, "sub", "tex", "n.png")
    sub = tmp_path / "sub" / "mat.usda"
    sub_stage = Usd.Stage.CreateNew(str(sub))
    _texture_shader(sub_stage, "/M/n", "./tex/n.png")
    sub_stage.GetRootLayer().Save()

    def build(stage):
        stage.DefinePrim("/ref").GetReferences().AddReference("./sub/mat.usda", "/M")

    path = _stage_with(tmp_path, build)

    entry = _by_prim(read_asset_paths(path))["/ref/n"]

    assert entry["resolved"] == "ok"
    assert entry["resolved_path"] == str(tmp_path / "sub" / "tex" / "n.png").replace("\\", "/")


def test_every_time_sample_of_a_sequence_is_reported(tmp_path):
    """A cache sequence authors one path per frame, not a single default."""

    def build(stage):
        vdb = UsdVol.OpenVDBAsset.Define(stage, "/vol/density")
        attr = vdb.CreateFilePathAttr()
        for frame in (1, 2, 3):
            attr.Set(Sdf.AssetPath(f"./cache/smoke.{frame:04d}.vdb"), frame)

    for frame in (1, 2, 3):
        _touch(tmp_path, "cache", f"smoke.{frame:04d}.vdb")
    path = _stage_with(tmp_path, build)

    result = read_asset_paths(path)
    authored = sorted(a["asset_path"] for a in result["assets"])

    assert authored == [f"./cache/smoke.{f:04d}.vdb" for f in (1, 2, 3)]
    assert sorted(a["frame"] for a in result["assets"]) == [1.0, 2.0, 3.0]


def test_a_default_value_is_reported_alongside_its_time_samples(tmp_path):
    """An attribute can hold both, and the default is a real authored reference.

    Time samples shadow it at every numeric time code, so no renderer reads it
    on a frame — but it is what evaluating at the default time returns, and it
    is a path in the file. Omitting it hides a broken reference.
    """

    def build(stage):
        attr = UsdShade.Shader.Define(stage, "/mtl/tex").CreateInput(
            "file", Sdf.ValueTypeNames.Asset
        ).GetAttr()
        attr.Set(Sdf.AssetPath("./tex/default.png"))
        attr.Set(Sdf.AssetPath("./tex/f10.png"), 10)

    _touch(tmp_path, "tex", "default.png")
    _touch(tmp_path, "tex", "f10.png")
    path = _stage_with(tmp_path, build)

    records = {a["asset_path"]: a["frame"] for a in read_asset_paths(path)["assets"]}

    assert records == {"./tex/default.png": None, "./tex/f10.png": 10.0}


def test_a_pure_sequence_gains_no_phantom_default_record(tmp_path):
    """Get() returns None when only samples exist — reading it must add nothing."""

    def build(stage):
        attr = UsdVol.OpenVDBAsset.Define(stage, "/vol/d").CreateFilePathAttr()
        attr.Set(Sdf.AssetPath("./c/s.0001.vdb"), 1)

    path = _stage_with(tmp_path, build)

    frames = [a["frame"] for a in read_asset_paths(path)["assets"]]

    assert frames == [1.0], "a default record would appear here as None"


def test_an_empty_asset_value_is_not_a_missing_file(tmp_path):
    """USD writes a blank asset as @@ — the absence of a reference, not a broken one.

    Classifying it by the same rules as a real path makes it "missing", which
    invents breakage and inflates asset_count, the number a caller reads to
    decide whether a scene is complete.
    """

    def build(stage):
        UsdShade.Shader.Define(stage, "/mtl/tex").CreateInput(
            "file", Sdf.ValueTypeNames.Asset
        ).Set(Sdf.AssetPath(""))

    path = _stage_with(tmp_path, build)

    result = read_asset_paths(path)

    assert result["assets"] == []
    assert result["asset_count"] == 0


def test_an_empty_element_does_not_displace_the_real_ones(tmp_path):
    """A blank slot in an array must vanish without taking its neighbours."""

    def build(stage):
        UsdShade.Shader.Define(stage, "/mtl/tex").CreateInput(
            "files", Sdf.ValueTypeNames.AssetArray
        ).Set([Sdf.AssetPath("./tex/a.png"), Sdf.AssetPath(""), Sdf.AssetPath("./tex/b.png")])

    _touch(tmp_path, "tex", "a.png")
    _touch(tmp_path, "tex", "b.png")
    path = _stage_with(tmp_path, build)

    result = read_asset_paths(path)

    assert [a["asset_path"] for a in result["assets"]] == ["./tex/a.png", "./tex/b.png"]
    assert result["asset_count"] == 2


def test_each_element_of_an_asset_array_gets_its_own_record(tmp_path):
    def build(stage):
        shader = UsdShade.Shader.Define(stage, "/mtl/tex")
        shader.CreateInput("files", Sdf.ValueTypeNames.AssetArray).Set(
            [Sdf.AssetPath("./tex/a.png"), Sdf.AssetPath("./tex/gone.png")]
        )

    _touch(tmp_path, "tex", "a.png")
    path = _stage_with(tmp_path, build)

    states = {a["asset_path"]: a["resolved"] for a in read_asset_paths(path)["assets"]}

    assert states == {"./tex/a.png": "ok", "./tex/gone.png": "missing"}


def test_kind_filters_the_result(tmp_path):
    def build(stage):
        _texture_shader(stage, "/mtl/tex", "./a.png")
        UsdLux.DomeLight.Define(stage, "/dome").CreateTextureFileAttr(
            Sdf.AssetPath("./h.exr")
        )

    path = _stage_with(tmp_path, build)

    only_textures = read_asset_paths(path, kind="texture")

    assert [a["prim_path"] for a in only_textures["assets"]] == ["/mtl/tex"]


def test_prim_path_scopes_the_walk(tmp_path):
    def build(stage):
        _texture_shader(stage, "/keep/tex", "./a.png")
        _texture_shader(stage, "/skip/tex", "./b.png")

    path = _stage_with(tmp_path, build)

    scoped = read_asset_paths(path, prim_path="/keep")

    assert [a["prim_path"] for a in scoped["assets"]] == ["/keep/tex"]


def test_a_relative_prim_path_is_rejected(tmp_path):
    """GetPrimAtPath returns an invalid prim for a relative path, which would
    walk nothing and look like a clean empty result."""
    path = _stage_with(tmp_path, lambda s: _texture_shader(s, "/mtl/tex", "./a.png"))

    with pytest.raises(ValueError, match="absolute"):
        read_asset_paths(path, prim_path="mtl")


@pytest.mark.anyio
async def test_the_tool_reports_a_broken_texture_over_mcp(tmp_path):
    """The end the caller actually sees."""
    path = _stage_with(tmp_path, lambda s: _texture_shader(s, "/mtl/tex", "./tex/gone.png"))

    async with Client(server.app) as client:
        result = await client.call_tool(
            "usd_read_asset_paths", {"path": path, "kind": "texture"}
        )

    assert result.is_error is False, result.content[0].text
    payload = json.loads(result.content[0].text)
    assert payload["assets"][0]["resolved"] == "missing"
    assert payload["assets"][0]["kind"] == "texture"


@pytest.mark.anyio
async def test_an_unknown_kind_is_refused_by_the_schema(tmp_path):
    """kind is a closed set; a typo must not silently return everything."""
    path = _stage_with(tmp_path, lambda s: _texture_shader(s, "/mtl/tex", "./a.png"))

    async with Client(server.app) as client:
        result = await client.call_tool(
            "usd_read_asset_paths", {"path": path, "kind": "textures"}
        )

    assert result.is_error is True


def test_the_result_is_capped_and_says_so(tmp_path):
    def build(stage):
        for i in range(5):
            _texture_shader(stage, f"/mtl/tex{i}", f"./tex/{i}.png")

    path = _stage_with(tmp_path, build)

    capped = read_asset_paths(path, limit=2)

    assert len(capped["assets"]) == 2
    assert capped["truncated"] is True
    assert capped["asset_count"] == 5, "the count reports the whole stage, not the page"
