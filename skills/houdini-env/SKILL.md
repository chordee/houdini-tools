---
name: houdini-env
description: Houdini environment variables and package configuration. Use when the user needs to set up, debug, or understand Houdini environment variables, houdini.env files, or JSON package plugins.
---

# Houdini Environment & Packages

Two mechanisms control Houdini's runtime configuration:

- **`houdini.env`** — plain key=value file in the user preference directory. Loaded automatically at startup.
- **JSON Packages** — `.json` files that configure paths and env vars without editing `houdini.env`. Scanned from several well-known locations.

Prefer packages for plugins; reserve `houdini.env` for user-level overrides.

## Quick Recipes

**Edit `houdini.env`** (path: `$HOME/houdini<MAJOR.MINOR>/houdini.env`):

```text
HOUDINI_PATH = /my/custom/path;&
HOUDINI_MAXTHREADS = 4
```

`&` keeps the default value, so the line above *prepends* `/my/custom/path` to `HOUDINI_PATH`. Use `;` as separator on all platforms inside this file.

**Minimal package** (drop in `$HOUDINI_USER_PREF_DIR/packages/my_plugin.json`):

```json
{
  "hpath": "/path/to/my/plugin"
}
```

Prepends `/path/to/my/plugin` to `HOUDINI_PATH`. The folder should contain standard subdirs (`otls`, `dso`, `python_panels`, ...).

**Package with env vars and OS gating:**

```json
{
  "enable": { "houdini_os": "windows" },
  "env": [
    { "MY_TOOL_ROOT": "${HOUDINI_PACKAGE_PATH}" },
    { "MY_TOOL_BIN":  "${MY_TOOL_ROOT}/bin" }
  ],
  "hpath": "${MY_TOOL_ROOT}"
}
```

`$HOUDINI_PACKAGE_PATH` is automatically set to the directory containing the package file.

## Debugging

- Set `HOUDINI_PACKAGE_VERBOSE=1` **in the shell before launching Houdini** (not inside a package) to see which packages load.
- `HOUDINI_DSO_ERROR` controls plugin loading verbosity.
- `HOUDINI_NO_ENV_FILE=1` skips `houdini.env` entirely; `HOUDINI_NO_ENV_FILE_OVERRIDES=1` loads it but lets the parent environment win.

## References

- [Environment variables full reference](references/env-vars.md) — core path/runtime tables, special tokens, preference directory, `houdini.env` syntax.
- [Packages full reference](references/packages.md) — scan order, all supported keys, expression grammar, variable expansion, best practices.
- Official docs: [env vars](https://www.sidefx.com/docs/houdini/ref/env.html) · [packages](https://www.sidefx.com/docs/houdini/ref/plugins.html)
