#!/bin/bash
# Makes a self-contained emulator for the app: copies qemu-system-arm into <dir>, the dylibs it needs from outside
# macOS (Homebrew's glib, pixman, libslirp, faad2, mpg123 and what they link) into <dir>/lib, and points every
# reference at those copies (@loader_path/lib/... from the binary, @loader_path/... between the dylibs). Then checks
# with otool -L that nothing points outside the bundle and the system, and signs everything ad hoc (rewriting install
# names breaks the signatures, and arm64 runs nothing unsigned); sign.sh signs again for a release. Also copies the
# en-us keymap into <dir>/share/keymaps, where build-qemu.sh's QEMU looks for it: -vnc won't start without one.
#
#   packaging/macos/bundle-qemu.sh <qemu-system-arm> <dir>
set -euo pipefail

if [ $# -ne 2 ]; then
    echo "usage: $0 <qemu-system-arm> <dir>" >&2
    exit 2
fi
qemu=$1
out=$2
src=$(cd "$(dirname "$0")/../../emulator" && pwd)
rm -rf "$out"
mkdir -p "$out/lib" "$out/share/keymaps"
cp "$qemu" "$out/qemu-system-arm"
chmod u+w "$out/qemu-system-arm"
cp "$src/pc-bios/keymaps/en-us" "$out/share/keymaps/"

# The non-system libraries a Mach-O file links, as paths on this Mac (@rpath and @loader_path resolved).
dependencies() {
    local file=$1 dir rpaths name path rpath
    dir=$(dirname "$file")
    rpaths=$(otool -l "$file" | awk '/cmd LC_RPATH/ { getline; getline; print $2 }')
    otool -L "$file" | tail -n +2 | awk '{ print $1 }' | while read -r name; do
        case "$name" in
            /usr/lib/* | /System/*) continue ;;
            @loader_path/*) path=$dir/${name#@loader_path/} ;;
            @rpath/*)
                path=
                for rpath in $rpaths; do
                    rpath=${rpath/@loader_path/$dir}
                    if [ -e "$rpath/${name#@rpath/}" ]; then path=$rpath/${name#@rpath/}; break; fi
                done
                [ -n "$path" ] || { echo "can't resolve $name in $file" >&2; exit 1; }
                ;;
            *) path=$name ;;
        esac
        echo "$name $path"
    done
}

# Copy the dependencies, breadth first: the binary's, then each copied library's.
queue=("$out/qemu-system-arm")
origins=("$qemu")
i=0
while [ $i -lt ${#queue[@]} ]; do
    file=${queue[$i]}
    origin=${origins[$i]}
    i=$((i + 1))
    if [ "$file" = "$out/qemu-system-arm" ]; then prefix=@loader_path/lib; else prefix=@loader_path; fi
    while read -r name path; do
        [ -n "$name" ] || continue
        base=$(basename "$path")
        if [ ! -e "$out/lib/$base" ]; then
            cp "$(realpath "$path")" "$out/lib/$base"
            chmod u+w "$out/lib/$base"
            install_name_tool -id "@loader_path/$base" "$out/lib/$base" 2>/dev/null
            queue+=("$out/lib/$base")
            origins+=("$(realpath "$path")")
        fi
        install_name_tool -change "$name" "$prefix/$base" "$file" 2>/dev/null
    done < <(dependencies "$origin")
done

# Drop the rpaths that point into the build machine (the references no longer use them).
for file in "${queue[@]}"; do
    otool -l "$file" | awk '/cmd LC_RPATH/ { getline; getline; print $2 }' | while read -r rpath; do
        install_name_tool -delete_rpath "$rpath" "$file" 2>/dev/null
    done
done

status=0
for file in "${queue[@]}"; do
    strip -x "$file" 2>/dev/null || true
    if otool -L "$file" | tail -n +2 | awk '{ print $1 }' | grep -vE '^(/usr/lib/|/System/|@loader_path/)'; then
        echo "error: $file still links the libraries above" >&2
        status=1
    fi
    if otool -l "$file" | grep -q /opt/homebrew; then
        echo "error: $file still mentions /opt/homebrew" >&2
        status=1
    fi
    # the oldest macOS each file runs on: Homebrew's bottles target the macOS they were built for
    minos=$(otool -l "$file" | awk '/LC_BUILD_VERSION/ { found = 1 } found && $1 == "minos" { print $2; exit }')
    echo "$(basename "$file"): macOS $minos+"
    codesign --force --sign - "$file" 2>/dev/null
done
exit $status
