"""
bgeo_reader.py — Houdini geometry cache format parser

Supports two formats:
  1. Classic bgeo V5 binary  (magic: 0x4267656F 'Bgeo')
  2. Houdini Binary JSON      (magic: \x7fNSJ)

Public entry points:
  parse_header()             — point/prim counts only (fast path)
  parse_inspect()            — rich metadata: counts, attributes, prim types, file info
  read_bgeo_clip_metadata()  — USD clip configuration for stitch workflow
"""

import re
import struct
from dataclasses import dataclass

# ── Constants ─────────────────────────────────────────────────────────────────

_V5_MAGIC = 0x4267656F   # 'Bgeo'
BJSON_MAGIC = b'\x7fNSJ'

# ── Data structures ───────────────────────────────────────────────────────────

class InvalidMagicError(Exception):
    pass


class ParseError(Exception):
    pass


@dataclass
class BgeoHeader:
    version: int
    npoints: int
    nprims: int


# ── Public entry point ────────────────────────────────────────────────────────

def parse_header(data: bytes) -> BgeoHeader:
    """
    Auto-detect format and parse the bgeo/BJSON geometry cache header.
    Returns only reliable metadata (point/prim counts).
    """
    if len(data) < 4:
        raise ParseError("data too short")

    if data[:4] == BJSON_MAGIC:
        return _parse_bjson(data)

    magic = struct.unpack_from(">I", data, 0)[0]
    if magic == _V5_MAGIC:
        return _parse_v5_binary(data)

    raise InvalidMagicError(f"unknown format magic: {data[:4].hex()}")


# ═══════════════════════════════════════════════════════════════════════════════
# BJSON parser (Houdini Binary JSON, Houdini 18+)
# ═══════════════════════════════════════════════════════════════════════════════

class _BJsonReader:
    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos
        self.strtab: dict[int, str] = {}

    def _b(self) -> int:
        if self.pos >= len(self.data):
            raise ParseError("unexpected end of data")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def _str(self) -> str:
        n = self._b()
        s = self.data[self.pos: self.pos + n].decode("ascii", errors="replace")
        self.pos += n
        return s

    def read(self):
        while True:
            if self.pos >= len(self.data):
                raise ParseError("unexpected end of BJSON data")
            b = self.data[self.pos]

            if b == 0x2b:          # '+' intern string
                self.pos += 1
                sid = self._b()
                s = self._str()
                self.strtab[sid] = s
            elif b == 0x26:        # '&' reference string
                self.pos += 1
                sid = self._b()
                return self.strtab.get(sid, f"<str:{sid}>")
            elif b == 0x5b:        # '[' array
                self.pos += 1
                items = []
                while self.pos < len(self.data) and self.data[self.pos] != 0x5d:
                    try: items.append(self.read())
                    except ParseError: break
                if self.pos < len(self.data) and self.data[self.pos] == 0x5d: self.pos += 1
                return items
            elif b == 0x7b:        # '{' dict
                self.pos += 1
                d = {}
                while self.pos < len(self.data) and self.data[self.pos] != 0x7d:
                    try:
                        k = self.read()
                        v = self.read()
                        if isinstance(k, str): d[k] = v
                    except ParseError: break
                if self.pos < len(self.data) and self.data[self.pos] == 0x7d: self.pos += 1
                return d
            elif b == 0x11: self.pos += 1; return self._b()
            elif b == 0x12:
                self.pos += 1
                v = struct.unpack_from("<h", self.data, self.pos)[0]
                self.pos += 2
                return v
            elif b == 0x13:
                self.pos += 1
                v = struct.unpack_from("<i", self.data, self.pos)[0]
                self.pos += 4
                return v
            elif b == 0x14:
                self.pos += 1
                v = struct.unpack_from("<q", self.data, self.pos)[0]
                self.pos += 8
                return v
            elif b == 0x19:
                self.pos += 1
                v = struct.unpack_from("<f", self.data, self.pos)[0]
                self.pos += 4
                return v
            elif b == 0x1a:
                self.pos += 1
                v = struct.unpack_from("<d", self.data, self.pos)[0]
                self.pos += 8
                return v
            elif b == 0x30: self.pos += 1; return False
            elif b == 0x31: self.pos += 1; return True
            elif b == 0x27:
                self.pos += 1
                length = self._b()
                s = self.data[self.pos: self.pos + length].decode("ascii", errors="replace")
                self.pos += length
                return s
            elif b == 0x40:
                self.pos += 1
                type_byte = self._b()
                count_byte = self._b()
                count = count_byte
                if count_byte >= 0x80:
                    extra = count_byte & 0x0f
                    if extra > 4:
                        raise ParseError(f"BJSON array count too wide: {extra} bytes")
                    count = 0
                    for i in range(extra): count |= self._b() << (8 * i)
                elem_size = {0x10:4, 0x11:1, 0x12:2, 0x13:4, 0x14:8, 0x18:2, 0x19:4, 0x1a:8}.get(type_byte, 1)
                self.pos += min(count * elem_size, len(self.data) - self.pos)
                return f"<array:{count}>"
            else:
                raise ParseError(f"unknown BJSON token {b:#x}")


