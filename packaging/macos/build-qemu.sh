#!/bin/bash
# Builds the emulator (the emulator/ submodule) for the app: a stripped release qemu-system-arm with only what the
# iPod touch uses. Slirp for Wi-Fi, faad2 and mpg123 for the AMC audio decoder, CoreAudio, VNC (the app draws the
# screen over it, raw encoding) and Cocoa for `skeuo run`'s window. The dependencies come from Homebrew;
# bundle-qemu.sh then copies them next to the binary.
#
# QEMU finds its data files (the VNC server's keymap, even when nothing asks for one) relative to the binary, from
# where bindir and datadir are under the prefix. Making the data directory bin/share puts it in share/ next to
# qemu-system-arm, where bundle-qemu.sh copies the keymap.
#
#   packaging/macos/build-qemu.sh [build dir]     default: packaging/macos/build/qemu
#
# A build directory configured with the options below is only rebuilt; one configured otherwise starts over.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
src=$(cd "$here/../../emulator" && pwd)
build=${1:-$here/build/qemu}
export MACOSX_DEPLOYMENT_TARGET=${MACOSX_DEPLOYMENT_TARGET:-13.0}

options=(
    --target-list=arm-softmmu --bindir=bin --datadir=bin --with-suffix=share
    --disable-debug-info --enable-strip
    --enable-slirp --enable-faad2 --enable-mpg123 --enable-cocoa --enable-vnc --audio-drv-list=coreaudio
    --disable-sdl --disable-gtk --disable-curl --disable-vnc-jpeg --disable-png --disable-zstd --disable-plugins
    --disable-docs --disable-tools --disable-curses --disable-auth-pam --disable-vnc-sasl --disable-libusb
    --disable-gnutls --disable-nettle --disable-gcrypt --disable-capstone --disable-libssh --disable-lzo
    --disable-snappy --disable-bzip2 --disable-lzfse --disable-dmg --disable-usb-redir --disable-spice
    --disable-opengl --disable-virglrenderer --disable-smartcard --disable-libcbor --disable-tpm --disable-blkio
    --disable-vmnet --disable-hvf --disable-iconv --disable-guest-agent --disable-rust
)
if [ -f "$build/build.ninja" ] && [ "$(cat "$build/skeuo-configure" 2>/dev/null)" != "${options[*]}" ]; then
    rm -rf "$build"
fi
mkdir -p "$build"
cd "$build"
if [ ! -f build.ninja ]; then
    "$src/configure" "${options[@]}"
    echo "${options[*]}" >skeuo-configure
fi
make -j"$(sysctl -n hw.ncpu)" qemu-system-arm
strip -x qemu-system-arm
echo "$build/qemu-system-arm"
