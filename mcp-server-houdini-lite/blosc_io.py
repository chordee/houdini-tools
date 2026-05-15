"""
blosc_io.py — Minimal Blosc I/O layer

Always reads only the first chunk; never reads the
entire file regardless of its size.
"""

import struct
from pathlib import Path

import blosc

SCFM_MAGIC = b'scf1'
SCFM_HDR_SIZE = 12  # scf1 header is always 12 bytes


class BloscDecompressError(Exception):
    pass


def read_first_chunk(path, max_read: int = 1_048_576) -> bytes:
    """
    Read a .bgeo.sc file and decompress its first Blosc chunk.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"file not found: {path}")

    with open(path, 'rb') as f:
        header = f.read(SCFM_HDR_SIZE)

    if header[:4] == SCFM_MAGIC:
        return _read_schunk_first_block(path)
    else:
        return _read_classic_blosc(path, max_read)


def _read_schunk_first_block(path: Path) -> bytes:
    """Read the first Blosc1 chunk from a scf1 container."""
    with open(path, 'rb') as f:
        f.seek(SCFM_HDR_SIZE)
        peek = f.read(16)
        if len(peek) < 16:
            raise BloscDecompressError("file too short")
        # cbytes in the Blosc1 header includes the 16-byte header itself
        cbytes = struct.unpack_from('<I', peek, 12)[0]
        if cbytes == 0 or cbytes > 256 * 1024 * 1024:
            raise BloscDecompressError(f"implausible cbytes: {cbytes}")
        f.seek(SCFM_HDR_SIZE)
        chunk_data = f.read(cbytes)

    if len(chunk_data) < cbytes:
        raise BloscDecompressError(
            f"incomplete chunk: read {len(chunk_data)} of {cbytes} bytes"
        )
    try:
        return blosc.decompress(chunk_data)
    except Exception as e:
        raise BloscDecompressError(f"blosc failed: {e}") from e


def _read_classic_blosc(path: Path, max_read: int) -> bytes:
    """Fallback for older Houdini versions."""
    with open(path, 'rb') as f:
        raw = f.read(max_read)
    try:
        return blosc.decompress(raw)
    except Exception:
        pass

    fallback = 4 * 1_048_576
    if max_read >= fallback:
        raise BloscDecompressError("blosc decompression failed")
    with open(path, 'rb') as f:
        raw = f.read(fallback)
    try:
        return blosc.decompress(raw)
    except Exception as e:
        raise BloscDecompressError(f"blosc failed after retry: {e}") from e
