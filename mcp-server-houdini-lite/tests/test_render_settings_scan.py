"""read_render_settings reports what a render will actually use.

The trap this exists to avoid: UsdRenderProduct does not inherit its
RenderSettings' values through the API. A product with no authored resolution
returns the schema fallback (2048x1080), not the 1920x1080 of the settings that
targets it — a plausible number that is simply wrong. Every RenderSettingsBase
attribute therefore carries where its value came from.

Products are nested under the settings that target them, which also resolves the
case of one product claimed by two settings prims: it appears under each, with
that settings' value. Listing it once would mean choosing between two correct
answers. Products no settings targets appear under orphan_products, where there
is nothing to inherit from.
"""

import json

import pytest
from mcp.client.client import Client
from pxr import Gf, Sdf, Usd, UsdGeom, UsdRender

import server
import usd_tools
from usd_tools import RENDER_MAX_ARRAY_ELEMENTS, UsdOpenError, read_render_settings

FALLBACK_RESOLUTION = [2048, 1080]


def _stage(tmp_path, build):
    path = tmp_path / "r.usda"
    stage = Usd.Stage.CreateNew(str(path))
    build(stage)
    stage.GetRootLayer().Save()
    return str(path)


def _settings(stage, prim_path, resolution=None, products=()):
    rs = UsdRender.Settings.Define(stage, prim_path)
    if resolution is not None:
        rs.CreateResolutionAttr(Gf.Vec2i(*resolution))
    if products:
        rs.CreateProductsRel().SetTargets(list(products))
    return rs


def _product(stage, prim_path, name=None, resolution=None, vars_=()):
    pr = UsdRender.Product.Define(stage, prim_path)
    if name is not None:
        pr.CreateProductNameAttr(name)
    if resolution is not None:
        pr.CreateResolutionAttr(Gf.Vec2i(*resolution))
    if vars_:
        pr.CreateOrderedVarsRel().SetTargets(list(vars_))
    return pr


def _only(result):
    assert len(result["render_settings"]) == 1, result["render_settings"]
    return result["render_settings"][0]


def test_a_settings_prim_reports_its_authored_resolution(tmp_path):
    path = _stage(tmp_path, lambda s: _settings(s, "/Render/rs", resolution=(1920, 1080)))

    entry = _only(read_render_settings(path))

    assert entry["prim_path"] == "/Render/rs"
    assert entry["attributes"]["resolution"] == {"value": [1920, 1080], "source": "authored"}


def test_a_product_inherits_the_resolution_of_the_settings_that_targets_it(tmp_path):
    """The whole point: Get() alone would report the 2048x1080 fallback here."""

    def build(stage):
        pr = _product(stage, "/Render/Products/beauty", name="render/beauty.exr")
        _settings(stage, "/Render/rs", resolution=(1920, 1080), products=[pr.GetPath()])

    path = _stage(tmp_path, build)

    product = _only(read_render_settings(path))["products"][0]

    assert product["attributes"]["resolution"] == {"value": [1920, 1080], "source": "inherited"}
    assert product["attributes"]["resolution"]["value"] != FALLBACK_RESOLUTION


def test_a_product_that_authors_its_own_value_overrides_the_settings(tmp_path):
    def build(stage):
        pr = _product(stage, "/Render/Products/half", resolution=(960, 540))
        _settings(stage, "/Render/rs", resolution=(1920, 1080), products=[pr.GetPath()])

    path = _stage(tmp_path, build)

    product = _only(read_render_settings(path))["products"][0]

    assert product["attributes"]["resolution"] == {"value": [960, 540], "source": "authored"}


def test_an_unset_value_with_no_settings_to_inherit_from_says_fallback(tmp_path):
    """A fallback is schema data, not scene data, and must not read as authored."""
    path = _stage(tmp_path, lambda s: _product(s, "/Render/Products/orphan"))

    product = read_render_settings(path)["orphan_products"][0]

    assert product["attributes"]["resolution"] == {
        "value": FALLBACK_RESOLUTION,
        "source": "fallback",
    }


def test_a_product_no_settings_targets_is_still_found(tmp_path):
    """Walking from the settings' products relationship would miss it entirely."""

    def build(stage):
        pr = _product(stage, "/Render/Products/used")
        _product(stage, "/Render/Products/orphan", name="render/orphan.exr")
        _settings(stage, "/Render/rs", resolution=(1920, 1080), products=[pr.GetPath()])

    path = _stage(tmp_path, build)
    result = read_render_settings(path)

    assert [p["prim_path"] for p in result["orphan_products"]] == ["/Render/Products/orphan"]
    assert result["orphan_products"][0]["product_name"] == "render/orphan.exr"


