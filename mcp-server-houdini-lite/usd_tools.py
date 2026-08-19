"""
usd_tools.py — USD file inspection and authoring utilities

Read-only functions for inspecting USD files without loading geometry:
  read_layer_metadata       — full layer metadata (custom, time, units, vars)
  read_layer_hierarchy      — prim hierarchy from a single layer (no composition)
  read_composed_hierarchy   — full composed hierarchy (refs/sublayers resolved,
                               payloads deferred)
  read_composition_arcs     — direct sublayers, references, and payloads declared
                               in a single layer (no composition)
  read_cameras              — all Camera prims with lens/projection attributes
  read_prim_attributes      — attribute names/types/time-sample info on a prim
  read_attribute_value      — value of a single named attribute on a prim
  read_render_settings      — RenderSettings / RenderProduct prims and what a
                               render driven by each would actually use
  read_layer_dependencies   — every layer the scene needs, walked transitively
  read_asset_paths          — every asset-valued attribute on a composed stage
                               (textures, light HDRIs, VDB caches), with the
                               absolute path each one resolves to

Write functions:
  write_layer_metadata           — partial update of layer metadata fields
  create_expressions_layer       — create a new USD layer containing only
                                    expressionVariables
  add_sublayers                  — prepend or append sublayer asset paths
  insert_sublayers               — insert sublayer asset paths at an explicit index
  remove_sublayers               — remove sublayer asset paths by exact string
"""

import re
from collections import deque
from pathlib import Path

from pxr import Ar, Sdf, Tf, Usd, UsdGeom, UsdLux, UsdRender, UsdShade, UsdVol, Gf, Vt

# Collect all Gf quaternion types (Quath was added in later USD versions)
_GF_QUAT_TYPES = tuple(
    t for t in (getattr(Gf, n, None) for n in ("Quatf", "Quatd", "Quath"))
    if t is not None
)

# Specifier token → human-readable string
_SPECIFIER_NAMES = {
    Sdf.SpecifierDef:   "def",
    Sdf.SpecifierOver:  "over",
    Sdf.SpecifierClass: "class",
}


class UsdOpenError(Exception):
    pass


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


# Layer metadata fields supported by read_layer_metadata / write_layer_metadata.
# Each entry maps a JSON key to ("kind", spec) where kind is one of:
#   "first_class" — uses HasXxx() / SetXxx() / ClearXxx() methods on Sdf.Layer
#   "generic"     — stored at the pseudo-root via GetField/SetField/EraseField
_LAYER_METADATA_SPEC = {
    "defaultPrim":         ("first_class", "DefaultPrim"),
    "startTimeCode":       ("first_class", "StartTimeCode"),
    "endTimeCode":         ("first_class", "EndTimeCode"),
    "framesPerSecond":     ("first_class", "FramesPerSecond"),
    "timeCodesPerSecond":  ("first_class", "TimeCodesPerSecond"),
    "customLayerData":     ("first_class", "CustomLayerData"),
    "expressionVariables": ("first_class", "ExpressionVariables"),
    "upAxis":              ("generic",     "upAxis"),
    "metersPerUnit":       ("generic",     "metersPerUnit"),
}


def _read_first_class(layer, suffix):
    if not getattr(layer, f"Has{suffix}")():
        return None
    attr_name = suffix[0].lower() + suffix[1:]
    value = getattr(layer, attr_name)
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)  # TfToken / Sdf.Path → str


def _read_generic(layer, field_name):
    spec = layer.pseudoRoot
    if not spec.HasInfo(field_name):
        return None
    return spec.GetInfo(field_name)


def read_layer_metadata(path: str) -> dict:
    """
    Read layer-level metadata from a single USD layer without composition.

    Returns a dict with keys:
        path            — input file path
        format          — file format id (e.g. "usda", "usdc", "usd")
        plus one key per supported metadata field (defaultPrim, startTimeCode,
        endTimeCode, framesPerSecond, timeCodesPerSecond, metersPerUnit, upAxis,
        customLayerData, expressionVariables). A field that has not been authored
        in the file reports value `None` (distinguishing "unauthored" from a
        legitimate authored zero / empty value).

    Raises:
        FileNotFoundError  — file does not exist
        UsdOpenError       — file could not be opened as a USD layer
    """
    _assert_exists(path)
    layer = _open_layer(path)

    result = {
        "path": path,
        "format": layer.GetFileFormat().formatId,
    }
    for key, (kind, spec) in _LAYER_METADATA_SPEC.items():
        if kind == "first_class":
            result[key] = _read_first_class(layer, spec)
        else:
            result[key] = _read_generic(layer, spec)
    return result


# Allowed leaf value types for expressionVariables (per OpenUSD docs).
# Bool must be checked before int (bool is a subclass of int in Python).
def _is_valid_expr_var_value(v):
    if isinstance(v, bool):
        return True
    if isinstance(v, int):
        return True
    if isinstance(v, str):
        return True
    if isinstance(v, list):
        if not v:
            return True  # empty list is fine
        first = v[0]
        if isinstance(first, bool):
            return all(isinstance(x, bool) for x in v)
        if isinstance(first, int):
            return all(isinstance(x, int) and not isinstance(x, bool) for x in v)
        if isinstance(first, str):
            return all(isinstance(x, str) for x in v)
        return False
    return False


def _validate_expression_variables(value):
    if not isinstance(value, dict):
        raise UsdOpenError(
            f"expressionVariables must be a dict, got {type(value).__name__}"
        )
    for k, v in value.items():
        if not isinstance(k, str):
            raise UsdOpenError(
                f"expressionVariables keys must be strings, got {type(k).__name__}"
            )
        if not _is_valid_expr_var_value(v):
            raise UsdOpenError(
                f"expressionVariables[{k!r}] has unsupported value/type "
                f"{v!r} ({type(v).__name__}); allowed: str, bool, int, "
                f"or homogeneous list of those"
            )


def _write_first_class(layer, suffix, value):
    if value is None:
        getattr(layer, f"Clear{suffix}")()
        return
    if suffix == "ExpressionVariables":
        _validate_expression_variables(value)
    elif suffix == "CustomLayerData":
        if not isinstance(value, dict):
            raise UsdOpenError(
                f"customLayerData must be a dict, got {type(value).__name__}"
            )
    attr_name = suffix[0].lower() + suffix[1:]
    setattr(layer, attr_name, value)


def _write_generic(layer, field_name, value):
    spec = layer.pseudoRoot
    if value is None:
        spec.ClearInfo(field_name)
    else:
        spec.SetInfo(field_name, value)


