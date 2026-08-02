"""usd_stitch_clips must reject a frame rate that would produce a broken stage.

fps is written straight into the stage as timeCodesPerSecond / framesPerSecond.
USD performs no validation of its own and stores 0, negatives, inf and nan
verbatim, so the resulting file declares a nonsense frame rate while the call
reports success. bgeo_stitch_usd_clips already rejects these; this covers the
usd path and the auto-detected value, which no field constraint can reach.
"""

import pytest
from mcp.client.client import Client
from pxr import Usd, UsdGeom

import server
from usd_clips import StitchClipsError, stitch_clips


@pytest.mark.parametrize("bad_fps", [0.0, -24.0])
def test_stitch_clips_rejects_non_positive_explicit_fps(bad_fps, tmp_path):
    with pytest.raises(StitchClipsError, match="fps"):
        stitch_clips(
            filepath_template=str(tmp_path / "cache.$F4.usd"),
            primpath="/root",
            output_path=str(tmp_path / "out.usda"),
            frame_range=(1, 2),
            fps=bad_fps,
        )


def test_stitch_clips_rejects_non_positive_auto_detected_fps(tmp_path):
    """A probe file carrying timeCodesPerSecond = 0 must not propagate silently."""
    for frame in (1, 2):
        path = tmp_path / f"cache.{frame:04d}.usd"
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.Xform.Define(stage, "/root")
        UsdGeom.Sphere.Define(stage, "/root/sphere")
        stage.SetTimeCodesPerSecond(0)
        stage.GetRootLayer().Save()

    with pytest.raises(StitchClipsError, match="fps"):
        stitch_clips(
            filepath_template=str(tmp_path / "cache.$F4.usd"),
            primpath="/root",
            output_path=str(tmp_path / "out.usda"),
            frame_range=(1, 2),
            fps=None,
        )

    # Rejecting late is not enough: topology, manifest and the output stage are
    # written before the frame rate is resolved, so a late raise would leave a
    # trail of partial output behind.
    leftovers = sorted(p.name for p in tmp_path.glob("out*"))
    assert leftovers == [], f"partial output left behind: {leftovers}"


@pytest.mark.anyio
@pytest.mark.parametrize("bad_fps", [0, -24])
async def test_usd_stitch_clips_tool_rejects_non_positive_fps(bad_fps, tmp_path):
    async with Client(server.app) as client:
        result = await client.call_tool(
            "usd_stitch_clips",
            {
                "filepath_template": str(tmp_path / "cache.$F4.usd"),
                "primpath": "/root",
                "output_path": str(tmp_path / "out.usda"),
                "frame_range": [1, 2],
                "fps": bad_fps,
            },
        )

    assert result.is_error is True
    assert "fps" in result.content[0].text


@pytest.mark.anyio
async def test_usd_stitch_clips_tool_still_accepts_a_valid_fps(tmp_path):
    """Guards against fixing the bug by rejecting everything."""
    for frame in (1, 2):
        path = tmp_path / f"cache.{frame:04d}.usd"
        stage = Usd.Stage.CreateNew(str(path))
        UsdGeom.Xform.Define(stage, "/root")
        stage.GetRootLayer().Save()

    async with Client(server.app) as client:
        result = await client.call_tool(
            "usd_stitch_clips",
            {
                "filepath_template": str(tmp_path / "cache.$F4.usd"),
                "primpath": "/root",
                "output_path": str(tmp_path / "out.usda"),
                "frame_range": [1, 2],
                "fps": 24.0,
            },
        )

    assert result.is_error is False
