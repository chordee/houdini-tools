"""
bgeo_clips.py — Stitch per-frame .bgeo.sc caches into a USD Value Clips stage.

Each clip asset path in the output USD points directly to a .bgeo.sc file.
A Houdini environment (or any DCC with a bgeo USD file format plugin) is
required to load the geometry at render / viewport time.

USD structure is derived from bgeo detail attributes embedded in the files:
  usdconfigpathprefix   → primpath on the output stage
  usdconfigsampleframe  → scene frame number for each file
"""

import math
import os
import re
import struct
from pathlib import Path

from pxr import Usd, UsdGeom, Sdf

from bgeo_reader import BJSON_MAGIC, read_bgeo_clip_metadata


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BgeoClipsError(Exception):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _decompress_bgeo(path: str) -> bytes:
    """Decompress a .bgeo.sc and return the raw BJSON bytes (magic stripped)."""
    from blosc_io import read_first_chunk, BloscDecompressError
    try:
        raw = read_first_chunk(path)
    except Exception as e:
        raise BgeoClipsError(f"failed to decompress {path}: {e}") from e
    if raw[:4] == BJSON_MAGIC:
        return raw[4:]
    raise BgeoClipsError(f"not BJSON data after decompression: {path}")


def _read_meta(path: str) -> dict:
    """Decompress and parse clip metadata from a single .bgeo.sc file."""
    data = _decompress_bgeo(path)
    return read_bgeo_clip_metadata(data)


def _resolve_frame(template: str, frame: int) -> str:
    """Resolve a per-frame path template (supports {frame:Nd} and $FN)."""
    houdini_pat = re.compile(r'\$F(\d*)')
    def _sub(m):
        pad = int(m.group(1)) if m.group(1) else 1
        return f"{frame:0{pad}d}"
    resolved = houdini_pat.sub(_sub, template)
    try:
        resolved = resolved.format(frame=frame)
    except KeyError:
        pass
    return resolved


def _scan_directory(filepath_template: str) -> dict[int, str]:
    """
    Scan the directory implied by filepath_template for all .bgeo.sc files,
    read their usdconfigsampleframe, and return {frame: path}.
    """
    directory = os.path.dirname(os.path.abspath(filepath_template))
    if not os.path.isdir(directory):
        raise BgeoClipsError(f"directory not found: {directory}")

    frame_map: dict[int, str] = {}
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".bgeo.sc"):
            continue
        fpath = os.path.join(directory, fname)
        try:
            meta = _read_meta(fpath)
            if meta["sample_frame"] is not None:
                frame_map[meta["sample_frame"]] = fpath
        except Exception as e:
            print(f"[WARNING] skipped unreadable file: {fname}: {e}")
    return frame_map


# ---------------------------------------------------------------------------
# USD type helpers
# ---------------------------------------------------------------------------

# Maps (storage, size) → Sdf.ValueTypeNames token
# Only covers common Houdini point/prim attribute types.
_BGEO_TO_SDF: dict[tuple, object] = {
    ("fpreal32", 1): Sdf.ValueTypeNames.Float,
    ("fpreal32", 2): Sdf.ValueTypeNames.Float2,
    ("fpreal32", 3): Sdf.ValueTypeNames.Float3,
    ("fpreal32", 4): Sdf.ValueTypeNames.Float4,
    ("fpreal64", 1): Sdf.ValueTypeNames.Double,
    ("fpreal64", 3): Sdf.ValueTypeNames.Double3,
    ("int32",    1): Sdf.ValueTypeNames.Int,
    ("int32",    3): Sdf.ValueTypeNames.Int3,
    ("int64",    1): Sdf.ValueTypeNames.Int64,
}

# Well-known Houdini attribute → USD schema attribute name
_HOUDINI_TO_USD_ATTR: dict[str, str] = {
    "P":  "points",
    "N":  "normals",
    "Cd": "primvars:displayColor",
    "uv": "primvars:st",
}


def _sdf_type(storage: str, size: int) -> object:
    return _BGEO_TO_SDF.get((storage, size), Sdf.ValueTypeNames.Token)


def _usd_attr_name(houdini_name: str) -> str:
    return _HOUDINI_TO_USD_ATTR.get(houdini_name, houdini_name)


# ---------------------------------------------------------------------------
# USDA text writer (bypasses USD format-detection validation)
# ---------------------------------------------------------------------------

