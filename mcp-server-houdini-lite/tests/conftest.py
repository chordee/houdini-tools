from pathlib import Path

import pytest

# Real Houdini-authored .bgeo.sc sequences used by the stitcher tests.
# Three sequences share one directory on purpose, so template filtering is
# exercised against actual files rather than synthetic ones:
#   plain.1-12              — written without usdconfigsampleframe
#   configured.2-13         — usdconfigsampleframe equal to the filename frame
#   offset_sparse.0001-0012 — usdconfigsampleframe 1001,1003,...,1023, so a
#                             path re-resolved from the sample frame would miss
BGEO_SEQ_DIR = Path(__file__).parent / "fixtures" / "bgeo_seq"


@pytest.fixture
def anyio_backend():
    return "asyncio"
