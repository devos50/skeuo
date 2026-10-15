#!/bin/sh
# iboot_console.sh <nor> <seconds> [extra QEMU arguments]: runs the 1G machine under lldb and prints what iBoot 1.1.5
# passes to its puts (0x18017896). iBoot only writes its console to UART0 when the NVRAM variable debug-uarts is
# set, which a test NOR doesn't have. QEMU from SKEUO_QEMU or the release build; NAND=<more -M options> adds e.g.
# nand-disk=disk.img,nand-overlay=overlay.
Q=${SKEUO_QEMU:-$(cd "$(dirname "$0")/../../.." && pwd)/packaging/macos/build/qemu/qemu-system-arm}
nor=$1; t=$2; shift 2
tmp=$(mktemp -d)
$Q -M iPod-Touch-1G,nor=$nor${NAND:+,$NAND} -cpu max -m 128M -display none -serial null -monitor none -gdb tcp::12399 -S "$@" &
qp=$!
cat > "$tmp/cmds" <<'EOC'
gdb-remote 12399
breakpoint set -H -a 0x18017896 -G true -C "memory read -f s -c 1 $r0"
continue
EOC
(sleep "$t"; kill $qp) &
lldb --arch armv6 --batch -s "$tmp/cmds" > "$tmp/out" 2>&1
grep -E '^0x[0-9a-f]+: "' "$tmp/out" | sed 's/^0x[0-9a-f]*: //'
rm -rf "$tmp"