def write_layer_metadata(
    path: str,
    metadata: dict,
    output_path: str | None = None,
) -> dict:
    """
    Update layer-level metadata on a USD layer.

    Only fields present in `metadata` are touched. A field value of None means
    "clear back to unauthored". Dict-valued fields (customLayerData /
    expressionVariables) are fully replaced; to merge, read first and pass the
    merged result.

    If `output_path` is None, the file is saved in-place (mode = "in_place").
    If `output_path` is provided, the layer is exported to a new file (mode =
    "export") and the source file is not touched; `output_path` must not exist
    already.

    Returns a dict describing what was applied.

    Raises:
        FileNotFoundError — source file does not exist
        UsdOpenError      — file could not be opened, is read-only, has an
                            unknown field name, or fails value validation
    """
    if not isinstance(metadata, dict):
        raise UsdOpenError(
            f"metadata must be a dict, got {type(metadata).__name__}"
        )

    unknown = [k for k in metadata if k not in _LAYER_METADATA_SPEC]
    if unknown:
        raise UsdOpenError(
            f"unknown metadata field(s): {unknown}; "
            f"allowed: {sorted(_LAYER_METADATA_SPEC.keys())}"
        )

    _assert_exists(path)
    source = _open_layer(path)

    if output_path is not None and Path(output_path).exists():
        raise UsdOpenError(
            f"output_path already exists, refusing to overwrite: {output_path}"
        )

    # In-place mode mutates the cached source layer; export mode works on an
    # anonymous copy so the layer cache for `path` is not polluted with edits
    # that never reach disk for that path.
    if output_path is None:
        if not source.permissionToEdit:
            raise UsdOpenError(f"layer is not editable in-place: {path}")
        target = source
    else:
        target = Sdf.Layer.CreateAnonymous()
        target.TransferContent(source)

    applied = []
    for key, value in metadata.items():
        kind, spec = _LAYER_METADATA_SPEC[key]
        if kind == "first_class":
            _write_first_class(target, spec, value)
        else:
            _write_generic(target, spec, value)
        applied.append({
            "field":  key,
            "action": "clear" if value is None else "set",
            **({} if value is None else {"new": value}),
        })

    if output_path is None:
        target.Save()
        mode = "in_place"
        out = path
    else:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        if not target.Export(output_path):
            raise UsdOpenError(f"failed to export layer to: {output_path}")
        mode = "export"
        out = output_path

    return {
        "path":        path,
        "output_path": out,
        "mode":        mode,
        "applied":     applied,
    }


def create_expressions_layer(
    output_path: str,
    expression_variables: dict,
) -> dict:
    """
    Create a new USD layer at output_path containing only the given
    expressionVariables metadata (no prims, no other layer metadata).

    The file format is inferred from output_path's extension (.usd / .usda /
    .usdc). output_path must not exist.

    Raises:
        UsdOpenError — output_path exists, expression_variables is empty or
                       contains unsupported value types, or layer creation
                       fails.
    """
    if not isinstance(expression_variables, dict) or not expression_variables:
        raise UsdOpenError(
            "expression_variables must be a non-empty dict"
        )
    _validate_expression_variables(expression_variables)

    out = Path(output_path)
    if out.exists():
        raise UsdOpenError(
            f"output_path already exists, refusing to overwrite: {output_path}"
        )
    out.parent.mkdir(parents=True, exist_ok=True)

    layer = Sdf.Layer.CreateNew(output_path)
    if layer is None:
        raise UsdOpenError(f"could not create USD layer: {output_path}")

    layer.expressionVariables = expression_variables
    layer.Save()

    return {
        "status":               "ok",
        "output_path":          output_path,
        "expression_variables": dict(expression_variables),
    }


def read_layer_hierarchy(path: str, max_depth: int = 0) -> dict:
    """
    Read the prim hierarchy from a single USD layer without composition.

    References, sublayers, and payloads are NOT resolved — only prims
    defined in this file are returned.

    Args:
        path       — absolute path to a USD file
        max_depth  — maximum hierarchy depth to include (0 = unlimited).
                     Depth 1 = root prims, depth 2 = their children, etc.

    Returns a dict with keys:
        path        — input file path
        composed    — False
        prim_count  — number of prims returned
        prims       — list of {path, type, specifier, depth}

    Raises:
        FileNotFoundError  — file does not exist
        UsdOpenError       — file could not be opened as a USD layer
    """
    _assert_exists(path)
    layer = _open_layer(path)

    prims = []

    def _visit(sdf_path: Sdf.Path) -> None:
        if not sdf_path.IsPrimPath():
            return
        depth = sdf_path.pathElementCount
        if max_depth > 0 and depth > max_depth:
            return
        spec = layer.GetPrimAtPath(sdf_path)
        prims.append({
            "path":      str(sdf_path),
            "type":      spec.typeName if spec else "",
            "specifier": _SPECIFIER_NAMES.get(spec.specifier, "unknown") if spec else "unknown",
            "depth":     depth,
        })

    layer.Traverse(layer.pseudoRoot.path, _visit)

    return {
        "path":       path,
        "composed":   False,
        "prim_count": len(prims),
        "prims":      prims,
    }


def read_composed_hierarchy(path: str, max_depth: int = 0) -> dict:
    """
    Read the full composed USD hierarchy with references and sublayers resolved.

    Payloads are NOT loaded (LoadNone), so heavy geometry data is never read.

    Args:
        path       — absolute path to a USD file
        max_depth  — maximum hierarchy depth to include (0 = unlimited)

    Returns a dict with keys:
        path        — input file path
        composed    — True
        prim_count  — number of prims returned
        prims       — list of {path, type, is_active, depth}

    Raises:
        FileNotFoundError  — file does not exist
        UsdOpenError       — stage could not be opened
    """
    _assert_exists(path)
    stage = _open_stage(path, load=Usd.Stage.LoadNone)

    prims = []
    for prim in stage.TraverseAll():
        prim_path = prim.GetPath()
        depth = prim_path.pathElementCount
        if max_depth > 0 and depth > max_depth:
            continue
        prims.append({
            "path":      str(prim_path),
            "type":      prim.GetTypeName(),
            "is_active": prim.IsActive(),
            "depth":     depth,
        })

    return {
        "path":       path,
        "composed":   True,
        "prim_count": len(prims),
        "prims":      prims,
    }


# A resolver scheme, e.g. "omniverse://…" or "asset:library/model.usda". USD
# dispatches on the scheme, with or without the double slash. Two or more
# characters before the colon keeps Windows drive letters (C:/…, C:\…) out.
_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]+:")


