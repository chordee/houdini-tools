---
name: houdini-node-help
description: Use when writing or editing help documentation for a Houdini node or digital asset — the node help card, the Help tab of Type Properties, or a .txt file under help/nodes/. Also use when help text renders wrong, a parameter's help does not appear beside its parameter, or a help file is not picked up by the help server.
---

# Houdini node help

Houdini node help is not Markdown. It is Houdini's own wiki markup, and the authoritative reference ships with every install — along with 5000+ real examples. Read those before writing.

## Read the shipped docs first

An agent asked to write node help will usually produce something close to correct from memory, and get the details wrong in ways that break rendering. The details are cheap to look up:

```bash
# Adjust the version; use houdini-locator skill to find the install
H="$HFS"   # e.g. D:/Programs/Side Effects Software/Houdini 22.0.368

# Node help specifics: where it goes, file naming, page structure (473 lines)
python -c "import zipfile;print(zipfile.ZipFile(r'$H/houdini/help/help.zip').read('nodes.txt').decode('utf-8','replace'))"

# Full wiki markup reference (1469 lines)
python -c "import zipfile;print(zipfile.ZipFile(r'$H/houdini/help/help.zip').read('format.txt').decode('utf-8','replace'))"

# A real example of the node type you are documenting
python -c "import zipfile;print(zipfile.ZipFile(r'$H/houdini/help/nodes.zip').read('sop/scatter.txt').decode('utf-8','replace'))"
```

Without a local install, the same two documents are online, and so is every node example:

- [Documenting your assets](https://www.sidefx.com/docs/houdini/help/nodes.html) — the online `nodes.txt`, including a style-tips section on writing parameter descriptions that say something
- [Wiki markup reference](https://www.sidefx.com/docs/houdini/help/format.html) — the online `format.txt`
- Append `.txt` to any help URL to get its raw markup: `https://www.sidefx.com/docs/houdini/nodes/sop/scatter.txt`

Prefer the local copies when Houdini is installed — they match the version being authored against, and the online docs track the current release.

Pick the example from the same context as your node — a SOP for a SOP, a LOP for a LOP. Conventions differ between contexts.

## Where the help goes

Two options, per Houdini's own `nodes.txt`:

- **The Help tab of the asset's Type Properties.** Usually the best choice for a digital asset — it travels with the asset.
- **A file under `HOUDINIPATH/help/nodes/<dir>/`**, where `<dir>` is the short category name: `obj`, `sop`, `dop`, `cop`, `out`, `lop`, `top`, `chop`, `vop`, `apex`.

File naming is exact, and wrong names are silently ignored by the help server:

| Node | Filename |
|---|---|
| `bravo` | `bravo.txt` |
| `com.corp::bravo` | `com.corp--bravo.txt` |
| `bravo::2` | `bravo-2.txt` |
| scoped node | `<scope>@<filename>.txt`, slashes in the scope become underscores |

## What agents get wrong from memory

Verified against the 1401 SOP and LOP help files shipped with Houdini 22.0:

| Mistake | Correct | Evidence |
|---|---|---|
| `""Summary.""` | `"""Summary."""` — three quotes | 1308 files use `"""`, none use `""` |
| A `Default:` line under each parameter | Omit it; the default comes from the parameter definition | 11 of 1401 do this |
| `Input 1:` under `@inputs` | Name what the input *is*: `Geometry to Copy:` | Overwhelming convention |
| Namespace folded into `#internal` | `#namespace:` and `#internal:` are separate lines | Every namespaced node |
| `* [Node:sop/x]` in `@related` | `- [Node:sop/x]` | 556 use `-`, 33 use `*` |

**Do not "fix" the order of `= Title =` and the `#directives`.** Both orders are common in shipped files (821 directive-first, 569 title-first). Neither is wrong.

## Page shape

```
= Scatter By Attribute =

#type: node
#context: sop
#namespace: chordee
#internal: scatter_by_attrib
#icon: SOP/scatter
#tags: scatter, points

"""Scatters points across a surface, with density driven by an attribute."""

Longer prose. Link to other nodes with [Scatter|Node:sop/scatter].

@parameters

Attribute Name:
    #id: attribname
    The float attribute that drives local scatter density.

Relax Iterations:
    #id: relaxiters
    Number of relaxation passes. `0` disables relaxation.

@inputs

Surface to scatter on:
    The geometry that receives the scattered points.

@outputs

Scattered points:
    The generated points. No input primitives are passed through.

@related

- [Node:sop/scatter]
- [Node:sop/relax]
```

`#id:` binds a block to the real parameter name so the text appears beside that parameter in the UI. Get it wrong and the help silently detaches — check it against the actual parm names on the asset, not against the label.

Item names sit at column 0 and their descriptions are indented under them; `@related` entries also sit at column 0. Both forms occur in shipped files, so an indented variant is not an error, but unindented is the majority (1115 of 1284 for `@parameters`, 707 of 981 for `@related`).

## Verify before shipping

Open the node's help in Houdini and read it. Rendering failures — an unclosed `"""`, a mis-indented block, a broken `[Node:...]` link — do not raise errors; they silently produce wrong output.