def _write_usda_clips(
    output_path: str,
    start_tc: int,
    end_tc: int,
    fps: float,
    default_prim: str,
    topology_rel: str | None,
    manifest_rel: str | None,
    clip_set: str,
    primpath: str,
    asset_paths: list[str],
    scene_frames: list[int],
    file_frames: list[int],
) -> None:
    """Write a USD Value Clips stage as plain USDA text.

    Using USD Python API to write clip metadata triggers format-detection
    on each assetPath.  Writing text directly avoids that validation and
    allows bgeo.sc paths to appear as-is.
    """
    # -- header --
    lines: list[str] = ["#usda 1.0", "("]
    lines.append(f"    startTimeCode = {start_tc}")
    lines.append(f"    endTimeCode = {end_tc}")
    lines.append(f"    timeCodesPerSecond = {fps:g}")
    lines.append(f"    framesPerSecond = {fps:g}")
    lines.append(f'    defaultPrim = "{default_prim}"')
    if topology_rel:
        lines.append("    subLayers = [")
        lines.append(f"        @{topology_rel}@")
        lines.append("    ]")
    lines.append(")")
    lines.append("")

    # -- clips dict --
    asset_list = ", ".join(f"@{p.replace(chr(92), '/')}@" for p in asset_paths)
    active_list = ", ".join(
        f"({float(s)}, {float(i)})"
        for i, s in enumerate(scene_frames)
    )
    times_list = ", ".join(
        f"({float(s)}, {float(f)})"
        for s, f in zip(scene_frames, file_frames)
    )

    lines.append(f'def Xform "{default_prim}" (')
    lines.append("    clips = {")
    lines.append(f'        dictionary {clip_set} = {{')
    lines.append(f"            asset[] assetPaths = [{asset_list}]")
    lines.append(f'            string primPath = "{primpath}"')
    lines.append(f"            double2[] active = [{active_list}]")
    lines.append(f"            double2[] times = [{times_list}]")
    if manifest_rel:
        lines.append(f"            asset manifestAssetPath = @{manifest_rel}@")
    lines.append("        }")
    lines.append("    }")
    lines.append(")")
    lines.append("{")
    lines.append("}")
    lines.append("")

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Topology / manifest generation helpers
# ---------------------------------------------------------------------------

def _write_attribs(prim, pvapi, attribs: list[tuple], interp) -> int:
    """Author attribute stubs with the given USD interpolation token.

    primvars (names mapped to primvars:*) are created via PrimvarsAPI so the
    interpolation metadata is properly encoded.  Built-in schema attributes
    (points, normals, etc.) that don't start with primvars: are created as
    plain attributes; interpolation metadata is only set when non-vertex
    (vertex is the implicit default for point-class data in USD).

    Returns the number of attributes authored.
    """
    count = 0
    for (name, size, storage) in attribs:
        usd_name = _usd_attr_name(name)
        sdf_type  = _sdf_type(storage, size)
        if usd_name.startswith("primvars:"):
            pvapi.CreatePrimvar(usd_name[len("primvars:"):], sdf_type, interp)
        else:
            attr = prim.CreateAttribute(usd_name, sdf_type)
            if interp != UsdGeom.Tokens.vertex:
                attr.SetMetadata("interpolation", str(interp))
        count += 1
    return count


# ---------------------------------------------------------------------------
# Topology / manifest generation
# ---------------------------------------------------------------------------

