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

Write functions:
  write_layer_metadata           — partial update of layer metadata fields
  create_expressions_layer       — create a new USD layer containing only
                                    expressionVariables
  add_sublayers                  — prepend or append sublayer asset paths
  insert_sublayers               — insert sublayer asset paths at an explicit index
  remove_sublayers               — remove sublayer asset paths by exact string
"""

from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, Gf, Vt

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
    layer = Sdf.Layer.FindOrOpen(path)
    if layer is None:
        raise UsdOpenError(f"could not open USD layer: {path}")

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
    source = Sdf.Layer.FindOrOpen(path)
    if source is None:
        raise UsdOpenError(f"could not open USD layer: {path}")

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
    layer = Sdf.Layer.FindOrOpen(path)
    if layer is None:
        raise UsdOpenError(f"could not open USD layer: {path}")

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
    stage = Usd.Stage.Open(path, load=Usd.Stage.LoadNone)
    if stage is None:
        raise UsdOpenError(f"could not open USD stage: {path}")

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


def read_composition_arcs(path: str) -> dict:
    """
    List the direct composition arcs declared in a single USD layer:
    sublayers, references, and payloads. No composition is performed —
    only arcs explicitly written in this file are returned.

    Returns a dict with keys:
        path        — input file path
        sublayers   — ordered list of sublayer asset paths (weakest last)
        references  — list of {prim_path, asset_path, target_prim_path}
        payloads    — list of {prim_path, asset_path, target_prim_path}

    Raises:
        FileNotFoundError  — file does not exist
        UsdOpenError       — file could not be opened as a USD layer
    """
    _assert_exists(path)
    layer = Sdf.Layer.FindOrOpen(path)
    if layer is None:
        raise UsdOpenError(f"could not open USD layer: {path}")

    sublayers = list(layer.subLayerPaths)

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
            })
        for pay in spec.payloadList.GetAppliedItems():
            payloads.append({
                "prim_path":        prim_str,
                "asset_path":       pay.assetPath,
                "target_prim_path": str(pay.primPath),
            })

    layer.Traverse(layer.pseudoRoot.path, _collect)

    return {
        "path":       path,
        "sublayers":  sublayers,
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
    layer = Sdf.Layer.FindOrOpen(path)
    if layer is None:
        raise UsdOpenError(f"could not open USD layer: {path}")

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
    stage = Usd.Stage.Open(path, load=Usd.Stage.LoadNone)
    if stage is None:
        raise UsdOpenError(f"could not open USD stage: {path}")

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
    if not prim_path:
        raise UsdOpenError("prim_path must not be empty")
    _assert_exists(path)
    load = Usd.Stage.LoadAll if load_payloads else Usd.Stage.LoadNone
    stage = Usd.Stage.Open(path, load=load)
    if stage is None:
        raise UsdOpenError(f"could not open USD stage: {path}")

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
    _assert_exists(path)
    load = Usd.Stage.LoadAll if load_payloads else Usd.Stage.LoadNone
    stage = Usd.Stage.Open(path, load=load)
    if stage is None:
        raise UsdOpenError(f"could not open USD stage: {path}")

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
    source = Sdf.Layer.FindOrOpen(path)
    if source is None:
        raise UsdOpenError(f"could not open USD layer: {path}")

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
