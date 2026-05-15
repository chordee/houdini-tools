---
name: houdini-lite
description: Inspect Houdini bgeo.sc geometry caches and USD scene files using MCP tools, without loading full geometry into memory. Use when the user needs to read cache metadata, attribute info, frame sequences, USD hierarchy, composition arcs, cameras, replace anchors, or stitch USD value clips.
---

# Houdini Lite Expert

MCP tools for inspecting `.bgeo.sc` geometry caches and USD scene files, plus a few write tools for stitching USD Value Clips and rewriting USD anchors. All tools avoid loading full geometry into memory. Parameter schemas come from each tool's MCP registration — this skill covers tool selection, behavioral rules, and workflows.

## Tool Picker

### bgeo (reads only the first compressed Blosc chunk — fast on multi-GB files)

- **counts only** → `bgeo_read_header`
- **attributes, geometry type, detail values, software info** → `bgeo_inspect`
- **frame range / total size of a sequence** → `bgeo_list_sequence`

### USD read (never loads geometry; payloads deferred by default)

- **single-layer hierarchy (no composition, fastest)** → `usd_read_hierarchy`
- **fully composed hierarchy (resolves refs + sublayers)** → `usd_read_hierarchy_composed`
- **direct sublayers/refs/payloads only** → `usd_read_composition_arcs`
- **camera lens & projection attributes** → `usd_read_cameras`
- **attribute names/types on a prim** → `usd_read_prim_attributes`
- **value of one named attribute** → `usd_read_attribute_value`
- **customLayerData only** → `usd_read_layer_metadata`

### USD write (creates or modifies files on disk)

- **stitch per-frame USD files into Value Clips** → `usd_stitch_clips`
- **stitch per-frame .bgeo.sc files into a USD Value Clips stage** → `bgeo_stitch_usd_clips`
- **batch-replace anchor asset paths in a single layer** → `usd_replace_anchors`

## Behavioral Rules

- **`usd_read_cameras`** — always compute and report the aperture ratio (`horizontal_aperture / vertical_aperture`) so the user sees the aspect (16:9 ≈ 1.778, 2.39:1, etc.) at a glance.
- **Write tools** intentionally return a concise summary only. For details (animated prims, attribute tables), follow up with the read tools.
- **`usd_replace_anchors`** does pure string replacement on `assetPath`; `primPath`, `layerOffset`, and `customData` are preserved. Keys in the `replacements` map must match the stored strings character-for-character — call `usd_read_composition_arcs` first to capture them.
- **Prims inside payloads** are not visible to `usd_read_prim_attributes` / `usd_read_attribute_value` unless `load_payloads: true` is passed.

## Workflows

### USD cache packaging — from per-frame `.usd` files

1. Confirm `filepath_template` and `primpath` with the user.
2. Call `usd_stitch_clips` with `filepath_template`, `primpath`, `output_path`, `frame_range`.
3. Report the three output files (main / topology / manifest); verify `missing_files` is empty.

### USD cache packaging — from per-frame `.bgeo.sc` files

1. Confirm the file path template with the user.
2. Call `bgeo_stitch_usd_clips` with only `filepath_template` + `output_path`; primpath and frame range are auto-detected from `usdconfigpathprefix` / `usdconfigsampleframe` detail attributes.
3. Note that the output USD references the `.bgeo.sc` files directly — Houdini (or a bgeo USD plugin) is required at load time.

### Anchor rewrite — asset relocation / path migration

1. `usd_read_composition_arcs` on the source layer to capture current anchor strings exactly.
2. Build a `{old: new}` map — values can be absolute or relative; the tool writes them as-is.
3. `usd_replace_anchors` with the map; check `total_replaced` matches your expectations.

## Notes

- bgeo readers expose only the first Blosc chunk; numeric attribute *values* are not present there (binary data lives in later chunks). String attributes and metadata are returned in full.
- When `array_size` or values seem missing from bgeo output, that's expected — use Houdini's CLI tools (via the `houdini-cli` skill) when you need full geometry.
