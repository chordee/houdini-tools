# houdini-lite

A lightweight [MCP](https://modelcontextprotocol.io/) server for Houdini pipeline tools. **No Houdini installation required** — reads `.bgeo.sc` files directly via Blosc decompression and BJSON parsing. Inspects `.bgeo.sc` geometry caches (attributes, geometry type, metadata) and USD scene files without loading full geometry into memory.

---

## Tools

### bgeo

#### `bgeo_read_header`

Reads point and primitive counts from a single `.bgeo.sc` file.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to a `.bgeo.sc` file |

**Output** (JSON)

```json
{
  "path": "/path/to/file.bgeo.sc",
  "version": -1,
  "npoints": 1500000,
  "nprims": 1
}
```

`version: -1` indicates Houdini Binary JSON format (Houdini 18+), which has no numeric version field.

---

#### `bgeo_inspect`

Reads rich metadata from a single `.bgeo.sc` file without loading geometry.
Reads only the first Blosc chunk — fast even for multi-GB files.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to a `.bgeo.sc` file |

**Output** (JSON)

```json
{
  "path": "/cache/sim.1001.bgeo.sc",
  "fileversion": "21.0.512",
  "npoints": 7954138,
  "nprims": 0,
  "nvertices": 0,
  "info": {
    "software": "Houdini 21.0.512",
    "date": "2026-04-02 18:06:01",
    "timetocook": 36.6,
    "primcount_summary": "4 VDBs",
    "attribute_summary": "11 point attributes:\tv, foam, ..."
  },
  "prim_types": ["VDB"],
  "prim_paths": [],
  "attributes": {
    "point": [
      { "name": "P",    "size": 3, "storage": "fpreal32", "values": null },
      { "name": "foam", "size": 1, "storage": "fpreal16", "values": null }
    ],
    "prim": [
      { "name": "name", "size": 1, "storage": "int32", "values": ["density", "flame"] }
    ],
    "vertex": [],
    "detail": [
      { "name": "varmap", "size": 7, "storage": "int32", "values": ["dopobject -> DOPOBJECT"] }
    ]
  }
}
```

`values` is a `list[str]` for string-type attributes; `null` for numeric types (binary data is not in the first chunk). If `size` and `storage` are both `null`, the entry was recovered from `info.attribute_summary` as a fallback — occurs when binary point data fills the 1 MB first chunk before all attribute definitions are written (typical in large particle caches).

---

#### `bgeo_list_sequence`

Scans a directory for numbered `.bgeo.sc` files and **groups them into sequences by base name** (the filename portion before the frame number). Multiple coexisting sequences in one directory are returned separately. Files whose frame number cannot be extracted are reported in `unmatched`. Does not open any geometry file.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `directory` | string | Directory containing the cache files |
| `pattern` | string | Glob pattern (default: `*.bgeo.sc`) |

**Output** (JSON)

```json
{
  "directory": "/path/to/cache",
  "sequence_count": 2,
  "sequences": [
    {
      "base_name": "flip",
      "frame_count": 240,
      "frame_range": { "first": 1001, "last": 1240 },
      "total_size_bytes": 42949672960,
      "frames": [
        { "frame": 1001, "filename": "flip.1001.bgeo.sc", "size_bytes": 178257920 }
      ]
    },
    {
      "base_name": "pyro",
      "frame_count": 120,
      "frame_range": { "first": 1001, "last": 1120 },
      "total_size_bytes": 1234567,
      "frames": [
        { "frame": 1001, "filename": "pyro.1001.bgeo.sc", "size_bytes": 10000 }
      ]
    }
  ],
  "unmatched": []
}
```

---

### VDB

#### `vdb_inspect`

Parses the binary header of an OpenVDB (`.vdb`) file using only the Python standard library — **no `pyopenvdb` and no Houdini required**. Returns each grid's name, raw grid type, a friendly type label, and any instance parent name. Also returns file-level metadata (the standard OpenVDB header `MetaMap`). No voxel data is loaded.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to a `.vdb` file |

**Output** (JSON)

```json
{
  "path": "/cache/sim.1001.vdb",
  "file_version": 224,
  "library_version": [12, 0],
  "uuid": "4B7928FA-C534-A025-7306-DAD9E5618DA5",
  "metadata": [
    { "key": "creator", "type": "string", "value": "Houdini 21.0.559/GEO_VDBTranslator" }
  ],
  "grid_count": 3,
  "grids": [
    { "name": "burn",        "grid_type": "Tree_float_5_4_3",           "friendly_type": "FloatGrid  (32-bit)",            "instance": "" },
    { "name": "temperature", "grid_type": "Tree_float_5_4_3_HalfFloat", "friendly_type": "FloatGrid  (saved as 16-bit half)", "instance": "" },
    { "name": "v",           "grid_type": "Tree_vec3s_5_4_3",           "friendly_type": "Vec3SGrid  (32-bit)",            "instance": "" }
  ]
}
```

Known grid types are mapped to friendly labels (`FloatGrid`, `Vec3SGrid`, etc.); unknown types fall back to the raw `Tree_*` string. File-level metadata values are decoded for common types (`string`, `int32`, `int64`, `float`, `double`, `bool`, `vec3i`, `vec3s`, `vec3d`); other known fixed-width types are skipped with `value: null`.

#### `vdb_stitch_volume_usd`

Stitches a numbered `.vdb` sequence into a single USD file containing a `UsdVol.Volume` with one `UsdVol.OpenVDBAsset` child per grid. The `filePath`, `fieldName`, and `fieldIndex` attributes are time-sampled across `frame_range`. Grids are auto-detected from the probe frame unless an explicit list is given. **No Houdini required. This tool writes files to disk.**

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filepath_template` | string | yes | Per-frame template; supports `{frame:04d}` or `$F4` format |
| `output_path` | string | yes | Absolute output path (`.usd` / `.usda` / `.usdc`). Must not already exist. |
| `frame_range` | `[int, int]` | yes | `[start, end]` frame range (inclusive) |
| `volume_name` | string | yes | Name of the `UsdVol.Volume` prim (single path segment) |
| `parent_primpath` | string | yes | Absolute USD path to the parent Xform, e.g. `/scene`. Created if missing. |
| `probe_frame` | integer | no | Frame used to detect grids. Defaults to start of `frame_range` |
| `grids` | string[] | no | Explicit grid names to include. Defaults to all grids from probe |
| `strict` | boolean | no | Abort if any source file is missing. Default: `false` |

**Output** (JSON)

```json
{
  "status": "ok",
  "output_path": "/scene/smoke.usda",
  "volume_primpath": "/scene/smoke",
  "grids": [
    { "grid_name": "burn",        "prim_path": "/scene/smoke/burn" },
    { "grid_name": "temperature", "prim_path": "/scene/smoke/temperature" },
    { "grid_name": "v",           "prim_path": "/scene/smoke/v" }
  ],
  "frame_range": [1, 12],
  "frame_count": 12,
  "probe_frame": 1,
  "probe_path": "/cache/sim.1.vdb",
  "missing_files": []
}
```

The output USD declares `field:<grid_name>` relationships from the Volume to each `OpenVDBAsset`, and writes time samples on the stage's start/end time codes. `filePath` is written exactly as resolved by `filepath_template` — use a relative template if you want a portable output.

#### `vdb_list_sequence`

Scans a directory for numbered `.vdb` files and **groups them into sequences by base name**, same shape as `bgeo_list_sequence`. Useful when a single directory holds multiple coexisting VDB sequences.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `directory` | string | Directory to scan |
| `pattern` | string | Glob pattern (default: `*.vdb`) |

**Output** (JSON)

```json
{
  "directory": "/cache/vdb",
  "sequence_count": 3,
  "sequences": [
    {
      "base_name": "sphere",
      "frame_count": 12,
      "frame_range": { "first": 1, "last": 12 },
      "total_size_bytes": 2881896,
      "frames": [
        { "frame": 1,  "filename": "sphere.1.vdb",  "size_bytes": 240158 },
        { "frame": 2,  "filename": "sphere.2.vdb",  "size_bytes": 240158 }
      ]
    }
  ],
  "unmatched": []
}
```

Per-sequence `frames` is always fully populated (length equal to `frame_count`); the example above is abridged to a single sequence with two frames.

---

### USD

#### `usd_read_layer_metadata`

Reads **all standard layer-level metadata** from a single USD layer without composition: `defaultPrim`, `startTimeCode`, `endTimeCode`, `framesPerSecond`, `timeCodesPerSecond`, `metersPerUnit`, `upAxis`, `customLayerData`, and `expressionVariables`. Any field that has not been authored in the file is reported as `null` — this distinguishes "unauthored" from an authored zero or empty value.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to a `.usd`, `.usda`, `.usdc`, or `.usdz` file |

**Output** (JSON)

```json
{
  "path": "/path/to/file.usda",
  "format": "usda",
  "defaultPrim": "torus1",
  "startTimeCode": 1.0,
  "endTimeCode": 240.0,
  "framesPerSecond": 24.0,
  "timeCodesPerSecond": 24.0,
  "metersPerUnit": 1.0,
  "upAxis": "Y",
  "customLayerData": { "author": "chordee", "project": "my_project" },
  "expressionVariables": { "PROJECT": "demo", "SHOT": "010", "TAKE": 3 }
}
```

---

#### `usd_write_layer_metadata`

Updates layer-level metadata on a USD layer. **Only fields present in `metadata` are touched**; unmentioned fields are left as-is. A field value of `null` clears the field back to its unauthored state. Dict-valued fields (`customLayerData` / `expressionVariables`) are **fully replaced** — to merge, read first and pass the merged dict. **This tool writes files to disk.**

By default the file is saved in-place. Pass `output_path` to export to a new file instead (source is not touched, and the extension determines format — so this can also convert `.usda` ↔ `.usdc`).

**`expressionVariables` value-type restriction**: only `string`, `bool`, `int`, or homogeneous list of those. `float`, nested `dict`, and mixed lists are rejected (per OpenUSD Variable Expressions spec).

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute path to an existing USD file to edit |
| `metadata` | object | yes | Map of metadata field name to new value. `null` clears the field. |
| `output_path` | string | no | If given, export to this path (must not exist) instead of saving in-place |

Allowed `metadata` fields: `defaultPrim`, `startTimeCode`, `endTimeCode`, `framesPerSecond`, `timeCodesPerSecond`, `metersPerUnit`, `upAxis`, `customLayerData`, `expressionVariables`.

**Output** (JSON)

```json
{
  "path":        "/path/to/file.usda",
  "output_path": "/path/to/file.usda",
  "mode":        "in_place",
  "applied": [
    { "field": "framesPerSecond",     "action": "set",   "new": 30.0 },
    { "field": "endTimeCode",         "action": "clear" },
    { "field": "expressionVariables", "action": "set",   "new": { "shot": "010" } }
  ]
}
```

`mode` is `"in_place"` or `"export"`; `output_path` equals `path` in in-place mode.

---

#### `usd_create_expressions_layer`

Creates a new USD layer at `output_path` containing **only** the given `expressionVariables` metadata (no prims, no other layer metadata). Useful for pipeline config layers that are sublayered or referenced by other USDs to inject variables. **This tool writes files to disk.**

`expression_variables` values are restricted to the same set as `usd_write_layer_metadata` (`str` / `bool` / `int` / homogeneous list of those). `output_path` must not already exist; file format is determined by the extension (`.usd` / `.usda` / `.usdc`).

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `output_path` | string | yes | Absolute path to the new USD layer (must not exist) |
| `expression_variables` | object | yes | Non-empty dict of variable name to value |

**Output** (JSON)

```json
{
  "status": "ok",
  "output_path": "/abs/path/to/vars.usda",
  "expression_variables": { "PROJECT": "demo", "SHOT": "010", "TAKE": 3 }
}
```

---

#### `usd_read_hierarchy`

Reads the prim hierarchy from a **single layer only** — references, sublayers, and payloads are not resolved. Fastest option for a quick structural overview.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to a USD file |
| `max_depth` | integer | Max depth to return (0 = unlimited, default: 0) |

**Output** (JSON)

```json
{
  "path": "/path/to/file.usda",
  "composed": false,
  "prim_count": 2,
  "prims": [
    { "path": "/World",     "type": "Xform", "specifier": "def", "depth": 1 },
    { "path": "/World/geo", "type": "Mesh",  "specifier": "def", "depth": 2 }
  ]
}
```

---

#### `usd_read_hierarchy_composed`

Reads the fully composed prim hierarchy, resolving all references and sublayers. Payloads are deferred to keep memory usage low.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to a USD file |
| `max_depth` | integer | Max depth to return (0 = unlimited, default: 0) |

**Output** (JSON)

```json
{
  "path": "/path/to/assembly.usda",
  "composed": true,
  "prim_count": 45,
  "prims": [
    { "path": "/World",        "type": "Xform", "is_active": true, "depth": 1 },
    { "path": "/World/car",    "type": "Xform", "is_active": true, "depth": 2 },
    { "path": "/World/car/body","type": "Mesh",  "is_active": true, "depth": 3 }
  ]
}
```

---

#### `usd_read_composition_arcs`

Lists the direct composition arcs (sublayers, references, payloads) declared in a single USD layer, without performing composition.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to a USD file |

**Output** (JSON)

```json
{
  "path": "/path/to/file.usda",
  "sublayers": [
    "./lighting.usda"
  ],
  "references": [
    { "prim_path": "/World/car", "asset_path": "./assets/car.usda", "target_prim_path": "" }
  ],
  "payloads": [
    { "prim_path": "/World/env", "asset_path": "./env.usda", "target_prim_path": "/Environment" }
  ]
}
```

`target_prim_path` is an empty string when the arc targets the default prim.

---

#### `usd_read_cameras`

Finds all Camera prims in a fully composed USD scene and reads their lens and projection attributes. Payloads are deferred to keep memory usage low.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to a USD file |
| `frame` | number | Time code for time-sampled attributes (omit for static/default value) |

**Output** (JSON)

```json
{
  "path": "/path/to/shot.usd",
  "frame": 1001.0,
  "camera_count": 1,
  "cameras": [
    {
      "prim_path": "/World/cam_main",
      "is_active": true,
      "projection": "perspective",
      "focal_length": 50.0,
      "horizontal_aperture": 36.0,
      "vertical_aperture": 20.25,
      "horizontal_aperture_offset": 0.0,
      "vertical_aperture_offset": 0.0,
      "clipping_range": [0.1, 100000.0],
      "f_stop": 0.0,
      "focus_distance": 5.0,
      "shutter_open": -0.25,
      "shutter_close": 0.25
    }
  ]
}
```

---

#### `usd_read_prim_attributes`

Lists attributes on a USD prim with progressive disclosure. Stage is opened with payloads deferred by default — use `load_payloads: true` if the target prim lives inside a payload.

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute path to a USD file |
| `prim_path` | string | yes | USD scene path of the prim (e.g. `/Geo/mesh`) |
| `detail` | string | no | `"names"` / `"types"` (default) / `"samples"` — controls how much info is returned per attribute |
| `filter` | string | no | Return only attributes whose name starts with this prefix (e.g. `"primvars:"`) |
| `limit` | integer | no | Maximum number of attributes to return (default: `200`) |
| `frame` | number | no | Time code used to evaluate `array_size`. Omit for default time. |
| `load_payloads` | boolean | no | Load USD payloads (default: `false`) |

**`detail` levels**

| Value | Fields returned per attribute |
|-------|-------------------------------|
| `"names"` | `name` |
| `"types"` | `name`, `type_name`, `variability`, `is_array`, `array_size` |
| `"samples"` | all of the above + `has_time_samples`, `time_sample_count` |

**Output** (JSON, `detail="samples"` example)

```json
{
  "path": "/cache/geo.usd",
  "prim_path": "/torus1/mesh_0",
  "detail": "samples",
  "attribute_count": 25,
  "total_attribute_count": 25,
  "truncated": false,
  "attributes": [
    {
      "name": "points",
      "type_name": "point3f[]",
      "variability": "varying",
      "is_array": true,
      "array_size": 1234,
      "has_time_samples": true,
      "time_sample_count": 100
    },
    {
      "name": "subdivisionScheme",
      "type_name": "token",
      "variability": "uniform",
      "is_array": false,
      "array_size": null,
      "has_time_samples": false,
      "time_sample_count": 0
    }
  ]
}
```

`array_size` is `null` if the attribute has no value (e.g. authored but never set). When `frame` is omitted and the attribute is time-sampled only, `array_size` is evaluated at the first available time sample. `total_attribute_count` reflects the untruncated count after filtering.

---

#### `usd_read_attribute_value`

Reads the value of a single named attribute on a USD prim. Stage is opened with payloads deferred by default.

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute path to a USD file |
| `prim_path` | string | yes | USD scene path of the prim (e.g. `/Geo/mesh`) |
| `attribute_name` | string | yes | Attribute name (e.g. `"points"`, `"xformOp:translate"`) |
| `frame` | number | no | Time code to evaluate. Omit to use default time (falls back to first time sample if no default value exists). |
| `max_elements` | integer | no | Maximum array elements to return (default: `100`) |
| `load_payloads` | boolean | no | Load USD payloads (default: `false`) |

**Output** (JSON)

```json
{
  "path": "/cache/geo.usd",
  "prim_path": "/torus1/mesh_0",
  "attribute_name": "points",
  "type_name": "point3f[]",
  "frame": null,
  "frame_used": 1001.0,
  "array_total": 5000,
  "array_truncated": true,
  "value": [
    [0.1, 0.2, 0.3],
    [0.4, 0.5, 0.6]
  ]
}
```

`frame` reflects the requested input (`null` = default time). `frame_used` is the time actually evaluated — it differs from `frame` when the fallback to the first time sample fires. `array_total` and `array_truncated` are `null` for non-array attributes.

**Supported value types**

| USD / Gf type | JSON representation |
|---------------|---------------------|
| `bool`, `int`, `float`, `string`, `token` | native JSON scalar |
| `Gf.Vec*` | `[x, y, z, ...]` |
| `Gf.Matrix*` | nested list, row-major |
| `Gf.Quat*` | `[real, ix, iy, iz]` |
| `Gf.Range*` | `[min, max]` |
| `Sdf.AssetPath` | resolved path string |
| `Sdf.ValueBlock` | `null` |
| `Vt.Array` | list of elements (truncated to `max_elements`) |

---

#### `usd_replace_anchors`

Replaces multiple anchor asset paths (sublayers, references, payloads) in a single USD layer file in one operation. **Edits the file in-place.** Use `usd_read_composition_arcs` first to inspect existing anchor strings.

The `replacements` map is applied as-is — the tool performs a pure string substitution. Whether the new paths are absolute or relative (and relative to what) is entirely up to the caller.

**Input**

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | string | Absolute path to a USD file to modify |
| `replacements` | object | `{old_asset_path: new_asset_path}`. Keys must match the exact strings stored in the file (as returned by `usd_read_composition_arcs`) |

**Output** (JSON)

```json
{
  "path": "/path/to/shot.usda",
  "replaced": [
    { "type": "sublayer",   "old": "./lighting.usda",      "new": "./lighting_v2.usda" },
    { "type": "reference",  "prim_path": "/World/car",     "old": "./assets/car.usda",  "new": "/abs/assets/car_v2.usda" },
    { "type": "payload",    "prim_path": "/World/env",     "old": "./env.usda",          "new": "./env_v2.usda" }
  ],
  "total_replaced": 3
}
```

`type` is one of `"sublayer"`, `"reference"`, or `"payload"`. Reference and payload entries include `prim_path` indicating where in the layer the arc is declared. Anchors whose `old` key is not found in the file are silently skipped and do not appear in `replaced`.

---

#### `usd_add_sublayers`

Adds one or more sublayer asset paths to a USD layer's `subLayerPaths` list. **This tool writes files to disk.**

USD `subLayerPaths` is **strongest-first**:

- `position: "prepend"` puts new entries at the top — for input `["A","B","C"]` the final list is `["A","B","C", ...existing]`, so `A` becomes the strongest.
- `position: "append"` puts them at the bottom — final `= [...existing, "A","B","C"]`, with `A` stronger than `B` and `C` but all weaker than the existing entries.

Entries whose string is already present in `subLayerPaths` are skipped (no-op) and reported in `skipped` — including duplicates within the input list itself. Anonymous layer identifiers (strings starting with `anon:`) are rejected.

By default the file is saved in-place. Pass `output_path` to export to a new file instead (source is not touched; extension decides format).

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute path to an existing USD file to edit |
| `sublayers` | string[] | yes | Non-empty list of sublayer asset path strings to add (stored as-is) |
| `position` | string | yes | `"prepend"` (strongest first) or `"append"` (weakest last) |
| `output_path` | string | no | If given, export to this path (must not exist) instead of saving in-place |

**Output** (JSON)

```json
{
  "path":        "/path/to/main.usd",
  "output_path": "/path/to/main.usd",
  "mode":        "in_place",
  "position":    "prepend",
  "added":       ["./vars.usda", "./override.usda"],
  "skipped":     [],
  "final_sublayers": ["./vars.usda", "./override.usda", "./existing.usda"]
}
```

`final_sublayers` is the complete `subLayerPaths` list after the write (strongest-first).

---

#### `usd_remove_sublayers`

Removes one or more sublayer asset paths from a USD layer's `subLayerPaths` list. Matches the exact stored strings — same strings returned by `usd_read_composition_arcs`. **This tool writes files to disk.**

Entries not found in `subLayerPaths` are silently skipped and reported in `not_found` — no error is raised, so a single call can mix existing and possibly-existing entries without aborting.

By default the file is saved in-place. Pass `output_path` to export to a new file instead.

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | string | yes | Absolute path to an existing USD file to edit |
| `sublayers` | string[] | yes | Non-empty list of sublayer asset path strings to remove (exact match) |
| `output_path` | string | no | If given, export to this path (must not exist) instead of saving in-place |

**Output** (JSON)

```json
{
  "path":        "/path/to/main.usd",
  "output_path": "/path/to/main.usd",
  "mode":        "in_place",
  "removed":     ["./override.usda"],
  "not_found":   ["./temp.usda"],
  "final_sublayers": ["./existing.usda"]
}
```

---

#### `usd_stitch_clips`

Stitches per-frame USD cache files into a single USD Value Clips stage. Automatically generates `topology.usd` and `manifest.usd` alongside the output. **This tool writes files to disk.**

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filepath_template` | string | yes | Per-frame path template. Supports `{frame:04d}` or `$F4` format |
| `primpath` | string | yes | Target prim path on the output stage, e.g. `/Geometry` |
| `output_path` | string | yes | Absolute output path (`.usd` / `.usda` / `.usdc`) |
| `frame_range` | [int, int] | yes | Source file frame range `[start, end]` (inclusive) |
| `scene_range` | [int, int] | no | Scene timeline range (defaults to `frame_range`) |
| `loop` | boolean | no | Loop file frames to fill `scene_range` (default: `false`) |
| `clip_set` | string | no | USD Clip Set name (default: `"default"`) |
| `clip_primpath` | string | no | Prim path inside clip files (defaults to `primpath`) |
| `strict` | boolean | no | Abort if any source file is missing (default: `false`) |
| `gen_topology` | boolean | no | Auto-generate `*.topology.usd` (default: `true`) |
| `gen_manifest` | boolean | no | Auto-generate `*.manifest.usd` (default: `true`) |
| `probe_frame` | integer | no | Frame used to build topology/manifest (default: first frame) |
| `auto_detect_prim` | boolean | no | Recursively detect animated child prims (default: `true`) |
| `fps` | number | no | Output stage FPS (default: auto-detected from probe frame) |

**Output** (JSON)

```json
{
  "status": "ok",
  "output_path": "/cache/stitched.usd",
  "topology_path": "/cache/stitched.topology.usd",
  "manifest_path": "/cache/stitched.manifest.usd",
  "clip_set": "default",
  "primpath": "/Geometry",
  "fps": 24.0,
  "frame_range": [1, 50],
  "scene_range": [1, 50],
  "loop": false,
  "frame_count": 50,
  "scene_frame_count": 50,
  "missing_files": [],
  "animated_prims": ["/Geometry/mesh_0"],
  "auto_detect_prim": true,
  "probe_frame": 1
}
```

---

#### `bgeo_stitch_usd_clips`

Stitches per-frame `.bgeo.sc` cache files into a USD Value Clips stage. The clip asset paths in the output USD point directly to the original `.bgeo.sc` files — a Houdini environment (or a DCC with a bgeo USD file format plugin) is required to load geometry at render / viewport time. **This tool writes files to disk.**

Automatically reads `usdconfigpathprefix` and `usdconfigsampleframe` detail attributes embedded in the `.bgeo.sc` files to configure the primpath and frame mapping without requiring the user to specify them.

**Mesh prim path resolution**

| Probe bgeo has `path` primitive attribute? | Resulting Mesh prim(s) |
|---|---|
| yes | One Mesh per unique value (e.g. `/Geo/TEST_PRIM`) |
| no  | A single Mesh at `<primpath>/mesh_0` |

When `path` is present, every value must be an absolute USD path **and** a descendant of `primpath`. Otherwise the tool raises `BgeoClipsError` — clip samples would not reach the Mesh, so the misconfiguration is surfaced instead of producing a broken stage. `primpath` itself (whether passed explicitly or auto-detected from `usdconfigpathprefix`) must also be an absolute path, and `fps` must be finite and positive.

**Input**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filepath_template` | string | yes | Per-frame path template. Supports `{frame:04d}` or `$F4` format |
| `output_path` | string | yes | Absolute output path (`.usd` / `.usda` / `.usdc`) |
| `frame_range` | [int, int] | no | Source file frame range `[start, end]`. Auto-detected from `usdconfigsampleframe` if omitted |
| `primpath` | string | no | Prim path on the output stage. Auto-detected from `usdconfigpathprefix` if omitted |
| `scene_range` | [int, int] | no | Scene timeline range (defaults to `frame_range`) |
| `loop` | boolean | no | Loop file frames to fill `scene_range` (default: `false`) |
| `clip_set` | string | no | USD Clip Set name (default: `"default"`) |
| `strict` | boolean | no | Abort if any source file is missing (default: `false`) |
| `gen_topology` | boolean | no | Auto-generate `*.topology.usd` (default: `true`) |
| `gen_manifest` | boolean | no | Auto-generate `*.manifest.usd` (default: `true`) |
| `probe_frame` | integer | no | Frame used to build topology/manifest (default: first frame) |
| `probe_file` | string | no | Absolute path to a specific `.bgeo.sc` to use as probe, overrides `probe_frame` |
| `fps` | number | no | Output stage FPS — bgeo has no FPS metadata, so the caller specifies it (default: `24`) |

**Output** (JSON)

```json
{
  "status": "ok",
  "output_path": "/cache/sim.usd",
  "topology_path": "/cache/sim.topology.usd",
  "manifest_path": "/cache/sim.manifest.usd",
  "clip_set": "default",
  "primpath": "/Geometry",
  "fps": 24.0,
  "frame_range": [1001, 1100],
  "scene_range": [1001, 1100],
  "frame_count": 100,
  "missing_files": []
}
```

---

## Known Limitations — `bgeo_stitch_usd_clips`

Surfaced by a USD + Houdini code review on 2026-05-15. Tracked here until a future pass.

- **Multi-segment `primpath` mis-resolves clip samples.** When `primpath` has more than one segment (e.g. `/Asset/Geo`), the main USD anchors the clips dictionary on the top prim (`/Asset`) but `primPath` inside the dict points at the full path (`/Asset/Geo`). USD value-clip resolution remaps descendants relative to the anchor, so a Mesh at `/Asset/Geo/mesh_0` gets looked up as `/Asset/Geo/Geo/mesh_0` in the clip file — wrong. Single-segment `primpath` (`/Geometry`, `/Geo`) works correctly. Workaround: keep `primpath` single-segment for now.
- **`frame_range` auto-detection branch is dead-code in step 5.** `_scan_directory` builds a `frame_map`, then step 1 reassigns `frame_range`, so the later `if frame_range is None` check (used to choose between `frame_map` lookup and template resolution during loop expansion) never fires. No visible regression because `_resolve_frame` produces the same path, but the intent is broken.
- **Mesh fallback name is hard-coded `mesh_0`.** Houdini's bgeo USD file format plugin synthesizes the fallback prim name from the SOP primitive type (`mesh_0` for polys, `points_0` for points, `sphere_0` for spheres, …). Mixed or non-poly caches without a `path` primitive attribute may not align with what the plugin produces at runtime.
- **`Cd → primvars:displayColor` type mismatch.** Authored as `Float3[]`, but the runtime plugin emits `Color3f[]`. Topology / manifest typeName won't match the clip's authored typeName for this attribute; renderers usually tolerate this but `usdchecker` may warn.
- **`path` mismatch is a stitcher-policy error, not a Houdini-malformed-data error.** Houdini's SOP Import LOP accepts absolute `path` values that don't share `usdconfigpathprefix` — the prefix is only applied to relative paths. This stitcher rejects that case because the resulting clip stage would be broken, but the error message describes the bgeo as "inconsistent USD configuration", which is stronger than reality.
- **`usdconfigsampleframe` parsing depends on the BJSON reader exposing int-stored values via the `strings` field.** Future Houdini versions may store this attribute as a native int with no string fallback, in which case `int(strings[0])` would `IndexError` and `_scan_directory` would silently skip the file (bare `except: pass`). Should accept both storage forms and log skipped files.
- **Topology layer authors typeless ancestor prims.** `DefinePrim("/Geo/mesh_0", "Mesh")` creates `/Geo` as `def "Geo"` (no specifier). The main USD layer defines it as `def Xform "Geo"`, so composed typeName is correct — but `usdchecker` may flag the typeless declaration in the topology layer alone.

---

## Supported bgeo Formats

| Format | Magic | Houdini version |
|--------|-------|-----------------|
| Binary JSON (BJSON) inside scf1 container | `scf1` + `\x7fNSJ` | 18+ |
| Classic V5 binary | `Bgeo` | older |

---

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

---

## Installation

```bash
git clone https://github.com/chordee/mcp-server-houdini-lite.git
cd mcp-server-houdini-lite
uv sync
```

---

## Claude Desktop Configuration

Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "houdini-lite": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/mcp-server-houdini-lite",
        "run",
        "server.py"
      ]
    }
  }
}
```

---

## License

[MIT](LICENSE)
