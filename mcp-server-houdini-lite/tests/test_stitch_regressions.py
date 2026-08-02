import pytest
from pxr import Usd, UsdGeom

import bgeo_clips
from bgeo_clips import BgeoClipsError, stitch_bgeo_clips
from usd_clips import StitchClipsError, stitch_clips


def test_bgeo_scan_only_uses_files_matching_the_template(tmp_path, monkeypatch):
    target = tmp_path / "target.0001.bgeo.sc"
    unrelated = tmp_path / "zzz.0001.bgeo.sc"
    target.touch()
    unrelated.touch()

    monkeypatch.setattr(
        bgeo_clips,
        "_read_meta",
        lambda path: {"sample_frame": 1001},
    )

    frame_map = bgeo_clips._scan_directory(
        str(tmp_path / "target.{frame:04d}.bgeo.sc")
    )

    assert frame_map == {1001: str(target)}


def test_bgeo_scan_rejects_duplicate_sample_frames(tmp_path, monkeypatch):
    first = tmp_path / "target.0001.bgeo.sc"
    second = tmp_path / "target.0002.bgeo.sc"
    first.touch()
    second.touch()

    monkeypatch.setattr(
        bgeo_clips,
        "_read_meta",
        lambda path: {"sample_frame": 1001},
    )

    with pytest.raises(BgeoClipsError, match="duplicate usdconfigsampleframe"):
        bgeo_clips._scan_directory(str(tmp_path / "target.$F4.bgeo.sc"))


def test_bgeo_auto_detection_preserves_scanned_asset_paths(tmp_path, monkeypatch):
    first_path = tmp_path / "target.0001.bgeo.sc"
    second_path = tmp_path / "target.0002.bgeo.sc"
    first_path.touch()
    second_path.touch()
    captured = {}

    monkeypatch.setattr(
        bgeo_clips,
        "_scan_directory",
        lambda template: {1001: str(first_path), 1003: str(second_path)},
    )
    monkeypatch.setattr(
        bgeo_clips,
        "_read_meta",
        lambda path: {"primpath": "/Geometry", "prim_paths": []},
    )
    monkeypatch.setattr(
        bgeo_clips,
        "_write_usda_clips",
        lambda **kwargs: captured.update(kwargs),
    )

    result = stitch_bgeo_clips(
        filepath_template=str(tmp_path / "target.{frame:04d}.bgeo.sc"),
        output_path=str(tmp_path / "out.usda"),
        gen_topology=False,
        gen_manifest=False,
        strict=True,
    )

    assert captured["asset_paths"] == [str(first_path), str(second_path)]
    assert captured["scene_frames"] == [1001, 1003]
    assert result["missing_files"] == []


@pytest.mark.parametrize(
    ("frame_range", "scene_range", "message"),
    [
        ((2, 1), None, "frame_range"),
        ((1, 2), (2, 1), "scene_range"),
    ],
)
def test_usd_stitch_rejects_reversed_ranges_before_writing(
    tmp_path, frame_range, scene_range, message
):
    with pytest.raises(StitchClipsError, match=message):
        stitch_clips(
            filepath_template=str(tmp_path / "cache.{frame}.usda"),
            primpath="/root",
            output_path=str(tmp_path / "out.usda"),
            frame_range=frame_range,
            scene_range=scene_range,
            fps=24.0,
        )

    assert list(tmp_path.glob("out*")) == []


def test_usd_stitch_rejects_missing_probe_prim_before_writing(tmp_path):
    probe_path = tmp_path / "cache.1.usda"
    stage = Usd.Stage.CreateNew(str(probe_path))
    UsdGeom.Xform.Define(stage, "/Other")
    stage.GetRootLayer().Save()

    with pytest.raises(StitchClipsError, match="primpath.*not found"):
        stitch_clips(
            filepath_template=str(tmp_path / "cache.{frame}.usda"),
            primpath="/Missing",
            output_path=str(tmp_path / "out.usda"),
            frame_range=(1, 1),
        )

    assert list(tmp_path.glob("out*")) == []
