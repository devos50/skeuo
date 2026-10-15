Continue step 3 of docs/multi-device-plan.md: the iPod touch 1G (S5L8900, n45ap, iPod1,1) machine in the emulator.
Read the plan first. Steps 1 and 2 are done and pushed (Skeuo main b7ee155, qemu-ios `skeuo` 924c6f8dba).

## Decisions since the plan (record them in the plan when you next touch it)

- **Target 1.1.5 first, not 2.x/3.x.** Apple only serves 1.1 to 1.1.5 for iPod1,1 (ipsw.me lists nothing else; 2.x/3.x were
  paid upgrades). The 1G branch also only ever booted 1.1.x. 2.x/3.x come later, from IPSWs users supply.
- The IPSW is downloaded and checked (SHA-1 1b818911316e4248ee01d3ec67f9d39afc3db240):
  `~/Library/Application Support/Skeuo/ipsw/iPod1,1_1.1.5_4B1_Restore.ipsw`. Extract it into its own scratch folder.

## What I learned

- Every firmware file is an **8900 container** (header 0x800; format byte at 7, 3 = encrypted; data size LE at 0xc),
  encrypted AES-128-CBC with zero IV and **key 0x837 = 188458A6D15034DFE386F23B61D43774** (public). Inside is a
  plaintext **Img2** image: 0x400 header (magic "2gmI", type at 4 e.g. 'llbz'/'ibot'/'dtre', data length at 0x10),
  then the data. LLB is iBoot-204.3.16, linked at 0x22000000, entry at data offset 0.
- **The NOR layout** (from the 1G branch's `data/nor_n45ap.bin`, a real dump with LLB and iBoot zeroed out; study
  only, never ship it): SysCfg at 0x4000, an IMG2 superblock at 0x8400 ("2GMI", granule 0x40, image offset 0x410,
  boot block 0), images from 0x10400. Each image header holds its length in granules at 0x18 (0xffffffff in the IPSW).
  In 1.1.x the 8900 container is dropped before LLB/iBoot are written to NOR. Where a real restore writes LLB is
  still unknown; for now LLB goes first in the image list and the machine finds it by tag.
- The 1G branch never ran LLB: it starts a pre-decrypted iBoot at 0x18000000 and patches the bootrom's routine table
  (0x2000008c/0x20000090) to stubs that drive its 8900 engine. Booting without the bootrom is new work.
- Register differences between the chips, found so far:
  - **Timer**: interrupt status at 0x10000 on the S5L8900 (0x118 on the S5L8720), plus a latch at 0xf8 that LLB
    polls and that acknowledges like the status.
  - **Chip ID**: only a revision (2) at the top of 0x4.
  - **I2C** has the same layout on both chips, so it's shared (`hw/i2c/ipod_touch_i2c.c` now builds under
    `CONFIG_S5L`; rename it `s5l_i2c` later).
  - **AES** offsets differ (see the plan).
- **The NOR is SST CFI flash**: LLB sends JEDEC autoselect and looks the IDs up in a table of 9 known chips.

## State of the code

Committed in `emulator/` on branch `skeuo-multi-device`: 15f03bfac8..5fbb206159, the timer and chip ID
properties, I2C and AES under `CONFIG_S5L` (AES with `dma-mask`, `big-endian-words` and readable key/IV/type
registers), and the `iPod-Touch-1G` machine with `s5l8900.clock` and 2 MB of RAM at 0x18000000. Then
(2ad617092f..efb02708ae) the GPIO's `fsel-offset`, the SPI's S5L8900 properties, and the 1G's SPI controllers and LCD
panel, (4b79b3893f) `s5l8900.bootrom` in place of the bootrom, and (5fbb206159) the NAND controller, its ECC
engine and the DMA controllers. The 2G still boots, suspends and resumes (checked on a clone of a 2.1.1 bundle). The
NOR format LLB needs is in the plan ("The 1G's NOR").

## Where it stands

