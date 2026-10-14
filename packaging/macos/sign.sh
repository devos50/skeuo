#!/bin/bash
# Signs Skeuo.app inside out: every library and executable in its resources (the emulator's dylibs, Python's
# extension modules and libpython, then QEMU and Python), then the app. All of them get the hardened runtime, and QEMU
# the JIT entitlement (qemu.entitlements). Ad hoc unless $SKEUO_SIGN_IDENTITY names a certificate, e.g.
# "Developer ID Application: … (TEAMID)"; then with a secure timestamp too, as notarization needs.
#
# The hardened runtime only loads libraries signed by the same team, and ad hoc signatures have none, so ad hoc
# QEMU and Python also get com.apple.security.cs.disable-library-validation. A Developer ID build doesn't need it.
#
#   packaging/macos/sign.sh <Skeuo.app>
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "usage: $0 <Skeuo.app>" >&2
    exit 2
fi
app=$1
here=$(cd "$(dirname "$0")" && pwd)
identity=${SKEUO_SIGN_IDENTITY:--}
options=(--force --sign "$identity" --options runtime)
entitlements=$(mktemp -d)
trap 'rm -rf "$entitlements"' EXIT
cp "$here/qemu.entitlements" "$entitlements/qemu.plist"
plutil -create xml1 "$entitlements/python.plist"
if [ "$identity" = - ]; then
    for plist in "$entitlements"/*.plist; do
        /usr/libexec/PlistBuddy -c "Add :com.apple.security.cs.disable-library-validation bool true" "$plist"
    done
else
    options+=(--timestamp)
fi

sign() {
    codesign "$@" 2>&1 | { grep -v "replacing existing signature" >&2 || true; }
    return "${PIPESTATUS[0]}"
}

machos=$(find "$app/Contents/Resources" -type f -print0 | xargs -0 file -h | awk -F: '/Mach-O/ { print $1 }')
# libraries first, then the executables that load them
echo "$machos" | grep -E '\.(dylib|so)$' | while read -r file; do
    sign "${options[@]}" "$file"
done
echo "$machos" | grep -vE '\.(dylib|so)$' | while read -r file; do
    case "$file" in
        */qemu/qemu-system-arm) sign "${options[@]}" --entitlements "$entitlements/qemu.plist" "$file" ;;
        */python/bin/python3) sign "${options[@]}" --entitlements "$entitlements/python.plist" "$file" ;;
        *) sign "${options[@]}" "$file" ;;
    esac
done
sign "${options[@]}" "$app"
codesign --verify --strict --deep "$app"
echo "signed $app ($([ "$identity" = - ] && echo "ad hoc" || echo "$identity"))"
