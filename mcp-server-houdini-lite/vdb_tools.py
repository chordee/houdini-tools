"""
vdb_tools.py — VDB file header inspection

Parses the binary header of an OpenVDB (.vdb) file using only the Python
standard library (no pyopenvdb, no Houdini). Returns grid names, types,
and file-level metadata. No voxel data is loaded.
"""

import struct
from pathlib import Path

VDB_MAGIC = 0x56444220  # b"VDB "

VDB_TYPE_MAP = {
    "Tree_float_5_4_3":            "FloatGrid  (32-bit)",
    "Tree_float_5_4_3_HalfFloat":  "FloatGrid  (saved as 16-bit half)",
    "Tree_half_5_4_3":             "HalfGrid   (16-bit)",
    "Tree_double_5_4_3":           "DoubleGrid (64-bit)",
    "Tree_int32_5_4_3":            "Int32Grid  (32-bit)",
    "Tree_int64_5_4_3":            "Int64Grid  (64-bit)",
    "Tree_vec3s_5_4_3":            "Vec3SGrid  (32-bit)",
    "Tree_vec3s_5_4_3_HalfFloat":  "Vec3SGrid  (saved as 16-bit half)",
    "Tree_vec3h_5_4_3":            "Vec3HGrid  (16-bit)",
    "Tree_vec3d_5_4_3":            "Vec3DGrid  (64-bit)",
    "Tree_bool_5_4_3":             "BoolGrid",
    "Tree_mask_5_4_3":             "MaskGrid",
}

_METADATA_FIXED_SIZE = {
    "bool":   1,
    "half":   2,
    "int32":  4,
    "float":  4,
    "int64":  8,
    "double": 8,
    "vec3i":  12,
    "vec3s":  12,
    "vec3h":  6,
    "vec3d":  24,
    "mat4s":  64,
    "mat4d":  128,
}


class VdbParseError(Exception):
    """Raised when the file is not a valid VDB or the header cannot be parsed."""


def _read_string(f) -> str:
    length = struct.unpack("<I", f.read(4))[0]
    return f.read(length).decode("utf-8", errors="replace")


def _read_metadata_value(f, type_name: str):
    """
    Read and return the value for a metadata entry, or return None for
    unknown types after safely skipping them via a uint32 length prefix.
    """
    if type_name == "string":
        length = struct.unpack("<I", f.read(4))[0]
        return f.read(length).decode("utf-8", errors="replace")

    if type_name == "bool":
        return bool(f.read(1)[0])
    if type_name == "int32":
        return struct.unpack("<i", f.read(4))[0]
    if type_name == "int64":
        return struct.unpack("<q", f.read(8))[0]
    if type_name == "float":
        return struct.unpack("<f", f.read(4))[0]
    if type_name == "double":
        return struct.unpack("<d", f.read(8))[0]
    if type_name == "vec3i":
        return list(struct.unpack("<iii", f.read(12)))
    if type_name == "vec3s":
        return list(struct.unpack("<fff", f.read(12)))
    if type_name == "vec3d":
        return list(struct.unpack("<ddd", f.read(24)))

    if type_name in _METADATA_FIXED_SIZE:
        f.read(_METADATA_FIXED_SIZE[type_name])
        return None

    try:
        length = struct.unpack("<I", f.read(4))[0]
        f.read(length)
        return None
    except Exception as e:
        raise VdbParseError(
            f"unknown metadata type '{type_name}' and length-prefix fallback failed"
        ) from e


def _read_metadata(f) -> list[dict]:
    count = struct.unpack("<I", f.read(4))[0]
    items = []
    for _ in range(count):
        key       = _read_string(f)
        type_name = _read_string(f)
        value     = _read_metadata_value(f, type_name)
        items.append({"key": key, "type": type_name, "value": value})
    return items


def _read_grid_descriptor(f, has_grid_offsets: bool) -> dict:
    name      = _read_string(f)
    grid_type = _read_string(f)
    instance  = _read_string(f)
    end_pos = None
    if has_grid_offsets:
        struct.unpack("<q", f.read(8))[0]  # grid buffer position
        struct.unpack("<q", f.read(8))[0]  # block buffer position
        end_pos = struct.unpack("<q", f.read(8))[0]
    return {
        "name":          name,
        "grid_type":     grid_type,
        "friendly_type": VDB_TYPE_MAP.get(grid_type, grid_type),
        "instance":      instance,
        "_end_pos":      end_pos,
    }


def read_vdb_inspect(path: str) -> dict:
    """
    Parse a VDB header and return its structural summary.

    Returns:
        {
          "path":            str,
          "file_version":    int,
          "library_version": [major, minor],
          "uuid":            str,
          "metadata":        [{"key", "type", "value"|None}, ...],
          "grid_count":      int,
          "grids":           [{"name", "grid_type", "friendly_type", "instance"}, ...],
        }

    Raises:
        FileNotFoundError — file does not exist
        VdbParseError     — invalid magic or header cannot be parsed
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"file not found: {path}")

    with open(p, "rb") as f:
        magic = struct.unpack("<q", f.read(8))[0]
        if magic != VDB_MAGIC:
            raise VdbParseError(f"not a valid VDB file (magic mismatch): {path}")

        file_version    = struct.unpack("<I", f.read(4))[0]
        major, minor    = struct.unpack("<II", f.read(8))
        has_grid_offsets = struct.unpack("<?", f.read(1))[0]

        uuid_bytes = f.read(36)
        uuid = uuid_bytes.decode("ascii", errors="replace")

        metadata = _read_metadata(f)

        if not has_grid_offsets:
            raise VdbParseError(
                "VDB file has no grid offsets; cannot inspect without "
                "parsing grid bodies. Re-save with offsets enabled."
            )

        grid_count = struct.unpack("<I", f.read(4))[0]
        grids = []
        for _ in range(grid_count):
            g = _read_grid_descriptor(f, has_grid_offsets)
            end_pos = g.pop("_end_pos")
            grids.append(g)
            if end_pos is not None:
                f.seek(end_pos)

    return {
        "path":            str(p),
        "file_version":    file_version,
        "library_version": [major, minor],
        "uuid":            uuid,
        "metadata":        metadata,
        "grid_count":      grid_count,
        "grids":           grids,
    }