LLB runs from the NOR, checks and decrypts iBoot and starts it at 0x18000000. iBoot reads the LCD panel's ID, sets up
the display, calls the bootrom's USB setup (`s5l8900.bootrom` stands in), finds the NAND (`s5l8900.nand`: 8 banks,
DMA, ECC) and initialises FIL, VFL and FTL, then stops: "[WMR:ERR] no signature or no production format", because
the NAND is empty. It then fails to mount the root filesystem and starts USB recovery mode. iBoot's console is visible
with `pipeline/tools/1g/iboot_console.sh`.

Next: put a filesystem on the NAND in Whimory 2.1's legacy format (see "The 1G's NAND" in the plan): the signature,
the DEVICEINFOBBT pages, the VFL and FTL contexts, and the filesystem through the FTL, presented from a 1.1.x disk
image the way the 2G's NAND model presents VSVFL. openiBoot's vfl/ftl code is the reference for the structures.
Smaller things iBoot prints: "battery voltage error" (the PMU's ADC) and no debug-uarts (an NVRAM on the NOR would
turn the serial console on).

## Tools

- Build: `packaging/macos/build-qemu.sh` (release build in `packaging/macos/build/qemu/`; `emulator/build` only holds
  a failed configure).
- `pipeline/tools/1g/` (untracked):
  - `make_nor_1g.py <extracted ipsw> <out>` builds a test NOR as a restore would leave it: CRCs, flags, the data
    encrypted and both signatures with the emulator's UID key (needs `openssl`).
  - `run1g.sh <nor> <seconds>` runs the machine headless and prints the serial output and a histogram of
    unimplemented accesses.
  - `iboot_console.sh <nor> <seconds>` prints iBoot's console messages (through lldb, breaking on its puts).
  - `dis.py <bin> <base> <start> <end> [arm]` disassembles part of a raw binary (Thumb by default) with Xcode's clang
    and llvm-objdump. There's no capstone, so `-d in_asm` only shows raw bytes.
- To try something in guest memory without a code change: `-device loader,file=<raw>,addr=<addr>,force-raw=on`
  (e.g. stubs at 0x20000000). `-monitor stdio` with `info registers` or `xp` piped in shows where a headless run is.
- Tracing: `-d in_asm,int,unimp -D trace.log`; "Taking exception 4 [Data Abort]" lines carry the DFAR.
- **lldb** works as the debugger: start QEMU with `-gdb tcp::12345 -S`, then `lldb --arch armv6` and
  `gdb-remote 12345`. `-trace 'ipod_touch_aes*'` shows the AES registers; the monitor's `gva2gpa` the page table.
- **Ghidra**: `/iPod Touch 1G/1.1.5/LLB.n45ap.1.1.5.bin` is the 1.1.5 LLB that runs (base 0x22000000), and
  `iBoot.n45ap.1.1.5.bin` next to it the iBoot it loads (base 0x18000000). The older
  `LLB.n45ap.RELEASE` is a different build: its addresses drift and some checks differ. The project `ios_kernel_reverse` has an "iPod Touch 1G" folder with LLB.n45ap.RELEASE,
  bootrom_s5l8900, openiboot.bin, ipt_1g_openiboot.bin, iboot_ram.bin, iBSS.n45ap.RELEASE.dfu.decrypted,
  kernelcache.out, nordump.bin and 1.x userland. Use the `mcp__ghidra__*` tools (or the plugin's HTTP API on
  127.0.0.1:8089). These programs were built against an older SLEIGH revision and only open read-only until they
  are upgraded; Ghidra suggested `python tools/upgrade_project_language.py --apply --folder "/iPod Touch 1G"` (in
  ~/Documents/ghidra-mcp). Ask me before running it, since it rewrites the project. openiBoot is the best reference
  for S5L8900 register layouts.

## Ground rules

- Skeuo ships no Apple code. Use the dump and Apple binaries only to learn the layout.
- Keep the machine contract (emulator `docs/system/arm/ipod-touch.rst`): a 1G option that isn't supported is refused,
  not ignored.
- Commit in reviewable pieces in the emulator. Ask me before pushing.
