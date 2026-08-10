---
name: houdini-docs-local
description: Use when looking up Houdini documentation — a HOM method signature, a VEX function, an expression function, an hscript command, a node's parameters — and especially when sidefx.com is unreachable, blocked by a studio network, or slow. Also use when the answer must match the installed Houdini version rather than the current release.
---

# Houdini documentation, locally

Every Houdini install carries the whole documentation set as wiki-markup source. Reaching for
`sidefx.com` is the default habit and it is wrong twice over here: it fails behind a studio
firewall, and it answers for the current release rather than the version in front of you.

## The mapping

A docs URL maps to a local archive by its first path segment:

```
https://www.sidefx.com/docs/houdini/<first>/<rest>.html
                                     ↓
$HFS/houdini/help/<first>.zip   →   <rest>.txt
```

```bash
# H is the Houdini install root — the directory holding bin/ and houdini/,
# not the path to hython. Use the houdini-locator skill to find it.
# The :? makes an unset HFS fail here rather than further down: with H empty,
# the single-file read raises a traceback but the search below just returns
# nothing, which reads exactly like "the docs do not mention this".
H="${HFS:?set HFS to the Houdini install root, e.g. /opt/hfs22.0.368}"

# hom/hou/Node.html  →  hom.zip : hou/Node.txt
python -c "import zipfile;print(zipfile.ZipFile(r'$H/houdini/help/hom.zip').read('hou/Node.txt').decode('utf-8','replace'))"
```

Verified against `help`, `nodes`, `hom`, `vex`, `expressions`, `commands` and `ref`. The `.txt`
is the source the HTML is generated from, so it carries the same content — including signatures,
parameter tables and examples.

## Which archive

Counts below are from Houdini 22.0.368 — 47 archives, 10450 documents. Another build will
differ; run the search commands rather than trusting these numbers:

| Archive | Documents | Contents |
|---|---|---|
| `nodes` | 5033 | Every node's reference page, under `sop/`, `lop/`, `dop/`, `vop/`, … |
| `vex` | 1178 | VEX language and functions |
| `hom` | 966 | Python scripting — `hou/Node.txt`, `hou/Geometry.txt`, … |
| `expressions` | 478 | Expression functions |
| `commands` | 442 | HScript commands |
| `tops` | 223 | PDG/TOPs |
| `ref` | 202 | Reference, including `plugins.txt` and the env-var list |
| `solaris` | 73 | Solaris and Karma |
| `help` | 6 | How the help system itself works, including its markup |

## When the path guess misses

Guessing a filename fails often — `solaris/intro.txt` does not exist, the page is `about_lops.txt`.
Search rather than guess again:

```bash
H="${HFS:?set HFS to the Houdini install root}"

# By filename — for a node or class whose page you cannot place
python -c "
import zipfile,glob,os
q='scatter'.lower()
for p in glob.glob(r'$H/houdini/help/*.zip'):
    for n in zipfile.ZipFile(p).namelist():
        if q in n.lower(): print(os.path.basename(p), n)
"

# By content — what you usually want for a method or function name, since
# no file is named after it
python -c "
import zipfile,glob,os
q=b'isEditableInsideLockedHDA'
for p in glob.glob(r'$H/houdini/help/*.zip'):
    z=zipfile.ZipFile(p)
    for n in z.namelist():
        if n.endswith('.txt') and q in z.read(n): print(os.path.basename(p), n)
"
```

## Why this beats the online copy even with a working network

The local set matches the installed build. The online set tracks the current release, so it
documents methods, parameters and nodes that an older install does not have — and it does so
without any indication that the version differs. An answer sourced from `sidefx.com` and applied
to an older Houdini can be confidently wrong in a way that is hard to trace.

Prefer local whenever an install is present. Fall back to the online copy only when there is
none, or when you specifically need the current release's behaviour.
