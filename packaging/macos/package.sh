#!/bin/bash
# Builds Skeuo's DMG for Apple silicon in one go: the release emulator with its dylibs (build-qemu.sh,
# bundle-qemu.sh), a standalone Python (fetch-python.sh) and the pipeline as the app's resources, the app
# (`tauri build` with tauri.bundle.json), signed inside out (sign.sh), and the DMG, signed too.
#
#   packaging/macos/package.sh [--unsigned]
#
# Signing is ad hoc unless $SKEUO_SIGN_IDENTITY names a Developer ID certificate. With one, setting
# $SKEUO_NOTARY_PROFILE (a notarytool keychain profile: `xcrun notarytool store-credentials`) also notarizes the DMG
# and staples the ticket. --unsigned leaves the app as the linker signed it, ad hoc, but with no hardened runtime or
# entitlements, for trying the bundle out.
#
# Needs Xcode's command line tools, Node, Rust, and Homebrew's glib, pixman, libslirp, faad2 and mpg123 to build;
# the result needs none of them.
set -euo pipefail

sign=1
if [ "${1:-}" = --unsigned ]; then
    sign=0
elif [ $# -gt 0 ]; then
    echo "usage: $0 [--unsigned]" >&2
    exit 2
fi
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
build=$here/build
stage=$build/stage
identity=${SKEUO_SIGN_IDENTITY:--}

echo "== the emulator"
"$here/build-qemu.sh" "$build/qemu" >"$build/qemu-build.log" 2>&1 || { tail -20 "$build/qemu-build.log"; exit 1; }
rm -rf "$stage"
mkdir -p "$stage"
"$here/bundle-qemu.sh" "$build/qemu/qemu-system-arm" "$stage/qemu"

echo "== Python and the pipeline"
"$here/fetch-python.sh" "$stage/python"
mkdir -p "$stage/pipeline"
rsync -a --exclude __pycache__ "$root/pipeline/skeuo" "$stage/pipeline/"
"$stage/python/bin/python3" -I -m compileall -q --invalidation-mode unchecked-hash "$stage/pipeline" >/dev/null

echo "== the app"
(cd "$root/app" && npm run tauri build -- --bundles app --config "$here/tauri.bundle.json")
app=$root/app/src-tauri/target/release/bundle/macos/Skeuo.app
if [ $sign = 1 ]; then
    "$here/sign.sh" "$app"
fi

echo "== the DMG"
version=$("$stage/python/bin/python3" -I -c 'import json, sys; print(json.load(open(sys.argv[1]))["version"])' \
    "$root/app/src-tauri/tauri.conf.json")
dmg=$build/Skeuo-$version-arm64.dmg
contents=$build/dmg
rm -rf "$contents" "$dmg"
mkdir -p "$contents"
ditto "$app" "$contents/Skeuo.app"
ln -s /Applications "$contents/Applications"
hdiutil create -quiet -volname Skeuo -fs HFS+ -format UDZO -srcfolder "$contents" "$dmg"
rm -rf "$contents"
if [ $sign = 1 ]; then
    codesign --force --sign "$identity" "$dmg"
    if [ "$identity" != - ] && [ -n "${SKEUO_NOTARY_PROFILE:-}" ]; then
        xcrun notarytool submit "$dmg" --keychain-profile "$SKEUO_NOTARY_PROFILE" --wait
        xcrun stapler staple "$dmg"
    fi
fi
du -h "$dmg"
