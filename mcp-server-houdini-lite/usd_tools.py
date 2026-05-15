"""
usd_tools.py — USD file inspection utilities

Read-only functions for inspecting USD files without loading geometry:
  read_layer_metadata       — customLayerData from a single layer (no composition)
  read_layer_hierarchy      — prim hierarchy from a single layer (no composition)
  read_composed_hierarchy   — full composed hierarchy (refs/sublayers resolved,
                               payloads deferred)
  read_composition_arcs     — direct sublayers, references, and payloads declared
                               in a single layer (no composition)
  read_cameras              — all Camera prims with lens/projection attributes
  read_prim_attributes      — attribute names/types/time-sample info on a prim
  read_attribute_value      — value of a single named attribute on a prim
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

def read_layer_metadata(path: str) -> dict:
    """
    Read customLayerData from a single USD layer without composition.

    Returns a dict with keys:
        path            — input file path
        format          — file format id (e.g. "usda", "usdc", "usd")
        customLayerData — the layer's customLayerData dict (may be empty)

    Raises:
        FileNotFoundError  — file does not exist
        UsdOpenError       — file could not be opened as a USD layer
    """
    _assert_exists(path)
    layer = Sdf.Layer.FindOrOpen(path)
    if layer is None:
        raise UsdOpenError(f"could not open USD layer: {path}")

    return {
        "path": path,
        "format": layer.GetFileFormat().formatId,
        "customLayerData": dict(layer.customLayerData),
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
