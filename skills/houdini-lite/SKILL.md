---
name: houdini-lite
description: Inspect Houdini bgeo.sc geometry caches, OpenVDB volume caches, and USD scene files using MCP tools, without loading full geometry into memory. Use when the user needs to read cache metadata, VDB grid lists, attribute info, frame sequences, USD hierarchy, composition arcs, cameras, replace anchors, add / insert / remove sublayers, or stitch USD value clips.
---

# Houdini Lite Expert

MCP tools for inspecting `.bgeo.sc` geometry caches and USD scene files, plus a few write tools for stitching USD Value Clips and rewriting USD anchors. All tools avoid loading full geometry into memory. Parameter schemas come from each tool's MCP registration — this skill covers tool selection, behavioral rules, and workflows.

## Tool Picker

### bgeo (reads only the first compressed Blosc chunk — fast on multi-GB files)

- **counts only** → `bgeo_read_header`
- **attributes, geometry type, detail values, software info** → `bgeo_inspect`
- **discover sequences / frame range / total size in a directory** → `bgeo_list_sequence`

### VDB (header-only parse via Python stdlib — no pyopenvdb / no Houdini)

- **grid names, types, friendly labels, file-level metadata** → `vdb_inspect`
- **discover sequences / frame range / total size in a directory** → `vdb_list_sequence`
- **stitch per-frame .vdb sequence into a USD Volume (time-sampled filePath)** → `vdb_stitch_volume_usd`

### USD read (never loads geometry; payloads deferred by default)

- **single-layer hierarchy (no composition, fastest)** → `usd_read_hierarchy`
- **fully composed hierarchy (resolves refs + sublayers)** → `usd_read_hierarchy_composed`
- **direct sublayers/refs/payloads only** → `usd_read_composition_arcs`
- **camera lens & projection attributes** → `usd_read_cameras`
- **attribute names/types on a prim** → `usd_read_prim_attributes`
- **value of one named attribute** → `usd_read_attribute_value`
- **all standard layer metadata (time codes, fps, units, axis, customLayerData, expressionVariables)** → `usd_read_layer_metadata`

### USD write (creates or modifies files on disk)

- **stitch per-frame USD files into Value Clips** → `usd_stitch_clips`
- **stitch per-frame .bgeo.sc files into a USD Value Clips stage** → `bgeo_stitch_usd_clips`
- **stitch per-frame .vdb files into a USD Volume** → `vdb_stitch_volume_usd` (under VDB above; note this builds a UsdVol.Volume with time-sampled OpenVDBAsset.filePath, **not** USD Value Clips — clips don't apply to volumes)
- **batch-replace anchor asset paths in a single layer** → `usd_replace_anchors`
- **add sublayers to a layer (prepend = strongest / append = weakest)** → `usd_add_sublayers`
- **insert sublayers at an explicit 0-based index (between existing entries)** → `usd_insert_sublayers`
- **remove sublayers from a layer (exact string match)** → `usd_remove_sublayers`
- **edit layer metadata (set / clear / overwrite, in-place or save-as)** → `usd_write_layer_metadata`
- **create a fresh USD layer holding only Variable Expressions** → `usd_create_expressions_layer`

## Behavioral Rules

- **`usd_read_cameras`** — always compute and report the aperture ratio (`horizontal_aperture / vertical_aperture`) so the user sees the aspect (16:9 ≈ 1.778, 2.39:1, etc.) at a glance.
- **Write tools** intentionally return a concise summary only. For details (animated prims, attribute tables), follow up with the read tools.
- **`usd_replace_anchors`** does pure string replacement on `assetPath`; `primPath`, `layerOffset`, and `customData` are preserved. Keys in the `replacements` map must match the stored strings character-for-character — call `usd_read_composition_arcs` first to capture them.
- **Prims inside payloads** are not visible to `usd_read_prim_attributes` / `usd_read_attribute_value` unless `load_payloads: true` is passed.
- **`bgeo_list_sequence` and `vdb_list_sequence` auto-group** by base name. A directory with several coexisting sequences returns each one separately in `sequences[]`; files whose frame number cannot be parsed go to `unmatched[]`.
- **`usd_write_layer_metadata`** only touches fields listed in `metadata`; dict-valued fields (`customLayerData` / `expressionVariables`) are **fully replaced**, not merged. To merge, read first then write the merged dict. A field value of `null` clears it back to unauthored.
- **`expressionVariables`** value types are stricter than `customLayerData`: only `str`, `bool`, `int`, or a homogeneous list of those. No `float`, no nested dict, no mixed-type list.
- **`usd_add_sublayers` / `usd_remove_sublayers`** match `subLayerPaths` strings **exactly** — call `usd_read_composition_arcs` first to capture them. Strength = list order: `prepend ["A","B","C"]` puts `A` strongest at the top, `append` puts the input list at the bottom (weakest). Re-adding an existing string is a no-op (`skipped`); removing a string that isn't there is a no-op (`not_found`). Neither raises for these cases.
- **`usd_insert_sublayers`** is for putting entries between existing ones — `index = 0` matches `prepend`, `index = len(existing)` matches `append`, anything in between inserts there. **No negative indexing**; out-of-range values raise. Multiple entries keep input order at the insertion point.

## Workflows

### USD cache packaging — from per-frame `.usd` files

1. Confirm `filepath_template` and `primpath` with the user.
2. Call `usd_stitch_clips` with `filepath_template`, `primpath`, `output_path`, `frame_range`.
3. Report the three output files (main / topology / manifest); verify `missing_files` is empty.

### USD cache packaging — from per-frame `.bgeo.sc` files

1. Confirm the file path template with the user.
2. Call `bgeo_stitch_usd_clips` with only `filepath_template` + `output_path`; primpath and frame range are auto-detected from `usdconfigpathprefix` / `usdconfigsampleframe` detail attributes.
3. Note that the output USD references the `.bgeo.sc` files directly — Houdini (or a bgeo USD plugin) is required at load time.

### VDB sequence → USD Volume

1. Pick a probe frame and call `vdb_inspect` (or rely on the default — first frame of `frame_range`) to confirm grid names.
2. Call `vdb_stitch_volume_usd` with `filepath_template`, `output_path`, `frame_range`, `volume_name`, `parent_primpath`.
3. Use a **relative `filepath_template`** if the output USD needs to be portable; the tool writes the resolved paths into `filePath.timeSamples` as-is.
4. The output USD has `field:<grid_name>` relationships from `UsdVol.Volume` to per-grid `UsdVol.OpenVDBAsset` prims; stage `startTimeCode` / `endTimeCode` reflect the frame range.

### Anchor rewrite — asset relocation / path migration

1. `usd_read_composition_arcs` on the source layer to capture current anchor strings exactly.
2. Build a `{old: new}` map — values can be absolute or relative; the tool writes them as-is.
3. `usd_replace_anchors` with the map; check `total_replaced` matches your expectations.

## Notes

- bgeo readers expose only the first Blosc chunk; numeric attribute *values* are not present there (binary data lives in later chunks). String attributes and metadata are returned in full.
- When `array_size` or values seem missing from bgeo output, that's expected — use Houdini's CLI tools (via the `houdini-cli` skill) when you need full geometry.
