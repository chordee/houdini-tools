# Houdini Packages (JSON Plugins)

Packages are `.json` files that configure the Houdini Path and environment variables **without editing `houdini.env`**. They must be valid JSON with a `.json` extension.

## Package Scan Locations (in order)

1. `$HOUDINI_USER_PREF_DIR/packages`
2. `$HSITE/houdini<major>.<minor>/packages`
3. `$HOUDINI_PACKAGE_DIR` (files go **directly** here; no `packages` subfolder)
4. `$HFS/packages`

`$HSITE` and `$HOUDINI_PACKAGE_DIR` must be set **before** Houdini starts.

## Processing Order

- Directories are scanned in the order above.
- Within a directory, files are processed alphabetically by default.
- Override with `"process_order": <integer>` — Houdini sorts packages in ascending order before processing.

## Supported Keys

| Key | Purpose |
|-----|---------|
| `hpath` | Modify `$HOUDINI_PATH`. String, array, or object with `"value"` and `"method"` (`prepend`, `append`, `replace`). Legacy `path` key is deprecated. |
| `env` | Array of environment variable definitions. Entries are objects mapping names to values, or use `"var"`, `"value"`, `"method"`. |
| `enable` | Boolean or expression string/map to activate/skip the package. |
| `load_package_once` | Boolean or expression; first file with this name in the search path wins, later duplicates ignored. |
| `package_path` | String or array of extra folders to scan recursively for additional packages. |
| `recommends` | Optional dependencies; Houdini warns if missing. |
| `requires` | Mandatory dependencies; Houdini errors if missing. |
| `preload_libraries` | Dynamic libraries to load before other binary plugins. |
| `show` | Controls visibility in the Package Browser. |

## Writing a Package

**Prepend a directory to `HOUDINI_PATH`:**

```json
{
  "hpath": "/path/to/my/plugin"
}
```

**Append instead of prepend:**

```json
{
  "hpath": {
    "value": "/path/to/my/plugin",
    "method": "append"
  }
}
```

**Set custom environment variables:**

```json
{
  "env": [
    { "MY_TOOL_ROOT": "/tools/my_tool" },
    { "MY_TOOL_BIN": "${MY_TOOL_ROOT}/bin" }
  ]
}
```

**Conditional by OS:**

```json
{
  "enable": {
    "houdini_os": "windows"
  },
  "hpath": "C:/my_windows_only_plugin"
}
```

## Variable Expansion

- Path variables prepend by default inside `env`.
- Use `"method": "append"` or `"method": "replace"` to change behavior.
- Variables defined earlier in the same `env` array are visible to later entries.
- Variables from one package are visible to other packages.
- `$HOUDINI_PACKAGE_PATH` is set to the directory containing the current package file; use it to build paths relative to that directory.
- Concatenation uses HScript-style curly braces: `"${BOB}/suffix"`.
- Defaults are supported: `"${VAR-DEFAULT}"`.

## Expression Grammar

Conditional values support:

- `==`, `!=`, `<`, `>`, `<=`, `>=`
- `and`, `or`, parentheses
- Identifiers: `houdini_version`, `houdini_os` (`'windows'`/`'linux'`/`'macos'`), `houdini_python`, `houdini_platform_build`
- Environment variables with `$` prefix

All comparisons are string-based.

## Best Practices

- Do **not** set `LD_LIBRARY_PATH` or `DYLD_LIBRARY_PATH` in a package — the dynamic linker resolves library paths at process startup, before package files are read, so these variables have no effect when set here.
- Plugin folders should use standard subdirectories (`otls`, `dso`, `python_panels`, etc.), and `HOUDINI_PATH` should point to the **parent** folder.
- If you rely on `OPlibraries` for HDAs, place the file in the plugin folder and ensure the folder sits on `HOUDINI_PATH` (or `HOUDINI_OPLIBRARIES_PATH`).
- Set `HOUDINI_PACKAGE_VERBOSE=1` in the terminal **before** launching Houdini to debug package loading. Do **not** set it inside a package file.
- Launching a subprocess from Houdini copies the parent's package environment; set `HOUDINI_PACKAGE_SKIP=1` beforehand to avoid duplication.
- To handle differing `$HOUDINI_USER_PREF_DIR` values across launchers (e.g. `hython` vs. desktop), place a small package in both preference folders that points via `package_path` to a shared external directory.

## Reference

- Houdini Packages: https://www.sidefx.com/docs/houdini/ref/plugins.html
