# husk

Standalone command-line renderer for USD files via Hydra. Default delegate is Karma; other delegates (Arnold, RenderMan, V-Ray, Redshift, …) are loaded with `-R <token>`.

- Usage: `husk [options] <usd_file> [-o <image_file>]`
- Official docs: https://www.sidefx.com/docs/houdini/ref/utils/husk.html

## Information / stage inspection
- `--help`, `--version`: Print usage / renderer version and exit.
- `--list-renderers`: List all available Hydra render delegates.
- `--list-cameras`: List Camera prims in the input stage.
- `--list-settings`: List `RenderSettings` prims in the input stage.
- `--properties` / `--property-definition`: Print Karma render property names / full definitions.
- `--property-definition-file <file>`: Save full property definitions to file (use `-` for stdout).

## Frame / sequence control
- `-f, --frame <n>`: Start frame number (default `1`).
- `-n, --frame-count <n>`: Number of frames to render including the start frame (default `1`).
- `-i, --frame-inc <n>`: Frame increment (default `1`).
- `--frame-list <frames>`: Space-separated explicit frame list. Overrides `-f` / `-n` / `-i`. Negative frames are not supported (leading hyphen is parsed as a flag).
- `--fps <n>`: Override the stage FPS; forwarded to the delegate as the `houdini:fps` render setting.

## Renderer / RenderSettings overrides
These override values in the USD file.

- `-R, --renderer <token>`: Hydra delegate to render with (default Karma; token names may vary by version — use `husk --list-renderers` to confirm). Examples: `BRAY_HdKarma`, `HdArnoldRendererPlugin`, `HdPrmanLoaderRendererPlugin`.
- `--delegate-options <string>`: Delegate-specific options string.
- `-s, --settings <prim_path>`: `RenderSettings` prim to render with.
- `-c, --camera <prim_path>`: Camera prim to render from.
- `--mask <paths>`: Limit stage population to the listed prims, their descendants and ancestors. Comma- or space-separated.
- `--purpose <tokens>`: Comma-separated purpose list (default `geometry,render`; also `proxy`, `guide`).
- `--complexity <level>`: Geometry complexity: `low`, `medium`, `high`, `veryhigh`, or a number `0`–`8`.
- `--disable-scene-lights` / `--disable-scene-materials`: Strip all scene lights / materials (applies to every delegate).
- `--disable-motionblur`: Force shutter close = shutter open; effectively disables motion blur.
- `--headlight <style>`: Headlight mode when the stage has no lights (default from `$HOUDINI_HUSK_DEFAULT_HEADLIGHT`).

## Output overrides
- `-o, --output <file_path>`: Output image path. Supports `$F`, `$F<N>`, `$FF`, `$N`, `<F>` / `<F4>`, and `%d` / `%04d`. Comma-separated list maps onto multiple render products.
- `--make-output-path`: Create missing parent directories of the output image.
- `-r, --res <w> <h>`: Override rendered resolution (e.g. `-r 1280 720`).
- `-S, --res-scale <percent>`: Scale the output (e.g. `25` = quarter-res, `200` = 2×).
- `--pixel-aspect <float>`: Pixel aspect ratio (default `1`).

## Resolver / variants
- `--resolver-context <file>` / `--resolver-context-string <arg>`: Initialize the asset resolver context (use `url=string` to scope to a URL prefix).
- `--variant-fallback <set=v1,v2>`: Default variant selection for prims that declare a variant set but no selection.

