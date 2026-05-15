# Houdini Command-Line Tools

Houdini ships with a comprehensive suite of command-line tools for batch processing and pipeline automation. The most commonly used tools are listed below. Tools that have their own dedicated reference page are linked.

## Geometry and 3D Data

- **`ginfo`**: Displays detailed statistics and metadata for geometry files (.bgeo, .obj, etc.).
  - Usage: `ginfo [options] <geometry_file>`
  - Options: `-v` (verbose output), `-p` (print point attributes), `-P` (print primitive attributes), `-d` (print detail attributes), `-V` (print vertex attributes)
- **`gconvert`**: The main tool for converting between Houdini geometry formats.
  - Usage: `gconvert <input_file> <output_file>`
  - Supports: .bgeo, .sc, .obj, .ply, .stl, and more
- **`geodiff`**: Compares two geometry files and reports the differences.
  - Usage: `geodiff [options] <file1> <file2>`
- **`greduce`**: Performs polygon reduction on geometry files from the command line.
  - Usage: `greduce [options] <input> <output>`

## Image and Texture Processing

- **`iinfo`**: Prints technical information about an image file (resolution, channels, etc.).
  - Usage: `iinfo [options] <image_file>`
- **`iconvert`**: Converts images between formats.
  - Usage: `iconvert <input_file> <output_file>`
- **`imaketx`**: Converts standard images into tiled mipmapped textures optimized for rendering.
  - Usage: `imaketx [options] <input> <output>`
- **`idiff`**: Compares two images and highlights visual differences.
  - Usage: `idiff [options] <image1> <image2>`

## Rendering and USD

- **`hrender`**: Command-line tool to render `.hip` files without launching the GUI.
  - Usage: `hrender [options] <hip_file>`
  - Common options: `-d <driver>` (output node to render), `-f <start_frame> -e <end_frame>` (frame range)
- **`husk`**: Standalone command-line renderer for USD files via Hydra (Karma by default, also Arnold, RenderMan, V-Ray, Redshift via their Hydra delegates).
  - Usage: `husk [options] <usd_file> [-o <image_file>]`
  - Full reference: [husk.md](husk.md)
- **`usdrecord`**: Pixar's USD command-line renderer, shipped with Houdini. Uses Hydra delegates (Storm, Karma CPU, Karma XPU, Houdini GL). Recommended to invoke via `hython`.
  - Usage: `hython usdrecord [options] <usd_file> <output_image>`
  - Full reference: [usdrecord.md](usdrecord.md)
- **`usdview`**: Dedicated viewer for inspecting and browsing a USD stage.
  - Usage: `usdview <usd_file>`

## Scene and File Management

- **`hexpand` / `hcollapse`**: Expands a binary `.hip` file into a human-readable text directory (for version control) and collapses it back.
  - Usage: `hexpand <hip_file> <directory>`
  - Usage: `hcollapse <directory> <hip_file>`
- **`hython`**: Houdini's Python interpreter, pre-configured with the `hou` module.
  - Usage: `hython <script.py> [args]`
- **`hscript`**: Launches the command-line HScript interpreter for running scene commands.
  - Usage: `hscript <script.hscript>`
- **`hotl`**: Tool for managing and inspecting Houdini Digital Assets (.hda / .otl).
  - Usage: `hotl [options] <hda_file>`

## Licensing and System

- **`hkey`**: Launches the graphical license administrator.
- **`sesictrl`**: Command-line interface for managing licenses and the `sesinetd` daemon.
- **`hserver`**: Manages the communication proxy between Houdini and the license server.

For more details, see: https://www.sidefx.com/docs/houdini/ref/utils/index.html
