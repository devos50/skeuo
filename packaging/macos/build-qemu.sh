#!/bin/bash
# Builds the emulator (the emulator/ submodule) for the app: a stripped release qemu-system-arm with only what the
# iPod touch uses. Slirp for Wi-Fi, faad2 and mpg123 for the AMC audio decoder, CoreAudio, VNC (the app draws the
# screen over it, raw encoding) and Cocoa for `skeuo run`'s window. The dependencies come from Homebrew;
# bundle-qemu.sh then copies them next to the binary.
#
#   packaging/macos/build-qemu.sh [build dir]     default: packaging/macos/build/qemu
#
# A build directory that is already configured is only rebuilt; remove it after changing the options below.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
src=$(cd "$here/../../emulator" && pwd)
build=${1:-$here/build/qemu}
export MACOSX_DEPLOYMENT_TARGET=${MACOSX_DEPLOYMENT_TARGET:-13.0}

mkdir -p "$build"
cd "$build"
[ -f build.ninja ] || "$src/configure" \
    --target-list=arm-softmmu \
    --disable-debug-info --enable-strip \
    --enable-slirp --enable-faad2 --enable-mpg123 --enable-cocoa --enable-vnc --audio-drv-list=coreaudio \
    --disable-sdl --disable-gtk --disable-curl --disable-vnc-jpeg --disable-png --disable-zstd --disable-plugins \
    --disable-docs --disable-tools --disable-curses --disable-auth-pam --disable-vnc-sasl --disable-libusb \
    --disable-gnutls --disable-nettle --disable-gcrypt --disable-capstone --disable-libssh --disable-lzo \
    --disable-snappy --disable-bzip2 --disable-lzfse --disable-dmg --disable-usb-redir --disable-spice \
    --disable-opengl --disable-virglrenderer --disable-smartcard --disable-libcbor --disable-tpm --disable-blkio \
    --disable-vmnet --disable-hvf --disable-iconv --disable-guest-agent --disable-rust
make -j"$(sysctl -n hw.ncpu)" qemu-system-arm
strip -x qemu-system-arm
echo "$build/qemu-system-arm"