def _generate_topology_from_bgeo(probe_path: str, topology_path: str, primpath: str) -> None:
    """
    Build a topology.usd from bgeo prim paths and attribute metadata.

    This file is a sublayer of the main USD, so attribute metadata authored
    here (e.g. primvar interpolation) participates in composition.
    Does NOT read geometry data — only uses BJSON attribute metadata.

    Fallback: when the bgeo has no 'path' primitive attribute (single-mesh
    case), author a single Mesh at <primpath>/mesh_0 to match the bgeo USD
    file format plugin's runtime prim hierarchy.
    """
    meta = _read_meta(probe_path)
    prim_paths     = meta["prim_paths"] or [f"{primpath.rstrip('/')}/mesh_0"]
    point_attribs  = meta["point_attribs"]   # [(name, size, storage), ...]
    prim_attribs   = meta["prim_attribs"]
    vertex_attribs = meta["vertex_attribs"]
    detail_attribs = meta["detail_attribs"]

    topo_stage = Usd.Stage.CreateNew(topology_path)
    for pp in prim_paths:
        prim  = topo_stage.DefinePrim(pp, "Mesh")
        pvapi = UsdGeom.PrimvarsAPI(prim)

        _write_attribs(prim, pvapi, point_attribs,  UsdGeom.Tokens.vertex)
        _write_attribs(prim, pvapi, prim_attribs,   UsdGeom.Tokens.uniform)
        _write_attribs(prim, pvapi, vertex_attribs, UsdGeom.Tokens.faceVarying)
        _write_attribs(prim, pvapi, detail_attribs, UsdGeom.Tokens.constant)

    # set defaultPrim to the top-level prim
    top = Sdf.Path(prim_paths[0]).GetPrefixes()[0]
    top_prim = topo_stage.GetPrimAtPath(top)
    if top_prim.IsValid():
        topo_stage.SetDefaultPrim(top_prim)

    topo_stage.GetRootLayer().Save()
    print(f"[INFO] Topology written → {topology_path}")


def _generate_manifest_from_bgeo(probe_path: str, manifest_path: str, primpath: str) -> None:
    """
    Build a manifest.usd listing animated attributes with correct interpolation.

    Covers all four bgeo attribute classes:
      pointattributes  → vertex
      primitiveattributes → uniform
      vertexattributes → faceVarying
      detailattributes → constant

    Mesh topology (faceVertexCounts / faceVertexIndices) is added explicitly
    because it lives in the bgeo primitives section, not as named attributes.

    Falls back to a single Mesh at <primpath>/mesh_0 when the bgeo has no
    'path' primitive attribute.
    """
    meta = _read_meta(probe_path)
    prim_paths     = meta["prim_paths"] or [f"{primpath.rstrip('/')}/mesh_0"]
    point_attribs  = meta["point_attribs"]
    prim_attribs   = meta["prim_attribs"]
    vertex_attribs = meta["vertex_attribs"]
    detail_attribs = meta["detail_attribs"]

    mfst_stage = Usd.Stage.CreateNew(manifest_path)

    _MESH_TOPOLOGY_ATTRS = [
        ("faceVertexCounts",  Sdf.ValueTypeNames.IntArray),
        ("faceVertexIndices", Sdf.ValueTypeNames.IntArray),
    ]

    animated_count = 0
    for pp in prim_paths:
        prim  = mfst_stage.DefinePrim(pp, "Mesh")
        pvapi = UsdGeom.PrimvarsAPI(prim)

        for usd_name, sdf_type in _MESH_TOPOLOGY_ATTRS:
            prim.CreateAttribute(usd_name, sdf_type)
            animated_count += 1

        animated_count += _write_attribs(prim, pvapi, point_attribs,  UsdGeom.Tokens.vertex)
        animated_count += _write_attribs(prim, pvapi, prim_attribs,   UsdGeom.Tokens.uniform)
        animated_count += _write_attribs(prim, pvapi, vertex_attribs, UsdGeom.Tokens.faceVarying)
        animated_count += _write_attribs(prim, pvapi, detail_attribs, UsdGeom.Tokens.constant)

    mfst_stage.GetRootLayer().Save()
    print(f"[INFO] Manifest written → {manifest_path}  ({animated_count} animated attribute(s))")


# ---------------------------------------------------------------------------
# Main stitcher
# ---------------------------------------------------------------------------