def _resolve_asset_path(layer, asset_path: str) -> dict:
    """Say where an authored asset path points, or why that cannot be determined.

    Path arithmetic answers this only for filesystem paths. An asset-resolver URI
    is the resolver's business — ComputeAbsolutePath would return
    "omniverse:/server/a.usd" for "omniverse://server/a.usd", a broken string
    rather than an answer — and an unexpanded expression variable is not yet a
    path at all. A bare relative name uses search semantics: USD anchors it when
    the file is found and leaves it alone when it is not, so an unchanged result
    means the search failed, not that the path is already absolute.
    """
    # Strip decorations first: ":SDF_FORMAT_ARGS:…" passes options to the file
    # format and "bundle.usdz[inner.usd]" names a layer inside a package.
    # Classifying before stripping reads "a.usd:SDF_FORMAT_ARGS:fps=24" as a
    # resolver scheme, since everything up to the first colon looks like one.
    outer = Sdf.Layer.SplitIdentifier(asset_path)[0]
    outer = Ar.SplitPackageRelativePathOuter(outer)[0]

    if outer == "":
        # An internal reference or payload: it targets a prim in this layer
        # stack, so there is no asset to locate rather than one that was
        # looked for and missed.
        return {"resolved_path": None, "resolved": "internal"}
    if _URI_SCHEME_RE.match(outer):
        return {"resolved_path": None, "resolved": "uri"}
    if "`" in outer or "${" in outer:
        return {"resolved_path": None, "resolved": "expression"}

    absolute = layer.ComputeAbsolutePath(outer)
    if absolute == outer and not Path(outer).is_absolute():
        return {"resolved_path": None, "resolved": "unresolved"}

    absolute = absolute.replace("\\", "/")
    exists = Path(absolute).is_file()
    return {"resolved_path": absolute, "resolved": "ok" if exists else "missing"}


def read_composition_arcs(path: str) -> dict:
    """
    List the direct composition arcs declared in a single USD layer:
    sublayers, references, and payloads. No composition is performed —
    only arcs explicitly written in this file are returned.

    Returns a dict with keys:
        path        — input file path
        sublayers   — ordered list of sublayer asset paths as authored (weakest last)
        sublayers_resolved — same order, each {asset_path, resolved_path, resolved}
        references  — list of {prim_path, asset_path, target_prim_path,
                               resolved_path, resolved}
        payloads    — same shape as references

    asset_path is always the string as authored, which is what replace_anchors
    matches on. resolved_path is where it points, or None when that cannot be
    determined by path arithmetic; resolved says which: ok, missing, unresolved,
    uri, expression or internal.

    Raises:
        FileNotFoundError  — file does not exist
        UsdOpenError       — file could not be opened as a USD layer
    """
    _assert_exists(path)
    layer = _open_layer(path)

    sublayers = list(layer.subLayerPaths)
    sublayers_resolved = [
        {"asset_path": a, **_resolve_asset_path(layer, a)} for a in sublayers
    ]

    references: list[dict] = []
    payloads:   list[dict] = []

    def _collect(sdf_path: Sdf.Path) -> None:
        if not sdf_path.IsPrimPath():
            return
        spec = layer.GetPrimAtPath(sdf_path)
        if spec is None:
            return
        prim_str = str(sdf_path)
        for ref in spec.referenceList.GetAppliedItems():
            references.append({
                "prim_path":        prim_str,
                "asset_path":       ref.assetPath,
                "target_prim_path": str(ref.primPath),
                **_resolve_asset_path(layer, ref.assetPath),
            })
        for pay in spec.payloadList.GetAppliedItems():
            payloads.append({
                "prim_path":        prim_str,
                "asset_path":       pay.assetPath,
                "target_prim_path": str(pay.primPath),
                **_resolve_asset_path(layer, pay.assetPath),
            })

    layer.Traverse(layer.pseudoRoot.path, _collect)

    return {
        "path":       path,
        "sublayers":  sublayers,
        "sublayers_resolved": sublayers_resolved,
        "references": references,
        "payloads":   payloads,
    }


def replace_anchors(path: str, replacements: dict[str, str]) -> dict:
    """
    Replace asset paths for sublayers, references, and payloads in a USD layer.

    Matches anchor strings exactly as stored in the file (the same strings
    returned by read_composition_arcs). Saves the layer in-place.

    Args:
        path         — absolute path to a USD file to modify
        replacements — {old_asset_path: new_asset_path}

    Returns a dict with keys:
        path           — input file path
        replaced       — list of replaced anchor dicts (type, old, new, prim_path)
        total_replaced — count of replaced anchors

    Raises:
        FileNotFoundError — file does not exist
        UsdOpenError      — file could not be opened as a USD layer
    """
    _assert_exists(path)
    layer = _open_layer(path)

    replaced: list[dict] = []

    with Sdf.ChangeBlock():
        for i, p in enumerate(list(layer.subLayerPaths)):
            if p in replacements:
                layer.subLayerPaths[i] = replacements[p]
                replaced.append({"type": "sublayer", "old": p, "new": replacements[p]})

        def _visit(sdf_path: Sdf.Path) -> None:
            spec = layer.GetObjectAtPath(sdf_path)
            if not isinstance(spec, Sdf.PrimSpec):
                return
            prim_str = str(sdf_path)
            for ref in spec.referenceList.GetAppliedItems():
                if ref.assetPath in replacements:
                    new_ref = Sdf.Reference(
                        assetPath=replacements[ref.assetPath],
                        primPath=ref.primPath,
                        layerOffset=ref.layerOffset,
                        customData=ref.customData,
                    )
                    spec.referenceList.ReplaceItemEdits(ref, new_ref)
                    replaced.append({"type": "reference", "prim_path": prim_str,
                                     "old": ref.assetPath, "new": replacements[ref.assetPath]})
            for pay in spec.payloadList.GetAppliedItems():
                if pay.assetPath in replacements:
                    new_pay = Sdf.Payload(
                        assetPath=replacements[pay.assetPath],
                        primPath=pay.primPath,
                        layerOffset=pay.layerOffset,
                    )
                    spec.payloadList.ReplaceItemEdits(pay, new_pay)
                    replaced.append({"type": "payload", "prim_path": prim_str,
                                     "old": pay.assetPath, "new": replacements[pay.assetPath]})

        layer.Traverse(layer.pseudoRoot.path, _visit)

    layer.Save()
    return {"path": path, "replaced": replaced, "total_replaced": len(replaced)}


def read_cameras(path: str, frame: float | None = None) -> dict:
    """
    Find all Camera prims in a fully composed USD stage and read their
    standard lens and projection attributes.

    The stage is opened with LoadNone — references and sublayers ARE resolved,
    but payload geometry is NOT loaded.

    Args:
        path   — absolute path to a USD file
        frame  — time code to evaluate (e.g. 1001.0). If None, uses
                 Usd.TimeCode.Default() which returns the static/default value.

    Returns a dict with keys:
        path          — input file path
        frame         — the frame used (null if default time was used)
        camera_count  — number of Camera prims found
        cameras       — list of camera dicts (see below)

    Each camera dict:
        prim_path                  — USD scene path
        is_active                  — bool
        projection                 — "perspective" | "orthographic" | null
        focal_length               — float (tenths of a scene unit) | null
        horizontal_aperture        — float | null
        vertical_aperture          — float | null
        horizontal_aperture_offset — float | null
        vertical_aperture_offset   — float | null
        clipping_range             — [near, far] | null
        f_stop                     — float (0 = disabled) | null
        focus_distance             — float | null
        shutter_open               — float | null
        shutter_close              — float | null

    Raises:
        FileNotFoundError  — file does not exist
        UsdOpenError       — stage could not be opened
    """
    _assert_exists(path)
    stage = _open_stage(path, load=Usd.Stage.LoadNone)

    time = Usd.TimeCode(frame) if frame is not None else Usd.TimeCode.Default()
    cameras = []

    for prim in stage.TraverseAll():
        if prim.GetTypeName() != "Camera":
            continue

        cam = UsdGeom.Camera(prim)

        def _get(attr_fn):
            try:
                return attr_fn().Get(time)
            except Exception:
                return None

        cameras.append({
            "prim_path":                  str(prim.GetPath()),
            "is_active":                  prim.IsActive(),
            "projection":                 _get(cam.GetProjectionAttr),
            "focal_length":               _get(cam.GetFocalLengthAttr),
            "horizontal_aperture":        _get(cam.GetHorizontalApertureAttr),
            "vertical_aperture":          _get(cam.GetVerticalApertureAttr),
            "horizontal_aperture_offset": _get(cam.GetHorizontalApertureOffsetAttr),
            "vertical_aperture_offset":   _get(cam.GetVerticalApertureOffsetAttr),
            "clipping_range":             _gf_to_json(_get(cam.GetClippingRangeAttr)),
            "f_stop":                     _get(cam.GetFStopAttr),
            "focus_distance":             _get(cam.GetFocusDistanceAttr),
            "shutter_open":               _get(cam.GetShutterOpenAttr),
            "shutter_close":              _get(cam.GetShutterCloseAttr),
        })

    return {
        "path":         path,
        "frame":        frame,
        "camera_count": len(cameras),
        "cameras":      cameras,
    }


