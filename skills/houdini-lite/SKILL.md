---
name: houdini-lite
description: Inspect Houdini bgeo.sc geometry caches and USD scene files using MCP tools, without loading full geometry into memory. Use when the user needs to read cache metadata, attribute info, frame sequences, USD hierarchy, composition arcs, cameras, or stitch USD value clips.
---

# Houdini Lite Expert

You have access to tools for inspecting Houdini `.bgeo.sc` geometry caches
and USD scene files — all without loading full geometry into memory.

---

## bgeo Tools

### `bgeo_read_header`

Reads point and primitive counts from a single `.bgeo.sc` file.

**Use when**: The user wants only the point/primitive count and nothing else.

**Input**: `path` — absolute path to a `.bgeo.sc` file.

**Output fields**:

| Field     | Meaning               |
|-----------|-----------------------|
| `npoints` | Total point count     |
| `nprims`  | Total primitive count |

---

### `bgeo_inspect`

Reads rich metadata from a single `.bgeo.sc` file without loading geometry.
Reads only the first Blosc chunk — fast even for multi-GB files.

**Use when**: The user wants attribute lists, geometry type, detail attribute values,
software/date info, or any metadata beyond bare counts.

**Input**: `path` — absolute path to a `.bgeo.sc` file.

**Output fields**:

| Field | Meaning |
|-------|---------|
| `fileversion` | Houdini version that wrote the file |
| `npoints` / `nprims` / `nvertices` | Geometry counts |
| `info.software` | Full Houdini version string |
| `info.date` | Cook timestamp |
| `info.timetocook` | Cook time in seconds |
| `info.primcount_summary` | Human-readable geometry type, e.g. `"4 VDBs"`, `"361 Polygons"` |
| `info.attribute_summary` | Full attribute listing string from Houdini |
| `prim_types` | List of geometry primitive type names, e.g. `["VDB"]`, `["PolySoup"]` |
| `prim_paths` | USD prim paths from `primitiveattributes.path` (USD workflow files only) |
| `attributes.point` / `.prim` / `.vertex` / `.detail` | Attribute definitions per scope |

Each attribute entry has `name`, `size`, `storage`, and `values`.
`values` is a `list[str]` for string-type attributes, or `null` for numeric types
(binary data is not in the first chunk).
If `size` and `storage` are both `null`, the entry was recovered from
`info.attribute_summary` as a fallback (occurs in very large files where binary
point data fills the first chunk before all attribute definitions are written).

---

### `bgeo_list_sequence`

Scans a directory for numbered `.bgeo.sc` files and returns frame information
without reading any geometry.

**Use when**: The user wants to know how many frames a cache sequence has, what
the frame range is, or the total disk size.

**Input**:

- `directory` — directory containing the cache files
- `pattern` (optional) — glob pattern, e.g. `"pyro_cache.*.bgeo.sc"` (default `"*.bgeo.sc"`)

**Output fields**:

| Field              | Meaning                                            |
|--------------------|----------------------------------------------------|
| `frame_count`      | Number of files found                              |
| `frame_range`      | `{first, last}` frame numbers                      |
| `total_size_bytes` | Combined size of all files                         |
| `frames`           | Per-frame list: `frame`, `filename`, `size_bytes`  |

---

## USD Tools

### `usd_read_layer_metadata`

Reads `customLayerData` from a single USD layer without composition.

**Use when**: The user wants to inspect metadata embedded in a USD file.

**Input**: `path` — absolute path to a USD file.

---

### `usd_read_hierarchy`

Reads the prim hierarchy from a **single layer only**.

**Use when**: The user wants a fast structural overview of one file.

---

### `usd_read_hierarchy_composed`

Reads the **fully composed** hierarchy — resolves all references and sublayers.

---

### `usd_read_composition_arcs`

Lists the direct composition arcs declared in a single layer.

---

### `usd_read_cameras`

Finds all Camera prims in a fully composed USD scene and reads their
lens and projection attributes.

**Use when**: The user wants to inspect camera settings, focal length,
aperture, clipping planes, or projection type. Works across referenced
files.

**Inputs**:

- `path` — absolute path to a USD file
- `frame` (optional) — time code for time-sampled attributes;
  omit for the static/default value

**Output fields per camera**:

<!-- markdownlint-disable MD013 -->
| Field                                           | Meaning                                |
|-------------------------------------------------|----------------------------------------|
| `prim_path`                                     | USD scene path of the Camera prim      |
| `is_active`                                     | Whether the prim is active             |
| `projection`                                    | `"perspective"` or `"orthographic"`    |
| `focal_length`                                  | Focal length in tenths of a scene unit |
| `horizontal_aperture` / `vertical_aperture`     | Aperture in tenths of a scene unit     |
| `clipping_range`                                | `[near, far]` clipping distances       |
| `f_stop`                                        | Lens aperture (0 = disabled)           |
| `focus_distance`                                | Focus plane distance                   |
| `shutter_open` / `shutter_close`                | Motion blur shutter times              |
<!-- markdownlint-enable MD013 -->

**Important:** When reporting camera data, always compute and include
the **aperture ratio** (`horizontal_aperture / vertical_aperture`) so
the user can immediately see the aspect ratio
(e.g. 16:9 ≈ 1.778, 2.39:1, etc.).

---

### `usd_stitch_clips`

Stitches per-frame USD cache files into a single USD Value Clips stage.
**This is a write operation** — it creates files on disk.