def stitch_bgeo_clips(
    filepath_template: str,
    output_path: str,
    frame_range: tuple[int, int] | None = None,
    primpath: str | None = None,
    scene_range: tuple[int, int] | None = None,
    loop: bool = False,
    clip_set: str = "default",
    strict: bool = False,
    gen_topology: bool = True,
    gen_manifest: bool = True,
    probe_frame: int | None = None,
    probe_file: str | None = None,
    fps: float = 24.0,
) -> dict:
    """
    Stitch per-frame .bgeo.sc files into a USD Value Clips stage.

    The clip asset paths in the output USD point directly to the .bgeo.sc files.
    Requires Houdini (or a bgeo USD plugin) to load geometry at runtime.

    Auto-detects primpath (from usdconfigpathprefix) and frame_range
    (from usdconfigsampleframe) when those arguments are omitted.

    Raises:
        FileNotFoundError   — probe file does not exist
        BgeoClipsError      — invalid arguments or USD operation failed
    """
    if not math.isfinite(fps) or fps <= 0:
        raise BgeoClipsError(f"fps must be a finite positive number, got: {fps!r}")

    # --- 1. Build frame map {scene_frame: bgeo_path} ---
    if frame_range is None:
        frame_map = _scan_directory(filepath_template)
        if not frame_map:
            raise BgeoClipsError(
                f"no readable .bgeo.sc with usdconfigsampleframe found in: "
                f"{os.path.dirname(os.path.abspath(filepath_template))}"
            )
        sorted_frames = sorted(frame_map.keys())
        frame_range = (sorted_frames[0], sorted_frames[-1])
        filepaths = [frame_map[f] for f in sorted_frames]
        file_frames = sorted_frames
        print(f"[INFO] Auto-detected {len(file_frames)} frame(s): "
              f"{frame_range[0]}–{frame_range[1]}")
    else:
        if frame_range[0] > frame_range[1]:
            raise BgeoClipsError(
                f"invalid frame_range: start ({frame_range[0]}) > end ({frame_range[1]})"
            )
        all_frames = list(range(frame_range[0], frame_range[1] + 1))
        filepaths = [_resolve_frame(filepath_template, f) for f in all_frames]
        file_frames = all_frames

    if not file_frames:
        raise BgeoClipsError("no frames resolved from frame_range")

    # --- 2. Validate files ---
    missing = [p for p in filepaths if not os.path.exists(p)]
    if missing:
        msg = f"[WARNING] {len(missing)} file(s) missing"
        if strict:
            raise BgeoClipsError(f"strict mode: {msg}")
        print(msg)

    # --- 3. Determine probe path ---
    if probe_file is not None:
        if not os.path.exists(probe_file):
            raise FileNotFoundError(f"probe file not found: {probe_file}")
        probe_path = probe_file
        print(f"[INFO] Probe file (explicit): {probe_path}")
    elif probe_frame is not None:
        probe_path = _resolve_frame(filepath_template, probe_frame)
        if not os.path.exists(probe_path):
            raise FileNotFoundError(f"probe frame file not found: {probe_path}")
        print(f"[INFO] Probe frame: {probe_frame}  ({probe_path})")
    else:
        probe_path = filepaths[0]
        print(f"[INFO] Probe frame: {file_frames[0]} (default — first frame)")

    # --- 4. Auto-detect primpath ---
    probe_meta = _read_meta(probe_path)
    if primpath is None:
        primpath = probe_meta["primpath"]
        if not primpath:
            raise BgeoClipsError(
                "usdconfigpathprefix not found in probe bgeo.sc; "
                "specify primpath explicitly."
            )
        print(f"[INFO] Auto-detected primpath: {primpath}")

    if not Sdf.Path(primpath).IsAbsolutePath():
        raise BgeoClipsError(
            f"primpath must be an absolute USD path (e.g. '/Geometry'), got: {primpath!r}"
        )

    # --- 4b. Cross-check: every 'path' attribute value must be a descendant
    # of primpath. A mismatch means the bgeo was authored with inconsistent
    # USD configuration (e.g. path='/Geo/X' but usdconfigpathprefix='/Geometry')
    # and the resulting USD clip stage would attach time samples to the wrong
    # branch. Surface this loudly instead of producing a broken output.
    bgeo_prim_paths = probe_meta["prim_paths"]
    if bgeo_prim_paths:
        primpath_sdf = Sdf.Path(primpath)
        non_absolute = [pp for pp in bgeo_prim_paths if not Sdf.Path(pp).IsAbsolutePath()]
        if non_absolute:
            raise BgeoClipsError(
                f"bgeo 'path' attribute value(s) {non_absolute} are not absolute USD "
                f"paths (probe: {probe_path}). Only absolute paths are supported."
            )
        misplaced = [
            pp for pp in bgeo_prim_paths
            if not Sdf.Path(pp).HasPrefix(primpath_sdf)
        ]
        if misplaced:
            raise BgeoClipsError(
                f"bgeo 'path' attribute value(s) {misplaced} are not descendants of "
                f"usdconfigpathprefix '{primpath}' (probe: {probe_path}). "
                f"This stitcher requires every 'path' value to share the '{primpath}' "
                f"prefix so clip samples reach the Mesh prim(s). Fix the source bgeo, "
                f"or pass primpath explicitly."
            )

    # --- 5. Scene range and loop ---
    if scene_range is None:
        scene_range = frame_range

    if scene_range[0] > scene_range[1]:
        raise BgeoClipsError(
            f"invalid scene_range: start ({scene_range[0]}) > end ({scene_range[1]})"
        )

    _MAX_SCENE_FRAMES = 100_000
    if loop and len(file_frames) < (scene_range[1] - scene_range[0] + 1):
        scene_len = scene_range[1] - scene_range[0] + 1
        if scene_len > _MAX_SCENE_FRAMES:
            raise BgeoClipsError(
                f"scene_range spans {scene_len} frames, exceeds limit of {_MAX_SCENE_FRAMES}"
            )
        mul = scene_len // len(file_frames) + 1
        file_frames = (file_frames * mul)

    scene_frames = list(range(scene_range[0], scene_range[1] + 1))
    paired = list(zip(scene_frames, file_frames))
    scene_frames = [p[0] for p in paired]
    file_frames  = [p[1] for p in paired]
    # rebuild filepaths to match (possibly looped) file_frames
    # for auto-detected frame_map, rebuild; otherwise use template
    try:
        if frame_range is None:   # auto-detected → frame_map was built in step 1
            filepaths = [frame_map[f] for f in file_frames]
        else:
            filepaths = [_resolve_frame(filepath_template, f) for f in file_frames]
    except KeyError as e:
        raise BgeoClipsError(f"frame {e} not found in scan result during loop expansion")

    print(f"[INFO] Scene frames: {scene_frames[0]}–{scene_frames[-1]}  ({len(scene_frames)} frames)")

    # --- 6. Determine topology / manifest paths ---
    out_dir  = os.path.dirname(os.path.abspath(output_path))
    out_stem = os.path.splitext(os.path.basename(output_path))[0]
    out_ext  = os.path.splitext(output_path)[1] or ".usd"
    topology_path = os.path.join(out_dir, f"{out_stem}.topology{out_ext}")
    manifest_path = os.path.join(out_dir, f"{out_stem}.manifest{out_ext}")

    # --- 7. Generate topology ---
    if gen_topology:
        _generate_topology_from_bgeo(probe_path, topology_path, primpath)

    # --- 8. Generate manifest ---
    if gen_manifest:
        _generate_manifest_from_bgeo(probe_path, manifest_path, primpath)

    # bgeo.sc has no FPS metadata, so the caller must provide it (default 24).
    print(f"[INFO] FPS: {fps}")

    # --- 9. Write USDA text directly ---
    # usd-core validates clip assetPaths by trying to open them to detect
    # the file format.  Since bgeo.sc is not a recognized USD format, any
    # ClipsAPI / SdfLayer approach raises pxr.Tf.ErrorException.
    # Writing USDA text directly bypasses all validation.
    os.makedirs(out_dir, exist_ok=True)
    prefixes = Sdf.Path(primpath).GetPrefixes()
    if not prefixes:
        raise BgeoClipsError(f"primpath has no prefixes (root path not allowed): {primpath}")
    top_name = str(prefixes[0])
    top_prim_name = top_name.lstrip("/")

    _write_usda_clips(
        output_path=output_path,
        start_tc=scene_frames[0],
        end_tc=scene_frames[-1],
        fps=fps,
        default_prim=top_prim_name,
        topology_rel=(
            os.path.relpath(topology_path, out_dir).replace("\\", "/")
            if gen_topology else None
        ),
        manifest_rel=(
            os.path.relpath(manifest_path, out_dir).replace("\\", "/")
            if gen_manifest else None
        ),
        clip_set=clip_set,
        primpath=primpath,
        asset_paths=filepaths,
        scene_frames=scene_frames,
        file_frames=file_frames,
    )
    print(f"[INFO] Output written → {output_path}")

    return {
        "status": "ok",
        "output_path": output_path,
        "topology_path": topology_path if gen_topology else None,
        "manifest_path": manifest_path if gen_manifest else None,
        "clip_set": clip_set,
        "primpath": primpath,
        "fps": fps,
        "frame_range": list(frame_range),
        "scene_range": list(scene_range),
        "frame_count": len(scene_frames),
        "missing_files": missing,
    }