# Authored arrays go straight into the MCP response. Render attributes are
# normally short — includedPurposes and the like — but nothing stops a scene
# from authoring a long one, so the serialized value is capped the way
# read_attribute_value caps its own.
RENDER_MAX_ARRAY_ELEMENTS = 100


def _render_base_attribute_names() -> tuple[str, ...]:
    """The attributes a RenderProduct takes from the RenderSettings targeting it.

    Derived from the schema rather than written out here: the inheritable set is
    exactly what the two prim types have in common, so a USD release that adds
    or retires one stays correct without an edit. camera is excluded because a
    relationship needs its targets resolved, not its value read.
    """
    registry = Usd.SchemaRegistry()
    settings = registry.FindConcretePrimDefinition("RenderSettings")
    product = registry.FindConcretePrimDefinition("RenderProduct")
    if settings is None or product is None:
        # A USD build without the render schema. Returning an empty set instead
        # would drop the inheritable attributes and read as "nothing was set".
        raise UsdOpenError(
            "this USD build does not provide the render schema "
            "(RenderSettings / RenderProduct); cannot read render settings"
        )
    return tuple(sorted((set(settings.GetPropertyNames())
                         & set(product.GetPropertyNames())) - {"camera"}))


def _serialize_render_value(value):
    return _value_to_json(value, max_elements=RENDER_MAX_ARRAY_ELEMENTS)


def _attribute_record(prim, name: str, inherit_from=None) -> dict | None:
    """One attribute's value plus where that value came from.

    The distinction is the reason this function exists. UsdRenderProduct does
    not consult its RenderSettings, so an unauthored resolution reads back as
    the schema fallback of 2048x1080 — a number that looks like a real setting
    and is not one. Reporting the source makes the difference visible instead
    of leaving the caller to assume.
    """
    attr = prim.GetAttribute(name)
    if attr and attr.HasAuthoredValue():
        return {"value": _serialize_render_value(attr.Get()), "source": "authored"}
    if inherit_from is not None:
        parent = inherit_from.GetAttribute(name)
        if parent and parent.HasAuthoredValue():
            return {"value": _serialize_render_value(parent.Get()), "source": "inherited"}
    if not attr:
        return None
    return {"value": _serialize_render_value(attr.Get()), "source": "fallback"}


def _render_attributes(prim, base_names: tuple[str, ...], inherit_from=None) -> dict:
    """The base set unconditionally, plus everything else actually authored.

    The base set is always present because its fallbacks are meaningful — they
    are what the renderer will use. Everything else is reported only when
    authored, which is what surfaces renderer-specific settings such as
    karma:global:samplesperpixel without padding the result with schema
    defaults nobody set.
    """
    attributes = {}
    for name in base_names:
        record = _attribute_record(prim, name, inherit_from)
        if record is not None:
            attributes[name] = record

    for attr in prim.GetAttributes():
        name = attr.GetName()
        if name in attributes or not attr.HasAuthoredValue():
            continue
        attributes[name] = {"value": _serialize_render_value(attr.Get()), "source": "authored"}
    return attributes


def _relationship_target(prim, name: str) -> str | None:
    rel = prim.GetRelationship(name)
    if not rel:
        return None
    targets = rel.GetTargets()
    return str(targets[0]) if targets else None


def _read_render_var(prim) -> dict:
    def _get(name):
        attr = prim.GetAttribute(name)
        return _value_to_json(attr.Get()) if attr else None

    return {
        "prim_path":   str(prim.GetPath()),
        "data_type":   _get("dataType"),
        "source_name": _get("sourceName"),
        "source_type": _get("sourceType"),
    }


def _read_render_product(stage, prim, base_names, inherit_from=None) -> dict:
    camera = _relationship_target(prim, "camera")
    camera_source = "authored" if camera else None
    if camera is None and inherit_from is not None:
        camera = _relationship_target(inherit_from, "camera")
        camera_source = "inherited" if camera else None

    variables, missing_vars = [], []
    rel = prim.GetRelationship("orderedVars")
    for target in (rel.GetTargets() if rel else []):
        var_prim = stage.GetPrimAtPath(target)
        if var_prim and var_prim.IsA(UsdRender.Var):
            variables.append(_read_render_var(var_prim))
        else:
            # A relationship can name any prim. Reading a non-Var as one yields
            # a record of empty fields under a borrowed identity, which hides
            # the mistake instead of reporting it.
            missing_vars.append(str(target))

    product_name = prim.GetAttribute("productName")
    product_type = prim.GetAttribute("productType")
    return {
        "prim_path":            str(prim.GetPath()),
        "product_name":         _value_to_json(product_name.Get()) if product_name else None,
        "product_type":         _value_to_json(product_type.Get()) if product_type else None,
        "camera":               camera,
        "camera_source":        camera_source,
        "attributes":           _render_attributes(prim, base_names, inherit_from),
        "vars":                 variables,
        "missing_var_targets":  missing_vars,
    }


