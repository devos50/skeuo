#!/bin/bash
# Puts a relocatable CPython for the app into <dir>: python-build-standalone's stripped install_only build for Apple
# silicon (pinned and checked by SHA-256), without what the pipeline never uses (Tk, IDLE, the test suite, pip and
# ensurepip, headers, static libraries, libpython). The archive is cached in packaging/macos/build/cache.
#
#   packaging/macos/fetch-python.sh <dir>
set -euo pipefail

release=20260929
version=3.12.14
sha256=1bb3e53d231ee2c8881e8daf6426f4dd95bff0dda496af0f3af300357aa998d0
name=cpython-$version+$release-aarch64-apple-darwin-install_only_stripped.tar.gz

if [ $# -ne 1 ]; then
    echo "usage: $0 <dir>" >&2
    exit 2
fi
out=$1
here=$(cd "$(dirname "$0")" && pwd)
cache=$here/build/cache
mkdir -p "$cache"
if [ ! -f "$cache/$name" ]; then
    curl -fsSL --retry 3 -o "$cache/$name.part" \
        "https://github.com/astral-sh/python-build-standalone/releases/download/$release/${name/+/%2B}"
    mv "$cache/$name.part" "$cache/$name"
fi
echo "$sha256  $cache/$name" | shasum -a 256 -c - >/dev/null

rm -rf "$out"
mkdir -p "$out"
tar -xzf "$cache/$name" -C "$out" --strip-components 1  # the archive's top directory is python/

lib=$out/lib/python3.12
rm -rf "$out/include" "$out/share" "$out/lib/pkgconfig" "$out"/lib/libtcl* "$out"/lib/libtk* "$out"/lib/tcl* \
    "$out"/lib/tk* "$out"/lib/itcl* "$out"/lib/thread* \
    "$lib/test" "$lib/idlelib" "$lib/tkinter" "$lib/turtledemo" "$lib/turtle.py" "$lib/ensurepip" "$lib/lib2to3" \
    "$lib/pydoc_data" "$lib"/config-3.12-* "$lib/site-packages"/* "$lib"/lib-dynload/_tkinter* \
    "$lib"/lib-dynload/*_test* "$lib"/lib-dynload/xxlimited*
# The interpreter is linked statically, so libpython (for embedding) goes too, and bin/ keeps one real python3:
# Tauri's resources would copy a symlink as a second 18 MB file.
rm "$out"/lib/libpython*.dylib
mv "$out/bin/python3.12" "$out/python3.tmp"
rm -rf "$out/bin"
mkdir "$out/bin"
mv "$out/python3.tmp" "$out/bin/python3"
find "$out" -name __pycache__ -prune -exec rm -rf {} +
# The app's Python writes no bytecode into the (signed) bundle, so compile the standard library now.
"$out/bin/python3" -I -m compileall -q -j 0 --invalidation-mode unchecked-hash "$lib" >/dev/null
du -sh "$out"
