#!/bin/bash

show_entry() {
    local install_path="$1"
    local version_label="$2"
    echo "--- Houdini $version_label ---"
    echo "Install Path : $install_path"
    [ -f "${install_path}/bin/hython" ]    && echo "hython       : ${install_path}/bin/hython"
    [ -f "${install_path}/bin/houdinifx" ] && echo "houdinifx    : ${install_path}/bin/houdinifx"
    echo ""
}

get_version_label() {
    local base
    base="$(basename "$1")"
    case "$base" in
        hfs*)     echo "${base#hfs}" ;;
        Houdini*) echo "${base#Houdini }" ;;
        *)        echo "(unknown version)" ;;
    esac
}

# Track install roots already printed so HFS and the scan results don't
# list the same install twice.
declare -A seen

# 1. HFS env var takes priority, if it points at a real install.
hfs_resolved=""
if [ -n "$HFS" ]; then
    if [ -f "$HFS/bin/hython" ]; then
        hfs_resolved="$(cd "$HFS" && pwd -P)"
        echo "[Source: HFS env var]"
        show_entry "$hfs_resolved" "$(get_version_label "$hfs_resolved")"
        seen["$hfs_resolved"]=1
    else
        echo "[HFS env var set to '$HFS' but bin/hython not found there — falling back to scan]"
        echo ""
    fi
fi

# 2. Standard /opt/hfs* scan.
OPT_DIR="/opt"
echo "--- Houdini Installations in $OPT_DIR ---"
found=0
for dir in "$OPT_DIR"/hfs*/; do
    [ -d "$dir" ] || continue
    resolved="$(cd "$dir" && pwd -P)"
    [ -n "${seen[$resolved]:-}" ] && continue
    found=1
    show_entry "$resolved" "$(get_version_label "$resolved")"
    seen["$resolved"]=1
done
[ "$found" -eq 0 ] && [ -z "$hfs_resolved" ] && echo "(none found)"

# 3. Anything else on PATH (informational).
echo "--- PATH Search ---"
which -a hython 2>/dev/null
which -a houdinifx 2>/dev/null