def read_render_settings(path: str, load_payloads: bool = False) -> dict:
    """
    Find the RenderSettings and RenderProduct prims on a stage and report what
    a render driven by each would actually use.

    Products are nested under the settings that target them. That is not
    presentation: a product's unauthored attributes come from the settings, so
    the same product listed under two settings prims genuinely has two
    resolutions, and a flat list would have to discard one of them. Products no
    settings targets are listed separately, since they have nothing to inherit.

    Args:
        path          — absolute path to a USD file
        load_payloads — load USD payloads. Required when the render prims are
                        defined inside one: without it they are simply absent,
                        and an empty result is indistinguishable from a scene
                        that declares no render settings at all.

    Returns a dict with keys:
        path                          — input file path
        default_render_settings_prim  — the stage's renderSettingsPrimPath
                                        metadata, or null if unauthored
        render_settings               — list of settings dicts (see below)
        orphan_products               — products no settings targets, same shape
                                        as a nested product

    Each settings dict:
        prim_path              — USD scene path
        camera                 — first target of the camera relationship, or null
        attributes             — name -> {value, source}, see below
        products               — list of product dicts
        missing_product_targets — targets of the products relationship that name
                                 a prim that is not on the stage

    Each product dict:
        prim_path, product_name, product_type
        camera / camera_source — resolved target and whether it came from the
                                 product or the settings
        attributes             — name -> {value, source}
        vars                   — ordered RenderVar dicts (prim_path, data_type,
                                 source_name, source_type)
        missing_var_targets    — orderedVars targets that are not on the stage

    Array values are reported as {"_array_total": n, "_truncated": bool,
    "values": [...]}, capped at RENDER_MAX_ARRAY_ELEMENTS.

    `source` is one of:
        authored  — set on this prim
        inherited — set on the RenderSettings that targets this product
        fallback  — neither; this is the schema default, not scene data

    Raises:
        FileNotFoundError  — file does not exist
        UsdOpenError       — stage could not be opened
    """
    _assert_exists(path)
    load = Usd.Stage.LoadAll if load_payloads else Usd.Stage.LoadNone
    stage = _open_stage(path, load=load)
    base_names = _render_base_attribute_names()

    settings_prims = []
    product_prims = {}
    for prim in stage.TraverseAll():
        # IsA rather than an exact type-name match, so a schema derived from
        # these — a renderer shipping its own settings type — is still found.
        if prim.IsA(UsdRender.Settings):
            settings_prims.append(prim)
        elif prim.IsA(UsdRender.Product):
            product_prims[str(prim.GetPath())] = prim

    claimed = set()
    render_settings = []
    for prim in settings_prims:
        products, missing = [], []
        rel = prim.GetRelationship("products")
        for target in (rel.GetTargets() if rel else []):
            key = str(target)
            product_prim = product_prims.get(key)
            if product_prim is None:
                missing.append(key)
                continue
            claimed.add(key)
            products.append(_read_render_product(stage, product_prim, base_names, prim))

        render_settings.append({
            "prim_path":               str(prim.GetPath()),
            "camera":                  _relationship_target(prim, "camera"),
            "attributes":              _render_attributes(prim, base_names),
            "products":                products,
            "missing_product_targets": missing,
        })

    orphans = [
        _read_render_product(stage, product_prims[key], base_names)
        for key in sorted(product_prims)
        if key not in claimed
    ]

    default_prim = stage.GetMetadata("renderSettingsPrimPath") or None
    return {
        "path":                         path,
        "default_render_settings_prim": str(default_prim) if default_prim else None,
        "render_settings":              render_settings,
        "orphan_products":              orphans,
    }


def _validate_limit(limit: int, name: str = "limit") -> None:
    """A negative bound is a slice index, not a cap.

    The MCP schemas reject one, but these functions are also called directly,
    and there `attrs[:-1]` quietly drops the last record instead of failing —
    a result indistinguishable from a genuine one. Zero stays legal: asking for
    none of them is coherent, and the truncation flags say so honestly.
    """
    if limit < 0:
        raise ValueError(f"{name} must be zero or greater, got: {limit}")


_ASSET_TYPES = frozenset({Sdf.ValueTypeNames.Asset, Sdf.ValueTypeNames.AssetArray})

_UDIM_TOKEN = "<UDIM>"


def _asset_kind(prim, attr_name: str) -> str:
    """Label an asset attribute by what declares it.

    The scan itself is by attribute type, so nothing asset-valued escapes it;
    this only says what the path is for. A DomeLight is not a UsdShade.Shader,
    so classifying by prim type alone — the obvious approach — would leave the
    HDRI of a lighting scene out of the "texture" bucket entirely.
    """
    if UsdVol.OpenVDBAsset(prim):
        return "volume"
    if prim.HasAPI(UsdLux.LightAPI):
        return "light"
    if UsdShade.Shader(prim) and attr_name.startswith("inputs:"):
        return "texture"
    return "other"


def _classify_asset(asset_path) -> tuple[str | None, str]:
    """Turn one Sdf.AssetPath into (resolved_path, state).

    resolvedPath is the composed stage's own answer, which is why it is used
    here instead of the layer arithmetic read_composition_arcs performs: a
    shader pulled in through a reference anchors against ITS layer, and
    anchoring against the root would yield a confidently wrong path.

    An empty resolvedPath is not automatically a missing file. The resolver
    never expands <UDIM>, so a templated path always comes back empty and
    calling that "missing" would condemn every UDIM texture in a production
    look. Resolver URIs are likewise not this function's to answer.
    """
    authored = asset_path.path
    resolved = asset_path.resolvedPath
    if resolved:
        return resolved.replace("\\", "/"), "ok"
    if _UDIM_TOKEN in authored:
        return None, "udim"
    if _URI_SCHEME_RE.match(authored):
        return None, "uri"
    if "`" in authored or "${" in authored:
        return None, "expression"
    return None, "missing"


def _asset_values(attr):
    """Yield (frame, Sdf.AssetPath) for every value the attribute holds.

    Both the default and every time sample are read, because an attribute can
    carry both and each is a real authored reference. Time samples shadow the
    default at every numeric time code, so nothing evaluates it on a frame —
    but it is a path in the file, and skipping it hides a broken one. Reading
    the samples matters for the opposite reason: a cache sequence authors one
    path per frame, so the default alone reports one file for a sequence of
    hundreds.

    Get() returns None when only samples are authored, so asking for it
    unconditionally adds no phantom record to a pure sequence.
    """
    def _each(frame, value):
        # An authored blank asset — USD writes it as @@ — is the absence of a
        # reference, not a broken one. Classifying it like a real path makes it
        # "missing", inventing breakage and inflating asset_count.
        if value is None:
            return
        if isinstance(value, Sdf.AssetPath):
            if value.path:
                yield frame, value
            return
        try:
            for item in value:
                if item and item.path:
                    yield frame, item
        except TypeError:
            return

    yield from _each(None, attr.Get())
    for frame in attr.GetTimeSamples():
        yield from _each(frame, attr.Get(frame))