**Use when**: The user wants to package a simulation or geometry cache
(split across many per-frame `.usd` files) into a single USD file with
Value Clips, so it can be referenced into a scene like a normal asset.

**Required inputs**:

- `filepath_template` — per-frame path template, e.g. `/cache/sim.{frame:04d}.usd` or `/cache/sim.$F4.usd`
- `primpath` — prim path in the output stage, e.g. `/Geometry`
- `output_path` — absolute output path (`.usd` / `.usda` / `.usdc`)
- `frame_range` — `[start, end]` frame range of the source files (inclusive)

**Optional inputs** (use defaults unless the user specifies otherwise):

| Parameter        | Default              | Meaning |
|------------------|----------------------|---------|
| `scene_range`    | same as `frame_range`| Scene timeline range; use with `loop` to retime |
| `loop`           | `false`              | Repeat source frames to fill `scene_range` |
| `clip_set`       | `"default"`          | USD Clip Set name |
| `clip_primpath`  | same as `primpath`   | Prim path inside each clip file |
| `strict`         | `false`              | Abort if any source file is missing |
| `gen_topology`   | `true`               | Auto-generate `*.topology.usd` |
| `gen_manifest`   | `true`               | Auto-generate `*.manifest.usd` |
| `probe_frame`    | first frame          | Frame used to build topology/manifest |
| `auto_detect_prim` | `true`             | Recursively find animated child prims |
| `fps`            | auto from probe frame| Output stage FPS |

**Output fields**:

| Field                | Meaning |
|----------------------|---------|
| `status`             | `"ok"` on success |
| `output_path`        | Written main USD file |
| `topology_path`      | Written topology file (`null` if skipped) |
| `manifest_path`      | Written manifest file (`null` if skipped) |
| `frame_count`        | Number of source frames used |
| `scene_frame_count`  | Number of scene timeline frames |
| `fps`                | FPS set on the output stage |
| `missing_files`      | Files that were absent (empty list = all present) |
| `animated_prims`     | Prim paths detected as animated |

---

### `bgeo_stitch_usd_clips`

Stitches per-frame `.bgeo.sc` cache files into a USD Value Clips stage.
**This is a write operation** — it creates files on disk.

The tool reads `usdconfigpathprefix` and `usdconfigsampleframe` detail attributes
embedded in the `.bgeo.sc` files to auto-configure the output USD structure.
The clip asset paths in the output USD point directly to the `.bgeo.sc` files —
a Houdini environment (or bgeo USD plugin) is required to load the geometry.

**Use when**: The user has a Houdini simulation cache as per-frame `.bgeo.sc` files
and wants to package them into a USD Value Clips stage for use in a USD pipeline.

**Required inputs**:

- `filepath_template` — per-frame path template, e.g. `/cache/sim.{frame:04d}.bgeo.sc`
- `output_path` — absolute output path

**Optional inputs** (most are auto-detected from bgeo metadata):

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `frame_range` | auto from `usdconfigsampleframe` | Source file frame range `[start, end]` |
| `primpath` | auto from `usdconfigpathprefix` | Prim path on the output stage |
| `probe_frame` | first frame | Frame number to use for topology/manifest generation |
| `probe_file` | — | Absolute path to a specific `.bgeo.sc` to use as probe (overrides `probe_frame`) |
| `scene_range` | same as `frame_range` | Scene timeline range for looping |
| `loop` | `false` | Loop frames to fill `scene_range` |
| `gen_topology` | `true` | Auto-generate `*.topology.usd` from bgeo prim paths |
| `gen_manifest` | `true` | Auto-generate `*.manifest.usd` from bgeo attribute metadata |
| `strict` | `false` | Abort if any source file is missing |

---

## Typical Workflows

### bgeo cache inspection

1. **Counts only** → `bgeo_read_header` (fastest).
2. **Attributes, geometry type, detail values** → `bgeo_inspect`.
3. **Sequence** → `bgeo_list_sequence` for frame range and total size.

### USD scene inspection

1. **Quick overview** → `usd_read_hierarchy`.
2. **Full scene** → `usd_read_hierarchy_composed`.
3. **Check dependencies** → `usd_read_composition_arcs`.
4. **Find cameras** → `usd_read_cameras`.

### USD cache packaging (from USD per-frame files)

1. Confirm the per-frame file path pattern and primpath with the user.
2. Call `usd_stitch_clips` with `filepath_template`, `primpath`, `output_path`, `frame_range`.
3. Report the three output files and confirm `missing_files` is empty.

### USD cache packaging (from bgeo.sc per-frame caches)

1. Confirm the `.bgeo.sc` file path template with the user.
2. Call `bgeo_stitch_usd_clips` with `filepath_template` and `output_path` — primpath and
   frame range are auto-detected from `usdconfigpathprefix` / `usdconfigsampleframe` attributes.
3. Inform the user that the output USD references the original `.bgeo.sc` files and requires
   a Houdini environment (or bgeo USD plugin) to load geometry.

---

## Important Notes

- Most tools are **read-only**. Write tools: `usd_stitch_clips`, `bgeo_stitch_usd_clips`.
- bgeo tools read only the first compressed Blosc chunk (fast even for multi-GB files).
- USD read tools never load geometry or payload data.
- `bgeo_read_header` and `bgeo_inspect` support `.bgeo.sc` only.
- Write tools return a **concise summary dict only**. Large intermediate data (prim paths,
  attribute tables, animated prim lists) are intentionally omitted to avoid bloating the
  model context window. Use the read-only inspection tools for follow-up detail queries.
