# usdrecord

Pixar's official USD command-line renderer, shipped alongside Houdini. Renders USD scenes (single frames or sequences) through any installed Hydra render delegate. No Houdini GUI required.

- Usage: `usdrecord [options] <usd_file> <output_image>`
- Recommended invocation on Windows: launch via `hython` so Houdini's libraries and search paths are loaded correctly.
- This page is a curated cheat-sheet. The canonical reference is `usdrecord --help`; no stand-alone official documentation page exists.

## Positional arguments
- `usdFilePath`: Input USD file (`.usd`, `.usda`, `.usdc`, `.usdz`).
- `outputImagePath`: Output image path.
  - Single frame: `path/to/image.png`
  - Sequence: must contain a frame placeholder, e.g. `frame.####.exr` or `frame.###.###.jpg`.

## Renderer selection
- `-r, --renderer <name>`: Hydra render delegate to use.
  - `Storm` (default): USD's built-in real-time GL renderer. Fast previews.
  - `Karma CPU`: Houdini's standard CPU renderer.
  - `Karma XPU`: Houdini's GPU/CPU hybrid renderer.
  - `Houdini GL`: Houdini's OpenGL preview renderer.

## Camera and frames
- `-cam, --camera <prim_path>`: Camera prim name or full path (default `main_cam`).
- `-f, --frames <spec>`: Frame range specification.
  - Single frame: `123`
  - Range: `101:105`
  - With stride: `101:110x2` (every second frame)

## Output settings
- `-w, --imageWidth <pixels>`: Output width (default `960`). Height is derived from the camera's aspect ratio.
- `-c, --complexity <level>`: Subdivision complexity: `low`, `medium`, `high`, `veryhigh`.
- `-color, --colorCorrectionMode <mode>`: Color correction: `disabled`, `sRGB`, `openColorIO`.

## Advanced
- `--mask <paths>`: Limit the stage to the listed prims. Useful for partial renders in large scenes.
- `--purposes <tokens>`: Display purposes to include (e.g. `proxy`, `render`, `guide`).
- `-rs, --renderSettingsPrimPath <prim_path>`: Use the `RenderSettings` prim at this path. Overrides command-line options where applicable.
- `--disableGpu`: Force CPU-only rendering. Useful for diagnosing GPU/driver issues on the XPU path.
- `--enableDomeLightVisibility`: Render the environment dome light (IBL) as a visible background.

## Examples

### Karma XPU sequence at 1080p
```cmd
"C:\Program Files\Side Effects Software\Houdini 21.0.512\bin\hython.exe" ^
  "C:\Program Files\Side Effects Software\Houdini 21.0.512\bin\usdrecord" ^
  --renderer "Karma XPU" --frames 1:100 --imageWidth 1920 ^
  --camera "/scene/main_cam" "C:/projects/shot01.usd" "C:/renders/shot01.####.exr"
```

### Storm single-frame preview
```cmd
hython usdrecord -w 1280 -c high "input.usd" "preview.png"
```

### Batch preview of every USD in a folder
```cmd
for %f in (*.usd) do hython usdrecord --renderer "Storm" --frames 1 --imageWidth 1280 "%f" "%~nf.png"
```

## Troubleshooting

- **Path not found**: ensure `C:\Program Files\Side Effects Software\Houdini 2x.x.xxx\bin` is on `PATH`, or always invoke through the full path to `hython`.
- **Pure black output**:
  - Check that `--camera` points to a valid camera prim.
  - Check that the stage actually contains lights, or that the default headlight is enabled.
  - Check `--purposes`: if the geometry is tagged `proxy` but you only render `render`, it will not appear.
- **Karma XPU crashes**: verify the GPU driver meets Houdini's requirements, or run with `--disableGpu` to bisect between renderer and hardware.
- **Windows `usdrecord.cmd` fails silently**: prefer `hython <full_path_to_usdrecord>` rather than calling `usdrecord.cmd` directly — the `.cmd` wrapper depends on the calling environment.
