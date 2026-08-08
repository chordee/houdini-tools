"""An empty scan has four causes and each one points somewhere different.

_scan_directory raises a cause-specific BgeoClipsError when it collects nothing:
the directory holds no .bgeo.sc at all, it holds some but none match the
filename template, every matching file failed to parse, or matching files
parsed but declare no usdconfigsampleframe. It used to return {} for all of
these and let the caller report "no readable .bgeo.sc with usdconfigsampleframe
found", which sent a user whose template simply did not match their filenames
off to inspect detail attributes that were never the problem.

The fixture directory holds three real Houdini sequences that make these cases
distinguishable with actual files rather than mocks:
  plain.1-12              — no usdconfigsampleframe at all
  configured.2-13         — usdconfigsampleframe matching the filename frame
  offset_sparse.0001-0012 — usdconfigsampleframe 1001,1003,...,1023
"""

import pytest
from conftest import BGEO_SEQ_DIR

import bgeo_clips
from bgeo_clips import BgeoClipsError


def test_scan_collects_only_the_requested_sequence(tmp_path):
    """Three sequences share the fixture directory; only one may be scanned."""
    frame_map = bgeo_clips._scan_directory(
        str(BGEO_SEQ_DIR / "offset_sparse.{frame:04d}.bgeo.sc")
    )

    assert sorted(frame_map) == [1001, 1003, 1005, 1007, 1009, 1011,
                                 1013, 1015, 1017, 1019, 1021, 1023]
    assert all("offset_sparse." in path for path in frame_map.values())


def test_scan_matches_the_template_case_insensitively():
    """Filenames and template may disagree on case; the scan still finds them."""
    frame_map = bgeo_clips._scan_directory(
        str(BGEO_SEQ_DIR / "OFFSET_SPARSE.$F4.bgeo.sc")
    )

    assert len(frame_map) == 12


def test_reports_the_template_when_files_exist_but_none_match(tmp_path):
    (tmp_path / "cache_0001.bgeo.sc").touch()
    (tmp_path / "cache_0002.bgeo.sc").touch()

    with pytest.raises(BgeoClipsError) as exc:
        bgeo_clips._scan_directory(str(tmp_path / "cache.{frame:04d}.bgeo.sc"))

    message = str(exc.value)
    # The cause is the template, so the message must point at it rather than
    # blame the file contents.
    assert "cache.{frame:04d}.bgeo.sc" in message
    assert "usdconfigsampleframe" not in message


def test_reports_an_empty_directory_distinctly(tmp_path):
    with pytest.raises(BgeoClipsError) as exc:
        bgeo_clips._scan_directory(str(tmp_path / "cache.{frame:04d}.bgeo.sc"))

    message = str(exc.value)
    assert "no .bgeo.sc" in message
    assert "usdconfigsampleframe" not in message


def test_still_blames_the_sample_frame_when_matching_files_lack_it():
    """plain.* are real caches written without usdconfigsampleframe."""
    with pytest.raises(BgeoClipsError) as exc:
        bgeo_clips._scan_directory(str(BGEO_SEQ_DIR / "plain.$F.bgeo.sc"))

    assert "usdconfigsampleframe" in str(exc.value)


def test_reports_unreadable_caches_rather_than_missing_sample_frames(tmp_path):
    """Files that match but cannot be parsed are corrupt, not unconfigured."""
    for name in ("cache.0001.bgeo.sc", "cache.0002.bgeo.sc"):
        (tmp_path / name).write_bytes(b"not a bgeo at all")

    with pytest.raises(BgeoClipsError) as exc:
        bgeo_clips._scan_directory(str(tmp_path / "cache.{frame:04d}.bgeo.sc"))

    message = str(exc.value)
    assert "unreadable" in message
    assert "usdconfigsampleframe" not in message