def _parse_bjson(data: bytes) -> BgeoHeader:
    pos = 4
    if pos < len(data) and data[pos] == ord('b'): pos += 1
    if pos >= len(data) or data[pos] != ord('['): raise ParseError("expected '['")
    pos += 1
    reader = _BJsonReader(data, pos)
    npoints = nprims = 0
    try:
        while reader.pos < len(data) and data[reader.pos] != 0x5d:
            key = reader.read()
            val = reader.read()
            if key == "pointcount": npoints = int(val)
            elif key == "primitivecount": nprims = int(val)
    except (ParseError, struct.error): pass
    return BgeoHeader(version=-1, npoints=npoints, nprims=nprims)


_SUMMARY_SCOPE_MAP = {
    "point":     "point",
    "primitive": "prim",
    "vertex":    "vertex",
    "global":    "detail",
}

_SUMMARY_RE = re.compile(
    r'(\d+)\s+(point|primitive|vertex|global)\s+attributes?:\s*(.*)',
    re.IGNORECASE,
)


def _parse_attribute_summary(summary: str) -> dict[str, list[str]]:
    """Parse attribute_summary string into {scope: [name, ...]}."""
    result: dict[str, list[str]] = {s: [] for s in _SUMMARY_SCOPE_MAP.values()}
    for line in summary.splitlines():
        m = _SUMMARY_RE.search(line)
        if not m:
            continue
        scope = _SUMMARY_SCOPE_MAP[m.group(2).lower()]
        names_raw = m.group(3).strip()
        if names_raw:
            result[scope] = [n.strip() for n in names_raw.split(',') if n.strip()]
    return result


def _extract_attr_entry(entry) -> tuple:
    """Extract (name, size, storage, strings) from a BJSON attribute entry list."""
    if not isinstance(entry, list) or len(entry) < 2:
        return None, None, None, None
    meta, attr_data = entry[0], entry[1]
    if not isinstance(meta, list):
        return None, None, None, None
    try:
        name = meta[meta.index("name") + 1]
    except (ValueError, IndexError):
        return None, None, None, None
    size = storage = strings = None
    if isinstance(attr_data, list):
        try: size = attr_data[attr_data.index("size") + 1]
        except (ValueError, IndexError): pass
        try: storage = attr_data[attr_data.index("storage") + 1]
        except (ValueError, IndexError): pass
        try: strings = attr_data[attr_data.index("strings") + 1]
        except (ValueError, IndexError): pass
    return name, size, storage, strings


