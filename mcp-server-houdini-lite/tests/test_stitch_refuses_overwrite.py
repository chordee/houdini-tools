"""The stitchers must not destroy files that already exist.

vdb_stitch_volume_usd has refused an existing output_path since it was written;
the USD and bgeo stitchers did not, and the calls they use overwrite silently
rather than failing. Usd.Stage.CreateNew reads like it would refuse an existing
file — it does not, it truncates and returns a valid stage — and bgeo's
open(path, "w") truncates by definition. Neither leaves a trace.

The blast radius is wider than output_path. Both stitchers derive
<stem>.topology<ext> and <stem>.manifest<ext> from the output name and write
them BEFORE the output stage, so a run that fails partway has already replaced
two files the caller never named.

The guard is scoped to what the call will actually write: with gen_topology
off, an existing topology file is not this call's business and must not block
it.
"""

import pytest
from conftest import BGEO_SEQ_DIR
from mcp.client.client import Client
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_REQUEST
from pxr import Usd, UsdGeom

import server
from bgeo_clips import BgeoClipsError, stitch_bgeo_clips
from usd_clips import StitchClipsError, reserve_clip_outputs, stitch_clips

SENTINEL = "DO NOT DESTROY ME\n"


def _usd_frames(tmp_path):
    """Two per-frame USD files, the input any usd stitch needs."""
    for frame in (1, 2):
        stage = Usd.Stage.CreateNew(str(tmp_path / f"cache.{frame:04d}.usd"))
        UsdGeom.Xform.Define(stage, "/root")
        UsdGeom.Sphere.Define(stage, "/root/sphere")
        stage.GetRootLayer().Save()
    return str(tmp_path / "cache.$F4.usd")


def _stitch_usd(tmp_path, **overrides):
    kwargs = {
        "filepath_template": _usd_frames(tmp_path),
        "primpath": "/root",
        "output_path": str(tmp_path / "out.usda"),
        "frame_range": (1, 2),
    }
    kwargs.update(overrides)
    return stitch_clips(**kwargs)


def _stitch_bgeo(tmp_path, **overrides):
    kwargs = {
        "filepath_template": str(BGEO_SEQ_DIR / "offset_sparse.$F4.bgeo.sc"),
        "output_path": str(tmp_path / "out.usda"),
    }
    kwargs.update(overrides)
    return stitch_bgeo_clips(**kwargs)


@pytest.mark.parametrize("existing", ["out.usda", "out.topology.usda", "out.manifest.usda"])
def test_usd_stitch_refuses_to_overwrite_any_file_it_would_write(tmp_path, existing):
    victim = tmp_path / existing
    victim.write_text(SENTINEL)

    with pytest.raises(StitchClipsError, match="already exists"):
        _stitch_usd(tmp_path)

    assert victim.read_text() == SENTINEL, f"{existing} was overwritten"


@pytest.mark.parametrize("existing", ["out.usda", "out.topology.usda", "out.manifest.usda"])
def test_bgeo_stitch_refuses_to_overwrite_any_file_it_would_write(tmp_path, existing):
    victim = tmp_path / existing
    victim.write_text(SENTINEL)

    with pytest.raises(BgeoClipsError, match="already exists"):
        _stitch_bgeo(tmp_path)

    assert victim.read_text() == SENTINEL, f"{existing} was overwritten"


def test_the_refusal_happens_before_anything_is_written(tmp_path):
    """A guard that fires after generate_topology has already lost the file."""
    (tmp_path / "out.usda").write_text(SENTINEL)

    with pytest.raises(StitchClipsError, match="already exists"):
        _stitch_usd(tmp_path)

    written = sorted(p.name for p in tmp_path.glob("out.*"))
    assert written == ["out.usda"], f"guard fired too late, wrote: {written}"


def test_a_topology_file_is_not_a_blocker_when_topology_is_not_generated(tmp_path):
    """Scope the guard to this call's outputs, or gen_topology=False breaks."""
    (tmp_path / "out.topology.usda").write_text(SENTINEL)

    result = _stitch_usd(tmp_path, gen_topology=False, gen_manifest=False)

    assert result["status"] == "ok"
    assert (tmp_path / "out.topology.usda").read_text() == SENTINEL


def test_a_clean_target_directory_still_stitches(tmp_path):
    """The guard must not turn every ordinary run into a refusal."""
    assert _stitch_usd(tmp_path)["status"] == "ok"
    assert (tmp_path / "out.usda").exists()


def test_the_claim_is_materialized_not_merely_checked(tmp_path):
    """Two stitches must not both clear the guard and race to the same output.

    Sync tool handlers run concurrently in threads, so a check-then-write guard
    leaves a window where both callers see an absent file and the loser
    truncates the winner. Reserving with O_EXCL closes it: the second claim
    fails because the first one left a file behind, which an existence check
    alone never would.
    """
    output_path = str(tmp_path / "out.usda")
    reserve_clip_outputs(output_path, True, True, StitchClipsError)

    with pytest.raises(StitchClipsError, match="already exists"):
        reserve_clip_outputs(output_path, True, True, StitchClipsError)


def test_a_losing_claim_does_not_strand_the_files_it_got(tmp_path):
    """Partial reservations are released, or one refusal poisons the path."""
    (tmp_path / "out.manifest.usda").write_text(SENTINEL)

    with pytest.raises(StitchClipsError, match="already exists"):
        reserve_clip_outputs(str(tmp_path / "out.usda"), True, True, StitchClipsError)

    stranded = sorted(p.name for p in tmp_path.glob("out.*"))
    assert stranded == ["out.manifest.usda"], f"stranded: {stranded}"


def test_a_failed_bgeo_stitch_leaves_nothing_behind(tmp_path):
    """The reservation must be released when the stitch fails after it."""
    with pytest.raises(BgeoClipsError):
        _stitch_bgeo(tmp_path, primpath="not/absolute")

    leftovers = sorted(p.name for p in tmp_path.glob("out.*"))
    assert leftovers == [], f"partial output left behind: {leftovers}"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool_name,extra",
    [
        ("usd_stitch_clips", {"primpath": "/root", "frame_range": [1, 2]}),
        ("bgeo_stitch_usd_clips", {}),
    ],
)
async def test_the_refusal_reaches_the_caller_as_a_clean_error(tmp_path, tool_name, extra):
    """Each stitcher raises its own exception type so its handler translates it.

    Raising a shared type instead would slip past the handler's except clause
    and surface as a raw traceback rather than -32600, the code the vdb
    stitcher already returns for this same refusal.
    """
    (tmp_path / "out.usda").write_text(SENTINEL)
    arguments = {
        "filepath_template": str(tmp_path / "cache.$F4.usd"),
        "output_path": str(tmp_path / "out.usda"),
        **extra,
    }

    async with Client(server.app) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool(tool_name, arguments)

    assert exc.value.code == INVALID_REQUEST
    assert "already exists" in exc.value.message
    assert (tmp_path / "out.usda").read_text() == SENTINEL
