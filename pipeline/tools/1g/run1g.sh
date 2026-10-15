#!/bin/sh
# run1g.sh <nor> <seconds> [extra -M options]: runs the 1G machine headless (QEMU from SKEUO_QEMU or the release
# build), leaving serial-1g.log and qemu-1g.log in the current directory, and prints the serial output and a
# histogram of unimplemented accesses.
rm -f serial-1g.log qemu-1g.log
${SKEUO_QEMU:-$(cd "$(dirname "$0")/../../.." && pwd)/packaging/macos/build/qemu/qemu-system-arm} -M iPod-Touch-1G,nor=$1$3 \
  -cpu max -m 128M -display none -serial file:serial-1g.log -monitor none -d unimp,guest_errors -D qemu-1g.log &
pid=$!
sleep "$2"; kill $pid 2>/dev/null; wait $pid 2>/dev/null
echo "--- serial"; head -c 4000 serial-1g.log; echo; echo "--- log ($(wc -l < qemu-1g.log) lines)"; sort qemu-1g.log | uniq -c | sort -rn | head -40