def test_a_product_claimed_by_two_settings_appears_under_each(tmp_path):
    """Both answers are correct; which one applies depends on the settings used."""

    def build(stage):
        pr = _product(stage, "/Render/Products/shared")
        _settings(stage, "/Render/A", resolution=(1920, 1080), products=[pr.GetPath()])
        _settings(stage, "/Render/B", resolution=(960, 540), products=[pr.GetPath()])

    path = _stage(tmp_path, build)
    result = read_render_settings(path)

    by_settings = {s["prim_path"]: s["products"][0] for s in result["render_settings"]}
    assert by_settings["/Render/A"]["attributes"]["resolution"]["value"] == [1920, 1080]
    assert by_settings["/Render/B"]["attributes"]["resolution"]["value"] == [960, 540]
    assert result["orphan_products"] == [], "a shared product is not an orphan"


def test_renderer_specific_attributes_are_reported(tmp_path):
    """karma:* and friends are what a Houdini user actually came for."""

    def build(stage):
        rs = _settings(stage, "/Render/rs", resolution=(1920, 1080))
        rs.GetPrim().CreateAttribute(
            "karma:global:samplesperpixel", Sdf.ValueTypeNames.Int
        ).Set(9)

    path = _stage(tmp_path, build)

    attrs = _only(read_render_settings(path))["attributes"]

    assert attrs["karma:global:samplesperpixel"] == {"value": 9, "source": "authored"}


def test_an_unauthored_non_schema_attribute_does_not_pad_the_result(tmp_path):
    """Only the RenderSettingsBase set is reported unconditionally."""
    path = _stage(tmp_path, lambda s: _settings(s, "/Render/rs", resolution=(1920, 1080)))

    attrs = _only(read_render_settings(path))["attributes"]

    assert "karma:global:samplesperpixel" not in attrs
    assert "pixelAspectRatio" in attrs, "schema base attributes are always present"


def test_the_camera_relationship_is_resolved_to_a_prim_path(tmp_path):
    def build(stage):
        UsdGeom.Camera.Define(stage, "/cameras/shotcam")
        rs = _settings(stage, "/Render/rs")
        rs.CreateCameraRel().SetTargets(["/cameras/shotcam"])

    path = _stage(tmp_path, build)

    assert _only(read_render_settings(path))["camera"] == "/cameras/shotcam"


def test_a_product_inherits_the_camera_too(tmp_path):
    def build(stage):
        UsdGeom.Camera.Define(stage, "/cameras/shotcam")
        pr = _product(stage, "/Render/Products/beauty")
        rs = _settings(stage, "/Render/rs", products=[pr.GetPath()])
        rs.CreateCameraRel().SetTargets(["/cameras/shotcam"])

    path = _stage(tmp_path, build)

    product = _only(read_render_settings(path))["products"][0]

    assert product["camera"] == "/cameras/shotcam"
    assert product["camera_source"] == "inherited"


def test_ordered_vars_are_reported_in_order(tmp_path):
    def build(stage):
        targets = []
        for var_name, source in (("Ci", "Ci"), ("a", "albedo"), ("N", "normal")):
            v = UsdRender.Var.Define(stage, f"/Render/Vars/{var_name}")
            v.CreateSourceNameAttr(source)
            v.CreateDataTypeAttr("color3f")
            targets.append(v.GetPath())
        pr = _product(stage, "/Render/Products/beauty", vars_=targets)
        _settings(stage, "/Render/rs", products=[pr.GetPath()])

    path = _stage(tmp_path, build)

    product = _only(read_render_settings(path))["products"][0]

    assert [v["source_name"] for v in product["vars"]] == ["Ci", "albedo", "normal"]
    assert product["vars"][0]["data_type"] == "color3f"


def test_the_stage_names_its_default_settings_prim(tmp_path):
    """Which settings a render uses by default is stage metadata, not a guess."""

    def build(stage):
        _settings(stage, "/Render/rs", resolution=(1920, 1080))
        stage.SetMetadata("renderSettingsPrimPath", "/Render/rs")

    path = _stage(tmp_path, build)

    assert read_render_settings(path)["default_render_settings_prim"] == "/Render/rs"


def test_no_default_is_reported_as_null_not_invented(tmp_path):
    path = _stage(tmp_path, lambda s: _settings(s, "/Render/rs"))

    assert read_render_settings(path)["default_render_settings_prim"] is None


def test_a_stage_with_no_render_prims_is_empty_not_an_error(tmp_path):
    path = _stage(tmp_path, lambda s: UsdGeom.Xform.Define(s, "/geo"))

    result = read_render_settings(path)

    assert result["render_settings"] == []
    assert result["orphan_products"] == []