def read_asset_paths(
    path: str,
    prim_path: str = "/",
    kind: str | None = None,
    limit: int = 500,
    load_payloads: bool = False,
) -> dict:
    """
    Find every asset-valued attribute on a composed stage and report where
    each one lands on disk.

    This answers "which textures does this scene use, and are they there?" —
    a question that otherwise needs one usd_read_prim_attributes plus one
    usd_read_attribute_value per shader.

    Args:
        path          — absolute path to a USD file
        prim_path     — subtree to walk; must be an absolute prim path
        kind          — keep only records of this kind (see below)
        limit         — cap on returned records; asset_count reports the true total
        load_payloads — load payloads. Required when materials live inside one.

    Returns a dict with keys:
        path        — input file path
        prim_path   — the subtree that was walked
        asset_count — total records found, before `limit` was applied
        truncated   — whether `limit` cut the list short
        assets      — list of asset dicts (see below)

    Each asset dict:
        prim_path     — USD scene path of the prim holding the attribute
        attribute     — attribute name, e.g. "inputs:file"
        frame         — time sample the value came from, null for the default
        asset_path    — the authored string, exactly as written
        resolved_path — absolute path, or null when it cannot be resolved
        resolved      — "ok" | "missing" | "udim" | "uri" | "expression"
        kind          — "texture" | "light" | "volume" | "other"

    Raises:
        FileNotFoundError  — file does not exist
        UsdOpenError       — stage could not be opened
        ValueError         — prim_path is not absolute, or kind is unknown
    """
    _assert_exists(path)
    _validate_limit(limit)

    if not Sdf.Path(prim_path).IsAbsolutePath():
        raise ValueError(
            f"prim_path must be an absolute USD path (e.g. '/mtl'), got: {prim_path!r}"
        )
    if kind is not None and kind not in ("texture", "light", "volume", "other"):
        raise ValueError(
            f"kind must be one of texture, light, volume, other — got: {kind!r}"
        )

    load = Usd.Stage.LoadAll if load_payloads else Usd.Stage.LoadNone
    stage = _open_stage(path, load=load)

    start = stage.GetPrimAtPath(prim_path)
    if not start:
        raise ValueError(f"prim not found: {prim_path}")

    assets = []
    for prim in Usd.PrimRange(start):
        for attr in prim.GetAttributes():
            if attr.GetTypeName() not in _ASSET_TYPES:
                continue
            attr_name = attr.GetName()
            attr_kind = _asset_kind(prim, attr_name)
            if kind is not None and attr_kind != kind:
                continue
            for frame, value in _asset_values(attr):
                resolved_path, state = _classify_asset(value)
                assets.append({
                    "prim_path":     str(prim.GetPath()),
                    "attribute":     attr_name,
                    "frame":         frame,
                    "asset_path":    value.path,
                    "resolved_path": resolved_path,
                    "resolved":      state,
                    "kind":          attr_kind,
                })

    return {
        "path":        path,
        "prim_path":   prim_path,
        "asset_count": len(assets),
        "truncated":   len(assets) > limit,
        "assets":      assets[:limit],
    }


def read_layer_dependencies(path: str, limit: int = 500) -> dict:
    """
    Walk a layer's composition dependencies transitively and report every layer
    the scene needs.

    This is the "what files do I have to ship" question. read_composition_arcs
    answers a different one — what a single layer declares, grouped by arc type
    and keeping the authored string that replace_anchors matches on. The two
    agree on the direct dependencies; only this one sees a layer reachable
    solely through another layer.

    Args:
        path  — absolute path to a USD file
        limit — cap on returned records; dependency_count reports the true total

    Returns a dict with keys:
        path             — input file path
        dependency_count — total layers found, before `limit` was applied
        missing_count    — how many of those could not be opened
        truncated        — whether `limit` cut the list short
        dependencies     — list of dependency dicts (see below)

    Each dependency dict:
        asset_path    — the authored string, exactly as written
        resolved_path — absolute path to the layer, or null when the authored
                        string is not a filesystem path
        resolved      — "ok"         layer opened
                        "missing"    nothing at that location
                        "uri"        a resolver scheme; not recursed into
                        "expression" an unexpanded expression variable
        depth         — 1 for a direct dependency of `path`, 2 for its
                        dependencies, and so on
        introduced_by — absolute path of the layer that declares it, which is
                        where a broken path has to be fixed

    Raises:
        FileNotFoundError — file does not exist
        UsdOpenError      — file could not be opened as a USD layer
    """
    _assert_exists(path)
    _validate_limit(limit)
    root = _open_layer(path)

    def _norm(p: str) -> str:
        # A layer USD opened reports realPath; one it could not reports the
        # computed path. On Windows those disagree on the separator, so a
        # caller comparing or joining them would silently mismatch.
        return p.replace("\\", "/")

    root_key = _norm(root.realPath or root.identifier)
    visited = {root_key}
    dependencies = []
    queue = deque([(root, 1)])

    while queue:
        layer, depth = queue.popleft()
        introduced_by = _norm(layer.realPath or layer.identifier)
        for dep in layer.GetCompositionAssetDependencies():
            # Classify before doing any path arithmetic. ComputeAbsolutePath
            # rewrites "omniverse://server/a.usd" as "omniverse:/server/a.usd",
            # losing a slash — reporting that as a resolved path would invent a
            # location the resolver never named, and opening it fails, so the
            # layer would also be blamed as missing.
            if _URI_SCHEME_RE.match(dep) or "`" in dep or "${" in dep:
                state = "uri" if _URI_SCHEME_RE.match(dep) else "expression"
                if dep in visited:
                    continue
                visited.add(dep)
                dependencies.append({
                    "asset_path":    dep,
                    "resolved_path": None,
                    "resolved":      state,
                    "depth":         depth,
                    "introduced_by": introduced_by,
                })
                continue

            absolute = _norm(layer.ComputeAbsolutePath(dep))
            sub = Sdf.Layer.FindOrOpen(absolute)
            key = _norm(sub.realPath) if (sub is not None and sub.realPath) else absolute
            if key in visited:
                continue
            visited.add(key)
            dependencies.append({
                "asset_path":    dep,
                "resolved_path": key,
                "resolved":      "ok" if sub is not None else "missing",
                "depth":         depth,
                "introduced_by": introduced_by,
            })
            if sub is not None:
                queue.append((sub, depth + 1))

    return {
        "path":             path,
        "dependency_count": len(dependencies),
        "missing_count":    sum(1 for d in dependencies if d["resolved"] == "missing"),
        "truncated":        len(dependencies) > limit,
        "dependencies":     dependencies[:limit],
    }


