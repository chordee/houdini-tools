# houdini-tools

Houdini toolkit plugin for Claude Code, Codex, and Gemini CLI. Bundles four skills plus a lightweight MCP server for inspecting `.bgeo.sc` caches and USD scene files without loading geometry.

## Contents

### Skills

| Skill | Purpose |
| --- | --- |
| `houdini-cli` | Drive Houdini's command-line tools (`ginfo`, `gconvert`, `hrender`, `husk`, `usdrecord`, `hython`, …) for geometry analysis, format conversion, and batch rendering. Detailed per-tool references live under `skills/houdini-cli/references/`. |
| `houdini-env` | Houdini environment variables, `houdini.env` syntax, and JSON package configuration. Covers `HOUDINI_PATH`, `HOUDINI_DSO_PATH`, `HOUDINI_USER_PREF_DIR`, package scan order, expression grammar, and best practices. |
| `houdini-locator` | Detect every Houdini installation on Windows or Linux and return the full path to `hython` / `houdinifx` for direct execution. |
| `houdini-lite` | Companion guide for the bundled MCP server: bgeo header / metadata / attribute inspection, frame-sequence scans, USD hierarchy and composition arcs, camera reads, prim-attribute queries, and Value Clip stitching. |

### MCP Server

| Server | Purpose |
| --- | --- |
| `houdini-lite` | Reads `.bgeo.sc` files directly via Blosc decompression and BJSON parsing — **no Houdini installation required**. Inspects USD stages via a bundled `pxr`. |

See [`mcp-server-houdini-lite/README.md`](mcp-server-houdini-lite/README.md) for the full tool reference (inputs, outputs, JSON examples).

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — used by the bundled MCP server.
- A Houdini installation is **not required** for `houdini-lite`. It is required for `houdini-cli` (which drives real Houdini binaries) and is auto-detected by `houdini-locator`.

## Installation

Clone the repo anywhere convenient, then point your AI agent CLI at it. Paths below assume the clone lives at `<repo-root>` (e.g. `~/houdini-tools` or `C:\dev\houdini-tools`).

```bash
git clone https://github.com/chordee/houdini-tools.git
```

The MCP server pulls its own Python dependencies on first run via `uv` — no manual `uv sync` required.

### Gemini CLI

Symlink (Linux/macOS) or junction (Windows) the repo into Gemini's extensions directory:

```bash
ln -s <repo-root> ~/.gemini/extensions/houdini-tools
```

```cmd
mklink /J "%USERPROFILE%\.gemini\extensions\houdini-tools" "<repo-root>"
```

Gemini auto-loads the extension on next launch (manifest: `gemini-extension.json`).

### Claude Code

Add the repo's parent directory as a marketplace in `~/.claude/settings.json`, then enable the plugin:

```json
"extraKnownMarketplaces": {
  "houdini-tools": {
    "source": {
      "source": "directory",
      "path": "<parent-of-repo-root>"
    }
  }
},
"enabledPlugins": {
  "houdini-tools@houdini-tools": true
}
```

Or use the `/plugin` UI inside Claude Code to add a local-directory marketplace pointing at the parent directory. Reload with `/reload-plugins` (or restart Claude Code) — `houdini-lite` MCP server starts automatically.

### Codex

Register the repo as a Codex marketplace and enable the plugin:

```bash
codex plugin marketplace add "<repo-root>"
```

```toml
# ~/.codex/config.toml
[plugins."houdini-tools@houdini-tools"]
enabled = true
```

Codex reads `.mcp.json` to launch the bundled MCP server.

### Manifest reference

| File | Purpose |
| --- | --- |
| `.claude-plugin/plugin.json` | Claude Code plugin manifest (declares MCP server) |
| `.codex-plugin/plugin.json` | Codex plugin manifest |
| `.mcp.json` | Codex MCP server config |
| `gemini-extension.json` | Gemini CLI extension manifest |

## Layout

```text
houdini-tools/
├── .claude-plugin/plugin.json     # Claude Code plugin manifest (with MCP server)
├── .codex-plugin/plugin.json      # Codex plugin manifest
├── .mcp.json                      # Codex MCP server config
├── gemini-extension.json          # Gemini CLI extension manifest (with MCP server)
├── mcp-server-houdini-lite/       # Bundled MCP server (uv project)
└── skills/
    ├── houdini-cli/               # CLI tool reference + workflows
    │   └── references/            # Per-tool deep dives (husk, usdrecord, …)
    ├── houdini-env/               # Environment variables & package configuration
    ├── houdini-locator/           # Houdini install detection scripts
    └── houdini-lite/              # MCP tool usage guide
```

## License

[MIT](LICENSE)