def test_a_dangling_product_target_is_reported_not_dropped(tmp_path):
    """A relationship can name a prim that is not there; silence would hide it."""

    def build(stage):
        rs = UsdRender.Settings.Define(stage, "/Render/rs")
        rs.CreateProductsRel().SetTargets(["/Render/Products/gone"])

    path = _stage(tmp_path, build)

    entry = _only(read_render_settings(path))

    assert entry["missing_product_targets"] == ["/Render/Products/gone"]
    assert entry["products"] == []


def test_a_missing_file_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_render_settings(str(tmp_path / "nope.usda"))


@pytest.mark.anyio
async def test_the_tool_reports_the_inherited_resolution_over_mcp(tmp_path):
    """The end a caller actually sees, on the case the tool exists for."""

    def build(stage):
        pr = _product(stage, "/Render/Products/beauty", name="render/beauty.exr")
        _settings(stage, "/Render/rs", resolution=(1920, 1080), products=[pr.GetPath()])

    path = _stage(tmp_path, build)

    async with Client(server.app) as client:
        result = await client.call_tool("usd_read_render_settings", {"path": path})

    assert result.is_error is False, result.content[0].text
    payload = json.loads(result.content[0].text)
    product = payload["render_settings"][0]["products"][0]
    assert product["attributes"]["resolution"] == {
        "value": [1920, 1080],
        "source": "inherited",
    }


def test_a_products_target_that_is_not_a_product_is_reported_as_missing(tmp_path):
    """A relationship can name any prim. Reading a Mesh as a product yields a
    record with no attributes and a made-up identity, which is worse than
    saying the target could not be used."""

    def build(stage):
        UsdGeom.Mesh.Define(stage, "/geo/notaproduct")
        rs = UsdRender.Settings.Define(stage, "/Render/rs")
        rs.CreateProductsRel().SetTargets(["/geo/notaproduct"])

    path = _stage(tmp_path, build)

    entry = _only(read_render_settings(path))

    assert entry["products"] == []
    assert entry["missing_product_targets"] == ["/geo/notaproduct"]


def test_a_var_target_that_is_not_a_var_is_reported_as_missing(tmp_path):
    def build(stage):
        UsdGeom.Mesh.Define(stage, "/geo/notavar")
        pr = _product(stage, "/Render/Products/beauty")
        pr.CreateOrderedVarsRel().SetTargets(["/geo/notavar"])
        _settings(stage, "/Render/rs", products=[pr.GetPath()])

    path = _stage(tmp_path, build)

    product = _only(read_render_settings(path))["products"][0]

    assert product["vars"] == []
    assert product["missing_var_targets"] == ["/geo/notavar"]


def test_render_prims_inside_a_payload_need_load_payloads(tmp_path):
    """Without it the answer is an empty list, indistinguishable from a scene
    that has no render settings at all."""
    inner = tmp_path / "inner.usda"
    inner_stage = Usd.Stage.CreateNew(str(inner))
    UsdRender.Settings.Define(inner_stage, "/Render/rs")
    inner_stage.SetDefaultPrim(inner_stage.GetPrimAtPath("/Render"))
    inner_stage.GetRootLayer().Save()

    def build(stage):
        stage.DefinePrim("/World").GetPayloads().AddPayload("./inner.usda")

    path = _stage(tmp_path, build)

    assert read_render_settings(path)["render_settings"] == []

    loaded = read_render_settings(path, load_payloads=True)
    assert [s["prim_path"] for s in loaded["render_settings"]] == ["/World/rs"]


def test_a_long_array_attribute_is_capped(tmp_path):
    """An authored array goes straight into the MCP response; unbounded, a big
    one would dominate it."""

    def build(stage):
        rs = _settings(stage, "/Render/rs")
        rs.GetPrim().CreateAttribute(
            "karma:global:manylayers", Sdf.ValueTypeNames.IntArray
        ).Set(list(range(500)))

    path = _stage(tmp_path, build)

    value = _only(read_render_settings(path))["attributes"]["karma:global:manylayers"]["value"]

    assert len(value["values"]) == RENDER_MAX_ARRAY_ELEMENTS
    assert value["_array_total"] == 500, "the true length is still reported"
    assert value["_truncated"] is True
    assert value["values"][0] == 0, "the cap keeps the front of the array"


def test_a_missing_render_schema_is_reported_as_a_usd_error(tmp_path):
    """A USD build without the render schemas would otherwise raise
    AttributeError from deep inside, which the handler does not translate."""

    class _EmptyRegistry:
        def FindConcretePrimDefinition(self, name):
            return None

    path = _stage(tmp_path, lambda s: _settings(s, "/Render/rs"))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(usd_tools.Usd, "SchemaRegistry", _EmptyRegistry)
        with pytest.raises(UsdOpenError, match="render schema"):
            read_render_settings(path)