def read_prim_attributes(
    path: str,
    prim_path: str,
    detail: str = "types",
    filter_prefix: str | None = None,
    limit: int = 200,
    frame: float | None = None,
    load_payloads: bool = False,
) -> dict:
    """List attributes on a prim with progressive disclosure via detail level."""
    if detail not in ("names", "types", "samples"):
        raise ValueError(f"detail must be 'names', 'types', or 'samples', got: {detail!r}")
    _validate_limit(limit)
    if not prim_path:
        raise UsdOpenError("prim_path must not be empty")
    _assert_exists(path)
    load = Usd.Stage.LoadAll if load_payloads else Usd.Stage.LoadNone
    stage = _open_stage(path, load=load)

    prim = stage.GetPrimAtPath(Sdf.Path(prim_path))
    if not prim.IsValid():
        raise UsdOpenError(f"prim not found: {prim_path}")

    time = Usd.TimeCode(frame) if frame is not None else Usd.TimeCode.Default()
    attrs = prim.GetAttributes()

    if filter_prefix is not None:
        attrs = [a for a in attrs if a.GetName().startswith(filter_prefix)]

    total = len(attrs)
    attrs = attrs[:limit]
    truncated = total > limit

    result_attrs = []
    for attr in attrs:
        entry = {"name": attr.GetName()}
        if detail in ("types", "samples"):
            type_name = attr.GetTypeName()
            is_array = type_name.isArray
            array_size = None
            if is_array:
                v = attr.Get(time)
                if v is None:
                    samples = attr.GetTimeSamples()
                    if samples:
                        v = attr.Get(Usd.TimeCode(samples[0]))
                array_size = len(v) if v is not None else None
            entry["type_name"] = str(type_name)
            entry["variability"] = (
                "uniform" if attr.GetVariability() == Sdf.VariabilityUniform else "varying"
            )
            entry["is_array"] = is_array
            entry["array_size"] = array_size
        if detail == "samples":
            ts_count = attr.GetNumTimeSamples()
            entry["has_time_samples"] = ts_count > 0
            entry["time_sample_count"] = ts_count
        result_attrs.append(entry)

    return {
        "path": path,
        "prim_path": prim_path,
        "detail": detail,
        "attribute_count": len(result_attrs),
        "total_attribute_count": total,
        "truncated": truncated,
        "attributes": result_attrs,
    }