def read_bgeo_clip_metadata(data: bytes) -> dict:
    """
    Extract USD clip configuration from a decompressed BJSON buffer (after the 4-byte magic).

    Walks the BJSON top-level dict to find:
      - globalattributes: usdconfigpathprefix, usdconfigsampleframe
      - primitiveattributes: unique 'path' strings (sub-prim hierarchy)
      - pointattributes: (name, size, storage) tuples

    Returns:
        primpath      str | None   — value of usdconfigpathprefix
        sample_frame  int | None   — value of usdconfigsampleframe (converted to int)
        prim_paths    list[str]    — unique prim paths from 'path' primitive attribute
        point_attribs list[tuple]  — [(name, size, storage), ...] from pointattributes
        prim_attribs  list[tuple]  — [(name, size, storage), ...] excluding 'path'
    """
    pos = 0
    if pos < len(data) and data[pos] == ord('b'): pos += 1
    if pos >= len(data) or data[pos] != ord('['): raise ParseError("expected '['")
    pos += 1

    reader = _BJsonReader(data, pos)
    primpath = None
    sample_frame = None
    prim_paths: list[str] = []
    point_attribs: list[tuple] = []
    prim_attribs: list[tuple] = []
    vertex_attribs: list[tuple] = []
    detail_attribs: list[tuple] = []

    try:
        while reader.pos < len(data) and data[reader.pos] != 0x5d:
            key = reader.read()
            val = reader.read()
            if key != "attributes":
                continue
            # val is a flat list: [section_name, section_data, ...]
            if not isinstance(val, list):
                break
            for i in range(0, len(val) - 1, 2):
                sname = val[i]
                sdata = val[i + 1]
                if not isinstance(sdata, list):
                    continue
                for entry in sdata:
                    name, size, storage, strings = _extract_attr_entry(entry)
                    if name is None:
                        continue

                    if sname == "globalattributes":
                        if name == "usdconfigpathprefix" and isinstance(strings, list) and strings:
                            primpath = strings[0]
                        elif name == "usdconfigsampleframe" and isinstance(strings, list) and strings:
                            try: sample_frame = int(strings[0])
                            except (ValueError, TypeError): pass
                    elif sname == "primitiveattributes":
                        if name == "path" and isinstance(strings, list):
                            seen: set[str] = set()
                            prim_paths = [
                                s for s in strings
                                if isinstance(s, str) and s not in seen and not seen.add(s)
                            ]
                        elif size is not None and storage is not None:
                            prim_attribs.append((name, size, storage))
                    elif sname == "pointattributes":
                        if size is not None and storage is not None:
                            point_attribs.append((name, size, storage))
                    elif sname == "vertexattributes":
                        if size is not None and storage is not None:
                            vertex_attribs.append((name, size, storage))
                    elif sname == "detailattributes":
                        if name not in ("usdconfigpathprefix", "usdconfigsampleframe"):
                            if size is not None and storage is not None:
                                detail_attribs.append((name, size, storage))
            break
    except (ParseError, struct.error):
        pass

    return {
        "primpath": primpath,
        "sample_frame": sample_frame,
        "prim_paths": prim_paths,
        "point_attribs": point_attribs,
        "prim_attribs": prim_attribs,
        "vertex_attribs": vertex_attribs,
        "detail_attribs": detail_attribs,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# bgeo full-metadata inspector (BJSON, single-pass)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_inspect(data: bytes) -> dict:
    """
    Auto-detect format and return rich geometry metadata from the first Blosc chunk.

    Returns a JSON-serializable dict with:
      fileversion, npoints, nprims, nvertices, info, prim_types, prim_paths,
      attributes (point / prim / vertex / detail — each entry has name, size,
      storage, values where values is a list[str] for string attrs or null).
    """
    if len(data) < 4:
        raise ParseError("data too short")

    if data[:4] == BJSON_MAGIC:
        return _inspect_bjson(data)

    magic = struct.unpack_from(">I", data, 0)[0]
    if magic == _V5_MAGIC:
        h = _parse_v5_binary(data)
        return {
            "fileversion": None,
            "npoints": h.npoints,
            "nprims": h.nprims,
            "nvertices": 0,
            "info": {},
            "prim_types": [],
            "prim_paths": [],
            "attributes": {"point": [], "prim": [], "vertex": [], "detail": []},
        }

    raise InvalidMagicError(f"unknown format magic: {data[:4].hex()}")


def _inspect_bjson(data: bytes) -> dict:
    pos = 4
    if pos < len(data) and data[pos] == ord('b'): pos += 1
    if pos >= len(data) or data[pos] != ord('['): raise ParseError("expected '['")
    pos += 1

    reader = _BJsonReader(data, pos)

    fileversion: str | None = None
    npoints = nprims = nvertices = 0
    info_out: dict = {}
    prim_types: list[str] = []
    prim_paths: list[str] = []
    attribs: dict = {"point": [], "prim": [], "vertex": [], "detail": []}

    try:
        while reader.pos < len(data) and data[reader.pos] != 0x5d:
            key = reader.read()
            val = reader.read()

            if key == "fileversion":
                fileversion = str(val) if val is not None else None

            elif key == "pointcount":
                npoints = int(val)
            elif key == "vertexcount":
                nvertices = int(val)
            elif key == "primitivecount":
                nprims = int(val)

            elif key == "info" and isinstance(val, dict):
                info_out = {
                    "software":          val.get("software"),
                    "date":              val.get("date"),
                    "timetocook":        val.get("timetocook"),
                    "primcount_summary": (val.get("primcount_summary") or "").strip() or None,
                    "attribute_summary": (val.get("attribute_summary") or "").strip() or None,
                }

            elif key == "attributes" and isinstance(val, list):
                for i in range(0, len(val) - 1, 2):
                    sname = val[i]
                    sdata = val[i + 1]
                    if not isinstance(sdata, list):
                        continue
                    for entry in sdata:
                        name, size, storage, strings = _extract_attr_entry(entry)
                        if name is None:
                            continue
                        values = (
                            [s for s in strings if isinstance(s, str)]
                            if isinstance(strings, list) else None
                        )
                        rec = {"name": name, "size": size, "storage": storage, "values": values}

                        if sname in ("globalattributes", "detailattributes"):
                            attribs["detail"].append(rec)
                        elif sname == "primitiveattributes":
                            if name == "path" and isinstance(strings, list):
                                seen: set[str] = set()
                                prim_paths = [
                                    s for s in strings
                                    if isinstance(s, str) and s not in seen and not seen.add(s)  # type: ignore[func-returns-value]
                                ]
                            attribs["prim"].append(rec)
                        elif sname == "pointattributes":
                            attribs["point"].append(rec)
                        elif sname == "vertexattributes":
                            attribs["vertex"].append(rec)

            elif key == "primitives" and isinstance(val, list):
                seen_types: set[str] = set()
                for entry in val:
                    if not isinstance(entry, list) or not entry:
                        continue
                    meta = entry[0]
                    if not isinstance(meta, list):
                        continue
                    t: str | None = None
                    if "runtype" in meta:
                        try: t = meta[meta.index("runtype") + 1]
                        except IndexError: pass
                    elif "type" in meta:
                        try:
                            t = meta[meta.index("type") + 1]
                            if t == "run": t = None
                        except IndexError: pass
                    if t and isinstance(t, str) and t not in seen_types:
                        prim_types.append(t)
                        seen_types.add(t)

    except (ParseError, struct.error):
        pass

    # Fallback: supplement truncated attribute lists using attribute_summary.
    # Occurs when large binary arrays in the first chunk push later attr
    # definitions beyond the 1MB boundary.
    summary_str = info_out.get("attribute_summary") or ""
    if summary_str:
        summary_attrs = _parse_attribute_summary(summary_str)
        for scope in ("point", "prim", "vertex", "detail"):
            existing = {a["name"] for a in attribs[scope]}
            for name in summary_attrs.get(scope, []):
                if name not in existing:
                    attribs[scope].append(
                        {"name": name, "size": None, "storage": None, "values": None}
                    )

    return {
        "fileversion": fileversion,
        "npoints": npoints,
        "nprims": nprims,
        "nvertices": nvertices,
        "info": info_out,
        "prim_types": prim_types,
        "prim_paths": prim_paths,
        "attributes": attribs,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# bgeo V5 binary parser
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_v5_binary(data: bytes) -> BgeoHeader:
    if len(data) < 41: raise ParseError("data too short")
    (version,) = struct.unpack_from(">i", data, 5)
    counts = struct.unpack_from(">iiii", data, 9)
    return BgeoHeader(version=version, npoints=counts[0], nprims=counts[1])
