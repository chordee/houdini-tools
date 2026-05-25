---
name: houdini-locator
description: Locates Houdini installations across Windows and Linux. Honors the HFS environment variable as highest priority when it points at a real install; otherwise scans standard Side Effects Software directories on Windows and /opt/hfs* paths on Linux. Use this when you need to find where Houdini is installed, which versions are available, or the path to hython/houdinifx.
---

# Houdini Locator

This skill provides a reliable way to find all Houdini installation paths without depending on Houdini itself.

## Lookup priority

1. **`HFS` environment variable** — if set and `bin/hython(.exe)` exists under it, that install is reported first under the `[Source: HFS env var]` header. If `HFS` is set but invalid, a one-line warning is printed and the scan continues.
2. **Standard install directory scan** — Windows: `C:\Program Files\Side Effects Software\Houdini *`; Linux: `/opt/hfs*`. Installs already reported via `HFS` are de-duplicated out of this section.
3. **PATH search** (Linux only) — `which -a hython` and `which -a houdinifx` are appended for visibility.

## Workflow

### 1. Run the Detection Script
Run the detection script appropriate for the current operating system:

- **Windows**: `powershell -ExecutionPolicy Bypass -File "$SKILLS_ROOT/houdini-locator/scripts/find-houdini.ps1"`
- **Linux**: `bash $SKILLS_ROOT/houdini-locator/scripts/find-houdini.sh`

### 2. Parse the Results
Analyze the output to identify:
- **Source marker**: an entry prefixed with `[Source: HFS env var]` is the user's explicitly chosen install and should win over scan results when picking a default.
- **Version number**: parsed from the folder basename (`Houdini 20.5.332` → `20.5.332`, `hfs20.5.332` → `20.5.332`). For an `HFS` pointing at a non-standard folder name, version may be reported as `(unknown version)` — the install path and `hython` path are still authoritative.
- **Install root**: the full installation path for each version.
- **Main executables**: full paths to `hython`, `houdini` (Windows) or `houdinifx` (Linux).

### 3. Usage Recommendations
- **Direct execution**: Prefer using the full path to `hython` to avoid environment conflicts.
- **Multiple versions**: Prefer the `HFS`-sourced entry if present; otherwise pick the latest or by requirement.

## Example Requests
- "Find all Houdini installations on my machine"
- "I need the full path to hython"
- "Which Houdini versions are available on this machine?"
