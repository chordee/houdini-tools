---
name: houdini-locator
description: Locates Houdini installations across Windows and Linux. On Windows scans standard Side Effects Software directories; on Linux scans /opt/hfs* paths. Use this when you need to find where Houdini is installed, which versions are available, or the path to hython/houdinifx.
---

# Houdini Locator

This skill provides a reliable way to find all Houdini installation paths without depending on Houdini itself.

## Workflow

### 1. Run the Detection Script
Run the detection script appropriate for the current operating system:

- **Windows**: `powershell -ExecutionPolicy Bypass -File "$SKILLS_ROOT/houdini-locator/scripts/find-houdini.ps1"`
- **Linux**: `bash $SKILLS_ROOT/houdini-locator/scripts/find-houdini.sh`

### 2. Parse the Results
Analyze the output to identify:
- **Version number**: parsed from the folder name (e.g. `20.5.332`).
- **Install root**: the full installation path for each version.
- **Main executables**: full paths to `hython`, `houdini` (Windows) or `houdinifx` (Linux).

### 3. Usage Recommendations
- **Direct execution**: Prefer using the full path to `hython` to avoid environment conflicts.
- **Multiple versions**: When multiple versions are detected, choose the latest one or select based on requirements.

## Example Requests
- "Find all Houdini installations on my machine"
- "I need the full path to hython"
- "Which Houdini versions are available on this machine?"