def read_attribute_value(
    path: str,
    prim_path: str,
    attribute_name: str,
    frame: float | None = None,
    max_elements: int = 100,
    load_payloads: bool = False,
) -> dict:
    """Read the value of a single attribute from a USD prim."""
    if not prim_path:
        raise UsdOpenError("prim_path must not be empty")
    if not attribute_name:
        raise UsdOpenError("attribute_name must not be empty")
    _validate_limit(max_elements, "max_elements")
    _assert_exists(path)
    load = Usd.Stage.LoadAll if load_payloads else Usd.Stage.LoadNone
    stage = _open_stage(path, load=load)

    prim = stage.GetPrimAtPath(Sdf.Path(prim_path))
    if not prim.IsValid():
        raise UsdOpenError(f"prim not found: {prim_path}")

    attr = prim.GetAttribute(attribute_name)
    if not attr.IsValid():
        raise UsdOpenError(f"attribute not found: {attribute_name} on {prim_path}")

    time = Usd.TimeCode(frame) if frame is not None else Usd.TimeCode.Default()
    raw = attr.Get(time)
    frame_used = frame
    if raw is None and frame is None:
        samples = attr.GetTimeSamples()
        if samples:
            frame_used = float(samples[0])
            raw = attr.Get(Usd.TimeCode(samples[0]))
    type_name = str(attr.GetTypeName())

    serialized = _value_to_json(raw, max_elements=max_elements)

    array_total = None
    array_truncated = None
    value = serialized

    if isinstance(serialized, dict) and "_array_total" in serialized:
        array_total = serialized["_array_total"]
        array_truncated = serialized["_truncated"]
        value = serialized["values"]

    return {
        "path": path,
        "prim_path": prim_path,
        "attribute_name": attribute_name,
        "type_name": type_name,
        "frame": frame,
        "frame_used": frame_used,
        "array_total": array_total,
        "array_truncated": array_truncated,
        "value": value,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _gf_to_json(value):
    """Convert a Gf type (e.g. GfVec2f for clippingRange) to a JSON list."""
    if value is None:
        return None
    try:
        # Gf.Vec* types support len() and __getitem__ but not __iter__
        return [value[i] for i in range(len(value))]
    except TypeError:
        return value


def _value_to_json(value, max_elements=None):
    """Serialize a USD/Gf/Vt value to a JSON-friendly Python object."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    # Blocked attribute — stronger than None, not a missing value
    if isinstance(value, Sdf.ValueBlock):
        return None
    # Gf.Quat* — check before Vec* since Quat has no len()
    if isinstance(value, _GF_QUAT_TYPES):
        im = value.imaginary
        return [value.real, im[0], im[1], im[2]]
    # Gf.Matrix* — has dimension attribute
    if hasattr(value, "dimension") and hasattr(value, "__getitem__"):
        try:
            nrows, ncols = value.dimension
            return [[value[i][j] for j in range(ncols)] for i in range(nrows)]
        except (TypeError, ValueError):
            pass
    # Gf.Vec* — supports len() and __getitem__
    if hasattr(value, "__getitem__") and hasattr(value, "__len__") and type(value).__module__ == "pxr.Gf":
        try:
            return [value[i] for i in range(len(value))]
        except Exception:
            pass
    # Gf.Range*
    if hasattr(value, "min") and hasattr(value, "max") and type(value).__module__ == "pxr.Gf":
        return [_value_to_json(value.min), _value_to_json(value.max)]
    # Sdf.AssetPath
    if isinstance(value, Sdf.AssetPath):
        return value.path
    # Sdf.TimeCode
    if isinstance(value, Sdf.TimeCode):
        return float(value)
    # Vt.Array (any VtArray type — no common base, detect by module)
    if type(value).__module__ == "pxr.Vt" and hasattr(value, "__len__"):
        total = len(value)
        truncated = (max_elements is not None) and (total > max_elements)
        count = min(total, max_elements) if max_elements is not None else total
        return {
            "_array_total": total,
            "_truncated": truncated,
            "values": [_value_to_json(value[i]) for i in range(count)],
        }
    # tuple / list
    if isinstance(value, (tuple, list)):
        return [_value_to_json(x) for x in value]
    return str(value)


def _assert_exists(path: str) -> None:
    if not Path(path).exists():
        raise FileNotFoundError(f"file not found: {path}")


def _open_layer(path: str) -> Sdf.Layer:
    """Open a layer, reporting any failure as UsdOpenError.

    A malformed file makes USD raise Tf.ErrorException rather than return None,
    so the None check alone does not honour the UsdOpenError contract these
    functions document.
    """
    try:
        layer = Sdf.Layer.FindOrOpen(path)
    except Tf.ErrorException as e:
        raise UsdOpenError(f"could not open USD layer: {path}") from e
    if layer is None:
        raise UsdOpenError(f"could not open USD layer: {path}")
    return layer


def _open_stage(path: str, **kwargs) -> Usd.Stage:
    """Open a stage, reporting any failure as UsdOpenError. See _open_layer."""
    try:
        stage = Usd.Stage.Open(path, **kwargs)
    except Tf.ErrorException as e:
        raise UsdOpenError(f"could not open USD stage: {path}") from e
    if stage is None:
        raise UsdOpenError(f"could not open USD stage: {path}")
    return stage


def _validate_sublayers_arg(sublayers) -> list[str]:
    if not isinstance(sublayers, list) or not sublayers:
        raise UsdOpenError("sublayers must be a non-empty list of strings")
    for s in sublayers:
        if not isinstance(s, str) or not s:
            raise UsdOpenError(
                f"sublayers items must be non-empty strings, got {s!r}"
            )
    return list(sublayers)


def _open_layer_for_write(path: str, output_path: str | None):
    """
    Common open + target-layer setup shared by sublayer write tools.

    Returns (source_layer, target_layer). In in-place mode source == target;
    in export mode target is an anonymous copy to avoid polluting the layer
    cache for `path` with edits that never reach disk for that path.
    """
    _assert_exists(path)
    source = _open_layer(path)

    if output_path is not None and Path(output_path).exists():
        raise UsdOpenError(
            f"output_path already exists, refusing to overwrite: {output_path}"
        )

    if output_path is None:
        if not source.permissionToEdit:
            raise UsdOpenError(f"layer is not editable in-place: {path}")
        return source, source

    target = Sdf.Layer.CreateAnonymous()
    target.TransferContent(source)
    return source, target


def _save_or_export(target, path: str, output_path: str | None) -> tuple[str, str]:
    if output_path is None:
        target.Save()
        return "in_place", path
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    if not target.Export(output_path):
        raise UsdOpenError(f"failed to export layer to: {output_path}")
    return "export", output_path


def add_sublayers(
    path: str,
    sublayers: list[str],
    position: str,
    output_path: str | None = None,
) -> dict:
    """
    Add one or more sublayer asset paths to a USD layer's subLayerPaths.

    The order of the input list is preserved. With position="prepend", the
    first item ends up at index 0 (strongest), so `final = sublayers + existing`.
    With position="append", `final = existing + sublayers`.

    Entries whose string is already present in subLayerPaths are skipped
    (no-op), and reported in `skipped`. Internal duplicates within `sublayers`
    are treated the same way — only the first occurrence is added.

    Anonymous layer identifiers (starting with "anon:") are rejected — USD
    does not allow writing them into a saved layer.

    If `output_path` is None, the file is saved in-place. Otherwise the layer
    is exported to a new file (must not exist), with format inferred from the
    extension; the source file is not touched.

    Raises:
        FileNotFoundError — source file does not exist
        UsdOpenError      — invalid arguments, layer not editable, or write fails
    """
    to_add = _validate_sublayers_arg(sublayers)
    if position not in ("prepend", "append"):
        raise UsdOpenError(
            f"position must be 'prepend' or 'append', got {position!r}"
        )
    for s in to_add:
        if s.startswith("anon:"):
            raise UsdOpenError(
                f"refusing to add anonymous layer identifier: {s!r}"
            )

    _, target = _open_layer_for_write(path, output_path)

    existing = list(target.subLayerPaths)
    added: list[str] = []
    skipped: list[str] = []
    seen = set(existing)
    for s in to_add:
        if s in seen:
            skipped.append(s)
        else:
            added.append(s)
            seen.add(s)

    if added:
        with Sdf.ChangeBlock():
            if position == "prepend":
                for i, s in enumerate(added):
                    target.subLayerPaths.insert(i, s)
            else:
                for s in added:
                    target.subLayerPaths.append(s)

    mode, out = _save_or_export(target, path, output_path)

    return {
        "path":            path,
        "output_path":     out,
        "mode":            mode,
        "position":        position,
        "added":           added,
        "skipped":         skipped,
        "final_sublayers": list(target.subLayerPaths),
    }


def insert_sublayers(
    path: str,
    sublayers: list[str],
    index: int,
    output_path: str | None = None,
) -> dict:
    """
    Insert one or more sublayer asset paths at an explicit position in a USD
    layer's subLayerPaths.

    `index` is 0-based against the existing subLayerPaths length. `index=0`
    inserts at the top (strongest, equivalent to add_sublayers prepend);
    `index=len(existing)` inserts at the bottom (weakest, equivalent to
    append). Values outside `[0, len(existing)]` — including any negative
    value — raise UsdOpenError.

    When multiple sublayers are inserted at index i, input order is preserved:
    new entries occupy indices i, i+1, i+2, ... and the entry originally at
    index i shifts down accordingly.

    Entries whose string is already present in subLayerPaths are skipped
    (no-op) and reported in `skipped`. Internal duplicates within `sublayers`
    are deduplicated the same way. Anonymous identifiers (starting with
    "anon:") are rejected.

    If `output_path` is None, the file is saved in-place; otherwise the layer
    is exported to a new file (must not exist), source untouched.

    Raises:
        FileNotFoundError — source file does not exist
        UsdOpenError      — invalid arguments, layer not editable, or write fails
    """
    to_add = _validate_sublayers_arg(sublayers)
    if not isinstance(index, int) or isinstance(index, bool):
        raise UsdOpenError(
            f"index must be a non-negative integer, got {index!r}"
        )
    for s in to_add:
        if s.startswith("anon:"):
            raise UsdOpenError(
                f"refusing to add anonymous layer identifier: {s!r}"
            )

    _, target = _open_layer_for_write(path, output_path)

    existing_len = len(target.subLayerPaths)
    if index < 0 or index > existing_len:
        raise UsdOpenError(
            f"index out of range: {index} (must be 0..{existing_len} inclusive)"
        )

    seen = set(target.subLayerPaths)
    added: list[str] = []
    skipped: list[str] = []
    for s in to_add:
        if s in seen:
            skipped.append(s)
        else:
            added.append(s)
            seen.add(s)

    if added:
        with Sdf.ChangeBlock():
            for j, s in enumerate(added):
                target.subLayerPaths.insert(index + j, s)

    mode, out = _save_or_export(target, path, output_path)

    return {
        "path":            path,
        "output_path":     out,
        "mode":            mode,
        "index":           index,
        "added":           added,
        "skipped":         skipped,
        "final_sublayers": list(target.subLayerPaths),
    }


def remove_sublayers(
    path: str,
    sublayers: list[str],
    output_path: str | None = None,
) -> dict:
    """
    Remove one or more sublayer asset paths from a USD layer's subLayerPaths.

    Matches the exact stored strings (same strings returned by
    read_composition_arcs). Entries not found in subLayerPaths are silently
    skipped and reported in `not_found`.

    If `output_path` is None, the file is saved in-place. Otherwise the layer
    is exported to a new file (must not exist); the source file is not touched.

    Raises:
        FileNotFoundError — source file does not exist
        UsdOpenError      — invalid arguments, layer not editable, or write fails
    """
    to_remove = _validate_sublayers_arg(sublayers)

    _, target = _open_layer_for_write(path, output_path)

    existing = list(target.subLayerPaths)
    removed: list[str] = []
    not_found: list[str] = []
    to_remove_set: set[str] = set()
    for s in to_remove:
        if s in to_remove_set:
            continue
        to_remove_set.add(s)
        if s in existing:
            removed.append(s)
        else:
            not_found.append(s)

    if removed:
        with Sdf.ChangeBlock():
            for s in removed:
                # subLayerPaths may legitimately contain duplicates; clear all
                while s in target.subLayerPaths:
                    target.subLayerPaths.remove(s)

    mode, out = _save_or_export(target, path, output_path)

    return {
        "path":            path,
        "output_path":     out,
        "mode":            mode,
        "removed":         removed,
        "not_found":       not_found,
        "final_sublayers": list(target.subLayerPaths),
    }
