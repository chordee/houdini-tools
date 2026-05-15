#!/bin/bash

OPT_DIR="/opt"

echo "--- Houdini Installations in $OPT_DIR ---"
found=0
for dir in "$OPT_DIR"/hfs*/; do
    [ -d "$dir" ] || continue
    found=1
    version="${dir##*/hfs}"
    version="${version%/}"
    echo "Version      : $version"
    echo "Install Path : $dir"
    [ -f "${dir}bin/hython" ]    && echo "hython       : ${dir}bin/hython"
    [ -f "${dir}bin/houdinifx" ] && echo "houdinifx    : ${dir}bin/houdinifx"
    echo ""
done
[ "$found" -eq 0 ] && echo "(none found)"

echo "--- PATH Search ---"
which -a hython 2>/dev/null
which -a houdinifx 2>/dev/null
