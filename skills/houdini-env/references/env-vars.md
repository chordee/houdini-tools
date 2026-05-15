# Houdini Environment Variables

## Core Path Variables

| Variable | Purpose |
|----------|---------|
| `HOUDINI_PATH` | Directories for configuration files, plugins, and scripts |
| `HOUDINI_DSO_PATH` | Custom plugin / DSO / DLL search path |
| `HOUDINI_OTLSCAN_PATH` | OTL / HDA directories (defaults from `HOUDINI_OTL_PATH` + `/otls`) |
| `HOUDINI_OPLIBRARIES_PATH` | `OPlibraries` file locations for the Operator Type Manager |
| `HOUDINI_SCRIPT_PATH` | Python / HScript search path |
| `HOUDINI_TEXTURE_PATH` | Texture search path |
| `HOUDINI_VEX_DSO_PATH` | VEX plugin search path |
| `HOUDINI_USD_DSO_PATH` | USD plugin search path |
| `MANTRA_DSO_PATH` | Mantra renderer DSO path |
| `KARMA_DSO_PATH` | Karma renderer DSO path |

## Special Tokens

- `__HVER__` — expands to `MAJOR.MINOR` at runtime (e.g. `20.5`).
- `$HFS` — Houdini installation root.
- `$HH` — `$HFS/houdini`; support scripts and internal files.
- `$HOME` / `$HSITE` / `$JOB` / `$HIP` — standard Houdini variables available in paths.

## Preference Directory

- `HOUDINI_USER_PREF_DIR` — user preferences folder. **Must contain `__HVER__`** so Houdini can substitute the version string.
  - Windows/Linux default: `$HOME/houdini__HVER__`
  - macOS fallback: `$HOME/Library/Preferences/houdini/__HVER__`
- The startup file `$HOUDINI_USER_PREF_DIR/houdini.env` is loaded automatically unless `HOUDINI_NO_ENV_FILE=1`.
- `HOUDINI_NO_ENV_FILE_OVERRIDES=1` loads `houdini.env` but prevents it from overriding variables already defined in the parent environment.

## Notable Runtime Variables

| Variable | Effect |
|----------|--------|
| `HOUDINI_MAXTHREADS` | Thread cap (`0` = all cores, `1` = single-thread, negative = total cores + N, e.g. `-1` = all but one core) |
| `HOUDINI_AUTHOR` | Overrides username/machine stamped into saved `.hip`/HDA files |
| `HOUDINI_TEMP_DIR` | Redirects temporary file generation |
| `HOUDINI_UNDO_DIR` | Redirects undo storage |
| `HOUDINI_UISCALE` | UI DPI scaling; default `100` |
| `HOUDINI_OGL_MAX_GL_VERSION` | Constrains OpenGL feature level |
| `HOUDINI_SCRIPT_LICENSE` | License checked out when using `hou` outside `hython`/`hbatch` (e.g. `"hbatch"`, `"hescape"`, `"pdg"`) |
| `HOUDINI_DSO_ERROR` | Verbosity level for dynamic-linking diagnostics |
| `HOUDINI_DISABLE_MMX` / `SSE` / `AVX` | Disable specific CPU instruction sets |

## `houdini.env` Format

Plain key-value pairs, one per line:

```text
HOUDINI_PATH = /my/custom/path;&
HOUDINI_MAXTHREADS = 4
```

- `&` expands to the default value for that variable (so `/my/path;&` prepends while keeping defaults).
- Within `houdini.env`, multiple paths are separated by `;` on all platforms.

## Reference

- Houdini Environment Variables: https://www.sidefx.com/docs/houdini/ref/env.html