## Image processing & products
- `--autocrop <pattern>`: Trim the EXR data window to the bounding box of non-zero pixels in the listed AOVs (e.g. `C,A`, or `"*"` for all).
- `--ocio <0|1>`: Use OCIO for image color transforms (otherwise fall back to Houdini's intrinsic format assumptions).
- `--exrmode <-1|0|1>`: EXR driver: `-1` use `$HOUDINI_OIIO_EXR`, `0` classic, `1` improved.
- `--disable-delegate-products`: Drop non-raster delegate render products (deep, checkpoint, photon map, …); keep raster output only.
- `--disable-dummy-raster-product`: Don't synthesize a dummy raster product when no raster products are defined.
- `--slap-comp <graph[?option=value...]>`: Run an Apex COP network on the rendered image. Can be specified multiple times; operations run in sequence.

## Tile rendering
- `--tile-count <xcount> <ycount>`: Render a single image as an X×Y tile grid (used with `--tile-index`).
- `--tile-index <index>`: 0-based tile index for this husk invocation.
- `--tile-suffix <suffix>`: Suffix appended to the output filename, expanded using the tile index. Same expansion rules as `-o`; `F` = tile index, `N` = 1-based tile index.

## Snapshots & time limits
- `--snapshot <sec>`: Save a partial image every `<sec>` seconds (default `-1`, off). On Linux/macOS, `kill -USR1 <pid>` also forces a snapshot.
- `--snapshot-path <path>`: Override snapshot output path.
- `--snapshot-suffix <suffix>`: Filename suffix for snapshots (default `_part`; empty = overwrite the final image).
- `--snapshot-save-mode <off|number>`: `off` deletes the partial when the render finishes; `number` keeps snapshots as a numbered sequence.
- `--timelimit <sec>`: Cancel the render after `<sec>` seconds (default `-1`, no limit).
- `--timelimit-nosave-partial`: When the time limit fires, don't save the partial image.

## mplay viewer
- `--no-mplay`: Disable any mplay output (use this for farm/headless renders).
- `--mplay-monitor <aovs>`: Start an mplay monitor; `<aovs>` is a comma-separated AOV list or `-` for all. Closing the monitor terminates the render.
- `--mplay-session <label>`: Send mplay output to a labelled session.
- `--mplay-scale <10-100>`: Point-filtered scale for mplay (default `100`).
- `--mplay-update <sec>`: Seconds between mplay image updates.

## Scripting hooks
`stage`, `husk_command`, and `hou.frame()` are available in every script.

- `--prerender-script <py>`: Runs once after the stage loads but **before** husk partitions `RenderSettings` into per-product tasks — this is the only hook that can still change cameras or split products.
- `--preframe-script <py>`: Runs before each frame. The `settings` dict is also available.
- `--postframe-script <py>`: Runs after each frame.
- `--postrender-script <py>`: Runs once after all frames are rendered.

## Karma-specific
Only with the default Karma delegate.

- `--engine <xpu|cpu>`: Karma rendering engine.
- `-p, --pixel-samples <n>`: Samples per pixel (default `128`). Overrides `RenderSettings`.
- `--bucket-size <pixels>`: Render bucket size (default `128`). Overrides `RenderSettings`.
- `--bucket-order <middle|top|bottom|left|right>`: First-rendered region.
- `--convergence-mode <pathtraced|variance>`: Default convergence mode when not set on the `RenderSettings`.
- `--ao-samples <n>` / `--ao-distance <n>`: Headlight ambient-occlusion samples / cutoff distance.
- `--lock-random <seed>`: Use a fixed random seed instead of the frame number.
- `--dicingcamera <prim_path>`: Use this camera for dicing instead of the render camera.
- `--autoheadlight`: Add a headlight when the stage has no lights.
- `--disable-lighting`: Skip all lighting (deprecated; use `--disable-scene-lights`).

## Threading & process control
- `-j, --threads <n>`: Thread count. `0` = all processors; `-1` = all but one.
- `--restart-delegate <n>`: Restart the render delegate every `n` frames. Default `0` **never restarts** and uses USD deltas between frames. Positive values force a full scene rebuild and have significant performance cost.
- `--fast-exit <0|1>`: Setting to `0` forces a full tear-down of the USD scene and Hydra interface at process exit.

## Logging & I/O redirection
- `-V, --verbose <level>`: Log verbosity (default `2`). The level string accepts digits and letter modifiers, e.g. `-V 5ae`:
  - `0`–`9`: verbosity (`8`+ may impact performance).
  - `p` / `P`: enable VEX profiling (`P` also runs NaN checks; severe perf hit).
  - `a` / `A`: enable / disable Alfred-style progress.
  - `e` / `E`: enable / disable elapsed-time prefix on messages.
  - `t` / `T`: enable / disable timestamps on messages.
- `--stdout <file>` / `--stderr <file>`: Redirect stdout / stderr (and Houdini log output) to a file. On Windows, `--stdout` also accepts `consolewait` / `consolenowait`.
- `--append-stdout <file>` / `--append-stderr <file>`: As above but append rather than overwrite.

## Licensing
New licensing system.

- `--apprentice` / `--indie` / `--core`: Force a specific license tier.
- `--check-licenses <list>` / `--skip-licenses <list>`: Comma-separated lists of internal license names to enable / disable during the license check.
- `--list-license-checks`: Show available license checks.

## Examples

Single-frame Karma render with explicit output:
```
husk --make-output-path -f 1001 -n 1 -o /render/shot010.$F4.exr /stage/shot010.usd
```

Quarter-resolution preview at low complexity, no mplay (farm-friendly):
```
husk -R BRAY_HdKarma -S 25 --complexity low --no-mplay \
     --make-output-path -f 1001 -n 24 -o /render/preview.$F4.exr /stage/shot010.usd
```

24-frame Arnold sequence using a specific `RenderSettings` and verbose log to file:
```
husk -R HdArnoldRendererPlugin -s /Render/rendersettings \
     -f 1001 -n 24 --purpose geometry,render --complexity high \
     --make-output-path -o /render/beauty.$F4.exr \
     -V 5ae --stderr /render/log.txt /stage/shot010.usd
```

Inspect a stage before rendering:
```
husk --list-renderers /stage/shot010.usd
husk --list-cameras   /stage/shot010.usd
husk --list-settings  /stage/shot010.usd
```
