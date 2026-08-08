"""End-to-end stitching against real Houdini caches, writing a real USD stage.

Every other bgeo test mocks something — _scan_directory, _read_meta, or
_write_usda_clips — so until now no test had ever produced an actual clip
stage from actual .bgeo.sc input. These do.

offset_sparse is the sequence that makes the auto-detection contract visible:
its usdconfigsampleframe values (1001, 1003, ... 1023) do not match the frame
numbers in its filenames (0001-0012). Code that re-resolved the template from a
sample frame would look for offset_sparse.1001.bgeo.sc and find nothing, so the
asset paths below only come out right if the scanned mapping is what is used.
"""

import pytest
from conftest import BGEO_SEQ_DIR
from pxr import Sdf, Usd

from bgeo_clips import BgeoClipsError, stitch_bgeo_clips

EXPECTED_SAMPLE_FRAMES = [1001, 1003, 1005, 1007, 1009, 1011,
                          1013, 1015, 1017, 1019, 1021, 1023]


def _clip_asset_paths(stage_path):
    """Read back the clip asset paths the stitcher authored."""
    stage = Usd.Stage.Open(str(stage_path))
    prim = stage.GetPrimAtPath("/ROOT")
    clips = prim.GetMetadata("clips")
    return [str(p.path) for p in clips["default"]["assetPaths"]]


def test_auto_detected_stitch_uses_scanned_paths_not_the_template(tmp_path):
    output_path = tmp_path / "out.usda"

    result = stitch_bgeo_clips(
        filepath_template=str(BGEO_SEQ_DIR / "offset_sparse.$F4.bgeo.sc"),
        output_path=str(output_path),
        strict=True,
    )

    assert result["status"] == "ok"
    assert result["primpath"] == "/ROOT"          # from usdconfigpathprefix
    assert result["frame_range"] == [1001, 1023]  # from usdconfigsampleframe
    assert result["frame_count"] == 12
    assert result["missing_files"] == []
    assert output_path.exists()

    # The authored assets must be the files that were scanned. Re-resolving
    # 1001..1023 through the template would have produced nonexistent paths.
    asset_paths = _clip_asset_paths(output_path)
    assert len(asset_paths) == 12
    assert [p.split("/")[-1] for p in asset_paths] == [
        f"offset_sparse.{n:04d}.bgeo.sc" for n in range(1, 13)
    ]


def test_auto_detected_stitch_preserves_the_sparse_timeline(tmp_path):
    output_path = tmp_path / "out.usda"

    stitch_bgeo_clips(
        filepath_template=str(BGEO_SEQ_DIR / "offset_sparse.$F4.bgeo.sc"),
        output_path=str(output_path),
        strict=True,
    )

    stage = Usd.Stage.Open(str(output_path))
    clips = stage.GetPrimAtPath("/ROOT").GetMetadata("clips")
    assert [t[0] for t in clips["default"]["times"]] == EXPECTED_SAMPLE_FRAMES
    assert stage.GetStartTimeCode() == 1001
    assert stage.GetEndTimeCode() == 1023


def test_loop_does_not_densify_an_auto_detected_sparse_timeline(tmp_path):
    """Both ranges omitted: the scanned timeline wins and loop is inert."""
    output_path = tmp_path / "out.usda"

    result = stitch_bgeo_clips(
        filepath_template=str(BGEO_SEQ_DIR / "offset_sparse.$F4.bgeo.sc"),
        output_path=str(output_path),
        loop=True,
        strict=True,
    )

    assert result["frame_count"] == 12
    # Each scanned file appears once and in order: looping would repeat them.
    assert [p.split("/")[-1] for p in _clip_asset_paths(output_path)] == [
        f"offset_sparse.{n:04d}.bgeo.sc" for n in range(1, 13)
    ]
    stage = Usd.Stage.Open(str(output_path))
    clips = stage.GetPrimAtPath("/ROOT").GetMetadata("clips")
    assert [t[0] for t in clips["default"]["times"]] == EXPECTED_SAMPLE_FRAMES


def test_topology_and_manifest_are_written_alongside_the_stage(tmp_path):
    output_path = tmp_path / "out.usda"

    result = stitch_bgeo_clips(
        filepath_template=str(BGEO_SEQ_DIR / "offset_sparse.$F4.bgeo.sc"),
        output_path=str(output_path),
        strict=True,
    )

    topology = tmp_path / "out.topology.usda"
    manifest = tmp_path / "out.manifest.usda"
    assert result["topology_path"] == str(topology)
    assert result["manifest_path"] == str(manifest)
    assert topology.exists() and manifest.exists()
    assert Sdf.Layer.FindOrOpen(str(topology)) is not None
    assert Sdf.Layer.FindOrOpen(str(manifest)) is not None


def test_explicit_frame_range_resolves_through_the_template(tmp_path):
    """configured.2-13 has sample frames equal to its filename frames."""
    output_path = tmp_path / "out.usda"

    result = stitch_bgeo_clips(
        filepath_template=str(BGEO_SEQ_DIR / "configured.$F.bgeo.sc"),
        output_path=str(output_path),
        frame_range=(2, 13),
        primpath="/ROOT",
        strict=True,
    )

    assert result["frame_count"] == 12
    assert [p.split("/")[-1] for p in _clip_asset_paths(output_path)] == [
        f"configured.{n}.bgeo.sc" for n in range(2, 14)
    ]


def test_primpath_inconsistent_with_the_cache_is_rejected(tmp_path):
    """offset_sparse declares /ROOT/mesh, so /Elsewhere cannot hold its samples."""
    with pytest.raises(BgeoClipsError, match="not descendants"):
        stitch_bgeo_clips(
            filepath_template=str(BGEO_SEQ_DIR / "offset_sparse.$F4.bgeo.sc"),
            output_path=str(tmp_path / "out.usda"),
            primpath="/Elsewhere",
            strict=True,
        )

    assert list(tmp_path.glob("out*")) == []
