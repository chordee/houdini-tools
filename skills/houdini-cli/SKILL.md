---
name: houdini-cli
description: Interact with Houdini command-line tools (ginfo, gconvert, hrender, hython, etc.). Use when user needs to analyze geometry, convert files, render scenes, or run Houdini Python scripts.
---

# Houdini CLI

This skill provides the ability to interact with Houdini's command-line tools.

## Environment Setup

Before running any Houdini tool, you must first locate the Houdini installation path and its `bin` directory.

1. **Locate Houdini**: Use the `houdini-locator` skill to obtain the install path (HFS) and bin directory (HBIN).

2. **Run a tool**: Prefix the tool name with the HBIN path, e.g. in PowerShell use `& "<HBIN>\ginfo.exe" <args>`.

## Common Workflows

### Inspect Geometry
Use `ginfo` to inspect geometry files such as `.bgeo`, `.bgeo.sc`, and `.obj`.
- Example: `& "<HBIN>\ginfo.exe" -v my_geo.bgeo.sc`

### Convert Geometry Formats
Use `gconvert` to convert files between different formats.
- Example: `& "<HBIN>\gconvert.exe" input.bgeo.sc output.obj`

### Render HIP Files
Use `hrender` for batch rendering.
- Example: `& "<HBIN>\hrender.exe" -d /out/mantra1 -f 1 -e 10 myscene.hip`

### USD Render with husk
Use `husk` to render a `.usd`/`.usda`/`.usdc` stage via a Hydra delegate (Karma by default).
- Example: `& "<HBIN>\husk.exe" --make-output-path -f 1 -n 10 -o /render/out.$F4.exr scene.usd` (`-n 10` = frame count, renders frames 1–10)
- Pick a delegate with `-R` (e.g. `-R HdArnoldRendererPlugin`) and a specific `RenderSettings` with `--settings /Render/rendersettings`.
- See [husk.md](references/husk.md) for the full flag list (frame range, output overrides, purpose/complexity, verbosity, threading, etc.).

### USD Preview Render with usdrecord
Use `usdrecord` for quick USD previews via Pixar's reference USD renderer (Storm by default; Karma CPU/XPU and Houdini GL also available). Invoke through `hython` so Houdini's libraries load correctly.
- Example: `& "<HBIN>\hython.exe" "<HBIN>\usdrecord" --renderer Storm -w 1280 scene.usd preview.png`
- Sequences require a frame placeholder in the output path (e.g. `out.####.exr`) and `--frames 1:100`.
- See [usdrecord.md](references/usdrecord.md) for the full flag list and troubleshooting.

### Run Python Scripts
Use `hython` to run scripts with access to the `hou` module.
- Example: `& "<HBIN>\hython.exe" process_geo.py`

## References

- Tool index: [tools.md](references/tools.md)
- Per-tool deep dives: [husk.md](references/husk.md) · [usdrecord.md](references/usdrecord.md)
- Official documentation: https://www.sidefx.com/docs/houdini/ref/utils/index.html
