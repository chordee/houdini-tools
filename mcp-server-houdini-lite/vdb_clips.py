"""
vdb_clips.py — Stitch a per-frame .vdb sequence into a USD Volume.

Creates a single USD file containing one UsdVol.Volume with one
UsdVol.OpenVDBAsset child per grid; the filePath / fieldName / fieldIndex
attributes are time-sampled across the supplied frame range. No Houdini
required — works with only usd-core.
"""

from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdVol

from usd_clips import resolve_filepath
from vdb_tools import VdbParseError, read_vdb_inspect


class VdbStitchError(Exception):
    """Raised when the stitch operation cannot proceed."""


def stitch_vdb_volume_usd(
    filepath_template: str,
    output_path: str,
    frame_range: tuple[int, int],
    volume_name: str,
    parent_primpath: str,
    probe_frame: int | None = None,
    grids: list[str] | None = None,
    strict: bool = False,
) -> dict:
    start, end = int(frame_range[0]), int(frame_range[1])
    if start > end:
        raise VdbStitchError(
            f"invalid frame_range: start ({start}) > end ({end})"
        )
    if not parent_primpath.startswith("/"):
        raise VdbStitchError(
            f"parent_primpath must be an absolute USD path: {parent_primpath!r}"
        )
    if not volume_name or not Sdf.Path.IsValidIdentifier(volume_name):
        raise VdbStitchError(
            f"volume_name must be a valid USD prim identifier "
            f"(letters, digits, underscores; cannot start with a digit), "
            f"got {volume_name!r}"
        )

    file_frames = list(range(start, end + 1))
    file_paths  = [resolve_filepath(filepath_template, f) for f in file_frames]
    missing = [
        {"frame": f, "path": p}
        for f, p in zip(file_frames, file_paths)
        if not Path(p).exists()
    ]
    if missing and strict:
        raise VdbStitchError(
            f"strict mode: {len(missing)} source file(s) missing "
            f"(first: {missing[0]['path']})"
        )

    if probe_frame is None:
        probe_frame = start
    probe_frame = int(probe_frame)
    if not (start <= probe_frame <= end):
        raise VdbStitchError(
            f"probe_frame {probe_frame} is outside frame_range "
            f"[{start}, {end}]"
        )
    probe_path = resolve_filepath(filepath_template, probe_frame)
    if not Path(probe_path).exists():
        raise VdbStitchError(
            f"probe file does not exist: {probe_path}"
        )

    try:
        probe_info = read_vdb_inspect(probe_path)
    except (FileNotFoundError, VdbParseError) as e:
        raise VdbStitchError(f"could not inspect probe file: {e}") from e

    probe_grid_names = [g["name"] for g in probe_info["grids"]]
    if grids:
        unknown = [g for g in grids if g not in probe_grid_names]
        if unknown:
            raise VdbStitchError(
                f"requested grids not present in probe ({probe_path}): "
                f"{unknown}; probe contains {probe_grid_names}"
            )
        target_grids = list(grids)
    else:
        target_grids = probe_grid_names

    if not target_grids:
        raise VdbStitchError(
            f"no grids to write (probe file {probe_path} has no grids)"
        )

    invalid = [g for g in target_grids if not Sdf.Path.IsValidIdentifier(g)]
    if invalid:
        raise VdbStitchError(
            f"grid names are not valid USD prim identifiers: {invalid}. "
            f"USD prim names must start with a letter or underscore and "
            f"contain only letters, digits, and underscores."
        )

    out_path = Path(output_path)
    if out_path.exists():
        raise VdbStitchError(
            f"output_path already exists, refusing to overwrite: {output_path}"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    stage = Usd.Stage.CreateNew(output_path)

    UsdGeom.Xform.Define(stage, parent_primpath)
    vol_path = f"{parent_primpath.rstrip('/')}/{volume_name}"
    UsdGeom.Xform.Define(stage, vol_path)
    vol = UsdVol.Volume.Define(stage, vol_path)

    grid_summaries = []
    for grid_name in target_grids:
        grid_path = f"{vol_path}/{grid_name}"
        vdb = UsdVol.OpenVDBAsset.Define(stage, grid_path)
        vol.CreateFieldRelationship(grid_name, grid_path)

        filepath_attr   = vdb.CreateFilePathAttr()
        fieldname_attr  = vdb.CreateFieldNameAttr()
        fieldindex_attr = vdb.CreateFieldIndexAttr()

        for f, p in zip(file_frames, file_paths):
            filepath_attr.Set(p, f)
            fieldname_attr.Set(grid_name, f)
            fieldindex_attr.Set(0, f)

        grid_summaries.append({
            "grid_name": grid_name,
            "prim_path": grid_path,
        })

    stage.SetStartTimeCode(start)
    stage.SetEndTimeCode(end)
    stage.GetRootLayer().Save()

    return {
        "status":          "ok",
        "output_path":     str(out_path),
        "volume_primpath": vol_path,
        "grids":           grid_summaries,
        "frame_range":     [start, end],
        "frame_count":     len(file_frames),
        "probe_frame":     probe_frame,
        "probe_path":      probe_path,
        "missing_files":   missing,
    }
